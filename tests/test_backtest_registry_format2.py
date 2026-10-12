"""Le registre au format 2 (§ 6.1 et § 8.1, test 1, du brief M4c-2 ; ``0010`` D14 et sa
précision de M4c-2, D0, D8, D9.2).

Les versions ; la forme des 44 contrats du format 1, inchangée (décision 1) ; un
document écrit et relu **au format de l'événement qui le cite** ; un registre du format
1 — construit par le code du jour puis récrit au format 1 par une aide du test — relu,
vérifié, et suivi d'un ajout du format 2 ; une ligne du format 1 qui porte un modèle
calé refusée par la vérification (décision 15) ; un RÉSULTAT du format 2 relu au bit ;
l'accord durci, pour toute ligne : chaque modèle déclaré sur chaque sortie scorée
(décision 3), une référence D8 par parcours de répétabilité, aux jours exacts
(décision 4) ; les refus d'``OutingOutcome``.
"""

import dataclasses
import re
import typing
from collections.abc import Callable
from dataclasses import replace
from datetime import timedelta
from pathlib import Path

import pytest

from fixtures.registry import (
    CALIBRATED_MODELS as DECLARED_MODELS,
)
from fixtures.registry import (
    OUTINGS,
    P03,
    Q20,
    Q27,
    REFERENCE_R1,
    at,
    d8_reference,
    declaration,
    not_calibrated,
    outcome,
    outcomes,
    references,
    registry_root,
    v0_of,
)
from fixtures.repeatability import DEUX_JOURS
from mountain_perf.backtest import (
    DOCUMENT_FIRST_FORMAT,
    DOCUMENT_SUFFIX,
    DOCUMENT_TYPES,
    DOCUMENTS_DIR,
    EVENTS_FILE,
    CodecError,
    RegistryError,
    append_declaration,
    append_result,
    canonical_bytes,
    content_hash,
    count_trials,
    declared_performance,
    decode_document,
    encode_contract,
    encode_document,
    load_outcomes,
    load_references,
    read_registry,
    verify_registry,
)
from mountain_perf.model.engine import ENGINE_VERSION
from mountain_perf.schemas import (
    REGISTRY_FORMAT_VERSION,
    REGISTRY_READABLE_FORMATS,
    CalibratedOutingScores,
    CalibratedScenarioScores,
    ContractError,
    DeclaredModel,
    DeclaredPerformance,
    Exclusion,
    ModelKind,
    ModelResult,
    OutingObservation,
    OutingOutcome,
    OutingScores,
    Performance,
    RegistryEvent,
    RepeatabilityReference,
    Result,
    ScenarioScores,
)
from test_backtest_registry_shape import _render

Q20_ID, Q27_ID, P03_ID = (outing.outing_id for outing in OUTINGS)
V0_RAW, V0_RECALIBRATED, CANDIDATE = DECLARED_MODELS
NAISMITH = DeclaredModel(
    ModelKind.NAISMITH, ENGINE_VERSION, None, "calage de 0010 D9.2"
)
"""Naismith déclarée à la version de la prévision de v0 que portent ses scores
``non calé`` (``not_calibrated``) : l'accord recoupe la version, pas la nature."""


# ---------------------------------------------------------------------------
# Aides : registres construits, puis récrits
# ---------------------------------------------------------------------------


def _calibrated(
    outing_id: str, *kinds: ModelKind
) -> tuple[tuple[ModelKind, OutingScores | CalibratedOutingScores], ...]:
    """v0 brut, puis chaque modèle calé ``non calé`` de prévision celle de v0."""
    v0 = v0_of(outing_id)
    return (
        (ModelKind.V0_RAW, v0),
        *((kind, not_calibrated(outing_id, kind, v0)) for kind in kinds),
    )


