"""
Phase 1 tests: listing parser + fit-score aggregator.

Every expected value below was computed by hand first, then encoded as an
assertion — the same verification principle as the evaluation harness tests.
"""

import json
from pathlib import Path

import pytest

from core.extraction.extractor import SkillExtractor, preprocess
from core.match.listing_parser import parse_listing, ListingProfile
from core.match.fit_scorer import (
    MatchResult,
    compute_match,
    _academic_contribution,
    _verdict,
    SKILL_WEIGHT,
    ACADEMIC_WEIGHT,
)

MOCK_LISTINGS_PATH = Path(__file__).resolve().parents[1] / "core" / "match" / "mock_listings.json"


@pytest.fixture(scope="module")
def extractor():
    return SkillExtractor()


# ── Bug-fix verification: the camelCase/slash issues from the real portal ──

def test_camelcase_splitting():
    assert "React Native" in preprocess("ReactNative")
    assert "MERN" in preprocess("MERNStack")


def test_ampersand_splitting():
    assert "&" not in preprocess("Clean&maintainablecoding")


def test_slash_splitting():
    result = preprocess("Python/Django")
    assert "Python" in result
    assert "Django" in result


def test_react_native_squished_resolves(extractor):
    assert "React Native" in extractor.extract_names("ReactNative")


def test_mern_stack_squished_resolves(extractor):
    assert "React" in extractor.extract_names("MERNStack")


def test_python_django_slash_resolves(extractor):
    names = extractor.extract_names("Python/Django")
    assert "Python" in names
    assert "Django" in names


def test_soft_skill_mush_correctly_unmatched(extractor):
    assert extractor.extract_names("logicalthinking") == set()
    assert extractor.extract_names("Clean&maintainablecoding") == set()
    assert extractor.extract_names("problemsolving") == set()


# ── Listing parser ──

def test_parse_eve_listing(extractor):
    listing_dict = {
        "id": "eve-sde-01", "title": "SDE", "company": "EVE Healthcare",
        "location": "Gurgaon", "category": "Service Based",
        "job_type": "Internship + PPO", "experience_level": "Entry Level",
        "stipend": "₹10,000/month",
        "eligible_branches": ["CSE", "IT", "CS (AI&ML)", "CS (DS)"],
        "required_skills": ["problemsolving", "logicalthinking",
                           "Clean&maintainablecoding", "Python/Django",
                           "ReactNative", "MERNStack"],
    }
    profile = parse_listing(listing_dict, extractor)

    # tech skills: Python, Django, React Native, React (from MERN)
    assert "Python" in profile.tech_skills
    assert "Django" in profile.tech_skills
    assert "React Native" in profile.tech_skills
    assert "React" in profile.tech_skills

    # unmatched: the three soft-skill mush tags
    assert "problemsolving" in profile.unmatched_tags
    assert "logicalthinking" in profile.unmatched_tags
    assert "Clean&maintainablecoding" in profile.unmatched_tags


def test_parse_all_mock_listings_without_crashing(extractor):
    data = json.loads(MOCK_LISTINGS_PATH.read_text())
    for listing_dict in data["listings"]:
        profile = parse_listing(listing_dict, extractor)
        assert profile.listing_id
        assert profile.title
        assert len(profile.tech_skills) + len(profile.unmatched_tags) > 0


def test_no_duplicate_skills_in_parsed_listing(extractor):
    listing_dict = {
        "id": "dup-test", "title": "T", "company": "C", "location": "L",
        "category": "C", "job_type": "J", "experience_level": "E",
        "stipend": "S", "eligible_branches": [],
        "required_skills": ["Python", "python", "Python/Django"],
    }
    profile = parse_listing(listing_dict, extractor)
    assert profile.tech_skills.count("Python") == 1


# ── Academic contribution (hand-verified math) ──

def test_academic_neutral_at_baseline():
    assert _academic_contribution([75.0]) == 0.0


def test_academic_bonus_capped():
    # 95% -> delta=20, * 0.5 = 10.0, capped at 10.0
    assert _academic_contribution([95.0]) == 10.0
    # 100% -> delta=25, * 0.5 = 12.5, capped at 10.0
    assert _academic_contribution([100.0]) == 10.0


def test_academic_penalty_capped():
    # 50% -> delta=-25, * 0.4 = -10.0, capped at -8.0
    assert _academic_contribution([50.0]) == -8.0


def test_academic_with_no_marks():
    assert _academic_contribution([]) == 0.0


# ── Verdict labels ──

def test_verdict_thresholds():
    assert _verdict(85) == "Strong Fit"
    assert _verdict(80) == "Strong Fit"
    assert _verdict(79) == "Good Fit"
    assert _verdict(60) == "Good Fit"
    assert _verdict(59) == "Partial Fit"
    assert _verdict(40) == "Partial Fit"
    assert _verdict(39) == "Needs Work"


# ── Fit scorer: hand-computed expected values ──

def _make_listing(tech_skills: list[str], unmatched: list[str] | None = None) -> ListingProfile:
    return ListingProfile(
        listing_id="test", title="T", company="C", location="L",
        category="C", job_type="J", experience_level="E", stipend="S",
        eligible_branches=(), tech_skills=tuple(tech_skills),
        unmatched_tags=tuple(unmatched or []), raw_tags=(),
    )


