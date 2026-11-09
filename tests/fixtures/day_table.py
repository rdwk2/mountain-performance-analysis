"""Des jours, un index, un journal et la table ``jours`` pour ``day_rows`` (AN2-2), sur
les constructeurs de ``tests/fixtures/days.py`` ; aucune donnée réelle."""

from __future__ import annotations

import dataclasses
from collections.abc import Collection, Sequence
from datetime import date, datetime, timedelta, timezone
from typing import Any

from fixtures.days import EMPTY_HISTORY, day_record, night, source
from mountain_perf.analyse.days import (
    DAY_VIEW_PARAMETER_SPECS,
    DEFAULT_DAY_DEFINITION,
    DayDefinition,
    DayTable,
    day_rows,
)
from mountain_perf.analyse.journal import Journal, JournalEvent
from mountain_perf.analyse.normals import NORMAL_PARAMETER_SPECS
from mountain_perf.schemas import (
    ActivityIndex,
    BodyBatterySeries,
    DayFamily,
    DayRecord,
    IndexedActivity,
    JournalEventType,
    Night,
    ParameterSet,
    TrainingStatusHistory,
)
from mountain_perf.schemas.processed import DayRow
from test_ingest_interim import INDEX_SOURCE
from test_schemas_interim import entry

FIRST_DAY = date(2000, 1, 1)
"""Le premier jour inventé des suites, un samedi."""

PLUS1 = timezone(timedelta(hours=1))
PLUS2 = timezone(timedelta(hours=2))

ABSENT_JOURNAL = Journal((), None)
"""Le journal d'un fichier absent."""


def nth(n: int, first: date = FIRST_DAY) -> date:
    """Le jour ``n`` après ``first`` (``n`` peut être négatif)."""
    return first + timedelta(days=n)


def jan(day: int) -> date:
    """Le jour ``day`` de janvier 2000."""
    return date(2000, 1, day)


def complete_days(
    count: int,
    first: date = FIRST_DAY,
    skip: Collection[int] = (),
    **changes: Any,
) -> tuple[DayRecord, ...]:
    """Des documents complets de jours consécutifs, sauf les rangs ``skip``."""
    return tuple(
        day_record(nth(i, first), **changes) for i in range(count) if i not in skip
    )


def days_with(
    count: int,
    position: int,
    first: date = FIRST_DAY,
    **changes: Any,
) -> tuple[DayRecord, ...]:
    """Des documents complets dont celui du rang ``position`` a des champs remplacés."""
    return tuple(
        day_record(nth(i, first), **(changes if i == position else {}))
        for i in range(count)
    )


def index_entry(ref: str, start: datetime, **changes: Any) -> IndexedActivity:
    """Une entrée de l'index sans enregistrement."""
    return entry(
        source=INDEX_SOURCE,
        activity_ref=ref,
        start_time=start,
        has_recording=False,
        **changes,
    )


def index_of(entries: Sequence[IndexedActivity]) -> ActivityIndex:
    """L'index de ces entrées, triées par départ puis par identifiant."""
    ordered = sorted(entries, key=lambda e: (e.start_time, e.activity_ref))
    return ActivityIndex(tuple(ordered), (INDEX_SOURCE,))


def journal_of(*events: tuple[date, date, JournalEventType]) -> Journal:
    """Un journal de ces événements, numérotés comme les lignes d'un fichier."""
    return Journal(
        tuple(
            JournalEvent(start, end, event_type, line)
            for line, (start, end, event_type) in enumerate(events, start=2)
        ),
        "0" * 64,
    )


def definition(
    views: dict[str, float] | None = None, normals: dict[str, float] | None = None
) -> DayDefinition:
    """Une définition aux seuils et paramètres donnés, les autres à leur défaut."""
    return DayDefinition(
        ParameterSet(DAY_VIEW_PARAMETER_SPECS, views or {}),
        ParameterSet(NORMAL_PARAMETER_SPECS, normals or {}),
    )


def table(
    days: Sequence[DayRecord],
    history: TrainingStatusHistory = EMPTY_HISTORY,
    entries: Sequence[IndexedActivity] = (),
    journal: Journal = ABSENT_JOURNAL,
    day_definition: DayDefinition = DEFAULT_DAY_DEFINITION,
) -> DayTable:
    """La table ``jours`` de ces documents."""
    return day_rows(tuple(days), history, index_of(entries), journal, day_definition)


def row_of(day_table: DayTable, day: date) -> DayRow:
    """La ligne de ``day``, qui existe exactement une fois."""
    (row,) = (row for row in day_table.rows if row.day == day)
    return row


def body_battery(
    day: date, times: Sequence[float], levels: Sequence[int]
) -> BodyBatterySeries:
    """Une série de Body Battery de nuit, sans statut."""
    return BodyBatterySeries(
        tuple(times),
        tuple(levels),
        (None,) * len(times),
        source(DayFamily.SLEEP, day),
    )


def night_with(day: date, series: BodyBatterySeries | None, **changes: Any) -> Night:
    """La nuit par défaut de ``day``, sa série de Body Battery remplacée ou retirée."""
    base = night(day, **changes)
    return dataclasses.replace(
        base, series=dataclasses.replace(base.series, body_battery=series)
    )


def dense(
    day: date, count: int, step_s: float = 180.0, level: int = 50
) -> BodyBatterySeries:
    """Une série dense de ``count`` points depuis le début de la nuit."""
    return body_battery(day, [i * step_s for i in range(count)], [level] * count)
