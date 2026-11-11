"""Garanties d'OG-1 que la suite ne tenait pas (relecture C de la PR #41).

Entrées plausibles du réel, construites par objets, passées à la règle, au chargement,
puis à la commande : le filtre ``has_recording`` et les bornes exactes du chargement,
les classes gelées, les instants à la microseconde, l'ordre des clés du compagnon, une
absence et son document, les ordres de contrôle, les classes d'erreur de la commande.
"""

from __future__ import annotations

import dataclasses
import json
from collections import Counter
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

import mountain_perf.estimation.origin as origin_module
import mountain_perf.ingest.interim as interim_module
import mountain_perf.runs as runs_module
from fixtures.montees import recording as montee
from fixtures.processed import COMMIT
from mountain_perf import cli, gitstate
from mountain_perf.backtest.calendar import origin as calendar_origin
from mountain_perf.cli import main
from mountain_perf.config import data_dir
from mountain_perf.estimation.curve import ActivityFate, NoCurve
from mountain_perf.estimation.intervals import ActivityIntervals, CurveInterval
from mountain_perf.estimation.origin import (
    ActivityEnd,
    CurveCorpus,
    Inspection,
    OriginEstimate,
    OriginHistory,
    TemporalDecision,
    check_origin,
    estimate_at_origin,
    origin_document,
    select_at_origin,
    window_lower_bound,
)
from mountain_perf.gitstate import GitState
from mountain_perf.ingest.interim import write_activities
from mountain_perf.runs import load_curve_corpus
from mountain_perf.schemas import (
    ActivityIndex,
    RecordingSession,
    TimerEvent,
    TimerEventType,
)
from mountain_perf.validation import ContractError
from test_estimation_curve import DEFAULTS
from test_ingest_interim import REPORT
from test_og1_origin import (
    ORIGIN,
    PROFILE,
    SHA,
    TRAIL,
    _season,
    activity_pair,
    at,
    corpus,
    origin_selection,
    rule,
)
from test_schemas_interim import SOURCE, entry
from test_schemas_interim import recording as bare_recording

NOW = datetime(2024, 6, 1, 12, tzinfo=UTC)
PARIS = ZoneInfo("Europe/Paris")
AT = ["--at", "2024-04-08", "--athlete", "x"]
"""Le jour dont l'origine est :data:`ORIGIN`."""


@pytest.fixture(autouse=True)
def fixed_world(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        gitstate, "git_state", lambda directory: GitState(COMMIT, False)
    )
    monkeypatch.setattr(cli, "_now", lambda: NOW)


def write(pairs: list[Any]) -> None:
    entries = sorted(
        (p[0] for p in pairs),
        key=lambda item: (item.start_time.timestamp(), item.activity_ref),
    )
    recordings = [p[1] for p in pairs if p[1] is not None]
    write_activities(
        data_dir(), ActivityIndex(tuple(entries), (SOURCE,)), recordings, REPORT
    )


def run(capsys: pytest.CaptureFixture[str], *options: str) -> tuple[int, str, str]:
    code = main(["curve", "o", *options])
    out, err = capsys.readouterr()
    return code, out, err


def meta() -> dict[str, Any]:
    path = data_dir() / "reference" / "o.meta.json"
    loaded: dict[str, Any] = json.loads(path.read_bytes().decode("utf-8"))
    return loaded


def lines_by_ref() -> dict[str, dict[str, Any]]:
    return {
        line["activity_ref"]: line
        for line in meta()["estimation"]["origin"]["activities"]
    }


def recording_file(ref: str) -> Path:
    return data_dir().joinpath("interim", "activities", "recordings", f"{ref}.json")


# --- Annexe 5 : les entrées plausibles ------------------------------------------------


def test_sorties_sans_ecoule_a_l_index_par_la_commande(
    capsys: pytest.CaptureFixture[str],
) -> None:
    write(_season())
    code, out, err = run(capsys, *AT)
    assert (code, err) == (0, "")
    assert lines_by_ref()["s0"]["method"] == "fin inférée"
    assert lines_by_ref()["apres"]["method"] == "index seul"
    assert "(0 sans écoulé)" not in out


