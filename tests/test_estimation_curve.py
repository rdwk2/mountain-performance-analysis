"""L'estimateur de la courbe (``mountain_perf.estimation.curve``, M6b,
``docs/decisions/0017``) : les tranches, la sélection, les écarts, les valeurs (a) et
(b), la vitesse écoulée, les comptes par étage, le filtre de FC, le niveau, la forme,
les lignes du fichier et le document du compagnon.

Les intervalles sont construits à la main (:func:`interval`) : leurs pentes se posent
aux centres des tranches (:data:`GRADES`) quand un niveau nul est attendu — le niveau
lit la courbe comme le moteur, prolongement compris."""

from __future__ import annotations

import math
from collections.abc import Sequence
from datetime import date, datetime, timedelta, timezone
from itertools import pairwise
from typing import Any

import pytest

from mountain_perf.estimation.curve import (
    CURVE_BIN_EDGES_PERMILLE,
    CURVE_ESTIMATION_PARAMETER_SPECS,
    ActivityExclusion,
    BinValue,
    CurveEstimate,
    CurveSelection,
    EstimatedBin,
    IntervalExclusion,
    bin_index,
    estimate_curve,
    select_candidates,
)
from mountain_perf.estimation.intervals import (
    ActivityIntervals,
    CurveInterval,
    TraceRefusal,
)
from mountain_perf.model.curve_io import CurveError
from mountain_perf.schemas import ActivityIndex, ParameterSet
from mountain_perf.validation import ContractError
from test_ingest_interim import INDEX_SOURCE
from test_schemas_interim import entry

PLUS2 = timezone(timedelta(hours=2))
DEFAULTS = ParameterSet(CURVE_ESTIMATION_PARAMETER_SPECS)

GRADES = [-0.175, -0.1125, 0.0125, 0.1125, 0.2125]
"""Des centres de tranches : ni interpolation ni prolongement."""


def interval(
    grade: float,
    length_m: float = 50.0,
    moving_s: float = 50.0,
    *,
    start_s: float = 0.0,
    stopped_s: float = 0.0,
    heart_rate_bpm: float | None = None,
) -> CurveInterval:
    """Un intervalle d'écoulé ``moving_s + stopped_s``, sans temps U."""
    return CurveInterval(
        length_m=length_m,
        grade=grade,
        start_s=start_s,
        end_s=start_s + moving_s + stopped_s,
        moving_s=moving_s,
        stopped_s=stopped_s,
        undetermined_s=0.0,
        heart_rate_bpm=heart_rate_bpm,
    )


def activity(
    ref: str,
    intervals: list[CurveInterval],
    elapsed_s: float = 3600.0,
    *,
    ceiling_s: float | None = None,
    after_ceiling: int = 0,
) -> ActivityIntervals:
    return ActivityIntervals(ref, elapsed_s, tuple(intervals), ceiling_s, after_ceiling)


def uniform(
    ref: str, speed_ms: float, grades: list[float], seconds: float = 900.0
) -> ActivityIntervals:
    """Une activité à ``speed_ms`` sur chaque pente de ``grades``, ``seconds`` de temps
    M par pente, en intervalles de 50 m."""
    count = round(seconds * speed_ms / 50)
    return activity(
        ref,
        [interval(g, 50.0, 50.0 / speed_ms) for g in grades for _ in range(count)],
    )


def selection(**changes: Any) -> CurveSelection:
    base: dict[str, Any] = {
        "source_activity_types": frozenset({"trail_running"}),
        "date_from": date(2024, 1, 1),
        "date_to": date(2024, 12, 31),
        "min_duration_s": None,
        "max_duration_s": None,
        "max_elapsed_s": None,
        "hr_center_bpm": None,
        "value": BinValue.POOLED,
    }
    return CurveSelection(**{**base, **changes})


def estimate(
    activities: Sequence[ActivityIntervals | TraceRefusal],
    chosen: CurveSelection | None = None,
    parameters: ParameterSet = DEFAULTS,
) -> CurveEstimate:
    """L'estimation de ``activities``, chacune nommée par sa référence, chaque refus
    ``refus<k>``."""
    refs = [
        a.activity_ref if isinstance(a, ActivityIntervals) else f"refus{k}"
        for k, a in enumerate(activities)
    ]
    return estimate_curve(activities, refs, chosen or selection(), parameters)


def only(result: CurveEstimate) -> EstimatedBin:
    assert len(result.bins) == 1
    return result.bins[0]


