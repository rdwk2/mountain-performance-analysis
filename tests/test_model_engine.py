"""Moteur de projection : le profil du brief, ses valeurs exactes, et les invariants.

Tolérance des temps : ``1e-9`` en absolu pour les exemples, ``1e-9`` en relatif pour
les propriétés — celles du brief.
"""

import math
from dataclasses import replace
from datetime import UTC, datetime
from itertools import pairwise

import pytest
from hypothesis import given

from fixtures.curves import SUPPORT_CURVE
from fixtures.projection import (
    CURVE_REF,
    ENDPOINTS,
    OUT_OF_SUPPORT_DISTANCE_M,
    OUT_OF_SUPPORT_TIME_S,
    REFUGE,
    REFUGE_ARRIVAL_S,
    SIX_INTERVAL_PROFILE,
    TOTAL_DURATION_AT_EFFORT_0_8_S,
    TOTAL_DURATION_S,
)
from fixtures.routes import LOLLIPOP_ROUTE
from mountain_perf.model.engine import (
    ENGINE_VERSION,
    PROJECTION_PARAMETER_SPECS,
    project,
    project_with_diagnostics,
    route_endpoints,
)
from mountain_perf.schemas import (
    NamedPoint,
    PaceCurve,
    ParameterSet,
    PointKind,
    Projection,
    ResolvedPoint,
    RouteProfile,
)
from mountain_perf.schemas.projection import TIME_TOLERANCE_S
from strategies import efforts, model_pace_curves, projectable_route_profiles

TIME_ABS_TOLERANCE_S = 1e-9


def parameters(effort: float | None = None) -> ParameterSet:
    values = {} if effort is None else {"effort": effort}
    return ParameterSet(PROJECTION_PARAMETER_SPECS, values)


def run(
    profile: RouteProfile = SIX_INTERVAL_PROFILE,
    effort: float | None = None,
    curve: PaceCurve = SUPPORT_CURVE,
) -> Projection:
    return project(
        profile,
        curve,
        parameters(effort),
        curve_ref=CURVE_REF,
        endpoints=ENDPOINTS,
    )


# ---------------------------------------------------------------------------
# Les valeurs du brief
# ---------------------------------------------------------------------------


def test_total_duration_at_effort_one() -> None:
    projection = run()
    assert projection.passages[-1].arrival_s == pytest.approx(
        TOTAL_DURATION_S, abs=TIME_ABS_TOLERANCE_S
    )


def test_named_passage_time() -> None:
    projection = run()
    refuge = projection.passages[1]
    assert refuge.point.point is REFUGE
    assert refuge.point.distance_m == 250.0
    assert refuge.arrival_s == pytest.approx(REFUGE_ARRIVAL_S, abs=TIME_ABS_TOLERANCE_S)


def test_effort_below_one_takes_longer() -> None:
    projection = run(effort=0.8)
    assert projection.passages[-1].arrival_s == pytest.approx(
        TOTAL_DURATION_AT_EFFORT_0_8_S, abs=TIME_ABS_TOLERANCE_S
    )


def test_out_of_support_share() -> None:
    """Un tiers de la distance et 56 % du temps passent par le prolongement."""
    _, diagnostics = project_with_diagnostics(
        SIX_INTERVAL_PROFILE,
        SUPPORT_CURVE,
        parameters(),
        curve_ref=CURVE_REF,
        endpoints=ENDPOINTS,
    )
    assert diagnostics.out_of_support_distance_m == pytest.approx(
        OUT_OF_SUPPORT_DISTANCE_M, abs=TIME_ABS_TOLERANCE_S
    )
    assert diagnostics.out_of_support_time_s == pytest.approx(
        OUT_OF_SUPPORT_TIME_S, abs=TIME_ABS_TOLERANCE_S
    )
    assert diagnostics.grade_min == pytest.approx(-0.40)
    assert diagnostics.grade_max == pytest.approx(0.40)


def test_interval_durations_match_the_brief() -> None:
    """Le détail : 200/3 + 40 + 100/3 + 100 + 200 + 100."""
    boundaries = tuple(
        ResolvedPoint(point=REFUGE, distance_m=at_m, elevation_m=1000.0, offset_m=0.0)
        for at_m in SIX_INTERVAL_PROFILE.distance_m[1:-1]
    )
    projection = run(replace(SIX_INTERVAL_PROFILE, resolved_points=boundaries))
    durations = [
        after.arrival_s - before.arrival_s
        for before, after in pairwise(projection.passages)
    ]
    assert durations == pytest.approx(
        [200 / 3, 40.0, 100 / 3, 100.0, 200.0, 100.0], abs=TIME_ABS_TOLERANCE_S
    )


# ---------------------------------------------------------------------------
# Forme de la projection
# ---------------------------------------------------------------------------


