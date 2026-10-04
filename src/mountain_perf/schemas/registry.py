"""Contrats du registre des expériences : déclaration, résultat, échec, journal,
comptage des essais (M4b-4).

Protocole : ``docs/decisions/0010`` D14 (et ses précisions de M4b-4), D0, D2.5, D2.6,
D7.4, D9.1, D9.2, D10.1, D10.3, D10.7. Le registre est un journal, une ligne par
événement en écriture canonique, et des documents nommés par leur empreinte
``sha256`` : une DÉCLARATION figée avant le calcul, puis un RÉSULTAT ou un ÉCHEC qui lui
répond ; une correction est un événement neuf du même type, qui nomme celui qu'il
corrige.

Aucune entrée/sortie ici : l'écriture canonique vit dans
``mountain_perf.backtest.codec``, le registre sur disque dans
``mountain_perf.backtest.registry``.
"""

from __future__ import annotations

import math
import re
from collections.abc import Hashable, Iterable, Mapping
from dataclasses import dataclass
from datetime import UTC, date, datetime
from enum import StrEnum
from itertools import pairwise
from types import MappingProxyType

from mountain_perf.schemas.clock import CLOCKS, Clock
from mountain_perf.schemas.common import SourceRef
from mountain_perf.schemas.matching import Coverage
from mountain_perf.schemas.metrics import (
    WEIGHT_SUM_TOLERANCE,
    MetricValue,
    TargetMember,
)
from mountain_perf.schemas.outing import ArtifactRef, ArtifactRole, Performance
from mountain_perf.schemas.parameters import ParameterSet
from mountain_perf.schemas.scoring import OutingScores, Scenario
from mountain_perf.validation import (
    ContractError,
    require_aware,
    require_finite,
    require_immutable_sequence,
    require_non_empty,
)

REGISTRY_FORMAT_VERSION = 1
"""Version du format des événements et des documents du registre (``0010`` D14).

Chaque document la porte, chaque événement aussi (``format_version``). Le registre
relit ses lignes et ses documents par les contrats du jour, strictement : un contrat
stocké qui change de forme demande d'augmenter cette version, et de dire comment
relire l'ancien format."""

CURVE_REF_HASH_LENGTH = 12
"""Nombre de caractères de l'empreinte ``sha256`` du CSV recopiés dans ``curve_ref``
(la règle de ``curve_reference``, ``mountain_perf.model.curve_io``, M3)."""

_SHA256_HEX = re.compile(r"[0-9a-f]{64}")
_COMMIT_HEX = re.compile(r"[0-9a-f]{40}")


def _require_sha256(text: str, name: str) -> None:
    """Refuse un texte qui n'est pas un ``sha256`` hexadécimal minuscule."""
    if not _SHA256_HEX.fullmatch(text):
        raise ContractError(
            f"{name} doit être un sha256 hexadécimal minuscule (64 caractères), "
            f"reçu {text!r}."
        )


def _require_optional_text(text: str | None, name: str) -> None:
    """Refuse un texte présent mais vide."""
    if text is not None:
        require_non_empty(text, name)


def _require_distinct(values: Iterable[Hashable], message: str) -> None:
    """Refuse une valeur répétée ; ``message`` reçoit la première répétée."""
    seen: set[Hashable] = set()
    for value in values:
        if value in seen:
            raise ContractError(message.format(value))
        seen.add(value)


class EventKind(StrEnum):
    """Type d'un événement du registre (``0010`` D14).

    Champs
    ------
    Valeurs décrites dans ``EVENT_KIND_DESCRIPTIONS``.

    Invariants
    ----------
    Énumération fermée ; un événement porte le contenu de son type, et lui seul.

    Producteur
    ----------
    Les ajouts du registre (``mountain_perf.backtest.registry``).

    Consommateurs
    -------------
    ``RegistryEvent``, ``RegistryLog`` ; le comptage des essais.

    Non promis
    ----------
    Le type ne dit pas si l'événement est en vigueur : c'est ``RegistryLog`` qui sait
    s'il a été corrigé.
    """

    DECLARATION = "declaration"
    RESULT = "result"
    FAILURE = "failure"


EVENT_KIND_DESCRIPTIONS: Mapping[EventKind, str] = MappingProxyType(
    {
        EventKind.DECLARATION: (
            "Déclaration : ce qui est évalué, avec quoi, sur quoi, figé avant le "
            "calcul ; compte pour un essai, corrections comprises."
        ),
        EventKind.RESULT: (
            "Résultat : ce qu'une exécution a produit pour une déclaration, sortie par "
            "sortie, documents cités par empreinte."
        ),
        EventKind.FAILURE: (
            "Échec : erreur technique ou non-évaluabilité d'une déclaration, avec son "
            "motif."
        ),
    }
)


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
    L'appelant d'une déclaration (M4b-5 pour v0 brut, M4c pour les autres).

    Consommateurs
    -------------
    ``DeclaredModel``, ``ExperimentDeclaration``, ``ModelResult``, ``OutingOutcome`` ;
    l'accord d'un résultat avec sa déclaration (``CURVE_MODELS``).

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


class ExperimentMetric(StrEnum):
    """Métrique d'une expérience : cible ou référence figée (``0010`` D10.1, D10.3).

    Champs
    ------
    Valeurs décrites dans ``EXPERIMENT_METRIC_DESCRIPTIONS``.

    Invariants
    ----------
    Énumération fermée : ``|L|``, ``|E_R|`` et ``D_R`` pour montée, plat, descente,
    ``q_usage``, dans cet ordre (celui du comptage des essais).

    Producteur
    ----------
    L'appelant d'une déclaration d'expérience (M4c).

    Consommateurs
    -------------
    ``ExperimentDeclaration``, ``FrozenReference``, ``ExperimentTrials``.

    Non promis
    ----------
    ``|L|`` est un membre parce qu'une référence figée peut le porter (garde-fou de
    D10.4) ; ce n'est jamais une cible. Mixte n'a pas de membre (D6).
    """

    LEVEL = "level"
    ASCENT_LEVEL = "ascent_level"
    FLAT_LEVEL = "flat_level"
    DESCENT_LEVEL = "descent_level"
    ASCENT_DISPERSION = "ascent_dispersion"
    FLAT_DISPERSION = "flat_dispersion"
    DESCENT_DISPERSION = "descent_dispersion"
    USAGE = "usage"


EXPERIMENT_METRIC_DESCRIPTIONS: Mapping[ExperimentMetric, str] = MappingProxyType(
    {
        ExperimentMetric.LEVEL: (
            "|L| : niveau sur tout le support ; garde-fou, jamais une cible (D10.1)."
        ),
        ExperimentMetric.ASCENT_LEVEL: "|E_montée| : niveau de la classe montée.",
        ExperimentMetric.FLAT_LEVEL: "|E_plat| : niveau de la classe plat.",
        ExperimentMetric.DESCENT_LEVEL: (
            "|E_descente| : niveau de la classe descente."
        ),
        ExperimentMetric.ASCENT_DISPERSION: (
            "D_montée : dispersion de la classe montée."
        ),
        ExperimentMetric.FLAT_DISPERSION: "D_plat : dispersion de la classe plat.",
        ExperimentMetric.DESCENT_DISPERSION: (
            "D_descente : dispersion de la classe descente."
        ),
        ExperimentMetric.USAGE: (
            "q_usage : cible d'usage aux passages de K (D7.4) ; seuil fixe, sans "
            "référence figée (D10.3)."
        ),
    }
)


