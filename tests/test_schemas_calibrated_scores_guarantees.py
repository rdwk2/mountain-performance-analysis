"""Garanties des contrats des scores calés tenues par des tests (correctifs de la PR
#23, M4c-2 ; relecture C et balayage de mutation de la conception).

- ``CalibratedPerformance``, invariant 3 (brief M4c-2, § 6.2 ; D7.1) : **chacun** des
  quatre modèles d'un groupe porte la même observation — une observation différente
  portée par le deuxième est refusée, comme par le premier.
- **Les contrôles se font dans l'ordre des listes** (§ 6.2) : l'invariant 3 de
  ``CalibratedPerformance`` après « un groupe porte une seule sortie » et avant « deux
  groupes » ; ``_check_supports`` avant ``_check_passages`` dans
  ``CalibratedScenarioScores``.

Le calage du 16 juin du monde de M4c-1 et les scores calés à ``β = 0`` viennent des
aides de ``test_schemas_calibration_hardening.py`` (test 2 du brief), recalculés à
chaque appel.
"""

import re
from dataclasses import replace

import pytest

from mountain_perf.schemas import CLOCKS, CalibratedOutingScores, CalibratedPerformance
from mountain_perf.validation import ContractError
from test_schemas_calibration_hardening import _calibrated, _june_16
from test_schemas_scoring import USAGE, _scenario


def _other_observation(
    performance: CalibratedPerformance, index: int
) -> tuple[CalibratedOutingScores, ...]:
    """Les entrées du premier groupe, celle d'``index`` portant une autre observation
    (une longueur de référence plus grande d'un mètre)."""
    group = list(performance.outings[:4])
    entry = group[index]
    changed = replace(
        entry.observation,
        reference_length_m=entry.observation.reference_length_m + 1.0,
    )
    group[index] = replace(entry, observation=changed)
    return tuple(group)


def test_the_second_model_of_a_group_carries_the_same_observation() -> None:
    """Invariant 3, D7.1 : le deuxième modèle d'un groupe (vitesse constante, dans
    l'ordre de ``CALIBRATED_MODELS``) porte la même observation que le premier."""
    performance = _june_16()
    with pytest.raises(
        ContractError,
        match=re.escape(
            "les quatre modèles de la sortie j1-0616 portent la même observation "
            "(D7.1)."
        ),
    ):
        CalibratedPerformance(
            performance.population, _other_observation(performance, 1)
        )


def test_one_outing_per_group_before_the_same_observation() -> None:
    """§ 6.2 : « un groupe porte une seule sortie » avant l'invariant 3 — le deuxième
    modèle porte une autre sortie **et** une autre observation."""
    performance = _june_16()
    group = list(_other_observation(performance, 1))
    group[1] = replace(group[1], outing_id="autre")
    with pytest.raises(
        ContractError, match=re.escape("un groupe porte une seule sortie, reçu ")
    ):
        CalibratedPerformance(performance.population, tuple(group))


def test_same_observation_before_two_groups() -> None:
    """§ 6.2 : l'invariant 3 avant « deux groupes » — le groupe de la sortie répété, le
    second avec une autre observation pour son deuxième modèle."""
    performance = _june_16()
    group = performance.outings[:4]
    with pytest.raises(
        ContractError, match=re.escape("portent la même observation (D7.1).")
    ):
        CalibratedPerformance(
            performance.population, (*group, *_other_observation(performance, 1))
        )


def test_supports_before_passages() -> None:
    """§ 6.2 : ``_check_supports`` avant ``_check_passages`` — en usage, une prévision
    à deux segments (supports) et à un cumulé de plus (passages)."""
    scores = _calibrated(_scenario(USAGE))
    forecast = replace(
        scores.forecast,
        segment_s=(*scores.forecast.segment_s, 100.0),
        point_s=(*scores.forecast.point_s, 1000.0),
    )
    with pytest.raises(
        ContractError,
        match=re.escape(f"support.segment_count (1) sous {CLOCKS[0]} doit valoir "),
    ):
        replace(scores, forecast=forecast)
