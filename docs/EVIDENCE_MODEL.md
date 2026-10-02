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
| `UNVERIFIABLE` | Could not be checked. **Never a penalty.** Carries a `reason`: see below |
| `CONTRADICTED` | Claimed, *and* positive counter-evidence exists — see §4 |

### `UNVERIFIABLE` carries a reason *(decided 2026-10-02)*

Five verdicts stay five. But one of them was carrying two completely different
meanings, so it now reports which:

| `unverifiable_reason` | Meaning |
|---|---|
| `by_design` | **No quantity of evidence could ever verify this** — "System Design", "REST API", "Microservices", soft skills (EC-9). Not a failure, and must never render as one. |
| `insufficient_artifacts` | **This candidate's public surface was too thin to check it** — the empty-GitHub majority case (EC-1). A statement about available evidence, not about the claim. |

*Reasoning.* Conflating them tells a student their computer-science fundamentals
are "unproven" when the system was structurally incapable of looking. A skill in
the `by_design` group is excluded from coverage (§8.5) and can never be
`CONTRADICTED`, so reporting it beside genuinely-unchecked claims also misstates
what the system did. A reason field was preferred over a sixth verdict because the
*verdict* is the same in both cases — unverified — while the *explanation* differs.

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

**Thresholds: conservative, and every one a named constant** (decided — §8.3).
`CONTRADICTION_MIN_AUTHORED_REPOS`, `CONTRADICTION_MIN_COVERAGE`,
`CONTRADICTION_MIN_AUTHORSHIP_SHARE` and the rest live in one place and are tuned
on Dataset A, not guessed in an expression.

They start deliberately **strict**, because the two error directions are not
symmetric. A missed contradiction costs one absent insight. A false contradiction
tells an honest candidate they look like a liar. Tuning therefore begins from
"fires rarely" and loosens only as far as Dataset A's labels justify — never the
other way round.

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

**Form: additive, capped, with bounded bonuses** (decided — §8.2).

```
confidence = clamp(TIER_BASE[max_tier]
                 + min(REPO_BONUS_CAP,   repo_bonus(n_repos_with_evidence))
                 + min(RECENCY_BONUS_CAP, recency_bonus(recency_weight))
                 + min(AUTHOR_BONUS_CAP,  author_bonus(authorship_share)),
                   0.0, 1.0)
```

`max_tier` sets the floor; the other three signals can only add, each capped
independently, and the total is clamped to [0, 1]. Three consequences, all
intended:

- **Tier dominates.** A manifest entry (E3) outranks any amount of README
  mentioning (E1), which is the whole premise of §2.
- **No signal can veto.** A missing `authorship_share` — common, because the
  commits API may be unavailable — reduces confidence but cannot collapse it.
  A multiplicative form would have let one absent signal zero out four present
  ones, which punishes the candidate for our infrastructure failing.
- **Bonuses cannot overwhelm tier.** Caps stop twenty trivial repos from lifting
  an E1 mention above a single E3 declaration.

Every constant above is a **named constant tuned later on Dataset A** (§8.3),
not a number embedded in an expression. The plan assigns the signals' *relative
weight* to experiment **E2**'s ablation, so these start conservative and are an
empirical result, not a design claim.

---

## 6. Readiness and coverage — the headline output

Two numbers, **always reported together**:

| Number | Definition |
|---|---|
| `claimed_readiness` | Demand-weighted coverage of the skills **claimed on the resume**, and nothing else (decided — §8.1) |
| `verified_readiness` | The same computation, weighted by confidence (§5) |

The gap between them is the product. It is also the paper's headline.

**`claimed_readiness` is resume-only.** It must be a *pure* self-report number, or
the comparison measures nothing: a baseline that already contains GitHub signal
understates the gain from evidence grading and quietly credits the baseline with
the very thing being tested.

A third number is retained purely as a reference point:

| Reference | Definition |
|---|---|
| `legacy_union_readiness` | `resume ∪ github` — the number this codebase shipped before the evidence model | 

It is **labelled as legacy, excluded from the headline, and never shown to a
candidate.** It exists so that a reader of the report can see what the old
behaviour produced, and because the regression tests pin it.

### What is excluded from both readiness numbers

Two categories are reported **separately**, deliberately outside both:

| Reported separately | Why |
|---|---|
| `attested_skills` (EA) | Excluded from `verified_readiness` (decided — §8.4). Self-attestation is a lever the candidate controls, so letting it raise a *verified* number would make the word "verified" untrue and hand the adversarial evaluation (E4) its easiest attack. Shown as its own list, honestly labelled. |
| `unclaimed_verified_skills` | Artifact evidence for skills never claimed — today's `hidden_strengths` (decided — §8.6). Outside both numbers because neither asks this question: `claimed_readiness` is about claims, and `verified_readiness` weights *claims* by evidence. Surfacing them is a headline feature ("you've been using Redis in three projects and never told anyone"), so they are prominent — as advice, not as score. |

