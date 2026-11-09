"""Chaque règle que le contrat de ``DayRow`` tient aussi, vue par le contrôle de la
valeur (AN2-2) : une situation inventée, une mutation du producteur, un contrôle. Tel
quel, le contrôle tient ; muté, le contrat refuse la ligne ; muté, le contrat
neutralisé,
la table se rend et le contrôle échoue."""

from __future__ import annotations

import math
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Any

import pytest

from fixtures.day_table import (
    PLUS1,
    complete_days,
    dense,
    index_entry,
    jan,
    journal_of,
    night_with,
    row_of,
    table,
)
from fixtures.days import (
    at,
    day_record,
    empty_day,
    readiness,
    stress_summary,
)
from mountain_perf.analyse import days as days_module
from mountain_perf.analyse.days import DayTable
from mountain_perf.schemas import (
    ContractError,
    JournalEventType,
    NightState,
    RestingHrStatus,
    ViewAbsence,
)
from mountain_perf.schemas.processed import (
    AdmissionRefusal,
    DayRow,
    DayRowState,
    NormalAbsence,
)

Columns = dict[str, Any]
D1, D2, D20 = jan(1), jan(2), jan(20)
REAL = DayRow


@dataclass(frozen=True)
class Rule:
    name: str
    situation: Callable[[], DayTable]
    check: Callable[[DayTable], None]
    mutate: Callable[[Columns], None]


def gap() -> DayTable:
    return table(complete_days(3, skip=(1,)))


def default() -> DayTable:
    return table(complete_days(1))


def twenty() -> DayTable:
    return table(complete_days(20))


def no_night() -> DayTable:
    return table((day_record(D1, night=None),))


def dense_night() -> DayTable:
    return table((day_record(D1, night=night_with(D1, dense(D1, 160))),))


def no_load() -> DayTable:
    return table(
        complete_days(1),
        entries=[
            index_entry("a", at(D1, 9), training_load=None),
            index_entry("b", at(D1, 11), training_load=None),
        ],
    )


def first(result: DayTable) -> DayRow:
    return result.rows[0]


def absent_of(result: DayTable) -> DayRow:
    return row_of(result, D2)


def on_absent(**changes: Any) -> Callable[[Columns], None]:
    def mutate(columns: Columns) -> None:
        if columns["state"] is DayRowState.ABSENT:
            columns.update(changes)

    return mutate


def on_all(**changes: Any) -> Callable[[Columns], None]:
    def mutate(columns: Columns) -> None:
        columns.update(changes)

    return mutate


def _window_absent(result: DayTable) -> None:
    row = absent_of(result)
    assert row.window_start is None
    assert row.data_end is None


def _window_empty(result: DayTable) -> None:
    assert first(result).window_start is None


def _mutate_empty(columns: Columns) -> None:
    if columns["state"] is DayRowState.EMPTY:
        columns["window_start"] = at(D1, 0)
        columns["data_end"] = at(D1, 23)


def _export(result: DayTable) -> None:
    assert absent_of(result).reference_export is None


def _uncertain(result: DayTable) -> None:
    assert first(result).uncertain_device is True


def _night_missing(result: DayTable) -> None:
    assert first(result).night_state is NightState.MISSING


def _no_night_reasons(result: DayTable) -> None:
    row = first(result)
    assert row.night_body_battery_absence is ViewAbsence.NO_NIGHT
    assert row.night_short_absence is ViewAbsence.NO_NIGHT


def _flag(result: DayTable) -> None:
    row = first(result)
    assert row.night_short is False
    assert row.night_short_absence is None


def _ceiling(result: DayTable) -> None:
    row = first(result)
    assert row.night_body_battery_ceiling is False
    assert row.night_body_battery_coverage == 1.0


def _coverage(result: DayTable) -> None:
    assert first(result).night_body_battery_coverage == 1.0


def _start_before_end(result: DayTable) -> None:
    row = first(result)
    assert row.night_start is not None
    assert row.night_end is not None
    assert row.night_start < row.night_end


def _end_is_start(columns: Columns) -> None:
    columns["night_end"] = columns["night_start"]


def _overlap(result: DayTable) -> None:
    assert first(result).naps_overlapping_night == 0


def _one_more_nap(columns: Columns) -> None:
    columns["naps_overlapping_night"] = columns["nap_count"] + 1


def _no_nap(result: DayTable) -> None:
    row = first(result)
    assert (row.nap_window_s, row.nap_sleep_s) == (0.0, 0.0)


def _stress_absent(result: DayTable) -> None:
    assert first(result).stress_valid is None


def _stress_time(result: DayTable) -> None:
    assert first(result).stress_measured_s == 63000.0


def _readiness(result: DayTable) -> None:
    row = first(result)
    assert row.readiness_absence is None
    assert row.readiness_instant == at(D1, 7, 5)


def _early() -> DayTable:
    return table((day_record(D1, readiness=(readiness(D1, instant=at(D1, 6)),)),))


def _score(result: DayTable) -> None:
    row = first(result)
    assert row.readiness_score is None
    assert row.readiness_level is None


