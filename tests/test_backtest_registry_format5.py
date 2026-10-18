"""Le registre au format 5 (brief M4d-3 ; ``0010`` D14 et sa précision et son exception
de M4d-3, D13) : la DÉCLARATION de sensibilité, son RÉSULTAT paire par paire, le
document de sensibilité.

- les versions, et le premier format du document : ``SensitivityOutcome`` au format 5,
  ni écrit ni relu avant ;
- un registre des formats 1 à 4 — construit par le code du jour, puis récrit à son
  format par ``_to_format`` de ``test_backtest_registry_format2.py`` — relu, vérifié
  (ses lignes sans les champs neufs, réécrites à l'octet), et suivi d'une centrale et
  de sa sensibilité au format 5 ; une ligne d'un format antérieur qui porte
  ``sensitivity`` ou ``pairs`` (même ``null`` ou vide) refusée ; l'invariant de
  ``RegistryEvent`` ;
- l'accord d'une DÉCLARATION de sensibilité, **à l'ajout et à la relecture** :
  empreintes des lignes de la centrale et de son RÉSULTAT, recopie champ pour champ,
  dix-neuf configurations dans l'ordre, appariement central ``(250, 30)``, ``r_c``
  15 m, références figées du comparateur d'une expérience ; à l'ajout seulement, la
  centrale et sa réponse en vigueur ;
- l'accord d'un RÉSULTAT de sensibilité, à l'ajout et à la relecture : les paires
  déclarées dans l'ordre, chacune accordée comme le RÉSULTAT d'une exécution, ses
  références D8 celles que la DÉCLARATION a figées, la paire ``(250, 30)`` celle du
  RÉSULTAT central, le document de sensibilité (configurations, comparateur,
  expérience oui ou non, performances, cible) ; une DÉCLARATION ordinaire qui reçoit un
  RÉSULTAT de sensibilité, et l'inverse ;
- ``count_trials`` (les sensibilités à part, l'invariant de somme),
  ``load_pair_outcomes`` et ``load_sensitivity``, deux sensibilités d'une même
  centrale.

Les registres sont construits sur les fixtures de ``fixtures.registry`` (une centrale
de v0 brut sur trois sorties, ou l'expérience synthétique de
``test_backtest_registry_format3.py``) : une DÉCLARATION de sensibilité qui la recopie,
et un RÉSULTAT dont chaque paire reprend les sorties de la centrale, avec un document
de sensibilité construit à la main — le registre ne recalcule rien, il n'a pas à
l'être ici. Trois tests prennent les sensibilités du monde
(``fixtures.sensitivity_world``) : le document d'une expérience, l'admission d'une autre
cible, et la relecture de ce que l'exécution a produit. Les journaux récrits à la main
le sont en JSON canonique, la chaîne des empreintes recalculée ; aucune donnée
réelle.
"""

import re
from collections.abc import Callable
from dataclasses import replace
from datetime import timedelta
from pathlib import Path
from typing import Any

import pytest

from fixtures.registry import (
    OUTINGS,
    V0_RAW,
    at,
    declaration,
    outcomes,
    performances,
    references,
    registry_root,
)
from fixtures.sensitivity_world import (
    ExperimentSensitivity,
    backtest_sensitivity,
    copy_registry,
    experiment_sensitivity,
)
from mountain_perf.backtest import (
    DOCUMENT_FIRST_FORMAT,
    DOCUMENT_TYPES,
    EVENTS_FILE,
    MATCHING_PARAMETER_SPECS,
    SENSITIVITY_CONFIGURATIONS,
    SENSITIVITY_PAIRS,
    CodecError,
    Pair,
    PairOutcome,
    RegistryError,
    admission_inputs,
    admit,
    append_declaration,
    append_failure,
    append_result,
    comparator_configuration,
    configuration_outcome,
    content_hash,
    count_trials,
    decode_document,
    encode_document,
    line_hash,
    load_outcomes,
    load_pair_outcomes,
    load_references,
    load_sensitivity,
    pair_matching,
    read_registry,
    reference_documents,
    sensitivity_outcome,
    verify_registry,
)
from mountain_perf.schemas import (
    CLOCKS,
    REGISTRY_FORMAT_VERSION,
    REGISTRY_READABLE_FORMATS,
    SENSITIVITY_FIRST_FORMAT,
    Admission,
    Availability,
    CalibratedOutingScores,
    ConfigurationOutcome,
    ConfigurationReferences,
    ContractError,
    Declaration,
    DeclaredEffect,
    EventKind,
    Exclusion,
    ExperimentMetric,
    ExperimentTrials,
    Failure,
    FailureKind,
    MetricComparison,
    MetricValue,
    ModelKind,
    OutingScores,
    PairReferences,
    PairResult,
    ParameterSet,
    PerformanceComparison,
    PerformanceMotif,
    RegistryEvent,
    RepeatabilityRecord,
    RepeatabilityReference,
    Result,
    SensitivityConfiguration,
    SensitivityDeclaration,
    SensitivityMetric,
    SensitivityOutcome,
    TrialCounts,
)
from test_backtest_registry_format2 import _rewrite, _to_format, _write_events
from test_backtest_registry_format3 import (
    _experiment_outcomes,
    _experiment_registry,
    _journal,
    _lines,
    _store,
)

Q20_ID, Q27_ID, P03_ID = (outing.outing_id for outing in OUTINGS)
CENTRAL_PAIR: Pair = (250.0, 30.0)
ELAPSED_COMPARATOR = SensitivityConfiguration(250.0, 30.0, 15.0, CLOCKS[0])
"""Le comparateur de ``just backtest``, et d'une expérience déclarée sous l'écoulé."""
COMPARATOR = SENSITIVITY_CONFIGURATIONS.index(ELAPSED_COMPARATOR)
"""Son rang parmi les dix-neuf : 4."""

REFUSED = "ajout refusé : "
RECOPY = (
    "une DÉCLARATION de sensibilité recopie la déclaration centrale, hors de la "
    "grille ; une autre modification est une expérience neuve (exception de D14, "
    "M4d-3)"
)
NINETEEN = (
    "une DÉCLARATION de sensibilité déclare les dix-neuf configurations de D13, "
    "toutes, dans leur ordre (M4d-3)"
)
CENTRAL_MATCHING = (
    "la centrale d'une sensibilité est appariée à (250, 30), r_c 15 m : son "
    "comparateur est une des dix-neuf configurations (M4d-3)"
)
FROZEN_COMPARATOR = (
    "les références figées du comparateur sont celles de l'expérience centrale, dont "
    "l'admission est la décision du comparateur (M4d-3)"
)
FROZEN_IFF = (
    "une DÉCLARATION de sensibilité fige les références de chaque configuration si et "
    "seulement si elle porte une expérience (M4d-3)."
)
CENTRAL_PAIR_IS_THE_RESULT = (
    "paire (250, 30), la paire de la centrale est son RÉSULTAT (2) : mêmes sorties, "
    "mêmes documents, mêmes références D8 (M4d-3)"
)
FROZEN_D8 = (
    "paire (100, 15), les références D8 publiées ne sont pas celles que la "
    "DÉCLARATION de sensibilité a figées"
)
EXPERIMENT_IFF = (
    "le document de sensibilité porte une expérience si et seulement si la "
    "déclaration en porte une"
)
CONFIGURATIONS_OF_THE_DOCUMENT = (
    "le document de sensibilité ne porte pas les configurations déclarées, dans leur "
    "ordre"
)
PERFORMANCES_OF_THE_DOCUMENT = (
    "le document de sensibilité ne porte pas les performances déclarées"
)
OTHER_TARGET = (
    "l'admission d'une configuration porte une autre cible que l'expérience déclarée"
)
SENSITIVITY_RESULT_ANSWERS_A_SENSITIVITY = (
    "un RÉSULTAT de sensibilité répond à une DÉCLARATION de sensibilité (M4d-3)"
)
SENSITIVITY_GETS_A_SENSITIVITY_RESULT = (
    "une DÉCLARATION de sensibilité reçoit un RÉSULTAT de sensibilité (M4d-3)"
)