def by_lower(result: CurveEstimate) -> dict[int, EstimatedBin]:
    return {b.lower_permille: b for b in result.bins}


# --- Les tranches -------------------------------------------------------------------


def test_the_bins() -> None:
    """Des bornes entières de −1 000 à 1 000 pour mille : 100 au-delà de ±400, 50 de
    −400 à −150 et de 350 à 400, 25 ailleurs ; 38 tranches (``0017``, P3.1)."""
    edges = CURVE_BIN_EDGES_PERMILLE
    assert edges[0] == -1000
    assert edges[-1] == 1000
    assert len(set(edges)) == len(edges) == 39
    for lower, upper in pairwise(edges):
        if lower >= 400 or upper <= -400:
            assert upper - lower == 100
        elif upper <= -150 or lower >= 350:
            assert upper - lower == 50
        else:
            assert upper - lower == 25


@pytest.mark.parametrize(
    ("grade", "lower"),
    [
        (-1.0, -1000),
        (-0.4, -400),
        (-0.15, -150),
        (-0.0001, -25),
        (0.0, 0),
        (0.0249, 0),
        (0.025, 25),
        (0.35, 350),
        (0.3999, 350),
        (0.4, 400),
        (0.9999, 900),
        (math.nextafter(-0.4, -math.inf), -500),
        (math.nextafter(-0.15, -math.inf), -200),
        (math.nextafter(0.0, -math.inf), -25),
        (math.nextafter(0.35, -math.inf), 325),
        (math.nextafter(0.4, -math.inf), 350),
        (math.nextafter(1.0, -math.inf), 900),
    ],
)
def test_bin_index(grade: float, lower: int) -> None:
    """Une tranche est ``[lo ; hi[`` : la borne basse comprise, la haute non (S13 :
    juste sous une borne)."""
    k = bin_index(grade)
    assert k is not None
    assert CURVE_BIN_EDGES_PERMILLE[k] == lower


@pytest.mark.parametrize("grade", [-1.0001, 1.0, 1.5, -2.0])
def test_bin_index_outside_the_domain(grade: float) -> None:
    assert bin_index(grade) is None


# --- La valeur ----------------------------------------------------------------------


def test_the_pooled_value() -> None:
    """(a) : somme des longueurs sur somme des temps M (``0017``, P3.3)."""
    result = estimate(
        [
            activity("a", [interval(0.01, 50, 25), interval(0.01, 50, 25)]),
            activity("b", [interval(0.01, 50, 100)]),
        ]
    )
    b = only(result)
    assert b.speed_ms == 1.0
    assert b.activity_count == 2
    assert b.moving_s == 150.0
    assert (b.lower_permille, b.upper_permille) == (0, 25)
    assert b.center_grade == 0.0125


def s01(
    scale: float = 1.0, reverse: bool = False
) -> list[ActivityIntervals | TraceRefusal]:
    outings: list[ActivityIntervals | TraceRefusal] = [
        activity(ref, [interval(0.01, speed * seconds * scale, seconds * scale)])
        for ref, speed, seconds in (
            ("a", 2.0, 60.0),
            ("b", 2.0, 60.0),
            ("c", 1.0, 600.0),
        )
    ]
    return outings[::-1] if reverse else outings


def test_s01_pooled_and_median() -> None:
    """S01 : trois sorties à 2, 2 et 1 m/s pendant 60, 60 et 600 s ; (a) pèse par le
    temps, (b) par activité."""
    pooled = only(estimate(s01()))
    median = only(estimate(s01(), selection(value=BinValue.MEDIAN)))
    assert pooled.speed_ms == 840.0 / 720.0
    assert median.speed_ms == 2.0
    assert pooled.activity_count == median.activity_count == 3
    again = only(estimate(s01(scale=3.0, reverse=True)))
    assert again.speed_ms == pytest.approx(840.0 / 720.0, rel=1e-15)


def test_pooled_against_median() -> None:
    """(a) contre (b) : avec (b), le temps de la tranche est celui des activités de la
    médiane (``0017``, P3.5)."""
    outings: list[ActivityIntervals | TraceRefusal] = [
        activity(ref, [interval(0.01, length, seconds)])
        for ref, length, seconds in (
            ("a", 600.0, 300.0),
            ("b", 120.0, 120.0),
            ("c", 360.0, 120.0),
            ("d", 30.0, 30.0),
        )
    ]
    pooled = only(estimate(outings))
    median = only(estimate(outings, selection(value=BinValue.MEDIAN)))
    assert pooled.speed_ms == 1110 / 570
    assert median.speed_ms == 2.0
    assert (pooled.activity_count, median.activity_count) == (4, 3)
    assert (pooled.moving_s, median.moving_s) == (570.0, 540.0)
    assert median.moving_total_s == 570.0
    assert pooled.max_moving_share == 300 / 570


