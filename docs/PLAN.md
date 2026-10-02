# Gap Telemetry — Software Development Plan (SDLC)

**Project:** Evidence-Verified Skill Intelligence
**Owner:** Utkarsh Raj · **Team:** 5 · **Duration:** 2026-09-21 → March 2027
**Model:** Iterative-Incremental, 6 increments aligned to monthly mentor reviews

---

# PART I — PROJECT DEFINITION

## 1. Problem statement

A resume is a self-report. Every system that consumes one — placement portals, ATS
filters, and the large family of student "resume analyser" projects — treats claims as
facts and does keyword matching on text the candidate wrote themselves. The output is a
number nobody can justify.

This has two victims. **Candidates** apply repeatedly and hear nothing, with no way to
learn why. **Recruiters** cannot distinguish a claimed skill from a practised one, so
they fall back on college tier and referrals.

The current codebase inherits this exact flaw. `core/github_profile/fetcher.py`
concatenates each repo's **name, description, topics, and README** and runs a keyword
matcher over it. All four fields are written by the candidate. The "second source" is the
same person's claims typed into a different box. The one field GitHub computes from real
file contents — `language` — is fetched and then discarded.

**That is why the project reads as generic: at present, it is doing what every other
resume project does.**

## 2. Solution concept

> **Every skill-gap tool gives you one number based on what you claim. We give you two:
> what you claim, and what you can prove.**

The system verifies each claimed skill against artifacts the candidate's *tools*
produced rather than artifacts the candidate *wrote* — repository file trees, dependency
manifests, commit authorship, language statistics. It reports **claimed readiness** and
**verified readiness** separately, and the distance between them is the product.

This is a **verification engine** with two surfaces on top:

- **Seeker surface (primary):** know where you stand, what you can prove, what to fix.
- **Recruiter surface (secondary):** verify a candidate's claims against public evidence.

Both read the same engine. The recruiter view is a different presentation of the same
verification record, not a second system — which is what makes a two-sided model
achievable inside one final-year project.

## 3. The "would I use this?" test

The single acceptance criterion for every feature: **would the owner use this on his own
resume, and would it help?** A concrete pass looks like this:

| # | Output | Why it earns its place |
|---|---|---|
| 1 | "Of 14 claimed skills: 9 verified, 3 unverifiable, 2 contradicted" | Honest, specific, checkable |
| 2 | "You claim Docker. No Dockerfile in 23 repos." | Surprising and immediately actionable |
| 3 | "Redis and Celery appear in 3 projects but not on your resume." | Free value on first use — **already half-built** as `hidden_strengths` |
| 4 | "62% verified readiness for Backend Developer. Top gap: Docker (71% of postings)." | Prioritised by real market data |
| 5 | "8 live postings you're closest to fitting, ranked." | Decision support |
| 6 | "6-week plan closing your top 3 gaps, with the project to build." | Action |
| 7 | *(next visit)* "You said you'd learn Docker. There's a Dockerfile in `api-service` now. Gap closed." | **The reason to come back** — the plan verifies itself (§9.7) |

Rows 2 and 3 are the ones nobody else produces. **Specificity is what stops a product
feeling generic** — "your readiness is 62%" is forgettable; "you claim Docker and there
is no Dockerfile" is not.

## 4. Objectives

| ID | Objective | Measured by |
|---|---|---|
| O1 | Verify skill claims against non-self-authored artifacts | Precision/recall vs. annotated ground truth (E1) |
| O2 | Distinguish *unverifiable* from *contradicted* | Reported separately; never conflated in scoring |
| O3 | Ground demand in a real, citable posting corpus | Zero invented probabilities in production |
| O4 | Produce actionable, evidence-conditioned guidance | Rubric evaluation (E4) |
| O5 | Serve both seeker and recruiter from one engine | Both surfaces live on the same verification record |
| O6 | Be genuinely usable by its own author | Owner's resume analysed; findings verified by hand |

---

# PART II — REQUIREMENTS

## 5. Functional requirements

### 5.1 Evidence & verification (the core — new)

| ID | Requirement | Priority |
|---|---|---|
| FR-1 | Fetch a candidate's public repos, excluding forks | Must |
| FR-2 | Retrieve each repo's full file tree in **one** API call (`git/trees?recursive=1`) | Must |
| FR-3 | Detect skills from **filesystem signals** (`Dockerfile`, `*.tf`, `.github/workflows/`, `*.ipynb`, `k8s/*.yaml`) | Must |
| FR-4 | Parse dependency manifests: `package.json`, `requirements.txt`, `pyproject.toml`, `go.mod`, `pom.xml`, `build.gradle`, `Gemfile`, `composer.json`, `Cargo.toml` | Must |
| FR-5 | Map declared dependencies → canonical skills (`react` → React, `torch` → PyTorch) | Must |
| FR-6 | Verify commit authorship per repo via the commits API filtered by author | Must |
| FR-7 | Incorporate GitHub's computed language-byte statistics (currently discarded — D5) | Must |
| FR-8 | Assign every skill an evidence tier E0–E4 (§9.1) | Must |
| FR-9 | Assign every claim a verdict: VERIFIED / WEAK / UNVERIFIABLE / CONTRADICTED | Must |
| FR-10 | Compute a continuous confidence score per skill from tier, repo count, recency, authorship share | Must |
| FR-11 | Report **verification coverage** — what fraction of claims could be checked at all | Must |
| FR-12 | Accept alternative evidence (deployed URLs, certificates, academic project PDFs) at explicitly lower tiers | Should |
| FR-13 | Record full provenance per skill: which repo, which file, which line of resume | Must |
| FR-14 | Weight evidence by recency; surface stale skills | Should |

