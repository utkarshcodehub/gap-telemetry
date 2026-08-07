"""
Shared test fixtures.

Sets AUTH_LOCAL_HS256_SECRET *before* any test file imports app.main —
app.settings.get_settings() reads it at import time (fail-fast design),
so this has to happen at conftest collection time, which pytest
guarantees runs before it imports sibling test modules.

Two distinct user fixtures (user_a_token / user_b_token) exist
specifically to make the per-user isolation tests in test_auth.py
possible: they're two different `sub` claims, nothing more.

Dev-minted (HS256) tokens above are fine for anything that only needs to
pass our own get_current_user dependency (/analyze, /roadmap). They are
NOT usable against /analyses: AnalysesStore forwards the bearer token
straight to the real Supabase project's PostgREST, which verifies the
signature against its own key material — a token signed with our
arbitrary local AUTH_LOCAL_HS256_SECRET will never pass that check, and
saved_analyses.user_id has a real FK to auth.users(id) besides. So
real_user_a/real_user_b below are actual signed-in Supabase users
(created once via the Admin API, service-role key) used specifically for
the /analyses isolation tests in test_api_roadmap.py.
"""

import os
import time

import jwt as pyjwt
import pytest
from supabase import create_client

from app.settings import get_settings

TEST_HS256_SECRET = "test-secret-do-not-use-in-production"
os.environ.setdefault("AUTH_LOCAL_HS256_SECRET", TEST_HS256_SECRET)

USER_A_ID = "aaaaaaaa-0000-0000-0000-000000000001"
USER_B_ID = "bbbbbbbb-0000-0000-0000-000000000002"

REAL_USER_A_EMAIL = "test-user-a@gapintel.test"
REAL_USER_B_EMAIL = "test-user-b@gapintel.test"
REAL_TEST_PASSWORD = "gapintel-test-password-not-real-1"


def _service_client():
    """Raw service-role client for test setup/cleanup — bypasses RLS on
    all four tables. Deliberately not built via JobStore: cleanup needs
    to hit saved_analyses too, which JobStore never touches."""
    settings = get_settings()
    return create_client(settings.supabase_url, settings.supabase_service_role_key)


def _truncate_market_data() -> None:
    """Delete-all on postings then skills (posting_skills cascades from
    postings). Safe here because the configured Supabase project is a
    disposable dev/FYP sandbox, confirmed with the user."""
    client = _service_client()
    client.table("postings").delete().gt("id", 0).execute()
    client.table("skills").delete().gt("id", 0).execute()


def _get_or_create_real_user(email: str, password: str) -> dict:
    """Idempotent: create the user if it doesn't exist yet (ignore the
    'already registered' error on repeat runs), then sign in for a real,
    Supabase-verifiable access token + user id."""
    client = _service_client()
    try:
        client.auth.admin.create_user({
            "email": email, "password": password, "email_confirm": True,
        })
    except Exception:
        pass  # already exists — fine, sign-in below is what we actually need

    anon_client = create_client(get_settings().supabase_url, get_settings().supabase_anon_key)
    session = anon_client.auth.sign_in_with_password({"email": email, "password": password})
    return {"token": session.session.access_token, "id": session.user.id}


def _mint(user_id: str, *, expired: bool = False, aud: str = "authenticated") -> str:
    now = int(time.time())
    payload = {
        "sub": user_id,
        "email": f"{user_id[:8]}@example.com",
        "aud": aud,
        "iat": now,
        "exp": (now - 10) if expired else (now + 3600),
    }
    return pyjwt.encode(payload, TEST_HS256_SECRET, algorithm="HS256")


@pytest.fixture
def user_a_token() -> str:
    return _mint(USER_A_ID)


@pytest.fixture
def user_b_token() -> str:
    return _mint(USER_B_ID)


@pytest.fixture
def expired_token() -> str:
    return _mint(USER_A_ID, expired=True)


@pytest.fixture
def wrong_audience_token() -> str:
    return _mint(USER_A_ID, aud="some-other-service")


@pytest.fixture
def auth_headers(user_a_token) -> dict:
    """Default valid auth header — most tests just need *a* logged-in user."""
    return {"Authorization": f"Bearer {user_a_token}"}


@pytest.fixture(scope="session")
def real_user_a() -> dict:
    """A real, signed-in Supabase user — {"token", "id"}. Required for any
    test that goes through AnalysesStore (see module docstring)."""
    return _get_or_create_real_user(REAL_USER_A_EMAIL, REAL_TEST_PASSWORD)


@pytest.fixture(scope="session")
def real_user_b() -> dict:
    return _get_or_create_real_user(REAL_USER_B_EMAIL, REAL_TEST_PASSWORD)


@pytest.fixture
def real_user_a_headers(real_user_a) -> dict:
    return {"Authorization": f"Bearer {real_user_a['token']}"}


@pytest.fixture
def real_user_b_headers(real_user_b) -> dict:
    return {"Authorization": f"Bearer {real_user_b['token']}"}


@pytest.fixture
def clean_saved_analyses(real_user_a, real_user_b):
    """Wipe saved_analyses rows belonging to the two real test users
    before and after each test that uses them, via the service-role
    client (bypasses RLS) — keeps isolation tests independent of
    whatever a previous run left behind."""
    def _wipe():
        client = _service_client()
        for uid in (real_user_a["id"], real_user_b["id"]):
            client.table("saved_analyses").delete().eq("user_id", uid).execute()
    _wipe()
    yield
    _wipe()
