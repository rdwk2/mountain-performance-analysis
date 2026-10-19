"""Le registre des expériences sur disque : journal, documents, ajout, relecture,
comptage des essais (M4b-4).

Protocole : ``docs/decisions/0010`` D14 (et ses précisions de M4b-4), D0, D2.5, D2.6.
Un dossier, donné par l'appelant :

- ``evenements.jsonl`` : le journal, une ligne par événement, son écriture canonique
  suivie de ``\\n`` ; chaque ligne porte l'empreinte de la précédente ;
- ``documents/<sha256>.json`` : observations, scores avec leurs prévisions, références
  D8, documents d'admission (M4c-3), de fourchettes (M4d-2) et de sensibilité (M4d-3),
  chacun nommé par l'empreinte de ses octets ;
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
from dataclasses import dataclass, replace
from datetime import UTC, date, datetime
from pathlib import Path

from mountain_perf.backtest.calendar import origin
from mountain_perf.backtest.codec import (
    DOCUMENT_FIRST_FORMAT,
    CodecError,
    canonical_bytes,
    content_hash,
    decode_contract,
    decode_document,
    encode_contract,
    encode_document,
)
from mountain_perf.backtest.sensitivity import (
    SENSITIVITY_CENTRAL_M,
    SENSITIVITY_CLUSTER_RADIUS_M,
    SENSITIVITY_CONFIGURATIONS,
)
from mountain_perf.model.curve_io import META_SUFFIX, CurveReadResult
from mountain_perf.schemas import (
    ADMISSION_FIRST_FORMAT,
    BAND_MODELS,
    BANDS_FIRST_FORMAT,
    CALIBRATED_KINDS,
    CLOCKS,
    REGISTRY_FORMAT_VERSION,
    SENSITIVITY_FIRST_FORMAT,
    Admission,
    ArtifactRef,
    ArtifactRole,
    CalibratedOutingScores,
    CalibratedScenarioScores,
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
    OutingBands,
    OutingObservation,
    OutingOutcome,
    OutingResult,
    OutingScores,
    PairResult,
    Performance,
    RegistryEvent,
    RegistryLog,
    RepeatabilityRecord,
    RepeatabilityReference,
    Result,
    Scenario,
    ScenarioScores,
    SensitivityConfiguration,
    SensitivityOutcome,
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
    """La ligne d'un événement : son écriture canonique, sans fin de ligne, **à son
    format** — avant le format 3, sans la clé ``admission`` du RÉSULTAT ni la clé
    ``reference_documents`` de l'expérience, qui y valent ``null`` (précision de D14,
    M4c-3) ; avant le format 4, sans la clé ``bands`` des sorties du RÉSULTAT, qui y
    vaut ``null`` (précision de D14, M4d-2) ; avant le format 5, sans les clés
    ``sensitivity`` de la DÉCLARATION, ``pairs`` et ``sensitivity`` du RÉSULTAT, qui y
    valent ``null`` et ``[]`` (précision de D14, M4d-3) : chaque ligne ancienne se
    réécrit à l'octet."""
    data = encode_contract(event)
    if event.format_version < SENSITIVITY_FIRST_FORMAT and isinstance(data, dict):
        declaration = data.get("declaration")
        if isinstance(declaration, dict):
            declaration.pop("sensitivity", None)
        result = data.get("result")
        if isinstance(result, dict):
            result.pop("pairs", None)
            result.pop("sensitivity", None)
    if event.format_version < BANDS_FIRST_FORMAT and isinstance(data, dict):
        result = data.get("result")
        if isinstance(result, dict):
            for outing in result.get("outings", ()):
                if isinstance(outing, dict):
                    outing.pop("bands", None)
    if event.format_version < ADMISSION_FIRST_FORMAT and isinstance(data, dict):
        result = data.get("result")
        if isinstance(result, dict):
            result.pop("admission", None)
        declaration = data.get("declaration")
        if isinstance(declaration, dict):
            experiment = declaration.get("experiment")
            if isinstance(experiment, dict):
                experiment.pop("reference_documents", None)
    return canonical_bytes(data)


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
        if event.declaration is not None and event.declaration.sensitivity is not None:
            _agree_sensitivity(log, event, _line_prefix(event.number))
        if event.result is not None:
            _agree(
                _declaration_of(log, event),
                event.result,
                _line_prefix(event.number),
                event.format_version,
            )
            _agree_central_pair(log, event, _line_prefix(event.number))
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
            event = decode_contract(RegistryEvent, _upgraded(raw))
        except (CodecError, ContractError) as error:
            raise RegistryError(f"{prefix}{error}") from error
        if _line(event) != line:
            raise RegistryError(f"{prefix}écriture non canonique")
        declared = event.declaration
        if (
            event.format_version >= ADMISSION_FIRST_FORMAT
            and declared is not None
            and declared.experiment is not None
            and declared.experiment.reference_documents is None
        ):
            raise RegistryError(
                f"{prefix}une expérience du format {event.format_version} fige les "
                "documents D8 de ses références (E6)"
            )
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


