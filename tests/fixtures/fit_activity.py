"""FIT d'activité synthétiques, écrits par ``fit_writer`` : de quoi exercer le lecteur
FIT de l'ingestion sans aucun FIT réel (règle 1).

Les valeurs sont données en unités du contrat (degrés, mètres, secondes) et converties
ici en valeurs brutes du profil FIT ; les tests du lecteur comparent aussi à des valeurs
brutes écrites en dur (``0011`` : une même erreur d'échelle des deux côtés ne passe
pas). Appareil inventé : fabricant 1, produit 999, logiciel 12,34.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

from fixtures.fit_writer import (
    BYTE,
    ENUM,
    SINT8,
    SINT32,
    STRING,
    UINT8,
    UINT16,
    UINT32,
    UINT32Z,
    DevFieldDef,
    FieldDef,
    FitWriter,
)

FIT_EPOCH = datetime(1989, 12, 31, tzinfo=UTC)
"""L'origine des instants FIT (``date_time``)."""

START = datetime(2024, 3, 9, 7, 30, tzinfo=UTC)
"""Départ par défaut des activités synthétiques (inventé)."""

# Numéros du profil FIT (messages, champs, valeurs).
FILE_ID, DEVICE_INFO, EVENT, RECORD, SESSION, ACTIVITY = 0, 23, 21, 20, 18, 34
DEVELOPER_DATA_ID, FIELD_DESCRIPTION = 207, 206
SPORTS = {"running": 1, "cycling": 2, "alpine_skiing": 13, "hiking": 17}
SUB_SPORTS = {"generic": 0, "trail": 3, "mountain": 8, "backcountry": 37}
TIMER_TYPES = {"start": 0, "stop": 1, "marker": 3, "stop_all": 4}
TIMER, COURSE_POINT = 0, 10
TIMER_TRIGGERS = {"manual": 0, "auto": 1, "fitness_equipment": 2}
SOURCE_ANTPLUS, SOURCE_BLE, SOURCE_LOCAL = 1, 3, 5
LOCAL_GPS, LOCAL_BAROMETER, LOCAL_WHR = 0, 4, 10
ANTPLUS_HEART_RATE, BLE_HEART_RATE, ANTPLUS_BIKE_POWER = 120, 1, 11

RECORD_FIELDS: dict[str, FieldDef] = {
    "timestamp": FieldDef(253, UINT32),
    "position_lat": FieldDef(0, SINT32),
    "position_long": FieldDef(1, SINT32),
    "altitude": FieldDef(2, UINT16),
    "heart_rate": FieldDef(3, UINT8),
    "distance": FieldDef(5, UINT32),
    "speed": FieldDef(6, UINT16),
    "enhanced_speed": FieldDef(73, UINT32),
    "enhanced_altitude": FieldDef(78, UINT32),
    "temperature": FieldDef(13, SINT8),
}


def fit_time(instant: datetime) -> int:
    """Un instant en secondes FIT."""
    return int((instant - FIT_EPOCH).total_seconds())


def semicircles(degrees: float) -> int:
    """Des degrés en semicercles (``2**31`` pour 180°)."""
    return round(degrees * 2**31 / 180)


def raw_altitude(metres: float) -> int:
    """Une altitude en valeur brute FIT : ``(m + 500) × 5``."""
    return round((metres + 500) * 5)


@dataclass(frozen=True)
class Sample:
    """Un message ``record`` : décalage depuis ``START`` (s) et valeurs en unités du
    contrat ; ``None`` écrit la valeur invalide du champ, s'il est défini.
    ``no_timestamp`` : le record s'écrit sans champ ``timestamp``, en-tête normal."""

    t_s: int
    lat: float | None = None
    lon: float | None = None
    enhanced_altitude: float | None = None
    altitude: float | None = None
    heart_rate: int | None = None
    distance: float | None = None
    enhanced_speed: float | None = None
    speed: float | None = None
    temperature: int | None = None
    raw: dict[str, int] = field(default_factory=dict)
    """Valeurs brutes imposées, par nom de champ (prioritaires)."""
    no_timestamp: bool = False


