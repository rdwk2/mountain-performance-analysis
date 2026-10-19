"""Le registre au format 3 (brief M4c-3, § 8.1 ; ``0010`` D14 et sa précision de
M4c-3, D10, décisions Q4 et E6) : le document d'admission, les documents D8 figés par
une expérience, le candidat.

- les versions, et le premier format de chaque document : ``Admission`` au format 3,
  ni écrite ni relue avant ;
- un registre du format 2 — construit par le code du jour, puis récrit au format 2 par
  ``_to_format`` de ``test_backtest_registry_format2.py`` — relu, vérifié, et suivi
  d'un ajout du format 3 ; une ligne du format 2 qui porte ``admission`` (même
  ``null``) ou ``reference_documents`` refusée, champ inconnu à son format ;
- une expérience du format 3 fige les documents D8 de ses références (E6), à l'ajout
  comme à la relecture ; l'invariant d'``ExperimentDeclaration`` ;
- l'accord d'un RÉSULTAT : un document d'admission cité si et seulement si sa
  déclaration porte une expérience, de la cible et de l'horloge de l'expérience ; les
  documents D8 publiés, ceux que la déclaration a figés ; un RÉSULTAT d'expérience
  cohérent relu au bit, son document d'admission compris ;
- le candidat : refusé sur une ligne antérieure au format 3, accepté calé au format 3.

La forme des contrats des lignes antérieures — 44 contrats, ``4e2f2b55…``, sans
``Result.admission`` ni ``ExperimentDeclaration.reference_documents`` — est tenue par
``test_shape_of_format_1_is_unchanged`` de ``test_backtest_registry_format2.py`` ; elle
n'est pas répétée ici.

Les admissions sont de vraies ``Admission``, produites par ``admit`` sur les entrées
construites de ``fixtures.admission`` ; aucune donnée réelle. Les journaux récrits à la
main le sont en JSON canonique, la chaîne des empreintes recalculée.
"""

import json
import re
from collections.abc import Callable
from dataclasses import replace
from functools import cache
from pathlib import Path
from typing import Any

import pytest

from fixtures.admission import EVALUATED, day, history, inputs
from fixtures.admission import experiment as admission_experiment
from fixtures.registry import (
    CALIBRATED_MODELS,
    at,
    declaration,
    references,
    registry_root,
)
from fixtures.registry import experiment as declared_experiment
from mountain_perf.backtest import (
    DOCUMENT_FIRST_FORMAT,
    DOCUMENT_SUFFIX,
    DOCUMENT_TYPES,
    DOCUMENTS_DIR,
    EVENTS_FILE,
    CodecError,
    RegistryError,
    admit,
    append_declaration,
    append_result,
    canonical_bytes,
    content_hash,
    count_trials,
    decode_document,
    encode_document,
    load_outcomes,
    load_references,
    read_registry,
    verify_registry,
)
from mountain_perf.schemas import (
    ADMISSION_FIRST_FORMAT,
    CLOCKS,
    REGISTRY_FORMAT_VERSION,
    REGISTRY_READABLE_FORMATS,
    Admission,
    CalibratedOutingScores,
    CalibratedScenarioScores,
    Clock,
    ContractError,
    Declaration,
    ExperimentDeclaration,
    ExperimentMetric,
    ModelKind,
    ModelResult,
    OutingBands,
    OutingObservation,
    OutingOutcome,
    RegistryEvent,
    RepeatabilityRecord,
    RepeatabilityReference,
    ScenarioScores,
    SensitivityOutcome,
)
from test_backtest_registry_format2 import (
    _documents,
    _outcomes,
    _registry,
    _rewrite,
    _scored_models,
    _to_format,
)

V0_RAW, V0_RECALIBRATED, CANDIDATE = CALIBRATED_MODELS
D8_SHA = content_hash(encode_document(references()[0][1]))
"""L'empreinte du document D8 de ``r1`` que publie ``append_result`` avec
``references()`` : celle que l'expérience fige (E6)."""


# ---------------------------------------------------------------------------
# Aides : admission, expérience, journal récrit à la main
# ---------------------------------------------------------------------------


