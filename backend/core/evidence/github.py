"""
Collect artifact evidence from a GitHub profile (FR-1 .. FR-7).

This is the half of the project that makes "verified" mean anything. The existing
`core/github_profile/fetcher.py` reads each repo's name, description, topics and
README -- all four written by the candidate -- so its "evidence" is the same
self-report as the resume. This module reads what the candidate's *tools*
produced instead.

REQUEST BUDGET (NFR-2: < 150 per analysis). Per repo:

    1  git/trees?recursive=1   entire file listing in ONE call
    1  contributors            authorship share for every contributor at once
   <=2 contents                only manifests the tree actually revealed
    0  languages               NOT fetched -- the repo list already carries the
                               primary `language`, so a per-repo call would cost
                               25 requests for a marginal refinement

    => <= 4 per repo, + 1 for the repo list. 25 repos = 101 requests.

CACHE (NFR-3: 24h TTL). Keyed by URL, on disk. Re-analysing an unchanged profile
costs ~0 requests, which matters because the GitHub limit is 5,000/hour
*shared with every other analysis* and a demo must not be one rate-limit away
from failing.

All HTTP goes through an injectable client so the golden fixtures in
tests/fixtures/github/ exercise the real detection logic with no network.
"""

from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

import requests

from core.evidence.absence import absence_is_evidence
from core.evidence.channels import CHANNELS, Channel, ChannelSpec
from core.evidence.model import SkillEvidence, Tier

API = "https://api.github.com"

#: Repos analysed, most-recently-pushed first. Caps the request budget; a profile
#: with more repos than this is analysed partially and says so (EC-12).
MAX_REPOS = 25
#: Manifests fetched per repo. The tree tells us which exist; we only pay for the
#: most informative few.
MAX_MANIFESTS_PER_REPO = 2
#: Tree entries kept. Vendored directories are excluded first (EC-8), so this is
#: a guard against a pathological repo rather than a normal limit.
MAX_TREE_ENTRIES = 20_000

CACHE_TTL_SECONDS = 24 * 3600

#: Vendored or generated paths. Their contents are someone else's work, so
#: counting them as evidence would credit the candidate for their dependencies
#: (EC-8).
VENDORED = (
    "node_modules/", "vendor/", "venv/", ".venv/", "site-packages/",
    "dist/", "build/", "target/", ".next/", "__pycache__/", "bower_components/",
    "third_party/", "external/",
)

#: Manifests we know how to parse, in descending order of how much they reveal.
MANIFEST_FILES = (
    "package.json", "requirements.txt", "pyproject.toml", "pom.xml",
    "build.gradle", "go.mod", "cargo.toml", "composer.json", "gemfile",
    "pubspec.yaml",
)


class BudgetExceeded(RuntimeError):
    """Raised instead of issuing a request beyond the per-analysis budget."""


@dataclass
class RequestBudget:
    """Hard per-analysis request cap (NFR-2)."""

    limit: int = 150
    spent: int = 0

    def take(self, n: int = 1) -> None:
        if self.spent + n > self.limit:
            raise BudgetExceeded(
                f"GitHub request budget exhausted ({self.spent}/{self.limit}). "
                f"Reduce MAX_REPOS or raise the budget deliberately."
            )
        self.spent += n

    @property
    def remaining(self) -> int:
        return max(0, self.limit - self.spent)


class Client(Protocol):
    def get_json(self, url: str) -> Any: ...
    def get_text(self, url: str) -> str: ...


