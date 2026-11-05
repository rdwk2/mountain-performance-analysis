"""La règle commune des vues des jours, par des propriétés, pour chaque vue prise à un
instant (``sleep_within`` et ``series_between`` à leur borne ``end``) :

1. **changer, retirer ou ajouter des données dont l'instant
   propre est après ``t``** (au plus tôt ``t`` avec ``strict``), **le document du
   lendemain du dernier jour compris, ne change pas la vue à ``t``** ; la même,
   resserrée sur ce lendemain
   (``test_the_next_day_added_does_not_change_the_view_at_t``) ;
2. **avec ``strict`` à ``t``, la vue rend les mêmes objets que sans ``strict`` à
   ``t`` − 1 µs** (la résolution des instants des contrats) ; seuls diffèrent ce qui
   se mesure depuis ``t`` : les âges et l'écart, d'une microseconde, la borne ``end``,
   et la couverture de ``series_between`` (prise ici sans minimum de couverture).

Instants propres : nuit et sieste, leur fin ;
point de série, son instant ; segment de phase, sa fin ; entrée de Training Readiness,
son instant ; FC de repos et état du jour, la fin de la fenêtre du jour (le plus tard
de son début + 24 h et de sa fin des données, lue dans le seul document du jour) ; bloc
de Training Status, son ``proper_instant`` (jamais rendu sans lui ; calculé à
l'ingestion, il n'est pas recalculé par la réécriture : la dépendance de celui d'un
bloc sans fenêtre de son jour au document du lendemain est hors de cette propriété,
et ``tests/test_ingest_days_training_status.py`` la tient).
Une nuit visible (finie au plus tard à ``t``) garde sa fenêtre, ses durées et ses
résumés ; ses séries et ses segments d'après ``t`` (hors de sa fenêtre) sont
réécrits eux aussi, et les vues qui rendent la nuit (``night_before``,
``sleep_within``) les coupent à ``t``.

La réécriture ajoute **le document du lendemain du dernier jour** (D + 1) dès que tous
ses instants propres sont après ``t`` : la vue à ``t`` ne doit pas en dépendre, même
par la fin de la fenêtre de D (une vue qui lirait le début de la fenêtre de D + 1
cacherait à ``t`` une grandeur de D que le monde sans D + 1 montre). Elle change la fin
des données d'un jour dont la fin est cachée en la gardant cachée : l'état et la fin
des données, si début + 24 h l'est ; sinon la seule fin des données, encore après
``t``.

Mondes inventés, de quelques jours de mars 2001 (la fenêtre d'un jour à +02:00 ou à
+01:00 : deux jours qui se suivent font aussi les recouvrements et les trous du
changement d'heure ; un jour complet a parfois 25 h de données), qui portent toutes
les séries que ``series_between`` peut lire. ``t`` : un instant décisif — la fin d'une
nuit, une microseconde après ou avant ; un point d'une série, jusqu'aux points d'une
nuit tombés après sa fin ; la dernière heure d'un jour de 25 h, l'intervalle entre la
fin des données et début + 24 h d'un jour tronqué —, l'instant propre d'une donnée du
monde (l'égalité exacte) ou une microseconde après, les abords de la fin du dernier
jour (une demi-heure ou une microseconde après, ou sa fin), ou libre ; la branche où
se décide la vue vient en tête, et la sorte de série de ``series_between`` est, une
fois sur deux, une sorte qui a un point à ``t``. Le lendemain ajouté est le plus
souvent à +01:00 (à +02:00 la veille, sa fenêtre commence une heure après début +
24 h : le trou de l'automne) et, une fois sur deux, sans nuit, sieste ni entrée de
Training Readiness. Hypothesis tirant plus souvent la
première branche d'un ``one_of`` et le premier élément d'un ``sampled_from``, l'ordre
des choix les met en tête : sans cela, le cas d'un lendemain qui ferait fuir une vue
serait trop rare pour que la propriété le voie.
"""

from __future__ import annotations

import dataclasses
import itertools
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from typing import Any

import pytest
from hypothesis import HealthCheck, assume, given, settings
from hypothesis import strategies as st

from fixtures.days import (
    EMPTY_DAY_SERIES,
    PLUS1,
    PLUS2,
    SRC,
    at,
    day_record,
    load_balance_block,
    midnight,
    nap,
    night,
    readiness,
    source,
    status_block,
)
from mountain_perf.ingest.day_views import (
    BodyBatteryReading,
    body_battery_at,
    night_before,
    readiness_at,
    resting_hr_at,
    series_between,
    sleep_within,
    training_status_at,
)
from mountain_perf.schemas import (
    BodyBatterySeries,
    BodyBatteryStatus,
    DayFamily,
    DayRecord,
    DaySeries,
    DayState,
    HeartRateSeries,
    HrvSeries,
    LoadBalanceBlock,
    Nap,
    Night,
    NightSeries,
    RespirationSeries,
    RestlessMomentsSeries,
    SeriesKind,
    SleepSegment,
    SleepStage,
    SpO2Series,
    StressSeries,
    TrainingStatusBlock,
    TrainingStatusHistory,
    TrainingStatusKind,
    ViewAbsence,
)

BASE = date(2001, 3, 8)
_DAY = timedelta(days=1)
_MICRO = timedelta(microseconds=1)
_HOUR = timedelta(hours=1)


@dataclass(frozen=True)
class World:
    """Un monde inventé : les documents des jours et Training Status."""

    days: tuple[DayRecord, ...]
    history: TrainingStatusHistory


