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
GROQ_MODEL = "openai/gpt-oss-120b"
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


SYSTEM_PROMPT = """You are an expert career-focused technical mentor and learning-roadmap architect for Indian engineering students preparing for technical placements.

Your job is to transform a student's skill-gap analysis into a highly practical, role-specific, evidence-driven learning roadmap.

The student is targeting a specific technical role. You must reason about:
1. The skills demanded by that role.
2. The student's existing strengths.
3. The severity of each skill gap.
4. The demand percentage of each skill in relevant job postings.
5. Prerequisites and dependencies between skills.
6. The limited time available to the student.
7. How each skill can be converted into demonstrable practical ability.

IMPORTANT PRINCIPLES:
- Do not produce a generic learning roadmap.
- Tailor every recommendation to the target role and the student's actual gaps.
- Treat demand percentages as evidence of market importance, not as the only ordering criterion.
- Use prerequisite logic when a lower-demand skill is necessary to learn a higher-demand skill.
- Do not re-teach existing strengths unless they are directly required as a prerequisite for a new skill.
- Build on existing strengths whenever possible.
- Prioritize skills that maximize employability within the available timeframe.
- Prefer depth in the most important skills over shallow coverage of many technologies.
- Every action must be concrete, specific, and executable.
- Avoid vague actions such as "learn X", "practice X", "study X", or "watch tutorials" unless accompanied by exactly what the student should learn or build.
- Favor hands-on implementation, debugging, documentation reading, coding exercises, and project work.
- Resources must be free. Do not recommend paid courses, bootcamps, or subscriptions.
- Projects must be realistic enough for a student to build and strong enough to demonstrate the week's learning.
- Projects should progressively increase in complexity across the roadmap.
- Each project should reinforce the skills learned during that week rather than being unrelated.
- The roadmap should move from foundations → implementation → integration → role-specific application → portfolio/interview readiness where appropriate.
- Do not overwhelm the student with unnecessary technologies.
- If multiple technologies solve the same problem, prefer the one most relevant to the target role and job-market demand.
- Make recommendations appropriate for an Indian engineering student preparing for placements, where practical projects, interview readiness, and demonstrable skills matter.
- Be specific about WHAT to learn, WHY it matters, and HOW it should be practiced, but keep the final response within the requested JSON structure.

QUALITY STANDARD:
A strong roadmap should make the student able to answer:
"What exactly should I work on this week, why am I working on it, what should I build, and how does this move me closer to being job-ready for my target role?"

You produce ONLY valid JSON.
Do not output markdown.
Do not output explanations outside the JSON.
Do not wrap the JSON in code fences.
Do not add extra fields that are not requested.
"""

