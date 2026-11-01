"""Command-line entry point: one subcommand per pipeline stage."""
from __future__ import annotations

import argparse
from pathlib import Path

from .config import load_config
from .device import onnx_providers, pick_device
from .premiere import DEFAULT_PAD, export_search
from .review import AUTO_THRESHOLD, THRESHOLD, apply_triage, export_csv
from .scan import relocate, resolve_roots, scan, write_unmapped_report
from .state import State
from .tools import find_tool
from .video import INTERVAL, MAX_FRAMES
from .xmp import is_embedded, read_back, sidecar_path, write_keywords

# Stages planned in PLAN.md that are not implemented yet: name -> phase.
PLANNED = {
    "faces": "phase 4",
    "name": "phase 4",
}


def build_parser() -> argparse.ArgumentParser:
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--dry-run", action="store_true", help="show what would happen, change nothing")
    common.add_argument("--limit", type=int, metavar="N", help="process only N items")
    common.add_argument("--folder", metavar="PATH", help="restrict to one folder (relative to media_root)")
    common.add_argument("--media-root", metavar="PATH", help="override media_root from the config")
    common.add_argument("--drive", metavar="NAME", help="which registered drive to work on (see `tagger drives`)")

    parser = argparse.ArgumentParser(prog="tagger", description="Media keyword tagger")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("scan", parents=[common], help="inventory the chosen folders")
    sub.add_parser("doctor", parents=[common], help="show device, tools and config")

    tg = sub.add_parser("tag", parents=[common], help="classify photos: scene gate + vocabulary suggestions")
    tg.add_argument("--model", choices=["hybrid", "bioclip", "clip"], default="hybrid")
    tg.add_argument("--top", type=int, default=3, help="suggestions shown per tier")
    tg.add_argument("--tiers", default="core,species", help="vocabulary tiers to use")
    tg.add_argument("--redo", action="store_true", help="re-tag files already tagged with this model")

    ex = sub.add_parser("export", parents=[common], help="write the suggestions to a CSV for review")
    ex.add_argument("--output", metavar="CSV", help="default: <data_dir>/review.csv")
    ex.add_argument("--threshold", type=float, default=THRESHOLD, help="min probability counted as suggested")

    dr = sub.add_parser("drives", help="list the registered drives, or manage them")
    dr_sub = dr.add_subparsers(dest="drives_command")
    di = dr_sub.add_parser("import", help="add the drives of a tab-separated sheet (HD, Descrição, Letra ...)")
    di.add_argument("table", metavar="TSV")
    da = dr_sub.add_parser("add", help="register one drive")
    da.add_argument("name")
    da.add_argument("--label", default="")
    da.add_argument("--location", default="")
    da.add_argument("--status", default="")
    da.add_argument("--contents", default="")
    ds = dr_sub.add_parser("import-state", help="move an old state.json into the index, under one drive")
    ds.add_argument("name", help="the drive those files are on")
    ds.add_argument("--state", metavar="JSON", help="default: <data_dir>/state.json")
    dc = dr_sub.add_parser("scan", help="scan a plugged-in drive, then make the previews of its photos")
    dc.add_argument("name")
    dp = dr_sub.add_parser("pair", help="remember the serial of a plugged-in drive (matches it by --letter)")
    dp.add_argument("name")
    dp.add_argument("--letter", required=True, metavar="X:")

    th = sub.add_parser("thumbs", parents=[common], help="make the cached previews of a drive's photos, so they show unplugged")

    sub.add_parser("review", parents=[common], help="open the Streamlit review page")

    vd = sub.add_parser("video", parents=[common], help="sample frames of each video and index what they show (read-only)")
    vd.add_argument("--interval", type=float, default=INTERVAL, help="seconds between frames")
    vd.add_argument("--max-frames", type=int, default=MAX_FRAMES, help="frame cap per video")
    vd.add_argument("--redo", action="store_true", help="reprocess videos already indexed")
    vd.add_argument("--strips-only", action="store_true",
                    help="only build the hover-preview strips of videos already indexed (no classification)")

    pr = sub.add_parser("premiere", parents=[common], help="export the videos matching a search as an XML for Premiere Pro")
    pr.add_argument("search", nargs="?", default="", help="words to look for, e.g. turtle (default: every indexed video)")
    pr.add_argument("--trim", action="store_true", help="cut each video around the moments instead of using the whole file")
    pr.add_argument("--pad", type=float, default=DEFAULT_PAD, help="with --trim: seconds kept around each moment")
    pr.add_argument("--output", metavar="XML", help="default: <data_dir>/premiere.xml")
    pr.add_argument("--bins", action=argparse.BooleanOptionalAction, default=True,
                    help="put the trimmed clips in one bin per category (default on)")

    sub.add_parser("relocate", parents=[common], help="re-apply locations.csv and date_ranges.csv to files already scanned")

    tr = sub.add_parser("triage", parents=[common], help="auto-approve clear photos, leave the uncertain for review")
    tr.add_argument("--auto", type=float, default=AUTO_THRESHOLD, help="core tags at least this likely are automatic")
    tr.add_argument("--uncertain", type=float, default=THRESHOLD, help="core tags from here up to --auto need review")

    wr = sub.add_parser("write", parents=[common], help="write approved keywords into photos (simulation unless --apply)")
    wr.add_argument("--apply", action="store_true", help="really write; without it nothing is changed")
    wr.add_argument("--redo", action="store_true", help="also check photos that look up to date")
    wr.add_argument("--embed", action="store_true",
                    help="embed in JPG/DNG instead of a sidecar (Lightroom only reads those embedded; the file is rewritten)")

    wt = sub.add_parser("write-test", help="append keywords to specific files, then read them back")
    wt.add_argument("files", nargs="+", metavar="FILE")
    wt.add_argument("-k", "--keyword", action="append", default=[], metavar="A|B|C",
                    help="hierarchical keyword (repeatable)")
    wt.add_argument("--country", default="")
    wt.add_argument("--city", default="")
    wt.add_argument("--sublocation", default="")
    wt.add_argument("--dry-run", action="store_true")
    wt.add_argument("--embed", action="store_true",
                    help="experiment: embed in video instead of a sidecar (use on copies only)")
    wt.add_argument("--ignore-minor", action="store_true",
                    help="let exiftool write despite 'minor' warnings (e.g. DJI maker notes)")

    sh = sub.add_parser("show", help="print the keyword tags stored in files or their sidecars")
    sh.add_argument("files", nargs="+", metavar="FILE")
    for name, phase in PLANNED.items():
        sub.add_parser(name, parents=[common], help=f"not implemented yet ({phase})")
    return parser


