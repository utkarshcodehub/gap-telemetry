"""
Tests for the evidence model (core/evidence/model.py).

This is the project's thesis, so each test names the decision it pins and why that
decision is load-bearing. Pure unit tests -- no network, no database.

Reference: docs/EVIDENCE_MODEL.md
"""

from __future__ import annotations

import pytest

from core.evidence.model import (
    UnverifiableReason,
    AUTHOR_BONUS_CAP,
    CONTRADICTION_MIN_AUTHORED_REPOS,
    REPO_BONUS_CAP,
    TIER_BASE,
    TIER_RANK,
    EvidenceReport,
    SkillEvidence,
    Tier,
    Verdict,
    confidence,
    coverage,
    score,
    verdict,
)

MARKET = [
    {"canonical": "Python", "category": "programming_language", "demand_pct": 50.0},
    {"canonical": "Docker", "category": "cloud_devops", "demand_pct": 30.0},
    {"canonical": "React", "category": "frontend", "demand_pct": 20.0},
    {"canonical": "Communication", "category": "soft_skill", "demand_pct": 60.0},
]
# Basket: Python 50 + Docker 30 + React 20 = 100.

PLENTY = dict(coverage_value=1.0, authored_repo_count=20)


# ------------------------------------------------------------------- tiers

def test_attested_is_not_on_the_fabrication_scale():
    """EA is an assertion, not an artifact (section 2). Ranking it against E1-E4
    would imply it had been checked against something. KeyError is correct."""
    with pytest.raises(KeyError):
        TIER_RANK[Tier.ATTESTED]


def test_tier_ranks_are_strictly_increasing():
    ranks = [TIER_RANK[t] for t in (Tier.CLAIMED, Tier.MENTIONED, Tier.PRESENT,
                                    Tier.DECLARED, Tier.AUTHORED)]
    assert ranks == sorted(ranks) and len(set(ranks)) == len(ranks)


# -------------------------------------------------------------- confidence

def test_no_artifact_evidence_is_zero_confidence():
    assert confidence(SkillEvidence("X")) == 0.0


def test_tier_sets_the_floor():
    for tier, base in TIER_BASE.items():
        assert confidence(SkillEvidence("X", max_tier=tier)) == pytest.approx(base)


def test_bonuses_can_never_invert_the_tier_ordering():
    """The single most important property of the additive form.

    If maximum breadth/recency/authorship on a README mention could outrank a bare
    dependency declaration, the whole fabrication-difficulty premise of section 2
    would collapse.
    """
    best_e1 = confidence(SkillEvidence("X", Tier.MENTIONED, n_repos=50,
                                       recency_months=0.0, authorship_share=1.0))
    bare_e3 = confidence(SkillEvidence("X", Tier.DECLARED))
    assert best_e1 < bare_e3, f"E1-with-everything {best_e1} >= bare E3 {bare_e3}"


def test_e2_alone_reads_as_verified_not_as_half_verified():
    """The calibration decision of 2026-10-03, pinned.

    Only 26% of repos in this product's real population contain a parseable
    manifest, so E3 is unreachable for most candidates for reasons that have
    nothing to do with them. E2 therefore has to anchor "verified" on its own: a
    candidate whose every claim is demonstrated in the file tree must not read as
    half-verified because of which ecosystem they work in.
    """
    bare_e2 = confidence(SkillEvidence("X", Tier.PRESENT))
    assert bare_e2 >= 0.5, (
        "a file-tree hit with nothing else must still read as verified; see "
        "TIER_BASE's note and docs/baselines/channel_recall_2026-10-03.md")

    typical_e2 = confidence(SkillEvidence("X", Tier.PRESENT, n_repos=2,
                                          recency_months=3.0, authorship_share=1.0))
    assert typical_e2 >= 0.70, f"an ordinary good E2 profile reads {typical_e2}"


