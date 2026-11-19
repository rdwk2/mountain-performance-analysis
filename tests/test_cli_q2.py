"""La commande de Q2 (AN3-3b, ``docs/decisions/0023``, § 11) : la puissance, la garde
de l'estimation, l'extra, le clone modifié, un fil BLAS, et ce que la sortie de la
puissance ne dit pas (C21) ; la provenance (C22). Sur le monde inventé de
``tests/fixtures/q2_run.py``, à tirages et grille réduits. Le dossier des données est
celui que ``conftest.py`` pose pour chaque test."""

from __future__ import annotations

import ast
import contextlib
import inspect
import io
import json
import os
import shutil
import sys
import textwrap
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest

from fixtures.processed import COMMIT
from mountain_perf import cli, gitstate
from mountain_perf.cli import main
from mountain_perf.config import data_dir
from mountain_perf.gitstate import GitState

Q2_EXTRA_ERROR = (
    "Erreur : Q2 demande l'extra analyse. Installer : uv sync --extra analyse"
)
"""Le message sans l'extra, recopié du brief (§ 11.1), écrit en dur."""
Q2_MODIFIED_TREE_ERROR = (
    "Erreur : un fichier suivi du code exécuté est modifié : mperf q2 écrit le "
    "commit du code dans ses résultats (CHARTE, § 10). Committer ou annuler la "
    "modification."
)
"""Le message d'un clone modifié (la phrase de Q1 avec « mperf q2 »), écrit en dur."""
Q2_NO_POWER_ERROR = (
    "Erreur : aucun résultat de mperf q2 puissance pour ces tables : lancer just q2 "
    "puissance d'abord (la puissance se calcule avant toute estimation, 0023)"
)
"""Le message de la garde de l'estimation, recopié du brief (§ 11.1), écrit en dur."""

OTHER_COMMIT = "b" * 40
POWER = Path("resultats") / "Q2" / "puissance"
BLAS = ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS")


@pytest.fixture(autouse=True)
def blas_restored(monkeypatch: pytest.MonkeyPatch) -> None:
    """``_run_q2`` écrit les variables BLAS dans ``os.environ`` : elles reprennent
    leur valeur d'avant le test."""
    for name in BLAS:
        if name in os.environ:
            monkeypatch.setenv(name, os.environ[name])
        else:
            monkeypatch.setenv(name, "0")
            monkeypatch.delenv(name)


def _hide(monkeypatch: pytest.MonkeyPatch, library: str, modules: list[str]) -> None:
    """``library`` absente (``None`` dans ``sys.modules``) ; ``modules`` retirés,
    pour que leur import soit refait."""
    for name in modules:
        monkeypatch.delitem(sys.modules, name, raising=False)
        parent, _, child = name.rpartition(".")
        if parent in sys.modules:
            monkeypatch.delattr(sys.modules[parent], child, raising=False)
    monkeypatch.setitem(sys.modules, library, None)


def _modules(prefix: str) -> list[str]:
    return sorted(m for m in sys.modules if m == prefix or m.startswith(f"{prefix}."))


@pytest.mark.parametrize("library", ["numpy", "scipy", "pyarrow", "plotly"])
def test_without_the_extra_the_command_says_how_to_install(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    library: str,
) -> None:
    """Sans numpy, scipy, pyarrow ou plotly : ``Q2_EXTRA_ERROR``, code 1, rien
    d'écrit (ce test n'a pas le saut de numpy)."""
    pytest.importorskip(library)
    modules = {
        "pyarrow": ["mountain_perf.analyse.parquet"],
        "plotly": ["mountain_perf.analyse.plot"],
    }.get(
        library,
        [
            *_modules("mountain_perf.analyse.inference"),
            *_modules("mountain_perf.analyse.q2"),
        ],
    )
    _hide(monkeypatch, library, modules)
    assert main(["q2", "puissance"]) == 1
    assert capsys.readouterr().err == Q2_EXTRA_ERROR + "\n"
    assert not (data_dir() / "resultats").exists()


