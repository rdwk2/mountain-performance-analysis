"""Les valeurs du rapport de sensibilité (``mountain_perf.backtest.report`` ; précisions
de D13 et D15, M4d-3 ; ``0010`` D12) : ``sensitivity_table``, ``axis_counts``,
``drift_under``.

- Sur une configuration construite à la main — deux modèles, cinq performances, dont
  une sans référence et un jour de plusieurs sorties — : les agrégats de chaque ligne
  par jeu et par modèle, au bit, sur la valeur **sous la configuration** (pas celle du
  comparateur), chacun sur son propre effectif, les manquants comptés par motif dans
  l'ordre de ``MISSING_ORDER`` ; ``|L|`` sur l'ensemble commun ; les trois axes comptés
  par modèle.
- Sur la sensibilité de ``just backtest`` du monde (``fixtures.sensitivity_world``) :
  la table d'une configuration de mouvement lue sous son horloge dans les scores de la
  paire ``(250, 30)`` ; les axes du comparateur ; la dérive de v0 brut sous l'écoulé et
  sous une horloge de mouvement, celle du rapport de l'exécution.

Aucune donnée réelle.
"""

import math
from dataclasses import replace
from datetime import date

import pytest

from fixtures.sensitivity_world import BacktestSensitivity, backtest_sensitivity
from mountain_perf.backtest import (
    REPORT_MODELS,
    Aggregate,
    AxisCounts,
    SensitivityRowKind,
    aggregate,
    axis_counts,
    drift_under,
    outing_drift_report,
    report_clocks,
    scored_performances,
    sensitivity_table,
)
from mountain_perf.schemas import (
    CLOCKS,
    Availability,
    ConfigurationOutcome,
    DataSet,
    MetricComparison,
    MetricValue,
    ModelKind,
    OutingScores,
    PerformanceComparison,
    PerformanceMotif,
    SensitivityConfiguration,
    SensitivityMetric,
    SupportComponent,
    Unavailability,
)

V0, CAL = ModelKind.V0_RAW, ModelKind.V0_RECALIBRATED
MODELS = (V0, CAL)
U = Unavailability
L, MAX_C, Q = (
    SensitivityMetric.LEVEL,
    SensitivityMetric.MAX_ABS_PASSAGE_ERROR,
    SensitivityMetric.USAGE,
)
R, DEV, CONF = DataSet.REPEATABILITY, DataSet.DEVELOPMENT, DataSet.CONFIRMATION
SEGMENTS = (SupportComponent.SEGMENTS,)


# ---------------------------------------------------------------------------
# Une configuration construite
# ---------------------------------------------------------------------------


def _value(
    value: float | None, motif: Unavailability = U.INSUFFICIENT_SUPPORT
) -> MetricValue:
    """Une valeur présente (effectif 1), ou absente à ``motif`` (effectif 0)."""
    if value is None:
        return MetricValue(None, motif, 0)
    return MetricValue(value, None, 1)


Side = tuple[MetricValue, MetricValue, tuple[SupportComponent, ...]]
"""Une métrique : la valeur au comparateur, sous la configuration, les composantes de
support changées."""


def _comparison(
    model: ModelKind, metric: SensitivityMetric, side: Side
) -> MetricComparison:
    comparator, value, support = side
    if comparator.available:
        availability = Availability.BOTH if value.available else Availability.LOST
    else:
        availability = Availability.GAINED if value.available else Availability.NEITHER
    difference = (
        None
        if value.value is None or comparator.value is None
        else value.value - comparator.value
    )
    return MetricComparison(
        model, metric, comparator, value, availability, support, difference
    )


def _model(
    model: ModelKind, sides: dict[SensitivityMetric, Side]
) -> tuple[MetricComparison, ...]:
    """Les neuf métriques d'un modèle : ``sides``, les autres absentes des deux côtés
    (``support insuffisant``)."""
    absent: Side = (_value(None), _value(None), ())
    return tuple(
        _comparison(model, metric, sides.get(metric, absent))
        for metric in SensitivityMetric
    )


def _performance(
    day: int, sides: dict[ModelKind, dict[SensitivityMetric, Side]]
) -> PerformanceComparison:
    return PerformanceComparison(
        date(2026, 6, day),
        f"s-2026-06-{day:02d}",
        None,
        tuple(c for model in MODELS for c in _model(model, sides[model])),
    )


def _motif(day: int, motif: PerformanceMotif) -> PerformanceComparison:
    return PerformanceComparison(date(2026, 6, day), f"s-2026-06-{day:02d}", motif, ())


