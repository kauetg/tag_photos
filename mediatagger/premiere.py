"""Premiere Pro export: a Final Cut 7 XML (xmeml) with one trimmed clip per moment found.

File → Import in Premiere turns it into a bin with a sequence, and (with bins on) a sub-bin
per category holding the trimmed clips. The XML only points at the video files; they are
read (ffprobe) but never changed.
"""
from __future__ import annotations

import json
import subprocess
import xml.etree.ElementTree as ET
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import quote

from .library import format_time, matching_tags, search
from .review import label
from .state import State

NTSC_RATES = {23.976: 24, 29.97: 30, 47.952: 48, 59.94: 60, 119.88: 120}
DEFAULT_PAD = 5.0  # seconds kept before and after each sampled moment
UNSORTED = "Unsorted"

# start, end, tag labels, category, [(time, tag label)] moments that fall inside the span
Span = tuple[float, float, str, str, list[tuple[float, str]]]


@dataclass
class Media:
    path: Path
    fps: float
    width: int
    height: int
    duration: float
    audio_channels: int
    audio_rate: int


def probe_media(path: Path, ffprobe: str) -> Media | None:
    proc = subprocess.run(
        [ffprobe, "-v", "error", "-show_entries",
         "stream=codec_type,width,height,r_frame_rate,channels,sample_rate:format=duration",
         "-of", "json", str(path)],
        capture_output=True, text=True,
    )
    try:
        data = json.loads(proc.stdout)
        streams = data["streams"]
        video = next(s for s in streams if s["codec_type"] == "video")
        audio = next((s for s in streams if s["codec_type"] == "audio"), None)
        num, den = video["r_frame_rate"].split("/")
        return Media(
            path=path, fps=float(num) / float(den), width=int(video["width"]), height=int(video["height"]),
            duration=float(data["format"]["duration"]),
            audio_channels=int(audio["channels"]) if audio else 0,
            audio_rate=int(audio["sample_rate"]) if audio else 48000,
        )
    except (KeyError, StopIteration, ValueError, ZeroDivisionError, json.JSONDecodeError):
        return None


def timebase(fps: float) -> tuple[int, bool]:
    """FCP7 writes frame rates as an integer timebase plus an NTSC (x1000/1001) flag."""
    for rate, base in NTSC_RATES.items():
        if abs(fps - rate) < 0.01:
            return base, True
    return round(fps), False


def real_fps(fps: float) -> float:
    base, ntsc = timebase(fps)
    return base * 1000 / 1001 if ntsc else float(base)


def category(keyword: str) -> str:
    """Top of the keyword hierarchy: 'Marine Life|Reptiles|Sea turtle' -> 'Marine Life'."""
    return keyword.split("|")[0]


def segments_for(
    entry: dict, text: str, duration: float, interval: float, pad: float = DEFAULT_PAD, whole: bool = False,
) -> list[Span]:
    """Spans of the video to put on the timeline, each with the matching moments inside it.

    Trimmed (default here): a span of `pad` seconds around each moment matching `text`,
    overlapping ones merged. `whole`: the entire file as one span, the moments only mark it.
    When the search matched the place or folder rather than a tag, the whole video is one span,
    filed under the category of the video's strongest tag.
    """
    pad = max(pad, interval / 2)  # a sampled frame stands for a slice about `interval` long
    moments = sorted(
        (t, label(tag["keyword"]), category(tag["keyword"]))
        for tag in matching_tags(entry, text) for t in tag["times"]
    )
    if not moments:
        tags = (entry.get("video") or {}).get("tags", [])
        return [(0.0, duration, "whole video", category(tags[0]["keyword"]) if tags else UNSORTED, [])]
    if whole:
        names = list(dict.fromkeys(name for _, name, _ in moments))
        top = Counter(cat for _, _, cat in moments).most_common(1)[0][0]
        return [(0.0, duration, ", ".join(names), top, [(t, name) for t, name, _ in moments])]
    spans: list[list] = []
    for t, name, cat in moments:
        start, end = max(0.0, t - pad), min(duration, t + pad)
        if spans and start <= spans[-1][1]:
            spans[-1][1] = max(spans[-1][1], end)
            if name not in spans[-1][2]:
                spans[-1][2].append(name)
            spans[-1][3].append(cat)
            spans[-1][4].append((t, name))
        else:
            spans.append([start, end, [name], [cat], [(t, name)]])
    return [(s, e, ", ".join(names), Counter(cats).most_common(1)[0][0], hits) for s, e, names, cats, hits in spans]


