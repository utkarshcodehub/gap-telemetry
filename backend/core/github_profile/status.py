"""
Explicit, structured status for a GitHub evidence fetch (NFR-4, EC-11).

Why this exists. The status used to be a bare string -- "not_requested",
"ok (12 repos)", or "skipped: <whatever the exception said>" -- and the frontend
decided what it meant with `startsWith('ok')` and a regex for the repo count.

That is how a dead credential went unnoticed for an unknown length of time. An
expired token produced `skipped: ...`, which rendered as one quiet line, so every
analysis silently fell back to resume-only evidence while still presenting a
readiness score as though GitHub had been consulted. For a project whose entire
claim is that evidence changes the number, silently losing the evidence is the
worst available failure.

So: a closed set of states, each with its own remedy, and a `severity` the UI
cannot misread. A fetch that did not happen is never reported as merely "skipped".
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class GitHubState(str, Enum):
    #: No username supplied. The only state that is genuinely uninteresting.
    NOT_REQUESTED = "not_requested"
    OK = "ok"
    #: Succeeded, but not everything was read (repo cap, budget, partial failure).
    PARTIAL = "partial"
    #: The configured GITHUB_TOKEN was rejected. Actionable by the operator, and
    #: invisible to the candidate unless we say so.
    TOKEN_REJECTED = "token_rejected"
    RATE_LIMITED = "rate_limited"
    USER_NOT_FOUND = "user_not_found"
    ERROR = "error"


#: States where evidence is missing or incomplete through no fault of the
#: candidate. The UI must show these prominently: a readiness score computed
#: without evidence means something different from one computed with it.
DEGRADED = frozenset({
    GitHubState.PARTIAL, GitHubState.TOKEN_REJECTED,
    GitHubState.RATE_LIMITED, GitHubState.ERROR,
})


@dataclass(frozen=True)
class GitHubStatus:
    state: GitHubState
    #: Written for whoever can act on it, not a raw exception string.
    message: str
    repos_analysed: int = 0

    @property
    def evidence_used(self) -> bool:
        return self.state in (GitHubState.OK, GitHubState.PARTIAL)

    @property
    def severity(self) -> str:
        """`info` | `warn` | `error` -- so the UI never guesses from a prefix."""
        if self.state is GitHubState.NOT_REQUESTED:
            return "info"
        if self.state is GitHubState.OK:
            return "info"
        if self.state is GitHubState.USER_NOT_FOUND:
            return "error"
        if self.state in DEGRADED:
            return "warn"
        return "warn"

    def as_dict(self) -> dict:
        return {
            "state": self.state.value,
            "message": self.message,
            "repos_analysed": self.repos_analysed,
            "evidence_used": self.evidence_used,
            "severity": self.severity,
        }


def not_requested() -> GitHubStatus:
    return GitHubStatus(
        state=GitHubState.NOT_REQUESTED,
        message="No GitHub username given, so this analysis uses resume claims only.",
    )


def ok(repos: int) -> GitHubStatus:
    return GitHubStatus(
        state=GitHubState.OK,
        message=f"Read {repos} public repositor{'y' if repos == 1 else 'ies'}.",
        repos_analysed=repos,
    )


def partial(repos: int, why: str) -> GitHubStatus:
    return GitHubStatus(
        state=GitHubState.PARTIAL,
        message=(f"Read {repos} repositories, but not all of them: {why}. "
                 f"Evidence may be incomplete, so absence here is not proof of absence."),
        repos_analysed=repos,
    )


def classify_error(exc: Exception) -> GitHubStatus:
    """Map a fetch failure onto a state with an actionable message.

    Deliberately never produces a bare "skipped": every branch says what failed
    and what to do, because the alternative is the silent degradation this module
    exists to prevent.
    """
    text = str(exc)
    low = text.lower()

    if "not found" in low:
        return GitHubStatus(
            state=GitHubState.USER_NOT_FOUND,
            message=f"{text}. Check the username spelling.",
        )
    if "rate limit" in low or "429" in low:
        return GitHubStatus(
            state=GitHubState.RATE_LIMITED,
            message=("GitHub rate limit reached, so no evidence could be read. "
                     "Without a token the limit is 60 requests/hour; set "
                     "GITHUB_TOKEN in backend/.env to raise it to 5,000. "
                     "This score reflects resume claims only."),
        )
    if "401" in low or "bad credentials" in low or "unauthorized" in low:
        return GitHubStatus(
            state=GitHubState.TOKEN_REJECTED,
            message=("The configured GITHUB_TOKEN was rejected (expired or "
                     "revoked), so no evidence could be read. Replace it in "
                     "backend/.env. This score reflects resume claims only."),
        )
    return GitHubStatus(
        state=GitHubState.ERROR,
        message=(f"GitHub evidence could not be read: {text}. This score "
                 f"reflects resume claims only."),
    )
