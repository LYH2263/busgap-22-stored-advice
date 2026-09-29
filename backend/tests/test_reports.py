"""报告固化 / 三口只读 / 漂移标记 / 阈值快照测试。"""
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base, get_db
from app.main import app
from app.models.models import BunchReport, Line
from app.services.report_store import save_report
from app.services.seed import seed_if_empty

engine = create_engine(
    "sqlite://",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
TestingSessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False)


@pytest.fixture()
def client():
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    db = TestingSessionLocal()
    seed_if_empty(db)  # 种子检一次：B12 初始阈值 bunch=3 / large=15
    db.close()

    def _override():
        s = TestingSessionLocal()
        try:
            yield s
        finally:
            s.close()

    app.dependency_overrides[get_db] = _override
    yield TestClient(app)
    app.dependency_overrides.clear()


def _index_events(events):
    return {(e["stop_name"], e["earlier_trip"], e["later_trip"]): e for e in events}


def _bunching_row(db):
    return db.scalars(
        select(BunchReport).where(BunchReport.status == "bunching").limit(1)
    ).first()


def test_seed_consistency(client):
    """种子检一次后：两列齐全、互相一致、两漂移标记均为否。"""
    reports = client.get("/api/reports").json()
    assert len(reports) == 1
    events = reports[0]["events"]
    # 4 个站 × 间隔 2/16/8 三条 = 12 行
    assert len(events) == 12
    statuses = sorted({e["status"] for e in events})
    assert statuses == ["bunching", "large_gap", "normal"]
    for e in events:
        assert e["status"] in ("bunching", "large_gap", "normal")
        assert e["suggestion"]
        assert e["text_drift"] is False
        assert e["status_drift"] is False
    # 间隔 2/16/8 的分类结果
    by_gap = {round(e["gap_min"]): e["status"] for e in events if e["stop_name"] == "起点站"}
    assert by_gap == {2: "bunching", 16: "large_gap", 8: "normal"}


def test_dirty_text_flagged_everywhere(client):
    """库内文句被改短：三处读出仍跟库，带「文句漂移」，不静默改回，状态不漂移。"""
    db = TestingSessionLocal()
    row = _bunching_row(db)
    key = (row.event_stop_name, row.earlier_trip, row.later_trip)
    row_id = row.id
    row.suggestion = "坏句"
    db.commit()
    db.close()

    listed = _index_events(client.get("/api/reports").json()[0]["events"])[key]
    detail = _index_events(client.get("/api/reports/1").json()["events"])[key]
    suggested = _index_events(client.get("/api/reports/suggestions?line_id=1").json()["suggestions"])[key]
    for got in (listed, detail, suggested):
        assert got["suggestion"] == "坏句"        # 跟库，不重拼
        assert got["status"] == "bunching"        # 码未动
        assert got["text_drift"] is True
        assert got["status_drift"] is False

    # 禁止静默写回：库内仍是脏文句
    db = TestingSessionLocal()
    assert db.get(BunchReport, row_id).suggestion == "坏句"
    db.close()


def test_dirty_status_flagged_everywhere(client):
    """状态码被改脏/与文句矛盾：读出跟库并带「状态漂移」，文句不漂移。"""
    db = TestingSessionLocal()
    row = _bunching_row(db)
    key = (row.event_stop_name, row.earlier_trip, row.later_trip)
    row_id = row.id
    original_text = row.suggestion
    row.status = "weird"
    db.commit()
    db.close()

    for payload in (client.get("/api/reports").json()[0]["events"],
                    client.get("/api/reports/1").json()["events"]):
        got = _index_events(payload)[key]
        assert got["status"] == "weird"
        assert got["suggestion"] == original_text
        assert got["status_drift"] is True
        assert got["text_drift"] is False

    # 码与文句互相矛盾（文句是串车句，码却写成 normal）
    db = TestingSessionLocal()
    db.get(BunchReport, row_id).status = "normal"
    db.commit()
    db.close()
    got = _index_events(client.get("/api/reports/1").json()["events"])[key]
    assert got["status"] == "normal"
    assert got["status_drift"] is True
    assert got["text_drift"] is False


