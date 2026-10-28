"""L'estimation de la courbe personnelle allure ↔ pente (M6b, ``docs/decisions/0017``),
depuis les intervalles des activités (:mod:`mountain_perf.estimation.intervals`).

La chaîne d':func:`estimate_curve`, dans cet ordre :

1. **les activités** (``0017``, P2) : un refus de trace écarte l'activité ; une durée
   hors de ``[min_duration_s ; max_duration_s[`` aussi ; les intervalles retirés au
   plafond sont comptés (P2.4) ;
2. **les intervalles et leurs écarts** (P1.5, P3.6, P5.2) : chacun écarté au premier
   motif — pente hors domaine, écoulé nul, vitesse hors d'échelle, puis, avec un filtre
   de FC et aux pentes de ``hr_min_grade`` ou plus seulement, FC indéfinie ou hors
   bande ; une activité sans intervalle retenu est écartée ;
3. **les tranches et leurs valeurs** (P3) : des tranches variables, en pour mille de
   pente, à centres nominaux ; la valeur (a), somme des longueurs sur somme des temps M,
   ou (b), médiane des vitesses des activités ; la vitesse écoulée, sur tous les
   intervalles retenus de la tranche ;
4. **le niveau** (P4.1, P4.2) : ``λ = ln(T / P)`` par activité, le temps M contre le
   temps que le moteur prévoit sur la courbe estimée — un **diagnostic d'ajustement**,
   en échantillon, absent si la courbe n'est pas projetable ;
5. **la forme** (P4.3, P4.4) : par tranche, l'écart interquartile de
   ``ln(P_jk / M_jk) + λ_j``, le niveau retiré ; un **logarithme sans unité : jamais
   ``dispersion_ms``**.

Python pur : ni ``analyse/`` ni ``backtest/``.
"""

from __future__ import annotations

import dataclasses
import math
import statistics
from bisect import bisect_right
from collections import Counter, defaultdict
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from enum import StrEnum

from mountain_perf.estimation.intervals import (
    HR_INTEGRATION,
    MAX_HR_STEP_S,
    ActivityIntervals,
    CurveInterval,
    TraceRefusal,
)
from mountain_perf.model.curve_io import (
    CURVE_PARAMETER_SPECS,
    CurveBin,
    CurveError,
    CurveFileRow,
    select_support,
)
from mountain_perf.model.pace import PaceModel
from mountain_perf.schemas import (
    HEART_RATE_RANGE_BPM,
    ActivityIndex,
    CurveProvenance,
    IndexedActivity,
    PaceCurve,
    ParameterSet,
    ParameterSpec,
    Sport,
)
from mountain_perf.validation import (
    ContractError,
    require_finite,
    require_in_range,
    require_non_empty,
)

METHOD = "mperf curve, M6b-1 (docs/decisions/0017)"
"""La méthode, nommée dans le compagnon (``0017``, P5.4)."""

CURVE_BIN_EDGES_PERMILLE: tuple[int, ...] = (
    *range(-1000, -400, 100),
    *range(-400, -150, 50),
    *range(-150, 350, 25),
    350,
    *range(400, 1001, 100),
)
"""Les bornes des tranches, en pour mille de pente, en entiers (39 bornes, 38
tranches) : 10 % de −100 à −40 %, 5 % de −40 à −15 %, 2,5 % de −15 à +35 %, 5 % de +35
à +40 %, 10 % de +40 à +100 %. Des entiers, pour que bornes et centres s'écrivent
exactement (``0017``, P3.1)."""

