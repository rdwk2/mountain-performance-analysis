"""Les données de Q2 (AN3-3b, ``docs/decisions/0023``) : jointure, journées, appareil
principal, exclusions et premier motif, normale de Q2, ``e_s`` et la règle « FC de
repos mesurée après la sortie » (cas C1 à C5, C18 du brief). Sur des tables inventées
(``tests/fixtures/q2_world.py``)."""

from __future__ import annotations

import math
from collections import Counter
from collections.abc import Sequence
from datetime import UTC, date, datetime, timedelta

import pytest

pytest.importorskip("numpy")
pytest.importorskip("scipy")

from fixtures.q2_world import (
    PLUS1,
    PLUS2,
    at,
    day_range,
    q2_activity,
    q2_climb,
    q2_day_row,
    q2_tables,
)
from mountain_perf.analyse.athlete import Periods
from mountain_perf.analyse.q2.data import (
    Period,
    Q2Data,
    Q2Error,
    Q2Motif,
    period_of,
    principal_device,
    q2_data,
    q2_normals,
)
from mountain_perf.analyse.q2.parameters import Q2_PARAMETER_SPECS
from mountain_perf.analyse.tables import Tables
from mountain_perf.schemas import ParameterSet
from mountain_perf.schemas.days import RestingHrStatus
from mountain_perf.schemas.processed import (
    ClimbFlag,
    ClimbRegime,
    DayRow,
    JournalEventType,
)

LONG = ClimbRegime.LONG_CLIMB
SHORT = ClimbRegime.SHORT_CLIMB
DEFAULTS = ParameterSet(Q2_PARAMETER_SPECS)


def _params(**values: float) -> ParameterSet:
    return ParameterSet(Q2_PARAMETER_SPECS, values)


def _data(tables: Tables, periods: Periods | None = None) -> Q2Data:
    return q2_data(tables, periods, DEFAULTS)


# --- C1 ---------------------------------------------------------------------


def test_c1_the_day_of_an_activity_is_its_local_date_and_days_are_merged() -> None:
    """C1 : 23 h 50 et 00 h 10 à +01:00 font deux journées locales ; deux activités le
    même jour font une journée ; une montée après minuit reste au jour de son
    activité."""
    a1 = at(date(2025, 3, 10), 23, 50)
    a2 = at(date(2025, 3, 11), 0, 10)
    a3 = at(date(2025, 3, 12), 8)
    a4 = at(date(2025, 3, 12), 14)
    activities = [
        q2_activity("a1", a1),
        q2_activity("a2", a2),
        q2_activity("a3", a3),
        q2_activity("a4", a4),
    ]
    climbs = [
        q2_climb("a1", a1, gain_m=300, moving_s=1000),
        q2_climb("a1", a1, offset_s=1800, gain_m=310, moving_s=1000),
        q2_climb("a2", a2, gain_m=320, moving_s=1000),
        q2_climb("a3", a3, gain_m=330, moving_s=1000),
        q2_climb("a4", a4, gain_m=340, moving_s=800),
    ]
    data = _data(q2_tables(activities, climbs))
    days = data.days[LONG]
    assert [d.day for d in days] == [
        date(2025, 3, 10),
        date(2025, 3, 11),
        date(2025, 3, 12),
    ]
    assert [len(d.climbs) for d in days] == [2, 1, 2]
    assert days[0].climbs[1].local_start_time == at(date(2025, 3, 11), 0, 20)
    assert [d.activity_count for d in days] == [1, 1, 2]
    twelfth = days[2]
    assert sum(c.y for c in twelfth.climbs) / 2 == pytest.approx(
        (math.log(0.33) + math.log(0.425)) / 2, rel=1e-12
    )


# --- C2 ---------------------------------------------------------------------


def _device_world(
    p_days: Sequence[date], q_days: Sequence[date], none_days: Sequence[date] = ()
) -> Tables:
    activities, climbs = [], []
    for k, (product, days) in enumerate(((1, p_days), (2, q_days), (None, none_days))):
        for i, day in enumerate(days):
            ref = f"p{k}_{i}"
            when = at(day, 8 + i % 3)
            activities.append(q2_activity(ref, when, product=product))
            climbs.append(q2_climb(ref, when))
    return q2_tables(activities, climbs)


