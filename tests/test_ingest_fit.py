"""Le lecteur FIT de l'ingestion, sur des FIT synthétiques (``0011``, ``0013``)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

pytest.importorskip("fitdecode")

import mountain_perf.ingest.fit as fit_module
from fixtures.fit_activity import (
    ANTPLUS_BIKE_POWER,
    ANTPLUS_HEART_RATE,
    BLE_HEART_RATE,
    FILE_ID,
    LOCAL_BAROMETER,
    LOCAL_GPS,
    LOCAL_WHR,
    SOURCE_ANTPLUS,
    SOURCE_BLE,
    SOURCE_LOCAL,
    START,
    Sample,
    activity_fit,
    semicircles,
)
from fixtures.fit_writer import ENUM, STRING, FieldDef, FitWriter
from mountain_perf.ingest.fit import SEMICIRCLE_DEG, FitRefusedError, read_fit
from mountain_perf.schemas import (
    ActivityRecording,
    DiscardCount,
    DiscardReason,
    ElevationField,
    RecordingPart,
    RefusalReason,
    SourceRef,
    SpeedField,
    TimerEventType,
    TimerTrigger,
)

SOURCE = SourceRef("garmin_fit", "7.zip", "c" * 64, datetime(2024, 4, 1, tzinfo=UTC))


def _read(data: bytes) -> ActivityRecording:
    return read_fit(data, activity_ref="7", source=SOURCE)


def _counts(recording: ActivityRecording) -> dict[tuple[str, str], int]:
    return {(d.part.value, d.reason.value): d.count for d in recording.discarded}


# --- oracles écrits en dur, indépendants de l'écrivain ------------------------------


def test_raw_values_convert_to_contract_units() -> None:
    sample = Sample(
        0,
        raw={
            "position_lat": 2**29,
            "position_long": -(2**30),
            "enhanced_altitude": 7500,
            "heart_rate": 150,
            "distance": 12345,
            "enhanced_speed": 2500,
        },
    )
    r = _read(activity_fit([sample]))
    assert r.position is not None
    assert r.position.latitude_deg == (45.0,)
    assert r.position.longitude_deg == (-90.0,)
    assert r.elevation is not None
    assert r.elevation.elevation_m == (1000.0,)
    assert r.heart_rate is not None
    assert r.heart_rate.heart_rate_bpm == (150.0,)
    assert r.distance is not None
    assert r.distance.distance_m == (123.45,)
    assert r.speed is not None
    assert r.speed.speed_ms == (2.5,)


def test_times_count_from_the_first_session_start() -> None:
    samples = [Sample(t, lat=45.0, lon=6.0, heart_rate=100) for t in (0, 1, 3)]
    r = _read(activity_fit(samples))
    assert r.start_time == START
    assert r.position is not None
    assert r.position.time_s == (0.0, 1.0, 3.0)


def test_channels_are_independent() -> None:
    samples = [
        Sample(0, heart_rate=100),
        Sample(1, lat=45.0, lon=6.0, heart_rate=101),
        Sample(2, lat=45.0001, lon=6.0, enhanced_altitude=1000.0),
    ]
    r = _read(activity_fit(samples))
    assert r.position is not None
    assert r.position.time_s == (1.0, 2.0)
    assert r.heart_rate is not None
    assert r.heart_rate.time_s == (0.0, 1.0)
    assert r.elevation is not None
    assert r.elevation.time_s == (2.0,)
    assert r.distance is None
    assert r.discarded == ()


# --- règles d'écart et leur ordre --------------------------------------------------


def test_each_discard_rule_counts_its_samples() -> None:
    samples = [
        Sample(-5, heart_rate=100),  # avant le départ
        Sample(0, lat=45.0, lon=6.0, heart_rate=101, distance=100.0),
        Sample(1, lat=45.0, heart_rate=10, distance=90.0),  # demi-position, FC, recul
        Sample(2, lat=45.0, lon=6.0, heart_rate=121, distance=95.0),  # recul
        Sample(2, heart_rate=122),  # instant déjà gardé
        Sample(3, distance=110.0),
    ]
    r = _read(activity_fit(samples))
    assert _counts(r) == {
        ("distance", "distance_decreasing"): 2,
        ("heart_rate", "before_start"): 1,
        ("heart_rate", "not_after_previous"): 1,
        ("heart_rate", "out_of_range"): 1,
        ("position", "half_position"): 1,
    }
    assert r.distance is not None
    assert r.distance.distance_m == (100.0, 110.0)
    assert r.heart_rate is not None
    assert r.heart_rate.time_s == (0.0, 2.0)
    assert r.position is not None
    assert r.position.time_s == (0.0, 2.0)


def test_a_discarded_sample_does_not_become_the_last_kept() -> None:
    """Une FC hors plage à 2 s ne fait pas refuser la FC valide de 1 s qui la suit."""
    samples = [
        Sample(0, heart_rate=100),
        Sample(2, heart_rate=252),
        Sample(1, heart_rate=110),
    ]
    r = _read(activity_fit(samples))
    assert r.heart_rate is not None
    assert r.heart_rate.time_s == (0.0, 1.0)
    assert _counts(r) == {("heart_rate", "out_of_range"): 1}


def test_time_rules_come_before_value_rules() -> None:
    """Avant le départ et hors plage : avant le départ ; déjà vu et hors plage : déjà
    vu ; déjà vu et demi-position : déjà vu."""
    samples = [
        Sample(-1, heart_rate=10),
        Sample(0, lat=45.0, lon=6.0, heart_rate=100),
        Sample(0, lat=45.0, heart_rate=10),
    ]
    r = _read(activity_fit(samples))
    assert _counts(r) == {
        ("heart_rate", "before_start"): 1,
        ("heart_rate", "not_after_previous"): 1,
        ("position", "not_after_previous"): 1,
    }


def test_out_of_range_position_is_discarded() -> None:
    samples = [
        Sample(0, raw={"position_lat": 2**30 + 1, "position_long": 0}),
        Sample(1, lat=45.0, lon=6.0),
    ]
    r = _read(activity_fit(samples))
    assert _counts(r) == {("position", "out_of_range"): 1}
    assert r.position is not None
    assert r.position.time_s == (1.0,)


def test_a_recording_written_twice_keeps_the_first_copy() -> None:
    """Le cas réel : le chronomètre repart au départ et la sortie est réécrite."""
    first = [
        Sample(t, lat=45.0 + t / 1e4, lon=6.0, heart_rate=100 + t, enhanced_speed=2.0)
        for t in range(4)
    ]
    again = [
        Sample(t, lat=45.0 + t / 1e4, lon=6.0, heart_rate=100 + t, enhanced_speed=2.0)
        for t in range(3)
    ]
    r = _read(activity_fit(first + again))
    assert r.position is not None
    assert r.position.time_s == (0.0, 1.0, 2.0, 3.0)
    assert _counts(r) == {
        ("heart_rate", "duplicate"): 3,
        ("position", "duplicate"): 3,
        ("speed", "duplicate"): 3,
    }


# --- champs améliorés, expansion, horodatage compressé, développeur ---------------


def test_basic_altitude_and_speed_when_the_file_writes_no_enhanced_field() -> None:
    """fitdecode tire enhanced_altitude d'altitude par expansion : l'expansion ne
    compte pas comme écrite."""
    samples = [
        Sample(0, altitude=1000.0, speed=2.0),
        Sample(1, altitude=1001.0, speed=2.5),
    ]
    r = _read(activity_fit(samples, record_fields=("timestamp", "altitude", "speed")))
    assert r.elevation is not None
    assert r.elevation.source_field is ElevationField.ALTITUDE
    assert r.elevation.elevation_m == (1000.0, 1001.0)
    assert r.speed is not None
    assert r.speed.source_field is SpeedField.SPEED


def test_enhanced_field_wins_and_basic_values_are_not_mixed_in() -> None:
    samples = [
        Sample(
            0, enhanced_altitude=1000.0, altitude=1500.0, enhanced_speed=2.0, speed=3.0
        ),
        Sample(1, altitude=1501.0, speed=3.1),
        Sample(2, enhanced_altitude=1002.0, enhanced_speed=2.2),
    ]
    fields = ("timestamp", "enhanced_altitude", "altitude", "enhanced_speed", "speed")
    r = _read(activity_fit(samples, record_fields=fields))
    assert r.elevation is not None
    assert r.elevation.source_field is ElevationField.ENHANCED_ALTITUDE
    assert r.elevation.time_s == (0.0, 2.0)
    assert r.elevation.elevation_m == (1000.0, 1002.0)
    assert r.speed is not None
    assert r.speed.source_field is SpeedField.ENHANCED_SPEED
    assert r.speed.speed_ms == (2.0, 2.2)
    assert _counts(r) == {
        ("elevation", "other_field"): 1,
        ("speed", "other_field"): 1,
    }


def test_other_field_is_counted_without_the_other_rules() -> None:
    """Le compte du champ non retenu ne regarde ni l'instant ni la valeur."""
    samples = [
        Sample(0, enhanced_altitude=1000.0, enhanced_speed=2.0),
        Sample(1, altitude=12000.0, speed=3.0),
        Sample(1, altitude=1001.0, speed=3.5),
        Sample(-5, altitude=1002.0, speed=3.0),
    ]
    fields = ("timestamp", "enhanced_altitude", "altitude", "enhanced_speed", "speed")
    r = _read(activity_fit(samples, record_fields=fields))
    assert _counts(r) == {("elevation", "other_field"): 3, ("speed", "other_field"): 3}


