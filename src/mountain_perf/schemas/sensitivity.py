"""Contrats de la sensibilité : comparaison des configurations de D13 à leur
comparateur, réserves d'une expérience (M4d-3).

Protocole : ``docs/decisions/0010`` D13 (et sa précision de M4d-3), D7, D10.2 à D10.6,
D14 (format 5). Pour chaque configuration de la sensibilité, la comparaison à trois axes
de chaque performance avec le **comparateur** — ``(250, 30, écoulé)`` pour ``just
backtest``, ``(250, 30, horloge déclarée)`` pour une expérience — : disponibilité,
support effectif, valeur ; pour une expérience, l'admission refaite sous la
configuration, les gains comparés, l'ensemble commun, et les réserves de la sensibilité.

Contrats **stockés** (format 5) : un document ``SensitivityOutcome`` par RÉSULTAT de
sensibilité. Aucun calcul ici hors la vérification des invariants : les producteurs
vivent dans ``mountain_perf.backtest.sensitivity``.
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from enum import StrEnum
from itertools import pairwise
from types import MappingProxyType

from mountain_perf.schemas.admission import (
    NUMERIC_TOLERANCE,
    Admission,
    AdmissionVerdict,
    GuardStatus,
    NonEvaluable,
    PerformanceAssessment,
)
from mountain_perf.schemas.calibration import CALIBRATED_KINDS, ModelKind
from mountain_perf.schemas.matching import SensitivityConfiguration
from mountain_perf.schemas.metrics import MetricValue
from mountain_perf.validation import (
    ContractError,
    require_finite,
    require_immutable_sequence,
    require_non_empty,
)


class Availability(StrEnum):
    """Axe (i) de la comparaison : la disponibilité d'une valeur au comparateur et sous
    la configuration (``0010`` D13 ; précision de M4d-3).

    Champs
    ------
    Valeurs décrites dans ``AVAILABILITY_DESCRIPTIONS``.

    Invariants
    ----------
    Énumération fermée ; elle se lit sur la présence des deux valeurs, jamais sur leur
    motif.

    Producteur
    ----------
    ``compare_metric`` (``mountain_perf.backtest.sensitivity``).

    Consommateurs
    -------------
    ``MetricComparison`` ; le rapport de sensibilité.

    Non promis
    ----------
    Deux valeurs indisponibles peuvent l'être à des motifs différents : les motifs
    restent dans les valeurs comparées.
    """

    BOTH = "both_available"
    LOST = "lost"
    GAINED = "gained"
    NEITHER = "both_unavailable"


AVAILABILITY_DESCRIPTIONS: Mapping[Availability, str] = MappingProxyType(
    {
        Availability.BOTH: "Disponible au comparateur et sous la configuration.",
        Availability.LOST: (
            "Disponible au comparateur, indisponible sous la configuration."
        ),
        Availability.GAINED: (
            "Indisponible au comparateur, disponible sous la configuration."
        ),
        Availability.NEITHER: "Indisponible des deux côtés, chacun à son motif.",
    }
)


class SupportComponent(StrEnum):
    """Axe (ii) de la comparaison : une composante du support effectif d'une métrique
    (``0010`` D13 ; précision de M4d-3, amendement de l'expert D13-A).

    Champs
    ------
    Valeurs décrites dans ``SUPPORT_COMPONENT_DESCRIPTIONS``.

    Invariants
    ----------
    Énumération fermée ; l'ordre est celui de la publication.

    Producteur
    ----------
    ``compare_metric`` (``mountain_perf.backtest.sensitivity``).

    Consommateurs
    -------------
    ``MetricComparison`` ; le rapport de sensibilité.

    Non promis
    ----------
    Une composante égale ne dit pas que la valeur l'est ; un effectif égal ne dit
    jamais qu'un support l'est.
    """

    SEGMENTS = "segments"
    ZERO_TIMES = "zero_times"
    POINTS = "points"
    TARGETS = "targets"
    POPULATION = "population"


SUPPORT_COMPONENT_DESCRIPTIONS: Mapping[SupportComponent, str] = MappingProxyType(
    {
        SupportComponent.SEGMENTS: (
            "Segments admis : bornes effectives et classes (de la classe, pour une "
            "métrique de régime)."
        ),
        SupportComponent.ZERO_TIMES: (
            "Segments admis de temps nul sous l'horloge : leurs bornes (D5.5)."
        ),
        SupportComponent.POINTS: (
            "Points de C_k (D7.3) : abscisses, motifs, et temps nul sous l'horloge."
        ),
        SupportComponent.TARGETS: (
            "Éléments de K (D7.4) : membres, abscisses, motifs, et temps nul "
            "sous l'horloge."
        ),
        SupportComponent.POPULATION: (
            "Population de calage du modèle sous l'horloge, en usage : C_j^eff et "
            "ses retraits (D9.2) ; modèles calés seulement."
        ),
    }
)


class SensitivityMetric(StrEnum):
    """Une métrique comparée par la sensibilité : les métriques d'usage de D15 sous
    l'horloge de la configuration (``0010`` D7, D15 ; précision de D13, M4d-3).

    Champs
    ------
    Valeurs décrites dans ``SENSITIVITY_METRIC_DESCRIPTIONS``.

    Invariants
    ----------
    Énumération fermée ; l'ordre est celui de la publication, dans chaque modèle.

    Producteur
    ----------
    ``compare_performance`` (``mountain_perf.backtest.sensitivity``).

    Consommateurs
    -------------
    ``MetricComparison`` ; le rapport de sensibilité.

    Non promis
    ----------
    ``|L|`` n'est pas comparé à part : c'est la valeur absolue de ``L``.
    """

    LEVEL = "level"
    ASCENT_LEVEL = "ascent_level"
    FLAT_LEVEL = "flat_level"
    DESCENT_LEVEL = "descent_level"
    ASCENT_DISPERSION = "ascent_dispersion"
    FLAT_DISPERSION = "flat_dispersion"
    DESCENT_DISPERSION = "descent_dispersion"
    MAX_ABS_PASSAGE_ERROR = "max_abs_passage_error_s"
    USAGE = "q_usage"


SENSITIVITY_METRIC_DESCRIPTIONS: Mapping[SensitivityMetric, str] = MappingProxyType(
    {
        SensitivityMetric.LEVEL: "L, le niveau de tout le support admis (D7.2).",
        SensitivityMetric.ASCENT_LEVEL: "E_R de la montée (D7.2).",
        SensitivityMetric.FLAT_LEVEL: "E_R du plat (D7.2).",
        SensitivityMetric.DESCENT_LEVEL: "E_R de la descente (D7.2).",
        SensitivityMetric.ASCENT_DISPERSION: "D_R de la montée (D7.2).",
        SensitivityMetric.FLAT_DISPERSION: "D_R du plat (D7.2).",
        SensitivityMetric.DESCENT_DISPERSION: "D_R de la descente (D7.2).",
        SensitivityMetric.MAX_ABS_PASSAGE_ERROR: (
            "max |C_k|, sur les points de D7.3 (secondes)."
        ),
        SensitivityMetric.USAGE: "q_usage, sur le K par défaut (D7.4).",
    }
)

METRIC_COMPONENTS: Mapping[SensitivityMetric, tuple[SupportComponent, ...]] = (
    MappingProxyType(
        {
            **{
                metric: (
                    SupportComponent.SEGMENTS,
                    SupportComponent.ZERO_TIMES,
                    SupportComponent.POPULATION,
                )
                for metric in tuple(SensitivityMetric)[:7]
            },
            SensitivityMetric.MAX_ABS_PASSAGE_ERROR: (
                SupportComponent.POINTS,
                SupportComponent.POPULATION,
            ),
            SensitivityMetric.USAGE: (
                SupportComponent.TARGETS,
                SupportComponent.POPULATION,
            ),
        }
    )
)
"""Les composantes du support effectif de chaque métrique (précision de D13, M4d-3),
dans l'ordre de ``SupportComponent`` ; ``POPULATION`` ne vaut que pour un modèle
calé."""


class PerformanceMotif(StrEnum):
    """Pourquoi une performance n'a pas de valeurs comparées (``0010`` D0, D3 ;
    précision de D15, M4b-5) — un motif qui ne dépend que du manifeste, donc le même
    sous toutes les configurations.

    Champs
    ------
    Valeurs décrites dans ``PERFORMANCE_MOTIF_DESCRIPTIONS``.

    Invariants
    ----------
    Énumération fermée.

    Producteur
    ----------
    ``compare_performance`` (``mountain_perf.backtest.sensitivity``).

    Consommateurs
    -------------
    ``PerformanceComparison`` ; le rapport de sensibilité.

    Non promis
    ----------
    Rien sur les sorties d'un jour de plusieurs sorties.
    """

    NOT_SCORED = "not_scored"
    NO_REFERENCE = "no_reference"
    MULTI_OUTING = "multi_outing_day"


PERFORMANCE_MOTIF_DESCRIPTIONS: Mapping[PerformanceMotif, str] = MappingProxyType(
    {
        PerformanceMotif.NOT_SCORED: "Sortie non scorée (non tracée, ou refusée).",
        PerformanceMotif.NO_REFERENCE: "Sortie sans référence : pas d'usage (D3).",
        PerformanceMotif.MULTI_OUTING: "Jour de plusieurs sorties (D0).",
    }
)


class SensitivityReserve(StrEnum):
    """Une réserve de la sensibilité d'une expérience (``0010`` D13, D10.6 ; précision
    de M4d-3, amendements de l'expert D13-B, D13-C).

    Champs
    ------
    Valeurs décrites dans ``SENSITIVITY_RESERVE_DESCRIPTIONS``.

    Invariants
    ----------
    Énumération fermée ; les réserves se cumulent, dans cet ordre.

    Producteur
    ----------
    ``sensitivity_outcome``.

    Consommateurs
    -------------
    ``ReserveEntry`` ; la vue composée ; le rapport.

    Non promis
    ----------
    Une réserve ne change pas le verdict (D13 : « jamais utilisée pour choisir ») ;
    « sensibilité incomplète », « restante » ou « faite » ne sont pas des réserves : ce
    sont des états de la vue composée (D10.6), jamais stockés.
    """

    SIGN_CHANGED = "sensitivity_sign_changed"
    VERDICT_CHANGED = "sensitivity_verdict_changed"
    EVALUABILITY_LOST = "sensitivity_evaluability_lost"
    SIGN_UNVERIFIABLE = "sensitivity_sign_unverifiable"


SENSITIVITY_RESERVE_DESCRIPTIONS: Mapping[SensitivityReserve, str] = MappingProxyType(
    {
        SensitivityReserve.SIGN_CHANGED: (
            "Sensibilité : signe changé — la classe de Ḡ, ou celle d'un G_j "
            "comparable, change du comparateur à une configuration."
        ),
        SensitivityReserve.VERDICT_CHANGED: (
            "Sensibilité : verdict modifié — une configuration n'a pas le verdict du "
            "comparateur (aucune décision comprise)."
        ),
        SensitivityReserve.EVALUABILITY_LOST: (
            "Sensibilité : évaluabilité perdue — une performance évaluable au "
            "comparateur ne l'est plus, ou un garde-fou calculé au comparateur ne "
            "l'est plus."
        ),
        SensitivityReserve.SIGN_UNVERIFIABLE: (
            "Sensibilité : signe non vérifiable — une configuration sans aucun gain "
            "comparable."
        ),
    }
)

DOCUMENT_RESERVES: tuple[SensitivityReserve, ...] = tuple(SensitivityReserve)
"""Les réserves qu'un document de sensibilité peut porter, dans cet ordre : toutes."""

