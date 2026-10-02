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


class GitHubStatusModel(BaseModel):
    """Explicit fetch outcome. Replaces a bare status string that the UI used to
    interpret with startsWith('ok') -- which is how an expired token went
    unnoticed while every analysis silently fell back to resume-only evidence."""

    state: str
    message: str
    repos_analysed: int
    #: False whenever the readiness score was computed WITHOUT GitHub evidence.
    evidence_used: bool
    #: info | warn | error, so the UI never guesses severity from a prefix.
    severity: str


class SkillAssessmentModel(BaseModel):
    skill: str
    verdict: str
    confidence: float
    max_tier: str | None
    n_repos: int
    unverifiable_reason: str | None
    in_demand_basket: bool
    demand_pct: float | None


class EvidenceReportModel(BaseModel):
    """The evidence engine's output: two readiness numbers, never one.

    The gap between claimed and verified IS the product. `verification_coverage`
    is None rather than 0 when nothing was assessable -- "nothing to check" and
    "checked nothing" are different statements.
    """

    claimed_readiness: float
    verified_readiness: float
    verification_coverage: float | None
    assessments: list[SkillAssessmentModel]
    attested_skills: list[str]
    unclaimed_verified_skills: list[str]
    #: True when collection was incomplete, so absence is not evidence.
    profile_partial: bool
    repos_analysed: int
    #: The pre-evidence-model `resume | github` union score, carried for the
    #: report and the regression tests. NOT shown in the product: a two-number
    #: story only reads clearly when there are exactly two numbers.
    legacy_union_readiness: float


class AnalyzeResponse(BaseModel):
    report: GapReportModel
    resume_skills_found: list[str]
    github: GitHubStatusModel
    #: Present only when a GitHub username was supplied AND collection succeeded.
    #: The legacy `report` above still ships the pre-evidence-model union score,
    #: so nothing breaks while the two are compared against the baseline.
    #: Always present. claimed_readiness needs no GitHub, so there is always
    #: a number to show; without evidence, verified is 0 and coverage None.
    evidence: EvidenceReportModel


class RoadmapRequest(BaseModel):
    role: str
    resume_skills: list[str] = Field(default_factory=list)
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
