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
le codec commun. Les trois fichiers s'écrivent dans ``processed.nouveau/``, qui prend
ensuite la place de ``processed/`` par un échange de dossier (:func:`write_tables`) :
les tables d'avant restent tant que les trois nouvelles ne sont pas écrites, et
``processed/`` porte toujours trois tables d'une même écriture. :func:`read_tables`
refuse trois tables de provenances différentes, des tables d'avant AN1-2c, et une table
qui manque ou qui ne se relit pas.
"""

from __future__ import annotations

import dataclasses
import json
import shutil
import typing
from collections.abc import Sequence
from datetime import datetime, timedelta, timezone
from enum import StrEnum
from pathlib import Path
from typing import Any

import pyarrow as pa
import pyarrow.parquet as pq

from mountain_perf.analyse.tables import Tables
from mountain_perf.codec import (
    CodecError,
    canonical_bytes,
    decode_contract,
    encode_contract,
)
from mountain_perf.schemas.processed import (
    ActivityRow,
    ClimbRow,
    ClimbVariantRow,
    ProcessedProvenance,
)
from mountain_perf.validation import ContractError

PROCESSED_DIR = Path("processed")
"""Le dossier des tables, sous ``MPA_DATA_DIR``."""

ACTIVITIES_FILE = "activites.parquet"
CLIMBS_FILE = "montees.parquet"
VARIANTS_FILE = "variantes.parquet"
PROVENANCE_KEY = b"mountain_perf.provenance"
_OFFSET_SUFFIX = "_utc_offset_s"
_NEW_SUFFIX = ".nouveau"
_OLD_SUFFIX = ".ancien"
STALE_TABLES = (
    "les tables de processed/ datent d'avant AN1-2c (sans {name}) : relancer just "
    "process"
)
"""Le message de :class:`ProcessedError` pour des tables d'avant AN1-2c."""

MISSING_TABLE = "{name} manque dans processed/ : relancer just process"
"""Le message de :class:`ProcessedError` pour une table d'AN1-2b qui manque."""

UNREADABLE_TABLE = "{name} ne se relit pas : relancer just process"
"""Le message de :class:`ProcessedError` pour une table abîmée."""

NO_TABLES = "aucune table dans processed/ : lancer just process"
"""Le message de ``FileNotFoundError`` quand ``processed/`` n'a aucune des trois
tables."""


class ProcessedError(ValueError):
    """Les tables de ``processed/`` ne se relisent pas ensemble : l'une manque, est
    d'un autre format, ou leurs provenances diffèrent ; le message dit laquelle."""


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


def _remove(path: Path) -> None:
    if path.exists():
        shutil.rmtree(path)


def write_tables(data_dir: Path, tables: Tables) -> tuple[Path, Path, Path]:
    """Écrit ``processed/activites.parquet``, ``montees.parquet`` et
    ``variantes.parquet`` sous ``data_dir`` ; les rend. Dans cet ordre : supprime
    ``processed.nouveau/`` et ``processed.ancien/`` s'ils restent d'une écriture
    interrompue ; écrit les trois fichiers dans ``processed.nouveau/`` ; renomme
    l'ancien ``processed/`` (s'il existe) en ``processed.ancien/`` ; met
    ``processed.nouveau/`` à sa place ; supprime ``processed.ancien/``. Une écriture
    qui échoue supprime ``processed.nouveau/`` et laisse ``processed/`` intact ; si
    ``processed.nouveau/`` ne prend pas sa place, ``processed.ancien/`` reprend la
    sienne. ``processed/`` se régénère en entier : rien d'autre n'y vit."""
    target = data_dir / PROCESSED_DIR
    new = target.with_name(target.name + _NEW_SUFFIX)
    old = target.with_name(target.name + _OLD_SUFFIX)
    _remove(new)
    _remove(old)
    files = (
        (ACTIVITIES_FILE, tables.activities, ActivityRow),
        (CLIMBS_FILE, tables.climbs, ClimbRow),
        (VARIANTS_FILE, tables.variants, ClimbVariantRow),
    )
    try:
        new.mkdir(parents=True)
        for name, rows, cls in files:
            _write(_table(rows, cls, tables.provenance), new / name)
    except BaseException:
        _remove(new)
        raise
    if target.exists():
        target.rename(old)
    try:
        new.rename(target)
    except BaseException:
        if old.exists() and not target.exists():
            old.rename(target)
        raise
    _remove(old)
    activities, climbs, variants = (target / name for name, _, _ in files)
    return activities, climbs, variants


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
    if not path.exists():
        message = STALE_TABLES if path.name == VARIANTS_FILE else MISSING_TABLE
        raise ProcessedError(message.format(name=path.name))
    try:
        table = pq.read_table(path)
    except (pa.ArrowException, OSError) as error:
        raise ProcessedError(UNREADABLE_TABLE.format(name=path.name)) from error
    metadata = table.schema.metadata or {}
    try:
        provenance = decode_contract(
            ProcessedProvenance, json.loads(metadata[PROVENANCE_KEY])
        )
    except (KeyError, ValueError, CodecError, ContractError) as error:
        raise ProcessedError(
            STALE_TABLES.format(name=f"provenance lisible dans {path.name}")
        ) from error
    try:
        rows = [_row(record, cls) for record in table.to_pylist()]
    except (KeyError, TypeError, ValueError) as error:
        raise ProcessedError(UNREADABLE_TABLE.format(name=path.name)) from error
    return tuple(rows), provenance


def _row[T](record: dict[str, Any], cls: type[T]) -> T:
    values: dict[str, object] = {}
    for name, annotation in _columns(cls):
        if annotation is datetime:
            offset = timedelta(seconds=record[name + _OFFSET_SUFFIX])
            values[name] = record[name].replace(tzinfo=timezone(offset))
        else:
            values[name] = _value(annotation, record[name])
    return cls(**values)


def read_tables(data_dir: Path) -> Tables:
    """Relit les trois tables de ``data_dir/processed/``. :class:`ProcessedError` si
    ``variantes.parquet`` manque ou qu'une provenance est illisible (des tables
    d'avant AN1-2c), si une autre table manque, si une table ne se relit pas (abîmée),
    ou si leurs provenances diffèrent ; le message dit laquelle, par son nom.
    ``FileNotFoundError`` si ``processed/`` n'a aucune des trois tables (une
    régénération jamais lancée)."""
    folder = data_dir / PROCESSED_DIR
    names = (ACTIVITIES_FILE, CLIMBS_FILE, VARIANTS_FILE)
    if not any((folder / name).exists() for name in names):
        raise FileNotFoundError(NO_TABLES)
    activities, first = _rows(folder / ACTIVITIES_FILE, ActivityRow)
    climbs, second = _rows(folder / CLIMBS_FILE, ClimbRow)
    variants, third = _rows(folder / VARIANTS_FILE, ClimbVariantRow)
    if not first == second == third:
        raise ProcessedError(
            "Les trois tables de processed/ n'ont pas la même provenance."
        )
    return Tables(activities, climbs, variants, first)
