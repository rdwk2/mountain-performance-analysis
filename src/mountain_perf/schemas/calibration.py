"""Contrats du calage des modèles de référence : population, calage, scores calés
(M4c-1).

Protocole : ``docs/decisions/0010`` D9 (et ses précisions de M4c-1), D2.4, D2.5,
D7.1, D7.4. Pour la performance évaluée ``j`` et chaque modèle calé, un seul paramètre
d'échelle ``β`` (D9.2), appris sur la population ``C_j`` des entraînements terminés
avant l'origine ``o_j``, dans la même horloge et le même scénario que le score évalué.
La prévision calée n'est pas portée : elle se refait depuis la prévision non calée et
le calage (décision 2 du brief M4c-1).

``ModelKind`` vit ici depuis M4c-1 (décision 5) : le registre le réimporte, et ce
module n'importe jamais ``schemas/registry.py``.

Aucun calcul ici hors la vérification des invariants : les producteurs vivent dans
``mountain_perf.backtest.calibration``.
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date, datetime
from enum import StrEnum
from itertools import pairwise
from types import MappingProxyType

from mountain_perf.schemas.clock import CLOCKS, Clock
from mountain_perf.schemas.metrics import METRIC_RELATIVE_TOLERANCE
from mountain_perf.schemas.outing import Unavailability
from mountain_perf.schemas.scoring import (
    ClockScores,
    ModelForecast,
    OutingObservation,
    Scenario,
)
from mountain_perf.validation import (
    ContractError,
    require_aware,
    require_finite,
    require_immutable_sequence,
)

EFFORT_BOUNDS: tuple[float, float] = (0.5, 1.5)
"""L'intervalle de l'effort recalé de v0, bornes comprises (``0010`` D9.2, ``0009``)."""


class ModelKind(StrEnum):
    """Nature d'un modèle évalué (``0010`` D9.1, D10.1).

    Champs
    ------
    Valeurs décrites dans ``MODEL_KIND_DESCRIPTIONS``.

    Invariants
    ----------
    Énumération fermée : les cinq modèles de D9.1 et le candidat de D10.1.

    Producteur
    ----------
    L'appelant d'une déclaration (M4b-5 pour v0 brut, M4c pour les autres) ; le
    calage (M4c-1).

    Consommateurs
    -------------
    ``ModelCalibration`` ; ``DeclaredModel``, ``ExperimentDeclaration``,
    ``ModelResult``, ``OutingOutcome`` ; l'accord d'un résultat avec sa déclaration
    (``CURVE_MODELS``).

    Non promis
    ----------
    La nature ne dit ni la version ni les paramètres : ils sont dans la déclaration du
    modèle.
    """

    V0_RAW = "v0_raw"
    V0_RECALIBRATED = "v0_recalibrated"
    CONSTANT_SPEED = "constant_speed"
    NAISMITH = "naismith"
    TOBLER = "tobler"
    CANDIDATE = "candidate"


MODEL_KIND_DESCRIPTIONS: Mapping[ModelKind, str] = MappingProxyType(
    {
        ModelKind.V0_RAW: "v0 brut : la courbe, effort 1, sans calage (D9.1).",
        ModelKind.V0_RECALIBRATED: (
            "v0 + effort recalé : le comparateur, base (0) de toute expérience (D9.1, "
            "D10.1)."
        ),
        ModelKind.CONSTANT_SPEED: "Vitesse constante : baseline (D9.1).",
        ModelKind.NAISMITH: (
            "Naismith : baseline, 5 km/h + 1 h par 600 m de D+ (D9.1)."
        ),
        ModelKind.TOBLER: "Tobler : baseline (D9.1).",
        ModelKind.CANDIDATE: "Candidat (1) : la base plus l'effet testé (D10.1).",
    }
)

CALIBRATED_MODELS: tuple[ModelKind, ...] = (
    ModelKind.V0_RECALIBRATED,
    ModelKind.CONSTANT_SPEED,
    ModelKind.NAISMITH,
    ModelKind.TOBLER,
)
"""Les quatre modèles calés de ``0010`` D9.1, dans l'ordre du protocole."""


def _close(value: float, expected: float) -> bool:
    """``value`` vaut ``expected`` à ``τ·max(1, |expected|)`` près, ``τ`` =
    ``METRIC_RELATIVE_TOLERANCE`` (décision 15 du brief M4c-1)."""
    return abs(value - expected) <= METRIC_RELATIVE_TOLERANCE * max(1.0, abs(expected))