_COMPUTED_GUARD = frozenset({GuardStatus.SATISFIED, GuardStatus.VIOLATED})


def sign_class(gain: float) -> int:
    """La classe de signe d'un gain (précision de D13, M4d-3 ; D10.3) : ``+1`` si
    ``gain > ε``, ``−1`` si ``gain < −ε``, ``0`` sinon, ``ε = 1e−6``
    (``NUMERIC_TOLERANCE``) ; les bornes sont dans la classe zéro."""
    if gain > NUMERIC_TOLERANCE:
        return 1
    if gain < -NUMERIC_TOLERANCE:
        return -1
    return 0


def _availability(comparator: MetricValue, value: MetricValue) -> Availability:
    if comparator.available:
        return Availability.BOTH if value.available else Availability.LOST
    return Availability.GAINED if value.available else Availability.NEITHER


@dataclass(frozen=True)
class MetricComparison:
    """Une métrique d'un modèle sur une performance, sous une configuration, comparée au
    comparateur (``0010`` D13 ; précision de M4d-3).

    Champs
    ------
    - ``model`` — sans unité — le modèle.
    - ``metric`` — sans unité — la métrique.
    - ``comparator`` — unité de la métrique — sa valeur, ou son motif, au comparateur.
    - ``value`` — unité de la métrique — sa valeur, ou son motif, sous la
      configuration.
    - ``availability`` — sans unité — l'axe (i).
    - ``support`` — sans unité — l'axe (ii) : les composantes du support effectif qui
      changent, parmi celles de la métrique (``METRIC_COMPONENTS``).
    - ``difference`` — unité de la métrique — l'axe (iii) : ``value − comparator``,
      quand les deux sont présentes.

    Invariants
    ----------
    - ``availability`` est celle que donnent les présences des deux valeurs ;
    - ``support`` est un tuple, sous-suite de ``METRIC_COMPONENTS[metric]`` (ordre,
      sans doublon) ; ``POPULATION`` seulement pour un modèle calé ;
    - ``difference`` présent **si et seulement si** les deux valeurs le sont, et vaut
      ``value.value − comparator.value`` au bit.

    Producteur
    ----------
    ``compare_metric`` (``mountain_perf.backtest.sensitivity``).

    Consommateurs
    -------------
    ``PerformanceComparison`` ; le rapport de sensibilité.

    Non promis
    ----------
    Le contrat ne relit pas les supports : leurs composantes changées sont celles du
    producteur ; l'écart ne prétend pas isoler l'effet du support.
    """

    model: ModelKind
    metric: SensitivityMetric
    comparator: MetricValue
    value: MetricValue
    availability: Availability
    support: tuple[SupportComponent, ...]
    difference: float | None

    def __post_init__(self) -> None:
        expected = _availability(self.comparator, self.value)
        if self.availability is not expected:
            raise ContractError(
                f"availability vaut {expected}, reçu {self.availability} (D13)."
            )
        require_immutable_sequence(self.support, "support")
        allowed = METRIC_COMPONENTS[self.metric]
        ranks = []
        for component in self.support:
            if component not in allowed:
                raise ContractError(
                    f"{component} n'est pas une composante du support de "
                    f"{self.metric} ({[c.value for c in allowed]})."
                )
            ranks.append(allowed.index(component))
        for previous, current in pairwise(ranks):
            if not previous < current:
                raise ContractError(
                    "support suit l'ordre de METRIC_COMPONENTS, sans doublon."
                )
        if (
            SupportComponent.POPULATION in self.support
            and self.model not in CALIBRATED_KINDS
        ):
            raise ContractError(
                f"{self.model} n'est pas calé : sa population ne change pas (D9.2)."
            )
        both = self.comparator.value is not None and self.value.value is not None
        if (self.difference is not None) != both:
            raise ContractError(
                "difference est présent si et seulement si les deux valeurs le sont."
            )
        if self.difference is not None:
            assert self.comparator.value is not None  # both
            assert self.value.value is not None
            require_finite(self.difference, "difference")
            if self.difference != self.value.value - self.comparator.value:
                raise ContractError(
                    "difference vaut value − comparator, au bit, reçu "
                    f"{self.difference}."
                )


