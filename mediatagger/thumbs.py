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


def thumb_target(cfg: Config, key: str, entry: dict) -> Path:
    """Where the preview of a photo lives. Named by the key, size and mtime the index already knows, so it can be
    found without the drive plugged in (and does not change when the drive gets another letter)."""
    digest = hashlib.sha1(f"{key}|{entry['size']}|{entry['mtime']}".encode("utf-8")).hexdigest()
    return cfg.data_dir / "thumbs" / f"{digest}.jpg"


def cached_thumbnail(cfg: Config, key: str, entry: dict) -> Path | None:
    """The preview if it was made already, else None. Never touches the drive."""
    target = thumb_target(cfg, key, entry)
    return target if target.exists() else None


def thumbnail(cfg: Config, key: str, entry: dict, exiftool: str) -> Path:
    """The cached preview, made now (needs the drive) when it does not exist yet."""
    target = thumb_target(cfg, key, entry)
    if not target.exists():
        target.parent.mkdir(parents=True, exist_ok=True)
        load_image(cfg.path_of(key), cfg, exiftool, max_side=THUMB_SIDE).save(target, quality=85)
    return target


def make_missing(cfg: Config, state, exiftool: str, prefix: str | None = None, limit: int | None = None) -> tuple[int, int]:
    """Make the previews that do not exist yet for plugged-in photos. Returns (made, failed)."""
    made = failed = 0
    for key, entry in sorted(state.files.items()):
        if entry["kind"] not in ("photo", "raw") or entry.get("missing") or not cfg.is_mounted(key):
            continue
        if prefix and not key.startswith(prefix.rstrip("/") + "/"):
            continue
        if cached_thumbnail(cfg, key, entry):
            continue
        if limit is not None and made + failed >= limit:
            break
        try:
            thumbnail(cfg, key, entry, exiftool)
            made += 1
        except Exception as exc:  # one unreadable file must not stop a long run
            failed += 1
            print(f"  warning: no preview for {key}: {exc}")
    return made, failed
