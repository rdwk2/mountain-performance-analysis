"""Les données de Q2 (AN3-3b, ``docs/decisions/0023``) : la jointure des montées et de
leurs activités, l'appareil principal, les exclusions dans leur ordre et leur premier
motif, les journées, la normale de repos propre à Q2, ``e_s``, ``r`` et les périodes.

**Le jour d'une activité** est la date de son départ, à son décalage local
(``start_time.date()``) ; une montée appartient au jour de son activité, même si elle
part après minuit. **La journée** d'un régime réunit les montées gardées de ce régime
des activités d'un même jour ; ses montées sont triées par ``(local_start_time,
activity_ref)``, les journées par date.

**Les exclusions** se jouent dans l'ordre de :class:`Q2Motif` ; une montée n'est
comptée qu'au premier motif qui l'exclut. Les étapes 1 à 4 sont communes aux mesures ;
l'étape 5 (par journée) et l'étape 6 (M-S) sont portées par chaque journée, que les
estimations appliquent selon leurs retraits.

Python pur : bibliothèque standard, ``normals`` et les contrats ; rien
d'``inference/``.
"""

from __future__ import annotations

import math
import statistics
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime
from enum import StrEnum

from mountain_perf.analyse.athlete import Periods
from mountain_perf.analyse.normals import integer_parameter, rank_ruptures
from mountain_perf.analyse.q2.parameters import (
    EXCLUDED_FLAGS,
    EXCLUDING_JOURNAL_TYPES,
    Q2_REGIMES,
)
from mountain_perf.analyse.tables import Tables
from mountain_perf.schemas import CENTRAL_CONVENTION_INDEX, ParameterSet
from mountain_perf.schemas.days import RestingHrStatus
from mountain_perf.schemas.processed import (
    ActivityRow,
    ClimbFlag,
    ClimbRegime,
    ClimbRow,
    DayRow,
)


class Q2Error(ValueError):
    """Les données ne permettent pas Q2 : le message dit pourquoi."""


class Q2Motif(StrEnum):
    """Les motifs d'exclusion, dans leur ordre (valeurs écrites dans ``flux.csv``)."""

    DEVICE = "appareil_non_principal"
    SESSIONS = "plusieurs_sessions"
    JOURNAL = "jour_exclu_du_journal"
    OUTSIDE_REGIMES = "hors_regimes"
    FLAG = "drapeau_exclu"
    NO_SPEED = "vitesse_absente"
    SHORT_GAIN = "cote_sous_gain_minimal"
    NO_HEART_RATE = "fc_indefinie"
    MERGED_DAY = "journee_reunie"
    RESTING_INVALID = "fc_repos_non_valide"
    NO_NORMAL = "normale_absente"
    STRADDLING = "a_cheval"
    UNCERTAIN = "jour_incertain"
    RESTING_AFTER = "fc_repos_apres_sortie"
    MS_NO_NORMAL = "ms_normale_absente"
    MS_STRADDLING = "ms_a_cheval"
    MS_UNCERTAIN = "ms_jour_incertain"
    MS_RESERVE = "ms_reserve_non_positive"


MOTIF_STEPS: Mapping[Q2Motif, int] = {
    Q2Motif.DEVICE: 1,
    Q2Motif.SESSIONS: 1,
    Q2Motif.JOURNAL: 1,
    Q2Motif.OUTSIDE_REGIMES: 2,
    Q2Motif.FLAG: 2,
    Q2Motif.NO_SPEED: 2,
    Q2Motif.SHORT_GAIN: 2,
    Q2Motif.NO_HEART_RATE: 3,
    Q2Motif.MERGED_DAY: 4,
    Q2Motif.RESTING_INVALID: 5,
    Q2Motif.NO_NORMAL: 5,
    Q2Motif.STRADDLING: 5,
    Q2Motif.UNCERTAIN: 5,
    Q2Motif.RESTING_AFTER: 5,
    Q2Motif.MS_NO_NORMAL: 6,
    Q2Motif.MS_STRADDLING: 6,
    Q2Motif.MS_UNCERTAIN: 6,
    Q2Motif.MS_RESERVE: 6,
}
"""L'étape de chaque motif."""


