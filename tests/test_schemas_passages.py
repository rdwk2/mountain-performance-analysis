"""Tests des contrats des passages (§ 6.1 et § 8.3, test 1, du brief M4a-3).

``0010`` D4.12, D0, D7.4. Un test par invariant de ``PassageObservation``,
``EpisodeAttribution`` et ``PassageMatchResult`` : un objet construit à la main qui
le viole (``ContractError``, visé par son message), et un objet valide à sa limite.
Exemple valide : la ligne Passages du § 7.3.1 (B repris, A encadré avec un épisode,
C hors préfixe), et la ligne Chronologie pour une occurrence ambiguë par la
chronologie.
"""

import math
from collections.abc import Mapping
from dataclasses import FrozenInstanceError, replace
from enum import Enum
from typing import Any

import pytest

from mountain_perf.schemas import (
    EPISODE_OUTCOME_DESCRIPTIONS,
    PASSAGE_ROLE_DESCRIPTIONS,
    PASSAGE_STATUS_DESCRIPTIONS,
    PASSAGE_STATUS_UNAVAILABILITY,
    ContractError,
    EpisodeAttribution,
    EpisodeOutcome,
    NamedPoint,
    PassageMatchResult,
    PassageObservation,
    PassageRole,
    PassageStatus,
    PointStatus,
    ResolvedPoint,
    StopEpisode,
    Unavailability,
)
from mountain_perf.schemas._dictionary import render

ARRIVAL = PassageRole.ARRIVAL
DEPARTURE = PassageRole.DEPARTURE
INTERMEDIATE = PassageRole.INTERMEDIATE
FOUND = PassageStatus.FOUND
ANCHORED = PassageStatus.ANCHORED
AMBIGUOUS = PassageStatus.AMBIGUOUS
OUTSIDE_PREFIX = PassageStatus.OUTSIDE_PREFIX


def _resolved(name: str, distance_m: float) -> ResolvedPoint:
    """Une occurrence : les coordonnées du lieu n'entrent pas dans le contrat."""
    return ResolvedPoint(
        NamedPoint(name, 45.0, 6.0, elevation_m=None),
        distance_m=distance_m,
        elevation_m=0.0,
        offset_m=0.0,
    )


def _undated(
    name: str,
    distance_m: float,
    status: PassageStatus,
    unavailability: Unavailability | None,
    role: PassageRole = INTERMEDIATE,
) -> PassageObservation:
    """Une occurrence sans instant, non comparable."""
    return PassageObservation(
        point=_resolved(name, distance_m),
        role=role,
        status=status,
        crossing_s=None,
        association_window_s=None,
        arrival_s=None,
        departure_s=None,
        stop_total_s=None,
        episode_count=0,
        chronology_violation=False,
        comparable=False,
        unavailability=unavailability,
    )


B = PassageObservation(
    point=_resolved("B", 250.4),
    role=INTERMEDIATE,
    status=FOUND,
    crossing_s=250.0,
    association_window_s=(0.0, 620.000001),
    arrival_s=250.0,
    departure_s=250.0,
    stop_total_s=0.0,
    episode_count=0,
    chronology_violation=False,
    comparable=True,
    unavailability=None,
)
"""B de Passages : repris 1, sans épisode."""

A = PassageObservation(
    point=_resolved("A", 375.0),
    role=INTERMEDIATE,
    status=FOUND,
    crossing_s=375.0,
    association_window_s=(250.0, 620.000001),
    arrival_s=375.0,
    departure_s=488.0,
    stop_total_s=96.0,
    episode_count=1,
    chronology_violation=False,
    comparable=True,
    unavailability=None,
)
"""A de Passages : encadré (1, 2), un épisode ``[392 ; 488]``."""

C = _undated("C", 899.999999, OUTSIDE_PREFIX, Unavailability.INSUFFICIENT_SUPPORT)
"""C de Passages : hors préfixe."""

EPISODE = StopEpisode(start_s=392.0, end_s=488.0, first_record=392, last_record=488)

ATTRIBUTED = EpisodeAttribution(
    episode=EPISODE,
    outcome=EpisodeOutcome.ATTRIBUTED,
    passage_index=1,
    median_latitude_deg=45.0,
    median_longitude_deg=6.004833,
)