def test_a_rewritten_sample_with_another_value_is_not_a_duplicate() -> None:
    """Un instant déjà gardé, avec une autre valeur : une mesure perdue, pas un
    doublon (une horloge recalée en arrière, par exemple)."""
    first = [
        Sample(t, lat=45.0, lon=6.0 + t / 1e4, heart_rate=100 + t) for t in range(3)
    ]
    again = [
        Sample(1, lat=45.0, lon=6.0001, heart_rate=150),
        Sample(2, lat=45.5, lon=6.0002, heart_rate=102),
        Sample(0, lat=45.0, lon=6.0, heart_rate=100),
    ]
    r = _read(activity_fit(first + again))
    assert _counts(r) == {
        ("heart_rate", "duplicate"): 2,
        ("heart_rate", "not_after_previous"): 1,
        ("position", "duplicate"): 2,
        ("position", "not_after_previous"): 1,
    }


def test_an_instant_between_kept_ones_is_not_a_duplicate() -> None:
    """Un instant non gardé du canal (entre deux instants gardés) n'a pas de jumeau."""
    first = [Sample(t, heart_rate=100) for t in (0, 2, 4)]
    r = _read(activity_fit([*first, Sample(1, heart_rate=100)]))
    assert _counts(r) == {("heart_rate", "not_after_previous"): 1}


