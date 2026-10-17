"""Garanties de la rubrique « dérive » du rapport complet (``cli.py`` ; précision P12.10
de M4d-1, arbitrage E4) que la batterie jointe n'exerçait pas : relecture C de la PR #28
(constats 2 à 4) et balayage par mutation de la PR #28 (lacunes L6 à L9). Des lacunes de
la conception, pas des défauts du code."""

import dataclasses
from typing import Any, cast

import pytest

from fixtures.segments import hand_profile
from mountain_perf import cli
from mountain_perf.backtest.drift import drift_diagnostic
from mountain_perf.model.engine import ProjectedTimeline
from mountain_perf.schemas import (
    CLOCKS,
    DRIFT_MODELS,
    DriftDiagnostic,
    ModelKind,
    OutingDrift,
    Unavailability,
)
from test_backtest_drift import FORECAST, POSITIONS, diagnose
from test_cli_drift import three
from test_schemas_drift import outing

ELAPSED = CLOCKS[0]


def _five_intervals() -> DriftDiagnostic:
    """Le cas de ``test_calibration_invariance`` : des retraits identifiables."""
    profile = hand_profile([0.0, 1000.0, 2000.0], [0.0, 30.0, 0.0])
    timeline = ProjectedTimeline((0.0, 1000.0, 2000.0), (0.8, 0.6))
    positions = [300.0, 700.0, 1000.0, 1400.0, 2000.0]
    v0: list[float | None] = [timeline.time_at(s) for s in positions]
    return drift_diagnostic(
        ModelKind.V0_RAW,
        CLOCKS[1],
        observed_s=[250.0, 600.0, 830.0, 1100.0, 1500.0],
        model_s=v0,
        v0_s=v0,
        positions_m=positions,
        origin_m=0.0,
        profile=profile,
        v0_timeline=timeline,
    )


def _rubric(monkeypatch: pytest.MonkeyPatch, drift: OutingDrift) -> list[str]:
    """La rubrique d'une dérive construite : ``outing_drift_report`` remplacé."""
    monkeypatch.setattr(cli, "outing_drift_report", lambda run, outing: drift)
    return cli._drift_lines(cast(Any, None), cast(Any, None))


# --- retraits identifiables et étendue (relecture C, constat 2 ; balayage, L7) --------


def test_slope_range_is_ordered_and_rendered() -> None:
    """L'étendue est ``(min, max)`` des pentes des retraits identifiables, et la
    rubrique l'écrit ``[min ; max]`` (``0010`` D12 ; arbitrage E4)."""
    diagnostic = _five_intervals()
    assert diagnostic.slope_range is not None
    low, high = diagnostic.slope_range
    assert low < high
    cells = cli._drift_fit_cells(diagnostic)
    assert cells[6] == f"[{cli._log(low)} ; {cli._log(high)}]"


def test_identifiable_withdrawals_in_the_table() -> None:
    """La cellule des retraits compte les identifiables sur ``H`` ; l'étendue vient de
    leurs pentes."""
    cells = cli._drift_fit_cells(three((0.4, 0.6, None), b=0.5))
    assert cells[4] == "2/3"
    assert cells[6] == f"[{cli._log(0.4)} ; {cli._log(0.6)}]"


def test_identifiable_withdrawals_in_the_detail() -> None:
    """Au détail de v0 brut, un retrait identifiable écrit ses ``ddl`` et sa pente."""
    diagnostic = three((0.4, None, None), b=0.5)
    first = diagnostic.withdrawals[0]
    assert first.dof is not None
    lines = cli._drift_detail_lines(diagnostic)
    header = next(i for i, line in enumerate(lines) if "retraits de v0 brut" in line)
    row = lines[header + 1]
    assert f" ; {first.dof} ; " in row
    assert row.endswith(cli._log(0.4))


def test_sign_of_a_slope_below_one() -> None:
    """Le signe est celui de la pente, à 0 près : une pente de 0,5 et des retraits de
    0,4, 1,5 et 0,6 sont « stable »."""
    assert cli._drift_sign(three((0.4, 1.5, 0.6), b=0.5)) == "stable"


# --- motifs (relecture C, constats 3 et 4 ; balayage, L8 et L9) -----------------------


def test_mixed_reasons_keep_the_table(monkeypatch: pytest.MonkeyPatch) -> None:
    """Séquence vide, v0 brut « support insuffisant », les modèles calés « non calé » :
    la table est écrite, une ligne par modèle, avec l'horizon et ``R_0`` « — » — la
    ligne unique est réservée à un motif commun."""
    diagnostics = tuple(
        DriftDiagnostic(
            model,
            ELAPSED,
            (),
            None,
            (),
            (),
            None,
            (),
            None,
            Unavailability.INSUFFICIENT_SUPPORT
            if model is ModelKind.V0_RAW
            else Unavailability.NOT_CALIBRATED,
        )
        for model in DRIFT_MODELS
    )
    drift = outing(elements=0, horizon_s=None, diagnostics=diagnostics)
    lines = _rubric(monkeypatch, drift)
    assert len(lines) == 3 + len(DRIFT_MODELS)
    assert "horizon P⁰_H — ; R_0 — ;" in lines[0]
    assert sum("non calé" in line for line in lines) == len(DRIFT_MODELS) - 1


def test_zero_time_label_in_the_table() -> None:
    """« temps nul » : le libellé d'un diagnostic indisponible pour un ``t_h <= 0`` (le
    seul des cinq motifs que la batterie jointe ne lisait pas)."""
    diagnostic = diagnose([0.0, 20.0, 40.0], FORECAST, POSITIONS, clock_index=1)
    assert diagnostic.unavailability is Unavailability.ZERO_TIME
    assert cli._drift_fit_cells(diagnostic) == ["temps nul"]


def test_zero_time_head_detail(monkeypatch: pytest.MonkeyPatch) -> None:
    """v0 brut en « temps nul » sous l'écoulé : le détail écrit « — » pour ``y_h`` et
    l'influence, sans exception (le corps du rapport est calculé avant le RÉSULTAT)."""
    head = diagnose([0.0, 20.0, 40.0], FORECAST, POSITIONS, clock_index=0)
    assert head.unavailability is Unavailability.ZERO_TIME
    diagnostics = tuple(dataclasses.replace(head, model=m) for m in DRIFT_MODELS)
    drift = outing(targets=3, stop=None, diagnostics=diagnostics, horizon_s=600.0)
    lines = _rubric(monkeypatch, drift)
    detail = [line for line in lines if line.strip().startswith("1 ")]
    assert detail
    assert " ; — ; " in detail[0]
    assert detail[0].endswith("; —")
