"""La table ``jours`` (AN2-2, ``docs/decisions/0019``) :
une ligne par jour du calendrier, du premier au dernier document d'``interim/days/``,
bornes comprises.

**Les lignes.** Un jour de l'étendue sans document a sa ligne, d'état ``absent`` ; sans
document du tout, la table n'a aucune ligne. Les lignes sont triées par jour. Chaque
ligne porte, dans cet ordre de calcul :

1. ce que disent les vues des jours (``mountain_perf.ingest.day_views``), appelées avec
   les seuils déclarés ``days.*`` (:data:`DAY_VIEW_PARAMETER_SPECS`) sur **une tranche
   bornée** des documents, jamais sur toute la suite (ci-dessous) : l'état de la nuit
   et ses drapeaux (``night_assessment``), la FC de repos et son statut
   (``resting_hr_on``), la Training Readiness du réveil (``readiness_on_waking``), la
   couverture de la série de Body Battery de la nuit (``series_between``) ;
2. les valeurs du document du jour, selon les validités : une grandeur de
   support ``day`` (``QUANTITY_SUPPORTS``) d'un jour qui n'est pas ``complete`` est
   absente de la ligne, sauf la FC de repos, dont ``resting_hr_on`` dit le statut
   (``provisional`` sur un jour tronqué) ; les grandeurs de nuit et de réveil restent ;
3. le stress du jour mesuré et sa validité ; les siestes ; Training Status (chaque
   bloc à la ligne de sa date propre) ; les types du journal ; l'activité du jour (les
   entrées de l'index d'``interim/activities/``) ;
4. l'admission de la valeur de chaque mesure dans les normales (``AdmissionRefusal``,
   le premier motif qui s'applique) ;
5. les normales (``mountain_perf.analyse.normals``), sur les suites de toute la table ;
6. le résumé (:class:`DaySummary`), ce que ``mperf tables`` résume de la table et de
   ce qui reste hors d'elle.

**La tranche bornée.** Les vues parcourent tous les documents
qu'on leur passe ; chacune ne lit que peu de jours. Pour le jour d, prises par
bissection sur la suite triée :

- ``night_assessment`` : les documents des jours ``[d − usual_window_days, d]``,
  bornes comprises (la vue lit les nuits de ``[d − usual_window_days, d − 1]`` et le
  document de d) ;
- ``resting_hr_on`` et ``readiness_on_waking`` : le document de d (aucun, s'il manque) ;
- ``series_between`` sur la nuit de d : les documents des jours ``[d − 1, d + 1]``,
  bornes comprises (une série de la nuit de la veille peut porter des points dans la
  fenêtre de la nuit de d ; une nuit du lendemain finie avant la fin de celle de d y
  entre aussi).

Le coût est linéaire en le nombre de jours (la tranche de ``night_assessment`` a au plus
``usual_window_days + 1`` documents) ; les activités se groupent par jour une seule
fois, les blocs de Training Status aussi.

**Non promis** : la tranche de ``series_between`` rend le même objet que la suite
entière tant qu'aucune nuit d'un document hors de ``[d − 1, d + 1]`` ne porte de point
dans la fenêtre de la nuit de d (une série étirée sur plus d'un jour) ; aucun contrat
d'``interim/days/`` ne l'interdit ; vérifié sur le réel, à revérifier
au contrôle réel de la PR. Les trois autres vues rendent toujours sur leur tranche le
même objet que sur la suite entière : elles ne lisent rien d'autre.

Python pur : la bibliothèque standard, ``mountain_perf.schemas``,
``mountain_perf.validation``, les vues et deux tables de constantes d'``ingest/``
(``SOURCE_TYPE_SPORTS``, la plage du Body Battery), le journal et les normales
d'``analyse/``.
"""

from __future__ import annotations

from bisect import bisect_left, bisect_right
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date, timedelta
from types import MappingProxyType
from typing import Any, NamedTuple

from mountain_perf.analyse.journal import Journal, journal_types_by_day
from mountain_perf.analyse.normals import (
    INTEGER_PARAMETERS,
    MEASURE_SPECS,
    NORMAL_PARAMETER_SPECS,
    MeasureNormal,
    NormalMeasure,
    integer_parameter,
    measure_normals,
    uncertain_days,
)
from mountain_perf.ingest.day_views import (
    night_assessment,
    readiness_on_waking,
    resting_hr_on,
    series_between,
)
from mountain_perf.ingest.families import BODY_BATTERY_LEVEL_RANGE
from mountain_perf.ingest.types import SOURCE_TYPE_SPORTS
from mountain_perf.schemas import (
    QUANTITY_SUPPORTS,
    ActivityIndex,
    DayRecord,
    DayState,
    IndexedActivity,
    NightState,
    ParameterSet,
    ParameterSpec,
    RestingHrStatus,
    SeriesKind,
    Sport,
    Support,
    TrainingStatusHistory,
    ViewAbsence,
)
from mountain_perf.schemas.processed import (
    AdmissionRefusal,
    DayRow,
    DayRowState,
    JournalEventType,
)
from mountain_perf.validation import ContractError