def _upgraded(raw: object) -> object:
    """Une ligne JSON d'un format antérieur, avant son décodage : avant le format 5, sa
    DÉCLARATION reçoit ``"sensitivity": null``, son RÉSULTAT ``"pairs": []`` et
    ``"sensitivity": null`` (précision de D14, M4d-3) ; avant le format 4,
    chaque sortie de son RÉSULTAT reçoit ``"bands": null`` (précision de D14, M4d-2) ;
    avant le format 3, son RÉSULTAT reçoit aussi ``"admission": null``, l'expérience de
    sa DÉCLARATION ``"reference_documents": null`` (précision de D14, M4c-3). Une ligne
    qui porte déjà l'une de ces clés, même ``null``, est refusée : champ inconnu à son
    format. Une ligne du format 4, ou non lisible (pas un dictionnaire, version
    absente), passe telle quelle : le décodage la juge."""
    if not isinstance(raw, dict):
        return raw
    version = raw.get("format_version")
    if type(version) is not int or version >= SENSITIVITY_FIRST_FORMAT:
        return raw
    declaration = raw.get("declaration")
    if isinstance(declaration, dict):
        if "sensitivity" in declaration:
            raise CodecError(
                f"declaration : champ inconnu au format {version} : 'sensitivity'"
            )
        raw = {**raw, "declaration": {**declaration, "sensitivity": None}}
    result = raw.get("result")
    if isinstance(result, dict):
        for key in ("pairs", "sensitivity"):
            if key in result:
                raise CodecError(
                    f"result : champ inconnu au format {version} : {key!r}"
                )
        raw = {**raw, "result": {**result, "pairs": [], "sensitivity": None}}
    if version >= BANDS_FIRST_FORMAT:
        return raw
    result = raw.get("result")
    if isinstance(result, dict) and isinstance(result.get("outings"), list):
        outings: list[object] = []
        for outing in result["outings"]:
            if isinstance(outing, dict):
                if "bands" in outing:
                    raise CodecError(
                        f"result.outings : champ inconnu au format {version} : 'bands'"
                    )
                outing = {**outing, "bands": None}
            outings.append(outing)
        raw = {**raw, "result": {**result, "outings": outings}}
    if version >= ADMISSION_FIRST_FORMAT:
        return raw
    result = raw.get("result")
    if isinstance(result, dict):
        if "admission" in result:
            raise CodecError(
                f"result : champ inconnu au format {version} : 'admission'"
            )
        raw = {**raw, "result": {**result, "admission": None}}
    declaration = raw.get("declaration")
    if isinstance(declaration, dict):
        experiment = declaration.get("experiment")
        if isinstance(experiment, dict):
            if "reference_documents" in experiment:
                raise CodecError(
                    f"experiment : champ inconnu au format {version} : "
                    "'reference_documents'"
                )
            experiment = {**experiment, "reference_documents": None}
            raw = {**raw, "declaration": {**declaration, "experiment": experiment}}
    return raw


def _declaration_of(log: RegistryLog, event: RegistryEvent) -> Declaration:
    """La déclaration à laquelle répond ``event``."""
    assert event.answers is not None  # contrat de RegistryEvent
    declaration = log.event(event.answers).declaration
    assert declaration is not None  # contrat de RegistryLog
    return declaration


def _cited(result: Result) -> list[str]:
    """Les documents d'un résultat, dans l'ordre : par sortie, l'observation puis, par
    modèle, le contrôle et l'usage, puis ses fourchettes (M4d-2) ; puis les références ;
    le document d'admission en dernier (M4c-3). Pour une sensibilité (M4d-3), de même
    paire par paire, puis le document de sensibilité."""
    cited: list[str] = []
    for outings, references in (
        (result.outings, result.references),
        *((pair.outings, pair.references) for pair in result.pairs),
    ):
        for outing in outings:
            cited.append(outing.observation)
            for model in outing.models:
                cited.append(model.control)
                if model.usage is not None:
                    cited.append(model.usage)
            if outing.bands is not None:
                cited.append(outing.bands)
        cited.extend(record.reference for record in references)
    if result.admission is not None:
        cited.append(result.admission)
    if result.sensitivity is not None:
        cited.append(result.sensitivity)
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
    chaque document cité décodé **au format de l'événement qui le cite** (précision
    de D14, M4c-2), ses scores reconstruits, ses prévisions recoupées avec la
    déclaration, ses références D8 avec les jours de répétabilité, son document
    d'admission avec l'expérience déclarée (M4c-3)."""
    log = read_registry(root)
    for event in log.events:
        if event.result is not None:
            _agree_documents(
                _declaration_of(log, event),
                event.result,
                lambda sha: _stored(root, sha),
                _line_prefix(event.number),
                "",
                event.format_version,
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


def _agree(
    declaration: Declaration, result: Result, prefix: str, format_version: int
) -> None:
    """L'accord sans documents (``0010`` D0, D3, D14) : chaque sortie du résultat est
    déclarée ; chaque sortie déclarée a un sort ; une sortie scorée est tracée, ses
    modèles sont déclarés, son usage existe si et seulement si elle a une référence,
    et elle l'est par **chaque modèle déclaré**, statut « non calé » ou « erreur du
    modèle » compris (D0, D9.2 ; précision de D14, M4c-2 : toute ligne, de tout
    format) ; les parcours des références D8 sont déclarés. Puis (M4c-3) : un
    document d'admission est cité si et seulement si la déclaration porte une
    expérience ; une expérience déclarée avant le format 3 (sans documents D8 figés)
    ne reçoit pas de RÉSULTAT ; chaque document D8 figé est celui que le RÉSULTAT
    publie pour ce parcours (E6). Enfin (M4d-2), au format 4, une sortie scorée cite
    ses fourchettes si et seulement si elle a une référence, que la déclaration déclare
    les cinq modèles du rapport (``BAND_MODELS``) et qu'elle ne porte pas
    d'expérience. Pour une DÉCLARATION de sensibilité (M4d-3) : le RÉSULTAT porte
    une paire par paire déclarée, dans l'ordre, chacune accordée comme le RÉSULTAT
    d'une exécution, et un document de sensibilité ; il ne cite pas de document
    d'admission (les admissions des configurations sont dans le document de
    sensibilité)."""
    sensitivity = declaration.sensitivity
    if sensitivity is None:
        if result.sensitivity is not None:
            raise RegistryError(
                f"{prefix}un RÉSULTAT de sensibilité répond à une DÉCLARATION de "
                "sensibilité (M4d-3)"
            )
        _agree_outings(declaration, result, prefix, format_version)
        _agree_admission(declaration, result, prefix)
        return
    if result.sensitivity is None:
        raise RegistryError(
            f"{prefix}une DÉCLARATION de sensibilité reçoit un RÉSULTAT de sensibilité "
            "(M4d-3)"
        )
    declared = [(p.score_step_m, p.lateral_tolerance_m) for p in sensitivity.pairs]
    present = [(p.score_step_m, p.lateral_tolerance_m) for p in result.pairs]
    if present != declared:
        raise RegistryError(
            f"{prefix}le RÉSULTAT de sensibilité porte les paires déclarées, dans "
            f"l'ordre : {declared} attendu, reçu {present}"
        )
    for pair in result.pairs:
        _agree_outings(
            declaration, _pair_view(pair), _pair_prefix(prefix, pair), format_version
        )


def _pair_view(pair: PairResult) -> Result:
    """Une paire d'un RÉSULTAT de sensibilité vue comme le RÉSULTAT d'une exécution
    (M4d-3) : ses sorties, ses sorties non scorées, ses références D8."""
    return Result(pair.outings, pair.unscored, pair.references)


def _pair_prefix(prefix: str, pair: PairResult) -> str:
    return f"{prefix}paire ({pair.score_step_m:g}, {pair.lateral_tolerance_m:g}), "


def _agree_outings(
    declaration: Declaration, result: Result, prefix: str, format_version: int
) -> None:
    """La partie de ``_agree`` qui porte sur les sorties et les références D8 d'un
    résultat d'exécution (ou d'une paire d'une sensibilité, M4d-3)."""
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
        present = {model.model for model in scored.models}
        absent = [
            model.kind for model in declaration.models if model.kind not in present
        ]
        if absent:
            raise RegistryError(
                f"{prefix}{scored.outing_id!r}, une sortie scorée l'est par chaque "
                f"modèle déclaré (D0, D9.2) ; absent : {', '.join(absent)}"
            )
    route_ids = declaration.route_ids
    for record in result.references:
        if record.route_id not in route_ids:
            raise RegistryError(f"{prefix}parcours non déclaré, {record.route_id!r}")
    if format_version >= BANDS_FIRST_FORMAT:
        _agree_bands(declaration, result, outings, prefix)


