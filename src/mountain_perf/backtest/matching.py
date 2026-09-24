"""Appariement d'une trace aux points de score du tracé de référence (M4a-2a).

``0010`` D4.2 (grille de score, bornes effectives des extrémités) et D4.5 à D4.9
(franchissements, recherche ordonnée, regroupement, extrémités, trous).

Chaque seuil est jugé par un **prédicat nommé** de ce module, et seulement par lui :
le code de recherche n'en réécrit aucune comparaison. C'est ce qui permet de tester
les égalités de seuil sur des valeurs exactement représentables, jamais à travers
une trace.
"""

from mountain_perf.schemas import ParameterSpec

MATCHING_PARAMETER_SPECS: tuple[ParameterSpec, ...] = (
    ParameterSpec(
        name="score_step_m",
        unit="m",
        default=250.0,
        minimum=10.0,
        maximum=5000.0,
        description="Δ, pas de la grille de score (0010 D4.2).",
    ),
    ParameterSpec(
        name="lateral_tolerance_m",
        unit="m",
        default=30.0,
        minimum=1.0,
        maximum=200.0,
        description="ε, tolérance latérale et d'ancrage (0010 D4.5, D4.8).",
    ),
    ParameterSpec(
        name="cluster_radius_m",
        unit="m",
        default=15.0,
        minimum=0.0,
        maximum=100.0,
        description="r_c, rayon de regroupement des candidats (0010 D4.7).",
    ),
)
"""Les trois paramètres déclaratifs de l'appariement, défauts de ``0010``.

``r_c`` est fixe dans la sensibilité (``0010`` D13) ; tous les autres seuils sont
des constantes de ce module, fixes au M4.
"""

WINDOW_FACTOR = 2.5
"""Facteur de la fenêtre de recherche (``0010`` D4.6) : la borne s'élargit de
``2,5·Δ`` par point depuis le dernier point daté."""

WINDOW_SLACK_M = 300.0
"""Marge de la fenêtre de recherche (m, ``0010`` D4.6)."""


def score_grid(length_m: float, step_m: float) -> tuple[float, ...]:
    """Grille de score ``s_k = k·Δ`` pour ``k·Δ < L``, plus ``L`` (``0010`` D4.2).

    Le produit ``k·Δ`` est calculé à chaque rang, jamais par additions successives :
    une somme cumulée de ``0,1`` rend ``0,7999999999999999`` au neuvième rang.
    ``step_m <= 0`` : ``ValueError``.
    """
    if not step_m > 0:
        raise ValueError(f"score_grid : pas non positif {step_m}.")
    grid_m: list[float] = []
    k = 0
    while k * step_m < length_m:
        grid_m.append(k * step_m)
        k += 1
    grid_m.append(length_m)
    return tuple(grid_m)


# ---------------------------------------------------------------------------
# Prédicats de seuil (0010 D4.5 à D4.8)
# ---------------------------------------------------------------------------


def crosses(h_before_m: float, h_after_m: float, *, closed: bool) -> bool:
    """Franchissement orienté de la normale entre deux enregistrements.

    Ouvert : ``h_before <= 0 < h_after`` (``0010`` D4.5). Fermé, au point
    d'arrivée : ``h_before <= 0 <= h_after`` et ``(h_before, h_after) != (0, 0)``
    (D4.8) — une trace qui longe la ligne d'arrivée ne la franchit pas.
    """
    if closed:
        return h_before_m <= 0 <= h_after_m and (h_before_m, h_after_m) != (0, 0)
    return h_before_m <= 0 < h_after_m


def crossing_fraction(h_before_m: float, h_after_m: float) -> float:
    """``f`` du franchissement (``0010`` D4.5) : ``0`` si ``h_before == 0``, sinon
    ``−h_before / (h_after − h_before)``."""
    if h_before_m == 0:
        return 0.0
    return -h_before_m / (h_after_m - h_before_m)


def within_tolerance(lateral_m: float, tolerance_m: float) -> bool:
    """Candidat admissible : écart latéral ``abs(lateral) < ε``, strictement
    (``0010`` D4.5)."""
    return abs(lateral_m) < tolerance_m


def window_bound_m(realized_m: float, step_m: float, k: int, k_last: int) -> float:
    """Borne de la fenêtre de recherche du point ``k`` (``0010`` D4.6) :
    ``d_r(π_cur) + 2,5·Δ·(k − k_der) + 300`` m."""
    return realized_m + WINDOW_FACTOR * step_m * (k - k_last) + WINDOW_SLACK_M


def within_window(realized_m: float, bound_m: float) -> bool:
    """Abscisse réalisée dans la fenêtre : ``d_r <= D`` (``0010`` D4.6)."""
    return realized_m <= bound_m


def within_cluster(distance_m: float, radius_m: float) -> bool:
    """Point du sous-chemin à ``<= r_c`` de ``Q`` (``0010`` D4.7)."""
    return distance_m <= radius_m


def departure_anchorable(h_m: float, lateral_m: float, tolerance_m: float) -> bool:
    """Premier enregistrement ancrable au départ (``0010`` D4.8) :
    ``0 < h_0 <= ε`` et ``abs(lateral) < ε``."""
    return 0 < h_m <= tolerance_m and within_tolerance(lateral_m, tolerance_m)


def arrival_anchorable(h_m: float, lateral_m: float, tolerance_m: float) -> bool:
    """Dernier enregistrement ancrable à l'arrivée (``0010`` D4.8) :
    ``−ε <= h < 0`` et ``abs(lateral) < ε``."""
    return -tolerance_m <= h_m < 0 and within_tolerance(lateral_m, tolerance_m)


def departure_offset_ok(s_m: float, tolerance_m: float, next_nominal_m: float) -> bool:
    """Projection d'ancrage du départ retenue (``0010`` D4.8) : ``s'_0 <= ε``, et
    ``s'_0 < s_1`` pour des bornes effectives strictement croissantes."""
    return s_m <= tolerance_m and s_m < next_nominal_m


def arrival_offset_ok(
    s_m: float, length_m: float, tolerance_m: float, previous_bound_m: float
) -> bool:
    """Projection d'ancrage de l'arrivée retenue (``0010`` D4.8) :
    ``L − s'_K <= ε``, et ``s'_K > b_{K−1}`` pour des bornes effectives strictement
    croissantes."""
    return length_m - s_m <= tolerance_m and s_m > previous_bound_m
