"""Load a PIL image from a supported media file using the cheapest route.

JPEG is opened directly. RAW files never get decoded when they carry an embedded
JPEG preview (ARW, DNG); GPR has none, so it falls back to rawpy.
"""
from __future__ import annotations

import io
import subprocess
import tempfile
from pathlib import Path

from PIL import Image, ImageOps

from .config import Config
from .tools import find_tool
from .xmp import ExiftoolError, run_exiftool

MAX_SIDE = 1024
CONVERTER_TIMEOUT = 120  # seconds per file; a GPR takes about 3 s
# A preview at least this wide is plenty for the models (they resize to 224-448 px).
MIN_PREVIEW_SIDE = 800
PREVIEW_TAGS = ["PreviewImage", "JpgFromRaw"]


class ImageLoadError(RuntimeError):
    pass


def _shrink(image: Image.Image, max_side: int) -> Image.Image:
    image = ImageOps.exif_transpose(image).convert("RGB")
    image.thumbnail((max_side, max_side))
    return image


# EXIF Orientation value -> PIL transpose that makes the picture upright.
_ORIENTATION_FIXES = {
    2: Image.Transpose.FLIP_LEFT_RIGHT,
    3: Image.Transpose.ROTATE_180,
    4: Image.Transpose.FLIP_TOP_BOTTOM,
    5: Image.Transpose.TRANSPOSE,
    6: Image.Transpose.ROTATE_270,
    7: Image.Transpose.TRANSVERSE,
    8: Image.Transpose.ROTATE_90,
}


def _upright(image: Image.Image, path: Path, exiftool: str) -> Image.Image:
    """Sony ARW previews carry no orientation; it only lives in the RAW's own EXIF."""
    if image.getexif().get(0x0112, 1) != 1:
        return image  # the preview is self-describing; _shrink applies it
    try:
        value = int(run_exiftool(exiftool, ["-n", "-s3", "-Orientation", str(path)]).strip() or 1)
    except (ExiftoolError, ValueError):
        return image
    fix = _ORIENTATION_FIXES.get(value)
    return image.transpose(fix) if fix is not None else image


def _embedded_preview(path: Path, exiftool: str, max_side: int) -> Image.Image | None:
    """First embedded preview that is big enough, else the largest one found."""
    best = None
    for tag in PREVIEW_TAGS:
        try:
            data = run_exiftool(exiftool, ["-b", f"-{tag}", str(path)], binary=True)
        except ExiftoolError:
            continue
        if not data:
            continue
        try:
            image = Image.open(io.BytesIO(data))
            image.draft("RGB", (max_side, max_side))
            image.load()
        except OSError:
            continue
        if max(image.size) >= MIN_PREVIEW_SIDE:
            return _shrink(_upright(image, path, exiftool), max_side)
        if best is None or max(image.size) > max(best.size):
            best = image
    return _shrink(_upright(best, path, exiftool), max_side) if best is not None else None


def _via_dng_converter(path: Path, cfg: Config, exiftool: str, max_side: int) -> Image.Image | None:
    """GPR has no preview and LibRaw cannot read it: let Adobe DNG Converter make a temp DNG."""
    converter = find_tool("dng_converter", cfg)
    if not converter or path.suffix.lower() != ".gpr":
        return None
    with tempfile.TemporaryDirectory(prefix="gpr_") as tmp:
        # The converter only reads the source; it writes the DNG into tmp.
        proc = subprocess.run(
            [converter, "-c", "-p1", "-d", tmp, str(path)],
            capture_output=True, timeout=CONVERTER_TIMEOUT,
        )
        dng = Path(tmp) / (path.stem + ".dng")
        if proc.returncode != 0 or not dng.exists():
            raise ImageLoadError(f"Adobe DNG Converter failed on {path.name} (exit {proc.returncode})")
        return _embedded_preview(dng, exiftool, max_side)


def _decode_raw(path: Path, max_side: int) -> Image.Image:
    """Slow path for RAW files without a preview (GPR). Half-size decode for speed."""
    try:
        import rawpy
    except ImportError as exc:
        raise ImageLoadError("rawpy is not installed") from exc
    try:
        with open(path, "rb") as f, rawpy.imread(f) as raw:
            rgb = raw.postprocess(half_size=True, use_camera_wb=True, output_bps=8)
    except Exception as exc:  # rawpy raises several unrelated error types
        raise ImageLoadError(
            f"no embedded preview and LibRaw cannot decode it (GoPro GPR uses VC-5): {exc}"
        ) from exc
    return _shrink(Image.fromarray(rgb), max_side)


def load_image(path: Path, cfg: Config, exiftool: str, max_side: int = MAX_SIDE) -> Image.Image:
    path = Path(path)
    kind = cfg.kind_of(path.name)
    try:
        if kind == "photo":
            image = Image.open(path)
            image.draft("RGB", (max_side, max_side))
            return _shrink(image, max_side)
        if kind == "raw":
            return (
                _embedded_preview(path, exiftool, max_side)
                or _via_dng_converter(path, cfg, exiftool, max_side)
                or _decode_raw(path, max_side)
            )
    except OSError as exc:
        raise ImageLoadError(f"cannot read {path.name}: {exc}") from exc
    raise ImageLoadError(f"{path.name}: not an image kind ({kind})")
