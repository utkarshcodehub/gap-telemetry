"""
Taxonomy loader.

Loads the skill taxonomy JSON and exposes:
  1. skills          -> list of Skill objects (canonical + category + aliases)
  2. alias_map       -> dict: lowercase alias -> canonical name
  3. category_map    -> dict: canonical name -> category

Design decision (interview-worthy):
We resolve everything to a *canonical* name so that "reactjs", "React.js"
and "react js" all count as ONE skill when we compute market demand
frequencies. Without normalization, demand counts fragment and the gap
score becomes meaningless.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

TAXONOMY_PATH = Path(__file__).parent / "skills_taxonomy.json"


@dataclass(frozen=True)
class Skill:
    canonical: str
    category: str
    aliases: tuple[str, ...] = field(default_factory=tuple)


class Taxonomy:
    def __init__(self, path: Path = TAXONOMY_PATH):
        raw = json.loads(path.read_text(encoding="utf-8"))
        self.skills: list[Skill] = [
            Skill(
                canonical=s["canonical"],
                category=s["category"],
                aliases=tuple(a.lower().strip() for a in s["aliases"]),
            )
            for s in raw["skills"]
        ]

        self.alias_map: dict[str, str] = {}
        self.category_map: dict[str, str] = {}

        for skill in self.skills:
            self.category_map[skill.canonical] = skill.category
            self.alias_map[skill.canonical.lower()] = skill.canonical
            for alias in skill.aliases:
                existing = self.alias_map.get(alias)
                if existing and existing != skill.canonical:
                    raise ValueError(
                        f"Alias collision: '{alias}' maps to both "
                        f"'{existing}' and '{skill.canonical}'"
                    )
                self.alias_map[alias] = skill.canonical

    def canonicalize(self, surface_form: str) -> str | None:
        return self.alias_map.get(surface_form.lower().strip())

    def all_aliases(self) -> list[str]:
        return list(self.alias_map.keys())

    def __len__(self) -> int:
        return len(self.skills)