def test_c2_the_principal_device_counts_days_not_activities() -> None:
    """C2 : P sur 3 jours (dont un à deux activités), Q sur 1 → P ; les montées de Q
    sont ``appareil_non_principal``."""
    d = [date(2025, 1, 1), date(2025, 1, 2), date(2025, 1, 3)]
    tables = _device_world([d[0], d[0], d[1], d[2]], [d[1]])
    assert principal_device(tables.activities, tables.climbs) == ("garmin", 1)
    data = _data(tables)
    assert [e.motif for e in data.excluded] == [Q2Motif.DEVICE]
    assert data.principal == ("garmin", 1)


def test_c2_a_tie_in_days_is_refused_even_if_activities_differ() -> None:
    """C2 : P sur 2 jours par 3 activités, Q sur 2 jours par 2 → égalité en jours."""
    d = [date(2025, 1, 1), date(2025, 1, 2)]
    tables = _device_world([d[0], d[0], d[1]], [d[0], d[1]])
    with pytest.raises(Q2Error) as error:
        principal_device(tables.activities, tables.climbs)
    assert str(error.value) == (
        "appareil principal indécidable : garmin:1 et garmin:2 portent chacun 2 jours"
    )


def test_c2_a_product_without_number_is_never_a_candidate() -> None:
    days = [date(2025, 1, i) for i in range(1, 6)]
    tables = _device_world([days[0]], [], days)
    assert principal_device(tables.activities, tables.climbs) == ("garmin", 1)
    only_none = _device_world([], [], days)
    with pytest.raises(Q2Error, match="aucun appareil désigné"):
        principal_device(only_none.activities, only_none.climbs)


# --- C3 ---------------------------------------------------------------------

APRIL_2 = date(2025, 4, 2)


def c3_tables() -> Tables:
    """Le monde de C3 : activités du 2 avril sauf mention, V_ref = 0,25 m/s."""
    t1 = at(APRIL_2, 9)
    t2, t3 = at(APRIL_2, 10), at(APRIL_2, 11)
    t4 = at(date(2025, 4, 3), 9)
    t5 = at(APRIL_2, 14)
    t6 = at(date(2025, 4, 5), 9)
    activities = [
        q2_activity("a1", t1),
        q2_activity("a2", t2, product=2),
        q2_activity("a3", t3, sessions=2),
        q2_activity("a4", t4),
        q2_activity("a5", t5),
        q2_activity("a6", t6),
    ]
    climbs = [
        q2_climb("a1", t1, offset_s=0, gain_m=301),  # m1
        q2_climb(
            "a1", t1, offset_s=100, flags=[ClimbFlag.SPIKE], vertical_speed_ms=None
        ),  # m2
        q2_climb("a1", t1, offset_s=200, regime=ClimbRegime.INTERMEDIATE),  # m3
        q2_climb("a1", t1, offset_s=300, regime=SHORT, gain_m=45.0),  # m4
        q2_climb("a1", t1, offset_s=400, regime=SHORT, gain_m=45.5),  # m5
        q2_climb(
            "a1", t1, offset_s=500, gain_m=306, flags=[ClimbFlag.SLOW_MOVING]
        ),  # m6
        q2_climb("a1", t1, offset_s=600, coverage=0.79),  # m7
        q2_climb("a1", t1, offset_s=700, gain_m=308, coverage=0.8),  # m8
        q2_climb("a2", t2, flags=[ClimbFlag.SPIKE]),  # m9
        q2_climb("a3", t3),  # m10
        q2_climb("a4", t4),  # m11
        q2_climb("a5", t5, gain_m=312),  # m12
        q2_climb("a1", t1, offset_s=800, flags=[ClimbFlag.SPIKE]),  # m13
        q2_climb("a6", t6, gain_m=314),  # m14
    ]
    days = [
        q2_day_row(date(2025, 3, 1) + timedelta(days=i))
        for i in range((date(2025, 4, 3) - date(2025, 3, 1)).days)
    ]
    days.append(q2_day_row(date(2025, 4, 3), journal=[JournalEventType.ILLNESS]))
    return q2_tables(activities, climbs, days, v_ref=0.25)


