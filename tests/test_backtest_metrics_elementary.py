"""Seuil, prédicats et fonctions pures élémentaires (§ 6.2, § 6.3, § 7.3 et § 8.1,
tests 2 et 3, du brief M4b-1).

``0010`` D7.1 (sortie de modèle invalide), D7.2 (``r_i``, ``A``, ``D_R``, ``C_comp``),
D7.5 (« trop peu représenté »). Les valeurs sont celles du § 7.3 ; les égalités
``==`` y sont testées par ``==``.
"""

import math

import pytest

from fixtures.metrics import raises_value_error
from mountain_perf.backtest import (
    UNDERREPRESENTED_BELOW,
    compensation,
    is_invalid_model_output,
    is_underrepresented,
    log_ratio,
    time_weighted_deviation,
)

# ---------------------------------------------------------------------------
# Prédicats (§ 6.2)
# ---------------------------------------------------------------------------


def test_underrepresented_threshold_of_the_brief() -> None:
    """``0010`` D7.5 : « un régime de moins de 3 segments »."""
    assert UNDERREPRESENTED_BELOW == 3


@pytest.mark.parametrize(
    ("count", "expected"),
    [(0, False), (1, True), (2, True), (3, False), (4, False)],
)
def test_is_underrepresented_at_its_bounds(count: int, expected: bool) -> None:
    """D7.5, choix 2 de rdw : vrai pour 1 et 2 ; 0 est « non évalué », 3 ne l'est
    plus."""
    assert is_underrepresented(count) is expected


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (None, True),
        (math.nan, True),
        (math.inf, True),
        (-math.inf, True),
        (0.0, True),
        (-0.0, True),
        (-5.0, True),
        (5e-324, False),
        (1.0, False),
    ],
    ids=["None", "nan", "inf", "-inf", "0.0", "-0.0", "-5.0", "5e-324", "1.0"],
)
def test_is_invalid_model_output(value: float | None, expected: bool) -> None:
    """D7.1, choix 2 du brief : ``p <= 0``, non finie ou manquante ; ``−0.0``
    compris ; le plus petit flottant positif est valide."""
    assert is_invalid_model_output(value) is expected


# ---------------------------------------------------------------------------
# log_ratio (§ 6.3)
# ---------------------------------------------------------------------------


def test_log_ratio_is_log_of_the_quotient() -> None:
    """Choix 1 du brief : ``math.log(p / t)``, au bit."""
    assert log_ratio(200.0, 100.0) == math.log(2.0)


@pytest.mark.parametrize(
    ("projected_s", "observed_s", "name"),
    [
        (0.0, 1.0, "projected_s"),
        (1.0, 0.0, "observed_s"),
        (-1.0, 1.0, "projected_s"),
        (math.nan, 1.0, "projected_s"),
        (1.0, math.inf, "observed_s"),
    ],
)
def test_log_ratio_needs_two_finite_positive_values(
    projected_s: float, observed_s: float, name: str
) -> None:
    with raises_value_error(f"log_ratio : {name} doit être fini et > 0"):
        log_ratio(projected_s, observed_s)


# ---------------------------------------------------------------------------
# time_weighted_deviation (§ 6.3)
# ---------------------------------------------------------------------------


def test_time_weighted_deviation_value() -> None:
    """D7.2 : ``fsum(t · |r − c|) / fsum(t) = (1·1 + 2·1.5 + 1·1) / 4``."""
    value = time_weighted_deviation((1.0, -1.0, 2.0), (0.0, 0.5, 1.0), (1.0, 2.0, 1.0))
    assert value == pytest.approx(1.25, abs=1e-9)


def test_time_weighted_deviation_is_exactly_zero_on_its_center() -> None:
    """D7.2 : un seul segment → ``D_R = 0`` exactement."""
    assert time_weighted_deviation((0.3,), (0.3,), (5.0,)) == 0.0


@pytest.mark.parametrize(
    ("ratios", "centers", "observed_s", "match"),
    [
        ((1.0, 2.0), (0.0,), (1.0, 1.0), "longueurs différentes"),
        ((1.0,), (0.0,), (1.0, 1.0), "longueurs différentes"),
        ((), (), (), "séquences vides"),
        ((1.0,), (0.0,), (0.0,), "temps total nul"),
        ((1.0,), (0.0,), (-1.0,), r"observed_s\[0\] doit être fini et >= 0"),
        ((1.0,), (0.0,), (math.inf,), r"observed_s\[0\] doit être fini et >= 0"),
    ],
    ids=["centers", "times", "empty", "zero-total", "negative", "infinite"],
)
@pytest.mark.parametrize("function", ["time_weighted_deviation", "compensation"])
def test_weighted_preconditions(
    function: str,
    ratios: tuple[float, ...],
    centers: tuple[float, ...],
    observed_s: tuple[float, ...],
    match: str,
) -> None:
    """§ 6.3 : mêmes longueurs, non vides, temps finis et ``>= 0``, total ``> 0`` —
    pour les deux fonctions."""
    with raises_value_error(f"{function} : {match}"):
        if function == "compensation":
            compensation(ratios, centers, 0.0, observed_s)
        else:
            time_weighted_deviation(ratios, centers, observed_s)


# ---------------------------------------------------------------------------
# compensation (§ 6.3)
# ---------------------------------------------------------------------------


def test_compensation_value() -> None:
    """D7.2 : ``(1·((0.5 + 0.5) − 1) + 1·((0.5 + 0.5) − 0)) / 2``."""
    value = compensation((1.0, 0.0), (0.5, 0.5), 0.0, (1.0, 1.0))
    assert value == pytest.approx(0.5, abs=1e-9)


def test_compensation_with_arbitrary_centers() -> None:
    """Termes ``1·0.5 + 2·0.5 + 1·0``, divisés par 4 ; les centres ne sont pas des
    ``E_R``."""
    value = compensation((1.0, -1.0, 2.0), (0.0, 0.5, 1.0), 0.25, (1.0, 2.0, 1.0))
    assert value == pytest.approx(0.375, abs=1e-9)
