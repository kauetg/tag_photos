import base64
import hashlib
import shutil

import pytest

from mediatagger.config import PROJECT_ROOT
from mediatagger.tools import find_tool
from mediatagger.xmp import flat_keywords, read_back, sidecar_path, write_keywords

# Smallest valid JPEG (1x1 pixel) so exiftool can embed tags in it.
TINY_JPEG = base64.b64decode(
    "/9j/4AAQSkZJRgABAQEASABIAAD/2wBDAP//////////////////////////////////////////"
    "////////////////////////////////////////////////wgALCAABAAEBAREA/8QAFBABAAAA"
    "AAAAAAAAAAAAAAAAAP/aAAgBAQABPxA="
)

WRITE_CFG = None  # filled by fixture


@pytest.fixture
def exiftool(cfg):
    found = find_tool("exiftool", cfg)
    if not found:
        pytest.skip("exiftool not available")
    return found


@pytest.fixture
def wcfg(cfg):
    cfg.embedded_exts = [".jpg", ".dng"]
    cfg.overwrite_original = False
    return cfg


def md5(path):
    return hashlib.md5(path.read_bytes()).hexdigest()


def test_flat_keywords_skip_root_and_dedupe():
    flat = flat_keywords(["Location|Philippines|Siquijor", "Location|Philippines"])
    assert flat == ["Philippines", "Siquijor"]
    assert flat_keywords(["Solo"]) == ["Solo"]


def test_sidecar_leaves_original_untouched(tmp_path, wcfg, exiftool):
    raw = tmp_path / "DSC0001.ARW"
    raw.write_bytes(b"not really a raw file" * 50)
    before = md5(raw)

    result = write_keywords(
        raw, ["Marine Life|Reptiles|Green sea turtle"], wcfg, exiftool,
        country="Philippines", city="Siquijor",
    )

    assert result["mode"] == "sidecar"
    assert md5(raw) == before
    assert sidecar_path(raw).name == "DSC0001.xmp"
    tags = read_back(raw, wcfg, exiftool)
    assert tags["XMP-lr:HierarchicalSubject"] == "Marine Life|Reptiles|Green sea turtle"
    assert set(tags["XMP-dc:Subject"]) == {"Reptiles", "Green sea turtle"}
    assert tags["XMP-photoshop:Country"] == "Philippines"


def test_keywords_are_appended_without_duplicates(tmp_path, wcfg, exiftool):
    clip = tmp_path / "clip.mp4"
    clip.write_bytes(b"video" * 100)
    write_keywords(clip, ["Location|Malaysia|Rawa"], wcfg, exiftool)
    write_keywords(clip, ["Location|Malaysia|Rawa", "Fauna|Fish|Clownfish"], wcfg, exiftool)

    tags = read_back(clip, wcfg, exiftool)
    assert sorted(tags["XMP-lr:HierarchicalSubject"]) == [
        "Fauna|Fish|Clownfish", "Location|Malaysia|Rawa",
    ]
    assert sorted(tags["XMP-dc:Subject"]) == ["Clownfish", "Fish", "Malaysia", "Rawa"]


def test_rewriting_same_keywords_is_a_noop(tmp_path, wcfg, exiftool):
    jpg = tmp_path / "photo.jpg"
    jpg.write_bytes(TINY_JPEG)
    for _ in range(2):
        write_keywords(jpg, ["Location|Singapore"], wcfg, exiftool)
    tags = read_back(jpg, wcfg, exiftool)
    assert tags["XMP-lr:HierarchicalSubject"] == "Location|Singapore"
    assert tags["XMP-dc:Subject"] == "Singapore"
    assert tags["IPTC:Keywords"] == "Singapore"


def test_existing_location_is_not_overwritten(tmp_path, wcfg, exiftool):
    raw = tmp_path / "a.ARW"
    raw.write_bytes(b"x" * 100)
    write_keywords(raw, ["Location|A"], wcfg, exiftool, country="Philippines")
    write_keywords(raw, ["Location|B"], wcfg, exiftool, country="Malaysia", city="Tioman")

    tags = read_back(raw, wcfg, exiftool)
    assert tags["XMP-photoshop:Country"] == "Philippines"  # kept
    assert tags["XMP-photoshop:City"] == "Tioman"  # was empty, so filled


def test_jpeg_is_embedded_and_keeps_backup(tmp_path, wcfg, exiftool):
    jpg = tmp_path / "photo.jpg"
    jpg.write_bytes(TINY_JPEG)
    result = write_keywords(jpg, ["Location|Singapore"], wcfg, exiftool)

    assert result["mode"] == "embedded"
    assert not sidecar_path(jpg).exists()
    assert (tmp_path / "photo.jpg_original").exists()
    tags = read_back(jpg, wcfg, exiftool)
    assert tags["XMP-lr:HierarchicalSubject"] == "Location|Singapore"
    assert tags["IPTC:Keywords"] == "Singapore"


def test_accented_keywords_and_paths(tmp_path, wcfg, exiftool):
    folder = tmp_path / "Área de Trabalho"
    folder.mkdir()
    raw = folder / "a.ARW"
    raw.write_bytes(b"x" * 100)
    write_keywords(raw, ["Location|Brasil|São Paulo"], wcfg, exiftool)
    assert read_back(raw, wcfg, exiftool)["XMP-lr:HierarchicalSubject"] == "Location|Brasil|São Paulo"


def test_dry_run_writes_nothing(tmp_path, wcfg, exiftool):
    raw = tmp_path / "a.ARW"
    raw.write_bytes(b"x" * 100)
    result = write_keywords(raw, ["Location|A"], wcfg, exiftool, dry_run=True)
    assert result["dry_run"] is True
    assert not sidecar_path(raw).exists()
    assert not (wcfg.data_dir / "write_log.jsonl").exists()


def test_write_is_logged(tmp_path, wcfg, exiftool):
    raw = tmp_path / "a.ARW"
    raw.write_bytes(b"x" * 100)
    write_keywords(raw, ["Location|A"], wcfg, exiftool)
    log = (wcfg.data_dir / "write_log.jsonl").read_text(encoding="utf-8").splitlines()
    assert len(log) == 1 and '"mode": "sidecar"' in log[0]
