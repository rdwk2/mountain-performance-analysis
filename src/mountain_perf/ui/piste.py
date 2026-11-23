"""Les outils communs aux pages de la piste analyse : la lecture des tables de
``processed/``, gardée en mémoire (``docs/decisions/0016``, section AN2-3, « Le
cache »), et le contrôle de la Fenêtre (``docs/decisions/0019``, section AN4-1).

Le contrôle garde son choix dans des clés de session à part, recopiées à chaque
changement : Streamlit efface l'état d'un contrôle absent de la page affichée. Les
bornes se calculent dans ``mountain_perf.analyse.window`` (règle 7 de ``CLAUDE.md``).

``mountain_perf.analyse`` ne s'importe que dans les fonctions
(``tests/test_ui_imports.py``, ``PISTE_PAGES``).
"""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from types import MappingProxyType
from typing import Any, Final

import streamlit as st

WINDOW_KEY: Final = "piste.fenetre"
"""La clé à part du choix de la Fenêtre : sa valeur (``"28"``, …, ``"plage"``)."""

RANGE_FIRST_KEY: Final = "piste.fenetre.du"
"""La clé à part du premier jour de la plage (une date)."""

RANGE_LAST_KEY: Final = "piste.fenetre.au"
"""La clé à part du dernier jour de la plage (une date)."""

CHOICE_WIDGET: Final = "piste.fenetre.choix"
"""La clé du contrôle du choix ; jamais écrite par le code."""

FIRST_WIDGET: Final = "piste.fenetre.choix_du"
"""La clé du contrôle du premier jour de la plage ; jamais écrite par le code."""

LAST_WIDGET: Final = "piste.fenetre.choix_au"
"""La clé du contrôle du dernier jour de la plage ; jamais écrite par le code."""

WINDOW_LABELS: Mapping[str, str] = MappingProxyType(
    {
        "28": "28 jours",
        "56": "56 jours",
        "90": "90 jours",
        "tout": "tout l'historique",
        "plage": "plage",
    }
)
"""Le libellé de chaque choix, par sa valeur, dans l'ordre de ``WindowChoice``."""

EMPTY_RANGE: Final = (
    "La plage est vide : son premier jour vient après le second, ou elle est hors des "
    "données."
)
"""Ce que dit la page d'une plage vide."""


def _read(data: Path, key: bytes) -> Any:
    """La lecture des tables, sous la clé de leur provenance ; ``read_tables`` résolu
    à l'appel."""
    from mountain_perf.analyse import parquet

    del key  # la clé ne sert qu'au cache
    return parquet.read_tables(data)


_cached_read = st.cache_resource(max_entries=1, show_spinner="Lecture des tables…")(
    _read
)
"""La lecture gardée en mémoire tant que le dossier et la clé ne changent pas ;
``st.cache_resource`` appliqué par un appel, sans décorateur (``mypy`` sans l'extra
``tableau``)."""


def cached_tables(data: Path) -> Any:
    """Les tables de ``data/processed/``, gardées en mémoire tant que leur provenance
    ne change pas ; sans clé (``tables_key`` rend ``None``), la lecture directe, qui
    lève comme ``read_tables``."""
    from mountain_perf.analyse import parquet

    key = parquet.tables_key(data)
    if key is None:
        return parquet.read_tables(data)
    return _cached_read(data, key)


def _copy(widget: str, kept: str) -> None:
    """Recopie la valeur du contrôle ``widget`` dans sa clé à part ``kept``."""
    st.session_state[kept] = st.session_state[widget]


def window_control(span: Any) -> Any:
    """Le contrôle de la Fenêtre, dans la barre latérale, sur l'étendue des données
    ``span`` : le choix, puis, pour une plage, ses deux jours (sans bornes : c'est
    ``date_range`` qui les ramène à l'étendue) ; chacun lu dans sa clé à part, et
    recopié dans elle à chaque changement. Rend la Fenêtre, ``None`` pour une plage
    vide."""
    from mountain_perf.analyse.window import (
        DEFAULT_CHOICE,
        DEFAULT_DAYS,
        WindowChoice,
        chosen_window,
        last_days,
    )

    options = tuple(choice.value for choice in WindowChoice)
    kept = st.session_state.get(WINDOW_KEY)
    index = options.index(kept if kept in options else DEFAULT_CHOICE.value)
    first: Any = None
    last: Any = None
    with st.sidebar:
        choice = st.radio(
            "Fenêtre",
            options,
            index=index,
            format_func=WINDOW_LABELS.__getitem__,
            key=CHOICE_WIDGET,
            horizontal=True,
            on_change=_copy,
            args=(CHOICE_WIDGET, WINDOW_KEY),
        )
        if choice == WindowChoice.RANGE.value:
            default = last_days(span, DEFAULT_DAYS)
            first = st.date_input(
                "Du",
                value=st.session_state.get(RANGE_FIRST_KEY, default.first),
                format="DD/MM/YYYY",
                key=FIRST_WIDGET,
                on_change=_copy,
                args=(FIRST_WIDGET, RANGE_FIRST_KEY),
            )
            last = st.date_input(
                "Au",
                value=st.session_state.get(RANGE_LAST_KEY, default.last),
                format="DD/MM/YYYY",
                key=LAST_WIDGET,
                on_change=_copy,
                args=(LAST_WIDGET, RANGE_LAST_KEY),
            )
    return chosen_window(span, WindowChoice(choice), first, last)
