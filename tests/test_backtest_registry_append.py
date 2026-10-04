"""Ajouts refusés (§ 6.3, § 7.4 et § 8.1, test 9, du brief M4b-4 ; ``0010`` D14, D0,
D2.6, D3).

Chaque refus d'ajout du § 7.4, en ``RegistryError`` de type exact et son message, et
**rien n'est écrit** : journal identique octet pour octet, aucun document ajouté (même
quand le défaut n'est pas sur le premier document), plus de verrou pris par l'ajout.
Chaque ordre prescrit, par une entrée qui viole deux règles ; et les acceptations
voisines.
"""

import re
from collections.abc import Callable
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

import pytest

from fixtures import scoring
from fixtures.registry import (
    CALIBRATED_MODELS,
    OUTINGS,
    P03,
    Q20,
    Q27,
    REFERENCE_R1,
    V0_RAW,
    at,
    curve,
    declaration,
    experiment,
    outcome,
    outcomes,
    references,
    registry_root,
)
from fixtures.repeatability import case_reference
from mountain_perf.backtest import (
    DOCUMENT_SUFFIX,
    DOCUMENTS_DIR,
    EVENTS_FILE,
    LOCK_FILE,
    RegistryError,
    append_declaration,
    append_result,
    content_hash,
    declared_performance,
    encode_document,
    read_registry,
)
from mountain_perf.model.engine import ENGINE_VERSION, PROJECTION_PARAMETER_SPECS
from mountain_perf.schemas import (
    DeclaredModel,
    Exclusion,
    ModelKind,
    OutingOutcome,
    OutingScores,
    ParameterSet,
    Performance,
    ScenarioScores,
    SourceRef,
)
from test_backtest_registry import snapshot

Q20_ID, Q27_ID, P03_ID = (outing.outing_id for outing in OUTINGS)


def _refused(root: Path, fragment: str, append: Callable[[], object]) -> None:
    """Le refus attendu, et rien n'est écrit."""
    before = snapshot(root)
    with pytest.raises(RegistryError, match=re.escape(fragment)):
        append()
    assert snapshot(root) == before


def _declared(tmp_path: Path, **changes: object) -> Path:
    """Un registre qui porte ``declaration(**changes)`` à ``at(0)``."""
    tmp_path.mkdir(exist_ok=True)
    root = registry_root(tmp_path)
    append_declaration(root, declaration(**changes), recorded_at=at(0))
    return root


def _on(scores: ScenarioScores, source: SourceRef) -> ScenarioScores:
    return replace(scores, forecast=replace(scores.forecast, source=source))


def _with(
    outcomes_: tuple[OutingOutcome, ...], *extra: OutingOutcome
) -> tuple[OutingOutcome, ...]:
    return (*outcomes_, *extra)


def _scored(outing_id: str, scores: OutingScores) -> OutingOutcome:
    coverage = outcome(outing_id).coverage
    return OutingOutcome(outing_id, coverage, ((ModelKind.V0_RAW, scores),))


def _replaced(scored: OutingOutcome) -> tuple[OutingOutcome, ...]:
    """``outcomes()`` où la sortie de ``scored`` est remplacée par ``scored``."""
    return tuple(
        scored if item.outing_id == scored.outing_id else item for item in outcomes()
    )


# ---------------------------------------------------------------------------
# Dossier, verrou, heure, documents altérés
# ---------------------------------------------------------------------------


def test_lock_of_another_append(tmp_path: Path) -> None:
    """§ 6.3, étape 2 : un verrou présent refuse l'ajout ; il est laissé en place (le
    retirer laisserait deux ajouts écrire le même numéro)."""
    root = _declared(tmp_path)
    (root / LOCK_FILE).write_bytes(b"")
    _refused(
        root,
        "registre verrouillé : le fichier « verrou » existe. Si aucun ajout n'est en "
        "cours (plantage), le supprimer à la main.",
        lambda: append_result(root, 1, outcomes(), recorded_at=at(1)),
    )
    assert (root / LOCK_FILE).exists()


def test_no_lock_after_an_append_accepted_or_refused(tmp_path: Path) -> None:
    root = _declared(tmp_path)
    assert not (root / LOCK_FILE).exists()
    append_result(root, 1, outcomes(), references=references(), recorded_at=at(1))
    assert not (root / LOCK_FILE).exists()
    _refused(
        root,
        "déjà une réponse",
        lambda: append_result(root, 1, outcomes(), recorded_at=at(2)),
    )
    assert not (root / LOCK_FILE).exists()