def test_e3_is_a_bonus_over_e2_not_a_different_league():
    """The ordering stays strict -- a declaration is harder to fabricate than a
    file -- but the step is bonus-sized. A chasm between them would be a claim
    about fabrication difficulty that the 26% finding does not support."""
    step = TIER_BASE[Tier.DECLARED] - TIER_BASE[Tier.PRESENT]
    assert 0 < step <= REPO_BONUS_CAP + AUTHOR_BONUS_CAP, (
        f"E2->E3 step is {step}; it should be comparable to the bonuses, not dwarf them")


def test_unknown_signals_are_not_penalties():
    """authorship_share is frequently None because the commits API is rate
    limited. That is our failure, not the candidate's, so it must only forgo a
    bonus -- never subtract. A multiplicative form would have zeroed this."""
    known_nothing = confidence(SkillEvidence("X", Tier.DECLARED))
    unknown_extras = confidence(SkillEvidence("X", Tier.DECLARED,
                                              recency_months=None,
                                              authorship_share=None))
    assert known_nothing == unknown_extras == pytest.approx(TIER_BASE[Tier.DECLARED])


def test_confidence_is_bounded_to_one():
    maxed = confidence(SkillEvidence("X", Tier.AUTHORED, n_repos=999,
                                     recency_months=0.0, authorship_share=1.0))
    assert 0.0 <= maxed <= 1.0


def test_each_bonus_is_capped_independently():
    base = TIER_BASE[Tier.PRESENT]
    repos_only = confidence(SkillEvidence("X", Tier.PRESENT, n_repos=999))
    assert repos_only == pytest.approx(base + REPO_BONUS_CAP)
    author_only = confidence(SkillEvidence("X", Tier.PRESENT, authorship_share=1.0))
    assert author_only == pytest.approx(base + AUTHOR_BONUS_CAP)


def test_recency_decays_and_stale_evidence_earns_nothing():
    fresh = confidence(SkillEvidence("X", Tier.PRESENT, recency_months=1.0))
    mid = confidence(SkillEvidence("X", Tier.PRESENT, recency_months=18.0))
    stale = confidence(SkillEvidence("X", Tier.PRESENT, recency_months=120.0))
    assert fresh > mid > stale == pytest.approx(TIER_BASE[Tier.PRESENT])


# ---------------------------------------------------------------- coverage

def test_coverage_is_none_when_nothing_is_assessable():
    """'nothing to check' and 'checked nothing' are different statements."""
    assert coverage([], claimed=set()) is None
    only_soft = [SkillEvidence("Communication", verifiable_by_design=False)]
    assert coverage(only_soft, claimed={"Communication"}) is None


def test_coverage_counts_retrieved_channels_not_verdicts():
    """Section 8.5: non-circular by construction. Checkability depends on what we
    fetched, never on what we concluded -- otherwise contradictions would raise
    coverage, and coverage licenses contradictions."""
    ev = [
        SkillEvidence("Python", channel_coverage=1.0),
        SkillEvidence("Docker", channel_coverage=1.0),
        SkillEvidence("React", channel_coverage=0.0),
    ]
    assert coverage(ev, claimed={"Python", "Docker", "React"}) == pytest.approx(2 / 3)


def test_coverage_is_graded_not_binary():
    """The revision (section 8.5). The old definition called a claim checkable if
    ANY repo yielded a channel, so coverage read 100% even when nine of ten
    fetches had failed. As the gate guarding against false contradictions, an
    always-1.0 value guards nothing."""
    ev = [SkillEvidence("Python", channel_coverage=0.1),
          SkillEvidence("Docker", channel_coverage=0.3)]
    assert coverage(ev, claimed={"Python", "Docker"}) == pytest.approx(0.2)


def test_partial_collection_shows_up_as_partial_coverage():
    """One repo read out of ten must not look like a complete assessment."""
    ev = [SkillEvidence("Python", channel_coverage=1 / 10)]
    cov = coverage(ev, claimed={"Python"})
    from core.evidence.model import CONTRADICTION_MIN_COVERAGE
    assert cov < CONTRADICTION_MIN_COVERAGE, (
        "coverage this thin must sit below the contradiction gate"
    )


