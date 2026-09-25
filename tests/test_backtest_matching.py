"""Appariement des points de score (§§ 5a.5 à 5a.8 du brief M4a-2a, ``0010`` D4).

Un test par ligne du tableau du § 7.2a (33 lignes) : statuts, ``t*``, ``π``, ``d_r``,
écart latéral, comptes et bornes effectives quand la ligne les donne, à ``1e−6`` ;
un point non listé d'une ligne est ``ABSENT``. Puis les reconstructions à 0° et 60°,
les tests directs de ``crossing_candidates`` et ``group_events``, les fixtures de
session S01 à S03, et les positions fractionnaires du § 5a.5.
"""

import math

import pytest

from fixtures import matching as cases
from fixtures.matching import (
    GREENWICH_EAST_DEG,
    GREENWICH_WEST_DEG,
    MatchCase,
    degree_trace,
    local_trace,
    matching_parameters,
)
from mountain_perf.backtest import (
    build_series,
    match_points,
    raw_position_at,
    realized_at,
    time_at,
    trace_route,
)
from mountain_perf.backtest.geometry import frame_at
from mountain_perf.backtest.matching import (
    CrossingCandidate,
    crossing_candidates,
    group_events,
    window_bound_m,
)
from mountain_perf.gpx import PROFILE_PARAMETER_SPECS, build_profile
from mountain_perf.schemas import ParameterSet, PointStatus, ScorePointObservation

FOUND = PointStatus.FOUND
ANCHORED = PointStatus.ANCHORED
AMBIGUOUS = PointStatus.AMBIGUOUS
ABSENT = PointStatus.ABSENT
OUT = PointStatus.OUT_OF_TOLERANCE
UNDEFINED = PointStatus.UNDEFINED_TANGENT

TOLERANCE = 1e-6
"""§ 7.0 : temps, positions ``π`` et distances à ``1e−6`` sur les valeurs publiées."""


def expect(
    point: ScorePointObservation,
    status: PointStatus,
    *,
    t: float | None = None,
    pi: float | None = None,
    dr: float | None = None,
    lateral: float | None = None,
    bound: float | None = None,
    c: int | None = None,
    e: int | None = None,
) -> None:
    """Vérifie un point contre une cellule du § 7.2a ; ce qui n'est pas donné n'est
    pas vérifié, sauf le statut."""
    assert point.status is status, f"point {point.index} : {point.status}"
    for value, expected in (
        (point.time_s, t),
        (point.position, pi),
        (point.realized_m, dr),
        (point.lateral_m, lateral),
        (point.effective_m, bound),
    ):
        if expected is not None:
            assert value == pytest.approx(expected, abs=TOLERANCE)
    if c is not None:
        assert point.candidate_count == c
    if e is not None:
        assert point.event_count == e


def statuses(points: tuple[ScorePointObservation, ...]) -> list[PointStatus]:
    return [point.status for point in points]


def _only_point(points: tuple[ScorePointObservation, ...], k: int) -> None:
    """Un point non listé d'une ligne est ``ABSENT``."""
    assert [p.status for p in points if p.index != k] == [ABSENT] * (len(points) - 1)


# ---------------------------------------------------------------------------
# § 7.2a — une ligne, un test
# ---------------------------------------------------------------------------


def test_t01_found_at_two_metres_per_second() -> None:
    """D4.5, D4.8 (arrivée fermée) — T01 : ``t*``, ``π`` et ``d_r`` distincts."""
    p = cases.t01().match()
    expect(p[0], FOUND, t=0, pi=0, dr=0, c=1, e=1)
    expect(p[1], FOUND, t=125, pi=62.5, dr=250, c=1, e=1)
    expect(p[2], FOUND, t=250, pi=125, dr=500, c=1, e=1)
    expect(p[3], FOUND, t=260, pi=130, dr=520, c=1, e=1)


def test_t01_bis_stationary_start_is_dated_on_the_last_instant() -> None:
    """D4.8 — T01-bis : immobile sur la ligne de départ, daté au dernier instant."""
    p = cases.t01_bis().match()
    expect(p[0], FOUND, t=10, pi=5, dr=0)
    expect(p[1], FOUND, t=135, pi=67.5)
    expect(p[2], FOUND, t=260, pi=130)
    expect(p[3], FOUND, t=270, pi=135)


