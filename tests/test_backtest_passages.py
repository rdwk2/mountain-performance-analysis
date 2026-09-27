"""``observe_passages`` sur les vingt-six lignes du § 7.3.1 du brief M4a-3 (§ 8.3,
test 5).

``0010`` D4.12. Pour chaque ligne : **chaque champ publié de chaque occurrence**
(rôle, statut, ``crossing_s``, fenêtre, ``arrival_s``, ``departure_s``,
``stop_total_s``, ``episode_count``, ``chronology_violation``, ``comparable``,
``unavailability``), y compris ceux que la ligne ne distingue pas — sans épisode,
``arrivée = départ = t*`` et ``S = 0`` ; sans instant, tout absent — ; chaque épisode
(bornes, issue, rang, médiane) ; le rattachement par ``attach_occurrence`` ; et ce que
la ligne annonce de l'appariement (``m``, ``b_m``, ``t*_m``, points). Tolérance
``1e−6`` (s, m) ; statuts, rôles, issues, comptes, rangs et booléens exacts.

Rattachements : ceux que le brief écrit entre parenthèses, et, pour les occurrences
où il ne l'écrit pas, celui que donne le choix 1 (marqués « déduit »).
"""

import math
from collections.abc import Callable
from dataclasses import dataclass, replace

import pytest

from fixtures import passages as p
from fixtures.matching import MatchCase, Point
from fixtures.segments import reference_profile
from fixtures.traces import local_deg
from mountain_perf.backtest import (
    MATCHING_PARAMETER_SPECS,
    attach_occurrence,
    build_series,
    clock_partition,
    observe_passages,
    score_grid,
)
from mountain_perf.backtest.geometry import to_local
from mountain_perf.schemas import (
    EpisodeOutcome,
    MatchResult,
    ParameterSet,
    ParameterSpec,
    PassageRole,
    PassageStatus,
    PointStatus,
    RouteProfile,
    Unavailability,
)

TOLERANCE = 1e-6

DEP = PassageRole.DEPARTURE
ARR = PassageRole.ARRIVAL
INT = PassageRole.INTERMEDIATE
FOUND = PassageStatus.FOUND
ANCHORED = PassageStatus.ANCHORED
AMBIGUOUS = PassageStatus.AMBIGUOUS
OUTSIDE = PassageStatus.OUTSIDE_PREFIX
INSUFFICIENT = Unavailability.INSUFFICIENT_SUPPORT
ATTRIBUTED = EpisodeOutcome.ATTRIBUTED
NO_CANDIDATE = EpisodeOutcome.NO_CANDIDATE
TIE = EpisodeOutcome.TIE


@dataclass(frozen=True)
class Occurrence:
    """Attendu d'une occurrence. Datée : ``arrival_s`` et ``departure_s`` valent
    ``crossing_s`` et ``stop_total_s`` 0 sauf mention."""

    name: str
    distance_m: float
    role: PassageRole
    status: PassageStatus
    attach: tuple[PassageRole, int, bool]
    crossing_s: float | None = None
    window_s: tuple[float, float] | None = None
    arrival_s: float | None = None
    departure_s: float | None = None
    stop_total_s: float | None = None
    episode_count: int = 0
    chronology_violation: bool = False
    comparable: bool = False
    unavailability: Unavailability | None = None


@dataclass(frozen=True)
class Episode:
    start_s: float
    end_s: float
    outcome: EpisodeOutcome
    passage_index: int | None
    median_m: Point


@dataclass(frozen=True)
class Row:
    """Une ligne du § 7.3.1 ; ``rule`` dit ce qu'elle distingue."""

    case: Callable[[], MatchCase]
    rule: str
    passages: tuple[Occurrence, ...]
    episodes: tuple[Episode, ...] = ()
    prefix_count: int | None = None
    prefix_end_m: float | None = None
    prefix_end_s: float | None = None
    start_m: float | None = None
    point_times: tuple[tuple[int, float | None], ...] = ()
    point_statuses: tuple[tuple[int, PointStatus], ...] = ()
    length_m: float | None = None


