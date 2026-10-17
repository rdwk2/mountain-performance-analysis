"""Diagnostic de longue course (``0010`` D12 et ses précisions de M4d-1).

Pour une sortie scorée avec usage : la séquence des éléments observés du ``K`` par
défaut (commune aux horloges, arrivée comprise), puis, pour chaque horloge du rapport et
chacun des cinq modèles de D9.1, les intervalles départ → départ depuis l'origine, la
pente descriptive du log-rapport ``y_h = ln(t_h / p_h)`` sur l'avancement ``u_h`` de v0
brut, les fractions de régime en nuisance, ses retraits et les cumuls ``C_k`` et
``B_k``.

L'algèbre est en Python pur (décision Q4 (d) de M4d) : une SVD de Jacobi à un côté sur
au plus trois colonnes donne la base des nuisances ; ``u`` et ``y`` sont centrés
exactement, projetés deux fois, et les sommes faites par ``math.fsum`` (arbitrage E3).

Fonctions pures, sans lecture ni écriture : le diagnostic ne s'écrit qu'au rapport
complet de ``just backtest`` (décision Q4 (e)).
"""

from __future__ import annotations

import math
from collections.abc import Sequence

from mountain_perf.backtest.calibration import calibrated_forecast
from mountain_perf.backtest.segments import grade_regime
from mountain_perf.model import PROJECTION_PARAMETER_SPECS
from mountain_perf.model.engine import ProjectedTimeline, projected_timeline
from mountain_perf.schemas import (
    CLOCKS,
    DRIFT_IDENTIFICATION_THRESHOLD,
    DRIFT_MODELS,
    DRIFT_RANK_TOLERANCE,
    DRIFT_REGIMES,
    CalibratedPerformance,
    Clock,
    ClockKind,
    DriftDiagnostic,
    DriftFit,
    DriftInterval,
    ModelKind,
    OutingDrift,
    OutingObservation,
    OutingScores,
    PaceCurve,
    ParameterSet,
    PassageMatchResult,
    RouteProfile,
    Unavailability,
)

DRIFT_JACOBI_EPSILON = 1e-15
"""Orthogonalité visée par la SVD de Jacobi : une paire de colonnes n'est plus tournée
quand ``|aᵀ b| <= 1e−15 ‖a‖ ‖b‖`` (relative aux normes des deux colonnes)."""

DRIFT_JACOBI_NEGLIGIBLE = 1e-13
"""Une colonne de norme ``<= 1e−13 ‖A‖_F`` n'est plus tournée : au niveau du bruit,
sa rotation ne converge pas (un retrait de trois colonnes sur deux lignes)."""

DRIFT_JACOBI_MAX_SWEEPS = 60
"""Le nombre de balayages au plus de la SVD de Jacobi ; au-delà, ``ArithmeticError``."""


def _dot(a: Sequence[float], b: Sequence[float]) -> float:
    return math.fsum(x * y for x, y in zip(a, b, strict=True))


def jacobi_svd(
    columns: Sequence[Sequence[float]],
) -> tuple[tuple[float, ...], tuple[tuple[float, ...], ...]]:
    """SVD de Jacobi à un côté d'une matrice lue **par colonnes** (arbitrage E3) :
    rotations de paires de colonnes jusqu'à l'orthogonalité (``DRIFT_JACOBI_EPSILON``),
    une colonne négligeable (``DRIFT_JACOBI_NEGLIGIBLE``) laissée telle quelle.

    Rend les valeurs singulières et les vecteurs singuliers à gauche **dans l'ordre des
    colonnes** (pas triés) ; une valeur nulle a un vecteur nul.

    Sans convergence en ``DRIFT_JACOBI_MAX_SWEEPS`` balayages : ``ArithmeticError``,
    jamais un résultat non convergé.
    """
    a = [[float(x) for x in col] for col in columns]
    k = len(a)
    negligible = DRIFT_JACOBI_NEGLIGIBLE**2 * math.fsum(_dot(col, col) for col in a)
    for _ in range(DRIFT_JACOBI_MAX_SWEEPS):
        rotated = False
        for p in range(k):
            for q in range(p + 1, k):
                alpha = _dot(a[p], a[p])
                beta = _dot(a[q], a[q])
                gamma = _dot(a[p], a[q])
                if (
                    gamma == 0.0
                    or min(alpha, beta) <= negligible
                    or abs(gamma) <= DRIFT_JACOBI_EPSILON * math.sqrt(alpha * beta)
                ):
                    continue
                rotated = True
                zeta = (beta - alpha) / (2.0 * gamma)
                t = math.copysign(1.0, zeta) / (abs(zeta) + math.hypot(1.0, zeta))
                c = 1.0 / math.hypot(1.0, t)
                s = c * t
                ap, aq = a[p], a[q]
                a[p] = [c * x - s * y for x, y in zip(ap, aq, strict=True)]
                a[q] = [s * x + c * y for x, y in zip(ap, aq, strict=True)]
        if not rotated:
            break
    else:
        raise ArithmeticError(
            f"SVD de Jacobi : pas de convergence en {DRIFT_JACOBI_MAX_SWEEPS} "
            "balayages."
        )
    sigma = tuple(math.sqrt(_dot(col, col)) for col in a)
    left = tuple(
        tuple(x / s for x in col) if s > 0 else tuple(0.0 for _ in col)
        for col, s in zip(a, sigma, strict=True)
    )
    return sigma, left


