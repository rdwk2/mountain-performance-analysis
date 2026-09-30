"""Observation d'une sortie : ``observe_outing`` (§ 6.3 et § 8.1, tests 3 et 4, du
brief M4b-2 ; ``0010`` D4.2, D4.8, D4.11, D4.12, D5.3, D5.4, D7.1, D7.3, D7.4).

Test 3 : sur les treize cas du § 7.2, chaque champ du tableau (préfixe, segments admis,
classes, ``b_0``, ``t*_0``, écart, ``θ``, points de ``C_k`` et éléments de ``K`` dans
l'ordre, temps nuls) et les valeurs de l'oracle du § 7.3, à la tolérance relative du
§ 7.0. Test 4 : les propriétés exactes du § 7.4 — totaux admis de M4a, même lieu dans
``C_k`` et dans ``K`` —, sur les treize cas et sur ``strategies.passage_cases``.
"""

import math

import pytest
from hypothesis import given, settings

from fixtures.matching import MatchCase
from fixtures.scoring import (
    CONSTRUCTED,
    SCORING_CASES,
    Chain,
    chain,
    close,
    observation,
    run_chain,
)
from fixtures.scoring_values import VALUES, P, V
from mountain_perf.backtest import observe_outing
from mountain_perf.schemas import (
    CLOCKS,
    ClockKind,
    ObservedPoint,
    OutingObservation,
    RegimeClass,
    Unavailability,
)
from strategies import passage_cases

ELAPSED, MOVING_C, MOVING_OR_UNDETERMINED_C = 0, 2, 7
"""Indices dans ``CLOCKS`` de ``E``, ``M θc`` et ``(M+U) θc`` (§ 7.0)."""

MOVING = [i for i, c in enumerate(CLOCKS) if c.kind is ClockKind.MOVING]
MOVING_OR_UNDETERMINED = [
    i for i, c in enumerate(CLOCKS) if c.kind is ClockKind.MOVING_OR_UNDETERMINED
]


def _values(name: str) -> V:
    """Les valeurs du § 7.3 ; « Régimes sans référence » a celles de Régimes."""
    return VALUES["Régimes" if name == "Régimes sans référence" else name]


def _label(c: Chain, point: ObservedPoint, *, arrival: bool = False) -> str:
    """Le libellé du § 7.3 : ``point k``, le nom du lieu, ``arrivée`` ou
    ``arrivée (nom)``."""
    name = None
    if point.passage_index is not None:
        name = c.passages.passages[point.passage_index].point.point.name
    if arrival:
        return "arrivée" if name is None else f"arrivée ({name})"
    if name is not None:
        return name
    return f"point {point.score_index}"


def _check_rows(observed: tuple[ObservedPoint, ...], rows: tuple[P, ...]) -> None:
    assert len(observed) == len(rows)
    for point, row in zip(observed, rows, strict=True):
        assert point.unavailability is row.motif
        assert close(point.distance_m, row.distance_m)
        if row.times_s is None:
            assert point.times_s is None
        else:
            assert point.times_s is not None
            assert close(point.times_s[ELAPSED], row.times_s[0])
            assert close(point.times_s[MOVING_C], row.times_s[1])


# ---------------------------------------------------------------------------
# Test 3 : structure et valeurs (§ 7.2, § 7.3)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("name", SCORING_CASES)
def test_observation_fields_of_the_table(name: str) -> None:
    """§ 7.2 : préfixe ``m/K``, segments admis et leurs classes, ``b_0``, ``t*_0``,
    écart présent ou non (``0010`` D4.8, choix 7), ``(θ_bas, θ_haut)``, temps nuls
    sous ``M θ1 … M θ5``."""
    c, observed, expected = chain(name), observation(name), _values(name)
    assert c.match.coverage.prefix_segment_count == expected.prefix
    assert len(c.match.segments) == expected.segment_count
    assert [s.index for s in observed.segments] == [r.index for r in expected.segments]
    assert [s.regime_class for s in observed.segments] == [
        r.regime_class for r in expected.segments
    ]
    assert close(observed.origin_m, expected.origin_m)
    assert close(observed.origin_s, expected.origin_s)
    assert close(observed.arrival_anchor_gap_m, expected.gap_m)
    assert close(observed.reference_length_m, c.profile.distance_m[-1])
    low, high = c.match.low_convention_index, c.match.high_convention_index
    conventions = None if low is None or high is None else (low + 1, high + 1)
    assert conventions == expected.conventions
    zero_time = {
        f"M{n + 1}": [s.index for s in observed.segments if s.times_s[i] == 0.0]
        for n, i in enumerate(MOVING)
    }
    assert {k: v for k, v in zero_time.items() if v} == expected.zero_time


