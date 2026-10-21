"""La figure de Q1 (``mountain_perf.analyse.q1``, AN1-2c, ``docs/decisions/0015``),
sur des lignes de ``processed/`` écrites à la main (``tests/fixtures/figure.py``)."""

from __future__ import annotations

import dataclasses
import math
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from fixtures.figure import (
    PLUS2,
    activity,
    climb,
    same_in_every_variant,
    start,
    tables_of,
    variant,
    without_track,
)
from mountain_perf.analyse.q1 import (
    Q1_PANELS,
    Q1_PARAMETER_SPECS,
    FigurePoint,
    PointStability,
    PointStatus,
    Q1Figure,
    View,
    covered_s,
    envelope_ms,
    month_of,
    q1_figure,
    summary_ms,
)
from mountain_perf.analyse.stability import VARIANTS
from mountain_perf.analyse.tables import Tables
from mountain_perf.schemas import CENTRAL_CONVENTION_INDEX, ParameterSet
from mountain_perf.schemas.processed import (
    ActivityRow,
    AltitudeStratum,
    ClimbFlag,
    ClimbRegime,
    ClimbRow,
    ClimbVariantRow,
    GradeStratum,
)

M_PER_H = 3600.0


def params(**changes: float) -> ParameterSet:
    return ParameterSet(Q1_PARAMETER_SPECS, changes)


def five_walks(
    regime: ClimbRegime = ClimbRegime.LONG_CLIMB,
) -> tuple[list[ActivityRow], list[ClimbRow]]:
    """Cinq activités d'une montée chacune, une par semaine : une facette
    affichée."""
    activities = [activity(f"w{i}", start(i)) for i in range(5)]
    climbs = [
        climb(f"w{i}", start(i), 600, 2400, 300, 1800, regime=regime) for i in range(5)
    ]
    return activities, climbs


def main_points(figure: Q1Figure) -> list[FigurePoint]:
    return [p for p in figure.points if p.view is View.MAIN]


# --- le résumé d'un point -------------------------------------------------------


def test_the_summary_is_the_ratio_of_the_sums() -> None:
    """Le cas de l'expert : une montée de 300 m coupée en deux à un arrêt, deux
    moitiés de 150 m montées à 700 et 500 m/h. La moyenne des deux VAM vaut 600 m/h ;
    le rapport des sommes, 583 m/h environ, celui de la montée entière."""
    fast = 150 / (700 / M_PER_H)
    slow = 150 / (500 / M_PER_H)
    halves = [
        climb("a", start(0), 100, 100 + fast, 150, fast),
        climb("a", start(0), 200 + fast, 200 + fast + slow, 150, slow),
    ]
    whole = [climb("a", start(0), 100, 200 + fast + slow, 300, fast + slow)]
    assert summary_ms(halves) == summary_ms(whole) == 300 / (fast + slow)
    assert summary_ms(halves) != pytest.approx(600 / M_PER_H)
    figure = q1_figure(tables_of([activity("a", start(0))], halves))
    (point,) = main_points(figure)
    assert point.climb_count == 2
    assert point.moving_gain_m == 300
    assert point.moving_s == fast + slow
    assert point.vertical_speed_ms == 300 / (fast + slow)


def test_the_summary_without_moving_time() -> None:
    lazy = climb("a", start(0), 100, 200, 30, 60)
    still = dataclasses.replace(lazy, moving_s_by_convention=(0.0,) * 5)
    assert summary_ms([still]) is None


def test_a_moving_time_under_a_second_gives_a_summary() -> None:
    """Le résumé existe dès qu'il y a du temps en M, même moins d'une seconde."""
    lazy = climb("a", start(0), 100, 200, 30, 60)
    brief = dataclasses.replace(
        lazy,
        moving_gain_m_by_convention=(0.25,) * 5,
        moving_s_by_convention=(0.5,) * 5,
    )
    assert summary_ms([brief]) == 0.5


def test_the_envelope_reads_the_ten_values() -> None:
    """Cinq conventions, deux formes : la plus petite et la plus grande des dix
    valeurs, sommées sur les montées du point."""
    c = climb(
        "a",
        start(0),
        100,
        1300,
        300,
        1000,
        moving_gain_m_by_convention=(280.0, 290.0, 300.0, 300.0, 310.0),
        moving_s_by_convention=(1100.0, 1050.0, 1000.0, 1000.0, 950.0),
        undetermined_gain_m_by_convention=(20.0, 10.0, 0.0, 0.0, 0.0),
        undetermined_s_by_convention=(100.0, 150.0, 200.0, 200.0, 250.0),
    )
    values = [
        *(
            g / m
            for g, m in zip(
                c.moving_gain_m_by_convention, c.moving_s_by_convention, strict=True
            )
        ),
        *(
            (g + gu) / (m + u)
            for g, gu, m, u in zip(
                c.moving_gain_m_by_convention,
                c.undetermined_gain_m_by_convention,
                c.moving_s_by_convention,
                c.undetermined_s_by_convention,
                strict=True,
            )
        ),
    ]
    assert envelope_ms([c, c]) == (min(values), max(values))
    assert min(values) == 300 / 1200
    assert max(values) == 310 / 950
    figure = q1_figure(tables_of([activity("a", start(0))], [c]))
    (point,) = main_points(figure)
    assert (point.vertical_speed_low_ms, point.vertical_speed_high_ms) == (
        min(values),
        max(values),
    )