def test_another_missing_module_propagates(monkeypatch: pytest.MonkeyPatch) -> None:
    pytest.importorskip("numpy")
    pytest.importorskip("pyarrow")
    pytest.importorskip("plotly")
    _hide(monkeypatch, "mountain_perf.analyse.q2.results", [])
    monkeypatch.delattr(
        sys.modules["mountain_perf.analyse.q2"], "results", raising=False
    )
    with pytest.raises(ModuleNotFoundError):
        main(["q2", "puissance"])


# --- le reste demande l'extra --------------------------------------------------------


def _extras() -> None:
    for library in ("numpy", "scipy", "pyarrow", "plotly"):
        pytest.importorskip(library)


@pytest.fixture
def fixed_world(monkeypatch: pytest.MonkeyPatch) -> list[Path]:
    """Un clone propre au commit des fixtures, le 2026-11-16, les tirages et la grille
    réduits ; rend les dossiers dont l'état git est lu."""
    _extras()
    from fixtures import q2_run
    from mountain_perf.analyse.q2 import parameters, power

    seen: list[Path] = []

    def state(directory: Path) -> GitState:
        seen.append(directory)
        return GitState(COMMIT, False)

    monkeypatch.setattr(gitstate, "git_state", state)
    monkeypatch.setattr(cli, "_today", lambda: q2_run.DAY)
    monkeypatch.setattr(parameters, "q2_parameters", q2_run.reduced_parameters)
    monkeypatch.setattr(power, "power_grids", q2_run.reduced_grids)
    return seen


@dataclass(frozen=True)
class PowerRun:
    """Une exécution de la puissance, faite une fois pour le module : le dossier des
    données, la sortie, le résultat calculé."""

    folder: Path
    out: str
    result: Any


@pytest.fixture(scope="module")
def power_run(tmp_path_factory: pytest.TempPathFactory) -> PowerRun:
    """Un résultat de puissance par module de tests (validé par la conception)."""
    _extras()
    from fixtures import q2_run
    from mountain_perf.analyse.q2 import parameters, power

    folder = tmp_path_factory.mktemp("q2_puissance")
    q2_run.write_world(folder)
    captured: list[Any] = []
    original = power.run_power

    def keep(*args: Any, **kwargs: Any) -> Any:
        result = original(*args, **kwargs)
        captured.append(result)
        return result

    out = io.StringIO()
    with pytest.MonkeyPatch.context() as patch:
        for name in BLAS:
            patch.setenv(name, os.environ.get(name, "0"))
        patch.setenv("MPA_DATA_DIR", str(folder))
        patch.setattr(gitstate, "git_state", lambda d: GitState(COMMIT, False))
        patch.setattr(cli, "_today", lambda: q2_run.DAY)
        patch.setattr(parameters, "q2_parameters", q2_run.reduced_parameters)
        patch.setattr(power, "power_grids", q2_run.reduced_grids)
        patch.setattr(power, "run_power", keep)
        with contextlib.redirect_stdout(out):
            assert main(["q2", "puissance"]) == 0
    return PowerRun(folder, out.getvalue(), captured[0])


def _copy(run: PowerRun) -> Path:
    target = data_dir()
    shutil.copytree(run.folder, target, dirs_exist_ok=True)
    return target


def _power_folder(base: Path) -> Path:
    (written,) = (base / POWER).iterdir()
    return written


def test_the_power_writes_its_folder_and_says_what_it_wrote(
    power_run: PowerRun,
) -> None:
    written = _power_folder(power_run.folder)
    assert sorted(p.name for p in written.iterdir()) == [
        "flux.csv",
        "provenance.json",
        "puissance.csv",
    ]
    lines = power_run.out.splitlines()
    assert lines[0].startswith("long_climb : 30 journées, ")
    assert "; plus petit effet visible à 80 % : " in lines[0]
    assert "; puissance à 5 %/an : " in lines[0]
    assert "; calibration : " in lines[0]
    assert "puissance approchée : covariance fixée dans la simulation (0023)" in lines
    assert lines[-1] == f"-> resultats/Q2/puissance/{written.name}/"
    document = json.loads((written / "provenance.json").read_text(encoding="utf-8"))
    assert document["commande"] == "mperf q2 puissance"
    assert "processus" not in document


