"""Garantie des contrats de la sensibilité (M4d-3, ``schemas/sensitivity.py``) que les
tests joints ne tenaient pas — correctif de la relecture de la PR #32 (relecture C,
passe 2).

Les moyennes de l'ensemble commun sont des ``math.fsum`` (précision de D13, amendement
D13-B). Le témoin des tests joints, ``1e8, 1e−8, −1e8``, ne sépare ``fsum`` que d'une
accumulation naïve : depuis Python 3.12, ``sum`` compense lui aussi (Neumaier) et rend
le même résultat. Ce témoin-ci les sépare d'un ulp.
"""

import math
from datetime import date

from mountain_perf.schemas import GainComparison
from mountain_perf.schemas.sensitivity import common_set, sign_class

WITNESS = (-1.2421729912250528e17, 1.8869979727329407e-19, -9.609134221238846e16)
"""Trois gains dont ``fsum`` et ``sum`` diffèrent d'un ulp."""


def test_common_set_means_use_fsum_not_sum() -> None:
    """Précision de D13 : les deux moyennes de l'ensemble commun sont des ``fsum`` sur
    ses jours, divisées par leur nombre — pas des ``sum``, que ce témoin sépare."""
    assert math.fsum(WITNESS) != sum(WITNESS)
    gains = tuple(
        GainComparison(
            date(2026, 6, day),
            value,
            None,
            value,
            None,
            sign_class(value),
            sign_class(value),
        )
        for day, value in zip((3, 4, 5), WITNESS, strict=True)
    )
    common = common_set(gains)
    assert common.days == tuple(g.civil_date for g in gains)
    assert common.comparator_mean == math.fsum(WITNESS) / 3
    assert common.mean == math.fsum(WITNESS) / 3
    assert common.mean != sum(WITNESS) / 3