def test_an_envelope_without_any_value() -> None:
    c = climb("a", start(0), 100, 200, 30, 60)
    still = dataclasses.replace(
        c,
        moving_s_by_convention=(0.0,) * 5,
        undetermined_s_by_convention=(0.0,) * 5,
    )
    assert envelope_ms([still]) is None
    (point,) = main_points(q1_figure(tables_of([activity("a", start(0))], [still])))
    assert point.status is PointStatus.NON_POSITIVE
    assert (
        point.vertical_speed_ms,
        point.vertical_speed_low_ms,
        point.vertical_speed_high_ms,
    ) == (None, None, None)


# --- les points et leurs groupes ------------------------------------------------


def test_one_point_per_activity_panel_and_strata() -> None:
    """Une activité, cinq montées : deux longues modérées basses (un point), une
    longue raide basse, une longue modérée moyenne, une côte : quatre points."""
    when = start(0)
    climbs = [
        climb("a", when, 100, 200, 300, 1800),
        climb("a", when, 300, 400, 250, 1500),
        climb("a", when, 500, 600, 300, 1800, grade=GradeStratum.STEEP),
        climb("a", when, 700, 800, 300, 1800, altitude=AltitudeStratum.MID),
        climb("a", when, 900, 1000, 50, 300, regime=ClimbRegime.SHORT_CLIMB),
    ]
    figure = q1_figure(tables_of([activity("a", when)], climbs))
    keys = [
        (p.panel, p.grade_stratum, p.altitude_stratum, p.climb_count)
        for p in main_points(figure)
    ]
    assert keys == [
        (ClimbRegime.LONG_CLIMB, GradeStratum.MODERATE, AltitudeStratum.LOW, 2),
        (ClimbRegime.LONG_CLIMB, GradeStratum.MODERATE, AltitudeStratum.MID, 1),
        (ClimbRegime.LONG_CLIMB, GradeStratum.STEEP, AltitudeStratum.LOW, 1),
        (ClimbRegime.SHORT_CLIMB, GradeStratum.MODERATE, AltitudeStratum.LOW, 1),
    ]


def test_the_points_are_ordered_by_panel_stratum_start_and_activity() -> None:
    later, earlier = start(3), start(1)
    activities = [activity("z", earlier), activity("b", later), activity("c", earlier)]
    climbs = [
        climb("b", later, 100, 200, 300, 1800),
        climb("z", earlier, 100, 200, 300, 1800),
        climb("c", earlier, 100, 200, 300, 1800),
        climb("c", earlier, 300, 400, 300, 1800, regime=ClimbRegime.SKI_TOURING),
        climb("z", earlier, 300, 400, 50, 300, regime=ClimbRegime.SHORT_CLIMB),
    ]
    figure = q1_figure(tables_of(activities, climbs))
    assert [(p.panel, p.activity_ref) for p in main_points(figure)] == [
        (ClimbRegime.LONG_CLIMB, "c"),
        (ClimbRegime.LONG_CLIMB, "z"),
        (ClimbRegime.LONG_CLIMB, "b"),
        (ClimbRegime.SHORT_CLIMB, "z"),
        (ClimbRegime.SKI_TOURING, "c"),
    ]
    assert Q1_PANELS == (
        ClimbRegime.LONG_CLIMB,
        ClimbRegime.SHORT_CLIMB,
        ClimbRegime.SKI_TOURING,
    )


@pytest.mark.parametrize(
    "regime",
    [ClimbRegime.INTERMEDIATE, ClimbRegime.SHORT_SKI_TOURING, ClimbRegime.OTHER_SPORT],
)
def test_the_other_regimes_are_in_no_panel(regime: ClimbRegime) -> None:
    activities, climbs = five_walks(regime)
    figure = q1_figure(tables_of(activities, climbs))
    assert figure.points == ()
    assert all(m.climbs == 0 for m in figure.month_panels)


def test_the_point_carries_the_start_of_its_activity() -> None:
    when = datetime(2024, 7, 1, 6, 30, tzinfo=PLUS2)
    figure = q1_figure(
        tables_of([activity("a", when)], [climb("a", when, 4000, 5000, 300, 900)])
    )
    (point,) = main_points(figure)
    assert point.start_time == when
    assert point.start_time.utcoffset() == timedelta(hours=2)


# --- les exclusions -------------------------------------------------------------


def test_a_flagged_climb_leaves_the_main_view_and_is_counted() -> None:
    when = start(0)
    climbs = [
        climb("a", when, 100, 200, 300, 1800),
        climb(
            "a",
            when,
            300,
            400,
            300,
            600,
            flags=(ClimbFlag.SLOW_MOVING, ClimbFlag.SPIKE),
        ),
        climb("a", when, 500, 600, 300, 600, flags=(ClimbFlag.SPIKE,)),
    ]
    figure = q1_figure(tables_of([activity("a", when)], climbs))
    (point,) = main_points(figure)
    assert point.climb_count == 1
    assert point.vertical_speed_ms == 300 / 1800
    (row,) = [m for m in figure.month_panels if m.panel is ClimbRegime.LONG_CLIMB]
    assert (row.climbs, row.flagged, row.kept) == (3, 2, 1)
    flags = dict(row.flags)
    assert flags[ClimbFlag.SPIKE] == 2
    assert flags[ClimbFlag.SLOW_MOVING] == 1
    assert flags[ClimbFlag.NON_HUMAN] == 0
    assert [f for f, _ in row.flags] == list(ClimbFlag)


