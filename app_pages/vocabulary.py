"""Vocabulary page: edit what the model looks for and the tags you apply by hand.

A tree of tags on the left, the selected tag's form on the right. Saves config/vocabulary.csv
(the previous version is kept as vocabulary.csv.bak).
"""
from dataclasses import replace

import streamlit as st

from mediatagger.uicontext import context, vocabulary
from mediatagger.vocabulary import SCENES, TIERS, VocabEntry, ancestors, save_vocabulary, validate

cfg, _, _ = context()
entries, by_keyword = vocabulary(cfg)
path = cfg.config_dir / "vocabulary.csv"

TIER_ICON = {"core": ":material/folder_open:", "species": ":material/pets:", "manual": ":material/edit:"}
TIER_HELP = {
    "core": "A group the model looks for; species can sit right below it.",
    "species": "A specific species, found by BioCLIP from the scientific name. Needs a core group right above it.",
    "manual": "Only ever applied by you in the review page; the model never looks for it.",
}
TOP = "(top level)"


def save(new_entries: list[VocabEntry], done: str, select: str | None) -> bool:
    """Validate and write; on a problem nothing is saved and the reasons are shown."""
    problems = validate(new_entries)
    if problems:
        st.error("\n".join(f"- {p}" for p in problems), title="Not saved")
        return False
    save_vocabulary(path, new_entries)
    st.session_state.vocab_sel = select
    st.toast(done, icon=":material/check:")
    return True


def parent_options(exclude: str = "") -> list[str]:
    """Where a tag can sit: any group path, and any core tag. Never inside `exclude` itself."""
    paths = set(ancestors(entries)) | {e.keyword for e in entries if e.tier == "core"}
    return sorted(p for p in paths if not exclude or not (p == exclude or p.startswith(exclude + "|")))


def pretty(keyword: str) -> str:
    return keyword.replace("|", " › ")


def new_tag_form(key: str, parent: str) -> None:
    """Create a tag under `parent`; it gets a plain prompt and every scene, to be refined in the form on the right."""
    options = [TOP, *parent_options()]
    with st.form(key, border=False, clear_on_submit=True):
        where = st.selectbox("Inside", options, index=options.index(parent) if parent in options else 0, format_func=pretty)
        name = st.text_input("Name", placeholder="Whale shark")
        tier = st.segmented_control("Kind", TIERS, default="manual", format_func=str.title, help="\n\n".join(TIER_HELP.values()))
        if st.form_submit_button("Create", type="primary"):
            name = name.strip()
            if not name or "|" in name:
                st.error("Give it a name, without the | character.")
                return
            keyword = name if where == TOP else f"{where}|{name}"
            fresh = VocabEntry(keyword, name, "", frozenset(SCENES), tier or "manual")
            if save([*entries, fresh], f"{pretty(keyword)} created.", keyword):
                st.rerun()


st.title("Vocabulary")
st.caption(
    "Every tag the app knows. **Core** and **species** are what the model looks for; **manual** tags are only ever "
    "applied by you in the review page. Aliases are other words that find the tag when you type."
)

# --- filters ----------------------------------------------------------------------------------------------------
f_search, f_scene, f_tier, f_new = st.columns([3, 3, 3, 1.4], vertical_alignment="bottom")
search = f_search.text_input("Filter", placeholder="turtle, cots, manual ...", icon=":material/search:")
scenes = f_scene.pills("Scene", SCENES, selection_mode="multi", format_func=str.title)
tiers = f_tier.pills("Kind", TIERS, selection_mode="multi", format_func=str.title)
with f_new.popover("New tag", icon=":material/add:", width="stretch"):
    new_tag_form("new_tag", TOP)

needle = search.strip().casefold()
shown = [
    e for e in sorted(entries, key=lambda e: [p.casefold() for p in e.keyword.split("|")])
    if (not scenes or e.scenes & set(scenes)) and (not tiers or e.tier in tiers)
    and (not needle or needle in " ".join([e.keyword, e.prompt, e.scientific_name, *e.aliases]).casefold())
]
selected = st.session_state.get("vocab_sel")
if selected not in by_keyword:
    selected = shown[0].keyword if shown else None
filtering = bool(needle or scenes or tiers)

left, right = st.columns([2, 3], gap="large")