@dataclass
class GitHubClient:
    """Budgeted, cached HTTP client. Cache hits cost no budget."""

    token: str | None = None
    budget: RequestBudget = field(default_factory=RequestBudget)
    cache_dir: Path | None = None
    #: Set when a supplied token was rejected and we fell back to
    #: unauthenticated access. Surfaced so a dead credential is visible
    #: rather than quietly halving what the analysis can see.
    token_rejected: bool = False
    #: Set once GitHub starts rate-limiting. Every subsequent call this
    #: hour would fail identically, so collection short-circuits.
    rate_limited: bool = False
    #: Transient network failures that were absorbed. Non-empty means the
    #: profile is partial, so absence is not evidence.
    transport_errors: list[str] = field(default_factory=list)
    _partial: bool = False
    _sess: Any = None

    @property
    def partial(self) -> bool:
        """True when something was skipped, so results must be labelled partial."""
        return self._partial

    def _headers(self, raw: bool = False) -> dict[str, str]:
        # The contents endpoint returns a JSON envelope with base64 `content` by
        # default, NOT the file. Parsing that envelope as a manifest silently
        # finds almost nothing -- it looked like every repo declared one
        # dependency. `vnd.github.raw` asks for the file itself.
        h = {"Accept": "application/vnd.github.raw" if raw
             else "application/vnd.github+json",
             "X-GitHub-Api-Version": "2022-11-28"}
        if self.token:
            h["Authorization"] = f"Bearer {self.token}"
        return h

    def _cache_path(self, url: str) -> Path | None:
        if not self.cache_dir:
            return None
        key = re.sub(r"[^A-Za-z0-9]+", "_", url)[-180:]
        return self.cache_dir / f"{key}.json"

    def _cached(self, url: str) -> Any | None:
        p = self._cache_path(url)
        if not p or not p.exists():
            return None
        if time.time() - p.stat().st_mtime > CACHE_TTL_SECONDS:
            return None
        try:
            return json.loads(p.read_text(encoding="utf-8"))["body"]
        except (json.JSONDecodeError, KeyError, OSError):
            return None

    def _store(self, url: str, body: Any) -> None:
        p = self._cache_path(url)
        if not p:
            return
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps({"url": url, "body": body}), encoding="utf-8")

    def _session(self) -> requests.Session:
        """Pooled session with retries.

        A full profile is ~95 sequential requests. Opening a fresh TLS connection
        for each one is both slow and fragile -- a single remote reset killed an
        entire analysis before this existed. Pooling reuses one connection and the
        retry handles the transient resets and 5xx that are normal at this volume.
        Note 403/429 are NOT retried: they mean rate-limited, and hammering a rate
        limit is how you stay rate-limited.
        """
        if self._sess is None:
            from requests.adapters import HTTPAdapter
            from urllib3.util.retry import Retry

            sess = requests.Session()
            retry = Retry(
                total=3, connect=3, read=3,
                backoff_factor=0.6,
                status_forcelist=(500, 502, 503, 504),
                allowed_methods=frozenset({"GET"}),
                raise_on_status=False,
            )
            adapter = HTTPAdapter(max_retries=retry, pool_connections=4,
                                  pool_maxsize=4)
            sess.mount("https://", adapter)
            self._sess = sess
        return self._sess

    def _fetch(self, url: str, *, as_text: bool, raw: bool = False) -> Any:
        hit = self._cached(url)
        if hit is not None:
            return hit
        if self.rate_limited:
            return None      # short-circuit: see the 403 branch below
        self.budget.take()
        try:
            resp = self._session().get(url, headers=self._headers(raw), timeout=30)
        except requests.RequestException as e:
            # Degrade, never crash. One flaky connection must not discard the
            # ~90 successful requests already spent, and must not be mistaken for
            # "this repo has no evidence" (NFR-4).
            self._partial = True
            self.transport_errors.append(f"{type(e).__name__} on {url[-60:]}")
            return None

        if resp.status_code == 401 and self.token:
            # An expired or revoked token must not kill the analysis. GitHub's
            # unauthenticated tier still works, just at 60 req/hr instead of
            # 5,000 -- so drop the credential, record it, and carry on. Silently
            # failing here is how the old fetcher came to report "skipped" for
            # every profile without anyone noticing the token had died.
            self.token = None
            self.token_rejected = True
            resp = requests.get(url, headers=self._headers(raw), timeout=30)

        if resp.status_code == 404:
            self._store(url, None)
            return None
        if resp.status_code in (403, 429):
            # Rate limited. Degrade to partial rather than failing the analysis
            # or, worse, reporting absence as if we had looked (NFR-4).
            #
            # Also STOP: every further call this hour will fail the same way, so
            # continuing would burn the request budget and minutes of wall clock
            # to collect nothing, while producing a result that looks complete
            # because most repos came back "empty" rather than "unavailable".
            self._partial = True
            self.rate_limited = True
            return None
        resp.raise_for_status()
        body = resp.text if as_text else resp.json()
        self._store(url, body)
        return body

    def get_json(self, url: str) -> Any:
        return self._fetch(url, as_text=False)

    def get_text(self, url: str) -> str:
        """Fetch a FILE's contents, not the API's envelope around it."""
        body = self._fetch(url, as_text=True, raw=True)
        if isinstance(body, str):
            return body
        # Defensive: if a cached entry or a proxy handed back the JSON envelope
        # anyway, decode it rather than parsing metadata as a manifest.
        if isinstance(body, dict) and body.get("encoding") == "base64":
            import base64
            try:
                return base64.b64decode(body.get("content") or "").decode(
                    "utf-8", errors="replace")
            except (ValueError, TypeError):
                return ""
        return ""