def test_an_activity_of_several_sessions_leaves_the_figure() -> None:
    when = start(0)
    activities = [activity("a", when, session_count=2), activity("b", start(1))]
    climbs = [
        climb("a", when, 100, 200, 300, 1800),
        climb("a", when, 300, 400, 300, 1800, flags=(ClimbFlag.SPIKE,)),
        climb("b", start(1), 100, 200, 300, 1800),
    ]
    figure = q1_figure(tables_of(activities, climbs))
    assert [p.activity_ref for p in main_points(figure)] == ["b"]
    rows = [m for m in figure.month_panels if m.panel is ClimbRegime.LONG_CLIMB]
    assert sum(m.multisession for m in rows) == 1
    assert sum(m.flagged for m in rows) == 1
    assert sum(m.kept for m in rows) == 1
    assert [m.multisession for m in figure.month_activities] == [1]


def test_a_climb_without_strata_leaves_the_figure() -> None:
    """Une pente « non résolue » sans drapeau, ou une altitude absente : la montée
    n'a pas de point, et le flux la compte."""
    when = start(0)
    climbs = [
        climb("a", when, 100, 200, 300, 1800, grade=GradeStratum.UNRESOLVED),
        climb("a", when, 300, 400, 300, 1800, altitude=None),
        climb("a", when, 500, 600, 300, 1800),
    ]
    figure = q1_figure(tables_of([activity("a", when)], climbs))
    (point,) = main_points(figure)
    assert point.climb_count == 1
    (row,) = [m for m in figure.month_panels if m.panel is ClimbRegime.LONG_CLIMB]
    assert (row.unstratified, row.kept, row.multisession) == (2, 1, 0)


def test_a_non_positive_summary_is_not_shown() -> None:
    """Un résumé négatif (un gain en M négatif, construit à la main) ne se place pas
    sur un axe logarithmique : le point reste, avec son statut, sans stabilité, et
    ne compte pas dans sa facette."""
    activities, climbs = five_walks()
    sinking = dataclasses.replace(
        climb("w0", start(0), 3000, 3600, 5, 600),
        moving_gain_m_by_convention=(-30.0,) * 5,
        grade_stratum=GradeStratum.STEEP,
    )
    figure = q1_figure(tables_of(activities, [*climbs, sinking]))
    steep = [p for p in main_points(figure) if p.grade_stratum is GradeStratum.STEEP]
    (point,) = steep
    assert point.status is PointStatus.NON_POSITIVE
    assert point.stability is None
    assert point.vertical_speed_ms == -30 / 600
    (row,) = [
        m
        for m in figure.month_panels
        if m.panel is ClimbRegime.LONG_CLIMB and m.points_non_positive
    ]
    assert row.points_non_positive == 1


# --- les facettes ---------------------------------------------------------------


@pytest.mark.parametrize(
    ("count", "status"), [(4, PointStatus.SMALL_FACET), (5, PointStatus.SHOWN)]
)
def test_a_facet_needs_five_activities(count: int, status: PointStatus) -> None:
    activities = [activity(f"w{i}", start(i)) for i in range(count)]
    climbs = [climb(f"w{i}", start(i), 100, 1900, 300, 1800) for i in range(count)]
    figure = q1_figure(tables_of(activities, climbs))
    assert {p.status for p in main_points(figure)} == {status}
    hidden = sum(m.points_hidden for m in figure.month_panels)
    assert hidden == (count if status is PointStatus.SMALL_FACET else 0)


def test_a_facet_counts_distinct_activities() -> None:
    """Quatre activités, dont une a deux points dans la facette (deux strates
    d'altitude) : quatre activités distinctes, sous le minimum de cinq ; avec le
    minimum à quatre, la facette s'affiche."""
    activities = [activity(f"w{i}", start(i)) for i in range(4)]
    climbs = [climb(f"w{i}", start(i), 100, 1900, 300, 1800) for i in range(4)]
    climbs.append(
        climb("w0", start(0), 2000, 3800, 300, 1800, altitude=AltitudeStratum.MID)
    )
    tables = tables_of(activities, climbs)
    assert len(main_points(q1_figure(tables))) == 5
    assert {p.status for p in main_points(q1_figure(tables))} == {
        PointStatus.SMALL_FACET
    }
    assert {
        p.status for p in main_points(q1_figure(tables, params(min_facet_activities=4)))
    } == {PointStatus.SHOWN}


def test_each_facet_counts_its_own_activities() -> None:
    """Cinq activités en pente modérée, une en pente raide : la facette raide ne
    s'affiche pas, la modérée si."""
    activities, climbs = five_walks()
    climbs.append(climb("w0", start(0), 3000, 3600, 100, 600, grade=GradeStratum.STEEP))
    figure = q1_figure(tables_of(activities, climbs))
    by_stratum = {p.grade_stratum: p.status for p in main_points(figure)}
    assert by_stratum == {
        GradeStratum.MODERATE: PointStatus.SHOWN,
        GradeStratum.STEEP: PointStatus.SMALL_FACET,
    }