def _outcomes(*kinds: ModelKind) -> tuple[OutingOutcome, ...]:
    """``outcomes()``, chaque sortie portant aussi les modèles calés ``kinds``."""
    return tuple(
        OutingOutcome(
            item.outing_id, item.coverage, _calibrated(item.outing_id, *kinds)
        )
        for item in outcomes()
    )


def _registry(
    tmp_path: Path,
    models: tuple[DeclaredModel, ...] = (V0_RAW,),
    outcomes_: tuple[OutingOutcome, ...] | None = None,
) -> Path:
    """Une DÉCLARATION de ``models`` et son RÉSULTAT, écrits par le code du jour."""
    root = registry_root(tmp_path)
    append_declaration(root, declaration(models=models), recorded_at=at(0))
    append_result(
        root,
        1,
        outcomes() if outcomes_ is None else outcomes_,
        references=references(),
        recorded_at=at(1),
    )
    return root


def _documents(root: Path) -> list[Path]:
    return sorted((root / DOCUMENTS_DIR).iterdir())


def _with_shas(result: Result, shas: Callable[[str], str]) -> Result:
    """``result``, chaque document cité renommé par ``shas``."""
    return replace(
        result,
        outings=tuple(
            replace(
                outing,
                observation=shas(outing.observation),
                models=tuple(
                    replace(
                        model,
                        control=shas(model.control),
                        usage=None if model.usage is None else shas(model.usage),
                    )
                    for model in outing.models
                ),
            )
            for outing in result.outings
        ),
        references=tuple(
            replace(record, reference=shas(record.reference))
            for record in result.references
        ),
    )


def _write_events(root: Path, events: list[RegistryEvent]) -> None:
    """Le journal écrit depuis ``events``, la chaîne des empreintes recalculée."""
    previous: str | None = None
    lines = []
    for event in events:
        rewritten = replace(event, previous_hash=previous)
        line = canonical_bytes(encode_contract(rewritten))
        previous = content_hash(line)
        lines.append(line + b"\n")
    (root / EVENTS_FILE).write_bytes(b"".join(lines))


def _rewrite(root: Path, change: Callable[[RegistryEvent], RegistryEvent]) -> None:
    """Le journal récrit, chaque événement par ``change`` ; les documents ne bougent
    pas."""
    _write_events(root, [change(event) for event in read_registry(root).events])


def _to_format_1(
    root: Path, change: Callable[[RegistryEvent], RegistryEvent] = lambda e: e
) -> None:
    """Le registre récrit au format 1, comme l'écrivait le code de M4b-5 : chaque
    enveloppe de document à ``"format":1`` (son nom, son empreinte), chaque ligne à
    ``format_version`` 1 citant ces documents, la chaîne recalculée ; ``change``
    s'applique d'abord à chaque événement, au format 2."""
    events = [change(event) for event in read_registry(root).events]
    renamed: dict[str, str] = {}
    for path in _documents(root):
        data = path.read_bytes()
        head = re.match(rb'\{"type":"[A-Za-z]+","format":2,', data)
        assert head is not None
        rewritten = (
            head.group(0).replace(b'"format":2,', b'"format":1,') + data[head.end() :]
        )
        sha = content_hash(rewritten)
        renamed[path.name.removesuffix(DOCUMENT_SUFFIX)] = sha
        path.unlink()
        (path.parent / f"{sha}{DOCUMENT_SUFFIX}").write_bytes(rewritten)

    def to_1(event: RegistryEvent) -> RegistryEvent:
        result = (
            None
            if event.result is None
            else _with_shas(event.result, renamed.__getitem__)
        )
        return replace(event, format_version=1, result=result)

    _write_events(root, [to_1(event) for event in events])


