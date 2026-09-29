"""报告固化存储：一次检测原子写入 status / suggestion 两列。"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.models import BunchReport
from app.services.bunch_engine import validate_frozen_pair


def next_run_id(db: Session) -> int:
    return int(db.scalar(select(func.coalesce(func.max(BunchReport.run_id), 0))) + 1)


def save_report(db: Session, line_id: int, stop_scope: str, events: list[dict]) -> int:
    """原子固化一次检测：先逐条校验两列齐全且互不矛盾，再整批提交。

    同一次检测的所有事件共享一个 run_id。任一条不过关 → 回滚，
    报告行数不增，抛 ValueError。
    """
    for e in events:
        validate_frozen_pair(
            e["status"], e["suggestion"], e["gap_min"], e["planned_headway_min"],
        )
    run_id = next_run_id(db)
    created_at = datetime.utcnow()
    rows = [
        BunchReport(
            run_id=run_id, line_id=line_id, scope=stop_scope,
            event_stop_name=e["stop_name"], created_at=created_at,
            gap_min=e["gap_min"], planned_headway_min=e["planned_headway_min"],
            earlier_trip=e["earlier_trip"], later_trip=e["later_trip"],
            status=e["status"], suggestion=e["suggestion"],
        )
        for e in events
    ]
    try:
        db.add_all(rows)
        db.flush()
        if rows and any(r.id is None for r in rows):
            raise ValueError("固化行未能取得主键")
        db.commit()
    except Exception:
        db.rollback()
        raise
    return run_id
