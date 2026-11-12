"""La condition 7 de l'accord du format 6 (OG-2, E6), correctifs de la PR #44 : le
document des termes ne nomme que le comparateur (C-1 de la relecture C du bloc 1), et
les termes d'un jour multi-sorties portent chaque scénario présent sur l'une
quelconque de ses sorties scorées, chacune recoupée (D-1 de la relecture C du
bloc 2)."""

from __future__ import annotations

import dataclasses
import json
import math
from collections.abc import Mapping, Sequence
from datetime import date
from pathlib import Path
from typing import Any

import pytest

import test_og2_accord as t
from mountain_perf.backtest import rolling as rolling_module
from mountain_perf.backtest.execution import BacktestError
from mountain_perf.backtest.registry import RegistryError, read_registry
from mountain_perf.schemas import (
    CalibratedOutingScores,
    CalibratedPerformance,
    CalibrationTerms,
    CurveStatus,
    ModelKind,
    OutingScores,
    Performance,
    Scenario,
)
from mountain_perf.validation import ContractError
from test_og2_evaluation import evaluate
from test_og2_rolling import build_world, fix_world, freeze_reads, prepare


@pytest.fixture(autouse=True)
def _world(monkeypatch: pytest.MonkeyPatch) -> None:
    fix_world(monkeypatch)


# --- Le document des termes ne nomme que le comparateur (C-1) -------------------------


@pytest.mark.parametrize(
    "model", [m for m in ModelKind if m is not ModelKind.V0_RECALIBRATED]
)
def test_the_terms_document_names_the_comparator_only(model: ModelKind) -> None:
    """Le contrat refuse un document des termes d'un autre modèle que v0 + effort
    recalé (brief § 6.5 (d) : « ``model`` : le comparateur »)."""
    with pytest.raises(ContractError, match="v0 \\+ effort recalé"):
        CalibrationTerms(model, ())


def test_a_stored_terms_document_of_another_model_is_refused(tmp_path: Path) -> None:
    """Le constat C-1 : un document des termes qui nomme v0 brut, avec un ``β`` faux de
    1e−9 en relatif (refusé sous le comparateur par
    ``test_a_beta_changed_by_1e_9_is_refused``), passait la condition 7 sans être
    recoupé. Écrit hors du contrat (comme le ferait un outil tiers), il est refusé à la
    relecture du document."""
    built = t.world()
    scored, _ = t.result_documents(built)
    calibrated = scored[1].scores[1][1]
    assert isinstance(calibrated, CalibratedOutingScores)
    beta = calibrated.control.clocks[0].calibration.beta
    assert beta is not None
    delta = 1e-9 * abs(beta)

    def lie(document: Any) -> Any:
        moved = t._shift(document, lambda value: value * math.exp(delta))
        object.__setattr__(moved, "model", ModelKind.V0_RAW)
        return moved

    t.refused(tmp_path, built, "v0 + effort recalé", terms_change=lie)


# --- Les termes d'un jour multi-sorties (D-1) -----------------------------------------


def _first_outing_without_reference(manifest: Path) -> None:
    """Le 2026-06-12 a trois sorties ; la première (par rang), ``a-2026-06-12``, perd
    sa route et sa référence : le comparateur n'a pas d'usage sur elle, mais en a un
    sur ``b-2026-06-12``."""
    data = json.loads(manifest.read_text(encoding="utf-8"))
    for outing in data["outings"]:
        if outing["id"] == "a-2026-06-12":
            outing.pop("route")
            outing.pop("reference")
            outing["dataset"] = "development"
    manifest.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")


def test_the_terms_of_a_multi_outing_day_carry_the_usage_of_a_later_outing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Brief § 6.5 (d) et § 6.8 (c) : « pour v0 + effort recalé, chaque scénario
    présent et chaque horloge déclarée ». Sous ``W`` = 28, le 2026-06-12 est ``curve``
    et le comparateur est calé en usage sur sa deuxième sortie : les termes portent
    l'usage, et l'accord relit le registre sans refus."""
    freeze_reads(monkeypatch)
    manifest = build_world(tmp_path)
    _first_outing_without_reference(manifest)
    preparation = prepare(manifest, [28])
    (evaluation,) = evaluate(preparation, tmp_path / "glissant")
    read_registry(tmp_path / "glissant")
    performances = preparation.common.performances
    j = next(k for k, p in enumerate(performances) if p.civil_date == date(2026, 6, 12))
    assert preparation.windows[0].curves[j].entry.status is CurveStatus.CURVE
    comparator = [
        entry
        for entry in evaluation.calibration[j].outings
        if entry.control.model is ModelKind.V0_RECALIBRATED
    ]
    assert comparator[0].usage is None
    assert any(
        entry.usage is not None and entry.usage.clocks[0].calibration.beta is not None
        for entry in comparator
    )
    terms = evaluation.terms[j]
    assert terms is not None
    assert {s.scenario for s in terms.sets} == {Scenario.CONTROL, Scenario.USAGE}


def test_the_accord_reads_every_scored_outing_of_a_day(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """La condition 7 lit toutes les sorties scorées par le comparateur, pas la
    première : les termes qu'écrivait la tête de la PR (les scénarios de la première
    sortie seule) sont refusés quand une sortie suivante du jour est calée en usage. Le
    refus de l'accord devient l'ÉCHEC technique de la fenêtre."""
    freeze_reads(monkeypatch)
    manifest = build_world(tmp_path)
    _first_outing_without_reference(manifest)
    preparation = prepare(manifest, [28])
    original = rolling_module._terms

    def first_outing_only(
        performance: Performance,
        performances: Sequence[Performance],
        calibrated: CalibratedPerformance,
        unscaled: Mapping[str, Mapping[ModelKind, OutingScores]],
    ) -> CalibrationTerms:
        document = original(performance, performances, calibrated, unscaled)
        comparator = [
            entry
            for entry in calibrated.outings
            if entry.control.model is ModelKind.V0_RECALIBRATED
        ]
        if not comparator or comparator[0].usage is not None:
            return document
        kept = tuple(s for s in document.sets if s.scenario is Scenario.CONTROL)
        return dataclasses.replace(document, sets=kept)

    monkeypatch.setattr(rolling_module, "_terms", first_outing_only)
    with pytest.raises(BacktestError) as error:
        evaluate(preparation, tmp_path / "glissant")
    cause = error.value.__cause__
    assert isinstance(cause, RegistryError)
    assert "condition 7" in str(cause)
    assert "2026-06-12" in str(cause)
