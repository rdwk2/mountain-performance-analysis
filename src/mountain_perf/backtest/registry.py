"""Le registre des expériences sur disque : journal, documents, ajout, relecture,
comptage des essais (M4b-4).

Protocole : ``docs/decisions/0010`` D14 (et ses précisions de M4b-4), D0, D2.5, D2.6.
Un dossier, donné par l'appelant :

- ``evenements.jsonl`` : le journal, une ligne par événement, son écriture canonique
  suivie de ``\\n`` ; chaque ligne porte l'empreinte de la précédente ;
- ``documents/<sha256>.json`` : observations, scores avec leurs prévisions, références
  D8, chacun nommé par l'empreinte de ses octets ;
- ``verrou`` : présent pendant un ajout, et seulement pendant.

Le code ajoute en fin de journal et ne réécrit jamais rien ; tout s'écrit et se lit en
octets. Les messages nomment les fichiers par leur chemin dans le registre, jamais par
un chemin absolu (règle 1) ; les erreurs du système de fichiers (``OSError``) remontent
telles quelles.
"""

from __future__ import annotations

import json
import os
from collections import Counter
from collections.abc import Callable, Iterator, Mapping
from contextlib import contextmanager
from datetime import UTC, date, datetime
from pathlib import Path

from mountain_perf.backtest.calendar import origin
from mountain_perf.backtest.codec import (
    CodecError,
    canonical_bytes,
    content_hash,
    decode_contract,
    decode_document,
    encode_contract,
    encode_document,
)
from mountain_perf.model.curve_io import META_SUFFIX, CurveReadResult
from mountain_perf.schemas import (
    REGISTRY_FORMAT_VERSION,
    ArtifactRef,
    ArtifactRole,
    DataSet,
    Declaration,
    DeclaredModel,
    DeclaredPerformance,
    EventKind,
    Exclusion,
    ExperimentMetric,
    ExperimentTrials,
    Failure,
    ModelKind,
    ModelResult,
    Outing,
    OutingObservation,
    OutingOutcome,
    OutingResult,
    OutingScores,
    Performance,
    RegistryEvent,
    RegistryLog,
    RepeatabilityRecord,
    RepeatabilityReference,
    Result,
    Scenario,
    ScenarioScores,
    SourceRef,
    TrialCounts,
)
from mountain_perf.validation import ContractError

EVENTS_FILE = "evenements.jsonl"
"""Le journal : une ligne par événement, ajoutée en fin, jamais réécrite."""

DOCUMENTS_DIR = "documents"
"""Le dossier des documents, nommés par leur empreinte."""

DOCUMENT_SUFFIX = ".json"
"""Le suffixe d'un document : ``<sha256>.json``."""

LOCK_FILE = "verrou"
"""Le verrou d'un ajout : présent pendant un ajout, et seulement pendant."""

CURVE_METADATA_KIND = "json"
"""La nature (``SourceRef.kind``) du compagnon ``.meta.json`` d'une courbe."""

CURVE_MODELS: frozenset[ModelKind] = frozenset(
    {ModelKind.V0_RAW, ModelKind.V0_RECALIBRATED, ModelKind.CANDIDATE}
)
"""Les modèles qui projettent avec la courbe : leurs prévisions recopient le
``curve_ref`` de la déclaration ; une baseline ne le recopie pas (précision de D14)."""

_REFUSED = "ajout refusé : "


class RegistryError(ValueError):
    """Registre illisible, incohérent, verrouillé, ou ajout refusé.

    Le message nomme les fichiers par leur chemin dans le registre
    (``evenements.jsonl, ligne 3``, ``documents/<sha256>.json``).
    """


def _line_prefix(number: int) -> str:
    return f"{EVENTS_FILE}, ligne {number} : "


def _document_name(sha: str) -> str:
    return f"{DOCUMENTS_DIR}/{sha}{DOCUMENT_SUFFIX}"


def _document_path(root: Path, sha: str) -> Path:
    return root / DOCUMENTS_DIR / f"{sha}{DOCUMENT_SUFFIX}"