def _days(days: tuple[date, ...]) -> str:
    return "[" + ", ".join(day.isoformat() for day in days) + "]"


def _require_increasing_days(days: tuple[date, ...], name: str) -> None:
    """Refuse des jours qui ne sont pas strictement croissants."""
    if any(b <= a for a, b in pairwise(days)):
        raise ContractError(f"{name} doit être strictement croissant par jour.")


def _require_calibrated_model(model: ModelKind) -> None:
    if model not in CALIBRATED_MODELS:
        raise ContractError(f"model doit être un modèle calé (D9.1), reçu {model}.")


class PopulationExclusionReason(StrEnum):
    """Motif d'exclusion d'une performance de ``C_j`` (``0010`` D2.4 ; précision de
    M4c-1).

    Champs
    ------
    Valeurs décrites dans ``POPULATION_EXCLUSION_DESCRIPTIONS``.

    Invariants
    ----------
    Énumération fermée : course, ou étiquette manquante ; « course » l'emporte quand
    une performance porte à la fois une course et une sortie sans étiquette.

    Producteur
    ----------
    ``calibration_population`` (``mountain_perf.backtest.calibration``).

    Consommateurs
    -------------
    ``PopulationExclusion``.

    Non promis
    ----------
    Le motif ne dit pas quelle sortie de la performance l'a déclenché.
    """

    RACE = "race"
    UNLABELLED = "unlabelled"


POPULATION_EXCLUSION_DESCRIPTIONS: Mapping[PopulationExclusionReason, str] = (
    MappingProxyType(
        {
            PopulationExclusionReason.RACE: (
                "course : une performance qui contient une course est exclue en "
                "entier (D2.4)."
            ),
            PopulationExclusionReason.UNLABELLED: (
                "étiquette manquante : une sortie sans étiquette ne vaut pas "
                "entraînement (D2.4)."
            ),
        }
    )
)


@dataclass(frozen=True)
class PopulationExclusion:
    """Une performance terminée avant l'origine ``o_j``, exclue de ``C_j`` (``0010``
    D2.4).

    Champs
    ------
    - ``civil_date`` — jour civil — le jour de la performance exclue.
    - ``reason`` — sans unité — son motif : course, sinon étiquette manquante.

    Invariants
    ----------
    Aucun au-delà des types.

    Producteur
    ----------
    ``calibration_population`` (``mountain_perf.backtest.calibration``).

    Consommateurs
    -------------
    ``CalibrationPopulation``.

    Non promis
    ----------
    Le motif n'est pas recoupé avec les étiquettes des sorties de la performance.
    """

    civil_date: date
    reason: PopulationExclusionReason


@dataclass(frozen=True)
class CalibrationPopulation:
    """La population ``C_j`` d'une performance évaluée (``0010`` D2.4, D2.5 ;
    précision de M4c-1).

    Champs
    ------
    - ``civil_date`` — jour civil — le jour évalué ``J``.
    - ``origin`` — instant avec fuseau — l'origine ``o_j`` de ``J``.
    - ``members`` — jours civils — les membres : performances terminées strictement
      avant ``o_j`` dont toutes les sorties sont étiquetées entraînement.
    - ``excluded`` — sans unité — les autres performances terminées avant ``o_j``,
      avec leur motif.

    Invariants
    ----------
    1. ``origin`` avec fuseau ; ``members`` et ``excluded`` sont des tuples ;
    2. ``members``, puis les jours de ``excluded`` : strictement croissants, et chacun
       antérieur à ``civil_date`` (D9.2 : le jour évalué n'entre jamais dans son
       propre calage) ;
    3. aucun jour à la fois membre et exclu.

    Producteur
    ----------
    ``calibration_population`` (``mountain_perf.backtest.calibration``).

    Consommateurs
    -------------
    ``calibrate`` ; ``CalibratedPerformance``.

    Non promis
    ----------
    ``origin`` n'est pas recalculée depuis ``civil_date`` ; le domaine des membres
    n'est pas revérifié.
    """

    civil_date: date
    origin: datetime
    members: tuple[date, ...]
    excluded: tuple[PopulationExclusion, ...]

    def __post_init__(self) -> None:
        require_aware(self.origin, "origin")
        require_immutable_sequence(self.members, "members")
        require_immutable_sequence(self.excluded, "excluded")
        excluded = tuple(exclusion.civil_date for exclusion in self.excluded)
        for name, days in (("members", self.members), ("excluded", excluded)):
            _require_increasing_days(days, name)
            for day in days:
                if day >= self.civil_date:
                    raise ContractError(
                        f"{name} : le jour {day.isoformat()} doit précéder le jour "
                        f"évalué {self.civil_date.isoformat()} (D9.2)."
                    )
        common = tuple(sorted(set(self.members) & set(excluded)))
        if common:
            raise ContractError(
                f"un jour ne peut être à la fois membre et exclu : {_days(common)}."
            )


