"""Adaptateur du moteur M3 : ``ProjectedTimeline`` (§ 6.1 et § 8.1, test 1, du brief
M4b-2 ; ``0010`` D16, « accès aux temps fins et aux cumuls v0 aux abscisses
exactes » ; décision 2 de rdw, Q3).

**Au bit contre une copie figée des formules de M3** : :func:`_frozen_cumulative`,
:func:`_frozen_time_at` et :func:`_frozen_project_with_diagnostics` recopient, telles
quelles, les écritures de ``model/engine.py`` sur ``main`` avant M4b-2 (commit
``878a718``) — le cumul par ``accumulate`` et le corps de ``_time_at``. Elles ne se
modifient pas : c'est la référence que la réécriture doit rendre au bit. Précision 4
de la relecture du plan : ``time_at`` aussi en chaque nœud, au milieu et au tiers de
chaque intervalle des profils des treize cas.
"""

import math
from bisect import bisect_right
from collections.abc import Sequence
from datetime import UTC, datetime
from itertools import accumulate, pairwise

import pytest
from hypothesis import given
from hypothesis import strategies as st

from fixtures.metrics import raises_value_error
from fixtures.scoring import (
    CONSTRUCTED,
    GENERATED_AT,
    curve_read,
    match_case,
    trace_profile,
)
from fixtures.segments import reference_profile
from mountain_perf.backtest import trace_route
from mountain_perf.model import (
    ENGINE_VERSION,
    PROJECTION_PARAMETER_SPECS,
    PaceModel,
    ProjectedTimeline,
    ProjectionDiagnostics,
    project_with_diagnostics,
    projected_timeline,
    route_endpoints,
)
from mountain_perf.schemas import (
    NamedPoint,
    PaceCurve,
    ParameterSet,
    Passage,
    Projection,
    ResolvedPoint,
    Route,
    RouteProfile,
)
from mountain_perf.validation import ContractError

V0 = ParameterSet(PROJECTION_PARAMETER_SPECS)

# ---------------------------------------------------------------------------
# Copie figée de M3 (main, 878a718) — ne pas modifier
# ---------------------------------------------------------------------------


def _frozen_cumulative(
    grid_m: Sequence[float], pace_s_per_m: Sequence[float]
) -> tuple[float, ...]:
    """Le cumul de ``project_with_diagnostics`` de M3, par ``accumulate``."""
    lengths_m = tuple(grid_m[i + 1] - grid_m[i] for i in range(len(grid_m) - 1))
    return tuple(
        accumulate(
            (
                length_m * pace
                for length_m, pace in zip(lengths_m, pace_s_per_m, strict=True)
            ),
            initial=0.0,
        )
    )


def _frozen_time_at(
    grid_m: Sequence[float],
    cumulative_s: Sequence[float],
    pace_s_per_m: Sequence[float],
    at_m: float,
) -> float:
    """Le corps de ``_time_at`` de M3."""
    i = min(max(bisect_right(grid_m, at_m) - 1, 0), len(grid_m) - 2)
    if at_m == grid_m[i]:
        return cumulative_s[i]
    if at_m == grid_m[i + 1]:
        return cumulative_s[i + 1]
    return cumulative_s[i] + (at_m - grid_m[i]) * pace_s_per_m[i]


def _frozen_share(part: float, whole: float) -> float:
    return part / whole if whole > 0 else 0.0


def _frozen_still(point: ResolvedPoint, at_s: float) -> Passage:
    return Passage(point=point, moving_time_s=at_s, arrival_s=at_s, departure_s=at_s)


