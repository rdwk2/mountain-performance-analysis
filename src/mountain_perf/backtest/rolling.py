"""Le backtest glissant (OG-2, ``docs/decisions/0010``, précision OG-2) : chaque
performance ``j`` jugée avec ``κ_j``, la courbe que la règle à l'origine (``0020``)
rend à son origine ``o_j`` sur la fenêtre ``W``.

Une commande, un processus : un manifeste, un index, un corpus, un cache des
intervalles ; une DÉCLARATION et un RÉSULTAT par ``W``. La règle n'est pas recodée
(``estimate_at_origin``), ni la projection (v0, ``0009``), ni le calage et les
fourchettes (``0010`` D9, D11) : ce module les enchaîne. Ses messages ne portent aucun
chemin absolu (règle 1 de ``CLAUDE.md``)."""

from __future__ import annotations

import json
import platform
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from mountain_perf.backtest.bands import evaluation_bands
from mountain_perf.backtest.calibration import (
    calibrate_performances,
    calibration_population,
    calibration_terms,
)
from mountain_perf.backtest.codec import content_hash, encode_document
from mountain_perf.backtest.correspondence import check_correspondence
from mountain_perf.backtest.execution import (
    MODELS,
    PROTOCOL_RECORD,
    V0_RAW_MODEL,
    BacktestError,
    ManifestPreparation,
    OutingRun,
    TracedOuting,
    _score,
    baseline_runs,
    failure_reason,
    outing_outcomes,
    prepare_manifest,
    reference_profile,
    repeatability_references,
    trace_outings,
    trace_profile,
)
from mountain_perf.backtest.manifest import load_manifest
from mountain_perf.backtest.matching import MATCHING_PARAMETER_SPECS
from mountain_perf.backtest.registry import (
    RollingDocuments,
    append_declaration,
    append_failure,
    append_result,
    declared_performance,
    line_hash,
)
from mountain_perf.estimation.curve import (
    CURVE_ESTIMATION_PARAMETER_SPECS,
    BinValue,
    CurveSelection,
)
from mountain_perf.estimation.intervals import (
    ActivityIntervals,
    TraceRefusal,
    activity_intervals,
)
from mountain_perf.estimation.origin import (
    ALL_PAST,
    CurveCorpus,
    OriginEstimate,
    OriginWindow,
    activity_end,
    estimate_at_origin,
    origin_absence_document,
    origin_companion,
)
from mountain_perf.gpx import PROFILE_PARAMETER_SPECS
from mountain_perf.model import PROJECTION_PARAMETER_SPECS, CurveReadResult
from mountain_perf.model.curve_io import (
    curve_csv_support,
    curve_documents,
    freeze_companion,
    read_curve_documents,
)
from mountain_perf.model.engine import portion_out_of_support_time_share
from mountain_perf.runs import load_curve_corpus
from mountain_perf.schemas import (
    CALIBRATED_MODELS,
    CLOCKS,
    AbsentCurve,
    ActivityRecording,
    CalibratedPerformance,
    CalibrationPopulation,
    CalibrationTerm,
    CalibrationTerms,
    CurveStatus,
    Declaration,
    Exclusion,
    Failure,
    FailureKind,
    FrozenCurve,
    ModelKind,
    OutingBands,
    OutingObservation,
    OutingOutcome,
    OutingScores,
    ParameterSet,
    Performance,
    RegistryEvent,
    RepeatabilityReference,
    RollingDeclaration,
    RollingPerformance,
    RollingRule,
    Scenario,
    ScenarioClockTerms,
    ShareScope,
    ShareUnavailability,
    Sport,
    Unavailability,
)
from mountain_perf.validation import ContractError

ROLLING_ACTIVITY_TYPES = frozenset({"trail_running"})
"""Les types de la sélection de la règle en mode glissant : ceux de ``mperf curve --at``
sans option (OG-2 n'expose aucun réglage de la règle)."""

DEFAULT_BEYOND_MARKER = 0.5
"""Le repère par défaut (D-OG2-4) : une performance est au-delà si sa part hors
support le dépasse strictement."""

