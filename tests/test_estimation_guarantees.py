"""Les garanties de l'estimation de la courbe (M6b, ``docs/decisions/0017`` ; §§ 6.3 et
6.4 du brief M6b-1) que la relecture de la PR #37 a trouvées sans test : les contrats
gelés, les textes publiés et les paramètres, les sommes, les comptes, les rangs des
quantiles, les seuils et les bornes.

Les valeurs que le brief donne sont **recopiées du brief**, jamais lues de la constante
qu'elles éprouvent ; les valeurs calculées le sont dans le test, par la règle du § 6.4.
Les activités sont inventées (règle 1)."""

from __future__ import annotations

import dataclasses
import math
from collections.abc import Callable
from datetime import UTC, date, datetime
from itertools import pairwise

import pytest

from fixtures.montees import FLAT
from fixtures.montees import recording as montee
from mountain_perf.estimation.curve import (
    CURVE_ESTIMATION_PARAMETER_SPECS,
    METHOD,
    ActivityExclusion,
    BinValue,
    CurveEstimate,
    EstimatedBin,
    IntervalExclusion,
    _pace_model,
    curve_file_rows,
    estimate_curve,
    estimation_document,
)
from mountain_perf.estimation.intervals import (
    ActivityIntervals,
    CurveInterval,
    TraceRefusal,
    _interpolate,
    activity_intervals,
    heart_rate_series,
)
from mountain_perf.gpx.profile import PROFILE_PARAMETER_SPECS, build_profile
from mountain_perf.ingest.views import trace_view
from mountain_perf.schemas import ParameterSet, Route
from mountain_perf.validation import ContractError
from test_estimation_curve import (
    DEFAULTS,
    GRADES,
    activity,
    estimate,
    interval,
    only,
    selection,
    uniform,
)
from test_estimation_intervals import hr_only, mean_of
from test_model_curve_io_extended import ROWS

PROFILE = ParameterSet(PROFILE_PARAMETER_SPECS)


def bin_of(result: CurveEstimate, grade: float) -> EstimatedBin:
    """La tranche de ``result`` qui contient ``grade``."""
    return next(
        b for b in result.bins if b.lower_permille <= grade * 1000 < b.upper_permille
    )


def bin_speeds(result: CurveEstimate) -> dict[float, float]:
    """La vitesse de la tranche de chaque pente de :data:`GRADES`."""
    return {grade: bin_of(result, grade).speed_ms for grade in GRADES}


def predicted_s(intervals: list[CurveInterval], speeds: dict[float, float]) -> float:
    """``P = Σ length_m × p(grade)``, les pentes aux centres des tranches :
    ``p = 1 / v``."""
    return math.fsum(i.length_m / speeds[i.grade] for i in intervals)


def level_of(outing: ActivityIntervals, speeds: dict[float, float]) -> float:
    """``λ = ln(T / P)`` sur les intervalles de temps M positif (§ 6.4, point 4)."""
    moving = [i for i in outing.intervals if i.moving_s > 0]
    return math.log(math.fsum(i.moving_s for i in moving) / predicted_s(moving, speeds))


def heart_rate_estimate() -> CurveEstimate:
    """Cinq activités, FC posée, vitesses différentes, une seconde d'arrêt par
    intervalle : forme, niveau et FC définis, vitesse écoulée sous la vitesse."""
    outings = []
    for k in range(5):
        speed = 2.0 + 0.1 * k
        outings.append(
            activity(
                f"u{k}",
                [
                    interval(
                        g,
                        50.0,
                        50.0 / speed,
                        stopped_s=1.0,
                        heart_rate_bpm=130.0 + 3 * k + 10 * g,
                    )
                    for g in GRADES
                    for _ in range(round(900 * speed / 50))
                ],
            )
        )
    return estimate(outings)


# --- Les contrats gelés -------------------------------------------------------------


def _trace_view() -> object:
    view = trace_view(montee([FLAT], noise=False))
    assert view is not None
    return view


def _heart_rate_series() -> object:
    series = heart_rate_series(hr_only([0.0, 1.0], [120.0, 121.0]), 0.0)
    assert series is not None
    return series


