"""Règles des passages sur fonctions pures (§ 6.2, § 6.4 à § 6.7, § 7.3.2 et § 8.3,
tests 2 et 4, du brief M4a-3).

``0010`` D4.12. Les égalités de seuil se testent ici, sur des valeurs exactement
représentables, jamais à travers une trace (§ 7.0) : constantes, prédicats,
rattachement, recherche d'une occurrence sur le repère direct.
"""

import math

import pytest

from fixtures.passages import DIRECT_FRAME, direct_trace
from fixtures.traces import local_deg
from mountain_perf.backtest import (
    ATTRIBUTION_DISTANCE_TIE_M,
    ATTRIBUTION_TIME_TIE_S,
    WAYPOINT_SNAP_M,
    attach_occurrence,
    attribute_episode,
    build_series,
    chronology_violations,
    episode_median,
    in_order,
    maintained,
    near_passage,
    observed_in_prefix,
    occurrence_crossing,
    snaps_to_point,
    time_distance_s,
    windows_overlap,
    within_tie,
)
from mountain_perf.backtest.geometry import to_local
from mountain_perf.schemas import (
    EpisodeOutcome,
    PassageRole,
    PassageStatus,
    RecordedTrace,
    StopEpisode,
)

ARRIVAL = PassageRole.ARRIVAL
DEPARTURE = PassageRole.DEPARTURE
INTERMEDIATE = PassageRole.INTERMEDIATE

GRID = (0.0, 250.0, 500.0, 750.0, 1000.0, 1010.0)
"""Grille du § 7.3.2 : ``Δ = 250``, ``L = 1010``."""


def test_constants_of_0010() -> None:
    """``0010`` D4.12 : 1 m (reprise), 1 s puis 1 m (égalités de l'association)."""
    assert WAYPOINT_SNAP_M == 1.0
    assert ATTRIBUTION_TIME_TIE_S == 1.0
    assert ATTRIBUTION_DISTANCE_TIE_M == 1.0


# ---------------------------------------------------------------------------
# Prédicats aux égalités (§ 6.2, § 7.3.2)
# ---------------------------------------------------------------------------


def test_snaps_to_point_is_strict() -> None:
    """Choix 1 : à 1 m exactement, l'occurrence est encadrée."""
    assert not snaps_to_point(1.0)
    assert snaps_to_point(0.999)


@pytest.mark.parametrize(
    ("arguments", "expected"),
    [
        ((12.0, 12.0, 500.0, 2), True),
        ((500.0, 12.0, 500.0, 2), True),
        ((11.9, 12.0, 500.0, 2), False),
        ((500.1, 12.0, 500.0, 2), False),
        ((12.0, 12.0, 12.0, 0), False),
    ],
    ids=str,
)
def test_observed_in_prefix(
    arguments: tuple[float, float, float, int], expected: bool
) -> None:
    """Choix 2 : ``m >= 1`` et ``b_0 <= s_w <= b_m``, bornes incluses."""
    assert observed_in_prefix(*arguments) is expected


def test_near_passage_is_strict() -> None:
    """``ε`` exactement : non candidate."""
    assert not near_passage(30.0, 30.0)
    assert near_passage(29.999, 30.0)


@pytest.mark.parametrize(
    ("arguments", "expected"),
    [
        ((100.0, 160.0, 160.0, 200.0), True),
        ((100.0, 160.0, 40.0, 100.0), True),
        ((100.0, 160.0, 160.5, 200.0), False),
    ],
    ids=str,
)
def test_windows_overlap_on_contact(
    arguments: tuple[float, float, float, float], expected: bool
) -> None:
    """Un contact est un chevauchement."""
    assert windows_overlap(*arguments) is expected


@pytest.mark.parametrize(
    ("time_s", "expected"),
    [(100.0, 0.0), (110.0, 0.0), (130.0, 0.0), (90.0, 10.0), (170.0, 10.0)],
)
def test_time_distance_to_the_episode(time_s: float, expected: float) -> None:
    """Choix 9, épisode ``[100 ; 160]`` : nulle dans l'épisode, bornes comprises,
    sinon distance à la borne la plus proche (précision P5 : au commit 3)."""
    assert time_distance_s(time_s, 100.0, 160.0) == expected


