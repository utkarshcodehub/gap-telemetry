"""
Live India job feed: JSearch (OpenWeb Ninja) -> Postgres.

This is the project's source of *current* market demand. The Naukri CC0 corpus is
real but frozen at Q4 2020 (pre-LLM-era); this feed keeps demand percentages
describing the market students are actually applying into.

Quota is the binding constraint and the provider makes it awkward:

  - 200 requests per billing period, resetting on the 2nd (NOT the calendar
    month -- see core/market/quota.py).
  - Pages are NOT free. Measured against the provider's own counter: 7 API calls
    consumed 12 requests, fitting `cost = ceil(num_pages / 5)` exactly. Results
    per request are therefore FLAT at ~48 regardless of num_pages, so deeper
    pages buy nothing and num_pages=5 is used for finer granularity.
  - No quota headers in any response, so nothing but the local ledger prevents a
    retry loop from burning the period.

Strategy: target-driven, not budget-driven. Roles are visited weakest-first and a
role stops as soon as its combined posting count (Naukri + this feed) clears
MIN_POSTINGS_PER_ROLE. Spending more on a role that already clears buys nothing
the floor needs. Because results are refiled by their mapped title, a query for
one role also tops up its neighbours, so all role counts are re-read after every
ingest rather than assumed.

Usage, from backend/ (so pydantic-settings resolves .env):

    cd backend
    python ../scraper/jsearch_feed.py --plan                    # spends 0
    python ../scraper/jsearch_feed.py --run --max-requests 80
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from app.settings import get_settings  # noqa: E402
from core.db.store import JobStore  # noqa: E402
from core.market.jsearch import (  # noqa: E402
    DEFAULT_NUM_PAGES,
    SOURCE,
    JSearchError,
    fetch_page,
    polite_pause,
    records_from_jobs,
    request_cost,
)
from core.market.quota import (  # noqa: E402
    DEFAULT_RESET_DAY,
    QuotaExhausted,
    QuotaLedger,
)
from core.taxonomy.roles import CANONICAL_ROLES, MIN_POSTINGS_PER_ROLE  # noqa: E402
from ingest import ingest_postings  # noqa: E402

_DATA = Path(__file__).resolve().parents[1] / "backend" / "data"
LEDGER_PATH = _DATA / "jsearch_quota.json"

#: Every raw API response is archived here, because this corpus is bought with a
#: capped monthly quota while the test suite truncates `postings` wholesale. A
#: database export would be lossy (only a 500-char excerpt is stored, so
#: re-extraction would find fewer skills), but replaying the raw response re-runs
#: the real pipeline for free. `--restore` does exactly that.
ARCHIVE_DIR = _DATA / "raw" / "jsearch"

#: Total usage ceiling for the period. The provider allows 200; this keeps at
#: least 100 in reserve at all times, so the feed can never consume the whole
#: allowance and strand later work.
PERIOD_USAGE_CAP = 100

#: Several phrasings per role, because a single query saturates at ~96 results.
#: Different phrasings surface different postings; results are refiled by their
#: mapped title, so a `data scientist` query legitimately lands under
#: `ai ml engineer` and a `power bi developer` query under `data analyst`.
PHRASINGS: dict[str, list[str]] = {
    "ai ml engineer": [
        "machine learning engineer", "data scientist", "ai engineer",
        "nlp engineer", "computer vision engineer",
    ],
    "data analyst": [
        "data analyst", "business intelligence analyst", "power bi developer",
        "tableau developer", "sql analyst",
    ],
    "data engineer": [
        "data engineer", "big data engineer", "etl developer",
        "azure data engineer", "spark developer",
    ],
    "qa engineer": [
        "qa engineer", "automation test engineer", "sdet", "software tester",
        "selenium automation engineer",
    ],
    "full stack developer": [
        "full stack developer", "full stack engineer", "mern stack developer",
        "java full stack developer", "mean stack developer",
    ],
    "frontend developer": [
        "frontend developer", "frontend engineer", "react developer",
        "angular developer", "ui developer",
    ],
    "devops engineer": [
        "devops engineer", "site reliability engineer", "cloud engineer",
        "kubernetes engineer", "aws devops engineer",
    ],
    "backend developer": [
        "backend developer", "backend engineer", "java backend developer",
        "python backend developer", "nodejs backend developer",
    ],
}


def role_counts(store: JobStore) -> dict[str, int]:
    """Combined India posting count per role, across every source."""
    return {r["role"]: r["postings"] for r in store.roles()}


def shortfalls(store: JobStore) -> dict[str, int]:
    counts = role_counts(store)
    return {
        role: max(0, MIN_POSTINGS_PER_ROLE - counts.get(role, 0))
        for role in CANONICAL_ROLES
    }


def existing_ids(store: JobStore) -> set[str]:
    """external_ids already held for this source, for client-side dedup.

    The database upsert makes re-ingestion harmless, but quota is spent *before*
    that -- the feed needs to know what it holds to decide whether another
    request is worth it.
    """
    seen: set[str] = set()
    page_size, offset = 1000, 0
    while True:
        resp = (
            store.client.table("postings")
            .select("external_id")
            .eq("source", SOURCE)
            .range(offset, offset + page_size - 1)
            .execute()
        )
        rows = resp.data or []
        seen.update(r["external_id"] for r in rows)
        if len(rows) < page_size:
            return seen
        offset += page_size


def _archive(jobs: list[dict], role: str, phrasing: str) -> None:
    """Persist a raw response so the quota spent on it is never lost again."""
    if not jobs:
        return
    ARCHIVE_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
    slug = re.sub(r"[^a-z0-9]+", "-", phrasing.lower()).strip("-")
    path = ARCHIVE_DIR / f"{stamp}-{slug}.json"
    path.write_text(json.dumps(
        {"fetched_at": stamp, "role": role, "query": phrasing, "data": jobs},
        indent=1,
    ), encoding="utf-8")


def cmd_restore(store: JobStore) -> None:
    """Rebuild the corpus from archived responses. Spends ZERO quota."""
    files = sorted(ARCHIVE_DIR.glob("*.json")) if ARCHIVE_DIR.exists() else []
    if not files:
        print(f"no archives in {ARCHIVE_DIR} -- nothing to restore.")
        return
    records, seen = [], set()
    for f in files:
        payload = json.loads(f.read_text(encoding="utf-8"))
        for rec in records_from_jobs(payload.get("data") or []):
            if rec.external_id in seen:
                continue
            seen.add(rec.external_id)
            records.append(rec)
    print(f"{len(files)} archived responses -> {len(records)} distinct postings")
    inserted = ingest_postings(records, store)
    print(f"ingested {inserted} new. DB total: {store.posting_count()}")


def cmd_plan(ledger: QuotaLedger, store: JobStore, num_pages: int) -> None:
    s = ledger.summary()
    cost = request_cost(num_pages)
    print(f"QUOTA  period={s['period']}  used={s['used']}/{s['cap']}  "
          f"remaining={s['remaining']}")
    print(f"       num_pages={num_pages} costs {cost} request(s) per call "
          f"(~{num_pages * 10} results)")
    print()
    counts = role_counts(store)
    short = shortfalls(store)
    held = len(existing_ids(store))
    print(f"already held from {SOURCE}: {held:,}")
    print()
    print(f"ROLE STATUS (floor {MIN_POSTINGS_PER_ROLE}) -- weakest first")
    for role, gap in sorted(short.items(), key=lambda kv: -kv[1]):
        have = counts.get(role, 0)
        mark = "CLEAR   " if gap == 0 else f"needs {gap:>3}"
        print(f"  {mark}  {role:<24} have {have:>4}")
    print()
    total = sum(short.values())
    print(f"total shortfall: {total} postings")
    if total:
        est_calls = -(-total // 46)  # ~96% of ~48 results map
        print(f"rough estimate : ~{est_calls} calls "
              f"= ~{est_calls * cost} requests, before any overlap")
    print("\nspends 0 requests.")


def cmd_run(ledger: QuotaLedger, store: JobStore, api_key: str,
            max_requests: int, num_pages: int) -> None:
    cost = request_cost(num_pages)
    spent = 0
    stats = {"calls": 0, "raw": 0, "unmappable": 0, "dupes": 0, "new": 0}

    held = existing_ids(store)
    short = shortfalls(store)
    print(f"budget {max_requests} requests ({cost}/call at num_pages={num_pages}); "
          f"ledger remaining {ledger.remaining()}")
    print(f"held from {SOURCE}: {len(held):,}")
    print(f"shortfall: {sum(short.values())} across "
          f"{sum(1 for v in short.values() if v)} roles\n")

    # Weakest first: a role that already clears the floor gains nothing the
    # floor needs from more spend.
    order = [r for r, gap in sorted(short.items(), key=lambda kv: -kv[1]) if gap > 0]
    if not order:
        print("every role already clears the floor; nothing to do.")
        return

    for role in order:
        if short.get(role, 0) <= 0:
            print(f"  {role}: cleared by cross-fill, skipping")
            continue
        for phrasing in PHRASINGS[role]:
            if spent + cost > max_requests:
                print(f"\nsession budget reached ({spent}/{max_requests})")
                return _finish(ledger, store, stats, spent)
            if short.get(role, 0) <= 0:
                print(f"  {role}: floor cleared, moving on")
                break
            try:
                ledger.spend(cost, note=f"{role} :: {phrasing!r} np={num_pages}")
            except QuotaExhausted as e:
                print(f"\nledger cap reached: {e}")
                return _finish(ledger, store, stats, spent)
            spent += cost
            stats["calls"] += 1

            try:
                res = fetch_page(api_key, phrasing, num_pages=num_pages)
            except JSearchError as e:
                print(f"  {phrasing!r}: FAILED -- {e}")
                continue

            stats["raw"] += res.raw_count
            stats["unmappable"] += res.unmappable
            fresh = [r for r in res.records if r.external_id not in held]
            stats["dupes"] += len(res.records) - len(fresh)
            held.update(r.external_id for r in fresh)

            _archive(res.raw_jobs, role, phrasing)
            inserted = ingest_postings(fresh, store) if fresh else 0
            stats["new"] += inserted
            short = shortfalls(store)   # cross-fill means every role can move

            print(f"  [{spent:>3}/{max_requests}] {phrasing:<30} "
                  f"raw {res.raw_count:>3}  new {len(fresh):>3}  "
                  f"ingested {inserted:>3}  | {role} still needs "
                  f"{short.get(role, 0)}")
            polite_pause()

    _finish(ledger, store, stats, spent)


def _finish(ledger: QuotaLedger, store: JobStore, stats: dict, spent: int) -> None:
    ledger.record_yield(results=stats["raw"], new_rows=stats["new"])
    print(f"\n{'=' * 62}")
    print(f"spent {spent} requests over {stats['calls']} calls")
    print(f"raw {stats['raw']}  unmappable {stats['unmappable']}  "
          f"already-held {stats['dupes']}  NEW {stats['new']}")
    print(f"ledger: {ledger.summary()}")
    print()
    counts = role_counts(store)
    print(f"ROLE STATUS (floor {MIN_POSTINGS_PER_ROLE})")
    for role in CANONICAL_ROLES:
        have = counts.get(role, 0)
        print(f"  {'CLEAR  ' if have >= MIN_POSTINGS_PER_ROLE else 'BELOW  '} "
              f"{role:<24} {have:>4}")
    print(f"\nDB postings total: {store.posting_count()}")


def main() -> None:
    ap = argparse.ArgumentParser()
    mode = ap.add_mutually_exclusive_group(required=True)
    mode.add_argument("--plan", action="store_true", help="status only; spends nothing")
    mode.add_argument("--run", action="store_true", help="fetch and ingest")
    mode.add_argument("--restore", action="store_true",
                     help="re-ingest from archived raw responses; spends 0 quota")
    ap.add_argument("--max-requests", type=int, default=0,
                    help="session budget in REQUESTS (not calls); required for --run")
    ap.add_argument("--num-pages", type=int, default=DEFAULT_NUM_PAGES)
    ap.add_argument("--period-cap", type=int, default=PERIOD_USAGE_CAP,
                    help="total usage ceiling for the period; the provider allows "
                         "200, this keeps the rest in reserve")
    ap.add_argument("--reset-day", type=int, default=DEFAULT_RESET_DAY)
    args = ap.parse_args()

    settings = get_settings()
    ledger = QuotaLedger(LEDGER_PATH, monthly_cap=args.period_cap,
                         reset_day=args.reset_day)
    store = JobStore()
    try:
        if args.plan:
            cmd_plan(ledger, store, args.num_pages)
            return
        if args.restore:
            cmd_restore(store)
            return
        if not settings.openwebninja_api_key:
            raise SystemExit("OPENWEBNINJA_API_KEY not set in backend/.env")
        if args.max_requests <= 0:
            raise SystemExit("--run requires --max-requests (a request budget)")
        cmd_run(ledger, store, settings.openwebninja_api_key,
                args.max_requests, args.num_pages)
    finally:
        store.close()


if __name__ == "__main__":
    main()
