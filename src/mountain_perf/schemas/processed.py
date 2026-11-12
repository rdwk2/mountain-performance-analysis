"""Contrats de ``processed/`` (AN1-2b, AN1-2c et AN2-2, ``docs/decisions/0014``) :
les tables ``activites``, ``montees``, ``variantes`` et ``jours`` de la piste analyse,
et leur provenance.

Une ligne de table est un contrat : ses champs, leurs unités et leurs invariants sont
ici, et le dictionnaire de données les publie. Les tables s'écrivent en Parquet par
``mountain_perf.analyse.parquet`` (extra ``analyse``) ; elles se régénèrent en entier
depuis ``interim/`` et ``journal.csv``, et se relisent sans rien recalculer.

Les champs ``*_by_convention`` ont une valeur par convention de ``CLOCK_CONVENTIONS``
(``0010`` D5.2), dans son ordre ; la convention centrale θc est à l'indice
``CENTRAL_CONVENTION_INDEX`` de ``schemas/clock.py``.
"""

from __future__ import annotations

import dataclasses
import math
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from enum import StrEnum
from types import MappingProxyType
from typing import Any

from mountain_perf.schemas.clock import CLOCK_CONVENTIONS
from mountain_perf.schemas.common import UTC_OFFSET_RANGE_S, Sport
from mountain_perf.schemas.days import NightState, RestingHrStatus, ViewAbsence
from mountain_perf.schemas.interim import (
    TEMPERATURE_RANGE_C,
    ViewRefusal,
    require_activity_ref,
    require_export_name,
)
from mountain_perf.validation import (
    ContractError,
    require_aware,
    require_finite,
    require_in_range,
    require_increasing,
    require_non_empty,
)


class ClimbFlag(StrEnum):
    """Un drapeau de montée : il marque, il ne retire pas.

    Champs
    ------
    Valeurs décrites dans ``CLIMB_FLAG_DESCRIPTIONS``.

    Invariants
    ----------
    Énumération fermée.

    Producteur
    ----------
    ``mountain_perf.analyse.quality``.

    Consommateurs
    -------------
    La table ``montees`` ; la figure de Q1 (AN1-2c), qui écarte de sa vue principale
    les montées marquées et le dit par motif.

    Non promis
    ----------
    Une montée sans drapeau n'est pas pour autant juste : les drapeaux attrapent des
    défauts connus, pas tous.
    """

    GAIN_OUTSIDE_MOVING = "gain_outside_moving"
    SLOW_MOVING = "slow_moving"
    NON_HUMAN = "non_human"
    SPIKE = "spike"
    UNRESOLVED_GRADE = "unresolved_grade"
    NON_BAROMETRIC = "non_barometric"
    ALTIMETRIC_DRIFT = "altimetric_drift"


CLIMB_FLAG_DESCRIPTIONS: Mapping[ClimbFlag, str] = MappingProxyType(
    {
        ClimbFlag.GAIN_OUTSIDE_MOVING: (
            "Une part du gain au-delà du seuil est prise hors de M (arrêt, trou,"
            " transition) : la VAM principale ne la voit pas."
        ),
        ClimbFlag.SLOW_MOVING: (
            "Le temps passé en M sans gain, lentement, dépasse le seuil : une"
            " transition ou un GPS qui erre."
        ),
        ClimbFlag.NON_HUMAN: (
            "VAM ou vitesse horizontale hors de toute échelle humaine : remontée"
            " mécanique, véhicule."
        ),
        ClimbFlag.SPIKE: "Un saut d'altitude brute entre deux enregistrements.",
        ClimbFlag.UNRESOLVED_GRADE: (
            "Pente non lue (strate « non résolue ») : sinuosité au-delà du seuil"
            " (lacets serrés, section verticale), ou pente en M jusqu'à la pente"
            " minimale (une part du gain est prise hors de M)."
        ),
        ClimbFlag.NON_BAROMETRIC: "Altitude sans baromètre attesté.",
        ClimbFlag.ALTIMETRIC_DRIFT: (
            "L'activité est une boucle dont la fermeture altimétrique dépasse le"
            " seuil : dérive de la pression."
        ),
    }
)


class ClimbRegime(StrEnum):
    """Le régime d'une montée, lu sur son gain ``G`` et son sport, jamais sur sa
    durée.

    Champs
    ------
    Valeurs décrites dans ``CLIMB_REGIME_DESCRIPTIONS``.

    Invariants
    ----------
    Énumération fermée.

    Producteur
    ----------
    ``mountain_perf.analyse.quality``, avec ``V_ref`` déclarée (``athlete.toml``).

    Consommateurs
    -------------
    La table ``montees`` ; les panneaux de la figure de Q1 (AN1-2c).

    Non promis
    ----------
    Les frontières dépendent de ``V_ref`` : changer sa déclaration change les régimes,
    et c'est voulu (elle se fige par version).
    """

    SHORT_CLIMB = "short_climb"
    INTERMEDIATE = "intermediate"
    LONG_CLIMB = "long_climb"
    SKI_TOURING = "ski_touring"
    SHORT_SKI_TOURING = "short_ski_touring"
    OTHER_SPORT = "other_sport"


CLIMB_REGIME_DESCRIPTIONS: Mapping[ClimbRegime, str] = MappingProxyType(
    {
        ClimbRegime.SHORT_CLIMB: "À pied, gain jusqu'à V_ref fois 5 min : une côte.",
        ClimbRegime.INTERMEDIATE: "À pied, entre les côtes et les montées longues.",
        ClimbRegime.LONG_CLIMB: "À pied, gain d'au moins V_ref fois 15 min.",
        ClimbRegime.SKI_TOURING: "Ski de randonnée, gain au-delà de V_ref fois 5 min.",
        ClimbRegime.SHORT_SKI_TOURING: (
            "Ski de randonnée, gain jusqu'à V_ref fois 5 min."
        ),
        ClimbRegime.OTHER_SPORT: "Tout autre sport, ou un type sans famille.",
    }
)


class GradeStratum(StrEnum):
    """La strate de pente d'une montée, ``G_M,θc / L_M``.

    Champs
    ------
    Valeurs décrites dans ``GRADE_STRATUM_DESCRIPTIONS``.

    Invariants
    ----------
    Énumération fermée.

    Producteur
    ----------
    ``mountain_perf.analyse.quality``.

    Consommateurs
    -------------
    La table ``montees`` ; les facettes de la figure de Q1 (AN1-2c).

    Non promis
    ----------
    Aucun ajustement ni inférence : une strate compare des montées semblables.
    """

    MODERATE = "moderate"
    STEEP = "steep"
    VERY_STEEP = "very_steep"
    UNRESOLVED = "unresolved"


GRADE_STRATUM_DESCRIPTIONS: Mapping[GradeStratum, str] = MappingProxyType(
    {
        GradeStratum.MODERATE: "De la pente minimale à 15 %.",
        GradeStratum.STEEP: "De 15 à 30 %.",
        GradeStratum.VERY_STEEP: "Au-delà de 30 %.",
        GradeStratum.UNRESOLVED: (
            "Pente non lue : sinuosité au-delà du seuil, ou pente en M jusqu'à la"
            " pente minimale (une part du gain est prise hors de M) ; la montée porte"
            " le drapeau unresolved_grade."
        ),
    }
)


class AltitudeStratum(StrEnum):
    """La strate d'altitude d'une montée, sur son altitude moyenne en M.

    Champs
    ------
    Valeurs décrites dans ``ALTITUDE_STRATUM_DESCRIPTIONS``.

    Invariants
    ----------
    Énumération fermée.

    Producteur
    ----------
    ``mountain_perf.analyse.quality``.

    Consommateurs
    -------------
    La table ``montees`` ; la couleur des points de la figure de Q1 (AN1-2c).

    Non promis
    ----------
    L'altitude est celle de la montre : un baromètre qui dérive la déplace.
    """

    LOW = "low"
    MID = "mid"
    HIGH = "high"


ALTITUDE_STRATUM_DESCRIPTIONS: Mapping[AltitudeStratum, str] = MappingProxyType(
    {
        AltitudeStratum.LOW: "Sous 1 500 m.",
        AltitudeStratum.MID: "De 1 500 à 2 500 m.",
        AltitudeStratum.HIGH: "Au-delà de 2 500 m.",
    }
)


class DayRowState(StrEnum):
    """L'état d'une ligne de la table ``jours`` (AN2-2) : ``absent`` pour un jour de
    l'étendue sans document, sinon l'état du document du jour (``DayState``).

    Champs
    ------
    Valeurs décrites dans ``DAY_ROW_STATE_DESCRIPTIONS`` (entre guillemets, le terme
    de l'athlète).

    Invariants
    ----------
    Énumération fermée, ordonnée : ``absent``, puis les quatre états de ``DayState``
    dans leur ordre (``empty``, ``no_measurement``, ``truncated``, ``complete``),
    de mêmes valeurs.

    Producteur
    ----------
    La table ``jours`` (``mountain_perf.analyse.days``, AN2-2) : ``absent``, ou l'état
    écrit dans le document du jour.

    Consommateurs
    -------------
    ``DayRow.state`` ; la page « récupération » (AN2-3), qui en tire ses manques.

    Non promis
    ----------
    ``absent`` n'existe que dans ``jours`` : ``interim/days/`` n'a pas de document
    pour ce jour, et n'en écrit jamais d'``absent``.
    """

    ABSENT = "absent"
    EMPTY = "empty"
    NO_MEASUREMENT = "no_measurement"
    TRUNCATED = "truncated"
    COMPLETE = "complete"


DAY_ROW_STATE_DESCRIPTIONS: Mapping[DayRowState, str] = MappingProxyType(
    {
        DayRowState.ABSENT: (
            "« absent » : un jour du calendrier, entre le premier et le dernier "
            "document d'interim/days/, sans document."
        ),
        DayRowState.EMPTY: (
            "« vide » : aucune famille ne porte de fenêtre du jour (la fenêtre de "
            "la nuit de sleep n'en est pas une)."
        ),
        DayRowState.NO_MEASUREMENT: (
            "« sans_mesure » : l'indicateur de présence de daily_summary est faux "
            "; ou, sans indicateur, aucun échantillon mesuré dans les séries du "
            "jour et pas de nuit."
        ),
        DayRowState.TRUNCATED: (
            "« tronqué » : fin_donnees précède début + 24 h (jour pris en cours de "
            "journée, montre non synchronisée, ou montre arrêtée)."
        ),
        DayRowState.COMPLETE: ("« complet » : aucun des cas précédents."),
    }
)


class JournalEventType(StrEnum):
    """Le type d'un événement de ``journal.csv``, tenu à la main par l'athlète
    (charte, § 3) : les valeurs sont celles **du fichier**.

    Champs
    ------
    Valeurs décrites dans ``JOURNAL_EVENT_TYPE_DESCRIPTIONS``.

    Invariants
    ----------
    Énumération fermée : les huit types de la charte, § 3.

    Producteur
    ----------
    La lecture du journal (``mountain_perf.analyse.journal``, AN2-2).

    Consommateurs
    -------------
    ``DayRow.journal_types`` ; l'admission dans les normales de ``jours`` (``maladie``,
    ``blessure``, ``sejour_altitude``) ; les plans des questions, qui disent quels types
    ils excluent ou contrôlent.

    Non promis
    ----------
    Le journal ne dit que ce que l'athlète y écrit : un jour sans événement n'est pas
    un jour sans maladie. La note d'un événement n'est jamais gardée.
    """

    ILLNESS = "maladie"
    INJURY = "blessure"
    RACE = "course"
    TRAVEL = "deplacement"
    MOVE = "demenagement"
    ALTITUDE_STAY = "sejour_altitude"
    BENCHMARK = "etalon"
    OTHER = "autre"


