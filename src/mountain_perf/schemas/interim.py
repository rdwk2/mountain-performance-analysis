"""Contrats d'``interim/`` (AN1-1, ``docs/decisions/0013``) : l'index des activités, et
l'enregistrement d'une activité, fidèles à la source, canal par canal ; le rapport de
la dernière ingestion.

``Activity`` et ``TrackPointStream`` (M1b) n'y sont pas écrits : ce sont des **vues**,
calculées à la lecture par ``mountain_perf.ingest.views``. Les documents s'écrivent et
se relisent par le codec commun (``mountain_perf.codec``), au format
``INTERIM_FORMAT_VERSION`` : d'où des ``tuple`` partout, jamais de ``frozenset`` ni de
``Sequence``, que le codec n'écrit pas.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timezone
from enum import StrEnum
from types import MappingProxyType

from mountain_perf.schemas.common import (
    ELEVATION_RANGE_M,
    HEART_RATE_RANGE_BPM,
    LATITUDE_RANGE_DEG,
    LONGITUDE_RANGE_DEG,
    UTC_OFFSET_RANGE_S,
    SourceRef,
)
from mountain_perf.validation import (
    ContractError,
    require_all_finite,
    require_all_in_range,
    require_aware,
    require_finite,
    require_immutable_sequence,
    require_in_range,
    require_increasing,
    require_min_length,
    require_non_empty,
    require_same_length,
)

INTERIM_FORMAT_VERSION = 1
"""Version du format des documents d'``interim/`` (``0013``, point 3).

Chaque document la porte. Elle change à chaque changement de forme d'un contrat de ce
module : le lecteur refuse un document d'un autre format, et ``interim/`` se régénère
depuis ``raw/`` (``0013``, Conséquences)."""

_REF = re.compile(r"[0-9A-Za-z_.-]+")


def require_activity_ref(ref: str, name: str = "activity_ref") -> None:
    """Un identifiant d'activité, qui sert de nom de fichier dans ``interim/`` :
    lettres et chiffres ASCII, ``_``, ``.``, ``-``, ni ``.`` ni ``..`` ; sinon
    ``ContractError``. La valeur n'est pas citée : elle vient de la source."""
    if not _REF.fullmatch(ref) or ref in (".", ".."):
        raise ContractError(
            f"{name} doit être fait de lettres et de chiffres ASCII, de « _ », « . » "
            "ou « - », et n'être ni « . » ni « .. »."
        )


def _require_optional_in_range(
    value: float | None, name: str, low: float, high: float = float("inf")
) -> None:
    if value is not None:
        require_finite(value, name)
        require_in_range(value, low, high, name)


def _require_strictly_sorted(keys: Sequence[tuple[object, ...]], name: str) -> None:
    """Refuse des clés non triées ou répétées : un document n'a qu'une écriture."""
    for i in range(1, len(keys)):
        if not keys[i - 1] < keys[i]:
            raise ContractError(
                f"{name} doit être trié sans doublon : rangs {i - 1} et {i}."
            )


# ---------------------------------------------------------------------------
# Énumérations
# ---------------------------------------------------------------------------


class ElevationField(StrEnum):
    """Champ du FIT d'où vient l'altitude d'un enregistrement.

    Champs
    ------
    Valeurs décrites dans ``ELEVATION_FIELD_DESCRIPTIONS``.

    Invariants
    ----------
    Énumération fermée : les deux champs d'altitude du profil FIT.

    Producteur
    ----------
    Le lecteur FIT de l'ingestion (``mountain_perf.ingest.fit``).

    Consommateurs
    -------------
    ``ElevationChannel`` ; tout consommateur qui veut savoir quelle résolution
    l'altitude a eue.

    Non promis
    ----------
    Rien sur la qualité de la mesure : un baromètre recalé et un GPS seul donnent le
    même champ.
    """

    ENHANCED_ALTITUDE = "enhanced_altitude"
    ALTITUDE = "altitude"


ELEVATION_FIELD_DESCRIPTIONS: Mapping[ElevationField, str] = MappingProxyType(
    {
        ElevationField.ENHANCED_ALTITUDE: (
            "Champ enhanced_altitude du message record, pris dès qu'un record du "
            "fichier y écrit une valeur autre que la valeur invalide du FIT (un champ "
            "déduit par le décodeur ne compte pas)."
        ),
        ElevationField.ALTITUDE: (
            "Champ altitude du message record, pris seulement quand aucun record du "
            "fichier n'écrit dans enhanced_altitude de valeur autre que la valeur "
            "invalide du FIT."
        ),
    }
)


class SpeedField(StrEnum):
    """Champ du FIT d'où vient la vitesse du capteur d'un enregistrement.

    Champs
    ------
    Valeurs décrites dans ``SPEED_FIELD_DESCRIPTIONS``.

    Invariants
    ----------
    Énumération fermée : les deux champs de vitesse du profil FIT.

    Producteur
    ----------
    Le lecteur FIT de l'ingestion.

    Consommateurs
    -------------
    ``SpeedChannel`` ; un diagnostic qui compare la vitesse du capteur à celle des
    positions.

    Non promis
    ----------
    La vitesse du capteur n'est pas la vitesse du moteur, qui se calcule sur les
    positions (``0013``, point 1).
    """

    ENHANCED_SPEED = "enhanced_speed"
    SPEED = "speed"


SPEED_FIELD_DESCRIPTIONS: Mapping[SpeedField, str] = MappingProxyType(
    {
        SpeedField.ENHANCED_SPEED: (
            "Champ enhanced_speed du message record, pris dès qu'un record du "
            "fichier y écrit une valeur autre que la valeur invalide du FIT (un champ "
            "déduit par le décodeur ne compte pas)."
        ),
        SpeedField.SPEED: (
            "Champ speed du message record, pris seulement quand aucun record du "
            "fichier n'écrit dans enhanced_speed de valeur autre que la valeur "
            "invalide du FIT."
        ),
    }
)


class TimerEventType(StrEnum):
    """Type d'un événement du chronomètre (message ``event`` du FIT dont l'événement
    est ``timer``).

    Champs
    ------
    Valeurs décrites dans ``TIMER_EVENT_TYPE_DESCRIPTIONS``.

    Invariants
    ----------
    Énumération fermée : les types que le profil FIT emploie pour démarrer et arrêter
    le chronomètre. Un événement du chronomètre d'un autre type est écarté et compté.

    Producteur
    ----------
    Le lecteur FIT de l'ingestion.

    Consommateurs
    -------------
    ``TimerEvent`` ; le diagnostic des trous et des pauses (``0013``, point 1).

    Non promis
    ----------
    Les nuances entre les types d'arrêt (``stop``, ``stop_all``, ``stop_disable``…)
    viennent de la montre et ne sont pas interprétées : tous arrêtent le chronomètre.
    """

    START = "start"
    STOP = "stop"
    STOP_ALL = "stop_all"
    STOP_DISABLE = "stop_disable"
    STOP_DISABLE_ALL = "stop_disable_all"


