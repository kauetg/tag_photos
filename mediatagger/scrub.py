"""Hover-scrub preview for a video card: move the mouse across it to flip through frames,
click to play from that moment. A Streamlit custom component (v2), declared once here."""
from __future__ import annotations

import base64
from collections.abc import Callable
from pathlib import Path

import streamlit as st

HTML = """
<div class="scrub" id="scrub">
  <div class="frame" id="frame"></div>
  <div class="time" id="time"></div>
  <div class="bar"><div class="marks" id="marks"></div><div class="head" id="head"></div></div>
</div>
"""

CSS = """
.scrub { position: relative; cursor: pointer; border-radius: var(--st-base-radius, 0.5rem); overflow: hidden;
         background: var(--st-secondary-background-color, #222); user-select: none; }
.frame { width: 100%; background-repeat: no-repeat; background-size: auto 100%; }
.time { position: absolute; right: 6px; bottom: 10px; padding: 1px 6px; border-radius: 4px; font-size: 12px;
        font-family: var(--st-font, sans-serif); color: #fff; background: rgba(0, 0, 0, 0.65); }
.bar { position: relative; height: 4px; background: rgba(255, 255, 255, 0.18); }
.head { position: absolute; top: 0; bottom: 0; width: 2px; background: var(--st-primary-color, #ff4b4b); }
.mark { position: absolute; top: 0; bottom: 0; width: 3px; background: #ffd23f; }
"""

JS = """
export default function (component) {
  const { data, parentElement, setTriggerValue } = component
  const root = parentElement.querySelector("#scrub")
  const frame = parentElement.querySelector("#frame")
  const time = parentElement.querySelector("#time")
  const head = parentElement.querySelector("#head")
  const marks = parentElement.querySelector("#marks")
  if (!root || !data) return

  const n = data.n
  const label = (s) => {
    s = Math.round(s)
    const h = Math.floor(s / 3600), m = Math.floor((s % 3600) / 60), sec = s % 60
    const mm = h ? String(m).padStart(2, "0") : String(m)
    return (h ? h + ":" : "") + mm + ":" + String(sec).padStart(2, "0")
  }
  const show = (i) => {
    i = Math.max(0, Math.min(n - 1, i))
    frame.style.backgroundPosition = (n > 1 ? (i / (n - 1)) * 100 : 0) + "% 0"
    time.textContent = label(data.times[i])
    head.style.left = ((data.times[i] / data.duration) * 100) + "%"
    return i
  }

  frame.style.backgroundImage = "url(" + data.src + ")"
  frame.style.aspectRatio = data.tile_w + " / " + data.tile_h
  marks.replaceChildren(...data.marks.map((f) => {
    const el = document.createElement("div")
    el.className = "mark"
    el.style.left = (f * 100) + "%"
    return el
  }))

  let current = show(data.start)
  root.onmousemove = (e) => {
    const box = root.getBoundingClientRect()
    current = show(Math.floor(((e.clientX - box.left) / box.width) * n))
  }
  root.onmouseleave = () => { current = show(data.start) }
  root.onclick = () => setTriggerValue("pick", data.times[current])
}
"""

_COMPONENT = st.components.v2.component("video_scrub", html=HTML, css=CSS, js=JS)


def data_uri(path: Path) -> str:
    return "data:image/jpeg;base64," + base64.b64encode(Path(path).read_bytes()).decode("ascii")


def scrub(
    strip_file: Path, strip: dict, duration: float, marks: list[float], start_time: float,
    key: str, on_pick: Callable[[float], None],
):
    """Show the strip. `on_pick(seconds)` runs when the user clicks a frame.

    `marks` are moments (seconds) drawn as ticks on the bar; `start_time` picks the frame shown at rest.
    """
    times = strip["times"]
    start = min(range(len(times)), key=lambda i: abs(times[i] - start_time))

    def picked():
        seconds = getattr(st.session_state[key], "pick", None)
        if seconds is not None:
            on_pick(float(seconds))

    return _COMPONENT(
        key=key,
        data={
            "src": data_uri(strip_file), "n": strip["n"], "tile_w": strip["tile_w"], "tile_h": strip["tile_h"],
            "times": times, "duration": max(duration, 1.0), "marks": [m / max(duration, 1.0) for m in marks],
            "start": start,
        },
        on_pick_change=picked,
    )
