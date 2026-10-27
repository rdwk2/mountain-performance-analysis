"""Le lecteur de l'index d'un export,
``raw/garmin/<export>/activities/activities.json`` (AN1-1, AN2-0,
``docs/decisions/0013``).

Ne lit que les champs dont les contrats ont besoin : ni nom, ni titre, ni lieu, ni
identifiant d'utilisateur ou d'appareil (règle 1). ``duration`` (le temps du
chronomètre) n'est pas lu : le temps écoulé est ``elapsedDuration``
(``docs/PIEGES_DATA.md``).
"""

import json
import math
from collections import Counter
from dataclasses import dataclass
from datetime import UTC, datetime, timezone

from mountain_perf.schemas import (
    HEART_RATE_RANGE_BPM,
    UTC_OFFSET_RANGE_S,
    IndexedActivity,
    IndexField,
    RefusalReason,
    RefusedEntry,
    SourceRef,
)

_TIME_FORMAT = "%Y-%m-%d %H:%M:%S"

_INF = float("inf")

_NUMBER_FIELDS: tuple[tuple[IndexField, str, float, float, bool], ...] = (
    (IndexField.ELAPSED_DURATION, "elapsedDuration", 0.0, _INF, False),
    (IndexField.MOVING_DURATION, "movingDuration", 0.0, _INF, True),
    (IndexField.DISTANCE, "distance", 0.0, _INF, True),
    (IndexField.ASCENT, "elevationGain", 0.0, _INF, True),
    (IndexField.DESCENT, "elevationLoss", 0.0, _INF, True),
    (IndexField.AVERAGE_HR, "averageHR", *HEART_RATE_RANGE_BPM, True),
    (IndexField.MAX_HR, "maxHR", *HEART_RATE_RANGE_BPM, True),
    (IndexField.TRAINING_LOAD, "activityTrainingLoad", 0.0, _INF, True),
)
"""Champ, clé de la source, plage, borne basse comprise (``elapsedDuration > 0``)."""


class IndexReadError(ValueError):
    """L'index n'est pas une liste JSON en UTF-8 : rien ne s'en lit."""


@dataclass(frozen=True)
class IndexReadResult:
    """Ce que le lecteur tire de l'index.

    - ``entries`` — les entrées gardées, dans l'ordre de la source, sans
      enregistrement (``has_recording`` faux) ;
    - ``refused`` — les entrées refusées, par rang croissant.
    """

    entries: tuple[IndexedActivity, ...]
    refused: tuple[RefusedEntry, ...]


def _identifier(item: object) -> str | None:
    """``activityId`` entier ``>= 0`` (un booléen n'en est pas un), en texte décimal."""
    if not isinstance(item, dict):
        return None
    value = item.get("activityId")
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        return None
    return str(value)


def _type_key(item: dict[str, object]) -> str | None:
    activity_type = item.get("activityType")
    if not isinstance(activity_type, dict):
        return None
    key = activity_type.get("typeKey")
    if not isinstance(key, str) or not key.strip():
        return None
    return key


def _start(item: dict[str, object]) -> datetime | None:
    """L'instant de ``startTimeGMT``, dans le fuseau à décalage fixe que donne la
    différence entre ``startTimeLocal`` et ``startTimeGMT`` ; ``None`` si l'un des
    textes manque ou se lit mal, ou si le décalage sort de ``UTC_OFFSET_RANGE_S``."""
    local_text = item.get("startTimeLocal")
    gmt_text = item.get("startTimeGMT")
    if not isinstance(local_text, str) or not isinstance(gmt_text, str):
        return None
    try:
        local = datetime.strptime(local_text, _TIME_FORMAT)
        gmt = datetime.strptime(gmt_text, _TIME_FORMAT)
    except ValueError:
        return None
    offset = local - gmt
    low, high = UTC_OFFSET_RANGE_S
    if not low <= offset.total_seconds() <= high:
        return None
    return gmt.replace(tzinfo=UTC).astimezone(timezone(offset))


def _number(
    value: object, low: float, high: float, low_included: bool
) -> tuple[float | None, bool]:
    """``(valeur, omis)`` : ``(None, False)`` pour une clé absente ou ``null`` ; un
    booléen, une valeur non numérique, non finie, trop grande pour un flottant ou hors
    plage est omise."""
    if value is None:
        return None, False
    if isinstance(value, bool) or not isinstance(value, int | float):
        return None, True
    try:
        number = float(value)
    except OverflowError:
        return None, True
    if not math.isfinite(number):
        return None, True
    above_low = number >= low if low_included else number > low
    if not above_low or number > high:
        return None, True
    return number, False