def nuisance_basis(columns: Sequence[Sequence[float]]) -> tuple[tuple[float, ...], ...]:
    """La base ``Z`` de l'espace engendré par les colonnes (``0010`` D12) : les vecteurs
    singuliers à gauche dont la valeur singulière dépasse ``DRIFT_RANK_TOLERANCE`` fois
    la plus grande (tolérance relative) ; vide pour une matrice nulle. Son nombre de
    vecteurs est le rang de ``Z``."""
    sigma, left = jacobi_svd(columns)
    top = max(sigma, default=0.0)
    if top == 0.0:
        return ()
    return tuple(
        u for s, u in zip(sigma, left, strict=True) if s > DRIFT_RANK_TOLERANCE * top
    )


def annihilate(
    v: Sequence[float], basis: Sequence[Sequence[float]]
) -> tuple[float, ...]:
    """Une passe de ``M_Z v`` sur une base orthonormée : chaque coefficient se lit sur
    ``v``, pas sur le vecteur en cours ; la stabilité vient de la seconde passe de
    l'appelant (``drift_fit``)."""
    out = list(v)
    for z in basis:
        c = _dot(z, v)
        out = [x - c * zi for x, zi in zip(out, z, strict=True)]
    return tuple(out)


def drift_fit(
    y: Sequence[float], u: Sequence[float], others: Sequence[Sequence[float]]
) -> DriftFit:
    """L'ajustement de la pente de dérive (``0010`` D12 ; arbitrage E3) : ``y_h = a +
    b·u_h + Σ_{R ≠ R_0} c_R f_hR + e_h``, poids égaux.

    ``others`` porte les colonnes ``f_R, R ≠ R_0``, une valeur par ligne ; la constante
    est ajoutée ici. ``u`` et ``y`` sont centrés exactement, puis projetés deux fois
    hors de ``Z`` ; ``b = (M_Z u)ᵀ (M_Z y) / ‖M_Z u‖²``, ``rho_u = ‖M_Z u‖² / Σ (u −
    ū)²`` (absent si ``u`` est constant), ``a_h = (M_Z u)_h / ‖M_Z u‖²``. La pente est
    identifiable si ``rho_u > DRIFT_IDENTIFICATION_THRESHOLD`` et ``rang(Z) <`` le
    nombre de lignes.

    Préconditions (``ValueError``) : au moins une ligne ; ``u`` et chaque colonne de
    ``others`` ont une valeur par ligne.
    """
    count = len(y)
    if count == 0 or len(u) != count or any(len(col) != count for col in others):
        raise ValueError(f"drift_fit : {count} lignes, colonnes de longueurs diverses.")
    basis = nuisance_basis([[1.0] * count, *others])

    def residual(v: Sequence[float]) -> tuple[float, ...]:
        mean = math.fsum(v) / count
        centred = [x - mean for x in v]
        return annihilate(annihilate(centred, basis), basis)

    mu = residual(u)
    mean_u = math.fsum(u) / count
    spread = math.fsum((x - mean_u) ** 2 for x in u)
    u_mz_u = _dot(mu, mu)
    rho = u_mz_u / spread if spread > 0.0 else None
    if rho is None or not rho > DRIFT_IDENTIFICATION_THRESHOLD or len(basis) >= count:
        return DriftFit(None, rho, u_mz_u, len(basis), count, None)
    slope = _dot(mu, residual(y)) / u_mz_u
    influence = tuple(x / u_mz_u for x in mu)
    return DriftFit(slope, rho, u_mz_u, len(basis), count, influence)


