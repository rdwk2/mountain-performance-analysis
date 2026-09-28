"""Enveloppes de ``L`` (§ 6.6, § 7.4 et § 8.1, test 6, du brief M4b-1).

``0010`` D5.4 : pour un total projeté ``P`` et un temps admissible dans ``[a ; b]``,
``L ∈ [ln(P/b) ; ln(P/a)]``, ``min |L| = 0`` si l'intervalle contient zéro ;
``a = 0 < P`` donne une borne supérieure ``+∞`` et le statut ``temps nul``. Chaque
ligne du § 7.4, chaque champ ; valeurs à ``1e−9`` en absolu.
"""

import math

import pytest

from fixtures.metrics import raises_value_error
from mountain_perf.backtest import log_ratio_envelope
from mountain_perf.schemas import Unavailability

ZERO = Unavailability.ZERO_TIME
ERR = Unavailability.MODEL_ERROR

VALUED = [
    ((100.0, 80.0, 120.0), -0.182321556794, 0.223143551314, 0.0, None),
    ((100.0, 120.0, 200.0), -0.693147180560, -0.182321556794, 0.182321556794, None),
    ((100.0, 50.0, 80.0), 0.223143551314, 0.693147180560, 0.223143551314, None),
    ((100.0, 0.0, 200.0), -0.693147180560, math.inf, 0.0, ZERO),
    ((200.0, 0.0, 100.0), 0.693147180560, math.inf, 0.693147180560, ZERO),
    ((100.0, 100.0, 100.0), 0.0, 0.0, 0.0, None),
]
"""Les lignes à valeurs du § 7.4 : ``(P, a, b)``, ``lower``, ``upper``, ``min_abs``,
motif."""


@pytest.mark.parametrize(
    ("arguments", "lower", "upper", "min_abs", "motif"),
    VALUED,
    ids=[str(row[0]) for row in VALUED],
)
def test_envelope_values(
    arguments: tuple[float, float, float],
    lower: float,
    upper: float,
    min_abs: float,
    motif: Unavailability | None,
) -> None:
    """§ 7.4, T11 et X08 compris ; ``a = 0 < b`` : ``upper = +inf``, ``zero_time``,
    ``lower`` et ``min |L|`` publiés (D5.4, choix 6 du brief)."""
    envelope = log_ratio_envelope(*arguments)
    assert envelope.lower == pytest.approx(lower, abs=1e-9)
    if math.isinf(upper):
        assert envelope.upper == math.inf
    else:
        assert envelope.upper == pytest.approx(upper, abs=1e-9)
    assert envelope.min_abs == pytest.approx(min_abs, abs=1e-9)
    assert envelope.unavailability is motif


UNVALUED = [
    ((100.0, 0.0, 0.0), ZERO),
    ((math.nan, 80.0, 120.0), ERR),
    ((0.0, 80.0, 120.0), ERR),
    ((None, 80.0, 120.0), ERR),
    ((math.nan, 0.0, 0.0), ZERO),
    ((math.nan, 0.0, 100.0), ERR),
]
"""Les lignes sans valeur du § 7.4 ; ``(nan, 0, 0)`` : l'observation d'abord."""


@pytest.mark.parametrize(
    ("arguments", "motif"), UNVALUED, ids=[str(row[0]) for row in UNVALUED]
)
def test_envelope_without_values(
    arguments: tuple[float | None, float, float], motif: Unavailability
) -> None:
    """§ 7.4 et choix 6 du brief : ``b = 0`` → ``zero_time`` avant tout ; sinon une
    projection invalide → ``model_error`` ; rien de calculable."""
    envelope = log_ratio_envelope(*arguments)
    assert (envelope.lower, envelope.upper, envelope.min_abs) == (None, None, None)
    assert envelope.unavailability is motif


@pytest.mark.parametrize(
    ("arguments", "match"),
    [
        ((100.0, 120.0, 80.0), r"low_s \(120.0\) doit être <= high_s \(80.0\)"),
        ((100.0, -1.0, 80.0), "low_s doit être fini et >= 0"),
        ((100.0, 80.0, math.inf), "high_s doit être fini et >= 0"),
        ((100.0, math.nan, 80.0), "low_s doit être fini et >= 0"),
    ],
    ids=["a>b", "a<0", "b=inf", "a=nan"],
)
def test_envelope_preconditions(
    arguments: tuple[float, float, float], match: str
) -> None:
    """§ 6.6 : des bornes d'observation fausses sont une erreur d'appel (choix 10)."""
    with raises_value_error(f"log_ratio_envelope : {match}"):
        log_ratio_envelope(*arguments)
