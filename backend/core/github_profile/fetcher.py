"""GitHub profile fetcher: username -> repos -> skill evidence."""

from __future__ import annotations

from dataclasses import dataclass

from pathlib import Path

import requests

from core import http_cache
from core.extraction.extractor import SkillExtractor

API = "https://api.github.com"

# Repo name/description/topics/language alone are often empty on personal
# projects (nobody fills in the "About" box) and yield zero extracted
# skills even for substantial repos. README content is far denser signal,
# but fetching one per repo is a separate API call each — cap it so a
# single analysis can't blow through the unauthenticated 60 req/hr limit
# (or take forever even with a token) on someone with 100 repos.
README_FETCH_LIMIT = 20
README_MAX_CHARS = 4000


@dataclass(frozen=True)
class GitHubProfile:
    username: str
    repo_count: int
    skills: dict[str, int]
    languages: dict[str, int]

    @property
    def skill_names(self) -> set[str]:
        return set(self.skills)


class GitHubFetchError(Exception):
    pass


def _fetch_readme_text(username: str, repo_name: str, headers: dict, timeout: int,
                       cache_dir: Path | None = None) -> str:
    try:
        status, body = http_cache.get_text(
            f"{API}/repos/{username}/{repo_name}/readme",
            headers={**headers, "Accept": "application/vnd.github.raw"},
            timeout=timeout, cache_dir=cache_dir,
        )
        if status == 200:
            return body[:README_MAX_CHARS]
    except requests.RequestException:
        pass
    return ""


def fetch_github_profile(
    username: str,
    extractor: SkillExtractor | None = None,
    token: str | None = None,
    timeout: int = 15,
    cache_dir: Path | None = None,
) -> GitHubProfile:
    """Legacy README-keyword profile fetch.

    `cache_dir` is strongly recommended: without it this re-fetches a repo list
    plus up to README_FETCH_LIMIT READMEs on every call, measured at ~15s and ~24
    requests against a rate limit shared by every analysis. See core/http_cache.
    """
    extractor = extractor or SkillExtractor()
    headers = {"Accept": "application/vnd.github+json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"

    status, repos_body = http_cache.get_json(
        f"{API}/users/{username}/repos",
        params={"per_page": 100, "sort": "updated", "type": "owner"},
        headers=headers, timeout=timeout, cache_dir=cache_dir,
    )

    if status == 404:
        raise GitHubFetchError(f"GitHub user '{username}' not found")
    if status == 403:
        raise GitHubFetchError("GitHub rate limit hit — retry later or pass a token")
    if status == 401:
        raise GitHubFetchError("GitHub rejected the token (401 Bad credentials)")
    if status != 200 or repos_body is None:
        raise GitHubFetchError(f"GitHub returned HTTP {status}")
    repos = repos_body

    skill_repo_count: dict[str, int] = {}
    languages: dict[str, int] = {}

    readmes_fetched = 0
    for repo in repos:
        if repo.get("fork"):
            continue
        readme_text = ""
        if readmes_fetched < README_FETCH_LIMIT:
            readme_text = _fetch_readme_text(username, repo.get("name", ""), headers,
                                             timeout, cache_dir)
            readmes_fetched += 1
        evidence_text = " ".join(filter(None, [
            repo.get("name", "").replace("-", " ").replace("_", " "),
            repo.get("description") or "",
            " ".join(repo.get("topics", [])).replace("-", " "),
            repo.get("language") or "",
            readme_text,
        ]))
        lang = repo.get("language")
        if lang:
            languages[lang] = languages.get(lang, 0) + 1
        for name in {s.canonical for s in extractor.extract(evidence_text)}:
            skill_repo_count[name] = skill_repo_count.get(name, 0) + 1

    return GitHubProfile(
        username=username,
        repo_count=len([r for r in repos if not r.get("fork")]),
        skills=dict(sorted(skill_repo_count.items(), key=lambda x: -x[1])),
        languages=dict(sorted(languages.items(), key=lambda x: -x[1])),
    )