@cache
def _admission(
    target: ExperimentMetric = ExperimentMetric.DESCENT_LEVEL,
    clock: Clock = CLOCKS[0],
) -> Admission:
    """Une vraie admission (``admit``) de cible ``target`` sous ``clock`` : l'historique
    et un jour évalué de ``fixtures.admission``, sans référence figée."""
    days = [history(), day("j", EVALUATED["j"], [100.0] * 9, [100.0] * 9, [95.0] * 9)]
    admitted = admit(admission_experiment(target, clock), inputs(days), ())
    assert isinstance(admitted, Admission)
    return admitted


def _experiment(**changes: object) -> ExperimentDeclaration:
    """L'expérience de ``fixtures.registry``, de la cible et de l'horloge de
    ``_admission()``, qui fige le document D8 de ``r1`` publié par ``references()``."""
    admission = _admission()
    fields: dict[str, object] = {
        "target": admission.target,
        "clock": admission.clock,
        "reference_documents": (RepeatabilityRecord("r1", D8_SHA),),
    }
    fields.update(changes)
    return declared_experiment(**fields)


def _experiment_declaration(**changes: object) -> Declaration:
    """La déclaration de v0 brut, de v0 recalé et du candidat, et de ``_experiment``."""
    return declaration(models=CALIBRATED_MODELS, experiment=_experiment(**changes))


def _experiment_outcomes() -> tuple[OutingOutcome, ...]:
    """Les trois sorties, scorées par v0 brut, v0 recalé et le candidat, les deux
    derniers ``non calés``."""
    return _outcomes(ModelKind.V0_RECALIBRATED, ModelKind.CANDIDATE)


def _experiment_registry(tmp_path: Path) -> Path:
    """Une DÉCLARATION d'expérience et son RÉSULTAT cohérent, écrits par le code du
    jour : le document d'admission de ``_admission()``, le document D8 figé."""
    root = registry_root(tmp_path)
    append_declaration(root, _experiment_declaration(), recorded_at=at(0))
    append_result(
        root,
        1,
        _experiment_outcomes(),
        references=references(),
        admission=_admission(),
        recorded_at=at(1),
    )
    return root


def _second(tmp_path: Path) -> Path:
    """Un second dossier de test, créé, pour un second registre (le registre ne crée
    jamais son dossier parent)."""
    second = tmp_path / "second"
    second.mkdir()
    return second


def _store(root: Path, value: object) -> str:
    """``value`` écrit à la main en document du format du jour ; son empreinte."""
    data = encode_document(value)
    sha = content_hash(data)
    (root / DOCUMENTS_DIR / f"{sha}{DOCUMENT_SUFFIX}").write_bytes(data)
    return sha


def _citing(admission: str | None) -> Callable[[RegistryEvent], RegistryEvent]:
    """Pour ``_rewrite`` : chaque RÉSULTAT cite le document d'admission
    ``admission``."""

    def change(event: RegistryEvent) -> RegistryEvent:
        if event.result is None:
            return event
        return replace(event, result=replace(event.result, admission=admission))

    return change


def _freezing(sha: str) -> Callable[[RegistryEvent], RegistryEvent]:
    """Pour ``_rewrite`` : l'expérience de chaque DÉCLARATION fige le document D8
    ``sha`` pour ``r1``."""

    def change(event: RegistryEvent) -> RegistryEvent:
        declared = event.declaration
        if declared is None or declared.experiment is None:
            return event
        experiment = replace(
            declared.experiment,
            reference_documents=(RepeatabilityRecord("r1", sha),),
        )
        return replace(event, declaration=replace(declared, experiment=experiment))

    return change


def _lines(root: Path) -> list[dict[str, Any]]:
    """Les lignes du journal, relues en JSON."""
    data = (root / EVENTS_FILE).read_bytes()
    return [json.loads(line) for line in data.split(b"\n")[:-1]]


def _journal(root: Path, change: Callable[[dict[str, Any]], None]) -> None:
    """Le journal récrit à la main : chaque ligne relue en JSON, changée en place par
    ``change``, réécrite en JSON canonique (``canonical_bytes``), la chaîne des
    empreintes recalculée ; les documents ne bougent pas."""
    previous: str | None = None
    lines = []
    for data in _lines(root):
        change(data)
        data["previous_hash"] = previous
        line = canonical_bytes(data)
        previous = content_hash(line)
        lines.append(line + b"\n")
    (root / EVENTS_FILE).write_bytes(b"".join(lines))