### 5.2 Market intelligence

| ID | Requirement | Priority |
|---|---|---|
| FR-15 | Ingest a frozen, citable public postings dataset as the research corpus | Must |
| FR-16 | Ingest a live public job API (Adzuna / Remotive / Jooble) for freshness | Should |
| FR-17 | Compute demand as document frequency from **one** implementation (resolve D4) | Must |
| FR-18 | Induce the skill taxonomy from the corpus rather than a hand-typed list (§9.2) | Must |
| FR-19 | Support every role the corpus contains, not 4 hardcoded ones | Must |
| FR-20 | Retire `synthetic_generator.py` to test fixtures only, clearly relabelled | Must |

### 5.3 Analysis & guidance

| ID | Requirement | Priority |
|---|---|---|
| FR-21 | Report **claimed readiness** and **verified readiness** as two distinct numbers | Must |
| FR-22 | Rank gaps by demand weight with justified thresholds (resolve D2, D3) | Must |
| FR-23 | Surface *unclaimed verified* skills — "on GitHub, missing from your resume" | Must |
| FR-24 | Surface `extras` in the UI (computed today, never rendered — D13) | Should |
| FR-25 | Generate roadmaps conditioned on evidence; every item cites its gap | Must |
| FR-26 | Validate LLM roadmap output against the prompt's own structural rules (D14) | Must |
| FR-27 | Rank live postings by fit for the candidate | Should |

### 5.4 Role Fit (second pillar, retained)

| ID | Requirement | Priority |
|---|---|---|
| FR-28 | Score fit against **real** listings, not 8 hand-written mocks (D12) | Must |
| FR-29 | Reconcile fit score with verified readiness — not an unrelated second percentage | Must |
| FR-30 | Consolidate `/role-fit` and `/role-fit-direct` into one authenticated endpoint (D10, D11) | Must |

### 5.5 Recruiter surface (secondary)

| ID | Requirement | Priority |
|---|---|---|
| FR-31 | Given a resume + GitHub handle, produce a verification report | Must |
| FR-32 | Display per-claim verdicts with provenance links | Must |
| FR-33 | Show verification coverage prominently so absence is never read as dishonesty | Must |
| FR-34 | Candidate-initiated shareable verified profile (public link) | Should |

### 5.6 Platform (largely built — preserve)

| ID | Requirement | Status |
|---|---|---|
| FR-35 | Supabase auth, JWKS-verified | Built, keep |
| FR-36 | Per-user saved analyses under RLS | Built, keep |
| FR-37 | Capped, magic-byte-checked PDF upload | Built, keep |
| FR-38 | Rate limiting on expensive routes | Built, keep |

### 5.7 Private and non-public evidence

*A candidate's best work is often the work they cannot show. Handling this badly makes the
product feel like an accusation; handling it well is a genuine contribution.*

| ID | Requirement | Priority |
|---|---|---|
| FR-39 | Optional GitHub OAuth `repo` scope — with explicit consent, verify against private repositories | Must |
| FR-40 | **Local evidence scanner** — a CLI the candidate runs on their own machine against work/private code; reads manifests and `git log --author`, emits a *signed evidence digest* (derived skills, authorship share, timestamps). **No source code, file contents, or repo names leave the machine.** | Must |
| FR-41 | Self-attestation — candidate marks a skill as used in private/work code; recorded at tier **EA (ATTESTED)** and always labelled as not independently verified | Must |
| FR-42 | **Zero-disclosure guarantee** — private evidence contributes derived signals only; the recruiter surface can show "Docker verified" without exposing any private artifact | Must |
| FR-43 | Private-evidence consent is revocable; revocation expires the derived signals and visibly lowers the affected tiers | Must |

### 5.8 Experience, voice and retention

| ID | Requirement | Priority |
|---|---|---|
| FR-44 | Display-layer voice mapping, technically separate from engine verdict names (§9.6) | Must |
| FR-45 | **Self-verifying roadmap** — detect completion of a roadmap item from new evidence and close the gap automatically, with no self-reporting (§9.7) | Must |
| FR-46 | Evidence-change detection between visits — "since you were last here…" | Must |
| FR-47 | Verified-readiness timeline plotted from existing `saved_analyses` history | Should |
| FR-48 | Milestones on genuine achievements only (first verified skill, first gap closed by real code) | Should |
| FR-49 | Shareable verified profile — public link, candidate-initiated (supersedes FR-34) | Should |
| FR-50 | Role watchlist — track a target role; surface threshold crossings and market drift | Could |

## 6. Non-functional requirements