def _models_of(
    event: RegistryEvent, change: Callable[[ModelKind], ModelKind]
) -> RegistryEvent:
    """``event``, la nature de chaque modèle, déclaré ou scoré, changée par
    ``change``."""
    if event.declaration is not None:
        models = tuple(
            replace(model, kind=change(model.kind))
            for model in event.declaration.models
        )
        return replace(event, declaration=replace(event.declaration, models=models))
    if event.result is not None:
        outings = tuple(
            replace(
                outing,
                models=tuple(
                    replace(model, model=change(model.model)) for model in outing.models
                ),
            )
            for outing in event.result.outings
        )
        return replace(event, result=replace(event.result, outings=outings))
    return event


def _scored_models(
    root: Path, change: Callable[[tuple[ModelResult, ...]], tuple[ModelResult, ...]]
) -> None:
    """Le RÉSULTAT 2 récrit, les ``ModelResult`` de chaque sortie changés par
    ``change`` (des documents échangés d'un modèle à l'autre)."""

    def on_result(event: RegistryEvent) -> RegistryEvent:
        if event.result is None:
            return event
        outings = tuple(
            replace(outing, models=change(outing.models))
            for outing in event.result.outings
        )
        return replace(event, result=replace(event.result, outings=outings))

    _rewrite(root, on_result)


def _shape(roots: list[type]) -> tuple[int, str]:
    """L'empreinte de forme de ``test_backtest_registry_shape.py``, depuis ``roots``."""
    seen: dict[str, str] = {}
    todo = list(roots)
    while todo:
        cls = todo.pop()
        if cls.__name__ in seen:
            continue
        hints = typing.get_type_hints(cls)
        parts = []
        for field in dataclasses.fields(cls):
            annotation = hints[field.name]
            parts.append(f"{field.name}:{_render(annotation)}")
            stack = [annotation]
            while stack:
                a = stack.pop()
                if dataclasses.is_dataclass(a) and isinstance(a, type):
                    todo.append(a)
                stack.extend(typing.get_args(a))
        seen[cls.__name__] = f"{cls.__name__}(" + ",".join(parts) + ")"
    text = "\n".join(sorted(seen.values()))
    return len(seen), content_hash(text.encode())


# ---------------------------------------------------------------------------
# Versions, forme, documents (§ 6.1, codec)
# ---------------------------------------------------------------------------


def test_versions() -> None:
    """§ 6.1 : le format écrit, les formats relus, le premier format de chaque type de
    document."""
    assert REGISTRY_FORMAT_VERSION == 2
    assert REGISTRY_READABLE_FORMATS == (1, 2)
    assert dict(DOCUMENT_FIRST_FORMAT) == {
        OutingObservation: 1,
        ScenarioScores: 1,
        RepeatabilityReference: 1,
        CalibratedScenarioScores: 2,
    }
    assert tuple(DOCUMENT_FIRST_FORMAT) == DOCUMENT_TYPES


def test_shape_of_format_1_is_unchanged() -> None:
    """Décision 1 : la forme de ``RegistryEvent`` et des trois documents du format 1
    est celle de M4b-4 — 44 contrats, ``4e2f2b55…`` (le format 2 n'en change aucun)."""
    assert _shape([RegistryEvent, *DOCUMENT_TYPES[:3]]) == (
        44,
        "4e2f2b5569ef8b6cdf9a1ea6d7c952bd1c14e5bb409f2f9653c43847dcb6d2ed",
    )


@pytest.mark.parametrize("format_version", [1, 2])
def test_document_at_the_requested_format(format_version: int) -> None:
    """§ 6.1, ``encode_document`` et ``decode_document`` : l'enveloppe porte le format
    demandé ; relu à ce format, le document redonne l'objet, et ses octets à la
    réécriture ; relu à l'autre format, il est refusé au format."""
    scores = v0_of(Q20_ID).control
    data = encode_document(scores, format_version)
    assert data.startswith(b'{"type":"ScenarioScores","format":%d,' % format_version)
    assert decode_document(data, ScenarioScores, format_version) == scores
    other = 3 - format_version
    with pytest.raises(
        CodecError,
        match=re.escape(f"document au format {format_version}, {other} attendu"),
    ):
        decode_document(data, ScenarioScores, other)


