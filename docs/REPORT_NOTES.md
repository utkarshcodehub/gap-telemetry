# Report notes

Findings that belong in the written report or the paper, recorded when they were
measured rather than reconstructed in February. Each entry says which chapter it
serves and what the evidence for it is.

Not a changelog — the git history is that. This is for results and decisions whose
*reasoning* would otherwise be lost, including the ones that are inconvenient.

---

## RN-1 · Only 26% of this population's repos declare any dependencies

**Chapters:** limitations; the evidence model's calibration; the defence of
`verification_coverage`.
**Evidence:** `docs/baselines/channel_recall_2026-10-03.md`, 488 repos across 48
real profiles in two sampling frames.

| Frame | Repos | With a parseable manifest |
|---|---|---|
| `population` (students, early-career) | 349 | 90 (**26%**) |
| `dense` (visibly active accounts) | 139 | 56 (40%) |
| the author's own profile | 23 | 23 (100%) |

DSA-solution repos, static pages and course work declare no dependencies. For
roughly three repos in four in the target population, **the MANIFEST channel does
not exist**, so E3 DECLARED is unreachable for reasons that have nothing to do
with the candidate's ability.

Three consequences, all of which are arguments the report should make rather than
caveats it should bury:

1. **E2 PRESENT is the working ceiling**, so the confidence constants were
   recalibrated to anchor "verified" at E2 with E3 as a bonus on top
   (`TIER_BASE`, 2026-10-03: E2 0.45→0.55, E3 0.65→0.70, E4 0.80→0.85). The tier
   ordering is strictly preserved. Pinned by
   `test_e2_alone_reads_as_verified_not_as_half_verified` and
   `test_e3_is_a_bonus_over_e2_not_a_different_league`.
2. **`verification_coverage` will be structurally low for this population**, and
   this is the finding that proves the metric was necessary rather than
   defensive. A system without it would report a low verified score for a
   competent candidate and let the reader infer dishonesty.
3. **Dataset A profiles must be screened for manifests.** A profile with none
   exercises one channel of three, so a dataset of such profiles would measure the
   file-tree channel and call it the evidence model.

**The honest reading, for the viva:** the single largest determinant of a
candidate's verified score in this population is not how good they are, it is
whether their work happens to live in an ecosystem that writes dependencies down.
That is a real limit on what artifact verification can claim, and the two-number
design (claimed vs verified, with coverage shown) is what keeps it from becoming a
misleading judgement about a person.

## RN-2 · A declared test runner is granted E3 DECLARED

**Status: open question for the mentor. Deliberately not changed.**
**Chapters:** evidence model, threats to validity; experiment E2's ablation list.

`core/evidence/channels.py` lists `pytest`, `vitest` and `jest` as MANIFEST
evidence for `Unit Testing`, which awards **E3 DECLARED — the strongest unauthored
tier** — for one line in a requirements file. A test runner frequently arrives
with a project template rather than by choice, and declaring it proves nothing
about whether tests were written. The file-tree half of the same spec (a `tests/`
or `__tests__/` directory) is the stronger signal, and the path that actually
evidences the skill.

Left in place because changing a tier rule on my own judgement, days before
Dataset A fixes the ground truth, is how a constant gets fitted to an opinion.
Two ways out, both planned:

- **Mentor review (October):** is a declared dev-tool dependency evidence of the
  practice it supports, or only of the project scaffold? The answer generalises
  past this one case — the same question covers linters, formatters and CI
  actions.
- **Experiment E2 (ablation):** add *"MANIFEST evidence for practice skills"* as
  an ablated signal, separately from MANIFEST evidence generally. If removing it
  does not cost F1, the rule was decoration and should go; if it helps, the
  objection above was wrong and the report says so.

The judgement is recorded in `backend/scripts/recall_labels.py` next to the
packages themselves, so whoever revisits it sees the reasoning in place.
