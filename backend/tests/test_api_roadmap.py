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
    """Ingests via main.get_store() — a fresh JobStore pointed at the same
    real Supabase project the app itself reads from (per .env) — so
    /health, /roles, /market see exactly these 4 postings. Every JobStore
    instance talks to the same physical tables regardless of when it was
    constructed, so this doesn't need to be the exact same Python object
    the route handlers use.

    Note: bare TestClient(main.app) (no `with` block) never triggers the
    @app.on_event("startup") auto-seed handler — Starlette's TestClient
    only runs lifespan/startup when used as a context manager — so there's
    no risk of the 500-posting auto-seed colliding with this fixture's 4
    known postings.

    The limiter is reset per test. /analyze allows 10/minute per client address
    and the whole suite shares one, so without this the suite's own call count
    silently caps how many /analyze tests may exist -- adding an eleventh made an
    unrelated test fail with a 429. Rate limiting is still proven, by the test
    that makes 12 calls inside a single test.
    """
    main.app.state.limiter.reset()
    _truncate_market_data()
    ingest_postings(
        [make_record("1", "Python, Machine Learning, Pandas", role="ml"),
         make_record("2", "Python, Deep Learning, PyTorch", role="ml"),
         make_record("3", "Python, SQL, Docker", role="ml"),
         make_record("4", "Java, Spring Boot", role="backend")],
        main.get_store(), main.EXTRACTOR,
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


def test_roles_reports_market_and_provenance(client):
    """The UI must be able to attribute a demand percentage to its source.

    The corpus mixes an archival Q4 2020 sample with a live feed, and a reader
    who cannot tell them apart cannot judge whether a number describes today's
    market. These strings come from the server so the UI never asserts a
    provenance claim of its own.
    """
    body = client.get("/roles").json()
    assert body["market"] == "IN"

    prov = body["provenance"]
    assert prov, "provenance must never be silently empty when postings exist"
    assert sum(p["postings"] for p in prov) == 4, "the fixture ingested 4 postings"

    entry = next(p for p in prov if p["source"] == "synthetic")
    # A stray fixture row must be labelled as fake, not pass as market data.
    assert "SYNTHETIC" in entry["label"]
    assert entry["live"] is False
    assert {"source", "label", "vintage", "live", "postings"} <= set(entry)


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


def test_analyses_with_dev_token_returns_401_not_500(client, auth_headers):
    """auth_headers is a dev-minted HS256 token — it passes our own
    get_current_user check, but /analyses forwards it straight to the real
    Supabase project's PostgREST, which rejects it. That must surface as a
    clean 401, not an unhandled 500 (see APIError handler in app/main.py)."""
    r = client.get("/analyses", headers=auth_headers)
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
    assert body["github"]["state"] == "not_requested"
    assert body["github"]["evidence_used"] is False


def test_evidence_block_is_present_even_without_a_github_username(client, auth_headers):
    """claimed_readiness needs only the resume and the market, so it is ALWAYS
    computed.

    This was previously optional, which meant an analysis with no GitHub username
    had no claimed number either and the UI fell back to the legacy union gauge --
    the very number the evidence model replaces.
    """
    r = client.post("/analyze", data={
        "role": "ml", "resume_text": "Skills: Python, SQL, Docker and PyTorch",
    }, headers=auth_headers)
    assert r.status_code == 200
    ev = r.json()["evidence"]

    assert ev is not None, "the evidence block must never be omitted"
    assert ev["claimed_readiness"] > 0, "resume claims alone produce a number"
    assert ev["verified_readiness"] == 0.0, "nothing was verified; nothing claimed to be"
    assert ev["repos_analysed"] == 0
    # None, not 0: "nothing to check" and "checked nothing" differ, and a 0 here
    # would read as a failed verification rather than an absent one.
    assert ev["verification_coverage"] is None
    assert ev["assessments"], "every claim still gets a verdict"
    assert {a["verdict"] for a in ev["assessments"]} <= {"UNVERIFIABLE"}


def test_evidence_block_carries_the_legacy_union_for_comparison(client, auth_headers):
    """The pre-evidence-model score stays in the API and out of the product.

    core/gap/baseline.py measures against it, so it has to remain reachable; the
    UI shows it nowhere, because a two-number story only reads clearly with
    exactly two numbers.
    """
    r = client.post("/analyze", data={
        "role": "ml", "resume_text": "Skills: Python, SQL and PyTorch",
    }, headers=auth_headers)
    body = r.json()
    assert body["evidence"]["legacy_union_readiness"] == body["report"]["readiness_score"]


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
    gh = r.json()["github"]
    # Never a bare "skipped": the state must name what failed, and
    # evidence_used must make clear the score had no GitHub input.
    assert gh["state"] in {"user_not_found", "rate_limited", "token_rejected", "error"}
    assert gh["evidence_used"] is False
    assert gh["severity"] in {"warn", "error"}
    assert "skipped" not in gh["message"].lower()


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
    # Patch the live settings object, NOT the env var: app/main.py builds
    # `settings` once at import time, so delenv("GROQ_API_KEY") here would come
    # too late and the route would make a real Groq call — which is exactly the
    # bug this line fixes (the test silently exercised the LLM path instead of
    # the fallback whenever a real key was present in backend/.env).
    monkeypatch.setattr(main.settings, "groq_api_key", None)
    # GroqRoadmapEngine also falls back to os.environ (generator.py), so close
    # that door too — otherwise an exported shell key resurrects the LLM path.
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    r = client.post("/roadmap", json={
        "role": "ml", "resume_skills": ["Python"], "n_weeks": 4,
    }, headers=auth_headers)
    assert r.status_code == 200
    body = r.json()
    assert body["engine"] == "template"
    assert len(body["weeks"]) >= 1


def test_roadmap_with_zero_skills_succeeds(client, auth_headers):
    """A resume that yields no recognized skills is a legitimate "start from
    scratch" state, not a validation error — every market skill in the
    basket becomes a gap. See RoadmapRequest.resume_skills in schemas.py."""
    r = client.post("/roadmap", json={
        "role": "ml", "resume_skills": [], "n_weeks": 2,
    }, headers=auth_headers)
    assert r.status_code == 200


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
