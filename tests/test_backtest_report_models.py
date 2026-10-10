"""Les valeurs du rapport à cinq modèles (§ 6.5 et § 8.1, test 4, du brief M4c-2 ;
``0010`` D15 et sa précision de M4c-2, D5.4, D7, D8, D9.2 ; décisions 5 et 11).

- ``REPORT_MODELS`` ; les entrées du rapport portent ``population`` (``C_j``)
  toujours, et ``calibrated`` dans l'ordre de ``CALIBRATED_MODELS`` (vide pour un jour
  multi-sorties ou une sortie non scorée).
- ``role_clock_scores`` rend les motifs **dans l'ordre** — motif de la performance,
  ``no_reference``, ``insufficient_support``, statut du calage —, sur les entrées du
  monde puis sur des entrées aux horloges réduites qui les mettent en concurrence ; un
  modèle calé se lit sur ses scores calés, sous l'horloge du rôle **parmi les onze**.
- Les tables par modèle ; l'**ensemble commun** (décision 5) ; ``route_comparisons``
  à cinq agrégats ; les valeurs ``USAGE_ELAPSED_LEVELS`` et ``COMMON_ABS_LEVEL``
  (§ 7.2, oracle ``mpmath`` indépendant).

Le monde de M4b-5 est exécuté une fois par module (``world``) ; les entrées se
recalculent dans chaque test, sans cache.
"""

import math
from dataclasses import replace
from datetime import date

import pytest

from fixtures.backtest_values import COMMON_ABS_LEVEL, USAGE_ELAPSED_LEVELS
from fixtures.backtest_world import run_world
from fixtures.registry import not_calibrated
from mountain_perf.backtest import (
    MISSING_ORDER,
    NO_REFERENCE,
    NOT_SCORED,
    REPORT_MODELS,
    BacktestRun,
    ClockRole,
    ReportMetric,
    ScoredPerformance,
    aggregate,
    aggregate_table,
    common_row,
    performance_values,
    role_clock_scores,
    route_comparisons,
    scored_performances,
)
from mountain_perf.schemas import (
    CALIBRATED_MODELS,
    CLOCKS,
    ClockScores,
    DataSet,
    ModelKind,
    RegimeClass,
    Scenario,
    Unavailability,
)

USAGE, CONTROL = Scenario.USAGE, Scenario.CONTROL
INSUFFICIENT = Unavailability.INSUFFICIENT_SUPPORT.value
NOT_CALIBRATED = Unavailability.NOT_CALIBRATED.value
MULTI = Unavailability.MULTI_OUTING_DAY.value


def _close(a: float | None, b: float | None) -> bool:
    """Tolérance du § 7.0 : relative ``1e−9``, absolue ``1e−12``."""
    if a is None or b is None:
        return a is b
    return math.isclose(a, b, rel_tol=1e-9, abs_tol=1e-12)


@pytest.fixture(scope="module")
def world(tmp_path_factory: pytest.TempPathFactory) -> BacktestRun:
    """Le monde de M4b-5 exécuté une fois."""
    return run_world(tmp_path_factory.mktemp("monde"))


def _entry(run: BacktestRun, day: str) -> ScoredPerformance:
    """L'entrée du rapport du jour ``day``, recalculée."""
    (entry,) = (
        e for e in scored_performances(run) if e.civil_date == date.fromisoformat(day)
    )
    return entry


# ---------------------------------------------------------------------------
# REPORT_MODELS, population, calibrated
# ---------------------------------------------------------------------------


def test_report_models() -> None:
    """Précision de D15 (M4c-2) : les cinq modèles de D9.1, dans l'ordre."""
    assert (ModelKind.V0_RAW, *CALIBRATED_MODELS) == REPORT_MODELS
    assert [m.value for m in REPORT_MODELS] == [
        "v0_raw",
        "v0_recalibrated",
        "constant_speed",
        "naismith",
        "tobler",
    ]