PASSAGES_RESULT = PassageMatchResult(passages=(B, A, C), episodes=(ATTRIBUTED,))
"""La ligne Passages du § 7.3.1."""

W1 = PassageObservation(
    point=_resolved("W1", 375.5),
    role=INTERMEDIATE,
    status=AMBIGUOUS,
    crossing_s=425.0,
    association_window_s=(250.0, 734.918885),
    arrival_s=387.0,
    departure_s=602.0,
    stop_total_s=215.0,
    episode_count=1,
    chronology_violation=True,
    comparable=False,
    unavailability=Unavailability.AMBIGUOUS,
)
"""W1 de Chronologie : ambiguë par la chronologie, événements conservés."""

W2 = replace(
    W1,
    point=_resolved("W2", 378.5),
    crossing_s=575.0,
    arrival_s=575.0,
    departure_s=575.0,
    stop_total_s=0.0,
    episode_count=0,
)

CHRONOLOGY_RESULT = PassageMatchResult(
    passages=(W1, W2),
    episodes=(
        EpisodeAttribution(
            StopEpisode(387.0, 602.0, 387, 481),
            EpisodeOutcome.ATTRIBUTED,
            0,
            45.0,
            6.0,
        ),
    ),
)

DEPARTURE_FOUND = PassageObservation(
    point=_resolved("Départ", 0.0),
    role=DEPARTURE,
    status=FOUND,
    crossing_s=0.0,
    association_window_s=(0.0, 250.0),
    arrival_s=0.0,
    departure_s=0.0,
    stop_total_s=0.0,
    episode_count=0,
    chronology_violation=False,
    comparable=False,
    unavailability=None,
)
"""Départ de M05 : trouvé, non cible, à la limite ``crossing_s == début == 0``."""

ARRIVAL_ANCHORED = PassageObservation(
    point=_resolved("Fin", 1009.999999),
    role=ARRIVAL,
    status=ANCHORED,
    crossing_s=992.0,
    association_window_s=(988.000001, 992.0),
    arrival_s=992.0,
    departure_s=992.0,
    stop_total_s=0.0,
    episode_count=0,
    chronology_violation=False,
    comparable=True,
    unavailability=None,
)
"""Fin de M05 ancré : arrivée ancrée, comparable, ``crossing_s == fin``."""


def _raises(match: str, **changes: Any) -> None:
    with pytest.raises(ContractError, match=match):
        replace(A, **changes)


# ---------------------------------------------------------------------------
# Énumérations, tables, dictionnaire
# ---------------------------------------------------------------------------

ENUM_TABLES: tuple[tuple[type[Enum], Mapping[Any, str]], ...] = (
    (PassageRole, PASSAGE_ROLE_DESCRIPTIONS),
    (PassageStatus, PASSAGE_STATUS_DESCRIPTIONS),
    (EpisodeOutcome, EPISODE_OUTCOME_DESCRIPTIONS),
)


@pytest.mark.parametrize(("enum", "table"), ENUM_TABLES, ids=lambda x: str(x)[:30])
def test_every_member_is_described(enum: type[Enum], table: Mapping[Any, str]) -> None:
    assert set(table) == set(enum)
    assert all(text.strip() for text in table.values())


@pytest.mark.parametrize(("enum", "table"), ENUM_TABLES, ids=lambda x: str(x)[:30])
def test_descriptions_are_read_only(enum: type[Enum], table: Mapping[Any, str]) -> None:
    writable: Any = table
    with pytest.raises(TypeError):
        writable[next(iter(enum))] = "Autre description."


def test_values_of_the_brief() -> None:
    """§ 6.1 : rôles, statuts (ceux de ``PointStatus``, puis ``outside_prefix``),
    issues."""
    assert [r.value for r in PassageRole] == ["departure", "arrival", "intermediate"]
    assert [s.value for s in PassageStatus] == [
        "found",
        "anchored",
        "ambiguous",
        "absent",
        "out_of_tolerance",
        "undefined_tangent",
        "outside_prefix",
    ]
    assert [s.value for s in PassageStatus][:6] == [s.value for s in PointStatus]
    assert [o.value for o in EpisodeOutcome] == ["attributed", "no_candidate", "tie"]