def test_c3_each_climb_is_counted_at_its_first_motif() -> None:
    """C3 : le premier motif de chaque montée, une seule fois."""
    data = _data(c3_tables())
    found = Counter((e.activity_ref, e.regime, e.motif) for e in data.excluded)
    assert found == Counter(
        {
            ("a1", LONG, Q2Motif.FLAG): 2,
            ("a1", ClimbRegime.INTERMEDIATE, Q2Motif.OUTSIDE_REGIMES): 1,
            ("a1", SHORT, Q2Motif.SHORT_GAIN): 1,
            ("a1", LONG, Q2Motif.NO_HEART_RATE): 1,
            ("a2", LONG, Q2Motif.DEVICE): 1,
            ("a3", LONG, Q2Motif.SESSIONS): 1,
            ("a4", LONG, Q2Motif.JOURNAL): 1,
        }
    )
    long_days = data.days[LONG]
    assert [d.day for d in long_days] == [APRIL_2, date(2025, 4, 5)]
    april_2 = long_days[0]
    assert [c.gain_m for c in april_2.climbs] == [301, 306, 308, 312]
    assert april_2.activity_count == 2
    assert april_2.step5 is None
    assert april_2.e_s == 0.0
    assert april_2.r == 55.0
    fifth = long_days[1]
    assert fifth.step5 is Q2Motif.RESTING_INVALID
    assert fifth.step6 is Q2Motif.MS_NO_NORMAL
    assert fifth.e_s is None
    assert [d.day for d in data.days[SHORT]] == [APRIL_2]
    assert [c.gain_m for c in data.days[SHORT][0].climbs] == [45.5]
    assert data.days[ClimbRegime.SKI_TOURING] == ()
    assert data.activity_dates == (APRIL_2, date(2025, 4, 5))
    assert data.regimes_present == (
        SHORT,
        ClimbRegime.INTERMEDIATE,
        LONG,
    )


# --- C4, C4 bis -------------------------------------------------------------


def _c4_days() -> list[DayRow]:
    first = date(2025, 1, 1)
    rows = []
    for i in range(40):
        ranks: tuple[int, ...] = (1,) if i <= 28 else () if i == 29 else (2,)
        rows.append(
            q2_day_row(
                first + timedelta(days=i),
                resting=50.0 + i % 7,
                ranks=ranks,
                uncertain=i == 29,
                journal=[JournalEventType.ILLNESS] if i == 12 else (),
            )
        )
    return rows


@pytest.mark.parametrize(
    ("index", "expected"),
    [
        (13, None),
        (14, None),
        (15, 52.5),
        (27, 53.0),
        (29, 53.0),
        (30, None),
        (35, None),
        (39, None),
    ],
)
def test_c4_the_q2_normal(index: int, expected: float | None) -> None:
    """C4 : fenêtre de 28 jours sans le jour lui-même, 14 jours admis au moins,
    coupée au changement de montre."""
    rows = _c4_days()
    normals = q2_normals(rows, DEFAULTS)
    assert normals[rows[index].day] == expected


def test_c4_with_five_admitted_days() -> None:
    rows = _c4_days()
    normals = q2_normals(rows, _params(normal_min_admitted_days=5))
    assert normals[rows[35].day] == 54.0
    assert normals[rows[39].day] == 53.0


def test_c4_bis_an_uncertain_day_never_enters_the_window() -> None:
    """C4 bis : le jour 5 (deux rangs, rupture) coupe la fenêtre et n'y entre pas."""
    first = date(2025, 2, 1)
    rows = [
        q2_day_row(
            first + timedelta(days=i),
            resting=50.0 + i % 7,
            ranks=(1, 2) if i == 5 else (1,),
            admitted=True,
        )
        for i in range(10)
    ]
    normals = q2_normals(rows, _params(normal_min_admitted_days=3))
    assert normals[rows[9].day] == 51.0


# --- C5 ---------------------------------------------------------------------

TARGET = date(2025, 6, 21)


def _step5_world(
    target: DayRow | None,
    before: list[DayRow],
    *,
    regime: ClimbRegime = LONG,
    h: float = 150.0,
) -> Q2Data:
    when = at(TARGET, 9, tz=PLUS2)
    rows = [*before, *([] if target is None else [target])]
    tables = q2_tables(
        [q2_activity("x1", when)],
        [q2_climb("x1", when, regime=regime, gain_m=300, h=h)],
        rows,
    )
    return _data(tables)


def _before(count: int = 20, **changes: object) -> list[DayRow]:
    return day_range(TARGET - timedelta(days=count), count, **changes)


def _motif(data: Q2Data, regime: ClimbRegime = LONG) -> Q2Motif | None:
    (day,) = data.days[regime]
    return day.step5