def test_entries_carry_population_and_calibrated_scores(world: BacktestRun) -> None:
    """§ 6.5, ``scored_performances`` : ``C_j`` pour chaque performance ; les scores
    calés de sa sortie, dans l'ordre de ``CALIBRATED_MODELS``, pour une sortie scorée
    d'une performance d'une seule sortie ; rien pour un jour multi-sorties ou une
    sortie non scorée. Aussi depuis le calcul d'avant le RÉSULTAT."""
    entries = scored_performances(world)
    populations = [performance.population for performance in world.calibration]
    assert [entry.population for entry in entries] == populations
    calibrated = {
        (e.outing_id, e.control.model): e
        for performance in world.calibration
        for e in performance.outings
    }
    for entry in entries:
        if entry.missing is not None:
            assert entry.calibrated == (), entry.civil_date
            continue
        assert entry.scores is not None
        kinds = [model for model, _ in entry.calibrated]
        assert kinds == list(CALIBRATED_MODELS)
        outing_id = {scores.outing_id for _, scores in entry.calibrated}
        (only,) = outing_id
        for model, scores in entry.calibrated:
            assert scores is calibrated[(only, model)]
        assert entry.calibrated[0][1].observation == entry.scores.observation
    missing = {entry.civil_date.isoformat(): entry.missing for entry in entries}
    assert missing["2026-06-12"] == MULTI
    assert missing["2026-06-16"] == NOT_SCORED
    assert missing["2026-06-20"] == NOT_SCORED


# ---------------------------------------------------------------------------
# role_clock_scores : l'ordre des motifs (§ 6.5)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("model", REPORT_MODELS)
@pytest.mark.parametrize("scenario", [USAGE, CONTROL])
@pytest.mark.parametrize("role", list(ClockRole))
def test_motifs_on_the_world(
    world: BacktestRun, model: ModelKind, scenario: Scenario, role: ClockRole
) -> None:
    """§ 6.5 : sur les entrées du monde — le 12 juin, jour multi-sorties ; le 16, non
    scorée ; le 15, sans référence (en usage) ; le 3, non calé (modèles calés) ; le
    27, des scores sous l'horloge du rôle."""
    assert (
        role_clock_scores(_entry(world, "2026-06-12"), scenario, role, model) == MULTI
    )
    assert (
        role_clock_scores(_entry(world, "2026-06-16"), scenario, role, model)
        == NOT_SCORED
    )
    june_15 = role_clock_scores(_entry(world, "2026-06-15"), scenario, role, model)
    if scenario is USAGE:
        assert june_15 == NO_REFERENCE
    else:
        assert isinstance(june_15, ClockScores)
    june_3 = role_clock_scores(_entry(world, "2026-06-03"), scenario, role, model)
    if model is ModelKind.V0_RAW:
        assert isinstance(june_3, ClockScores)
    else:
        assert june_3 == NOT_CALIBRATED
    june_27 = _entry(world, "2026-06-27")
    scores = role_clock_scores(june_27, scenario, role, model)
    assert isinstance(scores, ClockScores)
    index = list(ClockRole).index(role)
    assert scores.clock == june_27.clocks[index]


@pytest.mark.parametrize("model", REPORT_MODELS)
def test_motifs_compete_on_reduced_clocks(world: BacktestRun, model: ModelKind) -> None:
    """§ 6.5, l'ordre des motifs, mis en concurrence par des entrées aux horloges
    réduites à l'écoulé (rôle ``M θ_bas`` au-delà de ses horloges) : le 15 juin, en
    usage, ``no_reference`` passe avant ``insufficient_support`` ; les 3 et 27 juin,
    ``insufficient_support`` passe avant le statut du calage (non calé le 3)."""
    low = ClockRole.LOW

    def reduced(day: str) -> ScoredPerformance:
        entry = _entry(world, day)
        return replace(entry, clocks=entry.clocks[:1])

    assert role_clock_scores(reduced("2026-06-15"), USAGE, low, model) == NO_REFERENCE
    assert role_clock_scores(reduced("2026-06-15"), CONTROL, low, model) == INSUFFICIENT
    for day in ("2026-06-03", "2026-06-27"):
        for scenario in (USAGE, CONTROL):
            assert (
                role_clock_scores(reduced(day), scenario, low, model) == INSUFFICIENT
            ), (day, scenario)


@pytest.mark.parametrize("model", REPORT_MODELS)
@pytest.mark.parametrize("scenario", [USAGE, CONTROL])
def test_role_clock_is_read_among_the_eleven(
    world: BacktestRun, model: ModelKind, scenario: Scenario
) -> None:
    """§ 6.5 : l'horloge du rôle se lit parmi les onze (``CLOCKS.index``), pas par son
    rang — les horloges du 27 juin déplacées à d'autres rangs."""
    entry = _entry(world, "2026-06-27")
    moved = replace(entry, clocks=(CLOCKS[0], CLOCKS[6], CLOCKS[9]))
    for role, clock in zip(ClockRole, moved.clocks, strict=True):
        scores = role_clock_scores(moved, scenario, role, model)
        assert isinstance(scores, ClockScores)
        assert scores.clock == clock


