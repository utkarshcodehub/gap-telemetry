"""
Tests for GitHub artifact collection (core/evidence/github.py).

Runs entirely against golden fixtures in tests/fixtures/github/ -- no network, no
token, no rate limit. The fixtures are shaped exactly like the real API responses
and chosen to exercise each channel plus the cases that are easy to get wrong:
a fork, vendored directories, and a repo where the candidate is a minority author.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from core.evidence.channels import CHANNELS, validate_against_taxonomy
from core.evidence.github import (
    MAX_MANIFESTS_PER_REPO,
    BudgetExceeded,
    RequestBudget,
    collect_profile,
    evidence_from_profile,
    parse_build_gradle,
    parse_package_json,
    parse_pom_xml,
    parse_pyproject_toml,
    parse_requirements_txt,
)
from core.evidence.model import Tier

FIX = Path(__file__).parent / "fixtures" / "github"
#: Fixed clock so recency assertions do not rot. Fixtures are dated relative to
#: late 2026.
NOW = 1790000000.0   # ~2026-09-21


class FixtureClient:
    """Serves the golden fixtures, counting calls like the real client."""

    def __init__(self, budget: RequestBudget | None = None):
        self.budget = budget or RequestBudget()
        self.partial = False
        self.urls: list[str] = []

    def _resolve(self, url: str) -> Path | None:
        self.urls.append(url)
        if "/repos?" in url and "/users/" in url:
            return FIX / "repos.json"
        m = re.search(r"/repos/[^/]+/([^/]+)/git/trees/", url)
        if m:
            return FIX / f"tree_{m.group(1)}.json"
        m = re.search(r"/repos/[^/]+/([^/]+)/contributors", url)
        if m:
            return FIX / f"contributors_{m.group(1)}.json"
        m = re.search(r"/repos/[^/]+/([^/]+)/contents/(.+?)(?:\?|$)", url)
        if m:
            repo, path = m.group(1), Path(m.group(2)).name
            return FIX / f"manifest_{repo}_{path}"
        return None

    def get_json(self, url: str):
        p = self._resolve(url)
        self.budget.take()
        if p is None or not p.exists():
            return None
        return json.loads(p.read_text(encoding="utf-8"))

    def get_text(self, url: str) -> str:
        p = self._resolve(url)
        self.budget.take()
        return p.read_text(encoding="utf-8") if p and p.exists() else ""


@pytest.fixture
def profile():
    return collect_profile(FixtureClient(), "testuser", now=NOW)


# ------------------------------------------------------------- collection

def test_forks_are_excluded(profile):
    """A fork is someone else's code; crediting it inverts verification."""
    names = {r.name for r in profile.repos}
    assert names == {"api-service", "dashboard"}
    assert "someone-elses-lib" not in names


def test_vendored_paths_are_not_evidence(profile):
    """node_modules/react would otherwise make every JS project a React expert,
    and venv/.../flask would credit the candidate for their dependencies (EC-8)."""
    api = next(r for r in profile.repos if r.name == "api-service")
    assert not any("node_modules" in p for p in api.tree_paths)
    assert not any("venv/" in p for p in api.tree_paths)

    ev = {e.skill: e for e in evidence_from_profile(profile)}
    assert ev["Flask"].max_tier is None, "Flask only appeared inside venv/"


def test_manifests_are_parsed_into_packages(profile):
    api = next(r for r in profile.repos if r.name == "api-service")
    assert {"fastapi", "psycopg2-binary", "pytest", "boto3"} <= api.packages
    dash = next(r for r in profile.repos if r.name == "dashboard")
    assert {"react", "redux", "tailwindcss", "vitest"} <= dash.packages


def test_authorship_share_comes_from_contributions(profile):
    api = next(r for r in profile.repos if r.name == "api-service")
    assert api.authorship_share == pytest.approx(1.0), "sole author"
    dash = next(r for r in profile.repos if r.name == "dashboard")
    assert dash.authorship_share == pytest.approx(0.2), "20 of 100 commits"


def test_recency_is_measured_per_repo(profile):
    api = next(r for r in profile.repos if r.name == "api-service")
    dash = next(r for r in profile.repos if r.name == "dashboard")
    assert api.pushed_months_ago < 3, "pushed days before the fixed clock"
    assert dash.pushed_months_ago > 18, "pushed in early 2024"


# ---------------------------------------------------------------- budget

def test_request_budget_is_respected():
    budget = RequestBudget(limit=150)
    collect_profile(FixtureClient(budget), "testuser", now=NOW)
    # 1 repo list + per repo: 1 tree + <=2 manifests + 1 contributors.
    assert budget.spent <= 1 + 2 * (2 + MAX_MANIFESTS_PER_REPO)
    assert budget.spent < 150, "NFR-2: well inside the per-analysis cap"


