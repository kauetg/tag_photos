"""Locations page: places with the folder words that mean them, a timeline of date ranges, and a way to apply it all.

Saves config/locations.csv and config/date_ranges.csv (the previous versions are kept as .bak).
Every edit to a place is saved as soon as you make it; nothing here needs a separate save button except the date table.
"""
import re
from calendar import month_name, monthcalendar, monthrange
from collections import defaultdict
from dataclasses import replace
from datetime import date, timedelta
from html import escape

import streamlit as st

from mediatagger.config import normalize, parse_folder_date
from mediatagger.places import (
    DateRule, NameRule, default_keyword, load_date_rules, load_name_rules, save_date_rules, save_name_rules,
    unmapped_folders, validate_date_rules, validate_name_rules,
)
from mediatagger.scan import relocate, resolve_location
from mediatagger.uicontext import context, reload_config

cfg, _, state = context()
names_path = cfg.config_dir / "locations.csv"
dates_path = cfg.config_dir / "date_ranges.csv"
name_rules = load_name_rules(names_path)
date_rules = load_date_rules(dates_path)


def label(keyword: str) -> str:
    return keyword.removeprefix("Location|").replace("|", " › ")


def save_names(rules: list[NameRule], done: str) -> bool:
    """Validate and write; on a problem nothing is saved and the reasons are shown."""
    problems = validate_name_rules(rules)
    if problems:
        st.toast("Not saved: " + " ".join(problems), icon=":material/error:", duration="long")
        return False
    save_name_rules(names_path, rules)
    reload_config()
    st.toast(done, icon=":material/check:")
    return True


def save_dates(rules: list[DateRule], done: str) -> bool:
    problems = validate_date_rules(rules)
    if problems:
        st.toast("Not saved: " + " ".join(problems), icon=":material/error:", duration="long")
        return False
    save_date_rules(dates_path, rules)
    reload_config()
    st.toast(done, icon=":material/check:")
    return True


def range_form(key: str, rule: DateRule | None, default_day: date) -> DateRule | None:
    """A small form for one date range; returns the range when it is submitted, else None."""
    places = {}  # keyword -> (country, city, sublocation) of any rule that already uses it
    for r in [*name_rules, *date_rules]:
        places.setdefault(r.keyword, (r.country, r.city, r.sublocation))
    options = sorted(places, key=label)
    with st.form(key, border=False):
        a, b = st.columns(2)
        start = a.date_input("From", parse_folder_date(rule.start) if rule else default_day, format="YYYY-MM-DD")
        end = b.date_input("To", parse_folder_date(rule.end) if rule else default_day, format="YYYY-MM-DD")
        keyword = st.selectbox(
            "Place", options, index=options.index(rule.keyword) if rule else None, format_func=label, placeholder="Pick a place",
            help="A place that is not listed yet can be created under Places.",
        )
        note = st.text_input("Note", rule.note if rule else "")
        if not st.form_submit_button("Save", type="primary"):
            return None
    if not (start and end and keyword):
        st.toast("Pick both dates and a place.", icon=":material/error:")
        return None
    country, city, sub = places[keyword]
    return DateRule(start.strftime("%Y%m%d"), end.strftime("%Y%m%d"), keyword, country, city, sub, note.strip())


def set_words(keyword: str) -> None:
    """The chips of one place changed: its rules become exactly those words."""
    key = f"words:{keyword}"
    words = [w.strip() for w in st.session_state[key] if w.strip()]
    rules = load_name_rules(names_path)
    template = next(r for r in rules if r.keyword == keyword)
    rest = [r for r in rules if r.keyword != keyword]
    ok = bool(words) and save_names(rest + [replace(template, match=w) for w in words], f"{label(keyword)}: words saved.")
    if not ok:
        if not words:
            st.toast("A place needs at least one word; use its edit menu to delete it.", icon=":material/error:")
        del st.session_state[key]  # show what is really on disk again


def folder_head(name: str) -> str:
    """A starting word for a folder: its name without the leading date and 'Dia N'."""
    return re.sub(r"^\d{8}\s*(dia\s*\d+\s*)?", "", name, flags=re.I).strip()