@dataclass(frozen=True)
class CalibrationWithdrawal:
    """Un membre de ``C_j`` retiré de la population effective d'un calage (``0010``
    D9.2 ; précision de M4c-1).

    Champs
    ------
    - ``civil_date`` — jour civil — le jour du membre retiré.
    - ``reason`` — sans unité — son motif : support admis vide
      (``insufficient_support``) ou ``T_c`` nul (``zero_time``).

    Invariants
    ----------
    ``reason`` vaut ``INSUFFICIENT_SUPPORT`` ou ``ZERO_TIME``.

    Producteur
    ----------
    ``calibrate`` (``mountain_perf.backtest.calibration``).

    Consommateurs
    -------------
    ``ModelCalibration``.

    Non promis
    ----------
    Le motif n'est pas recoupé avec les scores du membre ; une projection invalide
    n'est jamais un retrait (D7.1 : elle rend le calage ``erreur du modèle``).
    """

    civil_date: date
    reason: Unavailability

    def __post_init__(self) -> None:
        if self.reason not in (
            Unavailability.INSUFFICIENT_SUPPORT,
            Unavailability.ZERO_TIME,
        ):
            raise ContractError(
                "un retrait a pour motif insufficient_support ou zero_time (D9.2), "
                f"reçu {self.reason}."
            )