@dataclass(frozen=True)
class PerformanceComparison:
    """Une performance déclarée, sous une configuration, comparée au comparateur
    (``0010`` D13 ; précision de M4d-3).

    Champs
    ------
    - ``civil_date`` — date — le jour de la performance.
    - ``outing_id`` — sans unité — sa première sortie.
    - ``motif`` — sans unité — pourquoi elle n'a pas de valeurs comparées ; absent si
      elle en a.
    - ``metrics`` — sans unité — les comparaisons, modèle par modèle, chaque modèle
      dans l'ordre de ``SensitivityMetric``.

    Invariants
    ----------
    - ``outing_id`` non vide ; ``metrics`` est un tuple ;
    - ``motif`` présent **si et seulement si** ``metrics`` est vide ;
    - ``metrics`` : par groupes consécutifs d'un modèle, chacun portant toutes les
      métriques de ``SensitivityMetric``, dans l'ordre ; des modèles distincts.

    Producteur
    ----------
    ``compare_performance`` (``mountain_perf.backtest.sensitivity``).

    Consommateurs
    -------------
    ``ConfigurationOutcome`` ; le rapport de sensibilité.

    Non promis
    ----------
    Le contrat ne dit pas dans quel ordre les modèles viennent : c'est celui de la
    déclaration, que ``SensitivityOutcome`` rend commun.
    """

    civil_date: date
    outing_id: str
    motif: PerformanceMotif | None
    metrics: tuple[MetricComparison, ...]

    def __post_init__(self) -> None:
        require_non_empty(self.outing_id, "outing_id")
        require_immutable_sequence(self.metrics, "metrics")
        if (self.motif is None) == (not self.metrics):
            raise ContractError(
                "motif est présent si et seulement si metrics est vide, reçu "
                f"motif={self.motif} et {len(self.metrics)} comparaisons."
            )
        order = tuple(SensitivityMetric)
        if len(self.metrics) % len(order):
            raise ContractError(
                f"metrics porte {len(order)} métriques par modèle, reçu "
                f"{len(self.metrics)} comparaisons."
            )
        models: list[ModelKind] = []
        for start in range(0, len(self.metrics), len(order)):
            group = self.metrics[start : start + len(order)]
            model = group[0].model
            if any(c.model is not model for c in group):
                raise ContractError(
                    f"metrics : le groupe {start // len(order)} mêle plusieurs modèles."
                )
            if tuple(c.metric for c in group) != order:
                raise ContractError(
                    f"metrics : les métriques de {model} suivent l'ordre de "
                    "SensitivityMetric, toutes."
                )
            if model in models:
                raise ContractError(f"metrics : {model} porté deux fois.")
            models.append(model)

    @property
    def models(self) -> tuple[ModelKind, ...]:
        """Les modèles comparés, dans l'ordre."""
        step = len(SensitivityMetric)
        return tuple(self.metrics[i].model for i in range(0, len(self.metrics), step))