TIMER_EVENT_TYPE_DESCRIPTIONS: Mapping[TimerEventType, str] = MappingProxyType(
    {
        TimerEventType.START: "Démarrage ou reprise du chronomètre.",
        TimerEventType.STOP: "Arrêt du chronomètre.",
        TimerEventType.STOP_ALL: "Arrêt du chronomètre (et des autres minuteries).",
        TimerEventType.STOP_DISABLE: "Arrêt du chronomètre, désactivé ensuite.",
        TimerEventType.STOP_DISABLE_ALL: (
            "Arrêt de toutes les minuteries, désactivées ensuite."
        ),
    }
)


class TimerTrigger(StrEnum):
    """Ce qui a déclenché un événement du chronomètre (sous-champ ``timer_trigger`` du
    message ``event``).

    Champs
    ------
    Valeurs décrites dans ``TIMER_TRIGGER_DESCRIPTIONS``.

    Invariants
    ----------
    Énumération fermée : les déclencheurs du profil FIT.

    Producteur
    ----------
    Le lecteur FIT de l'ingestion.

    Consommateurs
    -------------
    ``TimerEvent`` ; le temps de mouvement et les montées (AN1-2) : une pause
    automatique se déclenche aussi quand l'athlète monte lentement.

    Non promis
    ----------
    Une montre peut ne pas l'écrire.
    """

    MANUAL = "manual"
    AUTO = "auto"
    FITNESS_EQUIPMENT = "fitness_equipment"


TIMER_TRIGGER_DESCRIPTIONS: Mapping[TimerTrigger, str] = MappingProxyType(
    {
        TimerTrigger.MANUAL: "Par l'athlète (bouton de la montre).",
        TimerTrigger.AUTO: (
            "Par la montre (pause automatique) : vitesse sous un seuil, sans que "
            "l'athlète soit forcément à l'arrêt."
        ),
        TimerTrigger.FITNESS_EQUIPMENT: "Par un appareil de fitness relié.",
    }
)


class RecordingPart(StrEnum):
    """Partie d'un enregistrement : un canal, ou les événements du chronomètre.

    Champs
    ------
    Valeurs décrites dans ``RECORDING_PART_DESCRIPTIONS``.

    Invariants
    ----------
    Énumération fermée.

    Producteur
    ----------
    Le lecteur FIT de l'ingestion, qui compte ce qu'il écarte (``DiscardCount``).

    Consommateurs
    -------------
    ``DiscardCount`` ; le rapport d'ingestion.

    Non promis
    ----------
    Une partie nommée ici peut manquer à un enregistrement.
    """

    POSITION = "position"
    ELEVATION = "elevation"
    DISTANCE = "distance"
    HEART_RATE = "heart_rate"
    SPEED = "speed"
    TEMPERATURE = "temperature"
    TIMER_EVENT = "timer_event"


RECORDING_PART_DESCRIPTIONS: Mapping[RecordingPart, str] = MappingProxyType(
    {
        RecordingPart.POSITION: "Canal des positions (latitude et longitude).",
        RecordingPart.ELEVATION: "Canal de l'altitude.",
        RecordingPart.DISTANCE: "Canal de la distance cumulée de la source.",
        RecordingPart.HEART_RATE: "Canal de la fréquence cardiaque.",
        RecordingPart.SPEED: "Canal de la vitesse du capteur.",
        RecordingPart.TEMPERATURE: "Canal de la température du capteur de la montre.",
        RecordingPart.TIMER_EVENT: "Événements du chronomètre.",
    }
)


class DiscardReason(StrEnum):
    """Motif pour lequel l'ingestion écarte un échantillon ou un événement.

    Champs
    ------
    Valeurs décrites dans ``DISCARD_REASON_DESCRIPTIONS``.

    Invariants
    ----------
    Énumération fermée. Le contrat est strict, l'ingestion tolérante et tracée : rien
    n'est corrigé en silence, tout écart est compté sous l'un de ces motifs
    (``0013``, point 5).

    Producteur
    ----------
    Le lecteur FIT de l'ingestion.

    Consommateurs
    -------------
    ``DiscardCount`` ; le rapport d'ingestion.

    Non promis
    ----------
    Un échantillon gardé n'est pas garanti juste : seulement conforme au contrat.
    """

    NO_TIMESTAMP = "no_timestamp"
    BEFORE_START = "before_start"
    DUPLICATE = "duplicate"
    NOT_AFTER_PREVIOUS = "not_after_previous"
    HALF_POSITION = "half_position"
    SENTINEL = "sentinel"
    OUT_OF_RANGE = "out_of_range"
    DISTANCE_DECREASING = "distance_decreasing"
    OTHER_FIELD = "other_field"
    UNKNOWN_TYPE = "unknown_type"


DISCARD_REASON_DESCRIPTIONS: Mapping[DiscardReason, str] = MappingProxyType(
    {
        DiscardReason.NO_TIMESTAMP: "Message sans horodatage : il ne se place pas.",
        DiscardReason.BEFORE_START: "Instant antérieur au départ de l'enregistrement.",
        DiscardReason.DUPLICATE: (
            "Instant qui ne suit pas strictement celui du dernier échantillon gardé du "
            "même canal, et valeur égale à celle que le canal a gardée à cet instant : "
            "la répétition d'une mesure gardée (sortie enregistrée deux fois)."
        ),
        DiscardReason.NOT_AFTER_PREVIOUS: (
            "Instant qui ne suit pas strictement celui du dernier échantillon gardé "
            "du même canal, hors doublon (pour un événement du chronomètre : antérieur "
            "au dernier gardé)."
        ),
        DiscardReason.HALF_POSITION: (
            "Latitude sans longitude, ou longitude sans latitude."
        ),
        DiscardReason.SENTINEL: (
            "Zéro brut du codage FIT, que des écrivains de FIT emploient pour « pas de "
            "valeur » : altitude de −500 m exactement, position (0°, 0°)."
        ),
        DiscardReason.OUT_OF_RANGE: (
            "Valeur non finie ou hors de la plage physique du canal."
        ),
        DiscardReason.DISTANCE_DECREASING: (
            "Distance inférieure à la dernière distance gardée."
        ),
        DiscardReason.OTHER_FIELD: (
            "Valeur écrite dans le champ que le canal n'a pas retenu : altitude quand "
            "le canal prend enhanced_altitude, speed quand il prend enhanced_speed."
        ),
        DiscardReason.UNKNOWN_TYPE: (
            "Événement du chronomètre d'un type absent de TimerEventType."
        ),
    }
)


