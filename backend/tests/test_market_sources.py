"""
Tests for source provenance labels (core/market/sources.py).

These strings are what the UI shows to justify a demand percentage, so an
unknown source must read as unknown rather than being quietly dressed up.
Pure unit tests.
"""

from __future__ import annotations

from core.market.sources import SOURCE_INFO, describe


def test_the_live_feed_is_marked_live():
    d = describe("jsearch")
    assert d["live"] is True
    assert d["vintage"] == "current"


def test_the_archival_sample_is_not_marked_live():
    d = describe("naukri-cc0-2020q4")
    assert d["live"] is False
    assert d["vintage"] == "Q4 2020", (
        "the vintage must be visible: this sample predates the LLM/RAG/MLOps "
        "market entirely, so a reader assuming it is current would be misled"
    )


def test_synthetic_is_labelled_as_not_real_data():
    """The generator is test-only. If one of its rows ever reaches the UI it must
    announce itself, not pass as market data."""
    d = describe("synthetic")
    assert "SYNTHETIC" in d["label"]
    assert "not real market data" in d["label"]
    assert d["live"] is False


def test_an_unknown_source_is_reported_as_unknown_not_guessed():
    d = describe("some-future-feed")
    assert d["source"] == "some-future-feed"
    assert d["label"] == "some-future-feed", "no invented label"
    assert d["vintage"] == "unknown"
    assert d["live"] is False, "unknown sources must not claim to be current"


def test_every_entry_describes_itself_completely():
    for source in SOURCE_INFO:
        d = describe(source)
        assert d["label"] and d["vintage"]
        assert isinstance(d["live"], bool)
        assert d["source"] == source