def _line(event: RegistryEvent) -> bytes:
    """La ligne d'un événement : son écriture canonique, sans fin de ligne."""
    return canonical_bytes(encode_contract(event))


def line_hash(event: RegistryEvent) -> str:
    """L'empreinte ``sha256`` de la ligne canonique d'un événement, sans fin de ligne :
    celle que porte l'événement suivant (``previous_hash``) ; celle de la dernière
    ligne du journal scelle le registre (``0010`` D14 et sa précision de M4b-5)."""
    return content_hash(_line(event))


# ---------------------------------------------------------------------------
# Relecture
# ---------------------------------------------------------------------------


def read_registry(root: Path) -> RegistryLog:
    """Le journal relu et vérifié ; les documents cités présents et intacts.

    Dans cet ordre, au premier défaut ``RegistryError`` : le dossier ; la fin du
    journal (``\\n``), avant toute ligne ; ligne par ligne, JSON, décodage, écriture
    canonique, numéro, chaîne des empreintes ; les liens du journal ; puis, résultat
    par résultat, l'accord sans documents avec sa déclaration et chaque document cité,
    présent et intact. Les documents ne sont pas décodés (``verify_registry``).
    """
    if not root.is_dir():
        raise RegistryError("registre introuvable : son dossier n'existe pas.")
    path = root / EVENTS_FILE
    data = path.read_bytes() if path.exists() else b""
    if not data:
        return RegistryLog(())
    try:
        log = RegistryLog(_read_events(data))
    except ContractError as error:
        raise RegistryError(f"{EVENTS_FILE} : {error}") from error
    for event in log.events:
        if event.result is not None:
            _agree(
                _declaration_of(log, event), event.result, _line_prefix(event.number)
            )
            for sha in _cited(event.result):
                _stored(root, sha)
    return log


def _read_events(data: bytes) -> tuple[RegistryEvent, ...]:
    if not data.endswith(b"\n"):
        number = data.count(b"\n") + 1
        raise RegistryError(
            f"{_line_prefix(number)}ligne tronquée (sans fin de ligne) : "
            "un ajout a été interrompu. Si aucun ajout n'est en cours, retirer cette "
            "ligne incomplète à la main (le code ne réécrit jamais le journal)."
        )
    events: list[RegistryEvent] = []
    previous: bytes | None = None
    # Coupées sur l'octet \n seul : splitlines couperait aussi sur \r, U+2028, U+0085.
    for number, line in enumerate(data.split(b"\n")[:-1], start=1):
        prefix = _line_prefix(number)
        try:
            raw = json.loads(line.decode("utf-8"))
        except ValueError:
            # UnicodeDecodeError, JSONDecodeError, entier de plus de 4 300 chiffres.
            raise RegistryError(f"{prefix}JSON illisible") from None
        try:
            event = decode_contract(RegistryEvent, raw)
        except (CodecError, ContractError) as error:
            raise RegistryError(f"{prefix}{error}") from error
        if _line(event) != line:
            raise RegistryError(f"{prefix}écriture non canonique")
        if event.number != number:
            raise RegistryError(
                f"{prefix}porte le numéro {event.number}, {number} attendu"
            )
        expected = None if previous is None else content_hash(previous)
        if event.previous_hash != expected:
            raise RegistryError(
                f"{prefix}l'empreinte de la ligne précédente ne correspond pas"
            )
        events.append(event)
        previous = line
    return tuple(events)


def _declaration_of(log: RegistryLog, event: RegistryEvent) -> Declaration:
    """La déclaration à laquelle répond ``event``."""
    assert event.answers is not None  # contrat de RegistryEvent
    declaration = log.event(event.answers).declaration
    assert declaration is not None  # contrat de RegistryLog
    return declaration


def _cited(result: Result) -> list[str]:
    """Les documents d'un résultat, dans l'ordre : par sortie, l'observation puis, par
    modèle, le contrôle et l'usage ; puis les références."""
    cited: list[str] = []
    for outing in result.outings:
        cited.append(outing.observation)
        for model in outing.models:
            cited.append(model.control)
            if model.usage is not None:
                cited.append(model.usage)
    cited.extend(record.reference for record in result.references)
    return cited


