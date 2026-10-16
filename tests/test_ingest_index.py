"""Le lecteur de l'index de l'export (``ingest/index.py``), sur des index inventés."""

from __future__ import annotations

import json
from datetime import timedelta
from typing import Any

import pytest

from mountain_perf.ingest.index import IndexReadError, IndexReadResult, read_index
from mountain_perf.schemas import IndexField, RefusalReason


def item(**changes: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "activityId": 501,
        "activityName": "nom inventé",
        "activityType": {"typeKey": "trail_running", "parentTypeId": 1},
        "startTimeLocal": "2024-03-09 09:30:00",
        "startTimeGMT": "2024-03-09 08:30:00",
        "elapsedDuration": 3723.5,
        "duration": 3600.0,
        "movingDuration": 3301.25,
        "distance": 10450.75,
        "elevationGain": 812.0,
        "elevationLoss": 798.0,
        "averageHR": 141.0,
        "maxHR": 173.0,
        "ownerId": 42,
        "deviceId": 7,
    }
    return {**base, **changes}


def read(*items: Any) -> IndexReadResult:
    return read_index(json.dumps(list(items)).encode())


def test_entry_fields_and_local_offset() -> None:
    result = read(item())
    assert result.refused == ()
    (e,) = result.entries
    assert e.activity_ref == "501"
    assert e.source_activity_type == "trail_running"
    assert e.start_time.utcoffset() == timedelta(hours=1)
    assert e.start_time.isoformat() == "2024-03-09T09:30:00+01:00"
    assert (e.elapsed_duration_s, e.moving_duration_s) == (3723.5, 3301.25)
    assert (e.distance_m, e.ascent_m, e.descent_m) == (10450.75, 812.0, 798.0)
    assert (e.average_hr_bpm, e.max_hr_bpm) == (141.0, 173.0)
    assert e.has_recording is False
    assert e.omitted_fields == ()


def test_duration_is_not_the_elapsed_time() -> None:
    """``duration`` est le temps du chronomètre ; l'écoulé est ``elapsedDuration``."""
    (e,) = read(item(duration=10.0)).entries
    assert e.elapsed_duration_s == 3723.5


def test_absent_and_null_fields_are_absent_not_omitted() -> None:
    raw = item(distance=None)
    del raw["elevationGain"]
    (e,) = read(raw).entries
    assert e.distance_m is None
    assert e.ascent_m is None
    assert e.omitted_fields == ()


@pytest.mark.parametrize(
    ("key", "value", "field"),
    [
        ("elapsedDuration", 0, IndexField.ELAPSED_DURATION),
        ("movingDuration", -1, IndexField.MOVING_DURATION),
        ("distance", "10", IndexField.DISTANCE),
        ("elevationGain", True, IndexField.ASCENT),
        ("elevationLoss", float("inf"), IndexField.DESCENT),
        ("averageHR", 19.5, IndexField.AVERAGE_HR),
        ("maxHR", 251, IndexField.MAX_HR),
    ],
)
def test_unusable_value_is_omitted(key: str, value: Any, field: IndexField) -> None:
    (e,) = read_index(
        json.dumps([item(**{key: value})], allow_nan=True).encode()
    ).entries
    assert e.omitted_fields == (field,)
    assert getattr(e, field.value) is None


def test_zero_moving_time_is_kept() -> None:
    (e,) = read(item(movingDuration=0)).entries
    assert e.moving_duration_s == 0.0


def test_omitted_fields_are_sorted() -> None:
    (e,) = read(item(maxHR=300, distance=-1)).entries
    assert e.omitted_fields == (IndexField.DISTANCE, IndexField.MAX_HR)


def test_omitted_fields_are_sorted_by_value_not_by_declaration() -> None:
    """``distance_m`` avant ``moving_duration_s`` : l'ordre des valeurs, que le contrat
    exige, et non celui de la déclaration d'``IndexField``."""
    (e,) = read(item(movingDuration=-1, distance=-1)).entries
    assert e.omitted_fields == (IndexField.DISTANCE, IndexField.MOVING_DURATION)


@pytest.mark.parametrize(
    "changes",
    [
        {"activityId": None},
        {"activityId": "absente"},
        {"activityId": "501"},
        {"activityId": True},
        {"activityId": -3},
        {"activityType": {"parentTypeId": 1}},
        {"activityType": {"typeKey": " "}},
        {"activityType": "trail_running"},
        {"startTimeLocal": None},
        {"startTimeGMT": "2024-03-09T08:30:00"},
        {
            "startTimeLocal": "2024-03-10 00:30:00",
            "startTimeGMT": "2024-03-09 08:30:00",
        },
    ],
)
def test_unusable_entry_is_refused(changes: dict[str, Any]) -> None:
    second = item(**{"activityId": 2, **changes})
    if second["activityId"] == "absente":
        del second["activityId"]
    result = read(item(activityId=1), second)
    assert [e.activity_ref for e in result.entries] == ["1"]
    assert [(r.position, r.reason) for r in result.refused] == [
        (1, RefusalReason.UNUSABLE_ENTRY)
    ]