def test_status_unavailability_table_of_the_brief() -> None:
    """Précision P3 : la table statut → indisponibilité du § 6.1, valeur par valeur,
    avec les valeurs écrites ici ; ``found`` et ``anchored`` n'y sont pas (motif
    ``insufficient_support`` s'ils ne sont pas maintenus : il ne dépend pas du seul
    statut)."""
    assert dict(PASSAGE_STATUS_UNAVAILABILITY) == {
        PassageStatus.AMBIGUOUS: Unavailability.AMBIGUOUS,
        PassageStatus.ABSENT: Unavailability.ABSENT,
        PassageStatus.OUT_OF_TOLERANCE: Unavailability.ABSENT,
        PassageStatus.UNDEFINED_TANGENT: Unavailability.UNDEFINED_TANGENT,
        PassageStatus.OUTSIDE_PREFIX: Unavailability.INSUFFICIENT_SUPPORT,
    }
    writable: Any = PASSAGE_STATUS_UNAVAILABILITY
    with pytest.raises(TypeError):
        writable[PassageStatus.FOUND] = Unavailability.ABSENT


NEW_TYPES = (
    PassageRole,
    PassageStatus,
    EpisodeOutcome,
    PassageObservation,
    EpisodeAttribution,
    PassageMatchResult,
)


def test_new_types_are_in_the_dictionary() -> None:
    text = render()
    for cls in NEW_TYPES:
        assert f"## `{cls.__name__}`" in text
    for enum, _ in ENUM_TABLES:
        for member in enum:
            assert f"| `{member.name}` | `{member.value}` |" in text


@pytest.mark.parametrize(
    ("instance", "field"),
    [(A, "status"), (ATTRIBUTED, "outcome"), (PASSAGES_RESULT, "passages")],
    ids=lambda x: type(x).__name__ if not isinstance(x, str) else x,
)
def test_new_types_are_frozen(instance: object, field: str) -> None:
    with pytest.raises(FrozenInstanceError):
        setattr(instance, field, None)


# ---------------------------------------------------------------------------
# PassageObservation — exemples valides, dont les limites
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "passage",
    [
        B,
        A,
        C,
        W1,
        W2,
        DEPARTURE_FOUND,
        ARRIVAL_ANCHORED,
        # Départ absent, sans instant ni motif (Départ non daté).
        _undated("Départ", 0.0, PassageStatus.ABSENT, None, role=DEPARTURE),
        # Départ ambigu par sa recherche : sans instant ni motif.
        _undated("Départ", 0.0, AMBIGUOUS, None, role=DEPARTURE),
        # Arrivée hors préfixe (Final hors préfixe).
        _undated(
            "Fin",
            1009.999999,
            OUTSIDE_PREFIX,
            Unavailability.INSUFFICIENT_SUPPORT,
            ARRIVAL,
        ),
        # Trouvée, non maintenue (Y01).
        replace(
            A, comparable=False, unavailability=Unavailability.INSUFFICIENT_SUPPORT
        ),
        # Arrivée ancrée non maintenue.
        replace(
            ARRIVAL_ANCHORED,
            comparable=False,
            unavailability=Unavailability.INSUFFICIENT_SUPPORT,
        ),
        # Limite : S = départ − arrivée, arrivée = crossing_s = début de fenêtre.
        replace(
            A, crossing_s=392.0, association_window_s=(392.0, 620.0), arrival_s=392.0
        ),
        # Limite : crossing_s = fin de fenêtre = départ.
        replace(
            A,
            crossing_s=488.0,
            association_window_s=(250.0, 488.0),
            arrival_s=392.0,
            departure_s=488.0,
        ),
        # Limite : toutes les valeurs nulles.
        replace(DEPARTURE_FOUND, association_window_s=(0.0, 0.0), status=ANCHORED),
    ],
)
def test_passage_examples_build(passage: PassageObservation) -> None:
    assert replace(passage) == passage