def test_c5_each_cause_of_an_undefined_e_s() -> None:
    """C5 : chaque cause de ``e_s`` indéfini, avec son motif."""
    provisional = q2_day_row(TARGET, status=RestingHrStatus.PROVISIONAL)
    assert _motif(_step5_world(provisional, _before())) is Q2Motif.RESTING_INVALID
    assert _motif(_step5_world(None, _before())) is Q2Motif.RESTING_INVALID
    assert _motif(_step5_world(q2_day_row(TARGET), _before(5))) is Q2Motif.NO_NORMAL
    straddle = q2_day_row(TARGET, ranks=(1, 2))
    assert _motif(_step5_world(straddle, _before(ranks=()))) is Q2Motif.STRADDLING
    assert _motif(_step5_world(straddle, _before())) is Q2Motif.NO_NORMAL
    uncertain = q2_day_row(TARGET, ranks=(), uncertain=True)
    assert _motif(_step5_world(uncertain, _before())) is Q2Motif.UNCERTAIN
    after = q2_day_row(TARGET, midpoint=at(TARGET, 14, tz=PLUS2))
    assert _motif(_step5_world(after, _before())) is Q2Motif.RESTING_AFTER
    both = q2_day_row(TARGET, status=RestingHrStatus.PROVISIONAL, ranks=(1, 2))
    assert _motif(_step5_world(both, _before(ranks=()))) is Q2Motif.RESTING_INVALID
    short = _step5_world(provisional, _before(), regime=SHORT)
    assert _motif(short, SHORT) is Q2Motif.RESTING_INVALID


def test_c5_e_s_is_the_resting_rate_minus_the_q2_normal() -> None:
    data = _step5_world(q2_day_row(TARGET, resting=58.0), _before(resting=55.0))
    (day,) = data.days[LONG]
    assert day.step5 is None
    assert day.e_s == 3.0
    assert day.r == 55.0
    assert day.step6 is None


@pytest.mark.parametrize(("h", "motif"), [(60.0, Q2Motif.MS_RESERVE), (60.5, None)])
def test_c5_the_ms_reserve_is_judged_per_climb(h: float, motif: Q2Motif | None) -> None:
    """C5 : ``h − r ≤ 0`` exclut la montée de M-S."""
    data = _step5_world(q2_day_row(TARGET, resting=60.0), _before(resting=60.0), h=h)
    (day,) = data.days[LONG]
    assert day.reserve == (motif,)


def test_the_ms_day_motifs_follow_the_step5_rules_for_r() -> None:
    straddle = q2_day_row(TARGET, ranks=(1, 2))
    (day,) = _step5_world(straddle, _before(ranks=())).days[LONG]
    assert day.step6 is Q2Motif.MS_STRADDLING
    uncertain = q2_day_row(TARGET, ranks=(), uncertain=True)
    (day,) = _step5_world(uncertain, _before()).days[LONG]
    assert day.step6 is Q2Motif.MS_UNCERTAIN
    assert day.r is None


# --- C18 --------------------------------------------------------------------

MAY_6 = date(2025, 5, 6)


def _c18(midpoint: datetime | None, footing: bool = True) -> Q2Motif | None:
    run = at(MAY_6, 7, tz=PLUS2)
    climb_start = at(MAY_6, 14, tz=PLUS2)
    activities = [q2_activity("c1", climb_start)]
    if footing:
        activities.append(q2_activity("f1", run, product=9))
    rows = day_range(MAY_6 - timedelta(days=20), 20, tz=PLUS2)
    rows.append(q2_day_row(MAY_6, midpoint=midpoint, tz=PLUS2))
    tables = q2_tables(activities, [q2_climb("c1", climb_start)], rows)
    (day,) = _data(tables).days[LONG]
    return day.step5


def test_c18_the_resting_rate_after_the_first_outing_of_the_day() -> None:
    """C18 : la première activité du jour, quels que soient son sport, ses montées et
    son appareil ; une comparaison d'instants ; un milieu égal au départ est
    « après »."""
    after = Q2Motif.RESTING_AFTER
    assert _c18(at(MAY_6, 10, 15, tz=PLUS2)) is after
    assert _c18(at(MAY_6, 10, 15, tz=PLUS2), footing=False) is None
    assert _c18(at(MAY_6, 7, 0, tz=PLUS2)) is after
    assert _c18(None) is None
    assert _c18(at(MAY_6, 6, 15, tz=PLUS1)) is after
    assert _c18(at(MAY_6, 6, 45, tz=PLUS2)) is None


# --- les périodes -----------------------------------------------------------


