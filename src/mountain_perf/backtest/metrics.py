"""Métriques D7 : définitions, en fonctions pures sur des vecteurs (M4b-1).

``0010`` D5.4, D5.5, D7.1 à D7.5. Les entrées sont des vecteurs de nombres et de
statuts : projections ``p_i``, temps observés ``t_i``, classes de régime des segments
admis ; cumulés ``P_k``, ``T_k``, ``P^(0)_k`` et motifs d'observation aux passages. Ce
module ne lit ni trace, ni tracé, ni horloge, ni projection : M4b-2 les lui donne.

**Une seule écriture** de chaque quantité (brief M4b-1, § 3, choix 1) : ``log_ratio``
est la seule écriture de ``r_i``, ``L`` et ``E_R`` ; toute somme passe par
``math.fsum`` ; ``A`` et ``D_R`` passent par ``time_weighted_deviation`` ; ``C_comp``
passe par ``compensation``, jamais par ``W + B − A``.

**Une entrée d'observation fausse lève ``ValueError`` ; une sortie de modèle fausse
est un statut** (choix 10) : ``erreur du modèle``, jamais une exception.

Ce module n'importe aucun autre module de ``mountain_perf.backtest``.
"""

import math
from collections.abc import Sequence

UNDERREPRESENTED_BELOW = 3
"""Effectif en deçà duquel une classe est « trop peu représentée » (``0010`` D7.5) :
« un régime de moins de 3 segments sur une performance ». Une classe absente (effectif
0) n'est pas « trop peu représentée » : elle est « non évaluée » (D6)."""


# ---------------------------------------------------------------------------
# Prédicats (brief M4b-1, § 6.2)
# ---------------------------------------------------------------------------


def is_underrepresented(count: int) -> bool:
    """« Trop peu représenté » : ``1 <= count < 3`` (``0010`` D7.5, choix 2 de rdw)."""
    return 1 <= count < UNDERREPRESENTED_BELOW


def is_invalid_model_output(value: float | None) -> bool:
    """Sortie de modèle invalide : manquante, non finie ou ``<= 0``, ``−0.0`` compris
    (``0010`` D7.1, choix 2 du brief)."""
    return value is None or not math.isfinite(value) or value <= 0


# ---------------------------------------------------------------------------
# Fonctions pures élémentaires (brief M4b-1, § 6.3)
# ---------------------------------------------------------------------------


def log_ratio(projected_s: float, observed_s: float) -> float:
    """``ln(p / t)`` : la seule écriture de ``r_i``, ``L`` et ``E_R`` (``0010`` D7.2,
    choix 1 du brief).

    Précondition : deux valeurs finies ``> 0``, sinon ``ValueError``.
    """
    for name, value in (("projected_s", projected_s), ("observed_s", observed_s)):
        if not (math.isfinite(value) and value > 0):
            raise ValueError(f"log_ratio : {name} doit être fini et > 0, reçu {value}.")
    return math.log(projected_s / observed_s)


def _require_weighted(
    function: str,
    ratios: Sequence[float],
    centers: Sequence[float],
    observed_s: Sequence[float],
) -> float:
    """Préconditions communes de ``time_weighted_deviation`` et ``compensation`` ;
    renvoie ``fsum(t) > 0``."""
    if not len(ratios) == len(centers) == len(observed_s):
        raise ValueError(
            f"{function} : longueurs différentes ({len(ratios)}, {len(centers)}, "
            f"{len(observed_s)})."
        )
    if not observed_s:
        raise ValueError(f"{function} : séquences vides.")
    for i, time_s in enumerate(observed_s):
        if not (math.isfinite(time_s) and time_s >= 0):
            raise ValueError(
                f"{function} : observed_s[{i}] doit être fini et >= 0, reçu {time_s}."
            )
    total_s = math.fsum(observed_s)
    if not total_s > 0:
        raise ValueError(f"{function} : temps total nul.")
    return total_s


def time_weighted_deviation(
    ratios: Sequence[float], centers: Sequence[float], observed_s: Sequence[float]
) -> float:
    """``fsum(t_i · |r_i − c_i|) / fsum(t_i)`` : ``A`` (``c_i = L``) et ``D_R``
    (``c_i = E_R``) de ``0010`` D7.2.

    Précondition : trois séquences de même longueur, non vides, temps finis et
    ``>= 0``, ``fsum(t) > 0`` ; sinon ``ValueError``.
    """
    total_s = _require_weighted("time_weighted_deviation", ratios, centers, observed_s)
    return (
        math.fsum(
            t * abs(r - c) for r, c, t in zip(ratios, centers, observed_s, strict=True)
        )
        / total_s
    )


def compensation(
    ratios: Sequence[float],
    centers: Sequence[float],
    level: float,
    observed_s: Sequence[float],
) -> float:
    """``fsum(t_i · ((|r_i − c_i| + |c_i − level|) − |r_i − level|)) / fsum(t_i)`` :
    ``C_comp`` de ``0010`` D7.2 (``c_i = E_{R(i)}``, ``level = L``), par sa formule,
    **jamais** par ``W + B − A``.

    Mêmes préconditions que ``time_weighted_deviation``.
    """
    total_s = _require_weighted("compensation", ratios, centers, observed_s)
    return (
        math.fsum(
            t * ((abs(r - c) + abs(c - level)) - abs(r - level))
            for r, c, t in zip(ratios, centers, observed_s, strict=True)
        )
        / total_s
    )