def test_calibrated_document_does_not_exist_at_format_1() -> None:
    """§ 6.1 : un document calé s'écrit au format 2 et pas au format 1 ; relu au
    format 1, il est refusé — au format de son enveloppe d'abord (``"format":2``), puis,
    d'une enveloppe ``"format":1``, parce que le format 1 ne le connaît pas."""
    scores = not_calibrated(Q20_ID, ModelKind.NAISMITH, v0_of(Q20_ID)).control
    data = encode_document(scores, 2)
    assert decode_document(data, CalibratedScenarioScores, 2) == scores
    with pytest.raises(
        TypeError,
        match=re.escape(
            "CalibratedScenarioScores n'existe qu'à partir du format 2, demandé au "
            "format 1."
        ),
    ):
        encode_document(scores, 1)
    with pytest.raises(CodecError, match=re.escape("document au format 2, 1 attendu")):
        decode_document(data, CalibratedScenarioScores, 1)
    forged = data.replace(b'"format":2,', b'"format":1,', 1)
    with pytest.raises(
        CodecError,
        match=re.escape(
            "document de type 'CalibratedScenarioScores' au format 1, qui ne le "
            "connaît pas"
        ),
    ):
        decode_document(forged, CalibratedScenarioScores, 1)


# ---------------------------------------------------------------------------
# Le format 1 relu ; le format 2 enchaîné (décisions 1, 4, 15)
# ---------------------------------------------------------------------------


def test_format_1_registry_is_read(tmp_path: Path) -> None:
    """Décision 1, précision de D14 (M4c-2) : un registre du format 1 se relit, se
    vérifie, et ses documents se relisent au format 1, chacun égal à l'objet écrit."""
    root = _registry(tmp_path)
    _to_format_1(root)
    for path in _documents(root):
        assert re.match(rb'\{"type":"[A-Za-z]+","format":1,', path.read_bytes())
    log = verify_registry(root)
    assert [event.format_version for event in log.events] == [1, 1]
    assert load_outcomes(root, log, 2) == outcomes()
    assert load_references(root, log, 2) == references()


def test_format_1_line_with_a_calibrated_model_is_not_verified(tmp_path: Path) -> None:
    """Décision 15, précision de D14 (M4c-2) : au format 1, aucun modèle n'était calé ;
    une ligne du format 1 qui en porte un — Naismith en ``ScenarioScores``, comme le
    code de M4b-5 l'écrivait — ne se vérifie pas : ses scores ne sont pas relus, le
    modèle nommé. ``read_registry`` ne décode pas les documents, et la relit."""
    candidate = (ModelKind.CANDIDATE, v0_of(Q20_ID))
    root = _registry(
        tmp_path,
        models=(V0_RAW, CANDIDATE),
        outcomes_=tuple(
            OutingOutcome(
                item.outing_id,
                item.coverage,
                (item.scores[0], (ModelKind.CANDIDATE, v0_of(item.outing_id))),
            )
            for item in outcomes()
        ),
    )
    assert candidate[1] == v0_of(Q20_ID)
    _to_format_1(
        root,
        lambda event: _models_of(
            event,
            lambda kind: ModelKind.NAISMITH if kind is ModelKind.CANDIDATE else kind,
        ),
    )
    log = read_registry(root)
    message = (
        "evenements.jsonl, ligne 2 : 'q-2026-05-20', naismith : un modèle calé n'a "
        "pas de scores au format 1, une ligne du format 1 ne le relit pas (précision "
        "de D14, M4c-2)"
    )
    with pytest.raises(RegistryError, match=re.escape(message)):
        verify_registry(root)
    with pytest.raises(RegistryError, match=re.escape(message)):
        load_outcomes(root, log, 2)


