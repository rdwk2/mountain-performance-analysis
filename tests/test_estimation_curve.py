"""L'estimateur de la courbe (``mountain_perf.estimation.curve``, M6b,
``docs/decisions/0017``) : les tranches, la sélection, les écarts, les valeurs (a) et
(b), la vitesse écoulée, les comptes par étage, le filtre de FC, le niveau, la forme,
les lignes du fichier et le document du compagnon.

Les intervalles sont construits à la main (:func:`interval`) : leurs pentes se posent
aux centres des tranches (:data:`GRADES`) quand un niveau nul est attendu — le niveau
lit la courbe comme le moteur, prolongement compris."""

from __future__ import annotations

import json
import math
from collections.abc import Sequence
from datetime import UTC, date, datetime, timedelta, timezone
from itertools import pairwise
from typing import Any

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from mountain_perf.estimation.curve import (
    CURVE_BIN_EDGES_PERMILLE,
    CURVE_ESTIMATION_PARAMETER_SPECS,
    SUPPORT_THRESHOLD_MIN,
    ActivityExclusion,
    BinValue,
    CurveEstimate,
    CurveSelection,
    EstimatedBin,
    IntervalExclusion,
    bin_index,
    curve_file_rows,
    estimate_curve,
    estimation_document,
    rank_quantile,
    select_candidates,
)
from mountain_perf.estimation.intervals import (
    ActivityIntervals,
    CurveInterval,
    TraceRefusal,
)
from mountain_perf.gpx.profile import PROFILE_PARAMETER_SPECS
from mountain_perf.model.curve_io import CurveError, check_curve_rows
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


# --- Le rang, le filtre de FC, le niveau et la forme ----------------------------------


@pytest.mark.parametrize(
    ("n", "a", "b", "rank"),
    [
        (1, 1, 10, 1),
        (1, 9, 10, 1),
        (10, 1, 10, 1),
        (10, 9, 10, 9),
        (11, 1, 10, 2),
        (11, 9, 10, 10),
        (4, 1, 2, 2),
        (5, 1, 2, 3),
        (5, 1, 4, 2),
        (5, 3, 4, 4),
    ],
)
def test_rank_quantile(n: int, a: int, b: int, rank: int) -> None:
    """La valeur de rang ``⌈n·a/b⌉`` des valeurs triées (``0017``, P4.2)."""
    values = [10.0 * k for k in range(n, 0, -1)]
    assert rank_quantile(values, a, b) == 10.0 * rank


@pytest.mark.parametrize(
    ("values", "expected"),
    [
        ([7.0], (7.0, 7.0, 7.0)),
        ([2.0, 1.0], (1.0, 1.0, 2.0)),
        ([4.0, 3.0, 2.0, 1.0], (1.0, 2.0, 4.0)),
        ([5.0, 4.0, 3.0, 2.0, 1.0], (1.0, 3.0, 5.0)),
        ([float(k) for k in range(9, 0, -1)], (1.0, 5.0, 9.0)),
        ([float(k) for k in range(10, 0, -1)], (1.0, 5.0, 9.0)),
    ],
)
def test_s14_the_level_quantiles(
    values: list[float], expected: tuple[float, float, float]
) -> None:
    """S14 : ``n = 1`` ponctuel ; p50 est la médiane inférieure."""
    got = tuple(rank_quantile(values, a, b) for a, b in ((1, 10), (1, 2), (9, 10)))
    assert got == expected


def test_the_interquartile_range_of_five() -> None:
    values = [4.0, 0.0, 2.0, 3.0, 1.0]
    assert rank_quantile(values, 3, 4) - rank_quantile(values, 1, 4) == 2.0


def test_s12_an_unreadable_slice_is_said() -> None:
    """S12 : aucun écart (la vitesse en mouvement n'en est pas un), mais la tranche
    serait illisible par ``read_curve`` : l'erreur dit laquelle."""
    outings: list[ActivityIntervals | TraceRefusal] = [
        uniform(f"u{k}", 2.0, GRADES) for k in range(5)
    ]
    outings.append(activity("v", [interval(0.05, 50, 0.1, stopped_s=19.9)]))
    result = estimate(outings)
    assert result.excluded_intervals == ()
    assert by_lower(result)[50].speed_ms == pytest.approx(500.0)
    with pytest.raises(CurveError) as caught:
        check_curve_rows(curve_file_rows(result), SUPPORT_THRESHOLD_MIN)
    assert str(caught.value).startswith("La tranche 6.25 % serait illisible")
    assert "km/h" in str(caught.value)


