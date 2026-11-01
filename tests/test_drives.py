from pathlib import Path

from mediatagger import drives as d
from mediatagger.config import DriveNotMounted, load_config
from mediatagger.library import search
from mediatagger.scan import resolve_roots, scan
from mediatagger.state import State

import pytest

SHEET = (
    "HD\tDescrição\tLetra\tTamanho\tOcupado\tLivre\tStatus\tUltima mod.\tLocalização\tO que tem\tObs\n"
    "Splash IV\tBranco Estrela\tE:\t2000 GB\t1,540.00\t282.00\tEm uso\t23/12/2023\tPhilippines\tTailandia 22\tHD atual\n"
    "Splash III\tPreto Seagate 1\tH:\t1000 GB\t0.00\t931.00\tFuturo\t23/12/2023\tPhilippines\t-\t\n"
)


def volume(letter, serial):
    return d.Mounted(Path(f"{letter}:\\"), serial, "", 1000.0, 300.0)


def test_table_import_normalises_numbers_dates_and_dash(tmp_path):
    sheet = tmp_path / "hds.tsv"
    sheet.write_text(SHEET, encoding="utf-8")
    db = tmp_path / "index.db"
    assert d.import_table(db, sheet) == (2, 0)
    iv, iii = d.get_drive(db, "Splash IV"), d.get_drive(db, "Splash III")
    assert (iv.label, iv.size_gb, iv.used_gb, iv.free_gb, iv.last_mod) == ("Branco Estrela", 2000.0, 1540.0, 282.0, "2023-12-23")
    assert iv.title == "Splash IV · Branco Estrela" and iii.contents == ""  # "-" means nothing


def test_reimport_keeps_serial_and_scan_date(tmp_path):
    sheet = tmp_path / "hds.tsv"
    sheet.write_text(SHEET, encoding="utf-8")
    db = tmp_path / "index.db"
    d.import_table(db, sheet)
    drive = d.get_drive(db, "Splash IV")
    drive.serial, drive.last_scan = "ABCD1234", "2026-11-01"
    d.save_drive(db, drive)
    assert d.import_table(db, sheet) == (0, 2)
    kept = d.get_drive(db, "Splash IV")
    assert (kept.serial, kept.last_scan) == ("ABCD1234", "2026-11-01")


def test_a_drive_is_found_by_serial_not_by_letter(tmp_path):
    db = tmp_path / "index.db"
    d.save_drive(db, d.Drive("Splash IV", serial="AAAA0001"))
    d.save_drive(db, d.Drive("Splash V"))  # never paired
    now = [volume("G", "AAAA0001"), volume("E", "BBBB0002")]
    assert {n: m.root.drive for n, m in d.mounts_by_drive(db, now).items()} == {"Splash IV": "G:"}
    assert [v.serial for v in d.unregistered_volumes(db, now)] == ["BBBB0002"]


def test_path_of_follows_the_plugged_in_drive(cfg):
    cfg.mounts = {"Splash IV": Path("G:/")}
    assert cfg.path_of("Splash IV/20250101 Foo/a.ARW") == Path("G:/20250101 Foo/a.ARW")
    assert cfg.path_of("Test/x/y.jpg") == cfg.media_root / "x/y.jpg"  # the drive being scanned
    assert cfg.is_mounted("Splash IV/a") and not cfg.is_mounted("Splash V/a")
    with pytest.raises(DriveNotMounted):
        cfg.path_of("Splash V/a.ARW")


def test_two_drives_can_hold_the_same_relative_path(cfg, media, tmp_path):
    state = State.load(cfg.state_path)
    scan(cfg, state, resolve_roots(cfg, None))
    other = tmp_path / "other"
    (other / "20250122 Pereque").mkdir(parents=True)
    (other / "20250122 Pereque" / "a.ARW").write_bytes(b"another disk" * 100)
    cfg2 = load_config(cfg.config_dir, media_root=str(other), drive="Other")
    scan(cfg2, state, resolve_roots(cfg2, None))
    assert {"Test/20250122 Pereque/a.ARW", "Other/20250122 Pereque/a.ARW"} <= set(state.files)
    # scanning one drive never marks the other one missing
    assert not state.files["Test/20250122 Pereque/a.ARW"].get("missing")


def test_scan_needs_to_know_the_drive(cfg, media):
    cfg.drive = ""
    with pytest.raises(SystemExit):
        scan(cfg, State.load(cfg.state_path), resolve_roots(cfg, None))


def test_search_can_be_limited_to_one_drive(tmp_path):
    state = State(tmp_path / "index.db")
    tags = {"scene": {"underwater": 1.0}, "suggestions": [], "model": "m"}
    state.files = {
        "A/20260101 x/1.arw": {"kind": "raw", "tags": tags, "location": None},
        "B/20260101 x/1.arw": {"kind": "raw", "tags": tags, "location": None},
    }
    assert search(state, drive="B") == ["B/20260101 x/1.arw"]
    assert len(search(state)) == 2


def test_file_counts_per_drive_ignore_missing(tmp_path):
    db = tmp_path / "index.db"
    state = State(db)
    state.files = {"A/1": {"kind": "raw"}, "A/2": {"kind": "raw", "missing": True}, "B/1": {"kind": "raw"}}
    state.save()
    assert d.file_counts(db) == {"A": 1, "B": 1}


def test_search_can_show_only_the_connected_drives(tmp_path):
    state = State(tmp_path / "index.db")
    tags = {"scene": {"underwater": 1.0}, "suggestions": [], "model": "m"}
    state.files = {f"{drive}/20260101 x/1.arw": {"kind": "raw", "tags": tags, "location": None} for drive in "ABC"}
    assert search(state, drives={"A", "C"}) == ["A/20260101 x/1.arw", "C/20260101 x/1.arw"]
    assert search(state, drives=set()) == []
