"""Les valeurs du rapport D15 (§ 6.2 et § 8.1, tests 4 à 7, du brief M4b-5 ;
``0010`` D15, D3, D5.4, D6, D7, D8).

4. Les agrégats (``ENTRIES``, ``USAGE_ELAPSED``, ``CONTROL_ELAPSED``, ``USAGE_LOW``),
   et une propriété d'``aggregate``.
5. La référence D8 à côté de v0 (``COMPARISONS``).
6. Les sous-classes de descente (``SUBCLASSES``, ``FRACTIONS_A03``,
   ``SUBCLASS_METRICS_A03``, ``SUBCLASS_METRICS_A06``), et une propriété du seuil.
7. La géométrie, l'âge de la courbe, la troisième horloge (``GEOMETRY``,
   ``THIRD_CLOCK_NOT_ELAPSED``).

Le monde du § 7.1 est exécuté une fois pour le module ; les nombres se comparent à
``1e−9`` relatif, ``1e−12`` absolu (§ 7.0).
"""

import dataclasses
import math
from collections.abc import Sequence
from datetime import UTC, date, datetime, timedelta
from types import SimpleNamespace
from typing import Any, cast

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

import mountain_perf.backtest.report as report
from fixtures.backtest_values import (
    COMPARISONS,
    CONTROL_ELAPSED,
    ENTRIES,
    FRACTIONS_A03,
    GEOMETRY,
    SUBCLASS_METRICS_A03,
    SUBCLASS_METRICS_A06,
    SUBCLASSES,
    THIRD_CLOCK_NOT_ELAPSED,
    USAGE_ELAPSED,
    USAGE_LOW,
)
from fixtures.backtest_world import run_world
from fixtures.scoring import scores
from mountain_perf.backtest import (
    MISSING_ORDER,
    NO_REFERENCE,
    NOT_SCORED,
    REPORT_PARAMETER_SPECS,
    UNDERREPRESENTED,
    Aggregate,
    AggregateRow,
    BacktestRun,
    ClockRole,
    DescentSubclass,
    OutingRun,
    ReportMetric,
    ScoredPerformance,
    aggregate,
    aggregate_table,
    curve_age_days,
    descent_fractions,
    descent_subclasses,
    geometry_diagnostic,
    origins_before_curve,
    performance_values,
    report_clocks,
    route_comparisons,
    scored_performances,
    subclass_metrics,
    third_clock_is_elapsed,
)
from mountain_perf.backtest.segments import FineOverlap
from mountain_perf.schemas import (
    CLOCKS,
    AdmittedSegment,
    DataSet,
    MetricValue,
    ParameterSet,
    RegimeClass,
    RouteProfile,
    Scenario,
    ScenarioScores,
    Unavailability,
)
from mountain_perf.validation import ContractError

INSUFFICIENT = MetricValue(None, Unavailability.INSUFFICIENT_SUPPORT, 0)


def close(a: float | None, b: float | None) -> bool:
    """Tolérance du § 7.0 : relative ``1e−9``, absolue ``1e−12``."""
    if a is None or b is None:
        return a is b
    return math.isclose(a, b, rel_tol=1e-9, abs_tol=1e-12)


@pytest.fixture(scope="module")
def world(tmp_path_factory: pytest.TempPathFactory) -> BacktestRun:
    return run_world(tmp_path_factory.mktemp("monde"))


@pytest.fixture(scope="module")
def entries(world: BacktestRun) -> tuple[ScoredPerformance, ...]:
    return scored_performances(world)


def outing_run(world: BacktestRun, outing_id: str) -> OutingRun:
    return next(run for run in world.outings if run.outing.outing_id == outing_id)


def entry_of(entries: Sequence[ScoredPerformance], day: str) -> ScoredPerformance:
    return next(entry for entry in entries if entry.civil_date.isoformat() == day)


# ---------------------------------------------------------------------------
# 4. Agrégats (précision de D15, M4b-5 ; décision Q3)
# ---------------------------------------------------------------------------


