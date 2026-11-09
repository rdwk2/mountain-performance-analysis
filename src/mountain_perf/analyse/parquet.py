"""Écriture et relecture des tables de ``processed/`` en Parquet (AN1-2b, AN1-2c,
AN2-2, ``docs/decisions/0014``) : le seul module du projet qui importe pyarrow (extra
``analyse``, ``docs/decisions/0011``).

Chaque contrat se convertit d'après ses champs, colonne par colonne :

- texte et énumérations : ``string`` ; flottants : ``float64`` ; entiers : ``int64`` ;
  booléens : ``bool`` ; dates (``day`` de ``jours``) : ``date32`` ; toute colonne
  accepte ``null`` : c'est le contrat qui dit quel champ peut manquer ;
- listes : par convention, ``list<float64>`` ; ``flags`` et ``journal_types``,
  ``list<string>`` ; ``device_ranks`` et ``body_battery_series_versions``,
  ``list<int64>`` ;
- un instant (``start_time``, ``local_start_time``, jamais absents ; les instants de
  ``jours``, facultatifs) : deux colonnes, l'heure murale locale sans fuseau
  (``timestamp[us]``) et son décalage en secondes (``<nom>_utc_offset_s``,
  ``int32``) ; un instant absent a ses deux colonnes nulles, et une table où l'une
  seulement des deux est nulle ne se relit pas, ni une table où un instant jamais
  absent a ses deux colonnes nulles.

La provenance (:class:`~mountain_perf.schemas.processed.ProcessedProvenance`) s'écrit
dans les métadonnées de chaque fichier, sous la clé ``mountain_perf.provenance``, par
le codec commun. Les quatre fichiers s'écrivent dans ``processed.nouveau/``, qui prend
ensuite la place de ``processed/`` par un échange de dossier (:func:`write_tables`) :
les tables d'avant restent tant que les quatre nouvelles ne sont pas écrites, et
``processed/`` porte toujours quatre tables d'une même écriture. :func:`read_tables`
refuse quatre tables de provenances différentes, des tables d'avant AN1-2c ou d'avant
AN2-2, et une table qui manque ou qui ne se relit pas. La quatrième table ne change
rien aux trois autres : leurs colonnes, dans leur ordre, et leurs types sont ceux
d'avant AN2-2 (un schéma figé, que les tests gardent). Leurs octets, eux, changent :
la provenance, dans les métadonnées, a des champs neufs. La comparaison se fait une
fois, à la PR, contre ``main`` : pour le même ``interim/`` synthétique, les trois
tables écrites par la branche et par ``main`` ont le même schéma Arrow (hors des
métadonnées) et les mêmes lignes, et leur provenance ne diffère que par ses quatre
champs neufs, ses paramètres neufs (``days.<nom>``, ``normal.<nom>``) et le commit ;
le contrôle réel de la PR la refait sur le réel.
"""

from __future__ import annotations

import dataclasses
import json
import shutil
import typing
from collections.abc import Sequence
from datetime import date, datetime, timedelta, timezone
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
    DayRow,
    ProcessedProvenance,
)
from mountain_perf.validation import ContractError

PROCESSED_DIR = Path("processed")
"""Le dossier des tables, sous ``MPA_DATA_DIR``."""

ACTIVITIES_FILE = "activites.parquet"
CLIMBS_FILE = "montees.parquet"
VARIANTS_FILE = "variantes.parquet"
DAYS_FILE = "jours.parquet"
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
"""Le message de :class:`ProcessedError` pour une table qui manque, sauf
``variantes.parquet`` (``STALE_TABLES``) : ``activites.parquet``, ``montees.parquet``,
ou ``jours.parquet`` seul manquant, à côté de tables d'AN2-2 ; un ``processed/`` d'avant
AN2-2 se refuse avant, à sa première table, par sa provenance
(``STALE_DAYS_PROVENANCE``).
"""

UNREADABLE_TABLE = "{name} ne se relit pas : relancer just process"
"""Le message de :class:`ProcessedError` pour une table abîmée."""

NO_TABLES = "aucune table dans processed/ : lancer just process"
"""Le message de ``FileNotFoundError`` quand ``processed/`` n'a aucune des quatre
tables.
"""