RecordingReader = Callable[[str], tuple[ActivityRecording, str]]
"""Le lecteur d'un enregistrement d'``interim/`` et de son empreinte, par référence ;
donné par la commande (``backtest/`` n'importe pas ``ingest/``)."""


@dataclass(frozen=True)
class RollingSettings:
    """Les réglages du mode glissant écrits dans la DÉCLARATION (D-OG2-4) :

    - ``covered_threshold`` — fraction — ``s``, sans défaut ;
    - ``beyond_marker`` — fraction — le repère ;
    - ``rule_support_threshold_min`` — minutes — le seuil des diagnostics de la règle ;
    - ``coverage_tolerance_s`` — secondes — la tolérance de la correspondance, sans
      défaut.

    Le seuil de lecture n'y est pas : c'est le paramètre déclaré
    ``curve_min_support_min`` de v0 brut et du comparateur."""

    covered_threshold: float
    beyond_marker: float
    rule_support_threshold_min: float
    coverage_tolerance_s: float


def window_label(window: OriginWindow) -> str:
    """``w<n>`` pour ``n`` jours, ``all`` pour tout le passé (le nom d'une courbe)."""
    return ALL_PAST if isinstance(window, str) else f"w{window}"


def rolling_selection() -> CurveSelection:
    """La sélection de ``mperf curve --at`` sans option (OG-2) : ``trail_running``, ni
    durée ni plafond ni centre de FC, valeur « somme »."""
    return CurveSelection(
        ROLLING_ACTIVITY_TYPES, None, None, None, None, None, None, BinValue.POOLED
    )


def reading_threshold() -> float:
    """Le seuil de lecture de ``κ_j`` : le paramètre déclaré ``curve_min_support_min``
    de v0 brut (OG-2, § 6.7 (a))."""
    parameters = V0_RAW_MODEL.parameters
    assert parameters is not None  # v0 brut porte ses paramètres
    return parameters["curve_min_support_min"]


@dataclass(frozen=True)
class RollingCurve:
    """Le sort de la courbe d'une performance sous une fenêtre (OG-2) : l'estimation de
    la règle, le document figé (courbe ou absence), ``κ_j`` relue de ses octets (statut
    ``curve`` seulement), et l'entrée de la DÉCLARATION."""

    estimate: OriginEstimate
    document: FrozenCurve | AbsentCurve
    curve: CurveReadResult | None
    entry: RollingPerformance

    @property
    def companion(self) -> dict[str, Any] | None:
        """Le compagnon figé, relu (``None`` pour une absence)."""
        if isinstance(self.document, AbsentCurve):
            return None
        loaded: dict[str, Any] = json.loads(self.document.companion)
        return loaded


@dataclass(frozen=True)
class RollingWindow:
    """Une fenêtre de la commande : son document de règle, la courbe de chaque
    performance dans l'ordre, et sa DÉCLARATION."""

    window: OriginWindow
    rule: RollingRule
    curves: tuple[RollingCurve, ...]
    declaration: Declaration


@dataclass(frozen=True)
class RollingPreparation:
    """Ce que la commande glissante va évaluer, lu et contrôlé avant tout écrit : le
    manifeste préparé, le corpus, les réglages, l'instant de la préparation et une
    fenêtre par ``W``."""

    common: ManifestPreparation
    corpus: CurveCorpus
    settings: RollingSettings
    prepared_at: datetime
    windows: tuple[RollingWindow, ...]


def _rule(
    athlete_ref: str,
    commit: str,
    window: OriginWindow,
    selection: CurveSelection,
    parameters: ParameterSet,
    profile: ParameterSet,
    threshold: float,
) -> RollingRule:
    return RollingRule(
        athlete_ref=athlete_ref,
        commit=commit,
        window_days=None if isinstance(window, str) else window,
        source_activity_types=tuple(sorted(selection.source_activity_types)),
        min_duration_s=selection.min_duration_s,
        max_duration_s=selection.max_duration_s,
        max_elapsed_s=selection.max_elapsed_s,
        hr_center_bpm=selection.hr_center_bpm,
        value=selection.value.value,
        parameters=dict(parameters.values),
        profile_parameters=dict(profile.values),
        diagnostic_support_threshold_min=threshold,
    )