def drift_withdrawals(
    y: Sequence[float], u: Sequence[float], others: Sequence[Sequence[float]]
) -> tuple[DriftFit, ...]:
    """Les retraits (``0010`` D12) : pour chaque ligne, dans l'ordre, ``drift_fit`` sur
    les autres lignes, dans leur ordre, avec ``u`` et les fractions initiaux, **non
    renormalisés** ; la base et l'identification sont refaites à chaque retrait. Moins
    de deux lignes : aucun retrait."""
    count = len(y)
    if count < 2:
        return ()
    fits = []
    for drop in range(count):
        keep = [h for h in range(count) if h != drop]
        fits.append(
            drift_fit(
                [y[h] for h in keep],
                [u[h] for h in keep],
                [[col[h] for h in keep] for col in others],
            )
        )
    return tuple(fits)


def drift_sequence(
    observation: OutingObservation,
) -> tuple[tuple[int, ...], Unavailability | None]:
    """La séquence de D12 (précision de M4d-1, arbitrages E1 et E2) : les rangs des
    éléments du ``K`` par défaut observés, dans l'ordre, jusqu'au premier qui ne l'est
    pas, et le motif de celui-ci (absent si tout ``K`` est observé). L'arrivée est un
    élément comme les autres ; aucune horloge n'intervient."""
    ranks: list[int] = []
    for k, target in enumerate(observation.targets):
        if target.unavailability is not None:
            return tuple(ranks), target.unavailability
        ranks.append(k)
    return tuple(ranks), None


def regime_projected_s(
    profile: RouteProfile, timeline: ProjectedTimeline, start_m: float, end_m: float
) -> tuple[float, float, float]:
    """Le temps projeté de chaque régime de D6 entre deux abscisses, sur la grille fine
    (``0010`` D12) : pour chaque intervalle de la grille, la portion comprise entre
    ``start_m`` et ``end_m`` ajoute ``time_at(fin) − time_at(début)`` de la chronologie
    au régime de sa pente. Dans l'ordre de ``DRIFT_REGIMES`` (montée, plat, descente),
    secondes."""
    distance_m = profile.distance_m
    grades = profile.grade
    shares: tuple[list[float], list[float], list[float]] = ([], [], [])
    for i, grade in enumerate(grades):
        a = max(distance_m[i], start_m)
        b = min(distance_m[i + 1], end_m)
        if b > a:
            regime = DRIFT_REGIMES.index(grade_regime(grade))
            shares[regime].append(timeline.time_at(b) - timeline.time_at(a))
    return math.fsum(shares[0]), math.fsum(shares[1]), math.fsum(shares[2])


def _unavailable(
    model: ModelKind, clock: Clock, reason: Unavailability
) -> DriftDiagnostic:
    return DriftDiagnostic(model, clock, (), None, (), (), None, (), None, reason)


