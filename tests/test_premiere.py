import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

from mediatagger.premiere import Media, build_xml, real_fps, segments_for, timebase

TURTLE = "Marine Life|Reptiles|Sea turtle"


def entry(times):
    return {"video": {"tags": [{"keyword": TURTLE, "times": times, "hits": len(times)}]}}


def media(name="clip.mp4", fps=29.97, duration=60.0, audio=2):
    return Media(Path("C:/media/ação") / name, fps, 3840, 2160, duration, audio, 48000)


def parse(xml):
    return ET.fromstring(xml.split("\n", 2)[2])  # skip the XML declaration and DOCTYPE


def span(start, end, label="Sea turtle", cat="Marine Life", moments=()):
    return (start, end, label, cat, list(moments))


def test_timebase_flags_ntsc_rates():
    assert timebase(29.97) == (30, True) and timebase(25.0) == (25, False) and timebase(59.94) == (60, True)
    assert real_fps(29.97) == pytest.approx(29.97, abs=0.01)


def test_trimmed_segments_pad_clamp_and_merge():
    spans = segments_for(entry([2.0, 8.0, 40.0]), "turtle", duration=60, interval=5, pad=5)
    assert spans == [
        (0.0, 13.0, "Sea turtle", "Marine Life", [(2.0, "Sea turtle"), (8.0, "Sea turtle")]),
        (35.0, 45.0, "Sea turtle", "Marine Life", [(40.0, "Sea turtle")]),
    ]
    assert segments_for(entry([58.0]), "turtle", duration=60, interval=5, pad=5)[0][:2] == (53.0, 60.0)


def test_whole_file_is_one_span_with_every_moment_inside_it():
    (only,) = segments_for(entry([2.0, 8.0, 40.0]), "turtle", duration=60, interval=5, whole=True)
    assert only[:4] == (0.0, 60.0, "Sea turtle", "Marine Life")
    assert [t for t, _ in only[4]] == [2.0, 8.0, 40.0]


def test_search_matching_the_place_not_a_tag_uses_the_whole_video():
    assert segments_for(entry([2.0]), "komodo", duration=30, interval=5) == [(0.0, 30.0, "whole video", "Marine Life", [])]
    assert segments_for({"video": {"tags": []}}, "komodo", duration=30, interval=5)[0][3] == "Unsorted"


def test_span_category_follows_the_majority_tag():
    both = {"video": {"tags": [
        {"keyword": "Scene|Resort", "times": [10.0]},
        {"keyword": "Marine Life|Fish|Fish school", "times": [11.0, 12.0]},
    ]}}
    (merged,) = segments_for(both, "", duration=60, interval=5, pad=5)
    assert merged[3] == "Marine Life" and merged[2].count(",") == 1  # one merged span naming both tags


def test_bins_group_clips_by_category():
    items = [
        (media("a.mp4"), [span(10.0, 20.0), span(30.0, 35.0, "Resort", "Scene")]),
        (media("b.mp4"), [span(0.0, 5.0, "Fish school")]),
    ]
    root = parse(build_xml(items, "Search - x"))
    outer = root.find("./project/children/bin")
    assert outer.findtext("name") == "Search - x"
    bins = {b.findtext("name"): b.findall("children/clip") for b in outer.findall("children/bin")}
    assert sorted(bins) == ["Marine Life", "Scene"] and [len(v) for v in bins.values()] == [2, 1]
    clip = bins["Marine Life"][0]
    assert (clip.findtext("in"), clip.findtext("out")) == ("300", "599")
    assert outer.find("children/sequence") is not None  # same outer bin, after the category bins
    # each file is fully described once in the whole document, and that is inside a category bin
    assert len(root.findall(".//file/pathurl")) == 2
    assert root.find(".//sequence//file/pathurl") is None


def test_without_bins_the_sequence_is_the_root_child():
    root = parse(build_xml([(media(), [span(0.0, 5.0)])], "n", bins=False))
    assert root.find("./sequence") is not None and root.find("./project") is None
    assert len(root.findall(".//file/pathurl")) == 1


