"""De ``interim/`` aux lignes des tables ``activites`` et ``montees`` (AN1-2b,
``docs/decisions/0014``).

Pour chaque entrée de l'index, dans l'ordre de l'index : sa vue ``Activity`` (ou le
motif de son refus), son enregistrement s'il existe, la vue positions et altitude
(:func:`~mountain_perf.analyse.climbs.motion_track`), les montées retenues et leurs
mesures, leur stabilité sous les variantes déclarées, leurs drapeaux, leur régime et
leurs strates.

Les instants des enregistrements partent du départ de l'enregistrement ; ceux d'une
:class:`~mountain_perf.analyse.climbs.MotionTrack`, du premier instant de sa vue
(``offset_s`` plus tard). La FC et la température d'un intervalle de la vue se lisent
à son instant de départ, quand le canal a une valeur **au même instant** de
l'enregistrement (égalité exacte, comme la vue) ; le D+ d'un trou de la vue, sur tous
les échantillons du canal d'altitude entre ses deux instants ; la température moyenne
d'une activité, sur tout son canal.

Une erreur de contrat sur une activité, ou un document d'``interim/`` qui ne se relit
pas, arrête le calcul et nomme l'activité, ou l'index (:class:`TablesError`) : le
message reste dans le terminal de l'athlète.

Python pur : ce module ne demande aucun extra ; l'écriture en Parquet est dans
``mountain_perf.analyse.parquet``.
"""

from __future__ import annotations

import hashlib
import math
from bisect import bisect_left, bisect_right
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path
from statistics import median

from mountain_perf import __version__
from mountain_perf.analyse.athlete import AthleteSettings
from mountain_perf.analyse.climbs import (
    CLIMB_PARAMETER_SPECS,
    ClimbMeasure,
    MotionTrack,
    climbs,
    interpolate,
    motion_track,
    state_time_s,
    track_route,
)
from mountain_perf.analyse.quality import (
    QUALITY_PARAMETER_SPECS,
    REGIME_PARAMETER_SPECS,
    altimetric_drift,
    altitude_stratum,
    climb_flags,
    grade_stratum,
    regime,
)
from mountain_perf.analyse.stability import (
    STABILITY_PARAMETER_SPECS,
    stability,
    variant_climbs,
)
from mountain_perf.codec import CodecError
from mountain_perf.gpx.geo import deduplicated_polyline, haversine_m
from mountain_perf.gpx.profile import (
    PROFILE_PARAMETER_SPECS,
    build_profile_with_diagnostics,
)
from mountain_perf.ingest.interim import (
    ACTIVITIES_DIR,
    read_index,
    read_recording,
)
from mountain_perf.ingest.types import SOURCE_TYPE_SPORTS
from mountain_perf.ingest.views import activity_view
from mountain_perf.schemas import (
    CENTRAL_CONVENTION_INDEX,
    CLOCK_CONVENTIONS,
    ActivityRecording,
    IndexedActivity,
    IntervalState,
    ParameterSet,
    RouteProfile,
    TimerEventType,
    TimerTrigger,
    ViewRefusal,
)
from mountain_perf.schemas.processed import (
    ActivityRow,
    ClimbRegime,
    ClimbRow,
    ProcessedProvenance,
)
from mountain_perf.validation import ContractError

_STOPS = frozenset(t for t in TimerEventType if t is not TimerEventType.START)


class TablesError(ValueError):
    """Les lignes d'une activité violent un contrat, ou un document d'``interim/`` ne
    se relit pas : le message nomme l'activité (son identifiant dans l'index de
    l'export), ou l'index, et la cause."""


@dataclass(frozen=True)
class Definition:
    """Les paramètres de la définition : profil, montée, drapeaux, régimes,
    stabilité."""

    profile: ParameterSet
    climb: ParameterSet
    quality: ParameterSet
    regimes: ParameterSet
    stability: ParameterSet

    def items(self) -> tuple[tuple[str, float], ...]:
        """Tous les paramètres, ``famille.nom``, triés."""
        out = []
        for family, values in (
            ("climb", self.climb),
            ("profile", self.profile),
            ("quality", self.quality),
            ("regimes", self.regimes),
            ("stability", self.stability),
        ):
            out += [(f"{family}.{name}", float(v)) for name, v in values.values.items()]
        return tuple(sorted(out))