# ------------------------------------------------------------------ snapshots


@dataclass(frozen=True)
class RepoSnapshot:
    name: str
    primary_language: str | None
    pushed_months_ago: float | None
    tree_paths: tuple[str, ...]
    packages: frozenset[str]
    authorship_share: float | None
    #: True when the tree was retrieved; absence only means something if so.
    tree_retrieved: bool
    manifest_retrieved: bool


@dataclass(frozen=True)
class ProfileEvidence:
    username: str
    repos: tuple[RepoSnapshot, ...]
    #: Set when anything was skipped (rate limit, budget, repo cap). Suppresses
    #: contradiction downstream, because we did not look at everything.
    partial: bool
    requests_spent: int


def _months_ago(iso: str | None, now: float | None = None) -> float | None:
    if not iso:
        return None
    try:
        from datetime import datetime, timezone
        then = datetime.fromisoformat(iso.replace("Z", "+00:00"))
        ref = datetime.fromtimestamp(now, tz=timezone.utc) if now else datetime.now(timezone.utc)
        return max(0.0, (ref - then).days / 30.44)
    except (ValueError, TypeError):
        return None


def _is_vendored(path: str) -> bool:
    low = path.lower()
    return any(v in low for v in VENDORED)


# --------------------------------------------------------- manifest parsers


def parse_package_json(text: str) -> set[str]:
    try:
        d = json.loads(text)
    except json.JSONDecodeError:
        return set()
    out: set[str] = set()
    for key in ("dependencies", "devDependencies", "peerDependencies"):
        out |= {k.lower() for k in (d.get(key) or {})}
    return out


def parse_requirements_txt(text: str) -> set[str]:
    out = set()
    for line in text.splitlines():
        line = line.split("#", 1)[0].strip()
        if not line or line.startswith("-"):
            continue
        name = re.split(r"[\[<>=!~;\s]", line, 1)[0].strip()
        if name:
            out.add(name.lower())
    return out


def parse_pyproject_toml(text: str) -> set[str]:
    # Regex rather than a TOML parser: we only need dependency NAMES, and this
    # avoids depending on parser availability across Python versions.
    out = set()
    for m in re.finditer(r'^\s*"?([A-Za-z0-9][A-Za-z0-9._-]+)"?\s*[=,\]]', text, re.M):
        out.add(m.group(1).lower())
    for m in re.finditer(r'["\']([A-Za-z0-9][A-Za-z0-9._-]+)\s*[<>=~!]', text):
        out.add(m.group(1).lower())
    return out


def parse_go_mod(text: str) -> set[str]:
    out = set()
    for m in re.finditer(r"^\s*([a-z0-9./-]+\.[a-z]{2,}/[^\s]+)\s+v", text, re.M | re.I):
        out.add(m.group(1).lower())
    return out


def parse_cargo_toml(text: str) -> set[str]:
    return parse_pyproject_toml(text)


def parse_pom_xml(text: str) -> set[str]:
    return {m.group(1).lower()
            for m in re.finditer(r"<artifactId>\s*([^<\s]+)\s*</artifactId>", text)}


def parse_build_gradle(text: str) -> set[str]:
    out = set()
    for m in re.finditer(r"""['"]([a-zA-Z0-9._-]+):([a-zA-Z0-9._-]+)(?::|['"])""", text):
        out.add(m.group(2).lower())
    return out


def parse_composer_json(text: str) -> set[str]:
    try:
        d = json.loads(text)
    except json.JSONDecodeError:
        return set()
    out = set()
    for key in ("require", "require-dev"):
        out |= {k.split("/")[-1].lower() for k in (d.get(key) or {})}
    return out


def parse_gemfile(text: str) -> set[str]:
    return {m.group(1).lower() for m in re.finditer(r"""gem\s+['"]([^'"]+)['"]""", text)}


def parse_pubspec_yaml(text: str) -> set[str]:
    return {m.group(1).lower()
            for m in re.finditer(r"^\s{2}([a-z0-9_]+)\s*:", text, re.M)}