def test_non_object_entry_is_refused() -> None:
    result = read(item(), 5)
    assert [(r.position, r.reason) for r in result.refused] == [
        (1, RefusalReason.UNUSABLE_ENTRY)
    ]


def test_duplicate_ids_refuse_every_occurrence() -> None:
    result = read(item(activityId=1), item(activityId=2), item(activityId=1, maxHR=150))
    assert [e.activity_ref for e in result.entries] == ["2"]
    assert [(r.position, r.reason) for r in result.refused] == [
        (0, RefusalReason.DUPLICATE_ENTRY),
        (2, RefusalReason.DUPLICATE_ENTRY),
    ]


def test_duplicate_wins_over_unusable() -> None:
    result = read(item(activityId=1), item(activityId=1, startTimeLocal=None))
    assert [r.reason for r in result.refused] == [RefusalReason.DUPLICATE_ENTRY] * 2


@pytest.mark.parametrize(
    "data", [b"{}", b"[", b"\xff\xfe"], ids=["objet", "tronque", "non-utf8"]
)
def test_index_must_be_a_json_list(data: bytes) -> None:
    with pytest.raises(IndexReadError):
        read_index(data)


def test_personal_fields_are_not_read() -> None:
    """Rien d'autre que les champs du § 5.5 n'est lu : les champs personnels de
    l'index, présents ou non, ne changent pas l'entrée."""
    personal = {
        "activityName": "nom inventé",
        "locationName": "lieu inventé",
        "ownerFullName": "personne inventée",
        "ownerDisplayName": "pseudo inventé",
        "description": "texte inventé",
        "ownerId": 42,
        "deviceId": 7,
    }
    bare = {k: v for k, v in item().items() if k not in personal}
    assert read(item(**personal)).entries == read(bare).entries
    (e,) = read(item(**personal)).entries
    assert "inventé" not in repr(e)


# --- compléments du balayage par mutation ----------------------------------------


def test_identifier_zero_is_usable() -> None:
    (e,) = read(item(activityId=0)).entries
    assert e.activity_ref == "0"


@pytest.mark.parametrize(
    ("local", "offset"),
    [
        ("2024-03-08 20:30:00", timedelta(hours=-12)),
        ("2024-03-09 22:30:00", timedelta(hours=14)),
        ("2024-03-09 14:00:00", timedelta(hours=5, minutes=30)),
    ],
)
def test_offset_bounds_and_any_offset(local: str, offset: timedelta) -> None:
    (e,) = read(item(startTimeLocal=local)).entries
    assert e.start_time.utcoffset() == offset
    assert e.start_time.strftime("%Y-%m-%d %H:%M:%S") == local


def test_heart_rate_bounds_are_kept() -> None:
    (e,) = read(item(averageHR=20, maxHR=250)).entries
    assert (e.average_hr_bpm, e.max_hr_bpm, e.omitted_fields) == (20.0, 250.0, ())


def test_entries_after_a_refused_one_are_read() -> None:
    result = read(item(activityId=1, startTimeLocal=None), item(activityId=2))
    assert [e.activity_ref for e in result.entries] == ["2"]


@pytest.mark.parametrize(
    ("data", "message"),
    [
        (b"{}", "activities.json : liste d'activités attendue."),
        (b"[", "activities.json : JSON en UTF-8 attendu."),
        (b"\xef\xbb\xbf[]", "activities.json : JSON en UTF-8 attendu."),
        ("[]".encode("utf-16"), "activities.json : JSON en UTF-8 attendu."),
    ],
    ids=["objet", "tronque", "marque-utf8", "utf16"],
)
def test_index_errors_have_exact_messages(data: bytes, message: str) -> None:
    with pytest.raises(IndexReadError) as error:
        read_index(data)
    assert str(error.value) == message


@pytest.mark.parametrize(
    ("value", "expected"),
    [(True, True), (False, False), (None, None)],
)
def test_elevation_corrected_is_read(value: Any, expected: bool | None) -> None:
    (e,) = read(item(elevationCorrected=value)).entries
    assert e.elevation_corrected is expected
    assert e.omitted_fields == ()


def test_elevation_corrected_absent_is_absent() -> None:
    (e,) = read(item()).entries
    assert e.elevation_corrected is None
    assert e.omitted_fields == ()


@pytest.mark.parametrize("value", ["true", 1, 0, 1.0, [True]])
def test_elevation_corrected_must_be_a_boolean(value: Any) -> None:
    (e,) = read(item(elevationCorrected=value, maxHR=251)).entries
    assert e.elevation_corrected is None
    assert e.omitted_fields == (IndexField.ELEVATION_CORRECTED, IndexField.MAX_HR)


def test_a_number_too_large_for_a_float_is_omitted() -> None:
    raw = json.dumps([item(distance=10**400)]).encode()
    (e,) = read_index(raw).entries
    assert e.distance_m is None
    assert e.omitted_fields == (IndexField.DISTANCE,)
