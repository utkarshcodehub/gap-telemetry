"""
Guards against a destructive test run hitting data it must not touch.

The test suite's fixtures delete every row in `postings` and `skills` so that
counts are deterministic. That was tolerable when the only market data was a
synthetic generator that could be re-run at will. It is not tolerable now:

  - The database holds a corpus bought with a **capped monthly API quota**
    (200 requests per billing period, not refillable until it resets). This has
    already been destroyed once, by running the suite after an ingest.
  - If `backend/.env` is ever pointed at a project that matters, the same
    fixtures would delete that project's market tables with no warning at all.

Two independent checks, both of which must pass before anything is deleted:

1. **The target project must be explicitly named.** The project ref parsed from
   `SUPABASE_URL` has to appear in `DESTRUCTIVE_TESTS_ALLOW_REF`. Repointing
   `.env` at a different project therefore *blocks* the suite rather than
   silently wiping it, because the ref no longer matches.

2. **Nothing irreplaceable may be present.** Every non-fixture source in the
   table must be rebuildable from files on disk at zero quota cost. A source
   with no local archive blocks the run.

The logic here is pure so it can be tested without a database; `tests/conftest.py`
supplies the IO.
"""

from __future__ import annotations

import re
from pathlib import Path
from urllib.parse import urlparse

#: Sources the fixtures create themselves. Deleting these is always fine.
FIXTURE_SOURCES = frozenset({"synthetic"})

ALLOW_ENV_VAR = "DESTRUCTIVE_TESTS_ALLOW_REF"


class DestructiveTestBlocked(RuntimeError):
    """Raised instead of deleting data the suite is not cleared to delete."""


def project_ref(supabase_url: str | None) -> str:
    """Extract the project ref from a Supabase URL.

    'https://hhujhpulwxvdzeiqtagn.supabase.co' -> 'hhujhpulwxvdzeiqtagn'
    """
    if not supabase_url:
        return ""
    host = urlparse(supabase_url if "//" in supabase_url
                    else f"https://{supabase_url}").hostname or ""
    return host.split(".")[0] if host else ""


def parse_allowlist(raw: str | None) -> set[str]:
    return {r.strip() for r in (raw or "").split(",") if r.strip()}


def rebuildable_sources(data_dir: Path) -> set[str]:
    """Which non-fixture sources can be restored from disk, for free.

    Deliberately checks for the actual artifacts rather than trusting a flag: a
    source is only safe to delete if the files needed to rebuild it are here
    *now*.
    """
    safe: set[str] = set()
    naukri = data_dir / "raw" / "naukri"
    if naukri.is_dir() and any(naukri.glob("*.zip")):
        safe.add("naukri-cc0-2020q4")
    jsearch = data_dir / "raw" / "jsearch"
    if jsearch.is_dir() and any(jsearch.glob("*.json")):
        safe.add("jsearch")
    return safe


def check_truncate_allowed(
    *,
    supabase_url: str | None,
    allow_env_value: str | None,
    present_sources: set[str],
    rebuildable: set[str],
) -> None:
    """Raise DestructiveTestBlocked unless both checks pass."""
    ref = project_ref(supabase_url)
    allowed = parse_allowlist(allow_env_value)

    if not ref:
        raise DestructiveTestBlocked(
            "SUPABASE_URL is missing or unparseable, so the target project "
            "cannot be identified. Refusing to delete anything."
        )
    if ref not in allowed:
        raise DestructiveTestBlocked(
            f"Refusing to run destructive tests against project '{ref}'.\n"
            f"These fixtures DELETE every row in `postings` and `skills`.\n\n"
            f"If '{ref}' really is a disposable test project, name it explicitly:\n"
            f"    {ALLOW_ENV_VAR}={ref}\n"
            f"in backend/.env. Currently allowed: {sorted(allowed) or 'none'}.\n"
            f"If you did not expect this project, check which SUPABASE_URL "
            f"backend/.env points at before changing anything."
        )

    at_risk = {s for s in present_sources if s not in FIXTURE_SOURCES}
    unrecoverable = sorted(at_risk - rebuildable)
    if unrecoverable:
        raise DestructiveTestBlocked(
            f"Refusing to delete market data that cannot be rebuilt for free.\n"
            f"Unrecoverable source(s) present: {unrecoverable}\n\n"
            f"Some of this corpus was bought with a capped monthly API quota "
            f"that cannot be topped up until the period resets, and it has "
            f"already been lost once this way.\n"
            f"Either restore the local archives it rebuilds from "
            f"(backend/data/raw/...), or export the rows deliberately before "
            f"running the suite."
        )
