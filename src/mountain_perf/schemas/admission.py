"""Contrats du document d'admission exploratoire (M4c-3).

Protocole : ``docs/decisions/0010`` D10.2 à D10.6 et D14, avec leurs précisions de
M4c-3 (décisions E1 à E6 de la passe experte). Le RÉSULTAT d'une expérience (format 3
du registre) cite un document d'admission : l'évaluation de chaque performance
déclarée, les agrégats, les garde-fous, les causes de « à revoir », les conditions
calculables qui échouent, le verdict et ses réserves.

Aucun calcul de la règle ici : son producteur est ``mountain_perf.backtest.admission``.
Les invariants **recalculent** depuis les valeurs publiées ce qui en découle (seuils,
gains, moyennes, votes, causes, verdict, réserves), pour qu'un document relu ne puisse
pas se contredire.
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from enum import StrEnum
from itertools import pairwise
from types import MappingProxyType

from mountain_perf.schemas.calibration import EFFORT_BOUNDS
from mountain_perf.schemas.clock import Clock
from mountain_perf.schemas.metrics import METRIC_RELATIVE_TOLERANCE, MetricValue
from mountain_perf.schemas.outing import Unavailability
from mountain_perf.schemas.registry import ExperimentMetric
from mountain_perf.validation import (
    ContractError,
    require_finite,
    require_immutable_sequence,
    require_non_empty,
)

GAIN_FLOOR = 0.010
"""Plancher de ``δ_j``, et seuil fixe d'une cible (``0010`` D10.3)."""

GAIN_SHARE = 0.25
"""Part de la référence ``F_j`` dans ``δ_j = max(0,010 ; 0,25·F_j)`` (``0010``
D10.3)."""

HARM_FLOOR = 0.005
"""Plancher de ``η_jk``, et seuil fixe d'un garde-fou (``0010`` D10.4)."""

HARM_SHARE = 0.10
"""Part de la référence ``F_jk`` dans ``η_jk = max(0,005 ; 0,10·F_jk)`` (``0010``
D10.4)."""

HARM_MAX_FACTOR = 2.0
"""``H_jk <= 2·η_jk`` pour tout ``j`` de ``J_k`` (``0010`` D10.4)."""

PASSAGE_TOLERANCE = 0.01
"""Dommage relatif maximal à un passage comparable (``0010`` D10.4)."""

NUMERIC_TOLERANCE = 1e-6
"""La tolérance numérique ``ε`` des conditions de D10.3 et D10.4 (``0010`` D10.3 ;
décision E2 de M4c-3).

Moins d'une seconde sur ``10⁶`` s, sous la résolution des horodatages ; et plusieurs
ordres au-dessus de l'arrondi de la chaîne (des prévisions égales en réels diffèrent
en machine de ``1e−12`` sur des cumuls de 158 000 s). Les frontières de « comparable »
restent exactes, sans ``ε``.
"""

COMPARABLE_MAX_S = 4 * 3600.0
"""Durée projetée maximale d'une performance comparable, incluse (``0010`` D10.3)."""

COMPARABLE_DPLUS_PER_KM: tuple[float, float] = (50.0, 110.0)
"""Bande du D+/km d'une performance comparable, bornes incluses (``0010`` D10.3)."""

REGIME_MIN_SEGMENTS = 3
"""Une cible ou un garde-fou de régime demande 3 segments admis de la classe
(``0010`` D10.2, D10.4)."""

GUARD_METRICS: tuple[ExperimentMetric, ...] = (
    ExperimentMetric.LEVEL,
    ExperimentMetric.ASCENT_LEVEL,
    ExperimentMetric.FLAT_LEVEL,
    ExperimentMetric.DESCENT_LEVEL,
    ExperimentMetric.ASCENT_DISPERSION,
    ExperimentMetric.FLAT_DISPERSION,
    ExperimentMetric.DESCENT_DISPERSION,
)
"""La liste figée des garde-fous de métrique, dans cet ordre ; la cible en est retirée
(``0010`` D10.4)."""


def required_successes(evaluable: int) -> int:
    """``⌈3n/4⌉``, le nombre de succès exigés du vote (``0010`` D10.3), en entiers."""
    return (3 * evaluable + 3) // 4


# ---------------------------------------------------------------------------
# Énumérations
# ---------------------------------------------------------------------------


class AdmissionVerdict(StrEnum):
    """Verdict d'une admission exploratoire (``0010`` D10.6).

    Champs
    ------
    Valeurs décrites dans ``ADMISSION_VERDICT_DESCRIPTIONS``.

    Invariants
    ----------
    Énumération fermée, à trois états.

    Producteur
    ----------
    ``admit`` (``mountain_perf.backtest.admission``).

    Consommateurs
    -------------
    ``Admission``.

    Non promis
    ----------
    Jamais une preuve ; la confirmation (D10.7) n'est pas dans ce lot.
    """

    PROVISIONAL = "provisional_candidate"
    REJECTED = "rejected"
    TO_REVIEW = "to_review"


ADMISSION_VERDICT_DESCRIPTIONS: Mapping[AdmissionVerdict, str] = MappingProxyType(
    {
        AdmissionVerdict.PROVISIONAL: (
            "Candidat provisoire exploratoire : gain moyen, vote et pertes dans les "
            "seuils de D10.3, garde-fous de D10.4 satisfaits, rien à revoir."
        ),
        AdmissionVerdict.REJECTED: (
            "Rejeté : une condition calculable de D10.3 ou de D10.4 échoue, rien à "
            "revoir."
        ),
        AdmissionVerdict.TO_REVIEW: (
            "À revoir : une cible, un garde-fou exigé ou les passages ne se calculent "
            "pas, ou aucun passage comparable (D10.6)."
        ),
    }
)


class AdmissionReserve(StrEnum):
    """Réserve d'un verdict d'admission (``0010`` D10.5, D10.6 ; décision E1 de
    M4c-3).

    Champs
    ------
    Valeurs décrites dans ``ADMISSION_RESERVE_DESCRIPTIONS``.

    Invariants
    ----------
    Énumération fermée ; les réserves se cumulent, dans cet ordre.

    Producteur
    ----------
    ``admit`` (``mountain_perf.backtest.admission``).

    Consommateurs
    -------------
    ``Admission``.

    Non promis
    ----------
    Une réserve ne change pas le verdict.
    """

    COMPARATOR_SATURATED = "comparator_saturated"
    CANDIDATE_SATURATED = "candidate_saturated"
    SENSITIVITY_REMAINING = "central_sensitivity_remaining"


ADMISSION_RESERVE_DESCRIPTIONS: Mapping[AdmissionReserve, str] = MappingProxyType(
    {
        AdmissionReserve.COMPARATOR_SATURATED: (
            "Comparateur saturé : l'effort de (0) est borné sur une performance "
            "évaluable au moins (D10.5)."
        ),
        AdmissionReserve.CANDIDATE_SATURATED: (
            "Candidat saturé : de même pour (1) ; l'invariance au niveau ne vaut que "
            "si les deux efforts sont libres (décision E1)."
        ),
        AdmissionReserve.SENSITIVITY_REMAINING: (
            "Centrale, sensibilité restante : la sensibilité complète (D13) n'a pas "
            "tourné (D10.6)."
        ),
    }
)


