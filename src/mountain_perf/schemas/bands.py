"""Contrats des fourchettes : réservoir, résidus, quantiles, bornes, score d'intervalle,
couverture (M4d-2).

Protocole : ``docs/decisions/0010`` D11 (et sa précision de M4d-2), D2.2, D2.4, D7.3,
D7.4, D9.2, D14 (format 4). Pour une sortie scorée avec usage d'une performance ``j``
et chacun des cinq modèles du rapport : les résidus de jour ``Z_c = ln(T_c / P_c)`` des
membres ``c`` de ``C_j`` (le réservoir), leurs quantiles empiriques, et pour chaque
élément du ``K`` par défaut de ``j`` la fourchette ``[P_k e^{Q_0,1} ; P_k e^{Q_0,9}]``,
sa médiane et sa lecture prudente, le score d'intervalle et la couverture.

Contrats **stockés** (format 4) : un document ``OutingBands`` par sortie scorée avec
usage, cité par le RÉSULTAT de ``just backtest``. Aucun calcul ici hors la vérification
des invariants : les producteurs vivent dans ``mountain_perf.backtest.bands``.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from itertools import pairwise

from mountain_perf.schemas.calibration import CALIBRATED_MODELS, ModelKind
from mountain_perf.schemas.metrics import (
    METRIC_RELATIVE_TOLERANCE,
    WEIGHT_SUM_TOLERANCE,
    MetricValue,
)
from mountain_perf.schemas.outing import Unavailability
from mountain_perf.schemas.scoring import OBSERVATION_UNAVAILABILITY
from mountain_perf.validation import (
    ContractError,
    require_finite,
    require_immutable_sequence,
    require_non_empty,
)

BAND_LABEL = "plage de scénarios — calibration non disponible"
"""L'étiquette obligatoire des fourchettes (``0010`` D11), tant qu'aucune calibration
indépendante n'existe ; chaque document la porte."""

BAND_ALPHA = 0.2
"""``alpha`` de la fourchette (``0010`` D11) : quantiles ``alpha/2`` et
``1 − alpha/2``."""

BAND_PENALTY = 10.0
"""``2/alpha`` : le poids d'un dépassement dans le score d'intervalle (``0010``
D11)."""

BAND_QUANTILE_ORDERS: tuple[tuple[int, int], ...] = ((1, 10), (1, 2), (2, 3), (9, 10))
"""Les ordres des quantiles publiés, en fractions exactes ``(a, b)`` pour ``a/b`` : bas
(0,1), médiane (0,5), lecture prudente (2/3), haut (0,9)."""

BAND_MODELS: tuple[ModelKind, ...] = (ModelKind.V0_RAW, *CALIBRATED_MODELS)
"""Les cinq modèles d'un document de fourchettes, dans l'ordre du rapport (D9.1)."""

MEMBER_UNAVAILABILITY: frozenset[Unavailability] = frozenset(
    {Unavailability.INSUFFICIENT_SUPPORT, Unavailability.ZERO_TIME}
)
"""Les motifs d'observation d'un membre du réservoir (précision de D9.2)."""

RESIDUAL_UNAVAILABILITY: frozenset[Unavailability] = frozenset(
    {*MEMBER_UNAVAILABILITY, Unavailability.MODEL_ERROR, Unavailability.NOT_CALIBRATED}
)
"""Les motifs d'un résidu indisponible : ceux du membre, puis ceux du modèle."""

BAND_UNAVAILABILITY: frozenset[Unavailability] = frozenset(
    {
        Unavailability.INSUFFICIENT_SUPPORT,
        Unavailability.MODEL_ERROR,
        Unavailability.NOT_CALIBRATED,
    }
)
"""Les statuts d'une fourchette sans bornes (précision de D11, M4d-2)."""


def _close(value: float, expected: float) -> bool:
    """``value`` vaut ``expected`` à ``τ·max(1, |expected|)`` près, ``τ`` =
    ``METRIC_RELATIVE_TOLERANCE``, comme le calage (``exp`` dépend de la plateforme)."""
    return abs(value - expected) <= METRIC_RELATIVE_TOLERANCE * max(1.0, abs(expected))


def _rank(count: int, numerator: int, denominator: int) -> int:
    """``⌈count · numerator / denominator⌉``, en entiers (précision de D11)."""
    return (count * numerator + denominator - 1) // denominator


