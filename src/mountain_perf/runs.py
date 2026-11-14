"""Les enchaînements des commandes, communs à ``mperf`` et à l'interface : ``mperf
project`` (M5-1) et ``mperf match`` (M5-2) ; le chargement du corpus de la règle à
l'origine (OG-1) ; les sources de courbe des pages et de ``mperf project --at`` : la
courbe à l'origine, la courbe d'une plage, la courbe en mémoire (OG-UI).

Une commande et une page qui font la même chose appellent la même fonction, donc dans
le même ordre, et la même erreur sort la première. Ce module importe les seuls modules
purs de ``backtest/`` (appariement, passages, scores, calendrier), jamais le registre
ni l'exécution enregistrée.
"""

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Final

from mountain_perf.backtest.calendar import ORIGIN_LAG, civil_date
from mountain_perf.backtest.calendar import origin as civil_origin
from mountain_perf.backtest.geometry import ReferenceGeometry, reference_geometry
from mountain_perf.backtest.matching import MATCHING_PARAMETER_SPECS
from mountain_perf.backtest.passages import observe_passages
from mountain_perf.backtest.scoring import report_clocks, v0_scores
from mountain_perf.backtest.segments import match_trace
from mountain_perf.clocks import clock_partition
from mountain_perf.estimation.curve import (
    CURVE_ESTIMATION_PARAMETER_SPECS,
    SUPPORT_THRESHOLD_MIN,
    BinValue,
    CurveEstimate,
    CurveSelection,
    NoCurve,
    curve_file_rows,
    curve_provenance,
    estimate_curve_outcome,
    estimation_document,
    select_candidates,
)
from mountain_perf.estimation.decision import decide_on_index
from mountain_perf.estimation.origin import (
    CurveCorpus,
    IntervalsOf,
    OriginEstimate,
    OriginWindow,
    candidate_intervals,
    check_origin,
    estimate_at_origin,
    origin_companion,
    window_lower_bound,
)
from mountain_perf.gpx import (
    PROFILE_PARAMETER_SPECS,
    GpxReadResult,
    ProfileBuildResult,
    build_profile,
    build_profile_with_diagnostics,
    read_gpx,
)
from mountain_perf.gpx.trace_reader import read_trace
from mountain_perf.ingest.interim import (
    read_index_with_sha256,
    read_recording_with_sha256,
)
from mountain_perf.model import (
    PROJECTION_PARAMETER_SPECS,
    CurveReadResult,
    ProjectionDiagnostics,
    project_with_diagnostics,
    read_curve,
    route_endpoints,
)
from mountain_perf.model.curve_io import (
    CurveError,
    check_curve_rows,
    curve_documents,
    freeze_companion,
    read_curve_documents,
)
from mountain_perf.model.engine import portion_out_of_support_time_share
from mountain_perf.schemas import (
    ActivityIndex,
    Clock,
    ClockPartition,
    CurveProvenance,
    IndexedActivity,
    MatchResult,
    OutingScores,
    ParameterSet,
    PassageMatchResult,
    Projection,
    RecordedTrace,
    RouteProfile,
    Sport,
)
from mountain_perf.series import TraceSeries, build_series
from mountain_perf.validation import ContractError

FOLDER_ATHLETE: Final = "athlète du dossier"
"""L'étiquette de l'athlète des courbes en mémoire (OG-UI) : un dossier de données est
celui d'un athlète (rdw, 2026-11-12) ; elle ne s'écrit nulle part."""

MEMORY_COMMIT: Final = "en mémoire"
"""Le commit que demandent ``origin_companion`` et ``estimation_document`` pour une
courbe en mémoire (OG-UI) : ``freeze_companion`` le retire ; il ne se lit nulle part."""

RANGE_NO_CANDIDATE: Final = (
    "aucune activité candidate : aucun enregistrement des types demandés dans la "
    "fenêtre."
)
"""Le message de ``mperf curve --from --to`` sans candidate (M6b ; dans la bibliothèque
depuis OG-UI)."""


def now() -> datetime:
    """L'instant présent, en UTC : l'horloge des pages (OG-UI), que leurs tests
    remplacent."""
    return datetime.now(UTC)


def paris_today() -> date:
    """Le jour à Paris de :func:`now`."""
    return civil_date(now())


