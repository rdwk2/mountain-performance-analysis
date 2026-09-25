"""Fixtures synthétiques des segments (M4a-2b) — plan à 45° N, valeurs inventées.

Convention du § 7.0 des briefs M4a-2a et M4a-2b : références et traces décrites en
mètres ``(x, y)``, converties par :func:`fixtures.traces.local_deg`. Les lignes du
§ 7.2b reprises de M4a-2a sont construites par ``fixtures.matching`` ; ce module
ajoute l'altitude des références, les profils écrits à la main, les lieux nommés,
les enregistrements immobiles et un constructeur par ligne neuve du § 7.2b.

Utilisées par ``tests/test_backtest_segment_rules.py``,
``tests/test_backtest_segments.py`` et ``tests/test_backtest_segments_properties.py``.
"""

import math
from collections.abc import Sequence
from dataclasses import replace
from itertools import pairwise

from fixtures.matching import (
    EAST_510,
    REFERENCE_SOURCE,
    MatchCase,
    Point,
    TracePath,
    local_trace,
    matching_parameters,
    reference_route,
)
from fixtures.traces import local_deg
from mountain_perf.backtest import build_series, observe_segment
from mountain_perf.gpx import PROFILE_PARAMETER_SPECS, build_profile
from mountain_perf.schemas import (
    NamedPoint,
    ParameterSet,
    Route,
    RouteProfile,
    ScorePointObservation,
    ScoreSegmentObservation,
)

ElevatedPoint = tuple[float, float, float]
"""Un sommet ``(x, y, z)`` : mètres vers l'est, vers le nord, altitude."""


def elevated_route(*vertices: ElevatedPoint) -> Route:
    """Référence de sommets ``(x, y, z)``, sans lieu nommé."""
    positions = [local_deg(x_m, y_m) for x_m, y_m, _ in vertices]
    return Route(
        name="Référence synthétique à altitude",
        latitude_deg=tuple(lat for lat, _ in positions),
        longitude_deg=tuple(lon for _, lon in positions),
        elevation_m=tuple(z_m for _, _, z_m in vertices),
        named_points=(),
        source=REFERENCE_SOURCE,
    )


def hand_profile(
    distance_m: Sequence[float], elevation_m: Sequence[float]
) -> RouteProfile:
    """``RouteProfile`` écrit à la main : grille et altitudes données telles quelles."""
    return RouteProfile(
        route_name="Profil écrit à la main",
        source=REFERENCE_SOURCE,
        distance_m=tuple(distance_m),
        elevation_m=tuple(elevation_m),
        resolved_points=(),
        step_m=50.0,
        build_parameters=ParameterSet(PROFILE_PARAMETER_SPECS),
    )


def reference_profile(case: MatchCase) -> RouteProfile:
    """Profil de la référence d'un cas, aux défauts de ``0008`` (``0010`` D4.1)."""
    return build_profile(case.route, ParameterSet(PROFILE_PARAMETER_SPECS))


def observed(
    case: MatchCase,
) -> tuple[tuple[ScorePointObservation, ...], tuple[ScoreSegmentObservation, ...]]:
    """Points de ``match_points``, puis un ``observe_segment`` par couple de points
    consécutifs."""
    points = case.match()
    series = build_series(case.trace)
    geometry, profile = case.geometry, reference_profile(case)
    tolerance_m = case.parameters["lateral_tolerance_m"]
    segments = tuple(
        observe_segment(geometry, profile, case.trace, series, a, b, tolerance_m)
        for a, b in pairwise(points)
    )
    return points, segments


# ---------------------------------------------------------------------------
# Aides de construction
# ---------------------------------------------------------------------------


def regime_route(breaks: Sequence[tuple[float, float]], length_m: float) -> Route:
    """§ 7.0 de M4a-2b : référence vers l'est sur le parallèle de base, un sommet tous
    les 10 m (``x = 10·i``, produit calculé à chaque rang), altitude de chaque sommet
    par interpolation linéaire entre les cassures ``(x ; z)``."""

    def altitude(x_m: float) -> float:
        for (x0_m, z0_m), (x1_m, z1_m) in pairwise(breaks):
            if x0_m <= x_m <= x1_m:
                return z0_m + (x_m - x0_m) * (z1_m - z0_m) / (x1_m - x0_m)
        raise ValueError(f"{x_m} hors des cassures.")

    xs = [10.0 * i for i in range(round(length_m / 10) + 1)]
    return elevated_route(*((x_m, 0.0, altitude(x_m)) for x_m in xs))


def named_route(
    vertices: Sequence[Point], places: Sequence[tuple[str, Point]]
) -> Route:
    """Référence plate avec des lieux nommés, en ``local_deg(x, y)``."""
    return replace(
        reference_route(*vertices),
        named_points=tuple(
            NamedPoint(name, *local_deg(x_m, y_m), elevation_m=None)
            for name, (x_m, y_m) in places
        ),
    )