@dataclass(frozen=True)
class ModelCalibration:
    """Le calage d'un modèle pour une performance, dans un scénario et sous une
    horloge (``0010`` D9.2 ; précision de M4c-1).

    Champs
    ------
    - ``model`` — sans unité — le modèle calé.
    - ``scenario`` — sans unité — le scénario des totaux.
    - ``clock`` — sans unité — l'horloge des totaux observés.
    - ``population`` — jours civils — ``C_j^eff`` : les membres dont le support admis
      est non vide et ``T_c > 0``.
    - ``withdrawals`` — sans unité — les autres membres de ``C_j``, avec leur motif.
    - ``beta`` — sans unité — ``β`` : la moyenne des ``ln(T_c / P_c)``, un par membre
      de la population ; absent si le modèle n'est pas calé.
    - ``effort`` — sans unité — v0 seulement : ``exp(−β)`` borné à ``EFFORT_BOUNDS`` ;
      la prévision calée de v0 est la prévision non calée divisée par lui.
    - ``factor`` — sans unité — baseline : ``exp(β)``, le multiplicateur de la
      prévision non calée ; v0 : ``1 / effort``, publié pour lecture — la prévision
      calée de v0 est ``p / effort``, jamais ``p · factor`` (l'arrondi diffère ;
      décision 2).
    - ``saturated`` — sans unité — v0 seulement : ``exp(−β)`` hors de
      ``EFFORT_BOUNDS``.
    - ``unavailability`` — sans unité — ``NOT_CALIBRATED``, ``MODEL_ERROR``, ou absent
      (calé).

    Invariants
    ----------
    Dans l'ordre, ``τ = METRIC_RELATIVE_TOLERANCE`` (``1e−12``), ``_close(x, y)`` :
    ``|x − y| <= τ·max(1, |y|)`` :

    1. ``model`` dans ``CALIBRATED_MODELS`` ;
    2. ``population`` et ``withdrawals`` : tuples, strictement croissants par jour,
       sans jour commun ;
    3. ``unavailability`` absent, ``NOT_CALIBRATED`` ou ``MODEL_ERROR`` ;
    4. ``NOT_CALIBRATED`` si et seulement si ``population`` est vide ;
    5. calé (``unavailability`` absent) : ``beta`` fini, dans le domaine d'``exp``
       (``exp(beta)`` et ``exp(−beta)`` ne débordent pas) ; ``factor`` fini et
       ``> 0`` ; baseline : ni ``effort`` ni saturation, ``_close(factor,
       exp(beta))`` ; v0, ``(low, high) = EFFORT_BOUNDS`` : ``effort`` présent dans
       ``[low ; high]``, ``factor == 1 / effort`` **au bit**, ``saturated`` seulement
       si ``effort`` vaut ``low`` ou ``high``, ``_close(effort, min(max(exp(−beta),
       low), high))``, et ``saturated`` vaut ``exp(−beta)`` hors de ``[low ; high]``
       — indifférent quand ``exp(−beta)`` est à ``τ`` près d'une borne ;
    6. non calé ou en erreur : ni ``beta``, ni ``effort``, ni ``factor``, ni
       saturation.

    Producteur
    ----------
    ``calibrate`` (``mountain_perf.backtest.calibration``).

    Consommateurs
    -------------
    ``CalibratedClockScores`` ; ``calibrated_forecast``, ``calibrated_scores``.

    Non promis
    ----------
    - la population n'est recoupée ni avec ``C_j`` ni avec les retraits ; les
      ``ln(T_c / P_c)`` de chaque membre ne sont pas publiés ;
    - **la relation à ``beta`` n'est vérifiée qu'à ``τ`` près, pas au bit**
      (décision 15) : l'arrondi d'``exp`` dépend de la plateforme, et un calage écrit
      sur l'une doit se relire sur l'autre ; ``calibrate`` la tient au bit sur la
      plateforme qui calcule.
    """

    model: ModelKind
    scenario: Scenario
    clock: Clock
    population: tuple[date, ...]
    withdrawals: tuple[CalibrationWithdrawal, ...]
    beta: float | None
    effort: float | None
    factor: float | None
    saturated: bool
    unavailability: Unavailability | None

    def __post_init__(self) -> None:
        _require_calibrated_model(self.model)
        self._check_population()
        if self.unavailability not in (
            None,
            Unavailability.NOT_CALIBRATED,
            Unavailability.MODEL_ERROR,
        ):
            raise ContractError(
                "unavailability vaut not_calibrated ou model_error, ou est absent, "
                f"reçu {self.unavailability}."
            )
        not_calibrated = self.unavailability is Unavailability.NOT_CALIBRATED
        if not_calibrated != (not self.population):
            raise ContractError(
                "not_calibrated si et seulement si la population effective est vide "
                "(D9.2)."
            )
        if self.unavailability is None:
            self._check_calibrated()
        elif (
            self.beta is not None
            or self.effort is not None
            or self.factor is not None
            or self.saturated
        ):
            raise ContractError(
                "un modèle non calé ou en erreur n'a ni beta, ni effort, ni facteur, "
                "ni saturation."
            )

    def _check_population(self) -> None:
        require_immutable_sequence(self.population, "population")
        require_immutable_sequence(self.withdrawals, "withdrawals")
        withdrawn = tuple(withdrawal.civil_date for withdrawal in self.withdrawals)
        _require_increasing_days(self.population, "population")
        _require_increasing_days(withdrawn, "withdrawals")
        common = tuple(sorted(set(self.population) & set(withdrawn)))
        if common:
            raise ContractError(
                "un jour ne peut être à la fois dans la population et retiré : "
                f"{_days(common)}."
            )

    def _check_calibrated(self) -> None:
        if self.beta is None or self.factor is None:
            raise ContractError("un modèle calé porte beta et factor (D9.2).")
        require_finite(self.beta, "beta")
        require_finite(self.factor, "factor")
        try:
            growth, unbounded = math.exp(self.beta), math.exp(-self.beta)
        except OverflowError:
            raise ContractError(
                f"beta hors du domaine d'exp (exp(±beta) déborde), reçu {self.beta!r}."
            ) from None
        if not self.factor > 0:
            raise ContractError(f"factor doit être > 0, reçu {self.factor!r}.")
        tolerance = f"{METRIC_RELATIVE_TOLERANCE:g}"
        if self.model is not ModelKind.V0_RECALIBRATED:
            if self.effort is not None or self.saturated:
                raise ContractError("une baseline n'a ni effort ni saturation (D9.2).")
            if not _close(self.factor, growth):
                raise ContractError(
                    f"factor d'une baseline doit valoir exp(beta) = {growth!r} à "
                    f"{tolerance} près, reçu {self.factor!r} (D9.2)."
                )
            return
        low, high = EFFORT_BOUNDS
        if self.effort is None or not low <= self.effort <= high:
            raise ContractError(
                f"effort doit être dans [{low} ; {high}] (D9.2), reçu {self.effort!r}."
            )
        if self.factor != 1.0 / self.effort:
            raise ContractError(
                f"factor de v0 doit valoir 1 / effort = {1.0 / self.effort!r}, reçu "
                f"{self.factor!r}."
            )
        if self.saturated and self.effort not in (low, high):
            raise ContractError(
                f"une saturation met l'effort à une borne (D9.2), reçu {self.effort!r}."
            )
        expected = min(max(unbounded, low), high)
        if not _close(self.effort, expected):
            raise ContractError(
                f"effort doit valoir min(max(exp(-beta), {low}), {high}) = "
                f"{expected!r} à {tolerance} près, reçu {self.effort!r} (D9.2)."
            )
        at_bound = _close(unbounded, low) or _close(unbounded, high)
        if not at_bound and self.saturated != (not low <= unbounded <= high):
            raise ContractError(
                f"saturated vaut vrai si et seulement si exp(-beta) est hors de "
                f"[{low} ; {high}] (D9.2 ; indifférent à {tolerance} près d'une "
                "borne)."
            )


