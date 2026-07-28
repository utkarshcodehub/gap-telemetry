"""
FastAPI layer — now with the security lockdown applied.

What changed from the pre-auth version, and why:

1. Auth. /analyze, /roadmap, and all /analyses routes now require a
   verified Supabase bearer token (see app/deps.py). /health, /roles,
   and /market/{role} stay public on purpose — they expose only
   aggregate, non-personal market data, and a public landing page
   should be able to show "500 postings analyzed" without forcing a
   login first.

2. CORS. No more allow_origins=["*"]. Origins come from settings
   (CORS_ORIGINS env var), defaulting to the local Vite dev server only.

3. Upload limits. PDFs are read in capped chunks (never buffer an
   unbounded upload into memory) and checked for the %PDF magic bytes
   before parsing — never trust a client-supplied Content-Type header.

4. Rate limiting. /analyze and /roadmap are the expensive routes (PDF
   parsing, an LLM call) — they get a tight per-client limit. Read-only
   market endpoints get a looser default limit.

5. Per-user saved analyses. A minimal persistence layer that exists
   specifically to prove the isolation guarantee works: every query is
   scoped to the authenticated user's id at the SQL layer (see
   core/db/store.py). Covered by tests/test_auth.py, including the
   canonical "user B cannot see user A's data" case.
"""

import io
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fastapi import Depends, FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from pypdf import PdfReader
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address

from app.deps import get_current_user
from app.schemas import (
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
from core.gap.scorer import score_gap
from core.github_profile.fetcher import GitHubFetchError, fetch_github_profile
from core.resume.parser import ResumeParseError, parse_resume_text
from core.roadmap.generator import generate_roadmap

settings = get_settings()

app = FastAPI(
    title="Job-Skill Gap Intelligence API",
    description="Market-aware skill gap analysis + LLM learning roadmaps",
    version="1.1.0",
)

limiter = Limiter(key_func=get_remote_address)
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_methods=["*"],
    allow_headers=["*"],
)

EXTRACTOR = SkillExtractor()
STORE = JobStore()
MAX_UPLOAD_BYTES = settings.max_upload_mb * 1024 * 1024


@app.on_event("startup")
def seed_market_data_if_empty() -> None:
    """First run against a fresh Supabase project has no postings — rather
    than requiring a manual `python synthetic_generator.py` step (easy to
    forget, and the reason /market and /analyze silently 404'd before),
    seed the same 500-posting synthetic dataset automatically."""
    if STORE.posting_count() > 0:
        return
    if not STORE._can_write:
        print("[startup] DB is empty and SUPABASE_SERVICE_ROLE_KEY isn't set — "
              "skipping auto-seed. Add it to backend/.env and restart, or run "
              "scraper/synthetic_generator.py once that key is set.")
        return
    sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scraper"))
    from ingest import ingest_postings  # noqa: E402
    from synthetic_generator import generate  # noqa: E402

    records = generate(count=500, seed=42)
    inserted = ingest_postings(records, STORE, EXTRACTOR)
    print(f"[startup] seeded {inserted} synthetic postings (DB was empty)")


# ---------------------------------------------------------------- public

@app.get("/health")
def health():
    return {"status": "ok", "postings_in_db": STORE.posting_count()}


@app.get("/roles")
def roles():
    return {"roles": STORE.roles()}


@app.get("/market/{role}", response_model=list[MarketSkill])
def market(role: str):
    demand = STORE.demand(role)
    if not demand:
        raise HTTPException(404, f"No postings for role '{role}'. Run the scraper or generator first.")
    return demand


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
        if len(text.strip()) < 50:
            raise HTTPException(422, "PDF has no text layer (scanned image?). Export a digital PDF or paste resume text.")
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
    github_status = "not_requested"
    if github_username:
        try:
            gh = fetch_github_profile(github_username, EXTRACTOR)
            github_skills = gh.skills
            github_status = f"ok ({gh.repo_count} repos)"
        except GitHubFetchError as e:
            github_status = f"skipped: {e}"

    demand = STORE.demand(role)
    if not demand:
        raise HTTPException(404, f"No market data for role '{role}'.")

    report = score_gap(role, demand, profile.skill_names, github_skills)
    return AnalyzeResponse(
        report=GapReportModel.from_report(report),
        resume_skills_found=sorted(profile.skill_names),
        github_status=github_status,
    )


@app.post("/roadmap", response_model=RoadmapModel)
@limiter.limit(settings.rate_limit_roadmap)
async def roadmap(
    request: Request,
    req: RoadmapRequest,
    user: AuthUser = Depends(get_current_user),
):
    demand = STORE.demand(req.role)
    if not demand:
        raise HTTPException(404, f"No market data for role '{req.role}'.")

    report = score_gap(req.role, demand, set(req.resume_skills), req.github_skills or {})
    plan = generate_roadmap(report, n_weeks=req.n_weeks)
    return RoadmapModel(**plan.to_dict())


# ---------------------------------------------------------------- saved analyses (personal, isolated)

@app.post("/analyses", response_model=SavedAnalysisMeta)
async def save_analysis(req: SaveAnalysisRequest, user: AuthUser = Depends(get_current_user)):
    store = AnalysesStore(user.token)
    analysis_id = store.save_analysis(
        user_id=user.id, role=req.role,
        readiness_score=req.report.readiness_score,
        report_json=req.report.model_dump_json(),
    )
    row = store.get_analysis(analysis_id, user.id)
    return SavedAnalysisMeta(id=row["id"], role=row["role"],
                             readiness_score=row["readiness_score"], created_at=row["created_at"])


@app.get("/analyses", response_model=list[SavedAnalysisMeta])
async def list_my_analyses(user: AuthUser = Depends(get_current_user)):
    store = AnalysesStore(user.token)
    return store.list_analyses(user.id)  # RLS-scoped to user.id — see store.py


@app.get("/analyses/{analysis_id}", response_model=SavedAnalysisFull)
async def get_my_analysis(analysis_id: int, user: AuthUser = Depends(get_current_user)):
    store = AnalysesStore(user.token)
    row = store.get_analysis(analysis_id, user.id)
    if not row:
        # 404, not 403: don't confirm to a caller that a different
        # user's row even exists.
        raise HTTPException(404, "Analysis not found")
    return SavedAnalysisFull(
        id=row["id"], role=row["role"], readiness_score=row["readiness_score"],
        created_at=row["created_at"], report=row["report_json"],
    )


@app.delete("/analyses/{analysis_id}")
async def delete_my_analysis(analysis_id: int, user: AuthUser = Depends(get_current_user)):
    store = AnalysesStore(user.token)
    deleted = store.delete_analysis(analysis_id, user.id)
    if not deleted:
        raise HTTPException(404, "Analysis not found")
    return {"deleted": True}