def _level_quantiles() -> object:
    level = heart_rate_estimate().level
    assert level is not None
    return level


FROZEN: list[Callable[[], object]] = [
    _trace_view,
    lambda: interval(0.0125),
    lambda: activity("a", [interval(0.0125)]),
    _heart_rate_series,
    lambda: ROWS[0],
    selection,
    lambda: heart_rate_estimate().bins[0],
    _level_quantiles,
    lambda: heart_rate_estimate().counts,
    heart_rate_estimate,
]


@pytest.mark.parametrize("make", FROZEN)
def test_the_ten_classes_are_frozen(make: Callable[[], object]) -> None:
    """``TraceView``, ``CurveInterval``, ``ActivityIntervals``, ``HeartRateSeries``,
    ``CurveFileRow``, ``CurveSelection``, ``EstimatedBin``, ``LevelQuantiles``,
    ``CurveCounts``, ``CurveEstimate`` : réaffecter un champ lève."""
    instance = make()
    assert dataclasses.is_dataclass(instance)
    for field in dataclasses.fields(instance):
        with pytest.raises(dataclasses.FrozenInstanceError):
            setattr(instance, field.name, getattr(instance, field.name))


def test_the_ten_classes_are_those_named() -> None:
    names = sorted(type(make()).__name__ for make in FROZEN)
    assert names == sorted(
        [
            "TraceView",
            "CurveInterval",
            "ActivityIntervals",
            "HeartRateSeries",
            "CurveFileRow",
            "CurveSelection",
            "EstimatedBin",
            "LevelQuantiles",
            "CurveCounts",
            "CurveEstimate",
        ]
    )


def test_the_sequences_of_an_estimate_are_tuples() -> None:
    result = estimate([uniform("u", 2.0, GRADES), TraceRefusal.NO_TRACE])
    assert type(result.bins) is tuple
    assert type(result.excluded_activities) is tuple
    assert result.excluded_activities == ((ActivityExclusion.NO_TRACE, 1),)


# --- Les paramètres et les textes publiés, recopiés du brief ------------------------


def test_the_parameters_are_those_of_the_brief() -> None:
    """La table de ``CURVE_ESTIMATION_PARAMETER_SPECS`` du § 6.4, dans son ordre."""
    table = [
        ("hr_width_bpm", "bpm", 10.0, 1.0, 60.0, "Largeur de la bande de FC."),
        ("hr_lag_s", "s", 60.0, 0.0, 600.0, "Décalage de la FC sur l'intervalle."),
        (
            "hr_min_grade",
            None,
            -0.05,
            -1.0,
            1.0,
            "Pente à partir de laquelle la FC filtre ; en dessous, sans filtre.",
        ),
        (
            "hr_min_coverage",
            None,
            0.8,
            0.0,
            1.0,
            "Part de la fenêtre que la FC doit couvrir pour être définie.",
        ),
        (
            "median_min_moving_s",
            "s",
            60.0,
            0.0,
            3600.0,
            "Temps M minimal d'une activité dans une tranche, pour la valeur (b).",
        ),
        (
            "shape_min_moving_s",
            "s",
            120.0,
            0.0,
            3600.0,
            "Temps M minimal d'une activité dans une tranche, pour la forme.",
        ),
        (
            "shape_min_activities",
            None,
            5.0,
            2.0,
            1000.0,
            "Nombre minimal d'activités pour publier la forme d'une tranche.",
        ),
        (
            "max_elapsed_speed_ms",
            "m/s",
            25 / 3.6,
            1.0,
            50.0,
            "Vitesse écoulée au-delà de laquelle un intervalle est aberrant.",
        ),
        (
            "max_ascent_speed_ms",
            "m/s",
            2500 / 3600,
            0.1,
            10.0,
            "Vitesse verticale montante au-delà de laquelle un intervalle est "
            "aberrant.",
        ),
        (
            "max_descent_speed_ms",
            "m/s",
            5000 / 3600,
            0.1,
            10.0,
            "Vitesse verticale descendante au-delà de laquelle un intervalle est "
            "aberrant.",
        ),
    ]
    assert [
        (s.name, s.unit, s.default, s.minimum, s.maximum, s.description)
        for s in CURVE_ESTIMATION_PARAMETER_SPECS
    ] == table


