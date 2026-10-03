"""
Measure channel-map recall across a cohort of real GitHub profiles.

    cd backend
    python scripts/measure_channel_recall.py                       # frozen cohort
    python scripts/measure_channel_recall.py --sample 20           # draw a new one
    python scripts/measure_channel_recall.py --json out.json

THE PREREQUISITE THIS SATISFIES (docs/PLAN.md section 12). Dataset A must not be
labelled until the channel map's recall is known. On the first real profile the map
recognised 20 of 93 declared packages, and one gap -- `groq` in 12 manifests --
made an LLM-heavy candidate read UNVERIFIABLE for Large Language Models. Had that
profile been labelled first, the error would have entered Dataset A as ground
truth and every confidence constant tuned against it would have been fitted to a
hole in the map rather than to reality.

WHAT IT MEASURES. Two different numbers, because only one of them is honest on its
own:

  1. Coverage -- the share of declared (package, repo) pairs the map recognises.
     Fully automatic, and systematically PESSIMISTIC: most unrecognised packages
     are transitive dependencies that must never map to a skill (channels.py
     lesson 3). A low coverage number is therefore not by itself a defect.

  2. Recall on the labelled head -- of the most frequent unrecognised packages,
     which ones SHOULD have mapped. This needs human judgement, so the judgements
     live in scripts/recall_labels.py with a reason recorded for each, reviewable
     and diffable rather than buried in a notebook.

Recall is reported over DECLARATIONS, not distinct package names: a package in
twelve repos misleads twelve times and a package in one misleads once, so weighting
them equally would understate exactly the gaps that matter most.

Misses are split by who can fix them -- the map (lane A, here) or the taxonomy
(lane C, FR-18). A package naming a skill the taxonomy does not contain cannot be
verified however good this map gets, and saying so is the point.

Collection runs at the SAME budget as /analyze (150 requests, 25 repos), so the
result describes the map as the product actually exercises it. The earlier
measurement already showed the per-repo manifest cap was never the binding
constraint, so widening it here would only make the number flattering.

Cache note: this writes to data/cache/recall/, NOT the demo cache, so a
measurement never evicts or ages what scripts/prewarm_cache.py warmed.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from datetime import date
from pathlib import Path
from urllib.parse import quote

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.settings import get_settings  # noqa: E402
from core.evidence.channels import CHANNELS  # noqa: E402
from core.evidence.github import (  # noqa: E402
    API,
    _matches,
    GitHubClient,
    RequestBudget,
    collect_profile,
    evidence_from_profile,
)
from core.evidence.model import Tier  # noqa: E402
from core.taxonomy.loader import Taxonomy  # noqa: E402
from scripts.recall_labels import LABELS, Verdict  # noqa: E402

CACHE_DIR = Path(__file__).resolve().parents[1] / "data" / "cache" / "recall"
COHORT_FILE = Path(__file__).resolve().parent / "recall_cohort.txt"

#: Same as /analyze. See the module docstring.
BUDGET_PER_PROFILE = 150

#: The head of the frequency distribution, defined by a threshold rather than a
#: rank so the frontier does not move every time a fix is made. Every unrecognised
#: package declared at least this many times across the cohort must be judged;
#: recall is claimed over exactly that set and the doc says so. Below it sits a
#: long tail of one- and two-off names whose labels could not move any number.
MIN_DECLARATIONS = 3


# ------------------------------------------------------------------ the map


def package_to_skills() -> dict[str, list[str]]:
    """Every package name the channel map knows, lowercased, to its skills.

    One package can evidence several skills (`express` is both Express.js and
    Node.js), which is why this is a list.
    """
    out: dict[str, list[str]] = defaultdict(list)
    for skill, spec in CHANNELS.items():
        for pkg in spec.packages:
            out[pkg.lower()].append(skill)
    return dict(out)


# --------------------------------------------------------------- the cohort


def read_cohort(path: Path) -> list[str]:
    """One username per line; `#` comments and blanks ignored."""
    if not path.exists():
        return []
    out = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.split("#", 1)[0].strip()
        if line:
            out.append(line)
    return out


#: Two sampling frames, because one frame answers the wrong question.
#:
#: `population` is who the product is FOR: accounts reporting an Indian location
#: with at least ten public repos, newest first -- students and early-career
#: developers. It says what coverage looks like in the wild, and most of these
#: repos turn out to declare no dependencies at all, which is itself a result.
#:
#: `dense` is who Dataset A will be DRAWN FROM: the same population filtered to
#: visibly active accounts, which is where dependency manifests actually live. The
#: map's holes only show up against profiles that declare enough to expose them;
#: measuring recall on repos with no manifests would measure nothing.
#:
#: Both frames are biased -- self-reported location, and a follower count as a
#: proxy for activity. Written down rather than corrected: a stated bias beats an
#: unstated convenience sample.
FRAMES = {
    "population": ("location:India repos:>=10 type:user", "joined"),
    "dense": ("location:India repos:>=20 followers:>=20 type:user", "repositories"),
}


def sample_cohort(client: GitHubClient, n: int, *, frame: str = "population",
                  per_page: int = 100) -> list[str]:
    """Draw candidate profiles from GitHub's user search. See FRAMES."""
    query, sort = FRAMES[frame]
    q = quote(query)
    url = f"{API}/search/users?q={q}&sort={sort}&order=desc&per_page={per_page}"
    found: list[str] = []
    page = 1
    while len(found) < n and page <= 10:
        body = client.get_json(f"{url}&page={page}")
        items = (body or {}).get("items") or []
        if not items:
            break
        found.extend(i["login"] for i in items)
        page += 1
    return found[:n]


