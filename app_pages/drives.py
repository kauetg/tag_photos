"""Drives page: every disk you own, which ones are plugged in, and a button to index a new one.

Scanning runs as its own process (it can take hours), so the page stays usable and you can stop it.
"""
import subprocess
import sys
from dataclasses import replace
from pathlib import Path

import pandas as pd
import streamlit as st

from mediatagger.drives import (
    Drive, file_counts, list_drives, mounted_volumes, mounts_by_drive, refresh_from_mount, save_drive, unregistered_volumes,
)
from mediatagger.uicontext import context, reload_state

cfg, _, state = context()
db = cfg.state_path
PROJECT = Path(__file__).resolve().parent.parent

drives = list_drives(db)
volumes = mounted_volumes()
plugged = mounts_by_drive(db, volumes)
counts = file_counts(db)

st.title("Drives")
st.caption("Every disk with photos or videos. Search works on all of them; opening a file needs its disk plugged in.")


def gb(value):
    return None if value is None else f"{value:,.0f} GB"


def log_of(name):
    return cfg.data_dir / "reports" / f"scan_{name}.log"


if drives:
    rows = []
    for d in drives:
        mount = plugged.get(d.name)
        rows.append({
            "Drive": d.title, "Where": d.location, "Status": d.status,
            "Plugged in": f"yes, {mount.root.drive}" if mount else "no",
            "Files": counts.get(d.name, 0), "Last scan": d.last_scan or "never",
            "Size": gb(mount.total_gb if mount else d.size_gb), "Free": gb(mount.free_gb if mount else d.free_gb),
            "What is on it": d.contents,
        })
    st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch", alt="Table of drives")
else:
    st.info("No drives yet. Import your sheet with `python tagger.py drives import SHEET.tsv`, or add one below.", title="Empty")

# --- a disk that is plugged in but nobody knows -----------------------------------------------------

newcomers = unregistered_volumes(db, volumes)
unpaired = [d for d in drives if not d.serial]
if newcomers:
    with st.container(border=True):
        st.subheader("Plugged in, not yet known", anchor=False)
        st.caption("Pick the disk and say which drive it is. The app remembers its serial number, so it is recognised on any port.")
        mount = st.selectbox(
            "Disk", newcomers, key="new_mount",
            format_func=lambda v: f"{v.root.drive}  {v.volume_label or '(no label)'}  {v.total_gb:,.0f} GB, {v.free_gb:,.0f} GB free",
        )
        choice = st.selectbox("It is", [None, *[d.name for d in unpaired], "(a new drive)"], format_func=lambda n: n or "choose ...", key="new_which")
        name = st.text_input("Name of the new drive", key="new_name") if choice == "(a new drive)" else choice
        if st.button("Remember this disk", icon=":material/link:", disabled=not name):
            known = next((d for d in drives if d.name == name), None) or Drive(name.strip())
            refresh_from_mount(db, known, mount)
            st.rerun()

# --- scan ---------------------------------------------------------------------------------------------

st.subheader("Index a disk", anchor=False)
ready = [d for d in drives if d.name in plugged]
if not ready:
    st.caption("Plug a disk in and pair it above; it shows up here.")
else:
    target = st.selectbox("Disk", ready, format_func=lambda d: f"{d.title}  ({plugged[d.name].root.drive})", key="scan_target")
    job = st.session_state.get("scan_job")
    running = job is not None and job["process"].poll() is None


    def start_scan():
        log = log_of(target.name)
        log.parent.mkdir(parents=True, exist_ok=True)
        handle = log.open("w", encoding="utf-8")
        process = subprocess.Popen(
            [sys.executable, "-u", str(PROJECT / "tagger.py"), "drives", "scan", target.name],
            cwd=PROJECT, stdout=handle, stderr=subprocess.STDOUT,
        )
        st.session_state.scan_job = {"name": target.name, "process": process}


    def stop_scan():
        st.session_state.scan_job["process"].terminate()


    start, stop = st.columns(2)
    start.button("Scan this disk", icon=":material/play_arrow:", type="primary", width="stretch", on_click=start_scan, disabled=running,
                 help="Lists every photo and video, then makes the previews of the photos. Files are only read, never changed.")
    stop.button("Stop", icon=":material/stop:", width="stretch", on_click=stop_scan, disabled=not running)

    @st.fragment(run_every=3 if running else None)
    def progress():
        job = st.session_state.get("scan_job")
        if not job:
            return
        process, log = job["process"], log_of(job["name"])
        lines = log.read_text(encoding="utf-8", errors="replace").splitlines()[-12:] if log.exists() else []
        done = process.poll() is not None
        st.caption(f"{job['name']}: " + ("finished" if done and process.returncode == 0 else "stopped or failed" if done else "running ..."))
        st.code("\n".join(lines) or "starting ...", language=None)
        if done and not job.get("reloaded"):
            job["reloaded"] = True
            reload_state(cfg)
            st.rerun()

    progress()

# --- edit ---------------------------------------------------------------------------------------------

st.subheader("Edit a drive", anchor=False)
options = [*[d.name for d in drives], "(new)"]
picked = st.selectbox("Drive", options, key="edit_pick", label_visibility="collapsed")
current = next((d for d in drives if d.name == picked), Drive(""))
with st.form(f"edit:{picked}"):
    left, right = st.columns(2)
    name = left.text_input("Name", current.name, disabled=bool(current.name), help="Part of every file's key, so it cannot change once the drive exists.")
    label = right.text_input("What is written on the disk", current.label)
    location = left.text_input("Where it is kept", current.location)
    status = right.text_input("Status", current.status, help="Archive, In use, Future ...")
    contents = st.text_area("What is on it", current.contents)
    notes = st.text_area("Notes", current.notes)
    if st.form_submit_button("Save", icon=":material/save:", type="primary"):
        if not name.strip():
            st.error("Give the drive a name.")
        else:
            save_drive(db, replace(current, name=name.strip(), label=label, location=location, status=status, contents=contents, notes=notes))
            st.rerun()
