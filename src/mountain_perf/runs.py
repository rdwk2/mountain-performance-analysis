"""Les enchaînements des commandes, communs à ``mperf`` et à l'interface : ``mperf
project`` (M5-1) et ``mperf match`` (M5-2).

Une commande et une page qui font la même chose appellent la même fonction, donc dans
le même ordre, et la même erreur sort la première. Ce module importe les seuls modules
purs de ``backtest/`` (appariement, passages, scores, calendrier), jamais le registre
ni l'exécution enregistrée.
"""

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path

from mountain_perf.backtest.calendar import civil_date
from mountain_perf.backtest.geometry import ReferenceGeometry, reference_geometry
from mountain_perf.backtest.matching import MATCHING_PARAMETER_SPECS
from mountain_perf.backtest.passages import observe_passages
from mountain_perf.backtest.scoring import report_clocks, v0_scores
from mountain_perf.backtest.segments import match_trace
from mountain_perf.clocks import clock_partition
from mountain_perf.gpx import (
    PROFILE_PARAMETER_SPECS,
    GpxReadResult,
    ProfileBuildResult,
    build_profile,
    build_profile_with_diagnostics,
    read_gpx,
)
from mountain_perf.gpx.trace_reader import read_trace
from mountain_perf.model import (
    PROJECTION_PARAMETER_SPECS,
    CurveReadResult,
    ProjectionDiagnostics,
    project_with_diagnostics,
    read_curve,
    route_endpoints,
)
from mountain_perf.schemas import (
    Clock,
    ClockPartition,
    CurveProvenance,
    MatchResult,
    OutingScores,
    ParameterSet,
    PassageMatchResult,
    Projection,
    RecordedTrace,
    RouteProfile,
)
from mountain_perf.series import TraceSeries, build_series


@dataclass(frozen=True)
class RouteProjection:
    """Tout ce que ``mperf project`` lit et calcule : le GPX lu, le profil et ses
    diagnostics, la courbe lue, la projection et ses diagnostics."""

    read: GpxReadResult
    built: ProfileBuildResult
    curve: CurveReadResult
    projection: Projection
    diagnostics: ProjectionDiagnostics


def project_route(
    route_path: Path,
    curve_path: Path,
    profile_values: Mapping[str, float],
    projection_values: Mapping[str, float],
) -> RouteProjection:
    """Projette le tracé ``route_path`` avec la courbe ``curve_path``.

    Dans l'ordre de ``mperf project`` : les deux jeux de paramètres (les valeurs
    absentes prennent le défaut de leur spec), la lecture du GPX, le profil, la lecture
    de la courbe, la projection. Les erreurs remontent telles quelles.
    """
    grid_parameters = ParameterSet(PROFILE_PARAMETER_SPECS, profile_values)
    model_parameters = ParameterSet(PROJECTION_PARAMETER_SPECS, projection_values)
    read = read_gpx(route_path)
    built = build_profile_with_diagnostics(read.route, grid_parameters)
    curve = read_curve(curve_path, model_parameters)
    projection, diagnostics = project_with_diagnostics(
        built.profile,
        curve.curve,
        model_parameters,
        curve_ref=curve.curve_ref,
        endpoints=route_endpoints(read.route),
    )
    return RouteProjection(read, built, curve, projection, diagnostics)


@dataclass(frozen=True)
class OutingMatch:
    """Tout ce que ``mperf match`` lit et calcule avant les scores : les paramètres de
    l'appariement, la courbe lue si elle est donnée, le préparé lu et son profil aux
    défauts de ``0008``, la géométrie de référence, la trace, ses séries et sa
    partition, l'appariement et les passages."""

    parameters: ParameterSet
    curve: CurveReadResult | None
    read: GpxReadResult
    profile: RouteProfile
    geometry: ReferenceGeometry
    trace: RecordedTrace
    series: TraceSeries
    partition: ClockPartition
    result: MatchResult
    passages: PassageMatchResult


def match_outing(
    route_path: Path,
    trace_path: Path,
    curve_path: Path | None,
    matching_values: Mapping[str, float],
) -> OutingMatch:
    """Apparie la trace ``trace_path`` au préparé ``route_path``.

    Dans l'ordre de ``mperf match`` : les paramètres de l'appariement (les valeurs
    absentes prennent le défaut de leur spec) ; la courbe, si ``curve_path`` est
    donné, lue avant tout le reste (une erreur de lecture ne laisse rien) ; le préparé,
    son profil, sa géométrie ; la trace, ses séries, sa partition ; l'appariement, puis
    les passages. Les erreurs remontent telles quelles.
    """
    parameters = ParameterSet(MATCHING_PARAMETER_SPECS, matching_values)
    curve = None
    if curve_path is not None:
        curve = read_curve(curve_path, ParameterSet(PROJECTION_PARAMETER_SPECS))
    read = read_gpx(route_path)
    profile = build_profile(read.route, ParameterSet(PROFILE_PARAMETER_SPECS))
    geometry = reference_geometry(read.route)
    trace = read_trace([trace_path])
    series = build_series(trace)
    partition = clock_partition(trace, series)
    result = match_trace(geometry, profile, trace, series, partition, parameters)
    passages = observe_passages(result, geometry, profile, trace, series, partition)
    return OutingMatch(
        parameters,
        curve,
        read,
        profile,
        geometry,
        trace,
        series,
        partition,
        result,
        passages,
    )


@dataclass(frozen=True)
class OutingCheck:
    """Le contrôle d'une sortie par v0 brut, à l'effort 1 : ses scores, les horloges du
    rapport, le jour civil à Paris du premier instant de la trace — le jour que teste
    ``in_curve_window`` — et si ce jour tombe dans la fenêtre d'estimation de la courbe
    (``0010`` D2.2)."""

    scores: OutingScores
    clocks: tuple[Clock, ...]
    day: date
    in_curve_window: bool


def in_curve_window(start_time: datetime, estimation: CurveProvenance) -> bool:
    """La règle de ``0010`` D2.2 : le jour civil à Paris de ``start_time`` est entre
    ``date_from`` et ``date_to`` de la fenêtre d'estimation, bornes comprises. Un
    instant naïf lève ``ContractError``."""
    return estimation.date_from <= civil_date(start_time) <= estimation.date_to


def check_outing(match: OutingMatch, *, with_reference: bool = True) -> OutingCheck:
    """Les scores de v0 brut de l'appariement ``match`` (le préparé pour référence, ou
    aucune avec ``with_reference=False``, ``0010`` D3), les horloges du rapport, le jour
    de la sortie et la règle de la fenêtre. Lève ``ValueError`` si l'appariement n'a
    pas de courbe."""
    curve = match.curve
    if curve is None:
        raise ValueError("check_outing : l'appariement n'a pas de courbe.")
    scores = v0_scores(
        match.profile if with_reference else None,
        match.trace,
        match.result,
        match.passages,
        match.partition,
        curve.curve,
        curve_ref=curve.curve_ref,
    )
    return OutingCheck(
        scores,
        report_clocks(match.result),
        civil_date(match.trace.start_time),
        in_curve_window(match.trace.start_time, curve.curve.estimation),
    )