def test_the_heart_rate_filter() -> None:
    """Le filtre de FC, aux pentes de −5 % ou plus seulement, bande fermée
    (``0017``, P5.2)."""
    intervals = [
        interval(-0.0501),
        interval(-0.05),
        interval(-0.05, heart_rate_bpm=150.0),
        interval(0.1, heart_rate_bpm=155.0),
        interval(0.1, heart_rate_bpm=145.0),
        interval(0.1, heart_rate_bpm=155.001),
        interval(0.1, heart_rate_bpm=144.999),
    ]
    result = estimate([activity("a", intervals)], selection(hr_center_bpm=150.0))
    assert dict(result.excluded_intervals) == {
        IntervalExclusion.HR_UNDEFINED: 1,
        IntervalExclusion.HR_OUTSIDE: 2,
    }
    assert {k: b.moving_s for k, b in by_lower(result).items()} == {
        -75: 50.0,
        -50: 50.0,
        100: 100.0,
    }
    assert estimate([activity("a", intervals)]).excluded_intervals == ()


def test_s16_the_filter_selects_observations() -> None:
    """S16 : une courbe filtrée est une sélection descriptive ; sous −5 %, les
    observations ne sont pas filtrées."""
    intervals = [
        *(interval(-0.0625, 50, 25, heart_rate_bpm=120.0) for _ in range(20)),
        *(interval(-0.0375, 50, 25, heart_rate_bpm=150.0) for _ in range(20)),
        *(interval(-0.0375, 50, 50, heart_rate_bpm=120.0) for _ in range(20)),
        *(interval(-0.0125, 50, 25, heart_rate_bpm=150.0) for _ in range(20)),
    ]
    plain = by_lower(estimate([activity("a", intervals)]))
    filtered = by_lower(
        estimate([activity("a", intervals)], selection(hr_center_bpm=150.0))
    )
    assert plain[-50].speed_ms == 2000 / 1500
    assert filtered[-50].speed_ms == 2.0
    assert plain[-75].speed_ms == filtered[-75].speed_ms == 2.0


def test_s22_the_counts_by_stage() -> None:
    """S22 : les comptes par étage (``0017``, P2.6, P5.3)."""
    outings: list[ActivityIntervals | TraceRefusal] = [
        TraceRefusal.NO_TRACE,
        activity("court", [interval(0.0, heart_rate_bpm=150.0)], 60.0),
        activity("hors", [interval(0.0, heart_rate_bpm=170.0)]),
        activity("arret", [interval(-0.2, 10, 0, stopped_s=30)]),
        activity("descente", [interval(-0.2, 50, 40)]),
        activity(
            "pleine", [interval(0.0, heart_rate_bpm=150.0), interval(-0.2, 50, 40)]
        ),
    ]
    chosen = selection(min_duration_s=600.0, hr_center_bpm=150.0)
    counts = estimate(outings, chosen).counts
    assert (counts.candidates, counts.with_intervals, counts.eligible) == (6, 5, 4)
    assert (counts.retained, counts.moving) == (3, 2)
    assert (counts.filtered_side, counts.descents_only) == (1, 1)
    assert counts.retained_intervals == 4
    assert counts.retained_without_moving == 1
    assert counts.length_all_m == 160.0
    assert counts.length_moving_m == 150.0
    assert counts.moving_s == 130.0
    assert dict(counts.excluded_length_m) == {IntervalExclusion.HR_OUTSIDE: 50.0}
    unfiltered = estimate(outings, selection(min_duration_s=600.0)).counts
    assert unfiltered.filtered_side is None
    assert unfiltered.descents_only is None


def test_an_activity_without_moving_time_has_no_level() -> None:
    outings: list[ActivityIntervals | TraceRefusal] = [
        uniform(f"u{k}", 2.0, GRADES) for k in range(5)
    ]
    outings.append(activity("arret", [interval(0.0125, 10, 0, stopped_s=60)]))
    result = estimate(outings)
    assert result.counts.retained == 6
    assert result.counts.moving == 5
    assert result.counts.with_level == 5
    assert result.level is not None
    assert result.level.count == 5