def test_x01_both_ends_anchored() -> None:
    """D4.8 — X01 : départ et arrivée ancrés, écarts latéraux non nuls, instant
    d'arrivée ancrée lu en ``π = n − 1``."""
    p = cases.x01().match()
    expect(p[0], ANCHORED, bound=25.0, t=0, pi=0, dr=0, lateral=8, c=0, e=0)
    expect(p[1], FOUND, t=150, pi=75, dr=225.095516, lateral=1.4375)
    expect(p[2], FOUND, t=316.666667, pi=158.333333, dr=475.201917, lateral=-5.854167)
    expect(
        p[3], ANCHORED, bound=505.0, t=320, pi=160, dr=480.204048, lateral=-6, c=0, e=0
    )


def test_x03_departure_projection_tie_is_ambiguous() -> None:
    """D4.8 (précision) — X03 : minima de distance 5 en 10 et ≈ 40 m."""
    p = cases.x03().match()
    expect(p[0], AMBIGUOUS, bound=0.0, c=0, e=0)
    expect(p[1], FOUND, t=235.000031, pi=235.000031, dr=234.999992)
    expect(p[2], FOUND, t=325, pi=325, dr=324.999961)


def test_x03_arrival_projection_tie_is_ambiguous() -> None:
    """D4.8 (précision) — X03-arrivée : même égalité, chemin de code de l'arrivée."""
    p = cases.x03_arrival().match()
    expect(p[0], FOUND, t=0)
    expect(p[1], FOUND, t=250)
    expect(p[2], AMBIGUOUS, c=0, e=0)


def test_x03_bis_arrival_projection_behind_the_previous_bound() -> None:
    """D4.8 — X03-bis : ``s'_K = 495 <= b_{K−1} = 500`` : absente."""
    p = cases.x03_bis().match()
    expect(p[0], FOUND, t=0)
    expect(p[1], FOUND, t=250)
    expect(p[2], FOUND, t=500)
    expect(p[3], ABSENT)


def test_x08_elbow_departure_projects_on_the_second_branch() -> None:
    """D4.8 — X08 coude : ``b_0 = 25`` (projection), pas ``s + h``."""
    p = cases.x08_elbow().match()
    expect(p[0], ANCHORED, bound=25, t=0, pi=0, dr=0, lateral=-0.485071)
    expect(p[1], FOUND, t=112.5, pi=112.5, dr=225, lateral=-1.999928)
    expect(p[2], ANCHORED, bound=311, t=143, pi=143, dr=286, lateral=-1.999906)


def test_x08_mirror_arrival_projects_on_the_first_branch() -> None:
    """D4.8 — X08 miroir : ``b_K = 295`` (projection), pas ``s + h = 297,44``."""
    p = cases.x08_mirror().match()
    expect(p[0], ANCHORED, bound=9, t=0, pi=0, dr=0, lateral=1.999906)
    expect(p[1], FOUND, t=120.5, pi=120.5, dr=241, lateral=1.999984)
    expect(p[2], ANCHORED, bound=295, t=143, pi=143, dr=286, lateral=0.485071)


def test_x09_rejected_departure_with_an_oriented_crossing() -> None:
    """D4.7 (précision) appliquée à D4.8 — X09 : départ ancrable, projection en
    45 m > ε, et un franchissement orienté non admissible : ``hors ε``."""
    p = cases.x09().match()
    expect(p[0], OUT, c=0, e=0)
    expect(p[1], FOUND, t=247, pi=247, dr=247.015341)
    expect(p[2], FOUND, t=322, pi=322, dr=322.015341)


def test_x10_rejected_arrival_without_crossing() -> None:
    """D4.8 — X10 : projection en 280 m, ``L − s'_K = 45 > ε`` : absente."""
    p = cases.x10().match()
    expect(p[0], FOUND, t=0)
    expect(p[1], FOUND, t=250)
    expect(p[2], ABSENT)


def test_x11_arrival_record_outside_the_window() -> None:
    """D4.8 — X11 : dernier enregistrement ancrable, mais ``d_r = 1 698 > 1 425``."""
    p = cases.x11().match()
    expect(p[0], FOUND, t=0)
    expect(p[1], FOUND, t=125)
    expect(p[2], FOUND, t=250)
    expect(p[3], ABSENT)


