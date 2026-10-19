"""Garanties du rapport de sensibilité de la commande (M4d-3, ``cli.py`` ; précision
de D15) que les tests joints ne tenaient pas — correctifs de la relecture de la PR #32
(relecture C, passe 1).

Les tests joints vérifient la forme du rapport (titres, rubriques, ordre, légende) ;
ceux-ci, ses valeurs : pour une configuration de mouvement, les agrégats d'usage, les
trois axes et la dérive de v0 brut de **sa** comparaison, sous **son** horloge ; ``L``
de v0 brut, performance par performance, le comparateur puis la configuration ; sous
l'écoulé, la table des fourchettes de **sa** paire. Les valeurs attendues sont lues dans
le document de sensibilité du registre de la commande, égal à celui de la sensibilité
du monde par l'API, et dans les évaluations de ses paires, puis mises en forme par les
fonctions du rapport. Aucune donnée réelle.
"""

from typing import Any

import pytest

import mountain_perf.cli as cli
from fixtures.sensitivity_world import BacktestSensitivity, backtest_sensitivity
from mountain_perf.backtest import (
    REPORT_MODELS,
    axis_counts,
    drift_under,
    load_sensitivity,
    read_registry,
    scored_performances,
    sensitivity_table,
)
from mountain_perf.schemas import (
    CLOCKS,
    ModelKind,
    SensitivityMetric,
    SensitivityOutcome,
)
from test_cli_backtest import contiguous, lines_of
from test_cli_sensitivity import REPORT, _section, sensitivity_command

CENTRAL_PAIR = (250.0, 30.0)
MOVEMENT_RANK = 9
"""``(250, 30)`` sous ``M θ1`` : une configuration de mouvement."""
OTHER_PAIR_RANK = 0
"""``(100, 15)`` sous l'écoulé : une autre paire que la centrale."""


@pytest.fixture(scope="module")
def world(tmp_path_factory: pytest.TempPathFactory) -> BacktestSensitivity:
    """La sensibilité de ``just backtest`` sur le monde, par l'API."""
    return backtest_sensitivity(tmp_path_factory)


@pytest.fixture(scope="module")
def report(tmp_path_factory: pytest.TempPathFactory) -> list[str]:
    """Les lignes du rapport de sensibilité de la commande sur le monde."""
    command = sensitivity_command(tmp_path_factory)
    assert command.code == 0
    return lines_of(command.report(REPORT))


@pytest.fixture(scope="module")
def document(
    tmp_path_factory: pytest.TempPathFactory, world: BacktestSensitivity
) -> SensitivityOutcome:
    """Le document de sensibilité du registre de la commande, égal à celui de la
    sensibilité du monde par l'API (même monde, même code)."""
    command = sensitivity_command(tmp_path_factory)
    registry = command.data / "registre"
    loaded = load_sensitivity(registry, read_registry(registry), 4)
    assert loaded is not None
    assert loaded == world.run.evaluation.outcome
    return loaded


def _datasets(world: BacktestSensitivity) -> list[Any]:
    return [entry.datasets for entry in scored_performances(world.central)]


def _table(document: SensitivityOutcome, rank: int, world: BacktestSensitivity) -> Any:
    return cli._sensitivity_table_lines(
        sensitivity_table(
            document.configurations[rank], _datasets(world), REPORT_MODELS
        )
    )


def test_report_table_is_the_one_of_its_configuration(
    report: list[str], document: SensitivityOutcome, world: BacktestSensitivity
) -> None:
    """Précision de D15 (M4d-3) : les agrégats d'une configuration de mouvement sont
    ceux de **sa** comparaison, sous son horloge — pas ceux du comparateur
    (l'écoulé)."""
    expected = _table(document, MOVEMENT_RANK, world)
    assert expected != _table(document, document.comparator, world)
    assert contiguous(expected, _section(report, MOVEMENT_RANK))


