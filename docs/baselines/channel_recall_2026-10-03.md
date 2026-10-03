# Channel-map recall — cohort measurement, 2026-10-03

**This satisfies the hard prerequisite in `docs/PLAN.md` §12: Dataset A must not be
labelled until the channel map's recall is known.** Supersedes the n=1 finding in
`manifest_coverage_2026-10-02.md`, which this both confirms and corrects.

Reproduce with:

```bash
cd backend
python scripts/measure_channel_recall.py --frame population
python scripts/measure_channel_recall.py --frame dense
```

The cohorts are frozen in `backend/scripts/recall_cohort_population.txt` and
`recall_cohort_dense.txt`; the human judgements are in `backend/scripts/recall_labels.py`,
one line per package with its reason. Collection runs at `/analyze`'s own budget
(150 requests, 25 repos), so the result describes the map as the product actually
exercises it.

## Why this had to come first

The previous measurement found that on one profile the map recognised 20 of 93
declared packages, and that a single gap — `groq` in 12 manifests — made an
LLM-heavy candidate read `UNVERIFIABLE` for Large Language Models. Had that
profile been labelled first, the error would have entered Dataset A as ground
truth, and every confidence constant tuned against it would have been fitted to a
hole in the map rather than to reality.

That was n=1, and the profile was the author's own — the same profile the `groq`
fix had already been fitted to. This measurement uses 48 other people.

## Method

**Two sampling frames**, because one frame answers the wrong question.

| Frame | Query | n | What it is for |
|---|---|---|---|
| `population` | `location:India repos:>=10`, newest accounts first | 32 | who the product is **for** |
| `dense` | `location:India repos:>=20 followers:>=20`, most repos first | 16 | who Dataset A will be **drawn from** |

Both frames are biased — self-reported location, follower count as a proxy for
activity — and both biases are written down rather than corrected. A stated bias
beats an unstated convenience sample. The author's own profile is measured
separately and never mixed into either cohort: the map was already fitted to it, so
counting it would inflate the result.

**Three numbers, because only one of them is honest alone.**

1. **Declaration coverage** — the share of declared *(package, repo)* pairs the map
   recognises. Fully automatic and systematically pessimistic: most unrecognised
   packages are transitive dependencies that must never map to a skill. A low
   coverage number is not by itself a defect.
2. **Map recall** — of the packages that *should* have been recognised, how many
   were. Needs human judgement, which is why the judgements are in a reviewable
   file with a recorded reason each.
3. **Blind spots** — declarations where an unmapped package was its skill's *only*
   signal in that repo. **This is the only number that can change a verdict**, and
   therefore the only one that can put a wrong label into Dataset A.

Recall is counted over *declarations*, not distinct names: a package in twelve
repos misleads twelve times and a package in one misleads once. Labelling stops at
**3 declarations across a cohort**; below that sits a tail of ~250 names seen once
or twice whose labels could not move any number.

## Result

| | population | dense | author (reference) |
|---|---|---|---|
| Profiles | 32 | 16 | 1 |
| Repos | 349 | 139 | 23 |
| Repos with a manifest | 90 (26%) | 56 (40%) | 23 (100%) |
| Declarations | 1,118 | 586 | 304 |
| **Declaration coverage** | **36.9%** | **20.6%** | **44.7%** |
| **Map recall (judged head)** | **100%** | **100%** | **100%** |
| **End-to-end recall** | **86.2%** | **91.7%** | **82.9%** |
| Skills evidenced | 265 | 110 | 25 |
| …of them at E3 DECLARED | 126 | 29 | 17 |

### Before and after, population frame

Each row is a fix this measurement motivated, measured in order.

| | Declarations | Coverage | Map recall | End-to-end recall |
|---|---|---|---|---|
| As found | 1,305 | 20.9% | 72.8% | 67.4% |
| After the parser fix and the first five specs | 1,118 | 33.5% | 100% | 88.9% |
| After the mobile specs and the label corrections | 1,118 | **36.9%** | **100%** | **86.2%** |

