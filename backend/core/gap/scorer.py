"""Gap scoring — demand-weighted readiness, percentile tiers, evidence levels."""

from __future__ import annotations

from dataclasses import dataclass, field

MIN_DEMAND_PCT = 5.0
SOFT_CATEGORIES = {"soft_skill"}


@dataclass(frozen=True)
class GapItem:
    canonical: str
    category: str
    demand_pct: float
    tier: str


@dataclass(frozen=True)
class StrengthItem:
    canonical: str
    category: str
    demand_pct: float
    evidence: str
    github_repos: int = 0


@dataclass(frozen=True)
class GapReport:
    role: str
    readiness_score: float
    total_market_skills: int
    gaps: tuple[GapItem, ...]
    strengths: tuple[StrengthItem, ...]
    hidden_strengths: tuple[StrengthItem, ...]
    extras: tuple[str, ...]
    notes: tuple[str, ...] = field(default_factory=tuple)

    def summary(self) -> dict:
        return {
            "role": self.role,
            "readiness_score": self.readiness_score,
            "critical_gaps": [g.canonical for g in self.gaps if g.tier == "critical"],
            "strength_count": len(self.strengths),
            "hidden_strength_count": len(self.hidden_strengths),
        }


def _tier(rank: int, total: int) -> str:
    if total == 0:
        return "nice_to_have"
    pct = rank / total
    if pct <= 1 / 3:
        return "critical"
    if pct <= 2 / 3:
        return "important"
    return "nice_to_have"


def score_gap(
    role: str,
    market: list[dict],
    resume_skills: set[str],
    github_skills: dict[str, int] | None = None,
) -> GapReport:
    github_skills = github_skills or {}
    user_all = resume_skills | set(github_skills)

    basket = [m for m in market if m["demand_pct"] >= MIN_DEMAND_PCT and m["category"] not in SOFT_CATEGORIES]
    basket.sort(key=lambda m: m["demand_pct"], reverse=True)

    total_demand = sum(m["demand_pct"] for m in basket)
    matched_demand = sum(m["demand_pct"] for m in basket if m["canonical"] in user_all)
    readiness = round(matched_demand / total_demand * 100, 1) if total_demand else 0.0

    missing = [m for m in basket if m["canonical"] not in user_all]
    gaps = tuple(
        GapItem(canonical=m["canonical"], category=m["category"],
                demand_pct=m["demand_pct"], tier=_tier(i + 1, len(missing)))
        for i, m in enumerate(missing)
    )

    def evidence_for(name: str) -> tuple[str, int]:
        on_resume = name in resume_skills
        repos = github_skills.get(name, 0)
        if on_resume and repos:
            return "resume+github", repos
        if on_resume:
            return "resume", 0
        return "github", repos

    strengths = []
    hidden = []
    for m in basket:
        name = m["canonical"]
        if name not in user_all:
            continue
        ev, repos = evidence_for(name)
        item = StrengthItem(canonical=name, category=m["category"], demand_pct=m["demand_pct"], evidence=ev, github_repos=repos)
        strengths.append(item)
        if ev == "github":
            hidden.append(item)

    extras = tuple(sorted(user_all - {m["canonical"] for m in basket}))

    notes = []
    if hidden:
        names = ", ".join(h.canonical for h in hidden[:5])
        notes.append(f"Resume upgrade: {names} appear in your GitHub repos but not on your resume — add them with project evidence.")
    if not market:
        notes.append("Market data is empty — scrape or generate postings first.")

    return GapReport(
        role=role, readiness_score=readiness, total_market_skills=len(basket),
        gaps=gaps, strengths=tuple(strengths), hidden_strengths=tuple(hidden),
        extras=extras, notes=tuple(notes),
    )