def test_aggregate_of_hand_written_values() -> None:
    """Précision de D15 : la moyenne sur son propre effectif ; les motifs comptés dans
    l'ordre de ``MISSING_ORDER`` ; que des motifs ; aucune valeur."""
    values: list[float | str] = [
        1.0,
        "multi_outing_day",
        "zero_time",
        3.0,
        "zero_time",
        "no_reference",
        5.0,
    ]
    assert aggregate(values) == Aggregate(
        3.0, 3, (("zero_time", 2), ("multi_outing_day", 1), ("no_reference", 1))
    )
    assert aggregate(["not_scored", "underrepresented"]) == Aggregate(
        None, 0, (("underrepresented", 1), ("not_scored", 1))
    )
    assert aggregate([]) == Aggregate(None, 0, ())


def test_missing_order() -> None:
    """Précision de D15 : les motifs de ``Unavailability`` (D0) dans leur ordre, puis
    ceux du rapport."""
    assert MISSING_ORDER == (
        "absent",
        "ambiguous",
        "undefined_tangent",
        "gap",
        "interior_deviation",
        "insufficient_support",
        "zero_time",
        "unidentified_reference",
        "non_convergence",
        "model_error",
        "not_calibrated",
        "multi_outing_day",
        "underrepresented",
        "not_scored",
        "no_reference",
    )
    assert MISSING_ORDER[-3:] == (UNDERREPRESENTED, NOT_SCORED, NO_REFERENCE)


def test_report_parameter_specs() -> None:
    """Décision Q5, précision de D6 : le seuil des sous-classes, 0,80 par défaut,
    réglable dans ``[0,60 ; 1]`` ; 0,59 refusé."""
    (spec,) = REPORT_PARAMETER_SPECS
    assert (spec.name, spec.unit, spec.default, spec.minimum, spec.maximum) == (
        "descent_subclass_threshold",
        None,
        0.80,
        0.60,
        1.0,
    )
    with pytest.raises(ContractError) as raised:
        ParameterSet(REPORT_PARAMETER_SPECS, {"descent_subclass_threshold": 0.59})
    assert type(raised.value) is ContractError


def test_scored_performances_of_the_world(
    entries: tuple[ScoredPerformance, ...],
) -> None:
    """D0, D5.4, D15 : par performance déclarée, le jour, les jeux de ses sorties, les
    parcours de ses sorties de répétabilité, le motif, et le ``θ_bas`` de ses
    horloges du rapport."""
    got = tuple(
        (
            entry.civil_date.isoformat(),
            tuple(dataset.value for dataset in entry.datasets),
            entry.routes,
            entry.missing,
            entry.clocks[1].convention_index if entry.scores is not None else None,
        )
        for entry in entries
    )
    assert got == ENTRIES
    for entry in entries:
        assert (entry.scores is None) == (entry.clocks == ())
        if entry.scores is not None:
            assert len(entry.clocks) == 3
            assert entry.clocks[0] == CLOCKS[0]


def _table(rows: tuple[AggregateRow, ...]) -> list[tuple[Any, ...]]:
    return [
        (
            row.metric.value,
            None if row.regime_class is None else row.regime_class.value,
            tuple((a.value, a.count, a.missing) for a in row.by_set),
        )
        for row in rows
    ]


def _same_table(got: list[tuple[Any, ...]], expected: tuple[Any, ...]) -> None:
    assert [row[:2] for row in got] == [row[:2] for row in expected]
    for row, wanted in zip(got, expected, strict=True):
        for (value, count, missing), (w_value, w_count, w_missing) in zip(
            row[2], wanted[2], strict=True
        ):
            assert close(value, w_value), (row[:2], value, w_value)
            assert (count, missing) == (w_count, w_missing), row[:2]


