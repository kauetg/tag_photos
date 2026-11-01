import json

import pytest

from mediatagger import state as state_module
from mediatagger.state import State, import_state_json, split_key


def test_roundtrip(tmp_path):
    path = tmp_path / "data" / "index.db"
    s = State(path)
    s.files["Splash IV/a/b.jpg"] = {"size": 1, "kind": "photo"}
    s.save()
    assert State.load(path).files == {"Splash IV/a/b.jpg": {"size": 1, "kind": "photo"}}


def test_split_key():
    assert split_key("Splash IV/20250101 Foo/a.ARW") == ("Splash IV", "20250101 Foo/a.ARW")


def test_save_writes_only_what_changed(tmp_path, monkeypatch):
    path = tmp_path / "index.db"
    s = State(path)
    s.files = {"D/a.jpg": {"size": 1}, "D/b.jpg": {"size": 2}}
    s.save()
    s.files["D/b.jpg"]["size"] = 3
    written = []
    real = state_module._dump
    monkeypatch.setattr(state_module, "_dump", lambda entry: written.append(entry) or real(entry))
    s.save(keys=["D/b.jpg"])  # a review click checks one entry only
    assert written == [{"size": 3}]
    assert State.load(path).files["D/b.jpg"] == {"size": 3}


def test_removed_entries_are_deleted(tmp_path):
    path = tmp_path / "index.db"
    s = State(path)
    s.files = {"D/a.jpg": {}, "D/b.jpg": {}}
    s.save()
    del s.files["D/a.jpg"]
    s.save()
    assert list(State.load(path).files) == ["D/b.jpg"]


def test_a_bad_entry_fails_before_anything_is_written(tmp_path):
    path = tmp_path / "index.db"
    s = State(path)
    s.files["D/old"] = {"size": 1}
    s.save()
    s.files["D/new"] = {"size": object()}  # cannot be stored
    s.files["D/old"]["size"] = 2
    with pytest.raises(TypeError):
        s.save()
    assert State.load(path).files == {"D/old": {"size": 1}}


def test_import_old_state_json_puts_files_under_a_drive(tmp_path):
    old = tmp_path / "state.json"
    old.write_text(json.dumps({"version": 1, "files": {"20250101 Foo/a.ARW": {"kind": "raw"}}}), encoding="utf-8")
    assert import_state_json(old, tmp_path / "index.db", "Splash IV") == 1
    assert list(State.load(tmp_path / "index.db").files) == ["Splash IV/20250101 Foo/a.ARW"]
