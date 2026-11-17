"""Les paramètres et les constantes de Q2 (AN3-3b, ``docs/decisions/0023``) : les
seuils du plan, déclarés comme ceux de Q1, et les constantes que la provenance écrit.

Un ``ParameterSet`` ne tient que des flottants : les seuils qui sont des comptes
(:data:`INTEGER_PARAMETERS`) se lisent par ``normals.integer_parameter``, qui refuse
une valeur non entière.
"""

from __future__ import annotations

from mountain_perf.schemas import ParameterSet, ParameterSpec
from mountain_perf.schemas.processed import ClimbFlag, ClimbRegime, JournalEventType

_LOW_FRACTION, _HIGH_FRACTION = 0.001, 0.999


def _fraction(name: str, default: float, description: str) -> ParameterSpec:
    return ParameterSpec(
        name, None, default, _LOW_FRACTION, _HIGH_FRACTION, description
    )


def _count(
    name: str, default: float, description: str, minimum: float = 1.0
) -> ParameterSpec:
    return ParameterSpec(name, None, default, minimum, 1_000_000.0, description)


Q2_PARAMETER_SPECS: tuple[ParameterSpec, ...] = (
    _fraction(
        "min_heart_rate_coverage", 0.8, "Couverture minimale du support de la FC."
    ),
    ParameterSpec(
        "short_climb_min_gain_s",
        "s",
        180.0,
        1.0,
        3600.0,
        "Une côte est gardée si son gain dépasse V_ref multipliée par ce temps.",
    ),
    ParameterSpec(
        "route_radius_m",
        "m",
        100.0,
        1.0,
        100_000.0,
        "Distance maximale entre départs, et entre arrivées, de deux montées d'un"
        " même parcours.",
    ),
    ParameterSpec(
        "route_max_gain_ratio",
        None,
        1.10,
        1.0,
        100.0,
        "Rapport maximal des gains de deux montées d'un même parcours.",
    ),
    _count(
        "min_route_days",
        3.0,
        "Journées minimales d'un groupe de parcours après le quatrième retrait.",
    ),
    _count("normal_window_days", 28.0, "Jours de la fenêtre de la normale de Q2."),
    _count(
        "normal_min_admitted_days", 14.0, "Jours admis minimaux de la normale de Q2."
    ),
    _count("min_residual_df", 25.0, "Budget : n − p minimal avant les retraits."),
    _count(
        "min_estimable_df",
        10.0,
        "Sous ce n − p après les retraits, la comparaison est non estimable.",
    ),
    ParameterSpec(
        "phi_min_days",
        "d",
        2.0,
        0.001,
        100_000.0,
        "Borne basse de la portée φ de la covariance des journées.",
    ),
    _fraction("alpha", 0.05, "Seuil de la famille principale."),
    _count(
        "secondary_family_size",
        5.0,
        "Taille de la famille des secondaires (Bonferroni et Holm).",
    ),
    _fraction("delta", 0.05, "Plus petit effet utile, en fraction par an."),
    ParameterSpec(
        "bounded_reading_slope_bpm_per_year",
        "bpm/an",
        2.0,
        0.0,
        1000.0,
        "Seuil de la lecture bornée, rapporté seulement.",
    ),
    _count(
        "bootstrap_draws",
        2000.0,
        "Tirages du bootstrap de b_inv, de la bande de la figure et de S14.",
    ),
    _count("power_draws", 2000.0, "Tirages par valeur de b et par scénario."),
    _fraction(
        "calibration_trigger",
        0.075,
        "Taux de faux « établi » qui déclenche la calibration.",
    ),
    _fraction("power_target_visible", 0.8, "Puissance du plus petit effet visible."),
    _fraction(
        "power_target_no_effect",
        0.9,
        "Sous cette puissance à δ, « absence d'effet utile » est hors d'atteinte.",
    ),
    _fraction(
        "power_target_undecided",
        0.5,
        "Sous cette puissance à δ aux montées longues, « non tranché » est l'issue"
        " attendue.",
    ),
    _fraction("heart_rate_reliability", 0.85, "Fiabilité de la FC du scénario (4)."),
    ParameterSpec(
        "slow_component_sd",
        None,
        0.03,
        0.000001,
        10.0,
        "Scénario (2) : écart type de la composante lente, en log.",
    ),
    ParameterSpec(
        "slow_component_days",
        "d",
        45.0,
        0.001,
        100_000.0,
        "Scénario (2) : portée de la corrélation de la composante lente.",
    ),
    _fraction("hinge_peak", 0.08, "Scénario (3) : baisse au pic de la charnière."),
    _fraction(
        "discovery_step",
        0.05,
        "Scénario (3) : marche sur la période de découverte.",
    ),
    _fraction(
        "bounds_trigger",
        0.10,
        "Écart des parts exclues entre périodes qui déclenche les bornes.",
    ),
    _count("s14_min_months", 10.0, "S14 : mois non vides minimaux.", minimum=10.0),
    _fraction("spline_knot_low", 0.10, "Quantile du premier nœud de la spline de FC."),
    _fraction("spline_knot_mid", 0.50, "Quantile du nœud du milieu de la spline."),
    _fraction("spline_knot_high", 0.90, "Quantile du dernier nœud de la spline."),
    _count(
        "optimistic_below_days",
        40.0,
        "Sous ce nombre de journées, l'intervalle se dit « optimiste ».",
    ),
)
"""Les seuils du plan de Q2 (``docs/decisions/0023``), dans l'ordre du brief."""