def intervals_cache(
    corpus: CurveCorpus,
) -> Callable[..., ActivityIntervals | TraceRefusal]:
    """Un cache des intervalles en mémoire, le temps d'une préparation (OG-2, PG16) :
    une table de ``(activity_ref, recording_sha256, paramètres du profil, hr_lag_s,
    hr_min_coverage, max_elapsed_s)`` vers ce qu'``activity_intervals`` a rendu — la clé
    de ``0020`` (« Conséquences »), moins ce que le processus fixe."""
    store: dict[tuple[object, ...], ActivityIntervals | TraceRefusal] = {}

    def cached(
        recording: ActivityRecording,
        profile_parameters: ParameterSet,
        /,
        *,
        hr_lag_s: float,
        hr_min_coverage: float,
        max_elapsed_s: float | None,
    ) -> ActivityIntervals | TraceRefusal:
        ref = recording.activity_ref
        key = (
            ref,
            corpus.recording_sha256.get(ref),
            tuple(sorted(profile_parameters.values.items())),
            hr_lag_s,
            hr_min_coverage,
            max_elapsed_s,
        )
        if key not in store:
            store[key] = activity_intervals(
                recording,
                profile_parameters,
                hr_lag_s=hr_lag_s,
                hr_min_coverage=hr_min_coverage,
                max_elapsed_s=max_elapsed_s,
            )
        return store[key]

    return cached


def _check_correspondences(
    common: ManifestPreparation,
    corpus: CurveCorpus,
    origins: Sequence[datetime],
    tolerance_s: float,
    read_recording: RecordingReader,
) -> None:
    """La correspondance de chaque sortie qui déclare des activités (§ 6.3), avant tout
    écrit : chaque activité dans l'index ; son enregistrement lu une fois (celui du
    corpus, ou par ``read_recording``) quel que soit son type, s'il en a un ; ses fins ;
    les trois contrôles."""
    read = common.manifest
    entries = {entry.activity_ref: entry for entry in corpus.index.entries}
    for outing in read.outings:
        if not outing.activity_refs:
            continue
        ends = []
        for ref in outing.activity_refs:
            entry = entries.get(ref)
            if entry is None:
                raise ContractError(
                    f"sortie {outing.outing_id} : l'activité {ref} déclarée n'est pas "
                    "dans l'index."
                )
            recording = None
            if entry.has_recording:
                recording = corpus.recordings.get(ref)
                if recording is None:
                    recording = read_recording(ref)[0]
            ends.append(activity_end(entry, recording))
        check_correspondence(
            outing, read.traces.get(outing.outing_id), ends, origins, tolerance_s
        )


def _share(
    common: ManifestPreparation,
    performance: Performance,
    curve: CurveReadResult,
    profiles: dict[Path, Any],
) -> tuple[float | None, ShareScope | None, ShareUnavailability | None]:
    """La part hors support d'une performance ``curve`` (§ 6.2, § 6.7 (b) 7) : sur la
    portion déclarée du profil de sa référence (usage) ; sans référence, sur le profil
    de sa trace (contrôle) ; non tracée et sans référence, indisponible ; plusieurs
    sorties, indisponible."""
    if performance.is_multi_outing:
        return None, None, ShareUnavailability.MULTI_OUTING_DAY
    outing = performance.outings[0]
    parameters = ParameterSet(PROJECTION_PARAMETER_SPECS)
    if outing.reference is not None:
        profile, _ = reference_profile(common.manifest, outing, profiles)
        portion = outing.declared_portion_m
        length = profile.distance_m[-1]
        if portion is not None and portion[1] > length:
            raise ContractError(
                f"sortie {outing.outing_id} : portion_m ({portion[0]:g}, "
                f"{portion[1]:g}) dépasse la longueur du profil de sa référence "
                f"({length:g} m)."
            )
        share = portion_out_of_support_time_share(
            profile, curve.curve, parameters, portion
        )
        return share, ShareScope.USAGE, None
    trace = common.manifest.traces.get(outing.outing_id)
    if trace is None:
        return None, None, ShareUnavailability.NO_PROFILE
    profile, _ = trace_profile(outing, trace)
    share = portion_out_of_support_time_share(profile, curve.curve, parameters, None)
    return share, ShareScope.CONTROL, None


