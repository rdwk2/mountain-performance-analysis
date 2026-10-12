"""La commande ``mperf backtest`` à cinq modèles (§ 6.6 et § 8.1, test 5, du brief
M4c-2 ; ``0010`` D14 et D15 et leurs précisions de M4c-2 ; décision 10).

- Les formes que le monde n'a pas (§ 7.1), par les fonctions privées de ``cli.py``
  sur des objets construits : les cellules de calage (effort saturé, effort, facteur,
  ``erreur du modèle``, ``non calé``), le calage sous une horloge (statut avec
  ``C_j^eff``, retraits ``support insuffisant`` et ``temps nul``), la ligne de ``C_j``
  (exclusions ``course`` et ``étiquette manquante``, « aucun » sans membre).
- La ligne ``|L| commun`` est ``common_row`` de ``|L|``, en usage, sous l'écoulé
  (``common_row`` remplacé par un espion : les ``L`` communs du monde sont positifs).
- La première ligne de la sortie standard publie l'empreinte de la DÉCLARATION
  (ligne « (M4c, registre) Un processus tué… » de ``BACKLOG.md``) ; la synthèse et le
  corps du rapport se calculent **avant** le RÉSULTAT : une erreur y est un ÉCHEC
  technique, sans RÉSULTAT ni rapport (ligne « (M4c, rapport) … »).

``MPA_DATA_DIR`` pointe dans un dossier temporaire, ``cli.git_state`` est remplacé par
un état fixé (aides de ``test_cli_backtest.py``).
"""

import hashlib
import math
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

import pytest

import mountain_perf.cli as cli
from fixtures.backtest_world import write_world
from mountain_perf.backtest import (
    EVENTS_FILE,
    REPORT_MODELS,
    Aggregate,
    ClockRole,
    CommonRow,
    ReportMetric,
    ScoredPerformance,
    read_registry,
)
from mountain_perf.schemas import (
    CLOCKS,
    CalibrationPopulation,
    CalibrationWithdrawal,
    DataSet,
    EventKind,
    FailureKind,
    ModelCalibration,
    ModelKind,
    PopulationExclusion,
    PopulationExclusionReason,
    Scenario,
    Unavailability,
)
from test_cli_backtest import backtest, lines_of

DAY = date(2026, 6, 10)
MEMBERS = (date(2026, 6, 1), date(2026, 6, 2))


@pytest.fixture
def data(tmp_path: Path) -> Path:
    data = tmp_path / "donnees"
    data.mkdir()
    return data


def _calibration(
    model: ModelKind, beta: float | None, **changes: Any
) -> ModelCalibration:
    """Un calage sous ``M θ1`` à ``C_j^eff`` de deux jours ; ``beta`` donné : calé,
    l'effort ou le facteur qui s'en déduit (D9.2)."""
    fields: dict[str, Any] = {
        "model": model,
        "scenario": Scenario.USAGE,
        "clock": CLOCKS[1],
        "population": MEMBERS,
        "withdrawals": (),
        "beta": beta,
        "effort": None,
        "factor": None,
        "saturated": False,
        "unavailability": None,
    }
    if beta is not None and model is ModelKind.V0_RECALIBRATED:
        unbounded = math.exp(-beta)
        effort = min(max(unbounded, 0.5), 1.5)
        fields |= {
            "effort": effort,
            "factor": 1.0 / effort,
            "saturated": effort != unbounded,
        }
    elif beta is not None:
        fields["factor"] = math.exp(beta)
    fields.update(changes)
    return ModelCalibration(**fields)


SATURATED = _calibration(ModelKind.V0_RECALIBRATED, -1.0)
EFFORT = _calibration(ModelKind.V0_RECALIBRATED, -0.02)
FACTOR = _calibration(ModelKind.NAISMITH, -0.6)
MODEL_ERROR = _calibration(
    ModelKind.TOBLER, None, unavailability=Unavailability.MODEL_ERROR
)
NOT_CALIBRATED = _calibration(
    ModelKind.CONSTANT_SPEED,
    None,
    population=(),
    unavailability=Unavailability.NOT_CALIBRATED,
)
WITHDRAWALS = (
    CalibrationWithdrawal(date(2026, 6, 3), Unavailability.INSUFFICIENT_SUPPORT),
    CalibrationWithdrawal(date(2026, 6, 4), Unavailability.ZERO_TIME),
)


