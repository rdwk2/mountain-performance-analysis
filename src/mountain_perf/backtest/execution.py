"""L'exécution enregistrée de ``just backtest`` (M4b-5) : état git, domaine,
DÉCLARATION, chaîne de ``mperf match --curve`` sortie par sortie, références D8,
RÉSULTAT ou ÉCHEC.

Protocole : ``docs/decisions/0010`` D14 (et ses précisions de M4b-5), D0, D2.1, D2.5,
D2.6, D3, D8. Ce module lit des fichiers et écrit au registre ; il n'ajoute aucun
calcul : il enchaîne ceux des modules fusionnés. Ses messages ne portent aucun chemin
absolu (règle 1 de ``CLAUDE.md``).
"""

from __future__ import annotations

import math
import subprocess
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path

from mountain_perf.backtest.calendar import civil_date
from mountain_perf.backtest.clocks import clock_partition
from mountain_perf.backtest.geometry import (
    ReferenceGeometry,
    reference_geometry,
    trace_route,
)
from mountain_perf.backtest.manifest import ManifestReadResult, load_manifest
from mountain_perf.backtest.matching import MATCHING_PARAMETER_SPECS
from mountain_perf.backtest.outings import (
    DOMAIN_MIN_DPLUS_PER_KM,
    domain_profile_source,
    group_performances,
    in_domain,
    retain_outings,
)
from mountain_perf.backtest.passages import observe_passages
from mountain_perf.backtest.registry import (
    append_declaration,
    append_failure,
    append_result,
    curve_artifacts,
    declared_performance,
    line_hash,
)
from mountain_perf.backtest.repeatability import repeatability_reference
from mountain_perf.backtest.scoring import v0_scores
from mountain_perf.backtest.segments import match_trace
from mountain_perf.backtest.series import TraceSeries, build_series
from mountain_perf.gpx import (
    PROFILE_PARAMETER_SPECS,
    GpxError,
    ProfileError,
    build_profile,
    read_gpx,
)
from mountain_perf.model import (
    ENGINE_VERSION,
    PROJECTION_PARAMETER_SPECS,
    CurveReadResult,
    read_curve,
)
from mountain_perf.schemas import (
    CLOCKS,
    ClockPartition,
    DataSet,
    Declaration,
    DeclaredModel,
    Exclusion,
    Failure,
    FailureKind,
    MatchResult,
    ModelKind,
    Outing,
    OutingOutcome,
    OutingScores,
    ParameterSet,
    PassageMatchResult,
    Performance,
    RecordedTrace,
    RegistryEvent,
    RepeatabilityDay,
    RepeatabilityReference,
    RetentionDecision,
    RouteProfile,
    SourceRef,
    Sport,
)
from mountain_perf.validation import ContractError

PROTOCOL_RECORD = "0010"
"""Le decision record du protocole, que la DÉCLARATION nomme (``0010`` D14)."""

V0_RAW_MODEL = DeclaredModel(
    ModelKind.V0_RAW, ENGINE_VERSION, ParameterSet(PROJECTION_PARAMETER_SPECS), None
)
"""Le seul modèle de M4b : v0 brut, effort 1, paramètres par défaut, sans règle
d'estimation (précision de D14, M4b-5)."""

_GIT_MISSING = "git introuvable : just backtest enregistre le commit du code exécuté."
_NOT_A_REPOSITORY = (
    "le code exécuté n'est pas dans un dépôt git : just backtest enregistre son "
    "commit (0010 D14)."
)
_UNTRACED_UNREFERENCED = "sortie non tracée, sans référence"
_UNTRACED = "sortie non tracée"
_NO_PERFORMANCE = "aucune performance dans le domaine"


class BacktestError(RuntimeError):
    """Exécution impossible ou interrompue ; le message dit pourquoi, sans chemin
    absolu (règle 1 de ``CLAUDE.md``)."""


# ---------------------------------------------------------------------------
# État git (décision Q7)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class GitState:
    """Le commit du code exécuté et l'état de son arbre de travail : ``modified`` si
    un fichier suivi est modifié, indexé ou non (``0010`` D14)."""

    commit: str
    modified: bool


def _git(directory: Path, *arguments: str) -> str:
    try:
        completed = subprocess.run(
            ["git", "-C", str(directory), *arguments],
            capture_output=True,
            text=True,
            encoding="utf-8",
            check=False,
        )
    except OSError:
        raise BacktestError(_GIT_MISSING) from None
    if completed.returncode != 0:
        raise BacktestError(_NOT_A_REPOSITORY)
    return completed.stdout


