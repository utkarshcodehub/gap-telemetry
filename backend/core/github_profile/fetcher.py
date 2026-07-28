"""GitHub profile fetcher: username -> repos -> skill evidence."""

from __future__ import annotations

from dataclasses import dataclass

import requests

from core.extraction.extractor import SkillExtractor

API = "https://api.github.com"


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

    for repo in repos:
        if repo.get("fork"):
            continue
        evidence_text = " ".join(filter(None, [
            repo.get("name", "").replace("-", " ").replace("_", " "),
            repo.get("description") or "",
            " ".join(repo.get("topics", [])).replace("-", " "),
            repo.get("language") or "",
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
