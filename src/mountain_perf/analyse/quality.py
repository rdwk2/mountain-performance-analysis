"""Drapeaux, régimes et strates d'une montée (AN1-2, ``docs/decisions/0014``).

Un drapeau marque une montée, il ne la retire jamais de la table : la figure (AN1-2c)
dit, par motif, ce qu'elle écarte de sa vue principale. Les régimes et les strates se
lisent sur le terrain (gain, pente, altitude), jamais sur la durée : une durée dépend
de la vitesse, c'est-à-dire de la mesure étudiée.

Les seuils sont des paramètres déclarés, communs à tous les athlètes, sauf ``V_ref``,
la vitesse ascensionnelle de référence, que l'athlète déclare (``athlete.toml``) et qui
fixe la frontière des régimes en gain : côtes jusqu'à ``V_ref × 5 min``, montées
longues dès ``V_ref × 15 min``.

Python pur : ce module ne demande aucun extra.
"""

from __future__ import annotations

from mountain_perf.analyse.climbs import ClimbMeasure
from mountain_perf.schemas import ParameterSet, ParameterSpec, Sport
from mountain_perf.schemas.processed import (
    AltitudeStratum,
    ClimbFlag,
    ClimbRegime,
    GradeStratum,
)

QUALITY_PARAMETER_SPECS: tuple[ParameterSpec, ...] = (
    ParameterSpec(
        "max_outside_moving_gain_fraction",
        None,
        0.20,
        0.0,
        1.0,
        "Part du gain prise hors de M au-delà de laquelle la montée est marquée.",
    ),
    ParameterSpec(
        "max_slow_moving_fraction",
        None,
        0.10,
        0.0,
        1.0,
        "Part du temps M passée lentement, sans gain, au-delà de laquelle la montée"
        " est marquée.",
    ),
    ParameterSpec(
        "max_human_vertical_speed_ms",
        "m/s",
        3000.0 / 3600.0,
        0.1,
        5.0,
        "VAM au-delà de laquelle une montée n'est pas humaine (remontée mécanique,"
        " véhicule).",
    ),
    ParameterSpec(
        "max_foot_horizontal_speed_ms",
        "m/s",
        10.0,
        1.0,
        50.0,
        "Vitesse horizontale en M au-delà de laquelle une montée à pied n'est pas"
        " humaine.",
    ),
    ParameterSpec(
        "max_record_vertical_rate_ms",
        "m/s",
        3.0,
        0.1,
        50.0,
        "Variation d'altitude brute entre deux enregistrements au-delà de laquelle la"
        " montée porte un pic.",
    ),
    ParameterSpec(
        "max_sinuosity",
        None,
        6.0,
        1.0,
        1000.0,
        "Sinuosité au-delà de laquelle la pente d'une montée n'est pas résolue.",
    ),
    ParameterSpec(
        "loop_closure_distance_m",
        "m",
        50.0,
        1.0,
        1000.0,
        "Distance de l'arrivée au départ sous laquelle une activité est une boucle.",
    ),
    ParameterSpec(
        "max_loop_closure_rate_ms",
        "m/s",
        5.0 / 3600.0,
        0.0,
        1.0,
        "Fermeture altimétrique d'une boucle, par unité de temps, au-delà de laquelle"
        " ses montées sont marquées.",
    ),
)
"""Les seuils des drapeaux (``docs/decisions/0014``)."""

REGIME_PARAMETER_SPECS: tuple[ParameterSpec, ...] = (
    ParameterSpec(
        "short_climb_max_duration_s",
        "s",
        300.0,
        1.0,
        36000.0,
        "Une côte gagne au plus V_ref fois cette durée.",
    ),
    ParameterSpec(
        "long_climb_min_duration_s",
        "s",
        900.0,
        1.0,
        36000.0,
        "Une montée longue gagne au moins V_ref fois cette durée.",
    ),
    ParameterSpec(
        "moderate_grade_max",
        None,
        0.15,
        0.0,
        10.0,
        "Borne haute de la strate de pente modérée.",
    ),
    ParameterSpec(
        "steep_grade_max",
        None,
        0.30,
        0.0,
        10.0,
        "Borne haute de la strate de pente raide ; au-delà, très raide.",
    ),
    ParameterSpec(
        "low_altitude_max_m",
        "m",
        1500.0,
        -500.0,
        9000.0,
        "Borne haute de la strate d'altitude basse (altitude moyenne en M).",
    ),
    ParameterSpec(
        "mid_altitude_max_m",
        "m",
        2500.0,
        -500.0,
        9000.0,
        "Borne haute de la strate d'altitude moyenne ; au-delà, haute.",
    ),
)
"""Les régimes et les strates (``docs/decisions/0014``). Les deux durées ne
s'appliquent jamais à une durée mesurée : multipliées par ``V_ref``, elles donnent
des seuils de gain."""

DEFAULT_REFERENCE_VERTICAL_SPEED_MS = 900.0 / 3600.0
"""``V_ref`` par défaut du projet, quand ``athlete.toml`` n'en déclare pas."""