def _interval_score(lower: float, upper: float, observed: float) -> float:
    """``IS = (u − l) + 10 (l − T)₊ + 10 (T − u)₊``, sommé par ``fsum``."""
    return math.fsum(
        (
            upper - lower,
            BAND_PENALTY * max(lower - observed, 0.0),
            BAND_PENALTY * max(observed - upper, 0.0),
        )
    )


@dataclass(frozen=True)
class ReservoirMember:
    """Un membre ``c`` du réservoir de ``j`` (``0010`` D2.4, D11 ; précision de D9.2),
    indépendant du modèle.

    Champs
    ------
    - ``civil_date`` — jour civil — le jour de ``c``.
    - ``in_window`` — sans unité — ``c`` est dans la fenêtre de la courbe (D2.2).
    - ``outing_count`` — sans unité — ses sorties scorées qui ont l'usage (les sorties
      contributrices).
    - ``segment_count`` — sans unité — les segments admis de ces sorties.
    - ``support_m`` — mètres — leur longueur sur la référence.
    - ``observed_s`` — secondes — ``T_c``, sous l'écoulé.
    - ``unavailability`` — sans unité — ``support insuffisant`` (aucun segment) ou
      ``temps nul`` (``T_c = 0``).

    Invariants
    ----------
    1. ``outing_count``, ``segment_count`` ``>= 0`` ; un segment au moins ⇒ une sortie
       au moins ;
    2. ``support_m`` fini, nul sans segment, ``> 0`` sinon ;
    3. exactement un de ``observed_s`` et ``unavailability`` ; ``observed_s`` fini et
       ``> 0`` ; ``unavailability`` dans ``MEMBER_UNAVAILABILITY`` ;
    4. ``support insuffisant`` si et seulement si aucun segment.

    Producteur
    ----------
    ``reservoir_member`` (``mountain_perf.backtest.bands``).

    Consommateurs
    -------------
    ``OutingBands`` ; le rapport (M4d-2).

    Non promis
    ----------
    - ``in_window`` n'est recoupé avec la fenêtre que par ``OutingBands`` ;
    - les régimes du support ne sont pas portés : l'observation de ``c`` les a.
    """

    civil_date: date
    in_window: bool
    outing_count: int
    segment_count: int
    support_m: float
    observed_s: float | None
    unavailability: Unavailability | None

    def __post_init__(self) -> None:
        for name in ("outing_count", "segment_count"):
            value: int = getattr(self, name)
            if value < 0:
                raise ContractError(f"{name} doit être >= 0, reçu {value}.")
        if self.segment_count > 0 and self.outing_count == 0:
            raise ContractError(
                "des segments admis viennent d'une sortie contributrice au moins, reçu "
                f"{self.segment_count} segments et aucune sortie."
            )
        require_finite(self.support_m, "support_m")
        if (self.segment_count == 0) != (self.support_m == 0):
            raise ContractError(
                "support_m est nul si et seulement s'il n'y a aucun segment, reçu "
                f"{self.support_m} m pour {self.segment_count} segments."
            )
        if self.support_m < 0:
            raise ContractError(f"support_m doit être >= 0, reçu {self.support_m}.")
        if (self.observed_s is None) == (self.unavailability is None):
            raise ContractError(
                "exactement un de observed_s et unavailability doit être présent, reçu "
                f"observed_s={self.observed_s}, unavailability={self.unavailability}."
            )
        if self.observed_s is not None:
            require_finite(self.observed_s, "observed_s")
            if not self.observed_s > 0:
                raise ContractError(
                    f"observed_s doit être > 0, reçu {self.observed_s}."
                )
        motif = self.unavailability
        if motif is not None and motif not in MEMBER_UNAVAILABILITY:
            raise ContractError(f"motif d'un membre hors de la liste : {motif}.")
        if (motif is Unavailability.INSUFFICIENT_SUPPORT) != (self.segment_count == 0):
            raise ContractError(
                "support insuffisant si et seulement si aucun segment admis, reçu "
                f"{motif} pour {self.segment_count} segments."
            )

    @property
    def available(self) -> bool:
        """Le membre a un support et un temps (``unavailability is None``)."""
        return self.unavailability is None


