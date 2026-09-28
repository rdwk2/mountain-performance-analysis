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
from typing import TypeGuard

from mountain_perf.schemas import (
    ClassMetrics,
    LogRatioEnvelope,
    MetricValue,
    PositiveTimeDiagnostic,
    RegimeClass,
    SupportMetrics,
    Unavailability,
)

_INSUFFICIENT = Unavailability.INSUFFICIENT_SUPPORT
_ZERO_TIME = Unavailability.ZERO_TIME
_MODEL_ERROR = Unavailability.MODEL_ERROR

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


# ---------------------------------------------------------------------------
# Métriques du support et diagnostic (brief M4b-1, §§ 6.4, 6.5)
# ---------------------------------------------------------------------------


def _valid_output(value: float | None) -> TypeGuard[float]:
    """Sortie de modèle valide : la négation de ``is_invalid_model_output``, et rien
    d'autre ; le garde ne sert qu'au typage."""
    return not is_invalid_model_output(value)


def _model_outputs(projected_s: Sequence[float | None]) -> tuple[float, ...] | None:
    """Les sorties du modèle si aucune n'est invalide (``0010`` D7.1) ; sinon
    ``None``."""
    outputs: list[float] = []
    for value in projected_s:
        if _valid_output(value):
            outputs.append(value)
        else:
            return None
    return tuple(outputs)


def _require_support(
    function: str,
    projected_s: Sequence[float | None],
    observed_s: Sequence[float],
    classes: Sequence[RegimeClass],
) -> None:
    """Préconditions de ``support_metrics`` et ``positive_time_diagnostic`` : des
    entrées d'observation fausses sont une erreur d'appel (choix 10 du brief)."""
    if not len(projected_s) == len(observed_s) == len(classes):
        raise ValueError(
            f"{function} : longueurs différentes (projected_s={len(projected_s)}, "
            f"observed_s={len(observed_s)}, classes={len(classes)})."
        )
    for i, time_s in enumerate(observed_s):
        if not (math.isfinite(time_s) and time_s >= 0):
            raise ValueError(
                f"{function} : observed_s[{i}] doit être fini et >= 0, reçu {time_s}."
            )
    for i, regime in enumerate(classes):
        if not isinstance(regime, RegimeClass):
            raise ValueError(
                f"{function} : classes[{i}] doit être une RegimeClass, reçu {regime!r}."
            )


def _first_motif(*rules: tuple[bool, Unavailability]) -> Unavailability | None:
    """Le motif de la première règle vraie, dans l'ordre donné (choix 5 de rdw :
    l'observation avant le modèle) ; ``None`` si aucune ne s'applique."""
    for applies, motif in rules:
        if applies:
            return motif
    return None


def _unavailable_class(
    regime: RegimeClass, count: int, vector_motif: Unavailability | None
) -> ClassMetrics:
    """Une classe sans valeur : absente (``insufficient_support``, effectif 0, choix 3
    de rdw), sinon le motif vectoriel, jamais celui du support (choix 4 du brief)."""
    motif = _INSUFFICIENT if count == 0 else vector_motif
    value = MetricValue(None, motif, count)
    return ClassMetrics(regime, count, is_underrepresented(count), value, value, value)


