"""L'ingestion des jours (``build_days``, AN2-1), sur de faux exports écrits dans un
dossier temporaire : l'état du jour, sa fenêtre, l'export de référence, les cas nommés
(la référence, l'emprunt, l'état), les copies, les écarts, les rangs d'appareil,
l'égalité de la nuit. Sans extra : ni fitdecode, ni ``ingest_export``
(``test_ingest_export_days.py``). Training Status :
``test_ingest_days_training_status.py``."""

from __future__ import annotations

import dataclasses
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

from fixtures.day_exports import (
    build,
    export_dir,
    load,
    record,
    write_day,
    write_document,
)
from fixtures.days import (
    DAY,
    EXPORT_A,
    EXPORT_B,
    EXPORT_C,
    PLUS2,
    RETRIEVED,
    SPRING_DAY,
    at,
    midnight,
    ms,
    wall_ms,
)
from fixtures.families import (
    DOCUMENTS,
    NIGHT_END,
    NIGHT_START,
    OTHER_DEVICE,
    START,
    gmt_text,
    local_text,
    readiness_entry,
    status_entry,
    training_status_document,
)
from mountain_perf.ingest.days import build_days, load_export_days
from mountain_perf.schemas import (
    AlgorithmVersions,
    BlockCount,
    BorrowingCount,
    BorrowingRefusal,
    BorrowingRefusalCount,
    CodeCount,
    ComparisonClass,
    CopyDisagreementCount,
    DayBoundaryGap,
    DayFamily,
    DayFileRefusal,
    DayFileRefused,
    DayRecord,
    DayState,
    ExportDayCount,
    FamilyDayCount,
    PointDiscard,
    PointDiscardCount,
    ReadinessCopyCount,
    SleepSegment,
    SleepStage,
    SourceRef,
    TrainingStatusKind,
    WindowEdgeCount,
)

D1 = DAY + timedelta(days=1)
D2 = DAY + timedelta(days=2)
NOON = at(DAY, 12)
SCORE = "dailySleepDTO.sleepScores.overall.value"
"""La feuille du score de sommeil dans ``sleep``."""

_FINE_SLEEP_SERIES = (
    "sleepLevels",
    "sleepHeartRate",
    "sleepStress",
    "sleepBodyBattery",
    "hrvData",
    "wellnessEpochRespirationDataDTOList",
    "sleepRestlessMoments",
)
"""Les séries fines de ``sleep`` que Garmin efface (la SpO2 n'en est pas)."""


def _doc(family: DayFamily, day: date = DAY) -> Any:
    return DOCUMENTS[family](day)


def _stripped_sleep(day: date = DAY) -> dict[str, Any]:
    """Le document de ``sleep`` sans son détail : segments et séries fines vides."""
    document: dict[str, Any] = _doc(DayFamily.SLEEP, day)
    for key in _FINE_SLEEP_SERIES:
        document[key] = []
    return document


def _null_window(document: dict[str, Any]) -> dict[str, Any]:
    """Un document dont les trois champs de la fenêtre du jour sont nuls."""
    for key in ("startTimestampGMT", "startTimestampLocal", "endTimestampGMT"):
        document[key] = None
    return document


def _end_at(document: dict[str, Any], end: datetime) -> dict[str, Any]:
    """Un document d'une famille à fenêtre (hors ``daily_summary``) dont les données
    finissent à ``end``."""
    document["endTimestampGMT"] = gmt_text(end)
    document["endTimestampLocal"] = local_text(end)
    return document


def _summary(**changes: Any) -> dict[str, Any]:
    """Le document de ``daily_summary`` du jour, ses champs ``changes`` remplacés."""
    return {**_doc(DayFamily.DAILY_SUMMARY), **changes}


def _sleep(**changes: Any) -> dict[str, Any]:
    """Le document de ``sleep``, ses champs ``changes`` de ``dailySleepDTO``
    remplacés."""
    document: dict[str, Any] = _doc(DayFamily.SLEEP)
    document["dailySleepDTO"].update(changes)
    return document


def _levels(plan: list[tuple[int, int]]) -> list[dict[str, Any]]:
    """Des segments contigus depuis le début de la nuit : (code, durée en s)."""
    segments = []
    begin = NIGHT_START
    for code, seconds in plan:
        end = begin + timedelta(seconds=seconds)
        segments.append(
            {
                "startGMT": gmt_text(begin),
                "endGMT": gmt_text(end),
                "activityLevel": code,
            }
        )
        begin = end
    return segments


_FULL_PLAN = [(0, 3600), (1, 16200), (2, 5400), (3, 1800), (-1, 1800)]
"""Des segments qui redonnent les durées du résumé de la nuit par défaut."""

_REM_30 = [(0, 3600), (1, 16200), (2, 1800), (3, 1800), (-1, 1800)]
_UNMEASURABLE_10 = [(0, 3600), (1, 16200), (2, 5400), (3, 1800), (-1, 600)]


def _no_measurement_base(root: Path, end: datetime | None = None) -> None:
    """Un jour sans indicateur ni nuit, dont les séries du jour ne portent que des
    codes et un Body Battery modélisé : aucun échantillon mesuré."""
    stress = _doc(DayFamily.STRESS)
    stress["stressValuesArray"] = [
        [ms(START), -1],
        [ms(START + timedelta(minutes=3)), -2],
    ]
    stress["bodyBatteryValuesArray"] = [[ms(START), "MODELED", 40, 3]]
    respiration = _doc(DayFamily.RESPIRATION)
    respiration["respirationValuesArray"] = [[ms(START), -1]]
    if end is not None:
        _end_at(stress, end)
        _end_at(respiration, end)
    write_document(root, DayFamily.STRESS, stress)
    write_document(root, DayFamily.RESPIRATION, respiration)


def _sources(value: Any) -> list[SourceRef]:
    """Toutes les provenances d'un document, à toute profondeur."""
    if isinstance(value, SourceRef):
        return [value]
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        found: list[SourceRef] = []
        for item in dataclasses.fields(value):
            found += _sources(getattr(value, item.name))
        return found
    if isinstance(value, tuple):
        return [source for item in value for source in _sources(item)]
    return []


def _kinds(ingestion: Any, family: DayFamily) -> dict[str, ComparisonClass]:
    return {
        count.field_path: count.comparison
        for count in ingestion.report.comparisons
        if count.family is family
    }


# --- l'état du jour -----------------------------------------------------------------


def test_empty_wins_over_no_measurement(tmp_path: Path) -> None:
    """Aucune fenêtre du jour (celle de la nuit n'en est pas une), un indicateur faux :
    ``empty``."""
    summary = _summary(
        includesWellnessData=False,
        wellnessStartTimeGmt=None,
        wellnessStartTimeLocal=None,
        wellnessEndTimeGmt=None,
    )
    write_day(
        tmp_path,
        families=(DayFamily.SLEEP, DayFamily.DAILY_SUMMARY),
        daily_summary=summary,
    )
    day = record(build(tmp_path))
    assert day.state is DayState.EMPTY
    assert day.window_start is None
    assert day.night is not None


def test_no_measurement_by_the_indicator_wins_over_truncated(tmp_path: Path) -> None:
    """L'indicateur faux, quelle que soit la fenêtre (ici tronquée)."""
    summary = _summary(includesWellnessData=False, wellnessEndTimeGmt=gmt_text(NOON))
    write_day(tmp_path, families=(DayFamily.DAILY_SUMMARY,), daily_summary=summary)
    assert record(build(tmp_path)).state is DayState.NO_MEASUREMENT


def test_no_measurement_by_the_indicator_on_a_complete_window(tmp_path: Path) -> None:
    """Fenêtre complète, indicateur faux : ``no_measurement``."""
    write_day(tmp_path, daily_summary=_summary(includesWellnessData=False))
    day = record(build(tmp_path))
    assert day.state is DayState.NO_MEASUREMENT
    assert day.data_end == START + timedelta(days=1)


def test_no_measurement_without_indicator_wins_over_truncated(tmp_path: Path) -> None:
    """Sans indicateur (pas de ``daily_summary``) ni nuit, fenêtre tronquée à midi : des
    codes de stress (−1, −2) et de respiration (−1) et un point de Body Battery au
    statut ``MODELED`` (niveau 40), sans FC ni SpO2 ; aucun n'est un échantillon
    mesuré : ``no_measurement``, pas ``truncated``."""
    _no_measurement_base(tmp_path, NOON)
    day = record(build(tmp_path))
    assert day.window_family is DayFamily.STRESS
    assert day.data_end == NOON
    assert day.state is DayState.NO_MEASUREMENT


@pytest.mark.parametrize(
    "measured", ["heart_rate", "stress", "respiration", "spo2", "bb"]
)
def test_one_measured_sample_is_enough(tmp_path: Path, measured: str) -> None:
    """Sans indicateur, un seul échantillon mesuré (une valeur, pas un code ; un Body
    Battery ``measured``) : le jour n'est pas ``no_measurement``."""
    _no_measurement_base(tmp_path)
    later = ms(START + timedelta(minutes=6))
    if measured == "heart_rate":
        document = _doc(DayFamily.HEART_RATE)
        document["heartRateValues"] = [[later, 55]]
        write_document(tmp_path, DayFamily.HEART_RATE, document)
    elif measured == "spo2":
        write_document(tmp_path, DayFamily.SPO2, _doc(DayFamily.SPO2))
    else:
        stress = _doc(DayFamily.STRESS)
        stress["stressValuesArray"] = [[ms(START), -1]]
        stress["bodyBatteryValuesArray"] = [[ms(START), "MODELED", 40, 3]]
        respiration = _doc(DayFamily.RESPIRATION)
        respiration["respirationValuesArray"] = [[ms(START), -1]]
        if measured == "stress":
            stress["stressValuesArray"].append([later, 20])
        elif measured == "respiration":
            respiration["respirationValuesArray"].append([later, 15])
        else:
            stress["bodyBatteryValuesArray"] = [[ms(START), "MEASURED", 40, 3]]
        write_document(tmp_path, DayFamily.STRESS, stress)
        write_document(tmp_path, DayFamily.RESPIRATION, respiration)
    assert record(build(tmp_path)).state is DayState.COMPLETE


def test_a_night_is_a_measurement_without_indicator(tmp_path: Path) -> None:
    _no_measurement_base(tmp_path)
    assert record(build(tmp_path)).state is DayState.NO_MEASUREMENT
    write_document(tmp_path, DayFamily.SLEEP, _stripped_sleep())
    assert record(build(tmp_path)).state is DayState.COMPLETE


def test_truncated_wins_over_complete(tmp_path: Path) -> None:
    """``fin_donnees`` une milliseconde avant début + 24 h : ``truncated`` ; à début +
    24 h : ``complete``."""
    end = START + timedelta(days=1)
    before = gmt_text(end - timedelta(seconds=1), ".999")
    write_day(
        tmp_path,
        families=(DayFamily.DAILY_SUMMARY,),
        daily_summary=_summary(wellnessEndTimeGmt=before),
    )
    day = record(build(tmp_path))
    assert day.data_end == end - timedelta(milliseconds=1)
    assert day.state is DayState.TRUNCATED
    write_day(tmp_path, families=(DayFamily.DAILY_SUMMARY,))
    assert record(build(tmp_path)).state is DayState.COMPLETE


def test_a_truncated_day_without_night(tmp_path: Path) -> None:
    write_day(
        tmp_path,
        families=(DayFamily.DAILY_SUMMARY, DayFamily.HEART_RATE),
        daily_summary=_summary(wellnessEndTimeGmt=gmt_text(NOON)),
    )
    day = record(build(tmp_path))
    assert day.state is DayState.TRUNCATED
    assert day.night is None
    assert day.data_end == NOON


# --- la fenêtre du jour -------------------------------------------------------------


def test_a_day_without_daily_summary_takes_the_window_of_heart_rate(
    tmp_path: Path,
) -> None:
    families = [family for family in DayFamily if family is not DayFamily.DAILY_SUMMARY]
    write_day(tmp_path, families=families)
    ingestion = build(tmp_path)
    day = record(ingestion)
    assert day.window_family is DayFamily.HEART_RATE
    assert day.window_start == START
    assert day.wellness_data is None
    assert ingestion.report.window_families == (
        FamilyDayCount(DayFamily.HEART_RATE, 1),
    )


def test_the_window_falls_back_in_the_order_of_the_note(tmp_path: Path) -> None:
    order = (DayFamily.STRESS, DayFamily.RESPIRATION, DayFamily.SPO2)
    for position, family in enumerate(order):
        root = tmp_path / family.value
        write_day(root, families=order[position:])
        ingestion = build(root)
        assert record(ingestion).window_family is family
        assert ingestion.report.window_families == (FamilyDayCount(family, 1),)


def test_a_family_whose_window_differs_is_counted(tmp_path: Path) -> None:
    stress = _doc(DayFamily.STRESS)
    later = at(DAY, 1)
    stress["startTimestampGMT"] = gmt_text(later)
    stress["startTimestampLocal"] = local_text(later)
    write_day(tmp_path, stress=stress)
    ingestion = build(tmp_path)
    assert record(ingestion).window_start == START
    assert ingestion.report.window_mismatches == (FamilyDayCount(DayFamily.STRESS, 1),)


def test_a_window_with_another_offset_is_counted(tmp_path: Path) -> None:
    """Même jour, autre décalage : le début n'est pas le même (instant et décalage)."""
    same_instant = at(DAY, 1, offset=PLUS2)
    assert same_instant == START
    heart_rate = DOCUMENTS[DayFamily.HEART_RATE](DAY, same_instant)
    write_day(tmp_path, heart_rate=heart_rate)
    ingestion = build(tmp_path)
    assert ingestion.report.window_mismatches == (
        FamilyDayCount(DayFamily.HEART_RATE, 1),
    )


# --- l'export de référence ----------------------------------------------------------


def test_complete_with_detail_wins_over_a_more_recent_complete(tmp_path: Path) -> None:
    """L'ancien complet avec son détail, le récent complet **sans** son détail :
    l'ancien est la référence (le détail passe avant la date)."""
    write_day(tmp_path, export=EXPORT_A)
    write_day(tmp_path, export=EXPORT_B, families=(DayFamily.DAILY_SUMMARY,))
    day = record(build(tmp_path, EXPORT_A, EXPORT_B))
    assert day.reference_export == EXPORT_A
    assert day.state is DayState.COMPLETE


