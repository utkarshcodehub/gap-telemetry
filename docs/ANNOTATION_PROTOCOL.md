# Annotation protocol — Dataset A

**Version 1, 2026-10-03.** For the five annotators. Read all of it once before
labelling anything; it takes about ten minutes and it is the difference between a
dataset and a pile of opinions.

Charter: `docs/PLAN.md` §12. Tool: `backend/scripts/annotate.py`.

---

## 1. What you are deciding

**The unit of judgement is one claim.** A claim is a pair:

> *this resume asserts **Docker** — is Docker actually demonstrated in this
> person's public artifacts?*

You give one of three labels:

| Label | Key | Means |
|---|---|---|
| **demonstrated** | `d` | The artifacts show this skill was actually used. |
| **not demonstrated** | `n` | You looked at everything shown and the skill is not there, **and** you would have expected to see it if it were used. |
| **undeterminable** | `u` | You cannot tell from what is shown. Not a failure — a real third answer. |

You are **not** judging whether the person is good at the skill, whether the code
is well written, whether they would pass an interview, or whether the project is
impressive. Only: *do these artifacts demonstrate use of this skill.*

## 2. The three labels, precisely

### demonstrated (`d`)

Pick this when an artifact shows the skill in use. Enough on its own:

- A file that only exists because of the skill — `Dockerfile`, `*.tf`,
  `.github/workflows/ci.yml`, `*.ipynb`, `k8s/deployment.yaml`.
- A dependency declared in a manifest — `react` in `package.json`,
  `torch` in `requirements.txt`.
- Source files in the language — `*.rs` for Rust, `*.java` for Java.

The signal must be **direct and intentional**. Not enough:

- A transitive dependency the person never chose (`anyio` arrives with
  `starlette`; it says nothing about them).
- The skill's name in a README, a repo description, or a topic tag. **That is the
  person writing a claim in a different box, which is the thing this project
  exists to stop counting.** A README is never `d` on its own.
- A vendored copy of someone else's code (`node_modules/`, `vendor/`).

### not demonstrated (`n`)

**Two conditions, both required.** The skill is absent, *and* you would have
expected it to be present if the person used it.

The second condition is the one people get wrong. Consider:

> The person claims **Docker**. There are 23 repos, and no `Dockerfile` anywhere.

Is that `n` or `u`? It depends on whether a `Dockerfile` is where Docker use would
*show up* for this person. If they publish infrastructure work — Terraform,
Kubernetes manifests, Helm charts — then yes, a missing Dockerfile is
informative: `n`. If their public work is eight course assignments and a portfolio
page, then no: they may well have used Docker at an internship and have no reason
to containerise a homework repo. That is `u`.

**When the two conditions are not both met, the answer is `u`, not `n`.** This is
the single most important rule in this document. `n` is a statement about the
artifacts *and* about what the artifacts could have shown; `u` is a statement
about the limits of what we can see.

### undeterminable (`u`)

Pick this when:

- The skill is one no artifact could show — "Communication", "Problem Solving",
  "System Design", "Data Structures & Algorithms". Every project uses data
  structures; none declares them. **This is a category, not a failure.**
- The person's public surface is too thin to check anything (two repos, no
  manifests).
- The artifacts were not fully retrieved (the item will say `collection:
  partial`).
- The skill plausibly lives in private or work code and nothing public would
  contradict that.
- You genuinely cannot decide. `u` is always available and never a cop-out.

## 3. Rules you must follow

1. **Label independently.** Do not discuss items with the other annotator on the
   same profile until both of you have finished and submitted. The whole point of
   two annotators is to measure agreement; a conversation beforehand destroys the
   measurement rather than improving it.
2. **Judge only what the item shows you.** Do not open the person's GitHub, search
   their name, or look at their other accounts. Every annotator must see the same
   evidence, or the labels are not comparable.
3. **You will never see the system's answer.** The tool deliberately does not show
   the engine's verdict, tier, or confidence — if ground truth were anchored to the
   engine's output, the experiment would be measuring the engine against itself.
   If you ever see a verdict in the tool, stop and report it as a bug.
4. **Write a note whenever you label `n`.** One line: what you looked for and
   where. `n` is the strongest label and the only one that can read as an
   accusation, so it carries its reasoning. Notes on `d` and `u` are optional and
   welcome.
5. **Do not label claims for skills on the lane C list** — see §7. The tool will
   not show them.
6. **Take breaks.** Twenty-six items each is about 45 minutes. Tired annotators
   agree with themselves less than rested ones, which shows up as noise in κ and
   is indistinguishable from genuine ambiguity.

## 4. How a profile becomes items

Dataset A gets exact ground truth from **planted claims**, in two phases.