# ----------------------------------------------------------- the measurement


def measure_profile(username: str, token: str | None) -> dict | None:
    """Collect one profile and reduce it to package counts. None if it failed."""
    client = GitHubClient(token=token, budget=RequestBudget(limit=BUDGET_PER_PROFILE),
                          cache_dir=CACHE_DIR)
    try:
        prof = collect_profile(client, username)
    except Exception as e:                           # noqa: BLE001 - report, continue
        print(f"  {username:<24} FAILED  {type(e).__name__}: {e}")
        return None

    # Per-repo package sets, so a package in twelve repos counts twelve times.
    pkg_repos: dict[str, int] = defaultdict(int)
    for repo in prof.repos:
        for pkg in repo.packages:
            pkg_repos[pkg] += 1

    ev = evidence_from_profile(prof)
    evidenced = [e for e in ev if e.max_tier is not None]

    # Per REPO: which skills any channel already evidenced there, and which
    # packages the map did not recognise. This is what separates a package the map
    # misses from a skill the map misses -- `lucide-react` being unmapped costs
    # nothing in a repo where `react` is right next to it, and everything in a repo
    # where it is the only React signal. Only the second kind can put a wrong
    # label into Dataset A.
    known = package_to_skills()
    repo_detail = [
        {
            "repo": repo.name,
            "evidenced": sorted(s for s, spec in CHANNELS.items()
                                if spec.verifiable and _matches(spec, repo)),
            "unrecognised": sorted(p for p in repo.packages if p not in known),
        }
        for repo in prof.repos
    ]

    return {
        "username": username,
        "repos": len(prof.repos),
        "repos_with_a_manifest": sum(1 for r in prof.repos if r.manifest_retrieved),
        "partial": prof.partial,
        "requests": prof.requests_spent,
        "packages": dict(pkg_repos),
        "repo_detail": repo_detail,
        "skills_with_evidence": len(evidenced),
        "skills_at_declared": sum(1 for e in evidenced if e.max_tier is Tier.DECLARED),
    }


def blind_spots(profiles: list[dict]) -> dict[str, dict]:
    """Declarations where an unmapped package was a skill's ONLY signal in its repo.

    These are the misses that change an outcome. Everything else the map missed was
    covered by a sibling signal, so it costs nothing but a lower coverage number.
    """
    out: dict[str, dict] = {}
    for p in profiles:
        for repo in p["repo_detail"]:
            evidenced = set(repo["evidenced"])
            for pkg in repo["unrecognised"]:
                label = LABELS.get(pkg)
                if label is None or label.verdict != Verdict.SKILL or not label.skill:
                    continue
                if label.skill in evidenced:
                    continue        # a sibling signal already proved it
                row = out.setdefault(pkg, {"skill": label.skill, "repos": 0,
                                           "profiles": set()})
                row["repos"] += 1
                row["profiles"].add(p["username"])
    for row in out.values():
        row["profiles"] = len(row["profiles"])
    return out


def aggregate(profiles: list[dict]) -> dict:
    """Fold per-profile counts into one package table.

    `repos` is the declaration count -- the unit recall is measured in.
    """
    known = package_to_skills()
    table: dict[str, dict] = {}
    for p in profiles:
        for pkg, n in p["packages"].items():
            row = table.setdefault(pkg, {"repos": 0, "profiles": 0, "skills": known.get(pkg, [])})
            row["repos"] += n
            row["profiles"] += 1
    return table


# ---------------------------------------------------------------- reporting


