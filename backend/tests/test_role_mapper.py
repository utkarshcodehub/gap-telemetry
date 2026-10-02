"""
Tests for the title -> role_query mapper (core/taxonomy/roles.py).

Every case below is a real title from one of the two corpora, and most of them
encode a bug that was actually shipped and then fixed. Pure unit tests -- no
network, no database.
"""

from __future__ import annotations

import pytest

from core.taxonomy.roles import (
    CANONICAL_ROLES,
    explain_title,
    map_title,
    normalize_title,
)


# --------------------------------------------------------------- tier ordering

def test_explicit_role_beats_technology_token():
    """Regression: the headline mapper bug.

    'Hiring: Backend Developer - Nestjs & Typescript' was classified FRONTEND,
    because a single-tier rule list reached `typescript` before `back end`.
    TypeScript is written on both sides of the stack; "Backend Developer" is not
    ambiguous. An explicit role statement must outrank an inference.
    """
    assert map_title("Hiring: Backend Developer – Nestjs & Typescript") == "backend developer"


def test_full_stack_beats_its_component_signals():
    """'Full Stack Java Developer' must not become backend on the Java token."""
    for title in [
        "Full Stack Java Developer - Spring Boot/ Docker",
        "C#.net Full Stack Engineer-Immediate Joiner",
        "Software Senior Principal Engineer (Java full stack)",
        "Full stack - Java, Spring boot, Microservices",
    ]:
        assert map_title(title) == "full stack developer", title


def test_server_side_framework_beats_bare_language():
    """NestJS/Django say 'backend' more precisely than TypeScript/JS do."""
    assert map_title("Nestjs Engineer") == "backend developer"
    assert map_title("Django Engineer") == "backend developer"
    # ...but a bare frontend language with no server framework stays frontend.
    assert map_title("TypeScript Engineer") == "frontend developer"


def test_ml_phrase_beats_data_engineer_but_a_modifier_does_not():
    """An explicit ML role name wins; 'ML' as a mere modifier does not.

    "ML Engineer - Data Pipelines" is an ML role. "ML Data Engineer" is a data
    engineer who works on ML pipelines -- the head noun is 'Data Engineer' and
    'ML' only qualifies it. Reading the modifier as the role would misfile a
    large family of real titles.
    """
    assert map_title("ML Engineer - Data Pipelines") == "ai ml engineer"
    assert map_title("Machine Learning Engineer, Data Platform") == "ai ml engineer"
    assert map_title("ML Data Engineer") == "data engineer"


def test_data_engineer_beats_data_analyst():
    assert map_title("Data Engineer - Big Data") == "data engineer"


# ------------------------------------------------------------------ exclusions

def test_non_engineering_roles_are_excluded_not_mapped():
    """Regression: an academic-writing gig was classified as an ML engineer.

    'Part Time Academic Writer For Econometric/Data Science/Statistics' matched
    `data science` before anything checked whether it was an engineering job.
    """
    for title in [
        "Part Time Academic Writer For Econometric/Data Science/Statistics",
        "Technical Trainer- Data Analytics Training Manager (noida)",
        "Technical Sales Engineer/ Field Sales Engineer",
        "US Healthcare Recruiter- must have experience of US healthcare hiring",
        "Customer Service Executive @ Techmbs ( Malad, Mumbai)",
        "Business Development Executive",
    ]:
        assert map_title(title) is None, f"should be excluded: {title}"


def test_cloud_admin_titles_map_to_devops():
    """Regression: a bare \\badmin\\b exclusion rejected this real cloud role."""
    assert map_title("Azure Admin") == "devops engineer"
    assert map_title("AWS System Administrator") == "devops engineer"
    # ...but a cloud token must not outrank a more specific data role.
    assert map_title("Azure Data Engineer") == "data engineer"


@pytest.mark.parametrize("title", [
    "Model Training Engineer",   # bare \btraining\b would have rejected this
    "Production Support Engineer",  # bare \bproduction\b would have
])
def test_narrowed_exclusions_no_longer_reject_engineering_titles(title):
    """These may or may not map to a role -- the point is that they are no
    longer EXCLUDED as non-engineering. 'unmapped' and 'excluded' are different
    outcomes, and only the second would be a bug here."""
    _, why = explain_title(title)
    assert not why.startswith("excluded:"), f"{title} was excluded by {why}"


def test_non_software_testing_is_excluded():
    """5G/telecom testing is not software QA."""
    assert map_title("5G Testing Engineers /Test Lead openings") is None


# -------------------------------------------------------------------- recall

def test_technology_need_not_be_adjacent_to_developer():
    """Regression: patterns once required 'java developer' as a phrase, so
    IBM/Accenture-style titles naming the tech after a colon all failed."""
    assert map_title("Application Developer: Java & Web Technologies") == "backend developer"
    assert map_title("Application Developer: Microsoft .NET") == "backend developer"


def test_java_token_does_not_match_javascript():
    """\\bjava\\b must not fire inside 'JavaScript' -- the trailing 's'
    defeats the word boundary, and this is load-bearing."""
    assert map_title("JavaScript Developer") == "frontend developer"


# ------------------------------------------------------- rejection is a choice

def test_role_unspecified_titles_are_rejected_not_guessed():
    """These state no specialism. Forcing them into a role to recover volume
    would corrupt every demand percentage computed afterwards."""
    for title in ["Software Engineer", "Software Sr Engineer", "Associate",
                  "Sr. Associate - Projects", "Job Description", "Team Leader",
                  "Programmer Analyst"]:
        assert map_title(title) is None, f"should be rejected: {title}"


def test_blank_and_junk_titles_are_rejected():
    assert map_title("") is None
    assert map_title("   ") is None
    assert map_title("!!!") is None


# ------------------------------------------------------------- normalisation

def test_normalize_strips_mojibake_and_flattens_separators():
    # The Naukri corpus contains mangled en-dashes.
    assert normalize_title("Sr. Associate � Projects") == "sr. associate projects"
    assert normalize_title("Application Developer: Java") == "application developer java"
    assert normalize_title("  Multiple   Spaces  ") == "multiple spaces"


def test_mapping_is_case_insensitive():
    assert map_title("BACKEND DEVELOPER") == map_title("backend developer") == "backend developer"


# ------------------------------------------------------------------- contract

def test_every_mapped_role_is_in_the_canonical_vocabulary():
    titles = ["Backend Developer", "Frontend Developer", "Full Stack Developer",
              "Data Analyst", "Data Engineer", "Machine Learning Engineer",
              "DevOps Engineer", "QA Engineer"]
    produced = {map_title(t) for t in titles}
    assert None not in produced
    assert produced <= set(CANONICAL_ROLES)
    # These eight titles should between them cover the whole vocabulary.
    assert produced == set(CANONICAL_ROLES)


def test_explain_title_reports_a_reason_for_every_outcome():
    role, why = explain_title("Backend Developer")
    assert role == "backend developer" and why

    role, why = explain_title("Software Engineer")
    assert role is None and why == "no_rule"

    role, why = explain_title("Field Sales Engineer")
    assert role is None and why.startswith("excluded:")