def git_state(directory: Path) -> GitState:
    """L'état git du dépôt qui contient ``directory`` (précision de D14, M4b-5 ;
    décision Q7) : ``git rev-parse HEAD``, puis ``git status --porcelain
    --untracked-files=no``, modifié si sa sortie n'est pas vide — un fichier non suivi
    ne compte pas. ``BacktestError`` sans ``git``, ou hors d'un dépôt."""
    commit = _git(directory, "rev-parse", "HEAD").strip()
    status = _git(directory, "status", "--porcelain", "--untracked-files=no")
    return GitState(commit, status != "")


# ---------------------------------------------------------------------------
# Domaine (D2.1 et sa précision de M4b-5)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class OutingDomain:
    """Le profil de domaine d'une sortie : son D+/km (``None`` s'il est inconnu), les
    noms de ses fichiers, et le motif d'un D+/km inconnu."""

    outing_id: str
    dplus_per_km: float | None
    source: str | None
    reason: str | None


def _domain(read: ManifestReadResult, outing: Outing) -> OutingDomain:
    artifacts = domain_profile_source(outing)
    if not artifacts:
        return OutingDomain(outing.outing_id, None, None, _UNTRACED_UNREFERENCED)
    names = [artifact.source.identifier for artifact in artifacts]
    source = ", ".join(names)
    ascents_m: list[float] = []
    lengths_m: list[float] = []
    for artifact, name in zip(artifacts, names, strict=True):
        path = read.artifact_paths[artifact.source.content_hash]
        try:
            profile = build_profile(
                read_gpx(path).route, ParameterSet(PROFILE_PARAMETER_SPECS)
            )
        except (GpxError, ProfileError, ContractError) as error:
            reason = f"profil de domaine illisible ({name}) : {error}"
            return OutingDomain(outing.outing_id, None, source, reason)
        ascents_m.append(profile.cumulative_ascent_m[-1])
        lengths_m.append(profile.distance_m[-1])
    dplus = math.fsum(ascents_m) / math.fsum(lengths_m) * 1000
    return OutingDomain(outing.outing_id, dplus, source, None)


def outing_domains(read: ManifestReadResult) -> tuple[OutingDomain, ...]:
    """Le D+/km du profil de domaine de chaque sortie de ``read.outings``, dans leur
    ordre (``0010`` D2.1 et sa précision de M4b-5) : le préparé ou la trace de
    référence désignée, à défaut les fichiers de trace de la sortie, **refusés
    compris**, lus comme des tracés (lecture GPX, profil lissé de ``0008`` aux
    défauts) ; plusieurs fichiers : la somme de leurs D+ sur la somme de leurs
    longueurs. Sans fichier, ou au premier fichier qui ne se lit pas comme un tracé,
    le D+/km est inconnu, avec son motif."""
    return tuple(_domain(read, outing) for outing in read.outings)


def _out_of_domain(outing: Outing, domain: OutingDomain, first: date) -> str:
    """Le motif d'une sortie retenue hors du domaine, le premier dans l'ordre : sport,
    date, D+/km inconnu, D+/km sous le seuil (précision de D2.1, M4b-5)."""
    if outing.sport is not Sport.FOOT:
        return f"hors domaine : sport {outing.sport}, pas du trail à pied"
    day = civil_date(outing.start_time)
    if day < first:
        return (
            f"hors domaine : partie le {day.isoformat()}, avant le début du domaine "
            f"({first.isoformat()})"
        )
    if domain.dplus_per_km is None:
        return f"hors domaine : D+/km inconnu ({domain.reason})"
    return (
        f"hors domaine : D+/km {domain.dplus_per_km:.1f}, "
        f"sous {DOMAIN_MIN_DPLUS_PER_KM:g}"
    )


# ---------------------------------------------------------------------------
# Préparation : rien n'est écrit
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Preparation:
    """Ce que l'exécution va évaluer, lu et contrôlé avant tout écrit : le manifeste,
    la courbe, la rétention, les domaines, les performances et la DÉCLARATION."""

    manifest: ManifestReadResult
    curve: CurveReadResult
    decisions: tuple[RetentionDecision, ...]
    domains: tuple[OutingDomain, ...]
    performances: tuple[Performance, ...]
    declaration: Declaration