def grade_unresolved(
    measure: ClimbMeasure, climb: ParameterSet, quality: ParameterSet
) -> bool:
    """La pente de la montée n'est pas lue : sinuosité au-delà de ``max_sinuosity``
    (ou déplacement net nul), ou pente en M, ``G_M,θc / L_M``, jusqu'à la pente
    minimale de la montée (le filtre lit toute la montée : une part de son gain est
    alors prise hors de M). Une seule définition, pour la strate et pour le
    drapeau."""
    sinuosity = measure.sinuosity
    return (
        sinuosity is None
        or sinuosity > quality["max_sinuosity"]
        or measure.grade <= climb["min_grade"]
    )


def climb_flags(
    measure: ClimbMeasure,
    sport: Sport | None,
    *,
    barometric: bool,
    altimetric_drift: bool,
    climb: ParameterSet,
    quality: ParameterSet,
) -> frozenset[ClimbFlag]:
    """Les drapeaux de ``measure``. ``barometric`` : l'altitude vient d'un baromètre
    attesté ; ``altimetric_drift`` : l'activité est une boucle dont la fermeture
    altimétrique dépasse le seuil (:func:`altimetric_drift`) ; ``climb`` : les
    paramètres de la montée (la pente minimale, :func:`grade_unresolved`)."""
    flags: set[ClimbFlag] = set()
    outside = measure.outside_moving_gain_fraction
    if outside is None or outside > quality["max_outside_moving_gain_fraction"]:
        flags.add(ClimbFlag.GAIN_OUTSIDE_MOVING)
    slow = measure.slow_moving_fraction
    if slow is not None and slow > quality["max_slow_moving_fraction"]:
        flags.add(ClimbFlag.SLOW_MOVING)
    vertical = measure.vertical_speed_ms
    horizontal = measure.moving_horizontal_speed_ms
    if (vertical is not None and vertical > quality["max_human_vertical_speed_ms"]) or (
        sport is Sport.FOOT
        and horizontal is not None
        and horizontal > quality["max_foot_horizontal_speed_ms"]
    ):
        flags.add(ClimbFlag.NON_HUMAN)
    if measure.max_vertical_rate_ms > quality["max_record_vertical_rate_ms"]:
        flags.add(ClimbFlag.SPIKE)
    if grade_unresolved(measure, climb, quality):
        flags.add(ClimbFlag.UNRESOLVED_GRADE)
    if not barometric:
        flags.add(ClimbFlag.NON_BAROMETRIC)
    if altimetric_drift:
        flags.add(ClimbFlag.ALTIMETRIC_DRIFT)
    return frozenset(flags)


def altimetric_drift(
    closure_distance_m: float,
    closure_elevation_m: float,
    duration_s: float,
    quality: ParameterSet,
) -> bool:
    """Vrai si l'activité est une boucle (arrivée à moins de
    ``loop_closure_distance_m`` du départ) dont la fermeture altimétrique, par unité
    de temps, dépasse ``max_loop_closure_rate_ms``. Un indicateur, pas une
    correction."""
    if closure_distance_m >= quality["loop_closure_distance_m"] or duration_s <= 0:
        return False
    return abs(closure_elevation_m) / duration_s > quality["max_loop_closure_rate_ms"]


def regime(
    gain_m: float,
    sport: Sport | None,
    reference_vertical_speed_ms: float,
    regimes: ParameterSet,
) -> ClimbRegime:
    """Le régime d'une montée de gain ``gain_m`` : à pied, côte, intermédiaire ou
    montée longue ; en ski de randonnée, au-dessus ou en dessous du seuil des côtes ;
    tout autre sport à part."""
    short_max = reference_vertical_speed_ms * regimes["short_climb_max_duration_s"]
    long_min = reference_vertical_speed_ms * regimes["long_climb_min_duration_s"]
    if sport is Sport.FOOT:
        if gain_m <= short_max:
            return ClimbRegime.SHORT_CLIMB
        if gain_m >= long_min:
            return ClimbRegime.LONG_CLIMB
        return ClimbRegime.INTERMEDIATE
    if sport is Sport.SKI_TOURING:
        return (
            ClimbRegime.SKI_TOURING
            if gain_m > short_max
            else ClimbRegime.SHORT_SKI_TOURING
        )
    return ClimbRegime.OTHER_SPORT


def grade_stratum(
    measure: ClimbMeasure,
    climb: ParameterSet,
    regimes: ParameterSet,
    quality: ParameterSet,
) -> GradeStratum:
    """La strate de la pente en M, ``G_M,θc / L_M`` ; « non résolue » quand la pente
    n'est pas lue (:func:`grade_unresolved`), comme le drapeau ``UNRESOLVED_GRADE``."""
    if grade_unresolved(measure, climb, quality):
        return GradeStratum.UNRESOLVED
    if measure.grade <= regimes["moderate_grade_max"]:
        return GradeStratum.MODERATE
    if measure.grade <= regimes["steep_grade_max"]:
        return GradeStratum.STEEP
    return GradeStratum.VERY_STEEP


def altitude_stratum(
    measure: ClimbMeasure, regimes: ParameterSet
) -> AltitudeStratum | None:
    """La strate d'altitude, sur l'altitude moyenne en M ; ``None`` sans temps en
    mouvement."""
    mean = measure.moving_mean_elevation_m
    if mean is None:
        return None
    if mean < regimes["low_altitude_max_m"]:
        return AltitudeStratum.LOW
    if mean < regimes["mid_altitude_max_m"]:
        return AltitudeStratum.MID
    return AltitudeStratum.HIGH