def test_the_published_texts_are_those_of_the_brief() -> None:
    """``METHOD`` et les treize valeurs des énumérations (§ 6.4), dans l'ordre de leurs
    membres : l'ordre d'``IntervalExclusion`` est celui des motifs."""
    assert METHOD == "mperf curve, M6b-1 (docs/decisions/0017)"
    assert [(m.name, m.value) for m in BinValue] == [
        ("POOLED", "somme"),
        ("MEDIAN", "médiane"),
    ]
    assert [(m.name, m.value) for m in IntervalExclusion] == [
        ("CEILING", "au-delà du plafond"),
        ("GRADE", "pente hors domaine"),
        ("NO_ELAPSED", "écoulé nul"),
        ("ABERRANT", "vitesse hors d'échelle"),
        ("HR_UNDEFINED", "FC indéfinie"),
        ("HR_OUTSIDE", "FC hors bande"),
    ]
    assert [(m.name, m.value) for m in ActivityExclusion] == [
        ("NO_TRACE", "sans trace"),
        ("NO_PROFILE", "profil impossible"),
        ("SHORT", "plus courte que la durée minimale"),
        ("LONG", "pas plus courte que la durée maximale"),
        ("NO_INTERVAL", "aucun intervalle retenu"),
    ]


# --- La valeur (b) dans le fichier --------------------------------------------------


def test_with_b_the_file_carries_the_cells_of_the_median() -> None:
    """Avec (b), une activité sous ``median_min_moving_s`` dans la tranche : la ligne
    du fichier porte le nombre et le temps M des seules cellules de la médiane (P3.5),
    pas ceux de toutes les cellules de temps M positif."""
    kept = activity("a", [interval(0.0125, 1800.0, 900.0)])
    under = activity("b", [interval(0.0125, 30.0, 30.0)])
    result = estimate([kept, under], selection(value=BinValue.MEDIAN))
    b = only(result)
    (row,) = curve_file_rows(result)
    assert (row.activities, row.time_min) == (1, 15.0)
    assert (b.moving_activities, b.moving_total_s) == (2, 930.0)


# --- La FC : tolérance de couverture et pas relié -----------------------------------


def test_full_coverage_does_not_fall_on_a_rounding() -> None:
    """Une fenêtre couverte à 100 % dont la durée couverte, différence de cumuls, tombe
    sous sa largeur d'un arrondi : définie, à ``COVERAGE_TOLERANCE_S`` près."""
    times = list(range(0, 121, 3))
    rec = hr_only(times, [100 + 0.5 * t for t in times])
    a, b = 3.656308194333524, 20.27742383454349
    assert mean_of(rec, a, b, 1.0) == pytest.approx(100 + 0.25 * (a + b), abs=1e-9)


def test_a_coverage_short_by_five_hundredths_is_undefined() -> None:
    """Un trou de 12 s dans une fenêtre de 24 s : 12 s couvertes. Exiger 12 s :
    définie ; exiger 12,05 s : indéfinie — la tolérance n'est qu'un arrondi."""
    rec = hr_only([0, 3, 6, 18, 21, 24], [120] * 6)
    assert mean_of(rec, 0.0, 24.0, 12 / 24) == 120.0
    assert mean_of(rec, 0.0, 24.0, 12.05 / 24) is None


def test_a_heart_rate_step_of_ten_seconds_is_linked() -> None:
    """Un pas de 10 s exactement est relié (« au plus » ``MAX_HR_STEP_S``)."""
    series = heart_rate_series(hr_only([0, 10, 20], [120, 140, 140]), 0.0)
    assert series is not None
    assert series.covered_s == (0.0, 10.0, 20.0)
    assert series.mean(0.0, 20.0, 0.8) == (130.0 * 10 + 140.0 * 10) / 20


