"""
Live India job feed: JSearch (OpenWeb Ninja) -> Postgres.

This is the project's source of *current* market demand. The Naukri CC0 corpus
is real but frozen at Q4 2020 (pre-LLM-era); this feed is what keeps demand
percentages describing the market students are actually applying into.

Quota is the binding constraint: 200 requests/month on the free tier, 10 results
per request, and the API exposes no quota headers. Every request is therefore
reserved through core/market/quota.py BEFORE it is issued, and the ledger is
re-read from disk each time, so a retry loop cannot walk past the cap.

Usage, from backend/ (so pydantic-settings resolves .env):

    cd backend
    python ../scraper/jsearch_feed.py --plan                 # spends 0 requests
    python ../scraper/jsearch_feed.py --probe-num-pages      # spends 2
    python ../scraper/jsearch_feed.py --run                  # spends up to the budget
    python ../scraper/jsearch_feed.py --run --max-requests 8 # small real test
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from app.settings import get_settings  # noqa: E402
from core.db.store import JobStore  # noqa: E402
from core.market.jsearch import (  # noqa: E402
    SOURCE,
    JSearchError,
    fetch_page,
    polite_pause,
)
from core.market.quota import (  # noqa: E402
    DEFAULT_MONTHLY_CAP,
    DEFAULT_RESET_DAY,
    QuotaExhausted,
    QuotaLedger,
)
from core.taxonomy.roles import CANONICAL_ROLES, MIN_POSTINGS_PER_ROLE  # noqa: E402
from ingest import ingest_postings  # noqa: E402

LEDGER_PATH = (
    Path(__file__).resolve().parents[1] / "backend" / "data" / "jsearch_quota.json"
)

#: Stop paginating a role once a page is mostly postings we already hold. Live
#: listings persist for weeks, so later monthly runs re-see them; banking the
#: quota instead is worth more than the few new rows deeper pages would add.
SEEN_RATIO_STOP = 0.8

#: A page returning fewer than this is the end of useful depth for that query.
THIN_PAGE = 3


def allocate(budget: int, roles: tuple[str, ...]) -> dict[str, int]:
    """Split the budget evenly, distributing the remainder one-per-role.

    Equal allocation is deliberate. Weighting toward roles the Naukri corpus
    under-covers turned out to be unnecessary: at ~10 results per request, an
    even split clears MIN_POSTINGS_PER_ROLE for all eight roles in a single
    month, so the simpler rule is also sufficient.
    """
    base, extra = divmod(budget, len(roles))
    return {role: base + (1 if i < extra else 0) for i, role in enumerate(roles)}


def existing_ids(store: JobStore) -> set[str]:
    """external_ids already held for this source, for client-side dedup.

    The database upsert already makes re-ingestion harmless, but quota is spent
    *before* that -- so the feed needs to know what it already has in order to
    decide whether paginating deeper is worth a request.
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


def cmd_plan(ledger: QuotaLedger, store: JobStore) -> None:
    s = ledger.summary()
    print(f"QUOTA  period={s['period']}  used={s['used']}/{s['cap']}  "
          f"remaining={s['remaining']}  (results so far: {s['results']}, "
          f"new rows: {s['new_rows']})")
    print()
    held = existing_ids(store)
    print(f"already held from {SOURCE}: {len(held):,} postings")
    print()
    alloc = allocate(s["remaining"], CANONICAL_ROLES)
    print(f"PLANNED ALLOCATION of {s['remaining']} requests "
          f"(~10 results each, floor {MIN_POSTINGS_PER_ROLE}/role)")
    for role, n in alloc.items():
        print(f"  {role:<24} {n:>3} requests  -> ~{n * 10:>4} results")
    print()
    print("spends 0 requests. Use --run to execute.")


def cmd_probe(ledger: QuotaLedger, api_key: str) -> None:
    """Resolve whether num_pages=N costs 1 request or N.

    Spends exactly 2. The API returns no quota headers, so the question can only
    be answered by reading the dashboard counter before and after.
    """
    print("NUM_PAGES PROBE -- read your OpenWeb Ninja usage counter NOW, call it X.")
    print()
    for num_pages in (1, 2):
        ledger.spend(1, note=f"probe num_pages={num_pages}")
        try:
            res = fetch_page(api_key, "backend developer", num_pages=num_pages)
        except JSearchError as e:
            print(f"  num_pages={num_pages}: FAILED -- {e}")
            continue
        print(f"  num_pages={num_pages}: {res.raw_count} results returned "
              f"({len(res.records)} mapped, {res.unmappable} unmappable, "
              f"{res.wrong_country} wrong country)")
        polite_pause()
    print()
    print("Now read the counter again, call it Y.")
    print("  Y = X + 2  -> num_pages is FREE (1 request per call regardless)")
    print("  Y = X + 3  -> num_pages=N costs N requests")
    print(f"ledger now: {ledger.summary()}")


