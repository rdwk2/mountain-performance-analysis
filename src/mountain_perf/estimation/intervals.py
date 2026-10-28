"""Les intervalles d'une activité, tels que l'estimation de la courbe les mesure
(M6b, ``docs/decisions/0017``) : la courbe se mesure comme le moteur l'applique.

La chaîne, dans cet ordre (:func:`activity_intervals`) :

1. la trace du moteur tirée de l'enregistrement (``trace_view``) ; sans elle,
   « sans trace » (``0017``, P1.1) ;
2. le profil du moteur (``build_profile``, défauts de ``0008``) sur les positions et
   altitudes **brutes** de la trace ; un profil impossible est un motif compté (P1.1) ;
3. les horloges M, S, U de la convention centrale θc (``0010`` D5), cumulées aux
   instants de la trace et interpolées linéairement entre eux (D5.3) ;
4. les bornes des intervalles de la grille du profil : l'instant de chaque abscisse de
   la grille sur la distance réalisée ``d_r`` (:func:`time_at_distance`), la première
   borne ramenée au premier instant de la trace et la dernière au dernier (P1.3) : les
   intervalles pavent toute la trace ;
5. le plafond depuis le départ, s'il est donné : un intervalle qui commence au plafond
   ou après est retiré, celui qui le traverse est coupé (P2.4) ;
6. pour chaque intervalle, sa longueur sur le profil, la pente du profil lissé, ses
   temps M, S, U (les trous gardés, dans U, sans traitement : D1, P1.4) et sa FC
   moyenne décalée (:class:`HeartRateSeries`, P5.1).

Python pur : ni ``analyse/`` ni ``backtest/``.
"""

from __future__ import annotations

from bisect import bisect_left, bisect_right
from collections.abc import Sequence
from dataclasses import dataclass
from enum import StrEnum

from mountain_perf.clocks import clock_partition
from mountain_perf.gpx.profile import ProfileError, build_profile
from mountain_perf.ingest.views import trace_view
from mountain_perf.schemas import (
    CENTRAL_CONVENTION_INDEX,
    ActivityRecording,
    IntervalState,
    ParameterSet,
    Route,
)
from mountain_perf.series import MAX_STEP_S, build_series

MAX_HR_STEP_S = MAX_STEP_S
"""10 s : deux échantillons de FC plus éloignés ne sont pas reliés, un trou de FC (le
trou du moteur, ``0010`` D4.4)."""

COVERAGE_TOLERANCE_S = 1e-6
"""Tolérance de la couverture de la FC, en secondes : les durées couvertes sont des
différences de cumuls, et une couverture exigée de 100 % ne doit pas tomber sur un
arrondi."""

HR_INTEGRATION = "exacte, pas coupés au prorata"
"""Ce que le compagnon dit de l'intégration de la FC (``0017``, P5.1, P5.4)."""


class TraceRefusal(StrEnum):
    """Pourquoi une activité n'a pas d'intervalles (``0017``, P1.1)."""

    NO_TRACE = "sans trace"
    NO_PROFILE = "profil impossible"


@dataclass(frozen=True)
class CurveInterval:
    """Un intervalle de la grille du profil d'une activité.

    - ``length_m`` — mètres — longueur sur le profil, ``> 0`` ; coupée au plafond pour
      un intervalle coupé (``0017``, P2.4) ;
    - ``grade`` — fraction — pente de l'intervalle du profil, sur sa longueur
      d'origine, même coupé ;
    - ``start_s``, ``end_s`` — secondes — instants des bornes, depuis le premier
      instant de la trace ;
    - ``moving_s``, ``stopped_s``, ``undetermined_s`` — secondes — temps M, S, U sous
      θc entre les bornes ;
    - ``heart_rate_bpm`` — battements par minute — FC moyenne de la fenêtre décalée,
      ``None`` si indéfinie ;
    - ``truncated`` — sans unité — vrai si l'intervalle est coupé au plafond.

    ``elapsed_s`` (secondes, calculé) vaut ``end_s − start_s`` ; ``M + S + U = E`` aux
    arrondis près.
    """

    length_m: float
    grade: float
    start_s: float
    end_s: float
    moving_s: float
    stopped_s: float
    undetermined_s: float
    heart_rate_bpm: float | None
    truncated: bool = False

    @property
    def elapsed_s(self) -> float:
        """L'écoulé de l'intervalle, en secondes."""
        return self.end_s - self.start_s


@dataclass(frozen=True)
class ActivityIntervals:
    """Les intervalles d'une activité.

    - ``activity_ref`` — sans unité — l'identifiant de l'activité ;
    - ``elapsed_s`` — secondes — l'écoulé de la trace, du premier au dernier instant,
      plafond ignoré (``0017``, P2.3) ;
    - ``intervals`` — les intervalles gardés, dans l'ordre de la grille ;
    - ``ceiling_s`` — secondes — le plafond appliqué, ``None`` sans plafond ;
    - ``after_ceiling`` — sans unité — les intervalles retirés : ceux qui commencent au
      plafond ou après, et ceux que la coupe laisse sans longueur ;
    - ``after_ceiling_s`` — secondes — l'écoulé retiré au-delà du plafond.
    """

    activity_ref: str
    elapsed_s: float
    intervals: tuple[CurveInterval, ...]
    ceiling_s: float | None = None
    after_ceiling: int = 0
    after_ceiling_s: float = 0.0