def test_not_verifiable_by_design_skills_leave_the_denominator():
    """A candidate must not read as low-coverage because we cannot check
    'Communication'. It was never checkable by any amount of evidence."""
    ev = [
        SkillEvidence("Python", channel_coverage=1.0),
        SkillEvidence("Communication", verifiable_by_design=False),
    ]
    assert coverage(ev, claimed={"Python", "Communication"}) == 1.0


def test_attesting_many_skills_cannot_deflate_coverage():
    """The gaming vector section 8.5 closes.

    If attested claims counted in the denominator, attesting a pile of skills
    would drive coverage down, which would suppress CONTRADICTED on everything
    else. Excluding them from BOTH sides removes the lever.
    """
    ev = [SkillEvidence("Python", channel_coverage=1.0)] + [
        SkillEvidence(f"Private{i}", attested=True) for i in range(20)
    ]
    claimed = {"Python"} | {f"Private{i}" for i in range(20)}
    assert coverage(ev, claimed=claimed) == 1.0


def test_unclaimed_skills_are_not_in_coverage():
    ev = [SkillEvidence("Docker", channel_coverage=1.0)]
    assert coverage(ev, claimed=set()) is None


# ----------------------------------------------------------------- verdicts

@pytest.mark.parametrize("tier", [Tier.PRESENT, Tier.DECLARED, Tier.AUTHORED])
def test_e2_and_above_is_verified(tier):
    assert verdict(SkillEvidence("X", max_tier=tier), **PLENTY) is Verdict.VERIFIED


def test_e1_only_is_weak_not_verified():
    """E1 is README text the candidate wrote, which is exactly what the project
    argues is not evidence."""
    assert verdict(SkillEvidence("X", Tier.MENTIONED), **PLENTY) is Verdict.WEAK


def test_no_evidence_is_unverifiable():
    assert verdict(SkillEvidence("X"), **PLENTY) is Verdict.UNVERIFIABLE


def test_attestation_ranks_below_anything_checked_and_above_a_bare_claim():
    assert verdict(SkillEvidence("X", attested=True), **PLENTY) is Verdict.ATTESTED
    # ...but real evidence still wins.
    assert verdict(SkillEvidence("X", Tier.DECLARED, attested=True),
                   **PLENTY) is Verdict.VERIFIED


# --------------------------------------------- contradiction safety rule (s4)

def test_contradiction_fires_only_with_positive_counter_evidence():
    """It must NEVER follow from absence alone -- that is the whole rule.

    Uses Docker because the skill must also be on the absence allowlist; see
    test_contradiction_allowlist.py for that half.
    """
    absent = SkillEvidence("Docker", counter_evidence=False)
    assert verdict(absent, **PLENTY) is Verdict.UNVERIFIABLE

    accused = SkillEvidence("Docker", counter_evidence=True, authorship_share=0.9)
    assert verdict(accused, **PLENTY) is Verdict.CONTRADICTED


def test_contradiction_is_suppressed_at_low_coverage():
    """If we barely looked, we do not get to accuse. This is also why coverage has
    to be verdict-independent (section 8.5) or the gate is circular."""
    ev = SkillEvidence("Docker", counter_evidence=True, authorship_share=0.9)
    assert verdict(ev, coverage_value=0.2, authored_repo_count=20) is Verdict.UNVERIFIABLE
    assert verdict(ev, coverage_value=None, authored_repo_count=20) is Verdict.UNVERIFIABLE


def test_contradiction_is_suppressed_without_enough_analysed_material():
    ev = SkillEvidence("Docker", counter_evidence=True, authorship_share=0.9)
    assert verdict(ev, coverage_value=1.0,
                   authored_repo_count=CONTRADICTION_MIN_AUTHORED_REPOS - 1
                   ) is Verdict.UNVERIFIABLE