def _day_end(record: DayRecord) -> datetime:
    assert record.window_start is not None
    assert record.data_end is not None
    return max(record.window_start + _DAY, record.data_end)


def _times(draw: st.DrawFn, low: int, high: int, most: int) -> tuple[float, ...]:
    values = draw(st.lists(st.integers(low, high), max_size=most, unique=True))
    return tuple(float(value) for value in sorted(values))


@st.composite
def _night(draw: st.DrawFn, day: date, window_start: datetime) -> Night:
    start = window_start - timedelta(seconds=draw(st.integers(3600, 5 * 3600)))
    duration = draw(st.integers(4 * 3600, 10 * 3600))
    end_offset = draw(st.sampled_from([PLUS1, PLUS2]))
    end = (start + timedelta(seconds=duration)).astimezone(end_offset)
    cuts = sorted(
        draw(st.lists(st.integers(1, duration + 2400), max_size=4, unique=True))
    )
    bounds = [0, *cuts, duration + draw(st.integers(0, 2400))]
    stages = list(SleepStage)
    segments = tuple(
        SleepSegment(float(a), float(b), draw(st.sampled_from(stages)))
        for a, b in itertools.pairwise(bounds)
        if b > a
    )
    hr = _times(draw, -1800, duration + 3600, 5)
    hrv = _times(draw, -600, duration + 3600, 4)
    battery = _times(draw, -600, duration + 3600, 4)
    stress = _times(draw, -600, duration + 3600, 3)
    breath = _times(draw, -600, duration + 3600, 3)
    oxygen = _times(draw, -600, duration + 3600, 3)
    moments = _times(draw, -600, duration + 3600, 2)
    series = NightSeries(
        heart_rate=HeartRateSeries(hr, (55.0,) * len(hr), SRC) if hr else None,
        stress=(
            StressSeries(stress, (10,) * len(stress), (None,) * len(stress), SRC)
            if stress
            else None
        ),
        body_battery=(
            BodyBatterySeries(
                battery, (40,) * len(battery), (None,) * len(battery), SRC
            )
            if battery
            else None
        ),
        hrv=HrvSeries(hrv, (45.0,) * len(hrv), SRC) if hrv else None,
        respiration=(
            RespirationSeries(breath, (14.0,) * len(breath), (None,) * len(breath), SRC)
            if breath
            else None
        ),
        spo2=SpO2Series(oxygen, (95.0,) * len(oxygen), SRC) if oxygen else None,
        restless_moments=(
            RestlessMomentsSeries(moments, (1,) * len(moments), SRC)
            if moments
            else None
        ),
    )
    return night(day, start=start, end=end, segments=segments, series=series)


@st.composite
def _record(draw: st.DrawFn, day: date, bare: bool = False) -> DayRecord:
    offset = draw(st.sampled_from([PLUS1, PLUS2]))
    start = midnight(day, offset)
    shape = draw(st.sampled_from(["complete", "long", "truncated"]))
    if shape == "complete":
        data_end, state = start + _DAY, DayState.COMPLETE
    elif shape == "long":
        data_end, state = start + _DAY + _HOUR, DayState.COMPLETE
    else:
        data_end = start + timedelta(seconds=draw(st.integers(3600, 86399)))
        state = DayState.TRUNCATED
    the_night = None if bare or not draw(st.booleans()) else draw(_night(day, start))
    naps: tuple[Nap, ...] = ()
    if not bare and draw(st.booleans()):
        nap_start = at(day, 13, draw(st.integers(0, 59)), offset=offset)
        naps = (nap(day, start=nap_start, end=nap_start + timedelta(minutes=30)),)
    entries: list[Any] = []
    if not bare:
        for second in sorted(
            draw(st.lists(st.integers(5 * 3600, 21 * 3600), max_size=2, unique=True))
        ):
            entries.append(
                readiness(day, instant=start + timedelta(seconds=second), score=50)
            )
    heart = _times(draw, 0, 90000, 5)
    stress = _times(draw, 0, 90000, 3)
    battery = _times(draw, 0, 90000, 4)
    breath = _times(draw, 0, 90000, 3)
    oxygen = _times(draw, 0, 90000, 2)
    series = DaySeries(
        heart_rate=HeartRateSeries(heart, (60.0,) * len(heart), SRC) if heart else None,
        stress=(
            StressSeries(stress, (20,) * len(stress), (None,) * len(stress), SRC)
            if stress
            else None
        ),
        body_battery=(
            BodyBatterySeries(
                battery,
                (50,) * len(battery),
                (BodyBatteryStatus.MEASURED,) * len(battery),
                SRC,
            )
            if battery
            else None
        ),
        respiration=(
            RespirationSeries(breath, (15.0,) * len(breath), (None,) * len(breath), SRC)
            if breath
            else None
        ),
        spo2=SpO2Series(oxygen, (96.0,) * len(oxygen), SRC) if oxygen else None,
    )
    return day_record(
        day,
        window_start=start,
        data_end=data_end,
        state=state,
        night=the_night,
        naps=naps,
        readiness=tuple(entries),
        series=series,
    )


