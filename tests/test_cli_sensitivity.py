"""La commande ``mperf backtest … --sensitivity`` (brief M4d-3 ; précision de D15,
M4d-3 ; ``0010`` D13, D14), sur le monde de M4b-5 (``fixtures.backtest_world``).

- Sur le monde, une fois pour la session (``sensitivity_command``) : code 0 ; l'ordre
  des lignes de la sortie — l'empreinte de la DÉCLARATION centrale, la synthèse
  centrale (celle de ``just backtest``, au caractère près), une ligne par paire
  observée, l'empreinte de la DÉCLARATION de sensibilité, la synthèse de la
  sensibilité ; ses comptes de v0 brut, ceux du document de sensibilité du registre ;
  le rapport ``rapports/sensibilite-0004.txt`` : sa synthèse en tête, une rubrique par
  configuration dans l'ordre, la légende à la fin, aucune ligne vide, aucune espace
  en fin de ligne.
- Les deux noms de rapport, central et de sensibilité, refusés d'avance s'ils
  existent : rien n'est écrit au registre.
- Sans ``--sensitivity``, rien ne change : la synthèse de ``just backtest``, aucune
  ligne « paire ».

``MPA_DATA_DIR`` pointe dans un dossier temporaire et ``cli.git_state`` est remplacé
par un état fixé (aide ``backtest`` de ``test_cli_backtest.py``). Aucune donnée réelle.
"""

import hashlib
import re
import shutil
from pathlib import Path

import pytest

import mountain_perf.cli as cli
from fixtures.backtest_world import write_world
from fixtures.sensitivity_world import write_mini_world
from mountain_perf.backtest import (
    EVENTS_FILE,
    SENSITIVITY_CONFIGURATIONS,
    SENSITIVITY_PAIRS,
    BacktestRun,
    SensitivityEvaluation,
    axis_counts,
    count_trials,
    load_sensitivity,
    read_registry,
)
from mountain_perf.schemas import EventKind, ModelKind
from test_cli_backtest import SYNTHESIS, Outcome, backtest, contiguous, lines_of

CLOCK_LABELS = (
    ("écoulé",) * 9
    + tuple(f"M θ{k}" for k in range(1, 6))
    + tuple(f"(M+U) θ{k}" for k in range(1, 6))
)
"""Le libellé de l'horloge de chaque configuration, dans l'ordre de D13."""
TITLES = tuple(
    f"Δ {c.score_step_m:g} m, ε {c.lateral_tolerance_m:g} m, {label}"
    for c, label in zip(SENSITIVITY_CONFIGURATIONS, CLOCK_LABELS, strict=True)
)
"""Le titre de chaque configuration : ``Δ 100 m, ε 15 m, écoulé``…"""
COMPARATOR = 4
"""Le rang du comparateur, ``(250, 30)`` sous l'écoulé."""
REPORT = Path("rapports") / "sensibilite-0004.txt"
CENTRAL_REPORT = Path("rapports") / "backtest-0002.txt"
INDENT = " " * 13
HEAD = (
    "sensibilité  0010 D13 : qualifie la déclaration 1 et son résultat 2 ; 19 "
    "configurations, 9 paires (Δ, ε) ; rapportée, jamais utilisée pour choisir"
)
LEGEND = (
    "légende      sensibilité de 0010 D13 : rapportée, jamais utilisée pour choisir ; "
    "chaque configuration est comparée au comparateur, Δ 250 m, ε 30 m, sous "
    "l'écoulé"
)
EXISTS = (
    "Erreur : le rapport rapports/{name} existe déjà : il n'est jamais réécrit. Un "
    "registre neuf à côté d'anciens rapports ? Déplacer ces rapports ; rien n'est "
    "écrit.\n"
)


_RUNS: list[Outcome] = []