def test_the_period_of_a_day() -> None:
    periods = Periods(date(2031, 3, 1), date(2031, 5, 31))
    assert period_of(date(2031, 2, 28), periods) is Period.BEFORE
    assert period_of(date(2031, 3, 1), periods) is Period.DISCOVERY
    assert period_of(date(2031, 5, 31), periods) is Period.DISCOVERY
    assert period_of(date(2031, 6, 1), periods) is Period.AFTER
    assert period_of(date(2031, 6, 1), None) is Period.ALL


def test_a_day_carries_its_period() -> None:
    when = at(date(2031, 3, 1), 9)
    tables = q2_tables([q2_activity("p1", when)], [q2_climb("p1", when)])
    periods = Periods(date(2031, 3, 1), date(2031, 5, 31))
    (day,) = q2_data(tables, periods, DEFAULTS).days[LONG]
    assert day.period is Period.DISCOVERY


def test_a_climb_without_mean_elevation_has_no_speed() -> None:
    """Q-49 (m) : l'altitude moyenne absente exclut sous ``vitesse_absente``."""
    when = at(date(2025, 1, 1), 9)
    tables = q2_tables(
        [q2_activity("e1", when)],
        [q2_climb("e1", when, moving_mean_elevation_m=None)],
    )
    assert [e.motif for e in _data(tables).excluded] == [Q2Motif.NO_SPEED]


def test_utc_and_local_dates_differ_here() -> None:
    """Garde du cas C1 : à +01:00, 23 h 50 est encore la veille en UTC aussi, mais
    00 h 10 est la veille en UTC."""
    moment = at(date(2025, 3, 11), 0, 10)
    assert moment.astimezone(UTC).date() == date(2025, 3, 10)


# --- correctifs de la PR #52 : paramètres, ensembles exclus, minuit, heure ------------

BRIEF_DEFAULTS: tuple[tuple[str, float], ...] = (
    ("min_heart_rate_coverage", 0.8),
    ("short_climb_min_gain_s", 180.0),
    ("route_radius_m", 100.0),
    ("route_max_gain_ratio", 1.10),
    ("min_route_days", 3.0),
    ("normal_window_days", 28.0),
    ("normal_min_admitted_days", 14.0),
    ("min_residual_df", 25.0),
    ("min_estimable_df", 10.0),
    ("phi_min_days", 2.0),
    ("alpha", 0.05),
    ("secondary_family_size", 5.0),
    ("delta", 0.05),
    ("bounded_reading_slope_bpm_per_year", 2.0),
    ("bootstrap_draws", 2000.0),
    ("power_draws", 2000.0),
    ("calibration_trigger", 0.075),
    ("power_target_visible", 0.8),
    ("power_target_no_effect", 0.9),
    ("power_target_undecided", 0.5),
    ("heart_rate_reliability", 0.85),
    ("slow_component_sd", 0.03),
    ("slow_component_days", 45.0),
    ("hinge_peak", 0.08),
    ("discovery_step", 0.05),
    ("bounds_trigger", 0.10),
    ("s14_min_months", 10.0),
    ("spline_knot_low", 0.10),
    ("spline_knot_mid", 0.50),
    ("spline_knot_high", 0.90),
    ("optimistic_below_days", 40.0),
)
"""La table du § 5.2 du brief, recopiée : les 31 seuils de Q2 et leur défaut."""


def test_the_defaults_of_the_q2_parameters_are_those_of_the_brief() -> None:
    """Correctifs de la PR #52, 3.1 : chaque défaut de ``Q2_PARAMETER_SPECS`` est
    celui de la table du brief, recopiée en dur, et les noms sont dans son ordre.
    Contre un défaut changé (P3a : ``min_residual_df`` à 24 ; P3b :
    ``route_max_gain_ratio`` à 1,11)."""
    assert len(BRIEF_DEFAULTS) == 31
    assert [spec.name for spec in Q2_PARAMETER_SPECS] == [n for n, _ in BRIEF_DEFAULTS]
    for spec, (name, default) in zip(Q2_PARAMETER_SPECS, BRIEF_DEFAULTS, strict=True):
        assert (spec.name, spec.default) == (name, default)


COUNT_PARAMETERS = (
    "min_route_days",
    "normal_window_days",
    "normal_min_admitted_days",
    "min_residual_df",
    "min_estimable_df",
    "secondary_family_size",
    "bootstrap_draws",
    "power_draws",
    "optimistic_below_days",
)
"""Les seuils de comptes du brief dont la plage commence à 1 (``s14_min_months``
commence à 10)."""


