"""Garanties du registre au format 5 (M4d-3 ; ``0010`` D14, sa précision et son
exception) que les tests joints ne tenaient pas — correctifs de la relecture de la
PR #32 (relecture C en deux passes).

- L'invariant 5 de ``RegistryLog``, clauses 1 et 3 : le RÉSULTAT que nomme une
  DÉCLARATION de sensibilité la précède, et répond à la centrale.
- La relecture contrôle les documents d'un RÉSULTAT de sensibilité : ceux de chaque
  paire, et le document de sensibilité.
- Les contrats de la DÉCLARATION de sensibilité d'une expérience : une entrée de
  ``frozen`` par configuration, dans l'ordre ; chaque référence figée sous l'horloge de
  sa configuration.
- Chaque paire d'un RÉSULTAT de sensibilité accordée comme le RÉSULTAT d'une exécution,
  fourchettes comprises : une sortie de ``just backtest`` sans ses fourchettes, une
  sortie d'une expérience qui en cite, refusées.
- L'exception de D14 : une DÉCLARATION qui change le ``K``, l'horloge déclarée ou les
  seuls paramètres du candidat n'est pas une DÉCLARATION de sensibilité.

Les registres : les fixtures de ``fixtures.registry`` (les aides de
``test_backtest_registry_format5.py``), et les sensibilités du monde
(``fixtures.sensitivity_world``), copiées. Aucune donnée réelle.
"""

import re
from collections.abc import Callable
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest

from fixtures.registry import (
    CALIBRATED_MODELS,
    at,
    declaration,
    outcomes,
    references,
    registry_root,
)
from fixtures.registry import experiment as declared_experiment
from fixtures.sensitivity_world import (
    SENSITIVITY_RECORDED_AT,
    BacktestSensitivity,
    ExperimentSensitivity,
    backtest_sensitivity,
    copy_registry,
    experiment_sensitivity,
)
from mountain_perf.backtest import (
    DOCUMENTS_DIR,
    EVENTS_FILE,
    SENSITIVITY_CONFIGURATIONS,
    PairEvaluation,
    PairOutcome,
    RegistryError,
    append_declaration,
    append_result,
    line_hash,
    read_registry,
)
from mountain_perf.schemas import (
    CLOCKS,
    ConfigurationReferences,
    ContractError,
    Declaration,
    DeclaredUsageTarget,
    ExperimentMetric,
    OutingBands,
    OutingOutcome,
    ParameterSet,
    ParameterSpec,
    RegistryEvent,
    RegistryLog,
    SensitivityConfiguration,
    TargetMember,
)
from test_backtest_registry_format3 import (
    _admission,
    _experiment,
    _experiment_outcomes,
    _experiment_registry,
    _journal,
)
from test_backtest_registry_format5 import (
    RECOPY,
    _central,
    _line,
    _refused_append,
    _sensitivity_of,
    _write_declaration,
)

OTHER_PAIR = (100.0, 15.0)
"""Une paire autre que la centrale."""


@pytest.fixture(scope="module")
def world(tmp_path_factory: pytest.TempPathFactory) -> BacktestSensitivity:
    """La sensibilité de ``just backtest`` sur le monde."""
    return backtest_sensitivity(tmp_path_factory)


@pytest.fixture(scope="module")
def elapsed(tmp_path_factory: pytest.TempPathFactory) -> ExperimentSensitivity:
    """L'expérience du monde déclarée sous l'écoulé, et sa sensibilité."""
    return experiment_sensitivity(tmp_path_factory, "ecoule")


def _declaration(event: RegistryEvent) -> Declaration:
    assert event.declaration is not None
    return event.declaration


# ---------------------------------------------------------------------------
# L'invariant 5 de RegistryLog, clauses 1 et 3
# ---------------------------------------------------------------------------


def _event(base: RegistryEvent, number: int, declared: Declaration) -> RegistryEvent:
    return replace(
        base,
        number=number,
        recorded_at=at(number),
        previous_hash="0" * 64,
        declaration=declared,
    )


