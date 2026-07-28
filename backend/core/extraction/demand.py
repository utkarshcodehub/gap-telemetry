"""Market demand aggregation — document-frequency based (TF-IDF insight)."""

from __future__ import annotations

from dataclasses import dataclass

from core.extraction.extractor import SkillExtractor


@dataclass(frozen=True)
class SkillDemand:
    canonical: str
    category: str
    postings_count: int
    demand_pct: float
    total_mentions: int


def aggregate_demand(
    postings: list[str],
    extractor: SkillExtractor | None = None,
) -> list[SkillDemand]:
    extractor = extractor or SkillExtractor()
    total = len(postings)
    if total == 0:
        return []

    doc_freq: dict[str, int] = {}
    mention_freq: dict[str, int] = {}
    categories: dict[str, str] = {}

    for text in postings:
        for skill in extractor.extract(text):
            doc_freq[skill.canonical] = doc_freq.get(skill.canonical, 0) + 1
            mention_freq[skill.canonical] = (
                mention_freq.get(skill.canonical, 0) + skill.count
            )
            categories[skill.canonical] = skill.category

    demands = [
        SkillDemand(
            canonical=name,
            category=categories[name],
            postings_count=count,
            demand_pct=round(count / total * 100, 1),
            total_mentions=mention_freq[name],
        )
        for name, count in doc_freq.items()
    ]
    demands.sort(key=lambda d: d.demand_pct, reverse=True)
    return demands
