"""L'écrivain FIT des profils de démo (M5-3, D6) : le sous-ensemble utile du protocole
FIT, bibliothèque standard seule (``struct``).

Un fichier : un en-tête de 14 octets suivi de son CRC, les messages (chacun précédé de
sa définition, une fois par type local, en petit-boutiste), le CRC du fichier. Une
activité : ``file_id`` (un seul appareil, fabricant de développement), deux
``device_info`` (le créateur et un **baromètre** interne, D7), le départ du
chronomètre, un ``record`` par seconde, l'arrêt, la ``session`` et l'``activity``.

Les nombres de ce module sont ceux du **format** (numéros de messages et de champs,
types de base, table du CRC, échelles, époque), nommés ici ; aucun n'est inventé.
Spécification : FIT Protocol, document du SDK de Garmin ; aucun code du SDK n'est
repris, ni l'écrivain des fixtures des tests (``tests/fixtures/fit_writer.py``).
"""

import struct
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Final

from mountain_perf.validation import ContractError, require_aware

HEADER_SIZE: Final = 14
"""La taille de l'en-tête d'un fichier FIT, CRC d'en-tête compris."""

PROTOCOL_VERSION: Final = 0x20
"""La version du protocole (2.0)."""

PROFILE_VERSION: Final = 2132
"""La version du profil (21.32)."""

DATA_TYPE: Final = b".FIT"
"""La signature de l'en-tête."""

CRC_TABLE: Final = (
    0x0000, 0xCC01, 0xD801, 0x1400, 0xF001, 0x3C00, 0x2800, 0xE401,
    0xA001, 0x6C00, 0x7800, 0xB401, 0x5000, 0x9C01, 0x8801, 0x4400,
)  # fmt: skip
"""La table du CRC-16 du protocole FIT, de 16 entrées."""

DEFINITION_FLAG: Final = 0x40
"""Le bit d'un en-tête de message de définition."""

LITTLE_ENDIAN: Final = 0
"""L'architecture petit-boutiste d'une définition."""

ENUM: Final = (0x00, "B")
UINT8: Final = (0x02, "B")
UINT16: Final = (0x84, "H")
SINT32: Final = (0x85, "i")
UINT32: Final = (0x86, "I")
"""Les types de base utilisés : (numéro, format ``struct``)."""

FIT_EPOCH: Final = datetime(1989, 12, 31, tzinfo=UTC)
"""L'époque des instants FIT."""

SEMICIRCLES_PER_180: Final = 2_147_483_648
"""Les semicercles d'un demi-tour (2³¹) : une position vaut ``degrés × 2³¹ / 180``."""

ALTITUDE_OFFSET_M: Final = 500
ALTITUDE_SCALE: Final = 5
"""L'échelle de ``enhanced_altitude`` : ``(m + 500) × 5``."""

DISTANCE_SCALE: Final = 100
"""L'échelle d'une distance : des centimètres."""

SPEED_SCALE: Final = 1000
"""L'échelle de ``enhanced_speed`` : des mm/s."""

DURATION_SCALE: Final = 1000
"""L'échelle d'une durée de session : des millisecondes."""

FILE_ID: Final = 0
SESSION: Final = 18
RECORD: Final = 20
EVENT: Final = 21
DEVICE_INFO: Final = 23
ACTIVITY: Final = 34
"""Les numéros globaux des messages écrits."""

TIMESTAMP: Final = 253
"""Le numéro du champ d'horodatage, commun aux messages."""

FILE_TYPE_ACTIVITY: Final = 4
MANUFACTURER_DEVELOPMENT: Final = 255
PRODUCT: Final = 0
SOURCE_TYPE_LOCAL: Final = 5
CREATOR_INDEX: Final = 0
BAROMETER_INDEX: Final = 1
LOCAL_DEVICE_GPS: Final = 0
LOCAL_DEVICE_BAROMETER: Final = 4
EVENT_TIMER: Final = 0
EVENT_TYPE_START: Final = 0
EVENT_TYPE_STOP_ALL: Final = 4
SPORT_RUNNING: Final = 1
SUB_SPORT_TRAIL: Final = 3
"""Les valeurs des énumérations du profil."""

_FILE_ID_FIELDS = ((0, ENUM), (1, UINT16), (2, UINT16), (4, UINT32))
_DEVICE_INFO_FIELDS = ((TIMESTAMP, UINT32), (0, UINT8), (25, ENUM), (1, UINT8))
_EVENT_FIELDS = ((TIMESTAMP, UINT32), (0, ENUM), (1, ENUM))
_RECORD_FIELDS = (
    (TIMESTAMP, UINT32),
    (0, SINT32),
    (1, SINT32),
    (78, UINT32),
    (3, UINT8),
    (5, UINT32),
    (73, UINT32),
)
_SESSION_FIELDS = (
    (TIMESTAMP, UINT32),
    (2, UINT32),
    (7, UINT32),
    (8, UINT32),
    (9, UINT32),
    (5, ENUM),
    (6, ENUM),
)
_ACTIVITY_FIELDS = ((TIMESTAMP, UINT32), (1, UINT16))