def test_the_most_recent_complete_with_detail(tmp_path: Path) -> None:
    write_day(tmp_path, export=EXPORT_A)
    write_day(tmp_path, export=EXPORT_B)
    assert record(build(tmp_path, EXPORT_A, EXPORT_B)).reference_export == EXPORT_B


def test_complete_wins_over_a_more_recent_truncated(tmp_path: Path) -> None:
    """L'ancien complet **sans son détail**, le récent tronqué : l'ancien est la
    référence, ``complete`` (avec le détail, la première règle déciderait seule)."""
    write_day(tmp_path, export=EXPORT_A, families=(DayFamily.DAILY_SUMMARY,))
    write_day(
        tmp_path,
        export=EXPORT_B,
        families=(DayFamily.DAILY_SUMMARY, DayFamily.HEART_RATE),
        daily_summary=_summary(wellnessEndTimeGmt=gmt_text(NOON)),
    )
    day = record(build(tmp_path, EXPORT_A, EXPORT_B))
    assert day.reference_export == EXPORT_A
    assert day.state is DayState.COMPLETE


def test_truncated_wins_over_a_more_recent_day_without_measurement(
    tmp_path: Path,
) -> None:
    """L'ancien tronqué, le récent ``no_measurement`` par l'indicateur faux, sur une
    fenêtre complète : l'ancien est la référence, ``truncated``."""
    write_day(
        tmp_path,
        export=EXPORT_A,
        families=(DayFamily.DAILY_SUMMARY,),
        daily_summary=_summary(wellnessEndTimeGmt=gmt_text(NOON)),
    )
    write_day(
        tmp_path,
        export=EXPORT_B,
        families=(DayFamily.DAILY_SUMMARY,),
        daily_summary=_summary(includesWellnessData=False),
    )
    day = record(build(tmp_path, EXPORT_A, EXPORT_B))
    assert day.reference_export == EXPORT_A
    assert day.state is DayState.TRUNCATED


def test_no_measurement_wins_over_a_more_recent_empty_day(tmp_path: Path) -> None:
    """Ni complet ni tronqué : le plus récent où le jour est ``no_measurement`` passe
    devant un plus récent ``empty`` (un seul fichier vide) ; le jour garde la fenêtre
    et les séries de l'ancien."""
    write_day(
        tmp_path,
        export=EXPORT_A,
        families=(DayFamily.DAILY_SUMMARY, DayFamily.HEART_RATE),
        daily_summary=_summary(includesWellnessData=False),
    )
    write_document(tmp_path, DayFamily.HRV, b"{}", export=EXPORT_B)
    day = record(build(tmp_path, EXPORT_A, EXPORT_B))
    assert day.reference_export == EXPORT_A
    assert day.state is DayState.NO_MEASUREMENT
    assert day.window_start == START
    assert day.series.heart_rate is not None


def test_otherwise_the_most_recent_that_carries_the_day(tmp_path: Path) -> None:
    """Aucun export ne donne de fenêtre au jour : le plus récent qui le porte, même par
    un seul fichier vide."""
    write_day(tmp_path, export=EXPORT_A, families=(DayFamily.TRAINING_STATUS,))
    write_document(tmp_path, DayFamily.HRV, b"{}", export=EXPORT_B)
    day = record(build(tmp_path, EXPORT_A, EXPORT_B))
    assert day.reference_export == EXPORT_B
    assert day.state is DayState.EMPTY


def test_spo2_is_not_detail(tmp_path: Path) -> None:
    """La SpO2 seule n'est pas « son détail » (l'ancien, qui la garde, ne passe pas
    devant le récent) ; un jour sans SpO2 a son détail par ses autres séries."""
    first = tmp_path / "first"
    write_day(
        first, export=EXPORT_A, families=(DayFamily.DAILY_SUMMARY, DayFamily.SPO2)
    )
    write_day(first, export=EXPORT_B, families=(DayFamily.DAILY_SUMMARY,))
    assert record(build(first, EXPORT_A, EXPORT_B)).reference_export == EXPORT_B
    second = tmp_path / "second"
    write_day(
        second,
        export=EXPORT_A,
        families=(DayFamily.DAILY_SUMMARY, DayFamily.HEART_RATE),
    )
    write_day(
        second, export=EXPORT_B, families=(DayFamily.DAILY_SUMMARY, DayFamily.SPO2)
    )
    assert record(build(second, EXPORT_A, EXPORT_B)).reference_export == EXPORT_A


# --- les cas nommés : la référence et ses écarts --------------------------------------


def test_c6_i_everything_from_the_export_with_detail(tmp_path: Path) -> None:
    """E1 complet avec son détail, E2 plus récent complet sans : tout vient de E1, une
    seule provenance ; l'écart de E2 en dégradation, ni emprunt ni refus."""
    write_day(tmp_path, export=EXPORT_A)
    write_day(
        tmp_path,
        export=EXPORT_B,
        families=(DayFamily.DAILY_SUMMARY, DayFamily.SLEEP),
        daily_summary=_summary(totalSteps=12000),
        sleep=_stripped_sleep(),
    )
    ingestion = build(tmp_path, EXPORT_A, EXPORT_B)
    day = record(ingestion)
    assert day.reference_export == EXPORT_A
    assert {source.retrieved_at for source in _sources(day)} == {RETRIEVED[EXPORT_A]}
    kinds = {count.comparison for count in ingestion.report.comparisons}
    assert kinds == {ComparisonClass.DEGRADATION}
    assert ingestion.report.borrowings == ()
    assert ingestion.report.borrowing_refusals == ()


def test_c6_ii_a_corrected_night_window_is_a_degradation(tmp_path: Path) -> None:
    """La fenêtre de la nuit corrigée dans E2, sans détail : tout vient de E1 ; la
    fenêtre de E2 en dégradation ; ni emprunt ni refus."""
    write_day(tmp_path, export=EXPORT_A)
    corrected = _stripped_sleep()
    corrected["dailySleepDTO"]["sleepStartTimestampGMT"] = ms(
        NIGHT_START + timedelta(minutes=10)
    )
    write_day(
        tmp_path,
        export=EXPORT_B,
        families=(DayFamily.DAILY_SUMMARY, DayFamily.SLEEP),
        sleep=corrected,
    )
    ingestion = build(tmp_path, EXPORT_A, EXPORT_B)
    day = record(ingestion)
    assert day.reference_export == EXPORT_A
    assert day.night is not None
    assert day.night.start == NIGHT_START
    assert (
        _kinds(ingestion, DayFamily.SLEEP)["dailySleepDTO.sleepStartTimestampGMT"]
        is ComparisonClass.DEGRADATION
    )
    assert ingestion.report.borrowings == ()
    assert ingestion.report.borrowing_refusals == ()


# --- les emprunts -------------------------------------------------------------------


@pytest.mark.parametrize(
    ("shift_ms", "bound", "borrowed"),
    [
        (0, "Start", True),
        (500, "Start", True),
        (1000, "Start", False),
        (-1, "Start", False),
        (500, "End", True),
        (1000, "End", False),
    ],
)
def test_borrowing_a_night_series(
    tmp_path: Path, shift_ms: int, bound: str, borrowed: bool
) -> None:
    """E2, la référence, a son détail mais pas les moments agités, que E1 porte.
    Fenêtre de la nuit égale à la seconde (un écart de 500 ms tombe dans la même
    seconde) : emprunt, deux provenances ; fenêtre différente (une seconde, ou une
    milliseconde qui change de seconde, au début ou à la fin) : refus compté."""
    lender = _doc(DayFamily.SLEEP)
    instant = NIGHT_START if bound == "Start" else NIGHT_END
    dto = lender["dailySleepDTO"]
    dto[f"sleep{bound}TimestampGMT"] = ms(instant) + shift_ms
    dto[f"sleep{bound}TimestampLocal"] = wall_ms(instant) + shift_ms
    write_day(tmp_path, export=EXPORT_A, sleep=lender)
    reference = _doc(DayFamily.SLEEP)
    reference["sleepRestlessMoments"] = []
    write_day(tmp_path, export=EXPORT_B, sleep=reference)
    ingestion = build(tmp_path, EXPORT_A, EXPORT_B)
    day = record(ingestion)
    assert day.reference_export == EXPORT_B
    assert day.night is not None
    assert day.night.source.retrieved_at == RETRIEVED[EXPORT_B]
    piece = "night.series.restless_moments"
    moments = day.night.series.restless_moments
    if borrowed:
        assert moments is not None
        assert moments.time_s == (1800.0,)
        assert moments.source.retrieved_at == RETRIEVED[EXPORT_A]
        assert ingestion.report.borrowings == (
            BorrowingCount(DayFamily.SLEEP, piece, 1),
        )
        assert ingestion.report.borrowing_refusals == ()
        assert (
            _kinds(ingestion, DayFamily.SLEEP)["sleepRestlessMoments[*]"]
            is ComparisonClass.BORROWING
        )
    else:
        assert moments is None
        assert ingestion.report.borrowings == ()
        assert ingestion.report.borrowing_refusals == (
            BorrowingRefusalCount(
                DayFamily.SLEEP, piece, BorrowingRefusal.NIGHT_WINDOW, 1
            ),
        )


def _segments_case(
    root: Path, plan: list[tuple[int, int]], summary: dict[str, Any]
) -> Any:
    lender = _doc(DayFamily.SLEEP)
    lender["sleepLevels"] = _levels(plan)
    write_day(root, export=EXPORT_A, sleep=lender)
    reference = _sleep(**summary)
    reference["sleepLevels"] = []
    write_day(root, export=EXPORT_B, sleep=reference)
    return build(root, EXPORT_A, EXPORT_B)


def _check_segments(
    ingestion: Any, plan: list[tuple[int, int]], borrowed: bool
) -> None:
    day = record(ingestion)
    assert day.reference_export == EXPORT_B
    assert day.night is not None
    if borrowed:
        assert len(day.night.segments) == len(plan)
        assert day.night.segments[0].start_s == 0.0
        assert ingestion.report.borrowings == (
            BorrowingCount(DayFamily.SLEEP, "night.segments", 1),
        )
        assert ingestion.report.borrowing_refusals == ()
    else:
        assert day.night.segments == ()
        assert ingestion.report.borrowings == ()
        assert ingestion.report.borrowing_refusals == (
            BorrowingRefusalCount(
                DayFamily.SLEEP,
                "night.segments",
                BorrowingRefusal.NIGHT_DURATIONS,
                1,
            ),
        )


@pytest.mark.parametrize(("short_s", "borrowed"), [(210, True), (211, False)])
def test_borrowing_segments_needs_their_durations(
    tmp_path: Path, short_s: int, borrowed: bool
) -> None:
    """Des segments empruntés redonnent les durées du résumé de la référence, phase
    par phase, à ``NIGHT_TOLERANCE_S`` près (borne comprise)."""
    plan = [(0, 3600), (1, 16200), (2, 5400), (3, 1800 - short_s), (-1, 1800)]
    _check_segments(_segments_case(tmp_path, plan, {}), plan, borrowed)


@pytest.mark.parametrize(
    ("plan", "summary", "borrowed"),
    [
        (_REM_30, {}, False),
        (_REM_30, {"remSleepSeconds": None}, True),
        (_UNMEASURABLE_10, {}, False),
        (_UNMEASURABLE_10, {"unmeasurableSleepSeconds": None}, True),
    ],
)
def test_borrowing_segments_skips_a_phase_missing_from_the_summary(
    tmp_path: Path,
    plan: list[tuple[int, int]],
    summary: dict[str, Any],
    borrowed: bool,
) -> None:
    """Des segments empruntés se comparent aux seules durées que porte le résumé de la
    nuit retenue : le paradoxal des segments (30 min) contre un résumé à 90 min, refus
    ``night_durations`` ; contre un ``remSleepSeconds`` nul, emprunt. De même du non
    mesurable (10 min contre 30, contre ``unmeasurableSleepSeconds`` nul)."""
    _check_segments(_segments_case(tmp_path, plan, summary), plan, borrowed)


def _without(family: DayFamily) -> list[DayFamily]:
    return [item for item in DayFamily if item is not family]


def test_borrowing_a_whole_family(tmp_path: Path) -> None:
    """Une famille absente de la référence (pas de fichier) vient du plus récent des
    autres exports qui la porte ; la fenêtre de la nuit qu'elle recopie s'accorde."""
    write_day(tmp_path, export=EXPORT_A)
    write_day(tmp_path, export=EXPORT_B, families=_without(DayFamily.HRV))
    ingestion = build(tmp_path, EXPORT_A, EXPORT_B)
    day = record(ingestion)
    assert day.reference_export == EXPORT_B
    assert day.hrv is not None
    assert day.hrv.source.retrieved_at == RETRIEVED[EXPORT_A]
    assert ingestion.report.borrowings == (BorrowingCount(DayFamily.HRV, "hrv", 1),)
    assert ingestion.report.borrowing_refusals == ()
    assert set(_kinds(ingestion, DayFamily.HRV).values()) == {ComparisonClass.BORROWING}


def test_a_whole_family_counts_only_the_pieces_its_lender_carries(
    tmp_path: Path,
) -> None:
    """``sleep`` s'emprunte entière à un prêteur sans sieste : un morceau emprunté
    (``night``), pas deux ; ``naps``, que le prêteur ne porte pas, ne se compte pas."""
    lender = _doc(DayFamily.SLEEP)
    lender["dailySleepDTO"]["dailyNapDTOS"] = []
    write_day(tmp_path, export=EXPORT_A, sleep=lender)
    write_day(tmp_path, export=EXPORT_B, families=_without(DayFamily.SLEEP))
    ingestion = build(tmp_path, EXPORT_A, EXPORT_B)
    day = record(ingestion)
    assert day.night is not None
    assert day.naps == ()
    assert ingestion.report.borrowings == (BorrowingCount(DayFamily.SLEEP, "night", 1),)


@pytest.mark.parametrize("empty", [b"{}", b"[]", b"pas du json"])
def test_an_empty_or_refused_family_is_borrowed(tmp_path: Path, empty: bytes) -> None:
    """Une famille vide (``{}``, ``[]``) ou refusée est absente : elle s'emprunte."""
    write_day(tmp_path, export=EXPORT_A)
    write_day(tmp_path, export=EXPORT_B, hrv=empty)
    ingestion = build(tmp_path, EXPORT_A, EXPORT_B)
    day = record(ingestion)
    assert day.hrv is not None
    assert day.hrv.source.retrieved_at == RETRIEVED[EXPORT_A]
    assert ingestion.report.borrowings == (BorrowingCount(DayFamily.HRV, "hrv", 1),)
    refused = tuple(item for item in ingestion.report.refused if EXPORT_B in item.name)
    if empty == b"pas du json":
        assert refused == (
            DayFileRefused(
                f"garmin/{EXPORT_B}/hrv/{DAY.isoformat()}.json",
                DayFileRefusal.UNREADABLE_JSON,
            ),
        )
    else:
        assert refused == ()