def time_at_distance(
    distance_m: Sequence[float], time_s: Sequence[float], s: float
) -> float:
    """L'instant (secondes) où la distance réalisée atteint ``s`` (mètres), ``0017``,
    P1.3.

    Le premier enregistrement d'abscisse **strictement** supérieure à ``s`` et son
    prédécesseur, entre lesquels l'instant s'interpole linéairement : à abscisse égale
    (un arrêt), c'est donc le **dernier** instant qui compte. Au-delà de la dernière
    abscisse, le dernier instant.

    Précondition : ``distance_m`` croissante au sens large, de même longueur que
    ``time_s``, et ``s >= distance_m[0]``.
    """
    j = bisect_right(distance_m, s)
    if j >= len(distance_m):
        return time_s[-1]
    i = j - 1
    return time_s[i] + (s - distance_m[i]) / (distance_m[j] - distance_m[i]) * (
        time_s[j] - time_s[i]
    )


@dataclass(frozen=True)
class HeartRateSeries:
    """La FC d'un enregistrement, dans le temps de la trace, avec ses cumulés.

    - ``time_s`` — secondes — instants des échantillons, dans le temps de la trace ;
    - ``heart_rate_bpm`` — battements par minute — les échantillons ;
    - ``integral_bpm_s`` — battements (bpm·s) — intégrale cumulée aux instants, par
      trapèzes, des seuls pas reliés ;
    - ``covered_s`` — secondes — durée cumulée aux instants des seuls pas reliés.

    Un pas est relié s'il dure au plus :data:`MAX_HR_STEP_S` ; au-delà, c'est un trou,
    ni intégré ni couvert.
    """

    time_s: tuple[float, ...]
    heart_rate_bpm: tuple[float, ...]
    integral_bpm_s: tuple[float, ...]
    covered_s: tuple[float, ...]

    def _piece(self, i: int, u0: float, u1: float) -> tuple[float, float]:
        """L'intégrale exacte et la durée couverte du morceau ``[u0 ; u1]`` du pas
        ``i``."""
        t0, t1 = self.time_s[i], self.time_s[i + 1]
        if t1 - t0 > MAX_HR_STEP_S or u1 <= u0:
            return 0.0, 0.0
        v0, v1 = self.heart_rate_bpm[i], self.heart_rate_bpm[i + 1]
        slope = (v1 - v0) / (t1 - t0)
        a = v0 + slope * (u0 - t0)
        b = v0 + slope * (u1 - t0)
        return (a + b) / 2 * (u1 - u0), u1 - u0

    def mean(self, low: float, high: float, coverage: float) -> float | None:
        """La FC moyenne (bpm) de la fenêtre ``[low ; high]`` (secondes, temps de la
        trace) : l'intégrale **exacte** de la FC interpolée sur les pas reliés, un pas
        coupé par la fenêtre comptant pour sa partie dedans, divisée par la durée
        couverte — jamais par la durée de la fenêtre : un trou n'est pas une FC nulle
        (``0017``, P5.1).

        ``None`` si la fenêtre sort de la série ou est vide, si la durée couverte est
        nulle, ou si elle est sous ``coverage`` (fraction) de la fenêtre, à
        :data:`COVERAGE_TOLERANCE_S` près.
        """
        t = self.time_s
        if not (t[0] <= low and high <= t[-1] and high > low):
            return None
        first = bisect_right(t, low) - 1
        last = max(first, bisect_left(t, high) - 1)
        if first == last:
            integral, covered = self._piece(first, low, high)
        else:
            head_integral, head_covered = self._piece(first, low, t[first + 1])
            tail_integral, tail_covered = self._piece(last, t[last], high)
            integral = (
                head_integral
                + (self.integral_bpm_s[last] - self.integral_bpm_s[first + 1])
                + tail_integral
            )
            covered = (
                head_covered
                + (self.covered_s[last] - self.covered_s[first + 1])
                + tail_covered
            )
        if covered <= 0 or covered < coverage * (high - low) - COVERAGE_TOLERANCE_S:
            return None
        return integral / covered


def heart_rate_series(
    recording: ActivityRecording, offset_s: float
) -> HeartRateSeries | None:
    """La :class:`HeartRateSeries` de ``recording``, ses instants ramenés de
    ``offset_s`` secondes (l'origine de la trace) ; ``None`` sans canal de FC ou avec
    moins de deux échantillons."""
    channel = recording.heart_rate
    if channel is None or len(channel.time_s) < 2:
        return None
    time_s = tuple(t - offset_s for t in channel.time_s)
    values = tuple(channel.heart_rate_bpm)
    integral, covered = [0.0], [0.0]
    for j in range(1, len(time_s)):
        step = time_s[j] - time_s[j - 1]
        linked = step <= MAX_HR_STEP_S
        part = (values[j - 1] + values[j]) / 2 * step if linked else 0.0
        integral.append(integral[-1] + part)
        covered.append(covered[-1] + (step if linked else 0.0))
    return HeartRateSeries(time_s, values, tuple(integral), tuple(covered))


