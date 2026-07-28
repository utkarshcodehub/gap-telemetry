"""
Supabase (Postgres) storage layer.

Two clients, two trust levels — this is the important design decision here:

1. JobStore — market data (postings / skills / posting_skills). Public,
   read-only from the outside, written only by trusted server-side ingest
   (scraper / synthetic generator). Uses the service_role key, which
   bypasses Row-Level Security entirely — appropriate here because this
   process IS the trusted writer, not a stand-in for some external caller.

2. AnalysesStore — saved_analyses (personal data, one row per saved gap
   report). Built fresh per request with the *caller's own* Supabase
   bearer token, not the service_role key. That token is handed straight
   to PostgREST, so Postgres' own Row-Level Security (`auth.uid() =
   user_id`, see supabase/migrations/0001_core_schema.sql) is what
   actually enforces isolation — not application code. A query issued
   with someone else's user_id in it still can't return someone else's
   row, because the database itself won't show it to this token. We also
   keep an explicit `.eq("user_id", ...)` on every query as defense in
   depth (belt-and-suspenders — the same principle the old hand-rolled
   SQLite version used, now backed by a real second enforcement layer).

The GROUP BY / aggregate-join reads (demand-by-skill, postings-by-role)
aren't expressible through PostgREST's query builder, so those are plain
SQL functions (see the migration) called via `.rpc(...)`.
"""

from __future__ import annotations

import json
from dataclasses import dataclass

from supabase import Client, create_client

from app.settings import get_settings


@dataclass(frozen=True)
class PostingRecord:
    source: str
    external_id: str
    title: str
    company: str
    location: str
    experience: str
    salary: str
    description: str
    role_query: str


class JobStore:
    """Admin-privileged: market data only. Never used for saved_analyses."""

    def __init__(self, url: str | None = None, service_role_key: str | None = None):
        can_write = True
        if url is None or service_role_key is None:
            settings = get_settings()
            settings.validate_db_configured()
            url = url or settings.supabase_url
            service_role_key = service_role_key or settings.supabase_service_role_key
            if not service_role_key:
                # Degrade to read-only rather than refuse to start — most of
                # the app (health/roles/market/analyze/roadmap) only reads.
                service_role_key = settings.supabase_anon_key
                can_write = False
        self.client: Client = create_client(url, service_role_key)
        self._can_write = can_write

    # ---------- market data writes ----------

    def _require_write_access(self) -> None:
        if not self._can_write:
            raise RuntimeError(
                "SUPABASE_SERVICE_ROLE_KEY is not set in backend/.env — "
                "read-only mode, can't write market data. Get it from the "
                "Supabase dashboard: Project Settings -> API -> service_role "
                "secret key."
            )

    def insert_posting(self, p: PostingRecord) -> int | None:
        self._require_write_access()
        resp = (
            self.client.table("postings")
            .upsert(
                {
                    "source": p.source,
                    "external_id": p.external_id,
                    "title": p.title,
                    "company": p.company,
                    "location": p.location,
                    "experience": p.experience,
                    "salary": p.salary,
                    "description": p.description,
                    "role_query": p.role_query,
                },
                on_conflict="source,external_id",
                ignore_duplicates=True,
            )
            .execute()
        )
        return resp.data[0]["id"] if resp.data else None

    def upsert_skill(self, canonical: str, category: str) -> int:
        self._require_write_access()
        resp = (
            self.client.table("skills")
            .upsert({"canonical": canonical, "category": category}, on_conflict="canonical")
            .execute()
        )
        return resp.data[0]["id"]

    def link_skill(self, posting_id: int, skill_id: int, count: int) -> None:
        self._require_write_access()
        self.client.table("posting_skills").upsert(
            {"posting_id": posting_id, "skill_id": skill_id, "mention_count": count},
            on_conflict="posting_id,skill_id",
        ).execute()

    def commit(self) -> None:
        """No-op: every call above is already its own committed REST request.
        Kept so ingest.py's store.commit() call doesn't need to change."""

    # ---------- market data reads ----------

    def posting_count(self, role_query: str | None = None) -> int:
        q = self.client.table("postings").select("id", count="exact")
        if role_query:
            q = q.eq("role_query", role_query)
        return q.execute().count or 0

    def roles(self) -> list[dict]:
        resp = self.client.rpc("get_role_counts", {}).execute()
        return [{"role": r["role_query"], "postings": r["postings"]} for r in resp.data]

    def demand(self, role_query: str | None = None) -> list[dict]:
        resp = self.client.rpc("get_demand", {"p_role_query": role_query}).execute()
        return [
            {
                "canonical": r["canonical"],
                "category": r["category"],
                "postings_count": r["postings_count"],
                "demand_pct": float(r["demand_pct"]) if r["demand_pct"] is not None else 0.0,
                "total_mentions": r["total_mentions"],
            }
            for r in resp.data
        ]

    def close(self) -> None:
        """No persistent connection to close (HTTP-based client) — kept so
        existing call sites (`store.close()`) don't need to change."""


class AnalysesStore:
    """Per-user client for saved_analyses, scoped by the caller's own
    Supabase bearer token. RLS does the real enforcement (see module
    docstring) — do not use JobStore's service_role client for this table."""

    def __init__(self, user_token: str, url: str | None = None, anon_key: str | None = None):
        if url is None or anon_key is None:
            settings = get_settings()
            settings.validate_db_configured()
            url = url or settings.supabase_url
            anon_key = anon_key or settings.supabase_anon_key
        self.client: Client = create_client(url, anon_key)
        self.client.postgrest.auth(user_token)

    def save_analysis(
        self, user_id: str, role: str, readiness_score: float, report_json: str
    ) -> int:
        resp = (
            self.client.table("saved_analyses")
            .insert(
                {
                    "user_id": user_id,
                    "role": role,
                    "readiness_score": readiness_score,
                    "report_json": json.loads(report_json),
                }
            )
            .execute()
        )
        return resp.data[0]["id"]

    def list_analyses(self, user_id: str) -> list[dict]:
        resp = (
            self.client.table("saved_analyses")
            .select("id,role,readiness_score,created_at")
            .eq("user_id", user_id)
            .order("created_at", desc=True)
            .execute()
        )
        return resp.data

    def get_analysis(self, analysis_id: int, user_id: str) -> dict | None:
        resp = (
            self.client.table("saved_analyses")
            .select("id,role,readiness_score,report_json,created_at")
            .eq("id", analysis_id)
            .eq("user_id", user_id)
            .execute()
        )
        return resp.data[0] if resp.data else None

    def delete_analysis(self, analysis_id: int, user_id: str) -> bool:
        resp = (
            self.client.table("saved_analyses")
            .delete()
            .eq("id", analysis_id)
            .eq("user_id", user_id)
            .execute()
        )
        return len(resp.data) > 0