| ID | Requirement | Target |
|---|---|---|
| NFR-1 | Full analysis latency | < 45 s for a 25-repo profile |
| NFR-2 | GitHub API budget per analysis | < 150 requests (limit: 5,000/hr authenticated) |
| NFR-3 | Cache repo evidence | 24 h TTL; re-analysis of an unchanged profile costs ~0 calls |
| NFR-4 | Graceful degradation | Any external failure (GitHub, LLM, live API) degrades with an explicit status, never a silent zero |
| NFR-5 | Reproducibility | Every paper number regenerates by one command against the frozen corpus |
| NFR-6 | Setup | Clean clone → working demo in one documented command (resolves D17, D18) |
| NFR-7 | Privacy | Public data only; uploaded resumes never persisted beyond the user's own saved analyses |
| NFR-8 | Auditability | Every score decomposes into named, inspectable contributions |
| NFR-9 | Test suite | Green; covers all endpoints incl. the JWKS path (D15) |
| NFR-10 | Honest UI | No claim of "real market demand" unless real market data backs it |

## 7. Feasibility

**Technical.** Every required signal comes from documented, authenticated GitHub REST
endpoints — no cloning, no compilation, no code execution. The heaviest single call is
`git/trees?recursive=1`, one per repo. Budget for a 25-repo profile: 1 repo list + 25
trees + ~25 manifest fetches + 25 commit queries ≈ **76 calls**, well inside NFR-2. The
one genuine unknown is manifest→skill mapping quality, mitigated by starting with the
~200 highest-frequency packages per ecosystem.

**Operational.** Team capacity is bursty and checkpoint-driven. Every increment is sized
to be completable in a focused push before a review, and no lane blocks another.

**Legal / ethical.** Public GitHub data via the official API under its documented terms;
job data via published datasets and public APIs. The Naukri scraper — undocumented
internal API, hand-refreshed fingerprint headers — is **removed from the critical path**
and written up as an explored-and-rejected approach. Resume donors give written consent;
anonymisation is scripted. These decisions become a report section rather than a
liability.

**Economic.** Supabase free tier, Groq free tier, GitHub free API, public datasets.
Zero marginal cost.

---

# PART III — DESIGN

## 8. SDLC model and justification

**Iterative-incremental**, six increments, each ending at a monthly mentor review.

Justified by three project properties: requirements are partly discovered through
experiment (verification accuracy is not knowable in advance); an external reviewer
inspects progress monthly and can redirect it; and team availability is bursty, which
makes fixed-length increments with hard handoffs far safer than continuous flow.

Waterfall is rejected — it cannot absorb a mentor's mid-project redirection, and the
research component's requirements genuinely are not fully knowable at the start. Pure
agile is rejected — sprint cadence does not match a team that works in bursts around
review dates, and an FYP needs frozen deliverables, not a perpetually moving backlog.

Each increment carries all SDLC phases at small scale: requirements refinement → design
→ implementation → testing → review.

## 9. Core design

### 9.1 The evidence model *(the heart of the system)*

**Evidence tiers** — ordered by how hard the signal is to fabricate:

| Tier | Name | Source | Fakeable? |
|---|---|---|---|
| **E0** | CLAIMED | Resume text | Trivially |
| **EA** | ATTESTED | Candidate asserts private/work evidence (FR-41) | Trivially — but honestly flagged as unverified |
| **E1** | MENTIONED | Repo README / description / topics | Trivially — *this is all the system does today* |
| **E2** | PRESENT | File tree (`Dockerfile`, `*.tf`, `.github/workflows/`) — public, OAuth-private, or local-scanner digest | Hard — requires real project structure |
| **E3** | DECLARED | Dependency manifest entry | Very hard — the toolchain would break |
| **E4** | AUTHORED | E2/E3 evidence in a repo with verified commit authorship | Effectively not |

**Verdicts** — per claimed skill:

- **VERIFIED** — supported at E2 or above.
- **WEAK** — supported only at E1.
- **UNVERIFIABLE** — insufficient public artifacts to check. **Never a penalty.**
- **ATTESTED** — candidate declares private/work evidence. Ranked above a bare claim,
  below anything independently checked, and always labelled as such.
- **CONTRADICTED** — claimed, *and* the candidate has substantial public code in a
  context where the skill should appear, and it does not.

> **Contradiction safety rule.** CONTRADICTED requires *positive counter-evidence*:
> substantial authored code in a context where the skill would necessarily appear, and it
> does not. It never fires from absence alone, never when verification coverage is low,
> and never against a skill attested as private (FR-41). Absence of proof is always
> reported as UNVERIFIABLE. This rule is the difference between a product people trust and
> one that reads as an accusation.

> The UNVERIFIABLE / CONTRADICTED distinction is the intellectual core of the project.
> Conflating them is what makes naive verification unfair, and separating them is what
> makes this defensible. It is also the honest answer to the empty-GitHub problem.

**Confidence** — continuous per skill, replacing the current three-value label:

```
confidence = f(max_tier, n_repos_with_evidence, recency_weight, authorship_share)
```

**Readiness** — two numbers, always reported together:

- `claimed_readiness` — demand-weighted coverage counting every claim (today's number,
  retained as the baseline).
- `verified_readiness` — the same computation weighted by confidence.

**Coverage** — `verifiable_claims / total_claims`, shown prominently so a low verified
score is never misread as dishonesty when it is really absence of public code.

This directly replaces `core/gap/scorer.py:67`'s `resume_skills | set(github_skills)`
and makes the evidence label causal rather than cosmetic (D1).

### 9.2 Open-vocabulary taxonomy

*Answering the owner's question: "what does this 96-skill extractor mean, and why are we
limited?"*

