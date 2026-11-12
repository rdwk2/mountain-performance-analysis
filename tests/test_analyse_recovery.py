"""La vue de la page « récupération » (AN2-3, annexe C.2 du brief) : sur le monde
inventé de ``fixtures.recovery_world``. Python pur : ces tests tournent sans extra."""

from __future__ import annotations

import dataclasses
import enum
import json
from collections import Counter
from collections.abc import Mapping, Sequence
from datetime import date
from pathlib import Path
from typing import Any

import pytest

from fixtures.recovery_world import (
    FIRST_DAY,
    base_tables,
    changed_world,
    day_of,
    world_columns,
    world_rows,
    world_tables,
)
from mountain_perf.analyse.normals import NormalMeasure
from mountain_perf.analyse.recovery import (
    ABSENCE_LABELS,
    EXPERT_LEGEND,
    FAMILIES,
    JOURNAL_LABELS,
    MEASURE_LABELS,
    NIGHT_LABELS,
    NO_TREND,
    RECENT_DAYS,
    REFUSAL_LABELS,
    RESTING_HR_LABELS,
    MeasureLabel,
    MeasurePanel,
    RecoveryView,
    _number,
    data_at,
    legend,
    recovery_view,
)
from mountain_perf.analyse.tables import Tables
from mountain_perf.schemas.processed import (
    AdmissionRefusal,
    DayRow,
    JournalEventType,
    NormalAbsence,
)

HRV = NormalMeasure.HRV
SLEEP = NormalMeasure.MEASURED_SLEEP
SPO2 = NormalMeasure.NIGHT_SPO2


@pytest.fixture(scope="module")
def base(tmp_path_factory: pytest.TempPathFactory) -> Tables:
    return base_tables(tmp_path_factory.mktemp("base"))


def _view(
    base: Tables,
    *,
    rows: Sequence[DayRow] | None = None,
    journal: bool = True,
    parameters: dict[str, float] | None = None,
    everything: bool = False,
) -> RecoveryView:
    tables = world_tables(base, rows=rows, journal=journal, parameters=parameters)
    return recovery_view(tables.days, tables.provenance, everything=everything)


def _panel(view: RecoveryView, measure: NormalMeasure) -> MeasurePanel:
    return view.panels[list(NormalMeasure).index(measure)]


def _index(text: str) -> int:
    """Le rang dans le monde du jour d'une date d'instant UTC."""
    return (date.fromisoformat(text[:10]) - FIRST_DAY).days


def _edge(index: int) -> str:
    return f"{day_of(index).isoformat()}T00:00:00Z"


def _noon(index: int) -> str:
    return f"{day_of(index).isoformat()}T12:00:00Z"


def _point(view: RecoveryView, measure: NormalMeasure, index: int) -> Mapping[str, Any]:
    first = (view.first_day - FIRST_DAY).days if view.first_day else 0
    return _panel(view, measure).points[index - first]


def _replaced(
    changes: dict[int, dict[str, Any]], rows: Sequence[DayRow] | None = None
) -> list[DayRow]:
    """Les lignes du monde (ou ``rows``), champs changés **sans** recalculer les
    normales."""
    out = list(world_rows() if rows is None else rows)
    for index, update in changes.items():
        out[index] = dataclasses.replace(out[index], **update)
    return out


def _all_ill() -> tuple[DayRow, ...]:
    """Le monde dont tous les jours portent ``maladie`` : aucun jour admis, aucune
    normale."""
    return changed_world(
        {
            i: {"journal_types": (JournalEventType.ILLNESS,)}
            for i in range(len(world_columns()))
        }
    )


def test_the_default_period_is_the_last_56_rows(base: Tables) -> None:
    assert RECENT_DAYS == 56
    view = _view(base)
    assert view.first_day == day_of(84)
    assert view.last_day == day_of(139)
    assert view.x_domain == ("2000-03-27T00:00:00Z", "2000-05-22T00:00:00Z")
    assert all(len(panel.points) == 56 for panel in view.panels)
    whole = _view(base, everything=True)
    assert whole.everything
    assert whole.first_day == day_of(0)
    assert all(len(panel.points) == 140 for panel in whole.panels)


def test_the_six_panels_in_the_order_of_the_measures(base: Tables) -> None:
    view = _view(base)
    assert [panel.measure for panel in view.panels] == list(NormalMeasure)
    assert [panel.title for panel in view.panels] == [
        "HRV de la nuit (ms)",
        "FC de repos (bpm)",
        "Sommeil mesuré (h)",
        "Stress de la nuit",
        "Respiration de la nuit (resp./min)",
        "SpO2 de la nuit (%)",
    ]


def test_the_marks_follow_the_admission_of_the_table(base: Tables) -> None:
    view = _view(base)
    marks = Counter(point["marque"] for point in _panel(view, HRV).points)
    assert marks == {"plein": 37, "creux": 15, "pied": 4}
    for everything in (False, True):
        shown = _view(base, everything=everything)
        rows = world_rows()[-RECENT_DAYS:] if not everything else world_rows()
        for panel in shown.panels:
            for row, point in zip(rows, panel.points, strict=True):
                admitted = getattr(row, f"{panel.measure.value}_admitted")
                assert (point["marque"] == "plein") == admitted
                assert (point["marque"] == "pied") == (point["y"] is None)


