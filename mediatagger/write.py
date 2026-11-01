"""write: bring the photos' XMP in line with what you approved.

Adds what is missing and removes what this tool wrote earlier and you have since un-ticked; keywords it never
wrote (yours from Lightroom, say) are left alone. ARW/GPR get a sidecar .xmp; the extensions listed in the
config's [write] embedded get the XMP inside the file. Photos and RAW files only: videos are never touched.
"""
from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from .config import Config
from .review import APPROVED, AUTO, effective_location, effective_scene
from .state import State
from .xmp import ExiftoolError, sync_keywords

WRITABLE_KINDS = {"photo", "raw"}
LOCATION_FIELDS = ("country", "city", "sublocation")
EMBEDDABLE = [".jpg", ".jpeg", ".dng"]  # what --embed and the Write page's "embedded" option turn on


def keywords_for(entry: dict) -> list[str]:
    """Approved tags plus the location keyword, without duplicates, in a stable order."""
    keywords = list((entry.get("review") or {}).get("keywords", []))
    location = effective_location(entry).get("keyword")
    if location and location not in keywords:
        keywords.append(location)
    return keywords


def desired_for(entry: dict) -> tuple[list[str], dict]:
    """(keywords, location fields) the file should carry. Photos not approved should carry nothing of ours."""
    if (entry.get("review") or {}).get("status") not in (APPROVED, AUTO):
        return [], {}
    place = effective_location(entry)
    return keywords_for(entry), {f: place[f] for f in LOCATION_FIELDS if place.get(f)}


def is_dirty(entry: dict) -> bool:
    """True when the file is out of date: never written, or what you approved changed since it was written."""
    keywords, location = desired_for(entry)
    written = entry.get("written")
    if written is None and not keywords:
        return False  # never written and nothing to write
    if sorted(keywords) != sorted(written or []):
        return True
    # Entries written by an older version have no record of the location; leave those alone.
    return "written_location" in entry and location != entry["written_location"]


def candidates(
    state: State, prefix: str | None = None, scene: str | None = None, limit: int | None = None, include_clean: bool = False,
) -> list[str]:
    """Photos whose files need updating, in path order. `include_clean` also lists up-to-date ones."""
    keys = []
    for key, entry in sorted(state.files.items()):
        if entry["kind"] not in WRITABLE_KINDS or entry.get("missing"):
            continue
        if prefix and not key.startswith(prefix.rstrip("/") + "/"):
            continue
        if scene and effective_scene(entry) != scene:
            continue
        keywords, _ = desired_for(entry)
        if include_clean:
            if not keywords and entry.get("written") is None:
                continue
        elif not is_dirty(entry):
            continue
        keys.append(key)
    return keys[:limit] if limit else keys


def with_embedding(cfg: Config, embedded: bool) -> Config:
    """A copy of the config that embeds JPG/DNG (True) or writes a sidecar for every format (False)."""
    return replace(cfg, embedded_exts=list(EMBEDDABLE) if embedded else [])


def plan_for(cfg: Config, state: State, exiftool: str, key: str) -> dict:
    """What writing this photo would change, without touching it."""
    entry = state.files[key]
    keywords, location = desired_for(entry)
    return sync_keywords(
        cfg.media_root / key, keywords, entry.get("written") or [], cfg, exiftool,
        location, entry.get("written_location"), dry_run=True,
    )


def apply_for(cfg: Config, state: State, exiftool: str, key: str) -> dict:
    """Write this photo, read it back, and record what was written. Raises ExiftoolError if exiftool refuses."""
    entry = state.files[key]
    keywords, location = desired_for(entry)
    result = sync_keywords(
        cfg.media_root / key, keywords, entry.get("written") or [], cfg, exiftool,
        location, entry.get("written_location"), dry_run=False,
    )
    if result.get("verified", True):
        entry["written"] = keywords
        entry["written_location"] = location
        entry["written_at"] = result["time"]
        entry.setdefault("stages", {})["write"] = "done"
    else:
        entry.setdefault("stages", {})["write"] = "error: " + "; ".join(result["problems"])
    return result


def describe(result: dict) -> str:
    """One line for a plan or a result: '+Sea turtle, -Hawksbill, place Komodo'."""
    short = lambda items: ", ".join(k.split("|")[-1] for k in items)
    parts = []
    if result["add"]:
        parts.append(f"+ {short(result['add'])}")
    if result["remove"]:
        parts.append(f"- {short(result['remove'])}")
    if result["location_set"]:
        parts.append("place " + ", ".join(result["location_set"].values()))
    if result["location_clear"]:
        parts.append("place cleared")
    return "; ".join(parts) or "nothing to change"


def run_write(
    cfg: Config,
    state: State,
    exiftool: str,
    prefix: str | None = None,
    limit: int | None = None,
    apply: bool = False,
    redo: bool = False,
) -> int:
    keys = candidates(state, prefix, limit=limit, include_clean=redo)
    if not keys:
        print("Nothing to write: every approved photo is already up to date.")
        return 0

    done = failed = changed = 0
    for key in keys:
        try:
            result = apply_for(cfg, state, exiftool, key) if apply else plan_for(cfg, state, exiftool, key)
        except ExiftoolError as exc:
            print(f"  FAILED {key}: {exc}")
            state.files[key].setdefault("stages", {})["write"] = f"error: {exc}"
            failed += 1
            continue
        if not result.get("verified", True):
            print(f"  NOT VERIFIED {key}: {'; '.join(result['problems'])}")
            failed += 1
            continue
        verb = "wrote" if apply else "would write"
        print(f"{verb} {result['mode']:8s} {Path(key).name}: {describe(result)}")
        done += 1
        changed += not result["nothing_to_do"]
        if apply and done % cfg.save_every == 0:
            state.save()

    if apply:
        state.save()
    summary = f"{done} checked, {changed} changed, {failed} failed" if apply else f"{changed} of {len(keys)} files would change"
    print(summary + ("" if apply else " (dry run: add --apply to write)"))
    return 1 if failed else 0