@dataclass(frozen=True)
class GainComparison:
    """Le gain d'une performance déclarée, au comparateur et sous une configuration
    (``0010`` D10.2, D13 ; précision de M4d-3, amendement D13-B).

    Champs
    ------
    - ``civil_date`` — date — le jour de la performance.
    - ``comparator_gain`` — sans unité — ``G_j`` au comparateur ; absent si la
      performance n'y est pas évaluable ou si ``G_j`` y manque.
    - ``comparator_motif`` — sans unité — son motif de non-évaluabilité au comparateur.
    - ``gain`` — sans unité — ``G_j`` sous la configuration ; absent de même.
    - ``motif`` — sans unité — son motif de non-évaluabilité sous la configuration.
    - ``comparator_class``, ``gain_class`` — sans unité — leurs classes de signe
      (``sign_class``), présentes avec leur gain.

    Propriétés calculées (jamais stockées) : ``comparable`` (les deux gains présents),
    ``class_changed``.

    Invariants
    ----------
    - un gain présent : fini, et la performance est évaluable de ce côté (motif
      absent) ;
    - chaque classe présente **si et seulement si** son gain l'est, et vaut
      ``sign_class`` du gain.

    Producteur
    ----------
    ``compare_gains`` (``mountain_perf.backtest.sensitivity``).

    Consommateurs
    -------------
    ``ConfigurationOutcome`` ; le rapport.

    Non promis
    ----------
    Une valeur absente n'est jamais un zéro : une paire sans les deux gains n'est pas
    comparable, et son motif reste visible (D13-F).
    """

    civil_date: date
    comparator_gain: float | None
    comparator_motif: NonEvaluable | None
    gain: float | None
    motif: NonEvaluable | None
    comparator_class: int | None
    gain_class: int | None

    def __post_init__(self) -> None:
        for side, value, motif, klass in (
            (
                "comparator_gain",
                self.comparator_gain,
                self.comparator_motif,
                self.comparator_class,
            ),
            ("gain", self.gain, self.motif, self.gain_class),
        ):
            if value is None:
                if klass is not None:
                    raise ContractError(
                        f"{side} absent : sa classe de signe l'est aussi."
                    )
                continue
            require_finite(value, side)
            if motif is not None:
                raise ContractError(
                    f"{side} présent : la performance est évaluable de ce côté, reçu "
                    f"le motif {motif}."
                )
            if klass != sign_class(value):
                raise ContractError(
                    f"la classe de {side} vaut {sign_class(value)}, reçu {klass}."
                )

    @property
    def comparable(self) -> bool:
        """Les deux gains sont présents."""
        return self.comparator_gain is not None and self.gain is not None

    @property
    def class_changed(self) -> bool:
        """Comparable, et les deux classes diffèrent."""
        return self.comparable and self.comparator_class != self.gain_class


