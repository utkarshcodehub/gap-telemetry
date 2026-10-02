import io
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fastapi import Depends, FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from postgrest import APIError
from pypdf import PdfReader
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address

from app.deps import get_current_user
from app.schemas import (
    EvidenceReportModel,
    GitHubStatusModel,
    SkillAssessmentModel,
    AnalyzeResponse,
    GapReportModel,
    MarketSkill,
    RoadmapModel,
    RoadmapRequest,
    SavedAnalysisFull,
    SavedAnalysisMeta,
    SaveAnalysisRequest,
)
from app.settings import get_settings
from core.auth.verify import AuthUser
from core.db.store import AnalysesStore, JobStore
from core.extraction.extractor import SkillExtractor
from core.evidence.github import (
    GitHubClient,
    RequestBudget,
    collect_profile,
    evidence_from_profile,
)
from core.evidence.model import score as score_evidence
from core.gap.scorer import score_gap
from core.market.sources import describe
from core.github_profile.fetcher import GitHubFetchError, fetch_github_profile
from core.github_profile.status import classify_error as gh_classify
from core.github_profile.status import not_requested as gh_not_requested
from core.github_profile.status import ok as gh_ok
from core.resume.parser import ResumeParseError, assert_has_text_layer, parse_resume_text
from core.roadmap.generator import generate_roadmap

settings = get_settings()

#: Where cached GitHub artifact responses live (NFR-3, 24h TTL). Re-analysing an
#: unchanged profile costs ~0 requests, which matters because the limit is shared
#: across every analysis.
EVIDENCE_CACHE_DIR = Path(__file__).resolve().parents[1] / "data" / "cache" / "github"

#: The only market this deployment serves. Demand is never aggregated across
#: markets (see migration 0003); the US LinkedIn corpus is deliberately not
#: ingested and lives on disk for experiments only.
MARKET = "IN"

app = FastAPI(
    title="Gap Telemetry",
    description="Market-aware skill gap analysis + LLM learning roadmaps",
    version="1.1.0",
)

limiter = Limiter(key_func=get_remote_address)
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)


def _postgrest_api_error_handler(request: Request, exc: APIError) -> JSONResponse:
    """A bearer token that passes our own JWT verification but isn't a real
    Supabase-issued session token still gets forwarded to PostgREST as-is
    (see AnalysesStore) — PostgREST then rejects it and supabase-py raises
    APIError. Surface that as a clean 401 instead of an unhandled 500."""
    return JSONResponse(
        status_code=401,
        content={"detail": f"Session rejected by the database: {exc.message or 'unauthorized'}"},
    )


app.add_exception_handler(APIError, _postgrest_api_error_handler)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_methods=["*"],
    allow_headers=["*"],
)

EXTRACTOR = SkillExtractor()
MAX_UPLOAD_BYTES = settings.max_upload_mb * 1024 * 1024


STORE = JobStore()


def get_store() -> JobStore:
    return STORE


def get_analyses_store(user: AuthUser) -> AnalysesStore:
    return AnalysesStore(user_token=user.token)


# ---------------------------------------------------------------- public

@app.get("/health")
def health():
    store = get_store()
    try:
        return {"status": "ok", "postings_in_db": store.posting_count()}
    finally:
        store.close()


@app.get("/roles")
def roles():
    """Roles available for analysis, plus what data backs them.

    The provenance block exists so the UI can attribute a demand percentage to
    its source. The corpus mixes an archival Q4 2020 sample with a live feed, and
    a reader who cannot tell them apart cannot judge whether a number describes
    today's market. Returned here rather than from a second endpoint because the
    frontend already calls this on mount.
    """
    store = get_store()
    try:
        counts = store.provenance(MARKET)
        return {
            "market": MARKET,
            "roles": store.roles(),
            "provenance": [
                {**describe(c["source"]), "postings": c["postings"]} for c in counts
            ],
        }
    finally:
        store.close()


@app.get("/market/{role}", response_model=list[MarketSkill])
def market(role: str):
    store = get_store()
    try:
        demand = store.demand(role)
        if not demand:
            raise HTTPException(404, f"No postings for role '{role}'. Run the scraper or generator first.")
        return demand
    finally:
        store.close()


# ---------------------------------------------------------------- helpers

