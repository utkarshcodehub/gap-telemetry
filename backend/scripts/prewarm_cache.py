"""
Warm the GitHub response cache before a demo.

    cd backend
    python scripts/prewarm_cache.py utkarshcodehub
    python scripts/prewarm_cache.py utkarshcodehub --check    # report only

Why this exists. /analyze makes TWO GitHub passes -- the evidence collector and the
legacy README-keyword fetcher that feeds the pre-evidence-model score -- and a cold
run costs roughly 15 seconds and ~24 requests against a rate limit shared by every
analysis. Warm, the same run costs about 1.3 seconds and nothing. Warming only one
of the two passes is the easy mistake: it looks fixed, and the demo still stalls.

THE CACHE EXPIRES AFTER 24 HOURS. `--check` tells you how much life is left, so
"is the demo ready" is a question you can answer rather than hope about.

The cache is per-machine (it lives under the gitignored backend/data/), so a demo
from a different laptop starts cold no matter what was warmed here.
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.settings import get_settings  # noqa: E402
from core.evidence.github import (  # noqa: E402
    GitHubClient,
    RequestBudget,
    collect_profile,
    evidence_from_profile,
)
from core.extraction.extractor import SkillExtractor  # noqa: E402
from core.github_profile.fetcher import GitHubFetchError, fetch_github_profile  # noqa: E402
from core.http_cache import DEFAULT_TTL_SECONDS  # noqa: E402

CACHE_DIR = Path(__file__).resolve().parents[1] / "data" / "cache" / "github"

#: Below this, a demo is close enough to the TTL that it should be re-warmed.
STALE_WARNING_HOURS = 4.0


def cache_state() -> dict:
    files = list(CACHE_DIR.glob("*.json")) if CACHE_DIR.is_dir() else []
    if not files:
        return {"entries": 0}
    now = time.time()
    ages = [(now - f.stat().st_mtime) / 3600 for f in files]
    ttl_hours = DEFAULT_TTL_SECONDS / 3600
    return {
        "entries": len(files),
        "megabytes": sum(f.stat().st_size for f in files) / 1e6,
        "newest_hours": min(ages),
        "oldest_hours": max(ages),
        "hours_left": ttl_hours - max(ages),
        "trees": sum(1 for f in files if "git_trees" in f.name),
        "readmes": sum(1 for f in files if "readme" in f.name.lower()),
        "expired": sum(1 for a in ages if a > ttl_hours),
    }


def report(state: dict) -> bool:
    """Print the cache state. Returns True if it looks demo-ready."""
    if not state["entries"]:
        print(f"  cache is EMPTY ({CACHE_DIR})")
        return False

    print(f"  entries        : {state['entries']}  "
          f"({state['trees']} repo trees, {state['readmes']} READMEs)")
    print(f"  size           : {state['megabytes']:.1f} MB")
    print(f"  age            : {state['newest_hours']:.1f}h newest, "
          f"{state['oldest_hours']:.1f}h oldest")
    print(f"  expires in     : {state['hours_left']:.1f}h  "
          f"(TTL {DEFAULT_TTL_SECONDS // 3600}h)")

    if state["expired"]:
        print(f"  ** {state['expired']} entries are PAST the TTL and will be "
              f"re-fetched **")
        return False
    if state["hours_left"] < STALE_WARNING_HOURS:
        print(f"  ** under {STALE_WARNING_HOURS:.0f}h of life left -- re-warm "
              f"before the demo **")
        return False
    if not state["trees"] or not state["readmes"]:
        # Both passes must be cached. Only one warmed is the easy mistake.
        print("  ** only one of the two GitHub passes is cached -- re-warm **")
        return False
    return True


def warm(username: str) -> bool:
    settings = get_settings()
    if not settings.github_token:
        print("  ! GITHUB_TOKEN is not set. Warming will use the unauthenticated")
        print("    60 req/hour tier and may not finish a full profile.")

    extractor = SkillExtractor()
    ok = True

    # Pass 1: the legacy README fetcher. Uncached this is the slow one, and the
    # evidence block is gated on it succeeding.
    t = time.time()
    try:
        prof = fetch_github_profile(username, extractor,
                                   token=settings.github_token,
                                   cache_dir=CACHE_DIR)
        print(f"  legacy fetcher    : {time.time() - t:5.1f}s   "
              f"{prof.repo_count} repos, {len(prof.skills)} skills")
    except GitHubFetchError as e:
        print(f"  legacy fetcher    : FAILED -- {e}")
        ok = False

    # Pass 2: the artifact collector.
    t = time.time()
    client = GitHubClient(token=settings.github_token,
                          budget=RequestBudget(limit=150), cache_dir=CACHE_DIR)
    try:
        gh = collect_profile(client, username)
        n_ev = sum(1 for e in evidence_from_profile(gh) if e.max_tier is not None)
        print(f"  evidence collector: {time.time() - t:5.1f}s   "
              f"{len(gh.repos)} repos, {client.budget.spent} requests, "
              f"{n_ev} skills evidenced")
        if gh.partial:
            print("    ! profile came back PARTIAL -- rate limit, budget, or the "
                  "repo cap. Absence will not be treated as evidence.")
        if client.rate_limited:
            print("    ! rate limited mid-collection; re-run once it resets.")
            ok = False
        if client.token_rejected:
            print("    ! the token was REJECTED and we fell back to "
                  "unauthenticated. Replace GITHUB_TOKEN in backend/.env.")
            ok = False
    except Exception as e:                      # noqa: BLE001 - report, never crash
        print(f"  evidence collector: FAILED -- {type(e).__name__}: {e}")
        ok = False

    return ok


def main() -> None:
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("username", nargs="*",
                    help="GitHub username(s) to warm; omit with --check")
    ap.add_argument("--check", action="store_true",
                    help="report cache state without fetching anything")
    args = ap.parse_args()

    if args.check:
        print(f"CACHE STATE  ({CACHE_DIR})")
        ready = report(cache_state())
        print()
        print("demo-ready" if ready else "NOT demo-ready -- re-warm")
        sys.exit(0 if ready else 1)

    if not args.username:
        ap.error("give at least one username, or use --check")

    all_ok = True
    for name in args.username:
        print(f"WARMING  {name}")
        # Timed twice: the second pass proves the cache is actually being read
        # rather than merely written, which is the thing that could silently fail.
        all_ok &= warm(name)
        print("  verifying it reads back warm...")
        t = time.time()
        warm_ok = warm(name)
        elapsed = time.time() - t
        all_ok &= warm_ok
        print(f"  -> warm run took {elapsed:.1f}s")
        if elapsed > 5.0:
            print("     ** still slow on the second run: the cache is not being "
                  "read. Check that cache_dir is being passed through. **")
            all_ok = False
        print()

    print(f"CACHE STATE  ({CACHE_DIR})")
    ready = report(cache_state())
    print()
    print("demo-ready" if (ready and all_ok) else "NOT demo-ready -- see above")
    sys.exit(0 if (ready and all_ok) else 1)


if __name__ == "__main__":
    main()