def test_a_refused_value_outside_the_extent_sits_on_the_edge(base: Tables) -> None:
    view = _view(base)
    hrv = _panel(view, HRV)
    assert hrv.domain is not None
    zero = _point(view, HRV, 95)
    assert zero["marque"] == "creux"
    assert zero["hors"] == "dessous"
    assert zero["y"] == hrv.domain[0]
    assert zero["Valeur"] == "0 ms"
    rest = _panel(view, NormalMeasure.RESTING_HR)
    assert rest.domain is not None
    high = _point(view, NormalMeasure.RESTING_HR, 108)
    assert high["Valeur"] == "140 bpm"
    assert high["hors"] == "dessus"
    assert high["y"] == rest.domain[1]
    for panel in view.panels:
        assert all(
            point["hors"] is None
            for point in panel.points
            if point["marque"] == "plein"
        )


def test_a_panel_without_value_nor_normal_is_empty(base: Tables) -> None:
    spo2 = _panel(_view(base), SPO2)
    assert spo2.empty
    assert spo2.domain is None
    assert {point["marque"] for point in spo2.points} == {"pied"}
    assert spo2.normal_lines == ()
    assert spo2.isolated == ()
    assert not _panel(_view(base, everything=True), SPO2).empty


def test_no_normal_line_crosses_an_absent_normal(base: Tables) -> None:
    view = _view(base, everything=True)
    rows = world_rows()
    for panel in view.panels:
        column = f"{panel.measure.value}_normal_absence"
        runs: dict[str, list[int]] = {}
        for line in panel.normal_lines:
            index = _index(line["midi"])
            assert getattr(rows[index], column) is None
            runs.setdefault(line["suite"], []).append(index)
        for days in runs.values():
            assert days == list(range(days[0], days[0] + len(days)))


def _runs(panel: MeasurePanel) -> dict[str, list[Mapping[str, Any]]]:
    runs: dict[str, list[Mapping[str, Any]]] = {}
    for line in panel.normal_lines:
        runs.setdefault(line["suite"], []).append(line)
    return runs


def test_a_dashed_run_shares_its_ends_with_the_solid_runs(base: Tables) -> None:
    runs = list(_runs(_panel(_view(base), HRV)).values())
    assert [run[0]["trait"] for run in runs] == ["plein", "pointillé", "plein"]
    assert all(len({line["trait"] for line in run}) == 1 for run in runs)
    first, dashed, last = runs
    assert first[-1]["midi"] == dashed[0]["midi"]
    assert dashed[-1]["midi"] == last[0]["midi"]
    rows = world_rows()
    straddles = [rows[_index(line["midi"])].hrv_normal_straddles for line in dashed]
    assert straddles[0] is False
    assert straddles[-1] is False
    assert all(straddles[1:-1])


def test_a_one_day_segment_is_an_isolated_normal(base: Tables) -> None:
    spo2 = _panel(_view(base, everything=True), SPO2)
    assert [line["midi"] for line in spo2.isolated] == [_noon(70)]
    assert _noon(70) not in {line["midi"] for line in spo2.normal_lines}


def test_the_ruptures_and_the_uncertain_days(base: Tables) -> None:
    view = _view(base)
    assert [r["debut"] for r in _panel(view, HRV).ruptures] == [_edge(90)]
    assert [u["debut"] for u in view.uncertain] == [_edge(i) for i in (87, 88, 89)]
    assert [u["fin"] for u in view.uncertain] == [_edge(i) for i in (88, 89, 90)]
    sleep = _panel(_view(base, everything=True), SLEEP)
    assert [r["debut"] for r in sleep.ruptures] == [_edge(i) for i in (30, 60, 90)]


def test_one_ribbon_per_run_of_days_that_carry_the_type(base: Tables) -> None:
    view = _view(base)
    assert [
        (r["type"], _index(r["debut"]), _index(r["fin"])) for r in view.ribbons
    ] == [
        ("maladie", 100, 103),
        ("blessure", 102, 105),
        ("course", 110, 111),
        ("course", 115, 116),
        ("sejour_altitude", 120, 126),
    ]
    assert not view.journal_absent


def test_without_journal_no_ribbon_and_the_view_says_so(base: Tables) -> None:
    view = _view(base, journal=False)
    assert view.ribbons == ()
    assert view.journal_absent


def test_the_activity_marks_the_missing_load(base: Tables) -> None:
    view = _view(base)
    loads = {_index(load["midi"]): load for load in view.loads}
    assert loads[130]["marque"] == "pied"
    assert loads[130]["charge"] is None
    assert loads[131]["marque"] == "creux"
    assert loads[132]["marque"] == "plein"
    assert all(load["Activités"] > 0 for load in view.loads)
    families = {d["famille"] for d in view.durations if _index(d["debut"]) == 131}
    assert families == {"Autres", "À pied"}
    assert not [d for d in view.durations if _index(d["debut"]) == 133]


def test_the_garmin_hrv_keeps_the_days_that_have_one(base: Tables) -> None:
    days = _view(base).garmin_hrv
    assert len(days) == 53
    assert _noon(88) not in {day["midi"] for day in days}


