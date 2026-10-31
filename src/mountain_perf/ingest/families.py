"""La lecture d'un fichier d'une famille journalière d'un export Garmin (AN2-1) :
``raw/garmin/<export>/<famille>/<AAAA-MM-JJ>.json`` → ``FamilyRead``.

Un fichier, une famille, un export : ce module ne compare rien entre familles ni entre
exports (l'ingestion des jours, ``mountain_perf.ingest.days``, le fait). Il lit les
formes de la source, contrôle plages, codes et instants, et compte tout ce qu'il écarte.
**Le contrat est strict, la lecture tolérante et tracée** : un point, un segment, un
épisode ou une valeur qui ne tient pas dans son contrat est écarté et compté, jamais
corrigé ; un fichier qui ne se lit pas comme sa famille est refusé, avec son motif.

Fonction pure, sans dépendance : aucune E/S (les octets et la provenance viennent de
l'appelant), bibliothèque standard, ``mountain_perf.schemas`` et
``mountain_perf.validation`` seulement. Les identifiants d'appareil vus restent en
mémoire (``FamilyRead.device_ids``), jamais écrits ni affichés ; les identifiants
d'utilisateur ne sont pas lus.

Les constantes déclarées ici sont les seuils et les codes de l'ingestion : codes
établis en comptes sur les exports, plages tirées de bornes physiques, jamais des
valeurs observées. Aucun seuil des vues des jours.
"""

from __future__ import annotations

import dataclasses
import json
import math
import re
from collections import Counter
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta, timezone
from types import MappingProxyType
from typing import Any

from mountain_perf.schemas import (
    ELEVATION_RANGE_M,
    HEART_RATE_RANGE_BPM,
    UTC_OFFSET_RANGE_S,
    WAKING_CONTEXT,
    ActivityTotals,
    AlgorithmVersions,
    AltitudeAcclimationBlock,
    BodyBatteryStatus,
    BodyBatterySummary,
    CodeCount,
    DayFamily,
    DayFileRefusal,
    HeatAcclimationBlock,
    HrvSummary,
    LoadBalanceBlock,
    Nap,
    Night,
    NightSeries,
    PointDiscard,
    PointDiscardCount,
    ReadinessEntry,
    RespirationSummary,
    RestingHr,
    SleepStage,
    SourceRef,
    SpO2Summary,
    StressSummary,
    TrainingStatusBlock,
    TrainingStatusKind,
    Vo2MaxBlock,
)

SLEEP_STAGE_CODES: Mapping[int, SleepStage] = MappingProxyType(
    {
        0: SleepStage.DEEP,
        1: SleepStage.LIGHT,
        2: SleepStage.REM,
        3: SleepStage.AWAKE,
        -1: SleepStage.UNMEASURABLE,
    }
)
"""Les codes de phase de ``sleep.sleepLevels[*].activityLevel`` : ``0`` profond, ``1``
léger, ``2`` paradoxal, ``3`` éveil, ``-1`` non mesurable. Établis en comptes (la durée
des segments de chaque code redonne le champ du résumé correspondant), jamais sur une
valeur. La source écrit un code en entier ou en flottant de valeur entière (``1`` ou
``1.0``) : les deux sont le même code (``_integral``). Un autre code, ou un code non
entier (``1.5``) : segment écarté, ``unknown_code``, compté avec sa valeur."""

STRESS_SENTINEL_CODES: tuple[int, ...] = (-2, -1)
"""Les codes sentinelles du stress (``stressValuesArray``, ``sleepStress``,
``avgStressLevel``, ``averageStressLevel``) : gardés comme codes, pas comme niveaux ;
écrits en entiers ou en flottants de valeur entière (``-1`` ou ``-1.0``, le même code).
Un autre négatif, ou un négatif non entier : écarté, ``unknown_code``, compté avec sa
valeur."""

RESPIRATION_SENTINEL_CODES: tuple[int, ...] = (-2, -1)
"""Les codes sentinelles de la respiration (``respirationValuesArray``,
``wellnessEpochRespirationDataDTOList``) : gardés comme codes ; écrits en entiers ou
en flottants de valeur entière (``-1`` ou ``-1.0``, le même code). Un autre négatif, ou
un négatif non entier : écarté, ``unknown_code``, compté avec sa valeur."""

BODY_BATTERY_STATUS_CODES: Mapping[str, BodyBatteryStatus] = MappingProxyType(
    {
        "MEASURED": BodyBatteryStatus.MEASURED,
        "MODELED": BodyBatteryStatus.MODELED,
        "RESET": BodyBatteryStatus.RESET,
    }
)
"""Les statuts d'un point de la série de Body Battery du jour
(``stress.bodyBatteryValuesArray[*][1]``). Un statut nul : point écarté,
``null_value`` ; un autre texte : point écarté, ``unknown_code``, compté avec sa
valeur."""

READINESS_CONTEXTS: tuple[str, ...] = (
    "AFTER_POST_EXERCISE_RESET",
    WAKING_CONTEXT,
    "UPDATE_REALTIME_VARIABLES",
)
"""Les contextes connus d'une entrée de Training Readiness
(``training_readiness[*].inputContext``), dont le « réveil », ``WAKING_CONTEXT``
(déclaré dans ``mountain_perf.schemas``, que les vues lisent aussi). Un autre : l'entrée
est gardée, son contexte compté comme inconnu (``FamilyRead.unknown_contexts``)."""

CONFIRMATION_TYPES: tuple[str, ...] = ("enhanced_confirmed_final", "manually_confirmed")
"""Les types de confirmation connus de la fenêtre de la nuit
(``dailySleepDTO.sleepWindowConfirmationType``). Aucun ne dit à lui seul une nuit
déclarée ou une fenêtre provisoire (``Night.from_device``, ``Night.window_confirmed``) ;
un autre type est gardé dans ``Night.confirmation`` et compté
(``FamilyRead.unknown_confirmations``)."""

STRESS_LEVEL_RANGE: tuple[int, int] = (0, 100)
"""Plage d'un niveau de stress selon Garmin, bornes comprises : l'échelle de Garmin
(le zéro est une valeur)."""

BODY_BATTERY_LEVEL_RANGE: tuple[int, int] = (0, 100)
"""Plage d'un niveau de Body Battery, bornes comprises : l'échelle de Garmin."""

RESPIRATION_RANGE_BREATHS_PER_MIN: tuple[float, float] = (0.0, 70.0)
"""Plage d'une fréquence respiratoire, en respirations par minute : ``(0, 70]``, borne
basse **exclue** (une respiration nulle n'est pas une mesure), borne haute comprise
(au-delà de la ventilation d'effort maximale)."""

SPO2_RANGE_PERCENT: tuple[float, float] = (50.0, 100.0)
"""Plage d'une saturation en oxygène, en pourcentage, bornes comprises : sous 50 %, pas
une mesure d'un athlète vivant au repos."""

HRV_RANGE_MS: tuple[float, float] = (0.0, 500.0)
"""Plage d'une HRV selon Garmin, en millisecondes : ``(0, 500]``, borne basse
**exclue**, borne haute comprise."""

SKIN_TEMPERATURE_DEVIATION_RANGE_C: tuple[float, float] = (-10.0, 10.0)
"""Plage d'un écart de température cutanée à la normale, en °C, bornes comprises."""


@dataclass(frozen=True)
class CopyField:
    """Un champ d'une famille qui recopie une grandeur dont la source est une autre
    famille : ``path``, son chemin dans le document ; ``quantity``, la grandeur, nommée
    par son chemin dans ``DayRecord`` (celui de ``CopyDisagreementCount.quantity``)."""

    path: str
    quantity: str


COPY_FIELDS: Mapping[DayFamily, tuple[CopyField, ...]] = MappingProxyType(
    {
        DayFamily.HEART_RATE: (
            CopyField("restingHeartRate", "resting_hr.resting_hr_bpm"),
        ),
        DayFamily.DAILY_SUMMARY: (
            CopyField("restingHeartRate", "resting_hr.resting_hr_bpm"),
            CopyField(
                "avgWakingRespirationValue", "respiration.avg_waking_breaths_per_min"
            ),
            CopyField("highestRespirationValue", "respiration.highest_breaths_per_min"),
            CopyField("lowestRespirationValue", "respiration.lowest_breaths_per_min"),
            CopyField("averageSpo2", "spo2.average_spo2_percent"),
            CopyField("lowestSpo2", "spo2.lowest_spo2_percent"),
        ),
        DayFamily.SLEEP: (
            CopyField("restingHeartRate", "resting_hr.resting_hr_bpm"),
            CopyField("avgOvernightHrv", "hrv.last_night_avg_ms"),
            CopyField("hrvStatus", "hrv.status"),
            CopyField(
                "dailySleepDTO.averageRespirationValue",
                "respiration.avg_sleep_breaths_per_min",
            ),
            CopyField("dailySleepDTO.averageSpO2Value", "spo2.avg_sleep_spo2_percent"),
            CopyField(
                "wellnessSpO2SleepSummaryDTO.averageSPO2", "spo2.avg_sleep_spo2_percent"
            ),
        ),
        DayFamily.STRESS: (
            CopyField("avgStressLevel", "stress.average_level"),
            CopyField("maxStressLevel", "stress.max_level"),
        ),
        DayFamily.BODY_BATTERY: (
            CopyField("[*].charged", "body_battery.charged"),
            CopyField("[*].drained", "body_battery.drained"),
        ),
        DayFamily.HRV: (
            CopyField("sleepStartTimestampGMT", "night.start"),
            CopyField("sleepEndTimestampGMT", "night.end"),
            CopyField("hrvReadings", "night.series.hrv"),
        ),
        DayFamily.RESPIRATION: (
            CopyField("sleepStartTimestampGMT", "night.start"),
            CopyField("sleepEndTimestampGMT", "night.end"),
        ),
        DayFamily.SPO2: (
            CopyField("sleepStartTimestampGMT", "night.start"),
            CopyField("sleepEndTimestampGMT", "night.end"),
        ),
    }
)
"""Les copies que porte chaque famille, sous le nom de la grandeur dont la source est
ailleurs. Valeurs d'une copie (``QuantityCopy.value``) : un nombre
(``stress.average_level`` : le niveau, ou le code sentinelle tel que la source
l'écrit) ; un texte (``hrv.status``) ; un instant en secondes UTC depuis l'époque
(``night.start``, ``night.end`` : l'instant seul, pas le décalage) ; une série en
instants absolus (``night.series.hrv`` : ``HrvPoints``). ``sleep`` porte deux copies de
``spo2.avg_sleep_spo2_percent``, distinguées par leur chemin. Les copies de Training
Readiness ne sont pas des copies contrôlées (« copie antérieure ») ; le Body Battery
« pendant le sommeil » n'est pas une copie du changement de ``sleep``."""


@dataclass(frozen=True)
class ColumnLayout:
    """La disposition d'un tableau de points en colonnes que la lecture prend par
    position : ``descriptors``, le chemin de la liste de descripteurs qui le décrit dans
    le document ; ``index_field`` et ``key_field``, les champs de l'index et de la clé
    d'un descripteur ; ``columns``, chaque clé de la source que la lecture lit, et la
    colonne où elle la prend."""

    descriptors: str
    index_field: str
    key_field: str
    columns: Mapping[str, int]