def _repeatability_references(
    performances: tuple[Performance, ...],
) -> dict[str, SourceRef]:
    """La référence déclarée de chaque parcours du jeu de répétabilité (``0010`` D8,
    D8.1) : chaque sortie de répétabilité a un parcours et une référence, puis les
    jours d'un parcours ont tous la même ; ``BacktestError`` sinon."""
    outings = [
        outing
        for performance in performances
        for outing in performance.outings
        if outing.dataset is DataSet.REPEATABILITY
    ]
    by_route: dict[str, list[SourceRef]] = {}
    for outing in outings:
        if outing.route_id is None:
            raise BacktestError(
                f"sortie {outing.outing_id!r} : jeu de répétabilité sans parcours "
                "(0010 D8)."
            )
        if outing.reference is None:
            raise BacktestError(
                f"sortie {outing.outing_id!r} : jeu de répétabilité sans référence "
                "(0010 D8.1)."
            )
        by_route.setdefault(outing.route_id, []).append(
            outing.reference.artifact.source
        )
    for route_id in sorted(by_route):
        if len({source.content_hash for source in by_route[route_id]}) > 1:
            raise BacktestError(
                f"parcours {route_id!r} : ses jours de répétabilité n'ont pas tous la "
                "même référence (0010 D8.1)."
            )
    return {route_id: by_route[route_id][0] for route_id in sorted(by_route)}


def _exclusions(
    read: ManifestReadResult,
    decisions: tuple[RetentionDecision, ...],
    domains: dict[str, OutingDomain],
    in_domain_ids: set[str],
) -> tuple[Exclusion, ...]:
    """Les sorties écartées, dans l'ordre des décisions (jour, rang) — non retenue
    (D0), retenue hors du domaine (D2.1) —, puis les sorties d'un autre athlète, dans
    l'ordre des refus (D2.6)."""
    exclusions: list[Exclusion] = []
    for decision in decisions:
        outing = decision.outing
        if not decision.retained:
            reason = (
                "non retenue : écoulé cumulé du jour "
                f"{decision.cumulative_elapsed_s:.0f} s, 4 h ou plus (0010 D0)"
            )
            exclusions.append(Exclusion(outing.outing_id, reason))
        elif outing.outing_id not in in_domain_ids:
            domain = domains[outing.outing_id]
            reason = _out_of_domain(outing, domain, read.domain_start_date)
            exclusions.append(Exclusion(outing.outing_id, reason))
    present = {outing.outing_id for outing in read.outings}
    for entry in read.refused:
        if entry.outing_id not in present:
            exclusions.append(Exclusion(entry.outing_id, f"refusée : {entry.reason}"))
    return tuple(exclusions)


def prepare_backtest(
    manifest_path: Path,
    curve_path: Path,
    *,
    commit: str,
    tree_modified: bool,
    retrieved_at: datetime | None = None,
) -> Preparation:
    """Lit, contrôle et déclare, **sans rien écrire** (``0010`` D14, D0, D2.1, D2.5,
    D2.6, D8 ; précisions de M4b-5) : le manifeste et la courbe (leurs erreurs
    remontent telles quelles) ; les domaines, la rétention et les performances ; le
    jeu de répétabilité (parcours, référence, une seule par parcours) ; les exclusions
    et leurs motifs ; les deux fichiers de la courbe, lus à ``retrieved_at`` ; la
    DÉCLARATION de v0 brut seul, des onze horloges et de l'appariement par défaut."""
    read = load_manifest(manifest_path)
    curve = read_curve(curve_path, ParameterSet(PROJECTION_PARAMETER_SPECS))
    domains = outing_domains(read)
    by_id = {domain.outing_id: domain for domain in domains}
    decisions = retain_outings(read.outings)
    in_domain_ids = {
        outing.outing_id
        for outing in read.outings
        if in_domain(
            outing, by_id[outing.outing_id].dplus_per_km, read.domain_start_date
        )
    }
    performances = group_performances(decisions, in_domain_ids)
    _repeatability_references(performances)
    exclusions = _exclusions(read, decisions, by_id, in_domain_ids)
    csv, meta = curve_artifacts(curve_path, curve, retrieved_at=retrieved_at)
    declaration = Declaration(
        commit=commit,
        tree_modified=tree_modified,
        protocol_record=PROTOCOL_RECORD,
        athlete_ref=read.athlete_ref,
        matching=ParameterSet(MATCHING_PARAMETER_SPECS),
        clocks=CLOCKS,
        curve_ref=curve.curve_ref,
        curve=csv,
        curve_metadata=meta,
        manifest=read.source,
        performances=tuple(declared_performance(p) for p in performances),
        exclusions=exclusions,
        models=(V0_RAW_MODEL,),
        experiment=None,
    )
    return Preparation(read, curve, decisions, domains, performances, declaration)


