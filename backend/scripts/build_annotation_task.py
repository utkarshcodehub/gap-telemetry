"""
Build a Dataset A annotation task from real GitHub profiles.

    cd backend
    python scripts/build_annotation_task.py --name dry_run --cohort POP-01 POP-07 --per-profile 2
    python scripts/build_annotation_task.py --name dataset_a --role-stratified

Writes two files into data/annotations/<name>/ (gitignored):

    profiles.json   the artifacts, once per profile
    items.jsonl     one line per CLAIM -- the unit of judgement

THE ONE PROPERTY THAT MATTERS. A task file contains **no verdict, no tier and no
confidence**, and the artifacts it shows are not filtered by the channel map. An
annotator who could see the engine's answer -- or even just the files the engine
thought were relevant -- would produce ground truth anchored to the engine, and
experiment E1 would then be measuring the engine against itself. What the
annotator gets is a map-independent digest of what is actually in the repos:
root-level files, directory names, file extensions with counts, declared packages,
language, recency, authorship. They decide for themselves whether the skill is in
there. `tests/test_annotation.py` asserts the absence of engine output.

WHERE THE CANDIDATE SKILLS COME FROM. The market corpus, not the channel map: the
top demand skills for the profile's assigned role. That keeps the shortlist
independent of the thing under test, and it aims the dataset at the claims that
actually matter -- demand-weighted gaps are the product's output.

Concept skills ("System Design", "Communication") are deliberately KEPT. The right
label for them is `undeterminable`, that is a real third answer rather than a
failure, and a dataset without them would never test it.
"""

from __future__ import annotations

import argparse
import json
import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.main import get_store  # noqa: E402
from app.settings import get_settings  # noqa: E402
from core.evidence.github import (  # noqa: E402
    GitHubClient,
    RequestBudget,
    collect_profile,
)
from core.taxonomy.loader import Taxonomy  # noqa: E402
from scripts.measure_channel_recall import (  # noqa: E402
    CACHE_DIR,
    COHORT_FILE,
    classify,
    read_alias_map,
    read_cohort,
)
from scripts.recall_labels import LABELS, Verdict  # noqa: E402

OUT_ROOT = Path(__file__).resolve().parents[1] / "data" / "annotations"

#: How many file extensions to show per repo. Enough to see what a repo is made
#: of; short enough that the digest stays readable.
MAX_EXTENSIONS = 18
#: Root files are the most informative paths in a repo (Dockerfile, *.tf,
#: pom.xml all live there), so they are listed in full up to this many.
MAX_ROOT_FILES = 40


def excluded_skills(taxonomy: Taxonomy) -> dict[str, str]:
    """Canonical skills that must not be labelled, with the reason.

    Derived from the recall labels rather than hand-listed, so that when lane C
    fixes a taxonomy entry the exclusion disappears by itself instead of outliving
    its cause.

    What lands here is a skill whose taxonomy entry CONFLATES two genuinely
    different things: `Web Scraping` is an alias of `Selenium`, so a `d` or `n`
    recorded against Selenium may actually be about scraping with a parser. A
    label recorded against the wrong skill is worse than no label.

    The nine skills with no canonical entry at all (Streamlit, Vite, Pydantic,
    Kotlin, ...) need no exclusion: they are absent from the vocabulary, so they
    cannot appear in a demand basket and cannot become a claim. That absence IS
    the lane C finding, and `unreachable_skills()` reports it for the record.
    """
    out: dict[str, str] = {}
    for pkg, label in LABELS.items():
        if label.verdict != Verdict.SKILL or not label.skill:
            continue
        bucket, target, why = classify(pkg, taxonomy)
        if bucket != Verdict.NO_TAXONOMY_ENTRY:
            continue
        canonical = taxonomy.canonicalize(target)
        if canonical is not None and canonical != target:
            out[canonical] = (f"'{target}' is filed as an alias of '{canonical}', so a "
                              f"label here could be recorded against the wrong skill")
    return out


def unreachable_skills(taxonomy: Taxonomy) -> dict[str, str]:
    """Skills real candidates declare that the taxonomy has no entry for."""
    out: dict[str, str] = {}
    for pkg, label in LABELS.items():
        if label.verdict != Verdict.SKILL or not label.skill:
            continue
        bucket, target, why = classify(pkg, taxonomy)
        if bucket == Verdict.NO_TAXONOMY_ENTRY and taxonomy.canonicalize(target) is None:
            out[target] = why
    return out


# ------------------------------------------------------------------ artifacts


def repo_digest(repo) -> dict:
    """A map-independent summary of one repo.

    Deliberately NOT the paths that matched some skill's channel: that would show
    the annotator the engine's opinion of what is relevant and call it evidence.
    """
    paths = list(repo.tree_paths)
    root = sorted(p for p in paths if "/" not in p)
    dirs = sorted({p.split("/", 1)[0] for p in paths if "/" in p})

    exts: dict[str, int] = {}
    for p in paths:
        name = p.rsplit("/", 1)[-1]
        ext = "." + name.rsplit(".", 1)[-1] if "." in name else "(no extension)"
        exts[ext.lower()] = exts.get(ext.lower(), 0) + 1
    top_exts = dict(sorted(exts.items(), key=lambda kv: -kv[1])[:MAX_EXTENSIONS])

    return {
        "repo": repo.name,
        "primary_language": repo.primary_language,
        "pushed_months_ago": (round(repo.pushed_months_ago, 1)
                              if repo.pushed_months_ago is not None else None),
        "authorship_share": repo.authorship_share,
        "files_total": len(paths),
        "root_files": root[:MAX_ROOT_FILES],
        "root_files_truncated": max(0, len(root) - MAX_ROOT_FILES),
        "directories": dirs,
        "extensions": top_exts,
        "packages": sorted(repo.packages),
        "tree": paths,          # full tree, for the tool's /search command
    }