def classify(pkg: str, taxonomy: Taxonomy) -> tuple[str, str, str]:
    """(verdict, target skill, note) for an unrecognised package.

    An unlabelled package is reported as such rather than silently assumed to be
    noise. Assuming it would let the recall number improve by not looking.
    """
    label = LABELS.get(pkg)
    if label is None:
        return (Verdict.UNLABELLED, "", "")
    verdict, target, note = label.verdict, label.skill, label.note
    if verdict != Verdict.SKILL or not target:
        return (verdict, target, note)

    # Three ways a real skill is still not the map's to fix. Each was found by
    # trying to make the fix and noticing it would have been wrong.
    canonical = taxonomy.canonicalize(target)
    if canonical is None:
        # Nothing to attach a channel to. Lane C's FR-18.
        return (Verdict.NO_TAXONOMY_ENTRY, target, "no canonical entry")
    if canonical != target:
        # The taxonomy CONFLATES this skill with another one, so mapping the
        # package would verify the wrong skill -- `beautifulsoup4` would evidence
        # "Selenium" for someone who has never used Selenium. A false
        # verification is the worst failure this project can produce, so the
        # conflation has to be fixed before the channel is.
        return (Verdict.NO_TAXONOMY_ENTRY, target,
                f"the taxonomy folds it into '{canonical}'")
    spec = CHANNELS.get(canonical)
    if spec is not None and not spec.verifiable:
        # Deliberately not artifact-verifiable (EC-9). Attaching packages here
        # would quietly reclassify a concept as checkable; channels.py already
        # says the concrete tools need their own taxonomy entries.
        return (Verdict.NO_TAXONOMY_ENTRY, target,
                f"'{canonical}' is unverifiable by design; needs its own entry")
    return (verdict, target, note)


def report(profiles: list[dict], table: dict, taxonomy: Taxonomy) -> dict:
    total_decl = sum(r["repos"] for r in table.values())
    known_decl = sum(r["repos"] for r in table.values() if r["skills"])
    distinct_known = sum(1 for r in table.values() if r["skills"])

    unrecognised = sorted(((pkg, r) for pkg, r in table.items() if not r["skills"]),
                          key=lambda kv: (-kv[1]["repos"], kv[0]))
    head = [(pkg, r) for pkg, r in unrecognised if r["repos"] >= MIN_DECLARATIONS]
    tail = len(unrecognised) - len(head)

    print()
    print("COHORT")
    print(f"  profiles measured     : {len(profiles)}")
    print(f"  repos                 : {sum(p['repos'] for p in profiles)}")
    print(f"  repos with a manifest : {sum(p['repos_with_a_manifest'] for p in profiles)}")
    print(f"  partial collections   : {sum(1 for p in profiles if p['partial'])}")
    print(f"  requests spent        : {sum(p['requests'] for p in profiles)}")

    print()
    print("COVERAGE  (pessimistic: most misses are transitive deps and should stay unmapped)")
    print(f"  distinct packages     : {len(table)}  ({distinct_known} recognised)")
    print(f"  declarations          : {total_decl}  ({known_decl} recognised)")
    if total_decl:
        print(f"  declaration coverage  : {known_decl / total_decl:.1%}")

    buckets: dict[str, list[tuple[str, dict, str, str]]] = defaultdict(list)
    for pkg, row in head:
        verdict, target, note = classify(pkg, taxonomy)
        buckets[verdict].append((pkg, row, target, note))

    missed_map = sum(r["repos"] for _, r, _, _ in buckets[Verdict.SKILL])
    missed_tax = sum(r["repos"] for _, r, _, _ in buckets[Verdict.NO_TAXONOMY_ENTRY])
    unlabelled = buckets[Verdict.UNLABELLED]

    print()
    print(f"RECALL  (over the {len(head)} unrecognised packages declared "
          f"{MIN_DECLARATIONS}+ times; {tail} rarer ones left unjudged)")
    denom = known_decl + missed_map + missed_tax
    if denom:
        print(f"  map recall            : {known_decl / (known_decl + missed_map):.1%}"
              f"   ({missed_map} declarations the map should have caught)")
        print(f"  end-to-end recall     : {known_decl / denom:.1%}"
              f"   (also counting {missed_tax} blocked by a missing taxonomy entry)")
    if unlabelled:
        print(f"  ** {len(unlabelled)} head packages are UNLABELLED -- recall above is "
              f"not trustworthy until they are judged **")

    for verdict, title in (
        (Verdict.SKILL, "MISSES THE MAP CAN FIX (lane A -- add to channels.py)"),
        (Verdict.NO_TAXONOMY_ENTRY, "MISSES THE MAP CANNOT FIX (lane C -- no canonical skill)"),
        (Verdict.UNLABELLED, "UNJUDGED -- add to scripts/recall_labels.py"),
    ):
        rows = buckets[verdict]
        if not rows:
            continue
        print()
        print(title)
        for pkg, row, target, note in sorted(rows, key=lambda x: -x[1]["repos"]):
            shown = f"-> {target}" if target else note
            if verdict == Verdict.NO_TAXONOMY_ENTRY:
                shown = f"-> {target}  ({note})"
            print(f"  {row['repos']:>4} repos  {row['profiles']:>3} profiles  "
                  f"{pkg:<28} {shown}")

    noise = buckets[Verdict.TRANSITIVE] + buckets[Verdict.NOT_A_SKILL] + \
        buckets[Verdict.PARSER_ARTIFACT]
    print()
    print(f"CORRECTLY UNMAPPED  {len(noise)} of the head "
          f"({sum(r['repos'] for _, r, _, _ in noise)} declarations): "
          f"{len(buckets[Verdict.TRANSITIVE])} transitive, "
          f"{len(buckets[Verdict.NOT_A_SKILL])} not a skill, "
          f"{len(buckets[Verdict.PARSER_ARTIFACT])} parser artifacts")

    spots = blind_spots(profiles)
    print()
    print("BLIND SPOTS -- the only misses that can change a verdict")
    print("  (an unmapped package that was its skill's ONLY signal in that repo)")
    if not spots:
        print("  none: every miss had a sibling signal in the same repo")
    for pkg, row in sorted(spots.items(), key=lambda kv: -kv[1]["repos"]):
        bucket, _, why = classify(pkg, taxonomy)
        where = "MAP" if bucket == Verdict.SKILL else f"not the map: {why}"
        print(f"  {row['repos']:>4} repos  {row['profiles']:>3} profiles  "
              f"{pkg:<28} {row['skill']:<16} fix: {where}")

    return {
        "measured_at": date.today().isoformat(),
        "profiles": profiles,
        "declarations": total_decl,
        "declarations_recognised": known_decl,
        "distinct_packages": len(table),
        "distinct_recognised": distinct_known,
        "head_size": len(head),
        "tail_unjudged": tail,
        "missed_fixable_by_map": missed_map,
        "missed_blocked_by_taxonomy": missed_tax,
        "unlabelled_head": [p for p, _, _, _ in unlabelled],
        "blind_spots": spots,
        "head": [
            {"package": pkg, "repos": r["repos"], "profiles": r["profiles"],
             "verdict": classify(pkg, taxonomy)[0], "skill": classify(pkg, taxonomy)[1]}
            for pkg, r in head
        ],
    }


