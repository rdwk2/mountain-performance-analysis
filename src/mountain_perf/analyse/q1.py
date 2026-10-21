"""La figure de Q1 (AN1-2c, ``docs/decisions/0015``) : la vitesse ascensionnelle des
sorties, par régime, à pente et altitude comparables, calculée depuis les tables de
``processed/`` sans rien recalculer de la chaîne des montées.

**Panneaux** (:data:`Q1_PANELS`) : (a) montées longues, (b) côtes, (c) ski de
randonnée ; les intermédiaires, le ski court et les autres sports n'entrent dans aucun
panneau.

**Vue principale** : les montées du régime d'un panneau, sauf les montées marquées
(un drapeau au moins), celles d'une activité à plusieurs sessions (le sport d'une
session n'est relié à aucun régime) et celles sans strate (pente « non résolue », ou
sans altitude en M). **Vue de sensibilité** : les mêmes, stables seulement.

**Le point** : une activité × un panneau × une strate de pente × une strate
d'altitude. Son résumé est le rapport des sommes de ses montées,
``Σ G_M,θc / Σ M_θc`` : couper une montée sans changer le temps inclus ne le change
pas. Son enveloppe : la plus petite et la plus grande des dix valeurs
``Σ G_M,θ / Σ M_θ`` et ``Σ (G_M + G_U)_θ / Σ (M + U)_θ`` sur les cinq conventions. Un
point au résumé non positif ne se place pas sur un axe logarithmique ; une facette (un
panneau × une strate de pente) qui compte moins de ``min_facet_activities`` activités
distinctes (celles dont un point y a un résumé positif) ne s'affiche pas. Les deux
restent dans les points, avec leur statut.

**La stabilité du point** (vue principale), le critère de la montée transposé : pour
chaque variante de ``VARIANTS``, la part du gain du point qui reste dans une montée de
la variante, de la même activité, non marquée, du même panneau et des mêmes strates
(chaque montée du point pèse son ``G_M,θc``, multiplié par la part de son intervalle
``[t_a ; t_b]`` que couvre la réunion de ces montées) ; le point est retrouvé dans la
variante si cette part atteint ``min_kept_fraction``, et son résumé sous la variante
est le rapport des sommes de ces montées. Il est stable s'il est retrouvé dans au moins
``min_found_fraction`` des variantes et si le plus grand écart relatif de son résumé,
sur les variantes où il est retrouvé, reste sous ``max_relative_deviation``.

**Le flux**, mois par mois (date locale du départ de l'activité, du premier au dernier
mois, mois vides compris) : les activités, puis, par panneau, les montées, leurs
exclusions par motif, les montées et les points de chaque vue.

Python pur : ce module ne demande aucun extra.
"""

from __future__ import annotations

import math
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

from mountain_perf.analyse.stability import VARIANTS
from mountain_perf.analyse.tables import Tables
from mountain_perf.schemas import CENTRAL_CONVENTION_INDEX, ParameterSet, ParameterSpec
from mountain_perf.schemas.processed import (
    ActivityRow,
    AltitudeStratum,
    ClimbFlag,
    ClimbRegime,
    ClimbRow,
    ClimbVariantRow,
    GradeStratum,
    ProcessedProvenance,
)

Q1_PARAMETER_SPECS: tuple[ParameterSpec, ...] = (
    ParameterSpec(
        "min_facet_activities",
        None,
        5.0,
        1.0,
        1000.0,
        "Nombre minimal d'activités distinctes d'une facette affichée.",
    ),
    ParameterSpec(
        "min_kept_fraction",
        None,
        0.8,
        0.0,
        1.0,
        "Part minimale du gain d'un point qui reste dans son panneau et ses strates"
        " sous une variante, pour qu'il y soit retrouvé.",
    ),
    ParameterSpec(
        "min_found_fraction",
        None,
        0.8,
        0.0,
        1.0,
        "Part minimale des variantes où un point stable est retrouvé.",
    ),
    ParameterSpec(
        "max_relative_deviation",
        None,
        0.05,
        0.0,
        10.0,
        "Plus grand écart relatif du résumé admis pour un point stable.",
    ),
)
"""Les paramètres de la figure (``docs/decisions/0015``), aux valeurs de la stabilité
des montées, sans en dépendre."""

Q1_PANELS: tuple[ClimbRegime, ...] = (
    ClimbRegime.LONG_CLIMB,
    ClimbRegime.SHORT_CLIMB,
    ClimbRegime.SKI_TOURING,
)
"""Les panneaux de la figure, dans leur ordre : (a), (b), (c)."""

