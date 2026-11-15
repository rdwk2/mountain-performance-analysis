"""L'écrivain FIT des profils de démo (M5-3, § 6.2 (a) du brief, D6, D7), relu par le
vrai lecteur, ``read_fit`` (``ingest/fit.py``, extra ``ingest``)."""

from __future__ import annotations

import struct
from datetime import UTC, datetime, timedelta, timezone

import pytest

from mountain_perf.demo.fit import FitRecord, fit_activity_bytes, fit_file
from mountain_perf.schemas import SourceRef
from mountain_perf.validation import ContractError

TABLE = (
    0x0000, 0xCC01, 0xD801, 0x1400, 0xF001, 0x3C00, 0x2800, 0xE401,
    0xA001, 0x6C00, 0x7800, 0xB401, 0x5000, 0x9C01, 0x8801, 0x4400,
)  # fmt: skip
"""La table du CRC du § 6.2 (a), recopiée."""

START = datetime(2026, 11, 10, 8, 0, tzinfo=UTC)

RECORDS = (
    FitRecord(0, 0.0179864, -139.9910067, 1_200.0, 95.0, 0.0, 2.5),
    FitRecord(1, 0.0179865, -139.9909842, 1_200.4, 96.2, 2.5, 2.5),
    FitRecord(2, 0.0179866, -139.9909617, 1_200.9, 97.4, 5.0, 2.4),
)


def _crc(data: bytes) -> int:
    crc = 0
    for byte in data:
        for nibble in (byte & 0xF, byte >> 4):
            low = TABLE[crc & 0xF]
            crc = (crc >> 4) & 0x0FFF
            crc = crc ^ low ^ TABLE[nibble]
    return crc


def _source() -> SourceRef:
    return SourceRef(
        kind="garmin_fit",
        identifier="1_ACTIVITY.fit",
        content_hash="0" * 64,
        retrieved_at=START,
    )


def test_empty_file_header_and_crc() -> None:
    """L'en-tête d'un fichier vide de messages, son CRC et celui du fichier, contre le
    CRC calculé ici."""
    data = fit_file(b"")
    head = b"\x0e\x20\x54\x08\x00\x00\x00\x00.FIT"
    assert data[:12] == head
    assert data[12:14] == struct.pack("<H", _crc(head))
    assert data[14:] == struct.pack("<H", _crc(data[:14]))
    assert len(data) == 16


def test_every_field_of_a_fit_record() -> None:
    record = RECORDS[1]
    assert (
        record.elapsed_s,
        record.lat,
        record.lon,
        record.altitude_m,
        record.heart_rate,
        record.distance_m,
        record.speed_ms,
    ) == (1, 0.0179865, -139.9909842, 1_200.4, 96.2, 2.5, 2.5)


def test_read_fit_reads_three_records() -> None:
    pytest.importorskip("fitdecode")
    from mountain_perf.ingest.fit import read_fit

    data = fit_activity_bytes(START, RECORDS, timer_s=2.0, distance_m=5.0)
    recording = read_fit(data, activity_ref="1", source=_source())
    assert recording.start_time == START
    assert recording.position is not None
    assert recording.position.time_s == (0.0, 1.0, 2.0)
    for record, lat, lon in zip(
        RECORDS,
        recording.position.latitude_deg,
        recording.position.longitude_deg,
        strict=True,
    ):
        assert lat == pytest.approx(record.lat, abs=1e-6)
        assert lon == pytest.approx(record.lon, abs=1e-6)
    assert recording.elevation is not None
    for record, elevation in zip(RECORDS, recording.elevation.elevation_m, strict=True):
        assert elevation == pytest.approx(record.altitude_m, abs=0.2)
    assert recording.heart_rate is not None
    assert recording.heart_rate.heart_rate_bpm == (95.0, 96.0, 97.0)
    assert recording.distance is not None
    assert recording.distance.distance_m == pytest.approx((0.0, 2.5, 5.0))
    (session,) = recording.sessions
    assert (session.start_s, session.elapsed_duration_s) == (0.0, 2.0)
    assert (session.timer_duration_s, session.distance_m) == (2.0, 5.0)
    assert (session.sport, session.sub_sport) == ("running", "trail")
    assert recording.device.barometer is True
    assert recording.device.manufacturer == "development"
    assert recording.device.product == 0


def test_a_changed_crc_is_refused() -> None:
    pytest.importorskip("fitdecode")
    from mountain_perf.ingest.fit import FitRefusedError, read_fit

    data = bytearray(fit_activity_bytes(START, RECORDS, timer_s=2.0, distance_m=5.0))
    data[-1] ^= 0x01
    with pytest.raises(FitRefusedError):
        read_fit(bytes(data), activity_ref="1", source=_source())


def test_the_start_is_in_utc() -> None:
    paris = START.astimezone(timezone(timedelta(hours=1)))
    with pytest.raises(ContractError):
        fit_activity_bytes(paris, RECORDS, timer_s=2.0, distance_m=5.0)
    with pytest.raises(ContractError):
        fit_activity_bytes(
            START.replace(tzinfo=None), RECORDS, timer_s=2.0, distance_m=5.0
        )