def test_x12_arrival_compared_with_the_anchored_departure_bound() -> None:
    """D4.8 — X12, ``K = 1`` : ``s'_K = 22 <= b_0 = 25`` (et non ``s_0 = 0``)."""
    p = cases.x12().match()
    expect(p[0], ANCHORED, bound=25)
    expect(p[1], ABSENT)


def test_x13_crossing_beyond_the_window_inside_a_straddling_interval() -> None:
    """D4.6 — X13 : l'intervalle de 10 s commence dans la fenêtre, mais le
    franchissement de ``x = 500`` en sort (``d_r ≈ 1 180 > 1 175``)."""
    p = cases.x13().match()
    expect(p[0], FOUND, t=0)
    expect(p[1], FOUND, t=125)
    expect(p[2], ABSENT)
    expect(p[3], FOUND, t=675, pi=666, dr=1429.987726)
    expect(p[4], FOUND, t=800.000001, pi=791.000001, dr=1679.987726)
    expect(p[5], FOUND, t=805, pi=796, dr=1689.987725)


def test_x14_undefined_tangent_leaves_the_state_unchanged() -> None:
    """D4.3, D4.6 — X14 : après la tangente indéfinie, ``D = 1 675`` (``k_der = 0``) ;
    avec ``k_der = 1``, ``D = 987,5`` et l'arrivée serait perdue."""
    p = cases.x14().match()
    expect(p[0], FOUND, t=0)
    expect(p[1], UNDEFINED, c=0, e=0)
    expect(p[2], FOUND, t=524, pi=524, dr=1048)


def test_x04_candidates_separated_by_a_gap_are_two_events() -> None:
    """D4.7, D4.9 — X04 : deux candidats, à 1 s et 103 s, dans deux blocs."""
    p = cases.x04().match()
    expect(p[1], AMBIGUOUS, c=2, e=2)
    _only_point(p, 1)


def test_x05_ten_second_step_is_not_a_gap() -> None:
    """D4.9 — X05 : un pas de 10 s porte un franchissement."""
    p = cases.x05().match()
    expect(p[0], FOUND, t=0, pi=0, dr=0)
    expect(p[1], FOUND, t=10, pi=1, dr=20)


def test_t02_signed_lateral_interpolation() -> None:
    """D4.5 — T02 : de ``−40`` à ``+40`` m, l'écart interpolé est nul ; une
    interpolation des valeurs absolues rendrait 40 m et le rejet."""
    p = cases.t02().match()
    expect(p[1], FOUND, t=5, pi=0.5, dr=40.012501)
    assert p[1].lateral_m is not None
    assert abs(p[1].lateral_m) < 1e-5
    _only_point(p, 1)


def test_t03_cluster_is_one_event_dated_by_its_last_candidate() -> None:
    """D4.7 — T03 grappe : un événement de deux candidats, daté à 5 s."""
    p = cases.t03_cluster().match()
    expect(p[1], FOUND, t=5, pi=2.5, dr=5, c=2, e=1)
    _only_point(p, 1)


def test_t03_branches_subpath_leaving_the_disc_splits_the_event() -> None:
    """D4.7 — T03 branches : le sous-chemin passe à 20 m de ``Q`` : deux événements."""
    p = cases.t03_branches().match()
    expect(p[1], AMBIGUOUS, c=2, e=2)
    _only_point(p, 1)


def test_t03_east_cluster_distance_uses_the_cosine() -> None:
    """D4.3, D4.7 — T03 est : écart de 12 m vers l'est ; sans ``cos φ``, 17 m et deux
    événements."""
    p = cases.t03_east().match()
    expect(p[1], FOUND, t=9, pi=4.5, dr=28.999058, c=2, e=1)
    _only_point(p, 1)


def test_half_turn_has_an_undefined_tangent() -> None:
    """D4.3 — Demi-tour : ``L = 549,999999957``, tangente indéfinie au point 1."""
    case = cases.half_turn()
    assert case.geometry.length_m == pytest.approx(549.999999957, abs=TOLERANCE)
    p = case.match()
    expect(p[0], FOUND, t=0)
    expect(p[1], UNDEFINED)
    expect(p[2], FOUND, t=550)


