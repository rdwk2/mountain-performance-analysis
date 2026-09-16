"""Oracles et stabilité à la densité source, sans invariance au pas de grille.

Changer le pas de grille change la fenêtre effective et donc le profil : aucune
invariance à ce changement n'est promise.
"""

import math
from dataclasses import replace

import pytest

from fixtures.synthetic_routes import meridian_route, subdivide_route
from mountain_perf.gpx import PROFILE_PARAMETER_SPECS, build_profile
from mountain_perf.schemas import ParameterSet


@pytest.mark.parametrize(
    ("window_m", "gain", "expected_ascent_m"),
    [(0.0, 1.0, 120.0), (150.0, (1 + math.sqrt(2)) / 3, 40 * (1 + math.sqrt(2)))],
)
def test_exact_sinusoidal_oracle(
    window_m: float, gain: float, expected_ascent_m: float
) -> None:
    profile = build_profile(
        meridian_route(),
        ParameterSet(PROFILE_PARAMETER_SPECS, {"smoothing_window_m": window_m}),
    )
    ascent_m = profile.cumulative_ascent_m[32] - profile.cumulative_ascent_m[8]
    assert ascent_m == pytest.approx(expected_ascent_m, abs=1e-9)
    # Altitudes intérieures : cette comparaison détecte une fenêtre décentrée.
    for d_m, e_m in zip(
        profile.distance_m[1:-1], profile.elevation_m[1:-1], strict=True
    ):
        expected_m = 1500 + 20 * gain * math.sin(math.tau * d_m / 400)
        assert e_m == pytest.approx(expected_m, abs=1e-9)


def test_subdivision_preserves_profile_with_smoothing() -> None:
    route = meridian_route()
    parameters = ParameterSet(PROFILE_PARAMETER_SPECS, {"smoothing_window_m": 150})
    original = build_profile(route, parameters)
    subdivided = build_profile(subdivide_route(route), parameters)
    assert subdivided.distance_m == pytest.approx(original.distance_m, abs=1e-9)
    assert subdivided.elevation_m == pytest.approx(original.elevation_m, abs=1e-9)
    assert subdivided.cumulative_ascent_m == pytest.approx(
        original.cumulative_ascent_m, abs=1e-9
    )


@pytest.mark.parametrize("stride", [2, 3])
def test_decimation_changes_ascent_by_less_than_one_percent(stride: int) -> None:
    route = meridian_route(wavelength_m=600, length_m=3003, spacing_m=7)
    # Le dernier point est conservé : les deux tracés ont la même longueur.
    indices = sorted(
        set(range(0, len(route.latitude_deg), stride)) | {len(route.latitude_deg) - 1}
    )
    decimated = replace(
        route,
        latitude_deg=tuple(route.latitude_deg[i] for i in indices),
        longitude_deg=tuple(route.longitude_deg[i] for i in indices),
        elevation_m=tuple(route.elevation_m[i] for i in indices),
    )
    # δ = 7 ne divise pas h = 50 : l'interpolation travaille vraiment.
    # Validité double : δp <= h/2 ET δp <= λ/25 (21 <= 25 et 21 <= 24).
    parameters = ParameterSet(PROFILE_PARAMETER_SPECS, {"smoothing_window_m": 150})
    dense_ascent_m = build_profile(route, parameters).cumulative_ascent_m[-1]
    sparse_ascent_m = build_profile(decimated, parameters).cumulative_ascent_m[-1]
    assert abs(sparse_ascent_m - dense_ascent_m) / dense_ascent_m <= 0.01
