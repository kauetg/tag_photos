"""Vocabulary page: edit what the model looks for and the tags you apply by hand.

Saves config/vocabulary.csv (the previous version is kept as vocabulary.csv.bak).
"""
import pandas as pd
import streamlit as st

from mediatagger.uicontext import context, vocabulary
from mediatagger.vocabulary import COLUMNS, SCENES, TIERS, VocabEntry, save_vocabulary, validate

cfg, _, _ = context()
entries, _ = vocabulary(cfg)
path = cfg.config_dir / "vocabulary.csv"

st.title("Vocabulary")
st.caption(
    "Every tag the app knows. **core** and **species** rows are what the model looks for; **manual** rows are only "
    "ever applied by you in the review page. Aliases are other words that find the tag when you type (separate with ;)."
)


def to_frame(rows: list[VocabEntry]) -> pd.DataFrame:
    return pd.DataFrame(
        [[e.keyword, e.prompt, e.scientific_name, ";".join(s for s in SCENES if s in e.scenes), e.tier, "; ".join(e.aliases)] for e in rows],
        columns=COLUMNS,
    )


def to_entries(frame: pd.DataFrame) -> list[VocabEntry]:
    rows = []
    for record in frame.fillna("").to_dict("records"):
        if not any(str(v).strip() for v in record.values()):
            continue  # a blank row left in the table
        rows.append(
            VocabEntry(
                keyword=str(record["keyword"]).strip(), prompt=str(record["prompt"]).strip(),
                scientific_name=str(record["scientific_name"]).strip(),
                scenes=frozenset(s.strip() for s in str(record["scene"]).split(";") if s.strip()),
                tier=str(record["tier"]).strip() or "core",
                aliases=tuple(a.strip() for a in str(record["aliases"]).split(";") if a.strip()),
            )
        )
    return rows


search = st.text_input("Filter", placeholder="turtle, cots, manual ...", icon=":material/search:")
frame = to_frame(entries)
if search.strip():
    frame = frame[frame.apply(lambda row: search.casefold() in " ".join(map(str, row)).casefold(), axis=1)]

edited = st.data_editor(
    frame,
    num_rows="dynamic",
    hide_index=True,
    height=520,
    key=f"vocab_editor:{len(entries)}:{search}",
    alt="Table of every tag in the vocabulary, editable",
    column_config={
        "keyword": st.column_config.TextColumn("Keyword (A|B|C)", width="large", required=True),
        "prompt": st.column_config.TextColumn("What the model looks for", width="large"),
        "scientific_name": st.column_config.TextColumn("Scientific name"),
        "scene": st.column_config.TextColumn("Scene", help="underwater; drone; land"),
        "tier": st.column_config.SelectboxColumn("Tier", options=list(TIERS), required=True),
        "aliases": st.column_config.TextColumn("Aliases", width="medium"),
    },
)

if st.button("Save vocabulary", type="primary", icon=":material/save:"):
    if search.strip():
        # Edits made while filtered apply to those rows only; the rest stay as they are.
        shown = set(frame["keyword"])
        merged = [e for e in entries if e.keyword not in shown] + to_entries(edited)
    else:
        merged = to_entries(edited)
    problems = validate(merged)
    if problems:
        st.error("\n".join(f"- {p}" for p in problems), title="Not saved")
    else:
        save_vocabulary(path, merged)
        st.success(f"{len(merged)} rows saved. The previous version is kept as {path.name}.bak.", title="Saved")
        st.caption("New model rows only affect photos tagged from now on; run `tag --redo` to apply them to old ones. Manual tags work right away.")