def _stored(root: Path, sha: str) -> bytes:
    """Les octets du document ``sha``, présent et intact ; ``RegistryError`` sinon."""
    try:
        data = _document_path(root, sha).read_bytes()
    except FileNotFoundError:
        raise RegistryError(f"{_document_name(sha)} : document introuvable") from None
    if content_hash(data) != sha:
        raise RegistryError(
            f"{_document_name(sha)} : document altéré (empreinte différente)"
        )
    return data


def verify_registry(root: Path) -> RegistryLog:
    """``read_registry``, puis, résultat par résultat, l'accord par les documents :
    chaque document cité décodé, ses scores reconstruits, ses prévisions recoupées
    avec la déclaration, ses références D8 avec les jours déclarés."""
    log = read_registry(root)
    for event in log.events:
        if event.result is not None:
            _agree_documents(
                _declaration_of(log, event),
                event.result,
                lambda sha: _stored(root, sha),
                _line_prefix(event.number),
                "",
            )
    return log


# ---------------------------------------------------------------------------
# Accord d'un résultat avec sa déclaration
# ---------------------------------------------------------------------------


def _declared_outings(declaration: Declaration) -> dict[str, Outing]:
    return {
        outing.outing_id: outing
        for declared in declaration.performances
        for outing in declared.performance.outings
    }


def _agree(declaration: Declaration, result: Result, prefix: str) -> None:
    """L'accord sans documents (``0010`` D0, D3, D14) : chaque sortie du résultat est
    déclarée ; chaque sortie déclarée a un sort ; une sortie scorée est tracée, ses
    modèles sont déclarés, son usage existe si et seulement si elle a une référence ;
    les parcours des références D8 sont déclarés."""
    outings = _declared_outings(declaration)
    fates = [outing.outing_id for outing in result.outings]
    fates += [exclusion.outing_id for exclusion in result.unscored]
    for outing_id in fates:
        if outing_id not in outings:
            raise RegistryError(f"{prefix}sortie non déclarée, {outing_id!r}")
    for outing_id in declaration.outing_ids:
        if outing_id not in fates:
            raise RegistryError(
                f"{prefix}la sortie déclarée {outing_id!r} n'est ni scorée ni écartée "
                "avec un motif"
            )
    kinds = {model.kind for model in declaration.models}
    for scored in result.outings:
        outing = outings[scored.outing_id]
        if not outing.traces:
            raise RegistryError(
                f"{prefix}{scored.outing_id!r}, une sortie scorée a au moins une "
                "trace (l'observation vient de la trace ; une sortie non tracée "
                "s'écarte avec un motif)"
            )
        for model in scored.models:
            if model.model not in kinds:
                raise RegistryError(f"{prefix}modèle non déclaré, {model.model}")
            if (model.usage is not None) != (outing.reference is not None):
                raise RegistryError(
                    f"{prefix}{scored.outing_id!r}, le scénario usage est présent "
                    "si et seulement si la sortie a une référence (D3)"
                )
    route_ids = declaration.route_ids
    for record in result.references:
        if record.route_id not in route_ids:
            raise RegistryError(f"{prefix}parcours non déclaré, {record.route_id!r}")


def _decoded[T](
    read: Callable[[str], bytes], sha: str, expected: type[T], prefix: str
) -> T:
    """Le document ``sha`` décodé ; ses erreurs, préfixées de son nom."""
    try:
        return decode_document(read(sha), expected)
    except (CodecError, ContractError) as error:
        raise RegistryError(f"{prefix}{_document_name(sha)} : {error}") from error


def _model_scores(
    scored: OutingResult,
    read: Callable[[str], bytes],
    prefix: str,
    document_prefix: str,
) -> Iterator[tuple[ModelKind, OutingScores]]:
    """Les scores de chaque modèle d'une sortie scorée, reconstruits depuis ses
    documents : l'observation, puis, modèle par modèle, le contrôle et l'usage."""
    observation = _decoded(read, scored.observation, OutingObservation, document_prefix)
    for model in scored.models:
        control = _decoded(read, model.control, ScenarioScores, document_prefix)
        usage = (
            None
            if model.usage is None
            else _decoded(read, model.usage, ScenarioScores, document_prefix)
        )
        try:
            scores = OutingScores(observation, control, usage)
        except ContractError as error:
            raise RegistryError(f"{prefix}{scored.outing_id!r}, {error}") from error
        yield model.model, scores


