"""Library page: search photos and videos by tag, place, date and folder, then open them.

Read-only: it only reads state.json and the thumbnails; the media files are never changed.
"""
import streamlit as st

from mediatagger.library import (
    dive_folder, filter_options, format_time, indexed, matching_tags, open_file, open_in_vlc, reveal_in_folder,
    search, videos_near,
)
from mediatagger.scrub import scrub
from mediatagger.premiere import DEFAULT_PAD, export_selection
from mediatagger.review import effective_location, label
from mediatagger.tools import find_tool
from mediatagger.uicontext import context, photo_thumb

PAGE_SIZE = 20
MAX_MOMENTS = 6

cfg, exiftool, state = context()
options = filter_options(state)
vlc = find_tool("vlc", cfg)

if not any(indexed(e) for e in state.files.values()):
    st.info("Nothing is indexed yet. Run `python tagger.py tag` for photos and `python tagger.py video` for videos.", title="Empty library")
    st.stop()


def first_page():
    st.session_state.lib_page = 1


st.title("Library")
text = st.text_input(
    "Search", placeholder="turtle, komodo, coral, manta ...", icon=":material/search:", key="lib_text", on_change=first_page,
)

with st.sidebar:
    kinds = st.pills(
        "Show", ["video", "photo"], selection_mode="multi", default=["video", "photo"],
        format_func=lambda k: k.capitalize() + "s", key="lib_kinds", on_change=first_page,
    )
    country = st.selectbox("Country", [None, *options["country"]], format_func=lambda c: c or "(all)", key="lib_country", on_change=first_page)
    folder = st.selectbox("Dive folder", [None, *options["folder"]], format_func=lambda f: f or "(all)", key="lib_folder", on_change=first_page)
    dates = st.date_input("Dates", value=(), format="YYYY-MM-DD", key="lib_dates", on_change=first_page)

date_from = date_to = None
if len(dates) == 2:
    date_from, date_to = (d.strftime("%Y%m%d") for d in dates)

keys = search(
    state, text, tuple(kinds or ()), country=country, folder=folder, date_from=date_from, date_to=date_to,
)

video_keys = [k for k in keys if state.files[k]["kind"] == "video"]
# The export list outlives searches and pages: video key -> the search text it was added with.
export_list = {k: t for k, t in st.session_state.setdefault("export_list", {}).items() if k in state.files}
st.session_state.export_list = export_list
st.session_state.setdefault("sel_version", 0)


def toggle_export(key, widget_key):
    if st.session_state[widget_key]:
        export_list[key] = st.session_state.get("lib_text", "")
    else:
        export_list.pop(key, None)


def add_all_results():
    for k in video_keys:
        export_list[k] = st.session_state.get("lib_text", "")
    st.session_state.sel_version += 1  # new checkbox keys, so they show the new list


def clear_export_list():
    export_list.clear()
    st.session_state.sel_version += 1


with st.sidebar:
    st.subheader("Export for Premiere", anchor=False)
    clips = st.segmented_control(
        "Clips", ["whole", "trimmed"], default="whole", key="lib_clips",
        format_func=lambda c: "Whole files" if c == "whole" else "Trimmed around moments",
    )
    pad = st.number_input("Seconds around each moment", 1.0, 60.0, DEFAULT_PAD, step=1.0, key="lib_pad", disabled=clips != "trimmed")
    bins = st.checkbox("Organize in bins by category", value=True, key="lib_bins")
    st.caption("Each match becomes a marker on the timeline, so you can cut there." if clips == "whole" else "Each match is kept with its surroundings; overlapping ones are merged.")
    ffprobe = find_tool("ffprobe", cfg)

    selection = dict(export_list)

    def selected_xml():
        xml, _ = export_selection(
            state, cfg.media_root, ffprobe, selection, "Selected videos", pad, bins, clips != "trimmed",
        )
        return xml

    st.markdown(f"**{len(selection)}** videos in the export list")
    st.download_button(
        "Download XML of the list", selected_xml, file_name="premiere_export.xml", mime="application/xml", key="dl_selected",
        icon=":material/movie_edit:", type="primary", width="stretch", disabled=not selection or not ffprobe,
        help="File > Import in Premiere Pro. The videos are only referenced, never changed.",
    )
    add_col, clear_col = st.columns(2)
    add_col.button(f"Add all {len(video_keys)}", icon=":material/playlist_add:", width="stretch", disabled=not video_keys, on_click=add_all_results)
    clear_col.button("Clear list", icon=":material/delete_sweep:", width="stretch", disabled=not selection, on_click=clear_export_list)
    if selection:
        with st.expander("What is on the list"):
            for k in sorted(selection, key=lambda k: (state.files[k].get("folder_date") or "", k)):
                st.caption(f"{k.rsplit('/', 1)[-1]} · {dive_folder(k)}")