# ---------------------------------------------------------------------------
# Versions ; le document d'admission (§ 8.1, codec)
# ---------------------------------------------------------------------------


def test_versions() -> None:
    """Le format écrit, les formats relus, le premier format de l'admission ; le
    document d'admission, premier format 3, antépénultième type de document (puis
    les fourchettes du format 4, M4d-2, et la sensibilité du format 5, M4d-3)."""
    assert REGISTRY_FORMAT_VERSION == 5
    assert REGISTRY_READABLE_FORMATS == (1, 2, 3, 4, 5)
    assert ADMISSION_FIRST_FORMAT == 3
    assert dict(DOCUMENT_FIRST_FORMAT) == {
        OutingObservation: 1,
        ScenarioScores: 1,
        RepeatabilityReference: 1,
        CalibratedScenarioScores: 2,
        Admission: 3,
        OutingBands: 4,
        SensitivityOutcome: 5,
    }
    assert DOCUMENT_TYPES[-3] is Admission
    assert DOCUMENT_FIRST_FORMAT[Admission] == ADMISSION_FIRST_FORMAT


def test_admission_document_at_format_3() -> None:
    """Décision Q4 : le document d'admission s'écrit au format 3 et se relit égal à
    l'objet écrit."""
    admission = _admission()
    data = encode_document(admission, 3)
    assert data.startswith(b'{"type":"Admission","format":3,')
    assert decode_document(data, Admission, 3) == admission


@pytest.mark.parametrize("format_version", [1, 2])
def test_admission_document_does_not_exist_before_format_3(
    format_version: int,
) -> None:
    """Précision de D14 (M4c-2, M4c-3) : un document d'admission ne s'écrit pas avant
    le format 3 ; relu à un format antérieur, il est refusé — au format de son
    enveloppe d'abord (``"format":3``), puis, d'une enveloppe du format antérieur,
    parce que ce format ne le connaît pas."""
    admission = _admission()
    with pytest.raises(
        TypeError,
        match=re.escape(
            "Admission n'existe qu'à partir du format 3, demandé au format "
            f"{format_version}."
        ),
    ):
        encode_document(admission, format_version)
    data = encode_document(admission, 3)
    with pytest.raises(
        CodecError,
        match=re.escape(f"document au format 3, {format_version} attendu"),
    ):
        decode_document(data, Admission, format_version)
    forged = data.replace(b'"format":3,', f'"format":{format_version},'.encode(), 1)
    with pytest.raises(
        CodecError,
        match=re.escape(
            f"document de type 'Admission' au format {format_version}, qui ne le "
            "connaît pas"
        ),
    ):
        decode_document(forged, Admission, format_version)


# ---------------------------------------------------------------------------
# Le format 2 relu par le code du format 3
# ---------------------------------------------------------------------------


def _format_2_registry(tmp_path: Path) -> Path:
    """Une DÉCLARATION de v0 brut et de v0 recalé et son RÉSULTAT, écrits par le code
    du jour puis récrits au format 2."""
    root = _registry(
        tmp_path,
        models=(V0_RAW, V0_RECALIBRATED),
        outcomes_=_outcomes(ModelKind.V0_RECALIBRATED),
    )
    _to_format(root, 2)
    return root


def test_format_2_registry_is_read(tmp_path: Path) -> None:
    """Précision de D14 (M4c-3) : un registre du format 2 se relit et se vérifie par le
    code du format 3 ; ses lignes ne portent ni ``admission`` ni
    ``reference_documents`` (``_line`` les retire), son RÉSULTAT se relit sans
    admission, ses documents au format 2, chacun égal à l'objet écrit."""
    root = _format_2_registry(tmp_path)
    for path in _documents(root):
        assert re.match(rb'\{"type":"[A-Za-z]+","format":2,', path.read_bytes())
    declared, answered = _lines(root)
    assert "admission" not in answered["result"]
    assert declared["declaration"]["experiment"] is None
    log = verify_registry(root)
    assert [event.format_version for event in log.events] == [2, 2]
    result = log.events[1].result
    assert result is not None
    assert result.admission is None
    assert load_outcomes(root, log, 2) == _outcomes(ModelKind.V0_RECALIBRATED)
    assert load_references(root, log, 2) == references()