@pytest.mark.parametrize("name", SCORING_CASES)
def test_admitted_segments_values(name: str) -> None:
    """``0010`` D4.2, D5.3, D7.1 ; choix 1 : bornes effectives, abscisses réalisées
    et temps sous ``E``, ``M θc``, ``(M+U) θc`` du § 7.3 ; bornes recopiées (``==``)
    du ``ScoreSegmentObservation`` de M4a, nominales comprises."""
    c, observed, expected = chain(name), observation(name), _values(name)
    by_index = {s.index: s for s in c.match.segments}
    for segment, row in zip(observed.segments, expected.segments, strict=True):
        source = by_index[segment.index]
        assert source.admitted
        assert (
            segment.nominal_start_m,
            segment.nominal_end_m,
            segment.start_m,
            segment.end_m,
            segment.realized_start_m,
            segment.realized_end_m,
            segment.regime_class,
        ) == (
            source.nominal_start_m,
            source.nominal_end_m,
            source.start_m,
            source.end_m,
            source.realized_start_m,
            source.realized_end_m,
            source.regime_class,
        )
        assert close(segment.start_m, row.start_m)
        assert close(segment.end_m, row.end_m)
        assert close(segment.realized_start_m, row.realized_start_m)
        assert close(segment.realized_end_m, row.realized_end_m)
        for i, expected_s in zip(
            (ELAPSED, MOVING_C, MOVING_OR_UNDETERMINED_C), row.times_s, strict=True
        ):
            assert close(segment.times_s[i], expected_s)


@pytest.mark.parametrize("name", SCORING_CASES)
def test_error_points_of_the_prefix(name: str) -> None:
    """``0010`` D4.11, D4.12, D7.3 ; décision 3, choix 2, 3 et 6 : points de score
    ``1 … m`` en ``b_k`` à ``t*_k``, lieux intermédiaires non hors préfixe en ``s_w``,
    au départ de leur événement ou avec leur motif, origine exclue, par abscisse ;
    ``T`` depuis ``t*_0``."""
    c, observed, expected = chain(name), observation(name), _values(name)
    assert [_label(c, p) for p in observed.error_points] == [
        r.label for r in expected.points
    ]
    _check_rows(observed.error_points, expected.points)


@pytest.mark.parametrize("name", SCORING_CASES)
def test_targets_of_k(name: str) -> None:
    """``0010`` D4.8, D4.12, D7.4 ; décision 3 : ``K`` par défaut, un élément par
    membre ; l'arrivée en ``b_K`` à ``t*_K``, disponible si et seulement si ``m = K``,
    ``support insuffisant`` sinon ; désignée par un lieu, elle ne donne que son
    nom."""
    c, observed, expected = chain(name), observation(name), _values(name)
    last = len(observed.targets) - 1
    assert [
        _label(c, p, arrival=k == last) for k, p in enumerate(observed.targets)
    ] == [r.label for r in expected.targets]
    _check_rows(observed.targets, expected.targets)
    final = c.match.points[-1]
    arrival = observed.targets[-1]
    assert arrival.distance_m == final.effective_m
    assert arrival.score_index == len(c.match.points) - 1
    assert arrival.available == (
        c.match.coverage.prefix_segment_count == len(c.match.segments)
    )


def test_regimes_without_reference_observes_the_same_outing() -> None:
    """« Régimes sans référence » (§ 7.2) : l'observation ne dépend d'aucun modèle ni
    de la référence projetée (``0010`` D7.1)."""
    assert observation("Régimes sans référence") == observation("Régimes")


def test_arrival_anchor_gap_is_published_outside_the_prefix() -> None:
    """Choix 7 (``0010`` D4.8) : Régimes déviation, arrivée ancrée hors du préfixe —
    écart publié, élément d'arrivée ``support insuffisant``, lu en ``b_K``."""
    observed = observation("Régimes déviation")
    arrival = observed.targets[-1]
    assert arrival.unavailability is Unavailability.INSUFFICIENT_SUPPORT
    assert observed.arrival_anchor_gap_m is not None
    final = chain("Régimes déviation").match.points[-1]
    assert observed.arrival_anchor_gap_m == 0.0 - final.anchoring_offset_m
    assert arrival.distance_m == final.effective_m < final.nominal_m