def _line(number: int) -> str:
    """Le préfixe d'une erreur de relecture de la ligne ``number``."""
    return f"{EVENTS_FILE}, ligne {number} : "


# ---------------------------------------------------------------------------
# Aides : la DÉCLARATION de sensibilité, ses paires, son document
# ---------------------------------------------------------------------------


def _records(
    values: tuple[tuple[str, RepeatabilityReference], ...] | None = None,
) -> tuple[RepeatabilityRecord, ...]:
    """Les documents D8 de ``values`` (par défaut ``references()``), tels que
    ``append_result`` les écrit."""
    chosen = references() if values is None else values
    return tuple(
        RepeatabilityRecord(route_id, content_hash(encode_document(reference)))
        for route_id, reference in chosen
    )


def _pairs_of(
    configurations: tuple[SensitivityConfiguration, ...],
) -> tuple[PairReferences, ...]:
    """Une entrée par paire ``(Δ, ε)`` des configurations, dans l'ordre de leur
    première apparition, de documents D8 ceux de ``references()``."""
    pairs: list[Pair] = []
    for configuration in configurations:
        pair = (configuration.score_step_m, configuration.lateral_tolerance_m)
        if pair not in pairs:
            pairs.append(pair)
    return tuple(PairReferences(*pair, _records()) for pair in pairs)


def _frozen(declared: Declaration) -> tuple[ConfigurationReferences, ...] | None:
    """Les références figées d'une expérience sous chaque configuration : celles de
    l'expérience centrale pour le comparateur, aucune pour les autres (le registre ne
    les recalcule pas) ; ``None`` sans expérience."""
    experiment = declared.experiment
    if experiment is None:
        return None
    comparator = comparator_configuration(declared)
    return tuple(
        ConfigurationReferences(
            configuration,
            experiment.frozen_references if configuration == comparator else (),
        )
        for configuration in SENSITIVITY_CONFIGURATIONS
    )


def _sensitivity_of(
    root: Path, central: int = 1, answer: int = 2, **changes: Any
) -> Declaration:
    """La DÉCLARATION de sensibilité de la centrale ``central`` du registre et de son
    RÉSULTAT ``answer`` : la centrale recopiée, les empreintes de leurs lignes, les
    dix-neuf configurations, les documents D8 de ``references()`` pour chaque paire ;
    ``changes`` remplace des champs de la sensibilité."""
    log = read_registry(root)
    declared = log.event(central).declaration
    assert declared is not None
    sensitivity = SensitivityDeclaration(
        central=central,
        central_hash=line_hash(log.event(central)),
        answer=answer,
        answer_hash=line_hash(log.event(answer)),
        configurations=SENSITIVITY_CONFIGURATIONS,
        pairs=_pairs_of(SENSITIVITY_CONFIGURATIONS),
        frozen=_frozen(declared),
    )
    return replace(declared, sensitivity=replace(sensitivity, **changes))


def _pair_outcomes(
    written: tuple[Any, ...] | None = None,
    changed: dict[Pair, PairOutcome] | None = None,
) -> tuple[PairOutcome, ...]:
    """Chaque paire, dans l'ordre : les sorties ``written`` (par défaut
    ``outcomes()``), aucune non scorée, la référence D8 de ``references()`` ; sauf les
    paires de ``changed``."""
    chosen = outcomes() if written is None else written
    given = changed or {}
    return tuple(
        given.get(pair, PairOutcome(*pair, chosen, (), references()))
        for pair in SENSITIVITY_PAIRS
    )


def _metrics(model: ModelKind) -> tuple[MetricComparison, ...]:
    """Les neuf métriques d'un modèle, la même valeur des deux côtés."""
    value = MetricValue(0.125, None, 3)
    return tuple(
        MetricComparison(model, metric, value, value, Availability.BOTH, (), 0.0)
        for metric in SensitivityMetric
    )


def _comparisons(
    declared: Declaration | None = None,
) -> tuple[PerformanceComparison, ...]:
    """Chaque performance de ``declared`` (par défaut ``declaration()``) : les
    métriques de chaque modèle déclaré, ou, sans référence, son motif."""
    chosen = declaration() if declared is None else declared
    comparisons = []
    for entry in chosen.performances:
        first = entry.performance.outings[0]
        day = entry.performance.civil_date
        if first.reference is None:
            comparisons.append(
                PerformanceComparison(
                    day, first.outing_id, PerformanceMotif.NO_REFERENCE, ()
                )
            )
            continue
        metrics = tuple(c for model in chosen.models for c in _metrics(model.kind))
        comparisons.append(PerformanceComparison(day, first.outing_id, None, metrics))
    return tuple(comparisons)


def _document(
    comparator: int = COMPARATOR,
    configurations: tuple[SensitivityConfiguration, ...] = SENSITIVITY_CONFIGURATIONS,
    comparisons: tuple[PerformanceComparison, ...] | None = None,
) -> SensitivityOutcome:
    """Un document de sensibilité sans expérience, valide, chaque configuration
    portant ``comparisons`` (par défaut ``_comparisons()``)."""
    chosen = _comparisons() if comparisons is None else comparisons
    return SensitivityOutcome(
        comparator,
        tuple(
            ConfigurationOutcome(
                configuration,
                chosen,
                None,
                None,
                (),
                None,
                None,
                None,
                False,
                False,
                False,
                False,
            )
            for configuration in configurations
        ),
        (),
    )


def _other_references() -> tuple[tuple[str, RepeatabilityReference], ...]:
    """La référence D8 de ``r1``, lue un jour plus tard : mêmes jours, même fichier
    (même empreinte), un autre document."""
    ((route_id, reference),) = references()
    source = reference.reference
    later = replace(source, retrieved_at=source.retrieved_at + timedelta(days=1))
    return ((route_id, replace(reference, reference=later)),)


# ---------------------------------------------------------------------------
# Aides : registres
# ---------------------------------------------------------------------------


def _central(tmp_path: Path, **changes: Any) -> Path:
    """Une centrale de v0 brut (``declaration(**changes)``) et son RÉSULTAT."""
    root = registry_root(tmp_path)
    append_declaration(root, declaration(**changes), recorded_at=at(0))
    append_result(root, 1, outcomes(), references=references(), recorded_at=at(1))
    return root


def _declared(tmp_path: Path) -> Path:
    """La centrale, son RÉSULTAT, et sa DÉCLARATION de sensibilité (3)."""
    root = _central(tmp_path)
    append_declaration(root, _sensitivity_of(root), recorded_at=at(2))
    return root


def _answer(
    root: Path,
    number: int = 3,
    pairs: tuple[PairOutcome, ...] | None = None,
    document: SensitivityOutcome | None = None,
    minutes: int = 3,
) -> RegistryEvent:
    """Le RÉSULTAT de sensibilité de la DÉCLARATION ``number``."""
    return append_result(
        root,
        number,
        (),
        pairs=_pair_outcomes() if pairs is None else pairs,
        sensitivity=_document() if document is None else document,
        recorded_at=at(minutes),
    )


def _sensitivity_registry(tmp_path: Path) -> Path:
    """La centrale (1, 2) et sa sensibilité (3, 4)."""
    root = _declared(tmp_path)
    _answer(root)
    return root