# ---------------------------------------------------------------------------
# Exécution : DÉCLARATION, calcul, RÉSULTAT ou ÉCHEC
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class OutingRun:
    """Une sortie scorée, et ce qui a servi à la scorer : la chaîne de ``mperf match
    --curve`` (profil et géométrie de sa référence, ou de sa trace sans référence)."""

    outing: Outing
    profile: RouteProfile
    geometry: ReferenceGeometry
    trace: RecordedTrace
    series: TraceSeries
    partition: ClockPartition
    match: MatchResult
    passages: PassageMatchResult
    scores: OutingScores


@dataclass(frozen=True)
class BacktestRun:
    """Une exécution enregistrée : sa préparation, sa DÉCLARATION et son RÉSULTAT,
    les sorties scorées et non scorées, les références D8 par parcours, et le sceau
    (l'empreinte de la ligne du RÉSULTAT, la dernière du journal)."""

    preparation: Preparation
    declaration_event: RegistryEvent
    result_event: RegistryEvent
    outings: tuple[OutingRun, ...]
    unscored: tuple[Exclusion, ...]
    references: tuple[tuple[str, RepeatabilityReference], ...]
    seal: str


def failure_reason(error: BaseException) -> str:
    """Le motif sans chemin d'un ÉCHEC technique (précision de D14, M4b-5 ; règle 1 de
    ``CLAUDE.md``) : une ``OSError`` réduite à son type et à son ``errno`` (son message
    nomme un chemin) ; sinon « <type> : <message> », ou le type seul si le message est
    vide (``KeyboardInterrupt()``, ``ValueError()``)."""
    name = type(error).__name__
    if isinstance(error, OSError):
        return f"{name} (errno {error.errno})"
    message = str(error)
    return f"{name} : {message}" if message else name


def _score(
    read: ManifestReadResult,
    curve: CurveReadResult,
    outing: Outing,
    trace: RecordedTrace,
    profiles: dict[Path, tuple[RouteProfile, ReferenceGeometry]],
    generated_at: datetime,
) -> OutingRun:
    """La chaîne de ``mperf match --curve`` sur une sortie tracée (``0010`` D3) : avec
    référence, le tracé de son fichier (lu une fois par chemin) et l'usage sur ce
    profil ; sans référence, la grille sur sa trace enregistrée, sans usage."""
    reference = outing.reference
    usage: RouteProfile | None = None
    if reference is not None:
        path = read.artifact_paths[reference.artifact.source.content_hash]
        if path not in profiles:
            route = read_gpx(path).route
            profiles[path] = (
                build_profile(route, ParameterSet(PROFILE_PARAMETER_SPECS)),
                reference_geometry(route),
            )
        profile, geometry = profiles[path]
        usage = profile
    else:
        route = trace_route(trace, outing.traces[0].source.identifier)
        profile = build_profile(route, ParameterSet(PROFILE_PARAMETER_SPECS))
        geometry = reference_geometry(route)
    series = build_series(trace)
    partition = clock_partition(trace, series)
    match = match_trace(
        geometry,
        profile,
        trace,
        series,
        partition,
        ParameterSet(MATCHING_PARAMETER_SPECS),
    )
    passages = observe_passages(match, geometry, profile, trace, series, partition)
    scores = v0_scores(
        usage,
        trace,
        match,
        passages,
        partition,
        curve.curve,
        curve_ref=curve.curve_ref,
        generated_at=generated_at,
    )
    return OutingRun(
        outing, profile, geometry, trace, series, partition, match, passages, scores
    )


