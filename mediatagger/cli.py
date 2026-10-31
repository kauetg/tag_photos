"""Command-line entry point: one subcommand per pipeline stage."""
from __future__ import annotations

import argparse
from pathlib import Path

from .config import load_config
from .device import onnx_providers, pick_device
from .scan import resolve_roots, scan, write_unmapped_report
from .state import State
from .tools import find_tool
from .xmp import is_embedded, read_back, sidecar_path, write_keywords

# Stages planned in PLAN.md that are not implemented yet: name -> phase.
PLANNED = {
    "faces": "phase 4",
    "name": "phase 4",
    "tag": "phase 3",
    "export": "phase 3",
    "write": "phase 2/3",
}


def build_parser() -> argparse.ArgumentParser:
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--dry-run", action="store_true", help="show what would happen, change nothing")
    common.add_argument("--limit", type=int, metavar="N", help="process only N items")
    common.add_argument("--folder", metavar="PATH", help="restrict to one folder (relative to media_root)")
    common.add_argument("--media-root", metavar="PATH", help="override media_root from the config")

    parser = argparse.ArgumentParser(prog="tagger", description="Media keyword tagger")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("scan", parents=[common], help="inventory the chosen folders")
    sub.add_parser("doctor", parents=[common], help="show device, tools and config")

    wt = sub.add_parser("write-test", help="append keywords to specific files, then read them back")
    wt.add_argument("files", nargs="+", metavar="FILE")
    wt.add_argument("-k", "--keyword", action="append", default=[], metavar="A|B|C",
                    help="hierarchical keyword (repeatable)")
    wt.add_argument("--country", default="")
    wt.add_argument("--city", default="")
    wt.add_argument("--sublocation", default="")
    wt.add_argument("--dry-run", action="store_true")
    wt.add_argument("--ignore-minor", action="store_true",
                    help="let exiftool write despite 'minor' warnings (e.g. DJI maker notes)")

    sh = sub.add_parser("show", help="print the keyword tags stored in files or their sidecars")
    sh.add_argument("files", nargs="+", metavar="FILE")
    for name, phase in PLANNED.items():
        sub.add_parser(name, parents=[common], help=f"not implemented yet ({phase})")
    return parser


def cmd_doctor(cfg) -> int:
    print(f"media_root : {cfg.media_root}  ({'ok' if cfg.media_root.exists() else 'NOT FOUND'})")
    print(f"state file : {cfg.state_path}")
    print(f"device     : {pick_device()}")
    print(f"onnx       : {', '.join(onnx_providers())}")
    for tool in ("exiftool", "ffmpeg", "ffprobe"):
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


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command in PLANNED:
        print(f"'{args.command}' is not implemented yet ({PLANNED[args.command]}).")
        return 1
    if args.command in ("write-test", "show"):
        cfg = load_config(need_media_root=False)
        return cmd_show(cfg, args) if args.command == "show" else cmd_write_test(cfg, args)
    cfg = load_config(media_root=args.media_root)
    if args.command == "doctor":
        return cmd_doctor(cfg)
    return cmd_scan(cfg, args)