class ThresholdSource(StrEnum):
    """Source du seuil d'une performance ou d'une valeur de garde-fou (``0010`` D10.3,
    D10.4).

    Champs
    ------
    Valeurs décrites dans ``THRESHOLD_SOURCE_DESCRIPTIONS``.

    Invariants
    ----------
    Énumération fermée, dans l'ordre de D10.3 : locale, empruntée, fixe.

    Producteur
    ----------
    ``assess_performances``, ``admit`` (``mountain_perf.backtest.admission``).

    Consommateurs
    -------------
    ``PerformanceAssessment``, ``GuardValue``.

    Non promis
    ----------
    L'ordre local → emprunté → fixe n'est pas recoupé avec les références figées de la
    déclaration (la règle est celle d'``admit``).
    """

    LOCAL = "local"
    BORROWED = "borrowed"
    FIXED = "fixed"


THRESHOLD_SOURCE_DESCRIPTIONS: Mapping[ThresholdSource, str] = MappingProxyType(
    {
        ThresholdSource.LOCAL: (
            "Locale : la référence D8 du parcours, disponible (D10.3, 1)."
        ),
        ThresholdSource.BORROWED: (
            "Empruntée : la référence empruntée figée, pour une performance comparable "
            "(D10.3, 2)."
        ),
        ThresholdSource.FIXED: (
            "Fixe : aucune référence, seuil plancher (D10.3, 3) ; toujours pour "
            "q_usage."
        ),
    }
)


class NonEvaluable(StrEnum):
    """Motif d'une performance non évaluable (``0010`` D10.2 ; précision de M4c-3).

    Champs
    ------
    Valeurs décrites dans ``NON_EVALUABLE_DESCRIPTIONS``.

    Invariants
    ----------
    Énumération fermée, dans l'ordre où la règle les essaie : le premier qui s'applique
    est le motif.

    Producteur
    ----------
    ``assess_performances`` (``mountain_perf.backtest.admission``).

    Consommateurs
    -------------
    ``PerformanceAssessment`` ; le motif de l'ÉCHEC « non évaluable »
    (``run_experiment``).

    Non promis
    ----------
    Seul le premier motif est publié, pas les suivants.
    """

    EXCLUDED = "excluded"
    MULTI_OUTING = "multi_outing"
    UNSCORED = "unscored"
    NO_USAGE = "no_usage"
    INSUFFICIENT_SUPPORT = "insufficient_support"
    ZERO_TIME = "zero_time"
    UNDERREPRESENTED = "underrepresented"
    PASSAGE_UNAVAILABLE = "passage_unavailable"
    NOT_CALIBRATED = "not_calibrated"


NON_EVALUABLE_DESCRIPTIONS: Mapping[NonEvaluable, str] = MappingProxyType(
    {
        NonEvaluable.EXCLUDED: (
            "Exclue : une de ses sorties est l'objet d'une exclusion d'admission "
            "(D10.1)."
        ),
        NonEvaluable.MULTI_OUTING: "Jour multi-sorties (D10.2).",
        NonEvaluable.UNSCORED: "Sortie non scorée : pas d'observation.",
        NonEvaluable.NO_USAGE: (
            "Sans scénario d'usage : la sortie n'a pas de référence (D3)."
        ),
        NonEvaluable.INSUFFICIENT_SUPPORT: (
            "Support insuffisant : support admis vide, ou la classe de la cible "
            "absente."
        ),
        NonEvaluable.ZERO_TIME: (
            "Temps nul sur le support, sous l'horloge déclarée, même hors de la "
            "classe de la cible (D5.5)."
        ),
        NonEvaluable.UNDERREPRESENTED: (
            "Trop peu représentée : moins de 3 segments de la classe de la cible "
            "(D10.2)."
        ),
        NonEvaluable.PASSAGE_UNAVAILABLE: (
            "Passage indisponible : un élément de K indisponible, même de poids nul "
            "(q_usage)."
        ),
        NonEvaluable.NOT_CALIBRATED: (
            "Non calée : la population effective de (0) est vide sous l'horloge et "
            "le scénario déclarés (décision Q1)."
        ),
    }
)


class GuardStatus(StrEnum):
    """État d'un garde-fou (``0010`` D10.4).

    Champs
    ------
    Valeurs décrites dans ``GUARD_STATUS_DESCRIPTIONS``.

    Invariants
    ----------
    Énumération fermée.

    Producteur
    ----------
    ``admit`` (``mountain_perf.backtest.admission``).

    Consommateurs
    -------------
    ``GuardOutcome``, ``PassageGuardOutcome``.

    Non promis
    ----------
    L'état ne dit pas quel jour dépasse : ``FailedCheck`` le dit.
    """

    SATISFIED = "satisfied"
    VIOLATED = "violated"
    UNAVAILABLE = "unavailable"
    NOT_EVALUABLE = "not_evaluable"


GUARD_STATUS_DESCRIPTIONS: Mapping[GuardStatus, str] = MappingProxyType(
    {
        GuardStatus.SATISFIED: "Satisfait : les conditions de D10.4 tiennent, à ε.",
        GuardStatus.VIOLATED: (
            "Dépassé : la moyenne, ou un jour, dépasse son seuil au-delà de ε."
        ),
        GuardStatus.UNAVAILABLE: (
            "Indisponible : une valeur exigée manque ; « à revoir »."
        ),
        GuardStatus.NOT_EVALUABLE: (
            "Non évaluable : exigé nulle part ; pour les passages, « à revoir »."
        ),
    }
)


class ReviewCause(StrEnum):
    """Cause d'un verdict « à revoir » (``0010`` D10.2, D10.4).

    Champs
    ------
    Valeurs décrites dans ``REVIEW_CAUSE_DESCRIPTIONS``.

    Invariants
    ----------
    Énumération fermée, dans l'ordre des causes d'une admission.

    Producteur
    ----------
    ``admit`` (``mountain_perf.backtest.admission``).

    Consommateurs
    -------------
    ``ReviewReason``.

    Non promis
    ----------
    Une cause ne dit pas pourquoi la valeur manque : le motif de la valeur le dit.
    """

    TARGET_UNAVAILABLE = "target_unavailable"
    GUARD_UNAVAILABLE = "guard_unavailable"
    PASSAGES_UNAVAILABLE = "passages_unavailable"
    PASSAGES_NOT_APPLICABLE = "passages_not_applicable"


REVIEW_CAUSE_DESCRIPTIONS: Mapping[ReviewCause, str] = MappingProxyType(
    {
        ReviewCause.TARGET_UNAVAILABLE: (
            "Cible manquante : une performance évaluable sans G_j (D10.2)."
        ),
        ReviewCause.GUARD_UNAVAILABLE: (
            "Garde-fou indisponible : une valeur exigée sans H_jk (D10.4)."
        ),
        ReviewCause.PASSAGES_UNAVAILABLE: (
            "Passages indisponibles : une prévision manque à un passage comparable "
            "(D10.4)."
        ),
        ReviewCause.PASSAGES_NOT_APPLICABLE: (
            "Passages sans objet : aucune performance évaluable n'a de passage "
            "comparable (D10.4)."
        ),
    }
)


