"""Write page: put what you approved into the photos' XMP, after a preview of exactly what will change.

Adds what is missing and removes what this tool wrote before and you have since un-ticked. Keywords it never
wrote (yours from Lightroom) are left alone. RAW files get a sidecar .xmp; the originals are not touched.
"""
import pandas as pd
import streamlit as st

from mediatagger.config import DriveNotMounted
from mediatagger.library import dive_folder
from mediatagger.review import effective_scene
from mediatagger.uicontext import context
from mediatagger.vocabulary import SCENES
from mediatagger.write import apply_for, candidates, desired_for, describe, plan_for, with_embedding
from mediatagger.xmp import ExiftoolError

cfg, exiftool, state = context()

st.title("Write to files")
if not exiftool:
    st.error("exiftool was not found. Run `python tagger.py doctor` to see where the tools are expected.", title="Cannot write")
    st.stop()
if flash := st.session_state.pop("write_flash", None):
    getattr(st, flash[0])(flash[1], title=flash[2])

st.info(
    "**Do this in Lightroom first** (for photos that are already in its catalog): select them and use "
    "*Metadata → Save Metadata to File*, so none of your edits are lost. After writing here, select the same "
    "photos and use *Metadata → Read Metadata from File*. Videos are never written.",
    title="Order with Lightroom",
)

waiting = candidates(state)
if not waiting:
    st.success("Every approved photo is already up to date. Approve or change tags in the review page and they will show up here.", title="Nothing to write")
    st.stop()

default_mode = "embedded" if cfg.embedded_exts else "sidecar"
mode_col, scene_col, folder_col = st.columns(3)
mode = mode_col.segmented_control(
    "JPG and DNG", ["sidecar", "embedded"], default=default_mode, key="write_mode",
    format_func=lambda m: "Sidecar (safest)" if m == "sidecar" else "Inside the file",
    help="Lightroom keeps JPG and DNG metadata inside the file and may not read a sidecar next to them. "
         "Sidecar leaves the file alone; inside the file rewrites it and keeps a copy named *_original. RAW is always a sidecar.",
) or default_mode
scene = scene_col.segmented_control(
    "Scene", SCENES, default=None, key="write_scene", format_func=str.capitalize, help="Only photos of this scene. Click again to clear.",
)
folders = sorted({dive_folder(k) for k in waiting})
folder = folder_col.selectbox("Dive folder", [None, *folders], format_func=lambda f: f or "(all)", key="write_folder")

scoped = [k for k in candidates(state, prefix=folder, scene=scene) if cfg.is_mounted(k)]  # only drives that are plugged in
never = sum(state.files[k].get("written") is None for k in scoped)
takeback = sum(not desired_for(state.files[k])[0] for k in scoped if state.files[k].get("written") is not None)
st.markdown(
    f"**{len(scoped)}** of {len(waiting)} photos need their files updated: "
    f"**{never}** never written, **{len(scoped) - never - takeback}** changed since writing, "
    f"**{takeback}** to take our tags back out (skipped or unticked everything)."
)
if mode == "embedded":
    st.warning("JPG and DNG files will be rewritten with the tags inside them; a copy named *_original is kept next to each.", title="Inside the file")

signature = (mode, scene, folder)
stored = st.session_state.get("write_plans")
plans = stored["plans"] if stored and stored["signature"] == signature else None
run_cfg = with_embedding(cfg, mode == "embedded")

if st.button("Check what will change", icon=":material/fact_check:", disabled=not scoped):
    plans, failed = {}, {}
    progress = st.progress(0.0, text="Reading the current files ...")
    for i, key in enumerate(scoped, start=1):
        try:
            plans[key] = plan_for(run_cfg, state, exiftool, key)
        except (ExiftoolError, DriveNotMounted) as exc:
            failed[key] = str(exc)
        progress.progress(i / len(scoped), text=f"Checked {i} of {len(scoped)}")
    progress.empty()
    st.session_state.write_plans = {"signature": signature, "plans": plans, "failed": failed}
    stored = st.session_state.write_plans

if not plans:
    st.stop()

changing = {k: p for k, p in plans.items() if not p["nothing_to_do"]}
already = len(plans) - len(changing)
added = sum(len(p["add"]) for p in changing.values())
removed = sum(len(p["remove"]) for p in changing.values())
places = sum(bool(p["location_set"] or p["location_clear"]) for p in changing.values())
m1, m2, m3, m4 = st.columns(4)
m1.metric("Files to change", len(changing))
m2.metric("Tags added", added)
m3.metric("Tags removed", removed)
m4.metric("Places changed", places)
if already:
    st.caption(f"{already} more already match their files; writing only records that.")
for key, error in stored["failed"].items():
    st.warning(f"{key}: {error}", title="Could not check")

if changing:
    st.dataframe(
        pd.DataFrame(
            [[k.rsplit("/", 1)[-1], dive_folder(k), "inside the file" if p["mode"] == "embedded" else "sidecar .xmp", describe(p)]
             for k, p in changing.items()],
            columns=["Photo", "Dive folder", "Where", "What changes"],
        ),
        hide_index=True, height=min(420, 40 + 35 * len(changing)), alt="Preview of the changes to each photo's file",
    )

# A new key after every write, so the confirmation starts unticked again for the next batch.
confirm_key = f"write_saved_in_lr:{st.session_state.setdefault('write_round', 0)}"
saved = st.checkbox(
    "I saved the metadata in Lightroom first (not needed for photos that are not in its catalog)", key=confirm_key,
)
if st.button(f"Write {len(plans)} files", type="primary", icon=":material/edit_note:", disabled=not saved):
    done, problems = 0, []
    progress = st.progress(0.0, text="Writing ...")
    for i, key in enumerate(plans, start=1):
        try:
            result = apply_for(run_cfg, state, exiftool, key)
            if not result.get("verified", True):
                problems.append(f"{key}: {'; '.join(result['problems'])}")
            else:
                done += 1
        except (ExiftoolError, DriveNotMounted) as exc:
            state.files[key].setdefault("stages", {})["write"] = f"error: {exc}"
            problems.append(f"{key}: {exc}")
        progress.progress(i / len(plans), text=f"Wrote {i} of {len(plans)}")
    state.save()
    st.session_state.pop("write_plans", None)
    st.session_state.write_round += 1
    if problems:
        st.session_state.write_flash = ("warning", f"{done} written and checked, {len(problems)} had problems:\n\n" + "\n".join(f"- {p}" for p in problems), "Some files need attention")
    else:
        st.session_state.write_flash = (
            "success",
            f"{done} files written and read back to check. In Lightroom, select them and use Metadata → Read Metadata from File.",
            "Done",
        )
    st.rerun()