def test_contradiction_never_fires_against_attested_private_work():
    """Accusing someone over work they told us they cannot show is the single
    worst output this system could produce."""
    ev = SkillEvidence("Docker", counter_evidence=True, attested=True,
                       authorship_share=0.9)
    assert verdict(ev, **PLENTY) is Verdict.ATTESTED


def test_contradiction_never_fires_for_a_non_artifact_skill():
    ev = SkillEvidence("Communication", counter_evidence=True,
                       verifiable_by_design=False, authorship_share=0.9)
    assert verdict(ev, **PLENTY) is Verdict.UNVERIFIABLE


def test_contradiction_is_suppressed_when_the_code_is_mostly_someone_elses():
    """Low authorship means the repo's contents say little about this person."""
    ev = SkillEvidence("Docker", counter_evidence=True, authorship_share=0.1)
    assert verdict(ev, **PLENTY) is Verdict.UNVERIFIABLE


def test_unknown_authorship_does_not_block_contradiction():
    """Unknown is not the same as low: requiring a known-high share would make the
    verdict unreachable whenever the commits API is unavailable."""
    ev = SkillEvidence("Docker", counter_evidence=True, authorship_share=None)
    assert verdict(ev, **PLENTY) is Verdict.CONTRADICTED


# ---------------------------------------------------------------- readiness

def _ev(**kw) -> SkillEvidence:
    return SkillEvidence(**kw)


def test_claimed_readiness_counts_only_resume_claims():
    """Section 8.1. It is E1's control condition, so artifact-derived skills must
    not leak in -- that would credit the control with part of the treatment."""
    r = score(MARKET, claimed={"Python"},
              evidence=[_ev(skill="Docker", max_tier=Tier.DECLARED, n_repos=3)])
    assert r.claimed_readiness == 50.0, "Docker is evidenced but never claimed"


def test_verified_readiness_is_confidence_weighted_and_below_claimed():
    r = score(MARKET, claimed={"Python", "Docker"}, evidence=[
        _ev(skill="Python", max_tier=Tier.DECLARED, n_repos=3,
            recency_months=1.0, authorship_share=0.9, channel_coverage=1.0),
        _ev(skill="Docker", channel_coverage=1.0),   # claimed, no evidence
    ])
    assert r.claimed_readiness == 80.0
    assert 0 < r.verified_readiness < r.claimed_readiness
    # Only Python contributes, at its confidence.
    assert r.verified_readiness == pytest.approx(
        50.0 * confidence(_ev(skill="Python", max_tier=Tier.DECLARED, n_repos=3,
                              recency_months=1.0, authorship_share=0.9)), abs=0.1)


def test_a_fully_unevidenced_candidate_has_zero_verified_readiness():
    """The empty-GitHub majority case (EC-1). Coverage is what explains it, not a
    penalty -- so the number is 0 but every claim reads UNVERIFIABLE."""
    r = score(MARKET, claimed={"Python", "Docker", "React"}, evidence=[])
    assert r.claimed_readiness == 100.0
    assert r.verified_readiness == 0.0
    assert all(a.verdict is Verdict.UNVERIFIABLE for a in r.assessments)


def test_attested_skills_are_excluded_from_verified_readiness():
    """Section 8.4: self-attestation must not raise a number called 'verified', or
    the adversarial evaluation has a one-line exploit."""
    r = score(MARKET, claimed={"Python"},
              evidence=[_ev(skill="Python", attested=True)])
    assert r.claimed_readiness == 50.0
    assert r.verified_readiness == 0.0
    assert r.attested_skills == ("Python",)


def test_attesting_everything_cannot_inflate_verified_readiness():
    r = score(MARKET, claimed={"Python", "Docker", "React"}, evidence=[
        _ev(skill=s, attested=True) for s in ("Python", "Docker", "React")
    ])
    assert r.verified_readiness == 0.0
    assert len(r.attested_skills) == 3