@dataclass(frozen=True)
class CommonSet:
    """L'ensemble commun d'une configuration et du comparateur, publié en complément
    des moyennes de chacun sur son propre ensemble (``0010`` D13 ; amendement D13-B).

    Champs
    ------
    - ``days`` — dates — les performances où les deux gains sont présents.
    - ``entering`` — dates — évaluables sous la configuration, pas au comparateur.
    - ``leaving`` — dates — évaluables au comparateur, pas sous la configuration.
    - ``comparator_mean`` — sans unité — la moyenne des gains du comparateur sur
      ``days``.
    - ``mean`` — sans unité — celle des gains de la configuration sur ``days``.

    Invariants
    ----------
    Trois tuples de jours strictement croissants ; les moyennes présentes **si et
    seulement si** ``days`` n'est pas vide, finies.

    Producteur
    ----------
    ``compare_gains`` (``mountain_perf.backtest.sensitivity``).

    Consommateurs
    -------------
    ``ConfigurationOutcome`` ; le rapport.

    Non promis
    ----------
    Les moyennes principales restent celles de chaque admission ; celles-ci ne les
    remplacent pas.
    """

    days: tuple[date, ...]
    entering: tuple[date, ...]
    leaving: tuple[date, ...]
    comparator_mean: float | None
    mean: float | None

    def __post_init__(self) -> None:
        for name in ("days", "entering", "leaving"):
            values: tuple[date, ...] = getattr(self, name)
            require_immutable_sequence(values, name)
            for previous, current in pairwise(values):
                if not previous < current:
                    raise ContractError(f"{name} : jours strictement croissants.")
        for name in ("comparator_mean", "mean"):
            value: float | None = getattr(self, name)
            if (value is None) != (not self.days):
                raise ContractError(
                    f"{name} est présent si et seulement si days n'est pas vide."
                )
            if value is not None:
                require_finite(value, name)


