"""Le document de règle, la courbe figée, la courbe absente (OG-2, § 6.4 du brief
OG-2) : ``freeze_companion``, ``origin_absence_document``, ``RollingRule``,
``FrozenCurve``, ``AbsentCurve``.

Sur la saison synthétique de ``tests/test_og1_origin.py`` (huit trails ``s0`` à ``s7``
partis les 20 à 27 mars 2024 à 08:00 UTC, sans écoulé d'index, une heure
d'enregistrement ; ``apres``, parti le 2 avril). Les cas A3 et « 56 jours qui
contiennent tout le passé » sur la commande sont dans ``test_og2_rolling.py``."""

from __future__ import annotations

import hashlib
import json
from typing import Any

import pytest

from fixtures.processed import COMMIT
from mountain_perf.backtest import CodecError, decode_document, encode_document
from mountain_perf.estimation.curve import (
    CURVE_ESTIMATION_PARAMETER_SPECS,
    BinValue,
)
from mountain_perf.estimation.origin import (
    NO_CANDIDATE,
    estimate_at_origin,
    origin_absence_document,
    origin_companion,
)
from mountain_perf.model.curve_io import (
    CURVE_PARAMETER_SPECS,
    curve_documents,
    freeze_companion,
    read_curve_documents,
)
from mountain_perf.schemas import (
    AbsentCurve,
    FrozenCurve,
    ParameterSet,
    RollingRule,
    Sport,
)
from mountain_perf.validation import ContractError
from test_estimation_curve import DEFAULTS
from test_og1_cli_at import NOW
from test_og1_origin import (
    ORIGIN,
    PROFILE,
    SHA,
    _season,
    at,
    corpus,
    origin_selection,
    rule,
)
from test_og1b_coutures import same_curve

READ = ParameterSet(CURVE_PARAMETER_SPECS)
NAME = "og2-2024-04-08-w56.csv"


def _documents() -> tuple[bytes, bytes]:
    season = corpus(_season())
    result = rule(season)
    provenance, document = origin_companion(
        result,
        season,
        origin_selection(),
        DEFAULTS,
        PROFILE,
        commit=COMMIT,
        generated_at=NOW,
    )
    documents = curve_documents(result.rows, Sport.FOOT, provenance, document)
    return documents.csv, documents.companion


def test_the_frozen_companion_lacks_two_keys() -> None:
    """Le compagnon figé : les octets du compagnon sans la ligne de ``generated_at`` ni
    celle de ``estimation.commit`` ; le reste à l'octet."""
    _, companion = _documents()
    lines = companion.decode("utf-8").split("\n")
    generated = '  "generated_at": "2024-04-01T12:00:00+00:00",'
    commit = f'    "commit": "{COMMIT}",'
    assert lines.count(generated) == 1
    assert lines.count(commit) == 1
    expected = [line for line in lines if line not in (generated, commit)]
    assert freeze_companion(companion) == "\n".join(expected).encode("utf-8")
    frozen = json.loads(freeze_companion(companion))
    assert "generated_at" not in frozen
    assert "commit" not in frozen["estimation"]


def test_the_frozen_companion_reads_as_the_same_curve() -> None:
    csv, companion = _documents()
    frozen = freeze_companion(companion)
    plain = read_curve_documents(csv, companion, NAME, READ)
    again = read_curve_documents(csv, frozen, NAME, READ, generated_at=NOW)
    same_curve(again, plain)
    assert again.curve_ref == plain.curve_ref
    assert again.curve_ref.startswith(f"{NAME}#")


@pytest.mark.parametrize("key", ["generated_at", "commit"])
def test_a_companion_without_the_keys_is_refused(key: str) -> None:
    _, companion = _documents()
    document = json.loads(companion)
    if key == "generated_at":
        del document["generated_at"]
    else:
        del document["estimation"]["commit"]
    with pytest.raises(ContractError) as error:
        freeze_companion(json.dumps(document).encode("utf-8"))
    assert str(error.value) == (
        "companion : un compagnon de curve_documents attendu, avec « generated_at » et "
        "« estimation.commit »."
    )


# --- La courbe absente --------------------------------------------------------------