Today `core/taxonomy/skills_taxonomy.json` is 96 hand-typed skills and 335 aliases in a
flat list. Anything absent is invisible to the entire system; new skills require editing
JSON; React does not imply JavaScript; and nothing records *why* those 96.

**The corpus defines the vocabulary, not a person.** Four layers:

1. **Precision core (keep).** The existing taxonomy and PhraseMatcher stay as the exact,
   fast, trusted backbone. It is good code.
2. **Induction.** Mine candidate terms from the posting corpus: n-grams and noun phrases,
   filtered by document frequency and pointwise mutual information with role context;
   cluster surface variants by embedding similarity; canonicalise in cheap batched LLM
   passes with every decision logged. Target **96 → 300-500 skills, each with recorded
   provenance**.
3. **Semantic matching.** Embed skills and resume/repo spans in `pgvector` — already
   available inside the existing Supabase, so no new infrastructure — and match above a
   tuned threshold, with exact matches always taking precedence.
4. **Negation and context.** Window-based negation so *"not familiar with Python"* stops
   counting as evidence (D9).

Hierarchy falls out of corpus co-occurrence statistics: React implies JavaScript without
anyone hand-writing that edge.

#### Open findings for lane C — verify before the induction work

**L-1 · `C` reports 21.1% demand for backend developer — suspected false positive.**
*Found 2026-10-02, on the first real corpus (Naukri CC0, 859 India postings).* In the
backend-developer demand table, `C` ranks 9th at 21.1%, above `Git` and `CI/CD`. It is
plausible — Indian service companies do list C — but one posting in five naming C for a
backend role is high enough to suspect the extractor is matching a bare `C` where it
shouldn't, for example inside enumerations ("option C", "Plan C", "Annexure C"), degree
abbreviations, or a mangled `C#`/`C++` whose suffix was lost to the mojibake in this
corpus. The PhraseMatcher is longest-match-wins, so `C#` and `C++` should win *when the
suffix survives cleaning* — that is exactly the assumption to test.

Why it matters beyond one skill: a single-character canonical skill is the worst case for a
closed-vocabulary matcher, and `R` has the same shape. If these are over-matching, they
inflate their own demand *and* dilute every other skill's percentage, because demand is a
share of postings. Check `C` and `R` specifically against the raw `extract_text` of the
postings that matched, before any taxonomy expansion — expanding on top of a precision bug
would bake it in.

*Still present at 20.4% after the corpus grew to 1,442 postings (859 Naukri + 583 live
JSearch), so it is not an artifact of the small 2020 sample.*

**L-2 · Skills in the job TITLE are never extracted — a pure recall loss.**
*Found 2026-10-02.* Extraction runs on the description only
(`ingest.py` → `rec.text_for_extraction`). The title is stored and used to derive
`role_query`, then discarded as a skill source. A real example now in the database: a
posting titled **"JavaScript Frontend Developer"** has **zero** extracted skills, because
its description is pure company boilerplate that never names a technology. Another,
**"Cloud Solution Architects AWS /GCP /Azure"**, likewise contributes nothing.

Titles are unusually skill-dense — they are written to be scanned — so this is probably the
cheapest recall win available. 24 of 1,442 postings (1.7%) currently have no skills at all,
and those rows actively *dilute* every demand percentage: they inflate the denominator
while counting toward no skill. The fix is to extract from title + description, likely
weighting a title mention at least as strongly as a body mention. Worth measuring the
before/after as part of experiment **E3**.

### 9.3 Architecture

```
                    ┌──────────────── EVIDENCE VERIFICATION ENGINE ────────────────┐
  Resume PDF ──────►│  extract claims ──► verify ──► tier ──► confidence ──► verdict│
  GitHub handle ───►│      ▲                 ▲                                      │
  Alt. evidence ───►│      │                 │                                      │
                    └──────┼─────────────────┼──────────────────────────────────────┘
                           │                 │                    │
                     taxonomy (induced)   GitHub API        verification record
                           ▲              trees/manifests/         │
                           │              commits/languages        │
                    posting corpus ──► demand ──────────┐          │
                    (dataset + live API)                ▼          ▼
                                            ┌────────────────────────────────┐
                                            │  SEEKER            RECRUITER   │
                                            │  gaps, roadmap     verify a    │
                                            │  fit, profile      candidate   │
                                            └────────────────────────────────┘
```

One engine, one verification record, two presentations. Preserved unchanged: Supabase
auth with JWKS, RLS-scoped storage, the two-tier trust model in `core/db/store.py`, upload
safety, rate limiting.

### 9.4 Data design

New tables: `repo_evidence` (cached per repo+SHA — file tree digest, manifests,
authorship, language bytes), `skill_evidence` (claim → tier, confidence, verdict,
provenance), `taxonomy_terms` (induced skills with provenance and embedding), plus
`verification_coverage` fields on saved analyses. Existing `postings` / `skills` /
`posting_skills` / `saved_analyses` keep their shape; `pgvector` is enabled on the
existing project.

### 9.5 Technology decisions

