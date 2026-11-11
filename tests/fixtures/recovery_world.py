"""Le monde inventé de la page « récupération » (AN2-3, annexe C.1 du brief) : 140 jours
consécutifs de la table ``jours``, du 3 janvier au 21 mai 2000, et ses variantes de
tables. Aucune donnée réelle (règle 1).

Les refus viennent de ``days.admission_refusal`` ; les normales, segments, ruptures,
normales à cheval et jours incertains viennent de ``normals.measure_normals``
(paramètres par défaut) et ``normals.uncertain_days``, appelés sur les colonnes du
monde, comme la table le ferait : rien de tout cela ne s'écrit à la main.
"""

from __future__ import annotations

import dataclasses
import functools
import random
from collections.abc import Sequence
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

from fixtures.day_rows import absent_row, complete_row
from fixtures.processed import COMMIT, write_interim
from mountain_perf.analyse.athlete import DEFAULT_SETTINGS
from mountain_perf.analyse.days import VALUE_COLUMNS, admission_refusal
from mountain_perf.analyse.normals import (
    MEASURE_SPECS,
    NORMAL_PARAMETER_SPECS,
    NormalMeasure,
    measure_normals,
    uncertain_days,
)
from mountain_perf.analyse.tables import Tables, build_tables
from mountain_perf.schemas import NightState, RestingHrStatus
from mountain_perf.schemas.parameters import ParameterSet
from mountain_perf.schemas.processed import (
    JOURNAL_ABSENT,
    DayRow,
    JournalEventType,
)

FIRST_DAY = date(2000, 1, 3)
"""Le jour 0 du monde ; le jour 139 est le 21 mai 2000."""

DAY_COUNT = 140
ACQUIRED_AT = "2000-05-21T19:15:00+00:00"
"""L'instant d'acquisition de la provenance du monde."""

JOURNAL_SHA256 = "ab" * 32
"""L'empreinte inventée de ``journal.csv``."""

_SEED = 20000103
_ABSENT_DAYS = frozenset({87, 88, 89})
_PARTIAL_NIGHTS = frozenset({20, 128})
_CENTRES: dict[NormalMeasure, tuple[float, float]] = {
    NormalMeasure.HRV: (55.0, 6.0),
    NormalMeasure.RESTING_HR: (48.0, 2.5),
    NormalMeasure.MEASURED_SLEEP: (7.2, 0.7),
    NormalMeasure.NIGHT_STRESS: (22.0, 5.0),
    NormalMeasure.NIGHT_RESPIRATION: (14.5, 0.5),
    NormalMeasure.NIGHT_SPO2: (95.0, 1.2),
}
"""Le centre et l'écart de chaque mesure (le sommeil en heures)."""

_NO_VALUE: dict[int, tuple[NormalMeasure, ...]] = {
    115: (NormalMeasure.HRV,),
    116: (NormalMeasure.RESTING_HR,),
    117: (NormalMeasure.MEASURED_SLEEP, NormalMeasure.NIGHT_STRESS),
    118: (NormalMeasure.NIGHT_RESPIRATION,),
}
_SPO2_KEPT = frozenset({42, *range(56, 68), 69})
"""Les jours, dès le jour 40, où la SpO2 a une valeur."""

_JOURNAL: dict[int, tuple[JournalEventType, ...]] = {
    100: (JournalEventType.ILLNESS,),
    101: (JournalEventType.ILLNESS,),
    102: (JournalEventType.INJURY, JournalEventType.ILLNESS),
    103: (JournalEventType.INJURY,),
    104: (JournalEventType.INJURY,),
    110: (JournalEventType.RACE,),
    115: (JournalEventType.RACE,),
    **{d: (JournalEventType.ALTITUDE_STAY,) for d in range(120, 126)},
}
_FAMILY_COLUMNS = ("foot_elapsed_s", "mtb_elapsed_s", "ski_touring_elapsed_s")
_ACTIVITY_COLUMNS = (*_FAMILY_COLUMNS, "other_elapsed_s")


def day_of(index: int) -> date:
    """Le jour ``index`` du monde."""
    return FIRST_DAY + timedelta(days=index)


def default_normals() -> ParameterSet:
    """Les paramètres par défaut des normales."""
    return ParameterSet(NORMAL_PARAMETER_SPECS)


def _shifted(columns: dict[str, Any], days: int) -> None:
    """Décale de ``days`` jours chaque instant de la ligne."""
    for name, value in columns.items():
        if isinstance(value, datetime):
            columns[name] = value + timedelta(days=days)


def _value(rng: random.Random, measure: NormalMeasure) -> float:
    centre, spread = _CENTRES[measure]
    drawn = round(centre + rng.uniform(-2.0, 2.0) * spread, 1)
    if measure is NormalMeasure.MEASURED_SLEEP:
        return float(round(drawn * 3600))
    return drawn