# --- la vue de sensibilité ------------------------------------------------------


def test_the_stable_only_view_keeps_the_stable_climbs() -> None:
    activities, climbs = five_walks()
    climbs[0] = dataclasses.replace(climbs[0], stable=False)
    climbs[1] = dataclasses.replace(climbs[1], stable=None)
    climbs.append(climb("w2", start(2), 3000, 3600, 100, 300, stable=False))
    figure = q1_figure(tables_of(activities, climbs))
    stable_view = [p for p in figure.points if p.view is View.STABLE_ONLY]
    assert [(p.activity_ref, p.climb_count) for p in stable_view] == [
        ("w2", 1),
        ("w3", 1),
        ("w4", 1),
    ]
    assert all(p.stability is None for p in stable_view)
    assert {p.status for p in stable_view} == {PointStatus.SMALL_FACET}
    rows = [m for m in figure.month_panels if m.panel is ClimbRegime.LONG_CLIMB]
    assert sum(m.kept_unstable for m in rows) == 2
    assert sum(m.stable_only_points for m in rows) == 3
    assert sum(m.stable_only_points_hidden for m in rows) == 3


def test_the_stable_only_view_shows_a_full_facet() -> None:
    activities, climbs = five_walks()
    figure = q1_figure(tables_of(activities, climbs))
    rows = [m for m in figure.month_panels if m.panel is ClimbRegime.LONG_CLIMB]
    assert sum(m.stable_only_points for m in rows) == 5


# --- la stabilité du point ------------------------------------------------------


def _one_walk_tables(variants: list[ClimbVariantRow]) -> Tables:
    when = start(0)
    climbs = [climb("a", when, 1000, 3000, 300, 1800)]
    return tables_of([activity("a", when)], climbs, variants)


def _stability(variants: list[ClimbVariantRow], **changes: float) -> PointStability:
    (point,) = main_points(q1_figure(_one_walk_tables(variants), params(**changes)))
    assert point.stability is not None
    return point.stability


def test_a_point_found_in_every_variant_is_stable() -> None:
    when = start(0)
    climbs = [climb("a", when, 1000, 3000, 300, 1800)]
    s = _stability(same_in_every_variant(climbs))
    assert (
        s.found_fraction,
        s.min_kept_fraction,
        s.max_relative_deviation,
        s.stable,
    ) == (1.0, 1.0, 0.0, True)


def test_a_climb_cut_in_two_by_a_variant_stays_covered() -> None:
    """Une variante qui coupe une montée de 600 m en deux morceaux de 300 m : sous la
    ``V_ref`` des tables (900 m/h), le panneau des montées longues commence à 225 m,
    et les morceaux y restent, avec le même gain et le même temps. La montée reste
    couverte, au trou de 100 s entre les morceaux près, et le résumé ne change pas.
    Un morceau qui sort du panneau : le test suivant, et la chaîne dans
    ``test_analyse_variants.py``."""
    when = start(0)
    climbs = [climb("a", when, 1000, 3000, 600, 1800)]
    variants = [variant("a", v.name, 1000, 3000, 600, 1800) for v in VARIANTS[1:]]
    variants += [
        variant("a", VARIANTS[0].name, 1000, 1900, 300, 900),
        variant("a", VARIANTS[0].name, 2000, 3000, 300, 900),
    ]
    (point,) = main_points(
        q1_figure(tables_of([activity("a", when)], climbs, variants))
    )
    s = point.stability
    assert s is not None
    assert s.min_kept_fraction == pytest.approx(0.95)
    assert s.found_fraction == 1.0
    assert s.max_relative_deviation == 0.0
    assert s.stable is True


@pytest.mark.parametrize(
    "change",
    [
        {"regime": ClimbRegime.INTERMEDIATE},
        {"grade": GradeStratum.STEEP},
        {"altitude": AltitudeStratum.MID},
        {"flags": (ClimbFlag.SPIKE,)},
    ],
    ids=["panneau", "pente", "altitude", "drapeau"],
)
def test_a_climb_that_leaves_its_point_is_not_covered(change: dict[str, Any]) -> None:
    """Sous trois variantes, la montée change de panneau, de strate, ou se marque :
    elle n'y couvre plus le point, qui n'est retrouvé que dans neuf variantes sur
    douze (sous 80 %)."""
    variants = [variant("a", v.name, 1000, 3000, 300, 1800) for v in VARIANTS[3:]]
    variants += [
        variant("a", v.name, 1000, 3000, 300, 1800, **change) for v in VARIANTS[:3]
    ]
    s = _stability(variants)
    assert s.found_fraction == 9 / 12
    assert s.min_kept_fraction == 0.0
    assert s.stable is False


def test_the_kept_gain_weights_each_climb_by_its_gain_and_coverage() -> None:
    """Deux montées dans le point, de 300 m et 100 m ; une variante ne couvre que la
    première moitié de la grande : 150 m sur 400 restent."""
    when = start(0)
    climbs = [
        climb("a", when, 1000, 3000, 300, 1800),
        climb("a", when, 4000, 5000, 100, 600),
    ]
    variants = same_in_every_variant(climbs)
    first = VARIANTS[0].name
    variants = [r for r in variants if r.variant != first]
    variants.append(variant("a", first, 1000, 2000, 150, 900))
    (point,) = main_points(
        q1_figure(tables_of([activity("a", when)], climbs, variants))
    )
    assert point.stability is not None
    assert point.stability.min_kept_fraction == 150 / 400