CONFIGURATION = ConfigurationOutcome(
    SensitivityConfiguration(100.0, 15.0, 15.0, CLOCKS[0]),
    (
        _performance(
            1,
            {
                V0: {
                    L: (_value(0.5), _value(0.25), SEGMENTS),
                    MAX_C: (_value(90.0), _value(100.0), ()),
                    Q: (_value(0.0625), _value(0.0625), ()),
                },
                CAL: {
                    L: (_value(0.5), _value(0.5), ()),
                    MAX_C: (_value(200.0), _value(200.0), ()),
                    Q: (_value(0.125), _value(0.125), ()),
                },
            },
        ),
        _performance(
            2,
            {
                V0: {
                    L: (_value(-0.75), _value(-0.75), ()),
                    Q: (_value(0.25), _value(0.25), ()),
                },
                CAL: {
                    L: (_value(0.5), _value(None, U.NOT_CALIBRATED), ()),
                    MAX_C: (_value(None, U.NOT_CALIBRATED),) * 2 + ((),),
                    Q: (_value(None, U.NOT_CALIBRATED),) * 2 + ((),),
                },
            },
        ),
        _motif(3, PerformanceMotif.NO_REFERENCE),
        _motif(4, PerformanceMotif.MULTI_OUTING),
        _performance(
            5,
            {
                V0: {L: (_value(None, U.ZERO_TIME), _value(0.125), ())},
                CAL: {L: (_value(0.25), _value(0.375), SEGMENTS)},
            },
        ),
    ),
    None,
    None,
    (),
    None,
    None,
    None,
    False,
    False,
    False,
    False,
)
"""Une configuration de deux modèles : le 1er et le 2 juin en répétabilité (le 2, v0
recalé non calé sous la configuration), le 3 sans référence (développement), le 4 un
jour de plusieurs sorties (répétabilité et développement), le 5 en confirmation (``L``
de v0 brut gagnée)."""
DATASETS = ((R,), (R,), (DEV,), (R, DEV), (CONF,))
"""Les jeux de chaque performance, dans l'ordre."""

MULTI = ("multi_outing_day", 1)
NOT_CALIBRATED = ("not_calibrated", 1)
INSUFFICIENT = ("insufficient_support", 1)
NO_REFERENCE = ("no_reference", 1)
NOTHING = Aggregate(None, 0, ())


def _rows() -> dict[SensitivityRowKind, tuple[tuple[Aggregate, ...], ...]]:
    rows = sensitivity_table(CONFIGURATION, DATASETS, MODELS)
    assert [row.kind for row in rows] == list(SensitivityRowKind)
    return {row.kind: row.by_set for row in rows}


@pytest.mark.parametrize(
    ("kind", "expected"),
    [
        (
            SensitivityRowKind.LEVEL,
            (
                (
                    Aggregate(-0.25, 2, (MULTI,)),
                    Aggregate(0.5, 1, (NOT_CALIBRATED, MULTI)),
                ),
                (Aggregate(None, 0, (MULTI, NO_REFERENCE)),) * 2,
                (Aggregate(0.125, 1, ()), Aggregate(0.375, 1, ())),
            ),
        ),
        (
            SensitivityRowKind.ABS_LEVEL,
            (
                (
                    Aggregate(0.5, 2, (MULTI,)),
                    Aggregate(0.5, 1, (NOT_CALIBRATED, MULTI)),
                ),
                (Aggregate(None, 0, (MULTI, NO_REFERENCE)),) * 2,
                (Aggregate(0.125, 1, ()), Aggregate(0.375, 1, ())),
            ),
        ),
        (
            SensitivityRowKind.MAX_ABS_PASSAGE_ERROR,
            (
                (
                    Aggregate(100.0, 1, (INSUFFICIENT, MULTI)),
                    Aggregate(200.0, 1, (NOT_CALIBRATED, MULTI)),
                ),
                (Aggregate(None, 0, (MULTI, NO_REFERENCE)),) * 2,
                (Aggregate(None, 0, (INSUFFICIENT,)),) * 2,
            ),
        ),
        (
            SensitivityRowKind.USAGE_TARGET,
            (
                (
                    Aggregate(0.15625, 2, (MULTI,)),
                    Aggregate(0.125, 1, (NOT_CALIBRATED, MULTI)),
                ),
                (Aggregate(None, 0, (MULTI, NO_REFERENCE)),) * 2,
                (Aggregate(None, 0, (INSUFFICIENT,)),) * 2,
            ),
        ),
        (
            SensitivityRowKind.COMMON_ABS_LEVEL,
            (
                (Aggregate(0.25, 1, ()), Aggregate(0.5, 1, ())),
                (NOTHING, NOTHING),
                (Aggregate(0.125, 1, ()), Aggregate(0.375, 1, ())),
            ),
        ),
    ],
    ids=["L", "abs-L", "max-C_k", "q_usage", "abs-L-commun"],
)
def test_sensitivity_table_of_a_built_configuration(
    kind: SensitivityRowKind, expected: tuple[tuple[Aggregate, ...], ...]
) -> None:
    """Précision de D15 (M4d-3) : par ligne, jeu et modèle, la moyenne à poids égal par
    performance de la valeur sous la configuration, sur son propre effectif, ``|L|``
    en valeur absolue ; les manquants comptés par motif — celui de la performance
    (jour de plusieurs sorties, sans référence) ou de la valeur —, dans l'ordre de
    ``MISSING_ORDER`` ; une performance compte dans le jeu de chacune de ses sorties ;
    ``|L|`` commun sur les seules performances où tous les modèles ont ``|L|``."""
    assert _rows()[kind] == expected