def _experiment_declared(tmp_path: Path) -> Path:
    """L'expérience synthétique (1, 2) et sa DÉCLARATION de sensibilité (3)."""
    root = _experiment_registry(tmp_path)
    append_declaration(root, _sensitivity_of(root), recorded_at=at(2))
    return root


def _files(root: Path) -> dict[str, bytes]:
    """Les fichiers du registre et leurs octets."""
    return {
        str(path.relative_to(root)): path.read_bytes()
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


def _refused_append(root: Path, append: Callable[[], object], message: str) -> None:
    """L'ajout est refusé par ``message`` (préfixé « ajout refusé : ») ; rien n'est
    écrit."""
    before = _files(root)
    with pytest.raises(RegistryError, match=re.escape(REFUSED + message)):
        append()
    assert _files(root) == before


def _write_declaration(root: Path, forged: Declaration) -> None:
    """``forged`` écrite à la main en fin de journal, sans l'accord de l'ajout : la
    ligne canonique au format 5, la chaîne des empreintes recalculée."""
    events = list(read_registry(root).events)
    events.append(
        replace(
            events[0],
            number=len(events) + 1,
            recorded_at=at(len(events)),
            previous_hash="0" * 64,
            declaration=forged,
        )
    )
    _write_events(root, events)


def _write_result(root: Path, document: str) -> None:
    """Le RÉSULTAT de sensibilité de la DÉCLARATION 3 écrit à la main en fin de
    journal, sans l'accord de l'ajout : chaque paire reprend les sorties, les sorties
    non scorées et les références D8 du RÉSULTAT central (2) ; il cite ``document``."""
    events = list(read_registry(root).events)
    central = events[1].result
    assert central is not None
    pairs = tuple(
        PairResult(*pair, central.outings, central.unscored, central.references)
        for pair in SENSITIVITY_PAIRS
    )
    events.append(
        replace(
            events[1],
            number=4,
            answers=3,
            recorded_at=at(3),
            previous_hash="0" * 64,
            result=Result((), (), (), None, pairs, document),
        )
    )
    _write_events(root, events)


def _truncate(root: Path, kept: int) -> None:
    """Le journal réduit à ses ``kept`` premières lignes (les documents restent)."""
    lines = (root / EVENTS_FILE).read_bytes().split(b"\n")[:kept]
    (root / EVENTS_FILE).write_bytes(b"".join(line + b"\n" for line in lines))


def _on_result(
    change: Callable[[Result], Result],
) -> Callable[[RegistryEvent], RegistryEvent]:
    """Pour ``_rewrite`` : le RÉSULTAT de sensibilité (ligne 4) changé par
    ``change``."""

    def rewrite(event: RegistryEvent) -> RegistryEvent:
        if event.result is None or not event.result.pairs:
            return event
        return replace(event, result=change(event.result))

    return rewrite


def _with_pairs(
    change: Callable[[tuple[PairResult, ...]], tuple[PairResult, ...]],
) -> Callable[[Result], Result]:
    return lambda result: replace(result, pairs=change(result.pairs))


def _replaced(
    pairs: tuple[PairResult, ...], rank: int, **changes: Any
) -> tuple[PairResult, ...]:
    """``pairs``, la paire de rang ``rank`` changée."""
    return tuple(replace(p, **changes) if i == rank else p for i, p in enumerate(pairs))


# ---------------------------------------------------------------------------
# Versions ; le document de sensibilité (codec)
# ---------------------------------------------------------------------------


def test_versions() -> None:
    """Précision de D14 (M4d-3) : le format écrit, les formats relus, le premier format
    de la sensibilité, et son document, dernier des types de documents."""
    assert REGISTRY_FORMAT_VERSION == 5
    assert REGISTRY_READABLE_FORMATS == (1, 2, 3, 4, 5)
    assert SENSITIVITY_FIRST_FORMAT == 5
    assert DOCUMENT_FIRST_FORMAT[SensitivityOutcome] == 5
    assert DOCUMENT_TYPES[-1] is SensitivityOutcome


def test_sensitivity_document_at_format_5() -> None:
    """Précision de D14 (M4d-3) : le document de sensibilité s'écrit au format 5 et se
    relit égal à l'objet écrit, à l'octet à la réécriture."""
    value = _document()
    data = encode_document(value, 5)
    assert data.startswith(b'{"type":"SensitivityOutcome","format":5,')
    back = decode_document(data, SensitivityOutcome, 5)
    assert back == value
    assert encode_document(back, 5) == data


@pytest.mark.parametrize("format_version", [1, 2, 3, 4])
def test_sensitivity_document_does_not_exist_before_format_5(
    format_version: int,
) -> None:
    """Précision de D14 (M4d-3) : le document de sensibilité ne s'écrit pas avant le
    format 5 ; relu à un format antérieur, il est refusé — au format de son enveloppe
    d'abord, puis, d'une enveloppe du format antérieur, parce que ce format ne le
    connaît pas."""
    value = _document()
    with pytest.raises(
        TypeError,
        match=re.escape(
            "SensitivityOutcome n'existe qu'à partir du format 5, demandé au format "
            f"{format_version}."
        ),
    ):
        encode_document(value, format_version)
    data = encode_document(value, 5)
    with pytest.raises(
        CodecError, match=re.escape(f"document au format 5, {format_version} attendu")
    ):
        decode_document(data, SensitivityOutcome, format_version)
    forged = data.replace(b'"format":5,', f'"format":{format_version},'.encode(), 1)
    with pytest.raises(
        CodecError,
        match=re.escape(
            f"document de type 'SensitivityOutcome' au format {format_version}, qui "
            "ne le connaît pas"
        ),
    ):
        decode_document(forged, SensitivityOutcome, format_version)


# ---------------------------------------------------------------------------
# Les formats 1 à 4 relus par le code du format 5
# ---------------------------------------------------------------------------


def _old_registry(tmp_path: Path, version: int) -> Path:
    """Une centrale de v0 brut et son RÉSULTAT, écrits par le code du jour puis
    récrits au format ``version``."""
    root = _central(tmp_path)
    _to_format(root, version)
    return root


@pytest.mark.parametrize("version", [1, 2, 3, 4])
def test_old_registry_is_read_at_bit(tmp_path: Path, version: int) -> None:
    """Précision de D14 (M4d-3) : un registre des formats 1 à 4 se relit et se vérifie
    par le code du format 5 ; ses lignes ne portent ni ``sensitivity`` ni ``pairs``,
    se relisent sans eux, et chacune se réécrit à l'octet (son empreinte est celle de
    sa ligne) ; le journal n'est pas touché."""
    root = _old_registry(tmp_path, version)
    before = (root / EVENTS_FILE).read_bytes()
    declared, answered = _lines(root)
    assert "sensitivity" not in declared["declaration"]
    assert "pairs" not in answered["result"]
    assert "sensitivity" not in answered["result"]
    log = verify_registry(root)
    assert [event.format_version for event in log.events] == [version, version]
    first, second = log.events
    assert first.declaration is not None
    assert first.declaration.sensitivity is None
    assert second.result is not None
    assert (second.result.pairs, second.result.sensitivity) == ((), None)
    lines = before.split(b"\n")[:-1]
    assert [content_hash(line) for line in lines] == [line_hash(e) for e in log.events]
    assert load_pair_outcomes(root, log, 2) == ()
    assert load_sensitivity(root, log, 2) is None
    assert (root / EVENTS_FILE).read_bytes() == before


@pytest.mark.parametrize("version", [1, 2, 3, 4])
def test_sensitivity_follows_an_old_registry(tmp_path: Path, version: int) -> None:
    """Précision de D14 (M4d-3) : une centrale du format 5 et sa sensibilité
    s'enchaînent à un registre d'un format antérieur ; le journal entier se vérifie,
    les lignes anciennes restent à l'octet ; la sensibilité compte à part."""
    root = _old_registry(tmp_path, version)
    before = (root / EVENTS_FILE).read_bytes()
    append_declaration(root, declaration(), recorded_at=at(2))
    append_result(root, 3, outcomes(), references=references(), recorded_at=at(3))
    append_declaration(root, _sensitivity_of(root, 3, 4), recorded_at=at(4))
    _answer(root, 5, minutes=5)
    log = verify_registry(root)
    assert [e.format_version for e in log.events] == [version] * 2 + [5] * 4
    assert (root / EVENTS_FILE).read_bytes().startswith(before)
    trials = count_trials(log)
    assert (trials.declarations, trials.without_effect, trials.sensitivities) == (
        3,
        2,
        1,
    )


@pytest.mark.parametrize("version", [1, 2, 3, 4])
@pytest.mark.parametrize(
    ("line", "where", "key", "value"),
    [
        (1, "declaration", "sensitivity", None),
        (2, "result", "pairs", []),
        (2, "result", "sensitivity", None),
    ],
    ids=["declaration-sensitivity", "result-pairs", "result-sensitivity"],
)
def test_old_line_carrying_the_new_fields_is_refused(
    tmp_path: Path, version: int, line: int, where: str, key: str, value: object
) -> None:
    """Précision de D14 (M4d-3) : une ligne d'un format antérieur au 5 qui porte
    ``sensitivity`` (DÉCLARATION, RÉSULTAT) ou ``pairs`` (RÉSULTAT), même ``null`` ou
    vide, n'est pas relue : champ inconnu à son format."""
    root = _old_registry(tmp_path, version)

    def carrying(data: dict[str, Any]) -> None:
        if data["number"] == line:
            data[where][key] = value

    _journal(root, carrying)
    with pytest.raises(
        RegistryError,
        match=re.escape(
            f"{_line(line)}{where} : champ inconnu au format {version} : {key!r}"
        ),
    ):
        read_registry(root)


@pytest.mark.parametrize("version", [1, 2, 3, 4])
def test_event_before_format_5_carries_no_sensitivity(
    tmp_path: Path, version: int
) -> None:
    """Invariant 2 de ``RegistryEvent`` (M4d-3) : ni une DÉCLARATION de sensibilité,
    ni un RÉSULTAT de sensibilité avant le format 5."""
    log = read_registry(_sensitivity_registry(tmp_path))
    with pytest.raises(
        ContractError,
        match=re.escape(
            f"une DÉCLARATION du format {version} ne porte pas de sensibilité "
            "(format 5)."
        ),
    ):
        replace(log.events[2], format_version=version)
    with pytest.raises(
        ContractError,
        match=re.escape(
            f"un RÉSULTAT du format {version} ne porte pas de sensibilité (format 5)."
        ),
    ):
        replace(log.events[3], format_version=version)


# ---------------------------------------------------------------------------
# L'accord d'une DÉCLARATION de sensibilité, à l'ajout et à la relecture
# ---------------------------------------------------------------------------


def _swapped(
    configurations: tuple[SensitivityConfiguration, ...], i: int, j: int
) -> tuple[SensitivityConfiguration, ...]:
    """``configurations``, celles de rangs ``i`` et ``j`` échangées."""
    changed = list(configurations)
    changed[i], changed[j] = changed[j], changed[i]
    return tuple(changed)


def _with_configurations(
    configurations: tuple[SensitivityConfiguration, ...],
) -> Callable[[Path], Declaration]:
    return lambda root: _sensitivity_of(
        root, configurations=configurations, pairs=_pairs_of(configurations)
    )


def _recopied(**changes: Any) -> Callable[[Path], Declaration]:
    return lambda root: replace(_sensitivity_of(root), **changes)


DECLARATION_CASES: dict[str, tuple[Callable[[Path], Declaration], str]] = {
    "empreinte-centrale": (
        lambda root: _sensitivity_of(root, central_hash="0" * 64),
        "l'empreinte déclarée de la ligne de la DÉCLARATION centrale (1) ne "
        "correspond pas",
    ),
    "empreinte-resultat": (
        lambda root: _sensitivity_of(root, answer_hash="0" * 64),
        "l'empreinte déclarée de la ligne du RÉSULTAT central (2) ne correspond pas",
    ),
    "commit": (_recopied(commit="f" * 40), RECOPY),
    "manifeste": (
        _recopied(manifest=replace(declaration().manifest, content_hash="3" * 64)),
        RECOPY,
    ),
    "exclusions": (_recopied(exclusions=()), RECOPY),
    "performances": (_recopied(performances=performances()[:2]), RECOPY),
    "modeles": (
        _recopied(models=(replace(V0_RAW, engine_version="v0-autre"),)),
        RECOPY,
    ),
    "appariement-declare": (
        _recopied(matching=pair_matching((100.0, 15.0))),
        RECOPY,
    ),
    "neuf-de-l-ecoule": (
        _with_configurations(SENSITIVITY_CONFIGURATIONS[:9]),
        NINETEEN,
    ),
    "sans-la-derniere": (
        _with_configurations(SENSITIVITY_CONFIGURATIONS[:18]),
        NINETEEN,
    ),
    "ordre-des-horloges": (
        _with_configurations(_swapped(SENSITIVITY_CONFIGURATIONS, 9, 10)),
        NINETEEN,
    ),
    "ordre-des-paires": (
        _with_configurations(_swapped(SENSITIVITY_CONFIGURATIONS, 0, 1)),
        NINETEEN,
    ),
}
"""Les DÉCLARATIONS de sensibilité refusées sur la centrale de ``_central`` : leur
fabrique et le motif du refus, sans préfixe."""


@pytest.mark.parametrize("case", list(DECLARATION_CASES))
def test_declaration_refused_at_append(tmp_path: Path, case: str) -> None:
    """Précision et exception de D14 (M4d-3) : l'accord à l'ajout d'une DÉCLARATION de
    sensibilité — les empreintes des lignes de la centrale et de son RÉSULTAT, la
    recopie champ pour champ (une autre modification, l'appariement déclaré compris,
    est une expérience neuve), les dix-neuf configurations dans leur ordre (une
    sélection refusée) ; rien n'est écrit."""
    forged, message = DECLARATION_CASES[case]
    root = _central(tmp_path)
    _refused_append(
        root,
        lambda: append_declaration(root, forged(root), recorded_at=at(2)),
        message,
    )


@pytest.mark.parametrize("case", list(DECLARATION_CASES))
def test_declaration_refused_on_reading(tmp_path: Path, case: str) -> None:
    """Précision de D14 (M4d-3) : les mêmes refus à la relecture d'une ligne écrite à
    la main, sans l'accord de l'ajout."""
    forged, message = DECLARATION_CASES[case]
    root = _central(tmp_path)
    _write_declaration(root, forged(root))
    with pytest.raises(RegistryError, match=re.escape(_line(3) + message)):
        read_registry(root)


def test_accepted_declaration_is_read_back(tmp_path: Path) -> None:
    """Contre-épreuve : la DÉCLARATION de sensibilité exacte s'ajoute, se relit égale,
    et ne cite aucun document."""
    root = _central(tmp_path)
    expected = _sensitivity_of(root)
    documents = sorted((root / "documents").iterdir())
    event = append_declaration(root, expected, recorded_at=at(2))
    log = verify_registry(root)
    assert log.events[2] == event
    assert event.declaration == expected
    assert sorted((root / "documents").iterdir()) == documents


MATCHINGS = {
    "100-15": pair_matching((100.0, 15.0)),
    "250-45": pair_matching((250.0, 45.0)),
    "rayon-20": ParameterSet(MATCHING_PARAMETER_SPECS, {"cluster_radius_m": 20.0}),
}
"""Des appariements centraux hors de ``(250, 30)``, ``r_c = 15`` m."""


@pytest.mark.parametrize("name", list(MATCHINGS))
def test_central_matched_elsewhere_is_refused(tmp_path: Path, name: str) -> None:
    """Précision de D14 (M4d-3) : une centrale appariée hors de ``(250, 30)``,
    ``r_c = 15`` m, n'a pas de comparateur parmi les dix-neuf — sa DÉCLARATION de
    sensibilité, qui la recopie, est refusée à l'ajout et à la relecture."""
    (tmp_path / "ajout").mkdir()
    (tmp_path / "relecture").mkdir()
    root = _central(tmp_path / "ajout", matching=MATCHINGS[name])
    _refused_append(
        root,
        lambda: append_declaration(root, _sensitivity_of(root), recorded_at=at(2)),
        CENTRAL_MATCHING,
    )
    root = _central(tmp_path / "relecture", matching=MATCHINGS[name])
    _write_declaration(root, _sensitivity_of(root))
    with pytest.raises(RegistryError, match=re.escape(_line(3) + CENTRAL_MATCHING)):
        read_registry(root)


def _comparator_without_references(root: Path) -> Declaration:
    """La DÉCLARATION de sensibilité de l'expérience, les références figées de son
    comparateur retirées."""
    forged = _sensitivity_of(root)
    assert forged.sensitivity is not None
    assert forged.sensitivity.frozen is not None
    frozen = tuple(
        replace(entry, frozen_references=())
        if entry.configuration == ELAPSED_COMPARATOR
        else entry
        for entry in forged.sensitivity.frozen
    )
    return replace(forged, sensitivity=replace(forged.sensitivity, frozen=frozen))


def test_frozen_references_of_the_comparator(tmp_path: Path) -> None:
    """Précision de D14 (M4d-3) : pour une expérience, les références figées du
    comparateur sont celles de l'expérience centrale — d'autres sont refusées à
    l'ajout et à la relecture ; les exactes sont acceptées."""
    (tmp_path / "ajout").mkdir()
    (tmp_path / "relecture").mkdir()
    root = _experiment_registry(tmp_path / "ajout")
    _refused_append(
        root,
        lambda: append_declaration(
            root, _comparator_without_references(root), recorded_at=at(2)
        ),
        FROZEN_COMPARATOR,
    )
    append_declaration(root, _sensitivity_of(root), recorded_at=at(2))
    assert len(verify_registry(root).events) == 3
    root = _experiment_registry(tmp_path / "relecture")
    _write_declaration(root, _comparator_without_references(root))
    with pytest.raises(RegistryError, match=re.escape(_line(3) + FROZEN_COMPARATOR)):
        read_registry(root)


EXPERIMENT_RECOPY: dict[str, dict[str, Any]] = {
    "cible": {"target": ExperimentMetric.ASCENT_LEVEL},
    "candidat": {
        "effect": DeclaredEffect("autre", "un autre effet", None, "règle de D9.3")
    },
}
"""Ce qu'une DÉCLARATION de sensibilité d'une expérience ne change pas."""


@pytest.mark.parametrize("name", list(EXPERIMENT_RECOPY))
def test_experiment_recopy(tmp_path: Path, name: str) -> None:
    """Exception de D14 (M4d-3) : une DÉCLARATION de sensibilité qui change la cible
    ou le candidat de l'expérience n'en est pas une — refusée à l'ajout et à la
    relecture."""

    def forged(root: Path) -> Declaration:
        declared = _sensitivity_of(root)
        assert declared.experiment is not None
        experiment = replace(declared.experiment, **EXPERIMENT_RECOPY[name])
        return replace(declared, experiment=experiment)

    (tmp_path / "ajout").mkdir()
    (tmp_path / "relecture").mkdir()
    root = _experiment_registry(tmp_path / "ajout")
    _refused_append(
        root, lambda: append_declaration(root, forged(root), recorded_at=at(2)), RECOPY
    )
    root = _experiment_registry(tmp_path / "relecture")
    _write_declaration(root, forged(root))
    with pytest.raises(RegistryError, match=re.escape(_line(3) + RECOPY)):
        read_registry(root)


def test_frozen_references_iff_experiment(tmp_path: Path) -> None:
    """Invariant 9 de ``Declaration`` (M4d-3) : une DÉCLARATION de sensibilité fige
    les références de chaque configuration si et seulement si elle porte une
    expérience — refusé à la construction, et à la relecture d'une ligne qui les
    retire."""
    (tmp_path / "experience").mkdir()
    backtest = _sensitivity_of(_central(tmp_path))
    experiment = _sensitivity_of(_experiment_registry(tmp_path / "experience"))
    assert backtest.sensitivity is not None
    assert experiment.sensitivity is not None
    with pytest.raises(ContractError, match=re.escape(FROZEN_IFF)):
        replace(
            backtest,
            sensitivity=replace(
                backtest.sensitivity, frozen=experiment.sensitivity.frozen
            ),
        )
    with pytest.raises(ContractError, match=re.escape(FROZEN_IFF)):
        replace(experiment, sensitivity=replace(experiment.sensitivity, frozen=None))
    (tmp_path / "relue").mkdir()
    root = _experiment_declared(tmp_path / "relue")

    def without_frozen(data: dict[str, Any]) -> None:
        if data["number"] == 3:
            data["declaration"]["sensitivity"]["frozen"] = None

    _journal(root, without_frozen)
    with pytest.raises(RegistryError, match=re.escape(_line(3) + FROZEN_IFF)):
        read_registry(root)


def _corrected(tmp_path: Path, which: str) -> Path:
    """La centrale et son RÉSULTAT, puis une correction de la centrale (``which`` =
    ``"centrale"``) ou de son RÉSULTAT (``"reponse"``), identique."""
    root = _central(tmp_path)
    if which == "centrale":
        append_declaration(
            root,
            declaration(),
            recorded_at=at(2),
            corrects=1,
            correction_reason="correction synthétique",
        )
    else:
        append_result(
            root,
            1,
            outcomes(),
            references=references(),
            recorded_at=at(2),
            corrects=2,
            correction_reason="correction synthétique",
        )
    return root


NOT_IN_FORCE = {
    "centrale": "la DÉCLARATION centrale 1 est corrigée",
    "reponse": (
        "le RÉSULTAT 2 n'est pas la réponse en vigueur de la DÉCLARATION centrale 1"
    ),
}
"""Les refus d'une centrale, ou de sa réponse, qui n'est pas en vigueur."""


@pytest.mark.parametrize("which", list(NOT_IN_FORCE))
def test_central_and_answer_in_force_at_append_only(tmp_path: Path, which: str) -> None:
    """Précision de D14 (M4d-3) : à l'ajout seulement, la centrale et son RÉSULTAT sont
    en vigueur — une centrale corrigée, ou un RÉSULTAT central corrigé, est refusé ;
    à la relecture, la même ligne (écrite à la main) est acceptée."""
    (tmp_path / "ajout").mkdir()
    root = _corrected(tmp_path / "ajout", which)

    def append() -> RegistryEvent:
        return append_declaration(root, _sensitivity_of(root), recorded_at=at(3))

    _refused_append(root, append, NOT_IN_FORCE[which])
    relue = _corrected(tmp_path, which)
    _write_declaration(relue, _sensitivity_of(relue))
    assert len(verify_registry(relue).events) == 4


def test_sensitivity_of_a_sensitivity_is_refused(tmp_path: Path) -> None:
    """Invariant 5 de ``RegistryLog`` (M4d-3) : une DÉCLARATION de sensibilité qualifie
    une DÉCLARATION centrale, pas une autre sensibilité."""
    root = _sensitivity_registry(tmp_path)
    _refused_on_log = (
        f"{EVENTS_FILE} : la DÉCLARATION de sensibilité 5 qualifie l'événement 3, qui "
        "n'est pas une DÉCLARATION centrale."
    )
    before = _files(root)
    with pytest.raises(RegistryError, match=re.escape(_refused_on_log)):
        append_declaration(root, _sensitivity_of(root, 3, 4), recorded_at=at(4))
    assert _files(root) == before


# ---------------------------------------------------------------------------
# L'accord d'un RÉSULTAT de sensibilité, à l'ajout et à la relecture
# ---------------------------------------------------------------------------


def _paired(*pairs: Pair) -> str:
    return str(list(pairs))


RESULT_CASES: dict[
    str,
    tuple[
        Callable[[], tuple[PairOutcome, ...]],
        Callable[[Path, tuple[PairResult, ...]], tuple[PairResult, ...]],
        str,
        bool,
    ],
] = {
    "ordre-des-paires": (
        lambda: tuple(reversed(_pair_outcomes())),
        lambda root, pairs: tuple(reversed(pairs)),
        "le RÉSULTAT de sensibilité porte les paires déclarées, dans l'ordre : "
        f"{_paired(*SENSITIVITY_PAIRS)} attendu, reçu "
        f"{_paired(*reversed(SENSITIVITY_PAIRS))}",
        False,
    ),
    "paire-absente": (
        lambda: _pair_outcomes()[:-1],
        lambda root, pairs: pairs[:-1],
        "le RÉSULTAT de sensibilité porte les paires déclarées, dans l'ordre : "
        f"{_paired(*SENSITIVITY_PAIRS)} attendu, reçu "
        f"{_paired(*SENSITIVITY_PAIRS[:-1])}",
        False,
    ),
    "sortie-sans-sort": (
        lambda: _pair_outcomes(
            changed={(100.0, 15.0): PairOutcome(100.0, 15.0, outcomes()[:2], (), ())}
        ),
        lambda root, pairs: _replaced(pairs, 0, outings=pairs[0].outings[:2]),
        f"paire (100, 15), la sortie déclarée {P03_ID!r} n'est ni scorée ni écartée "
        "avec un motif",
        False,
    ),
    "sans-reference-d8": (
        lambda: _pair_outcomes(
            changed={(100.0, 15.0): PairOutcome(100.0, 15.0, outcomes(), (), ())}
        ),
        lambda root, pairs: _replaced(pairs, 0, references=()),
        "paire (100, 15), le parcours de répétabilité 'r1' n'a pas de référence D8",
        True,
    ),
    "references-d8-non-figees": (
        lambda: _pair_outcomes(
            changed={
                (100.0, 15.0): PairOutcome(
                    100.0, 15.0, outcomes(), (), _other_references()
                )
            }
        ),
        lambda root, pairs: _replaced(
            pairs,
            0,
            references=(
                RepeatabilityRecord("r1", _store(root, _other_references()[0][1])),
            ),
        ),
        FROZEN_D8,
        True,
    ),
    "paire-centrale-sorties": (
        lambda: _pair_outcomes(
            changed={
                CENTRAL_PAIR: PairOutcome(
                    *CENTRAL_PAIR,
                    outcomes()[:2],
                    (Exclusion(P03_ID, "sortie non tracée"),),
                    references(),
                )
            }
        ),
        lambda root, pairs: _replaced(
            pairs,
            4,
            outings=pairs[4].outings[:2],
            unscored=(Exclusion(P03_ID, "sortie non tracée"),),
        ),
        CENTRAL_PAIR_IS_THE_RESULT,
        False,
    ),
    "paire-centrale-references": (
        lambda: _pair_outcomes(
            changed={
                CENTRAL_PAIR: PairOutcome(
                    *CENTRAL_PAIR, outcomes(), (), _other_references()
                )
            }
        ),
        lambda root, pairs: _replaced(
            pairs,
            4,
            references=(
                RepeatabilityRecord("r1", _store(root, _other_references()[0][1])),
            ),
        ),
        CENTRAL_PAIR_IS_THE_RESULT,
        False,
    ),
}
"""Les RÉSULTATS de sensibilité refusés : leurs paires à l'ajout, le changement de
leurs paires à la relecture, le motif sans préfixe, et s'il faut la vérification par
les documents (``verify_registry``) pour le voir."""


@pytest.mark.parametrize("case", list(RESULT_CASES))
def test_result_pairs_refused_at_append(tmp_path: Path, case: str) -> None:
    """Précision de D14 (M4d-3) : le RÉSULTAT porte les paires déclarées, dans
    l'ordre, chacune accordée comme le RÉSULTAT d'une exécution (sorties, références
    D8 de chaque parcours de répétabilité), ses références D8 celles que la
    DÉCLARATION a figées, et la paire ``(250, 30)`` est le RÉSULTAT central ; rien
    n'est écrit."""
    pairs, _, message, _ = RESULT_CASES[case]
    root = _declared(tmp_path)
    _refused_append(root, lambda: _answer(root, pairs=pairs()), message)


@pytest.mark.parametrize("case", list(RESULT_CASES))
def test_result_pairs_refused_on_reading(tmp_path: Path, case: str) -> None:
    """Précision de D14 (M4d-3) : les mêmes refus à la relecture d'un RÉSULTAT récrit
    à la main — à ``read_registry`` ou, pour ce que disent les documents, à
    ``verify_registry``."""
    _, change, message, documents = RESULT_CASES[case]
    root = _sensitivity_registry(tmp_path)
    _rewrite(root, _on_result(_with_pairs(lambda pairs: change(root, pairs))))
    if documents:
        read_registry(root)
    with pytest.raises(RegistryError, match=re.escape(_line(4) + message)):
        (verify_registry if documents else read_registry)(root)


def test_exact_result_is_read_back(tmp_path: Path) -> None:
    """Contre-épreuve : le RÉSULTAT de sensibilité exact s'ajoute et se vérifie ; sa
    paire ``(250, 30)`` cite les documents mêmes du RÉSULTAT central ; il ne cite ni
    sorties, ni références, ni document d'admission à part."""
    root = _sensitivity_registry(tmp_path)
    log = verify_registry(root)
    central, answer = log.events[1].result, log.events[3].result
    assert central is not None
    assert answer is not None
    assert (answer.outings, answer.unscored, answer.references) == ((), (), ())
    assert answer.admission is None
    assert answer.sensitivity == content_hash(encode_document(_document()))
    pair = answer.pairs[COMPARATOR]
    assert (pair.outings, pair.unscored, pair.references) == (
        central.outings,
        central.unscored,
        central.references,
    )


DOCUMENT_CASES: dict[str, tuple[Callable[[], SensitivityOutcome], str]] = {
    "configurations-dans-un-autre-ordre": (
        lambda: _document(configurations=_swapped(SENSITIVITY_CONFIGURATIONS, 9, 10)),
        CONFIGURATIONS_OF_THE_DOCUMENT,
    ),
    "neuf-configurations": (
        lambda: _document(configurations=SENSITIVITY_CONFIGURATIONS[:9]),
        CONFIGURATIONS_OF_THE_DOCUMENT,
    ),
    "comparateur": (
        lambda: _document(comparator=3),
        f"le comparateur du document de sensibilité n'est pas {ELAPSED_COMPARATOR}",
    ),
    "performance-absente": (
        lambda: _document(comparisons=_comparisons()[:2]),
        PERFORMANCES_OF_THE_DOCUMENT,
    ),
    "autre-premiere-sortie": (
        lambda: _document(
            comparisons=(
                replace(_comparisons()[0], outing_id="autre-sortie"),
                *_comparisons()[1:],
            )
        ),
        PERFORMANCES_OF_THE_DOCUMENT,
    ),
}
"""Les documents de sensibilité refusés pour la centrale de v0 brut, et le motif."""


@pytest.mark.parametrize("case", list(DOCUMENT_CASES))
def test_sensitivity_document_refused(tmp_path: Path, case: str) -> None:
    """Précision de D14 (M4d-3) : le document de sensibilité porte les configurations
    déclarées dans leur ordre, le comparateur (``(250, 30)`` sous l'écoulé pour ``just
    backtest``), les performances déclarées (jours et premières sorties) — refusé à
    l'ajout, et à la vérification d'un RÉSULTAT qui le cite à la main."""
    document, message = DOCUMENT_CASES[case]
    (tmp_path / "ajout").mkdir()
    root = _declared(tmp_path / "ajout")
    _refused_append(root, lambda: _answer(root, document=document()), message)
    root = _sensitivity_registry(tmp_path)
    sha = _store(root, document())
    _rewrite(root, _on_result(lambda result: replace(result, sensitivity=sha)))
    read_registry(root)
    with pytest.raises(RegistryError, match=re.escape(_line(4) + message)):
        verify_registry(root)


def test_document_without_experiment_for_an_experiment(tmp_path: Path) -> None:
    """Précision de D14 (M4d-3) : le document de sensibilité d'une expérience porte une
    expérience — un document sans expérience est refusé à l'ajout et à la
    vérification."""
    (tmp_path / "ajout").mkdir()
    root = _experiment_declared(tmp_path / "ajout")
    pairs = _pair_outcomes(_experiment_outcomes())
    _refused_append(root, lambda: _answer(root, pairs=pairs), EXPERIMENT_IFF)
    root = _experiment_declared(tmp_path)
    _write_result(root, _store(root, _document()))
    read_registry(root)
    with pytest.raises(RegistryError, match=re.escape(_line(4) + EXPERIMENT_IFF)):
        verify_registry(root)


@pytest.fixture(scope="module")
def experiment(tmp_path_factory: pytest.TempPathFactory) -> ExperimentSensitivity:
    """L'expérience du monde déclarée sous l'écoulé, et sa sensibilité."""
    return experiment_sensitivity(tmp_path_factory, "ecoule")


def test_experiment_document_for_just_backtest(
    tmp_path: Path, experiment: ExperimentSensitivity
) -> None:
    """Précision de D14 (M4d-3) : le document de sensibilité de ``just backtest`` ne
    porte pas d'expérience — celui d'une expérience du monde (même comparateur,
    ``(250, 30)`` sous l'écoulé) est refusé à l'ajout et à la vérification."""
    document = experiment.run.evaluation.outcome
    assert document.experiment
    assert document.configurations[document.comparator].configuration == (
        ELAPSED_COMPARATOR
    )
    (tmp_path / "ajout").mkdir()
    root = _declared(tmp_path / "ajout")
    _refused_append(root, lambda: _answer(root, document=document), EXPERIMENT_IFF)
    root = _sensitivity_registry(tmp_path)
    sha = _store(root, document)
    _rewrite(root, _on_result(lambda result: replace(result, sensitivity=sha)))
    with pytest.raises(RegistryError, match=re.escape(_line(4) + EXPERIMENT_IFF)):
        verify_registry(root)


def _other_target(experiment: ExperimentSensitivity) -> SensitivityOutcome:
    """Le document de sensibilité de l'expérience, l'admission de la configuration
    ``(250, 30)`` sous ``M θ1`` refaite pour la cible ``flat_level`` : un document
    valide, dont une admission porte une autre cible que l'expérience déclarée."""
    evaluation = experiment.run.evaluation
    declared = evaluation.declaration_event.declaration
    assert declared is not None
    assert declared.experiment is not None
    assert declared.sensitivity is not None
    assert declared.sensitivity.frozen is not None
    outcome = evaluation.outcome
    rank = 9
    entry = declared.sensitivity.frozen[rank]
    central = experiment.central
    raw: dict[str, OutingScores] = {}
    calibrated: dict[tuple[str, ModelKind], CalibratedOutingScores] = {}
    for scored in central.outcomes:
        for kind, scores in scored.scores:
            if isinstance(scores, OutingScores):
                raw[scored.outing_id] = scores
            else:
                calibrated[(scored.outing_id, kind)] = scores
    inputs = admission_inputs(central.preparation, raw, calibrated)
    local = replace(
        declared.experiment,
        target=ExperimentMetric.FLAT_LEVEL,
        clock=entry.configuration.clock,
        frozen_references=entry.frozen_references,
        reference_documents=reference_documents(
            central.preparation.references, entry.frozen_references
        ),
    )
    admitted = admit(local, inputs, entry.frozen_references)
    assert isinstance(admitted, Admission)
    comparator = outcome.configurations[outcome.comparator].admission
    assert comparator is not None
    configurations = list(outcome.configurations)
    configurations[rank] = configuration_outcome(
        entry.configuration, configurations[rank].performances, admitted, comparator
    )
    return sensitivity_outcome(outcome.comparator, tuple(configurations))


def test_admission_of_another_target_is_refused(
    tmp_path: Path, experiment: ExperimentSensitivity
) -> None:
    """Précision de D14 (M4d-3) : l'admission de chaque configuration porte la cible
    déclarée — une admission d'une autre cible est refusée à l'ajout du RÉSULTAT
    (les paires de l'exécution) et à la vérification d'un RÉSULTAT qui cite ce
    document à la main."""
    document = _other_target(experiment)
    pairs = tuple(
        PairOutcome(*p.pair, p.outcomes, p.unscored, p.references)
        for p in experiment.run.evaluation.pairs
    )
    root = copy_registry(experiment.registry, tmp_path / "ajout")
    _truncate(root, 3)
    _refused_append(
        root,
        lambda: append_result(root, 3, (), pairs=pairs, sensitivity=document),
        OTHER_TARGET,
    )
    root = copy_registry(experiment.registry, tmp_path / "relecture")
    sha = _store(root, document)
    _rewrite(root, _on_result(lambda result: replace(result, sensitivity=sha)))
    with pytest.raises(RegistryError, match=re.escape(_line(4) + OTHER_TARGET)):
        verify_registry(root)


def test_ordinary_declaration_with_a_sensitivity_result(tmp_path: Path) -> None:
    """Précision de D14 (M4d-3) : un RÉSULTAT de sensibilité répond à une DÉCLARATION
    de sensibilité — refusé pour une DÉCLARATION ordinaire, à l'ajout et à la
    relecture."""
    (tmp_path / "ajout").mkdir()
    root = _central(tmp_path / "ajout")
    append_declaration(root, declaration(), recorded_at=at(2))
    _refused_append(
        root, lambda: _answer(root), SENSITIVITY_RESULT_ANSWERS_A_SENSITIVITY
    )
    root = _sensitivity_registry(tmp_path)

    def ordinary(event: RegistryEvent) -> RegistryEvent:
        if event.number != 3 or event.declaration is None:
            return event
        return replace(event, declaration=replace(event.declaration, sensitivity=None))

    _rewrite(root, ordinary)
    with pytest.raises(
        RegistryError,
        match=re.escape(_line(4) + SENSITIVITY_RESULT_ANSWERS_A_SENSITIVITY),
    ):
        read_registry(root)


def test_sensitivity_declaration_with_an_ordinary_result(tmp_path: Path) -> None:
    """Précision de D14 (M4d-3) : une DÉCLARATION de sensibilité reçoit un RÉSULTAT de
    sensibilité — un RÉSULTAT ordinaire (les sorties de la centrale) est refusé à
    l'ajout et à la relecture."""
    (tmp_path / "ajout").mkdir()
    root = _declared(tmp_path / "ajout")
    _refused_append(
        root,
        lambda: append_result(root, 3, outcomes(), references=references()),
        SENSITIVITY_GETS_A_SENSITIVITY_RESULT,
    )
    root = _sensitivity_registry(tmp_path)
    central = read_registry(root).events[1].result
    assert central is not None
    _rewrite(root, _on_result(lambda result: central))
    with pytest.raises(
        RegistryError,
        match=re.escape(_line(4) + SENSITIVITY_GETS_A_SENSITIVITY_RESULT),
    ):
        read_registry(root)


@pytest.mark.parametrize(
    ("changes", "message"),
    [
        (
            {"sensitivity": None},
            "pairs est non vide si et seulement si sensitivity est présent",
        ),
        (
            {"pairs": ()},
            "pairs est non vide si et seulement si sensitivity est présent",
        ),
        (
            {"admission": "a" * 64},
            "le RÉSULTAT d'une sensibilité porte ses sorties paire par paire",
        ),
        ({"sensitivity": "pas-une-empreinte"}, "sensitivity"),
    ],
    ids=["sans-document", "sans-paire", "avec-admission", "empreinte"],
)
def test_result_contract(tmp_path: Path, changes: dict[str, Any], message: str) -> None:
    """Invariants de ``Result`` (M4d-3) : des paires si et seulement si un document de
    sensibilité, ``sha256`` ; alors ni sorties, ni références, ni admission à part."""
    result = read_registry(_sensitivity_registry(tmp_path)).events[3].result
    assert result is not None
    with pytest.raises(ContractError, match=re.escape(message)):
        replace(result, **changes)
    with pytest.raises(ContractError, match="paires"):
        replace(result, pairs=(result.pairs[0], *result.pairs))


# ---------------------------------------------------------------------------
# Comptage des essais ; relecture des paires et du document ; deux sensibilités
# ---------------------------------------------------------------------------


def test_count_trials_counts_sensitivities_apart(tmp_path: Path) -> None:
    """Exception de D14 (M4d-3) : une DÉCLARATION de sensibilité ne compte ni comme
    essai de l'effet, ni comme exécution sans effet ; les sensibilités se comptent à
    part, corrections et échecs compris ; ``declarations`` vaut les exécutions sans
    effet, plus les essais de chaque effet et cible, plus les sensibilités."""
    root = _sensitivity_registry(tmp_path)
    append_declaration(root, _sensitivity_of(root), recorded_at=at(4))
    append_failure(
        root, 5, Failure(FailureKind.TECHNICAL, "panne synthétique"), recorded_at=at(5)
    )
    append_declaration(
        root,
        _sensitivity_of(root),
        recorded_at=at(6),
        corrects=5,
        correction_reason="correction synthétique",
    )
    (tmp_path / "experience").mkdir()
    experimental = read_registry(_experiment_registry(tmp_path / "experience")).events[
        0
    ]
    assert experimental.declaration is not None
    append_declaration(root, experimental.declaration, recorded_at=at(7))
    trials = count_trials(verify_registry(root))
    assert trials == TrialCounts(
        declarations=5,
        corrections=1,
        without_effect=1,
        by_experiment=(ExperimentTrials("arrêts", ExperimentMetric.DESCENT_LEVEL, 1),),
        sensitivities=3,
    )
    with pytest.raises(
        ContractError,
        match=re.escape(
            "declarations (5) doit valoir without_effect + Σ count + sensitivities "
            "(4) : chaque déclaration compte une fois."
        ),
    ):
        replace(trials, sensitivities=2)
    with pytest.raises(
        ContractError, match=re.escape("sensitivities doit être >= 0, reçu -1.")
    ):
        replace(trials, sensitivities=-1)


def test_pairs_and_document_are_read_back(tmp_path: Path) -> None:
    """``load_pair_outcomes`` et ``load_sensitivity`` (M4d-3) : les paires du RÉSULTAT
    de sensibilité et son document, relus égaux à ce qui a été ajouté ; vide et
    ``None`` pour le RÉSULTAT central ; un événement qui n'est pas un RÉSULTAT,
    refusé."""
    (tmp_path / "x").mkdir()
    root = _sensitivity_registry(tmp_path / "x")
    log = verify_registry(root)
    assert load_pair_outcomes(root, log, 4) == _pair_outcomes()
    assert load_sensitivity(root, log, 4) == _document()
    assert load_outcomes(root, log, 4) == ()
    assert load_references(root, log, 4) == ()
    assert load_pair_outcomes(root, log, 2) == ()
    assert load_sensitivity(root, log, 2) is None
    for load in (load_pair_outcomes, load_sensitivity):
        with pytest.raises(
            RegistryError, match=re.escape("l'événement 3 n'est pas un résultat")
        ):
            load(root, log, 3)


def test_world_pairs_and_document_are_read_back(
    tmp_path_factory: pytest.TempPathFactory,
) -> None:
    """``load_pair_outcomes`` et ``load_sensitivity`` (M4d-3), sur la sensibilité de
    ``just backtest`` du monde : relus du registre, égaux à ce que l'exécution a
    produit, paire par paire ; ``None`` et vide pour le RÉSULTAT central."""
    world = backtest_sensitivity(tmp_path_factory)
    log = read_registry(world.registry)
    produced = world.run.evaluation
    assert load_pair_outcomes(world.registry, log, 4) == tuple(
        PairOutcome(*pair.pair, pair.outcomes, pair.unscored, pair.references)
        for pair in produced.pairs
    )
    assert load_sensitivity(world.registry, log, 4) == produced.outcome
    assert load_sensitivity(world.registry, log, 2) is None
    assert load_pair_outcomes(world.registry, log, 2) == ()


def test_two_sensitivities_of_one_central(tmp_path: Path) -> None:
    """Exception de D14 (M4d-3) : une centrale peut recevoir plusieurs sensibilités,
    chacune comptée à part ; chacune qualifie la même centrale, la seconde ne touche
    ni la centrale ni la première."""
    root = _sensitivity_registry(tmp_path)
    before = (root / EVENTS_FILE).read_bytes()
    append_declaration(root, _sensitivity_of(root), recorded_at=at(4))
    _answer(root, 5, minutes=5)
    log = verify_registry(root)
    assert [e.kind for e in log.events] == [
        EventKind.DECLARATION,
        EventKind.RESULT,
    ] * 3
    assert (root / EVENTS_FILE).read_bytes().startswith(before)
    for number in (3, 5):
        declared = log.event(number).declaration
        assert declared is not None
        assert declared.sensitivity is not None
        assert (declared.sensitivity.central, declared.sensitivity.answer) == (1, 2)
        assert log.answer(number) == log.event(number + 1)
    trials = count_trials(log)
    assert (trials.declarations, trials.without_effect, trials.sensitivities) == (
        3,
        1,
        2,
    )
    assert load_sensitivity(root, log, 6) == load_sensitivity(root, log, 4)