def _curve_of(
    common: ManifestPreparation,
    corpus: CurveCorpus,
    performance: Performance,
    origin_at: datetime,
    window: OriginWindow,
    settings: RollingSettings,
    *,
    commit: str,
    prepared_at: datetime,
    intervals_of: Callable[..., ActivityIntervals | TraceRefusal],
    profiles: dict[Path, Any],
) -> RollingCurve:
    """La courbe d'une performance sous une fenêtre (§ 6.7 (b) 6 et 7) : la règle, puis
    la courbe figée et relue de ses octets (ou le document d'absence), le verdict de
    lecture, la part hors support."""
    selection = rolling_selection()
    parameters = ParameterSet(CURVE_ESTIMATION_PARAMETER_SPECS)
    profile = ParameterSet(PROFILE_PARAMETER_SPECS)
    athlete = common.manifest.athlete_ref
    result = estimate_at_origin(
        corpus,
        athlete,
        origin_at,
        window,
        selection,
        parameters,
        profile,
        support_threshold_min=settings.rule_support_threshold_min,
        intervals_of=intervals_of,
    )
    if result.estimate is None:
        absent = AbsentCurve(origin_absence_document(result, corpus).decode("utf-8"))
        entry = RollingPerformance(
            CurveStatus.ABSENT,
            content_hash(encode_document(absent)),
            None,
            None,
            None,
            None,
            ShareUnavailability.NO_CURVE,
        )
        return RollingCurve(result, absent, None, entry)
    provenance, estimation = origin_companion(
        result,
        corpus,
        selection,
        parameters,
        profile,
        commit=commit,
        generated_at=prepared_at,
    )
    documents = curve_documents(result.rows, Sport.FOOT, provenance, estimation)
    companion = freeze_companion(documents.companion)
    frozen = FrozenCurve(documents.csv.decode("utf-8"), companion.decode("utf-8"))
    sha = content_hash(encode_document(frozen))
    name = f"og2-{performance.civil_date.isoformat()}-{window_label(window)}.csv"
    if curve_csv_support(documents.csv, reading_threshold())[1] is not None:
        entry = RollingPerformance(
            CurveStatus.NO_READ_SUPPORT,
            sha,
            frozen.csv_sha256,
            f"{name}#{frozen.csv_sha256[:12]}",
            None,
            None,
            ShareUnavailability.NO_CURVE,
        )
        return RollingCurve(result, frozen, None, entry)
    curve = read_curve_documents(
        documents.csv,
        companion,
        name,
        ParameterSet(PROJECTION_PARAMETER_SPECS),
        generated_at=prepared_at,
    )
    share, scope, unavailable = _share(common, performance, curve, profiles)
    entry = RollingPerformance(
        CurveStatus.CURVE,
        sha,
        frozen.csv_sha256,
        curve.curve_ref,
        share,
        scope,
        unavailable,
    )
    return RollingCurve(result, frozen, curve, entry)


def platform_label() -> str:
    """« {système} {version}, Python {version} » : la plateforme de l'exécution."""
    return (
        f"{platform.system()} {platform.release()}, Python {platform.python_version()}"
    )