CURVE_ESTIMATION_PARAMETER_SPECS: tuple[ParameterSpec, ...] = (
    ParameterSpec("hr_width_bpm", "bpm", 10.0, 1.0, 60.0, "Largeur de la bande de FC."),
    ParameterSpec(
        "hr_lag_s", "s", 60.0, 0.0, 600.0, "Décalage de la FC sur l'intervalle."
    ),
    ParameterSpec(
        "hr_min_grade",
        None,
        -0.05,
        -1.0,
        1.0,
        "Pente à partir de laquelle la FC filtre ; en dessous, sans filtre.",
    ),
    ParameterSpec(
        "hr_min_coverage",
        None,
        0.8,
        0.0,
        1.0,
        "Part de la fenêtre que la FC doit couvrir pour être définie.",
    ),
    ParameterSpec(
        "median_min_moving_s",
        "s",
        60.0,
        0.0,
        3600.0,
        "Temps M minimal d'une activité dans une tranche, pour la valeur (b).",
    ),
    ParameterSpec(
        "shape_min_moving_s",
        "s",
        120.0,
        0.0,
        3600.0,
        "Temps M minimal d'une activité dans une tranche, pour la forme.",
    ),
    ParameterSpec(
        "shape_min_activities",
        None,
        5.0,
        2.0,
        1000.0,
        "Nombre minimal d'activités pour publier la forme d'une tranche.",
    ),
    ParameterSpec(
        "max_elapsed_speed_ms",
        "m/s",
        25 / 3.6,
        1.0,
        50.0,
        "Vitesse écoulée au-delà de laquelle un intervalle est aberrant.",
    ),
    ParameterSpec(
        "max_ascent_speed_ms",
        "m/s",
        2500 / 3600,
        0.1,
        10.0,
        "Vitesse verticale montante au-delà de laquelle un intervalle est aberrant.",
    ),
    ParameterSpec(
        "max_descent_speed_ms",
        "m/s",
        5000 / 3600,
        0.1,
        10.0,
        "Vitesse verticale descendante au-delà de laquelle un intervalle est aberrant.",
    ),
)
"""Les paramètres de l'estimateur (``0017``)."""

SUPPORT_THRESHOLD_MIN = ParameterSet(CURVE_PARAMETER_SPECS)["curve_min_support_min"]
"""Le seuil de support par défaut de ``read_curve`` (``0009`` D2), en minutes, pour le
niveau et pour ``check_curve_rows``."""

_FILL_PROVENANCE = CurveProvenance(
    activity_count=0,
    hr_center_bpm=None,
    hr_width_bpm=None,
    date_from=date(2000, 1, 1),
    date_to=date(2000, 1, 1),
    source_activity_types=frozenset(),
    min_duration_s=None,
    estimator=METHOD,
    generated_at=datetime(2000, 1, 1, tzinfo=UTC),
)
"""La provenance de remplissage de la courbe que le niveau lit : jamais écrite."""


class BinValue(StrEnum):
    """La valeur d'une tranche (``0017``, P3.3, P3.4)."""

    POOLED = "somme"
    MEDIAN = "médiane"


class IntervalExclusion(StrEnum):
    """Les motifs d'écart d'un intervalle, dans l'ordre où ils se testent."""

    CEILING = "au-delà du plafond"
    GRADE = "pente hors domaine"
    NO_ELAPSED = "écoulé nul"
    ABERRANT = "vitesse hors d'échelle"
    HR_UNDEFINED = "FC indéfinie"
    HR_OUTSIDE = "FC hors bande"


class ActivityExclusion(StrEnum):
    """Les motifs d'écart d'une activité."""

    NO_TRACE = "sans trace"
    NO_PROFILE = "profil impossible"
    SHORT = "plus courte que la durée minimale"
    LONG = "pas plus courte que la durée maximale"
    NO_INTERVAL = "aucun intervalle retenu"


@dataclass(frozen=True)
class CurveSelection:
    """Les activités d'une estimation et la valeur de ses tranches (``0017``, P2).

    - ``source_activity_types`` — sans unité — types de la source retenus, au moins un
      (P2.1 : une liste vide n'est jamais « aucun filtre ») ;
    - ``date_from``, ``date_to`` — dates civiles — la fenêtre, bornes comprises, sur le
      jour local du départ (P2.2) ;
    - ``min_duration_s`` — secondes — durée minimale d'une activité, comprise,
      ``>= 0`` ;
    - ``max_duration_s`` — secondes — durée maximale, exclue, ``> 0`` et au-dessus de la
      minimale ;
    - ``max_elapsed_s`` — secondes — plafond depuis le départ, ``> 0`` (P2.4) ;
    - ``hr_center_bpm`` — battements par minute — centre de la bande de FC, dans
      ``[20, 250]``, ``None`` sans filtre (P5) ;
    - ``value`` — la valeur des tranches.

    Vérifiée à la construction, avant toute lecture (``ContractError``).
    """

    source_activity_types: frozenset[str]
    date_from: date
    date_to: date
    min_duration_s: float | None
    max_duration_s: float | None
    max_elapsed_s: float | None
    hr_center_bpm: float | None
    value: BinValue

    def __post_init__(self) -> None:
        if not self.source_activity_types:
            raise ContractError("source_activity_types : au moins un type.")
        for activity_type in sorted(self.source_activity_types):
            require_non_empty(activity_type, "source_activity_types")
        if self.date_from > self.date_to:
            raise ContractError(
                f"date_from ({self.date_from}) doit être <= date_to ({self.date_to})."
            )
        if self.min_duration_s is not None:
            require_finite(self.min_duration_s, "min_duration_s")
            if self.min_duration_s < 0:
                raise ContractError(
                    f"min_duration_s doit être >= 0, reçu {self.min_duration_s}."
                )
        for name, value in (
            ("max_duration_s", self.max_duration_s),
            ("max_elapsed_s", self.max_elapsed_s),
        ):
            if value is not None:
                require_finite(value, name)
                if value <= 0:
                    raise ContractError(f"{name} doit être > 0, reçu {value}.")
        if (
            self.max_duration_s is not None
            and self.min_duration_s is not None
            and self.max_duration_s <= self.min_duration_s
        ):
            raise ContractError(
                f"max_duration_s ({self.max_duration_s}) doit être > min_duration_s "
                f"({self.min_duration_s})."
            )
        if self.hr_center_bpm is not None:
            require_finite(self.hr_center_bpm, "hr_center_bpm")
            require_in_range(self.hr_center_bpm, *HEART_RATE_RANGE_BPM, "hr_center_bpm")