def test_t05_gap_does_not_prevent_crossings_outside_it() -> None:
    """D4.9 — T05 : un trou de 11 s avant le point 1 ; les ``π`` en tiennent compte."""
    p = cases.t05().match()
    expect(p[0], FOUND, t=0, pi=0)
    expect(p[1], FOUND, t=250, pi=240)
    expect(p[2], FOUND, t=500, pi=490)
    expect(p[3], FOUND, t=510, pi=500)


def test_t05_bis_no_crossing_through_a_gap() -> None:
    """D4.9 — T05-bis : le seul franchissement du point 1 est dans un pas de 11 s."""
    p = cases.t05_bis().match()
    assert statuses(p) == [FOUND, ABSENT, FOUND, FOUND]
    expect(p[0], FOUND, t=0)
    expect(p[2], FOUND, t=500)
    expect(p[3], FOUND, t=510)


def test_t05_ter_crossing_inside_a_ten_second_step() -> None:
    """D4.9 — T05-ter : 10 s n'est pas un trou (instants entiers, exacts)."""
    p = cases.t05_ter().match()
    expect(p[0], FOUND, t=0, pi=0)
    expect(p[1], FOUND, t=250, pi=245.5)
    expect(p[2], FOUND, t=500, pi=491)
    expect(p[3], FOUND, t=510, pi=501)


def test_t07_closed_crossings_at_the_same_position_are_merged() -> None:
    """D4.7, D4.8 — T07 : deux franchissements fermés de même ``π``, confondus."""
    p = cases.t07().match()
    expect(p[0], ABSENT)
    expect(p[1], FOUND, t=5, pi=5)
    expect(p[2], FOUND, t=25, pi=25, c=1)


def test_window_bound_on_realized_distance_and_unchanged_after_absent() -> None:
    """D4.6 — Fenêtre : ``x = 500`` franchi à ``d_r ≈ 1 280 > D = 1 175`` ; au point
    3, ``D = 250 + 2,5·250·2 + 300 = 1 800``, l'état est resté celui du point 1."""
    case = cases.window()
    assert case.geometry.length_m == pytest.approx(1499.999996535, abs=TOLERANCE)
    p = case.match()
    expected = [
        (0, 0),
        (125, 250.000001),
        None,
        (765.000001, 1529.985922),
        (890.000001, 1779.985922),
        (1015.000001, 2029.985923),
        (1140, 2279.985920),
    ]
    for point, values in zip(p, expected, strict=True):
        if values is None:
            expect(point, ABSENT)
        else:
            expect(point, FOUND, t=values[0], pi=values[0], dr=values[1])


def test_out_of_tolerance_everywhere() -> None:
    """D4.7 (précision) — Hors ε : franchissements orientés à 40 m, aucun admissible."""
    p = cases.out_of_tolerance().match()
    for point in p:
        expect(point, OUT, c=0, e=0)
    assert len(p) == 4


def test_29_m_east_is_within_tolerance_on_the_right() -> None:
    """D4.3, D4.5 — À 29 m à l'est : écart négatif (à droite) ; sans ``cos φ``, 41 m."""
    p = cases.east_29().match()
    for point, t, lateral in zip(
        p,
        (0, 250, 500, 510),
        (-29.000000, -28.998862, -28.997724, -28.997678),
        strict=True,
    ):
        expect(point, FOUND, t=t, lateral=lateral)
    expect(p[3], FOUND, c=1)


def test_zigzag_realized_distance_and_profile_of_the_trace() -> None:
    """D4.4, D3 — Zigzag : ``d_r`` sur positions brutes ; le profil ``0008`` de la
    trace en ``Route`` a la même longueur que le ``d_r`` final."""
    case = cases.zigzag()
    p = case.match()
    for point, t, dr in zip(
        p,
        (0, 250, 500, 510),
        (0, 365.156265, 730.312538, 744.918784),
        strict=True,
    ):
        expect(point, FOUND, t=t, dr=dr)
    profile = build_profile(
        trace_route(case.trace, "Zigzag"), ParameterSet(PROFILE_PARAMETER_SPECS)
    )
    final_m = build_series(case.trace).realized_distance_m[-1]
    assert profile.distance_m[-1] == pytest.approx(final_m, rel=1e-9)


