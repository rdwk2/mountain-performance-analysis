"""Des tables synthétiques pour Q2 (AN3-3b) : activités, montées et jours inventés, sur
les constructeurs de ``fixtures/figure.py`` et ``fixtures/day_rows.py``. Les tailles
sont celles des cas du brief, sans rapport avec un effectif réel. Aucune donnée réelle
(règle 1)."""

from __future__ import annotations

import dataclasses
from collections.abc import Sequence
from datetime import date, datetime, timedelta, timezone
from typing import Any

from fixtures.day_rows import complete_row
from fixtures.figure import activity, climb, tables_of
from mountain_perf.analyse.tables import Tables
from mountain_perf.schemas.days import RestingHrStatus
from mountain_perf.schemas.processed import (
    ActivityRow,
    AdmissionRefusal,
    ClimbFlag,
    ClimbRegime,
    ClimbRow,
    DayRow,
    JournalEventType,
)

PLUS1 = timezone(timedelta(hours=1))
PLUS2 = timezone(timedelta(hours=2))


def at(day: date, hour: int = 9, minute: int = 0, tz: timezone = PLUS1) -> datetime:
    """L'instant ``hour:minute`` de ``day``, au décalage ``tz``."""
    return datetime(day.year, day.month, day.day, hour, minute, tzinfo=tz)


def q2_activity(
    ref: str,
    when: datetime,
    *,
    product: int | None = 1,
    manufacturer: str | None = "garmin",
    sessions: int | None = 1,
) -> ActivityRow:
    """Une activité de ``product`` (``garmin`` par défaut), partie à ``when``."""
    return activity(
        ref,
        when,
        device_manufacturer=manufacturer,
        device_product=product,
        session_count=sessions,
    )


def q2_climb(
    ref: str,
    when: datetime,
    *,
    offset_s: float = 0.0,
    gain_m: float = 300.0,
    moving_s: float = 1000.0,
    regime: ClimbRegime = ClimbRegime.LONG_CLIMB,
    flags: Sequence[ClimbFlag] = (),
    h: float | None = 150.0,
    coverage: float = 1.0,
    **changes: Any,
) -> ClimbRow:
    """Une montée de l'activité ``ref`` (partie à ``when``), qui commence ``offset_s``
    après son départ ; ``h`` et ``coverage`` : la FC décalée du principal ;
    ``changes`` remplace d'autres champs."""
    fields: dict[str, Any] = {
        "lagged_moving_heart_rate_bpm": h,
        "lagged_moving_heart_rate_coverage": coverage if h is not None else 0.0,
    }
    fields.update(changes)
    return climb(
        ref,
        when,
        offset_s,
        offset_s + moving_s,
        gain_m,
        moving_s,
        regime=regime,
        flags=flags,
        **fields,
    )


def q2_day_row(
    day: date,
    *,
    resting: float | None = 55.0,
    status: RestingHrStatus = RestingHrStatus.VALID,
    admitted: bool | None = None,
    ranks: tuple[int, ...] = (1,),
    uncertain: bool | None = None,
    journal: Sequence[JournalEventType] = (),
    midpoint: datetime | None = None,
    tz: timezone = PLUS1,
) -> DayRow:
    """La ligne ``complete`` du jour ``day`` : fenêtre à minuit au décalage du milieu
    de la demi-heure la plus basse (``tz`` sans lui), ``resting`` et son statut ;
    ``admitted`` vaut par défaut ``status is VALID`` et aucun type excluant ;
    ``uncertain`` vaut par défaut « au moins deux rangs »."""
    offset = midpoint.tzinfo if midpoint is not None else tz
    assert isinstance(offset, timezone)
    start = datetime(day.year, day.month, day.day, tzinfo=offset)
    excluding = {
        JournalEventType.ILLNESS,
        JournalEventType.INJURY,
        JournalEventType.ALTITUDE_STAY,
    }
    if admitted is None:
        admitted = status is RestingHrStatus.VALID and not (set(journal) & excluding)
    refusal: AdmissionRefusal | None = None
    if not admitted:
        if JournalEventType.ILLNESS in journal:
            refusal = AdmissionRefusal.ILLNESS
        elif JournalEventType.INJURY in journal:
            refusal = AdmissionRefusal.INJURY
        elif JournalEventType.ALTITUDE_STAY in journal:
            refusal = AdmissionRefusal.ALTITUDE_STAY
        else:
            refusal = AdmissionRefusal.INVALID_VALUE
    return complete_row(
        day=day,
        window_start=start,
        data_end=start + timedelta(hours=24, minutes=30),
        lowest_heart_rate_window_midpoint=midpoint,
        resting_hr_bpm=resting,
        resting_hr_status=status,
        resting_hr_admitted=admitted,
        resting_hr_refusal=refusal,
        device_ranks=ranks,
        uncertain_device=len(ranks) >= 2 if uncertain is None else uncertain,
        journal_types=tuple(sorted(set(journal))),
    )


def day_range(first: date, count: int, **changes: Any) -> list[DayRow]:
    """``count`` lignes de jours consécutifs depuis ``first``, toutes de ``changes``."""
    return [q2_day_row(first + timedelta(days=i), **changes) for i in range(count)]


def q2_tables(
    activities: Sequence[ActivityRow],
    climbs: Sequence[ClimbRow],
    days: Sequence[DayRow] = (),
    *,
    v_ref: float = 0.25,
) -> Tables:
    """Les tables de ces lignes, ``V_ref`` des tables à ``v_ref``."""
    tables = tables_of(activities, climbs, variants=[])
    provenance = dataclasses.replace(
        tables.provenance,
        reference_vertical_speed_ms=v_ref,
        day_count=len(days),
    )
    return dataclasses.replace(
        tables,
        days=tuple(sorted(days, key=lambda row: row.day)),
        provenance=provenance,
    )