@dataclass(frozen=True)
class BandQuantiles:
    """Les quantiles empiriques des résidus disponibles (``0010`` D11 ; précision de
    M4d-2).

    Champs
    ------
    - ``low``, ``median``, ``prudent``, ``high`` — sans unité (log-rapport) —
      ``Q_0,1``, ``Q_0,5`` (inférieure centrale si ``n`` pair), ``Q_2/3`` et
      ``Q_0,9`` : la statistique d'ordre de rang ``⌈n q⌉`` (à partir de 1).

    Invariants
    ----------
    Finis ; ``low <= median <= prudent <= high``.

    Producteur
    ----------
    ``band_quantiles`` (``mountain_perf.backtest.bands``).

    Consommateurs
    -------------
    ``ModelBand`` ; le rapport (M4d-2).

    Non promis
    ----------
    Ce sont des rangs, pas des niveaux de confiance : aucune couverture de 80 % n'est
    promise (D11, passe experte D11-F).
    """

    low: float
    median: float
    prudent: float
    high: float

    def __post_init__(self) -> None:
        values = (self.low, self.median, self.prudent, self.high)
        for name, value in zip(
            ("low", "median", "prudent", "high"), values, strict=True
        ):
            require_finite(value, name)
        for previous, current in pairwise(values):
            if not previous <= current:
                raise ContractError(
                    "les quantiles sont dans l'ordre low <= median <= prudent <= high, "
                    f"reçu {values}."
                )

    @property
    def values(self) -> tuple[float, float, float, float]:
        """Les quatre quantiles, dans l'ordre de ``BAND_QUANTILE_ORDERS``."""
        return (self.low, self.median, self.prudent, self.high)


