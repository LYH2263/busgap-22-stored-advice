"""原子固化与只读快照的端到端测例（sqlite + TestClient）。

覆盖：
- 种子数据检一次：2/16/8 三类，两漂移标记皆否；
- 只写一列 / 码句互相矛盾：整次写入失败、报告行数不增；
- 库内文句被改短：三处跟库读出 + 「文句漂移」，不静默写回；
- 库内状态码被改脏：三处跟库读出 + 「状态漂移」，不静默写回；
- 放宽串车阈后：旧报告快照不被刷，新检测按新阈写新快照，新旧并存；
- 列表 / 建议页 / 详情三个出口同一条报告码与句一致。
"""
import pytest
from sqlalchemy import select

from app.models.models import BunchReport, BunchReportEvent, Line
from app.services.report_store import FreezeError, freeze_report

BUNCH_PAIR = ("T01", "T02", 2.0)
LARGE_PAIR = ("T02", "T03", 16.0)
NORMAL_PAIR = ("T03", "T04", 8.0)
SEED_STOPS = ["起点站", "市民中心", "火车站", "终点站"]


def find_event(events, pair, stop_name="起点站"):
    earlier, later, gap = pair
    hits = [e for e in events if e["earlier_trip"] == earlier
            and e["later_trip"] == later and e["gap_min"] == gap
            and e["stop_name"] == stop_name]
    assert hits, f"缺少事件 {pair} @ {stop_name}"
    return hits[0]


def report_count(db) -> int:
    return len(db.scalars(select(BunchReport)).all())


def test_seed_detection_two_columns_consistent_no_drift(client):
    res = client.post("/api/reports/run?line_id=1")
    assert res.status_code == 200
    events = res.json()["events"]
    assert len(events) == 4 * 3  # 四个站点 × (2/16/8) 三个间隔

    by_status = {}
    for pair, expected in [(BUNCH_PAIR, "bunching"), (LARGE_PAIR, "large_gap"),
                           (NORMAL_PAIR, "normal")]:
        ev = find_event(events, pair)
        assert ev["status_code"] == expected
        assert ev["suggestion_text"]  # 文句列同时落库、非空
        assert ev["status_drift"] is False
        assert ev["text_drift"] is False
        by_status[expected] = ev

    # B12 对间隔 2、16、8 的分类结果在写入当时保持
    assert "低于串车阈值" in by_status["bunching"]["suggestion_text"]
    assert "超过大间隔阈值" in by_status["large_gap"]["suggestion_text"]
    assert "保持即可" in by_status["normal"]["suggestion_text"]


def test_missing_one_column_fails_whole_write(db_session):
    line = db_session.get(Line, 1)
    before = report_count(db_session)
    good = {"stop_name": "起点站", "earlier_trip": "T01", "later_trip": "T02",
            "gap_min": 2.0, "status_code": "bunching",
            "suggestion_text": "间隔 2.0 分钟低于串车阈值 3.0，建议后车缓行或抽稀。"}

    for bad in [dict(good, suggestion_text=""), dict(good, status_code=""),
                dict(good, suggestion_text=None), dict(good, status_code=None)]:
        with pytest.raises(FreezeError):
            freeze_report(db_session, line=line, stop_name="*", event_rows=[bad])
        db_session.rollback()

    assert report_count(db_session) == before  # 报告行数不增
    assert db_session.scalars(select(BunchReportEvent)).all() == []


def test_code_text_contradiction_fails_whole_write(db_session):
    line = db_session.get(Line, 1)
    bunch_text = "间隔 2.0 分钟低于串车阈值 3.0，建议后车缓行或抽稀。"
    large_text = "间隔 16.0 分钟超过大间隔阈值 15.0，建议前车减速或加发。"
    before = report_count(db_session)

    # 间隔 2 应判 bunching：码写成 normal
    wrong_code = {"stop_name": "起点站", "earlier_trip": "T01", "later_trip": "T02",
                  "gap_min": 2.0, "status_code": "normal", "suggestion_text": bunch_text}
    with pytest.raises(FreezeError):
        freeze_report(db_session, line=line, stop_name="*", event_rows=[wrong_code])
    db_session.rollback()

    # 码正确但文句挂了别的状态的句子
    wrong_text = {"stop_name": "起点站", "earlier_trip": "T01", "later_trip": "T02",
                  "gap_min": 2.0, "status_code": "bunching", "suggestion_text": large_text}
    with pytest.raises(FreezeError):
        freeze_report(db_session, line=line, stop_name="*", event_rows=[wrong_text])
    db_session.rollback()

    assert report_count(db_session) == before