def test_c21_nothing_estimated_on_the_data_is_written(power_run: PowerRun) -> None:
    """C21 : le ``b̂`` du principal, calculé ici par les fonctions du § 7, n'apparaît
    ni dans la sortie, ni dans ``puissance.csv``, ni dans ``provenance.json`` (en
    ``repr``, à 4 chiffres, en fraction par an) ; le monde a exactement ses sept
    clés."""
    from fixtures import q2_run
    from mountain_perf.analyse.inference.linear import fraction_per_year
    from mountain_perf.analyse.q2.data import q2_data
    from mountain_perf.analyse.q2.model import (
        Measure,
        build_design,
        fit_direct,
        model_spec,
        stage_one,
    )
    from mountain_perf.schemas.processed import ClimbRegime

    params = q2_run.reduced_parameters()
    data = q2_data(q2_run.world_tables(), None, params)
    texts = [power_run.out]
    written = _power_folder(power_run.folder)
    texts += [(written / n).read_text(encoding="utf-8") for n in ("puissance.csv",)]
    document_text = (written / "provenance.json").read_text(encoding="utf-8")
    texts.append(document_text)
    document = json.loads(document_text)
    for regime in (ClimbRegime.LONG_CLIMB, ClimbRegime.SHORT_CLIMB):
        spec = model_spec(data.days[regime], Measure.MP, regime, params)
        units = spec.units()
        design = build_design(units, spec, stage_one(units, Measure.MP), params)
        b = fit_direct(design, params).b
        for value in (b, fraction_per_year(b)):
            for form in (repr(value), f"{value:.4g}"):
                assert not any(form in text for text in texts), form
        assert set(document["regimes"][regime.value]["monde"]) == {
            "n",
            "p",
            "retraits",
            "tau2",
            "s2u",
            "phi",
            "s2e",
        }


