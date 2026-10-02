"""Resume parser: PDF -> raw text -> extracted skills (with evidence)."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from pypdf import PdfReader

from core.extraction.extractor import ExtractedSkill, SkillExtractor

_SECTION_RE = re.compile(
    r"^\s*(skills|technical skills|projects|experience|work experience|"
    r"internships?|education|certifications?|achievements?)\b",
    re.IGNORECASE | re.MULTILINE,
)


@dataclass(frozen=True)
class ResumeProfile:
    raw_text: str
    skills: tuple[ExtractedSkill, ...]
    sections_found: tuple[str, ...]

    @property
    def skill_names(self) -> set[str]:
        return {s.canonical for s in self.skills}


class ResumeParseError(Exception):
    pass


# A resume with less readable text than this almost certainly came out of a
# scanner rather than a word processor. Single source of truth: the API layer
# extracts PDF bytes itself (so it can enforce upload caps before parsing), so
# it calls assert_has_text_layer() directly rather than duplicating the rule.
MIN_TEXT_LAYER_CHARS = 50

_NO_TEXT_LAYER_MSG = (
    "PDF has no readable text layer (likely a scanned image). "
    "Export the resume as a digital PDF from Word/LaTeX/Canva, or paste the text instead."
)


def assert_has_text_layer(text: str) -> None:
    """Raise ResumeParseError if extracted text is too short to be a real resume."""
    if len(text.strip()) < MIN_TEXT_LAYER_CHARS:
        raise ResumeParseError(_NO_TEXT_LAYER_MSG)


def extract_pdf_text(path: Path | str) -> str:
    path = Path(path)
    if not path.exists():
        raise ResumeParseError(f"File not found: {path}")
    try:
        reader = PdfReader(path)
    except Exception as e:
        raise ResumeParseError(f"Could not open PDF: {e}") from e

    text = "\n".join(page.extract_text() or "" for page in reader.pages)
    assert_has_text_layer(text)
    return text


def parse_resume(path: Path | str, extractor: SkillExtractor | None = None) -> ResumeProfile:
    extractor = extractor or SkillExtractor()
    text = extract_pdf_text(path)
    sections = tuple(m.group(1).lower() for m in _SECTION_RE.finditer(text))
    return ResumeProfile(raw_text=text, skills=tuple(extractor.extract(text)), sections_found=sections)


def parse_resume_text(text: str, extractor: SkillExtractor | None = None) -> ResumeProfile:
    extractor = extractor or SkillExtractor()
    sections = tuple(m.group(1).lower() for m in _SECTION_RE.finditer(text))
    return ResumeProfile(raw_text=text, skills=tuple(extractor.extract(text)), sections_found=sections)