def test_raw_zeros_are_sentinels() -> None:
    """Le brut 0 de l'altitude (−500 m) et la position brute (0, 0) sont des valeurs
    sentinelles ; une latitude nulle avec une longitude non nulle est une position."""
    samples = [
        Sample(0, raw={"enhanced_altitude": 0}),
        Sample(1, raw={"position_lat": 0, "position_long": 0}),
        Sample(2, raw={"position_lat": 0, "position_long": semicircles(6.0)}),
        Sample(3, raw={"position_lat": semicircles(45.0), "position_long": 0}),
        Sample(4, lat=45.0, lon=6.0, enhanced_altitude=1000.0),
        Sample(5, raw={"position_lat": 0, "position_long": 0, "enhanced_altitude": 0}),
    ]
    r = _read(activity_fit(samples))
    assert _counts(r) == {("elevation", "sentinel"): 2, ("position", "sentinel"): 2}
    assert r.position is not None
    assert r.position.time_s == (2.0, 3.0, 4.0)
    assert r.position.latitude_deg[:2] == (0.0, semicircles(45.0) * SEMICIRCLE_DEG)
    assert r.position.longitude_deg[:2] == (semicircles(6.0) * SEMICIRCLE_DEG, 0.0)
    assert r.elevation is not None
    assert r.elevation.time_s == (4.0,)


def test_basic_altitude_zero_is_a_sentinel() -> None:
    samples = [Sample(0, raw={"altitude": 0}), Sample(1, altitude=1000.0)]
    r = _read(activity_fit(samples, record_fields=("timestamp", "altitude")))
    assert r.elevation is not None
    assert r.elevation.source_field is ElevationField.ALTITUDE
    assert r.elevation.time_s == (1.0,)
    assert _counts(r) == {("elevation", "sentinel"): 1}


def test_time_rules_come_before_the_sentinel() -> None:
    """L'ordre de la sentinelle et de la plage, lui, ne s'observe pas : −500 m et
    (0°, 0°) sont dans les plages."""
    samples = [
        Sample(0, lat=45.0, lon=6.0, enhanced_altitude=1000.0),
        Sample(0, raw={"position_lat": 0, "position_long": 0, "enhanced_altitude": 0}),
        Sample(-1, raw={"enhanced_altitude": 0}),
    ]
    r = _read(activity_fit(samples))
    assert _counts(r) == {
        ("elevation", "before_start"): 1,
        ("elevation", "not_after_previous"): 1,
        ("position", "not_after_previous"): 1,
    }