@pytest.mark.parametrize("answer", [3, 4], ids=["elle-meme", "au-dela"])
def test_sensitivity_naming_an_answer_that_does_not_precede_it(
    tmp_path: Path, answer: int
) -> None:
    """Invariant 5 de ``RegistryLog`` (M4d-3), clause 1 : une DÉCLARATION de
    sensibilité nomme un RÉSULTAT qui la précède — elle-même, ou un événement au-delà
    du journal, est refusée par le contrat, avec son motif."""
    root = _central(tmp_path)
    log = read_registry(root)
    forged = _sensitivity_of(root)
    assert forged.sensitivity is not None
    changed = replace(forged, sensitivity=replace(forged.sensitivity, answer=answer))
    with pytest.raises(
        ContractError,
        match=re.escape(
            f"la DÉCLARATION de sensibilité 3 nomme l'événement {answer}, qui ne la "
            "précède pas."
        ),
    ):
        RegistryLog((*log.events, _event(log.events[0], 3, changed)))


def _naming_another_result(tmp_path: Path) -> tuple[Path, Declaration]:
    """Une centrale (1, 2), une autre exécution (3, 4), et une DÉCLARATION de
    sensibilité de la centrale 1 qui nomme le RÉSULTAT 4 (empreinte exacte)."""
    root = _central(tmp_path)
    append_declaration(root, declaration(), recorded_at=at(2))
    append_result(root, 3, outcomes(), references=references(), recorded_at=at(3))
    log = read_registry(root)
    forged = _sensitivity_of(root, 1, 2)
    assert forged.sensitivity is not None
    changed = replace(
        forged,
        sensitivity=replace(
            forged.sensitivity, answer=4, answer_hash=line_hash(log.events[3])
        ),
    )
    return root, changed


ANOTHER_RESULT = (
    "la DÉCLARATION de sensibilité 5 nomme l'événement 4, qui n'est pas un RÉSULTAT "
    "de la déclaration 1."
)


def test_sensitivity_naming_the_result_of_another_declaration(tmp_path: Path) -> None:
    """Invariant 5 de ``RegistryLog`` (M4d-3), clause 3 : le RÉSULTAT nommé répond à la
    centrale — celui d'une autre DÉCLARATION est refusé par le contrat."""
    root, changed = _naming_another_result(tmp_path)
    log = read_registry(root)
    with pytest.raises(ContractError, match=re.escape(ANOTHER_RESULT)):
        RegistryLog((*log.events, _event(log.events[0], 5, changed)))


def test_line_naming_the_result_of_another_declaration_is_refused_on_reading(
    tmp_path: Path,
) -> None:
    """La même DÉCLARATION écrite à la main, sans l'accord de l'ajout : la relecture la
    refuse (l'accord ne vérifie « en vigueur » qu'à l'ajout ; c'est l'invariant 5 qui
    la voit à la relecture)."""
    root, changed = _naming_another_result(tmp_path)
    _write_declaration(root, changed)
    with pytest.raises(
        RegistryError, match=re.escape(f"{EVENTS_FILE} : {ANOTHER_RESULT}")
    ):
        read_registry(root)


# ---------------------------------------------------------------------------
# Les documents d'un RÉSULTAT de sensibilité, à la relecture
# ---------------------------------------------------------------------------


def _cited_by_the_central(log: RegistryLog) -> set[str]:
    central = log.events[1].result
    assert central is not None
    cited = {record.reference for record in central.references}
    for outing in central.outings:
        cited.add(outing.observation)
        if outing.bands is not None:
            cited.add(outing.bands)
        for model in outing.models:
            cited.add(model.control)
            if model.usage is not None:
                cited.add(model.usage)
    return cited