def _prefix(cfg, args) -> str | None:
    """Key prefix that limits a stage to the drive (and folder) being worked on."""
    if not cfg.drive:
        raise SystemExit("Which drive? Pass --drive NAME (see `tagger drives`).")
    if not args.folder:
        return cfg.drive
    folder = Path(args.folder)
    rel = folder.relative_to(cfg.media_root).as_posix() if folder.is_absolute() else folder.as_posix()
    return f"{cfg.drive}/{rel}"


def cmd_doctor(cfg) -> int:
    print(f"media_root : {cfg.media_root}  ({'ok' if cfg.media_root.exists() else 'NOT FOUND'})")
    print(f"index      : {cfg.state_path}")
    print(f"drive      : {cfg.drive or '(none: pass --drive)'}")
    for name, root in sorted(cfg.mounts.items()):
        print(f"  plugged  : {name} at {root}")
    print(f"device     : {pick_device()}")
    print(f"onnx       : {', '.join(onnx_providers())}")
    for tool in ("exiftool", "ffmpeg", "ffprobe", "dng_converter", "vlc"):
        print(f"{tool:<11}: {find_tool(tool, cfg) or 'NOT FOUND'}")
    print(f"folders    : {', '.join(cfg.folders) or '(none)'}")
    print(f"locations  : {len(cfg.locations)} rows")
    return 0


def cmd_scan(cfg, args) -> int:
    state = State.load(cfg.state_path)
    roots = resolve_roots(cfg, args.folder)
    mode = " (dry run)" if args.dry_run else ""
    print(f"Scanning {', '.join(str(r) for r in roots)}{mode}")
    report = scan(cfg, state, roots, dry_run=args.dry_run, limit=args.limit)
    if not args.dry_run and args.limit is None:
        from . import drives as d

        drive = d.get_drive(cfg.state_path, cfg.drive)
        mount = d.mounts_by_drive(cfg.state_path).get(cfg.drive)
        if drive and mount:
            d.refresh_from_mount(cfg.state_path, drive, mount)
        d.mark_scanned(cfg.state_path, cfg.drive)

    print(
        f"new {report.new}  changed {report.changed}  unchanged {report.unchanged}  "
        f"missing {report.missing}  errors {report.errors}"
    )
    if report.unmapped:
        print(f"{sum(report.unmapped.values())} files in folders without a location match:")
        for name, count in report.unmapped.most_common(10):
            print(f"  {count:6d}  {name}")
        if args.dry_run:
            print("  (report file not written in dry run)")
        else:
            print(f"  full list: {write_unmapped_report(cfg, report)}")
    return 0