def _sessions(pair: Any, stop_s: float) -> Any:
    item, rec = pair
    return item, dataclasses.replace(
        rec,
        sessions=(
            RecordingSession("running", None, 0.0, 1800.0, None, None),
            RecordingSession("running", None, 1900.0, None, None, None),
        ),
        timer_events=(
            TimerEvent(0.0, TimerEventType.START, None),
            TimerEvent(stop_s, TimerEventType.STOP, None),
        ),
    )


def test_plusieurs_sessions_et_chronometre_apres_le_dernier_point(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Une session sans écoulé, un arrêt du chronomètre après le dernier point : c'est
    lui qui finit l'activité, d'un côté ou de l'autre de l'origine."""
    start = ORIGIN - timedelta(seconds=4000)
    late = _sessions(
        activity_pair("late", start, index_elapsed_s=3600.0, recording_s=3600.0), 5000.0
    )
    early = _sessions(
        activity_pair("early", start, index_elapsed_s=3600.0, recording_s=3600.0),
        3900.0,
    )
    pairs = [*_season(), late, early]
    found = {
        i.end.activity_ref: i
        for i in select_at_origin(corpus(pairs), ORIGIN, 56, TRAIL)
    }
    assert found["late"].decision is TemporalDecision.AFTER_ORIGIN
    assert found["late"].end.safe_end == start + timedelta(seconds=5000)
    assert found["early"].decision is TemporalDecision.CANDIDATE
    assert found["early"].end.safe_end == start + timedelta(seconds=3900)
    write(pairs)
    code, _, err = run(capsys, *AT)
    assert (code, err) == (0, "")
    lines = lines_by_ref()
    assert lines["late"]["decision"] == "finie à l'origine ou après"
    assert lines["late"]["method"] == "index et enregistrement"
    assert lines["early"]["decision"] == "candidate"


def test_la_montre_finit_apres_l_index_par_la_commande(
    capsys: pytest.CaptureFixture[str],
) -> None:
    pair = activity_pair("a", at(31, 21, 40), index_elapsed_s=600.0, recording_s=2400.0)
    write([*_season(), pair])
    code, _, err = run(capsys, *AT)
    assert (code, err) == (0, "")
    line = lines_by_ref()["a"]
    assert line["decision"] == "finie à l'origine ou après"
    assert line["safe_end"] == "2024-03-31T22:20:00+00:00"
    assert line["recording_sha256"] is not None


def test_deux_entrees_de_meme_depart(capsys: pytest.CaptureFixture[str]) -> None:
    b = activity_pair("b", at(28, 8), index_elapsed_s=3600.0, recording_s=3600.0)
    a = activity_pair("a", at(28, 8), index_elapsed_s=3600.0, recording_s=3600.0)
    write([*_season(), b, a])
    code, _, err = run(capsys, *AT)
    assert (code, err) == (0, "")
    refs = [
        line["activity_ref"] for line in meta()["estimation"]["origin"]["activities"]
    ]
    assert refs.index("a") + 1 == refs.index("b")


def test_deux_candidates_de_meme_fin_sure(capsys: pytest.CaptureFixture[str]) -> None:
    a = activity_pair("a", at(28, 8), index_elapsed_s=3600.0, recording_s=3600.0)
    b = activity_pair("b", at(28, 8, 30), index_elapsed_s=1800.0, recording_s=1800.0)
    write([*_season(), a, b])
    code, _, err = run(capsys, *AT)
    assert (code, err) == (0, "")
    section = meta()["estimation"]["origin"]
    assert section["data_available_at"] == "2024-03-28T09:00:00+00:00"


@pytest.mark.parametrize(
    ("day", "window"),
    [
        ("2024-03-31", 7),
        ("2024-04-03", 1),
        ("2024-04-07", 56),
        ("2024-04-08", 1),
        ("2024-04-08", 56),
        ("2024-11-03", 56),
        ("2024-11-04", 1),
        ("2024-11-06", 3),
    ],
)
def test_changements_d_heure_par_la_commande(
    capsys: pytest.CaptureFixture[str], day: str, window: int
) -> None:
    """Les sept jours de recul ou la fenêtre traversent un changement d'heure :
    l'origine et la borne basse restent des minuits à Paris ; une fin à la borne entre,
    1 µs avant non, pour la règle comme pour le chargement."""
    origin = calendar_origin(datetime.fromisoformat(day).date())
    assert check_origin(origin) == origin
    lower = window_lower_bound(origin, window)
    assert lower is not None
    local_o, local_l = origin.astimezone(PARIS), lower.astimezone(PARIS)
    assert (local_o.hour, local_o.minute, local_l.hour, local_l.minute) == (0, 0, 0, 0)
    assert (local_o.date() - local_l.date()).days == window
    tick = timedelta(microseconds=1)
    on_bound = activity_pair(
        "bas", lower - timedelta(seconds=60), index_elapsed_s=60.0, recording_s=30.0
    )
    before = activity_pair(
        "avant",
        lower - timedelta(seconds=60) - tick,
        index_elapsed_s=60.0,
        recording_s=30.0,
    )
    write([on_bound, before])
    loaded = load_curve_corpus(data_dir(), "x", TRAIL, origin, window)
    assert list(loaded.recordings) == ["bas"]
    found = {
        i.end.activity_ref: i.decision
        for i in select_at_origin(loaded, origin, window, TRAIL)
    }
    assert found["bas"] is TemporalDecision.CANDIDATE
    assert found["avant"] is TemporalDecision.BEFORE_WINDOW
    code, out, err = run(capsys, "--at", day, "--window", str(window), "--athlete", "x")
    assert code in (0, 1), (out, err)
    if code == 1:
        assert err.startswith("Erreur : "), err


def test_une_fenetre_sans_intervalle_en_mouvement(
    capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Toutes les retenues sans intervalle de temps M : une absence, sans trace, qui dit
    la dernière retenue."""
    write(_season())

    def still(recording: Any, profile: Any, **options: Any) -> ActivityIntervals:
        return ActivityIntervals(
            recording.activity_ref,
            60.0,
            (CurveInterval(50.0, 0.0125, 0.0, 60.0, 0.0, 60.0, 0.0, None),),
            options.get("max_elapsed_s"),
        )

    monkeypatch.setattr(origin_module, "activity_intervals", still)
    code, out, err = run(capsys, *AT)
    assert code == 1
    assert err == (
        "Erreur : aucune courbe à l'origine : Aucune tranche estimée : aucun "
        "intervalle retenu n'a de temps en mouvement. Rien n'est écrit.\n"
    )
    assert "retenue 2024-03-27 10:00" in out
    assert not (data_dir() / "reference").exists()


def test_une_sortie_tres_lente_de_bout_en_bout(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Sans simulation : une marche à 5 cm/s ; quel qu'en soit le sort, jamais de
    trace."""
    rec = montee([(500.0, 0.0, 0.05)], noise=False, activity_ref="lent")
    item = entry(activity_ref="lent", start_time=at(20, 8), elapsed_duration_s=None)
    rec = dataclasses.replace(rec, start_time=at(20, 8))
    write([(item, rec)])
    code, _, err = run(capsys, *AT)
    assert code in (0, 1)
    if code == 1:
        assert err.startswith("Erreur : "), err


def test_un_enregistrement_d_un_type_non_choisi_abime_n_est_jamais_lu(
    capsys: pytest.CaptureFixture[str],
) -> None:
    other = activity_pair(
        "v",
        at(25, 8),
        index_elapsed_s=3600.0,
        recording_s=3600.0,
        activity_type="hiking",
    )
    write([*_season(), other])
    path = recording_file("v")
    path.write_bytes(path.read_bytes()[:100])
    code, _, err = run(capsys, *AT)
    assert (code, err) == (0, "")
    assert "v" not in lines_by_ref()


# --- Ce que le chargement ne garde pas ----------------------------------------------


def test_une_activite_sans_enregistrement_du_type_choisi_n_est_pas_lue(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Une activité saisie à la main : à l'index, du type choisi, sans FIT."""
    manual = (
        dataclasses.replace(
            entry(activity_ref="m", start_time=at(25, 8), elapsed_duration_s=3600.0),
            has_recording=False,
        ),
        None,
    )
    write([*_season(), manual])
    corpus_read = load_curve_corpus(data_dir(), "x", TRAIL, ORIGIN, 56)
    assert "m" not in corpus_read.recordings
    code, out, err = run(capsys, *AT)
    assert (code, err) == (0, "")
    assert "m" not in lines_by_ref()
    assert "1 sorties à pied finies" in out


def test_une_sortie_a_l_etranger_garde_son_jour_local(
    capsys: pytest.CaptureFixture[str],
) -> None:
    far = timezone(timedelta(hours=-5))
    away = activity_pair(
        "w",
        datetime(2024, 3, 19, 22, tzinfo=far),
        index_elapsed_s=None,
        recording_s=3600.0,
    )
    write([away, *_season()[1:8]])
    code, _, err = run(capsys, *AT)
    assert (code, err) == (0, "")
    assert meta()["date_from"] == "2024-03-19"


# --- Les entrées de la commande (annexe 4) ------------------------------------------


@pytest.mark.parametrize(
    "value",
    ["0", "-5", "+5", " 5", "5.0", "ALL", "٣", "５", "٥٦", "1٣", "1_000", "5\n"],  # noqa: RUF001
)
def test_fenetres_refusees_par_argparse(
    capsys: pytest.CaptureFixture[str], value: str
) -> None:
    with pytest.raises(SystemExit) as stopped:
        main(["curve", "o", *AT, "--window", value])
    assert stopped.value.code == 2
    assert "fenêtre invalide" in capsys.readouterr().err


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("-1", 1),
        ("1441", 1),
        ("1440.5", 1),
        ("nan", 1),
        ("inf", 1),
        ("1e400", 1),
    ],
)
def test_seuils_hors_garde_fous(
    capsys: pytest.CaptureFixture[str], value: str, expected: int
) -> None:
    write(_season())
    code, _, err = run(capsys, *AT, "--min-support-min", value)
    assert code == expected
    assert err.startswith("Erreur : "), err
    assert "curve_min_support_min" in err
    assert not (data_dir() / "reference").exists()