def stay(path: TracePath, count: int) -> TracePath:
    """``count`` enregistrements immobiles, un par seconde, à la dernière position."""
    for _ in range(count):
        path.jump(path.points_m[-1], 1.0)
    return path


# ---------------------------------------------------------------------------
# § 7.2b — une fonction par ligne neuve du tableau
# ---------------------------------------------------------------------------

REGIME_BREAKS = ((0.0, 0.0), (175.0, 35.0), (460.0, 35.0), (1010.0, -47.5))
"""Cassures d'altitude de Régimes et Régimes-écart."""


def regimes() -> MatchCase:
    """Référence à altitude de 1 010 m ; ``(20,3)→(1005,−4)`` à 1,5 m/s, toutes les
    2 s."""
    path = TracePath((20.0, 3.0)).to((1005.0, -4.0), speed_ms=1.5, step_s=2.0)
    return MatchCase(regime_route(REGIME_BREAKS, 1010.0), path.trace())


def regimes_deviation() -> MatchCase:
    """Régimes avec une bosse de 35 m au nord entre 300 et 450 m."""
    path = TracePath((20.0, 3.0)).to(
        (300.0, 3.0),
        (375.0, 38.0),
        (450.0, 3.0),
        (1005.0, -4.0),
        speed_ms=1.5,
        step_s=2.0,
    )
    return MatchCase(regime_route(REGIME_BREAKS, 1010.0), path.trace())


def anchored_departure_then_gap() -> MatchCase:
    """``(0 s, (12,3))``, puis ``(24,3)→(507,3)`` à 1,5 m/s toutes les 2 s à partir
    de 11 s : un trou de 11 s dans l'intervalle 0."""
    path = (
        TracePath((12.0, 3.0))
        .jump((24.0, 3.0), 11.0)
        .to((507.0, 3.0), speed_ms=1.5, step_s=2.0)
    )
    return MatchCase(reference_route(*EAST_510), path.trace())


def arrival_before_a_gap() -> MatchCase:
    """``(0,0)→(510,0)`` à 1,5 m/s toutes les 2 s (dernier en ``x = 510`` exactement),
    puis ``(351 s, (520,0))`` et ``(353 s, (523,0))``."""
    path = (
        TracePath((0.0, 0.0))
        .to((510.0, 0.0), speed_ms=1.5, step_s=2.0)
        .jump((520.0, 0.0), 11.0)
        .jump((523.0, 0.0), 2.0)
    )
    return MatchCase(reference_route(*EAST_510), path.trace())


def _sine_trace(amplitude_m: float, wavelength_m: float) -> MatchCase:
    """``x = 0,5·t``, ``y = a·sin(2π·x/λ)``, ``t = 0 … 1030`` s au pas de 1 s."""
    points = []
    for t in range(1031):
        x_m = 0.5 * t
        points.append((x_m, amplitude_m * math.sin(2 * math.pi * x_m / wavelength_m)))
    return MatchCase(reference_route(*EAST_510), local_trace(range(1031), points))


def high_ratio() -> MatchCase:
    """rho haut : ``y = 10·sin(2π·x/17)``."""
    return _sine_trace(10.0, 17.0)


def ratio_and_deviation() -> MatchCase:
    """rho et écart : ``y = 36·sin(2π·x/(250/3))``."""
    return _sine_trace(36.0, 250 / 3)


def low_ratio() -> MatchCase:
    """rho bas : pointe aller-retour de 60 m dans la référence ; trace droite à 2 m/s,
    un enregistrement par seconde."""
    path = TracePath((0.0, 0.0)).to((610.0, 0.0), speed_ms=2.0)
    return MatchCase(
        reference_route(
            (0.0, 0.0), (300.0, 0.0), (300.0, 60.0), (300.0, 0.0), (610.0, 0.0)
        ),
        path.trace(),
    )


def east_west_zigzag() -> MatchCase:
    """Référence vers le nord ; ``y = 1,25·t − 0,5``, ``x = 5·sin(2π·y/17)``,
    ``t = 0 … 412`` s au pas de 0,8 s : aucun enregistrement sur une ligne de score."""
    times = [0.8 * i for i in range(516)]
    points = []
    for t in times:
        y_m = 1.25 * t - 0.5
        points.append((5 * math.sin(2 * math.pi * y_m / 17), y_m))
    return MatchCase(
        reference_route((0.0, 0.0), (0.0, 510.0)), local_trace(times, points)
    )


def east_bump() -> MatchCase:
    """Bosse à l'est : référence vers le nord ; écart est-ouest de 22 m lu avec
    ``cos φ``. 1,5 m/s, toutes les 2 s."""
    path = TracePath((2.0, 25.0)).to(
        (2.0, 70.0),
        (24.0, 132.0),
        (2.0, 190.0),
        (-3.0, 505.0),
        speed_ms=1.5,
        step_s=2.0,
    )
    return MatchCase(reference_route((0.0, 0.0), (0.0, 530.0)), path.trace())


