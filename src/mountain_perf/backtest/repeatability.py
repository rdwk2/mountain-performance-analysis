"""Référence prédictive de répétabilité d'un parcours (``0010`` D8 ; M4b-3).

Deux fonctions pures sur un plan d'observation jours × segments — ``two_way_fit``,
l'ajustement additif ``y_uk = a_k + c_u`` d'une composante par moyennes alternées,
certifié par D8.3, et ``contraction_rate``, le diagnostic de conditionnement ``μ₂`` —
puis la référence d'un parcours sous les onze horloges.

Python pur (décision 1 de rdw du brief M4b-3) : toute somme passe par ``math.fsum``.
Ce module n'importe, de ``mountain_perf.backtest``, que ``support_metrics`` (M4b-1),
qui note les prévisions d'un pli.
"""

import math
from collections.abc import Collection, Iterable, Mapping, Sequence
from datetime import date

from mountain_perf.backtest.metrics import support_metrics
from mountain_perf.schemas import (
    CERTIFICATION_TOLERANCE,
    CLOCKS,
    MIN_CONTRIBUTING_SEGMENTS,
    AdmittedSegment,
    ClassFit,
    ClassMetrics,
    ClassScore,
    Clock,
    ClockReference,
    FoldScores,
    MetricValue,
    RegimeClass,
    RepeatabilityDay,
    RepeatabilityReference,
    SourceRef,
    SupportMetrics,
    TwoWayFit,
    Unavailability,
)

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

_INSUFFICIENT = Unavailability.INSUFFICIENT_SUPPORT
_UNIDENTIFIED = Unavailability.UNIDENTIFIED_REFERENCE
_ZERO_TIME = Unavailability.ZERO_TIME
_NON_CONVERGENCE = Unavailability.NON_CONVERGENCE
_MODEL_ERROR = Unavailability.MODEL_ERROR

_FAILURES = frozenset({_UNIDENTIFIED, _ZERO_TIME, _NON_CONVERGENCE, _MODEL_ERROR})
"""Les motifs d'un ajustement « en échec » : ses segments vus ne sont pas prévus
(brief M4b-3, § 6.1) ; ``insufficient_support`` n'en est pas un."""


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


# ---------------------------------------------------------------------------
# Référence d'un parcours (brief M4b-3, § 6.4)
# ---------------------------------------------------------------------------


def _is_cell(segment: AdmittedSegment) -> bool:
    """Une cellule : un segment admis dont les bornes effectives sont les bornes
    nominales, à l'égalité exacte (précision de ``0010`` D8.1, choix 1 du brief) ; un
    bord ancré n'en est jamais une."""
    return (
        segment.start_m == segment.nominal_start_m
        and segment.end_m == segment.nominal_end_m
    )


def _require_days(
    reference: SourceRef, days: Sequence[RepeatabilityDay], max_iterations: int
) -> None:
    """Préconditions de ``repeatability_reference`` (choix 5 du brief) :
    ``ValueError``, message citant la date ou l'indice."""
    if max_iterations < 1:
        raise ValueError(
            "repeatability_reference : max_iterations doit être >= 1, reçu "
            f"{max_iterations}."
        )
    dates: set[date] = set()
    for day in days:
        civil_date = day.performance.civil_date
        if civil_date in dates:
            raise ValueError(
                f"repeatability_reference : deux jours à la date {civil_date}."
            )
        dates.add(civil_date)
    for day in days:
        if day.reference != reference:
            raise ValueError(
                f"repeatability_reference : le jour {day.performance.civil_date} a "
                "une autre référence que celle du parcours."
            )
    bounds: dict[int, tuple[float, float]] = {}
    classes: dict[int, RegimeClass] = {}
    for day in sorted(days, key=lambda day: day.performance.civil_date):
        for segment in day.segments or ():
            k = segment.index
            nominal = (segment.nominal_start_m, segment.nominal_end_m)
            if bounds.setdefault(k, nominal) != nominal:
                raise ValueError(
                    f"repeatability_reference : l'indice {k} a deux couples de bornes "
                    f"nominales, {bounds[k]} et {nominal} (le "
                    f"{day.performance.civil_date})."
                )
            if not _is_cell(segment):
                continue
            regime = segment.regime_class
            if classes.setdefault(k, regime) != regime:
                raise ValueError(
                    f"repeatability_reference : l'indice {k} a deux classes sur ses "
                    f"cellules, {classes[k]} et {regime} (le "
                    f"{day.performance.civil_date})."
                )