FACET_STRATA: tuple[GradeStratum, ...] = (
    GradeStratum.MODERATE,
    GradeStratum.STEEP,
    GradeStratum.VERY_STEEP,
)
"""Les strates de pente qui ont une facette, dans leur ordre."""

ALTITUDE_STRATA: tuple[AltitudeStratum, ...] = tuple(AltitudeStratum)
"""Les strates d'altitude, dans leur ordre (la couleur des points)."""


class View(StrEnum):
    """Une vue de la figure."""

    MAIN = "principale"
    STABLE_ONLY = "sans_instables"


class PointStatus(StrEnum):
    """Le sort d'un point sur la figure."""

    SHOWN = "montre"
    SMALL_FACET = "facette_sous_n"
    NON_POSITIVE = "resume_non_positif"


@dataclass(frozen=True)
class PointStability:
    """La stabilité d'un point sous les variantes : la part des variantes où il est
    retrouvé, la plus petite part de son gain qui reste, le plus grand écart relatif
    de son résumé là où il est retrouvé (``None`` s'il ne l'est nulle part), et le
    critère."""

    found_fraction: float
    min_kept_fraction: float
    max_relative_deviation: float | None
    stable: bool


@dataclass(frozen=True)
class FigurePoint:
    """Un point de la figure : une activité, dans un panneau, une strate de pente et
    une strate d'altitude, sous une vue. ``vertical_speed_ms`` est le rapport des
    sommes, ``None`` sans temps en M ; l'enveloppe est ``None`` quand aucune des dix
    valeurs n'existe.
    ``stability`` n'existe que dans la vue principale, pour un résumé positif."""

    view: View
    panel: ClimbRegime
    grade_stratum: GradeStratum
    altitude_stratum: AltitudeStratum
    activity_ref: str
    start_time: datetime
    climb_count: int
    moving_gain_m: float
    moving_s: float
    vertical_speed_ms: float | None
    vertical_speed_low_ms: float | None
    vertical_speed_high_ms: float | None
    status: PointStatus
    stability: PointStability | None


@dataclass(frozen=True)
class MonthActivities:
    """Les activités d'un mois : entrées de l'index, avec une vue positions et
    altitude, à plusieurs sessions."""

    month: str
    activities: int
    with_track: int
    multisession: int


@dataclass(frozen=True)
class MonthPanel:
    """Le flux d'un panneau sur un mois.

    - ``climbs`` : montées du régime ;
    - ``flagged`` : marquées ; ``flags`` : par drapeau, dans l'ordre de ``ClimbFlag``
      (une montée compte une fois par drapeau) ;
    - ``multisession`` : non marquées, d'une activité à plusieurs sessions ;
    - ``unstratified`` : les autres, sans strate ;
    - ``kept``, ``kept_unstable`` : gardées pour la vue principale (avant les facettes
      et le résumé), dont instables ;
    - ``points``, ``points_hidden``, ``points_non_positive``, ``points_unstable`` : les
      points de la vue principale, dont ceux d'une facette sous le minimum, au résumé
      non positif, montrés et instables ;
    - ``stable_only_points``, ``stable_only_points_hidden``,
      ``stable_only_points_non_positive`` : les points de la vue de sensibilité, dont
      ceux d'une facette sous le minimum et au résumé non positif ; un point de la vue
      principale sans montée stable n'y est pas (``points − stable_only_points``).
    """

    month: str
    panel: ClimbRegime
    climbs: int
    flagged: int
    flags: tuple[tuple[ClimbFlag, int], ...]
    multisession: int
    unstratified: int
    kept: int
    kept_unstable: int
    points: int
    points_hidden: int
    points_non_positive: int
    points_unstable: int
    stable_only_points: int
    stable_only_points_hidden: int
    stable_only_points_non_positive: int


@dataclass(frozen=True)
class DeviceChange:
    """Un changement d'appareil : la première activité enregistrée, dans l'ordre du
    temps, dont le fabricant et le produit diffèrent de la précédente qui les dit ;
    une activité qui ne dit pas les deux ne compte pas."""

    start_time: datetime
    manufacturer: str | None
    product: int | None


