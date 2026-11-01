"""scan: inventory media files into state.json (incremental, read-only on the media)."""
from __future__ import annotations

import hashlib
import os
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterator

from .config import Config
from .state import State, split_key

HASH_CHUNK = 64 * 1024


@dataclass
class ScanReport:
    new: int = 0
    changed: int = 0
    unchanged: int = 0
    missing: int = 0
    errors: int = 0
    unmapped: Counter = field(default_factory=Counter)  # top-level folder -> files


def quick_hash(path: str, size: int) -> str:
    """Cheap fingerprint: size plus first and last 64 KB."""
    h = hashlib.sha1(str(size).encode())
    with open(path, "rb") as f:
        h.update(f.read(HASH_CHUNK))
        if size > 2 * HASH_CHUNK:
            f.seek(-HASH_CHUNK, os.SEEK_END)
            h.update(f.read(HASH_CHUNK))
    return h.hexdigest()


def resolve_roots(cfg: Config, folder: str | None) -> list[Path]:
    """Folders to scan: --folder if given, otherwise folders.txt ('*' = media_root)."""
    entries = [folder] if folder else cfg.folders
    if not entries:
        raise SystemExit("No folders to scan: fill config/folders.txt or pass --folder.")
    roots = []
    for entry in entries:
        path = cfg.media_root if entry == "*" else Path(entry)
        if not path.is_absolute():
            path = cfg.media_root / path
        roots.append(path)
    return roots


def iter_media(directory: str, cfg: Config) -> Iterator[os.DirEntry]:
    """Yield media files under `directory`, skipping ignored folders, in stable order."""
    try:
        entries = sorted(os.scandir(directory), key=lambda e: e.name.lower())
    except OSError as exc:
        print(f"  warning: cannot read {directory}: {exc}")
        return
    for entry in entries:
        if entry.is_dir(follow_symlinks=False):
            if not cfg.is_ignored_dir(entry.name):
                yield from iter_media(entry.path, cfg)
        elif entry.is_file() and cfg.kind_of(entry.name):
            yield entry


def _folder_date(parts: tuple[str, ...]) -> str | None:
    for part in parts:
        head = part[:8]
        if len(head) == 8 and head.isdigit():
            return head
    return None


def resolve_location(cfg: Config, folder_parts: tuple[str, ...], folder_date: str | None) -> dict | None:
    """Folder name first; the date range is only a fallback. None when neither knows the place."""
    by_name = cfg.find_location(folder_parts)
    by_date = None if by_name else cfg.find_location_by_date(folder_date)
    return by_name.as_dict("name") if by_name else by_date.as_dict("date") if by_date else None


def relocate(cfg: Config, state: State) -> dict[str, int]:
    """Re-run the location rules over every file already in the state (after editing the CSVs).

    Only the folder/date location is recomputed; a place you picked in the review page is kept.
    """
    counts = {"changed": 0, "unchanged": 0, "without_location": 0}
    cache: dict[tuple[str, ...], dict | None] = {}
    for key, entry in state.files.items():
        parts = tuple(Path(split_key(key)[1]).parts[:-1])
        if (parts, entry.get("folder_date")) not in cache:
            cache[(parts, entry.get("folder_date"))] = resolve_location(cfg, parts, entry.get("folder_date"))
        location = cache[(parts, entry.get("folder_date"))]
        if location != entry.get("location"):
            entry["location"] = location
            counts["changed"] += 1
        else:
            counts["unchanged"] += 1
        counts["without_location"] += location is None
    return counts


def scan(
    cfg: Config,
    state: State,
    roots: list[Path],
    dry_run: bool = False,
    limit: int | None = None,
) -> ScanReport:
    if not cfg.drive:
        raise SystemExit("Which drive is this? Pass --drive NAME (see `tagger drives`).")
    report = ScanReport()
    seen: set[str] = set()
    visited = 0
    processed_since_save = 0
    location_cache: dict[tuple[str, ...], object] = {}

    for root in roots:
        if not root.is_dir():
            print(f"  warning: folder not found: {root}")
            continue
        for entry in iter_media(str(root), cfg):
            if limit is not None and visited >= limit:
                break
            visited += 1

            rel = Path(entry.path).relative_to(cfg.media_root)
            key = f"{cfg.drive}/{rel.as_posix()}"
            seen.add(key)
            stat = entry.stat()
            old = state.files.get(key)

            if old and old["size"] == stat.st_size and old["mtime"] == stat.st_mtime_ns:
                report.unchanged += 1
                continue

            report.changed += bool(old)
            report.new += not old

            folder_parts = rel.parts[:-1]
            folder_date = _folder_date(folder_parts)
            if folder_parts not in location_cache:
                location_cache[folder_parts] = resolve_location(cfg, folder_parts, folder_date)
            location = location_cache[folder_parts]
            if location is None:
                report.unmapped[folder_parts[0] if folder_parts else "(root)"] += 1

            if dry_run:
                continue

            digest = None
            if cfg.quick_hash:
                try:
                    digest = quick_hash(entry.path, stat.st_size)
                except OSError as exc:
                    report.errors += 1
                    print(f"  warning: cannot hash {key}: {exc}")

            state.files[key] = {
                "kind": cfg.kind_of(entry.name),
                "size": stat.st_size,
                "mtime": stat.st_mtime_ns,
                "hash": digest,
                "folder_date": folder_date,
                "location": location,
                "stages": {"scan": "done"},
                "missing": False,
            }

            processed_since_save += 1
            if processed_since_save >= cfg.save_every:
                state.save()
                processed_since_save = 0
                print(f"  ... {visited} files visited, index saved")
        else:
            continue
        break  # limit reached inside the inner loop

    # Missing detection only makes sense after a full pass over the scanned roots.
    if limit is None:
        prefixes = [r.relative_to(cfg.media_root).as_posix() for r in roots if r.is_dir()]
        for key, entry in state.files.items():
            drive, rel = split_key(key)
            if drive != cfg.drive:
                continue
            in_scope = any(p in (".", "") or rel.startswith(p + "/") for p in prefixes)
            if in_scope and key not in seen and not entry.get("missing"):
                report.missing += 1
                if not dry_run:
                    entry["missing"] = True

    if not dry_run:
        state.save()
    return report


def write_unmapped_report(cfg: Config, report: ScanReport) -> Path | None:
    if not report.unmapped:
        return None
    path = cfg.data_dir / "reports" / "unmapped_folders.txt"
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [f"{count:6d}  {name}" for name, count in report.unmapped.most_common()]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path