DAY_VIEW_PARAMETER_SPECS: tuple[ParameterSpec, ...] = (
    ParameterSpec(
        name="max_unmeasured_fraction",
        unit=None,
        default=0.2,
        minimum=0.0,
        maximum=1.0,
        description=(
            "Nuit partielle : la part non mesurable de la nuit (non mesurable / "
            "(fin − début)) qui la dépasse strictement rend la nuit partial ; "
            "égale, non."
        ),
    ),
    ParameterSpec(
        name="short_sleep_s",
        unit="s",
        default=14400.0,
        minimum=0.0,
        maximum=86400.0,
        description=(
            "Nuit courte : un sommeil mesuré strictement sous ce seuil pose le "
            "drapeau short ; égal, non."
        ),
    ),
    ParameterSpec(
        name="shift_s",
        unit="s",
        default=14400.0,
        minimum=0.0,
        maximum=43200.0,
        description=(
            "Nuit décalée : un écart circulaire entre le milieu de la nuit et le "
            "milieu habituel strictement au-dessus de ce seuil pose le drapeau "
            "shifted ; égal, non."
        ),
    ),
    ParameterSpec(
        name="usual_window_days",
        unit="d",
        default=28.0,
        minimum=1.0,
        maximum=365.0,
        description=(
            "Milieu habituel de la nuit du jour d : les nuits complete et non "
            "short des jours [d − usual_window_days, d − 1], bornes comprises. Un "
            "compte, entier."
        ),
    ),
    ParameterSpec(
        name="usual_min_nights",
        unit=None,
        default=14.0,
        minimum=1.0,
        maximum=365.0,
        description=(
            "Milieu habituel : strictement moins de nuits, drapeau shifted inconnu "
            "; autant suffisent. Un compte de nuits, entier."
        ),
    ),
    ParameterSpec(
        name="resting_hr_min_sleep_s",
        unit="s",
        default=10800.0,
        minimum=0.0,
        maximum=86400.0,
        description=(
            "FC de repos : une nuit au sommeil mesuré strictement sous ce seuil "
            "donne le statut no_night ; égal, la nuit suffit."
        ),
    ),
    ParameterSpec(
        name="readiness_tolerance_s",
        unit="s",
        default=900.0,
        minimum=0.0,
        maximum=86400.0,
        description=(
            "Training Readiness du réveil : une entrée « réveil » au plus ce temps "
            "avant la fin de la nuit entre (borne comprise)."
        ),
    ),
    ParameterSpec(
        name="stress_min_fraction",
        unit=None,
        default=0.5,
        minimum=0.0,
        maximum=1.0,
        description=(
            "Stress du jour : valide si le temps mesuré (repos, bas, moyen, haut) "
            "atteint cette part de la fenêtre du jour (borne comprise)."
        ),
    ),
    ParameterSpec(
        name="min_coverage_fraction",
        unit=None,
        default=0.8,
        minimum=0.0,
        maximum=1.0,
        description=(
            "Grandeur tirée d'une série : sa couverture strictement sous ce "
            "minimum la rend absente ; égale, elle suffit."
        ),
    ),
    ParameterSpec(
        name="night_body_battery_step_s",
        unit="s",
        default=180.0,
        minimum=0.001,
        maximum=3600.0,
        description=(
            "Pas déclaré de la série de Body Battery de la nuit (une résolution de "
            "la source) : chaque point couvre [t, t + pas) dans la couverture."
        ),
    ),
)
"""Les seuils des vues et des validités de la table ``jours``, communs à tous les
athlètes, portés par la provenance sous ``days.<nom>``. Bornes comprises, celles des
arguments des vues : une fraction dans ``[0, 1]`` ; une durée positive ou nulle, jusqu'à
24 h
(``shift_s`` jusqu'à 12 h, l'écart circulaire le plus grand) ; un compte d'au moins 1,
jusqu'à 365 ; le pas, une résolution strictement positive de la source, dans ``[0,001 ;
3600]``
s.
"""

DAY_VIEW_INTEGER_PARAMETERS: tuple[str, ...] = ("usual_window_days", "usual_min_nights")
"""Les seuils des vues qui sont des comptes, entiers (``night_assessment`` les exige
entiers) : convertis par ``integer_parameter``, qui refuse une valeur non entière.
"""

BODY_BATTERY_CEILING: int = BODY_BATTERY_LEVEL_RANGE[1]
"""Le haut de l'échelle de Garmin, la borne haute de la plage d'un niveau de Body
Battery (``BODY_BATTERY_LEVEL_RANGE``, la lecture des familles) :
``night_body_battery_ceiling`` est vrai si un point de la série de la nuit l'atteint.
"""

SHORT_NIGHT_ADMITTED: frozenset[NormalMeasure] = frozenset(
    {NormalMeasure.MEASURED_SLEEP}
)
"""Les mesures dont la normale admet une nuit ``short`` :
le sommeil mesuré seul, que le drapeau filtrerait par lui-même ; pour les autres
mesures de nuit, une nuit courte est un filtre de qualité (``short_night``).
"""