@pytest.mark.parametrize(
    ("scenario", "role", "expected"),
    [
        (Scenario.USAGE, ClockRole.ELAPSED, USAGE_ELAPSED),
        (Scenario.CONTROL, ClockRole.ELAPSED, CONTROL_ELAPSED),
        (Scenario.USAGE, ClockRole.LOW, USAGE_LOW),
    ],
    ids=["usage-elapsed", "control-elapsed", "usage-low"],
)
def test_aggregate_tables_of_the_world(
    entries: tuple[ScoredPerformance, ...],
    scenario: Scenario,
    role: ClockRole,
    expected: tuple[Any, ...],
) -> None:
    """Précision de D15, décision Q3 : à poids égal par performance, séparés par jeu,
    chaque métrique sur son effectif ; une valeur de classe trop peu représentée
    n'entre pas (D7.5) ; le 12 juin compte dans ses deux jeux ; sous ``θ_bas``,
    ``a-2026-06-06`` est sous ``M θ2`` et le temps nul du dernier segment de ``a``
    rend les métriques vectorielles indisponibles."""
    _same_table(_table(aggregate_table(entries, scenario, role)), expected)


def test_control_has_no_usage_metrics(entries: tuple[ScoredPerformance, ...]) -> None:
    """D3, D7.3, D7.4 : le contrôle n'a ni ``max |C_k|`` ni ``q_usage``."""
    control = aggregate_table(entries, Scenario.CONTROL, ClockRole.ELAPSED)
    usage = aggregate_table(entries, Scenario.USAGE, ClockRole.ELAPSED)
    assert len(control) == 18
    assert [row.metric for row in usage[18:]] == [
        ReportMetric.MAX_ABS_PASSAGE_ERROR,
        ReportMetric.USAGE_TARGET,
    ]


@pytest.mark.parametrize("scenario", [Scenario.USAGE, Scenario.CONTROL])
def test_high_clock_equals_elapsed_but_on_the_stop(
    world: BacktestRun, entries: tuple[ScoredPerformance, ...], scenario: Scenario
) -> None:
    """D5.4 : sous ``θ_haut``, chaque performance vaut l'écoulé (aucun arrêt confirmé
    sur son support), sauf ``a-2026-06-06`` et son arrêt de 150 s."""
    differ = [
        entry.civil_date.isoformat()
        for entry in entries
        if performance_values(entry, scenario, ClockRole.HIGH)
        != performance_values(entry, scenario, ClockRole.ELAPSED)
    ]
    assert differ == ["2026-06-06"]


def test_performance_values_motifs(entries: tuple[ScoredPerformance, ...]) -> None:
    """Précision de D15 : un motif partout — jour multi-sorties, sortie non scorée,
    usage d'une sortie sans référence (D3) ; une classe trop peu représentée
    (D7.5) donne ``underrepresented`` à ses valeurs."""
    multi = performance_values(
        entry_of(entries, "2026-06-12"), Scenario.USAGE, ClockRole.ELAPSED
    )
    assert set(multi.values()) == {"multi_outing_day"}
    assert len(multi) == 20
    unscored = performance_values(
        entry_of(entries, "2026-06-16"), Scenario.CONTROL, ClockRole.LOW
    )
    assert set(unscored.values()) == {NOT_SCORED}
    assert len(unscored) == 18
    without = performance_values(
        entry_of(entries, "2026-06-15"), Scenario.USAGE, ClockRole.ELAPSED
    )
    assert set(without.values()) == {NO_REFERENCE}
    first = performance_values(
        entry_of(entries, "2026-06-03"), Scenario.USAGE, ClockRole.ELAPSED
    )
    flat = [first[(metric, RegimeClass.FLAT)] for metric in report.CLASS_METRICS]
    assert flat == [UNDERREPRESENTED] * 3
    assert all(
        isinstance(first[(m, RegimeClass.ASCENT)], float) for m in report.CLASS_METRICS
    )