@st.composite
def worlds(draw: st.DrawFn) -> World:
    count = draw(st.integers(1, 3))
    records = tuple(draw(_record(BASE + i * _DAY)) for i in range(count))
    statuses: list[TrainingStatusBlock] = []
    balances: list[LoadBalanceBlock] = []
    for record in records:
        assert record.window_start is not None
        if draw(st.booleans()):
            stamp = record.window_start + timedelta(seconds=draw(st.integers(0, 86399)))
            statuses.append(
                status_block(record.day, timestamp=stamp, proper_instant=stamp)
            )
        proper = draw(st.sampled_from([_day_end(record), None]))
        balances.append(load_balance_block(record.day, proper_instant=proper))
    history = TrainingStatusHistory(tuple(statuses), tuple(balances), (), (), ())
    return World(records, history)


def _all_series(series: DaySeries | NightSeries) -> list[Any]:
    """Les séries présentes d'un jour ou d'une nuit."""
    found = (getattr(series, item.name) for item in dataclasses.fields(series))
    return [item for item in found if item is not None]


def _night_instants(world: World) -> list[datetime]:
    """Les instants où se décident les nuits : une microseconde après la fin de chaque
    nuit (en tête : Hypothesis tire plus souvent le premier élément), sa fin, une
    microseconde avant (une nuit finie juste avant ou juste après ``t``). Les points
    d'une nuit tombés après sa fin sont dans la branche des points."""
    instants: list[datetime] = []
    for record in world.days:
        if record.night is not None:
            end = record.night.end
            instants += [end + _MICRO, end, end - _MICRO]
    return instants


def _tail_instants(world: World) -> list[datetime]:
    """Les instants où se décide la fin de la fenêtre d'un jour : la dernière heure
    d'un jour de 25 h ; l'intervalle entre ``data_end`` et début + 24 h d'un jour
    tronqué."""
    instants: list[datetime] = []
    for record in world.days:
        assert record.window_start is not None
        assert record.data_end is not None
        start, data_end = record.window_start, record.data_end
        if data_end > start + _DAY:
            instants += [start + _DAY, start + _DAY + _HOUR / 2, data_end - _MICRO]
        elif data_end < start + _DAY:
            instants += [data_end, data_end + (start + _DAY - data_end) / 2]
    return instants


def _series_points(world: World, kind: SeriesKind) -> list[datetime]:
    """Les instants des points de la série ``kind``, dans tous les jours."""
    name = kind.value.split("_", 1)[1]
    instants: list[datetime] = []
    for record in world.days:
        if kind.value.startswith("night_"):
            if record.night is None:
                continue
            origin, series = record.night.start, getattr(record.night.series, name)
        else:
            assert record.window_start is not None
            origin, series = record.window_start, getattr(record.series, name)
        if series is not None:
            instants += [origin + timedelta(seconds=t) for t in series.time_s]
    return instants


def _series_kind(world: World, t: datetime) -> st.SearchStrategy[SeriesKind]:
    """La sorte de série de ``series_between`` : une fois sur deux, une sorte qui a
    un point à ``t`` ou à ``t`` − 1 µs (s'il y en a), là où ``strict`` décide."""
    at_t = [
        kind
        for kind in SeriesKind
        if {t, t - _MICRO} & set(_series_points(world, kind))
    ]
    every = st.sampled_from(list(SeriesKind))
    return st.one_of(st.sampled_from(at_t), every) if at_t else every


def _proper_instants(world: World) -> list[datetime]:
    instants: list[datetime] = []
    for record in world.days:
        instants.append(_day_end(record))
        assert record.window_start is not None
        for series in _all_series(record.series):
            instants += [
                record.window_start + timedelta(seconds=t) for t in series.time_s
            ]
        instants += [item.end for item in record.naps]
        instants += [entry.instant for entry in record.readiness]
        if record.night is not None:
            instants.append(record.night.end)
            start = record.night.start
            instants += [
                start + timedelta(seconds=s.end_s) for s in record.night.segments
            ]
            for series_ in _all_series(record.night.series):
                instants += [start + timedelta(seconds=t) for t in series_.time_s]
    for proper in (
        *(block.proper_instant for block in world.history.statuses),
        *(block.proper_instant for block in world.history.load_balances),
    ):
        if proper is not None:
            instants.append(proper)
    return instants


_BRANCHES = ("night", "point", "tail", "proper", "end", "free")

_FIRST_BRANCH = {
    "body_battery_at": "night",
    "night_before": "night",
    "sleep_within": "night",
    "series_between": "point",
    "resting_hr_at": "tail",
    "readiness_at": "proper",
    "training_status_at": "proper",
}
"""La branche de ``t`` où se décide chaque vue, mise en tête : Hypothesis tire bien
plus souvent le premier élément d'un ``sampled_from``."""


@st.composite
def _instant(draw: st.DrawFn, world: World, name: str) -> datetime:
    """``t`` : à un instant décisif d'une nuit, de la fin d'un jour, d'un point d'une
    série (ou une microseconde après) ; l'instant propre d'une donnée du monde (ou une
    microseconde après) ; aux abords de la fin du dernier jour ; libre. Chaque sorte
    d'instant décisif a sa branche, et celle où se décide la vue ``name`` vient en
    tête."""
    end = _day_end(world.days[-1])
    points = [point for kind in SeriesKind for point in _series_points(world, kind)]
    branches = {
        "night": _night_instants(world),
        "tail": _tail_instants(world),
        "point": points,
        "proper": _proper_instants(world),
    }
    first = _FIRST_BRANCH[name]
    choice = draw(
        st.sampled_from([first, *(item for item in _BRANCHES if item != first)])
    )
    if branches.get(choice):
        instant = draw(st.sampled_from(branches[choice]))
        if choice == "night":
            return instant
        return instant + draw(st.sampled_from([timedelta(0), _MICRO]))
    if choice != "free":
        return end + draw(
            st.sampled_from([timedelta(minutes=30), _MICRO, timedelta(0)])
        )
    origin = world.days[0].window_start
    assert origin is not None
    return (
        origin - _HOUR + timedelta(microseconds=draw(st.integers(0, 4 * 86400 * 10**6)))
    )


