"""报告的原子固化与唯一读出路径。

- freeze_report：检测成功后把每条事件的「状态码」「建议文句」两列在同一
  事务内固化；任一列缺失或码/句互相矛盾（与该间隔应得的分类结果不符）时
  整次写入失败，报告行数不增。
- serialize_report：报告列表、报告详情、建议页三个读出口共用。只呈现库内
  两列，绝不按现行阈值重判或重拼；与写入时阈值快照不符时打漂移标记，不
  静默写回。
"""
from __future__ import annotations

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.models import BunchReport, BunchReportEvent, Line
from app.services.bunch_engine import (
    VALID_STATUS,
    classify_gap,
    render_suggestion,
)


class FreezeError(ValueError):
    """两列缺失或互相矛盾，固化被拒绝（不产生报告行）。"""


def validate_event_row(row: dict, planned_headway_min: float,
                       bunch_threshold: float, large_threshold: float) -> None:
    code = row.get("status_code")
    text = row.get("suggestion_text")
    if not code or not isinstance(code, str):
        raise FreezeError("状态码缺失：状态码与建议文句必须同时写入")
    if not text or not isinstance(text, str):
        raise FreezeError("建议文句缺失：状态码与建议文句必须同时写入")
    if code not in VALID_STATUS:
        raise FreezeError(f"状态码非法：{code!r}")
    gap_min = row["gap_min"]
    expected_code, expected_text = classify_gap(
        gap_min, planned_headway_min, bunch_threshold, large_threshold)
    if code != expected_code:
        raise FreezeError(
            f"状态码 {code!r} 与间隔 {gap_min} 分钟的分类结果 {expected_code!r} 矛盾")
    if text != render_suggestion(code, gap_min, planned_headway_min,
                                 bunch_threshold, large_threshold):
        raise FreezeError("建议文句与状态码互相矛盾，拒绝固化")


def freeze_report(db: Session, *, line: Line, stop_name: str,
                  event_rows: list[dict]) -> BunchReport:
    """原子固化一次检测结果。失败时回滚并抛 FreezeError，不留报告行。"""
    planned = line.planned_headway_min
    bunch = line.bunch_threshold
    large = line.large_threshold
    for row in event_rows:
        validate_event_row(row, planned, bunch, large)

    report = BunchReport(
        line_id=line.id,
        stop_name=stop_name,
        planned_headway_snapshot=planned,
        bunch_threshold_snapshot=bunch,
        large_threshold_snapshot=large,
        events=[
            BunchReportEvent(
                seq=i,
                stop_name=row["stop_name"],
                earlier_trip=row["earlier_trip"],
                later_trip=row["later_trip"],
                gap_min=row["gap_min"],
                status_code=row["status_code"],
                suggestion_text=row["suggestion_text"],
            )
            for i, row in enumerate(event_rows)
        ],
    )
    db.add(report)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise FreezeError("状态码/建议文句两列未同时落库，整次写入失败")
    db.refresh(report)
    return report


def serialize_event(ev: BunchReportEvent, planned_headway_min: float,
                    bunch_threshold: float, large_threshold: float) -> dict:
    # 以「写入时阈值快照 + 库内间隔」重算基准，仅用于比对漂移，绝不回写。
    canonical_code, canonical_text = classify_gap(
        ev.gap_min, planned_headway_min, bunch_threshold, large_threshold)
    return {
        "seq": ev.seq,
        "stop_name": ev.stop_name,
        "earlier_trip": ev.earlier_trip,
        "later_trip": ev.later_trip,
        "gap_min": ev.gap_min,
        "status_code": ev.status_code,
        "suggestion_text": ev.suggestion_text,
        "status_drift": ev.status_code != canonical_code,
        "text_drift": ev.suggestion_text != canonical_text,
    }


def serialize_report(report: BunchReport) -> dict:
    events = [
        serialize_event(
            ev,
            report.planned_headway_snapshot,
            report.bunch_threshold_snapshot,
            report.large_threshold_snapshot,
        )
        for ev in report.events
    ]
    return {
        "id": report.id,
        "line_id": report.line_id,
        "stop_name": report.stop_name,
        "created_at": report.created_at.isoformat() if report.created_at else None,
        "events": events,
        "thresholds": {
            "planned_headway_min": report.planned_headway_snapshot,
            "bunch_threshold": report.bunch_threshold_snapshot,
            "large_threshold": report.large_threshold_snapshot,
        },
    }