def _found(
    name: str,
    distance_m: float,
    attach: tuple[PassageRole, int, bool],
    crossing_s: float,
    window_s: tuple[float, float],
    role: PassageRole = INT,
    status: PassageStatus = FOUND,
    *,
    arrival_s: float | None = None,
    departure_s: float | None = None,
    stop_total_s: float | None = None,
    episode_count: int = 0,
    chronology_violation: bool = False,
    comparable: bool | None = None,
    unavailability: Unavailability | None = None,
) -> Occurrence:
    """Occurrence datée ; comparable par défaut, hors départ."""
    return Occurrence(
        name,
        distance_m,
        role,
        status,
        attach,
        crossing_s,
        window_s,
        arrival_s,
        departure_s,
        stop_total_s,
        episode_count,
        chronology_violation,
        role is not DEP if comparable is None else comparable,
        unavailability,
    )


def _undated(
    name: str,
    distance_m: float,
    status: PassageStatus,
    unavailability: Unavailability | None,
    attach: tuple[PassageRole, int, bool],
    role: PassageRole = INT,
) -> Occurrence:
    return Occurrence(
        name, distance_m, role, status, attach, unavailability=unavailability
    )


def _outside(
    name: str, distance_m: float, attach: tuple[PassageRole, int, bool]
) -> Occurrence:
    role = attach[0]
    return _undated(name, distance_m, OUTSIDE, INSUFFICIENT, attach, role)