class ReferenceSource(StrEnum):
    """Source d'une référence figée (``0010`` D10.3).

    Champs
    ------
    Valeurs décrites dans ``REFERENCE_SOURCE_DESCRIPTIONS``.

    Invariants
    ----------
    Énumération fermée : locale ou empruntée ; le seuil fixe n'a pas de référence.

    Producteur
    ----------
    L'appelant d'une déclaration d'expérience (M4c).

    Consommateurs
    -------------
    ``FrozenReference`` ; les seuils de D10.3 et D10.4 (M4c).

    Non promis
    ----------
    L'ordre local → emprunté → fixe n'est pas appliqué ici (M4c).
    """

    LOCAL = "local"
    BORROWED = "borrowed"


REFERENCE_SOURCE_DESCRIPTIONS: Mapping[ReferenceSource, str] = MappingProxyType(
    {
        ReferenceSource.LOCAL: "Locale : la référence D8 du parcours (D10.3, 1).",
        ReferenceSource.BORROWED: (
            "Empruntée : moyenne à poids égal des références disponibles de ses "
            "donneurs, figée avec eux (D10.3, 2)."
        ),
    }
)


class FailureKind(StrEnum):
    """Nature d'un ÉCHEC (``0010`` D14).

    Champs
    ------
    Valeurs décrites dans ``FAILURE_KIND_DESCRIPTIONS``.

    Invariants
    ----------
    Énumération fermée.

    Producteur
    ----------
    L'appelant de ``append_failure`` (M4b-5).

    Consommateurs
    -------------
    ``Failure`` ; le rapport (M4b-5).

    Non promis
    ----------
    La nature ne dit pas quelle sortie a manqué : le motif le dit.
    """

    TECHNICAL = "technical"
    NOT_EVALUABLE = "not_evaluable"


FAILURE_KIND_DESCRIPTIONS: Mapping[FailureKind, str] = MappingProxyType(
    {
        FailureKind.TECHNICAL: "Erreur technique : l'exécution n'a pas abouti.",
        FailureKind.NOT_EVALUABLE: (
            "Non-évaluabilité : l'expérience déclarée ne peut pas être évaluée."
        ),
    }
)

_METRIC_ORDER = tuple(ExperimentMetric)


@dataclass(frozen=True)
class DeclaredPerformance:
    """Une performance déclarée et son origine ``o_j`` (``0010`` D0, D2.5, D14).

    Champs
    ------
    - ``performance`` — sans unité — la performance telle que le manifeste la décrit
      (M4a, telle quelle) : sorties, fichiers, rôles, instants de disponibilité, jeu,
      étiquette.
    - ``origin`` — instant — ``o_j``, *aware*, stocké en UTC.

    Invariants
    ----------
    - ``origin`` porte un fuseau ; il est normalisé en UTC à la construction ;
    - ``origin`` précède **strictement** le départ de la première sortie.

    Producteur
    ----------
    ``declared_performance`` (``mountain_perf.backtest.registry``).

    Consommateurs
    -------------
    ``Declaration`` ; le test d'éligibilité à J−7 (M4c).

    Non promis
    ----------
    L'origine n'est pas recalculée depuis le jour civil : c'est
    ``declared_performance`` qui applique D2.5.
    """

    performance: Performance
    origin: datetime

    def __post_init__(self) -> None:
        require_aware(self.origin, "origin")
        object.__setattr__(self, "origin", self.origin.astimezone(UTC))
        start = self.performance.outings[0].start_time
        if not self.origin < start:
            raise ContractError(
                f"origin ({self.origin}) doit précéder strictement le départ de la "
                f"première sortie ({start}) (D2.5)."
            )


@dataclass(frozen=True)
class Exclusion:
    """Une sortie écartée, et pourquoi (``0010`` D0, D10.1, D14).

    Champs
    ------
    - ``outing_id`` — sans unité — l'identifiant de la sortie.
    - ``reason`` — sans unité — le motif, en clair.

    Invariants
    ----------
    ``outing_id`` et ``reason`` non vides.

    Producteur
    ----------
    L'appelant d'une déclaration ou d'un résultat (M4b-5).

    Consommateurs
    -------------
    ``Declaration.exclusions`` (sorties écartées d'une règle) ; ``Result.unscored``
    (sorties déclarées non scorées) ; le rapport (M4b-5).

    Non promis
    ----------
    Le motif ne nomme pas de chemin de fichier (règle 1) : c'est à l'appelant d'y
    veiller.
    """

    outing_id: str
    reason: str

    def __post_init__(self) -> None:
        require_non_empty(self.outing_id, "outing_id")
        require_non_empty(self.reason, "reason")


@dataclass(frozen=True)
class DeclaredModel:
    """Un modèle évalué, déclaré avant l'exécution (``0010`` D9, D14).

    Champs
    ------
    - ``kind`` — sans unité — la nature du modèle.
    - ``engine_version`` — sans unité — la version que ses prévisions recopient.
    - ``parameters`` — sans unité — les paramètres fixés avant l'exécution.
    - ``estimation_rule`` — sans unité — la règle d'estimation des paramètres appris,
      en clair.

    Invariants
    ----------
    - ``engine_version`` non vide ; ``estimation_rule`` absente ou non vide ;
    - **au moins un** de ``parameters`` et ``estimation_rule`` présent (les deux sont
      permis : v0 + effort recalé a des paramètres de départ et une règle).

    Producteur
    ----------
    L'appelant d'une déclaration (M4b-5, M4c).

    Consommateurs
    -------------
    ``Declaration`` ; l'accord d'un résultat avec sa déclaration (version, paramètres
    des modèles sans règle).

    Non promis
    ----------
    La règle n'est pas exécutée ni vérifiée : elle est déclarée.
    """

    kind: ModelKind
    engine_version: str
    parameters: ParameterSet | None
    estimation_rule: str | None

    def __post_init__(self) -> None:
        require_non_empty(self.engine_version, "engine_version")
        _require_optional_text(self.estimation_rule, "estimation_rule")
        if self.parameters is None and self.estimation_rule is None:
            raise ContractError(
                "un modèle déclaré porte des paramètres fixés, une règle d'estimation, "
                "ou les deux (D14)."
            )