def _fin_inferee(day: int, decision: str, fate: str | None) -> dict[str, Any]:
    start = f"2024-03-{day}T08:00:00+00:00"
    end = f"2024-03-{day}T09:00:00+00:00"
    return {
        "activity_ref": f"s{day - 20}",
        "decision": decision,
        "method": "fin inférée",
        "index_start": start,
        "index_end": None,
        "recording_start": start,
        "recording_end": end,
        "safe_end": end,
        "recording_sha256": SHA,
        "fate": fate,
        "contributes": False,
    }


APRES = {
    "activity_ref": "apres",
    "decision": "finie à l'origine ou après",
    "method": "index seul",
    "index_start": "2024-04-02T08:00:00+00:00",
    "index_end": "2024-04-02T09:00:00+00:00",
    "recording_start": None,
    "recording_end": None,
    "safe_end": None,
    "recording_sha256": None,
    "fate": None,
    "contributes": False,
}
HISTORY = {
    "foot_index_finished": 0,
    "foot_without_index_elapsed": 8,
    "selected_index_finished": 0,
    "selected_without_index_elapsed": 8,
}


def _text(document: dict[str, Any]) -> bytes:
    return (json.dumps(document, ensure_ascii=False, indent=2) + "\n").encode("utf-8")


def test_g5_an_absence_without_candidate_in_full() -> None:
    season = corpus(_season())
    result = rule(season, window=1, support_threshold_min=12.5)
    expected = {
        "athlete_ref": "x",
        "outcome": "absence",
        "absence_reason": NO_CANDIDATE,
        "support_threshold_min": 12.5,
        "origin": {
            "origin": "2024-03-31T22:00:00+00:00",
            "window": 1,
            "lower_bound": "2024-03-30T23:00:00+00:00",
            "outcome": "absence",
            "index_sha256": "b" * 64,
            "data_available_at": None,
            "last_retained_end": None,
            "history": HISTORY,
            "activities": [
                *(
                    _fin_inferee(day, "finie avant la fenêtre", None)
                    for day in range(20, 28)
                ),
                APRES,
            ],
        },
    }
    assert origin_absence_document(result, season) == _text(expected)


def test_g6_an_absence_with_retained_candidates_in_full() -> None:
    season = corpus(_season())
    parameters = ParameterSet(
        CURVE_ESTIMATION_PARAMETER_SPECS, {"median_min_moving_s": 3600.0}
    )
    result = estimate_at_origin(
        season,
        "x",
        ORIGIN,
        56,
        origin_selection(value=BinValue.MEDIAN),
        parameters,
        PROFILE,
    )
    assert result.absence_reason is not None
    assert result.absence_reason.startswith("Aucune tranche estimée")
    expected = {
        "athlete_ref": "x",
        "outcome": "absence",
        "absence_reason": result.absence_reason,
        "support_threshold_min": 10.0,
        "origin": {
            "origin": "2024-03-31T22:00:00+00:00",
            "window": 56,
            "lower_bound": "2024-02-04T23:00:00+00:00",
            "outcome": "absence",
            "index_sha256": "b" * 64,
            "data_available_at": "2024-03-27T09:00:00+00:00",
            "last_retained_end": "2024-03-27T09:00:00+00:00",
            "history": HISTORY,
            "activities": [
                *(_fin_inferee(day, "candidate", "retenue") for day in range(20, 28)),
                APRES,
            ],
        },
    }
    assert origin_absence_document(result, season) == _text(expected)


def test_a_curve_is_not_an_absence() -> None:
    season = corpus(_season())
    with pytest.raises(ContractError) as error:
        origin_absence_document(rule(season), season)
    assert str(error.value) == "result : une courbe n'est pas une absence."


def test_the_absence_of_another_athlete_is_refused() -> None:
    season = corpus(_season())
    result = rule(season, window=1)
    other = corpus(_season(), athlete="y")
    with pytest.raises(ContractError) as error:
        origin_absence_document(result, other)
    assert str(error.value) == (
        "corpus : celui de 'y', la règle a été rendue pour 'x'."
    )
    assert at(30, 23) == result.lower_bound


# --- Les trois contrats --------------------------------------------------------------


