"""Aides des tests du registre (M4b-4) : une déclaration de v0 brut, ses résultats, une
expérience de M4c, toutes en valeurs inventées ou tirées des fixtures commitées."""

from __future__ import annotations

import dataclasses
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

from fixtures import scoring
from fixtures.repeatability import REFERENCE, DaySpec, case_reference, days_of
from mountain_perf.backtest import (
    MATCHING_PARAMETER_SPECS,
    curve_artifacts,
    declared_performance,
    repeatability_reference,
)
from mountain_perf.model.engine import ENGINE_VERSION, PROJECTION_PARAMETER_SPECS
from mountain_perf.schemas import (
    CLOCKS,
    ArtifactRef,
    ArtifactRole,
    CalibratedClockScores,
    CalibratedOutingScores,
    CalibratedScenarioScores,
    DataSet,
    Declaration,
    DeclaredEffect,
    DeclaredModel,
    DeclaredPerformance,
    DeclaredUsageTarget,
    Exclusion,
    ExperimentDeclaration,
    ExperimentMetric,
    FrozenReference,
    MetricValue,
    ModelCalibration,
    ModelKind,
    Outing,
    OutingLabel,
    OutingOutcome,
    OutingScores,
    ParameterSet,
    Performance,
    ReferenceKind,
    ReferenceSource,
    RepeatabilityReference,
    RouteReference,
    Scenario,
    ScenarioScores,
    SourceRef,
    Sport,
    TargetMember,
    Unavailability,
)

COMMIT = "0123456789abcdef0123456789abcdef01234567"
RETRIEVED_AT = datetime(2026, 10, 3, 12, 0, tzinfo=UTC)
RECORDED_AT = datetime(2026, 10, 3, 13, 0, tzinfo=UTC)
ATHLETE = "athlete-1"
CURVE_PATH = scoring.CURVE_PATH


def at(minutes: int) -> datetime:
    """``RECORDED_AT`` plus ``minutes`` minutes."""
    return RECORDED_AT + timedelta(minutes=minutes)


def _source(kind: str, identifier: str, digit: str) -> SourceRef:
    return SourceRef(kind, identifier, digit * 64, RETRIEVED_AT)


REFERENCE_R1 = RouteReference(
    ReferenceKind.PREPARED,
    ArtifactRef(
        _source("gpx", "parcours.gpx", "5"),
        datetime(2026, 5, 13, 0, 0, tzinfo=UTC),
        ArtifactRole.FORECAST_INPUT,
    ),
)


def _outing(
    outing_id: str,
    day: date,
    trace: str,
    digit: str,
    route: str,
    reference: RouteReference | None,
    dataset: DataSet,
) -> Outing:
    start = datetime(day.year, day.month, day.day, 8, 0, tzinfo=UTC)
    end = start + timedelta(hours=2)
    return Outing(
        outing_id=outing_id,
        athlete_ref=ATHLETE,
        sport=Sport.FOOT,
        start_time=start,
        end_time=end,
        traces=(
            ArtifactRef(
                _source("gpx", trace, digit), end, ArtifactRole.EVALUATION_OBSERVATION
            ),
        ),
        route_id=route,
        reference=reference,
        dataset=dataset,
        label=OutingLabel.TRAINING,
    )


Q20 = _outing(
    "q-2026-05-20",
    date(2026, 5, 20),
    "q20.gpx",
    "6",
    "r1",
    REFERENCE_R1,
    DataSet.REPEATABILITY,
)
Q27 = _outing(
    "q-2026-05-27",
    date(2026, 5, 27),
    "q27.gpx",
    "7",
    "r1",
    REFERENCE_R1,
    DataSet.REPEATABILITY,
)
P03 = _outing(
    "p-2026-06-03", date(2026, 6, 3), "p03.gpx", "8", "r2", None, DataSet.DEVELOPMENT
)
OUTINGS = (Q20, Q27, P03)
SCORING_CASE = {
    Q20.outing_id: "Régimes",
    Q27.outing_id: "Passages",
    P03.outing_id: "Régimes sans référence",
}
"""Le cas de scores de M4b-2 de chaque sortie déclarée (usage si et seulement si la
sortie a une référence)."""