JOURNAL_EVENT_TYPE_DESCRIPTIONS: Mapping[JournalEventType, str] = MappingProxyType(
    {
        JournalEventType.ILLNESS: (
            "« maladie » : les jours couverts n'entrent dans aucune normale de jours."
        ),
        JournalEventType.INJURY: (
            "« blessure » : les jours couverts n'entrent dans aucune normale de jours."
        ),
        JournalEventType.RACE: (
            "« course » : une compétition ; marquée, rien d'exclu."
        ),
        JournalEventType.TRAVEL: (
            "« deplacement » : une absence temporaire ; marquée, rien d'exclu."
        ),
        JournalEventType.MOVE: (
            "« demenagement » : un changement durable de lieu de vie, donc de "
            "terrain ; marqué, rien d'exclu."
        ),
        JournalEventType.ALTITUDE_STAY: (
            "« sejour_altitude » : un séjour en altitude ; exclu des normales de "
            "jours par défaut (paramètre déclaré normal.exclude_altitude_stay)."
        ),
        JournalEventType.BENCHMARK: (
            "« etalon » : un passage d'un parcours étalon que l'appariement ne "
            "reconnaît pas ; marqué, rien d'exclu."
        ),
        JournalEventType.OTHER: (
            "« autre » : tout autre événement ; marqué, rien d'exclu."
        ),
    }
)


class NormalAbsence(StrEnum):
    """Pourquoi la normale d'une mesure manque à une ligne de ``jours``.

    Champs
    ------
    Valeurs décrites dans ``NORMAL_ABSENCE_DESCRIPTIONS``.

    Invariants
    ----------
    Énumération fermée : une normale absente porte un seul motif.

    Producteur
    ----------
    Les normales (``mountain_perf.analyse.normals``, AN2-2).

    Consommateurs
    -------------
    ``DayRow.<mesure>_normal_absence`` ; la page « récupération » (AN2-3), qui coupe la
    normale et sa plage où elle manque.

    Non promis
    ----------
    Le motif ne dit pas pourquoi les jours de la fenêtre ne sont pas admis : chaque
    ligne porte son propre motif de refus (``AdmissionRefusal``).
    """

    NO_ADMITTED_DAY = "no_admitted_day"
    TOO_FEW_ADMITTED_DAYS = "too_few_admitted_days"


NORMAL_ABSENCE_DESCRIPTIONS: Mapping[NormalAbsence, str] = MappingProxyType(
    {
        NormalAbsence.NO_ADMITTED_DAY: (
            "Aucun jour admis dans la fenêtre (au début de la table, ou après une "
            "longue suite de jours non admis)."
        ),
        NormalAbsence.TOO_FEW_ADMITTED_DAYS: (
            "Au moins un jour admis dans la fenêtre, moins que le minimum déclaré "
            "(normal.min_admitted_days)."
        ),
    }
)


class AdmissionRefusal(StrEnum):
    """Pourquoi la valeur d'une mesure d'un jour n'entre pas dans les normales,
    décidé **dans l'ordre des membres** : le premier qui s'applique.

    Champs
    ------
    Valeurs décrites dans ``ADMISSION_REFUSAL_DESCRIPTIONS``.

    Invariants
    ----------
    Énumération fermée, ordonnée : ``absent_row``, ``no_value``, ``invalid_value``,
    ``night_not_complete``, ``short_night``, ``shifted_night``, ``illness``,
    ``injury``, ``altitude_stay``.

    Producteur
    ----------
    L'admission de la table ``jours`` (``mountain_perf.analyse.days``, AN2-2).

    Consommateurs
    -------------
    ``DayRow.<mesure>_refusal`` ; la page « récupération » (AN2-3), qui en tire ses
    marques pleines, creuses et grises sans refaire la règle.

    Non promis
    ----------
    Un seul motif par mesure et par jour, le premier : une ligne qui en viole deux ne
    porte pas le second. Une valeur non admise reste dans sa colonne.
    """

    ABSENT_ROW = "absent_row"
    NO_VALUE = "no_value"
    INVALID_VALUE = "invalid_value"
    NIGHT_NOT_COMPLETE = "night_not_complete"
    SHORT_NIGHT = "short_night"
    SHIFTED_NIGHT = "shifted_night"
    ILLNESS = "illness"
    INJURY = "injury"
    ALTITUDE_STAY = "altitude_stay"


ADMISSION_REFUSAL_DESCRIPTIONS: Mapping[AdmissionRefusal, str] = MappingProxyType(
    {
        AdmissionRefusal.ABSENT_ROW: ("La ligne est absent (aucun document ce jour)."),
        AdmissionRefusal.NO_VALUE: ("La valeur de la mesure manque ce jour."),
        AdmissionRefusal.INVALID_VALUE: (
            "La valeur n'est pas valide pour la mesure : FC de repos d'un statut "
            "autre que valid, ou HRV <= 0 (sans logarithme)."
        ),
        AdmissionRefusal.NIGHT_NOT_COMPLETE: (
            "Mesure de nuit : l'état de la nuit n'est pas complete."
        ),
        AdmissionRefusal.SHORT_NIGHT: (
            "Mesure de nuit : la nuit porte le drapeau short (sauf pour le sommeil "
            "mesuré, où une nuit courte est admise)."
        ),
        AdmissionRefusal.SHIFTED_NIGHT: (
            "Mesure de nuit : la nuit porte le drapeau shifted (un drapeau inconnu "
            "n'exclut pas)."
        ),
        AdmissionRefusal.ILLNESS: ("Le journal couvre le jour d'une maladie."),
        AdmissionRefusal.INJURY: ("Le journal couvre le jour d'une blessure."),
        AdmissionRefusal.ALTITUDE_STAY: (
            "Le journal couvre le jour d'un séjour en altitude, exclu par le "
            "paramètre déclaré normal.exclude_altitude_stay."
        ),
    }
)

_N = len(CLOCK_CONVENTIONS)


def _check_numbers(row: object, fields: tuple[dataclasses.Field[Any], ...]) -> None:
    """Chaque nombre d'une ligne est fini ; chaque liste par convention a une valeur
    par convention, finie."""
    for field in fields:
        value = getattr(row, field.name)
        if isinstance(value, bool) or value is None:
            continue
        if isinstance(value, float | int):
            require_finite(float(value), field.name)
        elif field.name.endswith("_by_convention"):
            if not isinstance(value, tuple) or len(value) != _N:
                raise ContractError(f"{field.name} doit avoir {_N} valeurs.")
            for item in value:
                require_finite(float(item), field.name)


_LAGGED_HEART_RATES = (
    "lagged_moving_heart_rate",
    "unlagged_moving_heart_rate",
    "lagged_second_half_heart_rate",
    "lagged_elapsed_heart_rate",
)
"""Les préfixes des quatre paires de la FC décalée de ``ClimbRow`` (AN3-1a)."""


def _check_fraction(value: float | None, name: str) -> None:
    if value is not None:
        require_in_range(value, 0.0, 1.0, name)


def _check_non_negative(row: object, *names: str) -> None:
    for name in names:
        value = getattr(row, name)
        if value is None:
            continue
        values = value if isinstance(value, tuple) else (value,)
        for item in values:
            if item < 0:
                raise ContractError(f"{name} doit être >= 0, reçu {item}.")


def _local(value: datetime, name: str) -> datetime:
    offset = require_aware(value, name)
    require_in_range(offset.total_seconds(), *UTC_OFFSET_RANGE_S, f"décalage de {name}")
    return value.astimezone(timezone(offset))


