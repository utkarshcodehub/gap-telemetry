"""
Token verification, tested directly against the HS256 path (the JWKS/
production path can't be exercised without a live Supabase project — see
core/auth/verify.py's docstring. Both paths run the identical decode +
claim-check logic; only the key material and algorithm differ, so this
suite proves the verification logic itself is correct.
"""

import pytest

from core.auth.verify import AuthError, TokenVerifier
from tests.conftest import TEST_HS256_SECRET, USER_A_ID, _mint


@pytest.fixture
def verifier() -> TokenVerifier:
    return TokenVerifier(hs256_secret=TEST_HS256_SECRET)


def test_valid_token_verifies(verifier, user_a_token):
    user = verifier.verify(user_a_token)
    assert user.id == USER_A_ID
    assert user.email == f"{USER_A_ID[:8]}@example.com"


def test_expired_token_rejected(verifier, expired_token):
    with pytest.raises(AuthError, match="expired"):
        verifier.verify(expired_token)


def test_tampered_signature_rejected(verifier, user_a_token):
    tampered = user_a_token[:-4] + "abcd"
    with pytest.raises(AuthError):
        verifier.verify(tampered)


def test_wrong_secret_rejected(user_a_token):
    other_verifier = TokenVerifier(hs256_secret="a-completely-different-secret")
    with pytest.raises(AuthError):
        other_verifier.verify(user_a_token)


def test_wrong_audience_rejected(verifier, wrong_audience_token):
    with pytest.raises(AuthError, match="audience"):
        verifier.verify(wrong_audience_token)


def test_missing_sub_claim_rejected(verifier):
    import time
    import jwt as pyjwt
    now = int(time.time())
    # a structurally valid, correctly-signed token that simply never
    # got a 'sub' claim — must still be rejected
    bad = pyjwt.encode(
        {"aud": "authenticated", "iat": now, "exp": now + 3600},
        TEST_HS256_SECRET, algorithm="HS256",
    )
    with pytest.raises(AuthError, match="sub"):
        verifier.verify(bad)


def test_verifier_requires_some_key_material():
    with pytest.raises(ValueError):
        TokenVerifier()


def test_two_users_produce_different_ids(verifier):
    token_a = _mint("user-aaa")
    token_b = _mint("user-bbb")
    assert verifier.verify(token_a).id != verifier.verify(token_b).id
