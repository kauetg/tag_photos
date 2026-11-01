"""config/vocabulary.csv: what the models are asked to look for, plus the tags you apply by hand."""
from __future__ import annotations

import csv
import os
import shutil
from dataclasses import dataclass
from pathlib import Path

SCENES = ("underwater", "topside", "land")
TIERS = ("core", "species", "manual")
COLUMNS = ["keyword", "prompt", "scientific_name", "scene", "tier", "aliases"]


@dataclass(frozen=True)
class VocabEntry:
    keyword: str  # hierarchical, e.g. "Marine Life|Reptiles|Sea turtle"
    prompt: str  # natural-language description for generic CLIP
    scientific_name: str  # used instead of the prompt by BioCLIP when present
    scenes: frozenset[str]  # underwater / topside / land
    tier: str  # "core" (groups), "species", or "manual" (only ever applied by hand)
    aliases: tuple[str, ...] = ()  # other words that should find this tag when typing


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
                    prompt=(row.get("prompt") or "").strip(),
                    scientific_name=(row.get("scientific_name") or "").strip(),
                    scenes=frozenset(s.strip() for s in (row.get("scene") or "").split(";") if s.strip()),
                    tier=tier,
                    aliases=tuple(a.strip() for a in (row.get("aliases") or "").split(";") if a.strip()),
                )
            )
    return entries


def validate(entries: list[VocabEntry]) -> list[str]:
    """Human-readable problems, empty when the vocabulary is safe to save."""
    problems = []
    seen: dict[str, str] = {}
    core = {e.keyword for e in entries if e.tier == "core"}
    for e in entries:
        where = e.keyword or "(empty keyword)"
        if not e.keyword or any(not part.strip() for part in e.keyword.split("|")):
            problems.append(f"{where}: the keyword needs every level filled in (A|B|C).")
            continue
        folded = e.keyword.casefold()
        if folded in seen:
            problems.append(f"{e.keyword}: duplicated (also written as {seen[folded]}).")
        seen[folded] = e.keyword
        if e.tier not in TIERS:
            problems.append(f"{e.keyword}: tier must be one of {', '.join(TIERS)}.")
        if e.tier != "manual" and not e.prompt:
            problems.append(f"{e.keyword}: the prompt is empty, the model needs it.")
        if not e.scenes or not e.scenes <= set(SCENES):
            problems.append(f"{e.keyword}: scene must be some of {', '.join(SCENES)}, separated by ';'.")
        if e.tier == "species" and e.keyword.rsplit("|", 1)[0] not in core:
            problems.append(f"{e.keyword}: a species needs a core group right above it.")
    return problems


def save_vocabulary(path: Path, entries: list[VocabEntry]) -> None:
    """Validated, atomic write; the previous file is kept next to it as vocabulary.csv.bak."""
    problems = validate(entries)
    if problems:
        raise ValueError("; ".join(problems))
    path = Path(path)
    if path.exists():
        shutil.copy2(path, path.with_name(path.name + ".bak"))
    tmp = path.with_name(path.name + ".tmp")
    with tmp.open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f, lineterminator="\n")
        writer.writerow(COLUMNS)
        for e in entries:
            writer.writerow([
                e.keyword, e.prompt, e.scientific_name, ";".join(s for s in SCENES if s in e.scenes),
                e.tier, "; ".join(e.aliases),
            ])
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)


def add_manual_tag(path: Path, parent: str, name: str, aliases: str = "") -> str:
    """Add a hand-applied tag under `parent`; returns its full keyword."""
    name = name.strip()
    if not name or "|" in name:
        raise ValueError("Give the tag a name, without the | character.")
    keyword = f"{parent}|{name}" if parent else name
    entries = load_vocabulary(path)
    entries.append(
        VocabEntry(
            keyword=keyword, prompt=name, scientific_name="", scenes=frozenset(SCENES), tier="manual",
            aliases=tuple(a.strip() for a in aliases.replace(";", ",").split(",") if a.strip()),
        )
    )
    save_vocabulary(path, entries)
    return keyword


def ancestors(entries: list[VocabEntry]) -> list[str]:
    """Every group path in the vocabulary ('Marine Life', 'Marine Life|Fish', ...): where a new tag can go."""
    paths = set()
    for e in entries:
        parts = e.keyword.split("|")
        paths.update("|".join(parts[:i]) for i in range(1, len(parts)))
    return sorted(paths)


def pretty(entry_or_keyword: VocabEntry | str, vocab: dict[str, VocabEntry] | None = None) -> str:
    """'Marine Life › Reptiles › Sea turtle (turtle)': the path plus aliases, for typing-to-search pickers."""
    keyword = entry_or_keyword if isinstance(entry_or_keyword, str) else entry_or_keyword.keyword
    entry = entry_or_keyword if not isinstance(entry_or_keyword, str) else (vocab or {}).get(keyword)
    text = keyword.replace("|", " › ")
    return f"{text} ({', '.join(entry.aliases)})" if entry and entry.aliases else text
