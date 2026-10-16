"""Garanties des contrats du document d'admission (M4c-3, ``schemas/admission.py``) que
les tests joints ne tenaient pas — correctifs de la relecture de la PR #25 (balayage de
mutation de la conception, relecture C).

- un succès est un gain **strictement** au-dessus de ``ε`` (décision E2) ;
- l'invariant de classification de ``PerformanceAssessment`` vérifie la durée projetée
  même sans D+/km ;
- les ordres prescrits (§ 6.1, « dans l'ordre ») : une entrée qui viole deux contrôles
  voisins reçoit le message du premier.
"""

from __future__ import annotations

import math
import re
from dataclasses import replace

import pytest

from mountain_perf.schemas import ExperimentMetric, Unavailability
from mountain_perf.schemas.admission import (
    NUMERIC_TOLERANCE,
    AdmissionVerdict,
    NonEvaluable,
    ReviewCause,
    ReviewReason,
    ThresholdSource,
    _check_source,
)
from mountain_perf.validation import ContractError
from test_schemas_admission import (
    FIXED_SOURCE,
    G1,
    P1,
    P2,
    R1,
    VOTE_FAILS,
    _admission,
    _performance,
    _raises,
)


def test_a_gain_of_exactly_epsilon_is_not_a_success() -> None:
    """Décision E2, précision de D10.3 : « un succès est un ``G_j > ε`` » — un gain
    égal à ``ε`` exactement ne compte pas au vote."""
    exact = _performance(
        P1.civil_date.replace(day=16), NUMERIC_TOLERANCE, 0.0, 0.0625, **FIXED_SOURCE
    )
    assert exact.gain == NUMERIC_TOLERANCE
    admission = _admission(
        performances=(P1, P2, exact),
        mean_gain=math.fsum((G1, NUMERIC_TOLERANCE)) / 2,
        positive=1,
        mean_raw_gain=math.fsum((R1, 0.0625)) / 2,
        failures=(VOTE_FAILS,),
        verdict=AdmissionVerdict.REJECTED,
    )
    assert admission.positive == 1
    _raises(
        admission,
        "mean_threshold, mean_gain, positive, mean_raw_gain et raw_gains valent",
        positive=2,
        failures=(),
        verdict=AdmissionVerdict.PROVISIONAL,
    )


def test_projected_duration_is_checked_without_dplus() -> None:
    """``PerformanceAssessment``, invariant de classification : ``projected_s`` fini et
    ``>= 0`` même quand ``dplus_per_km`` est absent."""
    with pytest.raises(ContractError, match=re.escape("projected_s doit être >= 0")):
        replace(P1, comparable=None, dplus_per_km=None, projected_s=-1.0)


# ---------------------------------------------------------------------------
# Les ordres prescrits (§ 6.1)
# ---------------------------------------------------------------------------


def test_check_source_pairs_source_and_value_before_finiteness() -> None:
    """``_check_source``, dans l'ordre : la correspondance source / valeur, puis la
    valeur finie et ``>= 0``."""
    with pytest.raises(ContractError, match=re.escape("une source fixed porte")):
        _check_source(ThresholdSource.FIXED, math.inf, None)


def test_performance_invariant_2_before_invariant_4() -> None:
    """``PerformanceAssessment`` : l'invariant 2 (champs d'une non-évaluable) avant le
    4 (classification)."""
    with pytest.raises(ContractError, match=re.escape("une performance non évaluable")):
        replace(
            P2,
            source=ThresholdSource.FIXED,
            comparable_unavailability=Unavailability.MODEL_ERROR,
        )


def test_admission_invariant_2_before_invariant_3() -> None:
    """``Admission`` : l'invariant 2 (au moins une évaluable) avant le 3 (motifs)."""
    zero_time = replace(P2, motif=NonEvaluable.ZERO_TIME, dplus_per_km=None)
    with pytest.raises(
        ContractError, match=re.escape("une admission a au moins une performance")
    ):
        _admission(target=ExperimentMetric.USAGE, performances=(zero_time,))


def test_admission_review_before_failures() -> None:
    """``Admission`` : l'invariant 6 (``review``) avant le 7 (``failures``)."""
    wrong = ReviewReason(ReviewCause.PASSAGES_NOT_APPLICABLE, None, ())
    with pytest.raises(ContractError, match=re.escape("review vaut")):
        _admission(review=(wrong,), failures=(VOTE_FAILS,))