@dataclass(frozen=True)
class EstimatedBin:
    """Une tranche estimée.

    - ``lower_permille``, ``upper_permille`` — pour mille de pente — ses bornes,
      ``[lo ; hi[`` ;
    - ``center_grade`` — fraction — son centre nominal, ``(lo + hi) / 2000`` (P3.2) ;
    - ``speed_ms`` — m/s — sa valeur, (a) ou (b) ;
    - ``elapsed_speed_ms`` — m/s — sa vitesse écoulée, sur tous ses intervalles
      retenus, ceux sans temps M compris (P1.6) ;
    - ``moving_s`` — secondes — le temps M qui porte la valeur (``time_min × 60``) :
      avec (b), celui des seules activités de la médiane (P3.5) ;
    - ``activity_count`` — sans unité — les activités qui portent la valeur
      (``sample_count``) ;
    - ``mean_hr_bpm`` — battements par minute — FC moyenne pondérée par le temps M,
      ``None`` sans FC ;
    - ``shape_iqr`` — sans unité — sa forme, écart interquartile d'un logarithme,
      ``None`` sous le seuil d'activités ou sans niveau (P4.3, P4.4) ;
    - ``shape_activity_count`` — sans unité — les activités de la forme.

    Diagnostics (P1.6, P3.5) : ``moving_total_s`` (s, le temps M de toutes ses
    cellules de temps M positif), ``length_moving_m`` et ``length_all_m`` (m, ses
    longueurs de temps M positif et toutes), ``elapsed_total_s`` (s, l'écoulé de toutes
    ses cellules), ``moving_activities`` (ses cellules de temps M positif),
    ``n_eff_moving`` (sans unité, ``(Σ M_j)² / Σ M_j²`` : la **concentration des
    poids**, pas un nombre de jours indépendants), ``max_moving_share`` (la plus grande
    part de temps M d'une activité) et ``mean_grade`` (fraction, la pente moyenne
    pondérée par la longueur en mouvement).
    """

    lower_permille: int
    upper_permille: int
    center_grade: float
    speed_ms: float
    elapsed_speed_ms: float
    moving_s: float
    activity_count: int
    mean_hr_bpm: float | None
    shape_iqr: float | None
    shape_activity_count: int
    moving_total_s: float = 0.0
    length_moving_m: float = 0.0
    length_all_m: float = 0.0
    elapsed_total_s: float = 0.0
    moving_activities: int = 0
    n_eff_moving: float = 0.0
    max_moving_share: float = 0.0
    mean_grade: float = 0.0


@dataclass(frozen=True)
class LevelQuantiles:
    """Les quantiles du niveau ``λ_j = ln(T_j / P_j)`` des activités (sans unité), par
    la règle de rang (``0017``, P4.2) : ``p10``, ``p50`` (la médiane inférieure),
    ``p90`` ; ``count``, le nombre de niveaux. Un diagnostic d'ajustement, en
    échantillon."""

    p10: float
    p50: float
    p90: float
    count: int