def test_format_2_append_follows_format_1(tmp_path: Path) -> None:
    """Précision de D14 (M4c-2) : un ajout du format 2 s'enchaîne à un registre du
    format 1 — une DÉCLARATION et un RÉSULTAT à deux modèles, v0 brut et un modèle calé
    ``non calé`` ; le journal entier se vérifie, chaque ligne à son format, et chaque
    DÉCLARATION compte pour un essai."""
    root = _registry(tmp_path)
    _to_format_1(root)
    append_declaration(
        root, declaration(models=(V0_RAW, V0_RECALIBRATED)), recorded_at=at(2)
    )
    written = _outcomes(ModelKind.V0_RECALIBRATED)
    append_result(root, 3, written, references=references(), recorded_at=at(3))
    log = verify_registry(root)
    assert [event.format_version for event in log.events] == [1, 1, 2, 2]
    assert count_trials(log).declarations == 2
    assert load_outcomes(root, log, 2) == outcomes()
    assert load_outcomes(root, log, 4) == written


def test_format_1_line_citing_a_format_2_document(tmp_path: Path) -> None:
    """Précision de D14 (M4c-2) : un document se relit au format de l'événement qui le
    cite ; une ligne du format 1 qui cite un document du format 2 est refusée à la
    vérification."""
    root = _registry(tmp_path)
    _rewrite(root, lambda event: replace(event, format_version=1))
    read_registry(root)
    with pytest.raises(
        RegistryError, match=re.escape("document au format 2, 1 attendu")
    ):
        verify_registry(root)


def test_format_2_result_is_read_back_at_bit(tmp_path: Path) -> None:
    """Précision de D14 (M4c-2) : un RÉSULTAT du format 2 à cinq modèles se relit égal,
    au bit, aux objets écrits — les scores calés de chaque modèle, usage compris."""
    models = (
        V0_RAW,
        V0_RECALIBRATED,
        NAISMITH,
        replace(NAISMITH, kind=ModelKind.CONSTANT_SPEED),
        replace(NAISMITH, kind=ModelKind.TOBLER),
    )
    written = _outcomes(
        ModelKind.V0_RECALIBRATED,
        ModelKind.CONSTANT_SPEED,
        ModelKind.NAISMITH,
        ModelKind.TOBLER,
    )
    root = _registry(tmp_path, models=models, outcomes_=written)
    log = verify_registry(root)
    read = load_outcomes(root, log, 2)
    assert read == written
    usage = dict(read[0].scores)[ModelKind.NAISMITH]
    assert isinstance(usage, CalibratedOutingScores)
    assert usage.usage is not None


# ---------------------------------------------------------------------------
# L'accord : chaque modèle déclaré (décision 3)
# ---------------------------------------------------------------------------


def test_scored_outing_carries_every_declared_model(tmp_path: Path) -> None:
    """Décision 3, D0, D9.2 : une sortie scorée l'est par chaque modèle déclaré, statut
    ``non calé`` compris ; l'absent est nommé, dans l'ordre de la déclaration."""
    root = registry_root(tmp_path)
    models = (V0_RAW, V0_RECALIBRATED, NAISMITH)
    append_declaration(root, declaration(models=models), recorded_at=at(0))
    complete = _outcomes(ModelKind.V0_RECALIBRATED, ModelKind.NAISMITH)
    lacking = (
        complete[0],
        OutingOutcome(Q27_ID, complete[1].coverage, complete[1].scores[:1]),
        complete[2],
    )
    with pytest.raises(
        RegistryError,
        match=re.escape(
            "ajout refusé : 'q-2026-05-27', une sortie scorée l'est par chaque modèle "
            "déclaré (D0, D9.2) ; absent : v0_recalibrated, naismith"
        ),
    ):
        append_result(root, 1, lacking, references=references())
    assert append_result(root, 1, complete, references=references()).number == 2