def main() -> None:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--frame", choices=sorted(FRAMES), default="population",
                    help="sampling frame; also picks the default cohort file")
    ap.add_argument("--cohort", type=Path,
                    help="usernames, one per line (default: recall_cohort_<frame>.txt)")
    ap.add_argument("--sample", type=int, metavar="N",
                    help="draw N profiles from GitHub search and freeze them to --cohort")
    ap.add_argument("--json", type=Path, help="write the full result here")
    args = ap.parse_args()
    if args.cohort is None:
        args.cohort = COHORT_FILE.with_name(f"recall_cohort_{args.frame}.txt")

    settings = get_settings()
    if not settings.github_token:
        print("GITHUB_TOKEN is not set: 60 requests/hour is not enough for a cohort.")
        sys.exit(2)

    if args.sample:
        client = GitHubClient(token=settings.github_token,
                              budget=RequestBudget(limit=20), cache_dir=CACHE_DIR)
        drawn = sample_cohort(client, args.sample, frame=args.frame)
        existing = read_cohort(args.cohort)
        merged = existing + [u for u in drawn if u not in existing]
        args.cohort.write_text(
            "# Frozen cohort for the channel-map recall measurement.\n"
            "# Sampling frame: see sample_cohort() in measure_channel_recall.py.\n"
            + "\n".join(merged) + "\n", encoding="utf-8")
        print(f"froze {len(merged)} usernames to {args.cohort}")

    cohort = read_cohort(args.cohort)
    if not cohort:
        ap.error(f"no cohort: {args.cohort} is empty or missing. Use --sample N.")

    print(f"MEASURING {len(cohort)} profiles  (cache {CACHE_DIR})")
    profiles = []
    for name in cohort:
        p = measure_profile(name, settings.github_token)
        if p is None:
            continue
        print(f"  {name:<24} {p['repos']:>3} repos  "
              f"{len(p['packages']):>4} packages  {p['requests']:>4} requests"
              f"{'  PARTIAL' if p['partial'] else ''}")
        profiles.append(p)

    if not profiles:
        print("nothing collected")
        sys.exit(1)

    table = aggregate(profiles)
    result = report(profiles, table, Taxonomy())
    result["packages"] = table

    if args.json:
        args.json.write_text(json.dumps(result, indent=2, sort_keys=True), encoding="utf-8")
        print(f"\nwrote {args.json}")


if __name__ == "__main__":
    main()
