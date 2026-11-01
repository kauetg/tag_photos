"""Thumbnail cache for the review page, so RAW previews are extracted only once."""
from __future__ import annotations

import hashlib
from pathlib import Path

from .config import Config
from .imaging import load_image

THUMB_SIDE = 800


def thumb_path(cfg: Config, name: str) -> Path:
    """Where the cached JPEG for `name` lives (name is any stable string)."""
    return cfg.data_dir / "thumbs" / f"{hashlib.sha1(name.encode('utf-8')).hexdigest()}.jpg"


def thumbnail(path: Path, cfg: Config, exiftool: str) -> Path:
    """Cached JPEG under data/thumbs, named by the source path, size and mtime."""
    path = Path(path)
    stat = path.stat()
    digest = hashlib.sha1(f"{path}|{stat.st_size}|{stat.st_mtime_ns}".encode("utf-8")).hexdigest()
    target = cfg.data_dir / "thumbs" / f"{digest}.jpg"
    if not target.exists():
        target.parent.mkdir(parents=True, exist_ok=True)
        load_image(path, cfg, exiftool, max_side=THUMB_SIDE).save(target, quality=85)
    return target