class IndexField(StrEnum):
    """Champ facultatif de l'index qu'une valeur inutilisable a fait omettre.

    Champs
    ------
    Valeurs décrites dans ``INDEX_FIELD_DESCRIPTIONS``.

    Invariants
    ----------
    Énumération fermée : les champs facultatifs d'``IndexedActivity``.

    Producteur
    ----------
    Le lecteur de l'index de l'ingestion.

    Consommateurs
    -------------
    ``IndexedActivity.omitted_fields`` ; le rapport d'ingestion.

    Non promis
    ----------
    Un champ absent de la source n'est pas « omis » : il est seulement absent.
    """

    ELAPSED_DURATION = "elapsed_duration_s"
    MOVING_DURATION = "moving_duration_s"
    DISTANCE = "distance_m"
    ASCENT = "ascent_m"
    DESCENT = "descent_m"
    ELEVATION_CORRECTED = "elevation_corrected"
    AVERAGE_HR = "average_hr_bpm"
    MAX_HR = "max_hr_bpm"


INDEX_FIELD_DESCRIPTIONS: Mapping[IndexField, str] = MappingProxyType(
    {
        IndexField.ELAPSED_DURATION: "Temps écoulé (elapsedDuration).",
        IndexField.MOVING_DURATION: "Temps en mouvement (movingDuration).",
        IndexField.DISTANCE: "Distance de la source (distance).",
        IndexField.ASCENT: "D+ de la source (elevationGain).",
        IndexField.DESCENT: "D− de la source (elevationLoss).",
        IndexField.ELEVATION_CORRECTED: (
            "Altitude recalée par Garmin Connect (elevationCorrected)."
        ),
        IndexField.AVERAGE_HR: "FC moyenne (averageHR).",
        IndexField.MAX_HR: "FC maximale (maxHR).",
    }
)


class RefusalReason(StrEnum):
    """Motif pour lequel l'ingestion refuse un fichier ou une entrée de l'index.

    Champs
    ------
    Valeurs décrites dans ``REFUSAL_REASON_DESCRIPTIONS``.

    Invariants
    ----------
    Énumération fermée.

    Producteur
    ----------
    L'ingestion (``mountain_perf.ingest``).

    Consommateurs
    -------------
    ``RefusedFile``, ``RefusedEntry`` ; le rapport d'ingestion.

    Non promis
    ----------
    Le motif ne dit pas la cause matérielle (montre, export, transfert).
    """

    UNREADABLE_FIT = "unreadable_fit"
    NOT_ONE_FIT = "not_one_fit"
    DUPLICATE_ARCHIVE = "duplicate_archive"
    NO_SESSION = "no_session"
    NO_SAMPLE = "no_sample"
    NOT_IN_INDEX = "not_in_index"
    DUPLICATE_ENTRY = "duplicate_entry"
    UNUSABLE_ENTRY = "unusable_entry"


REFUSAL_REASON_DESCRIPTIONS: Mapping[RefusalReason, str] = MappingProxyType(
    {
        RefusalReason.UNREADABLE_FIT: (
            "FIT refusé par la lecture stricte : CRC faux, ou erreur de décodage."
        ),
        RefusalReason.NOT_ONE_FIT: (
            "Archive qui n'est pas un zip, qui n'a pas exactement un membre, dont le "
            "membre n'est pas un fichier .fit, ou dont le membre ne se lit pas."
        ),
        RefusalReason.DUPLICATE_ARCHIVE: (
            "Fichier de activity_fit/ dont le nom sans extension est celui d'un autre "
            "fichier : tous sont refusés."
        ),
        RefusalReason.NO_SESSION: (
            "FIT sans message session, ou dont une session n'est pas datée : "
            "l'enregistrement n'a pas de départ."
        ),
        RefusalReason.NO_SAMPLE: (
            "FIT dont aucun échantillon n'a été gardé : pas d'enregistrement."
        ),
        RefusalReason.NOT_IN_INDEX: "FIT dont l'activité n'est pas dans l'index.",
        RefusalReason.DUPLICATE_ENTRY: (
            "Entrée de l'index dont l'identifiant apparaît plus d'une fois : toutes "
            "ses entrées sont refusées."
        ),
        RefusalReason.UNUSABLE_ENTRY: (
            "Entrée de l'index sans identifiant, type ou départ utilisables."
        ),
    }
)


