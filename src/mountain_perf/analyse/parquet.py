"""Écriture et relecture des tables de ``processed/`` en Parquet (AN1-2b,
``docs/decisions/0014``) : le seul module du projet qui importe pyarrow (extra
``analyse``, ``docs/decisions/0011``).

Chaque contrat se convertit d'après ses champs, colonne par colonne :

- texte et énumérations : ``string`` ; flottants : ``float64`` ; entiers : ``int64`` ;
  booléens : ``bool`` ; toute colonne accepte ``null`` : c'est le contrat qui dit quel
  champ peut manquer ;
- listes par convention : ``list<float64>`` ; ``flags`` : ``list<string>`` ;
- un instant local (``start_time``, ``local_start_time``, jamais absents) : deux
  colonnes, l'heure murale locale sans fuseau (``timestamp[us]``) et son décalage en
  secondes (``<nom>_utc_offset_s``, ``int32``).

La provenance (:class:`~mountain_perf.schemas.processed.ProcessedProvenance`) s'écrit
dans les métadonnées de chaque fichier, sous la clé ``mountain_perf.provenance``, par
le codec commun. Les deux fichiers s'écrivent d'abord sous un nom temporaire ; une
fois les deux écrits, ils se mettent en place l'un après l'autre
(:func:`write_tables`). Si le second remplacement échouait, :func:`read_tables`
refuserait deux tables de provenances différentes.
"""

from __future__ import annotations

import dataclasses
import json
import typing
from collections.abc import Sequence
from datetime import datetime, timedelta, timezone
from enum import StrEnum
from pathlib import Path
from typing import Any

import pyarrow as pa
import pyarrow.parquet as pq

from mountain_perf.analyse.tables import Tables
from mountain_perf.codec import canonical_bytes, decode_contract, encode_contract
from mountain_perf.schemas.processed import (
    ActivityRow,
    ClimbRow,
    ProcessedProvenance,
)

PROCESSED_DIR = Path("processed")
"""Le dossier des tables, sous ``MPA_DATA_DIR``."""

ACTIVITIES_FILE = "activites.parquet"
CLIMBS_FILE = "montees.parquet"
PROVENANCE_KEY = b"mountain_perf.provenance"
_OFFSET_SUFFIX = "_utc_offset_s"
_TEMPORARY_SUFFIX = ".nouveau"


def _base(annotation: object) -> object:
    """Le type d'un champ, sans ``None`` s'il est facultatif."""
    args = typing.get_args(annotation)
    if type(None) in args:
        (rest,) = (a for a in args if a is not type(None))
        return rest
    return annotation


def _arrow_type(annotation: object) -> pa.DataType:
    if annotation is str or (
        isinstance(annotation, type) and issubclass(annotation, StrEnum)
    ):
        return pa.string()
    if annotation is bool:
        return pa.bool_()
    if annotation is int:
        return pa.int64()
    if annotation is float:
        return pa.float64()
    if typing.get_origin(annotation) is tuple:
        (item,) = {a for a in typing.get_args(annotation) if a is not Ellipsis}
        return pa.list_(_arrow_type(item))
    raise TypeError(f"type de colonne non pris en charge : {annotation!r}")


def _columns(cls: type) -> list[tuple[str, object]]:
    hints = typing.get_type_hints(cls)
    return [(f.name, _base(hints[f.name])) for f in dataclasses.fields(cls)]


def _plain(value: object) -> object:
    if isinstance(value, StrEnum):
        return value.value
    if isinstance(value, tuple):
        return [_plain(v) for v in value]
    return value