def test_invalid_values_are_not_values() -> None:
    """Un champ défini mais écrit à sa valeur invalide (fitdecode rend ``None``) ne
    compte pas pour son canal : ni écart, ni demi-position."""
    samples = [
        *(Sample(t) for t in range(3)),
        *(
            Sample(t, lat=45.0, lon=6.0, enhanced_altitude=1000.0, heart_rate=120)
            for t in range(3, 5)
        ),
        Sample(5, lat=45.1),
    ]
    r = _read(activity_fit(samples))
    assert r.position is not None
    assert r.position.time_s == (3.0, 4.0)
    assert r.elevation is not None
    assert r.elevation.time_s == (3.0, 4.0)
    assert r.heart_rate is not None
    assert r.heart_rate.time_s == (3.0, 4.0)
    assert _counts(r) == {("position", "half_position"): 1}


def test_compressed_timestamps_are_read() -> None:
    samples = [Sample(t, heart_rate=100 + t) for t in (0, 1, 2, 5, 20, 33)]
    r = _read(activity_fit(samples, compressed_after=2))
    assert r.heart_rate is not None
    assert r.heart_rate.time_s == (0.0, 1.0, 2.0, 5.0, 20.0, 33.0)


def test_developer_fields_are_ignored() -> None:
    samples = [Sample(0, lat=45.0, lon=6.0), Sample(1, lat=45.0001, lon=6.0)]
    r = _read(activity_fit(samples, developer_field=True))
    assert r.position is not None
    assert len(r.position.time_s) == 2


def test_compressed_timestamps_are_read_after_developer_fields() -> None:
    """fitdecode ajoute l'horodatage d'un en-tête compressé après les champs de
    développeur du record : il reste lu."""
    samples = [Sample(t, heart_rate=100 + t) for t in (0, 1, 2, 5, 20, 33)]
    r = _read(activity_fit(samples, compressed_after=2, developer_field=True))
    assert r.heart_rate is not None
    assert r.heart_rate.time_s == (0.0, 1.0, 2.0, 5.0, 20.0, 33.0)


# --- sessions, chronomètre, appareil -----------------------------------------------


def test_sessions_are_sorted_and_the_start_is_the_earliest() -> None:
    samples = [Sample(t, heart_rate=100) for t in (0, 30, 90)]
    r = _read(
        activity_fit(
            samples,
            sessions=(
                (60, "cycling", "mountain", 30.0, 30.0, 500.0),
                (0, "running", "trail", 60.0, 55.0, 300.0),
            ),
        )
    )
    assert [s.sport for s in r.sessions] == ["running", "cycling"]
    assert [s.sub_sport for s in r.sessions] == ["trail", "mountain"]
    assert [s.start_s for s in r.sessions] == [0.0, 60.0]
    assert r.sessions[0].timer_duration_s == 55.0
    assert r.sessions[1].distance_m == 500.0


def test_sessions_with_the_same_start_keep_the_file_order() -> None:
    """Tri stable : deux sessions au même départ restent dans l'ordre du fichier."""
    r = _read(
        activity_fit(
            [Sample(t, heart_rate=100) for t in (0, 30)],
            sessions=(
                (0, "running", "trail", 30.0, 30.0, 100.0),
                (0, "cycling", "mountain", 30.0, 30.0, 200.0),
                (0, "hiking", None, 30.0, 30.0, 50.0),
            ),
        )
    )
    assert [s.sport for s in r.sessions] == ["running", "cycling", "hiking"]


def test_timer_events_types_and_discards() -> None:
    r = _read(
        activity_fit(
            [Sample(0, heart_rate=100)],
            timer_events=(
                (-3, "start"),
                (-2, "stop"),
                (0, "start"),
                (10, "marker"),
                (12, "marker"),
                (20, "stop_all"),
                (20, "start"),
                (15, "stop"),
                (14, "start"),
            ),
        )
    )
    assert [(e.time_s, e.event_type) for e in r.timer_events] == [
        (0.0, TimerEventType.START),
        (20.0, TimerEventType.STOP_ALL),
        (20.0, TimerEventType.START),
    ]
    assert _counts(r) == {
        ("timer_event", "before_start"): 2,
        ("timer_event", "not_after_previous"): 2,
        ("timer_event", "unknown_type"): 2,
    }


def test_device_provenance_without_identifier() -> None:
    r = _read(activity_fit([Sample(0, heart_rate=100)]))
    assert r.device.file_type == "activity"
    assert r.device.manufacturer == "garmin"
    assert r.device.product == 999
    assert r.device.software_version == 12.34
    assert r.device.time_created == START


def test_discarded_are_sorted_by_part_then_reason() -> None:
    samples = [Sample(-1, lat=45.0, lon=6.0, heart_rate=100), Sample(0, heart_rate=252)]
    r = _read(activity_fit([*samples, Sample(1, heart_rate=100)]))
    assert r.discarded == (
        DiscardCount(RecordingPart.HEART_RATE, DiscardReason.BEFORE_START, 1),
        DiscardCount(RecordingPart.HEART_RATE, DiscardReason.OUT_OF_RANGE, 1),
        DiscardCount(RecordingPart.POSITION, DiscardReason.BEFORE_START, 1),
    )