COLUMN_LAYOUTS: Mapping[DayFamily, tuple[ColumnLayout, ...]] = MappingProxyType(
    {
        DayFamily.HEART_RATE: (
            ColumnLayout(
                "heartRateValueDescriptors",
                "index",
                "key",
                MappingProxyType({"timestamp": 0, "heartrate": 1}),
            ),
        ),
        DayFamily.STRESS: (
            ColumnLayout(
                "stressValueDescriptorsDTOList",
                "index",
                "key",
                MappingProxyType({"timestamp": 0, "stressLevel": 1}),
            ),
            ColumnLayout(
                "bodyBatteryValueDescriptorsDTOList",
                "bodyBatteryValueDescriptorIndex",
                "bodyBatteryValueDescriptorKey",
                MappingProxyType(
                    {
                        "timestamp": 0,
                        "bodyBatteryStatus": 1,
                        "bodyBatteryLevel": 2,
                        "bodyBatteryVersion": 3,
                    }
                ),
            ),
        ),
        DayFamily.RESPIRATION: (
            ColumnLayout(
                "respirationValueDescriptorsDTOList",
                "index",
                "key",
                MappingProxyType({"timestamp": 0, "respiration": 1}),
            ),
        ),
    }
)
"""Les tableaux en colonnes que la lecture prend par position, et leurs descripteurs :
``heartRateValues`` (``heart_rate``), ``stressValuesArray`` et
``bodyBatteryValuesArray`` (``stress``), ``respirationValuesArray`` (``respiration``).
Dans ``activity_details``, les index des colonnes changent d'un fichier à l'autre
(``docs/PIEGES_DATA.md``) ; dans les familles journalières, les descripteurs ont
toujours dit la disposition de ce tableau. Une liste de descripteurs présente et non
vide doit donc la dire : chaque clé lue y figure, et chacun de ses descripteurs porte
l'index de sa colonne (un entier, ou un flottant de valeur entière) ; sinon le fichier
est refusé (``unexpected_shape``). Les descripteurs d'autres clés sont ignorés ; une
liste absente, nulle ou vide laisse la lecture par position. Les tableaux qu'aucun
descripteur ne décrit (``spO2HourlyAverages`` ; ceux de ``spO2ValueDescriptorsDTOList``,
de ``respirationAveragesValueDescriptorDTOList`` et de ``body_battery`` ne sont pas
lus) ne se contrôlent pas."""


@dataclass(frozen=True)
class DayWindow:
    """La fenêtre du jour que porte un fichier : ``start``, son début (le texte GMT),
    dans le décalage local − GMT de ses deux textes ; ``data_end``, ``fin_donnees`` :
    la fin GMT, dans le même décalage. Garanties : décalage dans
    ``UTC_OFFSET_RANGE_S``, en secondes entières ; date locale de ``start`` = le jour du
    fichier ; ``data_end >= start``."""

    start: datetime
    data_end: datetime


@dataclass(frozen=True)
class HeartRatePoints:
    """Une série de FC en instants absolus (``epoch_s`` : secondes UTC depuis
    l'époque, strictement croissantes), FC en battements par minute dans
    ``HEART_RATE_RANGE_BPM``."""

    epoch_s: tuple[float, ...]
    heart_rate_bpm: tuple[float, ...]


@dataclass(frozen=True)
class StressPoints:
    """Une série de stress en instants absolus : par point, un niveau dans
    ``STRESS_LEVEL_RANGE`` ou un code de ``STRESS_SENTINEL_CODES``, exactement un des
    deux."""

    epoch_s: tuple[float, ...]
    stress_level: tuple[int | None, ...]
    code: tuple[int | None, ...]


@dataclass(frozen=True)
class BodyBatteryPoints:
    """Une série de Body Battery en instants absolus : niveaux dans
    ``BODY_BATTERY_LEVEL_RANGE`` ; statut présent pour chaque point de la journée
    (``stress``), absent pour chaque point de la nuit (``sleep``)."""

    epoch_s: tuple[float, ...]
    level: tuple[int, ...]
    status: tuple[BodyBatteryStatus | None, ...]


@dataclass(frozen=True)
class RespirationPoints:
    """Une série de respiration en instants absolus : par point, une fréquence dans
    ``RESPIRATION_RANGE_BREATHS_PER_MIN`` ou un code de ``RESPIRATION_SENTINEL_CODES``,
    exactement un des deux."""

    epoch_s: tuple[float, ...]
    breaths_per_min: tuple[float | None, ...]
    code: tuple[int | None, ...]


@dataclass(frozen=True)
class SpO2Points:
    """Une série de SpO2 en instants absolus, en pourcentage dans
    ``SPO2_RANGE_PERCENT``."""

    epoch_s: tuple[float, ...]
    spo2_percent: tuple[float, ...]


@dataclass(frozen=True)
class HrvPoints:
    """Une série de HRV de 5 min en instants absolus, en millisecondes dans
    ``HRV_RANGE_MS``."""

    epoch_s: tuple[float, ...]
    hrv_ms: tuple[float, ...]


@dataclass(frozen=True)
class RestlessMomentPoints:
    """Une série de moments agités en instants absolus, comptes entiers ``>= 0``."""

    epoch_s: tuple[float, ...]
    count: tuple[int, ...]


@dataclass(frozen=True)
class StageSegments:
    """Les segments de phase de la nuit en instants absolus (secondes UTC depuis
    l'époque) : ``end_epoch_s > start_epoch_s`` pour chacun ; triés, chacun commence au
    plus tôt à la fin du précédent."""

    start_epoch_s: tuple[float, ...]
    end_epoch_s: tuple[float, ...]
    stage: tuple[SleepStage, ...]


@dataclass(frozen=True)
class DayPoints:
    """Les séries de la journée d'un fichier, en instants absolus ; chacune absente
    (``None``) sans point gardé. ``heart_rate`` (``heart_rate``) ; ``stress`` et
    ``body_battery`` (``stress``) ; ``respiration`` (``respiration``) ; ``spo2``
    (``spo2``)."""

    heart_rate: HeartRatePoints | None = None
    stress: StressPoints | None = None
    body_battery: BodyBatteryPoints | None = None
    respiration: RespirationPoints | None = None
    spo2: SpO2Points | None = None


@dataclass(frozen=True)
class NightPoints:
    """Les séries de la nuit du document ``sleep``, en instants absolus ; chacune
    absente (``None``) sans point gardé (mêmes noms que ``NightSeries``)."""

    heart_rate: HeartRatePoints | None = None
    stress: StressPoints | None = None
    body_battery: BodyBatteryPoints | None = None
    hrv: HrvPoints | None = None
    respiration: RespirationPoints | None = None
    spo2: SpO2Points | None = None
    restless_moments: RestlessMomentPoints | None = None


@dataclass(frozen=True)
class QuantityCopy:
    """Une copie lue : la grandeur (nom de ``COPY_FIELDS``), le chemin du champ dans le
    document, la valeur (dans la plage de la grandeur, sinon écartée et comptée)."""

    quantity: str
    field_path: str
    value: float | str | HrvPoints


_NO_VERSIONS = AlgorithmVersions(None, None, None, None, None, ())
_NO_DAY_POINTS = DayPoints()
_NO_NIGHT_POINTS = NightPoints()


def _no_fields() -> Mapping[str, str]:
    return MappingProxyType({})


@dataclass(frozen=True)
class FamilyRead:
    """Ce que la lecture tire d'un fichier d'une famille journalière.

    - ``family``, ``day``, ``source`` — la famille, le jour du nom du fichier, sa
      provenance (reçue de l'appelant ; recopiée dans chaque sous-objet).
    - ``refusal`` — le motif du refus, ou ``None`` ; un fichier refusé ne porte rien
      d'autre (``empty`` faux).
    - ``empty`` — la famille est absente ce jour-là, sans refus : document ``{}`` ou
      ``[]``, ou document dont rien ne se lit : ni fenêtre, ni indicateur, ni morceau
      (siestes comprises), ni entrée de Training Readiness — même d'un appareil non
      principal —, ni bloc de Training Status — même refusé faute de date propre —, ni
      série, ni segment, ni copie ; les versions, les écarts, les identifiants
      d'appareil et les feuilles (``fields``) seuls ne sont pas un contenu.
    - ``window`` — la fenêtre du jour (``daily_summary``, ``heart_rate``, ``stress``,
      ``respiration``, ``spo2``), ou ``None``.
    - ``wellness_data`` — ``includesWellnessData`` (``daily_summary``).
    - ``night`` — la nuit principale (``sleep``), **sans séries ni segments**
      (``series`` toutes absentes, ``segments`` vide) : ils sont à part, en instants
      absolus, dans ``night_series`` et ``night_segments``.
    - ``naps`` — les siestes, triées par début.
    - ``resting_hr``, ``hrv``, ``respiration``, ``spo2``, ``stress``, ``body_battery``,
      ``activity_totals`` — les résumés de la famille source ; chacun absent si aucune
      de ses valeurs n'est portée.
    - ``versions`` — les versions d'algorithme que porte ce fichier (les autres
      absentes).
    - ``readiness`` — les entrées de Training Readiness de l'appareil principal, triées
      par instant ; ``readiness_non_primary`` — les entrées des autres, comptées.
    - ``status_block``, ``load_balance_block``, ``vo2_max_block``, ``heat_block``,
      ``altitude_block`` — les blocs de Training Status, chacun à sa date propre,
      ``file_day`` = ``day`` ; ``proper_instant`` = l'horodatage du statut s'il est
      porté, sinon ``None`` (calculé par l'ingestion des jours) ;
      ``refused_blocks`` — les sortes dont le bloc est présent sans date propre.
    - ``day_series``, ``night_series``, ``night_segments`` — les séries en instants
      absolus.
    - ``copies`` — les copies contrôlées (``COPY_FIELDS``), dans l'ordre de la table.
    - ``device_ids`` — les identifiants d'appareil vus, dans l'ordre de première
      apparition (jamais écrits ; absents de ``repr``).
    - ``discards`` — les écarts, par chemin et motif, triés ; ``unknown_codes`` — les
      codes inconnus des points écartés, avec leur valeur ; ``unknown_confirmations`` —
      les types de confirmation inconnus ; ``unknown_contexts`` — les contextes de
      Training Readiness inconnus.
    - ``has_detail`` — au moins une série fine que Garmin efface est non vide dans ce
      fichier : FC, stress, Body Battery, respiration de la journée ; segments, séries
      de la nuit (SpO2 exclue) ; HRV de 5 min de ``hrv``.
    - ``fields`` — les feuilles du document : chemin → texte JSON canonique de la valeur
      (une liste est une seule feuille, ``<chemin>[*]``, de tout son contenu), sans les
      champs d'identité ni ceux qui ne s'ingèrent pas.
    """

    family: DayFamily
    day: date
    source: SourceRef
    refusal: DayFileRefusal | None = None
    empty: bool = False
    window: DayWindow | None = None
    wellness_data: bool | None = None
    night: Night | None = None
    naps: tuple[Nap, ...] = ()
    resting_hr: RestingHr | None = None
    hrv: HrvSummary | None = None
    respiration: RespirationSummary | None = None
    spo2: SpO2Summary | None = None
    stress: StressSummary | None = None
    body_battery: BodyBatterySummary | None = None
    activity_totals: ActivityTotals | None = None
    versions: AlgorithmVersions = _NO_VERSIONS
    readiness: tuple[ReadinessEntry, ...] = ()
    readiness_non_primary: int = 0
    status_block: TrainingStatusBlock | None = None
    load_balance_block: LoadBalanceBlock | None = None
    vo2_max_block: Vo2MaxBlock | None = None
    heat_block: HeatAcclimationBlock | None = None
    altitude_block: AltitudeAcclimationBlock | None = None
    refused_blocks: tuple[TrainingStatusKind, ...] = ()
    day_series: DayPoints = _NO_DAY_POINTS
    night_series: NightPoints = _NO_NIGHT_POINTS
    night_segments: StageSegments | None = None
    copies: tuple[QuantityCopy, ...] = ()
    device_ids: tuple[int, ...] = field(default=(), repr=False)
    discards: tuple[PointDiscardCount, ...] = ()
    unknown_codes: tuple[CodeCount, ...] = ()
    unknown_confirmations: tuple[CodeCount, ...] = ()
    unknown_contexts: tuple[CodeCount, ...] = ()
    has_detail: bool = False
    fields: Mapping[str, str] = field(default_factory=_no_fields)


