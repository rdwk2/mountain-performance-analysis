"""Fixtures synthétiques des métriques (M4b-1) — valeurs du § 7 du brief M4b-1.

- :func:`raises_value_error` : une précondition lève un ``ValueError`` **simple**, pas
  un ``ContractError`` (qui en hérite) : une entrée d'observation fausse est une
  erreur d'appel, jamais un statut, et jamais un contrat refusé (choix 10 du brief).

Utilisées par les ``tests/test_backtest_metrics_*.py``.
"""

from collections.abc import Iterator
from contextlib import contextmanager

import pytest


@contextmanager
def raises_value_error(match: str) -> Iterator[None]:
    """``pytest.raises(ValueError, match=match)``, et le type exact ``ValueError``."""
    with pytest.raises(ValueError, match=match) as info:
        yield
    assert type(info.value) is ValueError