@dataclass(frozen=True)
class CourseOrigin:
    """L'origine d'une course (OG-UI) : ``day``, le jour de la course ;
    ``effective_day``, ``day`` ou, au-delà d'aujourd'hui + 7 jours, aujourd'hui + 7
    jours (l'origine bornée à aujourd'hui, rdw, 2026-11-12) ; ``origin_day``,
    ``effective_day`` − 7 jours ; ``origin``, 00:00 à Paris d'``origin_day``, en UTC
    (``0010`` D2.5) ; ``bounded``, vrai si ``day`` est au-delà d'aujourd'hui + 7
    jours."""

    day: date
    effective_day: date
    origin_day: date
    origin: datetime
    bounded: bool


def course_origin(day: date, today: date) -> CourseOrigin:
    """L'origine de la course du jour ``day``, aujourd'hui étant ``today`` (le jour à
    Paris de l'horloge) (OG-UI)."""
    limit = today + ORIGIN_LAG
    bounded = day > limit
    effective_day = limit if bounded else day
    origin_day = effective_day - ORIGIN_LAG
    return CourseOrigin(
        day, effective_day, origin_day, civil_origin(effective_day), bounded
    )


@dataclass(frozen=True)
class CurveBytes:
    """Une courbe en mémoire (OG-UI) : les octets canoniques de son CSV et de son
    compagnon figé (``freeze_companion``, sans ``generated_at`` ni
    ``estimation.commit``), son nom, l'instant de son estimation, donné à la
    lecture."""

    csv: bytes
    companion: bytes
    name: str
    generated_at: datetime


def read_curve_source(
    source: Path | CurveBytes, parameters: ParameterSet
) -> CurveReadResult:
    """``read_curve`` d'un fichier ; ``read_curve_documents`` d'une courbe en mémoire,
    avec son instant (OG-UI)."""
    if isinstance(source, CurveBytes):
        return read_curve_documents(
            source.csv,
            source.companion,
            source.name,
            parameters,
            generated_at=source.generated_at,
        )
    return read_curve(source, parameters)


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
    curve: Path | CurveBytes,
    profile_values: Mapping[str, float],
    projection_values: Mapping[str, float],
) -> RouteProjection:
    """Projette le tracé ``route_path`` avec la courbe ``curve``, un fichier ou une
    courbe en mémoire (OG-UI).

    Dans l'ordre de ``mperf project`` : les deux jeux de paramètres (les valeurs
    absentes prennent le défaut de leur spec), la lecture du GPX, le profil, la lecture
    de la courbe, la projection. Les erreurs remontent telles quelles.
    """
    grid_parameters = ParameterSet(PROFILE_PARAMETER_SPECS, profile_values)
    model_parameters = ParameterSet(PROJECTION_PARAMETER_SPECS, projection_values)
    read = read_gpx(route_path)
    built = build_profile_with_diagnostics(read.route, grid_parameters)
    read_result = read_curve_source(curve, model_parameters)
    projection, diagnostics = project_with_diagnostics(
        built.profile,
        read_result.curve,
        model_parameters,
        curve_ref=read_result.curve_ref,
        endpoints=route_endpoints(read.route),
    )
    return RouteProjection(read, built, read_result, projection, diagnostics)


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
    curve: Path | CurveBytes | None,
    matching_values: Mapping[str, float],
) -> OutingMatch:
    """Apparie la trace ``trace_path`` au préparé ``route_path``.

    Dans l'ordre de ``mperf match`` : les paramètres de l'appariement (les valeurs
    absentes prennent le défaut de leur spec) ; la courbe ``curve``, un fichier ou une
    courbe en mémoire (OG-UI), si elle est donnée, lue avant tout le reste (une erreur
    de lecture ne laisse rien) ; le préparé, son profil, sa géométrie ; la trace, ses
    séries, sa partition ; l'appariement, puis les passages. Les erreurs remontent
    telles quelles.
    """
    parameters = ParameterSet(MATCHING_PARAMETER_SPECS, matching_values)
    read_result = None
    if curve is not None:
        read_result = read_curve_source(curve, ParameterSet(PROJECTION_PARAMETER_SPECS))
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
        read_result,
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


