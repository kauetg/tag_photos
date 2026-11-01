from pathlib import Path

import pytest

from mediatagger.config import PROJECT_ROOT, load_config
from mediatagger.places import (
    DateRule, NameRule, default_keyword, load_date_rules, load_name_rules, save_date_rules, save_name_rules,
    unmapped_folders, validate_date_rules, validate_name_rules,
)
from mediatagger.scan import relocate, resolve_location
from mediatagger.state import State

RAWA = NameRule("Rawa", "Location|Malaysia|Johor|Rawa Island", "Malaysia", "Mersing", "Rawa Island")


def test_real_files_pass_validation():
    config = PROJECT_ROOT / "config"
    assert validate_name_rules(load_name_rules(config / "locations.csv")) == []
    assert validate_date_rules(load_date_rules(config / "date_ranges.csv")) == []


def test_default_keyword_skips_blank_levels():
    assert default_keyword("Malaysia", "Mersing", "Rawa Island") == "Location|Malaysia|Mersing|Rawa Island"
    assert default_keyword("Philippines", "", "") == "Location|Philippines"


def test_name_rules_roundtrip_and_backup(tmp_path):
    path = tmp_path / "locations.csv"
    rules = [RAWA, NameRule("Siqui", "Location|Philippines|Siquijor", "Philippines", "Siquijor")]
    save_name_rules(path, rules)
    assert load_name_rules(path) == rules
    save_name_rules(path, rules[:1])
    assert len(load_name_rules(path.with_name("locations.csv.bak"))) == 2
    assert not path.with_name("locations.csv.tmp").exists()


def test_name_rule_mistakes_are_caught_and_nothing_is_written(tmp_path):
    problems = " ".join(validate_name_rules([
        RAWA, NameRule("rawa", "Location|Malaysia|Rawa", "Malaysia"),  # same word, other case
        NameRule("Komodo", "Komodo", "Indonesia"),  # keyword without the Location| start
        NameRule("Bali", "Location|Indonesia|Bali", ""),  # no country
    ]))
    for expected in ("written twice", "must start with Location|", "country is empty"):
        assert expected in problems
    path = tmp_path / "locations.csv"
    save_name_rules(path, [RAWA])
    with pytest.raises(ValueError):
        save_name_rules(path, [RAWA, RAWA])
    assert load_name_rules(path) == [RAWA]  # the good file is untouched


def test_date_rules_are_validated_and_saved_in_date_order(tmp_path):
    problems = " ".join(validate_date_rules([
        DateRule("20260230", "20260301", "Location|X", "X"),  # not a real day
        DateRule("20260310", "20260301", "Location|X", "X"),  # ends before it starts
    ]))
    assert "real days" in problems and "before the start" in problems
    path = tmp_path / "date_ranges.csv"
    later = DateRule("20260601", "20260610", "Location|Indonesia|Komodo", "Indonesia", note="trip")
    earlier = DateRule("20260101", "20260110", "Location|Philippines", "Philippines")
    save_date_rules(path, [later, earlier])
    assert load_date_rules(path) == [earlier, later]


def make_cfg(tmp_path, names, dates):
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    save_name_rules(config_dir / "locations.csv", names)
    save_date_rules(config_dir / "date_ranges.csv", dates)
    return load_config(config_dir=config_dir, media_root=str(tmp_path))


def test_relocate_applies_edited_rules_and_keeps_review_choices(tmp_path):
    cfg = make_cfg(tmp_path, [RAWA], [DateRule("20260301", "20260331", "Location|Philippines", "Philippines")])
    state = State(tmp_path / "state.json")
    state.files = {
        "D/20260312 Rawa dive/a.arw": {"folder_date": "20260312", "location": None, "review": {"status": "approved", "keywords": [], "location": {"keyword": "Location|Mine"}}},
        "D/20260320 Mystery/b.arw": {"folder_date": "20260320", "location": {"keyword": "Location|Old"}},
        "D/20270101 Nowhere/c.arw": {"folder_date": "20270101", "location": None},
    }
    counts = relocate(cfg, state)
    assert counts == {"changed": 2, "unchanged": 1, "without_location": 1}
    assert state.files["D/20260312 Rawa dive/a.arw"]["location"]["source"] == "name"
    assert state.files["D/20260312 Rawa dive/a.arw"]["review"]["location"] == {"keyword": "Location|Mine"}  # untouched
    assert state.files["D/20260320 Mystery/b.arw"]["location"]["source"] == "date"
    assert state.files["D/20270101 Nowhere/c.arw"]["location"] is None
    assert relocate(cfg, state)["changed"] == 0  # a second run has nothing left to do


def test_resolve_location_prefers_the_name_over_the_date(tmp_path):
    cfg = make_cfg(tmp_path, [RAWA], [DateRule("20260301", "20260331", "Location|Philippines", "Philippines")])
    assert resolve_location(cfg, ("20260312 Rawa trip",), "20260312")["source"] == "name"
    assert resolve_location(cfg, ("20260312 Other",), "20260312")["keyword"] == "Location|Philippines"
    assert resolve_location(cfg, ("20260101 Other",), "20260101") is None


def test_unmapped_folders_counts_files_per_top_folder(tmp_path):
    state = State(tmp_path / "state.json")
    state.files = {
        "D/A/x/1.arw": {"location": None}, "D/A/2.arw": {"location": None}, "D/B/3.arw": {"location": {"keyword": "Location|X"}},
        "D/C/4.arw": {"location": None, "missing": True}, "D/5.arw": {"location": None},
    }
    assert dict(unmapped_folders(state)) == {"D/A": 2, "D/(root)": 1}