@dataclass(frozen=True)
class BandElement:
    """La fourchette d'un élément ``k`` du ``K`` par défaut de ``j`` (``0010`` D11,
    D7.4 ; précision de M4d-2).

    Champs
    ------
    - ``forecast_s`` — secondes — ``P_k``, le cumul du modèle depuis ``b_0``, calé à
      ``o_j``.
    - ``weight`` — sans unité — ``w_k`` (D7.4, proportionnel à ``P⁰_k``).
    - ``base_s`` — secondes — ``P⁰_k``, le cumul de v0 brut.
    - ``lower_s``, ``median_s``, ``prudent_s``, ``upper_s`` — secondes — ``P_k e^{Q}``
      pour les quatre quantiles.
    - ``width_s`` — secondes — ``u_k − l_k``.
    - ``observed_s`` — secondes — ``T_k`` sous l'écoulé, aux départs (D4.12).
    - ``observation`` — sans unité — le motif d'un élément non observé.
    - ``score_s`` — secondes — ``IS_k``.
    - ``covered`` — sans unité — ``l_k <= T_k <= u_k`` ; absent si l'élément n'est pas
      observé, ou si ``n = 1``.

    Invariants
    ----------
    1. ``forecast_s``, ``base_s`` finis et ``> 0`` ; ``weight`` fini et ``>= 0`` ;
    2. bornes finies, ``0 < lower_s <= median_s <= prudent_s <= upper_s`` ;
       ``width_s == upper_s − lower_s`` au bit ;
    3. exactement un de ``observed_s`` et ``observation`` ; ``observed_s`` fini et
       ``>= 0`` ; ``observation`` dans ``OBSERVATION_UNAVAILABILITY`` ;
    4. ``score_s`` présent si et seulement si l'élément est observé, et alors fini et
       égal **au bit** à ``fsum((u − l), 10 (l − T)₊, 10 (T − u)₊)`` ;
    5. ``covered`` présent ⇒ l'élément est observé, et ``covered == (l <= T <= u)``.

    Producteur
    ----------
    ``model_band`` (``mountain_perf.backtest.bands``).

    Consommateurs
    -------------
    ``ModelBand`` ; le rapport (M4d-2).

    Non promis
    ----------
    La relation des bornes à ``P_k`` et aux quantiles est vérifiée par ``ModelBand``, à
    ``τ`` près.
    """

    forecast_s: float
    weight: float
    base_s: float
    lower_s: float
    median_s: float
    prudent_s: float
    upper_s: float
    width_s: float
    observed_s: float | None
    observation: Unavailability | None
    score_s: float | None
    covered: bool | None

    def __post_init__(self) -> None:
        for name in ("forecast_s", "base_s"):
            value: float = getattr(self, name)
            require_finite(value, name)
            if not value > 0:
                raise ContractError(f"{name} doit être > 0, reçu {value}.")
        require_finite(self.weight, "weight")
        if self.weight < 0:
            raise ContractError(f"weight doit être >= 0, reçu {self.weight}.")
        bounds = (self.lower_s, self.median_s, self.prudent_s, self.upper_s)
        for name, value in zip(
            ("lower_s", "median_s", "prudent_s", "upper_s"), bounds, strict=True
        ):
            require_finite(value, name)
        if not self.lower_s > 0:
            raise ContractError(f"lower_s doit être > 0, reçu {self.lower_s}.")
        for previous, current in pairwise(bounds):
            if not previous <= current:
                raise ContractError(
                    "les bornes sont dans l'ordre lower <= median <= prudent <= upper, "
                    f"reçu {bounds}."
                )
        if self.width_s != self.upper_s - self.lower_s:
            raise ContractError(
                "width_s doit valoir upper_s − lower_s = "
                f"{self.upper_s - self.lower_s}, reçu {self.width_s}."
            )
        self._check_observation()

    def _check_observation(self) -> None:
        if (self.observed_s is None) == (self.observation is None):
            raise ContractError(
                "exactement un de observed_s et observation doit être présent, reçu "
                f"observed_s={self.observed_s}, observation={self.observation}."
            )
        motif = self.observation
        if motif is not None and motif not in OBSERVATION_UNAVAILABILITY:
            raise ContractError(f"motif d'observation hors de la liste : {motif}.")
        observed = self.observed_s
        if observed is None:
            if self.score_s is not None or self.covered is not None:
                raise ContractError("un élément non observé n'a ni score_s ni covered.")
            return
        require_finite(observed, "observed_s")
        if observed < 0:
            raise ContractError(f"observed_s doit être >= 0, reçu {observed}.")
        if self.score_s is not None:
            require_finite(self.score_s, "score_s")
        expected = _interval_score(self.lower_s, self.upper_s, observed)
        if self.score_s != expected:
            raise ContractError(
                "score_s doit valoir (u − l) + 10 (l − T)₊ + 10 (T − u)₊ = "
                f"{expected}, reçu {self.score_s}."
            )
        if self.covered is not None and self.covered != (
            self.lower_s <= observed <= self.upper_s
        ):
            raise ContractError(
                f"covered vaut l <= T <= u ({self.lower_s} <= {observed} <= "
                f"{self.upper_s}), reçu {self.covered}."
            )

    @property
    def observed(self) -> bool:
        """L'élément est observé (``observation is None``)."""
        return self.observation is None


