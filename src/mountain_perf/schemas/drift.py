"""Contrats du diagnostic de longue course (M4d-1).

Protocole : ``docs/decisions/0010`` D12 (et ses précisions de M4d-1), D4.12, D5.3, D6,
D7.3, D9.2. Pour une sortie scorée avec usage, la séquence des éléments observés du
``K`` par défaut (commune aux horloges, arrivée comprise), les intervalles départ →
départ depuis l'origine, la pente descriptive de ``y_h = ln(t_h / p_h)`` sur
l'avancement ``u_h`` avec les fractions de régime en nuisance, ses retraits, l'influence
de chaque intervalle et les cumuls ``C_k`` et ``B_k`` — par modèle et par horloge du
rapport.

**Contrats non stockés** : le diagnostic se calcule pendant l'exécution de ``just
backtest`` et ne s'écrit qu'au rapport complet ; aucun document du registre ne les
porte (décision Q4 (e) de M4d).

Aucun calcul ici hors la vérification des invariants : les producteurs vivent dans
``mountain_perf.backtest.drift``.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from mountain_perf.schemas.calibration import ModelKind
from mountain_perf.schemas.clock import CLOCKS, Clock, ClockKind
from mountain_perf.schemas.matching import Regime
from mountain_perf.schemas.metrics import METRIC_RELATIVE_TOLERANCE
from mountain_perf.schemas.outing import Unavailability
from mountain_perf.schemas.scoring import OBSERVATION_UNAVAILABILITY
from mountain_perf.validation import (
    ContractError,
    require_finite,
    require_immutable_sequence,
)

DRIFT_RANK_TOLERANCE = 1e-10
"""Tolérance relative du rang de la base des nuisances : une valeur singulière compte si
elle dépasse ``1e−10`` fois la plus grande (``0010`` D12)."""

DRIFT_IDENTIFICATION_THRESHOLD = 1e-10
"""La pente est identifiable si ``rho_u > 1e−10`` (``0010`` D12)."""

DRIFT_WEAK_SEPARATION = 0.10
"""Sous ce ``rho_u``, le rapport écrit « faible séparation position/régimes » (arbitrage
E4 de M4d) : une constante de présentation, pas un seuil statistique. ``1 / rho_u`` est
l'amplification de la variance de la pente par les nuisances, sous l'hypothèse
d'erreurs indépendantes de même variance ; sous ``0,10``, elle dépasse 10."""

DRIFT_REGIMES: tuple[Regime, ...] = (Regime.ASCENT, Regime.FLAT, Regime.DESCENT)
"""L'ordre des fractions de régime d'un intervalle, et du départage de ``R_0``
(``0010`` D12 : montée, plat, descente)."""

DRIFT_UNAVAILABILITIES: tuple[Unavailability, ...] = (
    Unavailability.MULTI_OUTING_DAY,
    Unavailability.INSUFFICIENT_SUPPORT,
    Unavailability.NOT_CALIBRATED,
    Unavailability.MODEL_ERROR,
    Unavailability.ZERO_TIME,
)
"""Les motifs d'un diagnostic indisponible (``0010`` D0, D12 ; précisions de M4d-1)."""

_TAU = METRIC_RELATIVE_TOLERANCE


def _close(x: float, y: float) -> bool:
    return abs(x - y) <= _TAU * max(1.0, abs(x), abs(y))


