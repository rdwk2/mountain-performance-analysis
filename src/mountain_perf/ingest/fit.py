"""Le lecteur FIT de l'ingestion (AN1-1, ``docs/decisions/0011`` et ``0013``) : seul
module qui importe fitdecode (extra ``ingest``), et son unique enveloppe typée.

Les valeurs de fitdecode n'en sortent pas : ``read_fit`` rend un ``ActivityRecording``,
et chaque valeur lue passe par une petite conversion contrôlée (``isinstance``). Lecture
stricte : CRC et erreurs de décodage lèvent, un fichier refusé n'est jamais lu à moitié.
Ne lit ni numéro de série, ni numéro ANT, ni aucun identifiant d'appareil ou de capteur
(règle 1).
"""

import io
import math
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any

import fitdecode

from mountain_perf.schemas import (
    ELEVATION_RANGE_M,
    HEART_RATE_RANGE_BPM,
    LATITUDE_RANGE_DEG,
    LONGITUDE_RANGE_DEG,
    TEMPERATURE_RANGE_C,
    ActivityRecording,
    DeviceProvenance,
    DiscardCount,
    DiscardReason,
    DistanceChannel,
    ElevationChannel,
    ElevationField,
    HeartRateChannel,
    PositionChannel,
    RecordingPart,
    RecordingSession,
    RefusalReason,
    SourceRef,
    SpeedChannel,
    SpeedField,
    TemperatureChannel,
    TimerEvent,
    TimerEventType,
    TimerTrigger,
)

SEMICIRCLE_DEG = 180.0 / 2**31
"""Un semicercle en degrés : les positions du FIT sont en semicercles (``2**31`` pour
180°)."""

ELEVATION_SENTINEL_M = -500.0
"""L'altitude du brut 0 du FIT (``brut / 5 − 500``) : un zéro de codage, que des
écrivains de FIT emploient pour « pas de valeur »."""

_INF = float("inf")
_ABSENT = object()

Counts = Counter[tuple[RecordingPart, DiscardReason]]


class FitRefusedError(Exception):
    """Le FIT est refusé : pas d'enregistrement ; ``reason`` dit pourquoi."""

    def __init__(self, reason: RefusalReason) -> None:
        super().__init__(reason.value)
        self.reason = reason


@dataclass(frozen=True)
class _Message:
    """Un message de données, réduit à ce que le lecteur peut lire : les champs
    **écrits** (ni déduits, ni de développeur) par nom du profil, valeur de fitdecode
    (``None`` pour la valeur invalide) ; leur valeur brute par numéro ; l'horodatage,
    écrit ou déduit d'un en-tête compressé, s'il est un instant."""

    name: str
    written: Mapping[str, object]
    raw_by_number: Mapping[int, object]
    timestamp: datetime | None


def _message(frame: Any) -> _Message:
    written: dict[str, object] = {}
    raw_by_number: dict[int, object] = {}
    timestamp: object = _ABSENT
    for field in frame.fields:
        definition = field.field_def
        if definition is not None and definition.is_dev:
            continue
        name = str(field.name)
        if name == "timestamp" and timestamp is _ABSENT:
            timestamp = field.value
        if definition is None:
            continue
        written.setdefault(name, field.value)
        raw_by_number.setdefault(int(definition.def_num), field.raw_value)
    return _Message(
        name=str(frame.name),
        written=written,
        raw_by_number=raw_by_number,
        timestamp=timestamp if isinstance(timestamp, datetime) else None,
    )


def _decode(data: bytes) -> list[_Message]:
    """Les messages de données du FIT, dans l'ordre du fichier ; lecture stricte (CRC
    et erreurs de décodage en mode ``RAISE``) : toute ``fitdecode.FitError`` refuse le
    fichier ``UNREADABLE_FIT``."""
    try:
        with fitdecode.FitReader(
            io.BytesIO(data),
            check_crc=fitdecode.CrcCheck.RAISE,
            error_handling=fitdecode.ErrorHandling.RAISE,
        ) as reader:
            return [
                _message(frame)
                for frame in reader
                if isinstance(frame, fitdecode.FitDataMessage)
            ]
    except fitdecode.FitError:
        raise FitRefusedError(RefusalReason.UNREADABLE_FIT) from None


