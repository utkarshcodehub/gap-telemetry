"""
Tests for the guard that stops the suite deleting data it shouldn't.

The fixtures in conftest.py DELETE every row in `postings` and `skills`. These
tests prove the guard actually refuses, rather than the refusal being assumed --
it has to hold against a mistake nobody is watching for.

Pure unit tests: core/db/safety.py takes the facts as arguments so it can be
exercised without touching a database.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from core.db.safety import (
    ALLOW_ENV_VAR,
    DestructiveTestBlocked,
    check_truncate_allowed,
    parse_allowlist,
    project_ref,
    rebuildable_sources,
)

DEV = "hhujhpulwxvdzeiqtagn"
DEV_URL = f"https://{DEV}.supabase.co"


def allowed(**kw):
    """check_truncate_allowed with safe defaults, overridable per test."""
    args = {
        "supabase_url": DEV_URL,
        "allow_env_value": DEV,
        "present_sources": {"synthetic"},
        "rebuildable": set(),
    }
    args.update(kw)
    return check_truncate_allowed(**args)


# ------------------------------------------------- check 1: named project only

def test_the_happy_path_is_allowed():
    allowed()  # must not raise


def test_an_unnamed_project_is_refused():
    """The case that matters: .env repointed at a project that isn't disposable.

    The guard must block rather than wipe, because nothing else would notice.
    """
    with pytest.raises(DestructiveTestBlocked, match="Refusing to run destructive"):
        allowed(supabase_url="https://someoneelsesproject.supabase.co")


def test_the_refusal_names_the_project_and_how_to_allow_it():
    with pytest.raises(DestructiveTestBlocked) as e:
        allowed(supabase_url="https://prodproject.supabase.co")
    msg = str(e.value)
    assert "prodproject" in msg, "must say which project it refused"
    assert ALLOW_ENV_VAR in msg, "must say how to allow it deliberately"
    assert "DELETE" in msg, "must say what it would have done"


def test_an_empty_allowlist_refuses_everything():
    for value in (None, "", "   ", ",,"):
        with pytest.raises(DestructiveTestBlocked):
            allowed(allow_env_value=value)


def test_a_missing_supabase_url_refuses_rather_than_assuming():
    for url in (None, "", "not a url"):
        with pytest.raises(DestructiveTestBlocked):
            allowed(supabase_url=url)


def test_allowlist_accepts_several_refs():
    allowed(allow_env_value=f"other-project, {DEV} ,third")


def test_a_substring_match_is_not_enough():
    """'hhujh' must not authorise 'hhujhpulwxvdzeiqtagn'."""
    with pytest.raises(DestructiveTestBlocked):
        allowed(allow_env_value=DEV[:5])


# ------------------------------------- check 2: nothing irreplaceable present

def test_quota_bought_data_blocks_the_wipe_when_no_archive_exists():
    """The failure this guard was written for.

    A JSearch corpus costs capped monthly API quota that cannot be topped up
    until the billing period resets. With no local archive it is unrecoverable,
    so the suite must refuse.
    """
    with pytest.raises(DestructiveTestBlocked, match="cannot be rebuilt"):
        allowed(present_sources={"synthetic", "jsearch"}, rebuildable=set())


def test_the_same_data_is_fine_once_it_can_be_rebuilt_for_free():
    allowed(present_sources={"synthetic", "jsearch"}, rebuildable={"jsearch"})


def test_an_unknown_source_is_treated_as_unrecoverable():
    """Fail closed: a source the guard has never heard of has no known way back."""
    with pytest.raises(DestructiveTestBlocked, match="cannot be rebuilt"):
        allowed(present_sources={"some-new-feed"}, rebuildable={"jsearch"})


def test_fixture_sources_never_block():
    allowed(present_sources={"synthetic"}, rebuildable=set())


def test_an_empty_table_never_blocks():
    allowed(present_sources=set(), rebuildable=set())


def test_the_refusal_lists_which_sources_are_at_risk():
    with pytest.raises(DestructiveTestBlocked) as e:
        allowed(present_sources={"jsearch", "naukri-cc0-2020q4"}, rebuildable=set())
    msg = str(e.value)
    assert "jsearch" in msg and "naukri-cc0-2020q4" in msg


# ---------------------------------------------------------------- helpers

@pytest.mark.parametrize("url,expected", [
    ("https://abc123.supabase.co", "abc123"),
    ("https://abc123.supabase.co/", "abc123"),
    ("abc123.supabase.co", "abc123"),
    ("https://abc123.supabase.co/rest/v1", "abc123"),
    ("", ""),
    (None, ""),
])
def test_project_ref_parsing(url, expected):
    assert project_ref(url) == expected


def test_parse_allowlist_trims_and_drops_blanks():
    assert parse_allowlist(" a , b ,, ") == {"a", "b"}
    assert parse_allowlist(None) == set()


def test_rebuildable_sources_requires_the_actual_files(tmp_path: Path):
    """A source counts as rebuildable only if its archive is present NOW."""
    assert rebuildable_sources(tmp_path) == set()

    (tmp_path / "raw" / "jsearch").mkdir(parents=True)
    assert rebuildable_sources(tmp_path) == set(), "empty dir is not an archive"

    (tmp_path / "raw" / "jsearch" / "a.json").write_text("{}", encoding="utf-8")
    assert rebuildable_sources(tmp_path) == {"jsearch"}

    (tmp_path / "raw" / "naukri").mkdir(parents=True)
    (tmp_path / "raw" / "naukri" / "x.zip").write_bytes(b"PK")
    assert rebuildable_sources(tmp_path) == {"jsearch", "naukri-cc0-2020q4"}
