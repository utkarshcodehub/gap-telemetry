"""
Emit a claim-only baseline snapshot: fixed profiles x every role.

Run from backend/:
    python scripts/baseline_snapshot.py                 # write docs/baselines/
    python scripts/baseline_snapshot.py --check         # fail if it has drifted

`--check` is the useful one in CI or before a commit: it regenerates and compares
against the stored snapshot, so any change to scoring behaviour has to be
acknowledged deliberately rather than slipping through.

The profiles below are DELIBERATELY SYNTHETIC and checked in. They are not a
dataset and make no claim to represent real candidates -- labelled ground truth
arrives with Dataset A in Increment 3. Their only job is to be fixed, so a diff
between two snapshots is attributable to a code change and not to data drift.

Market demand still comes from the live database, so a snapshot is only comparable
to another taken against the same corpus. The corpus composition is recorded in the
snapshot header for exactly that reason.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core.db.store import JobStore  # noqa: E402
from core.gap.baseline import as_dict, baseline_for_role  # noqa: E402

OUT_DIR = Path(__file__).resolve().parents[2] / "docs" / "baselines"
SNAPSHOT = OUT_DIR / "claim_only_baseline.json"

#: Fixed synthetic profiles. Chosen to span the range the evidence engine will
#: have to behave sensibly across, including the two awkward ends.
PROFILES: dict[str, dict] = {
    # The empty-GitHub majority case (EC-1). Verified readiness must not punish it.
    "resume_only_fresher": {
        "resume": {"Python", "SQL", "Git", "HTML", "CSS"},
        "github": {},
    },
    # Claims and artifacts agree -- the uninteresting, well-behaved case.
    "aligned_backend": {
        "resume": {"Java", "Spring Boot", "SQL", "REST API", "Docker", "Git"},
        "github": {"Java": 4, "Spring Boot": 3, "Docker": 2, "Git": 6},
    },
    # Claims far exceed artifacts -- where evidence grading should bite hardest.
    "overclaimed": {
        "resume": {"Kubernetes", "Terraform", "AWS", "Docker", "Python",
                   "Machine Learning", "PyTorch", "React", "Node.js"},
        "github": {"Python": 1},
    },
    # Artifacts exceed claims -- drives hidden_strengths, the "you never told
    # anyone you use Redis" feature.
    "underclaimed": {
        "resume": {"Python"},
        "github": {"Python": 5, "Docker": 3, "PostgreSQL": 2, "Redis": 2,
                   "FastAPI": 3, "Git": 7},
    },
    # Nothing recognised at all. A legitimate "start from scratch" state, not an
    # error -- every market skill becomes a gap.
    "empty": {"resume": set(), "github": {}},
}


def build(store: JobStore) -> dict:
    roles = [r["role"] for r in store.roles()]
    provenance = store.provenance("IN")

    results: dict[str, list[dict]] = {}
    for name, profile in PROFILES.items():
        rows = []
        for role in roles:
            market = store.demand(role)
            rows.append(as_dict(baseline_for_role(
                role, market, set(profile["resume"]), dict(profile["github"])
            )))
        results[name] = rows

    return {
        "schema": 1,
        "kind": "claim-only baseline (pre-evidence-engine)",
        "note": (
            "Golden-output baseline, not an accuracy measurement. Records BOTH "
            "candidate definitions of claimed_readiness because "
            "docs/EVIDENCE_MODEL.md section 8.1 leaves that choice open."
        ),
        "corpus": {"market": "IN", "sources": provenance,
                   "total_postings": sum(p["postings"] for p in provenance)},
        "roles": roles,
        "profiles": sorted(PROFILES),
        "results": results,
    }


def _comparable(snapshot: dict) -> dict:
    """The parts a drift check should compare -- excludes the timestamp."""
    return {k: v for k, v in snapshot.items() if k != "generated_at"}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true",
                    help="compare against the stored snapshot; exit 1 on drift")
    args = ap.parse_args()

    store = JobStore()
    try:
        fresh = build(store)
    finally:
        store.close()

    if args.check:
        if not SNAPSHOT.exists():
            raise SystemExit(f"no stored snapshot at {SNAPSHOT}; run without --check")
        stored = json.loads(SNAPSHOT.read_text(encoding="utf-8"))
        if _comparable(stored) == _comparable(fresh):
            print(f"baseline unchanged ({SNAPSHOT.name})")
            return
        # Point at what moved rather than just failing.
        print("BASELINE DRIFT detected.")
        if stored.get("corpus") != fresh.get("corpus"):
            print("  corpus changed -- snapshots are only comparable on the same "
                  "corpus, so regenerate rather than treating this as a code change:")
            print(f"    stored: {stored.get('corpus', {}).get('total_postings')} postings")
            print(f"    fresh : {fresh.get('corpus', {}).get('total_postings')} postings")
        for profile in sorted(set(stored.get("results", {})) | set(fresh["results"])):
            a = {r["role"]: r for r in stored.get("results", {}).get(profile, [])}
            b = {r["role"]: r for r in fresh["results"].get(profile, [])}
            for role in sorted(set(a) | set(b)):
                if a.get(role) != b.get(role):
                    print(f"  {profile} / {role}:")
                    for key in ("readiness_resume_only", "readiness_union",
                                "delta_union_minus_resume_only", "n_gaps"):
                        av, bv = a.get(role, {}).get(key), b.get(role, {}).get(key)
                        if av != bv:
                            print(f"      {key}: {av} -> {bv}")
        raise SystemExit(1)

    fresh["generated_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    SNAPSHOT.write_text(json.dumps(fresh, indent=2, sort_keys=True), encoding="utf-8")
    print(f"wrote {SNAPSHOT}")
    print(f"  {len(fresh['roles'])} roles x {len(PROFILES)} profiles, "
          f"corpus {fresh['corpus']['total_postings']} postings")
    for name in sorted(PROFILES):
        rows = fresh["results"][name]
        ro = sum(r["readiness_resume_only"] for r in rows) / len(rows)
        un = sum(r["readiness_union"] for r in rows) / len(rows)
        print(f"  {name:<22} mean readiness: resume-only {ro:5.1f}  "
              f"union {un:5.1f}  (delta {un - ro:+.1f})")


if __name__ == "__main__":
    main()
