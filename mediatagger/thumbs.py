"""Thumbnail cache for the review page, so RAW previews are extracted only once."""
from __future__ import annotations

import hashlib
from pathlib import Path

from .config import Config
from .imaging import load_image

THUMB_SIDE = 800


def cover(thumb: Path, ratio: float = 16 / 9, side: int = 480) -> Path:
    """A centre-cropped copy of a cached thumbnail with a fixed shape, so grid cards line up."""
    from PIL import Image

    thumb = Path(thumb)
    target = thumb.with_name(thumb.stem + "_cover.jpg")
    if not target.exists():
        with Image.open(thumb) as image:
            width, height = image.size
            if width / height > ratio:
                crop_w = round(height * ratio)
                box = ((width - crop_w) // 2, 0, (width + crop_w) // 2, height)
            else:
                crop_h = round(width / ratio)
                box = (0, (height - crop_h) // 2, width, (height + crop_h) // 2)
            cropped = image.convert("RGB").crop(box)
        cropped.thumbnail((side, side))
        cropped.save(target, quality=85)
    return target


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
