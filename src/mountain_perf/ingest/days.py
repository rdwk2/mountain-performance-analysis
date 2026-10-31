"""L'ingestion des jours (AN2-1) : les familles journalières de tous les exports Garmin
→ les documents d'``interim/days/`` (``DayRecord`` par jour, ``TrainingStatusHistory``,
``DaysReport``).

Deux temps, comme les activités (``mountain_perf.ingest.export``) :

1. ``load_export_days`` liste les fichiers journaliers d'un export et le refuse s'il
   contredit son instant d'acquisition (rien n'est écrit, le message nomme l'export) ;
2. ``build_days`` calcule tout, **jour par jour** (toutes les familles de tous les
   exports pour une date, puis le brut est oublié), avant la moindre écriture : l'état
   du jour dans chaque export, l'export de référence, le document du jour et ses
   emprunts, les écarts entre exports, les copies contrôlées, les blocs de Training
   Status, les rangs d'appareil, le rapport. Il ne lit que les octets des fichiers.

L'écriture est celle de ``mountain_perf.ingest.interim.write_days``, appelée par
``ingest_export`` après ``write_activities``.

Sans dépendance : bibliothèque standard, ``mountain_perf.schemas``,
``mountain_perf.validation`` et ``mountain_perf.ingest.families`` (la lecture d'un
fichier) ; ni fitdecode, ni ``export``, ni les vues. Les identifiants d'appareil vus
restent en mémoire, le temps de leur donner un rang ; aucun n'est écrit.

Les constantes déclarées ici sont des seuils et des listes de l'ingestion : aucun
seuil des vues des jours.
"""

from __future__ import annotations

import dataclasses
import hashlib
import re
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta, timezone
from itertools import pairwise
from pathlib import Path
from types import MappingProxyType
from typing import Any

from mountain_perf.ingest.families import (
    BodyBatteryPoints,
    FamilyRead,
    HeartRatePoints,
    HrvPoints,
    QuantityCopy,
    RespirationPoints,
    RestlessMomentPoints,
    SpO2Points,
    StageSegments,
    StressPoints,
    read_family,
)
from mountain_perf.schemas import (
    DAY_WINDOW_FAMILIES,
    AlgorithmVersions,
    AltitudeAcclimationBlock,
    BlockCount,
    BlockFieldCount,
    BodyBatterySeries,
    BodyBatteryStatus,
    BorrowingCount,
    BorrowingRefusal,
    BorrowingRefusalCount,
    CodeCount,
    ComparisonClass,
    ComparisonCount,
    CopyDisagreementCount,
    DayBoundaryGap,
    DayFamily,
    DayFileRefused,
    DayRecord,
    DaySeries,
    DaysExportReport,
    DaysReport,
    DayState,
    ExportDayCount,
    FamilyDayCount,
    HeartRateSeries,
    HeatAcclimationBlock,
    HrvSeries,
    LoadBalanceBlock,
    Night,
    NightSeries,
    PointDiscard,
    PointDiscardCount,
    ReadFile,
    ReadinessCopyCount,
    RespirationSeries,
    RestlessMomentsSeries,
    SleepSegment,
    SleepStage,
    SourceRef,
    SpO2Series,
    StressSeries,
    TrainingStatusBlock,
    TrainingStatusHistory,
    TrainingStatusKind,
    Vo2MaxBlock,
    WindowEdgeCount,
)

ACQUISITION_TOLERANCE_S = 3600.0
"""L'avance tolérée de la fin des données sur l'instant d'acquisition d'un export, en
secondes : la fin des données du dernier jour d'un export à **plus de** 3 600 s après
son instant d'acquisition (strictement) refuse l'export ; à 3 600 s exactement, il est
admis."""

NIGHT_TOLERANCE_S = 210.0
"""La tolérance de l'égalité de la nuit, ``end − start`` = phases + éveil + non
mesurable, en secondes : tirée du format seul, jamais des écarts observés — cinq durées
arrondies à la minute, un demi-pas chacune (5 × 30 s), plus un pas pour les bornes
(60 s). Un écart **strictement** au-delà se compte
(``DaysReport.night_equality_violations``) ; la même tolérance juge, pour un emprunt de
segments, chaque durée par phase contre le résumé de la référence."""

COMPARISON_IGNORED_FIELDS: Mapping[DayFamily, tuple[str, ...]] = MappingProxyType(
    {
        DayFamily.DAILY_SUMMARY: ("lastSyncTimestampGMT",),
        DayFamily.HRV: ("hrvSummary.createTimeStamp",),
    }
)
"""Les champs que les comparaisons entre exports ignorent : des métadonnées que Garmin
réécrit à chaque export sans qu'elles soient des mesures du jour.

- ``daily_summary.lastSyncTimestampGMT`` : l'instant de la dernière synchronisation du
  compte, celui du moment de l'export, pas du jour ;
- ``hrv.hrvSummary.createTimeStamp`` : l'instant où le serveur a écrit le résumé HRV,
  recalculé par Garmin, pas un instant de la nuit.

Parcourus et laissés comparés : les valeurs « dernières » du jour
(``latestRespiration…``, ``latestSpo2…``, ``latestSpO2…``) et les moyennes sur sept
jours (``lastSevenDays…``), qui sont des mesures du jour, figées une fois le jour fini ;
les réglages du compte (``privacyProtected``, ``rule``, ``source``), qui ne changent pas
d'un export à l'autre. ``createTimestampGMT`` et ``updateTimestampGMT`` des siestes sont
dans une liste, qui se compare comme une seule feuille (toujours nuls dans les exports
parcourus). ``training_status`` n'entre pas dans ces comparaisons
(``lastPrimarySyncDate`` compris) : ses écarts se comptent par bloc, sorte et champ
(``DaysReport.block_differences_between_exports``)."""

FAMILY_PIECES: Mapping[DayFamily, tuple[str, ...]] = MappingProxyType(
    {
        DayFamily.SLEEP: ("night", "naps"),
        DayFamily.HRV: ("hrv",),
        DayFamily.RESTING_HR: ("resting_hr",),
        DayFamily.HEART_RATE: ("series.heart_rate",),
        DayFamily.BODY_BATTERY: (),
        DayFamily.STRESS: ("series.stress", "series.body_battery"),
        DayFamily.RESPIRATION: ("respiration", "series.respiration"),
        DayFamily.SPO2: ("spo2", "series.spo2"),
        DayFamily.DAILY_SUMMARY: (
            "wellness_data",
            "stress",
            "body_battery",
            "activity_totals",
        ),
        DayFamily.TRAINING_READINESS: ("readiness",),
        DayFamily.TRAINING_STATUS: (),
    }
)
"""Les morceaux d'un ``DayRecord`` que porte chaque famille, par leur chemin dans le
document (celui de ``BorrowingCount.piece``). La nuit emportée avec ``sleep`` garde ses
segments et ses séries. ``body_battery`` ne porte que des copies contrôlées, et
``training_status`` ses blocs, choisis bloc par bloc : ni l'une ni l'autre ne
s'empruntent."""

