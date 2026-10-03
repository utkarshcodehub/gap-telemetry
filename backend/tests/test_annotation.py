"""
Tests for the Dataset A annotation tooling.

The tests that matter here all guard one property: **an annotator must never see
the engine's answer.** Ground truth anchored to the engine's output would make
experiment E1 a comparison of the engine with itself, and no amount of careful
statistics afterwards would recover from it. That failure is silent -- a leaked
verdict produces a dataset that looks fine and agrees suspiciously well -- so it
is asserted rather than trusted.

No network: the artifact digest is built from fake repo snapshots.
"""

from __future__ import annotations

import json

import pytest

from core.evidence.github import RepoSnapshot
from core.taxonomy.loader import Taxonomy
from scripts.annotate import LABELS, render_item, render_profile, search
from scripts.build_annotation_task import (
    build_items,
    excluded_skills,
    profile_digest,
    repo_digest,
    unreachable_skills,
)


def snap(name: str, *, language="Python", paths=(), packages=(), months=2.0,
         share=1.0) -> RepoSnapshot:
    return RepoSnapshot(
        name=name, primary_language=language, pushed_months_ago=months,
        tree_paths=tuple(paths), packages=frozenset(packages),
        authorship_share=share, tree_retrieved=True, manifest_retrieved=bool(packages),
    )


class FakeProfile:
    def __init__(self, repos, partial=False):
        self.repos = repos
        self.partial = partial


@pytest.fixture(scope="module")
def taxonomy():
    return Taxonomy()


# ------------------------------------------------- the no-leak guarantee

ENGINE_WORDS = ("verdict", "confidence", "verified", "unverifiable", "contradicted",
                "attested", "tier", "e0", "e1", "e2", "e3", "e4",
                "claimed_readiness", "max_tier")


def test_the_artifact_digest_carries_no_engine_output():
    """A digest key or value naming a verdict or a tier would hand the annotator
    the answer they are supposed to be producing independently."""
    d = repo_digest(snap("api", paths=("Dockerfile", "src/main.py"), packages=("fastapi",)))
    blob = json.dumps(d).lower()
    for word in ENGINE_WORDS:
        assert word not in blob, f"the digest leaks {word!r}"


def test_an_item_carries_no_engine_output():
    items = build_items("POP-01", "backend developer",
                        [{"skill": "Docker", "demand_pct": 71.0}])
    blob = json.dumps(items).lower()
    for word in ENGINE_WORDS:
        assert word not in blob, f"the item leaks {word!r}"


def test_the_digest_is_not_filtered_by_the_channel_map():
    """Showing only the paths that matched a skill's channel would be the engine's
    opinion of what is relevant, dressed as evidence. Every root file and every
    extension is shown, whether any channel knows about it or not."""
    repo = snap("thing", paths=("Dockerfile", "weird.xyz", "notes.txt",
                                "deep/nested/file.abc"))
    d = repo_digest(repo)
    assert "weird.xyz" in d["root_files"]
    assert ".xyz" in d["extensions"] and ".abc" in d["extensions"]
    assert "Dockerfile" in d["root_files"], "and nothing is privileged either"


def test_rendered_output_shows_no_verdict():
    prof = profile_digest(FakeProfile([snap("api", paths=("Dockerfile",))]), "POP-01")
    item = build_items("POP-01", "backend developer",
                       [{"skill": "Docker", "demand_pct": 71.0}])[0]
    text = (render_item(item, 1, 5) + render_profile(prof)).lower()
    for word in ("verdict", "confidence", "unverifiable", "contradicted"):
        assert word not in text


# ----------------------------------------------------------- the digest

def test_partial_collection_is_stated_because_it_changes_the_right_label():
    """When collection was incomplete, absence is not evidence and `u` is usually
    correct. An annotator who is not told would read a gap as an absence."""
    prof = profile_digest(FakeProfile([snap("a")], partial=True), "POP-02")
    assert prof["collection"] == "partial"
    assert "INCOMPLETE" in render_profile(prof)


def test_unknown_authorship_renders_as_a_question_mark_not_as_zero():
    """The commits API is often rate limited. That is our failure, not the
    candidate's, and rendering it as 0% would invite an unearned `n`."""
    prof = profile_digest(FakeProfile([snap("a", share=None)]), "POP-01")
    assert "0% of commits" not in render_profile(prof)
    assert "?" in render_profile(prof)