def test_s08_the_median_threshold() -> None:
    """S08 : onze activités à 59 s et une à 60 s : (b) ne garde que celle-ci."""
    outings: list[ActivityIntervals | TraceRefusal] = [
        activity(f"a{k}", [interval(0.01, 59.0, 59.0)]) for k in range(11)
    ]
    outings.append(activity("b", [interval(0.01, 120.0, 60.0)]))
    median = only(estimate(outings, selection(value=BinValue.MEDIAN)))
    assert median.speed_ms == 2.0
    assert median.moving_s == 60.0
    assert median.activity_count == 1
    assert median.moving_total_s == 11 * 59 + 60
    assert median.moving_activities == 12
    pooled = only(estimate(outings))
    assert pooled.moving_s == pooled.moving_total_s


def test_the_median_of_an_even_count() -> None:
    """(b), un nombre pair : la moyenne des deux vitesses du milieu, pas de leurs
    logarithmes (``0017``, P3.4)."""
    outings: list[ActivityIntervals | TraceRefusal] = [
        activity("a", [interval(0.01, 60.0, 60.0)]),
        activity("b", [interval(0.01, 180.0, 60.0)]),
    ]
    assert only(estimate(outings, selection(value=BinValue.MEDIAN))).speed_ms == 2.0


def test_the_median_threshold_is_inclusive() -> None:
    outings: list[ActivityIntervals | TraceRefusal] = [
        activity("a", [interval(0.01, 60.0, 60.0)]),
        activity("b", [interval(0.01, 3 * 59.999, 59.999)]),
    ]
    median = only(estimate(outings, selection(value=BinValue.MEDIAN)))
    assert median.speed_ms == 1.0
    assert median.activity_count == 1


def test_a_median_bin_without_an_activity_at_the_threshold_does_not_exist() -> None:
    outings: list[ActivityIntervals | TraceRefusal] = [
        activity("a", [interval(0.01, 0.3, 30.0), interval(0.2, 120.0, 600.0)])
    ]
    median = only(estimate(outings, selection(value=BinValue.MEDIAN)))
    assert median.lower_permille == 200


# --- Le temps M et l'écoulé ---------------------------------------------------------


def test_an_interval_without_moving_time() -> None:
    """Un intervalle sans temps M porte un arrêt : il compte dans la vitesse écoulée,
    pas dans la valeur (``0017``, P1.5, P1.6)."""
    result = estimate(
        [
            activity(
                "a",
                [interval(0.01, 50, 50), interval(0.01, 10, 0, stopped_s=40)],
            )
        ]
    )
    b = only(result)
    assert b.speed_ms == 1.0
    assert b.elapsed_speed_ms == 60 / 90
    assert b.activity_count == 1


def test_a_bin_of_intervals_without_moving_time_does_not_exist() -> None:
    result = estimate(
        [
            activity(
                "a",
                [interval(0.01, 50, 50), interval(0.1, 10, 0, stopped_s=40)],
            )
        ]
    )
    assert [b.lower_permille for b in result.bins] == [0]


@pytest.mark.parametrize("apart", [False, True])
def test_s06_moving_and_elapsed(apart: bool) -> None:
    """S06 : 50 m en 100 s, puis 50 m sans M en 10 s, dans une même activité et dans
    deux (l'intervalle sans M seul dans la sienne : une cellule sans temps M)."""
    moving, stopped = interval(0.01, 50, 100), interval(0.01, 50, 0, stopped_s=10)
    outings: list[ActivityIntervals | TraceRefusal] = (
        [activity("a", [moving]), activity("b", [stopped])]
        if apart
        else [activity("a", [moving, stopped])]
    )
    result = estimate(outings)
    b = only(result)
    assert b.speed_ms == 0.5
    assert b.elapsed_speed_ms == 100.0 / 110.0
    assert result.elapsed_moving_ratio == pytest.approx(1.1, abs=1e-15)
    assert b.length_moving_m == 50.0
    assert b.length_all_m == 100.0
    assert b.elapsed_total_s == 110.0