PARAMS = st.fixed_dictionaries(
    {
        "min_sleep_s": st.sampled_from([0.0, 3 * 3600.0, 6 * 3600.0]),
        "step_s": st.sampled_from([60.0, 900.0, 3600.0]),
        "span": st.sampled_from(
            [timedelta(hours=2), timedelta(hours=12), timedelta(days=3)]
        ),
        "series_kind": st.sampled_from(list(SeriesKind)),
        "status_kind": st.sampled_from(
            [TrainingStatusKind.STATUS, TrainingStatusKind.LOAD_BALANCE]
        ),
    }
)

_View = Callable[[World, datetime, bool, dict[str, Any], datetime], Any]

VIEWS: dict[str, _View] = {
    "body_battery_at": lambda w, t, s, p, a: body_battery_at(w.days, t, strict=s),
    "night_before": lambda w, t, s, p, a: night_before(w.days, t, strict=s),
    "readiness_at": lambda w, t, s, p, a: readiness_at(w.days, t, strict=s),
    "resting_hr_at": lambda w, t, s, p, a: resting_hr_at(
        w.days, t, min_sleep_s=p["min_sleep_s"], strict=s
    ),
    "series_between": lambda w, t, s, p, a: series_between(
        w.days,
        p["series_kind"],
        a,
        t,
        step_s=p["step_s"],
        min_coverage_fraction=0.0,
        strict=s,
    ),
    "sleep_within": lambda w, t, s, p, a: sleep_within(w.days, a, t, strict=s),
    "training_status_at": lambda w, t, s, p, a: training_status_at(
        w.history, p["status_kind"], t, strict=s
    ),
}


def _hidden(instant: datetime, t: datetime, strict: bool) -> bool:
    return instant >= t if strict else instant > t


def _rewrite_points(series: Any, origin: datetime, t: datetime, strict: bool) -> Any:
    """La série dont les points d'après ``t`` portent d'autres valeurs."""
    if series is None:
        return None
    hidden = [
        _hidden(origin + timedelta(seconds=time), t, strict) for time in series.time_s
    ]
    if not any(hidden):
        return series
    changes: dict[str, Any] = {}
    for item in dataclasses.fields(series):
        if item.name in ("time_s", "source", "status", "code"):
            continue
        values = getattr(series, item.name)
        changes[item.name] = tuple(
            (value if value is None else type(value)(value) + 1) if hide else value
            for value, hide in zip(values, hidden, strict=True)
        )
    return dataclasses.replace(series, **changes)


def _rewrite_night(night_: Night, t: datetime, strict: bool) -> Night:
    """La nuit dont les données d'après ``t`` changent : ses points et ses segments
    d'après ``t`` ; ceux d'une nuit finie après ``t`` tous, son instant propre étant le
    sien."""
    start = night_.start
    series = night_.series
    hidden = _hidden(night_.end, t, strict)
    cut = start - _DAY if hidden else t
    rewritten = NightSeries(
        heart_rate=_rewrite_points(series.heart_rate, start, cut, strict),
        stress=_rewrite_points(series.stress, start, cut, strict),
        body_battery=_rewrite_points(series.body_battery, start, cut, strict),
        hrv=_rewrite_points(series.hrv, start, cut, strict),
        respiration=_rewrite_points(series.respiration, start, cut, strict),
        spo2=_rewrite_points(series.spo2, start, cut, strict),
        restless_moments=_rewrite_points(series.restless_moments, start, cut, strict),
    )
    segments = tuple(
        dataclasses.replace(
            segment,
            stage=SleepStage.AWAKE
            if segment.stage is not SleepStage.AWAKE
            else SleepStage.LIGHT,
        )
        if _hidden(start + timedelta(seconds=segment.end_s), cut, strict)
        else segment
        for segment in night_.segments
    )
    changes: dict[str, Any] = {"series": rewritten, "segments": segments}
    if hidden:
        changes["deep_s"] = (night_.deep_s or 0.0) + 60.0
        changes["sleep_score"] = 33
    return dataclasses.replace(night_, **changes)


def _rewrite_day(record: DayRecord, t: datetime, strict: bool) -> DayRecord:
    assert record.window_start is not None
    assert record.data_end is not None
    start = record.window_start
    changes: dict[str, Any] = {
        "series": DaySeries(
            heart_rate=_rewrite_points(record.series.heart_rate, start, t, strict),
            stress=_rewrite_points(record.series.stress, start, t, strict),
            body_battery=_rewrite_points(record.series.body_battery, start, t, strict),
            respiration=_rewrite_points(record.series.respiration, start, t, strict),
            spo2=_rewrite_points(record.series.spo2, start, t, strict),
        ),
        "naps": tuple(
            dataclasses.replace(item, sleep_s=item.sleep_s + 60.0)
            if _hidden(item.end, t, strict)
            else item
            for item in record.naps
        ),
        "readiness": tuple(
            dataclasses.replace(entry, score=77)
            if _hidden(entry.instant, t, strict)
            else entry
            for entry in record.readiness
        ),
    }
    if record.night is not None:
        changes["night"] = _rewrite_night(record.night, t, strict)
    if _hidden(_day_end(record), t, strict):
        if record.resting_hr is not None:
            changes["resting_hr"] = dataclasses.replace(
                record.resting_hr, resting_hr_bpm=record.resting_hr.resting_hr_bpm + 1
            )
        if _hidden(start + _DAY, t, strict):
            if record.state is DayState.COMPLETE:
                changes["data_end"] = start + timedelta(hours=12)
                changes["state"] = DayState.TRUNCATED
            else:
                changes["data_end"] = start + _DAY
                changes["state"] = DayState.COMPLETE
        else:
            changes["data_end"] = record.data_end + timedelta(minutes=1)
    return dataclasses.replace(record, **changes)