@pytest.mark.parametrize(
    ("status", "unavailability"),
    [
        (PassageStatus.AMBIGUOUS, Unavailability.AMBIGUOUS),
        (PassageStatus.ABSENT, Unavailability.ABSENT),
        (PassageStatus.OUT_OF_TOLERANCE, Unavailability.ABSENT),
        (PassageStatus.UNDEFINED_TANGENT, Unavailability.UNDEFINED_TANGENT),
        (PassageStatus.OUTSIDE_PREFIX, Unavailability.INSUFFICIENT_SUPPORT),
    ],
)
def test_undated_statuses_carry_the_motive_of_the_table(
    status: PassageStatus, unavailability: Unavailability
) -> None:
    """§ 6.1 : chaque statut sans instant, de rôle intermédiaire ou arrivée, porte le
    motif du tableau ; tout autre motif est refusé."""
    for role in (INTERMEDIATE, ARRIVAL):
        passage = _undated("X", 500.0, status, unavailability, role)
        assert passage.unavailability is unavailability
        for other in Unavailability:
            if other is not unavailability:
                with pytest.raises(ContractError, match="non comparable a le motif"):
                    replace(passage, unavailability=other)
        with pytest.raises(ContractError, match="non comparable a le motif"):
            replace(passage, unavailability=None)


def test_dated_property() -> None:
    assert A.dated
    assert ARRIVAL_ANCHORED.dated
    assert W1.dated
    assert not C.dated
    assert not _undated("X", 1.0, AMBIGUOUS, Unavailability.AMBIGUOUS).dated


# ---------------------------------------------------------------------------
# PassageObservation — un test par invariant
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "field",
    ["crossing_s", "association_window_s", "arrival_s", "departure_s", "stop_total_s"],
)
def test_instants_are_all_present_or_all_absent(field: str) -> None:
    _raises("tous présents ou tous absents", **{field: None})


def test_instants_are_present_for_found_and_anchored() -> None:
    for status in (FOUND, ANCHORED):
        role = INTERMEDIATE if status is FOUND else ARRIVAL
        with pytest.raises(ContractError, match="doivent être présents"):
            _undated("X", 500.0, status, Unavailability.INSUFFICIENT_SUPPORT, role)


def test_instants_are_present_after_a_chronology_violation() -> None:
    with pytest.raises(ContractError, match="doivent être présents"):
        replace(
            _undated("X", 500.0, AMBIGUOUS, Unavailability.AMBIGUOUS),
            chronology_violation=True,
        )


@pytest.mark.parametrize(
    "status",
    [
        PassageStatus.ABSENT,
        PassageStatus.OUT_OF_TOLERANCE,
        PassageStatus.UNDEFINED_TANGENT,
        PassageStatus.OUTSIDE_PREFIX,
    ],
)
def test_instants_are_absent_for_an_undated_status(status: PassageStatus) -> None:
    _raises(
        "doivent être absents",
        status=status,
        comparable=False,
        unavailability=PASSAGE_STATUS_UNAVAILABILITY[status],
        episode_count=0,
    )


def test_instants_are_absent_for_ambiguous_without_chronology() -> None:
    """Une occurrence ambiguë par sa recherche n'a pas d'instant."""
    _raises(
        "doivent être absents",
        status=AMBIGUOUS,
        comparable=False,
        unavailability=Unavailability.AMBIGUOUS,
    )


@pytest.mark.parametrize(
    "changes",
    [
        {"crossing_s": math.nan},
        {"crossing_s": math.inf},
        {"association_window_s": (math.nan, 620.0)},
        {"association_window_s": (250.0, math.inf)},
        {"arrival_s": -math.inf},
        {"departure_s": math.nan},
        {"stop_total_s": math.nan},
    ],
    ids=str,
)
def test_instants_are_finite(changes: dict[str, Any]) -> None:
    _raises("doit être fini", **changes)


@pytest.mark.parametrize(
    ("changes", "name"),
    [
        (
            {
                "crossing_s": -1.0,
                "association_window_s": (-2.0, 0.0),
                "arrival_s": -1.0,
                "departure_s": -1.0,
                "stop_total_s": 0.0,
                "episode_count": 0,
            },
            "crossing_s",
        ),
        ({"association_window_s": (-1.0, 620.0)}, r"association_window_s\[0\]"),
        ({"stop_total_s": -1.0}, "stop_total_s"),
        # R10 des correctifs de la PR #12 : A a un épisode, seule l'arrivée est
        # négative ; tout le reste est valide.
        ({"arrival_s": -1.0}, "arrival_s"),
    ],
    ids=["crossing", "window", "stop_total", "arrival"],
)
def test_instants_are_non_negative(changes: dict[str, Any], name: str) -> None:
    """Un instant négatif ; ``crossing_s`` est le premier contrôlé."""
    _raises(f"{name} doit être >= 0", **changes)