PARSERS = {
    "package.json": parse_package_json,
    "requirements.txt": parse_requirements_txt,
    "pyproject.toml": parse_pyproject_toml,
    "go.mod": parse_go_mod,
    "cargo.toml": parse_cargo_toml,
    "pom.xml": parse_pom_xml,
    "build.gradle": parse_build_gradle,
    "composer.json": parse_composer_json,
    "gemfile": parse_gemfile,
    "pubspec.yaml": parse_pubspec_yaml,
}


def parse_manifest(filename: str, text: str) -> set[str]:
    return PARSERS.get(filename.lower(), lambda _: set())(text)


# ------------------------------------------------------------- collection


def collect_profile(
    client: Client,
    username: str,
    *,
    max_repos: int = MAX_REPOS,
    now: float | None = None,
) -> ProfileEvidence:
    """Gather artifact evidence for one GitHub user."""
    repos = client.get_json(f"{API}/users/{username}/repos"
                            f"?per_page=100&sort=pushed&type=owner") or []
    # Forks are excluded: the code is someone else's, so crediting it would be
    # the opposite of verification.
    owned = [r for r in repos if not r.get("fork")]
    partial = len(owned) > max_repos
    snapshots = []
    for repo in owned[:max_repos]:
        if getattr(client, "rate_limited", False):
            # Stop rather than appending empty snapshots: an empty tree is
            # indistinguishable from "this repo has no evidence", and that
            # difference is the whole basis of the contradiction rule.
            partial = True
            break
        snap = _snapshot_repo(client, username, repo, now=now)
        if not snap.tree_retrieved:
            # The repo whose fetch TRIPPED the limit would otherwise be kept with
            # an empty tree, which reads as "no evidence here" rather than "we
            # never saw it". Drop it and stop.
            partial = True
            break
        snapshots.append(snap)

    spent = getattr(getattr(client, "budget", None), "spent", 0)
    client_partial = bool(getattr(client, "partial", False))
    return ProfileEvidence(
        username=username,
        repos=tuple(snapshots),
        partial=partial or client_partial,
        requests_spent=spent,
    )


def _snapshot_repo(client: Client, username: str, repo: dict,
                   *, now: float | None = None) -> RepoSnapshot:
    full = repo.get("full_name") or f"{username}/{repo.get('name')}"
    branch = repo.get("default_branch") or "main"

    tree = client.get_json(f"{API}/repos/{full}/git/trees/{branch}?recursive=1")
    paths: list[str] = []
    tree_retrieved = tree is not None
    if isinstance(tree, dict):
        for entry in (tree.get("tree") or [])[:MAX_TREE_ENTRIES]:
            p = entry.get("path") or ""
            if p and not _is_vendored(p):
                paths.append(p)

    packages: set[str] = set()
    manifest_retrieved = False
    for name in _manifests_in(paths)[:MAX_MANIFESTS_PER_REPO]:
        text = client.get_text(f"{API}/repos/{full}/contents/{name}"
                               f"?ref={branch}")
        if text:
            manifest_retrieved = True
            packages |= parse_manifest(Path(name).name, text)

    share = _authorship_share(client, full, username)

    return RepoSnapshot(
        name=repo.get("name") or full,
        primary_language=repo.get("language"),
        pushed_months_ago=_months_ago(repo.get("pushed_at"), now),
        tree_paths=tuple(paths),
        packages=frozenset(packages),
        authorship_share=share,
        tree_retrieved=tree_retrieved,
        manifest_retrieved=manifest_retrieved,
    )


def _manifests_in(paths: list[str]) -> list[str]:
    """Manifest paths found in the tree, shallowest first (root beats nested)."""
    found = [p for p in paths if Path(p).name.lower() in MANIFEST_FILES]
    return sorted(found, key=lambda p: (p.count("/"), len(p)))


def _authorship_share(client: Client, full: str, username: str) -> float | None:
    """The candidate's share of commits, from one /contributors call.

    None means unknown, which must never be treated as low -- see
    EVIDENCE_MODEL section 8.2 and the contradiction rule.
    """
    data = client.get_json(f"{API}/repos/{full}/contributors?per_page=100")
    if not isinstance(data, list) or not data:
        return None
    total = sum(c.get("contributions") or 0 for c in data)
    if total <= 0:
        return None
    mine = sum(c.get("contributions") or 0 for c in data
               if (c.get("login") or "").lower() == username.lower())
    return mine / total