def _next_day(world: World, offset: timezone, bare: bool) -> DayRecord:
    last = world.days[-1].day + _DAY
    start = midnight(last, offset)
    heart = HeartRateSeries((600.0, 7200.0), (70.0, 71.0), SRC)
    return day_record(
        last,
        window_start=start,
        data_end=start + _DAY,
        night=None if bare else night(last, start=start + _HOUR, end=start + 6 * _HOUR),
        naps=()
        if bare
        else (
            nap(
                last, start=at(last, 13, offset=offset), end=at(last, 14, offset=offset)
            ),
        ),
        readiness=() if bare else (readiness(last, instant=start + 7 * _HOUR),),
        series=DaySeries(heart, None, None, None, None),
    )


def _next_day_hidden(record: DayRecord, t: datetime, strict: bool) -> bool:
    assert record.window_start is not None
    instants = [_day_end(record), record.window_start + timedelta(seconds=600)]
    if record.night is not None:
        instants.append(record.night.end)
    instants += [item.end for item in record.naps]
    instants += [entry.instant for entry in record.readiness]
    return all(_hidden(instant, t, strict) for instant in instants)


def _rewrite(world: World, t: datetime, strict: bool, after: DayRecord | None) -> World:
    days = tuple(_rewrite_day(record, t, strict) for record in world.days)
    if after is not None and _next_day_hidden(after, t, strict):
        days = (*days, after)
    history = world.history
    rewritten = TrainingStatusHistory(
        statuses=tuple(
            dataclasses.replace(block, acute_load=12.5)
            if block.proper_instant is not None
            and _hidden(block.proper_instant, t, strict)
            else block
            for block in history.statuses
        ),
        load_balances=tuple(
            dataclasses.replace(block, monthly_anaerobic=12.5)
            if block.proper_instant is not None
            and _hidden(block.proper_instant, t, strict)
            else block
            for block in history.load_balances
        ),
        vo2_max=history.vo2_max,
        heat_acclimation=history.heat_acclimation,
        altitude_acclimation=history.altitude_acclimation,
    )
    return World(days, rewritten)


_SETTINGS = settings(
    max_examples=120,
    deadline=None,
    suppress_health_check=[HealthCheck.too_slow, HealthCheck.data_too_large],
)


def _check_after_t(
    name: str, world: World, params: dict[str, Any], data: st.DataObject
) -> None:
    t = data.draw(_instant(world, name))
    params = {**params, "series_kind": data.draw(_series_kind(world, t))}
    strict = data.draw(st.booleans())
    offset = data.draw(st.sampled_from([PLUS1, PLUS2]))
    bare = data.draw(st.booleans())
    after = _next_day(world, offset, bare)
    anchor = t - params["span"]
    view = VIEWS[name]
    assert view(world, t, strict, params, anchor) == view(
        _rewrite(world, t, strict, after), t, strict, params, anchor
    )


@pytest.mark.parametrize("name", sorted(VIEWS))
@_SETTINGS
@given(world=worlds(), params=PARAMS, data=st.data())
def test_data_after_t_do_not_change_the_view_at_t(
    name: str, world: World, params: dict[str, Any], data: st.DataObject
) -> None:
    _check_after_t(name, world, params, data)


@pytest.mark.parametrize("name", sorted(VIEWS))
@settings(
    max_examples=100,
    deadline=None,
    suppress_health_check=[HealthCheck.too_slow, HealthCheck.data_too_large],
)
@given(world=worlds(), params=PARAMS, data=st.data())
def test_the_next_day_added_does_not_change_the_view_at_t(
    name: str, world: World, params: dict[str, Any], data: st.DataObject
) -> None:
    """La propriété précédente, resserrée sur le cas où un lendemain ferait fuir une
    vue. Entrée décisive : ``t`` aux abords de la fin du dernier jour D (sa fin, une
    microseconde ou une demi-heure après ; sans fenêtre de D, ``t`` libre), avec ou sans
    ``strict`` ; le document de D + 1 ajouté, sans nuit, sieste ni entrée, le plus
    souvent à +01:00 (à +02:00 la veille, sa fenêtre commence une heure après début +
    24 h de D : le trou de l'automne), s'il n'a aucun instant propre au plus tard
    ``t``. Attendu : la vue à ``t`` ne change pas ; la fin de la fenêtre de D ne lit pas
    D + 1."""
    end = _day_end(world.days[-1])
    t = end + data.draw(st.sampled_from([timedelta(0), _MICRO, timedelta(minutes=30)]))
    strict = data.draw(st.booleans())
    offset = data.draw(st.sampled_from([PLUS1, PLUS1, PLUS2]))
    after = _next_day(world, offset, bare=True)
    assume(_next_day_hidden(after, t, strict))
    grown = World((*world.days, after), world.history)
    anchor = t - params["span"]
    view = VIEWS[name]
    assert view(world, t, strict, params, anchor) == view(
        grown, t, strict, params, anchor
    )