def _number(value: object) -> float | None:
    """Un nombre de fitdecode en flottant ; ``None`` pour la valeur invalide ou ce qui
    n'est pas un nombre."""
    if isinstance(value, bool) or not isinstance(value, int | float):
        return None
    return float(value)


def _text(value: object) -> str | None:
    """Le texte d'une valeur de fitdecode (``str()``), ``None`` pour la valeur invalide
    ou un texte blanc."""
    if value is None:
        return None
    text = str(value)
    return text if text.strip() else None


# ---------------------------------------------------------------------------
# Les canaux
# ---------------------------------------------------------------------------


class _Channel:
    """L'état d'un canal pendant la lecture : instants et valeurs gardés, et la valeur
    gardée à chaque instant (pour juger un doublon)."""

    def __init__(self, part: RecordingPart, counts: Counts) -> None:
        self.part = part
        self.counts = counts
        self.time_s: list[float] = []
        self.values: list[tuple[float, ...]] = []
        self.kept_at: dict[float, object] = {}

    def discard(self, reason: DiscardReason) -> None:
        self.counts[(self.part, reason)] += 1

    def place(self, time_s: float | None, key: object) -> bool:
        """Les règles d'instant, dans cet ordre : sans horodatage (``NO_TIMESTAMP``) ;
        avant le départ (``BEFORE_START``) ; instant qui ne suit pas strictement le
        dernier gardé : ``DUPLICATE`` si le canal a gardé à cet instant exactement la
        même valeur ``key``, sinon ``NOT_AFTER_PREVIOUS``. Vrai si l'instant passe."""
        if time_s is None:
            self.discard(DiscardReason.NO_TIMESTAMP)
            return False
        if time_s < 0:
            self.discard(DiscardReason.BEFORE_START)
            return False
        if self.time_s and time_s <= self.time_s[-1]:
            same = self.kept_at.get(time_s, _ABSENT) == key
            self.discard(
                DiscardReason.DUPLICATE if same else DiscardReason.NOT_AFTER_PREVIOUS
            )
            return False
        return True

    def keep(self, time_s: float, key: object, values: tuple[float, ...]) -> None:
        self.time_s.append(time_s)
        self.values.append(values)
        self.kept_at[time_s] = key

    def column(self, rank: int) -> tuple[float, ...]:
        return tuple(values[rank] for values in self.values)


def _in_range(value: float, low: float, high: float) -> bool:
    """Fini et dans ``[low, high]``, bornes comprises."""
    return math.isfinite(value) and low <= value <= high


def _offer_position(
    channel: _Channel, time_s: float | None, lat: float | None, lon: float | None
) -> None:
    """Une position brute (semicercles) : règles d'instant, puis demi-position
    (``HALF_POSITION``), zéro brut des deux coordonnées (``SENTINEL``), plage après
    conversion en degrés (``OUT_OF_RANGE``)."""
    key = (lat, lon)
    if not channel.place(time_s, key) or time_s is None:
        return
    if lat is None or lon is None:
        channel.discard(DiscardReason.HALF_POSITION)
        return
    if lat == 0 and lon == 0:
        channel.discard(DiscardReason.SENTINEL)
        return
    lat_deg, lon_deg = lat * SEMICIRCLE_DEG, lon * SEMICIRCLE_DEG
    if not (
        _in_range(lat_deg, *LATITUDE_RANGE_DEG)
        and _in_range(lon_deg, *LONGITUDE_RANGE_DEG)
    ):
        channel.discard(DiscardReason.OUT_OF_RANGE)
        return
    channel.keep(time_s, key, (lat_deg, lon_deg))


def _offer_value(
    channel: _Channel,
    time_s: float | None,
    value: float,
    low: float,
    high: float,
    *,
    sentinel: float | None = None,
    non_decreasing: bool = False,
) -> None:
    """Une valeur : règles d'instant, puis zéro brut (``SENTINEL``, altitude), plage
    (``OUT_OF_RANGE``), recul sous la dernière gardée (``DISTANCE_DECREASING``,
    distance)."""
    if not channel.place(time_s, value) or time_s is None:
        return
    if sentinel is not None and value == sentinel:
        channel.discard(DiscardReason.SENTINEL)
        return
    if not _in_range(value, low, high):
        channel.discard(DiscardReason.OUT_OF_RANGE)
        return
    if non_decreasing and channel.values and value < channel.values[-1][0]:
        channel.discard(DiscardReason.DISTANCE_DECREASING)
        return
    channel.keep(time_s, value, (value,))