def test_relax_threshold_old_snapshot_untouched(client):
    """放宽串车阈后：旧报告两列不被新阈刷掉；再检一次新旧两份并存。"""
    db = TestingSessionLocal()
    line = db.scalars(select(Line)).first()
    line.bunch_threshold = 1.0  # 放宽：间隔 2 不再算串车
    db.commit()
    db.close()

    old = client.get("/api/reports/1").json()
    old_bunch = [e for e in old["events"] if round(e["gap_min"]) == 2]
    assert len(old_bunch) == 4
    for e in old_bunch:
        assert e["status"] == "bunching"                      # 旧快照不被新阈污染
        assert "串车阈值 3.0" in e["suggestion"]              # 句中旧阈值原样保留
        assert e["text_drift"] is False                       # 旧阈值句不算漂移
        assert e["status_drift"] is False

    resp = client.post("/api/reports/run?line_id=1")
    assert resp.status_code == 200
    new_run_id = resp.json()["run_id"]
    assert new_run_id == 2

    reports = client.get("/api/reports").json()
    assert {r["run_id"] for r in reports} == {1, 2}           # 新旧并存

    new = client.get(f"/api/reports/{new_run_id}").json()
    by_gap = {round(e["gap_min"]): e["status"] for e in new["events"] if e["stop_name"] == "起点站"}
    assert by_gap == {2: "normal", 16: "large_gap", 8: "normal"}  # 按新阈分类
    assert not any(e["status"] == "bunching" for e in new["events"])

    # 再点开旧份：仍是旧阈快照
    again = _index_events(client.get("/api/reports/1").json()["events"])
    assert again[("起点站", "T01", "T02")]["status"] == "bunching"
    assert "串车阈值 3.0" in again[("起点站", "T01", "T02")]["suggestion"]


def test_new_detection_writes_new_snapshot(client):
    """新检新快照：行数与状态按新阈，且不覆盖任何旧行。"""
    db = TestingSessionLocal()
    line = db.scalars(select(Line)).first()
    line.bunch_threshold = 1.0
    db.commit()
    old_count = db.scalar(select(func.count()).select_from(BunchReport))
    db.close()

    resp = client.post("/api/reports/run?line_id=1").json()
    assert len(resp["events"]) == 12
    assert sorted({e["status"] for e in resp["events"]}) == ["large_gap", "normal"]

    db = TestingSessionLocal()
    assert db.scalar(select(func.count()).select_from(BunchReport)) == old_count + 12
    assert db.scalar(select(func.count()).select_from(BunchReport).where(BunchReport.run_id == 1, BunchReport.status == "bunching")) == 4
    db.close()


def test_three_views_same_value(client):
    """列表、详情、建议接口三处，同一条报告的码与句必须一致（含标记）。"""
    listed = client.get("/api/reports").json()[0]
    detail = client.get(f"/api/reports/{listed['run_id']}").json()
    suggestions = client.get("/api/reports/suggestions?line_id=1").json()["suggestions"]

    list_idx = _index_events(listed["events"])
    detail_idx = _index_events(detail["events"])
    sug_idx = _index_events(suggestions)
    assert set(list_idx) == set(detail_idx)

    for key, e in list_idx.items():
        d = detail_idx[key]
        assert d["status"] == e["status"]
        assert d["suggestion"] == e["suggestion"]
        assert d["text_drift"] == e["text_drift"]
        assert d["status_drift"] == e["status_drift"]
        if e["status"] in ("bunching", "large_gap"):
            s = sug_idx[key]
            assert s["status"] == e["status"]
            assert s["suggestion"] == e["suggestion"]
            assert s["text_drift"] == e["text_drift"]
            assert s["status_drift"] == e["status_drift"]
    # 建议只含异常行
    assert all(s["status"] in ("bunching", "large_gap") for s in suggestions)
    assert len(suggestions) == 8  # 4 站 × (串车 + 大间隔)


def test_atomic_write_failure_no_row_growth():
    """只写一列 / 两列矛盾 / 文句不自洽：整次写入失败，报告行数不增。"""
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    db = TestingSessionLocal()
    seed_if_empty(db)
    before = db.scalar(select(func.count()).select_from(BunchReport))

    good = {"stop_name": "S", "earlier_trip": "A", "later_trip": "B",
            "gap_min": 2.0, "planned_headway_min": 8.0,
            "status": "bunching",
            "suggestion": "间隔 2.0 分钟低于串车阈值 3.0，建议后车缓行或抽稀。"}

    def expect_rollback(events):
        with pytest.raises(ValueError):
            save_report(db, 1, "*", events)

    expect_rollback([{**good, "suggestion": ""}])               # 只写状态码一列
    expect_rollback([{**good, "status": ""}])                   # 只写文句一列
    expect_rollback([{**good, "status": "normal"}])             # 两列互相矛盾
    expect_rollback([{**good, "suggestion": "间隔 9.9 分钟低于串车阈值 3.0，建议后车缓行或抽稀。"}])
    expect_rollback([{**good, "status": "bogus"}])              # 脏码
    expect_rollback([good, {**good, "status": "normal"}])       # 批中一条坏 → 整批回滚

    assert db.scalar(select(func.count()).select_from(BunchReport)) == before
    db.close()