@dataclass(frozen=True)
class Q1Figure:
    """Ce que la figure montre et ce que ses résultats écrivent.

    - ``points`` : vue principale puis vue de sensibilité ; dans chaque vue, par
      panneau, strate de pente, départ de l'activité, activité, strate d'altitude ;
    - ``period`` : le premier et le dernier départ des activités de l'index, en heure
      murale locale (celle de l'axe des dates et des mois du flux) ;
    - ``vertical_speed_range_ms`` : par panneau, le plus petit et le plus grand résumé
      des points montrés des deux vues (l'axe de VAM du panneau), ``None`` sans point ;
    - ``provenance`` : celle des tables lues ; ``parameters`` : ceux de la figure.
    """

    points: tuple[FigurePoint, ...]
    month_activities: tuple[MonthActivities, ...]
    month_panels: tuple[MonthPanel, ...]
    device_changes: tuple[DeviceChange, ...]
    period: tuple[datetime, datetime] | None
    vertical_speed_range_ms: tuple[tuple[ClimbRegime, tuple[float, float] | None], ...]
    provenance: ProcessedProvenance
    parameters: ParameterSet


def month_of(moment: datetime) -> str:
    """Le mois ``AAAA-MM`` de la date locale de ``moment``."""
    return f"{moment.year:04d}-{moment.month:02d}"


def _wall_clock(moment: datetime) -> datetime:
    """L'heure murale locale de ``moment``, sans fuseau : la clé de la période."""
    return moment.replace(tzinfo=None)


def _months(first: str, last: str) -> list[str]:
    year, month = int(first[:4]), int(first[5:])
    out = []
    while f"{year:04d}-{month:02d}" <= last:
        out.append(f"{year:04d}-{month:02d}")
        year, month = (year + 1, 1) if month == 12 else (year, month + 1)
    return out


def _ratio(gain: float, time: float) -> float | None:
    return gain / time if time > 0 else None


def summary_ms(climbs: Sequence[ClimbRow]) -> float | None:
    """Le rapport des sommes ``Σ G_M,θc / Σ M_θc`` ; ``None`` sans temps en M."""
    k = CENTRAL_CONVENTION_INDEX
    return _ratio(
        math.fsum(c.moving_gain_m_by_convention[k] for c in climbs),
        math.fsum(c.moving_s_by_convention[k] for c in climbs),
    )


def envelope_ms(climbs: Sequence[ClimbRow]) -> tuple[float, float] | None:
    """La plus petite et la plus grande des dix valeurs ``Σ G_M,θ / Σ M_θ`` et
    ``Σ (G_M + G_U)_θ / Σ (M + U)_θ`` ; ``None`` si aucune n'existe."""
    values: list[float] = []
    for k in range(len(climbs[0].moving_s_by_convention)):
        moving = math.fsum(c.moving_s_by_convention[k] for c in climbs)
        undetermined = math.fsum(c.undetermined_s_by_convention[k] for c in climbs)
        gain = math.fsum(c.moving_gain_m_by_convention[k] for c in climbs)
        gain_u = math.fsum(c.undetermined_gain_m_by_convention[k] for c in climbs)
        for value in (
            _ratio(gain, moving),
            _ratio(gain + gain_u, moving + undetermined),
        ):
            if value is not None:
                values.append(value)
    return (min(values), max(values)) if values else None


def covered_s(
    start_s: float, end_s: float, intervals: Iterable[tuple[float, float]]
) -> float:
    """La part de ``[start_s ; end_s]`` couverte par la réunion de ``intervals``, en
    secondes."""
    total, reach = 0.0, start_s
    for a, b in sorted(intervals):
        lo, hi = max(a, reach), min(b, end_s)
        if hi > lo:
            total += hi - lo
            reach = hi
    return total


def point_stability(
    climbs: Sequence[ClimbRow],
    candidates: Sequence[Sequence[ClimbVariantRow]],
    parameters: ParameterSet,
) -> PointStability:
    """La stabilité d'un point de montées ``climbs`` (résumé positif), contre, pour
    chaque variante, ``candidates`` : les montées de la variante de la même activité,
    non marquées, du même panneau et des mêmes strates. Comme pour la montée
    (``stability.py``), une variante qui retrouve le point sans résumé (sans temps en
    M) le retrouve, mais n'entre pas dans l'écart."""
    k = CENTRAL_CONVENTION_INDEX
    reference = summary_ms(climbs)
    assert reference is not None
    assert reference > 0
    total_gain = math.fsum(c.moving_gain_m_by_convention[k] for c in climbs)
    found = 0
    kept_fractions: list[float] = []
    deviations: list[float] = []
    for rows in candidates:
        spans = [(r.start_offset_s, r.end_offset_s) for r in rows]
        kept = math.fsum(
            c.moving_gain_m_by_convention[k]
            * covered_s(c.start_offset_s, c.end_offset_s, spans)
            / (c.end_offset_s - c.start_offset_s)
            for c in climbs
        )
        fraction = kept / total_gain
        kept_fractions.append(fraction)
        if fraction < parameters["min_kept_fraction"]:
            continue
        found += 1
        other = _ratio(
            math.fsum(r.moving_gain_m for r in rows),
            math.fsum(r.moving_s for r in rows),
        )
        if other is not None:
            deviations.append(abs(other / reference - 1))
    found_fraction = found / len(candidates)
    deviation = max(deviations) if deviations else None
    stable = (
        found_fraction >= parameters["min_found_fraction"]
        and deviation is not None
        and deviation < parameters["max_relative_deviation"]
    )
    return PointStability(found_fraction, min(kept_fractions), deviation, stable)