@dataclass(frozen=True)
class DriftInterval:
    """Un intervalle ``h`` de la séquence, départ → départ (``0010`` D12 ; précisions
    de M4d-1).

    Champs
    ------
    - ``start_m``, ``end_m`` — mètres — abscisses de la référence : ``b_0`` ou l'élément
      précédent, puis l'élément ``h``.
    - ``observed_s`` — secondes — ``t_h = T_h − T_{h−1}`` sous l'horloge (``T_0 = 0``).
    - ``projected_s`` — secondes — ``p_h = P_h − P_{h−1}`` du modèle.
    - ``log_ratio`` — sans unité — ``y_h = ln(t_h / p_h)``, **positif = plus long que
      prévu** ; absent si ``t_h <= 0``.
    - ``position`` — sans unité — ``u_h = (P⁰_{h−1} + p⁰_h / 2) / P⁰_H``, de v0 brut.
    - ``fractions`` — sans unité — ``f_hR`` de v0 brut, dans l'ordre de
      ``DRIFT_REGIMES`` : la part du temps projeté de chaque régime de D6 sur la grille
      fine, rapportée à leur somme (``p⁰_h`` aux arrondis près).
    - ``moving_s``, ``stop_s`` — secondes — sous l'écoulé seulement : déplacement
      ``A_h − D_{h−1}`` et arrêt ``D_h − A_h`` ; absents sous une autre horloge.

    Propriété calculée (jamais stockée) : ``local_error_min`` = ``(t_h − p_h) / 60``.

    Invariants
    ----------
    1. toutes les valeurs présentes finies ; ``start_m < end_m`` ; ``projected_s > 0`` ;
    2. ``log_ratio`` présent si et seulement si ``observed_s > 0``, et alors à ``τ``
       près de ``ln(observed_s / projected_s)`` (``τ = METRIC_RELATIVE_TOLERANCE``) ;
    3. ``0 < position < 1`` ;
    4. ``fractions`` : un tuple de trois valeurs de ``[0 ; 1]``, de somme 1 à ``τ``
       près ;
    5. ``moving_s`` et ``stop_s`` tous deux présents ou tous deux absents ; présents :
       ``stop_s >= 0`` et ``moving_s + stop_s`` à ``τ`` près de ``observed_s``.

    Producteur
    ----------
    ``drift_diagnostic`` (``mountain_perf.backtest.drift``).

    Consommateurs
    -------------
    ``DriftDiagnostic`` ; le rapport de ``just backtest`` (``cli.py``).

    Non promis
    ----------
    - les abscisses ne sont pas recoupées avec la référence ni avec ``K`` ;
    - ``position`` et ``fractions`` ne sont pas recoupées avec v0 ;
    - n'est pas un contrat stocké.
    """

    start_m: float
    end_m: float
    observed_s: float
    projected_s: float
    log_ratio: float | None
    position: float
    fractions: tuple[float, float, float]
    moving_s: float | None
    stop_s: float | None

    def __post_init__(self) -> None:
        for name in ("start_m", "end_m", "observed_s", "projected_s", "position"):
            require_finite(getattr(self, name), name)
        if not self.start_m < self.end_m:
            raise ContractError(
                f"start_m ({self.start_m}) doit être < end_m ({self.end_m})."
            )
        if not self.projected_s > 0:
            raise ContractError(f"projected_s doit être > 0, reçu {self.projected_s}.")
        if (self.log_ratio is not None) != (self.observed_s > 0):
            raise ContractError(
                "log_ratio doit être présent si et seulement si observed_s > 0 "
                f"(observed_s {self.observed_s})."
            )
        if self.log_ratio is not None:
            require_finite(self.log_ratio, "log_ratio")
            expected = math.log(self.observed_s / self.projected_s)
            if not _close(self.log_ratio, expected):
                raise ContractError(
                    f"log_ratio ({self.log_ratio}) doit valoir ln(observed_s / "
                    f"projected_s) ({expected})."
                )
        if not 0 < self.position < 1:
            raise ContractError(
                f"position doit être dans ]0 ; 1[, reçu {self.position}."
            )
        require_immutable_sequence(self.fractions, "fractions")
        if len(self.fractions) != len(DRIFT_REGIMES):
            raise ContractError(
                f"fractions doit porter {len(DRIFT_REGIMES)} valeurs, reçu "
                f"{len(self.fractions)}."
            )
        for i, value in enumerate(self.fractions):
            require_finite(value, f"fractions[{i}]")
            if not 0 <= value <= 1:
                raise ContractError(
                    f"fractions[{i}] doit être dans [0 ; 1], reçu {value}."
                )
        if not _close(math.fsum(self.fractions), 1.0):
            raise ContractError(
                f"fractions doit sommer à 1, reçu {math.fsum(self.fractions)}."
            )
        if (self.moving_s is None) != (self.stop_s is None):
            raise ContractError("moving_s et stop_s : tous deux présents ou absents.")
        if self.moving_s is not None and self.stop_s is not None:
            require_finite(self.moving_s, "moving_s")
            require_finite(self.stop_s, "stop_s")
            if self.stop_s < 0:
                raise ContractError(f"stop_s doit être >= 0, reçu {self.stop_s}.")
            if not _close(self.moving_s + self.stop_s, self.observed_s):
                raise ContractError(
                    f"moving_s + stop_s ({self.moving_s + self.stop_s}) doit valoir "
                    f"observed_s ({self.observed_s})."
                )

    @property
    def local_error_min(self) -> float:
        """L'erreur locale ``(t_h − p_h) / 60`` (minutes, ``0010`` D12)."""
        return (self.observed_s - self.projected_s) / 60.0


