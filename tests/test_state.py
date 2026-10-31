import json
import os

import pytest

from mediatagger import state as state_module
from mediatagger.state import State


def test_roundtrip(tmp_path):
    path = tmp_path / "data" / "state.json"
    s = State(path)
    s.files["a/b.jpg"] = {"size": 1}
    s.save()
    assert State.load(path).files == {"a/b.jpg": {"size": 1}}


def test_failed_save_keeps_previous_state(tmp_path, monkeypatch):
    path = tmp_path / "state.json"
    s = State(path)
    s.files["old"] = {"size": 1}
    s.save()

    s.files["new"] = {"size": 2}

    def boom(*args, **kwargs):
        raise OSError("simulated crash before rename")

    monkeypatch.setattr(state_module.os, "replace", boom)
    with pytest.raises(OSError):
        s.save()

    # The real file is untouched and still valid JSON.
    assert list(json.loads(path.read_text(encoding="utf-8"))["files"]) == ["old"]


def test_save_replaces_via_temp_file(tmp_path):
    path = tmp_path / "state.json"
    State(path).save()
    assert not os.path.exists(str(path) + ".tmp")