@pytest.mark.parametrize("value", ["0", "0.0", "1440", "-0.0"])
def test_seuils_aux_garde_fous(capsys: pytest.CaptureFixture[str], value: str) -> None:
    write(_season())
    code, _, err = run(capsys, *AT, "--min-support-min", value)
    assert code == 0, err
    assert meta()["diagnostic_support_threshold_min"] == float(value)


@pytest.mark.parametrize(
    "options",
    [
        ["--at", "2024-04-08", "--window", "100000", "--athlete", "x"],
        ["--at", "2024-04-08", "--window", "99999999999999", "--athlete", "x"],
        ["--at", "2024-04-08", "--window", "9" * 5000, "--athlete", "x"],
        ["--at", "0001-01-09", "--athlete", "x"],
        ["--at", "0001-01-09", "--window", "all", "--athlete", "x"],
        ["--at", "9999-12-31", "--athlete", "x"],
        ["--at", "2024-04-08", "--athlete", "  "],
        ["--at", "2024-04-08", "--athlete", ""],
        ["--at", "2024-04-08", "--athlete", "x", "--types", ""],
        ["--at", "2024-04-08", "--athlete", "x", "--types", "a,,b"],
        ["--at", "2024-04-08", "--athlete", "x", "--max-elapsed-min", "nan"],
        ["--at", "2024-04-08", "--athlete", "x", "--max-elapsed-min", "0"],
        ["--at", "2024-04-08", "--athlete", "x", "--min-duration-min", "inf"],
        ["--at", "2024-04-08", "--athlete", "x", "--hr-center", "400"],
        ["--at", "2024-04-08", "--athlete", "x", "--hr-center", "nan"],
    ],
)
def test_pas_de_trace_python(
    capsys: pytest.CaptureFixture[str], options: list[str]
) -> None:
    write(_season())
    try:
        code = main(["curve", "o", *options])
    except SystemExit as stopped:
        assert stopped.code == 2  # noqa: PT017 — argparse sort par SystemExit, ou non
        return
    _, err = capsys.readouterr()
    assert code in (0, 1)
    if code == 1:
        assert err.startswith("Erreur : "), err