INTEGER_PARAMETERS: tuple[str, ...] = (
    "min_route_days",
    "normal_window_days",
    "normal_min_admitted_days",
    "min_residual_df",
    "min_estimable_df",
    "secondary_family_size",
    "bootstrap_draws",
    "power_draws",
    "s14_min_months",
    "optimistic_below_days",
)
"""Les seuils qui sont des comptes, lus par ``normals.integer_parameter``."""


def q2_parameters() -> ParameterSet:
    """Les seuils de Q2, à leurs valeurs par défaut (``mperf q2`` les lit ici ; les
    tests de la commande remplacent cette fonction pour réduire les tirages)."""
    return ParameterSet(Q2_PARAMETER_SPECS)


Q2_ROOT_SEED = 20261115
"""La graine racine de Q2 : une constante du code, écrite dans la provenance, sans
option pour la changer (Q-35)."""

Q2_REGIMES: tuple[ClimbRegime, ...] = (
    ClimbRegime.LONG_CLIMB,
    ClimbRegime.SHORT_CLIMB,
    ClimbRegime.SKI_TOURING,
)
"""Les régimes de Q2, dans leur ordre."""

EXCLUDED_FLAGS: frozenset[ClimbFlag] = frozenset(
    {
        ClimbFlag.NON_HUMAN,
        ClimbFlag.SPIKE,
        ClimbFlag.UNRESOLVED_GRADE,
        ClimbFlag.NON_BAROMETRIC,
        ClimbFlag.ALTIMETRIC_DRIFT,
        ClimbFlag.GAIN_OUTSIDE_MOVING,
    }
)
"""Les drapeaux qui excluent une montée ; ``slow_moving`` n'y est pas."""

EXCLUDING_JOURNAL_TYPES: frozenset[JournalEventType] = frozenset(
    {
        JournalEventType.ILLNESS,
        JournalEventType.INJURY,
        JournalEventType.ALTITUDE_STAY,
    }
)
"""Les types du journal qui excluent les activités du jour."""

HINGE_DAYS: tuple[int, int, int] = (150, 200, 250)
"""Les jours de l'année de la charnière du scénario (3) : départ, pic, retour."""

AUTOCORRELATION_CLASSES: tuple[tuple[int, int | None], ...] = (
    (1, 7),
    (8, 14),
    (15, 28),
    (29, 56),
    (57, None),
)
"""Les classes d'écart, en jours, de l'autocorrélation des résidus (Q-37 (d))."""

SCENARIO_ONE_FRACTIONS: tuple[float, ...] = (
    0.0,
    0.01,
    0.02,
    0.03,
    0.04,
    0.05,
    0.075,
    0.10,
    0.15,
    0.20,
)
"""Les effets du scénario (1), en fraction par an (Q-36) ; ``delta`` s'y ajoute à sa
place s'il n'y est pas (Q-50 (e))."""

ALPHA_FACTORS: tuple[float, ...] = (1.0, 0.8, 0.6, 0.5, 0.4, 0.3, 0.2, 0.1)
"""La grille des seuils de la calibration, en multiples du seuil nominal
(Q-49 (l))."""

FIGURE_KNOT_QUANTILES: tuple[float, float, float] = (0.25, 0.5, 0.75)
"""Les quantiles des nœuds intérieurs de la courbe de la figure (avec le minimum et le
maximum : cinq nœuds, « 4 ddl »)."""
