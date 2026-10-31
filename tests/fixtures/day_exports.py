"""Des exports journaliers inventés (AN2-1), rangés dans un dossier temporaire comme
les vrais : ``raw/garmin/<export>/<famille>/<AAAA-MM-JJ>.json``, avec les documents de
``fixtures/families.py`` ; et leur ingestion (``load_export_days``, ``build_days``).

Les instants d'acquisition sont ceux de ``fixtures.days.RETRIEVED`` : A le plus
ancien, puis B, puis C.
"""

from __future__ import annotations

import json
from collections.abc import Iterable
from datetime import date, datetime
from pathlib import Path
from typing import Any

from fixtures.days import DAY, EXPORT_A, RETRIEVED
from fixtures.families import DOCUMENTS, encode
from mountain_perf.ingest.days import (
    DaysIngestion,
    ExportDays,
    build_days,
    load_export_days,
)
from mountain_perf.schemas import DayFamily, DayRecord

ALL_FAMILIES: tuple[DayFamily, ...] = tuple(DayFamily)
"""Les onze familles, dans l'ordre de ``DayFamily``."""


def export_dir(root: Path, export: str = EXPORT_A) -> Path:
    """Le dossier ``raw/garmin/<export>/`` sous ``root``."""
    return root / "raw" / "garmin" / export


def write_acquisition(root: Path, export: str = EXPORT_A) -> Path:
    """Le fichier ``acquisition.json`` de l'export, à son instant de ``RETRIEVED``."""
    path = export_dir(root, export) / "acquisition.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({"retrieved_at": RETRIEVED[export].isoformat()}), encoding="utf-8"
    )
    return path


def write_document(
    root: Path,
    family: DayFamily,
    document: Any,
    day: date = DAY,
    export: str = EXPORT_A,
) -> Path:
    """Le fichier ``<famille>/<day>.json`` de l'export : ``document`` (des octets tels
    quels, ou un document encodé comme la source)."""
    path = export_dir(root, export) / family.value / f"{day.isoformat()}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(document if isinstance(document, bytes) else encode(document))
    return path


def write_day(
    root: Path,
    day: date = DAY,
    export: str = EXPORT_A,
    families: Iterable[DayFamily] = ALL_FAMILIES,
    **documents: Any,
) -> None:
    """Les fichiers d'un jour de l'export : le document par défaut de chaque famille
    de ``families``, sauf ceux que ``documents`` donne (par la valeur de la famille)."""
    for family in families:
        document = documents.get(family.value)
        if document is None:
            document = DOCUMENTS[family](day)
        write_document(root, family, document, day, export)


def load(
    root: Path, export: str = EXPORT_A, retrieved_at: datetime | None = None
) -> ExportDays:
    """Les fichiers journaliers de l'export (``load_export_days``)."""
    instant = RETRIEVED[export] if retrieved_at is None else retrieved_at
    return load_export_days(export_dir(root, export), export, instant)


def build(root: Path, *exports: str) -> DaysIngestion:
    """L'ingestion des jours des exports nommés (A seul par défaut)."""
    return build_days([load(root, export) for export in exports or (EXPORT_A,)])


def record(ingestion: DaysIngestion, day: date = DAY) -> DayRecord:
    """Le document du jour ``day``."""
    found = [item for item in ingestion.records if item.day == day]
    assert len(found) == 1, day
    return found[0]
