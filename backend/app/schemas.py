"""Pydantic schemas — the public API contract, kept separate from the
internal core/ dataclasses so the API surface can stay stable even if
internal representations change."""

from pydantic import BaseModel, Field

from core.gap.scorer import GapReport


class MarketSkill(BaseModel):
    canonical: str
    category: str
    postings_count: int
    demand_pct: float
    total_mentions: int


class GapItemModel(BaseModel):
    canonical: str
    category: str
    demand_pct: float
    tier: str


class StrengthItemModel(BaseModel):
    canonical: str
    category: str
    demand_pct: float
    evidence: str
    github_repos: int


class GapReportModel(BaseModel):
    role: str
    readiness_score: float
    total_market_skills: int
    gaps: list[GapItemModel]
    strengths: list[StrengthItemModel]
    hidden_strengths: list[StrengthItemModel]
    extras: list[str]
    notes: list[str]

    @classmethod
    def from_report(cls, r: GapReport) -> "GapReportModel":
        return cls(
            role=r.role,
            readiness_score=r.readiness_score,
            total_market_skills=r.total_market_skills,
            gaps=[GapItemModel(**g.__dict__) for g in r.gaps],
            strengths=[StrengthItemModel(**s.__dict__) for s in r.strengths],
            hidden_strengths=[StrengthItemModel(**s.__dict__) for s in r.hidden_strengths],
            extras=list(r.extras),
            notes=list(r.notes),
        )


class AnalyzeResponse(BaseModel):
    report: GapReportModel
    resume_skills_found: list[str]
    github_status: str


class RoadmapRequest(BaseModel):
    role: str
    resume_skills: list[str] = Field(..., min_length=1)
    github_skills: dict[str, int] | None = None
    n_weeks: int = Field(default=6, ge=1, le=12)


class RoadmapWeekModel(BaseModel):
    week: int
    theme: str
    skills: list[str]
    actions: list[str]
    project: str


class RoadmapModel(BaseModel):
    role: str
    weeks: list[RoadmapWeekModel]
    summary: str
    engine: str


# ---- Saved analyses (personal, per-user data) ----

class SaveAnalysisRequest(BaseModel):
    role: str
    report: GapReportModel


class SavedAnalysisMeta(BaseModel):
    id: int
    role: str
    readiness_score: float
    created_at: str


class SavedAnalysisFull(SavedAnalysisMeta):
    report: GapReportModel
