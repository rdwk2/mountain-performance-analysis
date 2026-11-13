"""Les communs du paquet d'inférence (AN3-1, ``docs/decisions/0021``) : l'erreur,
l'intervalle, le quantile par statistique d'ordre, l'intervalle percentile, les
générateurs dérivés d'une graine, et les contrôles d'entrée partagés."""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy
import numpy.typing

type FloatArray = numpy.typing.NDArray[numpy.float64]
"""Un tableau de flottants 64 bits."""

RANK_TOLERANCE = 1e-10
"""Seuil relatif de rang d'une matrice de plan, sur la diagonale de ``R`` (QR)."""


class InferenceError(ValueError):
    """L'erreur de tout le paquet : une entrée refusée, un calcul impossible."""


@dataclass(frozen=True)
class Interval:
    """Un intervalle fermé ``[low ; high]``, aux bornes finies."""

    low: float
    high: float

    def __post_init__(self) -> None:
        if not (math.isfinite(self.low) and math.isfinite(self.high)):
            raise InferenceError(
                f"Interval : bornes non finies ({self.low}, {self.high})"
            )
        if self.low > self.high:
            raise InferenceError(f"Interval : low > high ({self.low} > {self.high})")


def as_vector(values: object, name: str, min_size: int = 1) -> FloatArray:
    """``values`` en vecteur neuf de flottants, fini, d'au moins ``min_size``
    éléments ; sinon ``InferenceError`` nommant ``name``."""
    array = numpy.array(values, dtype=numpy.float64)
    if array.ndim != 1:
        raise InferenceError(f"{name} : un vecteur est attendu")
    if array.shape[0] < min_size:
        raise InferenceError(f"{name} : au moins {min_size} valeurs attendues")
    if not numpy.all(numpy.isfinite(array)):
        raise InferenceError(f"{name} : valeurs non finies")
    return array


def as_matrix(values: object, name: str) -> FloatArray:
    """``values`` en matrice neuve de flottants, finie, non vide ; sinon
    ``InferenceError`` nommant ``name``."""
    array = numpy.array(values, dtype=numpy.float64)
    if array.ndim != 2 or array.shape[0] == 0 or array.shape[1] == 0:
        raise InferenceError(f"{name} : une matrice non vide est attendue")
    if not numpy.all(numpy.isfinite(array)):
        raise InferenceError(f"{name} : valeurs non finies")
    return array


def check_design(X: FloatArray, name: str = "X") -> None:  # noqa: N803
    """Refuse une matrice de plan ``n × p`` avec ``n ≤ p``, ou qui n'est pas de plein
    rang (``min |R_ii| ≤ 1e−10 · max |R_ii|`` dans sa QR)."""
    n, p = X.shape
    if n <= p:
        raise InferenceError(f"{name} : n ≤ p ({n} ≤ {p})")
    diagonal = numpy.abs(numpy.diag(numpy.linalg.qr(X, mode="r")))
    if float(diagonal.min()) <= RANK_TOLERANCE * float(diagonal.max()):
        raise InferenceError(f"{name} n'est pas de plein rang")


def frozen(array: FloatArray) -> FloatArray:
    """``array``, rendu non modifiable (pour les tableaux d'une dataclass)."""
    array.setflags(write=False)
    return array


def check_level(level: float, name: str = "level") -> None:
    """Refuse un niveau hors de ``]0 ; 1[``."""
    if not 0.0 < level < 1.0:
        raise InferenceError(f"{name} : hors de ]0 ; 1[ ({level})")


def order_quantile(values: object, q: float) -> float:
    """La statistique d'ordre ``x₍k₎``, ``k = ⌈q·B − 1e−9⌉`` (1-indexé, au moins 1),
    des ``B`` valeurs triées ; ``0 < q ≤ 1``. Sans interpolation."""
    if not 0.0 < q <= 1.0:
        raise InferenceError(f"q : hors de ]0 ; 1] ({q})")
    ordered = numpy.sort(as_vector(values, "values"))
    count = ordered.shape[0]
    k = max(math.ceil(q * count - 1e-9), 1)
    return float(ordered[k - 1])


def percentile_interval(draws: object, level: float) -> Interval:
    """L'intervalle percentile de niveau ``level`` : les statistiques d'ordre de
    ``(1 − level)/2`` et ``(1 + level)/2``."""
    check_level(level)
    return Interval(
        order_quantile(draws, (1.0 - level) / 2.0),
        order_quantile(draws, (1.0 + level) / 2.0),
    )


def child_rng(root_seed: int, *key: int) -> numpy.random.Generator:
    """Le générateur de la clé ``key`` sous la graine ``root_seed`` :
    ``SeedSequence(root_seed, spawn_key=key)``. Deux appels de mêmes arguments tirent
    la même suite ; c'est la seule façon dont le paquet crée un générateur."""
    _check_seed_part(root_seed, "root_seed")
    for part in key:
        _check_seed_part(part, "key")
    return numpy.random.default_rng(
        numpy.random.SeedSequence(root_seed, spawn_key=tuple(key))
    )


def _check_seed_part(value: int, name: str) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise InferenceError(f"{name} : un entier ≥ 0 est attendu ({value!r})")
