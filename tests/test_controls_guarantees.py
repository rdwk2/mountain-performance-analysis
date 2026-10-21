"""Garanties de ``ParameterDisplay`` et de ``changed_values`` sans test à la tête de la
PR #33 (relecture de la PR) : l'ordre des invariants, éprouvé par des entrées qui en
violent deux à la fois ; un pas infini refusé ; « qui diffèrent du défaut », sans
tolérance.
"""

import math

import pytest

from mountain_perf.controls import changed_values, parameter_controls
from mountain_perf.model import MODEL_PARAMETER_DISPLAYS, MODEL_PARAMETER_SPECS
from mountain_perf.schemas import ParameterDisplay
from mountain_perf.validation import ContractError


@pytest.mark.parametrize(
    ("label", "low", "high", "step", "message"),
    [
        # Le libellé avant la finitude des bornes.
        ("", math.nan, 1.0, 1.0, r"^x\.label ne doit pas être vide\.$"),
        # La finitude de low avant celle de high.
        ("X", math.nan, math.inf, 1.0, r"^x\.low doit être fini, reçu nan\.$"),
        # La finitude du pas avant low < high.
        ("X", 2.0, 1.0, math.inf, r"^x\.step doit être fini, reçu inf\.$"),
        # Un pas infini, seul.
        ("X", 0.0, 1.0, math.inf, r"^x\.step doit être fini, reçu inf\.$"),
    ],
    ids=["libelle-puis-low", "low-puis-high", "pas-puis-ordre", "pas-infini"],
)
def test_display_invariants_in_their_order(
    label: str, low: float, high: float, step: float, message: str
) -> None:
    with pytest.raises(ContractError, match=message):
        ParameterDisplay("x", label, low, high, step)


def test_changed_values_compares_to_the_default_exactly() -> None:
    controls = parameter_controls(MODEL_PARAMETER_SPECS, MODEL_PARAMETER_DISPLAYS)
    nudged = 1.0 + 1e-12
    assert changed_values(controls, {"effort": nudged}) == {"effort": nudged}
    assert changed_values(controls, {"effort": 1.0}) == {}