def test_a_heart_rate_step_of_fifteen_seconds_is_a_gap() -> None:
    """Un pas de 15 s est un trou : ni intégré, ni couvert ; la moyenne est celle du
    seul pas relié, sur sa seule durée."""
    series = heart_rate_series(hr_only([0, 15, 25], [120, 140, 140]), 0.0)
    assert series is not None
    assert series.covered_s == (0.0, 0.0, 10.0)
    assert series.integral_bpm_s == (0.0, 0.0, 1400.0)
    assert series.mean(0.0, 25.0, 0.0) == 140.0
    assert series.mean(0.0, 25.0, 0.8) is None


# --- Les sommes ---------------------------------------------------------------------


def test_the_sums_across_cells_are_exact() -> None:
    """Les sommes du § 6.4 par ``math.fsum`` : trois activités de 1, 2⁻⁵³ et 2⁻¹⁰⁶ s de
    temps M (et autant de mètres) dans une tranche ; la somme exacte, arrondie une
    fois, vaut ``1.0000000000000002`` ; ``sum`` rendrait ``1.0``."""
    outings = [
        activity(ref, [interval(0.01, value, value)])
        for ref, value in (("a", 1.0), ("b", 2.0**-53), ("c", 2.0**-106))
    ]
    result = estimate(outings)
    b = only(result)
    assert b.moving_s == 1.0000000000000002
    assert b.moving_total_s == 1.0000000000000002
    assert b.length_moving_m == 1.0000000000000002
    assert result.counts.moving_s == 1.0000000000000002
    assert result.counts.length_moving_m == 1.0000000000000002


def test_the_cumuls_of_a_cell_follow_the_intervals() -> None:
    """Une activité, trois intervalles de 0,1, 0,2 et 0,3 m dans une tranche : par
    ``+=`` dans l'ordre, ``(0.1 + 0.2) + 0.3`` vaut ``0.6000000000000001`` ; à rebours,
    ``0.6``."""
    outing = activity(
        "a",
        [interval(0.01, 0.1, 1.0), interval(0.01, 0.2, 1.0), interval(0.01, 0.3, 1.0)],
    )
    b = only(estimate([outing]))
    assert b.length_moving_m == 0.6000000000000001
    assert b.length_all_m == 0.6000000000000001


# --- Les lignes du fichier et le document -------------------------------------------


def test_every_column_of_the_file_rows() -> None:
    """Chaque ligne porte la FC, la forme, le temps, les activités et la vitesse
    écoulée de sa tranche."""
    result = heart_rate_estimate()
    rows = curve_file_rows(result)
    assert len(rows) == len(result.bins) == 5
    assert all(b.shape_iqr is not None for b in result.bins)
    for row, b in zip(rows, result.bins, strict=True):
        assert b.mean_hr_bpm is not None
        assert row.speed_ms == b.speed_ms
        assert row.mean_hr_bpm == b.mean_hr_bpm
        assert row.shape_iqr == b.shape_iqr
        assert row.time_min == b.moving_s / 60
        assert row.activities == b.activity_count
        assert row.elapsed_speed_ms == b.elapsed_speed_ms
        assert row.elapsed_speed_ms < row.speed_ms


