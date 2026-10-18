"""Les montées d'une activité : détectées sur le profil du moteur, bornées et
mesurées en temps, sur les horloges de ``0010`` D5 (AN1-2, ``docs/decisions/0014``).

La chaîne, dans cet ordre :

1. la vue positions et altitude de l'enregistrement (``stream_view``), ses blocs, son
   altitude lissée ``z̃`` et sa partition M/S/U sous les cinq conventions (``0010`` D4.4,
   D5), dans une :class:`MotionTrack` ;
2. le profil du moteur (``build_profile``, défauts de ``0008``) sur les mêmes positions
   et altitudes ; l'instant de chaque point de grille par interpolation sur l'abscisse ;
3. l'hystérésis sur l'altitude du profil, lissée (une contre-pente de moins de
   ``hysteresis_m`` sur le profil lissé reste dans la montée ; le lissage atténue une
   contre-pente courte et raide, qui peut être plus profonde sur le terrain) ; une
   montée dont le gain du profil n'atteint pas ``min_profile_gain_fraction`` fois
   ``min_gain_m`` est écartée (détection relâchée : le lissage rabote les côtes
   courtes, dont le gain se juge en temps à l'étape 6) ;
4. les replats : une suite de pas de grille de pente inférieure à ``flat_grade`` est
   candidate si la distance parcourue en mouvement pendant elle atteint
   ``flat_length_m − (w_eff − h)``, à l'arrondi près (un écart relatif d'au plus
   ``CLOCK_THRESHOLD_RELATIVE_TOLERANCE`` vaut égalité, comme en ``0010`` D5.2 : aux
   défauts, ce seuil vaut trois pas de grille, qu'un replat parcouru tout entier en
   mouvement atteint au dernier chiffre près) ; elle coupe si son temps en mouvement
   dépasse ``flat_time_ratio`` fois celui du plus court des deux morceaux qu'elle
   sépare, les fusions se faisant du replat le plus léger au plus lourd ;
5. les bornes : sur le profil, le dernier point à ``bound_tolerance_m`` du minimum et le
   premier à ``bound_tolerance_m`` du maximum ; en temps, sur ``z̃``, parmi les
   enregistrements à moins de ``w_eff`` de chaque borne, le dernier instant à la
   tolérance du minimum et le premier à la tolérance du maximum ; puis un replat, même
   montant, reste hors de la montée : la borne de départ avance tant que ``z̃`` monte de
   moins de ``flat_grade`` sur le pas de grille de ``d_r`` qui la suit, et se place,
   dans le premier pas qui monte d'au moins autant, au dernier instant à la tolérance
   du minimum de ce pas ; la borne d'arrivée recule de même, au premier instant à la
   tolérance du maximum de son pas. Le gain ``G`` est le maximum moins le minimum de
   ``z̃`` là où les bornes se sont placées (les fenêtres, ou ces pas) ;
6. les filtres, sur les mesures : ``G`` d'au moins
   ``max(min_gain_m ; min_climb_steps × pas × max_sustained_vertical_speed_ms)``,
   le pas étant l'intervalle médian de la montée ; une longueur parcourue en M
   positive ; une pente au-dessus de ``min_grade``, lue sur toute la montée et sur un
   seul support : ``z̃(t_b*) − z̃(t_a*)`` divisée par la distance réalisée ``d_r``
   entre les mêmes instants, trous compris. Une montée dont le gain est pris en partie
   hors de M reste donc dans la table ; un drapeau la marque quand cette part dépasse
   son seuil, ou quand sa pente en M ne dépasse plus la pente minimale
   (``quality.py``). Une montée sans aucune longueur parcourue en M (tout son gain
   dans un trou) est écartée, et le D+ du canal pendant les trous reste dans la table
   ``activites`` ;
7. les mesures (:class:`ClimbMeasure`) : l'horloge du gain ``G_X,θ`` (somme des
   variations de ``z̃`` sur les intervalles d'état X sous θ), la VAM principale
   ``G_M,θc / M_θc``, sa variante ``(G_M + G_U) / (M + U)`` et leur enveloppe sur les
   cinq conventions ; le temps M lent : les intervalles M (θc) dont la fenêtre de
   ``0010`` D5 a une vitesse verticale et une vitesse horizontale au plus
   ``slow_max_vertical_speed_ms`` et ``slow_max_horizontal_speed_ms`` (comparaisons
   brutes, sans la tolérance d'arrondi de D5.2).

Python pur : ce module ne demande aucun extra.
"""