@pytest.mark.parametrize("kind", ["observation", "scores", "fourchettes", "d8"])
def test_altered_document_of_a_pair_is_refused_on_reading(
    tmp_path: Path, world: BacktestSensitivity, kind: str
) -> None:
    """Précision de D14 (M4d-3) : chaque document cité par une paire du RÉSULTAT de
    sensibilité est présent et intact à la relecture (``read_registry``, celle que
    tout ajout refait) — un document de la paire ``(100, 15)``, cité par elle seule,
    altéré après l'écriture, est refusé."""
    root = copy_registry(world.registry, tmp_path / "registre")
    log = read_registry(root)
    result = log.events[3].result
    assert result is not None
    pair = result.pairs[0]
    assert (pair.score_step_m, pair.lateral_tolerance_m) == OTHER_PAIR
    central = _cited_by_the_central(log)
    if kind == "d8":
        candidates: list[str | None] = [record.reference for record in pair.references]
    else:
        candidates = [
            {
                "observation": scored.observation,
                "scores": scored.models[0].control,
                "fourchettes": scored.bands,
            }[kind]
            for scored in pair.outings
        ]
    own = [c for c in candidates if c is not None and c not in central]
    assert own
    sha = own[0]
    path = root / DOCUMENTS_DIR / f"{sha}.json"
    path.write_bytes(path.read_bytes() + b" ")
    with pytest.raises(
        RegistryError, match=re.escape(f"documents/{sha}.json : document altéré")
    ):
        read_registry(root)


def test_missing_sensitivity_document_is_refused_on_reading(
    tmp_path: Path, world: BacktestSensitivity
) -> None:
    """Précision de D14 (M4d-3) : le document de sensibilité, cité par le RÉSULTAT, est
    présent à la relecture — absent, le registre est refusé."""
    root = copy_registry(world.registry, tmp_path / "registre")
    result = read_registry(root).events[3].result
    assert result is not None
    sha = result.sensitivity
    assert sha is not None
    (root / DOCUMENTS_DIR / f"{sha}.json").unlink()
    with pytest.raises(
        RegistryError, match=re.escape(f"documents/{sha}.json : document introuvable")
    ):
        read_registry(root)


# ---------------------------------------------------------------------------
# Les contrats de la DÉCLARATION de sensibilité d'une expérience
# ---------------------------------------------------------------------------


FROZEN_ENTRIES = (
    "frozen porte une entrée par configuration, dans l'ordre des configurations."
)


@pytest.mark.parametrize("change", ["sans-la-derniere", "ordre"])
def test_frozen_has_one_entry_per_configuration_in_order(
    tmp_path: Path, change: str
) -> None:
    """Invariant 4 de ``SensitivityDeclaration`` (M4d-3) : ``frozen`` porte une entrée
    par configuration, de cette configuration, dans l'ordre — une entrée en moins, ou
    deux entrées échangées, sont refusées par le contrat ; et une ligne relue qui en
    perd une, avec le motif du contrat."""
    declared = _sensitivity_of(_experiment_registry(tmp_path))
    sensitivity = declared.sensitivity
    assert sensitivity is not None
    frozen = sensitivity.frozen
    assert frozen is not None
    assert [e.configuration for e in frozen] == list(SENSITIVITY_CONFIGURATIONS)
    changed = (
        frozen[:-1]
        if change == "sans-la-derniere"
        else (frozen[1], frozen[0], *frozen[2:])
    )
    with pytest.raises(ContractError, match=re.escape(FROZEN_ENTRIES)):
        replace(sensitivity, frozen=changed)
    (tmp_path / "relue").mkdir()
    root = _experiment_registry(tmp_path / "relue")
    append_declaration(root, _sensitivity_of(root), recorded_at=at(2))

    def without_the_last(data: dict[str, Any]) -> None:
        if data["number"] == 3:
            data["declaration"]["sensitivity"]["frozen"].pop()

    _journal(root, without_the_last)
    with pytest.raises(RegistryError, match=re.escape(_line(3) + FROZEN_ENTRIES)):
        read_registry(root)


