"""
/role-fit-direct endpoint.

Accepts raw listing data read from the page via data-field attributes,
instead of a listing_id from a pre-built dataset. This is the endpoint
the role-fit-widget.js calls in real time.

Auth: optional. Works without a token for the simulator context.
"""

from __future__ import annotations

import io
import re

from fastapi import File, Form, HTTPException, Request, UploadFile
from pypdf import PdfReader

from core.extraction.extractor import SkillExtractor
from core.github_profile.fetcher import GitHubFetchError, fetch_github_profile
from core.match.fit_scorer import compute_match
from core.match.listing_parser import ListingProfile
from core.match.verdict_explainer import explain_verdict
from core.resume.parser import ResumeParseError, parse_resume_text


def _split_field(raw: str) -> list[str]:
    parts = re.split(r"[\n,]+", raw or "")
    return [p.strip() for p in parts if p.strip()]


async def _read_pdf_text(file: UploadFile, max_bytes: int = 5 * 1024 * 1024) -> str:
    content = await file.read(max_bytes + 1)
    if len(content) > max_bytes:
        raise HTTPException(413, "File exceeds the 5MB limit")
    if not content.startswith(b"%PDF-"):
        raise HTTPException(422, "File is not a valid PDF (missing %PDF header)")
    try:
        reader = PdfReader(io.BytesIO(content))
        return "\n".join(p.extract_text() or "" for p in reader.pages)
    except Exception as e:
        raise HTTPException(422, f"Could not read PDF: {e}")


def register_role_fit_direct(app, settings, limiter, EXTRACTOR: SkillExtractor):
    """Register the /role-fit-direct route on the FastAPI app."""

    @app.post("/role-fit-direct")
    @limiter.limit(settings.rate_limit_analyze)
    async def role_fit_direct(
        request: Request,
        listing_title: str = Form(...),
        listing_company: str = Form(...),
        listing_location: str = Form(default=""),
        required_skills_raw: str = Form(default=""),
        eligibility_raw: str = Form(default=""),
        min_cgpa: str = Form(default=""),
        eligible_branches_raw: str = Form(default=""),
        resume_file: UploadFile | None = File(None),
        resume_text: str | None = Form(None),
        academic_marks: str | None = Form(None),
        github_username: str | None = Form(None),
    ):
        # ── Resolve resume text ──────────────────────────────────────────
        text: str = ""
        if resume_text and resume_text.strip():
            text = resume_text.strip()
        elif resume_file is not None:
            text = await _read_pdf_text(resume_file)
        if not text:
            raise HTTPException(422, "Provide resume_file (PDF) or resume_text.")

        # ── Parse the resume ─────────────────────────────────────────────
        try:
            profile = parse_resume_text(text, EXTRACTOR)
        except ResumeParseError as e:
            raise HTTPException(422, str(e))

        # ── GitHub enrichment (optional, degrades gracefully) ────────────
        github_skills: dict[str, int] = {}
        github_status = "not_requested"
        if github_username and github_username.strip():
            try:
                gh = fetch_github_profile(github_username.strip(), EXTRACTOR)
                github_skills = gh.skills
                github_status = f"ok ({gh.repo_count} repos)"
            except GitHubFetchError as e:
                github_status = f"skipped: {e}"

        all_candidate_skills = profile.skill_names | set(github_skills)

        # ── Parse academic marks ─────────────────────────────────────────
        marks: list[float] = []
        if academic_marks:
            try:
                marks = [float(m.strip()) for m in academic_marks.split(",") if m.strip()]
            except ValueError:
                raise HTTPException(422, "academic_marks must be comma-separated numbers e.g. '94.6,84.3'")

        # ── Build the listing profile from raw page fields ───────────────
        raw_tags = _split_field(required_skills_raw)
        tech_skills: list[str] = []
        unmatched_tags: list[str] = []
        seen: set[str] = set()

        for tag in raw_tags:
            found = EXTRACTOR.extract_names(tag)
            if found:
                for name in found:
                    if name not in seen:
                        tech_skills.append(name)
                        seen.add(name)
            else:
                unmatched_tags.append(tag)

        listing = ListingProfile(
            listing_id="live",
            title=listing_title,
            company=listing_company,
            location=listing_location,
            category="",
            job_type="",
            experience_level="Entry Level",
            stipend="",
            eligible_branches=tuple(_split_field(eligible_branches_raw)),
            tech_skills=tuple(tech_skills),
            unmatched_tags=tuple(unmatched_tags),
            raw_tags=tuple(raw_tags),
        )

        # ── Score and explain ─────────────────────────────────────────────
        result = compute_match(listing, all_candidate_skills, marks)
        explanation = explain_verdict(result, api_key=settings.groq_api_key)

        return {
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
            "github_status": github_status,
            "github_skills_used": sorted(github_skills.keys()),
            "eligible_branches": list(listing.eligible_branches),
            "eligibility_notes": _split_field(eligibility_raw),
            "min_cgpa": min_cgpa.strip() or None,
        }