# ---------------------------------------------------------------------------
# Cellules et textes de calage (§ 6.6)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("calibration", "cell"),
    [
        (SATURATED, "e 1.500000 saturé"),
        (EFFORT, "e 1.020201"),
        (FACTOR, "a 0.548812"),
        (MODEL_ERROR, "erreur du modèle"),
        (NOT_CALIBRATED, "non calé"),
    ],
    ids=["effort saturé", "effort", "facteur", "erreur du modèle", "non calé"],
)
def test_calibration_cell(calibration: ModelCalibration, cell: str) -> None:
    """§ 6.6, la cellule de la ligne de calage : ``e <effort>`` pour v0 (suivi de
    « saturé » si l'effort est borné), ``a <facteur>`` pour une baseline, sinon le
    libellé du statut — six décimales."""
    assert cli._calibration_cell(calibration) == cell


@pytest.mark.parametrize(
    ("calibration", "text"),
    [
        (SATURATED, "C_j^eff 2, β −1.000000, e 1.500000 saturé"),
        (FACTOR, "C_j^eff 2, β −0.600000, a 0.548812"),
        (MODEL_ERROR, "erreur du modèle, C_j^eff 2"),
        (NOT_CALIBRATED, "non calé"),
        (
            _calibration(
                ModelKind.V0_RECALIBRATED,
                -0.02,
                population=(date(2026, 6, 1),),
                withdrawals=WITHDRAWALS,
            ),
            "C_j^eff 1, β −0.020000, e 1.020201 (retraits : 2026-06-03 support "
            "insuffisant, 2026-06-04 temps nul)",
        ),
    ],
    ids=["saturé", "facteur", "erreur du modèle", "non calé", "retraits"],
)
def test_calibration_text(calibration: ModelCalibration, text: str) -> None:
    """§ 6.6, le calage sous une horloge du détail d'une sortie : ``C_j^eff``, ``β``
    signé à six décimales et la cellule ; le statut, ``C_j^eff`` compris pour une erreur
    du modèle ; les retraits et leur motif."""
    assert cli._calibration_text(calibration) == text


def test_population_line() -> None:
    """§ 6.6, ``C_j`` d'une performance (D2.4) : ses membres et ses exclusions — course
    et étiquette manquante — ; « aucun » sans membre."""
    origin = datetime(2026, 6, 2, 22, 0, tzinfo=UTC)
    population = CalibrationPopulation(
        DAY,
        origin,
        MEMBERS,
        (
            PopulationExclusion(date(2026, 6, 3), PopulationExclusionReason.RACE),
            PopulationExclusion(date(2026, 6, 4), PopulationExclusionReason.UNLABELLED),
        ),
    )
    assert cli._population_line(population) == (
        "calage       C_j 2 membres : 2026-06-01, 2026-06-02 ; exclues : 2026-06-03 "
        "course, 2026-06-04 étiquette manquante"
    )
    empty = CalibrationPopulation(DAY, origin, (), ())
    assert cli._population_line(empty) == "calage       C_j 0 membre : aucun"


# ---------------------------------------------------------------------------
# La ligne |L| commun (décision 5)
# ---------------------------------------------------------------------------


