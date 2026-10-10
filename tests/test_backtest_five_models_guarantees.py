"""Garanties de l'exécution, du rapport et de la commande à cinq modèles tenues par des
tests (correctifs de la PR #23, M4c-2 ; relecture C et balayage de mutation de la
conception).

- **La première ligne est vidée aussitôt** (brief M4c-2, § 3, décision 10 ; § 6.6,
  ``flush=True``) : quand la sortie standard est tamponnée (redirigée vers un fichier ou
  un tube), la ligne de la DÉCLARATION est déjà écrite quand le calcul commence.
- **Une interruption au clavier dans le calcul du rapport est un ÉCHEC technique**
  (§ 6.3, § 6.6) : la DÉCLARATION puis l'ÉCHEC, ni RÉSULTAT ni rapport.
- ``role_clock_scores`` rend le **statut** d'une horloge calée sans scores —
  ``model_error`` comme ``not_calibrated`` (§ 6.5).
- **Les deux notes de la ligne de calage**, dans cet ordre et entre les mêmes
  parenthèses : « (contrôle ; jour multi-sorties, <première sortie>) » (§ 6.6, point 4
  de la synthèse).
- **Les objets neufs sont gelés et portent des tuples** (§ 6.3, § 6.5) :
  ``BacktestEvaluation`` et ``CommonRow`` gelés ; ``OutingRun.baselines``,
  ``BacktestRun.calibration``, ``ScoredPerformance.calibrated`` et ``CommonRow.by_set``
  des tuples.

Le monde de M4b-5 est exécuté une fois par module (``world``) ; la commande, par les
aides de ``test_cli_backtest.py``, dans un dossier de données temporaire.
"""

import contextlib
import dataclasses
import io
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import pytest

import mountain_perf.cli as cli
from fixtures.backtest_world import COMMIT, COURBE, run_world, write_world
from mountain_perf.backtest import (
    BacktestEvaluation,
    BacktestRun,
    ClockRole,
    CommonRow,
    GitState,
    ReportMetric,
    common_row,
    read_registry,
    role_clock_scores,
    scored_performances,
)
from mountain_perf.schemas import (
    EventKind,
    FailureKind,
    ModelKind,
    Scenario,
    Unavailability,
)
from test_backtest_report_models import _entry
from test_cli_backtest import backtest, lines_of


@pytest.fixture(scope="module")
def world(tmp_path_factory: pytest.TempPathFactory) -> BacktestRun:
    """Le monde de M4b-5 exécuté une fois."""
    return run_world(tmp_path_factory.mktemp("monde"))


@pytest.fixture
def data(tmp_path: Path) -> Path:
    data = tmp_path / "donnees"
    data.mkdir()
    return data


# ---------------------------------------------------------------------------
# La DÉCLARATION publiée et vidée ; le calcul avant le RÉSULTAT (décision 10)
# ---------------------------------------------------------------------------