def _raw_record(sample: Sample, name: str, start: datetime) -> int | None:
    if name in sample.raw:
        return sample.raw[name]
    match name:
        case "timestamp":
            return fit_time(start + timedelta(seconds=sample.t_s))
        case "position_lat":
            return None if sample.lat is None else semicircles(sample.lat)
        case "position_long":
            return None if sample.lon is None else semicircles(sample.lon)
        case "enhanced_altitude" | "altitude":
            value = getattr(sample, name)
            return None if value is None else raw_altitude(value)
        case "heart_rate":
            return sample.heart_rate
        case "distance":
            return None if sample.distance is None else round(sample.distance * 100)
        case "enhanced_speed" | "speed":
            value = getattr(sample, name)
            return None if value is None else round(value * 1000)
        case "temperature":
            return sample.temperature
    raise ValueError(name)


def activity_fit(
    samples: Sequence[Sample],
    *,
    record_fields: Sequence[str] = (
        "timestamp",
        "position_lat",
        "position_long",
        "enhanced_altitude",
        "heart_rate",
        "distance",
        "enhanced_speed",
    ),
    start: datetime = START,
    sessions: Sequence[
        tuple[int | None, str, str | None, float | None, float, float]
    ] = ((0, "running", "trail", 60.0, 60.0, 100.0),),
    timer_events: Sequence[tuple[int | None, str]] = ((0, "start"), (60, "stop_all")),
    timer_triggers: Sequence[str | None] | None = None,
    other_events: Sequence[tuple[int, int, int]] = (),
    file_id: bool = True,
    manufacturer: int = 1,
    product: int | None = 999,
    time_created: bool = True,
    devices: Sequence[tuple[int, int | None]] = ((0, 1234),),
    sensors: Sequence[tuple[int, int | None, int | None]] = (),
    compressed_after: int | None = None,
    developer_field: bool = False,
    undeclared_developer: bool = False,
    corrupt_crc: bool = False,
) -> bytes:
    """Un FIT d'activité : ``file_id``, ``device_info``, événements, ``record`` (avec
    ``record_fields``), sessions (décalage, sport, sous-sport ou ``None``, temps écoulé,
    temps du chronomètre, distance ; un décalage ``None`` écrit un ``start_time``
    invalide, un temps écoulé ``None`` un ``total_elapsed_time`` invalide),
    ``activity``.

    ``timer_events`` : (décalage, type) ; un décalage ``None`` écrit l'événement sans
    horodatage. ``timer_triggers`` : un déclencheur par événement du chronomètre
    (``TIMER_TRIGGERS``, ou ``None`` pour la valeur invalide), écrit dans le champ
    ``data`` ; absent, les événements n'ont pas ce champ. ``other_events`` : (décalage,
    numéro d'événement, numéro de type), événements qui ne sont pas du chronomètre.
    ``devices`` : (``device_index``, logiciel en centièmes), ``device_index`` 0 étant le
    créateur. ``sensors`` : des ``device_info`` de capteurs, (``device_index``,
    ``source_type``, ``device_type``), valeurs brutes, ``None`` pour l'invalide.
    ``product`` ou ``time_created`` absents écrivent la valeur invalide.
    ``compressed_after`` : les records à partir de ce rang s'écrivent à horodatage
    compressé.
    ``developer_field`` : chaque record porte un champ de développeur déclaré ;
    ``undeclared_developer`` : il renvoie à un développeur jamais déclaré (erreur de
    décodage que seule la lecture stricte refuse). ``corrupt_crc`` : CRC faux.
    """
    w = FitWriter()
    if file_id:
        w.define(
            0,
            FILE_ID,
            (
                FieldDef(0, ENUM),
                FieldDef(1, UINT16),
                FieldDef(2, UINT16),
                FieldDef(3, UINT32Z),
                FieldDef(4, UINT32),
            ),
        )
        created = fit_time(start) if time_created else None
        w.data(0, (4, manufacturer, product, 4242, created))
    w.define(
        1, DEVICE_INFO, (FieldDef(253, UINT32), FieldDef(0, UINT8), FieldDef(5, UINT16))
    )
    for index, version in devices:
        w.data(1, (fit_time(start), index, version))
    if sensors:
        w.define(
            10,
            DEVICE_INFO,
            (
                FieldDef(253, UINT32),
                FieldDef(0, UINT8),
                FieldDef(25, ENUM),
                FieldDef(1, UINT8),
            ),
        )
        for index, source_type, device_type in sensors:
            w.data(10, (fit_time(start), index, source_type, device_type))
    data = () if timer_triggers is None else (FieldDef(3, UINT32),)
    w.define(
        2, EVENT, (FieldDef(253, UINT32), FieldDef(0, ENUM), FieldDef(1, ENUM), *data)
    )
    w.define(8, EVENT, (FieldDef(0, ENUM), FieldDef(1, ENUM), *data))
    triggers = (
        [()] * len(timer_events)
        if timer_triggers is None
        else [
            (None if name is None else TIMER_TRIGGERS[name],) for name in timer_triggers
        ]
    )
    for (offset, kind), trigger in zip(timer_events, triggers, strict=True):
        if offset is None:
            w.data(8, (TIMER, TIMER_TYPES[kind], *trigger))
        else:
            when = fit_time(start + timedelta(seconds=offset))
            w.data(2, (when, TIMER, TIMER_TYPES[kind], *trigger))
    for offset, event, event_type in other_events:
        when = fit_time(start + timedelta(seconds=offset))
        w.data(2, (when, event, event_type, *((None,) if data else ())))
    dev: tuple[DevFieldDef, ...] = ()
    if developer_field or undeclared_developer:
        if developer_field:
            w.define(4, DEVELOPER_DATA_ID, (FieldDef(3, UINT8), FieldDef(1, BYTE, 16)))
            w.data(4, (0, bytes(16)))
            w.define(
                4,
                FIELD_DESCRIPTION,
                (
                    FieldDef(0, UINT8),
                    FieldDef(1, UINT8),
                    FieldDef(2, UINT8),
                    FieldDef(3, STRING, 8),
                ),
            )
            w.data(4, (0, 0, 0x84, "essai"))
        dev = (DevFieldDef(0, 2, 0 if developer_field else 5),)
    dev_values = (b"\x07\x00",) if dev else ()
    w.define(5, RECORD, tuple(RECORD_FIELDS[name] for name in record_fields), dev)
    without_time = tuple(n for n in record_fields if n != "timestamp")
    w.define(9, RECORD, tuple(RECORD_FIELDS[n] for n in without_time), dev)
    for rank, sample in enumerate(samples):
        if compressed_after is not None and rank >= compressed_after:
            if rank == compressed_after:
                w.define(3, RECORD, tuple(RECORD_FIELDS[n] for n in without_time), dev)
            offset = fit_time(start + timedelta(seconds=sample.t_s)) & 0x1F
            w.data(
                3,
                tuple(_raw_record(sample, n, start) for n in without_time),
                dev_values,
                time_offset=offset,
            )
        elif sample.no_timestamp:
            w.data(
                9,
                tuple(_raw_record(sample, n, start) for n in without_time),
                dev_values,
            )
        else:
            w.data(
                5,
                tuple(_raw_record(sample, n, start) for n in record_fields),
                dev_values,
            )
    w.define(
        6,
        SESSION,
        (
            FieldDef(253, UINT32),
            FieldDef(2, UINT32),
            FieldDef(7, UINT32),
            FieldDef(8, UINT32),
            FieldDef(9, UINT32),
            FieldDef(5, ENUM),
            FieldDef(6, ENUM),
        ),
    )
    for offset, sport, sub_sport, elapsed, timer, distance in sessions:
        begin = start + timedelta(seconds=offset or 0)
        w.data(
            6,
            (
                fit_time(begin + timedelta(seconds=elapsed or timer)),
                None if offset is None else fit_time(begin),
                None if elapsed is None else round(elapsed * 1000),
                round(timer * 1000),
                round(distance * 100),
                SPORTS[sport],
                None if sub_sport is None else SUB_SPORTS[sub_sport],
            ),
        )
    w.define(7, ACTIVITY, (FieldDef(253, UINT32), FieldDef(1, UINT16)))
    w.data(7, (fit_time(start + timedelta(seconds=60)), len(sessions)))
    return w.to_bytes(corrupt_crc=corrupt_crc)