def test_reasons_are_sorted_by_value_not_by_rule() -> None:
    """``distance_decreasing`` avant ``duplicate`` : l'ordre des valeurs, que le contrat
    exige, et non celui des règles (le doublon se juge avant le recul)."""
    samples = [
        Sample(0, distance=100.0),
        Sample(1, distance=90.0),
        Sample(0, distance=100.0),
    ]
    r = _read(activity_fit(samples))
    assert r.discarded == (
        DiscardCount(RecordingPart.DISTANCE, DiscardReason.DISTANCE_DECREASING, 1),
        DiscardCount(RecordingPart.DISTANCE, DiscardReason.DUPLICATE, 1),
    )


def test_timer_event_rules_come_in_order() -> None:
    """Avant le départ l'emporte sur « antérieur au dernier gardé » et sur le type
    inconnu ; « antérieur au dernier gardé » l'emporte sur le type inconnu."""
    r = _read(
        activity_fit(
            [Sample(0, heart_rate=100)],
            timer_events=(
                (0, "start"),
                (-1, "stop"),
                (-2, "marker"),
                (10, "stop"),
                (5, "marker"),
            ),
        )
    )
    assert _counts(r) == {
        ("timer_event", "before_start"): 2,
        ("timer_event", "not_after_previous"): 1,
    }


def test_half_position_comes_before_the_range() -> None:
    samples = [
        Sample(0, raw={"position_lat": 2**30 + 1}),
        Sample(1, lat=45.0, lon=6.0),
    ]
    r = _read(activity_fit(samples))
    assert _counts(r) == {("position", "half_position"): 1}


def test_a_record_without_timestamp_writing_only_the_other_field() -> None:
    """Le compte du champ non retenu ne regarde pas l'instant, et le canal retenu n'a
    rien à écarter : ``OTHER_FIELD``, pas ``NO_TIMESTAMP``."""
    samples = [
        Sample(0, enhanced_altitude=1000.0, enhanced_speed=2.0),
        Sample(0, altitude=1001.0, speed=3.0, no_timestamp=True),
    ]
    fields = ("timestamp", "enhanced_altitude", "altitude", "enhanced_speed", "speed")
    r = _read(activity_fit(samples, record_fields=fields))
    assert _counts(r) == {("elevation", "other_field"): 1, ("speed", "other_field"): 1}


# --- refus --------------------------------------------------------------------------


def test_corrupt_crc_is_refused() -> None:
    with pytest.raises(FitRefusedError) as error:
        _read(activity_fit([Sample(0, heart_rate=100)], corrupt_crc=True))
    assert error.value.reason is RefusalReason.UNREADABLE_FIT


def test_no_session_is_refused() -> None:
    with pytest.raises(FitRefusedError) as error:
        _read(activity_fit([Sample(0, heart_rate=100)], sessions=()))
    assert error.value.reason is RefusalReason.NO_SESSION


def test_session_without_start_is_refused() -> None:
    sessions = (
        (0, "running", "trail", 60.0, 60.0, 100.0),
        (None, "cycling", "mountain", 30.0, 30.0, 50.0),
    )
    with pytest.raises(FitRefusedError) as error:
        _read(activity_fit([Sample(0, heart_rate=100)], sessions=sessions))
    assert error.value.reason is RefusalReason.NO_SESSION


def test_no_kept_sample_is_refused() -> None:
    with pytest.raises(FitRefusedError) as error:
        _read(activity_fit([Sample(-2, heart_rate=100), Sample(-1, heart_rate=100)]))
    assert error.value.reason is RefusalReason.NO_SAMPLE


def test_same_bytes_same_recording() -> None:
    data = activity_fit([Sample(t, lat=45.0, lon=6.0 + t / 1e4) for t in range(5)])
    assert _read(data) == _read(data)


def test_semicircle_helper_is_exact_for_the_oracles() -> None:
    assert semicircles(45.0) == 2**29
    assert START + timedelta(0) == START


# --- compléments du balayage par mutation ----------------------------------------


def test_session_fields_are_all_read() -> None:
    r = _read(
        activity_fit(
            [Sample(0, heart_rate=100)],
            sessions=((0, "hiking", None, 75.5, 70.25, 321.5),),
        )
    )
    (s,) = r.sessions
    assert (s.sport, s.sub_sport, s.start_s) == ("hiking", None, 0.0)
    assert (s.elapsed_duration_s, s.timer_duration_s, s.distance_m) == (
        75.5,
        70.25,
        321.5,
    )