**Phase 1 — determine the true skill set.** For each selected profile the tool
presents a shortlist of candidate skills together with the raw artifacts. Two
annotators label each claim independently; a third adjudicates disagreements. The
output is a per-profile skill set with a `d`/`n`/`u` label each.

**Phase 2 — build the fictional resume.** A *fictional person's* resume is
constructed from each profile: some skills labelled `d` (true claims) plus
deliberately **planted** skills labelled `n` (false claims). Because the false
claims were planted, precision and recall are computable exactly, without
annotator noise entering the headline numbers.

The resume is fictional on purpose. Nothing is published about any real person,
and the ethics position is in `docs/baselines/channel_recall_2026-10-03.md`
§"Ethics and data handling": public data only, read through the official API, and
no conclusion drawn about any individual. Profiles are referred to by alias
(`POP-07`) throughout; the alias→handle mapping stays out of the repository.

**Skills labelled `u` are never planted and never used as true claims.** They are
the honest middle and they belong in the dataset as what they are.

## 5. Adjudication

| Situation | What happens |
|---|---|
| Both annotators agree | The label stands. |
| One says `d`, the other `n` | Adjudicator decides. This is the disagreement that matters and the adjudicator's reasoning is recorded. |
| One says `d` or `n`, the other `u` | Adjudicator decides, and **defaults to `u`** when the evidence is at all arguable. A confident label nobody else could reach is not ground truth. |

Report **Cohen's κ** on the two independent annotators *before* adjudication, over
the three-label scheme, computed by `scripts/kappa.py` (Increment 4). Report it
whatever it is. A mediocre κ with a documented cause is a result; a κ that was
quietly improved by annotators comparing notes is a fabrication.

## 6. Choosing the profiles — and why the obvious way is wrong

**The sampling frames used for the channel-map measurement must not be reused
here.** They were drawn to stress the *map*, and the `dense` frame turned out to
be substantially **Android, Kotlin and React Native** — which matches *none* of the
eight roles in our posting corpus:

> backend developer (274 postings) · devops engineer (188) · full stack developer
> (173) · frontend developer (169) · qa engineer (160) · data engineer (159) ·
> data analyst (157) · ai ml engineer (154)

A Dataset A built from those profiles would measure verification on a population
the product does not serve, and E1's headline number would not transfer. Mobile
development is a real gap in the *corpus*, not a population to evaluate against.

### Recommended selection: role-stratified, with hard gates

**Stratify by role**, two profiles per role across the eight roles = 16 profiles.
At ~4 claims per profile that is the 60 claims the plan calls for, and every role
in the corpus is represented.

Draw each stratum with `scripts/sample_dataset_a.py`, which searches
**repositories** by the topic and language characteristic of each role and takes
their owners — a role is a thing people *build*, and topics describe repositories.
It then applies every gate below automatically and prints the drop-out.

```bash
cd backend
python scripts/sample_dataset_a.py --per-role 2            # preview, writes nothing
python scripts/sample_dataset_a.py --per-role 2 --freeze   # commit to the cohort
```

It previews by default: choosing the evaluation cohort is a decision, not a side
effect of running a script.

**Then apply every gate below.** Each one exists because of something already
measured:

| Gate | Why |
|---|---|
| ≥ 10 non-fork repos | The plan's floor; fewer and almost everything is `u`. |
| **≥ 3 repos with a parseable manifest** | Only 26% of this population's repos have one (RN-1). Without this gate a profile exercises the file-tree channel and nothing else, and the dataset would measure one channel of three. |
| Pushed something in the last 24 months | Recency weighting is part of the model; a dormant profile tests a different thing. |
| Not an organisation, not a bot | `type:user`, and discard accounts whose repos are all template-generated. |
| Primary language matches the role's stratum | Otherwise the stratification is decorative. |
| **Not in either recall cohort** | Those 48 profiles informed the channel map. Evaluating on them would be testing on training data — the exact mistake the recall prerequisite was written to prevent. The tool refuses them. |

**Record the drop-out rate.** The script prints it, and it is a finding about the
population rather than bookkeeping. Measured on two strata, 2026-10-03:

| | |
|---|---|
| Acceptance rate | **14%** of screened candidates |
| Dominant rejector | location not recognised as Indian (12 of 14) |
| Rejected by the manifest gate | **0** |

Two things follow. First, budget roughly **110 candidates screened and ~1,200 API
requests** for 16 profiles — free, but not instant. Second, and more interesting:
**the manifest gate rejected nobody here.** It bites hard on the general
population (26% of repos) and not at all on a role-targeted pool, because
role-typical topic-tagged repositories are real projects rather than coursework.
Role-stratified sampling therefore solves most of the RN-1 problem as a
side effect — keep the gate anyway, since it costs nothing and the day it fires is
the day it was needed.

