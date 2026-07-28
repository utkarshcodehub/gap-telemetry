import pytest
from core.extraction.extractor import SkillExtractor, preprocess
from core.extraction.demand import aggregate_demand
from core.taxonomy.loader import Taxonomy


@pytest.fixture(scope="module")
def extractor():
    return SkillExtractor()


def test_react_variants_all_map_to_react(extractor):
    for variant in ["ReactJS", "React.js", "react js", "REACT"]:
        names = extractor.extract_names(f"We need {variant} experience")
        assert "React" in names, f"failed on: {variant}"


def test_llm_umbrella_terms(extractor):
    names = extractor.extract_names("Experience with GenAI and LLMs, ideally LLaMA fine tuning")
    assert "Large Language Models" in names
    assert "Fine-tuning" in names


def test_react_native_not_double_counted(extractor):
    skills = extractor.extract("Build apps with React Native")
    names = {s.canonical for s in skills}
    assert "React Native" in names
    assert "React" not in names


def test_machine_learning_beats_fragments(extractor):
    names = extractor.extract_names("Strong machine learning fundamentals")
    assert "Machine Learning" in names


def test_go_language_no_false_positive(extractor):
    names = extractor.extract_names("We are going to grow the mongo team")
    assert "Go" not in names
    assert "MongoDB" in names


def test_r_language_no_false_positive(extractor):
    names = extractor.extract_names("Register for our hiring drive")
    assert "R" not in names


def test_comma_jammed_skills(extractor):
    names = extractor.extract_names("Skills: Python,SQL,Excel,Power BI")
    assert {"Python", "SQL", "Excel", "Power BI"} <= names


def test_slash_separated_skills(extractor):
    names = extractor.extract_names("Frontend: React.js/Next.js/Tailwind")
    assert {"React", "Next.js", "Tailwind CSS"} <= names


def test_realistic_naukri_posting(extractor):
    posting = """
    Job Title: AI/ML Engineer Intern
    We're looking for candidates with hands-on Python, strong DSA,
    experience building REST APIs (FastAPI/Flask preferred), and
    exposure to LLMs & prompt engineering. Knowledge of Docker,
    Git/GitHub and SQL (PostgreSQL) required. Bonus: RAG pipelines,
    vector databases (Pinecone/ChromaDB), scikit-learn.
    """
    names = extractor.extract_names(posting)
    expected = {"Python", "Data Structures & Algorithms", "REST API", "FastAPI", "Flask",
                "Large Language Models", "Prompt Engineering", "Docker", "Git", "SQL",
                "PostgreSQL", "RAG", "Vector Databases", "scikit-learn"}
    missing = expected - names
    assert not missing, f"missed: {missing}"


def test_counts_and_surfaces(extractor):
    skills = extractor.extract("Python developer. Python required. python!")
    py = next(s for s in skills if s.canonical == "Python")
    assert py.count == 3
    assert py.category == "programming_language"


def test_demand_uses_document_frequency():
    postings = ["Python Python Python needed", "Python and SQL", "Java only", "SQL analyst"]
    demand = aggregate_demand(postings)
    by_name = {d.canonical: d for d in demand}
    assert by_name["Python"].demand_pct == 50.0
    assert by_name["Python"].total_mentions == 4
    assert by_name["SQL"].demand_pct == 50.0
    assert by_name["Java"].demand_pct == 25.0


def test_taxonomy_has_no_alias_collisions():
    t = Taxonomy()
    assert len(t) > 90


def test_preprocess():
    assert preprocess("Python,SQL/Excel|Git") == "Python SQL Excel Git"
