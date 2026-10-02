"""
HTTP-level tests for /role-fit.

The Role Fit scoring maths is covered in test_match_score.py; this file covers
the *endpoint* — auth, listing lookup, and the GitHub enrichment that was
folded in when the duplicate /role-fit-direct route was removed.

Deliberately does NOT use the `client` fixture from test_api_roadmap.py: that
one truncates and re-ingests the live Supabase market tables, which /role-fit
never reads (it scores against core/match/mock_listings.json). A bare
TestClient keeps these tests fast and leaves market data alone.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

import app.main as main
from core.github_profile.fetcher import GitHubFetchError, GitHubProfile

LISTING_ID = "eve-sde-01"

# Enough text that the resume parser doesn't reject it as a scanned PDF.
RESUME_TEXT = (
    "Utkarsh Raj — Software Engineer. "
    "Built REST APIs with Python and Django. Front-end work in React. "
    "Comfortable with SQL, Git and writing tests."
)


@pytest.fixture
def client(monkeypatch):
    # Force the deterministic template explainer so these tests never make a
    # real Groq call. See the same pattern in test_api_roadmap.py — patching
    # the settings OBJECT matters, because app/main.py builds it at import.
    monkeypatch.setattr(main.settings, "groq_api_key", None)
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    return TestClient(main.app)


def _post(client, headers, **extra):
    return client.post(
        "/role-fit",
        data={"listing_id": LISTING_ID, "resume_text": RESUME_TEXT, **extra},
        headers=headers,
    )


def test_role_fit_requires_auth(client):
    r = _post(client, headers={})
    assert r.status_code == 401


def test_unknown_listing_returns_404(client, auth_headers):
    r = client.post(
        "/role-fit",
        data={"listing_id": "does-not-exist", "resume_text": RESUME_TEXT},
        headers=auth_headers,
    )
    assert r.status_code == 404


def test_role_fit_without_github(client, auth_headers):
    r = _post(client, auth_headers)
    assert r.status_code == 200
    body = r.json()

    assert body["listing_id"] == LISTING_ID
    assert 0 <= body["match_pct"] <= 100
    assert body["verdict"]
    assert body["explanation"]
    # No username supplied -> enrichment is skipped, not attempted.
    assert body["github"]["state"] == "not_requested"
    assert body["github_skills_used"] == []


def test_github_skills_are_merged_into_the_match(client, auth_headers, monkeypatch):
    """A skill proven only by GitHub should count toward the fit score.

    This is the behaviour that used to live solely in the deleted
    /role-fit-direct route.
    """
    before = _post(client, auth_headers).json()

    def fake_fetch(username, extractor, token=None, cache_dir=None):
        assert username == "octocat"
        return GitHubProfile(
            username=username,
            repo_count=7,
            # Required by eve-sde-01 but absent from RESUME_TEXT.
            skills={"React Native": 2, "MERN Stack": 1},
            languages={"JavaScript": 1234},
        )

    monkeypatch.setattr(main, "fetch_github_profile", fake_fetch)
    after = _post(client, auth_headers, github_username="octocat").json()

    assert after["github"]["state"] == "ok"
    assert after["github"]["repos_analysed"] == 7
    assert after["github"]["evidence_used"] is True
    assert after["github_skills_used"] == ["MERN Stack", "React Native"]
    assert after["match_pct"] > before["match_pct"]
    # resume_skills_found reports the resume alone — GitHub skills are
    # reported separately so the two sources stay distinguishable.
    assert "React Native" not in after["resume_skills_found"]


def test_github_failure_degrades_without_failing_the_request(
    client, auth_headers, monkeypatch
):
    def boom(username, extractor, token=None, cache_dir=None):
        raise GitHubFetchError("rate limited")

    monkeypatch.setattr(main, "fetch_github_profile", boom)
    r = _post(client, auth_headers, github_username="octocat")

    assert r.status_code == 200
    gh = r.json()["github"]
    assert gh["state"] == "rate_limited", "classified, not a bare 'skipped'"
    assert gh["evidence_used"] is False
    assert "GITHUB_TOKEN" in gh["message"], "must say how to fix it"