def _interpolate(xs: Sequence[float], ys: Sequence[float], x: float) -> float:
    """``ys`` interpolée linéairement en ``x`` sur ``xs`` (strictement croissants),
    prolongée par le premier ou le dernier pas hors de ``xs``."""
    i = max(0, min(bisect_right(xs, x) - 1, len(xs) - 2))
    return ys[i] + (x - xs[i]) / (xs[i + 1] - xs[i]) * (ys[i + 1] - ys[i])


def activity_intervals(
    recording: ActivityRecording,
    profile_parameters: ParameterSet,
    *,
    hr_lag_s: float,
    hr_min_coverage: float,
    max_elapsed_s: float | None = None,
) -> ActivityIntervals | TraceRefusal:
    """Les intervalles de ``recording`` sur la grille de son profil, ou le motif de
    leur absence (la chaîne de la docstring du module, dans cet ordre).

    ``hr_lag_s`` (secondes) décale la fenêtre de FC de chaque intervalle,
    ``hr_min_coverage`` (fraction) est la part qu'elle doit couvrir. Avec
    ``max_elapsed_s`` (secondes), le plafond est le premier instant de la trace plus
    ``max_elapsed_s`` : un intervalle qui commence au plafond ou après est retiré ;
    celui qui le traverse est coupé — sa longueur va jusqu'à la distance réalisée au
    plafond, sa fin au plafond, sa pente reste celle de l'intervalle du profil — et
    retiré si la coupe ne lui laisse aucune longueur. La FC d'un intervalle coupé se
    lit sur sa partie gardée, décalée : elle peut donc venir d'après le plafond.
    Une ``ProfileError`` donne « profil impossible » ; toute autre exception remonte.
    """
    view = trace_view(recording)
    if view is None:
        return TraceRefusal.NO_TRACE
    trace = view.trace
    try:
        profile = build_profile(
            Route(
                "vue",
                trace.latitude_deg,
                trace.longitude_deg,
                trace.elevation_m,
                (),
                recording.source,
            ),
            profile_parameters,
        )
    except ProfileError:
        return TraceRefusal.NO_PROFILE
    series = build_series(trace)
    partition = clock_partition(trace, series)
    states = partition.states[CENTRAL_CONVENTION_INDEX]
    time_s = trace.time_s
    clocks: dict[IntervalState, list[float]] = {state: [0.0] for state in IntervalState}
    for i, current in enumerate(states):
        step = time_s[i + 1] - time_s[i]
        for state, cumul in clocks.items():
            cumul.append(cumul[-1] + (step if current is state else 0.0))

    def clock(state: IntervalState, at_s: float) -> float:
        return _interpolate(time_s, clocks[state], at_s)

    d = series.realized_distance_m
    s = profile.distance_m
    z = profile.elevation_m
    bounds = [time_at_distance(d, time_s, s_k) for s_k in s]
    bounds[0] = time_s[0]
    bounds[-1] = time_s[-1]
    ceiling = None if max_elapsed_s is None else time_s[0] + max_elapsed_s
    heart_rate = heart_rate_series(recording, view.offset_s)
    intervals: list[CurveInterval] = []
    removed = 0
    for h in range(len(s) - 1):
        length = s[h + 1] - s[h]
        if length <= 0:
            continue
        a, b = bounds[h], bounds[h + 1]
        truncated = False
        if ceiling is not None:
            if a >= ceiling:
                removed += 1
                continue
            if b > ceiling:
                length = _interpolate(time_s, d, ceiling) - s[h]
                b = ceiling
                truncated = True
                if length <= 0:
                    removed += 1
                    continue
        mean_hr = (
            None
            if heart_rate is None
            else heart_rate.mean(a + hr_lag_s, b + hr_lag_s, hr_min_coverage)
        )
        intervals.append(
            CurveInterval(
                length_m=length,
                grade=(z[h + 1] - z[h]) / (s[h + 1] - s[h]),
                start_s=a,
                end_s=b,
                moving_s=clock(IntervalState.MOVING, b)
                - clock(IntervalState.MOVING, a),
                stopped_s=clock(IntervalState.STOPPED, b)
                - clock(IntervalState.STOPPED, a),
                undetermined_s=clock(IntervalState.UNDETERMINED, b)
                - clock(IntervalState.UNDETERMINED, a),
                heart_rate_bpm=mean_hr,
                truncated=truncated,
            )
        )
    after_s = 0.0 if ceiling is None else max(0.0, time_s[-1] - ceiling)
    return ActivityIntervals(
        recording.activity_ref,
        time_s[-1] - time_s[0],
        tuple(intervals),
        max_elapsed_s,
        removed,
        after_s,
    )
