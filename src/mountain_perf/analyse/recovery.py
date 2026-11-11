"""La vue de la page « récupération » (AN2-3, ``docs/decisions/0019``) : les lignes de
la table ``jours`` rangées en données de figure, sans rien calculer de neuf (règle 7 de
``CLAUDE.md``).

La page ne décide rien : la marque d'un jour est l'admission que porte la table ; la
normale et sa plage sont celles de la table, coupées où elle manque, en pointillé quand
elle est à cheval ; les ruptures, les jours incertains, le journal, l'activité du jour
et la HRV selon Garmin sont relus tels quels.

Les dates des marques sont des textes d'instants UTC (``AAAA-MM-JJT12:00:00Z`` au milieu
d'un jour, ``AAAA-MM-JJT00:00:00Z`` à son bord), que la figure lit sur une échelle UTC :
aucun calcul de fuseau ici, sauf :func:`data_at`, à l'heure de Paris.

Python pur : ce module ne demande aucun extra.
"""

from __future__ import annotations

import dataclasses
import itertools
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from types import MappingProxyType
from typing import Any, Final
from zoneinfo import ZoneInfo

from mountain_perf.analyse.days import VALUE_COLUMNS
from mountain_perf.analyse.normals import NormalMeasure
from mountain_perf.schemas.processed import (
    JOURNAL_ABSENT,
    AdmissionRefusal,
    DayRow,
    JournalEventType,
    NormalAbsence,
    ProcessedProvenance,
)

RECENT_DAYS: Final = 56
"""La période par défaut : les 56 dernières lignes de la table (8 semaines), son
dernier jour compris."""

PARIS: Final = ZoneInfo("Europe/Paris")
"""Le fuseau de « Données au … »."""

EDGE_PADDING: Final = 0.05
"""L'élargissement de l'étendue d'un panneau, de chaque côté, en part de sa largeur."""

UNDEFINED: Final = "—"
"""Le texte d'une valeur absente au survol."""


@dataclass(frozen=True)
class MeasureLabel:
    """L'affichage d'une mesure : son titre, son unité (la chaîne vide sans unité), le
    facteur de sa colonne à l'unité affichée, les chiffres après la virgule."""

    title: str
    unit: str
    scale: float
    digits: int


MEASURE_LABELS: Mapping[NormalMeasure, MeasureLabel] = MappingProxyType(
    {
        NormalMeasure.HRV: MeasureLabel("HRV de la nuit", "ms", 1.0, 0),
        NormalMeasure.RESTING_HR: MeasureLabel("FC de repos", "bpm", 1.0, 0),
        NormalMeasure.MEASURED_SLEEP: MeasureLabel("Sommeil mesuré", "h", 1 / 3600, 2),
        NormalMeasure.NIGHT_STRESS: MeasureLabel("Stress de la nuit", "", 1.0, 0),
        NormalMeasure.NIGHT_RESPIRATION: MeasureLabel(
            "Respiration de la nuit", "resp./min", 1.0, 1
        ),
        NormalMeasure.NIGHT_SPO2: MeasureLabel("SpO2 de la nuit", "%", 1.0, 0),
    }
)
"""L'affichage de chaque mesure, dans l'ordre de ``NormalMeasure``."""

REFUSAL_LABELS: Mapping[AdmissionRefusal, str] = MappingProxyType(
    {
        AdmissionRefusal.ABSENT_ROW: "pas de données ce jour",
        AdmissionRefusal.NO_VALUE: "pas de valeur",
        AdmissionRefusal.INVALID_VALUE: "valeur invalide",
        AdmissionRefusal.NIGHT_NOT_COMPLETE: "nuit incomplète",
        AdmissionRefusal.SHORT_NIGHT: "nuit courte",
        AdmissionRefusal.SHIFTED_NIGHT: "nuit décalée",
        AdmissionRefusal.ILLNESS: "maladie (journal)",
        AdmissionRefusal.INJURY: "blessure (journal)",
        AdmissionRefusal.ALTITUDE_STAY: "séjour en altitude (journal)",
    }
)
"""Le libellé de chaque motif de refus, au survol."""