class FailedCondition(StrEnum):
    """Condition calculable qui échoue (``0010`` D10.3, D10.4 ; P13).

    Champs
    ------
    Valeurs décrites dans ``FAILED_CONDITION_DESCRIPTIONS``.

    Invariants
    ----------
    Énumération fermée, dans l'ordre des conditions d'une admission.

    Producteur
    ----------
    ``admit`` (``mountain_perf.backtest.admission``).

    Consommateurs
    -------------
    ``FailedCheck``.

    Non promis
    ----------
    Une condition non calculable n'échoue pas : elle rend le verdict « à revoir ».
    """

    MEAN_GAIN = "mean_gain"
    VOTE = "vote"
    LOSS = "loss"
    GUARD = "guard"
    PASSAGES = "passages"


FAILED_CONDITION_DESCRIPTIONS: Mapping[FailedCondition, str] = MappingProxyType(
    {
        FailedCondition.MEAN_GAIN: "Gain moyen : Ḡ < δ̄ − ε (D10.3).",
        FailedCondition.VOTE: (
            "Vote : moins de ⌈3n/4⌉ gains au-dessus de ε, même en comptant les gains "
            "absents (D10.3)."
        ),
        FailedCondition.LOSS: "Perte : G_j < −δ_j − ε sur une performance (D10.3).",
        FailedCondition.GUARD: (
            "Garde-fou : H̄ > η̄ + ε, ou H_jk > 2η_jk + ε un jour (D10.4)."
        ),
        FailedCondition.PASSAGES: (
            "Passages : un dommage relatif au-delà de 1 % + ε à un passage comparable "
            "(D10.4)."
        ),
    }
)


# ---------------------------------------------------------------------------
# Aides privées
# ---------------------------------------------------------------------------


def _gain_threshold(reference: float | None) -> float:
    """``δ_j`` : le plancher sans référence, sinon ``max(GAIN_FLOOR, GAIN_SHARE·F)``."""
    if reference is None:
        return GAIN_FLOOR
    return max(GAIN_FLOOR, GAIN_SHARE * reference)


def _harm_threshold(reference: float | None) -> float:
    """``η_jk`` : le plancher sans référence, sinon
    ``max(HARM_FLOOR, HARM_SHARE·F)``."""
    if reference is None:
        return HARM_FLOOR
    return max(HARM_FLOOR, HARM_SHARE * reference)


def _check_source(
    source: ThresholdSource,
    reference: float | None,
    local_unavailability: Unavailability | None,
) -> None:
    """Une source et sa valeur de référence s'accordent (``0010`` D10.3)."""
    if (source is ThresholdSource.FIXED) != (reference is None):
        raise ContractError(
            f"une source {source} porte une valeur de référence si et seulement si "
            f"elle n'est pas « fixed », reçu {reference!r}."
        )
    if reference is not None:
        require_finite(reference, "reference")
        if not reference >= 0:
            raise ContractError(f"reference doit être >= 0, reçu {reference!r}.")
    if source is ThresholdSource.LOCAL and local_unavailability is not None:
        raise ContractError(
            "une référence locale utilisée n'a pas de motif d'indisponibilité."
        )


def _require_days(days: Sequence[date], name: str) -> None:
    """Une séquence immuable de jours strictement croissants."""
    require_immutable_sequence(days, name)
    if any(b <= a for a, b in pairwise(days)):
        raise ContractError(f"{name} doit être strictement croissant par jour.")


def _close(value: float, expected: float) -> bool:
    """``value`` vaut ``expected`` à ``τ·max(1, |expected|)`` près, comme le calage."""
    return abs(value - expected) <= METRIC_RELATIVE_TOLERANCE * max(1.0, abs(expected))


def _guard_status(values: Sequence[GuardValue]) -> GuardStatus:
    """L'état attendu d'un garde-fou de métrique (``0010`` D10.4 ; décision E2)."""
    if not values:
        return GuardStatus.NOT_EVALUABLE
    harms = [value.harm for value in values]
    if any(harm is None for harm in harms):
        return GuardStatus.UNAVAILABLE
    count = len(values)
    mean_harm = math.fsum(value.harm or 0.0 for value in values) / count
    mean_threshold = math.fsum(value.threshold for value in values) / count
    satisfied = mean_harm <= mean_threshold + NUMERIC_TOLERANCE and all(
        value.harm is not None
        and value.harm <= HARM_MAX_FACTOR * value.threshold + NUMERIC_TOLERANCE
        for value in values
    )
    return GuardStatus.SATISFIED if satisfied else GuardStatus.VIOLATED


def _passage_status(values: Sequence[PassageValue]) -> GuardStatus:
    """L'état attendu du garde-fou des passages (``0010`` D10.4 ; décision E2)."""
    if not values:
        return GuardStatus.NOT_EVALUABLE
    worsts = [value.worst for value in values]
    if any(worst is None for worst in worsts):
        return GuardStatus.UNAVAILABLE
    satisfied = all(
        worst is not None and worst <= PASSAGE_TOLERANCE + NUMERIC_TOLERANCE
        for worst in worsts
    )
    return GuardStatus.SATISFIED if satisfied else GuardStatus.VIOLATED


# ---------------------------------------------------------------------------
# Contrats
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class EffortValue:
    """L'effort calé d'un modèle sous l'horloge déclarée (``0010`` D9.2, D10.5 ;
    décision E1 de M4c-3).

    Champs
    ------
    - ``free`` — sans unité — ``exp(−β)``, l'effort libre.
    - ``bounded`` — sans unité — l'effort borné à ``EFFORT_BOUNDS``, celui du calage.
    - ``saturated`` — sans unité — l'effort libre est hors de ``EFFORT_BOUNDS``.

    Invariants
    ----------
    Dans l'ordre, ``(low, high) = EFFORT_BOUNDS``, ``τ = METRIC_RELATIVE_TOLERANCE`` :

    1. ``free`` et ``bounded`` finis ; ``free > 0`` ;
    2. ``bounded`` vaut ``min(max(free, low), high)`` à ``τ·max(1, ·)`` près ;
    3. hors du voisinage d'une borne (à la même tolérance), ``saturated`` vaut ``free``
       hors de ``[low ; high]`` — indifférent à ``τ`` près d'une borne, comme
       ``ModelCalibration``.

    Producteur
    ----------
    ``assess_performances`` (``mountain_perf.backtest.admission``).

    Consommateurs
    -------------
    ``PerformanceAssessment`` ; les réserves d'``Admission``.

    Non promis
    ----------
    ``free`` n'est pas recoupé avec ``β`` (absent du document).
    """

    free: float
    bounded: float
    saturated: bool

    def __post_init__(self) -> None:
        require_finite(self.free, "free")
        require_finite(self.bounded, "bounded")
        if not self.free > 0:
            raise ContractError(f"free doit être > 0, reçu {self.free!r}.")
        low, high = EFFORT_BOUNDS
        clipped = min(max(self.free, low), high)
        if not _close(self.bounded, clipped):
            raise ContractError(
                f"bounded doit valoir min(max(free, {low}), {high}) = {clipped!r}, "
                f"reçu {self.bounded!r}."
            )
        at_bound = _close(self.free, low) or _close(self.free, high)
        outside = not low <= self.free <= high
        if not at_bound and self.saturated != outside:
            raise ContractError(
                f"saturated vaut free hors de [{low} ; {high}], soit {outside}, reçu "
                f"{self.saturated}."
            )