def sensitivity_command(factory: pytest.TempPathFactory) -> Outcome:
    """``mperf backtest manifeste.json --curve courbe.csv --sensitivity`` sur le monde,
    exécutée au premier appel de la session (le README la relit aussi)."""
    if not _RUNS:
        root = factory.mktemp("commande-sensibilite")
        data = root / "donnees"
        data.mkdir()
        manifest = write_world(root / "monde")
        with pytest.MonkeyPatch.context() as monkeypatch:
            _RUNS.append(backtest(monkeypatch, data, manifest, "--sensitivity"))
    return _RUNS[0]


@pytest.fixture(scope="module")
def command(tmp_path_factory: pytest.TempPathFactory) -> Outcome:
    return sensitivity_command(tmp_path_factory)


def _seals(outcome: Outcome) -> list[str]:
    """L'empreinte de chaque ligne du journal, dans l'ordre."""
    journal = (outcome.data / "registre" / EVENTS_FILE).read_bytes()
    return [hashlib.sha256(line).hexdigest() for line in journal.split(b"\n")[:-1]]


def _parts(outcome: Outcome) -> tuple[list[str], list[str], str, list[str]]:
    """La sortie découpée : la synthèse centrale (sans la ligne de sa DÉCLARATION),
    les lignes « paire », la ligne de la DÉCLARATION de sensibilité, la synthèse de la
    sensibilité."""
    lines = lines_of(outcome.out)
    size = len(lines_of(SYNTHESIS))
    central = lines[1 : 1 + size]
    pairs = lines[1 + size : 1 + size + 8]
    return central, pairs, lines[1 + size + 8], lines[1 + size + 9 :]


# ---------------------------------------------------------------------------
# La commande sur le monde
# ---------------------------------------------------------------------------


def test_command_succeeds(command: Outcome) -> None:
    """Précision de D15 (M4d-3) : la commande et sa sensibilité réussissent, rien sur
    la sortie d'erreur ; le registre porte la centrale (1, 2) puis la sensibilité (3,
    4), qui compte à part."""
    assert (command.code, command.err) == (0, "")
    log = read_registry(command.data / "registre")
    assert [e.kind for e in log.events] == [
        EventKind.DECLARATION,
        EventKind.RESULT,
    ] * 2
    trials = count_trials(log)
    assert (trials.declarations, trials.without_effect, trials.sensitivities) == (
        2,
        1,
        1,
    )


def test_order_of_the_output(command: Outcome) -> None:
    """Précision de D15 (M4d-3) : l'empreinte de la DÉCLARATION centrale, la synthèse
    centrale (celle de ``just backtest``, au caractère près), une ligne par paire
    observée dans l'ordre, l'empreinte de la DÉCLARATION de sensibilité dès son ajout,
    puis la synthèse de la sensibilité — ce qu'elle qualifie, le registre et son sceau,
    une ligne par configuration, le rapport."""
    seals = _seals(command)
    first = lines_of(command.out)[0]
    assert first == f"déclaration  1 enregistrée ; dernière ligne sha256 {seals[0]}"
    central, pairs, declared, summary = _parts(command)
    text = "\n".join(central) + "\n"
    assert f"dernière ligne sha256 {seals[1]}\n" in text
    assert text.replace(seals[1], "<sceau>") == SYNTHESIS
    assert pairs == [
        f"paire        Δ {step:g} m, ε {tolerance:g} m observée"
        for step, tolerance in SENSITIVITY_PAIRS
        if (step, tolerance) != (250.0, 30.0)
    ]
    assert declared == (
        f"sensibilité  déclaration 3 enregistrée ; dernière ligne sha256 {seals[2]}"
    )
    assert summary[0] == HEAD
    assert summary[1] == (
        f"registre     déclaration 3, résultat 4 ; dernière ligne sha256 {seals[3]}"
    )
    assert summary[2] == (
        f"{INDENT}à recopier au JOURNAL : l'empreinte de la dernière ligne scelle le "
        "registre"
    )
    assert summary[3].split() == [
        "v0",
        "brut",
        "valeurs",
        "comparées",
        "perdues",
        "gagnées",
        "support",
        "changé",
        "valeur",
        "changée",
    ]
    assert len(summary) == 4 + 19 + 2
    # Le nom du rapport s'imprime avec « / », sous Windows aussi.
    report = REPORT.as_posix()
    assert summary[-2:] == [f"{INDENT}* comparateur", f"rapport      {report}"]