# ---------------------------------------------------------------------------
# L'index
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class IndexedActivity:
    """Une activité de l'index de l'export, telle que la source la décrit.

    Champs
    ------
    - ``activity_ref`` — sans unité — identifiant de l'activité dans la source.
    - ``source_activity_type`` — sans unité — type de la source, tel quel
      (``activityType.typeKey``).
    - ``start_time`` — instant — départ, *aware*, dans son fuseau local à décalage
      fixe (heure locale de la source moins son heure UTC).
    - ``elapsed_duration_s`` — secondes — temps écoulé, ``> 0``, si présent.
    - ``moving_duration_s`` — secondes — temps en mouvement, ``>= 0``, si présent.
    - ``distance_m`` — mètres — distance de la source, ``>= 0``, si présente.
    - ``ascent_m``, ``descent_m`` — mètres — D+ et D− de la source, ``>= 0``, si
      présents.
    - ``elevation_corrected`` — sans unité — vrai si Garmin Connect a recalé
      l'altitude de l'activité sur un modèle de terrain (``elevationCorrected``), si
      présent.
    - ``average_hr_bpm``, ``max_hr_bpm`` — battements par minute — FC moyenne et
      maximale, ``[20, 250]``, si présentes.
    - ``has_recording`` — sans unité — vrai si ``interim/`` porte l'enregistrement de
      cette activité.
    - ``omitted_fields`` — sans unité — champs présents dans la source mais omis ici,
      leur valeur étant inutilisable (non numérique, non finie ou hors plage).

    Invariants
    ----------
    - ``activity_ref`` : lettres et chiffres ASCII, ``_``, ``.``, ``-`` (il nomme le
      fichier de l'enregistrement) ;
    - ``source_activity_type`` non vide ;
    - ``start_time`` *aware*, décalage dans ``[-43200, 50400]`` s, ramené à un fuseau
      à décalage fixe ;
    - chaque champ facultatif présent est fini et dans sa plage ;
    - ``omitted_fields`` trié, sans doublon, et chaque champ omis est absent.

    Producteur
    ----------
    Le lecteur de l'index de l'ingestion (``mountain_perf.ingest.index``).

    Consommateurs
    -------------
    La vue ``Activity`` (``mountain_perf.ingest.views``) ; les tables d'analyse de la
    piste (AN1-2).

    Non promis
    ----------
    - aucun invariant entre champs : la FC moyenne peut dépasser la maximale, le
      temps en mouvement le temps écoulé (``0013``, point 1) ; la vue ``Activity`` les
      vérifie ;
    - ``distance_m`` est celle de la source, ni 2D ni 3D garantie ;
    - quand ``elevation_corrected`` est vrai, ``ascent_m`` et ``descent_m`` viennent du
      modèle de terrain de Garmin : ils ne se comparent pas au canal d'altitude de
      l'enregistrement, que la correction ne change pas ;
    - ``moving_duration_s`` est le temps en mouvement de Garmin (un algorithme non
      publié, à seuil de vitesse) : la piste calcule le sien ;
    - les valeurs ne sont pas recalculées depuis l'enregistrement.
    """

    activity_ref: str
    source_activity_type: str
    start_time: datetime
    elapsed_duration_s: float | None
    moving_duration_s: float | None
    distance_m: float | None
    ascent_m: float | None
    descent_m: float | None
    elevation_corrected: bool | None
    average_hr_bpm: float | None
    max_hr_bpm: float | None
    has_recording: bool
    omitted_fields: tuple[IndexField, ...]

    def __post_init__(self) -> None:
        require_activity_ref(self.activity_ref)
        require_non_empty(self.source_activity_type, "source_activity_type")
        offset = require_aware(self.start_time, "start_time")
        require_in_range(
            offset.total_seconds(), *UTC_OFFSET_RANGE_S, "décalage de start_time (s)"
        )
        object.__setattr__(
            self, "start_time", self.start_time.astimezone(timezone(offset))
        )
        if self.elapsed_duration_s is not None:
            require_finite(self.elapsed_duration_s, "elapsed_duration_s")
            if self.elapsed_duration_s <= 0:
                raise ContractError(
                    f"elapsed_duration_s doit être > 0, reçu {self.elapsed_duration_s}."
                )
        for name in ("moving_duration_s", "distance_m", "ascent_m", "descent_m"):
            _require_optional_in_range(getattr(self, name), name, 0.0)
        for name in ("average_hr_bpm", "max_hr_bpm"):
            _require_optional_in_range(getattr(self, name), name, *HEART_RATE_RANGE_BPM)
        require_immutable_sequence(self.omitted_fields, "omitted_fields")
        _require_strictly_sorted(
            [(field.value,) for field in self.omitted_fields], "omitted_fields"
        )
        for field in self.omitted_fields:
            if getattr(self, field.value) is not None:
                raise ContractError(
                    f"{field.value} est omis : il doit être absent (None)."
                )


@dataclass(frozen=True)
class ActivityIndex:
    """L'index des activités d'un export (document ``interim/activities/index.json``).

    Champs
    ------
    - ``entries`` — sans unité — les activités, triées par départ (instant) puis par
      identifiant.
    - ``source`` — sans unité — provenance : le fichier d'index de l'export, son
      empreinte, et l'instant d'acquisition de l'export.

    Invariants
    ----------
    - ``entries`` en tuple, identifiants uniques ;
    - ordre : instant de départ croissant, puis identifiant croissant à instant égal.

    Producteur
    ----------
    L'ingestion (``mountain_perf.ingest``).

    Consommateurs
    -------------
    Le lecteur d'``interim/`` ; la vue ``Activity`` ; les tables d'analyse (AN1-2).

    Non promis
    ----------
    - toutes les activités de l'export y sont, quel que soit leur type, sauf les
      entrées refusées (rapport d'ingestion) ;
    - ``source.retrieved_at`` est l'instant d'acquisition de l'export, jamais celui de
      l'ingestion ni d'une lecture (``0013``, point 5).
    """

    entries: tuple[IndexedActivity, ...]
    source: SourceRef

    def __post_init__(self) -> None:
        require_immutable_sequence(self.entries, "entries")
        _require_strictly_sorted(
            [
                (entry.start_time.timestamp(), entry.activity_ref)
                for entry in self.entries
            ],
            "entries (départ, identifiant)",
        )
        refs = [entry.activity_ref for entry in self.entries]
        if len(set(refs)) != len(refs):
            raise ContractError("entries : identifiant d'activité répété.")


# ---------------------------------------------------------------------------
# L'enregistrement
# ---------------------------------------------------------------------------


def _require_channel_times(time_s: tuple[float, ...]) -> None:
    require_immutable_sequence(time_s, "time_s")
    require_min_length(time_s, 1, "time_s")
    require_all_finite(time_s, "time_s")
    require_all_in_range(time_s, 0.0, float("inf"), "time_s")
    require_increasing(time_s, "time_s", strict=True)


def _require_values(
    values: tuple[float, ...], name: str, low: float, high: float = float("inf")
) -> None:
    require_immutable_sequence(values, name)
    require_all_finite(values, name)
    require_all_in_range(values, low, high, name)


@dataclass(frozen=True)
class PositionChannel:
    """Le canal des positions d'un enregistrement.

    Champs
    ------
    - ``time_s`` — secondes — depuis le départ de l'enregistrement.
    - ``latitude_deg``, ``longitude_deg`` — degrés — WGS84, convertis des
      semicercles du FIT à la lecture.

    Invariants
    ----------
    - tableaux en tuples, de même longueur, au moins un point, valeurs finies ;
    - ``time_s >= 0``, strictement croissant ;
    - coordonnées dans leurs plages.

    Producteur
    ----------
    Le lecteur FIT de l'ingestion.

    Consommateurs
    -------------
    La vue ``TrackPointStream`` ; les distances et profils, recalculés par
    ``gpx/geo.py`` et ``gpx/profile.py``.

    Non promis
    ----------
    Aucun pas régulier : un trou (signal perdu, chronomètre arrêté) reste un trou.
    """

    time_s: tuple[float, ...]
    latitude_deg: tuple[float, ...]
    longitude_deg: tuple[float, ...]

    def __post_init__(self) -> None:
        _require_channel_times(self.time_s)
        _require_values(self.latitude_deg, "latitude_deg", *LATITUDE_RANGE_DEG)
        _require_values(self.longitude_deg, "longitude_deg", *LONGITUDE_RANGE_DEG)
        require_same_length(
            time_s=self.time_s,
            latitude_deg=self.latitude_deg,
            longitude_deg=self.longitude_deg,
        )