def test_the_level_and_the_shape_of_the_curve_itself() -> None:
    """Cinq activités qui courent la courbe : niveau nul, formes nulles."""
    result = estimate([uniform(f"u{k}", 2.0, GRADES) for k in range(5)])
    level = result.level
    assert level is not None
    assert level.count == 5
    for quantile in (level.p10, level.p50, level.p90):
        assert quantile == pytest.approx(0.0, abs=1e-12)
    for b in result.bins:
        assert b.shape_activity_count == 5
        assert b.shape_iqr == pytest.approx(0.0, abs=1e-12)


@settings(deadline=None)
@given(st.lists(st.floats(min_value=0.5, max_value=2.0), min_size=5, max_size=8))
def test_the_level_absorbs_a_factor_per_activity(factors: list[float]) -> None:
    """Une vitesse multipliée par ``f`` par activité : le niveau la prend, la forme
    reste nulle (``0017``, P4.3)."""
    result = estimate(
        [uniform(f"u{k}", f, GRADES, 1800 / f) for k, f in enumerate(factors)]
    )
    level = result.level
    assert level is not None
    logs = [-math.log(f) for f in factors]
    shift = level.p50 - rank_quantile(logs, 1, 2)
    assert level.p10 == pytest.approx(rank_quantile(logs, 1, 10) + shift, abs=1e-9)
    assert level.p90 == pytest.approx(rank_quantile(logs, 9, 10) + shift, abs=1e-9)
    for b in result.bins:
        assert b.shape_iqr == pytest.approx(0.0, abs=1e-9)


def test_the_level_reads_the_moving_time_of_moving_intervals_only() -> None:
    """Une sixième activité qui court la courbe avec 5 s d'arrêt dans chaque intervalle
    et vingt intervalles sans M : son niveau est nul."""
    outings: list[ActivityIntervals | TraceRefusal] = [
        uniform(f"u{k}", 2.0, GRADES) for k in range(5)
    ]
    sixth = [interval(g, 50, 25, stopped_s=5) for g in GRADES for _ in range(36)]
    sixth += [interval(0.0125, 50, 0, stopped_s=30) for _ in range(20)]
    outings.append(activity("six", sixth))
    level = estimate(outings).level
    assert level is not None
    assert level.count == 6
    assert level.p10 == pytest.approx(0.0, abs=1e-12)
    assert level.p90 == pytest.approx(0.0, abs=1e-12)


def test_the_shape_needs_five_activities() -> None:
    four = estimate([uniform(f"u{k}", 2.0, GRADES) for k in range(4)])
    for b in four.bins:
        assert b.shape_iqr is None
        assert b.shape_activity_count == 4
    short = [uniform(f"u{k}", 2.0, GRADES) for k in range(4)]
    short.append(uniform("court", 2.0, GRADES, 100.0))
    for b in estimate(list(short)).bins:
        assert b.shape_iqr is None
        assert b.shape_activity_count == 4


@pytest.mark.parametrize(("seconds", "count"), [(119.999, 5), (120.0, 6)])
def test_the_shape_threshold_is_inclusive(seconds: float, count: int) -> None:
    outings: list[ActivityIntervals | TraceRefusal] = [
        uniform(f"u{k}", 2.0, GRADES) for k in range(5)
    ]
    outings.append(activity("six", [interval(0.0125, 2 * seconds, seconds)]))
    assert by_lower(estimate(outings))[0].shape_activity_count == count


def test_zero_thresholds_keep_cells_without_moving_time_out() -> None:
    """À des seuils nuls, une cellule sans temps M reste dehors : jamais
    ``ln(0 / 0)``."""
    outings: list[ActivityIntervals | TraceRefusal] = [
        uniform(f"u{k}", 2.0, GRADES) for k in range(5)
    ]
    outings.append(activity("arret", [interval(0.0125, 10, 0, stopped_s=60)]))
    parameters = ParameterSet(
        CURVE_ESTIMATION_PARAMETER_SPECS,
        {"shape_min_moving_s": 0.0, "median_min_moving_s": 0.0},
    )
    result = estimate(outings, parameters=parameters)
    assert by_lower(result)[0].shape_activity_count == 5
    counts = result.counts
    assert (counts.retained, counts.moving, counts.median) == (6, 5, 5)


def test_without_support_there_is_no_level_and_no_shape() -> None:
    result = estimate([uniform("u", 2.0, GRADES, 60.0)])
    assert result.bins
    assert result.level is None
    for b in result.bins:
        assert b.shape_iqr is None
        assert b.shape_activity_count == 0


