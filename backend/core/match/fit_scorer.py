"""
Fit-score aggregator — deterministic, reproducible, no AI involved.

Combines:
  - Skill match (primary driver, ~85% weight)
  - Academic context (low weight, ~15%, per the resolved design decision)

Output: a MatchResult dataclass with the percentage, a verdict label from
a fixed set, structured match/miss detail, and the academic contribution
broken out transparently (so the UI can show *why* academics affected the
score, not hide it).

Design decisions:

1. WHY 85/15 and not 50/50?
   The role listing's "Required Skills" field is the company's own explicit
   statement of what they want. Academic marks are a general signal — useful
   for tiebreaking, genuinely uncorrelated with whether a candidate knows
   React Native. Weighting academics heavier than ~15-20% would let a high
   CGPA mask a genuine skill gap, or let a low CGPA punish someone who has
   every listed skill. Both outcomes would violate the "trustworthy" bar.

2. WHY a fixed verdict vocabulary, not free text?
   Consistency. A student checking three listings should see "Strong Fit,"
   "Good Fit," "Partial Fit," or "Needs Work" — the same labels in the same
   order — not three different phrasings an LLM invented independently.
   The LLM's job (Phase 2) is to *explain* the verdict, not *name* it.

3. WHY is academic_score computed as a percentile-mapped bonus/penalty
   rather than a raw percentage?
   Raw marks vary wildly by board and institution (a 75% in CBSE vs 75%
   in a state board are not the same thing). Rather than pretend they're
   comparable, we map them into a gentle curve: marks above a "solid"
   threshold get a small bonus, marks below get a small penalty, and the
   effect is capped. This is explicitly a soft heuristic, not a precise
   signal — documented as such in the output.

4. WHY expose unmatched_tags separately?
   "logicalthinking" and "Clean&maintainablecoding" are not matchable
   technical skills. Ignoring them silently inflates the match %; counting
   them as misses deflates it unfairly. Showing them as "not confidently
   matched" is the honest middle — the user sees them, the score doesn't
   pretend to know what they mean.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from core.match.listing_parser import ListingProfile

# ── Weights (per resolved decision: low-weight academics) ──
SKILL_WEIGHT = 0.85
ACADEMIC_WEIGHT = 0.15

# ── Academic curve parameters ──
ACADEMIC_SOLID_THRESHOLD = 70.0   # marks above this get a bonus
ACADEMIC_MAX_BONUS = 10.0         # max points the academic component can add
ACADEMIC_MAX_PENALTY = -8.0       # max points it can subtract
ACADEMIC_BASELINE = 75.0          # "neutral" — neither bonus nor penalty

VerdictLabel = Literal["Strong Fit", "Good Fit", "Partial Fit", "Needs Work"]


def _verdict(score: float) -> VerdictLabel:
    if score >= 80:
        return "Strong Fit"
    if score >= 60:
        return "Good Fit"
    if score >= 40:
        return "Partial Fit"
    return "Needs Work"


def _academic_contribution(marks: list[float]) -> float:
    """
    Takes available academic marks (10th, 12th, CGPA — whatever's provided),
    averages them, and returns a bounded bonus/penalty.

    Gentle curve: every point above ACADEMIC_BASELINE earns a small bonus
    (capped at ACADEMIC_MAX_BONUS); every point below costs a small penalty
    (capped at ACADEMIC_MAX_PENALTY). Returns 0 if no marks provided.
    """
    if not marks:
        return 0.0
    avg = sum(marks) / len(marks)
    delta = avg - ACADEMIC_BASELINE
    if delta >= 0:
        return min(delta * 0.5, ACADEMIC_MAX_BONUS)
    else:
        return max(delta * 0.4, ACADEMIC_MAX_PENALTY)


@dataclass(frozen=True)
class MatchResult:
    listing_id: str
    listing_title: str
    company: str
    match_pct: float                       # 0–100, the headline number
    verdict: VerdictLabel                  # fixed vocabulary
    matched_skills: tuple[str, ...]        # canonical names the candidate has
    missing_skills: tuple[str, ...]        # canonical names the candidate lacks
    unmatched_tags: tuple[str, ...]        # raw tags that couldn't be interpreted
    skill_match_pct: float                 # skill-only %, before academic adjustment
    academic_adjustment: float             # how many points academics added/subtracted
    academic_marks_used: tuple[float, ...] # the raw marks that went in (transparency)

    def summary(self) -> dict:
        return {
            "listing": f"{self.listing_title} @ {self.company}",
            "match_pct": self.match_pct,
            "verdict": self.verdict,
            "matched": list(self.matched_skills),
            "missing": list(self.missing_skills),
            "unmatched_tags": list(self.unmatched_tags),
        }


def compute_match(
    listing: ListingProfile,
    candidate_skills: set[str],
    academic_marks: list[float] | None = None,
) -> MatchResult:
    """
    Compute the fit score for one candidate against one listing.
    Pure arithmetic — deterministic, no AI, same inputs always produce
    the same output.
    """
    required = set(listing.tech_skills)

    if not required:
        # Listing had zero parseable tech skills (all tags were soft-skill mush).
        # Can't compute a meaningful skill match — return a neutral score with
        # a clear signal that the listing's data was the problem, not the candidate.
        return MatchResult(
            listing_id=listing.listing_id,
            listing_title=listing.title,
            company=listing.company,
            match_pct=50.0,
            verdict="Partial Fit",
            matched_skills=(),
            missing_skills=(),
            unmatched_tags=listing.unmatched_tags,
            skill_match_pct=0.0,
            academic_adjustment=0.0,
            academic_marks_used=(),
        )

    matched = required & candidate_skills
    missing = required - candidate_skills
    skill_pct = (len(matched) / len(required)) * 100.0

    marks = academic_marks or []
    acad_adj = _academic_contribution(marks)

    # Blend: skill match dominates, academic adjusts at the margin
    raw_score = (skill_pct * SKILL_WEIGHT) + ((50.0 + acad_adj) * ACADEMIC_WEIGHT)
    # Normalize so 100% skills + max academic bonus = ~100,
    # and 0% skills + max penalty doesn't go below 0
    final = round(max(0.0, min(100.0, raw_score)), 1)

    return MatchResult(
        listing_id=listing.listing_id,
        listing_title=listing.title,
        company=listing.company,
        match_pct=final,
        verdict=_verdict(final),
        matched_skills=tuple(sorted(matched)),
        missing_skills=tuple(sorted(missing)),
        unmatched_tags=listing.unmatched_tags,
        skill_match_pct=round(skill_pct, 1),
        academic_adjustment=round(acad_adj, 1),
        academic_marks_used=tuple(marks),
    )