def _computed(
    outputs: tuple[float, ...],
    observed_s: Sequence[float],
    classes: Sequence[RegimeClass],
) -> SupportMetrics:
    """Les valeurs d'un support sans motif, par les écritures du choix 1 du brief."""
    n = len(observed_s)
    total_s = math.fsum(observed_s)
    ratios = [log_ratio(p, t) for p, t in zip(outputs, observed_s, strict=True)]
    level = log_ratio(math.fsum(outputs), total_s)
    class_levels: dict[RegimeClass, float] = {}
    rows: list[tuple[float, float, float]] = []
    metrics: list[ClassMetrics] = []
    for regime in RegimeClass:
        members = [i for i, c in enumerate(classes) if c is regime]
        count = len(members)
        if not members:
            metrics.append(_unavailable_class(regime, 0, None))
            continue
        class_s = [observed_s[i] for i in members]
        class_total_s = math.fsum(class_s)
        class_level = log_ratio(math.fsum(outputs[i] for i in members), class_total_s)
        dispersion = time_weighted_deviation(
            [ratios[i] for i in members], [class_level] * count, class_s
        )
        weight = class_total_s / total_s
        class_levels[regime] = class_level
        rows.append((class_level, dispersion, weight))
        metrics.append(
            ClassMetrics(
                regime,
                count,
                is_underrepresented(count),
                MetricValue(class_level, None, count),
                MetricValue(dispersion, None, count),
                MetricValue(class_level - level, None, count),
            )
        )
    within = math.fsum(weight * dispersion for _, dispersion, weight in rows)
    between = math.fsum(
        weight * abs(class_level - level) for class_level, _, weight in rows
    )
    dispersion = time_weighted_deviation(ratios, [level] * n, observed_s)
    centers = [class_levels[regime] for regime in classes]
    return SupportMetrics(
        segment_count=n,
        model_error=False,
        log_ratio=MetricValue(level, None, n),
        dispersion=MetricValue(dispersion, None, n),
        within=MetricValue(within, None, n),
        between=MetricValue(between, None, n),
        compensation=MetricValue(
            compensation(ratios, centers, level, observed_s), None, n
        ),
        classes=tuple(metrics),
    )


def _support(
    outputs: tuple[float, ...] | None,
    observed_s: Sequence[float],
    classes: Sequence[RegimeClass],
) -> SupportMetrics:
    """Le code commun de ``support_metrics`` et ``positive_time_diagnostic``.

    ``outputs`` vaut ``None`` si une sortie du modèle est invalide sur le support
    **principal** ; le drapeau ne se lève que sur un support non vide. Motifs par la
    table du § 6.4 du brief, lue de gauche à droite.
    """
    n = len(observed_s)
    model_error = n > 0 and outputs is None
    total_s = math.fsum(observed_s)
    level_motif = _first_motif(
        (n == 0, _INSUFFICIENT),
        (total_s == 0, _ZERO_TIME),
        (model_error, _MODEL_ERROR),
    )
    vector_motif = _first_motif(
        (n == 0, _INSUFFICIENT),
        (any(t == 0 for t in observed_s), _ZERO_TIME),
        (model_error, _MODEL_ERROR),
    )
    if outputs is not None and vector_motif is None:
        return _computed(outputs, observed_s, classes)
    if outputs is not None and level_motif is None:
        level = MetricValue(log_ratio(math.fsum(outputs), total_s), None, n)
    else:
        level = MetricValue(None, level_motif, n)
    vector = MetricValue(None, vector_motif, n)
    return SupportMetrics(
        segment_count=n,
        model_error=model_error,
        log_ratio=level,
        dispersion=vector,
        within=vector,
        between=vector,
        compensation=vector,
        classes=tuple(
            _unavailable_class(regime, sum(c is regime for c in classes), vector_motif)
            for regime in RegimeClass
        ),
    )


def support_metrics(
    projected_s: Sequence[float | None],
    observed_s: Sequence[float],
    classes: Sequence[RegimeClass],
) -> SupportMetrics:
    """Les métriques d'un support (``0010`` D7.1, D7.2, D5.5, D7.5 ; brief M4b-1,
    § 6.4).

    ``projected_s`` : les sorties du modèle ``p_i`` (s), n'importe quelle valeur,
    ``None`` compris ; ``observed_s`` : les temps observés ``t_i`` (s) ;
    ``classes`` : les classes des segments admis, dans l'ordre du support.

    Motifs, dans l'ordre (choix 5 de rdw, l'observation avant le modèle) : support
    vide (``insufficient_support``, effectif 0), classe absente (idem), un temps nul
    (``zero_time`` pour ``A``, ``W``, ``B``, ``C_comp`` et les valeurs des classes
    présentes ; ``L`` seulement si ``fsum(t) == 0``), erreur du modèle. Le drapeau
    ``model_error`` est levé dès qu'une sortie est invalide sur un support non vide,
    quel que soit le motif publié (D7.1).

    Préconditions (``ValueError``) : mêmes longueurs ; temps finis et ``>= 0`` ;
    classes de type ``RegimeClass``.

    Non promis : hors du domaine du brief M4b-1 (§ 3, choix 12 : projections et temps
    observés positifs dans ``[1e−6 ; 1e12]``), une valeur finie ``> 0`` peut faire
    sous-dépasser ou déborder un quotient ou une somme et lever une exception.
    """
    _require_support("support_metrics", projected_s, observed_s, classes)
    return _support(_model_outputs(projected_s), observed_s, classes)