# --- Les garanties écrites que la suite ne lit pas ------------------------------------


def test_le_document_d_une_absence_a_ses_cles_nulles() -> None:
    season = corpus(_season())
    result = rule(season, window=1, origin=at(19, 23))
    document = origin_document(result, season)
    assert document["data_available_at"] is None
    assert document["last_retained_end"] is None
    assert document["outcome"] == "absence"


def test_une_absence_garde_ses_champs() -> None:
    season = corpus(_season())
    result = rule(season, window=1, origin=at(19, 23), support_threshold_min=5.0)
    assert result.lower_bound == at(18, 23)
    assert result.support_threshold_min == 5.0
    assert result.history == OriginHistory(0, 0, 0, 0)
    assert result.support_error is None
    assert result.activity_types == TRAIL
    two = corpus(
        [activity_pair("a", at(30, 8), index_elapsed_s=60.0, recording_s=60.0)]
    )
    far = rule(two, origin=ORIGIN, chosen=origin_selection(min_duration_s=99999.0))
    assert far.history == OriginHistory(1, 0, 1, 0)
    assert far.lower_bound == at(4, 23, month=2)


def test_l_historique_a_ses_cles_dans_l_ordre() -> None:
    season = corpus(_season())
    document = origin_document(rule(season), season)
    assert list(document["history"]) == [  # type: ignore[call-overload]
        "foot_index_finished",
        "foot_without_index_elapsed",
        "selected_index_finished",
        "selected_without_index_elapsed",
    ]


