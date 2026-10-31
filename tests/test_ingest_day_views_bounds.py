"""Les vues des jours (``ingest/day_views.py``) : chaque seuil à sa borne, des deux
côtés, par une valeur calculée par l'expression même du code (jamais un arrondi qui
tomberait du bon côté par chance) ; chaque seuil hors domaine ; chaque entrée
contrôlée, le nom de l'argument en tête du message.

Jours inventés (``fixtures/days.py``).
"""

from __future__ import annotations

import math
from collections.abc import Callable
from datetime import datetime, timedelta
from typing import Any

import pytest

from fixtures.days import (
    DAY,
    EMPTY_NIGHT_SERIES,
    SRC,
    at,
    day_record,
    history,
    midnight,
    night,
    readiness,
)
from mountain_perf.ingest.day_views import (
    body_battery_at,
    night_assessment,
    night_before,
    nights_after,
    readiness_at,
    readiness_on_waking,
    resting_hr_at,
    resting_hr_on,
    series_between,
    sleep_within,
    training_status_at,
)
from mountain_perf.schemas import (
    DaySeries,
    HeartRateSeries,
    NightState,
    RestingHrStatus,
    SeriesKind,
    TrainingStatusKind,
    ViewAbsence,
)

PREVIOUS = DAY - timedelta(days=1)
NAIVE = datetime(2001, 3, 10, 12)
DAYS = (day_record(PREVIOUS), day_record())
HISTORY = history()

ASSESSMENT: dict[str, Any] = {
    "max_unmeasured_fraction": 0.1,
    "short_sleep_s": 3600.0,
    "shift_s": 3600.0,
    "usual_window_days": 7,
    "usual_min_nights": 1,
}


def _assess(days: Any = DAYS, day: Any = DAY, **changes: Any) -> Any:
    return night_assessment(days, day, **{**ASSESSMENT, **changes})


def _below(value: float) -> float:
    return math.nextafter(value, -math.inf)


def _above(value: float) -> float:
    return math.nextafter(value, math.inf)


def test_max_unmeasured_fraction_at_its_bound() -> None:
    """« partielle » si la part non mesurable dépasse strictement le seuil."""
    record = day_record(night=night(unmeasurable_s=1234.5))
    assert record.night is not None
    assert record.night.unmeasurable_s is not None
    fraction = (
        record.night.unmeasurable_s
        / (record.night.end - record.night.start).total_seconds()
    )
    days = (record,)
    assert _assess(days, max_unmeasured_fraction=fraction).state is NightState.COMPLETE
    assert _assess(days, max_unmeasured_fraction=_below(fraction)).state is (
        NightState.PARTIAL
    )


def test_short_sleep_at_its_bound() -> None:
    """« courte » si le sommeil mesuré est strictement sous le seuil."""
    record = day_record(night=night(deep_s=3600.25))
    assert record.night is not None
    measured = record.night.measured_sleep_s
    assert measured is not None
    assert _assess((record,), short_sleep_s=measured).short is False
    assert _assess((record,), short_sleep_s=_above(measured)).short is True


def test_shift_at_its_bound() -> None:
    """« décalée » si l'écart circulaire au milieu habituel dépasse strictement le
    seuil ; l'écart est celui que la vue rend (``midpoint_distance_s``)."""
    previous = day_record(PREVIOUS, naps=())
    record = day_record(night=night(start=at(PREVIOUS, 23, 17, 11), end=at(DAY, 7, 3)))
    distance = _assess((previous, record)).midpoint_distance_s
    assert distance is not None
    assert distance > 0
    assert _assess((previous, record), shift_s=distance).shifted is False
    assert _assess((previous, record), shift_s=_below(distance)).shifted is True


def test_usual_min_nights_at_its_bound() -> None:
    """``usual_min_nights`` nuits suffisent ; une de moins, le milieu est inconnu."""
    days = tuple(day_record(DAY - timedelta(days=i), naps=()) for i in (3, 2, 1, 0))
    known = _assess(days, usual_min_nights=3)
    assert known.usual_nights == 3
    assert known.shifted_absence is None
    unknown = _assess(days, usual_min_nights=4)
    assert unknown.shifted_absence is ViewAbsence.BELOW_USUAL_MINIMUM


