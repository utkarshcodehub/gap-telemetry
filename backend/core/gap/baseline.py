"""
Claim-only baseline, recorded before the evidence engine exists.

The project's central claim is that evidence-graded readiness is measurably better
than claim-only readiness (experiment E1). That comparison is impossible to make
honestly after the fact: once scoring changes, the "before" number is gone, and a
baseline reconstructed later is just the new code with a flag flipped.

So this captures the current behaviour as a frozen, reproducible artifact. It is a
GOLDEN-OUTPUT baseline, not an accuracy measurement -- accuracy needs labelled
ground truth, which arrives with Dataset A in Increment 3. What it gives now is the
ability to say exactly what changed and by how much, the moment scoring moves.

`claimed_readiness` is RESUME-ONLY (decided, `docs/EVIDENCE_MODEL.md` §8.1). It is
the control condition in E1, so it has to be a pure self-report: a baseline that
already contained GitHub signal would credit the control with part of the treatment
and understate the measured effect.

`legacy_union_readiness` records the `resume | github` behaviour this codebase
shipped before the evidence model. It is kept as a labelled reference -- for the
report, and because the regression tests pin it -- and is never the baseline and
never shown to a candidate.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from collections import Counter

from core.gap.scorer import GapReport, score_gap


@dataclass(frozen=True)
class RoleBaseline:
    role: str
    basket_size: int

    #: THE BASELINE: resume claims only, nothing else (EVIDENCE_MODEL section 8.1).
    claimed_readiness: float
    #: Reference only -- the shipped `resume_skills | set(github_skills)` number.
    #: Labelled legacy, never the baseline, never shown to a candidate.
    legacy_union_readiness: float
    #: Exactly the amount a union baseline would have wrongly credited to E1's
    #: control condition. Useful to report: it quantifies why section 8.1 matters.
    delta_legacy_minus_claimed: float

    n_gaps: int
    gaps_by_tier: dict[str, int]
    n_strengths: int
    strengths_by_evidence: dict[str, int]
    n_hidden_strengths: int
    n_extras: int

    #: Top gaps, so a change in RANKING is visible and not just a change in the
    #: headline number. E1 measures rank correlation, not only the score.
    top_gaps: list[str]


def _summarise(report: GapReport) -> dict:
    return {
        "n_gaps": len(report.gaps),
        "gaps_by_tier": dict(Counter(g.tier for g in report.gaps)),
        "n_strengths": len(report.strengths),
        "strengths_by_evidence": dict(Counter(s.evidence for s in report.strengths)),
        "n_hidden_strengths": len(report.hidden_strengths),
        "n_extras": len(report.extras),
        "top_gaps": [g.canonical for g in report.gaps[:10]],
    }


def baseline_for_role(
    role: str,
    market: list[dict],
    resume_skills: set[str],
    github_skills: dict[str, int] | None = None,
) -> RoleBaseline:
    """Score one profile against one role's market, both ways."""
    github_skills = github_skills or {}

    resume_only = score_gap(role, market, resume_skills, github_skills=None)
    union = score_gap(role, market, resume_skills, github_skills=github_skills)

    # The union report is the one that describes shipped behaviour, so its
    # structure is what a later diff should be compared against.
    summary = _summarise(union)

    return RoleBaseline(
        role=role,
        basket_size=union.total_market_skills,
        claimed_readiness=resume_only.readiness_score,
        legacy_union_readiness=union.readiness_score,
        delta_legacy_minus_claimed=round(
            union.readiness_score - resume_only.readiness_score, 1
        ),
        **summary,
    )


def as_dict(b: RoleBaseline) -> dict:
    return asdict(b)
