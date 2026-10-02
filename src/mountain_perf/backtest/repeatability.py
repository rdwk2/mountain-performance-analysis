"""Référence prédictive de répétabilité d'un parcours (``0010`` D8 ; M4b-3).

Deux fonctions pures sur un plan d'observation jours × segments — ``two_way_fit``,
l'ajustement additif ``y_uk = a_k + c_u`` d'une composante par moyennes alternées,
certifié par D8.3, et ``contraction_rate``, le diagnostic de conditionnement ``μ₂`` —
puis la référence d'un parcours sous les onze horloges.

Python pur (décision 1 de rdw du brief M4b-3) : toute somme passe par ``math.fsum``.
"""

import math
from collections.abc import Collection, Iterable, Mapping

from mountain_perf.schemas import CERTIFICATION_TOLERANCE, TwoWayFit

MAX_ITERATIONS = 10_000
"""La limite d'itérations des moyennes alternées de ``0010`` D8.3, la dernière
comprise (décision 1 de rdw du brief M4b-3). Atteinte sans certification :
``non-convergence``."""

JACOBI_MAX_SWEEPS = 50
"""Le nombre maximal de balayages de la méthode de Jacobi qui calcule ``μ₂``
(précision de ``0010`` D8.3, choix 4 du brief M4b-3) ; au-delà, ``μ₂`` est publié
indisponible, jamais ``0``."""

JACOBI_OFF_DIAGONAL_TOLERANCE = 1e-24
"""Le seuil de certification de Jacobi : la somme des carrés hors diagonale ``<=``
cette valeur, les valeurs propres sont la diagonale (choix 4 du brief M4b-3)."""

Cell = tuple[int, int]


def _components(cells: Iterable[Cell]) -> list[frozenset[Cell]]:
    """Les composantes connexes du graphe biparti jours × segments dont les cellules
    ``(u, k)`` sont les arêtes (``0010`` D8.2), chacune par ses cellules."""
    plan = set(cells)
    by_day: dict[int, list[Cell]] = {}
    by_segment: dict[int, list[Cell]] = {}
    for cell in plan:
        by_day.setdefault(cell[0], []).append(cell)
        by_segment.setdefault(cell[1], []).append(cell)
    components: list[frozenset[Cell]] = []
    seen: set[Cell] = set()
    for start in sorted(plan):
        if start in seen:
            continue
        component: set[Cell] = set()
        stack = [start]
        while stack:
            cell = stack.pop()
            if cell in component:
                continue
            component.add(cell)
            stack.extend(by_day[cell[0]])
            stack.extend(by_segment[cell[1]])
        seen |= component
        components.append(frozenset(component))
    return components


def _criteria(
    log_times: Mapping[Cell, float],
    segment_effect: dict[int, float],
    day_effect: dict[int, float],
    days_of: dict[int, list[int]],
    segments_of: dict[int, list[int]],
) -> tuple[float, float, float]:
    """Les trois premiers critères de D8.3 après le centrage : moyennes de résidus
    ``e_uk = (y_uk − a_k) − c_u`` par segment et par jour (maximum des valeurs
    absolues), ``|Σ c_u|``."""
    residual = {
        (u, k): (y - segment_effect[k]) - day_effect[u]
        for (u, k), y in log_times.items()
    }
    by_segment = max(
        abs(math.fsum(residual[u, k] for u in days) / len(days))
        for k, days in days_of.items()
    )
    by_day = max(
        abs(math.fsum(residual[u, k] for k in segments) / len(segments))
        for u, segments in segments_of.items()
    )
    return by_segment, by_day, abs(math.fsum(day_effect.values()))