@dataclass(frozen=True)
class _Group:
    view: View
    panel: ClimbRegime
    grade_stratum: GradeStratum
    altitude_stratum: AltitudeStratum
    activity: ActivityRow
    climbs: tuple[ClimbRow, ...]


def _groups(
    view: View, climbs: Sequence[ClimbRow], activities: dict[str, ActivityRow]
) -> list[_Group]:
    keyed: dict[tuple[ClimbRegime, GradeStratum, AltitudeStratum, str], list[ClimbRow]]
    keyed = {}
    for c in climbs:
        assert c.altitude_stratum is not None
        key = (c.regime, c.grade_stratum, c.altitude_stratum, c.activity_ref)
        keyed.setdefault(key, []).append(c)
    groups = [
        _Group(view, panel, grade, altitude, activities[ref], tuple(rows))
        for (panel, grade, altitude, ref), rows in keyed.items()
    ]
    groups.sort(
        key=lambda g: (
            Q1_PANELS.index(g.panel),
            FACET_STRATA.index(g.grade_stratum),
            g.activity.start_time,
            g.activity.activity_ref,
            ALTITUDE_STRATA.index(g.altitude_stratum),
        )
    )
    return groups


def _candidates(
    group: _Group, variants: dict[tuple[str, str], list[ClimbVariantRow]]
) -> list[list[ClimbVariantRow]]:
    return [
        [
            r
            for r in variants.get((group.activity.activity_ref, variant.name), [])
            if not r.flags
            and r.regime is group.panel
            and r.grade_stratum is group.grade_stratum
            and r.altitude_stratum is group.altitude_stratum
        ]
        for variant in VARIANTS
    ]


def _points(
    groups: Sequence[_Group],
    variants: dict[tuple[str, str], list[ClimbVariantRow]],
    parameters: ParameterSet,
) -> list[FigurePoint]:
    summaries = [summary_ms(g.climbs) for g in groups]
    facets: dict[tuple[ClimbRegime, GradeStratum], set[str]] = {}
    for g, s in zip(groups, summaries, strict=True):
        if s is not None and s > 0:
            facets.setdefault((g.panel, g.grade_stratum), set()).add(
                g.activity.activity_ref
            )
    minimum = parameters["min_facet_activities"]
    points = []
    k = CENTRAL_CONVENTION_INDEX
    for g, s in zip(groups, summaries, strict=True):
        if s is None or s <= 0:
            status = PointStatus.NON_POSITIVE
        elif len(facets[(g.panel, g.grade_stratum)]) < minimum:
            status = PointStatus.SMALL_FACET
        else:
            status = PointStatus.SHOWN
        stability = (
            point_stability(g.climbs, _candidates(g, variants), parameters)
            if g.view is View.MAIN and status is not PointStatus.NON_POSITIVE
            else None
        )
        envelope = envelope_ms(g.climbs)
        points.append(
            FigurePoint(
                view=g.view,
                panel=g.panel,
                grade_stratum=g.grade_stratum,
                altitude_stratum=g.altitude_stratum,
                activity_ref=g.activity.activity_ref,
                start_time=g.activity.start_time,
                climb_count=len(g.climbs),
                moving_gain_m=math.fsum(
                    c.moving_gain_m_by_convention[k] for c in g.climbs
                ),
                moving_s=math.fsum(c.moving_s_by_convention[k] for c in g.climbs),
                vertical_speed_ms=s,
                vertical_speed_low_ms=None if envelope is None else envelope[0],
                vertical_speed_high_ms=None if envelope is None else envelope[1],
                status=status,
                stability=stability,
            )
        )
    return points


def _device_changes(activities: Sequence[ActivityRow]) -> list[DeviceChange]:
    changes: list[DeviceChange] = []
    previous: tuple[str | None, int | None] | None = None
    for a in sorted(activities, key=lambda a: (a.start_time, a.activity_ref)):
        device = (a.device_manufacturer, a.device_product)
        if not a.has_recording or None in device:
            continue
        if previous is not None and device != previous:
            changes.append(DeviceChange(a.start_time, *device))
        previous = device
    return changes


def _multisession(activity: ActivityRow) -> bool:
    return (activity.session_count or 0) > 1