ABSENCE_LABELS: Mapping[NormalAbsence, str] = MappingProxyType(
    {
        NormalAbsence.NO_ADMITTED_DAY: "aucun jour admis dans la fenêtre",
        NormalAbsence.TOO_FEW_ADMITTED_DAYS: "trop peu de jours admis dans la fenêtre",
    }
)
"""Le libellé de chaque motif d'une normale absente, au survol."""

JOURNAL_LABELS: Mapping[JournalEventType, str] = MappingProxyType(
    {
        JournalEventType.ILLNESS: "Maladie",
        JournalEventType.INJURY: "Blessure",
        JournalEventType.RACE: "Course",
        JournalEventType.TRAVEL: "Déplacement",
        JournalEventType.MOVE: "Déménagement",
        JournalEventType.ALTITUDE_STAY: "Séjour en altitude",
        JournalEventType.BENCHMARK: "Étalon",
        JournalEventType.OTHER: "Autre",
    }
)
"""Le libellé de chaque type du journal, dans l'ordre de ``JournalEventType``."""

NIGHT_LABELS: Mapping[str, str] = MappingProxyType(
    {
        "missing": "absente",
        "declared": "déclarée",
        "in_progress": "en cours",
        "partial": "partielle",
        "complete": "complète",
    }
)
"""Le libellé de chaque état de la nuit, par sa valeur."""

RESTING_HR_LABELS: Mapping[str, str] = MappingProxyType(
    {
        "absent": "absente",
        "provisional": "provisoire",
        "no_night": "sans nuit",
        "valid": "valide",
    }
)
"""Le libellé de chaque statut de la FC de repos, par sa valeur."""

FAMILIES: tuple[tuple[str, str], ...] = (
    ("foot_elapsed_s", "À pied"),
    ("mtb_elapsed_s", "VTT"),
    ("ski_touring_elapsed_s", "Ski de randonnée"),
    ("other_elapsed_s", "Autres"),
)
"""Les durées de l'activité du jour : la colonne et son libellé, dans l'ordre de
l'empilement."""

LEGEND_DEFAULTS: Mapping[str, float] = MappingProxyType(
    {"normal.window_days": 28.0, "normal.range_k": 1.0, "normal.mad_factor": 1.4826}
)
"""Les paramètres de la provenance sous lesquels vaut ``EXPERT_LEGEND``."""

NO_TREND: Final = "Aucune bande simultanée n'est calculée : ne pas y lire une tendance."
"""La phrase qui clôt toute légende."""

EXPERT_LEGEND: tuple[str, ...] = (
    "Plage habituelle : médiane ± 1 écart robuste des jours valides parmi les 28 "
    "précédents (n jours : au survol). Environ un jour ordinaire sur trois en sort. "
    "Ce n'est pas un intervalle de confiance ; en sortir n'est pas une alerte.",
    "La normale suit un changement durable en deux semaines environ. " + NO_TREND,
)
"""La légende sous les paramètres par défaut (``LEGEND_DEFAULTS``)."""

_TRACKING = "La normale suit un changement durable en deux semaines environ."
_TRACKING_WINDOW = 28.0


@dataclass(frozen=True)
class MeasurePanel:
    """Le panneau d'une mesure : ses points (un par jour de la période), les suites de
    sa normale, ses normales isolées, ses ruptures, et son étendue (``None`` : un
    panneau vide)."""

    measure: NormalMeasure
    title: str
    unit: str
    points: tuple[Mapping[str, Any], ...]
    normal_lines: tuple[Mapping[str, Any], ...]
    isolated: tuple[Mapping[str, Any], ...]
    ruptures: tuple[Mapping[str, Any], ...]
    domain: tuple[float, float] | None

    @property
    def empty(self) -> bool:
        """Vrai si et seulement si le panneau n'a pas d'étendue."""
        return self.domain is None


@dataclass(frozen=True)
class RecoveryView:
    """Ce que montre la page « récupération » d'une table ``jours``."""

    data_at: str
    journal_absent: bool
    everything: bool
    first_day: date | None
    last_day: date | None
    x_domain: tuple[str, str] | None
    panels: tuple[MeasurePanel, ...]
    uncertain: tuple[Mapping[str, Any], ...]
    ribbons: tuple[Mapping[str, Any], ...]
    durations: tuple[Mapping[str, Any], ...]
    loads: tuple[Mapping[str, Any], ...]
    garmin_hrv: tuple[Mapping[str, Any], ...]
    legend: tuple[str, ...]