_AGES = ("age_s", "gap_s")


def _comparable(result: Any) -> Any:
    if not dataclasses.is_dataclass(result) or isinstance(result, type):
        return result
    changes: dict[str, Any] = {}
    for item in dataclasses.fields(result):
        if item.name in _AGES or item.name == "end":
            changes[item.name] = None
        if item.name == "coverage_fraction" and type(result).__name__ == "SeriesWindow":
            changes[item.name] = 0.0
    return dataclasses.replace(result, **changes)


@pytest.mark.parametrize("name", sorted(VIEWS))
@_SETTINGS
@given(world=worlds(), params=PARAMS, data=st.data())
def test_strict_at_t_is_plain_at_t_minus_a_microsecond(
    name: str, world: World, params: dict[str, Any], data: st.DataObject
) -> None:
    """Entrée décisive : une vue prise à ``t`` avec ``strict``, et sans ``strict`` à
    ``t`` − 1 µs, l'intervalle de ``sleep_within`` et de ``series_between`` partant du
    même début (``anchor``), sans minimum de couverture. Attendu : les mêmes objets
    (nuits, segments, points, entrées, jours, blocs, motifs) ; les âges et l'écart, plus
    longs d'une microseconde avec ``strict``."""
    t = data.draw(_instant(world, name))
    params = {**params, "series_kind": data.draw(_series_kind(world, t))}
    anchor = t - params["span"]
    view = VIEWS[name]
    strict = view(world, t, True, params, anchor)
    plain = view(world, t - _MICRO, False, params, anchor)
    assert _comparable(strict) == _comparable(plain)
    for age in _AGES:
        late, early = getattr(strict, age, None), getattr(plain, age, None)
        if late is not None and early is not None:
            assert abs(late - early - 1e-6) < 1e-9


_DECISIVE_PARAMS: dict[str, Any] = {
    "min_sleep_s": 0.0,
    "step_s": 60.0,
    "span": timedelta(hours=12),
    "series_kind": SeriesKind.DAY_HEART_RATE,
    "status_kind": TrainingStatusKind.STATUS,
}


def _decisive_world(name: str) -> tuple[World, datetime]:
    """Un monde où la propriété se décide à coup sûr : pour ``night_before`` et
    ``sleep_within``, une nuit finie à ``t`` dont un point de FC tombe une demi-heure
    après sa fin ; pour ``body_battery_at``, une nuit en cours à ``t`` dont des points
    de Body Battery précèdent ``t``, l'un au même instant qu'un point du jour ; pour
    ``resting_hr_at``, un jour complet de 25 h, ``t`` dans sa dernière heure (la fin de
    sa fenêtre, une heure après début + 24 h, est cachée)."""
    empty = NightSeries(None, None, None, None, None, None, None)
    if name == "resting_hr_at":
        start = midnight(BASE)
        record = day_record(BASE, data_end=start + _DAY + _HOUR)
        return World((record,), _NO_HISTORY), start + _DAY + _HOUR / 2
    if name in ("night_before", "sleep_within"):
        series = dataclasses.replace(
            empty, heart_rate=HeartRateSeries((0.0, 30600.0), (55.0, 56.0), SRC)
        )
        the_night = night(BASE, series=series)
        return World((day_record(BASE, night=the_night),), _NO_HISTORY), the_night.end
    battery = BodyBatterySeries((0.0, 3600.0), (30, 35), (None, None), SRC)
    the_night = night(BASE, series=dataclasses.replace(empty, body_battery=battery))
    return World((day_record(BASE, night=the_night),), _NO_HISTORY), at(BASE, 2)


_NO_HISTORY = TrainingStatusHistory((), (), (), (), ())


@pytest.mark.parametrize(
    "name", ["night_before", "sleep_within", "body_battery_at", "resting_hr_at"]
)
def test_data_after_t_do_not_change_the_view_at_t_in_decisive_worlds(
    name: str,
) -> None:
    """La première propriété, sur des mondes qui la décident : une nuit rendue est
    coupée à ``t`` (``night_before`` ; ``sleep_within``, l'intervalle partant de
    ``t``) ; une nuit en cours à ``t`` n'a ni fenêtre ni points (``body_battery_at``) ;
    la fin de la fenêtre d'un jour de 25 h est la fin de ses données
    (``resting_hr_at``)."""
    world, t = _decisive_world(name)
    view = VIEWS[name]
    for strict in (False, True):
        rewritten = _rewrite(world, t, strict, None)
        assert rewritten != world
        assert view(world, t, strict, _DECISIVE_PARAMS, t) == view(
            rewritten, t, strict, _DECISIVE_PARAMS, t
        )


def _decisive_strict_world(name: str) -> tuple[World, datetime]:
    """Un monde où la seconde propriété se décide à coup sûr : pour ``night_before``,
    une nuit finie une microseconde avant ``t`` ; pour ``series_between``, un point de
    FC du jour à ``t`` même."""
    if name == "night_before":
        record = day_record(BASE)
        assert record.night is not None
        return World((record,), _NO_HISTORY), record.night.end + _MICRO
    series = DaySeries(
        HeartRateSeries((3600.0, 7200.0), (60.0, 61.0), SRC), None, None, None, None
    )
    record = day_record(BASE, series=series)
    return World((record,), _NO_HISTORY), midnight(BASE) + 2 * _HOUR


