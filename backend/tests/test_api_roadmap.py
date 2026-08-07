"""
API + roadmap engine tests.

/analyze and /roadmap now require auth — every call to them below passes
`headers=auth_headers` (a valid token for a fixed test user, "user A").
The two explicit 401 tests below prove the lockdown actually holds when
that header is omitted.
"""

import json

import pytest
from fastapi.testclient import TestClient

import app.main as main
from core.gap.scorer import score_gap
from core.roadmap import generator as rm
from core.roadmap.generator import GroqRoadmapEngine, TemplateRoadmapEngine, generate_roadmap
from ingest import ingest_postings
from tests.conftest import _truncate_market_data
from tests.test_db_ingest import make_record


@pytest.fixture
def client():
    """Ingests straight into main.STORE — the same JobStore singleton the
    app itself reads from (a real Supabase project, per .env) — so
    /health, /roles, /market see exactly these 4 postings. No monkeypatch
    needed: main.py has no get_store() to patch, it's a module-level
    singleton already pointed at real settings.

    Note: bare TestClient(main.app) (no `with` block) never triggers the
    @app.on_event("startup") auto-seed handler — Starlette's TestClient
    only runs lifespan/startup when used as a context manager — so there's
    no risk of the 500-posting auto-seed colliding with this fixture's 4
    known postings.
    """
    _truncate_market_data()
    ingest_postings(
        [make_record("1", "Python, Machine Learning, Pandas", role="ml"),
         make_record("2", "Python, Deep Learning, PyTorch", role="ml"),
         make_record("3", "Python, SQL, Docker", role="ml"),
         make_record("4", "Java, Spring Boot", role="backend")],
        main.STORE, main.EXTRACTOR,
    )
    return TestClient(main.app)


# ---------------- public endpoints (no auth) ----------------

def test_health(client):
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json()["postings_in_db"] == 4


def test_roles(client):
    roles = {x["role"]: x["postings"] for x in client.get("/roles").json()["roles"]}
    assert roles == {"ml": 3, "backend": 1}


def test_market_known_role(client):
    r = client.get("/market/ml")
    assert r.status_code == 200
    demand = {d["canonical"]: d["demand_pct"] for d in r.json()}
    assert demand["Python"] == 100.0


def test_market_unknown_role_404(client):
    assert client.get("/market/astronaut").status_code == 404


# ---------------- auth lockdown itself ----------------

def test_analyze_without_auth_401(client):
    r = client.post("/analyze", data={"role": "ml", "resume_text": "Python"})
    assert r.status_code == 401


def test_roadmap_without_auth_401(client):
    r = client.post("/roadmap", json={"role": "ml", "resume_skills": ["Python"]})
    assert r.status_code == 401


def test_analyze_with_expired_token_401(client, expired_token):
    r = client.post("/analyze", data={"role": "ml", "resume_text": "Python"},
                    headers={"Authorization": f"Bearer {expired_token}"})
    assert r.status_code == 401


def test_analyze_with_malformed_token_401(client):
    r = client.post("/analyze", data={"role": "ml", "resume_text": "Python"},
                    headers={"Authorization": "Bearer not-a-real-jwt"})
    assert r.status_code == 401


# ---------------- protected endpoints (with auth) ----------------

def test_analyze_with_text(client, auth_headers):
    r = client.post("/analyze", data={
        "role": "ml", "resume_text": "Skills: Python, SQL, FastAPI and scikit-learn",
    }, headers=auth_headers)
    assert r.status_code == 200
    body = r.json()
    assert "Python" in body["resume_skills_found"]
    assert body["report"]["readiness_score"] > 0
    assert body["github_status"] == "not_requested"


def test_analyze_requires_input(client, auth_headers):
    r = client.post("/analyze", data={"role": "ml"}, headers=auth_headers)
    assert r.status_code == 422


def test_analyze_github_failure_degrades_not_dies(client, auth_headers, monkeypatch):
    from core.github_profile.fetcher import GitHubFetchError

    def boom(*a, **k):
        raise GitHubFetchError("rate limit")
    monkeypatch.setattr(main, "fetch_github_profile", boom)

    r = client.post("/analyze", data={
        "role": "ml", "resume_text": "Python and SQL", "github_username": "someone",
    }, headers=auth_headers)
    assert r.status_code == 200
    assert "skipped" in r.json()["github_status"]


def test_analyze_rejects_non_pdf_upload(client, auth_headers):
    r = client.post("/analyze", data={"role": "ml"}, headers=auth_headers,
                    files={"resume_file": ("resume.pdf", b"not a real pdf", "application/pdf")})
    assert r.status_code == 422
    assert "%PDF" in r.json()["detail"] or "valid PDF" in r.json()["detail"]


def test_analyze_rejects_oversized_upload(client, auth_headers, monkeypatch):
    monkeypatch.setattr(main, "MAX_UPLOAD_BYTES", 100)  # 100 bytes, trivial to exceed
    big_pdf = b"%PDF-1.4\n" + b"0" * 1000
    r = client.post("/analyze", data={"role": "ml"}, headers=auth_headers,
                    files={"resume_file": ("resume.pdf", big_pdf, "application/pdf")})
    assert r.status_code == 413


def test_roadmap_endpoint_template_fallback(client, auth_headers, monkeypatch):
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    r = client.post("/roadmap", json={
        "role": "ml", "resume_skills": ["Python"], "n_weeks": 4,
    }, headers=auth_headers)
    assert r.status_code == 200
    body = r.json()
    assert body["engine"] == "template"
    assert len(body["weeks"]) >= 1
    assert body["weeks"][0]["skills"]


