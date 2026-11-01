"""Library page: search photos and videos by tag, place, date and folder, then open them.

Read-only: it only reads the index (data/index.db) and the thumbnails; the media files are never changed.
"""
import streamlit as st

from mediatagger.library import (
    dive_name, drive_of, filter_options, format_time, indexed, matching_tags, open_file, open_in_vlc, reveal_in_folder,
    search, videos_near,
)
from mediatagger.scrub import scrub
from mediatagger.thumbs import cover
from mediatagger.premiere import DEFAULT_PAD, export_selection
from mediatagger.review import effective_location, label
from mediatagger.tools import find_tool
from mediatagger.uicontext import context, photo_thumb
from mediatagger.vocabulary import SCENES

PAGE_SIZE = 20  # cards per page in the list view
GRID_COLUMNS = 4
GRID_PAGE_SIZE = GRID_COLUMNS * 6  # cards per page in the grid view
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
    scene = st.segmented_control(
        "Scene", SCENES, default=None, key="lib_scene", on_change=first_page,
        format_func=str.capitalize, help="What the model saw, or what you picked in the review. Click again to clear.",
    )
    country = st.selectbox("Country", [None, *options["country"]], format_func=lambda c: c or "(all)", key="lib_country", on_change=first_page)
    drive = st.selectbox("Drive", [None, *options["drive"]], format_func=lambda d: d or "(all)", key="lib_drive", on_change=first_page)
    connected = st.toggle(
        "Only connected drives", key="lib_connected", on_change=first_page,
        help="Hide what lives on disks that are not plugged in right now.",
    )
    folder = st.selectbox("Dive folder", [None, *options["folder"]], format_func=lambda f: f or "(all)", key="lib_folder", on_change=first_page)
    dates = st.date_input("Dates", value=(), format="YYYY-MM-DD", key="lib_dates", on_change=first_page)

date_from = date_to = None
if len(dates) == 2:
    date_from, date_to = (d.strftime("%Y%m%d") for d in dates)