@dataclass(frozen=True)
class ModelBand:
    """Les fourchettes d'un modèle pour une sortie (``0010`` D11 ; précision de M4d-2).

    Champs
    ------
    - ``model`` — sans unité — le modèle (l'un des cinq de ``BAND_MODELS``).
    - ``residuals`` — sans unité (log-rapport) — un ``Z_c`` par membre de ``C_j``,
      dans l'ordre des membres, ou son motif ; effectif : les segments du membre.
    - ``projected_s`` — secondes — ``P_c``, la prévision du modèle calée à ``o_c`` sur
      le support du membre ; présente si et seulement si le résidu l'est.
    - ``quantiles`` — sans unité — les quantiles des résidus disponibles.
    - ``elements`` — sans unité — une fourchette par élément de ``K``, dans l'ordre ;
      vide sans bornes.
    - ``interval_score_s`` — secondes — ``IS_j = Σ w_k IS_k``.
    - ``normalised_score`` — sans unité — ``IS_j,norm = Σ w_k IS_k / P⁰_k``.
    - ``coverage`` — sans unité — ``Σ w_k 1{l_k <= T_k <= u_k}`` ; absente si ``n = 1``.
    - ``all_covered`` — sans unité — « tous couverts » ; présent avec la couverture.
    - ``median_usage_target`` — sans unité — ``q_usage`` de la prévision médiane
      (dénominateur v0 brut, D7.4).
    - ``median_max_abs_error_s`` — secondes — ``max |C_k|`` de la prévision médiane,
      sur les points de D7.3.
    - ``unavailability`` — sans unité — le statut d'une fourchette sans bornes.

    Propriétés calculées (jamais stockées) : ``count`` (``n``) et ``available``.

    Invariants
    ----------
    Dans l'ordre :

    1. ``model`` dans ``BAND_MODELS`` ; ``residuals``, ``projected_s``, ``elements``
       sont des tuples, ``projected_s`` de la longueur de ``residuals`` ;
    2. un résidu indisponible a un motif de ``RESIDUAL_UNAVAILABILITY`` ;
       ``projected_s[i]`` présent si et seulement si ``residuals[i]`` l'est, fini et
       ``> 0`` ;
    3. ``unavailability`` absent ou dans ``BAND_UNAVAILABILITY`` ; jamais
       ``non calé`` pour v0 brut ;
    4. un résidu en ``erreur du modèle`` ⇒ ``erreur du modèle``, sans quantiles ni
       éléments ; sinon ``support insuffisant`` si et seulement si ``n = 0``, sans
       quantiles ni éléments ; sinon les quantiles sont les statistiques d'ordre des
       résidus disponibles aux rangs ``⌈n a/b⌉`` de ``BAND_QUANTILE_ORDERS`` (au bit),
       et ``elements`` est vide si et seulement si ``unavailability`` est présent ;
    5. sans éléments : ni scores, ni couverture, ni médiane ;
    6. avec éléments : les poids ``w_k`` somment à 1 à ``WEIGHT_SUM_TOLERANCE`` près
       (D7.4) ; chaque borne vaut ``P_k · exp(Q)`` à ``τ`` près ; ``n = 1`` ⇒
       aucun ``covered``, ni couverture, ni « tous couverts » ; ``n >= 2`` ⇒ ``covered``
       présent pour chaque élément observé ;
    7. avec éléments, tous observés : ``interval_score_s``, ``normalised_score`` et
       (``n >= 2``) ``coverage`` valent, au bit, ``fsum(w_k IS_k)``,
       ``fsum(w_k IS_k / P⁰_k)``, ``fsum(w_k, couverts)``, d'effectif ``|K|`` ;
       ``all_covered`` vaut « tous couverts » ; sinon ils sont indisponibles au motif
       du premier élément non observé, d'effectif le nombre d'éléments observés, et
       ``all_covered`` est absent ; la médiane a ses deux valeurs.

    Producteur
    ----------
    ``model_band`` (``mountain_perf.backtest.bands``).

    Consommateurs
    -------------
    ``OutingBands`` ; le rapport (M4d-2).

    Non promis
    ----------
    - le résidu n'est recoupé ni avec ``T_c`` ni avec ``projected_s`` (``ln`` dépend de
      la plateforme) ;
    - la médiane n'est pas recalculée ;
    - les poids et ``P⁰`` sont recoupés entre modèles par ``OutingBands`` ; la
      proportionnalité de ``w_k`` à ``P⁰_k`` n'est pas revérifiée (ce sont les poids
      du ``q_usage`` de v0 brut, D7.4).
    """

    model: ModelKind
    residuals: tuple[MetricValue, ...]
    projected_s: tuple[float | None, ...]
    quantiles: BandQuantiles | None
    elements: tuple[BandElement, ...]
    interval_score_s: MetricValue | None
    normalised_score: MetricValue | None
    coverage: MetricValue | None
    all_covered: bool | None
    median_usage_target: MetricValue | None
    median_max_abs_error_s: MetricValue | None
    unavailability: Unavailability | None

    def __post_init__(self) -> None:
        if self.model not in BAND_MODELS:
            raise ContractError(
                f"model doit être l'un des cinq modèles du rapport, reçu {self.model}."
            )
        for name in ("residuals", "projected_s", "elements"):
            require_immutable_sequence(getattr(self, name), name)
        if len(self.projected_s) != len(self.residuals):
            raise ContractError(
                f"projected_s ({len(self.projected_s)}) et residuals "
                f"({len(self.residuals)}) ont la même longueur."
            )
        self._check_residuals()
        self._check_status()
        if not self.elements:
            self._check_without_elements()
            return
        self._check_bounds()
        self._check_scores()

    @property
    def count(self) -> int:
        """``n`` : le nombre de résidus disponibles."""
        return sum(residual.available for residual in self.residuals)

    @property
    def available(self) -> bool:
        """La fourchette a ses bornes (``unavailability is None``)."""
        return self.unavailability is None

    def _check_residuals(self) -> None:
        for i, (residual, projected) in enumerate(
            zip(self.residuals, self.projected_s, strict=True)
        ):
            motif = residual.unavailability
            if motif is not None and motif not in RESIDUAL_UNAVAILABILITY:
                raise ContractError(
                    f"residuals[{i}] : motif hors de la liste : {motif}."
                )
            if (projected is None) != (residual.value is None):
                raise ContractError(
                    f"projected_s[{i}] est présent si et seulement si residuals[{i}] "
                    "l'est."
                )
            if projected is not None:
                require_finite(projected, f"projected_s[{i}]")
                if not projected > 0:
                    raise ContractError(
                        f"projected_s[{i}] doit être > 0, reçu {projected}."
                    )

    def _check_status(self) -> None:
        status = self.unavailability
        if status is not None and status not in BAND_UNAVAILABILITY:
            raise ContractError(f"statut de la fourchette hors de la liste : {status}.")
        if self.model is ModelKind.V0_RAW and status is Unavailability.NOT_CALIBRATED:
            raise ContractError("v0 brut n'est jamais non calé (D9.2).")
        failed = any(
            residual.unavailability is Unavailability.MODEL_ERROR
            for residual in self.residuals
        )
        if failed or self.count == 0:
            expected = (
                Unavailability.MODEL_ERROR
                if failed
                else Unavailability.INSUFFICIENT_SUPPORT
            )
            if status is not expected or self.quantiles is not None or self.elements:
                raise ContractError(
                    f"{'un résidu en erreur du modèle' if failed else 'aucun résidu'}"
                    f" : statut {expected}, sans quantiles ni éléments, reçu {status}."
                )
            return
        if status is Unavailability.INSUFFICIENT_SUPPORT:
            raise ContractError(
                "support insuffisant : aucun résidu disponible (n = 0), reçu "
                f"n = {self.count}."
            )
        if self.quantiles is None:
            raise ContractError("des résidus disponibles ont leurs quantiles.")
        ordered = sorted(r.value for r in self.residuals if r.value is not None)
        expected_values = tuple(
            ordered[_rank(len(ordered), a, b) - 1] for a, b in BAND_QUANTILE_ORDERS
        )
        if self.quantiles.values != expected_values:
            raise ContractError(
                "les quantiles sont les statistiques d'ordre de rang ⌈n q⌉ des résidus "
                f"disponibles : {expected_values} attendus, reçu "
                f"{self.quantiles.values}."
            )
        if (not self.elements) != (status is not None):
            raise ContractError(
                "les éléments sont vides si et seulement si la fourchette a un statut, "
                f"reçu {len(self.elements)} éléments et le statut {status}."
            )

    def _check_without_elements(self) -> None:
        carried = (
            self.interval_score_s,
            self.normalised_score,
            self.coverage,
            self.all_covered,
            self.median_usage_target,
            self.median_max_abs_error_s,
        )
        if any(value is not None for value in carried):
            raise ContractError(
                "une fourchette sans éléments n'a ni scores, ni couverture, ni médiane."
            )

    def _check_bounds(self) -> None:
        assert self.quantiles is not None  # _check_status
        total = math.fsum(element.weight for element in self.elements)
        if abs(total - 1.0) > WEIGHT_SUM_TOLERANCE:
            raise ContractError(
                f"les poids des éléments somment à 1 à {WEIGHT_SUM_TOLERANCE} près "
                f"(D7.4), reçu {total}."
            )
        try:
            factors = tuple(math.exp(q) for q in self.quantiles.values)
        except OverflowError:
            raise ContractError(
                f"quantiles hors du domaine d'exp : {self.quantiles.values}."
            ) from None
        for k, element in enumerate(self.elements):
            bounds = (
                element.lower_s,
                element.median_s,
                element.prudent_s,
                element.upper_s,
            )
            for bound, factor in zip(bounds, factors, strict=True):
                if not _close(bound, element.forecast_s * factor):
                    raise ContractError(
                        f"elements[{k}] : chaque borne vaut P_k · exp(Q) à "
                        f"{METRIC_RELATIVE_TOLERANCE:g} près, reçu {bounds} pour P_k = "
                        f"{element.forecast_s}."
                    )
        single = self.count == 1
        for k, element in enumerate(self.elements):
            if single and element.covered is not None:
                raise ContractError(
                    f"elements[{k}] : n = 1, aucun élément n'est dit couvert (D11)."
                )
            if not single and element.observed and element.covered is None:
                raise ContractError(
                    f"elements[{k}] : un élément observé dit s'il est couvert (n >= 2)."
                )

    def _check_scores(self) -> None:
        if self.median_usage_target is None or self.median_max_abs_error_s is None:
            raise ContractError("une fourchette à bornes publie sa médiane.")
        if self.interval_score_s is None or self.normalised_score is None:
            raise ContractError("une fourchette à bornes publie ses scores.")
        single = self.count == 1
        if single and (self.coverage is not None or self.all_covered is not None):
            raise ContractError("n = 1 : ni couverture, ni « tous couverts » (D11).")
        if not single and self.coverage is None:
            raise ContractError("n >= 2 : la couverture est publiée.")
        missing = next((e for e in self.elements if not e.observed), None)
        observed = sum(element.observed for element in self.elements)
        published = [self.interval_score_s, self.normalised_score]
        if self.coverage is not None:
            published.append(self.coverage)
        if missing is not None:
            for value in published:
                if value.unavailability is not missing.observation or (
                    value.count != observed
                ):
                    raise ContractError(
                        "un élément non observé : scores et couverture indisponibles, "
                        f"au motif du premier ({missing.observation}), d'effectif "
                        f"{observed}."
                    )
            if self.all_covered is not None:
                raise ContractError(
                    "un élément non observé : pas de « tous couverts »."
                )
            return
        expected = [
            math.fsum(e.weight * _score(e) for e in self.elements),
            math.fsum(e.weight * _score(e) / e.base_s for e in self.elements),
        ]
        if self.coverage is not None:
            expected.append(math.fsum(e.weight for e in self.elements if e.covered))
        for value, wanted in zip(published, expected, strict=True):
            if value.value != wanted or value.count != len(self.elements):
                raise ContractError(
                    f"scores et couverture de K observé : {wanted} sur "
                    f"{len(self.elements)} éléments attendus, reçu {value}."
                )
        if self.coverage is not None:
            every = all(e.covered for e in self.elements)
            if self.all_covered is not every:
                raise ContractError(
                    f"all_covered vaut « tous couverts » ({every}), reçu "
                    f"{self.all_covered}."
                )