V0_RAW = DeclaredModel(
    ModelKind.V0_RAW, ENGINE_VERSION, ParameterSet(PROJECTION_PARAMETER_SPECS), None
)


def performances() -> tuple[DeclaredPerformance, ...]:
    return tuple(
        declared_performance(Performance(o.start_time.date(), (o,))) for o in OUTINGS
    )


def curve() -> tuple[ArtifactRef, ArtifactRef]:
    """Les deux artefacts de la courbe commitée ; l'instant de lecture du CSV est fixé à
    ``RETRIEVED_AT`` pour que l'écriture de la déclaration soit reproductible."""
    csv, meta = curve_artifacts(
        CURVE_PATH, scoring.curve_read(), retrieved_at=RETRIEVED_AT
    )
    source = dataclasses.replace(csv.source, retrieved_at=RETRIEVED_AT)
    return dataclasses.replace(csv, source=source), meta


def declaration(**changes: object) -> Declaration:
    """La déclaration de v0 brut sur les trois sorties ; ``changes`` remplace des
    champs."""
    csv, meta = curve()
    fields: dict[str, object] = dict(
        commit=COMMIT,
        tree_modified=False,
        protocol_record="0010",
        athlete_ref=ATHLETE,
        matching=ParameterSet(MATCHING_PARAMETER_SPECS),
        clocks=CLOCKS,
        curve_ref=scoring.curve_read().curve_ref,
        curve=csv,
        curve_metadata=meta,
        manifest=_source("manifest", "manifeste.json", "4"),
        performances=performances(),
        exclusions=(Exclusion("velo-2026-05-27", "hors domaine : VTT"),),
        models=(V0_RAW,),
        experiment=None,
    )
    fields.update(changes)
    return Declaration(**fields)  # type: ignore[arg-type]


def _on(scores: ScenarioScores, source: SourceRef) -> ScenarioScores:
    """``scores``, sa prévision portée sur ``source``."""
    forecast = dataclasses.replace(scores.forecast, source=source)
    return dataclasses.replace(scores, forecast=forecast)


def v0_of(outing_id: str) -> OutingScores:
    """Les scores de v0 brut du cas de M4b-2 de la sortie, ses prévisions portées sur
    ses fichiers déclarés (§ 6.3) : la première trace en contrôle, la référence en
    usage."""
    outing = next(o for o in OUTINGS if o.outing_id == outing_id)
    case = scoring.scores(SCORING_CASE[outing_id])
    reference, usage = outing.reference, case.usage
    return OutingScores(
        case.observation,
        _on(case.control, outing.traces[0].source),
        None
        if reference is None or usage is None
        else _on(usage, reference.artifact.source),
    )


def outcome(outing_id: str) -> OutingOutcome:
    """Les scores de v0 brut de la sortie (``v0_of``) et sa couverture."""
    name = SCORING_CASE[outing_id]
    chain = scoring.chain("Régimes" if name == "Régimes sans référence" else name)
    return OutingOutcome(
        outing_id, chain.match.coverage, ((ModelKind.V0_RAW, v0_of(outing_id)),)
    )


def outcomes() -> tuple[OutingOutcome, ...]:
    return tuple(outcome(o.outing_id) for o in OUTINGS)


def references() -> tuple[tuple[str, RepeatabilityReference], ...]:
    """La référence D8 du parcours ``r1`` : le cas « Deux jours » de M4b-3, son fichier
    remplacé par la référence déclarée des sorties de ``r1`` (précision de D14,
    M4b-5)."""
    reference = case_reference("Deux jours")
    source = REFERENCE_R1.artifact.source
    return (("r1", dataclasses.replace(reference, reference=source)),)


