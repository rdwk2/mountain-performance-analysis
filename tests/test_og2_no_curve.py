"""« sans courbe » (``Unavailability.NO_CURVE``) hors du mode glissant, par une pièce
que la condition 8 ne visite pas (relecture C du bloc 1, mutation 7)."""

from __future__ import annotations

import dataclasses
from pathlib import Path

import pytest

from fixtures.registry import (
    CALIBRATED_MODELS,
    at,
    declaration,
    experiment,
    references,
    registry_root,
)
from mountain_perf.backtest.registry import (
    append_declaration,
    read_registry,
    verify_registry,
)
from mountain_perf.schemas import MetricValue, Unavailability
from mountain_perf.validation import ContractError
from test_backtest_registry_format4 import _declared, _five, _refused_append


def test_a_frozen_reference_without_curve_in_a_declared_mode_line(
    tmp_path: Path,
) -> None:
    """Une DÉCLARATION « courbe déclarée » dont l'expérience fige une référence de
    valeur « sans courbe » : la ligne est écrite, relue et vérifiée."""
    declared = experiment()
    local, borrowed = declared.frozen_references
    no_curve = dataclasses.replace(
        borrowed, value=MetricValue(None, Unavailability.NO_CURVE, borrowed.value.count)
    )
    changed = dataclasses.replace(declared, frozen_references=(local, no_curve))
    root = registry_root(tmp_path)
    append_declaration(
        root,
        declaration(experiment=changed, models=CALIBRATED_MODELS),
        recorded_at=at(0),
    )
    event = read_registry(root).events[0]
    assert event.declaration is not None
    assert event.declaration.rolling is None
    assert event.declaration.experiment is not None
    reference = event.declaration.experiment.frozen_references[1]
    assert reference.value.unavailability is Unavailability.NO_CURVE
    verify_registry(root)


def test_a_d8_reference_cannot_carry_no_curve() -> None:
    """Un document de référence D8 dont un niveau vaudrait « sans courbe » : refusé par
    son contrat (D8.4, un F absent porte insufficient_support) avant tout écrit."""
    (_, reference), *_ = references()
    clock = reference.clocks[0]
    level = MetricValue(None, Unavailability.NO_CURVE, clock.level.count)
    with pytest.raises(ContractError, match=r"D8\.4"):
        dataclasses.replace(clock, level=level)


def test_bands_without_curve_outside_rolling_are_refused(tmp_path: Path) -> None:
    """Condition 8, fourchettes (constat C-2 de la relecture C du bloc 1, sans
    contre-exemple dans la relecture) : hors du mode glissant, des fourchettes dont la
    médiane de la cible d'usage vaudrait « sans courbe » sont refusées à l'ajout."""
    written = _five()
    k, scored = next((k, o) for k, o in enumerate(written) if o.bands is not None)
    assert scored.bands is not None
    band = scored.bands.models[0]
    assert band.median_usage_target is not None
    no_curve = MetricValue(
        None, Unavailability.NO_CURVE, band.median_usage_target.count
    )
    bands = dataclasses.replace(
        scored.bands,
        models=(
            dataclasses.replace(band, median_usage_target=no_curve),
            *scored.bands.models[1:],
        ),
    )
    changed = (
        *written[:k],
        dataclasses.replace(scored, bands=bands),
        *written[k + 1 :],
    )
    _refused_append(
        tmp_path,
        _declared(),
        changed,
        f"ajout refusé : {scored.outing_id!r}, fourchettes : « sans courbe » "
        "n'existe qu'en mode glissant (OG-2)",
    )