def rolling_rule(**changes: Any) -> RollingRule:
    fields: dict[str, Any] = {
        "athlete_ref": "x",
        "commit": COMMIT,
        "window_days": 56,
        "source_activity_types": ("trail_running",),
        "min_duration_s": None,
        "max_duration_s": None,
        "max_elapsed_s": None,
        "hr_center_bpm": None,
        "value": "somme",
        "parameters": dict(DEFAULTS.values),
        "profile_parameters": dict(PROFILE.values),
        "diagnostic_support_threshold_min": 10.0,
    }
    fields.update(changes)
    return RollingRule(**fields)


def frozen_curve() -> FrozenCurve:
    csv, companion = _documents()
    return FrozenCurve(csv.decode("utf-8"), freeze_companion(companion).decode("utf-8"))


def absent_curve() -> AbsentCurve:
    season = corpus(_season())
    return AbsentCurve(
        origin_absence_document(rule(season, window=1), season).decode("utf-8")
    )


@pytest.mark.parametrize("build", [rolling_rule, frozen_curve, absent_curve])
def test_the_documents_round_trip_at_format_6(build: Any) -> None:
    value = build()
    data = encode_document(value, 6)
    assert data.startswith(f'{{"type":"{type(value).__name__}","format":6,'.encode())
    assert decode_document(data, type(value), 6) == value


@pytest.mark.parametrize("build", [rolling_rule, frozen_curve, absent_curve])
def test_the_documents_are_refused_at_format_5(build: Any) -> None:
    value = build()
    with pytest.raises(TypeError, match="n'existe qu'à partir du format 6"):
        encode_document(value, 5)
    data = encode_document(value, 6).replace(b'"format":6', b'"format":5')
    with pytest.raises(CodecError, match="qui ne le connaît pas"):
        decode_document(data, type(value), 5)


def test_the_frozen_curve_names_its_csv() -> None:
    curve = frozen_curve()
    csv, _ = _documents()
    assert curve.csv_sha256 == hashlib.sha256(csv).hexdigest()


@pytest.mark.parametrize(
    ("changes", "message"),
    [
        ({"athlete_ref": ""}, "athlete_ref"),
        ({"window_days": 0}, "window_days doit valoir au moins 1, reçu 0."),
        ({"source_activity_types": ()}, "source_activity_types ne doit pas être vide."),
        (
            {"source_activity_types": ("b", "a")},
            "source_activity_types : des types triés et distincts attendus.",
        ),
        (
            {"source_activity_types": ("a", "a")},
            "source_activity_types : des types triés et distincts attendus.",
        ),
        ({"value": "moyenne"}, "value : l'une de ['somme', 'médiane'] attendue"),
        ({"min_duration_s": -1.0}, "min_duration_s doit être >= 0, reçu -1.0."),
        ({"max_elapsed_s": float("inf")}, "max_elapsed_s"),
        (
            {"diagnostic_support_threshold_min": 1441.0},
            "diagnostic_support_threshold_min doit être dans [0.0 ; 1440.0]",
        ),
    ],
)
def test_the_rolling_rule_invariants(changes: dict[str, Any], message: str) -> None:
    with pytest.raises(ContractError) as error:
        rolling_rule(**changes)
    assert message in str(error.value)


def test_the_rolling_rule_bounds() -> None:
    assert rolling_rule(window_days=1).window_days == 1
    assert rolling_rule(window_days=None).window_days is None
    assert rolling_rule(value="médiane").value == "médiane"
    assert rolling_rule(diagnostic_support_threshold_min=0.0)


def test_a_frozen_curve_carries_no_instant() -> None:
    csv, companion = _documents()
    with pytest.raises(ContractError, match="ne porte pas la clé « generated_at »"):
        FrozenCurve(csv.decode("utf-8"), companion.decode("utf-8"))
    with pytest.raises(ContractError):
        FrozenCurve("", "{}")
    with pytest.raises(ContractError, match="un objet JSON attendu"):
        FrozenCurve("x", "[]")
    with pytest.raises(ContractError):
        AbsentCurve("")


def test_a_null_generated_at_counts_as_carried() -> None:
    """Une clé à ``null`` est portée (C3 d'OG-1b) : refusée comme la clé pleine."""
    with pytest.raises(ContractError, match="« generated_at »"):
        FrozenCurve("x", '{"generated_at": null}')
