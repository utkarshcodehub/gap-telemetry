"""
Tests for the JSearch response -> PostingRecord mapping and the quota cost model.

Pure unit tests against a captured response shape -- no network. The job_uid case
below is the important one: keying on the wrong field would have silently
duplicated the entire corpus on every run.
"""

from __future__ import annotations

import pytest

from core.market.jsearch import (
    DEFAULT_NUM_PAGES,
    EXCERPT_CHARS,
    MARKET,
    SOURCE,
    request_cost,
    to_record,
)

# Shape taken from a real response (2026-10-02). job_id is ~402 chars and
# decodes to "<job_uid>:<rotating token>"; job_uid is the stable 24-char docid.
STABLE_UID = "NKUFFcm6aE0Fa9YeAAAAAA=="
ROTATING_ID = "TktVRkZjbTZhRTBGYTlZZUFBQUFBQT09OkVzd0JDb3dCUVVwcFZEUjBTWHBoVkhZMWRFUT" * 5


def job(**overrides) -> dict:
    base = {
        "job_id": ROTATING_ID,
        "job_uid": STABLE_UID,
        "job_title": "Backend Developer",
        "employer_name": "Round1 Jobs",
        "job_description": "We need Python, Django and PostgreSQL. " * 40,
        "job_city": "Bengaluru",
        "job_state": "Karnataka",
        "job_country": "IN",
        "job_location": "Bengaluru, Karnataka",
    }
    base.update(overrides)
    return base


# ------------------------------------------------------------ the identifier

def test_external_id_is_the_stable_uid_not_the_rotating_id():
    """Regression, and the costliest bug in this module.

    `job_id` embeds a per-request token, so the same posting returns a different
    job_id on every call. Keying on it made two identical queries look 100%
    disjoint, and would have re-inserted the whole corpus as new rows on every
    monthly run -- inflating counts, distorting every demand percentage, and
    preventing the already-held early-stop from ever firing.
    """
    rec = to_record(job())
    assert rec is not None
    assert rec.external_id == STABLE_UID
    assert rec.external_id != ROTATING_ID
    assert len(rec.external_id) == 24, "the stable docid is 24 chars"


def test_a_posting_without_a_uid_is_dropped_not_keyed_on_job_id():
    """No stable key means no safe dedup, so the posting is unusable.

    Falling back to job_id here would quietly reintroduce the duplication bug for
    exactly the rows most likely to recur.
    """
    assert to_record(job(job_uid=None)) is None
    assert to_record(job(job_uid="")) is None


def test_same_posting_under_two_different_job_ids_yields_one_external_id():
    a = to_record(job(job_id=ROTATING_ID + "AAAA"))
    b = to_record(job(job_id="Z" * 300))
    assert a.external_id == b.external_id == STABLE_UID


# ------------------------------------------------------------------ mapping

def test_role_comes_from_the_title_and_market_is_pinned():
    rec = to_record(job(job_title="Senior React Developer"))
    assert rec.role_query == "frontend developer", "refiled by title, not by query"
    assert rec.market == MARKET == "IN"
    assert rec.source == SOURCE


def test_unmappable_title_is_dropped():
    assert to_record(job(job_title="Software Engineer")) is None
    assert to_record(job(job_title="Business Development Executive")) is None


def test_description_is_excerpted_but_extraction_sees_the_full_text():
    full = "Python and Docker. " * 500
    rec = to_record(job(job_description=full))
    assert len(rec.description) == EXCERPT_CHARS
    assert rec.extract_text == " ".join(full.split())
    assert len(rec.text_for_extraction) > EXCERPT_CHARS, (
        "extraction must not run on the truncated excerpt -- that would "
        "silently undercount demand"
    )


def test_missing_description_is_dropped():
    assert to_record(job(job_description="")) is None
    assert to_record(job(job_description=None)) is None


def test_location_falls_back_to_city_and_state():
    rec = to_record(job(job_location=None))
    assert rec.location == "Bengaluru, Karnataka"


def test_experience_is_derived_from_the_nested_object():
    rec = to_record(job(job_required_experience={"required_experience_in_months": 36}))
    assert rec.experience == "3 yrs"
    rec = to_record(job(job_required_experience={"no_experience_required": True}))
    assert rec.experience == "fresher"
    assert to_record(job(job_required_experience=None)).experience == ""


# --------------------------------------------------------------- cost model

@pytest.mark.parametrize("num_pages,expected", [
    (1, 1), (2, 1), (5, 1),      # 1..5 pages -> 1 request
    (6, 2), (10, 2),             # 6..10      -> 2
    (11, 3), (15, 3),
    (20, 4),
])
def test_request_cost_is_one_per_five_pages(num_pages, expected):
    """Pages are NOT free. Measured against the provider's own counter: 7 API
    calls consumed 12 requests, and ceil(num_pages/5) is the only fit."""
    assert request_cost(num_pages) == expected


def test_results_per_request_is_flat_so_deeper_pages_buy_nothing():
    """~9.6 results/page measured, so results-per-request is ~48 at every depth.
    This is why num_pages=20 was not worth testing."""
    per_page = 9.6
    ratios = [per_page * n / request_cost(n) for n in (5, 10, 20)]
    assert max(ratios) - min(ratios) < 1.0, f"expected flat, got {ratios}"


def test_default_num_pages_costs_exactly_one_request():
    assert request_cost(DEFAULT_NUM_PAGES) == 1


def test_zero_or_negative_pages_is_an_error():
    for bad in (0, -1):
        with pytest.raises(ValueError):
            request_cost(bad)
