"""Contrats du backtest : sorties, artefacts, rétention, performance (M4a).

Protocole : ``docs/decisions/0010`` (D0, D2). Les instants sont *aware* et
**normalisés en UTC** : leurs consommateurs du M4 ne lisent que le calendrier de
Paris, recalculé depuis l'instant ; ``0006`` réserve le fuseau local à décalage fixe
aux instants dont un consommateur lit l'heure locale, ce qui n'est pas le cas ici.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, date, datetime
from enum import StrEnum
from types import MappingProxyType

from mountain_perf.schemas.common import SourceRef, Sport
from mountain_perf.schemas.reference import ReferencePerformance
from mountain_perf.validation import (
    ContractError,
    require_aware,
    require_finite,
    require_immutable_sequence,
    require_min_length,
    require_non_empty,
)

CUMULATIVE_TOLERANCE_S = 1e-6
"""Tolérance (secondes) entre un cumul d'écoulés et l'écoulé de sa dernière sortie.

Le cumul est une somme flottante ; il ne peut pas être plus petit que son dernier
terme, sauf d'un arrondi.
"""


class OutingLabel(StrEnum):
    """Étiquette course / entraînement d'une sortie (``0010`` D2.4).

    Champs
    ------
    Valeurs décrites dans ``OUTING_LABEL_DESCRIPTIONS``.

    Invariants
    ----------
    Énumération fermée. L'absence d'étiquette s'écrit ``None`` sur la sortie, et
    **ne vaut pas** entraînement.

    Producteur
    ----------
    Le manifeste (M4a), sortie par sortie.

    Consommateurs
    -------------
    ``Performance.all_training`` ; le calage (M4c), qui n'apprend que sur des
    performances d'entraînement.

    Non promis
    ----------
    Rien ne devine l'étiquette d'une sortie à partir de son nom, de sa date ou de son
    parcours.
    """

    RACE = "race"
    TRAINING = "training"


OUTING_LABEL_DESCRIPTIONS: Mapping[OutingLabel, str] = MappingProxyType(
    {
        OutingLabel.RACE: "Course : effort de compétition, exclu du calage.",
        OutingLabel.TRAINING: "Entraînement.",
    }
)


class DataSet(StrEnum):
    """Jeu auquel une sortie est déclarée appartenir (``0010`` D2.3).

    Champs
    ------
    Valeurs décrites dans ``DATA_SET_DESCRIPTIONS``.

    Invariants
    ----------
    Énumération fermée ; une sortie sans jeu déclaré porte ``None``.

    Producteur
    ----------
    Le manifeste (M4a).

    Consommateurs
    -------------
    La référence de répétabilité (M4b) et le rapport (M4b), qui sépare les agrégats
    par jeu.

    Non promis
    ----------
    Le jeu n'est pas recoupé avec les dates de la sortie ni avec la fenêtre de la
    courbe : il est déclaré, pas déduit.
    """

    REPEATABILITY = "repeatability"
    DEVELOPMENT = "development"
    CONFIRMATION = "confirmation"


DATA_SET_DESCRIPTIONS: Mapping[DataSet, str] = MappingProxyType(
    {
        DataSet.REPEATABILITY: (
            "Répétabilité : parcours répétés dans la fenêtre de la courbe ; scores "
            "« apprentissage »."
        ),
        DataSet.DEVELOPMENT: (
            "Développement : après la fenêtre, déjà regardées ; résultats indicatifs."
        ),
        DataSet.CONFIRMATION: (
            "Confirmation : origine postérieure au figement de la déclaration du "
            "candidat."
        ),
    }
)


class ReferenceKind(StrEnum):
    """Nature du tracé de référence d'une sortie (``0010`` D2.1, D2.6).

    Champs
    ------
    Valeurs décrites dans ``REFERENCE_KIND_DESCRIPTIONS``.

    Invariants
    ----------
    Énumération fermée.

    Producteur
    ----------
    Le manifeste (M4a).

    Consommateurs
    -------------
    Le choix du profil de domaine (M4a, orchestré en M4b) et l'appariement (M4a-2).

    Non promis
    ----------
    Rien ne vérifie qu'une trace de référence désignée a bien été désignée **avant**
    la sortie : c'est la date de disponibilité de l'artefact qui en répond.
    """

    PREPARED = "prepared"
    DESIGNATED_TRACE = "designated_trace"


REFERENCE_KIND_DESCRIPTIONS: Mapping[ReferenceKind, str] = MappingProxyType(
    {
        ReferenceKind.PREPARED: "Préparé : le tracé prévu avant la sortie.",
        ReferenceKind.DESIGNATED_TRACE: (
            "Trace de référence désignée à l'avance, faute de préparé."
        ),
    }
)


class ArtifactRole(StrEnum):
    """Rôle d'un artefact dans une évaluation (``0010`` D2.6).

    Champs
    ------
    Valeurs décrites dans ``ARTIFACT_ROLE_DESCRIPTIONS``.

    Invariants
    ----------
    Énumération fermée.

    Producteur
    ----------
    Le manifeste (M4a).

    Consommateurs
    -------------
    Le test de disponibilité à l'origine (M4c, confirmation), qui ne porte que sur
    les entrées de prévision.

    Non promis
    ----------
    Le rôle ne dit pas si l'artefact a effectivement servi à une prévision donnée.
    """

    FORECAST_INPUT = "forecast_input"
    EVALUATION_OBSERVATION = "evaluation_observation"


ARTIFACT_ROLE_DESCRIPTIONS: Mapping[ArtifactRole, str] = MappingProxyType(
    {
        ArtifactRole.FORECAST_INPUT: (
            "Entrée de prévision : courbe, préparé ou trace de référence, paramètres, "
            "historique de calage ; doit être disponible à l'origine."
        ),
        ArtifactRole.EVALUATION_OBSERVATION: (
            "Observation d'évaluation : trace réalisée, fin réelle ; postérieure par "
            "nature, jamais testée à l'origine."
        ),
    }
)


class Unavailability(StrEnum):
    """Statut d'une valeur non calculable (``0010`` D0).

    Champs
    ------
    Valeurs décrites dans ``UNAVAILABILITY_DESCRIPTIONS`` ; chaque description
    commence par le nom français du protocole.

    Invariants
    ----------
    Énumération fermée : les douze statuts de ``0010`` D0, ni plus ni moins.

    Producteur
    ----------
    Le backtest (M4a à M4d), là où une valeur ne peut pas être calculée.

    Consommateurs
    -------------
    Le rapport (M4b) et la règle d'admission (M4c).

    Non promis
    ----------
    Un statut ne vaut jamais zéro, ni « parfait », ni « échec sportif » ; un contrôle
    obligatoire indisponible ne vaut pas satisfaction. Aucun producteur n'existe en
    M4a-1 : le type est posé pour les lots suivants.
    """

    ABSENT = "absent"
    AMBIGUOUS = "ambiguous"
    UNDEFINED_TANGENT = "undefined_tangent"
    GAP = "gap"
    INTERIOR_DEVIATION = "interior_deviation"
    INSUFFICIENT_SUPPORT = "insufficient_support"
    ZERO_TIME = "zero_time"
    UNIDENTIFIED_REFERENCE = "unidentified_reference"
    NON_CONVERGENCE = "non_convergence"
    MODEL_ERROR = "model_error"
    NOT_CALIBRATED = "not_calibrated"
    MULTI_OUTING_DAY = "multi_outing_day"


UNAVAILABILITY_DESCRIPTIONS: Mapping[Unavailability, str] = MappingProxyType(
    {
        Unavailability.ABSENT: "absent — observation introuvable.",
        Unavailability.AMBIGUOUS: (
            "ambigu — plusieurs observations candidates, jamais départagées par "
            "l'erreur d'un modèle."
        ),
        Unavailability.UNDEFINED_TANGENT: (
            "tangente indéfinie — corde du profil trop courte pour orienter une "
            "normale."
        ),
        Unavailability.GAP: "trou — un trou d'enregistrement de plus de 10 s.",
        Unavailability.INTERIOR_DEVIATION: (
            "écart intérieur — la trace s'écarte du tracé à l'intérieur d'un segment."
        ),
        Unavailability.INSUFFICIENT_SUPPORT: (
            "support insuffisant — pas assez d'observations admises."
        ),
        Unavailability.ZERO_TIME: "temps nul — un temps observé nul sous une horloge.",
        Unavailability.UNIDENTIFIED_REFERENCE: (
            "référence non identifiée — gabarit de répétabilité non identifiable."
        ),
        Unavailability.NON_CONVERGENCE: (
            "non-convergence — limite d'itérations atteinte."
        ),
        Unavailability.MODEL_ERROR: (
            "erreur du modèle — sortie de modèle nulle, négative, non finie ou "
            "manquante."
        ),
        Unavailability.NOT_CALIBRATED: "non calé — population de calage vide.",
        Unavailability.MULTI_OUTING_DAY: (
            "jour multi-sorties — performance de plusieurs sorties, non évaluable."
        ),
    }
)


@dataclass(frozen=True)
class ArtifactRef:
    """Fichier utilisé par le backtest, avec son empreinte, sa disponibilité, son rôle.

    Champs
    ------
    - ``source`` — sans unité — nom du fichier et empreinte ``sha256``.
    - ``available_at`` — instant — moment à partir duquel l'artefact existait,
      *aware*, stocké en UTC.
    - ``role`` — sans unité — entrée de prévision ou observation d'évaluation.

    Invariants
    ----------
    ``available_at`` porte un fuseau ; il est normalisé en UTC à la construction.

    Producteur
    ----------
    Le manifeste (M4a) : pour une trace ou un doublon, ``available_at`` est la fin de
    la sortie ; pour une référence, l'instant déclaré.

    Consommateurs
    -------------
    ``Outing``, ``RouteReference`` ; le registre (M4b) ; le test de disponibilité à
    l'origine (M4c).

    Non promis
    ----------
    - ``available_at`` d'une observation d'évaluation n'est jamais testé à l'origine
      (``0010`` D2.6) ;
    - rien ne vérifie que le fichier existe encore, ni où il se trouve : ``source``
      ne porte qu'un nom de fichier (règle 1).
    """

    source: SourceRef
    available_at: datetime
    role: ArtifactRole

    def __post_init__(self) -> None:
        require_aware(self.available_at, "available_at")
        object.__setattr__(self, "available_at", self.available_at.astimezone(UTC))


@dataclass(frozen=True)
class RouteReference:
    """Tracé de référence d'une sortie : préparé ou trace désignée à l'avance.

    Champs
    ------
    - ``kind`` — sans unité — préparé ou trace de référence désignée.
    - ``artifact`` — sans unité — le fichier du tracé.

    Invariants
    ----------
    ``artifact.role`` vaut ``FORECAST_INPUT`` : un tracé de référence est une entrée
    de prévision.

    Producteur
    ----------
    Le manifeste (M4a).

    Consommateurs
    -------------
    Le profil de domaine (``0010`` D2.1) et l'appariement (M4a-2).

    Non promis
    ----------
    Le profil n'est pas construit ici ; le fichier n'est pas relu.
    """

    kind: ReferenceKind
    artifact: ArtifactRef

    def __post_init__(self) -> None:
        if self.artifact.role is not ArtifactRole.FORECAST_INPUT:
            raise ContractError(
                "artifact.role doit être FORECAST_INPUT (entrée de prévision), "
                f"reçu {self.artifact.role}."
            )


@dataclass(frozen=True)
class Outing:
    """Une sortie du manifeste, résolue : fichiers, instants, déclarations.

    Champs
    ------
    - ``outing_id`` — sans unité — identifiant stable de la sortie.
    - ``athlete_ref`` — sans unité — pseudonyme de l'athlète.
    - ``sport`` — sans unité — famille de modèle.
    - ``start_time``, ``end_time`` — instants — départ et fin, *aware*, stockés en
      UTC.
    - ``traces`` — sans unité — fichiers de la trace réalisée, dans l'ordre de
      concaténation ; vide pour une sortie non tracée.
    - ``duplicates`` — sans unité — autres enregistrements de la même sortie, hachés,
      jamais lus.
    - ``route_id``, ``variant`` — sans unité — parcours et variante déclarés.
    - ``declared_portion_m`` — mètres — portion déclarée ``(a, b)`` du parcours.
    - ``reference`` — sans unité — préparé ou trace de référence désignée.
    - ``dataset`` — sans unité — jeu déclaré.
    - ``label`` — sans unité — course ou entraînement ; ``None`` si absent.
    - ``external_records`` — sans unité — relevés externes de la sortie.

    Propriété calculée (jamais stockée) : ``elapsed_s``.

    Invariants
    ----------
    - ``outing_id`` et ``athlete_ref`` non vides ;
    - ``start_time`` et ``end_time`` portent un fuseau, sont normalisés en UTC, et
      ``start_time < end_time`` ;
    - ``traces``, ``duplicates`` et ``external_records`` sont des tuples ;
    - chaque trace et chaque doublon a le rôle ``EVALUATION_OBSERVATION`` ;
    - ``duplicates`` non vide ⇒ ``traces`` non vide ;
    - ``route_id`` et ``variant`` sont ``None`` ou non vides ;
    - ``declared_portion_m`` est ``None`` ou un tuple ``(a, b)`` fini avec
      ``0 <= a < b`` ;
    - chaque relevé externe porte l'``athlete_ref`` de la sortie.

    Producteur
    ----------
    Le manifeste (M4a).

    Consommateurs
    -------------
    La rétention, le domaine et les performances (M4a) ; l'appariement (M4a-2) ; le
    calage (M4c).

    Non promis
    ----------
    - pour une sortie tracée, ``start_time`` et ``end_time`` sont les instants du
      premier et du dernier enregistrement, pas ceux d'une montre ;
    - l'heure locale n'est pas conservée (un effet qui en aurait besoin, au M7, la
      lira sur l'``Activity`` du M6b) ;
    - le jour civil, le rang, la rétention et le domaine ne sont pas stockés : ils se
      dérivent ;
    - ``outing_id`` n'est unique que dans un manifeste, et c'est le lecteur qui le
      vérifie, pas le type ;
    - ``dataset`` n'est pas recoupé avec les dates ; ``declared_portion_m`` n'est pas
      recoupé avec la longueur d'un profil.
    """

    outing_id: str
    athlete_ref: str
    sport: Sport
    start_time: datetime
    end_time: datetime
    traces: tuple[ArtifactRef, ...] = ()
    duplicates: tuple[ArtifactRef, ...] = ()
    route_id: str | None = None
    variant: str | None = None
    declared_portion_m: tuple[float, float] | None = None
    reference: RouteReference | None = None
    dataset: DataSet | None = None
    label: OutingLabel | None = None
    external_records: tuple[ReferencePerformance, ...] = ()

    def __post_init__(self) -> None:
        require_non_empty(self.outing_id, "outing_id")
        require_non_empty(self.athlete_ref, "athlete_ref")
        for name in ("start_time", "end_time"):
            instant: datetime = getattr(self, name)
            require_aware(instant, name)
            object.__setattr__(self, name, instant.astimezone(UTC))
        if self.start_time >= self.end_time:
            raise ContractError(
                f"start_time ({self.start_time}) doit précéder "
                f"end_time ({self.end_time})."
            )
        for name in ("traces", "duplicates"):
            artifacts: tuple[ArtifactRef, ...] = getattr(self, name)
            require_immutable_sequence(artifacts, name)
            for i, artifact in enumerate(artifacts):
                if artifact.role is not ArtifactRole.EVALUATION_OBSERVATION:
                    raise ContractError(
                        f"{name}[{i}].role doit être EVALUATION_OBSERVATION, "
                        f"reçu {artifact.role}."
                    )
        if self.duplicates and not self.traces:
            raise ContractError(
                "duplicates non vide exige des traces : un doublon double une trace."
            )
        for name in ("route_id", "variant"):
            text: str | None = getattr(self, name)
            if text is not None:
                require_non_empty(text, name)
        if self.declared_portion_m is not None:
            portion = self.declared_portion_m
            require_immutable_sequence(portion, "declared_portion_m")
            if len(portion) != 2:
                raise ContractError(
                    f"declared_portion_m doit être un couple (a, b), reçu {portion}."
                )
            require_finite(portion[0], "declared_portion_m[0]")
            require_finite(portion[1], "declared_portion_m[1]")
            if not 0 <= portion[0] < portion[1]:
                raise ContractError(
                    f"declared_portion_m doit vérifier 0 <= a < b, reçu {portion}."
                )
        require_immutable_sequence(self.external_records, "external_records")
        for i, record in enumerate(self.external_records):
            if record.athlete_ref != self.athlete_ref:
                raise ContractError(
                    f"external_records[{i}].athlete_ref doit être celui de la sortie."
                )

    @property
    def elapsed_s(self) -> float:
        """Durée écoulée de la sortie (secondes) : ``end_time − start_time``."""
        return (self.end_time - self.start_time).total_seconds()


@dataclass(frozen=True)
class RetentionDecision:
    """Décision de rétention d'une sortie dans son jour civil (``0010`` D0).

    Champs
    ------
    - ``outing`` — sans unité — la sortie.
    - ``civil_date`` — date civile — jour civil de son départ, à Paris.
    - ``rank`` — sans unité — rang dans le jour, à partir de 1.
    - ``cumulative_elapsed_s`` — secondes — somme des écoulés des sorties du jour
      jusqu'à celle-ci incluse, tous sports confondus.
    - ``retained`` — sans unité — la sortie est-elle retenue.

    Invariants
    ----------
    - ``rank >= 1`` ;
    - ``cumulative_elapsed_s`` fini et ``>= outing.elapsed_s`` (à ``1e−6`` s près).

    Producteur
    ----------
    ``retain_outings`` (``mountain_perf.backtest.outings``).

    Consommateurs
    -------------
    Le regroupement en performances (M4a) ; le rapport (M4b), qui publie les sorties
    non retenues en diagnostic.

    Non promis
    ----------
    - la règle de rétention elle-même (la fonction la porte) : ``retained`` n'est pas
      recoupé avec ``rank`` et le cumul ;
    - le jour civil n'est pas recoupé avec le départ ;
    - le domaine n'est pas évalué ici.
    """

    outing: Outing
    civil_date: date
    rank: int
    cumulative_elapsed_s: float
    retained: bool

    def __post_init__(self) -> None:
        if self.rank < 1:
            raise ContractError(f"rank doit être >= 1, reçu {self.rank}.")
        require_finite(self.cumulative_elapsed_s, "cumulative_elapsed_s")
        if self.cumulative_elapsed_s < self.outing.elapsed_s - CUMULATIVE_TOLERANCE_S:
            raise ContractError(
                f"cumulative_elapsed_s ({self.cumulative_elapsed_s}) doit être >= "
                f"l'écoulé de la sortie ({self.outing.elapsed_s})."
            )


@dataclass(frozen=True)
class Performance:
    """Les sorties retenues et dans le domaine d'un même jour civil (``0010`` D0).

    Unité statistique de toutes les décisions du backtest : plis, moyennes, votes,
    calage.

    Champs
    ------
    - ``civil_date`` — date civile — le jour, à Paris.
    - ``outings`` — sans unité — les sorties, dans l'ordre de leur rang.

    Propriétés calculées (jamais stockées) : ``athlete_ref``, ``is_multi_outing``,
    ``all_training``, ``end_time``.

    Invariants
    ----------
    - ``outings`` est un tuple d'au moins une sortie ;
    - identifiants distincts ;
    - même ``athlete_ref`` pour toutes les sorties ;
    - ordre strictement croissant de ``(start_time, outing_id)``.

    Producteur
    ----------
    ``group_performances`` (``mountain_perf.backtest.outings``).

    Consommateurs
    -------------
    La référence de répétabilité (M4b), le calage et l'admission (M4c).

    Non promis
    ----------
    - le jour civil n'est pas recoupé avec les instants par le type (il faut un
      fuseau : c'est le regroupement qui le garantit) ;
    - la rétention et le domaine ne sont pas revérifiés ;
    - le jeu déclaré n'est pas agrégé ;
    - une performance de plusieurs sorties est « jour multi-sorties » : le type la
      représente, il ne dit pas comment l'évaluer.
    """

    civil_date: date
    outings: tuple[Outing, ...]

    def __post_init__(self) -> None:
        require_immutable_sequence(self.outings, "outings")
        require_min_length(self.outings, 1, "outings")
        ids = [outing.outing_id for outing in self.outings]
        if len(set(ids)) != len(ids):
            raise ContractError("outings doit porter des identifiants distincts.")
        if len({outing.athlete_ref for outing in self.outings}) > 1:
            raise ContractError("outings doit porter un seul athlete_ref.")
        keys = [(outing.start_time, outing.outing_id) for outing in self.outings]
        for i in range(1, len(keys)):
            if not keys[i - 1] < keys[i]:
                raise ContractError(
                    "outings doit être ordonné par (start_time, outing_id) : "
                    f"outings[{i - 1}] ne précède pas outings[{i}]."
                )

    @property
    def athlete_ref(self) -> str:
        """Pseudonyme de l'athlète, commun à toutes les sorties."""
        return self.outings[0].athlete_ref

    @property
    def is_multi_outing(self) -> bool:
        """Vrai si la performance compte plus d'une sortie (« jour multi-sorties »)."""
        return len(self.outings) > 1

    @property
    def all_training(self) -> bool:
        """Vrai si toutes les sorties sont étiquetées entraînement (``0010`` D2.4).

        Une étiquette ``None`` la rend fausse : une étiquette manquante ne vaut pas
        entraînement. Consommée par le calage (M4c).
        """
        return all(outing.label is OutingLabel.TRAINING for outing in self.outings)

    @property
    def end_time(self) -> datetime:
        """Instant de fin le plus tardif des sorties (la performance est terminée)."""
        return max(outing.end_time for outing in self.outings)