from __future__ import annotations

import math
from bisect import bisect_left, bisect_right
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import timedelta
from statistics import median

from mountain_perf.clocks import (
    CLOCK_THRESHOLD_RELATIVE_TOLERANCE,
    clock_partition,
    window_measures,
)
from mountain_perf.gpx.geo import deduplicated_polyline, haversine_m
from mountain_perf.gpx.profile import (
    PROFILE_PARAMETER_SPECS,
    build_profile_with_diagnostics,
)
from mountain_perf.ingest.views import stream_view
from mountain_perf.schemas import (
    CENTRAL_CONVENTION_INDEX,
    CLOCK_CONVENTIONS,
    ActivityRecording,
    IntervalState,
    ParameterSet,
    ParameterSpec,
    RecordedTrace,
    Route,
    SourceRef,
)
from mountain_perf.series import build_series

CLIMB_PARAMETER_SPECS: tuple[ParameterSpec, ...] = (
    ParameterSpec(
        "hysteresis_m", "m", 10.0, 1.0, 100.0, "Contre-pente tolérée dans une montée."
    ),
    ParameterSpec(
        "flat_grade",
        None,
        0.02,
        0.0,
        0.05,
        "Pente sous laquelle un pas du profil est plat.",
    ),
    ParameterSpec(
        "flat_length_m",
        "m",
        250.0,
        0.0,
        5000.0,
        "Longueur vraie, parcourue en mouvement, d'un replat qui peut couper une"
        " montée.",
    ),
    ParameterSpec(
        "flat_time_ratio",
        None,
        0.10,
        0.0,
        10.0,
        "Un replat coupe si son temps en mouvement dépasse ce rapport au temps du"
        " plus court morceau voisin.",
    ),
    ParameterSpec(
        "bound_tolerance_m",
        "m",
        1.0,
        0.0,
        10.0,
        "Tolérance des bornes au minimum et au maximum de l'altitude.",
    ),
    ParameterSpec("min_gain_m", "m", 20.0, 1.0, 1000.0, "Gain minimal d'une montée."),
    ParameterSpec(
        "min_profile_gain_fraction",
        None,
        0.5,
        0.0,
        1.0,
        "Part de min_gain_m que le gain du profil lissé doit atteindre pour qu'une"
        " montée détectée soit mesurée (détection relâchée : le lissage rabote les"
        " côtes courtes, dont le gain se juge ensuite en temps).",
    ),
    ParameterSpec(
        "max_sustained_vertical_speed_ms",
        "m/s",
        2000.0 / 3600.0,
        0.1,
        3.0,
        "Vitesse ascensionnelle soutenue de très haut niveau : le gain minimal"
        " couvre au moins min_climb_steps pas à cette vitesse.",
    ),
    ParameterSpec(
        "min_climb_steps",
        None,
        30.0,
        1.0,
        1000.0,
        "Nombre de pas d'échantillonnage qu'une montée dure au moins, même à la"
        " vitesse soutenue de très haut niveau (erreur de durée bornée par le pas).",
    ),
    ParameterSpec(
        "min_grade",
        None,
        0.05,
        0.0,
        1.0,
        "Pente moyenne minimale (la valeur du seuil « montée » de 0010 D6).",
    ),
    ParameterSpec(
        "slow_max_vertical_speed_ms",
        "m/s",
        0.03,
        0.0,
        1.0,
        "Un intervalle M est lent si la vitesse verticale de sa fenêtre est au plus"
        " celle-ci (le seuil vertical de θc).",
    ),
    ParameterSpec(
        "slow_max_horizontal_speed_ms",
        "m/s",
        0.30,
        0.0,
        5.0,
        "Et si la vitesse horizontale de sa fenêtre est au plus celle-ci (trois fois"
        " le seuil horizontal de θc).",
    ),
)
"""Les paramètres de la définition de la montée (``docs/decisions/0014``)."""


