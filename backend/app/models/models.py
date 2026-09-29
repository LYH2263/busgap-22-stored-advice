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
    line_id: Mapped[int] = mapped_column(ForeignKey("lines.id"))
    stop_name: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    # 写入时刻的阈值快照：历史报告不随后续阈值调整而改变
    planned_headway_snapshot: Mapped[float] = mapped_column(Float, default=8.0)
    bunch_threshold_snapshot: Mapped[float] = mapped_column(Float, default=3.0)
    large_threshold_snapshot: Mapped[float] = mapped_column(Float, default=15.0)
    events: Mapped[list["BunchReportEvent"]] = relationship(
        back_populates="report", cascade="all, delete-orphan", order_by="BunchReportEvent.seq")

class BunchReportEvent(Base):
    """检测成功写入时原子固化的分类结果。

    status_code 与 suggestion_text 两列均 NOT NULL：缺任一列整次写入失败；
    两列内容还必须在同一事务内通过码/句一致性校验。
    """
    __tablename__ = "bunch_report_events"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    report_id: Mapped[int] = mapped_column(ForeignKey("bunch_reports.id"))
    seq: Mapped[int] = mapped_column(Integer)
    stop_name: Mapped[str] = mapped_column(String(64))
    earlier_trip: Mapped[str] = mapped_column(String(32))
    later_trip: Mapped[str] = mapped_column(String(32))
    gap_min: Mapped[float] = mapped_column(Float)
    status_code: Mapped[str] = mapped_column(String(32), nullable=False)
    suggestion_text: Mapped[str] = mapped_column(Text, nullable=False)
    report: Mapped["BunchReport"] = relationship(back_populates="events")