async def _read_upload_capped(file: UploadFile, max_bytes: int) -> bytes:
    """Read an upload in chunks, aborting the moment it exceeds the cap —
    never buffer an unbounded file into memory first."""
    chunks: list[bytes] = []
    total = 0
    while True:
        chunk = await file.read(1024 * 1024)
        if not chunk:
            break
        total += len(chunk)
        if total > max_bytes:
            raise HTTPException(413, f"File exceeds the {max_bytes // (1024 * 1024)}MB limit")
        chunks.append(chunk)
    return b"".join(chunks)


async def _resume_text_from_inputs(resume_file: UploadFile | None, resume_text: str | None) -> str:
    if resume_text and resume_text.strip():
        return resume_text
    if resume_file is not None:
        content = await _read_upload_capped(resume_file, MAX_UPLOAD_BYTES)
        if not content.startswith(b"%PDF-"):
            raise HTTPException(422, "File is not a valid PDF (missing %PDF header)")
        try:
            reader = PdfReader(io.BytesIO(content))
            text = "\n".join(p.extract_text() or "" for p in reader.pages)
        except Exception as e:
            raise HTTPException(422, f"Could not read PDF: {e}")
        try:
            assert_has_text_layer(text)
        except ResumeParseError as e:
            raise HTTPException(422, str(e))
        return text
    raise HTTPException(422, "Provide resume_file (PDF) or resume_text.")


# ---------------------------------------------------------------- auth-required

@app.post("/analyze", response_model=AnalyzeResponse)
@limiter.limit(settings.rate_limit_analyze)
async def analyze(
    request: Request,
    role: str = Form(...),
    resume_file: UploadFile | None = File(None),
    resume_text: str | None = Form(None),
    github_username: str | None = Form(None),
    user: AuthUser = Depends(get_current_user),
):
    text = await _resume_text_from_inputs(resume_file, resume_text)
    try:
        profile = parse_resume_text(text, EXTRACTOR)
    except ResumeParseError as e:
        raise HTTPException(422, str(e))

    github_skills: dict[str, int] = {}
    gh_status = gh_not_requested()
    if github_username:
        try:
            gh = fetch_github_profile(github_username, EXTRACTOR,
                                      token=settings.github_token,
                                      cache_dir=EVIDENCE_CACHE_DIR)
            github_skills = gh.skills
            gh_status = gh_ok(gh.repo_count)
        except GitHubFetchError as e:
            # Never a quiet "skipped": classify_error states what failed and what
            # to do, and the response carries evidence_used=False so a caller
            # cannot mistake this for a score computed with evidence.
            gh_status = gh_classify(e)

    store = get_store()
    try:
        demand = store.demand(role)
    finally:
        store.close()
    if not demand:
        raise HTTPException(404, f"No market data for role '{role}'.")

    report = score_gap(role, demand, profile.skill_names, github_skills)

    # The evidence engine runs alongside the legacy score rather than replacing
    # it, so both can be compared against the recorded baseline before anything
    # is switched over. It needs the artifact collector, not the old README
    # keyword fetcher, so it only runs when a username was supplied.
    # Always computed, even with no GitHub username: claimed_readiness needs only
    # the resume and the market, so the UI always has a number to show. Without
    # evidence, verified is 0 and coverage is None -- "we could not check", which
    # is a different statement from "you scored zero".
    evidence_model = _evidence_for(
        github_username.strip() if (github_username and gh_status.evidence_used) else None,
        role, demand, profile.skill_names,
        legacy_union=report.readiness_score,
    )

    return AnalyzeResponse(
        report=GapReportModel.from_report(report),
        resume_skills_found=sorted(profile.skill_names),
        github=GitHubStatusModel(**gh_status.as_dict()),
        evidence=evidence_model,
    )