def _activity(rng: random.Random, index: int) -> dict[str, Any]:
    """L'activité d'un jour : celle du tableau aux jours 130 à 133, sinon tirée."""
    columns: dict[str, Any] = {name: 0.0 for name in _ACTIVITY_COLUMNS}
    columns.update(
        activity_count=0,
        garmin_training_load=0.0,
        activities_without_load=0,
        other_activity_count=0,
        activities_without_elapsed=0,
    )
    if index == 130:
        columns.update(
            activity_count=1,
            foot_elapsed_s=3600.0,
            garmin_training_load=None,
            activities_without_load=1,
        )
    elif index == 131:
        columns.update(
            activity_count=2,
            foot_elapsed_s=3600.0,
            other_elapsed_s=3600.0,
            other_activity_count=1,
            garmin_training_load=40.0,
            activities_without_load=1,
        )
    elif index == 132:
        columns.update(
            activity_count=1,
            other_elapsed_s=5400.0,
            other_activity_count=1,
            garmin_training_load=30.0,
        )
    elif index == 133:
        columns.update(
            activity_count=1, garmin_training_load=20.0, activities_without_elapsed=1
        )
    elif index in _ABSENT_DAYS:
        pass
    elif index < 4:
        # Les quatre familles, une fois chacune, au début de la table.
        column = _ACTIVITY_COLUMNS[index]
        columns.update(
            activity_count=1,
            garmin_training_load=50.0,
            other_activity_count=1 if column == "other_elapsed_s" else 0,
        )
        columns[column] = 3600.0
    elif rng.random() < 0.4:
        column = rng.choice(_FAMILY_COLUMNS)
        columns[column] = float(rng.randrange(1800, 10800, 300))
        load = float(rng.randrange(10, 150))
        columns.update(activity_count=1, garmin_training_load=load)
        if rng.random() < 0.2:
            columns["other_elapsed_s"] = float(rng.randrange(900, 3600, 300))
            columns.update(
                activity_count=2,
                other_activity_count=1,
                garmin_training_load=load + float(rng.randrange(5, 40)),
            )
    return columns


def _columns(index: int, rng: random.Random, *, journal: bool) -> dict[str, Any]:
    """Les colonnes du jour ``index``, sans les refus ni les normales."""
    day = day_of(index)
    activity = _activity(rng, index)
    if index in _ABSENT_DAYS:
        columns = dataclasses.asdict(absent_row(day=day))
        columns.update(activity)
        return columns
    columns = dataclasses.asdict(complete_row())
    _shifted(columns, (day - date(2000, 1, 6)).days)
    columns.update(activity)
    columns["day"] = day
    columns["journal_types"] = _JOURNAL.get(index, ()) if journal else ()
    columns["device_ranks"] = (1, 2) if index == 30 else ((1,) if index < 90 else (2,))
    columns["sleep_version"] = 2 if index < 60 else 3
    for measure in NormalMeasure:
        columns[VALUE_COLUMNS[measure]] = _value(rng, measure)
    if index in _PARTIAL_NIGHTS:
        columns["night_state"] = NightState.PARTIAL
    if index == 95:
        columns["hrv_last_night_avg_ms"] = 0.0
    if index == 105:
        columns["night_short"] = True
        columns["night_short_absence"] = None
    if index == 108:
        columns["resting_hr_bpm"] = 140.0
        columns["resting_hr_status"] = RestingHrStatus.PROVISIONAL
    if index == 112:
        columns["night_shifted"] = True
        columns["night_shifted_absence"] = None
    for measure in _NO_VALUE.get(index, ()):
        columns[VALUE_COLUMNS[measure]] = None
    if index == 116:
        columns["resting_hr_status"] = RestingHrStatus.ABSENT
    if index >= 40 and index not in _SPO2_KEPT:
        columns["spo2_avg_sleep_percent"] = None
    if 120 <= index <= 125:
        for measure in NormalMeasure:
            value = columns[VALUE_COLUMNS[measure]]
            if value is not None:
                columns[VALUE_COLUMNS[measure]] = round(value * 0.9, 1)
    weekly = index >= 7 and not 60 <= index <= 62
    columns["hrv_weekly_avg_ms"] = round(rng.uniform(50.0, 60.0), 1) if weekly else None
    bounds = index >= 20 and not 60 <= index <= 62
    columns["hrv_baseline_balanced_low_ms"] = 49.0 if bounds else None
    columns["hrv_baseline_balanced_upper_ms"] = 64.0 if bounds else None
    return columns


