"""Shared setup for the Streamlit pages: config, exiftool, the loaded state and cached thumbnails."""
from __future__ import annotations

import argparse
import sys

import streamlit as st

from .config import load_config
from .state import State
from .thumbs import thumbnail
from .tools import find_tool


@st.cache_resource
def _load(media_root):
    cfg = load_config(media_root=media_root)
    return cfg, find_tool("exiftool", cfg)


def context():
    """(cfg, exiftool, state). The state is loaded once per browser session."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--media-root")
    args, _ = parser.parse_known_args(sys.argv[1:])
    cfg, exiftool = _load(args.media_root)
    if "state" not in st.session_state:
        st.session_state.state = State.load(cfg.state_path)
    return cfg, exiftool, st.session_state.state


def reload_state(cfg) -> None:
    """Pick up what the command line wrote meanwhile (tag, video, triage ...)."""
    st.session_state.state = State.load(cfg.state_path)


@st.cache_data(show_spinner="Preparing thumbnail ...", max_entries=500)
def photo_thumb(path, _cfg, _exiftool):
    return str(thumbnail(path, _cfg, _exiftool))