def _entry(
    item: dict[str, object], ref: str, kind: str, start: datetime, source: SourceRef
) -> IndexedActivity:
    values: dict[IndexField, float | None] = {}
    omitted: list[IndexField] = []
    for field, key, low, high, low_included in _NUMBER_FIELDS:
        number, is_omitted = _number(item.get(key), low, high, low_included)
        values[field] = number
        if is_omitted:
            omitted.append(field)
    corrected = item.get("elevationCorrected")
    elevation_corrected: bool | None = None
    if isinstance(corrected, bool):
        elevation_corrected = corrected
    elif corrected is not None:
        omitted.append(IndexField.ELEVATION_CORRECTED)
    return IndexedActivity(
        activity_ref=ref,
        source_activity_type=kind,
        start_time=start,
        elapsed_duration_s=values[IndexField.ELAPSED_DURATION],
        moving_duration_s=values[IndexField.MOVING_DURATION],
        distance_m=values[IndexField.DISTANCE],
        ascent_m=values[IndexField.ASCENT],
        descent_m=values[IndexField.DESCENT],
        elevation_corrected=elevation_corrected,
        average_hr_bpm=values[IndexField.AVERAGE_HR],
        max_hr_bpm=values[IndexField.MAX_HR],
        training_load=values[IndexField.TRAINING_LOAD],
        has_recording=False,
        omitted_fields=tuple(sorted(omitted, key=lambda field: field.value)),
        source=source,
    )


def read_index(data: bytes, source: SourceRef) -> IndexReadResult:
    """Les entrées de l'index d'un export, lu depuis ses octets ; chaque entrée gardée
    porte ``source``, la provenance de ce fichier d'index (AN2-0).

    Les octets se décodent en UTF-8 strict puis en JSON (une marque d'ordre des octets
    en tête, ou de l'UTF-16, est refusée) : sinon ``IndexReadError``
    (« activities.json : JSON en UTF-8 attendu. ») ; un JSON qui n'est pas une liste :
    ``IndexReadError`` (« activities.json : liste d'activités attendue. »).

    Pour l'entrée de rang ``i``, dans cet ordre :

    1. l'identifiant est ``activityId``, entier ``>= 0`` (un booléen n'en est pas un),
       écrit en texte décimal ; s'il apparaît dans plusieurs entrées, chacune est
       refusée ``DUPLICATE_ENTRY``, avant tout autre contrôle ;
    2. une entrée qui n'est pas un objet, sans identifiant utilisable, sans
       ``activityType.typeKey`` texte non blanc, ou sans départ utilisable, est refusée
       ``UNUSABLE_ENTRY`` ;
    3. le départ : ``startTimeLocal`` et ``startTimeGMT``, textes au format
       ``%Y-%m-%d %H:%M:%S`` ; le décalage est leur différence, dans
       ``UTC_OFFSET_RANGE_S`` (bornes comprises) ; l'instant est ``startTimeGMT`` en
       UTC, exprimé dans le fuseau à décalage fixe (jamais le fuseau de la machine) ;
    4. les champs facultatifs ``elapsedDuration`` (``> 0``), ``movingDuration``,
       ``distance``, ``elevationGain``, ``elevationLoss``, ``activityTrainingLoad``
       (``>= 0``), ``averageHR``, ``maxHR`` (``HEART_RATE_RANGE_BPM``, bornes
       comprises) : clé absente ou ``null``,
       champ absent ; valeur non numérique (un booléen n'est pas un nombre), non finie,
       trop grande pour un flottant ou hors plage, champ absent et nommé dans
       ``omitted_fields`` ;
    5. ``elevationCorrected`` : un booléen, recopié ; absent ou ``null`` : absent ;
       toute autre valeur : absent et nommé dans ``omitted_fields``, trié par valeur
       d'``IndexField`` avec les autres champs omis.

    Les entrées gardées sont rendues dans l'ordre de la source, sans enregistrement ;
    les refusées, par rang croissant.
    """
    try:
        items = json.loads(data.decode("utf-8"))
    except ValueError:
        # UnicodeDecodeError, JSONDecodeError, et l'entier de plus de 4 300 chiffres.
        raise IndexReadError("activities.json : JSON en UTF-8 attendu.") from None
    if not isinstance(items, list):
        raise IndexReadError("activities.json : liste d'activités attendue.")
    refs = [_identifier(item) for item in items]
    counts = Counter(ref for ref in refs if ref is not None)
    entries: list[IndexedActivity] = []
    refused: list[RefusedEntry] = []
    for position, (item, ref) in enumerate(zip(items, refs, strict=True)):
        if ref is not None and counts[ref] > 1:
            refused.append(RefusedEntry(position, RefusalReason.DUPLICATE_ENTRY))
            continue
        if ref is None or not isinstance(item, dict):
            refused.append(RefusedEntry(position, RefusalReason.UNUSABLE_ENTRY))
            continue
        kind = _type_key(item)
        start = _start(item)
        if kind is None or start is None:
            refused.append(RefusedEntry(position, RefusalReason.UNUSABLE_ENTRY))
            continue
        entries.append(_entry(item, ref, kind, start, source))
    return IndexReadResult(tuple(entries), tuple(refused))