def test_the_document_keys_in_their_order() -> None:
    """Les clés du § 6.4, dans leur ordre : le document, ``level``, ``counts`` (sans
    ``excluded_length_m``, qui a sa clé), une tranche ; ``level`` et
    ``elapsed_moving_ratio`` sont ceux de l'estimation."""
    result = heart_rate_estimate()
    doc = estimation_document(
        result,
        selection(),
        DEFAULTS,
        PROFILE,
        commit="c" * 40,
        exports_retrieved_at=[datetime(2024, 4, 1, tzinfo=UTC)],
        support_error=None,
    )
    assert list(doc) == [
        "method",
        "commit",
        "value",
        "bin_edges_permille",
        "clock_convention",
        "heart_rate_integration",
        "heart_rate_max_step_s",
        "level_kind",
        "profile_parameters",
        "parameters",
        "projectable",
        "support_error",
        "level",
        "elapsed_moving_ratio",
        "excluded_activities",
        "excluded_intervals",
        "excluded_length_m",
        "counts",
        "bins",
        "exports_retrieved_at",
    ]
    level = doc["level"]
    assert isinstance(level, dict)
    assert list(level) == ["p10", "p50", "p90", "count"]
    assert result.level is not None
    assert level == {
        "p10": result.level.p10,
        "p50": result.level.p50,
        "p90": result.level.p90,
        "count": result.level.count,
    }
    assert doc["elapsed_moving_ratio"] == result.elapsed_moving_ratio
    counts = doc["counts"]
    assert isinstance(counts, dict)
    assert list(counts) == [
        "candidates",
        "with_intervals",
        "eligible",
        "retained",
        "moving",
        "median",
        "with_level",
        "filtered_side",
        "descents_only",
        "intervals",
        "truncated",
        "retained_intervals",
        "retained_without_moving",
        "length_all_m",
        "length_moving_m",
        "moving_s",
        "elapsed_s",
        "after_ceiling_s",
    ]
    bins = doc["bins"]
    assert isinstance(bins, list)
    assert list(bins[0]) == [
        "lower_permille",
        "upper_permille",
        "moving_total_s",
        "length_moving_m",
        "length_all_m",
        "elapsed_total_s",
        "moving_activities",
        "n_eff_moving",
        "max_moving_share",
        "mean_grade",
        "shape_activity_count",
    ]


# --- Les comptes --------------------------------------------------------------------


def test_the_counters_count_more_than_one() -> None:
    """Chaque motif arrive deux fois : ``SHORT``, ``NO_INTERVAL``, ``NO_TRACE``, puis
    ``LONG`` ; ``intervals``, ``truncated`` et ``CEILING`` sur deux activités."""
    good = [uniform(f"g{k}", 2.0, GRADES) for k in range(2)]
    short = [activity(f"s{k}", [interval(0.0125)], elapsed_s=100.0) for k in range(2)]
    nothing = [activity(f"n{k}", [interval(2.0)]) for k in range(2)]
    refused = [TraceRefusal.NO_TRACE, TraceRefusal.NO_TRACE]
    result = estimate(
        [*good, *short, *nothing, *refused], selection(min_duration_s=600.0)
    )
    assert dict(result.excluded_activities) == {
        ActivityExclusion.NO_TRACE: 2,
        ActivityExclusion.SHORT: 2,
        ActivityExclusion.NO_INTERVAL: 2,
    }
    long = [activity(f"l{k}", [interval(0.0125)], elapsed_s=99999.0) for k in range(2)]
    result = estimate([*good, *long], selection(max_duration_s=10000.0))
    assert dict(result.excluded_activities) == {ActivityExclusion.LONG: 2}
    assert result.counts.intervals == sum(len(a.intervals) for a in good)
    cut = CurveInterval(50.0, 0.0125, 0.0, 600.0, 25.0, 0.0, 0.0, None, truncated=True)
    ceiling = [ActivityIntervals(f"c{k}", 3600.0, (cut,), 600.0, 3) for k in range(2)]
    result = estimate(ceiling, selection(max_elapsed_s=600.0))
    assert result.counts.truncated == 2
    assert result.counts.intervals == 2 * (1 + 3)
    assert dict(result.excluded_intervals) == {IntervalExclusion.CEILING: 6}


# --- Les rangs des quantiles --------------------------------------------------------


def test_the_level_quantiles_ranks() -> None:
    """Onze niveaux distincts : p10 au rang ⌈11/10⌉ = 2, p50 au rang ⌈11/2⌉ = 6, p90 au
    rang ⌈99/10⌉ = 10 — ni le minimum, ni le maximum."""
    outings = [uniform(f"u{k}", math.exp(0.05 * k), GRADES) for k in range(11)]
    result = estimate(outings)
    assert result.excluded_intervals == ()
    speeds = bin_speeds(result)
    levels = sorted(level_of(outing, speeds) for outing in outings)
    level = result.level
    assert level is not None
    assert level.count == 11
    assert math.isclose(level.p10, levels[1], rel_tol=1e-12, abs_tol=1e-12)
    assert math.isclose(level.p50, levels[5], rel_tol=1e-12, abs_tol=1e-12)
    assert math.isclose(level.p90, levels[9], rel_tol=1e-12, abs_tol=1e-12)
    assert not math.isclose(level.p10, levels[0], rel_tol=1e-6)
    assert not math.isclose(level.p90, levels[10], rel_tol=1e-6)