pages = max(1, -(-len(keys) // PAGE_SIZE))
st.session_state.setdefault("lib_page", 1)
st.session_state.lib_page = min(st.session_state.lib_page, pages)

head, pager = st.columns([3, 1], vertical_alignment="bottom")
head.caption(f"{len(keys)} results")
page = pager.number_input("Page", 1, pages, key="lib_page", disabled=pages == 1)

if not keys:
    st.info("Nothing matches. Try fewer words or clear a filter.", title="No results")
    st.stop()


def moments(entry, search_text):
    """One line per matching tag: its name and when it shows up."""
    lines = []
    for tag in matching_tags(entry, search_text)[:MAX_MOMENTS]:
        times = ", ".join(format_time(t) for t in tag["times"][:8])
        lines.append(f"**{label(tag['keyword'])}** · {tag['hits']} of {entry['video']['frames']} frames · {times}")
    return lines


def open_buttons(key, scope):
    """`scope` keeps widget keys unique when a video shows up twice on the page."""
    path = cfg.media_root / key
    if state.files[key]["kind"] == "video":
        widget_key = f"sel:{st.session_state.sel_version}:{scope}:{key}"
        st.checkbox(
            "Add to export list", value=key in export_list, key=widget_key,
            on_change=toggle_export, args=(key, widget_key),
        )
    left, right = st.columns(2)
    left.button("Open file", icon=":material/play_circle:", key=f"open:{scope}:{key}", width="stretch", on_click=open_file, args=(path,))
    right.button("Show in folder", icon=":material/folder_open:", key=f"reveal:{scope}:{key}", width="stretch", on_click=reveal_in_folder, args=(path,))


for key in keys[(page - 1) * PAGE_SIZE : page * PAGE_SIZE]:
    entry = state.files[key]
    name = key.rsplit("/", 1)[-1]
    location = effective_location(entry)
    place =", ".join(p for p in (location.get("city"), location.get("country")) if p) or "no location"
    with st.container(border=True):
        image, info = st.columns([1, 3], gap="medium")
        with image:
            try:
                strip = (entry.get("video") or {}).get("strip")
                if strip and (cfg.data_dir / "thumbs" / strip["file"]).exists():
                    hits = matching_tags(entry, text) if text.strip() else []
                    marks = sorted(t for tag in hits for t in tag["times"])
                    best = hits[0]["best_t"] if hits else entry["video"]["duration"] / 2
                    scrub(
                        cfg.data_dir / "thumbs" / strip["file"], strip, entry["video"]["duration"], marks, best,
                        key=f"scrub:{key}", on_pick=lambda seconds, key=key: open_in_vlc(cfg.media_root / key, seconds, vlc),
                    )
                    st.caption("Move the mouse to browse, click to play in VLC.")
                else:
                    if entry["kind"] == "video":
                        shot = cfg.data_dir / "thumbs" / entry["video"]["thumb"]
                    else:
                        shot = photo_thumb(str(cfg.media_root / key), cfg, exiftool)
                    st.image(str(shot), alt=f"Preview of {name}", width="stretch")
            except Exception:  # an unreadable file should not break the whole page
                st.caption("no preview")
        with info:
            kind = "Video" if entry["kind"] == "video" else "Photo"
            st.subheader(name, anchor=False)
            st.caption(f"{kind} · {dive_folder(key)} · {place}")
            if entry["kind"] == "video":
                st.caption(f"{format_time(entry['video']['duration'])} long, one frame every {entry['video']['interval']:.0f} s")
                for line in moments(entry, text):
                    st.markdown(line)
            else:
                shown = entry["review"]["keywords"] if entry.get("review") else [
                    s["keyword"] for s in entry["tags"]["suggestions"] if s["prob"] >= 0.5
                ]
                st.markdown(" · ".join(f"**{label(k)}**" for k in shown) or "_no tags_")
            open_buttons(key, "result")

            if entry["kind"] != "video":
                near = videos_near(state, key)
                if near:
                    with st.expander(f"{len(near)} videos from the same dive folder"):
                        for vkey in near:
                            st.markdown(f"**{vkey.rsplit('/', 1)[-1]}**")
                            for line in moments(state.files[vkey], "")[:3]:
                                st.caption(line)
                            open_buttons(vkey, f"near:{key}")