def _frozen_project_with_diagnostics(
    profile: RouteProfile,
    curve: PaceCurve,
    parameters: ParameterSet,
    *,
    curve_ref: str,
    endpoints: tuple[NamedPoint, NamedPoint],
    generated_at: datetime,
) -> tuple[Projection, ProjectionDiagnostics]:
    """``project_with_diagnostics`` de M3, sa date fixée par l'appelant."""
    model = PaceModel(curve)
    grid_m = profile.distance_m
    elevation_m = profile.elevation_m
    grade = profile.grade
    effort = parameters["effort"]
    pace_s_per_m = tuple(model.pace_s_per_m(g) / effort for g in grade)
    lengths_m = tuple(grid_m[i + 1] - grid_m[i] for i in range(len(grid_m) - 1))
    cumulative_s = tuple(
        accumulate(
            (
                length_m * pace
                for length_m, pace in zip(lengths_m, pace_s_per_m, strict=True)
            ),
            initial=0.0,
        )
    )
    start_point, finish_point = endpoints
    passages = (
        _frozen_still(
            ResolvedPoint(
                point=start_point,
                distance_m=grid_m[0],
                elevation_m=elevation_m[0],
                offset_m=0.0,
            ),
            cumulative_s[0],
        ),
        *(
            _frozen_still(
                point,
                _frozen_time_at(grid_m, cumulative_s, pace_s_per_m, point.distance_m),
            )
            for point in profile.resolved_points
        ),
        _frozen_still(
            ResolvedPoint(
                point=finish_point,
                distance_m=grid_m[-1],
                elevation_m=elevation_m[-1],
                offset_m=0.0,
            ),
            cumulative_s[-1],
        ),
    )
    projection = Projection(
        profile=profile,
        curve_ref=curve_ref,
        parameters=parameters,
        passages=passages,
        start_time=None,
        engine_version=ENGINE_VERSION,
        generated_at=generated_at,
    )
    extrapolated = [i for i, g in enumerate(grade) if model.is_extrapolated(g)]
    out_of_support_distance_m = sum(lengths_m[i] for i in extrapolated)
    out_of_support_time_s = sum(lengths_m[i] * pace_s_per_m[i] for i in extrapolated)
    diagnostics = ProjectionDiagnostics(
        out_of_support_distance_m=out_of_support_distance_m,
        out_of_support_time_s=out_of_support_time_s,
        out_of_support_distance_share=_frozen_share(
            out_of_support_distance_m, grid_m[-1]
        ),
        out_of_support_time_share=_frozen_share(
            out_of_support_time_s, cumulative_s[-1]
        ),
        grade_min=min(grade),
        grade_max=max(grade),
    )
    return projection, diagnostics


# ---------------------------------------------------------------------------
# Invariants (ContractError), objets valides aux limites
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("grid_m", "pace_s_per_m", "match"),
    [
        ([0.0, 1.0], (1.0,), "grid_m doit être une séquence immuable"),
        ((0.0, 1.0), [1.0], "pace_s_per_m doit être une séquence immuable"),
        ((0.0,), (), "grid_m doit contenir au moins 2"),
        ((0.0, math.nan), (1.0,), r"grid_m\[1\] doit être fini"),
        ((0.0, math.inf), (1.0,), r"grid_m\[1\] doit être fini"),
        ((1.0, 2.0), (1.0,), r"grid_m\[0\] doit valoir 0"),
        ((0.0, 1.0, 1.0), (1.0, 1.0), "grid_m doit être strictement croissante"),
        ((0.0, 2.0, 1.0), (1.0, 1.0), "grid_m doit être strictement croissante"),
        ((0.0, 1.0, 2.0), (1.0,), "2 allures"),
        ((0.0, 1.0), (1.0, 1.0), "1 allures"),
        ((0.0, 1.0), (math.nan,), r"pace_s_per_m\[0\] doit être fini"),
        ((0.0, 1.0), (math.inf,), r"pace_s_per_m\[0\] doit être fini"),
        ((0.0, 1.0), (0.0,), r"pace_s_per_m\[0\] doit être > 0"),
        ((0.0, 1.0), (-1.0,), r"pace_s_per_m\[0\] doit être > 0"),
    ],
)
def test_invariants_of_projected_timeline(
    grid_m: tuple[float, ...], pace_s_per_m: tuple[float, ...], match: str
) -> None:
    """§ 6.1 : tuples, au moins deux nœuds finis strictement croissants depuis 0, une
    allure finie ``> 0`` par intervalle."""
    with pytest.raises(ContractError, match=match):
        ProjectedTimeline(grid_m, pace_s_per_m)