VALUE_COLUMNS: Mapping[NormalMeasure, str] = MappingProxyType(
    {
        NormalMeasure.HRV: "hrv_last_night_avg_ms",
        NormalMeasure.RESTING_HR: "resting_hr_bpm",
        NormalMeasure.MEASURED_SLEEP: "measured_sleep_s",
        NormalMeasure.NIGHT_STRESS: "night_avg_stress",
        NormalMeasure.NIGHT_RESPIRATION: "respiration_avg_sleep_breaths_per_min",
        NormalMeasure.NIGHT_SPO2: "spo2_avg_sleep_percent",
    }
)
"""La colonne de ``DayRow`` de la valeur que lit chaque mesure :
``hrv.last_night_avg_ms`` ; la FC de repos de ``resting_hr_on`` ; le sommeil mesuré de
``night_assessment`` ; ``night.avg_stress`` ;
``respiration.avg_sleep_breaths_per_min`` ; ``spo2.avg_sleep_spo2_percent``.
"""

_UNITS: Mapping[NormalMeasure, str] = MappingProxyType(
    {
        NormalMeasure.HRV: "_ms",
        NormalMeasure.RESTING_HR: "_bpm",
        NormalMeasure.MEASURED_SLEEP: "_s",
        NormalMeasure.NIGHT_STRESS: "",
        NormalMeasure.NIGHT_RESPIRATION: "_breaths_per_min",
        NormalMeasure.NIGHT_SPO2: "_percent",
    }
)

_DAY_VALUES = (
    ("hrv_last_night_avg_ms", "hrv.last_night_avg_ms"),
    ("hrv_last_night_5min_high_ms", "hrv.last_night_5min_high_ms"),
    ("hrv_weekly_avg_ms", "hrv.weekly_avg_ms"),
    ("hrv_baseline_balanced_low_ms", "hrv.baseline_balanced_low_ms"),
    ("hrv_baseline_balanced_upper_ms", "hrv.baseline_balanced_upper_ms"),
    ("hrv_baseline_low_upper_ms", "hrv.baseline_low_upper_ms"),
    ("hrv_baseline_marker_value", "hrv.baseline_marker_value"),
    ("hrv_status", "hrv.status"),
    (
        "respiration_avg_sleep_breaths_per_min",
        "respiration.avg_sleep_breaths_per_min",
    ),
    (
        "respiration_avg_waking_breaths_per_min",
        "respiration.avg_waking_breaths_per_min",
    ),
    ("spo2_avg_sleep_percent", "spo2.avg_sleep_spo2_percent"),
    ("spo2_average_percent", "spo2.average_spo2_percent"),
    ("spo2_lowest_percent", "spo2.lowest_spo2_percent"),
    ("stress_average_level", "stress.average_level"),
    ("stress_max_level", "stress.max_level"),
    ("body_battery_charged", "body_battery.charged"),
    ("body_battery_drained", "body_battery.drained"),
    ("body_battery_highest", "body_battery.highest"),
    ("body_battery_lowest", "body_battery.lowest"),
    ("body_battery_at_wake", "body_battery.at_wake"),
    ("body_battery_during_sleep", "body_battery.during_sleep"),
    ("steps", "activity_totals.steps"),
    ("moderate_intensity_s", "activity_totals.moderate_intensity_s"),
    ("vigorous_intensity_s", "activity_totals.vigorous_intensity_s"),
    ("floors_ascended_m", "activity_totals.floors_ascended_m"),
    ("floors_descended_m", "activity_totals.floors_descended_m"),
    ("average_altitude_m", "activity_totals.average_altitude_m"),
)
"""Chaque colonne lue telle quelle, et son chemin dans le document, une clé de
``QUANTITY_SUPPORTS``."""

_STRESS_MEASURED_PATHS = (
    "stress.rest_duration_s",
    "stress.low_duration_s",
    "stress.medium_duration_s",
    "stress.high_duration_s",
)

_NIGHT_FIELDS = (
    ("deep_s", "deep_s"),
    ("light_s", "light_s"),
    ("rem_s", "rem_s"),
    ("awake_s", "awake_s"),
    ("unmeasurable_s", "unmeasurable_s"),
    ("night_confirmation", "confirmation"),
    ("night_window_confirmed", "window_confirmed"),
    ("night_from_device", "from_device"),
    ("night_rem_capable", "rem_capable"),
    ("sleep_score", "sleep_score"),
    ("night_avg_stress", "avg_stress"),
    ("night_avg_heart_rate_bpm", "avg_heart_rate_bpm"),
    ("night_body_battery_change", "body_battery_change"),
    ("night_restless_moments", "restless_moments"),
    ("skin_temperature_deviation_c", "skin_temperature_deviation_c"),
)

_VERSION_FIELDS = (
    "sleep_version",
    "sleep_respiration_version",
    "respiration_version",
    "summary_respiration_version",
    "summary_body_battery_version",
)