def test_the_shape_quartile_ranks() -> None:
    """Cinq formes distinctes dans une tranche : Q1 au rang ⌈5/4⌉ = 2, Q3 au rang
    ⌈15/4⌉ = 4 ; ``x = ln(P_jk / M_jk) + λ_j`` (§ 6.4, point 5)."""
    g0 = GRADES[2]
    outings = []
    for j in range(5):
        intervals = []
        for g in GRADES:
            speed = 2.0 * (math.exp(0.1 * j) if g == g0 else 1.0)
            intervals += [
                interval(g, 50.0, 50.0 / speed) for _ in range(round(900 * speed / 50))
            ]
        outings.append(activity(f"f{j}", intervals))
    result = estimate(outings)
    speeds = bin_speeds(result)
    shapes = []
    for outing in outings:
        cell = [i for i in outing.intervals if i.grade == g0]
        moving = math.fsum(i.moving_s for i in cell)
        shapes.append(
            math.log(predicted_s(cell, speeds) / moving) + level_of(outing, speeds)
        )
    shapes.sort()
    b = bin_of(result, g0)
    assert b.shape_activity_count == 5
    assert b.shape_iqr is not None
    assert math.isclose(b.shape_iqr, shapes[3] - shapes[1], rel_tol=1e-9, abs_tol=1e-12)
    assert not math.isclose(b.shape_iqr, shapes[4] - shapes[0], rel_tol=1e-6)


# --- Les temps M minuscules et les seuils -------------------------------------------


def test_a_tiny_moving_interval_is_moving() -> None:
    """Un intervalle de 0 < M ≤ 1 s (0,5 s) compte comme en mouvement : au niveau,
    dans sa tranche, dans ``length_moving_m``, hors de ``retained_without_moving``, et
    son activité compte dans ``moving`` et dans sa tranche."""
    base = uniform("a", 2.0, GRADES)
    outing = activity("a", [*base.intervals, interval(GRADES[0], 0.2, 0.5)])
    result = estimate([outing])
    speeds = bin_speeds(result)
    assert result.level is not None
    assert math.isclose(
        result.level.p50, level_of(outing, speeds), rel_tol=1e-12, abs_tol=1e-15
    )
    cell = [i for i in outing.intervals if i.grade == GRADES[0]]
    b = bin_of(result, GRADES[0])
    assert b.moving_s == math.fsum(i.moving_s for i in cell)
    assert b.length_moving_m == b.length_all_m
    counts = result.counts
    assert counts.retained_without_moving == 0
    assert counts.length_moving_m == counts.length_all_m
    assert counts.moving_s == math.fsum(i.moving_s for i in outing.intervals)
    alone = activity("t", [interval(GRADES[2], 1.0, 0.5)])
    with_alone = estimate([uniform("g", 2.0, GRADES), alone])
    assert with_alone.counts.moving == 2
    assert bin_of(with_alone, GRADES[2]).activity_count == 2


def test_zero_thresholds_count_a_tiny_cell() -> None:
    """Aux seuils nuls, une cellule de M = 0,5 s compte pour la médiane et pour la
    forme."""
    parameters = ParameterSet(
        CURVE_ESTIMATION_PARAMETER_SPECS,
        {"shape_min_moving_s": 0.0, "median_min_moving_s": 0.0},
    )
    outings = [uniform(f"u{k}", 2.0, GRADES) for k in range(5)]
    outings.append(activity("t", [interval(GRADES[2], 0.9, 0.5)]))
    result = estimate(outings, parameters=parameters)
    assert result.counts.median == 6
    assert bin_of(result, GRADES[2]).shape_activity_count == 6


def test_a_cell_without_moving_time_is_not_an_activity_of_the_bin() -> None:
    still = activity("s", [interval(GRADES[0], 10.0, 0.0, stopped_s=60.0)])
    result = estimate([uniform("u", 2.0, GRADES), still])
    b = bin_of(result, GRADES[0])
    assert (b.activity_count, b.moving_activities) == (1, 1)