def test_un_instant_a_la_microseconde_garde_ses_decimales() -> None:
    pair = activity_pair("a", at(30, 8), index_elapsed_s=None, recording_s=600.25)
    season = corpus([*_season(), pair])
    lines = origin_document(rule(season), season)["activities"]
    line = next(x for x in lines if x["activity_ref"] == "a")  # type: ignore[attr-defined]
    assert line["recording_end"] == "2024-03-30T08:10:00.250000+00:00"


def test_select_at_origin_refuse_une_liste_de_types_vide() -> None:
    with pytest.raises(ContractError, match="au moins un type"):
        select_at_origin(corpus(_season()), ORIGIN, 56, frozenset())


def test_la_section_origin_est_une_copie() -> None:
    import mountain_perf.estimation.curve as curve_module

    season = corpus(_season())
    result = rule(season)
    assert result.estimate is not None
    section = origin_document(result, season)
    document = curve_module.estimation_document(
        result.estimate,
        origin_selection(),
        DEFAULTS,
        PROFILE,
        commit=COMMIT,
        exports_retrieved_at=(),
        support_error=None,
        origin=section,
    )
    section["outcome"] = "changée"
    assert document["origin"]["outcome"] == "courbe projetable"  # type: ignore[index]


def test_une_seule_lecture_par_document(monkeypatch: pytest.MonkeyPatch) -> None:
    write(_season())
    reads: Counter[str] = Counter()
    real = Path.read_bytes

    def counting(self: Path) -> bytes:
        reads[self.name] += 1
        return real(self)

    monkeypatch.setattr(Path, "read_bytes", counting)
    load_curve_corpus(data_dir(), "x", TRAIL, ORIGIN, 56)
    assert reads["index.json"] == 1
    assert reads["s0.json"] == 1


def _og1_instances() -> list[object]:
    season = corpus(_season())
    result = rule(season)
    no_curve = rule(season, chosen=origin_selection(min_duration_s=99999.0))
    assert result.estimate is not None
    assert no_curve.activity_fates
    from mountain_perf.estimation.curve import estimate_curve_outcome

    empty = estimate_curve_outcome([], [], origin_selection(), DEFAULTS)
    assert isinstance(empty, NoCurve)
    return [
        result.inspections[0].end,
        season,
        result.inspections[0],
        result.history,
        result,
        result.estimate.activity_fates[0],
        empty,
    ]


def test_les_classes_d_og1_sont_gelees() -> None:
    expected = {
        ActivityEnd,
        CurveCorpus,
        Inspection,
        OriginHistory,
        OriginEstimate,
        ActivityFate,
        NoCurve,
    }
    instances = _og1_instances()
    assert {type(i) for i in instances} == expected
    for instance in instances:
        for field in dataclasses.fields(instance):  # type: ignore[arg-type]
            with pytest.raises(dataclasses.FrozenInstanceError):
                setattr(instance, field.name, getattr(instance, field.name))