@pytest.mark.parametrize("name", ["night_before", "series_between"])
def test_strict_at_t_is_plain_at_t_minus_a_microsecond_in_decisive_worlds(
    name: str,
) -> None:
    """La seconde propriété, sur deux mondes qui la décident : une nuit finie à ``t`` −
    1 µs est rendue avec ``strict`` à ``t`` comme sans ``strict`` à ``t`` − 1 µs ; un
    point à ``t`` n'est rendu ni par l'une ni par l'autre."""
    world, t = _decisive_strict_world(name)
    anchor = t - _DECISIVE_PARAMS["span"]
    view = VIEWS[name]
    strict = view(world, t, True, _DECISIVE_PARAMS, anchor)
    plain = view(world, t - _MICRO, False, _DECISIVE_PARAMS, anchor)
    assert _comparable(strict) == _comparable(plain)


def test_the_rewriting_changes_something_after_t() -> None:
    """Garde-fou de la propriété : la réécriture touche bien des données (une nuit, une
    entrée, des points, la FC de repos), sans quoi elle ne prouverait rien."""
    record = day_record(BASE, naps=(nap(BASE),))
    world = World(
        (record,), TrainingStatusHistory((status_block(BASE),), (), (), (), ())
    )
    t = at(BASE, 6)
    rewritten = _rewrite(world, t, False, _next_day(world, PLUS1, bare=True))
    new = rewritten.days[0]
    assert new.night != record.night
    assert new.readiness != record.readiness
    assert new.naps != record.naps
    assert new.series != record.series
    assert new.resting_hr != record.resting_hr
    assert rewritten.history != world.history
    assert len(rewritten.days) == 2
    assert new.series != EMPTY_DAY_SERIES


# --- body_battery_at contre une implémentation naïve ----------------------------------


def _battery_times(
    draw: st.DrawFn, low: int, high: int, anchors: list[int]
) -> tuple[float, ...]:
    """Des instants en secondes depuis l'origine d'une série : libres, ou sur
    ``anchors`` (les bornes des nuits) ; parfois doublés à moins d'une microseconde (le
    même instant)."""
    pool = st.one_of(st.sampled_from(anchors), st.integers(low, high))
    times: list[float] = []
    for value in sorted(set(draw(st.lists(pool, max_size=5)))):
        times.append(float(value))
        if draw(st.integers(0, 3)) == 0:
            times.append(value + 3e-7)
    return tuple(times)


@st.composite
def _battery_night(
    draw: st.DrawFn, day: date, rank: int, start: datetime, previous: Night | None
) -> Night:
    """Une nuit qui touche la précédente, la recouvre, tient dans elle, ou libre ; ses
    points de Body Battery dans et hors de sa fenêtre, jusqu'à ses deux bornes, tous
    avant son début, tous après sa fin, ou aux instants de ceux de la précédente (deux
    nuits qui offrent un point au même instant)."""
    shape = draw(st.sampled_from(["touch", "overlap", "inside", "free"]))
    duration = draw(st.integers(1, 12 * 3600))
    if previous is not None and shape == "touch":
        night_start = previous.end
    elif previous is not None and shape == "overlap":
        night_start = previous.end - timedelta(seconds=draw(st.integers(1, 3 * 3600)))
    elif previous is not None and shape == "inside":
        span = int((previous.end - previous.start).total_seconds())
        offset = draw(st.integers(0, span - 1))
        night_start = previous.start + timedelta(seconds=offset)
        duration = draw(st.integers(1, span - offset))
    else:
        night_start = start + timedelta(seconds=draw(st.integers(-6 * 3600, 12 * 3600)))
    night_end = night_start + timedelta(seconds=duration)
    before = None if previous is None else previous.series.body_battery
    if previous is not None and before is not None and draw(st.booleans()):
        times = tuple(
            sorted(
                {
                    (
                        previous.start + timedelta(seconds=s) - night_start
                    ).total_seconds()
                    for s in before.time_s
                }
            )
        )
    else:
        low, high = draw(
            st.sampled_from(
                [(-3600, duration + 3600), (-3600, -1), (duration + 1, duration + 3600)]
            )
        )
        anchors = [bound for bound in (0, duration) if low <= bound <= high]
        times = _battery_times(draw, low, high, anchors or [low])
    battery = (
        BodyBatterySeries(
            times,
            tuple(10 * rank + index for index in range(len(times))),
            (None,) * len(times),
            source(DayFamily.SLEEP, day),
        )
        if times
        else None
    )
    return night(
        day,
        start=night_start,
        end=night_end.astimezone(draw(st.sampled_from([PLUS1, PLUS2]))),
        segments=(),
        series=NightSeries(None, None, battery, None, None, None, None),
    )