def test_without_prepared_reference_is_the_trace_itself() -> None:
    """D3 — Sans préparé : la trace en ``Route`` par ``trace_route``, ``L = 600``."""
    case = cases.without_prepared()
    assert case.geometry.length_m == pytest.approx(600, abs=TOLERANCE)
    p = case.match()
    for point, t in zip(p, (0, 250, 500, 600), strict=True):
        expect(point, FOUND, t=t)


def test_corner_half_chord_leans_the_normal() -> None:
    """D4.3 — Coin : la corde de 25 m de part et d'autre de ``s = 250`` penche la
    normale ; une demi-corde de 5 m rendrait 32 m et le rejet."""
    case = cases.corner()
    assert case.geometry.length_m == pytest.approx(539.999999986, abs=TOLERANCE)
    p = case.match()
    expect(p[0], FOUND, t=0)
    expect(p[1], FOUND, t=225.872310, pi=225.872310, dr=225.884924, lateral=25.926010)
    expect(p[2], FOUND, t=474, pi=474, dr=474.031144)
    expect(p[3], FOUND, t=514, pi=514, dr=514.031144)


def test_arrival_cluster_is_dated_by_its_first_candidate() -> None:
    """D4.7, D4.8 — Arrivée en grappe : un événement de deux candidats (510 et
    518 s), daté du premier."""
    p = cases.arrival_cluster().match()
    expect(p[0], FOUND, t=0)
    expect(p[1], FOUND, t=250)
    expect(p[2], FOUND, t=500)
    expect(p[3], FOUND, t=510, c=2, e=1)


def test_arrival_from_ahead_is_not_a_crossing() -> None:
    """D4.8 — Arrivée par l'avant : ``h = 0`` sur les deux derniers intervalles ; la
    paire ``(0, 0)`` n'est pas un franchissement."""
    p = cases.arrival_from_ahead().match()
    assert statuses(p) == [ABSENT] * 4


# ---------------------------------------------------------------------------
# Correctifs de la PR #9 — garanties écrites qu'aucune ligne du § 7.2a ne distinguait
# ---------------------------------------------------------------------------


def test_outer_elbow_departure_projects_on_the_vertex() -> None:
    """R2 : le départ se projette sur le sommet du coude (``t_i = 1``, ``t_{i+1} =
    0``), à 5 m ; sans la règle « sommet », aucun candidat de projection."""
    p = cases.outer_elbow().match()
    assert len(cases.outer_elbow().trace.time_s) == 148
    assert statuses(p) == [ANCHORED, FOUND, ANCHORED]
    expect(p[0], ANCHORED, bound=20.0, lateral=-8.731283, t=0, c=0, e=0)
    expect(p[1], FOUND, pi=116.5, lateral=-1.999928)
    expect(p[2], ANCHORED, bound=311.0, t=147)


# ---------------------------------------------------------------------------
# § 8, test 4 — reconstructions à 0° et à 60° de latitude de base
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("base_latitude_deg", [0.0, 60.0])
def test_t03_east_at_other_latitudes(base_latitude_deg: float) -> None:
    reference = cases.t03_east().match()
    rebuilt = cases.t03_east(base_latitude_deg).match()
    assert statuses(rebuilt) == statuses(reference)
    expect(rebuilt[1], FOUND, t=9, c=2, e=1)


@pytest.mark.parametrize("base_latitude_deg", [0.0, 60.0])
def test_29_m_east_at_other_latitudes(base_latitude_deg: float) -> None:
    reference = cases.east_29().match()
    rebuilt = cases.east_29(base_latitude_deg).match()
    assert statuses(rebuilt) == statuses(reference) == [FOUND] * 4
    for point, t in zip(rebuilt, (0, 250, 500, 510), strict=True):
        expect(point, FOUND, t=t)


# ---------------------------------------------------------------------------
# Fixtures de session (§ 7 du plan) — règles qu'aucune ligne du § 7.2a ne distingue
# ---------------------------------------------------------------------------


def test_s01_next_point_needs_a_position_after_the_current_one() -> None:
    """D4.6 : ``π > π_cur`` strict pour ``k > 0`` — la trace part sur la ligne
    d'arrivée (``π = 0``), qui n'est donc pas un franchissement orienté."""
    assert statuses(cases.s01().match()) == [ABSENT, ABSENT]