The parser fix accounts for the whole drop in declarations — **187 pseudo-packages
removed without losing a single real one** — since mapping a package does not change
how many were declared.

End-to-end recall *fell* between the last two rows, from 88.9% to 86.2%. That is the
number becoming more honest, not worse: each fix promoted rarer packages into the
judged head, and judging them found further taxonomy gaps that had been sitting
below the threshold uncounted.

## What the measurement found

### 1. An empty repository aborted an entire profile

GitHub answers **409 Conflict** for a repository with no commits. That escaped the
collector as an `HTTPError`, and `/analyze` catches it by falling back to *no
evidence at all*. **Five of the first eighteen profiles collected nothing for this
reason.** A candidate who had once created a repo and never pushed to it lost every
verification they had.

Empty repos are among the most common things on GitHub, so this is now a fact
rather than a failure: 404 and 409 are recorded as `definitive_misses`, the repo is
skipped, and the profile is **not** marked partial — nothing went wrong, so
suppressing `CONTRADICTED` for it would be wrong too. A tree fetch that fails for
any *other* reason still stops collection, because "nothing there" and "we could
not look" must never be the same thing. Proven by
`tests/test_evidence_github.py::test_an_empty_repo_is_skipped_without_losing_the_rest_of_the_profile`
and its counterpart.

This was the single most valuable thing the measurement found, and it was invisible
at n=1.

### 2. The coverage metric was lying to itself

`parse_pyproject_toml` scraped every `key = value` line, so `name`, `version`,
`description`, `edition`, `codegen-units` and `harness` all arrived looking like
packages — **14 of the 60 most frequent "unrecognised" names**, 187 declarations in
all. They could never cause a false verification (no channel lists a package called
`version`), but they inflated the denominator, so coverage read far worse than it
was and invited map work that would have fixed nothing. The parser is now
section-aware via `tomllib`, falling back to the old scrape only for TOML that will
not parse. `parse_composer_json` had the same problem with `php` and `ext-*`
platform constraints.

### 3. The map's real gaps were two whole ecosystems

Ten specs were extended, each justified by frequency in the cohort and by the
package being unambiguous for its skill:

| Spec | Added | Why it mattered |
|---|---|---|
| TypeScript | `typescript`, `ts-node`, `tsx` | declared in 16 repos across 7 profiles |
| React | `react-router-dom`, `lucide-react`, `@vitejs/plugin-react`, `react-icons`, `framer-motion`, `react-scripts` | React has **no** language or file channel; packages are all it has |
| SQL | `sqlalchemy`, `flask-sqlalchemy`, `alembic`, `knex`, `sequelize`, `typeorm` | an ORM is direct evidence of relational work |
| Rust | `serde`, `serde_json`, `tokio`, `clap`, `anyhow`, `rayon`, `thiserror`, `tracing`, `tracing-subscriber` | raises Rust from E2 PRESENT to E3 DECLARED |
| Next.js | `eslint-config-next` | |
| Tailwind CSS | `tailwind-merge` | |
| **Android Development** | `appcompat`, `appcompat-v7`, `recyclerview`, `cardview`, `constraintlayout`, `core-ktx`, `espresso-core`, `material`, `lifecycle-runtime-ktx`, `activity-compose`, `gradle` | the map had **no** package channel at all |
| **React Native** | `react-native-screens`, `react-native-safe-area-context`, `react-native-gesture-handler`, `metro-react-native-babel-preset`, `android-jsc`, `android-jsc-intl` | |
| Firebase | `google-services`, `firebase-database`, `firebase-auth`, `firebase-firestore` | |
| Java | `gson`, `retrofit` | |

**The `dense` frame is a different ecosystem from the `population` frame.** The
population frame is web; the dense frame is substantially Android, Kotlin and React
Native, and the map had almost nothing for any of them. Coverage there went
10.5% → 20.6% on that discovery alone. Dataset A will be drawn from profiles like
these, so a map tuned only on web profiles would have been tuned on the wrong
people.