def test_budget_refuses_rather_than_overspending():
    budget = RequestBudget(limit=2)
    with pytest.raises(BudgetExceeded):
        collect_profile(FixtureClient(budget), "testuser", now=NOW)


def test_a_profile_larger_than_the_repo_cap_is_marked_partial():
    """Partial results must say so: absence we did not look for is not evidence."""
    client = FixtureClient()
    p = collect_profile(client, "testuser", max_repos=1, now=NOW)
    assert p.partial is True
    assert len(p.repos) == 1


def test_a_profile_within_the_cap_is_not_partial(profile):
    assert profile.partial is False


# -------------------------------------------------------------- detection

def test_file_tree_evidence_reaches_e2(profile):
    ev = {e.skill: e for e in evidence_from_profile(profile)}
    assert ev["Docker"].max_tier is Tier.PRESENT, "Dockerfile in the tree"
    assert ev["CI/CD"].max_tier is Tier.PRESENT, ".github/workflows/"
    assert ev["Terraform"].max_tier is Tier.PRESENT, "terraform/main.tf"


def test_manifest_evidence_reaches_e3_and_outranks_file_tree(profile):
    """A declared dependency is harder to fake than a filename: the toolchain
    would break. That ordering is the premise the whole model rests on."""
    ev = {e.skill: e for e in evidence_from_profile(profile)}
    assert ev["FastAPI"].max_tier is Tier.DECLARED
    assert ev["PostgreSQL"].max_tier is Tier.DECLARED
    assert ev["React"].max_tier is Tier.DECLARED
    # Unit Testing hits BOTH tests/ (file tree) and pytest (manifest) -> E3 wins.
    assert ev["Unit Testing"].max_tier is Tier.DECLARED


def test_language_statistics_are_used(profile):
    ev = {e.skill: e for e in evidence_from_profile(profile)}
    assert ev["Python"].max_tier is Tier.PRESENT
    assert ev["TypeScript"].max_tier is Tier.PRESENT


def test_a_skill_with_no_artifact_gets_no_tier(profile):
    ev = {e.skill: e for e in evidence_from_profile(profile)}
    assert ev["Kubernetes"].max_tier is None
    assert ev["Rust"].max_tier is None


def test_breadth_is_counted_across_repos(profile):
    ev = {e.skill: e for e in evidence_from_profile(profile)}
    # Unit Testing is evidenced in BOTH repos, by different channels: pytest plus
    # tests/ in api-service, vitest in dashboard. Breadth must aggregate across
    # repos and across channels, since that is what the repo-count bonus rewards.
    assert ev["Unit Testing"].n_repos == 2
    # Docker only exists in api-service.
    assert ev["Docker"].n_repos == 1
    # Absent skills count zero repos, not None.
    assert ev["Kubernetes"].n_repos == 0


def test_recency_takes_the_most_recent_evidencing_repo(profile):
    """A skill used recently in one repo is not stale because another repo is."""
    ev = {e.skill: e for e in evidence_from_profile(profile)}
    # api-service (recent) and dashboard (early 2024) both evidence Unit Testing.
    assert ev["Unit Testing"].recency_months < 3, "takes the fresher of the two"
    # React only exists in the stale repo.
    assert ev["React"].recency_months > 18


def test_authorship_takes_the_strongest_evidencing_repo(profile):
    """Minority authorship in one repo must not drag down a skill the candidate
    demonstrably owns elsewhere -- that would punish collaboration."""
    ev = {e.skill: e for e in evidence_from_profile(profile)}
    assert ev["Unit Testing"].authorship_share == pytest.approx(1.0)
    # React exists only in the repo where they wrote 20% of the commits.
    assert ev["React"].authorship_share == pytest.approx(0.2)


def test_not_verifiable_by_design_skills_are_marked_never_scored(profile):
    ev = {e.skill: e for e in evidence_from_profile(profile)}
    for skill in ("System Design", "REST API", "Microservices", "Agile", "Linux"):
        assert ev[skill].verifiable_by_design is False, skill
        assert ev[skill].max_tier is None, skill


def test_channels_retrieved_reflects_what_was_fetched_not_what_was_found(profile):
    """Section 8.5: coverage must depend on retrieval, never on the verdict."""
    ev = {e.skill: e for e in evidence_from_profile(profile)}
    # Kubernetes was NOT found, but its channels (file tree, manifest) WERE
    # retrieved -- so it is checkable, and legitimately answerable as absent.
    assert ev["Kubernetes"].max_tier is None
    assert ev["Kubernetes"].channels_retrieved is True
    # A non-verifiable skill is never checkable.
    assert ev["System Design"].channels_retrieved is False