def test_configuration_lines_count_v0_of_the_document(command: Outcome) -> None:
    """Précision de D15 (M4d-3) : une ligne par configuration, dans l'ordre, le
    comparateur marqué ; pour v0 brut, les valeurs comparées, perdues, gagnées, de
    support changé et changées — les comptes du document de sensibilité du
    registre."""
    registry = command.data / "registre"
    document = load_sensitivity(registry, read_registry(registry), 4)
    assert document is not None
    lines = _parts(command)[3][4 : 4 + 19]
    for rank, line in enumerate(lines):
        assert line.startswith(INDENT)
        tokens = line.split()
        mark = "*" if rank == COMPARATOR else ""
        assert tokens[0] == f"{rank + 1}{mark}"
        assert " ".join(tokens[1:-5]) == TITLES[rank]
        (counts,) = axis_counts(document.configurations[rank], (ModelKind.V0_RAW,))
        assert [int(t) for t in tokens[-5:]] == [
            counts.compared,
            counts.lost,
            counts.gained,
            counts.support,
            counts.value,
        ]


def test_sensitivity_report(command: Outcome) -> None:
    """Précision de D15 (M4d-3) : le rapport ``rapports/sensibilite-0004.txt`` (le
    numéro de son RÉSULTAT) reprend la synthèse de la sensibilité, puis une rubrique
    par configuration dans l'ordre, le comparateur marqué, et finit par la légende ;
    aucune ligne vide, aucune espace en fin de ligne ; le rapport central est écrit
    aussi."""
    lines = lines_of(command.report(REPORT))
    summary = _parts(command)[3]
    assert lines[: len(summary)] == summary
    assert command.report(CENTRAL_REPORT)
    rubrics = [
        i
        for i, line in enumerate(lines)
        if line.startswith("sensibilité  configuration")
    ]
    assert [lines[i] for i in rubrics] == [
        f"sensibilité  configuration {rank + 1}/19  {title}"
        + (" — comparateur" if rank == COMPARATOR else "")
        for rank, title in enumerate(TITLES)
    ]
    assert rubrics[0] == len(summary)
    legend = [i for i, line in enumerate(lines) if line.startswith("légende")]
    assert legend == [len(lines) - 4]
    assert lines[-4] == LEGEND
    assert all(line.startswith(INDENT) for line in lines[-3:])
    assert all(line.strip() for line in lines)
    assert all(line == line.rstrip() for line in lines)


def _section(lines: list[str], rank: int) -> list[str]:
    """Les lignes de la rubrique de la configuration de rang ``rank``."""
    starts = [
        i
        for i, line in enumerate(lines)
        if line.startswith("sensibilité  configuration")
    ]
    end = starts[rank + 1] if rank + 1 < len(starts) else len(lines) - 4
    return lines[starts[rank] : end]


