"""Les baselines de ``0010`` D9.1 (§ 6.1, § 7.3 et § 8.1, test 1, du brief M4c-1).

Constantes écrites comme D9.1 ; sur le profil du § 7.3, les allures des trois
baselines contre un calcul indépendant en ``mpmath`` (tolérance du § 7.0) et leur
chronologie (précision de D9.1 : une ``ProjectedTimeline`` sur la grille fine) ;
Tobler symétrique autour de ``g = −0,05`` ; à une pente extrême, une allure infinie et
aucune chronologie (décision 6) ; les modèles qui ne sont pas des baselines refusés ;
par propriété, des allures finies et ``> 0`` sur les pentes usuelles, Naismith au bit.
"""

import math

import pytest
from hypothesis import given
from hypothesis import strategies as st

from fixtures.calibration import close
from fixtures.outings import source
from mountain_perf.gpx import PROFILE_PARAMETER_SPECS
from mountain_perf.model import (
    BASELINE_VERSION,
    BASELINES,
    CONSTANT_SPEED_MS,
    NAISMITH_CLIMB_S_PER_M,
    NAISMITH_SPEED_MS,
    TOBLER_DECAY,
    TOBLER_OFFSET,
    TOBLER_PEAK_MS,
    baseline_paces,
    baseline_timeline,
)
from mountain_perf.schemas import ModelKind, ParameterSet, RouteProfile


def _profile(
    distance_m: tuple[float, ...], elevation_m: tuple[float, ...]
) -> RouteProfile:
    return RouteProfile(
        route_name="Profil des baselines",
        source=source("gpx", "baselines.gpx", "1"),
        distance_m=distance_m,
        elevation_m=elevation_m,
        resolved_points=(),
        step_m=50.0,
        build_parameters=ParameterSet(PROFILE_PARAMETER_SPECS),
    )


PROFILE = _profile(
    (0.0, 50.0, 100.0, 130.0, 200.0, 260.0),
    (1000.0, 1005.0, 1005.0, 999.0, 995.5, 1010.0),
)
"""Le profil du § 7.3 : pentes ``0,1 ; 0 ; −0,2 ; −0,05 ; 0,241 666…``."""

EXPECTED_PACES = {
    ModelKind.CONSTANT_SPEED: (1.0, 1.0, 1.0, 1.0, 1.0),
    ModelKind.NAISMITH: (1.32, 0.72, 0.72, 0.72, 2.17),
    ModelKind.TOBLER: (
        1.0142753090274548,
        0.7147477299674149,
        1.0142753090274548,
        0.6,
        1.6653040336699894,
    ),
}
"""Les allures du § 7.3 (s/m), calculées en ``mpmath``."""

NOT_BASELINES = (ModelKind.V0_RAW, ModelKind.V0_RECALIBRATED, ModelKind.CANDIDATE)


def test_constants_are_the_literals_of_d9_1() -> None:
    """D9.1 ; décision 17 (``TOBLER_PEAK_MS`` en m/s)."""
    assert BASELINES == (ModelKind.CONSTANT_SPEED, ModelKind.NAISMITH, ModelKind.TOBLER)
    assert BASELINE_VERSION == "baselines-v1"
    assert CONSTANT_SPEED_MS == 1.0
    assert NAISMITH_SPEED_MS == 5.0 / 3.6
    assert NAISMITH_CLIMB_S_PER_M == 6.0
    assert (TOBLER_PEAK_MS, TOBLER_DECAY, TOBLER_OFFSET) == (6.0 / 3.6, 3.5, 0.05)


@pytest.mark.parametrize("baseline", BASELINES)
def test_paces_and_timeline_on_the_profile_of_7_3(baseline: ModelKind) -> None:
    """Précision de D9.1 : une allure par intervalle, à sa pente du profil lissé ; la
    chronologie porte la grille et ces allures, et ``P(260)`` est la somme des
    ``Δd · allure``."""
    paces = baseline_paces(PROFILE, baseline)
    assert isinstance(paces, tuple)
    assert len(paces) == len(PROFILE.grade)
    for pace, expected in zip(paces, EXPECTED_PACES[baseline], strict=True):
        assert close(pace, expected)
    timeline = baseline_timeline(PROFILE, baseline)
    assert timeline is not None
    assert timeline.grid_m == tuple(PROFILE.distance_m)
    assert timeline.pace_s_per_m == paces
    d = PROFILE.distance_m
    total = math.fsum((d[i + 1] - d[i]) * pace for i, pace in enumerate(paces))
    assert close(timeline.time_at(260.0), total)


def test_tobler_is_symmetric_around_its_fastest_grade() -> None:
    """D9.1 : Tobler symétrique autour de ``g = −0,05`` (intervalles 1 et 3 égaux), où
    il est le plus rapide (le 4ᵉ intervalle)."""
    paces = baseline_paces(PROFILE, ModelKind.TOBLER)
    assert paces[0] == paces[2]
    assert min(paces) == paces[3]


@pytest.mark.parametrize("sign", [1.0, -1.0])
def test_an_extreme_grade_has_no_tobler_timeline(sign: float) -> None:
    """Décision 6, précision de D9.1 : sur ``±300`` d'une pente de 1 cm,
    l'exponentielle de Tobler sous-dépasse — allure ``+inf``, aucune chronologie ; les
    deux autres baselines en ont une."""
    rise = sign * 3.0
    profile = _profile((0.0, 0.01, 100.0), (1000.0, 1000.0 + rise, 1000.0 + rise))
    assert baseline_paces(profile, ModelKind.TOBLER)[0] == math.inf
    assert baseline_timeline(profile, ModelKind.TOBLER) is None
    assert baseline_timeline(profile, ModelKind.CONSTANT_SPEED) is not None
    assert baseline_timeline(profile, ModelKind.NAISMITH) is not None


@pytest.mark.parametrize("model", NOT_BASELINES)
def test_a_model_that_is_not_a_baseline_is_refused(model: ModelKind) -> None:
    """§ 6.1 : précondition des deux fonctions, ``baseline`` dans ``BASELINES``."""
    with pytest.raises(ValueError, match=r"baseline_paces : .* n'est pas une baseline"):
        baseline_paces(PROFILE, model)
    with pytest.raises(ValueError, match="n'est pas une baseline"):
        baseline_timeline(PROFILE, model)


@given(st.floats(min_value=-2.0, max_value=2.0))
def test_paces_are_finite_and_positive_on_usual_grades(grade: float) -> None:
    """Propriété (D9.1) : de ``−2`` à ``2``, les trois allures sont finies et ``> 0`` ;
    Naismith vaut au bit ``1 / (5 / 3,6) + 6 · max(g, 0)``."""
    profile = _profile((0.0, 100.0), (1000.0, 1000.0 + 100.0 * grade))
    for baseline in BASELINES:
        (pace,) = baseline_paces(profile, baseline)
        assert math.isfinite(pace)
        assert pace > 0
    (naismith,) = baseline_paces(profile, ModelKind.NAISMITH)
    g = profile.grade[0]
    assert naismith == 1.0 / (5.0 / 3.6) + 6.0 * max(g, 0.0)