**The policy for adding a package**, now that there is one: map it when it is
*unambiguous* for its skill, even if another channel already fires — a manifest hit
raises the tier from E2 PRESENT to E3 DECLARED, so it changes confidence, not just a
coverage percentage. Do not chase the tail to move the metric.

`prisma` was deliberately **not** mapped under SQL: it also drives MongoDB, so it is
ambiguous, and the whole point of the tier model is that E3 means something.

### 4. Three fixes that would have been false verifications

Each was caught by attempting the fix and looking at what it would have claimed.

- **`beautifulsoup4` → Web Scraping.** The taxonomy files "Web Scraping" as an
  **alias of Selenium**. Mapping it would have verified *Selenium* for candidates
  who have never used a browser driver. `canonicalize()` returning something is not
  enough; it has to return the skill that was asked about. The measurement script
  now checks this, and `tests/test_channel_recall.py` pins it.
- **`bcrypt`, `bcryptjs`, `jsonwebtoken`, `pyjwt`, `passlib` → Authentication.** The
  only taxonomy entry that fits is `Cybersecurity`, which `channels.py` marks
  unverifiable by design (EC-9) — "a domain, not a declarable artifact; concrete
  tools would need their own taxonomy entries". Attaching packages there would have
  quietly turned a concept into something checkable.
- **`kotlin-gradle-plugin`, `kotlin-stdlib*` → Kotlin.** Kotlin is not in the
  taxonomy, and the map currently treats the Kotlin *language* as evidence of
  "Android Development" — a conflation, since Kotlin is also a server-side language.
  Reported as lane C's gap rather than folded into Android.

### 5. Four of my own judgements were wrong

An invariant test — *no package the map recognises may be labelled transitive,
not-a-skill or a parser artifact* — immediately caught four packages I had judged
noise while the map already credited them: `nodemon` (Node.js), `huggingface-hub`
(Hugging Face), `pytest`/`vitest`/`jest` (Unit Testing), plus `nltk` and `spacy`
labelled "no canonical entry" when both are in the taxonomy. Labels corrected.

**Open question for the mentor, not silently changed:** the map grants **E3
DECLARED** — the strongest unauthored tier — for a `pytest` line in a requirements
file. Test runners often arrive with a template. The file-tree half of that spec (a
`tests/` directory) is the stronger signal.

### 6. Two thirds of this population's repos declare nothing at all

Only **90 of 349 repos (26%)** in the population frame contained a parseable
manifest; in the dense frame, 56 of 139 (40%); on the author's profile, 23 of 23.
DSA-solution repos, static HTML pages and course work declare no dependencies, so
for most of this population the MANIFEST channel is simply unavailable and
FILE_TREE plus LANGUAGE carry everything.

Consequences, all of which belong in the report:

- E3 DECLARED is reachable for a minority of repos, so **E2 PRESENT is the working
  ceiling for most candidates** and the confidence constants must not assume
  otherwise.
- `verification_coverage` will be structurally low for this population. It was
  designed exactly for this — a low verified score must never read as dishonesty —
  and this is the number that proves the design was necessary rather than defensive.
- Dataset A's candidate profiles must be screened for *at least some* manifests, or
  the dataset will measure the file-tree channel and nothing else.

## The remaining blind spots are all lane C's

After the fixes, **map recall on the judged head is 100% in both frames**: there is
no miss left that the channel map could fix. Every surviving blind spot is a
taxonomy problem. Combined across both frames:

