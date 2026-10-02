"""
Tests for the claim-only baseline (core/gap/baseline.py).

The baseline exists so that "evidence grading is better than claim-only" can be
measured rather than asserted (experiment E1). That only works if the baseline is
reproducible and if it records what the plan leaves open. Both are tested here.

Pure unit tests against a fixed market -- no database.
"""

from __future__ import annotations

from core.gap.baseline import as_dict, baseline_for_role

# A deliberately small market so the arithmetic is checkable by hand.
# Soft skills and anything under MIN_DEMAND_PCT (5.0) are excluded from the
# basket by score_gap, so Communication and Obscure are here to prove it.
MARKET = [
    {"canonical": "Python", "category": "programming_language", "demand_pct": 60.0},
    {"canonical": "Docker", "category": "cloud_devops", "demand_pct": 30.0},
    {"canonical": "React", "category": "frontend", "demand_pct": 10.0},
    {"canonical": "Communication", "category": "soft_skill", "demand_pct": 50.0},
    {"canonical": "Obscure", "category": "backend", "demand_pct": 1.0},
]
# Basket = Python 60 + Docker 30 + React 10 = 100 total demand.


def test_resume_only_readiness_is_demand_weighted():
    b = baseline_for_role("r", MARKET, {"Python"})
    assert b.readiness_resume_only == 60.0, "Python is 60 of 100 basket demand"
    assert b.basket_size == 3, "soft skills and sub-threshold skills are excluded"


def test_github_corroborating_the_resume_moves_the_score_by_nothing():
    """The baseline fact that motivates the whole evidence model.

    Today's scoring unions resume and GitHub skills, so GitHub only ever ADDS
    skills the resume omitted. When GitHub *corroborates* a claim -- the common
    case, and the entire point of verification -- it contributes exactly zero to
    readiness. Evidence is cosmetic: a label printed beside a number it did not
    help produce.
    """
    b = baseline_for_role("r", MARKET, {"Python", "Docker"},
                          {"Python": 5, "Docker": 3})
    assert b.readiness_resume_only == 90.0
    assert b.readiness_union == 90.0
    assert b.delta_union_minus_resume_only == 0.0, (
        "five repos of corroborating Python evidence must currently change "
        "nothing -- if this ever becomes non-zero, scoring has changed"
    )


def test_github_only_skills_are_the_sole_way_github_moves_the_score():
    b = baseline_for_role("r", MARKET, {"Python"}, {"Docker": 2})
    assert b.readiness_resume_only == 60.0
    assert b.readiness_union == 90.0
    assert b.delta_union_minus_resume_only == 30.0
    assert b.n_hidden_strengths == 1, "Docker is on GitHub but not claimed"


def test_both_readiness_definitions_are_recorded():
    """docs/EVIDENCE_MODEL.md section 8.1: the plan defines claimed_readiness two
    incompatible ways. Both are measured so the choice can be made later without
    re-running anything, and neither is privileged here."""
    b = baseline_for_role("r", MARKET, {"Python"}, {"Docker": 1})
    d = as_dict(b)
    assert "readiness_resume_only" in d
    assert "readiness_union" in d
    assert "delta_union_minus_resume_only" in d


def test_empty_profile_is_a_legitimate_state_not_an_error():
    b = baseline_for_role("r", MARKET, set(), {})
    assert b.readiness_resume_only == 0.0
    assert b.readiness_union == 0.0
    assert b.n_gaps == 3, "every basket skill becomes a gap"


def test_ranking_is_captured_not_just_the_score():
    """E1 measures rank correlation against ground truth, not only the headline
    number, so a change in gap ORDER has to be visible in the baseline."""
    b = baseline_for_role("r", MARKET, set())
    assert b.top_gaps == ["Python", "Docker", "React"], "ordered by demand"


def test_gap_tiers_and_evidence_labels_are_counted():
    b = baseline_for_role("r", MARKET, {"Python"}, {"Python": 2, "Docker": 1})
    assert sum(b.gaps_by_tier.values()) == b.n_gaps
    assert sum(b.strengths_by_evidence.values()) == b.n_strengths
    assert b.strengths_by_evidence.get("resume+github") == 1, "Python is both"
    assert b.strengths_by_evidence.get("github") == 1, "Docker is GitHub-only"


def test_is_deterministic():
    """A snapshot diff must be attributable to a code change, so identical inputs
    must give byte-identical output."""
    args = ("r", MARKET, {"Python", "React"}, {"Docker": 2})
    assert as_dict(baseline_for_role(*args)) == as_dict(baseline_for_role(*args))


def test_an_empty_market_does_not_divide_by_zero():
    b = baseline_for_role("r", [], {"Python"}, {"Python": 1})
    assert b.readiness_resume_only == 0.0
    assert b.readiness_union == 0.0
    assert b.basket_size == 0