def two_way_fit(
    log_times: Mapping[tuple[int, int], float], max_iterations: int = MAX_ITERATIONS
) -> TwoWayFit:
    """L'ajustement ``y_uk = a_k + c_u`` d'une composante connexe par moyennes
    alternées, certifié par ``0010`` D8.3 (précision de M4b-3 ; brief M4b-3, § 6.2).

    ``log_times`` : les cellules ``(u, k) ↦ y_uk = ln t_uk`` d'**une** composante
    connexe ; ``u`` est le rang que l'appelant donne au jour.

    À la lettre : ``c_u = 0`` au départ ; à chaque itération, ``a_k`` reçoit la moyenne
    des ``y_uk − c_u`` sur les jours qui observent ``k`` (``k`` croissants), puis
    ``c_u`` la moyenne des ``y_uk − a_k`` sur les segments de ``u`` (``u``
    croissants), puis ``c_u ← c_u − m`` et ``a_k ← a_k + m``, ``m`` la moyenne des
    ``c_u``. Les critères sont évalués après ce centrage : moyennes de résidus par
    segment et par jour, ``|Σ c_u|``, incrément maximal des ajustés ``a_k + c_u``
    (``inf`` à la première itération, d'où au moins deux). Certifié quand les quatre
    sont sous ``CERTIFICATION_TOLERANCE`` ; sinon, la limite atteinte (la dernière
    itération comprise), le dernier état, non certifié.

    Préconditions (``ValueError``) : ``max_iterations >= 1`` ; au moins une cellule ;
    valeurs finies ; graphe biparti jours × segments connexe.
    """
    if max_iterations < 1:
        raise ValueError(
            f"two_way_fit : max_iterations doit être >= 1, reçu {max_iterations}."
        )
    if not log_times:
        raise ValueError("two_way_fit : aucune cellule.")
    for cell, value in log_times.items():
        if not math.isfinite(value):
            raise ValueError(
                f"two_way_fit : la cellule {cell} a une valeur non finie ({value})."
            )
    if len(_components(log_times)) != 1:
        raise ValueError("two_way_fit : graphe biparti jours × segments non connexe.")
    days_of: dict[int, list[int]] = {}
    segments_of: dict[int, list[int]] = {}
    for u, k in sorted(log_times):
        segments_of.setdefault(u, []).append(k)
        days_of.setdefault(k, []).append(u)
    days_of = dict(sorted(days_of.items()))
    segment_effect: dict[int, float] = {}
    day_effect = dict.fromkeys(segments_of, 0.0)
    previous: dict[Cell, float] | None = None
    for iteration in range(1, max_iterations + 1):
        for k, days in days_of.items():
            segment_effect[k] = math.fsum(
                log_times[u, k] - day_effect[u] for u in days
            ) / len(days)
        for u, segments in segments_of.items():
            day_effect[u] = math.fsum(
                log_times[u, k] - segment_effect[k] for k in segments
            ) / len(segments)
        mean = math.fsum(day_effect.values()) / len(day_effect)
        for u in day_effect:
            day_effect[u] = day_effect[u] - mean
        for k in segment_effect:
            segment_effect[k] = segment_effect[k] + mean
        by_segment, by_day, centering = _criteria(
            log_times, segment_effect, day_effect, days_of, segments_of
        )
        fitted = {(u, k): segment_effect[k] + day_effect[u] for u, k in log_times}
        increment = (
            math.inf
            if previous is None
            else max(abs(fitted[cell] - previous[cell]) for cell in log_times)
        )
        previous = fitted
        residuals = (by_segment, by_day, centering, increment)
        if all(value < CERTIFICATION_TOLERANCE for value in residuals):
            return _fit(segment_effect, day_effect, iteration, residuals, True)
    return _fit(segment_effect, day_effect, max_iterations, residuals, False)


def _fit(
    segment_effect: dict[int, float],
    day_effect: dict[int, float],
    iterations: int,
    residuals: tuple[float, float, float, float],
    certified: bool,
) -> TwoWayFit:
    return TwoWayFit(
        tuple(sorted(segment_effect.items())),
        tuple(sorted(day_effect.items())),
        iterations,
        residuals,
        certified,
    )