@dataclass(frozen=True)
class DeclaredEffect:
    """L'effet testé par une expérience (``0010`` D10.1, D9.3).

    Champs
    ------
    - ``name`` — sans unité — le nom de l'effet.
    - ``description`` — sans unité — ce qu'il fait, en clair.
    - ``parameters`` — sans unité — ses paramètres fixés.
    - ``estimation_rule`` — sans unité — sa règle d'estimation, en clair.

    Invariants
    ----------
    - ``name`` et ``description`` non vides ; ``estimation_rule`` absente ou non vide ;
    - au moins un de ``parameters`` et ``estimation_rule`` présent.

    Producteur
    ----------
    L'appelant d'une déclaration d'expérience (M4c).

    Consommateurs
    -------------
    ``ExperimentDeclaration`` ; le comptage des essais, par nom.

    Non promis
    ----------
    Deux effets de même nom sont le même effet pour le comptage des essais.
    """

    name: str
    description: str
    parameters: ParameterSet | None
    estimation_rule: str | None

    def __post_init__(self) -> None:
        require_non_empty(self.name, "name")
        require_non_empty(self.description, "description")
        _require_optional_text(self.estimation_rule, "estimation_rule")
        if self.parameters is None and self.estimation_rule is None:
            raise ContractError(
                "un effet déclaré porte des paramètres fixés, une règle d'estimation, "
                "ou les deux (D10.1)."
            )


@dataclass(frozen=True)
class DeclaredUsageTarget:
    """``K`` et ses poids, déclarés pour un parcours (``0010`` D7.4, D10.1).

    Champs
    ------
    - ``route_id`` — sans unité — le parcours.
    - ``members`` — sans unité — les éléments de ``K``, dans l'ordre du parcours.
    - ``weights`` — sans unité — les ``w_k`` ; absents : les poids par défaut de D7.4
      (proportionnels au temps projeté par la base).

    Invariants
    ----------
    - ``route_id`` non vide ; ``members`` est un tuple, ``weights`` aussi s'il est
      présent ;
    - ``members`` non vide ; le dernier élément est l'arrivée, et lui seul ;
    - les ``occurrence_index`` présents sont **strictement** croissants ;
    - ``weights`` présents : un poids par élément, chacun fini et ``>= 0``, de somme 1
      à ``WEIGHT_SUM_TOLERANCE`` près — la règle de ``UsageTarget`` (M4b-1), écrite de
      même, pour que des poids acceptés ici le soient par ``usage_target`` en M4c.

    Producteur
    ----------
    L'appelant d'une déclaration d'expérience de cible ``q_usage`` (M4c).

    Consommateurs
    -------------
    ``ExperimentDeclaration`` ; ``usage_target`` (M4c).

    Non promis
    ----------
    « Départ exclu » et ``P_k^(0) > 0`` (D7.4) ne sont pas vérifiés : ils demandent
    les rôles des lieux et la prévision de la base (M4c).
    """

    route_id: str
    members: tuple[TargetMember, ...]
    weights: tuple[float, ...] | None

    def __post_init__(self) -> None:
        require_non_empty(self.route_id, "route_id")
        require_immutable_sequence(self.members, "members")
        if self.weights is not None:
            require_immutable_sequence(self.weights, "weights")
        self._check_members()
        if self.weights is not None:
            self._check_weights(self.weights)

    def _check_members(self) -> None:
        if not self.members:
            raise ContractError(
                "members ne doit pas être vide : K porte au moins l'arrivée."
            )
        arrivals = [i for i, member in enumerate(self.members) if member.arrival]
        if arrivals != [len(self.members) - 1]:
            raise ContractError(
                "le dernier membre de K est l'arrivée, et lui seul, reçu l'arrivée "
                f"aux rangs {arrivals} sur {len(self.members)}."
            )
        indices = [
            member.occurrence_index
            for member in self.members
            if member.occurrence_index is not None
        ]
        for previous, current in pairwise(indices):
            if not previous < current:
                raise ContractError(
                    "les occurrence_index présents sont strictement croissants, reçu "
                    f"{previous} puis {current}."
                )

    def _check_weights(self, weights: tuple[float, ...]) -> None:
        if len(weights) != len(self.members):
            raise ContractError(
                f"weights ({len(weights)}) et members ({len(self.members)}) ont la "
                "même longueur."
            )
        for k, weight in enumerate(weights):
            require_finite(weight, f"weights[{k}]")
            if weight < 0:
                raise ContractError(f"weights[{k}] doit être >= 0, reçu {weight}.")
        total = math.fsum(weights)
        if abs(total - 1.0) > WEIGHT_SUM_TOLERANCE:
            raise ContractError(
                f"les poids somment à 1 à {WEIGHT_SUM_TOLERANCE} près, reçu {total}."
            )


@dataclass(frozen=True)
class FrozenReference:
    """Une valeur de référence figée et sa source (``0010`` D10.3).

    Champs
    ------
    - ``metric`` — sans unité — la métrique.
    - ``clock`` — sans unité — l'horloge.
    - ``source`` — sans unité — locale ou empruntée.
    - ``route_id`` — sans unité — le parcours d'une référence locale.
    - ``value`` — sans unité — ``F`` et son effectif ``m_q``, ou son motif (M4b-1).
    - ``donors`` — sans unité — les parcours donneurs d'une référence empruntée.

    Invariants
    ----------
    - ``donors`` est un tuple de noms non vides ; ``route_id`` absent ou non vide ;
    - ``metric`` n'est pas ``USAGE`` (``q_usage`` a un seuil fixe, D10.3) ;
    - locale : ``route_id`` présent, ``donors`` vide ;
    - empruntée : ``route_id`` absent, ``donors`` non vide, de noms distincts.

    Producteur
    ----------
    L'appelant d'une déclaration d'expérience (M4c), depuis les références D8.

    Consommateurs
    -------------
    ``ExperimentDeclaration`` ; les seuils de D10.3 et D10.4 (M4c).

    Non promis
    ----------
    La valeur n'est pas recalculée, ni depuis D8, ni comme moyenne des donneurs.
    """

    metric: ExperimentMetric
    clock: Clock
    source: ReferenceSource
    route_id: str | None
    value: MetricValue
    donors: tuple[str, ...]

    def __post_init__(self) -> None:
        require_immutable_sequence(self.donors, "donors")
        for i, donor in enumerate(self.donors):
            require_non_empty(donor, f"donors[{i}]")
        _require_optional_text(self.route_id, "route_id")
        if self.metric is ExperimentMetric.USAGE:
            raise ContractError(
                "q_usage n'a pas de référence figée : son seuil est fixe (D10.3)."
            )
        if self.source is ReferenceSource.LOCAL:
            self._check_local()
        else:
            self._check_borrowed()

    def _check_local(self) -> None:
        if self.route_id is None:
            raise ContractError("une référence locale nomme son parcours (route_id).")
        if self.donors:
            raise ContractError(
                f"une référence locale n'a pas de donneur, reçu {list(self.donors)}."
            )

    def _check_borrowed(self) -> None:
        if self.route_id is not None:
            raise ContractError(
                "une référence empruntée ne nomme pas de parcours : ses donneurs le "
                f"font, reçu route_id={self.route_id!r}."
            )
        if not self.donors:
            raise ContractError(
                "une référence empruntée a au moins un donneur (D10.3)."
            )
        _require_distinct(
            list(self.donors), "les donneurs sont distincts, reçu {!r} deux fois."
        )