BLOCK_FIELDS: Mapping[TrainingStatusKind, tuple[tuple[str, str], ...]] = (
    MappingProxyType(
        {
            TrainingStatusKind.STATUS: (
                ("timestamp", "timestamp"),
                ("status_code", "trainingStatus"),
                ("acute_load", "acuteTrainingLoadDTO.dailyTrainingLoadAcute"),
                ("chronic_load", "acuteTrainingLoadDTO.dailyTrainingLoadChronic"),
                (
                    "acute_chronic_ratio",
                    "acuteTrainingLoadDTO.dailyAcuteChronicWorkloadRatio",
                ),
                ("acwr_percent", "acuteTrainingLoadDTO.acwrPercent"),
                ("acwr_status", "acuteTrainingLoadDTO.acwrStatus"),
                ("min_chronic_load", "acuteTrainingLoadDTO.minTrainingLoadChronic"),
                ("max_chronic_load", "acuteTrainingLoadDTO.maxTrainingLoadChronic"),
                ("paused", "trainingPaused"),
                ("fitness_trend", "fitnessTrend"),
            ),
            TrainingStatusKind.LOAD_BALANCE: (
                ("monthly_aerobic_low", "monthlyLoadAerobicLow"),
                ("monthly_aerobic_low_target_min", "monthlyLoadAerobicLowTargetMin"),
                ("monthly_aerobic_low_target_max", "monthlyLoadAerobicLowTargetMax"),
                ("monthly_aerobic_high", "monthlyLoadAerobicHigh"),
                ("monthly_aerobic_high_target_min", "monthlyLoadAerobicHighTargetMin"),
                ("monthly_aerobic_high_target_max", "monthlyLoadAerobicHighTargetMax"),
                ("monthly_anaerobic", "monthlyLoadAnaerobic"),
                ("monthly_anaerobic_target_min", "monthlyLoadAnaerobicTargetMin"),
                ("monthly_anaerobic_target_max", "monthlyLoadAnaerobicTargetMax"),
            ),
            TrainingStatusKind.VO2_MAX: (
                ("vo2_max_precise_ml_kg_min", "vo2MaxPreciseValue"),
                ("vo2_max_ml_kg_min", "vo2MaxValue"),
            ),
            TrainingStatusKind.HEAT_ACCLIMATION: (
                ("heat_acclimation_percent", "heatAcclimationPercentage"),
                ("heat_trend", "heatTrend"),
            ),
            TrainingStatusKind.ALTITUDE_ACCLIMATION: (
                ("acclimation_altitude_m", "altitudeAcclimation"),
                ("current_altitude_m", "currentAltitude"),
                ("altitude_trend", "altitudeTrend"),
            ),
        }
    )
)
"""Les champs d'un bloc de Training Status que comparent les écarts d'un même bloc
(dans un export, entre exports) : chaque champ ingéré du contrat, avec son chemin dans
le bloc de la source (``BlockFieldCount.field_path``). La date propre, le jour du
fichier, l'instant propre et la provenance ne se comparent pas ; les champs que
l'ingestion ne lit pas (phrases, identifiants) non plus."""


class ExportDaysError(Exception):
    """Un export que l'ingestion des jours refuse ; rien n'est écrit. Le message
    commence par ``raw/garmin/<export>/ : `` ; ``ingest_export`` le relève en
    ``IngestError``, au même message."""


@dataclass(frozen=True)
class DayFile:
    """Un fichier journalier d'un export : son jour (celui de son nom), sa famille, son
    chemin (en mémoire seulement)."""

    day: date
    family: DayFamily
    path: Path = field(repr=False)


@dataclass(frozen=True)
class ExportDays:
    """Les fichiers journaliers d'un export, listés et vérifiés par
    ``load_export_days`` : son nom, son instant d'acquisition (tel que lu, décalage
    compris), ses fichiers triés par (jour, famille dans l'ordre de ``DayFamily``)."""

    name: str
    retrieved_at: datetime
    files: tuple[DayFile, ...] = field(repr=False)


@dataclass(frozen=True)
class DaysSummary:
    """Ce que l'ingestion des jours a fait, en nombres (``mperf ingest``).

    - ``days`` — les documents de jour écrits ;
    - ``reference_days`` — les jours par export de référence (ceux du rapport) ;
    - ``states`` — les jours par état, les quatre états dans l'ordre de ``DayState``,
      zéro compris ;
    - ``borrowings``, ``borrowing_refusals`` — les morceaux empruntés, les emprunts
      refusés (sommes des comptes du rapport, en morceaux × jours) ;
    - ``revisions``, ``degradations``, ``set_apart`` — les écarts entre exports de
      chaque classe, en champs × jours (sommes de ``ComparisonCount.days``) ;
    - ``refused_files`` — les fichiers journaliers refusés ;
    - ``point_discards`` — les points, segments, épisodes et valeurs écartés (somme) ;
    - ``unknown_codes`` — les apparitions de codes et de contextes de Training
      Readiness inconnus (somme des comptes de ``DaysReport.unknown_codes``) ; les
      types de confirmation inconnus n'y sont pas ;
    - ``training_status_blocks`` — les blocs de Training Status écrits ;
    - ``blocks_without_proper_instant`` — parmi eux, ceux sans instant propre.
    """

    days: int
    reference_days: tuple[ExportDayCount, ...]
    states: tuple[tuple[DayState, int], ...]
    borrowings: int
    borrowing_refusals: int
    revisions: int
    degradations: int
    set_apart: int
    refused_files: int
    point_discards: int
    unknown_codes: int
    training_status_blocks: int
    blocks_without_proper_instant: int


@dataclass(frozen=True)
class DaysIngestion:
    """Les documents d'``interim/days/`` calculés par ``build_days``, prêts pour
    ``write_days``, et leur résumé."""

    records: tuple[DayRecord, ...]
    history: TrainingStatusHistory
    report: DaysReport
    summary: DaysSummary


_FILE_NAME = re.compile(r"([0-9]{4})-([0-9]{2})-([0-9]{2})\.json")
_FAMILY_RANK = {family: rank for rank, family in enumerate(DayFamily)}
_DAY = timedelta(days=1)
_EPOCH = datetime(1970, 1, 1, tzinfo=UTC)
_MS = timedelta(milliseconds=1)


def _label(name: str) -> str:
    """Le dossier d'un export, tel que les messages le nomment."""
    return f"raw/garmin/{name}/"


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _source(file: DayFile, data: bytes, retrieved_at: datetime) -> SourceRef:
    return SourceRef(
        f"garmin_{file.family.value}",
        f"{file.day.isoformat()}.json",
        _sha256(data),
        retrieved_at,
    )


def _read(file: DayFile, retrieved_at: datetime) -> tuple[FamilyRead, str]:
    """La lecture d'un fichier journalier, et l'empreinte de ses octets."""
    data = file.path.read_bytes()
    source = _source(file, data, retrieved_at)
    return read_family(file.family, data, file.day, source), source.content_hash


def _day_window(reads: Mapping[DayFamily, FamilyRead]) -> tuple[DayFamily, Any] | None:
    """La fenêtre du jour d'un export : celle de ``daily_summary``, sinon de la
    première famille de ``DAY_WINDOW_FAMILIES`` qui en porte une."""
    for family in DAY_WINDOW_FAMILIES:
        read = reads.get(family)
        if read is not None and read.window is not None:
            return family, read.window
    return None


def load_export_days(export_dir: Path, name: str, retrieved_at: datetime) -> ExportDays:
    """Les fichiers journaliers de l'export rangé dans ``export_dir``
    (``raw/garmin/<name>/``), d'instant d'acquisition ``retrieved_at``.

    **La liste** : ``<famille>/<AAAA-MM-JJ>.json``, pour chaque famille de
    ``DayFamily`` dont le dossier existe ; un dossier qui n'est pas une famille
    journalière (``activities/``, ``activity_fit/``, ``range/``, le profil…) est
    ignoré, comme, dans le dossier d'une famille, un sous-dossier ou un fichier dont le
    nom n'est pas une date valide suivie de ``.json`` (``notes.txt``,
    ``2001-02-30.json``, ``2001-03-10.JSON``). Triée par (jour, famille dans l'ordre de
    ``DayFamily``). Un export sans famille journalière est admis : sa liste est
    vide.

    **Les refus** (``ExportDaysError``, le message commençant par
    ``raw/garmin/<name>/ : ``, rien n'est écrit), dans cet ordre :

    1. un fichier journalier daté après la date locale de ``retrieved_at`` (dans son
       décalage) : « … un fichier journalier est daté après le jour de l'acquisition
       de l'export ; acquisition.json est faux. » ;
    2. la fin des données (``fin_donnees``) du dernier jour qui porte une fenêtre du
       jour (lue comme celle du document du jour) à **plus de**
       ``ACQUISITION_TOLERANCE_S`` après ``retrieved_at`` : « … la fin des données de
       son dernier jour dépasse l'instant d'acquisition de plus d'une heure ;
       acquisition.json est faux. » (à ``ACQUISITION_TOLERANCE_S`` exactement, admis).

    Seuls les fichiers des familles qui portent une fenêtre du jour, au dernier jour qui
    en porte une, se lisent ici ; ``build_days`` lit le reste, jour par jour.
    """
    files: list[DayFile] = []
    for family in DayFamily:
        folder = export_dir / family.value
        if not folder.is_dir():
            continue
        for path in folder.iterdir():
            match = _FILE_NAME.fullmatch(path.name)
            if match is None or not path.is_file():
                continue
            try:
                day = date(*(int(part) for part in match.groups()))
            except ValueError:
                continue
            files.append(DayFile(day, family, path))
    files.sort(key=lambda file: (file.day, _FAMILY_RANK[file.family]))
    if any(file.day > retrieved_at.date() for file in files):
        raise ExportDaysError(
            f"{_label(name)} : un fichier journalier est daté après le jour de "
            "l'acquisition de l'export ; acquisition.json est faux."
        )
    window_files = [file for file in files if file.family in DAY_WINDOW_FAMILIES]
    for day in sorted({file.day for file in window_files}, reverse=True):
        reads = {
            file.family: _read(file, retrieved_at)[0]
            for file in window_files
            if file.day == day
        }
        found = _day_window(reads)
        if found is None:
            continue
        limit = retrieved_at + timedelta(seconds=ACQUISITION_TOLERANCE_S)
        if found[1].data_end > limit:
            raise ExportDaysError(
                f"{_label(name)} : la fin des données de son dernier jour dépasse "
                "l'instant d'acquisition de plus d'une heure ; acquisition.json est "
                "faux."
            )
        break
    return ExportDays(name, retrieved_at, tuple(files))