@dataclass(frozen=True)
class ElevationChannel:
    """Le canal de l'altitude d'un enregistrement.

    Champs
    ------
    - ``time_s`` — secondes — depuis le départ de l'enregistrement.
    - ``elevation_m`` — mètres — altitude, ``[-500, 9000]``.
    - ``source_field`` — sans unité — le champ du FIT d'où elle vient.

    Invariants
    ----------
    - tableaux en tuples, de même longueur, au moins un point, valeurs finies ;
    - ``time_s >= 0``, strictement croissant ; altitudes dans leur plage.

    Producteur
    ----------
    Le lecteur FIT de l'ingestion.

    Consommateurs
    -------------
    La vue ``TrackPointStream`` ; les profils et les montées (AN1-2).

    Non promis
    ----------
    Ni lissage ni recalage : l'altitude est celle de la montre. Une correction
    d'altitude de Garmin Connect ne change pas le FIT
    (``IndexedActivity.elevation_corrected``).
    """

    time_s: tuple[float, ...]
    elevation_m: tuple[float, ...]
    source_field: ElevationField

    def __post_init__(self) -> None:
        _require_channel_times(self.time_s)
        _require_values(self.elevation_m, "elevation_m", *ELEVATION_RANGE_M)
        require_same_length(time_s=self.time_s, elevation_m=self.elevation_m)


@dataclass(frozen=True)
class DistanceChannel:
    """Le canal de la distance cumulée de la source.

    Champs
    ------
    - ``time_s`` — secondes — depuis le départ de l'enregistrement.
    - ``distance_m`` — mètres — distance cumulée calculée par la montre, ``>= 0``.

    Invariants
    ----------
    - tableaux en tuples, de même longueur, au moins un point, valeurs finies ;
    - ``time_s >= 0``, strictement croissant ;
    - ``distance_m >= 0``, croissante au sens large.

    Producteur
    ----------
    Le lecteur FIT de l'ingestion.

    Consommateurs
    -------------
    La vue ``TrackPointStream`` ; des diagnostics (distance de la montre contre
    distance des positions).

    Non promis
    ----------
    Ni 2D ni 3D garantie ; la distance du moteur se recalcule sur les positions
    (``0013``, point 2). Un pic isolé fait écarter la suite jusqu'à ce que la distance
    le dépasse (``distance_decreasing`` le compte) : ce canal ne sert qu'au diagnostic.
    """

    time_s: tuple[float, ...]
    distance_m: tuple[float, ...]

    def __post_init__(self) -> None:
        _require_channel_times(self.time_s)
        _require_values(self.distance_m, "distance_m", 0.0)
        require_increasing(self.distance_m, "distance_m", strict=False)
        require_same_length(time_s=self.time_s, distance_m=self.distance_m)


@dataclass(frozen=True)
class HeartRateChannel:
    """Le canal de la fréquence cardiaque d'un enregistrement.

    Champs
    ------
    - ``time_s`` — secondes — depuis le départ de l'enregistrement.
    - ``heart_rate_bpm`` — battements par minute — FC, ``[20, 250]``.

    Invariants
    ----------
    - tableaux en tuples, de même longueur, au moins un point, valeurs finies ;
    - ``time_s >= 0``, strictement croissant ; FC dans sa plage.

    Producteur
    ----------
    Le lecteur FIT de l'ingestion.

    Consommateurs
    -------------
    La vue ``TrackPointStream`` ; les tables d'analyse (AN1-2).

    Non promis
    ----------
    Le capteur (poignet ou ceinture) n'est pas dit.
    """

    time_s: tuple[float, ...]
    heart_rate_bpm: tuple[float, ...]

    def __post_init__(self) -> None:
        _require_channel_times(self.time_s)
        _require_values(self.heart_rate_bpm, "heart_rate_bpm", *HEART_RATE_RANGE_BPM)
        require_same_length(time_s=self.time_s, heart_rate_bpm=self.heart_rate_bpm)


@dataclass(frozen=True)
class SpeedChannel:
    """Le canal de la vitesse du capteur, pour diagnostic.

    Champs
    ------
    - ``time_s`` — secondes — depuis le départ de l'enregistrement.
    - ``speed_ms`` — m/s — vitesse mesurée par la montre, ``>= 0``.
    - ``source_field`` — sans unité — le champ du FIT d'où elle vient.

    Invariants
    ----------
    - tableaux en tuples, de même longueur, au moins un point, valeurs finies ;
    - ``time_s >= 0``, strictement croissant ; ``speed_ms >= 0``.

    Producteur
    ----------
    Le lecteur FIT de l'ingestion.

    Consommateurs
    -------------
    La vue ``TrackPointStream`` (``speed_ms``), pour diagnostic.

    Non promis
    ----------
    Le moteur calcule la vitesse sur les positions ; celle-ci ne sert qu'au diagnostic
    (``0013``, point 1).
    """

    time_s: tuple[float, ...]
    speed_ms: tuple[float, ...]
    source_field: SpeedField

    def __post_init__(self) -> None:
        _require_channel_times(self.time_s)
        _require_values(self.speed_ms, "speed_ms", 0.0)
        require_same_length(time_s=self.time_s, speed_ms=self.speed_ms)


TEMPERATURE_RANGE_C: tuple[float, float] = (-60.0, 80.0)
"""Plage d'une température de capteur porté, en °C : large, elle écarte les valeurs
impossibles, pas les valeurs rares (grand froid, boîtier au soleil)."""


@dataclass(frozen=True)
class TemperatureChannel:
    """Le canal de la température du capteur de la montre.

    Champs
    ------
    - ``time_s`` — secondes — depuis le départ de l'enregistrement.
    - ``temperature_c`` — °C — température du capteur, dans ``TEMPERATURE_RANGE_C``.

    Invariants
    ----------
    - tableaux en tuples, de même longueur, au moins un point, valeurs finies ;
    - ``time_s >= 0``, strictement croissant ; températures dans leur plage.

    Producteur
    ----------
    Le lecteur FIT de l'ingestion.

    Consommateurs
    -------------
    La charge thermique (charte, § 12 ; Q10) ; les tables d'analyse.

    Non promis
    ----------
    Ce n'est pas la température de l'air : le capteur est chauffé par le corps, et
    l'effort la fait monter. La vue ``TrackPointStream`` ne la porte pas.
    """

    time_s: tuple[float, ...]
    temperature_c: tuple[float, ...]

    def __post_init__(self) -> None:
        _require_channel_times(self.time_s)
        _require_values(self.temperature_c, "temperature_c", *TEMPERATURE_RANGE_C)
        require_same_length(time_s=self.time_s, temperature_c=self.temperature_c)