# ---------------------------------------------------------------------------
# Les lecteurs typés
# ---------------------------------------------------------------------------

_EPOCH = datetime(1970, 1, 1, tzinfo=UTC)
_MS = timedelta(milliseconds=1)
_MIN_MS = (datetime(1, 1, 2, tzinfo=UTC) - _EPOCH) // _MS
_MAX_MS = (datetime(9999, 12, 30, tzinfo=UTC) - _EPOCH) // _MS
"""La plage d'un instant lu, en millisecondes depuis l'époque : ce que ``datetime``
représente, à un jour près (une garde de calcul, pas un seuil)."""

_INSTANT_TEXT = re.compile(
    r"([0-9]{4})-([0-9]{2})-([0-9]{2})T([0-9]{2}):([0-9]{2}):([0-9]{2})"
    r"(?:\.([0-9]{1,3}))?"
)
_DATE_TEXT = re.compile(r"([0-9]{4})-([0-9]{2})-([0-9]{2})")
_DIGITS = re.compile(r"[0-9]+")
_INF = float("inf")


class _ShapeError(Exception):
    """Un champ lu d'un autre type JSON que le sien : le fichier est refusé."""


class _DateMismatchError(Exception):
    """La date du document n'est pas celle de son nom."""


class _NoPrimaryError(Exception):
    """Une table de Training Status à plusieurs appareils sans un seul principal."""


def _object(value: Any) -> dict[str, Any] | None:
    if value is None:
        return None
    if not isinstance(value, dict):
        raise _ShapeError
    return value


def _list(value: Any) -> list[Any] | None:
    if value is None:
        return None
    if not isinstance(value, list):
        raise _ShapeError
    return value


def _number(value: Any) -> int | float | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise _ShapeError
    return value


def _text(value: Any) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise _ShapeError
    return value


def _boolean(value: Any) -> bool | None:
    if value is None:
        return None
    if not isinstance(value, bool):
        raise _ShapeError
    return value


def _ms(value: Any) -> int | None:
    """Un instant en millisecondes depuis l'époque, entier."""
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int):
        raise _ShapeError
    return value


def _text_ms(value: Any) -> int | None:
    """Un texte ``AAAA-MM-JJTHH:MM:SS[.f]``, lu comme GMT, en millisecondes."""
    text = _text(value)
    if text is None:
        return None
    match = _INSTANT_TEXT.fullmatch(text)
    if match is None:
        raise _ShapeError
    year, month, day, hour, minute, second, fraction = match.groups()
    try:
        instant = datetime(
            int(year),
            int(month),
            int(day),
            int(hour),
            int(minute),
            int(second),
            tzinfo=UTC,
        )
    except ValueError:
        raise _ShapeError from None
    milliseconds = int(fraction.ljust(3, "0")) if fraction else 0
    return (instant - _EPOCH) // _MS + milliseconds


def _date(value: Any) -> date | None:
    text = _text(value)
    if text is None:
        return None
    match = _DATE_TEXT.fullmatch(text)
    if match is None:
        raise _ShapeError
    try:
        return date(*(int(part) for part in match.groups()))
    except ValueError:
        raise _ShapeError from None


def _integral(value: int | float) -> int | None:
    """Un nombre de valeur entière, en entier (``1.0`` → ``1``) ; sinon ``None``."""
    if isinstance(value, int):
        return value
    if math.isfinite(value) and value.is_integer():
        return int(value)
    return None


def _code_text(value: Any) -> str:
    """L'écriture d'un code inconnu : un texte non blanc tel quel, sinon son écriture
    JSON."""
    if isinstance(value, str) and value.strip():
        return value
    return json.dumps(value)


def _in_range(
    value: int | float,
    low: float,
    high: float,
    *,
    low_open: bool = False,
    integral: bool = False,
) -> int | float | None:
    """La valeur si elle est finie (entière si demandé) et dans sa plage, sinon
    ``None`` (``out_of_range``)."""
    if integral:
        whole = _integral(value)
        if whole is None:
            return None
        value = whole
    try:
        number = float(value)
    except OverflowError:
        return None
    if not math.isfinite(number):
        return None
    if number < low or number > high or (low_open and number <= low):
        return None
    return value


def _instant(gmt_ms: int, offset_s: int) -> datetime:
    return (_EPOCH + timedelta(milliseconds=gmt_ms)).astimezone(
        timezone(timedelta(seconds=offset_s))
    )


def _offset_s(local_ms: int, gmt_ms: int) -> int | None:
    """Le décalage local − GMT, en secondes entières dans sa plage ; sinon ``None``."""
    difference = local_ms - gmt_ms
    if difference % 1000:
        return None
    seconds = difference // 1000
    low, high = UTC_OFFSET_RANGE_S
    return seconds if low <= seconds <= high else None


def _ms_in_range(value: int) -> bool:
    return _MIN_MS <= value <= _MAX_MS


def _path(obj: Any, *keys: str) -> Any:
    """La valeur au chemin ``keys`` d'objets imbriqués ; ``None`` si un maillon manque
    (un maillon d'un autre type que l'objet refuse le fichier)."""
    for key in keys:
        found = _object(obj)
        if found is None:
            return None
        obj = found.get(key)
    return obj


# ---------------------------------------------------------------------------
# Les feuilles comparées
# ---------------------------------------------------------------------------

_IDENTITY_KEYS = frozenset(
    {
        "activityId",
        "activityName",
        "deviceId",
        "displayName",
        "id",
        "recordedDevices",
        "userDailySummaryId",
        "userId",
        "userProfileId",
        "userProfilePK",
        "userProfilePk",
        "uuid",
    }
)
_NOT_INGESTED_KEYS = frozenset(
    {
        "sleepNeed",
        "nextSleepNeed",
        "sleepAlignment",
        "sleepMovement",
        "bodyBatteryActivityEvent",
        "bodyBatteryActivityEventList",
        "bodyBatteryDynamicFeedbackEvent",
        "endOfDayBodyBatteryDynamicFeedbackEvent",
    }
)
_NOT_INGESTED_PARTS = ("tomorrow", "feedback", "insight", "calorie")


def _excluded(key: str) -> bool:
    lowered = key.lower()
    return (
        key in _IDENTITY_KEYS
        or key in _NOT_INGESTED_KEYS
        or any(part in lowered for part in _NOT_INGESTED_PARTS)
        or key.endswith("Phrase")
    )


def _clean(value: Any) -> Any:
    """Une valeur sans ses clés exclues, à toute profondeur."""
    if isinstance(value, dict):
        return {key: _clean(item) for key, item in value.items() if not _excluded(key)}
    if isinstance(value, list):
        return [_clean(item) for item in value]
    return value


def _canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _leaves(value: Any, path: str, out: dict[str, str]) -> None:
    if isinstance(value, dict):
        for key in sorted(value):
            if not _excluded(key):
                _leaves(value[key], f"{path}.{key}" if path else key, out)
    elif isinstance(value, list):
        out[f"{path}[*]"] = _canonical(_clean(value))
    else:
        out[path] = _canonical(value)


# ---------------------------------------------------------------------------
# La lecture, ses comptes
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class _Point:
    """Un point gardé : ses millisecondes, sa valeur ou son code, son statut."""

    ms: int
    value: int | float | None
    code: int | None = None
    status: BodyBatteryStatus | None = None


class _Reader:
    """La lecture d'un fichier : ses comptes, ses identifiants d'appareil."""

    def __init__(self, family: DayFamily, day: date, source: SourceRef) -> None:
        self.family = family
        self.day = day
        self.source = source
        self.discards: Counter[tuple[str, PointDiscard]] = Counter()
        self.codes: Counter[tuple[str, str]] = Counter()
        self.confirmations: Counter[tuple[str, str]] = Counter()
        self.contexts: Counter[tuple[str, str]] = Counter()
        self.devices: list[int] = []

    def discard(self, path: str, reason: PointDiscard) -> None:
        self.discards[(path, reason)] += 1

    def unknown(self, path: str, code_path: str, raw: Any) -> None:
        self.discard(path, PointDiscard.UNKNOWN_CODE)
        self.codes[(code_path, _code_text(raw))] += 1

    def device(self, raw: Any) -> None:
        if raw is None:
            return
        if isinstance(raw, bool) or not isinstance(raw, int):
            raise _ShapeError
        if raw not in self.devices:
            self.devices.append(raw)

    def value(
        self,
        raw: Any,
        path: str,
        low: float,
        high: float = _INF,
        *,
        low_open: bool = False,
        integral: bool = False,
    ) -> Any:
        """Une valeur d'un résumé, d'une copie ou d'un bloc : absente si nulle ; hors
        de sa plage, absente et comptée."""
        number = _number(raw)
        if number is None:
            return None
        kept = _in_range(number, low, high, low_open=low_open, integral=integral)
        if kept is None:
            self.discard(path, PointDiscard.OUT_OF_RANGE)
        return kept

    def code(self, raw: Any, path: str) -> int | None:
        """Un code numérique, lu par sa valeur ; non entier, absent et compté."""
        number = _number(raw)
        if number is None:
            return None
        whole = _integral(number)
        if whole is None:
            self.discard(path, PointDiscard.OUT_OF_RANGE)
        return whole

    def label(self, raw: Any, path: str) -> str | None:
        """Un code texte : blanc, absent et compté (``null_value``)."""
        text = _text(raw)
        if text is not None and not text.strip():
            self.discard(path, PointDiscard.NULL_VALUE)
            return None
        return text

    def epoch(self, raw: Any, path: str, *, text: bool) -> float | None:
        """Un instant copié, en secondes UTC depuis l'époque."""
        ms = _text_ms(raw) if text else _ms(raw)
        if ms is None:
            return None
        if not _ms_in_range(ms):
            self.discard(path, PointDiscard.OUT_OF_RANGE)
            return None
        return ms / 1000

    def keep(self, kept: list[_Point], path: str, ms: int, point: _Point) -> None:
        """L'ordre des instants, contre le dernier point gardé."""
        if kept and ms == kept[-1].ms:
            self.discard(path, PointDiscard.DUPLICATE_INSTANT)
        elif kept and ms < kept[-1].ms:
            self.discard(path, PointDiscard.NOT_INCREASING)
        else:
            kept.append(point)

    def series(
        self,
        items: list[Any] | None,
        path: str,
        extract: Callable[[Any], tuple[int | None, Any]],
        low: float,
        high: float,
        *,
        low_open: bool = False,
        integral: bool = False,
        sentinels: tuple[int, ...] | None = None,
        code_path: str = "",
    ) -> list[_Point]:
        """Les points gardés d'une série, dans l'ordre des écarts : instant nul ou
        hors plage ; valeur nulle ; code (séries à codes) ; plage ; ordre."""
        kept: list[_Point] = []
        for item in items or ():
            ms, raw = extract(item)
            number = _number(raw)
            if ms is None:
                self.discard(path, PointDiscard.NULL_VALUE)
                continue
            if not _ms_in_range(ms):
                self.discard(path, PointDiscard.OUT_OF_RANGE)
                continue
            if number is None:
                self.discard(path, PointDiscard.NULL_VALUE)
                continue
            if sentinels is not None and number < 0:
                code = _integral(number)
                if code is None or code not in sentinels:
                    self.unknown(path, code_path, raw)
                    continue
                self.keep(kept, path, ms, _Point(ms, None, code))
                continue
            value = _in_range(number, low, high, low_open=low_open, integral=integral)
            if value is None:
                self.discard(path, PointDiscard.OUT_OF_RANGE)
                continue
            self.keep(kept, path, ms, _Point(ms, value))
        return kept

    def counts(self, counter: Counter[tuple[str, str]]) -> tuple[CodeCount, ...]:
        return tuple(
            CodeCount(self.family, path, text, count)
            for (path, text), count in sorted(counter.items())
        )

    def discard_counts(self) -> tuple[PointDiscardCount, ...]:
        return tuple(
            PointDiscardCount(self.family, path, reason, count)
            for (path, reason), count in sorted(
                self.discards.items(), key=lambda item: (item[0][0], item[0][1].value)
            )
        )


