"""Les garanties écrites des contrats du calage que le test 8 ne tenait pas (§ 6.2 et
§ 8.1, test 8, du brief M4c-1 ; décision 15 ; précision 4 de la session ; relectures de
la PR #21 et balayage de la conception) :

- l'ordre des contrôles de ``ModelCalibration`` (« dans l'ordre des listes »), lu au
  message d'un objet qui viole deux invariants voisins ;
- la tolérance ``τ`` : relative à ``max(1, |x|)`` au-dessus de 1, de largeur
  ``1e−12`` ; une saturation exactement à une borne, au bit ;
- ``POPULATION_EXCLUSION_DESCRIPTIONS`` en lecture seule (``MappingProxyType``).
"""

import math
from datetime import date

import pytest

from mountain_perf.schemas import (
    CLOCKS,
    POPULATION_EXCLUSION_DESCRIPTIONS,
    ContractError,
    ModelCalibration,
    ModelKind,
    PopulationExclusionReason,
    Scenario,
)

D1 = date(2026, 6, 1)
V0 = ModelKind.V0_RECALIBRATED


def _calibration(
    model: ModelKind,
    beta: float,
    effort: float | None,
    factor: float,
    saturated: bool,
) -> ModelCalibration:
    return ModelCalibration(
        model,
        Scenario.CONTROL,
        CLOCKS[0],
        (D1,),
        (),
        beta,
        effort,
        factor,
        saturated,
        None,
    )


def _v0(beta: float, effort: float, saturated: bool) -> ModelCalibration:
    return _calibration(V0, beta, effort, 1.0 / effort, saturated)


# ---------------------------------------------------------------------------
# L'ordre des contrôles (§ 6.2, invariant 5)
# ---------------------------------------------------------------------------


def test_the_domain_of_exp_is_checked_before_the_sign_of_the_factor() -> None:
    """Précision 4 : ``β = 710`` et un facteur ``−1`` — le domaine d'``exp`` d'abord."""
    with pytest.raises(ContractError, match="beta hors du domaine d'exp"):
        _calibration(ModelKind.TOBLER, 710.0, None, -1.0, False)


def test_the_bounds_of_the_effort_are_checked_before_the_factor() -> None:
    """§ 6.2 : effort ``0,4`` hors bornes **et** facteur ``2`` (≠ ``1 / 0,4``) — les
    bornes d'abord."""
    with pytest.raises(ContractError, match="effort doit être dans"):
        _calibration(V0, 1.0, 0.4, 2.0, True)


def test_a_saturation_off_a_bound_is_checked_before_the_relation_to_beta() -> None:
    """§ 6.2 : à ``β = 0,2``, un effort ``0,7`` saturé — « une saturation met l'effort à
    une borne » avant « effort doit valoir »."""
    with pytest.raises(ContractError, match="une saturation met l'effort à une borne"):
        _v0(0.2, 0.7, True)


# ---------------------------------------------------------------------------
# La tolérance τ (décision 15)
# ---------------------------------------------------------------------------


def test_the_tolerance_is_relative_for_a_large_factor() -> None:
    """Décision 15 : relative à ``max(1, |x|)`` — à ``β = 2``, un facteur
    ``exp(2) + 3e−12`` (au-delà de ``τ``, en deçà de ``τ · exp(2)``) est accepté ;
    ``exp(2) + 2e−11`` est refusé."""
    accepted = math.exp(2.0) + 3e-12
    assert _calibration(ModelKind.TOBLER, 2.0, None, accepted, False).factor == accepted
    with pytest.raises(ContractError, match="exp\\(beta\\)"):
        _calibration(ModelKind.TOBLER, 2.0, None, math.exp(2.0) + 2e-11, False)


def test_the_tolerance_is_relative_near_the_upper_bound() -> None:
    """Décision 15 : ``exp(−β) = 1,5 + 1,2e−12`` est égal à la borne haute à
    ``τ · 1,5`` près — la saturation y est indifférente."""
    beta = -math.log(1.5 + 1.2e-12)
    _v0(beta, 1.5, False)
    _v0(beta, 1.5, True)


def test_the_tolerance_is_one_e_minus_twelve() -> None:
    """Décision 15 : ``exp(−β) = 0,5 − 1,5e−12`` est hors de ``τ`` — l'effort borné à
    ``0,5`` doit être déclaré saturé."""
    beta = -math.log(0.5 - 1.5e-12)
    _v0(beta, 0.5, True)
    with pytest.raises(ContractError, match="saturated vaut vrai"):
        _v0(beta, 0.5, False)


def test_a_saturated_effort_is_exactly_at_a_bound() -> None:
    """Décision 15 : « une saturation à une borne », au bit — un effort saturé d'un ulp
    au-dessus de ``0,5`` est refusé."""
    with pytest.raises(ContractError, match="une saturation met l'effort à une borne"):
        _v0(1.0, math.nextafter(0.5, 1.0), True)


# ---------------------------------------------------------------------------
# Les descriptions (§ 6.2)
# ---------------------------------------------------------------------------


def test_exclusion_descriptions_are_read_only() -> None:
    """§ 6.2 : ``POPULATION_EXCLUSION_DESCRIPTIONS`` est un ``MappingProxyType``."""
    with pytest.raises(TypeError):
        POPULATION_EXCLUSION_DESCRIPTIONS[PopulationExclusionReason.RACE] = "x"  # type: ignore[index]
