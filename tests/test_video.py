from types import SimpleNamespace

from mediatagger.state import State
from mediatagger.video import aggregate, sample_times, select_files


def frame(scene, *tags):
    return {"scene": scene, "suggestions": [SimpleNamespace(keyword=k, prob=p, tier="core") for k, p in tags]}


def test_sample_times_are_centred_and_capped():
    assert sample_times(10, interval=5) == [2.5, 7.5]
    assert sample_times(0) == []
    times = sample_times(7200, interval=5, max_frames=120)  # 2 h would be 1440 frames
    assert len(times) == 120 and times[0] < 60 and times[-1] > 7140


def test_aggregate_counts_hits_and_remembers_the_best_moment():
    frames = [
        (5.0, frame({"underwater": 1.0}, ("Turtle", 0.6), ("Fish", 0.3))),
        (10.0, frame({"underwater": 1.0}, ("Turtle", 0.95))),
        (15.0, frame({"underwater": 0.0}, ("Fish", 0.7))),
    ]
    out = aggregate(frames)
    turtle = next(t for t in out["tags"] if t["keyword"] == "Turtle")
    assert turtle["hits"] == 2 and turtle["best"] == 0.95 and turtle["best_t"] == 10.0
    assert turtle["times"] == [5.0, 10.0]
    assert [t["keyword"] for t in out["tags"]] == ["Turtle", "Fish"]  # 0.3 is below the threshold
    assert round(out["scene"]["underwater"], 2) == 0.67


def test_compose_strip_picks_evenly_and_keeps_the_aspect_ratio():
    from PIL import Image

    from mediatagger.video import compose_strip

    frames = [(float(i), Image.new("RGB", (640, 360), (i * 10, 0, 0))) for i in range(40)]
    strip, meta = compose_strip(frames, count=12, tile_h=108)
    assert meta["n"] == 12 and (meta["tile_w"], meta["tile_h"]) == (192, 108)
    assert strip.size == (192 * 12, 108)
    assert meta["times"][0] == 0.0 and meta["times"][-1] == 39.0 and meta["times"] == sorted(meta["times"])
    short, short_meta = compose_strip(frames[:3], count=12)
    assert short_meta["n"] == 3 and short.size[0] == 192 * 3  # never more tiles than frames


def test_select_files_skips_done_photos_and_missing(tmp_path):
    state = State(tmp_path / "s.json")
    state.files = {
        "a/one.mp4": {"kind": "video"},
        "a/two.mp4": {"kind": "video", "stages": {"video": "done"}},
        "a/gone.mp4": {"kind": "video", "missing": True},
        "a/photo.arw": {"kind": "raw"},
    }
    assert select_files(state, None, None, redo=False) == ["a/one.mp4"]
    assert select_files(state, None, None, redo=True) == ["a/one.mp4", "a/two.mp4"]