def test_segment_of_zero_time_keeps_its_index() -> None:
    """Régimes déviation (§ 7.2) : le segment de temps nul est le segment 4, le
    quatrième admis (rang 3) ; un segment non admis (1) le précède."""
    observed = observation("Régimes déviation")
    assert [s.index for s in observed.segments] == [0, 2, 3, 4]
    assert observed.segments[3].times_s[MOVING_C] == 0.0


def test_classes_of_regimes() -> None:
    """Régimes (§ 7.2) : mixte 1, plat 1, descente 3 — la classe de la référence."""
    classes = [s.regime_class for s in observation("Régimes").segments]
    assert classes.count(RegimeClass.MIXED) == 1
    assert classes.count(RegimeClass.FLAT) == 1
    assert classes.count(RegimeClass.DESCENT) == 3


# ---------------------------------------------------------------------------
# Test 4 : propriétés exactes (§ 7.4)
# ---------------------------------------------------------------------------


def _check_admitted_totals(c: Chain, observed: OutingObservation) -> None:
    """Choix 1 : sous ``E`` et chaque ``M_θ``, ``fsum`` des temps des segments admis
    ``==`` les totaux admis de M4a ; sous ``M_θ + U_θ``, à ``1e−9·max(1, E_A)``."""
    totals = c.match.admitted_totals
    times = [s.times_s for s in observed.segments]
    elapsed_s = math.fsum(t[ELAPSED] for t in times)
    for k, i in enumerate(MOVING):
        assert elapsed_s == totals[k].elapsed_s
        assert math.fsum(t[i] for t in times) == totals[k].moving_s
    for k, i in enumerate(MOVING_OR_UNDETERMINED):
        expected = totals[k].moving_s + totals[k].undetermined_s
        tolerance = 1e-9 * max(1.0, totals[k].elapsed_s)
        assert abs(math.fsum(t[i] for t in times) - expected) <= tolerance


def _check_same_place(observed: OutingObservation) -> None:
    """``0010`` D4.12 : un même lieu a les mêmes temps (``==``) comme point de
    ``C_k`` et comme élément de ``K``."""
    places = {
        p.passage_index: p for p in observed.error_points if p.score_index is None
    }
    for target in observed.targets:
        if target.score_index is None and target.passage_index in places:
            assert target == places[target.passage_index]


def _check_undated(observed: OutingObservation) -> None:
    """Un départ non daté ne produit aucun point et aucun élément disponible."""
    if observed.origin_s is None:
        assert observed.error_points == ()
        assert observed.segments == ()
        assert not any(target.available for target in observed.targets)


@pytest.mark.parametrize("name", SCORING_CASES)
def test_observation_properties_on_the_cases(name: str) -> None:
    """§ 7.4, sur les treize cas : totaux admis de M4a, même lieu, départ non daté."""
    c, observed = chain(name), observation(name)
    _check_admitted_totals(c, observed)
    _check_same_place(observed)
    _check_undated(observed)


def test_undated_departure_observes_no_point() -> None:
    """Départ non daté (§ 7.2) : origine absente, aucun segment, aucun point, ``K``
    entièrement indisponible."""
    observed = observation("Départ non daté")
    assert observed.origin_s is None
    assert observed.error_points == ()
    assert [t.unavailability for t in observed.targets] == [
        Unavailability.INSUFFICIENT_SUPPORT
    ] * 2


@settings(deadline=None)
@given(passage_cases())
def test_observation_properties_on_drawn_cases(case: MatchCase) -> None:
    """§ 7.4 et test 4 : les mêmes propriétés sur les cas de la stratégie de
    M4a-3 (lieux, arrêts, reptations, détours, traces courtes)."""
    c = run_chain(case)
    observed = observe_outing(c.match, c.passages, c.partition)
    _check_admitted_totals(c, observed)
    _check_same_place(observed)
    _check_undated(observed)
    assert [p.score_index for p in observed.error_points if p.score_index] == list(
        range(1, c.match.coverage.prefix_segment_count + 1)
    )


def test_constructed_cases_are_the_twelve_constructors() -> None:
    assert len(CONSTRUCTED) == 12
    assert set(VALUES) == set(CONSTRUCTED)
