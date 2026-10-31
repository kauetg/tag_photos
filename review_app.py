"""Streamlit review page: look at each tagged photo, tick the tags to keep, save the decision.

Start it with `python tagger.py review` (or `streamlit run review_app.py -- --media-root <path>`).
Decisions go to state.json under "review"; nothing is written to the photos here.
"""
import argparse
import sys

import streamlit as st

from mediatagger.config import load_config
from mediatagger.review import APPROVED, PENDING, SKIPPED, decide, label, status, suggested, tagged_keys
from mediatagger.state import State
from mediatagger.thumbs import thumbnail
from mediatagger.tools import find_tool

st.set_page_config(page_title="Review tags", page_icon=":material/sailing:", layout="wide")

parser = argparse.ArgumentParser()
parser.add_argument("--media-root")
args, _ = parser.parse_known_args(sys.argv[1:])


@st.cache_resource
def get_cfg(media_root):
    cfg = load_config(media_root=media_root)
    return cfg, find_tool("exiftool", cfg)


@st.cache_data(show_spinner="Preparing thumbnail ...", max_entries=500)
def get_thumb(path, _cfg, _exiftool):
    return str(thumbnail(path, _cfg, _exiftool))


cfg, exiftool = get_cfg(args.media_root)

if "state" not in st.session_state:
    st.session_state.state = State.load(cfg.state_path)
    st.session_state.pos = 0
state = st.session_state.state

all_keys = tagged_keys(state)
if not all_keys:
    st.info("No tagged photos yet. Run `python tagger.py tag` first.", title="Nothing to review")
    st.stop()

with st.sidebar:
    st.title("Review tags")
    counts = {s: sum(status(state.files[k]) == s for k in all_keys) for s in (PENDING, APPROVED, SKIPPED)}
    st.progress(1 - counts[PENDING] / len(all_keys), text=f"{len(all_keys) - counts[PENDING]} of {len(all_keys)} reviewed")
    shown = st.segmented_control(
        "Show",
        [PENDING, APPROVED, SKIPPED, "all"],
        default=PENDING,
        format_func=lambda s: f"{s} ({counts[s]})" if s in counts else "all",
        key="shown",
        on_change=lambda: st.session_state.update(pos=0),
    )
    folders = sorted({k.rsplit("/", 1)[0] for k in all_keys})
    folder = st.selectbox("Folder", ["(all)", *folders], key="folder", on_change=lambda: st.session_state.update(pos=0))

keys = [
    k for k in all_keys
    if (shown in (None, "all") or status(state.files[k]) == shown)
    and (folder == "(all)" or k.startswith(folder + "/"))
]
if not keys:
    st.success("Nothing left in this view.", title="All done")
    st.stop()

st.session_state.pos = max(0, min(st.session_state.pos, len(keys) - 1))
key = keys[st.session_state.pos]
entry = state.files[key]
tags = entry["tags"]
options = [s["keyword"] for s in tags["suggestions"]]
probs = {s["keyword"]: s["prob"] for s in tags["suggestions"]}
previous = (entry.get("review") or {}).get("keywords")
default = [k for k in (previous if previous is not None else suggested(entry)) if k in options]


def finish(approved):
    chosen = st.session_state.get(f"pick:{key}", [])
    decide(entry, chosen, approved)
    state.save()
    if shown not in (PENDING, None):
        st.session_state.pos += 1


left, right = st.columns([3, 2], gap="large")
with left:
    try:
        st.image(get_thumb(str(cfg.media_root / key), cfg, exiftool), alt=f"Preview of {key.rsplit('/', 1)[-1]}", width="stretch")
    except Exception as exc:  # unreadable file: still let the user move on
        st.warning(str(exc), title="No preview")

with right:
    st.caption(f"{st.session_state.pos + 1} of {len(keys)} in this view")
    st.subheader(key.rsplit("/", 1)[-1])
    location = entry.get("location") or {}
    place = ", ".join(p for p in (location.get("city"), location.get("country")) if p)
    scene = max(tags["scene"], key=tags["scene"].get)
    st.caption(f"{key.rsplit('/', 1)[0]}  \n{place or 'no location'} · {scene} {tags['scene'][scene]:.0%} · {status(entry)}")

    st.pills(
        "Tags to write",
        options,
        selection_mode="multi",
        default=default,
        format_func=lambda k: f"{label(k)} {probs[k]:.0%}",
        key=f"pick:{key}",
    )
    st.caption("Ticked by default: 50% or more. A species percentage already includes its group's confidence.")

    st.button("Approve", type="primary", icon=":material/check:", width="stretch", on_click=finish, args=(True,))
    st.button("Skip", icon=":material/skip_next:", width="stretch", on_click=finish, args=(False,))
    st.button(
        "Previous",
        icon=":material/arrow_back:",
        width="stretch",
        disabled=st.session_state.pos == 0,
        on_click=lambda: st.session_state.update(pos=st.session_state.pos - 1),
    )