@dataclass(frozen=True)
class _Choice:
    """Le champ retenu d'un canal à deux champs, et celui qu'il écarte."""

    kept: str
    other: str


def _choose(records: Sequence[_Message], enhanced: str, basic: str) -> _Choice:
    """Le champ amélioré si un record du fichier y écrit une valeur, sinon le champ de
    base (``docs/decisions/0013`` ; le champ déduit par fitdecode ne compte pas)."""
    if any(record.written.get(enhanced) is not None for record in records):
        return _Choice(enhanced, basic)
    return _Choice(basic, enhanced)


def _offer_choice(
    channel: _Channel,
    record: _Message,
    time_s: float | None,
    choice: _Choice,
    low: float,
    high: float,
    *,
    sentinel: float | None = None,
) -> None:
    """Le champ retenu suit les règles ; un record qui écrit l'autre champ sans écrire
    le champ retenu compte ``OTHER_FIELD``, sans aucune autre règle."""
    value = _number(record.written.get(choice.kept))
    if value is None:
        if _number(record.written.get(choice.other)) is not None:
            channel.discard(DiscardReason.OTHER_FIELD)
        return
    _offer_value(channel, time_s, value, low, high, sentinel=sentinel)


# ---------------------------------------------------------------------------
# Sessions, chronomètre, appareil
# ---------------------------------------------------------------------------


def _sessions(messages: Sequence[_Message]) -> tuple[datetime, list[RecordingSession]]:
    """Le départ (le plus ancien des sessions) et les sessions triées par départ (tri
    stable) ; aucune session, ou une session sans ``start_time`` : ``NO_SESSION``."""
    found = [message for message in messages if message.name == "session"]
    starts: list[datetime] = []
    for session in found:
        start = session.written.get("start_time")
        if not isinstance(start, datetime):
            raise FitRefusedError(RefusalReason.NO_SESSION)
        starts.append(start)
    if not starts:
        raise FitRefusedError(RefusalReason.NO_SESSION)
    origin = min(starts)
    sessions = [
        RecordingSession(
            sport=_text(session.written.get("sport")),
            sub_sport=_text(session.written.get("sub_sport")),
            start_s=(start - origin).total_seconds(),
            elapsed_duration_s=_number(session.written.get("total_elapsed_time")),
            timer_duration_s=_number(session.written.get("total_timer_time")),
            distance_m=_number(session.written.get("total_distance")),
        )
        for session, start in zip(found, starts, strict=True)
    ]
    return origin, sorted(sessions, key=lambda session: session.start_s)


def _timer_events(
    messages: Sequence[_Message], origin: datetime, counts: Counts
) -> list[TimerEvent]:
    """Les événements du chronomètre (messages ``event`` dont l'événement est
    ``timer`` ; les autres sont ignorés, sans compte). Écartés, dans cet ordre : sans
    horodatage (``NO_TIMESTAMP``) ; avant le départ (``BEFORE_START``) ; antérieur au
    dernier gardé (``NOT_AFTER_PREVIOUS`` ; deux événements au même instant sont
    gardés) ; type absent de ``TimerEventType`` (``UNKNOWN_TYPE``)."""
    types = {member.value for member in TimerEventType}
    triggers = {member.value for member in TimerTrigger}
    events: list[TimerEvent] = []
    for message in messages:
        if message.name != "event" or _text(message.written.get("event")) != "timer":
            continue
        part = RecordingPart.TIMER_EVENT
        if message.timestamp is None:
            counts[(part, DiscardReason.NO_TIMESTAMP)] += 1
            continue
        time_s = (message.timestamp - origin).total_seconds()
        if time_s < 0:
            counts[(part, DiscardReason.BEFORE_START)] += 1
            continue
        if events and time_s < events[-1].time_s:
            counts[(part, DiscardReason.NOT_AFTER_PREVIOUS)] += 1
            continue
        kind = _text(message.written.get("event_type"))
        if kind is None or kind not in types:
            counts[(part, DiscardReason.UNKNOWN_TYPE)] += 1
            continue
        trigger = _text(message.written.get("timer_trigger"))
        events.append(
            TimerEvent(
                time_s,
                TimerEventType(kind),
                TimerTrigger(trigger) if trigger in triggers else None,
            )
        )
    return events