def test_trimmed_xml_structure_and_frame_math():
    spans = [span(10.0, 20.0, moments=[(12.0, "Sea turtle")]), span(30.0, 35.0, moments=[(31.0, "Sea turtle")])]
    root = parse(build_xml([(media(), spans)], "Search - turtle", bins=False))
    assert root.tag == "xmeml" and root.get("version") == "4"
    video_clips = root.findall("./sequence/media/video/track/clipitem")
    assert len(video_clips) == 2 and len(root.findall("./sequence/media/audio/track/clipitem")) == 2
    first, second = video_clips
    assert (first.findtext("in"), first.findtext("out")) == ("300", "599")  # 10 s and 20 s at 29.97 fps
    assert (first.findtext("start"), first.findtext("end")) == ("0", "300")
    assert second.findtext("start") == "300"  # clips are laid back to back
    assert root.findtext("./sequence/duration") == "450"  # 15 s
    assert root.find("./sequence/rate/ntsc").text == "TRUE"
    assert first.find("file/pathurl") is not None and second.find("file/pathurl") is None
    assert "%C3%A7%C3%A3o" in first.findtext("file/pathurl")  # accents are percent-encoded
    frames = [m.findtext("in") for m in root.findall("./sequence/marker")]
    assert frames == ["60", "330"]  # 2 s into the first clip, 1 s into the second (starts at frame 300)


def test_whole_file_clip_is_untrimmed_and_marked_at_each_moment():
    spans = [span(0.0, 60.0, moments=[(12.0, "Sea turtle"), (40.0, "Sea turtle")])]
    root = parse(build_xml([(media(), spans)], "n", bins=False))
    (clip,) = root.findall("./sequence/media/video/track/clipitem")
    assert (clip.findtext("in"), clip.findtext("out")) == ("0", "1798")  # 60 s at 29.97 fps
    assert [m.findtext("in") for m in root.findall("./sequence/marker")] == ["360", "1199"]
    assert root.findtext("./sequence/marker/comment") == "clip.mp4 @ 0:12"


def test_selection_uses_each_videos_own_search_and_date_order(monkeypatch, tmp_path):
    from mediatagger import premiere
    from mediatagger.state import State

    monkeypatch.setattr(premiere, "probe_media", lambda path, ffprobe: media(path.name))
    state = State(tmp_path / "s.json")
    manta = "Marine Life|Sharks and Rays|Ray|Manta ray"
    state.files = {
        "20260716 b/v/late.mp4": {"folder_date": "20260716", "video": {"interval": 5.0, "tags": [{"keyword": TURTLE, "times": [10.0]}]}},
        "20260125 a/v/early.mp4": {"folder_date": "20260125", "video": {"interval": 5.0, "tags": [
            {"keyword": TURTLE, "times": [20.0]}, {"keyword": manta, "times": [30.0]}]}},
    }
    selection = {"20260716 b/v/late.mp4": "turtle", "20260125 a/v/early.mp4": "manta"}
    xml, summary = premiere.export_selection(state, lambda key: tmp_path / key, "ffprobe", selection, "Selected videos", bins=False)
    root = parse(xml)
    names = [c.findtext("name") for c in root.findall("./sequence/media/video/track/clipitem")]
    assert names == ["early.mp4", "late.mp4"]  # oldest dive first
    assert [m.findtext("name") for m in root.findall("./sequence/marker")] == ["Manta ray", "Sea turtle"]
    assert summary["videos"] == 2 and summary["skipped"] == []


def test_video_without_audio_has_no_audio_track_items():
    root = parse(build_xml([(media(audio=0), [span(0.0, 5.0, cat="Scene")])], "n", bins=False))
    assert root.findall("./sequence/media/audio/track/clipitem") == []
    assert len(root.findall("./sequence/media/video/track/clipitem")) == 1


def test_nothing_to_export_is_an_error():
    with pytest.raises(ValueError):
        build_xml([], "empty")
