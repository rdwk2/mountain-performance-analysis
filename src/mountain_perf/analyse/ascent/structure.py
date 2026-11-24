"""L'étage 1 du modèle de la montée, la structure, sur toute l'histoire (AN4-2a,
``docs/decisions/0024``), en deux temps.

**Dans la sortie** : sur les sorties à deux montées ou plus, les colonnes
``[x, D, A, I]`` (``x = ln(FC / FC_réf)``, D+ au milieu et altitude en km, ``I`` la
montée intermédiaire) et ``y = ln(VAM)`` centrées par sortie ; une colonne portée par
moins de deux sorties sort du plan ; MCO, ``s²_e = rᵀr / (N_m − G − q)`` (le centrage
consomme ``G`` degrés : ce n'est pas ``LinearFit.scale``), covariance CR2 par sortie et
intervalles de Student aux degrés de Bell-McCaffrey.

**Entre sorties** : les résumés ``r̄_j`` de chaque sortie en moindres carrés généralisés
sur ``[1, D̄_j − D_ref, Ā_j − A_ref]`` sous la covariance à trois composantes de
``reml.py`` (``d_j = s²_e / n_j``) ; sa composante corrélée dans le temps est le niveau
qui suit le temps. Le résumé lu aux références ``s_j`` et sa variance empruntée
``v_j = sigma_u2 + s²_e / n_j``.

Les matrices passent à ``analyse/inference/`` en listes ; ce qui en revient (des
tableaux de numpy, annotés ``Any``) se convertit aussitôt en ``float`` et en ``tuple``.
"""

from __future__ import annotations

import math
import statistics
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from typing import Any

from mountain_perf.analyse.ascent.parameters import (
    MAX_ALTITUDE_SE,
    MAX_VIF,
    MIN_STRUCTURE_MULTI,
    PHI_BOUNDS_DAYS,
)
from mountain_perf.analyse.ascent.references import References
from mountain_perf.analyse.ascent.selection import AscentClimb
from mountain_perf.analyse.ascent.states import AscentState, Unavailable
from mountain_perf.analyse.inference.base import InferenceError, Interval
from mountain_perf.analyse.inference.clusters import cr2_cov, cr2_interval
from mountain_perf.analyse.inference.linear import ols
from mountain_perf.analyse.inference.reml import reml_fit

CARRIED = 1e-12
"""Une colonne centrée est portée par une sortie si une de ses valeurs dépasse ceci."""

LEVEL = 0.95
"""Le niveau des intervalles de l'étage 1."""

_NAMES = ("β", "g", "λ", "rho")


@dataclass(frozen=True)
class SortieSummary:
    """Le résumé d'une sortie : ``value``, ``s_j``, son log de VAM à la FC, au D+, à
    l'altitude et au régime de référence ; ``variance``, ``v_j``, empruntée ; les
    moyennes de la sortie ; ses appareils distincts, triés (``None`` en tête)."""

    activity_ref: str
    day: date
    n_climbs: int
    value: float
    variance: float
    mean_x: float
    mean_d_plus_km: float
    mean_altitude_km: float
    intermediate_share: float
    devices: tuple[tuple[str, int] | None, ...]


@dataclass(frozen=True)
class Point:
    """Le point générique des lissages : un jour, une valeur, sa variance."""

    day: date
    value: float
    variance: float


@dataclass(frozen=True)
class Structure:
    """L'étage 1, la structure.

    - β (``coef[0]``) : de combien le log de la VAM change quand le log de la FC
      augmente de 1, dans une même sortie.
    - ``g`` (``coef[1]``) : par 1 000 m de D+ en plus au milieu de la montée, dans une
      même sortie, à FC, altitude et régime égaux.
    - λ (``coef[2]``) : par 1 000 m d'altitude moyenne de la montée en plus, dans une
      même sortie, à FC, D+ et régime égaux (« ce qui change avec l'altitude »).
    - ``rho`` (``coef[3]``) : une montée intermédiaire contre une longue, dans une même
      sortie.
    - ``gamma_D`` (``gamma[0]``) : par 1 000 m de D+ moyen de la sortie en plus, entre
      sorties (« les sorties longues partent x % moins vite »).
    - ``s_j`` (``summaries[j].value``) : la sortie ``j`` à la FC de référence, au D+ de
      référence, à l'altitude de référence, en montée longue.

    ``cov`` : la covariance CR2 de ``coef`` (lignes et colonnes à 0 d'un coefficient
    non estimé) ; ``dfs`` et ``intervals`` : degrés de Bell-McCaffrey et intervalles à
    95 % (``None`` pour un coefficient non estimé) ; ``sigma_u2`` : l'effet de sortie
    (la composante blanche) ; ``level_process_variance`` : ``s²_a``, la variance du
    niveau qui suit le temps ; ``phi_days`` : sa portée."""

    references: References
    coef: tuple[float, float, float, float]
    cov: tuple[tuple[float, ...], ...]
    estimated: tuple[bool, bool, bool, bool]
    dfs: tuple[float | None, ...]
    intervals: tuple[Interval | None, ...]
    s2_e: float
    n_multi: int
    n_multi_climbs: int
    vif_beta: float | None
    vif_g: float | None
    sigma_u2: float
    level_process_variance: float
    phi_days: float
    gamma: tuple[float, float]
    gamma_cov: tuple[tuple[float, float], tuple[float, float]]
    sigma_u_at_zero: bool
    level_at_zero: bool
    phi_identified: bool
    phi_at_bound: bool
    summaries: tuple[SortieSummary, ...]
    altitude: AscentState | None
    states: tuple[AscentState, ...]

    @property
    def points(self) -> tuple[Point, ...]:
        """``(day, value, variance)`` de chaque résumé, dans leur ordre."""
        return tuple(Point(s.day, s.value, s.variance) for s in self.summaries)