def test_association_window_is_an_immutable_pair() -> None:
    _raises("séquence immuable", association_window_s=[250.0, 620.0])
    _raises("couple", association_window_s=(250.0, 400.0, 620.0))


@pytest.mark.parametrize(
    "window", [(375.5, 620.0), (250.0, 374.5)], ids=["after_start", "before_end"]
)
def test_crossing_is_inside_the_association_window(
    window: tuple[float, float],
) -> None:
    _raises("dans la fenêtre d'association", association_window_s=window)


@pytest.mark.parametrize(
    "changes",
    [{"arrival_s": 375.5}, {"departure_s": 374.5, "stop_total_s": 0.0}],
    ids=["arrival_after", "departure_before"],
)
def test_arrival_crossing_departure_are_ordered(changes: dict[str, Any]) -> None:
    _raises(r"arrival_s .* <= crossing_s .* <= departure_s", **changes)


def test_stop_total_fits_in_the_envelope() -> None:
    """``S <= départ − arrivée`` ; la limite ``S = départ − arrivée`` est valide
    (exemples)."""
    _raises("stop_total_s .* doit être <= departure_s − arrival_s", stop_total_s=113.5)


def test_episode_count_is_non_negative() -> None:
    with pytest.raises(ContractError, match="episode_count doit être >= 0"):
        replace(C, episode_count=-1)


def test_no_episode_means_zero_stop_total() -> None:
    _raises("stop_total_s doit valoir 0 sans épisode", episode_count=0)


def test_no_episode_means_arrival_equals_crossing_equals_departure() -> None:
    _raises(
        "sans épisode, arrival_s, crossing_s et departure_s",
        episode_count=0,
        stop_total_s=0.0,
    )


@pytest.mark.parametrize("role", [DEPARTURE, ARRIVAL])
def test_only_an_intermediate_receives_episodes(role: PassageRole) -> None:
    with pytest.raises(ContractError, match="seule une occurrence intermediate"):
        replace(A, role=role, comparable=role is ARRIVAL)


def test_episodes_need_instants() -> None:
    with pytest.raises(ContractError, match="a ses instants"):
        replace(C, episode_count=1)


@pytest.mark.parametrize(
    ("role", "status"),
    [(INTERMEDIATE, FOUND), (ARRIVAL, AMBIGUOUS), (DEPARTURE, AMBIGUOUS)],
    ids=["found", "arrival", "departure"],
)
def test_chronology_violation_is_an_ambiguous_intermediate(
    role: PassageRole, status: PassageStatus
) -> None:
    """Précision P1 : ``chronology_violation`` ⇒ ``AMBIGUOUS`` et ``INTERMEDIATE``."""
    with pytest.raises(ContractError, match="chronology_violation n'est porté"):
        replace(W1, role=role, status=status)


def test_anchored_is_a_departure_or_an_arrival() -> None:
    with pytest.raises(ContractError, match="peuvent être ANCHORED"):
        replace(B, status=ANCHORED)


def test_departure_is_never_comparable() -> None:
    with pytest.raises(ContractError, match="jamais comparable"):
        replace(DEPARTURE_FOUND, comparable=True)


@pytest.mark.parametrize("unavailability", list(Unavailability))
def test_departure_carries_no_motive(unavailability: Unavailability) -> None:
    """Précision P1 : un départ est non comparable **et** sans motif."""
    with pytest.raises(ContractError, match="aucun motif d'indisponibilité"):
        replace(DEPARTURE_FOUND, unavailability=unavailability)


def test_departure_is_never_outside_the_prefix() -> None:
    """Précision P1 : le départ est toujours observé."""
    with pytest.raises(ContractError, match="jamais OUTSIDE_PREFIX"):
        _undated("Départ", 0.0, OUTSIDE_PREFIX, None, role=DEPARTURE)


@pytest.mark.parametrize(
    "status",
    [
        AMBIGUOUS,
        PassageStatus.ABSENT,
        PassageStatus.OUT_OF_TOLERANCE,
        PassageStatus.UNDEFINED_TANGENT,
        OUTSIDE_PREFIX,
    ],
)
def test_comparable_is_found_or_anchored(status: PassageStatus) -> None:
    with pytest.raises(ContractError, match="comparable est FOUND ou ANCHORED"):
        replace(C, status=status, comparable=True, unavailability=None)


