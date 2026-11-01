"""The file index: one entry per media file, keyed "<drive name>/<path on the drive>", kept in SQLite.

`State.files` is still a plain dict of entries, so the stages mutate entries as before; `save()` writes only the
entries that changed, in one transaction (a crash leaves the previous index intact).
"""
from __future__ import annotations

import json
from pathlib import Path

from .drives import connect
from .vocabulary import LEGACY_SCENES


def split_key(key: str) -> tuple[str, str]:
    """'Splash IV/20250101 Foo/a.ARW' -> ('Splash IV', '20250101 Foo/a.ARW')."""
    drive, _, rel = key.partition("/")
    return drive, rel


def migrate_scene_names(files: dict[str, dict]) -> None:
    """Rename the old scene 'topside' to 'drone' wherever it was stored. Safe to run on every load."""
    for entry in files.values():
        for holder in (entry.get("tags"), entry.get("video")):
            scene = (holder or {}).get("scene")
            if scene and any(name in scene for name in LEGACY_SCENES):
                holder["scene"] = {LEGACY_SCENES.get(name, name): value for name, value in scene.items()}
        review = entry.get("review") or {}
        if review.get("scene") in LEGACY_SCENES:
            review["scene"] = LEGACY_SCENES[review["scene"]]


def _dump(entry: dict) -> str:
    return json.dumps(entry, ensure_ascii=False)


class State:
    def __init__(self, path: Path):
        self.path = Path(path)
        self.files: dict[str, dict] = {}
        self._saved: dict[str, str] = {}  # key -> JSON as last read from or written to the database

    @classmethod
    def load(cls, path: Path) -> "State":
        state = cls(path)
        if state.path.exists():
            conn = connect(state.path)
            try:
                for row in conn.execute("SELECT key, data FROM files"):
                    state.files[row["key"]] = json.loads(row["data"])
                    state._saved[row["key"]] = row["data"]
            finally:
                conn.close()
            migrate_scene_names(state.files)
        return state

    def save(self, keys: list[str] | None = None) -> None:
        """Write what changed. `keys` limits the check to those entries (a review click touches one file)."""
        wanted = self.files.keys() if keys is None else [k for k in keys if k in self.files]
        changed = {}
        for key in wanted:  # serialise everything first: a bad entry must fail before anything is written
            text = _dump(self.files[key])
            if self._saved.get(key) != text:
                changed[key] = text
        gone = [k for k in self._saved if k not in self.files] if keys is None else []
        if not changed and not gone:
            return
        conn = connect(self.path)
        try:
            with conn:
                for key, text in changed.items():
                    entry = self.files[key]
                    conn.execute(
                        "INSERT OR REPLACE INTO files (key, drive, kind, folder_date, missing, data) VALUES (?,?,?,?,?,?)",
                        (key, split_key(key)[0], entry.get("kind"), entry.get("folder_date"), int(bool(entry.get("missing"))), text),
                    )
                conn.executemany("DELETE FROM files WHERE key = ?", [(k,) for k in gone])
        finally:
            conn.close()
        self._saved.update(changed)
        for key in gone:
            del self._saved[key]


def import_state_json(json_path: Path, db: Path, drive: str) -> int:
    """Move an old state.json into the database, putting every file under `drive`. Returns how many files."""
    data = json.loads(Path(json_path).read_text(encoding="utf-8"))
    state = State(db)
    state.files = {f"{drive}/{key}": entry for key, entry in data.get("files", {}).items()}
    migrate_scene_names(state.files)
    state.save()
    return len(state.files)