def _single_contrast(cells: Sequence[Mapping[int, AdmittedSegment]]) -> bool:
    """« Un seul contraste » (précision de ``0010`` D8.4) : exactement deux jours
    éligibles ont au moins un indice de cellule en commun avec un autre jour
    éligible."""
    sharing = 0
    for u, own in enumerate(cells):
        others = {k for v, day in enumerate(cells) if v != u for k in day}
        if own.keys() & others:
            sharing += 1
    return sharing == 2


def _forecast_s(effect: float) -> float:
    """``p_jk = exp(a_k)`` (``0010`` D8.4) ; un débordement de ``math.exp`` (au-delà
    de ``a_k ≈ 709,78``) vaut une prévision non finie (§ 6.4, étape 4.7)."""
    try:
        return math.exp(effect)
    except OverflowError:
        return math.inf


def _without_component(
    regime: RegimeClass, motif: Unavailability, left_count: int, seen_count: int
) -> ClassFit:
    return ClassFit(
        regime, motif, left_count, seen_count, 0, 0, 0, (), None, None, None, None
    )


def _class_fit(
    regime: RegimeClass,
    fold: int,
    clock_index: int,
    dates: Sequence[date],
    cells: Sequence[Mapping[int, AdmittedSegment]],
    max_iterations: int,
) -> tuple[ClassFit, tuple[int, ...], dict[int, float]]:
    """L'ajustement d'un pli et d'une classe (§ 6.4, étape 4 ; ``0010`` D8.2, D8.3) :
    le ``ClassFit``, ``S_jR`` et les prévisions ``p_jk`` retenues (aucune en
    échec)."""
    training = {
        (u, k): segment
        for u, day in enumerate(cells)
        if u != fold
        for k, segment in day.items()
        if segment.regime_class is regime
    }
    left = sorted(
        k for k, segment in cells[fold].items() if segment.regime_class is regime
    )
    training_segments = {k for _, k in training}
    seen = tuple(k for k in left if k in training_segments)
    if not seen:
        return _without_component(regime, _INSUFFICIENT, len(left), 0), seen, {}
    meeting = [
        component
        for component in _components(training)
        if any(k in seen for _, k in component)
    ]
    if len(meeting) > 1:
        fit_failed = _without_component(regime, _UNIDENTIFIED, len(left), len(seen))
        return fit_failed, seen, {}
    component = meeting[0]
    contraction = contraction_rate(component)
    times_s = {cell: training[cell].times_s[clock_index] for cell in component}
    zero_cells = tuple(
        sorted((dates[u], k) for (u, k), time_s in times_s.items() if time_s == 0.0)
    )
    fit: TwoWayFit | None = None
    forecasts: dict[int, float] = {}
    motif: Unavailability | None
    if zero_cells:
        motif = _ZERO_TIME
    else:
        fit = two_way_fit(
            {cell: math.log(time_s) for cell, time_s in times_s.items()},
            max_iterations,
        )
        if not fit.certified:
            motif = _NON_CONVERGENCE
        else:
            effects = dict(fit.segment_effects)
            forecasts = {k: _forecast_s(effects[k]) for k in seen}
            invalid = any(not (math.isfinite(p) and p > 0) for p in forecasts.values())
            motif = _MODEL_ERROR if invalid else None
    class_fit = ClassFit(
        regime_class=regime,
        unavailability=motif,
        left_count=len(left),
        seen_count=len(seen),
        training_days=len({u for u, _ in component}),
        training_segments=len({k for _, k in component}),
        training_cells=len(component),
        zero_cells=zero_cells,
        iterations=None if fit is None else fit.iterations,
        residuals=None if fit is None else fit.residuals,
        contraction=contraction,
        contraction_unavailability=(
            None if contraction is not None else _NON_CONVERGENCE
        ),
    )
    return class_fit, seen, forecasts if motif is None else {}


