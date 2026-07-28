import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scraper"))

from core.db.store import JobStore, PostingRecord
from ingest import ingest_postings
from synthetic_generator import generate  # noqa: E402


def make_record(ext_id: str, desc: str, role: str = "test role") -> PostingRecord:
    return PostingRecord(source="synthetic", external_id=ext_id, title="T", company="C",
                         location="Noida", experience="0-1 Yrs", salary="ND",
                         description=desc, role_query=role)


@pytest.fixture
def store(tmp_path):
    s = JobStore(tmp_path / "test.db")
    yield s
    s.close()


def test_ingest_and_count(store):
    n = ingest_postings([make_record("1", "Python and SQL required"),
                         make_record("2", "Java developer with Spring Boot")], store)
    assert n == 2
    assert store.posting_count() == 2


def test_idempotent_reingest(store):
    recs = [make_record("1", "Python and SQL")]
    assert ingest_postings(recs, store) == 1
    assert ingest_postings(recs, store) == 0
    assert store.posting_count() == 1


def test_demand_from_sql(store):
    ingest_postings([make_record("1", "Python, SQL"), make_record("2", "Python and Docker"),
                     make_record("3", "Java only")], store)
    demand = {d["canonical"]: d for d in store.demand()}
    assert demand["Python"]["demand_pct"] == 66.7
    assert demand["Java"]["demand_pct"] == 33.3


def test_demand_filtered_by_role(store):
    ingest_postings([make_record("1", "Python", role="ml"), make_record("2", "Java", role="backend")], store)
    ml_demand = {d["canonical"] for d in store.demand("ml")}
    assert "Python" in ml_demand
    assert "Java" not in ml_demand


def test_synthetic_generator_deterministic():
    a = generate(count=40, seed=42)
    b = generate(count=40, seed=42)
    assert [r.description for r in a] == [r.description for r in b]
    assert len(a) == 40


def test_synthetic_demand_is_realistic(store):
    recs = generate(count=200, seed=7, roles=["ai ml engineer"])
    ingest_postings(recs, store)
    demand = {d["canonical"]: d["demand_pct"] for d in store.demand()}
    assert demand["Python"] > 80
    assert demand.get("Power BI", 0) < 5


# ---- saved_analyses table basics (full isolation tests live in test_auth.py) ----

def test_save_and_list_analysis(store):
    aid = store.save_analysis("user-1", "ai ml engineer", 42.0, '{"foo": "bar"}')
    assert aid > 0
    listed = store.list_analyses("user-1")
    assert len(listed) == 1
    assert listed[0]["readiness_score"] == 42.0


def test_saved_analysis_isolated_between_users(store):
    store.save_analysis("user-1", "ai ml engineer", 42.0, "{}")
    store.save_analysis("user-2", "data analyst", 70.0, "{}")
    assert len(store.list_analyses("user-1")) == 1
    assert len(store.list_analyses("user-2")) == 1
    assert store.list_analyses("user-1")[0]["role"] == "ai ml engineer"


def test_get_analysis_wrong_user_returns_none(store):
    aid = store.save_analysis("user-1", "ai ml engineer", 42.0, "{}")
    assert store.get_analysis(aid, "user-1") is not None
    assert store.get_analysis(aid, "user-2") is None


def test_delete_analysis_wrong_user_fails(store):
    aid = store.save_analysis("user-1", "ai ml engineer", 42.0, "{}")
    assert store.delete_analysis(aid, "user-2") is False
    assert store.delete_analysis(aid, "user-1") is True