def complete_world(table: Sequence[dict[str, Any]]) -> tuple[DayRow, ...]:
    """Les lignes de ``table`` (des colonnes, jour par jour, consécutifs) avec leurs
    refus, leurs jours incertains et leurs normales : ``admission_refusal``, puis
    ``uncertain_days`` et ``measure_normals`` sous les paramètres par défaut."""
    parameters = default_normals()
    rows = [dict(columns) for columns in table]
    for columns in rows:
        for measure in NormalMeasure:
            refusal = admission_refusal(measure, columns, exclude_altitude_stay=True)
            columns[f"{measure.value}_refusal"] = refusal
            columns[f"{measure.value}_admitted"] = refusal is None
    ranks = [columns["device_ranks"] for columns in rows]
    for columns, uncertain in zip(rows, uncertain_days(ranks), strict=True):
        columns["uncertain_device"] = uncertain
    for measure in NormalMeasure:
        spec = MEASURE_SPECS[measure]
        versions = None if spec.version is None else [c[spec.version] for c in rows]
        normals = measure_normals(
            measure,
            [c[VALUE_COLUMNS[measure]] for c in rows],
            [c[f"{measure.value}_admitted"] for c in rows],
            ranks,
            versions,
            parameters,
        )
        unit = _unit(measure)
        for columns, normal in zip(rows, normals, strict=True):
            prefix = measure.value
            columns.update(
                {
                    f"{prefix}_normal{unit}": normal.normal,
                    f"{prefix}_range_low{unit}": normal.range_low,
                    f"{prefix}_range_high{unit}": normal.range_high,
                    f"{prefix}_admitted_days": normal.admitted_days,
                    f"{prefix}_normal_absence": normal.absence,
                    f"{prefix}_segment": normal.segment,
                    f"{prefix}_rupture": normal.rupture,
                    f"{prefix}_normal_straddles": normal.straddles,
                }
            )
            if measure is NormalMeasure.HRV:
                columns["hrv_log_median"] = normal.log_median
                columns["hrv_log_dispersion"] = normal.log_dispersion
            else:
                columns[f"{prefix}_dispersion{unit}"] = normal.dispersion
    return tuple(DayRow(**columns) for columns in rows)


def _unit(measure: NormalMeasure) -> str:
    """Le suffixe d'unité des colonnes de normale de ``measure``, lu sur ``DayRow``."""
    prefix = f"{measure.value}_range_low"
    return next(
        f.name[len(prefix) :]
        for f in dataclasses.fields(DayRow)
        if f.name.startswith(prefix)
    )


@functools.cache
def world_columns(*, journal: bool = True) -> tuple[dict[str, Any], ...]:
    """Les colonnes des 140 jours, sans refus ni normales (une copie à chaque appel
    de :func:`world_rows` ; ne pas modifier ce tuple)."""
    rng = random.Random(_SEED)
    return tuple(_columns(i, rng, journal=journal) for i in range(DAY_COUNT))


@functools.cache
def world_rows(*, journal: bool = True) -> tuple[DayRow, ...]:
    """Les 140 lignes du monde ; sans journal, aucun type ni refus du journal."""
    return complete_world(world_columns(journal=journal))


def changed_world(
    changes: dict[int, dict[str, Any]], *, journal: bool = True
) -> tuple[DayRow, ...]:
    """Le monde dont les colonnes des jours de ``changes`` sont changées **avant** les
    refus et les normales, recalculés."""
    table = [dict(columns) for columns in world_columns(journal=journal)]
    for index, update in changes.items():
        table[index].update(update)
    return complete_world(table)


def base_tables(folder: Path) -> Tables:
    """Les tables de base : ``build_tables`` sur ``write_interim`` sous ``folder``."""
    write_interim(folder)
    return build_tables(folder, DEFAULT_SETTINGS, commit=COMMIT)


def world_tables(
    base: Tables,
    *,
    rows: Sequence[DayRow] | None = None,
    journal: bool = True,
    parameters: dict[str, float] | None = None,
) -> Tables:
    """Les tables du monde : ``base`` avec les lignes du monde (ou ``rows``), sa
    provenance à ``ACQUIRED_AT``, ``day_count`` au nombre de lignes, l'empreinte du
    journal (``"absent"`` sans journal), ses paramètres changés par ``parameters``."""
    days = tuple(world_rows(journal=journal) if rows is None else rows)
    values = dict(base.provenance.parameters)
    values.update(parameters or {})
    provenance = dataclasses.replace(
        base.provenance,
        acquired_at=ACQUIRED_AT,
        day_count=len(days),
        journal_sha256=JOURNAL_SHA256 if journal else JOURNAL_ABSENT,
        parameters=tuple(sorted(values.items())),
    )
    return dataclasses.replace(base, days=days, provenance=provenance)


def write_world(folder: Path, tables: Tables) -> None:
    """Écrit ``tables`` sous ``folder/processed/`` (pyarrow, importé ici seulement)."""
    from mountain_perf.analyse.parquet import write_tables

    write_tables(folder, tables)