def test_a_garmin_day_with_one_bound_only_is_not_kept(base: Tables) -> None:
    rows = _replaced(
        {139: {"hrv_weekly_avg_ms": None, "hrv_baseline_balanced_upper_ms": None}}
    )
    days = _view(base, rows=rows).garmin_hrv
    assert len(days) == 52
    assert _noon(139) not in {day["midi"] for day in days}


@pytest.mark.parametrize(
    ("name", "value", "written"),
    [
        ("normal.range_k", 2.0, "± 2,00"),
        ("normal.mad_factor", 1.0, "1,0000 × MAD"),
        ("normal.window_days", 30.0, "parmi les 30 précédents"),
    ],
)
def test_the_legend_holds_only_under_the_default_parameters(
    base: Tables, name: str, value: float, written: str
) -> None:
    assert _view(base).legend == EXPERT_LEGEND
    legend = _view(base, parameters={name: value}).legend
    text = " ".join(legend)
    assert legend != EXPERT_LEGEND
    assert "un jour ordinaire sur trois" not in text
    assert legend[-1].endswith(NO_TREND)
    assert ("deux semaines environ" in text) == (name != "normal.window_days")
    assert written in text


def test_data_at_is_written_at_paris_time(base: Tables) -> None:
    for acquired, text in (
        (
            "2000-05-21T19:15:00+00:00",
            "Données au 21/05/2000 à 21 h 15 (heure de Paris)",
        ),
        (
            "2000-01-10T23:30:00+00:00",
            "Données au 11/01/2000 à 0 h 30 (heure de Paris)",
        ),
    ):
        provenance = dataclasses.replace(base.provenance, acquired_at=acquired)
        assert data_at(provenance) == text
    assert _view(base).data_at == "Données au 21/05/2000 à 21 h 15 (heure de Paris)"


def test_an_empty_table_gives_empty_panels(base: Tables) -> None:
    view = _view(base, rows=())
    assert view.first_day is None
    assert view.last_day is None
    assert view.x_domain is None
    assert len(view.panels) == 6
    for panel in view.panels:
        assert panel.empty
        assert panel.points == ()
        assert panel.normal_lines == ()
        assert panel.isolated == ()
        assert panel.ruptures == ()
    assert view.ribbons == ()
    assert view.durations == ()
    assert view.loads == ()
    assert view.garmin_hrv == ()
    assert view.uncertain == ()


def test_the_tooltip_says_the_refusal_and_the_normal(base: Tables) -> None:
    view = _view(base, everything=True)
    admissions = {point["Admission"] for point in _panel(view, HRV).points}
    assert {
        "admise",
        "refusée : maladie (journal)",
        "refusée : pas de données ce jour",
        "refusée : valeur invalide",
    } <= admissions
    normals = {point["Normale"] for point in _panel(view, SPO2).points}
    assert {
        "absente : aucun jour admis dans la fenêtre",
        "absente : trop peu de jours admis dans la fenêtre",
    } <= normals
    assert any(
        point["Normale"].endswith(" ms (à cheval)")
        for point in _panel(view, HRV).points
    )


def test_each_refusal_says_its_own_label(base: Tables) -> None:
    view = _view(base, everything=True)
    admissions = {point["Admission"] for point in _panel(view, HRV).points}
    assert admissions == {"admise"} | {
        f"refusée : {label}" for label in REFUSAL_LABELS.values()
    }
    short = _point(view, HRV, 105)
    assert short["Admission"] == "refusée : nuit courte"
    assert short["Nuit"] == "complète (courte, décalée : inconnu)"
    shifted = _point(view, HRV, 112)
    assert shifted["Admission"] == "refusée : nuit décalée"
    assert "décalée" in shifted["Nuit"]
    assert _point(view, HRV, 128)["Nuit"].startswith("partielle")
    statuses = {point["FC de repos"] for p in view.panels for point in p.points}
    assert statuses <= set(RESTING_HR_LABELS.values())


def test_the_admitted_days_of_the_tooltip(base: Tables) -> None:
    view = _view(base, everything=True)
    for panel in view.panels:
        column = f"{panel.measure.value}_admitted_days"
        for row, point in zip(world_rows(), panel.points, strict=True):
            assert point["Jours admis"] == getattr(row, column)


def test_the_extent_holds_the_range(base: Tables) -> None:
    for everything in (False, True):
        for panel in _view(base, everything=everything).panels:
            for line in (*panel.normal_lines, *panel.isolated):
                assert panel.domain is not None
                assert panel.domain[0] <= line["bas"] <= line["haut"] <= panel.domain[1]


def test_rows_that_are_not_consecutive_are_refused(base: Tables) -> None:
    rows = list(world_rows())
    del rows[50]
    tables = world_tables(base, rows=rows)
    with pytest.raises(ValueError, match="pas consécutives"):
        recovery_view(tables.days, tables.provenance)


