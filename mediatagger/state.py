"""state.json: one entry per media file, keyed by path relative to media_root."""
from __future__ import annotations

import json
import os
from pathlib import Path

STATE_VERSION = 1


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