def test_covered_seconds_of_a_union() -> None:
    assert covered_s(10.0, 20.0, [(0.0, 12.0), (15.0, 18.0), (17.0, 30.0)]) == 7.0
    assert covered_s(10.0, 20.0, [(12.0, 14.0), (11.0, 13.0)]) == 3.0
    assert covered_s(10.0, 20.0, [(0.0, 10.0), (20.0, 30.0)]) == 0.0
    assert covered_s(10.0, 20.0, []) == 0.0


@pytest.mark.parametrize(("threshold", "found"), [(0.5, 1.0), (0.5 + 1e-12, 11 / 12)])
def test_the_kept_threshold_at_equality(threshold: float, found: float) -> None:
    """Sous une variante, la moitié de la montée reste : retrouvée si le seuil vaut
    exactement 0,5, pas au-dessus."""
    variants = [variant("a", v.name, 1000, 3000, 300, 1800) for v in VARIANTS[1:]]
    variants.append(variant("a", VARIANTS[0].name, 1000, 2000, 150, 900))
    s = _stability(variants, min_kept_fraction=threshold)
    assert s.found_fraction == found


@pytest.mark.parametrize(
    ("threshold", "stable"), [(10 / 12, True), (10 / 12 + 1e-12, False)]
)
def test_the_found_threshold_at_equality(threshold: float, stable: bool) -> None:
    variants = [variant("a", v.name, 1000, 3000, 300, 1800) for v in VARIANTS[2:]]
    s = _stability(variants, min_found_fraction=threshold)
    assert s.found_fraction == 10 / 12
    assert s.stable is stable


def test_the_deviation_threshold_at_equality() -> None:
    """Sous une variante, le résumé change de 1800 à 1700 s : l'écart vaut
    ``|(300 / 1700) / (300 / 1800) − 1|`` ; stable sous un seuil plus grand, pas à
    l'égalité."""
    variants = [variant("a", v.name, 1000, 3000, 300, 1800) for v in VARIANTS[1:]]
    variants.append(variant("a", VARIANTS[0].name, 1000, 3000, 300, 1700))
    deviation = abs((300 / 1700) / (300 / 1800) - 1)
    assert (
        _stability(variants, max_relative_deviation=deviation).max_relative_deviation
        == deviation
    )
    assert _stability(variants, max_relative_deviation=deviation).stable is False
    assert _stability(variants, max_relative_deviation=deviation + 1e-12).stable is True


def test_the_variant_summary_reads_all_its_climbs_of_the_point() -> None:
    """Sous une variante, une seconde montée apparaît dans le même panneau et les mêmes
    strates, sans recouvrir la montée de référence : elle entre dans le résumé de la
    variante (le point tel qu'il serait dessiné), pas dans le gain qui reste."""
    variants = [variant("a", v.name, 1000, 3000, 300, 1800) for v in VARIANTS[1:]]
    first = VARIANTS[0].name
    variants += [
        variant("a", first, 1000, 3000, 300, 1800),
        variant("a", first, 4000, 4600, 100, 300),
    ]
    s = _stability(variants)
    assert s.min_kept_fraction == 1.0
    assert s.max_relative_deviation == pytest.approx((400 / 2100) / (300 / 1800) - 1)


def test_a_variant_of_another_activity_does_not_count() -> None:
    when = start(0)
    climbs = [climb("a", when, 1000, 3000, 300, 1800)]
    variants = [variant("b", v.name, 1000, 3000, 300, 1800) for v in VARIANTS]
    activities = [activity("a", when), activity("b", start(1))]
    (point,) = main_points(q1_figure(tables_of(activities, climbs, variants)))
    s = point.stability
    assert s is not None
    assert (s.found_fraction, s.max_relative_deviation, s.stable) == (0.0, None, False)


def test_hidden_points_have_their_stability() -> None:
    """La stabilité se calcule pour tout point de la vue principale au résumé
    positif, facette affichée ou non."""
    (point,) = main_points(
        q1_figure(
            _one_walk_tables(
                same_in_every_variant([climb("a", start(0), 1000, 3000, 300, 1800)])
            )
        )
    )
    assert point.status is PointStatus.SMALL_FACET
    assert point.stability is not None


def test_unstable_shown_points_in_the_flux() -> None:
    activities, climbs = five_walks()
    variants = [r for r in same_in_every_variant(climbs) if r.activity_ref != "w0"]
    figure = q1_figure(tables_of(activities, climbs, variants))
    rows = [m for m in figure.month_panels if m.panel is ClimbRegime.LONG_CLIMB]
    assert sum(m.points_unstable for m in rows) == 1
    assert sum(m.points for m in rows) == 5


# --- le flux, la période, les appareils, les axes ------------------------------