def _stratified(climb: ClimbRow) -> bool:
    return climb.grade_stratum in FACET_STRATA and climb.altitude_stratum is not None


def _month_panel(
    month: str,
    panel: ClimbRegime,
    climbs: Sequence[ClimbRow],
    points: Sequence[FigurePoint],
    activities: dict[str, ActivityRow],
) -> MonthPanel:
    """Le flux de ``panel`` sur ``month`` : ``climbs`` sont les montées des panneaux,
    ``points`` ceux des deux vues."""
    here = [
        c
        for c in climbs
        if c.regime is panel
        and month_of(activities[c.activity_ref].start_time) == month
    ]
    unflagged = [c for c in here if not c.flags]
    single = [c for c in unflagged if not _multisession(activities[c.activity_ref])]
    kept = [c for c in single if _stratified(c)]
    mine = [p for p in points if p.panel is panel and month_of(p.start_time) == month]
    main = [p for p in mine if p.view is View.MAIN]
    sensitivity = [p for p in mine if p.view is View.STABLE_ONLY]
    return MonthPanel(
        month=month,
        panel=panel,
        climbs=len(here),
        flagged=len(here) - len(unflagged),
        flags=tuple((f, sum(1 for c in here if f in c.flags)) for f in ClimbFlag),
        multisession=len(unflagged) - len(single),
        unstratified=len(single) - len(kept),
        kept=len(kept),
        kept_unstable=sum(1 for c in kept if c.stable is False),
        points=len(main),
        points_hidden=sum(1 for p in main if p.status is PointStatus.SMALL_FACET),
        points_non_positive=sum(
            1 for p in main if p.status is PointStatus.NON_POSITIVE
        ),
        points_unstable=sum(
            1
            for p in main
            if p.status is PointStatus.SHOWN
            and p.stability is not None
            and not p.stability.stable
        ),
        stable_only_points=len(sensitivity),
        stable_only_points_hidden=sum(
            1 for p in sensitivity if p.status is PointStatus.SMALL_FACET
        ),
        stable_only_points_non_positive=sum(
            1 for p in sensitivity if p.status is PointStatus.NON_POSITIVE
        ),
    )


def q1_figure(tables: Tables, parameters: ParameterSet | None = None) -> Q1Figure:
    """La figure de Q1 des tables ``tables``, aux paramètres donnés (défauts de
    :data:`Q1_PARAMETER_SPECS`)."""
    parameters = parameters or ParameterSet(Q1_PARAMETER_SPECS)
    activities = {a.activity_ref: a for a in tables.activities}
    variants: dict[tuple[str, str], list[ClimbVariantRow]] = {}
    for r in tables.variants:
        variants.setdefault((r.activity_ref, r.variant), []).append(r)
    in_panels = [c for c in tables.climbs if c.regime in Q1_PANELS]
    kept = [
        c
        for c in in_panels
        if not c.flags
        and not _multisession(activities[c.activity_ref])
        and _stratified(c)
    ]
    main = _points(_groups(View.MAIN, kept, activities), variants, parameters)
    stable = [c for c in kept if c.stable is True]
    sensitivity = _points(
        _groups(View.STABLE_ONLY, stable, activities), variants, parameters
    )
    points = main + sensitivity

    ranges: list[tuple[ClimbRegime, tuple[float, float] | None]] = []
    for panel in Q1_PANELS:
        shown = [
            p.vertical_speed_ms
            for p in points
            if p.panel is panel
            and p.status is PointStatus.SHOWN
            and p.vertical_speed_ms is not None
        ]
        ranges.append((panel, (min(shown), max(shown)) if shown else None))

    starts = [a.start_time for a in tables.activities]
    period = (
        (min(starts, key=_wall_clock), max(starts, key=_wall_clock)) if starts else None
    )
    months = _months(month_of(period[0]), month_of(period[1])) if period else []
    month_activities = []
    for month in months:
        here = [a for a in tables.activities if month_of(a.start_time) == month]
        month_activities.append(
            MonthActivities(
                month,
                len(here),
                sum(1 for a in here if a.has_track),
                sum(1 for a in here if _multisession(a)),
            )
        )
    month_panels = [
        _month_panel(month, panel, in_panels, points, activities)
        for panel in Q1_PANELS
        for month in months
    ]
    return Q1Figure(
        points=tuple(points),
        month_activities=tuple(month_activities),
        month_panels=tuple(month_panels),
        device_changes=tuple(_device_changes(tables.activities)),
        period=period,
        vertical_speed_range_ms=tuple(ranges),
        provenance=tables.provenance,
        parameters=parameters,
    )