def test_a_whole_family_with_another_night_is_refused(tmp_path: Path) -> None:
    lender = _doc(DayFamily.HRV)
    lender["sleepStartTimestampGMT"] = gmt_text(NIGHT_START + timedelta(minutes=10))
    write_day(tmp_path, export=EXPORT_A, hrv=lender)
    write_day(tmp_path, export=EXPORT_B, families=_without(DayFamily.HRV))
    ingestion = build(tmp_path, EXPORT_A, EXPORT_B)
    assert record(ingestion).hrv is None
    assert ingestion.report.borrowings == ()
    assert ingestion.report.borrowing_refusals == (
        BorrowingRefusalCount(DayFamily.HRV, "hrv", BorrowingRefusal.NIGHT_WINDOW, 1),
    )


def test_a_whole_family_with_another_day_window_is_refused(tmp_path: Path) -> None:
    """Une série du jour d'une famille empruntée : même début de fenêtre (instant et
    décalage), sinon refus ``day_window``."""
    later = at(DAY, 1)
    lender = DOCUMENTS[DayFamily.HEART_RATE](DAY, later)
    write_day(tmp_path, export=EXPORT_A, heart_rate=lender)
    write_day(tmp_path, export=EXPORT_B, families=_without(DayFamily.HEART_RATE))
    ingestion = build(tmp_path, EXPORT_A, EXPORT_B)
    assert record(ingestion).series.heart_rate is None
    assert ingestion.report.borrowings == ()
    assert ingestion.report.borrowing_refusals == (
        BorrowingRefusalCount(
            DayFamily.HEART_RATE, "series.heart_rate", BorrowingRefusal.DAY_WINDOW, 1
        ),
    )


def test_borrowing_a_day_series(tmp_path: Path) -> None:
    """Une série du jour absente d'une famille de la référence : du plus récent des
    autres exports qui la porte, à même début de fenêtre ; les versions de la série de
    Body Battery (``(3,)``) sont celles du prêteur, la référence n'en portant pas."""
    write_day(tmp_path, export=EXPORT_A)
    stress = _doc(DayFamily.STRESS)
    stress["bodyBatteryValuesArray"] = []
    write_day(tmp_path, export=EXPORT_B, stress=stress)
    ingestion = build(tmp_path, EXPORT_A, EXPORT_B)
    day = record(ingestion)
    battery = day.series.body_battery
    assert battery is not None
    assert battery.time_s == (0.0, 180.0)
    assert battery.source.retrieved_at == RETRIEVED[EXPORT_A]
    assert day.series.stress is not None
    assert day.series.stress.source.retrieved_at == RETRIEVED[EXPORT_B]
    assert day.versions.body_battery_series_versions == (3,)
    assert ingestion.report.borrowings == (
        BorrowingCount(DayFamily.STRESS, "series.body_battery", 1),
    )


def test_a_day_series_of_another_window_is_not_borrowed(tmp_path: Path) -> None:
    """La même série, d'une fenêtre qui commence à un autre instant : refus
    ``day_window``, la série reste absente."""
    lender = DOCUMENTS[DayFamily.STRESS](DAY, at(DAY, 1))
    write_day(tmp_path, export=EXPORT_A, stress=lender)
    stress = _doc(DayFamily.STRESS)
    stress["bodyBatteryValuesArray"] = []
    write_day(tmp_path, export=EXPORT_B, stress=stress)
    ingestion = build(tmp_path, EXPORT_A, EXPORT_B)
    day = record(ingestion)
    assert day.series.body_battery is None
    assert day.versions.body_battery_series_versions == ()
    assert ingestion.report.borrowings == ()
    assert ingestion.report.borrowing_refusals == (
        BorrowingRefusalCount(
            DayFamily.STRESS, "series.body_battery", BorrowingRefusal.DAY_WINDOW, 1
        ),
    )


def test_the_lender_is_the_most_recent_of_the_others(tmp_path: Path) -> None:
    """Trois exports : la référence (le plus récent) emprunte au plus récent des deux
    autres ; un écart avec les deux autres compte un jour, une fois."""
    older = _doc(DayFamily.HRV)
    older["hrvSummary"]["weeklyAvg"] = 40
    write_day(tmp_path, export=EXPORT_A, hrv=older)
    write_day(tmp_path, export=EXPORT_B)
    reference = _doc(DayFamily.SLEEP)
    reference["dailySleepDTO"]["sleepScores"]["overall"]["value"] = 90
    write_day(
        tmp_path, export=EXPORT_C, families=_without(DayFamily.HRV), sleep=reference
    )
    ingestion = build(tmp_path, EXPORT_A, EXPORT_B, EXPORT_C)
    day = record(ingestion)
    assert day.reference_export == EXPORT_C
    assert day.hrv is not None
    assert day.hrv.weekly_avg_ms == 48
    assert day.hrv.source.retrieved_at == RETRIEVED[EXPORT_B]
    revisions = [
        count
        for count in ingestion.report.comparisons
        if count.family is DayFamily.SLEEP and count.field_path == SCORE
    ]
    assert len(revisions) == 1
    assert revisions[0].comparison is ComparisonClass.REVISION
    assert revisions[0].days == 1


def test_a_whole_daily_summary_with_another_window_is_refused(tmp_path: Path) -> None:
    """Une famille qui porte la fenêtre du jour et aucune série : l'accord sur la
    fenêtre (même début) se juge sur la famille entière."""
    lender = DOCUMENTS[DayFamily.DAILY_SUMMARY](DAY, at(DAY, 1))
    write_day(tmp_path, export=EXPORT_A, daily_summary=lender)
    write_day(tmp_path, export=EXPORT_B, families=_without(DayFamily.DAILY_SUMMARY))
    ingestion = build(tmp_path, EXPORT_A, EXPORT_B)
    day = record(ingestion)
    assert day.window_family is DayFamily.HEART_RATE
    assert day.wellness_data is None
    assert day.stress is None
    assert day.activity_totals is None
    assert ingestion.report.borrowings == ()
    assert ingestion.report.borrowing_refusals == tuple(
        BorrowingRefusalCount(
            DayFamily.DAILY_SUMMARY, piece, BorrowingRefusal.DAY_WINDOW, 1
        )
        for piece in sorted(
            ("wellness_data", "stress", "body_battery", "activity_totals")
        )
    )


def test_a_day_without_window_borrows_no_day_series(tmp_path: Path) -> None:
    """La référence n'a pas de fenêtre : aucun export n'en donne une au jour. L'ancien
    porte une série de FC sans fenêtre (ses trois champs de fenêtre nuls) : sa série du
    jour est refusée (``day_window``), ni gardée ni écartée, et rien d'autre ne
    s'emprunte (la FC de ``heart_rate`` n'est qu'une copie)."""
    write_document(
        tmp_path,
        DayFamily.HEART_RATE,
        _null_window(_doc(DayFamily.HEART_RATE)),
        export=EXPORT_A,
    )
    write_document(tmp_path, DayFamily.HRV, _doc(DayFamily.HRV), export=EXPORT_B)
    ingestion = build(tmp_path, EXPORT_A, EXPORT_B)
    day = record(ingestion)
    assert day.reference_export == EXPORT_B
    assert day.state is DayState.EMPTY
    assert day.series.heart_rate is None
    assert day.resting_hr is None
    assert ingestion.report.borrowings == ()
    assert ingestion.report.borrowing_refusals == (
        BorrowingRefusalCount(
            DayFamily.HEART_RATE, "series.heart_rate", BorrowingRefusal.DAY_WINDOW, 1
        ),
    )
    assert all(
        count.reason is not PointDiscard.NO_WINDOW
        for count in ingestion.report.point_discards
    )


def _refused_series_of_a_borrowed_family(root: Path) -> Any:
    """La référence B, à +01:00, sans ``heart_rate`` ; l'ancien A porte
    ``heart_rate`` sans fenêtre propre, et sa fenêtre du jour commence à +02:00."""
    write_day(
        root,
        export=EXPORT_A,
        families=(DayFamily.DAILY_SUMMARY, DayFamily.HEART_RATE),
        daily_summary=DOCUMENTS[DayFamily.DAILY_SUMMARY](DAY, midnight(DAY, PLUS2)),
        heart_rate=_null_window(_doc(DayFamily.HEART_RATE)),
    )
    write_day(root, export=EXPORT_B, families=_without(DayFamily.HEART_RATE))
    return build(root, EXPORT_A, EXPORT_B)


def test_a_day_with_window_keeps_out_the_refused_series_of_a_borrowed_family(
    tmp_path: Path,
) -> None:
    """La famille s'emprunte entière, sa série du jour est refusée (``day_window``) et
    reste absente du document ; ni emprunt compté pour elle, ni point écarté."""
    ingestion = _refused_series_of_a_borrowed_family(tmp_path)
    day = record(ingestion)
    assert day.reference_export == EXPORT_B
    assert day.window_start == START
    assert day.series.heart_rate is None
    assert ingestion.report.borrowings == ()
    assert ingestion.report.borrowing_refusals == (
        BorrowingRefusalCount(
            DayFamily.HEART_RATE, "series.heart_rate", BorrowingRefusal.DAY_WINDOW, 1
        ),
    )
    assert all(
        count.family is not DayFamily.HEART_RATE
        or count.reason is not PointDiscard.NO_WINDOW
        for count in ingestion.report.point_discards
    )


def test_every_leaf_of_a_whole_borrowed_family_is_a_borrowing(tmp_path: Path) -> None:
    """``heart_rate`` s'emprunte entière à A (la référence B n'en a pas), sa série du
    jour est refusée (``day_window``) : chacune de ses feuilles est un emprunt, la
    série refusée (``heartRateValues[*]``) et la copie (``restingHeartRate``)
    comprises."""
    kinds = _kinds(_refused_series_of_a_borrowed_family(tmp_path), DayFamily.HEART_RATE)
    assert kinds["heartRateValues[*]"] is ComparisonClass.BORROWING
    assert kinds["restingHeartRate"] is ComparisonClass.BORROWING
    assert set(kinds.values()) == {ComparisonClass.BORROWING}


# --- les écarts entre exports -------------------------------------------------------


def _score_export(root: Path, export: str, score: int, detail: bool) -> None:
    if detail:
        sleep = _doc(DayFamily.SLEEP)
        sleep["dailySleepDTO"]["sleepScores"]["overall"]["value"] = score
        write_day(root, export=export, sleep=sleep)
    else:
        sleep = _stripped_sleep()
        sleep["dailySleepDTO"]["sleepScores"]["overall"]["value"] = score
        write_day(
            root,
            export=export,
            families=(DayFamily.DAILY_SUMMARY, DayFamily.SLEEP),
            sleep=sleep,
        )


@pytest.mark.parametrize(
    ("old_detail", "new_detail", "reference", "kept", "kind"),
    [
        (True, True, EXPORT_B, 80, ComparisonClass.REVISION),
        (False, False, EXPORT_B, 80, ComparisonClass.REVISION),
        (True, False, EXPORT_A, 75, ComparisonClass.DEGRADATION),
        (False, True, EXPORT_B, 80, ComparisonClass.SET_APART),
    ],
)
def test_c6_iii_the_sleep_score_differs(
    tmp_path: Path,
    old_detail: bool,
    new_detail: bool,
    reference: str,
    kept: int,
    kind: ComparisonClass,
) -> None:
    """Le score de sommeil diffère entre E1 (75) et E2 (80). Les deux ont le détail, ou
    aucun : valeur de la référence, une révision ; E1 l'a et E2 ne l'a plus : valeur de
    E1, dégradation ; E1 ne l'a pas et E2 l'a : valeur de E2, à part."""
    _score_export(tmp_path, EXPORT_A, 75, old_detail)
    _score_export(tmp_path, EXPORT_B, 80, new_detail)
    ingestion = build(tmp_path, EXPORT_A, EXPORT_B)
    day = record(ingestion)
    assert day.reference_export == reference
    assert day.night is not None
    assert day.night.sleep_score == kept
    assert _kinds(ingestion, DayFamily.SLEEP)[SCORE] is kind


def test_c6_iv_two_exports_at_the_same_instant_are_refused(tmp_path: Path) -> None:
    write_day(tmp_path, export=EXPORT_A)
    write_day(tmp_path, export=EXPORT_B)
    same = RETRIEVED[EXPORT_A]
    exports = [load(tmp_path, EXPORT_A), load(tmp_path, EXPORT_B, same)]
    with pytest.raises(
        ValueError, match=r"^deux exports au même instant d'acquisition\.$"
    ):
        build_days(exports)
    with pytest.raises(ValueError, match=r"^build_days demande au moins un export\.$"):
        build_days([])


def test_c6_v_the_order_of_the_exports_changes_nothing(tmp_path: Path) -> None:
    write_day(tmp_path, export=EXPORT_A)
    write_day(tmp_path, export=EXPORT_B, families=_without(DayFamily.HRV))
    first = build_days([load(tmp_path, EXPORT_A), load(tmp_path, EXPORT_B)])
    second = build_days([load(tmp_path, EXPORT_B), load(tmp_path, EXPORT_A)])
    assert first == second
    assert first.report.borrowings != ()


def test_a_field_on_one_side_only_is_set_apart(tmp_path: Path) -> None:
    """Deux exports complets, aussi riches : une feuille d'un seul côté (un champ que
    Garmin aurait ajouté) est à part ; une feuille des deux côtés qui diffère est une
    révision."""
    write_day(tmp_path, export=EXPORT_A)
    write_day(
        tmp_path,
        export=EXPORT_B,
        daily_summary=_summary(inventedNewField=1, totalSteps=12000),
    )
    kinds = _kinds(build(tmp_path, EXPORT_A, EXPORT_B), DayFamily.DAILY_SUMMARY)
    assert kinds == {
        "inventedNewField": ComparisonClass.SET_APART,
        "totalSteps": ComparisonClass.REVISION,
    }