class Period(StrEnum):
    """La période d'une journée (``[periodes]`` d'``athlete.toml``) ; ``toutes`` sans
    période déclarée."""

    BEFORE = "avant"
    DISCOVERY = "decouverte"
    AFTER = "suite"
    ALL = "toutes"


def period_of(day: date, periods: Periods | None) -> Period:
    """``decouverte`` si ``debut ≤ day ≤ fin``, ``suite`` après, ``avant`` avant ;
    ``toutes`` sans période."""
    if periods is None:
        return Period.ALL
    if day < periods.discovery_start:
        return Period.BEFORE
    if day > periods.discovery_end:
        return Period.AFTER
    return Period.DISCOVERY


class HeartRate(StrEnum):
    """Les FC d'une montée : le principal (décalée, temps M) et les variantes de S1,
    S2 et S16 ; la valeur est le préfixe du champ de ``ClimbRow``."""

    LAGGED = "lagged_moving_heart_rate"
    UNLAGGED = "unlagged_moving_heart_rate"
    SECOND_HALF = "lagged_second_half_heart_rate"
    ELAPSED = "lagged_elapsed_heart_rate"


HEART_RATES: tuple[HeartRate, ...] = tuple(HeartRate)


def _heart_rate(climb: ClimbRow, which: HeartRate, min_coverage: float) -> float | None:
    value: float | None = getattr(climb, f"{which.value}_bpm")
    coverage: float = getattr(climb, f"{which.value}_coverage")
    if value is None or coverage < min_coverage:
        return None
    return value


def decimal_hour(moment: datetime) -> float:
    """L'heure locale de ``moment`` en heures décimales (Q-49 (c))."""
    return moment.hour + moment.minute / 60 + moment.second / 3600


@dataclass(frozen=True)
class Q2Climb:
    """Une montée gardée aux étapes 1 à 4, et ses grandeurs.

    ``y`` = ln de la VAM ; ``y_s12`` = ln de la VAM en M ou U (``None`` si absente ou
    non positive) ; ``heart_rates`` : une FC par :class:`HeartRate` (``None`` sous la
    couverture minimale) ; ``off_moving`` : la part hors mouvement ``(S + U)/(M + S +
    U)`` (``None`` sans temps)."""

    activity_ref: str
    local_start_time: datetime
    gain_m: float
    y: float
    y_s12: float | None
    heart_rates: tuple[float | None, ...]
    log_gain: float
    grade: float
    elevation_m: float
    preceding_ascent_m: float
    preceding_descent_m: float
    preceding_moving_s: float
    hour: float
    off_moving: float | None
    stable: bool | None
    slow_moving: bool
    start: tuple[float, float]
    end: tuple[float, float]

    @property
    def h(self) -> float:
        """La FC du principal (toujours définie pour une montée gardée)."""
        value = self.heart_rates[0]
        assert value is not None
        return value

    def heart_rate(self, which: HeartRate) -> float | None:
        """La FC ``which`` de la montée."""
        return self.heart_rates[HEART_RATES.index(which)]


@dataclass(frozen=True)
class Q2Day:
    """Une journée d'un régime (étapes 1 à 4) : sa date, sa période, ses montées
    triées, le nombre de ses activités, son motif d'étape 5 (ou ``None``), ``e_s``
    (défini si l'étape 5 ne l'exclut pas), ``r`` (la normale de Q2, définie si
    l'étape 6 ne l'exclut pas), son motif d'étape 6 de journée, et, par montée,
    ``ms_reserve_non_positive`` ou ``None``."""

    day: date
    period: Period
    climbs: tuple[Q2Climb, ...]
    activity_count: int
    step5: Q2Motif | None
    e_s: float | None
    r: float | None
    step6: Q2Motif | None
    reserve: tuple[Q2Motif | None, ...]