def _agree_admission(declaration: Declaration, result: Result, prefix: str) -> None:
    """La partie de ``_agree`` qui porte sur le document d'admission (M4c-3)."""
    experiment = declaration.experiment
    if (result.admission is not None) != (experiment is not None):
        raise RegistryError(
            f"{prefix}un RÉSULTAT cite un document d'admission si et seulement si sa "
            "déclaration porte une expérience (M4c-3)"
        )
    if experiment is None:
        return
    if experiment.reference_documents is None:
        raise RegistryError(
            f"{prefix}une expérience déclarée avant le format 3 ne reçoit pas de "
            "RÉSULTAT (ses documents D8 ne sont pas figés, E6)"
        )
    published = {record.route_id: record.reference for record in result.references}
    for frozen in experiment.reference_documents:
        if published.get(frozen.route_id) != frozen.reference:
            raise RegistryError(
                f"{prefix}le document D8 de {frozen.route_id!r} n'est pas celui que "
                "la déclaration a figé (E6)"
            )


def _agree_sensitivity(
    log: RegistryLog, event: RegistryEvent, prefix: str, *, appending: bool = False
) -> None:
    """L'accord d'une DÉCLARATION de sensibilité avec la centrale qu'elle qualifie
    (précision et exception de D14, M4d-3), dans cet ordre : les empreintes des lignes
    de la centrale et de son RÉSULTAT ; la déclaration recopie la centrale, champ pour
    champ, hors ``sensitivity`` ; ses configurations sont les dix-neuf de D13, dans leur
    ordre ; à l'ajout seulement (``appending``), la centrale et son RÉSULTAT sont en
    vigueur. Les liens (types, ordre) sont ceux de ``RegistryLog``."""
    declaration = event.declaration
    assert declaration is not None  # appelant
    sensitivity = declaration.sensitivity
    assert sensitivity is not None  # appelant
    central = log.event(sensitivity.central)
    answer = log.event(sensitivity.answer)
    for named, expected, what in (
        (central, sensitivity.central_hash, "de la DÉCLARATION centrale"),
        (answer, sensitivity.answer_hash, "du RÉSULTAT central"),
    ):
        if line_hash(named) != expected:
            raise RegistryError(
                f"{prefix}l'empreinte déclarée de la ligne {what} "
                f"({named.number}) ne correspond pas"
            )
    if replace(declaration, sensitivity=None) != central.declaration:
        raise RegistryError(
            f"{prefix}une DÉCLARATION de sensibilité recopie la déclaration centrale, "
            "hors de la grille ; une autre modification est une expérience neuve "
            "(exception de D14, M4d-3)"
        )
    if sensitivity.configurations != SENSITIVITY_CONFIGURATIONS:
        raise RegistryError(
            f"{prefix}une DÉCLARATION de sensibilité déclare les dix-neuf "
            "configurations de D13, toutes, dans leur ordre (M4d-3)"
        )
    central_pair = (
        *SENSITIVITY_CENTRAL_M,
        SENSITIVITY_CLUSTER_RADIUS_M,
    )
    declared_pair = tuple(
        declaration.matching[name]
        for name in ("score_step_m", "lateral_tolerance_m", "cluster_radius_m")
    )
    if declared_pair != central_pair:
        raise RegistryError(
            f"{prefix}la centrale d'une sensibilité est appariée à (250, 30), r_c "
            "15 m : son comparateur est une des dix-neuf configurations (M4d-3)"
        )
    experiment = declaration.experiment
    if experiment is not None and sensitivity.frozen is not None:
        comparator = comparator_configuration(declaration)
        (entry,) = [e for e in sensitivity.frozen if e.configuration == comparator]
        if entry.frozen_references != experiment.frozen_references:
            raise RegistryError(
                f"{prefix}les références figées du comparateur sont celles de "
                "l'expérience centrale, dont l'admission est la décision du "
                "comparateur (M4d-3)"
            )
    if not appending:
        return
    if not log.in_force(sensitivity.central):
        raise RegistryError(
            f"{_REFUSED}la DÉCLARATION centrale {sensitivity.central} est corrigée"
        )
    in_force = log.answer(sensitivity.central)
    if in_force is None or in_force.number != sensitivity.answer:
        raise RegistryError(
            f"{_REFUSED}le RÉSULTAT {sensitivity.answer} n'est pas la réponse en "
            f"vigueur de la DÉCLARATION centrale {sensitivity.central}"
        )