DEFAULT_DEFINITION = Definition(
    ParameterSet(PROFILE_PARAMETER_SPECS),
    ParameterSet(CLIMB_PARAMETER_SPECS),
    ParameterSet(QUALITY_PARAMETER_SPECS),
    ParameterSet(REGIME_PARAMETER_SPECS),
    ParameterSet(STABILITY_PARAMETER_SPECS),
)
"""La définition par défaut, celle de ``docs/decisions/0014``."""


@dataclass(frozen=True)
class Tables:
    """Les deux tables et leur provenance."""

    activities: tuple[ActivityRow, ...]
    climbs: tuple[ClimbRow, ...]
    provenance: ProcessedProvenance


def interim_sha256(data_dir: Path) -> str:
    """Empreinte d'``interim/activities/`` : SHA-256 des lignes ``chemin relatif``,
    tabulation, ``SHA-256 du document``, triées par chemin, terminées par un saut de
    ligne. Seuls les documents comptent (``*.json``) : un fichier qu'un explorateur de
    fichiers dépose (``.DS_Store``, ``Thumbs.db``) ne la change pas."""
    root = data_dir / ACTIVITIES_DIR
    lines = sorted(
        f"{path.relative_to(root).as_posix()}\t"
        f"{hashlib.sha256(path.read_bytes()).hexdigest()}\n"
        for path in root.rglob("*.json")
        if path.is_file()
    )
    return hashlib.sha256("".join(lines).encode("utf-8")).hexdigest()


def _intervals(track: MotionTrack, start_s: float, end_s: float) -> range:
    """Les intervalles de la vue qui recoupent ``[start_s ; end_s]``."""
    t = track.time_s
    first = max(bisect_right(t, start_s) - 1, 0)
    last = min(bisect_left(t, end_s), len(t) - 1)
    return range(first, last)


def _gaps(track: MotionTrack, start_s: float, end_s: float) -> tuple[int, float]:
    t = track.time_s
    count, total = 0, 0.0
    for i in _intervals(track, start_s, end_s):
        if track.gap_after[i]:
            count += 1
            total += min(t[i + 1], end_s) - max(t[i], start_s)
    return count, total


def _timer_stops(
    recording: ActivityRecording, start_s: float, end_s: float
) -> tuple[int, int]:
    """Arrêts du chronomètre dans ``[start_s ; end_s]`` (instants de
    l'enregistrement), dont ceux de la pause automatique."""
    stops = [
        e
        for e in recording.timer_events
        if e.event_type in _STOPS and start_s <= e.time_s <= end_s
    ]
    return len(stops), sum(1 for e in stops if e.trigger is TimerTrigger.AUTO)


def _channel(
    times: Sequence[float] | None, values: Sequence[float] | None
) -> dict[float, float]:
    if times is None or values is None:
        return {}
    return dict(zip(times, values, strict=True))


def _moving_mean(
    track: MotionTrack,
    channel: dict[float, float],
    start_s: float,
    end_s: float,
    *,
    second_half: bool = False,
) -> tuple[float | None, float]:
    """Moyenne d'un canal sur les intervalles M (θc) de ``[start_s ; end_s]`` qui ont
    une valeur à leur instant de départ, pondérée par la durée de l'intervalle dans la
    fenêtre ; et la part du temps M couverte. ``second_half`` : seulement après la
    moitié du temps M de la fenêtre."""
    t = track.time_s
    at = track.recording_time_s
    marks = track.states[CENTRAL_CONVENTION_INDEX]
    pieces: list[tuple[float, int]] = []
    for i in _intervals(track, start_s, end_s):
        if marks[i] is IntervalState.MOVING:
            duration = min(t[i + 1], end_s) - max(t[i], start_s)
            if duration > 0:
                pieces.append((duration, i))
    total = math.fsum(d for d, _ in pieces)
    if second_half:
        half, run, kept = total / 2, 0.0, []
        for duration, i in pieces:
            if run >= half:
                kept.append((duration, i))
            run += duration
        pieces = kept
        total = math.fsum(d for d, _ in pieces)
    weighted = [(d, channel[at[i]]) for d, i in pieces if at[i] in channel]
    covered = math.fsum(d for d, _ in weighted)
    coverage = covered / total if total > 0 else 0.0
    if covered <= 0:
        return None, coverage
    return math.fsum(d * v for d, v in weighted) / covered, coverage


