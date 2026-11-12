"""Contrats du registre des expériences : déclaration, résultat, échec, journal,
comptage des essais (M4b-4).

Protocole : ``docs/decisions/0010`` D14 (et ses précisions de M4b-4), D0, D2.5, D2.6,
D7.4, D9.1, D9.2, D10.1, D10.3, D10.7. Le registre est un journal, une ligne par
événement en écriture canonique, et des documents nommés par leur empreinte
``sha256`` : une DÉCLARATION figée avant le calcul, puis un RÉSULTAT ou un ÉCHEC qui lui
répond ; une correction est un événement neuf du même type, qui nomme celui qu'il
corrige.

Aucune entrée/sortie ici : l'écriture canonique vit dans ``mountain_perf.codec``, les
documents du registre dans ``mountain_perf.backtest.codec``, le registre sur disque
dans ``mountain_perf.backtest.registry``.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
from collections.abc import Hashable, Iterable, Mapping
from dataclasses import dataclass
from datetime import UTC, date, datetime
from enum import StrEnum
from itertools import pairwise
from types import MappingProxyType

from mountain_perf.schemas.bands import OutingBands
from mountain_perf.schemas.calibration import (
    CALIBRATED_KINDS,
    CalibratedOutingScores,
    ModelKind,
)
from mountain_perf.schemas.clock import CLOCKS, Clock
from mountain_perf.schemas.common import SourceRef
from mountain_perf.schemas.curve import SUPPORT_THRESHOLD_RANGE_MIN
from mountain_perf.schemas.matching import Coverage, SensitivityConfiguration
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

REGISTRY_FORMAT_VERSION = 6
"""Version du format que l'ajout d'un événement ou d'un document écrit (``0010`` D14).

Chaque document la porte, chaque événement aussi (``format_version``). Le registre
relit ses lignes et ses documents par les contrats du jour, strictement : un contrat
stocké qui change de forme demande d'augmenter cette version, et de dire comment
relire l'ancien format. Le format 2 (M4c-2) étend le format 1 sans changer la forme
d'aucun de ses contrats : il ajoute le document des scores calés
(``CalibratedScenarioScores``) ; une ligne ou un document du format 1 se relit donc par
les contrats du jour (précision de D14, M4c-2). Le format 3 (M4c-3) ajoute le document
d'admission (``Admission``) et deux champs, ``Result.admission`` et
``ExperimentDeclaration.reference_documents`` : une ligne d'un format antérieur se relit
sans eux — le registre les ajoute absents avant le décodage, et les retire à la
réécriture canonique (précision de D14, M4c-3). Le format 4 (M4d-2) ajoute le document
des fourchettes d'une sortie (``OutingBands``) et le champ ``OutingResult.bands`` ; une
ligne d'un format antérieur se relit et se réécrit de même, sans lui (précision de D14,
M4d-2). Le format 5 (M4d-3) ajoute la sensibilité de D13 : le champ
``Declaration.sensitivity`` (la DÉCLARATION de sensibilité), les champs
``Result.pairs`` et ``Result.sensitivity`` (son RÉSULTAT) et le document de sensibilité
(``SensitivityOutcome``) ; une ligne d'un format antérieur se relit et se réécrit de
même, sans eux (précision de D14, M4d-3). Le format 6 (OG-2) ajoute le mode glissant :
les champs ``Outing.activity_refs``, ``Declaration.rolling`` et ``Result.rolling``, les
documents ``RollingRule``, ``FrozenCurve``, ``AbsentCurve`` et ``CalibrationTerms``, et
rend facultatifs selon le mode ``curve_ref``, ``curve`` et ``curve_metadata`` (par
exception à Q4.7, ``0010`` précision OG-2, point 12) ; une ligne d'un format antérieur
se relit et se réécrit de même, sans les champs neufs, sa courbe toujours présente."""

REGISTRY_READABLE_FORMATS: tuple[int, ...] = (1, 2, 3, 4, 5, 6)
"""Les formats que le registre relit, dans l'ordre (précisions de D14, M4c-2, M4c-3,
M4d-2, M4d-3 et OG-2) : chaque ligne au sien, chaque document au format de l'événement
qui le cite."""

ADMISSION_FIRST_FORMAT = 3
"""Le premier format dont le RÉSULTAT d'une expérience cite un document d'admission et
dont l'expérience fige ses documents D8 (précision de D14, M4c-3)."""

BANDS_FIRST_FORMAT = 4
"""Le premier format dont le RÉSULTAT de ``just backtest`` cite, pour chaque sortie
scorée avec usage, le document de ses fourchettes (précision de D14, M4d-2)."""

SENSITIVITY_FIRST_FORMAT = 5
"""Le premier format qui connaît la sensibilité de D13 : la DÉCLARATION de sensibilité
(``Declaration.sensitivity``), son RÉSULTAT par paire (``Result.pairs``) et son
document de sensibilité (``Result.sensitivity``) (précision de D14, M4d-3)."""