def test_unclaimed_verified_skills_sit_outside_both_numbers():
    """Section 8.6: reported as advice, never folded into a score."""
    r = score(MARKET, claimed={"Python"}, evidence=[
        _ev(skill="Python", max_tier=Tier.DECLARED, channel_coverage=1.0),
        _ev(skill="Docker", max_tier=Tier.DECLARED, n_repos=3),  # never claimed
    ])
    assert r.unclaimed_verified_skills == ("Docker",)
    assert r.claimed_readiness == 50.0, "Docker excluded from claimed"
    assert r.verified_readiness < 50.0, "and excluded from verified"


def test_weakly_evidenced_unclaimed_skills_are_not_reported_as_verified():
    r = score(MARKET, claimed=set(),
              evidence=[_ev(skill="Docker", max_tier=Tier.MENTIONED, n_repos=9)])
    assert r.unclaimed_verified_skills == ()


def test_soft_skills_are_outside_the_basket_entirely():
    r = score(MARKET, claimed={"Communication"}, evidence=[])
    assert r.claimed_readiness == 0.0, "Communication is not in the demand basket"


def test_empty_market_does_not_divide_by_zero():
    r = score([], claimed={"Python"}, evidence=[])
    assert isinstance(r, EvidenceReport)
    assert r.claimed_readiness == 0.0 and r.verified_readiness == 0.0


# ------------------------------------- UNVERIFIABLE reason (five verdicts kept)

def test_by_design_and_insufficient_artifacts_are_distinguished():
    """One verdict was carrying two different meanings.

    "System Design" can never be verified by any amount of evidence (EC-9), while
    "Docker" simply was not found in this candidate's public code (EC-1).
    Reporting both as a bare UNVERIFIABLE tells a student their fundamentals are
    unproven when the system was never able to look.
    """
    r = score(MARKET, claimed={"Python"}, evidence=[
        _ev(skill="Python", verifiable_by_design=False),
    ])
    a = next(a for a in r.assessments if a.skill == "Python")
    assert a.verdict is Verdict.UNVERIFIABLE
    assert a.unverifiable_reason is UnverifiableReason.BY_DESIGN

    r2 = score(MARKET, claimed={"Python"}, evidence=[
        _ev(skill="Python", channel_coverage=1.0),
    ])
    a2 = next(a for a in r2.assessments if a.skill == "Python")
    assert a2.verdict is Verdict.UNVERIFIABLE
    assert a2.unverifiable_reason is UnverifiableReason.INSUFFICIENT_ARTIFACTS


def test_reason_is_only_set_for_unverifiable():
    r = score(MARKET, claimed={"Python"},
              evidence=[_ev(skill="Python", max_tier=Tier.DECLARED)])
    a = next(a for a in r.assessments if a.skill == "Python")
    assert a.verdict is Verdict.VERIFIED
    assert a.unverifiable_reason is None


# --------------------------------- CONTRADICTED requires a complete profile

def test_contradiction_is_suppressed_on_a_partial_profile():
    """If the repo cap, a rate limit, or an exhausted budget stopped us short, the
    skill may be in a repo we never opened. Absence then says nothing about the
    candidate -- only about our collection."""
    ev = _ev(skill="Docker", counter_evidence=True, authorship_share=0.9,
             channel_coverage=1.0)
    assert verdict(ev, coverage_value=1.0, authored_repo_count=20,
                   profile_partial=True) is Verdict.UNVERIFIABLE
    assert verdict(ev, coverage_value=1.0, authored_repo_count=20,
                   profile_partial=False) is Verdict.CONTRADICTED


