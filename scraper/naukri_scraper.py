"""
Naukri scraper — RUN THIS LOCALLY (network access to naukri.com required).

Usage:
    # From the repo root:
    python3 -m scraper.naukri_scraper --role "machine learning intern" --pages 25
    # If you are in backend/ instead:
    python3 ../scraper/naukri_scraper.py --role "machine learning intern" --pages 25

Hits Naukri's internal JSON search API (the same one their React frontend
calls) rather than parsing HTML: structured fields for free, no brittle
CSS selectors.

Required headers: 'appid' and 'systemid'. If Naukri rotates these, open
DevTools -> Network tab on a naukri.com search, click the 'v3/search'
request, and copy the current header values.

NOTE: scraping may conflict with a site's terms of service. For an
academic FYP keep volume small, or use the synthetic generator / a
licensed dataset as alternatives — see the security section of the
README for why this matters before any commercial use.
"""

import argparse
import json
import random
import sys
import time
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from core.db.store import JobStore, PostingRecord  # noqa: E402
from ingest import ingest_postings                  # noqa: E402

API_URL = "https://www.naukri.com/jobapi/v3/search"

HEADERS = {
    "appid": "109",
    "systemid": "Naukri",
    "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                   "AppleWebKit/537.36 (KHTML, like Gecko) "
                   "Chrome/126.0 Safari/537.36"),
    "Accept": "application/json",
}

RAW_DIR = Path(__file__).resolve().parents[1] / "backend" / "data" / "raw"


def fetch_page(role: str, page: int, session: requests.Session) -> dict:
    params = {
        "noOfResults": 20, "urlType": "search_by_keyword", "searchType": "adv",
        "keyword": role, "pageNo": page,
    }
    for attempt in range(4):
        resp = session.get(API_URL, params=params, headers=HEADERS, timeout=15)
        if resp.status_code == 200:
            return resp.json()
        if resp.status_code in (429, 500, 502, 503):
            wait = 2 ** attempt * 3
            print(f"  [{resp.status_code}] backing off {wait}s...")
            time.sleep(wait)
            continue
        resp.raise_for_status()
    raise RuntimeError(f"Page {page} failed after retries")


def parse_job(job: dict, role: str) -> PostingRecord | None:
    desc_parts = [job.get("title", ""), job.get("jobDescription", ""), job.get("tagsAndSkills", "")]
    placeholders = {p.get("type"): p.get("label") for p in job.get("placeholders", [])}
    external_id = str(job.get("jobId") or "")
    if not external_id:
        return None
    return PostingRecord(
        source="naukri", external_id=external_id, title=job.get("title", ""),
        company=job.get("companyName", ""), location=placeholders.get("location", ""),
        experience=placeholders.get("experience", ""), salary=placeholders.get("salary", ""),
        description=" \n".join(p for p in desc_parts if p), role_query=role,
    )


def scrape(role: str, pages: int) -> None:
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    session = requests.Session()
    store = JobStore()
    records: list[PostingRecord] = []

    for page in range(1, pages + 1):
        print(f"Page {page}/{pages} ...")
        data = fetch_page(role, page, session)
        snap = RAW_DIR / f"naukri_{role.replace(' ', '_')}_p{page}.json"
        snap.write_text(json.dumps(data, indent=1), encoding="utf-8")

        jobs = data.get("jobDetails", [])
        if not jobs:
            print("  no more results, stopping.")
            break
        for job in jobs:
            rec = parse_job(job, role)
            if rec:
                records.append(rec)
        time.sleep(2.5 + random.uniform(0, 1.5))

    inserted = ingest_postings(records, store)
    print(f"\nDone. {len(records)} fetched, {inserted} new postings ingested "
          f"(duplicates skipped). DB total for '{role}': {store.posting_count(role)}")
    store.close()


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--role", required=True, help='e.g. "machine learning intern"')
    ap.add_argument("--pages", type=int, default=25, help="20 postings/page")
    args = ap.parse_args()
    scrape(args.role, args.pages)