| Missing skill | Declarations | Packages | What lane C needs to do |
|---|---|---|---|
| **Authentication** | 20 | `bcrypt`, `bcryptjs`, `jsonwebtoken`, `pyjwt`, `passlib` | add the skill; `Cybersecurity` is unverifiable by design and cannot host it |
| **Pydantic** | 15 | `pydantic`, `pydantic-settings` | add the skill |
| **Vite** | 14 | `vite` | add the skill |
| **Streamlit** | 10 | `streamlit` | add the skill |
| **Kotlin** | 8 | `kotlin-gradle-plugin`, `kotlin-stdlib`, `kotlin-stdlib-jdk7` | add the skill; stop treating the Kotlin language as Android evidence |
| **Web Scraping** | 5 | `beautifulsoup4` | **split from Selenium** — currently an alias, which is a false-verification risk |
| **Jupyter** | 4 | `jupyter`, `notebook` | add the skill (FR-3 already treats `*.ipynb` as a file signal) |
| **Zod** | 4 | `zod` | add the skill |
| **Prisma** | 3 | `prisma`, `@prisma/client` | add the skill |

Each one is a skill a real candidate declared and could claim on a resume, and
each is currently unverifiable however good the channel map gets. The `Web
Scraping`/`Selenium` conflation is the urgent one: it is not a missing skill but a
*wrong* one, and it is the only item here that could produce a false verification
rather than a missing one.

## Verdict on the prerequisite

**Satisfied.** The channel map is no longer the binding constraint on verification
recall — the taxonomy is. Dataset A labelling may begin, with two conditions:

1. **Screen candidate profiles for manifests.** A profile with no parseable manifest
   exercises one channel out of three.
2. **Do not label a claim for any skill in the lane C table above.** Those claims
   are unverifiable for a reason that has nothing to do with the candidate, and
   recording them as ground truth would repeat the exact mistake this prerequisite
   exists to prevent — one level further up.

## Ethics and data handling

**Only public data, through the official API.** Every request was a documented,
authenticated GitHub REST call — the repo listing, `git/trees`, `contents` for
manifests, and `contributors`. Nothing was cloned, no code was executed, and no
private, authenticated or deleted content was touched. What was retained is
aggregate: per-repo package names and counts. No source code, no file contents, no
personal details, no email addresses.

**The handles are not published.** This repository is public and the cohort is 48
real people, so `recall_cohort_population.txt` and `recall_cohort_dense.txt` hold
anonymous ids (`POP-01`, `DEN-01`). The id→handle mapping lives only in
`backend/data/recall_cohort_map.json`, which is gitignored, and the measurement
prints and writes the alias everywhere — the handle is used to call the API and
then dropped, so no output file can leak it.
`tests/test_channel_recall.py::test_the_committed_cohort_files_contain_no_real_handles`
keeps it that way.

**Reproducibility without the handles.** The sampling query is published in
`FRAMES`, so anyone can redraw an equivalent cohort with
`--frame <frame> --sample N` and re-derive the result from scratch. Whoever holds
the local mapping reproduces it *exactly*. This is the weaker of the two
reproducibility guarantees NFR-5 asks for, and it is the right trade: an exactly
reproducible number is not worth publishing a list of students' accounts with a
note about what their code does not contain.

**Why no consent was sought, and why Dataset B is different.** This measurement
asks a question about *our map* — "which declared packages does it fail to
recognise" — and reports only aggregate counts; no individual is described,
scored, or identified. Dataset B, which pairs a real resume with a real GitHub
account and produces a per-person judgement, is a different kind of study and
carries the written-consent and anonymisation procedure described in PLAN.md §12.
The dividing line is whether anything is concluded *about a person*.

## Also worth knowing

- **Request cost.** The one cohort measured entirely cold, `dense`, cost **386
  requests for 16 profiles** — about 24 each, against NFR-2's 150 per *analysis*.
  The author's 23-repo profile cost 83 alone, so the per-profile cost tracks repo
  count. `population` is not quoted as a cold number: half of it was already cached
  when the fix landed. Re-running any frame from the cache costs ~0, which is why
  every number above was re-derived without touching the API.
- **The measurement writes to `data/cache/recall/`,** never the demo cache, so it
  cannot evict or age what `scripts/prewarm_cache.py` warmed.
- **One profile can dominate a frequency count.** `docsify-cli` appeared 22 times in
  the dense frame, all from one account. The `profiles` column is reported next to
  `repos` for exactly this reason, and a one-profile package is never treated as a
  cohort-wide finding.