# ---------------------------------------------------------------------------
# Un jour dans un export
# ---------------------------------------------------------------------------

_DAY_SERIES: tuple[tuple[str, DayFamily, str], ...] = (
    ("heart_rate", DayFamily.HEART_RATE, "heartRateValues"),
    ("stress", DayFamily.STRESS, "stressValuesArray"),
    ("body_battery", DayFamily.STRESS, "bodyBatteryValuesArray"),
    ("respiration", DayFamily.RESPIRATION, "respirationValuesArray"),
    ("spo2", DayFamily.SPO2, "spO2HourlyAverages"),
)
"""Les séries du jour : leur nom dans ``DaySeries``, leur famille, leur chemin dans la
source."""

_NIGHT_SERIES: tuple[tuple[str, str], ...] = (
    ("heart_rate", "sleepHeartRate"),
    ("stress", "sleepStress"),
    ("body_battery", "sleepBodyBattery"),
    ("hrv", "hrvData"),
    ("respiration", "wellnessEpochRespirationDataDTOList"),
    ("spo2", "wellnessEpochSPO2DataDTOList"),
    ("restless_moments", "sleepRestlessMoments"),
)
"""Les séries de la nuit : leur nom dans ``NightSeries``, leur chemin dans ``sleep``."""

_SEGMENTS_PATH = "sleepLevels"
_NIGHT_COPY_FAMILIES = (DayFamily.HRV, DayFamily.RESPIRATION, DayFamily.SPO2)
_NOT_BORROWED = (DayFamily.BODY_BATTERY, DayFamily.TRAINING_STATUS)
_STAGE_DURATIONS = (
    (SleepStage.DEEP, "deep_s"),
    (SleepStage.LIGHT, "light_s"),
    (SleepStage.REM, "rem_s"),
    (SleepStage.AWAKE, "awake_s"),
    (SleepStage.UNMEASURABLE, "unmeasurable_s"),
)

_SERIES_TYPES: Mapping[type, type] = MappingProxyType(
    {
        HeartRatePoints: HeartRateSeries,
        StressPoints: StressSeries,
        BodyBatteryPoints: BodyBatterySeries,
        RespirationPoints: RespirationSeries,
        SpO2Points: SpO2Series,
        HrvPoints: HrvSeries,
        RestlessMomentPoints: RestlessMomentsSeries,
    }
)


def _ms(epoch_s: float) -> int:
    """Les millisecondes exactes d'un instant lu (``epoch_s`` : ``ms / 1000``)."""
    return round(epoch_s * 1000)


def _instant_ms(instant: datetime) -> int:
    return (instant - _EPOCH) // _MS


def _relative(points: Any, origin: datetime, source: SourceRef) -> Any:
    """Une série en instants absolus, en secondes depuis ``origin``, exactement."""
    base = _instant_ms(origin)
    values = [
        getattr(points, item.name)
        for item in dataclasses.fields(points)
        if item.name != "epoch_s"
    ]
    times = tuple((_ms(epoch) - base) / 1000 for epoch in points.epoch_s)
    return _SERIES_TYPES[type(points)](times, *values, source)


def _point_count(points: Any) -> int:
    return 0 if points is None else len(points.epoch_s)


@dataclass
class _ExportDay:
    """Un jour dans un export : ses lectures présentes, sa fenêtre, son état, son
    détail."""

    position: int
    name: str
    reads: dict[DayFamily, FamilyRead]
    window_family: DayFamily | None
    window: Any
    state: DayState
    detail: bool


def _measured_sample(reads: Mapping[DayFamily, FamilyRead]) -> bool:
    """Un échantillon mesuré dans les séries du jour : un point de FC ou de SpO2, un
    niveau de stress, une fréquence respiratoire, un Body Battery ``measured``."""
    for read in reads.values():
        series = read.day_series
        if series.heart_rate is not None or series.spo2 is not None:
            return True
        if series.stress is not None and any(
            level is not None for level in series.stress.stress_level
        ):
            return True
        if series.respiration is not None and any(
            value is not None for value in series.respiration.breaths_per_min
        ):
            return True
        if series.body_battery is not None and any(
            status is BodyBatteryStatus.MEASURED
            for status in series.body_battery.status
        ):
            return True
    return False


def _export_day(
    position: int, name: str, reads: dict[DayFamily, FamilyRead]
) -> _ExportDay:
    """L'état du jour dans un export, dans l'ordre de ``DayState``."""
    found = _day_window(reads)
    detail = any(read.has_detail for read in reads.values())
    if found is None:
        return _ExportDay(position, name, reads, None, None, DayState.EMPTY, detail)
    family, window = found
    summary = reads.get(DayFamily.DAILY_SUMMARY)
    indicator = None if summary is None else summary.wellness_data
    sleep = reads.get(DayFamily.SLEEP)
    has_night = sleep is not None and sleep.night is not None
    if indicator is False or (
        indicator is None and not _measured_sample(reads) and not has_night
    ):
        state = DayState.NO_MEASUREMENT
    elif window.data_end < window.start + _DAY:
        state = DayState.TRUNCATED
    else:
        state = DayState.COMPLETE
    return _ExportDay(position, name, reads, family, window, state, detail)


def _reference(days: Sequence[_ExportDay]) -> _ExportDay:
    """L'export de référence d'un jour : le plus récent où il est ``complete`` et a son
    détail ; sinon le plus récent ``complete`` ; puis ``truncated`` ; puis
    ``no_measurement`` ; puis le plus récent qui le porte."""
    recent = sorted(days, key=lambda item: item.position, reverse=True)
    for accept in (
        lambda item: item.state is DayState.COMPLETE and item.detail,
        lambda item: item.state is DayState.COMPLETE,
        lambda item: item.state is DayState.TRUNCATED,
        lambda item: item.state is DayState.NO_MEASUREMENT,
    ):
        for item in recent:
            if accept(item):
                return item
    return recent[0]


# ---------------------------------------------------------------------------
# Le document d'un jour et ses emprunts
# ---------------------------------------------------------------------------


def _pieces(family: DayFamily, read: FamilyRead) -> list[str]:
    """Les morceaux de ``FAMILY_PIECES`` que porte une lecture."""
    carried = {
        "night": read.night is not None,
        "naps": bool(read.naps),
        "hrv": read.hrv is not None,
        "resting_hr": read.resting_hr is not None,
        "series.heart_rate": read.day_series.heart_rate is not None,
        "series.stress": read.day_series.stress is not None,
        "series.body_battery": read.day_series.body_battery is not None,
        "respiration": read.respiration is not None,
        "series.respiration": read.day_series.respiration is not None,
        "spo2": read.spo2 is not None,
        "series.spo2": read.day_series.spo2 is not None,
        "wellness_data": read.wellness_data is not None,
        "stress": read.stress is not None,
        "body_battery": read.body_battery is not None,
        "activity_totals": read.activity_totals is not None,
        "readiness": bool(read.readiness),
    }
    return [piece for piece in FAMILY_PIECES[family] if carried[piece]]


def _second(ms: int) -> int:
    """La seconde entière d'un instant en millisecondes (``ms // 1000``)."""
    return ms // 1000