def _climb_row(
    entry: IndexedActivity,
    recording: ActivityRecording,
    track: MotionTrack,
    profile: RouteProfile,
    measure: ClimbMeasure,
    rank: int,
    variants: Sequence[Sequence[ClimbMeasure]],
    *,
    barometric: bool,
    drift: bool,
    settings: AthleteSettings,
    definition: Definition,
) -> ClimbRow:
    span = measure.span
    offset = track.offset_s
    sport = SOURCE_TYPE_SPORTS.get(entry.source_activity_type)
    flags = climb_flags(
        measure,
        sport,
        barometric=barometric,
        altimetric_drift=drift,
        climb=definition.climb,
        quality=definition.quality,
    )
    stab = stability(measure, variants, definition.stability)
    envelope = measure.vertical_speed_envelope_ms
    gap_count, gap_s = _gaps(track, span.start_s, span.end_s)
    stops, autos = _timer_stops(recording, span.start_s + offset, span.end_s + offset)
    hr = _channel(
        None if recording.heart_rate is None else recording.heart_rate.time_s,
        None if recording.heart_rate is None else recording.heart_rate.heart_rate_bpm,
    )
    temperature = _channel(
        None if recording.temperature is None else recording.temperature.time_s,
        None if recording.temperature is None else recording.temperature.temperature_c,
    )
    mean_hr, coverage = _moving_mean(track, hr, span.start_s, span.end_s)
    half_hr, _ = _moving_mean(track, hr, span.start_s, span.end_s, second_half=True)
    mean_temperature, _ = _moving_mean(track, temperature, span.start_s, span.end_s)
    ascent, descent = profile.cumulative_ascent_m, profile.cumulative_descent_m
    device = recording.device
    local = (
        recording.start_time + timedelta(seconds=offset + span.start_s)
    ).astimezone(entry.start_time.tzinfo)
    return ClimbRow(
        activity_ref=entry.activity_ref,
        start_offset_s=offset + span.start_s,
        end_offset_s=offset + span.end_s,
        rank=rank,
        source_activity_type=entry.source_activity_type,
        sport=sport,
        local_start_time=local,
        device_manufacturer=device.manufacturer,
        device_product=device.product,
        software_version=device.software_version,
        barometric=barometric,
        profile_start_m=span.profile_start_m,
        profile_end_m=span.profile_end_m,
        profile_gain_m=span.profile_gain_m,
        raw_profile_gain_m=span.raw_profile_gain_m,
        profile_ascent_m=span.profile_ascent_m,
        gain_m=span.gain_m,
        moving_gain_m_by_convention=measure.moving_gain_m,
        stopped_gain_m_by_convention=measure.stopped_gain_m,
        undetermined_gain_m_by_convention=measure.undetermined_gain_m,
        gap_gain_m=measure.gap_gain_m,
        elapsed_s=measure.elapsed_s,
        moving_s_by_convention=measure.moving_s,
        stopped_s_by_convention=measure.stopped_s,
        undetermined_s_by_convention=measure.undetermined_s,
        slow_moving_s=measure.slow_moving_s,
        vertical_speed_ms=measure.vertical_speed_ms,
        moving_or_undetermined_vertical_speed_ms=(
            measure.moving_or_undetermined_vertical_speed_ms
        ),
        vertical_speed_low_ms=None if envelope is None else envelope[0],
        vertical_speed_high_ms=None if envelope is None else envelope[1],
        moving_distance_m=measure.moving_distance_m,
        grade=measure.grade,
        net_displacement_m=measure.net_displacement_m,
        sinuosity=measure.sinuosity,
        low_elevation_m=measure.low_elevation_m,
        high_elevation_m=measure.high_elevation_m,
        moving_mean_elevation_m=measure.moving_mean_elevation_m,
        step_s=measure.step_s,
        longest_step_s=measure.longest_step_s,
        gap_count=gap_count,
        gap_s=gap_s,
        timer_stop_count=stops,
        auto_pause_count=autos,
        max_vertical_rate_ms=measure.max_vertical_rate_ms,
        outside_moving_gain_fraction=measure.outside_moving_gain_fraction,
        slow_moving_fraction=measure.slow_moving_fraction,
        flags=tuple(sorted(flags)),
        found_fraction=stab.found_fraction,
        max_relative_deviation=stab.max_relative_deviation,
        stable=stab.stable,
        regime=regime(
            span.gain_m,
            sport,
            settings.reference_vertical_speed_ms,
            definition.regimes,
        ),
        grade_stratum=grade_stratum(
            measure, definition.climb, definition.regimes, definition.quality
        ),
        altitude_stratum=altitude_stratum(measure, definition.regimes),
        preceding_moving_s=state_time_s(
            track, CENTRAL_CONVENTION_INDEX, IntervalState.MOVING, 0.0, span.start_s
        ),
        preceding_ascent_m=interpolate(
            profile.distance_m, ascent, span.profile_start_m
        ),
        preceding_descent_m=interpolate(
            profile.distance_m, descent, span.profile_start_m
        ),
        moving_mean_heart_rate_bpm=mean_hr,
        moving_heart_rate_coverage=coverage,
        second_half_mean_heart_rate_bpm=half_hr,
        external_heart_rate_sensor=device.external_heart_rate_sensor,
        moving_mean_temperature_c=mean_temperature,
    )