def test_les_champs_sont_des_tuples() -> None:
    season = corpus(_season())
    result = rule(season)
    assert result.estimate is not None
    assert isinstance(result.inspections, tuple)
    assert isinstance(result.rows, tuple)
    assert isinstance(result.activity_fates, tuple)
    assert isinstance(result.estimate.excluded_activities, tuple)
    assert isinstance(result.estimate.excluded_intervals, tuple)
    absent = rule(season, chosen=origin_selection(min_duration_s=99999.0))
    assert isinstance(absent.activity_fates, tuple)


# --- La règle et le chargement font le même calcul (propriété) -----------------------


OFFSETS = st.sampled_from([-300, -60, 0, 60, 120, 330, 840])
TICKS = st.sampled_from(
    [
        timedelta(0),
        timedelta(microseconds=1),
        timedelta(microseconds=-1),
        timedelta(seconds=1),
        timedelta(seconds=-1),
        timedelta(hours=-3),
        timedelta(hours=3),
    ]
)


@settings(max_examples=300, deadline=None)
@given(
    target=st.sampled_from(["origin", "lower"]),
    tick=TICKS,
    offset=OFFSETS,
    elapsed=st.sampled_from([0.5, 59.999999, 60.0, 599.75, 3723.5]),
    window=st.sampled_from([1, 7, 56, "all"]),
    missing=st.booleans(),
)
def test_la_regle_et_le_chargement_lisent_les_memes_enregistrements(
    target: str,
    tick: timedelta,
    offset: int,
    elapsed: float,
    window: Any,
    missing: bool,
) -> None:
    """La décision « sur l'index seul » est la même des deux côtés, aux bornes exactes,
    décalage local et secondes flottantes compris."""
    bound = window_lower_bound(ORIGIN, window)
    anchor = ORIGIN if target == "origin" or bound is None else bound
    start = (anchor + tick - timedelta(seconds=elapsed)).astimezone(
        timezone(timedelta(minutes=offset))
    )
    item = entry(
        activity_ref="a",
        start_time=start,
        elapsed_duration_s=None if missing else elapsed,
    )
    index = ActivityIndex((item,), (SOURCE,))
    read: list[str] = []

    def fake_index(folder: Any) -> tuple[ActivityIndex, str]:
        return index, "b" * 64

    def fake_recording(folder: Any, ref: str) -> tuple[Any, str]:
        read.append(ref)
        return (
            bare_recording(activity_ref=ref, start_time=start.astimezone(UTC)),
            SHA,
        )

    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(runs_module, "read_index_with_sha256", fake_index)
        patch.setattr(runs_module, "read_recording_with_sha256", fake_recording)
        loaded = load_curve_corpus(Path("."), "x", TRAIL, ORIGIN, window)
    inspection = select_at_origin(loaded, ORIGIN, window, TRAIL)[0]
    assert (inspection.recording_sha256 is not None) == bool(read)


def test_estimate_at_origin_et_le_module_interim_restent_separes() -> None:
    """Témoin : le noyau n'importe pas le lecteur d'interim (M06)."""
    assert not hasattr(origin_module, "read_index")
    assert interim_module.read_index_with_sha256 is not None
    assert estimate_at_origin is not None


# --- Chaque classe d'erreur attrapée, produite à la commande (annexe 4) ---------------