def test_valid_timeline_at_its_limits() -> None:
    """Deux nœuds, une allure de ``5e−324`` (la plus petite ``> 0``) acceptée ; le
    cumul est calculé, jamais passé."""
    timeline = ProjectedTimeline((0.0, 1.0), (5e-324,))
    assert timeline.cumulative_s == (0.0, 5e-324)
    assert timeline.length_m == 1.0


# ---------------------------------------------------------------------------
# Au bit contre la copie figée : grilles tirées
# ---------------------------------------------------------------------------


@st.composite
def _grids_and_paces(draw: st.DrawFn) -> tuple[tuple[float, ...], tuple[float, ...]]:
    """Grille ``accumulate`` de longueurs tirées dans ``[1e−3 ; 1e3]`` m, allures
    tirées dans ``[1e−4 ; 20]`` s/m."""
    lengths = draw(
        st.lists(st.floats(1e-3, 1e3, allow_nan=False), min_size=1, max_size=40)
    )
    paces = draw(
        st.lists(
            st.floats(1e-4, 20.0, allow_nan=False),
            min_size=len(lengths),
            max_size=len(lengths),
        )
    )
    return tuple(accumulate(lengths, initial=0.0)), tuple(paces)


@given(_grids_and_paces(), st.data())
def test_timeline_is_m3_at_the_bit_on_drawn_grids(
    drawn: tuple[tuple[float, ...], tuple[float, ...]], data: st.DataObject
) -> None:
    """``0010`` D16 : ``cumulative_s`` et ``time_at`` aux nœuds, aux milieux et à des
    abscisses tirées dans ``[0 ; L]`` égalent (``==``) la copie figée de M3."""
    grid_m, pace_s_per_m = drawn
    timeline = ProjectedTimeline(grid_m, pace_s_per_m)
    cumulative_s = _frozen_cumulative(grid_m, pace_s_per_m)
    assert timeline.cumulative_s == cumulative_s
    middles = [(a + b) / 2 for a, b in pairwise(grid_m)]
    drawn_m = data.draw(
        st.lists(st.floats(0.0, grid_m[-1], allow_nan=False), max_size=20)
    )
    for at_m in (*grid_m, *middles, *drawn_m):
        expected = _frozen_time_at(grid_m, cumulative_s, pace_s_per_m, at_m)
        assert timeline.time_at(at_m) == expected


# ---------------------------------------------------------------------------
# Au bit contre la copie figée : profils des treize cas
# ---------------------------------------------------------------------------


def _profiles(name: str) -> list[tuple[Route, RouteProfile]]:
    """Le profil de référence et le profil de la trace (choix 4) d'un cas."""
    case = match_case(name)
    trace = case.trace
    route = trace_route(trace, trace.sources[0].identifier)
    return [(case.route, reference_profile(case)), (route, trace_profile(trace))]


@pytest.mark.parametrize("name", CONSTRUCTED)
def test_time_at_is_m3_at_the_bit_on_the_profiles_of_the_cases(name: str) -> None:
    """Précision 4 (§ 7.1) : sur les profils de référence et de trace, le cumul et
    ``time_at`` en chaque nœud, au milieu et au tiers de chaque intervalle égalent
    (``==``) la copie figée de ``_time_at`` (``0010`` D16)."""
    for _, profile in _profiles(name):
        timeline = projected_timeline(profile, curve_read().curve, V0)
        grid_m, pace_s_per_m = timeline.grid_m, timeline.pace_s_per_m
        cumulative_s = _frozen_cumulative(grid_m, pace_s_per_m)
        assert timeline.cumulative_s == cumulative_s
        for a, b in pairwise(grid_m):
            for at_m in (a, (a + b) / 2, a + (b - a) / 3):
                expected = _frozen_time_at(grid_m, cumulative_s, pace_s_per_m, at_m)
                assert timeline.time_at(at_m) == expected
        assert timeline.time_at(grid_m[-1]) == cumulative_s[-1]