# ---------------- saved analyses: the actual isolation proof ----------------
#
# These go through AnalysesStore, which forwards the bearer token straight
# to the real Supabase project's PostgREST — so they need real, signed-in
# Supabase users (real_user_a/real_user_b), not the dev-minted HS256
# tokens used elsewhere in this file. See tests/conftest.py's module
# docstring for why. clean_saved_analyses wipes each user's rows before
# and after so runs don't leak into each other.

def test_save_and_list_own_analysis(client, real_user_a_headers, clean_saved_analyses):
    analyze_resp = client.post("/analyze", data={
        "role": "ml", "resume_text": "Python and SQL",
    }, headers=real_user_a_headers).json()

    save_resp = client.post("/analyses", json={
        "role": "ml", "report": analyze_resp["report"],
    }, headers=real_user_a_headers)
    assert save_resp.status_code == 200

    listed = client.get("/analyses", headers=real_user_a_headers).json()
    assert len(listed) == 1
    assert listed[0]["role"] == "ml"


def test_user_b_cannot_see_user_a_saved_analyses(client, real_user_a_headers, real_user_b_headers, clean_saved_analyses):
    analyze_resp = client.post("/analyze", data={
        "role": "ml", "resume_text": "Python and SQL",
    }, headers=real_user_a_headers).json()
    client.post("/analyses", json={"role": "ml", "report": analyze_resp["report"]}, headers=real_user_a_headers)

    listed_as_b = client.get("/analyses", headers=real_user_b_headers).json()
    assert listed_as_b == []  # user A's saved analysis is invisible to user B


def test_user_b_cannot_fetch_user_a_analysis_by_id(client, real_user_a_headers, real_user_b_headers, clean_saved_analyses):
    analyze_resp = client.post("/analyze", data={
        "role": "ml", "resume_text": "Python and SQL",
    }, headers=real_user_a_headers).json()
    saved = client.post("/analyses", json={"role": "ml", "report": analyze_resp["report"]},
                        headers=real_user_a_headers).json()

    r = client.get(f"/analyses/{saved['id']}", headers=real_user_b_headers)
    assert r.status_code == 404  # not 403 — doesn't confirm the row exists


def test_user_b_cannot_delete_user_a_analysis(client, real_user_a_headers, real_user_b_headers, clean_saved_analyses):
    analyze_resp = client.post("/analyze", data={
        "role": "ml", "resume_text": "Python and SQL",
    }, headers=real_user_a_headers).json()
    saved = client.post("/analyses", json={"role": "ml", "report": analyze_resp["report"]},
                        headers=real_user_a_headers).json()

    r = client.delete(f"/analyses/{saved['id']}", headers=real_user_b_headers)
    assert r.status_code == 404
    # and it's still there for its actual owner
    assert client.get(f"/analyses/{saved['id']}", headers=real_user_a_headers).status_code == 200


# ---------------- rate limiting ----------------

def test_roadmap_rate_limit_returns_429(client, auth_headers, monkeypatch):
    monkeypatch.setattr(main.settings, "rate_limit_roadmap", "5/minute")
    # rebuild the limiter's view of the decorated route's limit for this test run
    client.app.state.limiter.reset()
    body = {"role": "ml", "resume_skills": ["Python"], "n_weeks": 2}
    statuses = [client.post("/roadmap", json=body, headers=auth_headers).status_code
                for _ in range(12)]
    assert 429 in statuses


# ---------------- roadmap engines (no API/auth involved) ----------------

MARKET = [
    {"canonical": "Pandas", "category": "data", "demand_pct": 70.0, "postings_count": 7, "total_mentions": 7},
    {"canonical": "Deep Learning", "category": "ml_ai", "demand_pct": 50.0, "postings_count": 5, "total_mentions": 5},
    {"canonical": "Python", "category": "programming_language", "demand_pct": 90.0, "postings_count": 9, "total_mentions": 9},
]


def make_report():
    return score_gap("ml", MARKET, {"Python"})


def test_template_engine_orders_by_demand():
    plan = TemplateRoadmapEngine().generate(make_report(), n_weeks=4)
    assert plan.engine == "template"
    assert "Pandas" in plan.weeks[0].skills


def test_groq_engine_parses_llm_json(monkeypatch):
    llm_payload = {
        "summary": "Focus on data foundations first.",
        "weeks": [{"week": 1, "theme": "Data foundations", "skills": ["Pandas"],
                   "actions": ["Do the 10-minute Pandas tutorial"],
                   "project": "EDA on an F1 dataset with Pandas"}],
    }

    class FakeResp:
        status_code = 200
        def raise_for_status(self): pass
        def json(self):
            return {"choices": [{"message": {"content": "```json\n" + json.dumps(llm_payload) + "\n```"}}]}

    monkeypatch.setattr(rm.requests, "post", lambda *a, **k: FakeResp())
    plan = GroqRoadmapEngine(api_key="test-key").generate(make_report())
    assert plan.engine == "groq"
    assert plan.weeks[0].skills == ["Pandas"]


def test_facade_falls_back_on_groq_failure(monkeypatch):
    def boom(*a, **k):
        raise ConnectionError("network down")
    monkeypatch.setattr(rm.requests, "post", boom)
    plan = generate_roadmap(make_report(), api_key="test-key")
    assert plan.engine == "template"


def test_facade_uses_template_without_key(monkeypatch):
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    plan = generate_roadmap(make_report())
    assert plan.engine == "template"