def test_s15_a_tiny_moving_time() -> None:
    """S15 : la vitesse en mouvement n'est pas un motif d'écart (``0017``, P3.6)."""
    still = interval(0.01, 50, 0, stopped_s=10)
    assert (
        only(estimate([activity("a", [interval(0.01, 50, 25), still])])).speed_ms == 2.0
    )
    tiny = interval(0.01, 50, 1e-9, stopped_s=10)
    result = estimate([activity("a", [interval(0.01, 50, 25), tiny])])
    assert only(result).speed_ms == 100 / (25 + 1e-9)
    assert result.excluded_intervals == ()


def test_the_elapsed_to_moving_ratio() -> None:
    result = estimate(
        [
            activity(
                "a",
                [interval(0.01, 50, 50, stopped_s=10), interval(0.1, 50, 50)],
            )
        ]
    )
    assert result.elapsed_moving_ratio == 110 / 100


def test_the_mean_heart_rate_is_weighted_by_moving_time() -> None:
    result = estimate(
        [
            activity(
                "a",
                [
                    interval(0.01, 30, 30, heart_rate_bpm=120.0),
                    interval(0.01, 90, 90, heart_rate_bpm=160.0),
                    interval(0.01, 50, 50),
                ],
            )
        ]
    )
    assert only(result).mean_hr_bpm == (120 * 30 + 160 * 90) / 120
    plain = estimate([activity("a", [interval(0.01, 50, 50)])])
    assert only(plain).mean_hr_bpm is None


# --- Les écarts ---------------------------------------------------------------------


def test_the_exclusions() -> None:
    """Chaque intervalle est écarté au premier motif ; ceux retirés au plafond sont
    comptés (``0017``, P2.4, P2.6, P3.6)."""
    outing = activity(
        "a",
        [
            interval(0.01, 50, 50),
            interval(1.0, 50, 50),
            interval(0.01, 50, 0),
            interval(0.01, 50, 5),
            interval(0.5, 400, 200),
            interval(-0.5, 600, 200),
        ],
        ceiling_s=7200.0,
        after_ceiling=4,
    )
    result = estimate([outing], selection(max_elapsed_s=7200.0))
    assert dict(result.excluded_intervals) == {
        IntervalExclusion.CEILING: 4,
        IntervalExclusion.GRADE: 1,
        IntervalExclusion.NO_ELAPSED: 1,
        IntervalExclusion.ABERRANT: 3,
    }
    assert only(result).lower_permille == 0
    assert result.counts.intervals == 10
    with pytest.raises(ValueError, match="plafond"):
        estimate([outing])


def test_a_grade_outside_the_domain_with_no_elapsed_is_counted_once() -> None:
    result = estimate([activity("a", [interval(0.01, 50, 50), interval(1.5, 50, 0)])])
    assert dict(result.excluded_intervals) == {IntervalExclusion.GRADE: 1}


def test_thresholds_reached_are_kept() -> None:
    """Les seuils atteints sont gardés ; juste au-delà, écartés."""
    parameters = ParameterSet(
        CURVE_ESTIMATION_PARAMETER_SPECS,
        {
            "max_elapsed_speed_ms": 5.0,
            "max_ascent_speed_ms": 0.5,
            "max_descent_speed_ms": 0.5,
        },
    )
    at = [interval(0.01, 50, 10), interval(0.5, 10, 10), interval(-0.5, 10, 10)]
    beyond = [
        interval(0.01, 50, 9.999),
        interval(0.5, 10, 9.999),
        interval(-0.5, 10, 9.999),
    ]
    result = estimate([activity("a", at + beyond)], parameters=parameters)
    assert dict(result.excluded_intervals) == {IntervalExclusion.ABERRANT: 3}
    assert result.counts.retained_intervals == 3


def test_the_vertical_speed_is_signed() -> None:
    """400 m à −50 % en 200 s : −1 m/s, sous le seuil de descente, gardé."""
    result = estimate([activity("a", [interval(-0.5, 400, 200)])])
    assert result.excluded_intervals == ()


def test_s11_a_fast_interval_is_kept() -> None:
    assert only(estimate([activity("a", [interval(0.1, 50, 10)])])).speed_ms == 5.0


# --- Les activités ------------------------------------------------------------------