def test_the_months_are_local_and_continuous() -> None:
    """Une activité le 31 mars, une autre en mai : avril figure, vide ; les mois vont
    du premier au dernier, sans trou (le mois local d'une activité dont la date UTC
    est la veille : ``test_a_month_is_read_on_the_local_date``)."""
    late = datetime(2024, 3, 31, 23, 30, tzinfo=PLUS2)
    may = datetime(2024, 5, 2, 9, tzinfo=PLUS2)
    activities = [
        activity("a", late),
        activity("b", may, has_track=False, has_recording=False, **_no_recording()),
    ]
    figure = q1_figure(tables_of(activities, [climb("a", late, 100, 1900, 300, 1800)]))
    assert month_of(late) == "2024-03"
    assert [(m.month, m.activities, m.with_track) for m in figure.month_activities] == [
        ("2024-03", 1, 1),
        ("2024-04", 0, 0),
        ("2024-05", 1, 0),
    ]
    assert [m.month for m in figure.month_panels] == [
        "2024-03",
        "2024-04",
        "2024-05",
    ] * 3
    assert [m.panel for m in figure.month_panels] == [
        panel for panel in Q1_PANELS for _ in range(3)
    ]
    assert figure.period == (late, may)


def test_a_year_boundary_in_the_months() -> None:
    december = datetime(2023, 12, 20, 9, tzinfo=PLUS2)
    february = datetime(2024, 2, 1, 9, tzinfo=PLUS2)
    figure = q1_figure(
        tables_of([activity("a", december), activity("b", february)], [])
    )
    assert [m.month for m in figure.month_activities] == [
        "2023-12",
        "2024-01",
        "2024-02",
    ]


def _no_recording() -> dict[str, None]:
    return {
        name: None
        for name in (
            "session_count",
            "device_manufacturer",
            "device_product",
            "software_version",
            "barometer",
            "external_heart_rate_sensor",
            "mean_temperature_c",
            "track_offset_s",
            "track_elapsed_s",
            "profile_distance_m",
            "profile_ascent_m",
            "profile_descent_m",
            "moving_s_by_convention",
            "stopped_s_by_convention",
            "undetermined_s_by_convention",
            "step_s",
            "longest_step_s",
            "gap_count",
            "gap_s",
            "timer_stop_count",
            "auto_pause_count",
            "position_gap_ascent_m",
            "loop",
            "closure_elevation_m",
            "closure_rate_ms",
            "altimetric_drift",
            "barometric",
            "mean_heart_rate_bpm",
            "heart_rate_coverage",
        )
    }


def test_no_activity_no_period() -> None:
    figure = q1_figure(tables_of([], []))
    assert figure.period is None
    assert figure.month_activities == ()
    assert figure.month_panels == ()
    assert figure.points == ()
    assert figure.vertical_speed_range_ms == tuple((p, None) for p in Q1_PANELS)


def test_the_device_changes() -> None:
    """Produits 1, 1, 2, (aucun : pas d'enregistrement), (inconnus), 1 : deux
    changements, vers 2 puis vers 1."""
    activities = [
        activity("a", start(0)),
        activity("b", start(1)),
        activity("c", start(2), device_product=2),
        activity(
            "d", start(3), has_track=False, has_recording=False, **_no_recording()
        ),
        activity("e", start(4), device_manufacturer=None, device_product=None),
        activity("f", start(5)),
    ]
    figure = q1_figure(tables_of(activities, []))
    assert [(c.start_time, c.product) for c in figure.device_changes] == [
        (start(2), 2),
        (start(5), 1),
    ]


def test_a_device_change_reads_the_manufacturer_too() -> None:
    activities = [
        activity("a", start(0)),
        activity("b", start(1), device_manufacturer="coros"),
    ]
    (change,) = q1_figure(tables_of(activities, [])).device_changes
    assert (change.manufacturer, change.product) == ("coros", 1)


def test_the_device_changes_follow_the_time_not_the_index() -> None:
    activities = [activity("b", start(1), device_product=2), activity("a", start(0))]
    (change,) = q1_figure(tables_of(activities, [])).device_changes
    assert change.start_time == start(1)


def test_the_vertical_speed_range_of_a_panel() -> None:
    """L'étendue d'un panneau : les résumés des points montrés des deux vues, et
    eux seuls (un point d'une facette cachée n'y entre pas)."""
    activities, climbs = five_walks()
    climbs[3] = climb("w3", start(3), 600, 2400, 360, 1800)
    climbs.append(climb("w0", start(0), 3000, 3600, 900, 600, grade=GradeStratum.STEEP))
    figure = q1_figure(tables_of(activities, climbs))
    ranges = dict(figure.vertical_speed_range_ms)
    assert ranges[ClimbRegime.LONG_CLIMB] == (300 / 1800, 360 / 1800)
    assert ranges[ClimbRegime.SHORT_CLIMB] is None


def test_the_vertical_speed_range_reads_both_views() -> None:
    """Le point le plus rapide d'un panneau n'est que dans la vue de sensibilité
    (``w0`` y perd sa montée lente, instable) : l'étendue du panneau va jusqu'à
    lui."""
    activities = [activity(f"w{i}", start(i)) for i in range(5)]
    climbs = [climb(f"w{i}", start(i), 600, 2400, 300, 1800) for i in range(1, 5)]
    climbs += [
        climb("w0", start(0), 600, 1200, 900, 600),
        climb("w0", start(0), 1300, 3100, 100, 1800, stable=False),
    ]
    figure = q1_figure(tables_of(activities, climbs))
    main = [p for p in main_points(figure) if p.activity_ref == "w0"]
    assert [p.vertical_speed_ms for p in main] == [1000 / 2400]
    ranges = dict(figure.vertical_speed_range_ms)
    assert ranges[ClimbRegime.LONG_CLIMB] == (300 / 1800, 900 / 600)


