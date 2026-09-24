"""Sorties retenues, domaine, performances (§ 4.6 du brief M4a-1, ``0010`` D0, D2.1).

Instants à Paris en heure d'été (UTC+2, décalage fixe) ; ``Outing`` construits
directement.
"""

from dataclasses import replace
from datetime import UTC, date, datetime, timedelta

import pytest
from hypothesis import given
from hypothesis import strategies as st

from fixtures.outings import OUTING, PARIS_SUMMER, PREPARED, TRACE_ARTIFACT, outing_at
from mountain_perf.backtest.outings import (
    DOMAIN_MIN_DPLUS_PER_KM,
    RETENTION_LIMIT_S,
    domain_profile_source,
    dplus_per_km,
    group_performances,
    in_domain,
    retain_outings,
)
from mountain_perf.schemas import (
    Outing,
    ParameterSet,
    RetentionDecision,
    RouteProfile,
    Sport,
)

DAY = date(2026, 7, 17)
H = 3600.0


def _at(hour: int, minute: int = 0) -> datetime:
    return datetime(2026, 7, 17, hour, minute, tzinfo=PARIS_SUMMER)


def _day(
    *durations_h: float, gap_h: float = 0.5, sports: tuple[Sport, ...] = ()
) -> list[Outing]:
    """Sorties successives du 2026-07-17 à partir de 07:00, séparées de ``gap_h``."""
    outings: list[Outing] = []
    start = _at(7)
    for i, hours in enumerate(durations_h):
        sport = sports[i] if i < len(sports) else Sport.FOOT
        outings.append(outing_at(f"s{i + 1}", start, hours * H, sport=sport))
        start += timedelta(hours=hours + gap_h)
    return outings


def _summary(decisions: tuple[RetentionDecision, ...]) -> list[tuple[bool, float]]:
    return [(d.retained, d.cumulative_elapsed_s) for d in decisions]


# ---------------------------------------------------------------------------
# Sorties retenues (``0010`` D0) — une ligne du tableau du § 7.1 par test
# ---------------------------------------------------------------------------


def test_constants_of_0010() -> None:
    assert RETENTION_LIMIT_S == 4 * H
    assert DOMAIN_MIN_DPLUS_PER_KM == 40.0


def test_x20_second_outing_beyond_4_h_is_not_retained() -> None:
    assert _summary(retain_outings(_day(2, 3))) == [(True, 7200.0), (False, 18000.0)]


def test_x20_contrast_both_retained_and_multi_outing_performance() -> None:
    decisions = retain_outings(_day(1, 2))
    assert _summary(decisions) == [(True, 3600.0), (True, 10800.0)]
    (performance,) = group_performances(decisions, {"s1", "s2"})
    assert performance.is_multi_outing
    (single,) = group_performances(decisions, {"s2"})
    assert not single.is_multi_outing


def test_rdw_rule_one_hour_flat_then_two_and_a_half_hours() -> None:
    decisions = retain_outings(_day(1, 2.5))
    assert _summary(decisions) == [(True, 3600.0), (True, 12600.0)]


def test_rdw_rule_one_hour_then_three_and_a_half_hours() -> None:
    decisions = retain_outings(_day(1, 3.5))
    assert _summary(decisions) == [(True, 3600.0), (False, 16200.0)]


def test_boundary_4_h_exactly_is_not_retained() -> None:
    """Seuil strict : un cumul de 4 h pile n'est pas retenu."""
    decisions = retain_outings(_day(1, 3))
    assert _summary(decisions) == [(True, 3600.0), (False, 14400.0)]


def test_three_outings() -> None:
    decisions = retain_outings(_day(1, 3.5, 1 / 3))
    assert [d.retained for d in decisions] == [True, False, False]
    assert [d.rank for d in decisions] == [1, 2, 3]


def test_first_outing_is_retained_whatever_its_length() -> None:
    (decision,) = retain_outings(_day(9))
    assert decision.retained
    assert decision.cumulative_elapsed_s == 9 * H


def test_all_sports_count_towards_the_cumulative() -> None:
    decisions = retain_outings(_day(3.5, 1, sports=(Sport.MTB, Sport.FOOT)))
    assert [d.retained for d in decisions] == [True, False]


def test_midnight_outing_belongs_to_the_day_of_its_start() -> None:
    start = datetime(2026, 7, 17, 20, 30, tzinfo=UTC)
    outing = replace(
        outing_at("nuit", start, 60.0),
        end_time=datetime(2026, 7, 18, 0, 30, tzinfo=UTC),
    )
    (decision,) = retain_outings([outing])
    assert decision.civil_date == date(2026, 7, 17)


def test_civil_day_is_the_paris_day() -> None:
    (decision,) = retain_outings(
        [outing_at("tard", datetime(2026, 7, 17, 22, 30, tzinfo=UTC), 60)]
    )
    assert decision.civil_date == date(2026, 7, 18)


def test_ties_on_start_are_ranked_by_outing_id() -> None:
    decisions = retain_outings([outing_at("b", _at(9), H), outing_at("a", _at(9), H)])
    assert [(d.outing.outing_id, d.rank) for d in decisions] == [("a", 1), ("b", 2)]


def test_days_are_ranked_separately_and_in_order() -> None:
    today = _day(3.5, 1)
    tomorrow = [outing_at("t1", _at(9) + timedelta(days=1), 3 * H)]
    decisions = retain_outings([*tomorrow, *today])
    assert [(d.civil_date, d.rank, d.retained) for d in decisions] == [
        (DAY, 1, True),
        (DAY, 2, False),
        (DAY + timedelta(days=1), 1, True),
    ]


# ---------------------------------------------------------------------------
# Domaine (``0010`` D2.1)
# ---------------------------------------------------------------------------