def test_role_clock_absent_from_the_performance(
    entries: tuple[ScoredPerformance, ...],
) -> None:
    """D5.4 (passe 1 de B) : une performance aux seules horloges ``(écoulé,)`` — sous
    ``θ_bas`` et ``θ_haut``, ``insufficient_support`` pour ses vingt clés ; sous
    l'écoulé, ses valeurs inchangées."""
    entry = entry_of(entries, "2026-06-03")
    elapsed_only = dataclasses.replace(entry, clocks=entry.clocks[:1])
    for role in (ClockRole.LOW, ClockRole.HIGH):
        values = performance_values(elapsed_only, Scenario.USAGE, role)
        assert len(values) == 20
        assert set(values.values()) == {"insufficient_support"}
    assert performance_values(
        elapsed_only, Scenario.USAGE, ClockRole.ELAPSED
    ) == performance_values(entry, Scenario.USAGE, ClockRole.ELAPSED)


value_or_motif = st.one_of(
    st.floats(min_value=-10, max_value=10, allow_nan=False),
    st.sampled_from(MISSING_ORDER),
)


@settings(max_examples=200, deadline=None)
@given(values=st.lists(value_or_motif, max_size=30), data=st.data())
def test_aggregate_properties(values: list[float | str], data: st.DataObject) -> None:
    """Précision de D15 : ``count`` est le nombre de nombres, ``count`` plus les
    comptes des motifs est la longueur ; motifs dans l'ordre de ``MISSING_ORDER``,
    comptes positifs ; la moyenne entre le plus petit et le plus grand nombre ;
    l'ordre de la liste n'y change rien."""
    result = aggregate(values)
    numbers = [v for v in values if not isinstance(v, str)]
    assert result.count == len(numbers)
    assert result.count + sum(n for _, n in result.missing) == len(values)
    ranks = [MISSING_ORDER.index(motif) for motif, _ in result.missing]
    assert ranks == sorted(set(ranks))
    assert all(n > 0 for _, n in result.missing)
    if numbers:
        assert result.value is not None
        assert min(numbers) - 1e-12 <= result.value <= max(numbers) + 1e-12
    else:
        assert result.value is None
    assert aggregate(data.draw(st.permutations(values))) == result


# ---------------------------------------------------------------------------
# 5. Référence D8 à côté de v0 (D8, décision Q4)
# ---------------------------------------------------------------------------


def test_route_comparisons_of_the_world(
    world: BacktestRun, entries: tuple[ScoredPerformance, ...]
) -> None:
    """D8, précision de D15 : par parcours, ses jours, « un seul contraste », et par
    ligne ``F`` sous l'écoulé avec son effectif ``m``, à côté de l'agrégat de v0 en
    usage sous l'écoulé sur les jours du parcours — le jour multi-sorties par son
    motif."""
    comparisons = route_comparisons(entries, world.references)
    assert [c.route_id for c in comparisons] == list(COMPARISONS)
    for comparison in comparisons:
        days, single, rows = COMPARISONS[comparison.route_id]
        assert (comparison.days, comparison.single_contrast) == (days, single)
        assert len(comparison.rows) == len(rows)
        for (metric, regime, f, by_model), wanted in zip(
            comparison.rows, rows, strict=True
        ):
            v0 = by_model[0]
            w_metric, w_regime, w_f, w_m, (w_value, w_count, w_missing) = wanted
            assert (metric.value, None if regime is None else regime.value) == (
                w_metric,
                w_regime,
            )
            assert close(f.value, w_f), (metric, regime)
            assert f.count == w_m, (metric, regime)
            assert close(v0.value, w_value), (metric, regime)
            assert (v0.count, v0.missing) == (w_count, w_missing), (metric, regime)


# ---------------------------------------------------------------------------
# 6. Sous-classes de descente (D6 et sa précision de M4b-5 ; décision Q5)
# ---------------------------------------------------------------------------

_LETTERS = {
    None: ".",
    DescentSubclass.ROLLING: "r",
    DescentSubclass.STEEP: "s",
    DescentSubclass.UNDECIDED: "u",
}


def _scenario(run: OutingRun) -> ScenarioScores:
    """Le scénario du rapport d'une sortie : l'usage, le contrôle sans référence."""
    usage = run.scores.usage
    return run.scores.control if usage is None else usage


