"""
JSearch client (OpenWeb Ninja) -> PostingRecord.

Subscribe DIRECTLY at openwebninja.com, not through RapidAPI. The provider's own
terms are what permit storing results in our database (see docs/legal/ and
backend/data/README.md §3); going via RapidAPI stacks a second, unreadable
contract on top for no benefit.

Measured against the live API on 2026-10-02, one request:
  - 10 results per request at num_pages=1
  - job_description median 3,024 chars (min 1,627, max 7,024) -- FULL text, no
    truncation, no trailing ellipsis. This is why JSearch was chosen over Adzuna
    (500-char cap), Jooble and Careerjet (both truncate).
  - country=in gave job_country == 'IN' for 10/10 results
  - NO quota headers in the response -- hence core/market/quota.py
"""

from __future__ import annotations

import time
from dataclasses import dataclass

import requests

from core.db.store import PostingRecord
from core.taxonomy.roles import map_title

API_URL = "https://api.openwebninja.com/jsearch/search"
SOURCE = "jsearch"
MARKET = "IN"

#: Matches the Naukri loader, so excerpt policy is uniform across sources.
#: Extraction still runs on the full text -- see PostingRecord.extract_text.
EXCERPT_CHARS = 500

#: Rate limit is 1,000/hour, so a monthly run of ~190 is nowhere near it. This
#: is politeness, not necessity.
PAUSE_SECONDS = 0.4


class JSearchError(RuntimeError):
    pass


@dataclass(frozen=True)
class PageResult:
    records: list[PostingRecord]
    raw_count: int           # results the API returned
    unmappable: int          # dropped: title stated no determinable role
    wrong_country: int       # dropped: job_country was not MARKET


def _clean(value: object) -> str:
    if value is None:
        return ""
    return " ".join(str(value).split())


def _salary(job: dict) -> str:
    explicit = _clean(job.get("job_salary") or job.get("job_salary_string"))
    if explicit:
        return explicit
    lo, hi = job.get("job_min_salary"), job.get("job_max_salary")
    cur = _clean(job.get("job_salary_currency"))
    per = _clean(job.get("job_salary_period"))
    if lo or hi:
        return " ".join(x for x in [cur, f"{lo or ''}-{hi or ''}", per] if x).strip()
    return ""


def _location(job: dict) -> str:
    explicit = _clean(job.get("job_location"))
    if explicit:
        return explicit
    parts = [_clean(job.get("job_city")), _clean(job.get("job_state"))]
    return ", ".join(p for p in parts if p)


def _experience(job: dict) -> str:
    req = job.get("job_required_experience") or {}
    if not isinstance(req, dict):
        return ""
    months = req.get("required_experience_in_months")
    if months:
        return f"{int(months) // 12} yrs" if int(months) >= 12 else f"{months} months"
    if req.get("no_experience_required"):
        return "fresher"
    return ""


def to_record(job: dict) -> PostingRecord | None:
    """Map one API result to a PostingRecord, or None if it should be dropped.

    The role comes from re-mapping the RETURNED title, not from the query that
    found it: searching "backend developer" legitimately surfaces the occasional
    full-stack job, and filing it under the queried role would mislabel it. A
    title stating no determinable role is dropped rather than defaulted -- see
    core/taxonomy/roles.py.
    """
    title = _clean(job.get("job_title"))
    role = map_title(title)
    if role is None:
        return None

    description = _clean(job.get("job_description"))
    external_id = _clean(job.get("job_id")) or _clean(job.get("job_uid"))
    if not description or not external_id:
        return None

    return PostingRecord(
        source=SOURCE,
        external_id=external_id,
        title=title,
        company=_clean(job.get("employer_name")),
        location=_location(job),
        experience=_experience(job),
        salary=_salary(job),
        description=description[:EXCERPT_CHARS],
        role_query=role,
        market=MARKET,
        extract_text=description,
    )


def fetch_page(
    api_key: str,
    query: str,
    *,
    page: int = 1,
    num_pages: int = 1,
    country: str = "in",
    date_posted: str = "month",
    timeout: int = 30,
) -> PageResult:
    """Fetch one API call's worth of results and map them.

    NOTE: the caller must have already reserved quota for this call via
    QuotaLedger.spend(). This function deliberately does not touch the ledger,
    so there is exactly one place that accounts for spend.
    """
    try:
        resp = requests.get(
            API_URL,
            headers={"x-api-key": api_key},
            params={
                "query": query,
                "page": page,
                "num_pages": num_pages,
                "country": country,
                "date_posted": date_posted,
            },
            timeout=timeout,
        )
    except requests.RequestException as e:
        raise JSearchError(f"request failed: {e}") from e

    if resp.status_code == 403:
        raise JSearchError(
            "403 from JSearch. If the body says 'not subscribed to this API', the "
            "key is valid but JSearch is not enabled on the account -- subscribe to "
            "it (free plan) in the OpenWeb Ninja dashboard."
        )
    if resp.status_code != 200:
        raise JSearchError(f"HTTP {resp.status_code}: {resp.text[:300]}")

    body = resp.json()
    if body.get("status") != "OK":
        raise JSearchError(f"API returned status={body.get('status')}: {str(body)[:300]}")

    jobs = body.get("data") or []
    records: list[PostingRecord] = []
    unmappable = wrong_country = 0
    want = country.upper()

    for job in jobs:
        got = _clean(job.get("job_country")).upper()
        if got and got != want:
            wrong_country += 1
            continue
        rec = to_record(job)
        if rec is None:
            unmappable += 1
            continue
        records.append(rec)

    return PageResult(
        records=records,
        raw_count=len(jobs),
        unmappable=unmappable,
        wrong_country=wrong_country,
    )


def polite_pause() -> None:
    time.sleep(PAUSE_SECONDS)
