# Handoff — Lane C (taxonomy & extraction)

Findings from lanes A and B that land in lane C's scope. Each is something the
evidence engine cannot fix from its side, because the problem is upstream in the
skill vocabulary or the extractor.

Owner: Member C · Charter: `docs/PLAN.md` §9.2

---

## C-1 · Skills with no taxonomy entry can never be verified

**Impact: high. Blocks verification outright, not just recall.**

The evidence engine maps *canonical skills* to the artifacts that prove them
(`core/evidence/channels.py`). A skill absent from `skills_taxonomy.json` has no
canonical name, so it has no channel entry, so **no amount of evidence can ever
verify it**. It is invisible end to end: not extracted from the resume, not
counted in demand, not verifiable from code.

**UPDATED 2026-10-03.** The original n=1 list of two skills is now a measured list
of nine, from **48 real profiles** across two sampling frames — 488 repos, 1,704
declared dependencies. Full method and result:
`docs/baselines/channel_recall_2026-10-03.md`, reproducible with
`cd backend && python scripts/measure_channel_recall.py --frame population|dense`.

**This list is now the binding constraint on verification recall.** After lane A's
fixes, map recall on the judged head is **100% in both frames** — there is no
remaining miss the channel map can fix. Everything below needs the taxonomy.

| Missing skill | Declarations | Packages seen | Note |
|---|---|---|---|
| **Authentication** | 20 | `bcrypt`, `bcryptjs`, `jsonwebtoken`, `pyjwt`, `passlib` | The largest gap. `Cybersecurity` cannot host it — `channels.py` marks that entry unverifiable by design (EC-9), "a domain, not a declarable artifact". |
| **Pydantic** | 15 | `pydantic`, `pydantic-settings` | |
| **Vite** | 14 | `vite` | The default modern front-end build tool. |
| **Streamlit** | 10 | `streamlit` | A mainstream Python app framework students ship with constantly. |
| **Kotlin** | 8 | `kotlin-gradle-plugin`, `kotlin-stdlib`, `kotlin-stdlib-jdk7` | See C-4 — this one is also a conflation. |
| **Web Scraping** | 5 | `beautifulsoup4` | See C-4. **Do this one first.** |
| **Jupyter** | 4 | `jupyter`, `notebook` | FR-3 already treats `*.ipynb` as a file signal, so the channel is half-built. |
| **Zod** | 4 | `zod` | |
| **Prisma** | 3 | `prisma`, `@prisma/client` | Deliberately not mapped under SQL by lane A: Prisma also drives MongoDB, so it is ambiguous. |

All are *directly declared* dependencies — intentional choices, not transitive
noise. Once a canonical entry exists, lane A supplies the channel entry.

**Request:** include all nine in the induced taxonomy, and treat "appears as a direct
dependency in many manifests" as a strong induction signal generally — it is
evidence of real use, unlike a term's frequency in job-posting prose.

## C-4 · Two taxonomy entries are *wrong*, not missing — and one can produce a false verification

**Impact: highest in this document. A missing skill under-reports; a conflated one
can verify a skill the candidate never used.**

1. **`Web Scraping` is an alias of `Selenium`.** `canonicalize("Web Scraping")`
   returns `"Selenium"`. Lane A was about to map `beautifulsoup4` (5 repos, 4
   profiles) to the skill it names, which would have evidenced **Selenium** for
   candidates who have never touched a browser driver. The two are different
   skills: scraping with a parser is not driving a browser. **Split them.**

2. **The Kotlin language is treated as evidence of `Android Development`.**
   `channels.py` lists `languages=("Kotlin",)` under Android Development because
   Kotlin has no entry of its own. Kotlin is also a server-side language, so a
   Kotlin backend currently evidences Android development. Add `Kotlin`, then lane
   A will narrow the Android spec.

The general lesson for the induced taxonomy: an alias that merges two genuinely
distinct skills is worse than a missing skill, because the evidence engine will
confidently attribute one to the other. The measurement script now checks for this
(`classify()` rejects a target whose `canonicalize()` returns a *different*
canonical) and `backend/tests/test_channel_recall.py` pins the behaviour.

## C-5 · `C` reports 21% demand — suspected extraction false positive

*(Carried from the earlier finding, repeated here so lane C has one list.)*

In the backend-developer demand table, `C` ranks above `Git` and `CI/CD` at
~20–21%. Plausible for Indian service companies, but one posting in five naming C
for a backend role is high enough to suspect the matcher is firing on a bare `C`
inside enumerations ("option C", "Annexure C"), degree abbreviations, or a
mangled `C#`/`C++` whose suffix was lost.

Single-character canonical skills are the worst case for a closed-vocabulary
matcher, and `R` has the same shape. Over-matching inflates their own demand
*and* dilutes every other skill's share, because demand is a share of postings.
**Check `C` and `R` against the raw `extract_text` of the postings that matched,
before any taxonomy expansion** — expanding on top of a precision bug bakes it in.

## C-6 · Skills in the job TITLE are never extracted

Extraction runs on the description only; the title is used for `role_query` then
discarded as a skill source. A posting titled **"JavaScript Frontend Developer"**
has zero extracted skills, because its body is company boilerplate.

24 of 1,442 postings (1.7%) have no skills at all, and those rows actively
*dilute* every demand percentage: they inflate the denominator while counting
toward no skill. Titles are the densest skill text available, so this is likely
the cheapest recall win there is. Worth measuring before/after as part of
experiment **E3**.

---

## Lesson from lane A worth reusing

When extending the taxonomy, prefer **direct manifest dependencies** over prose
frequency as a signal of real use. Lane A's measurement found that a skill's
ecosystem often has many interchangeable vendors, and listing only the popular
aggregators misses the common case — `groq` appeared in 12 manifests on a profile
where `langchain` and `openai` appeared in none. The same breadth problem will hit
an induced taxonomy that learns only the most-mentioned term per concept.
