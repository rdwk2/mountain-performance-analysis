"""Les textes des rapports de ``mperf profile`` et ``mperf project``, communs à la
commande et à l'interface : la commande les imprime, l'interface les affiche tels
quels. Les lignes de l'origine, celles d'une plage et les avertissements d'une courbe
en mémoire (OG-UI)."""

from collections import Counter
from datetime import date, datetime
from typing import Final

from mountain_perf.estimation.curve import CurveEstimate
from mountain_perf.estimation.origin import (
    PARIS,
    OriginEstimate,
    OriginHistory,
    TemporalDecision,
    cold_start_warning,
)
from mountain_perf.gpx import ProfileBuildResult
from mountain_perf.model import PROJECTION_PARAMETER_SPECS, CurveReadResult
from mountain_perf.runs import OriginCurve, OutingMatch, RangeCurve, RouteProjection
from mountain_perf.schemas import ParameterSet, Projection
from mountain_perf.units import (
    format_count,
    format_duration,
    format_grade,
    format_share,
)

OUT_OF_SUPPORT_MARKER: Final = 0.5
"""Le repère de la part du temps prévu hors support, au-delà duquel les pages et
``mperf project --at`` avertissent (cadrage de l'origine glissante, Q2 bis) ; celui du
rapport D15 du mode glissant."""


def grid_lines(result: ProfileBuildResult) -> tuple[str, str]:
    """Les lignes « grille » et « lissage » des rapports de ``mperf profile`` et
    ``mperf project``."""
    profile = result.profile
    grid = (
        f"grille       {format_count(profile.distance_m[-1])} m, "
        f"{format_count(len(profile.distance_m))} points, "
        f"pas {format_count(profile.step_m)} m"
    )
    effective = f"{format_count(result.effective_smoothing_window_m)} m effectif"
    if result.smoothing_point_count == 1:
        effective = f"aucun lissage ({effective}, 1 point)"
    else:
        effective += f" ({result.smoothing_point_count} points)"
    smoothing = (
        f"lissage      {format_count(profile.build_parameters['smoothing_window_m'])} "
        f"m demandé → {effective}"
    )
    return grid, smoothing


def projection_summary_lines(run: RouteProjection) -> tuple[str, ...]:
    """La synthèse du rapport de ``mperf project``, de « fichier » à « passages »."""
    result, read_result = run.built, run.curve
    projection, diagnostics = run.projection, run.diagnostics
    profile = result.profile
    estimation = read_result.curve.estimation
    source = read_result.source
    threshold = projection.parameters["curve_min_support_min"]
    total_s = projection.passages[-1].arrival_s
    resolved = len(profile.resolved_points)
    return (
        f"fichier      {profile.source.identifier}   "
        f"sha256 {profile.source.content_hash[:8]}…",
        f"courbe       {source.identifier}   sha256 {source.content_hash[:8]}…",
        f"             {estimation.activity_count} activités, "
        f"{estimation.date_from} → {estimation.date_to}",
        *grid_lines(result),
        support_line(read_result, threshold),
        f"             pentes rencontrées : {format_grade(diagnostics.grade_min)} … "
        f"{format_grade(diagnostics.grade_max)}",
        f"             hors support : "
        f"{format_share(diagnostics.out_of_support_distance_share)} de la distance, "
        f"{format_share(diagnostics.out_of_support_time_share)} du temps",
        f"effort       {projection.parameters['effort']:.2f}",
        f"durée        {format_duration(total_s)}   "
        f"(D+ {format_count(profile.cumulative_ascent_m[-1])} m / "
        f"D− {format_count(profile.cumulative_descent_m[-1])} m)",
        f"passages     {len(projection.passages)}   ({resolved} "
        f"lieu{'x' if resolved != 1 else ''} résolu{'s' if resolved != 1 else ''}, "
        "départ et arrivée synthétisés)",
    )


def passage_lines(projection: Projection) -> tuple[str, ...]:
    """La liste des passages du rapport de ``mperf project`` : distance, nom, temps."""
    width = max(len(format_count(p.point.distance_m)) for p in projection.passages)
    lines = []
    for passage in projection.passages:
        distance = f"{format_count(passage.point.distance_m)} m".rjust(width + 2)
        name = passage.point.point.name.ljust(22)
        lines.append(f"  {distance}   {name} {format_duration(passage.arrival_s)}")
    return tuple(lines)


def paris_minute(moment: datetime) -> str:
    """L'instant à Paris, à la minute."""
    return moment.astimezone(PARIS).strftime("%Y-%m-%d %H:%M")


