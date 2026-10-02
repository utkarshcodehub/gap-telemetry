"""Ingestion pipeline: PostingRecord list -> extract skills -> Supabase (Postgres).

Batched and resume-safe. Two bugs in the original per-row version, both found
while loading the first real corpus:

1. IT COULDN'T FINISH. One HTTP round trip per posting plus two per extracted
   skill meant ~15 requests per posting -- ~11,800 for 790 postings -- and
   Supabase closed the connection partway through. Now: one existence check and
   one upsert per chunk of postings, one upsert for all distinct skills, and one
   upsert per chunk of links. Roughly 120 requests for the same 790 postings.

2. A CRASH LEFT POSTINGS PERMANENTLY SKILL-LESS. The old loop did:

       posting_id = store.insert_posting(rec)
       if posting_id is None:   # already exists (ignore_duplicates)
           continue             # <-- skills never linked

   so any posting written before a crash was skipped on the re-run and never got
   its skills. Those rows then drag every demand percentage DOWN, because they
   inflate the denominator while contributing to no skill's count -- and the
   re-run looks like it succeeded. This matters beyond one-off loads: the live
   JSearch feed runs incrementally by design, so it would have accumulated them
   silently. `store.upsert_postings` now returns ids for existing rows too, and
   skills are linked regardless of whether the posting was new.
"""

from __future__ import annotations

from core.db.store import JobStore, PostingRecord
from core.extraction.extractor import SkillExtractor

#: Postings per batch. Each chunk costs one existence check plus one upsert, and
#: the existence check puts every external_id in the query string, so this is
#: kept well below any URL-length limit.
CHUNK = 100


def ingest_postings(
    records: list[PostingRecord],
    store: JobStore,
    extractor: SkillExtractor | None = None,
) -> int:
    """Ingest records; return the number of postings that were NEW.

    Skills are extracted from `rec.text_for_extraction` (the full description),
    not from `rec.description`, which may hold only a stored excerpt.
    """
    extractor = extractor or SkillExtractor()
    if not records:
        return 0

    # Collapse duplicates on the table's real uniqueness key BEFORE batching.
    # Postgres rejects an upsert whose statement touches the same conflict target
    # twice ("ON CONFLICT DO UPDATE command cannot affect row a second time"), so
    # one duplicated row aborts the whole chunk. A single JSearch response can
    # legitimately return the same posting on two of its pages, so this is a
    # normal input, not a caller error -- it belongs here rather than in each
    # loader.
    deduped: dict[tuple[str, str], PostingRecord] = {}
    for rec in records:
        deduped.setdefault((rec.source, rec.external_id), rec)
    records = list(deduped.values())

    # 1. Extract everything first -- pure CPU, no network.
    extracted: list[list] = [
        list(extractor.extract(rec.text_for_extraction)) for rec in records
    ]

    # 2. Upsert every distinct skill once, rather than once per posting.
    distinct: dict[str, str] = {}
    for skills in extracted:
        for s in skills:
            distinct.setdefault(s.canonical, s.category)
    skill_ids = store.upsert_skills(distinct)

    # 3. Postings and links, chunk by chunk.
    newly_inserted = 0
    for start in range(0, len(records), CHUNK):
        chunk = records[start:start + CHUNK]
        chunk_skills = extracted[start:start + CHUNK]

        # Which of these already exist? Needed only to report an accurate count
        # of new rows -- the upsert below writes either way.
        by_source: dict[str, list[str]] = {}
        for rec in chunk:
            by_source.setdefault(rec.source, []).append(rec.external_id)
        pre_existing: set[tuple[str, str]] = set()
        for source, ext_ids in by_source.items():
            for ext_id in store.existing_posting_ids(source, ext_ids):
                pre_existing.add((source, ext_id))

        posting_ids = store.upsert_postings(chunk)

        links: list[tuple[int, int, int]] = []
        for rec, skills in zip(chunk, chunk_skills):
            posting_id = posting_ids.get((rec.source, rec.external_id))
            if posting_id is None:
                # The upsert didn't return this row; without an id we cannot
                # link skills, so skip rather than write a half-record.
                continue
            if (rec.source, rec.external_id) not in pre_existing:
                newly_inserted += 1
            for s in skills:
                skill_id = skill_ids.get(s.canonical)
                if skill_id is not None:
                    links.append((posting_id, skill_id, s.count))

        store.link_skills(links)

    store.commit()
    return newly_inserted