def test_search_looks_through_the_whole_tree_not_just_the_digest():
    """The digest is a summary; `/pattern` is how an annotator checks something the
    summary did not happen to surface."""
    prof = profile_digest(
        FakeProfile([snap("infra", paths=("deploy/k8s/deployment.yaml",))]), "POP-01")
    assert "deploy/k8s/deployment.yaml" in search(prof, "k8s")
    assert "no path contains" in search(prof, "terraform")


def test_labels_are_exactly_the_three_the_protocol_defines():
    assert set(LABELS.values()) == {"demonstrated", "not demonstrated", "undeterminable"}


# --------------------------------------------- what must not be labelled

def test_a_conflated_skill_is_excluded_from_items(taxonomy):
    """`Web Scraping` is an alias of `Selenium`, so a label recorded against
    Selenium may actually be about scraping with a parser. A label on the wrong
    skill is worse than no label."""
    assert "Selenium" in excluded_skills(taxonomy)


def test_the_exclusion_list_is_derived_not_hand_written(taxonomy):
    """It comes from the recall labels, so when lane C fixes a taxonomy entry the
    exclusion disappears by itself instead of outliving its cause."""
    for skill, reason in excluded_skills(taxonomy).items():
        assert taxonomy.canonicalize(skill) == skill
        assert reason, "every exclusion carries its reason"


def test_skills_with_no_canonical_entry_are_reported_rather_than_silently_absent(taxonomy):
    """They cannot become claims because they are not in the vocabulary -- which is
    exactly the lane C finding, so it is printed rather than left implicit."""
    unreachable = unreachable_skills(taxonomy)
    assert {"Streamlit", "Vite", "Pydantic", "Kotlin"} <= set(unreachable)
    for skill in unreachable:
        assert taxonomy.canonicalize(skill) is None


def test_excluded_skills_never_reach_an_item(taxonomy):
    """The guarantee the protocol's section 7 promises."""
    from scripts.build_annotation_task import candidate_skills

    excluded = excluded_skills(taxonomy)
    pytest.importorskip("supabase")
    try:
        skills = candidate_skills("backend developer", taxonomy, top_n=999,
                                  exclude=excluded)
    except Exception:                       # noqa: BLE001 - no DB in this environment
        pytest.skip("market corpus unavailable")
    assert not ({s["skill"] for s in skills} & set(excluded))


# ------------------------------------------- choosing Dataset A's profiles

def test_every_corpus_role_has_a_sampling_stratum():
    """Stratification is only meaningful if no role is missing one. The eight
    roles are the ones the posting corpus actually serves; Dataset A built from
    mobile-heavy profiles would evaluate a population the product does not have."""
    from scripts.sample_dataset_a import ROLE_QUERIES

    assert set(ROLE_QUERIES) == {
        "backend developer", "frontend developer", "full stack developer",
        "devops engineer", "qa engineer", "data engineer", "data analyst",
        "ai ml engineer",
    }
    for role, queries in ROLE_QUERIES.items():
        # Several per role, tried in order. One topic tag proved too narrow a pool:
        # terraform/HCL and machine-learning/Python each yielded exactly one
        # qualifying profile in 300 results, and no pool size could fix that.
        assert queries and all(q.strip() for q in queries), role


def test_the_location_filter_errs_toward_dropping_candidates():
    """Self-reported and imperfect. A false negative costs one candidate from a
    large pool; keeping the gates strict is the right direction."""
    from scripts.sample_dataset_a import looks_indian

    assert looks_indian("Bengaluru, India")
    assert looks_indian("pune")
    assert not looks_indian(None)
    assert not looks_indian("")
    assert not looks_indian("Berlin, Germany")


def test_the_manifest_gate_is_the_one_rn1_requires():
    """RN-1: only 26% of this population's repos declare dependencies, so a
    profile without several is a one-channel profile."""
    from scripts.sample_dataset_a import MIN_REPOS_WITH_MANIFEST

    assert MIN_REPOS_WITH_MANIFEST >= 3