@pytest.mark.parametrize("rank", range(19))
def test_rubric_of_each_configuration(command: Outcome, rank: int) -> None:
    """Précision de D15 (M4d-3) : la rubrique d'une configuration — ses agrégats
    d'usage sous son horloge, les trois axes par modèle, ``L`` de v0 brut performance
    par performance, sous l'écoulé la table des fourchettes de sa paire, la dérive de
    v0 brut sous son horloge."""
    section = _section(lines_of(command.report(REPORT)), rank)
    label = CLOCK_LABELS[rank]
    heads = [line[:13].strip() for line in section if not line.startswith(" ")]
    elapsed = label == "écoulé"
    assert heads == (
        ["sensibilité", "agrégats", "agrégats", "dérive"]
        if elapsed
        else ["sensibilité", "agrégats", "dérive"]
    )
    assert section[1].startswith(f"agrégats     usage, {label} ;")
    (drift,) = [i for i, line in enumerate(section) if line.startswith("dérive")]
    assert section[drift].startswith(
        f"dérive       0010 D12, usage ; v0 brut sous {label} ;"
    )
    inner = [line.strip() for line in section]
    axes = [i for i, line in enumerate(inner) if line.startswith("axes ")]
    level = [i for i, line in enumerate(inner) if line.startswith("L de v0 brut")]
    bands = [i for i, line in enumerate(section) if line.startswith("agrégats     fou")]
    assert len(axes) == len(level) == 1
    assert 1 < axes[0] < level[0] < drift
    assert len(bands) == (1 if elapsed else 0)
    if bands:
        assert level[0] < bands[0] < drift
    for label_of_axis in ("comparées", "perdues", "gagnées"):
        assert any(line.startswith(label_of_axis) for line in inner)
    days, with_usage = _declared(command)
    performances = section[level[0] + 1 : level[0] + 1 + len(days)]
    assert [line[13:].split()[0] for line in performances] == days
    assert all(line.startswith(INDENT) for line in performances)
    drifts = section[drift + 2 : drift + 2 + len(with_usage)]
    assert section[drift + 1].split()[0] == "sortie"
    assert [line[13:].split()[0] for line in drifts] == with_usage
    assert len(section) == drift + 2 + len(with_usage)


def _declared(outcome: Outcome) -> tuple[list[str], list[str]]:
    """Les jours des performances déclarées de la centrale, et ses sorties scorées avec
    usage, dans l'ordre."""
    log = read_registry(outcome.data / "registre")
    declared = log.events[0].declaration
    result = log.events[1].result
    assert declared is not None
    assert result is not None
    days = [p.performance.civil_date.isoformat() for p in declared.performances]
    with_usage = [o.outing_id for o in result.outings if o.models[0].usage is not None]
    return days, with_usage


def test_legend_of_the_report(command: Outcome) -> None:
    """Précision de D15 (M4d-3) : la légende — rapportée, jamais utilisée pour choisir ;
    les trois axes, et qu'un effectif égal ne dit pas qu'un support l'est ; ``D`` non
    normalisé par ``Δ`` ; les dix configurations de mouvement lues dans l'exécution
    ``(250, 30)`` ; les fourchettes par paire, sous l'écoulé ; la dérive, pente
    descriptive, jamais une fatigue."""
    legend = " ".join(line.strip() for line in lines_of(command.report(REPORT))[-4:])
    for phrase in (
        "rapportée, jamais utilisée pour choisir",
        "trois axes",
        "un effectif égal ne dit pas qu'un support l'est",
        "D n'est pas normalisé par Δ",
        "les dix configurations de mouvement sont l'exécution (250, 30) lue sous leur "
        "horloge",
        "fourchettes : en écoulé, par paire",
        "pente descriptive",
        "jamais une fatigue",
    ):
        assert phrase in legend


# ---------------------------------------------------------------------------
# Les noms de rapport refusés d'avance ; sans --sensitivity
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("name", ["backtest-0002.txt", "sensibilite-0004.txt"])
def test_existing_report_is_refused_on_a_new_registry(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, name: str
) -> None:
    """Précision de D15 (M4d-3) : les deux noms de rapport, central et de sensibilité,
    sont refusés d'avance s'ils existent — sur un registre neuf, aucun registre n'est
    créé, l'ancien rapport reste intact."""
    data = tmp_path / "donnees"
    (data / "rapports").mkdir(parents=True)
    old = data / "rapports" / name
    old.write_bytes(b"ancien rapport\n")
    outcome = backtest(
        monkeypatch, data, write_world(tmp_path / "monde"), "--sensitivity"
    )
    assert (outcome.code, outcome.out) == (1, "")
    assert outcome.err == EXISTS.format(name=name)
    assert not (data / "registre").exists()
    assert old.read_bytes() == b"ancien rapport\n"


