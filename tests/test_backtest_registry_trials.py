"""Comptage des essais (§ 6.4, § 7.5 et § 8.1, test 11, du brief M4b-4 ; ``0010``
D14 ; décision 4).

Chaque DÉCLARATION compte pour un essai, corrections comprises ; un ÉCHEC ne compte
pas ; les exécutions sans effet à part ; les autres par couple effet × cible, ordonnés
par effet puis par rang de la cible dans ``ExperimentMetric``.
"""

from pathlib import Path

from fixtures.registry import (
    CALIBRATED_MODELS,
    at,
    declaration,
    experiment,
    registry_root,
)
from mountain_perf.backtest import (
    append_declaration,
    append_failure,
    count_trials,
    read_registry,
)
from mountain_perf.schemas import (
    DeclaredEffect,
    ExperimentMetric,
    ExperimentTrials,
    Failure,
    FailureKind,
    RegistryLog,
    TrialCounts,
)


def test_trial_counts_of_the_registry(tmp_path: Path) -> None:
    """§ 7.5 : cinq déclarations, dont une correction ; une sans effet ; « arrêts »
    deux fois sous ``|E_descente|`` (la correction compte), une fois sous
    ``D_descente`` ; « pente » une fois ; l'ÉCHEC ne compte pas."""
    root = registry_root(tmp_path)
    stops = declaration(models=CALIBRATED_MODELS, experiment=experiment())
    slope = declaration(
        models=CALIBRATED_MODELS,
        experiment=experiment(
            effect=DeclaredEffect("pente", "opérateur de pente", None, "règle"),
            target=ExperimentMetric.ASCENT_LEVEL,
            frozen_references=(),
        ),
    )
    dispersion = declaration(
        models=CALIBRATED_MODELS,
        experiment=experiment(
            target=ExperimentMetric.DESCENT_DISPERSION, frozen_references=()
        ),
    )
    append_declaration(root, declaration(), recorded_at=at(0))
    append_declaration(root, stops, recorded_at=at(1))
    append_declaration(
        root, stops, recorded_at=at(2), corrects=2, correction_reason="mauvaise horloge"
    )
    append_declaration(root, slope, recorded_at=at(3))
    append_declaration(root, dispersion, recorded_at=at(4))
    append_failure(
        root, 1, Failure(FailureKind.TECHNICAL, "plantage"), recorded_at=at(5)
    )
    assert count_trials(read_registry(root)) == TrialCounts(
        declarations=5,
        corrections=1,
        without_effect=1,
        by_experiment=(
            ExperimentTrials("arrêts", ExperimentMetric.DESCENT_LEVEL, 2),
            ExperimentTrials("arrêts", ExperimentMetric.DESCENT_DISPERSION, 1),
            ExperimentTrials("pente", ExperimentMetric.ASCENT_LEVEL, 1),
        ),
    )


def test_empty_registry_counts_nothing() -> None:
    assert count_trials(RegistryLog(())) == TrialCounts(0, 0, 0, ())


# ---------------------------------------------------------------------------
# Correctifs de la relecture de la PR #19
# ---------------------------------------------------------------------------


def test_corrective_answers_are_not_declaration_corrections(tmp_path: Path) -> None:
    """§ 6.4 : ``corrections`` compte les DÉCLARATIONS qui en corrigent une autre ; une
    réponse corrective (ici un ÉCHEC) n'y entre pas."""
    root = registry_root(tmp_path)
    append_declaration(root, declaration(), recorded_at=at(0))
    failure = Failure(FailureKind.TECHNICAL, "plantage")
    append_failure(root, 1, failure, recorded_at=at(1))
    append_failure(
        root,
        1,
        failure,
        recorded_at=at(2),
        corrects=2,
        correction_reason="motif complété",
    )
    assert count_trials(read_registry(root)) == TrialCounts(1, 0, 1, ())


def test_two_effects_of_the_same_name_are_one_effect(tmp_path: Path) -> None:
    """§ 6.1, ``DeclaredEffect`` : deux effets de même nom sont le même effet pour le
    comptage des essais, même décrits autrement."""
    root = registry_root(tmp_path)
    descriptions = ("temps d'arrêt ajouté aux passages", "arrêts, autre rédaction")
    for minutes, description in enumerate(descriptions):
        effect = DeclaredEffect("arrêts", description, None, "règle de D9.3")
        declared = declaration(
            models=CALIBRATED_MODELS, experiment=experiment(effect=effect)
        )
        append_declaration(root, declared, recorded_at=at(minutes))
    assert count_trials(read_registry(root)) == TrialCounts(
        2, 0, 0, (ExperimentTrials("arrêts", ExperimentMetric.DESCENT_LEVEL, 2),)
    )