@pytest.mark.parametrize("experiment", [False, True], ids=["sans", "avec"])
def test_append_follows_format_2(tmp_path: Path, experiment: bool) -> None:
    """Précision de D14 (M4c-3) : un ajout du format courant (3 ; 4 depuis M4d-2) —
    sans expérience, ou une expérience et son RÉSULTAT qui cite son admission —
    s'enchaîne à un registre du format 2 ; le journal entier se vérifie, chaque ligne
    à son format : la ligne du format courant porte ``admission``, celle du format 2
    non."""
    root = _format_2_registry(tmp_path)
    if experiment:
        declared = _experiment_declaration()
        written = _experiment_outcomes()
        admission: Admission | None = _admission()
    else:
        declared = declaration(models=(V0_RAW, V0_RECALIBRATED))
        written = _outcomes(ModelKind.V0_RECALIBRATED)
        admission = None
    append_declaration(root, declared, recorded_at=at(2))
    append_result(
        root,
        3,
        written,
        references=references(),
        admission=admission,
        recorded_at=at(3),
    )
    log = verify_registry(root)
    assert [event.format_version for event in log.events] == [2, 2, 5, 5]
    assert count_trials(log).declarations == 2
    assert load_outcomes(root, log, 2) == _outcomes(ModelKind.V0_RECALIBRATED)
    assert load_outcomes(root, log, 4) == written
    lines = _lines(root)
    assert "admission" not in lines[1]["result"]
    cited = None if admission is None else content_hash(encode_document(admission))
    assert lines[3]["result"]["admission"] == cited


@pytest.mark.parametrize("cited", [None, "a" * 64], ids=["null", "empreinte"])
def test_format_2_result_carrying_admission_is_refused(
    tmp_path: Path, cited: str | None
) -> None:
    """Précision de D14 (M4c-3) : un RÉSULTAT du format 2 ne connaît pas
    ``admission`` ; une ligne du format 2 qui porte le champ, même ``null``, est
    refusée à la relecture, avant tout décodage."""
    root = _format_2_registry(tmp_path)

    def with_admission(data: dict[str, Any]) -> None:
        if data["result"] is not None:
            data["result"]["admission"] = cited

    _journal(root, with_admission)
    with pytest.raises(
        RegistryError,
        match=re.escape(
            "evenements.jsonl, ligne 2 : result : champ inconnu au format 2 : "
            "'admission'"
        ),
    ):
        read_registry(root)


def test_format_2_experiment_carrying_reference_documents(tmp_path: Path) -> None:
    """Précision de D14 (M4c-3) : une expérience du format 2 ne connaît pas
    ``reference_documents`` ; une ligne du format 2 dont l'expérience porte le champ est
    refusée à la relecture. Sans le champ, la même ligne se relit, ses documents D8
    absents (une ligne antérieure au format 3 n'en fige pas)."""
    root = registry_root(tmp_path)
    written = _experiment_declaration()
    append_declaration(root, written, recorded_at=at(0))

    def at_format_2(data: dict[str, Any]) -> None:
        data["format_version"] = 2
        data["declaration"].pop("sensitivity")

    _journal(root, at_format_2)
    with pytest.raises(
        RegistryError,
        match=re.escape(
            "evenements.jsonl, ligne 1 : experiment : champ inconnu au format 2 : "
            "'reference_documents'"
        ),
    ):
        read_registry(root)

    def without_documents(data: dict[str, Any]) -> None:
        data["declaration"]["experiment"].pop("reference_documents")

    _journal(root, without_documents)
    log = verify_registry(root)
    assert log.events[0].format_version == 2
    assert written.experiment is not None
    expected = replace(
        written, experiment=replace(written.experiment, reference_documents=None)
    )
    assert log.events[0].declaration == expected


def test_event_before_format_3_does_not_freeze_d8_documents(tmp_path: Path) -> None:
    """Invariant 2 de ``RegistryEvent`` (M4c-3) : un événement d'un format antérieur au
    format 3 dont l'expérience fige des documents D8 est refusé par le contrat, comme
    un RÉSULTAT qui cite une admission ; sans eux, le même événement se construit."""
    root = registry_root(tmp_path)
    append_declaration(root, _experiment_declaration(), recorded_at=at(0))
    event = read_registry(root).events[0]
    with pytest.raises(
        ContractError,
        match=re.escape(
            "une expérience du format 2 ne fige pas de documents D8 (format 3)."
        ),
    ):
        replace(event, format_version=2)
    declared = event.declaration
    assert declared is not None
    assert declared.experiment is not None
    bare = replace(declared.experiment, reference_documents=None)
    replace(event, format_version=2, declaration=replace(declared, experiment=bare))