def _level(
    support: Sequence[int],
    predicted: Sequence[int],
    times_s: Mapping[int, float],
    fits: Sequence[ClassFit],
    metrics: SupportMetrics | None,
) -> MetricValue:
    """``L`` du jour retiré, effectif ``|S_j|``, par priorité (précision de ``0010``
    D8.4) : ``S_j`` vide ; total nul sur ``S_j`` ; ``P_j ≠ S_j``, le motif du premier
    ajustement en échec dans l'ordre de ``RegimeClass`` (``|L|`` strict, décision 5) ;
    sinon ``L`` de ``support_metrics`` sur ``P_j = S_j``, signé."""
    n = len(support)
    if n == 0:
        return MetricValue(None, _INSUFFICIENT, 0)
    if math.fsum(times_s[k] for k in support) == 0.0:
        return MetricValue(None, _ZERO_TIME, n)
    if predicted != support or metrics is None:
        failure = next(
            fit.unavailability for fit in fits if fit.unavailability in _FAILURES
        )
        return MetricValue(None, failure, n)
    return MetricValue(metrics.log_ratio.value, None, n)


def _class_score(
    fit: ClassFit,
    zero_on_support: bool,
    class_metrics: Mapping[RegimeClass, ClassMetrics],
) -> ClassScore:
    """Les scores d'une classe, effectif ``|S_jR|`` (précision de ``0010`` D8.4) :
    aucun segment vu ; un temps nul du jour retiré sur ``S_j``, pour toutes les
    classes (D5.5, décision 6) ; le motif de l'ajustement ; sinon ``E_R`` (signé) et
    ``D_R`` de ``support_metrics`` ; contribue avec au moins trois segments (D7.5)."""
    regime, n = fit.regime_class, fit.seen_count
    motif: Unavailability | None
    if n == 0:
        motif = _INSUFFICIENT
    elif zero_on_support:
        motif = _ZERO_TIME
    else:
        motif = fit.unavailability
    if motif is None:
        computed = class_metrics[regime]
        contributes = computed.log_ratio.available and n >= MIN_CONTRIBUTING_SEGMENTS
        return ClassScore(
            regime, n, computed.log_ratio, computed.dispersion, contributes
        )
    absent = MetricValue(None, motif, n)
    return ClassScore(regime, n, absent, absent, False)


def _fold_scores(
    fold: int,
    clock_index: int,
    dates: Sequence[date],
    cells: Sequence[Mapping[int, AdmittedSegment]],
    max_iterations: int,
) -> FoldScores:
    """Le pli ``j`` sous une horloge (§ 6.4, étapes 4 et 5)."""
    left_day = cells[fold]
    fits: list[ClassFit] = []
    support: list[int] = []
    forecasts: dict[int, float] = {}
    for regime in RegimeClass:
        fit, seen, predicted_s = _class_fit(
            regime, fold, clock_index, dates, cells, max_iterations
        )
        fits.append(fit)
        support.extend(seen)
        forecasts.update(predicted_s)
    support.sort()
    predicted = sorted(forecasts)
    times_s = {k: left_day[k].times_s[clock_index] for k in support}
    metrics = (
        support_metrics(
            [forecasts[k] for k in predicted],
            [times_s[k] for k in predicted],
            [left_day[k].regime_class for k in predicted],
        )
        if predicted
        else None
    )
    class_metrics = (
        {} if metrics is None else {item.regime_class: item for item in metrics.classes}
    )
    zero_on_support = any(times_s[k] == 0.0 for k in support)
    return FoldScores(
        day=dates[fold],
        support_count=len(support),
        predicted_count=len(predicted),
        fits=tuple(fits),
        forecast_s=tuple((k, forecasts[k]) for k in predicted),
        level=_level(support, predicted, times_s, fits, metrics),
        classes=tuple(
            _class_score(fit, zero_on_support, class_metrics) for fit in fits
        ),
    )


def _mean_over_days(values: Sequence[float]) -> MetricValue:
    """``F_q`` : moyenne arithmétique à poids égal par jour, effectif ``m_q`` ;
    ``m_q <= 1`` → ``support insuffisant`` (précision de ``0010`` D8.4)."""
    m = len(values)
    if m <= 1:
        return MetricValue(None, _INSUFFICIENT, m)
    return MetricValue(math.fsum(values) / m, None, m)