def _unit_suffix(measure: NormalMeasure) -> str:
    """Le suffixe d'unité des colonnes de normale de ``measure``, lu sur ``DayRow``."""
    prefix = f"{measure.value}_range_low"
    return next(
        f.name[len(prefix) :]
        for f in dataclasses.fields(DayRow)
        if f.name.startswith(prefix)
    )


_SUFFIXES: Mapping[NormalMeasure, str] = MappingProxyType(
    {measure: _unit_suffix(measure) for measure in NormalMeasure}
)


def _number(value: float, digits: int, unit: str = "") -> str:
    """``value`` arrondie à ``digits`` décimales, virgule décimale, « − » pour le
    signe, puis l'unité s'il y en a une."""
    text = f"{value:.{digits}f}".replace(".", ",").replace("-", "−")
    return f"{text} {unit}" if unit else text


def _day_text(day: date) -> str:
    return f"{day:%d/%m/%Y}"


def _edge(day: date) -> str:
    """Le début de ``day``, en instant UTC."""
    return f"{day.isoformat()}T00:00:00Z"


def _noon(day: date) -> str:
    """Le milieu de ``day``, en instant UTC."""
    return f"{day.isoformat()}T12:00:00Z"


def _next(day: date) -> date:
    return day + timedelta(days=1)


def data_at(provenance: ProcessedProvenance) -> str:
    """« Données au JJ/MM/AAAA à H h MM (heure de Paris) » : ``acquired_at``, à l'heure
    de Paris, quel que soit le fuseau de la machine."""
    instant = datetime.fromisoformat(provenance.acquired_at).astimezone(PARIS)
    return (
        f"Données au {instant:%d/%m/%Y} à {instant.hour} h {instant.minute:02d} "
        "(heure de Paris)"
    )


def legend(provenance: ProcessedProvenance) -> tuple[str, ...]:
    """La légende des normales : ``EXPERT_LEGEND`` sous les paramètres par défaut,
    sinon les paramètres de la provenance, sans la part des jours qui sortent."""
    parameters = dict(provenance.parameters)
    if all(parameters.get(name) == value for name, value in LEGEND_DEFAULTS.items()):
        return EXPERT_LEGEND
    window = parameters.get("normal.window_days", 0.0)
    k = parameters.get("normal.range_k", 0.0)
    factor = parameters.get("normal.mad_factor", 0.0)
    first = (
        f"Plage habituelle : médiane ± {_number(k, 2)} écart robuste des jours valides "
        f"parmi les {_number(window, 0)} précédents (n jours : au survol) ; écart "
        f"robuste : {_number(factor, 4)} × MAD, au moins la résolution de la mesure ; "
        "pour la HRV, en log. Paramètres hors des valeurs par défaut : la part des "
        "jours qui en sortent n'est pas dite. Ce n'est pas un intervalle de "
        "confiance ; en sortir n'est pas une alerte."
    )
    second = f"{_TRACKING} {NO_TREND}" if window == _TRACKING_WINDOW else NO_TREND
    return (first, second)


def period(rows: Sequence[DayRow], *, everything: bool) -> tuple[DayRow, ...]:
    """Toutes les lignes, ou les ``RECENT_DAYS`` dernières."""
    return tuple(rows) if everything else tuple(rows[-RECENT_DAYS:])


def _check_consecutive(rows: Sequence[DayRow]) -> None:
    for before, after in itertools.pairwise(rows):
        if after.day != _next(before.day):
            raise ValueError(
                f"Les lignes ne sont pas consécutives : {before.day.isoformat()} puis "
                f"{after.day.isoformat()}."
            )


def _night(row: DayRow) -> str:
    flags = []
    for flag, name in ((row.night_short, "courte"), (row.night_shifted, "décalée")):
        if flag is None:
            flags.append(f"{name} : inconnu")
        elif flag:
            flags.append(name)
    label = NIGHT_LABELS[row.night_state.value]
    return f"{label} ({', '.join(flags)})" if flags else label