def _exiftool_or_exit(cfg) -> str:
    exiftool = find_tool("exiftool", cfg)
    if not exiftool:
        raise SystemExit("exiftool not found (see `doctor`).")
    return exiftool


def cmd_show(cfg, args) -> int:
    exiftool = _exiftool_or_exit(cfg)
    for name in args.files:
        path = Path(name)
        tags = read_back(path, cfg, exiftool)
        mode = "embedded" if is_embedded(path, cfg) else f"sidecar {sidecar_path(path).name}"
        print(f"{path.name}  [{mode}]")
        print("  (no keywords)" if not tags else "\n".join(f"  {k} = {v}" for k, v in tags.items()))
    return 0


def cmd_write_test(cfg, args) -> int:
    exiftool = _exiftool_or_exit(cfg)
    if args.ignore_minor:
        cfg.ignore_minor_errors = True
    if args.embed:
        cfg.embedded_exts = [*cfg.embedded_exts, ".mp4", ".mov"]
    for name in args.files:
        path = Path(name)
        if not path.is_file():
            print(f"skip (not a file): {path}")
            continue
        result = write_keywords(
            path, args.keyword, cfg, exiftool,
            country=args.country, city=args.city, sublocation=args.sublocation,
            dry_run=args.dry_run,
        )
        verb = "would write" if args.dry_run else "wrote"
        print(f"{verb} {result['mode']:8s} {path.name} -> {Path(result['target']).name}")
        if not args.dry_run:
            for k, v in read_back(path, cfg, exiftool).items():
                print(f"    {k} = {v}")
    return 0


def cmd_tag(cfg, args) -> int:
    from .tag import run_tag  # heavy imports (torch) only when tagging

    exiftool = _exiftool_or_exit(cfg)
    state = State.load(cfg.state_path)
    prefix = _prefix(cfg, args)
    return run_tag(
        cfg, state, exiftool, args.model,
        prefix=prefix, limit=args.limit, dry_run=args.dry_run,
        top=args.top, tiers=set(args.tiers.split(",")), redo=args.redo,
    )


def cmd_export(cfg, args) -> int:
    output = Path(args.output) if args.output else cfg.data_dir / "review.csv"
    count = export_csv(State.load(cfg.state_path), output, args.threshold)
    print(f"{count} photos exported to {output}")
    return 0


def cmd_video(cfg, args) -> int:
    from .video import run_strips, run_video  # heavy imports (torch) only when needed

    prefix = _prefix(cfg, args)
    if args.strips_only:
        return run_strips(cfg, State.load(cfg.state_path), prefix=prefix, limit=args.limit, redo=args.redo)
    return run_video(
        cfg, State.load(cfg.state_path), prefix=prefix, limit=args.limit,
        interval=args.interval, max_frames=args.max_frames, dry_run=args.dry_run, redo=args.redo,
    )


def cmd_premiere(cfg, args) -> int:
    ffprobe = find_tool("ffprobe", cfg)
    if not ffprobe:
        raise SystemExit("ffprobe not found (see `doctor`).")
    try:
        xml, summary = export_search(
            State.load(cfg.state_path), cfg.path_of, ffprobe, args.search, args.pad, bins=args.bins,
            whole=not args.trim,
        )
    except ValueError:
        print("No indexed video matches that search.")
        return 1
    output = Path(args.output) if args.output else cfg.data_dir / "premiere.xml"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(xml, encoding="utf-8")
    bins = f", bins: {', '.join(summary['categories'])}" if args.bins else ""
    print(f"{summary['clips']} clips from {summary['videos']} videos -> {output}{bins}")
    for key in summary["skipped"]:
        print(f"  skipped (ffprobe could not read it): {key}")
    return 0


def cmd_relocate(cfg, args) -> int:
    state = State.load(cfg.state_path)
    counts = relocate(cfg, state)
    print(
        f"{counts['changed']} files got a different place, {counts['unchanged']} unchanged, "
        f"{counts['without_location']} still without a place" + (" (dry run, nothing saved)" if args.dry_run else "")
    )
    if not args.dry_run:
        state.save()
    return 0


def cmd_triage(cfg, args) -> int:
    from .tag import describe_triage

    state = State.load(cfg.state_path)
    counts = apply_triage(state, args.auto, args.uncertain)
    print(describe_triage(counts) + (" (dry run, nothing saved)" if args.dry_run else ""))
    if not args.dry_run:
        state.save()
    return 0


def cmd_review(cfg, args) -> int:
    import subprocess
    import sys

    app = Path(__file__).resolve().parent.parent / "streamlit_app.py"
    command = [sys.executable, "-m", "streamlit", "run", str(app)]
    return subprocess.call(command)