def test_subclass_of_each_admitted_segment(world: BacktestRun) -> None:
    """Précision de D6 : la sous-classe de chaque segment admis de chaque sortie
    scorée, aux seuils 0,80 et 0,60 — sur ``libre``, une fraction roulante d'exactement
    0,8 est roulante au seuil 0,80 (« atteint »)."""
    assert [run.outing.outing_id for run in world.outings] == list(SUBCLASSES)
    for run in world.outings:
        segments = run.scores.observation.segments
        fractions = descent_fractions(run.profile, segments)
        got = tuple(
            "".join(
                _LETTERS[s] for s in descent_subclasses(segments, fractions, threshold)
            )
            for threshold in (0.80, 0.60)
        )
        assert got == SUBCLASSES[run.outing.outing_id], run.outing.outing_id


def test_fractions_of_a_2026_06_03(world: BacktestRun) -> None:
    """D6 : les fractions roulante et raide des segments admis, sur leurs bornes
    effectives ; le segment de transition (0,4 ; 0,6), le mixte (0,6 ; 0)."""
    run = outing_run(world, "a-2026-06-03")
    fractions = descent_fractions(run.profile, run.scores.observation.segments)
    assert len(fractions) == len(FRACTIONS_A03)
    for (rolling, steep), (w_rolling, w_steep) in zip(
        fractions, FRACTIONS_A03, strict=True
    ):
        assert math.isclose(rolling, w_rolling, abs_tol=1e-12)
        assert math.isclose(steep, w_steep, abs_tol=1e-12)


def _segment(regime: RegimeClass, length_m: float = 4.0) -> AdmittedSegment:
    return AdmittedSegment(
        index=0,
        nominal_start_m=0.0,
        nominal_end_m=length_m,
        start_m=0.0,
        end_m=length_m,
        realized_start_m=0.0,
        realized_end_m=length_m,
        regime_class=regime,
        times_s=(1.0,) * len(CLOCKS),
    )


def test_bounds_of_the_rolling_and_steep_grades(
    world: BacktestRun, monkeypatch: pytest.MonkeyPatch
) -> None:
    """D6 : roulante ``−0,15 <= g < −0,05``, raide ``g < −0,15`` — la pente −0,15 est
    roulante, −0,05 ni l'une ni l'autre, juste sous −0,15 raide, juste au-dessus de
    −0,05 ni l'une ni l'autre."""
    pieces = (
        FineOverlap(1.0, -0.15),
        FineOverlap(1.0, -0.05),
        FineOverlap(1.0, math.nextafter(-0.15, -math.inf)),
        FineOverlap(1.0, math.nextafter(-0.05, 0.0)),
    )

    def four_pieces(
        profile: RouteProfile, start_m: float, end_m: float
    ) -> tuple[FineOverlap, ...]:
        return pieces

    monkeypatch.setattr(report, "fine_overlaps", four_pieces)
    profile = outing_run(world, "a-2026-06-03").profile
    assert descent_fractions(profile, [_segment(RegimeClass.DESCENT)]) == (
        (0.25, 0.25),
    )


def test_threshold_is_inclusive() -> None:
    """Précision de D6 : une fraction égale au seuil décide (« atteint »),
    ``0,7999999999`` non ; un segment d'une autre classe n'a pas de sous-classe."""
    descent, ascent = _segment(RegimeClass.DESCENT), _segment(RegimeClass.ASCENT)
    segments = [descent, descent, descent, descent, ascent]
    fractions = [
        (0.8, 0.0),
        (0.7999999999, 0.0),
        (0.0, 0.8),
        (0.1, 0.7999999999),
        (1.0, 0.0),
    ]
    assert descent_subclasses(segments, fractions, 0.8) == (
        DescentSubclass.ROLLING,
        DescentSubclass.UNDECIDED,
        DescentSubclass.STEEP,
        DescentSubclass.UNDECIDED,
        None,
    )