@dataclass(frozen=True)
class ClimbRow:
    """Une ligne de la table ``montees`` : une montée retenue d'une activité.

    Champs
    ------
    Identité et contexte :

    - ``activity_ref`` — sans unité — l'activité (index d'``interim/``).
    - ``start_offset_s``, ``end_offset_s`` — secondes — bornes en temps ``t_a*`` et
      ``t_b*``, depuis le départ de l'enregistrement ; la clé de la table est
      ``(activity_ref, start_offset_s)``.
    - ``rank`` — sans unité — rang de la montée dans l'activité, depuis 1 (change avec
      la définition : ce n'est pas un identifiant).
    - ``source_activity_type`` — sans unité — type de la source.
    - ``sport`` — sans unité — famille de la table des types, si le type en a une.
    - ``local_start_time`` — instant — départ de la montée, au décalage local de
      l'activité (index).
    - ``device_manufacturer``, ``device_product``, ``software_version`` — sans unité —
      l'appareil qui a écrit le FIT, si le fichier le dit.
    - ``barometric`` — sans unité — l'altitude vient d'un baromètre attesté (par le
      fichier, sinon par ``athlete.toml``).

    Profil (diagnostic, jamais au numérateur de la VAM) :

    - ``profile_start_m``, ``profile_end_m`` — mètres — abscisses des bornes sur le
      profil du moteur.
    - ``profile_gain_m``, ``raw_profile_gain_m`` — mètres — gain entre ces abscisses,
      sur le profil lissé et sur la grille non lissée.
    - ``profile_ascent_m`` — mètres — D+ cumulé du profil lissé entre ces abscisses.

    Gain et temps (bornes en temps, sur ``z̃`` de ``0010`` D4.4) :

    - ``gain_m`` — mètres — ``G``, le maximum moins le minimum de ``z̃`` près des
      bornes.
    - ``moving_gain_m_by_convention``, ``stopped_gain_m_by_convention``,
      ``undetermined_gain_m_by_convention`` — mètres — l'horloge du gain : variation
      de ``z̃`` sur les intervalles M, S et U de chaque convention.
    - ``gap_gain_m`` — mètres — variation de ``z̃`` sur les intervalles de trou.
    - ``elapsed_s`` — secondes — ``t_b* − t_a*``.
    - ``moving_s_by_convention``, ``stopped_s_by_convention``,
      ``undetermined_s_by_convention`` — secondes — temps M, S et U.
    - ``slow_moving_s`` — secondes — temps M (θc) lent : les intervalles M dont la
      fenêtre de ``0010`` D5 a une vitesse verticale et une vitesse horizontale au
      plus les seuils ``slow_max_*`` de la montée.

    VAM (m/s ; « VAM » est l'étiquette d'affichage) :

    - ``vertical_speed_ms`` — m/s — VAM principale, ``G_M,θc / M_θc``.
    - ``moving_or_undetermined_vertical_speed_ms`` — m/s — variante
      ``(G_M + G_U) / (M + U)`` sous θc.
    - ``vertical_speed_low_ms``, ``vertical_speed_high_ms`` — m/s — enveloppe : la
      plus petite et la plus grande des deux formes sur les cinq conventions.

    Géométrie :

    - ``moving_distance_m`` — mètres — ``L_M``, longueur parcourue en M (θc).
    - ``grade`` — sans unité — ``G_M,θc / L_M``, gain et longueur des mêmes
      intervalles M.
    - ``net_displacement_m`` — mètres — déplacement horizontal net entre les bornes.
    - ``sinuosity`` — sans unité — ``L_M`` divisée par le déplacement net, si celui-ci
      est positif.
    - ``low_elevation_m``, ``high_elevation_m`` — mètres — ``z̃`` la plus basse et la
      plus haute de la montée.
    - ``moving_mean_elevation_m`` — mètres — ``z̃`` moyenne en M (θc), pondérée par le
      temps.

    Qualité :

    - ``step_s``, ``longest_step_s`` — secondes — pas médian et plus long intervalle
      dans la montée.
    - ``gap_count``, ``gap_s`` — sans unité, secondes — trous (``0010`` D4.4) dans la
      montée, et leur durée.
    - ``timer_stop_count``, ``auto_pause_count`` — sans unité — arrêts du chronomètre
      dans la montée, dont ceux de la pause automatique.
    - ``max_vertical_rate_ms`` — m/s — plus grande variation d'altitude brute par
      seconde entre deux enregistrements.
    - ``outside_moving_gain_fraction`` — sans unité — part du gain de l'horloge prise
      hors de M (θc), ``(G_S + G_U) / (G_M + G_S + G_U)`` : un rapport signé, négatif
      quand l'altitude baisse pendant S ou U, absent si le dénominateur n'est pas
      positif.
    - ``slow_moving_fraction`` — sans unité — ``slow_moving_s / M_θc``.
    - ``flags`` — sans unité — les drapeaux, triés.
    - ``found_fraction``, ``max_relative_deviation``, ``stable`` — sans unité — la
      stabilité (variantes déclarées de la définition).
    - ``regime``, ``grade_stratum``, ``altitude_stratum`` — sans unité — régime et
      strates.

    Pour l'aval :

    - ``preceding_moving_s`` — secondes — temps M (θc) de l'activité avant la montée.
    - ``preceding_ascent_m``, ``preceding_descent_m`` — mètres — D+ et D− du profil de
      l'activité avant la montée.
    - ``moving_mean_heart_rate_bpm`` — battements par minute — FC moyenne sur les
      intervalles M (θc) de la montée qui ont une FC à leur instant de départ.
    - ``moving_heart_rate_coverage`` — sans unité — part du temps M (θc) couverte par
      ces intervalles.
    - ``second_half_mean_heart_rate_bpm`` — battements par minute — la même moyenne
      sur la seconde moitié du temps M.
    - ``external_heart_rate_sensor`` — sans unité — le fichier décrit un capteur de FC
      externe.
    - ``moving_mean_temperature_c`` — °C — température du capteur, moyenne de la même
      façon que la FC.

    La FC décalée (AN3-1a, ``0014``, précisions d'AN3-1a) : sur chaque morceau d'un
    support (temps de la trace), décalé, l'intégrale exacte de la FC interpolée et la
    durée couverte viennent de l'outil du moteur (``HeartRateSeries.integral``,
    ``0017`` P5.1), la fenêtre rognée à la série de FC ; la moyenne est l'intégrale
    sommée divisée par la durée couverte sommée, sans aucun seuil de couverture ; la
    couverture est la durée couverte sommée divisée par la durée du support, bornée
    à 1. Le décalage est ``HR_LAG_S`` (60 s, ``analyse/heart_rate.py``).

    - ``lagged_moving_heart_rate_bpm`` — battements par minute — FC moyenne des
      intervalles M (θc) de la montée, ceux de sa VAM, chacun décalé de ``HR_LAG_S`` ;
      absente sans durée couverte.
    - ``lagged_moving_heart_rate_coverage`` — fraction — part de ces intervalles que la
      FC couvre.
    - ``unlagged_moving_heart_rate_bpm`` — battements par minute — la même moyenne,
      sans décalage.
    - ``unlagged_moving_heart_rate_coverage`` — fraction — sa couverture.
    - ``lagged_second_half_heart_rate_bpm`` — battements par minute — la même moyenne
      sur la seconde moitié du temps M, décalée : l'intervalle qui contient le milieu
      du temps M est coupé exactement à cet instant.
    - ``lagged_second_half_heart_rate_coverage`` — fraction — sa couverture.
    - ``lagged_elapsed_heart_rate_bpm`` — battements par minute — FC moyenne de la
      fenêtre écoulée de la montée, de sa borne de départ à sa borne d'arrivée,
      décalée de ``HR_LAG_S``.
    - ``lagged_elapsed_heart_rate_coverage`` — fraction — sa couverture.

    Invariants
    ----------
    - ``activity_ref`` valide ; ``source_activity_type`` non vide ; ``rank >= 1`` ;
    - ``0 <= start_offset_s < end_offset_s`` ; ``elapsed_s`` égal à leur différence ;
    - ``local_start_time`` *aware*, ramené à un fuseau à décalage fixe ;
    - nombres finis ; listes par convention de cinq valeurs ;
    - positifs ou nuls : ``gain_m``, les abscisses et le D+ du profil, les distances,
      les durées, les pas, les comptes, le D+ et le D− qui précèdent ;
      ``moving_mean_temperature_c`` dans ``TEMPERATURE_RANGE_C`` ;
    - fractions dans ``[0, 1]``, sauf ``outside_moving_gain_fraction``, signée ;
      ``flags`` triés, sans doublon ;
    - les quatre couvertures de la FC décalée (``…_heart_rate_coverage`` d'AN3-1a)
      dans ``[0, 1]`` ; pour chacune des quatre paires, la FC est absente si et
      seulement si sa couverture vaut 0.

    Producteur
    ----------
    ``mountain_perf.analyse.tables``.

    Consommateurs
    -------------
    La figure de Q1 (AN1-2c) ; les questions de la piste qui lisent des montées.

    Non promis
    ----------
    - une VAM juste sans baromètre attesté (``barometric`` faux : le drapeau le dit) ;
    - la FC d'une côte de moins de deux minutes ;
    - une pente lue quand ``grade_stratum`` est « non résolue » ;
    - les descentes et les plats ; un identifiant de montée stable d'une version de la
      définition à l'autre ; que S soit un arrêt réel (le détecteur de ``0010`` n'est
      pas validé) ; la comparabilité entre montres ; une charge ;
    - la définition ne voit ni l'alpinisme, ni la via ferrata, ni l'escalade à
      l'échelle d'un ressaut.
    """

    activity_ref: str
    start_offset_s: float
    end_offset_s: float
    rank: int
    source_activity_type: str
    sport: Sport | None
    local_start_time: datetime
    device_manufacturer: str | None
    device_product: int | None
    software_version: float | None
    barometric: bool
    profile_start_m: float
    profile_end_m: float
    profile_gain_m: float
    raw_profile_gain_m: float
    profile_ascent_m: float
    gain_m: float
    moving_gain_m_by_convention: tuple[float, ...]
    stopped_gain_m_by_convention: tuple[float, ...]
    undetermined_gain_m_by_convention: tuple[float, ...]
    gap_gain_m: float
    elapsed_s: float
    moving_s_by_convention: tuple[float, ...]
    stopped_s_by_convention: tuple[float, ...]
    undetermined_s_by_convention: tuple[float, ...]
    slow_moving_s: float
    vertical_speed_ms: float | None
    moving_or_undetermined_vertical_speed_ms: float | None
    vertical_speed_low_ms: float | None
    vertical_speed_high_ms: float | None
    moving_distance_m: float
    grade: float
    net_displacement_m: float
    sinuosity: float | None
    low_elevation_m: float
    high_elevation_m: float
    moving_mean_elevation_m: float | None
    step_s: float
    longest_step_s: float
    gap_count: int
    gap_s: float
    timer_stop_count: int
    auto_pause_count: int
    max_vertical_rate_ms: float
    outside_moving_gain_fraction: float | None
    slow_moving_fraction: float | None
    flags: tuple[ClimbFlag, ...]
    found_fraction: float
    max_relative_deviation: float | None
    stable: bool | None
    regime: ClimbRegime
    grade_stratum: GradeStratum
    altitude_stratum: AltitudeStratum | None
    preceding_moving_s: float
    preceding_ascent_m: float
    preceding_descent_m: float
    moving_mean_heart_rate_bpm: float | None
    moving_heart_rate_coverage: float
    second_half_mean_heart_rate_bpm: float | None
    external_heart_rate_sensor: bool | None
    moving_mean_temperature_c: float | None
    lagged_moving_heart_rate_bpm: float | None
    lagged_moving_heart_rate_coverage: float
    unlagged_moving_heart_rate_bpm: float | None
    unlagged_moving_heart_rate_coverage: float
    lagged_second_half_heart_rate_bpm: float | None
    lagged_second_half_heart_rate_coverage: float
    lagged_elapsed_heart_rate_bpm: float | None
    lagged_elapsed_heart_rate_coverage: float

    def __post_init__(self) -> None:
        require_activity_ref(self.activity_ref)
        require_non_empty(self.source_activity_type, "source_activity_type")
        object.__setattr__(
            self, "local_start_time", _local(self.local_start_time, "local_start_time")
        )
        _check_numbers(self, dataclasses.fields(self))
        if self.rank < 1:
            raise ContractError(f"rank doit être >= 1, reçu {self.rank}.")
        if not 0 <= self.start_offset_s < self.end_offset_s:
            raise ContractError("Il faut 0 <= start_offset_s < end_offset_s.")
        if not math.isclose(
            self.elapsed_s, self.end_offset_s - self.start_offset_s, abs_tol=1e-6
        ):
            raise ContractError("elapsed_s doit valoir end_offset_s − start_offset_s.")
        _check_non_negative(
            self,
            "gain_m",
            "profile_start_m",
            "profile_end_m",
            "profile_ascent_m",
            "elapsed_s",
            "moving_s_by_convention",
            "stopped_s_by_convention",
            "undetermined_s_by_convention",
            "slow_moving_s",
            "moving_distance_m",
            "net_displacement_m",
            "step_s",
            "longest_step_s",
            "gap_count",
            "gap_s",
            "timer_stop_count",
            "auto_pause_count",
            "max_vertical_rate_ms",
            "preceding_moving_s",
            "preceding_ascent_m",
            "preceding_descent_m",
        )
        for name in (
            "slow_moving_fraction",
            "found_fraction",
            "moving_heart_rate_coverage",
        ):
            _check_fraction(getattr(self, name), name)
        for prefix in _LAGGED_HEART_RATES:
            bpm, coverage = f"{prefix}_bpm", f"{prefix}_coverage"
            _check_fraction(getattr(self, coverage), coverage)
            if (getattr(self, bpm) is None) != (getattr(self, coverage) == 0.0):
                raise ContractError(
                    f"{bpm} doit être absente si et seulement si {coverage} vaut 0."
                )
        if self.moving_mean_temperature_c is not None:
            require_in_range(
                self.moving_mean_temperature_c,
                *TEMPERATURE_RANGE_C,
                "moving_mean_temperature_c",
            )
        if list(self.flags) != sorted(set(self.flags)):
            raise ContractError("flags doit être trié, sans doublon.")


@dataclass(frozen=True)
class ClimbVariantRow:
    """Une ligne de la table ``variantes`` : une montée retenue sous une variante
    déclarée de la définition (``analyse/stability.py``), pour une activité qui a au
    moins une montée de référence.

    Champs
    ------
    - ``activity_ref`` — sans unité — l'activité (index d'``interim/``).
    - ``variant`` — sans unité — le nom de la variante, dans ``VARIANTS`` de
      ``mountain_perf.analyse.stability``.
    - ``start_offset_s``, ``end_offset_s`` — secondes — bornes en temps de la montée
      sous la variante, depuis le départ de l'enregistrement ; la clé de la table est
      ``(activity_ref, variant, start_offset_s)``.
    - ``gain_m`` — mètres — ``G`` sous la variante.
    - ``moving_gain_m``, ``moving_s`` — mètres, secondes — ``G_M,θc`` et ``M_θc`` sous
      la variante.
    - ``regime``, ``grade_stratum``, ``altitude_stratum`` — sans unité — régime et
      strates, sous les paramètres de la variante et la ``V_ref`` des tables.
    - ``flags`` — sans unité — les drapeaux sous les paramètres de la variante, triés.

    Invariants
    ----------
    - ``activity_ref`` valide ; ``variant`` non vide ;
    - ``0 <= start_offset_s < end_offset_s`` ; nombres finis ;
    - ``gain_m`` et ``moving_s`` positifs ou nuls ;
    - ``flags`` triés, sans doublon.

    Producteur
    ----------
    ``mountain_perf.analyse.tables``, depuis les montées que la stabilité des montées
    calcule déjà sous chaque variante.

    Consommateurs
    -------------
    La stabilité des points de la figure de Q1 (``mountain_perf.analyse.q1``).

    Non promis
    ----------
    - un identifiant de montée d'une variante à l'autre, ou d'une version de la
      définition à l'autre ;
    - les autres mesures d'une montée de variante (elles restent dans le calcul).
    """

    activity_ref: str
    variant: str
    start_offset_s: float
    end_offset_s: float
    gain_m: float
    moving_gain_m: float
    moving_s: float
    regime: ClimbRegime
    grade_stratum: GradeStratum
    altitude_stratum: AltitudeStratum | None
    flags: tuple[ClimbFlag, ...]

    def __post_init__(self) -> None:
        require_activity_ref(self.activity_ref)
        require_non_empty(self.variant, "variant")
        _check_numbers(self, dataclasses.fields(self))
        if not 0 <= self.start_offset_s < self.end_offset_s:
            raise ContractError("Il faut 0 <= start_offset_s < end_offset_s.")
        _check_non_negative(self, "gain_m", "moving_s")
        if list(self.flags) != sorted(set(self.flags)):
            raise ContractError("flags doit être trié, sans doublon.")


