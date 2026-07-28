"""
Token verification.

Verifies Supabase Auth JWTs. Supabase issues these on sign-up/sign-in and
the frontend attaches them as `Authorization: Bearer <token>`.

Two verification paths, both genuinely supported by Supabase itself:

1. JWKS (production, recommended). Supabase moved to asymmetric signing
   (RSA/ES256) so tokens can be verified LOCALLY against the project's
   public keys — no network call to Supabase on every request, which is
   the whole point (Supabase's own docs flag the old approach's forced
   `getUser()` network round-trip as the thing this replaces). We fetch
   `{SUPABASE_URL}/auth/v1/.well-known/jwks.json` once and cache it via
   PyJWT's PyJWKClient, which re-fetches automatically if a token shows
   up signed with a `kid` we haven't cached yet (e.g. after key rotation).

2. HS256 shared secret (local dev / this test suite). Supabase's legacy
   signing mode — still a real, currently-supported mode, not a fabricated
   test shortcut. Verification logic is otherwise identical: same claim
   checks, same error handling. This is what lets the test suite prove
   the verification logic works without a live Supabase project.

Either way we check: signature validity, expiry, and `aud == "authenticated"`
(the audience Supabase puts on user session tokens — rejecting anything
else stops a token minted for some other purpose being replayed here).
"""

from dataclasses import dataclass

import jwt
from jwt import PyJWKClient

EXPECTED_AUDIENCE = "authenticated"


@dataclass(frozen=True)
class AuthUser:
    id: str            # Supabase user UUID (the `sub` claim) — the value
                        # every per-user DB query must filter on
    email: str | None
    token: str          # the raw bearer token, passed through to Supabase's
                         # PostgREST so its own RLS (auth.uid()) can enforce
                         # per-user isolation natively, not just in our SQL


class AuthError(Exception):
    pass


class TokenVerifier:
    def __init__(self, jwks_url: str | None = None, hs256_secret: str | None = None):
        if not jwks_url and not hs256_secret:
            raise ValueError("TokenVerifier needs jwks_url or hs256_secret")
        self.jwks_url = jwks_url
        self.hs256_secret = hs256_secret
        self._jwks_client: PyJWKClient | None = None

    def _get_jwks_client(self) -> PyJWKClient:
        if self._jwks_client is None:
            self._jwks_client = PyJWKClient(self.jwks_url, cache_keys=True)
        return self._jwks_client

    def verify(self, token: str) -> AuthUser:
        try:
            if self.jwks_url:
                signing_key = self._get_jwks_client().get_signing_key_from_jwt(token)
                payload = jwt.decode(
                    token, signing_key.key,
                    algorithms=["RS256", "ES256"],
                    audience=EXPECTED_AUDIENCE,
                )
            else:
                payload = jwt.decode(
                    token, self.hs256_secret,
                    algorithms=["HS256"],
                    audience=EXPECTED_AUDIENCE,
                )
        except jwt.ExpiredSignatureError as e:
            raise AuthError("Token expired") from e
        except jwt.InvalidAudienceError as e:
            raise AuthError("Token has wrong audience") from e
        except jwt.PyJWTError as e:
            raise AuthError(f"Invalid token: {e}") from e

        sub = payload.get("sub")
        if not sub:
            raise AuthError("Token missing 'sub' claim")
        return AuthUser(id=str(sub), email=payload.get("email"), token=token)