@pytest.mark.parametrize(
    ("outing_id", "expected"),
    [("a-2026-06-03", SUBCLASS_METRICS_A03), ("a-2026-06-06", SUBCLASS_METRICS_A06)],
    ids=["a-2026-06-03", "a-2026-06-06"],
)
def test_subclass_metrics_under_the_report_clocks(
    world: BacktestRun,
    outing_id: str,
    expected: dict[int, Any],
) -> None:
    """Précision de D6, D7.2 : ``E_R``, ``D_R`` et ``E_R − L`` des descentes roulantes
    puis raides, en usage au seuil 0,80, sous chacune des horloges du rapport — les
    trois horloges de ``a-2026-06-06`` diffèrent (son arrêt)."""
    run = outing_run(world, outing_id)
    observation = run.scores.observation
    segments = observation.segments
    subclasses = descent_subclasses(
        segments, descent_fractions(run.profile, segments), 0.80
    )
    usage = run.scores.usage
    assert usage is not None
    ranks = sorted(expected)
    assert [CLOCKS.index(c) for c in report_clocks(run.match)] == ranks
    for rank in ranks:
        got = subclass_metrics(observation, usage, subclasses, CLOCKS[rank])
        for metrics, wanted in zip(got, expected[rank], strict=True):
            subclass, count, under, e_r, d_r, shape = wanted
            assert (metrics.subclass.value, metrics.segment_count) == (subclass, count)
            assert metrics.underrepresented is under
            assert close(metrics.log_ratio.value, e_r)
            assert close(metrics.dispersion.value, d_r)
            assert close(metrics.shape.value, shape)


def test_single_steep_segment_is_underrepresented(world: BacktestRun) -> None:
    """D7.5, précision de D6 : la descente raide de ``b-2026-06-04``, d'un segment,
    est trop peu représentée."""
    run = outing_run(world, "b-2026-06-04")
    segments = run.scores.observation.segments
    subclasses = descent_subclasses(
        segments, descent_fractions(run.profile, segments), 0.80
    )
    usage = run.scores.usage
    assert usage is not None
    rolling, steep = subclass_metrics(
        run.scores.observation, usage, subclasses, CLOCKS[0]
    )
    assert (rolling.segment_count, rolling.underrepresented) == (3, False)
    assert (steep.segment_count, steep.underrepresented) == (1, True)


fractions_pairs = st.tuples(
    st.floats(min_value=0, max_value=1), st.floats(min_value=0, max_value=1)
).filter(lambda pair: pair[0] + pair[1] <= 1)
thresholds = st.floats(min_value=0.6, max_value=1.0)


@settings(max_examples=200, deadline=None)
@given(pair=fractions_pairs, t1=thresholds, t2=thresholds)
def test_threshold_monotony(pair: tuple[float, float], t1: float, t2: float) -> None:
    """Précision de D6 : un segment de descente départagé à un seuil l'est à tout
    seuil plus bas, dans la même sous-classe ; roulant au seuil ``t`` ⇒ ``r >= t``,
    raide ⇒ ``s >= t`` ; un segment d'une autre classe n'a jamais de sous-classe."""
    low, high = min(t1, t2), max(t1, t2)
    descent = [_segment(RegimeClass.DESCENT)]
    (at_high,) = descent_subclasses(descent, [pair], high)
    (at_low,) = descent_subclasses(descent, [pair], low)
    if at_high is not DescentSubclass.UNDECIDED:
        assert at_low is at_high
    for threshold, subclass in ((high, at_high), (low, at_low)):
        if subclass is DescentSubclass.ROLLING:
            assert pair[0] >= threshold
        if subclass is DescentSubclass.STEEP:
            assert pair[1] >= threshold
    for regime in (RegimeClass.ASCENT, RegimeClass.FLAT, RegimeClass.MIXED):
        assert descent_subclasses([_segment(regime)], [pair], low) == (None,)


# ---------------------------------------------------------------------------
# 7. Géométrie, âge, troisième horloge (D3, D15, D2.5, D5.4)
# ---------------------------------------------------------------------------