@dataclass(frozen=True)
class ExperimentDeclaration:
    """La partie « expérience » d'une déclaration (``0010`` D10.1, D10.3, D10.7).

    Champs
    ------
    - ``effect`` — sans unité — l'effet testé.
    - ``target`` — sans unité — la cible ``q``.
    - ``clock`` — sans unité — l'horloge de la cible.
    - ``scenario`` — sans unité — le scénario de l'expérience : celui de ses scores, de
      son calage et de la projection qui classe les performances comparables (D9.2,
      D10.3).
    - ``base`` — sans unité — le modèle de base ``(0)``.
    - ``candidate`` — sans unité — le candidat ``(1)``.
    - ``usage_targets`` — sans unité — ``K`` et ses poids, par parcours ; vide : le
      ``K`` par défaut.
    - ``frozen_references`` — sans unité — les références figées et leur source.
    - ``analysis_date`` — date civile — la date d'analyse fixée d'avance (D10.7) ;
      absente pour une admission exploratoire.

    Invariants
    ----------
    - ``usage_targets`` et ``frozen_references`` sont des tuples ;
    - ``target`` n'est pas ``LEVEL`` (``|L|`` n'est pas une cible) ;
    - ``base`` vaut ``V0_RECALIBRATED`` ; ``candidate`` vaut ``CANDIDATE`` ;
    - ``usage_targets`` non vide ⇒ ``target`` vaut ``USAGE`` ;
    - ``target`` vaut ``USAGE`` ⇒ ``scenario`` vaut ``USAGE`` (``q_usage`` ne se
      calcule qu'en usage, D7.4) ;
    - les parcours des ``usage_targets`` sont distincts ;
    - les clés ``(metric, clock, source, route_id)`` des références figées sont
      distinctes ;
    - chaque donneur d'une référence empruntée a une référence locale de même
      ``metric``, de même ``clock``, pour ce parcours, disponible.

    Producteur
    ----------
    L'appelant d'une déclaration d'expérience (M4c).

    Consommateurs
    -------------
    ``Declaration`` ; le comptage des essais (effet × cible) ; l'admission (M4c).

    Non promis
    ----------
    Les règles de D10 (évaluabilité, seuils, garde-fous, ordre local → emprunté →
    fixe) ne sont pas appliquées ici (M4c) ; la date d'analyse n'est comparée ni à
    l'instant de la déclaration ni aux origines (M4c).
    """

    effect: DeclaredEffect
    target: ExperimentMetric
    clock: Clock
    scenario: Scenario
    base: ModelKind
    candidate: ModelKind
    usage_targets: tuple[DeclaredUsageTarget, ...]
    frozen_references: tuple[FrozenReference, ...]
    analysis_date: date | None

    def __post_init__(self) -> None:
        require_immutable_sequence(self.usage_targets, "usage_targets")
        require_immutable_sequence(self.frozen_references, "frozen_references")
        self._check_roles()
        self._check_usage()
        _require_distinct(
            [target.route_id for target in self.usage_targets],
            "les K déclarés portent sur des parcours distincts, reçu {!r} deux fois.",
        )
        _require_distinct(
            [
                (ref.metric, ref.clock, ref.source, ref.route_id)
                for ref in self.frozen_references
            ],
            "les références figées ont des clés (metric, clock, source, route_id) "
            "distinctes, reçu {} deux fois.",
        )
        self._check_donors()

    def _check_roles(self) -> None:
        if self.target is ExperimentMetric.LEVEL:
            raise ContractError("|L| n'est pas une cible (D10.1).")
        if self.base is not ModelKind.V0_RECALIBRATED:
            raise ContractError(
                f"la base (0) est v0 + effort recalé (D10.1), reçu {self.base}."
            )
        if self.candidate is not ModelKind.CANDIDATE:
            raise ContractError(
                f"le candidat (1) est CANDIDATE (D10.1), reçu {self.candidate}."
            )

    def _check_usage(self) -> None:
        usage = self.target is ExperimentMetric.USAGE
        if self.usage_targets and not usage:
            raise ContractError(
                "un K déclaré n'existe que pour la cible q_usage (D10.1), reçu la "
                f"cible {self.target}."
            )
        if usage and self.scenario is not Scenario.USAGE:
            raise ContractError(
                "la cible q_usage ne se calcule qu'en usage (D7.4), reçu le scénario "
                f"{self.scenario}."
            )

    def _check_donors(self) -> None:
        available = {
            (ref.metric, ref.clock, ref.route_id)
            for ref in self.frozen_references
            if ref.source is ReferenceSource.LOCAL and ref.value.value is not None
        }
        for ref in self.frozen_references:
            if ref.source is not ReferenceSource.BORROWED:
                continue
            for donor in ref.donors:
                if (ref.metric, ref.clock, donor) not in available:
                    raise ContractError(
                        f"le donneur {donor!r} de la référence empruntée de "
                        f"{ref.metric} sous {ref.clock} n'a pas de référence locale "
                        "disponible de même métrique et de même horloge (D10.3)."
                    )