@dataclass(frozen=True)
class RecordingSession:
    """Une session du FIT (message ``session``) : un FIT multisport en a plusieurs.

    Champs
    ------
    - ``sport``, ``sub_sport`` — sans unité — sport et sous-sport du FIT, tels quels,
      si présents.
    - ``start_s`` — secondes — départ de la session depuis le départ de
      l'enregistrement, ``>= 0``.
    - ``elapsed_duration_s`` — secondes — temps écoulé (``total_elapsed_time``),
      ``>= 0``, si présent.
    - ``timer_duration_s`` — secondes — temps du chronomètre (``total_timer_time``),
      ``>= 0``, si présent.
    - ``distance_m`` — mètres — distance totale (``total_distance``), ``>= 0``, si
      présente.

    Invariants
    ----------
    Textes non vides s'ils sont présents ; nombres finis et dans leurs plages.

    Producteur
    ----------
    Le lecteur FIT de l'ingestion.

    Consommateurs
    -------------
    Le diagnostic des pauses (temps écoulé contre temps du chronomètre) ; les tables
    d'analyse (AN1-2).

    Non promis
    ----------
    Aucun invariant entre champs (le chronomètre peut dépasser l'écoulé dans un
    fichier abîmé) ; ``sport`` n'est pas le ``Sport`` du moteur ; une session peut
    se répéter (un FIT chaîné) : des sessions qui se chevauchent ne se somment pas.
    """

    sport: str | None
    sub_sport: str | None
    start_s: float
    elapsed_duration_s: float | None
    timer_duration_s: float | None
    distance_m: float | None

    def __post_init__(self) -> None:
        for name in ("sport", "sub_sport"):
            text: str | None = getattr(self, name)
            if text is not None:
                require_non_empty(text, name)
        require_finite(self.start_s, "start_s")
        require_in_range(self.start_s, 0.0, float("inf"), "start_s")
        for name in ("elapsed_duration_s", "timer_duration_s", "distance_m"):
            _require_optional_in_range(getattr(self, name), name, 0.0)


@dataclass(frozen=True)
class TimerEvent:
    """Un démarrage ou un arrêt du chronomètre.

    Champs
    ------
    - ``time_s`` — secondes — depuis le départ de l'enregistrement, ``>= 0``.
    - ``event_type`` — sans unité — démarrage ou type d'arrêt.
    - ``trigger`` — sans unité — ce qui l'a déclenché, si le fichier le dit.

    Invariants
    ----------
    ``time_s`` fini et ``>= 0``.

    Producteur
    ----------
    Le lecteur FIT de l'ingestion.

    Consommateurs
    -------------
    Le diagnostic des trous (``0013``, point 1) ; les horloges de la piste (AN1-2).

    Non promis
    ----------
    Une suite d'événements n'est pas garantie alternée (démarrage, arrêt…) : elle est
    celle de la montre. Une pause automatique (``TimerTrigger.AUTO``) n'est pas un
    arrêt de l'athlète : en montée raide et lente, il peut monter pendant qu'elle dure.
    """

    time_s: float
    event_type: TimerEventType
    trigger: TimerTrigger | None

    def __post_init__(self) -> None:
        require_finite(self.time_s, "time_s")
        require_in_range(self.time_s, 0.0, float("inf"), "time_s")


@dataclass(frozen=True)
class DeviceProvenance:
    """La provenance de l'appareil qui a écrit le FIT, sans identifiant.

    Champs
    ------
    - ``file_type`` — sans unité — type du fichier (``file_id.type``), si présent.
    - ``manufacturer`` — sans unité — fabricant (``file_id.manufacturer``), si
      présent.
    - ``product`` — sans unité — numéro de produit (``file_id.product``, valeur
      brute), si présent.
    - ``time_created`` — instant — création du fichier, stocké en UTC, si présent.
    - ``software_version`` — sans unité — version du logiciel de l'appareil créateur
      (``device_info`` de l'appareil ``creator``), si présente.
    - ``barometer`` — sans unité — vrai si un ``device_info`` interne (``source_type``
      ``local``) est un baromètre ; faux si le fichier décrit des capteurs internes,
      sans baromètre ; absent s'il n'en décrit aucun.
    - ``external_heart_rate_sensor`` — sans unité — vrai si un ``device_info`` décrit
      un capteur de FC ANT+ ou Bluetooth Low Energy ; faux si le fichier décrit des
      appareils (un ``source_type`` au moins), sans un tel capteur ; absent s'il n'en
      décrit aucun.

    Invariants
    ----------
    - textes non vides s'ils sont présents ; ``product >= 0`` ;
    - ``time_created`` *aware*, ramené en UTC ;
    - ``software_version`` finie et ``>= 0``.

    Producteur
    ----------
    Le lecteur FIT de l'ingestion.

    Consommateurs
    -------------
    Le contrôle des changements de firmware (charte, § 11) ; la provenance.

    Non promis
    ----------
    **Ni numéro de série ni identifiant de l'appareil, ni d'un capteur** (``0013``,
    point 1 ; règle 1) ; le produit n'est pas traduit en nom de modèle. Un capteur
    présent n'a pas forcément mesuré chaque échantillon : la montre repasse à sa propre
    FC quand la ceinture décroche, et une montre qui ne décrit pas ses capteurs n'en est
    pas dépourvue.
    """

    file_type: str | None
    manufacturer: str | None
    product: int | None
    time_created: datetime | None
    software_version: float | None
    barometer: bool | None
    external_heart_rate_sensor: bool | None

    def __post_init__(self) -> None:
        for name in ("file_type", "manufacturer"):
            text: str | None = getattr(self, name)
            if text is not None:
                require_non_empty(text, name)
        if self.product is not None and self.product < 0:
            raise ContractError(f"product doit être >= 0, reçu {self.product}.")
        if self.time_created is not None:
            require_aware(self.time_created, "time_created")
            object.__setattr__(self, "time_created", self.time_created.astimezone(UTC))
        _require_optional_in_range(self.software_version, "software_version", 0.0)


@dataclass(frozen=True)
class DiscardCount:
    """Le nombre d'échantillons ou d'événements qu'une partie a perdus pour un motif.

    Champs
    ------
    - ``part`` — sans unité — le canal, ou les événements du chronomètre.
    - ``reason`` — sans unité — le motif.
    - ``count`` — sans unité — le nombre écarté, ``> 0``.

    Invariants
    ----------
    ``count > 0``.

    Producteur
    ----------
    Le lecteur FIT de l'ingestion.

    Consommateurs
    -------------
    ``ActivityRecording.discarded`` ; le rapport d'ingestion.

    Non promis
    ----------
    Les instants écartés ne sont pas listés.
    """

    part: RecordingPart
    reason: DiscardReason
    count: int

    def __post_init__(self) -> None:
        if self.count <= 0:
            raise ContractError(f"count doit être > 0, reçu {self.count}.")


