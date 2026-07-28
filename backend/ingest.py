"""Ingestion pipeline: PostingRecord list -> extract skills -> SQLite."""

from __future__ import annotations

from core.db.store import JobStore, PostingRecord
from core.extraction.extractor import SkillExtractor


def ingest_postings(records: list[PostingRecord], store: JobStore, extractor: SkillExtractor | None = None) -> int:
    extractor = extractor or SkillExtractor()
    inserted = 0
    for rec in records:
        posting_id = store.insert_posting(rec)
        if posting_id is None:
            continue
        inserted += 1
        for skill in extractor.extract(rec.description):
            skill_id = store.upsert_skill(skill.canonical, skill.category)
            store.link_skill(posting_id, skill_id, skill.count)
    store.commit()
    return inserted