def _position_gap_ascent_m(recording: ActivityRecording, track: MotionTrack) -> float:
    """D+ du canal d'altitude entre les deux instants de chaque trou de la vue."""
    channel = recording.elevation
    if channel is None:
        return 0.0
    times, values = channel.time_s, channel.elevation_m
    at = track.recording_time_s
    total = 0.0
    for i, gap in enumerate(track.gap_after):
        if not gap:
            continue
        lo = bisect_left(times, at[i])
        hi = bisect_right(times, at[i + 1])
        total += math.fsum(
            max(0.0, values[j + 1] - values[j]) for j in range(lo, hi - 1)
        )
    return total


@dataclass(frozen=True)
class _TrackSummary:
    """Ce que la vue positions et altitude d'une activité donne à sa ligne."""

    track_offset_s: float
    track_elapsed_s: float
    profile_distance_m: float
    profile_ascent_m: float
    profile_descent_m: float
    moving_s_by_convention: tuple[float, ...]
    stopped_s_by_convention: tuple[float, ...]
    undetermined_s_by_convention: tuple[float, ...]
    step_s: float
    longest_step_s: float
    gap_count: int
    gap_s: float
    timer_stop_count: int
    auto_pause_count: int
    position_gap_ascent_m: float
    loop: bool
    closure_elevation_m: float
    closure_rate_ms: float
    altimetric_drift: bool
    barometric: bool
    mean_heart_rate_bpm: float | None
    heart_rate_coverage: float
    climbs: tuple[ClimbRow, ...]