def test_parent_of_the_root_must_exist(tmp_path: Path) -> None:
    """§ 6.3, étape 1 : le dossier du registre est créé, jamais son parent."""
    root = tmp_path / "a" / "b"
    with pytest.raises(RegistryError, match=re.escape("dossier parent")):
        append_declaration(root, declaration(), recorded_at=at(0))
    assert not (tmp_path / "a").exists()


def test_time_does_not_go_back(tmp_path: Path) -> None:
    """D14 : l'heure d'enregistrement ne recule pas (égale permise)."""
    root = registry_root(tmp_path)
    append_declaration(root, declaration(), recorded_at=at(5))
    _refused(
        root,
        "précède celui de l'événement 1",
        lambda: append_declaration(root, declaration(), recorded_at=at(4)),
    )
    assert append_declaration(root, declaration(), recorded_at=at(5)).number == 2


@pytest.mark.parametrize(
    "name", ["Régimes", "Passages"], ids=["first-document", "fourth-document"]
)
def test_altered_document_already_present(tmp_path: Path, name: str) -> None:
    """§ 6.3, étape 7 : tous les documents présents sont contrôlés avant d'en écrire
    un seul ; un document altéré, où qu'il soit, et aucun document n'est ajouté."""
    root = _declared(tmp_path)
    outing_id = Q20_ID if name == "Régimes" else Q27_ID
    observation = outcome(outing_id).scores[0][1].observation
    sha = content_hash(encode_document(observation))
    (root / DOCUMENTS_DIR).mkdir()
    (root / DOCUMENTS_DIR / f"{sha}{DOCUMENT_SUFFIX}").write_bytes(b"{}")
    _refused(
        root,
        f"ajout refusé : {DOCUMENTS_DIR}/{sha}{DOCUMENT_SUFFIX} : document altéré "
        "(empreinte différente) ; rien n'est écrit",
        lambda: append_result(root, 1, outcomes(), references=references()),
    )


# ---------------------------------------------------------------------------
# Accord sans documents (D0, D3)
# ---------------------------------------------------------------------------


def test_declared_outing_without_fate(tmp_path: Path) -> None:
    """D0 : chaque sortie déclarée est scorée ou écartée avec un motif."""
    root = _declared(tmp_path)
    _refused(
        root,
        "ajout refusé : la sortie déclarée 'p-2026-06-03' n'est ni scorée ni écartée "
        "avec un motif",
        lambda: append_result(root, 1, outcomes()[:2]),
    )
    unscored = (Exclusion(P03_ID, "trace illisible"),)
    event = append_result(root, 1, outcomes()[:2], unscored=unscored)
    assert event.result is not None
    assert event.result.unscored == unscored


def test_undeclared_outing(tmp_path: Path) -> None:
    root = _declared(tmp_path)
    _refused(
        root,
        "ajout refusé : sortie non déclarée, 'x'",
        lambda: append_result(root, 1, outcomes(), unscored=(Exclusion("x", "motif"),)),
    )
    stranger = replace(outcome(Q20_ID), outing_id="z")
    _refused(
        root,
        "ajout refusé : sortie non déclarée, 'z'",
        lambda: append_result(root, 1, _with(outcomes(), stranger)),
    )


def test_undeclared_model(tmp_path: Path) -> None:
    root = _declared(tmp_path)
    scores = outcome(Q20_ID).scores[0][1]
    naismith = replace(outcome(Q20_ID), scores=((ModelKind.NAISMITH, scores),))
    _refused(
        root,
        "ajout refusé : modèle non déclaré, naismith",
        lambda: append_result(root, 1, _replaced(naismith)),
    )


def test_usage_if_and_only_if_reference(tmp_path: Path) -> None:
    """D3 : le scénario usage existe si et seulement si la sortie a une référence."""
    root = _declared(tmp_path)
    regimes = scoring.scores("Régimes")
    assert regimes.usage is not None
    with_usage = OutingScores(
        regimes.observation,
        _on(regimes.control, P03.traces[0].source),
        _on(regimes.usage, REFERENCE_R1.artifact.source),
    )
    _refused(
        root,
        "ajout refusé : 'p-2026-06-03', le scénario usage est présent si et seulement "
        "si la sortie a une référence (D3)",
        lambda: append_result(root, 1, _replaced(_scored(P03_ID, with_usage))),
    )
    without = scoring.scores("Régimes sans référence")
    without_usage = replace(without, control=_on(without.control, Q20.traces[0].source))
    _refused(
        root,
        "ajout refusé : 'q-2026-05-20', le scénario usage",
        lambda: append_result(root, 1, _replaced(_scored(Q20_ID, without_usage))),
    )