def drift_diagnostic(
    model: ModelKind,
    clock: Clock,
    *,
    observed_s: Sequence[float],
    model_s: Sequence[float | None],
    v0_s: Sequence[float | None],
    positions_m: Sequence[float],
    origin_m: float,
    profile: RouteProfile,
    v0_timeline: ProjectedTimeline,
    stops_s: Sequence[float] | None = None,
) -> DriftDiagnostic:
    """Le diagnostic de longue course d'un modèle sous une horloge (``0010`` D12 ;
    précisions de M4d-1).

    ``observed_s`` : les ``T_h`` sous ``clock``, depuis l'origine ; ``model_s`` : les
    ``P_h`` du modèle (``None`` : absente) ; ``v0_s`` : les ``P⁰_h`` de v0 brut ;
    ``positions_m`` : les abscisses ``s_h`` des éléments ; ``origin_m`` : ``b_0`` ;
    ``stops_s`` : l'arrêt ``D − A`` de chaque élément, sous l'écoulé seulement.

    Les motifs, dans l'ordre : séquence vide, puis abscisses de deux éléments
    successifs (l'origine comprise) non strictement croissantes : support insuffisant ;
    prévision du modèle ou de v0 brut absente ou non finie, puis ``p_h <= 0`` ou
    ``p⁰_h <= 0`` : erreur du modèle ; un ``t_h <= 0`` : temps nul, intervalles,
    ``R_0`` et cumuls publiés. Sinon l'ajustement sur les intervalles, les retraits et
    l'étendue de leurs pentes identifiables.

    ``u_h`` et les fractions viennent de v0 brut ; les fractions sont rapportées à la
    somme des temps projetés par régime (``p⁰_h`` aux arrondis près) ; ``C_k = P_k −
    T_k`` et ``B_k = T_k − T_H · (P_k / P_H)``, ``P`` du modèle évalué (cet ordre
    d'opérations donne ``B_H = 0`` au bit).
    """
    if not observed_s:
        return _unavailable(model, clock, Unavailability.INSUFFICIENT_SUPPORT)
    starts = (origin_m, *positions_m[:-1])
    if any(not end > start for start, end in zip(starts, positions_m, strict=True)):
        return _unavailable(model, clock, Unavailability.INSUFFICIENT_SUPPORT)
    forecasts: list[float] = []
    v0: list[float] = []
    for p, p0 in zip(model_s, v0_s, strict=True):
        if p is None or p0 is None or not math.isfinite(p) or not math.isfinite(p0):
            return _unavailable(model, clock, Unavailability.MODEL_ERROR)
        forecasts.append(p)
        v0.append(p0)
    rows = []
    previous_t = previous_p = previous_v = 0.0
    for t_k, p_k, v_k in zip(observed_s, forecasts, v0, strict=True):
        t_h, p_h, v_h = t_k - previous_t, p_k - previous_p, v_k - previous_v
        if not (p_h > 0 and v_h > 0):
            return _unavailable(model, clock, Unavailability.MODEL_ERROR)
        rows.append((t_h, p_h, previous_v, v_h))
        previous_t, previous_p, previous_v = t_k, p_k, v_k
    horizon = v0[-1]
    intervals = []
    all_shares = []
    for h, (start, end) in enumerate(zip(starts, positions_m, strict=True)):
        t_h, p_h, before, v_h = rows[h]
        shares = regime_projected_s(profile, v0_timeline, start, end)
        total = math.fsum(shares)
        if not total > 0:
            return _unavailable(model, clock, Unavailability.MODEL_ERROR)
        all_shares.append(shares)
        fractions = (shares[0] / total, shares[1] / total, shares[2] / total)
        if stops_s is None:
            moving, stop = None, None
        else:
            stop = stops_s[h]
            moving = t_h - stop
        intervals.append(
            DriftInterval(
                start,
                end,
                t_h,
                p_h,
                math.log(t_h / p_h) if t_h > 0 else None,
                (before + v_h / 2.0) / horizon,
                fractions,
                moving,
                stop,
            )
        )
    totals = [math.fsum(s[i] for s in all_shares) for i in range(3)]
    reference = max(range(3), key=lambda i: (totals[i], -i))
    last_t, last_p = observed_s[-1], forecasts[-1]
    cumulative = tuple(p - t for t, p in zip(observed_s, forecasts, strict=True))
    recentred = tuple(
        t - last_t * (p / last_p) for t, p in zip(observed_s, forecasts, strict=True)
    )
    if any(iv.log_ratio is None for iv in intervals):
        return DriftDiagnostic(
            model,
            clock,
            tuple(intervals),
            DRIFT_REGIMES[reference],
            cumulative,
            recentred,
            None,
            (),
            None,
            Unavailability.ZERO_TIME,
        )
    y = [iv.log_ratio for iv in intervals if iv.log_ratio is not None]
    u = [iv.position for iv in intervals]
    others = [
        [iv.fractions[i] for iv in intervals]
        for i in range(len(DRIFT_REGIMES))
        if i != reference
    ]
    fit = drift_fit(y, u, others)
    withdrawals = drift_withdrawals(y, u, others)
    slopes = [w.slope for w in withdrawals if w.slope is not None]
    slope_range = (min(slopes), max(slopes)) if slopes else None
    return DriftDiagnostic(
        model,
        clock,
        tuple(intervals),
        DRIFT_REGIMES[reference],
        cumulative,
        recentred,
        fit,
        withdrawals,
        slope_range,
        None,
    )