def test_calibrated_metrics_are_read_on_calibrated_scores(world: BacktestRun) -> None:
    """§ 6.5, ``performance_values`` : les métriques d'un modèle calé se lisent sur ses
    scores calés, sous l'horloge du rôle, comme celles de v0 sur les siens."""
    entry = _entry(world, "2026-06-27")
    for model, scaled in entry.calibrated:
        for scenario in (USAGE, CONTROL):
            calibrated = scaled.usage if scenario is USAGE else scaled.control
            assert calibrated is not None
            for index, role in enumerate(ClockRole):
                clock = calibrated.clocks[CLOCKS.index(entry.clocks[index])].scores
                assert clock is not None
                values = performance_values(entry, scenario, role, model)
                level = clock.support.log_ratio.value
                assert values[(ReportMetric.LEVEL, None)] == level
                raw = performance_values(entry, scenario, role)
                assert raw[(ReportMetric.LEVEL, None)] != level
    assert performance_values(entry, USAGE, ClockRole.ELAPSED) == performance_values(
        entry, USAGE, ClockRole.ELAPSED, ModelKind.V0_RAW
    )


# ---------------------------------------------------------------------------
# Tables par modèle, valeurs du § 7.2
# ---------------------------------------------------------------------------


def test_tables_per_model(world: BacktestRun) -> None:
    """§ 6.5, ``aggregate_table`` d'un modèle : chaque agrégat est celui des valeurs de
    ce modèle sur les performances du jeu ; ``USAGE_ELAPSED_LEVELS`` (§ 7.2)."""
    entries = scored_performances(world)
    for model in REPORT_MODELS:
        for scenario in (USAGE, CONTROL):
            for role in ClockRole:
                table = aggregate_table(entries, scenario, role, model)
                values = [
                    performance_values(entry, scenario, role, model)
                    for entry in entries
                ]
                for row in table:
                    for dataset, value in zip(DataSet, row.by_set, strict=True):
                        expected = aggregate(
                            [
                                v[(row.metric, row.regime_class)]
                                for entry, v in zip(entries, values, strict=True)
                                if dataset in entry.datasets
                            ]
                        )
                        assert value == expected
        table = aggregate_table(entries, USAGE, ClockRole.ELAPSED, model)
        rows = {row.metric: row for row in table if row.regime_class is None}
        for name, metric in (
            ("L", ReportMetric.LEVEL),
            ("|L|", ReportMetric.ABS_LEVEL),
        ):
            for dataset, value in zip(DataSet, rows[metric].by_set, strict=True):
                mean, count = USAGE_ELAPSED_LEVELS[(model.value, dataset.value, name)]
                assert value.count == count, (model, dataset, name)
                assert _close(value.value, mean), (model, dataset, name)


# ---------------------------------------------------------------------------
# L'ensemble commun (décision 5)
# ---------------------------------------------------------------------------


def _common_by_definition(
    entries: list[ScoredPerformance],
    scenario: Scenario,
    metric: ReportMetric,
    regime: RegimeClass | None,
) -> tuple[tuple[float | None, int, tuple[tuple[str, int], ...]], ...]:
    """La définition de la décision 5, recalculée : par jeu, les performances de ce jeu
    où les cinq modèles ont un nombre, puis la moyenne de chaque modèle sur elles."""
    result = []
    for dataset in DataSet:
        rows = []
        for entry in entries:
            if dataset not in entry.datasets:
                continue
            row = [
                performance_values(entry, scenario, ClockRole.ELAPSED, model)[
                    (metric, regime)
                ]
                for model in REPORT_MODELS
            ]
            if all(isinstance(value, float) for value in row):
                rows.append(row)
        for m in range(len(REPORT_MODELS)):
            numbers = [float(row[m]) for row in rows]
            mean = math.fsum(numbers) / len(numbers) if numbers else None
            result.append((mean, len(numbers), ()))
    return tuple(result)