def _table(rows: Sequence[object], cls: type, provenance: ProcessedProvenance) -> Any:
    arrays: dict[str, Any] = {}
    fields: list[Any] = []
    for name, annotation in _columns(cls):
        values = [getattr(row, name) for row in rows]
        if annotation is datetime:
            local = [v.replace(tzinfo=None) for v in values]
            offsets = [int(v.utcoffset().total_seconds()) for v in values]
            fields.append(pa.field(name, pa.timestamp("us")))
            arrays[name] = pa.array(local, type=pa.timestamp("us"))
            offset_name = name + _OFFSET_SUFFIX
            fields.append(pa.field(offset_name, pa.int32()))
            arrays[offset_name] = pa.array(offsets, type=pa.int32())
            continue
        arrow = _arrow_type(annotation)
        fields.append(pa.field(name, arrow))
        arrays[name] = pa.array([_plain(v) for v in values], type=arrow)
    metadata = {PROVENANCE_KEY: canonical_bytes(encode_contract(provenance))}
    schema = pa.schema(fields, metadata=metadata)
    return pa.table([arrays[f.name] for f in fields], schema=schema)


def _write(table: Any, path: Path) -> None:
    """Écrit ``table`` en Parquet dans ``path``."""
    pq.write_table(table, path)


def write_tables(data_dir: Path, tables: Tables) -> tuple[Path, Path]:
    """Écrit ``processed/activites.parquet`` et ``processed/montees.parquet`` sous
    ``data_dir`` ; les rend. Les deux s'écrivent d'abord sous un nom temporaire ; une
    fois les deux écrits, ils se mettent en place. Si une écriture échoue, les
    temporaires sont retirés et les tables d'avant restent."""
    folder = data_dir / PROCESSED_DIR
    folder.mkdir(parents=True, exist_ok=True)
    pairs = [
        (folder / name, folder / (name + _TEMPORARY_SUFFIX), rows, cls)
        for name, rows, cls in (
            (ACTIVITIES_FILE, tables.activities, ActivityRow),
            (CLIMBS_FILE, tables.climbs, ClimbRow),
        )
    ]
    try:
        for _, temporary, rows, cls in pairs:
            _write(_table(rows, cls, tables.provenance), temporary)
    except BaseException:
        for _, temporary, _, _ in pairs:
            temporary.unlink(missing_ok=True)
        raise
    for target, temporary, _, _ in pairs:
        temporary.replace(target)
    return pairs[0][0], pairs[1][0]


def _value(annotation: object, raw: object) -> object:
    if raw is None:
        return None
    if isinstance(annotation, type) and issubclass(annotation, StrEnum):
        return annotation(str(raw))
    if typing.get_origin(annotation) is tuple:
        (item,) = {a for a in typing.get_args(annotation) if a is not Ellipsis}
        if not isinstance(raw, list):
            raise TypeError(f"liste attendue, reçu {raw!r}")
        return tuple(_value(item, v) for v in raw)
    return raw


def _rows[T](path: Path, cls: type[T]) -> tuple[tuple[T, ...], ProcessedProvenance]:
    table = pq.read_table(path)
    metadata = table.schema.metadata or {}
    provenance = decode_contract(
        ProcessedProvenance, json.loads(metadata[PROVENANCE_KEY])
    )
    data = table.to_pylist()
    rows = []
    for record in data:
        values: dict[str, object] = {}
        for name, annotation in _columns(cls):
            if annotation is datetime:
                offset = timedelta(seconds=record[name + _OFFSET_SUFFIX])
                values[name] = record[name].replace(tzinfo=timezone(offset))
            else:
                values[name] = _value(annotation, record[name])
        rows.append(cls(**values))
    return tuple(rows), provenance


def read_tables(data_dir: Path) -> Tables:
    """Relit les deux tables de ``data_dir/processed/`` ; leurs provenances doivent
    être égales (``ValueError`` sinon)."""
    folder = data_dir / PROCESSED_DIR
    activities, first = _rows(folder / ACTIVITIES_FILE, ActivityRow)
    climbs, second = _rows(folder / CLIMBS_FILE, ClimbRow)
    if first != second:
        raise ValueError("Les deux tables de processed/ n'ont pas la même provenance.")
    return Tables(activities, climbs, first)
