"""La simulation de puissance générique et le seuil calibré (AN3-1,
``docs/decisions/0021``, ``docs/analyse/CHARTE.md`` § 6). « Seuil » veut dire
alpha ; « niveau », ``1 − alpha``. La puissance est la probabilité de lire « établi »
dans le sens de ``b`` ; l'erreur S, la part des « établi » de sens contraire ;
l'erreur M, la moyenne de ``|estimation|/|b|`` parmi les « établi » (Gelman et
Carlin, 2014)."""

from __future__ import annotations

import itertools
import math
import multiprocessing
from collections.abc import Callable, Sequence
from concurrent.futures import ProcessPoolExecutor
from dataclasses import dataclass
from functools import partial

import numpy

from mountain_perf.analyse.inference.base import InferenceError, child_rng
from mountain_perf.analyse.inference.readings import Reading


@dataclass(frozen=True)
class Outcome:
    """Le résultat d'une estimation simulée : l'estimation (sur l'échelle de ``b``),
    une lecture et un sens par seuil alpha de la grille, dans son ordre."""

    estimate: float
    readings: tuple[Reading, ...]
    directions: tuple[int, ...]


def _check_alphas(alphas: Sequence[float]) -> tuple[float, ...]:
    checked = tuple(float(a) for a in alphas)
    if not checked:
        raise InferenceError("alphas : la grille est vide")
    for alpha in checked:
        if not 0.0 < alpha < 1.0:
            raise InferenceError(f"alphas : hors de ]0 ; 1[ ({alpha})")
    return checked


def _one_draw[D](
    simulate: Callable[[float, numpy.random.Generator], D],
    estimate: Callable[[D, tuple[float, ...], numpy.random.Generator], Outcome],
    b_values: tuple[float, ...],
    alphas: tuple[float, ...],
    root_seed: int,
    key: tuple[int, ...],
    task: tuple[int, int],
) -> Outcome:
    """Le tirage ``k`` de ``b_values[i]`` : ``simulate`` sous
    ``child_rng(root_seed, *key, i, k)``, ``estimate`` sous
    ``child_rng(root_seed, *key, i, k, 1)``."""
    i, k = task
    data = simulate(b_values[i], child_rng(root_seed, *key, i, k))
    return estimate(data, alphas, child_rng(root_seed, *key, i, k, 1))