@dataclass(frozen=True)
class Declaration:
    """Le contenu d'une DÉCLARATION (``0010`` D14, D2.6, D10.1).

    Champs
    ------
    - ``commit`` — sans unité — le commit du code exécuté.
    - ``tree_modified`` — sans unité — l'arbre de travail portait des modifications
      non commitées.
    - ``protocol_record`` — sans unité — le decision record du protocole (``"0010"``).
    - ``athlete_ref`` — sans unité — l'athlète du manifeste et de la courbe.
    - ``matching`` — sans unité — les paramètres de l'appariement (``Δ``, ``ε``,
      ``r_c``).
    - ``clocks`` — sans unité — les horloges de l'exécution.
    - ``curve_ref`` — sans unité — la référence de la courbe.
    - ``curve`` — sans unité — le CSV de la courbe.
    - ``curve_metadata`` — sans unité — son compagnon ``.meta.json``.
    - ``manifest`` — sans unité — le manifeste lu, cité par son empreinte, sans rôle.
    - ``performances`` — sans unité — les performances évaluées.
    - ``exclusions`` — sans unité — les sorties écartées, avec leur motif.
    - ``models`` — sans unité — les modèles évalués.
    - ``experiment`` — sans unité — l'expérience ; absente sans effet testé.

    Propriétés calculées (jamais stockées) : ``outing_ids``, ``route_ids``,
    ``artifacts``.

    Invariants
    ----------
    1. ``protocol_record``, ``athlete_ref``, ``curve_ref`` non vides ; ``clocks``,
       ``performances``, ``exclusions``, ``models`` sont des tuples ;
    2. ``commit`` : 40 caractères hexadécimaux **minuscules** ;
    3. ``clocks`` non vide ; chaque horloge est dans ``CLOCKS`` ; leurs rangs dans
       ``CLOCKS`` sont strictement croissants (sous-suite, sans doublon) ;
    4. ``curve`` et ``curve_metadata`` ont le rôle ``FORECAST_INPUT`` ; ``curve_ref``
       vaut ``"<nom du CSV>#<12 premiers caractères de son sha256>"`` ;
    5. jours civils des performances strictement croissants ; chaque sortie a
       l'``athlete_ref`` déclaré ; identifiants de sortie distincts sur toutes les
       performances ;
    6. ``exclusions`` : identifiants distincts ;
    7. ``models`` non vide, de natures distinctes ;
    8. ``experiment`` présente : sa base puis son candidat sont des natures de
       ``models`` ; son horloge et celle de chaque référence figée sont dans
       ``clocks`` ; le parcours de chaque ``K`` est dans ``route_ids``.

    Producteur
    ----------
    L'appelant de ``append_declaration`` (M4b-5, M4c).

    Consommateurs
    -------------
    ``RegistryEvent`` ; l'accord d'un résultat avec sa déclaration ; le comptage des
    essais ; le test d'éligibilité à J−7 (M4c).

    Non promis
    ----------
    - les fichiers ne sont pas relus (empreintes de leur lecture) ;
    - ``matching`` n'est pas recoupé avec ``MATCHING_PARAMETER_SPECS`` ;
    - une exclusion peut nommer une sortie des performances (exclue d'une règle, pas
      du registre) ;
    - l'éligibilité à J−7 (D2.6) n'est pas évaluée (M4c).
    """

    commit: str
    tree_modified: bool
    protocol_record: str
    athlete_ref: str
    matching: ParameterSet
    clocks: tuple[Clock, ...]
    curve_ref: str
    curve: ArtifactRef
    curve_metadata: ArtifactRef
    manifest: SourceRef
    performances: tuple[DeclaredPerformance, ...]
    exclusions: tuple[Exclusion, ...]
    models: tuple[DeclaredModel, ...]
    experiment: ExperimentDeclaration | None

    def __post_init__(self) -> None:
        for name in ("protocol_record", "athlete_ref", "curve_ref"):
            require_non_empty(getattr(self, name), name)
        for name in ("clocks", "performances", "exclusions", "models"):
            require_immutable_sequence(getattr(self, name), name)
        if not _COMMIT_HEX.fullmatch(self.commit):
            raise ContractError(
                "commit doit porter 40 caractères hexadécimaux minuscules, reçu "
                f"{self.commit!r}."
            )
        self._check_clocks()
        self._check_curve()
        self._check_performances()
        _require_distinct(
            [exclusion.outing_id for exclusion in self.exclusions],
            "deux exclusions nomment la même sortie, {!r}.",
        )
        self._check_models()
        if self.experiment is not None:
            self._check_experiment(self.experiment)

    @property
    def outing_ids(self) -> tuple[str, ...]:
        """Les identifiants des sorties des performances, dans l'ordre."""
        return tuple(
            outing.outing_id
            for declared in self.performances
            for outing in declared.performance.outings
        )

    @property
    def route_ids(self) -> frozenset[str]:
        """Les parcours (``route_id`` non ``None``) des sorties des performances."""
        return frozenset(
            outing.route_id
            for declared in self.performances
            for outing in declared.performance.outings
            if outing.route_id is not None
        )

    @property
    def artifacts(self) -> tuple[ArtifactRef, ...]:
        """Tous les fichiers déclarés (D2.6) : la courbe, son compagnon, puis, sortie
        par sortie, ses traces, ses doublons et sa référence si elle en a une."""
        files = [self.curve, self.curve_metadata]
        for declared in self.performances:
            for outing in declared.performance.outings:
                files.extend(outing.traces)
                files.extend(outing.duplicates)
                if outing.reference is not None:
                    files.append(outing.reference.artifact)
        return tuple(files)

    def _check_clocks(self) -> None:
        if not self.clocks:
            raise ContractError("clocks ne doit pas être vide.")
        ranks: list[int] = []
        for i, clock in enumerate(self.clocks):
            if clock not in CLOCKS:
                raise ContractError(
                    f"clocks[{i}] n'est pas une des onze horloges de CLOCKS, reçu "
                    f"{clock}."
                )
            ranks.append(CLOCKS.index(clock))
        for previous, current in pairwise(ranks):
            if not previous < current:
                raise ContractError(
                    "les horloges suivent l'ordre de CLOCKS, sans doublon, reçu les "
                    f"rangs {previous} puis {current}."
                )

    def _check_curve(self) -> None:
        for name in ("curve", "curve_metadata"):
            artifact: ArtifactRef = getattr(self, name)
            if artifact.role is not ArtifactRole.FORECAST_INPUT:
                raise ContractError(
                    f"{name}.role doit être FORECAST_INPUT (entrée de prévision, "
                    f"D2.6), reçu {artifact.role}."
                )
        source = self.curve.source
        expected = f"{source.identifier}#{source.content_hash[:CURVE_REF_HASH_LENGTH]}"
        if self.curve_ref != expected:
            raise ContractError(
                f"curve_ref ({self.curve_ref!r}) doit nommer le CSV déclaré : "
                f"{expected!r} attendu."
            )

    def _check_performances(self) -> None:
        for previous, current in pairwise(self.performances):
            before, after = previous.performance, current.performance
            if not before.civil_date < after.civil_date:
                raise ContractError(
                    "les performances sont par jour civil strictement croissant, reçu "
                    f"{before.civil_date} puis {after.civil_date}."
                )
        for declared in self.performances:
            for outing in declared.performance.outings:
                if outing.athlete_ref != self.athlete_ref:
                    raise ContractError(
                        f"la sortie {outing.outing_id!r} est d'un autre athlète que "
                        "athlete_ref (D2.6)."
                    )
        _require_distinct(
            list(self.outing_ids),
            "les identifiants de sortie sont distincts sur toutes les performances, "
            "reçu {!r} deux fois.",
        )

    def _check_models(self) -> None:
        if not self.models:
            raise ContractError("models ne doit pas être vide : un modèle au moins.")
        _require_distinct(
            [model.kind for model in self.models],
            "les modèles déclarés ont des natures distinctes, reçu {} deux fois.",
        )

    def _check_experiment(self, experiment: ExperimentDeclaration) -> None:
        kinds = {model.kind for model in self.models}
        for role in ("base", "candidate"):
            kind: ModelKind = getattr(experiment, role)
            if kind not in kinds:
                raise ContractError(
                    f"experiment.{role} ({kind}) doit être un modèle déclaré."
                )
        if experiment.clock not in self.clocks:
            raise ContractError(
                f"l'horloge de la cible ({experiment.clock}) doit être une horloge de "
                "l'exécution (clocks)."
            )
        for i, ref in enumerate(experiment.frozen_references):
            if ref.clock not in self.clocks:
                raise ContractError(
                    f"l'horloge de la référence figée {i} ({ref.clock}) doit être une "
                    "horloge de l'exécution (clocks)."
                )
        route_ids = self.route_ids
        for target in experiment.usage_targets:
            if target.route_id not in route_ids:
                raise ContractError(
                    f"le K du parcours {target.route_id!r} doit porter sur un parcours "
                    "des performances déclarées."
                )