@dataclass(frozen=True)
class ExcludedClimb:
    """Une montée exclue aux étapes 1 à 3, son premier motif, et les grandeurs que
    lisent les bornes (``None`` quand elles manquent, ou hors des régimes de Q2)."""

    regime: ClimbRegime
    day: date
    period: Period
    motif: Q2Motif
    activity_ref: str
    log_gain: float | None
    grade: float
    elevation_m: float | None
    preceding_ascent_m: float
    preceding_descent_m: float
    hour: float
    h: float | None


@dataclass(frozen=True)
class Q2Data:
    """Ce que les estimations de Q2 lisent : le produit principal ``(fabricant,
    numéro)``, les périodes, les journées des étapes 1 à 4 par régime de Q2, les
    montées exclues aux étapes 1 à 3, la première et la dernière date des activités,
    les régimes présents parmi les montées, et ``v_ref`` des tables."""

    principal: tuple[str, int]
    periods: Periods | None
    days: Mapping[ClimbRegime, tuple[Q2Day, ...]]
    excluded: tuple[ExcludedClimb, ...]
    activity_dates: tuple[date, date] | None
    regimes_present: tuple[ClimbRegime, ...]
    reference_vertical_speed_ms: float


def _product(activity: ActivityRow) -> tuple[str, int] | None:
    if activity.device_manufacturer is None or activity.device_product is None:
        return None
    return (activity.device_manufacturer, activity.device_product)


def _name(product: tuple[str, int]) -> str:
    return f"{product[0]}:{product[1]}"


def principal_device(
    activities: Sequence[ActivityRow], climbs: Sequence[ClimbRow]
) -> tuple[str, int]:
    """Le produit qui porte le plus de jours distincts parmi les activités à montées
    d'un régime de Q2 (Q-34) ; un produit à fabricant ou numéro absent n'est jamais
    candidat. :class:`Q2Error` à égalité en tête, ou sans candidat."""
    with_climbs = {c.activity_ref for c in climbs if c.regime in Q2_REGIMES}
    days: dict[tuple[str, int], set[date]] = {}
    for activity in activities:
        product = _product(activity)
        if activity.activity_ref in with_climbs and product is not None:
            days.setdefault(product, set()).add(activity.start_time.date())
    if not days:
        raise Q2Error("aucun appareil désigné par les activités à montées")
    best = max(len(d) for d in days.values())
    leaders = sorted(p for p, d in days.items() if len(d) == best)
    if len(leaders) > 1:
        raise Q2Error(
            f"appareil principal indécidable : {_name(leaders[0])} et "
            f"{_name(leaders[1])} portent chacun {best} jours"
        )
    return leaders[0]


def q2_normals(
    days: Sequence[DayRow], parameters: ParameterSet
) -> dict[date, float | None]:
    """La normale de Q2 de chaque jour de ``days`` (jours consécutifs, dans leur
    ordre) : la médiane des FC de repos des jours admis (``resting_hr_admitted`` et pas
    ``uncertain_device``) de la fenêtre ``[t − normal_window_days ; t − 1]`` coupée au
    dernier changement de montre ``≤ t`` ; absente sous ``normal_min_admitted_days``
    jours admis."""
    window = integer_parameter(parameters, "normal_window_days")
    minimum = integer_parameter(parameters, "normal_min_admitted_days")
    ruptures = rank_ruptures([d.device_ranks for d in days])
    normals: dict[date, float | None] = {}
    cut = 0
    for t, row in enumerate(days):
        if ruptures[t]:
            cut = t
        values = [
            value
            for d in days[max(t - window, cut) : t]
            if d.resting_hr_admitted
            and not d.uncertain_device
            and (value := d.resting_hr_bpm) is not None
        ]
        normals[row.day] = (
            float(statistics.median(values)) if len(values) >= minimum else None
        )
    return normals