_TRAINING_STATUS = (
    (
        "statuses",
        "ts_status_instant",
        (
            ("ts_status_code", "status_code"),
            ("ts_acute_load", "acute_load"),
            ("ts_chronic_load", "chronic_load"),
            ("ts_acute_chronic_ratio", "acute_chronic_ratio"),
            ("ts_acwr_status", "acwr_status"),
        ),
    ),
    (
        "load_balances",
        "ts_load_balance_instant",
        (
            ("ts_monthly_aerobic_low", "monthly_aerobic_low"),
            ("ts_monthly_aerobic_low_target_min", "monthly_aerobic_low_target_min"),
            ("ts_monthly_aerobic_low_target_max", "monthly_aerobic_low_target_max"),
            ("ts_monthly_aerobic_high", "monthly_aerobic_high"),
            ("ts_monthly_aerobic_high_target_min", "monthly_aerobic_high_target_min"),
            ("ts_monthly_aerobic_high_target_max", "monthly_aerobic_high_target_max"),
            ("ts_monthly_anaerobic", "monthly_anaerobic"),
            ("ts_monthly_anaerobic_target_min", "monthly_anaerobic_target_min"),
            ("ts_monthly_anaerobic_target_max", "monthly_anaerobic_target_max"),
        ),
    ),
    (
        "vo2_max",
        "ts_vo2_max_instant",
        (
            ("ts_vo2_max_ml_kg_min", "vo2_max_ml_kg_min"),
            ("ts_vo2_max_precise_ml_kg_min", "vo2_max_precise_ml_kg_min"),
        ),
    ),
    (
        "heat_acclimation",
        "ts_heat_instant",
        (
            ("ts_heat_acclimation_percent", "heat_acclimation_percent"),
            ("ts_heat_trend", "heat_trend"),
        ),
    ),
    (
        "altitude_acclimation",
        "ts_altitude_instant",
        (
            ("ts_acclimation_altitude_m", "acclimation_altitude_m"),
            ("ts_current_altitude_m", "current_altitude_m"),
            ("ts_altitude_trend", "altitude_trend"),
        ),
    ),
)
"""Pour chaque sorte de Training Status : sa suite dans ``TrainingStatusHistory``, sa
colonne d'instant, et ses colonnes avec le champ du bloc que chacune lit."""


@dataclass(frozen=True)
class DaySummary:
    """Ce que ``mperf tables`` résume de la table ``jours`` et de ce qui reste hors
    d'elle (AN2-2) ; chaque champ est un compte. Les activités et les blocs de Training
    Status hors de l'étendue de la table n'y ont pas de ligne ; les nuits et les lignes
    ``absent``, la table les porte aussi (``night_body_battery_absence``, ``state``).

    - ``activities_before_first_day``, ``activities_after_last_day`` — les entrées de
      l'index dont le départ, en date locale, précède le premier jour de la table, ou
      suit le dernier : elles n'ont pas de ligne ; une table sans ligne n'a pas
      d'étendue, et toutes ses activités se comptent avant le premier jour ;
    - ``blocks_outside_days`` — les blocs de Training Status d'un jour hors de
      l'étendue de la table (tous, sans ligne) ;
    - ``nights_below_body_battery_coverage`` — les nuits dont la série de Body Battery
      est sous le minimum de couverture (motif ``below_coverage`` ; une nuit sans point
      n'en est pas : ``nights_without_body_battery_point``) ;
    - ``nights_without_body_battery_point`` — les nuits dont la série de Body Battery
      n'a aucun point dans la fenêtre de la nuit (motif ``no_point`` ; par exemple un
      jour ancien dont la source a vidé la série) ; une ligne sans nuit (motif
      ``no_night``, une ligne ``absent`` comprise) n'est comptée ni ici ni au-dessus ;
    - ``absent_days`` — les lignes ``absent``.

    Le résumé n'est pas écrit dans ``processed/`` : des tables relues
    (``read_tables``) n'en ont pas.
    """

    activities_before_first_day: int
    activities_after_last_day: int
    blocks_outside_days: int
    nights_below_body_battery_coverage: int
    nights_without_body_battery_point: int
    absent_days: int


@dataclass(frozen=True)
class DayDefinition:
    """Les paramètres déclarés de la table ``jours`` : ``views``, les seuils des vues
    et des validités (:data:`DAY_VIEW_PARAMETER_SPECS`) ; ``normals``, ceux des
    normales (``NORMAL_PARAMETER_SPECS``).

    ``ValueError`` à la construction si un jeu n'est pas de ses specs, ou si un compte
    ou l'interrupteur n'est pas entier (``integer_parameter``, qui nomme le
    paramètre).
    """

    views: ParameterSet
    normals: ParameterSet

    def __post_init__(self) -> None:
        if (
            not isinstance(self.views, ParameterSet)
            or self.views.specs != DAY_VIEW_PARAMETER_SPECS
        ):
            raise ValueError("views doit être un jeu de ses specs déclarées.")
        if (
            not isinstance(self.normals, ParameterSet)
            or self.normals.specs != NORMAL_PARAMETER_SPECS
        ):
            raise ValueError("normals doit être un jeu de ses specs déclarées.")
        for name in DAY_VIEW_INTEGER_PARAMETERS:
            integer_parameter(self.views, name)
        for name in INTEGER_PARAMETERS:
            integer_parameter(self.normals, name)

    def items(self) -> tuple[tuple[str, float], ...]:
        """Tous les paramètres, ``days.<nom>`` et ``normal.<nom>``, triés."""
        out = [(f"days.{name}", float(v)) for name, v in self.views.values.items()]
        out += [(f"normal.{name}", float(v)) for name, v in self.normals.values.items()]
        return tuple(sorted(out))