def test_the_kept_gain_reads_the_moving_gain_not_g() -> None:
    """La part qui reste pèse le gain pris en mouvement, pas ``G`` : la montée que
    chaque variante retrouve a ``G`` = 400 m mais ``G_M,θc`` = 200 m, l'autre 100 m
    des deux. 200 m sur 300 restent : le point n'est retrouvé dans aucune variante
    (avec ``G``, 400 sur 500 le retrouveraient dans toutes)."""
    when = start(0)
    climbs = [
        climb(
            "a", when, 1000, 3000, 400, 1800, moving_gain_m_by_convention=(200.0,) * 5
        ),
        climb("a", when, 4000, 5000, 100, 600),
    ]
    variants = [
        variant("a", v.name, 1000, 3000, 400, 1800, moving_gain_m=200.0)
        for v in VARIANTS
    ]
    (point,) = main_points(
        q1_figure(tables_of([activity("a", when)], climbs, variants))
    )
    assert point.stability is not None
    assert point.stability.min_kept_fraction == 200 / 300
    assert point.stability.found_fraction == 0.0


def test_the_figure_keeps_its_provenance_and_parameters() -> None:
    activities, climbs = five_walks()
    tables = tables_of(activities, climbs)
    figure = q1_figure(tables, params(min_facet_activities=3))
    assert figure.provenance == tables.provenance
    assert figure.parameters["min_facet_activities"] == 3
    assert q1_figure(tables).parameters == ParameterSet(Q1_PARAMETER_SPECS)


def test_the_declared_defaults() -> None:
    defaults = dict(ParameterSet(Q1_PARAMETER_SPECS).values)
    assert defaults == {
        "min_facet_activities": 5.0,
        "min_kept_fraction": 0.8,
        "min_found_fraction": 0.8,
        "max_relative_deviation": 0.05,
    }


def test_the_figure_does_not_change_its_tables() -> None:
    activities, climbs = five_walks()
    tables = tables_of(activities, climbs)
    before = dataclasses.replace(tables)
    q1_figure(tables)
    assert tables == before
    assert not math.isnan(tables.climbs[0].gain_m)


# --- les relectures du prototype (AN1-2c) ----------------------------------------


def test_the_summary_reads_the_central_convention() -> None:
    """Cinq conventions aux valeurs toutes différentes : le résumé, ``Σ G_M`` et
    ``Σ M`` du point sont ceux de θc, la convention centrale."""
    gains = (280.0, 290.0, 300.0, 305.0, 310.0)
    times = (1100.0, 1050.0, 1000.0, 990.0, 950.0)
    c = climb(
        "a",
        start(0),
        100,
        1300,
        300,
        1000,
        moving_gain_m_by_convention=gains,
        moving_s_by_convention=times,
    )
    (point,) = main_points(q1_figure(tables_of([activity("a", start(0))], [c])))
    k = CENTRAL_CONVENTION_INDEX
    assert (point.moving_gain_m, point.moving_s) == (gains[k], times[k])
    assert point.vertical_speed_ms == gains[k] / times[k]
    assert len({g / m for g, m in zip(gains, times, strict=True)}) == 5


def test_the_variant_summary_reads_the_moving_gain_not_g() -> None:
    """Sous chaque variante, le résumé est ``Σ G_M,θc / Σ M_θc`` de ses montées : un
    ``G`` doublé n'y change rien, et le point reste stable, sans écart."""
    climbs = [climb("a", start(0), 1000, 3000, 300, 1800)]
    rows = [dataclasses.replace(r, gain_m=600.0) for r in same_in_every_variant(climbs)]
    (point,) = main_points(
        q1_figure(tables_of([activity("a", start(0))], climbs, rows))
    )
    assert point.stability is not None
    assert point.stability.max_relative_deviation == 0.0
    assert point.stability.stable is True


def test_a_month_is_read_on_the_local_date() -> None:
    """Le 1er avril à 1 h 30, heure d'été (le 31 mars à 23 h 30 en UTC) : avril."""
    early = datetime(2024, 4, 1, 1, 30, tzinfo=PLUS2)
    assert month_of(early) == "2024-04"
    figure = q1_figure(tables_of([activity("a", early)], []))
    assert [m.month for m in figure.month_activities] == ["2024-04"]


def test_the_period_and_the_months_read_the_wall_clock() -> None:
    """Le premier instant (le 1er avril à 0 h 30, à +02:00) est le dernier départ en
    heure murale, le dernier instant (le 31 mars à 23 h, à +00:00) le premier : la
    période va du 31 mars, 23 h, au 1er avril, 0 h 30, et le flux compte les deux
    activités, en mars et en avril."""
    first = datetime(2024, 4, 1, 0, 30, tzinfo=PLUS2)
    last = datetime(2024, 3, 31, 23, 0, tzinfo=UTC)
    assert first < last
    figure = q1_figure(tables_of([activity("a", first), activity("b", last)], []))
    assert figure.period == (last, first)
    assert [(m.month, m.activities) for m in figure.month_activities] == [
        ("2024-03", 1),
        ("2024-04", 1),
    ]