def _sub(parent, tag, text=None, **attrs):
    node = ET.SubElement(parent, tag, **attrs)
    if text is not None:
        node.text = str(text)
    return node


def _rate(parent, fps: float):
    base, ntsc = timebase(fps)
    rate = _sub(parent, "rate")
    _sub(rate, "timebase", base)
    _sub(rate, "ntsc", "TRUE" if ntsc else "FALSE")


def _timecode(parent, fps: float):
    tc = _sub(parent, "timecode")
    _rate(tc, fps)
    _sub(tc, "string", "00:00:00:00")
    _sub(tc, "frame", 0)
    _sub(tc, "displayformat", "NDF")


def _path_url(path: Path) -> str:
    return "file://localhost/" + quote(path.resolve().as_posix(), safe="/")


def _file_node(parent, file_id: str, media: Media, defined: set[str]):
    """The full <file> the first time it appears in the document, a bare reference afterwards."""
    node = _sub(parent, "file", id=file_id)
    if file_id in defined:
        return node
    defined.add(file_id)
    _sub(node, "name", media.path.name)
    _sub(node, "pathurl", _path_url(media.path))
    _rate(node, media.fps)
    _sub(node, "duration", round(media.duration * real_fps(media.fps)))
    _timecode(node, media.fps)
    info = _sub(node, "media")
    video = _sub(_sub(info, "video"), "samplecharacteristics")
    _rate(video, media.fps)
    _sub(video, "width", media.width)
    _sub(video, "height", media.height)
    if media.audio_channels:
        audio = _sub(info, "audio")
        characteristics = _sub(audio, "samplecharacteristics")
        _sub(characteristics, "depth", 16)
        _sub(characteristics, "samplerate", media.audio_rate)
        _sub(audio, "channelcount", media.audio_channels)
    return node


def _build_sequence(parent, items, name: str, file_ids: dict[Path, str], defined: set[str]):
    first = items[0][0]
    seq_fps = real_fps(first.fps)
    seq = _sub(parent, "sequence", id="sequence-1")
    _sub(seq, "name", name)
    duration_node = _sub(seq, "duration")
    _rate(seq, first.fps)
    _timecode(seq, first.fps)
    media_node = _sub(seq, "media")
    video = _sub(media_node, "video")
    fmt = _sub(_sub(video, "format"), "samplecharacteristics")
    _rate(fmt, first.fps)
    _sub(fmt, "width", first.width)
    _sub(fmt, "height", first.height)
    _sub(fmt, "pixelaspectratio", "square")
    vtrack = _sub(video, "track")
    atrack = _sub(_sub(media_node, "audio"), "track") if any(m.audio_channels for m, _ in items) else None

    cursor = 0.0  # seconds on the timeline
    clip_no = 0
    markers = []
    for media, spans in items:
        file_id = file_ids[media.path]
        clip_fps = real_fps(media.fps)
        for start, end, _tag_labels, _category, moments in spans:
            clip_no += 1
            length = end - start
            timeline_start = round(cursor * seq_fps)
            timeline_end = timeline_start + round(length * seq_fps)
            in_f, out_f = round(start * clip_fps), round(end * clip_fps)
            vid_id, aud_id = f"clipitem-v{clip_no}", f"clipitem-a{clip_no}"
            for track, kind, clip_id in ((vtrack, "video", vid_id), (atrack, "audio", aud_id)):
                if track is None or (kind == "audio" and not media.audio_channels):
                    continue
                clip = _sub(track, "clipitem", id=clip_id)
                _sub(clip, "name", media.path.name)
                _sub(clip, "duration", round(media.duration * clip_fps))
                _rate(clip, media.fps)
                _sub(clip, "start", timeline_start)
                _sub(clip, "end", timeline_end)
                _sub(clip, "in", in_f)
                _sub(clip, "out", out_f)
                _file_node(clip, file_id, media, defined)
                if kind == "audio":
                    src = _sub(clip, "sourcetrack")
                    _sub(src, "mediatype", "audio")
                    _sub(src, "trackindex", 1)
                if media.audio_channels:
                    for ref, mtype in ((vid_id, "video"), (aud_id, "audio")):
                        link = _sub(clip, "link")
                        _sub(link, "linkclipref", ref)
                        _sub(link, "mediatype", mtype)
                        _sub(link, "trackindex", 1)
                        _sub(link, "clipindex", clip_no)
            for t, tag_label in moments:  # one marker where each match falls on the timeline
                frame = timeline_start + round((t - start) * seq_fps)
                markers.append((frame, tag_label, f"{media.path.name} @ {format_time(t)}"))
            cursor += length

    duration_node.text = str(round(cursor * seq_fps))
    # Sequence markers go before <media>, the order FCP7 itself writes.
    for frame, marker_name, comment in markers:
        marker = ET.Element("marker")
        _sub(marker, "name", marker_name)
        _sub(marker, "comment", comment)
        _sub(marker, "in", frame)
        _sub(marker, "out", -1)
        seq.insert(list(seq).index(media_node), marker)
    return seq