def _load_corpus(
    folder: Path,
    athlete_ref: str,
    keep: Callable[[ActivityIndex], Callable[[IndexedActivity], bool]],
) -> CurveCorpus:
    """La boucle de lecture commune des corpus (OG-UI) : l'index, puis ``keep(index)``,
    appelé une fois, qui rend le prédicat des entrées (qui ont un enregistrement) dont
    l'enregistrement se lit, dans l'ordre de l'index ; le corpus attesté par les
    empreintes des octets lus. Les erreurs : celles de :func:`load_curve_corpus`."""
    try:
        index, index_sha256 = read_index_with_sha256(folder)
    except ValueError as error:
        raise CurveError(
            f"index d'interim/ : {error} ; relancer `mperf ingest`."
        ) from error
    kept = keep(index)
    recordings = {}
    digests = {}
    for entry in index.entries:
        if not entry.has_recording or not kept(entry):
            continue
        ref = entry.activity_ref
        try:
            recordings[ref], digests[ref] = read_recording_with_sha256(folder, ref)
        except ValueError as error:
            raise CurveError(
                f"activité {ref} : {error} ; relancer `mperf ingest`."
            ) from error
    return CurveCorpus(athlete_ref, index, index_sha256, recordings, digests)


def load_curve_corpus(
    folder: Path,
    athlete_ref: str,
    activity_types: frozenset[str],
    origin: datetime,
    window: OriginWindow,
) -> CurveCorpus:
    """Le corpus de ``athlete_ref`` pour la règle à l'origine (OG-1,
    ``docs/decisions/0020``), attesté par les empreintes des octets lus sous
    ``folder`` : l'index, puis, dans son ordre, l'enregistrement de chaque entrée des
    types choisis qui en a un, **sauf** si l'index la fait finir (départ + écoulé) à
    l'origine ou après, ou avant la borne basse ; une entrée sans écoulé est lue. Ce
    sont exactement les décisions que ``select_at_origin`` prend sur l'index seul :
    ``decide_on_index``, écrite une fois (OG-2, ``estimation/decision.py``).

    Un document qui ne se relit pas (une ``ValueError`` : ``CodecError``,
    ``ContractError``) devient une ``CurveError`` qui le nomme et dit de relancer
    ``mperf ingest`` ; une ``InterimError`` (fichier absent, document qui porte un autre
    identifiant que son nom) remonte telle quelle.
    """
    moment = check_origin(origin)
    lower_bound = window_lower_bound(moment, window)

    def keep(index: ActivityIndex) -> Callable[[IndexedActivity], bool]:
        def kept(entry: IndexedActivity) -> bool:
            if entry.source_activity_type not in activity_types:
                return False
            index_end = (
                None
                if entry.elapsed_duration_s is None
                else entry.start_time + timedelta(seconds=entry.elapsed_duration_s)
            )
            return decide_on_index(index_end, moment, lower_bound) is None

        return kept

    return _load_corpus(folder, athlete_ref, keep)


def load_athlete_corpus(folder: Path, activity_types: frozenset[str]) -> CurveCorpus:
    """Le corpus complet du dossier (OG-UI) : l'index, puis l'enregistrement de chaque
    entrée des types choisis qui en a un, dans l'ordre de l'index ; l'athlète
    :data:`FOLDER_ATHLETE`. Les erreurs : celles de :func:`load_curve_corpus`."""

    def keep(index: ActivityIndex) -> Callable[[IndexedActivity], bool]:
        return lambda entry: entry.source_activity_type in activity_types

    return _load_corpus(folder, FOLDER_ATHLETE, keep)


def load_range_corpus(
    folder: Path, athlete_ref: str, selection: CurveSelection
) -> CurveCorpus:
    """Le corpus d'une plage (OG-UI) : l'index, puis l'enregistrement de chaque
    candidate de ``select_candidates(index, selection)``, dans l'ordre de l'index ; les
    erreurs : celles de :func:`load_curve_corpus`. Sans candidate,
    ``CurveError(RANGE_NO_CANDIDATE)``, juste après la lecture de l'index, avant de
    lire un enregistrement et de construire le corpus."""

    def keep(index: ActivityIndex) -> Callable[[IndexedActivity], bool]:
        refs = {entry.activity_ref for entry in select_candidates(index, selection)}
        if not refs:
            raise CurveError(RANGE_NO_CANDIDATE)
        return lambda entry: entry.activity_ref in refs

    return _load_corpus(folder, athlete_ref, keep)


def index_digest(folder: Path) -> str:
    """L'empreinte de l'index d'``interim/`` sous ``folder`` (OG-UI) : la clé de l'état
    du corpus qu'une page garde. Un index qui ne se relit pas : la ``CurveError`` de
    :func:`load_curve_corpus`."""
    try:
        return read_index_with_sha256(folder)[1]
    except ValueError as error:
        raise CurveError(
            f"index d'interim/ : {error} ; relancer `mperf ingest`."
        ) from error