@pytest.mark.parametrize("unavailability", list(Unavailability))
def test_comparable_carries_no_motive(unavailability: Unavailability) -> None:
    with pytest.raises(ContractError, match="comparable ne porte aucun motif"):
        replace(A, unavailability=unavailability)


@pytest.mark.parametrize(
    "unavailability",
    [
        None,
        *(u for u in Unavailability if u is not Unavailability.INSUFFICIENT_SUPPORT),
    ],
)
def test_found_not_maintained_is_insufficient_support(
    unavailability: Unavailability | None,
) -> None:
    """``FOUND`` ou ``ANCHORED`` non comparable : ``insufficient_support``, hors de
    la table (précision P3)."""
    for passage in (A, ARRIVAL_ANCHORED):
        with pytest.raises(ContractError, match="non comparable a le motif"):
            replace(passage, comparable=False, unavailability=unavailability)


def test_ambiguous_by_chronology_is_ambiguous_unavailable() -> None:
    with pytest.raises(ContractError, match="non comparable a le motif"):
        replace(W1, unavailability=Unavailability.INSUFFICIENT_SUPPORT)


# ---------------------------------------------------------------------------
# EpisodeAttribution
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "attribution",
    [
        ATTRIBUTED,
        replace(ATTRIBUTED, passage_index=0),
        replace(ATTRIBUTED, outcome=EpisodeOutcome.TIE, passage_index=None),
        replace(ATTRIBUTED, outcome=EpisodeOutcome.NO_CANDIDATE, passage_index=None),
        replace(ATTRIBUTED, median_latitude_deg=90.0, median_longitude_deg=180.0),
        replace(ATTRIBUTED, median_latitude_deg=-90.0, median_longitude_deg=-180.0),
    ],
)
def test_attribution_examples_build(attribution: EpisodeAttribution) -> None:
    assert replace(attribution) == attribution


def test_attributed_has_a_passage_index() -> None:
    with pytest.raises(ContractError, match="si et seulement si l'épisode est"):
        replace(ATTRIBUTED, passage_index=None)


@pytest.mark.parametrize("outcome", [EpisodeOutcome.TIE, EpisodeOutcome.NO_CANDIDATE])
def test_unattributed_has_no_passage_index(outcome: EpisodeOutcome) -> None:
    with pytest.raises(ContractError, match="si et seulement si l'épisode est"):
        replace(ATTRIBUTED, outcome=outcome, passage_index=0)


def test_passage_index_is_non_negative() -> None:
    with pytest.raises(ContractError, match="passage_index doit être >= 0"):
        replace(ATTRIBUTED, passage_index=-1)


@pytest.mark.parametrize(
    ("changes", "match"),
    [
        ({"median_latitude_deg": math.nan}, "median_latitude_deg doit être fini"),
        ({"median_longitude_deg": math.inf}, "median_longitude_deg doit être fini"),
        ({"median_latitude_deg": 90.5}, "median_latitude_deg doit être dans"),
        ({"median_latitude_deg": -90.5}, "median_latitude_deg doit être dans"),
        ({"median_longitude_deg": 180.5}, "median_longitude_deg doit être dans"),
        ({"median_longitude_deg": -180.5}, "median_longitude_deg doit être dans"),
    ],
    ids=str,
)
def test_medians_are_finite_and_in_range(changes: dict[str, Any], match: str) -> None:
    with pytest.raises(ContractError, match=match):
        replace(ATTRIBUTED, **changes)


# ---------------------------------------------------------------------------
# PassageMatchResult
# ---------------------------------------------------------------------------


def _tie(start_s: float, end_s: float) -> EpisodeAttribution:
    return EpisodeAttribution(
        StopEpisode(start_s, end_s, 0, 1), EpisodeOutcome.TIE, None, 45.0, 6.0
    )