def origin_summary_lines(result: OriginEstimate, day: date) -> tuple[str, ...]:
    """Les lignes de l'origine de ``mperf curve --at`` (OG-UI : communes avec
    ``mperf project --at`` et les pages) : l'origine et sa fenêtre, les décisions
    (zéros compris), les dernières fins s'il y a une candidate, l'historique selon
    l'index ; sans l'avertissement du démarrage à froid."""
    window = (
        "fenêtre tout le passé"
        if result.lower_bound is None
        else (
            f"fenêtre {result.window} jours, fins depuis le "
            f"{paris_minute(result.lower_bound)} à Paris"
        )
    )
    lines = [f"jour {day} : origine {paris_minute(result.origin)} à Paris ; {window}"]
    decisions = Counter(inspection.decision for inspection in result.inspections)
    details = ", ".join(f"{d.value} {decisions[d]}" for d in TemporalDecision)
    lines.append(f"activités inspectées : {len(result.inspections)} ({details})")
    if result.data_available_at is not None:
        last = result.last_retained_end
        lines.append(
            "  dernières fins, à Paris : candidate "
            f"{paris_minute(result.data_available_at)} ; retenue "
            f"{'aucune' if last is None else paris_minute(last)}"
        )
    history = result.history
    lines.append(
        f"historique à l'origine, selon l'index : {history.foot_index_finished} "
        f"sorties à pied finies ({history.foot_without_index_elapsed} sans écoulé), "
        f"{history.selected_index_finished} des types choisis "
        f"({history.selected_without_index_elapsed} sans écoulé)"
    )
    return tuple(lines)


def retained_line(estimate: CurveEstimate) -> str:
    """Les activités retenues d'une courbe en mémoire et leur temps en mouvement
    (OG-UI)."""
    counts = estimate.counts
    return (
        f"activités retenues : {counts.retained} sur {counts.candidates} candidates ; "
        f"{format_duration(counts.moving_s)} en mouvement"
    )


def _not_projectable(support_error: str | None) -> tuple[str, ...]:
    if support_error is None:
        return ()
    return (f"Courbe non projetable par read_curve : {support_error}",)


def origin_curve_lines(curve: OriginCurve) -> tuple[str, ...]:
    """Les lignes d'une courbe à l'origine (OG-UI) : l'origine bornée s'il y a lieu,
    les lignes de l'origine au jour effectif, les activités retenues, la ligne d'une
    courbe non projetable au seuil des diagnostics."""
    course = curve.course
    lines: list[str] = []
    if course.bounded:
        lines.append(
            f"course le {course.day} : au-delà de 7 jours, origine bornée à "
            f"aujourd'hui (celle d'une course le {course.effective_day}) ; ce n'est "
            "pas la courbe que le backtest prendrait pour cette course"
        )
    lines += origin_summary_lines(curve.result, course.effective_day)
    if curve.result.estimate is not None:
        lines.append(retained_line(curve.result.estimate))
    lines += _not_projectable(curve.result.support_error)
    return tuple(lines)


def range_curve_lines(curve: RangeCurve) -> tuple[str, ...]:
    """Les lignes d'une courbe sur une plage (OG-UI) : la plage, une description ;
    les activités retenues ; la ligne d'une courbe non projetable."""
    lines = [
        f"plage du {curve.date_from} au {curve.date_to} : les départs de ces jours "
        "(jour local), sans contrainte de disponibilité ; une description, pas une "
        "prévision"
    ]
    if curve.estimate is not None:
        lines.append(retained_line(curve.estimate))
    lines += _not_projectable(curve.support_error)
    return tuple(lines)


def support_warning(share: float) -> str | None:
    """L'avertissement d'une part du temps prévu hors support au-delà du repère
    (OG-UI) ; ``None`` au repère ou en deçà."""
    if share <= OUT_OF_SUPPORT_MARKER:
        return None
    return (
        f"{format_share(share)} du temps prévu hors du support de la courbe : au-delà "
        "de 50 %, l'erreur mesurée croît, et la prévision est celle du prolongement."
    )


def curve_warnings(history: OriginHistory | None, share: float) -> tuple[str, ...]:
    """Les avertissements d'une courbe en mémoire (OG-UI), dans cet ordre : le
    démarrage à froid (à l'origine seulement, ``history`` donné), puis le support."""
    warnings = []
    if history is not None:
        cold = cold_start_warning(history)
        if cold is not None:
            warnings.append(cold)
    support = support_warning(share)
    if support is not None:
        warnings.append(support)
    return tuple(warnings)


def support_line(read_result: CurveReadResult, threshold: float) -> str:
    """La ligne « support » de la synthèse de ``mperf project`` (OG-UI : commune avec
    la page sortie)."""
    low, high = read_result.kept_grade_range
    return (
        f"support      {read_result.bin_count_read} tranches lues, "
        f"{read_result.bin_count_kept} retenues (>= {threshold:g} min), "
        f"plage {format_grade(low)} … {format_grade(high)}"
    )


def outing_support_lines(match: OutingMatch, share: float) -> tuple[str, str]:
    """La plage de support et la part du temps prévu hors support d'une sortie
    comparée (OG-UI) : la ligne de :func:`support_line` au seuil auquel
    ``match_outing`` lit la courbe (son défaut), puis la part ; ``ValueError`` sans
    courbe, comme :func:`~mountain_perf.runs.outing_support_share`."""
    if match.curve is None:
        raise ValueError("check_outing : l'appariement n'a pas de courbe.")
    threshold = ParameterSet(PROJECTION_PARAMETER_SPECS)["curve_min_support_min"]
    return (
        support_line(match.curve, threshold),
        f"             hors support : {format_share(share)} du temps prévu",
    )