| Choice | Rationale |
|---|---|
| GitHub REST (trees, contents, commits) — **no cloning** | Whole file listing in one call; no compute, no storage, no code execution |
| `pgvector` in the existing Supabase | Semantic matching with zero new infrastructure |
| Frozen public dataset + live job API | Reproducible research corpus, plus live data for the demo |
| Keep spaCy PhraseMatcher as precision core | Already good; only add around it |
| Groq LLM, retained with template fallback | Free tier, existing prompt engineering, proven degradation path |
| **Rejected: Tree-sitter / AST analysis** | ~20% more signal for several times the engineering and compute. Documented as future work — a strength in the report, not an omission |
| GitHub OAuth `repo` scope, opt-in | The only way to verify private work; derived signals stored, never contents (FR-39, FR-42) |
| Local evidence scanner CLI (Python, ~300 LOC) | Covers work code that can never be shared with a third party — a case OAuth cannot reach |
| **Rejected: Naukri scraping** | Undocumented API, hand-refreshed fingerprints, already broke once (`92cd011`) |

### 9.6 Voice and persona

**The engine is clinical. The interface has a voice.** Rigour lives in the numbers;
personality lives in the framing around them. These are separated *technically*, not just
by convention:

- **Engine / API / paper:** `VERIFIED`, `WEAK`, `ATTESTED`, `UNVERIFIABLE`,
  `CONTRADICTED`. Fixed, testable, never cute.
- **Display layer:** a swappable vocabulary map (`frontend/src/voice.js`) that renders
  those verdicts for humans. Unit-tested for completeness — every verdict must have a
  rendering — and swappable for a formal register on the recruiter surface.

That separation is what lets the product have character without an examiner ever being
able to say the science got cute.

**Register: a good coach.** Not a cheerleader, not a compliance officer. Dry, direct, on
the candidate's side, never flattering.

**Rules:**
1. Never joke about a verdict that touches someone's integrity. CONTRADICTED is stated
   plainly and always offers the legitimate explanation first.
2. Be wry about *the market*, never about *the user*.
3. No manufactured enthusiasm. A high score earns understatement, not confetti.
4. Voice lives in headings, empty states, transitions, loading copy, milestones, and the
   roadmap's framing. **Never** in numbers, verdicts, provenance, or recruiter output.
5. The recruiter surface runs the formal vocabulary. Different audience, same engine.

**Central metaphor — "receipts".** Exactly what the system produces, instantly understood,
and it gives every piece of copy a spine: *skills with receipts*, *no receipts found*.

| Moment | Illustrative copy |
|---|---|
| Empty GitHub | "Nothing to verify yet. That's not a mark against you — it's a blank page. Here's how to fill it." |
| Contradicted | "You list Docker. We went through 23 repos and didn't find a single Dockerfile. Either it's private, or it's aspirational." |
| Hidden strength | "You've been using Redis in three projects and never told anyone. Put it on the resume." |
| High verified score | "Verified 81%. Most of what you claim, you can prove. That's rarer than it should be." |
| Roadmap item auto-verified | "You said you'd learn Docker. There's a Dockerfile in `api-service` now. Gap closed." |

### 9.7 The return loop

Gap analysers are read-once products. The verification engine is what makes a genuine
loop possible — built on real progress rather than manufactured engagement.

**The core loop — a roadmap that verifies itself:**

1. The roadmap says: close your Docker gap by containerising a service.
2. The candidate does the work and pushes it.
3. On the next visit the engine re-verifies, finds a `Dockerfile` in a repo they authored,
   and closes the gap **automatically — no self-reporting, no ticking a box**.
4. Verified readiness rises, attributable to a specific commit.

**No other roadmap tool can do this**, because none of them have an evidence layer — they
must ask the user whether they finished. This is the strongest argument that the
verification engine is not merely a research device but the thing that makes the product
work as a product.

Supporting returns, all honest:

- **"Since you were last here"** — new commits detected, skills that changed tier, gaps
  that closed (FR-46).
- **Market drift** — "Docker demand in your target role rose 6% this month," from the live
  feed (FR-16).
- **Verified-readiness timeline** — `saved_analyses` already stores the history; it only
  needs plotting (FR-47).
- **Milestones, lightly** — first verified skill, first gap closed by real code. Earned,
  never awarded for logging in (FR-48).
- **Shareable verified profile** — an external reason to keep it current (FR-49).

**Explicitly rejected:** visit streaks, points, activity badges, daily check-ins,
notification nagging. A verification product's credibility *is* its value; manufactured
engagement would spend it.

## 10. Edge cases and failure modes

*Explicitly requested. This section doubles as a report chapter and pre-empts the
questions an examiner will ask.*