PALETTE = ["#e4572e", "#2e86ab", "#76b041", "#f2b134", "#9b5de5", "#00a6a6", "#e56b9f", "#8d99ae"]
COUNTRY_COLOR = {c: PALETTE[i % len(PALETTE)] for i, c in enumerate(sorted({r.country for r in name_rules + date_rules}))}


def day_rules(rules: list[DateRule]) -> dict:
    """Day -> the rule that decides it (the shortest range wins, as in scan)."""
    best = {}
    for rule in rules:
        start, end = parse_folder_date(rule.start), parse_folder_date(rule.end)
        if not (start and end):
            continue
        span, day = (end - start).days, start
        while day <= end:
            if day not in best or span < best[day][0]:
                best[day] = (span, rule)
            day += timedelta(days=1)
    return {day: rule for day, (_, rule) in best.items()}


def step_month(months: list, delta: int) -> None:
    i = months.index(st.session_state.cal_month) + delta
    st.session_state.cal_month = months[min(max(i, 0), len(months) - 1)]


def month_html(year: int, month: int, day_rule: dict) -> str:
    """One month as a calendar grid: each day tinted by country, the place named where it starts."""
    cells = [f'<div class="wd">{wd}</div>' for wd in ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")]
    for week in monthcalendar(year, month):
        for col, number in enumerate(week):
            if not number:
                cells.append('<div class="day off"></div>')
                continue
            today = date(year, month, number)
            rule = day_rule.get(today)
            if not rule:
                cells.append(f'<div class="day none"><b>{number}</b></div>')
                continue
            color = COUNTRY_COLOR.get(rule.country, "#8d99ae")
            starts = col == 0 or day_rule.get(today - timedelta(days=1)) is not rule
            name = escape(label(rule.keyword).split(" › ")[-1]) if starts else ""
            tip = escape(f"{label(rule.keyword)} · {parse_folder_date(rule.start)} to {parse_folder_date(rule.end)}"
                         + (f" · {rule.note}" if rule.note else ""))
            cells.append(f'<div class="day" title="{tip}" style="background:{color}38;border-left-color:{color}"><b>{number}</b><span>{name}</span></div>')
    css = (
        "<style>.cal{display:grid;grid-template-columns:repeat(7,1fr);gap:4px;margin:8px 0 4px}"
        ".cal .wd{font-size:12px;opacity:.6;text-align:center}"
        ".cal .day{min-height:68px;padding:4px 6px;border-radius:6px;border-left:3px solid transparent;overflow:hidden}"
        ".cal .day b{font-size:12px;opacity:.7;display:block}.cal .day span{font-size:12px;font-weight:600;line-height:1.2}"
        ".cal .none{background:rgba(128,128,128,.08)}.cal .off{background:none}"
        ".key{display:flex;flex-wrap:wrap;gap:12px;font-size:13px;margin-top:6px}"
        ".key i{display:inline-block;width:10px;height:10px;border-radius:3px;margin-right:5px}</style>"
    )
    countries = sorted({r.country for d, r in day_rule.items() if (d.year, d.month) == (year, month)})
    key = "".join(f'<span><i style="background:{COUNTRY_COLOR.get(c, "#8d99ae")}"></i>{escape(c or "(none)")}</span>' for c in countries)
    return f'{css}<div class="cal">{"".join(cells)}</div><div class="key">{key}</div>'


st.title("Locations")
st.caption(
    "Where each dive happened. A word in the folder name decides first; if no word matches, the date ranges "
    "are the fallback. Edits apply to new scans right away and to the library when you press the button at the bottom."
)

# --- try a name -------------------------------------------------------------------------------------------------
with st.container(border=True):
    probe = st.text_input(
        "Try a folder name", placeholder="20260125 Dia 2 Siqui Mergulho Vibrations", icon=":material/science:",
        help="Type or paste a folder name, date first, to see which place the rules give it.",
    ).strip()
    if probe:
        head = probe[:8]
        place = resolve_location(cfg, (probe,), head if parse_folder_date(head) else None)
        if place:
            how = "a word in the name" if place["source"] == "name" else "the date range"
            st.success(f"**{label(place['keyword'])}**, found by {how}.")
        else:
            st.warning("No place found. Add a word from this name below, or a date range that covers it.")

# --- folders without a place ------------------------------------------------------------------------------------
missing = unmapped_folders(state)
places = defaultdict(list)  # keyword -> its rules
for rule in name_rules:
    places[rule.keyword].append(rule)

if missing:
    with st.container(border=True):
        st.markdown(f"**{sum(missing.values())} files in {len(missing)} folders have no place yet.**")
        folder = st.selectbox(
            "Folder", [f for f, _ in missing.most_common()], format_func=lambda f: f"{f}  ·  {missing[f]} files",
        )
        left, right = st.columns(2)
        word = left.text_input("Word that means it", value=folder_head(folder), key=f"assign_word:{folder}")
        target = right.selectbox("Place", sorted(places, key=label), format_func=label, index=None, placeholder="Pick a place")
        if st.button("Assign", icon=":material/add_link:", disabled=not (word.strip() and target)):
            template = places[target][0]
            if save_names(name_rules + [replace(template, match=word.strip())], f"“{word.strip()}” now means {label(target)}."):
                st.rerun()
        st.caption("A place that is not listed yet? Create it with *New place* below, then come back.")

# --- places -----------------------------------------------------------------------------------------------------
tab_places, tab_dates = st.tabs(["Places", "Date ranges"], key="locations_tab", on_change="rerun")  # fixed labels keep the tab across saves

with tab_places:
    st.caption(f"{len(places)} places, {len(name_rules)} folder words. A word in a folder name means its place; the longest match wins.")
    top = st.columns([4, 1], vertical_alignment="bottom")
    search = top[0].text_input("Filter", placeholder="Philippines, rawa, ...", icon=":material/search:", label_visibility="collapsed")
    with top[1].popover("New place", icon=":material/add_location_alt:", width="stretch"):
        with st.form("new_place", border=False):
            country = st.text_input("Country")
            city = st.text_input("City")
            sub = st.text_input("Sublocation")
            first = st.text_input("First folder word", help="A word in a folder name that means this place.")
            if st.form_submit_button("Create", type="primary"):
                rule = NameRule(first.strip(), default_keyword(country, city, sub), country.strip(), city.strip(), sub.strip())
                if save_names(name_rules + [rule], f"{label(rule.keyword)} created."):
                    st.rerun()

    by_country = defaultdict(list)
    for keyword, rules in places.items():
        words = [r.match for r in rules]
        if search.strip() and not any(normalize(search) in normalize(t) for t in [label(keyword), *words]):
            continue
        by_country[rules[0].country or "(no country)"].append((keyword, rules))

    for country_name in sorted(by_country):
        st.markdown(f"#### {country_name}")
        for keyword, rules in sorted(by_country[country_name], key=lambda kr: label(kr[0])):
            first_rule = rules[0]
            with st.container(border=True):
                name_col, words_col, menu_col = st.columns([3, 6, 1], vertical_alignment="center")
                parts = label(keyword).split(" › ")[1:] or [country_name]
                name_col.markdown(f"**{parts[-1]}**")
                if len(parts) > 1:
                    name_col.caption(" › ".join(parts[:-1]))
                words = [r.match for r in rules]
                words_col.multiselect(
                    f"Words for {label(keyword)}", words, default=words, accept_new_options=True, key=f"words:{keyword}",
                    label_visibility="collapsed", placeholder="Add a folder word", on_change=set_words, args=(keyword,),
                )
                with menu_col.popover("", icon=":material/more_vert:"):
                    with st.form(f"edit:{keyword}", border=False):
                        new_country = st.text_input("Country", first_rule.country)
                        new_city = st.text_input("City", first_rule.city)
                        new_sub = st.text_input("Sublocation", first_rule.sublocation)
                        new_keyword = st.text_input("Keyword", keyword, help="What is written into the photos.")
                        if st.form_submit_button("Save place", type="primary"):
                            rest = [r for r in name_rules if r.keyword != keyword]
                            edited = [replace(r, keyword=new_keyword.strip(), country=new_country.strip(),
                                              city=new_city.strip(), sublocation=new_sub.strip()) for r in rules]
                            if save_names(rest + edited, f"{label(new_keyword)} saved."):
                                st.rerun()
                    if st.button("Delete place", key=f"del:{keyword}", icon=":material/delete:"):
                        if save_names([r for r in name_rules if r.keyword != keyword], f"{label(keyword)} deleted."):
                            st.rerun()
    if search.strip() and not by_country:
        st.info("No place matches that.")

# --- date ranges ------------------------------------------------------------------------------------------------
with tab_dates:
    st.caption(f"{len(date_rules)} ranges. Days (inclusive) spent in one place; if ranges overlap, the shortest one wins.")
    day_rule = day_rules(date_rules)
    months = sorted({(d.year, d.month) for d in day_rule}) or [(date.today().year, date.today().month)]
    if st.session_state.get("cal_month") not in months:
        st.session_state.cal_month = months[-1]
    prev_col, pick_col, next_col = st.columns([1, 4, 1], vertical_alignment="center")
    prev_col.button("", icon=":material/chevron_left:", on_click=step_month, args=(months, -1), key="cal_prev", width="stretch")
    next_col.button("", icon=":material/chevron_right:", on_click=step_month, args=(months, 1), key="cal_next", width="stretch")
    pick_col.selectbox(
        "Month", months, key="cal_month", label_visibility="collapsed", format_func=lambda ym: f"{month_name[ym[1]]} {ym[0]}",
    )
    year, month = st.session_state.cal_month
    if day_rule:
        st.html(month_html(year, month, day_rule))

    head_col, new_col = st.columns([3, 1], vertical_alignment="center")
    head_col.markdown(f"**Ranges in {month_name[month]} {year}**")
    with new_col.popover("New range", icon=":material/event_available:", width="stretch"):
        added = range_form("new_range", None, date(year, month, 1))
        if added and save_dates(date_rules + [added], "Date range added."):
            st.rerun()

    first, last = date(year, month, 1), date(year, month, monthrange(year, month)[1])
    shown = [
        (i, r) for i, r in enumerate(date_rules)
        if parse_folder_date(r.start) and parse_folder_date(r.end) and parse_folder_date(r.start) <= last and parse_folder_date(r.end) >= first
    ]
    for i, rule in sorted(shown, key=lambda ir: (ir[1].start, ir[1].end)):
        with st.container(border=True):
            when_col, what_col, menu_col = st.columns([3, 6, 1], vertical_alignment="center")
            start, end = parse_folder_date(rule.start), parse_folder_date(rule.end)
            when_col.markdown(f"**{start:%d %b}**" + (f" → **{end:%d %b %Y}**" if end != start else f" {start:%Y}"))
            dot = f'<span style="color:{COUNTRY_COLOR.get(rule.country, "#8d99ae")}">●</span>'
            what_col.markdown(f"{dot} {escape(label(rule.keyword))}", unsafe_allow_html=True)
            if rule.note:
                what_col.caption(rule.note)
            with menu_col.popover("", icon=":material/more_vert:"):
                changed = range_form(f"edit_range:{i}", rule, start)
                if changed and save_dates(date_rules[:i] + [changed] + date_rules[i + 1:], "Date range saved."):
                    st.rerun()
                if st.button("Delete range", key=f"del_range:{i}", icon=":material/delete:"):
                    if save_dates(date_rules[:i] + date_rules[i + 1:], "Date range deleted."):
                        st.rerun()
    if not shown:
        st.caption("No range touches this month.")

# --- apply ------------------------------------------------------------------------------------------------------
st.subheader("Apply to the library", anchor=False)
st.caption(
    "Re-runs the rules over every file already scanned. A place you picked in the review page is kept, and "
    "files you already wrote with `write` keep the place that was written then."
)
if st.button("Reapply locations to the library", icon=":material/sync:"):
    counts = relocate(cfg, state)
    state.save()
    reload_config()
    st.success(
        f"{counts['changed']} files got a different place, {counts['unchanged']} stayed the same, "
        f"{counts['without_location']} still have none."
    )