def test_the_frozen_cohort_round_trips_by_role(tmp_path):
    """The role comments are structure, not decoration.

    The first full run left two strata one profile short, so topping a single role
    up is the normal way to finish a cohort. The freeze path therefore has to read
    the existing file back and merge -- an earlier version rewrote it from the
    current run's roles alone, which would have silently discarded the other six
    strata the moment anyone topped one up.
    """
    from scripts.sample_dataset_a import read_cohort_by_role, write_cohort_by_role

    path = tmp_path / "cohort.txt"
    original = {"backend developer": ["DSA-50", "DSA-51"],
                "devops engineer": ["DSA-56"]}
    write_cohort_by_role(path, original)
    assert read_cohort_by_role(path) == original

    merged = read_cohort_by_role(path)
    merged["devops engineer"].append("DSA-63")
    write_cohort_by_role(path, merged)
    back = read_cohort_by_role(path)
    assert back["devops engineer"] == ["DSA-56", "DSA-63"]
    assert back["backend developer"] == ["DSA-50", "DSA-51"], "other strata survive"


def test_an_unknown_role_comment_is_not_read_as_a_stratum(tmp_path):
    """Only the eight corpus roles are strata. A stray comment must not create a
    ninth, or a hand-edited file would quietly grow a role the corpus cannot serve."""
    from scripts.sample_dataset_a import read_cohort_by_role

    path = tmp_path / "cohort.txt"
    path.write_text(
        "# notes about something\nDSA-01\n# backend developer\nDSA-02\n",
        encoding="utf-8")
    assert read_cohort_by_role(path) == {"backend developer": ["DSA-02"]}


def test_ground_truth_is_not_collected_under_the_product_repo_cap():
    """Eight of the sixteen Dataset A profiles have 25+ repos, so collecting them
    at /analyze's cap would mark half the cohort `partial` -- which tells the
    annotator that absence is not evidence and steers them toward `u`, capping how
    many `n` labels the dataset can hold. `n` is what CONTRADICTED is measured
    against, so that cap would land on the verdict most in need of evaluation."""
    from core.evidence.github import MAX_REPOS
    from scripts.build_annotation_task import DATASET_BUDGET, DATASET_MAX_REPOS

    assert DATASET_MAX_REPOS > MAX_REPOS
    assert DATASET_BUDGET > 150, "NFR-2 bounds one live analysis, not dataset building"


def test_the_recency_gate_measures_a_share_not_a_single_repo():
    """A profile with 2 of 25 repos active is 92% dormant and passed the first
    implementation of a gate whose stated intent is that "a dormant profile tests a
    different thing"."""
    from scripts.sample_dataset_a import MIN_RECENT_SHARE

    assert 0 < MIN_RECENT_SHARE <= 1.0
    assert MIN_RECENT_SHARE >= 0.25


def test_the_view_is_bounded_but_the_data_is_not():
    """The cohort has profiles with 70 to 96 repos once the product's repo cap is
    off. Ninety-six blocks on one screen is not more evidence than twelve plus a
    search box -- it is less, because nobody reads it. So the VIEW is bounded while
    every tree stays searchable."""
    from scripts.annotate import REPOS_SHOWN

    many = FakeProfile([snap(f"repo{i}", paths=(f"r{i}/only_here.txt",), months=float(i))
                        for i in range(40)])
    prof = profile_digest(many, "DSA-59")

    default = render_profile(prof)
    assert f"showing the {REPOS_SHOWN} most recently pushed of 40" in default
    assert "repo39" not in default, "the tail is not rendered by default"

    assert "repo39" in render_profile(prof, show_all=True)
    assert "r39/only_here.txt" in search(prof, "only_here"), (
        "search covers every repo, bounded view or not")


def test_everything_declared_is_aggregated_across_the_profile():
    """For a claim about a library this one line is often the whole answer, and it
    does not depend on the annotator scrolling to the right repo."""
    prof = profile_digest(
        FakeProfile([snap("a", packages=("fastapi",)), snap("b", packages=("torch",))]),
        "DSA-50")
    text = render_profile(prof)
    assert "everything declared across all repos (2)" in text
    assert "fastapi, torch" in text


def test_the_most_recent_repos_are_the_ones_shown():
    """Recency decides, because recent work is what a current claim is about."""
    prof = profile_digest(
        FakeProfile([snap("old", months=60.0), snap("new", months=1.0)]), "DSA-50")
    text = render_profile(prof)
    assert text.index("- new") < text.index("- old")