def _columns(item: Any, size: int) -> list[Any]:
    """Un point en colonnes, d'au moins ``size`` colonnes."""
    if not isinstance(item, list) or len(item) < size:
        raise _ShapeError
    return item


def _column_pair(item: Any) -> tuple[int | None, Any]:
    point = _columns(item, 2)
    return _ms(point[0]), point[1]


def _field_pair(
    time_key: str, value_key: str, *, text: bool = False
) -> Callable[[Any], tuple[int | None, Any]]:
    def extract(item: Any) -> tuple[int | None, Any]:
        point = _object(item)
        if point is None:
            raise _ShapeError
        when = _text_ms(point.get(time_key)) if text else _ms(point.get(time_key))
        return when, point.get(value_key)

    return extract


def _check_layouts(document: dict[str, Any], family: DayFamily) -> None:
    """Les descripteurs de colonnes, présents et non vides, disent la disposition
    lue ; sinon ``_ShapeError``."""
    for layout in COLUMN_LAYOUTS.get(family, ()):
        descriptors = _list(document.get(layout.descriptors))
        if not descriptors:
            continue
        named: set[str] = set()
        for descriptor in descriptors:
            if not isinstance(descriptor, dict):
                raise _ShapeError
            key = descriptor.get(layout.key_field)
            if not isinstance(key, str) or key not in layout.columns:
                continue
            index = descriptor.get(layout.index_field)
            if isinstance(index, bool) or not isinstance(index, int | float):
                raise _ShapeError
            if _integral(index) != layout.columns[key]:
                raise _ShapeError
            named.add(key)
        if named != set(layout.columns):
            raise _ShapeError


def _epoch_s(points: list[_Point]) -> tuple[float, ...]:
    return tuple(point.ms / 1000 for point in points)


def _heart_rate(points: list[_Point]) -> HeartRatePoints | None:
    if not points:
        return None
    return HeartRatePoints(
        _epoch_s(points), tuple(float(point.value or 0.0) for point in points)
    )


def _stress(points: list[_Point]) -> StressPoints | None:
    if not points:
        return None
    return StressPoints(
        _epoch_s(points),
        tuple(None if point.value is None else int(point.value) for point in points),
        tuple(point.code for point in points),
    )


def _respiration(points: list[_Point]) -> RespirationPoints | None:
    if not points:
        return None
    return RespirationPoints(
        _epoch_s(points),
        tuple(None if point.value is None else float(point.value) for point in points),
        tuple(point.code for point in points),
    )


def _spo2(points: list[_Point]) -> SpO2Points | None:
    if not points:
        return None
    return SpO2Points(
        _epoch_s(points), tuple(float(point.value or 0.0) for point in points)
    )


def _hrv(points: list[_Point]) -> HrvPoints | None:
    if not points:
        return None
    return HrvPoints(
        _epoch_s(points), tuple(float(point.value or 0.0) for point in points)
    )


def _body_battery(points: list[_Point]) -> BodyBatteryPoints | None:
    if not points:
        return None
    return BodyBatteryPoints(
        _epoch_s(points),
        tuple(int(point.value or 0) for point in points),
        tuple(point.status for point in points),
    )


def _restless(points: list[_Point]) -> RestlessMomentPoints | None:
    if not points:
        return None
    return RestlessMomentPoints(
        _epoch_s(points), tuple(int(point.value or 0) for point in points)
    )


# ---------------------------------------------------------------------------
# Les morceaux communs
# ---------------------------------------------------------------------------


def _window(
    r: _Reader, start_raw: Any, local_raw: Any, end_raw: Any
) -> DayWindow | None:
    """La fenêtre du jour d'un fichier, dans l'ordre des écarts : manquante à demi ;
    décalage, instant ou date locale du début hors plage ; fin avant le début."""
    start, local, end = _text_ms(start_raw), _text_ms(local_raw), _text_ms(end_raw)
    if start is None and local is None and end is None:
        return None
    if start is None or local is None or end is None:
        r.discard("window", PointDiscard.NULL_VALUE)
        return None
    offset = _offset_s(local, start)
    if offset is None or not all(_ms_in_range(ms) for ms in (start, local, end)):
        r.discard("window", PointDiscard.OUT_OF_RANGE)
        return None
    begin = _instant(start, offset)
    if begin.date() != r.day:
        r.discard("window", PointDiscard.OUT_OF_RANGE)
        return None
    if end < start:
        r.discard("window", PointDiscard.NOT_INCREASING)
        return None
    return DayWindow(begin, _instant(end, offset))


def _check_date(found: date | None, day: date) -> None:
    if found is not None and found != day:
        raise _DateMismatchError


def _copy(
    copies: dict[str, QuantityCopy], quantity: str, path: str, value: Any
) -> None:
    if value is not None:
        copies[path] = QuantityCopy(quantity, path, value)


def _ordered_copies(
    family: DayFamily, copies: dict[str, QuantityCopy]
) -> tuple[QuantityCopy, ...]:
    return tuple(
        copies[copy.path] for copy in COPY_FIELDS.get(family, ()) if copy.path in copies
    )


def _summary[T](
    cls: Callable[..., T], values: dict[str, Any], src: SourceRef
) -> T | None:
    if all(value is None for value in values.values()):
        return None
    return cls(**values, source=src)


def _float(value: int | float | None) -> float | None:
    return None if value is None else float(value)


def _int(value: int | float | None) -> int | None:
    return None if value is None else int(value)


def _hrv_value(r: _Reader, raw: Any, path: str) -> float | None:
    return _float(r.value(raw, path, *HRV_RANGE_MS, low_open=True))


def _respiration_value(r: _Reader, raw: Any, path: str) -> float | None:
    return _float(r.value(raw, path, *RESPIRATION_RANGE_BREATHS_PER_MIN, low_open=True))


def _spo2_value(r: _Reader, raw: Any, path: str) -> float | None:
    return _float(r.value(raw, path, *SPO2_RANGE_PERCENT))


def _heart_rate_value(r: _Reader, raw: Any, path: str) -> float | None:
    return _float(r.value(raw, path, *HEART_RATE_RANGE_BPM))


def _level(
    r: _Reader, raw: Any, path: str, low: int = 0, high: int = 100
) -> int | None:
    return _int(r.value(raw, path, low, high, integral=True))


def _stress_average(r: _Reader, raw: Any, path: str) -> tuple[int | None, int | None]:
    """Un stress moyen : un niveau, ou un code sentinelle connu ; un autre négatif est
    un code inconnu, compté."""
    number = _number(raw)
    if number is None:
        return None, None
    if number < 0:
        code = _integral(number)
        if code is None or code not in STRESS_SENTINEL_CODES:
            r.unknown(path, path, raw)
            return None, None
        return None, code
    return _level(r, raw, path), None


def _version(r: _Reader, raw: Any, path: str) -> int | None:
    return _int(r.value(raw, path, 0, integral=True))


# ---------------------------------------------------------------------------
# Les familles
# ---------------------------------------------------------------------------

_Parts = dict[str, Any]


def _read_heart_rate(r: _Reader, doc: dict[str, Any]) -> _Parts:
    _check_date(_date(doc.get("calendarDate")), r.day)
    _check_layouts(doc, r.family)
    window = _window(
        r,
        doc.get("startTimestampGMT"),
        doc.get("startTimestampLocal"),
        doc.get("endTimestampGMT"),
    )
    copies: dict[str, QuantityCopy] = {}
    _copy(
        copies,
        "resting_hr.resting_hr_bpm",
        "restingHeartRate",
        _heart_rate_value(r, doc.get("restingHeartRate"), "restingHeartRate"),
    )
    points = r.series(
        _list(doc.get("heartRateValues")),
        "heartRateValues",
        _column_pair,
        *HEART_RATE_RANGE_BPM,
    )
    return {
        "window": window,
        "day_series": DayPoints(heart_rate=_heart_rate(points)),
        "copies": copies,
    }


def _read_stress(r: _Reader, doc: dict[str, Any]) -> _Parts:
    _check_date(_date(doc.get("calendarDate")), r.day)
    _check_layouts(doc, r.family)
    window = _window(
        r,
        doc.get("startTimestampGMT"),
        doc.get("startTimestampLocal"),
        doc.get("endTimestampGMT"),
    )
    copies: dict[str, QuantityCopy] = {}
    level, code = _stress_average(r, doc.get("avgStressLevel"), "avgStressLevel")
    _copy(
        copies,
        "stress.average_level",
        "avgStressLevel",
        code if level is None else level,
    )
    _copy(
        copies,
        "stress.max_level",
        "maxStressLevel",
        _level(r, doc.get("maxStressLevel"), "maxStressLevel"),
    )
    stress = r.series(
        _list(doc.get("stressValuesArray")),
        "stressValuesArray",
        _column_pair,
        *STRESS_LEVEL_RANGE,
        integral=True,
        sentinels=STRESS_SENTINEL_CODES,
        code_path="stressValuesArray[*][1]",
    )
    battery, series_versions = _day_body_battery(
        r, _list(doc.get("bodyBatteryValuesArray"))
    )
    return {
        "window": window,
        "day_series": DayPoints(
            stress=_stress(stress), body_battery=_body_battery(battery)
        ),
        "copies": copies,
        "series_versions": series_versions,
    }


def _day_body_battery(
    r: _Reader, items: list[Any] | None
) -> tuple[list[_Point], tuple[int, ...]]:
    """La série de Body Battery du jour : le statut avant le niveau ; les versions des
    points gardés."""
    path = "bodyBatteryValuesArray"
    kept: list[_Point] = []
    versions: set[int] = set()
    for item in items or ():
        point = _columns(item, 4)
        ms, status_raw, level_raw = _ms(point[0]), _text(point[1]), _number(point[2])
        version_raw = _number(point[3])
        if ms is None:
            r.discard(path, PointDiscard.NULL_VALUE)
            continue
        if not _ms_in_range(ms):
            r.discard(path, PointDiscard.OUT_OF_RANGE)
            continue
        if status_raw is None:
            r.discard(path, PointDiscard.NULL_VALUE)
            continue
        status = BODY_BATTERY_STATUS_CODES.get(status_raw)
        if status is None:
            r.unknown(path, "bodyBatteryValuesArray[*][1]", status_raw)
            continue
        if level_raw is None:
            r.discard(path, PointDiscard.NULL_VALUE)
            continue
        level = _in_range(level_raw, *BODY_BATTERY_LEVEL_RANGE, integral=True)
        if level is None:
            r.discard(path, PointDiscard.OUT_OF_RANGE)
            continue
        before = len(kept)
        r.keep(kept, path, ms, _Point(ms, level, status=status))
        if len(kept) > before and version_raw is not None:
            version = _in_range(version_raw, 0, _INF, integral=True)
            if version is None:
                r.discard("bodyBatteryValuesArray[*][3]", PointDiscard.OUT_OF_RANGE)
            else:
                versions.add(int(version))
    return kept, tuple(sorted(versions))