def _clock_reference(
    clock: Clock,
    clock_index: int,
    dates: Sequence[date],
    cells: Sequence[Mapping[int, AdmittedSegment]],
    max_iterations: int,
) -> ClockReference:
    """La référence sous une horloge (§ 6.4, étape 6) : les plis, ``F_|L|`` sur les
    plis où ``L`` est présent, ``F_|E_R|`` et ``F_D_R`` sur ceux où la classe
    contribue."""
    folds = tuple(
        _fold_scores(j, clock_index, dates, cells, max_iterations)
        for j in range(len(dates))
    )
    level = _mean_over_days(
        [abs(value) for fold in folds if (value := fold.level.value) is not None]
    )
    log_ratios: list[MetricValue] = []
    dispersions: list[MetricValue] = []
    for i in range(len(RegimeClass)):
        scores = [fold.classes[i] for fold in folds if fold.classes[i].contributes]
        log_ratios.append(
            _mean_over_days(
                [abs(v) for score in scores if (v := score.log_ratio.value) is not None]
            )
        )
        dispersions.append(
            _mean_over_days(
                [v for score in scores if (v := score.dispersion.value) is not None]
            )
        )
    return ClockReference(clock, folds, level, tuple(log_ratios), tuple(dispersions))


def repeatability_reference(
    reference: SourceRef,
    days: Sequence[RepeatabilityDay],
    *,
    max_iterations: int = MAX_ITERATIONS,
) -> RepeatabilityReference:
    """La référence prédictive de répétabilité d'un parcours sous les onze horloges
    (``0010`` D8 et ses précisions de M4b-3 ; brief M4b-3, § 6.4).

    ``days`` : les jours du jeu de répétabilité du parcours, dans n'importe quel ordre,
    jours multi-sorties compris (exclus et publiés). ``max_iterations`` : la limite de
    ``two_way_fit`` (paramètre des tests ; la règle est la valeur par défaut).

    Les jours éligibles sont triés par date, le rang ``u`` d'un jour est sa position ;
    ses cellules sont ses segments de bornes effectives nominales. Pour chaque horloge,
    chaque pli ``j`` et chaque classe ``R`` (montée, plat, descente, mixte) :
    ``S_jR``, les cellules de ``R`` du jour retiré vues à l'apprentissage — vide,
    ``support insuffisant`` ; dans plusieurs composantes du graphe de toutes les
    cellules d'apprentissage, ``référence non identifiée`` ; sinon la composante qui
    les contient, son ``μ₂`` (``contraction_rate``), puis une cellule nulle,
    ``temps nul`` ; un ajustement non certifié (``two_way_fit``),
    ``non-convergence`` ; une prévision ``exp(a_k)`` non finie ou nulle,
    ``erreur du modèle``. Puis les scores du pli par ``support_metrics`` sur ``P_j``
    (``L`` et ``E_R`` signés), et ``F`` sur les plis.

    Préconditions (``ValueError``, message citant la date ou l'indice) :
    ``max_iterations >= 1`` ; dates distinctes (multi-sorties compris) ; tous les
    jours sous ``reference`` ; un indice, un seul couple de bornes nominales (tous les
    segments, bords ancrés compris) et une seule classe sur ses cellules.

    Non promis : elle ne lit ni GPX ni manifeste et ne constitue pas les jours
    (M4b-5) ; elle ne vérifie pas que les segments viennent de ``reference`` ; aucune
    mention « un seul contraste » n'est écrite dans un texte (M4b-5) ; une prévision
    **finie** hors de ``[1e−6 ; 1e12]`` sort du domaine de ``support_metrics`` (brief
    M4b-1, choix 12), qui peut alors lever : seule une prévision non finie ou nulle
    donne ``erreur du modèle``.
    """
    _require_days(reference, days, max_iterations)
    eligible = sorted(
        (day for day in days if not day.performance.is_multi_outing),
        key=lambda day: day.performance.civil_date,
    )
    multi_outing_days = tuple(
        sorted(
            day.performance.civil_date
            for day in days
            if day.performance.is_multi_outing
        )
    )
    dates = tuple(day.performance.civil_date for day in eligible)
    cells = [
        {segment.index: segment for segment in day.segments or () if _is_cell(segment)}
        for day in eligible
    ]
    clocks = tuple(
        _clock_reference(clock, h, dates, cells, max_iterations)
        for h, clock in enumerate(CLOCKS)
    )
    return RepeatabilityReference(
        reference, dates, multi_outing_days, _single_contrast(cells), clocks
    )