def test_counts_add_up() -> None:
    samples = [
        Sample(-2, lat=45.0, lon=6.0, heart_rate=100),
        Sample(-1, lat=45.0, lon=6.0, heart_rate=100),
        Sample(0, lat=45.0, heart_rate=10),
        Sample(1, lon=6.0, heart_rate=252),
        Sample(2, raw={"position_lat": 2**30 + 5, "position_long": 0}),
        Sample(3, raw={"position_lat": -(2**30) - 3, "position_long": 0}),
        Sample(4, lat=45.0, lon=6.0, heart_rate=100),
    ]
    r = _read(activity_fit(samples))
    assert _counts(r) == {
        ("heart_rate", "before_start"): 2,
        ("heart_rate", "out_of_range"): 2,
        ("position", "before_start"): 2,
        ("position", "half_position"): 2,
        ("position", "out_of_range"): 2,
    }
    assert r.position is not None
    assert r.position.time_s == (4.0,)


def test_range_bounds_are_kept() -> None:
    samples = [
        Sample(
            0, raw={"position_lat": 2**30, "position_long": -(2**31)}, heart_rate=20
        ),
        Sample(1, raw={"position_lat": -(2**30), "position_long": 0}, heart_rate=250),
        Sample(2, raw={"enhanced_altitude": 1}, distance=0.0, enhanced_speed=0.0),
        Sample(3, enhanced_altitude=9000.0, distance=0.0, enhanced_speed=0.0),
    ]
    r = _read(activity_fit(samples))
    assert r.discarded == ()
    assert r.position is not None
    assert r.position.latitude_deg == (90.0, -90.0)
    assert r.position.longitude_deg == (-180.0, 0.0)
    assert r.heart_rate is not None
    assert r.heart_rate.heart_rate_bpm == (20.0, 250.0)
    assert r.distance is not None
    assert r.distance.distance_m == (0.0, 0.0)
    assert r.elevation is not None
    assert r.elevation.elevation_m == (-499.8, 9000.0)
    assert r.speed is not None
    assert r.speed.speed_ms == (0.0, 0.0)


def test_records_and_events_without_timestamp_are_counted() -> None:
    samples = [
        Sample(0, heart_rate=100),
        Sample(0, lat=45.0, lon=6.0, heart_rate=120, no_timestamp=True),
        Sample(0, lat=45.0, lon=6.0, heart_rate=121, no_timestamp=True),
        Sample(1, lat=45.0, lon=6.0, heart_rate=101),
    ]
    events = ((None, "stop_all"), (None, "stop_all"), (0, "start"), (60, "stop_all"))
    r = _read(activity_fit(samples, timer_events=events))
    assert _counts(r) == {
        ("heart_rate", "no_timestamp"): 2,
        ("position", "no_timestamp"): 2,
        ("timer_event", "no_timestamp"): 2,
    }
    assert r.heart_rate is not None
    assert r.heart_rate.time_s == (0.0, 1.0)
    assert r.position is not None
    assert r.position.time_s == (1.0,)
    assert [e.time_s for e in r.timer_events] == [0.0, 60.0]


def test_decreasing_values_are_kept_except_distance() -> None:
    rows = ((0, 120, 1010.0, 3.0), (1, 110, 1005.0, 2.0), (2, 100, 1000.0, 1.0))
    samples = [
        Sample(t, heart_rate=hr, enhanced_altitude=alt, enhanced_speed=v)
        for t, hr, alt, v in rows
    ]
    r = _read(activity_fit(samples))
    assert r.discarded == ()
    assert r.heart_rate is not None
    assert r.heart_rate.heart_rate_bpm == (120.0, 110.0, 100.0)


def test_no_speed_channel_when_every_speed_is_discarded() -> None:
    r = _read(activity_fit([Sample(-1, enhanced_speed=2.0), Sample(0, heart_rate=100)]))
    assert r.speed is None
    assert _counts(r) == {("speed", "before_start"): 1}


def test_no_elevation_channel_when_every_altitude_is_discarded() -> None:
    samples = [Sample(0, enhanced_altitude=9500.0, heart_rate=100)]
    r = _read(activity_fit(samples))
    assert r.elevation is None
    assert _counts(r) == {("elevation", "out_of_range"): 1}


def test_other_events_are_ignored() -> None:
    r = _read(
        activity_fit(
            [Sample(0, heart_rate=100)],
            timer_events=((0, "start"),),
            other_events=((5, 10, 3), (6, 10, 0)),
        )
    )
    assert [e.event_type for e in r.timer_events] == [TimerEventType.START]
    assert r.discarded == ()