def _stops(
    observation: OutingObservation,
    passages: PassageMatchResult,
    ranks: Sequence[int],
) -> tuple[float, ...]:
    """L'arrêt de chaque élément de la séquence : ``D − A`` de son passage (D4.12),
    l'enveloppe des épisodes attribués — pas leur somme ``S`` ; ``0.0`` pour un élément
    sans passage (l'arrivée)."""
    stops = []
    for k in ranks:
        index = observation.targets[k].passage_index
        if index is None:
            stops.append(0.0)
            continue
        passage = passages.passages[index]
        assert passage.arrival_s is not None  # élément observé
        assert passage.departure_s is not None
        stops.append(passage.departure_s - passage.arrival_s)
    return tuple(stops)


def outing_drift(
    scores: OutingScores,
    passages: PassageMatchResult,
    profile: RouteProfile,
    clocks: Sequence[Clock],
    calibrated: CalibratedPerformance,
    curve: PaceCurve,
    *,
    multi_outing: bool,
    outing_id: str,
) -> OutingDrift | None:
    """La dérive d'une sortie scorée (``0010`` D12 ; précisions de M4d-1) : ``None``
    sans usage ; sinon la séquence, commune aux horloges, son horizon ``P⁰_H`` (le
    cumul de v0 brut au dernier élément, s'il est fini et ``> 0``) et, pour chaque
    horloge de ``clocks`` puis chaque modèle de ``DRIFT_MODELS``, un diagnostic.

    Jour multi-sorties : tous indisponibles, ``MULTI_OUTING_DAY``. Sinon ``u`` et les
    fractions de la chronologie de v0 brut sur ``profile`` ; v0 brut prend ses cumuls
    tels quels (``drift_diagnostic`` les juge, après les abscisses) ; un modèle calé
    prend sa prévision d'usage de ``calibrated`` (celle de ``outing_id``), calée sous
    l'horloge — indisponible, avec le motif de son calage, si celui-ci l'est. Les
    arrêts ne sont publiés que sous l'écoulé.
    """
    usage = scores.usage
    if usage is None:
        return None
    observation = scores.observation
    ranks, stop = drift_sequence(observation)
    v0_s = [usage.forecast.target_s[k] for k in ranks]
    last = v0_s[-1] if v0_s else None
    horizon_s = last if last is not None and math.isfinite(last) and last > 0 else None
    diagnostics: list[DriftDiagnostic] = []
    if multi_outing:
        for clock in clocks:
            diagnostics += [
                _unavailable(model, clock, Unavailability.MULTI_OUTING_DAY)
                for model in DRIFT_MODELS
            ]
    else:
        timeline = projected_timeline(
            profile, curve, ParameterSet(PROJECTION_PARAMETER_SPECS)
        )
        positions_m = [observation.targets[k].distance_m for k in ranks]
        for clock in clocks:
            index = CLOCKS.index(clock)
            observed_s = []
            for k in ranks:
                times = observation.targets[k].times_s
                assert times is not None  # élément observé
                observed_s.append(times[index])
            stops_s = (
                _stops(observation, passages, ranks)
                if clock.kind is ClockKind.ELAPSED
                else None
            )
            for model in DRIFT_MODELS:
                if model is ModelKind.V0_RAW:
                    model_s = v0_s
                else:
                    entry = next(
                        e.usage
                        for e in calibrated.outings
                        if e.outing_id == outing_id
                        and e.usage is not None
                        and e.usage.model is model
                    )
                    calibration = entry.clocks[index].calibration
                    if calibration.unavailability is not None:
                        diagnostics.append(
                            _unavailable(model, clock, calibration.unavailability)
                        )
                        continue
                    target_s = calibrated_forecast(entry.forecast, calibration).target_s
                    model_s = [target_s[k] for k in ranks]
                diagnostics.append(
                    drift_diagnostic(
                        model,
                        clock,
                        observed_s=observed_s,
                        model_s=model_s,
                        v0_s=v0_s,
                        positions_m=positions_m,
                        origin_m=observation.origin_m,
                        profile=profile,
                        v0_timeline=timeline,
                        stops_s=stops_s,
                    )
                )
    return OutingDrift(
        outing_id,
        len(observation.targets),
        len(ranks),
        stop,
        horizon_s,
        tuple(diagnostics),
    )