def _night_window(read: FamilyRead) -> tuple[int, int] | None:
    """La fenêtre de la nuit que porte une lecture, en millisecondes : sa nuit, sinon
    ses copies des bornes de la nuit."""
    if read.night is not None:
        return _instant_ms(read.night.start), _instant_ms(read.night.end)
    bounds = {
        copy.quantity: copy.value
        for copy in read.copies
        if copy.quantity in ("night.start", "night.end")
    }
    start, end = bounds.get("night.start"), bounds.get("night.end")
    if isinstance(start, float) and isinstance(end, float):
        return _ms(start), _ms(end)
    return None


def _same_night(a: tuple[int, int], b: tuple[int, int]) -> bool:
    """Deux fenêtres de nuit égales à la seconde, aux deux bornes."""
    return _second(a[0]) == _second(b[0]) and _second(a[1]) == _second(b[1])


def _same_start(a: datetime, b: datetime) -> bool:
    """Deux débuts de fenêtre du jour égaux : instant et décalage."""
    return a == b and a.utcoffset() == b.utcoffset()


def _segment_durations(segments: StageSegments) -> dict[SleepStage, float]:
    durations = dict.fromkeys(SleepStage, 0.0)
    for start, end, stage in zip(
        segments.start_epoch_s, segments.end_epoch_s, segments.stage, strict=True
    ):
        durations[stage] += (_ms(end) - _ms(start)) / 1000
    return durations


def _durations_agree(segments: StageSegments, night: Night) -> bool:
    """Des segments redonnent chaque durée que porte le résumé de la nuit, à
    ``NIGHT_TOLERANCE_S`` près (comprise) ; une phase dont la durée manque au résumé ne
    se compare pas, une phase du résumé sans segment compte 0."""
    durations = _segment_durations(segments)
    for stage, name in _STAGE_DURATIONS:
        summary = getattr(night, name)
        if summary is not None and abs(durations[stage] - summary) > NIGHT_TOLERANCE_S:
            return False
    return True


@dataclass
class _Assembled:
    """Le document d'un jour et ce que son assemblage a compté."""

    record: DayRecord
    retained: dict[DayFamily, FamilyRead]
    whole: set[DayFamily]
    alone_leaves: set[tuple[DayFamily, str]]
    drops: Counter[tuple[DayFamily, str, PointDiscard]]
    borrowed: list[tuple[DayFamily, str]]
    refused: list[tuple[DayFamily, str, BorrowingRefusal]]


@dataclass
class _DayAssembly:
    """L'assemblage du document d'un jour, depuis l'export de référence et les autres
    exports qui portent le jour."""

    day: date
    reference: _ExportDay
    others: list[_ExportDay]
    retained: dict[DayFamily, FamilyRead] = field(default_factory=dict)
    whole: set[DayFamily] = field(default_factory=set)
    alone_leaves: set[tuple[DayFamily, str]] = field(default_factory=set)
    drops: Counter[tuple[DayFamily, str, PointDiscard]] = field(default_factory=Counter)
    borrowed: list[tuple[DayFamily, str]] = field(default_factory=list)
    refused: list[tuple[DayFamily, str, BorrowingRefusal]] = field(default_factory=list)
    refused_series: set[str] = field(default_factory=set)
    day_overrides: dict[str, tuple[Any, FamilyRead]] = field(default_factory=dict)
    night_overrides: dict[str, tuple[Any, SourceRef]] = field(default_factory=dict)
    segment_override: StageSegments | None = None

    @property
    def window_start(self) -> datetime | None:
        window = self.reference.window
        return None if window is None else window.start

    def _night(self) -> tuple[int, int] | None:
        """La fenêtre de la nuit du document : sa nuit, sinon une copie de ses bornes
        dans une famille retenue."""
        sleep = self.retained.get(DayFamily.SLEEP)
        if sleep is not None and sleep.night is not None:
            return _night_window(sleep)
        for family in _NIGHT_COPY_FAMILIES:
            read = self.retained.get(family)
            if read is not None:
                found = _night_window(read)
                if found is not None:
                    return found
        return None

    def _lenders(self, family: DayFamily) -> list[_ExportDay]:
        """Les autres exports qui portent la famille, du plus récent au plus ancien."""
        return [
            other
            for other in sorted(
                self.others, key=lambda item: item.position, reverse=True
            )
            if family in other.reads
        ]

    def _family_refusal(self, read: FamilyRead) -> BorrowingRefusal | None:
        start = self.window_start
        if (
            read.window is not None
            and start is not None
            and not _same_start(read.window.start, start)
        ):
            return BorrowingRefusal.DAY_WINDOW
        theirs, ours = _night_window(read), self._night()
        if theirs is not None and ours is not None and not _same_night(theirs, ours):
            return BorrowingRefusal.NIGHT_WINDOW
        return None

    def _day_series_agrees(self, read: FamilyRead, lender: _ExportDay) -> bool:
        """Une série du jour d'un autre export : même début de fenêtre, celle de sa
        famille, sinon celle du jour de son export."""
        start = self.window_start
        if start is None:
            return False
        window = read.window if read.window is not None else lender.window
        return window is not None and _same_start(window.start, start)

    def borrow_families(self) -> None:
        """Les familles qui manquent à la référence, du plus récent des autres exports
        qui les porte, et de lui seul."""
        self.retained = dict(self.reference.reads)
        for family in DayFamily:
            if family in self.retained or family in _NOT_BORROWED:
                continue
            lenders = self._lenders(family)
            if not lenders:
                continue
            lender = lenders[0]
            read = lender.reads[family]
            pieces = _pieces(family, read)
            reason = self._family_refusal(read)
            if reason is not None:
                self.refused += [(family, piece, reason) for piece in pieces]
                continue
            self.retained[family] = read
            self.whole.add(family)
            for piece in pieces:
                if piece.startswith("series.") and not self._day_series_agrees(
                    read, lender
                ):
                    self.refused.append((family, piece, BorrowingRefusal.DAY_WINDOW))
                    self.refused_series.add(piece.removeprefix("series."))
                else:
                    self.borrowed.append((family, piece))

    def borrow_series(self) -> None:
        """Les séries du jour et de la nuit, et les segments, qui manquent à une famille
        de la référence."""
        for name, family, path in _DAY_SERIES:
            own = self.reference.reads.get(family)
            if own is None or getattr(own.day_series, name) is not None:
                continue
            for lender in self._lenders(family):
                read = lender.reads[family]
                points = getattr(read.day_series, name)
                if points is None:
                    continue
                piece = f"series.{name}"
                if self._day_series_agrees(read, lender):
                    self.day_overrides[name] = (points, read)
                    self.alone_leaves.add((family, f"{path}[*]"))
                    self.borrowed.append((family, piece))
                else:
                    self.refused.append((family, piece, BorrowingRefusal.DAY_WINDOW))
                break
        sleep = self.reference.reads.get(DayFamily.SLEEP)
        if sleep is None or sleep.night is None:
            return
        ours = _night_window(sleep)
        assert ours is not None
        lenders = self._lenders(DayFamily.SLEEP)
        for name, path in _NIGHT_SERIES:
            if getattr(sleep.night_series, name) is not None:
                continue
            for lender in lenders:
                read = lender.reads[DayFamily.SLEEP]
                points = getattr(read.night_series, name)
                if points is None:
                    continue
                theirs = _night_window(read) if read.night is not None else None
                piece = f"night.series.{name}"
                if theirs is not None and _same_night(theirs, ours):
                    self.night_overrides[name] = (points, read.source)
                    self.alone_leaves.add((DayFamily.SLEEP, f"{path}[*]"))
                    self.borrowed.append((DayFamily.SLEEP, piece))
                else:
                    self.refused.append(
                        (DayFamily.SLEEP, piece, BorrowingRefusal.NIGHT_WINDOW)
                    )
                break
        if sleep.night_segments is not None:
            return
        for lender in lenders:
            read = lender.reads[DayFamily.SLEEP]
            if read.night_segments is None:
                continue
            theirs = _night_window(read) if read.night is not None else None
            if theirs is None or not _same_night(theirs, ours):
                reason = BorrowingRefusal.NIGHT_WINDOW
            elif not _durations_agree(read.night_segments, sleep.night):
                reason = BorrowingRefusal.NIGHT_DURATIONS
            else:
                self.segment_override = read.night_segments
                self.alone_leaves.add((DayFamily.SLEEP, f"{_SEGMENTS_PATH}[*]"))
                self.borrowed.append((DayFamily.SLEEP, "night.segments"))
                break
            self.refused.append((DayFamily.SLEEP, "night.segments", reason))
            break

    def _night_record(self) -> Night | None:
        sleep = self.retained.get(DayFamily.SLEEP)
        if sleep is None:
            return None
        night = sleep.night
        segments = (
            self.segment_override
            if self.segment_override is not None
            else sleep.night_segments
        )
        if night is None:
            for name, path in _NIGHT_SERIES:
                count = _point_count(getattr(sleep.night_series, name))
                if count:
                    self.drops[(DayFamily.SLEEP, path, PointDiscard.NO_NIGHT)] += count
            if segments is not None:
                self.drops[
                    (DayFamily.SLEEP, _SEGMENTS_PATH, PointDiscard.NO_NIGHT)
                ] += len(segments.stage)
            return None
        series: dict[str, Any] = {}
        for name, _ in _NIGHT_SERIES:
            if name in self.night_overrides:
                points, source = self.night_overrides[name]
            else:
                points, source = getattr(sleep.night_series, name), sleep.source
            series[name] = (
                None if points is None else _relative(points, night.start, source)
            )
        base = _instant_ms(night.start)
        stage_segments = (
            ()
            if segments is None
            else tuple(
                SleepSegment(
                    (_ms(start) - base) / 1000, (_ms(end) - base) / 1000, stage
                )
                for start, end, stage in zip(
                    segments.start_epoch_s,
                    segments.end_epoch_s,
                    segments.stage,
                    strict=True,
                )
            )
        )
        return dataclasses.replace(
            night, segments=stage_segments, series=NightSeries(**series)
        )

    def _day_series(self) -> DaySeries:
        start = self.window_start
        series: dict[str, Any] = {}
        read: FamilyRead | None
        for name, family, path in _DAY_SERIES:
            series[name] = None
            if name in self.day_overrides:
                points, read = self.day_overrides[name]
            else:
                read = self.retained.get(family)
                points = None if read is None else getattr(read.day_series, name)
                if family in self.whole and name in self.refused_series:
                    continue
            if points is None or read is None:
                continue
            if start is None:
                self.drops[(family, path, PointDiscard.NO_WINDOW)] += _point_count(
                    points
                )
                continue
            series[name] = _relative(points, start, read.source)
        return DaySeries(**series)

    def _versions(self) -> AlgorithmVersions:
        def version(family: DayFamily, name: str) -> int | None:
            read = self.retained.get(family)
            return None if read is None else getattr(read.versions, name)

        if "body_battery" in self.day_overrides:
            battery = self.day_overrides["body_battery"][1].versions
        else:
            stress = self.retained.get(DayFamily.STRESS)
            battery = (
                AlgorithmVersions(None, None, None, None, None, ())
                if stress is None
                else stress.versions
            )
        return AlgorithmVersions(
            sleep_version=version(DayFamily.SLEEP, "sleep_version"),
            sleep_respiration_version=version(
                DayFamily.SLEEP, "sleep_respiration_version"
            ),
            respiration_version=version(DayFamily.RESPIRATION, "respiration_version"),
            summary_respiration_version=version(
                DayFamily.DAILY_SUMMARY, "summary_respiration_version"
            ),
            summary_body_battery_version=version(
                DayFamily.DAILY_SUMMARY, "summary_body_battery_version"
            ),
            body_battery_series_versions=battery.body_battery_series_versions,
        )

    def assemble(self, ranks: tuple[int, ...]) -> _Assembled:
        def part(family: DayFamily, name: str) -> Any:
            read = self.retained.get(family)
            return None if read is None else getattr(read, name)

        window = self.reference.window
        sleep = self.retained.get(DayFamily.SLEEP)
        record = DayRecord(
            day=self.day,
            window_start=None if window is None else window.start,
            data_end=None if window is None else window.data_end,
            window_family=self.reference.window_family,
            wellness_data=part(DayFamily.DAILY_SUMMARY, "wellness_data"),
            state=self.reference.state,
            reference_export=self.reference.name,
            night=self._night_record(),
            naps=() if sleep is None else sleep.naps,
            resting_hr=part(DayFamily.RESTING_HR, "resting_hr"),
            hrv=part(DayFamily.HRV, "hrv"),
            respiration=part(DayFamily.RESPIRATION, "respiration"),
            spo2=part(DayFamily.SPO2, "spo2"),
            stress=part(DayFamily.DAILY_SUMMARY, "stress"),
            body_battery=part(DayFamily.DAILY_SUMMARY, "body_battery"),
            activity_totals=part(DayFamily.DAILY_SUMMARY, "activity_totals"),
            series=self._day_series(),
            readiness=part(DayFamily.TRAINING_READINESS, "readiness") or (),
            versions=self._versions(),
            device_ranks=ranks,
        )
        return _Assembled(
            record,
            self.retained,
            self.whole,
            self.alone_leaves,
            self.drops,
            self.borrowed,
            self.refused,
        )


