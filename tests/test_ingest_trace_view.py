"""La trace commune (``mountain_perf.ingest.views.trace_view``, M6b) : la trace du
moteur tirée d'un enregistrement, que les montées de la piste analyse
(``motion_track``) et l'estimation de la courbe appellent.

Enregistrements synthétiques de ``tests/fixtures/montees.py`` (qui enregistre à partir
de ``t = 1 s``) et de ``tests/test_schemas_interim.py``."""

from __future__ import annotations

from datetime import timedelta

from fixtures.montees import FLAT, climb_at, recording
from mountain_perf.analyse.climbs import motion_track
from mountain_perf.ingest.views import stream_view, trace_view
from mountain_perf.schemas import ElevationChannel, ElevationField, PositionChannel
from test_schemas_interim import recording as interim_recording


def test_the_trace_starts_at_the_first_instant_of_the_view() -> None:
    """La trace part du premier instant de la vue positions et altitude ; ses
    positions et altitudes sont celles de la vue ; sa source celle de
    l'enregistrement."""
    rec = recording([FLAT, climb_at(600, 0.15, 30)], noise=False)
    stream = stream_view(rec, elevation=True).stream
    assert stream is not None
    assert stream.elevation_m is not None
    view = trace_view(rec)
    assert view is not None
    trace = view.trace
    assert view.offset_s == 1.0
    assert trace.start_time == rec.start_time + timedelta(seconds=1)
    assert trace.time_s[0] == 0.0
    assert view.recording_time_s == stream.time_s
    assert trace.time_s == tuple(t - 1.0 for t in stream.time_s)
    assert trace.latitude_deg == stream.latitude_deg
    assert trace.longitude_deg == stream.longitude_deg
    assert trace.elevation_m == stream.elevation_m
    assert trace.sources == (rec.source,)
    assert trace.dropped_same_instant_count == 0


def test_the_view_keeps_the_instants_where_positions_and_elevation_meet() -> None:
    """Positions aux instants 0, 1, 2, 3 s, altitude aux seuls instants 1 et 3 s : la
    trace a ces deux instants, ramenés à l'origine de la vue."""
    rec = interim_recording(
        position=PositionChannel(
            (0.0, 1.0, 2.0, 3.0),
            (45.0, 45.0001, 45.0002, 45.0003),
            (6.0, 6.0001, 6.0002, 6.0003),
        ),
        elevation=ElevationChannel(
            (1.0, 3.0), (1000.0, 1001.0), ElevationField.ENHANCED_ALTITUDE
        ),
    )
    view = trace_view(rec)
    assert view is not None
    assert view.recording_time_s == (1.0, 3.0)
    assert view.trace.time_s == (0.0, 2.0)
    assert view.trace.longitude_deg == (6.0001, 6.0003)


def test_no_trace_without_positions_elevation_or_two_instants() -> None:
    """Sans positions, sans altitude, ou avec une seule altitude : ``None``."""
    with_elevation = ElevationChannel(
        (0.0, 1.0), (1000.0, 1001.0), ElevationField.ENHANCED_ALTITUDE
    )
    no_positions = interim_recording(position=None, elevation=with_elevation)
    assert trace_view(no_positions) is None
    assert trace_view(interim_recording(elevation=None)) is None
    single = ElevationChannel((1.0,), (1000.0,), ElevationField.ENHANCED_ALTITUDE)
    assert trace_view(interim_recording(elevation=single)) is None


def test_motion_track_reads_the_same_view() -> None:
    """``motion_track`` lit la vue de ``trace_view`` : même origine, mêmes instants dans
    le temps de la trace et dans celui de l'enregistrement."""
    rec = recording([FLAT, climb_at(600, 0.15, 30)], noise=False)
    view = trace_view(rec)
    track = motion_track(rec)
    assert view is not None
    assert track is not None
    assert track.offset_s == view.offset_s
    assert track.time_s == view.trace.time_s
    assert track.recording_time_s == view.recording_time_s