@dataclass(frozen=True)
class ActivityRow:
    """Une ligne de la table ``activites`` : une entrée de l'index d'``interim/``,
    de tout type.

    Champs
    ------
    De l'index (préfixe ``index_`` : valeurs de la source, jamais recalculées) :

    - ``activity_ref``, ``source_activity_type`` — sans unité — identifiant et type.
    - ``sport`` — sans unité — famille de la table des types, si le type en a une.
    - ``view_refusal`` — sans unité — pourquoi l'entrée n'a pas de vue ``Activity``,
      si elle n'en a pas.
    - ``start_time`` — instant — départ, au décalage local de la source.
    - ``index_elapsed_s``, ``index_moving_s`` — secondes ; ``index_distance_m``,
      ``index_ascent_m``, ``index_descent_m`` — mètres ;
      ``index_elevation_corrected`` — sans unité ; ``index_average_heart_rate_bpm``,
      ``index_max_heart_rate_bpm`` — battements par minute — si présents.
    - ``has_recording`` — sans unité — ``interim/`` porte l'enregistrement.

    De l'enregistrement (absents sans enregistrement) :

    - ``session_count`` — sans unité — sessions du FIT.
    - ``device_manufacturer``, ``device_product``, ``software_version`` — sans unité.
    - ``barometer`` — sans unité — ce que le fichier dit de son baromètre.
    - ``external_heart_rate_sensor`` — sans unité — capteur de FC externe décrit.
    - ``mean_temperature_c`` — °C — température moyenne du canal.
    - ``has_track`` — sans unité — l'enregistrement a une vue positions et altitude
      d'au moins deux instants.

    De la vue positions et altitude (absents sans vue) :

    - ``track_offset_s``, ``track_elapsed_s`` — secondes — premier instant de la vue
      et durée de la vue.
    - ``profile_distance_m``, ``profile_ascent_m``, ``profile_descent_m`` — mètres —
      longueur, D+ et D− du profil du moteur sur la vue.
    - ``moving_s_by_convention``, ``stopped_s_by_convention``,
      ``undetermined_s_by_convention`` — secondes — temps M, S et U de la vue.
    - ``step_s``, ``longest_step_s`` — secondes — pas médian et plus long intervalle.
    - ``gap_count``, ``gap_s`` — sans unité, secondes — trous de la vue.
    - ``timer_stop_count``, ``auto_pause_count`` — sans unité — arrêts du chronomètre,
      dont ceux de la pause automatique.
    - ``position_gap_ascent_m`` — mètres — D+ du canal d'altitude pendant les trous de
      la vue (la vue écarte cette altitude, le canal la garde).
    - ``loop`` — sans unité — l'arrivée est à moins du seuil du départ.
    - ``closure_elevation_m`` — mètres — ``z̃`` d'arrivée moins ``z̃`` de départ ;
      ``closure_rate_ms`` — m/s — sa valeur absolue par seconde de la vue ;
      ``altimetric_drift`` — sans unité — boucle au-delà du seuil.
    - ``barometric`` — sans unité — l'altitude vient-elle d'un baromètre : ce que le
      fichier dit, sinon ``athlete.toml``.
    - ``mean_heart_rate_bpm`` — battements par minute — FC moyenne du canal sur la
      vue ; ``heart_rate_coverage`` — sans unité — part des instants de la vue qui en
      ont une.

    Des montées :

    - ``climb_count`` et ``*_count`` par régime — sans unité — montées retenues ;
      ``flagged_climb_count``, ``unstable_climb_count`` — sans unité — celles qui
      portent un drapeau, celles que la stabilité dit instables.

    Invariants
    ----------
    - ``activity_ref`` valide ; ``source_activity_type`` non vide ;
    - ``start_time`` *aware*, ramené à un fuseau à décalage fixe ;
    - ``view_refusal`` présent si ``sport`` est absent (la vue ``Activity`` peut aussi
      être refusée pour un champ manquant quand le sport est connu) ;
    - sans enregistrement, aucun champ de l'enregistrement, et pas de vue ; sans vue
      positions et altitude, aucun champ de la vue, et aucune montée ;
    - nombres finis et positifs ou nuls, sauf ``closure_elevation_m`` et
      ``mean_temperature_c`` (dans ``TEMPERATURE_RANGE_C``) ; fractions dans
      ``[0, 1]`` ; la somme des comptes par régime égale ``climb_count`` ; les
      montées marquées et les instables n'excèdent pas ``climb_count``.

    Producteur
    ----------
    ``mountain_perf.analyse.tables``.

    Consommateurs
    -------------
    La figure de Q1 (AN1-2c, flux par mois) ; les questions de la piste (la charge
    recalculée viendra avec la question qui en a besoin, pas avec AN2).

    Non promis
    ----------
    - ``index_ascent_m`` ne se compare pas à ``profile_ascent_m``
      (``elevation_corrected``, lissage) ; aucune colonne ne mêle les deux ;
    - le temps en mouvement de l'index est celui de Garmin, pas celui de ``0010`` D5 ;
    - la FC moyenne n'est pas une charge.
    """

    activity_ref: str
    source_activity_type: str
    sport: Sport | None
    view_refusal: ViewRefusal | None
    start_time: datetime
    index_elapsed_s: float | None
    index_moving_s: float | None
    index_distance_m: float | None
    index_ascent_m: float | None
    index_descent_m: float | None
    index_elevation_corrected: bool | None
    index_average_heart_rate_bpm: float | None
    index_max_heart_rate_bpm: float | None
    has_recording: bool
    has_track: bool
    session_count: int | None
    track_offset_s: float | None
    track_elapsed_s: float | None
    profile_distance_m: float | None
    profile_ascent_m: float | None
    profile_descent_m: float | None
    moving_s_by_convention: tuple[float, ...] | None
    stopped_s_by_convention: tuple[float, ...] | None
    undetermined_s_by_convention: tuple[float, ...] | None
    step_s: float | None
    longest_step_s: float | None
    gap_count: int | None
    gap_s: float | None
    timer_stop_count: int | None
    auto_pause_count: int | None
    position_gap_ascent_m: float | None
    loop: bool | None
    closure_elevation_m: float | None
    closure_rate_ms: float | None
    altimetric_drift: bool | None
    device_manufacturer: str | None
    device_product: int | None
    software_version: float | None
    barometer: bool | None
    barometric: bool | None
    external_heart_rate_sensor: bool | None
    mean_heart_rate_bpm: float | None
    heart_rate_coverage: float | None
    mean_temperature_c: float | None
    climb_count: int
    short_climb_count: int
    intermediate_count: int
    long_climb_count: int
    ski_touring_count: int
    short_ski_touring_count: int
    other_sport_count: int
    flagged_climb_count: int
    unstable_climb_count: int

    def __post_init__(self) -> None:
        require_activity_ref(self.activity_ref)
        require_non_empty(self.source_activity_type, "source_activity_type")
        object.__setattr__(self, "start_time", _local(self.start_time, "start_time"))
        _check_numbers(self, dataclasses.fields(self))
        if self.sport is None and self.view_refusal is None:
            raise ContractError("Sans sport, view_refusal est présent.")
        recording = (
            "session_count",
            "device_manufacturer",
            "device_product",
            "software_version",
            "barometer",
            "external_heart_rate_sensor",
            "mean_temperature_c",
        )
        track = (
            "track_offset_s",
            "track_elapsed_s",
            "profile_distance_m",
            "profile_ascent_m",
            "profile_descent_m",
            "moving_s_by_convention",
            "stopped_s_by_convention",
            "undetermined_s_by_convention",
            "step_s",
            "longest_step_s",
            "gap_count",
            "gap_s",
            "timer_stop_count",
            "auto_pause_count",
            "position_gap_ascent_m",
            "loop",
            "closure_elevation_m",
            "closure_rate_ms",
            "altimetric_drift",
            "barometric",
            "mean_heart_rate_bpm",
            "heart_rate_coverage",
        )
        if not self.has_recording and any(
            getattr(self, n) is not None for n in recording
        ):
            raise ContractError("Sans enregistrement, aucun champ de l'enregistrement.")
        if not self.has_track and any(getattr(self, n) is not None for n in track):
            raise ContractError("Sans vue, aucun champ de la vue.")
        if self.has_track and not self.has_recording:
            raise ContractError("Une vue demande un enregistrement.")
        if not self.has_track and self.climb_count:
            raise ContractError("Sans vue, aucune montée.")
        names = [
            f.name
            for f in dataclasses.fields(self)
            if f.name not in ("closure_elevation_m", "mean_temperature_c")
        ]
        for name in names:
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, float | int | tuple):
                continue
            _check_non_negative(self, name)
        _check_fraction(self.heart_rate_coverage, "heart_rate_coverage")
        if self.mean_temperature_c is not None:
            require_in_range(
                self.mean_temperature_c, *TEMPERATURE_RANGE_C, "mean_temperature_c"
            )
        regimes = (
            self.short_climb_count
            + self.intermediate_count
            + self.long_climb_count
            + self.ski_touring_count
            + self.short_ski_touring_count
            + self.other_sport_count
        )
        if regimes != self.climb_count:
            raise ContractError("Les comptes par régime somment climb_count.")
        if max(self.flagged_climb_count, self.unstable_climb_count) > self.climb_count:
            raise ContractError("Montées marquées ou instables : au plus climb_count.")


_DAY_ROW_INSTANTS = (
    "window_start",
    "data_end",
    "night_start",
    "night_end",
    "readiness_instant",
    "ts_status_instant",
    "ts_load_balance_instant",
    "ts_vo2_max_instant",
    "ts_heat_instant",
    "ts_altitude_instant",
)

_DAY_ROW_NON_NEGATIVE = (
    "sleep_version",
    "sleep_respiration_version",
    "respiration_version",
    "summary_respiration_version",
    "summary_body_battery_version",
    "body_battery_series_versions",
    "measured_sleep_s",
    "deep_s",
    "light_s",
    "rem_s",
    "awake_s",
    "unmeasurable_s",
    "unmeasured_fraction",
    "night_restless_moments",
    "night_body_battery_coverage",
    "nap_count",
    "nap_window_s",
    "nap_sleep_s",
    "naps_overlapping_night",
    "stress_measured_s",
    "steps",
    "moderate_intensity_s",
    "vigorous_intensity_s",
    "floors_ascended_m",
    "floors_descended_m",
    "readiness_entry_count",
    "activity_count",
    "garmin_training_load",
    "activities_without_load",
    "foot_elapsed_s",
    "mtb_elapsed_s",
    "ski_touring_elapsed_s",
    "other_elapsed_s",
    "other_activity_count",
    "activities_without_elapsed",
    "hrv_log_dispersion",
    "resting_hr_dispersion_bpm",
    "measured_sleep_dispersion_s",
    "night_stress_dispersion",
    "night_respiration_dispersion_breaths_per_min",
    "night_spo2_dispersion_percent",
    "hrv_admitted_days",
    "resting_hr_admitted_days",
    "measured_sleep_admitted_days",
    "night_stress_admitted_days",
    "night_respiration_admitted_days",
    "night_spo2_admitted_days",
    "hrv_segment",
    "resting_hr_segment",
    "measured_sleep_segment",
    "night_stress_segment",
    "night_respiration_segment",
    "night_spo2_segment",
)