def test_perfect_skill_match_no_academics():
    listing = _make_listing(["Python", "SQL"])
    result = compute_match(listing, {"Python", "SQL"})
    # skill_pct = 100%, academic_adj = 0 (no marks)
    # raw = (100 * 0.85) + ((50 + 0) * 0.15) = 85 + 7.5 = 92.5
    assert result.skill_match_pct == 100.0
    assert result.match_pct == 92.5
    assert result.verdict == "Strong Fit"
    assert result.missing_skills == ()


def test_zero_skill_match_no_academics():
    listing = _make_listing(["Python", "SQL"])
    result = compute_match(listing, {"Java"})
    # skill_pct = 0%, academic_adj = 0
    # raw = (0 * 0.85) + ((50 + 0) * 0.15) = 0 + 7.5 = 7.5
    assert result.skill_match_pct == 0.0
    assert result.match_pct == 7.5
    assert result.verdict == "Needs Work"
    assert set(result.missing_skills) == {"Python", "SQL"}


def test_partial_match_with_good_academics():
    listing = _make_listing(["Python", "SQL", "Docker", "React"])
    result = compute_match(listing, {"Python", "SQL"}, academic_marks=[90.0])
    # skill_pct = 50%, academic_adj = (90-75)*0.5 = 7.5
    # raw = (50 * 0.85) + ((50 + 7.5) * 0.15) = 42.5 + 8.625 = 51.125 -> 51.1
    assert result.skill_match_pct == 50.0
    assert result.academic_adjustment == 7.5
    assert result.match_pct == 51.1
    assert result.verdict == "Partial Fit"


def test_partial_match_with_poor_academics():
    listing = _make_listing(["Python", "SQL", "Docker", "React"])
    result = compute_match(listing, {"Python", "SQL"}, academic_marks=[55.0])
    # skill_pct = 50%, academic_adj = (55-75)*0.4 = -8.0
    # raw = (50 * 0.85) + ((50 + (-8.0)) * 0.15) = 42.5 + 6.3 = 48.8
    assert result.skill_match_pct == 50.0
    assert result.academic_adjustment == -8.0
    assert result.match_pct == 48.8
    assert result.verdict == "Partial Fit"


def test_academics_cant_push_above_100_or_below_0():
    listing = _make_listing(["Python"])
    high = compute_match(listing, {"Python"}, academic_marks=[100.0])
    assert high.match_pct <= 100.0
    low = compute_match(listing, set(), academic_marks=[40.0])
    assert low.match_pct >= 0.0


def test_unmatched_tags_pass_through():
    listing = _make_listing(["Python"], unmatched=["logicalthinking", "problemsolving"])
    result = compute_match(listing, {"Python"})
    assert result.unmatched_tags == ("logicalthinking", "problemsolving")


def test_empty_tech_skills_gives_neutral_score():
    listing = _make_listing([], unmatched=["problemsolving", "logicalthinking"])
    result = compute_match(listing, {"Python"})
    assert result.match_pct == 50.0
    assert result.verdict == "Partial Fit"


# ── End-to-end: real mock listing + real resume extraction ──

def test_eve_listing_against_utkarsh_profile(extractor):
    data = json.loads(MOCK_LISTINGS_PATH.read_text())
    eve = next(l for l in data["listings"] if l["id"] == "eve-sde-01")
    listing = parse_listing(eve, extractor)

    resume_text = """
    Python, FastAPI, React.js, Next.js, SQL, SQLite, Git, spaCy, XGBoost
    Projects: ProPrompter using Groq LLaMA, F1 Race Predictor
    """
    resume_skills = extractor.extract_names(resume_text)
    result = compute_match(listing, resume_skills, academic_marks=[94.6, 84.3])

    # Utkarsh has Python and React (from his resume), listing wants Python,
    # Django, React Native, React — partial match expected
    assert result.verdict in ("Good Fit", "Partial Fit")
    assert "Python" in result.matched_skills
    assert "React" in result.matched_skills
    assert "Django" in result.missing_skills
    assert "React Native" in result.missing_skills
    assert len(result.unmatched_tags) >= 2  # the soft-skill mush tags


def test_startupx_listing_against_utkarsh_profile(extractor):
    data = json.loads(MOCK_LISTINGS_PATH.read_text())
    startupx = next(l for l in data["listings"] if l["id"] == "startupx-ai-01")
    listing = parse_listing(startupx, extractor)

    resume_text = """
    Python, FastAPI, React.js, SQL, Git, spaCy, XGBoost,
    LLMs, prompt engineering, Groq LLaMA
    """
    resume_skills = extractor.extract_names(resume_text)
    result = compute_match(listing, resume_skills, academic_marks=[94.6, 84.3])

    # StartupX wants Python, LLMs, LangChain, FastAPI, RAG, VectorDatabases,
    # PromptEngineering, Docker. Utkarsh has Python, FastAPI, LLMs, PromptEng.
    assert "Python" in result.matched_skills
    assert "FastAPI" in result.matched_skills
    assert "Large Language Models" in result.matched_skills
    assert result.verdict in ("Good Fit", "Partial Fit")
