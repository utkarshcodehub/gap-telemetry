"""
Skill extraction engine.

Pipeline:  raw text  ->  clean  ->  tokenize (spaCy)  ->  PhraseMatcher
           ->  canonicalize  ->  deduplicate  ->  ExtractedSkill list
"""

from __future__ import annotations

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
# CamelCase splitter: insert a space before an uppercase letter that follows
# a lowercase letter or digit. Handles TPO-portal-style squished tags like
# "ReactNative" -> "React Native", "MERNStack" -> "MERN Stack".
_CAMEL_RE = re.compile(r"(?<=[a-z0-9])(?=[A-Z])")


def preprocess(text: str) -> str:
    """Normalize messy posting/tag text so tokenization is clean."""
    text = _SEPARATOR_RE.sub(" ", text)
    text = _CAMEL_RE.sub(" ", text)
    text = text.replace("&", " ")
    text = _MULTISPACE_RE.sub(" ", text)
    return text.strip()


def _clean_no_camel_split(text: str) -> str:
    """Same normalization as preprocess(), minus the camelCase split — used
    as extract()'s first pass so a compound word with its own one-word
    taxonomy alias (JavaScript, TypeScript, PostgreSQL, LLaMA) matches
    directly instead of being fragmented into "Java Script" / "Postgre SQL"
    first, where only a wrong or generic sub-match survives."""
    text = _SEPARATOR_RE.sub(" ", text)
    text = text.replace("&", " ")
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
        doc = self.nlp(_clean_no_camel_split(text))
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

        # Second pass: a still-unmatched token might be a camelCase-squished
        # tag with no one-word alias of its own (e.g. "ReactNative" -> the
        # two-word alias "react native"). Split just that leftover token and
        # resolve it directly against the alias map.
        for i, token in enumerate(doc):
            if i in taken:
                continue
            split_text = _CAMEL_RE.sub(" ", token.text)
            if split_text == token.text:
                continue
            canonical = self.taxonomy.canonicalize(split_text)
            if canonical is None:
                continue
            counts[canonical] += 1
            surfaces.setdefault(canonical, set()).add(token.text)

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