| # | Case | Handling |
|---|---|---|
| EC-1 | **Empty or near-empty GitHub** (the majority of Indian students) | Coverage reported as low; all claims UNVERIFIABLE; the product still delivers gap analysis and roadmap. Never penalised. |
| EC-2 | No GitHub account at all | Claimed readiness only, with coverage = 0% stated plainly; alternative evidence offered (FR-12) |
| EC-3 | **Work is in private repos** | Three paths: OAuth `repo` scope (FR-39), the local evidence scanner for code that can never be shared (FR-40), or self-attestation at tier EA (FR-41). Never penalised, and the contradiction safety rule prevents a false accusation |
| EC-4 | **Group project — who wrote it?** | Commit authorship (FR-6) gives authorship share; below threshold, evidence is capped at E2 |
| EC-5 | **Tutorial follow-along repos** | Flagged heuristically (single bulk commit, no iteration, boilerplate-dominant tree) and down-weighted; documented as a known limitation |
| EC-6 | Forked repos | Excluded from evidence (already correct in current code) |
| EC-7 | Monorepo with many manifests | All manifests parsed; skills deduplicated per repo |
| EC-8 | Vendored `node_modules` / committed deps | Path-based exclusion list applied to file trees |
| EC-9 | Unverifiable skill classes (communication, leadership) | Marked NOT-VERIFIABLE-BY-DESIGN — a category, not a failure |
| EC-10 | Skill used long ago, never since | Recency weighting (FR-14); surfaced as stale rather than hidden |
| EC-11 | GitHub rate limit exhausted | Cached evidence served; explicit partial-result status (never a silent zero) |
| EC-12 | Very large profile (100+ repos) | Ranked by recency and size; top N analysed; N disclosed in the report |
| EC-13 | Scanned/image-only resume PDF | Detected and rejected with a clear message (exists today; deduplicate D7) |
| EC-14 | Resume in an unexpected format/language | Out of scope, stated explicitly |
| EC-15 | LLM unavailable or malformed output | Template fallback (exists) plus structural validation (D14) |
| EC-16 | Live job API down or rate-limited | Frozen corpus continues to serve; freshness banner shown |
| EC-17 | Role absent from corpus | Nearest roles offered rather than an empty result |
| EC-18 | Skill in taxonomy but absent from corpus | Excluded from demand; never silently zero-weighted |
| EC-19 | Candidate disputes a CONTRADICTED verdict | Provenance is inspectable; manual override recorded and shown as such |
| EC-20 | Supabase email confirmation delayed during a live demo | Pre-provisioned demo accounts in the rehearsal checklist |
| EC-21 | Private-repo consent granted, then revoked | Derived signals expire; affected tiers visibly drop with an explanation (FR-43) |
| EC-22 | Local scanner digest tampered with | Digests are signed; unsigned or invalid digests are rejected outright |
| EC-23 | Attested private skill shown to a recruiter | Rendered as ATTESTED, never as VERIFIED — the recruiter sees exactly what was and wasn't checked |
| EC-24 | **Roadmap auto-verification false positive** — a `Dockerfile` arrives via a project template, not learning | Requires verified authorship plus non-trivial content; a template-shaped commit does not close a gap |
| EC-25 | **Candidate games the self-verifying roadmap** — pushes hollow code to farm verifications | Authorship, iteration pattern, and content-substance checks; included deliberately in Dataset C's adversarial surface |

---

# PART IV — RESEARCH

## 11. Contributions

1. **Primary — evidence-tiered claim verification.** A tiered model that distinguishes
   self-authored assertion from tool-produced artifact, and separates *unverifiable*
   from *contradicted*. Claim: evidence-weighted readiness is measurably more accurate
   than claim-only readiness.
2. **Secondary — corpus-induced open-vocabulary taxonomy.** Replacing a hand-curated
   list with an induced, provenance-tracked one, measured by coverage and extraction
   recall.
3. **Tertiary — evidence-conditioned guidance.** Roadmaps constrained to what evidence
   justifies, with every recommendation citing its gap — and closing themselves when the
   evidence arrives (§9.7).
4. **Supporting — zero-disclosure verification.** Private and non-shareable work is
   verified through derived signals and locally-produced signed digests, so a claim can be
   substantiated without revealing the artifact that substantiates it (FR-39→FR-43). This
   is the honest answer to the fact that a candidate's best work is often the work they
   are not allowed to show.

## 12. Evaluation

*(Written for hand-off; the owner flagged this as the unclear part.)*

**The unit of judgement is one claim:** *this resume asserts skill X — is X actually
demonstrated in this person's public artifacts?* Label: demonstrated / not demonstrated /
undeterminable. Tedious, not difficult — which is why it suits four extra people.

**Dataset A — planted claims (N=60), exact ground truth.** Pick a real public GitHub user
with ≥10 non-fork repos; two annotators independently determine their true skill set, a
third adjudicates; construct a *fictional* person's resume mixing true skills with
deliberately planted false claims; record the known label per claim. Because the false
claims are planted, precision and recall are computable without annotator noise.

**PREREQUISITE before Dataset A is labelled: measure channel-map recall.**
*Added 2026-10-02 from the first real profile.*

Run the evidence collector over the candidate profiles, parse every fetched
manifest, subtract the packages `core/evidence/channels.py` already knows, and
rank what remains by how many manifests contain it. Fix the gaps that ranking
exposes **before** labelling begins.

Why this comes first. On the first real profile the map recognised 20 of 93
declared packages, and one gap — `groq` in 12 manifests, with langchain/openai
appearing in none — single-handedly made an LLM-heavy candidate read
`UNVERIFIABLE` for Large Language Models. Had that profile been labelled first,
the error would have entered Dataset A as ground truth, and every confidence
constant tuned against it would have been **fitted to a hole in the map rather
than to reality**. Collection effort is not the lever here: ranking manifests
better and raising the per-repo cap changed nothing on that profile. Full
measurement in `docs/baselines/manifest_coverage_2026-10-02.md`.