def prepare_rolling(
    manifest_path: Path,
    folder: Path,
    windows: Sequence[OriginWindow],
    settings: RollingSettings,
    *,
    commit: str,
    tree_modified: bool,
    prepared_at: datetime,
    read_recording: RecordingReader,
) -> RollingPreparation:
    """Lit, estime, contrôle et déclare, **sans rien écrire** (OG-2), dans cet ordre :
    le manifeste et ses étapes communes (``prepare_manifest``) ; les origines ; **un**
    corpus, celui de la plus tardive des origines sur tout le passé
    (``load_curve_corpus``) ; la correspondance des sorties qui déclarent des
    activités ; le cache des intervalles ; pour chaque ``W`` et chaque performance, la
    règle, la courbe figée ou l'absence, et la part hors support ; enfin une
    DÉCLARATION par ``W``. ``folder`` : le dossier des données (``interim/`` dessous) ;
    ``read_recording`` : le lecteur d'un enregistrement que le corpus n'a pas chargé.
    Une erreur remonte avant tout écrit."""
    common = prepare_manifest(load_manifest(manifest_path))
    declared = tuple(declared_performance(p) for p in common.performances)
    origins = sorted(item.origin for item in declared)
    athlete = common.manifest.athlete_ref
    corpus = load_curve_corpus(
        folder,
        athlete,
        ROLLING_ACTIVITY_TYPES,
        origins[-1] if origins else prepared_at,
        ALL_PAST,
    )
    _check_correspondences(
        common, corpus, origins, settings.coverage_tolerance_s, read_recording
    )
    cache = intervals_cache(corpus)
    profiles: dict[Path, Any] = {}
    selection = rolling_selection()
    built: list[RollingWindow] = []
    for window in windows:
        rule = _rule(
            athlete,
            commit,
            window,
            selection,
            ParameterSet(CURVE_ESTIMATION_PARAMETER_SPECS),
            ParameterSet(PROFILE_PARAMETER_SPECS),
            settings.rule_support_threshold_min,
        )
        curves = tuple(
            _curve_of(
                common,
                corpus,
                item.performance,
                item.origin,
                window,
                settings,
                commit=commit,
                prepared_at=prepared_at,
                intervals_of=cache,
                profiles=profiles,
            )
            for item in declared
        )
        rolling = RollingDeclaration(
            rule=content_hash(encode_document(rule)),
            window_days=rule.window_days,
            command_windows=tuple(None if isinstance(w, str) else w for w in windows),
            covered_threshold=settings.covered_threshold,
            beyond_marker=settings.beyond_marker,
            coverage_tolerance_s=settings.coverage_tolerance_s,
            index_sha256=corpus.index_sha256,
            platform=platform_label(),
            performances=tuple(curve.entry for curve in curves),
        )
        declaration = Declaration(
            commit=commit,
            tree_modified=tree_modified,
            protocol_record=PROTOCOL_RECORD,
            athlete_ref=athlete,
            matching=ParameterSet(MATCHING_PARAMETER_SPECS),
            clocks=CLOCKS,
            curve_ref=None,
            curve=None,
            curve_metadata=None,
            manifest=common.manifest.source,
            performances=declared,
            exclusions=common.exclusions,
            models=MODELS,
            experiment=None,
            rolling=rolling,
        )
        built.append(RollingWindow(window, rule, curves, declaration))
    return RollingPreparation(common, corpus, settings, prepared_at, tuple(built))


# ---------------------------------------------------------------------------
# Exécution : par fenêtre, DÉCLARATION, calcul, RÉSULTAT ou ÉCHEC
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class NoCurveRun:
    """Une sortie tracée d'une performance sans courbe (§ 6.8 (d)) : son observation
    et les scores non calés des trois baselines, ``q_usage`` « sans courbe » ; v0 brut
    et le comparateur ne la scorent pas (choix C12)."""

    traced: TracedOuting
    observation: OutingObservation
    baselines: tuple[tuple[ModelKind, OutingScores], ...]


@dataclass(frozen=True)
class RollingEvaluation:
    """Le calcul d'une fenêtre, avant son RÉSULTAT : sa fenêtre préparée, sa
    DÉCLARATION, les sorties scorées avec ``κ_j`` et celles des performances sans
    courbe, les sorties non scorées, les références D8, la population ``C_j`` et le
    calage de chaque performance (celui des seules baselines sans courbe), les
    fourchettes, et les
    documents des termes du calage, un par performance (absent sans courbe)."""

    window: RollingWindow
    declaration_event: RegistryEvent
    outings: tuple[OutingRun, ...]
    no_curve: tuple[NoCurveRun, ...]
    unscored: tuple[Exclusion, ...]
    references: tuple[tuple[str, RepeatabilityReference], ...]
    populations: tuple[CalibrationPopulation, ...]
    calibration: tuple[CalibratedPerformance, ...]
    bands: tuple[OutingBands, ...]
    terms: tuple[CalibrationTerms | None, ...]