def test_scored_outing_without_trace(tmp_path: Path) -> None:
    """D0 : une sortie non tracée s'écarte avec un motif ; scorée, elle est refusée."""
    untraced = replace(P03, traces=())
    performances = tuple(
        declared_performance(Performance(outing.start_time.date(), (outing,)))
        for outing in (Q20, Q27, untraced)
    )
    root = _declared(tmp_path, performances=performances)
    _refused(
        root,
        "ajout refusé : 'p-2026-06-03', une sortie scorée a au moins une trace",
        lambda: append_result(root, 1, outcomes()),
    )
    unscored = (Exclusion(P03_ID, "sortie non tracée"),)
    assert append_result(root, 1, outcomes()[:2], unscored=unscored).number == 2


@pytest.mark.parametrize(
    ("route_id", "case", "fragment"),
    [
        ("r9", "Deux jours", "ajout refusé : parcours non déclaré, 'r9'"),
        (
            "r1",
            "Multi-sorties",
            "ajout refusé : la référence de 'r1' porte un jour non déclaré sur ce "
            "parcours, 2026-05-24",
        ),
        (
            "r2",
            "Deux jours",
            "ajout refusé : la référence de 'r2' porte un jour non déclaré sur ce "
            "parcours, 2026-05-20",
        ),
    ],
    ids=["route-r9", "multi-outing-day", "days-of-r1-under-r2"],
)
def test_undeclared_route_and_days_of_a_d8_reference(
    tmp_path: Path, route_id: str, case: str, fragment: str
) -> None:
    """D14 : une référence D8 porte sur un parcours déclaré, et sur des jours (éligibles
    puis multi-sorties) déclarés sur ce parcours."""
    root = _declared(tmp_path)
    pair = ((route_id, case_reference(case)),)
    _refused(
        root, fragment, lambda: append_result(root, 1, outcomes(), references=pair)
    )


# ---------------------------------------------------------------------------
# Accord par les documents (D14, D2.6)
# ---------------------------------------------------------------------------


def test_engine_version_of_the_forecasts(tmp_path: Path) -> None:
    """Précision de D14 : les prévisions recopient la version déclarée."""
    root = _declared(
        tmp_path, models=(replace(V0_RAW, engine_version="projection-v1"),)
    )
    _refused(
        root,
        "version du moteur différente de la déclaration",
        lambda: append_result(root, 1, outcomes()),
    )


def test_parameters_of_a_model_without_rule(tmp_path: Path) -> None:
    """Précision de D14 : les paramètres fixés sont recopiés ; un modèle à règle
    d'estimation apprend les siens."""
    effort = ParameterSet(PROJECTION_PARAMETER_SPECS, {"effort": 1.1})
    root = _declared(tmp_path, models=(replace(V0_RAW, parameters=effort),))
    _refused(
        root,
        "paramètres différents des paramètres déclarés",
        lambda: append_result(root, 1, outcomes()),
    )
    ruled = replace(V0_RAW, parameters=effort, estimation_rule="calage de 0010 D9.2")
    other = _declared(tmp_path / "règle", models=(ruled,))
    assert append_result(other, 1, outcomes()).number == 2


def test_forecasts_name_declared_files_of_their_outing(tmp_path: Path) -> None:
    """Précision de D14 : la prévision de contrôle nomme la première trace déclarée de
    sa sortie, celle d'usage sa référence déclarée."""
    root = _declared(tmp_path)
    regimes = scoring.scores("Régimes")
    _refused(
        root,
        "ajout refusé : 'q-2026-05-20', v0_raw, control : la prévision ne nomme pas la "
        "première trace déclarée de la sortie",
        lambda: append_result(root, 1, _replaced(_scored(Q20_ID, regimes))),
    )
    assert regimes.usage is not None
    on_q27 = OutingScores(
        regimes.observation,
        _on(regimes.control, Q20.traces[0].source),
        _on(regimes.usage, Q27.traces[0].source),
    )
    _refused(
        root,
        "ajout refusé : 'q-2026-05-20', v0_raw, usage : la prévision ne nomme pas la "
        "référence déclarée de la sortie",
        lambda: append_result(root, 1, _replaced(_scored(Q20_ID, on_q27))),
    )