def _read_respiration(r: _Reader, doc: dict[str, Any]) -> _Parts:
    _check_date(_date(doc.get("calendarDate")), r.day)
    _check_layouts(doc, r.family)
    window = _window(
        r,
        doc.get("startTimestampGMT"),
        doc.get("startTimestampLocal"),
        doc.get("endTimestampGMT"),
    )
    summary = _summary(
        RespirationSummary,
        {
            "avg_sleep_breaths_per_min": _respiration_value(
                r, doc.get("avgSleepRespirationValue"), "avgSleepRespirationValue"
            ),
            "avg_waking_breaths_per_min": _respiration_value(
                r, doc.get("avgWakingRespirationValue"), "avgWakingRespirationValue"
            ),
            "highest_breaths_per_min": _respiration_value(
                r, doc.get("highestRespirationValue"), "highestRespirationValue"
            ),
            "lowest_breaths_per_min": _respiration_value(
                r, doc.get("lowestRespirationValue"), "lowestRespirationValue"
            ),
        },
        r.source,
    )
    copies = _night_window_copies(r, doc)
    points = r.series(
        _list(doc.get("respirationValuesArray")),
        "respirationValuesArray",
        _column_pair,
        *RESPIRATION_RANGE_BREATHS_PER_MIN,
        low_open=True,
        sentinels=RESPIRATION_SENTINEL_CODES,
        code_path="respirationValuesArray[*][1]",
    )
    version = _version(r, doc.get("respirationVersion"), "respirationVersion")
    return {
        "window": window,
        "respiration": summary,
        "day_series": DayPoints(respiration=_respiration(points)),
        "copies": copies,
        "versions": {"respiration_version": version},
    }


def _night_window_copies(r: _Reader, doc: dict[str, Any]) -> dict[str, QuantityCopy]:
    copies: dict[str, QuantityCopy] = {}
    for path, quantity in (
        ("sleepStartTimestampGMT", "night.start"),
        ("sleepEndTimestampGMT", "night.end"),
    ):
        _copy(copies, quantity, path, r.epoch(doc.get(path), path, text=True))
    return copies


def _read_spo2(r: _Reader, doc: dict[str, Any]) -> _Parts:
    _check_date(_date(doc.get("calendarDate")), r.day)
    window = _window(
        r,
        doc.get("startTimestampGMT"),
        doc.get("startTimestampLocal"),
        doc.get("endTimestampGMT"),
    )
    summary = _summary(
        SpO2Summary,
        {
            "avg_sleep_spo2_percent": _spo2_value(
                r, doc.get("avgSleepSpO2"), "avgSleepSpO2"
            ),
            "average_spo2_percent": _spo2_value(
                r, doc.get("averageSpO2"), "averageSpO2"
            ),
            "lowest_spo2_percent": _spo2_value(r, doc.get("lowestSpO2"), "lowestSpO2"),
        },
        r.source,
    )
    copies = _night_window_copies(r, doc)
    points = r.series(
        _list(doc.get("spO2HourlyAverages")),
        "spO2HourlyAverages",
        _column_pair,
        *SPO2_RANGE_PERCENT,
    )
    return {
        "window": window,
        "spo2": summary,
        "day_series": DayPoints(spo2=_spo2(points)),
        "copies": copies,
    }


_STRESS_DURATION_KEYS = (
    ("rest_duration_s", "restStressDuration"),
    ("low_duration_s", "lowStressDuration"),
    ("medium_duration_s", "mediumStressDuration"),
    ("high_duration_s", "highStressDuration"),
    ("activity_duration_s", "activityStressDuration"),
    ("uncategorized_duration_s", "uncategorizedStressDuration"),
    ("total_duration_s", "totalStressDuration"),
    ("stress_duration_s", "stressDuration"),
)


def _minutes(r: _Reader, raw: Any, path: str) -> float | None:
    minutes = r.value(raw, path, 0.0)
    return None if minutes is None else float(minutes) * 60


def _read_daily_summary(r: _Reader, doc: dict[str, Any]) -> _Parts:
    _check_date(_date(doc.get("calendarDate")), r.day)
    window = _window(
        r,
        doc.get("wellnessStartTimeGmt"),
        doc.get("wellnessStartTimeLocal"),
        doc.get("wellnessEndTimeGmt"),
    )
    wellness = _boolean(doc.get("includesWellnessData"))
    level, code = _stress_average(
        r, doc.get("averageStressLevel"), "averageStressLevel"
    )
    stress_values: dict[str, Any] = {
        "average_level": level,
        "average_level_code": code,
        "max_level": _level(r, doc.get("maxStressLevel"), "maxStressLevel"),
    }
    for name, key in _STRESS_DURATION_KEYS:
        stress_values[name] = _float(r.value(doc.get(key), key, 0.0))
    battery = {
        "charged": _int(
            r.value(
                doc.get("bodyBatteryChargedValue"),
                "bodyBatteryChargedValue",
                0,
                integral=True,
            )
        ),
        "drained": _int(
            r.value(
                doc.get("bodyBatteryDrainedValue"),
                "bodyBatteryDrainedValue",
                0,
                integral=True,
            )
        ),
        "highest": _level(
            r, doc.get("bodyBatteryHighestValue"), "bodyBatteryHighestValue"
        ),
        "lowest": _level(
            r, doc.get("bodyBatteryLowestValue"), "bodyBatteryLowestValue"
        ),
        "at_wake": _level(r, doc.get("bodyBatteryAtWakeTime"), "bodyBatteryAtWakeTime"),
        "during_sleep": _level(
            r, doc.get("bodyBatteryDuringSleep"), "bodyBatteryDuringSleep", -100, 100
        ),
    }
    totals = {
        "steps": _int(r.value(doc.get("totalSteps"), "totalSteps", 0, integral=True)),
        "moderate_intensity_s": _minutes(
            r, doc.get("moderateIntensityMinutes"), "moderateIntensityMinutes"
        ),
        "vigorous_intensity_s": _minutes(
            r, doc.get("vigorousIntensityMinutes"), "vigorousIntensityMinutes"
        ),
        "floors_ascended_m": _float(
            r.value(doc.get("floorsAscendedInMeters"), "floorsAscendedInMeters", 0.0)
        ),
        "floors_descended_m": _float(
            r.value(doc.get("floorsDescendedInMeters"), "floorsDescendedInMeters", 0.0)
        ),
        "average_altitude_m": _float(
            r.value(
                doc.get("averageMonitoringEnvironmentAltitude"),
                "averageMonitoringEnvironmentAltitude",
                *ELEVATION_RANGE_M,
            )
        ),
    }
    copies: dict[str, QuantityCopy] = {}
    _copy(
        copies,
        "resting_hr.resting_hr_bpm",
        "restingHeartRate",
        _heart_rate_value(r, doc.get("restingHeartRate"), "restingHeartRate"),
    )
    for key, quantity in (
        ("avgWakingRespirationValue", "respiration.avg_waking_breaths_per_min"),
        ("highestRespirationValue", "respiration.highest_breaths_per_min"),
        ("lowestRespirationValue", "respiration.lowest_breaths_per_min"),
    ):
        _copy(copies, quantity, key, _respiration_value(r, doc.get(key), key))
    for key, quantity in (
        ("averageSpo2", "spo2.average_spo2_percent"),
        ("lowestSpo2", "spo2.lowest_spo2_percent"),
    ):
        _copy(copies, quantity, key, _spo2_value(r, doc.get(key), key))
    return {
        "window": window,
        "wellness_data": wellness,
        "stress": _summary(StressSummary, stress_values, r.source),
        "body_battery": _summary(BodyBatterySummary, battery, r.source),
        "activity_totals": _summary(ActivityTotals, totals, r.source),
        "copies": copies,
        "versions": {
            "summary_respiration_version": _version(
                r, doc.get("respirationAlgorithmVersion"), "respirationAlgorithmVersion"
            ),
            "summary_body_battery_version": _version(
                r, doc.get("bodyBatteryVersion"), "bodyBatteryVersion"
            ),
        },
    }


def _read_body_battery(r: _Reader, root: list[Any]) -> _Parts:
    elements: list[dict[str, Any]] = []
    for item in root:
        element = _object(item)
        if element is None:
            raise _ShapeError
        elements.append(element)
    for element in elements:
        _check_date(_date(element.get("date")), r.day)
    copies: dict[str, QuantityCopy] = {}
    for rank, element in enumerate(elements):
        charged = r.value(element.get("charged"), "[*].charged", 0, integral=True)
        drained = r.value(element.get("drained"), "[*].drained", 0, integral=True)
        if rank:
            r.discard("[*]", PointDiscard.DUPLICATE_INSTANT)
            continue
        _copy(copies, "body_battery.charged", "[*].charged", charged)
        _copy(copies, "body_battery.drained", "[*].drained", drained)
    return {"copies": copies}


_RESTING_PATH = "allMetrics.metricsMap.WELLNESS_RESTING_HEART_RATE"


def _read_resting_hr(r: _Reader, doc: dict[str, Any]) -> _Parts:
    entries: list[dict[str, Any]] = []
    raw = _path(doc, "allMetrics", "metricsMap", "WELLNESS_RESTING_HEART_RATE")
    for item in _list(raw) or ():
        entry = _object(item)
        if entry is None:
            raise _ShapeError
        entries.append(entry)
    for entry in entries:
        _check_date(_date(entry.get("calendarDate")), r.day)
    resting: RestingHr | None = None
    for rank, entry in enumerate(entries):
        value = _heart_rate_value(r, entry.get("value"), f"{_RESTING_PATH}[*].value")
        if rank:
            r.discard(_RESTING_PATH, PointDiscard.DUPLICATE_INSTANT)
        elif value is not None:
            resting = RestingHr(value, r.source)
    return {"resting_hr": resting}


def _read_hrv(r: _Reader, doc: dict[str, Any]) -> _Parts:
    summary_doc = _object(doc.get("hrvSummary"))
    _check_date(_date(_path(summary_doc, "calendarDate")), r.day)
    summary_doc = summary_doc or {}
    baseline = _object(summary_doc.get("baseline")) or {}
    values = {
        "last_night_avg_ms": _hrv_value(
            r, summary_doc.get("lastNightAvg"), "hrvSummary.lastNightAvg"
        ),
        "last_night_5min_high_ms": _hrv_value(
            r, summary_doc.get("lastNight5MinHigh"), "hrvSummary.lastNight5MinHigh"
        ),
        "weekly_avg_ms": _hrv_value(
            r, summary_doc.get("weeklyAvg"), "hrvSummary.weeklyAvg"
        ),
        "status": r.label(summary_doc.get("status"), "hrvSummary.status"),
        "baseline_balanced_low_ms": _hrv_value(
            r, baseline.get("balancedLow"), "hrvSummary.baseline.balancedLow"
        ),
        "baseline_balanced_upper_ms": _hrv_value(
            r, baseline.get("balancedUpper"), "hrvSummary.baseline.balancedUpper"
        ),
        "baseline_low_upper_ms": _hrv_value(
            r, baseline.get("lowUpper"), "hrvSummary.baseline.lowUpper"
        ),
        "baseline_marker_value": _float(
            r.value(baseline.get("markerValue"), "hrvSummary.baseline.markerValue", 0.0)
        ),
    }
    copies = _night_window_copies(r, doc)
    readings = r.series(
        _list(doc.get("hrvReadings")),
        "hrvReadings",
        _field_pair("readingTimeGMT", "hrvValue", text=True),
        *HRV_RANGE_MS,
        low_open=True,
    )
    _copy(copies, "night.series.hrv", "hrvReadings", _hrv(readings))
    return {
        "hrv": _summary(HrvSummary, values, r.source),
        "copies": copies,
        "hrv_detail": bool(readings),
    }