def _agree_documents(
    declaration: Declaration,
    result: Result,
    read: Callable[[str], bytes],
    prefix: str,
    document_prefix: str,
) -> None:
    """L'accord par les documents (``0010`` D14, D2.6) : les scores de chaque sortie se
    reconstruisent, leurs prévisions recopient la déclaration de leur modèle et nomment
    un fichier déclaré de leur sortie ; les jours des références D8 sont déclarés, puis
    leur fichier est recoupé avec la référence déclarée des sorties de répétabilité de
    leur parcours (précision de D14, M4b-5)."""
    outings = _declared_outings(declaration)
    models = {model.kind: model for model in declaration.models}
    for scored in result.outings:
        outing = outings[scored.outing_id]
        for kind, scores in _model_scores(scored, read, prefix, document_prefix):
            _check_forecasts(declaration, models[kind], outing, scores, prefix)
    for record in result.references:
        reference = _decoded(
            read, record.reference, RepeatabilityReference, document_prefix
        )
        _check_reference_days(declaration, record.route_id, reference, prefix)
        _check_reference_outings(declaration, record.route_id, reference, prefix)


def _check_forecasts(
    declaration: Declaration,
    model: DeclaredModel,
    outing: Outing,
    scores: OutingScores,
    prefix: str,
) -> None:
    for scenario_scores in (scores.control, scores.usage):
        if scenario_scores is None:
            continue
        forecast = scenario_scores.forecast
        where = f"{prefix}{outing.outing_id!r}, {model.kind}, {forecast.scenario} : "
        if forecast.engine_version != model.engine_version:
            raise RegistryError(
                f"{where}version du moteur différente de la déclaration "
                f"({forecast.engine_version!r}, {model.engine_version!r} déclarée)"
            )
        if model.kind in CURVE_MODELS and forecast.curve_ref != declaration.curve_ref:
            raise RegistryError(
                f"{where}courbe différente de la déclaration ({forecast.curve_ref!r}, "
                f"{declaration.curve_ref!r} déclarée)"
            )
        if model.estimation_rule is None and forecast.parameters != model.parameters:
            raise RegistryError(f"{where}paramètres différents des paramètres déclarés")
        if forecast.scenario is Scenario.USAGE:
            reference = outing.reference
            declared = None if reference is None else reference.artifact.source
            if (
                declared is None
                or forecast.source.content_hash != declared.content_hash
            ):
                raise RegistryError(
                    f"{where}la prévision ne nomme pas la référence déclarée de la "
                    "sortie (empreinte différente)"
                )
        elif forecast.source.content_hash != outing.traces[0].source.content_hash:
            raise RegistryError(
                f"{where}la prévision ne nomme pas la première trace déclarée de la "
                "sortie (empreinte différente)"
            )


def _check_reference_days(
    declaration: Declaration,
    route_id: str,
    reference: RepeatabilityReference,
    prefix: str,
) -> None:
    days: set[date] = {
        declared.performance.civil_date
        for declared in declaration.performances
        if any(outing.route_id == route_id for outing in declared.performance.outings)
    }
    for day in (*reference.days, *reference.multi_outing_days):
        if day not in days:
            raise RegistryError(
                f"{prefix}la référence de {route_id!r} porte un jour non déclaré "
                f"sur ce parcours, {day.isoformat()}"
            )


