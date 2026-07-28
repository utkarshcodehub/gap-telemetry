"""Roadmap generation: GapReport -> week-by-week learning plan.
Two engines: Groq LLM (personalized) and template (deterministic fallback,
guarantees the product never dies from a missing/expired API key)."""

from __future__ import annotations

import json
import os
import re
from dataclasses import asdict, dataclass

import requests

from core.gap.scorer import GapReport

GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"
GROQ_MODEL = "llama-3.3-70b-versatile"
_FENCE_RE = re.compile(r"^```(?:json)?\s*|\s*```$", re.MULTILINE)


@dataclass(frozen=True)
class RoadmapWeek:
    week: int
    theme: str
    skills: list[str]
    actions: list[str]
    project: str


@dataclass(frozen=True)
class Roadmap:
    role: str
    weeks: list[RoadmapWeek]
    summary: str
    engine: str

    def to_dict(self) -> dict:
        return asdict(self)


SYSTEM_PROMPT = """You are a career-focused technical mentor for Indian \
engineering students preparing for placements. You produce ONLY valid JSON, \
no markdown, no commentary."""

USER_PROMPT_TEMPLATE = """A student targeting the role "{role}" has this \
skill-gap analysis (percentages = share of job postings demanding the skill):

READINESS SCORE: {readiness}/100
CRITICAL GAPS (close these first): {critical}
IMPORTANT GAPS: {important}
EXISTING STRENGTHS (build on these, do not re-teach): {strengths}

Create a {n_weeks}-week learning roadmap. Rules:
- Order skills by demand percentage AND prerequisite logic.
- Each week: one theme, 2-3 skills max, 3-4 concrete actions, ONE buildable project.
- Leverage existing strengths.
- Actions must be free-resource oriented — no paid courses.

Respond with ONLY this JSON structure:
{{"summary": "<2-3 sentence strategy overview>",
  "weeks": [{{"week": 1, "theme": "...", "skills": ["..."],
             "actions": ["..."], "project": "..."}}]}}"""


class GroqRoadmapEngine:
    def __init__(self, api_key: str | None = None, timeout: int = 45):
        self.api_key = api_key or os.environ.get("GROQ_API_KEY", "")
        self.timeout = timeout

    @property
    def available(self) -> bool:
        return bool(self.api_key)

    def generate(self, report: GapReport, n_weeks: int = 6) -> Roadmap:
        critical = [f"{g.canonical} ({g.demand_pct}%)" for g in report.gaps if g.tier == "critical"]
        important = [f"{g.canonical} ({g.demand_pct}%)" for g in report.gaps if g.tier == "important"]
        strengths = [f"{s.canonical} ({s.demand_pct}%, {s.evidence})" for s in report.strengths]

        prompt = USER_PROMPT_TEMPLATE.format(
            role=report.role, readiness=report.readiness_score,
            critical=", ".join(critical) or "none",
            important=", ".join(important) or "none",
            strengths=", ".join(strengths) or "none", n_weeks=n_weeks,
        )
        resp = requests.post(
            GROQ_URL,
            headers={"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"},
            json={"model": GROQ_MODEL,
                  "messages": [{"role": "system", "content": SYSTEM_PROMPT},
                               {"role": "user", "content": prompt}],
                  "temperature": 0.4, "max_tokens": 2000,
                  "response_format": {"type": "json_object"}},
            timeout=self.timeout,
        )
        resp.raise_for_status()
        raw = resp.json()["choices"][0]["message"]["content"]
        data = json.loads(_FENCE_RE.sub("", raw).strip())
        weeks = [RoadmapWeek(week=int(w["week"]), theme=str(w["theme"]),
                              skills=[str(s) for s in w["skills"]],
                              actions=[str(a) for a in w["actions"]],
                              project=str(w.get("project", "")))
                 for w in data["weeks"]]
        if not weeks:
            raise ValueError("LLM returned zero weeks")
        return Roadmap(role=report.role, weeks=weeks, summary=str(data.get("summary", "")), engine="groq")


class TemplateRoadmapEngine:
    ACTION_TEMPLATES = [
        "Read the official {skill} getting-started guide and take notes",
        "Complete one hands-on {skill} tutorial and push the code to GitHub",
        "Solve 3-5 small exercises using {skill} (Kaggle/docs examples)",
    ]

    def generate(self, report: GapReport, n_weeks: int = 6) -> Roadmap:
        ordered = list(report.gaps)
        weeks: list[RoadmapWeek] = []
        per_week = 2
        for i in range(min(n_weeks, max(1, (len(ordered) + 1) // per_week))):
            chunk = ordered[i * per_week:(i + 1) * per_week]
            if not chunk:
                break
            skills = [g.canonical for g in chunk]
            actions = [t.format(skill=skills[0]) for t in self.ACTION_TEMPLATES]
            weeks.append(RoadmapWeek(
                week=i + 1, theme=f"Close the {' + '.join(skills)} gap",
                skills=skills, actions=actions,
                project=f"Build a mini-project combining {skills[0]} with an existing strength "
                        f"({report.strengths[0].canonical if report.strengths else 'Python'})",
            ))
        return Roadmap(role=report.role, weeks=weeks,
                       summary=f"Readiness {report.readiness_score}/100. Plan closes {len(ordered)} gaps in demand order.",
                       engine="template")


def generate_roadmap(report: GapReport, n_weeks: int = 6, api_key: str | None = None) -> Roadmap:
    groq = GroqRoadmapEngine(api_key=api_key)
    if groq.available:
        try:
            return groq.generate(report, n_weeks)
        except Exception:
            pass
    return TemplateRoadmapEngine().generate(report, n_weeks)
