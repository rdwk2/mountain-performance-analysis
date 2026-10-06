"""L'exécution enregistrée de ``just backtest`` (§ 6.1 et § 8.1, tests 1 à 3, du brief
M4b-5 ; ``0010`` D14, D0, D2.1, D2.5, D2.6, D3, D8).

1. L'état git (décision Q7), dans un dépôt créé dans ``tmp_path``.
2. Le domaine et la déclaration, sur le monde synthétique du § 7.1 (``DOMAINS``,
   ``EXCLUSIONS``, ``PERFORMANCES``) ; les refus de la préparation ; rien n'est écrit.
3. L'exécution enregistrée sur le monde (``SCORED``, ``UNSCORED``, ``REFERENCES``) :
   le registre, le sceau, la DÉCLARATION avant le calcul, les ÉCHECs (décisions Q15
   et Q17), le recoupement des références D8 par l'accord du registre (Q11), et les
   variantes du monde des décisions Q14, Q16 et Q18.

Ce fichier porte aussi les aides des variantes du monde, réemployées par
``test_cli_backtest.py``.
"""

import dataclasses
import hashlib
import json
import math
import re
import shutil
import subprocess
from collections import Counter
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any

import pytest

import mountain_perf.backtest.execution as execution
from fixtures.backtest_values import (
    DOMAINS,
    EXCLUSIONS,
    PERFORMANCES,
    REFERENCES,
    SCORED,
    UNSCORED,
)
from fixtures.backtest_world import (
    ATHLETE,
    COMMIT,
    COURBE,
    EMPTY_GPX,
    RECORDED_AT,
    REFUSED,
    RETRIEVED_AT,
    run_world,
    untimed_gpx,
    write_world,
)
from mountain_perf.backtest import (
    EVENTS_FILE,
    MATCHING_PARAMETER_SPECS,
    PROTOCOL_RECORD,
    V0_RAW_MODEL,
    BacktestError,
    BacktestRun,
    ManifestError,
    RegistryError,
    git_state,
    line_hash,
    load_manifest,
    load_outcomes,
    load_references,
    outing_domains,
    prepare_backtest,
    read_registry,
    repeatability_reference,
    retain_outings,
    run_backtest,
    v0_scores,
    verify_registry,
)
from mountain_perf.gpx import GpxReadResult, read_gpx
from mountain_perf.model import ENGINE_VERSION, PROJECTION_PARAMETER_SPECS
from mountain_perf.schemas import (
    CLOCKS,
    EventKind,
    FailureKind,
    MetricValue,
    ModelKind,
    OutingScores,
    ParameterSet,
    RepeatabilityDay,
    RepeatabilityReference,
    RetentionDecision,
    SourceRef,
    Unavailability,
)

# ---------------------------------------------------------------------------
# Aides : le monde et ses variantes, le registre
# ---------------------------------------------------------------------------

Manifest = dict[str, object]


def _outings(manifest: Manifest) -> list[dict[str, object]]:
    outings = manifest["outings"]
    assert isinstance(outings, list)
    return outings


def _write_manifest(path: Path, manifest: Manifest) -> None:
    text = json.dumps(manifest, ensure_ascii=False, indent=2) + "\n"
    path.write_bytes(text.encode("utf-8"))


def world_variant(root: Path, change: Callable[[Manifest], None]) -> Path:
    """Le monde écrit dans ``root``, son manifeste modifié par ``change`` ; rend le
    chemin du manifeste."""
    path = write_world(root)
    manifest = json.loads(path.read_bytes())
    change(manifest)
    _write_manifest(path, manifest)
    return path


def outing(manifest: Manifest, outing_id: str) -> dict[str, object]:
    return next(o for o in _outings(manifest) if o["id"] == outing_id)


def untraced(manifest: Manifest, outing_id: str, start: str, end: str) -> None:
    """La sortie ``outing_id`` sans trace, ses instants déclarés."""
    entry = outing(manifest, outing_id)
    del entry["traces"]
    entry["start"], entry["end"] = start, end


def remove(manifest: Manifest, outing_id: str) -> None:
    _outings(manifest).remove(outing(manifest, outing_id))


def route_b_without_day(with_multi_outing_day: bool) -> Callable[[Manifest], None]:
    """Décisions Q16 et Q18 : ``b-2026-06-04`` et ``b-2026-06-08`` sans trace
    (instants déclarés, de 18 h à 18 h 45), avec ou sans ``b-2026-06-12`` : le
    parcours ``b`` n'a plus aucun jour."""

    def change(manifest: Manifest) -> None:
        untraced(
            manifest,
            "b-2026-06-04",
            "2026-06-04T18:00:00+02:00",
            "2026-06-04T18:45:00+02:00",
        )
        untraced(
            manifest,
            "b-2026-06-08",
            "2026-06-08T18:00:00+02:00",
            "2026-06-08T18:45:00+02:00",
        )
        if not with_multi_outing_day:
            remove(manifest, "b-2026-06-12")

    return change


def prepare(manifest: Path) -> execution.Preparation:
    return prepare_backtest(
        manifest, COURBE, commit=COMMIT, tree_modified=False, retrieved_at=RETRIEVED_AT
    )