def test_sans_dossier_de_donnees_un_message(
    capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("MPA_DATA_DIR")
    code, _, err = run(capsys, *AT)
    assert code == 1
    assert err.startswith("Erreur : "), err


def test_reference_est_un_fichier(capsys: pytest.CaptureFixture[str]) -> None:
    write(_season())
    (data_dir() / "reference").write_bytes(b"")
    code, _, err = run(capsys, *AT)
    assert code == 1
    assert err.startswith("Erreur : "), err


def test_l_index_est_un_dossier(capsys: pytest.CaptureFixture[str]) -> None:
    write(_season())
    path = data_dir().joinpath("interim", "activities", "index.json")
    path.unlink()
    path.mkdir()
    code, _, err = run(capsys, *AT)
    assert code == 1
    assert err.startswith("Erreur : "), err


def test_un_enregistrement_est_un_dossier(capsys: pytest.CaptureFixture[str]) -> None:
    write(_season())
    path = recording_file("s3")
    path.unlink()
    path.mkdir()
    code, _, err = run(capsys, *AT)
    assert code == 1
    assert err.startswith("Erreur : "), err


def test_un_enregistrement_abime_d_une_entree_que_l_index_decide_ne_gene_pas(
    capsys: pytest.CaptureFixture[str],
) -> None:
    write(_season())
    path = recording_file("apres")
    path.write_bytes(b"pas du json")
    code, _, err = run(capsys, *AT)
    assert (code, err) == (0, "")


def test_moins_l_infini_est_une_erreur_d_argument() -> None:
    """``-inf`` ressemble à une option : argparse le refuse en code 2 ; la forme ``=``
    passe jusqu'aux garde-fous."""
    write(_season())
    with pytest.raises(SystemExit) as stopped:
        main(["curve", "o", *AT, "--min-support-min", "-inf"])
    assert stopped.value.code == 2
    assert main(["curve", "o", *AT, "--min-support-min=-inf"]) == 1


# --- Les ordres de contrôle écrits au brief (deux fautes à la fois) -------------------


def test_l_historique_ne_compte_pas_une_sortie_partie_a_l_origine() -> None:
    from mountain_perf.estimation.origin import origin_history

    index = ActivityIndex(
        (entry(activity_ref="a", start_time=ORIGIN, elapsed_duration_s=None),),
        (SOURCE,),
    )
    assert origin_history(index, ORIGIN, TRAIL) == OriginHistory(0, 0, 0, 0)


def test_nocurve_garde_ses_intervalles_ecartes() -> None:
    from mountain_perf.estimation.curve import IntervalExclusion, estimate_curve_outcome
    from test_estimation_curve import activity, interval

    outcome = estimate_curve_outcome(
        [activity("x", [interval(1.5)])], ["x"], origin_selection(), DEFAULTS
    )
    assert isinstance(outcome, NoCurve)
    assert outcome.excluded_intervals == ((IntervalExclusion.GRADE, 1),)


def test_l_athlete_avant_l_empreinte() -> None:
    a = activity_pair("a", at(30, 8), index_elapsed_s=60.0, recording_s=60.0)
    with pytest.raises(ContractError, match="athlete_ref"):
        CurveCorpus("  ", ActivityIndex((a[0],), (SOURCE,)), "nope", {}, {})


def test_l_athlete_avant_la_selection_datee() -> None:
    from datetime import date

    from test_estimation_curve import selection

    with pytest.raises(ContractError, match="corpus est celui de"):
        rule(
            corpus(_season()),
            athlete="y",
            chosen=selection(date_from=date(2024, 3, 1), date_to=date(2024, 3, 31)),
        )


def test_la_fenetre_avant_l_origine() -> None:
    with pytest.raises(ContractError, match="window"):
        window_lower_bound(datetime(2024, 4, 1), 0)


@pytest.mark.parametrize(
    ("options", "message"),
    [
        (
            ["--from", "2024-03-01", "--window", "5", "--athlete", "x"],
            "--from et --to ensemble",
        ),
        (
            ["--at", "2030-01-01", "--from", "2024-03-01", "--athlete", "x"],
            "--at exclut",
        ),
        (["--hr-width", "5", "--athlete", "x"], "demandent --hr-center"),
    ],
)
def test_l_ordre_des_refus_a_deux_fautes(
    capsys: pytest.CaptureFixture[str], options: list[str], message: str
) -> None:
    code, _, err = run(capsys, *options)
    assert code == 1
    assert message in err


def test_l_origine_future_avant_la_courbe_deja_la(
    capsys: pytest.CaptureFixture[str],
) -> None:
    reference = data_dir() / "reference"
    reference.mkdir()
    (reference / "o.csv").write_bytes(b"")
    code, _, err = run(capsys, "--at", "2030-01-01", "--athlete", "x")
    assert code == 1
    assert "dans le futur" in err


def test_l_origine_future_avant_l_arbre_modifie(
    capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(gitstate, "git_state", lambda directory: GitState(COMMIT, True))
    code, _, err = run(capsys, "--at", "2030-01-01", "--athlete", "x")
    assert code == 1
    assert "dans le futur" in err