def test_s02_the_shape_is_read_against_the_engine() -> None:
    """S02 : six activités qui suivent exactement ``p(g) = 0,4 + 2g`` s/m, chacune
    d'un côté du centre des tranches intérieures : la forme se lit contre le temps
    prévu par le moteur, pas contre la vitesse de la tranche (``0017``, P4.3)."""
    centres = [-0.0375, -0.0125, 0.0125, 0.0375, 0.0625]

    def pace(g: float) -> float:
        return 0.4 + 2 * g

    outings: list[ActivityIntervals | TraceRefusal] = []
    for k in range(6):
        side = -0.005 if k < 3 else 0.005
        intervals = []
        for c in centres:
            g = c if c in (centres[0], centres[-1]) else c + side
            intervals += [interval(g, 50, 50 * pace(g)) for _ in range(12)]
        outings.append(activity(f"a{k}", intervals))
    result = estimate(outings)
    level = result.level
    assert level is not None
    for quantile in (level.p10, level.p50, level.p90):
        assert quantile == pytest.approx(0.0, abs=1e-12)
    for b in result.bins:
        assert b.shape_activity_count == 6
        assert b.shape_iqr == pytest.approx(0.0, abs=1e-12)
    for b in result.bins[1:-1]:
        assert b.mean_grade == pytest.approx(b.center_grade, abs=1e-12)
        assert b.n_eff_moving == pytest.approx(6, rel=0.01)


# --- Le fichier et le compagnon -----------------------------------------------------


def test_the_file_rows() -> None:
    """Une ligne par tranche ; la pente est le centre nominal, écrit exactement."""
    edges = CURVE_BIN_EDGES_PERMILLE
    outing = activity("a", [interval((lo + 1) / 1000, 50, 500) for lo in edges[:-1]])
    rows = curve_file_rows(estimate([outing]))
    assert len(rows) == 38
    for row, (lo, hi) in zip(rows, pairwise(edges), strict=True):
        assert float(row.grade_pct) == (lo + hi) / 20
        assert row.grade_pct == f"{float(row.grade_pct):g}"
    texts = {row.grade_pct for row in rows}
    for text in ("-95", "-37.5", "-13.75", "-1.25", "1.25", "33.75", "37.5", "95"):
        assert text in texts


def five() -> CurveEstimate:
    return estimate([uniform(f"u{k}", 2.0, GRADES) for k in range(5)])


def document(result: CurveEstimate, exports: list[datetime]) -> dict[str, object]:
    return estimation_document(
        result,
        selection(),
        DEFAULTS,
        ParameterSet(PROFILE_PARAMETER_SPECS),
        commit="c" * 40,
        exports_retrieved_at=exports,
        support_error=None,
    )


def test_the_estimation_document() -> None:
    result = five()
    same = [
        datetime(2024, 4, 1, 12, tzinfo=PLUS2),
        datetime(2024, 4, 1, 10, tzinfo=UTC),
    ]
    doc = document(result, same)
    json.dumps(doc, allow_nan=False)
    assert doc["value"] == "somme"
    assert doc["bin_edges_permille"] == list(CURVE_BIN_EDGES_PERMILLE)
    level = doc["level"]
    assert isinstance(level, dict)
    assert level["count"] == 5
    assert doc["exports_retrieved_at"] == ["2024-04-01T10:00:00+00:00"]
    parameters = doc["parameters"]
    assert isinstance(parameters, dict)
    assert list(parameters) == [spec.name for spec in CURVE_ESTIMATION_PARAMETER_SPECS]
    assert doc["projectable"] is True
    assert doc["support_error"] is None
    counts = doc["counts"]
    assert isinstance(counts, dict)
    assert counts["candidates"] == 5
    bins = doc["bins"]
    assert isinstance(bins, list)
    assert len(bins) == len(result.bins)
    integration = doc["heart_rate_integration"]
    assert isinstance(integration, str)
    assert integration.startswith("exacte")


def test_the_export_instants_are_sorted_as_instants() -> None:
    """``12:00`` à +02:00 (10 h UTC) vient avant ``11:00`` UTC, que l'ordre des textes
    mettrait devant."""
    received = [
        datetime(2024, 4, 1, 11, tzinfo=UTC),
        datetime(2024, 4, 1, 12, tzinfo=PLUS2),
        datetime(2024, 4, 1, 10, tzinfo=UTC),
    ]
    assert document(five(), received)["exports_retrieved_at"] == [
        "2024-04-01T10:00:00+00:00",
        "2024-04-01T11:00:00+00:00",
    ]
