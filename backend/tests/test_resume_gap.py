import pytest
from fpdf import FPDF

from core.gap.scorer import score_gap, MIN_DEMAND_PCT
from core.resume.parser import ResumeParseError, parse_resume, parse_resume_text

SAMPLE_RESUME_TEXT = """
Utkarsh Raj - B.Tech CSE
TECHNICAL SKILLS
Python, FastAPI, React.js, Next.js, SQL, SQLite, Git, spaCy
PROJECTS
ProPrompter: prompt optimizer using Groq LLaMA (LLMs, prompt engineering)
F1 Race Predictor: XGBoost model with Streamlit dashboard
EXPERIENCE
AI training evaluation on Outlier and Mindrift platforms
"""


@pytest.fixture(scope="module")
def sample_pdf(tmp_path_factory):
    path = tmp_path_factory.mktemp("resume") / "resume.pdf"
    pdf = FPDF()
    pdf.add_page()
    pdf.set_font("Helvetica", size=11)
    for line in SAMPLE_RESUME_TEXT.strip().splitlines():
        pdf.cell(0, 8, line, new_x="LMARGIN", new_y="NEXT")
    pdf.output(str(path))
    return path


def test_parse_resume_pdf(sample_pdf):
    profile = parse_resume(sample_pdf)
    assert {"Python", "FastAPI", "React", "SQL", "Large Language Models", "XGBoost"} <= profile.skill_names
    assert "technical skills" in profile.sections_found
    assert "projects" in profile.sections_found


def test_missing_file_raises():
    with pytest.raises(ResumeParseError, match="not found"):
        parse_resume("/nonexistent/resume.pdf")


def test_parse_resume_text_same_pipeline():
    profile = parse_resume_text(SAMPLE_RESUME_TEXT)
    assert "Prompt Engineering" in profile.skill_names


MARKET = [
    {"canonical": "Python", "category": "programming_language", "demand_pct": 90.0, "postings_count": 90, "total_mentions": 120},
    {"canonical": "Machine Learning", "category": "ml_ai", "demand_pct": 80.0, "postings_count": 80, "total_mentions": 95},
    {"canonical": "Docker", "category": "cloud_devops", "demand_pct": 40.0, "postings_count": 40, "total_mentions": 44},
    {"canonical": "SQL", "category": "programming_language", "demand_pct": 60.0, "postings_count": 60, "total_mentions": 70},
    {"canonical": "Kubernetes", "category": "cloud_devops", "demand_pct": 20.0, "postings_count": 20, "total_mentions": 21},
    {"canonical": "Terraform", "category": "cloud_devops", "demand_pct": 10.0, "postings_count": 10, "total_mentions": 10},
    {"canonical": "Communication", "category": "soft_skill", "demand_pct": 50.0, "postings_count": 50, "total_mentions": 55},
    {"canonical": "Rust", "category": "programming_language", "demand_pct": 1.0, "postings_count": 1, "total_mentions": 1},
]


def test_readiness_is_demand_weighted():
    report = score_gap("test", MARKET, resume_skills={"Python", "SQL"})
    assert report.readiness_score == 50.0


def test_missing_high_demand_hurts_more():
    with_python = score_gap("t", MARKET, {"Python"})
    with_terraform = score_gap("t", MARKET, {"Terraform"})
    assert with_python.readiness_score > with_terraform.readiness_score


def test_noise_floor_excludes_rare_skills():
    report = score_gap("t", MARKET, set())
    names = {g.canonical for g in report.gaps}
    assert "Rust" not in names
    assert MIN_DEMAND_PCT == 5.0


def test_soft_skills_excluded_from_math():
    without = score_gap("t", MARKET, {"Python"})
    with_comm = score_gap("t", MARKET, {"Python", "Communication"})
    assert without.readiness_score == with_comm.readiness_score


def test_gap_tiers_by_demand_rank():
    report = score_gap("t", MARKET, set())
    tiers = {g.canonical: g.tier for g in report.gaps}
    assert tiers["Python"] == "critical"
    assert tiers["Terraform"] == "nice_to_have"


def test_hidden_strengths_from_github():
    report = score_gap("t", MARKET, resume_skills={"Python"}, github_skills={"Docker": 3, "Python": 2})
    hidden = {h.canonical for h in report.hidden_strengths}
    assert hidden == {"Docker"}
    ev = {s.canonical: s.evidence for s in report.strengths}
    assert ev["Python"] == "resume+github"
    assert ev["Docker"] == "github"
    assert any("Resume upgrade" in n for n in report.notes)


def test_github_skills_count_toward_readiness():
    resume_only = score_gap("t", MARKET, {"Python"})
    plus_github = score_gap("t", MARKET, {"Python"}, {"Docker": 2})
    assert plus_github.readiness_score > resume_only.readiness_score


def test_extras_are_market_silent_skills():
    report = score_gap("t", MARKET, {"Python", "Blockchain"})
    assert "Blockchain" in report.extras


def test_empty_market():
    report = score_gap("t", [], {"Python"})
    assert report.readiness_score == 0.0
    assert any("empty" in n for n in report.notes)


def test_github_fetcher_parses_repos(monkeypatch):
    import core.github_profile.fetcher as gh

    fake_repos = [
        {"name": "proprompter", "fork": False, "language": "TypeScript",
         "description": "Prompt optimizer with FastAPI backend and Groq LLaMA",
         "topics": ["nextjs", "fastapi", "supabase"]},
        {"name": "f1-race-predictor", "fork": False, "language": "Python",
         "description": "XGBoost race prediction with Streamlit",
         "topics": ["machine-learning", "xgboost"]},
        {"name": "some-fork", "fork": True, "language": "Go",
         "description": "Forked repo must be ignored", "topics": []},
    ]

    class FakeResp:
        status_code = 200
        def json(self): return fake_repos
        def raise_for_status(self): pass

    class FakeReadmeResp:
        status_code = 404  # no README on any of these fake repos

    def fake_get(url, *a, **k):
        return FakeReadmeResp() if "/readme" in url else FakeResp()

    monkeypatch.setattr(gh.requests, "get", fake_get)
    profile = gh.fetch_github_profile("testuser")

    assert profile.repo_count == 2
    assert "Go" not in profile.languages
    assert profile.skills["Python"] >= 1
    assert "FastAPI" in profile.skills
    assert "Large Language Models" in profile.skills
    assert "XGBoost" in profile.skills