@dataclass(frozen=True)
class MotionTrack:
    """La vue positions et altitude d'un enregistrement, avec ses horloges.

    Les temps ``time_s`` partent du premier instant de la vue (``offset_s`` après le
    départ de l'enregistrement) ; ``recording_time_s`` garde les instants de
    l'enregistrement, ceux des canaux, pour les y lire à l'égalité exacte. Les cumuls
    ont une valeur par instant ; entre deux instants, ils s'interpolent linéairement
    (``0010`` D5.3) :

    - ``distance_m`` : ``d_r``, la distance réalisée des positions brutes, trous
      compris ;
    - ``time_in_state_s``, ``gain_in_state_m`` : par (convention, état), le temps et la
      variation de ``z̃`` des intervalles de cet état ;
    - ``moving_distance_m`` : la distance des intervalles M (θc) ;
    - ``slow_moving_s`` : le temps des intervalles M (θc) lents (``slow_max_*`` de
      :data:`CLIMB_PARAMETER_SPECS`) ;
    - ``gap_gain_m`` : la variation de ``z̃`` des intervalles de trou ;
    - ``moving_elevation_integral`` : ``z̃`` intégrée sur les intervalles M (θc), en
      mètres-secondes (trapèzes).
    """

    offset_s: float
    time_s: tuple[float, ...]
    recording_time_s: tuple[float, ...]
    latitude_deg: tuple[float, ...]
    longitude_deg: tuple[float, ...]
    elevation_m: tuple[float, ...]
    smoothed_elevation_m: tuple[float, ...]
    distance_m: tuple[float, ...]
    time_in_state_s: dict[tuple[int, IntervalState], tuple[float, ...]]
    gain_in_state_m: dict[tuple[int, IntervalState], tuple[float, ...]]
    moving_distance_m: tuple[float, ...]
    slow_moving_s: tuple[float, ...]
    gap_gain_m: tuple[float, ...]
    moving_elevation_integral: tuple[float, ...]
    gap_after: tuple[bool, ...]
    states: tuple[tuple[IntervalState, ...], ...]
    source: SourceRef


def _cumulate(values: Sequence[float]) -> tuple[float, ...]:
    out, total = [0.0], 0.0
    for value in values:
        total += value
        out.append(total)
    return tuple(out)


def motion_track(
    recording: ActivityRecording, climb: ParameterSet | None = None
) -> MotionTrack | None:
    """La :class:`MotionTrack` de ``recording`` ; ``None`` sans vue positions et
    altitude, ou si elle a moins de deux instants. ``climb`` donne les seuils du temps
    M lent (défauts de :data:`CLIMB_PARAMETER_SPECS`)."""
    climb = climb or ParameterSet(CLIMB_PARAMETER_SPECS)
    stream = stream_view(recording, elevation=True).stream
    if stream is None or len(stream.time_s) < 2 or stream.elevation_m is None:
        return None
    lat = tuple(stream.latitude_deg or ())
    lon = tuple(stream.longitude_deg or ())
    z = tuple(stream.elevation_m)
    offset = stream.time_s[0]
    time_s = tuple(t - offset for t in stream.time_s)
    start = recording.start_time + timedelta(seconds=offset)
    trace = RecordedTrace(start, time_s, lat, lon, z, (recording.source,), 0)
    series = build_series(trace)
    partition = clock_partition(trace, series)
    zs = series.smoothed_elevation_m
    steps = [time_s[i + 1] - time_s[i] for i in range(len(time_s) - 1)]
    rises = [zs[i + 1] - zs[i] for i in range(len(time_s) - 1)]
    time_in: dict[tuple[int, IntervalState], tuple[float, ...]] = {}
    gain_in: dict[tuple[int, IntervalState], tuple[float, ...]] = {}
    for k, states in enumerate(partition.states):
        for state in IntervalState:
            time_in[(k, state)] = _cumulate(
                [d if s is state else 0.0 for d, s in zip(steps, states, strict=True)]
            )
            gain_in[(k, state)] = _cumulate(
                [r if s is state else 0.0 for r, s in zip(rises, states, strict=True)]
            )
    moving = partition.states[CENTRAL_CONVENTION_INDEX]
    distance: list[float] = []
    slow: list[float] = []
    elevation_time: list[float] = []
    for i, state in enumerate(moving):
        if state is IntervalState.MOVING:
            distance.append(haversine_m(lat[i], lon[i], lat[i + 1], lon[i + 1]))
            elevation_time.append((zs[i] + zs[i + 1]) / 2 * steps[i])
            window = window_measures(trace, series, i)
            is_slow = (
                window is not None
                and window.v_z <= climb["slow_max_vertical_speed_ms"]
                and window.v_h <= climb["slow_max_horizontal_speed_ms"]
            )
            slow.append(steps[i] if is_slow else 0.0)
        else:
            distance.append(0.0)
            slow.append(0.0)
            elevation_time.append(0.0)
    gaps = [r if gap else 0.0 for r, gap in zip(rises, series.gap_after, strict=True)]
    return MotionTrack(
        offset_s=offset,
        time_s=time_s,
        recording_time_s=tuple(stream.time_s),
        latitude_deg=lat,
        longitude_deg=lon,
        elevation_m=z,
        smoothed_elevation_m=zs,
        distance_m=series.realized_distance_m,
        time_in_state_s=time_in,
        gain_in_state_m=gain_in,
        moving_distance_m=_cumulate(distance),
        slow_moving_s=_cumulate(slow),
        gap_gain_m=_cumulate(gaps),
        moving_elevation_integral=_cumulate(elevation_time),
        gap_after=series.gap_after,
        states=partition.states,
        source=recording.source,
    )


