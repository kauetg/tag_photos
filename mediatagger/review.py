"""Review layer: suggestions as a table (export) and the human decisions stored beside them."""
from __future__ import annotations

import csv
from pathlib import Path

from .state import State

THRESHOLD = 0.5  # suggestions at least this likely start out ticked in the review page
PENDING, APPROVED, SKIPPED = "pending", "approved", "skipped"


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


def decide(entry: dict, keywords: list[str], approved: bool) -> None:
    entry["review"] = {"status": APPROVED if approved else SKIPPED, "keywords": keywords if approved else []}


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
            loc = entry.get("location") or {}
            scene = max(tags["scene"], key=tags["scene"].get) if tags.get("scene") else ""
            out.writerow([
                key, loc.get("country", ""), loc.get("city", ""), scene,
                "; ".join(label(k) for k in suggested(entry, threshold)),
                "; ".join(f"{label(s['keyword'])} {s['prob']:.2f}" for s in tags["suggestions"]),
                status(entry),
                "; ".join(entry.get("review", {}).get("keywords", [])),
            ])
    return len(keys)