def test_the_filtered_side_counts_minus_five_percent() -> None:
    """``filtered_side`` compte une activité dont le seul intervalle en mouvement à
    ``>= −5 %`` est à −5 % exactement."""
    edge = activity("e", [interval(-0.05, 50.0, 25.0, heart_rate_bpm=150.0)])
    other = activity("o", [interval(-0.2, 50.0, 25.0)])
    result = estimate([edge, other], selection(hr_center_bpm=150.0))
    assert (result.counts.filtered_side, result.counts.descents_only) == (1, 1)


def test_the_filtered_side_needs_moving_time() -> None:
    """``filtered_side`` ne compte pas une activité dont le seul intervalle à
    ``>= −5 %`` n'a pas de temps M ; il compte celle dont cet intervalle a 0,5 s de
    temps M."""
    base = interval(-0.2, 50.0, 25.0)
    still = activity(
        "s",
        [base, interval(0.0125, 10.0, 0.0, stopped_s=60.0, heart_rate_bpm=150.0)],
    )
    tiny = activity("t", [base, interval(0.0125, 0.2, 0.5, heart_rate_bpm=150.0)])
    result = estimate([still, tiny], selection(hr_center_bpm=150.0))
    assert (result.counts.filtered_side, result.counts.descents_only) == (1, 1)


def test_a_cell_at_the_median_threshold_counts_for_b() -> None:
    """Une cellule de ``median_min_moving_s`` (60 s) exactement compte pour (b) : dans
    ``median``, et elle porte la valeur de sa tranche."""
    exact = activity("e", [interval(0.0125, 120.0, 60.0)])
    assert estimate([exact, uniform("g", 2.0, GRADES)]).counts.median == 2
    other = uniform("g", 2.0, GRADES[:1])
    result = estimate([exact, other], selection(value=BinValue.MEDIAN))
    bins = {b.lower_permille: b for b in result.bins}
    assert sorted(bins) == [-200, 0]
    b = bins[0]
    assert (b.speed_ms, b.moving_s, b.activity_count) == (2.0, 60.0, 1)


# --- Les bornes ---------------------------------------------------------------------


def test_the_interpolation_on_unequal_steps() -> None:
    """``_interpolate`` sur des pas inégaux : chaque pas, ses bornes, et le premier ou
    le dernier pas prolongé hors des instants."""
    xs, ys = [0.0, 2.0, 5.0, 9.0], [0.0, 4.0, 4.0, 12.0]
    assert _interpolate(xs, ys, 0.0) == 0.0
    assert _interpolate(xs, ys, 1.0) == 2.0
    assert _interpolate(xs, ys, 2.0) == 4.0
    assert _interpolate(xs, ys, 3.5) == 4.0
    assert _interpolate(xs, ys, 7.0) == 8.0
    assert _interpolate(xs, ys, 9.0) == 12.0
    assert _interpolate(xs, ys, -1.0) == -2.0
    assert _interpolate(xs, ys, 10.0) == 14.0


def test_the_selection_bounds() -> None:
    """Une fenêtre d'un jour, une durée minimale nulle, des durées de 0,5 s :
    acceptées ; une durée maximale nulle : refusée."""
    selection(date_from=date(2024, 5, 1), date_to=date(2024, 5, 1))
    selection(min_duration_s=0.0)
    selection(min_duration_s=0.5, max_duration_s=1.0)
    selection(max_duration_s=0.5)
    selection(max_elapsed_s=0.5)
    with pytest.raises(ContractError, match="max_duration_s"):
        selection(max_duration_s=0.0)


def test_without_a_ceiling_nothing_is_after_it() -> None:
    """Sans plafond : ``after_ceiling_s`` nul, rien de retiré, aucun plafond ; la
    référence de l'activité recopiée."""
    rec = montee([(2000.0, 0.0, 2.5), (1000.0, 0.1, 1.5)], seed=3, activity_ref="zz9")
    result = activity_intervals(rec, PROFILE, hr_lag_s=60.0, hr_min_coverage=0.8)
    assert isinstance(result, ActivityIntervals)
    assert result.activity_ref == "zz9"
    assert (result.ceiling_s, result.after_ceiling, result.after_ceiling_s) == (
        None,
        0,
        0.0,
    )


