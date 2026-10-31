"""Les blocs de Training Status de l'ingestion des jours (``build_days``, AN2-1) : le
choix de l'export puis du fichier, les écarts d'un même bloc dans un export et entre
exports, l'instant propre, les blocs refusés. Sans extra."""

from __future__ import annotations

import dataclasses
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

from fixtures.day_exports import build, write_day, write_document
from fixtures.days import (
    AUTUMN_DAY,
    DAY,
    EXPORT_A,
    EXPORT_B,
    PLUS1,
    PLUS2,
    SPRING_DAY,
    midnight,
)
from fixtures.families import (
    DOCUMENTS,
    acclimation_entry,
    balance_entry,
    status_entry,
    training_status_document,
    vo2_max_entry,
)
from mountain_perf.ingest.days import BLOCK_FIELDS
from mountain_perf.schemas import (
    AltitudeAcclimationBlock,
    BlockCount,
    BlockFieldCount,
    DayFamily,
    DayState,
    HeatAcclimationBlock,
    LoadBalanceBlock,
    TrainingStatusBlock,
    TrainingStatusKind,
    Vo2MaxBlock,
)

BEFORE = DAY - timedelta(days=1)
D1 = DAY + timedelta(days=1)
PRECISE = "vo2MaxPreciseValue"
"""Le chemin de la VO2max précise dans son bloc."""