@dataclass(frozen=True)
class ActivityRecording:
    """L'enregistrement d'une activité, tiré de son FIT (document
    ``interim/activities/recordings/<activity_ref>.json``).

    Champs
    ------
    - ``activity_ref`` — sans unité — l'activité de l'index.
    - ``start_time`` — instant — départ de l'enregistrement : celui de la première
      session, stocké en UTC ; tous les ``time_s`` en partent.
    - ``sessions`` — sans unité — les sessions du FIT, dans l'ordre du temps.
    - ``timer_events`` — sans unité — démarrages et arrêts du chronomètre.
    - ``position``, ``elevation``, ``distance``, ``heart_rate``, ``speed``,
      ``temperature`` — sans unité — les canaux ; un canal absent du fichier est
      absent (``None``).
    - ``device`` — sans unité — provenance de l'appareil.
    - ``discarded`` — sans unité — ce que l'ingestion a écarté, par partie et motif.
    - ``source`` — sans unité — provenance : l'archive du FIT dans l'export, son
      empreinte, et l'instant d'acquisition de l'export.

    Invariants
    ----------
    - ``activity_ref`` : lettres et chiffres ASCII, ``_``, ``.``, ``-`` ;
    - ``start_time`` *aware*, ramené en UTC ;
    - au moins une session ; la première part à ``0`` ; ``start_s`` croissant au sens
      large ;
    - ``timer_events`` : ``time_s`` croissant au sens large ;
    - au moins un canal présent ;
    - ``discarded`` trié par (partie, motif), sans doublon.

    Producteur
    ----------
    Le lecteur FIT de l'ingestion (``mountain_perf.ingest.fit``).

    Consommateurs
    -------------
    Le lecteur d'``interim/`` ; la vue ``TrackPointStream`` (M6b) ; les tables
    d'analyse (AN1-2).

    Non promis
    ----------
    - rien n'est interpolé : chaque canal a ses instants ;
    - les instants sont en UTC ; l'heure locale d'une activité est celle de l'index ;
    - aucun drapeau de qualité n'est posé ici : ``GPS_GAP`` vient de la vue, les
      autres détecteurs viendront avec leur usage ;
    - les champs du FIT propres à la montre (``unknown_<n>``) ne sont pas portés.
    """

    activity_ref: str
    start_time: datetime
    sessions: tuple[RecordingSession, ...]
    timer_events: tuple[TimerEvent, ...]
    position: PositionChannel | None
    elevation: ElevationChannel | None
    distance: DistanceChannel | None
    heart_rate: HeartRateChannel | None
    speed: SpeedChannel | None
    temperature: TemperatureChannel | None
    device: DeviceProvenance
    discarded: tuple[DiscardCount, ...]
    source: SourceRef

    def __post_init__(self) -> None:
        require_activity_ref(self.activity_ref)
        require_aware(self.start_time, "start_time")
        object.__setattr__(self, "start_time", self.start_time.astimezone(UTC))
        require_immutable_sequence(self.sessions, "sessions")
        require_min_length(self.sessions, 1, "sessions")
        if self.sessions[0].start_s != 0:
            raise ContractError(
                "sessions[0].start_s doit valoir 0 : le départ de l'enregistrement est "
                f"celui de la première session, reçu {self.sessions[0].start_s}."
            )
        require_increasing(
            [session.start_s for session in self.sessions],
            "sessions.start_s",
            strict=False,
        )
        require_immutable_sequence(self.timer_events, "timer_events")
        require_increasing(
            [event.time_s for event in self.timer_events],
            "timer_events.time_s",
            strict=False,
        )
        channels = (
            self.position,
            self.elevation,
            self.distance,
            self.heart_rate,
            self.speed,
            self.temperature,
        )
        if all(channel is None for channel in channels):
            raise ContractError("Un enregistrement porte au moins un canal.")
        require_immutable_sequence(self.discarded, "discarded")
        _require_strictly_sorted(
            [(item.part.value, item.reason.value) for item in self.discarded],
            "discarded (partie, motif)",
        )


# ---------------------------------------------------------------------------
# Le rapport
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ReadFile:
    """Un fichier de l'export lu par l'ingestion.

    Champs
    ------
    - ``name`` — sans unité — chemin relatif à ``raw/``, séparé par ``/``.
    - ``content_hash`` — sans unité — ``sha256`` du contenu, hexadécimal minuscule.

    Invariants
    ----------
    ``name`` non vide, sans ``\\``, sans ``:``, sans partie vide, ``.`` ou ``..`` ;
    ``content_hash`` en 64 caractères hexadécimaux minuscules.

    Producteur
    ----------
    L'ingestion.

    Consommateurs
    -------------
    ``IngestionReport``.

    Non promis
    ----------
    Un fichier lu peut avoir été refusé ensuite (``RefusedFile``).
    """

    name: str
    content_hash: str

    def __post_init__(self) -> None:
        _require_relative_name(self.name)
        _require_sha256(self.content_hash)


@dataclass(frozen=True)
class RefusedFile:
    """Un fichier de l'export que l'ingestion a refusé, et pourquoi.

    Champs
    ------
    - ``name`` — sans unité — chemin relatif à ``raw/``, séparé par ``/``.
    - ``reason`` — sans unité — le motif.

    Invariants
    ----------
    ``name`` comme dans ``ReadFile``.

    Producteur
    ----------
    L'ingestion.

    Consommateurs
    -------------
    ``IngestionReport``.

    Non promis
    ----------
    Le message de la bibliothèque de lecture n'est pas gardé.
    """

    name: str
    reason: RefusalReason

    def __post_init__(self) -> None:
        _require_relative_name(self.name)


@dataclass(frozen=True)
class RefusedEntry:
    """Une entrée de l'index que l'ingestion a refusée, et pourquoi.

    Champs
    ------
    - ``position`` — sans unité — rang de l'entrée dans le fichier d'index, depuis 0.
    - ``reason`` — sans unité — le motif.

    Invariants
    ----------
    ``position >= 0``.

    Producteur
    ----------
    Le lecteur de l'index de l'ingestion.

    Consommateurs
    -------------
    ``IngestionReport``.

    Non promis
    ----------
    L'identifiant de l'entrée n'est pas gardé : il peut manquer ou être illisible.
    """

    position: int
    reason: RefusalReason

    def __post_init__(self) -> None:
        if self.position < 0:
            raise ContractError(f"position doit être >= 0, reçu {self.position}.")


_SHA256_HEX = re.compile(r"[0-9a-f]{64}")


def _require_sha256(value: str) -> None:
    if not _SHA256_HEX.fullmatch(value):
        raise ContractError(
            "content_hash doit être un sha256 hexadécimal minuscule (64 caractères)."
        )


def _require_relative_name(name: str) -> None:
    require_non_empty(name, "name")
    parts = name.split("/")
    if "\\" in name or ":" in name or any(part in ("", ".", "..") for part in parts):
        raise ContractError(
            "name doit être un chemin relatif à raw/, séparé par « / », sans partie "
            "vide, « . » ni « .. »."
        )