def simulate_power[D](
    simulate: Callable[[float, numpy.random.Generator], D],
    estimate: Callable[[D, tuple[float, ...], numpy.random.Generator], Outcome],
    b_values: Sequence[float],
    alphas: Sequence[float],
    n_draws: int,
    root_seed: int,
    key: tuple[int, ...] = (),
    workers: int = 1,
) -> tuple[tuple[Outcome, ...], ...]:
    """Pour chaque ``b_values[i]``, les ``n_draws`` résultats d'``estimate`` sur des
    données tirées par ``simulate``, dans l'ordre de ``k``. Les graines ne dépendent
    que de ``(i, k)`` : le résultat ne dépend pas de ``workers``. ``workers > 1`` :
    des processus en contexte ``"spawn"`` ; ``simulate`` et ``estimate`` sont alors
    des fonctions de premier niveau d'un module importable."""
    effects = tuple(float(b) for b in b_values)
    if not effects or not all(math.isfinite(b) for b in effects):
        raise InferenceError("b_values : une grille non vide de réels est attendue")
    grid = _check_alphas(alphas)
    if isinstance(n_draws, bool) or not isinstance(n_draws, int) or n_draws < 1:
        raise InferenceError(f"n_draws : un entier ≥ 1 est attendu ({n_draws!r})")
    if isinstance(workers, bool) or not isinstance(workers, int) or workers < 1:
        raise InferenceError(f"workers : un entier ≥ 1 est attendu ({workers!r})")
    child_rng(root_seed, *key)
    tasks = [(i, k) for i in range(len(effects)) for k in range(n_draws)]
    draw = partial(_one_draw, simulate, estimate, effects, grid, root_seed, key)
    if workers == 1:
        outcomes = [draw(task) for task in tasks]
    else:
        context = multiprocessing.get_context("spawn")
        chunk = max(1, len(tasks) // (4 * workers))
        with ProcessPoolExecutor(max_workers=workers, mp_context=context) as pool:
            outcomes = list(pool.map(draw, tasks, chunksize=chunk))
    return tuple(
        tuple(outcomes[i * n_draws : (i + 1) * n_draws]) for i in range(len(effects))
    )


@dataclass(frozen=True)
class PowerRow:
    """Les comptes d'un effet ``b`` : parts des « établi » (quel que soit leur sens)
    et des « absence d'effet utile », erreur de Monte-Carlo de la première, puissance,
    erreurs S et M (``None`` à ``b = 0``, et S et M sans « établi »)."""

    b: float
    n_draws: int
    p_established: float
    p_no_useful_effect: float
    mc_se_established: float
    power: float | None
    s_error: float | None
    m_error: float | None


def _sign(value: float) -> int:
    return (value > 0) - (value < 0)


def power_table(
    b_values: Sequence[float],
    outcomes: Sequence[Sequence[Outcome]],
    alpha_index: int = 0,
) -> tuple[PowerRow, ...]:
    """Les comptes de chaque ``b``, à la lecture ``readings[alpha_index]``."""
    effects = tuple(float(b) for b in b_values)
    if len(effects) != len(outcomes):
        raise InferenceError("outcomes : une suite de résultats par b est attendue")
    if isinstance(alpha_index, bool) or not isinstance(alpha_index, int):
        raise InferenceError(f"alpha_index : un entier est attendu ({alpha_index!r})")
    rows: list[PowerRow] = []
    for b, draws in zip(effects, outcomes, strict=True):
        count = len(draws)
        if count == 0:
            raise InferenceError("outcomes : au moins un résultat par b est attendu")
        if any(not 0 <= alpha_index < len(o.readings) for o in draws):
            raise InferenceError(
                f"alpha_index : hors des indices des lectures ({alpha_index})"
            )
        established = [
            o for o in draws if o.readings[alpha_index] is Reading.ESTABLISHED
        ]
        no_effect = sum(
            1 for o in draws if o.readings[alpha_index] is Reading.NO_USEFUL_EFFECT
        )
        p = len(established) / count
        power = s_error = m_error = None
        if b != 0.0:
            sign = _sign(b)
            same = sum(1 for o in established if o.directions[alpha_index] == sign)
            contrary = sum(1 for o in established if o.directions[alpha_index] == -sign)
            power = same / count
            if established:
                s_error = contrary / len(established)
                m_error = sum(abs(o.estimate) / abs(b) for o in established) / len(
                    established
                )
        rows.append(
            PowerRow(
                b=b,
                n_draws=count,
                p_established=p,
                p_no_useful_effect=no_effect / count,
                mc_se_established=math.sqrt(p * (1.0 - p) / count),
                power=power,
                s_error=s_error,
                m_error=m_error,
            )
        )
    return tuple(rows)


def smallest_visible_effect(
    rows: Sequence[PowerRow], target: float = 0.8
) -> float | None:
    """Le plus petit ``|b|`` parmi les lignes ``b ≠ 0`` dont la puissance atteint
    ``target`` ; ``None`` s'il n'y en a pas (sur la grille donnée, sans
    interpolation)."""
    if not (math.isfinite(target) and 0.0 < target <= 1.0):
        raise InferenceError(f"target : hors de ]0 ; 1] ({target})")
    visible = [
        abs(row.b)
        for row in rows
        if row.b != 0.0 and row.power is not None and row.power >= target
    ]
    return min(visible) if visible else None


@dataclass(frozen=True)
class CalibratedAlpha:
    """Le seuil calibré : ``alpha`` retenu (``None`` : non calibrable), déclenché ou
    non, le taux au seuil nominal et le taux par seuil de la grille, au pire des
    scénarios."""

    alpha: float | None
    triggered: bool
    nominal_rate: float
    rates: tuple[float, ...]


def calibrate_alpha(
    null_outcomes: Sequence[Sequence[Outcome]],
    alphas: Sequence[float],
    alpha_target: float,
    trigger: float = 0.075,
) -> CalibratedAlpha:
    """Le seuil alpha calibré contre le pire des scénarios tirés à ``b = 0`` : déclenché
    si le taux de faux « établi » au seuil nominal ``alphas[0]`` dépasse ``trigger`` ;
    alors le plus grand ``alphas[j]`` dont le taux ne dépasse pas ``alpha_target``.
    Chaque taux se calcule en une seule division (``compte / N``)."""
    for name, value in (("alpha_target", alpha_target), ("trigger", trigger)):
        if not (math.isfinite(value) and 0.0 < value < 1.0):
            raise InferenceError(f"{name} : hors de ]0 ; 1[ ({value})")
    grid = _check_alphas(alphas)
    if any(b >= a for a, b in itertools.pairwise(grid)):
        raise InferenceError(
            "alphas : une grille strictement décroissante est attendue"
        )
    scenarios = [tuple(s) for s in null_outcomes]
    if not scenarios or any(not s for s in scenarios):
        raise InferenceError("null_outcomes : des scénarios non vides sont attendus")
    for scenario in scenarios:
        if any(len(o.readings) != len(grid) for o in scenario):
            raise InferenceError("null_outcomes : une lecture par seuil est attendue")
    rates = tuple(
        max(
            sum(1 for o in scenario if o.readings[j] is Reading.ESTABLISHED)
            / len(scenario)
            for scenario in scenarios
        )
        for j in range(len(grid))
    )
    triggered = rates[0] > trigger
    if not triggered:
        alpha: float | None = grid[0]
    else:
        admissible = [
            a for a, rate in zip(grid, rates, strict=True) if rate <= alpha_target
        ]
        alpha = max(admissible) if admissible else None
    return CalibratedAlpha(
        alpha=alpha, triggered=triggered, nominal_rate=rates[0], rates=rates
    )
