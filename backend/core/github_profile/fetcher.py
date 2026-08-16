"""GitHub profile fetcher: username -> repos -> skill evidence."""

from __future__ import annotations

from dataclasses import dataclass

import requests

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


def _fetch_readme_text(username: str, repo_name: str, headers: dict, timeout: int) -> str:
    try:
        resp = requests.get(
            f"{API}/repos/{username}/{repo_name}/readme",
            headers={**headers, "Accept": "application/vnd.github.raw"},
            timeout=timeout,
        )
        if resp.status_code == 200:
            return resp.text[:README_MAX_CHARS]
    except requests.RequestException:
        pass
    return ""


def fetch_github_profile(
    username: str,
    extractor: SkillExtractor | None = None,
    token: str | None = None,
    timeout: int = 15,
) -> GitHubProfile:
    extractor = extractor or SkillExtractor()
    headers = {"Accept": "application/vnd.github+json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"

    resp = requests.get(
        f"{API}/users/{username}/repos",
        params={"per_page": 100, "sort": "updated", "type": "owner"},
        headers=headers, timeout=timeout,
    )
    if resp.status_code == 404:
        raise GitHubFetchError(f"GitHub user '{username}' not found")
    if resp.status_code == 403:
        raise GitHubFetchError("GitHub rate limit hit — retry later or pass a token")
    resp.raise_for_status()
    repos = resp.json()

    skill_repo_count: dict[str, int] = {}
    languages: dict[str, int] = {}

    readmes_fetched = 0
    for repo in repos:
        if repo.get("fork"):
            continue
        readme_text = ""
        if readmes_fetched < README_FETCH_LIMIT:
            readme_text = _fetch_readme_text(username, repo.get("name", ""), headers, timeout)
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
