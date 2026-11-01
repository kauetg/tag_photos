"""Edit config/locations.csv (folder names -> places) and config/date_ranges.csv (date -> place)."""
from __future__ import annotations

import csv
import os
import shutil
from collections import Counter
from dataclasses import dataclass, replace
from pathlib import Path

from .config import normalize, parse_folder_date
from .state import State

NAME_COLUMNS = ["match", "keyword", "country", "city", "sublocation"]
DATE_COLUMNS = ["start", "end", "keyword", "country", "city", "sublocation", "note"]
KEYWORD_ROOT = "Location"


@dataclass(frozen=True)
class NameRule:
    """A word in a folder name that means a place, e.g. 'Rawa' -> Rawa Island."""

    match: str
    keyword: str
    country: str = ""
    city: str = ""
    sublocation: str = ""


@dataclass(frozen=True)
class DateRule:
    """A stretch of days (YYYYMMDD, inclusive) spent in one place; used when no folder name matches."""

    start: str
    end: str
    keyword: str
    country: str = ""
    city: str = ""
    sublocation: str = ""
    note: str = ""


def default_keyword(country: str, city: str, sublocation: str) -> str:
    """'Location|Malaysia|Mersing|Rawa Island' from the three fields, skipping blank ones."""
    return "|".join([KEYWORD_ROOT, *(p.strip() for p in (country, city, sublocation) if p and p.strip())])


def _read(path: Path) -> list[dict]:
    if not Path(path).exists():
        return []
    with Path(path).open(newline="", encoding="utf-8") as f:
        return [{k: (v or "").strip() for k, v in row.items()} for row in csv.DictReader(f)]


def load_name_rules(path: Path) -> list[NameRule]:
    return [NameRule(**{c: row.get(c, "") for c in NAME_COLUMNS}) for row in _read(path) if row.get("match")]


def load_date_rules(path: Path) -> list[DateRule]:
    return [DateRule(**{c: row.get(c, "") for c in DATE_COLUMNS}) for row in _read(path) if row.get("start") or row.get("end")]


@dataclass(frozen=True)
class PlaceCoord:
    """Where a place is on the map. `source` is 'osm' (found by name), 'approx' (a nearby or parent place) or 'manual'."""

    keyword: str
    lat: float
    lon: float
    source: str = "manual"


def load_place_coords(path: Path) -> dict[str, PlaceCoord]:
    """keyword -> PlaceCoord, from config/place_coords.csv; rows with unreadable numbers are skipped."""
    coords = {}
    for row in _read(path):
        try:
            coords[row["keyword"]] = PlaceCoord(row["keyword"], float(row["lat"]), float(row["lon"]), row.get("source") or "manual")
        except (KeyError, ValueError):
            continue
    return coords


def save_place_coords(path: Path, coords: dict[str, PlaceCoord]) -> None:
    """Validated, atomic write, sorted by keyword; the previous file is kept as place_coords.csv.bak."""
    problems = [f"{c.keyword}: latitude/longitude out of range." for c in coords.values() if not (-90 <= c.lat <= 90 and -180 <= c.lon <= 180)]
    rows = [replace(c, lat=f"{c.lat:.5f}", lon=f"{c.lon:.5f}") for _, c in sorted(coords.items())]
    _save(path, ["keyword", "lat", "lon", "source"], rows, problems)


def _place_problems(where: str, keyword: str, country: str) -> list[str]:
    problems = []
    if not keyword or not keyword.startswith(KEYWORD_ROOT + "|"):
        problems.append(f"{where}: the keyword must start with {KEYWORD_ROOT}| (e.g. {KEYWORD_ROOT}|Philippines|Bohol).")
    if not country:
        problems.append(f"{where}: the country is empty.")
    return problems


def validate_name_rules(rules: list[NameRule]) -> list[str]:
    problems, seen = [], {}
    for rule in rules:
        where = rule.match or "(empty match)"
        if not rule.match:
            problems.append("A row has no match word.")
            continue
        folded = normalize(rule.match)
        if folded in seen:
            problems.append(f"{where}: written twice (as {seen[folded]}); it would be ambiguous.")
        seen[folded] = rule.match
        problems += _place_problems(where, rule.keyword, rule.country)
    return problems


def validate_date_rules(rules: list[DateRule]) -> list[str]:
    problems = []
    for rule in rules:
        where = f"{rule.start} to {rule.end}"
        start, end = parse_folder_date(rule.start), parse_folder_date(rule.end)
        if start is None or end is None:
            problems.append(f"{where}: dates must be real days written YYYYMMDD.")
        elif end < start:
            problems.append(f"{where}: the end is before the start.")
        problems += _place_problems(where, rule.keyword, rule.country)
    return problems


def _save(path: Path, columns: list[str], rows: list, problems: list[str]) -> None:
    if problems:
        raise ValueError("; ".join(problems))
    path = Path(path)
    if path.exists():
        shutil.copy2(path, path.with_name(path.name + ".bak"))
    tmp = path.with_name(path.name + ".tmp")
    with tmp.open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f, lineterminator="\n")
        writer.writerow(columns)
        for row in rows:
            writer.writerow([getattr(row, c) for c in columns])
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)


def save_name_rules(path: Path, rules: list[NameRule]) -> None:
    """Validated, atomic write; the previous file stays next to it as locations.csv.bak."""
    _save(path, NAME_COLUMNS, rules, validate_name_rules(rules))


def save_date_rules(path: Path, rules: list[DateRule]) -> None:
    """Validated, atomic write; sorted by start date; the previous file is kept as date_ranges.csv.bak."""
    ordered = sorted(rules, key=lambda r: (r.start, r.end))
    _save(path, DATE_COLUMNS, ordered, validate_date_rules(ordered))


def unmapped_folders(state: State) -> Counter:
    """Top-level folders whose files have no place yet, with how many files each: what to add next."""
    counts: Counter = Counter()
    for key, entry in state.files.items():
        if not entry.get("missing") and not entry.get("location"):
            counts[key.split("/", 1)[0] if "/" in key else "(root)"] += 1
    return counts