# --- the tree ---------------------------------------------------------------------------------------------------
with left:
    st.caption(f"{len(shown)} of {len(entries)} tags")
    st.html("<style>.st-key-vocab_tree button,.st-key-vocab_tree button>div{justify-content:flex-start;text-align:left}</style>")
    with st.container(height=620, border=False, key="vocab_tree"):
        by_root: dict[str, list[VocabEntry]] = {}
        for e in shown:
            by_root.setdefault(e.keyword.split("|")[0], []).append(e)
        for root, rows in by_root.items():
            with st.expander(f"{root}  ·  {len(rows)}", expanded=filtering or (selected or "").split("|")[0] == root):
                seen_groups = set()
                for e in rows:
                    parts = e.keyword.split("|")
                    for i in range(2, len(parts)):  # a heading for each group that has no tag of its own
                        group = "|".join(parts[:i])
                        if group not in by_keyword and group not in seen_groups:
                            seen_groups.add(group)
                            pad = st.columns([i - 1, 30], gap="xxsmall")[1]
                            pad.caption(f"**{parts[i - 1]}**")
                    depth = len(parts) - 1
                    cell = st.columns([depth, 30], gap="xxsmall")[1] if depth else st
                    if cell.button(
                        parts[-1], key=f"pick:{e.keyword}", icon=TIER_ICON[e.tier], width="stretch",
                        type="primary" if e.keyword == selected else "tertiary",
                    ):
                        st.session_state.vocab_sel = e.keyword
                        st.rerun()
        if not shown:
            st.info("No tag matches that.")

# --- the selected tag -------------------------------------------------------------------------------------------
with right:
    if selected is None:
        st.info("Pick a tag on the left, or create one.")
        st.stop()
    entry = by_keyword[selected]
    parent, _, name = entry.keyword.rpartition("|")
    family = [e for e in entries if e.keyword == entry.keyword or e.keyword.startswith(entry.keyword + "|")]
    st.subheader(name, anchor=False)
    st.caption(pretty(parent) if parent else "Top level")

    parents = [TOP, *parent_options(entry.keyword)]
    with st.form(f"tag:{entry.keyword}", border=False):
        new_name = st.text_input("Name", name)
        new_parent = st.selectbox("Inside", parents, index=parents.index(parent) if parent in parents else 0, format_func=pretty)
        new_tier = st.segmented_control("Kind", TIERS, default=entry.tier, format_func=str.title, help=TIER_HELP[entry.tier])
        new_scenes = st.multiselect("Scenes", SCENES, default=sorted(entry.scenes, key=SCENES.index), format_func=str.title)
        new_prompt = st.text_area(
            "What the model looks for", entry.prompt, height=80,
            help="A plain description, e.g. “a green sea turtle”. Not needed for manual tags.",
        )
        new_sci = st.text_input("Scientific name", entry.scientific_name, help="BioCLIP uses this instead of the description when it is filled in.")
        new_aliases = st.multiselect(
            "Aliases", list(entry.aliases), default=list(entry.aliases), accept_new_options=True,
            help="Other words that find this tag when you type.",
        )
        if st.form_submit_button("Save tag", type="primary", icon=":material/save:"):
            new_name = new_name.strip()
            if not new_name or "|" in new_name:
                st.error("Give it a name, without the | character.")
            else:
                new_keyword = new_name if new_parent == TOP else f"{new_parent}|{new_name}"
                changed = replace(
                    entry, keyword=new_keyword, prompt=new_prompt.strip(), scientific_name=new_sci.strip(),
                    scenes=frozenset(new_scenes), tier=new_tier or entry.tier, aliases=tuple(a.strip() for a in new_aliases if a.strip()),
                )
                rows = []
                for e in entries:
                    if e is entry:
                        rows.append(changed)
                    elif e.keyword.startswith(entry.keyword + "|"):  # a rename or move carries the whole subtree along
                        rows.append(replace(e, keyword=new_keyword + e.keyword[len(entry.keyword):]))
                    else:
                        rows.append(e)
                if save(rows, f"{pretty(new_keyword)} saved.", new_keyword):
                    st.rerun()

    add_col, del_col = st.columns(2)
    with add_col.popover("Add a tag inside", icon=":material/subdirectory_arrow_right:", width="stretch"):
        new_tag_form(f"child:{entry.keyword}", entry.keyword)
    with del_col.popover("Delete", icon=":material/delete:", width="stretch"):
        st.markdown(f"Delete **{name}**" + (f" and the {len(family) - 1} tags inside it?" if len(family) > 1 else "?"))
        if st.button("Yes, delete", key=f"del:{entry.keyword}", type="primary"):
            if save([e for e in entries if e not in family], f"{pretty(entry.keyword)} deleted.", None):
                st.rerun()

st.caption("New model tags only affect photos tagged from now on; run `tag --redo` to apply them to old ones. Manual tags work right away.")
