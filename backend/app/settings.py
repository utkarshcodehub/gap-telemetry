"""
Environment-based settings.

Design decision: fail loudly, not silently.
If neither SUPABASE_URL nor AUTH_LOCAL_HS256_SECRET is configured, the
app refuses to start rather than quietly running with no way to verify
tokens (which would be the kind of misconfiguration that ships an
unauthenticated API to production by accident).

Two supported auth modes, matching Supabase's own dual-support:
  - Production:  SUPABASE_URL set        -> verify against the project's
                  live JWKS endpoint (asymmetric RS256/ES256, the current
                  Supabase-recommended approach — keys fetched and cached
                  locally, no network call needed per request after the
                  first).
  - Local/dev:    AUTH_LOCAL_HS256_SECRET set -> verify against a shared
                  secret (HS256). This is also a real, currently-supported
                  Supabase signing mode (their "legacy" JWT secret), not a
                  fake test-only path — so tests that exercise it are
                  exercising a genuinely supported code path, just via the
                  simpler algorithm.
Both may be set at once (e.g. while migrating); JWKS takes priority.
"""

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # --- Auth: at least one of these two must be set (checked below) ---
    supabase_url: str | None = None
    auth_local_hs256_secret: str | None = None

    # --- Data layer: Supabase Postgres (see core/db/store.py) ---
    # anon key: public, safe to commit-adjacent — used with each user's own
    #   bearer token so Postgres RLS enforces per-user isolation for real.
    # service_role key: SECRET — bypasses RLS, used only for the market-data
    #   admin path (scraper/ingest, public read-only tables). Never send to
    #   the frontend.
    supabase_anon_key: str | None = None
    supabase_service_role_key: str | None = None

    # --- CORS: comma-separated list of allowed origins ---
    cors_origins: str = "http://localhost:5173"

    # --- Uploads ---
    max_upload_mb: int = 5

    # --- Rate limiting (slowapi / `limits` syntax: "N/period") ---
    rate_limit_analyze: str = "10/minute"
    rate_limit_roadmap: str = "10/minute"
    rate_limit_default: str = "60/minute"

    # --- LLM ---
    groq_api_key: str | None = None

    @property
    def supabase_jwks_url(self) -> str | None:
        if not self.supabase_url:
            return None
        return f"{self.supabase_url.rstrip('/')}/auth/v1/.well-known/jwks.json"

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    def validate_auth_configured(self) -> None:
        if not self.supabase_url and not self.auth_local_hs256_secret:
            raise RuntimeError(
                "No auth configured. Set SUPABASE_URL (production, in your "
                "Supabase project's API settings) or AUTH_LOCAL_HS256_SECRET "
                "(local dev only — any random string) in backend/.env. "
                "See .env.example."
            )

    def validate_db_configured(self) -> None:
        """Minimum to run at all: url + anon key (covers every read, and the
        per-user RLS-scoped saved_analyses path — see AnalysesStore). The
        service_role key is only needed for admin writes to market data
        (scraper/ingest); its absence degrades JobStore to read-only rather
        than blocking the app, since most of the app doesn't need it."""
        if not self.supabase_url or not self.supabase_anon_key:
            raise RuntimeError(
                "Supabase data layer not configured. Set SUPABASE_URL and "
                "SUPABASE_ANON_KEY in backend/.env (Project Settings -> API "
                "in the Supabase dashboard)."
            )


def get_settings() -> Settings:
    """Not cached on purpose: keeps this trivially monkeypatchable in tests."""
    settings = Settings()
    settings.validate_auth_configured()
    return settings
