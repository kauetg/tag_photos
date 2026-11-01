"""Shared setup for the Streamlit pages: config, exiftool, the loaded state and cached thumbnails."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import streamlit as st

from .config import load_config
from .drives import mounts_by_drive
from .state import State
from .thumbs import cached_thumbnail, thumbnail
from .tools import find_tool
from .vocabulary import load_vocabulary


@st.cache_resource
def _load(media_root):
    cfg = load_config(media_root=media_root, need_media_root=False)
    return cfg, find_tool("exiftool", cfg)


def context():
    """(cfg, exiftool, state). The state is loaded once per browser session."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--media-root")
    args, _ = parser.parse_known_args(sys.argv[1:])
    cfg, exiftool = _load(args.media_root)
    cfg.mounts = {name: m.root for name, m in mounts_by_drive(cfg.state_path).items()}  # what is plugged in right now
    if "state" not in st.session_state:
        st.session_state.state = State.load(cfg.state_path)
    return cfg, exiftool, st.session_state.state


def reload_config() -> None:
    """Forget the cached config so edited CSVs (locations, date ranges) are read again on the next run."""
    _load.clear()


def reload_state(cfg) -> None:
    """Pick up what the command line wrote meanwhile (tag, video, triage ...)."""
    st.session_state.state = State.load(cfg.state_path)


@st.cache_data(max_entries=4)
def _vocabulary(path: str, mtime: int):
    return load_vocabulary(Path(path))


def vocabulary(cfg):
    """(entries, entries by keyword). Reloaded whenever the CSV changes, e.g. after editing it in the app."""
    path = cfg.config_dir / "vocabulary.csv"
    entries = _vocabulary(str(path), path.stat().st_mtime_ns)
    return entries, {e.keyword: e for e in entries}


def photo_thumb(cfg, exiftool, key, entry):
    """The cached preview of a photo; made now (the drive must be plugged in) when it is not there yet."""
    return str(cached_thumbnail(cfg, key, entry) or thumbnail(cfg, key, entry, exiftool))