def test_geometry_of_each_scored_outing(world: BacktestRun) -> None:
    """Précision de D3 : ``G`` et son effectif, puis par classe valeur, motif et
    effectif ; aucun sans usage ; nul pour ``b-2026-06-08``, dont la référence est la
    trace."""
    assert [run.outing.outing_id for run in world.outings] == list(GEOMETRY)
    for run in world.outings:
        diagnostic = geometry_diagnostic(run.scores)
        wanted = GEOMETRY[run.outing.outing_id]
        if wanted is None:
            assert diagnostic is None
            continue
        assert diagnostic is not None
        (w_total, w_count), w_classes = wanted
        assert close(diagnostic.total.value, w_total)
        assert diagnostic.total.count == w_count
        for got, (value, motif, count) in zip(
            diagnostic.classes, w_classes, strict=True
        ):
            assert close(got.value, value)
            assert (got.unavailability, got.count) == (motif, count)


def test_missing_usage_forecast_is_a_model_error(world: BacktestRun) -> None:
    """Précision de D3 : une prévision d'usage absente sur le premier segment — ``G``
    et la classe de ce segment en erreur du modèle, les autres classes présentes."""
    run = outing_run(world, "a-2026-06-03")
    usage = run.scores.usage
    assert usage is not None
    forecast = dataclasses.replace(
        usage.forecast, segment_s=(None, *usage.forecast.segment_s[1:])
    )
    broken = dataclasses.replace(
        run.scores, usage=dataclasses.replace(usage, forecast=forecast)
    )
    diagnostic = geometry_diagnostic(broken)
    assert diagnostic is not None
    first = run.scores.observation.segments[0].regime_class
    assert diagnostic.total == MetricValue(None, Unavailability.MODEL_ERROR, 18)
    for regime, value in zip(RegimeClass, diagnostic.classes, strict=True):
        if regime is first:
            assert value.unavailability is Unavailability.MODEL_ERROR
        else:
            assert value.value is not None


def test_class_without_segment_is_insufficient_support() -> None:
    """Précision de D3 (passe 1 de B) : le cas « Régimes » de M4b-2 n'a aucun segment
    de montée — montée en support insuffisant d'effectif 0, plat, descente et mixte
    présents (1, 3, 1), ``G`` sur 5 ; le cas « Départ non daté » n'a aucun segment —
    ``G`` et les quatre classes en support insuffisant."""
    diagnostic = geometry_diagnostic(scores("Régimes"))
    assert diagnostic is not None
    assert diagnostic.classes[0] == INSUFFICIENT
    assert [c.count for c in diagnostic.classes] == [0, 1, 3, 1]
    assert all(c.value is not None for c in diagnostic.classes[1:])
    assert diagnostic.total.value is not None
    assert diagnostic.total.count == 5
    undated = geometry_diagnostic(scores("Départ non daté"))
    assert undated is not None
    assert (undated.total, *undated.classes) == (INSUFFICIENT,) * 5


def test_curve_age_days() -> None:
    """D15 : l'âge de la courbe au jour civil **à Paris** de son estimation ; négatif
    si elle est postérieure."""
    estimated = datetime(2026, 2, 1, 11, 0, tzinfo=UTC)
    assert curve_age_days(estimated, date(2026, 6, 3)) == 122
    assert curve_age_days(estimated, date(2026, 1, 31)) == -1
    late = datetime(2026, 2, 1, 23, 30, tzinfo=UTC)
    assert curve_age_days(late, date(2026, 2, 2)) == 0


def test_origins_before_curve() -> None:
    """D2.5, D15 : une origine égale à l'instant de la courbe compte, une seconde plus
    tard non, la veille oui ; aucune origine : 0."""
    instant = datetime(2026, 2, 1, 11, 0, tzinfo=UTC)
    origins = [instant, instant + timedelta(seconds=1), instant - timedelta(days=1)]
    assert origins_before_curve(instant, origins) == 2
    assert origins_before_curve(instant, []) == 0