def curve_selection(
    date_from: date | None = None, date_to: date | None = None
) -> CurveSelection:
    """La sélection de ``mperf curve`` sans option (OG-UI) : ``trail_running``, ni
    durée, ni plafond, ni centre de FC, valeur « somme » ; avec ``date_from`` et
    ``date_to``, une plage."""
    return CurveSelection(
        frozenset({"trail_running"}),
        date_from,
        date_to,
        None,
        None,
        None,
        None,
        BinValue.POOLED,
    )


@dataclass(frozen=True)
class OriginCurve:
    """La courbe à l'origine d'une course (OG-UI) : l'origine, la fenêtre, ce que la
    règle a rendu, et la courbe en mémoire, ``None`` en cas d'absence."""

    course: CourseOrigin
    window: OriginWindow
    result: OriginEstimate
    curve: CurveBytes | None


def origin_curve(
    corpus: CurveCorpus,
    course: CourseOrigin,
    window: OriginWindow,
    *,
    generated_at: datetime,
    intervals_of: IntervalsOf | None = None,
) -> OriginCurve:
    """La courbe à l'origine de ``course`` sur ``corpus`` (OG-UI), aux défauts de
    ``mperf curve --at`` (sélection, paramètres, seuil des diagnostics) : la règle,
    puis, sauf absence, le compagnon, les octets canoniques et le compagnon figé, sous
    le nom ``origine-<jour effectif>-<w<W>|all>.csv``. Une courbe non projetable au
    seuil des diagnostics a ses octets : la lecture, au seuil de l'appelant, en
    décide. Rien n'est écrit."""
    selection = curve_selection()
    parameters = ParameterSet(CURVE_ESTIMATION_PARAMETER_SPECS)
    profile = ParameterSet(PROFILE_PARAMETER_SPECS)
    result = estimate_at_origin(
        corpus,
        corpus.athlete_ref,
        course.origin,
        window,
        selection,
        parameters,
        profile,
        intervals_of=intervals_of,
    )
    if result.estimate is None:
        return OriginCurve(course, window, result, None)
    provenance, document = origin_companion(
        result,
        corpus,
        selection,
        parameters,
        profile,
        commit=MEMORY_COMMIT,
        generated_at=generated_at,
    )
    documents = curve_documents(result.rows, Sport.FOOT, provenance, document)
    label = "all" if isinstance(window, str) else f"w{window}"
    name = f"origine-{course.effective_day.isoformat()}-{label}.csv"
    curve = CurveBytes(
        documents.csv, freeze_companion(documents.companion), name, generated_at
    )
    return OriginCurve(course, window, result, curve)


def range_estimate(
    corpus: CurveCorpus,
    selection: CurveSelection,
    parameters: ParameterSet,
    profile_parameters: ParameterSet,
    *,
    support_threshold_min: float,
    intervals_of: IntervalsOf | None = None,
) -> tuple[tuple[IndexedActivity, ...], CurveEstimate | NoCurve]:
    """Les candidates de la plage et leur estimation, celle de ``0017`` (OG-UI) :
    ``select_candidates(corpus.index, selection)``, leurs intervalles par
    :func:`~mountain_perf.estimation.origin.candidate_intervals`, puis
    ``estimate_curve_outcome`` au seuil donné. Sans candidate :
    ``CurveError(RANGE_NO_CANDIDATE)``, avant tout appel du fournisseur (sa seule
    ``CurveError`` : une absence d'estimation est un ``NoCurve``)."""
    entries = select_candidates(corpus.index, selection)
    if not entries:
        raise CurveError(RANGE_NO_CANDIDATE)
    refs = [entry.activity_ref for entry in entries]
    intervals = candidate_intervals(
        corpus,
        refs,
        selection,
        parameters,
        profile_parameters,
        intervals_of=intervals_of,
    )
    outcome = estimate_curve_outcome(
        intervals,
        refs,
        selection,
        parameters,
        support_threshold_min=support_threshold_min,
    )
    return entries, outcome


