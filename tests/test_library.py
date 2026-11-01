from mediatagger.library import dive_folder, format_time, matching_tags, search, videos_near
from mediatagger.review import decide
from mediatagger.state import State

TURTLE = "Marine Life|Reptiles|Sea turtle"
SIQUI = {"keyword": "Location|Philippines|Siquijor", "country": "Philippines", "city": "Siquijor"}
KOMODO = {"keyword": "Location|Indonesia|Komodo", "country": "Indonesia", "city": "Komodo"}


def make_state(tmp_path):
    state = State(tmp_path / "state.json")
    photo_tags = {"scene": {"underwater": 1.0}, "suggestions": [{"keyword": TURTLE, "prob": 0.98, "tier": "core"}]}
    state.files = {
        "Test/20260125 Siqui/photo/img1.arw": {"kind": "raw", "folder_date": "20260125", "location": SIQUI, "tags": photo_tags},
        "Test/20260125 Siqui/video/clip.mp4": {
            "kind": "video", "folder_date": "20260125", "location": SIQUI,
            "video": {"tags": [{"keyword": TURTLE, "best": 0.9, "best_t": 12.0, "hits": 3, "times": [10, 12, 14]}]},
        },
        "Test/20260713 Komodo/video/manta.mp4": {
            "kind": "video", "folder_date": "20260713", "location": KOMODO,
            "video": {"tags": [{"keyword": "Marine Life|Sharks and Rays|Ray|Manta ray", "best": 0.8, "best_t": 5.0, "hits": 1, "times": [5]}]},
        },
        "Test/20260713 Komodo/video/untagged.mp4": {"kind": "video", "folder_date": "20260713", "location": KOMODO},
    }
    return state


def test_untagged_files_are_not_in_the_index(tmp_path):
    keys = search(make_state(tmp_path))
    assert "Test/20260713 Komodo/video/untagged.mp4" not in keys and len(keys) == 3


def test_text_search_uses_the_hierarchy_and_ignores_accents(tmp_path):
    state = make_state(tmp_path)
    assert len(search(state, "reptiles")) == 2  # parent level of the turtle path
    assert search(state, "MANTA") == ["Test/20260713 Komodo/video/manta.mp4"]
    assert search(state, "turtle komodo") == []  # every word must match


def test_filters(tmp_path):
    state = make_state(tmp_path)
    assert len(search(state, kinds=("video",))) == 2
    assert search(state, country="Indonesia") == ["Test/20260713 Komodo/video/manta.mp4"]
    assert len(search(state, date_to="20260131")) == 2
    assert len(search(state, folder="Test/20260125 Siqui")) == 2


def test_photo_review_decides_what_is_searchable(tmp_path):
    state = make_state(tmp_path)
    photo = state.files["Test/20260125 Siqui/photo/img1.arw"]
    decide(photo, [], approved=True)  # reviewer ticked nothing
    assert "Test/20260125 Siqui/photo/img1.arw" not in search(state, "turtle")
    assert "Test/20260125 Siqui/photo/img1.arw" in search(state, "siquijor")  # location still counts


def test_scene_filter_uses_the_detected_scene_or_the_one_you_picked(tmp_path):
    state = make_state(tmp_path)
    photo = state.files["Test/20260125 Siqui/photo/img1.arw"]
    photo["tags"]["scene"] = {"underwater": 0.9, "drone": 0.1}
    state.files["Test/20260125 Siqui/video/clip.mp4"]["video"]["scene"] = {"underwater": 0.2, "drone": 0.8}
    state.files["Test/20260713 Komodo/video/manta.mp4"]["video"]["scene"] = {"underwater": 1.0}
    assert search(state, scene="underwater") == ["Test/20260125 Siqui/photo/img1.arw", "Test/20260713 Komodo/video/manta.mp4"]
    assert search(state, scene="drone") == ["Test/20260125 Siqui/video/clip.mp4"]
    decide(photo, [], approved=True, scene="land")  # corrected in the review page
    assert search(state, scene="land") == ["Test/20260125 Siqui/photo/img1.arw"]
    assert "Test/20260125 Siqui/photo/img1.arw" not in search(state, scene="underwater")


def test_videos_near_a_photo(tmp_path):
    state = make_state(tmp_path)
    assert videos_near(state, "Test/20260125 Siqui/photo/img1.arw") == ["Test/20260125 Siqui/video/clip.mp4"]
    assert dive_folder("D/b/c.mp4") == "D/b"


def test_matching_tags_and_time_format(tmp_path):
    entry = make_state(tmp_path).files["Test/20260125 Siqui/video/clip.mp4"]
    assert matching_tags(entry, "turtle") and matching_tags(entry, "shark") == []
    assert matching_tags(entry, "") == entry["video"]["tags"]
    assert format_time(75) == "1:15" and format_time(3725) == "1:02:05"