def interpolate(xs: Sequence[float], ys: Sequence[float], x: float) -> float:
    """``ys`` interpolée linéairement en ``x`` sur ``xs`` (croissants au sens large),
    prolongée par le premier ou le dernier intervalle hors de ``xs``. Une abscisse
    répétée est un saut : en elle, la valeur la plus à droite ; un premier ou un
    dernier intervalle de longueur nulle rend sa valeur de gauche, prolongée au-delà
    du bout."""
    i = max(0, min(bisect_right(xs, x) - 1, len(xs) - 2))
    if xs[i + 1] == xs[i]:
        return ys[i]
    return ys[i] + (x - xs[i]) / (xs[i + 1] - xs[i]) * (ys[i + 1] - ys[i])


def _at(track: MotionTrack, values: Sequence[float], at_s: float) -> float:
    return interpolate(track.time_s, values, at_s)


def _between(
    track: MotionTrack, values: Sequence[float], start_s: float, end_s: float
) -> float:
    return _at(track, values, end_s) - _at(track, values, start_s)


def state_time_s(
    track: MotionTrack,
    convention: int,
    state: IntervalState,
    start_s: float,
    end_s: float,
) -> float:
    """Temps passé dans ``state`` sous la convention ``convention`` sur
    ``[start_s ; end_s]`` (``0010`` D5.3)."""
    return _between(track, track.time_in_state_s[(convention, state)], start_s, end_s)


def state_gain_m(
    track: MotionTrack,
    convention: int,
    state: IntervalState,
    start_s: float,
    end_s: float,
) -> float:
    """L'horloge du gain : variation de ``z̃`` sur les intervalles de ``state`` sous
    ``convention``, intervalles partiels aux bornes. Les trois états somment
    ``z̃(end) − z̃(start)``."""
    return _between(track, track.gain_in_state_m[(convention, state)], start_s, end_s)


@dataclass(frozen=True)
class ClimbSpan:
    """Une montée trouvée : ses bornes en temps (depuis le premier instant de la vue),
    son gain ``G``, les abscisses de ses bornes sur le profil et trois gains de
    diagnostic entre ces abscisses : celui du profil lissé, celui de la grille non
    lissée, et le D+ cumulé du profil lissé (jamais au numérateur de la VAM)."""

    start_s: float
    end_s: float
    gain_m: float
    profile_start_m: float
    profile_end_m: float
    profile_gain_m: float
    raw_profile_gain_m: float
    profile_ascent_m: float


def _zigzag(z: Sequence[float], hysteresis: float) -> list[tuple[int, int]]:
    """Les montées de ``z`` à l'hystérésis ``hysteresis`` (étape 3), en paires
    d'indices ``(bas, haut)`` dans l'ordre : une montée part du point le plus bas
    atteint depuis le début ou depuis la fin de la précédente, quand l'altitude le
    dépasse d'au moins ``hysteresis`` ; elle finit à son point le plus haut, quand
    l'altitude redescend d'au moins ``hysteresis`` sous lui. À égalité, le premier
    point bas et le premier point haut ; une montée en cours à la fin compte."""
    climbs: list[tuple[int, int]] = []
    low = high = 0
    rising = False
    for i in range(1, len(z)):
        if not rising:
            if z[i] < z[low]:
                low = i
            elif z[i] - z[low] >= hysteresis:
                rising, high = True, i
        elif z[i] > z[high]:
            high = i
        elif z[high] - z[i] >= hysteresis:
            climbs.append((low, high))
            rising, low = False, i
    if rising:
        climbs.append((low, high))
    return climbs


