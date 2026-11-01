"""Locate external tools: config path, then tools/ in the project, then PATH."""
from __future__ import annotations

import shutil
from pathlib import Path

from .config import PROJECT_ROOT, Config

_BUNDLED = {
    "exiftool": ["tools/exiftool/exiftool.exe"],
    "ffmpeg": ["tools/ffmpeg/bin/ffmpeg.exe"],
    "ffprobe": ["tools/ffmpeg/bin/ffprobe.exe"],
    # Adobe's installer puts it here; absolute, so PROJECT_ROOT / path keeps it as is.
    "dng_converter": [r"C:\Program Files\Adobe\Adobe DNG Converter\Adobe DNG Converter.exe"],
    "vlc": [r"C:\Program Files\VideoLAN\VLC\vlc.exe", r"C:\Program Files (x86)\VideoLAN\VLC\vlc.exe"],
}


def find_tool(name: str, cfg: Config) -> str | None:
    configured = getattr(cfg, name, "")
    if configured and Path(configured).exists():
        return str(configured)
    for rel in _BUNDLED.get(name, []):
        candidate = PROJECT_ROOT / rel
        if candidate.exists():
            return str(candidate)
    return shutil.which(name)