def test_undeclared_model_is_named_before_an_absent_one(tmp_path: Path) -> None:
    """Décision 3, § 6.1 : l'accord nomme d'abord un modèle de trop, puis un modèle
    absent."""
    root = registry_root(tmp_path)
    append_declaration(
        root, declaration(models=(V0_RAW, V0_RECALIBRATED)), recorded_at=at(0)
    )
    first = outcome(Q20_ID)
    extra = OutingOutcome(
        Q20_ID, first.coverage, (*first.scores, (ModelKind.CANDIDATE, v0_of(Q20_ID)))
    )
    with pytest.raises(
        RegistryError, match=re.escape("ajout refusé : modèle non déclaré, candidate")
    ):
        append_result(root, 1, (extra, *outcomes()[1:]), references=references())


def test_calibrated_model_citing_scenario_scores(tmp_path: Path) -> None:
    """§ 6.1, relecture d'un modèle calé : son ``ModelResult`` cite des
    ``CalibratedScenarioScores`` ; un document de ``ScenarioScores`` est refusé."""
    root = _registry(
        tmp_path,
        models=(V0_RAW, V0_RECALIBRATED),
        outcomes_=_outcomes(ModelKind.V0_RECALIBRATED),
    )

    def v0_documents(models: tuple[ModelResult, ...]) -> tuple[ModelResult, ...]:
        raw, recalibrated = models
        return raw, replace(raw, model=recalibrated.model)

    _scored_models(root, v0_documents)
    read_registry(root)
    with pytest.raises(
        RegistryError,
        match=re.escape(
            "document de type 'ScenarioScores', 'CalibratedScenarioScores' attendu"
        ),
    ):
        verify_registry(root)


def test_calibrated_scores_of_another_model(tmp_path: Path) -> None:
    """§ 6.1, relecture d'un modèle calé : ses scores calés portent son modèle ; ceux
    d'un autre modèle calé sont refusés, le modèle nommé."""
    root = _registry(
        tmp_path,
        models=(V0_RAW, V0_RECALIBRATED, NAISMITH),
        outcomes_=_outcomes(ModelKind.V0_RECALIBRATED, ModelKind.NAISMITH),
    )

    def swapped(models: tuple[ModelResult, ...]) -> tuple[ModelResult, ...]:
        raw, recalibrated, naismith = models
        return (
            raw,
            replace(naismith, model=recalibrated.model),
            replace(recalibrated, model=naismith.model),
        )

    _scored_models(root, swapped)
    log = read_registry(root)
    message = (
        "evenements.jsonl, ligne 2 : 'q-2026-05-20', les scores calés portent le "
        "modèle naismith, v0_recalibrated attendu"
    )
    with pytest.raises(RegistryError, match=re.escape(message)):
        verify_registry(root)
    with pytest.raises(RegistryError, match=re.escape(message)):
        load_outcomes(root, log, 2)


# ---------------------------------------------------------------------------
# L'accord : une référence D8 par parcours, aux jours exacts (décision 4)
# ---------------------------------------------------------------------------


def _declared(tmp_path: Path, **changes: object) -> Path:
    root = registry_root(tmp_path)
    append_declaration(root, declaration(**changes), recorded_at=at(0))
    return root


def test_repeatability_route_without_reference(tmp_path: Path) -> None:
    """Décision 4, précision de D14 (M4c-2) : chaque parcours du jeu de répétabilité a
    sa référence D8."""
    root = _declared(tmp_path)
    with pytest.raises(
        RegistryError,
        match=re.escape(
            "ajout refusé : le parcours de répétabilité 'r1' n'a pas de référence D8"
        ),
    ):
        append_result(root, 1, outcomes())


