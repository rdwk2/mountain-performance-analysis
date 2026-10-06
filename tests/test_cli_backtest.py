"""La commande ``mperf backtest`` (§ 6.3, §§ 7.3, 7.4, 7.6 et § 8.1, tests 8 et 9,
du brief M4b-5 ; ``0010`` D14, D15).

8. La synthèse au caractère près (§ 7.3), le rapport complet (§ 7.4) et ses lignes
   prescrites, une seconde exécution, le seuil des descentes, un parcours sans jour
   (décision Q18), et l'âge de la courbe toujours signé (précision 1 de la relecture
   du plan).
9. Les refus de la commande et leurs ordres (§ 7.6) : rien n'est écrit, ou le sceau
   est publié (décisions Q15 et Q17).

``MPA_DATA_DIR`` pointe toujours dans un dossier temporaire et ``cli.git_state`` est
toujours remplacé par un état fixé (§ 7.0) : aucun test ne lit l'arbre du dépôt ni le
vrai dossier de données. Un appel qui laisserait s'échapper une interruption au
clavier fait échouer le test (``pytest.fail``) au lieu d'arrêter pytest.
"""

import contextlib
import hashlib
import io
import re
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pytest

import mountain_perf
import mountain_perf.backtest.execution as execution
import mountain_perf.cli as cli
from fixtures.backtest_values import SCORED
from fixtures.backtest_world import COMMIT, COURBE, write_world
from mountain_perf.backtest import (
    EVENTS_FILE,
    MISSING_ORDER,
    BacktestRun,
    GitState,
    read_registry,
)
from mountain_perf.schemas import EventKind, OutingScores
from test_backtest_execution import (
    Manifest,
    files,
    outing,
    route_b_without_day,
    world_variant,
)

FIXTURES = Path(__file__).parent / "fixtures"
SYNTHESIS = (FIXTURES / "backtest_synthese.txt").read_text(encoding="utf-8")
EXTRACTS = (FIXTURES / "backtest_rapport_extraits.txt").read_text(encoding="utf-8")
PACKAGE = Path(mountain_perf.__file__).resolve().parent
REPORT = Path("rapports") / "backtest-0002.txt"


@dataclass
class Outcome:
    """Un appel de la commande : code, sorties, dossiers et états git demandés."""

    code: int
    out: str
    err: str
    data: Path
    asked: list[Path] = field(default_factory=list)

    def report(self, name: Path = REPORT) -> str:
        data = (self.data / name).read_bytes()
        assert b"\r" not in data
        return data.decode("utf-8")

    def seal(self) -> str:
        """Le ``sha256`` de la dernière ligne du journal."""
        journal = (self.data / "registre" / EVENTS_FILE).read_bytes()
        return hashlib.sha256(journal.split(b"\n")[-2]).hexdigest()

    def kinds(self) -> tuple[EventKind, ...]:
        return tuple(e.kind for e in read_registry(self.data / "registre").events)


def call(
    monkeypatch: pytest.MonkeyPatch,
    data: Path,
    arguments: list[str],
    *,
    modified: bool = False,
) -> Outcome:
    """``mperf <arguments>``, ``MPA_DATA_DIR`` = ``data``, l'état git fixé (propre
    sauf ``modified``) et noté ; une interruption échappée fait échouer le test."""
    outcome = Outcome(0, "", "", data)

    def fixed_state(directory: Path) -> GitState:
        outcome.asked.append(directory)
        return GitState(COMMIT, modified)

    monkeypatch.setenv("MPA_DATA_DIR", str(data))
    monkeypatch.setattr(cli, "git_state", fixed_state)
    out, err = io.StringIO(), io.StringIO()
    try:
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            outcome.code = cli.main(arguments)
    except KeyboardInterrupt:
        pytest.fail("une interruption au clavier s'est échappée de la commande")
    outcome.out, outcome.err = out.getvalue(), err.getvalue()
    return outcome


def backtest(
    monkeypatch: pytest.MonkeyPatch,
    data: Path,
    manifest: Path,
    *extra: str,
    curve: Path = COURBE,
    modified: bool = False,
) -> Outcome:
    return call(
        monkeypatch,
        data,
        ["backtest", str(manifest), "--curve", str(curve), *extra],
        modified=modified,
    )