@dataclass(frozen=True)
class ConfigurationOutcome:
    """Une configuration de la sensibilité et sa comparaison au comparateur (``0010``
    D13 ; précision de M4d-3).

    Champs
    ------
    - ``configuration`` — sans unité — la configuration.
    - ``performances`` — sans unité — la comparaison de chaque performance déclarée,
      dans l'ordre des performances.
    - ``admission`` — sans unité — pour une expérience, l'admission refaite sous la
      configuration ; absente sans expérience, ou si aucune performance n'y est
      évaluable.
    - ``assessments`` — sans unité — pour une expérience sans performance évaluable
      sous la configuration, les évaluations ; absentes sinon.
    - ``gains`` — sans unité — pour une expérience, la comparaison du gain de chaque
      performance, dans l'ordre des performances ; vide sinon.
    - ``common`` — sans unité — pour une expérience, l'ensemble commun ; absent sinon.
    - ``mean_class``, ``comparator_mean_class`` — sans unité — les classes de signe de
      ``Ḡ`` sous la configuration et au comparateur ; absentes sans ``Ḡ``.
    - ``sign_changed``, ``verdict_changed``, ``evaluability_lost``,
      ``sign_unverifiable`` — sans unité — les réserves de la configuration.

    Invariants
    ----------
    1. ``performances`` et ``gains`` sont des tuples ; ``performances`` non vide, de
       jours strictement croissants ;
    2. sans expérience (``gains`` vide) : ni admission, ni évaluations, ni ensemble
       commun, ni classe, et les quatre réserves fausses ;
    3. avec expérience : exactement une de ``admission`` et ``assessments`` ;
       l'admission est sous l'horloge de la configuration ; ``gains`` porte les jours
       de ``performances`` ; le côté « configuration » de chaque gain est celui de
       ses évaluations (gain et motif) ; ``mean_class`` est la classe de ``Ḡ`` de
       l'admission ; ``common`` est celui que donnent les gains ;
       ``sign_unverifiable`` vaut « aucun gain comparable ».

    Producteur
    ----------
    ``configuration_outcome`` (``mountain_perf.backtest.sensitivity``).

    Consommateurs
    -------------
    ``SensitivityOutcome``, qui vérifie le côté « comparateur » ; le rapport.

    Non promis
    ----------
    Le côté « comparateur » (valeurs, gains, verdict) et les réserves qui en dépendent
    sont vérifiés par ``SensitivityOutcome``, qui porte le comparateur.
    """

    configuration: SensitivityConfiguration
    performances: tuple[PerformanceComparison, ...]
    admission: Admission | None
    assessments: tuple[PerformanceAssessment, ...] | None
    gains: tuple[GainComparison, ...]
    common: CommonSet | None
    mean_class: int | None
    comparator_mean_class: int | None
    sign_changed: bool
    verdict_changed: bool
    evaluability_lost: bool
    sign_unverifiable: bool

    def __post_init__(self) -> None:
        require_immutable_sequence(self.performances, "performances")
        require_immutable_sequence(self.gains, "gains")
        if not self.performances:
            raise ContractError("performances ne doit pas être vide.")
        days = [p.civil_date for p in self.performances]
        for previous, current in pairwise(days):
            if not previous < current:
                raise ContractError(
                    "performances : jours civils strictement croissants."
                )
        if not self.gains:
            self._check_without_experiment()
            return
        self._check_experiment(days)

    @property
    def experiment(self) -> bool:
        """La configuration évalue une expérience (``gains`` non vide)."""
        return bool(self.gains)

    @property
    def assessed(self) -> tuple[PerformanceAssessment, ...]:
        """Les évaluations de la configuration : celles de l'admission, ou
        ``assessments`` ; vide sans expérience."""
        if self.admission is not None:
            return self.admission.performances
        return () if self.assessments is None else self.assessments

    @property
    def verdict(self) -> AdmissionVerdict | None:
        """Le verdict de l'admission ; ``None`` sans décision."""
        return None if self.admission is None else self.admission.verdict

    def _check_without_experiment(self) -> None:
        present = [
            name
            for name in (
                "admission",
                "assessments",
                "common",
                "mean_class",
                "comparator_mean_class",
            )
            if getattr(self, name) is not None
        ]
        flags = [
            name
            for name in (
                "sign_changed",
                "verdict_changed",
                "evaluability_lost",
                "sign_unverifiable",
            )
            if getattr(self, name)
        ]
        if present or flags:
            raise ContractError(
                "sans expérience (gains vide), ni admission, ni évaluations, ni "
                f"ensemble commun, ni classe, ni réserve ; reçu {present + flags}."
            )

    def _check_experiment(self, days: Sequence[date]) -> None:
        if (self.admission is None) == (self.assessments is None):
            raise ContractError(
                "une expérience porte exactement une de admission et assessments."
            )
        if self.assessments is not None:
            require_immutable_sequence(self.assessments, "assessments")
        if (
            self.admission is not None
            and self.admission.clock != self.configuration.clock
        ):
            raise ContractError(
                f"l'admission est sous {self.admission.clock}, l'horloge de la "
                f"configuration ({self.configuration.clock}) attendue."
            )
        if [g.civil_date for g in self.gains] != list(days):
            raise ContractError("gains porte les jours des performances, dans l'ordre.")
        assessed = {a.civil_date: a for a in self.assessed}
        for gain in self.gains:
            assessment = assessed.get(gain.civil_date)
            if assessment is None:
                raise ContractError(
                    f"aucune évaluation du {gain.civil_date.isoformat()} sous la "
                    "configuration."
                )
            if (gain.gain, gain.motif) != (assessment.gain, assessment.motif):
                raise ContractError(
                    f"le gain du {gain.civil_date.isoformat()} n'est pas celui de son "
                    "évaluation sous la configuration."
                )
        mean = None if self.admission is None else self.admission.mean_gain
        expected = None if mean is None else sign_class(mean)
        if self.mean_class != expected:
            raise ContractError(
                f"mean_class vaut {expected} (classe de Ḡ), reçu {self.mean_class}."
            )
        if self.common != common_set(self.gains):
            raise ContractError("common n'est pas l'ensemble commun des gains.")
        unverifiable = not any(g.comparable for g in self.gains)
        if self.sign_unverifiable != unverifiable:
            raise ContractError(
                f"sign_unverifiable vaut {unverifiable} (aucun gain comparable)."
            )