def _references(
    performances: tuple[Performance, ...], scored: dict[str, OutingRun]
) -> tuple[tuple[str, RepeatabilityReference], ...]:
    """La référence D8 de chaque parcours du jeu de répétabilité, dans l'ordre des noms
    (``0010`` D8 ; précisions de D8.1 et de D14, M4b-5 ; décisions Q16 et Q18) : un
    jour de plusieurs sorties entre sans segments ; un jour d'une sortie scorée, avec
    ses segments admis ; un jour d'une sortie non scorée n'entre pas ; un parcours dont
    aucun jour n'entre garde une référence vide."""
    declared = _repeatability_references(performances)
    days: dict[str, list[RepeatabilityDay]] = {route_id: [] for route_id in declared}
    for performance in performances:
        routes = sorted(
            {
                outing.route_id
                for outing in performance.outings
                if outing.dataset is DataSet.REPEATABILITY and outing.route_id
            }
        )
        for route_id in routes:
            if performance.is_multi_outing:
                day = RepeatabilityDay(performance, declared[route_id], None)
            else:
                run = scored.get(performance.outings[0].outing_id)
                if run is None:
                    continue
                segments = run.scores.observation.segments
                day = RepeatabilityDay(performance, declared[route_id], segments)
            days[route_id].append(day)
    return tuple(
        (route_id, repeatability_reference(declared[route_id], days[route_id]))
        for route_id in declared
    )


def _evaluate(
    preparation: Preparation,
    registry_root: Path,
    declared: RegistryEvent,
    recorded_at: datetime | None,
) -> tuple[
    tuple[OutingRun, ...],
    tuple[Exclusion, ...],
    tuple[tuple[str, RepeatabilityReference], ...],
    RegistryEvent,
]:
    """Étape 3 de ``run_backtest`` : chaque sortie déclarée scorée ou écartée avec son
    motif, les références D8, puis le RÉSULTAT ; les prévisions datées de la
    DÉCLARATION."""
    read = preparation.manifest
    refused = {entry.outing_id: entry.reason for entry in read.refused}
    profiles: dict[Path, tuple[RouteProfile, ReferenceGeometry]] = {}
    runs: list[OutingRun] = []
    unscored: list[Exclusion] = []
    for performance in preparation.performances:
        for outing in performance.outings:
            trace = read.traces.get(outing.outing_id)
            if trace is None:
                reason = refused.get(outing.outing_id, _UNTRACED)
                unscored.append(Exclusion(outing.outing_id, reason))
                continue
            runs.append(
                _score(
                    read,
                    preparation.curve,
                    outing,
                    trace,
                    profiles,
                    declared.recorded_at,
                )
            )
    references = _references(
        preparation.performances, {run.outing.outing_id: run for run in runs}
    )
    outcomes = tuple(
        OutingOutcome(
            run.outing.outing_id, run.match.coverage, ((ModelKind.V0_RAW, run.scores),)
        )
        for run in runs
    )
    result = append_result(
        registry_root,
        declared.number,
        outcomes,
        unscored=tuple(unscored),
        references=references,
        recorded_at=recorded_at,
    )
    return tuple(runs), tuple(unscored), references, result


def run_backtest(
    preparation: Preparation,
    registry_root: Path,
    *,
    recorded_at: datetime | None = None,
) -> BacktestRun:
    """L'exécution enregistrée (``0010`` D14 et ses précisions de M4b-5 ; décisions
    Q15 et Q17), dans cet ordre : la DÉCLARATION, **avant tout calcul** (ses erreurs
    remontent telles quelles) ; sans performance, un ÉCHEC « non évaluable » ; puis le
    calcul et le RÉSULTAT — une exception ou une interruption au clavier y devient un
    ÉCHEC technique au motif sans chemin. Chaque ÉCHEC finit en ``BacktestError``, qui
    publie l'empreinte de sa ligne ; le sceau d'une exécution réussie est l'empreinte
    de la ligne du RÉSULTAT. Le recoupement des références D8 avec la référence
    déclarée des sorties est fait par l'accord du registre, à l'ajout du RÉSULTAT."""
    declared = append_declaration(
        registry_root, preparation.declaration, recorded_at=recorded_at
    )
    if not preparation.performances:
        failure = append_failure(
            registry_root,
            declared.number,
            Failure(FailureKind.NOT_EVALUABLE, _NO_PERFORMANCE),
            recorded_at=recorded_at,
        )
        raise BacktestError(
            f"{_NO_PERFORMANCE} : ÉCHEC enregistré (événement {failure.number} ; "
            f"dernière ligne sha256 {line_hash(failure)})."
        )
    try:
        outings, unscored, references, result = _evaluate(
            preparation, registry_root, declared, recorded_at
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
            f"échec de l'exécution, ÉCHEC enregistré (événement {failure.number} ; "
            f"dernière ligne sha256 {line_hash(failure)}) : {reason}"
        ) from error
    return BacktestRun(
        preparation,
        declared,
        result,
        outings,
        unscored,
        references,
        seal=line_hash(result),
    )