def test_a_truncated_day_is_never_revised(tmp_path: Path) -> None:
    """Un jour qui n'est pas complet dans les deux : ses écarts sont à part."""
    truncated = _summary(wellnessEndTimeGmt=gmt_text(NOON))
    write_day(tmp_path, export=EXPORT_A, daily_summary=truncated)
    write_day(
        tmp_path,
        export=EXPORT_B,
        daily_summary=_summary(wellnessEndTimeGmt=gmt_text(NOON), totalSteps=12000),
    )
    ingestion = build(tmp_path, EXPORT_A, EXPORT_B)
    assert record(ingestion).state is DayState.TRUNCATED
    assert _kinds(ingestion, DayFamily.DAILY_SUMMARY) == {
        "totalSteps": ComparisonClass.SET_APART
    }


def test_a_field_that_appears_with_a_lost_detail_is_a_degradation(
    tmp_path: Path,
) -> None:
    """E1 ancien avec son détail, E2 récent sans : tout écart du jour entre eux est
    une dégradation, une feuille de E2 seul (apparue) comprise, comme une feuille de E1
    seul (disparue) et une feuille des deux côtés (changée)."""
    write_day(
        tmp_path,
        export=EXPORT_A,
        families=(DayFamily.DAILY_SUMMARY, DayFamily.HEART_RATE),
    )
    write_day(
        tmp_path,
        export=EXPORT_B,
        families=(DayFamily.DAILY_SUMMARY,),
        daily_summary=_summary(inventedNewField=1, totalSteps=12000),
    )
    ingestion = build(tmp_path, EXPORT_A, EXPORT_B)
    assert record(ingestion).reference_export == EXPORT_A
    summary = _kinds(ingestion, DayFamily.DAILY_SUMMARY)
    assert summary == {
        "inventedNewField": ComparisonClass.DEGRADATION,
        "totalSteps": ComparisonClass.DEGRADATION,
    }
    heart_rate = _kinds(ingestion, DayFamily.HEART_RATE)
    assert heart_rate["heartRateValues[*]"] is ComparisonClass.DEGRADATION
    assert {count.comparison for count in ingestion.report.comparisons} == {
        ComparisonClass.DEGRADATION
    }


def test_ignored_and_not_ingested_fields_are_not_compared(tmp_path: Path) -> None:
    """``COMPARISON_IGNORED_FIELDS``, les champs ``tomorrow…`` et ``training_status``
    (comparé par bloc) ne se comptent pas en écarts."""
    first = at(DAY + timedelta(days=200), 12)
    second = first + timedelta(days=1)
    write_day(
        tmp_path,
        export=EXPORT_A,
        daily_summary=_summary(lastSyncTimestampGMT=gmt_text(first)),
    )
    hrv = _doc(DayFamily.HRV)
    hrv["hrvSummary"]["createTimeStamp"] = gmt_text(second, ".5")
    respiration = _doc(DayFamily.RESPIRATION)
    respiration["avgTomorrowSleepRespirationValue"] = 20
    respiration["tomorrowSleepStartTimestampGMT"] = gmt_text(at(DAY, 22))
    spo2 = _doc(DayFamily.SPO2)
    spo2["avgTomorrowSleepSpO2"] = 70
    status = _doc(DayFamily.TRAINING_STATUS)
    status["mostRecentTrainingStatus"]["lastPrimarySyncDate"] = D1.isoformat()
    write_day(
        tmp_path,
        export=EXPORT_B,
        daily_summary=_summary(lastSyncTimestampGMT=gmt_text(second)),
        hrv=hrv,
        respiration=respiration,
        spo2=spo2,
        training_status=status,
    )
    ingestion = build(tmp_path, EXPORT_A, EXPORT_B)
    assert ingestion.report.comparisons == ()
    assert ingestion.report.block_differences_between_exports == ()


# --- les bords de fenêtre -----------------------------------------------------------


def test_c15_i_the_night_series_comes_from_sleep_complete(tmp_path: Path) -> None:
    write_day(tmp_path)
    day = record(build(tmp_path))
    assert day.night is not None
    assert day.night.start == NIGHT_START
    series = day.night.series.heart_rate
    assert series is not None
    assert series.time_s == (0.0, 120.0)
    assert series.heart_rate_bpm == (52.0, 48.0)
    assert series.source.kind == "garmin_sleep"


def test_c15_ii_a_point_outside_the_window_of_its_file(tmp_path: Path) -> None:
    """Un point hors de la fenêtre de son fichier : gardé au jour du fichier qui le
    porte, son décalage hors de ``[0, 24 h]``, compté ; la borne de 24 h est dans la
    fenêtre."""
    heart_rate = _doc(DayFamily.HEART_RATE)
    heart_rate["heartRateValues"] = [
        [ms(START - timedelta(minutes=1)), 50],
        [ms(START), 55],
        [ms(START + timedelta(days=1)), 60],
    ]
    write_day(
        tmp_path,
        families=(DayFamily.DAILY_SUMMARY, DayFamily.HEART_RATE),
        heart_rate=heart_rate,
    )
    ingestion = build(tmp_path)
    series = record(ingestion).series.heart_rate
    assert series is not None
    assert series.time_s == (-60.0, 0.0, 86400.0)
    assert ingestion.report.window_edges == (
        WindowEdgeCount(DayFamily.HEART_RATE, "heartRateValues", 1, 0),
    )


def _heart_rate_day(root: Path, day: date, points: list[datetime]) -> None:
    heart_rate = _doc(DayFamily.HEART_RATE, day)
    heart_rate["heartRateValues"] = [[ms(point), 60] for point in points]
    write_day(
        root,
        day,
        families=(DayFamily.DAILY_SUMMARY, DayFamily.HEART_RATE),
        heart_rate=heart_rate,
    )


def test_c15_iii_instants_shared_by_two_neighbouring_files(tmp_path: Path) -> None:
    """Un instant présent dans les fichiers de deux jours voisins : gardé dans les
    deux, compté ; l'écart entre le dernier instant d'un jour et le premier du suivant,
    par famille et série du jour, le plus grand sur les couples de jours."""
    _heart_rate_day(tmp_path, DAY, [START, at(DAY, 12), midnight(D1)])
    _heart_rate_day(tmp_path, D1, [midnight(D1), at(D1, 12)])
    _heart_rate_day(tmp_path, D2, [midnight(D2) + timedelta(seconds=600)])
    ingestion = build(tmp_path)
    assert ingestion.report.window_edges == (
        WindowEdgeCount(DayFamily.HEART_RATE, "heartRateValues", 0, 1),
    )
    assert ingestion.report.day_boundary_gaps == (
        DayBoundaryGap(DayFamily.HEART_RATE, "heartRateValues", 2, 43800.0),
    )
    first = record(ingestion, DAY).series.heart_rate
    second = record(ingestion, D1).series.heart_rate
    assert first is not None
    assert first.time_s[-1] == 86400.0
    assert second is not None
    assert second.time_s[0] == 0.0


def test_c15_iii_no_gap_across_a_missing_day(tmp_path: Path) -> None:
    _heart_rate_day(tmp_path, DAY, [START])
    _heart_rate_day(tmp_path, D2, [midnight(D2)])
    ingestion = build(tmp_path)
    assert ingestion.report.day_boundary_gaps == ()
    assert ingestion.report.window_edges == ()


# --- les copies ---------------------------------------------------------------------


def test_copies_that_disagree_are_counted_by_quantity_and_family(
    tmp_path: Path,
) -> None:
    """Cinq copies qui diffèrent du document (la FC de repos de ``daily_summary`` et de
    ``heart_rate``, le début de la nuit de ``hrv`` décalé d'une seconde, la SpO2 de
    ``sleep``, le stress en code) : un jour chacune, par grandeur et famille ; la fin
    de la nuit de ``spo2``, à 999 ms de la fin, dans la même seconde, s'accorde."""
    heart_rate = _doc(DayFamily.HEART_RATE)
    heart_rate["restingHeartRate"] = 51
    hrv = _doc(DayFamily.HRV)
    hrv["sleepStartTimestampGMT"] = gmt_text(NIGHT_START + timedelta(seconds=1))
    stress = _doc(DayFamily.STRESS)
    stress["avgStressLevel"] = -1
    spo2 = _doc(DayFamily.SPO2)
    spo2["sleepEndTimestampGMT"] = gmt_text(NIGHT_END, ".999")
    write_day(
        tmp_path,
        daily_summary=_summary(restingHeartRate=50),
        heart_rate=heart_rate,
        hrv=hrv,
        sleep=_sleep(averageSpO2Value=93),
        stress=stress,
        spo2=spo2,
    )
    assert build(tmp_path).report.copy_disagreements == (
        CopyDisagreementCount("night.start", DayFamily.HRV, 1),
        CopyDisagreementCount("resting_hr.resting_hr_bpm", DayFamily.DAILY_SUMMARY, 1),
        CopyDisagreementCount("resting_hr.resting_hr_bpm", DayFamily.HEART_RATE, 1),
        CopyDisagreementCount("spo2.avg_sleep_spo2_percent", DayFamily.SLEEP, 1),
        CopyDisagreementCount("stress.average_level", DayFamily.STRESS, 1),
    )


def test_a_night_series_copy_is_compared_point_by_point(tmp_path: Path) -> None:
    write_day(tmp_path)
    assert build(tmp_path).report.copy_disagreements == ()
    hrv = _doc(DayFamily.HRV)
    hrv["hrvReadings"][0]["hrvValue"] = 46
    write_day(tmp_path, hrv=hrv)
    assert build(tmp_path).report.copy_disagreements == (
        CopyDisagreementCount("night.series.hrv", DayFamily.HRV, 1),
    )


def test_readiness_copies_are_counted_apart(tmp_path: Path) -> None:
    """« Copie antérieure » : les copies de Training Readiness, par grandeur copiée,
    hors du contrôle des copies."""
    readiness = [
        readiness_entry(DAY, sleepScore=70, acuteLoad=310, hrvWeeklyAverage=None),
        readiness_entry(
            DAY,
            timestamp=gmt_text(at(DAY, 18)),
            timestampLocal=local_text(at(DAY, 18)),
        ),
    ]
    write_day(tmp_path, training_readiness=readiness)
    report = build(tmp_path).report
    assert report.readiness_prior_copies == (
        ReadinessCopyCount("hrv.weekly_avg_ms", 1, 0),
        ReadinessCopyCount("night.sleep_score", 2, 1),
        ReadinessCopyCount("statuses.acute_load", 2, 1),
    )
    assert report.copy_disagreements == ()


# --- la nuit ------------------------------------------------------------------------


@pytest.mark.parametrize(("extra_s", "violations"), [(210, 0), (211, 1)])
def test_the_night_equality_at_its_tolerance(
    tmp_path: Path, extra_s: int, violations: int
) -> None:
    write_day(tmp_path, sleep=_sleep(awakeSleepSeconds=1800 + extra_s))
    assert build(tmp_path).report.night_equality_violations == violations


def test_night_equality_with_a_device_without_rem(tmp_path: Path) -> None:
    """Sans paradoxal détecté, il compte zéro ; détecté mais absent : pas de
    contrôle."""
    write_day(tmp_path, sleep=_sleep(deviceRemCapable=False, remSleepSeconds=None))
    assert build(tmp_path).report.night_equality_violations == 1
    write_day(
        tmp_path,
        sleep=_sleep(
            deviceRemCapable=False, remSleepSeconds=None, lightSleepSeconds=21600
        ),
    )
    assert build(tmp_path).report.night_equality_violations == 0
    write_day(tmp_path, sleep=_sleep(deviceRemCapable=True, remSleepSeconds=None))
    assert build(tmp_path).report.night_equality_violations == 0


def test_series_of_a_missing_night_are_dropped_and_counted(tmp_path: Path) -> None:
    write_day(
        tmp_path,
        families=(DayFamily.DAILY_SUMMARY, DayFamily.SLEEP),
        sleep=_sleep(sleepStartTimestampGMT=None, sleepEndTimestampGMT=None),
    )
    ingestion = build(tmp_path)
    assert record(ingestion).night is None
    dropped = {
        count.series_path: count.count
        for count in ingestion.report.point_discards
        if count.reason is PointDiscard.NO_NIGHT
    }
    assert dropped == {
        "sleepLevels": 2,
        "sleepHeartRate": 2,
        "sleepStress": 2,
        "sleepBodyBattery": 2,
        "hrvData": 2,
        "wellnessEpochRespirationDataDTOList": 2,
        "wellnessEpochSPO2DataDTOList": 2,
        "sleepRestlessMoments": 1,
    }
    assert all(
        count.family is DayFamily.SLEEP
        for count in ingestion.report.point_discards
        if count.reason is PointDiscard.NO_NIGHT
    )


def _windowless_stress(root: Path) -> Any:
    write_document(root, DayFamily.STRESS, _null_window(_doc(DayFamily.STRESS)))
    return build(root)


def test_day_series_without_window_are_dropped_and_counted(tmp_path: Path) -> None:
    ingestion = _windowless_stress(tmp_path)
    day = record(ingestion)
    assert day.state is DayState.EMPTY
    assert day.series.stress is None
    no_window = tuple(
        count
        for count in ingestion.report.point_discards
        if count.reason is PointDiscard.NO_WINDOW
    )
    assert no_window == (
        PointDiscardCount(
            DayFamily.STRESS, "bodyBatteryValuesArray", PointDiscard.NO_WINDOW, 2
        ),
        PointDiscardCount(
            DayFamily.STRESS, "stressValuesArray", PointDiscard.NO_WINDOW, 2
        ),
    )


def test_the_versions_of_a_dropped_body_battery_series_are_kept(tmp_path: Path) -> None:
    """Un jour sans fenêtre (le seul ``stress``, ses bornes nulles) dont la série de
    Body Battery porte la version 3 : jour ``empty``, série jetée (``no_window``),
    absente du document ; ses versions restent, ``(3,)``."""
    day = record(_windowless_stress(tmp_path))
    assert day.state is DayState.EMPTY
    assert day.series.body_battery is None
    assert day.versions.body_battery_series_versions == (3,)


def test_a_nap_overlapping_the_night_is_counted(tmp_path: Path) -> None:
    write_day(tmp_path)
    assert build(tmp_path).report.naps_overlapping_night == 0
    sleep = _doc(DayFamily.SLEEP)
    nap = sleep["dailySleepDTO"]["dailyNapDTOS"][0]
    nap["napStartTimestampGMT"] = gmt_text(at(DAY, 6, 30), "")
    nap["napEndTimestampGMT"] = gmt_text(at(DAY, 7), "")
    write_day(tmp_path, sleep=sleep)
    assert build(tmp_path).report.naps_overlapping_night == 1