@pytest.mark.parametrize("name", CONSTRUCTED)
def test_project_is_m3_at_the_bit_on_the_profiles_of_the_cases(name: str) -> None:
    """§ 6.1 : ``project_with_diagnostics`` réécrit sur la chronologie égale (``==``)
    la copie figée de M3, ``Projection`` et diagnostics, à ``generated_at`` égal."""
    read = curve_read()
    for route, profile in _profiles(name):
        endpoints = route_endpoints(route)
        rewritten = project_with_diagnostics(
            profile,
            read.curve,
            V0,
            curve_ref=read.curve_ref,
            endpoints=endpoints,
            generated_at=GENERATED_AT,
        )
        frozen = _frozen_project_with_diagnostics(
            profile,
            read.curve,
            V0,
            curve_ref=read.curve_ref,
            endpoints=endpoints,
            generated_at=GENERATED_AT,
        )
        assert rewritten == frozen


def test_named_points_are_projected_at_the_bit() -> None:
    """Les lieux résolus passent par ``time_at`` : Passages en a trois sur sa
    référence."""
    (route, profile), _ = _profiles("Passages")
    assert len(profile.resolved_points) == 3
    read = curve_read()
    projection, _ = project_with_diagnostics(
        profile,
        read.curve,
        V0,
        curve_ref=read.curve_ref,
        endpoints=route_endpoints(route),
        generated_at=GENERATED_AT,
    )
    timeline = projected_timeline(profile, read.curve, V0)
    for passage in projection.passages[1:-1]:
        assert passage.arrival_s == timeline.time_at(passage.point.distance_m)


def test_projected_timeline_divides_by_the_effort() -> None:
    """Les allures de v0 : celles de la courbe divisées par l'effort, au bit."""
    (_, profile), _ = _profiles("Régimes")
    curve = curve_read().curve
    parameters = ParameterSet(PROJECTION_PARAMETER_SPECS, {"effort": 0.8})
    timeline = projected_timeline(profile, curve, parameters)
    model = PaceModel(curve)
    assert timeline.grid_m == tuple(profile.distance_m)
    assert timeline.pace_s_per_m == tuple(
        model.pace_s_per_m(g) / 0.8 for g in profile.grade
    )


# ---------------------------------------------------------------------------
# Précondition de time_at (choix 11)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("name", CONSTRUCTED)
def test_time_at_refuses_an_abscissa_outside_the_route(name: str) -> None:
    """Choix 11 et § 7.1 : hors de ``[0 ; L]``, ``time_at`` lève ``ValueError`` (jamais
    de prolongement) ; ``0`` et ``L`` rendent ``cumulative_s[0]`` et
    ``cumulative_s[-1]``."""
    for _, profile in _profiles(name):
        timeline = projected_timeline(profile, curve_read().curve, V0)
        length_m = timeline.length_m
        for at_m in (-1e-9, length_m * (1 + 1e-15) + 1e-12, math.nan):
            with raises_value_error("time_at"):
                timeline.time_at(at_m)
        assert timeline.time_at(0.0) == timeline.cumulative_s[0] == 0.0
        assert timeline.time_at(length_m) == timeline.cumulative_s[-1]


def test_project_date_defaults_to_now() -> None:
    """La date de ``project`` reste celle de M3 : maintenant, avec fuseau."""
    (route, profile), _ = _profiles("Régimes")
    read = curve_read()
    before = datetime.now(UTC)
    projection, _ = project_with_diagnostics(
        profile,
        read.curve,
        V0,
        curve_ref=read.curve_ref,
        endpoints=route_endpoints(route),
    )
    assert before <= projection.generated_at <= datetime.now(UTC)