def _read_training_readiness(r: _Reader, root: list[Any]) -> _Parts:
    items: list[dict[str, Any]] = []
    for item in root:
        entry = _object(item)
        if entry is None:
            raise _ShapeError
        items.append(entry)
    for entry in items:
        _check_date(_date(entry.get("calendarDate")), r.day)
    kept: list[ReadinessEntry] = []
    non_primary = 0
    for entry in items:
        if _boolean(entry.get("primaryActivityTracker")) is not True:
            non_primary += 1
            continue
        gmt, local = (
            _text_ms(entry.get("timestamp")),
            _text_ms(entry.get("timestampLocal")),
        )
        if gmt is None or local is None:
            r.discard("readiness", PointDiscard.NULL_VALUE)
            continue
        offset = _offset_s(local, gmt)
        if offset is None or not (_ms_in_range(gmt) and _ms_in_range(local)):
            r.discard("readiness", PointDiscard.OUT_OF_RANGE)
            continue
        context = r.label(entry.get("inputContext"), "[*].inputContext")
        if context is not None and context not in READINESS_CONTEXTS:
            r.contexts[("[*].inputContext", context)] += 1
        kept.append(
            ReadinessEntry(
                instant=_instant(gmt, offset),
                input_context=context,
                score=_level(r, entry.get("score"), "[*].score"),
                level=r.label(entry.get("level"), "[*].level"),
                valid_sleep=_boolean(entry.get("validSleep")),
                sleep_score=_level(r, entry.get("sleepScore"), "[*].sleepScore"),
                hrv_weekly_average_ms=_hrv_value(
                    r, entry.get("hrvWeeklyAverage"), "[*].hrvWeeklyAverage"
                ),
                acute_load=_float(
                    r.value(entry.get("acuteLoad"), "[*].acuteLoad", 0.0)
                ),
                source=r.source,
            )
        )
        r.device(entry.get("deviceId"))
    return {
        "readiness": tuple(sorted(kept, key=lambda entry: entry.instant)),
        "readiness_non_primary": non_primary,
    }


_NO_NIGHT_SERIES = NightSeries(None, None, None, None, None, None, None)
_DTO = "dailySleepDTO"


def _night(r: _Reader, doc: dict[str, Any], dto: dict[str, Any]) -> Night | None:
    """La nuit principale, sans séries ni segments : bornes manquantes à demi ;
    décalage ou instant hors plage ; fin au plus le début."""
    bounds = (
        _ms(dto.get("sleepStartTimestampGMT")),
        _ms(dto.get("sleepEndTimestampGMT")),
        _ms(dto.get("sleepStartTimestampLocal")),
        _ms(dto.get("sleepEndTimestampLocal")),
    )
    rem_capable = _boolean(dto.get("deviceRemCapable"))
    durations = {
        name: _float(r.value(dto.get(key), f"{_DTO}.{key}", 0.0))
        for name, key in (
            ("deep_s", "deepSleepSeconds"),
            ("light_s", "lightSleepSeconds"),
            ("rem_s", "remSleepSeconds"),
            ("awake_s", "awakeSleepSeconds"),
            ("unmeasurable_s", "unmeasurableSleepSeconds"),
        )
    }
    if rem_capable is False:
        durations["rem_s"] = None
    confirmation = r.label(
        dto.get("sleepWindowConfirmationType"), f"{_DTO}.sleepWindowConfirmationType"
    )
    if confirmation is not None and confirmation not in CONFIRMATION_TYPES:
        r.confirmations[(f"{_DTO}.sleepWindowConfirmationType", confirmation)] += 1
    window_confirmed = _boolean(dto.get("sleepWindowConfirmed"))
    from_device = _boolean(dto.get("sleepFromDevice"))
    score = _level(
        r,
        _path(dto, "sleepScores", "overall", "value"),
        f"{_DTO}.sleepScores.overall.value",
    )
    avg_stress = _float(
        r.value(
            dto.get("avgSleepStress"), f"{_DTO}.avgSleepStress", *STRESS_LEVEL_RANGE
        )
    )
    avg_hr = _heart_rate_value(r, dto.get("avgHeartRate"), f"{_DTO}.avgHeartRate")
    change = _level(r, doc.get("bodyBatteryChange"), "bodyBatteryChange", -100, 100)
    restless = _int(
        r.value(
            doc.get("restlessMomentsCount"), "restlessMomentsCount", 0, integral=True
        )
    )
    skin = _float(
        r.value(
            doc.get("avgSkinTempDeviationC"),
            "avgSkinTempDeviationC",
            *SKIN_TEMPERATURE_DEVIATION_RANGE_C,
        )
    )
    if all(bound is None for bound in bounds):
        return None
    start_gmt, end_gmt, start_local, end_local = bounds
    if start_gmt is None or end_gmt is None or start_local is None or end_local is None:
        r.discard("night", PointDiscard.NULL_VALUE)
        return None
    start_offset = _offset_s(start_local, start_gmt)
    end_offset = _offset_s(end_local, end_gmt)
    if (
        start_offset is None
        or end_offset is None
        or not all(_ms_in_range(bound) for bound in (start_gmt, end_gmt))
        or not all(_ms_in_range(bound) for bound in (start_local, end_local))
    ):
        r.discard("night", PointDiscard.OUT_OF_RANGE)
        return None
    if end_gmt <= start_gmt:
        r.discard("night", PointDiscard.NOT_INCREASING)
        return None
    return Night(
        start=_instant(start_gmt, start_offset),
        end=_instant(end_gmt, end_offset),
        **durations,
        confirmation=confirmation,
        window_confirmed=window_confirmed,
        from_device=from_device,
        rem_capable=rem_capable,
        segments=(),
        sleep_score=score,
        avg_stress=avg_stress,
        avg_heart_rate_bpm=avg_hr,
        body_battery_change=change,
        restless_moments=restless,
        skin_temperature_deviation_c=skin,
        series=_NO_NIGHT_SERIES,
        source=r.source,
    )


def _nap(r: _Reader, item: Any) -> Nap | None:
    """Une sieste : bornes manquantes ; décalage ou instant hors plage ; fin au plus
    le début ; durée de sommeil nulle ou hors plage."""
    nap = _object(item)
    if nap is None:
        raise _ShapeError
    start, end = (
        _text_ms(nap.get("napStartTimestampGMT")),
        _text_ms(nap.get("napEndTimestampGMT")),
    )
    start_minutes = _number(nap.get("napStartTimeOffset"))
    end_minutes = _number(nap.get("napEndTimeOffset"))
    sleep = _number(nap.get("napTimeSec"))
    source_raw = nap.get("napSource")
    _number(source_raw)
    if start is None or end is None or start_minutes is None or end_minutes is None:
        r.discard("naps", PointDiscard.NULL_VALUE)
        return None
    offsets = [_minutes_offset(minutes) for minutes in (start_minutes, end_minutes)]
    start_offset, end_offset = offsets
    if (
        start_offset is None
        or end_offset is None
        or not _ms_in_range(start)
        or not _ms_in_range(end)
    ):
        r.discard("naps", PointDiscard.OUT_OF_RANGE)
        return None
    if end <= start:
        r.discard("naps", PointDiscard.NOT_INCREASING)
        return None
    if sleep is None:
        r.discard("naps", PointDiscard.NULL_VALUE)
        return None
    sleep_s = _in_range(sleep, 0.0, _INF)
    if sleep_s is None:
        r.discard("naps", PointDiscard.OUT_OF_RANGE)
        return None
    return Nap(
        start=_instant(start, start_offset),
        end=_instant(end, end_offset),
        sleep_s=float(sleep_s),
        nap_source_code=r.code(source_raw, f"{_DTO}.dailyNapDTOS[*].napSource"),
        source=r.source,
    )


def _minutes_offset(minutes: int | float) -> int | None:
    """Un décalage de sieste, en minutes entières, en secondes dans sa plage."""
    whole = _integral(minutes)
    if whole is None:
        return None
    seconds = whole * 60
    low, high = UTC_OFFSET_RANGE_S
    return seconds if low <= seconds <= high else None


def _segments(r: _Reader, items: list[Any] | None) -> StageSegments | None:
    """Les segments de phase : borne ou code nul ; borne hors plage ; code inconnu ;
    durée nulle ou négative ; recouvrement du dernier gardé."""
    path = "sleepLevels"
    kept: list[tuple[int, int, SleepStage]] = []
    for item in items or ():
        segment = _object(item)
        if segment is None:
            raise _ShapeError
        start, end = _text_ms(segment.get("startGMT")), _text_ms(segment.get("endGMT"))
        raw = segment.get("activityLevel")
        level = _number(raw)
        if start is None or end is None or level is None:
            r.discard(path, PointDiscard.NULL_VALUE)
            continue
        if not _ms_in_range(start) or not _ms_in_range(end):
            r.discard(path, PointDiscard.OUT_OF_RANGE)
            continue
        code = _integral(level)
        stage = None if code is None else SLEEP_STAGE_CODES.get(code)
        if stage is None:
            r.unknown(path, "sleepLevels[*].activityLevel", raw)
            continue
        if end <= start:
            r.discard(path, PointDiscard.NOT_INCREASING)
            continue
        if kept and start < kept[-1][1]:
            r.discard(path, PointDiscard.OVERLAPPING_SEGMENT)
            continue
        kept.append((start, end, stage))
    if not kept:
        return None
    return StageSegments(
        tuple(start / 1000 for start, _, _ in kept),
        tuple(end / 1000 for _, end, _ in kept),
        tuple(stage for _, _, stage in kept),
    )