def _profile(ascent_m: float) -> RouteProfile:
    return RouteProfile(
        route_name="Profil de domaine",
        source=OUTING.traces[0].source,
        distance_m=(0.0, 10_000.0),
        elevation_m=(0.0, ascent_m),
        resolved_points=(),
        step_m=50.0,
        build_parameters=ParameterSet(specs=()),
    )


@pytest.mark.parametrize(
    ("ascent_m", "expected", "inside"), [(399.9, 39.99, False), (400.0, 40.0, True)]
)
def test_x17_dplus_per_km_threshold_is_inclusive(
    ascent_m: float, expected: float, inside: bool
) -> None:
    value = dplus_per_km(_profile(ascent_m))
    assert value == pytest.approx(expected, abs=1e-9)
    assert in_domain(OUTING, value, date(2026, 5, 20)) is inside


@pytest.mark.parametrize(
    ("start", "inside"),
    [
        (datetime(2026, 5, 19, 22, 0, 0, tzinfo=UTC), True),
        (datetime(2026, 5, 19, 21, 59, 59, tzinfo=UTC), False),
    ],
    ids=["minuit-a-Paris", "veille-a-Paris"],
)
def test_domain_starts_on_the_declared_paris_day(start: datetime, inside: bool) -> None:
    outing = outing_at("debut", start, H)
    assert in_domain(outing, 80.0, date(2026, 5, 20)) is inside


def test_domain_is_foot_only() -> None:
    outing = outing_at("velo", _at(9), H, sport=Sport.MTB)
    assert not in_domain(outing, 80.0, date(2026, 5, 20))


def test_unknown_dplus_is_out_of_domain() -> None:
    assert not in_domain(OUTING, None, date(2026, 5, 20))


def test_domain_profile_source_prefers_the_reference() -> None:
    assert domain_profile_source(OUTING) == (PREPARED.artifact,)
    assert domain_profile_source(replace(OUTING, reference=None)) == (TRACE_ARTIFACT,)
    untraced = replace(OUTING, reference=None, traces=(), duplicates=())
    assert domain_profile_source(untraced) == ()


# ---------------------------------------------------------------------------
# Performances (``0010`` D0)
# ---------------------------------------------------------------------------


def test_performances_hold_retained_in_domain_outings_by_day() -> None:
    today = _day(1, 3.5, 0.5)  # s1 retenue, s2 et s3 non
    tomorrow = [
        outing_at("t1", _at(9) + timedelta(days=1), H),
        outing_at("t2", _at(14) + timedelta(days=1), H),
    ]
    after = [outing_at("u1", _at(9) + timedelta(days=2), H)]
    decisions = retain_outings([*after, *tomorrow, *today])
    performances = group_performances(decisions, {"s1", "s2", "t1", "t2"})
    assert [(p.civil_date, [o.outing_id for o in p.outings]) for p in performances] == [
        (DAY, ["s1"]),
        (DAY + timedelta(days=1), ["t1", "t2"]),
    ]


def test_a_day_without_retained_in_domain_outing_gives_nothing() -> None:
    decisions = retain_outings(_day(1, 1))
    assert group_performances(decisions, set()) == ()


# ---------------------------------------------------------------------------
# Propriétés
# ---------------------------------------------------------------------------


@st.composite
def _outing_lists(draw: st.DrawFn) -> list[Outing]:
    """Sorties sur trois jours, départs à la minute, durées de 1 min à 6 h."""
    count = draw(st.integers(min_value=1, max_value=12))
    base = datetime(2026, 7, 16, 22, 0, tzinfo=UTC)
    return [
        outing_at(
            f"o{i:02d}",
            base + timedelta(minutes=draw(st.integers(0, 3 * 24 * 60))),
            60.0 * draw(st.integers(1, 6 * 60)),
            sport=draw(st.sampled_from(Sport)),
        )
        for i in range(count)
    ]


@given(_outing_lists())
def test_retention_properties(outings: list[Outing]) -> None:
    decisions = retain_outings(outings)
    assert sorted(d.outing.outing_id for d in decisions) == sorted(
        o.outing_id for o in outings
    )
    assert [(d.civil_date, d.rank) for d in decisions] == sorted(
        (d.civil_date, d.rank) for d in decisions
    )
    by_day: dict[date, list[RetentionDecision]] = {}
    for decision in decisions:
        by_day.setdefault(decision.civil_date, []).append(decision)
    for day_decisions in by_day.values():
        assert [d.rank for d in day_decisions] == list(range(1, len(day_decisions) + 1))
        assert day_decisions[0].retained
        flags = [d.retained for d in day_decisions]
        assert flags == sorted(flags, reverse=True)  # préfixe de rangs retenus
        cumuls = [d.cumulative_elapsed_s for d in day_decisions]
        assert cumuls == sorted(cumuls)
        assert cumuls[-1] == pytest.approx(
            sum(d.outing.elapsed_s for d in day_decisions)
        )
        starts = [(d.outing.start_time, d.outing.outing_id) for d in day_decisions]
        assert starts == sorted(starts)


@given(_outing_lists(), st.data())
def test_performance_properties(outings: list[Outing], data: st.DataObject) -> None:
    decisions = retain_outings(outings)
    in_domain_ids = set(
        data.draw(st.lists(st.sampled_from([o.outing_id for o in outings])))
    )
    performances = group_performances(decisions, in_domain_ids)
    dates = [p.civil_date for p in performances]
    assert dates == sorted(set(dates))
    retained = {
        (d.civil_date, d.outing.outing_id)
        for d in decisions
        if d.retained and d.outing.outing_id in in_domain_ids
    }
    assert {
        (p.civil_date, o.outing_id) for p in performances for o in p.outings
    } == retained