_NIGHT_FLAGS = (
    ("night_short", "night_short_absence"),
    ("night_shifted", "night_shifted_absence"),
)

_NIGHT_QUANTITIES = (
    "night_short",
    "night_shifted",
    "measured_sleep_s",
    "deep_s",
    "light_s",
    "rem_s",
    "awake_s",
    "unmeasurable_s",
    "unmeasured_fraction",
    "night_confirmation",
    "night_window_confirmed",
    "night_from_device",
    "night_rem_capable",
    "sleep_score",
    "night_avg_stress",
    "night_avg_heart_rate_bpm",
    "night_body_battery_change",
    "night_restless_moments",
    "skin_temperature_deviation_c",
    "night_body_battery_ceiling",
    "night_body_battery_coverage",
)

_NIGHT_ABSENCES = (
    "night_short_absence",
    "night_shifted_absence",
    "night_body_battery_absence",
)

_ACTIVITY_COUNTS = (
    "activities_without_load",
    "other_activity_count",
    "activities_without_elapsed",
)

_ACTIVITY_AMOUNTS = (
    "garmin_training_load",
    "foot_elapsed_s",
    "mtb_elapsed_s",
    "ski_touring_elapsed_s",
    "other_elapsed_s",
)

_ABSENT_ROW_MISSING = (
    "sleep_version",
    "sleep_respiration_version",
    "respiration_version",
    "summary_respiration_version",
    "summary_body_battery_version",
    "resting_hr_bpm",
    "hrv_last_night_avg_ms",
    "hrv_last_night_5min_high_ms",
    "hrv_weekly_avg_ms",
    "hrv_baseline_balanced_low_ms",
    "hrv_baseline_balanced_upper_ms",
    "hrv_baseline_low_upper_ms",
    "hrv_baseline_marker_value",
    "hrv_status",
    "respiration_avg_sleep_breaths_per_min",
    "respiration_avg_waking_breaths_per_min",
    "spo2_avg_sleep_percent",
    "spo2_average_percent",
    "spo2_lowest_percent",
    "stress_average_level",
    "stress_max_level",
    "stress_measured_s",
    "stress_valid",
    "body_battery_charged",
    "body_battery_drained",
    "body_battery_highest",
    "body_battery_lowest",
    "body_battery_at_wake",
    "body_battery_during_sleep",
    "steps",
    "moderate_intensity_s",
    "vigorous_intensity_s",
    "floors_ascended_m",
    "floors_descended_m",
    "average_altitude_m",
)

_MEASURE_COLUMNS = (
    ("hrv", "_ms", "hrv_last_night_avg_ms"),
    ("resting_hr", "_bpm", "resting_hr_bpm"),
    ("measured_sleep", "_s", "measured_sleep_s"),
    ("night_stress", "", "night_avg_stress"),
    (
        "night_respiration",
        "_breaths_per_min",
        "respiration_avg_sleep_breaths_per_min",
    ),
    ("night_spo2", "_percent", "spo2_avg_sleep_percent"),
)
"""Pour chaque mesure, dans l'ordre : son préfixe, le suffixe d'unité de ses colonnes,
la colonne de sa valeur."""