def test_within_tie_includes_the_exact_gap() -> None:
    assert within_tie(11.0, 10.0, 1.0)
    assert not within_tie(11.5, 10.0, 1.0)


def test_in_order_accepts_equality() -> None:
    assert in_order(100.0, 100.0)
    assert not in_order(100.5, 100.0)


@pytest.mark.parametrize(
    ("arguments", "expected"),
    [
        ((25.0, 25.0, 25.0, 100.0), True),
        ((24.5, 30.0, 25.0, 100.0), False),
        ((30.0, 100.0, 25.0, 100.0), True),
        ((30.0, 100.5, 25.0, 100.0), False),
    ],
    ids=str,
)
def test_maintained_includes_both_bounds(
    arguments: tuple[float, float, float, float], expected: bool
) -> None:
    """Choix 12 : ``t*_0 <= arrivée`` et ``départ <= t*_m``, bornes incluses."""
    assert maintained(*arguments) is expected


# ---------------------------------------------------------------------------
# Rattachement (§ 6.4, § 7.3.2)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("distance_m", "expected"),
    [
        (1009.5, (ARRIVAL, 5, True)),
        (1009.0, (INTERMEDIATE, 4, False)),
        (0.5, (DEPARTURE, 0, True)),
        (1.0, (INTERMEDIATE, 0, False)),
        (500.0, (INTERMEDIATE, 2, True)),
        (249.0, (INTERMEDIATE, 0, False)),
        (249.5, (INTERMEDIATE, 1, True)),
        (250.999, (INTERMEDIATE, 1, True)),
        (251.0, (INTERMEDIATE, 1, False)),
        (1000.5, (INTERMEDIATE, 4, True)),
    ],
    ids=str,
)
def test_attach_occurrence(
    distance_m: float, expected: tuple[PassageRole, int, bool]
) -> None:
    """Choix 1 : arrivée, départ, point ``k``, point ``k + 1``, sinon encadrée ; à
    1 m exactement, encadrée."""
    assert attach_occurrence(distance_m, GRID) == expected


def test_attach_occurrence_takes_the_arrival_first() -> None:
    """Grille ``(0 ; 1,5)`` : ``s_w = 0,7`` est à moins de 1 m des deux extrémités ;
    l'arrivée d'abord (« Arrivée unique »)."""
    assert attach_occurrence(0.7, (0.0, 1.5)) == (ARRIVAL, 1, True)


@pytest.mark.parametrize(
    ("distance_m", "grid_m", "match"),
    [
        (0.0, (0.0,), "grille de 1 point"),
        (0.0, (), "grille de 0 point"),
        (5.0, (1.0, 250.0), "commençant à 1.0"),
        (5.0, (0.0, 250.0, 250.0, 300.0), "non strictement croissante"),
        (5.0, (0.0, 250.0, 200.0), "non strictement croissante"),
        (-0.5, GRID, "hors de"),
        (1010.5, GRID, "hors de"),
    ],
    ids=["one_point", "empty", "first", "equal", "decreasing", "below", "above"],
)
def test_attach_occurrence_preconditions(
    distance_m: float, grid_m: tuple[float, ...], match: str
) -> None:
    with pytest.raises(ValueError, match=match):
        attach_occurrence(distance_m, grid_m)


# ---------------------------------------------------------------------------
# Recherche d'une occurrence sur le repère direct (§ 6.4, § 7.3.2)
# ---------------------------------------------------------------------------

STRAIGHT = (-2.0, -1.0, 0.0, 1.0, 2.0)
STEP = (-2.0, -1.0, 1.0, 2.0)


def _crossing(
    trace: RecordedTrace, after: float, before: float
) -> tuple[PassageStatus, float | None]:
    return occurrence_crossing(
        trace, build_series(trace), DIRECT_FRAME, after, before, 30.0, 15.0
    )