def test_c22_the_provenance_and_a_date_independent_fingerprint(
    power_run: PowerRun,
    fixed_world: list[Path],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """C22 : chaque paramètre de Q2 avec sa valeur, la graine ; une seconde exécution
    à une autre date (le calcul repris du module) a la même empreinte."""
    from datetime import date

    from fixtures import q2_run
    from mountain_perf.analyse.q2 import power
    from mountain_perf.analyse.q2.parameters import Q2_PARAMETER_SPECS, Q2_ROOT_SEED

    written = _power_folder(power_run.folder)
    document = json.loads((written / "provenance.json").read_text(encoding="utf-8"))
    params = q2_run.reduced_parameters()
    assert document["parametres"] == {
        spec.name: params[spec.name] for spec in Q2_PARAMETER_SPECS
    }
    assert document["graine"] == Q2_ROOT_SEED
    q2_run.write_world(data_dir())
    monkeypatch.setattr(power, "run_power", lambda *a, **k: power_run.result)
    monkeypatch.setattr(cli, "_today", lambda: date(2026, 11, 20))
    assert main(["q2", "puissance"]) == 0
    capsys.readouterr()
    other = _power_folder(data_dir())
    assert other.name == "2026-11-20_" + written.name.split("_")[1]


def test_the_estimation_without_a_power_result_is_refused(
    fixed_world: list[Path], capsys: pytest.CaptureFixture[str]
) -> None:
    """La garde (§ 10.3) : sans résultat de puissance des mêmes tables, rien n'est
    calculé ni écrit."""
    from fixtures import q2_run

    q2_run.write_world(data_dir())
    assert main(["q2"]) == 1
    assert capsys.readouterr().err == Q2_NO_POWER_ERROR + "\n"
    assert not (data_dir() / "resultats").exists()


def test_a_power_result_of_other_tables_does_not_count(
    power_run: PowerRun,
    fixed_world: list[Path],
    capsys: pytest.CaptureFixture[str],
) -> None:
    from fixtures import q2_run

    target = data_dir()
    shutil.copytree(power_run.folder / "resultats", target / "resultats")
    q2_run.write_world(target, seed=12)
    assert main(["q2"]) == 1
    assert capsys.readouterr().err == Q2_NO_POWER_ERROR + "\n"


def test_a_modified_clone_is_refused(
    fixed_world: list[Path],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    from fixtures import q2_run

    q2_run.write_world(data_dir())
    monkeypatch.setattr(gitstate, "git_state", lambda d: GitState(COMMIT, True))
    assert main(["q2", "puissance"]) == 1
    assert capsys.readouterr().err == Q2_MODIFIED_TREE_ERROR + "\n"
    assert not (data_dir() / "resultats").exists()


def test_tables_of_another_commit_are_said(
    power_run: PowerRun,
    fixed_world: list[Path],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    from fixtures import q2_run
    from mountain_perf.analyse.q2 import power

    q2_run.write_world(data_dir())
    monkeypatch.setattr(gitstate, "git_state", lambda d: GitState(OTHER_COMMIT, False))
    monkeypatch.setattr(power, "run_power", lambda *a, **k: power_run.result)
    assert main(["q2", "puissance"]) == 0
    assert (
        f"Tables écrites par un autre commit ({COMMIT[:12]}) : relancer just process "
        "si leur calcul a changé."
    ) in capsys.readouterr().out.splitlines()


# --- un fil BLAS ---------------------------------------------------------------------


def test_run_q2_sets_one_blas_thread_overwriting(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Q-50 (b), à ``--processus 1`` : les trois variables valent ``"1"`` après
    ``_run_q2``, une valeur ``"4"`` posée avant comprise (ici, sans tables, la
    commande s'arrête tôt)."""
    _extras()
    for name in BLAS:
        monkeypatch.setenv(name, "4")
    assert cli._run_q2("puissance", 1) == 1
    assert tuple(os.environ[name] for name in BLAS) == ("1", "1", "1")


def test_the_first_statement_of_run_q2_sets_the_blas_threads() -> None:
    """Correction D : la première instruction de ``_run_q2`` (après la docstring) est
    l'appel qui pose les trois variables, avant tout import."""
    tree = ast.parse(textwrap.dedent(inspect.getsource(cli._run_q2)))
    function = tree.body[0]
    assert isinstance(function, ast.FunctionDef)
    first = function.body[1]
    assert isinstance(first, ast.Expr)
    assert isinstance(first.value, ast.Call)
    assert isinstance(first.value.func, ast.Name)
    assert first.value.func.id == "_single_thread_blas"
    assert cli.BLAS_THREAD_VARIABLES == BLAS


# --- l'analyse des arguments ---------------------------------------------------------


@pytest.mark.parametrize("value", ["0", "-1", "deux"])
def test_processus_below_one_is_refused(
    value: str, capsys: pytest.CaptureFixture[str]
) -> None:
    with pytest.raises(SystemExit) as stop:
        main(["q2", "puissance", "--processus", value])
    assert stop.value.code == 2
    assert "--processus" in capsys.readouterr().err


def test_only_puissance_is_a_mode(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as stop:
        main(["q2", "estimation"])
    assert stop.value.code == 2
    capsys.readouterr()


def test_mperf_help_lists_the_q2_subcommand(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("COLUMNS", "200")
    with pytest.raises(SystemExit):
        main(["--help"])
    assert "Q2 : la puissance (puissance), puis l'estimation" in capsys.readouterr().out


# --- l'estimation ---------------------------------------------------------------------


def _journal_lines(base: Path) -> list[bytes]:
    path = base / "resultats" / "essais.jsonl"
    return path.read_bytes().splitlines() if path.exists() else []


def _estimations(base: Path) -> list[str]:
    root = base / "resultats" / "Q2"
    return sorted(p.name for p in root.iterdir() if p.name != "puissance")


def test_the_estimation_after_the_power(
    power_run: PowerRun,
    fixed_world: list[Path],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Puissance, puis estimation : le dossier, 24 lignes au journal ; à une autre
    date, 48 ; le même jour, refusée sans rien écrire (le calcul repris de la première
    estimation)."""
    from datetime import date

    from mountain_perf.analyse.q2 import trials

    base = _copy(power_run)
    computed: list[Any] = []
    original = trials.q2_trials

    def keep(*args: Any, **kwargs: Any) -> Any:
        if not computed:
            computed.append(original(*args, **kwargs))
        return computed[0]

    monkeypatch.setattr(trials, "q2_trials", keep)
    assert main(["q2"]) == 0
    out = capsys.readouterr().out.splitlines()
    (name,) = _estimations(base)
    assert sorted(p.name for p in (base / "resultats" / "Q2" / name).iterdir()) == [
        "autocorrelation.csv",
        "essais.csv",
        "figure.csv",
        "figure.html",
        "flux.csv",
        "provenance.json",
    ]
    assert len(_journal_lines(base)) == 24
    assert out[0].startswith("P : estime — ")
    assert len([line for line in out if " : " in line and " — " in line]) >= 20
    assert "24 essais ajoutés à resultats/essais.jsonl" in out
    assert out[-1] == f"-> resultats/Q2/{name}/"
    document = json.loads(
        (base / "resultats" / "Q2" / name / "provenance.json").read_text(
            encoding="utf-8"
        )
    )
    assert document["puissance"]["dossier"] == _power_folder(base).name
    monkeypatch.setattr(cli, "_today", lambda: date(2026, 11, 18))
    assert main(["q2"]) == 0
    capsys.readouterr()
    assert len(_journal_lines(base)) == 48
    assert len(_estimations(base)) == 2
    before = (base / "resultats" / "essais.jsonl").read_bytes()
    assert main(["q2"]) == 1
    assert "existe déjà : rien n'est réécrit" in capsys.readouterr().err
    assert (base / "resultats" / "essais.jsonl").read_bytes() == before
    assert len(_estimations(base)) == 2


def test_a_broken_journal_refuses_the_estimation(
    power_run: PowerRun,
    fixed_world: list[Path],
    capsys: pytest.CaptureFixture[str],
) -> None:
    """§ 10.4 (correction H) : une chaîne rompue, aucun dossier d'estimation."""
    base = _copy(power_run)
    journal = base / "resultats" / "essais.jsonl"
    journal.write_bytes(b'{"precedente":"x"}\n')
    assert main(["q2"]) == 1
    assert capsys.readouterr().err == (
        "Erreur : essais.jsonl, ligne 1 : la chaîne est rompue ; rien n'est écrit\n"
    )
    assert _estimations(base) == []
    assert journal.read_bytes() == b'{"precedente":"x"}\n'


# --- correctifs de la PR #52 ----------------------------------------------------------

POWER_HEADER = (
    "regime,scenario,b_fraction_par_an,tirages,tirages_en_echec,p_etabli,"
    "p_absence_effet_utile,erreur_mc_etabli,puissance,erreur_s,erreur_m,"
    "biais_fraction_par_an"
)
"""L'en-tête de ``puissance.csv``, recopié du brief (§ 8.4), écrit en dur."""


def test_the_power_header_and_no_failed_draw(power_run: PowerRun) -> None:
    """Correctifs de la PR #52, 3.5 et 3.7 (a) : l'en-tête de ``puissance.csv`` écrit
    en dur ; sur le monde de la commande (celui de C21), aucun tirage en échec, ni
    dans ``puissance.csv`` ni dans la provenance. Contre l'en-tête changé (P3j) et une
    estimation simulée qui lève sans qu'on le voie (P3o)."""
    written = _power_folder(power_run.folder)
    lines = (written / "puissance.csv").read_text(encoding="utf-8").splitlines()
    assert lines[0] == POWER_HEADER
    assert len(lines) > 1
    failed = POWER_HEADER.split(",").index("tirages_en_echec")
    assert all(line.split(",")[failed] == "0" for line in lines[1:])
    document = json.loads((written / "provenance.json").read_text(encoding="utf-8"))
    regimes = document["regimes"]
    assert set(regimes) == {"long_climb", "short_climb"}
    assert all(r["tirages_en_echec"] == 0 for r in regimes.values())


POWER_TOP_KEYS = {
    "question",
    "commande",
    "commit",
    "version_du_paquet",
    "periode",
    "tables",
    "periodes",
    "parametres",
    "graine",
    "appareil_principal",
    "grilles",
    "regimes",
    "fichiers",
    "genere_le",
}
"""Les clés du haut de la provenance de la puissance (§ 10.1), écrites en dur."""
REGIME_KEYS = {
    "statut",
    "monde",
    "colonnes",
    "residus_de_journee_nuls",
    "reml_sans_date",
    "seuils",
    "plus_petit_effet_visible",
    "a_delta",
    "a_zero",
    "calibration",
    "absence_hors_d_atteinte",
    "non_tranche_attendu",
    "message",
    "tirages_en_echec",
}
"""Les clés de ``regimes.<régime>`` d'un régime calculé (§§ 8.4, 10.1)."""


def test_the_power_provenance_keys_and_sorted_text(power_run: PowerRun) -> None:
    """Correctifs de la PR #52, 3 bis.11 : les clés du haut et celles de
    ``regimes.<régime>``, écrites en dur ; ``commit`` (celui des fixtures),
    ``version_du_paquet`` (celle de ``pyproject.toml``), ``periode`` (la première et
    la dernière journée, relues dans les tables par le test), ``periodes`` absent ; le
    texte égal à son JSON relu puis réécrit trié. Contre ``provenance.json`` écrit sans
    ``sort_keys`` (P5l), ``commit`` retiré (P5l)."""
    from fixtures import q2_run

    written = _power_folder(power_run.folder)
    text = (written / "provenance.json").read_text(encoding="utf-8")
    document = json.loads(text)
    assert text == (
        json.dumps(document, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    )
    assert set(document) == POWER_TOP_KEYS
    for regime in ("long_climb", "short_climb"):
        assert set(document["regimes"][regime]) == REGIME_KEYS
    assert document["commit"] == COMMIT
    assert document["version_du_paquet"] == "0.0.1"
    starts = [a.start_time.date() for a in q2_run.world_tables().activities]
    assert document["periode"] == {
        "debut": min(starts).isoformat(),
        "fin": max(starts).isoformat(),
    }
    assert document["periodes"] is None


def test_the_power_summary_line_of_a_regime(power_run: PowerRun) -> None:
    """Correctifs de la PR #52, 3 bis.14 : la ligne des montées longues du résumé,
    bâtie dans le test : ``n``, ``p`` et les retraits du modèle calculé ici par
    ``model_spec`` ; le plus petit effet visible, la puissance à δ et la calibration
    lus dans le résultat calculé (ils dépendent des tirages), mis en forme à la
    main."""
    from fixtures import q2_run
    from mountain_perf.analyse.q2.data import q2_data
    from mountain_perf.analyse.q2.model import Measure, model_spec
    from mountain_perf.schemas.processed import ClimbRegime

    params = q2_run.reduced_parameters()
    data = q2_data(q2_run.world_tables(), None, params)
    long = ClimbRegime.LONG_CLIMB
    spec = model_spec(data.days[long], Measure.MP, long, params)
    (summary,) = [r.summary for r in power_run.result.regimes if r.regime is long]
    visible = (
        "hors de la grille"
        if summary.smallest_visible is None
        else format(100 * summary.smallest_visible, ".1f").replace(".", ",") + " %/an"
    )
    power = format(summary.power_at_delta, ".2f").replace(".", ",")
    calibration = summary.calibration
    calibrated = (
        "non déclenchée"
        if not calibration.triggered
        else "non calibrable"
        if calibration.alpha is None
        else f"déclenchée ({calibration.alpha!r})"
    )
    withdrawals = "-".join(str(w) for w in spec.withdrawals) or "aucun"
    expected = (
        f"long_climb : {spec.n} journées, {spec.p} colonnes, retraits {withdrawals} "
        f"; plus petit effet visible à 80 % : {visible} ; puissance à 5 %/an : "
        f"{power} ; calibration : {calibrated}"
    )
    assert power_run.out.splitlines()[0] == expected


@pytest.mark.parametrize("processus", [1, 2, 3])
def test_processus_is_passed_to_simulate_power(
    fixed_world: list[Path],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    processus: int,
) -> None:
    """Correctifs de la PR #52, 3 bis.14 : ``--processus 1``, ``2`` et ``3`` sont
    acceptés (code 0) et un espion de ``simulate_power`` voit ce nombre de
    processus à chaque appel (8 : deux régimes, quatre scénarios). Contre un
    ``--processus`` qui refuse 1 (P5n) et ``workers`` non transmis (P5n)."""
    from fixtures import q2_run
    from mountain_perf.analyse.inference.power import Outcome
    from mountain_perf.analyse.inference.readings import Reading
    from mountain_perf.analyse.q2 import power

    seen: list[int] = []

    def fake(
        simulate: Any,
        estimate: Any,
        b_values: Any,
        alphas: Any,
        n_draws: int,
        root_seed: int,
        key: tuple[int, ...] = (),
        workers: int = 1,
    ) -> Any:
        seen.append(workers)
        undecided = Outcome(0.0, (Reading.UNDECIDED,) * len(alphas), (0,) * len(alphas))
        return tuple((undecided,) * n_draws for _ in b_values)

    q2_run.write_world(data_dir())
    monkeypatch.setattr(power, "simulate_power", fake)
    code: object
    try:
        code = main(["q2", "puissance", "--processus", str(processus)])
    except SystemExit as stop:
        code = stop.code
    assert code == 0
    capsys.readouterr()
    assert seen == [processus] * 8


@dataclass(frozen=True)
class EstimationRun:
    """Une estimation après la puissance, faite une fois pour le module : le dossier
    des données, la sortie, le dossier écrit."""

    folder: Path
    out: str
    written: Path


@pytest.fixture(scope="module")
def estimation_run(
    power_run: PowerRun, tmp_path_factory: pytest.TempPathFactory
) -> EstimationRun:
    """``mperf q2`` sur le monde de la puissance du module (le principal y est
    estimé)."""
    _extras()
    from fixtures import q2_run
    from mountain_perf.analyse.q2 import parameters, power

    folder = tmp_path_factory.mktemp("q2_estimation")
    shutil.copytree(power_run.folder, folder, dirs_exist_ok=True)
    out = io.StringIO()
    with pytest.MonkeyPatch.context() as patch:
        for name in BLAS:
            patch.setenv(name, os.environ.get(name, "0"))
        patch.setenv("MPA_DATA_DIR", str(folder))
        patch.setattr(gitstate, "git_state", lambda d: GitState(COMMIT, False))
        patch.setattr(cli, "_today", lambda: q2_run.DAY)
        patch.setattr(parameters, "q2_parameters", q2_run.reduced_parameters)
        patch.setattr(power, "power_grids", q2_run.reduced_grids)
        with contextlib.redirect_stdout(out):
            assert main(["q2"]) == 0
    (name,) = _estimations(folder)
    return EstimationRun(folder, out.getvalue(), folder / "resultats" / "Q2" / name)


def test_the_estimation_writes_the_figure(estimation_run: EstimationRun) -> None:
    """Correctifs de la PR #52, 3 bis.14 : le principal estimé, ``figure.html`` porte
    la figure (sa légende et le graphique), pas la phrase « pas de figure » ;
    ``figure.csv`` a ses points."""
    page = (estimation_run.written / "figure.html").read_text(encoding="utf-8")
    assert "Pas de figure" not in page
    assert "Résidus partiels de la date, montées longues" in page
    assert "Plotly.newPlot(" in page
    lines = (estimation_run.written / "figure.csv").read_text(encoding="utf-8")
    assert "\npoint," in lines


def test_each_journal_line_carries_the_commit(estimation_run: EstimationRun) -> None:
    """Correctifs de la PR #52, 3 bis.14 : chaque ligne d'``essais.jsonl`` porte le
    commit du code exécuté (celui des fixtures) et le nom du dossier écrit."""
    lines = _journal_lines(estimation_run.folder)
    assert len(lines) == 24
    records = [json.loads(line) for line in lines]
    assert all(r["commit"] == COMMIT for r in records)
    assert all(r["execution"] == estimation_run.written.name for r in records)


def test_the_s19_summary_line(estimation_run: EstimationRun) -> None:
    """Correctifs de la PR #52, 3 bis.14 : la ligne de S19 du résumé, écrite en dur
    (``κ`` estimé : la ligne n'a pas de lecture)."""
    assert "S19 : estime" in estimation_run.out.splitlines()


def test_the_estimation_provenance_names_the_figure_key(
    estimation_run: EstimationRun,
) -> None:
    """Correctifs de la PR #52, 3 bis.11 : une provenance d'estimation avec figure : sa
    clé de générateur ``[20261115, 2, 0, 2]`` écrite en dur ; le texte trié."""
    text = (estimation_run.written / "provenance.json").read_text(encoding="utf-8")
    document = json.loads(text)
    assert document["figure"]["cle"] == [20261115, 2, 0, 2]
    assert document["commit"] == COMMIT
    assert text == (
        json.dumps(document, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    )
