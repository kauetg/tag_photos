import csv

from mediatagger.review import APPROVED, PENDING, SKIPPED, decide, export_csv, status, suggested, tagged_keys
from mediatagger.state import State


def make_state(tmp_path):
    state = State(tmp_path / "state.json")
    state.files = {
        "a/one.arw": {
            "kind": "raw",
            "location": {"country": "Philippines", "city": "Siquijor"},
            "tags": {
                "scene": {"underwater": 0.9, "topside": 0.1},
                "suggestions": [
                    {"keyword": "Marine Life|Reptiles|Sea turtle", "prob": 0.98, "tier": "core"},
                    {"keyword": "Marine Life|Reptiles|Sea turtle|Green sea turtle", "prob": 0.4, "tier": "species"},
                ],
            },
        },
        "a/two.arw": {"kind": "raw"},  # never tagged
        "b/gone.arw": {"kind": "raw", "missing": True, "tags": {"scene": {}, "suggestions": []}},
    }
    return state


def test_only_tagged_present_files_are_reviewable(tmp_path):
    assert tagged_keys(make_state(tmp_path)) == ["a/one.arw"]
    assert tagged_keys(make_state(tmp_path), prefix="b") == []


def test_suggested_respects_threshold(tmp_path):
    entry = make_state(tmp_path).files["a/one.arw"]
    assert suggested(entry) == ["Marine Life|Reptiles|Sea turtle"]
    assert len(suggested(entry, threshold=0.3)) == 2


def test_decide_and_status(tmp_path):
    entry = make_state(tmp_path).files["a/one.arw"]
    assert status(entry) == PENDING
    decide(entry, ["Marine Life|Reptiles|Sea turtle"], approved=True)
    assert status(entry) == APPROVED and entry["review"]["keywords"]
    decide(entry, ["ignored"], approved=False)
    assert status(entry) == SKIPPED and entry["review"]["keywords"] == []


def test_export_csv(tmp_path):
    state = make_state(tmp_path)
    decide(state.files["a/one.arw"], ["Marine Life|Reptiles|Sea turtle"], approved=True)
    out = tmp_path / "out" / "review.csv"
    assert export_csv(state, out) == 1
    with out.open(encoding="utf-8-sig", newline="") as f:
        rows = list(csv.DictReader(f))
    assert rows[0]["file"] == "a/one.arw"
    assert rows[0]["city"] == "Siquijor" and rows[0]["scene"] == "underwater"
    assert rows[0]["suggested"] == "Sea turtle"
    assert rows[0]["status"] == APPROVED
    assert rows[0]["approved"] == "Marine Life|Reptiles|Sea turtle"