@dataclass(frozen=True)
class DriftFit:
    """Un ajustement de la pente de dérive sur un ensemble d'intervalles (``0010``
    D12).

    Champs
    ------
    - ``slope`` — sans unité — ``b = (M_Z u)ᵀ y / ‖M_Z u‖²`` ; absent si la pente n'est
      pas identifiable.
    - ``rho`` — sans unité — ``rho_u = ‖M_Z u‖² / Σ (u − ū)²`` ; absent si
      ``Σ (u − ū)² = 0``.
    - ``u_mz_u`` — sans unité — ``uᵀ M_Z u``, calculé ``‖M_Z u‖²``.
    - ``rank`` — sans unité — le rang de la base ``Z`` des nuisances.
    - ``count`` — sans unité — le nombre d'intervalles.
    - ``influence`` — sans unité — ``a_h = (M_Z u)_h / ‖M_Z u‖²`` par intervalle, dans
      l'ordre : ``b = Σ a_h y_h`` (une erreur ``δy_h`` déplace ``b`` de ``a_h δy_h``) ;
      présente avec la pente.

    Propriétés calculées (jamais stockées) : ``identifiable`` = ``slope`` présente ;
    ``dof`` = ``count − rank − 1``, les degrés de liberté résiduels (``ddl`` au
    rapport), avec la pente.

    Invariants
    ----------
    1. ``count >= 1`` ; ``1 <= rank <= min(count, len(DRIFT_REGIMES))`` ;
    2. ``u_mz_u`` fini et ``>= 0`` ; ``rho`` absent, ou fini et ``>= 0`` ;
    3. ``slope`` présente si et seulement si ``rho`` est présent,
       ``rho > DRIFT_IDENTIFICATION_THRESHOLD`` et ``rank < count`` ; présente, finie ;
    4. ``influence`` présente si et seulement si ``slope`` l'est ; un tuple de ``count``
       valeurs finies.

    Producteur
    ----------
    ``drift_fit`` (``mountain_perf.backtest.drift``).

    Consommateurs
    -------------
    ``DriftDiagnostic`` ; le rapport.

    Non promis
    ----------
    - ``rho`` n'est pas recoupé avec ``u_mz_u`` (``Σ (u − ū)²`` n'est pas publié) ;
    - aucune incertitude de ``slope`` n'est publiée ; ``1 / rho`` n'est une
      amplification de variance que sous une hypothèse d'erreurs
      (``DRIFT_WEAK_SEPARATION``) ;
    - ``slope`` est une pente descriptive : un mélange de régimes non linéaire en
      fractions, ou un arrêt sur un intervalle court, la font varier sans effet du
      temps (passe experte de M4d, D12-D et D12-E) ;
    - ``Σ a_h = 0``, ``Σ a_h u_h = 1`` et ``b = Σ a_h y_h`` ne sont vrais au calcul près
      que si la constante est dans ``Z`` : la troncature du rang (``sigma <= 1e−10
      sigma_max``) peut en écarter une part infime (oracle de M4d-1 : ``Σ a_h`` de
      l'ordre de ``1e−11``) ; ``u`` et ``y`` étant centrés, la pente garde son
      interception et son invariance au calage ;
    - n'est pas un contrat stocké.
    """

    slope: float | None
    rho: float | None
    u_mz_u: float
    rank: int
    count: int
    influence: tuple[float, ...] | None

    def __post_init__(self) -> None:
        if self.count < 1:
            raise ContractError(f"count doit être >= 1, reçu {self.count}.")
        top = min(self.count, len(DRIFT_REGIMES))
        if not 1 <= self.rank <= top:
            raise ContractError(f"rank doit être dans [1 ; {top}], reçu {self.rank}.")
        require_finite(self.u_mz_u, "u_mz_u")
        if self.u_mz_u < 0:
            raise ContractError(f"u_mz_u doit être >= 0, reçu {self.u_mz_u}.")
        if self.rho is not None:
            require_finite(self.rho, "rho")
            if self.rho < 0:
                raise ContractError(f"rho doit être >= 0, reçu {self.rho}.")
        identifiable = (
            self.rho is not None
            and self.rho > DRIFT_IDENTIFICATION_THRESHOLD
            and self.rank < self.count
        )
        if (self.slope is not None) != identifiable:
            raise ContractError(
                "slope doit être présente si et seulement si rho > "
                f"DRIFT_IDENTIFICATION_THRESHOLD et rank < count (rho {self.rho}, "
                f"rank {self.rank}, count {self.count})."
            )
        if self.slope is not None:
            require_finite(self.slope, "slope")
        self._check_influence()

    def _check_influence(self) -> None:
        if (self.influence is not None) != (self.slope is not None):
            raise ContractError(
                "influence doit être présente si et seulement si slope l'est."
            )
        if self.influence is None:
            return
        require_immutable_sequence(self.influence, "influence")
        if len(self.influence) != self.count:
            raise ContractError(
                f"influence doit porter {self.count} valeurs, reçu "
                f"{len(self.influence)}."
            )
        for i, value in enumerate(self.influence):
            require_finite(value, f"influence[{i}]")

    @property
    def identifiable(self) -> bool:
        """La pente est identifiable (``0010`` D12)."""
        return self.slope is not None

    @property
    def dof(self) -> int | None:
        """``ddl = count − rank − 1`` avec la pente ; ``None`` sans elle."""
        return self.count - self.rank - 1 if self.slope is not None else None


