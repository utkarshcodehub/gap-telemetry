"""
Tests for the monthly request cap (core/market/quota.py).

This is the only thing standing between a retry loop and a blown JSearch monthly
allowance, which cannot be refilled until the next calendar month. So the cap
itself is tested, not just the happy path. No network, no database.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone

import pytest

from core.market.quota import QuotaExhausted, QuotaLedger


@pytest.fixture
def ledger(tmp_path):
    return QuotaLedger(tmp_path / "quota.json", monthly_cap=10, reset_day=2)


def test_starts_empty(ledger):
    assert ledger.used() == 0
    assert ledger.remaining() == 10


def test_spend_decrements_remaining(ledger):
    assert ledger.spend(3) == 7
    assert ledger.used() == 3
    assert ledger.remaining() == 7


def test_cap_is_hard(ledger):
    ledger.spend(10)
    assert ledger.remaining() == 0
    with pytest.raises(QuotaExhausted):
        ledger.spend(1)
    assert ledger.used() == 10, "a refused spend must not be recorded"


def test_a_single_oversized_spend_is_refused_atomically(ledger):
    ledger.spend(8)
    with pytest.raises(QuotaExhausted):
        ledger.spend(5)          # would reach 13
    assert ledger.used() == 8, "no partial spend"
    assert ledger.spend(2) == 0, "the remaining 2 are still available"


def test_a_retry_loop_cannot_walk_past_the_cap(ledger):
    """The scenario the cap exists for.

    Each iteration constructs a FRESH ledger object, which is what a retrying
    subprocess, a rerun after a crash, or a second terminal would do. The count
    must come from disk every time, not from in-memory state.
    """
    granted = 0
    for _ in range(100):
        fresh = QuotaLedger(ledger.path, monthly_cap=10, reset_day=2)
        try:
            fresh.spend(1)
            granted += 1
        except QuotaExhausted:
            pass
    assert granted == 10, f"loop obtained {granted} requests against a cap of 10"
    assert QuotaLedger(ledger.path, monthly_cap=10, reset_day=2).used() == 10


def test_periods_are_accounted_separately(ledger):
    ledger.spend(10, period="2026-10-02")
    assert ledger.remaining("2026-10-02") == 0
    assert ledger.remaining("2026-11-02") == 10, "a new period starts fresh"
    ledger.spend(4, period="2026-11-02")
    assert ledger.used("2026-10-02") == 10
    assert ledger.used("2026-11-02") == 4


def test_period_key_anchors_to_the_reset_day_not_the_calendar_month(tmp_path):
    """The bug a calendar-month key would cause.

    The provider resets on the 2nd (observed: "resetting Nov 2, 2026"), so usage
    on 1 November belongs to the period that began 2 October. A calendar key
    would file it under November and hand out a second allowance a day early.
    """
    led = QuotaLedger(tmp_path / "q.json", monthly_cap=10, reset_day=2)
    on = lambda y, m, d: led.period_key(datetime(y, m, d, tzinfo=timezone.utc))

    assert on(2026, 10, 2) == "2026-10-02", "reset day starts a new period"
    assert on(2026, 10, 31) == "2026-10-02"
    assert on(2026, 11, 1) == "2026-10-02", "the day BEFORE reset is still the old period"
    assert on(2026, 11, 2) == "2026-11-02", "and the reset day rolls it over"
    # Year boundary.
    assert on(2027, 1, 1) == "2026-12-02"
    assert on(2027, 1, 2) == "2027-01-02"


def test_reset_day_1_behaves_like_calendar_months(tmp_path):
    led = QuotaLedger(tmp_path / "q.json", reset_day=1)
    assert led.period_key(datetime(2026, 3, 9, tzinfo=timezone.utc)) == "2026-03-01"
    assert led.period_key(datetime(2026, 12, 31, tzinfo=timezone.utc)) == "2026-12-01"


def test_reset_day_beyond_28_is_rejected(tmp_path):
    """A reset day of 29-31 would make a period disappear in February."""
    for bad in (0, 29, 31, -1):
        with pytest.raises(ValueError):
            QuotaLedger(tmp_path / "q.json", reset_day=bad)


def test_month_key_is_gone_and_fails_loudly(tmp_path):
    led = QuotaLedger(tmp_path / "q.json", reset_day=2)
    with pytest.raises(AttributeError, match="period_key"):
        led.month_key()


def test_a_corrupt_ledger_refuses_to_spend_rather_than_resetting(tmp_path):
    """A truncated or garbled file must NOT read as 'zero used'.

    Reading zero would hand a full fresh allowance to whatever just crashed --
    the exact opposite of what a cap is for.
    """
    path = tmp_path / "quota.json"
    path.write_text("{not valid json", encoding="utf-8")
    led = QuotaLedger(path, monthly_cap=10, reset_day=2)
    with pytest.raises(QuotaExhausted, match="unreadable"):
        led.spend(1)


def test_record_yield_never_affects_the_cap(ledger):
    ledger.spend(2)
    ledger.record_yield(results=20, new_rows=17)
    ledger.record_yield(results=10, new_rows=3)
    s = ledger.summary()
    assert s["used"] == 2 and s["remaining"] == 8
    assert s["results"] == 30 and s["new_rows"] == 20


def test_notes_are_recorded_for_auditing(ledger):
    ledger.spend(1, note="backend developer p1")
    data = json.loads(ledger.path.read_text(encoding="utf-8"))
    runs = data["periods"][ledger.period_key()]["runs"]
    assert len(runs) == 1
    assert runs[0]["note"] == "backend developer p1"
    assert runs[0]["spent"] == 1
    assert runs[0]["at"]


def test_zero_or_negative_spend_is_a_programming_error(ledger):
    for bad in (0, -1):
        with pytest.raises(ValueError):
            ledger.spend(bad)


def test_ledger_file_is_valid_json_after_many_writes(ledger):
    for _ in range(10):
        ledger.spend(1, note="x")
    data = json.loads(ledger.path.read_text(encoding="utf-8"))
    assert data["periods"][ledger.period_key()]["requests"] == 10