# --- les comptes de lecture ---------------------------------------------------------


def test_a_value_out_of_range_and_an_unknown_code_are_counted(tmp_path: Path) -> None:
    """Une FC hors plage, un code de stress inconnu (−3), un contexte de Training
    Readiness inconnu, un type de confirmation inconnu : deux points écartés ;
    ``unknown_codes`` porte le code et le contexte, ``unknown_confirmations`` le type ;
    le résumé compte 2 codes inconnus (le code et le contexte, pas le type de
    confirmation)."""
    heart_rate = _doc(DayFamily.HEART_RATE)
    heart_rate["heartRateValues"] = [[ms(START), 55], [ms(at(DAY, 12)), 300]]
    stress = _doc(DayFamily.STRESS)
    stress["stressValuesArray"] = [[ms(START), 20], [ms(at(DAY, 1)), -3]]
    write_day(
        tmp_path,
        heart_rate=heart_rate,
        stress=stress,
        sleep=_sleep(sleepWindowConfirmationType="invented_type"),
        training_readiness=[readiness_entry(DAY, inputContext="INVENTED_CONTEXT")],
    )
    ingestion = build(tmp_path)
    report = ingestion.report
    assert report.point_discards == (
        PointDiscardCount(
            DayFamily.HEART_RATE, "heartRateValues", PointDiscard.OUT_OF_RANGE, 1
        ),
        PointDiscardCount(
            DayFamily.STRESS, "stressValuesArray", PointDiscard.UNKNOWN_CODE, 1
        ),
    )
    assert report.unknown_codes == (
        CodeCount(DayFamily.STRESS, "stressValuesArray[*][1]", "-3", 1),
        CodeCount(
            DayFamily.TRAINING_READINESS, "[*].inputContext", "INVENTED_CONTEXT", 1
        ),
    )
    assert report.unknown_confirmations == (
        CodeCount(
            DayFamily.SLEEP,
            "dailySleepDTO.sleepWindowConfirmationType",
            "invented_type",
            1,
        ),
    )
    assert ingestion.summary.point_discards == 2
    assert ingestion.summary.unknown_codes == 2


def test_only_the_retained_files_are_counted(tmp_path: Path) -> None:
    """Les écarts de lecture d'un export qui n'est pas la référence ne se comptent pas :
    ils ne sont pas dans ``interim/days/``."""
    heart_rate = _doc(DayFamily.HEART_RATE)
    heart_rate["heartRateValues"] = [[ms(START), 55], [ms(at(DAY, 12)), 300]]
    write_day(tmp_path, export=EXPORT_A, heart_rate=heart_rate)
    write_day(tmp_path, export=EXPORT_B)
    report = build(tmp_path, EXPORT_A, EXPORT_B).report
    assert report.point_discards == (
        PointDiscardCount(
            DayFamily.HEART_RATE, "heartRateValues", PointDiscard.NULL_VALUE, 1
        ),
    )


def test_readiness_entries_of_another_device(tmp_path: Path) -> None:
    readiness = [
        readiness_entry(DAY),
        readiness_entry(
            DAY,
            deviceId=OTHER_DEVICE,
            primaryActivityTracker=False,
            timestamp=gmt_text(at(DAY, 9)),
            timestampLocal=local_text(at(DAY, 9)),
        ),
    ]
    write_day(tmp_path, training_readiness=readiness)
    ingestion = build(tmp_path)
    assert ingestion.report.readiness_non_primary == 1
    assert [entry.instant for entry in record(ingestion).readiness] == [at(DAY, 7, 5)]


# --- les rangs d'appareil -----------------------------------------------------------


def _sleep_devices(day: date, need: int, nap: int) -> dict[str, Any]:
    sleep: dict[str, Any] = _doc(DayFamily.SLEEP, day)
    dto = sleep["dailySleepDTO"]
    for key in ("sleepNeed", "nextSleepNeed", "sleepAlignment"):
        dto[key]["deviceId"] = need
    dto["dailyNapDTOS"][0]["deviceId"] = nap
    sleep["wellnessSpO2SleepSummaryDTO"]["deviceId"] = need
    for item in sleep["wellnessEpochSPO2DataDTOList"]:
        item["deviceId"] = need
    return sleep


def test_device_ranks_one_device_then_two(tmp_path: Path) -> None:
    """Premier vu, premier rang, au fil des dates ; jamais l'identifiant."""
    write_day(tmp_path, DAY)
    write_day(tmp_path, D1, sleep=_sleep_devices(D1, 7, OTHER_DEVICE))
    ingestion = build(tmp_path)
    assert record(ingestion, DAY).device_ranks == (1,)
    assert record(ingestion, D1).device_ranks == (1, 2)


def test_device_ranks_in_the_order_of_appearance_in_a_family(tmp_path: Path) -> None:
    """Deux neufs dans une même famille : l'ordre où la lecture les rencontre (le besoin
    de sommeil avant les siestes), pas celui de leurs identifiants."""
    write_day(
        tmp_path, DAY, families=(DayFamily.SLEEP,), sleep=_sleep_devices(DAY, 8, 7)
    )
    write_day(tmp_path, D1, families=(DayFamily.SLEEP,), sleep=_sleep_devices(D1, 7, 7))
    ingestion = build(tmp_path)
    assert record(ingestion, DAY).device_ranks == (1, 2)
    assert record(ingestion, D1).device_ranks == (2,)


def test_device_ranks_follow_the_order_of_the_families(tmp_path: Path) -> None:
    """Deux neufs le même jour : la famille d'abord (``sleep`` avant
    ``training_readiness``), pas l'identifiant."""
    write_day(
        tmp_path,
        DAY,
        families=(DayFamily.SLEEP, DayFamily.TRAINING_READINESS),
        sleep=_sleep_devices(DAY, 8, 8),
    )
    write_day(tmp_path, D1, families=(DayFamily.TRAINING_READINESS,))
    ingestion = build(tmp_path)
    assert record(ingestion, DAY).device_ranks == (1, 2)
    assert record(ingestion, D1).device_ranks == (2,)


# --- les jours et le résumé ---------------------------------------------------------


def test_an_export_without_daily_families(tmp_path: Path) -> None:
    (tmp_path / "raw" / "garmin" / EXPORT_A / "activities").mkdir(parents=True)
    ingestion = build(tmp_path)
    assert ingestion.records == ()
    export = ingestion.report.exports[0]
    assert (export.files, export.first_day, export.last_day) == (0, None, None)
    assert export.families == ()
    assert ingestion.summary.days == 0


def test_an_empty_document_is_an_absent_family(tmp_path: Path) -> None:
    write_day(tmp_path, hrv=b"{}")
    ingestion = build(tmp_path)
    day = record(ingestion)
    assert day.hrv is None
    assert day.state is DayState.COMPLETE
    assert ingestion.report.refused == ()
    assert f"garmin/{EXPORT_A}/hrv/{DAY.isoformat()}.json" in {
        item.name for item in ingestion.report.read
    }


def test_an_only_empty_day_has_its_document(tmp_path: Path) -> None:
    write_day(tmp_path, DAY)
    write_document(tmp_path, DayFamily.HRV, b"[]", D1)
    ingestion = build(tmp_path)
    assert [item.day for item in ingestion.records] == [DAY, D1]
    empty = record(ingestion, D1)
    assert empty.state is DayState.EMPTY
    assert empty == DayRecord(
        day=D1,
        window_start=None,
        data_end=None,
        window_family=None,
        wellness_data=None,
        state=DayState.EMPTY,
        reference_export=EXPORT_A,
        night=None,
        naps=(),
        resting_hr=None,
        hrv=None,
        respiration=None,
        spo2=None,
        stress=None,
        body_battery=None,
        activity_totals=None,
        series=empty.series,
        readiness=(),
        versions=empty.versions,
        device_ranks=(),
    )
    assert empty.series.heart_rate is None
    assert empty.series.stress is None


def test_two_passes_give_the_same_documents(tmp_path: Path) -> None:
    write_day(tmp_path, export=EXPORT_A)
    write_day(tmp_path, export=EXPORT_B, families=_without(DayFamily.HRV))
    assert build(tmp_path, EXPORT_A, EXPORT_B) == build(tmp_path, EXPORT_A, EXPORT_B)


def test_the_summary_follows_the_report(tmp_path: Path) -> None:
    write_day(tmp_path, DAY, export=EXPORT_A)
    write_day(tmp_path, D1, export=EXPORT_A)
    write_day(
        tmp_path,
        DAY,
        export=EXPORT_B,
        families=_without(DayFamily.HRV),
        daily_summary=_summary(totalSteps=12000),
        heart_rate=b"pas du json",
    )
    write_document(tmp_path, DayFamily.HRV, b"{}", D2, EXPORT_B)
    ingestion = build(tmp_path, EXPORT_A, EXPORT_B)
    report, summary = ingestion.report, ingestion.summary

    def total(kind: ComparisonClass) -> int:
        return sum(item.days for item in report.comparisons if item.comparison is kind)

    assert summary.days == len(ingestion.records) == 3
    assert summary.reference_days == report.reference_days
    assert summary.states == (
        (DayState.EMPTY, 1),
        (DayState.NO_MEASUREMENT, 0),
        (DayState.TRUNCATED, 0),
        (DayState.COMPLETE, 2),
    )
    assert summary.borrowings == sum(item.count for item in report.borrowings) > 0
    assert summary.borrowing_refusals == sum(
        item.count for item in report.borrowing_refusals
    )
    assert summary.revisions == total(ComparisonClass.REVISION) > 0
    assert summary.degradations == total(ComparisonClass.DEGRADATION)
    assert summary.set_apart == total(ComparisonClass.SET_APART)
    assert summary.refused_files == len(report.refused) == 1
    assert summary.point_discards == sum(item.count for item in report.point_discards)
    assert summary.unknown_codes == sum(item.count for item in report.unknown_codes)
    history = ingestion.history
    assert summary.training_status_blocks == sum(
        len(suite)
        for suite in (
            history.statuses,
            history.load_balances,
            history.vo2_max,
            history.heat_acclimation,
            history.altitude_acclimation,
        )
    )
    assert summary.blocks_without_proper_instant == sum(
        item.count for item in report.blocks_without_proper_instant
    )


# --- les correctifs de la relecture -------------------------------------------------


def test_a_night_without_its_two_gmt_bounds_counts_no_discard(tmp_path: Path) -> None:
    """Les deux bornes GMT de la nuit nulles : pas de nuit, ses segments et séries
    jetés et comptés (``no_night``), et aucun écart ``night`` au rapport."""
    write_day(
        tmp_path,
        families=(DayFamily.DAILY_SUMMARY, DayFamily.SLEEP),
        sleep=_sleep(sleepStartTimestampGMT=None, sleepEndTimestampGMT=None),
    )
    ingestion = build(tmp_path)
    day = record(ingestion)
    assert day.night is None
    assert len(day.naps) == 1
    assert [
        count
        for count in ingestion.report.point_discards
        if count.series_path == "night"
    ] == []
    assert (
        PointDiscardCount(DayFamily.SLEEP, "sleepLevels", PointDiscard.NO_NIGHT, 2)
        in ingestion.report.point_discards
    )


def _third_export_case(root: Path, family: DayFamily, agree: bool) -> Any:
    """C, la référence, n'a pas ``family`` ; B, le plus récent des deux autres, la
    prête entière sans une de ses séries ; A porte cette série, à une fenêtre qui
    s'accorde (``agree``) ou non."""
    if family is DayFamily.STRESS:
        lender = _doc(DayFamily.STRESS)
        lender["bodyBatteryValuesArray"] = []
        third = (
            _doc(DayFamily.STRESS)
            if agree
            else DOCUMENTS[DayFamily.STRESS](DAY, at(DAY, 1))
        )
    else:
        lender = _doc(DayFamily.SLEEP)
        lender["sleepRestlessMoments"] = []
        third = _doc(DayFamily.SLEEP)
        if not agree:
            third["dailySleepDTO"]["sleepStartTimestampGMT"] += 1000
            third["dailySleepDTO"]["sleepStartTimestampLocal"] += 1000
    write_day(root, export=EXPORT_A, **{family.value: third})
    write_day(root, export=EXPORT_B, **{family.value: lender})
    write_day(root, export=EXPORT_C, families=_without(family))
    return build(root, EXPORT_A, EXPORT_B, EXPORT_C)


@pytest.mark.parametrize("family", [DayFamily.STRESS, DayFamily.SLEEP])
def test_a_series_missing_from_a_whole_borrowed_family_is_borrowed(
    tmp_path: Path, family: DayFamily
) -> None:
    """La famille vient entière de B ; la série qui lui manque, de A, aux fenêtres qui
    s'accordent (même début de la fenêtre du jour ; même nuit à la seconde) : deux
    provenances, deux emprunts comptés."""
    ingestion = _third_export_case(tmp_path, family, agree=True)
    day = record(ingestion)
    assert day.reference_export == EXPORT_C
    expected: tuple[BorrowingCount, ...]
    if family is DayFamily.STRESS:
        assert day.series.stress is not None
        assert day.series.stress.source.retrieved_at == RETRIEVED[EXPORT_B]
        battery = day.series.body_battery
        assert battery is not None
        assert battery.time_s == (0.0, 180.0)
        assert battery.source.retrieved_at == RETRIEVED[EXPORT_A]
        assert day.versions.body_battery_series_versions == (3,)
        expected = (
            BorrowingCount(DayFamily.STRESS, "series.body_battery", 1),
            BorrowingCount(DayFamily.STRESS, "series.stress", 1),
        )
    else:
        assert day.night is not None
        assert day.night.source.retrieved_at == RETRIEVED[EXPORT_B]
        moments = day.night.series.restless_moments
        assert moments is not None
        assert moments.time_s == (1800.0,)
        assert moments.source.retrieved_at == RETRIEVED[EXPORT_A]
        expected = (
            BorrowingCount(DayFamily.SLEEP, "naps", 1),
            BorrowingCount(DayFamily.SLEEP, "night", 1),
            BorrowingCount(DayFamily.SLEEP, "night.series.restless_moments", 1),
        )
    assert ingestion.report.borrowings == expected
    assert ingestion.report.borrowing_refusals == ()