def fit_crc(data: bytes, crc: int = 0) -> int:
    """Le CRC-16 du protocole FIT de ``data``, à partir de ``crc``."""
    for byte in data:
        for nibble in (byte & 0xF, (byte >> 4) & 0xF):
            low = CRC_TABLE[crc & 0xF]
            crc = (crc >> 4) & 0x0FFF
            crc = crc ^ low ^ CRC_TABLE[nibble]
    return crc


def fit_file(body: bytes) -> bytes:
    """Un fichier FIT : l'en-tête de 14 octets et son CRC, les messages ``body``, le CRC
    du fichier (sur l'en-tête et les messages)."""
    head = struct.pack(
        "<BBHI4s", HEADER_SIZE, PROTOCOL_VERSION, PROFILE_VERSION, len(body), DATA_TYPE
    )
    head += struct.pack("<H", fit_crc(head))
    content = head + body
    return content + struct.pack("<H", fit_crc(content))


@dataclass(frozen=True)
class FitRecord:
    """Un enregistrement d'une seconde : le temps depuis le départ (secondes
    entières), la position en degrés, l'altitude en mètres, la FC en bpm, la distance
    depuis le départ en mètres, la vitesse horizontale en m/s."""

    elapsed_s: int
    lat: float
    lon: float
    altitude_m: float
    heart_rate: float
    distance_m: float
    speed_ms: float


class _Messages:
    """Les messages d'un fichier, chaque définition écrite une fois par type local."""

    def __init__(self) -> None:
        self.body = bytearray()
        self.fields: dict[int, tuple[tuple[int, tuple[int, str]], ...]] = {}

    def data(
        self,
        local: int,
        number: int,
        fields: tuple[tuple[int, tuple[int, str]], ...],
        values: Sequence[int],
    ) -> None:
        if local not in self.fields:
            self.body += struct.pack(
                "<BBBHB", DEFINITION_FLAG | local, 0, LITTLE_ENDIAN, number, len(fields)
            )
            for field, (base, fmt) in fields:
                self.body += struct.pack("<BBB", field, struct.calcsize(fmt), base)
            self.fields[local] = fields
        self.body += struct.pack("<B", local)
        for (_, (_, fmt)), value in zip(fields, values, strict=True):
            self.body += struct.pack("<" + fmt, value)


def _instant(moment: datetime) -> int:
    return (moment - FIT_EPOCH) // timedelta(seconds=1)


def _semicircles(degrees: float) -> int:
    return round(degrees * SEMICIRCLES_PER_180 / 180)


def fit_activity_bytes(
    start: datetime,
    records: Sequence[FitRecord],
    *,
    timer_s: float,
    distance_m: float,
) -> bytes:
    """Le FIT d'une activité de course à pied en trail : départ ``start`` (en UTC,
    sinon ``ContractError``), un ``record`` par enregistrement, la session de durée
    écoulée celle du dernier enregistrement, de chronomètre ``timer_s`` et de distance
    ``distance_m``."""
    if require_aware(start, "start") != timedelta(0):
        raise ContractError("start : le départ d'un FIT s'écrit en UTC.")
    if not records:
        raise ContractError("records : au moins un enregistrement.")
    begin = _instant(start)
    elapsed = records[-1].elapsed_s
    end = begin + elapsed
    messages = _Messages()
    messages.data(
        0,
        FILE_ID,
        _FILE_ID_FIELDS,
        (FILE_TYPE_ACTIVITY, MANUFACTURER_DEVELOPMENT, PRODUCT, begin),
    )
    for index, device in (
        (CREATOR_INDEX, LOCAL_DEVICE_GPS),
        (BAROMETER_INDEX, LOCAL_DEVICE_BAROMETER),
    ):
        messages.data(
            1,
            DEVICE_INFO,
            _DEVICE_INFO_FIELDS,
            (begin, index, SOURCE_TYPE_LOCAL, device),
        )
    messages.data(2, EVENT, _EVENT_FIELDS, (begin, EVENT_TIMER, EVENT_TYPE_START))
    for record in records:
        messages.data(
            3,
            RECORD,
            _RECORD_FIELDS,
            (
                begin + record.elapsed_s,
                _semicircles(record.lat),
                _semicircles(record.lon),
                round((record.altitude_m + ALTITUDE_OFFSET_M) * ALTITUDE_SCALE),
                round(record.heart_rate),
                round(record.distance_m * DISTANCE_SCALE),
                round(record.speed_ms * SPEED_SCALE),
            ),
        )
    messages.data(2, EVENT, _EVENT_FIELDS, (end, EVENT_TIMER, EVENT_TYPE_STOP_ALL))
    messages.data(
        4,
        SESSION,
        _SESSION_FIELDS,
        (
            end,
            begin,
            round(elapsed * DURATION_SCALE),
            round(timer_s * DURATION_SCALE),
            round(distance_m * DISTANCE_SCALE),
            SPORT_RUNNING,
            SUB_SPORT_TRAIL,
        ),
    )
    messages.data(5, ACTIVITY, _ACTIVITY_FIELDS, (end, 1))
    return fit_file(bytes(messages.body))