@dataclass(frozen=True)
class RollingWindowRun:
    """Une fenêtre enregistrée : son calcul, son RÉSULTAT et le sceau (l'empreinte de
    la ligne du RÉSULTAT)."""

    evaluation: RollingEvaluation
    result_event: RegistryEvent
    seal: str


def member_curve(window: RollingWindow, j: int, c: int) -> CurveReadResult:
    """La courbe avec laquelle on projette le membre ``c`` dans le réservoir des
    fourchettes de la performance ``j`` (§ 6.8 (b), « la prévision du membre ») : **le
    seul point de choix**. Le réservoir (a) rend ``κ_j`` ; le réservoir (b) rendrait la
    courbe de ``c``. Le calage (a) ne passe pas par ici : il projette toujours avec
    ``κ_j``."""
    del c  # réservoir (a) : la courbe de j, pour tout membre
    curve = window.curves[j].curve
    assert curve is not None  # j a le statut curve
    return curve


_TERM_SCENARIOS = tuple(Scenario)


def _terms(
    performance: Performance,
    performances: Sequence[Performance],
    calibrated: CalibratedPerformance,
    unscaled: Mapping[str, Mapping[ModelKind, OutingScores]],
) -> CalibrationTerms:
    """Le document des termes du calage du comparateur d'une performance (E6) : pour
    chaque scénario présent sur **l'une quelconque** des sorties scorées par le
    comparateur (l'usage d'un jour multi-sorties peut manquer à la première et non à
    une suivante) et chaque horloge, les ``(T_c, P_c)`` de ``calibration_terms``, sur
    les scores de v0 brut des membres."""
    del performance
    population = calibrated.population
    by_day = {p.civil_date: p for p in performances}
    members = {
        day: tuple(
            unscaled[outing.outing_id][ModelKind.V0_RAW]
            for outing in by_day[day].outings
            if outing.outing_id in unscaled
        )
        for day in population.members
    }
    comparator = [
        entry
        for entry in calibrated.outings
        if entry.control.model is ModelKind.V0_RECALIBRATED
    ]
    scenarios = []
    if comparator:
        scenarios.append(Scenario.CONTROL)
        if any(entry.usage is not None for entry in comparator):
            scenarios.append(Scenario.USAGE)
    sets = tuple(
        ScenarioClockTerms(
            scenario,
            clock,
            tuple(
                CalibrationTerm(day, observed, forecast)
                for day, observed, forecast in calibration_terms(
                    population, ModelKind.V0_RECALIBRATED, scenario, i, members
                )
            ),
        )
        for scenario in sorted(scenarios, key=_TERM_SCENARIOS.index)
        for i, clock in enumerate(CLOCKS)
    )
    return CalibrationTerms(ModelKind.V0_RECALIBRATED, sets)


BASELINE_CALIBRATED = tuple(
    model for model in CALIBRATED_MODELS if model is not ModelKind.V0_RECALIBRATED
)
"""Les modèles calés d'une performance sans courbe : les trois baselines (§ 6.8 (d))."""