@dataclass(frozen=True)
class ModelResult:
    """Les documents des scores d'un modèle sur une sortie (``0010`` D14).

    Champs
    ------
    - ``model`` — sans unité — la nature du modèle.
    - ``control`` — sans unité — le ``sha256`` du document ``ScenarioScores`` du
      contrôle, prévision comprise.
    - ``usage`` — sans unité — celui de l'usage ; absent sans référence (D3).

    Invariants
    ----------
    ``control`` et ``usage`` présent sont des ``sha256``.

    Producteur
    ----------
    ``append_result`` (``mountain_perf.backtest.registry``).

    Consommateurs
    -------------
    ``OutingResult`` ; la relecture et la vérification du registre ;
    ``load_outcomes``.

    Non promis
    ----------
    Le contrat ne lit pas les documents.
    """

    model: ModelKind
    control: str
    usage: str | None

    def __post_init__(self) -> None:
        _require_sha256(self.control, "control")
        if self.usage is not None:
            _require_sha256(self.usage, "usage")


@dataclass(frozen=True)
class OutingResult:
    """Une sortie scorée d'un RÉSULTAT (``0010`` D14, D4.11).

    Champs
    ------
    - ``outing_id`` — sans unité — la sortie.
    - ``coverage`` — sans unité — sa couverture (D4.11).
    - ``observation`` — sans unité — le ``sha256`` du document ``OutingObservation``.
    - ``models`` — sans unité — les documents de chaque modèle.

    Invariants
    ----------
    - ``outing_id`` non vide ; ``observation`` est un ``sha256`` ; ``models`` est un
      tuple ;
    - ``models`` non vide, de modèles distincts ;
    - ``usage`` présent pour tous les modèles ou pour aucun.

    Producteur
    ----------
    ``append_result`` (``mountain_perf.backtest.registry``).

    Consommateurs
    -------------
    ``Result`` ; la relecture et la vérification du registre ; ``load_outcomes``.

    Non promis
    ----------
    Le contrat ne lit pas les documents ; rien ne relie la couverture à
    l'observation.
    """

    outing_id: str
    coverage: Coverage
    observation: str
    models: tuple[ModelResult, ...]

    def __post_init__(self) -> None:
        require_non_empty(self.outing_id, "outing_id")
        _require_sha256(self.observation, "observation")
        require_immutable_sequence(self.models, "models")
        if not self.models:
            raise ContractError(
                "models ne doit pas être vide : une sortie scorée l'est par un modèle "
                "au moins."
            )
        _require_distinct(
            [model.model for model in self.models],
            "les modèles d'une sortie scorée sont distincts, reçu {} deux fois.",
        )
        if len({model.usage is None for model in self.models}) > 1:
            raise ContractError(
                "l'usage est présent pour tous les modèles ou pour aucun (D3)."
            )


@dataclass(frozen=True)
class RepeatabilityRecord:
    """Une référence D8 d'un RÉSULTAT (``0010`` D8, D14).

    Champs
    ------
    - ``route_id`` — sans unité — le parcours.
    - ``reference`` — sans unité — le ``sha256`` du document
      ``RepeatabilityReference``.

    Invariants
    ----------
    ``route_id`` non vide ; ``reference`` est un ``sha256``.

    Producteur
    ----------
    ``append_result`` (``mountain_perf.backtest.registry``).

    Consommateurs
    -------------
    ``Result`` ; la relecture et la vérification du registre ; ``load_references``.

    Non promis
    ----------
    Le contrat ne lit pas le document.
    """

    route_id: str
    reference: str

    def __post_init__(self) -> None:
        require_non_empty(self.route_id, "route_id")
        _require_sha256(self.reference, "reference")


@dataclass(frozen=True)
class Result:
    """Le contenu d'un RÉSULTAT (``0010`` D14, D0).

    Champs
    ------
    - ``outings`` — sans unité — les sorties scorées.
    - ``unscored`` — sans unité — les sorties déclarées non scorées, avec leur motif.
    - ``references`` — sans unité — les références D8 des parcours.

    Invariants
    ----------
    - ``outings``, ``unscored`` et ``references`` sont des tuples ;
    - les identifiants de ``outings`` et de ``unscored``, pris ensemble, sont
      distincts ;
    - les parcours de ``references`` sont distincts.

    Producteur
    ----------
    ``append_result`` (``mountain_perf.backtest.registry``).

    Consommateurs
    -------------
    ``RegistryEvent`` ; la relecture, la vérification et la lecture des documents du
    registre ; le rapport (M4b-5).

    Non promis
    ----------
    - l'accord avec la déclaration est vérifié par le registre, pas par le contrat ;
    - gains, dommages et verdict (M4c) n'y sont pas encore : une version du format
      les ajoutera ;
    - l'ordre des sorties est celui de l'appelant.
    """

    outings: tuple[OutingResult, ...]
    unscored: tuple[Exclusion, ...]
    references: tuple[RepeatabilityRecord, ...]

    def __post_init__(self) -> None:
        for name in ("outings", "unscored", "references"):
            require_immutable_sequence(getattr(self, name), name)
        _require_distinct(
            [outing.outing_id for outing in self.outings]
            + [exclusion.outing_id for exclusion in self.unscored],
            "une sortie est scorée ou écartée, une seule fois, reçu {!r} deux fois.",
        )
        _require_distinct(
            [record.route_id for record in self.references],
            "les références D8 portent sur des parcours distincts, reçu {!r} deux "
            "fois.",
        )


@dataclass(frozen=True)
class Failure:
    """Le contenu d'un ÉCHEC (``0010`` D14).

    Champs
    ------
    - ``kind`` — sans unité — erreur technique ou non-évaluabilité.
    - ``reason`` — sans unité — le motif, en clair.

    Invariants
    ----------
    ``reason`` non vide.

    Producteur
    ----------
    L'appelant de ``append_failure`` (M4b-5).

    Consommateurs
    -------------
    ``RegistryEvent`` ; le rapport (M4b-5).

    Non promis
    ----------
    Le motif ne nomme pas de chemin de fichier (règle 1) : c'est à l'appelant d'y
    veiller.
    """

    kind: FailureKind
    reason: str

    def __post_init__(self) -> None:
        require_non_empty(self.reason, "reason")