def test_result_before_format_3_cites_no_admission(tmp_path: Path) -> None:
    """Invariant 2 de ``RegistryEvent`` (M4c-3) : un RÉSULTAT d'un format antérieur au
    format 3 qui cite un document d'admission est refusé par le contrat ; sans lui, le
    même événement se construit. ``Result.admission`` est une empreinte ``sha256``."""
    root = _experiment_registry(tmp_path)
    event = read_registry(root).events[1]
    result = event.result
    assert result is not None
    with pytest.raises(
        ContractError,
        match=re.escape(
            "un RÉSULTAT du format 2 ne cite pas de document d'admission (format 3)."
        ),
    ):
        replace(event, format_version=2)
    replace(event, format_version=2, result=replace(result, admission=None))
    with pytest.raises(
        ContractError,
        match=re.escape(
            "admission doit être un sha256 hexadécimal minuscule (64 caractères), "
            "reçu 'pas une empreinte'."
        ),
    ):
        replace(result, admission="pas une empreinte")


def test_experiment_declared_before_format_3_gets_no_result(tmp_path: Path) -> None:
    """Décision E6, précision de D14 (M4c-3) : une expérience déclarée au format 2 ne
    fige pas ses documents D8 ; un RÉSULTAT du format 3 qui lui répond, son admission
    citée, est refusé — à l'ajout comme à la relecture — plutôt que de laisser l'accord
    E6 sans objet."""
    root = registry_root(tmp_path)
    append_declaration(root, _experiment_declaration(), recorded_at=at(0))

    def at_format_2(data: dict[str, Any]) -> None:
        data["format_version"] = 2
        data["declaration"]["experiment"].pop("reference_documents")
        data["declaration"].pop("sensitivity")

    _journal(root, at_format_2)
    message = (
        "une expérience déclarée avant le format 3 ne reçoit pas de RÉSULTAT (ses "
        "documents D8 ne sont pas figés, E6)"
    )
    with pytest.raises(RegistryError, match=re.escape(message)):
        append_result(
            root,
            1,
            _experiment_outcomes(),
            references=references(),
            admission=_admission(),
            recorded_at=at(1),
        )
    assert len(read_registry(root).events) == 1

    second = _experiment_registry(_second(tmp_path))
    _journal(second, lambda data: at_format_2(data) if data["number"] == 1 else None)
    with pytest.raises(
        RegistryError, match=re.escape(f"evenements.jsonl, ligne 2 : {message}")
    ):
        read_registry(second)


# ---------------------------------------------------------------------------
# Une expérience au format 3 fige ses documents D8 (E6)
# ---------------------------------------------------------------------------


def test_append_declaration_requires_reference_documents(tmp_path: Path) -> None:
    """Décision E6 : ``append_declaration`` refuse une expérience qui ne fige pas les
    documents D8 de ses références, avant tout accès au registre."""
    root = registry_root(tmp_path)
    with pytest.raises(
        ValueError,
        match=re.escape(
            "append_declaration : une expérience fige les documents D8 de ses "
            "références (reference_documents, E6)."
        ),
    ):
        append_declaration(
            root, _experiment_declaration(reference_documents=None), recorded_at=at(0)
        )
    assert not root.exists()


@pytest.mark.parametrize(
    ("case", "message"),
    [
        (
            "null",
            "evenements.jsonl, ligne 1 : une expérience du format 5 fige les "
            "documents D8 de ses références (E6)",
        ),
        (
            "absent",
            "evenements.jsonl, ligne 1 : declaration.experiment : champs manquants de "
            "ExperimentDeclaration : reference_documents",
        ),
    ],
    ids=["null", "absent"],
)
def test_format_3_experiment_without_reference_documents(
    tmp_path: Path, case: str, message: str
) -> None:
    """Décision E6, précision de D14 (M4c-3) : une DÉCLARATION d'expérience du format 3
    récrite sans ses documents D8 — ``null``, ou le champ retiré — est refusée à la
    relecture."""
    root = registry_root(tmp_path)
    append_declaration(root, _experiment_declaration(), recorded_at=at(0))

    def without_documents(data: dict[str, Any]) -> None:
        experiment = data["declaration"]["experiment"]
        if case == "null":
            experiment["reference_documents"] = None
        else:
            del experiment["reference_documents"]

    _journal(root, without_documents)
    with pytest.raises(RegistryError, match=re.escape(message)):
        read_registry(root)