def test_missing_reference_is_checked_last(tmp_path: Path) -> None:
    """§ 6.1, ``_agree_documents`` : le parcours sans référence se contrôle en dernier ;
    un RÉSULTAT sans référence dont une prévision est fausse est refusé au motif de la
    prévision."""
    root = _declared(tmp_path)
    scores = v0_of(Q20_ID)
    forecast = replace(scores.control.forecast, source=Q27.traces[0].source)
    wrong = replace(scores, control=replace(scores.control, forecast=forecast))
    first = outcome(Q20_ID)
    scored = (
        OutingOutcome(Q20_ID, first.coverage, ((ModelKind.V0_RAW, wrong),)),
        *outcomes()[1:],
    )
    with pytest.raises(
        RegistryError,
        match=re.escape("la prévision ne nomme pas la première trace déclarée"),
    ):
        append_result(root, 1, scored)


def _multi_day() -> tuple[DeclaredPerformance, ...]:
    """Les performances déclarées où le 2026-05-20 de ``r1`` a deux sorties."""
    later = replace(
        Q20,
        outing_id="q-2026-05-20-b",
        start_time=Q20.start_time + timedelta(hours=4),
        end_time=Q20.end_time + timedelta(hours=4),
    )
    day = declared_performance(Performance(Q20.start_time.date(), (Q20, later)))
    others = tuple(
        declared_performance(Performance(outing.start_time.date(), (outing,)))
        for outing in (Q27, P03)
    )
    return (day, *others)


SOURCE = REFERENCE_R1.artifact.source


@pytest.mark.parametrize(
    ("case", "message"),
    [
        (
            "jour scoré omis",
            "la référence de 'r1' omet le jour 2026-05-20 du jeu de répétabilité",
        ),
        (
            "jour non scoré porté",
            "la référence de 'r1' porte le jour 2026-05-20, qui n'en est pas un du "
            "jeu de répétabilité",
        ),
        (
            "jour multi-sorties omis",
            "la référence de 'r1' omet le jour multi-sorties 2026-05-20 du jeu de "
            "répétabilité",
        ),
        (
            "jour d'une sortie parmi les multi-sorties",
            "la référence de 'r1' porte le jour multi-sorties 2026-05-20, qui n'en "
            "est pas un du jeu de répétabilité",
        ),
    ],
)
def test_reference_days_are_exact(tmp_path: Path, case: str, message: str) -> None:
    """Décision 4, précision de D14 (M4c-2) : les jours d'une référence D8 sont
    exactement ceux d'une seule sortie scorée du jeu sur ce parcours, et ses jours
    multi-sorties ceux du jeu sur ce parcours ; chaque écart, par son message. La
    référence exacte du même RÉSULTAT est acceptée."""
    single = [DEUX_JOURS[1]]
    multi = [replace(DEUX_JOURS[0], multi=True), DEUX_JOURS[1]]
    unscored_q20 = (Exclusion(Q20_ID, "trace illisible"),)
    unscored_b = (Exclusion("q-2026-05-20-b", "trace illisible"),)
    scored = outcomes()
    unscored: tuple[Exclusion, ...] = unscored_b
    changes: dict[str, object] = {"performances": _multi_day()}
    if case == "jour scoré omis":
        changes, unscored, wrong, right = {}, (), single, list(DEUX_JOURS)
    elif case == "jour non scoré porté":
        changes, scored, unscored = {}, outcomes()[1:], unscored_q20
        wrong, right = list(DEUX_JOURS), single
    elif case == "jour multi-sorties omis":
        wrong, right = single, multi
    else:
        changes, scored, unscored = {}, outcomes()[1:], unscored_q20
        wrong, right = multi, single
    root = _declared(tmp_path, **changes)
    with pytest.raises(RegistryError, match=re.escape(f"ajout refusé : {message}")):
        append_result(
            root,
            1,
            scored,
            unscored=unscored,
            references=(("r1", d8_reference(SOURCE, wrong)),),
        )
    event = append_result(
        root,
        1,
        scored,
        unscored=unscored,
        references=(("r1", d8_reference(SOURCE, right)),),
    )
    assert event.number == 2
    verify_registry(root)


