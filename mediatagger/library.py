"""Library index: search photos and videos by tag, place, date and folder; open them on disk.

Pure logic over state.json (the Streamlit page is a thin layer on top). Nothing here
writes to media files.
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from .config import normalize
from .review import AUTO, APPROVED, effective_location, effective_scene, status, suggested
from .state import State

KINDS = {"video": {"video"}, "photo": {"photo", "raw"}}


def entry_keywords(entry: dict) -> list[str]:
    """Hierarchical keywords this file can be found by, plus its location."""
    if entry["kind"] == "video":
        keywords = [t["keyword"] for t in (entry.get("video") or {}).get("tags", [])]
    elif status(entry) in (APPROVED, AUTO):
        keywords = list(entry["review"]["keywords"])
    else:
        keywords = suggested(entry)
    location = effective_location(entry).get("keyword")
    return [*keywords, location] if location else keywords


def indexed(entry: dict) -> bool:
    """True when the file has been through the stage that produces its tags."""
    if entry.get("missing"):
        return False
    return bool(entry.get("video")) if entry["kind"] == "video" else bool(entry.get("tags"))


def haystack(key: str, entry: dict) -> str:
    return normalize(" ".join([key, *entry_keywords(entry)]))


def matching_tags(entry: dict, text: str) -> list[dict]:
    """Video tags that match the search (all of them when there is no search text)."""
    tags = (entry.get("video") or {}).get("tags", [])
    terms = normalize(text).split()
    if not terms:
        return tags
    return [t for t in tags if any(term in normalize(t["keyword"]) for term in terms)]


def search(
    state: State,
    text: str = "",
    kinds: tuple[str, ...] = ("video", "photo"),
    country: str | None = None,
    city: str | None = None,
    scene: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    folder: str | None = None,
    drive: str | None = None,
    drives: set[str] | None = None,
) -> list[str]:
    """Keys of the files matching every filter; every word of `text` must match somewhere."""
    wanted = set().union(*(KINDS[k] for k in kinds)) if kinds else set()
    terms = normalize(text).split()
    found = []
    for key, entry in state.files.items():
        if entry["kind"] not in wanted or not indexed(entry):
            continue
        location = effective_location(entry)
        if country and location.get("country") != country:
            continue
        if city and location.get("city") != city:
            continue
        if scene and effective_scene(entry) != scene:
            continue
        date = entry.get("folder_date") or ""
        if (date_from and date < date_from) or (date_to and date > date_to):
            continue
        if folder and not key.startswith(folder + "/"):
            continue
        if drive and not key.startswith(drive + "/"):
            continue
        if drives is not None and drive_of(key) not in drives:
            continue
        if terms:
            hay = haystack(key, entry)
            if not all(term in hay for term in terms):
                continue
        found.append(key)
    return sorted(found, key=lambda k: (state.files[k].get("folder_date") or "", k))


def dive_folder(key: str) -> str:
    """The top-level folder (one dive / one day) a file lives in, with its drive: 'Splash IV/20250101 Foo'."""
    return "/".join(key.split("/")[:2])


def dive_name(key: str) -> str:
    """Just the folder name, without the drive."""
    return key.split("/")[1] if key.count("/") >= 2 else ""


def drive_of(key: str) -> str:
    return key.split("/", 1)[0]


def videos_near(state: State, key: str) -> list[str]:
    """Indexed videos from the same dive folder: where to look for the video behind a photo."""
    folder = dive_folder(key)
    return sorted(
        k for k, e in state.files.items()
        if e["kind"] == "video" and indexed(e) and dive_folder(k) == folder
    )


def filter_options(state: State) -> dict[str, list[str]]:
    countries, cities, folders, drives = set(), set(), set(), set()
    for key, entry in state.files.items():
        if not indexed(entry):
            continue
        location = effective_location(entry)
        countries.add(location.get("country") or "")
        cities.add(location.get("city") or "")
        folders.add(dive_folder(key))
        drives.add(drive_of(key))
    return {
        "drive": sorted(drives),
        "country": sorted(c for c in countries if c),
        "city": sorted(c for c in cities if c),
        "folder": sorted(folders),
    }


def format_time(seconds: float) -> str:
    seconds = int(round(seconds))
    hours, rest = divmod(seconds, 3600)
    minutes, secs = divmod(rest, 60)
    return f"{hours}:{minutes:02d}:{secs:02d}" if hours else f"{minutes}:{secs:02d}"


def open_file(path: Path) -> None:
    """Open with the default app (the page runs on the same machine as the browser)."""
    if sys.platform == "win32":
        os.startfile(str(path))  # noqa: S606 - user-initiated, local path from our own index
    else:
        subprocess.Popen(["open" if sys.platform == "darwin" else "xdg-open", str(path)])


def open_in_vlc(path: Path, seconds: float, vlc: str | None) -> None:
    """Play from `seconds` in VLC; without VLC, fall back to the default player from the start."""
    if vlc:
        subprocess.Popen([vlc, f"--start-time={int(seconds)}", str(path)])
    else:
        open_file(path)


def reveal_in_folder(path: Path) -> None:
    """Show the file selected in the system file manager."""
    if sys.platform == "win32":
        subprocess.Popen(["explorer", f"/select,{path}"])
    elif sys.platform == "darwin":
        subprocess.Popen(["open", "-R", str(path)])
    else:
        subprocess.Popen(["xdg-open", str(path.parent)])
