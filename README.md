# Job-Skill Gap Intelligence — "Gap Telemetry" (FYP)

Scrapes real job postings → NLP-extracts & normalizes skills → parses your
resume/GitHub → outputs a quantified, demand-weighted gap report + LLM
learning roadmap. Now with authentication, locked-down CORS, upload
limits, rate limiting, and per-user data isolation.

## Architecture
```
postings (Naukri/synthetic) ─┐
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
- `scraper/naukri_scraper.py` — Naukri JSON-API scraper (rate-limited, idempotent — run locally)
- `scraper/synthetic_generator.py` — 500-posting probability-weighted fallback dataset
- `core/db/store.py` — Supabase (Postgres): shared market tables + user-scoped `saved_analyses`, RLS-enforced
- `core/resume/parser.py` — pypdf extraction + scanned-PDF detection
- `core/github_profile/fetcher.py` — GitHub REST API skill evidence
- `core/gap/scorer.py` — demand-weighted readiness, percentile tiers, evidence levels
- `core/roadmap/generator.py` — Groq LLaMA roadmap + deterministic template fallback
- `core/auth/verify.py` — Supabase JWT verification (JWKS prod / HS256 dev), see below
- `app/settings.py`, `app/deps.py`, `app/main.py` — FastAPI: auth, CORS, upload limits, rate limiting
- `frontend/` — React dashboard with Supabase login gate
- `tests/` — 63 tests, real integration tests against the Supabase project
  in `backend/.env` (a configured project incl. service-role key is
  required to run them — see below)

## Auth & security (Day 6)

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

**What's still open, on purpose (see conversation notes):** the Naukri
scraper hits an undocumented internal API — resolve the data-sourcing
question before any commercial use.

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

```bash
# Backend
cd backend
pip install -r requirements.txt
python3 -m spacy download en_core_web_sm
cp .env.example .env   # then edit — see "Setting up Supabase Auth" above
# Tests hit the real Supabase project above (incl. writing/truncating
# postings/skills/saved_analyses and two test auth users) — point .env
# at a disposable dev project, not one with data you care about.
python3 -m pytest tests/ -v      # 63 passed
# From the repo root, or use the direct script path from backend/.
python3 -m scraper.naukri_scraper --role "machine learning intern" --pages 25
python3 ../scraper/synthetic_generator.py --count 500 --seed 42
uvicorn app.main:app --reload    # http://127.0.0.1:8000/docs

# Frontend (separate terminal)
cd frontend
npm install
cp .env.example .env   # fill in your Supabase project values
npm run dev             # http://localhost:5173
```

## Full demo sequence (viva)
1. Seed data (Naukri scraper or synthetic generator).
2. Start the backend, then the frontend.
3. Sign up / sign in on the login screen.
4. Pick role, upload resume PDF, enter GitHub username → Run gap analysis.
5. Save the analysis (proves per-user persistence), generate a roadmap.
6. Open a second browser (or incognito), sign in as a different user, confirm you don't see the first user's saved analysis — the isolation guarantee, live.

## Key design decisions (interview prep)
1. **spacy.blank("en"), not en_core_web_sm** for extraction — dictionary-driven task, tokenizer + PhraseMatcher is 10x faster with no accuracy cost for known skills.
2. **PhraseMatcher over regex** — token-boundary matching ("Go" won't match inside "going").
3. **Canonical normalization** — "ReactJS/React.js/react js" → "React", or demand counts fragment.
4. **Document frequency, not term frequency** for demand — one posting spamming a skill 5x shouldn't inflate its market demand.
5. **Demand-weighted readiness, not a skill count** — missing Python (90% demand) costs more than missing Terraform (10%).
6. **JWKS over shared-secret JWT verification** — local, fast, no per-request network call to the auth provider, and keys can rotate without redeploying the backend.
7. **SQL-level user scoping, not app-level checks** — `saved_analyses` has real Postgres Row-Level Security (`auth.uid() = user_id`, see `supabase/migrations/0001_core_schema.sql`), enforced by the database itself against the caller's own bearer token, not by an application-layer check. The app also adds an explicit `.eq("user_id", ...)` on every query as defense in depth, but RLS is what actually can't be bypassed.
8. **Two roadmap engines (Groq + template)** — resilience (the product never dies from a missing API key) doubles as a ready-made LLM-vs-rule-based comparison for the evaluation chapter.