USER_PROMPT_TEMPLATE = """A student targeting the technical role "{role}" wants to become placement-ready.

You have the following skill-gap analysis. Percentages represent the share of relevant job postings that demand the skill.

STUDENT READINESS SCORE:
{readiness}/100

CRITICAL GAPS — close these first:
{critical}

IMPORTANT GAPS:
{important}

EXISTING STRENGTHS — build on these and do not unnecessarily re-teach them:
{strengths}

AVAILABLE LEARNING PERIOD:
{n_weeks} weeks

YOUR TASK:

Create a highly tailored {n_weeks}-week learning roadmap that closes the student's most important skill gaps and increases their readiness for the "{role}" role.

Before deciding the weekly sequence, reason internally about the student's situation using these questions:

1. Which missing skills have the highest market demand?
2. Which skills are foundational prerequisites for other missing skills?
3. Which critical gaps should be addressed immediately?
4. Which existing strengths can accelerate learning or be reused in projects?
5. Which skills are closely related and should be learned together?
6. Which skills are unnecessary or lower priority given the limited number of weeks?
7. What practical evidence should the student produce to demonstrate competency in each important skill?
8. What progression makes sense from foundational knowledge to practical implementation?
9. What would make this roadmap specifically appropriate for "{role}" rather than another technical role?

ROADMAP RULES:

1. PRIORITIZATION
- Prioritize skills using both job-posting demand percentage and prerequisite/dependency logic.
- A lower-demand prerequisite may come before a higher-demand skill when the higher-demand skill cannot be learned effectively without it.
- Critical gaps should generally receive priority over important gaps.
- Do not attempt to cover every listed gap if doing so would make the roadmap shallow.
- Focus on the smallest set of skills that can produce the largest improvement in job readiness.

2. EXISTING STRENGTHS
- Do not spend a week re-learning skills already listed under EXISTING STRENGTHS.
- Use existing strengths as building blocks for new skills.
- If a strength is useful for a project, explicitly leverage it rather than introducing an unnecessary replacement technology.

3. WEEKLY STRUCTURE
Every week MUST contain:
- One clear theme.
- Maximum 2-3 skills.
- Exactly 3-4 concrete actions.
- Exactly ONE buildable project.

The theme should represent the main capability the student is developing that week.

4. CONCRETE ACTIONS
Each action must describe a specific outcome or activity.

Bad:
"Learn Python."

Good:
"Implement file handling, exception handling, modules, and package structure by building a small CLI utility."

Bad:
"Practice SQL."

Good:
"Write SQL queries using JOINs, GROUP BY, subqueries, CTEs, and window functions against a realistic dataset."

Actions should preferably involve:
- implementation,
- coding exercises,
- debugging,
- documentation,
- small experiments,
- architecture/design decisions,
- integration,
- testing,
- or measurable practice.

Avoid generic motivational advice.

5. PROJECT DESIGN
Every weekly project must:
- directly use at least one of that week's target skills;
- be realistically buildable by a student within that week;
- have a clear practical purpose;
- increase in complexity as the roadmap progresses;
- preferably be something the student can later show on GitHub or discuss in an interview.

Do not repeatedly suggest generic projects such as "build a calculator", "build a simple website", or "make a CRUD app" unless they are genuinely relevant to "{role}" and meaningfully demonstrate the target skill.

6. PROGRESSION
The roadmap should have a logical progression.

Where appropriate, follow this pattern:
- Weeks 1-2: prerequisite/foundation gaps
- Middle weeks: core role-specific skills
- Later weeks: integration, advanced application, realistic systems/projects
- Final week(s): consolidation, portfolio-quality work, interview-oriented application

Do NOT force this exact pattern if the student's gaps indicate a better sequence.

7. ROLE SPECIFICITY
Recommendations must reflect "{role}".

For example:
- A backend roadmap should emphasize APIs, databases, backend architecture, authentication, testing, deployment, etc.
- A data/ML roadmap should emphasize data handling, statistics, modeling, evaluation, experimentation, deployment, etc.
- A frontend roadmap should emphasize UI architecture, state management, performance, accessibility, testing, etc.
- A DevOps/cloud roadmap should emphasize Linux, networking, CI/CD, containers, cloud infrastructure, observability, etc.

Do not mix unrelated technologies simply because they are popular.

8. RESOURCE CONSTRAINT
- Assume the student has access to free online documentation, tutorials, open-source repositories, practice platforms, and free tooling.
- Do not recommend paid resources.
- Prefer official documentation and high-quality free resources when mentioning resources.
- Do not make the roadmap dependent on a specific paid platform.

9. REALISM
The student is a placement-oriented engineering student with limited time.

Therefore:
- Avoid unrealistic workloads.
- Do not introduce 5-6 new technologies in one week.
- Do not recommend learning entire ecosystems in a few days.
- Prioritize practical competency over theoretical completeness.
- Prefer learning fewer skills deeply enough to build with and discuss in interviews.

10. TAILORING
The roadmap must clearly reflect the relationship between:
EXISTING STRENGTHS → CURRENT GAPS → TARGET ROLE → WEEKLY SKILLS → PROJECTS.

Do not generate a roadmap that could be given unchanged to any student.

11. SUMMARY
The summary must be 2-3 sentences and should explain:
- the overall strategy,
- the most important priority,
- and how the roadmap uses the student's strengths while closing the highest-value gaps.

12. JSON VALIDITY
Return ONLY the following JSON structure.

Do not add:
- resources
- estimated_hours
- difficulty
- prerequisites
- explanations
- progress_metrics
- interview_questions
- any other fields

Use exactly these fields:

{{
  "summary": "<2-3 sentence strategy overview>",
  "weeks": [
    {{
      "week": 1,
      "theme": "<clear weekly theme>",
      "skills": ["<skill 1>", "<skill 2>"],
      "actions": [
        "<specific concrete action>",
        "<specific concrete action>",
        "<specific concrete action>",
        "<specific concrete action>"
      ],
      "project": "<one practical project directly related to the week's skills>"
    }}
  ]
}}

The number of week objects MUST equal {n_weeks}.
Each week MUST contain:
- exactly one theme,
- 1-3 skills,
- exactly 3-4 actions,
- exactly one project.

Return ONLY valid JSON with no markdown or additional text.
"""


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
