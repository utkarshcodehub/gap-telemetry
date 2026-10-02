"""
Human-readable descriptions of each market-data source.

The UI must be able to attribute a demand percentage to the data behind it,
because the corpus is mixed: an archival sample from Q4 2020 sits alongside a
live feed. A reader who cannot tell which is which cannot judge whether a number
describes today's market -- and the difference is not cosmetic. The 2020 sample
contains no LLM, RAG, MLOps or AI-agent postings at all, because that market did
not exist yet.

These labels live here, in one place on the server, rather than in the frontend,
so the UI never has to infer or invent a provenance claim.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class SourceInfo:
    label: str
    vintage: str
    #: True when the source is refreshed on an ongoing basis, so its postings
    #: describe the market now rather than at a fixed point in the past.
    live: bool


SOURCE_INFO: dict[str, SourceInfo] = {
    "naukri-cc0-2020q4": SourceInfo(
        label="Naukri (CC0 sample)", vintage="Q4 2020", live=False
    ),
    "jsearch": SourceInfo(
        label="Live job feed", vintage="current", live=True
    ),
    # Retained only so a stray fixture row is labelled honestly rather than
    # silently passing as real market data. The generator is test-only; see
    # backend/data/README.md.
    "synthetic": SourceInfo(
        label="SYNTHETIC — test fixture, not real market data",
        vintage="n/a", live=False,
    ),
}


def describe(source: str) -> dict:
    """Describe one source. Unknown sources are reported as unknown, not guessed."""
    info = SOURCE_INFO.get(source)
    if info is None:
        return {"source": source, "label": source, "vintage": "unknown", "live": False}
    return {
        "source": source,
        "label": info.label,
        "vintage": info.vintage,
        "live": info.live,
    }
