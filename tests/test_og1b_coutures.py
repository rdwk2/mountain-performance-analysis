"""Les coutures de la règle à l'origine (OG-1b, ``docs/decisions/0020``, précision
OG-1b) : le fournisseur des intervalles, le compagnon en fonctions pures, la lecture
d'une courbe depuis ses octets. Jours, heures et activités inventés (règle 1) ; aucun
comportement ne change, les valeurs attendues sont écrites en dur."""

from __future__ import annotations

import dataclasses
import hashlib
import math
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from fixtures.processed import COMMIT
from mountain_perf import cli, gitstate
from mountain_perf.config import data_dir
from mountain_perf.estimation import origin as origin_module
from mountain_perf.estimation.curve import (
    CURVE_ESTIMATION_PARAMETER_SPECS,
    BinValue,
    CurveSelection,
)
from mountain_perf.estimation.intervals import (
    ActivityIntervals,
    TraceRefusal,
    activity_intervals,
)
from mountain_perf.estimation.origin import (
    NO_CANDIDATE,
    IntervalsOf,
    OriginOutcome,
    OriginWindow,
    estimate_at_origin,
    origin_companion,
)
from mountain_perf.gitstate import GitState
from mountain_perf.gpx.profile import PROFILE_PARAMETER_SPECS
from mountain_perf.model.curve_io import CurveError, curve_documents, write_curve
from mountain_perf.runs import load_curve_corpus
from mountain_perf.schemas import ActivityRecording, ParameterSet, Sport
from mountain_perf.validation import ContractError
from test_estimation_curve import DEFAULTS
from test_model_curve_io_extended import ESTIMATION, PROVENANCE, ROWS
from test_og1_cli_at import (
    AT,
    EXPORTS,
    NOW,
    ORIGIN_0325,
    RANGE,
    companion,
    run,
    write_aligned,
)
from test_og1_origin import (
    ORIGIN,
    PROFILE,
    TRAIL,
    _season,
    corpus,
    origin_selection,
    rule,
)

NO_CANDIDATE_ORIGIN = datetime(2024, 3, 19, 23, tzinfo=UTC)
"""00:00 à Paris le 2024-03-20 : aucune candidate sur ``_season()``."""

Call = tuple[str, ParameterSet, dict[str, Any]]


def recorder(calls: list[Call]) -> IntervalsOf:
    """Un fournisseur qui note chaque appel, puis délègue à
    ``activity_intervals``."""

    def provider(
        recording: ActivityRecording, profile: ParameterSet, **options: Any
    ) -> ActivityIntervals | TraceRefusal:
        calls.append((recording.activity_ref, profile, dict(options)))
        return activity_intervals(recording, profile, **options)

    return provider


# --- Section 1 : le fournisseur des intervalles (commit 1) -------------------------


def test_un_fournisseur_recoit_les_candidates_et_les_parametres_de_la_regle() -> None:
    parameters = ParameterSet(
        CURVE_ESTIMATION_PARAMETER_SPECS, {"hr_lag_s": 30.0, "hr_min_coverage": 0.5}
    )
    chosen = origin_selection(max_elapsed_s=1800.0)
    calls: list[Call] = []
    result = estimate_at_origin(
        corpus(_season()),
        "x",
        ORIGIN,
        56,
        chosen,
        parameters,
        PROFILE,
        intervals_of=recorder(calls),
    )
    assert len(calls) == 8
    assert [ref for ref, _, _ in calls] == [f"s{k}" for k in range(8)]
    for _, profile, options in calls:
        assert profile is PROFILE
        assert options == {
            "hr_lag_s": 30.0,
            "hr_min_coverage": 0.5,
            "max_elapsed_s": 1800.0,
        }
    assert result.outcome is OriginOutcome.NOT_PROJECTABLE
    assert result == estimate_at_origin(
        corpus(_season()), "x", ORIGIN, 56, chosen, parameters, PROFILE
    )