DEFAULT_DAY_DEFINITION = DayDefinition(
    ParameterSet(DAY_VIEW_PARAMETER_SPECS), ParameterSet(NORMAL_PARAMETER_SPECS)
)
"""La définition par défaut de la table ``jours`` : les défauts déclarés."""


@dataclass(frozen=True)
class DayTable:
    """Ce que rend :func:`day_rows` : les lignes, triées par jour, et le résumé."""

    rows: tuple[DayRow, ...]
    summary: DaySummary


class DaySlices(NamedTuple):
    """Les tranches des documents que les vues lisent pour un jour. Elles ne servent
    qu'aux vues : le document du jour se prend par son jour, jamais dans une tranche,
    et la table calculée avec des tranches égales à toute la suite est la même.
    """

    night: tuple[DayRecord, ...]
    own: tuple[DayRecord, ...]
    series: tuple[DayRecord, ...]


def _shifted(day: date, days: int) -> date:
    """``day`` décalé de ``days`` jours, arrêté au bout du calendrier de ``date``."""
    try:
        return day + timedelta(days=days)
    except OverflowError:
        return date.max if days > 0 else date.min


def day_slices(
    days: tuple[DayRecord, ...],
    keys: Sequence[date],
    day: date,
    usual_window_days: int,
) -> DaySlices:
    """Les tranches du jour ``day`` dans ``days`` (triés par jour, ``keys`` leurs
    jours) : ``[day − usual_window_days, day]`` pour ``night_assessment`` ; ``[day,
    day]`` pour ``resting_hr_on`` et ``readiness_on_waking`` ; ``[day − 1, day + 1]``
    pour ``series_between``, bornes comprises. Une borne qui sortirait du calendrier
    de ``date`` s'arrête à son bout, sans erreur.
    """

    def between(first: date, last: date) -> tuple[DayRecord, ...]:
        return days[bisect_left(keys, first) : bisect_right(keys, last)]

    return DaySlices(
        night=between(_shifted(day, -usual_window_days), day),
        own=between(day, day),
        series=between(_shifted(day, -1), _shifted(day, 1)),
    )


def activity_columns(entries: Sequence[IndexedActivity]) -> dict[str, Any]:
    """L'activité d'un jour, depuis ses entrées de l'index (de tout type, avec ou sans
    enregistrement) :

    - ``activity_count`` — les entrées ;
    - ``garmin_training_load`` — la somme des ``training_load`` présentes ; ``0.0``
      sans activité ; **absente** si le jour a des activités et que toutes en sont
      sans (un manque, pas zéro) ; une charge nulle est une valeur ;
    - ``activities_without_load`` — les entrées sans ``training_load`` ;
    - ``foot_elapsed_s``, ``mtb_elapsed_s``, ``ski_touring_elapsed_s`` — la somme des
      ``elapsed_duration_s`` des entrées de chaque famille de ``SOURCE_TYPE_SPORTS`` ;
    - ``other_elapsed_s``, ``other_activity_count`` — la somme des temps écoulés des
      types sans famille, et leur nombre (avec ou sans temps écoulé) ;
    - ``activities_without_elapsed`` — les entrées sans temps écoulé, ajoutées à
      aucune durée.

    Une sortie enregistrée deux fois (deux entrées) s'additionne deux fois.
    """
    loads = [e.training_load for e in entries if e.training_load is not None]
    durations = dict.fromkeys((Sport.FOOT, Sport.MTB, Sport.SKI_TOURING, None), 0.0)
    other_count = 0
    without_elapsed = 0
    for entry in entries:
        sport = SOURCE_TYPE_SPORTS.get(entry.source_activity_type)
        if sport is None:
            other_count += 1
        if entry.elapsed_duration_s is None:
            without_elapsed += 1
        else:
            durations[sport] += entry.elapsed_duration_s
    return {
        "activity_count": len(entries),
        "garmin_training_load": float(sum(loads)) if loads or not entries else None,
        "activities_without_load": len(entries) - len(loads),
        "foot_elapsed_s": durations[Sport.FOOT],
        "mtb_elapsed_s": durations[Sport.MTB],
        "ski_touring_elapsed_s": durations[Sport.SKI_TOURING],
        "other_elapsed_s": durations[None],
        "other_activity_count": other_count,
        "activities_without_elapsed": without_elapsed,
    }


