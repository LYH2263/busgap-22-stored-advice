from datetime import datetime
from sqlalchemy import DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.database import Base

class Line(Base):
    __tablename__ = "lines"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    code: Mapped[str] = mapped_column(String(32), unique=True)
    name: Mapped[str] = mapped_column(String(128))
    planned_headway_min: Mapped[float] = mapped_column(Float, default=8.0)
    bunch_threshold: Mapped[float] = mapped_column(Float, default=3.0)
    large_threshold: Mapped[float] = mapped_column(Float, default=15.0)
    trips: Mapped[list["Trip"]] = relationship(back_populates="line")

class Trip(Base):
    __tablename__ = "trips"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    line_id: Mapped[int] = mapped_column(ForeignKey("lines.id"))
    trip_no: Mapped[str] = mapped_column(String(32))
    planned_depart: Mapped[datetime] = mapped_column(DateTime)
    vehicle_no: Mapped[str] = mapped_column(String(32), default="")
    line: Mapped["Line"] = relationship(back_populates="trips")
    arrivals: Mapped[list["Arrival"]] = relationship(back_populates="trip")

class Arrival(Base):
    __tablename__ = "arrivals"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    trip_id: Mapped[int] = mapped_column(ForeignKey("trips.id"))
    stop_name: Mapped[str] = mapped_column(String(64))
    stop_seq: Mapped[int] = mapped_column(Integer)
    actual_arrive: Mapped[datetime] = mapped_column(DateTime)
    trip: Mapped["Trip"] = relationship(back_populates="arrivals")

class BunchReport(Base):
    __tablename__ = "bunch_reports"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    # 一次检测的批次号：同一次 /run 写入的所有事件行共享；报告按它聚合成一份
    run_id: Mapped[int] = mapped_column(Integer, index=True)
    line_id: Mapped[int] = mapped_column(ForeignKey("lines.id"))
    # 本次检测的站点范围："*" 表示全站
    scope: Mapped[str] = mapped_column(String(64))
    # 该事件实际发生的站点
    event_stop_name: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    gap_min: Mapped[float] = mapped_column(Float, default=0.0)
    planned_headway_min: Mapped[float] = mapped_column(Float, default=0.0)
    earlier_trip: Mapped[str] = mapped_column(String(32), default="")
    later_trip: Mapped[str] = mapped_column(String(32), default="")
    # 检测成功时与建议文句一起原子固化；读侧只展示这两列，禁止按现行阈值重判或重拼
    status: Mapped[str] = mapped_column(String(32), default="")
    suggestion: Mapped[str] = mapped_column(Text, default="")