@dataclass(frozen=True)
class RegistryEvent:
    """Un événement du registre, une ligne du journal (``0010`` D14).

    Champs
    ------
    - ``format_version`` — sans unité — la version du format.
    - ``number`` — sans unité — son rang dans le journal, à partir de 1 (identifiant
      et lien).
    - ``kind`` — sans unité — déclaration, résultat ou échec.
    - ``recorded_at`` — instant — l'instant d'enregistrement, *aware*, stocké en UTC.
    - ``previous_hash`` — sans unité — le ``sha256`` de la ligne précédente.
    - ``answers`` — sans unité — le numéro de la déclaration à laquelle répond un
      résultat ou un échec.
    - ``corrects`` — sans unité — le numéro de l'événement corrigé.
    - ``correction_reason`` — sans unité — le motif de la correction.
    - ``declaration``, ``result``, ``failure`` — sans unité — le contenu, selon le
      type.

    Invariants
    ----------
    1. ``recorded_at`` porte un fuseau, normalisé en UTC ; ``previous_hash`` présent :
       un ``sha256`` ; ``correction_reason`` présent : non vide ;
    2. ``format_version == REGISTRY_FORMAT_VERSION`` ;
    3. ``number >= 1`` ;
    4. ``previous_hash`` absent **si et seulement si** ``number == 1`` ;
    5. le contenu présent est celui du type, et lui seul ;
    6. ``answers`` présent **si et seulement si** le type est résultat ou échec, et
       alors ``1 <= answers < number`` ;
    7. ``corrects`` absent, ou ``1 <= corrects < number`` ;
    8. ``correction_reason`` présent **si et seulement si** ``corrects`` l'est.

    Producteur
    ----------
    Les ajouts du registre (``mountain_perf.backtest.registry``).

    Consommateurs
    -------------
    ``RegistryLog`` ; la relecture du registre ; le comptage des essais.

    Non promis
    ----------
    Les liens vers les autres événements (type de la cible, correction unique…) sont
    des invariants du journal (``RegistryLog``).
    """

    format_version: int
    number: int
    kind: EventKind
    recorded_at: datetime
    previous_hash: str | None
    answers: int | None
    corrects: int | None
    correction_reason: str | None
    declaration: Declaration | None
    result: Result | None
    failure: Failure | None

    def __post_init__(self) -> None:
        require_aware(self.recorded_at, "recorded_at")
        object.__setattr__(self, "recorded_at", self.recorded_at.astimezone(UTC))
        if self.previous_hash is not None:
            _require_sha256(self.previous_hash, "previous_hash")
        _require_optional_text(self.correction_reason, "correction_reason")
        if self.format_version != REGISTRY_FORMAT_VERSION:
            raise ContractError(
                f"format_version vaut {REGISTRY_FORMAT_VERSION}, reçu "
                f"{self.format_version}."
            )
        if self.number < 1:
            raise ContractError(
                f"number est un rang à partir de 1, reçu {self.number}."
            )
        if (self.previous_hash is None) != (self.number == 1):
            raise ContractError(
                "previous_hash est absent si et seulement si l'événement est le "
                f"premier, reçu number={self.number} et previous_hash "
                f"{'absent' if self.previous_hash is None else 'présent'}."
            )
        self._check_content()
        self._check_links()

    def _check_content(self) -> None:
        present = {
            EventKind.DECLARATION: self.declaration is not None,
            EventKind.RESULT: self.result is not None,
            EventKind.FAILURE: self.failure is not None,
        }
        expected = {kind: kind is self.kind for kind in EventKind}
        if present != expected:
            carried = [str(kind) for kind, here in present.items() if here]
            raise ContractError(
                f"un événement {self.kind} porte le contenu de son type, et lui seul, "
                f"reçu {carried}."
            )

    def _check_links(self) -> None:
        answering = self.kind in (EventKind.RESULT, EventKind.FAILURE)
        if (self.answers is not None) != answering:
            raise ContractError(
                "answers est présent si et seulement si l'événement est un résultat ou "
                f"un échec, reçu {self.kind} et answers={self.answers}."
            )
        if self.answers is not None and not 1 <= self.answers < self.number:
            raise ContractError(
                f"answers ({self.answers}) nomme une déclaration qui précède "
                f"l'événement {self.number}."
            )
        if self.corrects is not None and not 1 <= self.corrects < self.number:
            raise ContractError(
                f"corrects ({self.corrects}) nomme un événement qui précède "
                f"l'événement {self.number}."
            )
        if (self.correction_reason is None) != (self.corrects is None):
            raise ContractError(
                "correction_reason est présent si et seulement si corrects l'est : une "
                "correction dit son motif."
            )


@dataclass(frozen=True)
class RegistryLog:
    """Le journal relu, ses liens vérifiés (``0010`` D14).

    Champs
    ------
    - ``events`` — sans unité — les événements, dans l'ordre du journal.

    Invariants
    ----------
    ``events`` est un tuple ; ``events[i].number == i + 1`` ; les ``recorded_at`` ne
    décroissent pas (égaux permis) ; puis, événement par événement, dans l'ordre du
    journal :

    1. un événement qui répond (``answers``) vise une déclaration ;
    2. une réponse qui n'est pas une correction est la **seule** de sa déclaration ;
    3. une correction vise un événement du même type ; une réponse qui corrige vise
       une réponse à la même déclaration ;
    4. un événement est corrigé au plus une fois.

    Méthodes : ``event(number)`` (``IndexError`` hors de ``[1 ; len(events)]``),
    ``corrected_by(number)``, ``in_force(number)``, ``answer(declaration)``.

    Producteur
    ----------
    ``read_registry`` et ``verify_registry`` (``mountain_perf.backtest.registry``) ;
    les ajouts, qui vérifient le journal augmenté avant d'écrire.

    Consommateurs
    -------------
    ``load_outcomes``, ``load_references``, ``count_trials`` ; le rapport (M4b-5) ;
    l'admission (M4c).

    Non promis
    ----------
    La chaîne des empreintes et les documents sont vérifiés par la relecture des
    fichiers, pas par le contrat.
    """

    events: tuple[RegistryEvent, ...]

    def __post_init__(self) -> None:
        require_immutable_sequence(self.events, "events")
        for i, event in enumerate(self.events):
            if event.number != i + 1:
                raise ContractError(
                    f"events[{i}] porte le numéro {event.number}, {i + 1} attendu."
                )
        for previous, current in pairwise(self.events):
            if current.recorded_at < previous.recorded_at:
                raise ContractError(
                    f"recorded_at de l'événement {current.number} "
                    f"({current.recorded_at.isoformat()}) précède celui de "
                    f"l'événement {previous.number} "
                    f"({previous.recorded_at.isoformat()}) : l'heure ne recule pas."
                )
        self._check_links()

    def _check_links(self) -> None:
        answered: dict[int, int] = {}
        corrected: dict[int, int] = {}
        for event in self.events:
            if event.answers is not None:
                self._check_answer(event, event.answers, answered)
            if event.corrects is not None:
                self._check_correction(event, event.corrects, corrected)

    def _check_answer(
        self, event: RegistryEvent, number: int, answered: dict[int, int]
    ) -> None:
        if self.events[number - 1].kind is not EventKind.DECLARATION:
            raise ContractError(
                f"l'événement {event.number} répond à l'événement {number}, qui n'est "
                "pas une déclaration."
            )
        if event.corrects is None:
            if number in answered:
                raise ContractError(
                    f"la déclaration {number} a déjà une réponse (événement "
                    f"{answered[number]}) : une autre réponse est une correction."
                )
            answered[number] = event.number

    def _check_correction(
        self, event: RegistryEvent, number: int, corrected: dict[int, int]
    ) -> None:
        target = self.events[number - 1]
        if target.kind is not event.kind:
            raise ContractError(
                f"l'événement {event.number} ({event.kind}) corrige l'événement "
                f"{number} ({target.kind}) : une correction vise un événement du même "
                "type."
            )
        if event.answers is not None and target.answers != event.answers:
            raise ContractError(
                f"l'événement {event.number} répond à la déclaration {event.answers} "
                f"et corrige l'événement {number}, qui répond à la déclaration "
                f"{target.answers}."
            )
        if number in corrected:
            raise ContractError(
                f"l'événement {number} est déjà corrigé (événement "
                f"{corrected[number]})."
            )
        corrected[number] = event.number

    def event(self, number: int) -> RegistryEvent:
        """L'événement de ce numéro ; ``IndexError`` hors de ``[1 ; len(events)]``."""
        if not 1 <= number <= len(self.events):
            raise IndexError(
                f"aucun événement de numéro {number} (le journal en compte "
                f"{len(self.events)})."
            )
        return self.events[number - 1]

    def corrected_by(self, number: int) -> int | None:
        """Le numéro de l'événement qui corrige l'événement ``number``, ou ``None``."""
        for event in self.events:
            if event.corrects == number:
                return event.number
        return None

    def in_force(self, number: int) -> bool:
        """L'événement ``number`` n'est pas corrigé ; ``IndexError`` comme ``event``."""
        self.event(number)
        return self.corrected_by(number) is None

    def answer(self, declaration: int) -> RegistryEvent | None:
        """La réponse en vigueur à la déclaration ``declaration`` : le résultat ou
        l'échec non corrigé qui lui répond, ou ``None``."""
        for event in self.events:
            if event.answers == declaration and self.corrected_by(event.number) is None:
                return event
        return None


