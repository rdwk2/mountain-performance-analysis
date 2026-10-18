"""La stabilité d'une montée (AN1-2, ``docs/decisions/0014``) : la même chaîne sous
des variantes déclarées de sa définition, une à la fois, recalculée à chaque
régénération.

Une montée de référence est **retrouvée** dans une variante si une montée de la
variante la recouvre en temps avec un indice de Jaccard (intersection sur union de
``[t_a ; t_b]``) d'au moins ``min_jaccard`` ; on garde la meilleure, et à égalité la
première dans l'ordre du temps. Elle est
**stable** si elle est retrouvée dans au moins ``min_found_fraction`` des variantes et
si le plus grand écart relatif de sa VAM principale entre la référence et une
variante où elle est retrouvée reste sous ``max_relative_deviation``. Une montée
instable est marquée, jamais retirée.

Python pur : ce module ne demande aucun extra.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass

from mountain_perf.analyse.climbs import (
    CLIMB_PARAMETER_SPECS,
    ClimbMeasure,
    MotionTrack,
    climbs,
)
from mountain_perf.gpx.profile import PROFILE_PARAMETER_SPECS
from mountain_perf.schemas import ParameterSet, ParameterSpec

STABILITY_PARAMETER_SPECS: tuple[ParameterSpec, ...] = (
    ParameterSpec(
        "min_jaccard",
        None,
        0.5,
        0.0,
        1.0,
        "Recouvrement minimal en temps (intersection sur union) d'une montée"
        " retrouvée.",
    ),
    ParameterSpec(
        "min_found_fraction",
        None,
        0.8,
        0.0,
        1.0,
        "Part minimale des variantes où une montée stable est retrouvée.",
    ),
    ParameterSpec(
        "max_relative_deviation",
        None,
        0.05,
        0.0,
        10.0,
        "Plus grand écart relatif de VAM admis pour une montée stable.",
    ),
)
"""Les seuils de la stabilité (``docs/decisions/0014``)."""


@dataclass(frozen=True)
class Variant:
    """Une variante de la définition : son nom et ce qu'elle change aux paramètres
    du profil et de la montée."""

    name: str
    profile: Callable[[dict[str, float]], dict[str, float]]
    climb: Callable[[dict[str, float]], dict[str, float]]


def _same(values: dict[str, float]) -> dict[str, float]:
    return values


def _scale(key: str, factor: float) -> Callable[[dict[str, float]], dict[str, float]]:
    return lambda values: {**values, key: values[key] * factor}


def _shift(key: str, delta: float) -> Callable[[dict[str, float]], dict[str, float]]:
    return lambda values: {**values, key: values[key] + delta}


def _set(key: str, value: float) -> Callable[[dict[str, float]], dict[str, float]]:
    return lambda values: {**values, key: value}


VARIANTS: tuple[Variant, ...] = (
    Variant("hysteresis_half", _same, _scale("hysteresis_m", 0.5)),
    Variant("hysteresis_double", _same, _scale("hysteresis_m", 2.0)),
    Variant("flat_length_half", _same, _scale("flat_length_m", 0.5)),
    Variant("flat_length_double", _same, _scale("flat_length_m", 2.0)),
    Variant("flat_time_ratio_half", _same, _scale("flat_time_ratio", 0.5)),
    Variant("flat_time_ratio_double", _same, _scale("flat_time_ratio", 2.0)),
    Variant("flat_grade_minus", _same, _shift("flat_grade", -0.01)),
    Variant("flat_grade_plus", _same, _shift("flat_grade", 0.01)),
    Variant("smoothing_five_points", _set("smoothing_window_m", 250.0), _same),
    Variant("grid_25_m", _set("grid_step_m", 25.0), _same),
    Variant("bound_tolerance_half", _same, _scale("bound_tolerance_m", 0.5)),
    Variant("bound_tolerance_double", _same, _scale("bound_tolerance_m", 2.0)),
)
"""Les variantes déclarées, une à la fois, appliquées aux paramètres de référence."""


@dataclass(frozen=True)
class ClimbStability:
    """La stabilité d'une montée de référence.

    - ``found_fraction`` : part des variantes où elle est retrouvée ;
    - ``max_relative_deviation`` : plus grand ``|VAM_v / VAM − 1|`` sur les variantes
      où elle est retrouvée et où les deux VAM existent ; ``None`` s'il n'y en a
      aucune ;
    - ``stable`` : le critère du module ; ``None`` si la montée n'a pas de VAM
      positive (sans temps en mouvement, ou un gain en M nul ou négatif : aucun écart
      relatif ne se lit).
    """

    found_fraction: float
    max_relative_deviation: float | None
    stable: bool | None


def jaccard(a: ClimbMeasure, b: ClimbMeasure) -> float:
    """Intersection sur union de ``[t_a ; t_b]`` de deux montées."""
    inter = min(a.span.end_s, b.span.end_s) - max(a.span.start_s, b.span.start_s)
    if inter <= 0:
        return 0.0
    union = max(a.span.end_s, b.span.end_s) - min(a.span.start_s, b.span.start_s)
    return inter / union


def _best(
    reference: ClimbMeasure, candidates: Sequence[ClimbMeasure], min_jaccard: float
) -> ClimbMeasure | None:
    best, best_value = None, 0.0
    for candidate in candidates:
        value = jaccard(reference, candidate)
        if value > best_value:
            best, best_value = candidate, value
    return best if best_value >= min_jaccard else None


def variant_climbs(
    track: MotionTrack,
    profile: ParameterSet | None = None,
    climb: ParameterSet | None = None,
) -> tuple[tuple[ClimbMeasure, ...], ...]:
    """Les montées de ``track`` sous chaque variante de :data:`VARIANTS`, dans son
    ordre, à partir des paramètres de référence donnés."""
    profile = profile or ParameterSet(PROFILE_PARAMETER_SPECS)
    climb = climb or ParameterSet(CLIMB_PARAMETER_SPECS)
    out = []
    for variant in VARIANTS:
        p = ParameterSet(PROFILE_PARAMETER_SPECS, variant.profile(dict(profile.values)))
        c = ParameterSet(CLIMB_PARAMETER_SPECS, variant.climb(dict(climb.values)))
        out.append(climbs(track, p, c))
    return tuple(out)


def stability(
    reference: ClimbMeasure,
    variants: Sequence[Sequence[ClimbMeasure]],
    parameters: ParameterSet,
) -> ClimbStability:
    """La stabilité de ``reference`` contre les montées de chaque variante."""
    found = 0
    deviations: list[float] = []
    vam = reference.vertical_speed_ms
    for candidates in variants:
        match = _best(reference, candidates, parameters["min_jaccard"])
        if match is None:
            continue
        found += 1
        other = match.vertical_speed_ms
        if vam is not None and vam > 0 and other is not None:
            deviations.append(abs(other / vam - 1))
    fraction = found / len(variants) if variants else 0.0
    deviation = max(deviations) if deviations else None
    if vam is None or vam <= 0:
        stable = None
    else:
        stable = (
            fraction >= parameters["min_found_fraction"]
            and deviation is not None
            and deviation < parameters["max_relative_deviation"]
        )
    return ClimbStability(fraction, deviation, stable)
