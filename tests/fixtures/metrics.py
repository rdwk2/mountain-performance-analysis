"""Fixtures synthétiques des métriques (M4b-1) — valeurs du § 7 du brief M4b-1.

- :class:`SupportCase` et :data:`SUPPORT_CASES` : les quatorze entrées du § 7.1,
  recopiées telles quelles (``p``, ``t``, classes) ;
- :func:`bits` : une représentation « au bit » d'un résultat, chaque flottant par
  ``float.hex`` (distingue ``0.0`` de ``-0.0``) ;
- :func:`raises_value_error` : une précondition lève un ``ValueError`` **simple**, pas
  un ``ContractError`` (qui en hérite) : une entrée d'observation fausse est une
  erreur d'appel, jamais un statut, et jamais un contrat refusé (choix 10 du brief).

Utilisées par les ``tests/test_backtest_metrics_*.py`` et par
:func:`strategies.support_cases`.
"""

import dataclasses
import math
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass

import pytest

from mountain_perf.schemas import RegimeClass

A, F, D, X = (
    RegimeClass.ASCENT,
    RegimeClass.FLAT,
    RegimeClass.DESCENT,
    RegimeClass.MIXED,
)
NAN = math.nan


@dataclass(frozen=True)
class SupportCase:
    """Les entrées de ``support_metrics`` ; ``features`` : étiquettes de la stratégie
    :func:`strategies.support_cases` (vide pour les fixtures du § 7.1)."""

    projected_s: tuple[float | None, ...]
    observed_s: tuple[float, ...]
    classes: tuple[RegimeClass, ...]
    features: frozenset[str] = frozenset()


SUPPORT_CASES: dict[str, SupportCase] = {
    "T12": SupportCase((200.0, 50.0, 100.0), (100.0, 100.0, 100.0), (A, A, X)),
    "Dyadique": SupportCase(
        (300.0, 150.0, 50.0, 25.0, 100.0),
        (75.0, 150.0, 100.0, 200.0, 100.0),
        (A, A, D, D, F),
    ),
    "Quatre classes": SupportCase(
        (150.0, 90.0, 160.0, 55.0, 85.0, 90.0, 100.0, 60.0, 50.0, 40.0),
        (120.0, 95.0, 130.0, 60.0, 80.0, 110.0, 140.0, 70.0, 45.0, 60.0),
        (A, A, A, F, F, D, D, D, X, X),
    ),
    "Une classe": SupportCase(
        (100 * math.exp(0.2), 100 * math.exp(-0.2)), (100.0, 100.0), (A, A)
    ),
    "T11 D": SupportCase((100.0, 100.0), (100.0, 200.0), (D, D)),
    "Un segment": SupportCase((90.0,), (100.0,), (D,)),
    "Temps nul": SupportCase((100.0, 100.0), (0.0, 100.0), (A, D)),
    "Tout nul": SupportCase((100.0, 100.0), (0.0, 0.0), (A, A)),
    "Tout nul, erreur": SupportCase((NAN, 100.0), (0.0, 0.0), (A, A)),
    "T22": SupportCase((100.0, 100.0, NAN), (100.0, 100.0, 100.0), (A, A, A)),
    "Manquante": SupportCase((100.0, None, 100.0), (100.0, 100.0, 100.0), (A, D, D)),
    "Temps nul et erreur": SupportCase(
        (100.0, NAN, 100.0), (0.0, 100.0, 100.0), (A, D, D)
    ),
    "Erreur sur le nul": SupportCase(
        (NAN, 100.0, 100.0), (0.0, 100.0, 100.0), (A, D, D)
    ),
    "Vide": SupportCase((), (), ()),
}
"""Les entrées du § 7.1 du brief M4b-1, par nom de fixture."""


def bits(obj: object) -> object:
    """``obj`` avec chaque flottant remplacé par ``float.hex``, récursivement dans les
    tuples et les dataclasses : deux résultats égaux par :func:`bits` sont égaux au
    bit."""
    if isinstance(obj, float):
        return obj.hex()
    if isinstance(obj, tuple):
        return tuple(bits(item) for item in obj)
    if dataclasses.is_dataclass(obj) and not isinstance(obj, type):
        return (
            type(obj).__name__,
            tuple(bits(getattr(obj, f.name)) for f in dataclasses.fields(obj)),
        )
    return obj


@contextmanager
def raises_value_error(match: str) -> Iterator[None]:
    """``pytest.raises(ValueError, match=match)``, et le type exact ``ValueError``."""
    with pytest.raises(ValueError, match=match) as info:
        yield
    assert type(info.value) is ValueError