def _domain(
    rows: Sequence[DayRow], measure: NormalMeasure
) -> tuple[tuple[float, float] | None, bool]:
    """L'étendue du panneau (V5), et si elle vient des valeurs admises, de la plage
    ou des refusées autres que ``invalid_value`` (alors V6 pose au bord)."""
    label = MEASURE_LABELS[measure]
    prefix, suffix = measure.value, _SUFFIXES[measure]
    value_column = VALUE_COLUMNS[measure]
    main: list[float] = []
    refused: list[float] = []
    valid_refused: list[float] = []
    for row in rows:
        value = getattr(row, value_column)
        if value is not None:
            if getattr(row, f"{prefix}_admitted"):
                main.append(value * label.scale)
            else:
                refused.append(value * label.scale)
                if getattr(row, f"{prefix}_refusal") is not (
                    AdmissionRefusal.INVALID_VALUE
                ):
                    valid_refused.append(value * label.scale)
        low = getattr(row, f"{prefix}_range_low{suffix}")
        high = getattr(row, f"{prefix}_range_high{suffix}")
        if low is not None and high is not None:
            main += [low * label.scale, high * label.scale]
    candidates, edges = main or valid_refused, True
    if not candidates:
        candidates, edges = refused, False
    if not candidates:
        return None, False
    lowest, highest = min(candidates), max(candidates)
    if highest > lowest:
        width = highest - lowest
        return (lowest - EDGE_PADDING * width, highest + EDGE_PADDING * width), edges
    pad = max(abs(highest) * EDGE_PADDING, 1.0)
    return (lowest - pad, highest + pad), edges


def _points(
    rows: Sequence[DayRow],
    measure: NormalMeasure,
    domain: tuple[float, float] | None,
    edges: bool,
) -> tuple[Mapping[str, Any], ...]:
    label = MEASURE_LABELS[measure]
    prefix, suffix = measure.value, _SUFFIXES[measure]
    points = []
    for row in rows:
        value = getattr(row, VALUE_COLUMNS[measure])
        admitted = getattr(row, f"{prefix}_admitted")
        shown = None if value is None else value * label.scale
        mark = "plein" if admitted else ("creux" if value is not None else "pied")
        y, outside = shown, None
        if shown is not None and domain is not None and edges:
            if shown < domain[0]:
                y, outside = domain[0], "dessous"
            elif shown > domain[1]:
                y, outside = domain[1], "dessus"
        refusal = getattr(row, f"{prefix}_refusal")
        normal = getattr(row, f"{prefix}_normal{suffix}")
        if normal is not None:
            normal_text = _number(normal * label.scale, label.digits, label.unit)
            if getattr(row, f"{prefix}_normal_straddles"):
                normal_text += " (à cheval)"
        else:
            absence = getattr(row, f"{prefix}_normal_absence")
            normal_text = f"absente : {ABSENCE_LABELS[absence]}"
        low = getattr(row, f"{prefix}_range_low{suffix}")
        high = getattr(row, f"{prefix}_range_high{suffix}")
        if low is not None and high is not None:
            range_text = (
                f"{_number(low * label.scale, label.digits)} à "
                f"{_number(high * label.scale, label.digits, label.unit)}"
            )
        else:
            range_text = UNDEFINED
        points.append(
            {
                "midi": _noon(row.day),
                "marque": mark,
                "y": y,
                "hors": outside,
                "Jour": _day_text(row.day),
                "Valeur": UNDEFINED
                if shown is None
                else _number(shown, label.digits, label.unit),
                "Admission": "admise"
                if refusal is None
                else f"refusée : {REFUSAL_LABELS[refusal]}",
                "Nuit": _night(row),
                "FC de repos": RESTING_HR_LABELS[row.resting_hr_status.value],
                "Normale": normal_text,
                "Plage": range_text,
                "Jours admis": getattr(row, f"{prefix}_admitted_days"),
            }
        )
    return tuple(points)


@dataclass
class _Run:
    """Une suite de la normale : ses jours (des indices de la période), son segment,
    si elle est à cheval."""

    days: list[int]
    segment: int
    straddles: bool