def test_a_ribbon_cut_by_the_period_keeps_its_dates(base: Tables) -> None:
    rows = changed_world(
        {i: {"journal_types": (JournalEventType.ILLNESS,)} for i in range(80, 87)}
    )
    ribbons = [
        r
        for r in _view(base, rows=rows).ribbons
        if r["Période"].startswith("du 23/03/2000 au")
    ]
    assert len(ribbons) == 1
    assert ribbons[0]["type"] == "maladie"
    assert ribbons[0]["debut"] == _edge(84)
    assert ribbons[0]["fin"] == _edge(87)


def test_a_journal_without_event_in_the_period(base: Tables) -> None:
    rows = changed_world(
        {10: {"journal_types": (JournalEventType.RACE,)}}, journal=False
    )
    view = _view(base, rows=rows)
    assert view.ribbons == ()
    assert not view.journal_absent
    assert _view(base, rows=rows, everything=True).ribbons


def test_a_journal_without_any_event_is_not_absent(base: Tables) -> None:
    """V14 : ``journal_absent`` se lit sur la provenance, jamais sur les types des
    jours ; un ``journal.csv`` présent sans aucun événement n'est pas un journal
    absent (contre-épreuve M04, sous sa forme « toute la table »)."""
    rows = world_rows(journal=False)
    assert not any(row.journal_types for row in rows)
    for everything in (False, True):
        view = _view(base, rows=rows, everything=everything)
        assert view.ribbons == ()
        assert not view.journal_absent


def test_an_isolated_normal_that_straddles_is_dashed(base: Tables) -> None:
    rows = _replaced({70: {"night_spo2_normal_straddles": True}})
    isolated = _panel(_view(base, rows=rows, everything=True), SPO2).isolated
    assert len(isolated) == 1
    assert isolated[0]["trait"] == "pointillé"
    assert isolated[0]["pointille"] is True


def test_an_invalid_value_does_not_stretch_an_axis_without_extent(
    base: Tables,
) -> None:
    view = _view(base, rows=_all_ill())
    hrv = _panel(view, HRV)
    assert hrv.normal_lines == ()
    assert all(point["marque"] != "plein" for point in hrv.points)
    assert hrv.domain is not None
    assert hrv.domain[0] > 0
    zero = _point(view, HRV, 95)
    assert zero["Valeur"] == "0 ms"
    assert zero["hors"] == "dessous"
    assert zero["y"] == hrv.domain[0]


def test_the_garmin_hrv_runs_stop_at_a_missing_day(base: Tables) -> None:
    days = _view(base, everything=True).garmin_hrv
    runs: dict[str, list[int]] = {}
    for day in days:
        if day["suite_moyenne"] is not None:
            runs.setdefault(day["suite_moyenne"], []).append(_index(day["midi"]))
    assert len(runs) == 3
    for indices in runs.values():
        assert indices == list(range(indices[0], indices[0] + len(indices)))


def test_a_refused_value_on_the_edge_stays_and_just_below_goes_to_the_edge(
    base: Tables,
) -> None:
    domain = _panel(_view(base), HRV).domain
    assert domain is not None
    assert not world_rows()[112].hrv_admitted
    on_edge = _view(base, rows=_replaced({112: {"hrv_last_night_avg_ms": domain[0]}}))
    point = _point(on_edge, HRV, 112)
    assert point["hors"] is None
    assert point["y"] == domain[0]
    assert _panel(on_edge, HRV).domain == domain
    below = _view(
        base, rows=_replaced({112: {"hrv_last_night_avg_ms": domain[0] - 1e-9}})
    )
    point = _point(below, HRV, 112)
    assert point["hors"] == "dessous"
    assert point["y"] == domain[0]
    assert _panel(below, HRV).domain == domain


def test_a_one_day_run_inside_a_segment_is_drawn_not_isolated(base: Tables) -> None:
    rows = _replaced({130: {"hrv_normal_straddles": True}})
    hrv = _panel(_view(base, rows=rows), HRV)
    assert hrv.isolated == ()
    dashed = [line for line in hrv.normal_lines if line["pointille"]]
    assert [_index(line["midi"]) for line in dashed[-3:]] == [129, 130, 131]
    assert len({line["suite"] for line in dashed[-3:]}) == 1


def test_data_at_writes_the_minutes_on_two_digits(base: Tables) -> None:
    provenance = dataclasses.replace(
        base.provenance, acquired_at="2000-07-01T06:05:00+00:00"
    )
    assert data_at(provenance) == "Données au 01/07/2000 à 8 h 05 (heure de Paris)"


def test_the_extent_is_widened_by_five_percent_of_its_width(base: Tables) -> None:
    rows = world_rows()[-RECENT_DAYS:]
    values = [
        row.hrv_last_night_avg_ms
        for row in rows
        if row.hrv_admitted and row.hrv_last_night_avg_ms is not None
    ]
    for row in rows:
        if row.hrv_range_low_ms is not None and row.hrv_range_high_ms is not None:
            values += [row.hrv_range_low_ms, row.hrv_range_high_ms]
    low, high = min(values), max(values)
    assert _panel(_view(base), HRV).domain == (
        low - 0.05 * (high - low),
        high + 0.05 * (high - low),
    )