def cmd_drives(cfg, args) -> int:
    from . import drives as d
    from .state import import_state_json

    db = cfg.state_path
    if args.drives_command == "import":
        added, updated = d.import_table(db, Path(args.table))
        print(f"{added} drives added, {updated} updated")
    elif args.drives_command == "add":
        d.save_drive(db, d.Drive(args.name, args.label, location=args.location, status=args.status, contents=args.contents))
        print(f"drive '{args.name}' registered")
    elif args.drives_command == "import-state":
        if not d.get_drive(db, args.name):
            raise SystemExit(f"No drive named '{args.name}'. Register it first (`tagger drives add`).")
        source = Path(args.state) if args.state else cfg.data_dir / "state.json"
        print(f"{import_state_json(source, db, args.name)} files imported from {source} under '{args.name}'")
    elif args.drives_command == "pair":
        drive = d.get_drive(db, args.name)
        mount = next((v for v in d.mounted_volumes() if v.root.drive.upper() == args.letter.upper()[:2]), None)
        if not drive or not mount:
            raise SystemExit("Unknown drive name, or nothing is plugged in at that letter.")
        d.refresh_from_mount(db, drive, mount)
        print(f"'{drive.name}' is now {mount.serial} ({mount.volume_label or 'no label'}) at {mount.root}")
    elif args.drives_command == "scan":
        mount = cfg.mounts.get(args.name)
        if not d.get_drive(db, args.name) or not mount:
            raise SystemExit(f"'{args.name}' is not registered, or not plugged in (or its serial is not paired yet).")
        drive_cfg = load_config(media_root=str(mount), drive=args.name)
        scan_args = argparse.Namespace(dry_run=False, limit=None, folder=None, drive=args.name)
        cmd_scan(drive_cfg, scan_args)
        return cmd_thumbs(drive_cfg, scan_args)
    else:
        counts = d.file_counts(db)
        for drive in d.list_drives(db):
            where = cfg.mounts.get(drive.name)
            print(f"{drive.title:34s} {drive.location:12s} {drive.status:8s} {counts.get(drive.name, 0):7d} files  "
                  f"{'plugged at ' + str(where) if where else 'not plugged in'}")
    return 0


def cmd_thumbs(cfg, args) -> int:
    from .thumbs import make_missing

    exiftool = _exiftool_or_exit(cfg)
    made, failed = make_missing(cfg, State.load(cfg.state_path), exiftool, _prefix(cfg, args), args.limit)
    print(f"{made} previews made, {failed} failed")
    return 0


def cmd_write(cfg, args) -> int:
    from .write import run_write, with_embedding

    exiftool = _exiftool_or_exit(cfg)
    if args.embed:
        cfg = with_embedding(cfg, True)
    if args.apply:
        print(f"WRITING into {cfg.media_root}")
    prefix = _prefix(cfg, args)
    return run_write(
        cfg, State.load(cfg.state_path), exiftool,
        prefix=prefix, limit=args.limit, apply=args.apply, redo=args.redo,
    )


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command in PLANNED:
        print(f"'{args.command}' is not implemented yet ({PLANNED[args.command]}).")
        return 1
    if args.command in ("write-test", "show"):
        cfg = load_config(need_media_root=False)
        return cmd_show(cfg, args) if args.command == "show" else cmd_write_test(cfg, args)
    if args.command == "drives":
        return cmd_drives(load_config(need_media_root=False), args)
    media_root = args.media_root
    if args.drive and not media_root:
        from .drives import mounts_by_drive

        config = load_config(need_media_root=False)
        mounted = mounts_by_drive(config.state_path).get(args.drive)
        media_root = str(mounted.root) if mounted else None
    cfg = load_config(media_root=media_root, drive=args.drive, need_media_root=args.command in ("scan", "doctor", "thumbs"))
    if args.command == "doctor":
        return cmd_doctor(cfg)
    if args.command == "tag":
        return cmd_tag(cfg, args)
    if args.command == "premiere":
        return cmd_premiere(cfg, args)
    if args.command == "video":
        return cmd_video(cfg, args)
    if args.command == "thumbs":
        return cmd_thumbs(cfg, args)
    if args.command == "relocate":
        return cmd_relocate(cfg, args)
    if args.command == "triage":
        return cmd_triage(cfg, args)
    if args.command == "write":
        return cmd_write(cfg, args)
    if args.command == "export":
        return cmd_export(cfg, args)
    if args.command == "review":
        return cmd_review(cfg, args)
    return cmd_scan(cfg, args)