**Dataset B — real pairs (N=40), external validity.** Real consenting resume + GitHub
pairs from classmates and seniors, anonymised by script. Two annotators label each claim
independently; **Cohen's κ** reported; disagreements adjudicated. *The consent form and
anonymisation procedure become a report subsection — a genuine ethics contribution.*

**Dataset C — adversarial (N=30).** Deliberately inflated resumes designed to fool the
system. Measures detection rate *and* documents the failure modes. "We attacked our own
system and here is where it broke" is the most viva-proof section a report can contain.

| ID | Question | Design | Metric |
|---|---|---|---|
| **E1** *(primary)* | Does evidence verification beat claim-only? | Same pipeline, verification on/off, Datasets A+B | Precision / recall / F1; Kendall τ vs. ground-truth gap ranking |
| **E2** | Which signals matter? | Ablate file tree, manifests, authorship, language stats, recency | Δ F1 per removed signal |
| **E3** | Does induced vocabulary beat the 96-skill list? | Closed vs. induced + semantic layer | Extraction precision / recall; corpus coverage |
| **E4** | Can the system be fooled? | Dataset C | Detection rate; failure taxonomy |
| **E5** *(secondary)* | Do evidence-conditioned roadmaps help? | 3 annotators rubric-score, blind to engine | Mean score; inter-rater agreement |

Every experiment runs by one command against the frozen corpus (NFR-5).

---

# PART V — EXECUTION

## 13. Team structure

| Lane | Owner | Scope | Interface contract |
|---|---|---|---|
| **A — Verification engine** *(thesis core)* | **Utkarsh** | Evidence tiers, confidence model, verdicts, scoring rework, architecture, paper lead | Publishes `verify_claims()` / `score_gap()`; all lanes consume |
| **B — Market corpus** | Member B | Dataset ingestion, live API, demand single-source-of-truth + parity test, role expansion | Writes only via `backend/ingest.py` |
| **C — Taxonomy & extraction** | Member C | Corpus induction, `pgvector` semantic layer, negation, hierarchy | `SkillExtractor.extract()` signature stable |
| **D — Role Fit, API health & private evidence** | Member D | Real listings, endpoint consolidation, fit↔readiness reconciliation, close D15 test gaps, **the local evidence scanner CLI** (FR-40) | Owns `/role-fit`; deletes `/role-fit-direct`; scanner emits a documented digest format |
| **E — Surfaces, voice & tooling** | Member E | Seeker UI, recruiter view, provenance display, **the voice layer** (§9.6), return-loop surfaces, one-command setup, annotation tool | Consumes API only |

**Annotation is shared five ways** — ~26 items each across Datasets A/B/C. Deliberate:
every member gets first-hand contact with the research question they will be examined on.

## 14. Increments

Each increment has a **hard handoff one week before the mentor review**.

### Increment 1 — mid-Oct 2026 · *Honest foundations*
- **B:** Real corpus ingested and serving demand; synthetic generator demoted to fixtures (FR-15, FR-20)
- **E:** One-command setup incl. migrations; README corrected (NFR-6, D16, D17, D18)
- **D:** `/role-fit-direct` deleted; duplicate heuristics removed (D7, D11)
- **A:** Evidence model specified; claim-only baseline instrumented so every later gain is measurable
- **Show:** demo on real postings + written thesis statement
- **Exit:** no invented number reaches the UI; clean clone → working demo

### Increment 2 — mid-Nov 2026 · *Verification engine v1*
- **A:** File trees, manifest parsing, language stats, commit authorship (FR-1→FR-8); tiers live
- **A:** Confidence + verdicts replace the set union at `scorer.py:67` (FR-9, FR-10, D1)
- **C:** Taxonomy induction v1 — 96 → 300+ with provenance (FR-18)
- **E:** Voice layer scaffolded now, not bolted on later — verdict→copy mapping with its completeness test (FR-44)
- **E:** Annotation tool ready; protocol dry-run on 5 items
- **Show:** **claimed vs. verified readiness, side by side, on the owner's own resume** (O6)
- **Exit:** evidence provably moves the score and the movement is explainable

### Increment 3 — mid-Dec 2026 · *Honesty, private evidence, second pillar*
- **A:** UNVERIFIABLE/CONTRADICTED separation + **contradiction safety rule**, coverage metric, recency weighting (FR-11, FR-14)
- **A:** Private evidence — OAuth `repo` scope, attestation tier EA, zero-disclosure storage, revocation (FR-39, FR-41→FR-43)
- **A/E:** Alternative evidence intake (FR-12); edge cases EC-1→EC-9 and EC-21→EC-23 handled explicitly
- **C:** Semantic layer + negation handling (D9)
- **D:** Role Fit on real listings; endpoints consolidated; reconciled with readiness (FR-28→FR-30)
- **D:** Local evidence scanner CLI shipped with a documented, signed digest format (FR-40)
- **E:** Provenance UI — click a skill, see the file; `extras` surfaced (FR-13, D13)
- **E:** Voice applied across the seeker surface (§9.6)
- **All:** Dataset A complete (60 items)
- **Show:** the empty-GitHub and private-repo cases handled fairly, plus live-listing Role Fit
- **Exit:** no honest candidate can be falsely contradicted