def _runs(rows: Sequence[DayRow], measure: NormalMeasure) -> list[_Run]:
    """Les suites de la normale (V8)."""
    prefix, suffix = measure.value, _SUFFIXES[measure]
    runs: list[_Run] = []
    current: _Run | None = None
    for i, row in enumerate(rows):
        if getattr(row, f"{prefix}_normal{suffix}") is None:
            current = None
            continue
        segment = getattr(row, f"{prefix}_segment")
        straddles = getattr(row, f"{prefix}_normal_straddles")
        if (
            current is not None
            and current.segment == segment
            and current.straddles == straddles
        ):
            current.days.append(i)
        else:
            current = _Run([i], segment, straddles)
            runs.append(current)
    return runs


def _normal_record(
    row: DayRow, measure: NormalMeasure, key: str, dashed: bool
) -> Mapping[str, Any]:
    label = MEASURE_LABELS[measure]
    prefix, suffix = measure.value, _SUFFIXES[measure]
    return {
        "midi": _noon(row.day),
        "normale": getattr(row, f"{prefix}_normal{suffix}") * label.scale,
        "bas": getattr(row, f"{prefix}_range_low{suffix}") * label.scale,
        "haut": getattr(row, f"{prefix}_range_high{suffix}") * label.scale,
        "suite": key,
        "pointille": dashed,
        "trait": "pointillé" if dashed else "plein",
    }


def _normals(
    rows: Sequence[DayRow], measure: NormalMeasure
) -> tuple[tuple[Mapping[str, Any], ...], tuple[Mapping[str, Any], ...]]:
    """Les suites de la normale (V8, V9) et les normales isolées (V10)."""
    runs = _runs(rows, measure)
    per_segment: dict[int, int] = {}
    for run in runs:
        per_segment[run.segment] = per_segment.get(run.segment, 0) + len(run.days)
    lines: list[Mapping[str, Any]] = []
    isolated: list[Mapping[str, Any]] = []
    for n, run in enumerate(runs):
        key = f"s{n}"
        if per_segment[run.segment] == 1:
            isolated.append(
                _normal_record(rows[run.days[0]], measure, key, run.straddles)
            )
            continue
        days = list(run.days)
        if run.straddles:
            if n > 0:
                before = runs[n - 1]
                if before.segment == run.segment and before.days[-1] == days[0] - 1:
                    days.insert(0, before.days[-1])
            if n + 1 < len(runs):
                after = runs[n + 1]
                if after.segment == run.segment and after.days[0] == days[-1] + 1:
                    days.append(after.days[0])
        lines += [_normal_record(rows[i], measure, key, run.straddles) for i in days]
    return tuple(lines), tuple(isolated)


def _panel(rows: Sequence[DayRow], measure: NormalMeasure) -> MeasurePanel:
    label = MEASURE_LABELS[measure]
    domain, edges = _domain(rows, measure)
    lines, isolated = _normals(rows, measure)
    ruptures = tuple(
        {"debut": _edge(row.day), "Rupture": _day_text(row.day)}
        for row in rows
        if getattr(row, f"{measure.value}_rupture")
    )
    title = f"{label.title} ({label.unit})" if label.unit else label.title
    return MeasurePanel(
        measure=measure,
        title=title,
        unit=label.unit,
        points=_points(rows, measure, domain, edges),
        normal_lines=lines,
        isolated=isolated,
        ruptures=ruptures,
        domain=domain,
    )


def _ribbons(
    rows: Sequence[DayRow], first: date | None, last: date | None
) -> tuple[Mapping[str, Any], ...]:
    """Les rubans du journal (V13) : les suites de toute la table, rognées à la
    période."""
    if first is None or last is None:
        return ()
    ribbons: list[dict[str, Any]] = []
    for kind in JournalEventType:
        runs: list[list[date]] = []
        for row in rows:
            if kind in row.journal_types:
                if runs and runs[-1][-1] == row.day - timedelta(days=1):
                    runs[-1].append(row.day)
                else:
                    runs.append([row.day])
        for run in runs:
            if run[-1] < first or run[0] > last:
                continue
            ribbons.append(
                {
                    "type": kind.value,
                    "Type": JOURNAL_LABELS[kind],
                    "debut": _edge(max(run[0], first)),
                    "fin": _edge(_next(min(run[-1], last))),
                    "Période": f"du {_day_text(run[0])} au {_day_text(run[-1])}",
                }
            )
    ribbons.sort(key=lambda ribbon: (ribbon["debut"], ribbon["type"]))
    return tuple(ribbons)