def run(manifest: Path, registry: Path) -> BacktestRun:
    return run_backtest(prepare(manifest), registry, recorded_at=RECORDED_AT)


def last_line_hash(registry: Path) -> str:
    """Le ``sha256`` des octets de la dernière ligne du journal, sans fin de ligne."""
    data = (registry / EVENTS_FILE).read_bytes()
    assert data.endswith(b"\n")
    return hashlib.sha256(data.split(b"\n")[-2]).hexdigest()


def files(root: Path) -> dict[str, bytes]:
    """Les fichiers sous ``root`` et leurs octets : « rien n'est écrit »."""
    return {
        path.relative_to(root).as_posix(): path.read_bytes()
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


def close(a: float | None, b: float | None) -> bool:
    """Tolérance du § 7.0 : relative ``1e−9``, absolue ``1e−12``."""
    if a is None or b is None:
        return a is b
    return math.isclose(a, b, rel_tol=1e-9, abs_tol=1e-12)


@pytest.fixture(scope="module")
def world(tmp_path_factory: pytest.TempPathFactory) -> tuple[Path, BacktestRun]:
    """Le monde exécuté une fois : son dossier et l'exécution."""
    root = tmp_path_factory.mktemp("monde")
    return root, run_world(root)


# ---------------------------------------------------------------------------
# 1. État git (décision Q7)
# ---------------------------------------------------------------------------

needs_git = pytest.mark.skipif(shutil.which("git") is None, reason="git absent")


def _git(repository: Path, *arguments: str) -> str:
    completed = subprocess.run(
        ["git", "-C", str(repository), *arguments],
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=True,
    )
    return completed.stdout


@pytest.fixture
def repository(tmp_path: Path) -> Path:
    """Un dépôt : un fichier suivi, un commit fait sans dépendre de l'identité ni de
    la signature de la machine, un sous-dossier."""
    repository = tmp_path / "depot"
    (repository / "sous-dossier").mkdir(parents=True)
    _git(repository, "init", "-q")
    (repository / "suivi.txt").write_bytes(b"suivi\n")
    _git(repository, "add", "suivi.txt")
    _git(
        repository,
        "-c",
        "user.name=Synthetique",
        "-c",
        "user.email=synthetique@example.invalid",
        "-c",
        "commit.gpgsign=false",
        "commit",
        "-q",
        "-m",
        "commit synthétique",
    )
    return repository


@needs_git
def test_commit_is_read_from_a_subfolder(repository: Path) -> None:
    """Précision de D14 (M4b-5) : le commit du dépôt qui contient le dossier, égal à
    ``git rev-parse HEAD``, de 40 caractères ; l'arbre propre."""
    state = git_state(repository / "sous-dossier")
    assert state.commit == _git(repository, "rev-parse", "HEAD").strip()
    assert re.fullmatch(r"[0-9a-f]{40}", state.commit)
    assert state.modified is False


@needs_git
def test_untracked_file_does_not_modify_the_tree(repository: Path) -> None:
    """Décision Q7 : un fichier non suivi ne compte pas."""
    (repository / "non-suivi.txt").write_bytes(b"x\n")
    assert git_state(repository).modified is False


@needs_git
def test_tracked_file_modified_then_staged_modifies_the_tree(
    repository: Path,
) -> None:
    """Décision Q7 : un fichier suivi modifié, indexé ou non, compte."""
    (repository / "suivi.txt").write_bytes(b"modifie\n")
    assert git_state(repository).modified is True
    _git(repository, "add", "suivi.txt")
    assert git_state(repository).modified is True


@needs_git
def test_outside_a_repository(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Précision de D14 (M4b-5) : hors d'un dépôt, ``BacktestError`` (le plafond de
    recherche empêche de remonter dans un dépôt parent de ``tmp_path``)."""
    outside = tmp_path / "hors"
    outside.mkdir()
    monkeypatch.setenv("GIT_CEILING_DIRECTORIES", str(tmp_path))
    with pytest.raises(BacktestError) as raised:
        git_state(outside)
    assert type(raised.value) is BacktestError
    assert str(raised.value) == (
        "le code exécuté n'est pas dans un dépôt git : just backtest enregistre son "
        "commit (0010 D14)."
    )


def test_without_git(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Décision Q7 : sans ``git`` (``PATH`` vide), ``BacktestError``."""
    monkeypatch.setenv("PATH", "")
    with pytest.raises(BacktestError) as raised:
        git_state(tmp_path)
    assert type(raised.value) is BacktestError
    assert str(raised.value) == (
        "git introuvable : just backtest enregistre le commit du code exécuté."
    )


# ---------------------------------------------------------------------------
# 2. Domaine et déclaration (D2.1, D0, D2.5, D2.6, D14)
# ---------------------------------------------------------------------------


def test_outing_domains_of_the_world(tmp_path: Path) -> None:
    """Précision de D2.1 (M4b-5) : le D+/km de chaque sortie — la trace refusée lue
    comme profil (``c-2026-06-16``), deux tronçons sommés (``libre-2026-06-15``), une
    sortie sans fichier (``velo-2026-05-30``), un fichier illisible
    (``x-2026-06-18``)."""
    domains = outing_domains(load_manifest(write_world(tmp_path)))
    assert [d.outing_id for d in domains] == [e[0] for e in DOMAINS]
    for domain, (_, dplus, source, reason) in zip(domains, DOMAINS, strict=True):
        assert close(domain.dplus_per_km, dplus), domain
        assert (domain.source, domain.reason) == (source, reason)


def test_declaration_of_the_world(tmp_path: Path) -> None:
    """D14 et sa précision de M4b-5 : la déclaration exacte — commit, arbre, ``0010``,
    athlète, appariement par défaut, onze horloges, courbe, compagnon et instant de
    sa lecture, manifeste, performances et origines (D2.5), exclusions et leurs
    motifs dans l'ordre (D0, D2.1, D2.6), v0 brut seul, sans expérience ; rien n'est
    écrit."""
    manifest = write_world(tmp_path)
    before = files(tmp_path)
    declaration = prepare(manifest).declaration
    assert files(tmp_path) == before
    assert (declaration.commit, declaration.tree_modified) == (COMMIT, False)
    assert declaration.protocol_record == PROTOCOL_RECORD == "0010"
    assert declaration.athlete_ref == ATHLETE
    assert declaration.matching == ParameterSet(MATCHING_PARAMETER_SPECS)
    assert declaration.clocks == CLOCKS
    csv_hash = hashlib.sha256(COURBE.read_bytes()).hexdigest()
    meta_path = COURBE.with_name("courbe_synthetique.meta.json")
    assert declaration.curve_ref == f"courbe_synthetique.csv#{csv_hash[:12]}"
    curve, meta = declaration.curve, declaration.curve_metadata
    assert (curve.source.identifier, curve.source.content_hash) == (
        "courbe_synthetique.csv",
        csv_hash,
    )
    assert (meta.source.identifier, meta.source.content_hash) == (
        "courbe_synthetique.meta.json",
        hashlib.sha256(meta_path.read_bytes()).hexdigest(),
    )
    assert meta.source.retrieved_at == RETRIEVED_AT
    assert curve.available_at == meta.available_at
    assert curve.available_at.isoformat() == "2026-02-01T11:00:00+00:00"
    assert (declaration.manifest.identifier, declaration.manifest.content_hash) == (
        "manifeste.json",
        hashlib.sha256(manifest.read_bytes()).hexdigest(),
    )
    assert declaration.manifest.content_hash.startswith("aedb8754")
    assert (
        tuple(
            (
                p.performance.civil_date.isoformat(),
                tuple(o.outing_id for o in p.performance.outings),
                p.origin.isoformat(),
            )
            for p in declaration.performances
        )
        == PERFORMANCES
    )
    assert tuple((e.outing_id, e.reason) for e in declaration.exclusions) == EXCLUSIONS
    assert declaration.models == (V0_RAW_MODEL,)
    assert V0_RAW_MODEL.kind is ModelKind.V0_RAW
    assert V0_RAW_MODEL.engine_version == ENGINE_VERSION
    assert V0_RAW_MODEL.parameters == ParameterSet(PROJECTION_PARAMETER_SPECS)
    assert V0_RAW_MODEL.estimation_rule is None
    assert declaration.experiment is None


@pytest.mark.parametrize(
    ("change", "message"),
    [
        (
            lambda m: outing(m, "a-2026-06-03").pop("route"),
            "sortie 'a-2026-06-03' : jeu de répétabilité sans parcours (0010 D8).",
        ),
        (
            lambda m: outing(m, "b-2026-06-04").pop("reference"),
            "sortie 'b-2026-06-04' : jeu de répétabilité sans référence (0010 D8.1).",
        ),
        (
            lambda m: outing(m, "a-2026-06-10").update(
                reference=outing(m, "b-2026-06-04")["reference"]
            ),
            "parcours 'a' : ses jours de répétabilité n'ont pas tous la même référence "
            "(0010 D8.1).",
        ),
    ],
    ids=["without-route", "without-reference", "two-references"],
)
def test_refusals_of_the_repeatability_set(
    tmp_path: Path, change: Callable[[Manifest], object], message: str
) -> None:
    """D8, D8.1 : une sortie de répétabilité sans parcours, sans référence, ou un
    parcours à deux références, refusés avant tout écrit."""

    def apply(manifest: Manifest) -> None:
        change(manifest)

    manifest = world_variant(tmp_path, apply)
    before = files(tmp_path)
    with pytest.raises(BacktestError) as raised:
        prepare(manifest)
    assert type(raised.value) is BacktestError
    assert str(raised.value) == message
    assert files(tmp_path) == before


def test_manifest_error_is_raised_as_is(tmp_path: Path) -> None:
    """La ``ManifestError`` de ``load_manifest`` remonte telle quelle."""
    manifest = world_variant(tmp_path, lambda m: m.update(schema_version=2))
    with pytest.raises(ManifestError) as expected:
        load_manifest(manifest)
    with pytest.raises(ManifestError) as raised:
        prepare(manifest)
    assert type(raised.value) is ManifestError
    assert str(raised.value) == str(expected.value)


# ---------------------------------------------------------------------------
# 3. Exécution enregistrée (D14, D0, D3, D8)
# ---------------------------------------------------------------------------


def test_registry_of_the_world(world: tuple[Path, BacktestRun]) -> None:
    """D14 : une DÉCLARATION (n° 1) et un RÉSULTAT (n° 2) qui lui répond, tous deux à
    ``RECORDED_AT`` ; relus par ``verify_registry`` comme par ``read_registry`` ; les
    événements de ``BacktestRun`` sont ceux du journal."""
    root, backtest = world
    registry = root / "registre"
    log = verify_registry(registry)
    assert log == read_registry(registry)
    declaration, result = log.events
    assert (declaration.number, declaration.kind) == (1, EventKind.DECLARATION)
    assert (result.number, result.kind, result.answers) == (2, EventKind.RESULT, 1)
    assert declaration.recorded_at == result.recorded_at == RECORDED_AT
    assert (backtest.declaration_event, backtest.result_event) == (declaration, result)


def test_scored_and_unscored_outings(world: tuple[Path, BacktestRun]) -> None:
    """D0, D3 : douze sorties scorées ; ``c-2026-06-16`` non scorée au motif de son
    refus, ``a-2026-06-20`` « sortie non tracée » ; ``load_outcomes`` et
    ``load_references`` relisent les sorties et les références de l'exécution."""
    root, backtest = world
    assert tuple(run.outing.outing_id for run in backtest.outings) == SCORED
    assert tuple((e.outing_id, e.reason) for e in backtest.unscored) == UNSCORED
    registry = root / "registre"
    log = read_registry(registry)
    outcomes = load_outcomes(registry, log, 2)
    assert tuple(o.outing_id for o in outcomes) == SCORED
    for outcome, run in zip(outcomes, backtest.outings, strict=True):
        assert outcome.coverage == run.match.coverage
        assert outcome.scores == ((ModelKind.V0_RAW, run.scores),)
    assert load_references(registry, log, 2) == backtest.references
    result = backtest.result_event.result
    assert result is not None
    assert tuple((e.outing_id, e.reason) for e in result.unscored) == UNSCORED


def test_seal_is_the_hash_of_the_last_line(world: tuple[Path, BacktestRun]) -> None:
    """Précision de D14 (M4b-5) : le sceau est le ``sha256`` de la dernière ligne du
    journal, ``line_hash`` du RÉSULTAT."""
    root, backtest = world
    assert backtest.seal == last_line_hash(root / "registre")
    assert backtest.seal == line_hash(backtest.result_event)


def test_forecasts_are_dated_by_the_declaration(
    world: tuple[Path, BacktestRun],
) -> None:
    """D14 : les prévisions sont datées de la DÉCLARATION, qui fixe ce que l'exécution
    évalue."""
    _, backtest = world
    for run in backtest.outings:
        scenarios = [run.scores.control, run.scores.usage]
        for scenario in scenarios:
            if scenario is not None:
                assert scenario.forecast.generated_at == RECORDED_AT


def test_d8_references_of_the_world(world: tuple[Path, BacktestRun]) -> None:
    """D8 et sa précision de M4b-3 : une référence par parcours, ses jours, le jour
    multi-sorties écarté, « un seul contraste » et son fichier."""
    _, backtest = world
    assert [route for route, _ in backtest.references] == sorted(REFERENCES)
    for route, reference in backtest.references:
        assert (
            tuple(d.isoformat() for d in reference.days),
            tuple(d.isoformat() for d in reference.multi_outing_days),
            reference.single_contrast,
            reference.reference.identifier,
        ) == REFERENCES[route]


def test_declaration_is_written_before_any_computation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """D14 : la DÉCLARATION avant tout calcul — à chaque calcul de scores, la dernière
    ligne du registre est la DÉCLARATION."""
    registry = tmp_path / "registre"
    seen: list[tuple[int, EventKind]] = []
    real = v0_scores

    def spy(*args: Any, **kwargs: Any) -> OutingScores:
        events = read_registry(registry).events
        seen.append((len(events), events[-1].kind))
        return real(*args, **kwargs)

    monkeypatch.setattr(execution, "v0_scores", spy)
    run(write_world(tmp_path / "monde"), registry)
    assert seen == [(1, EventKind.DECLARATION)] * len(SCORED)


def _failure_lines(registry: Path) -> tuple[EventKind, ...]:
    return tuple(event.kind for event in read_registry(registry).events)


def test_no_performance_is_a_not_evaluable_failure(tmp_path: Path) -> None:
    """Précision de D14 (M4b-5), décision Q15 : sans performance dans le domaine (les
    sorties ``velo-*`` et ``plat-*`` seules), une DÉCLARATION puis un ÉCHEC « non
    évaluable » qui lui répond, et une ``BacktestError`` qui publie son empreinte."""
    kept = {"velo-2026-05-30", "velo-2026-06-06", "velo-2026-06-09", "plat-2026-06-11"}

    def only_velo_and_flat(manifest: Manifest) -> None:
        manifest["outings"] = [o for o in _outings(manifest) if o["id"] in kept]

    registry = tmp_path / "registre"
    manifest = world_variant(tmp_path / "monde", only_velo_and_flat)
    with pytest.raises(BacktestError) as raised:
        run(manifest, registry)
    assert type(raised.value) is BacktestError
    seal = last_line_hash(registry)
    assert str(raised.value) == (
        "aucune performance dans le domaine : ÉCHEC enregistré (événement 2 ; "
        f"dernière ligne sha256 {seal})."
    )
    declaration, failure = read_registry(registry).events
    assert declaration.kind is EventKind.DECLARATION
    assert (failure.kind, failure.answers) == (EventKind.FAILURE, 1)
    assert failure.failure is not None
    assert failure.failure.kind is FailureKind.NOT_EVALUABLE
    assert failure.failure.reason == "aucune performance dans le domaine"
    assert line_hash(failure) == seal


@pytest.mark.parametrize(
    ("error", "reason"),
    [
        (
            OSError(5, "erreur d'entrée-sortie", "/chemin/personnel.gpx"),
            "OSError (errno 5)",
        ),
        (ValueError("valeur inattendue"), "ValueError : valeur inattendue"),
        (ValueError(), "ValueError"),
        (KeyboardInterrupt(), "KeyboardInterrupt"),
    ],
    ids=["oserror-with-path", "valueerror", "empty-message", "keyboard-interrupt"],
)
def test_exception_of_the_computation_is_a_technical_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    error: BaseException,
    reason: str,
) -> None:
    """Précision de D14 (M4b-5), décisions Q15 et Q17 : une exception du calcul, ou
    une interruption au clavier, devient un ÉCHEC technique au motif sans chemin
    (``OSError`` : type et ``errno`` ; message vide : le type seul) ; la
    ``BacktestError`` publie l'empreinte de l'ÉCHEC et est chaînée à l'erreur."""

    def raising(*args: Any, **kwargs: Any) -> OutingScores:
        raise error

    monkeypatch.setattr(execution, "v0_scores", raising)
    registry = tmp_path / "registre"
    manifest = write_world(tmp_path / "monde")
    try:
        with pytest.raises(BacktestError) as raised:
            run(manifest, registry)
    except KeyboardInterrupt:
        pytest.fail("une interruption au clavier s'est échappée de run_backtest")
    assert type(raised.value) is BacktestError
    seal = last_line_hash(registry)
    assert str(raised.value) == (
        "échec de l'exécution, ÉCHEC enregistré (événement 2 ; dernière ligne sha256 "
        f"{seal}) : {reason}"
    )
    assert raised.value.__cause__ is error
    assert _failure_lines(registry) == (EventKind.DECLARATION, EventKind.FAILURE)
    failure = read_registry(registry).events[-1]
    assert failure.failure is not None
    assert (failure.failure.kind, failure.failure.reason) == (
        FailureKind.TECHNICAL,
        reason,
    )
    assert line_hash(failure) == seal
    journal = (registry / EVENTS_FILE).read_bytes()
    assert b"chemin" not in journal
    assert b"personnel" not in journal