@dataclass(frozen=True)
class PerformanceAssessment:
    """L'évaluation d'une performance déclarée par une admission (``0010`` D10.2,
    D10.3, D10.5 ; précisions et décisions de M4c-3).

    Champs
    ------
    - ``civil_date`` — jour civil — le jour.
    - ``outing_ids`` — sans unité — ses sorties, dans l'ordre de la performance.
    - ``motif`` — sans unité — pourquoi elle n'est pas évaluable ; absent : évaluable.
    - ``comparable`` — sans unité — « comparable » de D10.3 ; absent : non classée.
    - ``comparable_unavailability`` — sans unité — pourquoi elle n'est pas classée,
      quand (0) est en erreur du modèle (décision E3).
    - ``dplus_per_km`` — m/km — le D+/km du profil de domaine (D2.1) ; absent pour un
      jour multi-sorties.
    - ``projected_s`` — s — la durée projetée de « comparable » (décision Q7).
    - ``source`` — sans unité — la source de ``F_j`` (évaluable seulement).
    - ``local_unavailability`` — sans unité — le motif de la référence locale quand
      elle n'est pas la source (``absent`` sans locale du parcours).
    - ``reference`` — unité de la cible — ``F_j``.
    - ``threshold`` — unité de la cible — ``δ_j``.
    - ``base`` — unité de la cible — la cible de (0) sous l'horloge déclarée.
    - ``candidate`` — unité de la cible — la cible de (1).
    - ``raw`` — unité de la cible — la cible de v0 brut.
    - ``gain`` — unité de la cible — ``G_j = q^(0) − q^(1)``.
    - ``raw_gain`` — unité de la cible — ``G_j^brut = q^(v0 brut) − q^(1)`` (D10.5).
    - ``base_effort`` — sans unité — l'effort de (0), s'il est calé (décision E1).
    - ``candidate_effort`` — sans unité — l'effort de (1), s'il est calé.

    Invariants
    ----------
    Dans l'ordre :

    1. ``outing_ids`` : un tuple non vide de noms non vides, distincts ;
    2. ``motif`` présent : ni ``source``, ni ``local_unavailability``, ni
       ``reference``, ni ``threshold``, ni cible, ni gain, ni effort ;
    3. évaluable : ``source``, ``threshold``, ``base``, ``candidate``, ``raw``
       présents ; la source et ``F`` s'accordent (``F`` absent si et seulement si la
       source est fixe ; ``F`` fini et ``>= 0`` ; une locale utilisée sans motif) ;
       ``threshold == max(0,010 ; 0,25·F)`` (le plancher sans ``F``), au bit ; ``gain``
       absent si ``base`` ou ``candidate`` l'est, sinon exactement ``base −
       candidate`` ; de même ``raw_gain`` avec ``raw`` ;
    4. pour toute performance : ``dplus_per_km`` et ``projected_s`` présents finis et
       ``>= 0`` ; ``comparable_unavailability`` présent : ni ``comparable`` ni
       ``projected_s`` ; ``comparable`` vrai : D+/km dans ``COMPARABLE_DPLUS_PER_KM``
       et ``projected_s <= COMPARABLE_MAX_S``, comparaisons exactes ; une source
       empruntée demande ``comparable`` vrai.

    Producteur
    ----------
    ``assess_performances`` (``mountain_perf.backtest.admission``).

    Consommateurs
    -------------
    ``Admission``.

    Non promis
    ----------
    « Comparable » n'est pas recalculé (l'étiquette d'entraînement n'est pas
    publiée) ; la cible n'est pas recalculée depuis les scores.
    """

    civil_date: date
    outing_ids: tuple[str, ...]
    motif: NonEvaluable | None
    comparable: bool | None
    comparable_unavailability: Unavailability | None
    dplus_per_km: float | None
    projected_s: float | None
    source: ThresholdSource | None
    local_unavailability: Unavailability | None
    reference: float | None
    threshold: float | None
    base: MetricValue | None
    candidate: MetricValue | None
    raw: MetricValue | None
    gain: float | None
    raw_gain: float | None
    base_effort: EffortValue | None
    candidate_effort: EffortValue | None

    def __post_init__(self) -> None:
        self._check_outings()
        if self.motif is not None:
            self._check_not_evaluable()
        else:
            self._check_evaluable()
        self._check_classification()

    def _check_outings(self) -> None:
        require_immutable_sequence(self.outing_ids, "outing_ids")
        if not self.outing_ids:
            raise ContractError("outing_ids ne doit pas être vide.")
        for i, outing_id in enumerate(self.outing_ids):
            require_non_empty(outing_id, f"outing_ids[{i}]")
        if len(set(self.outing_ids)) != len(self.outing_ids):
            raise ContractError("les sorties d'une performance sont distinctes.")

    def _check_not_evaluable(self) -> None:
        fields = (
            self.source,
            self.local_unavailability,
            self.reference,
            self.threshold,
            self.base,
            self.candidate,
            self.raw,
            self.gain,
            self.raw_gain,
            self.base_effort,
            self.candidate_effort,
        )
        if any(field is not None for field in fields):
            raise ContractError(
                f"une performance non évaluable ({self.motif}) n'a ni source, ni motif "
                "de la locale, ni F, ni seuil, ni cible, ni gain, ni effort."
            )

    def _check_evaluable(self) -> None:
        if (
            self.source is None
            or self.threshold is None
            or self.base is None
            or self.candidate is None
            or self.raw is None
        ):
            raise ContractError(
                "une performance évaluable porte source, seuil et les cibles de (0), "
                "de (1) et de v0 brut."
            )
        _check_source(self.source, self.reference, self.local_unavailability)
        expected = _gain_threshold(self.reference)
        if self.threshold != expected:
            raise ContractError(
                f"threshold doit valoir max({GAIN_FLOOR} ; {GAIN_SHARE}·F) = "
                f"{expected!r}, reçu {self.threshold!r} (D10.3)."
            )
        candidate = self.candidate.value
        for name, gain, first in (
            ("gain", self.gain, self.base.value),
            ("raw_gain", self.raw_gain, self.raw.value),
        ):
            if first is None or candidate is None:
                if gain is not None:
                    raise ContractError(
                        f"{name} est absent quand une des deux cibles l'est."
                    )
                continue
            difference = first - candidate
            if gain != difference:
                raise ContractError(
                    f"{name} doit valoir {difference!r}, reçu {gain!r}."
                )

    def _check_classification(self) -> None:
        for name, value in (
            ("dplus_per_km", self.dplus_per_km),
            ("projected_s", self.projected_s),
        ):
            if value is None:
                continue
            require_finite(value, name)
            if not value >= 0:
                raise ContractError(f"{name} doit être >= 0, reçu {value!r}.")
        if self.comparable_unavailability is not None and (
            self.comparable is not None or self.projected_s is not None
        ):
            raise ContractError(
                "une performance non classée (motif de comparabilité) n'a ni "
                "« comparable » ni durée projetée."
            )
        if self.comparable:
            low, high = COMPARABLE_DPLUS_PER_KM
            if (
                self.dplus_per_km is None
                or self.projected_s is None
                or not low <= self.dplus_per_km <= high
                or not self.projected_s <= COMPARABLE_MAX_S
            ):
                raise ContractError(
                    f"une performance comparable a un D+/km dans [{low} ; {high}] et "
                    f"une durée projetée d'au plus {COMPARABLE_MAX_S} s (D10.3)."
                )
        if self.source is ThresholdSource.BORROWED and self.comparable is not True:
            raise ContractError(
                "une référence empruntée ne sert qu'à une performance comparable "
                "(D10.3)."
            )