def _durations(rows: Sequence[DayRow]) -> tuple[Mapping[str, Any], ...]:
    durations = []
    for row in rows:
        if row.activity_count <= 0:
            continue
        for order, (column, name) in enumerate(FAMILIES):
            seconds = getattr(row, column)
            if seconds > 0:
                hours = seconds / 3600
                durations.append(
                    {
                        "debut": _edge(row.day),
                        "fin": _edge(_next(row.day)),
                        "famille": name,
                        "ordre": order,
                        "heures": hours,
                        "Jour": _day_text(row.day),
                        "Durée": _number(hours, 2, "h"),
                    }
                )
    return tuple(durations)


def _loads(rows: Sequence[DayRow]) -> tuple[Mapping[str, Any], ...]:
    loads = []
    for row in rows:
        if row.activity_count <= 0:
            continue
        load = row.garmin_training_load
        if load is None:
            mark, text = "pied", "absente (aucune activité n'en a)"
        elif row.activities_without_load > 0:
            mark = "creux"
            text = f"{_number(load, 0)} (minorée : des activités sans charge)"
        else:
            mark, text = "plein", _number(load, 0)
        loads.append(
            {
                "midi": _noon(row.day),
                "charge": load,
                "marque": mark,
                "Jour": _day_text(row.day),
                "Charge": text,
                "Activités": row.activity_count,
                "Sans charge": row.activities_without_load,
                "Autres activités": row.other_activity_count,
                "Sans durée": row.activities_without_elapsed,
            }
        )
    return tuple(loads)


def _garmin_hrv(rows: Sequence[DayRow]) -> tuple[Mapping[str, Any], ...]:
    """La HRV selon Garmin (V17), par suites de jours consécutifs."""
    days = []
    mean_runs = bound_runs = 0
    had_mean = had_bounds = False
    for row in rows:
        mean = row.hrv_weekly_avg_ms
        low = row.hrv_baseline_balanced_low_ms
        high = row.hrv_baseline_balanced_upper_ms
        bounds = low is not None and high is not None
        if mean is not None and not had_mean:
            mean_runs += 1
        if bounds and not had_bounds:
            bound_runs += 1
        had_mean, had_bounds = mean is not None, bounds
        if mean is None and not bounds:
            continue
        days.append(
            {
                "midi": _noon(row.day),
                "moyenne": mean,
                "bas": low,
                "haut": high,
                "suite_moyenne": None if mean is None else f"m{mean_runs}",
                "suite_bornes": f"b{bound_runs}" if bounds else None,
                "Jour": _day_text(row.day),
                "Moyenne de la semaine": UNDEFINED
                if mean is None
                else _number(mean, 0, "ms"),
                "Bornes": f"{_number(low, 0)} à {_number(high, 0, 'ms')}"
                if low is not None and high is not None
                else UNDEFINED,
            }
        )
    return tuple(days)


def recovery_view(
    rows: Sequence[DayRow],
    provenance: ProcessedProvenance,
    *,
    everything: bool = False,
) -> RecoveryView:
    """La vue de ``rows``, les lignes de ``jours`` dans l'ordre, sur la période
    (:func:`period`). ``ValueError`` si deux lignes voisines ne sont pas deux jours
    consécutifs."""
    _check_consecutive(rows)
    shown = period(rows, everything=everything)
    first = shown[0].day if shown else None
    last = shown[-1].day if shown else None
    x_domain = (
        None if first is None or last is None else (_edge(first), _edge(_next(last)))
    )
    return RecoveryView(
        data_at=data_at(provenance),
        journal_absent=provenance.journal_sha256 == JOURNAL_ABSENT,
        everything=everything,
        first_day=first,
        last_day=last,
        x_domain=x_domain,
        panels=tuple(_panel(shown, measure) for measure in NormalMeasure),
        uncertain=tuple(
            {"debut": _edge(row.day), "fin": _edge(_next(row.day))}
            for row in shown
            if row.uncertain_device
        ),
        ribbons=_ribbons(rows, first, last),
        durations=_durations(shown),
        loads=_loads(shown),
        garmin_hrv=_garmin_hrv(shown),
        legend=legend(provenance),
    )