def test_min_sleep_at_its_bound() -> None:
    """``no_night`` si le sommeil mesuré est strictement sous ``min_sleep_s`` : par jour
    et à l'instant."""
    record = day_record(night=night(light_s=16200.75))
    assert record.night is not None
    measured = record.night.measured_sleep_s
    assert measured is not None
    days = (record,)
    assert (
        resting_hr_on(days, DAY, min_sleep_s=measured).status is RestingHrStatus.VALID
    )
    assert resting_hr_on(days, DAY, min_sleep_s=_above(measured)).status is (
        RestingHrStatus.NO_NIGHT
    )
    instant = midnight(DAY + timedelta(days=1))
    assert resting_hr_at(days, instant, min_sleep_s=measured).status is (
        RestingHrStatus.VALID
    )
    assert resting_hr_at(days, instant, min_sleep_s=_above(measured)).status is (
        RestingHrStatus.NO_NIGHT
    )


def test_waking_tolerance_at_its_bound() -> None:
    """Entrée d'instant au moins fin de la nuit − ``tolerance_s`` : retenue à la borne,
    pas un cheveu en deçà."""
    entry = readiness(instant=at(DAY, 6, 51, 17))
    record = day_record(readiness=(entry,))
    assert record.night is not None
    tolerance = (record.night.end - entry.instant).total_seconds()
    assert readiness_on_waking((record,), DAY, tolerance_s=tolerance).entry == entry
    assert readiness_on_waking(
        (record,), DAY, tolerance_s=_below(tolerance)
    ).absence is (ViewAbsence.NO_ENTRY_AFTER_NIGHT)


def test_min_coverage_fraction_at_its_bound() -> None:
    """Absente si la couverture est strictement sous le minimum ; la couverture est
    celle que la vue rend."""
    series = DaySeries(
        HeartRateSeries((0.0, 600.0), (50.0, 51.0), SRC), None, None, None, None
    )
    record = day_record(night=None, series=series)
    start, end = midnight(DAY), at(DAY, 0, 37)
    options: dict[str, Any] = {"step_s": 77.0, "min_coverage_fraction": 0.0}
    coverage = series_between(
        (record,), SeriesKind.DAY_HEART_RATE, start, end, **options
    ).coverage_fraction
    assert 0 < coverage < 1
    kept = series_between(
        (record,),
        SeriesKind.DAY_HEART_RATE,
        start,
        end,
        step_s=77.0,
        min_coverage_fraction=coverage,
    )
    assert kept.absence is None
    refused = series_between(
        (record,),
        SeriesKind.DAY_HEART_RATE,
        start,
        end,
        step_s=77.0,
        min_coverage_fraction=_above(coverage),
    )
    assert refused.absence is ViewAbsence.BELOW_COVERAGE


def test_thresholds_at_the_edges_of_their_domain() -> None:
    """Les bornes du domaine sont admises : 0 et 1 pour une fraction, 0 pour une durée,
    1 pour un compte, le plus petit pas positif."""
    for fraction in (0, 1, 0.0, 1.0):
        _assess(max_unmeasured_fraction=fraction)
        series_between(
            DAYS,
            SeriesKind.DAY_HEART_RATE,
            at(DAY, 0),
            at(DAY, 1),
            step_s=60.0,
            min_coverage_fraction=fraction,
        )
    _assess(short_sleep_s=0, shift_s=0.0, usual_window_days=1, usual_min_nights=1)
    resting_hr_on(DAYS, DAY, min_sleep_s=0)
    resting_hr_at(DAYS, at(DAY, 12), min_sleep_s=-0.0)
    readiness_on_waking(DAYS, DAY, tolerance_s=0.0)
    nights_after(DAYS, at(PREVIOUS, 0), 1)
    series_between(
        DAYS,
        SeriesKind.DAY_HEART_RATE,
        at(DAY, 0),
        at(DAY, 1),
        step_s=5e-324,
        min_coverage_fraction=0.0,
    )


_FRACTION_BAD = [math.nan, math.inf, -math.inf, -0.1, _above(1.0), 2.0, True, "0.5"]
_DURATION_BAD = [math.nan, math.inf, -math.inf, -1.0, -5e-324, True, "1", None]
_STEP_BAD = [*_DURATION_BAD, 0.0, -0.0]
_COUNT_BAD = [0, -1, 1.5, 14.0, True, math.nan, "14", None]