def d8_reference(source: SourceRef, specs: list[DaySpec]) -> RepeatabilityReference:
    """Une référence D8 des jours ``specs`` du § 7.2 de M4b-3, son fichier remplacé par
    ``source`` (M4c-2 : les jours d'une référence sont exactement ceux du jeu)."""
    reference = repeatability_reference(REFERENCE, days_of(specs))
    return dataclasses.replace(reference, reference=source)


def _not_calibrated(
    model: ModelKind, scores: ScenarioScores
) -> CalibratedScenarioScores:
    return CalibratedScenarioScores(
        model,
        scores.scenario,
        scores.forecast,
        tuple(
            CalibratedClockScores(
                ModelCalibration(
                    model,
                    scores.scenario,
                    clock,
                    (),
                    (),
                    None,
                    None,
                    None,
                    False,
                    Unavailability.NOT_CALIBRATED,
                ),
                None,
            )
            for clock in CLOCKS
        ),
    )


def not_calibrated(
    outing_id: str, model: ModelKind, scores: OutingScores
) -> CalibratedOutingScores:
    """Les scores d'un modèle calé ``non calé`` sous les onze horloges, de prévision
    non calée celle de ``scores`` (M4c-2) : la forme la plus simple d'un document
    calé, pour les tests du registre."""
    return CalibratedOutingScores(
        outing_id,
        scores.observation,
        _not_calibrated(model, scores.control),
        None if scores.usage is None else _not_calibrated(model, scores.usage),
    )


def experiment(**changes: object) -> ExperimentDeclaration:
    """Une expérience de M4c : effet « arrêts », cible ``|E_descente|``, sous
    l'écoulé, en usage."""
    fields: dict[str, object] = dict(
        effect=DeclaredEffect(
            "arrêts", "temps d'arrêt ajouté aux passages", None, "règle de D9.3"
        ),
        target=ExperimentMetric.DESCENT_LEVEL,
        clock=CLOCKS[0],
        scenario=Scenario.USAGE,
        base=ModelKind.V0_RECALIBRATED,
        candidate=ModelKind.CANDIDATE,
        usage_targets=(),
        frozen_references=(
            FrozenReference(
                ExperimentMetric.DESCENT_LEVEL,
                CLOCKS[0],
                ReferenceSource.LOCAL,
                "r1",
                MetricValue(0.05, None, 2),
                (),
            ),
            FrozenReference(
                ExperimentMetric.DESCENT_LEVEL,
                CLOCKS[0],
                ReferenceSource.BORROWED,
                None,
                MetricValue(0.05, None, 2),
                ("r1",),
            ),
        ),
        analysis_date=None,
    )
    fields.update(changes)
    return ExperimentDeclaration(**fields)  # type: ignore[arg-type]


CALIBRATED_MODELS = (
    V0_RAW,
    DeclaredModel(
        ModelKind.V0_RECALIBRATED,
        ENGINE_VERSION,
        ParameterSet(PROJECTION_PARAMETER_SPECS),
        "calage de 0010 D9.2",
    ),
    DeclaredModel(
        ModelKind.CANDIDATE,
        ENGINE_VERSION,
        ParameterSet(PROJECTION_PARAMETER_SPECS),
        "calage de 0010 D9.2, plus l'effet",
    ),
)


def usage_target(**changes: object) -> DeclaredUsageTarget:
    fields: dict[str, object] = dict(
        route_id="r1",
        members=(
            TargetMember(0, False),
            TargetMember(2, False),
            TargetMember(None, True),
        ),
        weights=(0.25, 0.25, 0.5),
    )
    fields.update(changes)
    return DeclaredUsageTarget(**fields)  # type: ignore[arg-type]


def registry_root(tmp_path: Path) -> Path:
    """Le dossier du registre : un sous-dossier, créé par le premier ajout."""
    return tmp_path / "registre"
