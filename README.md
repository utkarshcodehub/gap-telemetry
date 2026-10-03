# Job-Skill Gap Intelligence — "Gap Telemetry"

Scrapes real job postings → NLP-extracts & normalizes skills → parses your
resume/GitHub → outputs a quantified, demand-weighted gap report + LLM
learning roadmap. Now with authentication, locked-down CORS, upload
limits, rate limiting, and per-user data isolation.

## Architecture
```
postings (synthetic today → real corpus) ─┐
                              ├─► SkillExtractor ─► demand aggregation ─┐
resume PDF / GitHub ──────────┘        │                                ├─► gap score ─► Groq LLM roadmap ─► React dashboard
                               taxonomy (canonical skills + aliases) ───┘

Supabase Auth (JWT issuance) ──► FastAPI verifies locally via JWKS ──► user_id scopes
                                                                        every saved_analyses query
```

## Modules
- `core/taxonomy/` — 95+ canonical skills, ~300 aliases, collision-guarded loader
- `core/extraction/extractor.py` — spaCy PhraseMatcher engine, token-boundary safe, longest-match-wins
- `core/extraction/demand.py` — document-frequency demand aggregation
- `scraper/naukri_scraper.py` — Naukri JSON-API scraper. **Retired from the critical path** (undocumented API, rotating fingerprint headers); kept for reference
- `scraper/synthetic_generator.py` — 500-posting probability-weighted fallback dataset
- `core/db/store.py` — Supabase (Postgres): shared market tables + user-scoped `saved_analyses`, RLS-enforced
- `core/resume/parser.py` — pypdf extraction + scanned-PDF detection
- `core/github_profile/fetcher.py` — GitHub REST API skill evidence
- `core/gap/scorer.py` — demand-weighted readiness, percentile tiers, evidence levels
- `core/roadmap/generator.py` — Groq LLaMA roadmap + deterministic template fallback
- `core/auth/verify.py` — Supabase JWT verification (JWKS prod / HS256 dev), see below
- `app/settings.py`, `app/deps.py`, `app/main.py` — FastAPI: auth, CORS, upload limits, rate limiting
- `frontend/` — React dashboard with Supabase login gate
- `tests/` — 335 tests, real integration tests against the Supabase project
  in `backend/.env` (a configured project incl. service-role key is
  required to run them — see below)

## Auth & security

**Auth.** `/analyze`, `/roadmap`, and all `/analyses` routes require a
Supabase-issued bearer token, verified **locally** against the project's
JWKS endpoint (no network call to Supabase per request — the current
Supabase-recommended pattern; asymmetric key verification, not the older
shared-secret approach). `/health`, `/roles`, `/market/{role}` stay public
— they only expose aggregate market data.

