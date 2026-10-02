# Evidence Model — specification

**Status:** specification of decisions already taken in `docs/PLAN.md` §9.1.
Nothing here is new design. Where the plan is silent or self-contradictory, the
question is recorded in **§8 Open questions** rather than answered — those are
research-design decisions and belong to the project owner.

**Implements:** FR-8 … FR-14, FR-39 … FR-43 · **Measured by:** experiments E1, E2
**Replaces:** `core/gap/scorer.py:67`, `user_all = resume_skills | set(github_skills)`

---

## 1. Why this exists

A resume is a self-report. Every system that consumes one — placement portals, ATS
filters, and the large family of student "resume analyser" projects — treats a
claim as a fact. So does this codebase today: `score_gap` unions resume skills
with GitHub skills and the "evidence" label it computes is **cosmetic**, printed
beside a number it did not help produce.

Worse, the GitHub half is barely independent. `core/github_profile/fetcher.py`
reads each repo's **name, description, topics and README** — all four written by
the candidate — and runs the same keyword matcher over them. The second source is
the same person's claims in a different box.

This model replaces that with a graded judgement about **how hard each signal
would be to fabricate**, and makes that grade causal: it changes the score.

---

## 2. Evidence tiers

Ordered by fabrication difficulty, not by source.

| Tier | Name | Source | Fakeable? |
|---|---|---|---|
| **E0** | `CLAIMED` | Resume text | Trivially |
| **EA** | `ATTESTED` | Candidate asserts private/work evidence (FR-41) | Trivially — but honestly flagged as unverified |
| **E1** | `MENTIONED` | Repo README / description / topics | Trivially — **this is all the system does today** |
| **E2** | `PRESENT` | File tree (`Dockerfile`, `*.tf`, `.github/workflows/`) — public, OAuth-private, or local-scanner digest | Hard — requires real project structure |
| **E3** | `DECLARED` | Dependency-manifest entry | Very hard — the toolchain would break |
| **E4** | `AUTHORED` | E2/E3 evidence in a repo with verified commit authorship | Effectively not |

**EA is deliberately not ordinal with E1–E4.** It is ranked above a bare claim and
below anything independently checked, but it is an *assertion*, not an artifact,
so it does not sit on the fabrication-difficulty scale with the others. It exists
because a candidate's best work is often work they are contractually unable to
show (EC-3), and refusing to represent that at all would be its own distortion.

---

## 3. Verdicts

One verdict per **claimed** skill. The unit of judgement is a claim, not a skill:
*this resume asserts X — is X demonstrated in this person's artifacts?*

| Verdict | Condition |
|---|---|
| `VERIFIED` | Supported at **E2 or above** |
| `WEAK` | Supported only at **E1** |
| `ATTESTED` | Candidate declares private/work evidence (**EA**); always labelled as not independently checked |
| `UNVERIFIABLE` | Insufficient artifacts to check. **Never a penalty.** |
| `CONTRADICTED` | Claimed, *and* positive counter-evidence exists — see §4 |

### The distinction that matters

`UNVERIFIABLE` and `CONTRADICTED` must never be conflated. One means *"we could
not look"*; the other means *"we looked, and it should have been there."*
Collapsing them is what makes naive verification unfair — most Indian engineering
students have a near-empty GitHub (EC-1), and a system that reads absence as
dishonesty is simply wrong about the majority of its users.

---

## 4. Contradiction safety rule

> `CONTRADICTED` requires **positive counter-evidence**: substantial authored code
> in a context where the skill would necessarily appear, and it does not.

It **never** fires:

- from absence alone;
- when verification coverage (§6) is low;
- against a skill attested as private (FR-41).

Absence of proof is always reported as `UNVERIFIABLE`.

This is the single rule with the most power to do harm. A false `CONTRADICTED` on
an honest candidate is not a wrong number — it is an accusation, and it is the
difference between a product people trust and one they resent. The dispute path
(EC-19) exists because even a correct rule will occasionally be wrong: provenance
is inspectable, and a manual override is recorded and shown as such.

⚠️ **"Substantial" and "a context where the skill would necessarily appear" are
not defined by the plan.** See §8.3 — this threshold must be set before the rule
can be implemented.

---

## 5. Confidence

A continuous per-skill value replacing today's three-value `evidence` string.
Inputs, as fixed by the plan:

```
confidence = f(max_tier, n_repos_with_evidence, recency_weight, authorship_share)
```

| Input | Meaning | Available from |
|---|---|---|
| `max_tier` | Highest tier any evidence for this skill reached | §2 |
| `n_repos_with_evidence` | Distinct repos supplying evidence (already computed as `skill_repo_count`) | `github_profile/fetcher.py` |
| `recency_weight` | Decay on how recently the evidence was touched (FR-14) | repo `pushed_at` / commit dates |
| `authorship_share` | Candidate's share of commits in the evidencing repo (FR-6) | commits API, filtered by author |

⚠️ **Only the inputs are decided; the function is not.** Its form, ranges and
normalisation are open — see §8.2. Note the plan assigns the *relative weight* of
these signals to experiment **E2**'s ablation, so weights are intended to be an
empirical result rather than a design choice. The functional form is still a
design decision, because it determines whether those weights are interpretable.

---

## 6. Readiness and coverage — the headline output

Two numbers, **always reported together**:

