"""Bus bunching: planned headway vs actual arrival gaps."""
from __future__ import annotations

import re
from dataclasses import asdict, dataclass
from datetime import datetime

VALID_STATUSES: tuple[str, ...] = ("bunching", "large_gap", "normal")

# 文句结构正则。阈值/计划值允许与现行配置不同——那是合法的历史快照，
# 只要与行内固化的 gap_min / planned_headway_min 自洽即可。
_SUGGESTION_PATTERNS: dict[str, re.Pattern[str]] = {
    "bunching": re.compile(r"^间隔 (?P<gap>-?\d+(?:\.\d+)?) 分钟低于串车阈值 -?\d+(?:\.\d+)?，建议后车缓行或抽稀。$"),
    "large_gap": re.compile(r"^间隔 (?P<gap>-?\d+(?:\.\d+)?) 分钟超过大间隔阈值 -?\d+(?:\.\d+)?，建议前车减速或加发。$"),
    "normal": re.compile(r"^间隔接近计划 (?P<hw>-?\d+(?:\.\d+)?) 分钟，保持即可。$"),
}


@dataclass
class GapEvent:
    stop_name: str
    earlier_trip: str
    later_trip: str
    gap_min: float
    planned_headway_min: float
    status: str
    suggestion: str


def suggestion_for(status: str, gap_min: float, planned_headway_min: float,
                   bunch_threshold: float, large_threshold: float) -> str:
    """某状态码对应的规范建议文句——写入与漂移判定的唯一基准。"""
    if status == "bunching":
        return f"间隔 {gap_min:.1f} 分钟低于串车阈值 {bunch_threshold}，建议后车缓行或抽稀。"
    if status == "large_gap":
        return f"间隔 {gap_min:.1f} 分钟超过大间隔阈值 {large_threshold}，建议前车减速或加发。"
    if status == "normal":
        return f"间隔接近计划 {planned_headway_min:.1f} 分钟，保持即可。"
    return ""


def imply_status(suggestion: str) -> str | None:
    """从句式反推状态码；文句被改短/改脏到无法辨认时返回 None。"""
    if not suggestion:
        return None
    if "低于串车阈值" in suggestion:
        return "bunching"
    if "超过大间隔阈值" in suggestion:
        return "large_gap"
    if "保持即可" in suggestion:
        return "normal"
    return None


def classify_gap(gap_min: float, planned_headway_min: float, bunch_threshold: float, large_threshold: float) -> tuple[str, str]:
    if gap_min < bunch_threshold:
        status = "bunching"
    elif gap_min > large_threshold:
        status = "large_gap"
    else:
        status = "normal"
    return status, suggestion_for(status, gap_min, planned_headway_min, bunch_threshold, large_threshold)


def _suggestion_self_consistent(status: str, suggestion: str, gap_min: float,
                                planned_headway_min: float) -> bool:
    """文句结构完整，且嵌入的间隔/计划值与行内固化值自洽。

    句中嵌入的阈值不参与比对——历史快照里嵌旧阈值是合法的。
    """
    match = _SUGGESTION_PATTERNS[status].match(suggestion or "")
    if not match:
        return False
    if status == "normal":
        return float(match.group("hw")) == round(float(planned_headway_min), 1)
    return float(match.group("gap")) == round(float(gap_min), 1)


def validate_frozen_pair(status: str, suggestion: str, gap_min: float, planned_headway_min: float) -> None:
    """写入前校验：两列必须同时存在、互相不矛盾、文句结构与行内值自洽。

    任一事件不过关都抛 ValueError，由调用方整批回滚——报告行数不增。
    """
    if not status or not suggestion:
        raise ValueError("分类状态码与建议文句必须同时写入")
    if status not in VALID_STATUSES:
        raise ValueError(f"非法分类状态码: {status!r}")
    implied = imply_status(suggestion)
    if implied is None:
        raise ValueError("建议文句无法对应任何分类状态码")
    if implied != status:
        raise ValueError(f"状态码 {status!r} 与建议文句 {suggestion!r} 互相矛盾")
    if not _suggestion_self_consistent(status, suggestion, gap_min, planned_headway_min):
        raise ValueError("建议文句与行内固化的间隔/计划值不自洽")


def drift_flags(status: str, suggestion: str, gap_min: float, planned_headway_min: float) -> tuple[bool, bool]:
    """读侧漂移判定，只报告、不写回，且绝不按现行阈值重判。

    返回 (文句漂移, 状态漂移)：
    - 文句漂移：文句被改短/改字（句式不符、嵌入的间隔或计划值与行内固化值不符）；
      句中嵌入的阈值与现行配置不同不算漂移——那是合法的历史快照。
    - 状态漂移：状态码被改脏（非法值）或与文句反推出的码矛盾。
    """
    implied = imply_status(suggestion or "")
    status_valid = status in VALID_STATUSES
    # 码被改脏（非法），或码合法却与文句反推出的码矛盾 → 状态漂移
    status_drift = (not status_valid) or (
        implied is not None and status_valid and implied != status
    )
    # 文句不可辨认，或句式/嵌入值与行内固化值不自洽 → 文句漂移
    if implied is None:
        text_drift = True
    else:
        text_drift = not _suggestion_self_consistent(
            implied, suggestion, gap_min, planned_headway_min
        )
    return text_drift, status_drift


def detect_bunching(arrivals: list[dict], planned_headway_min: float, bunch_threshold: float, large_threshold: float) -> list[GapEvent]:
    by_stop: dict[str, list[dict]] = {}
    for a in arrivals:
        by_stop.setdefault(a["stop_name"], []).append(a)
    events: list[GapEvent] = []
    for stop, items in by_stop.items():
        items = sorted(items, key=lambda x: x["actual_arrive"])
        for i in range(1, len(items)):
            prev, cur = items[i - 1], items[i]
            # 先固化为 2 位小数值，分类与文句都基于它——保证写入文句与存储 gap_min 严格自洽
            gap_min = round((cur["actual_arrive"] - prev["actual_arrive"]).total_seconds() / 60.0, 2)
            status, suggestion = classify_gap(gap_min, planned_headway_min, bunch_threshold, large_threshold)
            events.append(GapEvent(stop, prev["trip_no"], cur["trip_no"], gap_min, planned_headway_min, status, suggestion))
    return events


def events_to_dicts(events: list[GapEvent]) -> list[dict]:
    return [asdict(e) for e in events]