@pytest.mark.parametrize("name", COUNT_PARAMETERS)
def test_a_count_parameter_at_one_is_accepted(name: str) -> None:
    """Correctifs de la PR #52, 3.10 : un compte vaut au moins 1 (§ 5.2) ; 1 est
    accepté, et se lit comme l'entier 1. Contre une borne basse posée à 2."""
    from mountain_perf.analyse.normals import integer_parameter

    params = _params(**{name: 1.0})
    assert params[name] == 1.0
    assert integer_parameter(params, name) == 1


EXCLUDED_FLAG_NAMES = (
    "non_human",
    "spike",
    "unresolved_grade",
    "non_barometric",
    "altimetric_drift",
    "gain_outside_moving",
)
"""Les drapeaux exclus du § 5.2 du brief, recopiés."""


@pytest.mark.parametrize("flag", EXCLUDED_FLAG_NAMES)
def test_each_excluded_flag_excludes_its_climb(flag: str) -> None:
    """Correctifs de la PR #52, 3.2 : une montée qui porte un drapeau exclu du brief
    est exclue sous ``drapeau_exclu``. Contre un drapeau retiré de l'ensemble (P3d :
    ``non_human``)."""
    when = at(date(2025, 1, 1), 9)
    tables = q2_tables(
        [q2_activity("f1", when)], [q2_climb("f1", when, flags=[ClimbFlag(flag)])]
    )
    data = _data(tables)
    assert [e.motif.value for e in data.excluded] == ["drapeau_exclu"]
    assert data.days[LONG] == ()


@pytest.mark.parametrize("journal_type", ["maladie", "blessure", "sejour_altitude"])
def test_each_excluding_journal_type_excludes_the_day(journal_type: str) -> None:
    """Correctifs de la PR #52, 3.2 : une journée dont le journal porte un type qui
    exclut un jour (le brief : ``maladie``, ``blessure``, ``sejour_altitude``) a sa
    montée exclue sous ``jour_exclu_du_journal``. Contre un type retiré de l'ensemble
    (P3c : ``sejour_altitude``)."""
    day = date(2025, 1, 10)
    when = at(day, 9)
    rows = [
        *day_range(day - timedelta(days=5), 5),
        q2_day_row(day, journal=[JournalEventType(journal_type)]),
    ]
    tables = q2_tables([q2_activity("j1", when)], [q2_climb("j1", when)], rows)
    data = _data(tables)
    assert [e.motif.value for e in data.excluded] == ["jour_exclu_du_journal"]
    assert data.days[LONG] == ()


def test_the_first_outing_just_after_midnight() -> None:
    """Correctifs de la PR #52, 3.3 (avec C18) : la première activité du jour D part à
    00 h 30 (+02:00 ; sans montée, d'un autre produit), la montée longue à 14 h 00, le
    milieu de la demi-heure la plus basse à 10 h 00 : la première sortie est celle de
    00 h 30, prise au jour local de son départ (Q-47) : ``fc_repos_apres_sortie``. À
    jouer sous ``TZ=UTC`` et ``TZ=Europe/Paris``. Contre le jour de la première sortie
    pris au fuseau de la machine (P3e, sous ``TZ=UTC`` : 00 h 30 +02:00 y est la
    veille)."""
    early = at(MAY_6, 0, 30, tz=PLUS2)
    climb_start = at(MAY_6, 14, tz=PLUS2)
    activities = [q2_activity("c1", climb_start), q2_activity("f0", early, product=9)]
    rows = day_range(MAY_6 - timedelta(days=20), 20, tz=PLUS2)
    rows.append(q2_day_row(MAY_6, midpoint=at(MAY_6, 10, 0, tz=PLUS2), tz=PLUS2))
    tables = q2_tables(activities, [q2_climb("c1", climb_start)], rows)
    (day,) = _data(tables).days[LONG]
    assert day.step5 is Q2Motif.RESTING_AFTER


def test_the_hour_of_a_climb_counts_its_seconds() -> None:
    """Correctifs de la PR #52, 3.10 (Q-49 (c)) : une montée partie à 09 h 30 min
    36 s a une heure de 9,51. Contre des secondes divisées par 3 601 (P3w)."""
    when = at(date(2025, 1, 1), 9, 30)
    tables = q2_tables([q2_activity("s1", when)], [q2_climb("s1", when, offset_s=36)])
    (day,) = _data(tables).days[LONG]
    (climb,) = day.climbs
    assert climb.local_start_time.second == 36
    assert climb.hour == pytest.approx(9.51, rel=1e-12)
