"""
Ingest the Naukri CC0 corpus (real Indian job postings) into Postgres.

Source
    Kaggle: promptcloud/naukri-job-listing-dataset
    License: CC0 (public domain) -- no attribution obligation, no share-alike.
    Coverage: India, 2020-10-01 to 2020-12-31, 5,000-row sample.
    See backend/data/README.md for the checksum and full provenance.

This replaces scraper/synthetic_generator.py as the source of market demand.
The generator invented its skill probabilities by hand, so every demand
percentage derived from it described a market that does not exist.

Two things this loader does that are easy to get wrong:

1. STORES AN EXCERPT, EXTRACTS FROM THE FULL TEXT. Descriptions here run to a
   median 1,376 and a maximum 10,658 characters. Storing all of them would eat
   the free tier's 500 MB budget for data no query ever reads back -- demand is
   computed from `posting_skills`, not from description text. But extracting
   skills from a truncated excerpt would silently undercount demand. So the
   excerpt goes in `description` and the full text in `extract_text`.

2. DROPS POSTINGS WHOSE ROLE CANNOT BE DETERMINED. `role_query` is NOT NULL and
   drives every demand figure, so a posting with no inferable specialism is
   discarded rather than defaulted. This discards roughly 83% of the file: most
   of it is not tech at all (retail, finance, BPO, medical), and much of the
   rest carries titles like "Software Engineer" or "Associate" that genuinely
   state no specialism. See backend/core/taxonomy/roles.py.

Run from backend/ so pydantic-settings resolves .env (it is CWD-relative):

    cd backend
    python ../scraper/naukri_cc0_ingest.py --dry-run
    python ../scraper/naukri_cc0_ingest.py
"""

from __future__ import annotations

import argparse
import io
import json
import sys
import zipfile
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from core.db.store import JobStore, PostingRecord  # noqa: E402
from core.taxonomy.roles import MIN_POSTINGS_PER_ROLE, map_title  # noqa: E402
from ingest import ingest_postings  # noqa: E402

SOURCE = "naukri-cc0-2020q4"
MARKET = "IN"

DEFAULT_ZIP = (
    Path(__file__).resolve().parents[1]
    / "backend" / "data" / "raw" / "naukri" / "naukri-job-listing-dataset.zip"
)
MEMBER = (
    "marketing_sample_for_naukri_com-naukri_com_job_data__"
    "20201001_20201231__5k_data.ldjson"
)

#: Enough to eyeball a posting or spot-check a skill match in the UI, small
#: enough that 10k postings cost ~5 MB rather than ~40 MB.
EXCERPT_CHARS = 500


def _clean(value: object) -> str:
    if value is None:
        return ""
    return " ".join(str(value).split())


def _salary(rec: dict) -> str:
    offered = _clean(rec.get("salary_offered"))
    if offered and offered not in {"-", "0"}:
        return offered
    lo, hi = _clean(rec.get("inferred_salary_from")), _clean(rec.get("inferred_salary_to"))
    cur = _clean(rec.get("inferred_salary_currency"))
    if lo and hi:
        return f"{cur} {lo}-{hi}".strip()
    return ""


def _location(rec: dict) -> str:
    parts = [_clean(rec.get("city")) or _clean(rec.get("inferred_city")),
             _clean(rec.get("state")) or _clean(rec.get("inferred_state"))]
    return ", ".join(p for p in parts if p)


def load(zip_path: Path) -> tuple[list[PostingRecord], Counter]:
    """Parse the archive into PostingRecords. Returns (records, funnel counts)."""
    stats: Counter = Counter()
    records: list[PostingRecord] = []
    seen_ids: set[str] = set()

    with zipfile.ZipFile(zip_path) as zf, zf.open(MEMBER) as raw:
        for line in io.TextIOWrapper(raw, encoding="utf-8", errors="replace"):
            line = line.strip()
            if not line:
                continue
            stats["rows"] += 1
            rec = json.loads(line)

            # `country` is dirty: '110025 India', 'MYSURU Mysore KA 570001
            # India.', bare pincodes, '-', and 21 rows of 'USA'. Substring match
            # on 'india' is the honest filter; anything else is dropped rather
            # than assumed Indian.
            if "india" not in _clean(rec.get("country")).lower():
                stats["dropped_not_india"] += 1
                continue
            stats["india"] += 1

            title = _clean(rec.get("job_title"))
            role = map_title(title)
            if role is None:
                stats["dropped_unmappable_role"] += 1
                continue

            description = _clean(rec.get("job_description"))
            if not description:
                stats["dropped_no_description"] += 1
                continue

            external_id = _clean(rec.get("uniq_id"))
            if not external_id or external_id in seen_ids:
                stats["dropped_duplicate_id"] += 1
                continue
            seen_ids.add(external_id)

            stats["kept"] += 1
            stats[f"role:{role}"] += 1
            records.append(PostingRecord(
                source=SOURCE,
                external_id=external_id,
                title=title,
                company=_clean(rec.get("company_name")),
                location=_location(rec),
                experience="",          # not present in this corpus
                salary=_salary(rec),
                description=description[:EXCERPT_CHARS],
                role_query=role,
                market=MARKET,
                extract_text=description,
            ))
    return records, stats


def report(stats: Counter, records: list[PostingRecord]) -> None:
    print("FUNNEL")
    for key in ("rows", "india", "dropped_not_india", "dropped_unmappable_role",
                "dropped_no_description", "dropped_duplicate_id", "kept"):
        print(f"  {key:<26} {stats[key]:>6,}")
    print()
    roles = Counter({k[5:]: v for k, v in stats.items() if k.startswith("role:")})
    print(f"PER-ROLE (floor {MIN_POSTINGS_PER_ROLE})")
    for role, n in roles.most_common():
        mark = "ok       " if n >= MIN_POSTINGS_PER_ROLE else "LOW-CONF "
        print(f"  {mark} {role:<24} {n:>5,}")
    print()
    if records:
        stored = sum(len(r.description) for r in records)
        full = sum(len(r.extract_text or "") for r in records)
        print(f"description text: storing {stored:,} chars of {full:,} "
              f"({stored / full * 100:.1f}%) -- excerpt saves {(full - stored) / 1024:.0f} KB")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--zip", type=Path, default=DEFAULT_ZIP)
    ap.add_argument("--dry-run", action="store_true",
                    help="parse and report, write nothing")
    ap.add_argument("--limit", type=int, default=0,
                    help="ingest at most N records (0 = all)")
    args = ap.parse_args()

    if not args.zip.exists():
        raise SystemExit(f"archive not found: {args.zip}")

    records, stats = load(args.zip)
    report(stats, records)

    if args.limit:
        records = records[:args.limit]
        print(f"\n--limit {args.limit}: ingesting {len(records)} of {stats['kept']}")

    if args.dry_run:
        print("\n--dry-run: nothing written.")
        return

    store = JobStore()
    try:
        inserted = ingest_postings(records, store)
        print(f"\n{len(records)} records, {inserted} newly inserted. "
              f"DB postings total: {store.posting_count()}")
    finally:
        store.close()


if __name__ == "__main__":
    main()