def test_common_row_is_its_definition(world: BacktestRun) -> None:
    """Décision 5 : pour chaque métrique, classe comprise, et chaque jeu,
    ``common_row`` égal à sa définition recalculée ; même effectif pour les cinq,
    aucun motif compté ; ``COMMON_ABS_LEVEL`` (§ 7.2)."""
    entries = list(scored_performances(world))
    for scenario in (USAGE, CONTROL):
        keys = [
            (row.metric, row.regime_class)
            for row in aggregate_table(entries, scenario, ClockRole.ELAPSED)
        ]
        assert len(keys) == (20 if scenario is USAGE else 18)
        for metric, regime in keys:
            row = common_row(entries, scenario, ClockRole.ELAPSED, metric, regime)
            assert (row.metric, row.regime_class) == (metric, regime)
            got = tuple(
                (value.value, value.count, value.missing)
                for by_set in row.by_set
                for value in by_set
            )
            assert got == _common_by_definition(entries, scenario, metric, regime)
            for by_set in row.by_set:
                assert len(by_set) == len(REPORT_MODELS)
                assert len({value.count for value in by_set}) == 1
                assert all(value.missing == () for value in by_set)
    row = common_row(entries, USAGE, ClockRole.ELAPSED, ReportMetric.ABS_LEVEL)
    for dataset, by_set in zip(DataSet, row.by_set, strict=True):
        means, count = COMMON_ABS_LEVEL[dataset.value]
        assert [value.count for value in by_set] == [count] * len(REPORT_MODELS)
        for value, mean in zip(by_set, means, strict=True):
            assert _close(value.value, mean), dataset


def test_common_set_leaves_out_a_performance_one_model_lacks(
    world: BacktestRun,
) -> None:
    """Décision 5 : une performance où Naismith est ``non calé`` sort de l'ensemble
    commun pour les cinq modèles ; un jeu sans performance commune (la répétabilité du
    monde) : cinq agrégats vides."""
    entries = list(scored_performances(world))
    index = next(i for i, e in enumerate(entries) if e.civil_date == date(2026, 6, 27))
    entry = entries[index]
    outing = next(
        run for run in world.outings if run.outing.outing_id == "a-2026-06-27"
    )
    naismith = dict(outing.baselines)[ModelKind.NAISMITH]
    lacking = not_calibrated("a-2026-06-27", ModelKind.NAISMITH, naismith)
    entries[index] = replace(
        entry,
        calibrated=tuple(
            (model, lacking if model is ModelKind.NAISMITH else scores)
            for model, scores in entry.calibrated
        ),
    )
    row = common_row(entries, USAGE, ClockRole.ELAPSED, ReportMetric.ABS_LEVEL)
    repeatability, _, confirmation = row.by_set
    assert [value.count for value in confirmation] == [1] * len(REPORT_MODELS)
    june_25 = _entry(world, "2026-06-25")
    for model, value in zip(REPORT_MODELS, confirmation, strict=True):
        alone = performance_values(june_25, USAGE, ClockRole.ELAPSED, model)
        assert value.value == alone[(ReportMetric.ABS_LEVEL, None)]
        assert value.missing == ()
    assert all(
        (value.value, value.count, value.missing) == (None, 0, ())
        for value in repeatability
    )
    # Son propre effectif, Naismith le perd seul.
    table = aggregate_table(entries, USAGE, ClockRole.ELAPSED, ModelKind.NAISMITH)
    (abs_level,) = [r for r in table if r.metric is ReportMetric.ABS_LEVEL]
    assert abs_level.by_set[2].count == 1
    assert abs_level.by_set[2].missing == ((NOT_CALIBRATED, 1),)
    assert NOT_CALIBRATED in MISSING_ORDER


# ---------------------------------------------------------------------------
# La référence D8 à côté des cinq modèles
# ---------------------------------------------------------------------------


def test_route_comparisons_carry_five_aggregates(world: BacktestRun) -> None:
    """§ 6.5, ``RouteComparison.rows`` : un agrégat par modèle de ``REPORT_MODELS``, v0
    brut en premier, chacun sur les performances du parcours, en usage sous
    l'écoulé."""
    entries = scored_performances(world)
    comparisons = route_comparisons(entries, world.references)
    assert [c.route_id for c in comparisons] == [r for r, _ in world.references]
    for comparison in comparisons:
        on_route = [e for e in entries if comparison.route_id in e.routes]
        for metric, regime, _, by_model in comparison.rows:
            assert len(by_model) == len(REPORT_MODELS)
            for model, value in zip(REPORT_MODELS, by_model, strict=True):
                expected = aggregate(
                    [
                        performance_values(e, USAGE, ClockRole.ELAPSED, model)[
                            (metric, regime)
                        ]
                        for e in on_route
                    ]
                )
                assert value == expected, (comparison.route_id, metric, model)