| Number | Definition |
|---|---|
| `claimed_readiness` | Demand-weighted coverage counting every claim. The baseline. |
| `verified_readiness` | The same computation, weighted by confidence (§5). |

Plus:

| Metric | Definition |
|---|---|
| `verification_coverage` | `verifiable_claims / total_claims` |

Coverage is shown **prominently**, so a low verified score is never misread as
dishonesty when it is really absence of public code. A candidate with no GitHub
should see *"we could check 0% of your claims"*, not a low score with no
explanation.

The gap between the two numbers is the product. It is also the paper's headline.

⚠️ **`claimed_readiness` is defined two incompatible ways by the plan**, and it is
the baseline the entire research claim is measured against. See §8.1 — this is
the gap that most needs resolving, and the baseline harness (§7) deliberately
records both candidate definitions so the choice can be made without re-running
anything.

---

## 7. Baseline instrumentation

`verified_readiness` cannot be shown to be *better* than `claimed_readiness`
unless the latter is recorded before the evidence engine exists. Otherwise the
comparison is made against a number that has already moved.

`backend/core/gap/baseline.py` computes, for a fixed set of candidate profiles ×
roles, every quantity needed to detect a later change:

- `readiness_resume_only` — resume claims only
- `readiness_union` — today's `resume ∪ github` behaviour, unchanged
- `delta_union_minus_resume_only` — how much GitHub signal already contributes
- gap counts per tier, strength counts per evidence label, `hidden_strengths`
- the demand basket size per role

`backend/scripts/baseline_snapshot.py` emits this as a JSON artifact under
`docs/baselines/`. Profiles are checked in and deterministic, so a snapshot is
reproducible and a diff between two snapshots is attributable to a code change
rather than to data drift.

This is a **golden-output baseline**, not an accuracy measurement. Accuracy needs
labelled ground truth, which arrives with Dataset A in Increment 3. What this
gives now is the ability to say exactly what changed, and by how much, the moment
scoring behaviour moves.

---

## 8. Open questions — for the project owner

These change the research design. They are listed, not decided.

### 8.1 What is `claimed_readiness`? *(highest priority)*

The plan says both:

> "demand-weighted coverage **counting every claim**" — implies resume claims only
> "**(today's number**, retained as the baseline)" — today's number is
> `resume_skills | set(github_skills)`, a union that includes GitHub-derived
> skills, which are **not** claims

These are different quantities. It matters because the baseline determines the
measured size of the effect in **E1**: if the baseline already contains GitHub
signal, the apparent gain from evidence grading is *understated*, and the project
undersells its own contribution. If the baseline is resume-only, the comparison is
cleaner but is no longer "today's number".

*Current handling:* the baseline harness records **both**, so this can be decided
later at no cost.

### 8.2 What is the confidence function?

Inputs are fixed; form is not. Open: is it additive or multiplicative; is it
bounded to [0, 1]; does `max_tier` dominate or merely contribute; how does
`recency_weight` decay (linear, exponential, half-life in months); what happens
when `authorship_share` is unknown because the commits API was unavailable.

A multiplicative form makes a single weak signal suppress the whole score; an
additive one lets strong signals compensate. That is a substantive choice about
how forgiving the system is, not an implementation detail.

### 8.3 What counts as "substantial" counter-evidence?

Required before §4 can be implemented. Open: how much authored code makes absence
meaningful (repo count? commit count? authorship share?), and what defines "a
context where the skill would necessarily appear" — same-ecosystem repos, or
role-matched repos, or something else. Setting it loose produces false
accusations; setting it tight makes `CONTRADICTED` fire so rarely that the
headline feature never appears.

### 8.4 Does `ATTESTED` contribute to `verified_readiness`, and how much?

The plan ranks EA "above a bare claim, below anything independently checked",
which implies a non-zero weight, but names no value. If it contributes, it is a
lever the candidate controls directly — which interacts with the adversarial
evaluation (Dataset C, experiment **E4**): attesting everything would be the
obvious attack.

### 8.5 What exactly is a "verifiable claim" in the coverage denominator?

`verifiable_claims / total_claims` admits two readings: claims we *could* have
checked (the candidate has artifacts in that area), or claims that resolved to
any verdict other than `UNVERIFIABLE`. The second is circular if used to justify
suppressing `CONTRADICTED` when coverage is low (§4).

### 8.6 How are GitHub-only skills scored?

Skills found in artifacts but never claimed are today's `hidden_strengths`, and
§3 of the plan treats surfacing them as a headline feature ("you've been using
Redis in three projects and never told anyone"). But they are not claims, so the
verdict scheme in §3 has no slot for them. Open: do they contribute to
`verified_readiness`, or are they reported alongside it as an advisory?

---

## 9. What this model does **not** cover

Stated so the scope is not quietly assumed wider than it is:

- **Proficiency and seniority.** Evidence establishes *use*, never *level*. One
  Dockerfile and three years of Kubernetes operations are both E2/E3.
- **Non-artifact skills.** Communication, leadership and teamwork are
  `NOT-VERIFIABLE-BY-DESIGN` (EC-9) — a category, not a failure.
- **Code quality.** Tree-sitter/AST analysis is explicitly out of scope
  (`docs/PLAN.md` §9.5) and documented as future work.
- **Derivative work.** Tutorial-clone detection (EC-5) is a known limitation,
  heuristic at best.