def test_dirty_text_follows_db_with_text_drift_no_writeback(client, db_session):
    report_id = client.post("/api/reports/run?line_id=1").json()["id"]

    # 库内文句被改短（绕过服务层的人为脏数据）
    ev = db_session.scalars(
        select(BunchReportEvent).where(BunchReportEvent.report_id == report_id,
                                       BunchReportEvent.gap_min == 2.0)
    ).first()
    ev.suggestion_text = "文句被改短。"
    db_session.commit()

    detail = client.get(f"/api/reports/{report_id}").json()
    listed = [r for r in client.get("/api/reports?line_id=1").json() if r["id"] == report_id][0]
    sugg = client.get("/api/reports/suggestions?line_id=1").json()["suggestions"]

    for src in [find_event(detail["events"], BUNCH_PAIR),
                find_event(listed["events"], BUNCH_PAIR)]:
        assert src["suggestion_text"] == "文句被改短。"  # 跟库，不重拼
        assert src["text_drift"] is True
        assert src["status_drift"] is False
    tip = find_event(sugg, BUNCH_PAIR)
    assert tip["suggestion_text"] == "文句被改短。"
    assert tip["text_drift"] is True

    # 禁止静默写回：读完之后库内仍是短句子
    db_session.expire_all()
    assert db_session.get(BunchReportEvent, ev.id).suggestion_text == "文句被改短。"


def test_dirty_status_follows_db_with_status_drift_no_writeback(client, db_session):
    report_id = client.post("/api/reports/run?line_id=1").json()["id"]

    # 库内状态码被改脏
    ev = db_session.scalars(
        select(BunchReportEvent).where(BunchReportEvent.report_id == report_id,
                                       BunchReportEvent.gap_min == 2.0)
    ).first()
    ev.status_code = "large_gap"
    db_session.commit()

    detail = client.get(f"/api/reports/{report_id}").json()
    listed = [r for r in client.get("/api/reports?line_id=1").json() if r["id"] == report_id][0]
    sugg = client.get("/api/reports/suggestions?line_id=1").json()["suggestions"]

    for src in [find_event(detail["events"], BUNCH_PAIR),
                find_event(listed["events"], BUNCH_PAIR),
                find_event(sugg, BUNCH_PAIR)]:
        assert src["status_code"] == "large_gap"  # 跟库，不按阈值重判
        assert src["status_drift"] is True
        assert src["text_drift"] is False  # 原串车文句未动，仍与快照一致

    db_session.expire_all()
    assert db_session.get(BunchReportEvent, ev.id).status_code == "large_gap"


def test_relax_threshold_old_snapshot_kept_new_run_new_snapshot(client, db_session):
    # 旧检测：串车阈 3.0，间隔 8 判 normal
    old_id = client.post("/api/reports/run?line_id=1").json()["id"]
    old_normal = find_event(client.get(f"/api/reports/{old_id}").json()["events"], NORMAL_PAIR)
    assert old_normal["status_code"] == "normal"
    assert old_normal["status_drift"] is False and old_normal["text_drift"] is False

    # 放宽串车阈 3.0 → 10.0（间隔 8 将落入串车）
    line = db_session.get(Line, 1)
    line.bunch_threshold = 10.0
    db_session.commit()

    # 旧报告两列不得被新阈刷掉：列表里点开旧份仍是旧快照、无漂移
    rows = client.get("/api/reports?line_id=1").json()
    assert len(rows) == 1
    old_reopened = [r for r in rows if r["id"] == old_id][0]
    assert old_reopened["thresholds"]["bunch_threshold"] == 3.0
    old_ev = find_event(old_reopened["events"], NORMAL_PAIR)
    assert old_ev["status_code"] == "normal"
    assert "保持即可" in old_ev["suggestion_text"]
    assert old_ev["status_drift"] is False and old_ev["text_drift"] is False

    # 再跑一次新检测：按新阈分类，写入并存的新快照
    new_id = client.post("/api/reports/run?line_id=1").json()["id"]
    assert new_id != old_id
    rows = client.get("/api/reports?line_id=1").json()
    assert {r["id"] for r in rows} == {old_id, new_id}  # 新旧两份并存

    new_report = [r for r in rows if r["id"] == new_id][0]
    assert new_report["thresholds"]["bunch_threshold"] == 10.0
    new_ev = find_event(new_report["events"], NORMAL_PAIR)
    assert new_ev["status_code"] == "bunching"
    assert "低于串车阈值 10.0" in new_ev["suggestion_text"]
    assert new_ev["status_drift"] is False and new_ev["text_drift"] is False

    # 点开旧份仍不被新阈污染
    old_detail = client.get(f"/api/reports/{old_id}").json()
    assert find_event(old_detail["events"], NORMAL_PAIR)["status_code"] == "normal"
    assert old_detail["thresholds"]["bunch_threshold"] == 3.0


def test_three_outlets_same_code_and_text(client):
    report_id = client.post("/api/reports/run?line_id=1").json()["id"]

    listed = [r for r in client.get("/api/reports?line_id=1").json() if r["id"] == report_id][0]
    detail = client.get(f"/api/reports/{report_id}").json()
    suggestions = client.get("/api/reports/suggestions?line_id=1").json()["suggestions"]
    assert len(suggestions) == 8  # 每站 1 串车 + 1 大间隔 × 4 站

    for pair in [BUNCH_PAIR, LARGE_PAIR]:
        a = find_event(listed["events"], pair)
        b = find_event(detail["events"], pair)
        c = find_event(suggestions, pair)
        assert a["status_code"] == b["status_code"] == c["status_code"]
        assert a["suggestion_text"] == b["suggestion_text"] == c["suggestion_text"]
        assert a["status_drift"] == b["status_drift"] == c["status_drift"] is False
        assert a["text_drift"] == b["text_drift"] == c["text_drift"] is False