ROWS: dict[str, Row] = {
    "Passages": Row(
        p.passages,
        "choix 1 et 2 : reprise à moins de 1 m, encadrement, hors préfixe ; un épisode "
        "attribué sous θ_c ; S à part de l'enveloppe",
        (
            _found("B", 250.4, (INT, 1, True), 250.0, (0.0, 620.000001)),
            _found(
                "A",
                375.0,
                (INT, 1, False),
                375.0,
                (250.0, 620.000001),
                departure_s=488.0,
                stop_total_s=96.0,
                episode_count=1,
            ),
            _outside("C", 899.999999, (INT, 3, False)),  # rattachement déduit
        ),
        (Episode(392.0, 488.0, ATTRIBUTED, 1, (380.0, 0.0)),),
        prefix_count=3,
        prefix_end_m=750.0,
        prefix_end_s=870.000001,
    ),
    "Y01": Row(
        p.y01,
        "choix 12 : un épisode attribué fait sortir le départ du préfixe — support "
        "insuffisant, événements conservés",
        (
            _found(
                "w",
                240.0,
                (INT, 0, False),
                620.0,
                (0.0, 820.000005),
                arrival_s=234.0,
                departure_s=1006.0,
                stop_total_s=772.0,
                episode_count=1,
                comparable=False,
                unavailability=INSUFFICIENT,
            ),
        ),
        (Episode(234.0, 1006.0, ATTRIBUTED, 0, (240.0, 0.0)),),
        prefix_count=1,
        prefix_end_s=820.000005,
    ),
    "M05": Row(
        p.m05,
        "choix 1, 3, 11 : départ repris non cible ; deux reprises du point 1 à égalité "
        "(chronologie non stricte) ; arrivée reprise",
        (
            _found("Départ", 0.0, (DEP, 0, True), 0.0, (0.0, 250.0), role=DEP),
            _found("Borne bis", 249.8, (INT, 1, True), 250.0, (0.0, 500.000001)),
            _found("Borne", 250.3, (INT, 1, True), 250.0, (0.0, 500.000001)),
            _found("À 1,5 m", 251.5, (INT, 1, False), 251.5, (250.0, 500.000001)),
            _found(
                "Fin", 1009.999999, (ARR, 5, True), 1010.0, (1000.000001, 1015.0), ARR
            ),
        ),
        prefix_count=5,
        prefix_end_s=1010.0,
    ),
    "M05 ancré": Row(
        p.m05_anchored,
        "choix 2 et 3 : préfixe jugé sur [b_0 ; b_m] ; départ et arrivée repris avec "
        "leur statut ancré",
        (
            _found("Départ", 0.0, (DEP, 0, True), 0.0, (0.0, 238.0), DEP, ANCHORED),
            _outside("Avant", 8.0, (INT, 0, False)),  # rattachement déduit
            _found("Juste après", 12.7, (INT, 0, False), 0.7, (0.0, 238.0)),
            _outside("Presque", 1004.999999, (INT, 4, False)),  # déduit
            _found(
                "Fin",
                1009.999999,
                (ARR, 5, True),
                992.0,
                (988.000001, 992.0),
                ARR,
                ANCHORED,
            ),
        ),
        prefix_count=5,
        prefix_end_m=1003.999999,
        prefix_end_s=992.0,
        start_m=12.0,
        point_times=((0, 0.0), (5, 992.0)),
        point_statuses=((0, PointStatus.ANCHORED), (5, PointStatus.ANCHORED)),
    ),
    "Coin coupé": Row(
        p.cut_corner,
        "limite connue du § 3 : passage absent à un virage serré",
        (
            _undated(
                "W", 766.0, PassageStatus.ABSENT, Unavailability.ABSENT, (INT, 3, False)
            ),
        ),
        prefix_count=5,
        prefix_end_s=1052.0,
        point_times=((3, 769.562226),),
        point_statuses=tuple((k, PointStatus.FOUND) for k in range(6)),
        length_m=1066.163969,
    ),
    "Hors ε": Row(
        p.out_of_tolerance,
        "choix 4 : un franchissement orienté, aucun admissible — hors ε, motif absent",
        (
            _undated(
                "H",
                375.5,
                PassageStatus.OUT_OF_TOLERANCE,
                Unavailability.ABSENT,
                (INT, 1, False),
            ),
        ),
        prefix_count=5,
    ),
    "Lacet": Row(
        p.switchback,
        "choix 4 : un événement de deux candidats, daté par le dernier",
        (_found("L", 375.5, (INT, 1, False), 409.5, (250.0, 534.000001)),),
        prefix_count=5,
        prefix_end_s=1044.0,
    ),
    "Lacet large": Row(
        p.wide_switchback,
        "choix 4 : deux événements — ambigu",
        (_undated("L", 375.5, AMBIGUOUS, Unavailability.AMBIGUOUS, (INT, 1, False)),),
        prefix_count=5,
    ),
    "Égalité": Row(
        p.tie,
        "choix 7 et 9 : égalité en temps (1 s) puis en espace (1 m), distance à "
        "Q_w sur le tracé — non attribué",
        (
            _found("E1", 370.3, (INT, 1, False), 370.3, (250.0, 620.000001)),
            _found("E2", 389.7, (INT, 1, False), 509.7, (250.0, 620.000001)),  # déduit
        ),
        (Episode(392.0, 488.0, TIE, None, (380.0, 0.0)),),
        prefix_count=5,
        prefix_end_s=1130.0,
    ),
    "Égalité, espace": Row(
        p.tie_by_space,
        "choix 9 : égalité en temps à 1 s, départagée par l'espace",
        (
            _found(
                "E1",
                372.5,
                (INT, 1, False),  # déduit
                372.5,
                (250.0, 560.094488),
                departure_s=486.0,
                stop_total_s=94.0,
                episode_count=1,
            ),
            _found(
                "E2", 391.5, (INT, 1, False), 505.759055, (250.0, 560.094488)
            ),  # déduit
        ),
        (Episode(392.0, 486.0, ATTRIBUTED, 0, (380.0, 0.0)),),
        prefix_count=5,
        prefix_end_s=815.496063,
    ),
    "Fenêtre": Row(
        p.window,
        "choix 5 : une candidate plus proche est écartée par sa fenêtre",
        (
            _found("Y", 495.0, (INT, 1, False), 495.0, (250.0, 500.000001)),
            _found(
                "X",
                524.999999,
                (INT, 2, False),
                645.0,
                (500.000001, 870.000001),
                arrival_s=515.0,
                stop_total_s=96.0,
                episode_count=1,
            ),
        ),
        (Episode(515.0, 611.0, ATTRIBUTED, 1, (503.0, 0.0)),),
        prefix_count=5,
        point_times=((2, 500.000001),),
    ),
    "Chronologie": Row(
        p.chronology,
        "choix 8 et 11 : médiane d'un arrêt rampant ; départ de W1 après l'arrivée "
        "de W2 — les deux ambiguës, événements conservés",
        (
            _found(
                "W1",
                375.5,
                (INT, 1, False),
                425.0,
                (250.0, 734.918885),
                status=AMBIGUOUS,
                arrival_s=387.0,
                departure_s=602.0,
                stop_total_s=215.0,
                episode_count=1,
                chronology_violation=True,
                comparable=False,
                unavailability=Unavailability.AMBIGUOUS,
            ),
            _found(
                "W2",
                378.5,
                (INT, 1, False),
                575.0,
                (250.0, 734.918885),  # fenêtre déduite de l'encadrement (1, 2)
                status=AMBIGUOUS,
                chronology_violation=True,
                comparable=False,
                unavailability=Unavailability.AMBIGUOUS,
            ),
        ),
        (Episode(387.0, 602.0, ATTRIBUTED, 0, (376.195, 0.0)),),
        prefix_count=5,
    ),
    "Chronologie finale": Row(
        p.final_chronology,
        "choix 11 : départ après l'arrivée finale — seule l'occurrence est marquée",
        (
            _found(
                "F",
                1004.499999,
                (INT, 4, False),
                1033.0,
                (1000.000001, 1143.0),
                status=AMBIGUOUS,
                arrival_s=1017.0,
                departure_s=1166.0,
                stop_total_s=149.0,
                episode_count=1,
                chronology_violation=True,
                comparable=False,
                unavailability=Unavailability.AMBIGUOUS,
            ),
        ),
        (Episode(1017.0, 1166.0, ATTRIBUTED, 0, (1007.425, 0.0)),),
        prefix_count=5,
        prefix_end_s=1143.0,
        point_times=((5, 1143.0),),
    ),
    "Aller-retour": Row(
        p.out_and_back,
        "D4.12 : deux occurrences d'un même lieu ; tangente indéfinie au demi-tour",
        (
            _found("M", 300.0, (INT, 1, False), 300.0, (250.0, 500.0)),
            _undated(
                "T",
                620.0,
                PassageStatus.UNDEFINED_TANGENT,
                Unavailability.UNDEFINED_TANGENT,
                (INT, 2, False),
            ),
            _found(
                "M",
                940.0,
                (INT, 3, False),
                1060.0,
                (750.0, 1120.0),
                arrival_s=947.0,
                stop_total_s=96.0,
                episode_count=1,
            ),
        ),
        (Episode(947.0, 1043.0, ATTRIBUTED, 2, (305.0, 0.0)),),
        prefix_count=5,
        prefix_end_s=1360.0,
        length_m=1240.0,
    ),
    "Reprise en m": Row(
        p.resume_at_m,
        "choix 5 et 12 : fenêtre d'une reprise en m jusqu'au point daté suivant, "
        "arrêt juste après le préfixe — support insuffisant ; R+ hors préfixe",
        (
            _found(
                "R",
                499.499999,
                (INT, 2, True),
                500.000001,
                (250.0, 890.000001),
                departure_s=613.0,
                stop_total_s=96.0,
                episode_count=1,
                comparable=False,
                unavailability=INSUFFICIENT,
            ),
            _outside("R+", 500.799999, (INT, 2, True)),
        ),
        (Episode(517.0, 613.0, ATTRIBUTED, 0, (505.0, 0.0)),),
        prefix_count=2,
        prefix_end_m=500.0,
        prefix_end_s=500.000001,
        point_times=((3, 890.000001),),
    ),
    "Reprise en m, hors tracé": Row(
        p.resume_at_m_off_route,
        "choix 5 : aucun point daté après m — fenêtre jusqu'au dernier enregistrement",
        (
            _found(
                "R",
                499.499999,
                (INT, 2, True),
                500.000001,
                (250.0, 825.0),
                departure_s=613.0,
                stop_total_s=96.0,
                episode_count=1,
                comparable=False,
                unavailability=INSUFFICIENT,
            ),
        ),
        (Episode(517.0, 613.0, ATTRIBUTED, 0, (505.0, 0.0)),),
        prefix_count=2,
        prefix_end_s=500.000001,
        point_times=((3, None), (4, None), (5, None)),
        point_statuses=tuple((k, PointStatus.ABSENT) for k in (3, 4, 5)),
    ),
    "Passages (M4a-2b)": Row(
        p.passages_m4a2b,
        "choix 2 : départ ancré, lieu avant b_0 et lieu après b_m hors préfixe",
        (
            _outside("A", 5.0, (INT, 0, False)),  # rattachement déduit
            _found("B", 300.0, (INT, 1, False), 192.0, (158.666667, 325.333334)),
            _found("C", 479.999999, (INT, 1, False), 312.0, (158.666667, 325.333334)),
            _outside("D", 699.999999, (INT, 2, False)),  # rattachement déduit
        ),
        prefix_count=2,
        prefix_end_m=500.0,
        prefix_end_s=325.333334,
        start_m=12.0,
        point_statuses=((0, PointStatus.ANCHORED),),
    ),
    "Retour": Row(
        p.return_crossing,
        "choix 4 : borne haute — le second franchissement admissible vient après π_2",
        (_found("W", 375.5, (INT, 1, False), 375.5, (250.0, 500.000001)),),
        prefix_count=2,
        prefix_end_m=500.0,
    ),
    "Arrêt à l'arrivée": Row(
        p.stop_at_arrival,
        "choix 6 : l'arrivée n'est pas candidate — épisode sans candidate",
        (
            _found(
                "Fin", 1009.999999, (ARR, 5, True), 1010.0, (1000.000001, 1132.0), ARR
            ),
        ),
        (Episode(1024.0, 1115.0, NO_CANDIDATE, None, (1012.0, 0.0)),),
        prefix_count=5,
        prefix_end_s=1010.0,
    ),
    "Deux arrêts": Row(
        p.two_stops,
        "choix 10 : deux épisodes attribués à la même occurrence ; S = somme",
        (
            _found(
                "A",
                375.5,
                (INT, 1, False),
                375.5,
                (250.0, 730.000001),
                departure_s=598.0,
                stop_total_s=152.0,
                episode_count=2,
            ),
        ),
        (
            Episode(392.0, 468.0, ATTRIBUTED, 0, (380.0, 0.0)),
            Episode(522.0, 598.0, ATTRIBUTED, 0, (380.0, 0.0)),
        ),
        prefix_count=5,
        point_times=((2, 730.000001),),
    ),
    "Départ dans l'arrêt": Row(
        p.departure_in_stop,
        "choix 6, 11, 12 : le départ n'est ni candidat ni dans la chronologie ; "
        "arrivée avant t*_0 — support insuffisant",
        (
            _found("Départ", 0.0, (DEP, 0, True), 25.0, (25.0, 371.0), role=DEP),
            _found(
                "P",
                3.5,
                (INT, 0, False),
                112.5,
                (25.0, 371.0),
                arrival_s=17.0,
                stop_total_s=95.0,
                episode_count=1,
                comparable=False,
                unavailability=INSUFFICIENT,
            ),
        ),
        (Episode(17.0, 112.0, ATTRIBUTED, 1, (1.58, 0.0)),),
        prefix_count=5,
        point_times=((0, 25.0),),
    ),
    "Arrêt à 35 m": Row(
        p.stop_at_35_m,
        "D4.12 : Q_w à 35 m >= ε de la médiane — épisode sans candidate",
        (_found("Z", 345.0, (INT, 1, False), 345.0, (250.0, 620.000001)),),
        (Episode(392.0, 488.0, NO_CANDIDATE, None, (380.0, 0.0)),),
        prefix_count=5,
    ),
    "Final hors préfixe": Row(
        p.final_outside_prefix,
        "choix 2 et 11 : arrivée hors préfixe bien que datée ; arrivée finale hors "
        "de la chronologie quand m < K",
        (
            _found(
                "F",
                999.499999,
                (INT, 4, True),
                1155.500066,
                (750.375941, 1785.5),
                arrival_s=1011.0,
                departure_s=1926.0,
                stop_total_s=915.0,
                episode_count=1,
                comparable=False,
                unavailability=INSUFFICIENT,
            ),
            _outside("Fin", 1009.999999, (ARR, 5, True)),
        ),
        (Episode(1011.0, 1926.0, ATTRIBUTED, 0, (1004.968254, 1.47619)),),
        prefix_count=4,
        prefix_end_m=1000.0,
        prefix_end_s=1155.500066,
        point_times=((5, 1785.5),),
        point_statuses=((5, PointStatus.FOUND),),
    ),
    "Départ non daté": Row(
        p.undated_departure,
        "choix 2 et 3 : m = 0 ; départ repris sans instant, toujours observé",
        (
            _undated(
                "Départ", 0.0, PassageStatus.ABSENT, None, (DEP, 0, True), role=DEP
            ),
            _outside("Q", 100.0, (INT, 0, False)),
        ),
        prefix_count=0,
        prefix_end_s=None,
        point_statuses=tuple((k, PointStatus.ABSENT) for k in range(6)),
    ),
    "Reprise en m, point m + 1 hors ε": Row(
        p.resume_next_out_of_tolerance,
        "choix 5 : fenêtre jusqu'au premier point daté après m (le point 4), pas "
        "jusqu'au dernier enregistrement",
        (_found("R", 499.499999, (INT, 2, True), 500.000001, (250.0, 1200.000001)),),
        (Episode(1737.0, 1828.0, NO_CANDIDATE, None, (505.0, 0.0)),),
        prefix_count=2,
        prefix_end_s=500.000001,
        point_times=((3, None), (4, 1200.000001), (5, 1210.0)),
        point_statuses=((3, PointStatus.OUT_OF_TOLERANCE),),
    ),
    "Deux reprises": Row(
        p.two_resumes,
        "choix 7 : distance mesurée à Q_w sur le tracé, pas au point de score repris",
        (
            _found("Borne bis", 249.1, (INT, 1, True), 250.0, (0.0, 620.000001)),
            _found(
                "Borne",
                250.9,
                (INT, 1, True),
                250.0,
                (0.0, 620.000001),
                departure_s=360.0,
                stop_total_s=96.0,
                episode_count=1,
            ),
        ),
        (Episode(264.0, 360.0, ATTRIBUTED, 1, (252.0, 0.0)),),
        prefix_count=5,
        prefix_end_s=1130.0,
    ),
}
"""Les vingt-six lignes du § 7.3.1, dans l'ordre du tableau."""