@dataclass(frozen=True)
class GuardValue:
    """La valeur d'un garde-fou de métrique sur une performance de ``J_k`` (``0010``
    D10.4).

    Champs
    ------
    - ``civil_date`` — jour civil — le jour.
    - ``base`` — unité de la métrique — la métrique de (0) sous l'horloge déclarée.
    - ``candidate`` — unité de la métrique — la métrique de (1).
    - ``harm`` — unité de la métrique — ``H_jk = (q^(1) − q^(0))_+`` ; absent si une
      des deux valeurs l'est.
    - ``source`` — sans unité — la source de ``F_jk``.
    - ``local_unavailability`` — sans unité — le motif de la référence locale quand
      elle n'est pas la source.
    - ``reference`` — unité de la métrique — ``F_jk``, propre à ce garde-fou (P8).
    - ``threshold`` — unité de la métrique — ``η_jk``.

    Invariants
    ----------
    Dans l'ordre : la source et ``F`` s'accordent (comme ``PerformanceAssessment``) ;
    ``threshold == max(0,005 ; 0,10·F)`` (le plancher sans ``F``), au bit ; une des
    deux valeurs absente : ``harm`` absent ; sinon ``harm == max(0, candidate −
    base)``, au bit.

    Producteur
    ----------
    ``admit`` (``mountain_perf.backtest.admission``).

    Consommateurs
    -------------
    ``GuardOutcome``.

    Non promis
    ----------
    La métrique n'est pas recalculée depuis les scores.
    """

    civil_date: date
    base: MetricValue
    candidate: MetricValue
    harm: float | None
    source: ThresholdSource
    local_unavailability: Unavailability | None
    reference: float | None
    threshold: float

    def __post_init__(self) -> None:
        _check_source(self.source, self.reference, self.local_unavailability)
        expected = _harm_threshold(self.reference)
        if self.threshold != expected:
            raise ContractError(
                f"threshold doit valoir max({HARM_FLOOR} ; {HARM_SHARE}·F) = "
                f"{expected!r}, reçu {self.threshold!r} (D10.4)."
            )
        base, candidate = self.base.value, self.candidate.value
        if base is None or candidate is None:
            if self.harm is not None:
                raise ContractError("harm est absent quand une des deux valeurs l'est.")
            return
        harm = max(0.0, candidate - base)
        if self.harm != harm:
            raise ContractError(
                f"harm doit valoir max(0, candidate − base) = {harm!r}, reçu "
                f"{self.harm!r} (D10.4)."
            )


@dataclass(frozen=True)
class GuardOutcome:
    """Un garde-fou de métrique d'une admission (``0010`` D10.4).

    Champs
    ------
    - ``metric`` — sans unité — la métrique du garde-fou.
    - ``values`` — sans unité — ses valeurs sur ``J_k``, dans l'ordre des jours.
    - ``mean_harm`` — unité de la métrique — ``H̄_k = fsum(H) / |J_k|`` ; absent si
      ``J_k`` est vide ou si un ``H`` manque.
    - ``mean_threshold`` — unité de la métrique — ``η̄_k = fsum(η) / |J_k|`` ; absent
      si ``J_k`` est vide.
    - ``status`` — sans unité — son état.

    Invariants
    ----------
    Dans l'ordre, ``ε = NUMERIC_TOLERANCE`` :

    1. ``values`` : un tuple de jours strictement croissants ;
    2. ``mean_harm`` et ``mean_threshold`` valent leurs moyennes, au bit, présentes
       et absentes à leur place ;
    3. ``status`` : ``NOT_EVALUABLE`` si ``J_k`` est vide ; ``UNAVAILABLE`` si un
       ``H`` manque ; sinon ``SATISFIED`` si et seulement si ``H̄ <= η̄ + ε`` et
       ``H <= 2·η + ε`` pour chaque valeur, ``VIOLATED`` sinon.

    Producteur
    ----------
    ``admit`` (``mountain_perf.backtest.admission``).

    Consommateurs
    -------------
    ``Admission``.

    Non promis
    ----------
    ``J_k`` n'est pas recoupé avec l'observation.
    """

    metric: ExperimentMetric
    values: tuple[GuardValue, ...]
    mean_harm: float | None
    mean_threshold: float | None
    status: GuardStatus

    def __post_init__(self) -> None:
        require_immutable_sequence(self.values, "values")
        _require_days(tuple(value.civil_date for value in self.values), "values")
        count = len(self.values)
        harms = [value.harm for value in self.values]
        mean_harm = None
        mean_threshold = None
        if count:
            mean_threshold = math.fsum(value.threshold for value in self.values) / count
            if all(harm is not None for harm in harms):
                mean_harm = math.fsum(harm or 0.0 for harm in harms) / count
        if (self.mean_harm, self.mean_threshold) != (mean_harm, mean_threshold):
            raise ContractError(
                f"les moyennes du garde-fou {self.metric} valent fsum(…) / |J_k| : "
                f"{mean_harm!r} et {mean_threshold!r}, reçu {self.mean_harm!r} et "
                f"{self.mean_threshold!r}."
            )
        expected = _guard_status(self.values)
        if self.status is not expected:
            raise ContractError(
                f"le garde-fou {self.metric} est {expected}, reçu {self.status} "
                "(D10.4)."
            )


@dataclass(frozen=True)
class PassageValue:
    """Le garde-fou des passages sur une performance évaluable (``0010`` D10.4).

    Champs
    ------
    - ``civil_date`` — jour civil — le jour.
    - ``passages`` — sans unité — le nombre de ses passages comparables de ``K``.
    - ``worst`` — sans unité — le plus grand dommage relatif
      ``(|P^(1)_k − T_k| − |P^(0)_k − T_k|)_+ / T_k`` ; absent si une prévision manque.

    Invariants
    ----------
    ``passages >= 1`` ; ``worst`` présent : fini et ``>= 0``.

    Producteur
    ----------
    ``admit`` (``mountain_perf.backtest.admission``).

    Consommateurs
    -------------
    ``PassageGuardOutcome``.

    Non promis
    ----------
    Les dommages de chaque passage ne sont pas publiés (ils se recalculent depuis les
    documents du RÉSULTAT).
    """

    civil_date: date
    passages: int
    worst: float | None

    def __post_init__(self) -> None:
        if not self.passages >= 1:
            raise ContractError(f"passages doit être >= 1, reçu {self.passages}.")
        if self.worst is not None:
            require_finite(self.worst, "worst")
            if not self.worst >= 0:
                raise ContractError(f"worst doit être >= 0, reçu {self.worst!r}.")