@st.composite
def _battery_days(draw: st.DrawFn) -> tuple[DayRecord, ...]:
    """Deux à quatre jours qui se suivent : des nuits qui se recouvrent, se touchent,
    tiennent l'une dans l'autre ou manquent ; des points du jour dans et hors des
    fenêtres des nuits, sur leurs bornes et une seconde à côté, ou aucun."""
    count = draw(st.integers(2, 4))
    frames: list[tuple[date, datetime, Night | None]] = []
    previous: Night | None = None
    for rank in range(count):
        day = BASE + rank * _DAY
        start = midnight(day, draw(st.sampled_from([PLUS1, PLUS2])))
        the_night = (
            draw(_battery_night(day, rank, start, previous))
            if draw(st.integers(0, 3))
            else None
        )
        previous = the_night or previous
        frames.append((day, start, the_night))
    nights = [the_night for _, _, the_night in frames if the_night is not None]
    days: list[DayRecord] = []
    for day, start, the_night in frames:
        anchors = [
            max(0, int((bound - start).total_seconds()) + step)
            for item in nights
            for bound in (item.start, item.end)
            for step in (-1, 0, 1)
        ]
        times = (
            _battery_times(draw, 0, 90000, anchors or [0])
            if draw(st.booleans())
            else ()
        )
        statuses = st.sampled_from(list(BodyBatteryStatus))
        battery = (
            BodyBatterySeries(
                times,
                tuple(100 - index for index in range(len(times))),
                tuple(draw(statuses) for _ in times),
                source(DayFamily.STRESS, day),
            )
            if times
            else None
        )
        days.append(
            day_record(
                day,
                window_start=start,
                data_end=start + _DAY,
                night=the_night,
                naps=(),
                readiness=(),
                series=DaySeries(None, None, battery, None, None),
            )
        )
    return tuple(days)


def _battery_instants(days: tuple[DayRecord, ...]) -> list[datetime]:
    """Les bornes des nuits et les instants des points."""
    found: list[datetime] = []
    for record in days:
        if record.night is not None:
            found += [record.night.start, record.night.end]
            series = record.night.series.body_battery
            if series is not None:
                found += [
                    record.night.start + timedelta(seconds=s) for s in series.time_s
                ]
        series = record.series.body_battery
        if series is not None and record.window_start is not None:
            found += [record.window_start + timedelta(seconds=s) for s in series.time_s]
    return found


def _naive_body_battery_at(
    days: tuple[DayRecord, ...], t: datetime, strict: bool
) -> BodyBatteryReading:
    """La vue écrite à plat : la visibilité de chaque point calculée directement."""

    def visible(instant: datetime) -> bool:
        return instant < t if strict else instant <= t

    nights = [
        (record.day, record.night)
        for record in days
        if record.night is not None and visible(record.night.end)
    ]
    found: list[tuple[datetime, date, int, BodyBatteryReading]] = []
    for day, the_night in nights:
        series = the_night.series.body_battery
        for index, time in enumerate(() if series is None else series.time_s):
            assert series is not None
            point = the_night.start + timedelta(seconds=time)
            if the_night.start <= point <= the_night.end:
                reading = BodyBatteryReading(
                    point,
                    series.level[index],
                    None,
                    True,
                    day,
                    None,
                    series.source,
                    None,
                )
                found.append((point, day, index, reading))
    for record in days:
        series = record.series.body_battery
        if series is None or record.window_start is None:
            continue
        for index, time in enumerate(series.time_s):
            point = record.window_start + timedelta(seconds=time)
            inside = any(item.start <= point <= item.end for _, item in nights)
            if visible(point) and not inside:
                reading = BodyBatteryReading(
                    point,
                    series.level[index],
                    series.status[index],
                    False,
                    record.day,
                    None,
                    series.source,
                    None,
                )
                found.append((point, record.day, index, reading))
    if not found:
        return BodyBatteryReading(
            None, None, None, None, None, None, None, ViewAbsence.NO_POINT
        )
    latest = max(point for point, _, _, _ in found)
    _, _, _, reading = min(
        (item for item in found if item[0] == latest),
        key=lambda item: (item[1], item[2]),
    )
    return dataclasses.replace(reading, age_s=(t - latest).total_seconds())


@settings(
    max_examples=2000,
    deadline=None,
    suppress_health_check=[HealthCheck.too_slow, HealthCheck.data_too_large],
)
@given(days=_battery_days(), data=st.data())
def test_body_battery_at_is_the_naive_view(
    days: tuple[DayRecord, ...], data: st.DataObject
) -> None:
    """``body_battery_at`` rend ce que rend la vue écrite à plat (le dernier point
    visible, ceux de la nuit dans sa fenêtre fermée, ceux du jour hors de toutes les
    fenêtres, à instants égaux le jour le plus ancien puis le premier de la série), sur
    des nuits qui se recouvrent, se touchent, tiennent l'une dans l'autre ou manquent ;
    ``t`` à la fin d'une nuit, une heure après tout (toutes les nuits finies), sur une
    borne de fenêtre ou un point, une microseconde à côté, ou libre (Hypothesis tirant
    plus souvent la première branche, les instants décisifs viennent en tête)."""
    instants = _battery_instants(days)
    ends = [record.night.end for record in days if record.night is not None]
    near = st.sampled_from(instants) if instants else st.nothing()
    after = st.just(max(instants) + _HOUR) if instants else st.nothing()
    free = st.integers(-12 * 3600, (len(days) + 1) * 86400).map(
        lambda seconds: midnight(BASE) + timedelta(seconds=seconds)
    )
    t = data.draw(
        st.one_of(
            st.sampled_from(ends) if ends else st.nothing(),
            after,
            near,
            near.map(lambda instant: instant + _MICRO),
            near.map(lambda instant: instant - _MICRO),
            free,
        )
    )
    strict = data.draw(st.booleans())
    assert body_battery_at(days, t, strict=strict) == _naive_body_battery_at(
        days, t, strict
    )