def evaluate_rolling(
    window: RollingWindow,
    preparation: RollingPreparation,
    declared: RegistryEvent,
    traced: tuple[TracedOuting, ...],
    untraced: tuple[Exclusion, ...],
) -> RollingEvaluation:
    """Le calcul d'une fenêtre, sans rien écrire (§ 6.8). Pour chaque performance ``j``,
    dans l'ordre :

    - au statut ``curve`` : les scores non calés **avec ``κ_j``** de ses sorties et de
      celles des membres de ``C_j`` (``_score``) ; ``calibrate_performances`` sur
      **toutes** les performances (les exclusions de ``C_j`` en dépendent) et ces seuls
      scores — le calage (a) ; les fourchettes sur les scores du réservoir, dont
      chaque membre est projeté avec ``member_curve(j, c)`` — le réservoir (a), et sur
      le calage de ces scores ; les termes du calage ; la ligne de ``j`` seule est
      gardée ;
    - sans courbe : ses sorties et celles de ses membres scorées par les seules
      baselines (``baseline_runs``, ``q_usage`` « sans courbe »), le calage des
      baselines, ni fourchettes ni termes.

    Les prévisions sont datées de ``declared``."""
    performances = preparation.common.performances
    at = declared.recorded_at
    by_outing = {item.outing.outing_id: item for item in traced}
    by_day = {p.civil_date: p for p in performances}
    index_of = {p.civil_date: k for k, p in enumerate(performances)}
    populations = tuple(calibration_population(p, performances) for p in performances)
    runs: list[OutingRun] = []
    no_curve: list[NoCurveRun] = []
    calibration: list[CalibratedPerformance] = []
    bands: list[OutingBands] = []
    terms: list[CalibrationTerms | None] = []
    observations: dict[str, OutingObservation] = {}
    memo: dict[tuple[int, str], OutingRun] = {}
    baselines_memo: dict[str, tuple[OutingObservation, Any]] = {}

    def score(curve: CurveReadResult, outing_id: str) -> OutingRun:
        key = (id(curve), outing_id)
        if key not in memo:
            memo[key] = _score(curve, by_outing[outing_id], at)
        return memo[key]

    def baselines_of(outing_id: str) -> tuple[OutingObservation, Any]:
        if outing_id not in baselines_memo:
            baselines_memo[outing_id] = baseline_runs(
                by_outing[outing_id], at, base_unavailability=Unavailability.NO_CURVE
            )
        return baselines_memo[outing_id]

    for j, (performance, population) in enumerate(
        zip(performances, populations, strict=True)
    ):
        members = [index_of[day] for day in population.members]
        useful = [
            (k, outing.outing_id)
            for k in (j, *members)
            for outing in performances[k].outings
            if outing.outing_id in by_outing
        ]
        own = {outing.outing_id for outing in performance.outings}
        kappa = window.curves[j].curve
        if kappa is None:
            unscaled = {
                outing_id: dict(baselines_of(outing_id)[1]) for _, outing_id in useful
            }
            calibrated = calibrate_performances(
                performances,
                unscaled,
                models=BASELINE_CALIBRATED,
                base_unavailability=Unavailability.NO_CURVE,
            )
            for outing in performance.outings:
                if outing.outing_id in by_outing:
                    observation, scores = baselines_of(outing.outing_id)
                    no_curve.append(
                        NoCurveRun(by_outing[outing.outing_id], observation, scores)
                    )
                    observations[outing.outing_id] = observation
            calibration.append(calibrated[j])
            terms.append(None)
            continue
        scored = {outing_id: score(kappa, outing_id) for _, outing_id in useful}
        unscaled = {
            outing_id: {ModelKind.V0_RAW: run.scores, **dict(run.baselines)}
            for outing_id, run in scored.items()
        }
        calibrated = calibrate_performances(performances, unscaled)
        reservoir_runs = {
            outing_id: (
                scored[outing_id]
                if k == j
                else score(member_curve(window, j, k), outing_id)
            )
            for k, outing_id in useful
        }
        if all(reservoir_runs[i] is scored[i] for i in scored):
            reservoir, reservoir_calibration = unscaled, calibrated
        else:
            reservoir = {
                outing_id: {ModelKind.V0_RAW: run.scores, **dict(run.baselines)}
                for outing_id, run in reservoir_runs.items()
            }
            reservoir_calibration = calibrate_performances(performances, reservoir)
        estimation = kappa.curve.estimation
        window_bands = evaluation_bands(
            performances,
            reservoir,
            reservoir_calibration,
            (estimation.date_from, estimation.date_to),
        )
        for outing in performance.outings:
            run = scored.get(outing.outing_id)
            if run is not None:
                runs.append(run)
                observations[outing.outing_id] = run.scores.observation
        bands.extend(entry for entry in window_bands if entry.outing_id in own)
        calibration.append(calibrated[j])
        terms.append(_terms(performance, performances, calibrated[j], unscaled))
    references = repeatability_references(performances, observations)
    del by_day
    return RollingEvaluation(
        window,
        declared,
        tuple(runs),
        tuple(no_curve),
        tuple(untraced),
        references,
        populations,
        tuple(calibration),
        tuple(bands),
        tuple(terms),
    )


