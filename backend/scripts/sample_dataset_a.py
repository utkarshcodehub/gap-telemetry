"""
Draw a role-stratified candidate pool for Dataset A.

    cd backend
    python scripts/sample_dataset_a.py                      # preview, freezes nothing
    python scripts/sample_dataset_a.py --per-role 2 --freeze # commit to a cohort

WHY NOT REUSE THE RECALL COHORTS. They were drawn to stress the channel map, and
the `dense` frame turned out to be substantially Android, Kotlin and React Native
-- which matches NONE of the eight roles in our posting corpus. A Dataset A built
from them would measure verification on a population the product does not serve,
and E1's headline number would not transfer. They are also the profiles that
informed the map, so evaluating on them would be testing on training data; both
this script and the task builder refuse them.

METHOD. One stratum per role, so every role in the corpus is represented:

  1. REPOSITORY search per role, by the topic and language characteristic of that
     role, and take the owners. Repository search is used rather than user search
     because a role is a thing people BUILD, and topics describe repositories.
  2. Cheap screen, one request each: real user (not an organisation), >= 10 public
     repos, an Indian location, not already in a recall cohort.
  3. Expensive screen, one collection each: >= 10 non-fork repos and -- the gate
     that matters -- >= 3 repos with a parseable dependency manifest. Only 26% of
     this population's repos have one (RN-1), so without this gate a profile
     exercises the file-tree channel and nothing else, and the dataset would
     measure one channel of three and call it the evidence model.

The drop-out rate at each stage is printed, because it is itself a finding about
the population and belongs in the report.

Repository search cannot filter by owner location, so step 1 is role-targeted and
step 2 is population-targeted. Doing it in that order costs one request per
candidate instead of collecting everyone; the bias this introduces -- Indian
developers who publish role-typical, topic-tagged repositories -- is stated rather
than corrected, like every other frame in this project.

Handles are never printed or written: the output is aliases plus the gitignored
mapping, exactly as the recall cohorts are (DSA-xx).
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from urllib.parse import quote

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.settings import get_settings  # noqa: E402
from core.evidence.github import (  # noqa: E402
    API,
    GitHubClient,
    RequestBudget,
    collect_profile,
)
from scripts.measure_channel_recall import (  # noqa: E402
    CACHE_DIR,
    COHORT_FILE,
    read_alias_map,
    read_cohort,
    write_alias_map,
)

COHORT_OUT = COHORT_FILE.with_name("dataset_a_cohort.txt")

#: Role -> repository-search query. The corpus's eight roles, each matched by what
#: its practitioners actually publish. Approximate by construction: a topic tag is
#: a claim by the repo's author, which is why it only picks the POOL -- every
#: candidate is then screened on artifacts, which are not self-reported.
ROLE_QUERIES: dict[str, str] = {
    "backend developer": "topic:spring-boot language:Java",
    "frontend developer": "topic:react language:TypeScript",
    "full stack developer": "topic:mern-stack",
    "devops engineer": "topic:terraform language:HCL",
    "qa engineer": "topic:selenium",
    "data engineer": "topic:etl language:Python",
    "data analyst": "topic:data-analysis",
    "ai ml engineer": "topic:machine-learning language:Python",
}

#: Gates. Each one traces to something measured; see the module docstring.
MIN_PUBLIC_REPOS = 10
MIN_NON_FORK_REPOS = 10
MIN_REPOS_WITH_MANIFEST = 3
RECENT_PUSH_MONTHS = 24.0

INDIA = ("india", "bharat", "bengaluru", "bangalore", "mumbai", "delhi", "pune",
         "hyderabad", "chennai", "kolkata", "noida", "gurgaon", "gurugram",
         "ahmedabad", "jaipur", "kochi", "coimbatore", "indore", "lucknow",
         "bhopal", "nagpur", "surat", "patna", "chandigarh", "vizag",
         "visakhapatnam", "thiruvananthapuram", "mysore", "nashik", "vadodara")


def looks_indian(location: str | None) -> bool:
    """Self-reported and therefore imperfect, like every location filter.

    A city list rather than the country alone, because most people write the city.
    False negatives (an unlisted town) cost a candidate; false positives are
    unlikely. Erring toward dropping candidates is the right direction: the pool
    is large and the gates are supposed to be strict.
    """
    if not location:
        return False
    low = location.lower()
    return any(token in low for token in INDIA)


def owners_for_role(client: GitHubClient, query: str, *, want: int) -> list[str]:
    """Distinct repository owners matching a role's query, most recently pushed first.

    Sorted by recency, NOT by stars. A first pass sorted by stars rejected 56 of 60
    candidates on location, because star-ranked results are dominated by famous
    international projects -- the wrong population twice over, since a
    many-thousand-star maintainer is not who this product is for either. Recency
    surfaces ordinary active repositories, which is both the population we want and
    a far cheaper screen.
    """
    q = quote(f"{query} fork:false")
    seen: list[str] = []
    for page in (1, 2, 3):
        body = client.get_json(
            f"{API}/search/repositories?q={q}&sort=updated&order=desc"
            f"&per_page=100&page={page}")
        items = (body or {}).get("items") or []
        if not items:
            break
        for repo in items:
            owner = (repo.get("owner") or {})
            if owner.get("type") == "User" and owner.get("login") not in seen:
                seen.append(owner["login"])
        if len(seen) >= want:
            break
    return seen


def cheap_screen(client: GitHubClient, handle: str) -> tuple[bool, str]:
    user = client.get_json(f"{API}/users/{handle}")
    if not user:
        return False, "could not fetch the account"
    if user.get("type") != "User":
        return False, "not a personal account"
    if (user.get("public_repos") or 0) < MIN_PUBLIC_REPOS:
        return False, f"{user.get('public_repos')} public repos"
    if not looks_indian(user.get("location")):
        return False, "location not recognised as Indian"
    return True, "ok"


def artifact_screen(client: GitHubClient, handle: str) -> tuple[bool, str, dict]:
    prof = collect_profile(client, handle)
    non_fork = len(prof.repos)
    with_manifest = sum(1 for r in prof.repos if r.manifest_retrieved)
    recent = sum(1 for r in prof.repos
                 if r.pushed_months_ago is not None
                 and r.pushed_months_ago <= RECENT_PUSH_MONTHS)
    stats = {"repos": non_fork, "with_manifest": with_manifest, "recent": recent,
             "partial": prof.partial}
    if non_fork < MIN_NON_FORK_REPOS:
        return False, f"{non_fork} non-fork repos", stats
    if with_manifest < MIN_REPOS_WITH_MANIFEST:
        return False, f"only {with_manifest} repos declare dependencies", stats
    if not recent:
        return False, "nothing pushed in 24 months", stats
    return True, "ok", stats


def main() -> None:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--per-role", type=int, default=2,
                    help="profiles to accept per role (8 roles x 2 = the plan's 16)")
    ap.add_argument("--pool-per-role", type=int, default=12,
                    help="candidates to screen per role before giving up")
    ap.add_argument("--freeze", action="store_true",
                    help="write the cohort and the alias mapping; off by default, "
                         "because choosing the evaluation cohort is a decision")
    ap.add_argument("--roles", nargs="*", default=sorted(ROLE_QUERIES),
                    help="limit to these roles")
    args = ap.parse_args()

    settings = get_settings()
    if not settings.github_token:
        sys.exit("GITHUB_TOKEN is not set: screening needs more than 60 requests/hour.")

    in_recall: set[str] = set()
    mapping = read_alias_map()
    for frame in ("population", "dense"):
        for alias in read_cohort(COHORT_FILE.with_name(f"recall_cohort_{frame}.txt")):
            if alias in mapping:
                in_recall.add(mapping[alias])

    client = GitHubClient(token=settings.github_token,
                          budget=RequestBudget(limit=4000), cache_dir=CACHE_DIR)

    accepted: dict[str, list[tuple[str, dict]]] = {}
    tally = {"searched": 0, "cheap_rejected": 0, "artifact_rejected": 0,
             "in_recall_cohort": 0, "accepted": 0}

    for role in args.roles:
        query = ROLE_QUERIES[role]
        print(f"\n{role}   ({query})")
        pool = owners_for_role(client, query, want=args.pool_per_role)
        keep: list[tuple[str, dict]] = []
        for handle in pool:
            if len(keep) >= args.per_role:
                break
            tally["searched"] += 1
            if handle in in_recall:
                tally["in_recall_cohort"] += 1
                print("  -  (skipped: informed the channel map)")
                continue
            ok, why = cheap_screen(client, handle)
            if not ok:
                tally["cheap_rejected"] += 1
                print(f"  -  rejected: {why}")
                continue
            ok, why, stats = artifact_screen(client, handle)
            if not ok:
                tally["artifact_rejected"] += 1
                print(f"  -  rejected: {why}  ({stats['repos']} repos)")
                continue
            keep.append((handle, stats))
            tally["accepted"] += 1
            print(f"  +  ACCEPTED  {stats['repos']} repos, "
                  f"{stats['with_manifest']} with a manifest, "
                  f"{stats['recent']} pushed recently")
        accepted[role] = keep
        if len(keep) < args.per_role:
            print(f"  ** only {len(keep)} of {args.per_role} found; raise "
                  f"--pool-per-role or relax a gate deliberately **")

    print(f"\n{'=' * 70}")
    print("DROP-OUT  (a finding about the population, not just bookkeeping)")
    for k, v in tally.items():
        print(f"  {k:<20} {v}")
    screened = tally["searched"] - tally["in_recall_cohort"]
    if screened:
        print(f"  acceptance rate      {tally['accepted'] / screened:.0%} of "
              f"{screened} screened")
    print(f"  requests spent       {client.budget.spent}")

    if not args.freeze:
        print("\nPREVIEW ONLY -- nothing was written. Re-run with --freeze to commit "
              "to this cohort.")
        return

    n = len(mapping)
    lines = []
    for role, keep in accepted.items():
        lines.append(f"# {role}")
        for handle, _ in keep:
            n += 1
            alias = f"DSA-{n:02d}"
            mapping[alias] = handle
            lines.append(alias)
    write_alias_map(mapping)
    COHORT_OUT.write_text(
        "# Dataset A cohort, role-stratified. ANONYMISED -- handles live only in\n"
        "# backend/data/recall_cohort_map.json, which is gitignored.\n"
        "# Selection method and gates: scripts/sample_dataset_a.py.\n"
        + "\n".join(lines) + "\n", encoding="utf-8")
    print(f"\nfroze {tally['accepted']} aliases to {COHORT_OUT}")


if __name__ == "__main__":
    main()