@pytest.mark.parametrize(
    ("trace", "after", "before", "expected"),
    [
        pytest.param(
            direct_trace((-3.0, -2.0, -1.0, 0.0, -1.0, -2.0)),
            0.0,
            5.0,
            (PassageStatus.ABSENT, None),
            id="touches_and_backs_off",
        ),
        pytest.param(
            direct_trace(STRAIGHT),
            2.0,
            4.0,
            (PassageStatus.ABSENT, None),
            id="at_after",
        ),
        pytest.param(
            direct_trace(STRAIGHT), 1.5, 4.0, (PassageStatus.FOUND, 2.0), id="after_1.5"
        ),
        pytest.param(
            direct_trace(STRAIGHT),
            0.0,
            2.0,
            (PassageStatus.ABSENT, None),
            id="at_before",
        ),
        pytest.param(
            direct_trace(STRAIGHT),
            0.0,
            2.5,
            (PassageStatus.FOUND, 2.0),
            id="before_2.5",
        ),
        pytest.param(
            direct_trace(STEP), 0.0, 1.0, (PassageStatus.ABSENT, None), id="beyond"
        ),
        pytest.param(
            direct_trace(STEP),
            0.0,
            1.5,
            (PassageStatus.ABSENT, None),
            id="at_before_in_interval",
        ),
        pytest.param(
            direct_trace(STEP, y_m=45.0),
            0.0,
            1.25,
            (PassageStatus.ABSENT, None),
            id="oriented_beyond",
        ),
        pytest.param(
            direct_trace(STEP, time_s=(0.0, 1.0, 12.0, 13.0)),
            0.0,
            3.0,
            (PassageStatus.ABSENT, None),
            id="gap",
        ),
        pytest.param(
            direct_trace(STEP, y_m=45.0),
            0.0,
            3.0,
            (PassageStatus.OUT_OF_TOLERANCE, None),
            id="out_of_tolerance",
        ),
        pytest.param(
            direct_trace((-2.0, -1.0, 1.0, -1.0, 1.0, 2.0)),
            0.0,
            5.0,
            (PassageStatus.FOUND, 3.5),
            id="last_candidate",
        ),
        pytest.param(
            direct_trace((-2.0, -1.0, 1.0, -20.0, -19.0, 1.0, 2.0)),
            0.0,
            6.0,
            (PassageStatus.AMBIGUOUS, None),
            id="two_events",
        ),
    ],
)
def test_occurrence_crossing(
    trace: RecordedTrace,
    after: float,
    before: float,
    expected: tuple[PassageStatus, float | None],
) -> None:
    """Choix 4 : condition ouverte, ``π_k < π < π_{k+1}`` strictes, candidats
    admissibles si l'écart latéral est ``< ε``, regroupés au rayon ``r_c``, datés
    par le dernier candidat ; ``hors ε`` s'il y a un franchissement orienté dans
    l'intervalle, ``absent`` sinon. Positions exactes : ``π = 2`` sur un
    enregistrement confondu avec l'ancre, ``π = 1,5`` et ``3,5`` entre ``x = −1`` et
    ``x = 1``."""
    assert _crossing(trace, after, before) == expected


# ---------------------------------------------------------------------------
# Association et chronologie (§ 6.5, § 6.7, § 7.3.2)
# ---------------------------------------------------------------------------

ATTRIBUTED = EpisodeOutcome.ATTRIBUTED
TIE = EpisodeOutcome.TIE

