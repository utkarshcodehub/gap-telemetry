"""
Tests for the demo cache pre-warmer (scripts/prewarm_cache.py).

Only the staleness logic is tested, and that is the point: the script's whole value
is answering "is the demo ready" truthfully. A false "demo-ready" is worse than no
script at all, because it replaces a known risk with an unfounded reassurance.

No network. CACHE_DIR is redirected at a tmp_path.
"""

from __future__ import annotations

import os
import time
from pathlib import Path

import pytest

import scripts.prewarm_cache as pw
from core.http_cache import DEFAULT_TTL_SECONDS

TTL_HOURS = DEFAULT_TTL_SECONDS / 3600


@pytest.fixture
def cache(tmp_path, monkeypatch):
    monkeypatch.setattr(pw, "CACHE_DIR", tmp_path)
    return tmp_path


def entry(cache: Path, name: str, age_hours: float = 0.0) -> Path:
    p = cache / name
    p.write_text("{}", encoding="utf-8")
    if age_hours:
        when = time.time() - age_hours * 3600
        os.utime(p, (when, when))
    return p


def both_passes(cache: Path, age_hours: float = 0.0) -> None:
    """One entry per GitHub pass -- the minimum for a usable cache."""
    entry(cache, "a_git_trees_main.json", age_hours)
    entry(cache, "b_repos_x_readme.json", age_hours)


def test_an_empty_cache_is_not_demo_ready(cache):
    assert pw.cache_state()["entries"] == 0
    assert pw.report(pw.cache_state()) is False


def test_a_fresh_cache_with_both_passes_is_demo_ready(cache):
    both_passes(cache)
    assert pw.report(pw.cache_state()) is True


def test_only_one_warmed_pass_is_not_demo_ready(cache):
    """The easy mistake this script exists to catch.

    /analyze makes two GitHub passes. Warming only the evidence collector looks
    fixed -- the collector reports 0 requests -- while the legacy README fetcher
    still costs ~15 seconds on the demo's first request.
    """
    entry(cache, "a_git_trees_main.json")          # collector only
    assert pw.report(pw.cache_state()) is False

    entry(cache, "b_repos_x_readme.json")          # now both
    assert pw.report(pw.cache_state()) is True


def test_expired_entries_are_not_demo_ready(cache):
    both_passes(cache, age_hours=TTL_HOURS + 6)
    state = pw.cache_state()
    assert state["expired"] == 2
    assert state["hours_left"] < 0
    assert pw.report(state) is False


def test_nearly_expired_warns_rather_than_passing(cache):
    """A cache with two hours of life left is not a cache you demo on.

    Reporting it as ready would be technically true and practically useless --
    the TTL could lapse between setup and the actual demo.
    """
    both_passes(cache, age_hours=TTL_HOURS - 2)
    state = pw.cache_state()
    assert state["expired"] == 0, "not yet expired..."
    assert pw.report(state) is False, "...but too close to rely on"


def test_plenty_of_life_left_passes(cache):
    both_passes(cache, age_hours=1.0)
    state = pw.cache_state()
    assert state["hours_left"] > pw.STALE_WARNING_HOURS
    assert pw.report(state) is True


def test_mixed_ages_are_judged_by_the_OLDEST_entry(cache):
    """The oldest entry is what expires first, so it decides readiness. Judging by
    the newest would call a cache ready while most of it was about to lapse."""
    both_passes(cache, age_hours=0.1)
    entry(cache, "c_git_trees_old.json", age_hours=TTL_HOURS + 1)
    state = pw.cache_state()
    assert state["newest_hours"] < 1
    assert state["expired"] == 1
    assert pw.report(state) is False
