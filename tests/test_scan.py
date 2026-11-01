import os

from mediatagger.scan import resolve_roots, scan, write_unmapped_report
from mediatagger.state import State


def run(cfg, **kwargs):
    state = State.load(cfg.state_path)
    return state, scan(cfg, state, resolve_roots(cfg, kwargs.pop("folder", None)), **kwargs)


def test_first_scan_finds_media_and_skips_catalogs(cfg):
    state, report = run(cfg)
    keys = sorted(state.files)
    assert report.new == 6
    assert "Test/20250122 Pereque/a.ARW" in keys
    assert not any("lrdata" in k or "Old Lightroom" in k for k in keys)
    assert not any(k.endswith(".txt") for k in keys)


def test_keys_are_relative_posix_paths(cfg):
    state, _ = run(cfg)
    assert all("\\" not in k and ":" not in k for k in state.files)


def test_kinds_dates_and_locations(cfg):
    state, _ = run(cfg)
    raw = state.files["Test/20250122 Pereque/a.ARW"]
    assert raw["kind"] == "raw"
    assert raw["folder_date"] == "20250122"
    assert raw["location"]["keyword"] == "Location|Brazil|Guaruja|Pereque"
    assert state.files["Test/20250122 Pereque/clip.mp4"]["kind"] == "video"
    # Accent-insensitive: folder says "Sao Paulo", match row says "Sao Paulo".
    assert state.files["Test/20241227 Sao Paulo Mercado/d.jpg"]["location"]["city"] == "Sao Paulo"


def test_second_scan_is_incremental(cfg):
    run(cfg)
    _, report = run(cfg)
    assert (report.new, report.changed, report.unchanged) == (0, 0, 6)


def test_changed_file_is_rescanned(cfg, media):
    state, _ = run(cfg)
    old_hash = state.files["Test/20250122 Pereque/b.jpg"]["hash"]
    (media / "20250122 Pereque" / "b.jpg").write_bytes(b"different content")
    state, report = run(cfg)
    assert report.changed == 1
    assert state.files["Test/20250122 Pereque/b.jpg"]["hash"] != old_hash


def test_deleted_file_is_marked_missing(cfg, media):
    run(cfg)
    os.remove(media / "20250122 Pereque" / "b.jpg")
    state, report = run(cfg)
    assert report.missing == 1
    assert state.files["Test/20250122 Pereque/b.jpg"]["missing"] is True


def test_limit_then_resume(cfg):
    state, first = run(cfg, limit=2)
    assert first.new == 2 and first.missing == 0
    _, second = run(cfg)
    assert second.new == 4 and second.unchanged == 2


def test_dry_run_changes_nothing(cfg):
    _, report = run(cfg, dry_run=True)
    assert report.new == 6
    assert not cfg.state_path.exists()


def test_folder_restriction(cfg):
    state, report = run(cfg, folder="20250122 Pereque")
    assert report.new == 3
    assert all(k.startswith("Test/20250122 Pereque/") for k in state.files)


def test_missing_detection_stays_inside_scanned_folder(cfg, media):
    run(cfg)
    os.remove(media / "20241227 Chegada Ilhabela" / "c.DNG")
    _, report = run(cfg, folder="20250122 Pereque")
    assert report.missing == 0


def test_date_range_is_fallback_and_name_wins(cfg):
    state, report = run(cfg)
    # "Casinha" has no name match, but its date (20250101) falls in a range.
    casinha = state.files["Test/20250101 Casinha/e.mov"]["location"]
    assert casinha["source"] == "date" and casinha["sublocation"] == "Newyear"
    # Pereque folder is dated 20250122 (inside the wide range) but the name wins.
    pereque = state.files["Test/20250122 Pereque/a.ARW"]["location"]
    assert pereque["source"] == "name"
    assert report.unmapped == {}


def test_unmapped_folders_report(cfg):
    cfg.date_ranges.clear()
    _, report = run(cfg)
    # "Casinha" has no locations.csv row and no date range.
    assert report.unmapped["20250101 Casinha"] == 1
    path = write_unmapped_report(cfg, report)
    assert "20250101 Casinha" in path.read_text(encoding="utf-8")