def test_s02_ambiguous_point_leaves_the_state_unchanged() -> None:
    """D4.6, D4.7 : après un point ambigu, l'état reste celui du point 0 ; ``x = 500``
    est franchi à ``d_r ≈ 1 348 <= D = 1 550`` (en ``π = 337``, ``t = 674`` s)."""
    p = cases.s02().match()
    assert statuses(p) == [FOUND, AMBIGUOUS, FOUND, FOUND, FOUND]
    expect(p[1], AMBIGUOUS, c=2, e=2)
    expect(p[2], FOUND, t=674, pi=337)


def test_s03_anchoring_never_erases_an_ambiguity() -> None:
    """D4.8 : l'ancrage ne s'applique que sans candidat admissible ; le départ,
    ancrable, a deux événements et reste ambigu."""
    p = cases.s03().match()
    expect(p[0], AMBIGUOUS, bound=0.0, c=2, e=2)
    assert statuses(p) == [AMBIGUOUS, FOUND, FOUND, FOUND]
    # 22 pas de 3 m jusqu'à (1,5 ; 3), puis 248,5 m à 1,5 m/s.
    expect(p[1], FOUND, pi=22 + 248.5 / 3, t=44 + 248.5 / 1.5)


# ---------------------------------------------------------------------------
# crossing_candidates et group_events, directement (§ 5a.6)
# ---------------------------------------------------------------------------


def _point_1(case: MatchCase) -> tuple[tuple[CrossingCandidate, ...], int]:
    geometry = case.geometry
    frame = frame_at(geometry, 250.0)
    assert frame is not None
    series = build_series(case.trace)
    return crossing_candidates(
        case.trace,
        series,
        frame,
        0.0,
        window_bound_m(0.0, 250.0, 1, 0),
        closed=False,
        tolerance_m=30.0,
        departure=False,
    )


def test_crossing_candidates_on_t03_cluster() -> None:
    candidates, oriented = _point_1(cases.t03_cluster())
    assert oriented == 2
    assert [c.position for c in candidates] == pytest.approx([0.5, 2.5], abs=TOLERANCE)
    assert all(abs(c.lateral_m) < 1e-6 for c in candidates)


def test_group_events_on_t03_cluster_and_x04() -> None:
    for case, sizes in ((cases.t03_cluster(), [2]), (cases.x04(), [1, 1])):
        candidates, _ = _point_1(case)
        frame = frame_at(case.geometry, 250.0)
        assert frame is not None
        events = group_events(
            case.trace, build_series(case.trace), frame, candidates, 15.0
        )
        assert [len(event) for event in events] == sizes


def test_crossing_candidates_on_x04() -> None:
    """X04 : deux franchissements orientés admissibles, de part et d'autre du trou ;
    c'est ``group_events`` qui les sépare."""
    candidates, oriented = _point_1(cases.x04())
    assert oriented == 2
    assert [c.position for c in candidates] == pytest.approx([0.5, 2.5], abs=TOLERANCE)


def test_group_events_without_candidate() -> None:
    case = cases.t03_cluster()
    frame = frame_at(case.geometry, 250.0)
    assert frame is not None
    assert group_events(case.trace, build_series(case.trace), frame, (), 15.0) == ()


# ---------------------------------------------------------------------------
# Positions fractionnaires (§ 5a.5) et préconditions (§ 5a.8)
# ---------------------------------------------------------------------------

POSITIONS_TRACE = local_trace(
    [0.0, 2.0, 5.0, 9.0], [(0.0, 0.0), (3.0, 1.0), (9.0, -2.0), (10.0, 4.0)]
)


def test_positions_are_exact_at_each_record() -> None:
    """``t(π)``, ``d_r(π)`` et ``P(π)`` rendent l'enregistrement en ``π`` entier,
    ``n − 1`` compris."""
    trace = POSITIONS_TRACE
    series = build_series(trace)
    for j in range(len(trace.time_s)):
        assert time_at(trace, float(j)) == trace.time_s[j]
        assert realized_at(series, float(j)) == series.realized_distance_m[j]
        assert raw_position_at(trace, float(j)) == (
            trace.latitude_deg[j],
            trace.longitude_deg[j],
        )