def test_declaration_line_is_flushed_before_the_computation(
    tmp_path: Path, data: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Décision 10, § 6.6 : la sortie standard tamponnée (un ``TextIOWrapper`` sur des
    octets, comme un fichier ou un tube) ; quand la synthèse commence à se calculer, la
    ligne de la DÉCLARATION est déjà dans les octets écrits, et elle seule."""
    raw = io.BytesIO()
    stdout = io.TextIOWrapper(raw, encoding="utf-8", newline="\n")
    seen: list[bytes] = []
    original = cli._summary_parts

    def watching(*arguments: Any, **keywords: Any) -> Any:
        seen.append(raw.getvalue())
        return original(*arguments, **keywords)

    monkeypatch.setattr(cli, "_summary_parts", watching)
    monkeypatch.setenv("MPA_DATA_DIR", str(data))
    monkeypatch.setattr(cli, "git_state", lambda directory: GitState(COMMIT, False))
    manifest = write_world(tmp_path / "monde")
    with contextlib.redirect_stdout(stdout):
        code = cli.main(["backtest", str(manifest), "--curve", str(COURBE)])
    stdout.flush()
    assert code == 0
    (written,) = seen
    text = written.decode("utf-8")
    assert text.startswith("déclaration  1 enregistrée ; dernière ligne sha256 ")
    assert text.count("\n") == 1
    assert text.endswith("\n")


def test_keyboard_interrupt_in_the_report_body(
    tmp_path: Path, data: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """§ 6.3, § 6.6 : une interruption au clavier pendant le calcul du corps du rapport
    est un ÉCHEC technique — code 1, la DÉCLARATION puis l'ÉCHEC, aucun RÉSULTAT, aucun
    rapport ; la sortie standard ne porte que la ligne de la DÉCLARATION."""

    def interrupted(*arguments: object) -> object:
        raise KeyboardInterrupt

    monkeypatch.setattr(cli, "_report_body", interrupted)
    outcome = backtest(monkeypatch, data, write_world(tmp_path / "monde"))
    assert outcome.code == 1
    events = read_registry(data / "registre").events
    assert [event.kind for event in events] == [
        EventKind.DECLARATION,
        EventKind.FAILURE,
    ]
    failure = events[-1].failure
    assert failure is not None
    assert failure.kind is FailureKind.TECHNICAL
    assert failure.reason.startswith("KeyboardInterrupt")
    assert not (data / "rapports").exists() or not any((data / "rapports").iterdir())
    (line,) = lines_of(outcome.out)
    assert line.startswith("déclaration  1 enregistrée ; dernière ligne sha256 ")


# ---------------------------------------------------------------------------
# Le statut d'une horloge calée sans scores (§ 6.5)
# ---------------------------------------------------------------------------


def test_model_error_status_of_a_calibrated_clock(world: BacktestRun) -> None:
    """§ 6.5, ``role_clock_scores`` : sous une horloge calée sans scores, la valeur de
    son statut — ``model_error`` (l'entrée du 27 juin, horloges d'usage de la vitesse
    constante en erreur du modèle)."""
    entry = _entry(world, "2026-06-27")
    model = ModelKind.CONSTANT_SPEED
    scaled = dict(entry.calibrated)[model]
    usage = scaled.usage
    assert usage is not None
    clocks = tuple(
        clock
        if clock.calibration.unavailability is not None
        else replace(
            clock,
            calibration=replace(
                clock.calibration,
                beta=None,
                effort=None,
                factor=None,
                saturated=False,
                unavailability=Unavailability.MODEL_ERROR,
            ),
            scores=None,
        )
        for clock in usage.clocks
    )
    erroneous = replace(scaled, usage=replace(usage, clocks=clocks))
    changed = replace(
        entry,
        calibrated=tuple(
            (kind, erroneous if kind is model else scores)
            for kind, scores in entry.calibrated
        ),
    )
    assert (
        role_clock_scores(changed, Scenario.USAGE, ClockRole.ELAPSED, model)
        == Unavailability.MODEL_ERROR.value
    )


# ---------------------------------------------------------------------------
# Les deux notes de la ligne de calage (§ 6.6)
# ---------------------------------------------------------------------------


def test_both_notes_of_a_calibration_line(world: BacktestRun) -> None:
    """§ 6.6, point 4 de la synthèse : un jour multi-sorties dont la première sortie
    scorée est en contrôle seul (sans référence) — « (contrôle ; jour multi-sorties,
    <première sortie>) », dans cet ordre, entre les mêmes parenthèses."""
    performance = next(p for p in world.calibration if p.outings)
    outings = tuple(replace(entry, usage=None) for entry in performance.outings)
    day = performance.population.civil_date
    declared = SimpleNamespace(
        performance=SimpleNamespace(civil_date=day, is_multi_outing=True)
    )
    run = SimpleNamespace(
        preparation=SimpleNamespace(
            declaration=SimpleNamespace(performances=[declared])
        ),
        calibration=[
            SimpleNamespace(population=performance.population, outings=outings)
        ],
    )
    (line,) = cli._calibration_lines(cast(BacktestRun, run))[2:]
    assert line.endswith(f" (contrôle ; jour multi-sorties, {outings[0].outing_id})")


# ---------------------------------------------------------------------------
# Objets gelés, champs en tuples (§ 6.3, § 6.5)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("cls", [BacktestEvaluation, CommonRow])
def test_new_objects_are_frozen(cls: Any) -> None:
    """§ 6.3, § 6.5 : ``BacktestEvaluation`` et ``CommonRow`` sont des dataclasses
    gelées — affecter un champ lève ``FrozenInstanceError``."""
    instance = object.__new__(cls)
    with pytest.raises(dataclasses.FrozenInstanceError):
        setattr(instance, dataclasses.fields(cls)[0].name, None)


def test_new_fields_are_tuples(world: BacktestRun) -> None:
    """§ 6.3, § 6.5 : ``OutingRun.baselines``, ``BacktestRun.calibration``,
    ``ScoredPerformance.calibrated`` et ``CommonRow.by_set`` (et chacun de ses jeux)
    sont des tuples."""
    assert isinstance(world.calibration, tuple)
    assert all(isinstance(run.baselines, tuple) for run in world.outings)
    entries = scored_performances(world)
    assert all(isinstance(entry.calibrated, tuple) for entry in entries)
    row = common_row(entries, Scenario.USAGE, ClockRole.ELAPSED, ReportMetric.ABS_LEVEL)
    assert isinstance(row.by_set, tuple)
    assert all(isinstance(values, tuple) for values in row.by_set)