def reference_spike() -> MatchCase:
    """Pointe du tracé : sommet à 32 m au nord ; trace droite à 2 m/s, 1 Hz."""
    path = TracePath((0.0, 0.0)).to((560.0, 0.0), speed_ms=2.0)
    return MatchCase(
        reference_route(
            (0.0, 0.0), (370.0, 0.0), (375.0, 32.0), (380.0, 0.0), (560.0, 0.0)
        ),
        path.trace(),
    )


def trace_spur() -> MatchCase:
    """Écart de la trace : aller-retour de 33 m vers l'est depuis ``y = 120`` ;
    1,25 m/s, un enregistrement par seconde."""
    path = TracePath((0.0, 0.0)).to(
        (0.0, 120.0), (33.0, 120.0), (0.0, 120.0), (0.0, 515.0), speed_ms=1.25
    )
    return MatchCase(reference_route((0.0, 0.0), (0.0, 510.0)), path.trace())


def overshoot() -> MatchCase:
    """Dépassement (``ε = 20``, ``r_c = 25``) : boucle au-delà de ``x = 250``.
    1,5 m/s, toutes les 2 s."""
    path = TracePath((0.0, 0.0)).to(
        (240.0, 0.0),
        (262.0, 12.0),
        (244.0, 12.0),
        (256.0, 12.0),
        (270.0, 0.0),
        (515.0, 0.0),
        speed_ms=1.5,
        step_s=2.0,
    )
    return MatchCase(
        reference_route(*EAST_510),
        path.trace(),
        matching_parameters(lateral_tolerance_m=20.0, cluster_radius_m=25.0),
    )


EAST_760 = ((0.0, 0.0), (760.0, 0.0))


def stop_off_support() -> MatchCase:
    """Arrêt hors support : arrêt de 150 s à 40 m au nord, dans un segment exclu.
    1,5 m/s, un enregistrement par seconde."""
    path = TracePath((0.0, 0.0)).to((120.0, 0.0), (150.0, 40.0), speed_ms=1.5)
    stay(path, 150).to((180.0, 0.0), (760.0, 0.0), speed_ms=1.5)
    return MatchCase(reference_route(*EAST_760), path.trace())


def _stop_path() -> TracePath:
    """``(0,0)→(150,0)`` à 1,5 m/s (0 … 100 s), puis 110 enregistrements immobiles
    (101 … 210 s)."""
    return stay(TracePath((0.0, 0.0)).to((150.0, 0.0), speed_ms=1.5), 110)


def stop() -> MatchCase:
    """Arrêt : l'arrêt de 110 s, puis ``(150,0)→(760,0)`` à 1,5 m/s."""
    path = _stop_path().to((760.0, 0.0), speed_ms=1.5)
    return MatchCase(reference_route(*EAST_760), path.trace())


def two_stops() -> MatchCase:
    """Deux arrêts (``Δ = 100``) : l'arrêt de 110 s, ``(150,0)→(450,0)`` à 1,5 m/s,
    150 enregistrements en ``x = 450 + 0,07·j`` (calculé à chaque rang), puis
    ``(460,5 ; 0)→(760,0)`` à 1,5 m/s."""
    path = _stop_path().to((450.0, 0.0), speed_ms=1.5)
    for j in range(1, 151):
        path.jump((450 + 0.07 * j, 0.0), 1.0)
    path.to((760.0, 0.0), speed_ms=1.5)
    return MatchCase(
        reference_route(*EAST_760),
        path.trace(),
        matching_parameters(score_step_m=100.0),
    )


PASSAGE_PLACES = (
    ("A", (5.0, 3.0)),
    ("B", (300.0, 4.0)),
    ("C", (480.0, -2.0)),
    ("D", (700.0, 1.0)),
)
"""Les quatre lieux nommés de Passages."""


def passages() -> MatchCase:
    """Référence de 1 010 m à quatre lieux nommés ; ``(12,2)→(600,2)→(600,200)`` à
    1,5 m/s, toutes les 2 s."""
    path = TracePath((12.0, 2.0)).to(
        (600.0, 2.0), (600.0, 200.0), speed_ms=1.5, step_s=2.0
    )
    return MatchCase(
        named_route(((0.0, 0.0), (1010.0, 0.0)), PASSAGE_PLACES), path.trace()
    )


def passages_departure_excluded() -> MatchCase:
    """Passages, avec un détour de 38 m au nord dans le premier segment."""
    path = TracePath((12.0, 2.0)).to(
        (100.0, 2.0),
        (130.0, 40.0),
        (160.0, 2.0),
        (600.0, 2.0),
        (600.0, 200.0),
        speed_ms=1.5,
        step_s=2.0,
    )
    return MatchCase(
        named_route(((0.0, 0.0), (1010.0, 0.0)), PASSAGE_PLACES), path.trace()
    )
