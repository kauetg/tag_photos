"""Review layer: suggestions as a table (export) and the human decisions stored beside them."""
from __future__ import annotations

import csv
import hashlib
from pathlib import Path

from .state import State

THRESHOLD = 0.5  # suggestions at least this likely start out ticked in the review page
AUTO_THRESHOLD = 0.9  # core tags this likely are approved without a human
SAMPLE_EVERY = 50  # one in N auto-approvable photos is still shown, as a spot check
PENDING, APPROVED, SKIPPED, AUTO = "pending", "approved", "skipped", "auto"


def suggested(entry: dict, threshold: float = THRESHOLD) -> list[str]:
    tags = entry.get("tags") or {}
    return [s["keyword"] for s in tags.get("suggestions", []) if s["prob"] >= threshold]


def status(entry: dict) -> str:
    return (entry.get("review") or {}).get("status", PENDING)


def tagged_keys(state: State, prefix: str | None = None) -> list[str]:
    """Photos that have suggestions, in path order."""
    keys = []
    for key, entry in sorted(state.files.items()):
        if entry.get("missing") or not entry.get("tags"):
            continue
        if prefix and not key.startswith(prefix.rstrip("/") + "/"):
            continue
        keys.append(key)
    return keys


def is_sample(key: str, every: int = SAMPLE_EVERY) -> bool:
    """Stable spot-check pick: the same photos every run, spread evenly."""
    return int(hashlib.sha1(key.encode("utf-8")).hexdigest()[:8], 16) % every == 0


def triage(entry: dict, auto: float = AUTO_THRESHOLD, uncertain: float = THRESHOLD) -> tuple[str, list[str]]:
    """('auto', keywords) when no human is needed, else ('review', []).

    Only core (group) tags can be automatic: species are where the model errs.
    A photo with any core tag between `uncertain` and `auto` is left for a human.
    """
    core = [s for s in (entry.get("tags") or {}).get("suggestions", []) if s["tier"] == "core"]
    if any(uncertain <= s["prob"] < auto for s in core):
        return "review", []
    return "auto", [s["keyword"] for s in core if s["prob"] >= auto]


def apply_triage(
    state: State, auto: float = AUTO_THRESHOLD, uncertain: float = THRESHOLD, only_new: bool = False,
) -> dict[str, int]:
    """Mark the clear photos as auto-approved. Never touches a human decision.

    `only_new` leaves every photo that already has a review entry alone, so opening the review page
    never overrides thresholds you applied from the command line.
    """
    counts = {AUTO: 0, "review": 0, "sample": 0, "kept": 0}
    for key in tagged_keys(state):
        entry = state.files[key]
        if status(entry) not in (PENDING, AUTO) or (only_new and "review" in entry):
            counts["kept"] += 1  # a person (or an earlier triage) already decided
            continue
        entry.pop("review", None)  # recompute, so changed thresholds or a re-tag take effect
        verdict, keywords = triage(entry, auto, uncertain)
        if verdict == "review":
            counts["review"] += 1
        elif is_sample(key):
            counts["sample"] += 1  # looks clear, but a person confirms a few
        else:
            entry["review"] = {"status": AUTO, "keywords": keywords}
            counts[AUTO] += 1
    return counts


def decide(entry: dict, keywords: list[str], approved: bool, location: dict | None = None) -> None:
    """Store the human decision. `location` is set only when the person changed the place."""
    entry["review"] = {"status": APPROVED if approved else SKIPPED, "keywords": keywords if approved else []}
    if approved and location:
        entry["review"]["location"] = location


def effective_location(entry: dict) -> dict:
    """The place to use for a photo: the one picked in review, else the one from folder/date."""
    return (entry.get("review") or {}).get("location") or entry.get("location") or {}


def known_locations(cfg) -> list[dict]:
    """Every place named in locations.csv and date_ranges.csv, for the review page's location picker."""
    places = {}
    for item in [*cfg.locations, *cfg.date_ranges]:
        loc = getattr(item, "location", item)  # a DateRange carries its Location
        if loc.keyword:
            places[(loc.keyword, loc.city, loc.sublocation)] = {
                "keyword": loc.keyword, "country": loc.country, "city": loc.city, "sublocation": loc.sublocation,
            }
    return sorted(places.values(), key=lambda p: (p["country"], p["city"], p["sublocation"], p["keyword"]))


def place_label(place: dict) -> str:
    parts = [p for p in (place.get("sublocation"), place.get("city"), place.get("country")) if p]
    return ", ".join(parts) or place.get("keyword", "(no location)")


def split_by_confidence(entry: dict, auto: float = AUTO_THRESHOLD) -> tuple[list[str], list[str]]:
    """(sure, unsure) suggestion keywords: core tags at least `auto` likely, then everything else."""
    sure, unsure = [], []
    for s in (entry.get("tags") or {}).get("suggestions", []):
        (sure if s["tier"] == "core" and s["prob"] >= auto else unsure).append(s["keyword"])
    return sure, unsure


def label(keyword: str) -> str:
    return keyword.split("|")[-1]


def export_csv(state: State, path: Path, threshold: float = THRESHOLD) -> int:
    """One row per tagged photo; utf-8-sig so Excel opens accents correctly."""
    keys = tagged_keys(state)
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8-sig") as f:
        out = csv.writer(f)
        out.writerow(["file", "country", "city", "scene", "suggested", "all_suggestions", "status", "approved"])
        for key in keys:
            entry = state.files[key]
            tags = entry["tags"]
            loc = effective_location(entry)
            scene = max(tags["scene"], key=tags["scene"].get) if tags.get("scene") else ""
            out.writerow([
                key, loc.get("country", ""), loc.get("city", ""), scene,
                "; ".join(label(k) for k in suggested(entry, threshold)),
                "; ".join(f"{label(s['keyword'])} {s['prob']:.2f}" for s in tags["suggestions"]),
                status(entry),
                "; ".join(entry.get("review", {}).get("keywords", [])),
            ])
    return len(keys)