@dataclass(frozen=True)
class DriftDiagnostic:
    """Le diagnostic de longue course d'une sortie, pour un modèle et une horloge
    (``0010`` D12 ; précisions de M4d-1).

    Champs
    ------
    - ``model`` — sans unité — le modèle évalué (les cinq de D9.1).
    - ``clock`` — sans unité — l'horloge des temps observés.
    - ``intervals`` — sans unité — les intervalles de la séquence, dans l'ordre.
    - ``reference_regime`` — sans unité — ``R_0`` : le régime de plus grand temps
      projeté total (égalités dans l'ordre de ``DRIFT_REGIMES``).
    - ``cumulative_errors_s`` — secondes — ``C_k = P_k − T_k`` à chaque élément.
    - ``recentred_s`` — secondes — ``B_k = T_k − c·P_k``, ``c = T_H / P_H``.
    - ``fit`` — sans unité — l'ajustement sur tous les intervalles.
    - ``withdrawals`` — sans unité — un ajustement par intervalle retiré, dans l'ordre.
    - ``slope_range`` — sans unité — ``(min b ; max b)`` des retraits identifiables ;
      absent s'il n'y en a aucun.
    - ``unavailability`` — sans unité — le motif d'un diagnostic indisponible (dans
      ``DRIFT_UNAVAILABILITIES``), ou absent.

    Invariants
    ----------
    1. ``model`` est l'un des cinq modèles de D9.1 ; ``clock`` dans ``CLOCKS`` ;
    2. tuples ; ``cumulative_errors_s`` et ``recentred_s`` finis ;
    3. ``unavailability`` absent ou dans ``DRIFT_UNAVAILABILITIES`` ;
    4. ``ZERO_TIME`` : des intervalles, l'un au moins de temps observé ``<= 0`` ; ni
       ajustement, ni retraits, ni étendue ; les autres motifs : aucun intervalle,
       aucun cumul, ni ``R_0``, ni ajustement, ni retraits, ni étendue ;
    5. disponible : des intervalles, tous de temps observé ``> 0`` ; ``R_0`` présent ;
       ``fit`` présent, ``fit.count`` égal au nombre d'intervalles ; un retrait par
       intervalle s'il y en a au moins deux (aucun sinon), chacun de ``count``
       ``H − 1`` ; ``slope_range`` égal, au bit, au minimum et au maximum des pentes
       des retraits identifiables, absent s'il n'y en a aucun ;
    6. des intervalles : ``R_0`` présent ; ``cumulative_errors_s`` et ``recentred_s``
       d'autant de valeurs ; le dernier ``B_k`` à ``τ`` près de 0 ;
    7. sous l'écoulé, chaque intervalle porte déplacement et arrêt ; sous une autre
       horloge, aucun.

    Producteur
    ----------
    ``drift_diagnostic``, ``outing_drift`` (``mountain_perf.backtest.drift``).

    Consommateurs
    -------------
    ``OutingDrift`` ; le rapport de ``just backtest``.

    Non promis
    ----------
    - les intervalles ne sont pas recoupés entre eux (continuité des abscisses) ;
    - ``C_k`` et ``B_k`` ne sont pas recoupés avec les intervalles ;
    - n'est pas un contrat stocké.
    """

    model: ModelKind
    clock: Clock
    intervals: tuple[DriftInterval, ...]
    reference_regime: Regime | None
    cumulative_errors_s: tuple[float, ...]
    recentred_s: tuple[float, ...]
    fit: DriftFit | None
    withdrawals: tuple[DriftFit, ...]
    slope_range: tuple[float, float] | None
    unavailability: Unavailability | None

    def __post_init__(self) -> None:
        if self.model is ModelKind.CANDIDATE:
            raise ContractError("model doit être l'un des cinq modèles de D9.1.")
        if self.clock not in CLOCKS:
            raise ContractError(
                f"clock n'est pas une des onze horloges : {self.clock}."
            )
        for name in ("intervals", "cumulative_errors_s", "recentred_s", "withdrawals"):
            require_immutable_sequence(getattr(self, name), name)
        for name in ("cumulative_errors_s", "recentred_s"):
            for i, value in enumerate(getattr(self, name)):
                require_finite(value, f"{name}[{i}]")
        if self.unavailability is not None and (
            self.unavailability not in DRIFT_UNAVAILABILITIES
        ):
            raise ContractError(
                f"unavailability doit être dans DRIFT_UNAVAILABILITIES, reçu "
                f"{self.unavailability}."
            )
        self._check_shape()
        self._check_clock()

    def _check_shape(self) -> None:
        count = len(self.intervals)
        no_fit = self.fit is None and not self.withdrawals and self.slope_range is None
        if self.unavailability is Unavailability.ZERO_TIME:
            if not count or all(iv.observed_s > 0 for iv in self.intervals):
                raise ContractError(
                    "ZERO_TIME : des intervalles, l'un au moins de temps observé <= 0."
                )
            if not no_fit:
                raise ContractError(
                    "ZERO_TIME : ni ajustement, ni retraits, ni étendue."
                )
        elif self.unavailability is not None:
            if count or self.cumulative_errors_s or self.recentred_s:
                raise ContractError(
                    f"{self.unavailability} : aucun intervalle ni cumul."
                )
            if self.reference_regime is not None or not no_fit:
                raise ContractError(
                    f"{self.unavailability} : ni R_0, ni ajustement, ni retraits."
                )
            return
        else:
            self._check_available(count)
        if self.reference_regime is None:
            raise ContractError("R_0 doit être présent quand il y a des intervalles.")
        if len(self.cumulative_errors_s) != count or len(self.recentred_s) != count:
            raise ContractError(
                "cumulative_errors_s et recentred_s : une valeur par intervalle."
            )
        if not _close(self.recentred_s[-1], 0.0):
            raise ContractError(
                f"le dernier B_k doit valoir 0, reçu {self.recentred_s[-1]}."
            )

    def _check_available(self, count: int) -> None:
        if not count:
            raise ContractError("un diagnostic disponible a des intervalles.")
        if any(iv.observed_s <= 0 for iv in self.intervals):
            raise ContractError("disponible : tous les temps observés > 0.")
        if self.fit is None or self.fit.count != count:
            raise ContractError("fit doit porter tous les intervalles.")
        expected = count if count > 1 else 0
        if len(self.withdrawals) != expected:
            raise ContractError(
                f"withdrawals doit porter {expected} ajustements, reçu "
                f"{len(self.withdrawals)}."
            )
        if any(w.count != count - 1 for w in self.withdrawals):
            raise ContractError("chaque retrait porte H − 1 intervalles.")
        slopes = [w.slope for w in self.withdrawals if w.slope is not None]
        expected_range = (min(slopes), max(slopes)) if slopes else None
        if self.slope_range != expected_range:
            raise ContractError(
                f"slope_range ({self.slope_range}) doit valoir {expected_range}."
            )

    def _check_clock(self) -> None:
        elapsed = self.clock.kind is ClockKind.ELAPSED
        for i, interval in enumerate(self.intervals):
            if (interval.moving_s is not None) != elapsed:
                raise ContractError(
                    f"intervals[{i}] : déplacement et arrêt sous l'écoulé seulement."
                )


