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
