"""Des lignes de ``processed/`` écrites à la main, pour la figure de Q1 (AN1-2c) :
chaque montée, chaque activité et chaque montée de variante a des valeurs inventées,
cohérentes avec ses contrats. Aucune donnée réelle (règle 1)."""

from __future__ import annotations

import dataclasses
from collections.abc import Sequence
from datetime import datetime, timedelta, timezone
from typing import Any

from fixtures.processed import COMMIT
from mountain_perf.analyse.stability import VARIANTS
from mountain_perf.analyse.tables import DEFAULT_DEFINITION, Tables
from mountain_perf.schemas import CENTRAL_CONVENTION_INDEX, Sport
from mountain_perf.schemas.processed import (
    ActivityRow,
    AltitudeStratum,
    ClimbFlag,
    ClimbRegime,
    ClimbRow,
    ClimbVariantRow,
    GradeStratum,
    ProcessedProvenance,
)

PLUS2 = timezone(timedelta(hours=2))
PLUS1 = timezone(timedelta(hours=1))
BASE = datetime(2024, 3, 4, 9, tzinfo=PLUS1)
"""Le départ de la première activité ; les suivantes, une semaine plus tard chacune."""


def start(week: int, hour: int = 9) -> datetime:
    """Le départ local de l'activité de la semaine ``week`` (heure d'hiver)."""
    return (BASE + timedelta(weeks=week)).replace(hour=hour)


def activity(ref: str, when: datetime, **changes: Any) -> ActivityRow:
    """Une activité à pied, enregistrée, avec une vue ; ``climb_count`` et les comptes
    par régime se donnent dans ``changes`` s'ils comptent."""
    row = ActivityRow(
        activity_ref=ref,
        source_activity_type="trail_running",
        sport=Sport.FOOT,
        view_refusal=None,
        start_time=when,
        index_elapsed_s=3600.0,
        index_moving_s=3500.0,
        index_distance_m=10_000.0,
        index_ascent_m=500.0,
        index_descent_m=500.0,
        index_elevation_corrected=False,
        index_average_heart_rate_bpm=140.0,
        index_max_heart_rate_bpm=170.0,
        has_recording=True,
        has_track=True,
        session_count=1,
        track_offset_s=0.0,
        track_elapsed_s=3600.0,
        profile_distance_m=10_000.0,
        profile_ascent_m=480.0,
        profile_descent_m=480.0,
        moving_s_by_convention=(3400.0,) * 5,
        stopped_s_by_convention=(100.0,) * 5,
        undetermined_s_by_convention=(100.0,) * 5,
        step_s=1.0,
        longest_step_s=2.0,
        gap_count=0,
        gap_s=0.0,
        timer_stop_count=0,
        auto_pause_count=0,
        position_gap_ascent_m=0.0,
        loop=False,
        closure_elevation_m=0.0,
        closure_rate_ms=0.0,
        altimetric_drift=False,
        device_manufacturer="garmin",
        device_product=1,
        software_version=1.0,
        barometer=True,
        barometric=True,
        external_heart_rate_sensor=False,
        mean_heart_rate_bpm=140.0,
        heart_rate_coverage=1.0,
        mean_temperature_c=15.0,
        climb_count=0,
        short_climb_count=0,
        intermediate_count=0,
        long_climb_count=0,
        ski_touring_count=0,
        short_ski_touring_count=0,
        other_sport_count=0,
        flagged_climb_count=0,
        unstable_climb_count=0,
    )
    return dataclasses.replace(row, **changes)