def _entries(result: DayTable) -> None:
    assert first(result).readiness_entry_count == 1


def _two_events() -> DayTable:
    return table(
        complete_days(1),
        journal=journal_of(
            (D1, D1, JournalEventType.TRAVEL), (D1, D1, JournalEventType.RACE)
        ),
    )


def _types(result: DayTable) -> None:
    assert first(result).journal_types == (
        JournalEventType.RACE,
        JournalEventType.TRAVEL,
    )


def _without_load(result: DayTable) -> None:
    assert first(result).activities_without_load == 2


def _one_more_load(columns: Columns) -> None:
    columns["activities_without_load"] = columns["activity_count"] + 1


def _load_absent(result: DayTable) -> None:
    assert first(result).garmin_training_load is None


def _no_activity(result: DayTable) -> None:
    row = first(result)
    assert row.garmin_training_load == 0.0
    assert row.foot_elapsed_s == 0.0
    assert row.other_elapsed_s == 0.0


def _ill() -> DayTable:
    return table(
        complete_days(3), journal=journal_of((D2, D2, JournalEventType.ILLNESS))
    )


def _refused(result: DayTable) -> None:
    row = row_of(result, D2)
    assert row.hrv_refusal is AdmissionRefusal.ILLNESS
    assert row.hrv_admitted is False


def _admit_refused(columns: Columns) -> None:
    if columns["hrv_refusal"] is not None:
        columns["hrv_admitted"] = True


def _absent_reasons(result: DayTable) -> None:
    row = absent_of(result)
    assert row.hrv_refusal is AdmissionRefusal.ABSENT_ROW
    assert row.resting_hr_refusal is AdmissionRefusal.ABSENT_ROW


def _admitted_value(result: DayTable) -> None:
    row = first(result)
    assert row.hrv_admitted is True
    assert row.hrv_last_night_avg_ms == 50.0


def _hrv_range(result: DayTable) -> None:
    row = row_of(result, D20)
    assert row.hrv_range_low_ms == pytest.approx(50 / 1.02, rel=1e-6)
    assert row.hrv_range_high_ms == pytest.approx(51.0, rel=1e-6)


def _drop_high(columns: Columns) -> None:
    if columns["hrv_normal_ms"] is not None:
        columns["hrv_range_high_ms"] = None


def _hrv_normal(result: DayTable) -> None:
    row = row_of(result, D20)
    assert row.hrv_normal_absence is None
    assert row.hrv_normal_ms == pytest.approx(50, rel=1e-6)


def _too_few(columns: Columns) -> None:
    if columns["hrv_normal_ms"] is not None:
        columns["hrv_normal_absence"] = NormalAbsence.TOO_FEW_ADMITTED_DAYS


def _range_holds(result: DayTable) -> None:
    row = row_of(result, D20)
    assert row.resting_hr_range_high_bpm == 49.0
    assert row.resting_hr_normal_bpm == 48.0


def _high_below(columns: Columns) -> None:
    if columns["resting_hr_normal_bpm"] is not None:
        columns["resting_hr_range_high_bpm"] = columns["resting_hr_normal_bpm"] - 1


def _no_day(result: DayTable) -> None:
    row = row_of(result, D1)
    assert row.hrv_normal_absence is NormalAbsence.NO_ADMITTED_DAY
    assert row.hrv_admitted_days == 0


def _few_at_zero(columns: Columns) -> None:
    if columns["hrv_admitted_days"] == 0:
        columns["hrv_normal_absence"] = NormalAbsence.TOO_FEW_ADMITTED_DAYS


def _exponential(result: DayTable) -> None:
    row = row_of(result, D20)
    assert row.hrv_log_median is not None
    assert row.hrv_normal_ms == pytest.approx(math.exp(row.hrv_log_median), rel=1e-12)


def _scaled(columns: Columns) -> None:
    if columns["hrv_normal_ms"] is not None:
        columns["hrv_normal_ms"] *= 1.001


def _absent_ranks(result: DayTable) -> None:
    assert absent_of(result).device_ranks == ()


def _absent_steps(result: DayTable) -> None:
    assert absent_of(result).steps is None


def _absent_naps(result: DayTable) -> None:
    assert absent_of(result).nap_count == 0


def _absent_status(result: DayTable) -> None:
    assert absent_of(result).resting_hr_status is RestingHrStatus.ABSENT


def _absent_entries(result: DayTable) -> None:
    assert absent_of(result).readiness_entry_count == 0


NOON = datetime(2000, 1, 2, tzinfo=PLUS1)
NEXT = datetime(2000, 1, 3, tzinfo=PLUS1)
JOURNEY = (JournalEventType.TRAVEL, JournalEventType.RACE)
NO_LOW = stress_summary(D1, low_duration_s=None)

