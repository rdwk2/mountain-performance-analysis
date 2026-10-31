"""Les descripteurs de colonnes des familles journalières (AN2-1).

La lecture prend par position les colonnes de ``heartRateValues``,
``stressValuesArray``, ``bodyBatteryValuesArray`` (``stress``) et
``respirationValuesArray`` ; une liste de descripteurs présente et non vide doit dire
cette disposition, sinon le fichier est refusé (``unexpected_shape``). Les dispositions
sont écrites ici en dur : retirer une colonne de ``COLUMN_LAYOUTS`` fait rougir un test.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import pytest

from fixtures.families import (
    heart_rate_document,
    read,
    respiration_document,
    spo2_document,
    stress_document,
)
from mountain_perf.ingest.families import COLUMN_LAYOUTS
from mountain_perf.schemas import DayFamily, DayFileRefusal

SPEC_LAYOUTS = [
    (
        DayFamily.HEART_RATE,
        "heartRateValueDescriptors",
        "index",
        "key",
        {"timestamp": 0, "heartrate": 1},
        "heartRateValues",
    ),
    (
        DayFamily.STRESS,
        "stressValueDescriptorsDTOList",
        "index",
        "key",
        {"timestamp": 0, "stressLevel": 1},
        "stressValuesArray",
    ),
    (
        DayFamily.STRESS,
        "bodyBatteryValueDescriptorsDTOList",
        "bodyBatteryValueDescriptorIndex",
        "bodyBatteryValueDescriptorKey",
        {
            "timestamp": 0,
            "bodyBatteryStatus": 1,
            "bodyBatteryLevel": 2,
            "bodyBatteryVersion": 3,
        },
        "bodyBatteryValuesArray",
    ),
    (
        DayFamily.RESPIRATION,
        "respirationValueDescriptorsDTOList",
        "index",
        "key",
        {"timestamp": 0, "respiration": 1},
        "respirationValuesArray",
    ),
]
LAYOUT_IDS = ["heart_rate", "stress", "body_battery", "respiration"]

_DOCUMENTS: dict[DayFamily, Callable[[], dict[str, Any]]] = {
    DayFamily.HEART_RATE: heart_rate_document,
    DayFamily.STRESS: stress_document,
    DayFamily.RESPIRATION: respiration_document,
}
_SERIES = {
    "heartRateValues": "heart_rate",
    "stressValuesArray": "stress",
    "bodyBatteryValuesArray": "body_battery",
    "respirationValuesArray": "respiration",
}


def _descriptor(
    index_field: str, key_field: str, key: Any, index: Any
) -> dict[str, Any]:
    return {key_field: key, index_field: index}


def _read_with(
    family: DayFamily, path: str, descriptors: Any
) -> tuple[DayFileRefusal | None, Any]:
    document = _DOCUMENTS[family]()
    if descriptors == "absent":
        del document[path]
    else:
        document[path] = descriptors
    result = read(family, document)
    return result.refusal, result


def test_the_declared_layouts_are_those_of_the_brief() -> None:
    """``COLUMN_LAYOUTS`` porte exactement ces quatre dispositions, et aucune pour une
    autre famille (``spO2HourlyAverages`` n'a pas de descripteur)."""
    declared = [
        (
            family,
            layout.descriptors,
            layout.index_field,
            layout.key_field,
            dict(layout.columns),
        )
        for family, layouts in COLUMN_LAYOUTS.items()
        for layout in layouts
    ]
    assert declared == [spec[:5] for spec in SPEC_LAYOUTS]
    assert set(COLUMN_LAYOUTS) == {
        DayFamily.HEART_RATE,
        DayFamily.STRESS,
        DayFamily.RESPIRATION,
    }


@pytest.mark.parametrize(
    ("family", "path", "index_field", "key_field", "columns", "table"),
    SPEC_LAYOUTS,
    ids=LAYOUT_IDS,
)
def test_descriptors_that_say_the_read_layout_are_read_by_position(
    family: DayFamily,
    path: str,
    index_field: str,
    key_field: str,
    columns: dict[str, int],
    table: str,
) -> None:
    """La disposition lue, dans l'ordre des colonnes ou à rebours, avec un descripteur
    d'une autre clé en plus : le fichier se lit, sa série est là."""
    forward = [_descriptor(index_field, key_field, k, i) for k, i in columns.items()]
    extra = _descriptor(index_field, key_field, "invented", 9)
    for descriptors in (forward, [*reversed(forward), extra]):
        refusal, result = _read_with(family, path, descriptors)
        assert refusal is None
        assert getattr(result.day_series, _SERIES[table]) is not None


@pytest.mark.parametrize("value", [None, [], "absent"])
@pytest.mark.parametrize(
    ("family", "path", "index_field", "key_field", "columns", "table"),
    SPEC_LAYOUTS,
    ids=LAYOUT_IDS,
)
def test_without_descriptors_the_columns_are_read_by_position(
    family: DayFamily,
    path: str,
    index_field: str,
    key_field: str,
    columns: dict[str, int],
    table: str,
    value: Any,
) -> None:
    refusal, result = _read_with(family, path, value)
    assert refusal is None
    assert getattr(result.day_series, _SERIES[table]) is not None


@pytest.mark.parametrize(
    ("family", "path", "index_field", "key_field", "columns", "table"),
    SPEC_LAYOUTS,
    ids=LAYOUT_IDS,
)
def test_a_read_column_placed_elsewhere_refuses_the_file(
    family: DayFamily,
    path: str,
    index_field: str,
    key_field: str,
    columns: dict[str, int],
    table: str,
) -> None:
    """Chaque colonne lue, une à une, dite à un autre index : refus."""
    for moved in columns:
        descriptors = [
            _descriptor(index_field, key_field, k, i + 10 if k == moved else i)
            for k, i in columns.items()
        ]
        refusal, _ = _read_with(family, path, descriptors)
        assert refusal is DayFileRefusal.UNEXPECTED_SHAPE, moved


@pytest.mark.parametrize(
    ("family", "path", "index_field", "key_field", "columns", "table"),
    SPEC_LAYOUTS,
    ids=LAYOUT_IDS,
)
def test_two_read_columns_swapped_refuse_the_file(
    family: DayFamily,
    path: str,
    index_field: str,
    key_field: str,
    columns: dict[str, int],
    table: str,
) -> None:
    keys = list(columns)
    swapped = dict(columns)
    swapped[keys[0]], swapped[keys[1]] = columns[keys[1]], columns[keys[0]]
    descriptors = [
        _descriptor(index_field, key_field, k, i) for k, i in swapped.items()
    ]
    refusal, _ = _read_with(family, path, descriptors)
    assert refusal is DayFileRefusal.UNEXPECTED_SHAPE


@pytest.mark.parametrize(
    ("family", "path", "index_field", "key_field", "columns", "table"),
    SPEC_LAYOUTS,
    ids=LAYOUT_IDS,
)
def test_a_read_column_not_named_refuses_the_file(
    family: DayFamily,
    path: str,
    index_field: str,
    key_field: str,
    columns: dict[str, int],
    table: str,
) -> None:
    """Chaque colonne lue, une à une, absente d'une liste qui nomme les autres."""
    for missing in columns:
        descriptors = [
            _descriptor(index_field, key_field, k, i)
            for k, i in columns.items()
            if k != missing
        ]
        refusal, _ = _read_with(family, path, descriptors)
        assert refusal is DayFileRefusal.UNEXPECTED_SHAPE, missing


@pytest.mark.parametrize(
    ("index", "refused"),
    [(1, False), (1.0, False), (1.5, True), (True, True), (None, True), ("1", True)],
)
def test_the_index_is_read_by_its_value(index: Any, refused: bool) -> None:
    """Un index s'écrit en entier ou en flottant de valeur entière ; un flottant non
    entier, un booléen, ``null`` ou un texte ne disent pas la colonne : refus."""
    descriptors = [
        {"key": "timestamp", "index": 0},
        {"key": "heartrate", "index": index},
    ]
    refusal, _ = _read_with(
        DayFamily.HEART_RATE, "heartRateValueDescriptors", descriptors
    )
    assert (refusal is DayFileRefusal.UNEXPECTED_SHAPE) is refused


@pytest.mark.parametrize("item", [None, "timestamp", ["timestamp", 0]])
def test_a_descriptor_that_is_not_an_object_refuses_the_file(item: Any) -> None:
    """À côté de la disposition complète : un élément qui n'est pas un objet refuse le
    fichier, il n'est pas ignoré."""
    descriptors = [
        {"key": "timestamp", "index": 0},
        {"key": "heartrate", "index": 1},
        item,
    ]
    refusal, _ = _read_with(
        DayFamily.HEART_RATE, "heartRateValueDescriptors", descriptors
    )
    assert refusal is DayFileRefusal.UNEXPECTED_SHAPE


def test_a_list_of_descriptors_of_another_type_refuses_the_file() -> None:
    for value in ({"key": "timestamp"}, "timestamp", 3):
        refusal, _ = _read_with(
            DayFamily.HEART_RATE, "heartRateValueDescriptors", value
        )
        assert refusal is DayFileRefusal.UNEXPECTED_SHAPE


def test_a_key_of_another_type_is_another_key() -> None:
    """Un descripteur dont la clé n'est pas un texte ne nomme aucune colonne lue : la
    colonne qu'il remplace manque, refus ; à côté de la disposition complète, ignoré."""
    replaced = [{"key": "timestamp", "index": 0}, {"key": 1, "index": 1}]
    refusal, _ = _read_with(DayFamily.HEART_RATE, "heartRateValueDescriptors", replaced)
    assert refusal is DayFileRefusal.UNEXPECTED_SHAPE
    beside = [
        {"key": "timestamp", "index": 0},
        {"key": "heartrate", "index": 1},
        {"key": ["heartrate"], "index": 5},
    ]
    refusal, result = _read_with(
        DayFamily.HEART_RATE, "heartRateValueDescriptors", beside
    )
    assert refusal is None
    assert result.day_series.heart_rate is not None


def test_the_date_is_checked_before_the_descriptors() -> None:
    document = heart_rate_document()
    document["calendarDate"] = "2001-03-11"
    document["heartRateValueDescriptors"] = [{"key": "heartrate", "index": 7}]
    assert read(DayFamily.HEART_RATE, document).refusal is DayFileRefusal.DATE_MISMATCH


def test_the_spo2_descriptors_are_not_checked() -> None:
    """``spO2ValueDescriptorsDTOList`` décrit un tableau que la lecture ne lit pas ;
    ``spO2HourlyAverages`` n'a pas de descripteur : rien n'est contrôlé."""
    document = spo2_document()
    document["spO2ValueDescriptorsDTOList"] = [
        {"spo2ValueDescriptorIndex": 1, "spo2ValueDescriptorKey": "timestamp"},
        {"spo2ValueDescriptorIndex": 0, "spo2ValueDescriptorKey": "spo2Reading"},
    ]
    result = read(DayFamily.SPO2, document)
    assert result.refusal is None
    assert result.day_series.spo2 is not None


def test_the_respiration_averages_descriptors_are_not_checked() -> None:
    """``respirationAveragesValuesArray`` ne se lit pas : ses descripteurs ne se
    contrôlent pas."""
    document = respiration_document()
    document["respirationAveragesValueDescriptorDTOList"] = [
        {"respirationAverageValueDescriptorIndex": 3, "key": "timestamp"},
        "pas un descripteur",
    ]
    assert read(DayFamily.RESPIRATION, document).refusal is None


def test_the_fixture_documents_are_not_changed() -> None:
    """Les constructeurs rendent un document neuf à chaque appel (les tests ci-dessus
    les modifient)."""
    for make in (heart_rate_document, stress_document, respiration_document):
        first = make()
        first["mutated"] = True
        first[next(iter(first))] = "changé"
        assert "mutated" not in make()
        assert make() == make()