ROLLING_FIRST_FORMAT = 6
"""Le premier format qui connaît le mode glissant (OG-2, ``0010`` précision OG-2) : la
correspondance déclarée d'une sortie (``Outing.activity_refs``), puis la DÉCLARATION
et le RÉSULTAT glissants. Une ligne d'un format antérieur s'écrit sans ces clés, et se
relit sans elles."""

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
    - ``members`` non vide ; au plus une arrivée, en dernier si elle est présente —
      D7.4 n'exige l'arrivée que du ``K`` par défaut (décision E4 de M4c-3) ;
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
            raise ContractError("members ne doit pas être vide : K non vide (D7.4).")
        arrivals = [i for i, member in enumerate(self.members) if member.arrival]
        if arrivals not in ([], [len(self.members) - 1]):
            raise ContractError(
                "K porte au plus une arrivée, en dernier, reçu l'arrivée aux rangs "
                f"{arrivals} sur {len(self.members)}."
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
    - ``reference_documents`` — sans unité — l'empreinte du document D8 de chaque
      parcours dont une référence figée vient (décision E6 de M4c-3) ; absent avant
      le format 3.
    - ``analysis_date`` — date civile — la date d'analyse fixée d'avance (D10.7) ;
      absente pour une admission exploratoire.

    Invariants
    ----------
    - ``usage_targets`` et ``frozen_references`` sont des tuples ;
    - ``target`` n'est pas ``LEVEL`` (``|L|`` n'est pas une cible) ;
    - ``base`` vaut ``V0_RECALIBRATED`` ; ``candidate`` vaut ``CANDIDATE`` ;
    - ``scenario`` vaut ``USAGE`` : une expérience se déclare en usage, le garde-fou
      des passages n'existant qu'en usage (D10.4 ; précision de D10.1, M4c-3) ;
    - ``usage_targets`` non vide ⇒ ``target`` vaut ``USAGE`` ;
    - les parcours des ``usage_targets`` sont distincts ;
    - les clés ``(metric, clock, source, route_id)`` des références figées sont
      distinctes ;
    - chaque donneur d'une référence empruntée a une référence locale de même
      ``metric``, de même ``clock``, pour ce parcours, disponible ;
    - ``reference_documents`` présent : un tuple, de parcours distincts, exactement
      les parcours des références figées (le ``route_id`` des locales, les donneurs
      des empruntées ; E6).

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
    reference_documents: tuple[RepeatabilityRecord, ...] | None
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
        self._check_documents()

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
        if self.scenario is not Scenario.USAGE:
            raise ContractError(
                "une expérience se déclare en usage : le garde-fou des passages "
                "n'existe qu'en usage (D10.4 ; M4c-3), reçu le scénario "
                f"{self.scenario}."
            )
        if self.usage_targets and self.target is not ExperimentMetric.USAGE:
            raise ContractError(
                "un K déclaré n'existe que pour la cible q_usage (D10.1), reçu la "
                f"cible {self.target}."
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

    def _check_documents(self) -> None:
        documents = self.reference_documents
        if documents is None:
            return
        require_immutable_sequence(documents, "reference_documents")
        _require_distinct(
            [document.route_id for document in documents],
            "les documents D8 figés portent sur des parcours distincts, reçu {!r} "
            "deux fois.",
        )
        routes = {document.route_id for document in documents}
        contributors: set[str] = set()
        for ref in self.frozen_references:
            if ref.source is ReferenceSource.LOCAL and ref.route_id is not None:
                contributors.add(ref.route_id)
            contributors.update(ref.donors)
        if routes != contributors:
            raise ContractError(
                "les documents D8 figés sont ceux des parcours des références figées "
                f"(E6), reçu {sorted(routes)} pour {sorted(contributors)}."
            )


def _require_pair(step_m: float, tolerance_m: float) -> None:
    """Refuse une paire ``(Δ, ε)`` non finie ou non positive."""
    for value, name in ((step_m, "score_step_m"), (tolerance_m, "lateral_tolerance_m")):
        require_finite(value, name)
        if value <= 0:
            raise ContractError(f"{name} doit être > 0, reçu {value}.")


@dataclass(frozen=True)
class PairReferences:
    """Les références D8 d'une paire ``(Δ, ε)`` de la sensibilité, figées avant la
    DÉCLARATION de sensibilité (``0010`` D13, D14 ; précision de M4d-3).

    Champs
    ------
    - ``score_step_m`` — mètres — ``Δ``.
    - ``lateral_tolerance_m`` — mètres — ``ε``.
    - ``references`` — sans unité — le document D8 de chaque parcours du jeu de
      répétabilité, calculé sur les seules observations de la paire.

    Invariants
    ----------
    ``Δ`` et ``ε`` finis et ``> 0`` ; ``references`` est un tuple, de parcours
    distincts.

    Producteur
    ----------
    ``run_sensitivity`` (``mountain_perf.backtest.sensitivity_run``).

    Consommateurs
    -------------
    ``SensitivityDeclaration`` ; l'accord du registre : le RÉSULTAT publie, pour la
    paire, exactement ces documents.

    Non promis
    ----------
    Le contrat ne lit pas les documents.
    """

    score_step_m: float
    lateral_tolerance_m: float
    references: tuple[RepeatabilityRecord, ...]

    def __post_init__(self) -> None:
        _require_pair(self.score_step_m, self.lateral_tolerance_m)
        require_immutable_sequence(self.references, "references")
        _require_distinct(
            [record.route_id for record in self.references],
            "les références D8 d'une paire portent sur des parcours distincts, reçu "
            "{!r} deux fois.",
        )


@dataclass(frozen=True)
class ConfigurationReferences:
    """Les références figées d'une expérience sous une configuration de la sensibilité
    (``0010`` D10.3, D13 ; précision de M4d-3) : celles de la référence D8 de sa paire,
    sous son horloge, par la règle de l'expérience (locale, puis empruntée).

    Champs
    ------
    - ``configuration`` — sans unité — la configuration.
    - ``frozen_references`` — sans unité — ses références figées.

    Invariants
    ----------
    ``frozen_references`` est un tuple ; chacune est sous l'horloge de la
    configuration.

    Producteur
    ----------
    ``run_sensitivity`` (``mountain_perf.backtest.sensitivity_run``).

    Consommateurs
    -------------
    ``SensitivityDeclaration`` ; l'admission de la configuration.

    Non promis
    ----------
    Le contrat ne recalcule pas les références depuis les documents D8.
    """

    configuration: SensitivityConfiguration
    frozen_references: tuple[FrozenReference, ...]

    def __post_init__(self) -> None:
        require_immutable_sequence(self.frozen_references, "frozen_references")
        for i, reference in enumerate(self.frozen_references):
            if reference.clock != self.configuration.clock:
                raise ContractError(
                    f"la référence figée {i} est sous {reference.clock}, l'horloge de "
                    f"la configuration ({self.configuration.clock}) attendue."
                )


@dataclass(frozen=True)
class SensitivityDeclaration:
    """Ce qu'une DÉCLARATION de sensibilité ajoute à la déclaration centrale qu'elle
    qualifie (``0010`` D13, D14 ; précision et exception de M4d-3).

    Champs
    ------
    - ``central`` — sans unité — le numéro de la DÉCLARATION centrale.
    - ``central_hash`` — sans unité — le ``sha256`` de sa ligne.
    - ``answer`` — sans unité — le numéro du RÉSULTAT qui lui répond.
    - ``answer_hash`` — sans unité — le ``sha256`` de sa ligne.
    - ``configurations`` — sans unité — les configurations, dans l'ordre.
    - ``pairs`` — sans unité — les références D8 de chaque paire ``(Δ, ε)`` des
      configurations, figées avant la DÉCLARATION.
    - ``frozen`` — sans unité — pour une expérience, les références figées de chaque
      configuration ; absent sans expérience.

    Invariants
    ----------
    1. ``1 <= central < answer`` ; ``central_hash`` et ``answer_hash`` sont des
       ``sha256`` ;
    2. ``configurations`` et ``pairs`` sont des tuples ; ``configurations`` non vide,
       sans doublon ;
    3. ``pairs`` : une entrée par paire ``(Δ, ε)`` des configurations, dans l'ordre de
       leur première apparition ;
    4. ``frozen`` présent : un tuple, une entrée par configuration, de cette
       configuration, dans l'ordre.

    Producteur
    ----------
    ``run_sensitivity`` (``mountain_perf.backtest.sensitivity_run``).

    Consommateurs
    -------------
    ``Declaration`` ; ``RegistryLog`` (liens) ; l'accord du registre ; le comptage des
    essais ; la vue composée (``sensitivity_qualification``).

    Non promis
    ----------
    Que les configurations soient les dix-neuf de D13, que les lignes nommées soient
    celles du journal, que la déclaration recopie la centrale : c'est l'accord du
    registre qui le vérifie.
    """

    central: int
    central_hash: str
    answer: int
    answer_hash: str
    configurations: tuple[SensitivityConfiguration, ...]
    pairs: tuple[PairReferences, ...]
    frozen: tuple[ConfigurationReferences, ...] | None

    def __post_init__(self) -> None:
        if not 1 <= self.central < self.answer:
            raise ContractError(
                "central et answer sont des numéros d'événement, la réponse après la "
                f"déclaration : 1 <= central < answer, reçu {self.central} et "
                f"{self.answer}."
            )
        _require_sha256(self.central_hash, "central_hash")
        _require_sha256(self.answer_hash, "answer_hash")
        require_immutable_sequence(self.configurations, "configurations")
        require_immutable_sequence(self.pairs, "pairs")
        if not self.configurations:
            raise ContractError("configurations ne doit pas être vide.")
        _require_distinct(
            self.configurations, "une configuration est déclarée une fois, reçu {}."
        )
        expected: list[tuple[float, float]] = []
        for configuration in self.configurations:
            pair = (configuration.score_step_m, configuration.lateral_tolerance_m)
            if pair not in expected:
                expected.append(pair)
        declared = [(p.score_step_m, p.lateral_tolerance_m) for p in self.pairs]
        if declared != expected:
            raise ContractError(
                "pairs porte une entrée par paire (Δ, ε) des configurations, dans "
                f"l'ordre de leur première apparition : {expected} attendu, reçu "
                f"{declared}."
            )
        if self.frozen is not None:
            require_immutable_sequence(self.frozen, "frozen")
            configurations = tuple(entry.configuration for entry in self.frozen)
            if configurations != self.configurations:
                raise ContractError(
                    "frozen porte une entrée par configuration, dans l'ordre des "
                    "configurations."
                )


_BIN_VALUES = ("somme", "médiane")
"""Les deux textes de ``BinValue`` (``estimation/curve.py``), écrits ici sans importer
``estimation/`` (OG-2)."""


@dataclass(frozen=True)
class RollingRule:
    """Le document de règle d'une exécution glissante (OG-2, ``0010`` précision OG-2,
    point 2) : tout ce qui détermine ``κ_j`` hors de l'origine.

    Champs
    ------
    - ``athlete_ref`` — sans unité — l'athlète du manifeste et du corpus.
    - ``commit`` — sans unité — le commit du code qui applique la règle.
    - ``window_days`` — jours — la fenêtre ``W`` ; ``None`` : tout le passé.
    - ``source_activity_types`` — sans unité — les types de la source sélectionnés.
    - ``min_duration_s``, ``max_duration_s`` — secondes — les durées de la sélection.
    - ``max_elapsed_s`` — secondes — le plafond depuis le départ.
    - ``hr_center_bpm`` — battements par minute — le centre de la bande de FC.
    - ``value`` — sans unité — la valeur des tranches (« somme », « médiane »).
    - ``parameters`` — unités de chaque paramètre — les paramètres effectifs de
      l'estimation, défauts compris.
    - ``profile_parameters`` — unités de chaque paramètre — ceux du profil.
    - ``diagnostic_support_threshold_min`` — minutes — le seuil des diagnostics.

    Invariants
    ----------
    - textes non vides ; ``window_days >= 1`` ou ``None`` ;
    - types non vides, triés, distincts ;
    - ``value`` dans les valeurs de ``BinValue`` ;
    - durées finies et ``>= 0`` ; le seuil dans ``SUPPORT_THRESHOLD_RANGE_MIN``.

    Producteur
    ----------
    ``prepare_rolling`` (``mountain_perf.backtest.rolling``).

    Consommateurs
    -------------
    La DÉCLARATION glissante (son empreinte) ; l'accord du registre (condition R et
    condition 2).

    Non promis
    ----------
    Ni ``s``, ni le repère, ni le seuil de lecture, ni la tolérance, ni la plateforme :
    ils sont à la DÉCLARATION, les documents de règle d'une commande étant égaux hors
    ``W``.
    """

    athlete_ref: str
    commit: str
    window_days: int | None
    source_activity_types: tuple[str, ...]
    min_duration_s: float | None
    max_duration_s: float | None
    max_elapsed_s: float | None
    hr_center_bpm: float | None
    value: str
    parameters: Mapping[str, float]
    profile_parameters: Mapping[str, float]
    diagnostic_support_threshold_min: float

    def __post_init__(self) -> None:
        for name in ("athlete_ref", "commit", "value"):
            require_non_empty(getattr(self, name), name)
        if self.window_days is not None and self.window_days < 1:
            raise ContractError(
                f"window_days doit valoir au moins 1, reçu {self.window_days}."
            )
        require_immutable_sequence(self.source_activity_types, "source_activity_types")
        if not self.source_activity_types:
            raise ContractError("source_activity_types ne doit pas être vide.")
        for text in self.source_activity_types:
            require_non_empty(text, "source_activity_types")
        if list(self.source_activity_types) != sorted(set(self.source_activity_types)):
            raise ContractError(
                "source_activity_types : des types triés et distincts attendus."
            )
        if self.value not in _BIN_VALUES:
            raise ContractError(
                f"value : l'une de {list(_BIN_VALUES)} attendue, reçu {self.value!r}."
            )
        for name in ("min_duration_s", "max_duration_s", "max_elapsed_s"):
            duration: float | None = getattr(self, name)
            if duration is not None:
                require_finite(duration, name)
                if duration < 0:
                    raise ContractError(f"{name} doit être >= 0, reçu {duration}.")
        threshold = self.diagnostic_support_threshold_min
        require_finite(threshold, "diagnostic_support_threshold_min")
        low, high = SUPPORT_THRESHOLD_RANGE_MIN
        if not low <= threshold <= high:
            raise ContractError(
                f"diagnostic_support_threshold_min doit être dans [{low} ; {high}], "
                f"reçu {threshold}."
            )
        object.__setattr__(self, "parameters", MappingProxyType(dict(self.parameters)))
        object.__setattr__(
            self,
            "profile_parameters",
            MappingProxyType(dict(self.profile_parameters)),
        )


@dataclass(frozen=True)
class FrozenCurve:
    """La courbe figée d'une performance (OG-2, ``0010`` précision OG-2, point 3) : les
    octets du CSV de ``mperf curve --at`` et du compagnon sans instant d'estimation ni
    commit, en textes UTF-8.

    Champs
    ------
    - ``csv`` — sans unité — le texte du CSV.
    - ``companion`` — sans unité — le texte du compagnon figé.

    Propriété calculée (jamais stockée) : ``csv_sha256``, l'empreinte des octets UTF-8
    du CSV — « la même courbe » se dit par elle.

    Invariants
    ----------
    - textes non vides ;
    - ``companion`` est un objet JSON sans clé ``generated_at``.

    Producteur
    ----------
    ``prepare_rolling`` (``mountain_perf.backtest.rolling``).

    Consommateurs
    -------------
    La DÉCLARATION glissante (son empreinte) ; le RÉSULTAT (qui le publie) ; l'accord.

    Non promis
    ----------
    Le contrat ne relit pas le CSV : l'accord le fait (condition 5 bis).
    """

    csv: str
    companion: str

    def __post_init__(self) -> None:
        require_non_empty(self.csv, "csv")
        require_non_empty(self.companion, "companion")
        try:
            document = json.loads(self.companion)
        except ValueError as error:
            raise ContractError("companion : un objet JSON attendu.") from error
        if not isinstance(document, dict):
            raise ContractError("companion : un objet JSON attendu.")
        if "generated_at" in document:
            raise ContractError(
                "companion : un compagnon figé ne porte pas la clé « generated_at »."
            )

    @property
    def csv_sha256(self) -> str:
        """L'empreinte ``sha256`` des octets UTF-8 du CSV."""
        return hashlib.sha256(self.csv.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class AbsentCurve:
    """La courbe absente d'une performance (OG-2, ``0010`` précision OG-2, point 3) :
    le document d'``origin_absence_document``, en texte UTF-8.

    Champs
    ------
    - ``document`` — sans unité — le texte du document d'absence.

    Invariants
    ----------
    ``document`` non vide.

    Producteur
    ----------
    ``prepare_rolling`` (``mountain_perf.backtest.rolling``).

    Consommateurs
    -------------
    La DÉCLARATION glissante (son empreinte) ; le RÉSULTAT ; l'accord.

    Non promis
    ----------
    Le contrat ne relit pas le document : l'accord le fait.
    """

    document: str

    def __post_init__(self) -> None:
        require_non_empty(self.document, "document")


class CurveStatus(StrEnum):
    """Le sort de la courbe d'une performance en mode glissant (OG-2).

    Valeurs décrites dans ``CURVE_STATUS_DESCRIPTIONS``.
    """

    CURVE = "curve"
    ABSENT = "absent"
    NO_READ_SUPPORT = "no_read_support"


CURVE_STATUS_DESCRIPTIONS: Mapping[CurveStatus, str] = MappingProxyType(
    {
        CurveStatus.CURVE: "courbe",
        CurveStatus.ABSENT: "sans courbe : absence",
        CurveStatus.NO_READ_SUPPORT: "sans courbe : aucun support au seuil de lecture",
    }
)


class ShareScope(StrEnum):
    """Sur quel profil se prend la part hors support d'une performance (OG-2).

    Valeurs décrites dans ``SHARE_SCOPE_DESCRIPTIONS``.
    """

    USAGE = "usage"
    CONTROL = "control"


SHARE_SCOPE_DESCRIPTIONS: Mapping[ShareScope, str] = MappingProxyType(
    {
        ShareScope.USAGE: "usage — sur la portion déclarée du profil de référence.",
        ShareScope.CONTROL: (
            "contrôle — sans référence, sur le profil de la trace (PG11 de la note)."
        ),
    }
)


class ShareUnavailability(StrEnum):
    """Le motif d'une part hors support indisponible (OG-2, PG12).

    Valeurs décrites dans ``SHARE_UNAVAILABILITY_DESCRIPTIONS``.
    """

    NO_CURVE = "no_curve"
    MULTI_OUTING_DAY = "multi_outing_day"
    NO_PROFILE = "no_profile"


SHARE_UNAVAILABILITY_DESCRIPTIONS: Mapping[ShareUnavailability, str] = MappingProxyType(
    {
        ShareUnavailability.NO_CURVE: "sans courbe — l'un des deux statuts.",
        ShareUnavailability.MULTI_OUTING_DAY: (
            "jour multi-sorties — la portion déclarée est celle d'une sortie."
        ),
        ShareUnavailability.NO_PROFILE: (
            "sans profil — une sortie non tracée et sans référence."
        ),
    }
)


@dataclass(frozen=True)
class RollingPerformance:
    """Ce qu'une DÉCLARATION glissante fixe d'une performance (OG-2, ``0010``
    précision OG-2, points 3 et 9).

    Champs
    ------
    - ``status`` — sans unité — le sort de sa courbe.
    - ``document`` — sans unité — le ``sha256`` du document ``FrozenCurve`` ou
      ``AbsentCurve``.
    - ``curve_sha256`` — sans unité — le ``sha256`` des octets du CSV ; absent pour une
      absence.
    - ``curve_ref`` — sans unité — ``<nom>#<12 caractères>`` ; absent pour une absence.
    - ``out_of_support_share`` — fraction — la part hors support, entière.
    - ``share_scope`` — sans unité — le profil de la part.
    - ``share_unavailability`` — sans unité — le motif d'une part indisponible.

    Invariants
    ----------
    - ``document`` est un ``sha256`` ;
    - ``ABSENT`` ⟺ ``curve_sha256`` et ``curve_ref`` absents ; sinon ``curve_sha256``
      est un ``sha256`` et ``curve_ref`` vaut ``<nom>#<curve_sha256[:12]>`` ;
    - la part présente ⟺ ``share_unavailability`` absent ;
    - la part présente : dans ``[0 ; 1]``, avec ``share_scope``, et le statut vaut
      ``CURVE`` ;
    - le statut n'est pas ``CURVE`` : ``share_unavailability`` vaut ``NO_CURVE``.

    Producteur
    ----------
    ``prepare_rolling`` (``mountain_perf.backtest.rolling``).

    Consommateurs
    -------------
    ``RollingDeclaration`` ; l'accord ; les rapports (ensembles).

    Non promis
    ----------
    Le contrat ne relit pas les documents.
    """

    status: CurveStatus
    document: str
    curve_sha256: str | None
    curve_ref: str | None
    out_of_support_share: float | None
    share_scope: ShareScope | None
    share_unavailability: ShareUnavailability | None

    def __post_init__(self) -> None:
        _require_sha256(self.document, "document")
        if self.status is CurveStatus.ABSENT:
            if self.curve_sha256 is not None or self.curve_ref is not None:
                raise ContractError(
                    "une courbe absente n'a ni curve_sha256 ni curve_ref (OG-2)."
                )
        else:
            if self.curve_sha256 is None or self.curve_ref is None:
                raise ContractError(
                    f"une performance {self.status} porte curve_sha256 et curve_ref "
                    "(OG-2)."
                )
            _require_sha256(self.curve_sha256, "curve_sha256")
            name, separator, digest = self.curve_ref.rpartition("#")
            expected = self.curve_sha256[:CURVE_REF_HASH_LENGTH]
            if not name or not separator or digest != expected:
                raise ContractError(
                    f"curve_ref ({self.curve_ref!r}) doit valoir "
                    f"'<nom>#{expected}' (OG-2)."
                )
        share = self.out_of_support_share
        if (share is None) == (self.share_unavailability is None):
            raise ContractError(
                "la part hors support est présente si et seulement si son motif "
                "d'indisponibilité est absent (OG-2)."
            )
        if share is not None:
            require_finite(share, "out_of_support_share")
            if not 0 <= share <= 1:
                raise ContractError(
                    f"out_of_support_share doit être dans [0 ; 1], reçu {share}."
                )
            if self.share_scope is None:
                raise ContractError("une part présente porte son share_scope (OG-2).")
            if self.status is not CurveStatus.CURVE:
                raise ContractError("une part présente demande le statut curve (OG-2).")
        elif self.share_scope is not None:
            raise ContractError("une part indisponible n'a pas de share_scope (OG-2).")
        if (
            self.status is not CurveStatus.CURVE
            and self.share_unavailability is not ShareUnavailability.NO_CURVE
        ):
            raise ContractError(
                "sans courbe, la part est indisponible au motif no_curve (OG-2)."
            )


@dataclass(frozen=True)
class RollingDeclaration:
    """Le mode glissant d'une DÉCLARATION (OG-2, ``0010`` précision OG-2, points 1, 2,
    9 et 10).

    Champs
    ------
    - ``rule`` — sans unité — le ``sha256`` du document ``RollingRule``.
    - ``window_days`` — jours — la fenêtre ; ``None`` : tout le passé.
    - ``command_windows`` — jours — les fenêtres de la commande, dans son ordre.
    - ``covered_threshold`` — fraction — ``s`` : couverte ⟺ part ``<= s``.
    - ``beyond_marker`` — fraction — le repère : au-delà ⟺ part ``>`` repère.
    - ``coverage_tolerance_s`` — secondes — la tolérance de la correspondance.
    - ``index_sha256`` — sans unité — l'empreinte de l'index d'``interim/`` lu.
    - ``platform`` — sans unité — la plateforme de l'exécution.
    - ``performances`` — sans unité — une entrée par performance, dans l'ordre.

    Invariants
    ----------
    - ``rule`` et ``index_sha256`` sont des ``sha256`` ;
    - ``window_days >= 1`` ou ``None`` ;
    - ``command_windows`` non vide, distinctes, chacune ``>= 1`` ou ``None``, et
      contient ``window_days`` ;
    - ``covered_threshold`` et ``beyond_marker`` finis, dans ``[0 ; 1]`` ;
    - la tolérance finie, ``>= 0`` ; ``platform`` non vide.

    Producteur
    ----------
    ``prepare_rolling`` (``mountain_perf.backtest.rolling``).

    Consommateurs
    -------------
    ``Declaration`` ; l'accord ; les rapports.

    Non promis
    ----------
    Le seuil de lecture n'y est pas : c'est le paramètre déclaré
    ``curve_min_support_min`` de v0 brut et du comparateur.
    """

    rule: str
    window_days: int | None
    command_windows: tuple[int | None, ...]
    covered_threshold: float
    beyond_marker: float
    coverage_tolerance_s: float
    index_sha256: str
    platform: str
    performances: tuple[RollingPerformance, ...]

    def __post_init__(self) -> None:
        _require_sha256(self.rule, "rule")
        _require_sha256(self.index_sha256, "index_sha256")
        require_immutable_sequence(self.command_windows, "command_windows")
        require_immutable_sequence(self.performances, "performances")
        for name, window in (
            ("window_days", self.window_days),
            *(("command_windows", w) for w in self.command_windows),
        ):
            if window is not None and window < 1:
                raise ContractError(f"{name} : au moins 1 jour, reçu {window}.")
        if not self.command_windows:
            raise ContractError("command_windows ne doit pas être vide.")
        _require_distinct(
            self.command_windows, "command_windows : {!r} donnée deux fois."
        )
        if self.window_days not in self.command_windows:
            raise ContractError(
                f"command_windows doit contenir window_days ({self.window_days})."
            )
        for name in ("covered_threshold", "beyond_marker"):
            value: float = getattr(self, name)
            require_finite(value, name)
            if not 0 <= value <= 1:
                raise ContractError(f"{name} doit être dans [0 ; 1], reçu {value}.")
        require_finite(self.coverage_tolerance_s, "coverage_tolerance_s")
        if self.coverage_tolerance_s < 0:
            raise ContractError(
                "coverage_tolerance_s doit être >= 0, reçu "
                f"{self.coverage_tolerance_s}."
            )
        require_non_empty(self.platform, "platform")


@dataclass(frozen=True)
class CalibrationTerm:
    """Un membre du calage d'une performance (OG-2, E6) : les termes dont ``β`` est
    fait.

    Champs
    ------
    - ``civil_date`` — date civile — le jour du membre.
    - ``observed_s`` — secondes — ``T_c``.
    - ``forecast_s`` — secondes — ``P_c`` ; absent : la projection du membre est
      invalide.

    Invariants
    ----------
    ``T_c`` fini et ``> 0`` ; ``P_c`` absent, ou fini et ``> 0``.

    Producteur
    ----------
    ``calibration_terms`` (``mountain_perf.backtest.calibration``).

    Consommateurs
    -------------
    ``ScenarioClockTerms`` ; l'accord (condition 7) ; le rapport (contributeurs).

    Non promis
    ----------
    Le terme ne dit pas la sortie du membre.
    """

    civil_date: date
    observed_s: float
    forecast_s: float | None

    def __post_init__(self) -> None:
        require_finite(self.observed_s, "observed_s")
        if not self.observed_s > 0:
            raise ContractError(f"observed_s doit être > 0, reçu {self.observed_s}.")
        if self.forecast_s is not None:
            require_finite(self.forecast_s, "forecast_s")
            if not self.forecast_s > 0:
                raise ContractError(
                    f"forecast_s doit être > 0, reçu {self.forecast_s}."
                )


@dataclass(frozen=True)
class ScenarioClockTerms:
    """Les termes du calage d'une performance sous un scénario et une horloge (OG-2).

    Champs
    ------
    - ``scenario`` — sans unité — le scénario.
    - ``clock`` — sans unité — l'horloge.
    - ``terms`` — sans unité — un terme par membre de ``C_j^eff``, dans l'ordre.

    Invariants
    ----------
    ``terms`` est un tuple ; jours strictement croissants.

    Producteur
    ----------
    ``evaluate_rolling`` (``mountain_perf.backtest.rolling``).

    Consommateurs
    -------------
    ``CalibrationTerms``.

    Non promis
    ----------
    Le contrat ne recalcule pas ``β``.
    """

    scenario: Scenario
    clock: Clock
    terms: tuple[CalibrationTerm, ...]

    def __post_init__(self) -> None:
        require_immutable_sequence(self.terms, "terms")
        for previous, current in pairwise(self.terms):
            if not previous.civil_date < current.civil_date:
                raise ContractError(
                    "les termes sont par jour strictement croissant, reçu "
                    f"{previous.civil_date} puis {current.civil_date}."
                )


@dataclass(frozen=True)
class CalibrationTerms:
    """Le document des termes du calage d'une performance (OG-2, E6) : pour le
    comparateur, chaque scénario présent et chaque horloge, les ``(T_c, P_c)`` des
    membres de ``C_j^eff``.

    Champs
    ------
    - ``model`` — sans unité — le comparateur, v0 + effort recalé.
    - ``sets`` — sans unité — un ensemble de termes par paire ``(scénario, horloge)``.

    Invariants
    ----------
    ``model`` est ``ModelKind.V0_RECALIBRATED`` ; ``sets`` est un tuple ; paires
    ``(scenario, clock)`` distinctes, dans l'ordre des scénarios puis de ``CLOCKS``.

    Producteur
    ----------
    ``evaluate_rolling`` (``mountain_perf.backtest.rolling``).

    Consommateurs
    -------------
    Le RÉSULTAT glissant ; l'accord (condition 7) ; le rapport.

    Non promis
    ----------
    Le contrat ne recoupe pas les termes avec un calage : l'accord le fait.
    """

    model: ModelKind
    sets: tuple[ScenarioClockTerms, ...]

    def __post_init__(self) -> None:
        if self.model is not ModelKind.V0_RECALIBRATED:
            raise ContractError(
                "le document des termes porte le comparateur, v0 + effort recalé, "
                f"reçu {self.model}."
            )
        require_immutable_sequence(self.sets, "sets")
        scenarios = tuple(Scenario)
        keys = [
            (scenarios.index(item.scenario), CLOCKS.index(item.clock))
            if item.clock in CLOCKS
            else (scenarios.index(item.scenario), -1)
            for item in self.sets
        ]
        for previous, current in pairwise(keys):
            if not previous < current:
                raise ContractError(
                    "les paires (scénario, horloge) sont distinctes, dans l'ordre des "
                    "scénarios puis de CLOCKS."
                )


@dataclass(frozen=True)
class RollingResult:
    """Ce que le RÉSULTAT d'une exécution glissante publie de plus (OG-2, ``0010``
    précision OG-2, point 12).

    Champs
    ------
    - ``rule`` — sans unité — le ``sha256`` du document de règle.
    - ``curves`` — sans unité — les documents de courbe, un par performance, dans
      l'ordre de la DÉCLARATION.
    - ``calibration_terms`` — sans unité — un document ``CalibrationTerms`` par
      performance ; absent pour une performance sans courbe.

    Invariants
    ----------
    des ``sha256`` ; ``curves`` et ``calibration_terms`` de même longueur.

    Producteur
    ----------
    ``append_result`` (``mountain_perf.backtest.registry``).

    Consommateurs
    -------------
    ``Result`` ; l'accord.

    Non promis
    ----------
    Le contrat ne lit pas les documents.
    """

    rule: str
    curves: tuple[str, ...]
    calibration_terms: tuple[str | None, ...]

    def __post_init__(self) -> None:
        _require_sha256(self.rule, "rule")
        require_immutable_sequence(self.curves, "curves")
        require_immutable_sequence(self.calibration_terms, "calibration_terms")
        for sha in self.curves:
            _require_sha256(sha, "curves")
        for item in self.calibration_terms:
            if item is not None:
                _require_sha256(item, "calibration_terms")
        if len(self.curves) != len(self.calibration_terms):
            raise ContractError(
                "curves et calibration_terms : un document par performance (OG-2)."
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
    - ``curve_ref`` — sans unité — la référence de la courbe ; absente en mode
      glissant (format 6, OG-2).
    - ``curve`` — sans unité — le CSV de la courbe ; absent en mode glissant.
    - ``curve_metadata`` — sans unité — son compagnon ``.meta.json`` ; absent en mode
      glissant.
    - ``manifest`` — sans unité — le manifeste lu, cité par son empreinte, sans rôle.
    - ``performances`` — sans unité — les performances évaluées.
    - ``exclusions`` — sans unité — les sorties écartées, avec leur motif.
    - ``models`` — sans unité — les modèles évalués.
    - ``experiment`` — sans unité — l'expérience ; absente sans effet testé.
    - ``sensitivity`` — sans unité — ce qu'ajoute une DÉCLARATION de sensibilité
      (format 5, M4d-3) ; absent pour une autre déclaration.
    - ``rolling`` — sans unité — le mode glissant (OG-2) : ``None`` pour une courbe
      déclarée.

    Propriétés calculées (jamais stockées) : ``outing_ids``, ``route_ids``,
    ``artifacts``.

    Invariants
    ----------
    1. ``protocol_record``, ``athlete_ref``, ``curve_ref`` (présent) non vides ;
       ``clocks``,
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
       ``clocks`` ; le parcours de chaque ``K`` est dans ``route_ids`` ;
    9. ``sensitivity`` présent : l'horloge de chacune de ses configurations est dans
       ``clocks`` ; ses références figées sont présentes **si et seulement si** la
       déclaration porte une expérience ;
    10. ``rolling`` absent : ``curve_ref``, ``curve`` et ``curve_metadata`` présents
        (l'invariant 4) ; ``rolling`` présent : les trois absents (OG-2, D-P7) ;
    11. ``rolling`` présent : ni ``experiment`` ni ``sensitivity`` (D-OG2-8) ;
    12. ``rolling`` présent : une entrée de ``rolling.performances`` par performance.

    Producteur
    ----------
    L'appelant de ``append_declaration`` (M4b-5, M4c, M4d-3).

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
    curve_ref: str | None
    curve: ArtifactRef | None
    curve_metadata: ArtifactRef | None
    manifest: SourceRef
    performances: tuple[DeclaredPerformance, ...]
    exclusions: tuple[Exclusion, ...]
    models: tuple[DeclaredModel, ...]
    experiment: ExperimentDeclaration | None
    sensitivity: SensitivityDeclaration | None = None
    rolling: RollingDeclaration | None = None

    def __post_init__(self) -> None:
        for name in ("protocol_record", "athlete_ref"):
            require_non_empty(getattr(self, name), name)
        if self.curve_ref is not None:
            require_non_empty(self.curve_ref, "curve_ref")
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
        if self.sensitivity is not None:
            self._check_sensitivity(self.sensitivity)
        if self.rolling is not None:
            self._check_rolling(self.rolling)

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
        """Tous les fichiers déclarés (D2.6) : la courbe et son compagnon s'ils sont
        présents (OG-2), puis, sortie par sortie, ses traces, ses doublons et sa
        référence si elle en a une."""
        files = [f for f in (self.curve, self.curve_metadata) if f is not None]
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
        present = [
            value is not None
            for value in (self.curve_ref, self.curve, self.curve_metadata)
        ]
        if self.rolling is not None:
            if any(present):
                raise ContractError(
                    "le mode glissant n'a pas de courbe déclarée : curve_ref, curve et "
                    "curve_metadata absents (0010, précision OG-2, D-P7)."
                )
            return
        if not all(present):
            raise ContractError(
                "curve_ref, curve et curve_metadata vont ensemble en mode « courbe "
                "déclarée » (0010 D2.6)."
            )
        assert self.curve is not None  # all(present)
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

    def _check_sensitivity(self, sensitivity: SensitivityDeclaration) -> None:
        for i, configuration in enumerate(sensitivity.configurations):
            if configuration.clock not in self.clocks:
                raise ContractError(
                    f"l'horloge de la configuration {i} ({configuration.clock}) doit "
                    "être une horloge de l'exécution (clocks)."
                )
        if (sensitivity.frozen is None) != (self.experiment is None):
            raise ContractError(
                "une DÉCLARATION de sensibilité fige les références de chaque "
                "configuration si et seulement si elle porte une expérience (M4d-3)."
            )

    def _check_rolling(self, rolling: RollingDeclaration) -> None:
        if self.experiment is not None:
            raise ContractError(
                "une expérience d'admission n'existe pas en mode glissant : hors du "
                "jalon (0010 D10, précision OG-2)."
            )
        if self.sensitivity is not None:
            raise ContractError(
                "une DÉCLARATION de sensibilité n'existe pas en mode glissant : hors "
                "du jalon (0010 D13, précision OG-2)."
            )
        if len(rolling.performances) != len(self.performances):
            raise ContractError(
                "rolling : une entrée par performance attendue "
                f"({len(self.performances)}), reçu {len(rolling.performances)}."
            )


@dataclass(frozen=True)
class ModelResult:
    """Les documents des scores d'un modèle sur une sortie (``0010`` D14).

    Champs
    ------
    - ``model`` — sans unité — la nature du modèle.
    - ``control`` — sans unité — le ``sha256`` du document ``ScenarioScores`` du
      contrôle, prévision comprise ; depuis le format 2, ``CalibratedScenarioScores``
      pour un modèle calé (M4c-2).
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
    - ``bands`` — sans unité — le ``sha256`` du document ``OutingBands`` (format 4,
      M4d-2) ; absent sans fourchettes.

    Invariants
    ----------
    - ``outing_id`` non vide ; ``observation`` est un ``sha256`` ; ``models`` est un
      tuple ;
    - ``models`` non vide, de modèles distincts ;
    - ``usage`` présent pour tous les modèles ou pour aucun ;
    - ``bands`` présent : un ``sha256``, et l'usage est présent.

    Producteur
    ----------
    ``append_result`` (``mountain_perf.backtest.registry``).

    Consommateurs
    -------------
    ``Result`` ; la relecture et la vérification du registre ; ``load_outcomes``.

    Non promis
    ----------
    Le contrat ne lit pas les documents ; rien ne relie la couverture à
    l'observation ; qui porte des fourchettes est dit par l'accord du registre.
    """

    outing_id: str
    coverage: Coverage
    observation: str
    models: tuple[ModelResult, ...]
    bands: str | None = None

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
        if self.bands is not None:
            _require_sha256(self.bands, "bands")
            if self.models[0].usage is None:
                raise ContractError(
                    "des fourchettes demandent l'usage (0010 D11) : la sortie n'en a "
                    "pas."
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
class PairResult:
    """Ce que le RÉSULTAT d'une sensibilité porte d'une paire ``(Δ, ε)`` (``0010`` D13,
    D14 ; précision de M4d-3) : ce que porte le RÉSULTAT d'une exécution.

    Champs
    ------
    - ``score_step_m`` — mètres — ``Δ``.
    - ``lateral_tolerance_m`` — mètres — ``ε``.
    - ``outings`` — sans unité — les sorties scorées sous la paire.
    - ``unscored`` — sans unité — les sorties déclarées non scorées, avec leur motif.
    - ``references`` — sans unité — les références D8 des parcours, sous la paire.

    Invariants
    ----------
    - ``Δ`` et ``ε`` finis et ``> 0`` ;
    - ``outings``, ``unscored`` et ``references`` sont des tuples ;
    - les identifiants de ``outings`` et de ``unscored``, pris ensemble, sont
      distincts ; les parcours de ``references`` sont distincts.

    Producteur
    ----------
    ``append_result`` (``mountain_perf.backtest.registry``).

    Consommateurs
    -------------
    ``Result`` ; la relecture et la vérification du registre ; ``load_pair_outcomes``.

    Non promis
    ----------
    L'accord avec la déclaration est vérifié par le registre, pas par le contrat.
    """

    score_step_m: float
    lateral_tolerance_m: float
    outings: tuple[OutingResult, ...]
    unscored: tuple[Exclusion, ...]
    references: tuple[RepeatabilityRecord, ...]

    def __post_init__(self) -> None:
        _require_pair(self.score_step_m, self.lateral_tolerance_m)
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
class Result:
    """Le contenu d'un RÉSULTAT (``0010`` D14, D0).

    Champs
    ------
    - ``outings`` — sans unité — les sorties scorées.
    - ``unscored`` — sans unité — les sorties déclarées non scorées, avec leur motif.
    - ``references`` — sans unité — les références D8 des parcours.
    - ``admission`` — sans unité — le ``sha256`` du document d'admission d'une
      expérience (format 3, M4c-3) ; absent sans expérience.
    - ``pairs`` — sans unité — pour une sensibilité, chaque paire ``(Δ, ε)`` (format 5,
      M4d-3) ; vide sinon.
    - ``sensitivity`` — sans unité — pour une sensibilité, le ``sha256`` du document
      ``SensitivityOutcome`` (format 5, M4d-3) ; absent sinon.
    - ``rolling`` — sans unité — ce que publie une exécution glissante (format 6,
      OG-2) ; absent sinon.

    Invariants
    ----------
    - ``outings``, ``unscored``, ``references`` et ``pairs`` sont des tuples ;
    - les identifiants de ``outings`` et de ``unscored``, pris ensemble, sont
      distincts ;
    - les parcours de ``references`` sont distincts ;
    - ``admission`` présent : un ``sha256`` ;
    - ``sensitivity`` présent : un ``sha256`` ; ``pairs`` non vide **si et seulement
      si** ``sensitivity`` est présent ; alors ``outings``, ``unscored`` et
      ``references`` sont vides, ``admission`` absent, et les paires ``(Δ, ε)`` sont
      distinctes.

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
    - le document d'admission n'est pas lu par le contrat : la relecture du registre
      le décode et recoupe sa cible et son horloge (M4c-3) ;
    - l'ordre des sorties est celui de l'appelant.
    """

    outings: tuple[OutingResult, ...]
    unscored: tuple[Exclusion, ...]
    references: tuple[RepeatabilityRecord, ...]
    admission: str | None = None
    pairs: tuple[PairResult, ...] = ()
    sensitivity: str | None = None
    rolling: RollingResult | None = None

    def __post_init__(self) -> None:
        for name in ("outings", "unscored", "references", "pairs"):
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
        if self.admission is not None:
            _require_sha256(self.admission, "admission")
        self._check_sensitivity()

    def _check_sensitivity(self) -> None:
        if self.sensitivity is not None:
            _require_sha256(self.sensitivity, "sensitivity")
        if bool(self.pairs) != (self.sensitivity is not None):
            raise ContractError(
                "pairs est non vide si et seulement si sensitivity est présent : le "
                "RÉSULTAT d'une sensibilité (M4d-3)."
            )
        if self.sensitivity is None:
            return
        if self.outings or self.unscored or self.references or self.admission:
            raise ContractError(
                "le RÉSULTAT d'une sensibilité porte ses sorties paire par paire : ni "
                "outings, ni unscored, ni references, ni admission (M4d-3)."
            )
        _require_distinct(
            [(pair.score_step_m, pair.lateral_tolerance_m) for pair in self.pairs],
            "les paires (Δ, ε) d'une sensibilité sont distinctes, reçu {} deux fois.",
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
    2. ``format_version`` dans ``REGISTRY_READABLE_FORMATS`` (1 à 5, M4d-3) ;
       avant le format 3, ni ``Result.admission``, ni ``reference_documents`` d'une
       expérience ; avant le format 4, aucune sortie avec ``bands`` ; avant le format
       5, ni ``Declaration.sensitivity``, ni ``Result.pairs``, ni
       ``Result.sensitivity`` (vérifiés en dernier) ;
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
        if self.format_version not in REGISTRY_READABLE_FORMATS:
            formats = ", ".join(map(str, REGISTRY_READABLE_FORMATS))
            raise ContractError(
                f"format_version vaut l'un de {formats}, reçu {self.format_version}."
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
        self._check_before_format_3()
        self._check_before_format_4()
        self._check_before_format_5()

    def _check_before_format_3(self) -> None:
        """Invariant 2, avant le format 3 : ni document d'admission, ni documents D8
        figés (précision de D14, M4c-3)."""
        version = self.format_version
        if version >= ADMISSION_FIRST_FORMAT:
            return
        if self.result is not None and self.result.admission is not None:
            raise ContractError(
                f"un RÉSULTAT du format {version} ne cite pas de document d'admission "
                "(format 3)."
            )
        experiment = None if self.declaration is None else self.declaration.experiment
        if experiment is not None and experiment.reference_documents is not None:
            raise ContractError(
                f"une expérience du format {version} ne fige pas de documents D8 "
                "(format 3)."
            )

    def _check_before_format_4(self) -> None:
        """Invariant 2, avant le format 4 : aucune sortie ne cite de fourchettes
        (précision de D14, M4d-2)."""
        version = self.format_version
        if version >= BANDS_FIRST_FORMAT or self.result is None:
            return
        if any(outing.bands is not None for outing in self.result.outings):
            raise ContractError(
                f"un RÉSULTAT du format {version} ne cite pas de fourchettes "
                "(format 4)."
            )

    def _check_before_format_5(self) -> None:
        """Invariant 2, avant le format 5 : ni DÉCLARATION de sensibilité, ni RÉSULTAT
        de sensibilité (précision de D14, M4d-3)."""
        version = self.format_version
        if version >= SENSITIVITY_FIRST_FORMAT:
            return
        if self.declaration is not None and self.declaration.sensitivity is not None:
            raise ContractError(
                f"une DÉCLARATION du format {version} ne porte pas de sensibilité "
                "(format 5)."
            )
        if self.result is not None and (
            self.result.pairs or self.result.sensitivity is not None
        ):
            raise ContractError(
                f"un RÉSULTAT du format {version} ne porte pas de sensibilité "
                "(format 5)."
            )

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
    4. un événement est corrigé au plus une fois ;
    5. une DÉCLARATION de sensibilité (M4d-3) nomme une DÉCLARATION centrale qui la
       précède et n'est pas elle-même une sensibilité, et un RÉSULTAT qui la précède
       et répond à cette centrale.

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
            sensitivity = (
                None if event.declaration is None else event.declaration.sensitivity
            )
            if sensitivity is not None:
                self._check_sensitivity(event, sensitivity)

    def _check_sensitivity(
        self, event: RegistryEvent, sensitivity: SensitivityDeclaration
    ) -> None:
        if sensitivity.answer >= event.number:
            raise ContractError(
                f"la DÉCLARATION de sensibilité {event.number} nomme l'événement "
                f"{sensitivity.answer}, qui ne la précède pas."
            )
        central = self.events[sensitivity.central - 1]
        if central.declaration is None or central.declaration.sensitivity is not None:
            raise ContractError(
                f"la DÉCLARATION de sensibilité {event.number} qualifie l'événement "
                f"{sensitivity.central}, qui n'est pas une DÉCLARATION centrale."
            )
        answer = self.events[sensitivity.answer - 1]
        if answer.kind is not EventKind.RESULT or answer.answers != sensitivity.central:
            raise ContractError(
                f"la DÉCLARATION de sensibilité {event.number} nomme l'événement "
                f"{sensitivity.answer}, qui n'est pas un RÉSULTAT de la déclaration "
                f"{sensitivity.central}."
            )

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
      ``(modèle, scores)`` : ``OutingScores`` pour v0 brut,
      ``CalibratedOutingScores`` pour un modèle calé (M4c-2), dont le candidat
      (M4c-3).
    - ``bands`` — sans unité — les fourchettes de la sortie (M4d-2) ; absentes sans
      usage, et pour une expérience.

    Invariants
    ----------
    - ``outing_id`` non vide ; ``scores`` est un tuple de couples (tuples) ;
    - ``scores`` non vide, de modèles distincts ;
    - un modèle de ``CALIBRATED_KINDS`` porte des ``CalibratedOutingScores``, de ce
      modèle (``control.model``) et de cette sortie ; v0 brut, des ``OutingScores``
      (M4c-2 ; le candidat est calé depuis M4c-3) ;
    - **la même observation** (``==``) pour tous les modèles (D7.1 : le support ne
      dépend que de l'observation) ;
    - ``bands`` présentes : de cette sortie (``outing_id``), et la sortie a l'usage.

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
    scores: tuple[tuple[ModelKind, OutingScores | CalibratedOutingScores], ...]
    bands: OutingBands | None = None

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
        for kind, scores in self.scores:
            self._check_scores_type(kind, scores)
        first_kind, first = self.scores[0]
        for kind, scores in self.scores[1:]:
            if scores.observation != first.observation:
                raise ContractError(
                    f"les scores de {kind} portent une autre observation que ceux de "
                    f"{first_kind} : le support ne dépend que de l'observation (D7.1)."
                )
        if self.bands is not None:
            if self.bands.outing_id != self.outing_id:
                raise ContractError(
                    f"les fourchettes portent la sortie {self.bands.outing_id!r}, "
                    f"{self.outing_id!r} attendue."
                )
            if first.usage is None:
                raise ContractError(
                    "des fourchettes demandent l'usage (0010 D11) : la sortie n'en a "
                    "pas."
                )

    def _check_scores_type(
        self, kind: ModelKind, scores: OutingScores | CalibratedOutingScores
    ) -> None:
        """Le type des scores d'un modèle (M4c-2) : calés pour un modèle calé, de ce
        modèle et de cette sortie ; non calés sinon."""
        if kind in CALIBRATED_KINDS:
            if not isinstance(scores, CalibratedOutingScores):
                raise ContractError(
                    f"{kind} est un modèle calé : ses scores sont des "
                    "CalibratedOutingScores."
                )
            if scores.control.model is not kind:
                raise ContractError(
                    f"les scores calés de {kind} portent le modèle "
                    f"{scores.control.model}."
                )
            if scores.outing_id != self.outing_id:
                raise ContractError(
                    f"les scores calés de {kind} portent la sortie "
                    f"{scores.outing_id!r}, {self.outing_id!r} attendue."
                )
        elif not isinstance(scores, OutingScores):
            raise ContractError(
                f"{kind} n'est pas un modèle calé : ses scores sont des OutingScores."
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
    - ``by_experiment`` — sans unité — les expériences, par couple effet × cible.
    - ``sensitivities`` — sans unité — les DÉCLARATIONS de sensibilité (M4d-3),
      comptées à part : elles ne sont pas des essais (exception de D14, M4d-3).

    Invariants
    ----------
    - ``by_experiment`` est un tuple ;
    - les quatre comptes ``>= 0`` ; ``corrections <= declarations`` ;
    - ``declarations == without_effect + Σ count + sensitivities`` ;
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
    Chaque DÉCLARATION compte pour un essai, corrections comprises, sauf une
    DÉCLARATION de sensibilité (exception de D14, M4d-3) : la règle ne peut que
    surestimer le nombre d'essais ; un ÉCHEC ne compte pas.
    """

    declarations: int
    corrections: int
    without_effect: int
    by_experiment: tuple[ExperimentTrials, ...]
    sensitivities: int = 0

    def __post_init__(self) -> None:
        require_immutable_sequence(self.by_experiment, "by_experiment")
        for name in ("declarations", "corrections", "without_effect", "sensitivities"):
            value: int = getattr(self, name)
            if value < 0:
                raise ContractError(f"{name} doit être >= 0, reçu {value}.")
        if self.corrections > self.declarations:
            raise ContractError(
                f"corrections ({self.corrections}) ne dépasse pas declarations "
                f"({self.declarations}) : une correction est une déclaration."
            )
        total = (
            self.without_effect
            + sum(t.count for t in self.by_experiment)
            + self.sensitivities
        )
        if self.declarations != total:
            raise ContractError(
                f"declarations ({self.declarations}) doit valoir without_effect + "
                f"Σ count + sensitivities ({total}) : chaque déclaration compte une "
                "fois."
            )
        keys = [(t.effect, _METRIC_ORDER.index(t.target)) for t in self.by_experiment]
        for previous, current in pairwise(keys):
            if not previous < current:
                raise ContractError(
                    "by_experiment est ordonné par effet puis par rang de la cible "
                    "dans ExperimentMetric, sans doublon, reçu "
                    f"{previous} puis {current}."
                )