def test_start_and_finish_are_always_synthesised() -> None:
    projection = run()
    first, last = projection.passages[0], projection.passages[-1]
    assert len(projection.passages) == 3
    assert first.point.distance_m == 0.0
    assert first.point.point.kind is PointKind.START
    assert first.arrival_s == 0.0
    assert last.point.distance_m == SIX_INTERVAL_PROFILE.distance_m[-1]
    assert last.point.point.kind is PointKind.FINISH
    # Altitudes lues sur le profil lissé, pas sur le fichier.
    assert first.point.elevation_m == SIX_INTERVAL_PROFILE.elevation_m[0]
    assert last.point.elevation_m == SIX_INTERVAL_PROFILE.elevation_m[-1]
    assert first.point.offset_m == last.point.offset_m == 0.0


def test_start_and_finish_are_synthesised_even_over_a_named_place() -> None:
    """Le contrat les exige, même si le GPX porte déjà un lieu à ces abscisses."""
    at_ends = (
        ResolvedPoint(point=REFUGE, distance_m=0.0, elevation_m=1000.0, offset_m=0.0),
        ResolvedPoint(point=REFUGE, distance_m=600.0, elevation_m=1020.0, offset_m=0.0),
    )
    projection = run(replace(SIX_INTERVAL_PROFILE, resolved_points=at_ends))
    assert len(projection.passages) == 4
    assert projection.passages[0].point.point.kind is PointKind.START
    assert projection.passages[-1].point.point.kind is PointKind.FINISH
    # Même abscisse, même temps au bit près.
    assert projection.passages[0].arrival_s == projection.passages[1].arrival_s
    assert projection.passages[-2].arrival_s == projection.passages[-1].arrival_s


def test_two_places_at_the_same_abscissa_both_get_a_passage() -> None:
    """Deux lieux **différents** à la même abscisse donnent deux passages.

    Le nombre de passages est vérifié **avant** les temps : sans lui, dédoublonner
    les ``resolved_points`` ferait disparaître un passage sans qu'aucune assertion
    ne rougisse — la comparaison des temps est sous un ``if`` qui n'aurait plus de
    paire à comparer.
    """
    coincident = tuple(
        ResolvedPoint(
            point=NamedPoint(
                name=name, latitude_deg=45.0, longitude_deg=6.0, elevation_m=None
            ),
            distance_m=250.0,
            elevation_m=1000.0,
            offset_m=0.0,
        )
        for name in ("Fontaine", "Croisement")
    )
    projection = run(replace(SIX_INTERVAL_PROFILE, resolved_points=coincident))
    assert len(projection.passages) == 4
    inner = projection.passages[1:3]
    assert [passage.point.point.name for passage in inner] == [
        "Fontaine",
        "Croisement",
    ]
    assert inner[0].arrival_s == inner[1].arrival_s
    assert inner[0].departure_s == inner[1].departure_s
    assert inner[0].moving_time_s == inner[1].moving_time_s
    assert inner[0].arrival_s == pytest.approx(
        REFUGE_ARRIVAL_S, abs=TIME_ABS_TOLERANCE_S
    )


def test_projection_fields() -> None:
    projection = run()
    assert projection.curve_ref == CURVE_REF
    assert projection.engine_version == ENGINE_VERSION
    assert projection.start_time is None
    assert projection.profile is SIX_INTERVAL_PROFILE
    # Le jeu complet : effort et seuil de support. Ceux de la grille sont déjà
    # dans profile.build_parameters.
    assert set(projection.parameters.values) == {"effort", "curve_min_support_min"}
    assert projection.parameters["effort"] == 1.0


def test_generated_at_defaults_to_an_aware_instant() -> None:
    assert run().generated_at.tzinfo is not None


def test_generated_at_is_honoured_when_given() -> None:
    moment = datetime(2026, 3, 1, 8, 0, tzinfo=UTC)
    projection = project(
        SIX_INTERVAL_PROFILE,
        SUPPORT_CURVE,
        parameters(),
        curve_ref=CURVE_REF,
        endpoints=ENDPOINTS,
        generated_at=moment,
    )
    assert projection.generated_at == moment


def test_route_endpoints_read_the_file_elevations() -> None:
    start, finish = route_endpoints(LOLLIPOP_ROUTE)
    assert start.name == "Départ"
    assert start.kind is PointKind.START
    assert start.latitude_deg == LOLLIPOP_ROUTE.latitude_deg[0]
    assert start.longitude_deg == LOLLIPOP_ROUTE.longitude_deg[0]
    assert start.elevation_m == LOLLIPOP_ROUTE.elevation_m[0]
    assert finish.name == "Arrivée"
    assert finish.kind is PointKind.FINISH
    assert finish.latitude_deg == LOLLIPOP_ROUTE.latitude_deg[-1]
    assert finish.longitude_deg == LOLLIPOP_ROUTE.longitude_deg[-1]
    assert finish.elevation_m == LOLLIPOP_ROUTE.elevation_m[-1]


# ---------------------------------------------------------------------------
# Propriétés
# ---------------------------------------------------------------------------