def test_every_taxonomy_skill_yields_an_evidence_record(profile):
    ev = evidence_from_profile(profile)
    assert len(ev) == len(CHANNELS)
    assert len({e.skill for e in ev}) == len(CHANNELS)


def test_channel_map_covers_the_whole_taxonomy():
    """The guard that stops Member C's induced taxonomy silently losing
    verifiability for its new skills."""
    tax_path = Path(__file__).resolve().parents[1] / "core" / "taxonomy" / "skills_taxonomy.json"
    data = json.loads(tax_path.read_text(encoding="utf-8"))
    items = data if isinstance(data, list) else data.get("skills", data)
    validate_against_taxonomy({s["canonical"] for s in items})


# ------------------------------------------------------- manifest parsers

def test_requirements_txt_handles_pins_comments_and_includes():
    pkgs = parse_requirements_txt(
        "fastapi==0.110.0\n# comment\nnumpy>=1.2 ; python_version>'3.9'\n"
        "-r dev.txt\nrequests[security]\n\n")
    assert pkgs == {"fastapi", "numpy", "requests"}


def test_package_json_includes_dev_dependencies():
    pkgs = parse_package_json(json.dumps(
        {"dependencies": {"React": "^18"}, "devDependencies": {"jest": "^29"}}))
    assert pkgs == {"react", "jest"}


def test_pyproject_metadata_is_not_mistaken_for_dependencies():
    """What the cohort measurement found. The old regex scraped every
    `key = value` line, so `name`, `version` and `description` arrived looking
    like packages -- 14 such pseudo-packages among the 60 most frequent
    "unrecognised" names, inflating the denominator of the coverage metric."""
    pkgs = parse_pyproject_toml("""
[project]
name = "gap-telemetry"
version = "0.2.0"
description = "a thing"
requires-python = ">=3.11"
dependencies = ["fastapi>=0.110", "pydantic", "httpx[http2]==0.27"]

[project.optional-dependencies]
dev = ["pytest"]

[build-system]
requires = ["setuptools"]
build-backend = "setuptools.build_meta"
""")
    assert pkgs == {"fastapi", "pydantic", "httpx", "pytest"}, (
        "build-system requires is excluded too: a build backend is the toolchain, "
        "not a declared dependency of the project")


def test_cargo_metadata_is_not_mistaken_for_dependencies():
    """Cargo.toml goes through the same parser, and its profile tables were the
    worst offenders: `edition`, `codegen-units`, `lto`, `harness`."""
    pkgs = parse_pyproject_toml("""
[package]
name = "solver"
version = "0.1.0"
edition = "2021"
repository = "https://example.invalid/solver"

[dependencies]
serde = { version = "1", features = ["derive"] }
clap = "4"

[dev-dependencies]
criterion = "0.5"

[profile.release]
codegen-units = 1
lto = true
panic = "abort"

[[bench]]
harness = false
""")
    assert pkgs == {"serde", "clap", "criterion"}


def test_poetry_dependencies_are_found_and_the_python_pin_is_not_one():
    pkgs = parse_pyproject_toml("""
[tool.poetry.dependencies]
python = "^3.11"
django = "^5.0"

[tool.poetry.group.dev.dependencies]
black = "^24.0"
""")
    assert pkgs == {"django", "black"}, "a language version pin is not a dependency"


def test_unparseable_toml_falls_back_rather_than_losing_the_file():
    """Degrade, never drop. A truncated manifest should still yield what it can,
    noise included -- the alternative is reading a real dependency set as empty,
    which is exactly the absence the contradiction rule must never invent."""
    pkgs = parse_pyproject_toml('[project]\ndependencies = ["fastapi>=0.1"\n')
    assert "fastapi" in pkgs


def test_composer_platform_requirements_are_not_packages():
    """`php` arrived as a "package" declared in three repos. composer keeps the
    runtime constraint in the same table as real dependencies."""
    from core.evidence.github import parse_composer_json
    pkgs = parse_composer_json("""
    {"require": {"php": "^8.1", "ext-mbstring": "*", "laravel/framework": "^11.0"},
     "require-dev": {"phpunit/phpunit": "^11.0"}}
    """)
    assert pkgs == {"framework", "phpunit"}


def test_malformed_manifests_return_nothing_rather_than_raising():
    assert parse_package_json("{not json") == set()
    assert parse_pom_xml("") == set()


def test_pom_xml_and_gradle_extract_artifact_names():
    assert "spring-boot-starter-web" in parse_pom_xml(
        "<dependency><artifactId>spring-boot-starter-web</artifactId></dependency>")
    assert "junit-jupiter" in parse_build_gradle(
        "testImplementation 'org.junit.jupiter:junit-jupiter:5.10.0'")