@pytest.mark.parametrize(
    ("value", "expected"), [(55.0, (52.25, 57.75)), (10.0, (9.0, 11.0))]
)
def test_an_extent_of_one_value_is_widened_by_its_size_or_one(
    base: Tables, value: float, expected: tuple[float, float]
) -> None:
    rows = _replaced(
        {
            130: {
                "hrv_last_night_avg_ms": value,
                "hrv_admitted": True,
                "hrv_refusal": None,
            }
        },
        _all_ill(),
    )
    assert rows[87].hrv_refusal is AdmissionRefusal.ABSENT_ROW
    assert rows[115].hrv_refusal is AdmissionRefusal.NO_VALUE
    domain = _panel(_view(base, rows=rows), HRV).domain
    assert domain is not None
    assert domain == pytest.approx(expected, rel=1e-12)


def test_the_tooltip_writes_the_value_the_normal_and_the_range_in_the_unit(
    base: Tables,
) -> None:
    rows = _replaced(
        {
            130: {
                "measured_sleep_s": 27000.0,
                "measured_sleep_normal_s": 26000.0,
                "measured_sleep_range_low_s": 25200.0,
                "measured_sleep_range_high_s": 28800.0,
                "respiration_avg_sleep_breaths_per_min": 14.3,
                "night_respiration_normal_breaths_per_min": 14.5,
                "night_respiration_range_low_breaths_per_min": 13.9,
                "night_respiration_range_high_breaths_per_min": 15.1,
            }
        }
    )
    view = _view(base, rows=rows)
    sleep = _point(view, SLEEP, 130)
    assert sleep["Valeur"] == "7,50 h"
    assert sleep["Normale"] == "7,22 h"
    assert sleep["Plage"] == "7,00 à 8,00 h"
    assert sleep["y"] == 7.5
    breath = _point(view, NormalMeasure.NIGHT_RESPIRATION, 130)
    assert breath["Valeur"] == "14,3 resp./min"
    assert breath["Normale"] == "14,5 resp./min"
    assert breath["Plage"] == "13,9 à 15,1 resp./min"


def test_the_families_are_stacked_in_their_order(base: Tables) -> None:
    durations = _view(base, everything=True).durations
    names = [name for _, name in FAMILIES]
    assert all(d["ordre"] == names.index(d["famille"]) for d in durations)
    assert {d["famille"] for d in durations} == set(names)


def test_one_garmin_bound_alone_is_not_a_band(base: Tables) -> None:
    rows = _replaced({130: {"hrv_baseline_balanced_upper_ms": None}})
    days = {_index(day["midi"]): day for day in _view(base, rows=rows).garmin_hrv}
    assert days[130]["suite_bornes"] is None
    assert days[130]["Bornes"] == "—"
    assert days[129]["suite_bornes"] is not None
    assert days[131]["suite_bornes"] is not None
    assert days[129]["suite_bornes"] != days[131]["suite_bornes"]


def test_the_load_text_says_missing_and_partial(base: Tables) -> None:
    loads = {_index(load["midi"]): load for load in _view(base).loads}
    assert loads[130]["Charge"] == "absente (aucune activité n'en a)"
    assert loads[131]["Charge"] == "40 (minorée : des activités sans charge)"
    assert loads[132]["Charge"] == "30"


def test_the_display_labels_are_exact() -> None:
    assert dict(MEASURE_LABELS) == {
        NormalMeasure.HRV: MeasureLabel("HRV de la nuit", "ms", 1.0, 0),
        NormalMeasure.RESTING_HR: MeasureLabel("FC de repos", "bpm", 1.0, 0),
        NormalMeasure.MEASURED_SLEEP: MeasureLabel("Sommeil mesuré", "h", 1 / 3600, 2),
        NormalMeasure.NIGHT_STRESS: MeasureLabel("Stress de la nuit", "", 1.0, 0),
        NormalMeasure.NIGHT_RESPIRATION: MeasureLabel(
            "Respiration de la nuit", "resp./min", 1.0, 1
        ),
        NormalMeasure.NIGHT_SPO2: MeasureLabel("SpO2 de la nuit", "%", 1.0, 0),
    }
    assert list(MEASURE_LABELS) == list(NormalMeasure)
    assert dict(REFUSAL_LABELS) == {
        AdmissionRefusal.ABSENT_ROW: "pas de données ce jour",
        AdmissionRefusal.NO_VALUE: "pas de valeur",
        AdmissionRefusal.INVALID_VALUE: "valeur invalide",
        AdmissionRefusal.NIGHT_NOT_COMPLETE: "nuit incomplète",
        AdmissionRefusal.SHORT_NIGHT: "nuit courte",
        AdmissionRefusal.SHIFTED_NIGHT: "nuit décalée",
        AdmissionRefusal.ILLNESS: "maladie (journal)",
        AdmissionRefusal.INJURY: "blessure (journal)",
        AdmissionRefusal.ALTITUDE_STAY: "séjour en altitude (journal)",
    }
    assert list(REFUSAL_LABELS) == list(AdmissionRefusal)
    assert dict(ABSENCE_LABELS) == {
        NormalAbsence.NO_ADMITTED_DAY: "aucun jour admis dans la fenêtre",
        NormalAbsence.TOO_FEW_ADMITTED_DAYS: "trop peu de jours admis dans la fenêtre",
    }
    assert list(ABSENCE_LABELS) == list(NormalAbsence)
    assert list(JOURNAL_LABELS.items()) == [
        (JournalEventType.ILLNESS, "Maladie"),
        (JournalEventType.INJURY, "Blessure"),
        (JournalEventType.RACE, "Course"),
        (JournalEventType.TRAVEL, "Déplacement"),
        (JournalEventType.MOVE, "Déménagement"),
        (JournalEventType.ALTITUDE_STAY, "Séjour en altitude"),
        (JournalEventType.BENCHMARK, "Étalon"),
        (JournalEventType.OTHER, "Autre"),
    ]
    assert dict(NIGHT_LABELS) == {
        "missing": "absente",
        "declared": "déclarée",
        "in_progress": "en cours",
        "partial": "partielle",
        "complete": "complète",
    }
    assert dict(RESTING_HR_LABELS) == {
        "absent": "absente",
        "provisional": "provisoire",
        "no_night": "sans nuit",
        "valid": "valide",
    }
    assert FAMILIES == (
        ("foot_elapsed_s", "À pied"),
        ("mtb_elapsed_s", "VTT"),
        ("ski_touring_elapsed_s", "Ski de randonnée"),
        ("other_elapsed_s", "Autres"),
    )