def range_companion(
    estimate: CurveEstimate,
    entries: Sequence[IndexedActivity],
    corpus: CurveCorpus,
    selection: CurveSelection,
    parameters: ParameterSet,
    profile_parameters: ParameterSet,
    *,
    commit: str,
    generated_at: datetime,
    support_threshold_min: float,
) -> tuple[CurveProvenance, dict[str, object]]:
    """La provenance et le document d'estimation d'une courbe sur une plage, ceux que
    ``mperf curve --from --to`` écrit (OG-UI) : une fonction pure. Une sélection sans
    ses deux dates : ``ContractError``."""
    if selection.date_from is None or selection.date_to is None:
        raise ContractError("selection : une plage de dates est requise.")
    retained = set(estimate.activity_refs)
    # L'entrée et l'enregistrement d'une activité peuvent venir de deux exports
    # (0013, précision 16) : la courbe est choisie sur l'une, mesurée sur l'autre.
    exports = [
        instant
        for entry in entries
        if entry.activity_ref in retained
        for instant in (
            entry.source.retrieved_at,
            corpus.recordings[entry.activity_ref].source.retrieved_at,
        )
    ]
    provenance = curve_provenance(
        estimate,
        selection,
        parameters,
        date_from=selection.date_from,
        date_to=selection.date_to,
        estimator=(
            "mperf curve (M6b) : intervalles de la grille du profil, temps M "
            f"θc, tranches variables, valeur {selection.value.value}"
        ),
        generated_at=generated_at,
        athlete_ref=corpus.athlete_ref,
        support_threshold_min=support_threshold_min,
    )
    rows = curve_file_rows(estimate)
    document = estimation_document(
        estimate,
        selection,
        parameters,
        profile_parameters,
        commit=commit,
        exports_retrieved_at=exports,
        support_error=check_curve_rows(rows, support_threshold_min),
    )
    return provenance, document


@dataclass(frozen=True)
class RangeCurve:
    """La courbe d'une plage de dates (OG-UI), une description, pas une prévision : la
    plage, l'estimation (``None`` en cas d'absence), la raison d'une absence, l'erreur
    de support au seuil des diagnostics, la courbe en mémoire."""

    date_from: date
    date_to: date
    estimate: CurveEstimate | None
    absence_reason: str | None
    support_error: str | None
    curve: CurveBytes | None


def range_curve(
    corpus: CurveCorpus,
    date_from: date,
    date_to: date,
    *,
    generated_at: datetime,
    intervals_of: IntervalsOf | None = None,
) -> RangeCurve:
    """La courbe de la plage ``[date_from ; date_to]`` sur ``corpus`` (OG-UI), aux
    défauts de ``mperf curve --from --to`` : sans candidate, ou sans tranche, une
    absence et sa raison ; sinon les octets canoniques et le compagnon figé, sous le
    nom ``plage-<du>-<au>.csv``. Une plage à l'envers lève le ``ContractError`` de
    ``CurveSelection``. Rien n'est écrit."""
    selection = curve_selection(date_from, date_to)
    parameters = ParameterSet(CURVE_ESTIMATION_PARAMETER_SPECS)
    profile = ParameterSet(PROFILE_PARAMETER_SPECS)
    try:
        entries, outcome = range_estimate(
            corpus,
            selection,
            parameters,
            profile,
            support_threshold_min=SUPPORT_THRESHOLD_MIN,
            intervals_of=intervals_of,
        )
    except CurveError:
        return RangeCurve(date_from, date_to, None, RANGE_NO_CANDIDATE, None, None)
    if isinstance(outcome, NoCurve):
        return RangeCurve(date_from, date_to, None, outcome.reason, None, None)
    rows = curve_file_rows(outcome)
    provenance, document = range_companion(
        outcome,
        entries,
        corpus,
        selection,
        parameters,
        profile,
        commit=MEMORY_COMMIT,
        generated_at=generated_at,
        support_threshold_min=SUPPORT_THRESHOLD_MIN,
    )
    documents = curve_documents(rows, Sport.FOOT, provenance, document)
    curve = CurveBytes(
        documents.csv,
        freeze_companion(documents.companion),
        f"plage-{date_from}-{date_to}.csv",
        generated_at,
    )
    return RangeCurve(
        date_from,
        date_to,
        outcome,
        None,
        check_curve_rows(rows, SUPPORT_THRESHOLD_MIN),
        curve,
    )


def outing_day(trace_path: Path) -> date:
    """Le jour à Paris du premier instant de la trace, celui de :func:`check_outing`
    (OG-UI)."""
    return civil_date(read_trace([trace_path]).start_time)


def outing_support_share(match: OutingMatch) -> float:
    """La part du temps prévu hors du support de la courbe de ``match`` sur son
    préparé, au seuil de lecture par défaut (OG-UI) ; ``ValueError`` sans courbe, comme
    :func:`check_outing`."""
    curve = match.curve
    if curve is None:
        raise ValueError("check_outing : l'appariement n'a pas de courbe.")
    return portion_out_of_support_time_share(
        match.profile, curve.curve, ParameterSet(PROJECTION_PARAMETER_SPECS), None
    )