@dataclass(frozen=True)
class CalibratedClockScores:
    """Le calage d'un modèle sous une horloge, et les scores de sa prévision calée
    (``0010`` D9.2, D7).

    Champs
    ------
    - ``calibration`` — sans unité — le calage sous cette horloge.
    - ``scores`` — sans unité — les scores de la prévision calée sous cette horloge ;
      absents si le modèle n'est pas calé.

    Invariants
    ----------
    1. ``scores`` absents si et seulement si ``calibration.unavailability`` est
       présent ;
    2. ``scores.clock == calibration.clock``.

    Producteur
    ----------
    ``calibrated_scores`` (``mountain_perf.backtest.calibration``).

    Consommateurs
    -------------
    ``CalibratedScenarioScores``.

    Non promis
    ----------
    La prévision calée n'est pas portée : elle se refait depuis la prévision non
    calée et le calage (décision 2).
    """

    calibration: ModelCalibration
    scores: ClockScores | None

    def __post_init__(self) -> None:
        unavailability = self.calibration.unavailability
        if (self.scores is None) != (unavailability is not None):
            raise ContractError(
                "scores absents si et seulement si le modèle n'est pas calé "
                f"({unavailability})."
            )
        if self.scores is not None and self.scores.clock != self.calibration.clock:
            raise ContractError(
                f"scores.clock ({self.scores.clock}) doit être l'horloge du calage "
                f"({self.calibration.clock})."
            )