STALE_DAYS_PROVENANCE = (
    "la provenance de {name} date d'avant AN2-2 (sans {fields}) : relancer just process"
)
"""Le message de :class:`ProcessedError` pour une table dont la provenance n'a pas
les champs d'AN2-2 (``DAYS_PROVENANCE_FIELDS``) : ``{fields}``, ceux qui manquent,
dans leur ordre. Seulement pour une provenance qui a tous les champs d'avant AN2-2 :
à qui manque aussi un champ plus ancien, c'est ``STALE_TABLES``.
"""

DAYS_PROVENANCE_FIELDS = (
    "interim_days_sha256",
    "journal_sha256",
    "day_count",
    "acquired_at",
)
"""Les champs de la provenance neufs avec AN2-2, les quatre derniers de
:class:`~mountain_perf.schemas.processed.ProcessedProvenance`.
"""

MIXED_PROVENANCE = "Les quatre tables de processed/ n'ont pas la même provenance."
"""Le message de :class:`ProcessedError` pour des tables de provenances
différentes.
"""


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
    if annotation is date:
        return pa.date32()
    if annotation is int:
        return pa.int64()
    if annotation is float:
        return pa.float64()
    if typing.get_origin(annotation) is tuple:
        (item,) = {a for a in typing.get_args(annotation) if a is not Ellipsis}
        return pa.list_(_arrow_type(item))
    raise TypeError(f"type de colonne non pris en charge : {annotation!r}")


def _columns(cls: type) -> list[tuple[str, object, bool]]:
    """Chaque champ de ``cls`` : nom, type sans ``None``, s'il est facultatif."""
    hints = typing.get_type_hints(cls)
    return [
        (f.name, _base(hints[f.name]), type(None) in typing.get_args(hints[f.name]))
        for f in dataclasses.fields(cls)
    ]


def _plain(value: object) -> object:
    if isinstance(value, StrEnum):
        return value.value
    if isinstance(value, tuple):
        return [_plain(v) for v in value]
    return value


def _table(rows: Sequence[object], cls: type, provenance: ProcessedProvenance) -> Any:
    arrays: dict[str, Any] = {}
    fields: list[Any] = []
    for name, annotation, _ in _columns(cls):
        values = [getattr(row, name) for row in rows]
        if annotation is datetime:
            local = [None if v is None else v.replace(tzinfo=None) for v in values]
            offsets = [
                None if v is None else int(v.utcoffset().total_seconds())
                for v in values
            ]
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