@pytest.mark.parametrize(
    ("present", "named"),
    [
        (("sensibilite-0008.txt",), "sensibilite-0008.txt"),
        (("backtest-0006.txt", "sensibilite-0008.txt"), "backtest-0006.txt"),
    ],
    ids=["sensibilite", "les-deux"],
)
def test_existing_report_is_refused_after_a_registry(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    command: Outcome,
    present: tuple[str, ...],
    named: str,
) -> None:
    """Précision de D15 (M4d-3) : après un registre de quatre événements, les noms
    prévus sont ``backtest-0006.txt`` et ``sensibilite-0008.txt`` — l'un ou l'autre
    présent, la commande est refusée (le central d'abord), le registre reste à
    l'octet."""
    data = tmp_path / "donnees"
    shutil.copytree(command.data, data)
    for name in present:
        (data / "rapports" / name).write_bytes(b"ancien rapport\n")
    journal = (data / "registre" / EVENTS_FILE).read_bytes()
    documents = sorted((data / "registre" / "documents").iterdir())
    outcome = backtest(
        monkeypatch, data, write_world(tmp_path / "monde"), "--sensitivity"
    )
    assert (outcome.code, outcome.out) == (1, "")
    assert outcome.err == EXISTS.format(name=named)
    assert (data / "registre" / EVENTS_FILE).read_bytes() == journal
    assert sorted((data / "registre" / "documents").iterdir()) == documents


def test_without_sensitivity_nothing_changes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Précision de D15 (M4d-3) : sans ``--sensitivity``, la commande est celle de
    ``just backtest`` — sa synthèse au caractère près, aucune ligne « paire », aucune
    sensibilité au registre, aucun rapport de sensibilité."""
    data = tmp_path / "donnees"
    data.mkdir()
    outcome = backtest(monkeypatch, data, write_world(tmp_path / "monde"))
    assert (outcome.code, outcome.err) == (0, "")
    lines = lines_of(outcome.out)
    assert not [line for line in lines if line.startswith(("paire", "sensibilité"))]
    seal = outcome.seal()
    assert outcome.synthesis.replace(seal, "<sceau>") == SYNTHESIS
    log = read_registry(data / "registre")
    assert len(log.events) == 2
    assert count_trials(log).sensitivities == 0
    assert sorted(p.name for p in (data / "rapports").iterdir()) == [
        "backtest-0002.txt"
    ]
    assert not re.search("sensibilite", outcome.out)
    assert not contiguous(["paire"], lines)


class PanneError(RuntimeError):
    """Une exception synthétique."""


def test_error_in_the_sensitivity_report_is_a_technical_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Précision de D15 (M4d-3) : le rapport de sensibilité se calcule avant son
    RÉSULTAT — une erreur y est l'ÉCHEC technique de la sensibilité, dont l'empreinte
    est publiée ; ni synthèse ni rapport de sensibilité ; la centrale et son rapport
    restent (petit monde)."""

    def broken(evaluation: SensitivityEvaluation, central: BacktestRun) -> list[str]:
        raise PanneError("panne synthétique")

    monkeypatch.setattr(cli, "_sensitivity_body", broken)
    data = tmp_path / "donnees"
    data.mkdir()
    outcome = backtest(
        monkeypatch, data, write_mini_world(tmp_path / "monde"), "--sensitivity"
    )
    assert outcome.code == 1
    assert outcome.kinds() == (
        EventKind.DECLARATION,
        EventKind.RESULT,
        EventKind.DECLARATION,
        EventKind.FAILURE,
    )
    seals = _seals(outcome)
    assert outcome.err == (
        "Erreur : échec de la sensibilité, ÉCHEC enregistré (événement 4 ; dernière "
        f"ligne sha256 {seals[3]}) : PanneError : panne synthétique\n"
    )
    lines = lines_of(outcome.out)
    assert lines[-1] == (
        f"sensibilité  déclaration 3 enregistrée ; dernière ligne sha256 {seals[2]}"
    )
    assert len([line for line in lines if line.startswith("paire")]) == 8
    assert sorted(p.name for p in (data / "rapports").iterdir()) == [
        "backtest-0002.txt"
    ]