def admission_refusal(
    measure: NormalMeasure,
    columns: Mapping[str, Any],
    *,
    exclude_altitude_stay: bool,
) -> AdmissionRefusal | None:
    """Le motif qui refuse la valeur de ``measure`` du jour (``columns``, ses colonnes
    sans les normales) dans les normales, ou ``None`` si elle est admise : **le premier
    qui s'applique, dans l'ordre d'``AdmissionRefusal``** :

    1. ``absent_row`` : la ligne est ``absent`` ;
    2. ``no_value`` : la valeur de la mesure (:data:`VALUE_COLUMNS`) manque ;
    3. ``invalid_value`` : la FC de repos, d'un statut autre que ``valid`` ; la HRV,
       négative ou nulle (elle n'a pas de logarithme) ;
    4. pour une mesure de nuit : ``night_not_complete`` (état autre que ``complete``),
       ``short_night`` (drapeau ``short`` posé, vrai ; sauf pour le sommeil mesuré,
       :data:`SHORT_NIGHT_ADMITTED`), ``shifted_night`` (drapeau ``shifted`` posé) ;
       un drapeau inconnu (absent) n'exclut pas ;
    5. le journal du jour (la nuit suit son jour de réveil) : ``illness``
       (``maladie``), ``injury`` (``blessure``), ``altitude_stay``
       (``sejour_altitude``, seulement avec ``exclude_altitude_stay``).

    Une valeur refusée reste dans sa colonne ; la normale ne lit que les admises.
    """
    if columns["state"] is DayRowState.ABSENT:
        return AdmissionRefusal.ABSENT_ROW
    value = columns[VALUE_COLUMNS[measure]]
    if value is None:
        return AdmissionRefusal.NO_VALUE
    if (
        measure is NormalMeasure.RESTING_HR
        and columns["resting_hr_status"] is not RestingHrStatus.VALID
    ):
        return AdmissionRefusal.INVALID_VALUE
    if measure is NormalMeasure.HRV and value <= 0:
        return AdmissionRefusal.INVALID_VALUE
    if MEASURE_SPECS[measure].night:
        if columns["night_state"] is not NightState.COMPLETE:
            return AdmissionRefusal.NIGHT_NOT_COMPLETE
        if columns["night_short"] is True and measure not in SHORT_NIGHT_ADMITTED:
            return AdmissionRefusal.SHORT_NIGHT
        if columns["night_shifted"] is True:
            return AdmissionRefusal.SHIFTED_NIGHT
    types = columns["journal_types"]
    if JournalEventType.ILLNESS in types:
        return AdmissionRefusal.ILLNESS
    if JournalEventType.INJURY in types:
        return AdmissionRefusal.INJURY
    if exclude_altitude_stay and JournalEventType.ALTITUDE_STAY in types:
        return AdmissionRefusal.ALTITUDE_STAY
    return None


def _quantity(record: DayRecord | None, path: str) -> Any:
    """La grandeur ``path`` du document ; absente sans document ou sans sous-objet, et,
    de support ``day``, sur un jour qui n'est pas ``complete``."""
    if record is None:
        return None
    if QUANTITY_SUPPORTS[path] is Support.DAY and record.state is not DayState.COMPLETE:
        return None
    family, field = path.split(".")
    summary = getattr(record, family)
    return None if summary is None else getattr(summary, field)


def _stress_columns(record: DayRecord | None, min_fraction: float) -> dict[str, Any]:
    durations = [_quantity(record, path) for path in _STRESS_MEASURED_PATHS]
    measured = None if None in durations else float(sum(durations))
    valid: bool | None = None
    if (
        measured is not None
        and record is not None
        and record.window_start is not None
        and record.data_end is not None
    ):
        end = max(record.window_start + timedelta(days=1), record.data_end)
        window_s = (end - record.window_start).total_seconds()
        valid = measured >= min_fraction * window_s
    return {"stress_measured_s": measured, "stress_valid": valid}


def _document_columns(record: DayRecord | None) -> dict[str, Any]:
    """Ce que la ligne lit du document du jour, sans seuil."""
    versions = None if record is None else record.versions
    columns: dict[str, Any] = {
        "state": DayRowState.ABSENT
        if record is None
        else DayRowState(record.state.value),
        "window_start": None if record is None else record.window_start,
        "data_end": None if record is None else record.data_end,
        "reference_export": None if record is None else record.reference_export,
        "device_ranks": () if record is None else record.device_ranks,
        "body_battery_series_versions": ()
        if versions is None
        else versions.body_battery_series_versions,
        "readiness_entry_count": 0 if record is None else len(record.readiness),
    }
    for name in _VERSION_FIELDS:
        columns[name] = None if versions is None else getattr(versions, name)
    for column, path in _DAY_VALUES:
        columns[column] = _quantity(record, path)
    night = None if record is None else record.night
    columns["night_start"] = None if night is None else night.start
    columns["night_end"] = None if night is None else night.end
    for column, field in _NIGHT_FIELDS:
        columns[column] = None if night is None else getattr(night, field)
    naps = () if record is None else record.naps
    columns["nap_count"] = len(naps)
    columns["nap_window_s"] = float(
        sum((nap.end - nap.start).total_seconds() for nap in naps)
    )
    columns["nap_sleep_s"] = float(sum(nap.sleep_s for nap in naps))
    columns["naps_overlapping_night"] = (
        0
        if night is None
        else sum(1 for nap in naps if nap.start < night.end and nap.end > night.start)
    )
    return columns