def _build_category_bins(parent, items, file_ids: dict[Path, str], defined: set[str]):
    """One bin per category, each holding a trimmed clip per span (sorted by category name)."""
    by_category: dict[str, list] = {}
    for media, spans in items:
        for start, end, tag_label, cat, _moments in spans:
            by_category.setdefault(cat, []).append((media, start, end, tag_label))
    number = 0
    for cat in sorted(by_category):
        bin_node = _sub(parent, "bin")
        _sub(bin_node, "name", cat)
        children = _sub(bin_node, "children")
        for media, start, end, tag_label in by_category[cat]:
            number += 1
            clip_fps = real_fps(media.fps)
            clip = _sub(children, "clip", id=f"clip-{number}")
            _sub(clip, "name", f"{media.path.stem} {format_time(start)} {tag_label}")
            _sub(clip, "duration", round(media.duration * clip_fps))
            _rate(clip, media.fps)
            _sub(clip, "in", round(start * clip_fps))
            _sub(clip, "out", round(end * clip_fps))
            _file_node(clip, file_ids[media.path], media, defined)


def build_xml(items: list[tuple[Media, list[Span]]], name: str, bins: bool = True) -> str:
    """items: (media, spans) per video, in the order they should appear on the timeline."""
    if not items:
        raise ValueError("nothing to export")
    file_ids: dict[Path, str] = {}
    for media, _ in items:
        file_ids.setdefault(media.path, f"file-{len(file_ids) + 1}")
    defined: set[str] = set()

    root = ET.Element("xmeml", version="4")
    if bins:
        project = _sub(root, "project")
        _sub(project, "name", name)
        outer = _sub(_sub(project, "children"), "bin")
        _sub(outer, "name", name)
        children = _sub(outer, "children")
        _build_category_bins(children, items, file_ids, defined)  # first, so it holds the full <file>s
        _build_sequence(children, items, name, file_ids, defined)
    else:
        _build_sequence(root, items, name, file_ids, defined)

    ET.indent(root)
    return '<?xml version="1.0" encoding="UTF-8"?>\n<!DOCTYPE xmeml>\n' + ET.tostring(root, encoding="unicode") + "\n"


def export_selection(
    state: State, media_root: Path, ffprobe: str, selection: dict[str, str], name: str,
    pad: float = DEFAULT_PAD, bins: bool = True, whole: bool = True,
) -> tuple[str, dict]:
    """XML for the chosen videos. `selection` maps a state key to the search text it was picked
    with, so each video's markers (or trimmed spans) are the ones that search found."""
    items, skipped = [], []
    ordered = sorted(selection, key=lambda k: (state.files[k].get("folder_date") or "", k))
    for key in ordered:
        entry = state.files[key]
        media = probe_media(media_root / key, ffprobe)
        if media is None:
            skipped.append(key)
            continue
        spans = segments_for(entry, selection[key], media.duration, entry["video"].get("interval", 5.0), pad, whole)
        items.append((media, spans))
    xml = build_xml(items, name, bins=bins)
    categories = sorted({span[3] for _, spans in items for span in spans})
    return xml, {"videos": len(items), "clips": sum(len(s) for _, s in items), "skipped": skipped, "categories": categories}


def export_search(
    state: State, media_root: Path, ffprobe: str, text: str = "", pad: float = DEFAULT_PAD, bins: bool = True,
    whole: bool = True, **filters,
) -> tuple[str, dict]:
    """XML for every indexed video matching the search. Returns (xml, summary)."""
    selection = {key: text for key in search(state, text, kinds=("video",), **filters)}
    return export_selection(
        state, media_root, ffprobe, selection, f"Search - {text}" if text else "Library export", pad, bins, whole,
    )