def test_device_without_file_id_or_creator() -> None:
    r = _read(activity_fit([Sample(0, heart_rate=100)], file_id=False, devices=()))
    assert (r.device.file_type, r.device.manufacturer, r.device.product) == (None,) * 3
    assert (r.device.time_created, r.device.software_version) == (None, None)


def test_device_creator_is_index_zero() -> None:
    r = _read(
        activity_fit(
            [Sample(0, heart_rate=100)],
            devices=((2, 701), (0, 5601), (1, 5602)),
            product=None,
            time_created=False,
        )
    )
    assert r.device.software_version == 56.01
    assert (r.device.product, r.device.time_created) == (None, None)


def test_the_first_file_id_and_the_first_creator_are_read() -> None:
    """Le premier ``file_id`` donne le fabricant et le produit ; le premier
    ``device_info`` du créateur, la version du logiciel."""
    r = _read(
        activity_fit(
            [Sample(0, heart_rate=100)],
            second_file_id=(255, 1001),
            devices=((0, 5601), (0, 7002)),
        )
    )
    assert (r.device.manufacturer, r.device.product) == ("garmin", 999)
    assert r.device.software_version == 56.01


def test_a_malformed_fit_that_fitdecode_cannot_decode_is_unreadable() -> None:
    """Une définition au champ de taille nulle : fitdecode lève une ``ValueError``, pas
    une ``FitError`` ; le fichier est refusé ``UNREADABLE_FIT``, sans arrêter
    l'ingestion (``0013``, point 5)."""
    w = FitWriter()
    w.define(0, FILE_ID, (FieldDef(0, ENUM), FieldDef(8, STRING)))
    w.data(0, (4, None))
    with pytest.raises(FitRefusedError) as error:
        _read(w.to_bytes())
    assert error.value.reason is RefusalReason.UNREADABLE_FIT