def _rotate(matrix: list[list[float]], p: int, q: int) -> None:
    """Une rotation de Jacobi qui annule ``matrix[p][q]`` (brief M4b-3, § 6.3) :
    colonnes, puis lignes."""
    theta = (matrix[q][q] - matrix[p][p]) / (2 * matrix[p][q])
    t = math.copysign(1.0, theta) / (abs(theta) + math.sqrt(theta * theta + 1))
    cos = 1 / math.sqrt(t * t + 1)
    sin = t * cos
    for row in matrix:
        row[p], row[q] = cos * row[p] - sin * row[q], sin * row[p] + cos * row[q]
    rows_p, rows_q = matrix[p], matrix[q]
    for r in range(len(matrix)):
        rows_p[r], rows_q[r] = (
            cos * rows_p[r] - sin * rows_q[r],
            sin * rows_p[r] + cos * rows_q[r],
        )


def _eigenvalues(matrix: list[list[float]], max_sweeps: int) -> list[float] | None:
    """Les valeurs propres d'une matrice symétrique par Jacobi cyclique, ou ``None``
    si ``max_sweeps`` balayages ne la certifient pas (choix 4 du brief M4b-3)."""
    n = len(matrix)
    work = [row[:] for row in matrix]
    sweeps = 0
    while True:
        off = math.fsum(work[p][q] ** 2 for p in range(n) for q in range(n) if p != q)
        if off <= JACOBI_OFF_DIAGONAL_TOLERANCE:
            return [work[i][i] for i in range(n)]
        if sweeps >= max_sweeps:
            return None
        for p in range(n - 1):
            for q in range(p + 1, n):
                if work[p][q] != 0:
                    _rotate(work, p, q)
        sweeps += 1


def contraction_rate(
    cells: Collection[tuple[int, int]], max_sweeps: int = JACOBI_MAX_SWEEPS
) -> float | None:
    """``μ₂``, le diagnostic de conditionnement d'une composante (précision de
    ``0010`` D8.3 ; brief M4b-3, § 6.3).

    ``cells`` : les cellules ``(u, k)`` d'une composante, le plan sans les temps ; une
    cellule répétée compte une fois. ``μ₂`` est la seconde valeur propre de
    ``S = D_j^(−1/2) N D_s^(−1) Nᵀ D_j^(−1/2)`` : ``S[u][v] = fsum(1/d_k sur les k
    observés par u et par v) / sqrt(d_u·d_v)``, jours croissants. Un seul jour :
    ``0.0`` exactement. Valeurs propres par Jacobi cyclique, certifiées quand la somme
    des carrés hors diagonale est ``<= JACOBI_OFF_DIAGONAL_TOLERANCE`` (contrôlée
    avant chaque balayage et après le dernier) ; non certifiées en ``max_sweeps``
    balayages : ``None``. Renvoie ``min(1.0, max(0.0, μ₂))``.

    ``μ₂`` est le facteur asymptotique de contraction de l'erreur des moyennes
    alternées : ``0`` pour un plan complet, proche de ``1`` pour des jours mal reliés.
    Il ne dépend que du plan et ne mesure pas l'incertitude de ``F``.

    Préconditions (``ValueError``) : au moins une cellule ; graphe connexe.
    """
    plan = frozenset(cells)
    if not plan:
        raise ValueError("contraction_rate : aucune cellule.")
    if len(_components(plan)) != 1:
        raise ValueError(
            "contraction_rate : graphe biparti jours × segments non connexe."
        )
    segments_of: dict[int, set[int]] = {}
    segment_degree: dict[int, int] = {}
    for u, k in plan:
        segments_of.setdefault(u, set()).add(k)
        segment_degree[k] = segment_degree.get(k, 0) + 1
    days = sorted(segments_of)
    if len(days) == 1:
        return 0.0
    matrix = [
        [
            math.fsum(1 / segment_degree[k] for k in segments_of[u] & segments_of[v])
            / math.sqrt(len(segments_of[u]) * len(segments_of[v]))
            for v in days
        ]
        for u in days
    ]
    eigenvalues = _eigenvalues(matrix, max_sweeps)
    if eigenvalues is None:
        return None
    second = sorted(eigenvalues, reverse=True)[1]
    return min(1.0, max(0.0, second))
