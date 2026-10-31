"""Load config/vocabulary.csv: what the models are asked to look for."""
from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class VocabEntry:
    keyword: str  # hierarchical, e.g. "Marine Life|Reptiles|Sea turtle"
    prompt: str  # natural-language description for generic CLIP
    scientific_name: str  # used instead of the prompt by BioCLIP when present
    scenes: frozenset[str]  # underwater / topside / land
    tier: str  # "core" (groups) or "species"


def load_vocabulary(path: Path, tiers: set[str] | None = None) -> list[VocabEntry]:
    entries = []
    with Path(path).open(newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            tier = (row.get("tier") or "core").strip()
            if tiers and tier not in tiers:
                continue
            entries.append(
                VocabEntry(
                    keyword=row["keyword"].strip(),
                    prompt=row["prompt"].strip(),
                    scientific_name=(row.get("scientific_name") or "").strip(),
                    scenes=frozenset(s.strip() for s in row["scene"].split(";") if s.strip()),
                    tier=tier,
                )
            )
    return entries