@dataclass(frozen=True)
class CalibratedScenarioScores:
    """Les scores calés d'un modèle sur une sortie, dans un scénario, sous les onze
    horloges (``0010`` D9.2, D7 ; précision de M4c-1).

    Champs
    ------
    - ``model`` — sans unité — le modèle calé.
    - ``scenario`` — sans unité — le scénario.
    - ``forecast`` — sans unité — la prévision **non calée** (v0 à l'effort 1,
      baseline à son échelle nominale).
    - ``clocks`` — sans unité — le calage et les scores calés sous chaque horloge,
      dans l'ordre de ``CLOCKS``.

    Invariants
    ----------
    1. ``model`` dans ``CALIBRATED_MODELS`` ;
    2. ``forecast.scenario is scenario`` ;
    3. ``clocks`` est un tuple ; ses horloges sont ``CLOCKS``, dans l'ordre ;
    4. chaque calage porte ce ``model`` et ce ``scenario`` ;
    5. sous les horloges dont les scores sont présents (calées), comme
       ``ScenarioScores`` : ``support.segment_count == len(forecast.segment_s)``, les
       mêmes effectifs de classe et le même ``support.model_error`` (la première
       horloge calée sert de référence) ;
    6. sous ces mêmes horloges, comme ``ScenarioScores`` : ``passage_errors`` présent
       **si et seulement si** ``scenario == USAGE`` ; en usage,
       ``len(errors_s) == len(forecast.point_s)`` et
       ``len(usage_target.comparable) == len(forecast.target_s)``.

    Producteur
    ----------
    ``calibrated_scores`` (``mountain_perf.backtest.calibration``).

    Consommateurs
    -------------
    ``CalibratedOutingScores``.

    Non promis
    ----------
    - Aucune enveloppe (D5.4 ; décision 8) : la prévision calée change d'une horloge à
      l'autre ;
    - une horloge non calée n'a pas de scores et n'entre dans aucune comparaison des
      invariants 5 et 6 (décision Q2 de M4c-2).
    """

    model: ModelKind
    scenario: Scenario
    forecast: ModelForecast
    clocks: tuple[CalibratedClockScores, ...]

    def __post_init__(self) -> None:
        _require_calibrated_model(self.model)
        if self.forecast.scenario is not self.scenario:
            raise ContractError(
                f"forecast.scenario ({self.forecast.scenario}) doit valoir scenario "
                f"({self.scenario})."
            )
        require_immutable_sequence(self.clocks, "clocks")
        if tuple(entry.calibration.clock for entry in self.clocks) != CLOCKS:
            raise ContractError(
                "clocks porte les onze horloges dans l'ordre de CLOCKS."
            )
        for entry in self.clocks:
            calibration = entry.calibration
            if (
                calibration.model is not self.model
                or calibration.scenario is not self.scenario
            ):
                raise ContractError(
                    f"le calage sous {calibration.clock} doit porter le modèle "
                    f"{self.model} et le scénario {self.scenario}."
                )
        present = [entry.scores for entry in self.clocks if entry.scores is not None]
        if present:
            self._check_supports(present)
            self._check_passages(present)

    def _check_supports(self, present: list[ClockScores]) -> None:
        """Invariant 5, recopié de ``ScenarioScores`` (décision Q2 de M4c-2)."""
        segment_count = len(self.forecast.segment_s)
        first = present[0].support
        counts = [regime.segment_count for regime in first.classes]
        for scores in present:
            support = scores.support
            if support.segment_count != segment_count:
                raise ContractError(
                    f"support.segment_count ({support.segment_count}) sous "
                    f"{scores.clock} doit valoir len(forecast.segment_s) "
                    f"({segment_count})."
                )
            if [regime.segment_count for regime in support.classes] != counts:
                raise ContractError(
                    f"les effectifs de classe sous {scores.clock} doivent être ceux "
                    "des autres horloges."
                )
            if support.model_error != first.model_error:
                raise ContractError(
                    f"support.model_error sous {scores.clock} doit être celui des "
                    "autres horloges (D7.1)."
                )

    def _check_passages(self, present: list[ClockScores]) -> None:
        """Invariant 6, recopié de ``ScenarioScores`` (décision Q2 de M4c-2)."""
        usage = self.scenario is Scenario.USAGE
        for scores in present:
            errors, target = scores.passage_errors, scores.usage_target
            if (errors is not None) != usage:
                raise ContractError(
                    f"passage_errors sous {scores.clock} est présent si et seulement "
                    f"si le scénario est l'usage, reçu {self.scenario}."
                )
            if errors is None or target is None:
                continue
            if len(errors.errors_s) != len(self.forecast.point_s):
                raise ContractError(
                    f"passage_errors sous {scores.clock} porte une erreur par point "
                    f"({len(self.forecast.point_s)}), reçu {len(errors.errors_s)}."
                )
            if len(target.comparable) != len(self.forecast.target_s):
                raise ContractError(
                    f"usage_target sous {scores.clock} porte un élément par cumulé de "
                    f"K ({len(self.forecast.target_s)}), reçu {len(target.comparable)}."
                )


