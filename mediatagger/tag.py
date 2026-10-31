"""tag: classify photos (scene gate + vocabulary suggestions) and store them in state.json."""
from __future__ import annotations

from pathlib import Path

from .classify import HybridTagger, Tagger
from .config import Config
from .device import pick_device
from .imaging import ImageLoadError, load_image
from .review import apply_triage
from .state import State
from .vocabulary import load_vocabulary

IMAGE_KINDS = {"photo", "raw"}
BATCH_SIZE = 8


def select_files(state: State, prefix: str | None, model_key: str, limit: int | None, redo: bool) -> list[str]:
    keys = []
    for key, entry in sorted(state.files.items()):
        if entry["kind"] not in IMAGE_KINDS or entry.get("missing"):
            continue
        if prefix and not key.startswith(prefix.rstrip("/") + "/"):
            continue
        if not redo and (entry.get("tags") or {}).get("model") == model_key:
            continue
        keys.append(key)
    return keys[:limit] if limit else keys


def describe(result: dict, top: int) -> str:
    scene, best = max(result["scene"].items(), key=lambda kv: kv[1])
    parts = [f"{scene} {best:.2f}"]
    for s in result["suggestions"]:
        label = s.keyword.split("|")[-1]
        parts.append(f"{label} {s.prob:.2f}{'*' if s.tier == 'species' else ''}")
    return " | ".join(parts)


def describe_triage(counts: dict[str, int]) -> str:
    return (
        f"triage: {counts['auto']} approved automatically, {counts['review']} need review, "
        f"{counts['sample']} spot checks, {counts['kept']} already decided by you"
    )


def run_tag(
    cfg: Config,
    state: State,
    exiftool: str,
    model_key: str,
    prefix: str | None = None,
    limit: int | None = None,
    dry_run: bool = False,
    top: int = 3,
    tiers: set[str] | None = None,
    redo: bool = False,
) -> int:
    keys = select_files(state, prefix, model_key, limit, redo)
    if not keys:
        print("Nothing to tag.")
        return 0

    vocabulary = load_vocabulary(cfg.config_dir / "vocabulary.csv", tiers)
    device = pick_device()
    print(f"Loading {model_key} on {device} ({len(vocabulary)} vocabulary rows) ...")
    tagger = HybridTagger(device, vocabulary) if model_key == "hybrid" else Tagger(model_key, device, vocabulary)

    done = 0
    for start in range(0, len(keys), BATCH_SIZE):
        batch_keys, images = [], []
        for key in keys[start : start + BATCH_SIZE]:
            try:
                images.append(load_image(cfg.media_root / key, cfg, exiftool))
                batch_keys.append(key)
            except ImageLoadError as exc:
                print(f"  skip {key}: {exc}")
                state.files[key].setdefault("stages", {})["tag"] = f"error: {exc}"
        if not images:
            continue

        embeddings = tagger.encode_images(images)
        for key, emb in zip(batch_keys, embeddings):
            result = tagger.classify(emb, top=top)
            print(f"{Path(key).name:34s} {describe(result, top)}")
            if dry_run:
                continue
            entry = state.files[key]
            entry["tags"] = {
                "model": model_key,
                "scene": {k: round(v, 4) for k, v in result["scene"].items()},
                "suggestions": [s.as_dict() for s in result["suggestions"]],
            }
            entry.setdefault("stages", {})["tag"] = "done"
            done += 1
        if not dry_run and done and done % cfg.save_every < BATCH_SIZE:
            state.save()

    if not dry_run:
        print(describe_triage(apply_triage(state)))
        state.save()
    print(f"{len(keys)} files processed" + (" (dry run, nothing saved)" if dry_run else ""))
    return 0
