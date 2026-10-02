"""
Canonical role vocabulary, and mappers from each source's own role field into it.

Why this exists. `postings.role_query` is NOT NULL because the original Naukri
scraper searched *by role*, so the search term was the role. Bulk datasets have
no search term -- they have a free-text job title -- so the role has to be
derived. Every source therefore maps into ONE canonical vocabulary, otherwise
demand figures from different sources aren't comparable:

    Naukri CC0 / LinkedIn  ->  map_title(job title)
    JSearch                ->  the search query (already a role; map_title
                               still normalises it)

Two design rules, both deliberate:

1. ORDERED RULES, FIRST MATCH WINS. Order encodes specificity. "Full Stack Java
   Developer" carries both a full-stack and a backend signal, and full stack is
   the more specific claim, so it is evaluated first. Likewise an explicit ML
   role name before data-* ("ML Engineer - Data Pipelines" is an ML role, while
   "ML Data Engineer" is a data engineer -- 'ML' there is only a modifier on the
   head noun), and data engineer before data analyst
   ("Data Engineer: Big Data").

2. AN UNMAPPABLE TITLE IS REJECTED, NEVER GUESSED. `map_title` returns None for
   "Software Engineer", "Associate", "Job Description". Those titles genuinely
   do not state a specialism, and forcing them into `backend developer` to
   recover volume would corrupt every demand percentage computed afterwards.
   Measured on the Naukri CC0 corpus, rejection discards ~83% of rows -- that
   is the honest cost and it is preferred to a fabricated signal.

EXCLUDE runs before any role rule: it rejects non-engineering job families
outright, so "Data Science Trainer" is a teaching vacancy rather than an ML one
and "Technical Sales Engineer" is a sales job. Each pattern there is narrower
than it looks on purpose -- bare `admin` would have rejected "Azure Admin",
bare `training` would have rejected "Model Training Engineer", and bare
`production` would have rejected "Production Support Engineer".
"""

from __future__ import annotations

import re

#: The canonical role vocabulary. PROVISIONAL -- not locked. The Naukri CC0
#: corpus is too small to populate all of these (only `backend developer`
#: clears a 150-posting floor), so the set is confirmed once live JSearch
#: volume lands. See docs/PLAN.md lane B.
CANONICAL_ROLES: tuple[str, ...] = (
    "backend developer",
    "frontend developer",
    "full stack developer",
    "data analyst",
    "data engineer",
    "ai ml engineer",
    "devops engineer",
    "qa engineer",
)

#: Minimum postings before a role's demand figures are trustworthy enough to
#: offer. Document frequency over fewer documents than this has an interval too
#: wide to support critical/nice-to-have tiering.
MIN_POSTINGS_PER_ROLE = 150

_EXCLUDE = [
    # teaching / writing / content
    r"\bwriter\b", r"\bfaculty\b", r"\bteacher\b", r"\btrainer\b", r"\btutor\b",
    r"\blecturer\b", r"\bprofessor\b", r"\bcontent (writer|developer|creator)\b",
    r"\bcopywriter\b", r"\btraining (manager|coordinator|institute|executive)\b",
    # recruiting / sales / admin / finance / ops
    r"\brecruit", r"\btalent acquisition\b", r"\bsales\b", r"\bmarketing\b",
    r"\bbusiness development\b", r"\bhr\b", r"\bhuman resource",
    r"\baccount(s|ant)\b", r"\bfinance\b", r"\baudit", r"\bpayroll\b",
    r"\breceptionist\b", r"\b(office|back ?office) admin",
    r"\badmin (executive|assistant|officer)\b", r"\btele ?caller\b",
    r"\bcustomer (care|support|service)\b", r"\bvoice\b", r"\bbpo\b",
    r"\bback office\b",
    # non-software engineering / medical
    r"\b5g\b", r"\btelecom\b", r"\bhardware\b", r"\bcivil\b", r"\bmechanical\b",
    r"\belectrical\b", r"\bnurse\b", r"\bdoctor\b", r"\bmedical\b", r"\bpharma",
    r"\bsite engineer", r"\bmanufactur",
    r"\bproduction (operator|supervisor|in ?charge|manager)\b",
]

# Matching runs in two tiers, and the split matters.
#
# TIER 1 -- the title NAMES the role. An explicit statement always beats an
# inference from technology, because many technologies are stack-agnostic. Real
# example that forced this design: "Hiring: Backend Developer - Nestjs &
# Typescript" was classified FRONTEND, because a single-tier rule list reached
# `typescript` (a frontend pattern) before `back end`. TypeScript is written on
# both sides of the stack; "Backend Developer" is not ambiguous at all.
#
# TIER 2 -- no role named, so infer from technology. Only consulted when tier 1
# is silent. Specific server-side frameworks (NestJS, Spring, Django) come
# before bare stack-agnostic languages, for the same reason.
_RULES_TIER1: list[tuple[str, list[str]]] = [
    # Full stack first: its titles also contain backend/frontend words.
    ("full stack developer", [
        r"full[\s\-_]?stack", r"\bmern\b", r"\bmean stack\b",
    ]),
    # An explicit ML role name wins. Note this does NOT catch 'ML' used as a
    # mere modifier: "ML Data Engineer" falls through to data engineer below,
    # because the head noun is 'Data Engineer' and 'ML' only qualifies it.
    ("ai ml engineer", [
        r"machine learning", r"\bml engineer", r"\bai\s*/\s*ml\b",
        r"deep learning", r"data scientist", r"data science", r"\bnlp\b",
        r"computer vision", r"artificial intelligence",
    ]),
    # Data engineer before data analyst: "Data Engineer: Big Data".
    ("data engineer", [r"data engineer", r"data platform engineer"]),
    ("data analyst", [
        r"data analyst", r"business intelligence", r"reporting analyst",
        r"\bbi (developer|analyst|consultant)\b",
    ]),
    ("qa engineer", [
        r"\bqa\b", r"quality assurance", r"\bsdet\b", r"\btester\b",
        r"test (engineer|lead|specialist|analyst|automation)",
        r"automation test", r"\btesting (engineer|lead|specialist)\b",
    ]),
    ("devops engineer", [
        r"\bdevops\b", r"\bsre\b", r"site reliability", r"cloud engineer",
        r"infrastructure engineer", r"platform engineer",
        r"build (and |& )?release engineer",
    ]),
    ("backend developer", [
        r"back[\s\-_]?end", r"\bapi (developer|engineer)\b",
        r"server[\s\-_]?side",
    ]),
    ("frontend developer", [
        r"front[\s\-_]?end", r"\bui (developer|engineer)\b", r"\bui\s*/\s*ux\b",
        r"\bweb (developer|designer)\b",
    ]),
]