@dataclass(frozen=True)
class CalibratedOutingScores:
    """Les scores calés d'un modèle sur une sortie, dans ses scénarios (``0010`` D3,
    D9.2).

    Champs
    ------
    - ``outing_id`` — sans unité — l'identifiant de la sortie.
    - ``observation`` — sans unité — ce que la sortie observe (celle des scores non
      calés de la source).
    - ``control`` — sans unité — les scores calés du scénario contrôle.
    - ``usage`` — sans unité — les scores calés du scénario usage ; absents pour une
      sortie sans référence (D3).

    Invariants
    ----------
    1. ``control.scenario is CONTROL`` ;
    2. ``usage`` présent : ``usage.scenario is USAGE``, même modèle que ``control`` ;
    3. pour chaque scénario présent,
       ``len(forecast.segment_s) == len(observation.segments)`` ;
    4. en usage, comme ``OutingScores`` : ``len(point_s) ==
       len(observation.error_points)`` et ``len(target_s) ==
       len(observation.targets)``.

    Producteur
    ----------
    ``calibrate_performances`` (``mountain_perf.backtest.calibration``).

    Consommateurs
    -------------
    ``CalibratedPerformance`` ; l'exécution et le rapport à cinq modèles (M4c-2).

    Non promis
    ----------
    Les calages ne sont pas recoupés d'un scénario à l'autre (``C_j^eff`` peut
    différer).
    """

    outing_id: str
    observation: OutingObservation
    control: CalibratedScenarioScores
    usage: CalibratedScenarioScores | None

    def __post_init__(self) -> None:
        if self.control.scenario is not Scenario.CONTROL:
            raise ContractError(
                f"control porte le scénario contrôle, reçu {self.control.scenario}."
            )
        if self.usage is not None:
            if self.usage.scenario is not Scenario.USAGE:
                raise ContractError(
                    f"usage porte le scénario usage, reçu {self.usage.scenario}."
                )
            if self.usage.model is not self.control.model:
                raise ContractError("usage et control portent le même modèle.")
        segments = len(self.observation.segments)
        for scores in (self.control, self.usage):
            if scores is None:
                continue
            projections = len(scores.forecast.segment_s)
            if projections != segments:
                raise ContractError(
                    f"{scores.scenario} : {projections} projections pour {segments} "
                    "segments admis."
                )
        if self.usage is not None:
            forecast = self.usage.forecast
            observation = self.observation
            if len(forecast.point_s) != len(observation.error_points):
                raise ContractError(
                    f"usage : {len(forecast.point_s)} cumulés pour "
                    f"{len(observation.error_points)} points de C_k."
                )
            if len(forecast.target_s) != len(observation.targets):
                raise ContractError(
                    f"usage : {len(forecast.target_s)} cumulés pour "
                    f"{len(observation.targets)} éléments de K."
                )


@dataclass(frozen=True)
class CalibratedPerformance:
    """Le calage d'une performance évaluée et les scores calés de ses sorties scorées
    (``0010`` D9.2).

    Champs
    ------
    - ``population`` — sans unité — ``C_j``.
    - ``outings`` — sans unité — par sortie scorée, dans l'ordre de la performance,
      les scores calés des quatre modèles, dans l'ordre de ``CALIBRATED_MODELS``.

    Invariants
    ----------
    1. ``outings`` est un tuple ; sa longueur est un multiple de quatre ;
    2. par groupes consécutifs de quatre : les modèles (``control.model``) sont
       ``CALIBRATED_MODELS``, dans l'ordre ; un seul ``outing_id`` par groupe ; deux
       groupes n'ont pas le même ``outing_id`` ;
    3. dans chaque groupe, **la même observation** (``==``) pour les quatre modèles
       (D7.1 : le support ne dépend que de l'observation ; décision Q2 de M4c-2).

    Producteur
    ----------
    ``calibrate_performances`` (``mountain_perf.backtest.calibration``).

    Consommateurs
    -------------
    L'exécution et le rapport à cinq modèles (M4c-2).

    Non promis
    ----------
    Les sorties non scorées n'y figurent pas ; les calages ne sont pas recoupés d'une
    sortie à l'autre d'une même performance.
    """

    population: CalibrationPopulation
    outings: tuple[CalibratedOutingScores, ...]

    def __post_init__(self) -> None:
        require_immutable_sequence(self.outings, "outings")
        size = len(CALIBRATED_MODELS)
        if len(self.outings) % size:
            raise ContractError(
                f"outings porte {size} modèles par sortie, reçu {len(self.outings)}."
            )
        seen: set[str] = set()
        for start in range(0, len(self.outings), size):
            group = self.outings[start : start + size]
            models = tuple(entry.control.model for entry in group)
            if models != CALIBRATED_MODELS:
                raise ContractError(
                    "les modèles d'une sortie suivent CALIBRATED_MODELS, reçu "
                    f"[{', '.join(models)}]."
                )
            identifiers = sorted({entry.outing_id for entry in group})
            if len(identifiers) != 1:
                raise ContractError(
                    "un groupe porte une seule sortie, reçu "
                    f"[{', '.join(identifiers)}]."
                )
            if any(entry.observation != group[0].observation for entry in group[1:]):
                raise ContractError(
                    f"les quatre modèles de la sortie {identifiers[0]} portent la même "
                    "observation (D7.1)."
                )
            if identifiers[0] in seen:
                raise ContractError(f"la sortie {identifiers[0]} a deux groupes.")
            seen.add(identifiers[0])