# Correctifs de la PR AN2-3, lot 1 : les règles qu'aucun test ne tenait.

VIEW_FILE = Path(__file__).parent / "fixtures" / "recovery_view.json"


def _jsonable(value: object) -> object:
    """La règle de conversion de la forme écrite : une dataclass en objet (ses champs,
    dans leur ordre), une ``date`` en texte ISO, un tuple ou une liste en liste, un
    dictionnaire en objet (clés et ordre gardés), une énumération par sa valeur."""
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        return {
            f.name: _jsonable(getattr(value, f.name)) for f in dataclasses.fields(value)
        }
    if isinstance(value, enum.Enum):
        return value.value
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, tuple | list):
        return [_jsonable(item) for item in value]
    if isinstance(value, Mapping):
        return {str(key): _jsonable(item) for key, item in value.items()}
    return value


def _as_written(value: object) -> object:
    return json.loads(json.dumps(_jsonable(value), ensure_ascii=False))


def test_the_whole_view_is_its_written_form(base: Tables) -> None:
    """La vue entière du monde inventé, sous deux appels : sans l'argument
    ``everything`` (la période récente, par la valeur par défaut), puis ``everything``
    vrai ; chacune, convertie par :func:`_jsonable`, est comparée entière à sa forme
    écrite dans ``fixtures/recovery_view.json``.

    Le fichier a été tiré une fois du code de la PR AN2-3 (tête ``7cebef4``), par un
    script hors du dépôt qui applique la même conversion, puis relu contre l'annexe A
    (A.1, ses paragraphes sur les dates et les nombres affichés) avant d'être figé. Un
    écart futur se relit contre l'annexe A avant de toucher au fichier : le fichier ne
    se retire pas pour faire passer le test."""
    written = json.loads(VIEW_FILE.read_text(encoding="utf-8"))
    tables = world_tables(base)
    recent = recovery_view(tables.days, tables.provenance)
    whole = recovery_view(tables.days, tables.provenance, everything=True)
    assert _as_written(recent) == written["recente"]
    assert _as_written(whole) == written["toute"]


def test_the_sleep_extent_is_in_hours(base: Tables) -> None:
    """V5 : l'étendue du sommeil est au facteur d'affichage (des heures), plage
    comprise."""
    rows = world_rows()[-RECENT_DAYS:]
    hours = [
        row.measured_sleep_s / 3600
        for row in rows
        if row.measured_sleep_admitted and row.measured_sleep_s is not None
    ]
    for row in rows:
        low, high = row.measured_sleep_range_low_s, row.measured_sleep_range_high_s
        if low is not None and high is not None:
            hours += [low / 3600, high / 3600]
    lowest, highest = min(hours), max(hours)
    expected = (
        lowest - 0.05 * (highest - lowest),
        highest + 0.05 * (highest - lowest),
    )
    domain = _panel(_view(base), SLEEP).domain
    assert domain == pytest.approx(expected, rel=1e-12)
    assert domain is not None
    assert 4.0 < domain[0] < domain[1] < 11.0


def test_a_refused_value_on_the_upper_edge_stays_inside(base: Tables) -> None:
    """V6 : une valeur refusée égale à la borne haute du domaine reste dedans."""
    domain = _panel(_view(base), HRV).domain
    assert domain is not None
    assert not world_rows()[112].hrv_admitted
    view = _view(base, rows=_replaced({112: {"hrv_last_night_avg_ms": domain[1]}}))
    point = _point(view, HRV, 112)
    assert point["hors"] is None
    assert point["y"] == domain[1]
    assert _panel(view, HRV).domain == domain


def test_a_repeated_day_and_two_rows_upside_down_are_refused(base: Tables) -> None:
    """V1 : un jour en double, puis deux lignes à l'envers, lèvent ``ValueError``."""
    rows = list(world_rows())
    repeated = [*rows[:51], rows[50], *rows[51:]]
    swapped = [*rows[:50], rows[51], rows[50], *rows[52:]]
    for case in (repeated, swapped):
        tables = world_tables(base, rows=case)
        with pytest.raises(ValueError, match="pas consécutives"):
            recovery_view(tables.days, tables.provenance)