@dataclass
class _Piece:
    first: int
    last: int
    span: ClimbSpan | None = None


def _profile_bounds(
    z: Sequence[float], first: int, last: int, tolerance: float
) -> tuple[int, int]:
    top_value = max(z[first : last + 1])
    top = next(i for i in range(first, last + 1) if z[i] >= top_value - tolerance)
    bottom_value = min(z[first : top + 1])
    bottom = max(i for i in range(first, top + 1) if z[i] <= bottom_value + tolerance)
    return bottom, top


def _lowest(
    zs: Sequence[float], lo: int, hi: int, tolerance: float
) -> tuple[int, float]:
    """Le dernier indice de ``[lo ; hi]`` à ``tolerance`` du minimum de ``zs``, et ce
    minimum."""
    low = min(zs[lo : hi + 1])
    return max(i for i in range(lo, hi + 1) if zs[i] <= low + tolerance), low


def _highest(
    zs: Sequence[float], lo: int, hi: int, tolerance: float
) -> tuple[int, float]:
    """Le premier indice de ``[lo ; hi]`` à ``tolerance`` du maximum de ``zs``, et ce
    maximum."""
    high = max(zs[lo : hi + 1])
    return min(i for i in range(lo, hi + 1) if zs[i] >= high - tolerance), high


def _time_bounds(
    track: MotionTrack,
    start_m: float,
    end_m: float,
    window_m: float,
    tolerance: float,
    step_m: float,
    flat_grade: float,
) -> tuple[float, float, float] | None:
    d, zs = track.distance_m, track.smoothed_elevation_m
    a0, a1 = bisect_left(d, start_m - window_m), bisect_right(d, start_m + window_m)
    b0, b1 = bisect_left(d, end_m - window_m), bisect_right(d, end_m + window_m)
    if a1 <= a0 or b1 <= b0:
        return None
    start, low = _lowest(zs, a0, a1 - 1, tolerance)
    end, high = _highest(zs, b0, b1 - 1, tolerance)
    first, rise = start, end
    while first < end:
        j = bisect_left(d, d[first] + step_m, first + 1, end)
        if zs[j] - zs[first] >= flat_grade * (d[j] - d[first]):
            rise = j
            break
        first += 1
    if first > start:
        start, low = _lowest(zs, first, rise, tolerance)
    last, rise = end, start
    while last > start:
        j = bisect_right(d, d[last] - step_m, start + 1, last) - 1
        if zs[last] - zs[j] >= flat_grade * (d[last] - d[j]):
            rise = j
            break
        last -= 1
    if last < end:
        end, high = _highest(zs, rise, last, tolerance)
    if track.time_s[end] <= track.time_s[start]:
        return None
    return track.time_s[start], track.time_s[end], high - low


def _settle(
    track: MotionTrack,
    grid: Sequence[float],
    z: Sequence[float],
    raw_z: Sequence[float],
    piece: _Piece,
    climb: ParameterSet,
    window_m: float,
    step_m: float,
) -> _Piece:
    bottom, top = _profile_bounds(
        z, piece.first, piece.last, climb["bound_tolerance_m"]
    )
    if top <= bottom:
        piece.span = None
        return piece
    bounds = _time_bounds(
        track,
        grid[bottom],
        grid[top],
        window_m,
        climb["bound_tolerance_m"],
        step_m,
        climb["flat_grade"],
    )
    if bounds is None:
        piece.span = None
        return piece
    ascent = math.fsum(max(0.0, z[i + 1] - z[i]) for i in range(bottom, top))
    piece.span = ClimbSpan(
        bounds[0],
        bounds[1],
        bounds[2],
        grid[bottom],
        grid[top],
        z[top] - z[bottom],
        raw_z[top] - raw_z[bottom],
        ascent,
    )
    return piece