def test_sans_fournisseur_activity_intervals_du_module_lu_a_l_appel(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[Call] = []
    monkeypatch.setattr(origin_module, "activity_intervals", recorder(calls))
    rule(corpus(_season()))
    assert len(calls) == 8


def test_un_fournisseur_remplace_activity_intervals(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    expected = rule(corpus(_season()))

    def forbidden(*args: Any, **options: Any) -> Any:
        raise AssertionError("activity_intervals du module appelée")

    monkeypatch.setattr(origin_module, "activity_intervals", forbidden)
    result = estimate_at_origin(
        corpus(_season()),
        "x",
        ORIGIN,
        56,
        origin_selection(),
        DEFAULTS,
        PROFILE,
        support_threshold_min=10.0,
        intervals_of=activity_intervals,
    )
    assert result == expected


def test_sans_candidate_le_fournisseur_n_est_pas_appele() -> None:
    calls: list[Call] = []
    result = estimate_at_origin(
        corpus(_season()),
        "x",
        NO_CANDIDATE_ORIGIN,
        56,
        origin_selection(),
        DEFAULTS,
        PROFILE,
        intervals_of=recorder(calls),
    )
    assert result.outcome is OriginOutcome.ABSENT
    assert result.absence_reason == NO_CANDIDATE
    assert calls == []


# --- Section 2 : le compagnon en fonctions pures (commit 2) ------------------------


@pytest.fixture
def fixed_world(monkeypatch: pytest.MonkeyPatch) -> None:
    """Un clone propre au commit des fixtures, l'horloge à :data:`NOW` (celle de
    ``test_og1_cli_at.py``, sans ``autouse``)."""
    monkeypatch.setattr(
        gitstate, "git_state", lambda directory: GitState(COMMIT, False)
    )
    monkeypatch.setattr(cli, "_now", lambda: NOW)


KEYS = [
    "sport",
    "activity_count",
    "hr_center_bpm",
    "hr_width_bpm",
    "hr_lag_s",
    "date_from",
    "date_to",
    "source_activity_types",
    "min_duration_s",
    "max_duration_s",
    "max_elapsed_s",
    "diagnostic_support_threshold_min",
    "athlete_ref",
    "estimator",
    "generated_at",
    "estimation",
]
"""Les clés du compagnon, dans l'ordre."""

DEFAULT_PROFILE = {
    "grid_step_m": 50,
    "smoothing_window_m": 150,
    "point_match_max_offset_m": 150,
    "point_match_min_separation_m": 500,
}
"""Le profil aux défauts, que la commande ne change jamais."""

ALL_HR = [
    "--window",
    "all",
    "--hr-center",
    "140",
    "--hr-width",
    "20",
    "--hr-lag",
    "30",
    "--max-elapsed-min",
    "30",
    "--min-duration-min",
    "1",
    "--max-duration-min",
    "600",
    "--value",
    "b",
    "--min-support-min",
    "5",
]

ORIGIN_DEFAULTS: dict[str, Any] = {
    "sport": "foot",
    "activity_count": 1,
    "hr_center_bpm": None,
    "hr_width_bpm": None,
    "hr_lag_s": None,
    "date_from": "2024-03-09",
    "date_to": "2024-03-09",
    "source_activity_types": ["trail_running"],
    "min_duration_s": None,
    "max_duration_s": None,
    "max_elapsed_s": None,
    "diagnostic_support_threshold_min": 10.0,
    "athlete_ref": "x",
    "estimator": (
        "mperf curve --at (OG-1) : règle à l'origine, fenêtre 56 jours ; intervalles "
        "de la grille du profil, temps M θc, tranches variables, valeur somme"
    ),
    "generated_at": "2024-04-01T12:00:00+00:00",
}
ORIGIN_ALL_HR: dict[str, Any] = {
    **ORIGIN_DEFAULTS,
    "hr_center_bpm": 140.0,
    "hr_width_bpm": 20.0,
    "hr_lag_s": 30.0,
    "min_duration_s": 60.0,
    "max_duration_s": 36000.0,
    "max_elapsed_s": 1800.0,
    "diagnostic_support_threshold_min": 5.0,
    "estimator": (
        "mperf curve --at (OG-1) : règle à l'origine, fenêtre all ; intervalles "
        "de la grille du profil, temps M θc, tranches variables, valeur médiane"
    ),
}


@pytest.mark.usefixtures("fixed_world")
@pytest.mark.parametrize(
    ("options", "top", "estimation"),
    [
        pytest.param(
            [],
            ORIGIN_DEFAULTS,
            {
                "value": "somme",
                "hr_width_bpm": 10.0,
                "hr_lag_s": 60.0,
                "window": 56,
                "lower_bound": "2024-01-21T23:00:00+00:00",
            },
            id="defauts",
        ),
        pytest.param(
            ALL_HR,
            ORIGIN_ALL_HR,
            {
                "value": "médiane",
                "hr_width_bpm": 20.0,
                "hr_lag_s": 30.0,
                "window": "all",
                "lower_bound": None,
            },
            id="tout_fc",
        ),
    ],
)
def test_le_compagnon_a_l_origine_en_dur(
    capsys: pytest.CaptureFixture[str],
    options: list[str],
    top: dict[str, Any],
    estimation: dict[str, Any],
) -> None:
    write_aligned(data_dir())
    assert run(capsys, *AT, *options)[0] == 0
    meta = companion()
    assert list(meta) == KEYS
    assert {key: meta[key] for key in KEYS[:-1]} == top
    document = meta["estimation"]
    assert document["mode"] == "origine"
    assert document["commit"] == COMMIT
    assert document["value"] == estimation["value"]
    assert document["parameters"]["hr_width_bpm"] == estimation["hr_width_bpm"]
    assert document["parameters"]["hr_lag_s"] == estimation["hr_lag_s"]
    assert document["exports_retrieved_at"] == EXPORTS
    assert document["projectable"] is True
    assert document["support_error"] is None
    assert document["support_grade_range"] == [-0.0125, 0.0125]
    assert document["origin"]["window"] == estimation["window"]
    assert document["origin"]["lower_bound"] == estimation["lower_bound"]
    assert document["profile_parameters"] == DEFAULT_PROFILE


RANGE_DEFAULTS: dict[str, Any] = {
    **ORIGIN_DEFAULTS,
    "date_from": "2024-03-01",
    "date_to": "2024-03-31",
    "estimator": (
        "mperf curve (M6b) : intervalles de la grille du profil, temps M θc, "
        "tranches variables, valeur somme"
    ),
}
RANGE_HR: dict[str, Any] = {
    **RANGE_DEFAULTS,
    "hr_center_bpm": 140.0,
    "hr_width_bpm": 20.0,
    "hr_lag_s": 30.0,
    "min_duration_s": 60.0,
    "max_duration_s": 36000.0,
    "max_elapsed_s": 1800.0,
}


@pytest.mark.usefixtures("fixed_world")
@pytest.mark.parametrize(
    ("options", "top"),
    [
        pytest.param([], RANGE_DEFAULTS, id="defauts"),
        pytest.param(ALL_HR[2:14], RANGE_HR, id="fc"),
    ],
)
def test_la_provenance_d_une_plage_en_dur(
    capsys: pytest.CaptureFixture[str], options: list[str], top: dict[str, Any]
) -> None:
    write_aligned(data_dir())
    assert run(capsys, *RANGE, *options)[0] == 0
    meta = companion()
    assert list(meta) == KEYS
    assert {key: meta[key] for key in KEYS[:-1]} == top
    assert meta["estimation"]["mode"] == "plage"
    assert meta["estimation"]["origin"] is None


@pytest.mark.usefixtures("fixed_world")
@pytest.mark.parametrize(
    ("options", "window", "chosen", "values", "threshold"),
    [
        pytest.param([], 56, origin_selection(), {}, 10.0, id="defauts"),
        pytest.param(
            ALL_HR,
            "all",
            CurveSelection(
                TRAIL, None, None, 60.0, 36000.0, 1800.0, 140.0, BinValue.MEDIAN
            ),
            {"hr_width_bpm": 20.0, "hr_lag_s": 30.0},
            5.0,
            id="tout_fc",
        ),
    ],
)
def test_origin_companion_rend_ce_que_la_commande_ecrit(
    capsys: pytest.CaptureFixture[str],
    options: list[str],
    window: OriginWindow,
    chosen: CurveSelection,
    values: dict[str, float],
    threshold: float,
) -> None:
    folder = data_dir()
    write_aligned(folder)
    assert run(capsys, *AT, *options)[0] == 0
    season = load_curve_corpus(folder, "x", TRAIL, ORIGIN_0325, window)
    parameters = ParameterSet(CURVE_ESTIMATION_PARAMETER_SPECS, values)
    profile = ParameterSet(PROFILE_PARAMETER_SPECS)
    result = estimate_at_origin(
        season,
        "x",
        ORIGIN_0325,
        window,
        chosen,
        parameters,
        profile,
        support_threshold_min=threshold,
    )
    documents = curve_documents(
        result.rows,
        Sport.FOOT,
        *origin_companion(
            result,
            season,
            chosen,
            parameters,
            profile,
            commit=COMMIT,
            generated_at=NOW,
        ),
    )
    reference = folder / "reference"
    assert documents.csv == (reference / "origine.csv").read_bytes()
    assert documents.companion == (reference / "origine.meta.json").read_bytes()


def test_avec_un_cache_les_memes_documents() -> None:
    season = corpus(_season())
    store: dict[tuple[str, tuple[tuple[str, Any], ...]], Any] = {}
    calls: list[str] = []
    delegated: list[str] = []

    def cached(
        recording: ActivityRecording, profile: ParameterSet, **options: Any
    ) -> ActivityIntervals | TraceRefusal:
        calls.append(recording.activity_ref)
        key = (recording.activity_ref, tuple(sorted(options.items())))
        if key not in store:
            delegated.append(recording.activity_ref)
            store[key] = activity_intervals(recording, profile, **options)
        found: ActivityIntervals | TraceRefusal = store[key]
        return found

    cases: list[tuple[datetime, OriginWindow]] = [
        (ORIGIN, 56),
        (ORIGIN, 28),
        (ORIGIN, "all"),
        (datetime(2024, 3, 24, 23, tzinfo=UTC), 56),
        (datetime(2024, 3, 20, 23, tzinfo=UTC), 56),
    ]
    for moment, window in cases:
        plain = rule(season, origin=moment, window=window)
        with_cache = estimate_at_origin(
            season,
            "x",
            moment,
            window,
            origin_selection(),
            DEFAULTS,
            PROFILE,
            support_threshold_min=10.0,
            intervals_of=cached,
        )
        outputs = [
            curve_documents(
                result.rows,
                Sport.FOOT,
                *origin_companion(
                    result,
                    season,
                    origin_selection(),
                    DEFAULTS,
                    PROFILE,
                    commit=COMMIT,
                    generated_at=NOW,
                ),
            )
            for result in (plain, with_cache)
        ]
        assert outputs[0] == outputs[1]
    assert len(calls) == 30
    assert delegated == [f"s{k}" for k in range(8)]


def test_une_absence_n_a_pas_de_compagnon() -> None:
    season = corpus(_season())
    result = rule(season, origin=NO_CANDIDATE_ORIGIN)
    with pytest.raises(ContractError) as error:
        origin_companion(
            result,
            season,
            origin_selection(),
            DEFAULTS,
            PROFILE,
            commit=COMMIT,
            generated_at=NOW,
        )
    assert str(error.value) == "result : une absence n'a pas de compagnon."


def test_le_compagnon_porte_le_profil_donne() -> None:
    profile = ParameterSet(PROFILE_PARAMETER_SPECS, {"grid_step_m": 25})
    season = corpus(_season())
    result = estimate_at_origin(
        season, "x", ORIGIN, 56, origin_selection(), DEFAULTS, profile
    )
    assert result.estimate is not None
    _, document = origin_companion(
        result,
        season,
        origin_selection(),
        DEFAULTS,
        profile,
        commit=COMMIT,
        generated_at=NOW,
    )
    assert document["profile_parameters"] == {**DEFAULT_PROFILE, "grid_step_m": 25}


def test_le_corpus_d_un_autre_athlete_est_refuse() -> None:
    result = rule(corpus(_season()))
    with pytest.raises(ContractError) as error:
        origin_companion(
            result,
            corpus(_season(), athlete="y"),
            origin_selection(),
            DEFAULTS,
            PROFILE,
            commit=COMMIT,
            generated_at=NOW,
        )
    assert str(error.value) == (
        "corpus : celui de 'y', la règle a été rendue pour 'x'."
    )


ROWS_CSV = (
    "grade_pct,kmh,hr,vam_mh,time_min,kmh_elapsed,activities,shape_iqr\n"
    "-12.5,9.0,128.25,-1125.0,30.0,8.1,6,0.125\n"
    "-1.25,10.8,,-135.00000000000003,45.5,9.9,7,\n"
    "1.25,9.9,140.0,123.75000000000001,60.0,9.0,7,0.0625\n"
    "13.75,3.6,150.5,495.00000000000006,25.0,3.15,5,\n"
)
"""Le CSV de ``ROWS``, octet pour octet."""


def test_curve_documents_en_dur() -> None:
    documents = curve_documents(ROWS, Sport.FOOT, PROVENANCE, ESTIMATION)
    assert hashlib.sha256(documents.csv).hexdigest() == (
        "391b1dd485029307c6a491b00ec1277cb8522e0ee10362c6187eaae5f50f1827"
    )
    assert len(documents.companion) == 611
    assert hashlib.sha256(documents.companion).hexdigest() == (
        "4df333c0a33934649535a65eace262f25cc2350ef663f20d078a740c972251c1"
    )
    assert documents.csv.decode("utf-8") == ROWS_CSV


def test_write_curve_ecrit_les_octets_de_curve_documents(tmp_path: Path) -> None:
    write_curve(tmp_path / "k.csv", ROWS, Sport.FOOT, PROVENANCE, ESTIMATION)
    documents = curve_documents(ROWS, Sport.FOOT, PROVENANCE, ESTIMATION)
    assert (tmp_path / "k.csv").read_bytes() == documents.csv
    assert (tmp_path / "k.meta.json").read_bytes() == documents.companion


def test_write_curve_refuse_d_abord_un_fichier_existant(tmp_path: Path) -> None:
    (tmp_path / "k.csv").write_bytes(b"deja")
    with pytest.raises(CurveError) as error:
        write_curve(
            tmp_path / "k.csv",
            ROWS,
            Sport.FOOT,
            PROVENANCE,
            {"level": {"p10": math.nan}},
        )
    assert str(error.value) == "k.csv existe déjà : une courbe n'est jamais réécrite."


def test_curve_documents_le_compagnon_d_abord() -> None:
    rows = (dataclasses.replace(ROWS[0], grade_pct="abc"), *ROWS[1:])
    with pytest.raises(ValueError, match="could not convert") as error:
        curve_documents(rows, Sport.FOOT, PROVENANCE, ESTIMATION)
    assert str(error.value) == "could not convert string to float: 'abc'"
    with pytest.raises(ValueError, match="JSON compliant"):
        curve_documents(rows, Sport.FOOT, PROVENANCE, {"level": {"p10": math.nan}})
