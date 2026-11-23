"""Les outils communs aux pages de la piste analyse : la lecture des tables de
``processed/``, gardée en mémoire (``docs/decisions/0016``, section AN2-3, « Le
cache »).

``mountain_perf.analyse`` ne s'importe que dans les fonctions
(``tests/test_ui_imports.py``, ``PISTE_PAGES``).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import streamlit as st


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
