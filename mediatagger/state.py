"""state.json: one entry per media file, keyed by path relative to media_root."""
from __future__ import annotations

import json
import os
from pathlib import Path

from .vocabulary import LEGACY_SCENES

STATE_VERSION = 1


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


class State:
    def __init__(self, path: Path):
        self.path = Path(path)
        self.files: dict[str, dict] = {}

    @classmethod
    def load(cls, path: Path) -> "State":
        state = cls(path)
        if state.path.exists():
            data = json.loads(state.path.read_text(encoding="utf-8"))
            state.files = data.get("files", {})
            migrate_scene_names(state.files)
        return state

    def save(self) -> None:
        """Atomic write: temp file in the same folder, fsync, then rename over the old one."""
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_name(self.path.name + ".tmp")
        payload = {"version": STATE_VERSION, "files": self.files}
        with tmp.open("w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, self.path)