_CALLS: dict[str, Callable[..., Any]] = {
    "night_assessment": lambda **kw: _assess(**kw),
    "resting_hr_on": lambda **kw: resting_hr_on(DAYS, DAY, **{"min_sleep_s": 0, **kw}),
    "resting_hr_at": lambda **kw: resting_hr_at(
        DAYS, at(DAY, 12), **{"min_sleep_s": 0, **kw}
    ),
    "readiness_on_waking": lambda **kw: readiness_on_waking(
        DAYS, DAY, **{"tolerance_s": 0, **kw}
    ),
    "series_between": lambda **kw: series_between(
        DAYS,
        SeriesKind.DAY_HEART_RATE,
        at(DAY, 0),
        at(DAY, 1),
        **{"step_s": 60.0, "min_coverage_fraction": 0.0, **kw},
    ),
    "nights_after": lambda **kw: nights_after(DAYS, at(DAY, 0), **kw),
}

CASES = [
    *(("night_assessment", "max_unmeasured_fraction", v) for v in _FRACTION_BAD),
    *(("night_assessment", "short_sleep_s", v) for v in _DURATION_BAD),
    *(("night_assessment", "shift_s", v) for v in _DURATION_BAD),
    *(("night_assessment", "usual_window_days", v) for v in _COUNT_BAD),
    *(("night_assessment", "usual_min_nights", v) for v in _COUNT_BAD),
    *(("resting_hr_on", "min_sleep_s", v) for v in _DURATION_BAD),
    *(("resting_hr_at", "min_sleep_s", v) for v in _DURATION_BAD),
    *(("readiness_on_waking", "tolerance_s", v) for v in _DURATION_BAD),
    *(("series_between", "step_s", v) for v in _STEP_BAD),
    *(("series_between", "min_coverage_fraction", v) for v in _FRACTION_BAD),
    *(("nights_after", "count", v) for v in _COUNT_BAD),
]


@pytest.mark.parametrize(
    ("call", "name", "value"),
    CASES,
    ids=[f"{call}-{name}-{value!r}" for call, name, value in CASES],
)
def test_a_threshold_out_of_its_domain_names_its_argument(
    call: str, name: str, value: Any
) -> None:
    with pytest.raises(ValueError, match=rf"^{name} "):
        _CALLS[call](**{name: value})


_NUMBER_THRESHOLDS = list(
    dict.fromkeys(
        (call, name)
        for call, name, _ in CASES
        if name not in ("usual_window_days", "usual_min_nights", "count")
    )
)


@pytest.mark.parametrize(
    ("call", "name"),
    _NUMBER_THRESHOLDS,
    ids=[f"{call}-{name}" for call, name in _NUMBER_THRESHOLDS],
)
def test_a_threshold_must_be_finite(call: str, name: str) -> None:
    """``nan`` est refusé comme non fini, avant tout contrôle de son domaine."""
    with pytest.raises(ValueError, match=rf"^{name} doit être fini, reçu nan\.$"):
        _CALLS[call](**{name: math.nan})


def _instant_calls() -> list[tuple[str, Callable[[Any], Any]]]:
    hour = at(DAY, 12)
    kind = SeriesKind.DAY_HEART_RATE
    return [
        ("start", lambda v: sleep_within(DAYS, v, hour)),
        ("end", lambda v: sleep_within(DAYS, at(DAY, 0), v)),
        ("instant", lambda v: body_battery_at(DAYS, v)),
        ("instant", lambda v: night_before(DAYS, v)),
        ("after", lambda v: nights_after(DAYS, v, 1)),
        (
            "instant",
            lambda v: training_status_at(HISTORY, TrainingStatusKind.STATUS, v),
        ),
        ("instant", lambda v: readiness_at(DAYS, v)),
        ("instant", lambda v: resting_hr_at(DAYS, v, min_sleep_s=0)),
        (
            "start",
            lambda v: series_between(
                DAYS, kind, v, hour, step_s=60.0, min_coverage_fraction=0.0
            ),
        ),
        (
            "end",
            lambda v: series_between(
                DAYS, kind, at(DAY, 0), v, step_s=60.0, min_coverage_fraction=0.0
            ),
        ),
    ]


@pytest.mark.parametrize("value", [NAIVE, DAY, "2001-03-10T12:00:00+01:00"])
@pytest.mark.parametrize(("name", "call"), _instant_calls())
def test_an_instant_must_be_aware(
    name: str, call: Callable[[Any], Any], value: Any
) -> None:
    with pytest.raises(ValueError, match=rf"^{name} doit être un instant aware"):
        call(value)


