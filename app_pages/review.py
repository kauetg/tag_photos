"""Streamlit review page: look at each photo the model was unsure about, fix its place and tags, save.

Run from streamlit_app.py. Decisions go to state.json under "review"; nothing is written to the
photos here (that is `python tagger.py write`).
"""
import streamlit as st

from mediatagger.review import (
    APPROVED, AUTO, PENDING, SKIPPED, THRESHOLD, apply_triage, decide, detected_scene, effective_location,
    effective_scene, is_sample, known_locations, label, place_label, split_by_confidence, status, tagged_keys, triage,
)
from mediatagger.uicontext import context, photo_thumb, vocabulary
from mediatagger.vocabulary import SCENES, add_manual_tag, ancestors, pretty

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

def in_scope(k):
    """Photos inside the scene and folder filters (read from the widgets' last values, as they are drawn below)."""
    folder_now, scene_now = st.session_state.get("folder", "(all)"), st.session_state.get("scene_filter")
    return (folder_now == "(all)" or k.startswith(folder_now + "/")) and (
        not scene_now or effective_scene(state.files[k]) == scene_now
    )


scoped = [k for k in all_keys if in_scope(k)]
with st.sidebar:
    st.title("Review tags")
    counts = {s: sum(status(state.files[k]) == s for k in scoped) for s in (PENDING, APPROVED, SKIPPED, AUTO)}
    st.progress(
        1 - counts[PENDING] / len(scoped) if scoped else 1.0,
        text=f"{len(scoped) - counts[PENDING]} of {len(scoped)} decided",
    )
    shown = st.segmented_control(
        "Show",
        [PENDING, APPROVED, SKIPPED, AUTO, "all"],
        default=PENDING,
        format_func=lambda s: f"{s} ({counts[s]})" if s in counts else "all",
        key="shown",
        on_change=lambda: st.session_state.update(pos=0),
    )
    st.segmented_control(
        "Scene", SCENES, default=None, key="scene_filter", format_func=str.capitalize,
        on_change=lambda: st.session_state.update(pos=0),
        help="Only photos of this scene: what the model saw, or what you picked. Click again to clear.",
    )
    folders = sorted({k.rsplit("/", 1)[0] for k in all_keys})
    folder = st.selectbox("Folder", ["(all)", *folders], key="folder", on_change=lambda: st.session_state.update(pos=0))

keys = [k for k in scoped if shown in (None, "all") or status(state.files[k]) == shown]
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

FIELDS = ("sure", "unsure", "extra", "place", "scene")
sure_key, unsure_key, extra_key, place_key, scene_key = (f"{name}:{key}" for name in FIELDS)
drafts = st.session_state.setdefault("drafts", {})  # edits to photos you moved away from without deciding
if st.session_state.get("ready_for") != key:  # you just arrived at this photo: its widgets start from scratch
    st.session_state.ready_for = key
    if key in drafts:
        for name in FIELDS:
            st.session_state[f"{name}:{key}"] = drafts[key][name]
    else:  # first visit: start from the model's suggestions
        st.session_state[sure_key] = [k for k in sure if previous is None or k in previous]
        st.session_state[unsure_key] = [k for k in unsure if (k in previous if previous is not None else probs[k] >= THRESHOLD)]
        st.session_state[extra_key] = [k for k in (previous or []) if k not in probs]
        st.session_state[place_key] = current_label
        st.session_state[scene_key] = effective_scene(entry)
new_tag =st.session_state.pop("new_tag", None)
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
    scene = st.session_state.get(f"scene:{key}")
    decide(
        entry, list(dict.fromkeys(picked)), approved, {**place, "source": "review"} if changed else None,
        scene if scene and scene != detected_scene(entry) else None,
    )
    drafts.pop(key, None)
    state.save()
    if shown not in (PENDING, None):
        st.session_state.pos += 1


def go(step, key=key):
    """Move through the photos without deciding; what you changed on this one is kept as a draft."""
    drafts[key] = {name: st.session_state.get(f"{name}:{key}") for name in FIELDS}
    st.session_state.pos += step


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
        st.image(photo_thumb(cfg, exiftool, key, entry), alt=f"Preview of {key.rsplit('/', 1)[-1]}", width="stretch")
    except Exception as exc:  # unreadable file: still let the user move on
        st.warning(str(exc), title="No preview")

with right:
    scene = max(tags["scene"], key=tags["scene"].get)
    prev_col, count_col, next_col = st.columns([1, 2, 1], vertical_alignment="center")
    prev_col.button("Previous photo", icon=":material/arrow_back:", width="stretch", disabled=st.session_state.pos == 0,
                    on_click=go, args=(-1,), key="nav_prev", type="secondary")
    count_col.markdown(f"**{st.session_state.pos + 1} of {len(keys)}**", text_alignment="center")
    next_col.button("Next photo", icon=":material/arrow_forward:", icon_position="right", width="stretch",
                    disabled=st.session_state.pos >= len(keys) - 1, on_click=go, args=(1,), key="nav_next", type="secondary")
    st.caption(status(entry))
    st.subheader(key.rsplit("/", 1)[-1], anchor=False)
    st.caption(f"{key.rsplit('/', 1)[0]}  \n{scene} {tags['scene'][scene]:.0%}")
    if status(entry) == PENDING and triage(entry)[0] == "auto" and is_sample(key):
        st.info("The model was confident here; this is a spot check of the automatic approvals.", title="Spot check")

    with st.container(border=True):
        st.markdown("**Where**")
        st.selectbox("Location", list(places), key=place_key, label_visibility="collapsed")

    with st.container(border=True):
        st.markdown("**What is in it**")
        st.segmented_control(
            "Scene of this photo", SCENES, key=scene_key, format_func=str.capitalize,
            help="The model's guess. It decides which of your own tags are offered below, and the scene filters.",
        )
        scene_now = st.session_state.get(scene_key) or detected_scene(entry)
        if sure:
            st.caption("The model is sure about these. Untick any that are wrong.")
            st.pills("Sure", sure, selection_mode="multi", key=sure_key, label_visibility="collapsed",
                     format_func=lambda k: f"{label(k)} {probs[k]:.0%}")
        if unsure:
            st.caption("Needs your eye. Ticked ones are 50% or more; a species percentage already includes its group.")
            st.pills("Unsure", unsure, selection_mode="multi", key=unsure_key, label_visibility="collapsed",
                     format_func=lambda k: f"{label(k)} {probs[k]:.0%}")
        taken = set(probs)
        # Tags that make sense in this scene, plus any you already picked (a picked tag must stay selectable).
        offered = {k for k, e in by_keyword.items() if k not in taken and (scene_now in e.scenes or not scene_now)}
        offered |= set(st.session_state.get(extra_key, []))
        st.multiselect(
            "Add tags of your own",
            sorted(offered, key=lambda k: pretty(k, by_keyword).casefold()),
            key=extra_key, format_func=lambda k: pretty(k, by_keyword),
            placeholder="Type to search: cots, bleaching, turtle ...",
        )
        if st.button("Create a new tag", icon=":material/add:", type="tertiary"):
            new_tag_dialog(key)

    st.button("Approve", type="primary", icon=":material/check:", width="stretch", on_click=finish, args=(True,))
    st.button("Skip", icon=":material/skip_next:", width="stretch", on_click=finish, args=(False,))
