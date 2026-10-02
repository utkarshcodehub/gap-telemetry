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

Measured on one real profile (23 repos, 36 manifests, 93 distinct packages):

| Missing skill | Manifests | Why it matters |
|---|---|---|
| **`streamlit`** | 8 | A mainstream Python app framework. Students build and ship with it constantly, and it is a genuine, claimable skill. |
| **`vite`** | 12 | The default modern front-end build tool. Present in essentially every recent React or Vue project. |

Both are *directly declared* dependencies — intentional choices, not transitive
noise. Adding them to the taxonomy is a precondition for the evidence engine
doing anything with them; once added, lane A supplies the channel entries.

**Request:** include both in the induced taxonomy, and treat "appears as a direct
dependency in many manifests" as a strong induction signal generally — it is
evidence of real use, unlike a term's frequency in job-posting prose.

## C-2 · `C` reports 21% demand — suspected extraction false positive

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

## C-3 · Skills in the job TITLE are never extracted

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
