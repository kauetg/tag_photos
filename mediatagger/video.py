"""video: sample frames, classify them, keep a per-video summary with timestamps.

Videos are only ever read. Frames go to a temp folder and the results live in
state.json under "video"; nothing is written to or next to the video files.
"""
from __future__ import annotations

import math
import subprocess
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from PIL import Image

from .classify import HybridTagger
from .config import Config
from .device import pick_device
from .review import THRESHOLD
from .state import State
from .thumbs import thumb_path
from .timing import timing_line
from .tools import find_tool
from .vocabulary import load_vocabulary

INTERVAL = 5.0  # seconds between sampled frames, stretched for long videos
MAX_FRAMES = 120  # cap per video, so a 2-hour clip costs the same as a 10-minute one
FRAME_SIDE = 640
BATCH_SIZE = 16
MAX_TIMES = 20  # timestamps kept per tag
THUMB_SIDE = 480
STRIP_FRAMES = 12  # frames in the hover-scrub strip
STRIP_TILE_H = 108  # height of one strip frame in pixels


def probe_duration(path: Path, ffprobe: str) -> float:
    proc = subprocess.run(
        [ffprobe, "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(path)],
        capture_output=True, text=True,
    )
    try:
        return float(proc.stdout.strip())
    except ValueError:
        return 0.0


def sample_times(duration: float, interval: float = INTERVAL, max_frames: int = MAX_FRAMES) -> list[float]:
    """Evenly spaced moments, each in the middle of its slice of the video."""
    if duration <= 0:
        return []
    count = min(max_frames, max(1, math.ceil(duration / interval)))
    step = duration / count
    return [round(step * (i + 0.5), 2) for i in range(count)]


def extract_frame(path: Path, t: float, ffmpeg: str, out: Path) -> bool:
    """One frame by fast seek (no decoding of everything before it)."""
    proc = subprocess.run(
        [ffmpeg, "-nostdin", "-v", "error", "-ss", str(t), "-i", str(path), "-frames:v", "1",
         "-vf", f"scale='min({FRAME_SIDE},iw)':-2", "-q:v", "3", "-y", str(out)],
        capture_output=True,
    )
    return proc.returncode == 0 and out.exists() and out.stat().st_size > 0


def compose_strip(frames: list[tuple[float, Image.Image]], count: int = STRIP_FRAMES, tile_h: int = STRIP_TILE_H) -> tuple[Image.Image, dict]:
    """Evenly chosen frames side by side in one image, for the hover-scrub in the Library page."""
    count = min(count, len(frames))
    chosen = [frames[round(i * (len(frames) - 1) / max(count - 1, 1))] for i in range(count)]
    tile_w = max(1, round(chosen[0][1].width * tile_h / chosen[0][1].height))
    strip = Image.new("RGB", (tile_w * count, tile_h))
    for i, (_, image) in enumerate(chosen):
        strip.paste(image.resize((tile_w, tile_h)), (i * tile_w, 0))
    return strip, {"n": count, "tile_w": tile_w, "tile_h": tile_h, "times": [t for t, _ in chosen]}


def save_strip(cfg: Config, key: str, frames: list[tuple[float, Image.Image]]) -> dict:
    strip, meta = compose_strip(frames)
    target = thumb_path(cfg, f"strip|{key}")
    target.parent.mkdir(parents=True, exist_ok=True)
    strip.save(target, quality=70)
    return {"file": target.name, **meta}


def aggregate(frames: list[tuple[float, dict]], threshold: float = THRESHOLD) -> dict:
    """Per keyword: strongest frame, how many frames reached `threshold`, and when."""
    tags: dict[str, dict] = {}
    scene: dict[str, float] = {}
    for t, result in frames:
        for name, p in result["scene"].items():
            scene[name] = scene.get(name, 0.0) + p / len(frames)
        for s in result["suggestions"]:
            if s.prob < threshold:
                continue
            tag = tags.setdefault(s.keyword, {"keyword": s.keyword, "tier": s.tier, "best": 0.0, "best_t": t, "hits": 0, "times": []})
            tag["hits"] += 1
            if len(tag["times"]) < MAX_TIMES:
                tag["times"].append(t)
            if s.prob > tag["best"]:
                tag["best"], tag["best_t"] = round(s.prob, 4), t
    ranked = sorted(tags.values(), key=lambda x: (-x["hits"], -x["best"]))
    return {"scene": {k: round(v, 4) for k, v in scene.items()}, "tags": ranked}


def select_files(state: State, prefix: str | None, limit: int | None, redo: bool) -> list[str]:
    keys = []
    for key, entry in sorted(state.files.items()):
        if entry["kind"] != "video" or entry.get("missing"):
            continue
        if prefix and not key.startswith(prefix.rstrip("/") + "/"):
            continue
        if not redo and (entry.get("stages") or {}).get("video") == "done":
            continue
        keys.append(key)
    return keys[:limit] if limit else keys


def run_strips(cfg: Config, state: State, prefix: str | None = None, limit: int | None = None, redo: bool = False) -> int:
    """Build the hover strips for videos that are already indexed, without classifying again."""
    ffmpeg = find_tool("ffmpeg", cfg)
    if not ffmpeg:
        raise SystemExit("ffmpeg not found (see `doctor`).")
    keys = [
        k for k in select_files(state, prefix, None, redo=True)
        if (state.files[k].get("video") or {}) and (redo or not state.files[k]["video"].get("strip"))
    ]
    keys = keys[:limit] if limit else keys
    if not keys:
        print("No videos need a strip.")
        return 0
    for key in keys:
        entry = state.files[key]
        times = sample_times(entry["video"]["duration"], max_frames=STRIP_FRAMES)
        frames = []
        with tempfile.TemporaryDirectory(prefix="strip_") as tmp:
            for i, t in enumerate(times):
                out = Path(tmp) / f"{i:02d}.jpg"
                if extract_frame(cfg.path_of(key), t, ffmpeg, out):
                    with Image.open(out) as im:
                        frames.append((t, im.convert("RGB")))
        if not frames:
            print(f"  skip {key}: no frame could be extracted")
            continue
        entry["video"]["strip"] = save_strip(cfg, key, frames)
        state.save()
        print(f"{Path(key).name:34s} strip with {len(frames)} frames")
    print(f"{len(keys)} strips built")
    return 0


def run_video(
    cfg: Config,
    state: State,
    prefix: str | None = None,
    limit: int | None = None,
    interval: float = INTERVAL,
    max_frames: int = MAX_FRAMES,
    dry_run: bool = False,
    redo: bool = False,
) -> int:
    ffmpeg, ffprobe = find_tool("ffmpeg", cfg), find_tool("ffprobe", cfg)
    if not ffmpeg or not ffprobe:
        raise SystemExit("ffmpeg/ffprobe not found (see `doctor`).")
    keys = select_files(state, prefix, limit, redo)
    if not keys:
        print("No videos to process.")
        return 0

    vocabulary = load_vocabulary(cfg.config_dir / "vocabulary.csv")
    device = pick_device()
    print(f"Loading hybrid on {device} ({len(vocabulary)} vocabulary rows) ...")
    tagger = HybridTagger(device, vocabulary)

    started = time.perf_counter()
    for key in keys:
        path = cfg.path_of(key)
        duration = probe_duration(path, ffprobe)
        times = sample_times(duration, interval, max_frames)
        if not times:
            print(f"  skip {key}: cannot read the duration")
            state.files[key].setdefault("stages", {})["video"] = "error: unreadable"
            continue
        if dry_run:
            print(f"{Path(key).name:34s} {duration:7.1f}s -> {len(times)} frames")
            continue

        frames: list[tuple[float, Image.Image]] = []
        with tempfile.TemporaryDirectory(prefix="vid_") as tmp:
            def grab(item):
                i, t = item
                out = Path(tmp) / f"{i:04d}.jpg"
                return (t, out) if extract_frame(path, t, ffmpeg, out) else None

            with ThreadPoolExecutor(max_workers=4) as pool:
                for got in pool.map(grab, enumerate(times)):
                    if got:
                        with Image.open(got[1]) as im:
                            frames.append((got[0], im.convert("RGB")))
        if not frames:
            print(f"  skip {key}: no frame could be extracted")
            state.files[key].setdefault("stages", {})["video"] = "error: no frames"
            continue

        results = []
        for start in range(0, len(frames), BATCH_SIZE):
            chunk = frames[start : start + BATCH_SIZE]
            embeddings = tagger.encode_images([im for _, im in chunk])
            results += [(t, tagger.classify(emb, top=5)) for (t, _), emb in zip(chunk, embeddings)]

        summary = aggregate(results)
        # Thumbnail: the frame where the strongest tag peaks, else the middle of the video.
        pick = summary["tags"][0]["best_t"] if summary["tags"] else frames[len(frames) // 2][0]
        thumb_frame = min(frames, key=lambda f: abs(f[0] - pick))[1]
        thumb_frame.thumbnail((THUMB_SIDE, THUMB_SIDE))
        target = thumb_path(cfg, f"video|{key}")
        target.parent.mkdir(parents=True, exist_ok=True)
        thumb_frame.save(target, quality=85)

        entry = state.files[key]
        entry["video"] = {
            "duration": round(duration, 1), "interval": round(duration / len(times), 2),
            "frames": len(frames), "thumb": target.name, "strip": save_strip(cfg, key, frames), **summary,
        }
        entry.setdefault("stages", {})["video"] = "done"
        state.save()
        top = ", ".join(f"{t['keyword'].split('|')[-1]} x{t['hits']}" for t in summary["tags"][:4]) or "(nothing clear)"
        print(f"{Path(key).name:34s} {duration:7.1f}s {len(frames):3d} frames | {top}")

    print(timing_line(len(keys), time.perf_counter() - started, "videos") + (" (dry run, nothing saved)" if dry_run else ""))
    return 0