def test_sensitivity_table_mean_is_an_fsum() -> None:
    """Précision de D15 (M4d-3) : la moyenne est ``fsum`` sur l'effectif — des valeurs
    que la somme naïve perd."""
    values = (1e8, 1e-8, -1e8)
    performances = tuple(
        _performance(day, {V0: {L: (_value(0.0), _value(v), ())}, CAL: {}})
        for day, v in zip((1, 2, 3), values, strict=True)
    )
    configuration = replace(CONFIGURATION, performances=performances)
    rows = sensitivity_table(configuration, ((R,),) * 3, MODELS)
    level = next(row for row in rows if row.kind is SensitivityRowKind.LEVEL)
    assert level.by_set[0][0] == Aggregate(math.fsum(values) / 3, 3, ())
    assert level.by_set[0][0].value == pytest.approx(1e-8 / 3, rel=1e-12)
    assert level.by_set[0][0] == aggregate(list(values))


def test_axis_counts_of_a_built_configuration() -> None:
    """Précision de D13 (M4d-3) : par modèle, dans l'ordre demandé, sur les
    performances sans motif — les comparaisons, les valeurs perdues et gagnées, celles
    dont une composante de support change, celles dont l'écart est non nul (un écart
    nul ne compte pas)."""
    assert axis_counts(CONFIGURATION, MODELS) == (
        AxisCounts(V0, 27, 0, 1, 1, 2),
        AxisCounts(CAL, 27, 1, 0, 1, 1),
    )
    assert axis_counts(CONFIGURATION, (CAL,)) == (AxisCounts(CAL, 27, 1, 0, 1, 1),)
    assert axis_counts(CONFIGURATION, (ModelKind.TOBLER,)) == (
        AxisCounts(ModelKind.TOBLER, 0, 0, 0, 0, 0),
    )


# ---------------------------------------------------------------------------
# La sensibilité de just backtest du monde
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def world(tmp_path_factory: pytest.TempPathFactory) -> BacktestSensitivity:
    """La sensibilité de ``just backtest`` sur le monde."""
    return backtest_sensitivity(tmp_path_factory)


def test_table_of_a_movement_configuration_reads_its_clock(
    world: BacktestSensitivity,
) -> None:
    """Précisions de D13 et D15 (M4d-3) : une configuration de mouvement se lit dans
    l'exécution ``(250, 30)``, sous son horloge — la ligne ``L`` de v0 brut est, par
    jeu, l'agrégat des ``L`` d'usage de v0 brut sous cette horloge, lus dans les scores
    de la paire centrale, ou du motif de chaque performance."""
    evaluation = world.run.evaluation
    rank = 9
    configuration = evaluation.outcome.configurations[rank]
    clock = configuration.configuration.clock
    assert clock == CLOCKS[1]
    (central,) = [p for p in evaluation.pairs if p.pair == (250.0, 30.0)]
    by_outing = {outcome.outing_id: outcome for outcome in central.outcomes}
    entries = scored_performances(world.central)
    datasets = [entry.datasets for entry in entries]
    values: list[float | str] = []
    for comparison in configuration.performances:
        if comparison.motif is not None:
            values.append(comparison.motif.value)
            continue
        (v0,) = [
            s
            for kind, s in by_outing[comparison.outing_id].scores
            if kind is ModelKind.V0_RAW
        ]
        assert isinstance(v0, OutingScores)
        assert v0.usage is not None
        metric = v0.usage.clocks[CLOCKS.index(clock)].support.log_ratio
        if metric.value is None:
            assert metric.unavailability is not None
            values.append(metric.unavailability.value)
        else:
            values.append(metric.value)
    rows = sensitivity_table(configuration, datasets, REPORT_MODELS)
    level = next(row for row in rows if row.kind is SensitivityRowKind.LEVEL)
    for d, dataset in enumerate(DataSet):
        members = [
            v for v, sets in zip(values, datasets, strict=True) if dataset in sets
        ]
        assert level.by_set[d][0] == aggregate(members)
    assert len(rows) == len(SensitivityRowKind)
    assert all(len(row.by_set) == len(DataSet) for row in rows)
    assert all(len(cell) == len(REPORT_MODELS) for row in rows for cell in row.by_set)


