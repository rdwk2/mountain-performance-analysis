"""L'ajustement joint des niveaux par activité, et l'écart récent de la règle en couches
(M6b-3, ``docs/decisions/0025``) : du Python pur, sur des nombres, que la règle à
l'origine appelle.

Le modèle : le temps M d'une activité ``c`` dans une tranche ``k`` vaut
``l_ck · exp(−a_c − f_k)`` (une vitesse ``exp(a_c + f_k)``) ; un seul ajustement de
Poisson à lien logarithme, par ajustement proportionnel itératif, sur toutes les
tranches de temps M positif, sans seuil de support. Le niveau rendu est au signe du
moteur (``λ_c > 0`` : plus lent que la forme, comme ``λ_j`` de ``0017``, P4.2), défini à
une constante près, commune à toutes les activités : seules ses différences comptent.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Final

from mountain_perf.validation import (
    ContractError,
    require_finite,
    require_immutable_sequence,
    require_non_empty,
)

TOLERANCE: Final = 1e-10
"""Le critère d'arrêt : la plus grande variation ``|ln(u'_k / u_k)|`` d'un tour."""

MAX_ITERATIONS: Final = 1000
"""Le nombre maximal de tours de la boucle."""

_LAST_BIN: Final = 37
"""L'indice de la dernière des 38 tranches de pente (``0017``, P3.1)."""


@dataclass(frozen=True)
class ActivityBins:
    """Les cellules d'une activité que lit l'ajustement.

    - ``activity_ref`` — sans unité — l'activité, non vide ;
    - ``bins`` — ``(k, length_moving_m, moving_s)`` : la tranche, la longueur (m) et le
      temps M (s) des intervalles retenus de temps M positif, ``k`` entier strictement
      croissant dans ``[0 ; 37]``, longueurs et temps finis et ``> 0``.

    Contrôlé à la construction (``ContractError``).
    """

    activity_ref: str
    bins: tuple[tuple[int, float, float], ...]

    def __post_init__(self) -> None:
        require_non_empty(self.activity_ref, "activity_ref")
        require_immutable_sequence(self.bins, "bins")
        if not self.bins:
            raise ContractError(f"bins de {self.activity_ref} : au moins une cellule.")
        previous = -1
        for k, length_m, moving_s in self.bins:
            if isinstance(k, bool) or not isinstance(k, int) or not 0 <= k <= _LAST_BIN:
                raise ContractError(
                    f"bins de {self.activity_ref} : une tranche entière dans "
                    f"[0 ; {_LAST_BIN}] attendue, reçu {k!r}."
                )
            if k <= previous:
                raise ContractError(
                    f"bins de {self.activity_ref} : des tranches strictement "
                    "croissantes attendues."
                )
            previous = k
            for name, value in (("length_moving_m", length_m), ("moving_s", moving_s)):
                require_finite(value, name)
                if value <= 0:
                    raise ContractError(
                        f"bins de {self.activity_ref} : {name} doit être > 0, reçu "
                        f"{value}."
                    )

    @property
    def moving_s(self) -> float:
        """Le poids de l'activité : la somme de ses temps M, dans l'ordre de
        ``bins``."""
        return math.fsum(moving for _, _, moving in self.bins)


@dataclass(frozen=True)
class JointLevels:
    """Ce que rend l'ajustement joint.

    - ``levels`` — sans unité — ``λ_c``, dans l'ordre des activités reçues ;
    - ``iterations`` — sans unité — les tours de la boucle faits, de 1 à
      :data:`MAX_ITERATIONS` ;
    - ``converged`` — vrai si le critère d'arrêt a été atteint.
    """

    levels: tuple[float, ...]
    iterations: int
    converged: bool


