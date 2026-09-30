"""Contrats des scores d'un modèle sur une sortie : observation, prévision, scores
(M4b-2).

Protocole : ``docs/decisions/0010`` D3, D4.2, D4.8, D4.11, D4.12, D5.3 à D5.5, D7.
Trois étages (décision 1 de rdw, Q2) :

- l'**observation** d'une sortie, indépendante de tout modèle (D7.1 : le support est
  déterminé par l'observation seule) — segments admis et leurs temps sous les onze
  horloges, points de ``C_k``, éléments de ``K`` ;
- la **prévision** d'un modèle dans un scénario (D3) — projections de segment,
  cumulés aux points et aux éléments de ``K`` ;
- les **scores** par scénario et par horloge, qui portent les résultats des fonctions
  de M4b-1, et les enveloppes de D5.4.

Aucun calcul ici : les producteurs vivent dans ``mountain_perf.backtest.scoring``.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from itertools import pairwise
from types import MappingProxyType

from mountain_perf.schemas.clock import CLOCKS, Clock
from mountain_perf.schemas.common import SourceRef
from mountain_perf.schemas.matching import RegimeClass
from mountain_perf.schemas.metrics import (
    LogRatioEnvelope,
    PassageErrors,
    PositiveTimeDiagnostic,
    SupportMetrics,
    TargetMember,
    UsageTarget,
)
from mountain_perf.schemas.outing import Unavailability
from mountain_perf.schemas.parameters import ParameterSet
from mountain_perf.validation import (
    ContractError,
    require_all_finite,
    require_aware,
    require_finite,
    require_immutable_sequence,
    require_non_empty,
)


class Scenario(StrEnum):
    """Scénario d'une prévision (``0010`` D3).

    Champs
    ------
    Valeurs décrites dans ``SCENARIO_DESCRIPTIONS``.

    Invariants
    ----------
    Énumération fermée : usage ou contrôle.

    Producteur
    ----------
    ``usage_forecast`` et ``control_forecast`` (``mountain_perf.backtest.scoring``).

    Consommateurs
    -------------
    ``ModelForecast``, ``ScenarioScores``, ``OutingScores`` ; ``mperf match`` ; le
    rapport (M4b-5).

    Non promis
    ----------
    L'écart de scores entre les deux scénarios n'isole pas causalement une cause
    (D3) ; le diagnostic de géométrie (usage − contrôle) n'est pas calculé ici.
    """

    USAGE = "usage"
    CONTROL = "control"


SCENARIO_DESCRIPTIONS: Mapping[Scenario, str] = MappingProxyType(
    {
        Scenario.USAGE: (
            "Usage : projection sur le profil de référence (préparé ou trace de "
            "référence désignée), comparée à la trace réalisée (D3)."
        ),
        Scenario.CONTROL: (
            "Contrôle : projection sur le profil de la trace réalisée elle-même, "
            "rétrospective, non disponible à J−7 (D3)."
        ),
    }
)

OBSERVATION_UNAVAILABILITY: frozenset[Unavailability] = frozenset(
    {
        Unavailability.ABSENT,
        Unavailability.AMBIGUOUS,
        Unavailability.UNDEFINED_TANGENT,
        Unavailability.INSUFFICIENT_SUPPORT,
    }
)
"""Les motifs qu'une observation de M4a-3 peut porter : ceux de
``PASSAGE_STATUS_UNAVAILABILITY``, plus ``support insuffisant`` (hors préfixe, non
maintenue, arrivée hors du préfixe). Jamais ``model_error`` ni ``zero_time``, qui sont
des motifs de métrique."""


def _require_clock_times(times_s: tuple[float, ...], name: str) -> None:
    """Un temps par horloge de ``CLOCKS``, fini et ``>= 0``."""
    require_immutable_sequence(times_s, name)
    if len(times_s) != len(CLOCKS):
        raise ContractError(
            f"{name} porte un temps par horloge ({len(CLOCKS)}), reçu {len(times_s)}."
        )
    require_all_finite(times_s, name)
    for i, time_s in enumerate(times_s):
        if time_s < 0:
            raise ContractError(f"{name}[{i}] doit être >= 0, reçu {time_s}.")


@dataclass(frozen=True)
class AdmittedSegment:
    """Un segment admis de la sortie et ses temps sous les onze horloges (``0010``
    D4.2, D5.3, D5.4, D7.1).

    Champs
    ------
    - ``index`` — sans unité — ``k``, rang du segment dans la grille de score.
    - ``nominal_start_m``, ``nominal_end_m`` — mètres — ``s_k``, ``s_{k+1}``, bornes
      nominales.
    - ``start_m``, ``end_m`` — mètres — ``b_k``, ``b_{k+1}``, bornes effectives
      (D4.2).
    - ``realized_start_m``, ``realized_end_m`` — mètres — ``d_r(π_k)``,
      ``d_r(π_{k+1})``, abscisses réalisées des bornes (D3).
    - ``regime_class`` — sans unité — la classe du segment, celle de la référence
      (partition commune, D3).
    - ``times_s`` — secondes — le temps du segment sous chacune des onze horloges,
      dans l'ordre de ``CLOCKS``.

    Invariants
    ----------
    - ``index >= 0`` ; les six abscisses finies et ``>= 0`` ;
      ``nominal_start_m < nominal_end_m`` ; ``start_m < end_m`` ;
      ``realized_start_m <= realized_end_m`` ;
    - ``regime_class`` est une ``RegimeClass`` ;
    - ``times_s`` est un tuple de ``len(CLOCKS)`` valeurs finies et ``>= 0`` ;
    - ``times_s[0] > 0`` (l'écoulé d'un segment admis : ``t*_k < t*_{k+1}``).

    Producteur
    ----------
    ``observe_outing`` (``mountain_perf.backtest.scoring``).

    Consommateurs
    -------------
    ``score_scenario`` ; la référence D8 (M4b-3 : un segment est identifié par ses
    bornes, et un segment de bord ancré n'est pas la cellule nominale, D4.2) ; le
    rapport (M4b-5) ; les baselines (M4c).

    Non promis
    ----------
    - ``M_θ <= (M + U)_θ <= E`` n'est vrai qu'en réels et n'est pas vérifié ;
    - les temps ne sont pas recoupés avec une partition ;
    - le contrat ne dit pas quelles bornes effectives diffèrent des nominales (celles
      d'un bord ancré, par le producteur).
    """

    index: int
    nominal_start_m: float
    nominal_end_m: float
    start_m: float
    end_m: float
    realized_start_m: float
    realized_end_m: float
    regime_class: RegimeClass
    times_s: tuple[float, ...]

    def __post_init__(self) -> None:
        if self.index < 0:
            raise ContractError(f"index doit être >= 0, reçu {self.index}.")
        for name in (
            "nominal_start_m",
            "nominal_end_m",
            "start_m",
            "end_m",
            "realized_start_m",
            "realized_end_m",
        ):
            value: float = getattr(self, name)
            require_finite(value, name)
            if value < 0:
                raise ContractError(f"{name} doit être >= 0, reçu {value}.")
        if not self.nominal_start_m < self.nominal_end_m:
            raise ContractError(
                f"nominal_start_m ({self.nominal_start_m}) doit être < nominal_end_m "
                f"({self.nominal_end_m})."
            )
        if not self.start_m < self.end_m:
            raise ContractError(
                f"start_m ({self.start_m}) doit être < end_m ({self.end_m})."
            )
        if not self.realized_start_m <= self.realized_end_m:
            raise ContractError(
                f"realized_start_m ({self.realized_start_m}) doit être <= "
                f"realized_end_m ({self.realized_end_m})."
            )
        if not isinstance(self.regime_class, RegimeClass):
            raise ContractError(
                f"regime_class doit être une RegimeClass, reçu {self.regime_class!r}."
            )
        _require_clock_times(self.times_s, "times_s")
        if not self.times_s[0] > 0:
            raise ContractError(
                "l'écoulé d'un segment admis est > 0 (t*_k < t*_{k+1}), reçu "
                f"{self.times_s[0]}."
            )


@dataclass(frozen=True)
class ObservedPoint:
    """Un point de ``C_k``, ou un élément de ``K``, observé sur la sortie (``0010``
    D4.12, D7.3, D7.4).

    Champs
    ------
    - ``distance_m`` — mètres — l'abscisse où le cumul projeté est lu : ``b_k`` d'un
      point de score, ``s_w`` d'un lieu, ``b_K`` de l'arrivée.
    - ``score_index`` — sans unité — ``k`` d'un point de score (et de l'arrivée).
    - ``passage_index`` — sans unité — rang du lieu dans
      ``PassageMatchResult.passages``.
    - ``unavailability`` — sans unité — le motif d'observation (``0010`` D0).
    - ``times_s`` — secondes — ``T_k``, cumulé depuis ``t*_0`` sous chacune des onze
      horloges, dans l'ordre de ``CLOCKS``.

    Propriété calculée (jamais stockée) : ``available``.

    Invariants
    ----------
    - ``distance_m`` finie et ``>= 0`` ;
    - au moins un des deux indices est présent ; présents, ils sont ``>= 0`` ;
    - ``times_s`` présent **si et seulement si** ``unavailability`` est absent ;
    - ``unavailability`` absent ou dans ``OBSERVATION_UNAVAILABILITY`` (jamais
      ``model_error``, ``zero_time``…) ;
    - ``times_s`` présent : tuple de ``len(CLOCKS)`` valeurs finies et ``>= 0``.

    Producteur
    ----------
    ``observe_outing`` (``mountain_perf.backtest.scoring``).

    Consommateurs
    -------------
    ``score_scenario`` ; le rapport (``mperf match``, M4b-5).

    Non promis
    ----------
    - le nom du lieu n'est pas porté : l'appelant a les passages ;
    - un ``T_k`` peut être nul sous une horloge (``comparable`` le dira, M4b-1).
    """

    distance_m: float
    score_index: int | None
    passage_index: int | None
    unavailability: Unavailability | None
    times_s: tuple[float, ...] | None

    def __post_init__(self) -> None:
        require_finite(self.distance_m, "distance_m")
        if self.distance_m < 0:
            raise ContractError(f"distance_m doit être >= 0, reçu {self.distance_m}.")
        if self.score_index is None and self.passage_index is None:
            raise ContractError(
                "au moins un de score_index et passage_index doit être présent."
            )
        for name in ("score_index", "passage_index"):
            index: int | None = getattr(self, name)
            if index is not None and index < 0:
                raise ContractError(f"{name} doit être >= 0, reçu {index}.")
        if (self.times_s is None) == (self.unavailability is None):
            raise ContractError(
                "times_s est présent si et seulement si unavailability est absent, "
                f"reçu times_s={self.times_s}, unavailability={self.unavailability}."
            )
        motif = self.unavailability
        if motif is not None and motif not in OBSERVATION_UNAVAILABILITY:
            raise ContractError(f"motif d'observation hors de la liste : {motif}.")
        if self.times_s is not None:
            _require_clock_times(self.times_s, "times_s")

    @property
    def available(self) -> bool:
        """Le point est observé : ``unavailability is None``."""
        return self.unavailability is None


@dataclass(frozen=True)
class OutingObservation:
    """Ce qu'une sortie observe, indépendamment de tout modèle (``0010`` D4.8, D4.11,
    D4.12, D5.3, D5.4, D7.1, D7.3, D7.4).

    Champs
    ------
    - ``reference_length_m`` — mètres — ``L``, longueur du tracé de référence.
    - ``origin_m`` — mètres — ``b_0``, origine des cumulés.
    - ``origin_s`` — secondes depuis le premier enregistrement — ``t*_0`` ; absent si
      le départ n'est pas daté.
    - ``segments`` — sans unité — les segments admis, dans l'ordre.
    - ``error_points`` — sans unité — les points de ``C_k`` (D7.3) : points de score
      du préfixe et lieux intermédiaires, origine exclue, par abscisse croissante.
    - ``members`` — sans unité — ``K`` par défaut (``default_targets``, D7.4).
    - ``targets`` — sans unité — un élément observé par membre, dans le même ordre.
    - ``arrival_anchor_gap_m`` — mètres — ``L − b_K`` d'une arrivée ancrée (D4.8).

    Invariants
    ----------
    - ``L`` finie et ``> 0`` ; ``0 <= b_0 < L`` ; ``origin_s`` absent, ou fini et
      ``>= 0`` ;
    - ``segments``, ``error_points``, ``members``, ``targets`` sont des tuples ;
    - ``segments`` : ``index`` strictement croissants ; ``b_0 <= start_m`` et
      ``end_m <= L`` ;
    - ``error_points`` : exactement un des deux indices ; ``score_index >= 1``
      (origine exclue) ; ``distance_m`` non décroissantes, dans ``[b_0 ; L]`` ;
    - ``members`` et ``targets`` : même longueur, ``>= 1`` ; le dernier membre est
      ``arrival``, et lui seul ; pour un membre intermédiaire,
      ``targets[i].passage_index == members[i].occurrence_index`` et ``score_index``
      absent ; pour l'arrivée, ``score_index`` présent et
      ``passage_index == occurrence_index`` ;
    - ``origin_s`` absent ⇒ ``error_points`` vide et aucun élément de ``targets``
      disponible ;
    - ``arrival_anchor_gap_m`` absent, ou fini et ``>= 0``.

    Producteur
    ----------
    ``observe_outing`` (``mountain_perf.backtest.scoring``).

    Consommateurs
    -------------
    Les prévisions et ``score_scenario`` ; la référence D8 (M4b-3) ; le rapport
    (M4b-5) ; les baselines (M4c).

    Non promis
    ----------
    Le contrat ne vérifie pas que ``score_index`` de l'arrivée vaut ``K``, ni les
    temps contre une partition, ni que les points sont ceux du préfixe : ce sont les
    tests du producteur.
    """

    reference_length_m: float
    origin_m: float
    origin_s: float | None
    segments: tuple[AdmittedSegment, ...]
    error_points: tuple[ObservedPoint, ...]
    members: tuple[TargetMember, ...]
    targets: tuple[ObservedPoint, ...]
    arrival_anchor_gap_m: float | None

    def __post_init__(self) -> None:
        self._check_origin()
        for name in ("segments", "error_points", "members", "targets"):
            require_immutable_sequence(getattr(self, name), name)
        self._check_segments()
        self._check_error_points()
        self._check_targets()
        self._check_arrival_last()
        if self.origin_s is None:
            self._check_undated_origin()
        gap_m = self.arrival_anchor_gap_m
        if gap_m is not None:
            require_finite(gap_m, "arrival_anchor_gap_m")
            if gap_m < 0:
                raise ContractError(
                    f"arrival_anchor_gap_m doit être >= 0, reçu {gap_m}."
                )

    def _check_origin(self) -> None:
        length_m, origin_m = self.reference_length_m, self.origin_m
        require_finite(length_m, "reference_length_m")
        if length_m <= 0:
            raise ContractError(f"reference_length_m doit être > 0, reçu {length_m}.")
        require_finite(origin_m, "origin_m")
        if not 0 <= origin_m < length_m:
            raise ContractError(
                f"origin_m doit être dans [0 ; {length_m}[, reçu {origin_m}."
            )
        if self.origin_s is not None:
            require_finite(self.origin_s, "origin_s")
            if self.origin_s < 0:
                raise ContractError(f"origin_s doit être >= 0, reçu {self.origin_s}.")

    def _check_segments(self) -> None:
        for previous, current in pairwise(self.segments):
            if not previous.index < current.index:
                raise ContractError(
                    "les index des segments sont strictement croissants, reçu "
                    f"{previous.index} puis {current.index}."
                )
        for segment in self.segments:
            if not (
                self.origin_m <= segment.start_m
                and segment.end_m <= self.reference_length_m
            ):
                raise ContractError(
                    f"le segment {segment.index} ([{segment.start_m} ; "
                    f"{segment.end_m}]) doit être dans [b_0 ; L] = [{self.origin_m} ; "
                    f"{self.reference_length_m}]."
                )

    def _check_error_points(self) -> None:
        for k, point in enumerate(self.error_points):
            if (point.score_index is None) == (point.passage_index is None):
                raise ContractError(
                    f"error_points[{k}] porte exactement un de score_index et "
                    "passage_index."
                )
            if point.score_index is not None and point.score_index < 1:
                raise ContractError(
                    f"error_points[{k}] : l'origine est exclue (score_index >= 1), "
                    f"reçu {point.score_index}."
                )
        for k, point in enumerate(self.error_points):
            if not self.origin_m <= point.distance_m <= self.reference_length_m:
                raise ContractError(
                    f"error_points[{k}].distance_m ({point.distance_m}) doit être "
                    f"dans [b_0 ; L] = [{self.origin_m} ; {self.reference_length_m}]."
                )
        distances_m = [point.distance_m for point in self.error_points]
        for k in range(1, len(distances_m)):
            if distances_m[k] < distances_m[k - 1]:
                raise ContractError(
                    "les points de C_k sont par abscisse non décroissante, reçu "
                    f"{distances_m[k - 1]} puis {distances_m[k]}."
                )

    def _check_targets(self) -> None:
        if len(self.members) != len(self.targets):
            raise ContractError(
                f"members ({len(self.members)}) et targets ({len(self.targets)}) ont "
                "la même longueur."
            )
        if not self.members:
            raise ContractError("K n'est jamais vide : il porte au moins l'arrivée.")
        for i, (member, target) in enumerate(
            zip(self.members, self.targets, strict=True)
        ):
            if target.passage_index != member.occurrence_index:
                raise ContractError(
                    f"targets[{i}].passage_index ({target.passage_index}) doit valoir "
                    f"members[{i}].occurrence_index ({member.occurrence_index})."
                )
            if (target.score_index is not None) != member.arrival:
                raise ContractError(
                    f"targets[{i}] : score_index présent si et seulement si l'élément "
                    "est l'arrivée."
                )

    def _check_arrival_last(self) -> None:
        arrivals = [i for i, member in enumerate(self.members) if member.arrival]
        if arrivals != [len(self.members) - 1]:
            raise ContractError(
                "le dernier membre de K est l'arrivée, et lui seul, reçu l'arrivée "
                f"aux rangs {arrivals} sur {len(self.members)}."
            )

    def _check_undated_origin(self) -> None:
        if self.error_points:
            raise ContractError("départ non daté : aucun point de C_k.")
        if any(target.available for target in self.targets):
            raise ContractError("départ non daté : aucun élément de K disponible.")


@dataclass(frozen=True)
class ModelForecast:
    """La prévision d'un modèle dans un scénario (``0010`` D3, D7.1 ; décision 1 de
    rdw).

    Champs
    ------
    - ``scenario`` — sans unité — usage ou contrôle.
    - ``source`` — sans unité — le tracé du profil projeté : la référence en usage, la
      trace en contrôle.
    - ``curve_ref`` — sans unité — la référence de la courbe.
    - ``parameters`` — sans unité — les paramètres du modèle.
    - ``engine_version`` — sans unité — la version du moteur.
    - ``generated_at`` — date — l'instant de la prévision, avec fuseau.
    - ``segment_s`` — secondes — ``p_i``, une projection par segment admis.
    - ``point_s`` — secondes — ``P_k``, un cumulé par point de ``C_k`` (usage).
    - ``target_s`` — secondes — ``P_k``, un cumulé par élément de ``K`` (usage).

    Invariants
    ----------
    - ``curve_ref`` et ``engine_version`` non vides ; ``generated_at`` avec fuseau ;
    - ``segment_s``, ``point_s``, ``target_s`` sont des tuples ;
    - ``scenario == CONTROL`` ⇒ ``point_s`` et ``target_s`` vides.

    Producteur
    ----------
    ``usage_forecast`` et ``control_forecast`` (``mountain_perf.backtest.scoring``).

    Consommateurs
    -------------
    ``score_scenario`` ; la prévision conservée (M4b-4) ; les baselines (M4c).

    Non promis
    ----------
    - **les valeurs ne sont pas validées** : ce sont des sorties de modèle, jugées
      par D7.1 dans les scores (``None``, non finies ou ``<= 0`` y deviennent
      « erreur du modèle ») ;
    - les longueurs ne sont pas recoupées avec une observation : ce sont les
      préconditions de ``score_scenario``.
    """

    scenario: Scenario
    source: SourceRef
    curve_ref: str
    parameters: ParameterSet
    engine_version: str
    generated_at: datetime
    segment_s: tuple[float | None, ...]
    point_s: tuple[float | None, ...]
    target_s: tuple[float | None, ...]

    def __post_init__(self) -> None:
        require_non_empty(self.curve_ref, "curve_ref")
        require_non_empty(self.engine_version, "engine_version")
        require_aware(self.generated_at, "generated_at")
        for name in ("segment_s", "point_s", "target_s"):
            require_immutable_sequence(getattr(self, name), name)
        if self.scenario is Scenario.CONTROL:
            self._check_control_without_points()

    def _check_control_without_points(self) -> None:
        if self.point_s or self.target_s:
            raise ContractError(
                "une prévision de contrôle n'a ni point de C_k ni élément de K (C_k "
                "et q_usage en usage seulement)."
            )


@dataclass(frozen=True)
class ClockScores:
    """Les scores d'un scénario sous une horloge (``0010`` D5.5, D7).

    Champs
    ------
    - ``clock`` — sans unité — l'horloge des temps observés.
    - ``support`` — sans unité — les métriques du support (D7.1, D7.2).
    - ``diagnostic`` — sans unité — le sous-support à temps positifs (D5.5), quand le
      support a un temps nul.
    - ``passage_errors`` — sans unité — les erreurs aux passages ``C_k`` (D7.3), en
      usage.
    - ``usage_target`` — sans unité — la cible d'usage ``q_usage`` (D7.4), en usage.

    Invariants
    ----------
    - ``diagnostic`` présent **si et seulement si**
      ``support.dispersion.unavailability is ZERO_TIME`` ; présent,
      ``len(diagnostic.mask) == support.segment_count`` ;
    - ``passage_errors`` et ``usage_target`` tous deux présents ou tous deux absents.

    Producteur
    ----------
    ``score_scenario`` (``mountain_perf.backtest.scoring``).

    Consommateurs
    -------------
    ``ScenarioScores`` ; le rapport (``mperf match``, M4b-5).

    Non promis
    ----------
    Le contrat ne recalcule pas les objets de M4b-1 et ne les recoupe pas avec
    l'observation.
    """

    clock: Clock
    support: SupportMetrics
    diagnostic: PositiveTimeDiagnostic | None
    passage_errors: PassageErrors | None
    usage_target: UsageTarget | None

    def __post_init__(self) -> None:
        self._check_diagnostic()
        if (self.passage_errors is None) != (self.usage_target is None):
            raise ContractError(
                "passage_errors et usage_target sont tous deux présents (usage) ou "
                "tous deux absents (contrôle)."
            )

    def _check_diagnostic(self) -> None:
        zero_time = self.support.dispersion.unavailability is Unavailability.ZERO_TIME
        if (self.diagnostic is not None) != zero_time:
            raise ContractError(
                "diagnostic présent si et seulement si le motif vectoriel du support "
                f"est zero_time (D5.5), reçu {self.support.dispersion.unavailability}."
            )
        if (
            self.diagnostic is not None
            and len(self.diagnostic.mask) != self.support.segment_count
        ):
            raise ContractError(
                f"le masque du diagnostic ({len(self.diagnostic.mask)}) porte un "
                f"booléen par segment du support ({self.support.segment_count})."
            )


@dataclass(frozen=True)
class ScenarioScores:
    """Les scores d'un scénario sous les onze horloges, et ses enveloppes (``0010``
    D5.4, D7).

    Champs
    ------
    - ``scenario`` — sans unité — usage ou contrôle.
    - ``forecast`` — sans unité — la prévision scorée.
    - ``envelope`` — sans unité — l'enveloppe de ``L`` du support (D5.4).
    - ``class_envelopes`` — sans unité — l'enveloppe de ``E_R`` de chaque classe, dans
      l'ordre de ``RegimeClass`` (montée, plat, descente, mixte).
    - ``clocks`` — sans unité — les scores sous chaque horloge, dans l'ordre de
      ``CLOCKS``.

    Invariants
    ----------
    - ``forecast.scenario == scenario`` ; ``class_envelopes`` et ``clocks`` sont des
      tuples ;
    - ``tuple(c.clock for c in clocks) == CLOCKS`` ;
    - sous toutes les horloges, le même ``support.segment_count``, égal à
      ``len(forecast.segment_s)``, les mêmes effectifs de classe et le même
      ``support.model_error`` ;
    - ``passage_errors`` présent sous chaque horloge **si et seulement si**
      ``scenario == USAGE`` ; en usage, ``len(errors_s) == len(forecast.point_s)`` et
      ``len(usage_target.comparable) == len(forecast.target_s)`` ;
    - ``envelope`` absente **si et seulement si** ``segment_count == 0`` ;
      ``class_envelopes`` a quatre éléments, chacun absent si et seulement si
      l'effectif de sa classe est nul ;
    - une enveloppe présente de motif ``model_error`` ⇒ ``support.model_error`` ;
      ``support.model_error`` ⇒ toute enveloppe présente a un motif.

    Producteur
    ----------
    ``score_scenario`` (``mountain_perf.backtest.scoring``).

    Consommateurs
    -------------
    ``OutingScores`` ; le rapport (``mperf match``, M4b-5) ; les baselines (M4c).

    Non promis
    ----------
    Les enveloppes ne sont pas recalculées par le contrat ; elles valent à ``P``
    fixé (D5.4).
    """

    scenario: Scenario
    forecast: ModelForecast
    envelope: LogRatioEnvelope | None
    class_envelopes: tuple[LogRatioEnvelope | None, ...]
    clocks: tuple[ClockScores, ...]

    def __post_init__(self) -> None:
        if self.forecast.scenario is not self.scenario:
            raise ContractError(
                f"forecast.scenario ({self.forecast.scenario}) doit valoir scenario "
                f"({self.scenario})."
            )
        require_immutable_sequence(self.class_envelopes, "class_envelopes")
        require_immutable_sequence(self.clocks, "clocks")
        self._check_clock_order()
        self._check_supports()
        self._check_passages()
        self._check_envelope_presence()
        self._check_class_envelopes()
        self._check_envelope_motifs()

    def _check_clock_order(self) -> None:
        if tuple(scores.clock for scores in self.clocks) != CLOCKS:
            raise ContractError(
                "clocks porte les onze horloges dans l'ordre de CLOCKS, reçu "
                f"{[scores.clock for scores in self.clocks]}."
            )

    def _check_supports(self) -> None:
        segment_count = len(self.forecast.segment_s)
        first = self.clocks[0].support
        counts = [regime.segment_count for regime in first.classes]
        for scores in self.clocks:
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

    def _check_passages(self) -> None:
        usage = self.scenario is Scenario.USAGE
        for scores in self.clocks:
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

    def _check_envelope_presence(self) -> None:
        empty = self.clocks[0].support.segment_count == 0
        if (self.envelope is None) != empty:
            raise ContractError(
                "envelope est absente si et seulement si le support est vide."
            )

    def _check_class_envelopes(self) -> None:
        if len(self.class_envelopes) != len(RegimeClass):
            raise ContractError(
                f"class_envelopes porte une enveloppe par classe ({len(RegimeClass)}), "
                f"reçu {len(self.class_envelopes)}."
            )
        for regime, envelope in zip(
            self.clocks[0].support.classes, self.class_envelopes, strict=True
        ):
            if (envelope is None) != (regime.segment_count == 0):
                raise ContractError(
                    f"l'enveloppe de {regime.regime_class} est absente si et seulement "
                    f"si sa classe est vide (effectif {regime.segment_count})."
                )

    def _check_envelope_motifs(self) -> None:
        model_error = self.clocks[0].support.model_error
        for envelope in (self.envelope, *self.class_envelopes):
            if envelope is None:
                continue
            motif = envelope.unavailability
            if motif is Unavailability.MODEL_ERROR and not model_error:
                raise ContractError(
                    "une enveloppe en model_error exige support.model_error (D7.1)."
                )
            if model_error and motif is None:
                raise ContractError(
                    "sous support.model_error, toute enveloppe présente a un motif "
                    "(D7.1)."
                )


@dataclass(frozen=True)
class OutingScores:
    """Les scores d'un modèle sur une sortie, dans ses scénarios (``0010`` D3, D7).

    Champs
    ------
    - ``observation`` — sans unité — ce que la sortie observe, indépendamment du
      modèle.
    - ``control`` — sans unité — les scores du scénario contrôle.
    - ``usage`` — sans unité — les scores du scénario usage ; absent pour une sortie
      sans référence (D3).

    Invariants
    ----------
    - ``control.scenario == CONTROL`` ; ``usage`` absent ou
      ``usage.scenario == USAGE`` ;
    - pour chaque scénario présent,
      ``len(forecast.segment_s) == len(observation.segments)`` ;
    - en usage, ``len(point_s) == len(observation.error_points)`` et
      ``len(target_s) == len(observation.targets)``.

    Producteur
    ----------
    ``score_outing`` et ``v0_scores`` (``mountain_perf.backtest.scoring``).

    Consommateurs
    -------------
    ``mperf match`` ; le rapport (M4b-5).

    Non promis
    ----------
    - ``usage`` absent ne dit pas pourquoi (sortie sans référence : l'appelant le
      sait) ;
    - aucune métrique n'y est agrégée sur plusieurs sorties.
    """

    observation: OutingObservation
    control: ScenarioScores
    usage: ScenarioScores | None

    def __post_init__(self) -> None:
        if self.control.scenario is not Scenario.CONTROL:
            raise ContractError(
                f"control porte le scénario contrôle, reçu {self.control.scenario}."
            )
        if self.usage is not None and self.usage.scenario is not Scenario.USAGE:
            raise ContractError(
                f"usage porte le scénario usage, reçu {self.usage.scenario}."
            )
        observation = self.observation
        for scores in (self.control, self.usage):
            if scores is None:
                continue
            forecast = scores.forecast
            if len(forecast.segment_s) != len(observation.segments):
                raise ContractError(
                    f"{scores.scenario} : {len(forecast.segment_s)} projections pour "
                    f"{len(observation.segments)} segments admis."
                )
        if self.usage is not None:
            forecast = self.usage.forecast
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
