"""write: put the approved keywords into the photos (embedded) or their sidecars.

Photos and RAW files only. Videos are never touched, whatever the state says.
"""
from __future__ import annotations

from pathlib import Path

from .config import Config
from .review import APPROVED, AUTO, effective_location
from .state import State
from .xmp import ExiftoolError, write_keywords

WRITABLE_KINDS = {"photo", "raw"}


def keywords_for(entry: dict) -> list[str]:
    """Approved tags plus the location keyword, without duplicates, in a stable order."""
    keywords = list((entry.get("review") or {}).get("keywords", []))
    location = effective_location(entry).get("keyword")
    if location and location not in keywords:
        keywords.append(location)
    return keywords


def select_files(state: State, prefix: str | None, redo: bool, limit: int | None) -> list[str]:
    keys = []
    for key, entry in sorted(state.files.items()):
        if entry["kind"] not in WRITABLE_KINDS or entry.get("missing"):
            continue
        if (entry.get("review") or {}).get("status") not in (APPROVED, AUTO):
            continue
        if prefix and not key.startswith(prefix.rstrip("/") + "/"):
            continue
        keywords = keywords_for(entry)
        if not keywords or (not redo and entry.get("written") == keywords):
            continue
        keys.append(key)
    return keys[:limit] if limit else keys


def run_write(
    cfg: Config,
    state: State,
    exiftool: str,
    prefix: str | None = None,
    limit: int | None = None,
    apply: bool = False,
    redo: bool = False,
) -> int:
    keys = select_files(state, prefix, redo, limit)
    if not keys:
        print("Nothing to write (approve photos in the review page first).")
        return 0

    done = failed = 0
    for key in keys:
        entry = state.files[key]
        keywords = keywords_for(entry)
        location = effective_location(entry)
        try:
            result = write_keywords(
                cfg.media_root / key, keywords, cfg, exiftool,
                country=location.get("country", ""), city=location.get("city", ""),
                sublocation=location.get("sublocation", ""), dry_run=not apply,
            )
        except ExiftoolError as exc:
            print(f"  FAILED {key}: {exc}")
            entry.setdefault("stages", {})["write"] = f"error: {exc}"
            failed += 1
            continue
        verb = "wrote" if apply else "would write"
        print(f"{verb} {result['mode']:8s} {Path(key).name} -> {Path(result['target']).name}: "
              + ", ".join(k.split("|")[-1] for k in keywords))
        if apply:
            entry["written"] = keywords
            entry.setdefault("stages", {})["write"] = "done"
            done += 1
            if done % cfg.save_every == 0:
                state.save()

    if apply:
        state.save()
    summary = f"{done} written, {failed} failed" if apply else f"{len(keys)} files would be written"
    print(summary + ("" if apply else " (dry run: add --apply to write)"))
    return 1 if failed else 0