CORRECTIVE_ROWS: dict[str, Row] = {
    "Chronologie miroir": Row(
        p.chronology_mirror,
        "R4 des correctifs de la PR #12, choix 11 : le second lieu reçoit l'arrêt ; "
        "son arrivée (387) précède le départ du premier (411,5) — les deux ambiguës",
        (
            _found(
                "W1",
                375.5,
                (INT, 1, False),
                411.5,
                (250.0, 869.000001),
                status=AMBIGUOUS,
                chronology_violation=True,
                comparable=False,
                unavailability=Unavailability.AMBIGUOUS,
            ),
            _found(
                "W2",
                378.5,
                (INT, 1, False),
                599.0,
                (250.0, 869.000001),
                status=AMBIGUOUS,
                arrival_s=387.0,
                departure_s=737.0,
                stop_total_s=350.0,
                episode_count=1,
                chronology_violation=True,
                comparable=False,
                unavailability=Unavailability.AMBIGUOUS,
            ),
        ),
        (Episode(387.0, 737.0, ATTRIBUTED, 1, (378.13, 0.0)),),
        prefix_count=5,
        prefix_end_s=1379.0,
    ),
    "Hors ε à ε = 50": Row(
        p.out_of_tolerance_eps_50,
        "R5 des correctifs de la PR #12 : ε lu dans match.parameters — l'écart de "
        "45 m devient admissible",
        (_found("H", 375.5, (INT, 1, False), 375.5, (250.0, 500.000001)),),
        prefix_count=5,
        prefix_end_s=1010.0,
    ),
    "Arrêt à 35 m à ε = 40": Row(
        p.stop_at_35_m_eps_40,
        "R5 des correctifs de la PR #12 : ε lu dans match.parameters pour "
        "l'association — Z devient candidate",
        (
            _found(
                "Z",
                345.0,
                (INT, 1, False),
                345.0,
                (250.0, 620.000001),
                departure_s=488.0,
                stop_total_s=96.0,
                episode_count=1,
            ),
        ),
        (Episode(392.0, 488.0, ATTRIBUTED, 0, (380.0, 0.0)),),
        prefix_count=5,
        prefix_end_s=1130.0,
    ),
    "Lacet large à r_c = 30": Row(
        p.wide_switchback_radius_30,
        "R5 des correctifs de la PR #12 : r_c lu dans match.parameters — un seul "
        "événement, daté par son dernier candidat",
        (_found("L", 375.5, (INT, 1, False), 435.5, (250.0, 560.000001)),),
        prefix_count=5,
        prefix_end_s=1070.0,
    ),
}
"""Lignes ajoutées par les correctifs de la PR #12 (R4 à R6), mêmes vérifications."""