def _agree_central_pair(log: RegistryLog, event: RegistryEvent, prefix: str) -> None:
    """La paire ``(250, 30)`` d'un RÉSULTAT de sensibilité est le RÉSULTAT central
    (précision de D14, M4d-3) : mêmes sorties scorées (mêmes documents), mêmes sorties
    non scorées, mêmes références D8 — rien n'y est recalculé ni réécrit."""
    result = event.result
    assert result is not None  # appelant
    declaration = _declaration_of(log, event)
    sensitivity = declaration.sensitivity
    if sensitivity is None:
        return
    central = log.event(sensitivity.answer).result
    assert central is not None  # liens : la réponse centrale est un RÉSULTAT
    for pair in result.pairs:
        if (pair.score_step_m, pair.lateral_tolerance_m) != SENSITIVITY_CENTRAL_M:
            continue
        if (pair.outings, pair.unscored, pair.references) != (
            central.outings,
            central.unscored,
            central.references,
        ):
            raise RegistryError(
                f"{_pair_prefix(prefix, pair)}la paire de la centrale est son RÉSULTAT "
                f"({sensitivity.answer}) : mêmes sorties, mêmes documents, mêmes "
                "références D8 (M4d-3)"
            )


def comparator_configuration(declaration: Declaration) -> SensitivityConfiguration:
    """Le comparateur d'une sensibilité (précision de D13, M4d-3) : ``(250, 30)`` sous
    l'écoulé pour ``just backtest``, sous l'horloge déclarée pour une expérience."""
    clock = (
        CLOCKS[0] if declaration.experiment is None else declaration.experiment.clock
    )
    return SensitivityConfiguration(
        *SENSITIVITY_CENTRAL_M, SENSITIVITY_CLUSTER_RADIUS_M, clock
    )


def _agree_bands(
    declaration: Declaration,
    result: Result,
    outings: Mapping[str, Outing],
    prefix: str,
) -> None:
    """Au format 4 (précision de D14, M4d-2) : une sortie scorée cite ses fourchettes si
    et seulement si elle a une référence, que la déclaration déclare les cinq modèles
    du rapport (``BAND_MODELS``) et qu'elle ne porte pas d'expérience."""
    kinds = {model.kind for model in declaration.models}
    expected = declaration.experiment is None and set(BAND_MODELS) <= kinds
    for scored in result.outings:
        wanted = expected and outings[scored.outing_id].reference is not None
        if (scored.bands is not None) != wanted:
            raise RegistryError(
                f"{prefix}{scored.outing_id!r}, une sortie scorée cite ses "
                "fourchettes si et seulement si elle a une référence, que les cinq "
                "modèles du rapport sont déclarés et qu'il n'y a pas d'expérience "
                "(M4d-2)"
            )


def _decoded[T](
    read: Callable[[str], bytes],
    sha: str,
    expected: type[T],
    prefix: str,
    format_version: int,
) -> T:
    """Le document ``sha`` décodé au format ``format_version``, celui de l'événement
    qui le cite (précision de D14, M4c-2) ; ses erreurs, préfixées de son nom."""
    try:
        return decode_document(read(sha), expected, format_version)
    except (CodecError, ContractError) as error:
        raise RegistryError(f"{prefix}{_document_name(sha)} : {error}") from error


def _model_scores(
    scored: OutingResult,
    read: Callable[[str], bytes],
    prefix: str,
    document_prefix: str,
    format_version: int,
) -> Iterator[tuple[ModelKind, OutingScores | CalibratedOutingScores]]:
    """Les scores de chaque modèle d'une sortie scorée, reconstruits depuis ses
    documents au format ``format_version`` : l'observation, puis, modèle par modèle,
    le contrôle et l'usage — en ``CalibratedScenarioScores`` puis
    ``CalibratedOutingScores`` pour un modèle calé (``CALIBRATED_KINDS``, le
    candidat compris depuis M4c-3), de ce modèle ; en ``ScenarioScores`` puis
    ``OutingScores`` pour v0 brut.

    Un candidat n'existe qu'à partir du format 3 : une ligne antérieure qui en porte un
    est refusée, avant tout décodage de ses scores (précision de D14, M4c-3). Au
    format 1, aucun modèle n'était calé : une ligne d'un format antérieur au document
    calé (``DOCUMENT_FIRST_FORMAT``) qui en porte un est refusée, avant tout décodage
    de ses scores (précision de D14, M4c-2)."""
    observation = _decoded(
        read, scored.observation, OutingObservation, document_prefix, format_version
    )
    for model in scored.models:
        if (
            model.model is ModelKind.CANDIDATE
            and format_version < ADMISSION_FIRST_FORMAT
        ):
            raise RegistryError(
                f"{prefix}{scored.outing_id!r}, {model.model} : un candidat n'existe "
                "qu'à partir du format 3 (M4c-3)"
            )
        if model.model in CALIBRATED_KINDS:
            if format_version < DOCUMENT_FIRST_FORMAT[CalibratedScenarioScores]:
                raise RegistryError(
                    f"{prefix}{scored.outing_id!r}, {model.model} : un modèle calé "
                    f"n'a pas de scores au format {format_version}, une ligne du "
                    f"format {format_version} ne le relit pas (précision de D14, "
                    "M4c-2)"
                )
            yield (
                model.model,
                _calibrated_scores(
                    scored,
                    model,
                    observation,
                    read,
                    prefix,
                    document_prefix,
                    format_version,
                ),
            )
            continue
        control = _decoded(
            read, model.control, ScenarioScores, document_prefix, format_version
        )
        usage = (
            None
            if model.usage is None
            else _decoded(
                read, model.usage, ScenarioScores, document_prefix, format_version
            )
        )
        try:
            scores = OutingScores(observation, control, usage)
        except ContractError as error:
            raise RegistryError(f"{prefix}{scored.outing_id!r}, {error}") from error
        yield model.model, scores