# ---------------------------------------------------------------------------
# La passe sur les jours
# ---------------------------------------------------------------------------


_KIND_ATTRIBUTES = (
    (TrainingStatusKind.STATUS, "status_block"),
    (TrainingStatusKind.LOAD_BALANCE, "load_balance_block"),
    (TrainingStatusKind.VO2_MAX, "vo2_max_block"),
    (TrainingStatusKind.HEAT_ACCLIMATION, "heat_block"),
    (TrainingStatusKind.ALTITUDE_ACCLIMATION, "altitude_block"),
)
"""Chaque sorte de bloc de Training Status, et son attribut dans ``FamilyRead``."""

type _Block = (
    TrainingStatusBlock
    | LoadBalanceBlock
    | Vo2MaxBlock
    | HeatAcclimationBlock
    | AltitudeAcclimationBlock
)


def _copy_target(record: DayRecord, quantity: str) -> Any:
    """La grandeur du document qu'une copie contrôlée recopie, ou ``None`` s'il ne la
    porte pas : un instant de la nuit en millisecondes, la série de HRV de la nuit en
    (millisecondes, valeur), le stress moyen en niveau ou en code."""
    night = record.night
    if quantity in ("night.start", "night.end"):
        if night is None:
            return None
        return _instant_ms(night.start if quantity == "night.start" else night.end)
    if quantity == "night.series.hrv":
        if night is None or night.series.hrv is None:
            return None
        return tuple(
            zip(
                _series_instants(night.series.hrv, night.start),
                night.series.hrv.hrv_ms,
                strict=True,
            )
        )
    if quantity == "stress.average_level":
        stress = record.stress
        if stress is None:
            return None
        if stress.average_level is not None:
            return stress.average_level
        return stress.average_level_code
    part, name = quantity.split(".")
    holder = getattr(record, part)
    return None if holder is None else getattr(holder, name)


def _copy_differs(copy: QuantityCopy, target: Any) -> bool:
    """Une copie qui ne s'accorde pas avec la grandeur du document : les bornes de la
    nuit à la seconde, la série de HRV point par point, le reste à l'égalité."""
    value = copy.value
    if isinstance(value, HrvPoints):
        points = tuple(
            zip((_ms(epoch) for epoch in value.epoch_s), value.hrv_ms, strict=True)
        )
        return bool(points != target)
    if copy.quantity in ("night.start", "night.end") and not isinstance(value, str):
        return _second(_ms(value)) != _second(target)
    return bool(value != target)


def _series_instants(series: Any, origin: datetime) -> list[int]:
    """Les instants d'une série du document, en millisecondes depuis l'époque."""
    base = _instant_ms(origin)
    return [base + round(time * 1000) for time in series.time_s]


@dataclass
class _History:
    """Les blocs de Training Status retenus et leurs comptes."""

    history: TrainingStatusHistory
    in_export: Counter[tuple[TrainingStatusKind, str]]
    between: Counter[tuple[TrainingStatusKind, str]]
    without: Counter[TrainingStatusKind]