def test_format_3_experiment_with_reference_documents_is_read(tmp_path: Path) -> None:
    """Décision E6 : une DÉCLARATION d'expérience du format 3 qui fige ses documents D8
    s'écrit avec eux et se relit égale à l'objet écrit."""
    root = registry_root(tmp_path)
    written = _experiment_declaration()
    append_declaration(root, written, recorded_at=at(0))
    (line,) = _lines(root)
    assert line["declaration"]["experiment"]["reference_documents"] == [
        {"route_id": "r1", "reference": D8_SHA}
    ]
    log = verify_registry(root)
    assert log.events[0].format_version == 5
    assert log.events[0].declaration == written


@pytest.mark.parametrize(
    ("documents", "message"),
    [
        (
            (RepeatabilityRecord("r1", D8_SHA), RepeatabilityRecord("r1", "e" * 64)),
            "les documents D8 figés portent sur des parcours distincts, reçu 'r1' "
            "deux fois.",
        ),
        (
            (RepeatabilityRecord("r1", D8_SHA), RepeatabilityRecord("r2", "e" * 64)),
            "les documents D8 figés sont ceux des parcours des références figées "
            "(E6), reçu ['r1', 'r2'] pour ['r1'].",
        ),
        (
            (),
            "les documents D8 figés sont ceux des parcours des références figées "
            "(E6), reçu [] pour ['r1'].",
        ),
        (
            [RepeatabilityRecord("r1", D8_SHA)],
            "reference_documents doit être une séquence immuable : passer un tuple, "
            "reçu list.",
        ),
    ],
    ids=["répété", "en trop", "manquant", "liste"],
)
def test_reference_documents_invariant(documents: object, message: str) -> None:
    """Invariant d'``ExperimentDeclaration`` (E6) : les documents D8 figés, un tuple,
    portent sur des parcours distincts, exactement ceux des références figées (le
    parcours des locales et les donneurs des empruntées)."""
    with pytest.raises(ContractError, match=re.escape(message)):
        _experiment(reference_documents=documents)


def test_reference_documents_follow_the_frozen_references() -> None:
    """Invariant d'``ExperimentDeclaration`` (E6) : sans référence figée, aucun
    document D8 ; absents (``None``), rien n'est exigé — l'ajout et la relecture du
    format 3 les exigent."""
    empty = _experiment(frozen_references=(), reference_documents=())
    assert empty.reference_documents == ()
    frozen = (RepeatabilityRecord("r1", D8_SHA),)
    assert _experiment().reference_documents == frozen
    assert _experiment(reference_documents=None).reference_documents is None


# ---------------------------------------------------------------------------
# L'accord d'un RÉSULTAT : l'admission et les documents D8 figés
# ---------------------------------------------------------------------------


def test_experiment_result_is_read_back_at_bit(tmp_path: Path) -> None:
    """Décision Q4, précision de D14 (M4c-3) : un RÉSULTAT d'expérience complet et
    cohérent — chaque modèle déclaré, le candidat calé, le document D8 figé, le
    document d'admission de la cible et de l'horloge de l'expérience — est accepté ;
    il se vérifie et se relit égal, au bit, aux objets écrits, le document d'admission
    compris."""
    root = _experiment_registry(tmp_path)
    log = verify_registry(root)
    assert [event.format_version for event in log.events] == [5, 5]
    result = log.events[1].result
    assert result is not None
    sha = content_hash(encode_document(_admission()))
    assert result.admission == sha
    assert _lines(root)[1]["result"]["admission"] == sha
    assert [(r.route_id, r.reference) for r in result.references] == [("r1", D8_SHA)]
    assert load_outcomes(root, log, 2) == _experiment_outcomes()
    assert load_references(root, log, 2) == references()
    data = (root / DOCUMENTS_DIR / f"{sha}{DOCUMENT_SUFFIX}").read_bytes()
    assert decode_document(data, Admission) == _admission()
    assert decode_document(data, Admission, 5) == _admission()