def fit_joint_levels(rows: Sequence[ActivityBins]) -> JointLevels:
    """L'ajustement joint des niveaux de ``rows`` (``0025``), à la lettre :

    1. ``T_c`` la somme des temps M de ``c`` ; pour chaque tranche ``k`` présente,
       dans l'ordre croissant, ``t_k`` et ``l_k`` les sommes des temps et des longueurs
       des activités qui l'ont, dans l'ordre de ``rows`` ;
    2. ``u_k = t_k / l_k`` (s/m) ;
    3. au plus :data:`MAX_ITERATIONS` tours : ``e_c = T_c / Σ_k l_ck u_k``, puis
       ``u'_k = t_k / Σ_c e_c l_ck`` ; ``u`` prend ``u'`` **avant** le test d'arrêt
       ``max_k |ln(u'_k / u_k)| < TOLERANCE`` ;
    4. après la boucle, ``e_c`` recalculé avec le ``u`` final ;
    5. ``f_k = −ln u_k``, ``c₀ = Σ t_k f_k / Σ t_k``, ``λ_c = ln e_c − c₀``.

    Toute somme par ``math.fsum``. ``ContractError`` si ``rows`` est vide ou si deux
    activités ont la même référence. Des activités sans tranche commune ont des niveaux
    relatifs fixés par le départ de la boucle, non par les données."""
    if not rows:
        raise ContractError("rows : au moins une activité.")
    refs = [row.activity_ref for row in rows]
    if len(set(refs)) != len(refs):
        raise ContractError("rows : une activité donnée deux fois.")
    cells = [{k: (length, moving) for k, length, moving in row.bins} for row in rows]
    weights = [row.moving_s for row in rows]
    keys = sorted({k for row in cells for k in row})
    times = {k: math.fsum(row[k][1] for row in cells if k in row) for k in keys}
    lengths = {k: math.fsum(row[k][0] for row in cells if k in row) for k in keys}
    pace = {k: times[k] / lengths[k] for k in keys}

    def scales(current: dict[int, float]) -> list[float]:
        return [
            weight / math.fsum(length * current[k] for k, length, _ in row.bins)
            for weight, row in zip(weights, rows, strict=True)
        ]

    iterations = MAX_ITERATIONS
    converged = False
    for i in range(1, MAX_ITERATIONS + 1):
        scale = scales(pace)
        updated = {
            k: times[k]
            / math.fsum(
                e * row[k][0] for e, row in zip(scale, cells, strict=True) if k in row
            )
            for k in keys
        }
        done = max(abs(math.log(updated[k] / pace[k])) for k in keys) < TOLERANCE
        pace = updated
        if done:
            iterations = i
            converged = True
            break
    scale = scales(pace)
    shape = {k: -math.log(pace[k]) for k in keys}
    offset = math.fsum(times[k] * shape[k] for k in keys) / math.fsum(
        times[k] for k in keys
    )
    return JointLevels(
        tuple(math.log(e) - offset for e in scale), iterations, converged
    )


def level_shift(
    levels: Sequence[float], weights: Sequence[float], recent: Sequence[bool]
) -> float | None:
    """L'écart récent ``Δ = m(récentes) − m(toutes)``, ``m(S)`` la moyenne des niveaux
    de ``S`` pesée par les poids, ``Σ w λ / Σ w`` dans l'ordre (``0025``) ; ``None``
    sous deux activités ou sans récente ; ``0.0`` si toutes sont récentes.
    ``ContractError`` pour des suites de longueurs différentes ou un poids non fini ou
    ``<= 0``."""
    if not len(levels) == len(weights) == len(recent):
        raise ContractError(
            "level_shift : levels, weights et recent de même longueur attendus."
        )
    for weight in weights:
        require_finite(weight, "weights")
        if weight <= 0:
            raise ContractError(f"weights : des poids > 0 attendus, reçu {weight}.")
    if len(levels) < 2 or not any(recent):
        return None
    if all(recent):
        return 0.0

    def mean(chosen: Sequence[bool]) -> float:
        kept = [
            (w, level)
            for w, level, keep in zip(weights, levels, chosen, strict=True)
            if keep
        ]
        return math.fsum(w * level for w, level in kept) / math.fsum(w for w, _ in kept)

    return mean(recent) - mean([True] * len(levels))