def _document(
    day: date,
    *,
    statuses: dict[str, Any] | None = None,
    balances: dict[str, Any] | None = None,
    vo2: dict[str, Any] | None = None,
    acclimation: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Un document de Training Status qui ne porte que les blocs donnés."""
    document = training_status_document(
        day, statuses=statuses or {}, balances=balances or {}
    )
    document["mostRecentVO2Max"]["generic"] = vo2
    document["mostRecentVO2Max"]["heatAltitudeAcclimation"] = acclimation
    return document


def _vo2(
    root: Path, file_day: date, block_day: date, value: float, export: str = EXPORT_A
) -> None:
    """Le fichier de Training Status de ``file_day`` qui porte la seule VO2max de
    ``block_day``."""
    document = _document(
        file_day, vo2=vo2_max_entry(block_day, vo2MaxPreciseValue=value)
    )
    write_document(root, DayFamily.TRAINING_STATUS, document, file_day, export)


def _window_day(
    root: Path,
    day: date,
    start: datetime | None = None,
    end: datetime | None = None,
    export: str = EXPORT_A,
) -> None:
    """Le jour ``day`` de l'export, avec sa seule fenêtre du jour
    (``daily_summary``)."""
    document = DOCUMENTS[DayFamily.DAILY_SUMMARY](day, start, end)
    write_document(root, DayFamily.DAILY_SUMMARY, document, day, export)


def _only(blocks: tuple[Any, ...]) -> Any:
    assert len(blocks) == 1
    return blocks[0]


def test_a_block_dated_before_its_file(tmp_path: Path) -> None:
    """La VO2max du fichier de DAY est datée de la veille : elle va à sa date propre,
    avec le jour de son fichier ; la veille n'a pas de document, son instant propre est
    le début de la fenêtre de son lendemain, DAY (ici aussi le jour du fichier)."""
    _window_day(tmp_path, DAY)
    _vo2(tmp_path, DAY, BEFORE, 55.5)
    ingestion = build(tmp_path)
    block = _only(ingestion.history.vo2_max)
    assert (block.day, block.file_day) == (BEFORE, DAY)
    assert block.proper_instant == midnight(DAY)
    assert [item.day for item in ingestion.records] == [DAY]


def test_an_acclimation_block_with_two_dates(tmp_path: Path) -> None:
    """La chaleur et l'altitude d'un même bloc de la source, à deux dates propres : deux
    sous-blocs, chacun dans sa suite, à sa date."""
    _window_day(tmp_path, DAY)
    document = _document(DAY, acclimation=acclimation_entry(DAY))
    write_document(tmp_path, DayFamily.TRAINING_STATUS, document)
    history = build(tmp_path).history
    heat = _only(history.heat_acclimation)
    altitude = _only(history.altitude_acclimation)
    assert (heat.day, heat.file_day) == (DAY - timedelta(days=2), DAY)
    assert (altitude.day, altitude.file_day) == (DAY - timedelta(days=3), DAY)
    assert heat.proper_instant == midnight(DAY - timedelta(days=1))
    assert altitude.proper_instant == midnight(DAY - timedelta(days=2))
    assert heat.heat_acclimation_percent == 20
    assert altitude.acclimation_altitude_m == 1500


def test_a_block_in_its_own_file_and_in_a_later_one(tmp_path: Path) -> None:
    """Deux fichiers d'un export portent le bloc de DAY : celui de DAY est gardé, la
    différence est comptée."""
    write_document(
        tmp_path,
        DayFamily.TRAINING_STATUS,
        _document(DAY, statuses={"7": status_entry(DAY)}),
    )
    later = status_entry(DAY)
    later["acuteTrainingLoadDTO"]["dailyTrainingLoadAcute"] = 310
    write_document(
        tmp_path,
        DayFamily.TRAINING_STATUS,
        _document(D1, statuses={"7": later}),
        D1,
    )
    ingestion = build(tmp_path)
    block = _only(ingestion.history.statuses)
    assert (block.day, block.file_day, block.acute_load) == (DAY, DAY, 300)
    assert ingestion.report.block_differences_in_export == (
        BlockFieldCount(
            TrainingStatusKind.STATUS, "acuteTrainingLoadDTO.dailyTrainingLoadAcute", 1
        ),
    )
    assert ingestion.report.block_differences_between_exports == ()


def test_a_block_in_its_own_file_and_in_an_earlier_one(tmp_path: Path) -> None:
    """Le bloc de DAY porté, dans un même export, par le fichier de la veille (55.5) et
    par celui de DAY (56.5) : la valeur gardée est celle du fichier de DAY, pas du plus
    ancien ; la différence est comptée dans l'export."""
    _vo2(tmp_path, BEFORE, DAY, 55.5)
    _vo2(tmp_path, DAY, DAY, 56.5)
    ingestion = build(tmp_path)
    block = _only(ingestion.history.vo2_max)
    assert (block.file_day, block.vo2_max_precise_ml_kg_min) == (DAY, 56.5)
    assert ingestion.report.block_differences_in_export == (
        BlockFieldCount(TrainingStatusKind.VO2_MAX, PRECISE, 1),
    )


def test_between_exports_each_export_gives_the_block_of_the_same_rule(
    tmp_path: Path,
) -> None:
    """Entre exports, le bloc retenu se compare au bloc que la même règle prend dans
    chaque autre export, pas à son plus ancien fichier. A (ancien) : le bloc de DAY
    porté par le fichier de la veille (55.5) et par celui de DAY (56.5) ; B (récent,
    référence) : le fichier de DAY seul (56.5). A donne son fichier de DAY : aucun écart
    entre exports ; l'écart de A reste compté dans l'export."""
    _vo2(tmp_path, BEFORE, DAY, 55.5, EXPORT_A)
    _vo2(tmp_path, DAY, DAY, 56.5, EXPORT_A)
    _vo2(tmp_path, DAY, DAY, 56.5, EXPORT_B)
    ingestion = build(tmp_path, EXPORT_A, EXPORT_B)
    block = _only(ingestion.history.vo2_max)
    assert block.vo2_max_precise_ml_kg_min == 56.5
    assert block.source.retrieved_at == datetime(2001, 12, 2, 11, tzinfo=UTC)
    assert ingestion.report.block_differences_between_exports == ()
    assert ingestion.report.block_differences_in_export == (
        BlockFieldCount(TrainingStatusKind.VO2_MAX, PRECISE, 1),
    )


def test_the_proper_instant_follows_the_chosen_file_only(tmp_path: Path) -> None:
    """Le bloc de DAY porté par le fichier de la veille (jour avec fenêtre) et par
    celui de DAY, dont le jour n'a pas de fenêtre (Training Status seul) : le fichier de
    DAY est choisi ; sans fenêtre de DAY, ni de son lendemain (pas de document), ni du
    jour du fichier choisi, le bloc n'a pas d'instant propre (la fenêtre de la veille ne
    sert pas) ; il reste, compté."""
    _window_day(tmp_path, BEFORE)
    _vo2(tmp_path, BEFORE, DAY, 56.5)
    _vo2(tmp_path, DAY, DAY, 56.5)
    ingestion = build(tmp_path)
    block = _only(ingestion.history.vo2_max)
    assert block.file_day == DAY
    assert block.proper_instant is None
    assert ingestion.report.blocks_without_proper_instant == (
        BlockCount(TrainingStatusKind.VO2_MAX, 1),
    )


def test_a_block_without_its_own_file_comes_from_the_oldest(tmp_path: Path) -> None:
    """Le bloc de la veille, porté par DAY et D1 : le plus ancien des deux, sans écart
    s'ils s'accordent."""
    _vo2(tmp_path, D1, BEFORE, 55.5)
    _vo2(tmp_path, DAY, BEFORE, 55.5)
    ingestion = build(tmp_path)
    block = _only(ingestion.history.vo2_max)
    assert (block.day, block.file_day) == (BEFORE, DAY)
    assert ingestion.report.block_differences_in_export == ()


def test_two_exports_carry_the_block_the_reference_of_its_day(tmp_path: Path) -> None:
    """Le bloc de DAY dans deux exports : celui de l'export de référence de DAY ;
    l'écart entre exports compté par sorte et champ."""
    _vo2(tmp_path, DAY, DAY, 55.5, EXPORT_A)
    _vo2(tmp_path, DAY, DAY, 56.5, EXPORT_B)
    ingestion = build(tmp_path, EXPORT_A, EXPORT_B)
    assert ingestion.records[0].reference_export == EXPORT_B
    assert _only(ingestion.history.vo2_max).vo2_max_precise_ml_kg_min == 56.5
    assert ingestion.report.block_differences_between_exports == (
        BlockFieldCount(TrainingStatusKind.VO2_MAX, PRECISE, 1),
    )
    assert ingestion.report.block_differences_in_export == ()


def test_the_same_disagreement_in_two_exports_counts_one_block(tmp_path: Path) -> None:
    """A et B portent les mêmes fichiers : le bloc de DAY dans le fichier de la veille
    (55.5) et dans celui de DAY (56.5). Le désaccord d'un même bloc se compte une fois
    par champ, quel que soit le nombre d'exports où il se voit : 1, pas 2 ; entre
    exports, les deux blocs retenus s'accordent."""
    for export in (EXPORT_A, EXPORT_B):
        _vo2(tmp_path, BEFORE, DAY, 55.5, export)
        _vo2(tmp_path, DAY, DAY, 56.5, export)
    ingestion = build(tmp_path, EXPORT_A, EXPORT_B)
    assert ingestion.report.block_differences_in_export == (
        BlockFieldCount(TrainingStatusKind.VO2_MAX, PRECISE, 1),
    )
    assert ingestion.report.block_differences_between_exports == ()


def test_the_reference_of_the_day_even_if_older(tmp_path: Path) -> None:
    """L'export de référence de DAY est l'ancien (il a le détail) : son bloc, pas celui
    du plus récent."""
    families = [item for item in DayFamily if item is not DayFamily.TRAINING_STATUS]
    write_day(tmp_path, export=EXPORT_A, families=families)
    _vo2(tmp_path, DAY, DAY, 55.5, EXPORT_A)
    _window_day(tmp_path, DAY, export=EXPORT_B)
    _vo2(tmp_path, DAY, DAY, 56.5, EXPORT_B)
    ingestion = build(tmp_path, EXPORT_A, EXPORT_B)
    assert ingestion.records[0].reference_export == EXPORT_A
    assert _only(ingestion.history.vo2_max).vo2_max_precise_ml_kg_min == 55.5


def test_a_block_whose_day_has_no_reference(tmp_path: Path) -> None:
    """La VO2max de la veille (aucun fichier à sa date) : du plus récent des exports qui
    la portent."""
    _vo2(tmp_path, DAY, BEFORE, 55.5, EXPORT_A)
    _vo2(tmp_path, DAY, BEFORE, 57.5, EXPORT_B)
    ingestion = build(tmp_path, EXPORT_A, EXPORT_B)
    block = _only(ingestion.history.vo2_max)
    assert block.day == BEFORE
    assert block.vo2_max_precise_ml_kg_min == 57.5


def test_the_proper_instant_of_a_status_is_its_timestamp(tmp_path: Path) -> None:
    _window_day(tmp_path, DAY)
    document = _document(DAY, statuses={"7": status_entry(DAY)})
    write_document(tmp_path, DayFamily.TRAINING_STATUS, document)
    block = _only(build(tmp_path).history.statuses)
    noon = datetime(2001, 3, 10, 12, tzinfo=PLUS1)
    assert block.timestamp == noon
    assert block.proper_instant == noon


def test_the_proper_instant_is_the_end_of_the_window_even_truncated(
    tmp_path: Path,
) -> None:
    """Un bloc sans horodatage daté d'un jour tronqué : début + 24 h (le plus tard de
    début + 24 h et de ``fin_donnees``), pas ``fin_donnees``."""
    _window_day(tmp_path, DAY, end=datetime(2001, 3, 10, 12, tzinfo=PLUS1))
    document = _document(DAY, statuses={"7": status_entry(DAY, timestamp=None)})
    write_document(tmp_path, DayFamily.TRAINING_STATUS, document)
    ingestion = build(tmp_path)
    assert ingestion.records[0].state is DayState.TRUNCATED
    assert _only(ingestion.history.statuses).proper_instant == midnight(D1)


def test_the_proper_instant_without_a_window_of_its_day(tmp_path: Path) -> None:
    """Sans fenêtre de son jour (le 24 mars) ni de son lendemain (le 25, sans
    document), la règle de repli : le minuit local qui suit sa date, au décalage de la
    fenêtre du jour du fichier choisi (le 26, après le changement d'heure, +02:00). Elle
    est ici une heure trop tôt : 00:00+02:00 le 25 mars, quand le vrai minuit local qui
    suit le 24 est 00:00+01:00."""
    after = SPRING_DAY + timedelta(days=1)
    _window_day(tmp_path, after, midnight(after, PLUS2))
    _vo2(tmp_path, after, SPRING_DAY - timedelta(days=1), 55.5)
    block = _only(build(tmp_path).history.vo2_max)
    assert block.proper_instant == midnight(SPRING_DAY, PLUS2)
    assert block.proper_instant.utcoffset() == timedelta(hours=2)
    assert block.proper_instant == midnight(SPRING_DAY, PLUS1) - timedelta(hours=1)


def test_the_proper_instant_without_a_window_of_its_day_is_the_next_start(
    tmp_path: Path,
) -> None:
    """La VO2max datée du 24 mars, sans document de ce jour ; le 25 mars (le dimanche du
    passage à l'heure d'été) a sa fenêtre, à +01:00, et ne porte pas le bloc ; le
    fichier choisi est celui du 26 mars, à +02:00, de l'autre côté du changement
    d'heure. L'instant propre est le début de la fenêtre du 25 mars (00:00+01:00), pas
    le minuit qui suit le 24 au décalage du fichier choisi (00:00+02:00 le 25, une heure
    trop tôt)."""
    after = SPRING_DAY + timedelta(days=1)
    _window_day(tmp_path, SPRING_DAY)
    _window_day(tmp_path, after, midnight(after, PLUS2))
    _vo2(tmp_path, after, SPRING_DAY - timedelta(days=1), 55.5)
    block = _only(build(tmp_path).history.vo2_max)
    assert block.proper_instant == midnight(SPRING_DAY, PLUS1)
    assert block.proper_instant.utcoffset() == timedelta(hours=1)


def test_the_proper_instant_with_an_empty_next_day_falls_back(tmp_path: Path) -> None:
    """La VO2max datée du 24 mars, sans document de ce jour ; le 25 mars a un document
    ``empty`` (un fichier ``hrv`` vide : le document existe, sans fenêtre) ; le fichier
    choisi est celui du 26 mars, à +02:00. La règle de repli, le minuit qui suit le 24
    au décalage du fichier choisi (00:00+02:00 le 25), pas « aucun instant propre » : un
    lendemain ``empty`` n'a pas de fenêtre à prêter."""
    after = SPRING_DAY + timedelta(days=1)
    write_document(tmp_path, DayFamily.HRV, b"{}", SPRING_DAY)
    _window_day(tmp_path, after, midnight(after, PLUS2))
    _vo2(tmp_path, after, SPRING_DAY - timedelta(days=1), 55.5)
    ingestion = build(tmp_path)
    assert ingestion.records[0].day == SPRING_DAY
    assert ingestion.records[0].state is DayState.EMPTY
    block = _only(ingestion.history.vo2_max)
    assert block.proper_instant == midnight(SPRING_DAY, PLUS2)
    assert block.proper_instant.utcoffset() == timedelta(hours=2)


def _autumn_status(root: Path) -> None:
    document = _document(
        AUTUMN_DAY,
        statuses={"7": status_entry(AUTUMN_DAY, timestamp=None)},
        balances={"7": balance_entry(AUTUMN_DAY)},
    )
    write_document(root, DayFamily.TRAINING_STATUS, document, AUTUMN_DAY)


def test_the_proper_instant_of_a_complete_25_hour_day_is_its_true_end(
    tmp_path: Path,
) -> None:
    """Le dimanche du passage à l'heure d'hiver, sa fenêtre à +02:00 et ses données
    jusqu'au lundi 00:00+01:00 (25 h, ``complete``), sans document du lundi ; son
    équilibre de la charge et son statut sans horodatage. Leur instant propre est la
    vraie fin du jour, le minuit local du lundi, pas début + 24 h (une heure plus
    tôt)."""
    monday = AUTUMN_DAY + timedelta(days=1)
    _window_day(tmp_path, AUTUMN_DAY, midnight(AUTUMN_DAY, PLUS2), midnight(monday))
    _autumn_status(tmp_path)
    ingestion = build(tmp_path)
    day = ingestion.records[0]
    assert day.state is DayState.COMPLETE
    assert day.data_end == midnight(monday)
    assert day.window_start is not None
    assert day.data_end - day.window_start == timedelta(hours=25)
    history = ingestion.history
    assert _only(history.statuses).proper_instant == midnight(monday)
    assert _only(history.load_balances).proper_instant == midnight(monday)


def test_the_proper_instant_of_a_day_ignores_a_later_next_window(
    tmp_path: Path,
) -> None:
    """Le dimanche du passage à l'heure d'hiver tel que Garmin l'écrit, une fenêtre de
    24 h à +02:00 (fin des données au lundi 00:00+02:00), suivi du lundi, dont la
    fenêtre commence à 00:00+01:00, une heure après début + 24 h. L'instant propre de
    l'équilibre de la charge du dimanche (sans horodatage) est début + 24 h, le plus
    tard de début + 24 h et de la fin des données ; le début du lundi n'y entre pas."""
    monday = AUTUMN_DAY + timedelta(days=1)
    _window_day(tmp_path, AUTUMN_DAY, midnight(AUTUMN_DAY, PLUS2))
    _window_day(tmp_path, monday)
    _autumn_status(tmp_path)
    block = _only(build(tmp_path).history.load_balances)
    assert block.proper_instant == midnight(monday, PLUS2)
    assert block.proper_instant == midnight(monday) - timedelta(hours=1)


def test_the_window_of_the_block_day_wins_over_the_file_day(tmp_path: Path) -> None:
    """Le jour du bloc a sa fenêtre (+01:00) : la fin de celle-ci (début + 24 h, le jour
    étant complet sur 24 h), pas le minuit qui suit au décalage du jour du fichier
    (+02:00, après le changement d'heure)."""
    block_day = SPRING_DAY - timedelta(days=1)
    after = SPRING_DAY + timedelta(days=1)
    _window_day(tmp_path, block_day)
    _window_day(tmp_path, after, midnight(after, PLUS2))
    _vo2(tmp_path, after, block_day, 55.5)
    block = _only(build(tmp_path).history.vo2_max)
    assert block.proper_instant == midnight(SPRING_DAY, PLUS1)
    assert block.proper_instant.utcoffset() == timedelta(hours=1)


def test_an_empty_day_has_no_window_for_its_blocks(tmp_path: Path) -> None:
    """Un jour ``empty`` (son document existe, sans fenêtre) : comme un jour sans
    document ; son instant propre est le début de la fenêtre de son lendemain, D1 (ici
    aussi le jour du fichier)."""
    write_document(tmp_path, DayFamily.HRV, b"{}", DAY)
    _window_day(tmp_path, D1)
    _vo2(tmp_path, D1, DAY, 55.5)
    ingestion = build(tmp_path)
    assert ingestion.records[0].state is DayState.EMPTY
    assert _only(ingestion.history.vo2_max).proper_instant == midnight(D1)


def test_a_block_without_proper_instant_is_kept_and_counted(tmp_path: Path) -> None:
    """Ni le jour du bloc, ni son lendemain, ni le jour du fichier n'ont de fenêtre :
    pas d'instant propre ; le bloc reste, compté."""
    _vo2(tmp_path, DAY, BEFORE, 55.5)
    ingestion = build(tmp_path)
    block = _only(ingestion.history.vo2_max)
    assert block.proper_instant is None
    assert ingestion.report.blocks_without_proper_instant == (
        BlockCount(TrainingStatusKind.VO2_MAX, 1),
    )
    assert ingestion.summary.training_status_blocks == 1
    assert ingestion.summary.blocks_without_proper_instant == 1


def test_a_block_without_its_date_is_refused_and_counted(tmp_path: Path) -> None:
    document = _document(DAY, statuses={"7": status_entry(DAY, calendarDate=None)})
    write_document(tmp_path, DayFamily.TRAINING_STATUS, document)
    ingestion = build(tmp_path)
    assert ingestion.history.statuses == ()
    assert ingestion.report.refused_blocks == (
        BlockCount(TrainingStatusKind.STATUS, 1),
    )
    assert ingestion.summary.training_status_blocks == 0


def test_every_ingested_field_of_a_block_is_compared() -> None:
    """``BLOCK_FIELDS`` : chaque champ du contrat d'une sorte, hors de la date propre,
    du jour du fichier, de l'instant propre et de la provenance."""
    contracts = {
        TrainingStatusKind.STATUS: TrainingStatusBlock,
        TrainingStatusKind.LOAD_BALANCE: LoadBalanceBlock,
        TrainingStatusKind.VO2_MAX: Vo2MaxBlock,
        TrainingStatusKind.HEAT_ACCLIMATION: HeatAcclimationBlock,
        TrainingStatusKind.ALTITUDE_ACCLIMATION: AltitudeAcclimationBlock,
    }
    assert list(BLOCK_FIELDS) == list(TrainingStatusKind)
    for kind, contract in contracts.items():
        compared = [
            item.name
            for item in dataclasses.fields(contract)
            if item.name not in ("day", "file_day", "proper_instant", "source")
        ]
        assert [attribute for attribute, _ in BLOCK_FIELDS[kind]] == compared, kind
    assert dict(BLOCK_FIELDS) == {
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