@dataclass(frozen=True)
class CurveCounts:
    """Les comptes par étage d'une estimation (``0017``, P2.6, P5.3).

    Activités : ``candidates`` (reçues), ``with_intervals`` (sans refus de trace),
    ``eligible`` (dans la fenêtre de durée), ``retained`` (avec un intervalle retenu),
    ``moving`` (avec un intervalle retenu de temps M positif : celles de (a)),
    ``median`` (avec une cellule de temps M positif d'au moins ``median_min_moving_s`` :
    celles de (b)), ``with_level`` (le nombre de niveaux) ; avec un filtre de FC
    seulement, sinon ``None`` : ``filtered_side`` (les retenues qui ont un intervalle
    retenu de temps M positif à une pente de ``hr_min_grade`` ou plus) et
    ``descents_only`` (``moving − filtered_side`` : observations de descente non
    filtrées).

    Intervalles des activités éligibles : ``intervals`` (toute leur grille, ceux retirés
    au plafond compris), ``truncated`` (coupés au plafond), ``retained_intervals``,
    ``retained_without_moving`` ; ``length_all_m`` et ``length_moving_m`` (m,
    longueurs des intervalles retenus, tous ou de temps M positif), ``moving_s`` et
    ``elapsed_s`` (s, temps M et écoulé des intervalles retenus), ``after_ceiling_s``
    (s, écoulé retiré au-delà du plafond) ; ``excluded_length_m`` (m, par motif
    d'écart, dans l'ordre de :class:`IntervalExclusion`, sans les motifs à zéro).
    """

    candidates: int
    with_intervals: int
    eligible: int
    retained: int
    moving: int
    median: int
    with_level: int
    filtered_side: int | None
    descents_only: int | None
    intervals: int
    truncated: int
    retained_intervals: int
    retained_without_moving: int
    length_all_m: float
    length_moving_m: float
    moving_s: float
    elapsed_s: float
    after_ceiling_s: float
    excluded_length_m: tuple[tuple[IntervalExclusion, float], ...] = ()


@dataclass(frozen=True)
class CurveEstimate:
    """Le résultat d'une estimation.

    - ``bins`` — les tranches estimées, par pente croissante ;
    - ``level`` — les quantiles du niveau, ``None`` si la courbe n'est pas projetable ;
    - ``elapsed_moving_ratio`` — sans unité — écoulé / M sur tous les intervalles
      retenus : un descriptif du corpus, jamais un facteur de conversion (P1.6) ;
    - ``activity_refs`` — les activités retenues, dans l'ordre reçu ;
    - ``excluded_activities``, ``excluded_intervals`` — les écarts par motif, dans
      l'ordre de leur énumération, sans les motifs à zéro ;
    - ``counts`` — les comptes par étage.
    """

    bins: tuple[EstimatedBin, ...]
    level: LevelQuantiles | None
    elapsed_moving_ratio: float
    activity_refs: tuple[str, ...]
    excluded_activities: tuple[tuple[ActivityExclusion, int], ...]
    excluded_intervals: tuple[tuple[IntervalExclusion, int], ...]
    counts: CurveCounts


def bin_index(grade: float) -> int | None:
    """L'indice de la tranche de ``grade`` (fraction), ``[lo ; hi[`` : la borne basse
    comprise, la haute non ; ``None`` hors de ``[−100 % ; +100 %[`` (``0017``, P3.1)."""
    k = bisect_right(CURVE_BIN_EDGES_PERMILLE, grade * 1000) - 1
    if k < 0 or k >= len(CURVE_BIN_EDGES_PERMILLE) - 1:
        return None
    return k