@given(projectable_route_profiles(), model_pace_curves(), efforts())
def test_effort_is_a_pure_homothety_of_time(
    profile: RouteProfile, curve: PaceCurve, effort: float
) -> None:
    """Propriété 1 : T(effort) × effort == T(1)."""
    reference = (
        project(
            profile, curve, parameters(1.0), curve_ref=CURVE_REF, endpoints=ENDPOINTS
        )
        .passages[-1]
        .arrival_s
    )
    scaled = (
        project(
            profile, curve, parameters(effort), curve_ref=CURVE_REF, endpoints=ENDPOINTS
        )
        .passages[-1]
        .arrival_s
    )
    assert scaled * effort == pytest.approx(reference, rel=1e-9)


@given(projectable_route_profiles(), model_pace_curves(), efforts())
def test_times_are_non_decreasing_and_never_stop(
    profile: RouteProfile, curve: PaceCurve, effort: float
) -> None:
    """Propriété 4 : M3 ignore les arrêts, et les cumuls croissent au sens large."""
    projection = project(
        profile, curve, parameters(effort), curve_ref=CURVE_REF, endpoints=ENDPOINTS
    )
    for passage in projection.passages:
        assert passage.moving_time_s == passage.arrival_s == passage.departure_s
        assert math.isfinite(passage.arrival_s)
    for before, after in pairwise(projection.passages):
        assert after.arrival_s >= before.arrival_s


@given(projectable_route_profiles(duplicate_passage=True), model_pace_curves())
def test_same_abscissa_gives_the_same_bits(
    profile: RouteProfile, curve: PaceCurve
) -> None:
    """Propriété 5 : identiques au bit près, pas seulement à la tolérance près."""
    projection = project(
        profile, curve, parameters(), curve_ref=CURVE_REF, endpoints=ENDPOINTS
    )
    for before, after in pairwise(projection.passages):
        if before.point.distance_m == after.point.distance_m:
            assert before.arrival_s == after.arrival_s
            assert before.departure_s == after.departure_s
            assert before.moving_time_s == after.moving_time_s


@given(projectable_route_profiles(), model_pace_curves(), efforts())
def test_segments_and_stops_close_the_total(
    profile: RouteProfile, curve: PaceCurve, effort: float
) -> None:
    """Propriété 6 : l'invariant central de ``Projection``, sur du vrai calcul.

    Les arrêts se somment sur les passages **intérieurs** : sommer ceux de tous les
    passages donnerait une autre quantité.
    """
    projection = project(
        profile, curve, parameters(effort), curve_ref=CURVE_REF, endpoints=ENDPOINTS
    )
    total = sum(segment.duration_s for segment in projection.segments)
    total += sum(passage.stop_duration_s for passage in projection.passages[1:-1])
    expected = projection.passages[-1].arrival_s - projection.passages[0].departure_s
    assert total == pytest.approx(expected, abs=TIME_TOLERANCE_S)


def subdivide(profile: RouteProfile) -> RouteProfile:
    """Double la densité de points, altitudes interpolées linéairement.

    Chaque sous-intervalle garde la pente de son parent : le temps total ne doit
    pas bouger.
    """
    distance_m: list[float] = []
    elevation_m: list[float] = []
    for (d0, d1), (e0, e1) in zip(
        pairwise(profile.distance_m), pairwise(profile.elevation_m), strict=True
    ):
        distance_m += [d0, (d0 + d1) / 2]
        elevation_m += [e0, (e0 + e1) / 2]
    distance_m.append(profile.distance_m[-1])
    elevation_m.append(profile.elevation_m[-1])
    return replace(
        profile, distance_m=tuple(distance_m), elevation_m=tuple(elevation_m)
    )


@given(projectable_route_profiles(), model_pace_curves())
def test_doubling_the_grid_density_does_not_change_the_time(
    profile: RouteProfile, curve: PaceCurve
) -> None:
    """Propriété 7 : additivité. C'est elle qui attrape une erreur d'intégration.

    À ne pas confondre avec l'invariance au changement de largeur de lissage, qui
    est **fausse** (biais d'échelle mesuré à 3 %) : ici les altitudes interpolées ne
    changent pas, donc les pentes non plus.
    """
    coarse = project(
        profile, curve, parameters(), curve_ref=CURVE_REF, endpoints=ENDPOINTS
    )
    fine = project(
        subdivide(profile),
        curve,
        parameters(),
        curve_ref=CURVE_REF,
        endpoints=ENDPOINTS,
    )
    assert fine.passages[-1].arrival_s == pytest.approx(
        coarse.passages[-1].arrival_s, rel=1e-9
    )


@given(projectable_route_profiles(), model_pace_curves())
def test_diagnostics_never_exceed_the_whole_route(
    profile: RouteProfile, curve: PaceCurve
) -> None:
    projection, diagnostics = project_with_diagnostics(
        profile, curve, parameters(), curve_ref=CURVE_REF, endpoints=ENDPOINTS
    )
    assert 0.0 <= diagnostics.out_of_support_distance_m <= profile.distance_m[-1]
    total_s = projection.passages[-1].arrival_s
    assert 0.0 <= diagnostics.out_of_support_time_s <= total_s + TIME_TOLERANCE_S
    assert diagnostics.grade_min <= diagnostics.grade_max
