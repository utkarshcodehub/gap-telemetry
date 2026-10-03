# Mentor review — October 2026

One page. What changed, what was decided, and the four things most worth
challenging. Everything here is implemented and tested, not proposed.

**Project:** evidence-verified skill intelligence. *Every skill-gap tool gives one
number based on what you claim. We give two: what you claim, and what you can
prove.*

---

## 1. The problem we found in our own code

The project already compared a resume against market demand. But the "second
source" was not independent: `github_profile/fetcher.py` read each repo's **name,
description, topics and README** — all four written by the candidate — and ran the
same keyword matcher over them. It was the resume's claims in a different box.

Worse, the evidence label it produced never touched the score. Measured on five
fixed profiles, **GitHub moved the readiness number by +0.0 in four of five**. The
only case it moved (+6.8) was where GitHub revealed a skill the resume omitted.
**When GitHub *corroborated* a claim — the common case, and the entire point of
verification — it contributed exactly zero.** That is recorded as a regression test
and is the quantitative case for the whole project.

## 2. Market data is now real, and India-first

| | |
|---|---|
| Was | 500 synthetic postings with hand-typed skill probabilities (Python 0.92, RAG 0.22) |
| Now | **1,434 real Indian postings** — 859 Naukri (CC0, Q4 2020) + 575 live feed (Oct 2026) |

We evaluated a 124k-posting Kaggle LinkedIn corpus and **measured it at zero India
postings** — 3 apparent matches were *Madras, Oregon* and *India Hook, South
Carolina*, and 0 of 8,526 distinct locations name an Indian state. It is kept on
disk for extraction experiments only; migration `0003` makes the separation
structural so a US row cannot contaminate an India demand figure.

Evidence that the live feed earns its place: `ai ml engineer` demand now shows
**Large Language Models 52%, MLOps 31%, AI Agents 31%** — none of which can exist
in a 2020 corpus.

## 3. The evidence model, decided

Claims are graded by **how hard the signal is to fabricate**: resume text (E0) →
README prose (E1) → file-tree artifact (E2) → declared dependency (E3) → plus
verified commit authorship (E4). Verdicts: `VERIFIED`, `WEAK`, `ATTESTED`,
`UNVERIFIABLE`, `CONTRADICTED`.

Decisions taken, each with reasoning in `docs/EVIDENCE_MODEL.md` §8:

- **§8.1 `claimed_readiness` is resume-only.** It is the control condition; a
  baseline containing GitHub signal would credit the control with part of the
  treatment and understate our own effect.
- **§8.2 Confidence is additive with capped bonuses.** Multiplicative would let one
  absent signal zero out four present ones — and authorship data is frequently
  unavailable, which is *our* failure, not the candidate's.
- **§8.4 Self-attestation is excluded from verified readiness.** It is the one
  input a candidate controls; letting it raise a number called *verified* would
  make the word false.
- **§8.5 Coverage is the mean per-claim share of repos actually read.** The first
  version reported 100% while nine of twelve fetches had failed — useless as the
  gate against false accusations.
- **§8.6 / §8.7** Unclaimed-but-evidenced skills sit outside both numbers; every
  claim gets a verdict even when outside the role's demand basket.

## 4. The verdict we are deliberately not shipping yet

`CONTRADICTED` is the only output that could wrong an honest person. It is
**computed but switched off by default** (`REVEAL_CONTRADICTED_VERDICT=false`);
until Dataset A validates it, such a claim reports `UNVERIFIABLE` and the
suppression is recorded so the rule's hit rate can be measured *before* anyone
sees it.

Four independent gates: a two-skill allowlist (`Docker`, `Terraform`), published
infrastructure-as-code, enough repos and coverage, and a complete profile.

**This was wrong twice, and both corrections came from testing it on a real
profile** — the project author's, 23 repos:

1. Admitting CI workflows and PaaS deploy configs as "comparable infrastructure"
   was backwards. A `render.yaml` is a *buildpack deploy* — the mainstream
   alternative to containerising — so its presence argues **against** inferring
   anything from a missing Dockerfile. Narrowed to infrastructure-as-code only.
2. The original assumption "Docker use implies a committed Dockerfile" holds for
   professional repositories and **not for students**, who meet Docker in courses
   and internships and never containerise a personal project.

Result: the author's `Docker` claim went `CONTRADICTED` → **`UNVERIFIABLE`**, which
is the honest answer.

---

## Open questions — the four we would most like challenged

1. **Is the peer-context gate right, or now too strict?** Infrastructure-as-code
   only may suppress genuine contradictions. Dataset A should measure true vs
   false suppression before it is loosened.
2. **Should `claimed_readiness` really be resume-only?** It makes the comparison
   clean but means the baseline is *not* the number the product previously shipped.
3. **Is a two-skill allowlist too conservative to demonstrate the contribution?**
   If `CONTRADICTED` almost never fires, the headline feature may be invisible in
   the evaluation even if the mechanism is sound.
4. **Is a declared test runner evidence of testing?** The map grants **E3
   DECLARED** — the strongest unauthored tier — for a `pytest` line in a
   requirements file, where it often arrives with a project template. The same
   question covers linters, formatters and CI actions. Deliberately left unchanged
   rather than decided on our own judgement; it is also queued as an E2 ablation
   (RN-2 in `docs/REPORT_NOTES.md`).

### Resolved since this brief was written

5. **Channel-map recall was the binding constraint — it is not any more.**
   ~~On the author's profile the map recognised 20 of 93 declared packages, and
   one gap (`groq` in 12 manifests) alone made an LLM-heavy candidate read
   `UNVERIFIABLE`.~~ **Measured on 2026-10-03 over 48 other profiles** (488 repos,
   1,704 declared dependencies, two stated sampling frames): after ten spec
   extensions, **map recall on the judged head is 100% in both frames**. The
   binding constraint is now the **taxonomy** — nine skills real candidates
   declare have no canonical entry, and `Web Scraping` is an *alias of Selenium*,
   which would have produced a false verification. Handed to lane C.
   Full result: `docs/baselines/channel_recall_2026-10-03.md`.

   It also found that an **empty repository aborted an entire profile** (GitHub
   answers 409 for a repo with no commits) — five of the first eighteen profiles
   verified nothing — and that **only 26% of this population's repos declare any
   dependencies at all**, which is why the confidence constants were recalibrated
   to treat E2 as the working ceiling and E3 as a bonus (RN-1).

**Status:** 1,434 postings · 359 tests · evidence engine live in `/analyze` with
both numbers in the UI · `CONTRADICTED` off pending validation · channel-map
recall measured and its prerequisite closed.