def common_set(gains: Sequence[GainComparison]) -> CommonSet:
    """L'ensemble commun que donnent des gains comparés (amendement D13-B) : les jours
    où les deux gains sont présents, les entrants et les sortants (évaluabilité), et
    les deux moyennes sur les jours communs, par ``math.fsum``."""
    days = tuple(g.civil_date for g in gains if g.comparable)
    entering = tuple(
        g.civil_date
        for g in gains
        if g.motif is None and g.comparator_motif is not None
    )
    leaving = tuple(
        g.civil_date
        for g in gains
        if g.comparator_motif is None and g.motif is not None
    )
    comparator = [g.comparator_gain for g in gains if g.comparable]
    values = [g.gain for g in gains if g.comparable]
    if not days:
        return CommonSet(days, entering, leaving, None, None)
    return CommonSet(
        days,
        entering,
        leaving,
        math.fsum(v for v in comparator if v is not None) / len(days),
        math.fsum(v for v in values if v is not None) / len(days),
    )


@dataclass(frozen=True)
class ReserveEntry:
    """Une réserve de la sensibilité et les configurations qui la portent (``0010``
    D13 ; précision de M4d-3).

    Champs
    ------
    - ``reserve`` — sans unité — la réserve.
    - ``configurations`` — sans unité — les rangs des configurations en cause, dans
      ``SensitivityOutcome.configurations``.

    Invariants
    ----------
    ``configurations`` : un tuple non vide de rangs ``>= 0`` strictement croissants.

    Producteur
    ----------
    ``sensitivity_outcome`` (``mountain_perf.backtest.sensitivity``).

    Consommateurs
    -------------
    ``SensitivityOutcome`` ; la vue composée ; le rapport.

    Non promis
    ----------
    Rien sur la gravité d'une réserve : elles se publient, elles ne décident pas.
    """

    reserve: SensitivityReserve
    configurations: tuple[int, ...]

    def __post_init__(self) -> None:
        require_immutable_sequence(self.configurations, "configurations")
        if not self.configurations:
            raise ContractError("configurations ne doit pas être vide.")
        if self.configurations[0] < 0:
            raise ContractError("configurations : des rangs >= 0.")
        for previous, current in pairwise(self.configurations):
            if not previous < current:
                raise ContractError("configurations : rangs strictement croissants.")


_FLAGS: Mapping[SensitivityReserve, str] = MappingProxyType(
    {
        SensitivityReserve.SIGN_CHANGED: "sign_changed",
        SensitivityReserve.VERDICT_CHANGED: "verdict_changed",
        SensitivityReserve.EVALUABILITY_LOST: "evaluability_lost",
        SensitivityReserve.SIGN_UNVERIFIABLE: "sign_unverifiable",
    }
)


def guards_lost(comparator: Admission | None, admission: Admission | None) -> bool:
    """Un garde-fou calculé au comparateur (satisfait ou violé) ne l'est plus sous la
    configuration — passages compris ; sans décision au comparateur : non (précision de
    D13, M4d-3 ; D13-C)."""
    if comparator is None:
        return False
    own = {} if admission is None else {g.metric: g.status for g in admission.guards}
    for guard in comparator.guards:
        if guard.status in _COMPUTED_GUARD and own.get(guard.metric) not in (
            _COMPUTED_GUARD
        ):
            return True
    passages = None if admission is None else admission.passages.status
    return comparator.passages.status in _COMPUTED_GUARD and (
        passages not in _COMPUTED_GUARD
    )


