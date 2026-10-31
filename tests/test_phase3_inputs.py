import pytest

from mediatagger.config import PROJECT_ROOT
from mediatagger.imaging import ImageLoadError, load_image
from mediatagger.vocabulary import load_vocabulary

VOCAB = PROJECT_ROOT / "config" / "vocabulary.csv"


def test_real_vocabulary_is_well_formed():
    rows = load_vocabulary(VOCAB)
    assert len(rows) > 100
    assert {r.tier for r in rows} <= {"core", "species"}
    assert all(r.scenes <= {"underwater", "topside", "land"} and r.scenes for r in rows)
    assert all(r.keyword and r.prompt for r in rows)
    assert len({r.keyword for r in rows}) == len(rows)  # no duplicate keywords


def test_every_species_has_a_core_parent():
    rows = load_vocabulary(VOCAB)
    core = {r.keyword for r in rows if r.tier == "core"}
    orphans = [r.keyword for r in rows if r.tier == "species" and r.keyword.rsplit("|", 1)[0] not in core]
    assert not orphans


def test_tiers_filter():
    core = load_vocabulary(VOCAB, {"core"})
    assert core and all(r.tier == "core" for r in core)


def test_jpeg_loads_as_rgb_and_is_shrunk(tmp_path, cfg):
    from PIL import Image

    jpg = tmp_path / "a.jpg"
    Image.new("RGB", (3000, 2000), (10, 120, 200)).save(jpg)
    cfg.kinds = {".jpg": "photo", ".arw": "raw"}
    image = load_image(jpg, cfg, exiftool="unused", max_side=512)
    assert image.mode == "RGB"
    assert max(image.size) == 512


def test_unreadable_raw_gives_clear_error(tmp_path, cfg):
    raw = tmp_path / "broken.arw"
    raw.write_bytes(b"not a raw file" * 10)
    cfg.kinds = {".jpg": "photo", ".arw": "raw"}
    from mediatagger.tools import find_tool

    exiftool = find_tool("exiftool", cfg)
    if not exiftool:
        pytest.skip("exiftool not available")
    with pytest.raises(ImageLoadError):
        load_image(raw, cfg, exiftool)
