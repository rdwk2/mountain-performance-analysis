"""Contrats de ``processed/`` (AN1-2b, ``docs/decisions/0014``) : les tables
``activites`` et ``montees`` de la piste analyse, et leur provenance.

Une ligne de table est un contrat : ses champs, leurs unités et leurs invariants sont
ici, et le dictionnaire de données les publie. Les tables s'écrivent en Parquet par
``mountain_perf.analyse.parquet`` (extra ``analyse``) ; elles se régénèrent en entier
depuis ``interim/`` et se relisent sans rien recalculer.

Les champs ``*_by_convention`` ont une valeur par convention de ``CLOCK_CONVENTIONS``
(``0010`` D5.2), dans son ordre ; la convention centrale θc est à l'indice
``CENTRAL_CONVENTION_INDEX`` de ``schemas/clock.py``.
"""

from __future__ import annotations

import dataclasses
import math
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import StrEnum
from types import MappingProxyType
from typing import Any

from mountain_perf.schemas.clock import CLOCK_CONVENTIONS
from mountain_perf.schemas.common import UTC_OFFSET_RANGE_S, Sport
from mountain_perf.schemas.interim import (
    TEMPERATURE_RANGE_C,
    ViewRefusal,
    require_activity_ref,
)
from mountain_perf.validation import (
    ContractError,
    require_aware,
    require_finite,
    require_in_range,
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

    - ``activity_ref`` — sans unité — l'activité (index de l'export).
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
      ``flags`` triés, sans doublon.

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
        if self.moving_mean_temperature_c is not None:
            require_in_range(
                self.moving_mean_temperature_c,
                *TEMPERATURE_RANGE_C,
                "moving_mean_temperature_c",
            )
        if list(self.flags) != sorted(set(self.flags)):
            raise ContractError("flags doit être trié, sans doublon.")


@dataclass(frozen=True)
class ActivityRow:
    """Une ligne de la table ``activites`` : une entrée de l'index de l'export, de
    tout type.

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
    La figure de Q1 (AN1-2c, flux par mois) ; la charge recalculée (AN2) ; les
    questions de la piste.

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


@dataclass(frozen=True)
class ProcessedProvenance:
    """La provenance des tables de ``processed/``, écrite dans les métadonnées de
    chaque fichier.

    Champs
    ------
    - ``interim_sha256`` — sans unité — empreinte d'``interim/activities/`` : SHA-256
      de la liste triée des chemins relatifs et des SHA-256 de ses documents.
    - ``package_version`` — sans unité — version du paquet qui a écrit les tables.
    - ``reference_vertical_speed_ms`` — m/s — ``V_ref`` utilisée ;
      ``reference_vertical_speed_declared`` — sans unité — déclarée dans
      ``athlete.toml``, ou défaut du projet.
    - ``barometer_products`` — sans unité — produits déclarés barométriques,
      ``fabricant:produit``, triés.
    - ``parameters`` — sans unité — tous les paramètres de la définition, par nom
      ``famille.nom`` (profil, montée, drapeaux, régimes, stabilité), triés.
    - ``activity_count``, ``climb_count`` — sans unité — lignes des deux tables.

    Invariants
    ----------
    - ``interim_sha256`` : 64 chiffres hexadécimaux minuscules ;
    - ``package_version`` non vide ; ``reference_vertical_speed_ms > 0`` ;
    - ``barometer_products`` et ``parameters`` triés, sans doublon ; valeurs finies ;
    - comptes positifs ou nuls.

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
      produits barométriques), sur la même plateforme, écrivent les mêmes tables ;
    - d'une plateforme à l'autre (Windows, Linux), les mêmes tables à l'octet : les
      fonctions trigonométriques du système peuvent différer d'une unité du dernier
      chiffre.
    """

    interim_sha256: str
    package_version: str
    reference_vertical_speed_ms: float
    reference_vertical_speed_declared: bool
    barometer_products: tuple[str, ...]
    parameters: tuple[tuple[str, float], ...]
    activity_count: int
    climb_count: int

    def __post_init__(self) -> None:
        if len(self.interim_sha256) != 64 or any(
            c not in "0123456789abcdef" for c in self.interim_sha256
        ):
            raise ContractError("interim_sha256 : 64 chiffres hexadécimaux minuscules.")
        require_non_empty(self.package_version, "package_version")
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
        if self.activity_count < 0 or self.climb_count < 0:
            raise ContractError("Les comptes sont positifs ou nuls.")