TRACK_FIELDS: tuple[str, ...] = (
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
"""Les champs d'une ligne d'activité qui viennent de la vue positions et altitude."""


def without_track() -> dict[str, Any]:
    """Les changements d'une activité enregistrée sans vue positions et altitude."""
    return {"has_track": False, **dict.fromkeys(TRACK_FIELDS)}


def climb(
    ref: str,
    when: datetime,
    start_s: float,
    end_s: float,
    gain_m: float,
    moving_s: float,
    *,
    regime: ClimbRegime = ClimbRegime.LONG_CLIMB,
    grade: GradeStratum = GradeStratum.MODERATE,
    altitude: AltitudeStratum | None = AltitudeStratum.LOW,
    flags: Sequence[ClimbFlag] = (),
    stable: bool | None = True,
    **changes: Any,
) -> ClimbRow:
    """Une montée de ``ref``, de ``start_s`` à ``end_s`` (depuis le départ de
    l'enregistrement), qui prend ``gain_m`` en ``moving_s`` de mouvement sous les cinq
    conventions, sans gain ni temps hors de M ; ``changes`` remplace d'autres
    champs."""
    speed = gain_m / moving_s
    row = ClimbRow(
        activity_ref=ref,
        start_offset_s=start_s,
        end_offset_s=end_s,
        rank=1,
        source_activity_type="trail_running",
        sport=Sport.FOOT,
        local_start_time=when + timedelta(seconds=start_s),
        device_manufacturer="garmin",
        device_product=1,
        software_version=1.0,
        barometric=True,
        profile_start_m=1000.0,
        profile_end_m=3000.0,
        profile_gain_m=gain_m,
        raw_profile_gain_m=gain_m,
        profile_ascent_m=gain_m,
        gain_m=gain_m,
        moving_gain_m_by_convention=(gain_m,) * 5,
        stopped_gain_m_by_convention=(0.0,) * 5,
        undetermined_gain_m_by_convention=(0.0,) * 5,
        gap_gain_m=0.0,
        elapsed_s=end_s - start_s,
        moving_s_by_convention=(moving_s,) * 5,
        stopped_s_by_convention=(0.0,) * 5,
        undetermined_s_by_convention=(0.0,) * 5,
        slow_moving_s=0.0,
        vertical_speed_ms=speed,
        moving_or_undetermined_vertical_speed_ms=speed,
        vertical_speed_low_ms=speed,
        vertical_speed_high_ms=speed,
        moving_distance_m=2000.0,
        grade=gain_m / 2000.0,
        net_displacement_m=1500.0,
        sinuosity=2000.0 / 1500.0,
        low_elevation_m=1000.0,
        high_elevation_m=1000.0 + gain_m,
        moving_mean_elevation_m=1000.0 + gain_m / 2,
        step_s=1.0,
        longest_step_s=2.0,
        gap_count=0,
        gap_s=0.0,
        timer_stop_count=0,
        auto_pause_count=0,
        max_vertical_rate_ms=0.5,
        outside_moving_gain_fraction=0.0,
        slow_moving_fraction=0.0,
        flags=tuple(sorted(flags)),
        found_fraction=1.0 if stable else 0.5,
        max_relative_deviation=0.0 if stable else 0.2,
        stable=stable,
        regime=regime,
        grade_stratum=grade,
        altitude_stratum=altitude,
        preceding_moving_s=start_s,
        preceding_ascent_m=0.0,
        preceding_descent_m=0.0,
        moving_mean_heart_rate_bpm=150.0,
        moving_heart_rate_coverage=1.0,
        second_half_mean_heart_rate_bpm=155.0,
        external_heart_rate_sensor=False,
        moving_mean_temperature_c=15.0,
    )
    return dataclasses.replace(row, **changes)


def variant(
    ref: str,
    name: str,
    start_s: float,
    end_s: float,
    gain_m: float,
    moving_s: float,
    *,
    regime: ClimbRegime = ClimbRegime.LONG_CLIMB,
    grade: GradeStratum = GradeStratum.MODERATE,
    altitude: AltitudeStratum | None = AltitudeStratum.LOW,
    flags: Sequence[ClimbFlag] = (),
    moving_gain_m: float | None = None,
) -> ClimbVariantRow:
    """Une montée de ``ref`` sous la variante ``name`` ; son gain pris en mouvement
    vaut ``gain_m``, sauf si ``moving_gain_m`` le donne."""
    return ClimbVariantRow(
        activity_ref=ref,
        variant=name,
        start_offset_s=start_s,
        end_offset_s=end_s,
        gain_m=gain_m,
        moving_gain_m=gain_m if moving_gain_m is None else moving_gain_m,
        moving_s=moving_s,
        regime=regime,
        grade_stratum=grade,
        altitude_stratum=altitude,
        flags=tuple(sorted(flags)),
    )


def same_in_every_variant(climbs: Sequence[ClimbRow]) -> list[ClimbVariantRow]:
    """Chaque montée de ``climbs``, telle quelle, sous chaque variante : ``G``,
    ``G_M,θc`` et ``M_θc`` de la montée."""
    return [
        variant(
            c.activity_ref,
            v.name,
            c.start_offset_s,
            c.end_offset_s,
            c.gain_m,
            c.moving_s_by_convention[CENTRAL_CONVENTION_INDEX],
            regime=c.regime,
            grade=c.grade_stratum,
            altitude=c.altitude_stratum,
            flags=c.flags,
            moving_gain_m=c.moving_gain_m_by_convention[CENTRAL_CONVENTION_INDEX],
        )
        for v in VARIANTS
        for c in climbs
    ]


def tables_of(
    activities: Sequence[ActivityRow],
    climbs: Sequence[ClimbRow],
    variants: Sequence[ClimbVariantRow] | None = None,
) -> Tables:
    """Les tables de ces lignes ; les variantes sont, par défaut, les montées
    elles-mêmes sous chaque variante."""
    chosen = same_in_every_variant(climbs) if variants is None else list(variants)
    provenance = ProcessedProvenance(
        interim_sha256="0" * 64,
        package_version="0.0.1",
        commit=COMMIT,
        reference_vertical_speed_ms=0.25,
        reference_vertical_speed_declared=False,
        barometer_products=(),
        parameters=DEFAULT_DEFINITION.items(),
        activity_count=len(activities),
        climb_count=len(climbs),
        variant_climb_count=len(chosen),
    )
    return Tables(tuple(activities), tuple(climbs), tuple(chosen), provenance)