def _moving_s(track: MotionTrack, start_s: float, end_s: float) -> float:
    if end_s <= start_s:
        return 0.0
    return state_time_s(
        track, CENTRAL_CONVENTION_INDEX, IntervalState.MOVING, start_s, end_s
    )


def track_route(track: MotionTrack) -> Route:
    """La vue de ``track`` comme tracé, pour le profil du moteur."""
    return Route(
        "vue",
        track.latitude_deg,
        track.longitude_deg,
        track.elevation_m,
        (),
        track.source,
    )


def detect_climbs(
    track: MotionTrack, profile: ParameterSet, climb: ParameterSet
) -> tuple[ClimbSpan, ...]:
    """Les montées de ``track``, dans l'ordre du temps (étapes 2 à 5 du module) ;
    aucune si la vue a moins de deux positions distinctes ou moins de deux pas de
    grille de long."""
    route = track_route(track)
    polyline = deduplicated_polyline(track.latitude_deg, track.longitude_deg)
    if (
        len(polyline.indices) < 2
        or polyline.distance_m[-1] < 2 * profile["grid_step_m"]
    ):
        return ()
    built = build_profile_with_diagnostics(route, profile)
    grid, z = built.profile.distance_m, built.profile.elevation_m
    unsmoothed = ParameterSet(
        PROFILE_PARAMETER_SPECS, {**profile.values, "smoothing_window_m": 0.0}
    )
    raw_z = build_profile_with_diagnostics(route, unsmoothed).profile.elevation_m
    times = [track.time_s[i] for i in polyline.indices]
    grid_time = [interpolate(polyline.distance_m, times, s) for s in grid]
    window_m = built.effective_smoothing_window_m
    flat_threshold_m = climb["flat_length_m"] - (window_m - profile["grid_step_m"])
    flat_reached_m = (1 - CLOCK_THRESHOLD_RELATIVE_TOLERANCE) * flat_threshold_m
    spans: list[ClimbSpan] = []
    for low, high in _zigzag(z, climb["hysteresis_m"]):
        if z[high] - z[low] < climb["min_gain_m"] * climb["min_profile_gain_fraction"]:
            continue
        cuts: list[int] = [low]
        h = low
        while h < high:
            if (z[h + 1] - z[h]) / (grid[h + 1] - grid[h]) < climb["flat_grade"]:
                k = h
                while (
                    k < high
                    and (z[k + 1] - z[k]) / (grid[k + 1] - grid[k])
                    < climb["flat_grade"]
                ):
                    k += 1
                if (
                    _between(track, track.moving_distance_m, grid_time[h], grid_time[k])
                    >= flat_reached_m
                ):
                    cuts += [h, k]
                h = k
            else:
                h += 1
        cuts.append(high)
        pieces = [
            _settle(
                track,
                grid,
                z,
                raw_z,
                _Piece(cuts[2 * i], cuts[2 * i + 1]),
                climb,
                window_m,
                profile["grid_step_m"],
            )
            for i in range(len(cuts) // 2)
        ]
        pieces = [p for p in pieces if p.span is not None]
        while len(pieces) > 1:
            best, best_ratio = 0, math.inf
            for i in range(len(pieces) - 1):
                left, right = pieces[i].span, pieces[i + 1].span
                assert left is not None
                assert right is not None
                shortest = min(
                    _moving_s(track, left.start_s, left.end_s),
                    _moving_s(track, right.start_s, right.end_s),
                )
                ratio = (
                    _moving_s(track, left.end_s, right.start_s) / shortest
                    if shortest > 0
                    else math.inf
                )
                if ratio < best_ratio:
                    best, best_ratio = i, ratio
            if best_ratio > climb["flat_time_ratio"]:
                break
            merged = _settle(
                track,
                grid,
                z,
                raw_z,
                _Piece(pieces[best].first, pieces[best + 1].last),
                climb,
                window_m,
                profile["grid_step_m"],
            )
            if merged.span is None:
                break
            pieces[best : best + 2] = [merged]
        spans += [p.span for p in pieces if p.span is not None]
    return tuple(sorted(spans, key=lambda s: s.start_s))


@dataclass(frozen=True)
class ClimbMeasure:
    """Les mesures d'une montée retenue. Temps en secondes depuis le premier instant
    de la vue ; les champs en tuple ont une valeur par convention de
    ``CLOCK_CONVENTIONS``, dans son ordre."""

    span: ClimbSpan
    step_s: float
    longest_step_s: float
    moving_distance_m: float
    moving_s: tuple[float, ...]
    stopped_s: tuple[float, ...]
    undetermined_s: tuple[float, ...]
    moving_gain_m: tuple[float, ...]
    stopped_gain_m: tuple[float, ...]
    undetermined_gain_m: tuple[float, ...]
    gap_gain_m: float
    slow_moving_s: float
    net_displacement_m: float
    max_vertical_rate_ms: float
    low_elevation_m: float
    high_elevation_m: float
    moving_mean_elevation_m: float | None

    @property
    def elapsed_s(self) -> float:
        """Écoulé ``E = t_b − t_a``."""
        return self.span.end_s - self.span.start_s

    @property
    def grade(self) -> float:
        """``G_M,θc / L_M`` : le gain et la longueur des mêmes intervalles M."""
        return self.moving_gain_m[CENTRAL_CONVENTION_INDEX] / self.moving_distance_m

    @property
    def sinuosity(self) -> float | None:
        """``L_M`` divisée par le déplacement net entre les bornes ; ``None`` si les
        deux bornes sont confondues."""
        if self.net_displacement_m <= 0:
            return None
        return self.moving_distance_m / self.net_displacement_m

    @property
    def vertical_speed_by_convention_ms(self) -> tuple[float | None, ...]:
        """``G_M,θ / M_θ`` pour chaque convention ; ``None`` sans temps en
        mouvement."""
        return tuple(
            g / m if m > 0 else None
            for g, m in zip(self.moving_gain_m, self.moving_s, strict=True)
        )

    @property
    def vertical_speed_ms(self) -> float | None:
        """VAM principale, ``G_M,θc / M_θc`` ; ``None`` sans temps en mouvement."""
        return self.vertical_speed_by_convention_ms[CENTRAL_CONVENTION_INDEX]

    @property
    def moving_or_undetermined_vertical_speed_by_convention_ms(
        self,
    ) -> tuple[float | None, ...]:
        """La variante ``(G_M,θ + G_U,θ) / (M_θ + U_θ)`` pour chaque convention."""
        out: list[float | None] = []
        for k in range(len(self.moving_s)):
            time_s = self.moving_s[k] + self.undetermined_s[k]
            gain_m = self.moving_gain_m[k] + self.undetermined_gain_m[k]
            out.append(gain_m / time_s if time_s > 0 else None)
        return tuple(out)

    @property
    def moving_or_undetermined_vertical_speed_ms(self) -> float | None:
        """La variante sous la convention centrale."""
        return self.moving_or_undetermined_vertical_speed_by_convention_ms[
            CENTRAL_CONVENTION_INDEX
        ]

    @property
    def vertical_speed_envelope_ms(self) -> tuple[float, float] | None:
        """Le plus petit et le plus grand de la VAM principale et de sa variante sur
        les cinq conventions (dix valeurs) ; ``None`` si aucune n'existe."""
        values = [
            v
            for v in (
                *self.vertical_speed_by_convention_ms,
                *self.moving_or_undetermined_vertical_speed_by_convention_ms,
            )
            if v is not None
        ]
        return (min(values), max(values)) if values else None

    @property
    def outside_moving_gain_fraction(self) -> float | None:
        """Part du gain de l'horloge pris hors de M sous θc,
        ``(G_S + G_U) / (G_M + G_S + G_U)`` ; ``None`` si ce total n'est pas
        positif."""
        k = CENTRAL_CONVENTION_INDEX
        moving = self.moving_gain_m[k]
        other = self.stopped_gain_m[k] + self.undetermined_gain_m[k]
        total = moving + other
        return other / total if total > 0 else None

    @property
    def slow_moving_fraction(self) -> float | None:
        """Temps M lent rapporté à ``M_θc`` ; ``None`` sans temps en mouvement."""
        m = self.moving_s[CENTRAL_CONVENTION_INDEX]
        return self.slow_moving_s / m if m > 0 else None

    @property
    def moving_horizontal_speed_ms(self) -> float | None:
        """``L_M / M_θc`` ; ``None`` sans temps en mouvement."""
        m = self.moving_s[CENTRAL_CONVENTION_INDEX]
        return self.moving_distance_m / m if m > 0 else None


def measure_climb(
    track: MotionTrack, span: ClimbSpan, climb: ParameterSet
) -> ClimbMeasure | None:
    """Les mesures de ``span`` ; ``None`` si elle ne passe pas les filtres (étape 6).
    Les bornes de ``span`` sont des instants de ``track``, comme celles que donne
    :func:`detect_climbs`."""
    t = track.time_s
    first, last = bisect_right(t, span.start_s) - 1, bisect_left(t, span.end_s)
    steps = [t[i + 1] - t[i] for i in range(max(first, 0), min(last, len(t) - 1))]
    step = median(steps)
    minimum_gain = max(
        climb["min_gain_m"],
        climb["min_climb_steps"] * step * climb["max_sustained_vertical_speed_ms"],
    )
    distance = _between(track, track.moving_distance_m, span.start_s, span.end_s)
    rise = _between(track, track.smoothed_elevation_m, span.start_s, span.end_s)
    length = _between(track, track.distance_m, span.start_s, span.end_s)
    if (
        span.gain_m < minimum_gain
        or distance <= 0
        or length <= 0
        or rise / length <= climb["min_grade"]
    ):
        return None
    k_all = range(len(CLOCK_CONVENTIONS))

    def per(state: IntervalState, gain: bool) -> tuple[float, ...]:
        f = state_gain_m if gain else state_time_s
        return tuple(f(track, k, state, span.start_s, span.end_s) for k in k_all)

    lat0, lon0 = (
        _at(track, track.latitude_deg, span.start_s),
        _at(track, track.longitude_deg, span.start_s),
    )
    lat1, lon1 = (
        _at(track, track.latitude_deg, span.end_s),
        _at(track, track.longitude_deg, span.end_s),
    )
    z = track.elevation_m
    inside = range(max(first, 0), min(last, len(t) - 1))
    rates = [abs(z[i + 1] - z[i]) / (t[i + 1] - t[i]) for i in inside]
    zs = track.smoothed_elevation_m
    zs_inside = [_at(track, zs, span.start_s), _at(track, zs, span.end_s)]
    zs_inside += [zs[i] for i in range(max(first + 1, 0), min(last, len(t)))]
    moving_central = state_time_s(
        track, CENTRAL_CONVENTION_INDEX, IntervalState.MOVING, span.start_s, span.end_s
    )
    elevation_time = _between(
        track, track.moving_elevation_integral, span.start_s, span.end_s
    )
    return ClimbMeasure(
        span=span,
        step_s=step,
        longest_step_s=max(steps),
        moving_distance_m=distance,
        moving_s=per(IntervalState.MOVING, gain=False),
        stopped_s=per(IntervalState.STOPPED, gain=False),
        undetermined_s=per(IntervalState.UNDETERMINED, gain=False),
        moving_gain_m=per(IntervalState.MOVING, gain=True),
        stopped_gain_m=per(IntervalState.STOPPED, gain=True),
        undetermined_gain_m=per(IntervalState.UNDETERMINED, gain=True),
        gap_gain_m=_between(track, track.gap_gain_m, span.start_s, span.end_s),
        slow_moving_s=_between(track, track.slow_moving_s, span.start_s, span.end_s),
        net_displacement_m=haversine_m(lat0, lon0, lat1, lon1),
        max_vertical_rate_ms=max(rates, default=0.0),
        low_elevation_m=min(zs_inside),
        high_elevation_m=max(zs_inside),
        moving_mean_elevation_m=(
            elevation_time / moving_central if moving_central > 0 else None
        ),
    )


def climbs(
    track: MotionTrack,
    profile: ParameterSet | None = None,
    climb: ParameterSet | None = None,
) -> tuple[ClimbMeasure, ...]:
    """Les montées retenues de ``track`` et leurs mesures, aux paramètres donnés
    (défauts de ``0008`` et de :data:`CLIMB_PARAMETER_SPECS`)."""
    profile = profile or ParameterSet(PROFILE_PARAMETER_SPECS)
    climb = climb or ParameterSet(CLIMB_PARAMETER_SPECS)
    out: list[ClimbMeasure] = []
    for span in detect_climbs(track, profile, climb):
        measure = measure_climb(track, span, climb)
        if measure is not None:
            out.append(measure)
    return tuple(out)