def _view_columns(
    day: date,
    record: DayRecord | None,
    slices: DaySlices,
    views: ParameterSet,
    usual_window_days: int,
    usual_min_nights: int,
) -> dict[str, Any]:
    """Ce que les vues des jours disent du jour, sur leurs tranches."""
    assessment = night_assessment(
        slices.night,
        day,
        max_unmeasured_fraction=views["max_unmeasured_fraction"],
        short_sleep_s=views["short_sleep_s"],
        shift_s=views["shift_s"],
        usual_window_days=usual_window_days,
        usual_min_nights=usual_min_nights,
    )
    resting = resting_hr_on(
        slices.own, day, min_sleep_s=views["resting_hr_min_sleep_s"]
    )
    waking = readiness_on_waking(
        slices.own, day, tolerance_s=views["readiness_tolerance_s"]
    )
    entry = waking.entry
    columns: dict[str, Any] = {
        "night_state": assessment.state,
        "night_short": assessment.short,
        "night_short_absence": assessment.short_absence,
        "night_shifted": assessment.shifted,
        "night_shifted_absence": assessment.shifted_absence,
        "measured_sleep_s": assessment.measured_sleep_s,
        "unmeasured_fraction": assessment.unmeasured_fraction,
        "resting_hr_bpm": resting.resting_hr_bpm,
        "resting_hr_status": resting.status,
        "readiness_score": None if entry is None else entry.score,
        "readiness_level": None if entry is None else entry.level,
        "readiness_instant": None if entry is None else entry.instant,
        "readiness_absence": waking.absence,
    }
    night = None if record is None else record.night
    if night is None:
        columns["night_body_battery_ceiling"] = None
        columns["night_body_battery_coverage"] = None
        columns["night_body_battery_absence"] = ViewAbsence.NO_NIGHT
        return columns
    window = series_between(
        slices.series,
        SeriesKind.NIGHT_BODY_BATTERY,
        night.start,
        night.end,
        step_s=views["night_body_battery_step_s"],
        min_coverage_fraction=views["min_coverage_fraction"],
    )
    usable = window.absence is None
    columns["night_body_battery_ceiling"] = (
        any(point.value == BODY_BATTERY_CEILING for point in window.points)
        if usable
        else None
    )
    columns["night_body_battery_coverage"] = (
        window.coverage_fraction if usable else None
    )
    columns["night_body_battery_absence"] = window.absence
    return columns


def _status_blocks(
    history: TrainingStatusHistory, first: date | None, last: date | None
) -> tuple[dict[date, dict[str, Any]], int]:
    """Les colonnes de Training Status par jour de l'étendue, et le compte des blocs
    hors d'elle."""
    by_day: dict[date, dict[str, Any]] = {}
    outside = 0
    for suite, instant, fields in _TRAINING_STATUS:
        for block in getattr(history, suite):
            if first is None or last is None or not first <= block.day <= last:
                outside += 1
                continue
            columns = by_day.setdefault(block.day, {})
            columns[instant] = block.proper_instant
            for column, field in fields:
                columns[column] = getattr(block, field)
    return by_day, outside


def _empty_status() -> dict[str, Any]:
    columns: dict[str, Any] = {}
    for _, instant, fields in _TRAINING_STATUS:
        columns[instant] = None
        for column, _ in fields:
            columns[column] = None
    return columns


def _normal_columns(measure: NormalMeasure, normal: MeasureNormal) -> dict[str, Any]:
    prefix, unit = measure.value, _UNITS[measure]
    columns: dict[str, Any] = {
        f"{prefix}_normal{unit}": normal.normal,
        f"{prefix}_range_low{unit}": normal.range_low,
        f"{prefix}_range_high{unit}": normal.range_high,
        f"{prefix}_admitted_days": normal.admitted_days,
        f"{prefix}_normal_absence": normal.absence,
        f"{prefix}_segment": normal.segment,
        f"{prefix}_rupture": normal.rupture,
        f"{prefix}_normal_straddles": normal.straddles,
    }
    if measure is NormalMeasure.HRV:
        columns["hrv_log_median"] = normal.log_median
        columns["hrv_log_dispersion"] = normal.log_dispersion
    else:
        columns[f"{prefix}_dispersion{unit}"] = normal.dispersion
    return columns


def _add_normals(table: Sequence[dict[str, Any]], normals: ParameterSet) -> None:
    """Pose sur chaque ligne les jours incertains et, mesure par mesure, les normales,
    sur les suites de toute la table."""
    ranks = [columns["device_ranks"] for columns in table]
    for columns, uncertain in zip(table, uncertain_days(ranks), strict=True):
        columns["uncertain_device"] = uncertain
    for measure in NormalMeasure:
        spec = MEASURE_SPECS[measure]
        versions = (
            None
            if spec.version is None
            else [columns[spec.version] for columns in table]
        )
        results = measure_normals(
            measure,
            [columns[VALUE_COLUMNS[measure]] for columns in table],
            [columns[f"{measure.value}_admitted"] for columns in table],
            ranks,
            versions,
            normals,
        )
        for columns, normal in zip(table, results, strict=True):
            columns.update(_normal_columns(measure, normal))


