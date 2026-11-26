"""Les constantes du modèle de la montée (AN4-2a, ``docs/decisions/0024``) : des
réglages déclarés d'un tableau de bord (charte, § 8), non les seuils d'un protocole
scellé ; recopiés dans ``0024``."""

from __future__ import annotations

from typing import Final

from mountain_perf.analyse.q2.parameters import EXCLUDED_FLAGS as _Q2_EXCLUDED_FLAGS
from mountain_perf.schemas.processed import ClimbFlag, ClimbRegime

ASCENT_REGIMES: Final[tuple[ClimbRegime, ...]] = (
    ClimbRegime.LONG_CLIMB,
    ClimbRegime.INTERMEDIATE,
)
"""Les régimes gardés : montées longues et intermédiaires (rdw, 2026-11-23, cadrage)."""

MIN_HEART_RATE_COVERAGE: Final = 0.8
"""Couverture minimale (fraction) de la FC décalée d'une montée (rdw, 2026-11-23)."""

EXCLUDED_FLAGS: Final[frozenset[ClimbFlag]] = _Q2_EXCLUDED_FLAGS
"""Les six drapeaux qui écartent une montée, ceux de Q2 (le même objet ; rdw)."""

YEAR_DAYS: Final = 365
"""L'année écoulée des références, en jours (rdw, 2026-11-23, Q-93)."""

HR_STEP_BPM: Final = 5.0
"""L'arrondi des FC de référence, en bpm (rdw, 2026-11-23, Q-93)."""

ALTITUDE_STEP_M: Final = 100.0
"""L'arrondi de l'altitude de référence, en mètres (rdw, 2026-11-23, Q-94)."""

MONTH_DAYS: Final = 365.25 / 12
"""Un mois, en jours : l'unité des pentes en temps (rdw, 2026-11-23)."""

PHI_BOUNDS_DAYS: Final[tuple[float, float]] = (7.0, 365.0)
"""Les bornes de ``φ``, en jours, du REML de l'étage 1 (rdw, 2026-11-23, Q-109)."""

MIN_STRUCTURE_MULTI: Final = 10
"""Sorties à deux montées ou plus, au moins, pour l'étage 1 (rdw, 2026-11-23, Q-109)."""

MAX_VIF: Final = 10.0
"""Inflation de variance de β ou de ``g`` au-delà : « non séparable » (rdw, Q-110)."""

MAX_ALTITUDE_SE: Final = 0.05
"""Erreur type de λ (log par 1 000 m) au-delà : λ insuffisant (rdw, Q-110)."""

DEFAULT_N_DAYS: Final = 56
"""``N``, en jours, la fenêtre de l'étage 3 (rdw, 2026-11-23, Q-110)."""

MIN_SLOPE_SORTIES: Final = 3
"""Sorties minimales pour la pente de l'étage 3 (rdw, 2026-11-23, Q-110)."""

FREEZE_DAYS: Final = 28
"""Jours après la dernière sortie au-delà desquels l'étage 3 se tait (rdw, Q-84)."""

TAU_DEFAULT: Final = 0.03
"""``τ`` par défaut, en log par mois (environ 3 %/mois) (rdw, 2026-11-23, Q-112)."""

TAU_CAP: Final = 0.05
"""Le plafond de ``τ`` estimé, en log par mois (rdw, 2026-11-23, Q-112)."""

TAU_MIN_PERIODS: Final = 12
"""Périodes riches minimales pour estimer ``τ`` (rdw, 2026-11-23, Q-112)."""

TAU_MIN_SORTIES: Final = 5
"""Sorties minimales d'une période riche (rdw, 2026-11-23, Q-112 et la conception)."""

MIN_TREND_SORTIES: Final = 6
"""Sorties minimales pour la tendance de la Fenêtre (rdw, 2026-11-23, Q-113)."""

TAU_BETA: Final = 0.15
"""``τ_β``, l'écart habituel de β entre une Fenêtre et l'histoire (rdw, Q-111)."""

TAU_G: Final = 0.03
"""``τ_g``, celui de ``g``, en log par 1 000 m (rdw, 2026-11-23, Q-111)."""

BORROWED_BELOW: Final = 0.2
"""Poids de la Fenêtre pour ``g`` sous lequel G3 est « emprunté » (rdw, Q-111)."""

SCALE_FLOOR: Final = 0.01
"""Le plancher de l'échelle ``m = 2·τ``, en log par mois (rdw, 2026-11-23, Q-113)."""

SCALE_CAP: Final = 0.10
"""Le plafond de l'échelle ``m = 2·τ``, en log par mois (rdw, 2026-11-23, Q-113)."""

COLOUR_MAX_DAYS: Final = 120
"""Longueur de Fenêtre, en jours, au-delà de laquelle la tendance n'a pas de couleur."""

HR_BOUNDS_CENTILES: Final[tuple[int, int]] = (5, 95)
"""Centiles des FC de la Fenêtre qui bornent la courbe de G2 (rdw, 2026-11-22, Q-88)."""
