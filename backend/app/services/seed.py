from datetime import datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.models import Arrival, BunchReport, Line, Trip
from app.services.bunch_engine import detect_bunching, events_to_dicts
from app.services.report_store import save_report


def seed_if_empty(db: Session) -> None:
    if (db.scalar(select(func.count()).select_from(Line)) or 0) > 0:
        return
    base = datetime(2026, 9, 17, 7, 0, 0)
    line = Line(code="B12", name="城东环线", planned_headway_min=8.0, bunch_threshold=3.0, large_threshold=15.0)
    db.add(line)
    db.flush()
    specs = [("T01", "粤A1001", 0), ("T02", "粤A1002", 2), ("T03", "粤A1003", 18), ("T04", "粤A1004", 26)]
    stops = ["起点站", "市民中心", "火车站", "终点站"]
    for trip_no, vehicle, offset in specs:
        trip = Trip(line_id=line.id, trip_no=trip_no, planned_depart=base + timedelta(minutes=offset), vehicle_no=vehicle)
        db.add(trip)
        db.flush()
        for seq, stop in enumerate(stops):
            arrive = base + timedelta(minutes=offset + seq * 6)
            if stop == "市民中心" and trip_no == "T02":
                arrive = base + timedelta(minutes=8)
            if stop == "火车站" and trip_no == "T03":
                arrive = base + timedelta(minutes=30)
            db.add(Arrival(trip_id=trip.id, stop_name=stop, stop_seq=seq, actual_arrive=arrive))
    db.flush()
    # 种子检一次：用初始阈值把分类状态码与建议文句固化成历史快照。
    # 之后即便放宽阈值，这份快照的两列也不会被重刷。
    trips = db.scalars(select(Trip).where(Trip.line_id == line.id)).all()
    trip_no_map = {t.id: t.trip_no for t in trips}
    arrivals = db.scalars(select(Arrival).join(Trip, Arrival.trip_id == Trip.id).where(Trip.line_id == line.id)).all()
    payload = [{"stop_name": a.stop_name, "trip_no": trip_no_map[a.trip_id], "actual_arrive": a.actual_arrive}
               for a in arrivals]
    events = detect_bunching(payload, line.planned_headway_min, line.bunch_threshold, line.large_threshold)
    save_report(db, line.id, "*", events_to_dicts(events))