def test_a_last_one_day_run_after_a_longer_one_is_not_isolated(base: Tables) -> None:
    """V10 : la dernière suite d'un segment n'a qu'un jour (son ``straddles`` change),
    après une suite plus longue du même segment : ce jour reste dans
    ``normal_lines``."""
    rows = _replaced({139: {"hrv_normal_straddles": True}})
    assert rows[139].hrv_segment == rows[138].hrv_segment
    hrv = _panel(_view(base, rows=rows), HRV)
    assert hrv.isolated == ()
    assert _noon(139) in {line["midi"] for line in hrv.normal_lines}


def test_the_ribbons_at_the_edges_of_the_period_and_at_the_same_start(
    base: Tables,
) -> None:
    """V13 : une suite qui finit au premier jour de la période, une qui commence au
    dernier ; une suite d'un type entièrement avant la période, puis une autre du même
    type dedans ; deux rubans au même ``debut``, triés par la valeur du type."""
    illness, injury = JournalEventType.ILLNESS, JournalEventType.INJURY
    changes: dict[int, dict[str, Any]] = {
        **{i: {"journal_types": (illness,)} for i in range(80, 85)},
        **{
            i: {"journal_types": (JournalEventType.TRAVEL,)}
            for i in (60, 61, 62, 90, 91)
        },
        **{i: {"journal_types": (injury, illness)} for i in (95, 96)},
        139: {"journal_types": (JournalEventType.RACE,)},
    }
    view = _view(base, rows=changed_world(changes, journal=False))
    assert [
        (r["type"], _index(r["debut"]), _index(r["fin"])) for r in view.ribbons
    ] == [
        ("maladie", 84, 85),
        ("deplacement", 90, 92),
        ("blessure", 95, 97),
        ("maladie", 95, 97),
        ("course", 139, 140),
    ]


def test_a_one_second_duration_is_kept(base: Tables) -> None:
    """V15 : une famille à une seconde donne son enregistrement."""
    rows = _replaced({132: {"foot_elapsed_s": 1.0}})
    durations = [
        d
        for d in _view(base, rows=rows).durations
        if _index(d["debut"]) == 132 and d["famille"] == "À pied"
    ]
    assert len(durations) == 1
    assert durations[0]["Durée"] == "0,00 h"
    assert durations[0]["heures"] == 1 / 3600


def test_the_four_counts_of_the_load_tooltip(base: Tables) -> None:
    """V16 : les quatre comptes du survol de la charge, quatre nombres différents."""
    rows = _replaced(
        {
            131: {
                "activity_count": 4,
                "activities_without_load": 1,
                "other_activity_count": 2,
                "activities_without_elapsed": 3,
            }
        }
    )
    (load,) = [x for x in _view(base, rows=rows).loads if _index(x["midi"]) == 131]
    assert load["Activités"] == 4
    assert load["Sans charge"] == 1
    assert load["Autres activités"] == 2
    assert load["Sans durée"] == 3


def test_the_legend_sentences_in_full(base: Tables) -> None:
    """V20 : les deux phrases en toutes lettres, w différent de 28 puis égal à 28 ; un
    paramètre absent de la provenance vaut 0."""
    no_trend = "Aucune bande simultanée n'est calculée : ne pas y lire une tendance."
    tail = (
        "pour la HRV, en log. Paramètres hors des valeurs par défaut : la part des "
        "jours qui en sortent n'est pas dite. Ce n'est pas un intervalle de "
        "confiance ; en sortir n'est pas une alerte."
    )
    thirty = _view(
        base,
        parameters={
            "normal.window_days": 30.0,
            "normal.range_k": 2.0,
            "normal.mad_factor": 1.0,
        },
    ).legend
    assert thirty == (
        "Plage habituelle : médiane ± 2,00 écart robuste des jours valides parmi les "
        "30 précédents (n jours : au survol) ; écart robuste : 1,0000 × MAD, au moins "
        "la résolution de la mesure ; " + tail,
        no_trend,
    )
    twenty_eight = _view(base, parameters={"normal.range_k": 1.5}).legend
    assert twenty_eight == (
        "Plage habituelle : médiane ± 1,50 écart robuste des jours valides parmi les "
        "28 précédents (n jours : au survol) ; écart robuste : 1,4826 × MAD, au moins "
        "la résolution de la mesure ; " + tail,
        "La normale suit un changement durable en deux semaines environ. " + no_trend,
    )
    without_k = dataclasses.replace(
        base.provenance,
        parameters=tuple(
            (name, value)
            for name, value in base.provenance.parameters
            if name != "normal.range_k"
        ),
    )
    assert legend(without_k)[0].startswith("Plage habituelle : médiane ± 0,00 écart")


def test_a_negative_number_is_written_with_the_minus_sign() -> None:
    """A.1, « Les nombres affichés » : aucune colonne affichée par la vue n'est
    négative ; le signe moins se lit donc sur la fonction de formatage du module."""
    assert _number(-1.25, 1, "ms") == "−1,2 ms"
    assert _number(-3.0, 0) == "−3"