@pytest.mark.parametrize("family", [DayFamily.STRESS, DayFamily.SLEEP])
def test_a_series_missing_from_a_whole_borrowed_family_needs_its_window(
    tmp_path: Path, family: DayFamily
) -> None:
    """Le même, la fenêtre de A en désaccord (la fenêtre du jour commence une heure
    plus tard ; la nuit une seconde plus tard) : la série reste absente, le refus se
    compte."""
    ingestion = _third_export_case(tmp_path, family, agree=False)
    day = record(ingestion)
    if family is DayFamily.STRESS:
        assert day.series.body_battery is None
        assert day.versions.body_battery_series_versions == ()
        refusal = BorrowingRefusalCount(
            DayFamily.STRESS, "series.body_battery", BorrowingRefusal.DAY_WINDOW, 1
        )
    else:
        assert day.night is not None
        assert day.night.series.restless_moments is None
        refusal = BorrowingRefusalCount(
            DayFamily.SLEEP,
            "night.series.restless_moments",
            BorrowingRefusal.NIGHT_WINDOW,
            1,
        )
    assert ingestion.report.borrowing_refusals == (refusal,)


# --- les règles que la suite ne tenait pas ------------------------------------------


def test_a_missing_night_drops_only_the_series_it_carries(tmp_path: Path) -> None:
    """La nuit absente (ses deux bornes GMT nulles), ses segments et ses moments agités
    vides : seules les séries portées se jettent, une série absente ne compte rien."""
    sleep = _sleep(sleepStartTimestampGMT=None, sleepEndTimestampGMT=None)
    sleep["sleepRestlessMoments"] = []
    sleep["sleepLevels"] = []
    write_day(
        tmp_path, families=(DayFamily.DAILY_SUMMARY, DayFamily.SLEEP), sleep=sleep
    )
    dropped = {
        count.series_path: count.count
        for count in build(tmp_path).report.point_discards
        if count.reason is PointDiscard.NO_NIGHT
    }
    assert dropped == {
        "sleepHeartRate": 2,
        "sleepStress": 2,
        "sleepBodyBattery": 2,
        "hrvData": 2,
        "wellnessEpochRespirationDataDTOList": 2,
        "wellnessEpochSPO2DataDTOList": 2,
    }


def test_the_detail_of_an_empty_day_makes_a_degradation(tmp_path: Path) -> None:
    """A, l'ancien, porte le jour sans fenêtre (``empty``, le seul ``sleep``) mais avec
    son détail ; B, le récent, le porte complet sans son détail, un autre score de
    sommeil : B est la référence, et l'écart du score est une dégradation."""
    write_day(tmp_path, export=EXPORT_A, families=(DayFamily.SLEEP,))
    sleep = _stripped_sleep()
    sleep["dailySleepDTO"]["sleepScores"]["overall"]["value"] = 90
    write_day(
        tmp_path,
        export=EXPORT_B,
        families=(DayFamily.DAILY_SUMMARY, DayFamily.SLEEP),
        sleep=sleep,
    )
    ingestion = build(tmp_path, EXPORT_A, EXPORT_B)
    assert record(ingestion).reference_export == EXPORT_B
    assert _kinds(ingestion, DayFamily.SLEEP)[SCORE] is ComparisonClass.DEGRADATION


def _piece(day: DayRecord, piece: str) -> Any:
    """Un morceau du document, par son chemin (celui de ``BorrowingCount.piece``)."""
    if piece.startswith("series."):
        return getattr(day.series, piece.removeprefix("series."))
    return getattr(day, piece)


_WHOLE_PIECES = [
    (DayFamily.SLEEP, ("naps", "night")),
    (DayFamily.HRV, ("hrv",)),
    (DayFamily.RESTING_HR, ("resting_hr",)),
    (DayFamily.HEART_RATE, ("series.heart_rate",)),
    (DayFamily.STRESS, ("series.body_battery", "series.stress")),
    (DayFamily.RESPIRATION, ("respiration", "series.respiration")),
    (DayFamily.SPO2, ("series.spo2", "spo2")),
    (
        DayFamily.DAILY_SUMMARY,
        ("activity_totals", "body_battery", "stress", "wellness_data"),
    ),
    (DayFamily.TRAINING_READINESS, ("readiness",)),
]


@pytest.mark.parametrize(("family", "pieces"), _WHOLE_PIECES)
def test_a_whole_family_borrows_each_of_its_pieces(
    tmp_path: Path, family: DayFamily, pieces: tuple[str, ...]
) -> None:
    """Chaque famille qui s'emprunte, absente de la référence B et portée entière par A
    (fenêtres en accord) : chacun de ses morceaux s'emprunte, une fois, et le document
    le porte, de la provenance de A."""
    write_day(tmp_path, export=EXPORT_A)
    write_day(tmp_path, export=EXPORT_B, families=_without(family))
    ingestion = build(tmp_path, EXPORT_A, EXPORT_B)
    day = record(ingestion)
    assert day.reference_export == EXPORT_B
    assert ingestion.report.borrowings == tuple(
        BorrowingCount(family, piece, 1) for piece in pieces
    )
    assert ingestion.report.borrowing_refusals == ()
    for piece in pieces:
        value = _piece(day, piece)
        assert value is not None, piece
        assert value != (), piece
        items = value if isinstance(value, tuple) else (value,)
        for item in items:
            if hasattr(item, "source"):
                assert item.source.retrieved_at == RETRIEVED[EXPORT_A], piece


def test_a_family_that_copies_one_bound_of_the_night_is_borrowed(
    tmp_path: Path,
) -> None:
    """``hrv`` de A ne recopie que le début de la nuit (sa fin nulle) : rien à comparer
    sur la nuit, la famille s'emprunte."""
    lender = _doc(DayFamily.HRV)
    lender["sleepEndTimestampGMT"] = None
    write_day(tmp_path, export=EXPORT_A, hrv=lender)
    write_day(tmp_path, export=EXPORT_B, families=_without(DayFamily.HRV))
    ingestion = build(tmp_path, EXPORT_A, EXPORT_B)
    assert ingestion.report.borrowings == (BorrowingCount(DayFamily.HRV, "hrv", 1),)
    assert ingestion.report.borrowing_refusals == ()


def test_borrowed_segments_add_up_the_durations_of_a_phase(tmp_path: Path) -> None:
    """Deux segments légers (2 h 15 chacun) redonnent ensemble le léger du résumé
    (4 h 30) : l'emprunt passe."""
    plan = [(0, 3600), (1, 8100), (1, 8100), (2, 5400), (3, 1800), (-1, 1800)]
    _check_segments(_segments_case(tmp_path, plan, {}), plan, borrowed=True)


def _shifted_night_copy(family: DayFamily) -> dict[str, Any]:
    """Le document de ``family`` dont la copie du début de la nuit est dix minutes plus
    tard que la nuit de ``sleep``."""
    document: dict[str, Any] = _doc(family)
    document["sleepStartTimestampGMT"] = gmt_text(NIGHT_START + timedelta(minutes=10))
    return document


def test_the_night_of_the_document_is_the_one_of_sleep_before_its_copies(
    tmp_path: Path,
) -> None:
    """La référence B porte la nuit de ``sleep`` et, dans ``hrv``, une copie de ses
    bornes décalée de dix minutes ; ``respiration``, que B n'a pas, vient de A, sa copie
    égale à la nuit de ``sleep`` : l'emprunt se juge contre ``sleep``, il passe."""
    write_day(
        tmp_path,
        export=EXPORT_A,
        families=(DayFamily.DAILY_SUMMARY, DayFamily.RESPIRATION),
    )
    write_day(
        tmp_path,
        export=EXPORT_B,
        families=_without(DayFamily.RESPIRATION),
        hrv=_shifted_night_copy(DayFamily.HRV),
    )
    ingestion = build(tmp_path, EXPORT_A, EXPORT_B)
    assert record(ingestion).reference_export == EXPORT_B
    assert ingestion.report.borrowings == (
        BorrowingCount(DayFamily.RESPIRATION, "respiration", 1),
        BorrowingCount(DayFamily.RESPIRATION, "series.respiration", 1),
    )
    assert ingestion.report.borrowing_refusals == ()


def test_without_sleep_the_night_of_the_document_is_a_copy(tmp_path: Path) -> None:
    """Ni A ni B ne portent ``sleep`` : la nuit du document est la copie de ses bornes
    dans ``hrv`` de B ; ``respiration`` de A, dont la copie en diffère de dix minutes,
    est refusée (``night_window``)."""
    write_day(
        tmp_path,
        export=EXPORT_A,
        families=(DayFamily.DAILY_SUMMARY, DayFamily.RESPIRATION),
    )
    write_day(
        tmp_path,
        export=EXPORT_B,
        families=(DayFamily.DAILY_SUMMARY, DayFamily.HRV),
        hrv=_shifted_night_copy(DayFamily.HRV),
    )
    ingestion = build(tmp_path, EXPORT_A, EXPORT_B)
    day = record(ingestion)
    assert day.reference_export == EXPORT_B
    assert day.night is None
    assert day.respiration is None
    assert ingestion.report.borrowings == ()
    assert ingestion.report.borrowing_refusals == tuple(
        BorrowingRefusalCount(
            DayFamily.RESPIRATION, piece, BorrowingRefusal.NIGHT_WINDOW, 1
        )
        for piece in ("respiration", "series.respiration")
    )


def test_a_day_series_of_a_file_without_window_agrees_by_its_export(
    tmp_path: Path,
) -> None:
    """La série de FC de A vient d'un fichier sans fenêtre propre (ses champs nuls) ; la
    fenêtre du jour de A (``daily_summary``) commence comme celle de la référence B : la
    série s'emprunte, de la provenance de A."""
    write_day(
        tmp_path,
        export=EXPORT_A,
        families=(DayFamily.DAILY_SUMMARY, DayFamily.HEART_RATE),
        heart_rate=_null_window(_doc(DayFamily.HEART_RATE)),
    )
    own = _doc(DayFamily.HEART_RATE)
    own["heartRateValues"] = []
    write_day(tmp_path, export=EXPORT_B, heart_rate=own)
    ingestion = build(tmp_path, EXPORT_A, EXPORT_B)
    day = record(ingestion)
    assert day.reference_export == EXPORT_B
    series = day.series.heart_rate
    assert series is not None
    assert series.time_s == (0.0, 43200.0)
    assert series.source.retrieved_at == RETRIEVED[EXPORT_A]
    assert ingestion.report.borrowings == (
        BorrowingCount(DayFamily.HEART_RATE, "series.heart_rate", 1),
    )


def test_two_refused_families_and_a_borrowed_one(tmp_path: Path) -> None:
    """B n'a ni ``hrv``, ni ``resting_hr``, ni ``spo2`` ; A les porte, ``hrv`` et
    ``spo2`` d'une autre nuit : les deux refus se comptent, et ``resting_hr``, entre
    elles dans l'ordre des familles, s'emprunte."""
    write_day(
        tmp_path,
        export=EXPORT_A,
        hrv=_shifted_night_copy(DayFamily.HRV),
        spo2=_shifted_night_copy(DayFamily.SPO2),
    )
    lacking = (DayFamily.HRV, DayFamily.RESTING_HR, DayFamily.SPO2)
    write_day(
        tmp_path,
        export=EXPORT_B,
        families=[family for family in DayFamily if family not in lacking],
    )
    ingestion = build(tmp_path, EXPORT_A, EXPORT_B)
    assert ingestion.report.borrowings == (
        BorrowingCount(DayFamily.RESTING_HR, "resting_hr", 1),
    )
    night_window = BorrowingRefusal.NIGHT_WINDOW
    assert ingestion.report.borrowing_refusals == (
        BorrowingRefusalCount(DayFamily.HRV, "hrv", night_window, 1),
        BorrowingRefusalCount(DayFamily.SPO2, "series.spo2", night_window, 1),
        BorrowingRefusalCount(DayFamily.SPO2, "spo2", night_window, 1),
    )


def _lacking_series() -> tuple[dict[str, Any], dict[str, Any]]:
    """``stress`` sans ses deux séries ; ``sleep`` sans FC, sans moments agités, sans
    segments."""
    stress: dict[str, Any] = _doc(DayFamily.STRESS)
    stress["stressValuesArray"] = []
    stress["bodyBatteryValuesArray"] = []
    sleep: dict[str, Any] = _doc(DayFamily.SLEEP)
    for key in ("sleepHeartRate", "sleepRestlessMoments", "sleepLevels"):
        sleep[key] = []
    return stress, sleep


def test_every_missing_series_skips_a_lender_that_lacks_it(tmp_path: Path) -> None:
    """C, la référence, n'a ni les deux séries de ``stress``, ni deux séries et les
    segments de sa nuit ; B, le plus récent des autres, ne les a pas non plus ; A les
    porte : chacune vient de A, chacune comptée, et ses feuilles sont des emprunts."""
    full = _doc(DayFamily.SLEEP)
    full["sleepLevels"] = _levels(_FULL_PLAN)
    write_day(tmp_path, export=EXPORT_A, sleep=full)
    for export in (EXPORT_B, EXPORT_C):
        stress, sleep = _lacking_series()
        write_day(tmp_path, export=export, stress=stress, sleep=sleep)
    ingestion = build(tmp_path, EXPORT_A, EXPORT_B, EXPORT_C)
    day = record(ingestion)
    assert day.reference_export == EXPORT_C
    assert ingestion.report.borrowings == (
        BorrowingCount(DayFamily.SLEEP, "night.segments", 1),
        BorrowingCount(DayFamily.SLEEP, "night.series.heart_rate", 1),
        BorrowingCount(DayFamily.SLEEP, "night.series.restless_moments", 1),
        BorrowingCount(DayFamily.STRESS, "series.body_battery", 1),
        BorrowingCount(DayFamily.STRESS, "series.stress", 1),
    )
    assert ingestion.report.borrowing_refusals == ()
    night = day.night
    assert night is not None
    assert night.source.retrieved_at == RETRIEVED[EXPORT_C]
    assert night.segments == (
        SleepSegment(0.0, 3600.0, SleepStage.DEEP),
        SleepSegment(3600.0, 19800.0, SleepStage.LIGHT),
        SleepSegment(19800.0, 25200.0, SleepStage.REM),
        SleepSegment(25200.0, 27000.0, SleepStage.AWAKE),
        SleepSegment(27000.0, 28800.0, SleepStage.UNMEASURABLE),
    )
    for series in (
        night.series.heart_rate,
        night.series.restless_moments,
        day.series.stress,
        day.series.body_battery,
    ):
        assert series is not None
        assert series.source.retrieved_at == RETRIEVED[EXPORT_A]
    sleep_kinds = _kinds(ingestion, DayFamily.SLEEP)
    for path in ("sleepLevels[*]", "sleepHeartRate[*]", "sleepRestlessMoments[*]"):
        assert sleep_kinds[path] is ComparisonClass.BORROWING, path
    stress_kinds = _kinds(ingestion, DayFamily.STRESS)
    for path in ("stressValuesArray[*]", "bodyBatteryValuesArray[*]"):
        assert stress_kinds[path] is ComparisonClass.BORROWING, path


