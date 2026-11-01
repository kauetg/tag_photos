"""Streamlit entry point: the library (search) and the review page.

Start it with `python tagger.py review` (or `streamlit run streamlit_app.py -- --media-root <path>`).
"""
import base64
from pathlib import Path

import streamlit as st

from mediatagger.uicontext import context, reload_state

st.set_page_config(page_title="ReeFind", page_icon="assets/gliph.svg", layout="wide")

cfg, _, _ = context()
theme = st.context.theme.type or "dark"
st.logo(f"assets/logo-for-{theme}.svg", icon_image=f"assets/gliph-for-{theme}.svg", size="large")
st.html('<style>[data-testid="stSidebarLogo"]{height:3.25rem}[data-testid="stSidebarHeader"]{height:5rem}</style>')  # "large" is only 2rem

# The symbol as a faint, tilted watermark in the corner of the page (tilted and faded inside the SVG itself).
mark = (Path("assets") / f"gliph-for-{theme}.svg").read_text(encoding="utf-8")
mark = mark.replace('viewBox="0 0 500 500"', 'viewBox="-100 -100 700 700"').replace("<g id=", '<g opacity=".06" transform="rotate(-14 250 250)" id=', 1)
st.html(
    f'<style>.stApp{{background-image:url("data:image/svg+xml;base64,{base64.b64encode(mark.encode()).decode()}");'
    "background-repeat:no-repeat;background-position:right -5rem bottom -5rem;background-size:40rem;background-attachment:fixed}</style>"
)

pages = st.navigation([
    st.Page("app_pages/library.py", title="Library", icon=":material/search:", default=True),
    st.Page("app_pages/review.py", title="Review tags", icon=":material/checklist:"),
    st.Page("app_pages/write.py", title="Write", icon=":material/edit_note:"),
    st.Page("app_pages/vocabulary.py", title="Vocabulary", icon=":material/sell:"),
    st.Page("app_pages/locations.py", title="Locations", icon=":material/pin_drop:"),
])

with st.sidebar:
    st.button("Reload data", icon=":material/refresh:", width="stretch", on_click=reload_state, args=(cfg,))

pages.run()