def _columns(climb: AscentClimb, references: References) -> tuple[float, ...]:
    return (
        math.log(climb.hr_bpm / references.hr_bpm),
        climb.d_plus_km,
        climb.altitude_km,
        1.0 if climb.intermediate else 0.0,
    )


def _sorties(climbs: Sequence[AscentClimb]) -> list[list[AscentClimb]]:
    """Les montées groupées par sortie, les sorties triées par ``(day,
    activity_ref)``."""
    groups: dict[str, list[AscentClimb]] = {}
    for climb in climbs:
        groups.setdefault(climb.activity_ref, []).append(climb)
    return sorted(groups.values(), key=lambda g: (g[0].day, g[0].activity_ref))


def _centered(
    sorties: Sequence[Sequence[AscentClimb]], references: References
) -> tuple[list[list[float]], list[float], list[int]]:
    """Les colonnes ``[x, D, A, I]`` et la réponse centrées par sortie, et
    l'étiquette (le rang) de la sortie de chaque ligne."""
    rows: list[list[float]] = []
    response: list[float] = []
    labels: list[int] = []
    for rank, sortie in enumerate(sorties):
        columns = [_columns(c, references) for c in sortie]
        means = [statistics.fmean(col[k] for col in columns) for k in range(4)]
        y_bar = statistics.fmean(c.log_speed for c in sortie)
        for climb, col in zip(sortie, columns, strict=True):
            rows.append([col[k] - means[k] for k in range(4)])
            response.append(climb.log_speed - y_bar)
            labels.append(rank)
    return rows, response, labels


def _vif(rows: Sequence[Sequence[float]], k: int) -> float:
    """``1 / (1 − R²_k)`` de la colonne ``k`` régressée, sans constante, sur les
    autres colonnes de ``rows`` (``R²_k = 1 − RSS / Σ x_k²``) ; 1 si elle est seule."""
    target = [row[k] for row in rows]
    others = [[v for i, v in enumerate(row) if i != k] for row in rows]
    if not others[0]:
        return 1.0
    total = sum(v * v for v in target)
    resid: Any = ols(others, target).resid
    rss = sum(float(e) ** 2 for e in resid.tolist())
    return math.inf if rss == 0.0 else total / rss


def _devices(sortie: Sequence[AscentClimb]) -> tuple[tuple[str, int] | None, ...]:
    found = {c.device for c in sortie}
    known = sorted(d for d in found if d is not None)
    return ((None,) if None in found else ()) + tuple(known)