def test_an_error_of_the_reader_is_not_an_unreadable_file(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Seul le décodage par fitdecode est gardé : une erreur du lecteur lui-même (ici,
    simulée dans la réduction des messages) se propage, avec son type, au lieu de
    refuser le fichier ``UNREADABLE_FIT``."""

    def broken(frame: object) -> object:
        raise KeyError("erreur du lecteur")

    monkeypatch.setattr(fit_module, "_message", broken)
    with pytest.raises(KeyError, match="erreur du lecteur"):
        _read(activity_fit([Sample(0, heart_rate=100)]))


def test_product_zero_is_a_product_number() -> None:
    """0 est un numéro de produit (``uint16``), pas la valeur invalide."""
    r = _read(activity_fit([Sample(0, heart_rate=100)], product=0))
    assert r.device.product == 0


def test_relative_time_created_is_absent() -> None:
    """Un ``time_created`` inférieur à ``0x10000000`` (horloge non réglée) : fitdecode
    le laisse en entier, ce n'est pas un instant ; il est absent, et le reste se lit."""
    r = _read(activity_fit([Sample(0, heart_rate=100)], created_raw=1000))
    assert r.device.time_created is None
    assert r.start_time == START


def test_strict_reading_refuses_a_decoding_error() -> None:
    """Un champ de développeur d'un développeur jamais déclaré : fitdecode ne fait
    qu'avertir par défaut ; la lecture stricte refuse."""
    data = activity_fit([Sample(0, heart_rate=100)], undeclared_developer=True)
    with pytest.raises(FitRefusedError) as error:
        _read(data)
    assert error.value.reason is RefusalReason.UNREADABLE_FIT


# --- capteurs, déclencheur, température (révision 2) --------------------------------


@pytest.mark.parametrize(
    ("sensors", "barometer", "external"),
    [
        ([], None, None),
        (
            [(1, SOURCE_LOCAL, LOCAL_BAROMETER), (2, SOURCE_LOCAL, LOCAL_GPS)],
            True,
            False,
        ),
        ([(1, SOURCE_LOCAL, LOCAL_GPS), (2, SOURCE_LOCAL, LOCAL_WHR)], False, False),
        ([(1, SOURCE_LOCAL, None)], None, False),
        ([(1, SOURCE_ANTPLUS, ANTPLUS_HEART_RATE)], None, True),
        ([(1, SOURCE_BLE, BLE_HEART_RATE)], None, True),
        ([(1, SOURCE_ANTPLUS, ANTPLUS_BIKE_POWER)], None, False),
        ([(1, SOURCE_BLE, ANTPLUS_HEART_RATE)], None, False),
        ([(1, SOURCE_ANTPLUS, BLE_HEART_RATE)], None, False),
        ([(1, None, ANTPLUS_HEART_RATE)], None, None),
        (
            [
                (1, SOURCE_LOCAL, LOCAL_BAROMETER),
                (2, SOURCE_ANTPLUS, ANTPLUS_HEART_RATE),
            ],
            True,
            True,
        ),
    ],
)
def test_device_sensors(
    sensors: list[tuple[int, int | None, int | None]],
    barometer: bool | None,
    external: bool | None,
) -> None:
    """Baromètre : décrit parmi les capteurs internes ; capteur de FC externe : ANT+ ou
    BLE, avec le type de FC de sa propre table (120 en ANT+, 1 en BLE)."""
    samples = [Sample(t, heart_rate=100) for t in range(2)]
    device = _read(activity_fit(samples, sensors=sensors)).device
    assert (device.barometer, device.external_heart_rate_sensor) == (
        barometer,
        external,
    )


def test_timer_triggers_are_read() -> None:
    events = [(0, "start"), (30, "stop"), (40, "start"), (60, "stop_all")]
    triggers = ["manual", "auto", None, "fitness_equipment"]
    samples = [Sample(t, heart_rate=100) for t in range(2)]
    r = _read(activity_fit(samples, timer_events=events, timer_triggers=triggers))
    assert [(e.time_s, e.event_type, e.trigger) for e in r.timer_events] == [
        (0.0, TimerEventType.START, TimerTrigger.MANUAL),
        (30.0, TimerEventType.STOP, TimerTrigger.AUTO),
        (40.0, TimerEventType.START, None),
        (60.0, TimerEventType.STOP_ALL, TimerTrigger.FITNESS_EQUIPMENT),
    ]


def test_timer_trigger_absent_is_none() -> None:
    samples = [Sample(t, heart_rate=100) for t in range(2)]
    r = _read(activity_fit(samples))
    assert [e.trigger for e in r.timer_events] == [None, None]


def test_temperature_channel() -> None:
    """Bornes gardées, hors plage écartée, valeur invalide ignorée, valeurs qui
    décroissent gardées ; le brut 0 (0 °C) est une température."""
    samples = [
        Sample(0, temperature=-60),
        Sample(1, temperature=80),
        Sample(2, temperature=81),
        Sample(3, temperature=-61),
        Sample(4),
        Sample(5, temperature=0),
        Sample(6, temperature=-5),
    ]
    r = _read(activity_fit(samples, record_fields=("timestamp", "temperature")))
    assert r.temperature is not None
    assert r.temperature.time_s == (0.0, 1.0, 5.0, 6.0)
    assert r.temperature.temperature_c == (-60.0, 80.0, 0.0, -5.0)
    assert _counts(r) == {("temperature", "out_of_range"): 2}


def test_a_recording_with_only_a_temperature_is_kept() -> None:
    samples = [Sample(t, temperature=20) for t in range(2)]
    r = _read(activity_fit(samples, record_fields=("timestamp", "temperature")))
    assert r.temperature is not None
    assert (r.position, r.elevation, r.heart_rate) == (None, None, None)


def test_relative_timestamps_are_absent() -> None:
    """Un horodatage relatif (inférieur à ``0x10000000``, une horloge non réglée) n'est
    pas un instant : fitdecode le laisse en entier, et le record est sans horodatage."""
    samples = [
        Sample(0, lat=45.0, lon=6.0, heart_rate=100),
        Sample(1, lat=45.0, lon=6.0, heart_rate=101, raw={"timestamp": 1000}),
        Sample(2, lat=45.0, lon=6.0, heart_rate=102),
    ]
    r = _read(activity_fit(samples))
    assert r.heart_rate is not None
    assert r.heart_rate.time_s == (0.0, 2.0)
    assert _counts(r) == {
        ("heart_rate", "no_timestamp"): 1,
        ("position", "no_timestamp"): 1,
    }


def test_a_field_defined_but_always_invalid_is_not_chosen() -> None:
    """Le champ amélioré compte s'il porte une valeur dans un record ; défini mais
    toujours invalide, il ne compte pas : le canal prend le champ de base."""
    samples = [Sample(t, altitude=1000.0 + t, speed=2.0) for t in range(3)]
    fields = ("timestamp", "enhanced_altitude", "altitude", "enhanced_speed", "speed")
    r = _read(activity_fit(samples, record_fields=fields))
    assert r.elevation is not None
    assert r.elevation.source_field is ElevationField.ALTITUDE
    assert r.elevation.elevation_m == (1000.0, 1001.0, 1002.0)
    assert r.speed is not None
    assert r.speed.source_field is SpeedField.SPEED
    assert r.discarded == ()