def test_common_line_is_common_row_of_abs_level(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Décision 5, précision de D15 (M4c-2) : la ligne ``|L| commun`` de chaque jeu est
    ``common_row`` de ``|L|``, en usage, sous l'écoulé — un espion le remplace."""
    calls: list[tuple[Any, ...]] = []

    def spy(
        entries: Any,
        scenario: Scenario,
        role: ClockRole,
        metric: ReportMetric,
        regime: Any = None,
    ) -> CommonRow:
        calls.append((tuple(entries), scenario, role, metric, regime))
        return CommonRow(
            metric,
            regime,
            tuple(
                tuple(
                    Aggregate(0.1 * (d + 1) + 0.01 * m, d + 1, ())
                    for m in range(len(REPORT_MODELS))
                )
                for d in range(len(DataSet))
            ),
        )

    monkeypatch.setattr(cli, "common_row", spy)
    entries: tuple[ScoredPerformance, ...] = ()
    lines = cli._model_aggregate_lines(entries)
    assert calls == [
        ((), Scenario.USAGE, ClockRole.ELAPSED, ReportMetric.ABS_LEVEL, None)
    ]
    common = [line for line in lines if line.startswith(" " * 13 + "|L| commun")]
    assert common == [
        "             |L| commun      0.100000 (1)        0.110000 (1)        "
        "0.120000 (1)        0.130000 (1)        0.140000 (1)",
        "             |L| commun      0.200000 (2)        0.210000 (2)        "
        "0.220000 (2)        0.230000 (2)        0.240000 (2)",
        "             |L| commun      0.300000 (3)        0.310000 (3)        "
        "0.320000 (3)        0.330000 (3)        0.340000 (3)",
    ]


# ---------------------------------------------------------------------------
# La DÉCLARATION publiée dès son ajout ; le calcul avant le RÉSULTAT (décision 10)
# ---------------------------------------------------------------------------


def test_first_line_publishes_the_declaration(
    tmp_path: Path, data: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Décision 10, précision de D14 (M4c-2) : la première ligne de la sortie standard
    est ``déclaration  1 enregistrée ; dernière ligne sha256 <empreinte>``, l'empreinte
    de la première ligne du journal ; la synthèse suit."""
    outcome = backtest(monkeypatch, data, write_world(tmp_path / "monde"))
    assert (outcome.code, outcome.err) == (0, "")
    journal = (data / "registre" / EVENTS_FILE).read_bytes()
    first = hashlib.sha256(journal.split(b"\n")[0]).hexdigest()
    lines = lines_of(outcome.out)
    assert lines[0] == f"déclaration  1 enregistrée ; dernière ligne sha256 {first}"
    assert lines[1].startswith("backtest     cinq modèles (v0 brut, ")
    assert lines[2].startswith("registre     déclaration 1, résultat 2 ;")


@pytest.mark.parametrize("computed", ["_report_body", "_summary_parts"])
def test_report_is_computed_before_the_result(
    tmp_path: Path, data: Path, monkeypatch: pytest.MonkeyPatch, computed: str
) -> None:
    """Décision 10, précision de D14 (M4c-2) : le corps du rapport et la synthèse se
    calculent avant le RÉSULTAT — une erreur de ce calcul est un ÉCHEC technique ; code
    1, le journal a la DÉCLARATION puis l'ÉCHEC, aucun RÉSULTAT, aucun rapport ;
    l'erreur publie l'empreinte de l'ÉCHEC, la sortie standard celle de la
    DÉCLARATION."""

    def raising(*arguments: object) -> object:
        raise ValueError("calcul du rapport")

    monkeypatch.setattr(cli, computed, raising)
    outcome = backtest(monkeypatch, data, write_world(tmp_path / "monde"))
    assert outcome.code == 1
    events = read_registry(data / "registre").events
    assert [event.kind for event in events] == [
        EventKind.DECLARATION,
        EventKind.FAILURE,
    ]
    failure = events[-1].failure
    assert failure is not None
    assert (failure.kind, failure.reason) == (
        FailureKind.TECHNICAL,
        "ValueError : calcul du rapport",
    )
    assert not (data / "rapports").exists() or not any((data / "rapports").iterdir())
    assert outcome.err == (
        "Erreur : échec de l'exécution, ÉCHEC enregistré (événement 2 ; dernière ligne "
        f"sha256 {outcome.seal()}) : ValueError : calcul du rapport\n"
    )
    journal = (data / "registre" / EVENTS_FILE).read_bytes()
    first = hashlib.sha256(journal.split(b"\n")[0]).hexdigest()
    assert outcome.out == (
        f"déclaration  1 enregistrée ; dernière ligne sha256 {first}\n"
    )