def _calibrated_scores(
    scored: OutingResult,
    model: ModelResult,
    observation: OutingObservation,
    read: Callable[[str], bytes],
    prefix: str,
    document_prefix: str,
    format_version: int,
) -> CalibratedOutingScores:
    """Les scores calés d'un modèle calé sur une sortie scorée (M4c-2) : son contrôle
    et son usage décodés en ``CalibratedScenarioScores``, puis
    ``CalibratedOutingScores``, qui doit porter ce modèle."""
    control = _decoded(
        read, model.control, CalibratedScenarioScores, document_prefix, format_version
    )
    usage = (
        None
        if model.usage is None
        else _decoded(
            read,
            model.usage,
            CalibratedScenarioScores,
            document_prefix,
            format_version,
        )
    )
    try:
        scores = CalibratedOutingScores(scored.outing_id, observation, control, usage)
        if control.model is not model.model:
            raise ContractError(
                f"les scores calés portent le modèle {control.model}, {model.model} "
                "attendu"
            )
    except ContractError as error:
        raise RegistryError(f"{prefix}{scored.outing_id!r}, {error}") from error
    return scores


def _agree_documents(
    declaration: Declaration,
    result: Result,
    read: Callable[[str], bytes],
    prefix: str,
    document_prefix: str,
    format_version: int,
) -> None:
    """L'accord par les documents (``0010`` D14, D2.6), chaque document relu au format
    ``format_version`` de l'événement qui le cite (précision de D14, M4c-2), dans cet
    ordre : les scores de chaque sortie se reconstruisent, leurs prévisions recopient
    la déclaration de leur modèle et nomment un fichier déclaré de leur sortie, puis ses
    fourchettes s'accordent à la déclaration et aux calages de la sortie
    (``_check_bands``, M4d-2) ; pour
    chaque référence D8, ses jours sont exactement ceux du jeu de répétabilité sur son
    parcours, puis son fichier est recoupé avec la référence déclarée des sorties de
    répétabilité de ce parcours (précision de D14, M4b-5) ; puis le document
    d'admission, décodé au même format, porte la cible et l'horloge de l'expérience
    déclarée (M4c-3) ; en dernier, chaque parcours du jeu de répétabilité a sa
    référence D8 (précision de D14, M4c-2). Pour un RÉSULTAT de sensibilité (M4d-3) :
    paire par paire, les mêmes contrôles des sorties et des références, puis les
    références D8 de chaque paire sont celles que la déclaration a figées ; enfin le
    document de sensibilité (``_check_sensitivity``)."""
    sensitivity = declaration.sensitivity
    if sensitivity is None:
        _agree_outing_documents(
            declaration, result, read, prefix, document_prefix, format_version
        )
        _agree_admission_document(
            declaration, result, read, prefix, document_prefix, format_version
        )
        _agree_reference_routes(declaration, result, prefix)
        return
    for pair, frozen in zip(result.pairs, sensitivity.pairs, strict=True):
        where = _pair_prefix(prefix, pair)
        view = _pair_view(pair)
        _agree_outing_documents(
            declaration, view, read, where, document_prefix, format_version
        )
        _agree_reference_routes(declaration, view, where)
        if pair.references != frozen.references:
            raise RegistryError(
                f"{where}les références D8 publiées ne sont pas celles que la "
                "DÉCLARATION de sensibilité a figées"
            )
    assert result.sensitivity is not None  # _agree
    outcome = _decoded(
        read, result.sensitivity, SensitivityOutcome, document_prefix, format_version
    )
    _check_sensitivity(declaration, outcome, prefix)


def _check_sensitivity(
    declaration: Declaration, outcome: SensitivityOutcome, prefix: str
) -> None:
    """Le document de sensibilité (précision de D14, M4d-3), décodé au format de
    l'événement : ses configurations sont celles de la déclaration ; son comparateur
    est ``comparator_configuration`` ; il porte une expérience si et seulement si la
    déclaration en porte une ; ses performances sont celles de la déclaration (jours et
    premières sorties) ; l'admission de chaque configuration porte la cible déclarée."""
    assert declaration.sensitivity is not None  # appelant
    configurations = tuple(c.configuration for c in outcome.configurations)
    if configurations != declaration.sensitivity.configurations:
        raise RegistryError(
            f"{prefix}le document de sensibilité ne porte pas les configurations "
            "déclarées, dans leur ordre"
        )
    expected = comparator_configuration(declaration)
    if configurations[outcome.comparator] != expected:
        raise RegistryError(
            f"{prefix}le comparateur du document de sensibilité n'est pas {expected}"
        )
    experiment = declaration.experiment
    if outcome.experiment != (experiment is not None):
        raise RegistryError(
            f"{prefix}le document de sensibilité porte une expérience si et seulement "
            "si la déclaration en porte une"
        )
    days = [
        (d.performance.civil_date, d.performance.outings[0].outing_id)
        for d in declaration.performances
    ]
    first = outcome.configurations[0]
    if [(p.civil_date, p.outing_id) for p in first.performances] != days:
        raise RegistryError(
            f"{prefix}le document de sensibilité ne porte pas les performances "
            "déclarées"
        )
    if experiment is None:
        return
    for configuration in outcome.configurations:
        admission = configuration.admission
        if admission is not None and admission.target != experiment.target:
            raise RegistryError(
                f"{prefix}l'admission d'une configuration porte une autre cible que "
                "l'expérience déclarée"
            )


