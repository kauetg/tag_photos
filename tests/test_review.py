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
                "scene": {"underwater": 0.9, "drone": 0.1},
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


def tagged(*suggestions):
    return {"kind": "raw", "tags": {"scene": {"underwater": 1.0}, "suggestions": [
        {"keyword": k, "prob": p, "tier": t} for k, p, t in suggestions]}}


def test_triage_bands():
    from mediatagger.review import triage

    turtle = "Marine Life|Reptiles|Sea turtle"
    assert triage(tagged((turtle, 0.98, "core"))) == ("auto", [turtle])
    assert triage(tagged((turtle, 0.98, "core"), ("Activity|Scuba diving", 0.6, "core")))[0] == "review"
    assert triage(tagged((turtle, 0.7, "core")))[0] == "review"
    assert triage(tagged((turtle, 0.3, "core"))) == ("auto", [])  # nothing clear: location only
    # species never make a photo automatic, and never block one that is otherwise clear
    assert triage(tagged((turtle, 0.98, "core"), (turtle + "|Green sea turtle", 0.6, "species"))) == ("auto", [turtle])


def test_apply_triage_keeps_human_decisions(tmp_path):
    from mediatagger.review import AUTO, apply_triage, is_sample

    turtle = "Marine Life|Reptiles|Sea turtle"
    state = State(tmp_path / "state.json")
    keys = [f"f/{i}.arw" for i in range(200)]
    state.files = {k: tagged((turtle, 0.98, "core")) for k in keys}
    state.files["f/human.arw"] = tagged((turtle, 0.98, "core"))
    decide(state.files["f/human.arw"], [], approved=False)
    state.files["f/unsure.arw"] = tagged((turtle, 0.6, "core"))
    counts = apply_triage(state)
    assert status(state.files["f/human.arw"]) == "skipped" and counts["kept"] == 1
    assert status(state.files["f/unsure.arw"]) == PENDING and counts["review"] == 1
    samples = [k for k in keys if is_sample(k)]
    assert counts["sample"] == len(samples) and 0 < len(samples) < 20
    assert counts[AUTO] == 200 - len(samples)
    assert all(status(state.files[k]) == PENDING for k in samples)
    assert apply_triage(state) == counts  # idempotent


def test_split_by_confidence_puts_only_clear_core_tags_in_sure():
    from mediatagger.review import split_by_confidence

    turtle = "Marine Life|Reptiles|Sea turtle"
    entry = tagged(
        (turtle, 0.98, "core"), ("Activity|Scuba diving", 0.6, "core"),
        (turtle + "|Green sea turtle", 0.95, "species"),  # species are never "sure"
    )
    assert split_by_confidence(entry) == ([turtle], ["Activity|Scuba diving", turtle + "|Green sea turtle"])


def test_review_location_overrides_the_folder_location():
    from mediatagger.review import effective_location

    entry = tagged()
    entry["location"] = {"keyword": "Location|Philippines|Siquijor", "city": "Siquijor"}
    assert effective_location(entry)["city"] == "Siquijor"
    decide(entry, [], approved=True, location={"keyword": "Location|Philippines|Bohol", "city": "Bohol"})
    assert effective_location(entry)["city"] == "Bohol"
    decide(entry, [], approved=True)  # approving again without touching the place drops the override
    assert effective_location(entry)["city"] == "Siquijor"
    decide(entry, [], approved=False, location={"keyword": "x"})  # a skip never stores a place
    assert "location" not in entry["review"]


def test_scene_is_detected_from_photos_and_videos_and_can_be_overridden():
    from mediatagger.review import detected_scene, effective_scene

    photo = tagged()
    photo["tags"]["scene"] = {"underwater": 0.1, "drone": 0.8, "land": 0.1}
    assert detected_scene(photo) == "drone"
    video = {"kind": "video", "video": {"scene": {"underwater": 0.7, "drone": 0.2, "land": 0.1}}}
    assert detected_scene(video) == "underwater"
    assert detected_scene({"kind": "raw"}) is None
    decide(photo, [], approved=True, scene="underwater")  # the person says it is actually underwater
    assert effective_scene(photo) == "underwater" and detected_scene(photo) == "drone"
    decide(photo, [], approved=False, scene="land")  # a skip never stores a scene
    assert effective_scene(photo) == "drone"


def test_apply_triage_only_new_leaves_existing_reviews_alone(tmp_path):
    from mediatagger.review import AUTO, apply_triage

    turtle = "Marine Life|Reptiles|Sea turtle"
    state = State(tmp_path / "state.json")
    state.files = {"a/new.arw": tagged((turtle, 0.98, "core")), "a/old.arw": tagged((turtle, 0.98, "core"))}
    state.files["a/old.arw"]["review"] = {"status": AUTO, "keywords": []}  # an earlier triage with other thresholds
    counts = apply_triage(state, only_new=True)
    assert state.files["a/old.arw"]["review"]["keywords"] == []
    assert state.files["a/new.arw"]["review"]["keywords"] == [turtle]
    assert counts["kept"] == 1


def test_known_locations_merges_locations_and_date_ranges():
    from types import SimpleNamespace

    from mediatagger.review import known_locations, place_label

    loc = SimpleNamespace(keyword="Location|Malaysia|Johor|Rawa Island", country="Malaysia", city="Mersing", sublocation="Rawa Island")
    dated = SimpleNamespace(location=SimpleNamespace(keyword="Location|Philippines", country="Philippines", city="", sublocation=""))
    repeated = SimpleNamespace(location=SimpleNamespace(**vars(loc)))  # a DateRange wraps a Location
    cfg = SimpleNamespace(locations=[loc], date_ranges=[dated, repeated])
    places = known_locations(cfg)
    assert [place_label(p) for p in places] == ["Rawa Island, Mersing, Malaysia", "Philippines"]  # sorted by country, no repeats


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
