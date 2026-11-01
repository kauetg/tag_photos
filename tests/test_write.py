import hashlib

import pytest

from mediatagger.review import decide
from mediatagger.state import State
from mediatagger.tools import find_tool
from mediatagger.write import apply_for, candidates, describe, desired_for, is_dirty, keywords_for, plan_for
from mediatagger.xmp import _as_list, read_back, run_exiftool, sidecar_path, write_keywords

TURTLE = "Marine Life|Reptiles|Sea turtle"
GREEN = TURTLE + "|Green sea turtle"
SIQUI = {"keyword": "Location|Philippines|Siquijor", "country": "Philippines", "city": "Siquijor"}


@pytest.fixture
def exiftool(cfg):
    found = find_tool("exiftool", cfg)
    if not found:
        pytest.skip("exiftool not available")
    return found


def entry_with(keywords, location=SIQUI, approved=True, **extra):
    entry = {"kind": "raw", "location": dict(location), **extra}
    decide(entry, keywords, approved=approved)
    return entry


def make_state(tmp_path):
    state = State(tmp_path / "state.json")
    state.files = {
        "a/new.arw": entry_with([TURTLE]),  # approved, never written
        "a/clean.arw": entry_with([TURTLE], written=[TURTLE, SIQUI["keyword"]], written_location={"country": "Philippines", "city": "Siquijor"}),
        "a/changed.arw": entry_with([TURTLE], written=[TURTLE, GREEN, SIQUI["keyword"]]),  # unticked the species since
        "a/skipped_after.arw": entry_with([TURTLE], approved=False, written=[TURTLE]),  # skipped after being written
        "a/skipped_never.arw": entry_with([TURTLE], approved=False),
        "a/pending.arw": {"kind": "raw", "location": SIQUI},
        "a/clip.mp4": {**entry_with([TURTLE]), "kind": "video"},
        "a/gone.arw": entry_with([TURTLE], missing=True),
    }
    return state


def md5(path):
    return hashlib.md5(path.read_bytes()).hexdigest()


def test_keywords_include_location_once():
    entry = {"location": SIQUI, "review": {"keywords": [TURTLE, SIQUI["keyword"]]}}
    assert keywords_for(entry) == [TURTLE, SIQUI["keyword"]]
    assert keywords_for({"location": SIQUI, "review": {"keywords": [TURTLE]}}) == [TURTLE, SIQUI["keyword"]]


def test_review_location_is_what_gets_written():
    entry = {
        "location": SIQUI,
        "review": {"status": "approved", "keywords": [TURTLE], "location": {"keyword": "Location|Philippines|Bohol", "city": "Bohol"}},
    }
    assert keywords_for(entry) == [TURTLE, "Location|Philippines|Bohol"]
    assert desired_for(entry)[1] == {"city": "Bohol"}


def test_a_photo_that_is_not_approved_should_carry_nothing_of_ours():
    assert desired_for(entry_with([TURTLE], approved=False)) == ([], {})
    assert desired_for({"kind": "raw", "location": SIQUI}) == ([], {})


def test_only_photos_that_are_out_of_date_are_candidates(tmp_path):
    state = make_state(tmp_path)
    assert candidates(state) == ["a/changed.arw", "a/new.arw", "a/skipped_after.arw"]
    assert candidates(state, include_clean=True) == [
        "a/changed.arw", "a/clean.arw", "a/new.arw", "a/skipped_after.arw",
    ]
    assert candidates(state, prefix="b") == []
    assert candidates(state, limit=1) == ["a/changed.arw"]


def test_candidates_can_be_limited_to_a_scene(tmp_path):
    state = make_state(tmp_path)
    state.files["a/new.arw"]["tags"] = {"scene": {"underwater": 1.0}}
    state.files["a/changed.arw"]["tags"] = {"scene": {"drone": 1.0}}
    assert candidates(state, scene="underwater") == ["a/new.arw"]
    assert candidates(state, scene="drone") == ["a/changed.arw"]


def test_dirty_detection():
    assert is_dirty(entry_with([TURTLE]))  # never written
    in_sync = entry_with([TURTLE], written=[TURTLE, SIQUI["keyword"]], written_location={"country": "Philippines", "city": "Siquijor"})
    assert not is_dirty(in_sync)
    in_sync["review"]["location"] = {"keyword": "Location|Philippines|Bohol", "country": "Philippines", "city": "Bohol"}
    assert is_dirty(in_sync)  # you moved the photo to another place
    old = entry_with([TURTLE], written=[TURTLE, SIQUI["keyword"]])  # written by an older version: no location record
    assert not is_dirty(old)


def new_cfg(cfg, tmp_path):
    cfg.embedded_exts = []
    cfg.overwrite_original = False
    cfg.media_root = tmp_path
    return cfg


