"""
Tests for explicit GitHub fetch status (core/github_profile/status.py).

The failure these guard against actually happened: an expired GITHUB_TOKEN
produced the string "skipped: ...", which the UI rendered as one quiet line. Every
analysis silently fell back to resume-only evidence while still presenting a
readiness score as though GitHub had been consulted. For a project whose claim is
that evidence changes the number, losing the evidence silently is the worst
available failure.

Pure unit tests.
"""

from __future__ import annotations

import pytest

from core.github_profile.fetcher import GitHubFetchError
from core.github_profile.status import (
    DEGRADED,
    GitHubState,
    classify_error,
    not_requested,
    ok,
    partial,
)


def test_no_username_is_the_only_uninteresting_state():
    s = not_requested()
    assert s.state is GitHubState.NOT_REQUESTED
    assert s.evidence_used is False
    assert s.severity == "info"
    assert "resume claims only" in s.message


def test_success_reports_how_much_was_read():
    s = ok(12)
    assert s.state is GitHubState.OK
    assert s.evidence_used is True
    assert s.repos_analysed == 12
    assert s.severity == "info"
    assert "12" in s.message


def test_success_message_is_grammatical_for_one_repo():
    assert ok(1).message.endswith("1 public repository.")
    assert ok(2).message.endswith("2 public repositories.")


@pytest.mark.parametrize("exc,expected", [
    (GitHubFetchError("GitHub user 'nope' not found"), GitHubState.USER_NOT_FOUND),
    (GitHubFetchError("GitHub rate limit hit — retry later or pass a token"),
     GitHubState.RATE_LIMITED),
    (GitHubFetchError("401 Client Error: Unauthorized"), GitHubState.TOKEN_REJECTED),
    (GitHubFetchError("Bad credentials"), GitHubState.TOKEN_REJECTED),
    (GitHubFetchError("connection reset by peer"), GitHubState.ERROR),
])
def test_failures_are_classified_not_lumped_together(exc, expected):
    assert classify_error(exc).state is expected


def test_no_failure_is_ever_reported_as_a_bare_skipped():
    """The exact regression. 'skipped' told the reader nothing and hid a dead
    credential; every branch must name the fault and the remedy."""
    for exc in (GitHubFetchError("GitHub user 'x' not found"),
                GitHubFetchError("GitHub rate limit hit"),
                GitHubFetchError("Bad credentials"),
                GitHubFetchError("something odd")):
        s = classify_error(exc)
        assert "skipped" not in s.message.lower()
        assert s.evidence_used is False, "a failed fetch contributed no evidence"
        assert len(s.message) > 30, "must explain, not just label"


def test_a_token_problem_says_how_to_fix_it():
    s = classify_error(GitHubFetchError("Bad credentials"))
    assert "GITHUB_TOKEN" in s.message
    assert "resume claims only" in s.message, (
        "the reader must know the score lacked evidence"
    )


def test_a_rate_limit_explains_the_two_tiers():
    s = classify_error(GitHubFetchError("GitHub rate limit hit"))
    assert "60" in s.message and "5,000" in s.message


def test_degraded_states_never_claim_evidence_was_used():
    for state in DEGRADED:
        if state is GitHubState.PARTIAL:
            continue       # partial DID read something, just not everything
        s = classify_error(GitHubFetchError("x")) if state is GitHubState.ERROR else None
        if s:
            assert s.evidence_used is False


def test_partial_reads_something_but_warns_that_absence_proves_nothing():
    s = partial(5, "stopped at the repository cap")
    assert s.state is GitHubState.PARTIAL
    assert s.evidence_used is True, "it did read 5 repos"
    assert s.severity == "warn"
    assert "not proof of absence" in s.message


def test_user_not_found_is_an_error_not_a_warning():
    """A typo in the username is the candidate's to fix, unlike a rate limit."""
    assert classify_error(GitHubFetchError("user 'xyz' not found")).severity == "error"


def test_as_dict_exposes_everything_the_ui_needs_without_parsing():
    d = ok(3).as_dict()
    assert set(d) == {"state", "message", "repos_analysed", "evidence_used", "severity"}
    assert d["state"] == "ok" and d["repos_analysed"] == 3
    # The UI must never have to infer severity from a string prefix again.
    assert d["severity"] == "info"