def _axis_lines(document: SensitivityOutcome, rank: int) -> list[str]:
    counts = axis_counts(document.configurations[rank], REPORT_MODELS)
    lines = [cli._row("axes", [cli.MODEL_LABELS[c.model] for c in counts])]
    for label, field in cli.AXIS_ROWS:
        lines.append(cli._row(label, [str(getattr(c, field)) for c in counts]))
    return lines


def test_report_axes_are_those_of_its_configuration(
    report: list[str], document: SensitivityOutcome
) -> None:
    """Précision de D15 (M4d-3) : les trois axes par modèle d'une configuration sont
    ceux de sa comparaison au comparateur."""
    expected = _axis_lines(document, MOVEMENT_RANK)
    assert expected != _axis_lines(document, document.comparator)
    assert contiguous(expected, _section(report, MOVEMENT_RANK))


def test_report_level_lines_read_comparator_then_configuration(
    report: list[str], document: SensitivityOutcome
) -> None:
    """Précision de D15 (M4d-3) : ``L`` de v0 brut, performance par performance — le
    comparateur, puis la configuration, la disponibilité, l'écart, les composantes
    changées."""
    configuration = document.configurations[MOVEMENT_RANK]
    section = _section(report, MOVEMENT_RANK)
    differs = 0
    for performance in configuration.performances:
        if performance.motif is not None:
            continue
        (level,) = [
            c
            for c in performance.metrics
            if c.model is ModelKind.V0_RAW and c.metric is SensitivityMetric.LEVEL
        ]
        support = ", ".join(cli.SUPPORT_COMPONENT_LABELS[c] for c in level.support)
        line = cli._row(
            performance.civil_date.isoformat(),
            [
                cli._label(level.comparator, cli._log),
                cli._label(level.value, cli._log),
                cli.AVAILABILITY_LABELS[level.availability],
                "—" if level.difference is None else cli._log(level.difference),
                support or "—",
            ],
        )
        assert line in section
        differs += level.comparator != level.value
    assert differs > 0


def _drift_lines(
    world: BacktestSensitivity, pair: tuple[float, float], clock: Any
) -> Any:
    (evaluated,) = [p for p in world.run.evaluation.pairs if p.pair == pair]
    evaluation = evaluated.evaluation
    assert evaluation is not None
    lines = []
    for outing in evaluation.outings:
        drift = drift_under(evaluation, outing, clock)
        if drift is None:
            continue
        (diagnostic,) = [
            d
            for d in drift.diagnostics
            if d.model is ModelKind.V0_RAW and d.clock == clock
        ]
        lines.append(
            cli._drift_row(outing.outing.outing_id, cli._drift_fit_cells(diagnostic))
        )
    return lines


def test_report_drift_is_read_under_the_configuration_clock(
    report: list[str], world: BacktestSensitivity
) -> None:
    """Précision de D15 (M4d-3) : la dérive de v0 brut d'une configuration de
    mouvement, sous **son** horloge — pas les valeurs de l'écoulé sous son titre."""
    expected = _drift_lines(world, CENTRAL_PAIR, CLOCKS[1])
    assert expected
    assert expected != _drift_lines(world, CENTRAL_PAIR, CLOCKS[0])
    assert contiguous(expected, _section(report, MOVEMENT_RANK))


def test_report_bands_are_those_of_the_pair(
    report: list[str], world: BacktestSensitivity
) -> None:
    """Précision de D15 (M4d-3) : sous l'écoulé, la table des fourchettes de **sa**
    paire — pour ``(100, 15)``, pas celle de la centrale."""
    pairs = {p.pair: p.evaluation for p in world.run.evaluation.pairs}
    own, central = pairs[(100.0, 15.0)], pairs[CENTRAL_PAIR]
    assert own is not None
    assert central is not None
    expected = cli._band_aggregate_lines(scored_performances(own))
    assert expected != cli._band_aggregate_lines(scored_performances(central))
    assert contiguous(expected, _section(report, OTHER_PAIR_RANK))