def positive_time_diagnostic(
    projected_s: Sequence[float | None],
    observed_s: Sequence[float],
    classes: Sequence[RegimeClass],
) -> PositiveTimeDiagnostic:
    """Le diagnostic du sous-support à temps positifs (``0010`` D5.5 ; brief M4b-1,
    § 6.5 et choix 5).

    Masque ``t_i > 0`` ; mêmes métriques que ``support_metrics``, par le même code,
    sur les segments de masque vrai. **L'erreur du modèle s'y juge sur le support
    principal** : une sortie invalide sur un segment masqué rend le diagnostic
    indisponible (``model_error``), sauf si le sous-support est vide. Sans temps nul,
    ``metrics`` égale ``support_metrics`` sur les mêmes entrées. Toujours calculable ;
    ne remplace jamais le support principal.

    Mêmes préconditions que ``support_metrics``.
    """
    _require_support("positive_time_diagnostic", projected_s, observed_s, classes)
    mask = tuple(t > 0 for t in observed_s)
    kept = [i for i, positive in enumerate(mask) if positive]
    principal = _model_outputs(projected_s)
    outputs = None if principal is None else tuple(principal[i] for i in kept)
    metrics = _support(
        outputs, [observed_s[i] for i in kept], [classes[i] for i in kept]
    )
    return PositiveTimeDiagnostic(mask, metrics)


# ---------------------------------------------------------------------------
# Enveloppes (brief M4b-1, § 6.6)
# ---------------------------------------------------------------------------


def log_ratio_envelope(
    projected_s: float | None, low_s: float, high_s: float
) -> LogRatioEnvelope:
    """L'intervalle de ``L`` quand le temps admissible parcourt ``[a ; b]``
    (``0010`` D5.4 ; brief M4b-1, § 6.6 et choix 6) : ``L ∈ [ln(P/b) ; ln(P/a)]``.

    Dans l'ordre : ``b == 0`` → ``zero_time``, rien de calculable (l'observation
    d'abord) ; sortie invalide → ``model_error``, rien de calculable ; sinon
    ``lower = log_ratio(P, b)`` ; ``a == 0 < b`` → ``upper = +inf`` et ``zero_time``,
    ``lower`` et ``min |L|`` restant publiés ; ``min |L| = 0`` si l'intervalle contient
    zéro, sinon ``min(|lower|, |upper|)``. Pour un régime, M4b-2 appelle la même
    fonction avec ``P_R``, ``a_R`` et ``b_R``.

    Préconditions (``ValueError``) : ``low_s`` et ``high_s`` finis, ``>= 0``,
    ``low_s <= high_s``.

    Non promis : hors du domaine du brief M4b-1 (§ 3, choix 12 : projection et bornes
    positives dans ``[1e−6 ; 1e12]``), une valeur finie ``> 0`` peut faire
    sous-dépasser ou déborder un quotient et lever une exception.
    """
    for name, value in (("low_s", low_s), ("high_s", high_s)):
        if not (math.isfinite(value) and value >= 0):
            raise ValueError(
                f"log_ratio_envelope : {name} doit être fini et >= 0, reçu {value}."
            )
    if low_s > high_s:
        raise ValueError(
            f"log_ratio_envelope : low_s ({low_s}) doit être <= high_s ({high_s})."
        )
    if high_s == 0:
        return LogRatioEnvelope(None, None, None, _ZERO_TIME)
    if not _valid_output(projected_s):
        return LogRatioEnvelope(None, None, None, _MODEL_ERROR)
    lower = log_ratio(projected_s, high_s)
    motif: Unavailability | None
    if low_s == 0:
        upper, motif = math.inf, _ZERO_TIME
    else:
        upper, motif = log_ratio(projected_s, low_s), None
    min_abs = 0.0 if lower <= 0 <= upper else min(abs(lower), abs(upper))
    return LogRatioEnvelope(lower, upper, min_abs, motif)
