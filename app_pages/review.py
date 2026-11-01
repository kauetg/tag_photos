"""Streamlit review page: look at each photo the model was unsure about, fix its place and tags, save.

Run from streamlit_app.py. Decisions go to state.json under "review"; nothing is written to the
photos here (that is `python tagger.py write`).
"""
import streamlit as st

from mediatagger.review import (
    APPROVED, AUTO, PENDING, SKIPPED, THRESHOLD, apply_triage, decide, effective_location, is_sample, known_locations,
    label, place_label, split_by_confidence, status, tagged_keys, triage,
)
from mediatagger.uicontext import context, photo_thumb, vocabulary
from mediatagger.vocabulary import add_manual_tag, ancestors, pretty

cfg, exiftool, state = context()
vocab, by_keyword = vocabulary(cfg)
st.session_state.setdefault("pos", 0)

if not st.session_state.get("triaged"):
    # Photos nobody has looked at yet: clear ones are approved automatically, the rest wait here.
    apply_triage(state, only_new=True)
    state.save()
    st.session_state.triaged = True

all_keys = tagged_keys(state)
if not all_keys:
    st.info("No tagged photos yet. Run `python tagger.py tag` first.", title="Nothing to review")
    st.stop()

with st.sidebar:
    st.title("Review tags")
    counts = {s: sum(status(state.files[k]) == s for k in all_keys) for s in (PENDING, APPROVED, SKIPPED, AUTO)}
    st.progress(1 - counts[PENDING] / len(all_keys), text=f"{len(all_keys) - counts[PENDING]} of {len(all_keys)} decided")
    shown = st.segmented_control(
        "Show",
        [PENDING, APPROVED, SKIPPED, AUTO, "all"],
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
probs = {s["keyword"]: s["prob"] for s in tags["suggestions"]}
sure, unsure = split_by_confidence(entry)
previous = (entry.get("review") or {}).get("keywords")

# Places you can pick: everything in locations.csv / date_ranges.csv, plus this photo's own.
original = entry.get("location") or {}
places = {place_label(p): p for p in known_locations(cfg)}
current = effective_location(entry)
current_label = place_label(current) if current else "(no location)"
if current_label not in places:
    places = {current_label: current, **places}

sure_key, unsure_key, extra_key, place_key = (f"{name}:{key}" for name in ("sure", "unsure", "extra", "place"))
if sure_key not in st.session_state:  # first visit to this photo: start from the model's suggestions
    st.session_state[sure_key] = [k for k in sure if previous is None or k in previous]
    st.session_state[unsure_key] = [k for k in unsure if (k in previous if previous is not None else probs[k] >= THRESHOLD)]
    st.session_state[extra_key] = [k for k in (previous or []) if k not in probs]
    st.session_state[place_key] = current_label
new_tag = st.session_state.pop("new_tag", None)
if new_tag and new_tag[0] == key:  # a tag just created in the dialog goes straight onto this photo
    st.session_state[extra_key] = [*st.session_state[extra_key], new_tag[1]]


def same_place(a: dict, b: dict) -> bool:
    return (a.get("keyword"), a.get("city"), a.get("sublocation")) == (b.get("keyword"), b.get("city"), b.get("sublocation"))


def finish(approved, key=key, entry=entry, places=places, original=original):
    picked = [
        *st.session_state.get(f"sure:{key}", []),
        *st.session_state.get(f"unsure:{key}", []),
        *st.session_state.get(f"extra:{key}", []),
    ]
    place = places.get(st.session_state.get(f"place:{key}"))
    changed = bool(place) and not same_place(place, original)
    decide(entry, list(dict.fromkeys(picked)), approved, {**place, "source": "review"} if changed else None)
    state.save()
    if shown not in (PENDING, None):
        st.session_state.pos += 1


@st.dialog("Create a tag")
def new_tag_dialog(photo_key):
    st.caption("It is added to the vocabulary as a tag you apply by hand; the model never uses it.")
    parent = st.selectbox("Where does it belong?", ancestors(vocab), format_func=lambda p: p.replace("|", " › "))
    name = st.text_input("Name, in English", placeholder="Coral bleaching")
    aliases = st.text_input("Other words that should find it (optional)", placeholder="bleaching event, white coral")
    if st.button("Create tag", type="primary", icon=":material/add:"):
        try:
            created = add_manual_tag(cfg.config_dir / "vocabulary.csv", parent, name, aliases)
        except ValueError as exc:
            st.error(str(exc))
        else:
            st.session_state.new_tag = (photo_key, created)
            st.rerun()


left, right = st.columns([3, 2], gap="large")
with left:
    try:
        st.image(photo_thumb(str(cfg.media_root / key), cfg, exiftool), alt=f"Preview of {key.rsplit('/', 1)[-1]}", width="stretch")
    except Exception as exc:  # unreadable file: still let the user move on
        st.warning(str(exc), title="No preview")

with right:
    scene = max(tags["scene"], key=tags["scene"].get)
    st.caption(f"{st.session_state.pos + 1} of {len(keys)} in this view · {status(entry)}")
    st.subheader(key.rsplit("/", 1)[-1], anchor=False)
    st.caption(f"{key.rsplit('/', 1)[0]}  \n{scene} {tags['scene'][scene]:.0%}")
    if status(entry) == PENDING and triage(entry)[0] == "auto" and is_sample(key):
        st.info("The model was confident here; this is a spot check of the automatic approvals.", title="Spot check")

    with st.container(border=True):
        st.markdown("**Where**")
        st.selectbox("Location", list(places), key=place_key, label_visibility="collapsed")

    with st.container(border=True):
        st.markdown("**What is in it**")
        if sure:
            st.caption("The model is sure about these. Untick any that are wrong.")
            st.pills("Sure", sure, selection_mode="multi", key=sure_key, label_visibility="collapsed",
                     format_func=lambda k: f"{label(k)} {probs[k]:.0%}")
        if unsure:
            st.caption("Needs your eye. Ticked ones are 50% or more; a species percentage already includes its group.")
            st.pills("Unsure", unsure, selection_mode="multi", key=unsure_key, label_visibility="collapsed",
                     format_func=lambda k: f"{label(k)} {probs[k]:.0%}")
        taken = set(probs)
        st.multiselect(
            "Add tags of your own",
            sorted((k for k in by_keyword if k not in taken), key=lambda k: pretty(k, by_keyword).casefold()),
            key=extra_key, format_func=lambda k: pretty(k, by_keyword),
            placeholder="Type to search: cots, bleaching, turtle ...",
        )
        if st.button("Create a new tag", icon=":material/add:", type="tertiary"):
            new_tag_dialog(key)

    st.button("Approve", type="primary", icon=":material/check:", width="stretch", on_click=finish, args=(True,))
    skip, back = st.columns(2)
    skip.button("Skip", icon=":material/skip_next:", width="stretch", on_click=finish, args=(False,))
    back.button(
        "Previous", icon=":material/arrow_back:", width="stretch", disabled=st.session_state.pos == 0,
        on_click=lambda: st.session_state.update(pos=st.session_state.pos - 1),
    )