def test_score_passes_partial_through_to_the_gate():
    ev = [_ev(skill="Docker", counter_evidence=True, authorship_share=0.9,
              channel_coverage=1.0, n_repos=20)]
    partial = score(MARKET, claimed={"Docker"}, evidence=ev, profile_partial=True,
                    reveal_contradictions=True)
    complete = score(MARKET, claimed={"Docker"}, evidence=ev, profile_partial=False,
                     reveal_contradictions=True)
    assert partial.assessments[0].verdict is Verdict.UNVERIFIABLE
    assert complete.assessments[0].verdict is Verdict.CONTRADICTED


# ------------------------------- every claim is assessed (section 8.7)

def test_claims_outside_the_demand_basket_still_get_verdicts():
    """Section 8.7. The basket decides what moves a PERCENTAGE, not what gets
    looked at.

    Before this, a backend-role analysis silently dropped FastAPI, Supabase and
    Pandas because their demand sits under the 5% floor -- and a reader cannot tell
    "below the floor" from "unverified" when both simply fail to appear.
    """
    r = score(MARKET, claimed={"Python", "Kubernetes"}, evidence=[
        _ev(skill="Python", max_tier=Tier.DECLARED, channel_coverage=1.0),
        _ev(skill="Kubernetes", max_tier=Tier.DECLARED, channel_coverage=1.0),
    ])
    assessed = {a.skill: a for a in r.assessments}
    assert set(assessed) == {"Python", "Kubernetes"}
    assert assessed["Kubernetes"].verdict is Verdict.VERIFIED, (
        "Kubernetes is not in MARKET's basket, but the claim was still assessed"
    )
    assert assessed["Kubernetes"].in_demand_basket is False
    assert assessed["Kubernetes"].demand_pct is None
    assert assessed["Python"].in_demand_basket is True
    assert assessed["Python"].demand_pct == 50.0


def test_out_of_basket_claims_do_not_move_either_percentage():
    with_extra = score(MARKET, claimed={"Python", "Kubernetes"}, evidence=[
        _ev(skill="Python", max_tier=Tier.DECLARED, channel_coverage=1.0),
        _ev(skill="Kubernetes", max_tier=Tier.AUTHORED, n_repos=9,
            channel_coverage=1.0),
    ])
    without = score(MARKET, claimed={"Python"}, evidence=[
        _ev(skill="Python", max_tier=Tier.DECLARED, channel_coverage=1.0),
    ])
    assert with_extra.claimed_readiness == without.claimed_readiness
    assert with_extra.verified_readiness == without.verified_readiness


# ------------------------- CONTRADICTED is computed but hidden by default

def test_contradicted_is_hidden_by_default_and_reported_as_unverifiable():
    """The verdict that could wrong an honest candidate ships switched off.

    Until Dataset A validates the rule, a claim the engine WOULD contradict is
    reported as UNVERIFIABLE -- the honest fallback -- and the suppression is
    recorded so the rule's hit rate can be measured before anyone sees it.
    """
    ev = [_ev(skill="Docker", counter_evidence=True, authorship_share=0.9,
              channel_coverage=1.0, n_repos=20)]

    hidden = score(MARKET, claimed={"Docker"}, evidence=ev)
    a = hidden.assessments[0]
    assert a.verdict is Verdict.UNVERIFIABLE
    assert a.unverifiable_reason is UnverifiableReason.INSUFFICIENT_ARTIFACTS
    assert a.suppressed_contradiction is True, (
        "the computed verdict must be recorded, not discarded -- Dataset A needs it"
    )

    shown = score(MARKET, claimed={"Docker"}, evidence=ev,
                  reveal_contradictions=True)
    b = shown.assessments[0]
    assert b.verdict is Verdict.CONTRADICTED
    assert b.suppressed_contradiction is False


def test_suppression_is_not_claimed_for_ordinary_unverifiable_claims():
    r = score(MARKET, claimed={"Docker"}, evidence=[_ev(skill="Docker")])
    a = r.assessments[0]
    assert a.verdict is Verdict.UNVERIFIABLE
    assert a.suppressed_contradiction is False, (
        "no contradiction was computed, so nothing was suppressed"
    )