@pytest.mark.parametrize("gain_m", [-30.0, 0.0])
def test_a_non_positive_point_does_not_count_in_its_facet(gain_m: float) -> None:
    """Quatre activités au résumé positif et une au résumé négatif, ou nul, dans la
    même facette : la facette compte quatre activités, sous le minimum."""
    activities = [activity(f"w{i}", start(i)) for i in range(5)]
    climbs = [climb(f"w{i}", start(i), 100, 1900, 300, 1800) for i in range(4)]
    climbs.append(
        dataclasses.replace(
            climb("w4", start(4), 100, 1900, 5, 600),
            moving_gain_m_by_convention=(gain_m,) * 5,
        )
    )
    statuses = [p.status for p in main_points(q1_figure(tables_of(activities, climbs)))]
    assert statuses == [PointStatus.SMALL_FACET] * 4 + [PointStatus.NON_POSITIVE]


def test_in_a_facet_the_start_comes_before_the_altitude() -> None:
    """Dans une facette, les points vont par départ de l'activité, puis par strate
    d'altitude : une activité plus tôt, en altitude moyenne, passe avant une plus
    tardive, en altitude basse."""
    activities = [activity("a", start(0)), activity("b", start(1))]
    climbs = [
        climb("a", start(0), 100, 1900, 300, 1800, altitude=AltitudeStratum.MID),
        climb("b", start(1), 100, 1900, 300, 1800, altitude=AltitudeStratum.LOW),
    ]
    points = main_points(q1_figure(tables_of(activities, climbs)))
    assert [p.activity_ref for p in points] == ["a", "b"]


def test_the_deviation_is_read_where_the_point_is_found_only() -> None:
    """Sous une variante, la moitié du gain seulement reste, à une VAM triple : le
    point n'y est pas retrouvé, et ce résumé n'entre pas dans l'écart."""
    variants = [variant("a", v.name, 1000, 3000, 300, 1800) for v in VARIANTS[1:]]
    variants.append(variant("a", VARIANTS[0].name, 1000, 2000, 150, 300))
    s = _stability(variants)
    assert s.found_fraction == 11 / 12
    assert s.max_relative_deviation == 0.0
    assert s.stable is True


def test_a_variant_that_finds_the_point_without_moving_time() -> None:
    """Comme pour la montée : une variante qui couvre tout le point sans temps en M le
    retrouve, mais son résumé, qui n'existe pas, n'entre pas dans l'écart."""
    variants = [variant("a", v.name, 1000, 3000, 300, 1800) for v in VARIANTS[1:]]
    variants.append(variant("a", VARIANTS[0].name, 1000, 3000, 300, 0))
    s = _stability(variants)
    assert (s.found_fraction, s.min_kept_fraction) == (1.0, 1.0)
    assert s.max_relative_deviation == 0.0
    assert s.stable is True


def test_with_track_reads_the_track_not_the_recording() -> None:
    """Une activité enregistrée sans vue positions et altitude : comptée parmi les
    activités, pas parmi celles qui ont une vue."""
    figure = q1_figure(tables_of([activity("a", start(0), **without_track())], []))
    (month,) = figure.month_activities
    assert (month.activities, month.with_track) == (1, 0)


def test_a_hidden_unstable_point_is_not_counted_unstable() -> None:
    """``points_unstable`` compte les points montrés et instables : un point caché
    instable n'y entre pas."""
    climbs = [climb("a", start(0), 1000, 3000, 300, 1800)]
    figure = q1_figure(tables_of([activity("a", start(0))], climbs, []))
    (point,) = main_points(figure)
    assert point.status is PointStatus.SMALL_FACET
    assert point.stability is not None
    assert point.stability.stable is False
    assert sum(m.points_unstable for m in figure.month_panels) == 0


def test_an_unknown_product_is_not_a_device_change() -> None:
    """Une activité dont le produit manque ne dit pas son appareil : produits 1,
    inconnu, 1, aucun changement."""
    activities = [
        activity("a", start(0)),
        activity("b", start(1), device_product=None),
        activity("c", start(2)),
    ]
    assert q1_figure(tables_of(activities, [])).device_changes == ()


def test_the_flux_of_the_stable_only_view() -> None:
    """Cinq activités, la montée de ``w0`` instable, et une montée raide de ``w1`` au
    résumé négatif : la vue de sensibilité a cinq points, dont quatre dans une facette
    sous le minimum et un au résumé non positif ; le point de ``w0`` n'y est pas."""
    activities, climbs = five_walks()
    climbs[0] = dataclasses.replace(climbs[0], stable=False)
    climbs.append(
        dataclasses.replace(
            climb("w1", start(1), 3000, 3600, 5, 600, grade=GradeStratum.STEEP),
            moving_gain_m_by_convention=(-30.0,) * 5,
        )
    )
    figure = q1_figure(tables_of(activities, climbs))
    rows = [m for m in figure.month_panels if m.panel is ClimbRegime.LONG_CLIMB]
    totals = {
        name: sum(getattr(m, name) for m in rows)
        for name in (
            "points",
            "points_hidden",
            "points_non_positive",
            "stable_only_points",
            "stable_only_points_hidden",
            "stable_only_points_non_positive",
        )
    }
    assert totals == {
        "points": 6,
        "points_hidden": 0,
        "points_non_positive": 1,
        "stable_only_points": 5,
        "stable_only_points_hidden": 4,
        "stable_only_points_non_positive": 1,
    }