_RULES_TIER2: list[tuple[str, list[str]]] = [
    ("ai ml engineer", [r"\btensorflow\b", r"\bpytorch\b", r"\bscikit",
                        r"\bllm[s]?\b", r"\bgenai\b"]),
    ("data engineer", [
        r"\bbig data\b", r"\betl\b", r"\bhadoop\b", r"\bspark\b",
        r"data warehous", r"datawarehous", r"\binformatica\b", r"\bpyspark\b",
        r"\bsnowflake\b", r"\bdatabricks\b", r"\bairflow\b",
    ]),
    ("data analyst", [r"\bpower bi\b", r"\btableau\b", r"\bqlik"]),
    # Cloud-platform tokens land here, AFTER data engineer, so that
    # "Azure Data Engineer" is a data engineer and "Azure Admin" is devops.
    ("devops engineer", [
        r"\bkubernetes\b", r"\bterraform\b", r"\bansible\b", r"\bazure\b",
        r"\baws\b", r"\bgcp\b", r"\bjenkins\b", r"\bci\s*/\s*cd\b",
        r"\bsys ?admin\b", r"\bsystem admin",
    ]),
    # Server-side frameworks before bare languages: "Nestjs & Typescript" is a
    # backend job, and NestJS says so far more precisely than TypeScript does.
    ("backend developer", [
        r"\bspring( boot)?\b", r"\bdjango\b", r"\bflask\b", r"\bfastapi\b",
        r"\bnest\.?js\b", r"\bexpress\.?js\b", r"ruby on rails",
        r"\bmicroservices\b", r"\bnode\.?js\b", r"\blaravel\b",
    ]),
    ("frontend developer", [
        r"\breact\b", r"\bangular\b", r"\bvue\.?js\b", r"\bnext\.?js\b",
        r"\bsvelte\b",
    ]),
    # Bare languages last -- weakest signal. \bjava\b does NOT match
    # "javascript": the trailing 's' defeats the word boundary.
    ("backend developer", [
        r"\bjava\b", r"\.net\b", r"\bdotnet\b", r"\bc#", r"\bpython\b",
        r"\bphp\b", r"\bgolang\b", r"\bc\+\+", r"\bmainframe\b", r"\bcobol\b",
        r"\bscala\b",
    ]),
    ("frontend developer", [r"\bjavascript\b", r"\btypescript\b"]),
]

#: Kept for callers that only need the flat view (tier 1 then tier 2).
_RULES = _RULES_TIER1 + _RULES_TIER2

_EXCLUDE_C = [re.compile(p) for p in _EXCLUDE]
_TIER1_C = [(role, [re.compile(p) for p in pats]) for role, pats in _RULES_TIER1]
_TIER2_C = [(role, [re.compile(p) for p in pats]) for role, pats in _RULES_TIER2]
_RULES_C = _TIER1_C + _TIER2_C


def normalize_title(title: str) -> str:
    """Lowercase, drop non-ASCII, flatten separators.

    Source titles contain mangled en-dashes ("Sr. Associate � Projects") and
    use ':' / '-' / '/' interchangeably ("Application Developer: Java Full
    Stack"), so separators are flattened to spaces before matching.
    """
    t = title.lower()
    t = "".join(ch if ord(ch) < 128 else " " for ch in t)
    t = re.sub(r"[:;,\|\(\)\[\]]+", " ", t)
    return re.sub(r"\s+", " ", t).strip()


def map_title(title: str) -> str | None:
    """Map a job title to a canonical role, or None if it cannot be determined.

    None is a legitimate, expected outcome -- see rule 2 in the module
    docstring. Callers must drop the posting, not substitute a default.
    """
    t = normalize_title(title)
    if not t:
        return None
    for pattern in _EXCLUDE_C:
        if pattern.search(t):
            return None
    for role, patterns in _RULES_C:
        for pattern in patterns:
            if pattern.search(t):
                return role
    return None


def explain_title(title: str) -> tuple[str | None, str]:
    """Like map_title, but also returns why -- for auditing a corpus.

    Returns (role, reason). reason is the matched pattern when mapped, or
    "excluded:<pattern>" / "no_rule" / "blank" when not.
    """
    t = normalize_title(title)
    if not t:
        return None, "blank"
    for pattern in _EXCLUDE_C:
        if pattern.search(t):
            return None, f"excluded:{pattern.pattern}"
    for role, patterns in _RULES_C:
        for pattern in patterns:
            if pattern.search(t):
                return role, pattern.pattern
    return None, "no_rule"
