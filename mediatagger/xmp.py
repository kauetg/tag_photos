"""Write keywords with exiftool: embedded for the extensions in the config, sidecar .xmp for the rest.

`write_keywords` only appends. `sync_keywords` also removes, but only what this tool wrote before.
"""
from __future__ import annotations

import json
import os
import subprocess
import tempfile
import time
from pathlib import Path

from .config import Config

# Empty XMP packet used to start a sidecar; exiftool then fills it in.
EMPTY_XMP = (
    '<?xpacket begin="﻿" id="W5M0MpCehiHzreSzNTczkc9d"?>\n'
    '<x:xmpmeta xmlns:x="adobe:ns:meta/">'
    '<rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#">'
    '<rdf:Description rdf:about=""/></rdf:RDF></x:xmpmeta>\n'
    '<?xpacket end="w"?>\n'
)

READ_TAGS = [
    "-XMP-dc:Subject",
    "-XMP-lr:HierarchicalSubject",
    "-IPTC:Keywords",
    "-XMP-photoshop:Country",
    "-XMP-photoshop:City",
    "-XMP-iptcCore:Location",
]


# Formats that can carry IPTC; video can only carry XMP.
IPTC_EXTS = {".jpg", ".jpeg", ".dng", ".tif", ".tiff"}


class ExiftoolError(RuntimeError):
    pass


def flat_keywords(hierarchical: list[str]) -> list[str]:
    """Plain keywords for universal readers: every level except the root category.

    'Location|Philippines|Siquijor' -> ['Philippines', 'Siquijor'].
    """
    flat: list[str] = []
    for path in hierarchical:
        parts = path.split("|")
        for part in parts[1:] if len(parts) > 1 else parts:
            if part and part not in flat:
                flat.append(part)
    return flat


def is_embedded(path: Path, cfg: Config) -> bool:
    return path.suffix.lower() in cfg.embedded_exts


def sidecar_path(path: Path) -> Path:
    return path.with_suffix(".xmp")


def run_exiftool(exiftool: str, args: list[str], binary: bool = False):
    """Run exiftool with arguments passed through a UTF-8 argfile (safe for accents).

    Returns stdout as text, or as bytes when `binary` is true (for -b extractions).
    """
    with tempfile.NamedTemporaryFile(
        "w", suffix=".args", delete=False, encoding="utf-8", newline="\n"
    ) as f:
        f.write("\n".join(args) + "\n")
        argfile = f.name
    try:
        text_opts = {} if binary else {"text": True, "encoding": "utf-8"}
        proc = subprocess.run(
            [exiftool, "-charset", "utf8", "-charset", "filename=utf8", "-@", argfile],
            capture_output=True,
            **text_opts,
        )
    finally:
        os.unlink(argfile)
    stderr = proc.stderr.decode("utf-8", "replace") if binary else proc.stderr
    if proc.returncode != 0 or "Error:" in stderr:
        raise ExiftoolError(stderr.strip())
    return proc.stdout


def write_keywords(
    path: Path,
    hierarchical: list[str],
    cfg: Config,
    exiftool: str,
    country: str = "",
    city: str = "",
    sublocation: str = "",
    dry_run: bool = False,
) -> dict:
    """Append keywords to `path` (embedded) or to its sidecar. Returns what was done."""
    embedded = is_embedded(path, cfg)
    target = path if embedded else sidecar_path(path)
    flat = flat_keywords(hierarchical)
    location = {
        "XMP-photoshop:Country": country,
        "XMP-photoshop:City": city,
        "XMP-iptcCore:Location": sublocation,
    }
    location = {tag: value for tag, value in location.items() if value}

    result = {
        "file": str(path),
        "mode": "embedded" if embedded else "sidecar",
        "target": str(target),
        "hierarchical": hierarchical,
        "flat": flat,
        "location": location,
        "time": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "dry_run": dry_run,
    }
    if dry_run:
        return result

    # Sidecars are our own tiny files, so no backup is needed; embedded writes
    # keep exiftool's "_original" backup unless the config says otherwise.
    overwrite = ["-overwrite_original"] if (not embedded or cfg.overwrite_original) else []

    if not embedded and not target.exists():
        target.write_text(EMPTY_XMP, encoding="utf-8")

    # exiftool's += can duplicate list values, so only add what is not there yet.
    existing = read_back(path, cfg, exiftool)
    have_subject = _as_list(existing.get("XMP-dc:Subject"))
    have_hier = _as_list(existing.get("XMP-lr:HierarchicalSubject"))
    have_iptc = _as_list(existing.get("IPTC:Keywords"))

    if cfg.ignore_minor_errors:
        overwrite = ["-m", *overwrite]  # same flags for both passes below

    use_iptc = embedded and path.suffix.lower() in IPTC_EXTS

    args = list(overwrite)
    args += [f"-XMP-dc:Subject+={k}" for k in flat if k not in have_subject]
    args += [f"-XMP-lr:HierarchicalSubject+={h}" for h in hierarchical if h not in have_hier]
    if use_iptc:
        args.append("-IPTC:CodedCharacterSet=UTF8")
        args += [f"-IPTC:Keywords+={k}" for k in flat if k not in have_iptc]
    if len(args) > len(overwrite) + (1 if use_iptc else 0):  # skip when nothing to add
        args.append(str(target))
        run_exiftool(exiftool, args)

    if location:
        # -wm cg: create missing tags only, never edit a value that already exists.
        loc_args = list(overwrite) + ["-wm", "cg"]
        loc_args += [f"-{tag}={value}" for tag, value in location.items()]
        loc_args.append(str(target))
        run_exiftool(exiftool, loc_args)

    log_write(cfg, result)
    return result