def cmd_run(ledger: QuotaLedger, store: JobStore, api_key: str,
            max_requests: int | None, num_pages: int) -> None:
    budget = ledger.remaining()
    if max_requests is not None:
        budget = min(budget, max_requests)
    if budget <= 0:
        print(f"no quota left this month: {ledger.summary()}")
        return

    alloc = allocate(budget, CANONICAL_ROLES)
    held = existing_ids(store)
    print(f"budget {budget} requests, {len(held):,} postings already held\n")

    all_records = []
    spent = total_raw = total_unmappable = total_seen = 0

    for role, limit in alloc.items():
        role_new = 0
        for page in range(1, limit + 1):
            try:
                ledger.spend(1, note=f"{role} p{page}")
            except QuotaExhausted as e:
                print(f"  stopping: {e}")
                break
            spent += 1
            try:
                res = fetch_page(api_key, role, page=page, num_pages=num_pages)
            except JSearchError as e:
                print(f"  {role} p{page}: FAILED -- {e}")
                break

            total_raw += res.raw_count
            total_unmappable += res.unmappable
            fresh = [r for r in res.records if r.external_id not in held]
            seen = len(res.records) - len(fresh)
            total_seen += seen
            held.update(r.external_id for r in fresh)
            all_records.extend(fresh)
            role_new += len(fresh)

            if res.raw_count < THIN_PAGE:
                print(f"  {role} p{page}: thin page ({res.raw_count}), "
                      f"stopping this role")
                break
            if res.records and seen / len(res.records) >= SEEN_RATIO_STOP:
                print(f"  {role} p{page}: {seen}/{len(res.records)} already held, "
                      f"banking the rest of this role's quota")
                break
            polite_pause()
        print(f"  {role:<24} +{role_new} new")

    print(f"\nspent {spent} requests -> {total_raw} results, "
          f"{total_unmappable} unmappable, {total_seen} already held, "
          f"{len(all_records)} new")

    if not all_records:
        ledger.record_yield(results=total_raw, new_rows=0)
        print("nothing new to ingest.")
        return

    inserted = ingest_postings(all_records, store)
    ledger.record_yield(results=total_raw, new_rows=inserted)
    print(f"ingested {inserted} new postings. DB total: {store.posting_count()}")
    print(f"ledger: {ledger.summary()}")


def main() -> None:
    ap = argparse.ArgumentParser()
    mode = ap.add_mutually_exclusive_group(required=True)
    mode.add_argument("--plan", action="store_true",
                     help="show quota and allocation; spends nothing")
    mode.add_argument("--probe-num-pages", action="store_true",
                     help="spend exactly 2 requests to resolve num_pages cost")
    mode.add_argument("--run", action="store_true", help="fetch and ingest")
    ap.add_argument("--max-requests", type=int, default=None,
                    help="cap this run below the remaining monthly budget")
    ap.add_argument("--num-pages", type=int, default=1,
                    help="pages per request; leave at 1 until the probe says "
                         "it is free")
    ap.add_argument("--monthly-cap", type=int, default=DEFAULT_MONTHLY_CAP,
                    help="self-imposed cap below the provider's 200/period")
    ap.add_argument("--reset-day", type=int, default=DEFAULT_RESET_DAY,
                    help="day of month the provider resets the allowance; this "
                         "account resets on the 2nd, NOT the 1st")
    args = ap.parse_args()

    settings = get_settings()
    api_key = settings.openwebninja_api_key
    ledger = QuotaLedger(
        LEDGER_PATH, monthly_cap=args.monthly_cap, reset_day=args.reset_day
    )

    if args.plan:
        store = JobStore()
        try:
            cmd_plan(ledger, store)
        finally:
            store.close()
        return

    if not api_key:
        raise SystemExit(
            "OPENWEBNINJA_API_KEY is not set in backend/.env — see .env.example"
        )

    if args.probe_num_pages:
        cmd_probe(ledger, api_key)
        return

    store = JobStore()
    try:
        cmd_run(ledger, store, api_key, args.max_requests, args.num_pages)
    finally:
        store.close()


if __name__ == "__main__":
    main()
