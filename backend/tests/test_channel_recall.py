"""
Tests for the channel-map recall measurement (scripts/measure_channel_recall.py).

No network: the measurement's collection half is the collector, which
test_evidence_github.py already covers against fixtures. What is tested here is
the reasoning half -- the part that decides what a miss MEANS -- plus two
invariants between the labels and the map that would otherwise rot silently.

The whole point of the measurement is to stop a hole in the map from entering
Dataset A as ground truth. Logic that classified misses wrongly would do exactly
that, one level up.
"""

from __future__ import annotations

import pytest

from core.evidence.channels import CHANNELS
from core.taxonomy.loader import Taxonomy
from scripts.measure_channel_recall import (
    blind_spots,
    classify,
    package_to_skills,
)
from scripts.recall_labels import LABELS, Verdict


@pytest.fixture(scope="module")
def taxonomy():
    return Taxonomy()


# ------------------------------------------------------------------- the map

def test_package_to_skills_inverts_the_map():
    known = package_to_skills()
    assert "react" in known and "React" in known["react"]


def test_a_package_can_evidence_more_than_one_skill():
    """`express` is both Express.js and Node.js, so the inverted map has to hold
    a list. A dict of single skills would silently drop one of them."""
    known = package_to_skills()
    assert set(known["express"]) == {"Express.js", "Node.js"}


# -------------------------------------------------------------- classify()

def test_an_unlabelled_package_is_reported_not_assumed_harmless():
    """Treating unjudged packages as noise would let recall improve by not
    looking, which is the one failure mode a recall measurement cannot have."""
    verdict, _, _ = classify("some-package-nobody-has-judged", Taxonomy())
    assert verdict == Verdict.UNLABELLED


def test_a_skill_the_taxonomy_lacks_is_not_the_maps_problem(taxonomy):
    verdict, skill, why = classify("streamlit", taxonomy)
    assert verdict == Verdict.NO_TAXONOMY_ENTRY
    assert skill == "Streamlit"
    assert "no canonical entry" in why


def test_a_conflated_skill_is_not_the_maps_problem_either(taxonomy):
    """The trap that nearly produced a false verification.

    The taxonomy files "Web Scraping" as an ALIAS OF SELENIUM, so mapping
    `beautifulsoup4` would have evidenced Selenium for candidates who have never
    used a browser driver. canonicalize() returning something non-None is not
    enough -- it has to return the skill that was asked about.
    """
    verdict, skill, why = classify("beautifulsoup4", taxonomy)
    assert verdict == Verdict.NO_TAXONOMY_ENTRY
    assert skill == "Web Scraping"
    assert "Selenium" in why


def test_an_unverifiable_by_design_target_is_not_the_maps_problem(taxonomy):
    """`bcrypt` is deliberate, specific work whose only fitting taxonomy entry is
    Cybersecurity -- which channels.py marks unverifiable by design (EC-9).
    Attaching packages there would quietly make a concept checkable."""
    verdict, skill, _ = classify("bcrypt", taxonomy)
    assert verdict == Verdict.NO_TAXONOMY_ENTRY
    assert skill == "Authentication"


def test_noise_verdicts_pass_through_unchanged(taxonomy):
    assert classify("anyio", taxonomy)[0] == Verdict.TRANSITIVE
    assert classify("eslint", taxonomy)[0] == Verdict.NOT_A_SKILL
    assert classify("codegen-units", taxonomy)[0] == Verdict.PARSER_ARTIFACT


# ------------------------------------------------------------ blind_spots()

def _profile(**repo) -> list[dict]:
    return [{"username": "u", "repo_detail": [repo]}]


def test_a_miss_with_a_sibling_signal_is_not_a_blind_spot():
    """`lucide-react` unmapped costs nothing in a repo where `react` sits next to
    it. Counting it would inflate the list of things worth fixing."""
    spots = blind_spots(_profile(repo="web", evidenced=["React"],
                                 unrecognised=["lucide-react"]))
    assert spots == {}


def test_a_miss_that_was_the_only_signal_is_a_blind_spot():
    spots = blind_spots(_profile(repo="app", evidenced=["Python"],
                                 unrecognised=["streamlit"]))
    assert spots["streamlit"]["skill"] == "Streamlit"
    assert spots["streamlit"]["repos"] == 1


def test_noise_is_never_a_blind_spot():
    spots = blind_spots(_profile(repo="api", evidenced=[],
                                 unrecognised=["anyio", "h11", "version"]))
    assert spots == {}


def test_blind_spots_count_repos_but_deduplicate_profiles():
    """A package in six of one candidate's repos is one candidate's problem. Both
    numbers are reported because they answer different questions: how often it
    bites, and how many people it bites."""
    profiles = [
        {"username": "a", "repo_detail": [
            {"repo": "1", "evidenced": [], "unrecognised": ["vite"]},
            {"repo": "2", "evidenced": [], "unrecognised": ["vite"]},
        ]},
        {"username": "b", "repo_detail": [
            {"repo": "3", "evidenced": [], "unrecognised": ["vite"]},
        ]},
    ]
    assert blind_spots(profiles)["vite"] == {"skill": "Vite", "repos": 3, "profiles": 2}


# ----------------------------------------------- invariants between the two

def test_the_map_never_recognises_a_package_labelled_as_noise():
    """The invariant that keeps the two files honest about each other.

    If the map credited a package judged transitive, not-a-skill or a parser
    artifact, it would be verifying a skill from a dependency resolver's output
    rather than from a choice the candidate made.
    """
    known = package_to_skills()
    noise = {Verdict.TRANSITIVE, Verdict.NOT_A_SKILL, Verdict.PARSER_ARTIFACT}
    offenders = {pkg: (label.verdict, known[pkg])
                 for pkg, label in LABELS.items()
                 if label.verdict in noise and pkg in known}
    assert offenders == {}


def test_every_skill_label_names_a_real_or_deliberately_absent_skill(taxonomy):
    """A SKILL label must point at a canonical taxonomy name OR carry a note
    saying why it cannot. A typo'd skill name would otherwise sit in the lane C
    list forever looking like a real gap."""
    unexplained = [
        (pkg, label.skill) for pkg, label in LABELS.items()
        if label.verdict == Verdict.SKILL
        and taxonomy.canonicalize(label.skill) != label.skill
        and not label.note
    ]
    assert unexplained == [], "every unmappable skill needs its reason recorded"


def test_mapped_packages_are_not_still_listed_as_unmappable(taxonomy):
    """Once a package is in the map, its label must not claim the skill is
    unreachable -- that combination is how a fixed gap keeps being reported."""
    known = package_to_skills()
    contradictions = [
        pkg for pkg, label in LABELS.items()
        if pkg in known and label.verdict == Verdict.SKILL
        and classify(pkg, taxonomy)[0] == Verdict.NO_TAXONOMY_ENTRY
    ]
    assert contradictions == []


def test_concept_skills_never_gained_a_package_channel():
    """EC-9's guarantee, asserted rather than trusted: the measurement's whole
    temptation is to close a gap by attaching packages to a concept."""
    leaked = [s for s, spec in CHANNELS.items() if not spec.verifiable and spec.packages]
    assert leaked == []