def _outcomes(evaluation: RollingEvaluation) -> tuple[OutingOutcome, ...]:
    """Ce que le RÉSULTAT porte de chaque sortie scorée, dans l'ordre des performances
    et de leurs sorties : avec une courbe, v0 brut et les quatre modèles calés
    (``outing_outcomes``) ; sans courbe, les trois baselines calées seules."""
    with_curve = {
        outcome.outing_id: outcome
        for outcome in outing_outcomes(
            evaluation.outings,
            tuple(
                item
                for item, term in zip(
                    evaluation.calibration, evaluation.terms, strict=True
                )
                if term is not None
            ),
            evaluation.bands,
        )
    }
    calibrated = {
        (entry.outing_id, entry.control.model): entry
        for performance in evaluation.calibration
        for entry in performance.outings
    }
    without = {
        run.traced.outing.outing_id: OutingOutcome(
            run.traced.outing.outing_id,
            run.traced.match.coverage,
            tuple(
                (model, calibrated[(run.traced.outing.outing_id, model)])
                for model in BASELINE_CALIBRATED
            ),
        )
        for run in evaluation.no_curve
    }
    ordered: list[OutingOutcome] = []
    for performance in evaluation.window.declaration.performances:
        for outing in performance.performance.outings:
            found = with_curve.get(outing.outing_id) or without.get(outing.outing_id)
            if found is not None:
                ordered.append(found)
    return tuple(ordered)


def run_rolling(
    preparation: RollingPreparation,
    registry_root: Path,
    *,
    recorded_at: datetime | None = None,
    on_declaration: Callable[[RegistryEvent, str], None] | None = None,
    before_result: Callable[[RollingEvaluation], None] | None = None,
    after_result: Callable[[RollingWindowRun], None] | None = None,
) -> tuple[RollingWindowRun, ...]:
    """L'exécution enregistrée de la commande glissante (§ 6.7 (c)), sur le modèle de
    ``run_backtest`` : pour chaque ``W``, dans l'ordre de la commande, la DÉCLARATION
    (``on_declaration``), le calcul (les sorties tracées une fois pour toutes les
    fenêtres : l'appariement ne lit pas la courbe), ``before_result`` (le rapport
    calculé), le RÉSULTAT, puis ``after_result`` (l'annonce du RÉSULTAT et l'écriture
    de son rapport, avant la fenêtre suivante) ; une exception ou une interruption au
    clavier avant le RÉSULTAT devient l'ÉCHEC technique de **ce** ``W``,
    ``BacktestError``, et la commande s'arrête. ``after_result`` est appelé hors de ce
    cas : le RÉSULTAT est déjà au registre, et son erreur sort telle quelle (les ``W``
    suivants ne sont pas déclarés)."""
    runs: list[RollingWindowRun] = []
    traced: tuple[tuple[TracedOuting, ...], tuple[Exclusion, ...]] | None = None
    for window in preparation.windows:
        declared = append_declaration(
            registry_root, window.declaration, recorded_at=recorded_at
        )
        try:
            if on_declaration is not None:
                on_declaration(declared, line_hash(declared))
            if traced is None:
                traced = trace_outings(
                    preparation.common, {}, window.declaration.matching
                )
            evaluation = evaluate_rolling(
                window, preparation, declared, traced[0], traced[1]
            )
            if before_result is not None:
                before_result(evaluation)
            result = append_result(
                registry_root,
                declared.number,
                _outcomes(evaluation),
                unscored=evaluation.unscored,
                references=evaluation.references,
                rolling=RollingDocuments(
                    window.rule,
                    tuple(curve.document for curve in window.curves),
                    evaluation.terms,
                ),
                recorded_at=recorded_at,
            )
        except (Exception, KeyboardInterrupt) as error:
            reason = failure_reason(error)
            failure = append_failure(
                registry_root,
                declared.number,
                Failure(FailureKind.TECHNICAL, reason),
                recorded_at=recorded_at,
            )
            raise BacktestError(
                f"échec de l'exécution glissante, ÉCHEC enregistré (événement "
                f"{failure.number} ; dernière ligne sha256 {line_hash(failure)}) : "
                f"{reason}"
            ) from error
        window_run = RollingWindowRun(evaluation, result, line_hash(result))
        runs.append(window_run)
        if after_result is not None:
            after_result(window_run)
    return tuple(runs)
