from mediatagger.review import decide
from mediatagger.state import State
from mediatagger.write import keywords_for, select_files

TURTLE = "Marine Life|Reptiles|Sea turtle"
SIQUI = "Location|Philippines|Siquijor"


def make_state(tmp_path):
    state = State(tmp_path / "state.json")
    loc = {"keyword": SIQUI, "country": "Philippines", "city": "Siquijor"}
    state.files = {
        "a/turtle.arw": {"kind": "raw", "location": loc},
        "a/pending.arw": {"kind": "raw", "location": loc},
        "a/skipped.arw": {"kind": "raw", "location": loc},
        "a/clip.mp4": {"kind": "video", "location": loc},
        "a/gone.arw": {"kind": "raw", "location": loc, "missing": True},
    }
    decide(state.files["a/turtle.arw"], [TURTLE], approved=True)
    decide(state.files["a/skipped.arw"], [TURTLE], approved=False)
    decide(state.files["a/clip.mp4"], [TURTLE], approved=True)  # even if approved, never written
    decide(state.files["a/gone.arw"], [TURTLE], approved=True)
    return state


def test_keywords_include_location_once():
    entry = {"location": {"keyword": SIQUI}, "review": {"keywords": [TURTLE, SIQUI]}}
    assert keywords_for(entry) == [TURTLE, SIQUI]
    assert keywords_for({"location": {"keyword": SIQUI}, "review": {"keywords": [TURTLE]}}) == [TURTLE, SIQUI]


def test_only_approved_photos_are_selected(tmp_path):
    assert select_files(make_state(tmp_path), None, redo=False, limit=None) == ["a/turtle.arw"]


def test_already_written_is_skipped_unless_redo(tmp_path):
    state = make_state(tmp_path)
    state.files["a/turtle.arw"]["written"] = keywords_for(state.files["a/turtle.arw"])
    assert select_files(state, None, redo=False, limit=None) == []
    assert select_files(state, None, redo=True, limit=None) == ["a/turtle.arw"]


def test_prefix_and_limit(tmp_path):
    state = make_state(tmp_path)
    assert select_files(state, "b", redo=False, limit=None) == []
    assert select_files(state, "a", redo=False, limit=0) == ["a/turtle.arw"]