def test_curve_of_the_forecasts(tmp_path: Path) -> None:
    """Précision de D14 : les modèles qui projettent avec la courbe la recopient ; une
    baseline ne la recopie pas."""
    csv, meta = curve()
    other = replace(csv, source=replace(csv.source, content_hash="1" * 64))
    changes: dict[str, object] = {
        "curve": other,
        "curve_metadata": meta,
        "curve_ref": "courbe_synthetique.csv#111111111111",
    }
    root = _declared(tmp_path, **changes)
    _refused(
        root,
        "courbe différente de la déclaration",
        lambda: append_result(root, 1, outcomes()),
    )
    naismith = DeclaredModel(
        ModelKind.NAISMITH,
        ENGINE_VERSION,
        ParameterSet(PROJECTION_PARAMETER_SPECS),
        None,
    )
    baseline = _declared(tmp_path / "baseline", models=(naismith,), **changes)
    scored = tuple(
        replace(item, scores=((ModelKind.NAISMITH, item.scores[0][1]),))
        for item in outcomes()
    )
    assert append_result(baseline, 1, scored).number == 2


# ---------------------------------------------------------------------------
# Écrit, donc relu : refus de l'écriture canonique (étapes 0 et 4)
# ---------------------------------------------------------------------------


def test_lone_surrogate_in_the_result_line(tmp_path: Path) -> None:
    """§ 6.2, étape 4 : la ligne s'écrit en mémoire avant toute écriture ; rien n'est
    écrit, aucun document compris."""
    root = _declared(tmp_path)
    unscored = (Exclusion(P03_ID, "trace \udcff illisible"),)
    _refused(
        root,
        "ajout refusé : result.unscored[0].reason : un texte doit s'encoder en UTF-8",
        lambda: append_result(root, 1, outcomes()[:2], unscored=unscored),
    )
    assert not (root / DOCUMENTS_DIR).exists()


def test_datetime_for_the_analysis_date(tmp_path: Path) -> None:
    """§ 6.2, étape 4 : une ``datetime`` pour une ``date``, que le contrat accepte, est
    refusée à l'écriture ; rien n'est écrit, et le registre se relit (D10.7)."""
    root = _declared(tmp_path)
    dated = experiment(analysis_date=datetime(2026, 12, 1, tzinfo=UTC))
    declared = declaration(models=CALIBRATED_MODELS, experiment=dated)
    _refused(
        root,
        "ajout refusé : declaration.experiment.analysis_date : ",
        lambda: append_declaration(root, declared, recorded_at=at(1)),
    )
    assert len(read_registry(root).events) == 1


def test_lone_surrogate_in_a_document(tmp_path: Path) -> None:
    """§ 6.3, étape 0 : une ``CodecError`` de l'écriture d'un document devient « ajout
    refusé »."""
    root = _declared(tmp_path)
    two_days = case_reference("Deux jours")
    renamed = replace(
        two_days, reference=replace(two_days.reference, identifier="parcours\udcff.gpx")
    )
    _refused(
        root,
        "ajout refusé : reference.identifier : un texte doit s'encoder en UTF-8",
        lambda: append_result(root, 1, outcomes(), references=(("r1", renamed),)),
    )


# ---------------------------------------------------------------------------
# Ordres prescrits
# ---------------------------------------------------------------------------


def test_undeclared_outing_before_forgotten_outing(tmp_path: Path) -> None:
    """§ 6.3 : une sortie non déclarée se signale avant une sortie oubliée."""
    root = _declared(tmp_path)
    _refused(
        root,
        "ajout refusé : sortie non déclarée, 'x'",
        lambda: append_result(
            root, 1, outcomes()[:2], unscored=(Exclusion("x", "motif"),)
        ),
    )


def test_lock_before_reading(tmp_path: Path) -> None:
    """§ 6.3 : le verrou se prend avant la relecture du registre."""
    root = _declared(tmp_path)
    (root / LOCK_FILE).write_bytes(b"")
    data = (root / EVENTS_FILE).read_bytes()
    (root / EVENTS_FILE).write_bytes(data[:-1])
    _refused(
        root,
        "registre verrouillé",
        lambda: append_result(root, 1, outcomes()),
    )


def test_declaration_with_an_experiment_is_accepted(tmp_path: Path) -> None:
    """D10.1, D10.7 : la déclaration complète d'une expérience, date d'analyse
    comprise."""
    root = registry_root(tmp_path)
    dated = experiment(analysis_date=datetime(2026, 12, 1, tzinfo=UTC).date())
    declared = declaration(models=CALIBRATED_MODELS, experiment=dated)
    event = append_declaration(root, declared, recorded_at=at(0))
    assert read_registry(root).events == (event,)