**Per-user isolation.** A `saved_analyses` table lets a signed-in user
save and list their own gap reports. Every query filters by `user_id` in
the SQL itself — not just an application-layer check — so it can't leak
across users even if a check were forgotten elsewhere. Proven by
`tests/test_api_roadmap.py::test_user_b_cannot_*` (two different users,
one tries to read/delete the other's saved analysis, gets 404).

**CORS.** Locked to `CORS_ORIGINS` (env var), not `*`.

**Uploads.** Read in capped chunks (never buffer an unbounded file into
memory), checked for the `%PDF` magic bytes before parsing — the
`Content-Type` header is never trusted alone.

**Rate limiting.** `/analyze` and `/roadmap` (the expensive routes — PDF
parsing, an LLM call) are limited via `slowapi`; defaults in `.env.example`.

**The open problem.** Market demand is currently computed from
*synthetic* postings with hand-chosen skill probabilities, so every demand
percentage the UI shows describes an invented market. Replacing that with a
real, citable corpus is the top priority — see `docs/PLAN.md`.

## Setting up Supabase Auth

1. Create a free project at supabase.com (2 minutes).
2. Backend: copy `backend/.env.example` → `backend/.env`, set
   `SUPABASE_URL=https://<your-ref>.supabase.co` (no secret needs to be
   stored — verification uses the public JWKS endpoint).
3. Frontend: copy `frontend/.env.example` → `frontend/.env`, set
   `VITE_SUPABASE_URL` and `VITE_SUPABASE_ANON_KEY` (Project Settings → API).
4. Enable Email auth in Supabase Auth settings (on by default).

**Before you have a project set up**, or for local dev: leave
`AUTH_LOCAL_HS256_SECRET` set in `backend/.env` (any random string) and
mint a test token with:
```bash
cd backend
python3 scripts/mint_dev_token.py
curl -H "Authorization: Bearer $(python3 scripts/mint_dev_token.py)" http://127.0.0.1:8000/analyses
```

## Run

### Quickest path: one command

```bash
python bootstrap.py           # sets up what it can, names what it can't
python bootstrap.py --check   # verifies only, changes nothing
```

It creates the venv, installs both dependency sets, copies the `.env` templates,
probes the database (telling you *which* migration is missing rather than failing
opaquely), seeds the corpora from local archives, and catches the trap where
`backend/.env` and `frontend/.env` point at **different** Supabase projects. You
still have to paste your own Supabase credentials into the two `.env` files — it
cannot invent those — and it tells you exactly which keys are missing.

The manual steps below are what it automates, kept because knowing them matters
more than running one command.

### 1. Backend

```bash
cd backend
pip install -r requirements.txt
# No spaCy model download is needed — extraction uses spacy.blank("en")
# deliberately (see "Key design decisions" #1).

cp .env.example .env   # then edit — see "Setting up Supabase Auth" above
```

### 2. Apply the database schema — required, and easy to miss

Nothing works against an empty project: `/health`, `/roles` and every analysis
route will fail with opaque 500s if the tables don't exist. Apply both
migrations, in order, to your Supabase project (SQL Editor, or `supabase db
push` if you use the CLI):

```
backend/supabase/migrations/0001_core_schema.sql
backend/supabase/migrations/0002_pin_function_search_path.sql
```

### 3. Seed market data

```bash
cd backend
python3 ../scraper/synthetic_generator.py --count 500 --seed 42
```

> ⚠️ **This data is synthetic.** The skill probabilities in
> `scraper/synthetic_generator.py` are hand-chosen, not measured, so demand
> percentages derived from it describe an invented market, not a real one. It
> exists so the app runs offline. Replacing it with a real, citable posting
> corpus is the current priority — see `docs/PLAN.md` §6.
>
> `scraper/naukri_scraper.py` also exists but is **not** a supported path: it
> hits an undocumented internal API whose fingerprint headers must be
> hand-refreshed when they rotate. Kept for reference only.

### 4. Run both halves

```bash
cd backend && uvicorn app.main:app --reload    # http://127.0.0.1:8000/docs
```

```bash
cd frontend && npm install
cp .env.example .env
npm run dev                                     # http://localhost:5173
```

> **Two `.env` files, same project.** `backend/.env` needs `SUPABASE_URL`;
> `frontend/.env` needs `VITE_SUPABASE_URL` and `VITE_SUPABASE_ANON_KEY`. They
> must point at the *same* Supabase project. If the frontend's values are
> missing or wrong it does **not** fail at startup — it logs a console warning
> and then login fails with an unhelpful error, so check the browser console
> first if sign-in misbehaves.

### Before a demo: warm the GitHub cache

```bash
cd backend
python scripts/prewarm_cache.py <github-username>   # warm both passes
python scripts/prewarm_cache.py --check             # is it still usable?
```

An analysis with a GitHub username makes two API passes, and cold they cost ~15
seconds and ~24 requests against a rate limit shared by every analysis. Warm, the
same run costs about 1.3 seconds and nothing.

**The cache expires after 24 hours**, so `--check` before you present; it exits
non-zero when the cache is empty, stale, nearly stale, or has only one of the two
passes warmed. The cache is per-machine (under gitignored `backend/data/`), so a
demo from a different laptop starts cold regardless.

### Tests

```bash
cd backend && python3 -m pytest tests/ -q
```

> ⚠️ The suite runs against the **real** Supabase project in `backend/.env` and
> **truncates `postings`** (plus `skills`, `posting_skills`, `saved_analyses`)
> as part of its fixtures. Point `.env` at a disposable dev project, and
> re-seed with step 3 afterwards or `/roles` will show only test fixture data.

## Full demo sequence
1. Seed data (`synthetic_generator.py` — see the honesty caveat in Run step 3).
2. Start the backend, then the frontend.
3. Sign up / sign in on the login screen.
4. Pick role, upload resume PDF, enter GitHub username → Run gap analysis.
5. Save the analysis (proves per-user persistence), generate a roadmap.
6. Open a second browser (or incognito), sign in as a different user, confirm you don't see the first user's saved analysis — the isolation guarantee, live.

## Key design decisions
1. **spacy.blank("en"), not en_core_web_sm** for extraction — dictionary-driven task, tokenizer + PhraseMatcher is 10x faster with no accuracy cost for known skills.
2. **PhraseMatcher over regex** — token-boundary matching ("Go" won't match inside "going").
3. **Canonical normalization** — "ReactJS/React.js/react js" → "React", or demand counts fragment.
4. **Document frequency, not term frequency** for demand — one posting spamming a skill 5x shouldn't inflate its market demand.
5. **Demand-weighted readiness, not a skill count** — missing Python (90% demand) costs more than missing Terraform (10%).
6. **JWKS over shared-secret JWT verification** — local, fast, no per-request network call to the auth provider, and keys can rotate without redeploying the backend.
7. **SQL-level user scoping, not app-level checks** — `saved_analyses` has real Postgres Row-Level Security (`auth.uid() = user_id`, see `supabase/migrations/0001_core_schema.sql`), enforced by the database itself against the caller's own bearer token, not by an application-layer check. The app also adds an explicit `.eq("user_id", ...)` on every query as defense in depth, but RLS is what actually can't be bypassed.
8. **Two roadmap engines (Groq + template)** — resilience (the product never dies from a missing API key) doubles as a ready-made LLM-vs-rule-based comparison for the evaluation chapter.