ALL_ROWS = {**ROWS, **CORRECTIVE_ROWS}


def _close(actual: float | None, expected: float | None) -> bool:
    if expected is None or actual is None:
        return actual is expected
    return abs(actual - expected) <= TOLERANCE


def _median_error_m(lat_deg: float, lon_deg: float, point: Point) -> float:
    """Distance (``to_local``) entre la médiane publiée et ``local_deg(x, y)``."""
    return math.hypot(*to_local(*local_deg(*point), lat_deg, lon_deg))


def test_the_table_has_twenty_six_rows() -> None:
    assert len(ROWS) == 26


@pytest.mark.parametrize("row", ALL_ROWS.values(), ids=ALL_ROWS.keys())
def test_observe_passages(row: Row) -> None:
    """``0010`` D4.12, chaque ligne du § 7.3.1 et celles des correctifs de la PR #12 :
    ``Row.rule`` nomme la règle distinguée."""
    case = row.case()
    match, result = p.observed_passages(case)
    coverage = match.coverage
    if row.length_m is not None:
        assert _close(case.geometry.length_m, row.length_m)
    if row.prefix_count is not None:
        assert coverage.prefix_segment_count == row.prefix_count
    if row.prefix_end_m is not None:
        assert _close(coverage.prefix_end_m, row.prefix_end_m)
    if row.prefix_end_s is not None or row.prefix_count == 0:
        assert _close(coverage.prefix_end_s, row.prefix_end_s)
    if row.start_m is not None:
        assert _close(match.points[0].effective_m, row.start_m)
    for k, time_s in row.point_times:
        assert _close(match.points[k].time_s, time_s)
    for k, status in row.point_statuses:
        assert match.points[k].status is status
    grid_m = score_grid(case.geometry.length_m, case.parameters["score_step_m"])
    assert [q.point.point.name for q in result.passages] == [
        e.name for e in row.passages
    ]
    for observed, expected in zip(result.passages, row.passages, strict=True):
        name = expected.name
        assert _close(observed.point.distance_m, expected.distance_m), name
        assert attach_occurrence(observed.point.distance_m, grid_m) == expected.attach
        assert observed.role is expected.role, name
        assert observed.status is expected.status, name
        dated = expected.crossing_s is not None
        arrival_s = (
            expected.arrival_s
            if expected.arrival_s is not None
            else (expected.crossing_s)
        )
        departure_s = (
            expected.departure_s
            if expected.departure_s is not None
            else (expected.crossing_s)
        )
        stop_s = (
            expected.stop_total_s
            if expected.stop_total_s is not None
            else (0.0 if dated else None)
        )
        assert _close(observed.crossing_s, expected.crossing_s), name
        if expected.window_s is None:
            assert observed.association_window_s is None, name
        else:
            assert observed.association_window_s is not None, name
            for own, wanted in zip(
                observed.association_window_s, expected.window_s, strict=True
            ):
                assert _close(own, wanted), name
        assert _close(observed.arrival_s, arrival_s), name
        assert _close(observed.departure_s, departure_s), name
        assert _close(observed.stop_total_s, stop_s), name
        assert observed.episode_count == expected.episode_count, name
        assert observed.chronology_violation is expected.chronology_violation, name
        assert observed.comparable is expected.comparable, name
        assert observed.unavailability is expected.unavailability, name
    assert len(result.episodes) == len(row.episodes)
    for attribution, episode in zip(result.episodes, row.episodes, strict=True):
        assert _close(attribution.episode.start_s, episode.start_s)
        assert _close(attribution.episode.end_s, episode.end_s)
        assert attribution.outcome is episode.outcome
        assert attribution.passage_index == episode.passage_index
        error_m = _median_error_m(
            attribution.median_latitude_deg,
            attribution.median_longitude_deg,
            episode.median_m,
        )
        assert error_m <= TOLERANCE