A first attempt sorted the repository search by **stars** and rejected 56 of 60 on
location: star-ranked results are dominated by famous international projects,
which is the wrong population twice over, since a many-thousand-star maintainer is
not who this product is for either. Sorting by recency instead halved the screening
cost and doubled the acceptance rate.

### Diversity within a stratum

Do not take two profiles from the same stratum that look alike. One prolific
account and one modest one per role is better than two prolific ones: the modest
profiles are where `u` is the right answer, and a dataset without them will make
the engine look better than it is.

## 7. Skills that must not be labelled

**You will never be shown `Selenium`.** The taxonomy files `Web Scraping` as an
*alias of Selenium*, so a `d` or `n` recorded against Selenium might actually be
about scraping with a parser — a label on the wrong skill is worse than no label
(`docs/HANDOFF_LANE_C.md` C-4). It is the one skill the item generator excludes,
and `tests/test_annotation.py::test_excluded_skills_never_reach_an_item` enforces
it. If `Selenium` ever appears, stop and report it.

**Nine other skills cannot appear as claims at all**, which is a different thing
worth understanding:

> Authentication · Pydantic · Vite · Streamlit · Kotlin · Jupyter · Zod · Prisma ·
> Drizzle

They have **no canonical taxonomy entry**, so they are invisible to the whole
system — not extracted from a resume, not counted in demand, not verifiable from
code — and therefore cannot become an item in the first place. Real candidates in
the cohort declared every one of them. **That absence is itself the finding** (C-1),
not a gap in this protocol, and the item generator prints the list each time it
runs so it stays visible rather than becoming invisible twice over.

The general rule behind both: labelling a claim whose skill our vocabulary cannot
represent would bake a vocabulary gap into the ground truth — the same mistake the
channel-map prerequisite exists to prevent, one level further up.

## 8. Using the tool

```bash
cd backend
python scripts/annotate.py --task dry_run --annotator <your-name>
```

- One item per screen: the claim, then the artifacts, then the prompt.
- `d` / `n` / `u` to label, `s` to skip for now, `b` to go back one,
  `?` to re-read the label definitions, `q` to save and quit.
- Progress saves after **every** item, so quitting loses nothing and you can
  resume by re-running the same command.
- Your labels go to `data/annotations/<task>/<your-name>.jsonl`, which is
  gitignored. Send the file to the lane A owner when the task is finished.

## 9. Before the real thing: the five-item dry run

Everyone does the same five items first — including the adjudicator. They were
chosen to cover one clear `d`, one clear `n`, one `u`-because-no-artifact-could-
show-it, one `u`-because-the-surface-is-thin, and one genuinely arguable case.

Then compare, out loud, as a group. **The dry run is the only time discussing
items is allowed**, and its purpose is to surface disagreements about the
*protocol* while they are still cheap to fix. If the five of us disagree on item 5,
this document needs another paragraph — which is exactly what the dry run is for.

Expected outcome: agreement on items 1–4 and an argument about item 5. If there is
disagreement on items 1–4, stop and fix the protocol before labelling 60 claims
against it.

Build it with:

```bash
cd backend
python scripts/build_annotation_task.py --name dry_run --allow-recall-cohort   --cohort POP-01 POP-18 POP-04 POP-21   --claims POP-01:Python POP-01:React POP-18:Communication POP-04:Docker POP-21:Docker
```

`--allow-recall-cohort` is required and correct here: these four profiles informed
the channel map, so they may be used to rehearse the protocol but **never** as
Dataset A data. The generator refuses them without the flag (§6, last gate).

---

### Facilitator section — read only after everyone has labelled

<details>
<summary>What each dry-run item was chosen to test (spoilers)</summary>

| # | Item | The case it covers | Expected |
|---|---|---|---|
| 1 | POP-01 · **Python** | Unambiguous `d`. Eight Python repos, `pandas`/`numpy`/`sqlalchemy` declared. | `d` |
| 2 | POP-01 · **React** | `n` where both conditions hold. Twelve repos, every one Python or Jupyter, **no `package.json` anywhere** — React work would have produced a JS project. Also exercises the mandatory note. | `n` |
| 3 | POP-18 · **Communication** | `u` because no artifact could ever show it. EC-9: a category, not a failure. | `u` |
| 4 | POP-04 · **Docker** | `u` because the surface is too thin. Three repos, no manifests. Absence here means nothing — the trap the `n` rule's second condition exists to prevent. | `u` |
| 5 | POP-21 · **Docker** | **Genuinely arguable.** Eleven repos including a Postgres/Prisma app and Rust, no Dockerfile, no infrastructure-as-code. Someone shipping that may well have containerised it — or used a PaaS. | argue |

If the group splits on items 1–4, the protocol is at fault and needs another
paragraph. If it splits on item 5, that is the correct outcome: write down which
way you resolved it and why, and that sentence becomes protocol v2.

</details>
