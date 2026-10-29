"""Les quatre champs de M6b de ``CurveProvenance`` (``schemas/curve.py``) : l'athlète,
la durée maximale, le plafond et le décalage de la FC, absents par défaut, et leurs
invariants (``docs/decisions/0017``)."""

from __future__ import annotations

import dataclasses
import math
from typing import Any

import pytest

from fixtures.performance import MANUAL_PROVENANCE
from mountain_perf.validation import ContractError

FILTERED = dataclasses.replace(
    MANUAL_PROVENANCE, hr_center_bpm=150.0, hr_width_bpm=10.0
)
"""La provenance manuelle avec un filtre de FC : le décalage y est permis."""


def test_a_curve_from_before_m6b_has_none_of_the_four_fields() -> None:
    """Une provenance d'avant M6b ne dit ni athlète, ni durée maximale, ni plafond,
    ni décalage."""
    assert MANUAL_PROVENANCE.athlete_ref is None
    assert MANUAL_PROVENANCE.max_duration_s is None
    assert MANUAL_PROVENANCE.max_elapsed_s is None
    assert MANUAL_PROVENANCE.hr_lag_s is None


def test_a_complete_provenance_is_built() -> None:
    """Les quatre champs présents et cohérents, avec un filtre de FC ; une durée
    maximale juste au-dessus de la minimale ; un décalage nul."""
    provenance = dataclasses.replace(
        FILTERED,
        athlete_ref="x",
        min_duration_s=1800.0,
        max_duration_s=1800.5,
        max_elapsed_s=7200.0,
        hr_lag_s=0.0,
    )
    assert provenance.athlete_ref == "x"
    assert provenance.max_duration_s == 1800.5
    assert provenance.max_elapsed_s == 7200.0
    assert provenance.hr_lag_s == 0.0


@pytest.mark.parametrize(
    ("changes", "field"),
    [
        ({"athlete_ref": ""}, "athlete_ref"),
        ({"athlete_ref": "   "}, "athlete_ref"),
        ({"max_duration_s": 0.0}, "max_duration_s"),
        ({"max_duration_s": math.inf}, "max_duration_s"),
        ({"max_elapsed_s": -1.0}, "max_elapsed_s"),
        ({"max_elapsed_s": math.nan}, "max_elapsed_s"),
        ({"min_duration_s": 600.0, "max_duration_s": 600.0}, "max_duration_s"),
        ({"hr_lag_s": -0.5}, "hr_lag_s"),
        ({"hr_lag_s": math.inf}, "hr_lag_s"),
    ],
)
def test_each_invariant_names_its_field(changes: dict[str, Any], field: str) -> None:
    """Sur une provenance filtrée (seule la plage du décalage est en cause), chaque
    invariant violé lève une ``ContractError`` qui nomme son champ."""
    with pytest.raises(ContractError, match=field):
        dataclasses.replace(FILTERED, **changes)


def test_a_lag_without_a_heart_rate_filter_is_refused() -> None:
    """Un décalage de FC n'a de sens qu'avec un filtre (``hr_center_bpm``)."""
    with pytest.raises(ContractError, match="hr_lag_s"):
        dataclasses.replace(MANUAL_PROVENANCE, hr_lag_s=60.0)
