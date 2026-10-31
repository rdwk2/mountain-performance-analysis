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

from fixtures.day_exports import build, load, record, write_day, write_document
from fixtures.days import (
    DAY,
    EXPORT_A,
    EXPORT_B,
    EXPORT_C,
    PLUS2,
    RETRIEVED,
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
)
from mountain_perf.ingest.days import build_days
from mountain_perf.schemas import (
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
    FamilyDayCount,
    PointDiscard,
    PointDiscardCount,
    ReadinessCopyCount,
    SourceRef,
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