def _track_summary(
    entry: IndexedActivity,
    recording: ActivityRecording,
    track: MotionTrack,
    settings: AthleteSettings,
    definition: Definition,
) -> _TrackSummary:
    lat, lon = track.latitude_deg, track.longitude_deg
    polyline = deduplicated_polyline(lat, lon)
    profile = (
        build_profile_with_diagnostics(track_route(track), definition.profile).profile
        if len(polyline.indices) >= 2
        else None
    )
    device = recording.device
    barometric = settings.barometric(
        device.barometer, device.manufacturer, device.product
    )
    zs = track.smoothed_elevation_m
    closure_distance = haversine_m(lat[0], lon[0], lat[-1], lon[-1])
    elapsed = track.time_s[-1]
    closure = zs[-1] - zs[0]
    drift = altimetric_drift(closure_distance, closure, elapsed, definition.quality)
    rows: tuple[ClimbRow, ...] = ()
    if profile is not None:
        measures = climbs(track, definition.profile, definition.climb)
        variants = (
            variant_climbs(track, definition.profile, definition.climb)
            if measures
            else ()
        )
        rows = tuple(
            _climb_row(
                entry,
                recording,
                track,
                profile,
                measure,
                rank,
                variants,
                barometric=barometric,
                drift=drift,
                settings=settings,
                definition=definition,
            )
            for rank, measure in enumerate(measures, start=1)
        )
    t = track.time_s
    steps = [t[i + 1] - t[i] for i in range(len(t) - 1)]
    gap_count, gap_s = _gaps(track, 0.0, elapsed)
    stops, autos = _timer_stops(recording, track.offset_s, track.offset_s + elapsed)
    hr = recording.heart_rate
    hr_values = _channel(
        None if hr is None else hr.time_s, None if hr is None else hr.heart_rate_bpm
    )
    with_hr = [hr_values[x] for x in track.recording_time_s if x in hr_values]
    k_all = range(len(CLOCK_CONVENTIONS))

    def totals(state: IntervalState) -> tuple[float, ...]:
        return tuple(track.time_in_state_s[(k, state)][-1] for k in k_all)

    return _TrackSummary(
        track_offset_s=track.offset_s,
        track_elapsed_s=elapsed,
        profile_distance_m=0.0 if profile is None else profile.distance_m[-1],
        profile_ascent_m=0.0 if profile is None else profile.cumulative_ascent_m[-1],
        profile_descent_m=(
            0.0 if profile is None else profile.cumulative_descent_m[-1]
        ),
        moving_s_by_convention=totals(IntervalState.MOVING),
        stopped_s_by_convention=totals(IntervalState.STOPPED),
        undetermined_s_by_convention=totals(IntervalState.UNDETERMINED),
        step_s=median(steps),
        longest_step_s=max(steps),
        gap_count=gap_count,
        gap_s=gap_s,
        timer_stop_count=stops,
        auto_pause_count=autos,
        position_gap_ascent_m=_position_gap_ascent_m(recording, track),
        loop=closure_distance < definition.quality["loop_closure_distance_m"],
        closure_elevation_m=closure,
        closure_rate_ms=abs(closure) / elapsed if elapsed > 0 else 0.0,
        altimetric_drift=drift,
        barometric=barometric,
        mean_heart_rate_bpm=math.fsum(with_hr) / len(with_hr) if with_hr else None,
        heart_rate_coverage=len(with_hr) / len(t),
        climbs=rows,
    )