@dataclass(frozen=True)
class OutingDrift:
    """Le diagnostic de longue course d'une sortie scorée avec usage : la séquence,
    commune aux horloges, et un ``DriftDiagnostic`` par horloge du rapport et par modèle
    (``0010`` D12 ; précisions de M4d-1, arbitrages E1 et E2).

    Champs
    ------
    - ``outing_id`` — sans unité — la sortie.
    - ``targets`` — sans unité — le nombre d'éléments du ``K`` par défaut.
    - ``elements`` — sans unité — ``H``, la longueur de la séquence : les éléments de
      ``K`` observés, dans l'ordre, jusqu'au premier qui ne l'est pas, arrivée comprise.
    - ``stop`` — sans unité — le motif d'observation du premier élément non retenu (de
      rang ``elements``), absent si tout ``K`` l'est.
    - ``horizon_s`` — secondes — ``P⁰_H``, le cumul de v0 brut au dernier élément ;
      absent sans élément ou sans prévision de v0 brut.
    - ``diagnostics`` — sans unité — pour chaque horloge du rapport, dans l'ordre
      (écoulé, ``M`` sous ``θ_bas``, ``M + U`` sous ``θ_haut``), les cinq modèles dans
      l'ordre de ``DRIFT_MODELS``.

    Invariants
    ----------
    1. ``outing_id`` non vide ; ``targets >= 1`` ; ``0 <= elements <= targets`` ;
    2. ``stop`` absent si et seulement si ``elements == targets`` ; présent, dans
       ``OBSERVATION_UNAVAILABILITY`` ;
    3. ``horizon_s`` absent ou fini et ``> 0`` ; absent si ``elements == 0`` ;
    4. ``diagnostics`` un tuple non vide ; par groupe de cinq consécutifs, une même
       horloge et les cinq modèles dans l'ordre ; des horloges distinctes, l'écoulé
       d'abord ;
    5. un diagnostic qui a des intervalles en a ``elements``.

    Producteur
    ----------
    ``outing_drift`` (``mountain_perf.backtest.drift``).

    Consommateurs
    -------------
    Le rapport de ``just backtest``.

    Non promis
    ----------
    - les horloges ne sont pas recoupées avec celles du rapport de la sortie ;
    - ``horizon_s`` n'est pas recoupé avec les intervalles ;
    - n'est pas un contrat stocké.
    """

    outing_id: str
    targets: int
    elements: int
    stop: Unavailability | None
    horizon_s: float | None
    diagnostics: tuple[DriftDiagnostic, ...]

    def __post_init__(self) -> None:
        if not self.outing_id:
            raise ContractError("outing_id ne doit pas être vide.")
        if self.targets < 1:
            raise ContractError(f"targets doit être >= 1, reçu {self.targets}.")
        if not 0 <= self.elements <= self.targets:
            raise ContractError(
                f"elements doit être dans [0 ; {self.targets}], reçu {self.elements}."
            )
        if (self.stop is None) != (self.elements == self.targets):
            raise ContractError(
                "stop doit être absent si et seulement si tout K est retenu."
            )
        if self.stop is not None and self.stop not in OBSERVATION_UNAVAILABILITY:
            raise ContractError(
                f"stop doit être un motif d'observation, reçu {self.stop}."
            )
        if self.horizon_s is not None:
            require_finite(self.horizon_s, "horizon_s")
            if self.horizon_s <= 0 or self.elements == 0:
                raise ContractError(
                    "horizon_s : > 0, et seulement avec au moins un élément."
                )
        self._check_diagnostics()

    def _check_diagnostics(self) -> None:
        require_immutable_sequence(self.diagnostics, "diagnostics")
        size = len(DRIFT_MODELS)
        if not self.diagnostics or len(self.diagnostics) % size:
            raise ContractError(
                f"diagnostics doit porter un multiple non nul de {size} diagnostics, "
                f"reçu {len(self.diagnostics)}."
            )
        clocks = []
        for start in range(0, len(self.diagnostics), size):
            group = self.diagnostics[start : start + size]
            clock = group[0].clock
            if any(d.clock != clock for d in group):
                raise ContractError("un groupe de diagnostics porte une seule horloge.")
            if tuple(d.model for d in group) != DRIFT_MODELS:
                raise ContractError("les cinq modèles, dans l'ordre de DRIFT_MODELS.")
            clocks.append(clock)
        if len(set(clocks)) != len(clocks) or clocks[0] != CLOCKS[0]:
            raise ContractError("des horloges distinctes, l'écoulé d'abord.")
        for d in self.diagnostics:
            if d.intervals and len(d.intervals) != self.elements:
                raise ContractError(
                    f"un diagnostic porte {len(d.intervals)} intervalles, la séquence "
                    f"{self.elements}."
                )


DRIFT_MODELS: tuple[ModelKind, ...] = (
    ModelKind.V0_RAW,
    ModelKind.V0_RECALIBRATED,
    ModelKind.CONSTANT_SPEED,
    ModelKind.NAISMITH,
    ModelKind.TOBLER,
)
"""Les modèles du diagnostic, dans l'ordre du rapport (``0010`` D9.1, D15)."""
