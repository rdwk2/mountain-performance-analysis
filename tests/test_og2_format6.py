"""La DÉCLARATION et le RÉSULTAT au format 6 (OG-2, § 6.5 du brief OG-2) : le mode
glissant, les contrats neufs, leurs invariants à leurs bornes, les lignes anciennes
relues et réécrites à l'octet, les clés neuves refusées à un format antérieur."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import replace
from datetime import date
from pathlib import Path
from typing import Any

import pytest

from fixtures.registry import (
    CALIBRATED_MODELS,
    at,
    declaration,
    experiment,
    registry_root,
)
from mountain_perf.backtest import (
    canonical_bytes,
    decode_contract,
    decode_document,
    encode_contract,
    encode_document,
)
from mountain_perf.backtest.registry import (
    EVENTS_FILE,
    RegistryError,
    _line,
    _upgraded,
    append_declaration,
    line_hash,
    read_registry,
)
from mountain_perf.schemas import (
    CLOCKS,
    CURVE_STATUS_DESCRIPTIONS,
    REGISTRY_FORMAT_VERSION,
    ROLLING_FIRST_FORMAT,
    SHARE_SCOPE_DESCRIPTIONS,
    SHARE_UNAVAILABILITY_DESCRIPTIONS,
    UNAVAILABILITY_DESCRIPTIONS,
    CalibrationTerm,
    CalibrationTerms,
    CurveStatus,
    Declaration,
    EventKind,
    ModelKind,
    RegistryEvent,
    Result,
    RollingDeclaration,
    RollingPerformance,
    RollingResult,
    Scenario,
    ScenarioClockTerms,
    ShareScope,
    ShareUnavailability,
    Unavailability,
)
from mountain_perf.validation import ContractError

SHA_A, SHA_B, SHA_C = "a" * 64, "b" * 64, "c" * 64
CSV_SHA = "0123456789ab" + "d" * 52


def curve_performance(share: float = 0.25) -> RollingPerformance:
    return RollingPerformance(
        CurveStatus.CURVE,
        SHA_A,
        CSV_SHA,
        f"og2-2026-06-20-w56.csv#{CSV_SHA[:12]}",
        share,
        ShareScope.USAGE,
        None,
    )


def absent_performance() -> RollingPerformance:
    return RollingPerformance(
        CurveStatus.ABSENT, SHA_B, None, None, None, None, ShareUnavailability.NO_CURVE
    )


def no_read_performance() -> RollingPerformance:
    return RollingPerformance(
        CurveStatus.NO_READ_SUPPORT,
        SHA_C,
        CSV_SHA,
        f"og2-2026-06-27-w56.csv#{CSV_SHA[:12]}",
        None,
        None,
        ShareUnavailability.NO_CURVE,
    )


def rolling(**changes: Any) -> RollingDeclaration:
    fields: dict[str, Any] = {
        "rule": SHA_A,
        "window_days": 56,
        "command_windows": (28, 56, None),
        "covered_threshold": 0.1,
        "beyond_marker": 0.5,
        "coverage_tolerance_s": 60.0,
        "index_sha256": SHA_B,
        "platform": "Windows 11, Python 3.12.0",
        "performances": (
            curve_performance(),
            absent_performance(),
            no_read_performance(),
        ),
    }
    fields.update(changes)
    return RollingDeclaration(**fields)


def rolling_declaration(**changes: Any) -> Declaration:
    return declaration(
        curve_ref=None, curve=None, curve_metadata=None, rolling=rolling(), **changes
    )


def terms() -> CalibrationTerms:
    sets = tuple(
        ScenarioClockTerms(
            scenario,
            clock,
            (
                CalibrationTerm(date(2026, 6, 1), 3600.0, 3500.0),
                CalibrationTerm(date(2026, 6, 8), 1800.0, None),
            ),
        )
        for scenario in Scenario
        for clock in CLOCKS
    )
    return CalibrationTerms(ModelKind.V0_RECALIBRATED, sets)


# --- Le numéro et les énumérations ---------------------------------------------------


def test_the_format_6() -> None:
    assert REGISTRY_FORMAT_VERSION == ROLLING_FIRST_FORMAT == 6


def test_the_enumerations_and_their_descriptions() -> None:
    assert [s.value for s in CurveStatus] == ["curve", "absent", "no_read_support"]
    assert list(CURVE_STATUS_DESCRIPTIONS.values()) == [
        "courbe",
        "sans courbe : absence",
        "sans courbe : aucun support au seuil de lecture",
    ]
    assert [s.value for s in ShareScope] == ["usage", "control"]
    assert set(SHARE_SCOPE_DESCRIPTIONS) == set(ShareScope)
    assert [s.value for s in ShareUnavailability] == [
        "no_curve",
        "multi_outing_day",
        "no_profile",
    ]
    assert set(SHARE_UNAVAILABILITY_DESCRIPTIONS) == set(ShareUnavailability)
    members = list(Unavailability)
    no_curve = members.index(Unavailability.NO_CURVE)
    assert members[no_curve - 1] is Unavailability.NON_CONVERGENCE
    assert members[no_curve + 1] is Unavailability.MODEL_ERROR
    assert UNAVAILABILITY_DESCRIPTIONS[Unavailability.NO_CURVE].startswith(
        "sans courbe — "
    )


# --- Les contrats et leurs bornes ---------------------------------------------------


@pytest.mark.parametrize("share", [0.0, 1.0])
def test_a_share_at_its_bounds_is_accepted(share: float) -> None:
    assert curve_performance(share).out_of_support_share == share


def test_a_share_above_one_by_an_ulp_is_refused() -> None:
    with pytest.raises(ContractError, match=r"dans \[0 ; 1\]"):
        curve_performance(1.0000000000000002)


@pytest.mark.parametrize(
    ("changes", "fragment"),
    [
        ({"document": "x"}, "document doit être un sha256"),
        ({"curve_ref": "og2.csv#000000000000"}, "doit valoir '<nom>#0123456789ab'"),
        ({"curve_ref": "#0123456789ab"}, "doit valoir"),
        ({"curve_sha256": None}, "porte curve_sha256 et curve_ref"),
        ({"share_scope": None}, "porte son share_scope"),
        (
            {"out_of_support_share": None},
            "présente si et seulement si son motif d'indisponibilité est absent",
        ),
        (
            {"share_unavailability": ShareUnavailability.NO_PROFILE},
            "présente si et seulement si",
        ),
    ],
)
def test_rolling_performance_invariants(changes: dict[str, Any], fragment: str) -> None:
    with pytest.raises(ContractError, match=_escaped(fragment)):
        replace(curve_performance(), **changes)


def test_a_curve_without_share_has_a_reason() -> None:
    for reason in ShareUnavailability:
        if reason is ShareUnavailability.NO_CURVE:
            continue
        performance = replace(
            curve_performance(),
            out_of_support_share=None,
            share_scope=None,
            share_unavailability=reason,
        )
        assert performance.share_unavailability is reason


def test_without_curve_the_share_is_no_curve() -> None:
    with pytest.raises(ContractError, match="au motif no_curve"):
        replace(
            absent_performance(), share_unavailability=ShareUnavailability.NO_PROFILE
        )
    with pytest.raises(ContractError, match="ni curve_sha256 ni curve_ref"):
        replace(absent_performance(), curve_sha256=CSV_SHA)
    with pytest.raises(ContractError, match="demande le statut curve"):
        replace(
            no_read_performance(),
            out_of_support_share=0.1,
            share_scope=ShareScope.USAGE,
            share_unavailability=None,
        )


def _escaped(text: str) -> str:
    return re.escape(text)


@pytest.mark.parametrize(
    ("changes", "fragment"),
    [
        ({"window_days": 0}, "window_days : au moins 1 jour, reçu 0."),
        (
            {"command_windows": (28, 0, 56)},
            "command_windows : au moins 1 jour, reçu 0.",
        ),
        ({"command_windows": ()}, "command_windows ne doit pas être vide."),
        ({"command_windows": (28, 28, 56)}, "command_windows : 28 donnée deux fois."),
        ({"command_windows": (28, None)}, "command_windows doit contenir window_days"),
        ({"covered_threshold": 1.5}, "covered_threshold doit être dans [0 ; 1]"),
        ({"beyond_marker": -0.1}, "beyond_marker doit être dans [0 ; 1]"),
        ({"coverage_tolerance_s": -1.0}, "coverage_tolerance_s doit être >= 0"),
        ({"platform": ""}, "platform"),
        ({"rule": "x"}, "rule doit être un sha256"),
        ({"index_sha256": "x"}, "index_sha256 doit être un sha256"),
    ],
)
def test_rolling_declaration_invariants(changes: dict[str, Any], fragment: str) -> None:
    with pytest.raises(ContractError, match=_escaped(fragment)):
        rolling(**changes)


def test_rolling_declaration_bounds() -> None:
    assert rolling(window_days=1, command_windows=(1,)).window_days == 1
    assert rolling(window_days=None).window_days is None
    assert rolling(covered_threshold=0.0, beyond_marker=1.0).beyond_marker == 1.0


def test_calibration_terms_invariants() -> None:
    assert terms().model is ModelKind.V0_RECALIBRATED
    with pytest.raises(ContractError, match="observed_s doit être > 0"):
        CalibrationTerm(date(2026, 6, 1), 0.0, 1.0)
    with pytest.raises(ContractError, match="forecast_s doit être > 0"):
        CalibrationTerm(date(2026, 6, 1), 1.0, 0.0)
    term = CalibrationTerm(date(2026, 6, 1), 1.0, 1.0)
    with pytest.raises(ContractError, match="strictement croissant"):
        ScenarioClockTerms(Scenario.USAGE, CLOCKS[0], (term, term))
    usage = ScenarioClockTerms(Scenario.USAGE, CLOCKS[0], ())
    control = ScenarioClockTerms(Scenario.CONTROL, CLOCKS[0], ())
    with pytest.raises(ContractError, match="dans l'ordre des scénarios"):
        CalibrationTerms(ModelKind.V0_RECALIBRATED, (usage, usage))
    order = tuple(Scenario)
    first, second = sorted((usage, control), key=lambda s: order.index(s.scenario))
    assert CalibrationTerms(ModelKind.V0_RECALIBRATED, (first, second))
    with pytest.raises(ContractError, match="dans l'ordre des scénarios"):
        CalibrationTerms(ModelKind.V0_RECALIBRATED, (second, first))


def test_rolling_result_invariants() -> None:
    result = RollingResult(SHA_A, (SHA_B, SHA_C), (SHA_A, None))
    assert result.calibration_terms == (SHA_A, None)
    with pytest.raises(ContractError, match="un document par performance"):
        RollingResult(SHA_A, (SHA_B,), (SHA_A, None))
    with pytest.raises(ContractError, match="sha256"):
        RollingResult(SHA_A, ("x",), (None,))


def test_the_calibration_terms_round_trip_at_format_6() -> None:
    data = encode_document(terms(), 6)
    assert decode_document(data, CalibrationTerms, 6) == terms()
    with pytest.raises(TypeError):
        encode_document(terms(), 5)


# --- La DÉCLARATION ------------------------------------------------------------------


def test_a_rolling_declaration_has_no_declared_curve() -> None:
    declared = rolling_declaration()
    assert declared.curve_ref is None
    assert all(a.source.kind != "csv" for a in declared.artifacts)
    with pytest.raises(ContractError) as error:
        replace(declared, curve_ref=declaration().curve_ref)
    assert str(error.value) == (
        "le mode glissant n'a pas de courbe déclarée : curve_ref, curve et "
        "curve_metadata absents (0010, précision OG-2, D-P7)."
    )


def test_the_declared_curve_goes_together() -> None:
    with pytest.raises(ContractError) as error:
        declaration(curve_metadata=None)
    assert str(error.value) == (
        "curve_ref, curve et curve_metadata vont ensemble en mode « courbe déclarée » "
        "(0010 D2.6)."
    )


def test_a_rolling_declaration_refuses_an_experiment() -> None:
    with pytest.raises(ContractError) as error:
        rolling_declaration(experiment=experiment(), models=CALIBRATED_MODELS)
    assert str(error.value) == (
        "une expérience d'admission n'existe pas en mode glissant : hors du jalon "
        "(0010 D10, précision OG-2)."
    )


def test_a_rolling_declaration_has_one_entry_per_performance() -> None:
    extra = rolling(
        performances=(*rolling().performances, curve_performance()),
    )
    with pytest.raises(ContractError) as error:
        declaration(curve_ref=None, curve=None, curve_metadata=None, rolling=extra)
    assert (
        str(error.value) == "rolling : une entrée par performance attendue (3), reçu 4."
    )


def _lines(root: Path) -> list[bytes]:
    return (root / EVENTS_FILE).read_bytes().split(b"\n")[:-1]


def test_a_declared_mode_declaration_at_format_6(tmp_path: Path) -> None:
    """Les trois clés neuves à vide, à leurs places ; le reste celui d'aujourd'hui."""
    root = registry_root(tmp_path)
    append_declaration(root, declaration(), recorded_at=at(0))
    (line,) = _lines(root)
    data = json.loads(line)
    assert data["format_version"] == 6
    assert data["declaration"]["rolling"] is None
    assert list(data["declaration"])[-1] == "rolling"
    for declared in data["declaration"]["performances"]:
        for outing in declared["performance"]["outings"]:
            assert outing["activity_refs"] == []
            assert list(outing)[-1] == "activity_refs"


def test_a_rolling_declaration_line_reads_back_at_bit(tmp_path: Path) -> None:
    root = registry_root(tmp_path)
    written = append_declaration(root, rolling_declaration(), recorded_at=at(0))
    (line,) = _lines(root)
    log = read_registry(root)
    assert log.events[0] == written
    assert log.events[0].declaration == rolling_declaration()
    assert line_hash(log.events[0]) == hashlib.sha256(line).hexdigest()


# --- Les lignes anciennes ------------------------------------------------------------


def _at_format(root: Path, version: int) -> bytes:
    """La DÉCLARATION écrite au format 6, réécrite au format ``version`` comme le
    registre l'écrit à ce format (sans les clés qu'il ne connaît pas)."""
    (event,) = read_registry(root).events
    line = _line(replace(event, format_version=version))
    (root / EVENTS_FILE).write_bytes(line + b"\n")
    return line


@pytest.mark.parametrize("version", [1, 2, 3, 4, 5])
def test_lines_of_formats_1_to_5_rewrite_to_the_byte(
    tmp_path: Path, version: int
) -> None:
    root = registry_root(tmp_path)
    append_declaration(root, declaration(), recorded_at=at(0))
    line = _at_format(root, version)
    assert b'"rolling"' not in line
    assert b'"activity_refs"' not in line
    (event,) = read_registry(root).events
    assert event.format_version == version
    assert _line(event) == line
    assert event.declaration == declaration()


def test_a_format_5_declaration_has_no_rolling_key(tmp_path: Path) -> None:
    root = registry_root(tmp_path)
    append_declaration(root, declaration(), recorded_at=at(0))
    data = json.loads(_at_format(root, 5))
    assert "rolling" not in data["declaration"]
    assert "rolling" not in json.dumps(data)


@pytest.mark.parametrize(
    ("place", "message"),
    [
        ("declaration", "declaration : champ inconnu au format 5 : 'rolling'"),
        ("outing", "declaration : champ inconnu au format 5 : 'activity_refs'"),
    ],
)
def test_a_format_5_line_carrying_a_new_key_is_refused(
    tmp_path: Path, place: str, message: str
) -> None:
    root = registry_root(tmp_path)
    append_declaration(root, declaration(), recorded_at=at(0))
    data = json.loads(_at_format(root, 5))
    if place == "declaration":
        data["declaration"]["rolling"] = None
    else:
        data["declaration"]["performances"][0]["performance"]["outings"][0][
            "activity_refs"
        ] = []
    (root / EVENTS_FILE).write_bytes(canonical_bytes(data) + b"\n")
    with pytest.raises(RegistryError, match=_escaped(message)):
        read_registry(root)


def test_a_format_5_result_carrying_rolling_is_refused() -> None:
    raw = {"format_version": 5, "result": {"outings": [], "rolling": None}}
    with pytest.raises(
        ValueError, match="result : champ inconnu au format 5 : 'rolling'"
    ):
        _upgraded(raw)


def test_a_rolling_result_round_trips_in_an_event() -> None:
    result = Result((), (), (), rolling=RollingResult(SHA_A, (SHA_B,), (None,)))
    event = RegistryEvent(
        format_version=6,
        number=2,
        kind=EventKind.RESULT,
        recorded_at=at(1),
        previous_hash=SHA_C,
        answers=1,
        corrects=None,
        correction_reason=None,
        declaration=None,
        result=result,
        failure=None,
    )
    assert decode_contract(RegistryEvent, encode_contract(event)) == event