def _score(element: BandElement) -> float:
    assert element.score_s is not None  # élément observé
    return element.score_s


@dataclass(frozen=True)
class OutingBands:
    """Le document des fourchettes d'une sortie scorée avec usage (``0010`` D11, D14 ;
    précision de M4d-2 ; format 4).

    Champs
    ------
    - ``outing_id`` — sans unité — la sortie.
    - ``window_from``, ``window_to`` — jours civils — la fenêtre de la courbe (D2.2),
      bornes comprises.
    - ``label`` — sans unité — ``BAND_LABEL``.
    - ``multi_outing`` — sans unité — la performance a plusieurs sorties : fourchettes
      en diagnostic, hors des agrégats (D0).
    - ``members`` — sans unité — le réservoir ``C_j``, dans l'ordre des jours.
    - ``models`` — sans unité — les fourchettes des cinq modèles, dans l'ordre de
      ``BAND_MODELS``.

    Invariants
    ----------
    Dans l'ordre :

    1. ``outing_id`` non vide ; ``window_from <= window_to`` ; ``label`` vaut
       ``BAND_LABEL`` ; ``members`` et ``models`` sont des tuples ;
    2. jours des membres strictement croissants ; ``in_window`` vaut
       ``window_from <= jour <= window_to`` ;
    3. les modèles sont ceux de ``BAND_MODELS``, dans l'ordre ;
    4. chaque modèle a un résidu par membre ; un membre indisponible donne, à chaque
       modèle, un résidu indisponible à son motif ; l'effectif d'un résidu est le
       nombre de segments de son membre ; un membre disponible n'a ni ``support
       insuffisant`` ni ``temps nul`` ; v0 brut n'a jamais de résidu ``non calé`` ;
    5. les modèles à éléments en ont autant, avec les mêmes observations, les mêmes
       poids et les mêmes ``P⁰_k`` ; v0 brut a ``P_k == P⁰_k``.

    Producteur
    ----------
    ``outing_bands`` (``mountain_perf.backtest.bands``) ; la relecture du registre.

    Consommateurs
    -------------
    ``OutingOutcome`` ; ``append_result``, qui l'écrit en document ; la vérification du
    registre ; le rapport (M4d-2).

    Non promis
    ----------
    - ``C_j``, ``K`` et la sortie sont recoupés par l'accord du registre, pas ici ;
    - la fenêtre n'est recoupée avec la courbe par rien (la courbe n'est pas relue).
    """

    outing_id: str
    window_from: date
    window_to: date
    label: str
    multi_outing: bool
    members: tuple[ReservoirMember, ...]
    models: tuple[ModelBand, ...]

    def __post_init__(self) -> None:
        require_non_empty(self.outing_id, "outing_id")
        if not self.window_from <= self.window_to:
            raise ContractError(
                f"window_from ({self.window_from}) précède window_to "
                f"({self.window_to}) ou lui est égal."
            )
        if self.label != BAND_LABEL:
            raise ContractError(
                f"label doit valoir {BAND_LABEL!r}, reçu {self.label!r}."
            )
        require_immutable_sequence(self.members, "members")
        require_immutable_sequence(self.models, "models")
        self._check_members()
        kinds = tuple(band.model for band in self.models)
        if kinds != BAND_MODELS:
            raise ContractError(
                f"models porte les cinq modèles du rapport dans l'ordre, reçu {kinds}."
            )
        for band in self.models:
            self._check_residuals(band)
        self._check_elements()

    def _check_members(self) -> None:
        for previous, current in pairwise(self.members):
            if not previous.civil_date < current.civil_date:
                raise ContractError(
                    "les membres sont par jour strictement croissant, reçu "
                    f"{previous.civil_date} puis {current.civil_date}."
                )
        for member in self.members:
            inside = self.window_from <= member.civil_date <= self.window_to
            if member.in_window != inside:
                raise ContractError(
                    f"le membre {member.civil_date} est "
                    f"{'dans' if inside else 'hors de'} la fenêtre "
                    f"[{self.window_from} ; {self.window_to}], reçu in_window="
                    f"{member.in_window}."
                )

    def _check_residuals(self, band: ModelBand) -> None:
        if len(band.residuals) != len(self.members):
            raise ContractError(
                f"{band.model} : un résidu par membre, reçu {len(band.residuals)} pour "
                f"{len(self.members)} membres."
            )
        for member, residual in zip(self.members, band.residuals, strict=True):
            day = member.civil_date
            if residual.count != member.segment_count:
                raise ContractError(
                    f"{band.model}, {day} : l'effectif du résidu est le nombre de "
                    f"segments du membre ({member.segment_count}), reçu "
                    f"{residual.count}."
                )
            motif = residual.unavailability
            if not member.available:
                if motif is not member.unavailability:
                    raise ContractError(
                        f"{band.model}, {day} : un membre indisponible donne un résidu "
                        f"à son motif ({member.unavailability}), reçu {motif}."
                    )
            elif motif in MEMBER_UNAVAILABILITY:
                raise ContractError(
                    f"{band.model}, {day} : un membre disponible n'a pas le motif "
                    f"{motif}."
                )
            if (
                band.model is ModelKind.V0_RAW
                and motif is Unavailability.NOT_CALIBRATED
            ):
                raise ContractError(f"v0 brut, {day} : jamais non calé (D9.2).")

    def _check_elements(self) -> None:
        shaped = [band for band in self.models if band.elements]
        if not shaped:
            return
        first = shaped[0]
        reference = _element_keys(first.elements)
        for band in shaped[1:]:
            if _element_keys(band.elements) != reference:
                raise ContractError(
                    f"{band.model} : mêmes éléments de K que {first.model} (nombre, "
                    "observations, poids, P⁰_k)."
                )
        raw = self.models[0]
        if any(e.forecast_s != e.base_s for e in raw.elements):
            raise ContractError("v0 brut : P_k vaut P⁰_k.")


def _element_keys(
    elements: Sequence[BandElement],
) -> tuple[tuple[float | None, Unavailability | None, float, float], ...]:
    return tuple((e.observed_s, e.observation, e.weight, e.base_s) for e in elements)