def _read_sleep(r: _Reader, doc: dict[str, Any]) -> _Parts:
    dto_raw = _object(doc.get(_DTO))
    _check_date(_date(_path(dto_raw, "calendarDate")), r.day)
    dto = dto_raw or {}
    night = _night(r, doc, dto)
    naps = [
        nap
        for nap in (_nap(r, item) for item in _list(dto.get("dailyNapDTOS")) or ())
        if nap is not None
    ]
    segments = _segments(r, _list(doc.get("sleepLevels")))
    pair = _field_pair("startGMT", "value")
    series = NightPoints(
        heart_rate=_heart_rate(
            r.series(
                _list(doc.get("sleepHeartRate")),
                "sleepHeartRate",
                pair,
                *HEART_RATE_RANGE_BPM,
            )
        ),
        stress=_stress(
            r.series(
                _list(doc.get("sleepStress")),
                "sleepStress",
                pair,
                *STRESS_LEVEL_RANGE,
                integral=True,
                sentinels=STRESS_SENTINEL_CODES,
                code_path="sleepStress[*].value",
            )
        ),
        body_battery=_body_battery(
            r.series(
                _list(doc.get("sleepBodyBattery")),
                "sleepBodyBattery",
                pair,
                *BODY_BATTERY_LEVEL_RANGE,
                integral=True,
            )
        ),
        hrv=_hrv(
            r.series(
                _list(doc.get("hrvData")), "hrvData", pair, *HRV_RANGE_MS, low_open=True
            )
        ),
        respiration=_respiration(
            r.series(
                _list(doc.get("wellnessEpochRespirationDataDTOList")),
                "wellnessEpochRespirationDataDTOList",
                _field_pair("startTimeGMT", "respirationValue"),
                *RESPIRATION_RANGE_BREATHS_PER_MIN,
                low_open=True,
                sentinels=RESPIRATION_SENTINEL_CODES,
                code_path="wellnessEpochRespirationDataDTOList[*].respirationValue",
            )
        ),
        spo2=_spo2(
            r.series(
                _list(doc.get("wellnessEpochSPO2DataDTOList")),
                "wellnessEpochSPO2DataDTOList",
                _field_pair("epochTimestamp", "spo2Reading", text=True),
                *SPO2_RANGE_PERCENT,
            )
        ),
        restless_moments=_restless(
            r.series(
                _list(doc.get("sleepRestlessMoments")),
                "sleepRestlessMoments",
                pair,
                0,
                _INF,
                integral=True,
            )
        ),
    )
    copies: dict[str, QuantityCopy] = {}
    _copy(
        copies,
        "resting_hr.resting_hr_bpm",
        "restingHeartRate",
        _heart_rate_value(r, doc.get("restingHeartRate"), "restingHeartRate"),
    )
    _copy(
        copies,
        "hrv.last_night_avg_ms",
        "avgOvernightHrv",
        _hrv_value(r, doc.get("avgOvernightHrv"), "avgOvernightHrv"),
    )
    _copy(copies, "hrv.status", "hrvStatus", r.label(doc.get("hrvStatus"), "hrvStatus"))
    _copy(
        copies,
        "respiration.avg_sleep_breaths_per_min",
        f"{_DTO}.averageRespirationValue",
        _respiration_value(
            r, dto.get("averageRespirationValue"), f"{_DTO}.averageRespirationValue"
        ),
    )
    _copy(
        copies,
        "spo2.avg_sleep_spo2_percent",
        f"{_DTO}.averageSpO2Value",
        _spo2_value(r, dto.get("averageSpO2Value"), f"{_DTO}.averageSpO2Value"),
    )
    spo2_summary = _object(doc.get("wellnessSpO2SleepSummaryDTO")) or {}
    _copy(
        copies,
        "spo2.avg_sleep_spo2_percent",
        "wellnessSpO2SleepSummaryDTO.averageSPO2",
        _spo2_value(
            r,
            spo2_summary.get("averageSPO2"),
            "wellnessSpO2SleepSummaryDTO.averageSPO2",
        ),
    )
    for key in ("sleepNeed", "nextSleepNeed", "sleepAlignment"):
        r.device(_path(dto, key, "deviceId"))
    r.device(spo2_summary.get("deviceId"))
    for item in _list(dto.get("dailyNapDTOS")) or ():
        r.device(_path(item, "deviceId"))
    for item in _list(doc.get("wellnessEpochSPO2DataDTOList")) or ():
        r.device(_path(item, "deviceId"))
    return {
        "night": night,
        "naps": tuple(sorted(naps, key=lambda nap: nap.start)),
        "night_series": series,
        "night_segments": segments,
        "copies": copies,
        "versions": {
            "sleep_version": _version(
                r, dto.get("sleepVersion"), f"{_DTO}.sleepVersion"
            ),
            "sleep_respiration_version": _version(
                r, doc.get("respirationVersion"), "respirationVersion"
            ),
        },
    }


_STATUS_TABLE = ("mostRecentTrainingStatus", "latestTrainingStatusData")
_BALANCE_TABLE = ("mostRecentTrainingLoadBalance", "metricsTrainingLoadBalanceDTOMap")


def _choose(r: _Reader, doc: dict[str, Any], keys: tuple[str, str]) -> Any:
    """Le bloc choisi d'une table rangée par appareil : sa seule clé, ou le seul bloc
    principal ; sinon ``_NoPrimaryError``. Lit la clé du bloc choisi (si elle n'est
    faite que de chiffres) puis son ``deviceId``."""
    table = _object(_path(doc, *keys))
    if not table:
        return None
    for block in table.values():
        if not isinstance(block, dict):
            raise _ShapeError
    if len(table) == 1:
        ((key, chosen),) = table.items()
    else:
        primary = [
            (key, block)
            for key, block in table.items()
            if _boolean(block.get("primaryTrainingDevice")) is True
        ]
        if len(primary) != 1:
            raise _NoPrimaryError
        ((key, chosen),) = primary
    if _DIGITS.fullmatch(key):
        r.device(int(key))
    r.device(chosen.get("deviceId"))
    return chosen


def _present(block: dict[str, Any] | None, keys: tuple[str, ...]) -> bool:
    return block is not None and any(block.get(key) is not None for key in keys)


def _status_block(r: _Reader, block: dict[str, Any]) -> TrainingStatusBlock | None:
    n = "mostRecentTrainingStatus.latestTrainingStatusData.<n>"
    day = _date(block.get("calendarDate"))
    stamp = _ms(block.get("timestamp"))
    if stamp is not None and not _ms_in_range(stamp):
        r.discard(f"{n}.timestamp", PointDiscard.OUT_OF_RANGE)
        stamp = None
    timestamp = None if stamp is None else _EPOCH + timedelta(milliseconds=stamp)
    code = _int(
        r.value(block.get("trainingStatus"), f"{n}.trainingStatus", 0, integral=True)
    )
    dto = _object(block.get("acuteTrainingLoadDTO")) or {}
    loads = {
        name: _float(r.value(dto.get(key), f"{n}.acuteTrainingLoadDTO.{key}", 0.0))
        for name, key in (
            ("acute_load", "dailyTrainingLoadAcute"),
            ("chronic_load", "dailyTrainingLoadChronic"),
            ("acute_chronic_ratio", "dailyAcuteChronicWorkloadRatio"),
            ("acwr_percent", "acwrPercent"),
            ("min_chronic_load", "minTrainingLoadChronic"),
            ("max_chronic_load", "maxTrainingLoadChronic"),
        )
    }
    status = r.label(dto.get("acwrStatus"), f"{n}.acuteTrainingLoadDTO.acwrStatus")
    paused = _boolean(block.get("trainingPaused"))
    trend = r.code(block.get("fitnessTrend"), f"{n}.fitnessTrend")
    if day is None:
        return None
    return TrainingStatusBlock(
        day=day,
        file_day=r.day,
        timestamp=timestamp,
        proper_instant=timestamp,
        status_code=code,
        **loads,
        acwr_status=status,
        paused=paused,
        fitness_trend=trend,
        source=r.source,
    )


_BALANCE_KEYS = (
    ("monthly_aerobic_low", "monthlyLoadAerobicLow"),
    ("monthly_aerobic_low_target_min", "monthlyLoadAerobicLowTargetMin"),
    ("monthly_aerobic_low_target_max", "monthlyLoadAerobicLowTargetMax"),
    ("monthly_aerobic_high", "monthlyLoadAerobicHigh"),
    ("monthly_aerobic_high_target_min", "monthlyLoadAerobicHighTargetMin"),
    ("monthly_aerobic_high_target_max", "monthlyLoadAerobicHighTargetMax"),
    ("monthly_anaerobic", "monthlyLoadAnaerobic"),
    ("monthly_anaerobic_target_min", "monthlyLoadAnaerobicTargetMin"),
    ("monthly_anaerobic_target_max", "monthlyLoadAnaerobicTargetMax"),
)


def _balance_block(r: _Reader, block: dict[str, Any]) -> LoadBalanceBlock | None:
    n = "mostRecentTrainingLoadBalance.metricsTrainingLoadBalanceDTOMap.<n>"
    day = _date(block.get("calendarDate"))
    values = {
        name: _float(r.value(block.get(key), f"{n}.{key}", 0.0))
        for name, key in _BALANCE_KEYS
    }
    if day is None:
        return None
    return LoadBalanceBlock(day, r.day, None, **values, source=r.source)


def _read_training_status(r: _Reader, doc: dict[str, Any]) -> _Parts:
    status_raw = _choose(r, doc, _STATUS_TABLE)
    balance_raw = _choose(r, doc, _BALANCE_TABLE)
    refused: list[TrainingStatusKind] = []
    parts: _Parts = {"refused_blocks": refused, "chosen": (status_raw, balance_raw)}
    if status_raw is not None and _present(
        status_raw,
        ("calendarDate", "timestamp", "trainingStatus", "acuteTrainingLoadDTO"),
    ):
        parts["status_block"] = _status_block(r, status_raw)
        if parts["status_block"] is None:
            refused.append(TrainingStatusKind.STATUS)
    balance_keys = ("calendarDate", *(key for _, key in _BALANCE_KEYS))
    if balance_raw is not None and _present(balance_raw, balance_keys):
        parts["load_balance_block"] = _balance_block(r, balance_raw)
        if parts["load_balance_block"] is None:
            refused.append(TrainingStatusKind.LOAD_BALANCE)
    vo2 = _object(_path(doc, "mostRecentVO2Max", "generic"))
    if _present(vo2, ("calendarDate", "vo2MaxPreciseValue", "vo2MaxValue")):
        assert vo2 is not None
        day = _date(vo2.get("calendarDate"))
        path = "mostRecentVO2Max.generic"
        precise = _float(
            r.value(vo2.get("vo2MaxPreciseValue"), f"{path}.vo2MaxPreciseValue", 0.0)
        )
        shown = _float(r.value(vo2.get("vo2MaxValue"), f"{path}.vo2MaxValue", 0.0))
        if day is None:
            refused.append(TrainingStatusKind.VO2_MAX)
        else:
            parts["vo2_max_block"] = Vo2MaxBlock(
                day, r.day, None, precise, shown, r.source
            )
    node = _object(_path(doc, "mostRecentVO2Max", "heatAltitudeAcclimation"))
    path = "mostRecentVO2Max.heatAltitudeAcclimation"
    if _present(
        node, ("heatAcclimationDate", "heatAcclimationPercentage", "heatTrend")
    ):
        assert node is not None
        day = _date(node.get("heatAcclimationDate"))
        percent = _float(
            r.value(
                node.get("heatAcclimationPercentage"),
                f"{path}.heatAcclimationPercentage",
                0.0,
            )
        )
        trend = r.label(node.get("heatTrend"), f"{path}.heatTrend")
        if day is None:
            refused.append(TrainingStatusKind.HEAT_ACCLIMATION)
        else:
            parts["heat_block"] = HeatAcclimationBlock(
                day, r.day, None, percent, trend, r.source
            )
    altitude_keys = (
        "altitudeAcclimationDate",
        "altitudeAcclimation",
        "currentAltitude",
        "altitudeTrend",
    )
    if _present(node, altitude_keys):
        assert node is not None
        day = _date(node.get("altitudeAcclimationDate"))
        acclimation = _float(
            r.value(
                node.get("altitudeAcclimation"),
                f"{path}.altitudeAcclimation",
                *ELEVATION_RANGE_M,
            )
        )
        current = _float(
            r.value(
                node.get("currentAltitude"),
                f"{path}.currentAltitude",
                *ELEVATION_RANGE_M,
            )
        )
        trend = r.label(node.get("altitudeTrend"), f"{path}.altitudeTrend")
        if day is None:
            refused.append(TrainingStatusKind.ALTITUDE_ACCLIMATION)
        else:
            parts["altitude_block"] = AltitudeAcclimationBlock(
                day, r.day, None, acclimation, current, trend, r.source
            )
    return parts


def _training_status_leaves(
    doc: dict[str, Any], chosen: tuple[Any, Any]
) -> dict[str, Any]:
    """Le document de Training Status dont chaque table rangée par appareil est
    remplacée par ``{"<n>": bloc choisi}`` (ou ``{}``) : jamais la clé."""
    replaced = dict(doc)
    for (outer, table), block in zip(
        (_STATUS_TABLE, _BALANCE_TABLE), chosen, strict=True
    ):
        node = replaced.get(outer)
        if isinstance(node, dict) and table in node:
            replaced[outer] = {**node, table: {} if block is None else {"<n>": block}}
    return replaced


# ---------------------------------------------------------------------------
# La lecture d'un fichier
# ---------------------------------------------------------------------------

_LIST_FAMILIES = frozenset({DayFamily.BODY_BATTERY, DayFamily.TRAINING_READINESS})