ATTRIBUTION_TABLE: tuple[
    tuple[str, tuple[tuple[int, float, float], ...], tuple[EpisodeOutcome, int | None]],
    ...,
] = (
    ("1", ((0, 90.0, 10.0), (1, 170.0, 10.0)), (TIE, None)),
    ("2 (1,5 s > 1 s)", ((0, 90.0, 10.0), (1, 171.5, 10.0)), (ATTRIBUTED, 0)),
    ("3", ((0, 90.0, 10.0), (1, 170.5, 10.0)), (TIE, None)),
    ("4 (1,5 m > 1 m)", ((0, 90.0, 10.0), (1, 170.5, 11.5)), (ATTRIBUTED, 0)),
    ("5 (1 s exactement)", ((0, 90.0, 10.0), (1, 171.0, 10.0)), (TIE, None)),
    ("6 (1 m exactement)", ((0, 90.0, 10.0), (1, 170.5, 11.0)), (TIE, None)),
    ("7", ((0, 90.0, 10.0), (1, 170.75, 10.0)), (TIE, None)),
    ("8", ((0, 90.0, 10.0), (1, 170.5, 10.75)), (TIE, None)),
    ("9 (le temps d'abord)", ((0, 130.0, 12.0), (1, 170.0, 10.0)), (ATTRIBUTED, 0)),
    ("10 (deux distances nulles)", ((0, 102.0, 10.0), (1, 131.0, 10.0)), (TIE, None)),
    (
        "11 (l'espace ne départage que les gardées par le temps)",
        ((0, 90.0, 10.0), (1, 170.0, 10.0), (2, 200.0, 1.0)),
        (TIE, None),
    ),
    ("12 (aucune)", (), (EpisodeOutcome.NO_CANDIDATE, None)),
    ("13", ((3, 500.0, 29.0),), (ATTRIBUTED, 3)),
    (
        "14 (minimum spatial parmi les gardées par le temps)",
        ((0, 90.0, 10.0), (1, 170.0, 11.5), (2, 200.0, 1.0)),
        (ATTRIBUTED, 0),
    ),
)
"""Les quatorze lignes de ``attribute_episode(100, 160, …)`` du § 7.3.2."""


@pytest.mark.parametrize(
    ("candidates", "expected"),
    [(c, e) for _, c, e in ATTRIBUTION_TABLE],
    ids=[label for label, _, _ in ATTRIBUTION_TABLE],
)
def test_attribute_episode(
    candidates: tuple[tuple[int, float, float], ...],
    expected: tuple[EpisodeOutcome, int | None],
) -> None:
    """Choix 9 : distance temporelle à 1 s près du minimum, puis, parmi les gardées,
    distance à la médiane à 1 m près de **leur** minimum ; une seule : attribué ;
    plusieurs : non attribué ; aucune : sans candidate."""
    assert attribute_episode(100.0, 160.0, candidates) == expected


@pytest.mark.parametrize(
    ("envelopes", "final", "expected"),
    [
        (((90.0, 200.0), (150.0, 150.0)), None, (True, True)),
        (((90.0, 520.0),), 510.0, (True,)),
        (((100.0, 100.0), (100.0, 100.0)), None, (False, False)),
        (((0.0, 50.0), (40.0, 60.0), (55.0, 70.0)), None, (True, True, True)),
        (((10.0, 20.0),), 20.0, (False,)),
        (((10.0, 30.0), (40.0, 50.0)), 45.0, (False, True)),
        ((), 100.0, ()),
    ],
    ids=[
        "both_marked",
        "final_only_the_occurrence",
        "equality_in_order",
        "every_pair_judged",
        "final_equality",
        "last_before_final",
        "no_envelope",
    ],
)
def test_chronology_violations(
    envelopes: tuple[tuple[float, float], ...],
    final: float | None,
    expected: tuple[bool, ...],
) -> None:
    """Choix 11 : chaque couple consécutif jugé sur les valeurs données, les deux
    marqués, l'arrivée finale jamais marquée ; égalité : dans l'ordre."""
    assert chronology_violations(envelopes, final) == expected


def test_episode_median_of_smoothed_positions() -> None:
    """Choix 8 : médiane des positions **lissées** des enregistrements
    ``first_record`` à ``last_record`` inclus. ``x = 0, 0, 0, 3, 0, 0, 12`` à 1 Hz :
    les ``x`` lissés des enregistrements 1 à 5 valent 0,75, 0,6, 0,6, 3, 3,75
    (moyenne tronquée au bord du bloc) ; médiane 0,75 — la médiane brute serait 0,
    celle des enregistrements 2 à 4 serait 0,6."""
    trace = direct_trace((0.0, 0.0, 0.0, 3.0, 0.0, 0.0, 12.0))
    episode = StopEpisode(1.0, 5.0, first_record=1, last_record=5)
    lat_deg, lon_deg = episode_median(build_series(trace), episode)
    assert math.hypot(*to_local(*local_deg(0.75, 0.0), lat_deg, lon_deg)) <= 1e-6