def lines_of(text: str) -> list[str]:
    assert text.endswith("\n")
    return text.split("\n")[:-1]


def contiguous(block: list[str], lines: list[str]) -> list[int]:
    """Les rangs où ``block`` est une suite contiguë de ``lines``."""
    n = len(block)
    return [i for i in range(len(lines) - n + 1) if lines[i : i + n] == block]


@pytest.fixture
def data(tmp_path: Path) -> Path:
    data = tmp_path / "donnees"
    data.mkdir()
    return data


@pytest.fixture(scope="module")
def world(tmp_path_factory: pytest.TempPathFactory) -> Iterator[Outcome]:
    """La commande sur le monde, une fois pour le module."""
    root = tmp_path_factory.mktemp("commande")
    data = root / "donnees"
    data.mkdir()
    manifest = write_world(root / "monde")
    with pytest.MonkeyPatch.context() as monkeypatch:
        yield backtest(monkeypatch, data, manifest)


# ---------------------------------------------------------------------------
# 8. La commande sur le monde (§§ 7.3, 7.4 ; D14, D15)
# ---------------------------------------------------------------------------


def test_synthesis_is_the_expected_text(world: Outcome) -> None:
    """§ 7.3, précision de D15 (M4b-5) : la synthèse au caractère près ; le sceau est
    l'empreinte de la dernière ligne du journal (précision de D14)."""
    assert (world.code, world.err) == (0, "")
    seal = world.seal()
    assert f"dernière ligne sha256 {seal}\n" in world.out
    assert world.out.replace(seal, "<sceau>") == SYNTHESIS


def test_git_state_of_the_executed_package(world: Outcome) -> None:
    """Décision Q7 : l'état git est demandé une fois, pour le dossier du paquet
    exécuté, pas pour le dossier courant."""
    assert world.asked == [PACKAGE]


def _heads(lines: list[str]) -> list[str]:
    """Les têtes de section : l'étiquette d'une ligne qui ne commence pas par une
    espace (colonne de 13 caractères)."""
    return [line[:13].strip() for line in lines if not line.startswith(" ")]


DETAIL_HEADS = [
    "performance",
    "référence",
    "trace",
    "départ",
    "arrivée",
    "points",
    "segments",
    "couverture",
    "préfixe",
    "horloges",
    "épisodes",
    "passages",
    "v0 brut",
    "usage",
    "C_k",
    "K",
    "contrôle",
]


def test_report_and_its_section_heads(world: Outcome) -> None:
    """Précision de D15 (M4b-5), § 6.3 : le rapport ``rapports/backtest-0002.txt``,
    UTF-8 sans ``\\r``, commence par la synthèse ; ses têtes se suivent — six tables
    d'agrégats, deux références, descentes, géométrie, douze détails (sans ``C_k``
    ni ``K`` pour une sortie sans référence), deux non scorées, la légende ; 2 020
    lignes."""
    report = world.report()
    assert report.startswith(world.out)
    lines = lines_of(report)
    assert len(lines) == 2020
    assert all(line == line.rstrip() and line for line in lines)
    expected = _heads(lines_of(SYNTHESIS))
    expected += ["agrégats"] * 6 + ["référence"] * 2 + ["descentes", "géométrie"]
    for outing_id in SCORED:
        without = outing_id.startswith("libre-")
        expected += [h for h in DETAIL_HEADS if not (without and h in ("C_k", "K"))]
    expected += ["non scorée"] * 2 + ["légende"]
    assert _heads(lines) == expected


