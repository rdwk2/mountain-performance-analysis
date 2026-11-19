"""Des tables synthétiques pour Q2 (AN3-3b) : activités, montées et jours inventés, sur
les constructeurs de ``fixtures/figure.py`` et ``fixtures/day_rows.py``. Les tailles
sont celles des cas du brief, sans rapport avec un effectif réel. Aucune donnée réelle
(règle 1)."""

from __future__ import annotations

import dataclasses
import math
import random
from collections.abc import Sequence
from datetime import date, datetime, timedelta, timezone
from typing import Any

from fixtures.day_rows import complete_row
from fixtures.figure import activity, climb, tables_of
from mountain_perf.analyse.q2.data import Period, Q2Climb, Q2Day, Q2Motif
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
    grade: float | None = None,
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
    row = climb(
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
    return row if grade is None else dataclasses.replace(row, grade=grade)


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


WORLD_START = date(2025, 3, 3)
"""Le premier jour d'activité possible de ``small_world``."""
ROUTES = ((45.0, 6.0), (45.5, 6.5))
"""Les départs des deux parcours de ``small_world``."""


def _world_climb(
    rnd: random.Random,
    ref: str,
    when: datetime,
    t: int,
    k: int,
    *,
    regime: ClimbRegime,
    b: float,
    route: tuple[float, float] | None,
    day_effect: float,
) -> ClimbRow:
    """Une montée de ``small_world`` : ``ln v`` suit un modèle connu à ``b`` imposé."""
    if regime is ClimbRegime.SHORT_CLIMB:
        gain = rnd.uniform(60.0, 150.0)
        base = -1.6
    else:
        gain = (
            rnd.uniform(600.0, 900.0)
            if route is not None
            else rnd.uniform(300.0, 500.0)
        )
        base = -1.0
    h = 140.0 + rnd.gauss(0.0, 6.0)
    log_v = (
        base
        + b * t
        + 0.01 * (h - 140.0)
        - 0.1 * (math.log(gain) - 6.0)
        + day_effect
        + rnd.gauss(0.0, 0.03)
    )
    speed = math.exp(log_v)
    if route is None:
        lat, lon = 46.0 + rnd.uniform(0.0, 1.0), 7.0 + rnd.uniform(0.0, 1.0)
    else:
        lat, lon = route[0] + rnd.uniform(0.0, 0.0002), route[1]
    return q2_climb(
        ref,
        when,
        offset_s=3000.0 * k + rnd.uniform(0.0, 600.0),
        gain_m=gain,
        moving_s=gain / speed,
        regime=regime,
        h=h,
        grade=rnd.uniform(0.1, 0.3),
        moving_mean_elevation_m=rnd.uniform(800.0, 2500.0),
        preceding_ascent_m=rnd.uniform(0.0, 800.0),
        preceding_descent_m=rnd.uniform(0.0, 600.0),
        unlagged_moving_heart_rate_bpm=h - 1.0 + rnd.gauss(0.0, 1.0),
        lagged_second_half_heart_rate_bpm=h + 3.0 + rnd.gauss(0.0, 1.0),
        lagged_elapsed_heart_rate_bpm=h - 0.5 + rnd.gauss(0.0, 1.0),
        moving_or_undetermined_vertical_speed_ms=speed * rnd.uniform(0.9, 1.0),
        start_latitude_deg=lat,
        start_longitude_deg=lon,
        end_latitude_deg=lat + 0.03,
        end_longitude_deg=lon,
        stable=rnd.random() > 0.2,
    )


def small_world(
    seed: int,
    *,
    days: int = 30,
    span: int = 200,
    b: float = 0.0002,
    regimes: Sequence[ClimbRegime] = (
        ClimbRegime.LONG_CLIMB,
        ClimbRegime.SHORT_CLIMB,
    ),
) -> Tables:
    """Un monde d'estimation inventé : pour chaque régime de ``regimes``, ``days``
    journées sur ``span`` jours, de deux ou trois montées dont ``ln v`` suit un modèle
    connu (pente ``b`` en log par jour, FC, gain, effet de journée, bruit) ; la plus
    grande montée de chaque journée longue suit l'un de deux parcours ; une ligne de
    ``jours`` par jour, de 30 jours avant le premier à un jour après le dernier."""
    rnd = random.Random(seed)
    plan: dict[int, list[ClimbRegime]] = {}
    for regime in regimes:
        for offset in rnd.sample(range(span), days):
            plan.setdefault(offset, []).append(regime)
    activities: list[ActivityRow] = []
    climbs: list[ClimbRow] = []
    for offset in sorted(plan):
        day = WORLD_START + timedelta(days=offset)
        ref = f"w{offset:03d}"
        when = at(day, 7)
        activities.append(q2_activity(ref, when))
        k = 0
        for regime in plan[offset]:
            effect = rnd.gauss(0.0, 0.03)
            for i in range(rnd.choice((2, 3))):
                route = (
                    ROUTES[offset % 2]
                    if regime is ClimbRegime.LONG_CLIMB and i == 0
                    else None
                )
                climbs.append(
                    _world_climb(
                        rnd,
                        ref,
                        when,
                        offset,
                        k,
                        regime=regime,
                        b=b,
                        route=route,
                        day_effect=effect,
                    )
                )
                k += 1
    first = WORLD_START - timedelta(days=30)
    count = (WORLD_START + timedelta(days=span + 1) - first).days
    rows = [
        q2_day_row(
            first + timedelta(days=i), resting=round(50.0 + rnd.gauss(0.0, 1.5), 1)
        )
        for i in range(count)
    ]
    return q2_tables(activities, climbs, rows)


def make_climb(
    *,
    when: datetime | None = None,
    y: float = -1.0,
    h: float = 150.0,
    lat: float = 45.0,
    gain_m: float = 300.0,
    log_gain: float | None = None,
    grade: float = 0.15,
    elevation_m: float = 1500.0,
    d_plus: float = 0.0,
    d_minus: float = 0.0,
    variants: tuple[float | None, float | None, float | None] | None = None,
) -> Q2Climb:
    """Une montée de Q2 écrite à la main (sans passer par les tables)."""
    moment = when or at(date(2025, 1, 1), 9)
    return Q2Climb(
        activity_ref="m1",
        local_start_time=moment,
        gain_m=gain_m,
        y=y,
        y_s12=y,
        heart_rates=(h, *(variants or (h, h, h))),
        log_gain=math.log(gain_m) if log_gain is None else log_gain,
        grade=grade,
        elevation_m=elevation_m,
        preceding_ascent_m=d_plus,
        preceding_descent_m=d_minus,
        preceding_moving_s=0.0,
        hour=moment.hour + moment.minute / 60,
        off_moving=0.0,
        stable=True,
        slow_moving=False,
        start=(lat, 6.0),
        end=(lat + 0.03, 6.0),
    )


def make_day(
    day: date,
    climbs: Sequence[Q2Climb],
    *,
    e_s: float | None = 0.0,
    r: float | None = 50.0,
    step5: Q2Motif | None = None,
    step6: Q2Motif | None = None,
) -> Q2Day:
    """Une journée de Q2 écrite à la main ; ``e_s`` n'est gardé que sans motif
    d'étape 5, ``r`` que sans motif d'étape 6."""
    r_value = r if step6 is None else None
    return Q2Day(
        day=day,
        period=Period.ALL,
        climbs=tuple(climbs),
        activity_count=1,
        step5=step5,
        e_s=e_s if step5 is None else None,
        r=r_value,
        step6=step6,
        reserve=tuple(
            Q2Motif.MS_RESERVE if r_value is not None and c.h - r_value <= 0 else None
            for c in climbs
        ),
    )


RICH_START = date(2025, 3, 3)
"""Le premier jour d'activité possible de ``rich_world``."""
RICH_EXCLUDED = (date(2025, 4, 16), date(2025, 9, 10))
"""Les deux journées de ``rich_world`` exclues à l'étape 5 (FC de repos
``provisional``)."""


def rich_world(
    seed: int, *, days: int = 45, span: int = 300, b: float = 0.0004
) -> Tables:
    """Un monde d'estimation inventé, plus riche que :func:`small_world` (correctifs
    de la PR #52) : ``days`` journées de montées longues sur ``span`` jours, de trois
    montées chacune, dont la FC varie d'une journée à l'autre et pèse fort sur la VAM
    (``ln v`` croît de 0,02 par battement) : l'inverse est bien identifiée. La plus
    grande montée de chaque journée suit l'un de deux parcours. Les deux journées de
    :data:`RICH_EXCLUDED` (ajoutées au tirage) ont une FC de repos ``provisional`` :
    l'étape 5 les exclut. Aux seuils par défaut, aucun retrait ne joue (la spline de
    la FC est au modèle, ``e_s`` aussi). Tailles sans rapport avec un effectif
    réel."""
    rnd = random.Random(seed)
    offsets = set(rnd.sample(range(span), days - len(RICH_EXCLUDED)))
    offsets |= {(d - RICH_START).days for d in RICH_EXCLUDED}
    activities: list[ActivityRow] = []
    climbs: list[ClimbRow] = []
    for offset in sorted(offsets):
        day = RICH_START + timedelta(days=offset)
        ref = f"r{offset:03d}"
        when = at(day, 7)
        activities.append(q2_activity(ref, when))
        heart = rnd.uniform(130.0, 165.0)
        effect = rnd.gauss(0.0, 0.02)
        for k in range(3):
            route = ROUTES[offset % 2] if k == 0 else None
            gain = rnd.uniform(700.0, 800.0) if route else rnd.uniform(300.0, 500.0)
            h = heart + rnd.gauss(0.0, 3.0)
            log_v = (
                -1.0
                + b * offset
                + 0.02 * (h - 145.0)
                - 0.1 * (math.log(gain) - 6.0)
                + effect
                + rnd.gauss(0.0, 0.02)
            )
            speed = math.exp(log_v)
            if route is None:
                lat, lon = 46.0 + rnd.uniform(0.0, 1.0), 7.0 + rnd.uniform(0.0, 1.0)
            else:
                lat, lon = route[0] + rnd.uniform(0.0, 0.0002), route[1]
            climbs.append(
                q2_climb(
                    ref,
                    when,
                    offset_s=3000.0 * k + rnd.uniform(0.0, 600.0),
                    gain_m=gain,
                    moving_s=gain / speed,
                    h=h,
                    grade=rnd.uniform(0.1, 0.3),
                    moving_mean_elevation_m=rnd.uniform(800.0, 2500.0),
                    preceding_ascent_m=rnd.uniform(0.0, 800.0),
                    preceding_descent_m=rnd.uniform(0.0, 600.0),
                    unlagged_moving_heart_rate_bpm=h - 1.0 + rnd.gauss(0.0, 1.0),
                    lagged_second_half_heart_rate_bpm=h + 3.0 + rnd.gauss(0.0, 1.0),
                    lagged_elapsed_heart_rate_bpm=h - 0.5 + rnd.gauss(0.0, 1.0),
                    moving_or_undetermined_vertical_speed_ms=speed
                    * rnd.uniform(0.9, 1.0),
                    start_latitude_deg=lat,
                    start_longitude_deg=lon,
                    end_latitude_deg=lat + 0.03,
                    end_longitude_deg=lon,
                    stable=rnd.random() > 0.2,
                )
            )
    first = RICH_START - timedelta(days=30)
    count = (RICH_START + timedelta(days=span + 1) - first).days
    rows = [
        q2_day_row(
            first + timedelta(days=i),
            resting=round(50.0 + rnd.gauss(0.0, 1.5), 1),
            status=RestingHrStatus.PROVISIONAL
            if first + timedelta(days=i) in RICH_EXCLUDED
            else RestingHrStatus.VALID,
        )
        for i in range(count)
    ]
    return q2_tables(activities, climbs, rows)
