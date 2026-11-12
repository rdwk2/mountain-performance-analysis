"""La page « Q1 » (AN2-3, ``docs/decisions/0015``) : la dernière figure écrite par
``just q1``, telle quelle, sans la recalculer, avec sa date ; elle dit si elle ne vient
pas des tables actuelles.

``mountain_perf.analyse`` ne s'importe que dans la fonction
(``tests/test_ui_imports.py``, ``PISTE_PAGES``) ; ni plotly ni pyarrow : la figure est
le HTML écrit par ``just q1``.
"""

from __future__ import annotations

import streamlit as st
import streamlit.components.v1 as components

from mountain_perf.ui.components import data_folder
from mountain_perf.ui.recuperation import cached_tables

FIGURE_HEIGHT = 1100
"""La hauteur du cadre de la figure, en pixels."""

MATCH_TEXTS: dict[str, str] = {
    "different": (
        "Cette figure ne vient pas des tables actuelles : just process a été relancé "
        "depuis (autre commit, autres paramètres, journal.csv retouché…). Relancer "
        "just q1 pour la refaire."
    ),
    "unknown": (
        "Comparaison impossible : les tables actuelles ne se relisent pas. La figure "
        "est celle du dernier just q1."
    ),
}
"""L'avertissement de chaque comparaison qui n'est pas ``same``."""


def _unreadable(count: int) -> None:
    if count:
        st.caption(f"Dossiers de résultats illisibles, ignorés : {count}.")


def q1_page() -> None:
    """La page « Q1 » (Q1 à Q6)."""
    from mountain_perf.analyse.parquet import ProcessedError
    from mountain_perf.analyse.results import (
        RESULTS_DIR,
        TablesMatch,
        latest_result,
        read_figure,
        stored_results,
    )

    st.title("Q1")
    data = data_folder()
    if data is None:
        return
    try:
        current = cached_tables(data).provenance
    except (ProcessedError, FileNotFoundError):
        current = None
    latest = latest_result(data, current)
    if latest is None:
        st.info("Aucun résultat de Q1 dans resultats/Q1/ : lancer just q1.")
        _unreadable(stored_results(data)[1])
        return
    folder = f"{RESULTS_DIR.as_posix()}/{latest.result.folder.name}/"
    st.caption(
        f"Figure du {latest.result.generated_on:%d/%m/%Y} ({folder}), telle que just "
        "q1 l'a écrite."
    )
    if latest.match is not TablesMatch.SAME:
        st.warning(MATCH_TEXTS[latest.match.value])
    _unreadable(latest.unreadable)
    html = read_figure(latest.result)
    if html is None:
        st.error(f"figure.html manque dans {folder}.")
        return
    components.html(html, height=FIGURE_HEIGHT, scrolling=True)