@dataclass(frozen=True)
class OutingOutcome:
    """Ce qu'une exécution a produit pour une sortie (``0010`` D14, D7.1).

    Champs
    ------
    - ``outing_id`` — sans unité — la sortie.
    - ``coverage`` — sans unité — sa couverture (D4.11).
    - ``scores`` — sans unité — les scores de chaque modèle, couples
      ``(modèle, scores)``.

    Invariants
    ----------
    - ``outing_id`` non vide ; ``scores`` est un tuple de couples (tuples) ;
    - ``scores`` non vide, de modèles distincts ;
    - **la même observation** (``==``) pour tous les modèles (D7.1 : le support ne
      dépend que de l'observation).

    Producteur
    ----------
    L'appelant de ``append_result`` (M4b-5) ; ``load_outcomes``.

    Consommateurs
    -------------
    ``append_result``, qui en écrit les documents ; le rapport (M4b-5).

    Non promis
    ----------
    Rien ne relie la couverture à l'observation.
    """

    outing_id: str
    coverage: Coverage
    scores: tuple[tuple[ModelKind, OutingScores], ...]

    def __post_init__(self) -> None:
        require_non_empty(self.outing_id, "outing_id")
        require_immutable_sequence(self.scores, "scores")
        for i, item in enumerate(self.scores):
            require_immutable_sequence(item, f"scores[{i}]")
            if len(item) != 2:
                raise ContractError(
                    f"scores[{i}] est un couple (modèle, scores), reçu {len(item)} "
                    "éléments."
                )
        if not self.scores:
            raise ContractError("scores ne doit pas être vide : un modèle au moins.")
        _require_distinct(
            [kind for kind, _ in self.scores],
            "les modèles d'une sortie sont distincts, reçu {} deux fois.",
        )
        first_kind, first = self.scores[0]
        for kind, scores in self.scores[1:]:
            if scores.observation != first.observation:
                raise ContractError(
                    f"les scores de {kind} portent une autre observation que ceux de "
                    f"{first_kind} : le support ne dépend que de l'observation (D7.1)."
                )


@dataclass(frozen=True)
class ExperimentTrials:
    """Le nombre d'essais d'un couple effet × cible (``0010`` D14 ; décision 4 de
    rdw).

    Champs
    ------
    - ``effect`` — sans unité — le nom de l'effet.
    - ``target`` — sans unité — la cible.
    - ``count`` — sans unité — les DÉCLARATIONS de ce couple, corrections comprises.

    Invariants
    ----------
    ``effect`` non vide ; ``count >= 1``.

    Producteur
    ----------
    ``count_trials`` (``mountain_perf.backtest.registry``).

    Consommateurs
    -------------
    ``TrialCounts`` ; le rapport (M4b-5) ; l'admission (M4c).

    Non promis
    ----------
    Le comptage ne dit pas quels essais ont produit un candidat ; l'horloge n'entre
    pas dans la clé.
    """

    effect: str
    target: ExperimentMetric
    count: int

    def __post_init__(self) -> None:
        require_non_empty(self.effect, "effect")
        if self.count < 1:
            raise ContractError(
                f"count doit être >= 1 : un couple compté a un essai au moins, reçu "
                f"{self.count}."
            )


@dataclass(frozen=True)
class TrialCounts:
    """Le comptage des essais d'un registre (``0010`` D14 ; décision 4 de rdw).

    Champs
    ------
    - ``declarations`` — sans unité — les DÉCLARATIONS, corrections comprises.
    - ``corrections`` — sans unité — celles qui en corrigent une autre.
    - ``without_effect`` — sans unité — celles sans expérience (exécutions sans effet
      testé).
    - ``by_experiment`` — sans unité — les autres, par couple effet × cible.

    Invariants
    ----------
    - ``by_experiment`` est un tuple ;
    - les trois comptes ``>= 0`` ; ``corrections <= declarations`` ;
    - ``declarations == without_effect + Σ count`` ;
    - ``by_experiment`` ordonné par effet puis par rang de la cible dans
      ``ExperimentMetric``, sans doublon (clés strictement croissantes).

    Producteur
    ----------
    ``count_trials`` (``mountain_perf.backtest.registry``).

    Consommateurs
    -------------
    Le rapport (M4b-5) ; l'admission (M4c).

    Non promis
    ----------
    Chaque DÉCLARATION compte pour un essai, corrections comprises : la règle ne peut
    que surestimer le nombre d'essais ; un ÉCHEC ne compte pas.
    """

    declarations: int
    corrections: int
    without_effect: int
    by_experiment: tuple[ExperimentTrials, ...]

    def __post_init__(self) -> None:
        require_immutable_sequence(self.by_experiment, "by_experiment")
        for name in ("declarations", "corrections", "without_effect"):
            value: int = getattr(self, name)
            if value < 0:
                raise ContractError(f"{name} doit être >= 0, reçu {value}.")
        if self.corrections > self.declarations:
            raise ContractError(
                f"corrections ({self.corrections}) ne dépasse pas declarations "
                f"({self.declarations}) : une correction est une déclaration."
            )
        total = self.without_effect + sum(t.count for t in self.by_experiment)
        if self.declarations != total:
            raise ContractError(
                f"declarations ({self.declarations}) doit valoir without_effect + "
                f"Σ count ({total}) : chaque déclaration compte une fois."
            )
        keys = [(t.effect, _METRIC_ORDER.index(t.target)) for t in self.by_experiment]
        for previous, current in pairwise(keys):
            if not previous < current:
                raise ContractError(
                    "by_experiment est ordonné par effet puis par rang de la cible "
                    "dans ExperimentMetric, sans doublon, reçu "
                    f"{previous} puis {current}."
                )
