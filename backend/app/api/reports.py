from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.models import Arrival, BunchReport, Line, Trip
from app.services.bunch_engine import detect_bunching, drift_flags, events_to_dicts
from app.services.report_store import save_report

router = APIRouter(prefix="/reports", tags=["reports"])


def _row_to_dict(r: BunchReport) -> dict:
    """库内固化行 → 读接口结构。只展示库内两列，并附漂移标记，绝不重判/重拼。"""
    text_drift, status_drift = drift_flags(
        r.status, r.suggestion, r.gap_min, r.planned_headway_min
    )
    return {
        "stop_name": r.event_stop_name,
        "earlier_trip": r.earlier_trip,
        "later_trip": r.later_trip,
        "gap_min": r.gap_min,
        "planned_headway_min": r.planned_headway_min,
        "status": r.status,
        "suggestion": r.suggestion,
        "text_drift": text_drift,
        "status_drift": status_drift,
    }


@router.get("")
def list_reports(db: Session = Depends(get_db)):
    """报告列表：按 run_id 聚合，逐条只带库内两列与漂移标记。"""
    rows = db.scalars(
        select(BunchReport).order_by(BunchReport.run_id.desc(), BunchReport.id)
    ).all()
    grouped: dict[int, dict] = {}
    for r in rows:
        head = grouped.get(r.run_id)
        if head is None:
            head = {"run_id": r.run_id, "line_id": r.line_id, "stop_scope": r.scope,
                    "created_at": r.created_at.isoformat(), "events": []}
            grouped[r.run_id] = head
        head["events"].append(_row_to_dict(r))
    return list(grouped.values())


@router.post("/run")
def run_detection(line_id: int, stop_name: str | None = None, db: Session = Depends(get_db)):
    line = db.get(Line, line_id)
    if not line:
        raise HTTPException(404, "线路不存在")
    trips = db.scalars(select(Trip).where(Trip.line_id == line_id)).all()
    trip_ids = [t.id for t in trips]
    trip_no_map = {t.id: t.trip_no for t in trips}
    arrivals = db.scalars(select(Arrival).where(Arrival.trip_id.in_(trip_ids))).all()
    payload = [{"stop_name": a.stop_name, "trip_no": trip_no_map[a.trip_id], "actual_arrive": a.actual_arrive}
               for a in arrivals if stop_name is None or a.stop_name == stop_name]
    events = detect_bunching(payload, line.planned_headway_min, line.bunch_threshold, line.large_threshold)
    data = events_to_dicts(events)
    try:
        run_id = save_report(db, line_id, stop_name or "*", data)
    except ValueError as exc:
        raise HTTPException(400, f"报告固化失败，整次写入已回滚: {exc}")
    return {"run_id": run_id, "events": data}


@router.get("/suggestions")
def suggestions(line_id: int, db: Session = Depends(get_db)):
    """建议页只读最近一次检测库内固化的异常行，不触发检测、不按现行阈值重判。"""
    latest_run = db.scalars(
        select(BunchReport.run_id).where(BunchReport.line_id == line_id)
        .order_by(BunchReport.run_id.desc()).limit(1)
    ).first()
    if latest_run is None:
        return {"line_id": line_id, "run_id": None, "suggestions": []}
    rows = db.scalars(
        select(BunchReport).where(BunchReport.run_id == latest_run).order_by(BunchReport.id)
    ).all()
    return {"line_id": line_id, "run_id": latest_run,
            "suggestions": [_row_to_dict(r) for r in rows if r.status in ("bunching", "large_gap")]}


@router.get("/timeline")
def timeline(line_id: int, stop_name: str = "市民中心", db: Session = Depends(get_db)):
    trips = db.scalars(select(Trip).where(Trip.line_id == line_id)).all()
    trip_ids = [t.id for t in trips]
    trip_no_map = {t.id: t.trip_no for t in trips}
    arrivals = sorted(db.scalars(select(Arrival).where(Arrival.trip_id.in_(trip_ids), Arrival.stop_name == stop_name)).all(),
                      key=lambda a: a.actual_arrive)
    if not arrivals:
        return {"stop_name": stop_name, "marks": []}
    t0 = arrivals[0].actual_arrive
    span = max((arrivals[-1].actual_arrive - t0).total_seconds(), 1)
    marks = [{"trip_no": trip_no_map[a.trip_id], "actual_arrive": a.actual_arrive.isoformat(),
              "pct": round((a.actual_arrive - t0).total_seconds() / span * 100, 2)} for a in arrivals]
    return {"stop_name": stop_name, "marks": marks}


@router.get("/{run_id}")
def get_report(run_id: int, db: Session = Depends(get_db)):
    """点开一份报告：原样读库内快照，阈值再怎么放宽也不污染旧份。"""
    rows = db.scalars(
        select(BunchReport).where(BunchReport.run_id == run_id).order_by(BunchReport.id)
    ).all()
    if not rows:
        raise HTTPException(404, "报告不存在")
    first = rows[0]
    return {"run_id": first.run_id, "line_id": first.line_id, "stop_scope": first.scope,
            "created_at": first.created_at.isoformat(),
            "events": [_row_to_dict(r) for r in rows]}
