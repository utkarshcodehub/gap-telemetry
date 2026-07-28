"""
Shared test fixtures.

Sets AUTH_LOCAL_HS256_SECRET *before* any test file imports app.main —
app.settings.get_settings() reads it at import time (fail-fast design),
so this has to happen at conftest collection time, which pytest
guarantees runs before it imports sibling test modules.

Two distinct user fixtures (user_a_token / user_b_token) exist
specifically to make the per-user isolation tests in test_auth.py
possible: they're two different `sub` claims, nothing more.
"""

import os
import time

import jwt as pyjwt
import pytest

TEST_HS256_SECRET = "test-secret-do-not-use-in-production"
os.environ.setdefault("AUTH_LOCAL_HS256_SECRET", TEST_HS256_SECRET)

USER_A_ID = "aaaaaaaa-0000-0000-0000-000000000001"
USER_B_ID = "bbbbbbbb-0000-0000-0000-000000000002"


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