def test_segments_of_another_night_are_refused_by_their_window(tmp_path: Path) -> None:
    """Des segments qui redonnent les durées du résumé, d'une nuit une seconde plus
    tard : refus ``night_window`` (la fenêtre passe avant les durées)."""
    lender = _doc(DayFamily.SLEEP)
    lender["sleepLevels"] = _levels(_FULL_PLAN)
    dto = lender["dailySleepDTO"]
    dto["sleepStartTimestampGMT"] += 1000
    dto["sleepStartTimestampLocal"] += 1000
    write_day(tmp_path, export=EXPORT_A, sleep=lender)
    reference = _doc(DayFamily.SLEEP)
    reference["sleepLevels"] = []
    write_day(tmp_path, export=EXPORT_B, sleep=reference)
    ingestion = build(tmp_path, EXPORT_A, EXPORT_B)
    night = record(ingestion).night
    assert night is not None
    assert night.segments == ()
    assert ingestion.report.borrowing_refusals == (
        BorrowingRefusalCount(
            DayFamily.SLEEP, "night.segments", BorrowingRefusal.NIGHT_WINDOW, 1
        ),
    )


def test_the_segments_of_a_night_in_seconds_from_its_start(tmp_path: Path) -> None:
    """Les segments du document, en secondes depuis le début de la nuit, début et fin
    exacts."""
    write_day(tmp_path)
    night = record(build(tmp_path)).night
    assert night is not None
    assert night.segments == (
        SleepSegment(0.0, 3600.0, SleepStage.LIGHT),
        SleepSegment(3600.0, 7200.0, SleepStage.DEEP),
    )


def test_the_document_carries_the_versions_and_summaries_of_its_families(
    tmp_path: Path,
) -> None:
    respiration = _doc(DayFamily.RESPIRATION)
    respiration["respirationVersion"] = 201
    write_day(
        tmp_path,
        respiration=respiration,
        daily_summary=_summary(respirationAlgorithmVersion=202),
    )
    day = record(build(tmp_path))
    assert day.versions == AlgorithmVersions(
        sleep_version=2,
        sleep_respiration_version=200,
        respiration_version=201,
        summary_respiration_version=202,
        summary_body_battery_version=3,
        body_battery_series_versions=(3,),
    )
    assert day.wellness_data is True
    assert day.respiration is not None
    assert day.respiration.avg_sleep_breaths_per_min == 13.0
    assert day.body_battery is not None
    assert day.body_battery.charged == 60
    assert day.activity_totals is not None
    assert day.activity_totals.steps == 10000


def test_a_stress_copy_against_an_average_written_as_a_code(tmp_path: Path) -> None:
    """Le stress moyen du document est un code (−1, de ``daily_summary``) ; la copie de
    ``stress`` porte un niveau (25) : elle diffère, comptée."""
    write_day(tmp_path, daily_summary=_summary(averageStressLevel=-1))
    assert build(tmp_path).report.copy_disagreements == (
        CopyDisagreementCount("stress.average_level", DayFamily.STRESS, 1),
    )


def _counted_lender(root: Path, day: date) -> None:
    """A, au jour ``day`` : toutes ses familles, ``hrv`` d'une autre nuit."""
    hrv = _doc(DayFamily.HRV, day)
    hrv["sleepStartTimestampGMT"] = gmt_text(at(day - timedelta(days=1), 23, 10))
    write_day(root, day, export=EXPORT_A, hrv=hrv)


def _counted_reference(root: Path, day: date) -> None:
    """B, au jour ``day`` : ni ``hrv`` ni ``daily_summary`` ; une FC de repos copiée qui
    diffère, une fenêtre de ``stress`` une heure plus tard et un code de stress inconnu,
    un type de confirmation inconnu, deux champs de la nuit révisés, un bloc « statut »
    sans sa date."""
    heart_rate = _doc(DayFamily.HEART_RATE, day)
    heart_rate["restingHeartRate"] = 51
    stress = _doc(DayFamily.STRESS, day)
    stress["startTimestampGMT"] = gmt_text(at(day, 1))
    stress["startTimestampLocal"] = local_text(at(day, 1))
    stress["stressValuesArray"] = [[ms(midnight(day)), 20], [ms(at(day, 2)), -3]]
    sleep = _doc(DayFamily.SLEEP, day)
    dto = sleep["dailySleepDTO"]
    dto["sleepWindowConfirmationType"] = "invented_type"
    dto["sleepScores"]["overall"]["value"] = 90
    dto["avgSleepStress"] = 20
    status = training_status_document(
        day, statuses={"7": status_entry(day, calendarDate=None)}
    )
    lacking = (DayFamily.HRV, DayFamily.DAILY_SUMMARY)
    write_day(
        root,
        day,
        export=EXPORT_B,
        families=[family for family in DayFamily if family not in lacking],
        heart_rate=heart_rate,
        stress=stress,
        sleep=sleep,
        training_status=status,
    )


def test_every_count_of_the_report_adds_up_over_two_days(tmp_path: Path) -> None:
    """Les mêmes cas deux jours de suite : chaque compte du rapport vaut 2, un par
    jour ; le résumé somme les jours de toutes les révisions."""
    for day in (DAY, D1):
        _counted_lender(tmp_path, day)
        _counted_reference(tmp_path, day)
    ingestion = build(tmp_path, EXPORT_A, EXPORT_B)
    report = ingestion.report
    assert report.reference_days == (ExportDayCount(EXPORT_B, 2),)
    assert report.window_families == (FamilyDayCount(DayFamily.HEART_RATE, 2),)
    assert report.window_mismatches == (FamilyDayCount(DayFamily.STRESS, 2),)
    assert report.borrowings == tuple(
        BorrowingCount(DayFamily.DAILY_SUMMARY, piece, 2)
        for piece in ("activity_totals", "body_battery", "stress", "wellness_data")
    )
    assert report.borrowing_refusals == (
        BorrowingRefusalCount(DayFamily.HRV, "hrv", BorrowingRefusal.NIGHT_WINDOW, 2),
    )
    assert report.unknown_codes == (
        CodeCount(DayFamily.STRESS, "stressValuesArray[*][1]", "-3", 2),
    )
    assert report.unknown_confirmations == (
        CodeCount(
            DayFamily.SLEEP,
            "dailySleepDTO.sleepWindowConfirmationType",
            "invented_type",
            2,
        ),
    )
    assert report.refused_blocks == (BlockCount(TrainingStatusKind.STATUS, 2),)
    assert report.copy_disagreements == (
        CopyDisagreementCount("resting_hr.resting_hr_bpm", DayFamily.HEART_RATE, 2),
    )
    found = {
        (count.family, count.field_path): (count.comparison, count.days)
        for count in report.comparisons
    }
    assert found[(DayFamily.SLEEP, SCORE)] == (ComparisonClass.REVISION, 2)
    assert found[(DayFamily.SLEEP, "dailySleepDTO.avgSleepStress")] == (
        ComparisonClass.REVISION,
        2,
    )
    revisions = [
        count
        for count in report.comparisons
        if count.comparison is ComparisonClass.REVISION
    ]
    assert all(count.days == 2 for count in revisions)
    assert ingestion.summary.revisions == 2 * len(revisions) > 2


def test_the_night_equality_without_rem_at_its_tolerance(tmp_path: Path) -> None:
    """Sans paradoxal détecté, il compte zéro : un total de 210 s au-dessus de la durée
    (la tolérance) n'est pas une infraction, 211 s l'est."""
    for light_s, violations in ((21810, 0), (21811, 1)):
        sleep = _sleep(
            deviceRemCapable=False, remSleepSeconds=None, lightSleepSeconds=light_s
        )
        write_day(tmp_path, sleep=sleep)
        assert build(tmp_path).report.night_equality_violations == violations


def _sleep_with_naps(day: date, *naps: tuple[datetime, datetime]) -> dict[str, Any]:
    """Le document de ``sleep`` de ``day``, ses siestes remplacées par ``naps``."""
    sleep: dict[str, Any] = _doc(DayFamily.SLEEP, day)
    dto = sleep["dailySleepDTO"]
    template = dto["dailyNapDTOS"][0]
    dto["dailyNapDTOS"] = [
        {
            **template,
            "napStartTimestampGMT": gmt_text(start, ""),
            "napEndTimestampGMT": gmt_text(end, ""),
        }
        for start, end in naps
    ]
    return sleep


def test_naps_that_touch_the_night_do_not_overlap_it(tmp_path: Path) -> None:
    """Une sieste finie à l'instant où la nuit commence, une autre commencée à
    l'instant où elle finit : aucune ne la recoupe."""
    half_hour = timedelta(minutes=30)
    sleep = _sleep_with_naps(
        DAY,
        (NIGHT_START - half_hour, NIGHT_START),
        (NIGHT_END, NIGHT_END + half_hour),
    )
    write_day(tmp_path, sleep=sleep)
    ingestion = build(tmp_path)
    assert len(record(ingestion).naps) == 2
    assert ingestion.report.naps_overlapping_night == 0


def test_a_night_with_a_missing_duration_still_counts_its_naps(tmp_path: Path) -> None:
    """Le profond manque : pas de contrôle de l'égalité, mais la sieste qui recoupe la
    nuit se compte."""
    sleep = _sleep_with_naps(DAY, (at(DAY, 6, 30), at(DAY, 7, 30)))
    sleep["dailySleepDTO"]["deepSleepSeconds"] = None
    write_day(tmp_path, sleep=sleep)
    report = build(tmp_path).report
    assert report.night_equality_violations == 0
    assert report.naps_overlapping_night == 1


def test_the_night_checks_add_up_over_two_days(tmp_path: Path) -> None:
    """Deux jours, chacun une nuit hors de l'égalité et une sieste qui la recoupe :
    deux de chaque."""
    for day in (DAY, D1):
        sleep = _sleep_with_naps(day, (at(day, 6, 30), at(day, 7, 30)))
        sleep["dailySleepDTO"]["awakeSleepSeconds"] = 1800 + 211
        write_day(tmp_path, day, sleep=sleep)
    report = build(tmp_path).report
    assert report.night_equality_violations == 2
    assert report.naps_overlapping_night == 2


def test_a_night_across_the_change_of_time_is_measured_in_real_time(
    tmp_path: Path,
) -> None:
    """La nuit du 25 mars 2001, de 23:00+01:00 à 07:00+02:00 : 7 h réelles, 8 h
    d'heures murales. Ses phases (8 h) ne redonnent pas sa durée, une infraction ; un
    point de FC 7 h 30 après son début est après sa fin, compté."""
    start = at(SPRING_DAY - timedelta(days=1), 23)
    end = at(SPRING_DAY, 7, offset=PLUS2)
    sleep: dict[str, Any] = _doc(DayFamily.SLEEP, SPRING_DAY)
    dto = sleep["dailySleepDTO"]
    dto["sleepEndTimestampGMT"] = ms(end)
    dto["sleepEndTimestampLocal"] = wall_ms(end)
    sleep["sleepHeartRate"] = [
        {"startGMT": ms(start), "value": 52},
        {"startGMT": ms(start + timedelta(hours=7, minutes=30)), "value": 48},
    ]
    write_day(
        tmp_path,
        SPRING_DAY,
        families=(DayFamily.DAILY_SUMMARY, DayFamily.SLEEP),
        sleep=sleep,
    )
    ingestion = build(tmp_path)
    night = record(ingestion, SPRING_DAY).night
    assert night is not None
    assert night.end - night.start == timedelta(hours=7)
    assert ingestion.report.night_equality_violations == 1
    assert (
        WindowEdgeCount(DayFamily.SLEEP, "sleepHeartRate", 1, 0)
        in ingestion.report.window_edges
    )


def test_readiness_copies_that_differ_add_up(tmp_path: Path) -> None:
    """Deux entrées qui recopient un score de sommeil (70 contre 80) et une HRV
    hebdomadaire (40 contre 48) qui diffèrent : deux copies, deux qui diffèrent."""
    evening = at(DAY, 18)
    readiness = [
        readiness_entry(DAY, sleepScore=70, hrvWeeklyAverage=40),
        readiness_entry(
            DAY,
            sleepScore=70,
            hrvWeeklyAverage=40,
            timestamp=gmt_text(evening),
            timestampLocal=local_text(evening),
        ),
    ]
    write_day(tmp_path, training_readiness=readiness)
    prior = build(tmp_path).report.readiness_prior_copies
    assert ReadinessCopyCount("hrv.weekly_avg_ms", 2, 2) in prior
    assert ReadinessCopyCount("night.sleep_score", 2, 2) in prior


def test_an_absent_day_series_does_not_stop_the_edges(tmp_path: Path) -> None:
    """Pas de série de FC (la première des séries du jour) ; un point de stress une
    minute avant la fenêtre : compté."""
    heart_rate = _doc(DayFamily.HEART_RATE)
    heart_rate["heartRateValues"] = []
    stress = _doc(DayFamily.STRESS)
    stress["stressValuesArray"] = [[ms(START - timedelta(minutes=1)), 20]]
    write_day(
        tmp_path,
        families=(DayFamily.DAILY_SUMMARY, DayFamily.HEART_RATE, DayFamily.STRESS),
        heart_rate=heart_rate,
        stress=stress,
    )
    assert build(tmp_path).report.window_edges == (
        WindowEdgeCount(DayFamily.STRESS, "stressValuesArray", 1, 0),
    )


def test_a_point_half_a_second_after_the_day_is_outside(tmp_path: Path) -> None:
    heart_rate = _doc(DayFamily.HEART_RATE)
    heart_rate["heartRateValues"] = [[ms(START), 55], [ms(START) + 86400500, 60]]
    write_day(
        tmp_path,
        families=(DayFamily.DAILY_SUMMARY, DayFamily.HEART_RATE),
        heart_rate=heart_rate,
    )
    assert build(tmp_path).report.window_edges == (
        WindowEdgeCount(DayFamily.HEART_RATE, "heartRateValues", 1, 0),
    )