# -------------------------------------------------------------- detection


def _tier_for_channel(channel: Channel) -> Tier:
    # MANIFEST outranks the rest: a declared dependency is the hardest of the
    # three to fabricate, because the toolchain would break.
    return Tier.DECLARED if channel is Channel.MANIFEST else Tier.PRESENT


def _matches(spec: ChannelSpec, repo: RepoSnapshot) -> set[Channel]:
    hits: set[Channel] = set()

    if spec.languages and repo.primary_language:
        if repo.primary_language.lower() in {l.lower() for l in spec.languages}:
            hits.add(Channel.LANGUAGE)

    if spec.packages and repo.packages:
        wanted = {p.lower() for p in spec.packages}
        if wanted & repo.packages:
            hits.add(Channel.MANIFEST)

    if spec.files or spec.extensions or spec.path_contains:
        lowered = [p.lower() for p in repo.tree_paths]
        names = {Path(p).name for p in lowered}
        if ({f.lower() for f in spec.files} & names
                or any(p.endswith(e.lower()) for e in spec.extensions for p in lowered)
                or any(frag.lower() in p for frag in spec.path_contains for p in lowered)):
            hits.add(Channel.FILE_TREE)

    return hits


def _channel_retrieved_for(spec: ChannelSpec, repo: RepoSnapshot) -> bool:
    """Did THIS repo yield a channel capable of carrying THIS skill's signal?

    Per-repo, not profile-wide: a skill is only checkable in a repo whose relevant
    artifacts we actually read. This is what makes verification_coverage graded
    rather than effectively binary (EVIDENCE_MODEL section 8.5, revised).
    """
    channels = spec.channels
    if Channel.MANIFEST in channels and repo.manifest_retrieved:
        return True
    if Channel.FILE_TREE in channels and repo.tree_retrieved:
        return True
    # The language field arrives with the repo listing, so it is retrieved
    # whenever the repo is in scope at all.
    if Channel.LANGUAGE in channels:
        return True
    return False


def evidence_from_profile(profile: ProfileEvidence) -> list[SkillEvidence]:
    """Turn repo snapshots into one SkillEvidence per mapped skill."""
    in_scope = len(profile.repos)

    out: list[SkillEvidence] = []
    for skill, spec in CHANNELS.items():
        if not spec.verifiable:
            # channel_coverage stays None: the question does not apply, which is
            # different from "we looked and found no way to check".
            out.append(SkillEvidence(skill=skill, verifiable_by_design=False))
            continue

        best: Tier | None = None
        repos_hit = 0
        recency: float | None = None
        shares: list[float] = []

        for repo in profile.repos:
            hits = _matches(spec, repo)
            if not hits:
                continue
            repos_hit += 1
            for ch in hits:
                tier = _tier_for_channel(ch)
                if best is None or tier.value > best.value:
                    best = tier
            if repo.pushed_months_ago is not None:
                recency = (repo.pushed_months_ago if recency is None
                           else min(recency, repo.pushed_months_ago))
            if repo.authorship_share is not None:
                shares.append(repo.authorship_share)

        # Checkability is about what we RETRIEVED, never what we concluded --
        # that is what keeps verification_coverage non-circular (section 8.5).
        # Counted per repo and averaged, so nine failed fetches out of ten show
        # up as 10% coverage rather than as a confident 100%.
        retrieved_in = sum(1 for r in profile.repos
                           if _channel_retrieved_for(spec, r))
        channel_coverage = (retrieved_in / in_scope) if in_scope else 0.0

        # Positive counter-evidence, not inferred from absence alone: the skill
        # is on a deliberately tiny allowlist of cases where the artifact is
        # effectively unavoidable, we read the detecting channel in enough repos,
        # and it still is not there. core/evidence/absence.py explains why almost
        # nothing qualifies -- manifest-only skills in particular cannot, because
        # we sample manifests rather than reading them all.
        counter = absence_is_evidence(
            skill,
            found=best is not None,
            repos_with_channel=retrieved_in,
            channel_coverage=channel_coverage,
        )

        out.append(SkillEvidence(
            skill=skill,
            max_tier=best,
            n_repos=repos_hit,
            repos_with_channel=retrieved_in,
            recency_months=recency,
            authorship_share=max(shares) if shares else None,
            channel_coverage=channel_coverage,
            verifiable_by_design=True,
            counter_evidence=counter,
        ))
    return out