def test_a_night_without_flag_is_its_label_alone(base: Tables) -> None:
    """V7 : une nuit sans drapeau (ni courte ni décalée, tous deux connus)."""
    rows = _replaced({130: {"night_shifted": False, "night_shifted_absence": None}})
    assert rows[130].night_short is False
    assert _point(_view(base, rows=rows), HRV, 130)["Nuit"] == "complète"


def test_the_view_is_pure_and_the_same_twice(base: Tables) -> None:
    """V21, V22 : la vue ne modifie pas les lignes reçues et ne dépend que de ses
    arguments."""
    tables = world_tables(base)
    rows = list(tables.days)
    copy = list(rows)
    first = recovery_view(rows, tables.provenance)
    assert rows == copy
    second = recovery_view(rows, tables.provenance)
    assert rows == copy
    assert first == second
    assert first == recovery_view(tuple(copy), tables.provenance)


def test_the_records_have_no_other_key(base: Tables) -> None:
    """A.1 : pour chaque sorte d'enregistrement, ses clés et aucune autre."""
    view = _view(base, everything=True)
    normal = {"midi", "normale", "bas", "haut", "suite", "pointille", "trait"}
    expected: list[tuple[str, Sequence[Mapping[str, Any]], set[str]]] = [
        (
            "point",
            [p for panel in view.panels for p in panel.points],
            {
                "midi",
                "marque",
                "y",
                "hors",
                "Jour",
                "Valeur",
                "Admission",
                "Nuit",
                "FC de repos",
                "Normale",
                "Plage",
                "Jours admis",
            },
        ),
        ("suite", [x for p in view.panels for x in p.normal_lines], normal),
        ("isolée", [x for p in view.panels for x in p.isolated], normal),
        ("rupture", [x for p in view.panels for x in p.ruptures], {"debut", "Rupture"}),
        ("incertain", view.uncertain, {"debut", "fin"}),
        ("ruban", view.ribbons, {"type", "Type", "debut", "fin", "Période"}),
        (
            "durée",
            view.durations,
            {"debut", "fin", "famille", "ordre", "heures", "Jour", "Durée"},
        ),
        (
            "charge",
            view.loads,
            {
                "midi",
                "charge",
                "marque",
                "Jour",
                "Charge",
                "Activités",
                "Sans charge",
                "Autres activités",
                "Sans durée",
            },
        ),
        (
            "garmin",
            view.garmin_hrv,
            {
                "midi",
                "moyenne",
                "bas",
                "haut",
                "suite_moyenne",
                "suite_bornes",
                "Jour",
                "Moyenne de la semaine",
                "Bornes",
            },
        ),
    ]
    for kind, records, keys in expected:
        assert records, kind
        for record in records:
            assert set(record) == keys, kind


def test_the_view_texts_are_those_of_the_annex(base: Tables) -> None:
    """A.7 : les textes que rend la vue, recopiés de l'annexe, comparés à la vue,
    jamais aux constantes du module."""
    whole = _view(base, everything=True)
    assert whole.legend == (
        "Plage habituelle : médiane ± 1 écart robuste des jours valides parmi les 28 "
        "précédents (n jours : au survol). Environ un jour ordinaire sur trois en "
        "sort. Ce n'est pas un intervalle de confiance ; en sortir n'est pas une "
        "alerte.",
        "La normale suit un changement durable en deux semaines environ. Aucune bande "
        "simultanée n'est calculée : ne pas y lire une tendance.",
    )
    outside = _view(base, parameters={"normal.window_days": 30.0}).legend
    assert outside[-1] == (
        "Aucune bande simultanée n'est calculée : ne pas y lire une tendance."
    )
    assert [panel.title for panel in whole.panels] == [
        "HRV de la nuit (ms)",
        "FC de repos (bpm)",
        "Sommeil mesuré (h)",
        "Stress de la nuit",
        "Respiration de la nuit (resp./min)",
        "SpO2 de la nuit (%)",
    ]
    admissions = {p["Admission"] for p in _panel(whole, HRV).points}
    assert admissions == {
        "admise",
        "refusée : pas de données ce jour",
        "refusée : pas de valeur",
        "refusée : valeur invalide",
        "refusée : nuit incomplète",
        "refusée : nuit courte",
        "refusée : nuit décalée",
        "refusée : maladie (journal)",
        "refusée : blessure (journal)",
        "refusée : séjour en altitude (journal)",
    }
    normals = {p["Normale"] for p in _panel(whole, SPO2).points}
    assert {
        "absente : aucun jour admis dans la fenêtre",
        "absente : trop peu de jours admis dans la fenêtre",
    } <= normals
    assert {r["Type"] for r in whole.ribbons} == {
        "Maladie",
        "Blessure",
        "Course",
        "Séjour en altitude",
    }
    assert {d["famille"] for d in whole.durations} == {
        "À pied",
        "VTT",
        "Ski de randonnée",
        "Autres",
    }
    nights = {p["Nuit"].split(" (")[0] for p in _panel(whole, HRV).points}
    assert nights == {"absente", "partielle", "complète"}
    rests = {p["FC de repos"] for p in _panel(whole, HRV).points}
    assert rests == {"absente", "provisoire", "valide"}