def _evidence_for(username: str | None, role: str, demand: list[dict],
                  claimed: set[str], *,
                  legacy_union: float) -> EvidenceReportModel:
    """Score the claims, with artifact evidence when a username is available.

    Never returns None and never raises: a GitHub problem degrades the VERIFIED
    half while claimed_readiness -- which needs no GitHub at all -- still stands
    (NFR-4). The explicit github status in the same response says what happened.
    """
    evidence: list = []
    partial = False
    repos = 0

    if username:
        try:
            client = GitHubClient(
                token=settings.github_token,
                budget=RequestBudget(limit=150),
                cache_dir=EVIDENCE_CACHE_DIR,
            )
            gh = collect_profile(client, username)
            evidence = evidence_from_profile(gh)
            partial, repos = gh.partial, len(gh.repos)
        except Exception:
            # Collection failed outright. Fall through with no evidence rather
            # than failing the analysis; verified will be 0 and coverage None.
            partial = True

    rep = score_evidence(
        demand, claimed, evidence,
        profile_partial=partial,
        # Off until Dataset A validates the rule; a claim that would be
        # contradicted reports UNVERIFIABLE instead (EVIDENCE_MODEL 8.8).
        reveal_contradictions=settings.reveal_contradicted_verdict,
    )

    return EvidenceReportModel(
        claimed_readiness=rep.claimed_readiness,
        verified_readiness=rep.verified_readiness,
        verification_coverage=rep.verification_coverage,
        assessments=[
            SkillAssessmentModel(
                skill=a.skill, verdict=a.verdict.value, confidence=a.confidence,
                max_tier=a.max_tier.value if a.max_tier else None,
                n_repos=a.n_repos,
                unverifiable_reason=(a.unverifiable_reason.value
                                     if a.unverifiable_reason else None),
                in_demand_basket=a.in_demand_basket, demand_pct=a.demand_pct,
            )
            for a in rep.assessments
        ],
        attested_skills=list(rep.attested_skills),
        unclaimed_verified_skills=list(rep.unclaimed_verified_skills),
        profile_partial=partial,
        repos_analysed=repos,
        legacy_union_readiness=legacy_union,
    )


@app.post("/roadmap", response_model=RoadmapModel)
@limiter.limit(settings.rate_limit_roadmap)
async def roadmap(
    request: Request,
    req: RoadmapRequest,
    user: AuthUser = Depends(get_current_user),
):
    store = get_store()
    try:
        demand = store.demand(req.role)
    finally:
        store.close()
    if not demand:
        raise HTTPException(404, f"No market data for role '{req.role}'.")

    report = score_gap(req.role, demand, set(req.resume_skills), req.github_skills or {})
    plan = generate_roadmap(report, n_weeks=req.n_weeks, api_key=settings.groq_api_key)
    return RoadmapModel(**plan.to_dict())


# ---------------------------------------------------------------- saved analyses (personal, isolated)

@app.post("/analyses", response_model=SavedAnalysisMeta)
async def save_analysis(req: SaveAnalysisRequest, user: AuthUser = Depends(get_current_user)):
    store = get_analyses_store(user)
    analysis_id = store.save_analysis(
        user_id=user.id,
        role=req.role,
        readiness_score=req.report.readiness_score,
        report_json=req.report.model_dump_json(),
    )
    row = store.get_analysis(analysis_id, user.id)
    if not row:
        raise HTTPException(500, "Analysis saved but could not be retrieved")
    return SavedAnalysisMeta(
        id=row["id"],
        role=row["role"],
        readiness_score=row["readiness_score"],
        created_at=row["created_at"],
    )


@app.get("/analyses", response_model=list[SavedAnalysisMeta])
async def list_my_analyses(user: AuthUser = Depends(get_current_user)):
    store = get_analyses_store(user)
    return store.list_analyses(user.id)  # scoped to user.id in SQL — see store.py


@app.get("/analyses/{analysis_id}", response_model=SavedAnalysisFull)
async def get_my_analysis(analysis_id: int, user: AuthUser = Depends(get_current_user)):
    store = get_analyses_store(user)
    row = store.get_analysis(analysis_id, user.id)
    if not row:
        # 404, not 403: don't confirm to a caller that a different
        # user's row even exists.
        raise HTTPException(404, "Analysis not found")
    report_payload = row["report_json"]
    if isinstance(report_payload, str):
        report_payload = json.loads(report_payload)
    return SavedAnalysisFull(
        id=row["id"],
        role=row["role"],
        readiness_score=row["readiness_score"],
        created_at=row["created_at"],
        report=report_payload,
    )


@app.delete("/analyses/{analysis_id}")
async def delete_my_analysis(analysis_id: int, user: AuthUser = Depends(get_current_user)):
    store = get_analyses_store(user)
    deleted = store.delete_analysis(analysis_id, user.id)
    if not deleted:
        raise HTTPException(404, "Analysis not found")
    return {"deleted": True}


