"""
FastAPI dependency: get_current_user.

Apply via `user: AuthUser = Depends(get_current_user)` on any endpoint
that touches personal data. Missing or invalid token -> 401, before the
endpoint body ever runs.

The verifier is built once (module-level singleton), the same pattern
already used for the SkillExtractor in main.py — constructing a fresh
PyJWKClient per request would mean losing its key cache every time,
which defeats the entire point of local JWKS verification.
"""


from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.settings import get_settings
from core.auth.verify import AuthError, AuthUser, TokenVerifier

_bearer_scheme = HTTPBearer(auto_error=False)
_verifier: TokenVerifier | None = None


def get_verifier() -> TokenVerifier:
    global _verifier
    if _verifier is None:
        settings = get_settings()
        _verifier = TokenVerifier(
            jwks_url=settings.supabase_jwks_url,
            hs256_secret=settings.auth_local_hs256_secret,
        )
    return _verifier


async def get_current_user(
    creds: HTTPAuthorizationCredentials | None = Depends(_bearer_scheme),
) -> AuthUser:
    if creds is None:
        raise HTTPException(status_code=401, detail="Missing bearer token")
    try:
        return get_verifier().verify(creds.credentials)
    except AuthError as e:
        raise HTTPException(status_code=401, detail=str(e)) from e