@dataclass(frozen=True)
class SensitivityOutcome:
    """Le document d'une sensibilité (``0010`` D13, D14 ; précision de M4d-3) : chaque
    configuration comparée au comparateur, et les réserves.

    Champs
    ------
    - ``comparator`` — sans unité — le rang du comparateur dans ``configurations``.
    - ``configurations`` — sans unité — les configurations, dans l'ordre déclaré.
    - ``reserves`` — sans unité — les réserves, dans l'ordre de ``DOCUMENT_RESERVES`` ;
      vide sans expérience.

    Invariants
    ----------
    1. ``configurations`` : un tuple non vide, de configurations distinctes, toutes avec
       ou toutes sans expérience ; ``0 <= comparator < len(configurations)`` ;
    2. chaque configuration porte les mêmes performances (jours, sorties, motifs) et
       les mêmes modèles que le comparateur ;
    3. le côté « comparateur » de chaque comparaison est la valeur du comparateur (même
       performance, modèle, métrique) ; le comparateur, comparé à lui-même, n'a aucune
       composante changée ;
    4. avec expérience : le côté « comparateur » de chaque gain est celui du
       comparateur, ``comparator_mean_class`` aussi ; ``sign_changed``,
       ``verdict_changed``, ``evaluability_lost`` sont ceux que donne la comparaison
       au comparateur ;
    5. ``reserves`` : pour chaque réserve de ``DOCUMENT_RESERVES``, dans l'ordre, une
       entrée **si et seulement si** une configuration la porte, avec les rangs de
       toutes celles qui la portent.

    Producteur
    ----------
    ``sensitivity_outcome`` (``mountain_perf.backtest.sensitivity``).

    Consommateurs
    -------------
    ``append_result`` (document cité par ``Result.sensitivity``) ; la relecture du
    registre ; la vue composée ; le rapport de sensibilité.

    Non promis
    ----------
    Que les configurations soient celles que la déclaration déclare (accord du
    registre) ; les composantes de support changées ne se recalculent pas ici.
    """

    comparator: int
    configurations: tuple[ConfigurationOutcome, ...]
    reserves: tuple[ReserveEntry, ...]

    def __post_init__(self) -> None:
        require_immutable_sequence(self.configurations, "configurations")
        require_immutable_sequence(self.reserves, "reserves")
        if not self.configurations:
            raise ContractError("configurations ne doit pas être vide.")
        if not 0 <= self.comparator < len(self.configurations):
            raise ContractError(
                f"comparator ({self.comparator}) est un rang de configurations."
            )
        seen = [c.configuration for c in self.configurations]
        if len(set(seen)) != len(seen):
            raise ContractError("les configurations sont distinctes.")
        if len({c.experiment for c in self.configurations}) != 1:
            raise ContractError(
                "toutes les configurations portent une expérience, ou aucune."
            )
        base = self.configurations[self.comparator]
        for rank, outcome in enumerate(self.configurations):
            self._check_against(rank, outcome, base)
        self._check_reserves()

    @property
    def experiment(self) -> bool:
        """La sensibilité est celle d'une expérience."""
        return self.configurations[0].experiment

    def _check_against(
        self, rank: int, outcome: ConfigurationOutcome, base: ConfigurationOutcome
    ) -> None:
        where = f"configuration {rank}"
        shape = [
            (p.civil_date, p.outing_id, p.motif, p.models) for p in outcome.performances
        ]
        expected = [
            (p.civil_date, p.outing_id, p.motif, p.models) for p in base.performances
        ]
        if shape != expected:
            raise ContractError(
                f"{where} : mêmes performances (jours, sorties, motifs) et mêmes "
                "modèles que le comparateur."
            )
        for mine, theirs in zip(outcome.performances, base.performances, strict=True):
            for comparison, reference in zip(mine.metrics, theirs.metrics, strict=True):
                if comparison.comparator != reference.value:
                    raise ContractError(
                        f"{where}, {mine.civil_date.isoformat()}, {comparison.model}, "
                        f"{comparison.metric} : le côté comparateur n'est pas la "
                        "valeur du comparateur."
                    )
                if rank == self.comparator and comparison.support:
                    raise ContractError(
                        "le comparateur, comparé à lui-même, n'a aucune composante "
                        "de support changée."
                    )
        if not outcome.experiment:
            return
        own = {a.civil_date: a for a in base.assessed}
        for gain in outcome.gains:
            assessment = own[gain.civil_date]
            if (gain.comparator_gain, gain.comparator_motif) != (
                assessment.gain,
                assessment.motif,
            ):
                raise ContractError(
                    f"{where}, {gain.civil_date.isoformat()} : le gain du comparateur "
                    "n'est pas le sien."
                )
        if outcome.comparator_mean_class != base.mean_class:
            raise ContractError(
                f"{where} : comparator_mean_class n'est pas la classe de Ḡ du "
                "comparateur."
            )
        means = (outcome.mean_class, outcome.comparator_mean_class)
        sign = (None not in means and means[0] != means[1]) or any(
            g.class_changed for g in outcome.gains
        )
        verdict = outcome.verdict != base.verdict
        lost = any(
            g.comparator_motif is None and g.motif is not None for g in outcome.gains
        ) or guards_lost(base.admission, outcome.admission)
        for name, value in (
            ("sign_changed", sign),
            ("verdict_changed", verdict),
            ("evaluability_lost", lost),
        ):
            if getattr(outcome, name) != value:
                raise ContractError(f"{where} : {name} vaut {value}.")

    def _check_reserves(self) -> None:
        expected = []
        for reserve in DOCUMENT_RESERVES:
            ranks = tuple(
                rank
                for rank, outcome in enumerate(self.configurations)
                if getattr(outcome, _FLAGS[reserve])
            )
            if ranks:
                expected.append(ReserveEntry(reserve, ranks))
        if self.reserves != tuple(expected):
            raise ContractError(
                "reserves : une entrée par réserve portée, dans l'ordre de "
                "DOCUMENT_RESERVES, avec les rangs de toutes les configurations qui "
                "la portent."
            )