def _climb_motif(
    climb: ClimbRow,
    activity: ActivityRow,
    principal: tuple[str, int],
    journal_days: set[date],
    v_ref: float,
    parameters: ParameterSet,
) -> Q2Motif | None:
    if _product(activity) != principal:
        return Q2Motif.DEVICE
    if (activity.session_count or 1) > 1:
        return Q2Motif.SESSIONS
    if activity.start_time.date() in journal_days:
        return Q2Motif.JOURNAL
    if climb.regime not in Q2_REGIMES:
        return Q2Motif.OUTSIDE_REGIMES
    if any(flag in EXCLUDED_FLAGS for flag in climb.flags):
        return Q2Motif.FLAG
    if (
        climb.vertical_speed_ms is None
        or climb.vertical_speed_ms <= 0
        or climb.moving_mean_elevation_m is None
    ):
        return Q2Motif.NO_SPEED
    if (
        climb.regime is ClimbRegime.SHORT_CLIMB
        and climb.gain_m <= v_ref * parameters["short_climb_min_gain_s"]
    ):
        return Q2Motif.SHORT_GAIN
    if _heart_rate(climb, HeartRate.LAGGED, parameters["min_heart_rate_coverage"]) is (
        None
    ):
        return Q2Motif.NO_HEART_RATE
    return None


def _log_or_none(value: float | None) -> float | None:
    return math.log(value) if value is not None and value > 0 else None


def _off_moving(climb: ClimbRow) -> float | None:
    i = CENTRAL_CONVENTION_INDEX
    moving = climb.moving_s_by_convention[i]
    off = climb.stopped_s_by_convention[i] + climb.undetermined_s_by_convention[i]
    total = moving + off
    return off / total if total > 0 else None


def _kept(climb: ClimbRow, min_coverage: float) -> Q2Climb:
    speed = climb.vertical_speed_ms
    elevation = climb.moving_mean_elevation_m
    assert speed is not None
    assert elevation is not None
    if climb.gain_m <= 0:
        raise Q2Error(f"montée gardée de gain nul ({climb.activity_ref})")
    return Q2Climb(
        activity_ref=climb.activity_ref,
        local_start_time=climb.local_start_time,
        gain_m=climb.gain_m,
        y=math.log(speed),
        y_s12=_log_or_none(climb.moving_or_undetermined_vertical_speed_ms),
        heart_rates=tuple(_heart_rate(climb, w, min_coverage) for w in HEART_RATES),
        log_gain=math.log(climb.gain_m),
        grade=climb.grade,
        elevation_m=elevation,
        preceding_ascent_m=climb.preceding_ascent_m,
        preceding_descent_m=climb.preceding_descent_m,
        preceding_moving_s=climb.preceding_moving_s,
        hour=decimal_hour(climb.local_start_time),
        off_moving=_off_moving(climb),
        stable=climb.stable,
        slow_moving=ClimbFlag.SLOW_MOVING in climb.flags,
        start=(climb.start_latitude_deg, climb.start_longitude_deg),
        end=(climb.end_latitude_deg, climb.end_longitude_deg),
    )


def _step5(
    row: DayRow | None, normal: float | None, first_start: datetime | None
) -> Q2Motif | None:
    if row is None or row.resting_hr_status is not RestingHrStatus.VALID:
        return Q2Motif.RESTING_INVALID
    if normal is None:
        return Q2Motif.NO_NORMAL
    if len(row.device_ranks) >= 2:
        return Q2Motif.STRADDLING
    if row.uncertain_device:
        return Q2Motif.UNCERTAIN
    midpoint = row.lowest_heart_rate_window_midpoint
    if midpoint is not None and first_start is not None and midpoint >= first_start:
        return Q2Motif.RESTING_AFTER
    return None


def _step6(row: DayRow | None, normal: float | None) -> Q2Motif | None:
    if row is None or normal is None:
        return Q2Motif.MS_NO_NORMAL
    if len(row.device_ranks) >= 2:
        return Q2Motif.MS_STRADDLING
    if row.uncertain_device:
        return Q2Motif.MS_UNCERTAIN
    return None


def _climb_order(climb: ClimbRow) -> tuple[datetime, str]:
    return (climb.local_start_time, climb.activity_ref)