def test_detail_of_an_outing_is_the_match_output(
    world: Outcome, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """§ 6.3, point 6 : le détail de ``a-2026-06-03`` — ses trois lignes d'en-tête,
    puis, ligne pour ligne, la sortie de ``mperf match <préparé> <trace> --curve``."""
    lines = lines_of(world.report())
    head = (
        "performance  2026-06-03 — a-2026-06-03 ; parcours a ; jeu répétabilité ; "
        "entraînement"
    )
    (i,) = [k for k, line in enumerate(lines) if line == head]
    assert lines[i + 1 : i + 3] == [
        "             origine o_j 2026-05-27 00:00 (Paris) ; âge de la courbe +122 "
        "jours au jour J, +115 à o_j",
        "             (M+U) θ_haut égale l'écoulé : aucun arrêt confirmé sur le "
        "support admis",
    ]
    world_root = tmp_path / "monde"
    write_world(world_root)
    match = call(
        monkeypatch,
        tmp_path,
        [
            "match",
            str(world_root / "gpx/a/prepare.gpx"),
            str(world_root / "gpx/a/a03.gpx"),
            "--curve",
            str(COURBE),
        ],
    )
    assert match.code == 0
    expected = lines_of(match.out)
    assert lines[i + 3 : i + 3 + len(expected)] == expected
    assert lines[i + 3 + len(expected)].startswith("performance  2026-06-04")


def test_the_eight_extracts(world: Outcome) -> None:
    """§ 7.4 : chacun des huit extraits est une suite contiguë des lignes du rapport,
    le dernier à sa fin."""
    lines = lines_of(world.report())
    blocks = [block.split("\n") for block in EXTRACTS.rstrip("\n").split("\n\n")]
    assert len(blocks) == 8
    for block in blocks:
        assert contiguous(block, lines), block[0]
    assert lines[-len(blocks[-1]) :] == blocks[-1]


def test_causes_of_unavailable_fold_levels(world: Outcome) -> None:
    """Décision Q4 : sous la référence de ``a``, une seule ligne explique les ``|L|``
    de pli indisponibles sous les cinq ``M θ`` — le temps nul du dernier segment, et
    sa cellule nulle sur les trois jours."""
    lines = lines_of(world.report())
    cause = (
        "             M θ1, M θ2, M θ3, M θ4, M θ5 : |L| indisponible sur 3 plis sur "
        "3 : 3 temps nul ; cellules nulles : montée k 17 (2026-06-03, 2026-06-06, "
        "2026-06-10)"
    )
    (k,) = [i for i, line in enumerate(lines) if line == cause]
    heads = [i for i, line in enumerate(lines) if line.startswith("référence    ")]
    a = next(i for i in heads if lines[i].startswith("référence    a — "))
    b = next(i for i in heads if lines[i].startswith("référence    b — "))
    assert a < k < b


def test_underrepresented_subclass_mentions(world: Outcome) -> None:
    """§ 6.3, point 4, précision de D6 : une raide d'un segment est « trop peu
    représentée » ; une sous-classe vide, sans mention."""
    lines = lines_of(world.report())
    assert (
        lines.count(
            "             b-2026-06-04, usage — 3 roulantes, 1 raide (trop peu "
            "représentée), 2 non départagées"
        )
        == 1
    )
    assert (
        lines.count(
            "             libre-2026-06-12, contrôle — 4 roulantes, 0 raide, 0 non "
            "départagée"
        )
        == 1
    )
    assert (
        lines.count("             total : 38 roulantes, 20 raides, 14 non départagées")
        == 1
    )


def test_legend_of_the_zero_time(world: Outcome) -> None:
    """Précision de D15, décision Q4 : la légende explique le temps nul sous un
    ``M θ``."""
    assert (
        "             temps nul sous un M θ : un segment admis sans temps en mouvement "
        "sous ce seuil, souvent le dernier d'une trace arrêtée à l'arrivée (fenêtre "
        "de 0010 D5.2) ; D8 ne l'ajuste pas (cellule nulle, choix M02) : |L| du pli et "
        "F indisponibles"
    ) in lines_of(world.report())


def test_every_missing_motif_has_its_label() -> None:
    """§ 6.3 : chaque motif de ``MISSING_ORDER`` a son libellé, dans le même ordre —
    ceux de ``mperf match``, puis les autres noms de ``0010`` D0, dont ``trou`` et
    ``non calé``, puis ceux du rapport."""
    assert tuple(cli.MISSING_LABELS) == MISSING_ORDER
    assert list(cli.MISSING_LABELS.values()) == [
        "absent",
        "ambigu",
        "tangente indéfinie",
        "trou",
        "écart intérieur",
        "support insuffisant",
        "temps nul",
        "référence non identifiée",
        "non-convergence",
        "erreur du modèle",
        "non calé",
        "jour multi-sorties",
        "trop peu représenté",
        "non scorée",
        "sans référence",
    ]


def test_second_execution(
    tmp_path: Path, data: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Précision de D14, D15 : une seconde exécution sur le même registre — ses
    événements 3 et 4, ``backtest-0004.txt`` ; les deux rapports."""
    manifest = write_world(tmp_path / "monde")
    first = backtest(monkeypatch, data, manifest)
    second = backtest(monkeypatch, data, manifest)
    assert (first.code, second.code) == (0, 0)
    assert "registre     déclaration 3, résultat 4 ;" in second.out
    assert "rapport      rapports/backtest-0004.txt\n" in second.out
    assert second.kinds() == (EventKind.DECLARATION, EventKind.RESULT) * 2
    assert first.report().startswith(first.out)
    assert second.report(Path("rapports") / "backtest-0004.txt").startswith(second.out)


def test_descent_threshold(
    tmp_path: Path, data: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Décision Q5, précision de D6 : ``--descent-threshold 0.6`` — « au seuil 0.60 »,
    38 roulantes, 34 raides, aucune non départagée ; deux raides « trop peu
    représentées », au pluriel."""
    outcome = backtest(
        monkeypatch, data, write_world(tmp_path / "monde"), "--descent-threshold", "0.6"
    )
    assert outcome.code == 0
    assert (
        "diagnostics  descentes roulantes et raides au seuil 0.60 ; géométrie usage − "
        "contrôle : rapport complet\n"
    ) in outcome.out
    lines = lines_of(outcome.report())
    assert (
        "descentes    roulantes et raides au seuil 0.60 (0010 D6) ; diagnostic, ni "
        "cible ni garde-fou"
    ) in lines
    assert "             total : 38 roulantes, 34 raides, 0 non départagée" in lines
    assert (
        "             a-2026-06-10, usage — 3 roulantes, 2 raides (trop peu "
        "représentées), 0 non départagée"
    ) in lines


@pytest.mark.parametrize(
    ("with_multi_outing_day", "head"),
    [
        (True, "référence    b — aucun jour ; jours multi-sorties écartés 2026-06-12"),
        (False, "référence    b — aucun jour"),
    ],
    ids=["with-multi-outing-day", "without"],
)
def test_route_without_any_day(
    tmp_path: Path,
    data: Path,
    monkeypatch: pytest.MonkeyPatch,
    with_multi_outing_day: bool,
    head: str,
) -> None:
    """Décision Q18 : ``b-2026-06-04`` et ``b-2026-06-08`` sans trace, avec puis sans
    ``b-2026-06-12`` — la synthèse publie ses ``F`` en support insuffisant, à côté de
    v0 sans valeur ; le rapport, une seule tête de sa référence, « aucun jour »."""
    manifest = world_variant(
        tmp_path / "monde", route_b_without_day(with_multi_outing_day)
    )
    outcome = backtest(monkeypatch, data, manifest)
    assert outcome.code == 0
    assert (
        "             b — 0 jour ; écoulé, usage : F du parcours, v0 sur ses jours\n"
        "             |L|             F support insuffisant (m 0)  v0 — (0)\n"
    ) in outcome.out
    lines = lines_of(outcome.report())
    heads = [line for line in lines if line.startswith("référence    b ")]
    assert heads == [head]


def test_curve_age_is_always_signed(
    tmp_path: Path, data: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Précision 1 de la relecture du plan (D15, âge de la courbe) : un âge s'écrit
    toujours signé, ``+0`` compris, le moins typographique pour un âge négatif,
    « jours » invariable — la courbe recopiée, estimée le 2026-06-10, postérieure à
    neuf origines."""
    curves = tmp_path / "courbe"
    curves.mkdir()
    curve = curves / COURBE.name
    curve.write_bytes(COURBE.read_bytes())
    meta = COURBE.with_name("courbe_synthetique.meta.json")
    text = meta.read_bytes().decode("utf-8")
    old = '"generated_at": "2026-02-01T12:00:00+01:00"'
    assert text.count(old) == 1
    new = text.replace(old, '"generated_at": "2026-06-10T12:00:00+02:00"')
    (curves / meta.name).write_bytes(new.encode("utf-8"))
    outcome = backtest(monkeypatch, data, write_world(tmp_path / "monde"), curve=curve)
    assert outcome.code == 0
    assert (
        "             âge au jour J : de −7 à +17 jours ; postérieure à l'origine de 9 "
        "performances sur 12"
    ) in lines_of(outcome.out)
    assert (
        lines_of(outcome.report()).count(
            "             origine o_j 2026-06-03 00:00 (Paris) ; âge de la courbe +0 "
            "jours au jour J, −7 à o_j"
        )
        == 1
    )


# ---------------------------------------------------------------------------
# 9. Refus de la commande (§ 7.6 ; décisions Q7, Q15, Q17)
# ---------------------------------------------------------------------------


def test_modified_tree_is_refused(
    tmp_path: Path, data: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Précision de D14 (M4b-5), décision Q7 : un arbre de travail modifié est
    refusé avant tout écrit."""
    outcome = backtest(
        monkeypatch, data, write_world(tmp_path / "monde"), modified=True
    )
    assert (outcome.code, outcome.out) == (1, "")
    assert outcome.err == (
        "Erreur : l'arbre de travail porte des modifications non commitées : just "
        "backtest enregistre le commit du code exécuté (0010 D14). Committer d'abord ; "
        "rien n'est écrit.\n"
    )
    assert list(data.iterdir()) == []


def test_curve_is_required(
    tmp_path: Path, data: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Précision de D2.6 (M4b-4) : la courbe est une entrée déclarée de l'exécution ;
    ``--curve`` absent, la ligne d'usage puis le message, code 1 ; rien n'est
    écrit."""
    manifest = write_world(tmp_path / "monde")
    outcome = call(monkeypatch, data, ["backtest", str(manifest)])
    assert (outcome.code, outcome.out) == (1, "")
    lines = lines_of(outcome.err)
    assert lines[0].startswith("usage: mperf backtest ")
    assert lines[-1] == (
        "Erreur : --curve est obligatoire : la courbe est une entrée déclarée de "
        "l'exécution (0010 D2.6)."
    )
    assert list(data.iterdir()) == []
    assert outcome.asked == []


@pytest.mark.parametrize("value", ["0.59", "1.01"])
def test_threshold_out_of_range_is_refused(
    tmp_path: Path, data: Path, monkeypatch: pytest.MonkeyPatch, value: str
) -> None:
    """Décision Q5 : un seuil hors de ``[0,60 ; 1]`` est refusé, avant tout."""
    manifest = write_world(tmp_path / "monde")
    outcome = backtest(monkeypatch, data, manifest, "--descent-threshold", value)
    assert (outcome.code, outcome.out) == (1, "")
    assert outcome.err == (
        "Erreur : descent_subclass_threshold doit être dans [0.6, 1.0], "
        f"reçu {value}.\n"
    )
    assert list(data.iterdir()) == []
    assert outcome.asked == []


def test_data_dir_is_required(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """§ 6.3, étape 2 : sans ``MPA_DATA_DIR``, le message de ``ConfigError``."""
    manifest = write_world(tmp_path / "monde")
    monkeypatch.setattr(cli, "git_state", lambda directory: GitState(COMMIT, False))
    monkeypatch.delenv("MPA_DATA_DIR", raising=False)
    err = io.StringIO()
    with contextlib.redirect_stderr(err), contextlib.redirect_stdout(io.StringIO()):
        code = cli.main(["backtest", str(manifest), "--curve", str(COURBE)])
    assert code == 1
    assert err.getvalue().startswith(
        "Erreur : La variable d'environnement MPA_DATA_DIR n'est pas définie."
    )


def _old_report(data: Path) -> Path:
    path = data / REPORT
    path.parent.mkdir()
    path.write_bytes(b"ancien rapport\n")
    return path


def test_existing_report_is_refused(
    tmp_path: Path, data: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Précision de D15 (M4b-5) : un rapport n'est jamais réécrit ; un rapport prévu
    déjà présent (un registre neuf à côté d'anciens rapports) est refusé avant tout
    écrit — aucun registre, l'ancien rapport intact."""
    old = _old_report(data)
    outcome = backtest(monkeypatch, data, write_world(tmp_path / "monde"))
    assert (outcome.code, outcome.out) == (1, "")
    assert outcome.err == (
        "Erreur : le rapport rapports/backtest-0002.txt existe déjà : il n'est jamais "
        "réécrit. Un registre neuf à côté d'anciens rapports ? Déplacer ces rapports ; "
        "rien n'est écrit.\n"
    )
    assert not (data / "registre").exists()
    assert old.read_bytes() == b"ancien rapport\n"


def test_modified_tree_is_refused_before_the_existing_report(
    tmp_path: Path, data: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """§ 7.6, ordre : un arbre modifié **et** un rapport existant — le refus de
    l'arbre."""
    _old_report(data)
    outcome = backtest(
        monkeypatch, data, write_world(tmp_path / "monde"), modified=True
    )
    assert outcome.code == 1
    assert outcome.err.startswith("Erreur : l'arbre de travail porte")
    assert files(data) == {"rapports/backtest-0002.txt": b"ancien rapport\n"}


def test_no_performance_publishes_the_failure_hash(
    tmp_path: Path, data: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Précision de D14 (M4b-5), décision Q15 : sans performance dans le domaine, un
    ÉCHEC « non évaluable » enregistré, son empreinte publiée ; aucun rapport."""

    def july(manifest: Manifest) -> None:
        manifest["domain_start_date"] = "2026-07-01"

    outcome = backtest(monkeypatch, data, world_variant(tmp_path / "monde", july))
    assert (outcome.code, outcome.out) == (1, "")
    assert outcome.err == (
        "Erreur : aucune performance dans le domaine : ÉCHEC enregistré (événement 2 ; "
        f"dernière ligne sha256 {outcome.seal()}).\n"
    )
    assert outcome.kinds() == (EventKind.DECLARATION, EventKind.FAILURE)
    assert not (data / "rapports").exists()


def test_keyboard_interrupt_during_the_computation(
    tmp_path: Path, data: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Décision Q17 : une interruption au clavier pendant le calcul devient un ÉCHEC
    technique, son empreinte publiée ; aucun rapport."""

    def interrupted(*args: Any, **kwargs: Any) -> OutingScores:
        raise KeyboardInterrupt

    monkeypatch.setattr(execution, "v0_scores", interrupted)
    outcome = backtest(monkeypatch, data, write_world(tmp_path / "monde"))
    assert (outcome.code, outcome.out) == (1, "")
    assert outcome.err == (
        "Erreur : échec de l'exécution, ÉCHEC enregistré (événement 2 ; dernière ligne "
        f"sha256 {outcome.seal()}) : KeyboardInterrupt\n"
    )
    assert outcome.kinds() == (EventKind.DECLARATION, EventKind.FAILURE)
    assert not (data / "rapports").exists()


def _reports_is_a_file(data: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    (data / "rapports").write_bytes(b"")


def _report_raises(error: BaseException) -> Callable[[Path, pytest.MonkeyPatch], None]:
    def change(data: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        def raising(run: BacktestRun, summary: object, threshold: float) -> str:
            raise error

        monkeypatch.setattr(cli, "_full_report", raising)

    return change


@pytest.mark.parametrize(
    ("change", "reason"),
    [
        (_reports_is_a_file, "FileExistsError (errno 17)"),
        (
            _report_raises(ValueError("valeur inattendue")),
            "ValueError : valeur inattendue",
        ),
        (_report_raises(KeyboardInterrupt()), "KeyboardInterrupt"),
    ],
    ids=["reports-is-a-file", "valueerror", "keyboard-interrupt"],
)
def test_report_not_written_publishes_the_seal(
    tmp_path: Path,
    data: Path,
    monkeypatch: pytest.MonkeyPatch,
    change: Callable[[Path, pytest.MonkeyPatch], None],
    reason: str,
) -> None:
    """Décisions Q15 et Q17 : un rapport qui ne se calcule ou ne s'écrit pas après le
    RÉSULTAT — ``rapports`` est un fichier, le calcul lève, ou une interruption au
    clavier — publie le sceau dans l'erreur de la commande ; aucun rapport."""
    change(data, monkeypatch)
    outcome = backtest(monkeypatch, data, write_world(tmp_path / "monde"))
    assert (outcome.code, outcome.out) == (1, "")
    assert outcome.err == (
        "Erreur : RÉSULTAT enregistré (événement 2 ; dernière ligne sha256 "
        f"{outcome.seal()}) ; rapport rapports/backtest-0002.txt non écrit : {reason}\n"
    )
    assert outcome.kinds() == (EventKind.DECLARATION, EventKind.RESULT)
    assert not (data / REPORT).exists()


# ---------------------------------------------------------------------------
# Correctifs de la relecture de la PR #20
# ---------------------------------------------------------------------------

NO_SCORED_SYNTHESIS = (
    "backtest     v0 brut, protocole 0010 — commit 0123456789ab ; Δ 250 m, ε 30 m, "
    "r_c 15 m\n"
    "registre     déclaration 1, résultat 2 ; dernière ligne sha256 <sceau>\n"
    "             à recopier au JOURNAL : l'empreinte de la dernière ligne scelle le "
    "registre\n"
    "manifeste    manifeste.json   sha256 87001248… — 2 sorties, 2 performances\n"
    "courbe       courbe_synthetique.csv   sha256 6767dd38… — estimée le 2026-02-01\n"
    "             âge au jour J : de +135 à +139 jours ; postérieure à l'origine de 0 "
    "performance sur 2\n"
    "             mouvement historique non harmonisé ; biais d'opérateur de pente "
    "(0009, 0010 D6)\n"
    "performances jour        sortie                      jeu            étiquette     "
    "couverture  préfixe    L           q_usage\n"
    "             2026-06-16  c-2026-06-16                développement  entraînement  "
    "non scorée : trace refusée (c16.gpx) : c16.gpx, trkpt[0].time : instant "
    "manquant.\n"
    "             2026-06-20  a-2026-06-20                développement  entraînement  "
    "non scorée : sortie non tracée\n"
    "agrégats     usage, écoulé ; moyenne à poids égal par performance (effectif) ; "
    "détail et motifs : rapport complet\n"
    "                             répétabilité        développement       "
    "confirmation\n"
    "             L               — (0)               — (0)               — (0)\n"
    "             |L|             — (0)               — (0)               — (0)\n"
    "             A               — (0)               — (0)               — (0)\n"
    "             W               — (0)               — (0)               — (0)\n"
    "             B               — (0)               — (0)               — (0)\n"
    "             C_comp          — (0)               — (0)               — (0)\n"
    "             montée E_R−L    — (0)               — (0)               — (0)\n"
    "             montée |E_R|    — (0)               — (0)               — (0)\n"
    "             montée D_R      — (0)               — (0)               — (0)\n"
    "             plat E_R−L      — (0)               — (0)               — (0)\n"
    "             plat |E_R|      — (0)               — (0)               — (0)\n"
    "             plat D_R        — (0)               — (0)               — (0)\n"
    "             descente E_R−L  — (0)               — (0)               — (0)\n"
    "             descente |E_R|  — (0)               — (0)               — (0)\n"
    "             descente D_R    — (0)               — (0)               — (0)\n"
    "             mixte E_R−L     — (0)               — (0)               — (0)\n"
    "             mixte |E_R|     — (0)               — (0)               — (0)\n"
    "             mixte D_R       — (0)               — (0)               — (0)\n"
    "             max |C_k|       — (0)               — (0)               — (0)\n"
    "             q_usage         — (0)               — (0)               — (0)\n"
    "diagnostics  descentes roulantes et raides au seuil 0.80 ; géométrie usage − "
    "contrôle : rapport complet\n"
    "rapport      rapports/backtest-0002.txt\n"
)
"""La synthèse d'une exécution sans sortie scorée (K1) : celle du prototype de la
conception ; aucune ligne « référence » sans parcours de répétabilité."""


def test_run_without_any_scored_outing_writes_its_report(
    tmp_path: Path, data: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Précision de D15 (le rapport s'écrit en entier à chaque exécution), § 6.3,
    point 5 : des performances dont aucune sortie n'est scorée (``c-2026-06-16``, trace
    refusée ; ``a-2026-06-20``, non tracée) — le RÉSULTAT, sa synthèse, et son rapport,
    dont la géométrie n'a aucune ligne de sortie."""

    def unscored_only(manifest: Manifest) -> None:
        outings = manifest["outings"]
        assert isinstance(outings, list)
        kept = ("c-2026-06-16", "a-2026-06-20")
        manifest["outings"] = [o for o in outings if o["id"] in kept]

    manifest = world_variant(tmp_path / "monde", unscored_only)
    outcome = backtest(monkeypatch, data, manifest)
    assert (outcome.code, outcome.err) == (0, "")
    assert outcome.kinds() == (EventKind.DECLARATION, EventKind.RESULT)
    assert outcome.out.replace(outcome.seal(), "<sceau>") == NO_SCORED_SYNTHESIS
    lines = lines_of(outcome.report())
    assert "             total : 0 roulante, 0 raide, 0 non départagée" in lines
    block = [
        "géométrie    usage − contrôle = ln(ΣP_usage / ΣP_contrôle) sur le support "
        "admis (0010 D3), v0 brut",
        "                             G                   montée              plat"
        "                descente            mixte",
        "non scorée   c-2026-06-16 — trace refusée (c16.gpx) : c16.gpx, trkpt[0].time "
        ": instant manquant.",
        "non scorée   a-2026-06-20 — sortie non tracée",
    ]
    assert len(contiguous(block, lines)) == 1


def test_unscored_outing_of_a_multi_outing_day(
    tmp_path: Path, data: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """§ 6.3, synthèse : « (jour multi-sorties) » à la fin de chaque ligne d'un tel
    jour, celle d'une sortie non scorée comprise — la trace de ``libre-2026-06-12``
    sans horodatage, ses instants déclarés."""

    def declared_instants(manifest: Manifest) -> None:
        entry = outing(manifest, "libre-2026-06-12")
        entry["start"] = "2026-06-12T19:00:00+02:00"
        entry["end"] = "2026-06-12T19:40:00+02:00"

    manifest = world_variant(tmp_path / "monde", declared_instants)
    trace = tmp_path / "monde" / "gpx" / "libre" / "libre12.gpx"
    text = trace.read_bytes().decode("utf-8")
    untimed = re.sub(r"<time>[^<]*</time>", "", text)
    assert untimed != text
    trace.write_bytes(untimed.encode("utf-8"))
    outcome = backtest(monkeypatch, data, manifest)
    assert outcome.code == 0
    day = [
        line
        for line in lines_of(outcome.out)
        if line.startswith("             2026-06-12  ")
    ]
    assert day == [
        "             2026-06-12  a-2026-06-12                répétabilité   "
        "entraînement  100.00 %    4.26 km    −0.002133   0.014189 "
        "(jour multi-sorties)",
        "             2026-06-12  b-2026-06-12                répétabilité   "
        "entraînement  99.96 %     3.64 km    +0.015959   0.015832 "
        "(jour multi-sorties)",
        "             2026-06-12  libre-2026-06-12            développement  "
        "entraînement  non scorée : trace refusée (libre12.gpx) : libre12.gpx, "
        "trkpt[0].time : instant manquant. (jour multi-sorties)",
    ]


class _InterruptedWrite:
    """Un fichier dont l'écriture s'interrompt à mi-texte (Ctrl-C)."""

    def __init__(self, stream: Any) -> None:
        self.stream = stream

    def __enter__(self) -> "_InterruptedWrite":
        return self

    def __exit__(self, *exc: object) -> None:
        self.stream.close()

    def write(self, text: str) -> int:
        self.stream.write(text[: len(text) // 2])
        self.stream.flush()
        raise KeyboardInterrupt


def test_interrupted_write_leaves_no_report(
    tmp_path: Path, data: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Décision Q17, § 6.3, étape 6 : une interruption au clavier pendant l'écriture
    du rapport publie le sceau dans l'erreur d'un rapport non écrit — et le fichier
    commencé ne garde pas son nom."""
    real_open = Path.open

    def opened(path: Path, mode: str = "r", *args: Any, **kwargs: Any) -> Any:
        stream = real_open(path, mode, *args, **kwargs)
        return _InterruptedWrite(stream) if mode == "x" else stream

    monkeypatch.setattr(Path, "open", opened)
    outcome = backtest(monkeypatch, data, write_world(tmp_path / "monde"))
    assert (outcome.code, outcome.out) == (1, "")
    assert outcome.err == (
        "Erreur : RÉSULTAT enregistré (événement 2 ; dernière ligne sha256 "
        f"{outcome.seal()}) ; rapport rapports/backtest-0002.txt non écrit : "
        "KeyboardInterrupt\n"
    )
    assert outcome.kinds() == (EventKind.DECLARATION, EventKind.RESULT)
    assert list((data / "rapports").iterdir()) == []