def _device(messages: Sequence[_Message]) -> DeviceProvenance:
    """La provenance de l'appareil : le premier ``file_id`` (type, fabricant, numéro
    brut du champ 2, création), le premier ``device_info`` du créateur (version du
    logiciel), et les capteurs que décrivent les ``device_info``. Aucun numéro de série
    ni identifiant."""
    file_id = next((m for m in messages if m.name == "file_id"), None)
    infos = [message for message in messages if message.name == "device_info"]
    creator = next(
        (m for m in infos if _text(m.written.get("device_index")) == "creator"), None
    )
    product: int | None = None
    time_created: datetime | None = None
    if file_id is not None:
        raw = file_id.raw_by_number.get(2)
        if isinstance(raw, int) and not isinstance(raw, bool) and raw >= 0:
            product = raw
        created = file_id.written.get("time_created")
        time_created = created if isinstance(created, datetime) else None
    sources = [_text(m.written.get("source_type")) for m in infos]
    local_types = [
        _text(m.written.get("local_device_type"))
        for m, source in zip(infos, sources, strict=True)
        if source == "local"
    ]
    described = [kind for kind in local_types if kind is not None]
    barometer = None if not described else "barometer" in described
    external = any(
        (
            source == "antplus"
            and _text(m.written.get("antplus_device_type")) == "heart_rate"
        )
        or (
            source == "bluetooth_low_energy"
            and _text(m.written.get("ble_device_type")) == "heart_rate"
        )
        for m, source in zip(infos, sources, strict=True)
    )
    external_sensor: bool | None = external
    if not external and all(source is None for source in sources):
        external_sensor = None
    return DeviceProvenance(
        file_type=None if file_id is None else _text(file_id.written.get("type")),
        manufacturer=(
            None if file_id is None else _text(file_id.written.get("manufacturer"))
        ),
        product=product,
        time_created=time_created,
        software_version=(
            None
            if creator is None
            else _number(creator.written.get("software_version"))
        ),
        barometer=barometer,
        external_heart_rate_sensor=external_sensor,
    )