def q2_data(
    tables: Tables, periods: Periods | None, parameters: ParameterSet
) -> Q2Data:
    """Les données de Q2 depuis ``tables`` : l'appareil principal, les montées exclues
    aux étapes 1 à 3 et leur premier motif, les journées des étapes 1 à 4 de chaque
    régime de Q2, avec leurs motifs d'étapes 5 et 6, ``e_s`` et ``r``."""
    activities = {a.activity_ref: a for a in tables.activities}
    principal = principal_device(tables.activities, tables.climbs)
    rows = {row.day: row for row in tables.days}
    normals = q2_normals(sorted(tables.days, key=lambda r: r.day), parameters)
    journal_days = {
        row.day
        for row in tables.days
        if any(t in EXCLUDING_JOURNAL_TYPES for t in row.journal_types)
    }
    first_start: dict[date, datetime] = {}
    for entry in tables.activities:
        when = entry.start_time
        if when.date() not in first_start or when < first_start[when.date()]:
            first_start[when.date()] = when
    v_ref = tables.provenance.reference_vertical_speed_ms
    coverage = parameters["min_heart_rate_coverage"]
    kept: dict[tuple[ClimbRegime, date], list[ClimbRow]] = {}
    excluded: list[ExcludedClimb] = []
    for climb in sorted(
        tables.climbs,
        key=lambda c: (
            activities[c.activity_ref].start_time.date()
            if c.activity_ref in activities
            else date.min,
            *_climb_order(c),
        ),
    ):
        activity = activities.get(climb.activity_ref)
        if activity is None:
            raise Q2Error(f"montée sans activité ({climb.activity_ref})")
        day = activity.start_time.date()
        motif = _climb_motif(
            climb, activity, principal, journal_days, v_ref, parameters
        )
        if motif is None:
            kept.setdefault((climb.regime, day), []).append(climb)
            continue
        q2 = climb.regime in Q2_REGIMES
        excluded.append(
            ExcludedClimb(
                regime=climb.regime,
                day=day,
                period=period_of(day, periods),
                motif=motif,
                activity_ref=climb.activity_ref,
                log_gain=_log_or_none(climb.gain_m) if q2 else None,
                grade=climb.grade,
                elevation_m=climb.moving_mean_elevation_m if q2 else None,
                preceding_ascent_m=climb.preceding_ascent_m,
                preceding_descent_m=climb.preceding_descent_m,
                hour=decimal_hour(climb.local_start_time),
                h=_heart_rate(climb, HeartRate.LAGGED, coverage) if q2 else None,
            )
        )
    days: dict[ClimbRegime, tuple[Q2Day, ...]] = {}
    for regime in Q2_REGIMES:
        built: list[Q2Day] = []
        for (r, day), members in sorted(kept.items(), key=lambda item: item[0][1]):
            if r is not regime:
                continue
            members.sort(key=_climb_order)
            climbs = tuple(_kept(c, coverage) for c in members)
            row = rows.get(day)
            normal = normals.get(day)
            step5 = _step5(row, normal, first_start.get(day))
            step6 = _step6(row, normal)
            e_s = None
            if step5 is None and row is not None and normal is not None:
                assert row.resting_hr_bpm is not None
                e_s = row.resting_hr_bpm - normal
            r_value = normal if step6 is None else None
            reserve = tuple(
                Q2Motif.MS_RESERVE
                if r_value is not None and c.h - r_value <= 0
                else None
                for c in climbs
            )
            built.append(
                Q2Day(
                    day=day,
                    period=period_of(day, periods),
                    climbs=climbs,
                    activity_count=len({c.activity_ref for c in members}),
                    step5=step5,
                    e_s=e_s,
                    r=r_value,
                    step6=step6,
                    reserve=reserve,
                )
            )
        days[regime] = tuple(built)
    starts = [a.start_time.date() for a in tables.activities]
    present = {c.regime for c in tables.climbs}
    return Q2Data(
        principal=principal,
        periods=periods,
        days=days,
        excluded=tuple(excluded),
        activity_dates=(min(starts), max(starts)) if starts else None,
        regimes_present=tuple(r for r in ClimbRegime if r in present),
        reference_vertical_speed_ms=v_ref,
    )