_READERS: Mapping[DayFamily, Callable[[_Reader, Any], _Parts]] = MappingProxyType(
    {
        DayFamily.SLEEP: _read_sleep,
        DayFamily.HRV: _read_hrv,
        DayFamily.RESTING_HR: _read_resting_hr,
        DayFamily.HEART_RATE: _read_heart_rate,
        DayFamily.BODY_BATTERY: _read_body_battery,
        DayFamily.STRESS: _read_stress,
        DayFamily.RESPIRATION: _read_respiration,
        DayFamily.SPO2: _read_spo2,
        DayFamily.DAILY_SUMMARY: _read_daily_summary,
        DayFamily.TRAINING_READINESS: _read_training_readiness,
        DayFamily.TRAINING_STATUS: _read_training_status,
    }
)

_CONTENT = (
    "window",
    "wellness_data",
    "night",
    "resting_hr",
    "hrv",
    "respiration",
    "spo2",
    "stress",
    "body_battery",
    "activity_totals",
    "status_block",
    "load_balance_block",
    "vo2_max_block",
    "heat_block",
    "altitude_block",
    "night_segments",
)


def _has_content(parts: _Parts) -> bool:
    if any(parts.get(name) is not None for name in _CONTENT):
        return True
    if parts.get("naps") or parts.get("readiness") or parts.get("copies"):
        return True
    if parts.get("readiness_non_primary") or parts.get("refused_blocks"):
        return True
    day: DayPoints = parts.get("day_series", DayPoints())
    night: NightPoints = parts.get("night_series", NightPoints())
    return any(
        getattr(day, item.name) is not None for item in dataclasses.fields(day)
    ) or any(
        getattr(night, item.name) is not None for item in dataclasses.fields(night)
    )


def _detail(parts: _Parts) -> bool:
    """Au moins une série fine que Garmin efface, non vide (SpO2 exclue)."""
    day: DayPoints = parts.get("day_series", DayPoints())
    night: NightPoints = parts.get("night_series", NightPoints())
    return bool(
        day.heart_rate
        or day.stress
        or day.body_battery
        or day.respiration
        or parts.get("night_segments")
        or night.heart_rate
        or night.stress
        or night.body_battery
        or night.hrv
        or night.respiration
        or night.restless_moments
        or parts.get("hrv_detail")
    )


def _decode(data: bytes) -> Any:
    try:
        return json.loads(data.decode("utf-8"))
    except (ValueError, RecursionError):
        # UnicodeDecodeError, JSONDecodeError, et l'entier de plus de 4 300 chiffres.
        raise _UnreadableError from None


class _UnreadableError(Exception):
    """Les octets ne se lisent pas en JSON (UTF-8)."""


def read_family(
    family: DayFamily, data: bytes, day: date, source: SourceRef
) -> FamilyRead:
    """Lit un fichier ``<famille>/<day>.json`` d'un export, depuis ses octets ; chaque
    sous-objet porte ``source``, la provenance de ce fichier. Fonction pure.

    **Refus**, le premier rencontré en lisant le document (``FamilyRead.refusal``,
    rien d'autre n'est rendu), dans cet ordre pour les quatre premiers ; les deux
    derniers se rencontrent dans l'ordre de la lecture (pour Training Status : la
    table des statuts, puis celle de l'équilibre, puis les champs des blocs ; une
    forme fausse dans la table des statuts passe donc avant un principal manquant
    dans celle de l'équilibre) :

    1. ``unreadable_json`` : les octets ne se décodent pas en UTF-8 strict (une marque
       d'ordre des octets en tête est refusée), ou le texte ne se lit pas par
       ``json.loads`` tel quel : la grammaire du JSON, plus les jetons ``NaN``,
       ``Infinity`` et ``-Infinity``, admis — ils donnent une valeur non finie, écartée
       ensuite comme hors de sa plage (``out_of_range`` ; dans une série à codes,
       ``-Infinity`` est un négatif : ``unknown_code``) ; une clé répétée, la dernière
       l'emporte ; ne se lisent pas : un caractère de contrôle brut dans un texte, un
       entier de plus de 4 300 chiffres (la limite de ``int``), une imbrication trop
       profonde (``RecursionError``) ;
    2. un document ``{}`` ou ``[]`` n'est pas un refus : la famille est absente ce
       jour-là (``empty``), quelle que soit la forme de sa racine ;
    3. ``unexpected_shape`` : racine d'un autre type que celui de la famille (une liste
       pour ``body_battery`` et ``training_readiness``, un objet pour les autres) ;
    4. ``date_mismatch`` : la date que porte le document n'est pas ``day`` —
       ``calendarDate`` de la racine (``heart_rate``, ``stress``, ``respiration``,
       ``spo2``, ``daily_summary``), de ``dailySleepDTO`` (``sleep``), de
       ``hrvSummary`` (``hrv``), de chaque entrée (``resting_hr``,
       ``training_readiness``), ``date`` de chaque élément (``body_battery``) ;
       Training Status n'a pas de date de document (chaque bloc a la sienne) ;
    5. ``no_primary_device`` : une table de Training Status rangée par appareil a
       plusieurs clés sans exactement un bloc ``primaryTrainingDevice`` vrai (une seule
       clé : son bloc, principal ou non) ;
    6. ``unexpected_shape`` : un champ lu d'un autre type JSON que le sien (objet,
       liste, texte, nombre — un booléen n'en est pas un —, booléen ; instant en
       millisecondes entier ; horodatage texte ``AAAA-MM-JJTHH:MM:SS`` avec ou sans
       fraction d'un à trois chiffres ; date ``AAAA-MM-JJ``), un point en colonnes
       trop court, ou une liste de descripteurs de colonnes qui contredit la disposition
       lue (``COLUMN_LAYOUTS``).

    **Instants** : les millisecondes se lisent exactement (``1970-01-01 UTC`` +
    ``timedelta(milliseconds=…)``) ; les textes sont lus comme GMT. Un décalage est
    local − GMT, lu sur les deux écritures du même instant (millisecondes d'heure
    murale de ``sleep``, textes ``…Local``), en secondes entières dans
    ``UTC_OFFSET_RANGE_S``. Celui d'une sieste est écrit en minutes
    (``napStartTimeOffset``, ``napEndTimeOffset``) : un nombre entier de minutes — un
    entier JSON, ou un flottant fini de valeur entière (``60.0`` vaut 60) —, multiplié
    par 60 puis contrôlé dans ``UTC_OFFSET_RANGE_S`` (de −720 à 840 min, bornes
    comprises) ; un flottant non entier (``60.5``, même si ses secondes sont entières),
    une valeur non finie ou hors de la plage écartent la sieste (``out_of_range``).
    Les séries sont en secondes UTC depuis l'époque
    (``ms / 1000``) ; la fenêtre du jour, la nuit, les siestes, les entrées sont
    *aware*, dans leur décalage ; l'horodatage d'un bloc « statut » est en UTC (la
    source n'en donne pas l'heure locale).

    **Écarts** (``discards``, par chemin et motif ; rien n'est corrigé) :

    - un point de série, dans cet ordre : instant nul (``null_value``) ou hors de sa
      plage (``out_of_range``) ; valeur nulle (``null_value``) ; négative dans une série
      à codes (stress, respiration) : code connu gardé comme code, sinon
      ``unknown_code`` (compté aussi avec sa valeur, ``unknown_codes``) ; hors de la
      plage de sa grandeur (``out_of_range`` : non finie, hors bornes, non entière pour
      un niveau ou un compte ; **zéro n'est écarté que hors de la plage**) ; puis
      l'instant contre le dernier point gardé : égal, ``duplicate_instant`` (le premier
      gardé), antérieur, ``not_increasing`` ;
    - un point de Body Battery du jour : le statut avant le niveau (statut nul,
      ``null_value`` ; inconnu, ``unknown_code``) ;
    - un segment de phase : borne ou code nul, borne hors plage, code inconnu, durée
      nulle ou négative (``not_increasing``), recouvrement du dernier gardé
      (``overlapping_segment``) ;
    - la nuit (série ``night``) et chaque sieste (série ``naps``) : borne manquante à
      demi (``null_value``), décalage ou instant hors plage (``out_of_range``), fin au
      plus le début (``not_increasing``) — l'épisode est écarté, le fichier gardé ;
    - la fenêtre du jour (série ``window``) : manquante à demi, décalage hors plage ou
      date locale du début autre que ``day``, fin GMT avant le début ;
    - une entrée de Training Readiness (série ``readiness``) : horodatage manquant ou
      décalage hors plage ;
    - une valeur d'un résumé, d'une copie ou d'un bloc hors de sa plage : absente,
      comptée sous le chemin de son champ ; un code texte blanc : absent,
      ``null_value`` ; une entrée de plus dans ``resting_hr`` ou ``body_battery`` (un
      jour, une valeur) : ``duplicate_instant``.

    Un type de confirmation inconnu (``CONFIRMATION_TYPES``) et un contexte de Training
    Readiness inconnu (``READINESS_CONTEXTS``) sont gardés et comptés à part.

    **Ne se lisent pas** : les champs ``tomorrow…`` (la nuit de J + 1), le besoin de
    sommeil, l'alignement, les textes de conseil, les événements de Body Battery, la
    série de mouvement, les identifiants (sauf ceux d'appareil, en mémoire), les
    calories ; ni dans les morceaux, ni dans ``fields``.
    """
    refused = FamilyRead(family, day, source)
    try:
        document = _decode(data)
    except _UnreadableError:
        return dataclasses.replace(refused, refusal=DayFileRefusal.UNREADABLE_JSON)
    if document == {} or document == []:
        return dataclasses.replace(refused, empty=True)
    expected = list if family in _LIST_FAMILIES else dict
    if not isinstance(document, expected):
        return dataclasses.replace(refused, refusal=DayFileRefusal.UNEXPECTED_SHAPE)
    reader = _Reader(family, day, source)
    try:
        parts = _READERS[family](reader, document)
    except _DateMismatchError:
        return dataclasses.replace(refused, refusal=DayFileRefusal.DATE_MISMATCH)
    except _NoPrimaryError:
        return dataclasses.replace(refused, refusal=DayFileRefusal.NO_PRIMARY_DEVICE)
    except _ShapeError:
        return dataclasses.replace(refused, refusal=DayFileRefusal.UNEXPECTED_SHAPE)
    leaves: dict[str, str] = {}
    if family is DayFamily.TRAINING_STATUS:
        assert isinstance(document, dict)
        _leaves(_training_status_leaves(document, parts.pop("chosen")), "", leaves)
    else:
        _leaves(document, "", leaves)
    series_versions = parts.pop("series_versions", ())
    versions = AlgorithmVersions(
        **{
            "sleep_version": None,
            "sleep_respiration_version": None,
            "respiration_version": None,
            "summary_respiration_version": None,
            "summary_body_battery_version": None,
            **parts.pop("versions", {}),
        },
        body_battery_series_versions=series_versions,
    )
    hrv_detail = parts.get("hrv_detail", False)
    detail = _detail(parts) or hrv_detail
    parts.pop("hrv_detail", None)
    empty = not _has_content(parts)
    copies = _ordered_copies(family, parts.pop("copies", {}))
    parts["refused_blocks"] = tuple(
        kind for kind in TrainingStatusKind if kind in parts.get("refused_blocks", ())
    )
    return FamilyRead(
        family=family,
        day=day,
        source=source,
        empty=empty and not copies,
        **parts,
        versions=versions,
        copies=copies,
        device_ids=tuple(reader.devices),
        discards=reader.discard_counts(),
        unknown_codes=reader.counts(reader.codes),
        unknown_confirmations=reader.counts(reader.confirmations),
        unknown_contexts=reader.counts(reader.contexts),
        has_detail=detail,
        fields=MappingProxyType(leaves),
    )