@dataclass(frozen=True)
class PassageGuardOutcome:
    """Le garde-fou des passages d'une admission (``0010`` D10.4).

    Champs
    ------
    - ``values`` — sans unité — une valeur par performance évaluable qui a un passage
      comparable, dans l'ordre des jours.
    - ``status`` — sans unité — son état.

    Invariants
    ----------
    ``values`` : un tuple de jours strictement croissants ; ``status`` :
    ``NOT_EVALUABLE`` sans valeur ; ``UNAVAILABLE`` si un ``worst`` manque ; sinon
    ``SATISFIED`` si et seulement si chaque ``worst <= PASSAGE_TOLERANCE + ε``,
    ``VIOLATED`` sinon.

    Producteur
    ----------
    ``admit`` (``mountain_perf.backtest.admission``).

    Consommateurs
    -------------
    ``Admission``.

    Non promis
    ----------
    Les passages comparables ne sont pas recoupés avec l'observation.
    """

    values: tuple[PassageValue, ...]
    status: GuardStatus

    def __post_init__(self) -> None:
        require_immutable_sequence(self.values, "values")
        _require_days(tuple(value.civil_date for value in self.values), "values")
        expected = _passage_status(self.values)
        if self.status is not expected:
            raise ContractError(
                f"le garde-fou des passages est {expected}, reçu {self.status} (D10.4)."
            )


@dataclass(frozen=True)
class ReviewReason:
    """Une cause du verdict « à revoir » (``0010`` D10.2, D10.4).

    Champs
    ------
    - ``cause`` — sans unité — la cause.
    - ``metric`` — sans unité — le garde-fou indisponible (``GUARD_UNAVAILABLE``
      seulement).
    - ``days`` — jours civils — les performances en cause : sans ``G_j``, sans
      ``H_jk``, sans pire dommage ; aucune pour l'absence de passage comparable.

    Invariants
    ----------
    ``days`` : un tuple strictement croissant ; ``metric`` présent si et seulement si
    la cause est ``GUARD_UNAVAILABLE`` ; ``PASSAGES_NOT_APPLICABLE`` ne nomme pas de
    jour, les autres en nomment.

    Producteur
    ----------
    ``admit`` (``mountain_perf.backtest.admission``).

    Consommateurs
    -------------
    ``Admission``.

    Non promis
    ----------
    Le motif de chaque valeur manquante n'est pas répété ici.
    """

    cause: ReviewCause
    metric: ExperimentMetric | None
    days: tuple[date, ...]

    def __post_init__(self) -> None:
        _require_days(self.days, "days")
        if (self.metric is not None) != (self.cause is ReviewCause.GUARD_UNAVAILABLE):
            raise ContractError(
                f"une cause {self.cause} nomme une métrique si et seulement si elle "
                "est guard_unavailable."
            )
        if self.cause is ReviewCause.PASSAGES_NOT_APPLICABLE:
            if self.days:
                raise ContractError(
                    "une cause passages_not_applicable ne nomme pas de jour."
                )
        elif not self.days:
            raise ContractError(f"une cause {self.cause} nomme ses jours.")


@dataclass(frozen=True)
class FailedCheck:
    """Une condition calculable qui échoue (``0010`` D10.3, D10.4 ; P13).

    Champs
    ------
    - ``condition`` — sans unité — la condition.
    - ``metric`` — sans unité — le garde-fou (``GUARD`` seulement).
    - ``days`` — jours civils — les performances qui violent seules la condition :
      perte au-delà de ``δ_j``, ``H_jk > 2·η_jk + ε``, passage au-delà de
      ``1 % + ε`` ; aucune pour le gain moyen et le vote, ni pour un garde-fou dépassé
      par sa seule moyenne.

    Invariants
    ----------
    ``days`` : un tuple strictement croissant ; ``metric`` présent si et seulement si
    la condition est ``GUARD`` ; ``MEAN_GAIN`` et ``VOTE`` sans jour ; ``LOSS`` et
    ``PASSAGES`` avec des jours.

    Producteur
    ----------
    ``admit`` (``mountain_perf.backtest.admission``).

    Consommateurs
    -------------
    ``Admission``.

    Non promis
    ----------
    L'écart de chaque jour à son seuil n'est pas publié (il se lit sur les valeurs).
    """

    condition: FailedCondition
    metric: ExperimentMetric | None
    days: tuple[date, ...]

    def __post_init__(self) -> None:
        _require_days(self.days, "days")
        if (self.metric is not None) != (self.condition is FailedCondition.GUARD):
            raise ContractError(
                f"une condition {self.condition} nomme une métrique si et seulement si "
                "elle est guard."
            )
        dayless = (FailedCondition.MEAN_GAIN, FailedCondition.VOTE)
        dated = (FailedCondition.LOSS, FailedCondition.PASSAGES)
        if self.condition in dayless and self.days:
            raise ContractError(f"la condition {self.condition} ne nomme pas de jour.")
        if self.condition in dated and not self.days:
            raise ContractError(f"la condition {self.condition} nomme ses jours.")


_REGIME_MOTIFS = frozenset(
    {
        NonEvaluable.INSUFFICIENT_SUPPORT,
        NonEvaluable.ZERO_TIME,
        NonEvaluable.UNDERREPRESENTED,
    }
)
"""Les motifs d'observation d'une cible de régime (D10.2)."""