### Coverage

| Metric | Definition |
|---|---|
| `verification_coverage` | mean per-claim channel coverage (revised — §8.5) |

Shown **prominently**, so a low verified score is never misread as dishonesty when
it is really absence of public code. A candidate with no GitHub should see *"we
could check 0% of your claims"*, not a low score with no explanation. Reported as
`None`, not `0`, when `assessable_claims` is zero — "nothing to check" and "checked
nothing" are different statements.

---

## 7. Baseline instrumentation

`verified_readiness` cannot be shown to be *better* than `claimed_readiness`
unless the latter is recorded before the evidence engine exists. Otherwise the
comparison is made against a number that has already moved.

`backend/core/gap/baseline.py` computes, for a fixed set of candidate profiles ×
roles, every quantity needed to detect a later change:

- `claimed_readiness` — resume claims only. **The baseline**, per §8.1.
- `legacy_union_readiness` — the shipped `resume ∪ github` behaviour, retained as
  a labelled reference only
- `delta_legacy_minus_claimed` — how much GitHub signal the old number already
  contributed, i.e. exactly the amount a union baseline would have wrongly
  credited to the control condition in E1
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

## 8. Decisions — resolved, and why

> **FLAG FOR MENTOR REVIEW.** These six are research-design decisions, not
> implementation details. Each changes what experiment **E1** measures or how
> fairly the system treats a candidate, so each is stated with its reasoning for a
> reviewer to challenge. Decided by the project owner on 2026-10-02 except §8.5,
> which was proposed here and is the one most worth a second opinion.

### 8.1 `claimed_readiness` is resume-only ✅

The plan said both "counting every claim" (resume only) and "today's number"
(a `resume ∪ github` union). **Decided: resume-only.**

*Reasoning.* The baseline has to be a pure self-report, because it is the control
condition in E1. A baseline containing GitHub signal credits the control with part
of the treatment, which understates the measured effect — the project would
undersell its own contribution and the comparison would not isolate what it claims
to isolate. The legacy union survives as `legacy_union_readiness`, labelled and
excluded from the headline, so the old behaviour stays inspectable.

### 8.2 Confidence is additive, capped, with bounded bonuses ✅

**Decided: additive.** `max_tier` sets a floor; the other three signals add,
each capped independently; the total clamps to [0, 1]. Full form in §5.

*Reasoning.* The alternative — multiplicative — lets a single absent signal zero
out every present one. `authorship_share` is frequently unavailable (the commits
API is rate-limited or the repo has one commit), and a candidate must not lose
confidence because *our* fetch failed. Additive degrades gracefully; multiplicative
punishes infrastructure problems. Caps stop twenty trivial repos outranking one
real dependency declaration, preserving the tier ordering that §2 exists to
establish.

### 8.3 Thresholds are conservative, named constants, tuned on Dataset A ✅

**Decided.** No threshold is an inline literal. Each is a module-level constant
with a comment stating what it protects, and initial values are deliberately
strict.

*Reasoning.* The error directions are not symmetric. A missed contradiction costs
one absent insight; a false one tells an honest candidate they look like a liar.
So tuning starts from "fires rarely" and loosens only as far as Dataset A's labels
justify. Naming them is what makes the later tuning a recorded experiment rather
than an undocumented edit, which matters because E2's ablation needs to vary them.

### 8.4 `ATTESTED` is excluded from verified readiness, shown separately ✅

**Decided: excluded**, reported as its own labelled list.

*Reasoning.* Self-attestation is the one input the candidate fully controls. If it
raised a number called *verified*, the word would be false, and the adversarial
evaluation (Dataset C / E4) would have a trivial exploit: attest everything.
Excluding it keeps "verified" meaning independently checked, while still
representing private work honestly — which is the point of EA existing (EC-3).

### 8.5 Coverage — REVISED 2026-10-02 🔶 *flag for mentor review*

```
verification_coverage = mean over assessable claims of channel_coverage(claim)

channel_coverage(claim) = in-scope repos where a channel capable of proving the
                          claim was successfully retrieved
                          ----------------------------------------------------
                          in-scope repos
```

| Term | Definition |
|---|---|
| `assessable claims` | Claimed skills that are **(a)** artifact-evidenceable by category — excluding `by_design` skills (EC-9) — **and (b)** not attested as private (EA) |
| `in-scope repos` | The non-fork repositories the analysis set out to read |
| *channel capable of proving the claim* | From the skill→channel map: file tree, dependency manifest, or language statistics |