class ViewRefusal(StrEnum):
    """Pourquoi une entrée de l'index n'a pas de vue ``Activity``.

    Champs
    ------
    Valeurs décrites dans ``VIEW_REFUSAL_DESCRIPTIONS``.

    Invariants
    ----------
    Énumération fermée.

    Producteur
    ----------
    La vue ``Activity`` (``mountain_perf.ingest.views``).

    Consommateurs
    -------------
    ``ViewRefusalCount`` ; le rapport d'ingestion ; tout consommateur des vues.

    Non promis
    ----------
    Seul le premier motif rencontré est dit, dans l'ordre de la vue.
    """

    NO_SPORT = "no_sport"
    MISSING_FIELD = "missing_field"
    INVARIANT = "invariant"


VIEW_REFUSAL_DESCRIPTIONS: Mapping[ViewRefusal, str] = MappingProxyType(
    {
        ViewRefusal.NO_SPORT: (
            "Type de la source absent de la table des types : pas de famille de modèle."
        ),
        ViewRefusal.MISSING_FIELD: (
            "L'entrée n'a pas un des champs qu'Activity exige (temps écoulé et en "
            "mouvement, distance, D+, D−)."
        ),
        ViewRefusal.INVARIANT: (
            "Les valeurs de l'entrée violent un invariant d'Activity."
        ),
    }
)


@dataclass(frozen=True)
class ViewRefusalCount:
    """Le nombre d'entrées de l'index d'un type de la source qui n'ont pas de vue
    ``Activity``, pour un motif.

    Champs
    ------
    - ``reason`` — sans unité — le motif.
    - ``source_activity_type`` — sans unité — le type de la source, tel quel.
    - ``count`` — sans unité — le nombre d'entrées, ``> 0``.

    Invariants
    ----------
    ``source_activity_type`` non vide ; ``count > 0``.

    Producteur
    ----------
    L'ingestion, qui calcule la vue ``Activity`` de chaque entrée.

    Consommateurs
    -------------
    ``IngestionReport`` ; ``mperf ingest``, qui l'affiche.

    Non promis
    ----------
    Les entrées ne sont pas nommées ; le compte est celui de la table des types au
    moment de l'ingestion.
    """

    reason: ViewRefusal
    source_activity_type: str
    count: int

    def __post_init__(self) -> None:
        require_non_empty(self.source_activity_type, "source_activity_type")
        if self.count <= 0:
            raise ContractError(f"count doit être > 0, reçu {self.count}.")


@dataclass(frozen=True)
class RecordingMismatch:
    """Un enregistrement dont le départ ou la durée ne s'accorde pas avec son entrée
    de l'index.

    Champs
    ------
    - ``activity_ref`` — sans unité — l'activité.
    - ``start_offset_s`` — secondes — départ de l'enregistrement moins départ de
      l'entrée.
    - ``recording_elapsed_s`` — secondes — somme des temps écoulés des sessions, si
      toutes le portent.
    - ``index_elapsed_s`` — secondes — temps écoulé de l'entrée, si présent.

    Invariants
    ----------
    ``activity_ref`` : lettres et chiffres ASCII, ``_``, ``.``, ``-`` ; nombres finis.

    Producteur
    ----------
    L'ingestion, qui compare chaque enregistrement à son entrée.

    Consommateurs
    -------------
    ``IngestionReport`` ; ``mperf ingest``, qui en affiche le compte ; la vérification
    de l'ingestion.

    Non promis
    ----------
    Rien n'est refusé : un désaccord signale un FIT rattaché à une autre activité, ou
    une horloge différente, sans dire laquelle des deux sources a raison.
    """

    activity_ref: str
    start_offset_s: float
    recording_elapsed_s: float | None
    index_elapsed_s: float | None

    def __post_init__(self) -> None:
        require_activity_ref(self.activity_ref)
        require_finite(self.start_offset_s, "start_offset_s")
        for name in ("recording_elapsed_s", "index_elapsed_s"):
            _require_optional_in_range(getattr(self, name), name, 0.0)


@dataclass(frozen=True)
class IngestionReport:
    """Le rapport de la dernière ingestion (document
    ``interim/activities/report.json``).

    Champs
    ------
    - ``retrieved_at`` — instant — instant d'acquisition de l'export, stocké en UTC.
    - ``read`` — sans unité — les fichiers lus, triés par nom.
    - ``refused_files`` — sans unité — les fichiers refusés, triés par nom.
    - ``refused_entries`` — sans unité — les entrées de l'index refusées, triées par
      rang.
    - ``view_refusals`` — sans unité — les entrées gardées sans vue ``Activity``,
      comptées par (motif, type de la source), triées ainsi (``0013``, point 2).
    - ``mismatches`` — sans unité — les enregistrements en désaccord avec leur
      entrée, triés par identifiant.

    Invariants
    ----------
    - ``retrieved_at`` *aware*, ramené en UTC ;
    - listes en tuples, triées, sans doublon ;
    - un fichier refusé a été lu.

    Producteur
    ----------
    L'ingestion.

    Consommateurs
    -------------
    L'athlète (``mperf ingest`` en affiche le compte) ; la vérification de
    l'ingestion.

    Non promis
    ----------
    Aucun instant d'exécution : deux ingestions des mêmes fichiers écrivent le même
    rapport (``0013``, point 5). Les écarts par canal sont dans chaque
    enregistrement, les champs omis dans chaque entrée de l'index.
    """

    retrieved_at: datetime
    read: tuple[ReadFile, ...]
    refused_files: tuple[RefusedFile, ...]
    refused_entries: tuple[RefusedEntry, ...]
    view_refusals: tuple[ViewRefusalCount, ...]
    mismatches: tuple[RecordingMismatch, ...]

    def __post_init__(self) -> None:
        require_aware(self.retrieved_at, "retrieved_at")
        object.__setattr__(self, "retrieved_at", self.retrieved_at.astimezone(UTC))
        for name in (
            "read",
            "refused_files",
            "refused_entries",
            "view_refusals",
            "mismatches",
        ):
            require_immutable_sequence(getattr(self, name), name)
        _require_strictly_sorted(
            [
                (item.reason.value, item.source_activity_type)
                for item in self.view_refusals
            ],
            "view_refusals (motif, type)",
        )
        _require_strictly_sorted(
            [(item.activity_ref,) for item in self.mismatches], "mismatches"
        )
        _require_strictly_sorted([(item.name,) for item in self.read], "read")
        _require_strictly_sorted(
            [(item.name,) for item in self.refused_files], "refused_files"
        )
        _require_strictly_sorted(
            [(item.position,) for item in self.refused_entries],
            "refused_entries",
        )
        read = {item.name for item in self.read}
        for item in self.refused_files:
            if item.name not in read:
                raise ContractError(
                    "refused_files : un fichier refusé doit figurer dans read."
                )
