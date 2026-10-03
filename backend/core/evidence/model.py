"""
The evidence model: tiers -> confidence -> verdict -> readiness.

Implements docs/EVIDENCE_MODEL.md. Pure functions over an evidence bundle, with no
network and no database, so every decision in that document is testable in
isolation and the thresholds can be tuned on Dataset A without touching the
callers.

Nothing here replaces core/gap/scorer.py yet. That module keeps shipping the
legacy `resume | github` union while this one is built and measured against the
baseline in core/gap/baseline.py.

Every threshold is a NAMED CONSTANT with a comment saying what it protects
(EVIDENCE_MODEL section 8.3). They start strict on purpose: a missed contradiction
costs one absent insight, while a false one tells an honest candidate they look
like a liar. Tuning loosens from here only as far as labelled data justifies.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

# --------------------------------------------------------------------- tiers


class Tier(str, Enum):
    """Evidence tiers, ordered by how hard the signal is to fabricate."""

    CLAIMED = "E0"      # resume text
    ATTESTED = "EA"     # candidate asserts private/work evidence
    MENTIONED = "E1"    # repo README / description / topics -- candidate-authored
    PRESENT = "E2"      # file tree: Dockerfile, *.tf, .github/workflows/
    DECLARED = "E3"     # dependency-manifest entry
    AUTHORED = "E4"     # E2/E3 in a repo with verified commit authorship


#: Fabrication-difficulty rank. EA is DELIBERATELY ABSENT: it is an assertion, not
#: an artifact, so it does not sit on this scale at all (EVIDENCE_MODEL section 2).
#: Looking EA up here is a bug, and KeyError is the right outcome.
TIER_RANK: dict[Tier, int] = {
    Tier.CLAIMED: 0,
    Tier.MENTIONED: 1,
    Tier.PRESENT: 2,
    Tier.DECLARED: 3,
    Tier.AUTHORED: 4,
}

#: A claim at or above this tier counts as independently verified.
VERIFIED_AT_OR_ABOVE = Tier.PRESENT


class UnverifiableReason(str, Enum):
    """Why a claim could not be verified. Five verdicts stay five; this splits the
    one verdict that was carrying two completely different meanings.

    BY_DESIGN is not a failure and must never read as one: no quantity of evidence
    could verify "System Design" (EC-9). INSUFFICIENT_ARTIFACTS is a statement
    about this candidate's public surface, which is the empty-GitHub majority case
    (EC-1). Conflating them tells a student their concepts are unproven when the
    system was never able to look.
    """

    BY_DESIGN = "by_design"
    INSUFFICIENT_ARTIFACTS = "insufficient_artifacts"


class Verdict(str, Enum):
    VERIFIED = "VERIFIED"
    WEAK = "WEAK"
    ATTESTED = "ATTESTED"
    UNVERIFIABLE = "UNVERIFIABLE"
    CONTRADICTED = "CONTRADICTED"


# ----------------------------------------------------------------- constants
# Confidence is ADDITIVE with capped bonuses (EVIDENCE_MODEL section 8.2):
# max_tier sets a floor, the other signals can only add, each capped, total
# clamped to [0, 1]. A multiplicative form would let one missing signal zero out
# four present ones -- and authorship_share is frequently missing because the
# commits API is rate-limited, which is our failure, not the candidate's.

#: Floor contributed by the strongest evidence found. The jump from E1 to E2 is
#: the largest on purpose: it is the step from candidate-authored prose to an
#: artifact their toolchain produced.
#: Recalibrated 2026-10-03 from the cohort measurement: **E2 PRESENT is the
#: working ceiling and E3 DECLARED is a bonus on top of it**, not the other way
#: round.
#:
#: Only 26% of repos in a 349-repo sample of this product's actual population
#: contained a parseable dependency manifest at all (DSA-solution repos, static
#: pages and course work declare nothing), so for roughly three repos in four the
#: MANIFEST channel does not exist and E3 is unreachable no matter what the
#: candidate can do. The earlier ladder put E2 at 0.45 -- below half -- which
#: meant a candidate whose every claim was genuinely demonstrated in the file tree
#: still read as weakly verified, and verified_readiness would have been
#: systematically depressed for the majority by an artifact of which ecosystem
#: they work in rather than by anything about them.
#:
#: So E2 anchors "verified" and E3 adds to it. The ordering is strictly preserved
#: -- a declaration still beats a file, because it is still harder to fabricate --
#: but the step is bonus-sized rather than a chasm. Full measurement:
#: docs/baselines/channel_recall_2026-10-03.md.
#:
#: These are the constants Dataset A exists to validate (E1/E2). They are stated
#: here, with the reasoning, so the experiment can disagree with them.
TIER_BASE: dict[Tier, float] = {
    Tier.MENTIONED: 0.15,
    Tier.PRESENT: 0.55,
    Tier.DECLARED: 0.70,
    Tier.AUTHORED: 0.85,
}

#: Breadth. Capped so twenty throwaway repos cannot lift an E1 mention above a
#: single E3 declaration -- that would invert the tier ordering section 2 exists
#: to establish.
REPO_BONUS_PER_REPO = 0.025
REPO_BONUS_CAP = 0.10

#: Recency. Evidence decays: a skill last touched years ago is weaker evidence of
#: current ability than the same skill touched last month (FR-14).
RECENCY_BONUS_CAP = 0.06
RECENCY_FULL_WITHIN_MONTHS = 6.0
RECENCY_ZERO_AFTER_MONTHS = 36.0

#: Authorship. Distinguishes "this is in a repo I own" from "I wrote this".
AUTHOR_BONUS_CAP = 0.10
AUTHOR_SHARE_FOR_FULL_BONUS = 0.50

# Contradiction thresholds. Deliberately strict -- see the module docstring.
#: Below this many repos we successfully analysed, absence means nothing.
CONTRADICTION_MIN_AUTHORED_REPOS = 5
#: Below this verification coverage, we did not look hard enough to accuse anyone.
CONTRADICTION_MIN_COVERAGE = 0.60
#: Below this share of commits, the code is not meaningfully theirs, so its
#: contents say nothing about what they personally can do.
CONTRADICTION_MIN_AUTHORSHIP_SHARE = 0.50


# ------------------------------------------------------------------- bundles


@dataclass(frozen=True)
class SkillEvidence:
    """Everything known about one skill for one candidate."""

    skill: str

    #: Strongest artifact tier found, or None when no artifact evidence exists.
    #: Never Tier.ATTESTED -- attestation is carried by `attested` below.
    max_tier: Tier | None = None
    #: Distinct repos supplying artifact evidence.
    n_repos: int = 0
    #: Distinct repos where a channel capable of proving this skill was READ.
    #: Distinct from n_repos, which counts where it was FOUND. The contradiction
    #: message must quote this one -- saying "we looked across 0 repositories"
    #: makes a well-founded accusation read as baseless.
    repos_with_channel: int = 0
    #: Months since the most recent evidence was touched. None = unknown.
    recency_months: float | None = None
    #: Candidate's share of commits in the evidencing repo(s). None = unknown,
    #: which must not be punished (section 8.2).
    authorship_share: float | None = None

    #: Share of in-scope repos where a channel capable of carrying this skill's
    #: signal was successfully retrieved (section 8.5). Verdict-independent,
    #: which is what keeps coverage non-circular. 0.0 means we never managed to
    #: look anywhere; None means the question does not apply because the skill is
    #: not artifact-verifiable.
    channel_coverage: float | None = None
    #: Can this skill ever be evidenced by an artifact? False for soft skills and
    #: process/methodology (EC-9) -- excluded from coverage entirely.
    verifiable_by_design: bool = True
    #: Candidate declares private/work evidence (EA, FR-41).
    attested: bool = False

    #: Positive counter-evidence: the skill would necessarily have appeared in
    #: artifacts we did retrieve, and it did not. Set by the engine that inspects
    #: artifacts, not inferred here from absence.
    counter_evidence: bool = False

    @property
    def channels_retrieved(self) -> bool:
        """True when at least some artifact surface was retrieved for this skill."""
        return bool(self.channel_coverage)


@dataclass(frozen=True)
class SkillAssessment:
    skill: str
    verdict: Verdict
    confidence: float
    max_tier: Tier | None
    n_repos: int
    claimed: bool
    #: Set only when verdict is UNVERIFIABLE. Lets a caller separate "nothing
    #: could ever check this" from "we could not check it for you".
    unverifiable_reason: UnverifiableReason | None = None
    #: True when the engine computed CONTRADICTED but the reveal flag was off, so
    #: the verdict reported above is UNVERIFIABLE instead. Recorded rather than
    #: discarded: Dataset A needs to know how often the rule WOULD have fired, to
    #: measure it before it is ever shown to a candidate.
    suppressed_contradiction: bool = False
    #: Whether this role's demand basket contains the skill. Verdicts are produced
    #: for every claim; only the readiness PERCENTAGE depends on the basket, so a
    #: claim outside it is assessed but contributes nothing to the score.
    in_demand_basket: bool = True
    #: The skill's market demand, or None when outside the basket.
    demand_pct: float | None = None


# ---------------------------------------------------------------- confidence


def _repo_bonus(n_repos: int) -> float:
    return min(REPO_BONUS_CAP, max(0, n_repos - 1) * REPO_BONUS_PER_REPO)


def _recency_bonus(months: float | None) -> float:
    """Unknown recency earns no bonus, but is never a penalty."""
    if months is None:
        return 0.0
    if months <= RECENCY_FULL_WITHIN_MONTHS:
        return RECENCY_BONUS_CAP
    if months >= RECENCY_ZERO_AFTER_MONTHS:
        return 0.0
    span = RECENCY_ZERO_AFTER_MONTHS - RECENCY_FULL_WITHIN_MONTHS
    return RECENCY_BONUS_CAP * (1.0 - (months - RECENCY_FULL_WITHIN_MONTHS) / span)


def _author_bonus(share: float | None) -> float:
    if share is None:
        return 0.0
    return min(AUTHOR_BONUS_CAP,
               AUTHOR_BONUS_CAP * (share / AUTHOR_SHARE_FOR_FULL_BONUS))


def confidence(ev: SkillEvidence) -> float:
    """Continuous [0, 1] confidence. Additive, capped, clamped (section 8.2)."""
    if ev.max_tier is None:
        return 0.0
    base = TIER_BASE.get(ev.max_tier, 0.0)
    total = (base
             + _repo_bonus(ev.n_repos)
             + _recency_bonus(ev.recency_months)
             + _author_bonus(ev.authorship_share))
    return round(min(1.0, max(0.0, total)), 4)


# ------------------------------------------------------------------ coverage


def coverage(evidence: list[SkillEvidence], claimed: set[str]) -> float | None:
    """Mean per-claim channel coverage, or None when nothing is assessable.

    Each assessable claim carries `channel_coverage`: the share of IN-SCOPE REPOS
    where a channel capable of proving it was successfully retrieved. This is the
    mean of those (section 8.5, revised).

    The earlier definition counted a claim as "checkable" if ANY repo had yielded
    a usable channel, which made coverage effectively binary -- it read 100%
    whenever a single repo came back, even if nine others had failed. As the gate
    protecting against false contradictions, a near-always-1.0 value protects
    nothing. Averaging per-repo retrieval instead makes partial collection show up
    as partial, which is what the gate needs to see.

    Still non-circular: no term consults a verdict. Attested claims are excluded
    from the mean entirely -- otherwise attesting many skills would drag coverage
    down and suppress CONTRADICTED across the board, which is a gaming vector.
    """
    assessable = [e for e in evidence
                  if e.skill in claimed and e.verifiable_by_design and not e.attested]
    if not assessable:
        return None
    per_claim = [e.channel_coverage or 0.0 for e in assessable]
    # Deliberately NOT rounded: this value is compared against
    # CONTRADICTION_MIN_COVERAGE, and rounding a gate input can flip a boundary
    # case. Rounding for display is the caller's job.
    return sum(per_claim) / len(per_claim)


# ------------------------------------------------------------------- verdict


def verdict(
    ev: SkillEvidence,
    *,
    coverage_value: float | None,
    authored_repo_count: int,
    profile_partial: bool = False,
) -> Verdict:
    """Classify one CLAIMED skill.

    The contradiction safety rule (section 4) lives here. CONTRADICTED requires
    positive counter-evidence AND enough analysed material AND enough coverage AND
    enough authorship. It never fires from absence alone, never at low coverage,
    and never against an attested skill.
    """
    tier = ev.max_tier
    if tier is not None and TIER_RANK[tier] >= TIER_RANK[VERIFIED_AT_OR_ABOVE]:
        return Verdict.VERIFIED

    if ev.counter_evidence and _contradiction_permitted(
        ev, coverage_value=coverage_value, authored_repo_count=authored_repo_count,
        profile_partial=profile_partial,
    ):
        return Verdict.CONTRADICTED

    # Attestation ranks above a bare claim but below anything checked, so it is
    # only consulted once VERIFIED and CONTRADICTED are ruled out.
    if ev.attested:
        return Verdict.ATTESTED

    if tier is Tier.MENTIONED:
        return Verdict.WEAK

    return Verdict.UNVERIFIABLE


def _contradiction_permitted(
    ev: SkillEvidence, *, coverage_value: float | None, authored_repo_count: int,
    profile_partial: bool = False,
) -> bool:
    from core.evidence.absence import can_be_contradicted
    if not can_be_contradicted(ev.skill):
        # Defence in depth: the allowlist is enforced here too, so a caller that
        # sets counter_evidence directly cannot bypass it.
        return False
    if profile_partial:
        # We did not see the whole profile -- because of the repo cap, a rate
        # limit, or an exhausted budget. The skill may well be in a repo we never
        # opened, so absence here is not counter-evidence about the candidate.
        return False
    if ev.attested:
        return False            # never accuse work we were told is private
    if not ev.verifiable_by_design:
        return False            # absence of a soft skill in code means nothing
    if authored_repo_count < CONTRADICTION_MIN_AUTHORED_REPOS:
        return False
    if coverage_value is None or coverage_value < CONTRADICTION_MIN_COVERAGE:
        return False
    share = ev.authorship_share
    if share is not None and share < CONTRADICTION_MIN_AUTHORSHIP_SHARE:
        return False
    return True


def unverifiable_reason_for(ev: SkillEvidence) -> UnverifiableReason:
    """Why this claim is UNVERIFIABLE. Only meaningful for that verdict."""
    if not ev.verifiable_by_design:
        return UnverifiableReason.BY_DESIGN
    return UnverifiableReason.INSUFFICIENT_ARTIFACTS


# ----------------------------------------------------------------- readiness


@dataclass(frozen=True)
class EvidenceReport:
    claimed_readiness: float
    verified_readiness: float
    verification_coverage: float | None
    assessments: tuple[SkillAssessment, ...] = field(default=())
    #: Reported separately, outside BOTH readiness numbers (sections 8.4, 8.6).
    attested_skills: tuple[str, ...] = field(default=())
    unclaimed_verified_skills: tuple[str, ...] = field(default=())


def score(
    market: list[dict],
    claimed: set[str],
    evidence: list[SkillEvidence],
    *,
    min_demand_pct: float = 5.0,
    soft_categories: frozenset[str] = frozenset({"soft_skill"}),
    profile_partial: bool = False,
    reveal_contradictions: bool = False,
) -> EvidenceReport:
    """Produce both readiness numbers plus what sits outside them.

    `claimed_readiness` counts ONLY resume claims (section 8.1): it is E1's control
    condition, so including artifact-derived skills would credit the control with
    part of the treatment.
    """
    basket = [m for m in market
              if m["demand_pct"] >= min_demand_pct
              and m["category"] not in soft_categories]
    total_demand = sum(m["demand_pct"] for m in basket)

    by_skill = {e.skill: e for e in evidence}
    cov = coverage(evidence, claimed)
    authored_repos = max((e.n_repos for e in evidence), default=0)

    demand_by_skill = {m["canonical"]: m["demand_pct"] for m in basket}

    claimed_demand = 0.0
    verified_demand = 0.0
    assessments: list[SkillAssessment] = []

    # EVERY claim is assessed, whether or not this role's market wants it. The
    # demand basket decides what counts toward a PERCENTAGE; it has no business
    # deciding whether a candidate's claim gets looked at. Previously a resume
    # listing FastAPI and Supabase simply had those claims ignored for a backend
    # role, which reads as "unverified" when in fact nobody checked.
    for name in sorted(claimed):
        ev = by_skill.get(name, SkillEvidence(skill=name))
        v = verdict(ev, coverage_value=cov, authored_repo_count=authored_repos,
                    profile_partial=profile_partial)
        # The engine always computes CONTRADICTED; revealing it is a separate
        # decision. Until Dataset A validates the rule, a candidate sees
        # UNVERIFIABLE -- the honest fallback -- while the suppressed verdict is
        # still recorded so its frequency can be measured.
        suppressed = False
        if v is Verdict.CONTRADICTED and not reveal_contradictions:
            v = Verdict.UNVERIFIABLE
            suppressed = True
        conf = confidence(ev)
        demand = demand_by_skill.get(name)

        if demand is not None:
            claimed_demand += demand
            # ATTESTED contributes nothing to verified readiness (section 8.4).
            if v is not Verdict.ATTESTED:
                verified_demand += demand * conf

        assessments.append(SkillAssessment(
            skill=name, verdict=v, confidence=conf,
            max_tier=ev.max_tier, n_repos=ev.n_repos, claimed=True,
            unverifiable_reason=(unverifiable_reason_for(ev)
                                 if v is Verdict.UNVERIFIABLE else None),
            in_demand_basket=demand is not None,
            demand_pct=demand,
            suppressed_contradiction=suppressed,
        ))

    basket_names = {m["canonical"] for m in basket}
    unclaimed_verified = tuple(sorted(
        e.skill for e in evidence
        if e.skill not in claimed
        and e.skill in basket_names
        and e.max_tier is not None
        and TIER_RANK[e.max_tier] >= TIER_RANK[VERIFIED_AT_OR_ABOVE]
    ))

    pct = lambda x: round(x / total_demand * 100, 1) if total_demand else 0.0
    return EvidenceReport(
        claimed_readiness=pct(claimed_demand),
        verified_readiness=pct(verified_demand),
        verification_coverage=cov,
        assessments=tuple(assessments),
        attested_skills=tuple(sorted(e.skill for e in evidence if e.attested)),
        unclaimed_verified_skills=unclaimed_verified,
    )