RULES = [
    Rule(
        "fenêtre, ligne absent",
        gap,
        _window_absent,
        on_absent(window_start=NOON, data_end=NEXT),
    ),
    Rule(
        "fenêtre, ligne empty",
        lambda: table((empty_day(D1),)),
        _window_empty,
        _mutate_empty,
    ),
    Rule("export", gap, _export, on_absent(reference_export="garmin_a")),
    Rule(
        "deux rangs",
        lambda: table((day_record(D1, device_ranks=(1, 2)),)),
        _uncertain,
        on_all(uncertain_device=False),
    ),
    Rule(
        "état de la nuit",
        no_night,
        _night_missing,
        on_all(night_state=NightState.COMPLETE),
    ),
    Rule(
        "motifs sans nuit",
        no_night,
        _no_night_reasons,
        on_all(
            night_body_battery_absence=ViewAbsence.BELOW_COVERAGE,
            night_short_absence=ViewAbsence.NO_MEASURED_SLEEP,
        ),
    ),
    Rule(
        "drapeau ou motif",
        default,
        _flag,
        on_all(night_short_absence=ViewAbsence.NO_MEASURED_SLEEP),
    ),
    Rule(
        "plafond et couverture",
        dense_night,
        _ceiling,
        on_all(night_body_battery_ceiling=None),
    ),
    Rule(
        "couverture bornée",
        dense_night,
        _coverage,
        on_all(night_body_battery_coverage=1.5),
    ),
    Rule("début avant fin", default, _start_before_end, _end_is_start),
    Rule("siestes sur la nuit", default, _overlap, _one_more_nap),
    Rule(
        "sans sieste",
        lambda: table((day_record(D1, naps=()),)),
        _no_nap,
        on_all(nap_window_s=60.0),
    ),
    Rule(
        "validité du stress",
        lambda: table((day_record(D1, stress=NO_LOW),)),
        _stress_absent,
        on_all(stress_valid=False),
    ),
    Rule("durées positives", default, _stress_time, on_all(stress_measured_s=-1.0)),
    Rule(
        "instant de Readiness",
        default,
        _readiness,
        on_all(readiness_absence=ViewAbsence.NO_ENTRY_AFTER_NIGHT),
    ),
    Rule(
        "score avec l'instant",
        _early,
        _score,
        on_all(readiness_score=70, readiness_level="MODERATE"),
    ),
    Rule("une entrée", default, _entries, on_all(readiness_entry_count=0)),
    Rule("types triés", _two_events, _types, on_all(journal_types=JOURNEY)),
    Rule("comptes d'activité", no_load, _without_load, _one_more_load),
    Rule("charge absente", no_load, _load_absent, on_all(garmin_training_load=0.0)),
    Rule("sans activité", default, _no_activity, on_all(foot_elapsed_s=60.0)),
    Rule("admise sans motif", _ill, _refused, _admit_refused),
    Rule(
        "absent_row",
        gap,
        _absent_reasons,
        on_absent(
            hrv_refusal=AdmissionRefusal.NO_VALUE,
            resting_hr_refusal=AdmissionRefusal.NO_VALUE,
        ),
    ),
    Rule(
        "valeur admise présente",
        default,
        _admitted_value,
        on_all(hrv_last_night_avg_ms=None),
    ),
    Rule("normale et plage ensemble", twenty, _hrv_range, _drop_high),
    Rule("normale ou motif", twenty, _hrv_normal, _too_few),
    Rule("plage et normale", twenty, _range_holds, _high_below),
    Rule("no_admitted_day", twenty, _no_day, _few_at_zero),
    Rule("exponentielle", twenty, _exponential, _scaled),
    Rule("absent : rangs", gap, _absent_ranks, on_absent(device_ranks=(1,))),
    Rule("absent : valeur du jour", gap, _absent_steps, on_absent(steps=1)),
    Rule("absent : sieste", gap, _absent_naps, on_absent(nap_count=1)),
    Rule(
        "absent : FC de repos",
        gap,
        _absent_status,
        on_absent(resting_hr_status=RestingHrStatus.NO_NIGHT),
    ),
    Rule(
        "absent : Readiness", gap, _absent_entries, on_absent(readiness_entry_count=1)
    ),
]


def _mutated(monkeypatch: pytest.MonkeyPatch, rule: Rule) -> None:
    def build(**columns: Any) -> DayRow:
        rule.mutate(columns)
        return REAL(**columns)

    monkeypatch.setattr(days_module, "DayRow", build)


@pytest.mark.parametrize("rule", RULES, ids=lambda rule: rule.name)
def test_as_it_is_the_check_holds(rule: Rule) -> None:
    rule.check(rule.situation())


@pytest.mark.parametrize("rule", RULES, ids=lambda rule: rule.name)
def test_mutated_the_contract_refuses(
    rule: Rule, monkeypatch: pytest.MonkeyPatch
) -> None:
    _mutated(monkeypatch, rule)
    with pytest.raises(ContractError):
        rule.situation()


@pytest.mark.parametrize("rule", RULES, ids=lambda rule: rule.name)
def test_mutated_and_neutralized_the_check_fails(
    rule: Rule, monkeypatch: pytest.MonkeyPatch
) -> None:
    _mutated(monkeypatch, rule)
    monkeypatch.setattr(DayRow, "__post_init__", lambda self: None)
    result = rule.situation()
    with pytest.raises(AssertionError):
        rule.check(result)