**Why it was revised.** The first definition counted a claim as "checkable" if
**any** repo had yielded a usable channel. On the first real profile that produced
**`coverage = 100%`** while nine of twelve repo fetches had actually failed to a
rate limit. As the gate standing between a thin analysis and a false
`CONTRADICTED`, a value that reads 1.0 whenever a single repo succeeds protects
nothing at all. Averaging per-repo retrieval instead makes incomplete collection
*look* incomplete, which is the only thing the gate needs from it.

**Still non-circular.** No term consults a verdict. Retrieval is settled before any
judgement about presence or absence, so coverage cannot be raised by the
contradictions it licenses.

**Attested claims remain excluded from the mean.** They would otherwise drag it
down, suppressing `CONTRADICTED` across the board — the same gaming vector §8.4
guards from the other side.

### `CONTRADICTED` additionally requires a complete profile *(decided)*

A partial profile — repo cap reached, rate limit hit, request budget exhausted —
now blocks `CONTRADICTED` outright, independently of coverage.

*Reasoning.* Coverage measures how much of each *repo set* we read; it does not
capture that we deliberately stopped at 12 of 23 repositories. The skill may be in
a repo nobody opened, so absence is a fact about our collection, not about the
candidate. These are two different incompletenesses and only one of them was
previously gated.

### 8.7 Every claim gets a verdict; only the percentage depends on the basket *(decided 2026-10-02)*

A claim is assessed whether or not the role's demand basket wants it. The basket
decides what contributes to a **percentage**; it has no business deciding whether
a candidate's claim is looked at.

*Reasoning.* The first real run assessed 9 of 27 claimed skills for a backend role
and silently dropped FastAPI, Supabase, Pandas, NumPy, scikit-learn and the rest,
because their demand for that role is under the 5% floor. A reader cannot tell
"below the demand floor" from "unverified" — both simply fail to appear. After the
change, VERIFIED on the author's own profile went from 5 to **16**. The readiness
figures are unchanged, because those skills still contribute nothing to the
percentage; what changed is that the candidate is now told what the system found.

Assessments carry `in_demand_basket` and `demand_pct` so the two groups can be
shown separately.

### 8.8 `CONTRADICTED` requires an absence allowlist 🔶 *flag for mentor review*

A per-skill eligibility list decides when absence is evidence at all. **A skill not
on it can never be CONTRADICTED**, whatever the evidence shows. Eligible skills must
still clear every §8.3 gate plus a non-partial profile.

**Admission criterion**, which matters more than the list:

1. **The evidence must live in the file tree, not only in a manifest.** Trees are
   read completely; manifests are **sampled** (`MAX_MANIFESTS_PER_REPO`). For a
   manifest-only skill, absence may just mean we never opened the file that
   declared it.
2. **The artifact must be effectively unavoidable** — Docker without a Dockerfile
   is close to impossible; MongoDB without a locally-declared driver is routine.
3. **It must live where we look** — root or a conventional path, not behind a build
   step or in a sibling infrastructure repo.

**Admitted: `Docker`, `Terraform`.** Both file-tree detectable, both with an
unavoidable artifact at a conventional path.

**Rejected, with reasons** — the rejections are the substance:

| Rejected | Why |
|---|---|
| MySQL, MongoDB, PostgreSQL, Redis | Manifest-only, and we sample manifests. Also routinely used via a hosted client or ORM that never names them locally. Fails (1). |
| React, Angular, Vue.js | Manifest-only; same sampling problem. Fails (1). |
| CI/CD | File-tree detectable, but using CI at work while keeping personal repos plain is entirely normal. Fails (2). |
| Kubernetes | Manifests usually live in a separate infrastructure repo outside the profile. Fails (3). |
| Python, TypeScript, Java | Already positively detected from language statistics; a contradiction adds nothing a reader cannot see. |

**What a contradiction means to the candidate.** Not "you lied". It means *your
public code does not support this claim, so add evidence or mark it private*. The
attestation path (EA / FR-41) exists so a candidate whose real experience is at
work has a truthful answer, which is what makes the verdict survivable — and why
it must stay rare.

**First live result**, on the author's own profile (23 repos, every tree read,
non-partial): **`Docker` → CONTRADICTED**, `MySQL` and `MongoDB` → `UNVERIFIABLE`.
The database skills were spared by criterion (1), not by luck.

### 8.6 Unclaimed-verified skills sit outside both numbers ✅

**Decided: reported separately**, in neither readiness figure.

*Reasoning.* Neither number asks this question. `claimed_readiness` is about
claims; `verified_readiness` weights *claims* by their evidence. A skill that was
never claimed has no claim to weight. Folding it into either would quietly change
what the number means — and into `verified_readiness` specifically it would inflate
the treatment condition in E1 with something the control never saw. It stays
prominent as *advice* ("add Redis to your resume, it is in three of your repos"),
which is where its value is anyway.

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