def test_third_clock_is_elapsed_on_the_world(world: BacktestRun) -> None:
    """Précision de D15, décision Q13 : seule ``a-2026-06-06`` a un arrêt confirmé
    sur son support admis ; ailleurs, ``(M+U) θ_haut`` égale l'écoulé."""
    not_elapsed = tuple(
        run.outing.outing_id
        for run in world.outings
        if not third_clock_is_elapsed(run.match)
    )
    assert not_elapsed == THIRD_CLOCK_NOT_ELAPSED


# ---------------------------------------------------------------------------
# Correctifs de la relecture de la PR #20
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "cls",
    [
        report.Aggregate,
        report.ScoredPerformance,
        report.AggregateRow,
        report.RouteComparison,
        report.SubclassMetrics,
        report.GeometryDiagnostic,
    ],
    ids=lambda cls: str(cls.__name__),
)
def test_report_objects_are_frozen(cls: Any) -> None:
    """§ 6.2 : chacun de ces objets est gelé — affecter un champ lève
    ``FrozenInstanceError``."""
    instance = object.__new__(cls)
    with pytest.raises(dataclasses.FrozenInstanceError):
        setattr(instance, dataclasses.fields(cls)[0].name, None)


def test_shape_takes_the_motif_of_a_missing_level(world: BacktestRun) -> None:
    """Précision de D6 (``E_R − L`` : ``L`` absent, le motif de ``L``) : sous une
    horloge dont le ``L`` du scénario manque — une erreur du modèle hors des
    descentes —, une sous-classe garde son ``E_R`` et son ``E_R − L`` prend le motif
    de ``L``. Le scénario est réduit à ce que ``subclass_metrics`` en lit."""
    run = outing_run(world, "a-2026-06-03")
    usage = run.scores.usage
    assert usage is not None
    segments = run.scores.observation.segments
    subclasses = descent_subclasses(
        segments, descent_fractions(run.profile, segments), 0.80
    )
    level = MetricValue(None, Unavailability.MODEL_ERROR, len(segments))
    reduced = SimpleNamespace(
        forecast=usage.forecast,
        clocks=[SimpleNamespace(support=SimpleNamespace(log_ratio=level))],
    )
    rolling, steep = subclass_metrics(
        run.scores.observation, cast(ScenarioScores, reduced), subclasses, CLOCKS[0]
    )
    for metrics in (rolling, steep):
        assert metrics.log_ratio.value is not None
        assert metrics.shape == MetricValue(
            None, Unavailability.MODEL_ERROR, metrics.log_ratio.count
        )


def test_values_of_a_performance_without_scores(world: BacktestRun) -> None:
    """§ 6.2, ``performance_values`` : ``entry.missing`` présent, ou sans scores —
    toutes les clés valent le motif (``not_scored`` sans motif) ; un motif présent
    l'emporte sur des scores présents."""
    run = outing_run(world, "a-2026-06-03")
    day, sets, routes = date(2026, 6, 3), (DataSet.REPEATABILITY,), ("a",)
    multi = Unavailability.MULTI_OUTING_DAY.value
    without = ScoredPerformance(day, sets, routes, None, (), None)
    masked = ScoredPerformance(
        day, sets, routes, run.scores, report_clocks(run.match), multi
    )
    for entry, motif in ((without, NOT_SCORED), (masked, multi)):
        values = performance_values(entry, Scenario.USAGE, ClockRole.ELAPSED)
        assert len(values) == 20
        assert set(values.values()) == {motif}


def test_aggregate_refuses_an_unknown_motif() -> None:
    """``aggregate`` (publique) : un motif hors de ``MISSING_ORDER`` lève
    ``ValueError`` au lieu de disparaître des motifs comptés."""
    with pytest.raises(
        ValueError, match=r"^aggregate : motifs inconnus \['inconnu'\]$"
    ):
        aggregate([1.0, "inconnu", NOT_SCORED])