# ------------------------------------------------------- degradation (NFR-4)

class RateLimitedClient(FixtureClient):
    """Serves the repo list, then rate-limits like GitHub does."""

    def __init__(self, allow: int = 1):
        super().__init__()
        self.allow = allow
        self.rate_limited = False

    def get_json(self, url: str):
        if self.rate_limited:
            return None
        if len(self.urls) >= self.allow:
            self.rate_limited = True
            self.partial = True
            return None
        return super().get_json(url)


def test_rate_limiting_stops_collection_instead_of_faking_empty_repos():
    """The distinction that matters most for the contradiction rule.

    An empty tree is indistinguishable from "this repo has no evidence". If a
    rate-limited fetch produced empty snapshots, absence we never looked for
    would read exactly like absence we verified -- and absence is what
    CONTRADICTED is built on.
    """
    client = RateLimitedClient(allow=1)
    p = collect_profile(client, "testuser", now=NOW)
    assert p.partial is True
    assert p.repos == (), "no snapshot is better than an empty one"


def test_rate_limited_client_stops_spending_budget():
    """Every further call this hour fails identically, so continuing would burn
    the budget and wall clock to collect nothing."""
    client = RateLimitedClient(allow=1)
    collect_profile(client, "testuser", now=NOW)
    before = client.budget.spent
    client.get_json("https://api.github.com/anything")
    assert client.budget.spent == before, "short-circuited, no budget spent"


# ------------------------------------------------- empty repositories (409)

class EmptyRepoClient(FixtureClient):
    """Serves the fixtures, but reports one repo as having no commits.

    GitHub answers 409 Conflict for a repository with no commits. The real client
    records that URL as a definitive miss; this reproduces that contract without
    the network.
    """

    def __init__(self, empty_repo: str):
        super().__init__()
        self.empty_repo = empty_repo
        self.definitive_misses: set[str] = set()

    def get_json(self, url: str):
        if f"/{self.empty_repo}/git/trees/" in url:
            self.urls.append(url)
            self.budget.take()
            self.definitive_misses.add(url)
            return None
        return super().get_json(url)


def _repo_names() -> list[str]:
    repos = json.loads((FIX / "repos.json").read_text(encoding="utf-8"))
    return [r["name"] for r in repos if not r.get("fork")]


def test_an_empty_repo_is_skipped_without_losing_the_rest_of_the_profile():
    """The defect the cohort measurement exposed, and the costliest kind.

    A 409 used to escape as an HTTPError, so a candidate who had once created a
    repo and never pushed to it lost EVERY verification they had -- five of
    eighteen sampled profiles collected nothing for this reason. An empty repo is
    one of the most common things on GitHub.
    """
    first = _repo_names()[0]
    client = EmptyRepoClient(first)
    p = collect_profile(client, "testuser", now=NOW)

    assert first not in {r.name for r in p.repos}, "the empty repo is skipped"
    assert len(p.repos) == len(_repo_names()) - 1, "every other repo still collected"
    assert p.partial is False, (
        "nothing went wrong, so the profile is complete -- marking it partial "
        "would suppress CONTRADICTED for a candidate we fully examined")


def test_an_empty_repo_costs_no_contributors_request():
    """No commits means no contributors to ask about."""
    client = EmptyRepoClient(_repo_names()[0])
    collect_profile(client, "testuser", now=NOW)
    assert not any(f"/{client.empty_repo}/contributors" in u for u in client.urls)


def test_a_failed_tree_fetch_still_stops_collection():
    """The counterpart. 'Nothing there' is a fact; 'we could not look' is not, and
    only the second one may truncate a profile."""
    class FailingClient(FixtureClient):
        def get_json(self, url: str):
            if "/git/trees/" in url:
                self.urls.append(url)
                self.budget.take()
                return None          # no definitive_misses: an unexplained miss
            return super().get_json(url)

    p = collect_profile(FailingClient(), "testuser", now=NOW)
    assert p.repos == ()
    assert p.partial is True


class _Resp:
    def __init__(self, status: int):
        self.status_code = status
        self.text = ""

    def json(self):
        return {}

    def raise_for_status(self):
        raise AssertionError(f"{self.status_code} should have been handled")


def test_the_real_client_treats_409_as_an_answer_not_a_failure():
    from core.evidence.github import GitHubClient

    client = GitHubClient(budget=RequestBudget(limit=5))
    client._sess = type("S", (), {"get": lambda self, url, **kw: _Resp(409)})()

    assert client.get_json("https://api.github.com/x/git/trees/main") is None
    assert "https://api.github.com/x/git/trees/main" in client.definitive_misses
    assert client.partial is False, "an empty repo does not make a profile partial"
    assert client.rate_limited is False
