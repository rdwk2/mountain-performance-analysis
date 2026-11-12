"""La part hors support sur une portion du profil (OG-2, § 6.2 du brief OG-2) :
``portion_out_of_support_share`` et ``portion_out_of_support_time_share``.

La table à la main vient de l'oracle de la conception : une chronologie ``grid_m`` =
(0, 100, 300, 400), ``pace_s_per_m`` = (0,5 ; 1,0 ; 0,4), l'intervalle du milieu seul
hors support ; termes 50, 200, 40."""

from __future__ import annotations

from dataclasses import replace
from itertools import accumulate, pairwise

import pytest
from hypothesis import given
from hypothesis import strategies as st

from fixtures.curves import SUPPORT_CURVE
from fixtures.projection import CURVE_REF, ENDPOINTS, SIX_INTERVAL_PROFILE
from mountain_perf.model.engine import (
    PROJECTION_PARAMETER_SPECS,
    ProjectedTimeline,
    portion_out_of_support_share,
    portion_out_of_support_time_share,
    project_with_diagnostics,
)
from mountain_perf.schemas import PaceCurve, ParameterSet, RouteProfile
from mountain_perf.schemas.metrics import METRIC_RELATIVE_TOLERANCE
from mountain_perf.validation import ContractError
from strategies import efforts, model_pace_curves, projectable_route_profiles

HAND = ProjectedTimeline((0.0, 100.0, 300.0, 400.0), (0.5, 1.0, 0.4))
MIDDLE = (False, True, False)


@pytest.mark.parametrize(
    ("portion", "share"),
    [
        (None, 0.6896551724137931),
        ((50.0, 350.0), 0.8163265306122449),
        ((0.0, 100.0), 0.0),
        ((150.0, 250.0), 1.0),
        ((100.0, 300.0), 1.0),
        ((0.0, 300.0), 0.8),
    ],
)
def test_shares_by_hand(portion: tuple[float, float] | None, share: float) -> None:
    assert portion_out_of_support_share(HAND, MIDDLE, portion) == share


@pytest.mark.parametrize(
    "portion", [(0.0, 400.0000001), (-1.0, 100.0), (100.0, 100.0), (300.0, 100.0)]
)
def test_a_portion_outside_the_profile_is_refused(
    portion: tuple[float, float],
) -> None:
    a, b = portion
    with pytest.raises(ContractError) as error:
        portion_out_of_support_share(HAND, MIDDLE, portion)
    assert str(error.value) == (
        f"portion_m : (a, b) avec 0 <= a < b <= 400.0 attendu, reçu ({a}, {b})."
    )


def test_one_flag_per_interval_is_required() -> None:
    with pytest.raises(ContractError) as error:
        portion_out_of_support_share(HAND, (False, True), None)
    assert str(error.value) == (
        "extrapolated : une valeur par intervalle attendue (3), reçu 2."
    )


def test_all_out_of_support_and_all_inside() -> None:
    assert portion_out_of_support_share(HAND, (True, True, True), None) == 1.0
    assert portion_out_of_support_share(HAND, (True, True, True), (10, 20)) == 1.0
    assert portion_out_of_support_share(HAND, (False, False, False), None) == 0.0


def _parameters(effort: float | None = None) -> ParameterSet:
    values = {} if effort is None else {"effort": effort}
    return ParameterSet(PROJECTION_PARAMETER_SPECS, values)


def _engine_share(profile: RouteProfile, curve: PaceCurve, effort: float) -> float:
    _, diagnostics = project_with_diagnostics(
        profile, curve, _parameters(effort), curve_ref=CURVE_REF, endpoints=ENDPOINTS
    )
    return diagnostics.out_of_support_time_share


def test_without_portion_it_is_the_engine_field() -> None:
    """Sur le profil des tests du moteur : 5/9, le champ du moteur."""
    share = portion_out_of_support_time_share(
        SIX_INTERVAL_PROFILE, SUPPORT_CURVE, _parameters(), None
    )
    assert share == pytest.approx(
        _engine_share(SIX_INTERVAL_PROFILE, SUPPORT_CURVE, 1.0),
        rel=METRIC_RELATIVE_TOLERANCE,
    )
    assert share == pytest.approx(5 / 9, rel=METRIC_RELATIVE_TOLERANCE)


def test_a_profile_inside_the_support_gives_zero() -> None:
    flat = replace(
        SIX_INTERVAL_PROFILE,
        elevation_m=(1000.0, 1010.0, 1000.0, 1000.0, 1010.0, 1000.0, 1010.0),
        resolved_points=(),
    )
    assert portion_out_of_support_time_share(
        flat, SUPPORT_CURVE, _parameters(), None
    ) == (0.0)
    assert (
        portion_out_of_support_time_share(flat, SUPPORT_CURVE, _parameters(), (10, 20))
        == 0.0
    )


@given(projectable_route_profiles(), model_pace_curves(), efforts())
def test_equal_to_the_engine_within_the_tolerance(
    profile: RouteProfile, curve: PaceCurve, effort: float
) -> None:
    share = portion_out_of_support_time_share(profile, curve, _parameters(effort), None)
    engine = _engine_share(profile, curve, effort)
    assert share == pytest.approx(engine, rel=METRIC_RELATIVE_TOLERANCE, abs=1e-300)
    assert 0.0 <= share <= 1.0


@st.composite
def timelines(draw: st.DrawFn) -> ProjectedTimeline:
    steps = draw(
        st.lists(
            st.floats(0.01, 1000.0, allow_nan=False, allow_infinity=False),
            min_size=1,
            max_size=40,
        )
    )
    paces = draw(
        st.lists(
            st.floats(0.01, 100.0, allow_nan=False, allow_infinity=False),
            min_size=len(steps),
            max_size=len(steps),
        )
    )
    grid = tuple(accumulate(steps, initial=0.0))
    if any(b <= a for a, b in pairwise(grid)):
        grid = tuple(float(i) for i in range(len(steps) + 1))
    return ProjectedTimeline(grid, tuple(paces))


@given(timelines())
def test_all_out_of_support_is_exactly_one(timeline: ProjectedTimeline) -> None:
    """Le numérateur et le dénominateur sont tous deux des ``math.fsum`` des mêmes
    termes : exactement 1, jamais ``1.0000000000000002`` (le défaut du moteur)."""
    flags = (True,) * len(timeline.pace_s_per_m)
    assert portion_out_of_support_share(timeline, flags, None) == 1.0
    middle = (timeline.length_m * 0.25, timeline.length_m * 0.75)
    assert portion_out_of_support_share(timeline, flags, middle) == 1.0


@given(timelines(), st.data())
def test_the_share_stays_in_zero_one(
    timeline: ProjectedTimeline, data: st.DataObject
) -> None:
    n = len(timeline.pace_s_per_m)
    flags = data.draw(st.lists(st.booleans(), min_size=n, max_size=n))
    a = data.draw(st.floats(0.0, timeline.length_m * 0.5))
    b = data.draw(st.floats(timeline.length_m * 0.5, timeline.length_m))
    portion = (a, b) if a < b else None
    share = portion_out_of_support_share(timeline, tuple(flags), portion)
    assert 0.0 <= share <= 1.0