def test_admission_document_must_be_stored(tmp_path: Path) -> None:
    """Précision de D14 (M4c-3) : le document d'admission est un document cité ; absent,
    la relecture le nomme."""
    root = _experiment_registry(tmp_path)
    sha = content_hash(encode_document(_admission()))
    (root / DOCUMENTS_DIR / f"{sha}{DOCUMENT_SUFFIX}").unlink()
    with pytest.raises(
        RegistryError,
        match=re.escape(f"documents/{sha}.json : document introuvable"),
    ):
        read_registry(root)


AGREEMENT = (
    "un RÉSULTAT cite un document d'admission si et seulement si sa déclaration "
    "porte une expérience (M4c-3)"
)


def test_experiment_result_without_admission_is_refused(tmp_path: Path) -> None:
    """Précision de D14 (M4c-3) : le RÉSULTAT d'une déclaration d'expérience cite un
    document d'admission ; sans lui, il est refusé à l'ajout, et, récrit sans lui, à
    la relecture."""
    root = registry_root(tmp_path)
    append_declaration(root, _experiment_declaration(), recorded_at=at(0))
    with pytest.raises(RegistryError, match=re.escape(f"ajout refusé : {AGREEMENT}")):
        append_result(root, 1, _experiment_outcomes(), references=references())
    assert len(read_registry(root).events) == 1
    root = _experiment_registry(_second(tmp_path))
    _rewrite(root, _citing(None))
    with pytest.raises(
        RegistryError, match=re.escape(f"evenements.jsonl, ligne 2 : {AGREEMENT}")
    ):
        read_registry(root)


def test_admission_without_experiment_is_refused(tmp_path: Path) -> None:
    """Précision de D14 (M4c-3) : le RÉSULTAT d'une déclaration sans expérience ne cite
    pas de document d'admission ; refusé à l'ajout, et, récrit pour en citer un
    présent et intact, à la relecture."""
    root = registry_root(tmp_path)
    append_declaration(root, declaration(models=CALIBRATED_MODELS), recorded_at=at(0))
    with pytest.raises(RegistryError, match=re.escape(f"ajout refusé : {AGREEMENT}")):
        append_result(
            root,
            1,
            _experiment_outcomes(),
            references=references(),
            admission=_admission(),
        )
    assert len(read_registry(root).events) == 1
    root = _registry(
        _second(tmp_path), models=CALIBRATED_MODELS, outcomes_=_experiment_outcomes()
    )
    _rewrite(root, _citing(_store(root, _admission())))
    with pytest.raises(
        RegistryError, match=re.escape(f"evenements.jsonl, ligne 2 : {AGREEMENT}")
    ):
        read_registry(root)


@pytest.mark.parametrize(
    "admission",
    [
        lambda: _admission(target=ExperimentMetric.ASCENT_LEVEL),
        lambda: _admission(clock=CLOCKS[1]),
    ],
    ids=["autre cible", "autre horloge"],
)
def test_admission_of_another_target_or_clock(
    tmp_path: Path, admission: Callable[[], Admission]
) -> None:
    """Précision de D14 (M4c-3) : la cible et l'horloge du document d'admission sont
    celles de l'expérience déclarée ; une autre est refusée à l'ajout et, sur une ligne
    récrite pour la citer, à la vérification — ``read_registry``, qui ne décode pas les
    documents, la relit."""
    other = admission()
    message = (
        "l'admission porte une autre cible ou une autre horloge que l'expérience "
        "déclarée"
    )
    root = registry_root(tmp_path)
    append_declaration(root, _experiment_declaration(), recorded_at=at(0))
    with pytest.raises(RegistryError, match=re.escape(f"ajout refusé : {message}")):
        append_result(
            root,
            1,
            _experiment_outcomes(),
            references=references(),
            admission=other,
        )
    root = _experiment_registry(_second(tmp_path))
    _rewrite(root, _citing(_store(root, other)))
    read_registry(root)
    with pytest.raises(
        RegistryError, match=re.escape(f"evenements.jsonl, ligne 2 : {message}")
    ):
        verify_registry(root)


FROZEN = "le document D8 de 'r1' n'est pas celui que la déclaration a figé (E6)"