def test_frozen_references_are_under_the_configuration_clock() -> None:
    """Invariant de ``ConfigurationReferences`` (M4d-3) : chaque référence figée d'une
    configuration est sous l'horloge de la configuration — une référence sous une autre
    horloge est refusée par le contrat ; sous la sienne, acceptée."""
    frozen = declared_experiment().frozen_references
    assert {reference.clock for reference in frozen} == {CLOCKS[0]}
    moving = SensitivityConfiguration(250.0, 30.0, 15.0, CLOCKS[3])
    with pytest.raises(
        ContractError,
        match=re.escape(
            f"la référence figée 0 est sous {CLOCKS[0]}, l'horloge de la configuration "
            f"({CLOCKS[3]}) attendue."
        ),
    ):
        ConfigurationReferences(moving, frozen)
    elapsed = SensitivityConfiguration(250.0, 30.0, 15.0, CLOCKS[0])
    assert ConfigurationReferences(elapsed, frozen).frozen_references == frozen


# ---------------------------------------------------------------------------
# Chaque paire accordée comme le RÉSULTAT d'une exécution : les fourchettes
# ---------------------------------------------------------------------------


BANDS_RULE = (
    "une sortie scorée cite ses fourchettes si et seulement si elle a une référence, "
    "que les cinq modèles du rapport sont déclarés et qu'il n'y a pas d'expérience "
    "(M4d-2)"
)


def _central_only(registry: Path, target: Path) -> Path:
    """Une copie du registre ``registry`` réduite à ses deux premiers événements (la
    centrale et sa réponse) ; ses documents restent."""
    root = copy_registry(registry, target)
    lines = (root / EVENTS_FILE).read_bytes().split(b"\n")[:2]
    (root / EVENTS_FILE).write_bytes(b"".join(line + b"\n" for line in lines))
    return root


def _bands_of(world: BacktestSensitivity) -> dict[str, OutingBands]:
    """Les fourchettes des sorties de ``(100, 15)`` dans la sensibilité de ``just
    backtest`` du monde (ses sorties à référence)."""
    (pair,) = [p for p in world.run.evaluation.pairs if p.pair == OTHER_PAIR]
    bands = {o.outing_id: o.bands for o in pair.outcomes if o.bands is not None}
    assert bands
    return bands


def _changed(
    pairs: tuple[PairEvaluation, ...],
    outing_id: str,
    change: Callable[[OutingOutcome], OutingOutcome],
) -> tuple[PairOutcome, ...]:
    """Les paires d'une sensibilité, la sortie ``outing_id`` de ``(100, 15)`` changée
    par ``change``."""
    return tuple(
        PairOutcome(
            *evaluated.pair,
            tuple(
                change(outcome)
                if evaluated.pair == OTHER_PAIR and outcome.outing_id == outing_id
                else outcome
                for outcome in evaluated.outcomes
            ),
            evaluated.unscored,
            evaluated.references,
        )
        for evaluated in pairs
    )


def test_backtest_pair_outing_without_its_bands_is_refused(
    tmp_path: Path, world: BacktestSensitivity
) -> None:
    """Précision de D14 (M4d-3) : chaque paire est accordée « comme le RÉSULTAT d'une
    exécution », fourchettes comprises — pour ``just backtest``, une sortie scorée à
    référence d'une paire qui ne cite pas ses fourchettes est refusée à l'ajout ; rien
    n'est écrit."""
    root = copy_registry(world.central_only, tmp_path / "registre")
    declared = world.run.evaluation.declaration_event
    append_declaration(
        root, _declaration(declared), recorded_at=SENSITIVITY_RECORDED_AT
    )
    outing_id = next(iter(_bands_of(world)))
    pairs = _changed(
        world.run.evaluation.pairs,
        outing_id,
        lambda outcome: replace(outcome, bands=None),
    )
    _refused_append(
        root,
        lambda: append_result(
            root,
            3,
            (),
            pairs=pairs,
            sensitivity=world.run.evaluation.outcome,
            recorded_at=SENSITIVITY_RECORDED_AT,
        ),
        f"paire (100, 15), {outing_id!r}, {BANDS_RULE}",
    )


