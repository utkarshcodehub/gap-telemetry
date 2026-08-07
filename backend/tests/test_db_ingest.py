import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scraper"))

from core.db.store import JobStore, PostingRecord
from ingest import ingest_postings
from synthetic_generator import generate  # noqa: E402
from tests.conftest import _truncate_market_data


def make_record(ext_id: str, desc: str, role: str = "test role") -> PostingRecord:
    return PostingRecord(source="synthetic", external_id=ext_id, title="T", company="C",
                         location="Noida", experience="0-1 Yrs", salary="ND",
                         description=desc, role_query=role)


@pytest.fixture
def store():
    """Real JobStore against the Supabase project configured in .env,
    truncated first so each test starts from a known-empty market-data
    table set. saved_analyses is a separate concern (AnalysesStore, see
    test_api_roadmap.py's isolation section) — not touched here."""
    _truncate_market_data()
    s = JobStore()
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
    # 40, not 200: each posting is one insert_posting call plus an
    # upsert_skill+link_skill round trip per extracted skill — 200 would
    # mean thousands of real HTTP calls for one test.
    recs = generate(count=40, seed=7, roles=["ai ml engineer"])
    ingest_postings(recs, store)
    demand = {d["canonical"]: d["demand_pct"] for d in store.demand()}
    assert demand["Python"] > 80
    assert demand.get("Power BI", 0) < 5

# saved_analyses (AnalysesStore, not JobStore) isolation tests live in
# test_api_roadmap.py's "saved analyses" section — they exercise the real
# /analyses HTTP routes end-to-end with real signed-in Supabase users,
# which is both more realistic and the only way to actually trigger RLS.