@pytest.mark.parametrize(
    ("frozen", "published"),
    [
        ("d" * 64, references),
        (D8_SHA, lambda: ()),
    ],
    ids=["autre document", "aucun document"],
)
def test_published_d8_document_is_the_frozen_one(
    tmp_path: Path,
    frozen: str,
    published: Callable[[], tuple[tuple[str, RepeatabilityReference], ...]],
) -> None:
    """Décision E6 : les documents D8 d'un RÉSULTAT d'expérience sont ceux que sa
    déclaration a figés ; un autre, ou aucun, est refusé à l'ajout — aucun : avant le
    parcours de répétabilité sans référence D8."""
    root = registry_root(tmp_path)
    frozen_records = (RepeatabilityRecord("r1", frozen),)
    append_declaration(
        root,
        _experiment_declaration(reference_documents=frozen_records),
        recorded_at=at(0),
    )
    with pytest.raises(RegistryError, match=re.escape(f"ajout refusé : {FROZEN}")):
        append_result(
            root,
            1,
            _experiment_outcomes(),
            references=published(),
            admission=_admission(),
        )


def test_frozen_d8_document_is_checked_on_reading(tmp_path: Path) -> None:
    """Décision E6 : sur une DÉCLARATION récrite pour figer un autre document D8 que
    celui que publie son RÉSULTAT, la relecture refuse le RÉSULTAT."""
    root = _experiment_registry(tmp_path)
    _rewrite(root, _freezing("d" * 64))
    with pytest.raises(
        RegistryError, match=re.escape(f"evenements.jsonl, ligne 2 : {FROZEN}")
    ):
        read_registry(root)


# ---------------------------------------------------------------------------
# Le candidat (M4c-3)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("format_version", [1, 2])
def test_candidate_before_format_3_is_refused(
    tmp_path: Path, format_version: int
) -> None:
    """Précision de D14 (M4c-3) : un candidat n'existe qu'à partir du format 3 ; une
    ligne antérieure qui en porte un — v0 brut et le candidat calé ``non calé``,
    récrits à ce format — ne se vérifie pas, ses scores non relus, le modèle nommé.
    ``read_registry`` ne décode pas les documents, et la relit."""
    root = _registry(
        tmp_path,
        models=(V0_RAW, CANDIDATE),
        outcomes_=_outcomes(ModelKind.CANDIDATE),
    )
    _to_format(root, format_version)
    log = read_registry(root)
    message = (
        "evenements.jsonl, ligne 2 : 'q-2026-05-20', candidate : un candidat n'existe "
        "qu'à partir du format 3 (M4c-3)"
    )
    with pytest.raises(RegistryError, match=re.escape(message)):
        verify_registry(root)
    with pytest.raises(RegistryError, match=re.escape(message)):
        load_outcomes(root, log, 2)


def test_calibrated_candidate_at_format_3_is_accepted(tmp_path: Path) -> None:
    """Décision Q2 de M4c-3 : au format 3, le candidat est un modèle calé ; ses scores
    calés ``non calé`` sont acceptés et se relisent en ``CalibratedOutingScores``,
    égaux aux objets écrits."""
    written = _outcomes(ModelKind.CANDIDATE)
    root = _registry(tmp_path, models=(V0_RAW, CANDIDATE), outcomes_=written)
    log = verify_registry(root)
    read = load_outcomes(root, log, 2)
    assert read == written
    for item in read:
        scores = dict(item.scores)[ModelKind.CANDIDATE]
        assert isinstance(scores, CalibratedOutingScores)
        assert scores.control.model is ModelKind.CANDIDATE


def test_candidate_citing_scenario_scores_is_refused(tmp_path: Path) -> None:
    """Décision Q2 de M4c-3 : le ``ModelResult`` du candidat cite des
    ``CalibratedScenarioScores`` ; une ligne du format 3 qui lui fait citer les
    documents de v0 brut (des ``ScenarioScores``) ne se vérifie pas."""
    root = _registry(
        tmp_path,
        models=(V0_RAW, CANDIDATE),
        outcomes_=_outcomes(ModelKind.CANDIDATE),
    )

    def v0_documents(models: tuple[ModelResult, ...]) -> tuple[ModelResult, ...]:
        raw, candidate = models
        return raw, replace(raw, model=candidate.model)

    _scored_models(root, v0_documents)
    read_registry(root)
    with pytest.raises(
        RegistryError,
        match=re.escape(
            "document de type 'ScenarioScores', 'CalibratedScenarioScores' attendu"
        ),
    ):
        verify_registry(root)
