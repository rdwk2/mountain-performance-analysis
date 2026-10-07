"""Les baselines de ``0010`` D9.1 : vitesse constante, Naismith, Tobler (M4c-1).

Une allure (s/m de distance horizontale) par intervalle de la grille fine du profil
(``0008``), à sa pente ``g`` du profil lissé ; leur chronologie est une
``ProjectedTimeline``, comme celle de v0 : leurs prévisions et leurs scores passent par
les fonctions de M4b-2 (précision de D9.1). Une baseline ne lit pas la courbe.

Une allure non finie ou nulle sur un intervalle (Tobler à une pente extrême) : la
baseline n'a aucune chronologie sur ce profil (décision 6 du brief M4c-1), d'où
``erreur du modèle`` pour la performance, jamais une exception.
"""

import math
from typing import Final

from mountain_perf.model.engine import ProjectedTimeline
from mountain_perf.schemas import ModelKind, RouteProfile

BASELINE_VERSION: Final = "baselines-v1"
"""Version recopiée dans les prévisions des baselines (``engine_version``)."""

CONSTANT_SPEED_MS: Final = 1.0
"""Vitesse nominale de la vitesse constante, absorbée par le facteur (D9.1)."""

NAISMITH_SPEED_MS: Final = 5.0 / 3.6
"""Vitesse de Naismith sur le plat : 5 km/h en m/s (D9.1)."""

NAISMITH_CLIMB_S_PER_M: Final = 3600.0 / 600.0
"""Coût de la montée de Naismith : 1 h par 600 m de D+, soit 6 s/m (D9.1)."""

TOBLER_PEAK_MS: Final = 6.0 / 3.6
"""Vitesse maximale de Tobler : 6 km/h en m/s, à ``g = −0,05`` (D9.1 ; décision 17)."""

TOBLER_DECAY: Final = 3.5
"""Décroissance de Tobler : ``v = v_max · exp(−3,5 · |g + 0,05|)`` (D9.1)."""

TOBLER_OFFSET: Final = 0.05
"""Décalage de la pente de vitesse maximale de Tobler (D9.1)."""

BASELINES: tuple[ModelKind, ...] = (
    ModelKind.CONSTANT_SPEED,
    ModelKind.NAISMITH,
    ModelKind.TOBLER,
)
"""Les trois baselines de D9.1, dans l'ordre du protocole."""


def _tobler_pace(grade: float) -> float:
    """Allure de Tobler, dans l'ordre de calcul de la précision de D9.1 ; ``+inf`` si
    l'exponentielle sous-dépasse."""
    decay = math.exp(-TOBLER_DECAY * abs(grade + TOBLER_OFFSET))
    speed_ms = TOBLER_PEAK_MS * decay
    return math.inf if speed_ms == 0.0 else 1.0 / speed_ms


def baseline_paces(profile: RouteProfile, baseline: ModelKind) -> tuple[float, ...]:
    """L'allure (s/m de distance horizontale) d'une baseline sur chaque intervalle de
    la grille, à sa pente ``g`` (``profile.grade``) — ``0010`` D9.1 et sa précision :

    - vitesse constante : ``1 / CONSTANT_SPEED_MS`` ;
    - Naismith : ``1 / NAISMITH_SPEED_MS + NAISMITH_CLIMB_S_PER_M · max(g, 0)`` (le D+
      du profil lissé, ``Δz⁺ = max(g, 0) · Δd``) ;
    - Tobler : ``1 / (TOBLER_PEAK_MS · exp(−TOBLER_DECAY · |g + TOBLER_OFFSET|))``.

    Une allure peut être non finie (Tobler à une pente extrême, où l'exponentielle
    sous-dépasse) : elle est rendue telle quelle. Précondition (``ValueError``) :
    ``baseline`` est l'une de ``BASELINES``.
    """
    if baseline not in BASELINES:
        raise ValueError(f"baseline_paces : {baseline} n'est pas une baseline (D9.1).")
    if baseline is ModelKind.CONSTANT_SPEED:
        pace = 1.0 / CONSTANT_SPEED_MS
        return tuple(pace for _ in profile.grade)
    if baseline is ModelKind.NAISMITH:
        flat = 1.0 / NAISMITH_SPEED_MS
        return tuple(flat + NAISMITH_CLIMB_S_PER_M * max(g, 0.0) for g in profile.grade)
    return tuple(_tobler_pace(g) for g in profile.grade)


def baseline_timeline(
    profile: RouteProfile, baseline: ModelKind
) -> ProjectedTimeline | None:
    """La chronologie d'une baseline sur un profil (``0010`` D9.1 et sa précision) :
    ``ProjectedTimeline`` de la grille et des allures de :func:`baseline_paces` ;
    ``None`` si une allure n'est pas finie et ``> 0`` — la baseline n'a alors aucune
    prévision sur ce profil (décision 6). Même précondition que
    :func:`baseline_paces`, qui la vérifie.
    """
    paces = baseline_paces(profile, baseline)
    if not all(math.isfinite(pace) and pace > 0 for pace in paces):
        return None
    return ProjectedTimeline(tuple(profile.distance_m), paces)