def fit_structure(
    climbs: Sequence[AscentClimb], references: References
) -> Structure | Unavailable:
    """L'étage 1 sur les montées ``climbs`` (toute l'histoire), aux références
    ``references``. ``INSUFFICIENT`` sous ``MIN_STRUCTURE_MULTI`` sorties à deux
    montées ou plus, quand β ou ``g`` n'est pas estimé (sa colonne sort du plan), ou
    quand un calcul d'``inference/`` refuse ; ``NOT_SEPARABLE`` pour un plan de rang
    incomplet."""
    sorties = _sorties(climbs)
    multi = [s for s in sorties if len(s) >= 2]
    if len(multi) < MIN_STRUCTURE_MULTI:
        return Unavailable(
            AscentState.INSUFFICIENT,
            f"{len(multi)} sorties à deux montées ou plus, "
            f"{MIN_STRUCTURE_MULTI} au moins.",
        )
    rows, response, labels = _centered(multi, references)
    carriers = [
        len({labels[i] for i, row in enumerate(rows) if abs(row[k]) > CARRIED})
        for k in range(4)
    ]
    kept = [k for k in range(4) if carriers[k] >= 2]
    for k in (0, 1):
        if k not in kept:
            return Unavailable(
                AscentState.INSUFFICIENT,
                f"{_NAMES[k]} non estimé : sa colonne varie dans {carriers[k]} "
                "sortie(s) à deux montées ou plus, 2 au moins.",
            )
    design = [[row[k] for k in kept] for row in rows]
    try:
        first = ols(design, response)
    except InferenceError as error:
        return Unavailable(
            AscentState.NOT_SEPARABLE, f"Le plan dans la sortie : {error}."
        )
    coef_kept = [float(c) for c in first.coef.tolist()]
    resid = [float(e) for e in first.resid.tolist()]
    n_multi_climbs = len(rows)
    s2_e = sum(e * e for e in resid) / (n_multi_climbs - len(multi) - len(kept))
    try:
        cov_any: Any = cr2_cov(design, resid, labels)
        cov_kept = [[float(v) for v in row] for row in cov_any.tolist()]
        fitted = [
            cr2_interval(design, response, labels, p, LEVEL) for p in range(len(kept))
        ]
    except InferenceError as error:
        return Unavailable(AscentState.INSUFFICIENT, f"Le premier temps : {error}.")
    coef = [0.0] * 4
    cov = [[0.0] * 4 for _ in range(4)]
    dfs: list[float | None] = [None] * 4
    intervals: list[Interval | None] = [None] * 4
    for p, k in enumerate(kept):
        coef[k] = coef_kept[p]
        interval, df = fitted[p]
        intervals[k] = interval
        dfs[k] = float(df)
        for q, m in enumerate(kept):
            cov[k][m] = cov_kept[p][q]
    vif_beta = _vif(design, kept.index(0))
    vif_g = _vif(design, kept.index(1))
    states = (AscentState.NOT_SEPARABLE,) if max(vif_beta, vif_g) > MAX_VIF else ()
    altitude = (
        AscentState.INSUFFICIENT
        if 2 not in kept or math.sqrt(cov[2][2]) > MAX_ALTITUDE_SE
        else None
    )
    beta, g, lam, rho = coef
    start = sorties[0][0].day
    residual_means: list[float] = []
    second_rows: list[list[float]] = []
    days: list[float] = []
    known: list[float] = []
    means: list[tuple[float, float, float, float]] = []
    for sortie in sorties:
        columns = [_columns(c, references) for c in sortie]
        residual_means.append(
            statistics.fmean(
                c.log_speed - (beta * x + g * d + lam * a + rho * i)
                for c, (x, d, a, i) in zip(sortie, columns, strict=True)
            )
        )
        mean = tuple(statistics.fmean(col[k] for col in columns) for k in range(4))
        means.append((mean[0], mean[1], mean[2], mean[3]))
        second_rows.append(
            [1.0, mean[1] - references.d_plus_km, mean[2] - references.altitude_km]
        )
        days.append(float((sortie[0].day - start).days))
        known.append(s2_e / len(sortie))
    try:
        second = reml_fit(second_rows, residual_means, days, known, PHI_BOUNDS_DAYS)
    except InferenceError as error:
        return Unavailable(AscentState.INSUFFICIENT, f"Le second temps : {error}.")
    gamma_any: Any = second.fit.coef
    gamma_d, gamma_a = float(gamma_any[1]), float(gamma_any[2])
    gamma_cov_any: Any = second.fit.cov
    gamma_cov = (
        (float(gamma_cov_any[1, 1]), float(gamma_cov_any[1, 2])),
        (float(gamma_cov_any[2, 1]), float(gamma_cov_any[2, 2])),
    )
    sigma_u2 = float(second.tau2)
    summaries = tuple(
        SortieSummary(
            activity_ref=sortie[0].activity_ref,
            day=sortie[0].day,
            n_climbs=len(sortie),
            value=r_bar
            - gamma_d * (mean[1] - references.d_plus_km)
            - gamma_a * (mean[2] - references.altitude_km)
            + g * references.d_plus_km
            + lam * references.altitude_km,
            variance=sigma_u2 + s2_e / len(sortie),
            mean_x=mean[0],
            mean_d_plus_km=mean[1],
            mean_altitude_km=mean[2],
            intermediate_share=mean[3],
            devices=_devices(sortie),
        )
        for sortie, r_bar, mean in zip(sorties, residual_means, means, strict=True)
    )
    return Structure(
        references=references,
        coef=(coef[0], coef[1], coef[2], coef[3]),
        cov=tuple(tuple(row) for row in cov),
        estimated=(0 in kept, 1 in kept, 2 in kept, 3 in kept),
        dfs=tuple(dfs),
        intervals=tuple(intervals),
        s2_e=s2_e,
        n_multi=len(multi),
        n_multi_climbs=n_multi_climbs,
        vif_beta=vif_beta,
        vif_g=vif_g,
        sigma_u2=sigma_u2,
        level_process_variance=float(second.s2u),
        phi_days=float(second.phi),
        gamma=(gamma_d, gamma_a),
        gamma_cov=gamma_cov,
        sigma_u_at_zero=second.tau2_at_zero,
        level_at_zero=second.s2u_at_zero,
        phi_identified=second.phi_identified,
        phi_at_bound=second.phi_at_lower or second.phi_at_upper,
        summaries=summaries,
        altitude=altitude,
        states=states,
    )