def test_axis_counts_of_the_comparator(world: BacktestSensitivity) -> None:
    """Précision de D13 (M4d-3) : le comparateur, comparé à lui-même — pour chacun des
    cinq modèles, autant de comparaisons que les autres configurations, aucune perdue,
    gagnée, de support changé, ni changée."""
    outcome = world.run.evaluation.outcome
    counts = axis_counts(outcome.configurations[outcome.comparator], REPORT_MODELS)
    assert [c.model for c in counts] == list(REPORT_MODELS)
    compared = 9 * sum(p.motif is None for p in outcome.configurations[0].performances)
    assert compared > 0
    assert counts == tuple(AxisCounts(m, compared, 0, 0, 0, 0) for m in REPORT_MODELS)
    for configuration in outcome.configurations:
        for count in axis_counts(configuration, REPORT_MODELS):
            assert count.compared == compared


def test_drift_under_the_elapsed_and_a_movement_clock(
    world: BacktestSensitivity,
) -> None:
    """Précision de D15 (M4d-3) ; ``0010`` D12 : la dérive d'une sortie scorée d'une
    paire sous l'horloge d'une configuration — sous l'écoulé, les diagnostics de
    l'écoulé seuls ; sous une horloge de mouvement, l'écoulé puis elle — égaux à ceux
    du rapport de l'exécution sous ces horloges ; ``None`` sans usage."""
    (central,) = [p for p in world.run.evaluation.pairs if p.pair == (250.0, 30.0)]
    evaluation = central.evaluation
    assert evaluation is not None
    with_usage = 0
    for outing in evaluation.outings:
        report = outing_drift_report(evaluation, outing)
        elapsed = drift_under(evaluation, outing, CLOCKS[0])
        if outing.scores.usage is None:
            assert report is None
            assert elapsed is None
            continue
        with_usage += 1
        assert report is not None
        assert elapsed is not None
        assert elapsed == replace(
            report,
            diagnostics=tuple(d for d in report.diagnostics if d.clock == CLOCKS[0]),
        )
        clocks = report_clocks(outing.match)
        if len(clocks) < 2:
            continue
        moving = drift_under(evaluation, outing, clocks[1])
        assert moving is not None
        assert [d.clock for d in moving.diagnostics] == [
            d.clock for d in report.diagnostics if d.clock in (CLOCKS[0], clocks[1])
        ]
        assert moving == replace(
            report,
            diagnostics=tuple(
                d for d in report.diagnostics if d.clock in (CLOCKS[0], clocks[1])
            ),
        )
    assert with_usage >= 3


def test_drift_under_another_pair(world: BacktestSensitivity) -> None:
    """Précision de D15 (M4d-3) : la dérive d'une autre paire se lit dans l'évaluation
    de cette paire, sous l'écoulé — celle du rapport de son exécution."""
    (pair,) = [p for p in world.run.evaluation.pairs if p.pair == (100.0, 15.0)]
    evaluation = pair.evaluation
    assert evaluation is not None
    seen = 0
    for outing in evaluation.outings:
        report = outing_drift_report(evaluation, outing)
        drift = drift_under(evaluation, outing, CLOCKS[0])
        if report is None:
            assert drift is None
            continue
        seen += 1
        assert drift is not None
        assert [d.clock for d in drift.diagnostics] == [CLOCKS[0]] * len(
            drift.diagnostics
        )
        assert drift.diagnostics == tuple(
            d for d in report.diagnostics if d.clock == CLOCKS[0]
        )
    assert seen >= 3
