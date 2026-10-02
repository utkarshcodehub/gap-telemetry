# Job-Skill Gap Intelligence — Technical Documentation

This document explains, in plain language, **everything** this project does and **how** it does it —
every moving part, every design decision, every file's job. It's written so that someone with basic
programming knowledge but no prior context on this codebase can read it start to finish and understand
the whole system.

If you just want to run the project, see `README.md`. This file is the deep dive.

---

## Table of Contents

1. [What This Project Actually Does](#1-what-this-project-actually-does)
2. [The Big Picture: How Data Flows Through the System](#2-the-big-picture-how-data-flows-through-the-system)
3. [Tech Stack and Why Each Piece Was Chosen](#3-tech-stack-and-why-each-piece-was-chosen)
4. [Project Folder Structure](#4-project-folder-structure)
5. [The Database: What's Stored and Where](#5-the-database-whats-stored-and-where)
6. [Getting Job Postings Into the System](#6-getting-job-postings-into-the-system)
7. [The Skill Taxonomy — Teaching the System What a "Skill" Is](#7-the-skill-taxonomy--teaching-the-system-what-a-skill-is)
8. [The Extraction Engine — Finding Skills Inside Raw Text](#8-the-extraction-engine--finding-skills-inside-raw-text)
9. [Market Demand — How "Skill X Appears in 42% of Postings" Is Calculated](#9-market-demand--how-skill-x-appears-in-42-of-postings-is-calculated)
10. [Resume Parsing](#10-resume-parsing)
11. [GitHub Evidence — Turning Your Repos Into Skill Signal](#11-github-evidence--turning-your-repos-into-skill-signal)
12. [The Gap Scoring Algorithm — The Heart of the Product](#12-the-gap-scoring-algorithm--the-heart-of-the-product)
13. [Learning Roadmap Generation](#13-learning-roadmap-generation)
14. [The Role Fit Feature — A Separate Mini-Product](#14-the-role-fit-feature--a-separate-mini-product)
15. [Authentication and Security](#15-authentication-and-security)
16. [The Backend API — Every Endpoint Explained](#16-the-backend-api--every-endpoint-explained)
17. [The Frontend — How the React App Is Put Together](#17-the-frontend--how-the-react-app-is-put-together)
18. [Testing](#18-testing)
19. [Running the Project Locally](#19-running-the-project-locally)
20. [Known Rough Edges (Being Honest)](#20-known-rough-edges-being-honest)
21. [Glossary](#21-glossary)

---

## 1. What This Project Actually Does

In one sentence: **you give it your resume (and optionally a GitHub username), pick a target job role,
and it tells you exactly which in-demand skills you're missing for that role, backed by real numbers
from real job postings — then generates a personalized learning plan to close the gap.**

There are two separate features inside this one app:

- **Gap Telemetry** (the main feature) — compares your skills against what the job market actually
  demands for a role, and produces a "readiness score" plus a prioritized gap list and a learning roadmap.
- **Role Fit** (a second, self-contained feature) — simulates a college placement portal (TPO — Training
  & Placement Office, common in Indian engineering colleges) where you browse job listings and check how
  well you match each specific listing, including your academic marks as a minor factor.

Both features share the same underlying skill-extraction engine, but they answer different questions:
Gap Telemetry asks "what does the *entire market* for this role want, and where do I stand?" while Role
Fit asks "how well do I match *this one specific listing*?"

---

## 2. The Big Picture: How Data Flows Through the System

```
                    ┌─────────────────────────────────────────┐
                    │   JOB POSTINGS (real or synthetic)       │
                    │   scraper/naukri_scraper.py               │
                    │   scraper/synthetic_generator.py          │
                    └───────────────────┬───────────────────────┘
                                        │ raw posting text
                                        ▼
                    ┌─────────────────────────────────────────┐
                    │   SKILL EXTRACTOR (spaCy PhraseMatcher)  │
                    │   backend/core/extraction/extractor.py   │
                    │   uses the taxonomy to find & normalize   │
                    │   skill mentions in the text              │
                    └───────────────────┬───────────────────────┘
                                        │ normalized skills
                                        ▼
                    ┌─────────────────────────────────────────┐
                    │   SUPABASE POSTGRES DATABASE              │
                    │   postings / skills / posting_skills      │
                    └───────────────────┬───────────────────────┘
                                        │ aggregated via SQL
                                        ▼
                    ┌─────────────────────────────────────────┐
                    │   MARKET DEMAND per role                  │
                    │   "Python appears in 84% of postings      │
                    │    for 'backend developer'"                │
                    └───────────────────┬───────────────────────┘
                                        │
      ┌─────────────────────────────────┤
      │                                 │
      ▼                                 ▼
┌───────────────┐              ┌──────────────────────┐
│ YOUR RESUME    │              │ YOUR GITHUB PROFILE    │
│ (PDF or text)  │              │ (optional)              │
│ → same         │              │ → same extractor,       │
│   extractor    │              │   reads repo name/desc/  │
└───────┬───────┘              │   topics/language/README │
        │                       └───────────┬──────────────┘
        └───────────────┬───────────────────┘
                        ▼
            ┌─────────────────────────────┐
            │  GAP SCORER                    │
            │  backend/core/gap/scorer.py    │
            │  compares your skills against  │
            │  market demand → readiness      │
            │  score + tiered gap list         │
            └───────────────┬─────────────────┘
                            │
                            ▼
            ┌─────────────────────────────┐
            │  ROADMAP GENERATOR             │
            │  Groq LLM (or template          │
            │  fallback) turns the gap        │
            │  report into a week-by-week     │
            │  learning plan                   │
            └───────────────┬─────────────────┘
                            │
                            ▼
            ┌─────────────────────────────┐
            │  REACT FRONTEND                │
            │  displays everything, lets      │
            │  you save analyses for later    │
            └─────────────────────────────┘
```

Everything above the "GAP SCORER" box only needs to happen **once per role** (postings get scraped/
generated and stored). Everything from "YOUR RESUME" downward happens **every time you click "Run gap
analysis."**

---

## 3. Tech Stack and Why Each Piece Was Chosen

| Piece | What it is | Why this one |
|---|---|---|
| **FastAPI** | Python web framework for the backend API | Async-native, automatic request validation via Pydantic, auto-generates interactive API docs at `/docs` for free |
| **spaCy** (`spacy.blank("en")`) | NLP library, used only for tokenization + phrase matching | Deliberately the *blank* (no pretrained model) pipeline, not `en_core_web_sm`. Skill extraction is a dictionary-lookup problem, not a language-understanding problem — a blank tokenizer + `PhraseMatcher` is ~10x faster and just as accurate for matching known skill names, so there's no reason to pay for a full statistical model |
| **Supabase** | Hosted Postgres database + authentication service | Gives you a real Postgres database, user sign-up/sign-in, and Row-Level Security (database-enforced per-user data isolation) without running your own auth server |
| **PyJWT** | Verifies the login tokens Supabase issues | Lets the backend check "is this a real, unexpired, correctly-signed login token?" without calling Supabase over the network on every single request |
| **Groq** | Hosted LLM inference API (OpenAI-compatible) | Used for the two AI-generated features (learning roadmaps, Role Fit explanations) — chosen for very fast/cheap inference; the code talks to it via plain HTTP requests, no special SDK |
| **React + Vite** | Frontend framework + dev server/bundler | Vite gives near-instant hot-reload during development; React's component model fits the dashboard-with-panels UI naturally |
| **pypdf** | Extracts text from uploaded PDF resumes | Pure-Python, no external binary dependency, good enough for the "text layer" extraction this project needs (it does *not* do OCR — scanned image PDFs are explicitly rejected with a clear error) |
| **slowapi** | Rate limiting for FastAPI | Protects the expensive endpoints (PDF parsing, LLM calls) from being hammered |

---

## 4. Project Folder Structure

```
job-skill-gap/
├── README.md                       ← quick-start guide
├── TECHNICAL_DOCUMENTATION.md      ← this file
│
├── backend/
│   ├── app/                        ← the FastAPI web layer (HTTP concerns only)
│   │   ├── main.py                 ← all API routes for Gap Telemetry + saved analyses + Role Fit
│   │   ├── schemas.py              ← Pydantic request/response shapes (the API's public contract)
│   │   ├── settings.py             ← reads backend/.env into a typed Settings object
│   │   └── deps.py                 ← the `get_current_user` auth dependency
│   │
│   ├── core/                       ← all the actual logic, framework-agnostic
│   │   ├── taxonomy/               ← the master list of ~96 known skills + their aliases
│   │   ├── extraction/             ← spaCy-based skill-finding engine
│   │   ├── resume/                 ← PDF/text → structured resume profile
│   │   ├── github_profile/         ← GitHub API → skill evidence
│   │   ├── gap/                    ← the readiness-score / gap-tier algorithm
│   │   ├── roadmap/                ← LLM + template learning-plan generators
│   │   ├── match/                  ← Role Fit's scoring + listing parsing + LLM explainer
│   │   ├── auth/                   ← Supabase JWT verification
│   │   └── db/                     ← Supabase (Postgres) read/write layer
│   │
│   ├── scraper/ (see note)         ← actually lives at the repo root, see below
│   ├── scripts/mint_dev_token.py   ← generates a fake login token for local testing without Supabase
│   ├── supabase/migrations/        ← the SQL that creates the database tables + security rules
│   ├── tests/                      ← 89 automated tests, run against a real Supabase project
│   ├── ingest.py                   ← the shared "extract skills from postings, write to DB" pipeline
│   ├── requirements.txt            ← Python dependencies
│   └── .env / .env.example         ← configuration (API keys, database URL — .env is git-ignored)
│
├── scraper/                        ← at repo root, imported by backend scripts
│   ├── naukri_scraper.py           ← pulls real postings from Naukri.com's internal API
│   └── synthetic_generator.py      ← generates realistic fake postings (the usual data source)
│
└── frontend/
    └── src/
        ├── main.jsx                ← app entry point
        ├── AuthGate.jsx            ← login/signup screen, shows App.jsx once signed in
        ├── App.jsx                 ← the "Gap Telemetry" tab — the main dashboard
        ├── RoleFitPage.jsx         ← the "Role Fit" tab — the TPO-portal simulation
        ├── HistoryPanel.jsx        ← "saved analyses" list/view/delete panel
        ├── components.jsx          ← shared presentational pieces (gauges, panels, charts)
        ├── api.js                  ← every backend HTTP call lives here
        ├── supabaseClient.js       ← the one place the frontend talks to Supabase directly
        ├── theme.js                ← light/dark mode persistence
        └── styles.css              ← all styling (no CSS framework — hand-written)
```

---

## 5. The Database: What's Stored and Where

The project uses **one Supabase Postgres project** for everything, but treats different tables with
different trust levels. The schema lives in `backend/supabase/migrations/0001_core_schema.sql`.

### Tables

| Table | Purpose | Who can write to it | Who can read it |
|---|---|---|---|
| `postings` | Raw job postings (title, company, description, etc.) | Only the backend's admin key (scraper/generator scripts) | Anyone (public market data) |
| `skills` | The deduplicated list of canonical skill names that have appeared in postings | Only the backend's admin key | Anyone |
| `posting_skills` | Join table: "posting X mentions skill Y, Z times" | Only the backend's admin key | Anyone |
| `saved_analyses` | One row per gap report a user chose to save | The owning user only | The owning user only |

### Two different "keys" used to talk to this database

This is one of the more important design decisions in the whole project, so it's worth explaining
carefully:

- **`SUPABASE_SERVICE_ROLE_KEY`** — an all-powerful admin key. It bypasses every security rule
  (Row-Level Security, see below). The backend uses this key *only* for writing market data
  (`JobStore` in `core/db/store.py`), because the backend itself is the trusted party doing that write —
  there's no "user" involved in scraping job postings.
- **The signed-in user's own login token** — when a user saves a gap analysis, the backend does **not**
  use its admin key. Instead it takes the exact bearer token the user's browser sent, and uses *that* to
  talk to the database (`AnalysesStore` in `core/db/store.py`). This means the database itself — not the
  backend's application code — decides whether that user is allowed to see or delete that row.

### Row-Level Security (RLS) — the real enforcement mechanism

Postgres has a feature where you can attach security rules directly to a table, and those rules are
checked on *every* query no matter how the query was issued — even if there's a bug in the application
code that forgot to filter by user. This project uses it on `saved_analyses`:

```sql
create policy "select own analyses"
    on public.saved_analyses for select
    using (auth.uid() = user_id);
```

In plain English: "you may only `SELECT` rows where the `user_id` column matches your own logged-in user
ID." The same rule exists for `insert` and `delete`. `auth.uid()` is a special Postgres function Supabase
provides that reads the user ID straight out of the verified login token attached to the request — so
there's no way to fake it.

The backend *also* adds an explicit `.eq("user_id", ...)` filter in its own queries (see
`AnalysesStore.list_analyses` etc. in `store.py`), even though RLS would already block cross-user access
on its own. This is "defense in depth" — two independent layers, so a mistake in one doesn't compromise
the whole system.

### Aggregation via SQL functions (RPCs)

Some queries (like "for role X, what percentage of postings mention each skill?") involve `GROUP BY` and
counting across joined tables — the kind of query Supabase's simple query-builder API can't express. For
these, the migration defines real SQL functions (`get_demand`, `get_role_counts`) that the Python backend
calls via `.rpc("get_demand", {...})`. This keeps the aggregation logic in the database, where it's fast,
instead of pulling every row over the network and counting them in Python.

---

## 6. Getting Job Postings Into the System

Before you can compare a resume against "the job market," there needs to be job market data sitting in
the database. There are two ways postings get in, both living at the repo root in `scraper/`:

### 6a. `synthetic_generator.py` — the one actually used day-to-day

This generates realistic-*looking* fake job postings, seeded so results are reproducible. It defines
four roles, each with a hand-curated list of skills and the *probability* that skill shows up in a
posting for that role:

```python
"backend developer": [
    (["Node.js", "NodeJS", "node"], 0.55),
    (["Python", "python"], 0.50),
    (["REST APIs", "RESTful APIs", "REST"], 0.75),
    ...
]
```

For each fake posting, it rolls a random number against each skill's probability to decide whether to
include it, picks a random company/location/title/experience/salary from curated lists, and stitches it
all into a paragraph using one of three sentence templates. Run with `--count 500 --seed 42`, it
generates 500 postings split evenly across the four roles (125 each). Using a fixed random seed means
running it twice produces the exact same dataset — useful for reproducible demos and tests.

### 6b. `naukri_scraper.py` — real data, but fragile by nature

This is a *real, working* scraper — not a stub — that hits Naukri.com's own internal JSON search API
directly (`https://www.naukri.com/jobapi/v3/search`), the same API Naukri's own website's JavaScript
calls when you search on their site. It:

- Sends two special headers (`appid`, `systemid`) that identify the request as coming from Naukri's own
  mobile app — without them the API rejects the request.
- Paginates through results, waiting 2.5–4 seconds (randomized) between pages to avoid hammering the
  server.
- Retries with exponential backoff if it gets rate-limited (HTTP 429) or a server error.
- Saves each raw JSON response to `backend/data/raw/` as a snapshot, in case you want to re-process it
  without re-fetching.
- Feeds parsed postings into the exact same `ingest_postings()` pipeline the synthetic generator uses.

The fragility: those `appid`/`systemid` header values aren't officially documented anywhere — they were
found by inspecting Naukri's own mobile app traffic, and Naukri can change them at any time, which would
silently break the scraper until someone re-captures new values. This is why the synthetic generator
exists as the default/fallback data source.

### 6c. The shared ingestion pipeline

Both sources ultimately call `ingest_postings()` in `backend/ingest.py`:

```python
def ingest_postings(records, store, extractor=None):
    for rec in records:
        posting_id = store.insert_posting(rec)   # 1. save the posting itself
        if posting_id is None:
            continue                              # already existed, skip
        for skill in extractor.extract(rec.description):
            skill_id = store.upsert_skill(skill.canonical, skill.category)
            store.link_skill(posting_id, skill_id, skill.count)  # 2. record which skills it mentions
    return inserted
```

Two important details:

1. **Skills are extracted at *ingest* time, not at query/analysis time.** By the time a posting is in
   the database, its skills have already been identified and linked. This makes every later query fast —
   no re-parsing text on every request.
2. **Deduplication happens via `on_conflict="source,external_id"` with `ignore_duplicates=True`.** Every
   posting has a `(source, external_id)` pair (e.g. `("synthetic", "syn-backenddeveloper-42")`) that acts
   as its unique fingerprint. Running the generator or scraper again won't create duplicate rows for
   postings it's already seen — `insert_posting()` returns `None` for anything that already exists, and
   `ingest_postings()` simply skips extracting skills for it again.

---

## 7. The Skill Taxonomy — Teaching the System What a "Skill" Is

Job postings and resumes describe the same skill in wildly inconsistent ways: `"ReactJS"`, `"React.js"`,
`"react js"`, and `"React"` all mean the exact same thing. If the system treated these as four different
skills, market-demand percentages would fragment into meaninglessness (a skill mentioned in 40% of
postings might look like four different skills each mentioned in 10%).

The fix is `backend/core/taxonomy/skills_taxonomy.json` — a hand-curated list of **96 canonical skills**
across 12 categories, each with a list of known surface forms ("aliases"):

```json
{
  "canonical": "JavaScript",
  "category": "programming_language",
  "aliases": ["javascript", "js", "ecmascript", "es6", "vanilla js"]
}
```

| Category | # skills | Examples |
|---|---|---|
| `ml_ai` | 17 | Machine Learning, TensorFlow, PyTorch, LLMs, Prompt Engineering |
| `data` | 13 | SQL, Pandas, Power BI, Data Visualization, Statistics |
| `programming_language` | 10 | Python, Java, JavaScript, TypeScript, Go, Rust |
| `backend` | 10 | REST API, FastAPI, Django, Spring Boot, Microservices |
| `cloud_devops` | 10 | AWS, Docker, Kubernetes, CI/CD, Terraform |
| `database` | 9 | PostgreSQL, MongoDB, Redis, MySQL |
| `frontend` | 8 | React, Next.js, Tailwind CSS, Redux |
| `cs_fundamentals` | 6 | Data Structures & Algorithms, System Design, Computer Networks |
| `soft_skill` | 4 | Communication Skills, Teamwork, Agile/Scrum |
| `mobile` | 3 | Android Development, React Native, Flutter |
| `testing` | 3 | Unit Testing, Selenium, pytest/JUnit |
| `emerging` | 3 | Blockchain, and other newer tech |

`core/taxonomy/loader.py`'s `Taxonomy` class loads this file once and builds two lookup dictionaries:

- **`alias_map`**: every alias (lowercased) → its canonical name. `"reactjs"` → `"React"`.
- **`category_map`**: canonical name → category. `"React"` → `"frontend"`.

One safety check runs at load time: if two different skills accidentally claim the same alias (an
"alias collision"), the loader raises an error immediately at startup rather than silently letting one
skill's data get corrupted by another's — a data-integrity bug here would be very hard to notice later.

**Why `soft_skill`s are excluded from scoring:** the gap scorer (section 12) deliberately ignores the
`soft_skill` category when building its market-demand "basket." Things like "communication skills" show
up in tons of postings but aren't a *learnable, closeable gap* the way "Docker" is — including them would
inflate/distort the readiness score without giving the user anything actionable to do about it.

---

## 8. The Extraction Engine — Finding Skills Inside Raw Text

This is arguably the most technically interesting part of the project: given a blob of raw text (a job
posting description, a resume, a GitHub repo's README), how do you reliably find every skill mention in
it, matching real word boundaries, handling messy real-world formatting?

`backend/core/extraction/extractor.py`'s `SkillExtractor` class does this using **spaCy's
`PhraseMatcher`** — a tool built specifically for "find any of these N known phrases inside this text,
matching whole tokens only." This matters because a naive string-search approach (`"go" in text`) would
wrongly match the substring "go" inside the word "going" — `PhraseMatcher` operates on tokens (words),
so it only matches "go" as its own standalone word.

### Setup (once, at startup)

```python
self.nlp = spacy.blank("en")
self.matcher = PhraseMatcher(self.nlp.vocab, attr="LOWER")
for skill in self.taxonomy.skills:
    patterns = list(self.nlp.pipe({skill.canonical.lower(), *skill.aliases}))
    self.matcher.add(skill.canonical, patterns)
```

Every one of the 96 skills' canonical name + all its aliases get registered as patterns the matcher
should look for, tagged with the skill's canonical name as the "label" to return when matched.

### The extraction pipeline, step by step

Given some input text, `extract()` does:

1. **Clean the text** (`_clean_no_camel_split`) — collapse separator characters (commas, slashes,
   bullets, pipes, brackets) and `&` into spaces, collapse multiple spaces into one.
2. **Tokenize and match** — run spaCy's tokenizer, then `PhraseMatcher` finds every span of tokens that
   matches a known skill's canonical name or alias.
3. **Resolve overlaps ("longest match wins")** — if the text contains "React Native," the matcher might
   find both `"React"` (a skill on its own) and `"React Native"` (a different skill) overlapping at the
   same position. The code sorts matches by length (longest first) and keeps a match only if none of its
   tokens have already been "claimed" by a longer match:
   ```python
   matches = sorted(matches, key=lambda s: (-(s.end - s.start), s.start))
   taken: set[int] = set()
   for span in matches:
       if any(t in taken for t in range(span.start, span.end)):
           continue
       taken.update(range(span.start, span.end))
       kept.append(span)
   ```
   This correctly extracts "React Native" as one skill instead of double-counting it as both "React" and
   "React Native."
4. **Second pass: camelCase splitting for leftover tokens.** This handles a specific, real problem: some
   job-portal tags come squished together with no spaces at all, e.g. `"ReactNative"` typed as one word.
   The *first* pass deliberately does **not** split camelCase words (explained below), so a token like
   `"ReactNative"` won't have matched anything yet. For every token still unmatched after pass 1, the
   code tries inserting spaces before capital letters (`"ReactNative"` → `"React Native"`) and looks that
   up directly against the alias map.

### Why camelCase splitting isn't done on the *first* pass — a real bug this project hit and fixed

Early in this project's life, camelCase splitting ran unconditionally on *all* text before matching. This
seemed harmless until it started corrupting real one-word product names: `"JavaScript"` → `"Java Script"`
(which wrongly matched just "Java"), `"TypeScript"` → `"Type Script"` (matched nothing), `"PostgreSQL"` →
`"Postgre SQL"` (only generic "SQL" survived), `"LLaMA"` → `"LLa MA"` (matched nothing).

The fix — the two-pass approach described above — matches the *unsplit* text first (so one-word aliases
like `"javascript"`, `"typescript"`, `"postgresql"` match directly and correctly), and only falls back to
splitting camelCase for whatever tokens are *still* unmatched afterward. This gets the best of both: real
compound product names extract correctly, and genuinely squished multi-word tags (`"ReactNative"`) still
get caught by the fallback pass.

### `preprocess()` — a second, separate function, deliberately unused by `extract()`

You'll notice `extractor.py` has a `preprocess()` function that *does* unconditionally camelCase-split,
and it's covered by its own unit tests but never called by `extract()` itself. This is intentional — it's
kept as a standalone utility (and its own contract is tested independently) but the two-pass strategy
inside `extract()` uses a separate near-identical cleaning function (`_clean_no_camel_split`) that skips
just the camelCase step. Keeping `preprocess()` around unchanged means its existing tests keep proving it
does what it always did, without entangling it with the fix above.

---

## 9. Market Demand — How "Skill X Appears in 42% of Postings" Is Calculated

This is a **document-frequency** calculation, not a term-frequency one — a deliberate choice explained in
the SQL function comments. The difference matters:

- **Term frequency** would count *every mention*: a posting that says "Python" five times would count as
  5 toward Python's total.
- **Document frequency** counts *how many distinct postings mention it at all*, regardless of how many
  times. A posting mentioning Python once and a posting mentioning it five times both count as exactly 1.

Document frequency is the right metric here because the question being answered is "what fraction of
*employers* want this skill," not "how many times does this word appear in the corpus" — one posting
that stuffs "Python Python Python" shouldn't make Python look more in-demand than it really is.

The actual computation happens in Postgres (`get_demand` SQL function, `backend/supabase/migrations/
0001_core_schema.sql`):

```sql
select
    s.canonical,
    s.category,
    count(distinct ps.posting_id) as postings_count,
    round(count(distinct ps.posting_id) / nullif((select n from total), 0) * 100, 1) as demand_pct,
    sum(ps.mention_count) as total_mentions
from public.posting_skills ps
join public.skills   s on s.id = ps.skill_id
join public.postings p on p.id = ps.posting_id
where p_role_query is null or p.role_query = p_role_query
group by s.id
order by postings_count desc;
```

`count(distinct ps.posting_id)` is the document-frequency count. `demand_pct` divides that by the total
number of postings for the role and multiplies by 100. `total_mentions` (a simple `sum`) is kept around
too, purely as extra context, but it isn't what drives the readiness score.

(There's a legacy in-memory version of this same idea, `core/extraction/demand.py`'s `aggregate_demand()`
— it predates the move to Supabase and is no longer used by the running app; it's only referenced by its
own test today. The real, current computation is the SQL function above.)

---

## 10. Resume Parsing

`backend/core/resume/parser.py` handles turning an uploaded resume into a structured, skill-tagged
profile.

- **PDF text extraction** uses `pypdf` — it reads the PDF's embedded text layer directly. It does **not**
  perform OCR (optical character recognition on images), so a resume that's actually a scanned photo/
  image with no real text layer will fail to parse.
- **Scanned-PDF detection**: after extracting text, if the result is under 50 characters, the parser
  assumes it's a scanned image PDF and raises a clear `ResumeParseError` telling the user to export a
  digital PDF instead of guessing at garbled OCR output.
- **Section detection** (`_SECTION_RE`): a regex looks for common resume section headers (Skills,
  Projects, Experience, Education, Certifications, Achievements, etc.) and records which ones were found
  — mostly informational, not currently used to weight extraction differently by section.
- **Skill extraction** — the resume's raw text is run through the exact same `SkillExtractor` used for
  job postings, ensuring consistent canonicalization on both sides of the comparison.

Two entry points exist: `parse_resume(path)` reads from a file path (used by CLI tools/tests),
`parse_resume_text(text)` takes already-extracted text (used by the API, which extracts PDF text itself
first so it can validate upload size/type before parsing — see section 16).

---

## 11. GitHub Evidence — Turning Your Repos Into Skill Signal

`backend/core/github_profile/fetcher.py`'s `fetch_github_profile(username, ...)` supplements your resume
with evidence pulled from your public GitHub activity — the idea being that a skill you've actually
*used* in real projects but forgot to write on your resume shouldn't count against you.

### What it actually reads

For a given username, it calls GitHub's REST API (`GET /users/{username}/repos`, up to 100 repos, owned
repos only — forks are explicitly excluded so a repo you merely starred/forked doesn't inflate your
evidence). For each repo, it builds a block of "evidence text" out of:

- the repo name (with dashes/underscores turned into spaces, e.g. `job-skill-gap` → `job skill gap`)
- the repo's description field
- its topics (tags)
- its primary language (as reported by GitHub)
- **its README content** (up to the first 4000 characters, capped at the 20 most-recently-updated repos)

That combined text gets run through the same `SkillExtractor` used everywhere else, and every skill found
is tallied as "found in N of your repos."

**Why README content was added on top of the metadata fields:** repo name/description/topics/language
are frequently left blank on personal projects — most people never fill in a repo's "About" box on
GitHub. A README, by contrast, is where people actually *describe* what they built and what they used.
Reading it dramatically increases how much real signal gets found, especially for projects with sparse
metadata but a proper README.

**Why README fetching is capped at 20 repos:** each README fetch is a *separate* GitHub API call. Someone
with 100 repos would otherwise trigger 101 total API calls for one analysis — both slow, and easy to
exhaust GitHub's rate limit. Capping it to the 20 most recently updated repos is a reasonable tradeoff:
recent work is the most representative signal anyway.

### Rate limits and the optional token

Unauthenticated requests to GitHub's API are capped at 60 per hour, *shared across every user of this
app if they're all coming from the same server IP* — easy to exhaust with even light usage. Setting
`GITHUB_TOKEN` in `backend/.env` (any GitHub Personal Access Token, no special scopes needed for reading
public repos) raises that ceiling to 5,000 requests/hour and is sent as `Authorization: Bearer <token>`
on every request.

If a fetch fails — user not found (404), rate limit hit (403), or any network error — it's caught and
turned into a readable status string (`"skipped: GitHub user 'x' not found"` etc.) rather than crashing
the whole analysis; GitHub evidence is always an optional enhancement, never a hard requirement.

### How the extracted skills actually affect your score

This is worth being explicit about, because it's easy to *think* it's cosmetic when it isn't: in
`core/gap/scorer.py`, GitHub-derived skills are unioned directly into the same set used for scoring:

```python
user_all = resume_skills | set(github_skills)
```

A skill found only on GitHub counts exactly the same toward the readiness score as one found on your
resume. Each matched market skill also gets tagged with **where the evidence came from** — `"resume"`,
`"github"`, or `"resume+github"` — which the frontend surfaces via a dedicated "GitHub evidence" panel
(see section 17) so the contribution is visible, not buried.

Three things affect *how much difference* adding a GitHub username actually makes to your final score,
worth understanding if it ever looks like "nothing happened":

1. **Overlap with your resume.** If a skill GitHub found was already on your resume, the score can't move
   for that skill — it was already counted.
2. **Relevance to the selected role.** GitHub might turn up real skills (say, "Rust") that simply aren't
   part of the demand basket for the role you're analyzing against — those get bucketed into `extras`
   (skills you have that the market doesn't currently ask for in this role) rather than closing a gap.
3. **Metadata richness.** Repos with no description/topics and a thin or missing README will yield little
   or nothing, regardless of how much real skill went into the code itself — the extractor can only see
   text, not source code.

---

## 12. The Gap Scoring Algorithm — The Heart of the Product

`backend/core/gap/scorer.py`'s `score_gap()` function is where everything comes together. Given a role's
market demand data, your resume skills, and your GitHub skills, it produces a `GapReport`. Let's walk
through exactly what it does, with a worked example.

### Step 1 — Build the "basket": which market skills actually count?

```python
basket = [m for m in market if m["demand_pct"] >= MIN_DEMAND_PCT and m["category"] not in SOFT_CATEGORIES]
```

Two filters are applied to the raw market-demand list before anything else:

- **`MIN_DEMAND_PCT = 5.0`** — a skill mentioned in fewer than 5% of postings for this role is treated as
  noise/one-off, not filtered out of the *database*, but excluded from the scoring basket. Otherwise a
  single quirky posting mentioning an obscure tool would create a "gap" that's not really representative
  of the market.
- **`soft_skill` category is excluded** — as explained in section 7, "communication skills" isn't a
  closeable technical gap the way "Docker" is.

### Step 2 — Compute the readiness score

```python
total_demand = sum(m["demand_pct"] for m in basket)
matched_demand = sum(m["demand_pct"] for m in basket if m["canonical"] in user_all)
readiness = round(matched_demand / total_demand * 100, 1)
```

This is a **demand-weighted** score, not a simple "skills you have ÷ skills that exist" count. Concretely:
imagine the basket is just two skills — Python at 90% demand and Terraform at 10% demand. If you know
Python but not Terraform: `matched_demand = 90`, `total_demand = 100`, readiness = **90%**. If you know
Terraform but not Python: `matched_demand = 10`, readiness = **10%**. Missing the high-demand skill costs
far more than missing the low-demand one — which matches reality (a role that lists Python in 9 out of 10
postings but Terraform in only 1 clearly cares much more about Python).

### Step 3 — Rank the gaps into tiers

Everything in the basket that you *don't* have becomes a "gap." Gaps are sorted by demand percentage
(highest first), then split into three equal-sized tiers by rank position:

```python
def _tier(rank, total):
    pct = rank / total
    if pct <= 1/3:  return "critical"
    if pct <= 2/3:  return "important"
    return "nice_to_have"
```

So if there are 12 missing skills, the top 4 (by demand) are "critical," the next 4 are "important," and
the bottom 4 are "nice to have." This is a straightforward percentile split — it's not saying "critical"
means some fixed demand threshold, it means "you're missing this and it's in the top third of what you're
missing, ranked by how much the market wants it."

### Step 4 — Determine evidence for each matched skill

For every basket skill you *do* have, the code figures out where the evidence for it came from:

```python
def evidence_for(name):
    on_resume = name in resume_skills
    repos = github_skills.get(name, 0)
    if on_resume and repos:  return "resume+github", repos
    if on_resume:             return "resume", 0
    return "github", repos
```

Skills whose evidence is `"github"` only (found in your repos but *not* on your resume) get collected
separately as `hidden_strengths` — the report explicitly calls these out with a note:

> "Resume upgrade: X, Y appear in your GitHub repos but not on your resume — add them with project
> evidence."

This is actionable advice, not just data — you clearly know the skill (it's in real code), you just
haven't written it down.

### Step 5 — `extras`: skills you have that the market for this role doesn't want (much)

```python
extras = tuple(sorted(user_all - {m["canonical"] for m in basket}))
```

Anything you know (from resume or GitHub) that isn't part of this role's demand basket at all — either
because it's below the 5% noise threshold or genuinely irrelevant to this specific role — gets listed
here. This field is computed by the backend but, as of this writing, isn't rendered anywhere in the
frontend yet (see section 20).

### Full worked example

Say the basket for "backend developer" is:

| Skill | Demand |
|---|---|
| Python | 70% |
| SQL | 60% |
| Docker | 40% |
| Redis | 20% |
| Kafka | 10% |

Your resume has Python and SQL. Your GitHub has Python and Docker (found via a README).

- `user_all = {Python, SQL, Docker}`
- `total_demand = 70 + 60 + 40 + 20 + 10 = 200`
- `matched_demand = 70 (Python) + 60 (SQL) + 40 (Docker) = 170`
- `readiness = round(170 / 200 * 100, 1) = 85.0`
- Missing: Redis (20%), Kafka (10%) → both gaps. With 2 missing skills, rank 1 (Redis, higher demand)
  falls in the top third → `"critical"`. Rank 2 (Kafka) falls in the bottom third → `"nice_to_have"`.
- Evidence: Python → `"resume+github"` (found in both), SQL → `"resume"`, Docker → `"github"` only, which
  also makes it a `hidden_strength` with the "add it to your resume" note.

---

## 13. Learning Roadmap Generation

Once you have a `GapReport`, `backend/core/roadmap/generator.py`'s `generate_roadmap()` turns it into a
week-by-week study plan. There are **two interchangeable engines**, and the system always tries the
better one first with an automatic fallback:

```python
def generate_roadmap(report, n_weeks=6, api_key=None):
    groq = GroqRoadmapEngine(api_key=api_key)
    if groq.available:
        try:
            return groq.generate(report, n_weeks)
        except Exception:
            pass
    return TemplateRoadmapEngine().generate(report, n_weeks)
```

### `GroqRoadmapEngine` — the real, AI-generated plan

If a Groq API key is configured, the gap report's critical gaps, important gaps, and existing strengths
(with their evidence source) get formatted into a detailed prompt and sent to Groq's chat-completions API
(OpenAI-compatible endpoint, currently configured to use the `openai/gpt-oss-120b` model). The system
prompt instructs the model at length on what makes a *good* roadmap for this specific use case — not
generic advice, but role-specific, prerequisite-aware, action-oriented, free-resource-only, with exactly
one concrete project per week that increases in complexity as the weeks progress. The model is asked to
respond in strict JSON (`response_format: {"type": "json_object"}`), which is then parsed directly into
`RoadmapWeek` objects.

If the LLM call fails for *any* reason (network error, invalid API key, malformed JSON response, rate
limit) — the `except Exception: pass` catches it and the code falls straight through to the template
engine below, so a broken or missing API key degrades the *quality* of the roadmap but never breaks the
feature entirely.

### `TemplateRoadmapEngine` — the deterministic fallback, always available

No API call, no network dependency. It simply takes the ranked gap list, chunks it two skills per week,
and fills in one of three fixed action-template sentences ("Read the official {skill} getting-started
guide...", "Complete one hands-on {skill} tutorial...", "Solve 3-5 small exercises using {skill}..."),
plus a generic project suggestion combining the new skill with an existing strength. It's intentionally
plain — its job is to guarantee the product *works* even with zero configuration, not to be impressive.

### Why the "engine" field matters

Every `Roadmap` object carries an `engine` field (`"groq"` or `"template"`), returned to the frontend so
it's visible which one produced a given plan — useful both for debugging ("why does this roadmap look so
generic? — oh, the API key isn't set") and for transparency to the end user.

### A real bug this project hit, worth knowing about

Early on, the `/roadmap` API endpoint called `generate_roadmap(report, n_weeks=req.n_weeks)` — without
passing the `api_key` argument at all. `GroqRoadmapEngine.__init__` falls back to reading
`os.environ.get("GROQ_API_KEY", "")` when no key is explicitly passed — but the backend's settings system
(`pydantic-settings`, reading from `backend/.env`) does **not** copy values into `os.environ` — it only
populates its own `Settings` object. So even with a perfectly valid `GROQ_API_KEY` sitting in `.env`, the
roadmap engine would silently see an empty key and fall back to the template every single time, with no
error or warning anywhere. The fix was simply to pass it explicitly:
`generate_roadmap(report, n_weeks=req.n_weeks, api_key=settings.groq_api_key)`. This is a good example of
why "it's configured in `.env`" isn't automatically the same as "the code that needs it can see it."

---

## 14. The Role Fit Feature — A Separate Mini-Product

Role Fit (`frontend/src/RoleFitPage.jsx`, backed by `core/match/`) simulates browsing a college campus
placement portal and checking your fit against individual listings — deliberately a *different* mental
model from Gap Telemetry's "whole market" view.

### The mock listings

`backend/core/match/mock_listings.json` contains 8 hand-written fake job listings styled after a real TPO
portal, complete with realistically messy `required_skills` tags exactly as a company recruiter might
type them — e.g. `"problemsolving"`, `"logicalthinking"`, `"Clean&maintainablecoding"`,
`"Python/Django"`, `"ReactNative"`. This messiness is deliberate — it's the same real-world tag-quality
problem this project's extraction engine already has to solve.

### `listing_parser.py` — separating real skills from unmatchable noise

Each listing's raw tags get run individually through the `SkillExtractor`. Tags that resolve to a real
taxonomy skill go into `tech_skills`; tags that don't match anything (like `"logicalthinking"` — a soft
trait, not a discrete skill) go into `unmatched_tags`. This distinction is surfaced to the user
explicitly rather than either silently dropping unmatched tags (which would inflate the match percentage,
since the denominator shrinks) or silently counting them as "missing" (which would unfairly deflate it,
since the user can't "learn" logical thinking the way they can learn Django).

### `fit_scorer.py` — a deterministic, non-AI score

```python
raw_score = (skill_pct * 0.85) + ((50.0 + acad_adj) * 0.15)
```

The match percentage is **85% driven by skill overlap**, and 15% by a gentle, capped adjustment based on
academic marks (10th/12th/CGPA, if the user provides any). The 85/15 split is a deliberate design choice
explained directly in the code's docstring: the listing's required-skills field is the company's own
explicit statement of what they want, while academic marks are a general, much weaker signal — heavily
weighting them would let a high CGPA mask a real skill gap, or let a low CGPA unfairly punish someone who
has every listed skill.

The academic adjustment itself is a curve, not a raw percentage: marks above a 75% "neutral" baseline earn
a small bonus (capped at +10 points), marks below it cost a small penalty (capped at −8 points) — this is
explicitly a soft heuristic (raw marks aren't comparable across boards/institutions), not a precise
signal, and the UI shows the exact point adjustment transparently rather than hiding it inside the final
number.

The final percentage always maps to one of exactly four fixed labels — `"Strong Fit"` (≥80), `"Good Fit"`
(≥60), `"Partial Fit"` (≥40), `"Needs Work"` (below that) — chosen deliberately over letting an LLM invent
free-text labels, so a student checking multiple listings sees a consistent vocabulary every time.

### `verdict_explainer.py` — the AI layer, constrained to *explaining*, not *deciding*

Same dual-engine pattern as the roadmap generator (Groq LLM + deterministic template fallback). Critically,
the LLM is **only ever given the already-computed matched/missing/unmatched skill lists and the final
score** — never the raw resume or listing text — so it's structurally incapable of inventing a skill that
wasn't really found, or contradicting the number that was already calculated by ordinary code. Its only
job is writing 2-3 plain-English sentences about *why* the score is what it is. Output is capped at 300
tokens specifically to prevent it from rambling into a full essay.

### One entry point *(was two — consolidated)*

**`POST /role-fit`** (in `main.py`) is the single route that computes a Role Fit result. It takes a
`listing_id` referencing one of the 8 mock listings, plus a resume, optional academic marks, and an
optional `github_username` whose extracted skills are merged into the candidate's skill set the same way
`/analyze` does — including passing the configured `GITHUB_TOKEN` through, so it isn't stuck on GitHub's
unauthenticated rate limit.

There used to be a second route, `POST /role-fit-direct`, in its own `role_fit_direct.py`. It took the
listing's fields as raw form data instead of an ID, for listing data read live off a page by a
`role-fit-widget.js`. That widget was never written and nothing in the frontend ever called the route, so
it was an unauthenticated, untested duplicate of ~100 lines of the same logic — with its own separate
hardcoded 5MB upload cap that ignored the configurable `MAX_UPLOAD_BYTES`. It was deleted; its one genuine
capability (GitHub enrichment) was folded into `/role-fit`, which is where the `github_username` parameter
above came from.

---

## 15. Authentication and Security

### How login works

The frontend talks to Supabase Auth *directly* (`frontend/src/supabaseClient.js`) for sign-up/sign-in —
the backend is never involved in that step at all, and never sees a password. Once signed in, Supabase
hands the frontend a **JWT** (JSON Web Token) — a signed, self-contained proof of identity. Every
subsequent API call to the backend attaches this token as `Authorization: Bearer <token>`.

### How the backend verifies that token — two supported modes

`backend/core/auth/verify.py`'s `TokenVerifier` supports two genuinely-different-but-both-real Supabase
signing modes simultaneously:

1. **JWKS (production)** — Supabase signs tokens with an asymmetric key pair (RS256/ES256). The backend
   fetches the project's *public* key from a well-known URL
   (`{SUPABASE_URL}/auth/v1/.well-known/jwks.json`) once, caches it, and verifies every token's signature
   locally — no network call to Supabase on each request. If a token shows up signed with a key ID
   (`kid`) the cache doesn't have yet (e.g. after Supabase rotates keys), `PyJWKClient` automatically
   re-fetches.
2. **HS256 (local dev / tests)** — a simpler shared-secret signing mode. Still a real, currently-supported
   Supabase mode, not a fake shortcut — it's what lets the test suite and local development work without
   needing a live Supabase project reachable at all.

Both can be configured at once (`SUPABASE_URL` and `AUTH_LOCAL_HS256_SECRET` both set in `.env`), and
JWKS is tried first with a fallback to HS256 if the token doesn't verify against JWKS — useful during a
migration from local dev to a real project. Either way, every token is checked for a valid signature, a
non-expired timestamp, and the `aud` (audience) claim equal to `"authenticated"` — rejecting a token
signed for some other purpose from being replayed here.

`backend/scripts/mint_dev_token.py` generates a fake-but-validly-signed HS256 token for local testing
without ever touching a real Supabase project.

### What's public vs. what requires login

`/health`, `/roles`, and `/market/{role}` are intentionally public — they only expose aggregate,
non-personal market statistics (e.g. "500 postings analyzed"), so a landing page can show real numbers
before anyone signs in. Every route that touches personal data (`/analyze`, `/roadmap`, all `/analyses`
routes) requires a valid bearer token via the `get_current_user` FastAPI dependency — missing or invalid
token means a `401` before the route's own code ever runs.

### CORS

Locked to an explicit allow-list read from the `CORS_ORIGINS` environment variable (defaulting to just
the local Vite dev server) — not the common-but-unsafe `allow_origins=["*"]`.

### Upload safety

Resume file uploads are read in 1MB chunks with a running total, aborting the moment the configured
`MAX_UPLOAD_MB` limit is exceeded — the file is never fully buffered into memory first (which would let
someone exhaust server memory with one huge upload before the size check ever runs). After reading, the
first bytes are checked for the literal `%PDF-` magic-number header before attempting to parse it — a
client-supplied `Content-Type` header is never trusted alone, since it's trivial to fake.

### Rate limiting

`slowapi` enforces per-client-IP limits (configurable via `.env`, defaulting to 10/minute) specifically on
`/analyze` and `/roadmap` — the two expensive routes (PDF parsing + potentially an LLM call). Cheaper
read-only routes get a looser default limit.

### Handling a specific database-level auth edge case

A token can pass the backend's own JWT verification (it's correctly signed, not expired) but still not be
a real Supabase-issued *session* — for example, the local dev HS256 test token. If such a token gets
forwarded to Supabase's PostgREST layer (which happens for the `saved_analyses` routes, see section 5),
PostgREST itself rejects it and the `supabase-py` library raises a `postgrest.APIError`. Without handling,
this would surface as an unhelpful generic 500 error. `main.py` registers a global exception handler that
catches this specific exception type and turns it into a clean, honest `401 Session rejected by the
database`.

---

## 16. The Backend API — Every Endpoint Explained

Base URL in development: `http://127.0.0.1:8000`. Interactive docs auto-generated by FastAPI are always
available at `/docs`.

| Method & Path | Auth required? | Purpose |
|---|---|---|
| `GET /health` | No | Returns `{"status": "ok", "postings_in_db": N}` — a liveness/data-availability check |
| `GET /roles` | No | Lists every role that has market data, with posting counts, for populating the role dropdown |
| `GET /market/{role}` | No | Full skill-demand breakdown for one role (canonical name, category, demand %, mention count) |
| `POST /analyze` | Yes | The core Gap Telemetry action. Takes `role`, a resume (`resume_file` PDF or `resume_text`), and optional `github_username`; returns a full `GapReport` plus which skills were found and the GitHub fetch status |
| `POST /roadmap` | Yes | Takes a `role`, a resume-skill list, optional GitHub skills, and desired week count; re-runs the gap scorer and generates a learning roadmap from the result |
| `POST /analyses` | Yes | Saves a gap report permanently to the signed-in user's account |
| `GET /analyses` | Yes | Lists the signed-in user's saved analyses (summary only: id, role, score, date) |
| `GET /analyses/{id}` | Yes | Full detail (including the complete report) for one saved analysis — 404 (not 403) if it doesn't exist *or* belongs to someone else, so a caller can't distinguish "doesn't exist" from "exists but isn't yours" |
| `DELETE /analyses/{id}` | Yes | Deletes one saved analysis, same not-found-vs-not-yours behavior |
| `GET /listings` | No | Summary list of the 8 mock Role Fit listings, for the browsing grid |
| `GET /listings/{id}` | No | Full detail for one listing |
| `POST /role-fit` | Yes | Computes a Role Fit match score against one listing by ID. Takes `listing_id`, a resume (`resume_file` or `resume_text`), optional `academic_marks`, and an optional `github_username` whose skills are merged into the candidate's set |

Why `/analyze` and `/roadmap` accept a resume two different ways (`resume_file` *or* `resume_text`): the
frontend lets a user either upload a PDF or paste raw text directly — useful for quickly testing without
needing an actual PDF file handy. `_resume_text_from_inputs()` in `main.py` prefers `resume_text` if
present and non-empty, otherwise falls back to extracting from `resume_file`.

---

## 17. The Frontend — How the React App Is Put Together

No routing library, no global state library (Redux/Zustand/etc.) — the whole app is deliberately built
with plain React `useState`/`useEffect`, which is entirely sufficient for its size. There are exactly two
top-level "pages," switched by a simple `tab` state variable rather than a URL router.

### Component tree

```
main.jsx
 └─ AuthGate.jsx           (shows a login form, or renders App once signed in)
     └─ App.jsx            (the top-level app shell once authenticated)
         ├─ [tab: Gap Telemetry]
         │   ├─ HistoryPanel.jsx        (saved analyses: list / view / delete)
         │   ├─ ReadinessGauge          ─┐
         │   ├─ StrengthsPanel           │  all from components.jsx —
         │   ├─ GitHubEvidencePanel      │  pure presentational, receive
         │   ├─ GapBoard                 │  a `report` object as props
         │   └─ RoadmapTimeline         ─┘
         └─ [tab: Role Fit]
             └─ RoleFitPage.jsx  (its own self-contained grid → detail → result flow)
```

### `App.jsx` — the Gap Telemetry dashboard

Holds all the session state: selected role, resume text/file, GitHub username, the analysis result, the
generated roadmap, save status, theme, and the saved-analyses history panel's open/closed state and
refresh counter. On mount, it fetches the role list from `/roles`; if that fails (backend unreachable), it
falls back to a hardcoded `FALLBACK_ROLES` list so the UI still renders something reasonable, with a clear
error message.

One subtle bug this project hit and fixed, worth understanding as a general React lesson: the initial
role-selection logic was `setRole((current) => current || list[0].role)`. Since `role` starts as a
non-empty string (`FALLBACK_ROLES[0].role`), `current` was *always* truthy, so this line could never
actually update the selection once real roles loaded — the `<select>`'s displayed value stayed pinned to
a role name that might not even be one of the newly-loaded `<option>`s, silently sending an invalid role
to `/analyze`. The fix checks whether the *current* selection is actually present in the *newly fetched*
list, falling back to the first real option only if not:
`setRole((current) => (list.some((r) => r.role === current) ? current : list[0].role))`.

### `HistoryPanel.jsx` — saved analyses

A self-contained component (owns its own fetch/loading/error state, similar in spirit to `RoleFitPage.jsx`
rather than the purely-presentational components in `components.jsx`). It lists saved analyses (newest
first — the database query itself is already sorted that way), expands a row in place to show the full
report using the exact same `ReadinessGauge`/`StrengthsPanel`/`GapBoard` components a fresh analysis uses,
and deletes with a two-step inline confirmation (no `window.confirm()` — kept as an in-page UI element
consistent with the rest of the app). It accepts a `refreshKey` prop that `App.jsx` increments after every
successful save, so the list updates automatically without a manual page refresh.

### `GitHubEvidencePanel` — making GitHub's contribution visible

Added specifically because a single small status line (`"✓ GitHub: ok (12 repos)"`) made it easy to miss
whether GitHub evidence actually *did* anything. This panel explicitly lists every strength whose evidence
includes GitHub, tagging each one either **"new · github only"** (a skill your resume didn't mention —
these are the `hidden_strengths` from section 12) or **"confirmed"** (a skill both sources agree on), or
shows an honest "no new skills beyond your resume" message if there was genuinely nothing new to add.

### `api.js` — the one file that talks to the backend

Every backend call lives here as a small exported async function (`analyze()`, `getRoadmap()`,
`saveAnalysis()`, `listSavedAnalyses()`, etc.), each attaching the Supabase access token as a bearer
header via a shared `authHeader()` helper. `jsonOrThrow()` is the shared error-handling wrapper — it
specifically handles FastAPI/Pydantic's validation-error shape (`detail` being an array of `{msg, ...}`
objects rather than a plain string) and turns it into a readable joined message instead of the raw
`[object Object]` a naive `.detail` access would produce.

### Dev-mode API proxy

`frontend/vite.config.js` proxies any request to `/api/*` straight through to `http://127.0.0.1:8000/*`
during development, stripping the `/api` prefix. This means the frontend code never needs to know or care
about the backend's actual host/port — it always just calls `/api/...`, and Vite's dev server forwards it.

### Theming

`theme.js` is deliberately tiny: reads/writes a `theme` value in `localStorage` and sets a `data-theme`
attribute on the `<html>` element. All the actual color values live in `styles.css` as CSS custom
properties (`--bg`, `--panel`, `--accent`, etc.), defined once for light mode and overridden for dark mode
under `:root[data-theme="dark"]` — no JavaScript-driven style computation, just CSS variables switching.

---

## 18. Testing

**89 automated tests** across 6 files in `backend/tests/`, run with `pytest`:

| File | # tests | Covers |
|---|---|---|
| `test_api_roadmap.py` | 25 | Full API integration tests: `/analyze`, `/roadmap`, `/analyses` CRUD, auth enforcement |
| `test_match_score.py` | 24 | Role Fit's deterministic scoring math, listing parsing |
| `test_extraction.py` | 13 | The skill extractor: camelCase handling, alias resolution, overlap resolution |
| `test_resume_gap.py` | 13 | Gap scoring math, GitHub fetcher parsing |
| `test_auth.py` | 8 | JWT verification (JWKS and HS256 paths), rejection cases |
| `test_db_ingest.py` | 6 | The ingest pipeline writing to the real database |

An important, deliberate characteristic of this test suite: **these are real integration tests against a
live Supabase project**, not mocked-database unit tests. `backend/tests/conftest.py` connects to whatever
project is configured in `backend/.env`, creates two real test-auth users, and — critically —
**truncates the entire `postings` table** before running the API test fixtures
(`_truncate_market_data()`), reseeding it with a small amount of fixture data the tests themselves need.

**This has a real, easy-to-be-surprised-by consequence:** running the test suite against the same
Supabase project you use for actual development will wipe out whatever real/synthetic dataset was seeded
there, replacing it with a handful of tiny test-fixture postings. This is intentional and documented in
the code's own comment ("safe here because the configured Supabase project is a disposable dev/FYP
sandbox") — but it means the practical workflow is: **run the test suite, then re-run
`synthetic_generator.py` afterward** to restore a full dataset before demoing or using the app normally.

---

## 19. Running the Project Locally

(Condensed here — `README.md` has the full step-by-step with exact commands.)

1. **Backend**: `pip install -r backend/requirements.txt`, download the spaCy tokenizer data, copy
   `backend/.env.example` → `backend/.env` and fill in a Supabase project's URL + keys (or use
   `AUTH_LOCAL_HS256_SECRET` for auth-free local dev), then `uvicorn app.main:app --reload` from
   `backend/`.
2. **Seed data**: run `python scraper/synthetic_generator.py --count 500 --seed 42` from `backend/` (it
   must run from there so the relative `.env` path resolves).
3. **Frontend**: `npm install` in `frontend/`, copy `frontend/.env.example` → `frontend/.env` with the
   Supabase project's public URL + anon key, then `npm run dev`.
4. **Optional but recommended**: add `GROQ_API_KEY` and `GITHUB_TOKEN` to `backend/.env` to unlock
   AI-generated roadmaps/explanations and authenticated (higher-rate-limit) GitHub lookups. Both are fully
   optional — the app works correctly without either, just with the template roadmap engine and
   unauthenticated GitHub requests.

One easy-to-miss gotcha: **`uvicorn --reload` only watches Python files for changes, not `.env`.** Editing
`.env` while the backend is already running has no effect until the process is fully stopped and
restarted — the settings object is only read once, at process startup.

---

## 20. Known Rough Edges (Being Honest)

In the spirit of explaining *everything*, including what isn't perfect yet:

- **The `extras` field is computed but never displayed.** The gap scorer calculates which of your skills
  aren't part of the current role's demand basket (section 12, step 5), but no frontend component renders
  it yet — this data is silently thrown away today.
- **The Naukri scraper is inherently fragile**, depending on undocumented API headers that Naukri could
  change at any time with no warning (section 6b). It's real, working code — not a stub — but it's not
  something to depend on for guaranteed uptime.
- **Role Fit still scores against 8 hand-written mock listings**, not real postings (section 14) — so
  the feature demonstrates the algorithm rather than doing anything useful yet.
- **The two LLM-prompt files (`roadmap/generator.py` and `match/verdict_explainer.py`) currently point at
  two different Groq models** (`openai/gpt-oss-120b` vs. `llama-3.3-70b-versatile` respectively) — not
  wrong, just worth knowing they aren't kept in sync automatically.
- **Running the test suite wipes real market data** in whatever Supabase project is configured (section
  18) — a deliberate tradeoff for realistic integration testing, but easy to be caught off guard by.

---

## 21. Glossary

- **Canonical name** — the one "official" spelling a skill is normalized to (e.g., `"React"`), regardless
  of how many different ways it appears in raw text (`"ReactJS"`, `"react.js"`, `"React JS"`).
- **Document frequency** — counting how many distinct documents (postings) mention something at least
  once, as opposed to counting every individual mention.
- **JWT (JSON Web Token)** — a signed, tamper-evident piece of text that proves "this user is who they
  claim to be," issued at login and attached to every subsequent request.
- **JWKS (JSON Web Key Set)** — a published set of public cryptographic keys a service (Supabase) exposes,
  letting anyone verify that service's signed tokens without contacting it directly.
- **PhraseMatcher** — a spaCy tool for finding exact, whole-word matches of known phrases inside text,
  as opposed to fuzzy/statistical matching.
- **RLS (Row-Level Security)** — a Postgres feature that attaches access rules directly to a table, so
  the database itself (not application code) enforces who can see/modify which rows.
- **RPC (Remote Procedure Call)** — here, calling a predefined SQL function on the database from
  application code, used for aggregate queries that can't be expressed through Supabase's simpler
  query-builder API.
- **Service role key** — Supabase's admin-level API key that bypasses all Row-Level Security; used only
  by trusted backend processes, never sent to the frontend.
- **Readiness score** — this project's headline number: what percentage of a role's demand-weighted
  market skill basket you currently cover.
- **Tier (critical / important / nice_to_have)** — a percentile ranking of your *missing* skills by how
  much market demand each one represents.