# ---------------------------------------------------------------------------
# Préconditions de observe_passages (§ 6.9)
# ---------------------------------------------------------------------------


def test_series_built_on_another_trace_is_refused() -> None:
    case, other = p.passages(), p.m05()
    match, _ = p.observed_passages(case)
    series = build_series(other.trace)
    with pytest.raises(ValueError, match="séries, partition et trace"):
        observe_passages(
            match,
            case.geometry,
            reference_profile(case),
            case.trace,
            series,
            clock_partition(case.trace, build_series(case.trace)),
        )


def test_partition_built_on_another_trace_is_refused() -> None:
    case, other = p.passages(), p.m05()
    match, _ = p.observed_passages(case)
    series = build_series(case.trace)
    with pytest.raises(ValueError, match="séries, partition et trace"):
        observe_passages(
            match,
            case.geometry,
            reference_profile(case),
            case.trace,
            series,
            clock_partition(other.trace, build_series(other.trace)),
        )


def _observe_with(
    case: MatchCase,
    *,
    match: MatchResult | None = None,
    profile: RouteProfile | None = None,
) -> None:
    """``observe_passages`` sur un cas, un argument remplacé."""
    own, _ = p.observed_passages(case)
    series = build_series(case.trace)
    observe_passages(
        own if match is None else match,
        case.geometry,
        reference_profile(case) if profile is None else profile,
        case.trace,
        series,
        clock_partition(case.trace, series),
    )


def test_undeclared_parameters_are_refused() -> None:
    case = p.passages()
    match, _ = p.observed_passages(case)
    spec = ParameterSpec("score_step_m", "m", 250.0, 10.0, 5000.0, "Δ.")
    with pytest.raises(ValueError, match="MATCHING_PARAMETER_SPECS"):
        _observe_with(case, match=replace(match, parameters=ParameterSet((spec,))))


def test_profile_of_another_route_is_refused() -> None:
    case = p.passages()
    with pytest.raises(ValueError, match="profil et géométrie"):
        _observe_with(case, profile=reference_profile(p.out_and_back()))


def test_points_of_another_grid_are_refused() -> None:
    """``Δ = 100`` : la grille compte 12 points, le ``MatchResult`` 6."""
    case = p.passages()
    match, _ = p.observed_passages(case)
    parameters = ParameterSet(MATCHING_PARAMETER_SPECS, {"score_step_m": 100.0})
    with pytest.raises(ValueError, match="6 points pour une grille de 12"):
        _observe_with(case, match=replace(match, parameters=parameters))