def test_experiment_pair_outing_citing_bands_is_refused(
    tmp_path: Path, world: BacktestSensitivity, elapsed: ExperimentSensitivity
) -> None:
    """Précision de D14 (M4d-3) : pour une expérience, aucune sortie d'une paire ne
    cite de fourchettes — une sortie qui en cite (celles de la même sortie dans la
    sensibilité de ``just backtest``) est refusée à l'ajout ; rien n'est écrit."""
    root = _central_only(elapsed.registry, tmp_path / "registre")
    declared = elapsed.run.evaluation.declaration_event
    append_declaration(
        root, _declaration(declared), recorded_at=SENSITIVITY_RECORDED_AT
    )
    outing_id, bands = next(iter(_bands_of(world).items()))
    pairs = _changed(
        elapsed.run.evaluation.pairs,
        outing_id,
        lambda outcome: replace(outcome, bands=bands),
    )
    _refused_append(
        root,
        lambda: append_result(
            root,
            3,
            (),
            pairs=pairs,
            sensitivity=elapsed.run.evaluation.outcome,
            recorded_at=SENSITIVITY_RECORDED_AT,
        ),
        f"paire (100, 15), {outing_id!r}, {BANDS_RULE}",
    )


# ---------------------------------------------------------------------------
# L'exception de D14 : K, horloge déclarée, paramètres du candidat
# ---------------------------------------------------------------------------


FACTOR = ParameterSpec("factor", None, 1.0, 0.5, 1.5, "Facteur inventé.")
"""Un paramètre d'effet inventé."""
K_R1 = DeclaredUsageTarget("r1", (TargetMember(0, False),), None)
"""Un ``K`` déclaré sur ``r1`` : son premier lieu nommé seul."""


def _usage_registry(tmp_path: Path) -> Path:
    """Une expérience de cible ``q_usage`` à ``K`` déclaré (``K_R1``), et son RÉSULTAT
    cohérent."""
    root = registry_root(tmp_path)
    experiment = _experiment(target=ExperimentMetric.USAGE, usage_targets=(K_R1,))
    append_declaration(
        root,
        declaration(models=CALIBRATED_MODELS, experiment=experiment),
        recorded_at=at(0),
    )
    append_result(
        root,
        1,
        _experiment_outcomes(),
        references=references(),
        admission=_admission(ExperimentMetric.USAGE),
        recorded_at=at(1),
    )
    return root


RECOPY_CASES: dict[str, tuple[Callable[[Path], Path], dict[str, Any]]] = {
    "k": (_usage_registry, {"usage_targets": ()}),
    "horloge": (_experiment_registry, {"clock": CLOCKS[3]}),
    "parametres": (
        _experiment_registry,
        {
            "effect": replace(
                declared_experiment().effect,
                parameters=ParameterSet((FACTOR,), {"factor": 1.2}),
            )
        },
    ),
}
"""Ce qu'une DÉCLARATION de sensibilité d'une expérience ne change pas non plus : le
registre de la centrale, et le changement de son expérience."""


@pytest.mark.parametrize("name", list(RECOPY_CASES))
def test_experiment_recopy_of_k_clock_and_parameters(tmp_path: Path, name: str) -> None:
    """Exception de D14 (M4d-3) : « une déclaration qui change autre chose — candidat,
    paramètres, cible, horloge déclarée, ``K`` […] — n'est pas une DÉCLARATION de
    sensibilité » — le ``K``, l'horloge déclarée ou les seuls paramètres du candidat
    changés : refusée à l'ajout et à la relecture, au motif de la recopie."""
    registry, changes = RECOPY_CASES[name]

    def forged(root: Path) -> Declaration:
        declared = _sensitivity_of(root)
        assert declared.experiment is not None
        return replace(declared, experiment=replace(declared.experiment, **changes))

    (tmp_path / "ajout").mkdir()
    (tmp_path / "relecture").mkdir()
    root = registry(tmp_path / "ajout")
    accepted = _sensitivity_of(root)
    assert forged(root) != accepted
    _refused_append(
        root, lambda: append_declaration(root, forged(root), recorded_at=at(2)), RECOPY
    )
    append_declaration(root, accepted, recorded_at=at(2))
    root = registry(tmp_path / "relecture")
    _write_declaration(root, forged(root))
    with pytest.raises(RegistryError, match=re.escape(_line(3) + RECOPY)):
        read_registry(root)