def _agree_outing_documents(
    declaration: Declaration,
    result: Result,
    read: Callable[[str], bytes],
    prefix: str,
    document_prefix: str,
    format_version: int,
) -> None:
    """La partie de ``_agree_documents`` qui porte sur les sorties et les références D8
    (d'une exécution, ou d'une paire d'une sensibilité, M4d-3)."""
    outings = _declared_outings(declaration)
    models = {model.kind: model for model in declaration.models}
    for scored in result.outings:
        outing = outings[scored.outing_id]
        calibrated: list[CalibratedOutingScores] = []
        for kind, scores in _model_scores(
            scored, read, prefix, document_prefix, format_version
        ):
            _check_forecasts(declaration, models[kind], outing, scores, prefix)
            if isinstance(scores, CalibratedOutingScores):
                calibrated.append(scores)
        if scored.bands is not None:
            _check_bands(
                declaration,
                scored,
                calibrated,
                read,
                prefix,
                document_prefix,
                format_version,
            )
    for record in result.references:
        reference = _decoded(
            read,
            record.reference,
            RepeatabilityReference,
            document_prefix,
            format_version,
        )
        _check_reference_days(declaration, result, record.route_id, reference, prefix)
        _check_reference_outings(declaration, record.route_id, reference, prefix)


def _agree_reference_routes(
    declaration: Declaration, result: Result, prefix: str
) -> None:
    """La dernière partie de ``_agree_documents`` : chaque parcours du jeu de
    répétabilité a sa référence D8 (précision de D14, M4c-2)."""
    referenced = {record.route_id for record in result.references}
    for route_id in sorted(_repeatability_routes(declaration)):
        if route_id not in referenced:
            raise RegistryError(
                f"{prefix}le parcours de répétabilité {route_id!r} n'a pas de "
                "référence D8"
            )


def _agree_admission_document(
    declaration: Declaration,
    result: Result,
    read: Callable[[str], bytes],
    prefix: str,
    document_prefix: str,
    format_version: int,
) -> None:
    """La partie de ``_agree_documents`` qui porte sur le document d'admission
    (M4c-3)."""
    experiment = declaration.experiment
    if result.admission is not None and experiment is not None:
        admission = _decoded(
            read, result.admission, Admission, document_prefix, format_version
        )
        if (admission.target, admission.clock) != (
            experiment.target,
            experiment.clock,
        ):
            raise RegistryError(
                f"{prefix}l'admission porte une autre cible ou une autre horloge que "
                "l'expérience déclarée"
            )


def _check_bands(
    declaration: Declaration,
    scored: OutingResult,
    calibrated: list[CalibratedOutingScores],
    read: Callable[[str], bytes],
    prefix: str,
    document_prefix: str,
    format_version: int,
) -> None:
    """Les fourchettes d'une sortie scorée (précision de D14, M4d-2), décodées au format
    de l'événement, dans cet ordre : elles portent la sortie ; pour le calage de chaque
    modèle calé de la sortie (en usage, sous l'écoulé), leurs membres sont les jours de
    ``C_j`` qu'il porte (sa population et ses retraits), chacun disponible si et
    seulement s'il est dans la population, au motif de son retrait sinon ; elles disent
    si la performance a plusieurs sorties ; chaque modèle à bornes a autant d'éléments
    que le ``K`` de l'observation. Rien n'est recalculé : les documents se recoupent
    entre eux (le code du calage n'est pas appelé)."""
    assert scored.bands is not None  # appelant
    bands = _decoded(read, scored.bands, OutingBands, document_prefix, format_version)
    name = repr(scored.outing_id)
    if bands.outing_id != scored.outing_id:
        raise RegistryError(
            f"{prefix}{name}, les fourchettes portent la sortie {bands.outing_id!r}"
        )
    days = tuple(member.civil_date for member in bands.members)
    for scores in calibrated:
        assert scores.usage is not None  # une sortie à référence a l'usage (_agree)
        calibration = scores.usage.clocks[0].calibration  # l'écoulé, CLOCKS[0]
        withdrawn = {w.civil_date: w.reason for w in calibration.withdrawals}
        if days != tuple(sorted({*calibration.population, *withdrawn})):
            raise RegistryError(
                f"{prefix}{name}, les membres des fourchettes ne sont pas les jours de "
                f"C_j du calage de {calibration.model} (population et retraits, D2.4)"
            )
        for member in bands.members:
            if member.unavailability != withdrawn.get(member.civil_date):
                raise RegistryError(
                    f"{prefix}{name}, le membre du {member.civil_date.isoformat()} "
                    "des fourchettes n'a pas le statut que lui donne le calage de "
                    f"{calibration.model} (D9.2)"
                )
    performance = next(
        declared.performance
        for declared in declaration.performances
        if any(o.outing_id == scored.outing_id for o in declared.performance.outings)
    )
    if bands.multi_outing != performance.is_multi_outing:
        raise RegistryError(
            f"{prefix}{name}, les fourchettes disent mal si la performance a plusieurs "
            "sorties"
        )
    observation = _decoded(
        read, scored.observation, OutingObservation, document_prefix, format_version
    )
    targets = len(observation.targets)
    for band in bands.models:
        if band.elements and len(band.elements) != targets:
            raise RegistryError(
                f"{prefix}{name}, {band.model} : {len(band.elements)} éléments de "
                f"fourchette pour un K de {targets}"
            )