LOCATION_TAGS = {
    "country": "XMP-photoshop:Country",
    "city": "XMP-photoshop:City",
    "sublocation": "XMP-iptcCore:Location",
}


def sync_keywords(
    path: Path,
    desired: list[str],
    previous: list[str],
    cfg: Config,
    exiftool: str,
    location: dict | None = None,
    previous_location: dict | None = None,
    dry_run: bool = False,
) -> dict:
    """Make the file's keywords match `desired`, touching only what this tool wrote before.

    `previous` is what we wrote last time: those keywords are removed if no longer desired. Keywords we
    never wrote (yours from Lightroom, say) are never removed. A flat keyword is only removed when no other
    hierarchical keyword in the file still uses it. Location fields are created when empty, and changed or
    cleared only while they still hold the value we wrote (`previous_location`; None = unknown, create only).
    Returns what was (or, in a dry run, would be) done; with a real write it also reads the file back.
    """
    embedded = is_embedded(path, cfg)
    target = path if embedded else sidecar_path(path)
    use_iptc = embedded and path.suffix.lower() in IPTC_EXTS

    existing = read_back(path, cfg, exiftool)
    have_subject = _as_list(existing.get("XMP-dc:Subject"))
    have_hier = _as_list(existing.get("XMP-lr:HierarchicalSubject"))
    have_iptc = _as_list(existing.get("IPTC:Keywords"))

    add_hier = [h for h in desired if h not in have_hier]
    remove_hier = [h for h in previous if h not in desired and h in have_hier]
    still_used = set(flat_keywords([h for h in have_hier if h not in remove_hier] + add_hier))
    flat_add = [k for k in flat_keywords(desired) if k not in have_subject]
    flat_remove = [k for k in flat_keywords(remove_hier) if k in have_subject and k not in still_used]
    iptc_add = [k for k in flat_keywords(desired) if k not in have_iptc] if use_iptc else []
    iptc_remove = [k for k in flat_keywords(remove_hier) if k in have_iptc and k not in still_used] if use_iptc else []

    loc_set: dict[str, str] = {}
    loc_clear: list[str] = []
    for name, tag in LOCATION_TAGS.items():
        want = (location or {}).get(name, "")
        have = str(existing.get(tag) or "")
        written = None if previous_location is None else previous_location.get(name, "")
        if want:
            if not have or (have != want and written is not None and have == written):
                loc_set[tag] = want
        elif have and written and have == written:
            loc_clear.append(tag)

    result = {
        "file": str(path),
        "mode": "embedded" if embedded else "sidecar",
        "target": str(target),
        "add": add_hier,
        "remove": remove_hier,
        "location_set": loc_set,
        "location_clear": loc_clear,
        "time": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "dry_run": dry_run,
    }
    result["nothing_to_do"] = not (add_hier or remove_hier or flat_add or flat_remove or iptc_add or iptc_remove or loc_set or loc_clear)
    if dry_run or result["nothing_to_do"]:
        return result

    overwrite = ["-overwrite_original"] if (not embedded or cfg.overwrite_original) else []
    if cfg.ignore_minor_errors:
        overwrite = ["-m", *overwrite]
    if not embedded and not target.exists():
        target.write_text(EMPTY_XMP, encoding="utf-8")

    args = list(overwrite)
    args += [f"-XMP-dc:Subject-={k}" for k in flat_remove]
    args += [f"-XMP-lr:HierarchicalSubject-={h}" for h in remove_hier]
    args += [f"-XMP-dc:Subject+={k}" for k in flat_add]
    args += [f"-XMP-lr:HierarchicalSubject+={h}" for h in add_hier]
    if iptc_add or iptc_remove:
        args.append("-IPTC:CodedCharacterSet=UTF8")
        args += [f"-IPTC:Keywords-={k}" for k in iptc_remove]
        args += [f"-IPTC:Keywords+={k}" for k in iptc_add]
    args += [f"-{tag}={value}" for tag, value in loc_set.items()]
    args += [f"-{tag}=" for tag in loc_clear]
    args.append(str(target))
    run_exiftool(exiftool, args)

    after = read_back(path, cfg, exiftool)
    after_hier = _as_list(after.get("XMP-lr:HierarchicalSubject"))
    problems = [f"missing after write: {h}" for h in add_hier if h not in after_hier]
    problems += [f"still there after write: {h}" for h in remove_hier if h in after_hier]
    problems += [f"{tag} is not {value!r} after write" for tag, value in loc_set.items() if str(after.get(tag) or "") != value]
    result["verified"] = not problems
    result["problems"] = problems
    log_write(cfg, result)
    return result


def _as_list(value) -> list[str]:
    """exiftool -j returns a scalar for one value and a list for several."""
    if value is None:
        return []
    return [str(v) for v in value] if isinstance(value, list) else [str(value)]


def read_back(path: Path, cfg: Config, exiftool: str) -> dict:
    """Read the keyword tags from the file (embedded) or its sidecar."""
    target = path if is_embedded(path, cfg) else sidecar_path(path)
    if not target.exists():
        return {}
    out = run_exiftool(exiftool, ["-j", "-G1", *READ_TAGS, str(target)])
    data = json.loads(out)[0]
    data.pop("SourceFile", None)
    return data


def log_write(cfg: Config, entry: dict) -> None:
    cfg.data_dir.mkdir(parents=True, exist_ok=True)
    with (cfg.data_dir / "write_log.jsonl").open("a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")