def test_d8_reference_naming_another_file_is_refused_by_the_registry(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Précision de D14 (M4b-5), décision Q11 : l'exécution ne recoupe pas le fichier
    de la référence calculée — l'accord du registre refuse le RÉSULTAT, et le refus
    devient un ÉCHEC technique ; aucun RÉSULTAT."""
    real = repeatability_reference
    other = SourceRef("gpx", "autre.gpx", "1" * 64, RETRIEVED_AT)

    def renamed(
        reference: SourceRef, days: Sequence[RepeatabilityDay]
    ) -> RepeatabilityReference:
        computed = real(reference, days)
        if reference.identifier == "prepare.gpx":
            return dataclasses.replace(computed, reference=other)
        return computed

    monkeypatch.setattr(execution, "repeatability_reference", renamed)
    registry = tmp_path / "registre"
    with pytest.raises(BacktestError) as raised:
        run(write_world(tmp_path / "monde"), registry)
    assert type(raised.value) is BacktestError
    assert str(raised.value).endswith(
        "RegistryError : ajout refusé : la référence de 'a' ne nomme pas la référence "
        "déclarée de la sortie 'a-2026-06-03' (empreinte différente)"
    )
    assert _failure_lines(registry) == (EventKind.DECLARATION, EventKind.FAILURE)


def test_refused_declaration_is_raised_as_is(tmp_path: Path) -> None:
    """D14 : une DÉCLARATION refusée par le registre (dossier parent absent) remonte
    en ``RegistryError``, telle quelle ; rien n'est écrit."""
    manifest = write_world(tmp_path / "monde")
    preparation = prepare(manifest)
    before = files(tmp_path)
    with pytest.raises(RegistryError) as raised:
        run_backtest(preparation, tmp_path / "absent" / "registre")
    assert type(raised.value) is RegistryError
    assert str(raised.value) == (
        "registre impossible à créer : son dossier parent n'existe pas."
    )
    assert files(tmp_path) == before
    assert not (tmp_path / "absent").exists()


def test_unscored_repeatability_day_is_left_out_of_the_reference(
    tmp_path: Path,
) -> None:
    """Précision de D8.1 (M4b-5), décision Q16 : la trace de ``a-2026-06-10``
    remplacée par une trace sans horodatage, ses instants déclarés — la sortie est non
    scorée au motif de son refus, la référence de ``a`` porte les 3 et 6 juin et le
    jour multi-sorties du 12 ; le RÉSULTAT est accepté."""

    def declared_instants(manifest: Manifest) -> None:
        entry = outing(manifest, "a-2026-06-10")
        entry["start"] = "2026-06-10T08:00:00+02:00"
        entry["end"] = "2026-06-10T08:50:00+02:00"

    world_root = tmp_path / "monde"
    manifest = world_variant(world_root, declared_instants)
    (world_root / "gpx/a/a10.gpx").write_bytes(untimed_gpx(REFUSED).encode("utf-8"))
    registry = tmp_path / "registre"
    backtest = run(manifest, registry)
    assert (
        "a-2026-06-10",
        "trace refusée (a10.gpx) : a10.gpx, trkpt[0].time : instant manquant.",
    ) in [(e.outing_id, e.reason) for e in backtest.unscored]
    reference = dict(backtest.references)["a"]
    assert [d.isoformat() for d in reference.days] == ["2026-06-03", "2026-06-06"]
    assert [d.isoformat() for d in reference.multi_outing_days] == ["2026-06-12"]
    verify_registry(registry)


def test_route_without_any_day_keeps_an_empty_reference(tmp_path: Path) -> None:
    """Décisions Q16 et Q18 : ``b-2026-06-04`` et ``b-2026-06-08`` sans trace,
    ``b-2026-06-12`` retirée — deux références, ``a`` et ``b`` ; celle de ``b`` est
    vide : aucun jour, aucun jour multi-sorties, pas « un seul contraste », son
    fichier, et sous chaque horloge aucun pli et ses neuf ``F`` en support
    insuffisant d'effectif 0 ; le RÉSULTAT est accepté."""
    registry = tmp_path / "registre"
    manifest = world_variant(tmp_path / "monde", route_b_without_day(False))
    backtest = run(manifest, registry)
    assert [route for route, _ in backtest.references] == ["a", "b"]
    result = backtest.result_event.result
    assert result is not None
    assert [record.route_id for record in result.references] == ["a", "b"]
    reference = dict(backtest.references)["b"]
    assert (reference.days, reference.multi_outing_days) == ((), ())
    assert reference.single_contrast is False
    assert reference.reference.identifier == "b08.gpx"
    empty = MetricValue(None, Unavailability.INSUFFICIENT_SUPPORT, 0)
    for clock in reference.clocks:
        assert clock.folds == ()
        assert (clock.level, *clock.log_ratios, *clock.dispersions) == (empty,) * 9
    unscored = dict((e.outing_id, e.reason) for e in backtest.unscored)
    assert unscored["b-2026-06-04"] == unscored["b-2026-06-08"] == "sortie non tracée"
    verify_registry(registry)


def test_outing_of_another_set_on_the_route_is_not_held(tmp_path: Path) -> None:
    """Décision Q14 : ``a-bis-2026-06-12``, à pied sur ``a`` mais en développement,
    sans référence (la trace de ``libre-2026-06-12``, réemployée) — la performance du
    12 juin la compte, le RÉSULTAT s'écrit et ``verify_registry`` l'accepte."""

    def add_variant(manifest: Manifest) -> None:
        _outings(manifest).append(
            {
                "id": "a-bis-2026-06-12",
                "sport": "foot",
                "traces": [{"file": "gpx/libre/libre12.gpx"}],
                "route": "a",
                "dataset": "development",
                "label": "training",
            }
        )

    registry = tmp_path / "registre"
    backtest = run(world_variant(tmp_path / "monde", add_variant), registry)
    june_12 = next(
        p
        for p in backtest.preparation.performances
        if p.civil_date.isoformat() == "2026-06-12"
    )
    assert "a-bis-2026-06-12" in [o.outing_id for o in june_12.outings]
    assert backtest.result_event.kind is EventKind.RESULT
    verify_registry(registry)


# ---------------------------------------------------------------------------
# Correctifs de la relecture de la PR #20
# ---------------------------------------------------------------------------


def _without_route_or_reference(manifest: Manifest) -> None:
    entry = outing(manifest, "a-2026-06-03")
    entry.pop("route")
    entry.pop("reference")


def _two_references_then_without_route(manifest: Manifest) -> None:
    outing(manifest, "a-2026-06-10").update(
        reference=outing(manifest, "b-2026-06-04")["reference"]
    )
    outing(manifest, "b-2026-06-12").pop("route")


@pytest.mark.parametrize(
    ("change", "message"),
    [
        (
            _without_route_or_reference,
            "sortie 'a-2026-06-03' : jeu de répétabilité sans parcours (0010 D8).",
        ),
        (
            _two_references_then_without_route,
            "sortie 'b-2026-06-12' : jeu de répétabilité sans parcours (0010 D8).",
        ),
    ],
    ids=["route-before-reference", "outings-before-references"],
)
def test_order_of_the_refusals_of_the_repeatability_set(
    tmp_path: Path, change: Callable[[Manifest], None], message: str
) -> None:
    """§ 6.1, étape 3 : pour chaque sortie, dans l'ordre, sans parcours puis sans
    référence ; puis, parcours par parcours, plus d'une référence — une sortie sans
    parcours ni référence reçoit « sans parcours » ; un parcours à deux références et
    une sortie suivante sans parcours, « sans parcours »."""
    with pytest.raises(BacktestError) as raised:
        prepare(world_variant(tmp_path, change))
    assert str(raised.value) == message


def test_first_unreadable_domain_file_wins(tmp_path: Path) -> None:
    """§ 6.1, point 2 (précision de D2.1) : les fichiers du profil de domaine se lisent
    dans l'ordre, arrêt au premier qui ne se lit pas — ``libre-2026-06-15``, ses deux
    tronçons sans point (refusés, ses instants déclarés) : le motif nomme le
    premier."""

    def declared_instants(manifest: Manifest) -> None:
        entry = outing(manifest, "libre-2026-06-15")
        entry["start"] = "2026-06-15T08:00:00+02:00"
        entry["end"] = "2026-06-15T09:00:00+02:00"

    manifest = world_variant(tmp_path, declared_instants)
    folder = tmp_path / "gpx" / "libre"
    (folder / "libre15_1.gpx").write_bytes(EMPTY_GPX.encode("utf-8"))
    second = EMPTY_GPX.replace("Trace vide", "Second tronçon vide")
    assert second != EMPTY_GPX
    (folder / "libre15_2.gpx").write_bytes(second.encode("utf-8"))
    domain = next(
        d
        for d in outing_domains(load_manifest(manifest))
        if d.outing_id == "libre-2026-06-15"
    )
    assert domain.dplus_per_km is None
    assert domain.reason == (
        "profil de domaine illisible (libre15_1.gpx) : Aucun <trkpt> dans le fichier "
        "GPX."
    )


def test_contract_error_of_a_domain_file_is_an_unknown_dplus(tmp_path: Path) -> None:
    """§ 6.1, point 2 (précision de D2.1) : un fichier lisible dont une altitude n'est
    pas finie fait lever ``ContractError`` à sa lecture — le D+/km de
    ``x-2026-06-18`` est inconnu, avec son motif ; la préparation continue."""
    manifest = write_world(tmp_path)
    folder = tmp_path / "gpx" / "libre"
    text = (folder / "c16.gpx").read_bytes().decode("utf-8")
    elevations = re.findall(r"<ele>[^<]*</ele>", text)
    assert len(elevations) > 2
    position = text.index(elevations[1], text.index(elevations[0]) + 1)
    nan = text[:position] + "<ele>nan</ele>" + text[position + len(elevations[1]) :]
    (folder / "x18.gpx").write_bytes(nan.encode("utf-8"))
    domain = next(
        d
        for d in outing_domains(load_manifest(manifest))
        if d.outing_id == "x-2026-06-18"
    )
    assert domain.dplus_per_km is None
    assert domain.reason == (
        "profil de domaine illisible (x18.gpx) : elevation_m[1] doit être fini, reçu "
        "nan."
    )
    exclusions = prepare(manifest).declaration.exclusions
    reasons = {e.outing_id: e.reason for e in exclusions}
    assert reasons["x-2026-06-18"] == f"hors domaine : D+/km inconnu ({domain.reason})"


def test_tree_modified_is_declared(tmp_path: Path) -> None:
    """§ 6.1 : la DÉCLARATION porte l'arbre tel que l'appelant le donne
    (``tree_modified``)."""
    preparation = prepare_backtest(
        write_world(tmp_path),
        COURBE,
        commit=COMMIT,
        tree_modified=True,
        retrieved_at=RETRIEVED_AT,
    )
    assert preparation.declaration.tree_modified is True


def test_reference_file_is_read_once_per_execution(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """§ 6.1, étape 3 : le tracé d'une référence est lu une fois par fichier (cache par
    chemin) — pendant l'exécution du monde, ``prepare.gpx`` (parcours ``a``) et
    ``b08.gpx`` (parcours ``b``) une fois chacun."""
    preparation = prepare(write_world(tmp_path / "monde"))
    counts: Counter[str] = Counter()

    def counted(path: Path) -> GpxReadResult:
        counts[path.name] += 1
        return read_gpx(path)

    monkeypatch.setattr(execution, "read_gpx", counted)
    run_backtest(preparation, tmp_path / "registre", recorded_at=RECORDED_AT)
    assert counts == Counter({"prepare.gpx": 1, "b08.gpx": 1})


@pytest.mark.parametrize(
    "cls",
    [
        execution.GitState,
        execution.OutingDomain,
        execution.Preparation,
        execution.OutingRun,
        execution.BacktestRun,
    ],
    ids=lambda cls: str(cls.__name__),
)
def test_execution_objects_are_frozen(cls: Any) -> None:
    """§ 6.1 : chacun de ces objets est gelé — affecter un champ lève
    ``FrozenInstanceError``."""
    instance = object.__new__(cls)
    with pytest.raises(dataclasses.FrozenInstanceError):
        setattr(instance, dataclasses.fields(cls)[0].name, None)


def test_preparation_keeps_its_decisions_and_domains(tmp_path: Path) -> None:
    """§ 6.1 : la préparation garde les décisions de rétention (``decisions``) et le
    profil de domaine de chaque sortie (``domains``), ceux que ``retain_outings`` et
    ``outing_domains`` rendent sur son manifeste (les sorties comparées par leur
    identifiant : chaque lecture date ses fichiers)."""
    manifest = write_world(tmp_path)
    read = load_manifest(manifest)
    preparation = prepare(manifest)

    def decided(decisions: Sequence[RetentionDecision]) -> list[tuple[object, ...]]:
        return [
            (
                d.outing.outing_id,
                d.civil_date,
                d.rank,
                d.cumulative_elapsed_s,
                d.retained,
            )
            for d in decisions
        ]

    assert decided(preparation.decisions) == decided(retain_outings(read.outings))
    assert preparation.domains == outing_domains(read)


def _without_performance(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    kept = {"velo-2026-05-30", "velo-2026-06-06", "velo-2026-06-09", "plat-2026-06-11"}

    def only_velo_and_flat(manifest: Manifest) -> None:
        manifest["outings"] = [o for o in _outings(manifest) if o["id"] in kept]

    return world_variant(tmp_path / "monde", only_velo_and_flat)


def _computation_raises(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    def raising(*args: Any, **kwargs: Any) -> OutingScores:
        raise ValueError("valeur inattendue")

    monkeypatch.setattr(execution, "v0_scores", raising)
    return write_world(tmp_path / "monde")


@pytest.mark.parametrize(
    "failing",
    [_without_performance, _computation_raises],
    ids=["not-evaluable", "technical"],
)
def test_failure_is_recorded_at_the_given_instant(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    failing: Callable[[Path, pytest.MonkeyPatch], Path],
) -> None:
    """§ 6.1, étapes 2 et 4 : l'ÉCHEC, « non évaluable » ou technique, est enregistré à
    l'instant donné (``recorded_at``), comme la DÉCLARATION."""
    registry = tmp_path / "registre"
    manifest = failing(tmp_path, monkeypatch)
    with pytest.raises(BacktestError):
        run(manifest, registry)
    declaration, failure = read_registry(registry).events
    assert failure.kind is EventKind.FAILURE
    assert declaration.recorded_at == failure.recorded_at == RECORDED_AT


def test_route_of_a_single_repeatability_outing(tmp_path: Path) -> None:
    """D8, D8.1 : un parcours de répétabilité d'une seule sortie (``b-2026-06-08``
    seule sur ``b``) a sa référence déclarée, et sa référence D8 un jour."""

    def single_b(manifest: Manifest) -> None:
        remove(manifest, "b-2026-06-04")
        remove(manifest, "b-2026-06-12")

    backtest = run(world_variant(tmp_path / "monde", single_b), tmp_path / "registre")
    reference = dict(backtest.references)["b"]
    assert [day.isoformat() for day in reference.days] == ["2026-06-08"]
    assert reference.reference.identifier == "b08.gpx"


def test_motif_of_an_outing_of_the_first_day_of_the_domain(tmp_path: Path) -> None:
    """Précision de D2.1 : le domaine commence le jour de ``domain_start_date`` — une
    sortie de ce jour-là, hors du domaine, l'est par son D+/km, pas par sa date
    (``plat-2026-06-11``, le domaine ouvert le 2026-06-11)."""
    manifest = world_variant(
        tmp_path, lambda m: m.update(domain_start_date="2026-06-11")
    )
    exclusions = prepare(manifest).declaration.exclusions
    reasons = {e.outing_id: e.reason for e in exclusions}
    assert reasons["plat-2026-06-11"] == "hors domaine : D+/km 4.8, sous 40"


def test_unscored_outing_first_in_a_multi_outing_day(tmp_path: Path) -> None:
    """§ 6.1, étape 3, sortie par sortie : une sortie non scorée en tête d'un jour de
    trois sorties (``a-2026-06-12`` sans trace, ses instants déclarés) n'arrête pas les
    suivantes — ``b-2026-06-12`` et ``libre-2026-06-12`` sont scorées."""

    def untraced_a12(manifest: Manifest) -> None:
        untraced(
            manifest,
            "a-2026-06-12",
            "2026-06-12T07:00:00+02:00",
            "2026-06-12T07:45:00+02:00",
        )

    backtest = run(
        world_variant(tmp_path / "monde", untraced_a12), tmp_path / "registre"
    )
    scored = [o.outing.outing_id for o in backtest.outings]
    assert "b-2026-06-12" in scored
    assert "libre-2026-06-12" in scored
    unscored = [(e.outing_id, e.reason) for e in backtest.unscored]
    assert ("a-2026-06-12", "sortie non tracée") in unscored