def _repeatability_routes(declaration: Declaration) -> set[str]:
    """Les parcours du jeu de répétabilité : ceux des sorties déclarées de ce jeu qui
    ont un parcours (``0010`` D8)."""
    return {
        outing.route_id
        for declared in declaration.performances
        for outing in declared.performance.outings
        if outing.dataset is DataSet.REPEATABILITY and outing.route_id
    }


def _check_forecasts(
    declaration: Declaration,
    model: DeclaredModel,
    outing: Outing,
    scores: OutingScores | CalibratedOutingScores,
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
    result: Result,
    route_id: str,
    reference: RepeatabilityReference,
    prefix: str,
) -> None:
    """Les jours d'une référence D8 (``0010`` D8 ; précisions de D14, M4b-5 et
    M4c-2) : d'abord, chacun est un jour déclaré sur ce parcours ; puis ils sont
    **exactement** ceux du jeu de répétabilité sur ce parcours — une performance
    déclarée de plusieurs sorties, dont une de ce jeu sur ce parcours, donne un jour
    multi-sorties ; une performance d'une seule sortie, de ce jeu sur ce parcours, un
    jour si cette sortie est scorée par le résultat. Pour les jours puis les jours
    multi-sorties : chaque jour attendu absent, puis chaque jour présent non
    attendu, dans l'ordre des jours."""
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
    scored = {outing.outing_id for outing in result.outings}
    single: set[date] = set()
    multi: set[date] = set()
    for declared in declaration.performances:
        performance = declared.performance
        if not any(
            outing.dataset is DataSet.REPEATABILITY and outing.route_id == route_id
            for outing in performance.outings
        ):
            continue
        if performance.is_multi_outing:
            multi.add(performance.civil_date)
        elif performance.outings[0].outing_id in scored:
            single.add(performance.civil_date)
    for present, expected, kind in (
        (set(reference.days), single, "jour"),
        (set(reference.multi_outing_days), multi, "jour multi-sorties"),
    ):
        for day in sorted(expected - present):
            raise RegistryError(
                f"{prefix}la référence de {route_id!r} omet le {kind} "
                f"{day.isoformat()} du jeu de répétabilité"
            )
        for day in sorted(present - expected):
            raise RegistryError(
                f"{prefix}la référence de {route_id!r} porte le {kind} "
                f"{day.isoformat()}, qui n'en est pas un du jeu de répétabilité"
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

    Précondition (``ValueError``), avant tout accès au registre : une expérience fige
    les documents D8 de ses références (``reference_documents``, E6 ; M4c-3).
    """
    experiment = declaration.experiment
    if experiment is not None and experiment.reference_documents is None:
        raise ValueError(
            "append_declaration : une expérience fige les documents D8 de ses "
            "références (reference_documents, E6)."
        )
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


@dataclass(frozen=True)
class PairOutcome:
    """Ce qu'une sensibilité a produit pour une paire ``(Δ, ε)`` (M4d-3), en mémoire :
    les sorties scorées, les sorties non scorées et les références D8, comme pour une
    exécution. N'est pas un contrat stocké : ``append_result`` en écrit les
    documents."""

    score_step_m: float
    lateral_tolerance_m: float
    outcomes: tuple[OutingOutcome, ...]
    unscored: tuple[Exclusion, ...]
    references: tuple[tuple[str, RepeatabilityReference], ...]


def append_result(
    root: Path,
    declaration: int,
    outcomes: tuple[OutingOutcome, ...],
    *,
    unscored: tuple[Exclusion, ...] = (),
    references: tuple[tuple[str, RepeatabilityReference], ...] = (),
    admission: Admission | None = None,
    pairs: tuple[PairOutcome, ...] = (),
    sensitivity: SensitivityOutcome | None = None,
    recorded_at: datetime | None = None,
    corrects: int | None = None,
    correction_reason: str | None = None,
) -> RegistryEvent:
    """Ajoute un RÉSULTAT à la déclaration numéro ``declaration`` (``0010`` D14, D0) ;
    rend l'événement écrit.

    Les observations, les scores (prévisions comprises), les fourchettes (format 4,
    M4d-2) et les références D8 sont écrits en documents, cités par empreinte ;
    chaque sortie déclarée est scorée (``outcomes``) ou écartée avec un motif
    (``unscored``). Le document d'admission
    d'une expérience (``admission``) est écrit en dernier et cité par
    ``Result.admission`` (M4c-3). Le RÉSULTAT d'une sensibilité (M4d-3) porte ses
    sorties paire par paire (``pairs``, ``outcomes`` vide) et cite le document de
    sensibilité (``sensitivity``), écrit en dernier. L'accord à l'ajout est celui de la
    vérification, documents compris.
    """
    result, documents = _result_documents(
        outcomes, unscored, references, admission, pairs, sensitivity
    )
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
    admission: Admission | None = None,
    pairs: tuple[PairOutcome, ...] = (),
    sensitivity: SensitivityOutcome | None = None,
) -> tuple[Result, dict[str, bytes]]:
    """Étape 0 de l'ajout d'un résultat, avant tout accès au registre : les documents
    écrits en mémoire, dans l'ordre, chacun une fois — par sortie, ses fourchettes après
    ses modèles (M4d-2) ; le document d'admission en dernier (M4c-3) ; pour une
    sensibilité, les paires dans l'ordre, puis le document de sensibilité (M4d-3) ; le
    ``Result`` qui les cite. Contrats refusés : ``RegistryError``."""
    documents: dict[str, bytes] = {}

    def store(value: object) -> str:
        try:
            data = encode_document(value)
        except CodecError as error:
            raise RegistryError(f"{_REFUSED}{error}") from error
        sha = content_hash(data)
        documents.setdefault(sha, data)
        return sha

    def outing_results(
        values: tuple[OutingOutcome, ...],
    ) -> tuple[OutingResult, ...]:
        outings: list[OutingResult] = []
        for outcome in values:
            observation = store(outcome.scores[0][1].observation)
            models = tuple(
                ModelResult(
                    kind,
                    store(scores.control),
                    None if scores.usage is None else store(scores.usage),
                )
                for kind, scores in outcome.scores
            )
            bands = None if outcome.bands is None else store(outcome.bands)
            outings.append(
                OutingResult(
                    outcome.outing_id, outcome.coverage, observation, models, bands
                )
            )
        return tuple(outings)

    def records(
        values: tuple[tuple[str, RepeatabilityReference], ...],
    ) -> tuple[RepeatabilityRecord, ...]:
        return tuple(
            RepeatabilityRecord(route_id, store(reference))
            for route_id, reference in values
        )

    outings = outing_results(outcomes)
    cited_references = records(references)
    cited = None if admission is None else store(admission)
    try:
        pair_results = tuple(
            PairResult(
                pair.score_step_m,
                pair.lateral_tolerance_m,
                outing_results(pair.outcomes),
                pair.unscored,
                records(pair.references),
            )
            for pair in pairs
        )
        outcome = None if sensitivity is None else store(sensitivity)
        result = Result(
            outings, unscored, cited_references, cited, pair_results, outcome
        )
    except ContractError as error:
        raise RegistryError(f"{_REFUSED}{error}") from error
    return result, documents


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
        if declaration is not None and declaration.sensitivity is not None:
            _agree_sensitivity(extended, event, _REFUSED, appending=True)
        if result is not None:
            declared = _declaration_of(extended, event)
            _agree(declared, result, _REFUSED, REGISTRY_FORMAT_VERSION)
            _agree_central_pair(extended, event, _REFUSED)
            _agree_documents(
                declared,
                result,
                documents.__getitem__,
                _REFUSED,
                _REFUSED,
                REGISTRY_FORMAT_VERSION,
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
    présents, intacts et décodés au format de l'événement ``number`` (précision de
    D14, M4c-2) ; leurs fourchettes, au format 4 (M4d-2)."""
    result = _result(log, number)
    format_version = log.event(number).format_version

    def read(sha: str) -> bytes:
        return _stored(root, sha)

    return tuple(
        OutingOutcome(
            scored.outing_id,
            scored.coverage,
            tuple(
                _model_scores(scored, read, _line_prefix(number), "", format_version)
            ),
            None
            if scored.bands is None
            else _decoded(read, scored.bands, OutingBands, "", format_version),
        )
        for scored in result.outings
    )


def load_pair_outcomes(
    root: Path, log: RegistryLog, number: int
) -> tuple[PairOutcome, ...]:
    """Les paires du RÉSULTAT de sensibilité ``number`` (M4d-3) : pour chacune, ses
    sorties scorées et ses références D8 reconstruites depuis leurs documents, au format
    de l'événement ``number`` ; vide pour un autre RÉSULTAT."""
    result = _result(log, number)
    format_version = log.event(number).format_version

    def read(sha: str) -> bytes:
        return _stored(root, sha)

    pairs: list[PairOutcome] = []
    for pair in result.pairs:
        prefix = _pair_prefix(_line_prefix(number), pair)
        outcomes = tuple(
            OutingOutcome(
                scored.outing_id,
                scored.coverage,
                tuple(_model_scores(scored, read, prefix, "", format_version)),
                None
                if scored.bands is None
                else _decoded(read, scored.bands, OutingBands, "", format_version),
            )
            for scored in pair.outings
        )
        references = tuple(
            (
                record.route_id,
                _decoded(
                    read, record.reference, RepeatabilityReference, "", format_version
                ),
            )
            for record in pair.references
        )
        pairs.append(
            PairOutcome(
                pair.score_step_m,
                pair.lateral_tolerance_m,
                outcomes,
                pair.unscored,
                references,
            )
        )
    return tuple(pairs)


def load_sensitivity(
    root: Path, log: RegistryLog, number: int
) -> SensitivityOutcome | None:
    """Le document de sensibilité du RÉSULTAT ``number`` (M4d-3), au format de
    l'événement ; ``None`` pour un autre RÉSULTAT."""
    result = _result(log, number)
    if result.sensitivity is None:
        return None
    return _decoded(
        lambda sha: _stored(root, sha),
        result.sensitivity,
        SensitivityOutcome,
        "",
        log.event(number).format_version,
    )


def load_references(
    root: Path, log: RegistryLog, number: int
) -> tuple[tuple[str, RepeatabilityReference], ...]:
    """Les références D8 du résultat ``number`` : couples (parcours, référence), au
    format de l'événement ``number`` (précision de D14, M4c-2)."""
    result = _result(log, number)
    format_version = log.event(number).format_version
    return tuple(
        (
            record.route_id,
            _decoded(
                lambda sha: _stored(root, sha),
                record.reference,
                RepeatabilityReference,
                "",
                format_version,
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
    couple effet × cible, ordonnés par effet puis par rang de la cible ; les
    DÉCLARATIONS de sensibilité à part, hors des essais (exception de D14, M4d-3)."""
    everything = [
        event.declaration for event in log.events if event.declaration is not None
    ]
    sensitivities = sum(d.sensitivity is not None for d in everything)
    declarations = [d for d in everything if d.sensitivity is None]
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
        declarations=len(everything),
        corrections=corrections,
        without_effect=len(declarations) - sum(by_pair.values()),
        by_experiment=tuple(
            ExperimentTrials(effect, target, count)
            for (effect, target), count in ordered
        ),
        sensitivities=sensitivities,
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