def test_the_activities() -> None:
    """Un écart de chaque motif ; la durée minimale comprise, la maximale exclue
    (``0017``, P2.3)."""
    sane = [interval(0.01, 50, 50)]
    chosen = selection(min_duration_s=1800.0, max_duration_s=7200.0)
    result = estimate(
        [
            TraceRefusal.NO_TRACE,
            TraceRefusal.NO_PROFILE,
            activity("court", sane, 1799.0),
            activity("juste", sane, 1800.0),
            activity("long", sane, 7200.0),
            activity("hors", [interval(1.5, 50, 50)]),
        ],
        chosen,
    )
    assert result.activity_refs == ("juste",)
    assert dict(result.excluded_activities) == {
        ActivityExclusion.NO_TRACE: 1,
        ActivityExclusion.NO_PROFILE: 1,
        ActivityExclusion.SHORT: 1,
        ActivityExclusion.LONG: 1,
        ActivityExclusion.NO_INTERVAL: 1,
    }
    with pytest.raises(CurveError, match="Aucune tranche"):
        estimate([TraceRefusal.NO_TRACE, activity("court", sane, 60.0)], chosen)


def test_no_bin_says_why() -> None:
    """Une activité retenue peut n'avoir aucun intervalle en mouvement."""
    still = activity("a", [interval(-0.2, 10, 0, stopped_s=30)])
    with pytest.raises(
        CurveError, match="aucun intervalle retenu n'a de temps en mouvement"
    ):
        estimate([still])
    short = activity("a", [interval(0.01, 30, 30)])
    with pytest.raises(
        CurveError, match="aucune activité n'a 60 s de temps en mouvement"
    ):
        estimate([short], selection(value=BinValue.MEDIAN))


def test_the_ceiling_of_the_intervals_is_the_declared_one() -> None:
    sane = [interval(0.01, 50, 50)]
    with pytest.raises(ValueError, match="plafond"):
        estimate([activity("a", sane)], selection(max_elapsed_s=7200.0))
    with pytest.raises(ValueError, match="plafond"):
        estimate([activity("a", sane, ceiling_s=7200.0)])


# --- La sélection -------------------------------------------------------------------


def test_select_candidates() -> None:
    """Le jour civil local du départ, bornes comprises, et les seuls types déclarés
    (``0017``, P2.1, P2.2)."""
    index = ActivityIndex(
        (
            entry(
                source=INDEX_SOURCE,
                activity_ref="avant",
                start_time=datetime(2023, 12, 31, 23, 59, tzinfo=PLUS2),
            ),
            entry(
                source=INDEX_SOURCE,
                activity_ref="premier",
                start_time=datetime(2024, 1, 1, 0, 30, tzinfo=PLUS2),
            ),
            entry(
                source=INDEX_SOURCE,
                activity_ref="velo",
                source_activity_type="cycling",
                start_time=datetime(2024, 6, 1, 9, tzinfo=PLUS2),
            ),
            entry(
                source=INDEX_SOURCE,
                activity_ref="sans",
                has_recording=False,
                start_time=datetime(2024, 7, 1, 9, tzinfo=PLUS2),
            ),
            entry(
                source=INDEX_SOURCE,
                activity_ref="dernier",
                start_time=datetime(2024, 12, 31, 23, 59, tzinfo=PLUS2),
            ),
            entry(
                source=INDEX_SOURCE,
                activity_ref="apres",
                start_time=datetime(2025, 1, 1, 0, 0, tzinfo=PLUS2),
            ),
        ),
        (INDEX_SOURCE,),
    )
    refs = [e.activity_ref for e in select_candidates(index, selection())]
    assert refs == ["premier", "dernier"]
    both = selection(source_activity_types=frozenset({"trail_running", "cycling"}))
    refs = [e.activity_ref for e in select_candidates(index, both)]
    assert refs == ["premier", "velo", "dernier"]


@pytest.mark.parametrize(
    ("changes", "message"),
    [
        ({"source_activity_types": frozenset()}, "au moins un type"),
        ({"source_activity_types": frozenset({""})}, "source_activity_types"),
        ({"date_from": date(2025, 1, 1)}, "date_from"),
        ({"min_duration_s": -1.0}, "min_duration_s"),
        ({"max_duration_s": 0.0}, "max_duration_s"),
        ({"max_elapsed_s": 0.0}, "max_elapsed_s"),
        ({"max_elapsed_s": math.inf}, "max_elapsed_s"),
        ({"min_duration_s": 60.0, "max_duration_s": 60.0}, "max_duration_s"),
        ({"hr_center_bpm": 10.0}, "hr_center_bpm"),
        ({"hr_center_bpm": math.nan}, "hr_center_bpm"),
    ],
)
def test_the_selection_is_refused(changes: dict[str, Any], message: str) -> None:
    with pytest.raises(ContractError, match=message):
        selection(**changes)