### Increment 4 — mid-Jan 2027 · *Evaluation and the loop*
- **All:** Datasets B and C complete; κ computed
- **A:** E1–E5 executed; results tables generated by script
- **A:** Evidence-conditioned roadmap + structural validation (FR-25, FR-26, D14)
- **A:** **Self-verifying roadmap** — gaps close from real commits, with the anti-gaming checks (FR-45, EC-24, EC-25)
- **E:** Recruiter surface with the formal vocabulary (FR-31→FR-33)
- **E:** "Since you were last here" change detection (FR-46)
- **Show:** the results — **and a gap closing itself from a real commit.**
- **Exit:** a number exists answering "does this help, and by how much"

### Increment 5 — mid-Feb 2027 · *Paper and report*
- **A:** Paper draft — related work, method, results, limitations
- **All:** Report chapters, each member covering their own lane
- **D:** D15 test gaps closed; suite green including a JWKS-path test (NFR-9)
- **E:** Verified-readiness timeline, milestones, shareable verified profile (FR-47→FR-49)
- **Show:** the paper draft

### Increment 6 — March 2027 · *Ship*
- Demo rehearsed end to end three times, including failure paths
- Report finalised, paper submitted, viva drilled per lane
- **Show:** the finished thing

## 15. Testing strategy

| Level | Scope | Cadence |
|---|---|---|
| Unit | Scoring maths, tier assignment, manifest parsers, extraction | Every change |
| Integration | Endpoints incl. role-fit and JWKS paths (closes D15) | Every increment |
| Contract | Python↔SQL demand parity (closes D4); GitHub API response shapes | Every increment |
| Fixture | Golden repo fixtures so verification is testable without network | Increment 2 onward |
| Acceptance | The §3 "would I use this?" table, run against the owner's real resume | Every increment |
| Voice | Every verdict has a rendering; engine names never leak into the UI and copy never leaks into the API (§9.6) | Every change |
| Scanner | Digest signing, tamper rejection, and "no file contents in the payload" asserted in a test | Increment 3 onward |
| Adversarial | Dataset C, including roadmap-gaming attempts (EC-25) | Increment 4 |
| Demo rehearsal | Clean clone → full journey, timed | Every increment |

⚠️ **Standing hazard:** `pytest` truncates the live Supabase `postings` table. Re-seed
from `backend/` after any full run, per the project memory note, before demoing anything.

## 16. Risk register

| Risk | L | I | Mitigation |
|---|---|---|---|
| A member goes quiet for a whole increment | H | M | Lanes are independent; each "Show" depends on **A** plus at most one other lane |
| GitHub rate limits during a live demo | M | H | 24 h evidence cache (NFR-3); pre-warmed demo profiles |
| Manifest→skill mapping is noisy | M | M | Start with top ~200 packages per ecosystem; measure and report coverage honestly |
| **Verification turns out not to help** | L | H | A publishable negative result. E2's ablation explains why; honesty beats a fabricated win |
| Annotation stalls | M | H | Dataset A is fully self-serve and needs no external consent; it alone supports E1 |
| Semantic layer underdelivers | M | L | Layers 1–2 ship independently and already answer "why only 96" |
| Live job API changes | M | L | Frozen corpus carries every research claim; live feed is demo polish |
| **A false CONTRADICTED verdict on an honest candidate** | M | H | The contradiction safety rule (§9.1); coverage always shown; provenance always inspectable; dispute path EC-19 |
| Voice reads as unserious and costs credibility | M | M | Voice is confined to the display layer, absent from verdicts and recruiter output, and reviewed against §9.6's rules each increment |
| Self-verifying roadmap is gamed | M | M | Authorship, iteration and substance checks; attacked deliberately in Dataset C (EC-25) |
| Private-evidence handling leaks something it shouldn't | L | H | Derived signals only; scanner tested to prove no file contents are transmitted; revocation path (FR-43) |
| Scope creep returns | H | H | §5 is frozen. Anything not carrying an FR-ID waits until April |

## 17. Deliverables

- [ ] Working system — both surfaces, real data, one-command setup
- [ ] Local evidence scanner CLI with a documented digest format
- [ ] Three annotated datasets (A: 60, B: 40, C: 30) with κ reported
- [ ] Five experiments with reproducible results tables
- [ ] Research paper
- [ ] Project report with per-lane chapters
- [ ] Rehearsed demo
- [ ] Per-member viva preparation

## 18. Verification

**Per change:** `cd backend && venv/Scripts/python.exe -m pytest tests/ -q` stays green;
re-seed afterwards (§15).

**Per increment:**
1. Clean clone into a temp directory; follow the README exactly; reach a working demo
   with no undocumented step.
2. Run the experiment scripts; confirm results regenerate unattended.
3. Walk the full journey: sign in → role → resume → GitHub → analyse → inspect provenance
   → roadmap → save → Role Fit on a live listing → recruiter view.
4. Sign in as a second user; confirm the first user's saved analysis is invisible.
5. **Run the owner's own resume through it and check the findings by hand** (O6).

**Before the viva:** each member explains their lane's design decisions and defends one
arbitrary constant in it. The audit found several (D2, D3, D6); each gets empirical
justification or becomes a documented limitation.

---

## 19. First actions

1. Approve this plan; freeze §5.
2. Start Increment 1 — the corpus swap unblocks every downstream claim.
3. Pick and freeze the static dataset and the live API.
4. Hand lanes B–E to the four members as standalone briefs.
5. Take §2 and §11 to the mentor at the October review.