@pytest.mark.parametrize("refs", [["a"], ["a", "b", "x"]])
def test_references_and_candidates_of_different_lengths_are_refused(
    refs: list[str],
) -> None:
    """Deux candidates, une ou trois références : ``ValueError``, jamais une
    estimation sur une partie des candidates."""
    candidates = [uniform("a", 2.0, GRADES), uniform("b", 2.0, GRADES)]
    with pytest.raises(ValueError, match=r"zip\(\) argument 2 is"):
        estimate_curve(candidates, refs, selection(), DEFAULTS)


def test_a_bin_of_ten_minutes_at_the_edge_is_in_the_support() -> None:
    """La tranche la plus raide n'a que 600 s pile de temps M : elle atteint le seuil
    du support (10 min, comme ``read_curve``) et le moteur la lit. Son activité a donc
    un niveau nul, comme les autres, au lieu d'un temps prolongé."""
    outings = [uniform(f"u{k}", 2.0, GRADES[:-1]) for k in range(5)]
    edge = uniform("e", 1.0, GRADES[-1:], 600.0)
    outings.append(edge)
    result = estimate(outings)
    b = bin_of(result, GRADES[-1])
    assert b.moving_s == 600.0
    model = _pace_model(result.bins)
    assert model is not None
    assert model.grade_range == (GRADES[0], GRADES[-1])
    assert result.level is not None
    assert (result.level.p10, result.level.p90, result.level.count) == (0.0, 0.0, 6)


def test_a_last_profile_interval_under_a_metre_is_kept() -> None:
    """Une trace droite d'un peu moins de 101 m, une grille au pas d'1 m : le dernier
    intervalle du profil fait moins d'1 m (au moins un demi-pas : la grille le garde),
    il est gardé ; les longueurs sont celles de la grille, et leur somme est la longueur
    du profil."""
    rec = montee([(101.5, 0.0, 0.5)], noise=False)
    profile_parameters = ParameterSet(PROFILE_PARAMETER_SPECS, {"grid_step_m": 1})
    view = trace_view(rec)
    assert view is not None
    trace = view.trace
    grid = build_profile(
        Route(
            "vue",
            trace.latitude_deg,
            trace.longitude_deg,
            trace.elevation_m,
            (),
            rec.source,
        ),
        profile_parameters,
    ).distance_m
    assert 0 < grid[-1] - grid[-2] < 1
    result = activity_intervals(
        rec, profile_parameters, hr_lag_s=60.0, hr_min_coverage=0.8
    )
    assert isinstance(result, ActivityIntervals)
    lengths = [i.length_m for i in result.intervals]
    assert lengths == [b - a for a, b in pairwise(grid)]
    assert math.fsum(lengths) == pytest.approx(grid[-1] - grid[0], abs=1e-9)


def test_a_start_stop_longer_than_the_ceiling_keeps_nothing() -> None:
    """À l'arrêt au départ plus longtemps que le plafond : la coupe du premier
    intervalle ne lui laisse aucune longueur, aucun intervalle n'est gardé, tous sont
    comptés au-delà du plafond (P2.4)."""
    rec = montee([FLAT], noise=False, stops=[(0.0, 400.0)])
    plain = activity_intervals(rec, PROFILE, hr_lag_s=60.0, hr_min_coverage=0.8)
    capped = activity_intervals(
        rec, PROFILE, hr_lag_s=60.0, hr_min_coverage=0.8, max_elapsed_s=300.0
    )
    assert isinstance(plain, ActivityIntervals)
    assert isinstance(capped, ActivityIntervals)
    assert plain.intervals[0].end_s > 300.0
    assert capped.intervals == ()
    assert capped.after_ceiling == len(plain.intervals)
    assert capped.after_ceiling_s == pytest.approx(plain.elapsed_s - 300.0, abs=1e-9)