def test_reference_days_hold_for_every_format(tmp_path: Path) -> None:
    """Décision 4 : l'accord durci vaut pour toute ligne, de tout format — une ligne
    du format 1 dont la référence omet un jour scoré n'est pas vérifiée."""
    root = registry_root(tmp_path)
    append_declaration(root, declaration(), recorded_at=at(0))
    append_result(root, 1, outcomes(), references=references(), recorded_at=at(1))
    lacking = d8_reference(SOURCE, [DEUX_JOURS[1]])
    sha = content_hash(encode_document(lacking))
    (root / DOCUMENTS_DIR / f"{sha}{DOCUMENT_SUFFIX}").write_bytes(
        encode_document(lacking)
    )

    def lacking_day(event: RegistryEvent) -> RegistryEvent:
        if event.result is None:
            return event
        records = tuple(replace(r, reference=sha) for r in event.result.references)
        return replace(event, result=replace(event.result, references=records))

    _to_format_1(root, lacking_day)
    with pytest.raises(
        RegistryError,
        match=re.escape(
            "evenements.jsonl, ligne 2 : la référence de 'r1' omet le jour 2026-05-20 "
            "du jeu de répétabilité"
        ),
    ):
        verify_registry(root)


# ---------------------------------------------------------------------------
# OutingOutcome (§ 6.1)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("kind", "scores", "message"),
    [
        (
            ModelKind.NAISMITH,
            lambda: v0_of(Q20_ID),
            "naismith est un modèle calé : ses scores sont des CalibratedOutingScores.",
        ),
        (
            ModelKind.NAISMITH,
            lambda: not_calibrated(Q20_ID, ModelKind.TOBLER, v0_of(Q20_ID)),
            "les scores calés de naismith portent le modèle tobler.",
        ),
        (
            ModelKind.NAISMITH,
            lambda: not_calibrated("autre", ModelKind.NAISMITH, v0_of(Q20_ID)),
            "les scores calés de naismith portent la sortie 'autre', 'q-2026-05-20' "
            "attendue.",
        ),
        (
            ModelKind.CANDIDATE,
            lambda: not_calibrated(Q20_ID, ModelKind.NAISMITH, v0_of(Q20_ID)),
            "candidate n'est pas un modèle calé : ses scores sont des OutingScores.",
        ),
    ],
)
def test_outing_outcome_refusals(
    kind: ModelKind,
    scores: Callable[[], OutingScores | CalibratedOutingScores],
    message: str,
) -> None:
    """§ 6.1, invariant neuf d'``OutingOutcome`` : un modèle calé porte des scores
    calés, de ce modèle et de cette sortie ; un autre modèle, des ``OutingScores``."""
    first = outcome(Q20_ID)
    with pytest.raises(ContractError, match=re.escape(message)):
        OutingOutcome(Q20_ID, first.coverage, (*first.scores, (kind, scores())))


def test_outing_outcome_raw_with_calibrated_scores() -> None:
    """§ 6.1 : v0 brut n'est pas un modèle calé — des scores calés lui sont refusés."""
    first = outcome(Q20_ID)
    scores = not_calibrated(Q20_ID, ModelKind.V0_RECALIBRATED, v0_of(Q20_ID))
    with pytest.raises(
        ContractError,
        match=re.escape(
            "v0_raw n'est pas un modèle calé : ses scores sont des OutingScores."
        ),
    ):
        OutingOutcome(Q20_ID, first.coverage, ((ModelKind.V0_RAW, scores),))


def test_outing_outcome_accepts_a_calibrated_model() -> None:
    """§ 6.1 : v0 brut et un modèle calé, chacun de son type, sur la même
    observation."""
    first = outcome(Q20_ID)
    calibrated = not_calibrated(Q20_ID, ModelKind.NAISMITH, v0_of(Q20_ID))
    accepted = OutingOutcome(
        Q20_ID, first.coverage, (*first.scores, (ModelKind.NAISMITH, calibrated))
    )
    assert accepted.scores[1] == (ModelKind.NAISMITH, calibrated)
