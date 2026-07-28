"""
Skill extraction engine.

Pipeline:  raw text  ->  clean  ->  tokenize (spaCy)  ->  PhraseMatcher
           ->  canonicalize  ->  deduplicate  ->  ExtractedSkill list
"""

import re
from collections import Counter
from dataclasses import dataclass

import spacy
from spacy.matcher import PhraseMatcher

from core.taxonomy.loader import Taxonomy


@dataclass(frozen=True)
class ExtractedSkill:
    canonical: str
    category: str
    count: int
    surface_forms: tuple[str, ...]


_SEPARATOR_RE = re.compile(r"[,/|•·;()\[\]{}]+")
_MULTISPACE_RE = re.compile(r"\s+")


def preprocess(text: str) -> str:
    text = _SEPARATOR_RE.sub(" ", text)
    text = _MULTISPACE_RE.sub(" ", text)
    return text.strip()


class SkillExtractor:
    def __init__(self, taxonomy: Taxonomy | None = None):
        self.taxonomy = taxonomy or Taxonomy()
        self.nlp = spacy.blank("en")
        self.matcher = PhraseMatcher(self.nlp.vocab, attr="LOWER")

        for skill in self.taxonomy.skills:
            patterns = list(
                self.nlp.pipe({skill.canonical.lower(), *skill.aliases})
            )
            self.matcher.add(skill.canonical, patterns)

    def extract(self, text: str) -> list[ExtractedSkill]:
        doc = self.nlp(preprocess(text))
        matches = self.matcher(doc, as_spans=True)

        matches = sorted(matches, key=lambda s: (-(s.end - s.start), s.start))
        taken: set[int] = set()
        kept = []
        for span in matches:
            token_ids = range(span.start, span.end)
            if any(t in taken for t in token_ids):
                continue
            taken.update(token_ids)
            kept.append(span)

        counts: Counter[str] = Counter()
        surfaces: dict[str, set[str]] = {}
        for span in kept:
            canonical = self.nlp.vocab.strings[span.label]
            counts[canonical] += 1
            surfaces.setdefault(canonical, set()).add(span.text)

        return [
            ExtractedSkill(
                canonical=name,
                category=self.taxonomy.category_map[name],
                count=count,
                surface_forms=tuple(sorted(surfaces[name])),
            )
            for name, count in counts.most_common()
        ]

    def extract_names(self, text: str) -> set[str]:
        return {s.canonical for s in self.extract(text)}