def _check_reference_outings(
    declaration: Declaration,
    route_id: str,
    reference: RepeatabilityReference,
    prefix: str,
) -> None:
    """Le recoupement d'une référence D8 (précision de D14, M4b-5 ; décisions Q11 et
    Q14) : à chacun de ses jours, multi-sorties compris, chaque sortie déclarée du jeu
    de répétabilité sur son parcours a une référence déclarée de même empreinte que le
    fichier de la référence D8. Seule l'empreinte compte, pas le nom ; une sortie d'un
    autre parcours, d'un autre jeu ou d'un autre jour n'y est pas tenue."""
    days = {*reference.days, *reference.multi_outing_days}
    expected = reference.reference.content_hash
    for declared in declaration.performances:
        if declared.performance.civil_date not in days:
            continue
        for outing in declared.performance.outings:
            held = outing.dataset is DataSet.REPEATABILITY
            if not held or outing.route_id != route_id:
                continue
            declared_reference = outing.reference
            if (
                declared_reference is None
                or declared_reference.artifact.source.content_hash != expected
            ):
                raise RegistryError(
                    f"{prefix}la référence de {route_id!r} ne nomme pas la référence "
                    f"déclarée de la sortie {outing.outing_id!r} (empreinte différente)"
                )


# ---------------------------------------------------------------------------
# Ajout
# ---------------------------------------------------------------------------


def append_declaration(
    root: Path,
    declaration: Declaration,
    *,
    recorded_at: datetime | None = None,
    corrects: int | None = None,
    correction_reason: str | None = None,
) -> RegistryEvent:
    """Ajoute une DÉCLARATION (``0010`` D14) ; rend l'événement écrit.

    Une correction est une DÉCLARATION neuve qui nomme celle qu'elle corrige et son
    motif ; chaque DÉCLARATION compte pour un essai, corrections comprises.
    """
    return _append(
        root,
        EventKind.DECLARATION,
        answers=None,
        declaration=declaration,
        documents={},
        recorded_at=recorded_at,
        corrects=corrects,
        correction_reason=correction_reason,
    )


def append_result(
    root: Path,
    declaration: int,
    outcomes: tuple[OutingOutcome, ...],
    *,
    unscored: tuple[Exclusion, ...] = (),
    references: tuple[tuple[str, RepeatabilityReference], ...] = (),
    recorded_at: datetime | None = None,
    corrects: int | None = None,
    correction_reason: str | None = None,
) -> RegistryEvent:
    """Ajoute un RÉSULTAT à la déclaration numéro ``declaration`` (``0010`` D14, D0) ;
    rend l'événement écrit.

    Les observations, les scores (prévisions comprises) et les références D8 sont
    écrits en documents, cités par empreinte ; chaque sortie déclarée est scorée
    (``outcomes``) ou écartée avec un motif (``unscored``).
    """
    result, documents = _result_documents(outcomes, unscored, references)
    return _append(
        root,
        EventKind.RESULT,
        answers=declaration,
        result=result,
        documents=documents,
        recorded_at=recorded_at,
        corrects=corrects,
        correction_reason=correction_reason,
    )


def append_failure(
    root: Path,
    declaration: int,
    failure: Failure,
    *,
    recorded_at: datetime | None = None,
    corrects: int | None = None,
    correction_reason: str | None = None,
) -> RegistryEvent:
    """Ajoute un ÉCHEC à la déclaration numéro ``declaration`` (``0010`` D14) ; rend
    l'événement écrit."""
    return _append(
        root,
        EventKind.FAILURE,
        answers=declaration,
        failure=failure,
        documents={},
        recorded_at=recorded_at,
        corrects=corrects,
        correction_reason=correction_reason,
    )


def _result_documents(
    outcomes: tuple[OutingOutcome, ...],
    unscored: tuple[Exclusion, ...],
    references: tuple[tuple[str, RepeatabilityReference], ...],
) -> tuple[Result, dict[str, bytes]]:
    """Étape 0 de l'ajout d'un résultat, avant tout accès au registre : les documents
    écrits en mémoire, dans l'ordre, chacun une fois ; le ``Result`` qui les cite."""
    documents: dict[str, bytes] = {}

    def store(value: object) -> str:
        try:
            data = encode_document(value)
        except CodecError as error:
            raise RegistryError(f"{_REFUSED}{error}") from error
        sha = content_hash(data)
        documents.setdefault(sha, data)
        return sha

    outings: list[OutingResult] = []
    for outcome in outcomes:
        observation = store(outcome.scores[0][1].observation)
        models = tuple(
            ModelResult(
                kind,
                store(scores.control),
                None if scores.usage is None else store(scores.usage),
            )
            for kind, scores in outcome.scores
        )
        outings.append(
            OutingResult(outcome.outing_id, outcome.coverage, observation, models)
        )
    records = tuple(
        RepeatabilityRecord(route_id, store(reference))
        for route_id, reference in references
    )
    return Result(tuple(outings), unscored, records), documents