def _days_calls() -> list[Callable[[Any], Any]]:
    hour = at(DAY, 12)
    return [
        lambda d: sleep_within(d, at(DAY, 0), hour),
        lambda d: body_battery_at(d, hour),
        lambda d: night_before(d, hour),
        lambda d: nights_after(d, hour, 1),
        lambda d: readiness_at(d, hour),
        lambda d: night_assessment(d, DAY, **ASSESSMENT),
        lambda d: resting_hr_on(d, DAY, min_sleep_s=0),
        lambda d: resting_hr_at(d, hour, min_sleep_s=0),
        lambda d: readiness_on_waking(d, DAY, tolerance_s=0),
        lambda d: series_between(
            d,
            SeriesKind.DAY_HEART_RATE,
            at(DAY, 0),
            hour,
            step_s=60.0,
            min_coverage_fraction=0.0,
        ),
    ]


@pytest.mark.parametrize("call", _days_calls())
@pytest.mark.parametrize("order", ["unsorted", "duplicate"])
def test_days_must_be_sorted_without_duplicates(
    order: str, call: Callable[[Any], Any]
) -> None:
    days = (DAYS[1], DAYS[0]) if order == "unsorted" else (DAYS[1], DAYS[1])
    with pytest.raises(
        ValueError, match=r"^days doit être trié par jour, sans doublon"
    ):
        call(days)


def _day_calls() -> list[Callable[[Any], Any]]:
    return [
        lambda d: night_assessment(DAYS, d, **ASSESSMENT),
        lambda d: resting_hr_on(DAYS, d, min_sleep_s=0),
        lambda d: readiness_on_waking(DAYS, d, tolerance_s=0),
    ]


@pytest.mark.parametrize("value", [at(DAY, 0), "2001-03-10", None])
@pytest.mark.parametrize("call", _day_calls())
def test_day_must_be_a_date(value: Any, call: Callable[[Any], Any]) -> None:
    with pytest.raises(ValueError, match=r"^day doit être une date"):
        call(value)


def _strict_calls() -> list[Callable[[Any], Any]]:
    hour = at(DAY, 12)
    return [
        lambda s: sleep_within(DAYS, at(DAY, 0), hour, strict=s),
        lambda s: body_battery_at(DAYS, hour, strict=s),
        lambda s: night_before(DAYS, hour, strict=s),
        lambda s: training_status_at(
            HISTORY, TrainingStatusKind.STATUS, hour, strict=s
        ),
        lambda s: readiness_at(DAYS, hour, strict=s),
        lambda s: resting_hr_at(DAYS, hour, min_sleep_s=0, strict=s),
        lambda s: series_between(
            DAYS,
            SeriesKind.DAY_HEART_RATE,
            at(DAY, 0),
            hour,
            step_s=60.0,
            min_coverage_fraction=0.0,
            strict=s,
        ),
    ]


@pytest.mark.parametrize("value", [1, 0, "yes", None])
@pytest.mark.parametrize("call", _strict_calls())
def test_strict_must_be_a_boolean(value: Any, call: Callable[[Any], Any]) -> None:
    with pytest.raises(ValueError, match=r"^strict doit être un booléen"):
        call(value)


def test_kinds_must_be_their_enumerations() -> None:
    with pytest.raises(ValueError, match=r"^kind doit être un TrainingStatusKind"):
        training_status_at(HISTORY, "status", at(DAY, 12))  # type: ignore[arg-type]
    with pytest.raises(ValueError, match=r"^kind doit être un SeriesKind"):
        series_between(
            DAYS,
            "day_heart_rate",  # type: ignore[arg-type]
            at(DAY, 0),
            at(DAY, 1),
            step_s=60.0,
            min_coverage_fraction=0.0,
        )
    with pytest.raises(ValueError, match=r"^kind doit être un SeriesKind"):
        series_between(
            DAYS,
            TrainingStatusKind.STATUS,  # type: ignore[arg-type]
            at(DAY, 0),
            at(DAY, 1),
            step_s=60.0,
            min_coverage_fraction=0.0,
        )


def test_a_date_is_not_mistaken_for_an_instant() -> None:
    """``date`` n'est pas un instant ; un ``datetime`` n'est pas un jour."""
    with pytest.raises(ValueError, match=r"^instant doit être un instant aware"):
        night_before(DAYS, DAY)  # type: ignore[arg-type]
    with pytest.raises(ValueError, match=r"^day doit être une date"):
        resting_hr_on(DAYS, at(DAY, 0), min_sleep_s=0)
    record = day_record(night=night(series=EMPTY_NIGHT_SERIES))
    assert night_before((record,), at(DAY, 8)).day == DAY