def rank_quantile(values: Sequence[float], numerator: int, denominator: int) -> float:
    """La valeur de rang ``⌈n · numerator / denominator⌉`` (à partir de 1) des valeurs
    triées, le rang calculé en entiers (``0017``, P4.2 ; la règle de rang de ``0010``
    D11). Le rang 1/2 est donc la médiane **inférieure** pour ``n`` pair. Précondition :
    ``values`` non vide."""
    ordered = sorted(values)
    n = len(ordered)
    return ordered[(n * numerator + denominator - 1) // denominator - 1]


def select_candidates(
    index: ActivityIndex, selection: CurveSelection
) -> tuple[IndexedActivity, ...]:
    """Les entrées de l'index, dans son ordre, qui ont un enregistrement, dont le type
    de la source est dans la sélection et dont le jour civil local du départ
    (``entry.start_time.date()``, l'heure locale de l'index, sans passer par l'UTC) est
    dans ``[date_from ; date_to]``, bornes comprises (``0017``, P2.1, P2.2).

    Ce jour peut différer du jour à Paris de ``0010`` (D0, D2.2) pour une sortie
    enregistrée sous un autre fuseau ; l'index est la source de vérité du filtre
    (``0013``, précision 3).
    """
    return tuple(
        entry
        for entry in index.entries
        if entry.has_recording
        and entry.source_activity_type in selection.source_activity_types
        and selection.date_from <= entry.start_time.date() <= selection.date_to
    )


@dataclass
class _Cell:
    """Les cumuls d'une activité dans une tranche (``+=``, dans l'ordre des
    intervalles)."""

    length_all_m: float = 0.0
    elapsed_s: float = 0.0
    length_moving_m: float = 0.0
    moving_s: float = 0.0
    grade_length_m: float = 0.0
    hr_moving: float = 0.0
    hr_moving_s: float = 0.0
    moving_intervals: list[CurveInterval] = field(default_factory=list)


def _interval_exclusion(
    interval: CurveInterval, selection: CurveSelection, parameters: ParameterSet
) -> IntervalExclusion | None:
    """Le premier motif d'écart de ``interval``, ou ``None`` s'il est retenu (``0017``,
    P2.6, P3.6, P5.2)."""
    if bin_index(interval.grade) is None:
        return IntervalExclusion.GRADE
    elapsed = interval.elapsed_s
    if elapsed <= 0:
        return IntervalExclusion.NO_ELAPSED
    vertical = interval.length_m * interval.grade / elapsed
    if (
        interval.length_m / elapsed > parameters["max_elapsed_speed_ms"]
        or vertical > parameters["max_ascent_speed_ms"]
        or vertical < -parameters["max_descent_speed_ms"]
    ):
        return IntervalExclusion.ABERRANT
    center = selection.hr_center_bpm
    if center is not None and interval.grade >= parameters["hr_min_grade"]:
        if interval.heart_rate_bpm is None:
            return IntervalExclusion.HR_UNDEFINED
        if abs(interval.heart_rate_bpm - center) > parameters["hr_width_bpm"] / 2:
            return IntervalExclusion.HR_OUTSIDE
    return None


def _cells(intervals: Sequence[CurveInterval]) -> dict[int, _Cell]:
    """Les cellules d'une activité retenue, par tranche (``0017``, P3.3, P1.6)."""
    cells: dict[int, _Cell] = {}
    for interval in intervals:
        k = bin_index(interval.grade)
        assert k is not None
        cell = cells.setdefault(k, _Cell())
        cell.length_all_m += interval.length_m
        cell.elapsed_s += interval.elapsed_s
        if interval.moving_s > 0:
            cell.length_moving_m += interval.length_m
            cell.moving_s += interval.moving_s
            cell.grade_length_m += interval.grade * interval.length_m
            cell.moving_intervals.append(interval)
            if interval.heart_rate_bpm is not None:
                cell.hr_moving += interval.heart_rate_bpm * interval.moving_s
                cell.hr_moving_s += interval.moving_s
    return cells


def _estimated_bin(
    k: int, cells: Sequence[_Cell], value: BinValue, median_min_moving_s: float
) -> EstimatedBin | None:
    """La tranche ``k`` depuis les cellules de ses activités ; ``None`` sans temps M,
    ou, avec (b), sans activité au seuil (``0017``, P3.3 à P3.5)."""
    moving_cells = [cell for cell in cells if cell.moving_s > 0]
    moving_total = math.fsum(cell.moving_s for cell in moving_cells)
    if moving_total == 0:
        return None
    length_moving = math.fsum(cell.length_moving_m for cell in moving_cells)
    if value is BinValue.POOLED:
        speed = length_moving / moving_total
        carried = moving_total
        count = len(moving_cells)
    else:
        median_cells = [c for c in moving_cells if c.moving_s >= median_min_moving_s]
        if not median_cells:
            return None
        speed = statistics.median(c.length_moving_m / c.moving_s for c in median_cells)
        carried = math.fsum(c.moving_s for c in median_cells)
        count = len(median_cells)
    hr_time = math.fsum(cell.hr_moving_s for cell in moving_cells)
    lower, upper = CURVE_BIN_EDGES_PERMILLE[k], CURVE_BIN_EDGES_PERMILLE[k + 1]
    moving = [cell.moving_s for cell in moving_cells]
    return EstimatedBin(
        lower_permille=lower,
        upper_permille=upper,
        center_grade=(lower + upper) / 2000,
        speed_ms=speed,
        elapsed_speed_ms=math.fsum(c.length_all_m for c in cells)
        / math.fsum(c.elapsed_s for c in cells),
        moving_s=carried,
        activity_count=count,
        mean_hr_bpm=(
            None
            if hr_time == 0
            else math.fsum(cell.hr_moving for cell in moving_cells) / hr_time
        ),
        shape_iqr=None,
        shape_activity_count=0,
        moving_total_s=moving_total,
        length_moving_m=length_moving,
        length_all_m=math.fsum(c.length_all_m for c in cells),
        elapsed_total_s=math.fsum(c.elapsed_s for c in cells),
        moving_activities=len(moving_cells),
        n_eff_moving=moving_total**2 / math.fsum(m * m for m in moving),
        max_moving_share=max(moving) / moving_total,
        mean_grade=math.fsum(c.grade_length_m for c in moving_cells) / length_moving,
    )


def _predicted_s(model: PaceModel, intervals: Sequence[CurveInterval]) -> float:
    """Le temps que le moteur prévoit sur ``intervals``, la somme de
    ``length_m × p(grade)`` (s), prolongement compris (``0009`` D4)."""
    return math.fsum(i.length_m * model.pace_s_per_m(i.grade) for i in intervals)


def _pace_model(bins: Sequence[EstimatedBin]) -> PaceModel | None:
    """Le moteur sur la courbe des tranches estimées, à la règle de support de
    ``read_curve`` ; ``None`` si le support est impossible (``0017``, P3.7, P4.1)."""
    curve_bins = [
        CurveBin(b.center_grade, b.speed_ms, b.moving_s / 60, b.activity_count)
        for b in bins
    ]
    try:
        kept, _ = select_support(curve_bins, SUPPORT_THRESHOLD_MIN)
    except CurveError:
        return None
    return PaceModel(
        PaceCurve(
            sport=Sport.FOOT,
            grade=tuple(b.grade for b in kept),
            speed_ms=tuple(b.speed_ms for b in kept),
            sample_count=tuple(b.sample_count for b in kept),
            dispersion_ms=None,
            estimation=_FILL_PROVENANCE,
            source=None,
        )
    )


def estimate_curve(
    candidates: Sequence[ActivityIntervals | TraceRefusal],
    candidate_refs: Sequence[str],
    selection: CurveSelection,
    parameters: ParameterSet,
) -> CurveEstimate:
    """La courbe estimée sur ``candidates`` (``candidate_refs[i]`` nomme
    ``candidates[i]``), la chaîne de la docstring du module dans cet ordre.

    ``ValueError`` si des intervalles ont été coupés à un autre plafond que celui de la
    sélection (l'appelant coupe au plafond déclaré, ``0017``, P2.4) ; ``CurveError`` si
    aucune tranche ne s'estime, avec la raison.
    """
    activity_exclusions: Counter[ActivityExclusion] = Counter()
    interval_exclusions: Counter[IntervalExclusion] = Counter()
    excluded_length: defaultdict[IntervalExclusion, list[float]] = defaultdict(list)
    retained: list[tuple[str, list[CurveInterval]]] = []
    with_intervals = eligible = intervals = truncated = 0
    after_ceiling: list[float] = []
    for ref, candidate in zip(candidate_refs, candidates, strict=True):
        if isinstance(candidate, TraceRefusal):
            activity_exclusions[
                ActivityExclusion.NO_TRACE
                if candidate is TraceRefusal.NO_TRACE
                else ActivityExclusion.NO_PROFILE
            ] += 1
            continue
        with_intervals += 1
        if candidate.ceiling_s != selection.max_elapsed_s:
            raise ValueError(
                f"{ref} : intervalles coupés au plafond {candidate.ceiling_s}, la "
                f"sélection déclare le plafond {selection.max_elapsed_s} ; l'appelant "
                "coupe les intervalles au plafond déclaré (0017, P2.4)."
            )
        if (
            selection.min_duration_s is not None
            and candidate.elapsed_s < selection.min_duration_s
        ):
            activity_exclusions[ActivityExclusion.SHORT] += 1
            continue
        if (
            selection.max_duration_s is not None
            and candidate.elapsed_s >= selection.max_duration_s
        ):
            activity_exclusions[ActivityExclusion.LONG] += 1
            continue
        eligible += 1
        intervals += len(candidate.intervals) + candidate.after_ceiling
        truncated += sum(1 for interval in candidate.intervals if interval.truncated)
        after_ceiling.append(candidate.after_ceiling_s)
        if candidate.after_ceiling:
            interval_exclusions[IntervalExclusion.CEILING] += candidate.after_ceiling
        kept: list[CurveInterval] = []
        for interval in candidate.intervals:
            reason = _interval_exclusion(interval, selection, parameters)
            if reason is None:
                kept.append(interval)
            else:
                interval_exclusions[reason] += 1
                excluded_length[reason].append(interval.length_m)
        if kept:
            retained.append((ref, kept))
        else:
            activity_exclusions[ActivityExclusion.NO_INTERVAL] += 1

    cells = [(ref, _cells(kept)) for ref, kept in retained]
    median_min = parameters["median_min_moving_s"]
    bins: list[EstimatedBin] = []
    members: list[list[tuple[str, _Cell]]] = []
    for k in sorted({k for _, activity in cells for k in activity}):
        present = [(ref, activity[k]) for ref, activity in cells if k in activity]
        estimated = _estimated_bin(
            k, [cell for _, cell in present], selection.value, median_min
        )
        if estimated is not None:
            bins.append(estimated)
            members.append(present)
    if not bins:
        if selection.value is BinValue.MEDIAN:
            raise CurveError(
                f"Aucune tranche estimée : aucune activité n'a {median_min:g} s de "
                "temps en mouvement dans une même tranche (valeur (b))."
            )
        raise CurveError(
            "Aucune tranche estimée : aucun intervalle retenu n'a de temps en "
            "mouvement."
        )

    level: LevelQuantiles | None = None
    levels: dict[str, float] = {}
    model = _pace_model(bins)
    if model is not None:
        for ref, kept in retained:
            moving = [interval for interval in kept if interval.moving_s > 0]
            if moving:
                total = math.fsum(interval.moving_s for interval in moving)
                levels[ref] = math.log(total / _predicted_s(model, moving))
        values = list(levels.values())
        level = LevelQuantiles(
            rank_quantile(values, 1, 10),
            rank_quantile(values, 1, 2),
            rank_quantile(values, 9, 10),
            len(values),
        )
        shape_min_moving = parameters["shape_min_moving_s"]
        for b, estimated in enumerate(bins):
            shapes = [
                math.log(_predicted_s(model, cell.moving_intervals) / cell.moving_s)
                + levels[ref]
                for ref, cell in members[b]
                if cell.moving_s > 0 and cell.moving_s >= shape_min_moving
            ]
            bins[b] = dataclasses.replace(
                estimated,
                shape_iqr=(
                    rank_quantile(shapes, 3, 4) - rank_quantile(shapes, 1, 4)
                    if len(shapes) >= parameters["shape_min_activities"]
                    else None
                ),
                shape_activity_count=len(shapes),
            )

    kept_all = [interval for _, kept in retained for interval in kept]
    moving_kept = [interval for interval in kept_all if interval.moving_s > 0]
    moving_activities = sum(
        1 for _, kept in retained if any(i.moving_s > 0 for i in kept)
    )
    filtered_side: int | None = None
    descents_only: int | None = None
    if selection.hr_center_bpm is not None:
        min_grade = parameters["hr_min_grade"]
        filtered_side = sum(
            1
            for _, kept in retained
            if any(i.moving_s > 0 and i.grade >= min_grade for i in kept)
        )
        descents_only = moving_activities - filtered_side
    counts = CurveCounts(
        candidates=len(candidates),
        with_intervals=with_intervals,
        eligible=eligible,
        retained=len(retained),
        moving=moving_activities,
        median=sum(
            1
            for _, activity in cells
            if any(
                c.moving_s > 0 and c.moving_s >= median_min for c in activity.values()
            )
        ),
        with_level=len(levels),
        filtered_side=filtered_side,
        descents_only=descents_only,
        intervals=intervals,
        truncated=truncated,
        retained_intervals=len(kept_all),
        retained_without_moving=len(kept_all) - len(moving_kept),
        length_all_m=math.fsum(i.length_m for i in kept_all),
        length_moving_m=math.fsum(i.length_m for i in moving_kept),
        moving_s=math.fsum(i.moving_s for i in kept_all),
        elapsed_s=math.fsum(i.elapsed_s for i in kept_all),
        after_ceiling_s=math.fsum(after_ceiling),
        excluded_length_m=tuple(
            (reason, math.fsum(excluded_length[reason]))
            for reason in IntervalExclusion
            if excluded_length[reason]
        ),
    )
    return CurveEstimate(
        bins=tuple(bins),
        level=level,
        elapsed_moving_ratio=counts.elapsed_s / counts.moving_s,
        activity_refs=tuple(ref for ref, _ in retained),
        excluded_activities=tuple(
            (reason, activity_exclusions[reason])
            for reason in ActivityExclusion
            if activity_exclusions[reason]
        ),
        excluded_intervals=tuple(
            (reason, interval_exclusions[reason])
            for reason in IntervalExclusion
            if interval_exclusions[reason]
        ),
        counts=counts,
    )


def _grade_pct(lower: int, upper: int) -> str:
    """Le centre ``(lower + upper) / 20`` en pourcentage, écrit exactement : ``-13.75``,
    ``1.25``, ``37.5``, ``-95``."""
    n = lower + upper
    whole, rest = divmod(abs(n), 20)
    text = f"{'-' if n < 0 else ''}{whole}"
    if rest:
        text += "." + f"{rest * 5:02d}".rstrip("0")
    return text


def curve_file_rows(estimate: CurveEstimate) -> tuple[CurveFileRow, ...]:
    """Les lignes du fichier de courbe, une par tranche estimée, dans l'ordre ; la
    pente est le centre nominal en pourcentage, écrit exactement (``0017``, P3.7)."""
    return tuple(
        CurveFileRow(
            grade_pct=_grade_pct(b.lower_permille, b.upper_permille),
            speed_ms=b.speed_ms,
            mean_hr_bpm=b.mean_hr_bpm,
            time_min=b.moving_s / 60,
            elapsed_speed_ms=b.elapsed_speed_ms,
            activities=b.activity_count,
            shape_iqr=b.shape_iqr,
        )
        for b in estimate.bins
    )


def estimation_document(
    estimate: CurveEstimate,
    selection: CurveSelection,
    parameters: ParameterSet,
    profile_parameters: ParameterSet,
    *,
    commit: str,
    exports_retrieved_at: Sequence[datetime],
    support_error: str | None,
) -> dict[str, object]:
    """Le document que ``write_curve`` range sous la clé ``estimation`` du compagnon,
    et que ``read_curve`` ignore : la méthode, ses paramètres, le niveau, les écarts,
    les comptes et les diagnostics des tranches (``0017``, P5.4), en JSON simple.

    ``exports_retrieved_at`` : les instants d'acquisition des exports lus, distincts
    comme instants, ramenés en UTC et triés comme instants."""
    counts = estimate.counts
    return {
        "method": METHOD,
        "commit": commit,
        "value": selection.value.value,
        "bin_edges_permille": list(CURVE_BIN_EDGES_PERMILLE),
        "clock_convention": "θc",
        "heart_rate_integration": HR_INTEGRATION,
        "heart_rate_max_step_s": MAX_HR_STEP_S,
        "level_kind": "diagnostic d'ajustement, en échantillon",
        "profile_parameters": dict(profile_parameters.values),
        "parameters": dict(parameters.values),
        "projectable": support_error is None,
        "support_error": support_error,
        "level": (
            None
            if estimate.level is None
            else {
                "p10": estimate.level.p10,
                "p50": estimate.level.p50,
                "p90": estimate.level.p90,
                "count": estimate.level.count,
            }
        ),
        "elapsed_moving_ratio": estimate.elapsed_moving_ratio,
        "excluded_activities": {
            reason.value: n for reason, n in estimate.excluded_activities
        },
        "excluded_intervals": {
            reason.value: n for reason, n in estimate.excluded_intervals
        },
        "excluded_length_m": {
            reason.value: metres for reason, metres in counts.excluded_length_m
        },
        "counts": {
            f.name: getattr(counts, f.name)
            for f in dataclasses.fields(CurveCounts)
            if f.name != "excluded_length_m"
        },
        "bins": [
            {
                "lower_permille": b.lower_permille,
                "upper_permille": b.upper_permille,
                "moving_total_s": b.moving_total_s,
                "length_moving_m": b.length_moving_m,
                "length_all_m": b.length_all_m,
                "elapsed_total_s": b.elapsed_total_s,
                "moving_activities": b.moving_activities,
                "n_eff_moving": b.n_eff_moving,
                "max_moving_share": b.max_moving_share,
                "mean_grade": b.mean_grade,
                "shape_activity_count": b.shape_activity_count,
            }
            for b in estimate.bins
        ],
        "exports_retrieved_at": [
            moment.isoformat()
            for moment in sorted({m.astimezone(UTC) for m in exports_retrieved_at})
        ],
    }