# ---------------------------------------------------------------- role fit (Phase 2)

from core.match.listing_parser import parse_listing
from core.match.fit_scorer import compute_match
from core.match.verdict_explainer import explain_verdict

MOCK_LISTINGS_PATH = Path(__file__).resolve().parents[1] / "core" / "match" / "mock_listings.json"


def _load_mock_listings() -> list[dict]:
    return json.loads(MOCK_LISTINGS_PATH.read_text(encoding="utf-8"))["listings"]


@app.get("/listings")
def list_listings():
    """Return all available mock listings (summary only, not full details)."""
    listings = _load_mock_listings()
    return [
        {
            "id": l["id"],
            "title": l["title"],
            "company": l["company"],
            "location": l["location"],
            "job_type": l["job_type"],
            "stipend": l["stipend"],
            "eligible_branches": l["eligible_branches"],
        }
        for l in listings
    ]


@app.get("/listings/{listing_id}")
def get_listing(listing_id: str):
    """Return full detail for one listing."""
    listings = _load_mock_listings()
    found = next((l for l in listings if l["id"] == listing_id), None)
    if not found:
        raise HTTPException(404, f"Listing '{listing_id}' not found")
    return found


@app.post("/role-fit")
@limiter.limit(settings.rate_limit_analyze)
async def role_fit(
    request: Request,
    listing_id: str = Form(...),
    resume_file: UploadFile | None = File(None),
    resume_text: str | None = Form(None),
    academic_marks: str | None = Form(None),
    github_username: str | None = Form(None),
    user: AuthUser = Depends(get_current_user),
):
    """
    Compute the Role Fit match score for one candidate against one listing.

    academic_marks: comma-separated percentages, e.g. "94.6,84.3,78.5"
    github_username: optional — GitHub-derived skills are merged into the
      candidate's skill set, the same way /analyze does it.
    """
    # Find the listing
    listings = _load_mock_listings()
    listing_dict = next((l for l in listings if l["id"] == listing_id), None)
    if not listing_dict:
        raise HTTPException(404, f"Listing '{listing_id}' not found")

    # Parse resume
    text = await _resume_text_from_inputs(resume_file, resume_text)
    try:
        profile = parse_resume_text(text, EXTRACTOR)
    except ResumeParseError as e:
        raise HTTPException(422, str(e))

    # GitHub enrichment (optional, degrades gracefully)
    github_skills: dict[str, int] = {}
    gh_status = gh_not_requested()
    if github_username and github_username.strip():
        try:
            gh = fetch_github_profile(
                github_username.strip(), EXTRACTOR, token=settings.github_token,
                cache_dir=EVIDENCE_CACHE_DIR,
            )
            github_skills = gh.skills
            gh_status = gh_ok(gh.repo_count)
        except GitHubFetchError as e:
            gh_status = gh_classify(e)

    candidate_skills = profile.skill_names | set(github_skills)

    # Parse listing
    listing = parse_listing(listing_dict, EXTRACTOR)

    # Parse academic marks
    marks: list[float] = []
    if academic_marks:
        try:
            marks = [float(m.strip()) for m in academic_marks.split(",") if m.strip()]
        except ValueError:
            raise HTTPException(422, "academic_marks must be comma-separated numbers, e.g. '94.6,84.3'")

    # Compute deterministic score
    result = compute_match(listing, candidate_skills, marks)

    # Generate explanation (LLM or template fallback)
    explanation = explain_verdict(result, api_key=settings.groq_api_key)

    return {
        "listing_id": result.listing_id,
        "listing_title": result.listing_title,
        "company": result.company,
        "match_pct": result.match_pct,
        "verdict": result.verdict,
        "explanation": explanation,
        "matched_skills": list(result.matched_skills),
        "missing_skills": list(result.missing_skills),
        "unmatched_tags": list(result.unmatched_tags),
        "skill_match_pct": result.skill_match_pct,
        "academic_adjustment": result.academic_adjustment,
        "academic_marks_used": list(result.academic_marks_used),
        "resume_skills_found": sorted(profile.skill_names),
        "github": gh_status.as_dict(),
        "github_skills_used": sorted(github_skills.keys()),
    }
