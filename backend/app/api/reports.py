from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session
from app.database import get_db
from app.models.models import Arrival, BunchReport, Line, Trip
from app.services.bunch_engine import detect_bunching
from app.services.report_store import FreezeError, freeze_report, serialize_report

router = APIRouter(prefix="/reports", tags=["reports"])


@router.get("")
def list_reports(line_id: int | None = None, db: Session = Depends(get_db)):
    """报告列表：只展示库内固化的状态码/建议文句两列。"""
    q = select(BunchReport).order_by(BunchReport.id.desc())
    if line_id is not None:
        q = q.where(BunchReport.line_id == line_id)
    rows = db.scalars(q).all()
    return [serialize_report(r) for r in rows]


@router.get("/suggestions")
def suggestions(line_id: int, db: Session = Depends(get_db)):
    """建议页（只读）：取该线路最新一份报告里的异常建议，绝不现场重判。"""
    report = db.scalars(
        select(BunchReport)
        .where(BunchReport.line_id == line_id)
        .order_by(BunchReport.id.desc())
    ).first()
    if report is None:
        return {"line_id": line_id, "report_id": None, "suggestions": []}
    data = serialize_report(report)
    return {
        "line_id": line_id,
        "report_id": report.id,
        "suggestions": [e for e in data["events"] if e["status_code"] != "normal"],
    }


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


@router.get("/{report_id}")
def get_report(report_id: int, db: Session = Depends(get_db)):
    """报告详情（读接口）：与列表、建议页共用同一序列化结果。"""
    report = db.get(BunchReport, report_id)
    if not report:
        raise HTTPException(404, "报告不存在")
    return serialize_report(report)


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
    event_rows = [{
        "stop_name": e.stop_name,
        "earlier_trip": e.earlier_trip,
        "later_trip": e.later_trip,
        "gap_min": e.gap_min,
        "status_code": e.status,
        "suggestion_text": e.suggestion,
    } for e in events]
    try:
        report = freeze_report(db, line=line, stop_name=stop_name or "*", event_rows=event_rows)
    except FreezeError as exc:
        raise HTTPException(400, f"检测结果固化失败：{exc}")
    return serialize_report(report)