def write_tables(data_dir: Path, tables: Tables) -> tuple[Path, Path, Path, Path]:
    """Écrit ``processed/activites.parquet``, ``montees.parquet``,
    ``variantes.parquet`` et ``jours.parquet`` sous ``data_dir`` ; les rend, dans cet
    ordre. Dans cet ordre : supprime ``processed.nouveau/`` et ``processed.ancien/``
    s'ils restent d'une écriture interrompue ; écrit les quatre fichiers, dans l'ordre
    de leur rendu, dans ``processed.nouveau/`` ; renomme
    l'ancien ``processed/`` (s'il existe) en ``processed.ancien/`` ; met
    ``processed.nouveau/`` à sa place ; supprime ``processed.ancien/``. Une écriture
    qui échoue supprime ``processed.nouveau/`` et laisse ``processed/`` intact ; si
    ``processed.nouveau/`` ne prend pas sa place, ``processed.ancien/`` reprend la
    sienne. ``processed/`` se régénère en entier : rien d'autre n'y vit.
    """
    target = data_dir / PROCESSED_DIR
    new = target.with_name(target.name + _NEW_SUFFIX)
    old = target.with_name(target.name + _OLD_SUFFIX)
    _remove(new)
    _remove(old)
    files = (
        (ACTIVITIES_FILE, tables.activities, ActivityRow),
        (CLIMBS_FILE, tables.climbs, ClimbRow),
        (VARIANTS_FILE, tables.variants, ClimbVariantRow),
        (DAYS_FILE, tables.days, DayRow),
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
    activities, climbs, variants, days = (target / name for name, _, _ in files)
    return activities, climbs, variants, days


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


def _missing_days_fields(document: object) -> tuple[str, ...]:
    """Les champs d'AN2-2 qui manquent à une provenance qui a tous ceux d'avant ; aucun
    pour tout autre document (une provenance plus ancienne, ou qui n'est pas un
    objet)."""
    if not isinstance(document, dict):
        return ()
    older = (
        f.name
        for f in dataclasses.fields(ProcessedProvenance)
        if f.name not in DAYS_PROVENANCE_FIELDS
    )
    if any(name not in document for name in older):
        return ()
    return tuple(name for name in DAYS_PROVENANCE_FIELDS if name not in document)


def _rows[T](path: Path, cls: type[T]) -> tuple[tuple[T, ...], ProcessedProvenance]:
    if not path.exists():
        message = STALE_TABLES if path.name == VARIANTS_FILE else MISSING_TABLE
        raise ProcessedError(message.format(name=path.name))
    try:
        table = pq.read_table(path)
    except (pa.ArrowException, OSError) as error:
        raise ProcessedError(UNREADABLE_TABLE.format(name=path.name)) from error
    metadata = table.schema.metadata or {}
    stale = STALE_TABLES.format(name=f"provenance lisible dans {path.name}")
    try:
        document = json.loads(metadata[PROVENANCE_KEY])
    except (KeyError, ValueError) as error:
        raise ProcessedError(stale) from error
    missing = _missing_days_fields(document)
    if missing:
        raise ProcessedError(
            STALE_DAYS_PROVENANCE.format(name=path.name, fields=", ".join(missing))
        )
    try:
        provenance = decode_contract(ProcessedProvenance, document)
    except (TypeError, ValueError, CodecError, ContractError) as error:
        raise ProcessedError(stale) from error
    try:
        rows = [_row(record, cls) for record in table.to_pylist()]
    except (KeyError, TypeError, ValueError) as error:
        raise ProcessedError(UNREADABLE_TABLE.format(name=path.name)) from error
    return tuple(rows), provenance


def _instant(
    wall: datetime | None, offset: int | None, optional: bool
) -> datetime | None:
    """L'instant de ses deux colonnes : nulles ensemble pour un instant facultatif
    absent, sinon ``ValueError``."""
    if wall is None and offset is None:
        if optional:
            return None
        raise ValueError("un instant obligatoire aux deux colonnes nulles")
    if wall is None or offset is None:
        raise ValueError("une seule des deux colonnes d'un instant est nulle")
    return wall.replace(tzinfo=timezone(timedelta(seconds=offset)))


def _row[T](record: dict[str, Any], cls: type[T]) -> T:
    values: dict[str, object] = {}
    for name, annotation, optional in _columns(cls):
        if annotation is datetime:
            values[name] = _instant(
                record[name], record[name + _OFFSET_SUFFIX], optional
            )
        else:
            values[name] = _value(annotation, record[name])
    return cls(**values)


def read_tables(data_dir: Path) -> Tables:
    """Relit les quatre tables de ``data_dir/processed/``, une à une dans l'ordre
    d'écriture (``activites``, ``montees``, ``variantes``, ``jours``) ; le résumé de
    ``jours``, qui ne s'écrit pas, est absent (``day_summary`` vaut ``None``).

    :class:`ProcessedError`, à la première table qui fait défaut, si elle manque
    (``variantes.parquet`` : des tables d'avant AN1-2c, ``STALE_TABLES`` ; une autre,
    ``jours.parquet`` compris : ``MISSING_TABLE``), si elle ne se relit pas (abîmée,
    une colonne d'instant nulle sans l'autre, ou les deux d'un instant jamais absent :
    ``UNREADABLE_TABLE``), si sa provenance n'a pas les champs d'AN2-2
    (``STALE_DAYS_PROVENANCE``, qui les nomme) ou ne se relit pas (``STALE_TABLES``) ;
    puis si leurs provenances diffèrent (``MIXED_PROVENANCE``).
    ``FileNotFoundError`` (``NO_TABLES``) si ``processed/`` n'a aucune des quatre
    tables (une régénération jamais lancée).
    """
    folder = data_dir / PROCESSED_DIR
    names = (ACTIVITIES_FILE, CLIMBS_FILE, VARIANTS_FILE, DAYS_FILE)
    if not any((folder / name).exists() for name in names):
        raise FileNotFoundError(NO_TABLES)
    activities, first = _rows(folder / ACTIVITIES_FILE, ActivityRow)
    climbs, second = _rows(folder / CLIMBS_FILE, ClimbRow)
    variants, third = _rows(folder / VARIANTS_FILE, ClimbVariantRow)
    days, fourth = _rows(folder / DAYS_FILE, DayRow)
    if not first == second == third == fourth:
        raise ProcessedError(MIXED_PROVENANCE)
    return Tables(activities, climbs, variants, first, days, None)