@dataclass(frozen=True)
class Admission:
    """Le document d'admission d'une expérience (``0010`` D10.2 à D10.6, D14 ;
    décision Q4 de M4c-3).

    Champs
    ------
    - ``target`` — sans unité — la cible déclarée.
    - ``clock`` — sans unité — son horloge.
    - ``performances`` — sans unité — chaque performance déclarée, dans l'ordre des
      jours, évaluable ou non.
    - ``evaluable`` — sans unité — ``n``, le nombre de performances évaluables.
    - ``mean_gain`` — unité de la cible — ``Ḡ`` ; absent si un ``G_j`` manque.
    - ``mean_threshold`` — unité de la cible — ``δ̄``.
    - ``positive`` — sans unité — le nombre de ``G_j > ε``.
    - ``required`` — sans unité — ``⌈3n/4⌉``.
    - ``mean_raw_gain`` — unité de la cible — la moyenne des gains contre v0 brut ;
      absente si l'un manque (décision E5).
    - ``raw_gains`` — sans unité — le nombre de gains contre v0 brut qui existent.
    - ``guards`` — sans unité — les garde-fous de ``GUARD_METRICS`` sans la cible,
      dans cet ordre.
    - ``passages`` — sans unité — le garde-fou des passages.
    - ``review`` — sans unité — les causes de « à revoir ».
    - ``failures`` — sans unité — les conditions calculables qui échouent.
    - ``verdict`` — sans unité — le verdict.
    - ``reserves`` — sans unité — ses réserves.

    Invariants
    ----------
    Dans l'ordre, ``ε = NUMERIC_TOLERANCE``, « évaluables » = les performances sans
    motif, dans l'ordre :

    1. ``performances``, ``guards``, ``review``, ``failures``, ``reserves`` sont des
       tuples ; ``target`` n'est pas ``|L|`` ; ``performances`` non vide, de jours
       strictement croissants ;
    2. au moins une évaluable (``n = 0`` : aucun document, un ÉCHEC « non
       évaluable ») ; ``evaluable`` est leur nombre ; ``required ==
       required_successes(evaluable)`` ;
    3. sous ``q_usage``, aucun motif de support, de temps nul ou de sous-représentation
       ; sous une autre cible, pas de ``passage_unavailable`` ; sous ``q_usage``,
       chaque évaluable a la source fixe sans motif de la locale ; sous une autre
       cible, une source autre que locale porte le motif de la locale (P6) ;
    4. ``(mean_threshold, mean_gain, positive, mean_raw_gain, raw_gains)`` vaut, au
       bit, ``(fsum(δ)/n, fsum(G)/n`` si les ``n`` existent sinon absent, ``#{G > ε}``,
       ``fsum(G^brut)/n`` si les ``n`` existent sinon absent, ``#{G^brut présents})`` ;
    5. les métriques des garde-fous sont ``GUARD_METRICS`` sans la cible, dans cet
       ordre ; leurs jours sont évaluables ; ``|L|`` porte tous les jours évaluables ;
       une valeur de source autre que locale porte le motif de la locale ; une source
       empruntée demande une performance comparable ; les jours des passages sont
       évaluables ;
    6. ``review`` vaut, dans cet ordre : ``TARGET_UNAVAILABLE`` (jours évaluables sans
       ``G_j``) s'il y en a ; un ``GUARD_UNAVAILABLE`` par garde-fou indisponible
       (jours sans ``H``) ; ``PASSAGES_UNAVAILABLE`` (jours sans ``worst``) si les
       passages sont indisponibles, ou ``PASSAGES_NOT_APPLICABLE`` s'ils ne sont pas
       évaluables ;
    7. ``failures`` vaut, dans cet ordre : ``MEAN_GAIN`` si ``Ḡ`` existe et ``Ḡ < δ̄ −
       ε`` ; ``VOTE`` si ``positive`` plus le nombre de ``G_j`` absents est sous
       ``required`` ; ``LOSS`` (jours où ``G_j < −δ_j − ε``) s'il y en a ; pour chaque
       garde-fou, ``GUARD`` (jours où ``H > 2·η + ε``) s'il est ``VIOLATED`` ou si de
       tels jours existent ; ``PASSAGES`` (jours où ``worst > 0,01 + ε``) de même ;
    8. ``verdict`` : ``TO_REVIEW`` si ``review`` n'est pas vide, sinon ``REJECTED`` si
       ``failures`` n'est pas vide, sinon ``PROVISIONAL`` ;
    9. ``reserves`` : ``COMPARATOR_SATURATED`` si une évaluable a l'effort de (0)
       saturé, ``CANDIDATE_SATURATED`` de même pour (1), puis
       ``SENSITIVITY_REMAINING``, dans cet ordre.

    Producteur
    ----------
    ``admit`` (``mountain_perf.backtest.admission``).

    Consommateurs
    -------------
    ``append_result`` (document cité par ``Result.admission``) ; la relecture du
    registre.

    Non promis
    ----------
    Les évaluations ne sont pas recalculées depuis les scores et les références (la
    règle est celle d'``admit``) ; la cible et l'horloge sont recoupées avec la
    déclaration par l'accord du registre.
    """

    target: ExperimentMetric
    clock: Clock
    performances: tuple[PerformanceAssessment, ...]
    evaluable: int
    mean_gain: float | None
    mean_threshold: float
    positive: int
    required: int
    mean_raw_gain: float | None
    raw_gains: int
    guards: tuple[GuardOutcome, ...]
    passages: PassageGuardOutcome
    review: tuple[ReviewReason, ...]
    failures: tuple[FailedCheck, ...]
    verdict: AdmissionVerdict
    reserves: tuple[AdmissionReserve, ...]

    def __post_init__(self) -> None:
        self._check_form()
        evaluable = self._evaluable()
        self._check_count(evaluable)
        self._check_sources()
        self._check_aggregates(evaluable)
        self._check_guards(evaluable)
        review = self._expected_review(evaluable)
        if self.review != review:
            raise ContractError(
                f"review vaut {review!r}, reçu {self.review!r} (D10.2, D10.4)."
            )
        failures = self._expected_failures(evaluable)
        if self.failures != failures:
            raise ContractError(
                f"failures vaut {failures!r}, reçu {self.failures!r} (D10.3, D10.4)."
            )
        if self.review:
            verdict = AdmissionVerdict.TO_REVIEW
        elif self.failures:
            verdict = AdmissionVerdict.REJECTED
        else:
            verdict = AdmissionVerdict.PROVISIONAL
        if self.verdict is not verdict:
            raise ContractError(
                f"le verdict est {verdict}, reçu {self.verdict} (D10.6)."
            )
        self._check_reserves(evaluable)

    def _check_form(self) -> None:
        for name in ("performances", "guards", "review", "failures", "reserves"):
            require_immutable_sequence(getattr(self, name), name)
        if self.target is ExperimentMetric.LEVEL:
            raise ContractError("|L| n'est pas une cible (D10.1).")
        if not self.performances:
            raise ContractError("performances ne doit pas être vide.")
        days = [performance.civil_date for performance in self.performances]
        if any(b <= a for a, b in pairwise(days)):
            raise ContractError(
                "performances doit être strictement croissant par jour."
            )

    def _evaluable(self) -> tuple[PerformanceAssessment, ...]:
        return tuple(
            performance
            for performance in self.performances
            if performance.motif is None
        )

    def _check_count(self, evaluable: tuple[PerformanceAssessment, ...]) -> None:
        if not evaluable:
            raise ContractError(
                "une admission a au moins une performance évaluable (n = 0 : aucun "
                "document, un ÉCHEC « non évaluable », D10.2)."
            )
        if self.evaluable != len(evaluable):
            raise ContractError(
                f"evaluable compte les performances évaluables, {len(evaluable)}, "
                f"reçu {self.evaluable}."
            )
        required = required_successes(self.evaluable)
        if self.required != required:
            raise ContractError(
                f"required vaut ⌈3n/4⌉ = {required}, reçu {self.required} (D10.3)."
            )

    def _check_sources(self) -> None:
        usage = self.target is ExperimentMetric.USAGE
        for performance in self.performances:
            motif = performance.motif
            if motif is None:
                continue
            if (usage and motif in _REGIME_MOTIFS) or (
                not usage and motif is NonEvaluable.PASSAGE_UNAVAILABLE
            ):
                raise ContractError(
                    f"le {performance.civil_date.isoformat()}, le motif {motif} "
                    f"n'existe pas pour la cible {self.target} (D10.2)."
                )
        for performance in self.performances:
            if performance.motif is not None:
                continue
            day = performance.civil_date.isoformat()
            source = performance.source
            if usage:
                if (
                    source is not ThresholdSource.FIXED
                    or performance.local_unavailability is not None
                ):
                    raise ContractError(
                        "q_usage a le seuil fixe pour toute performance, sans motif de "
                        f"la locale (D10.3), reçu {source} le {day}."
                    )
            elif (
                source is not ThresholdSource.LOCAL
                and performance.local_unavailability is None
            ):
                raise ContractError(
                    f"le {day}, la source {source} porte le motif de la référence "
                    "locale (P6)."
                )

    def _check_aggregates(self, evaluable: tuple[PerformanceAssessment, ...]) -> None:
        n = len(evaluable)
        gains = [performance.gain for performance in evaluable]
        raw_gains = [performance.raw_gain for performance in evaluable]
        present = [gain for gain in gains if gain is not None]
        raw_present = [gain for gain in raw_gains if gain is not None]
        expected = (
            math.fsum(performance.threshold or 0.0 for performance in evaluable) / n,
            math.fsum(present) / n if len(present) == n else None,
            sum(1 for gain in present if gain > NUMERIC_TOLERANCE),
            math.fsum(raw_present) / n if len(raw_present) == n else None,
            len(raw_present),
        )
        received = (
            self.mean_threshold,
            self.mean_gain,
            self.positive,
            self.mean_raw_gain,
            self.raw_gains,
        )
        if received != expected:
            raise ContractError(
                "mean_threshold, mean_gain, positive, mean_raw_gain et raw_gains "
                f"valent {expected!r}, reçu {received!r} (D10.3, D10.5)."
            )

    def _check_guards(self, evaluable: tuple[PerformanceAssessment, ...]) -> None:
        metrics = tuple(metric for metric in GUARD_METRICS if metric is not self.target)
        if tuple(guard.metric for guard in self.guards) != metrics:
            raise ContractError(
                f"guards porte {', '.join(metrics)}, dans cet ordre (D10.4)."
            )
        by_day = {performance.civil_date: performance for performance in evaluable}
        for guard in self.guards:
            if any(value.civil_date not in by_day for value in guard.values):
                raise ContractError(
                    f"le garde-fou {guard.metric} porte un jour non évaluable."
                )
        level = self.guards[0]
        if tuple(value.civil_date for value in level.values) != tuple(by_day):
            raise ContractError(
                "|L| est exigé sur toute performance évaluable (D10.4)."
            )
        for guard in self.guards:
            for value in guard.values:
                day = value.civil_date.isoformat()
                if (
                    value.source is not ThresholdSource.LOCAL
                    and value.local_unavailability is None
                ):
                    raise ContractError(
                        f"le {day}, la source {value.source} du garde-fou "
                        f"{guard.metric} porte le motif de la référence locale (P6)."
                    )
                if (
                    value.source is ThresholdSource.BORROWED
                    and by_day[value.civil_date].comparable is not True
                ):
                    raise ContractError(
                        f"le {day}, une référence empruntée du garde-fou "
                        f"{guard.metric} ne sert qu'à une performance comparable "
                        "(D10.3, D10.4)."
                    )
        if any(value.civil_date not in by_day for value in self.passages.values):
            raise ContractError(
                "le garde-fou des passages porte un jour non évaluable."
            )

    def _expected_review(
        self, evaluable: tuple[PerformanceAssessment, ...]
    ) -> tuple[ReviewReason, ...]:
        review: list[ReviewReason] = []
        missing = tuple(
            performance.civil_date
            for performance in evaluable
            if performance.gain is None
        )
        if missing:
            review.append(ReviewReason(ReviewCause.TARGET_UNAVAILABLE, None, missing))
        for guard in self.guards:
            if guard.status is GuardStatus.UNAVAILABLE:
                days = tuple(
                    value.civil_date for value in guard.values if value.harm is None
                )
                review.append(
                    ReviewReason(ReviewCause.GUARD_UNAVAILABLE, guard.metric, days)
                )
        if self.passages.status is GuardStatus.UNAVAILABLE:
            days = tuple(
                value.civil_date
                for value in self.passages.values
                if value.worst is None
            )
            review.append(ReviewReason(ReviewCause.PASSAGES_UNAVAILABLE, None, days))
        elif self.passages.status is GuardStatus.NOT_EVALUABLE:
            review.append(ReviewReason(ReviewCause.PASSAGES_NOT_APPLICABLE, None, ()))
        return tuple(review)

    def _expected_failures(
        self, evaluable: tuple[PerformanceAssessment, ...]
    ) -> tuple[FailedCheck, ...]:
        failures: list[FailedCheck] = []
        epsilon = NUMERIC_TOLERANCE
        if self.mean_gain is not None and not (
            self.mean_gain >= self.mean_threshold - epsilon
        ):
            failures.append(FailedCheck(FailedCondition.MEAN_GAIN, None, ()))
        absent = sum(1 for performance in evaluable if performance.gain is None)
        if self.positive + absent < self.required:
            failures.append(FailedCheck(FailedCondition.VOTE, None, ()))
        losses = tuple(
            performance.civil_date
            for performance in evaluable
            if performance.gain is not None
            and not performance.gain >= -(performance.threshold or 0.0) - epsilon
        )
        if losses:
            failures.append(FailedCheck(FailedCondition.LOSS, None, losses))
        for guard in self.guards:
            days = tuple(
                value.civil_date
                for value in guard.values
                if value.harm is not None
                and not value.harm <= HARM_MAX_FACTOR * value.threshold + epsilon
            )
            if guard.status is GuardStatus.VIOLATED or days:
                failures.append(FailedCheck(FailedCondition.GUARD, guard.metric, days))
        days = tuple(
            value.civil_date
            for value in self.passages.values
            if value.worst is not None
            and not value.worst <= PASSAGE_TOLERANCE + epsilon
        )
        if self.passages.status is GuardStatus.VIOLATED or days:
            failures.append(FailedCheck(FailedCondition.PASSAGES, None, days))
        return tuple(failures)

    def _check_reserves(self, evaluable: tuple[PerformanceAssessment, ...]) -> None:
        reserves: list[AdmissionReserve] = []
        if any(
            performance.base_effort is not None and performance.base_effort.saturated
            for performance in evaluable
        ):
            reserves.append(AdmissionReserve.COMPARATOR_SATURATED)
        if any(
            performance.candidate_effort is not None
            and performance.candidate_effort.saturated
            for performance in evaluable
        ):
            reserves.append(AdmissionReserve.CANDIDATE_SATURATED)
        reserves.append(AdmissionReserve.SENSITIVITY_REMAINING)
        if self.reserves != tuple(reserves):
            expected = [reserve.value for reserve in reserves]
            received = [reserve.value for reserve in self.reserves]
            raise ContractError(
                f"reserves vaut {expected}, reçu {received} (D10.5, D10.6)."
            )