@pytest.mark.parametrize(
    "result",
    [
        PASSAGES_RESULT,
        CHRONOLOGY_RESULT,
        PassageMatchResult((), ()),
        # Limite : deux occurrences de même abscisse (Borne bis et Borne).
        PassageMatchResult((B, replace(B, point=_resolved("B bis", 250.4))), ()),
        # Limite : épisodes séparés, sans attribution.
        PassageMatchResult((C,), (_tie(10.0, 80.0), _tie(80.5, 200.0))),
    ],
)
def test_result_examples_build(result: PassageMatchResult) -> None:
    assert replace(result) == result


@pytest.mark.parametrize("field", ["passages", "episodes"])
def test_result_sequences_are_tuples(field: str) -> None:
    changes: dict[str, Any] = {field: list(getattr(PASSAGES_RESULT, field))}
    with pytest.raises(ContractError, match="séquence immuable"):
        replace(PASSAGES_RESULT, **changes)


def test_passages_follow_the_distance() -> None:
    with pytest.raises(ContractError, match="non décroissant le long de passages"):
        PassageMatchResult((A, B), ())


@pytest.mark.parametrize(
    "second", [(488.0, 500.0), (400.0, 500.0)], ids=["contact", "overlap"]
)
def test_episodes_are_in_time_order_and_disjoint(second: tuple[float, float]) -> None:
    with pytest.raises(ContractError, match="dans l'ordre du temps et disjoints"):
        PassageMatchResult((C,), (_tie(392.0, 488.0), _tie(*second)))


def test_passage_index_is_below_the_passage_count() -> None:
    """Précision P1 : ``passage_index < len(passages)``."""
    with pytest.raises(ContractError, match="dépasse le nombre de passages"):
        replace(PASSAGES_RESULT, episodes=(replace(ATTRIBUTED, passage_index=3),))


@pytest.mark.parametrize(
    "target",
    [
        replace(DEPARTURE_FOUND, point=_resolved("Départ", 375.0)),
        replace(ARRIVAL_ANCHORED, point=_resolved("Fin", 375.0)),
        _undated("A", 375.0, OUTSIDE_PREFIX, Unavailability.INSUFFICIENT_SUPPORT),
        _undated("A", 375.0, AMBIGUOUS, Unavailability.AMBIGUOUS),
    ],
    ids=["departure", "arrival", "outside_prefix", "ambiguous_search"],
)
def test_attributed_passage_is_found_or_ambiguous_by_chronology(
    target: PassageObservation,
) -> None:
    """Précision P1 : ``passage_index`` désigne une occurrence ``INTERMEDIATE``
    ``FOUND``, ou ``AMBIGUOUS`` avec ``chronology_violation`` (valide :
    ``CHRONOLOGY_RESULT``)."""
    with pytest.raises(ContractError, match="seule une occurrence intermediate FOUND"):
        PassageMatchResult((B, target, C), (ATTRIBUTED,))


def test_episode_count_matches_the_attributions() -> None:
    with pytest.raises(ContractError, match=r"episode_count .* doit valoir le nombre"):
        replace(PASSAGES_RESULT, episodes=())
    with pytest.raises(ContractError, match=r"episode_count .* doit valoir le nombre"):
        replace(PASSAGES_RESULT, episodes=(replace(ATTRIBUTED, passage_index=0),))


@pytest.mark.parametrize(
    ("changes", "name"),
    [
        ({"arrival_s": 370.0}, "arrival_s"),
        ({"departure_s": 490.0}, "departure_s"),
        ({"stop_total_s": 95.0}, "stop_total_s"),
    ],
)
def test_events_are_computed_on_the_attributed_episodes(
    changes: dict[str, Any], name: str
) -> None:
    """Égalités exactes : ``min``, ``max`` et ``math.fsum`` sur les épisodes
    attribués."""
    with pytest.raises(ContractError, match=rf"passages\[1\]\.{name} "):
        PassageMatchResult((B, replace(A, **changes), C), (ATTRIBUTED,))


def test_arrival_is_the_start_of_an_episode_before_the_crossing() -> None:
    """Chronologie : l'épisode ``[387 ; 602]`` commence avant ``t* = 425`` (W1) —
    ``arrival_s`` est le début de l'épisode, pas une valeur plus basse."""
    with pytest.raises(ContractError, match=r"passages\[0\]\.arrival_s "):
        replace(CHRONOLOGY_RESULT, passages=(replace(W1, arrival_s=380.0), W2))