def test_the_edges_of_a_truncated_day_are_its_24_hours(tmp_path: Path) -> None:
    """Un jour tronqué à midi : un point de FC à 18 h est dans les 24 h de la fenêtre,
    pas compté (la borne n'est pas la fin des données)."""
    heart_rate = _doc(DayFamily.HEART_RATE)
    heart_rate["heartRateValues"] = [[ms(START), 55], [ms(at(DAY, 18)), 60]]
    write_day(
        tmp_path,
        families=(DayFamily.DAILY_SUMMARY, DayFamily.HEART_RATE),
        daily_summary=_summary(wellnessEndTimeGmt=gmt_text(NOON)),
        heart_rate=heart_rate,
    )
    ingestion = build(tmp_path)
    assert record(ingestion).state is DayState.TRUNCATED
    assert ingestion.report.window_edges == ()


def _night_battery(day: date, points: list[datetime]) -> dict[str, Any]:
    """Le document de ``sleep`` de ``day`` sans FC de la nuit, sa série de Body Battery
    aux instants ``points``."""
    sleep: dict[str, Any] = _doc(DayFamily.SLEEP, day)
    sleep["sleepHeartRate"] = []
    sleep["sleepBodyBattery"] = [
        {"startGMT": ms(point), "value": 50} for point in points
    ]
    return sleep


def test_the_edges_of_the_night_over_three_days(tmp_path: Path) -> None:
    """La FC de la nuit absente (la première série) ; la série de Body Battery : le
    10, des points une minute avant la nuit, à son début, à sa fin, une minute après,
    et à 23 h 30 (dans la nuit du 11) ; le 11, ce point partagé et un à 23 h 30 (dans
    la nuit du 12) ; le 12, ce dernier. Hors de leur nuit : 3 + 1 ; partagés avec la
    nuit de la veille : 1 + 1."""
    minute = timedelta(minutes=1)
    late = at(DAY, 23, 30)
    later = at(D1, 23, 30)
    days = {
        DAY: [NIGHT_START - minute, NIGHT_START, NIGHT_END, NIGHT_END + minute, late],
        D1: [late, later],
        D2: [later],
    }
    for day, points in days.items():
        write_day(
            tmp_path,
            day,
            families=(DayFamily.DAILY_SUMMARY, DayFamily.SLEEP),
            sleep=_night_battery(day, points),
        )
    assert build(tmp_path).report.window_edges == (
        WindowEdgeCount(DayFamily.SLEEP, "sleepBodyBattery", 4, 2),
    )


def test_refused_files_are_listed_by_name(tmp_path: Path) -> None:
    """``sleep`` se lit avant ``hrv`` (l'ordre des familles) ; le rapport les range par
    nom."""
    write_document(tmp_path, DayFamily.SLEEP, b"pas du json")
    write_document(tmp_path, DayFamily.HRV, b"pas du json")
    refused = build(tmp_path).report.refused
    assert [item.name for item in refused] == [
        f"garmin/{EXPORT_A}/hrv/{DAY.isoformat()}.json",
        f"garmin/{EXPORT_A}/sleep/{DAY.isoformat()}.json",
    ]


def test_body_battery_is_never_borrowed(tmp_path: Path) -> None:
    """La référence B n'a pas ``body_battery`` ; A le porte (chargé : 61) : il ne
    s'emprunte pas ; sa feuille est à part, et ses copies ne se contrôlent pas."""
    lender = _doc(DayFamily.BODY_BATTERY)
    lender[0]["charged"] = 61
    write_day(tmp_path, export=EXPORT_A, body_battery=lender)
    write_day(tmp_path, export=EXPORT_B, families=_without(DayFamily.BODY_BATTERY))
    ingestion = build(tmp_path, EXPORT_A, EXPORT_B)
    assert record(ingestion).reference_export == EXPORT_B
    assert _kinds(ingestion, DayFamily.BODY_BATTERY) == {
        "[*]": ComparisonClass.SET_APART
    }
    assert ingestion.report.borrowings == ()
    assert ingestion.report.copy_disagreements == ()


def test_a_borrowed_family_is_a_borrowing_even_on_a_degraded_day(
    tmp_path: Path,
) -> None:
    """A, ancien, complet avec son détail, sans ``training_readiness`` ; B, récent,
    complet sans son détail, la porte : A est la référence, la famille vient de B, et
    sa feuille est un emprunt, pas une dégradation."""
    write_day(
        tmp_path, export=EXPORT_A, families=_without(DayFamily.TRAINING_READINESS)
    )
    write_day(
        tmp_path,
        export=EXPORT_B,
        families=(DayFamily.DAILY_SUMMARY, DayFamily.TRAINING_READINESS),
    )
    ingestion = build(tmp_path, EXPORT_A, EXPORT_B)
    assert record(ingestion).reference_export == EXPORT_A
    assert ingestion.report.borrowings == (
        BorrowingCount(DayFamily.TRAINING_READINESS, "readiness", 1),
    )
    assert _kinds(ingestion, DayFamily.TRAINING_READINESS) == {
        "[*]": ComparisonClass.BORROWING
    }


def test_the_lender_of_a_series_alone_counts_no_discard(tmp_path: Path) -> None:
    """La série de FC manque à la référence B et vient seule de A, dont la lecture
    écarte un point nul : l'écart n'est pas compté (A n'est pas retenu)."""
    write_day(tmp_path, export=EXPORT_A)
    own = _doc(DayFamily.HEART_RATE)
    own["heartRateValues"] = []
    write_day(tmp_path, export=EXPORT_B, heart_rate=own)
    ingestion = build(tmp_path, EXPORT_A, EXPORT_B)
    assert record(ingestion).series.heart_rate is not None
    assert ingestion.report.borrowings == (
        BorrowingCount(DayFamily.HEART_RATE, "series.heart_rate", 1),
    )
    assert ingestion.report.point_discards == ()


def test_the_reference_days_are_listed_by_name(tmp_path: Path) -> None:
    """``garmin_z``, acquis avant ``garmin_y``, est la référence d'un jour, et
    ``garmin_y`` d'un autre : les comptes vont par nom, pas par instant."""
    write_day(tmp_path, DAY, export="garmin_z")
    write_day(tmp_path, D1, export="garmin_y")
    ingestion = build_days(
        [
            load_export_days(export_dir(tmp_path, name), name, RETRIEVED[instant])
            for name, instant in (("garmin_z", EXPORT_A), ("garmin_y", EXPORT_B))
        ]
    )
    expected = (ExportDayCount("garmin_y", 1), ExportDayCount("garmin_z", 1))
    assert ingestion.report.reference_days == expected
    assert ingestion.summary.reference_days == expected


def test_device_ranks_follow_the_families_even_borrowed(tmp_path: Path) -> None:
    """Le 10, ``sleep`` (l'appareil 8) vient entier de A, ``training_readiness``
    (l'appareil 7) de la référence B : rangs dans l'ordre des familles, 8 puis 7 ; le
    11, l'appareil 7 seul garde son rang, 2."""
    write_day(
        tmp_path,
        export=EXPORT_A,
        families=(DayFamily.SLEEP,),
        sleep=_sleep_devices(DAY, 8, 8),
    )
    write_day(
        tmp_path,
        export=EXPORT_B,
        families=(
            DayFamily.DAILY_SUMMARY,
            DayFamily.HEART_RATE,
            DayFamily.TRAINING_READINESS,
        ),
    )
    write_day(
        tmp_path,
        D1,
        export=EXPORT_B,
        families=(DayFamily.DAILY_SUMMARY, DayFamily.TRAINING_READINESS),
    )
    ingestion = build(tmp_path, EXPORT_A, EXPORT_B)
    assert record(ingestion).reference_export == EXPORT_B
    assert record(ingestion).night is not None
    assert record(ingestion, DAY).device_ranks == (1, 2)
    assert record(ingestion, D1).device_ranks == (2,)


# --- la relecture bornée et le second balayage --------------------------------------


def _shifted(document: dict[str, Any]) -> dict[str, Any]:
    """Le document de ``sleep``, sa nuit commencée une seconde plus tard."""
    dto = document["dailySleepDTO"]
    dto["sleepStartTimestampGMT"] += 1000
    dto["sleepStartTimestampLocal"] += 1000
    return document


def _whole_sleep_case(root: Path, case: str) -> Any:
    """C, la référence, n'a pas ``sleep`` ; B, le plus récent des deux autres, la prête
    entière sans segments ; A porte des segments qui s'accordent (``agree``), d'une nuit
    une seconde plus tard (``window``), qui ne redonnent pas la durée du paradoxal
    (``durations``), ou n'en porte pas (``none``)."""
    third = _doc(DayFamily.SLEEP)
    third["sleepLevels"] = [] if case == "none" else _levels(_FULL_PLAN)
    if case == "window":
        _shifted(third)
    elif case == "durations":
        third["sleepLevels"] = _levels(_REM_30)
    lender = _doc(DayFamily.SLEEP)
    lender["sleepLevels"] = []
    write_day(root, export=EXPORT_A, sleep=third)
    write_day(root, export=EXPORT_B, sleep=lender)
    write_day(root, export=EXPORT_C, families=_without(DayFamily.SLEEP))
    return build(root, EXPORT_A, EXPORT_B, EXPORT_C)


_WHOLE_BORROWINGS = (
    BorrowingCount(DayFamily.SLEEP, "naps", 1),
    BorrowingCount(DayFamily.SLEEP, "night", 1),
)


def test_the_segments_of_a_whole_borrowed_night_come_from_a_third_export(
    tmp_path: Path,
) -> None:
    """La nuit vient entière de B, sans segments ; ceux de A, à la même nuit et aux
    durées du résumé : les segments viennent de A, un emprunt ``night.segments``."""
    ingestion = _whole_sleep_case(tmp_path, "agree")
    day = record(ingestion)
    assert day.reference_export == EXPORT_C
    assert day.night is not None
    assert day.night.source.retrieved_at == RETRIEVED[EXPORT_B]
    assert day.night.segments == (
        SleepSegment(0.0, 3600.0, SleepStage.DEEP),
        SleepSegment(3600.0, 19800.0, SleepStage.LIGHT),
        SleepSegment(19800.0, 25200.0, SleepStage.REM),
        SleepSegment(25200.0, 27000.0, SleepStage.AWAKE),
        SleepSegment(27000.0, 28800.0, SleepStage.UNMEASURABLE),
    )
    assert ingestion.report.borrowings == (
        *_WHOLE_BORROWINGS,
        BorrowingCount(DayFamily.SLEEP, "night.segments", 1),
    )
    assert ingestion.report.borrowing_refusals == ()


@pytest.mark.parametrize(
    ("case", "reason"),
    [
        ("window", BorrowingRefusal.NIGHT_WINDOW),
        ("durations", BorrowingRefusal.NIGHT_DURATIONS),
        ("none", None),
    ],
)
def test_the_segments_of_a_whole_borrowed_night_need_their_agreements(
    tmp_path: Path, case: str, reason: BorrowingRefusal | None
) -> None:
    """Le même, les segments de A d'une nuit une seconde plus tard (refus
    ``night_window``), qui ne redonnent pas la durée du paradoxal du résumé (refus
    ``night_durations``), ou absents (ni emprunt ni refus) : aucun segment."""
    ingestion = _whole_sleep_case(tmp_path, case)
    day = record(ingestion)
    assert day.night is not None
    assert day.night.segments == ()
    assert ingestion.report.borrowings == _WHOLE_BORROWINGS
    assert ingestion.report.borrowing_refusals == (
        ()
        if reason is None
        else (BorrowingRefusalCount(DayFamily.SLEEP, "night.segments", reason, 1),)
    )


def _only_the_most_recent_lender(root: Path, piece: str) -> Any:
    """C, la référence, n'a pas ``piece`` ; B, le plus récent des deux autres, la porte
    à une fenêtre en désaccord (la fenêtre du jour une heure plus tard, la nuit une
    seconde plus tard) ; A, le plus ancien, à une fenêtre qui s'accorde."""
    if piece == "series.body_battery":
        reference = _doc(DayFamily.STRESS)
        reference["bodyBatteryValuesArray"] = []
        write_day(root, export=EXPORT_A)
        write_day(
            root, export=EXPORT_B, stress=DOCUMENTS[DayFamily.STRESS](DAY, at(DAY, 1))
        )
        write_day(root, export=EXPORT_C, stress=reference)
    else:
        reference = _doc(DayFamily.SLEEP)
        older = _doc(DayFamily.SLEEP)
        newer = _shifted(_doc(DayFamily.SLEEP))
        if piece == "night.segments":
            reference["sleepLevels"] = []
            older["sleepLevels"] = _levels(_FULL_PLAN)
            newer["sleepLevels"] = _levels(_FULL_PLAN)
        else:
            reference["sleepRestlessMoments"] = []
        write_day(root, export=EXPORT_A, sleep=older)
        write_day(root, export=EXPORT_B, sleep=newer)
        write_day(root, export=EXPORT_C, sleep=reference)
    return build(root, EXPORT_A, EXPORT_B, EXPORT_C)


@pytest.mark.parametrize(
    ("piece", "family", "reason"),
    [
        ("series.body_battery", DayFamily.STRESS, BorrowingRefusal.DAY_WINDOW),
        (
            "night.series.restless_moments",
            DayFamily.SLEEP,
            BorrowingRefusal.NIGHT_WINDOW,
        ),
        ("night.segments", DayFamily.SLEEP, BorrowingRefusal.NIGHT_WINDOW),
    ],
)
def test_a_piece_refused_by_the_most_recent_lender_is_not_asked_of_the_next(
    tmp_path: Path, piece: str, family: DayFamily, reason: BorrowingRefusal
) -> None:
    """Une série du jour, une série de la nuit, les segments : du plus récent des
    autres exports qui la porte, et de lui seul. B la refuse par sa fenêtre ; A, qui
    s'accorde, n'est pas essayé : rien n'est pris, un refus, aucun emprunt."""
    ingestion = _only_the_most_recent_lender(tmp_path, piece)
    day = record(ingestion)
    assert day.reference_export == EXPORT_C
    assert day.night is not None
    if piece == "series.body_battery":
        assert day.series.body_battery is None
    elif piece == "night.segments":
        assert day.night.segments == ()
    else:
        assert day.night.series.restless_moments is None
    assert ingestion.report.borrowings == ()
    assert ingestion.report.borrowing_refusals == (
        BorrowingRefusalCount(family, piece, reason, 1),
    )