@dataclass
class _Builder:
    """La passe jour par jour : les documents, et les comptes du rapport. Ce qu'il
    garde d'un jour pour la suite : son document, ses blocs de Training Status, son
    export de référence, les appareils vus."""

    exports: Sequence[ExportDays]
    records: list[DayRecord] = field(default_factory=list)
    documents: dict[date, DayRecord] = field(default_factory=dict)
    read: list[ReadFile] = field(default_factory=list)
    refused: list[DayFileRefused] = field(default_factory=list)
    reference_days: Counter[str] = field(default_factory=Counter)
    window_families: Counter[DayFamily] = field(default_factory=Counter)
    window_mismatches: Counter[DayFamily] = field(default_factory=Counter)
    borrowings: Counter[tuple[DayFamily, str]] = field(default_factory=Counter)
    borrowing_refusals: Counter[tuple[DayFamily, str, BorrowingRefusal]] = field(
        default_factory=Counter
    )
    comparisons: Counter[tuple[DayFamily, str, ComparisonClass]] = field(
        default_factory=Counter
    )
    edges: dict[tuple[DayFamily, str], list[int]] = field(default_factory=dict)
    gaps: dict[tuple[DayFamily, str], list[float]] = field(default_factory=dict)
    copies: Counter[tuple[str, DayFamily]] = field(default_factory=Counter)
    readiness_copies: dict[str, list[int]] = field(default_factory=dict)
    acute_copies: list[tuple[date, float]] = field(default_factory=list)
    night_violations: int = 0
    discards: Counter[tuple[DayFamily, str, PointDiscard]] = field(
        default_factory=Counter
    )
    codes: Counter[tuple[DayFamily, str, str]] = field(default_factory=Counter)
    confirmations: Counter[tuple[DayFamily, str, str]] = field(default_factory=Counter)
    naps_overlapping: int = 0
    refused_blocks: Counter[TrainingStatusKind] = field(default_factory=Counter)
    non_primary: int = 0
    devices: dict[int, int] = field(default_factory=dict)
    blocks: dict[tuple[TrainingStatusKind, date], dict[int, list[_Block]]] = field(
        default_factory=dict
    )
    references: dict[date, int] = field(default_factory=dict)

    # --- un jour ------------------------------------------------------------------

    def day(self, day: date, files: Mapping[int, Sequence[DayFile]]) -> None:
        """Un jour : chaque fichier lu, l'état du jour dans chaque export, la référence,
        le document et ses emprunts, les comptes du jour ; puis le brut est oublié."""
        export_days: list[_ExportDay] = []
        for position in sorted(files):
            export = self.exports[position]
            reads: dict[DayFamily, FamilyRead] = {}
            for file in files[position]:
                result, digest = _read(file, export.retrieved_at)
                name = (
                    f"garmin/{export.name}/{file.family.value}/{day.isoformat()}.json"
                )
                self.read.append(ReadFile(name, digest))
                if result.refusal is not None:
                    self.refused.append(DayFileRefused(name, result.refusal))
                    continue
                if file.family is DayFamily.TRAINING_STATUS:
                    self._keep_blocks(position, result)
                if not result.empty:
                    reads[file.family] = result
            export_days.append(_export_day(position, export.name, reads))
        if not export_days:
            raise ValueError("un jour sans export qui le porte.")
        reference = _reference(export_days)
        self.references[day] = reference.position
        others = [item for item in export_days if item is not reference]
        assembly = _DayAssembly(day, reference, others)
        assembly.borrow_families()
        assembly.borrow_series()
        assembled = assembly.assemble(self._ranks(assembly.retained))
        self._count(assembled, reference, others)
        self._edges(assembled.record)
        self.records.append(assembled.record)
        self.documents[day] = assembled.record

    def _keep_blocks(self, position: int, read: FamilyRead) -> None:
        for kind, attribute in _KIND_ATTRIBUTES:
            block = getattr(read, attribute)
            if block is not None:
                exports = self.blocks.setdefault((kind, block.day), {})
                exports.setdefault(position, []).append(block)

    def _ranks(self, retained: Mapping[DayFamily, FamilyRead]) -> tuple[int, ...]:
        """Les rangs des appareils des lectures retenues : familles dans l'ordre de
        ``DayFamily``, puis ordre d'apparition ; premier vu, premier rang."""
        ranks: set[int] = set()
        for family in DayFamily:
            read = retained.get(family)
            if read is None:
                continue
            for device in read.device_ids:
                ranks.add(self.devices.setdefault(device, len(self.devices) + 1))
        return tuple(sorted(ranks))

    def _count(
        self, assembled: _Assembled, reference: _ExportDay, others: list[_ExportDay]
    ) -> None:
        record = assembled.record
        self.reference_days[reference.name] += 1
        if record.window_family not in (None, DayFamily.DAILY_SUMMARY):
            assert record.window_family is not None
            self.window_families[record.window_family] += 1
        if record.window_start is not None:
            for family, read in assembled.retained.items():
                if read.window is not None and not (
                    _same_start(read.window.start, record.window_start)
                    and read.window.data_end == record.data_end
                ):
                    self.window_mismatches[family] += 1
        for family, piece in assembled.borrowed:
            self.borrowings[(family, piece)] += 1
        for family, piece, reason in assembled.refused:
            self.borrowing_refusals[(family, piece, reason)] += 1
        self._compare(assembled, reference, others)
        differing: set[tuple[str, DayFamily]] = set()
        for family, read in assembled.retained.items():
            for copy in read.copies:
                target = _copy_target(record, copy.quantity)
                if target is not None and _copy_differs(copy, target):
                    differing.add((copy.quantity, family))
            for discard in read.discards:
                key = (discard.family, discard.series_path, discard.reason)
                self.discards[key] += discard.count
            for code in (*read.unknown_codes, *read.unknown_contexts):
                self.codes[(code.family, code.field_path, code.code)] += code.count
            for code in read.unknown_confirmations:
                key_code = (code.family, code.field_path, code.code)
                self.confirmations[key_code] += code.count
            self.non_primary += read.readiness_non_primary
            for kind in read.refused_blocks:
                self.refused_blocks[kind] += 1
        for item in differing:
            self.copies[item] += 1
        self.discards.update(assembled.drops)
        self._night_checks(record)
        self._readiness_copies(record)

    def _night_checks(self, record: DayRecord) -> None:
        """L'égalité de la nuit, à ``NIGHT_TOLERANCE_S`` près (comprise) : sans
        paradoxal détecté, il compte zéro ; une durée absente, pas de contrôle. Les
        siestes qui recoupent la nuit."""
        night = record.night
        if night is None:
            return
        rem = night.rem_s
        if rem is None and night.rem_capable is False:
            rem = 0.0
        parts = (night.deep_s, night.light_s, rem, night.awake_s, night.unmeasurable_s)
        total = 0.0
        for part in parts:
            if part is None:
                break
            total += part
        else:
            duration = (night.end - night.start).total_seconds()
            if abs(duration - total) > NIGHT_TOLERANCE_S:
                self.night_violations += 1
        for nap in record.naps:
            if nap.start < night.end and night.start < nap.end:
                self.naps_overlapping += 1

    def _readiness_copy(self, quantity: str, copy: object, final: object) -> None:
        if copy is None:
            return
        counts = self.readiness_copies.setdefault(quantity, [0, 0])
        counts[0] += 1
        if final is not None and copy != final:
            counts[1] += 1

    def _readiness_copies(self, record: DayRecord) -> None:
        """Les copies de Training Readiness (« copie antérieure ») ; la charge aiguë se
        compare après la passe, au bloc « statut » de la date du jour."""
        sleep_score = None if record.night is None else record.night.sleep_score
        weekly = None if record.hrv is None else record.hrv.weekly_avg_ms
        for entry in record.readiness:
            self._readiness_copy("night.sleep_score", entry.sleep_score, sleep_score)
            self._readiness_copy(
                "hrv.weekly_avg_ms", entry.hrv_weekly_average_ms, weekly
            )
            if entry.acute_load is not None:
                self.acute_copies.append((record.day, entry.acute_load))

    def _compare(
        self, assembled: _Assembled, reference: _ExportDay, others: list[_ExportDay]
    ) -> None:
        """Les écarts entre la référence et chacun des autres exports qui portent le
        jour, feuille par feuille, chacun rangé dans la première classe qui convient :
        emprunt, dégradation, révision, à part. Un jour compte une fois par (famille,
        feuille, classe)."""
        found: set[tuple[DayFamily, str, ComparisonClass]] = set()
        for other in others:
            newer, older = (
                (other, reference)
                if other.position > reference.position
                else (reference, other)
            )
            degraded = older.detail and not newer.detail
            alike = (
                reference.state is DayState.COMPLETE
                and other.state is DayState.COMPLETE
                and reference.detail == other.detail
            )
            for family in DayFamily:
                if family is DayFamily.TRAINING_STATUS:
                    continue
                ignored = COMPARISON_IGNORED_FIELDS.get(family, ())
                ours = reference.reads.get(family)
                theirs = other.reads.get(family)
                mine = {} if ours is None else dict(ours.fields)
                yours = {} if theirs is None else dict(theirs.fields)
                for path in sorted(set(mine) | set(yours)):
                    if path in ignored or mine.get(path) == yours.get(path):
                        continue
                    if (
                        family in assembled.whole
                        or (family, path) in assembled.alone_leaves
                    ):
                        kind = ComparisonClass.BORROWING
                    elif degraded:
                        kind = ComparisonClass.DEGRADATION
                    elif alike and path in mine and path in yours:
                        kind = ComparisonClass.REVISION
                    else:
                        kind = ComparisonClass.SET_APART
                    found.add((family, path, kind))
        for key in found:
            self.comparisons[key] += 1

    def _edges(self, record: DayRecord) -> None:
        """Les bords de fenêtre : les points hors de la fenêtre de leur fichier, les
        instants présents dans deux jours voisins ; pour les séries du jour, l'écart
        entre le dernier instant de la veille et le premier du jour."""
        previous = self.documents.get(record.day - _DAY)
        if record.window_start is not None:
            for name, family, path in _DAY_SERIES:
                series = getattr(record.series, name)
                if series is None:
                    continue
                outside = sum(not 0 <= time <= 86400 for time in series.time_s)
                shared = 0
                if previous is not None and previous.window_start is not None:
                    before = getattr(previous.series, name)
                    if before is not None:
                        instants = _series_instants(series, record.window_start)
                        earlier = _series_instants(before, previous.window_start)
                        shared = len(set(instants) & set(earlier))
                        gap = (instants[0] - earlier[-1]) / 1000
                        self.gaps.setdefault((family, path), []).append(gap)
                self._edge(family, path, outside, shared)
        night = record.night
        if night is None:
            return
        duration = (night.end - night.start).total_seconds()
        for name, path in _NIGHT_SERIES:
            series = getattr(night.series, name)
            if series is None:
                continue
            outside = sum(not 0 <= time <= duration for time in series.time_s)
            shared = 0
            if previous is not None and previous.night is not None:
                before = getattr(previous.night.series, name)
                if before is not None:
                    shared = len(
                        set(_series_instants(series, night.start))
                        & set(_series_instants(before, previous.night.start))
                    )
            self._edge(DayFamily.SLEEP, path, outside, shared)

    def _edge(self, family: DayFamily, path: str, outside: int, shared: int) -> None:
        if outside or shared:
            counts = self.edges.setdefault((family, path), [0, 0])
            counts[0] += outside
            counts[1] += shared

    # --- Training Status ----------------------------------------------------------

    def _proper_instant(self, block: _Block) -> datetime | None:
        """L'instant propre d'un bloc : l'horodatage du statut ; sinon la fin de la
        fenêtre du jour de sa date (le plus tard de début + 24 h et de la fin des
        données) ; sinon le début de la fenêtre du lendemain ; sinon le minuit local
        qui suit sa date, au décalage de la fenêtre du jour du fichier choisi (une heure
        trop tôt ou trop tard au changement d'heure) ; sinon aucun."""
        if isinstance(block, TrainingStatusBlock) and block.timestamp is not None:
            return block.timestamp
        own = self.documents.get(block.day)
        if own is not None and own.window_start is not None:
            assert own.data_end is not None
            return max(own.window_start + _DAY, own.data_end)
        following = self.documents.get(block.day + _DAY)
        if following is not None and following.window_start is not None:
            return following.window_start
        chosen = self.documents.get(block.file_day)
        if chosen is not None and chosen.window_start is not None:
            offset = chosen.window_start.utcoffset()
            assert offset is not None
            after = block.day + _DAY
            return datetime(after.year, after.month, after.day, tzinfo=timezone(offset))
        return None

    @staticmethod
    def _pick(blocks: Sequence[_Block], day: date) -> _Block:
        """Dans un export : le bloc du fichier du jour de sa date, sinon du plus ancien
        fichier qui le porte."""
        for block in blocks:
            if block.file_day == day:
                return block
        return min(blocks, key=lambda block: block.file_day)

    def _history(self) -> _History:
        """Les blocs de Training Status : de l'export de référence du jour de leur date,
        sinon du plus récent qui les porte ; dans cet export, la règle de ``_pick``.
        Les écarts d'un même bloc, dans un export et entre exports, une fois par
        champ."""
        chosen: dict[TrainingStatusKind, list[_Block]] = {
            kind: [] for kind in TrainingStatusKind
        }
        in_export: Counter[tuple[TrainingStatusKind, str]] = Counter()
        between: Counter[tuple[TrainingStatusKind, str]] = Counter()
        without: Counter[TrainingStatusKind] = Counter()
        for (kind, day), by_export in sorted(self.blocks.items()):
            reference = self.references.get(day)
            position = (
                reference
                if reference is not None and reference in by_export
                else max(by_export)
            )
            block = self._pick(by_export[position], day)
            picks = [
                self._pick(blocks, day)
                for other, blocks in by_export.items()
                if other != position
            ]
            for attribute, path in BLOCK_FIELDS[kind]:
                if any(
                    len({getattr(item, attribute) for item in blocks}) > 1
                    for blocks in by_export.values()
                ):
                    in_export[(kind, path)] += 1
                value = getattr(block, attribute)
                if any(getattr(item, attribute) != value for item in picks):
                    between[(kind, path)] += 1
            proper = self._proper_instant(block)
            if proper is None:
                without[kind] += 1
            chosen[kind].append(dataclasses.replace(block, proper_instant=proper))
        history = TrainingStatusHistory(
            statuses=tuple(
                block
                for block in chosen[TrainingStatusKind.STATUS]
                if isinstance(block, TrainingStatusBlock)
            ),
            load_balances=tuple(
                block
                for block in chosen[TrainingStatusKind.LOAD_BALANCE]
                if isinstance(block, LoadBalanceBlock)
            ),
            vo2_max=tuple(
                block
                for block in chosen[TrainingStatusKind.VO2_MAX]
                if isinstance(block, Vo2MaxBlock)
            ),
            heat_acclimation=tuple(
                block
                for block in chosen[TrainingStatusKind.HEAT_ACCLIMATION]
                if isinstance(block, HeatAcclimationBlock)
            ),
            altitude_acclimation=tuple(
                block
                for block in chosen[TrainingStatusKind.ALTITUDE_ACCLIMATION]
                if isinstance(block, AltitudeAcclimationBlock)
            ),
        )
        return _History(history, in_export, between, without)

    # --- le rapport ---------------------------------------------------------------

    def result(self) -> DaysIngestion:
        """Après la passe : Training Status, la charge aiguë de Training Readiness, le
        rapport, le résumé."""
        found = self._history()
        history = found.history
        statuses = {block.day: block.acute_load for block in history.statuses}
        for day, acute in self.acute_copies:
            self._readiness_copy("statuses.acute_load", acute, statuses.get(day))
        report = DaysReport(
            exports=tuple(self._export_report(export) for export in self.exports),
            read=tuple(sorted(self.read, key=lambda item: item.name)),
            refused=tuple(sorted(self.refused, key=lambda item: item.name)),
            reference_days=tuple(
                ExportDayCount(name, count)
                for name, count in sorted(self.reference_days.items())
            ),
            window_families=_family_counts(self.window_families),
            window_mismatches=_family_counts(self.window_mismatches),
            borrowings=tuple(
                BorrowingCount(family, piece, count)
                for (family, piece), count in sorted(self.borrowings.items())
            ),
            borrowing_refusals=tuple(
                BorrowingRefusalCount(family, piece, reason, count)
                for (family, piece, reason), count in sorted(
                    self.borrowing_refusals.items()
                )
            ),
            comparisons=tuple(
                ComparisonCount(family, path, kind, count)
                for (family, path, kind), count in sorted(self.comparisons.items())
            ),
            window_edges=tuple(
                WindowEdgeCount(family, path, outside, shared)
                for (family, path), (outside, shared) in sorted(self.edges.items())
            ),
            day_boundary_gaps=tuple(
                DayBoundaryGap(family, path, len(gaps), max(gaps))
                for (family, path), gaps in sorted(self.gaps.items())
            ),
            copy_disagreements=tuple(
                CopyDisagreementCount(quantity, family, count)
                for (quantity, family), count in sorted(self.copies.items())
            ),
            readiness_prior_copies=tuple(
                ReadinessCopyCount(quantity, entries, differing)
                for quantity, (entries, differing) in sorted(
                    self.readiness_copies.items()
                )
            ),
            night_equality_violations=self.night_violations,
            point_discards=tuple(
                PointDiscardCount(family, path, reason, count)
                for (family, path, reason), count in sorted(self.discards.items())
                if count
            ),
            unknown_codes=_code_counts(self.codes),
            unknown_confirmations=_code_counts(self.confirmations),
            naps_overlapping_night=self.naps_overlapping,
            refused_blocks=_block_counts(self.refused_blocks),
            block_differences_in_export=_block_field_counts(found.in_export),
            block_differences_between_exports=_block_field_counts(found.between),
            blocks_without_proper_instant=_block_counts(found.without),
            readiness_non_primary=self.non_primary,
        )
        return DaysIngestion(
            tuple(self.records), history, report, self._summary(report, history)
        )

    def _export_report(self, export: ExportDays) -> DaysExportReport:
        days = [file.day for file in export.files]
        return DaysExportReport(
            name=export.name,
            retrieved_at=export.retrieved_at,
            first_day=min(days, default=None),
            last_day=max(days, default=None),
            files=len(export.files),
            families=tuple(sorted({file.family for file in export.files})),
        )

    def _summary(
        self, report: DaysReport, history: TrainingStatusHistory
    ) -> DaysSummary:
        states = Counter(record.state for record in self.records)
        classes: Counter[ComparisonClass] = Counter()
        for count in report.comparisons:
            classes[count.comparison] += count.days
        blocks = sum(
            len(suite)
            for suite in (
                history.statuses,
                history.load_balances,
                history.vo2_max,
                history.heat_acclimation,
                history.altitude_acclimation,
            )
        )
        return DaysSummary(
            days=len(self.records),
            reference_days=report.reference_days,
            states=tuple((state, states[state]) for state in DayState),
            borrowings=sum(count.count for count in report.borrowings),
            borrowing_refusals=sum(count.count for count in report.borrowing_refusals),
            revisions=classes[ComparisonClass.REVISION],
            degradations=classes[ComparisonClass.DEGRADATION],
            set_apart=classes[ComparisonClass.SET_APART],
            refused_files=len(report.refused),
            point_discards=sum(count.count for count in report.point_discards),
            unknown_codes=sum(count.count for count in report.unknown_codes),
            training_status_blocks=blocks,
            blocks_without_proper_instant=sum(
                count.count for count in report.blocks_without_proper_instant
            ),
        )


