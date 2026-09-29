"""Bus bunching: planned headway vs actual arrival gaps.

分类结果在检测成功写入时原子固化：每条事件的「状态码」(status_code)
与「建议文句」(suggestion_text) 必须同时落库且互相一致，否则整次写入
失败。读出侧（报告列表 / 报告详情 / 建议页）只展示库内这两列，严禁按
现行阈值重判或重拼；与写入时快照不一致时只打漂移标记，不静默写回。
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime

STATUS_BUNCHING = "bunching"
STATUS_LARGE_GAP = "large_gap"
STATUS_NORMAL = "normal"
VALID_STATUS = frozenset({STATUS_BUNCHING, STATUS_LARGE_GAP, STATUS_NORMAL})


@dataclass
class GapEvent:
    stop_name: str
    earlier_trip: str
    later_trip: str
    gap_min: float
    planned_headway_min: float
    status: str
    suggestion: str


def render_suggestion(status: str, gap_min: float, planned_headway_min: float,
                      bunch_threshold: float, large_threshold: float) -> str:
    """按状态码渲染规范建议文句。

    仅用于两个场景：检测写入时校验码/句一致，以及读出时与库内快照比对
    判断漂移。任何读接口都不得用它的返回值替换库内文句。
    """
    if status == STATUS_BUNCHING:
        return f"间隔 {gap_min:.1f} 分钟低于串车阈值 {bunch_threshold}，建议后车缓行或抽稀。"
    if status == STATUS_LARGE_GAP:
        return f"间隔 {gap_min:.1f} 分钟超过大间隔阈值 {large_threshold}，建议前车减速或加发。"
    if status == STATUS_NORMAL:
        return f"间隔接近计划 {planned_headway_min:.1f} 分钟，保持即可。"
    raise ValueError(f"未知状态码: {status!r}")


def classify_gap(gap_min: float, planned_headway_min: float, bunch_threshold: float, large_threshold: float) -> tuple[str, str]:
    if gap_min < bunch_threshold:
        status = STATUS_BUNCHING
    elif gap_min > large_threshold:
        status = STATUS_LARGE_GAP
    else:
        status = STATUS_NORMAL
    return status, render_suggestion(status, gap_min, planned_headway_min, bunch_threshold, large_threshold)


def detect_bunching(arrivals: list[dict], planned_headway_min: float, bunch_threshold: float, large_threshold: float) -> list[GapEvent]:
    by_stop: dict[str, list[dict]] = {}
    for a in arrivals:
        by_stop.setdefault(a["stop_name"], []).append(a)
    events: list[GapEvent] = []
    for stop, items in by_stop.items():
        items = sorted(items, key=lambda x: x["actual_arrive"])
        for i in range(1, len(items)):
            prev, cur = items[i - 1], items[i]
            gap_min = (cur["actual_arrive"] - prev["actual_arrive"]).total_seconds() / 60.0
            gap_min = round(gap_min, 2)
            status, suggestion = classify_gap(gap_min, planned_headway_min, bunch_threshold, large_threshold)
            events.append(GapEvent(stop, prev["trip_no"], cur["trip_no"], gap_min, planned_headway_min, status, suggestion))
    return events


def events_to_dicts(events: list[GapEvent]) -> list[dict]:
    return [asdict(e) for e in events]