@dataclass(frozen=True)
class DayRow:
    """Une ligne de la table ``jours`` (AN2-2) : un jour du calendrier, du premier au
    dernier document d'``interim/days/``, bornes comprises ; la clé est ``day``.

    Champs
    ------
    Un instant est *aware*, au décalage de sa source (en Parquet, l'heure murale et le
    décalage) ; une grandeur absente (``None``) est un manque, jamais un zéro, sauf les
    durées de l'activité du jour, sommes des seules activités qui en ont (0 si aucune
    n'en a), que complète ``activities_without_elapsed``. Les valeurs « selon Garmin »
    sont celles du document du jour (``DayRecord``), sans rien de recalculé ; les états,
    les drapeaux et les statuts viennent des vues des jours
    (``mountain_perf.ingest.day_views``), appelées avec les seuils déclarés ``days.*``
    de la provenance.

    Le jour :

    - ``day`` — date — le jour de Garmin, celui du document.
    - ``state`` — sans unité — ``absent`` (aucun document ce jour), sinon l'état du
      document.
    - ``window_start``, ``data_end`` — instants — début de la fenêtre du jour (minuit
      local) et ``fin_donnees`` ; présents si l'état n'est ni ``absent`` ni ``empty``.
    - ``reference_export`` — sans unité — le nom de l'export de référence du jour.
    - ``device_ranks`` — sans unité — les rangs des appareils que nomment les familles
      du jour (``DayRecord.device_ranks``), triés.
    - ``uncertain_device`` — sans unité — valeur incertaine, commune aux six mesures :
      au moins deux rangs ce jour (on ne sait pas quelle montre a mesuré), ou un jour
      sans rang situé entre le dernier jour à rangs avant lui et un jour suivant de
      rupture de rang, sans jour à rangs entre eux (l'intervalle incertain d'un
      changement de montre).
    - ``sleep_version``, ``sleep_respiration_version``, ``respiration_version``,
      ``summary_respiration_version``, ``summary_body_battery_version`` — sans unité —
      les versions d'algorithme du jour (``AlgorithmVersions``).
    - ``body_battery_series_versions`` — sans unité — les versions de la série de
      Body Battery du jour, triées.

    La nuit rattachée au jour (le document du jour, et la vue ``night_assessment``) :

    - ``night_start``, ``night_end`` — instants — début et fin de la nuit principale.
    - ``night_state`` — sans unité — l'état de la nuit (``NightState``).
    - ``night_short``, ``night_shifted`` — sans unité — les drapeaux ``short`` et
      ``shifted`` : vrai, faux, ou inconnu (absent) ; ``night_short_absence``,
      ``night_shifted_absence`` — sans unité — le motif d'un drapeau inconnu.
    - ``measured_sleep_s`` — secondes — le sommeil mesuré (profond + léger, plus le
      paradoxal s'il est détecté).
    - ``deep_s``, ``light_s``, ``rem_s``, ``awake_s``, ``unmeasurable_s`` — secondes —
      profond, léger, paradoxal, éveil, non mesurable, selon Garmin.
    - ``unmeasured_fraction`` — fraction — non mesurable / (fin − début), positive ou
      nulle ;
      au-dessus de 1 si la source le veut (``Night`` ne promet pas que la somme de ses
      durées tient dans la nuit).
    - ``night_confirmation`` — sans unité — type de confirmation de la fenêtre, code
      de la source ; ``night_window_confirmed``, ``night_from_device``,
      ``night_rem_capable`` — sans unité — fenêtre confirmée, nuit venue de la montre,
      appareil qui détecte le paradoxal.
    - ``sleep_score`` — sans unité — score de sommeil selon Garmin.
    - ``night_avg_stress`` — sans unité — stress moyen du sommeil.
    - ``night_avg_heart_rate_bpm`` — battements par minute — FC moyenne du sommeil.
    - ``night_body_battery_change`` — sans unité — changement de Body Battery du
      sommeil.
    - ``night_restless_moments`` — sans unité — nombre de moments agités.
    - ``skin_temperature_deviation_c`` — °C — écart de température cutanée de la nuit.
    - ``night_body_battery_ceiling`` — sans unité — la série de Body Battery de la nuit
      atteint le haut de l'échelle de Garmin (« bb_plafond ») ;
      ``night_body_battery_coverage`` — fraction — sa couverture dans la fenêtre de la
      nuit (``series_between``, au pas déclaré) ; ``night_body_battery_absence`` —
      sans unité — le motif quand les deux manquent (sous le minimum de couverture,
      sans point, sans nuit).

    Les siestes (zéro sans sieste) :

    - ``nap_count`` — sans unité — les siestes du jour.
    - ``nap_window_s`` — secondes — la somme des durées de leurs fenêtres (fin −
      début).
    - ``nap_sleep_s`` — secondes — la somme de leurs durées de sommeil selon Garmin.
    - ``naps_overlapping_night`` — sans unité — les siestes qui recoupent la nuit.

    Les valeurs du jour (une grandeur de support ``day`` d'un jour qui n'est pas
    ``complete`` est absente, sauf la FC de repos, dont le statut le dit) :

    - ``resting_hr_bpm`` — battements par minute — la FC de repos selon Garmin
      (``resting_hr_on``) ; ``resting_hr_status`` — sans unité — son statut.
    - ``hrv_last_night_avg_ms``, ``hrv_last_night_5min_high_ms``,
      ``hrv_weekly_avg_ms`` — millisecondes — la HRV de la nuit, sa plus haute valeur
      de 5 min, celle de la semaine ; ``hrv_baseline_balanced_low_ms``,
      ``hrv_baseline_balanced_upper_ms``, ``hrv_baseline_low_upper_ms`` —
      millisecondes — les bornes de la normale de Garmin ;
      ``hrv_baseline_marker_value`` — sans unité — son repère ; ``hrv_status`` — sans
      unité — le statut HRV, code de la source.
    - ``respiration_avg_sleep_breaths_per_min``,
      ``respiration_avg_waking_breaths_per_min`` — respirations par minute — moyennes
      du sommeil et de l'éveil.
    - ``spo2_avg_sleep_percent``, ``spo2_average_percent``, ``spo2_lowest_percent`` —
      pourcentage — SpO2 du sommeil, moyenne et plus basse du jour.
    - ``stress_average_level``, ``stress_max_level`` — sans unité — stress moyen et
      maximal du jour ; ``stress_measured_s`` — secondes — la somme des durées au
      repos, en stress bas, moyen et haut (absente si l'une manque, donc sur tout jour
      qui n'est pas ``complete``) ; ``stress_valid`` — sans unité —
      ``stress_measured_s`` atteint la fraction déclarée de la fenêtre du jour ;
      absent sans stress ou sans fenêtre.
    - ``body_battery_charged``, ``body_battery_drained``, ``body_battery_highest``,
      ``body_battery_lowest``, ``body_battery_at_wake``, ``body_battery_during_sleep``
      — sans unité — le Body Battery du jour selon Garmin.
    - ``steps`` — sans unité — les pas ; ``moderate_intensity_s``,
      ``vigorous_intensity_s`` — secondes — intensité modérée et vigoureuse ;
      ``floors_ascended_m``, ``floors_descended_m`` — mètres — étages montés et
      descendus ; ``average_altitude_m`` — mètres — altitude moyenne du jour.

    Chacune, hors la FC de repos (la vue ``resting_hr_on``) et le stress mesuré, se lit
    au
    chemin du document de même sens, une clé de ``QUANTITY_SUPPORTS`` : ``hrv_<x>`` à
    ``hrv.<x>`` (les huit de la HRV), ``body_battery_<x>`` à ``body_battery.<x>`` (les
    six
    du Body Battery), les six de l'activité à ``activity_totals.<x>`` (``steps`` à
    ``activity_totals.steps``), ``stress_average_level`` à ``stress.average_level``,
    ``stress_max_level`` à ``stress.max_level``,
    ``respiration_avg_sleep_breaths_per_min``
    à ``respiration.avg_sleep_breaths_per_min``,
    ``respiration_avg_waking_breaths_per_min``
    à ``respiration.avg_waking_breaths_per_min``, ``spo2_avg_sleep_percent`` à
    ``spo2.avg_sleep_spo2_percent``, ``spo2_average_percent`` à
    ``spo2.average_spo2_percent``, ``spo2_lowest_percent`` à
    ``spo2.lowest_spo2_percent``.

    Training Readiness du réveil (``readiness_on_waking``, à la tolérance déclarée) :

    - ``readiness_score`` — sans unité — le score ; ``readiness_level`` — sans unité
      — le niveau, code de la source ; ``readiness_instant`` — instant — l'instant de
      l'entrée retenue ; ``readiness_absence`` — sans unité — le motif, sans entrée
      retenue.
    - ``readiness_entry_count`` — sans unité — les entrées de Training Readiness du
      jour.

    Training Status (le bloc de chaque sorte dont la date propre est ce jour ;
    l'instant d'une sorte est l'instant propre du bloc, absent si le bloc n'en a pas :
    la ligne porte alors des valeurs que ``training_status_at`` ne rend jamais) :

    - ``ts_status_instant`` — instant ; ``ts_status_code`` — sans unité — le statut,
      code de la source ; ``ts_acute_load``, ``ts_chronic_load`` — sans unité — les
      charges aiguë et chronique ; ``ts_acute_chronic_ratio`` — sans unité — leur
      rapport ; ``ts_acwr_status`` — sans unité — le statut du rapport, code de la
      source.
    - ``ts_load_balance_instant`` — instant ; ``ts_monthly_aerobic_low``,
      ``ts_monthly_aerobic_low_target_min``, ``ts_monthly_aerobic_low_target_max``,
      ``ts_monthly_aerobic_high``, ``ts_monthly_aerobic_high_target_min``,
      ``ts_monthly_aerobic_high_target_max``, ``ts_monthly_anaerobic``,
      ``ts_monthly_anaerobic_target_min``, ``ts_monthly_anaerobic_target_max`` — sans
      unité — l'équilibre de la charge mensuelle et ses cibles.
    - ``ts_vo2_max_instant`` — instant ; ``ts_vo2_max_ml_kg_min``,
      ``ts_vo2_max_precise_ml_kg_min`` — ml/kg/min — la VO2max affichée et précise.
    - ``ts_heat_instant`` — instant ; ``ts_heat_acclimation_percent`` — pourcentage —
      l'acclimatation à la chaleur ; ``ts_heat_trend`` — sans unité — sa tendance,
      code de la source.
    - ``ts_altitude_instant`` — instant ; ``ts_acclimation_altitude_m``,
      ``ts_current_altitude_m`` — mètres — les altitudes d'acclimatation et courante
      selon Garmin ; ``ts_altitude_trend`` — sans unité — sa tendance, code de la
      source.

    Le journal :

    - ``journal_types`` — sans unité — les types des événements de ``journal.csv`` qui
      couvrent le jour (du début à la fin, bornes comprises), triés, sans doublon ;
      vide sans événement.

    L'activité du jour (les entrées de l'index d'``interim/activities/`` de départ ce
    jour, en date locale, de tout type) :

    - ``activity_count`` — sans unité — les activités du jour.
    - ``garmin_training_load`` — sans unité — la somme de leurs charges selon Garmin ;
      ``0`` sans activité ; absente si toutes en sont sans.
    - ``activities_without_load`` — sans unité — les activités sans charge.
    - ``foot_elapsed_s``, ``mtb_elapsed_s``, ``ski_touring_elapsed_s`` — secondes — la
      somme des temps écoulés de l'index, par famille de la table des types.
    - ``other_elapsed_s`` — secondes — celle des types sans famille ;
      ``other_activity_count`` — sans unité — leur nombre.
    - ``activities_without_elapsed`` — sans unité — les activités sans temps écoulé,
      ajoutées à aucune durée.

    Les normales, pour six mesures, dans cet ordre : ``hrv`` (la HRV de la nuit, ms,
    en log), ``resting_hr`` (la FC de repos, bpm), ``measured_sleep`` (le sommeil
    mesuré, s), ``night_stress`` (le stress de la nuit, sans unité),
    ``night_respiration`` (la respiration de la nuit, respirations par minute),
    ``night_spo2`` (la SpO2 de la nuit, pourcentage). Pour le préfixe ``<p>`` d'une
    mesure d'unité ``<u>`` (sans suffixe pour ``night_stress``) :

    - ``<p>_admitted`` — sans unité — la valeur du jour entre dans les normales ;
      ``<p>_refusal`` — sans unité — sinon le motif, le premier dans l'ordre
      d'``AdmissionRefusal``.
    - ``<p>_normal_<u>`` — unité de la mesure — la normale du jour : la médiane des
      valeurs admises des jours ``[jour − fenêtre, jour − 1]`` ; pour la HRV,
      l'exponentielle de la médiane du log.
    - ``<p>_range_low_<u>``, ``<p>_range_high_<u>`` — unité de la mesure — la plage,
      médiane ∓ k s ; pour la HRV, exp(médiane du log ∓ k s du log), dissymétrique.
    - ``<p>_dispersion_<u>`` — unité de la mesure — la dispersion s = max(facteur ×
      MAD ; plancher) ; pour la HRV, à sa place, ``hrv_log_median`` et
      ``hrv_log_dispersion`` — sans unité — la médiane et s du log de la HRV en ms.
    - ``<p>_admitted_days`` — sans unité — les jours admis de la fenêtre ;
      ``<p>_normal_absence`` — sans unité — le motif d'une normale absente.
    - ``<p>_segment`` — sans unité — le nombre de lignes avant celle-ci dont la
      normale est absente.
    - ``<p>_rupture`` — sans unité — une rupture de la mesure ce jour : un rang du jour
      manque aux rangs du dernier jour précédent qui en porte, ou la version de la
      famille de la mesure change.
    - ``<p>_normal_straddles`` — sans unité — normale à cheval : une rupture de la
      mesure dans la fenêtre, le premier jour exclu, ou un jour incertain dans la
      fenêtre.

    Les colonnes, mesure par mesure :

    - ``hrv_admitted``, ``hrv_refusal``, ``hrv_normal_ms``, ``hrv_range_low_ms``,
      ``hrv_range_high_ms``, ``hrv_log_median``, ``hrv_log_dispersion``,
      ``hrv_admitted_days``, ``hrv_normal_absence``, ``hrv_segment``,
      ``hrv_rupture``, ``hrv_normal_straddles`` ;
    - ``resting_hr_admitted``, ``resting_hr_refusal``, ``resting_hr_normal_bpm``,
      ``resting_hr_range_low_bpm``, ``resting_hr_range_high_bpm``,
      ``resting_hr_dispersion_bpm``, ``resting_hr_admitted_days``,
      ``resting_hr_normal_absence``, ``resting_hr_segment``, ``resting_hr_rupture``,
      ``resting_hr_normal_straddles`` ;
    - ``measured_sleep_admitted``, ``measured_sleep_refusal``,
      ``measured_sleep_normal_s``, ``measured_sleep_range_low_s``,
      ``measured_sleep_range_high_s``, ``measured_sleep_dispersion_s``,
      ``measured_sleep_admitted_days``, ``measured_sleep_normal_absence``,
      ``measured_sleep_segment``, ``measured_sleep_rupture``,
      ``measured_sleep_normal_straddles`` ;
    - ``night_stress_admitted``, ``night_stress_refusal``, ``night_stress_normal``,
      ``night_stress_range_low``, ``night_stress_range_high``,
      ``night_stress_dispersion``, ``night_stress_admitted_days``,
      ``night_stress_normal_absence``, ``night_stress_segment``,
      ``night_stress_rupture``, ``night_stress_normal_straddles`` ;
    - ``night_respiration_admitted``, ``night_respiration_refusal``,
      ``night_respiration_normal_breaths_per_min``,
      ``night_respiration_range_low_breaths_per_min``,
      ``night_respiration_range_high_breaths_per_min``,
      ``night_respiration_dispersion_breaths_per_min``,
      ``night_respiration_admitted_days``, ``night_respiration_normal_absence``,
      ``night_respiration_segment``, ``night_respiration_rupture``,
      ``night_respiration_normal_straddles`` ;
    - ``night_spo2_admitted``, ``night_spo2_refusal``, ``night_spo2_normal_percent``,
      ``night_spo2_range_low_percent``, ``night_spo2_range_high_percent``,
      ``night_spo2_dispersion_percent``, ``night_spo2_admitted_days``,
      ``night_spo2_normal_absence``, ``night_spo2_segment``, ``night_spo2_rupture``,
      ``night_spo2_normal_straddles``.

    Invariants
    ----------
    - nombres finis ; instants *aware*, ramenés à un fuseau à décalage fixe ;
    - positifs ou nuls : les durées, les comptes, les versions, la charge, la
      couverture, ``unmeasured_fraction``, les jours admis, les segments, les
      dispersions ; ``night_body_battery_coverage`` dans ``[0, 1]`` ;
    - ``window_start`` et ``data_end`` présents ensemble, si et seulement si l'état
      n'est ni ``absent`` ni ``empty`` ; ``reference_export`` présent si et seulement
      si l'état n'est pas ``absent``, un nom d'export valide ;
    - ``device_ranks`` : des rangs d'au moins 1, strictement croissants ; au moins deux
      rangs :
      ``uncertain_device`` vrai ; ``body_battery_series_versions`` strictement
      croissant ;
    - ``night_start`` et ``night_end`` présents ensemble, si et seulement si
      ``night_state`` n'est pas ``missing`` ; ``night_start`` précède ``night_end`` ;
      sans
      nuit, aucune grandeur de la nuit, et les motifs des drapeaux et du Body Battery
      de la nuit valent ``no_night`` ;
    - chaque drapeau présent si et seulement si son motif est absent ;
      ``night_body_battery_ceiling`` et ``night_body_battery_coverage`` présents
      ensemble, si et seulement si ``night_body_battery_absence`` est absent ;
    - au plus ``nap_count`` siestes qui recoupent la nuit ; sans sieste, durées des
      siestes nulles ;
    - ``stress_valid`` présent seulement avec ``stress_measured_s`` ;
    - ``readiness_instant`` présent si et seulement si ``readiness_absence`` est
      absent ; ``readiness_score`` et ``readiness_level`` seulement avec l'instant ;
      un instant demande au moins une entrée ;
    - ``journal_types`` trié, sans doublon ;
    - ``activities_without_load``, ``other_activity_count`` et
      ``activities_without_elapsed`` au plus ``activity_count`` ;
      ``garmin_training_load`` absente si et seulement si le jour a des activités,
      toutes sans charge ; sans activité, charge et durées nulles ;
    - pour chaque mesure : ``<p>_admitted`` vrai si et seulement si ``<p>_refusal``
      est absent ; ``<p>_refusal`` vaut ``absent_row`` si et seulement si l'état est
      ``absent`` ; une valeur admise est présente ; la normale, sa plage et sa
      dispersion présentes ensemble, si et seulement si ``<p>_normal_absence`` est
      absent ; ``range_low`` ≤ ``normal`` ≤ ``range_high`` ; ``no_admitted_day`` si et
      seulement si ``<p>_admitted_days`` est nul ; ``hrv_normal_ms`` vaut
      l'exponentielle de ``hrv_log_median`` ;
    - une ligne ``absent`` n'a ni fenêtre, ni export de référence, ni rang, ni
      version, ni nuit (``night_state`` ``missing``), ni sieste, ni valeur du jour
      (``resting_hr_status`` ``absent``), ni entrée de Training Readiness ; elle peut
      porter Training Status, le journal, l'activité du jour, ``uncertain_device`` et
      sa normale.

    Producteur
    ----------
    La table ``jours`` (``mountain_perf.analyse.days``, AN2-2), mise dans les tables
    par ``mountain_perf.analyse.tables``.

    Consommateurs
    -------------
    La page « récupération » (AN2-3), qui lit ``jours`` et n'a rien à calculer ; les
    questions de la piste qui lisent des jours.

    Non promis
    ----------
    - les normales de ``jours`` sont descriptives : elles continuent à travers une
      rupture et la marquent, sans rien exclure ; celle d'une question se refait dans
      son plan (charte, § 11) ;
    - les composites de Garmin (Training Readiness, score de sommeil, statut HRV,
      Body Battery) n'ont pas de normale ;
    - une sortie enregistrée par deux appareils, deux fois dans l'index, s'additionne
      deux fois à l'activité du jour ; la charge est celle de Garmin, jamais
      recalculée ;
    - aucun firmware : les rangs ne se comparent pas à l'appareil d'un FIT ;
    - la ligne dépend aussi de ``journal.csv``, tenu à la main.
    """

    day: date
    state: DayRowState
    window_start: datetime | None
    data_end: datetime | None
    reference_export: str | None
    device_ranks: tuple[int, ...]
    uncertain_device: bool
    sleep_version: int | None
    sleep_respiration_version: int | None
    respiration_version: int | None
    summary_respiration_version: int | None
    summary_body_battery_version: int | None
    body_battery_series_versions: tuple[int, ...]
    night_start: datetime | None
    night_end: datetime | None
    night_state: NightState
    night_short: bool | None
    night_short_absence: ViewAbsence | None
    night_shifted: bool | None
    night_shifted_absence: ViewAbsence | None
    measured_sleep_s: float | None
    deep_s: float | None
    light_s: float | None
    rem_s: float | None
    awake_s: float | None
    unmeasurable_s: float | None
    unmeasured_fraction: float | None
    night_confirmation: str | None
    night_window_confirmed: bool | None
    night_from_device: bool | None
    night_rem_capable: bool | None
    sleep_score: int | None
    night_avg_stress: float | None
    night_avg_heart_rate_bpm: float | None
    night_body_battery_change: int | None
    night_restless_moments: int | None
    skin_temperature_deviation_c: float | None
    night_body_battery_ceiling: bool | None
    night_body_battery_coverage: float | None
    night_body_battery_absence: ViewAbsence | None
    nap_count: int
    nap_window_s: float
    nap_sleep_s: float
    naps_overlapping_night: int
    resting_hr_bpm: float | None
    resting_hr_status: RestingHrStatus
    hrv_last_night_avg_ms: float | None
    hrv_last_night_5min_high_ms: float | None
    hrv_weekly_avg_ms: float | None
    hrv_baseline_balanced_low_ms: float | None
    hrv_baseline_balanced_upper_ms: float | None
    hrv_baseline_low_upper_ms: float | None
    hrv_baseline_marker_value: float | None
    hrv_status: str | None
    respiration_avg_sleep_breaths_per_min: float | None
    respiration_avg_waking_breaths_per_min: float | None
    spo2_avg_sleep_percent: float | None
    spo2_average_percent: float | None
    spo2_lowest_percent: float | None
    stress_average_level: int | None
    stress_max_level: int | None
    stress_measured_s: float | None
    stress_valid: bool | None
    body_battery_charged: int | None
    body_battery_drained: int | None
    body_battery_highest: int | None
    body_battery_lowest: int | None
    body_battery_at_wake: int | None
    body_battery_during_sleep: int | None
    steps: int | None
    moderate_intensity_s: float | None
    vigorous_intensity_s: float | None
    floors_ascended_m: float | None
    floors_descended_m: float | None
    average_altitude_m: float | None
    readiness_score: int | None
    readiness_level: str | None
    readiness_instant: datetime | None
    readiness_absence: ViewAbsence | None
    readiness_entry_count: int
    ts_status_instant: datetime | None
    ts_status_code: int | None
    ts_acute_load: float | None
    ts_chronic_load: float | None
    ts_acute_chronic_ratio: float | None
    ts_acwr_status: str | None
    ts_load_balance_instant: datetime | None
    ts_monthly_aerobic_low: float | None
    ts_monthly_aerobic_low_target_min: float | None
    ts_monthly_aerobic_low_target_max: float | None
    ts_monthly_aerobic_high: float | None
    ts_monthly_aerobic_high_target_min: float | None
    ts_monthly_aerobic_high_target_max: float | None
    ts_monthly_anaerobic: float | None
    ts_monthly_anaerobic_target_min: float | None
    ts_monthly_anaerobic_target_max: float | None
    ts_vo2_max_instant: datetime | None
    ts_vo2_max_ml_kg_min: float | None
    ts_vo2_max_precise_ml_kg_min: float | None
    ts_heat_instant: datetime | None
    ts_heat_acclimation_percent: float | None
    ts_heat_trend: str | None
    ts_altitude_instant: datetime | None
    ts_acclimation_altitude_m: float | None
    ts_current_altitude_m: float | None
    ts_altitude_trend: str | None
    journal_types: tuple[JournalEventType, ...]
    activity_count: int
    garmin_training_load: float | None
    activities_without_load: int
    foot_elapsed_s: float
    mtb_elapsed_s: float
    ski_touring_elapsed_s: float
    other_elapsed_s: float
    other_activity_count: int
    activities_without_elapsed: int
    hrv_admitted: bool
    hrv_refusal: AdmissionRefusal | None
    hrv_normal_ms: float | None
    hrv_range_low_ms: float | None
    hrv_range_high_ms: float | None
    hrv_log_median: float | None
    hrv_log_dispersion: float | None
    hrv_admitted_days: int
    hrv_normal_absence: NormalAbsence | None
    hrv_segment: int
    hrv_rupture: bool
    hrv_normal_straddles: bool
    resting_hr_admitted: bool
    resting_hr_refusal: AdmissionRefusal | None
    resting_hr_normal_bpm: float | None
    resting_hr_range_low_bpm: float | None
    resting_hr_range_high_bpm: float | None
    resting_hr_dispersion_bpm: float | None
    resting_hr_admitted_days: int
    resting_hr_normal_absence: NormalAbsence | None
    resting_hr_segment: int
    resting_hr_rupture: bool
    resting_hr_normal_straddles: bool
    measured_sleep_admitted: bool
    measured_sleep_refusal: AdmissionRefusal | None
    measured_sleep_normal_s: float | None
    measured_sleep_range_low_s: float | None
    measured_sleep_range_high_s: float | None
    measured_sleep_dispersion_s: float | None
    measured_sleep_admitted_days: int
    measured_sleep_normal_absence: NormalAbsence | None
    measured_sleep_segment: int
    measured_sleep_rupture: bool
    measured_sleep_normal_straddles: bool
    night_stress_admitted: bool
    night_stress_refusal: AdmissionRefusal | None
    night_stress_normal: float | None
    night_stress_range_low: float | None
    night_stress_range_high: float | None
    night_stress_dispersion: float | None
    night_stress_admitted_days: int
    night_stress_normal_absence: NormalAbsence | None
    night_stress_segment: int
    night_stress_rupture: bool
    night_stress_normal_straddles: bool
    night_respiration_admitted: bool
    night_respiration_refusal: AdmissionRefusal | None
    night_respiration_normal_breaths_per_min: float | None
    night_respiration_range_low_breaths_per_min: float | None
    night_respiration_range_high_breaths_per_min: float | None
    night_respiration_dispersion_breaths_per_min: float | None
    night_respiration_admitted_days: int
    night_respiration_normal_absence: NormalAbsence | None
    night_respiration_segment: int
    night_respiration_rupture: bool
    night_respiration_normal_straddles: bool
    night_spo2_admitted: bool
    night_spo2_refusal: AdmissionRefusal | None
    night_spo2_normal_percent: float | None
    night_spo2_range_low_percent: float | None
    night_spo2_range_high_percent: float | None
    night_spo2_dispersion_percent: float | None
    night_spo2_admitted_days: int
    night_spo2_normal_absence: NormalAbsence | None
    night_spo2_segment: int
    night_spo2_rupture: bool
    night_spo2_normal_straddles: bool

    def __post_init__(self) -> None:
        self._check_values()
        self._check_day()
        self._check_night()
        self._check_episodes()
        self._check_activity()
        for prefix, unit, value in _MEASURE_COLUMNS:
            self._check_measure(prefix, unit, value)
        if self.state is DayRowState.ABSENT:
            self._check_absent_row()

    def _check_values(self) -> None:
        for name in _DAY_ROW_INSTANTS:
            value = getattr(self, name)
            if value is not None:
                object.__setattr__(self, name, _local(value, name))
        _check_numbers(self, dataclasses.fields(self))
        _check_non_negative(self, *_DAY_ROW_NON_NEGATIVE)
        _check_fraction(self.night_body_battery_coverage, "night_body_battery_coverage")

    def _check_day(self) -> None:
        if (self.window_start is None) != (self.data_end is None):
            raise ContractError("window_start et data_end vont ensemble.")
        has_window = self.state not in (DayRowState.ABSENT, DayRowState.EMPTY)
        if (self.window_start is not None) != has_window:
            raise ContractError(
                "window_start et data_end : présents si et seulement si state n'est "
                "ni absent ni empty."
            )
        if (self.reference_export is None) != (self.state is DayRowState.ABSENT):
            raise ContractError(
                "reference_export : absent si et seulement si state est absent."
            )
        if self.reference_export is not None:
            try:
                require_export_name(self.reference_export)
            except ContractError as error:
                raise ContractError(f"reference_export : {error}") from error
        for rank in self.device_ranks:
            if rank < 1:
                raise ContractError(f"device_ranks doit être >= 1, reçu {rank}.")
        require_increasing(self.device_ranks, "device_ranks", strict=True)
        if len(self.device_ranks) >= 2 and not self.uncertain_device:
            raise ContractError(
                "uncertain_device : un jour à au moins deux rangs est incertain."
            )
        require_increasing(
            self.body_battery_series_versions,
            "body_battery_series_versions",
            strict=True,
        )

    def _check_night(self) -> None:
        if (self.night_start is None) != (self.night_end is None):
            raise ContractError("night_start et night_end vont ensemble.")
        if (self.night_start is not None) != (
            self.night_state is not NightState.MISSING
        ):
            raise ContractError(
                "night_start et night_end : présents si et seulement si night_state "
                "n'est pas missing."
            )
        if (
            self.night_start is not None
            and self.night_end is not None
            and not self.night_start < self.night_end
        ):
            raise ContractError("night_start doit précéder night_end.")
        for flag, absence in _NIGHT_FLAGS:
            if (getattr(self, flag) is None) == (getattr(self, absence) is None):
                raise ContractError(
                    f"{flag} et {absence} : l'un ou l'autre, jamais les deux."
                )
        if (self.night_body_battery_ceiling is None) != (
            self.night_body_battery_coverage is None
        ):
            raise ContractError(
                "night_body_battery_ceiling et night_body_battery_coverage vont "
                "ensemble."
            )
        if (self.night_body_battery_coverage is None) == (
            self.night_body_battery_absence is None
        ):
            raise ContractError(
                "night_body_battery_coverage et night_body_battery_absence : l'un ou "
                "l'autre, jamais les deux."
            )
        if self.night_start is None:
            for name in _NIGHT_QUANTITIES:
                if getattr(self, name) is not None:
                    raise ContractError(
                        f"Sans nuit, aucune grandeur de la nuit : {name}."
                    )
            for name in _NIGHT_ABSENCES:
                if getattr(self, name) is not ViewAbsence.NO_NIGHT:
                    raise ContractError(f"Sans nuit, {name} vaut no_night.")

    def _check_episodes(self) -> None:
        if self.naps_overlapping_night > self.nap_count:
            raise ContractError("naps_overlapping_night : au plus nap_count.")
        if self.nap_count == 0 and (self.nap_window_s != 0 or self.nap_sleep_s != 0):
            raise ContractError("Sans sieste, nap_window_s et nap_sleep_s sont nuls.")
        if self.stress_valid is not None and self.stress_measured_s is None:
            raise ContractError("stress_valid demande stress_measured_s.")
        if (self.readiness_instant is None) == (self.readiness_absence is None):
            raise ContractError(
                "readiness_instant et readiness_absence : l'un ou l'autre, jamais les "
                "deux."
            )
        if self.readiness_instant is None and (
            self.readiness_score is not None or self.readiness_level is not None
        ):
            raise ContractError(
                "readiness_score et readiness_level demandent readiness_instant."
            )
        if self.readiness_instant is not None and self.readiness_entry_count < 1:
            raise ContractError("readiness_instant demande readiness_entry_count >= 1.")
        if list(self.journal_types) != sorted(set(self.journal_types)):
            raise ContractError("journal_types doit être trié, sans doublon.")

    def _check_activity(self) -> None:
        for name in _ACTIVITY_COUNTS:
            if getattr(self, name) > self.activity_count:
                raise ContractError(f"{name} : au plus activity_count.")
        all_without_load = (
            self.activity_count > 0
            and self.activities_without_load == self.activity_count
        )
        if (self.garmin_training_load is None) != all_without_load:
            raise ContractError(
                "garmin_training_load : absente si et seulement si le jour a des "
                "activités, toutes sans charge."
            )
        if self.activity_count == 0 and any(
            getattr(self, name) != 0 for name in _ACTIVITY_AMOUNTS
        ):
            raise ContractError(
                "Sans activité, garmin_training_load et les durées sont nulles."
            )

    def _check_measure(self, prefix: str, unit: str, value: str) -> None:
        admitted = f"{prefix}_admitted"
        refusal = f"{prefix}_refusal"
        normal = f"{prefix}_normal{unit}"
        low = f"{prefix}_range_low{unit}"
        high = f"{prefix}_range_high{unit}"
        absence = f"{prefix}_normal_absence"
        days = f"{prefix}_admitted_days"
        if getattr(self, admitted) != (getattr(self, refusal) is None):
            raise ContractError(
                f"{admitted} : vrai si et seulement si {refusal} est absent."
            )
        if (getattr(self, refusal) is AdmissionRefusal.ABSENT_ROW) != (
            self.state is DayRowState.ABSENT
        ):
            raise ContractError(
                f"{refusal} vaut absent_row si et seulement si state est absent."
            )
        if getattr(self, admitted) and getattr(self, value) is None:
            raise ContractError(f"{admitted} : une valeur admise ({value}) est là.")
        group = (
            (normal, low, high, "hrv_log_dispersion", "hrv_log_median")
            if prefix == "hrv"
            else (normal, low, high, f"{prefix}_dispersion{unit}")
        )
        if len({getattr(self, name) is None for name in group}) > 1:
            raise ContractError(f"{', '.join(group)} vont ensemble.")
        if (getattr(self, normal) is None) == (getattr(self, absence) is None):
            raise ContractError(
                f"{normal} et {absence} : l'un ou l'autre, jamais les deux."
            )
        if (getattr(self, absence) is NormalAbsence.NO_ADMITTED_DAY) != (
            getattr(self, days) == 0
        ):
            raise ContractError(
                f"{absence} vaut no_admitted_day si et seulement si {days} est nul."
            )
        center = getattr(self, normal)
        if center is None:
            return
        if not getattr(self, low) <= center <= getattr(self, high):
            raise ContractError(f"Il faut {low} <= {normal} <= {high}.")
        if prefix == "hrv" and self.hrv_log_median is not None:
            try:
                expected = math.exp(self.hrv_log_median)
            except OverflowError:
                expected = math.inf
            if not math.isclose(center, expected, rel_tol=1e-9):
                raise ContractError("hrv_normal_ms doit valoir exp(hrv_log_median).")

    def _check_absent_row(self) -> None:
        if self.device_ranks:
            raise ContractError("Une ligne absent n'a pas de rang : device_ranks vide.")
        if self.body_battery_series_versions:
            raise ContractError(
                "Une ligne absent n'a pas de version : body_battery_series_versions "
                "vide."
            )
        for name in _ABSENT_ROW_MISSING:
            if getattr(self, name) is not None:
                raise ContractError(
                    f"Une ligne absent n'a ni version ni valeur du jour : {name}."
                )
        if self.night_state is not NightState.MISSING:
            raise ContractError(
                "Une ligne absent n'a pas de nuit : night_state missing."
            )
        if self.nap_count != 0:
            raise ContractError("Une ligne absent n'a pas de sieste : nap_count nul.")
        if self.resting_hr_status is not RestingHrStatus.ABSENT:
            raise ContractError("Une ligne absent : resting_hr_status vaut absent.")
        if self.readiness_entry_count != 0:
            raise ContractError(
                "Une ligne absent n'a pas d'entrée de Training Readiness : "
                "readiness_entry_count nul."
            )