def profile_digest(profile, alias: str) -> dict:
    return {
        "profile": alias,
        "repos_in_scope": len(profile.repos),
        # Stated plainly, because it changes the right label: when collection was
        # incomplete, absence is not evidence and `u` is usually correct.
        "collection": "partial" if profile.partial else "complete",
        "repos": [repo_digest(r) for r in profile.repos],
    }


# ---------------------------------------------------------------------- items


def candidate_skills(role: str, taxonomy: Taxonomy, *, top_n: int,
                     exclude: dict[str, str]) -> list[dict]:
    """The role's highest-demand skills, from the market corpus."""
    demand = get_store().demand(role)
    out = []
    for row in demand:
        if len(out) >= top_n:
            break
        if row["canonical"] in exclude:
            continue
        out.append({"skill": row["canonical"], "demand_pct": row["demand_pct"]})
    return out


def build_items(profile_alias: str, role: str, skills: list[dict]) -> list[dict]:
    return [
        {
            "id": f"{profile_alias}:{s['skill']}",
            "profile": profile_alias,
            "role": role,
            "skill": s["skill"],
            # Context for the annotator, not a hint: it says why this claim is
            # worth judging, never whether it is true.
            "role_demand_pct": s["demand_pct"],
        }
        for s in skills
    ]


# --------------------------------------------------------------------- collect


def collect(alias: str, handle: str, token: str | None):
    client = GitHubClient(token=token, budget=RequestBudget(limit=150),
                          cache_dir=CACHE_DIR)
    return collect_profile(client, handle)


def main() -> None:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--name", required=True, help="task name, e.g. dry_run")
    ap.add_argument("--cohort", nargs="+", required=True,
                    help="profile aliases (resolved via the gitignored map)")
    ap.add_argument("--role", default="backend developer",
                    help="role whose demand basket supplies the candidate skills")
    ap.add_argument("--per-profile", type=int, default=4,
                    help="claims per profile, sampled from the role's demand basket")
    ap.add_argument("--claims", nargs="*", default=[], metavar="ALIAS:Skill",
                    help="explicit claims instead of sampling -- used to assemble the "
                         "dry run, which has to cover one case of each kind")
    ap.add_argument("--allow-recall-cohort", action="store_true",
                    help="permit profiles that informed the channel map (dry runs only)")
    ap.add_argument("--seed", type=int, default=20261003)
    args = ap.parse_args()

    settings = get_settings()
    taxonomy = Taxonomy()
    excluded = excluded_skills(taxonomy)
    random.seed(args.seed)

    # Profiles that informed the channel map must not become evaluation data --
    # that is testing on training data, which is the exact mistake the recall
    # prerequisite was written to prevent.
    in_recall = set()
    for frame in ("population", "dense"):
        in_recall |= set(read_cohort(COHORT_FILE.with_name(f"recall_cohort_{frame}.txt")))
    offenders = [a for a in args.cohort if a in in_recall]
    if offenders and not args.allow_recall_cohort:
        ap.error(f"{', '.join(offenders)} informed the channel map. Evaluating on them "
                 f"is testing on training data. Pass --allow-recall-cohort only for a "
                 f"dry run, where nothing is being measured.")

    aliases = read_alias_map()
    out_dir = OUT_ROOT / args.name
    out_dir.mkdir(parents=True, exist_ok=True)

    profiles: dict[str, dict] = {}
    items: list[dict] = []
    skills = candidate_skills(args.role, taxonomy, top_n=args.per_profile * 3,
                              exclude=excluded)

    explicit: dict[str, list[str]] = {}
    for spec in args.claims:
        alias, _, skill = spec.partition(":")
        if not skill:
            ap.error(f"--claims takes ALIAS:Skill, got {spec!r}")
        if skill in excluded:
            ap.error(f"{skill} must not be labelled: {excluded[skill]}")
        if taxonomy.canonicalize(skill) != skill:
            ap.error(f"{skill!r} is not a canonical taxonomy skill")
        explicit.setdefault(alias, []).append(skill)

    by_demand = {s["skill"]: s["demand_pct"] for s in
                 candidate_skills(args.role, taxonomy, top_n=999, exclude=excluded)}

    for alias in args.cohort:
        handle = aliases.get(alias, alias)
        prof = collect(alias, handle, settings.github_token)
        profiles[alias] = profile_digest(prof, alias)
        if explicit:
            chosen = [{"skill": s, "demand_pct": by_demand.get(s, 0.0)}
                      for s in explicit.get(alias, [])]
        else:
            chosen = random.sample(skills, min(args.per_profile, len(skills)))
        items.extend(build_items(alias, args.role, chosen))
        print(f"  {alias:<10} {len(prof.repos):>3} repos  "
              f"{'PARTIAL' if prof.partial else 'complete':<8} "
              f"{len(chosen)} claims")

    (out_dir / "profiles.json").write_text(
        json.dumps(profiles, indent=2, sort_keys=True), encoding="utf-8")
    with (out_dir / "items.jsonl").open("w", encoding="utf-8") as f:
        for item in items:
            f.write(json.dumps(item, sort_keys=True) + "\n")

    print()
    print(f"wrote {len(items)} claims over {len(profiles)} profiles to {out_dir}")
    if excluded:
        print("excluded skills (a label here could land on the wrong skill):")
        for skill, why in sorted(excluded.items()):
            print(f"  {skill}: {why}")
    unreachable = unreachable_skills(taxonomy)
    if unreachable:
        print(f"{len(unreachable)} skills cannot appear as claims at all -- no "
              f"canonical entry (lane C): {', '.join(sorted(unreachable))}")


if __name__ == "__main__":
    main()