def _append(
    root: Path,
    kind: EventKind,
    *,
    answers: int | None,
    declaration: Declaration | None = None,
    result: Result | None = None,
    failure: Failure | None = None,
    documents: Mapping[str, bytes],
    recorded_at: datetime | None,
    corrects: int | None,
    correction_reason: str | None,
) -> RegistryEvent:
    """Étapes 1 à 7 de l'ajout : rien n'est écrit tant que tout n'est pas contrôlé."""
    _create(root)
    with _locked(root):
        log = read_registry(root)
        previous = line_hash(log.events[-1]) if log.events else None
        try:
            event = RegistryEvent(
                format_version=REGISTRY_FORMAT_VERSION,
                number=len(log.events) + 1,
                kind=kind,
                recorded_at=datetime.now(UTC) if recorded_at is None else recorded_at,
                previous_hash=previous,
                answers=answers,
                corrects=corrects,
                correction_reason=correction_reason,
                declaration=declaration,
                result=result,
                failure=failure,
            )
        except ContractError as error:
            raise RegistryError(f"{_REFUSED}{error}") from error
        try:
            line = _line(event)
        except CodecError as error:
            raise RegistryError(f"{_REFUSED}{error}") from error
        try:
            extended = RegistryLog((*log.events, event))
        except ContractError as error:
            raise RegistryError(f"{EVENTS_FILE} : {error}") from error
        if result is not None:
            declared = _declaration_of(extended, event)
            _agree(declared, result, _REFUSED)
            _agree_documents(
                declared, result, documents.__getitem__, _REFUSED, _REFUSED
            )
        _write(root, documents, line)
    return event


def _create(root: Path) -> None:
    """Crée le dossier du registre, jamais son parent."""
    if root.exists():
        return
    try:
        root.mkdir()
    except FileNotFoundError:
        raise RegistryError(
            "registre impossible à créer : son dossier parent n'existe pas."
        ) from None


@contextmanager
def _locked(root: Path) -> Iterator[None]:
    """Le verrou d'un ajout : créé exclusivement, fermé aussitôt, retiré quoi qu'il
    arrive ensuite ; un verrou déjà présent n'est jamais retiré."""
    lock = root / LOCK_FILE
    try:
        descriptor = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError:
        raise RegistryError(
            "registre verrouillé : le fichier « verrou » existe. Si aucun ajout n'est "
            "en cours (plantage), le supprimer à la main."
        ) from None
    try:
        os.close(descriptor)
        yield
    finally:
        lock.unlink(missing_ok=True)


def _write(root: Path, documents: Mapping[str, bytes], line: bytes) -> None:
    """Étape 7 : tous les documents déjà présents contrôlés, puis les absents écrits
    (temporaire, ``fsync``, ``os.replace``), puis la ligne ajoutée en fin de journal."""
    absent: list[tuple[Path, bytes]] = []
    for sha, data in documents.items():
        path = _document_path(root, sha)
        if not path.exists():
            absent.append((path, data))
        elif content_hash(path.read_bytes()) != sha:
            raise RegistryError(
                f"{_REFUSED}{_document_name(sha)} : document altéré (empreinte "
                "différente) ; rien n'est écrit"
            )
    if absent:
        (root / DOCUMENTS_DIR).mkdir(exist_ok=True)
    for path, data in absent:
        temporary = path.with_name(f"{path.name}.tmp")
        with temporary.open("wb") as file:
            file.write(data)
            file.flush()
            os.fsync(file.fileno())
        os.replace(temporary, path)
    with (root / EVENTS_FILE).open("ab") as journal:
        journal.write(line + b"\n")
        journal.flush()
        os.fsync(journal.fileno())


# ---------------------------------------------------------------------------
# Lecture des documents
# ---------------------------------------------------------------------------


