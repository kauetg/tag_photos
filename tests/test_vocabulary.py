import pytest

from mediatagger.config import PROJECT_ROOT
from mediatagger.vocabulary import (
    SCENES, VocabEntry, add_manual_tag, ancestors, load_vocabulary, pretty, save_vocabulary, validate,
)

TURTLE = "Marine Life|Reptiles|Sea turtle"


def entry(keyword, tier="core", scenes=("underwater",), prompt="x", aliases=()):
    return VocabEntry(keyword, prompt, "", frozenset(scenes), tier, tuple(aliases))


def test_real_vocabulary_passes_validation():
    assert validate(load_vocabulary(PROJECT_ROOT / "config" / "vocabulary.csv")) == []


def test_save_roundtrip_keeps_aliases_and_writes_a_backup(tmp_path):
    path = tmp_path / "vocabulary.csv"
    rows = [entry(TURTLE, aliases=("turtle", "tortuga")), entry(TURTLE + "|Green sea turtle", "species")]
    save_vocabulary(path, rows)
    assert load_vocabulary(path) == rows
    save_vocabulary(path, rows[:1])  # second save keeps the previous file
    assert len(load_vocabulary(path.with_name("vocabulary.csv.bak"))) == 2
    assert not path.with_name("vocabulary.csv.tmp").exists()


def test_validate_catches_the_mistakes_a_hand_edit_can_make():
    problems = validate([
        entry("A|B"), entry("a|b"),  # duplicate ignoring case
        entry("A||C"),  # empty level
        entry("X|Y", tier="species"),  # species without a core parent
        entry("Q|R", scenes=("sky",)),  # unknown scene
        entry("M|N", prompt=""),  # model rows need a prompt
        entry("M|O", tier="manual", prompt=""),  # manual rows do not
        entry("T|U", tier="weird"),
    ])
    text = " ".join(problems)
    for expected in ("duplicated", "every level", "core group", "scene must be", "prompt is empty", "tier must be"):
        assert expected in text
    assert "M|O" not in text


def test_a_bad_vocabulary_is_never_written(tmp_path):
    path = tmp_path / "vocabulary.csv"
    save_vocabulary(path, [entry("A|B")])
    with pytest.raises(ValueError):
        save_vocabulary(path, [entry("A|B"), entry("A|B")])
    assert [e.keyword for e in load_vocabulary(path)] == ["A|B"]  # the good file is untouched


def test_old_topside_name_is_read_as_drone(tmp_path):
    path = tmp_path / "vocabulary.csv"
    path.write_text(
        "keyword,prompt,scientific_name,scene,tier,aliases\nScene|Beach,a beach,,topside;land,core,\n", encoding="utf-8"
    )
    (beach,) = load_vocabulary(path)
    assert beach.scenes == frozenset({"drone", "land"}) and validate([beach]) == []


def test_state_load_renames_the_old_scene_everywhere(tmp_path):
    import json

    from mediatagger.state import State

    path = tmp_path / "state.json"
    files = {
        "a/photo.arw": {"kind": "raw", "tags": {"scene": {"underwater": 0.1, "topside": 0.9}}, "review": {"status": "approved", "scene": "topside"}},
        "a/clip.mp4": {"kind": "video", "video": {"scene": {"topside": 0.6, "land": 0.4}}},
    }
    path.write_text(json.dumps({"version": 1, "files": files}), encoding="utf-8")
    state = State.load(path)
    assert state.files["a/photo.arw"]["tags"]["scene"] == {"underwater": 0.1, "drone": 0.9}
    assert state.files["a/photo.arw"]["review"]["scene"] == "drone"
    assert state.files["a/clip.mp4"]["video"]["scene"] == {"drone": 0.6, "land": 0.4}
    State.load(path)  # already migrated data loads unchanged
    state.save()
    assert "topside" not in path.read_text(encoding="utf-8")


def test_add_manual_tag(tmp_path):
    path = tmp_path / "vocabulary.csv"
    save_vocabulary(path, [entry("Conservation|Impact|Marine debris")])
    keyword = add_manual_tag(path, "Conservation|Impact", "Coral bleaching", "bleaching event, white coral")
    assert keyword == "Conservation|Impact|Coral bleaching"
    added = load_vocabulary(path)[-1]
    assert added.tier == "manual" and added.scenes == frozenset(SCENES)
    assert added.aliases == ("bleaching event", "white coral")
    with pytest.raises(ValueError):
        add_manual_tag(path, "Conservation|Impact", "coral BLEACHING")  # same name, other case
    with pytest.raises(ValueError):
        add_manual_tag(path, "Conservation", "")


def test_ancestors_and_pretty_labels():
    rows = [entry(TURTLE, aliases=("turtle",)), entry("Coral|Soft coral")]
    assert ancestors(rows) == ["Coral", "Marine Life", "Marine Life|Reptiles"]
    by_keyword = {e.keyword: e for e in rows}
    assert pretty(TURTLE, by_keyword) == "Marine Life › Reptiles › Sea turtle (turtle)"
    assert pretty("Coral|Soft coral", by_keyword) == "Coral › Soft coral"
    assert pretty("Not|In vocabulary", by_keyword) == "Not › In vocabulary"