keys = search(
    state, text, tuple(kinds or ()), country=country, scene=scene, folder=folder, drive=drive, drives={d for d in options["drive"] if cfg.mount_of(d)} if connected else None, date_from=date_from, date_to=date_to,
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
            state, cfg.path_of, ffprobe, selection, "Selected videos", pad, bins, clips != "trimmed",
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

# What the page shows: the search results, or exactly what is on its way to Premiere (oldest dive first).
mode = st.session_state.get("lib_mode") or "results"
export_keys = sorted(export_list, key=lambda k: (state.files[k].get("folder_date") or "", k))
shown_keys = export_keys if mode == "export" else keys
st.segmented_control(
    "Showing", ["results", "export"], default="results", key="lib_mode", on_change=first_page, label_visibility="collapsed",
    format_func=lambda m: f"Search results ({len(keys)})" if m == "results" else f":material/movie_edit: Export list ({len(export_list)})",
)


def query_of(key):
    """The words a card highlights: what you typed, or the search a listed video was added with."""
    return export_list.get(key, "") if mode == "export" else text


view = st.session_state.get("lib_view") or "grid"
page_size = GRID_PAGE_SIZE if view == "grid" else PAGE_SIZE
pages = max(1, -(-len(shown_keys) // page_size))
st.session_state.setdefault("lib_page", 1)
st.session_state.lib_page = min(st.session_state.lib_page, pages)

head, switch, pager = st.columns([2, 2, 1], vertical_alignment="bottom")
if mode == "export":
    total = sum(state.files[k]["video"]["duration"] for k in export_keys)
    head.caption(f"{len(export_keys)} videos, {format_time(total)} in total. Each one goes to Premiere whole or trimmed, as set in the sidebar.")
else:
    head.caption(f"{len(keys)} results")
switch.segmented_control(
    "View", ["grid", "list"], default="grid", key="lib_view", on_change=first_page, label_visibility="collapsed",
    format_func=lambda v: ":material/grid_view: Grid" if v == "grid" else ":material/view_list: List",
)
page = pager.number_input("Page", 1, pages, key="lib_page", disabled=pages == 1)

if not shown_keys:
    if mode == "export":
        st.info("Tick \"Add to export list\" on videos, or use \"Add all\" in the sidebar.", title="The export list is empty")
    else:
        st.info("Nothing matches. Try fewer words or clear a filter.", title="No results")
    st.stop()


def moments(entry, search_text):
    """One line per matching tag: its name and when it shows up."""
    lines = []
    for tag in matching_tags(entry, search_text)[:MAX_MOMENTS]:
        times = ", ".join(format_time(t) for t in tag["times"][:8])
        lines.append(f"**{label(tag['keyword'])}** · {tag['hits']} of {entry['video']['frames']} frames · {times}")
    return lines


def export_checkbox(key, scope):
    """The 'Add to export list' box of a video. `scope` keeps widget keys unique when it shows up twice."""
    if state.files[key]["kind"] == "video":
        widget_key = f"sel:{st.session_state.sel_version}:{scope}:{key}"
        st.checkbox(
            "Add to export list", value=key in export_list, key=widget_key,
            on_change=toggle_export, args=(key, widget_key),
        )


def open_buttons(key, scope, stacked=False):
    """Open the file / show it in its folder. `stacked` puts them one above the other (narrow grid cards)."""
    plugged = cfg.is_mounted(key)
    path = cfg.path_of(key) if plugged else None
    left, right = (st.container(), st.container()) if stacked else st.columns(2)
    left.button("Open file", icon=":material/play_circle:", key=f"open:{scope}:{key}", width="stretch", on_click=open_file, args=(path,), disabled=not plugged)
    right.button("Show in folder", icon=":material/folder_open:", key=f"reveal:{scope}:{key}", width="stretch", on_click=reveal_in_folder, args=(path,), disabled=not plugged)
    if not plugged:
        st.caption(f"Plug in {drive_of(key)} to open it.", help="The preview and tags above come from the index.")


def drive_badge(key):
    """Which disk the file is on: green when it is plugged in right now, grey when it is not."""
    plugged = cfg.is_mounted(key)
    st.badge(
        drive_of(key), icon=":material/hard_drive:", color="green" if plugged else "gray",
        help="Plugged in" if plugged else "Not plugged in: the preview and tags come from the index",
    )


def place_of(entry):
    location = effective_location(entry)
    return ", ".join(p for p in (location.get("city"), location.get("country")) if p) or "no location"


def photo_tags(entry):
    """What a photo is found by: your review if there is one, else the model's likely suggestions."""
    keywords = entry["review"]["keywords"] if entry.get("review") else [
        s["keyword"] for s in entry["tags"]["suggestions"] if s["prob"] >= 0.5
    ]
    return keywords


def render_media(key, entry, name, hint=True, crop=False):
    """Hover-scrub strip for a video that has one, otherwise a plain thumbnail (`crop`: fixed 16:9 shape)."""
    try:
        strip = (entry.get("video") or {}).get("strip")
        if strip and (cfg.data_dir / "thumbs" / strip["file"]).exists():
            query = query_of(key)
            hits = matching_tags(entry, query) if query.strip() else []
            marks = sorted(t for tag in hits for t in tag["times"])
            best = hits[0]["best_t"] if hits else entry["video"]["duration"] / 2
            scrub(
                cfg.data_dir / "thumbs" / strip["file"], strip, entry["video"]["duration"], marks, best,
                key=f"scrub:{key}", on_pick=lambda seconds, key=key: cfg.is_mounted(key) and open_in_vlc(cfg.path_of(key), seconds, vlc),
            )
            if hint:
                st.caption("Move the mouse to browse, click to play in VLC.")
        else:
            if entry["kind"] == "video":
                shot = cfg.data_dir / "thumbs" / entry["video"]["thumb"]
            else:
                shot = photo_thumb(cfg, exiftool, key, entry)
            st.image(str(cover(shot) if crop else shot), alt=f"Preview of {name}", width="stretch")
    except Exception:  # an unreadable file should not break the whole page
        st.caption("no preview")


def render_list_card(key):
    entry = state.files[key]
    name = key.rsplit("/", 1)[-1]
    place = place_of(entry)
    with st.container(border=True):
        image, info = st.columns([1, 3], gap="medium")
        with image:
            render_media(key, entry, name)
        with info:
            kind = "Video" if entry["kind"] == "video" else "Photo"
            st.subheader(name, anchor=False)
            drive_badge(key)
            st.caption(f"{kind} · {dive_name(key)} · {place}")
            if entry["kind"] == "video":
                st.caption(f"{format_time(entry['video']['duration'])} long, one frame every {entry['video']['interval']:.0f} s")
                for line in moments(entry, query_of(key)):
                    st.markdown(line)
            else:
                st.markdown(" · ".join(f"**{label(k)}**" for k in photo_tags(entry)) or "_no tags_")
            export_checkbox(key, "result")
            open_buttons(key, "result")

            if entry["kind"] != "video":
                near = videos_near(state, key)
                if near:
                    with st.expander(f"{len(near)} videos from the same dive folder"):
                        for vkey in near:
                            st.markdown(f"**{vkey.rsplit('/', 1)[-1]}**")
                            for line in moments(state.files[vkey], "")[:3]:
                                st.caption(line)
                            export_checkbox(vkey, f"near:{key}")
                            open_buttons(vkey, f"near:{key}")


def render_grid_card(key):
    """A compact card: preview, name, place, top tags, the export box and the two open buttons."""
    entry = state.files[key]
    name = key.rsplit("/", 1)[-1]
    is_video = entry["kind"] == "video"
    with st.container(border=True):
        render_media(key, entry, name, hint=False, crop=True)
        drive_badge(key)
        st.markdown(f"**{name}**")
        meta = f"{format_time(entry['video']['duration'])} · " if is_video else ""
        st.caption(f"{meta}{place_of(entry)} · {dive_name(key)[:8]}")
        if is_video:
            shown = [label(t["keyword"]) for t in matching_tags(entry, query_of(key))[:3]]
        else:
            shown = [label(k) for k in photo_tags(entry)[:3]]
        st.markdown(" · ".join(f"`{s}`" for s in shown) or "_no tags_")
        export_checkbox(key, "grid")
        open_buttons(key, "grid", stacked=True)


page_keys = shown_keys[(page - 1) * page_size : page * page_size]
if view == "grid":
    for start in range(0, len(page_keys), GRID_COLUMNS):
        for column, key in zip(st.columns(GRID_COLUMNS), page_keys[start : start + GRID_COLUMNS]):
            with column:
                render_grid_card(key)
else:
    for key in page_keys:
        render_list_card(key)