def _result(log: RegistryLog, number: int) -> Result:
    result = log.event(number).result
    if result is None:
        raise RegistryError(f"l'événement {number} n'est pas un résultat")
    return result


def load_outcomes(
    root: Path, log: RegistryLog, number: int
) -> tuple[OutingOutcome, ...]:
    """Les sorties scorées du résultat ``number``, reconstruites depuis ses documents,
    présents, intacts et décodés."""
    result = _result(log, number)

    def read(sha: str) -> bytes:
        return _stored(root, sha)

    return tuple(
        OutingOutcome(
            scored.outing_id,
            scored.coverage,
            tuple(_model_scores(scored, read, _line_prefix(number), "")),
        )
        for scored in result.outings
    )


def load_references(
    root: Path, log: RegistryLog, number: int
) -> tuple[tuple[str, RepeatabilityReference], ...]:
    """Les références D8 du résultat ``number`` : couples (parcours, référence)."""
    result = _result(log, number)
    return tuple(
        (
            record.route_id,
            _decoded(
                lambda sha: _stored(root, sha),
                record.reference,
                RepeatabilityReference,
                "",
            ),
        )
        for record in result.references
    )


# ---------------------------------------------------------------------------
# Comptage des essais et aides
# ---------------------------------------------------------------------------


def count_trials(log: RegistryLog) -> TrialCounts:
    """Le comptage des essais (``0010`` D14 ; décision 4 de rdw) : chaque DÉCLARATION
    compte, corrections comprises ; les exécutions sans effet à part ; les autres par
    couple effet × cible, ordonnés par effet puis par rang de la cible."""
    declarations = [
        event.declaration for event in log.events if event.declaration is not None
    ]
    corrections = sum(
        event.corrects is not None
        for event in log.events
        if event.kind is EventKind.DECLARATION
    )
    by_pair: Counter[tuple[str, ExperimentMetric]] = Counter()
    for declaration in declarations:
        experiment = declaration.experiment
        if experiment is not None:
            by_pair[(experiment.effect.name, experiment.target)] += 1
    rank = {metric: i for i, metric in enumerate(ExperimentMetric)}
    ordered = sorted(by_pair.items(), key=lambda item: (item[0][0], rank[item[0][1]]))
    return TrialCounts(
        declarations=len(declarations),
        corrections=corrections,
        without_effect=len(declarations) - sum(by_pair.values()),
        by_experiment=tuple(
            ExperimentTrials(effect, target, count)
            for (effect, target), count in ordered
        ),
    )


def declared_performance(performance: Performance) -> DeclaredPerformance:
    """La performance déclarée et son origine ``o_j`` (``0010`` D2.5) : 00:00 à Paris
    du jour civil ``J − 7``."""
    return DeclaredPerformance(performance, origin(performance.civil_date))


def curve_artifacts(
    curve_path: Path, read: CurveReadResult, *, retrieved_at: datetime | None = None
) -> tuple[ArtifactRef, ArtifactRef]:
    """Les deux fichiers de la courbe que déclare une exécution (``0010`` D2.6 ;
    décision 2) : le CSV lu et son compagnon ``.meta.json``, disponibles à l'instant
    d'estimation de la provenance (``generated_at``), entrées de prévision.

    Précondition : ``read`` est la lecture de ``curve_path`` (``ValueError`` sinon).
    Le compagnon est haché ici, lu à ``retrieved_at`` (maintenant par défaut).
    """
    if read.source.identifier != curve_path.name:
        raise ValueError(
            f"curve_artifacts : la lecture est celle de « {read.source.identifier} », "
            f"pas de « {curve_path.name} »"
        )
    available_at = read.curve.estimation.generated_at
    meta_path = curve_path.with_name(f"{curve_path.stem}{META_SUFFIX}")
    meta = SourceRef(
        CURVE_METADATA_KIND,
        meta_path.name,
        content_hash(meta_path.read_bytes()),
        datetime.now(UTC) if retrieved_at is None else retrieved_at,
    )
    return (
        ArtifactRef(read.source, available_at, ArtifactRole.FORECAST_INPUT),
        ArtifactRef(meta, available_at, ArtifactRole.FORECAST_INPUT),
    )