def test_positions_are_linear_between_records() -> None:
    trace = POSITIONS_TRACE
    series = build_series(trace)
    assert time_at(trace, 1.25) == pytest.approx(2.0 + 0.25 * 3.0)
    d = series.realized_distance_m
    assert realized_at(series, 2.5) == pytest.approx(0.5 * d[2] + 0.5 * d[3])
    lat, lon = raw_position_at(trace, 0.5)
    assert lat == pytest.approx((trace.latitude_deg[0] + trace.latitude_deg[1]) / 2)
    assert lon == pytest.approx((trace.longitude_deg[0] + trace.longitude_deg[1]) / 2)


@pytest.mark.parametrize("position", [-0.5, 3.5, math.nan])
def test_positions_outside_the_trace_are_refused(position: float) -> None:
    trace = POSITIONS_TRACE
    series = build_series(trace)
    with pytest.raises(ValueError, match="hors de"):
        time_at(trace, position)
    with pytest.raises(ValueError, match="hors de"):
        realized_at(series, position)
    with pytest.raises(ValueError, match="hors de"):
        raw_position_at(trace, position)


def test_time_and_realized_distance_are_exact_at_the_last_record() -> None:
    """R1b (correctifs de la PR #9) : en ``π = n − 1``, ``(1 − f)·a + f·b`` rend
    l'enregistrement bit pour bit ; ``a + f·(b − a)`` rendrait
    ``0.8999999999999999``."""
    trace = degree_trace(
        (0.0, 0.2, 0.9),
        (45.0, 45.0, 45.0),
        (6.0, 6.0 + math.degrees(1e-7), 6.0 + math.degrees(2e-7)),
    )
    series = build_series(trace)
    assert time_at(trace, 2.0) == 0.9
    assert realized_at(series, 2.0) == series.realized_distance_m[2]


def test_raw_position_is_exact_at_the_last_record_across_a_meridian() -> None:
    """R1c (correctifs de la PR #9) : même exactitude pour ``P(π)``, sur un pas qui
    franchit Greenwich."""
    trace = degree_trace(
        (0.0, 1.0, 2.0),
        (45.0, 45.0, 45.0),
        (GREENWICH_WEST_DEG - 1e-4, GREENWICH_WEST_DEG, GREENWICH_EAST_DEG),
    )
    assert raw_position_at(trace, 2.0) == (45.0, 0.007578580617976076)


def test_arrival_on_the_last_vertex_across_a_meridian_is_found() -> None:
    """R1d (correctifs de la PR #9) : la trace finit exactement sur le dernier
    sommet ; ``h = 0`` exactement et l'arrivée est trouvée en ``π = 400`` par la
    condition fermée. Un dernier sommet décalé d'un ulp la ferait ancrer."""
    points = cases.greenwich_arrival().match()
    assert statuses(points) == [FOUND] * 5
    expect(points[-1], FOUND, pi=400, t=800)
    assert points[-1].position == 400.0


def test_match_points_needs_series_built_on_the_trace() -> None:
    case = cases.t01()
    other = build_series(cases.x05().trace)
    with pytest.raises(ValueError, match="longueurs différentes"):
        match_points(case.geometry, case.trace, other, case.parameters)


def test_match_points_needs_matching_parameters() -> None:
    case = cases.t01()
    with pytest.raises(ValueError, match="MATCHING_PARAMETER_SPECS"):
        match_points(
            case.geometry,
            case.trace,
            build_series(case.trace),
            ParameterSet(PROFILE_PARAMETER_SPECS),
        )


def test_one_point_per_grid_rank() -> None:
    """§ 5a.8 : un point par rang de la grille, dans l'ordre, ``nominal_m`` = grille."""
    p = cases.window().match()
    assert [point.index for point in p] == list(range(7))
    assert [point.nominal_m for point in p][:-1] == [250.0 * k for k in range(6)]


def test_other_step_changes_the_grid() -> None:
    case = MatchCase(
        cases.t01().route, cases.t01().trace, matching_parameters(score_step_m=100.0)
    )
    p = case.match()
    assert [point.nominal_m for point in p][:-1] == [100.0 * k for k in range(6)]
    assert statuses(p) == [FOUND] * 7