JOURNAL_ABSENT = "absent"
"""``ProcessedProvenance.journal_sha256`` quand ``journal.csv`` n'existe pas."""


def _is_sha256(text: str) -> bool:
    return len(text) == 64 and all(c in "0123456789abcdef" for c in text)


@dataclass(frozen=True)
class ProcessedProvenance:
    """La provenance des tables de ``processed/``, écrite dans les métadonnées de
    chaque fichier.

    Champs
    ------
    - ``interim_sha256`` — sans unité — empreinte d'``interim/activities/`` seul :
      SHA-256 de la liste triée des chemins relatifs et des SHA-256 de ses documents ;
      ``interim/days/`` a la sienne, ``interim_days_sha256``.
    - ``package_version`` — sans unité — version du paquet qui a écrit les tables.
    - ``commit`` — sans unité — commit git du code qui a écrit les tables ;
      ``mperf tables`` refuse un arbre de travail modifié (AN1-2c).
    - ``reference_vertical_speed_ms`` — m/s — ``V_ref`` utilisée ;
      ``reference_vertical_speed_declared`` — sans unité — déclarée dans
      ``athlete.toml``, ou défaut du projet.
    - ``barometer_products`` — sans unité — produits déclarés barométriques,
      ``fabricant:produit``, triés.
    - ``parameters`` — sans unité — tous les paramètres de la définition, par nom
      ``famille.nom`` (profil, montée, drapeaux, régimes, stabilité ; depuis AN2-2,
      ``days.<nom>`` les seuils des vues et des validités de la table ``jours``, et
      ``normal.<nom>`` ceux de ses normales), triés.
    - ``activity_count``, ``climb_count``, ``variant_climb_count`` — sans unité —
      lignes des tables ``activites``, ``montees`` et ``variantes``.
    - ``interim_days_sha256`` — sans unité — empreinte d'``interim/days/``, calculée
      comme ``interim_sha256``.
    - ``journal_sha256`` — sans unité — SHA-256 des octets de ``journal.csv``, ou
      ``JOURNAL_ABSENT`` (``"absent"``) s'il n'existe pas.
    - ``day_count`` — sans unité — lignes de la table ``jours``.
    - ``acquired_at`` — instant, en texte ISO 8601 — l'instant d'acquisition le plus
      récent des exports du rapport des jours (``DaysReport.exports[*].retrieved_at``,
      stocké en UTC), écrit par la méthode ``isoformat`` de cet instant en UTC ;
      toujours présent : le rapport des jours nomme au moins un export.

    Invariants
    ----------
    - ``interim_sha256`` et ``interim_days_sha256`` : 64 chiffres hexadécimaux
      minuscules ; ``journal_sha256`` de même, ou ``JOURNAL_ABSENT`` ;
    - ``package_version`` non vide ; ``commit`` : 40 ou 64 chiffres hexadécimaux
      minuscules (SHA-1 ou SHA-256 de git) ; ``reference_vertical_speed_ms`` strictement
      positive ;
    - ``barometer_products`` et ``parameters`` triés, sans doublon ; valeurs finies ;
    - comptes positifs ou nuls ;
    - ``acquired_at``, un texte, se relit par ``datetime.fromisoformat`` en un
      instant *aware* de décalage nul, que la méthode ``isoformat`` réécrit à
      l'identique.

    Producteur
    ----------
    ``mountain_perf.analyse.tables``.

    Consommateurs
    -------------
    Les résultats de la piste (charte, § 10 : empreinte des données, seuils figés).

    Non promis
    ----------
    - un instant de génération : il n'y en a pas, et deux régénérations du même
      ``interim/`` par le même code, avec le même ``athlete.toml`` (``V_ref``,
      produits barométriques) et le même ``journal.csv``, sur la même plateforme,
      écrivent les mêmes tables : les tables dépendent aussi de ``journal.csv``, tenu
      à la main, et toute retouche du fichier, une note ou un blanc compris, change son
      empreinte, donc les quatre tables et l'empreinte des résultats de Q1 ;
    - d'une plateforme à l'autre (Windows, Linux), les mêmes tables à l'octet : les
      fonctions trigonométriques du système peuvent différer d'une unité du dernier
      chiffre.
    """

    interim_sha256: str
    package_version: str
    commit: str
    reference_vertical_speed_ms: float
    reference_vertical_speed_declared: bool
    barometer_products: tuple[str, ...]
    parameters: tuple[tuple[str, float], ...]
    activity_count: int
    climb_count: int
    variant_climb_count: int
    interim_days_sha256: str
    journal_sha256: str
    day_count: int
    acquired_at: str

    def __post_init__(self) -> None:
        if len(self.interim_sha256) != 64 or any(
            c not in "0123456789abcdef" for c in self.interim_sha256
        ):
            raise ContractError("interim_sha256 : 64 chiffres hexadécimaux minuscules.")
        require_non_empty(self.package_version, "package_version")
        if len(self.commit) not in (40, 64) or any(
            c not in "0123456789abcdef" for c in self.commit
        ):
            raise ContractError("commit : 40 ou 64 chiffres hexadécimaux minuscules.")
        require_finite(self.reference_vertical_speed_ms, "reference_vertical_speed_ms")
        if self.reference_vertical_speed_ms <= 0:
            raise ContractError("reference_vertical_speed_ms doit être > 0.")
        if list(self.barometer_products) != sorted(set(self.barometer_products)):
            raise ContractError("barometer_products doit être trié, sans doublon.")
        names = [name for name, _ in self.parameters]
        if names != sorted(set(names)):
            raise ContractError("parameters doit être trié par nom, sans doublon.")
        for name, value in self.parameters:
            require_finite(value, name)
        if min(self.activity_count, self.climb_count, self.variant_climb_count) < 0:
            raise ContractError("Les comptes sont positifs ou nuls.")
        if not _is_sha256(self.interim_days_sha256):
            raise ContractError(
                "interim_days_sha256 : 64 chiffres hexadécimaux minuscules."
            )
        if self.journal_sha256 != JOURNAL_ABSENT and not _is_sha256(
            self.journal_sha256
        ):
            raise ContractError(
                "journal_sha256 : 64 chiffres hexadécimaux minuscules, ou 'absent'."
            )
        if self.day_count < 0:
            raise ContractError(f"day_count doit être >= 0, reçu {self.day_count}.")
        self._check_acquired_at()

    def _check_acquired_at(self) -> None:
        text: object = self.acquired_at
        if not isinstance(text, str):
            raise ContractError(
                "acquired_at : un instant ISO 8601 en texte, obligatoire, reçu "
                f"{type(text).__name__}."
            )
        try:
            instant = datetime.fromisoformat(text)
        except ValueError as error:
            raise ContractError("acquired_at : instant ISO 8601 illisible.") from error
        if instant.utcoffset() != timedelta(0):
            raise ContractError(
                "acquired_at doit être en UTC (un décalage nul, écrit)."
            )
        if instant.isoformat() != text:
            raise ContractError(
                "acquired_at doit être l'écriture isoformat() de son instant en UTC."
            )