def _family_counts(counts: Counter[DayFamily]) -> tuple[FamilyDayCount, ...]:
    return tuple(
        FamilyDayCount(family, days) for family, days in sorted(counts.items())
    )


def _code_counts(counts: Counter[tuple[DayFamily, str, str]]) -> tuple[CodeCount, ...]:
    return tuple(
        CodeCount(family, path, code, count)
        for (family, path, code), count in sorted(counts.items())
    )


def _block_counts(counts: Counter[TrainingStatusKind]) -> tuple[BlockCount, ...]:
    return tuple(BlockCount(kind, count) for kind, count in sorted(counts.items()))


def _block_field_counts(
    counts: Counter[tuple[TrainingStatusKind, str]],
) -> tuple[BlockFieldCount, ...]:
    return tuple(
        BlockFieldCount(kind, path, count)
        for (kind, path), count in sorted(counts.items())
    )


def build_days(exports: Sequence[ExportDays]) -> DaysIngestion:
    """Les documents d'``interim/days/`` de tous les exports (``load_export_days``),
    calculés avant toute écriture. Pur, sauf la lecture des octets des fichiers.

    Les exports se rangent par instant d'acquisition (au moins un, deux instants égaux :
    ``ValueError``, ``ingest_export`` les a refusés avant). Puis **jour par jour**, par
    date croissante (un document par jour qu'au moins un export porte, même par un
    fichier vide ou refusé), toutes les familles de tous les exports pour cette date,
    puis le brut est oublié :

    1. chaque fichier lu (``read_family``), inscrit au rapport
       (``garmin/<export>/<famille>/<date>.json``, son empreinte), refusé s'il l'est ;
       une famille refusée, vide ou sans fichier est absente de cet export ce jour-là ;
    2. dans chaque export qui porte le jour : sa fenêtre du jour (``daily_summary``,
       sinon la première famille de ``DAY_WINDOW_FAMILIES`` qui en porte une), son état
       dans l'ordre de ``DayState`` (``empty`` sans fenêtre ; ``no_measurement`` si
       l'indicateur est faux, ou, sans indicateur, sans échantillon mesuré dans les
       séries du jour et sans nuit ; ``truncated`` si ``fin_donnees`` précède début +
       24 h ; ``complete``), et « a son détail » (une série fine que Garmin efface, non
       vide, SpO2 exclue, dans l'une de ses familles) ;
    3. l'export de référence (``_reference``) ;
    4. le document du jour (``_DayAssembly``) : toutes les familles de la référence ;
       une famille qui lui manque, du plus récent des autres exports qui la porte, si
       ce que les deux portent en commun s'accorde (fenêtre du jour, même début ;
       fenêtre de la nuit, à la seconde ; rien en commun : emprunt) ; une série qui
       manque à une famille retenue (série du jour : même début de fenêtre ; série ou
       segments de la nuit : même fenêtre à la seconde, et des segments qui redonnent
       les durées du résumé à ``NIGHT_TOLERANCE_S`` près) ; sinon le morceau reste
       absent et le refus se compte, par famille, morceau et motif ; les séries en
       secondes depuis le début de la fenêtre du jour, ou de la nuit, chacune avec la
       provenance de son fichier ; des séries et segments d'une nuit absente, ou des
       séries du jour d'un jour sans fenêtre, jetés et comptés (``no_night``,
       ``no_window``) ;
    5. les comptes du jour : écarts entre exports (``_Builder._compare``), fenêtres qui
       diffèrent de celle du jour ; sur les seules lectures retenues (la référence et
       les familles empruntées entières, pas le prêteur d'une série ou de segments
       seuls) : copies contrôlées, écarts de lecture, codes et types de confirmation
       inconnus, entrées non principales, blocs refusés ; les points que l'assemblage
       jette ; égalité de la nuit, siestes qui recoupent la nuit, rangs d'appareil
       (premier vu, premier rang), comptes des bords de fenêtre contre le jour
       précédent, copies de Training Readiness.

    Après la passe : les blocs de Training Status (``_Builder._history``) et leur
    instant propre ; les copies de la charge aiguë de Training Readiness, contre le
    bloc « statut » de la date du jour ; le rapport, chaque liste triée par sa clé ; le
    résumé.
    """
    if not exports:
        raise ValueError("build_days demande au moins un export.")
    ordered = sorted(exports, key=lambda export: export.retrieved_at)
    if any(
        first.retrieved_at == second.retrieved_at for first, second in pairwise(ordered)
    ):
        raise ValueError("deux exports au même instant d'acquisition.")
    by_day: dict[date, dict[int, list[DayFile]]] = {}
    for position, export in enumerate(ordered):
        for file in export.files:
            by_day.setdefault(file.day, {}).setdefault(position, []).append(file)
    builder = _Builder(ordered)
    for day in sorted(by_day):
        files = {
            position: sorted(items, key=lambda file: _FAMILY_RANK[file.family])
            for position, items in by_day.pop(day).items()
        }
        builder.day(day, files)
    return builder.result()