def day_rows(
    days: Sequence[DayRecord],
    history: TrainingStatusHistory,
    index: ActivityIndex,
    journal: Journal,
    definition: DayDefinition = DEFAULT_DAY_DEFINITION,
) -> DayTable:
    """La table ``jours`` des documents ``days`` (``read_days`` : triés par jour, sans
    doublon, sinon ``ValueError``), de Training Status ``history``, des entrées de
    l'index ``index`` et du journal ``journal``, sous les paramètres ``definition``.

    Une ligne par jour de ``[premier document, dernier document]``, bornes comprises,
    triées ; un jour sans document, une ligne ``absent`` ; sans document, aucune ligne.
    Chaque vue reçoit sa tranche (module) ; les validités, l'admission et les normales
    sont celles du module.

    - **Training Status** : chaque bloc va à la ligne de son ``day`` ; l'instant d'une
      sorte est le ``proper_instant`` du bloc (absent s'il n'en a pas) ; un bloc d'un
      jour hors de l'étendue n'a pas de ligne et se compte (``blocks_outside_days``) ;
      le contrat de ``TrainingStatusHistory`` donne au plus un bloc par sorte et par
      date.
    - **L'activité du jour** : le jour d'une entrée est la date locale de son
      ``start_time`` ; une entrée d'avant le premier jour ou d'après le dernier n'a pas
      de ligne et se compte ; les entrées se groupent par jour une seule fois
      (:func:`activity_columns`) ; ``activity_columns`` est appelée pour chaque jour du
      calendrier, une ligne ``absent`` comprise, avec les entrées du jour (une suite
      vide
      pour un jour sans activité), et ses colonnes vont telles quelles dans la ligne.
    - **Le journal** : ``journal_types_by_day`` sur les bornes de la table.
    - **Les normales** : ``measure_normals`` par mesure, sur toute la table ;
      ``uncertain_device`` vient d'``uncertain_days`` sur les rangs de toute la table.

    Une ligne qui viole le contrat de ``DayRow`` lève ``ContractError``, qui nomme son
    jour.
    """
    documents = tuple(days)
    for i in range(1, len(documents)):
        if not documents[i - 1].day < documents[i].day:
            raise ValueError(
                "day_rows : days doit être trié par jour, sans doublon : rangs "
                f"{i - 1} et {i}."
            )
    usual_window_days = integer_parameter(definition.views, "usual_window_days")
    usual_min_nights = integer_parameter(definition.views, "usual_min_nights")
    exclude_altitude_stay = (
        integer_parameter(definition.normals, "exclude_altitude_stay") == 1
    )
    if not documents:
        _, outside = _status_blocks(history, None, None)
        return DayTable((), DaySummary(len(index.entries), 0, outside, 0, 0, 0))
    first, last = documents[0].day, documents[-1].day
    keys = tuple(record.day for record in documents)
    records = dict(zip(keys, documents, strict=True))
    status, outside = _status_blocks(history, first, last)
    types = journal_types_by_day(journal, first, last)
    entries: dict[date, list[IndexedActivity]] = {}
    before, after = 0, 0
    for entry in index.entries:
        day = entry.start_time.date()
        if day < first:
            before += 1
        elif day > last:
            after += 1
        else:
            entries.setdefault(day, []).append(entry)
    table: list[dict[str, Any]] = []
    for ordinal in range(first.toordinal(), last.toordinal() + 1):
        day = date.fromordinal(ordinal)
        record = records.get(day)
        slices = day_slices(documents, keys, day, usual_window_days)
        columns: dict[str, Any] = {"day": day, **_document_columns(record)}
        columns.update(
            _view_columns(
                day,
                record,
                slices,
                definition.views,
                usual_window_days,
                usual_min_nights,
            )
        )
        columns.update(_stress_columns(record, definition.views["stress_min_fraction"]))
        columns.update(_empty_status())
        columns.update(status.get(day, {}))
        columns["journal_types"] = types.get(day, ())
        columns.update(activity_columns(entries.get(day, ())))
        for measure in NormalMeasure:
            refusal = admission_refusal(
                measure, columns, exclude_altitude_stay=exclude_altitude_stay
            )
            columns[f"{measure.value}_refusal"] = refusal
            columns[f"{measure.value}_admitted"] = refusal is None
        table.append(columns)
    _add_normals(table, definition.normals)
    rows: list[DayRow] = []
    for columns in table:
        try:
            rows.append(DayRow(**columns))
        except ContractError as error:
            raise ContractError(
                f"jour {columns['day'].isoformat()} : {error}"
            ) from error
    absences = [columns["night_body_battery_absence"] for columns in table]
    summary = DaySummary(
        activities_before_first_day=before,
        activities_after_last_day=after,
        blocks_outside_days=outside,
        nights_below_body_battery_coverage=absences.count(ViewAbsence.BELOW_COVERAGE),
        nights_without_body_battery_point=absences.count(ViewAbsence.NO_POINT),
        absent_days=sum(
            1 for columns in table if columns["state"] is DayRowState.ABSENT
        ),
    )
    return DayTable(tuple(rows), summary)
