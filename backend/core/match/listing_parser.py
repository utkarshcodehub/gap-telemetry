"""
Listing parser — ingests a TPO portal listing and produces a structured
ListingProfile ready for the fit-score aggregator.

Design decisions:

1. WHY separate "tech_skills" from "unmatched_tags"?
   TPO portal skill fields are free-text: companies type whatever they
   want, with no validation. Some tags are real tech skills ("Python/Django",
   "ReactNative") that the taxonomy can normalize. Others are soft-skill
   phrasing ("logicalthinking", "Clean&maintainablecoding") that aren't
   discrete, matchable skills at all. Silently ignoring them gives a
   false-high match %; pretending they're matchable gives a false-low.
   Separating them lets the UI show "not confidently matched" instead
   of guessing — the transparency requirement from the feature plan.

2. WHY normalize at parse time, not at scoring time?
   Same principle as the job-posting extractor: normalization is done
   once, at the boundary, so the scorer only ever sees canonical names.
   One normalization path for both sides of the comparison.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from core.extraction.extractor import SkillExtractor


@dataclass(frozen=True)
class ListingProfile:
    """Structured representation of one TPO portal listing."""
    listing_id: str
    title: str                      # e.g. "SDE"
    company: str                    # e.g. "EVE Healthcare"
    location: str
    category: str                   # e.g. "Service Based"
    job_type: str                   # e.g. "Internship + PPO"
    experience_level: str           # e.g. "Entry Level"
    stipend: str                    # e.g. "₹10,000/month"
    eligible_branches: tuple[str, ...]
    tech_skills: tuple[str, ...]    # canonical names, normalized
    unmatched_tags: tuple[str, ...]  # raw tags that didn't map to any skill
    raw_tags: tuple[str, ...]       # original tags as entered on the portal


def parse_listing(
    listing: dict,
    extractor: SkillExtractor | None = None,
) -> ListingProfile:
    """
    Parse a listing dict (matching the mock-listings JSON shape) into
    a ListingProfile.

    Expected dict keys:
        id, title, company, location, category, job_type, experience_level,
        stipend, eligible_branches (list[str]), required_skills (list[str])
    """
    extractor = extractor or SkillExtractor()
    raw_tags = tuple(listing.get("required_skills", []))

    tech: list[str] = []
    unmatched: list[str] = []
    seen: set[str] = set()

    for tag in raw_tags:
        # Run each tag through the extractor individually — handles
        # camelCase splitting, slash splitting, and alias normalization
        found = extractor.extract_names(tag)
        if found:
            for name in found:
                if name not in seen:
                    tech.append(name)
                    seen.add(name)
        else:
            unmatched.append(tag)

    return ListingProfile(
        listing_id=str(listing.get("id", "")),
        title=listing.get("title", ""),
        company=listing.get("company", ""),
        location=listing.get("location", ""),
        category=listing.get("category", ""),
        job_type=listing.get("job_type", ""),
        experience_level=listing.get("experience_level", "Entry Level"),
        stipend=listing.get("stipend", ""),
        eligible_branches=tuple(listing.get("eligible_branches", [])),
        tech_skills=tuple(tech),
        unmatched_tags=tuple(unmatched),
        raw_tags=raw_tags,
    )