def _activity_row(
    entry: IndexedActivity,
    refusal: ViewRefusal | None,
    recording: ActivityRecording | None,
    summary: _TrackSummary | None,
) -> ActivityRow:
    s = summary
    rows = () if s is None else s.climbs
    counts = dict.fromkeys(ClimbRegime, 0)
    for row in rows:
        counts[row.regime] += 1
    device = None if recording is None else recording.device
    temperature = None if recording is None else recording.temperature
    return ActivityRow(
        activity_ref=entry.activity_ref,
        source_activity_type=entry.source_activity_type,
        sport=SOURCE_TYPE_SPORTS.get(entry.source_activity_type),
        view_refusal=refusal,
        start_time=entry.start_time,
        index_elapsed_s=entry.elapsed_duration_s,
        index_moving_s=entry.moving_duration_s,
        index_distance_m=entry.distance_m,
        index_ascent_m=entry.ascent_m,
        index_descent_m=entry.descent_m,
        index_elevation_corrected=entry.elevation_corrected,
        index_average_heart_rate_bpm=entry.average_hr_bpm,
        index_max_heart_rate_bpm=entry.max_hr_bpm,
        has_recording=entry.has_recording,
        has_track=s is not None,
        session_count=None if recording is None else len(recording.sessions),
        track_offset_s=None if s is None else s.track_offset_s,
        track_elapsed_s=None if s is None else s.track_elapsed_s,
        profile_distance_m=None if s is None else s.profile_distance_m,
        profile_ascent_m=None if s is None else s.profile_ascent_m,
        profile_descent_m=None if s is None else s.profile_descent_m,
        moving_s_by_convention=None if s is None else s.moving_s_by_convention,
        stopped_s_by_convention=None if s is None else s.stopped_s_by_convention,
        undetermined_s_by_convention=(
            None if s is None else s.undetermined_s_by_convention
        ),
        step_s=None if s is None else s.step_s,
        longest_step_s=None if s is None else s.longest_step_s,
        gap_count=None if s is None else s.gap_count,
        gap_s=None if s is None else s.gap_s,
        timer_stop_count=None if s is None else s.timer_stop_count,
        auto_pause_count=None if s is None else s.auto_pause_count,
        position_gap_ascent_m=None if s is None else s.position_gap_ascent_m,
        loop=None if s is None else s.loop,
        closure_elevation_m=None if s is None else s.closure_elevation_m,
        closure_rate_ms=None if s is None else s.closure_rate_ms,
        altimetric_drift=None if s is None else s.altimetric_drift,
        device_manufacturer=None if device is None else device.manufacturer,
        device_product=None if device is None else device.product,
        software_version=None if device is None else device.software_version,
        barometer=None if device is None else device.barometer,
        barometric=None if s is None else s.barometric,
        external_heart_rate_sensor=(
            None if device is None else device.external_heart_rate_sensor
        ),
        mean_heart_rate_bpm=None if s is None else s.mean_heart_rate_bpm,
        heart_rate_coverage=None if s is None else s.heart_rate_coverage,
        mean_temperature_c=(
            None
            if temperature is None or not temperature.temperature_c
            else math.fsum(temperature.temperature_c) / len(temperature.temperature_c)
        ),
        climb_count=len(rows),
        short_climb_count=counts[ClimbRegime.SHORT_CLIMB],
        intermediate_count=counts[ClimbRegime.INTERMEDIATE],
        long_climb_count=counts[ClimbRegime.LONG_CLIMB],
        ski_touring_count=counts[ClimbRegime.SKI_TOURING],
        short_ski_touring_count=counts[ClimbRegime.SHORT_SKI_TOURING],
        other_sport_count=counts[ClimbRegime.OTHER_SPORT],
        flagged_climb_count=sum(1 for r in rows if r.flags),
        unstable_climb_count=sum(1 for r in rows if r.stable is False),
    )


def build_tables(
    data_dir: Path,
    settings: AthleteSettings,
    definition: Definition = DEFAULT_DEFINITION,
) -> Tables:
    """Les deux tables d'``interim/`` sous ``data_dir``, dans l'ordre de l'index ;
    les montées d'une activité dans l'ordre du temps. :class:`TablesError` si
    l'index ou l'enregistrement d'une activité ne se relit pas (``CodecError`` : un
    document d'un autre format, ou abîmé ; ``ContractError`` : un contrat en refuse la
    relecture), ou si les lignes d'une activité violent un contrat ;
    ``InterimError`` si un document manque."""
    try:
        index = read_index(data_dir)
    except (ContractError, CodecError) as error:
        raise TablesError(f"index d'interim/ : {error}") from error
    activity_rows: list[ActivityRow] = []
    climb_rows: list[ClimbRow] = []
    for entry in index.entries:
        refusal = activity_view(index, entry).refusal
        try:
            recording = (
                read_recording(data_dir, entry.activity_ref)
                if entry.has_recording
                else None
            )
            track = (
                None if recording is None else motion_track(recording, definition.climb)
            )
            summary = (
                None
                if recording is None or track is None
                else _track_summary(entry, recording, track, settings, definition)
            )
            activity_rows.append(_activity_row(entry, refusal, recording, summary))
        except (ContractError, CodecError) as error:
            raise TablesError(f"activité {entry.activity_ref} : {error}") from error
        if summary is not None:
            climb_rows += summary.climbs
    provenance = ProcessedProvenance(
        interim_sha256=interim_sha256(data_dir),
        package_version=__version__,
        reference_vertical_speed_ms=settings.reference_vertical_speed_ms,
        reference_vertical_speed_declared=settings.reference_vertical_speed_declared,
        barometer_products=tuple(
            sorted(f"{m}:{p}" for m, p in settings.barometer_products)
        ),
        parameters=definition.items(),
        activity_count=len(activity_rows),
        climb_count=len(climb_rows),
    )
    return Tables(tuple(activity_rows), tuple(climb_rows), provenance)