def read_fit(data: bytes, *, activity_ref: str, source: SourceRef) -> ActivityRecording:
    """L'enregistrement tiré des octets d'un FIT d'activité.

    - **Décodage strict** (``CrcCheck.RAISE``, ``ErrorHandling.RAISE``), messages de
      données seulement : toute ``fitdecode.FitError`` lève ``FitRefusedError``
      (``UNREADABLE_FIT``).
    - **Sessions** : chaque message ``session`` porte un ``start_time``, sinon (ou sans
      session) ``NO_SESSION`` ; le départ de l'enregistrement est le plus ancien, et
      tous les ``time_s`` en partent ; sessions triées par départ (tri stable).
    - **Champs** : reconnus par leur nom dans le profil de fitdecode (le produit, par
      son numéro) ; seuls les champs **écrits** comptent, jamais ceux que fitdecode
      déduit par expansion, sauf l'horodatage d'un en-tête compressé ; un champ écrit à
      sa valeur invalide n'est pas une valeur ; un horodatage qui n'est pas un instant
      (temps relatif d'une horloge non réglée) est absent ; les champs de développeur ne
      sont jamais lus.
    - **Altitude et vitesse** : ``enhanced_altitude`` (``enhanced_speed``) si un record
      du fichier y écrit une valeur, sinon ``altitude`` (``speed``) ; le champ retenu
      est dit ; un record qui écrit l'autre champ sans écrire le champ retenu compte
      ``OTHER_FIELD``, sans aucune autre règle.
    - **Écarts**, canal par canal, sur les records dans l'ordre du fichier, dans cet
      ordre : sans horodatage (``NO_TIMESTAMP``) ; avant le départ (``BEFORE_START``) ;
      instant qui ne suit pas strictement le dernier gardé du canal (``DUPLICATE`` si le
      canal a gardé à cet instant exactement la même valeur, brute en semicercles pour
      les positions ; sinon ``NOT_AFTER_PREVIOUS``) ; latitude sans longitude ou
      l'inverse (``HALF_POSITION``) ; zéro brut du codage (``SENTINEL`` : altitude de
      ``ELEVATION_SENTINEL_M``, quel que soit le champ retenu, ou latitude et longitude
      brutes toutes deux nulles) ; valeur non finie ou hors de la plage du contrat,
      positions converties en degrés (``OUT_OF_RANGE``) ; distance inférieure à la
      dernière gardée (``DISTANCE_DECREASING``). Un échantillon écarté ne devient
      jamais le dernier gardé ; les autres valeurs qui décroissent sont gardées ; un
      canal sans échantillon gardé est absent.
    - **Chronomètre** : voir ``_timer_events`` ; ``trigger`` est le sous-champ
      ``timer_trigger`` s'il est une valeur de ``TimerTrigger``, sinon ``None``.
    - Aucun échantillon gardé dans aucun canal : ``NO_SAMPLE``.
    - **Appareil** : ``DeviceProvenance`` (``barometer`` : vrai si un appareil interne
      est un baromètre, faux si des appareils internes ont un type sans qu'aucun en
      soit un, ``None`` sinon ; ``external_heart_rate_sensor`` : vrai pour un capteur de
      FC ANT+ ou Bluetooth Low Energy, faux si au moins un ``device_info`` a un
      ``source_type``, ``None`` sinon).
    - ``discarded`` : les comptes non nuls, triés par (valeur de la partie, valeur du
      motif).
    """
    messages = _decode(data)
    origin, sessions = _sessions(messages)
    records = [message for message in messages if message.name == "record"]
    altitude = _choose(records, "enhanced_altitude", "altitude")
    speed_choice = _choose(records, "enhanced_speed", "speed")
    counts: Counts = Counter()
    position = _Channel(RecordingPart.POSITION, counts)
    elevation = _Channel(RecordingPart.ELEVATION, counts)
    distance = _Channel(RecordingPart.DISTANCE, counts)
    heart_rate = _Channel(RecordingPart.HEART_RATE, counts)
    speed = _Channel(RecordingPart.SPEED, counts)
    temperature = _Channel(RecordingPart.TEMPERATURE, counts)
    for record in records:
        time_s = (
            None
            if record.timestamp is None
            else (record.timestamp - origin).total_seconds()
        )
        lat = _number(record.written.get("position_lat"))
        lon = _number(record.written.get("position_long"))
        if lat is not None or lon is not None:
            _offer_position(position, time_s, lat, lon)
        _offer_choice(
            elevation,
            record,
            time_s,
            altitude,
            *ELEVATION_RANGE_M,
            sentinel=ELEVATION_SENTINEL_M,
        )
        _offer_choice(speed, record, time_s, speed_choice, 0.0, _INF)
        value = _number(record.written.get("distance"))
        if value is not None:
            _offer_value(distance, time_s, value, 0.0, _INF, non_decreasing=True)
        value = _number(record.written.get("heart_rate"))
        if value is not None:
            _offer_value(heart_rate, time_s, value, *HEART_RATE_RANGE_BPM)
        value = _number(record.written.get("temperature"))
        if value is not None:
            _offer_value(temperature, time_s, value, *TEMPERATURE_RANGE_C)
    timer_events = _timer_events(messages, origin, counts)
    channels = (position, elevation, distance, heart_rate, speed, temperature)
    if not any(channel.time_s for channel in channels):
        raise FitRefusedError(RefusalReason.NO_SAMPLE)
    return ActivityRecording(
        activity_ref=activity_ref,
        start_time=origin,
        sessions=tuple(sessions),
        timer_events=tuple(timer_events),
        position=(
            PositionChannel(
                tuple(position.time_s), position.column(0), position.column(1)
            )
            if position.time_s
            else None
        ),
        elevation=(
            ElevationChannel(
                tuple(elevation.time_s),
                elevation.column(0),
                ElevationField(altitude.kept),
            )
            if elevation.time_s
            else None
        ),
        distance=(
            DistanceChannel(tuple(distance.time_s), distance.column(0))
            if distance.time_s
            else None
        ),
        heart_rate=(
            HeartRateChannel(tuple(heart_rate.time_s), heart_rate.column(0))
            if heart_rate.time_s
            else None
        ),
        speed=(
            SpeedChannel(
                tuple(speed.time_s), speed.column(0), SpeedField(speed_choice.kept)
            )
            if speed.time_s
            else None
        ),
        temperature=(
            TemperatureChannel(tuple(temperature.time_s), temperature.column(0))
            if temperature.time_s
            else None
        ),
        device=_device(messages),
        discarded=tuple(
            DiscardCount(part, reason, count)
            for (part, reason), count in sorted(
                counts.items(), key=lambda item: (item[0][0].value, item[0][1].value)
            )
        ),
        source=source,
    )
