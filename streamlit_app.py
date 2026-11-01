"""Streamlit entry point: the library (search) and the review page.

Start it with `python tagger.py review` (or `streamlit run streamlit_app.py -- --media-root <path>`).
"""
import streamlit as st

from mediatagger.uicontext import context, reload_state

st.set_page_config(page_title="Media tagger", page_icon=":material/sailing:", layout="wide")

cfg, _, _ = context()

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