def test_sync_adds_then_removes_only_what_we_wrote(tmp_path, cfg, exiftool):
    cfg = new_cfg(cfg, tmp_path)
    raw = tmp_path / "DSC1.ARW"
    raw.write_bytes(b"not really a raw file" * 50)
    original = md5(raw)
    write_keywords(raw, ["Mine|From Lightroom"], cfg, exiftool)  # a keyword that is not ours

    state = State(tmp_path / "state.json")
    state.files["DSC1.ARW"] = entry_with([TURTLE, GREEN])
    apply_for(cfg, state, exiftool, "DSC1.ARW")
    tags = read_back(raw, cfg, exiftool)
    assert set(_as_list(tags["XMP-lr:HierarchicalSubject"])) == {"Mine|From Lightroom", TURTLE, GREEN, SIQUI["keyword"]}
    assert "Green sea turtle" in _as_list(tags["XMP-dc:Subject"])

    decide(state.files["DSC1.ARW"], [TURTLE], approved=True)  # you un-ticked the species
    assert is_dirty(state.files["DSC1.ARW"])
    result = apply_for(cfg, state, exiftool, "DSC1.ARW")
    assert result["remove"] == [GREEN] and result["verified"]
    tags = read_back(raw, cfg, exiftool)
    assert set(_as_list(tags["XMP-lr:HierarchicalSubject"])) == {"Mine|From Lightroom", TURTLE, SIQUI["keyword"]}
    flat = _as_list(tags["XMP-dc:Subject"])
    assert "Green sea turtle" not in flat  # the removed tag's own word went
    assert {"Sea turtle", "Reptiles", "From Lightroom"} <= set(flat)  # words still used by other tags stayed
    assert not is_dirty(state.files["DSC1.ARW"])
    assert md5(raw) == original  # the RAW itself is never touched


def test_skipping_a_written_photo_takes_our_tags_back_out(tmp_path, cfg, exiftool):
    cfg = new_cfg(cfg, tmp_path)
    (tmp_path / "DSC2.ARW").write_bytes(b"raw" * 100)
    state = State(tmp_path / "state.json")
    state.files["DSC2.ARW"] = entry_with([TURTLE])
    apply_for(cfg, state, exiftool, "DSC2.ARW")
    decide(state.files["DSC2.ARW"], [], approved=False)
    apply_for(cfg, state, exiftool, "DSC2.ARW")
    tags = read_back(tmp_path / "DSC2.ARW", cfg, exiftool)
    assert not _as_list(tags.get("XMP-lr:HierarchicalSubject"))
    assert not _as_list(tags.get("XMP-photoshop:City"))  # and the place we wrote


def test_location_changes_only_while_it_still_holds_what_we_wrote(tmp_path, cfg, exiftool):
    cfg = new_cfg(cfg, tmp_path)
    raw = tmp_path / "DSC3.ARW"
    raw.write_bytes(b"raw" * 100)
    state = State(tmp_path / "state.json")
    state.files["DSC3.ARW"] = entry_with([TURTLE])
    apply_for(cfg, state, exiftool, "DSC3.ARW")
    assert read_back(raw, cfg, exiftool)["XMP-photoshop:City"] == "Siquijor"

    state.files["DSC3.ARW"]["review"]["location"] = {"keyword": "Location|Philippines|Bohol", "country": "Philippines", "city": "Bohol"}
    apply_for(cfg, state, exiftool, "DSC3.ARW")
    assert read_back(raw, cfg, exiftool)["XMP-photoshop:City"] == "Bohol"  # we wrote Siquijor, so we may change it

    run_exiftool(exiftool, ["-XMP-photoshop:City=Set in Lightroom", str(sidecar_path(raw))])
    state.files["DSC3.ARW"]["review"]["location"] = {"keyword": "Location|Philippines|Cebu", "country": "Philippines", "city": "Cebu"}
    apply_for(cfg, state, exiftool, "DSC3.ARW")
    assert read_back(raw, cfg, exiftool)["XMP-photoshop:City"] == "Set in Lightroom"  # not ours any more: left alone


def test_a_plan_changes_nothing_and_a_second_write_is_a_no_op(tmp_path, cfg, exiftool):
    cfg = new_cfg(cfg, tmp_path)
    raw = tmp_path / "DSC4.ARW"
    raw.write_bytes(b"raw" * 100)
    state = State(tmp_path / "state.json")
    state.files["DSC4.ARW"] = entry_with([TURTLE])

    plan = plan_for(cfg, state, exiftool, "DSC4.ARW")
    assert plan["dry_run"] and plan["add"] == [TURTLE, SIQUI["keyword"]] and not plan["nothing_to_do"]
    assert not sidecar_path(raw).exists()  # a plan never creates the sidecar
    assert describe(plan) == "+ Sea turtle, Siquijor; place Philippines, Siquijor"

    apply_for(cfg, state, exiftool, "DSC4.ARW")
    stamp = md5(sidecar_path(raw))
    again = apply_for(cfg, state, exiftool, "DSC4.ARW")
    assert again["nothing_to_do"] and md5(sidecar_path(raw)) == stamp
    assert state.files["DSC4.ARW"]["written"] == [TURTLE, SIQUI["keyword"]]
    assert state.files["DSC4.ARW"]["stages"]["write"] == "done"
