"""Contrats des points de score : l'observation de chaque point de la grille de score.

Protocole : ``docs/decisions/0010`` D4.2 et D4.5 à D4.9. Pour chaque point ``k`` de
la grille de score du tracé de référence, la trace dit s'il a été franchi, **où**
(position fractionnaire ``π``, abscisse réalisée ``d_r(π)``), **quand** (``t*``), et
sinon pourquoi. Les segments, la couverture et le préfixe (M4a-2b) se construisent
sur ces observations.

M4a-2b (``0010`` D4.2, D4.9 à D4.11, D5.4, D6, D13) : l'observation de chaque
segment ``[b_k ; b_{k+1}]`` (régimes, admissibilité), la couverture publiée, les
totaux du support admis, les configurations de sensibilité et le ``MatchResult``
qui rassemble le tout. Aucun seuil du protocole ne figure ici : ils vivent dans
``mountain_perf.backtest.segments``.
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from itertools import pairwise
from types import MappingProxyType

from mountain_perf.schemas.clock import (
    CLOCK_CONVENTIONS,
    CLOCK_TOTALS_RELATIVE_TOLERANCE,
    Clock,
    ClockTotals,
)
from mountain_perf.schemas.parameters import ParameterSet
from mountain_perf.validation import (
    ContractError,
    require_finite,
    require_immutable_sequence,
    require_non_empty,
)


class PointStatus(StrEnum):
    """Statut de l'observation d'un point de score (``0010`` D4.3 à D4.8).

    Champs
    ------
    Valeurs décrites dans ``POINT_STATUS_DESCRIPTIONS``.

    Invariants
    ----------
    Énumération fermée : un point de score reçoit un seul statut par sortie.

    Producteur
    ----------
    ``match_points`` (``mountain_perf.backtest.matching``).

    Consommateurs
    -------------
    ``ScorePointObservation`` ; ``mperf match`` ; les segments, la couverture et le
    préfixe (M4a-2b).

    Non promis
    ----------
    Seuls ``FOUND`` et ``ANCHORED`` datent un point. Les autres statuts sont des
    indisponibilités motivées (``0010`` D0) : ni un échec sportif, ni une erreur du
    modèle. ``AMBIGUOUS`` n'est jamais départagé.
    """

    FOUND = "found"
    ANCHORED = "anchored"
    AMBIGUOUS = "ambiguous"
    ABSENT = "absent"
    OUT_OF_TOLERANCE = "out_of_tolerance"
    UNDEFINED_TANGENT = "undefined_tangent"


POINT_STATUS_DESCRIPTIONS: Mapping[PointStatus, str] = MappingProxyType(
    {
        PointStatus.FOUND: (
            "Trouvé : un seul événement de candidats admissibles (D4.5 à D4.7)."
        ),
        PointStatus.ANCHORED: (
            "Ancré : extrémité sans candidat admissible, datée par le premier ou le "
            "dernier enregistrement (D4.8)."
        ),
        PointStatus.AMBIGUOUS: (
            "Ambigu : deux événements ou plus (D4.7), ou projection d'ancrage à "
            "égalité (D4.8) ; jamais départagé."
        ),
        PointStatus.ABSENT: (
            "Absent : aucun franchissement orienté dans la fenêtre, et pas "
            "d'ancrage — pour une extrémité, quel que soit l'échec de l'ancrage "
            "(D4.8)."
        ),
        PointStatus.OUT_OF_TOLERANCE: (
            "Hors ε : au moins un franchissement orienté dans la fenêtre, aucun "
            "admissible, et pas d'ancrage — pour une extrémité aussi (D4.7, "
            "précision, appliquée à D4.8)."
        ),
        PointStatus.UNDEFINED_TANGENT: (
            "Tangente indéfinie : corde de moins de 1e−6 m (D4.3)."
        ),
    }
)

_DATED = frozenset({PointStatus.FOUND, PointStatus.ANCHORED})
_WITHOUT_CANDIDATE = frozenset(
    {
        PointStatus.ANCHORED,
        PointStatus.ABSENT,
        PointStatus.OUT_OF_TOLERANCE,
        PointStatus.UNDEFINED_TANGENT,
    }
)


@dataclass(frozen=True)
class ScorePointObservation:
    """Observation d'un point ``k`` de la grille de score par une trace réalisée.

    Champs
    ------
    - ``index`` — sans unité — ``k``, rang dans la grille de score.
    - ``nominal_m`` — mètres — ``s_k``, abscisse du point sur la référence.
    - ``effective_m`` — mètres — borne effective ``b_k`` (``0010`` D4.2) : ``s'_0``
      ou ``s'_K`` si l'extrémité est ancrée, sinon ``s_k``.
    - ``status`` — sans unité — statut de l'observation.
    - ``position`` — sans unité — ``π = i + f``, position fractionnaire dans la trace.
    - ``time_s`` — secondes — ``t*``, depuis le premier enregistrement de la trace.
    - ``lateral_m`` — mètres — écart latéral signé ``(P − Q)·n`` du candidat qui
      date l'événement, ou de l'enregistrement ancré ; positif à gauche du sens de
      parcours de la référence.
    - ``realized_m`` — mètres — ``d_r(π)``, abscisse réalisée.
    - ``candidate_count`` — sans unité — candidats admissibles de la fenêtre, après
      confusion des candidats de même ``π``.
    - ``event_count`` — sans unité — événements formés par ces candidats.

    Propriétés calculées (jamais stockées) : ``dated`` et ``anchoring_offset_m``.

    Invariants
    ----------
    - ``index >= 0`` ; ``nominal_m`` et ``effective_m`` finis et ``>= 0`` ;
    - ``effective_m != nominal_m`` ⇒ ``status == ANCHORED`` ;
    - ``position``, ``time_s``, ``lateral_m``, ``realized_m`` présents **si et
      seulement si** le point est daté ; présents, ils sont finis, et ``position``,
      ``time_s``, ``realized_m`` sont ``>= 0`` ;
    - ``ANCHORED`` ⇒ ``position`` entière : l'ancrage date par un enregistrement ;
    - ``candidate_count >= 0``, ``event_count >= 0``,
      ``event_count <= candidate_count`` ;
    - ``FOUND`` ⇒ ``event_count == 1`` ;
    - ``ANCHORED``, ``ABSENT``, ``OUT_OF_TOLERANCE``, ``UNDEFINED_TANGENT`` ⇒
      ``candidate_count == 0`` ;
    - ``AMBIGUOUS`` ⇒ ``event_count >= 2`` ou ``candidate_count == 0`` (au moins
      deux événements, ou aucun candidat et une projection d'ancrage à égalité).

    Producteur
    ----------
    ``match_points`` (``mountain_perf.backtest.matching``).

    Consommateurs
    -------------
    ``mperf match`` ; les segments, la couverture et le préfixe (M4a-2b) ; les
    passages nommés (M4a-3).

    Non promis
    ----------
    - la cohérence **entre** points (indices consécutifs, positions et instants
      croissants, bornes effectives croissantes) n'est pas vérifiée ici : c'est une
      propriété de ``match_points`` et un invariant du futur ``MatchResult``
      (M4a-2b) ;
    - un point ne connaît ni ``K`` ni ``L`` ;
    - ``lateral_m`` n'est pas comparé à ``ε``, que le contrat ignore.
    """

    index: int
    nominal_m: float
    effective_m: float
    status: PointStatus
    position: float | None
    time_s: float | None
    lateral_m: float | None
    realized_m: float | None
    candidate_count: int
    event_count: int

    def __post_init__(self) -> None:
        if self.index < 0:
            raise ContractError(f"index doit être >= 0, reçu {self.index}.")
        for name in ("nominal_m", "effective_m"):
            value: float = getattr(self, name)
            require_finite(value, name)
            if value < 0:
                raise ContractError(f"{name} doit être >= 0, reçu {value}.")
        if (
            self.effective_m != self.nominal_m
            and self.status is not PointStatus.ANCHORED
        ):
            raise ContractError(
                "effective_m ne peut différer de nominal_m que pour un point "
                f"ANCHORED, reçu {self.status} ({self.effective_m} ≠ "
                f"{self.nominal_m})."
            )
        self._check_dating()
        self._check_counts()

    def _check_dating(self) -> None:
        dated = self.dated
        for name in ("position", "time_s", "lateral_m", "realized_m"):
            value: float | None = getattr(self, name)
            if dated and value is None:
                raise ContractError(
                    f"{name} doit être présent pour un point daté ({self.status})."
                )
            if not dated and value is not None:
                raise ContractError(
                    f"{name} doit être absent pour un point non daté ({self.status})."
                )
            if value is None:
                continue
            require_finite(value, name)
            if name != "lateral_m" and value < 0:
                raise ContractError(f"{name} doit être >= 0, reçu {value}.")
        if (
            self.status is PointStatus.ANCHORED
            and self.position is not None
            and not self.position.is_integer()
        ):
            raise ContractError(
                "position doit être entière pour un point ANCHORED (daté par un "
                f"enregistrement), reçu {self.position}."
            )

    def _check_counts(self) -> None:
        for name in ("candidate_count", "event_count"):
            count: int = getattr(self, name)
            if count < 0:
                raise ContractError(f"{name} doit être >= 0, reçu {count}.")
        if self.event_count > self.candidate_count:
            raise ContractError(
                f"event_count ({self.event_count}) doit être <= candidate_count "
                f"({self.candidate_count})."
            )
        if self.status is PointStatus.FOUND and self.event_count != 1:
            raise ContractError(
                "event_count doit valoir 1 pour un point FOUND, "
                f"reçu {self.event_count}."
            )
        if self.status in _WITHOUT_CANDIDATE and self.candidate_count != 0:
            raise ContractError(
                f"candidate_count doit valoir 0 pour un point {self.status}, "
                f"reçu {self.candidate_count}."
            )
        if (
            self.status is PointStatus.AMBIGUOUS
            and self.event_count < 2
            and self.candidate_count != 0
        ):
            raise ContractError(
                "un point AMBIGUOUS a au moins deux événements, ou aucun candidat "
                f"(projection d'ancrage à égalité) : reçu {self.candidate_count} "
                f"candidat(s), {self.event_count} événement(s)."
            )

    @property
    def dated(self) -> bool:
        """Le point est daté : statut ``FOUND`` ou ``ANCHORED``."""
        return self.status in _DATED

    @property
    def anchoring_offset_m(self) -> float:
        """``effective_m − nominal_m`` (mètres) : nul hors ancrage.

        ``s'_0 >= 0`` au départ, ``s'_K − L <= 0`` à l'arrivée ; nul aussi quand la
        projection d'ancrage tombe sur l'extrémité du tracé.
        """
        return self.effective_m - self.nominal_m


# ---------------------------------------------------------------------------
# Segments, couverture, totaux admis, sensibilité (M4a-2b)
# ---------------------------------------------------------------------------

FRACTION_TOLERANCE = 1e-9
"""Tolérance des fractions de régime d'un segment (``0010`` D6).

Chaque fraction est dans ``[0 ; 1]`` et leur somme vaut 1 à ``1e−9`` près : une
borne effective d'ancrage peut rendre une fraction de ``1,0000000000000002``.
"""

COVERAGE_RELATIVE_TOLERANCE = 1e-6
"""Tolérance relative des identités de longueur de la couverture (``0010`` D4.11),
rapportée à ``max(1, L)``."""


class SegmentExclusion(StrEnum):
    """Motif d'exclusion d'un segment de score (``0010`` D4.9, D4.10).

    Champs
    ------
    Valeurs décrites dans ``SEGMENT_EXCLUSION_DESCRIPTIONS``.

    Correspondance entre le statut des bornes (``PointStatus``), le motif du segment
    et les indisponibilités de ``0010`` D0 (``Unavailability``) :

    - deux bornes ``found`` ou ``anchored`` : admis, ``gap``, ``length_ratio`` ou
      ``interior_deviation`` ; pas d'indisponibilité de borne ;
    - une borne ``ambiguous``, ``absent`` ou ``undefined_tangent`` :
      ``unobserved_bound`` ; indisponibilité ``ambiguous``, ``absent`` ou
      ``undefined_tangent`` ;
    - une borne ``out_of_tolerance`` : ``unobserved_bound`` ; pas d'équivalent
      (précision de D4.7) ;
    - motif ``gap`` : indisponibilité ``gap`` ;
    - motif ``length_ratio`` : pas d'équivalent (précision de D4.10) ;
    - motif ``interior_deviation`` : indisponibilité ``interior_deviation``.

    Invariants
    ----------
    Énumération fermée ; un segment non admis porte un seul motif, le premier dans
    l'ordre des conditions de D4.10 : borne non observée, trou, rapport de longueur,
    écart intérieur.

    Producteur
    ----------
    ``observe_segment`` et ``match_trace`` (``mountain_perf.backtest.segments``).

    Consommateurs
    -------------
    ``ScoreSegmentObservation`` ; ``Coverage`` ; ``mperf match`` ; les métriques
    (M4b), qui lisent le motif et les statuts des bornes.

    Non promis
    ----------
    ``UNOBSERVED_BOUND`` ne dit pas quel statut a la borne : ce sont les points du
    ``MatchResult`` qui le portent. Aucune conversion vers ``Unavailability`` n'est
    codée ici.
    """

    UNOBSERVED_BOUND = "unobserved_bound"
    GAP = "gap"
    LENGTH_RATIO = "length_ratio"
    INTERIOR_DEVIATION = "interior_deviation"


SEGMENT_EXCLUSION_DESCRIPTIONS: Mapping[SegmentExclusion, str] = MappingProxyType(
    {
        SegmentExclusion.UNOBSERVED_BOUND: (
            "Borne non observée : une borne ni trouvée ni ancrée (D4.10, point 1) ; "
            "durée inconnue."
        ),
        SegmentExclusion.GAP: (
            "Trou : un intervalle de plus de 10 s à l'intérieur (D4.9) ; temps "
            "écoulé connu, jamais scoré."
        ),
        SegmentExclusion.LENGTH_RATIO: (
            "Rapport de longueur : longueur réalisée sur longueur du segment hors de "
            "[0,6 ; 1,6] (D4.10, point 3, précision)."
        ),
        SegmentExclusion.INTERIOR_DEVIATION: (
            "Écart intérieur : H = max(H_1, H_2) > ε (D4.10, point 4)."
        ),
    }
)


class Regime(StrEnum):
    """Régime d'un intervalle de la grille fine, selon sa pente (``0010`` D6).

    Champs
    ------
    Valeurs décrites dans ``REGIME_DESCRIPTIONS``.

    Invariants
    ----------
    Énumération fermée : chaque pente fine reçoit un seul régime.

    Producteur
    ----------
    ``grade_regime`` (``mountain_perf.backtest.segments``).

    Consommateurs
    -------------
    Les fractions de régime des segments ; ``Coverage.regime_fraction`` ;
    ``mperf match`` ; les métriques par régime (M4b).

    Non promis
    ----------
    Le diagnostic « descente roulante / raide » de D6 n'est pas un régime : il n'est
    pas calculé en M4a (M4b).
    """

    ASCENT = "ascent"
    FLAT = "flat"
    DESCENT = "descent"


REGIME_DESCRIPTIONS: Mapping[Regime, str] = MappingProxyType(
    {
        Regime.ASCENT: "Montée : pente fine g > 0,05.",
        Regime.FLAT: "Plat : −0,05 ≤ g ≤ 0,05, bornes incluses.",
        Regime.DESCENT: "Descente : pente fine g < −0,05.",
    }
)


class RegimeClass(StrEnum):
    """Classe d'un segment de score (``0010`` D6).

    Champs
    ------
    Valeurs décrites dans ``REGIME_CLASS_DESCRIPTIONS``.

    Invariants
    ----------
    Énumération fermée : un segment est pur d'un régime ou mixte.

    Producteur
    ----------
    ``regime_class`` (``mountain_perf.backtest.segments``).

    Consommateurs
    -------------
    ``ScoreSegmentObservation`` ; les métriques par régime (M4b).

    Non promis
    ----------
    Mixte n'est jamais une cible, un garde-fou ni une dimension d'apprentissage
    (D6). Le temps observé n'est jamais réparti selon les fractions.
    """

    ASCENT = "ascent"
    FLAT = "flat"
    DESCENT = "descent"
    MIXED = "mixed"


REGIME_CLASS_DESCRIPTIONS: Mapping[RegimeClass, str] = MappingProxyType(
    {
        RegimeClass.ASCENT: "Montée pure : au moins 80 % de la longueur en montée.",
        RegimeClass.FLAT: "Plat pur : au moins 80 % de la longueur en plat.",
        RegimeClass.DESCENT: (
            "Descente pure : au moins 80 % de la longueur en descente."
        ),
        RegimeClass.MIXED: "Mixte : aucun régime n'atteint 80 % de la longueur.",
    }
)


@dataclass(frozen=True)
class ScoreSegmentObservation:
    """Observation d'un segment ``[b_k ; b_{k+1}]`` de la grille de score.

    Champs
    ------
    - ``index`` — sans unité — ``k``, rang du segment.
    - ``nominal_start_m``, ``nominal_end_m`` — mètres — ``s_k``, ``s_{k+1}``.
    - ``start_m``, ``end_m`` — mètres — bornes effectives ``b_k``, ``b_{k+1}``
      (``0010`` D4.2).
    - ``ascent_fraction``, ``flat_fraction``, ``descent_fraction`` — sans unité —
      fractions de régime sur ``[b_k ; b_{k+1}]`` (D6).
    - ``regime_class`` — sans unité — classe du segment, pure ou mixte (D6).
    - ``exclusion`` — sans unité — motif d'exclusion ; ``None`` = admis (D4.10).
    - ``length_ratio`` — sans unité — rapport de longueur ``rho`` (D4.10, point 3).
    - ``h1_m``, ``h2_m`` — mètres — ``H_1``, ``H_2`` (D4.10, point 4).
    - ``start_s``, ``end_s`` — secondes — ``t*_k``, ``t*_{k+1}``, instants des bornes
      quand elles sont datées.
    - ``realized_start_m``, ``realized_end_m`` — mètres — ``d_r(π_k)``,
      ``d_r(π_{k+1})``, abscisses réalisées des bornes quand elles sont datées (D3).

    Propriétés calculées (jamais stockées) : ``admitted``, ``length_m`` et
    ``interior_deviation_m``.

    Invariants
    ----------
    - ``index >= 0`` ; les quatre abscisses finies et ``>= 0`` ;
      ``nominal_start_m < nominal_end_m`` ; ``start_m < end_m`` ;
    - fractions finies, chacune dans ``[0 ; 1]`` à ``1e−9`` près, de somme 1 à
      ``1e−9`` près ;
    - ``regime_class`` est ``MIXED`` ou le régime d'une plus grande fraction ; une
      fraction égale à 1 à ``1e−9`` près impose sa classe ;
    - ``start_s`` présent si et seulement si ``realized_start_m`` l'est ; de même
      pour ``end_s`` et ``realized_end_m`` ; présents, ils sont finis et ``>= 0`` ;
      ``start_s < end_s`` et ``realized_start_m <= realized_end_m`` quand les quatre
      sont présents ;
    - ``length_ratio``, ``h1_m``, ``h2_m`` : tous présents ou tous absents ;
      présents, finis et ``>= 0`` ;
    - admis ⇒ ``length_ratio``, ``start_s``, ``end_s`` présents ;
    - ``UNOBSERVED_BOUND`` ⇒ ``length_ratio`` absent, et ``start_s`` ou ``end_s``
      absent ;
    - ``GAP`` ⇒ ``length_ratio`` absent, ``start_s`` et ``end_s`` présents ;
    - ``LENGTH_RATIO`` ou ``INTERIOR_DEVIATION`` ⇒ ``length_ratio``, ``start_s``,
      ``end_s`` présents.

    Producteur
    ----------
    ``observe_segment`` et ``match_trace`` (``mountain_perf.backtest.segments``).

    Consommateurs
    -------------
    ``Coverage``, ``MatchResult``, ``mperf match`` ; les métriques (M4b).

    Non promis
    ----------
    - un segment de bord ancré n'est pas la même cellule que le segment nominal
      (D4.2) : ses bornes le distinguent, son ``index`` non ;
    - les temps d'un segment non admis ne sont jamais un score ;
    - le contrat ignore les seuils (``0,6``, ``1,6``, ``ε``, ``0,80``) et ne vérifie
      donc pas qu'un motif correspond aux valeurs publiées : c'est le rôle des tests
      du producteur.
    """

    index: int
    nominal_start_m: float
    nominal_end_m: float
    start_m: float
    end_m: float
    ascent_fraction: float
    flat_fraction: float
    descent_fraction: float
    regime_class: RegimeClass
    exclusion: SegmentExclusion | None
    length_ratio: float | None
    h1_m: float | None
    h2_m: float | None
    start_s: float | None
    end_s: float | None
    realized_start_m: float | None
    realized_end_m: float | None

    def __post_init__(self) -> None:
        self._check_bounds()
        self._check_regimes()
        self._check_dating()
        self._check_controls()
        self._check_exclusion()

    def _check_bounds(self) -> None:
        if self.index < 0:
            raise ContractError(f"index doit être >= 0, reçu {self.index}.")
        for name in ("nominal_start_m", "nominal_end_m", "start_m", "end_m"):
            value: float = getattr(self, name)
            require_finite(value, name)
            if value < 0:
                raise ContractError(f"{name} doit être >= 0, reçu {value}.")
        if not self.nominal_start_m < self.nominal_end_m:
            raise ContractError(
                f"nominal_start_m ({self.nominal_start_m}) doit précéder "
                f"nominal_end_m ({self.nominal_end_m})."
            )
        if not self.start_m < self.end_m:
            raise ContractError(
                f"start_m ({self.start_m}) doit précéder end_m ({self.end_m})."
            )

    def _check_regimes(self) -> None:
        fractions = {
            Regime.ASCENT: self.ascent_fraction,
            Regime.FLAT: self.flat_fraction,
            Regime.DESCENT: self.descent_fraction,
        }
        for regime, value in fractions.items():
            name = f"{regime.value}_fraction"
            require_finite(value, name)
            if not -FRACTION_TOLERANCE <= value <= 1 + FRACTION_TOLERANCE:
                raise ContractError(
                    f"{name} doit être dans [0 ; 1] à 1e−9 près, reçu {value}."
                )
        total = math.fsum(fractions.values())
        if abs(total - 1) > FRACTION_TOLERANCE:
            raise ContractError(
                "la somme des fractions de régime doit valoir 1 à 1e−9 près, reçu "
                f"{total}."
            )
        largest = max(fractions.values())
        if self.regime_class is not RegimeClass.MIXED:
            own = fractions[Regime(self.regime_class.value)]
            if own != largest:
                raise ContractError(
                    f"regime_class {self.regime_class} doit être MIXED ou le régime "
                    f"d'une plus grande fraction, reçu {own} < {largest}."
                )
        for regime, value in fractions.items():
            if (
                abs(value - 1) <= FRACTION_TOLERANCE
                and self.regime_class.value != regime.value
            ):
                raise ContractError(
                    f"une fraction égale à 1 impose sa classe : {regime.value} vaut "
                    f"{value}, reçu regime_class {self.regime_class}."
                )

    def _check_dating(self) -> None:
        for time_name, realized_name in (
            ("start_s", "realized_start_m"),
            ("end_s", "realized_end_m"),
        ):
            time_s: float | None = getattr(self, time_name)
            realized_m: float | None = getattr(self, realized_name)
            if (time_s is None) != (realized_m is None):
                raise ContractError(
                    f"{time_name} doit être présent si et seulement si "
                    f"{realized_name} l'est."
                )
            for name, value in ((time_name, time_s), (realized_name, realized_m)):
                if value is None:
                    continue
                require_finite(value, name)
                if value < 0:
                    raise ContractError(f"{name} doit être >= 0, reçu {value}.")
        if self.start_s is None or self.end_s is None:
            return
        if not self.start_s < self.end_s:
            raise ContractError(
                f"start_s ({self.start_s}) doit précéder end_s ({self.end_s})."
            )
        if (
            self.realized_start_m is not None
            and self.realized_end_m is not None
            and self.realized_start_m > self.realized_end_m
        ):
            raise ContractError(
                f"realized_start_m ({self.realized_start_m}) doit être <= "
                f"realized_end_m ({self.realized_end_m})."
            )

    def _check_controls(self) -> None:
        controls = {
            "length_ratio": self.length_ratio,
            "h1_m": self.h1_m,
            "h2_m": self.h2_m,
        }
        present = [value is not None for value in controls.values()]
        if any(present) and not all(present):
            raise ContractError(
                "length_ratio, h1_m et h2_m doivent être tous présents ou tous "
                f"absents, reçu {controls}."
            )
        for name, value in controls.items():
            if value is None:
                continue
            require_finite(value, name)
            if value < 0:
                raise ContractError(f"{name} doit être >= 0, reçu {value}.")

    def _check_exclusion(self) -> None:
        both_dated = self.start_s is not None and self.end_s is not None
        controlled = self.length_ratio is not None
        exclusion = self.exclusion
        if exclusion is SegmentExclusion.UNOBSERVED_BOUND:
            if controlled:
                raise ContractError(
                    "un segment unobserved_bound ne publie pas length_ratio."
                )
            if both_dated:
                raise ContractError(
                    "un segment unobserved_bound a une borne non datée : start_s ou "
                    "end_s absent."
                )
        elif exclusion is SegmentExclusion.GAP:
            if controlled:
                raise ContractError("un segment gap ne publie pas length_ratio.")
            if not both_dated:
                raise ContractError("un segment gap publie start_s et end_s.")
        elif not (controlled and both_dated):
            state = "admis" if exclusion is None else str(exclusion)
            raise ContractError(
                f"un segment {state} publie length_ratio, start_s et end_s."
            )

    @property
    def admitted(self) -> bool:
        """Segment admis au score : aucun motif d'exclusion (``0010`` D4.10)."""
        return self.exclusion is None

    @property
    def length_m(self) -> float:
        """``end_m − start_m`` (mètres) : longueur exacte entre les bornes
        effectives (``0010`` D4.2)."""
        return self.end_m - self.start_m

    @property
    def interior_deviation_m(self) -> float | None:
        """``H = max(H_1, H_2)`` (mètres, ``0010`` D4.10) ; ``None`` si l'un manque."""
        if self.h1_m is None or self.h2_m is None:
            return None
        return max(self.h1_m, self.h2_m)


_COVERAGE_FLOATS = (
    "reference_length_m",
    "admitted_m",
    "excluded_unobserved_bound_m",
    "excluded_gap_m",
    "excluded_length_ratio_m",
    "excluded_interior_deviation_m",
    "anchoring_excluded_m",
    "ascent_length_m",
    "flat_length_m",
    "descent_length_m",
    "admitted_ascent_m",
    "admitted_flat_m",
    "admitted_descent_m",
    "admitted_elapsed_s",
    "excluded_gap_s",
    "excluded_length_ratio_s",
    "excluded_interior_deviation_s",
    "prefix_end_m",
)


@dataclass(frozen=True)
class Coverage:
    """Couverture publiée d'une sortie contre un tracé de référence (``0010`` D4.11).

    Champs
    ------
    - ``reference_length_m`` — mètres — ``L``, longueur du profil de référence.
    - ``admitted_m`` — mètres — longueur des segments admis.
    - ``excluded_unobserved_bound_m``, ``excluded_gap_m``,
      ``excluded_length_ratio_m``, ``excluded_interior_deviation_m`` — mètres —
      longueur des segments exclus, par motif.
    - ``anchoring_excluded_m`` — mètres — ``b_0 + (L − b_K)``, motif ``ancrage``.
    - ``ascent_length_m``, ``flat_length_m``, ``descent_length_m`` — mètres —
      longueurs fines de chaque régime sur ``[0 ; L]``.
    - ``admitted_ascent_m``, ``admitted_flat_m``, ``admitted_descent_m`` — mètres —
      longueurs fines de chaque régime dans les segments admis.
    - ``admitted_elapsed_s`` — secondes — ``E_A``, écoulé des segments admis.
    - ``excluded_gap_s``, ``excluded_length_ratio_s``,
      ``excluded_interior_deviation_s`` — secondes — temps écoulés exclus connus,
      par motif.
    - ``prefix_segment_count`` — sans unité — ``m``, longueur du préfixe comparable.
    - ``prefix_end_m`` — mètres — ``b_m``, fin du préfixe.
    - ``prefix_end_s`` — secondes — ``t*_m``, ``None`` si le point ``m`` n'est pas
      daté.
    - ``prefix_last_passage`` — sans unité — nom du dernier lieu nommé du préfixe,
      ``None`` s'il n'en contient pas.

    Propriété calculée (jamais stockée) : ``fraction`` ; méthode
    ``regime_fraction(regime)`` : longueur admise du régime rapportée à sa longueur
    sur ``[0 ; L]``, ``None`` si celle-ci est nulle (« non évalué »).

    Invariants
    ----------
    - valeurs finies et ``>= 0`` ; ``L > 0`` ;
    - ``admitted_m + Σ excluded_*_m + anchoring_excluded_m = L`` à
      ``1e−6·max(1, L)`` près ;
    - ``ascent_length_m + flat_length_m + descent_length_m = L`` à
      ``1e−6·max(1, L)`` près ;
    - chaque longueur admise d'un régime ``<=`` sa longueur sur ``[0 ; L]`` à
      ``1e−6·max(1, L)`` près ;
    - ``prefix_segment_count >= 0`` ; ``prefix_last_passage`` non vide s'il est
      présent.

    Producteur
    ----------
    ``match_trace`` (``mountain_perf.backtest.segments``).

    Consommateurs
    -------------
    ``MatchResult``, ``mperf match`` ; le rapport (M4b).

    Non promis
    ----------
    - les « durées inconnues » de D4.11 sont les segments ``unobserved_bound`` du
      ``MatchResult``, que ``mperf match`` compte ;
    - le temps passé sur les marges d'ancrage n'est pas observé et n'est pas publié ;
    - les comptes de points par statut sont dans les points.
    """

    reference_length_m: float
    admitted_m: float
    excluded_unobserved_bound_m: float
    excluded_gap_m: float
    excluded_length_ratio_m: float
    excluded_interior_deviation_m: float
    anchoring_excluded_m: float
    ascent_length_m: float
    flat_length_m: float
    descent_length_m: float
    admitted_ascent_m: float
    admitted_flat_m: float
    admitted_descent_m: float
    admitted_elapsed_s: float
    excluded_gap_s: float
    excluded_length_ratio_s: float
    excluded_interior_deviation_s: float
    prefix_segment_count: int
    prefix_end_m: float
    prefix_end_s: float | None
    prefix_last_passage: str | None

    def __post_init__(self) -> None:
        for name in _COVERAGE_FLOATS:
            value: float = getattr(self, name)
            require_finite(value, name)
            if value < 0:
                raise ContractError(f"{name} doit être >= 0, reçu {value}.")
        if self.prefix_end_s is not None:
            require_finite(self.prefix_end_s, "prefix_end_s")
            if self.prefix_end_s < 0:
                raise ContractError(
                    f"prefix_end_s doit être >= 0, reçu {self.prefix_end_s}."
                )
        length_m = self.reference_length_m
        if not length_m > 0:
            raise ContractError(f"reference_length_m doit être > 0, reçu {length_m}.")
        tolerance_m = COVERAGE_RELATIVE_TOLERANCE * max(1.0, length_m)
        partition_gap_m = math.fsum(
            (
                self.admitted_m,
                self.excluded_unobserved_bound_m,
                self.excluded_gap_m,
                self.excluded_length_ratio_m,
                self.excluded_interior_deviation_m,
                self.anchoring_excluded_m,
                -length_m,
            )
        )
        if abs(partition_gap_m) > tolerance_m:
            raise ContractError(
                "admitted_m + excluded_*_m + anchoring_excluded_m doit valoir "
                f"reference_length_m, écart {partition_gap_m}."
            )
        regime_gap_m = math.fsum(
            (self.ascent_length_m, self.flat_length_m, self.descent_length_m, -length_m)
        )
        if abs(regime_gap_m) > tolerance_m:
            raise ContractError(
                "ascent_length_m + flat_length_m + descent_length_m doit valoir "
                f"reference_length_m, écart {regime_gap_m}."
            )
        for regime in Regime:
            admitted_m, total_m = self._regime_lengths(regime)
            if admitted_m > total_m + tolerance_m:
                raise ContractError(
                    f"admitted_{regime.value}_m ({admitted_m}) doit être <= "
                    f"{regime.value}_length_m ({total_m})."
                )
        if self.prefix_segment_count < 0:
            raise ContractError(
                "prefix_segment_count doit être >= 0, reçu "
                f"{self.prefix_segment_count}."
            )
        if self.prefix_last_passage is not None:
            require_non_empty(self.prefix_last_passage, "prefix_last_passage")

    def _regime_lengths(self, regime: Regime) -> tuple[float, float]:
        """Longueur admise et longueur sur ``[0 ; L]`` d'un régime (mètres)."""
        admitted_m: float = getattr(self, f"admitted_{regime.value}_m")
        total_m: float = getattr(self, f"{regime.value}_length_m")
        return admitted_m, total_m

    @property
    def fraction(self) -> float:
        """``admitted_m / L`` (sans unité) : couverture globale (``0010`` D4.11)."""
        return self.admitted_m / self.reference_length_m

    def regime_fraction(self, regime: Regime) -> float | None:
        """Couverture d'un régime (sans unité) : longueur fine admise rapportée à la
        longueur fine sur ``[0 ; L]`` ; ``None`` si celle-ci est nulle, « non évalué »
        (``0010`` D4.11)."""
        admitted_m, total_m = self._regime_lengths(regime)
        if total_m == 0:
            return None
        return admitted_m / total_m


@dataclass(frozen=True)
class AdmittedTotals:
    """Totaux du support admis sous une convention : écoulé, mouvement, arrêt,
    indéterminé (``0010`` D5.4).

    Champs
    ------
    - ``elapsed_s`` — secondes — ``E_A``, somme des ``t*_{k+1} − t*_k`` des segments
      admis.
    - ``moving_s`` — secondes — ``M_{θ,A}``.
    - ``stopped_s`` — secondes — ``S_{θ,A}``.
    - ``undetermined_s`` — secondes — ``U_{θ,A}``.

    Invariants
    ----------
    - valeurs finies et ``>= 0`` ;
    - ``|M + S + U − E_A| <= 1e−9 · max(1, E_A)`` (la tolérance de ``ClockTotals``).

    Producteur
    ----------
    ``admitted_totals`` (``mountain_perf.backtest.segments``).

    Consommateurs
    -------------
    ``MatchResult``, ``mperf match`` ; les enveloppes et le rapport (M4b).

    Non promis
    ----------
    Ce ne sont pas les totaux de la trace (``ClockTotals``) : aucun des deux types ne
    se convertit en l'autre, les deux jeux ne se mélangent jamais (D5.4).
    """

    elapsed_s: float
    moving_s: float
    stopped_s: float
    undetermined_s: float

    def __post_init__(self) -> None:
        for name in ("elapsed_s", "moving_s", "stopped_s", "undetermined_s"):
            value: float = getattr(self, name)
            require_finite(value, name)
            if value < 0:
                raise ContractError(f"{name} doit être >= 0, reçu {value}.")
        gap = math.fsum(
            (self.moving_s, self.stopped_s, self.undetermined_s, -self.elapsed_s)
        )
        if abs(gap) > CLOCK_TOTALS_RELATIVE_TOLERANCE * max(1.0, self.elapsed_s):
            raise ContractError(
                "moving_s + stopped_s + undetermined_s doit valoir elapsed_s, "
                f"écart {gap}."
            )


@dataclass(frozen=True)
class SensitivityConfiguration:
    """Une configuration de sensibilité (``0010`` D13).

    Champs
    ------
    - ``score_step_m`` — mètres — ``Δ``, pas de la grille de score.
    - ``lateral_tolerance_m`` — mètres — ``ε``, tolérance latérale.
    - ``cluster_radius_m`` — mètres — ``r_c``, rayon de regroupement.
    - ``clock`` — sans unité — l'horloge de la configuration.

    Invariants
    ----------
    Valeurs finies ; ``Δ > 0``, ``ε > 0``, ``r_c >= 0``.

    Producteur
    ----------
    ``SENSITIVITY_CONFIGURATIONS`` (``mountain_perf.backtest.sensitivity``).

    Consommateurs
    -------------
    L'exécution de la sensibilité (M4d).

    Non promis
    ----------
    Rien n'est exécuté en M4a ; une configuration ne dit pas comment elle sera
    exécutée.
    """

    score_step_m: float
    lateral_tolerance_m: float
    cluster_radius_m: float
    clock: Clock

    def __post_init__(self) -> None:
        for name in ("score_step_m", "lateral_tolerance_m", "cluster_radius_m"):
            value: float = getattr(self, name)
            require_finite(value, name)
        if self.score_step_m <= 0:
            raise ContractError(
                f"score_step_m doit être > 0, reçu {self.score_step_m}."
            )
        if self.lateral_tolerance_m <= 0:
            raise ContractError(
                f"lateral_tolerance_m doit être > 0, reçu {self.lateral_tolerance_m}."
            )
        if self.cluster_radius_m < 0:
            raise ContractError(
                f"cluster_radius_m doit être >= 0, reçu {self.cluster_radius_m}."
            )


@dataclass(frozen=True)
class MatchResult:
    """Tout ce que l'appariement observe d'une sortie contre un tracé de référence.

    Champs
    ------
    - ``parameters`` — sans unité — ``Δ``, ``ε``, ``r_c``, déclarés par
      ``MATCHING_PARAMETER_SPECS``.
    - ``points`` — sans unité — l'observation de chaque point de score, dans l'ordre.
    - ``segments`` — sans unité — l'observation de chaque segment, dans l'ordre.
    - ``coverage`` — sans unité — couverture, exclusions et préfixe (D4.11).
    - ``departure_delay_s`` — secondes — ``t*_0``, depuis le premier enregistrement ;
      ``None`` si le départ n'est pas daté.
    - ``trace_totals`` — sans unité — les cinq totaux de la trace (D5.4).
    - ``admitted_totals`` — sans unité — les cinq totaux du support admis (D5.4).
    - ``low_convention_index``, ``high_convention_index`` — sans unité — ``θ_bas``,
      ``θ_haut``, indices dans ``CLOCK_CONVENTIONS``.
    - ``admitted_sensitivity_range_s`` — secondes — ``I_sens,A``,
      ``(min_θ M_{θ,A} ; E_A − min_θ S_{θ,A})``.

    Invariants
    ----------
    - ``points``, ``segments``, ``trace_totals``, ``admitted_totals`` sont des
      tuples ;
    - ``len(points) >= 2``, ``len(segments) == len(points) − 1`` ;
    - ``points[k].index == k`` et ``segments[k].index == k`` ;
    - ``points[0].nominal_m == 0``, ``points[−1].nominal_m ==
      coverage.reference_length_m``, ``nominal_m`` strictement croissants ;
    - ``effective_m`` strictement croissants ; ``effective_m != nominal_m`` seulement
      pour le premier et le dernier point ;
    - ``position`` et ``time_s`` strictement croissants le long des points datés ;
    - pour chaque ``k`` : ``nominal_start_m``, ``start_m``, ``start_s``,
      ``realized_start_m`` du segment ``k`` égaux à ``nominal_m``, ``effective_m``,
      ``time_s``, ``realized_m`` du point ``k`` ; de même pour la fin avec le point
      ``k + 1`` ;
    - un segment est ``unobserved_bound`` si et seulement si l'une de ses bornes
      n'est pas datée ;
    - ``m = coverage.prefix_segment_count`` : les ``m`` premiers segments sont
      admis, et ``m == len(segments)`` ou le segment ``m`` ne l'est pas ;
      ``prefix_end_m`` et ``prefix_end_s`` sont ``effective_m`` et ``time_s`` du
      point ``m`` ;
    - ``departure_delay_s == points[0].time_s`` ;
    - ``len(trace_totals) == len(admitted_totals) == len(CLOCK_CONVENTIONS)`` ; les
      ``elapsed_s`` des ``admitted_totals`` égaux entre eux et à
      ``coverage.admitted_elapsed_s`` à ``1e−9·max(1, E_A)`` près ;
    - ``low_convention_index``, ``high_convention_index`` et
      ``admitted_sensitivity_range_s`` sont ``None`` si et seulement si aucun segment
      n'est admis ; présents, les deux indices sont le premier indice du minimum de
      ``moving_s`` et du maximum de ``moving_s + undetermined_s`` des
      ``admitted_totals``, et l'intervalle vaut ``(min moving_s ; E_A − min
      stopped_s)`` à ``1e−9·max(1, E_A)`` près (sa borne basse peut dépasser la haute
      d'un ulp sur un support entièrement mobile).

    Producteur
    ----------
    ``match_trace`` (``mountain_perf.backtest.segments``).

    Consommateurs
    -------------
    ``mperf match`` ; les passages (M4a-3) ; les métriques et le rapport (M4b).

    Non promis
    ----------
    - un ``MatchResult`` ne connaît ni la trace ni le tracé, seulement ce qui en a été
      observé ;
    - la grille ``nominal_m`` n'est pas recalculée par le contrat, qui ignore ``Δ`` ;
    - aucun extrême segment par segment n'est jamais publié (D5.4).
    """

    parameters: ParameterSet
    points: tuple[ScorePointObservation, ...]
    segments: tuple[ScoreSegmentObservation, ...]
    coverage: Coverage
    departure_delay_s: float | None
    trace_totals: tuple[ClockTotals, ...]
    admitted_totals: tuple[AdmittedTotals, ...]
    low_convention_index: int | None
    high_convention_index: int | None
    admitted_sensitivity_range_s: tuple[float, float] | None

    def __post_init__(self) -> None:
        self._check_sequences()
        self._check_points()
        self._check_segments()
        self._check_prefix()
        if self.departure_delay_s != self.points[0].time_s:
            raise ContractError(
                f"departure_delay_s ({self.departure_delay_s}) doit valoir "
                f"points[0].time_s ({self.points[0].time_s})."
            )
        self._check_totals()
        self._check_extremes()

    def _check_sequences(self) -> None:
        for name in ("points", "segments", "trace_totals", "admitted_totals"):
            require_immutable_sequence(getattr(self, name), name)
        if len(self.points) < 2:
            raise ContractError(
                f"points doit compter au moins 2 points, reçu {len(self.points)}."
            )
        if len(self.segments) != len(self.points) - 1:
            raise ContractError(
                f"segments doit compter len(points) − 1 = {len(self.points) - 1} "
                f"segments, reçu {len(self.segments)}."
            )
        for k, point in enumerate(self.points):
            if point.index != k:
                raise ContractError(
                    f"points[{k}].index doit valoir {k}, reçu {point.index}."
                )
        for k, segment in enumerate(self.segments):
            if segment.index != k:
                raise ContractError(
                    f"segments[{k}].index doit valoir {k}, reçu {segment.index}."
                )

    def _check_points(self) -> None:
        points = self.points
        if points[0].nominal_m != 0:
            raise ContractError(
                f"points[0].nominal_m doit valoir 0, reçu {points[0].nominal_m}."
            )
        length_m = self.coverage.reference_length_m
        if points[-1].nominal_m != length_m:
            raise ContractError(
                f"points[−1].nominal_m ({points[-1].nominal_m}) doit valoir "
                f"coverage.reference_length_m ({length_m})."
            )
        for a, b in pairwise(points):
            if not a.nominal_m < b.nominal_m:
                raise ContractError(
                    "nominal_m doit être strictement croissant "
                    f"(points {a.index} et {b.index})."
                )
            if not a.effective_m < b.effective_m:
                raise ContractError(
                    "effective_m doit être strictement croissant "
                    f"(points {a.index} et {b.index})."
                )
        for point in points[1:-1]:
            if point.effective_m != point.nominal_m:
                raise ContractError(
                    "effective_m ne peut différer de nominal_m qu'au premier et au "
                    f"dernier point (point {point.index})."
                )
        dated = [point for point in points if point.dated]
        for a, b in pairwise(dated):
            for name in ("position", "time_s"):
                before: float = getattr(a, name)
                after: float = getattr(b, name)
                if not before < after:
                    raise ContractError(
                        f"{name} doit être strictement croissant le long des points "
                        f"datés (points {a.index} et {b.index})."
                    )

    def _check_segments(self) -> None:
        for k, segment in enumerate(self.segments):
            start, end = self.points[k], self.points[k + 1]
            # Avant l'égalité des bornes, qui l'impliquerait sans le nommer.
            unobserved = segment.exclusion is SegmentExclusion.UNOBSERVED_BOUND
            if unobserved == (start.dated and end.dated):
                raise ContractError(
                    f"segments[{k}] est unobserved_bound si et seulement si l'une de "
                    "ses bornes n'est pas datée."
                )
            pairs = (
                ("nominal_start_m", segment.nominal_start_m, start.nominal_m),
                ("start_m", segment.start_m, start.effective_m),
                ("start_s", segment.start_s, start.time_s),
                ("realized_start_m", segment.realized_start_m, start.realized_m),
                ("nominal_end_m", segment.nominal_end_m, end.nominal_m),
                ("end_m", segment.end_m, end.effective_m),
                ("end_s", segment.end_s, end.time_s),
                ("realized_end_m", segment.realized_end_m, end.realized_m),
            )
            for name, own, expected in pairs:
                if own != expected:
                    raise ContractError(
                        f"segments[{k}].{name} ({own}) doit reprendre la valeur de "
                        f"sa borne ({expected})."
                    )

    def _check_prefix(self) -> None:
        m = self.coverage.prefix_segment_count
        if m > len(self.segments):
            raise ContractError(
                f"prefix_segment_count ({m}) dépasse le nombre de segments "
                f"({len(self.segments)})."
            )
        if not all(segment.admitted for segment in self.segments[:m]):
            raise ContractError(
                f"les {m} premiers segments du préfixe comparable doivent être admis."
            )
        if m < len(self.segments) and self.segments[m].admitted:
            raise ContractError(
                f"le préfixe comparable est le plus long : le segment {m} ne doit pas "
                "être admis."
            )
        end = self.points[m]
        if self.coverage.prefix_end_m != end.effective_m:
            raise ContractError(
                f"prefix_end_m ({self.coverage.prefix_end_m}) doit valoir "
                f"points[{m}].effective_m ({end.effective_m})."
            )
        if self.coverage.prefix_end_s != end.time_s:
            raise ContractError(
                f"prefix_end_s ({self.coverage.prefix_end_s}) doit valoir "
                f"points[{m}].time_s ({end.time_s})."
            )

    def _check_totals(self) -> None:
        conventions = len(CLOCK_CONVENTIONS)
        for name in ("trace_totals", "admitted_totals"):
            count = len(getattr(self, name))
            if count != conventions:
                raise ContractError(
                    f"{name} doit porter {conventions} totaux, reçu {count}."
                )
        elapsed_s = self.coverage.admitted_elapsed_s
        tolerance_s = CLOCK_TOTALS_RELATIVE_TOLERANCE * max(1.0, elapsed_s)
        for k, totals in enumerate(self.admitted_totals):
            if abs(totals.elapsed_s - elapsed_s) > tolerance_s:
                raise ContractError(
                    f"admitted_totals[{k}].elapsed_s ({totals.elapsed_s}) doit valoir "
                    f"coverage.admitted_elapsed_s ({elapsed_s})."
                )

    def _check_extremes(self) -> None:
        low, high = self.low_convention_index, self.high_convention_index
        interval = self.admitted_sensitivity_range_s
        if not any(segment.admitted for segment in self.segments):
            if low is not None or high is not None or interval is not None:
                raise ContractError(
                    "θ_bas, θ_haut et I_sens,A doivent être absents sans segment admis."
                )
            return
        if low is None or high is None or interval is None:
            raise ContractError(
                "θ_bas, θ_haut et I_sens,A doivent être présents dès qu'un segment "
                "est admis."
            )
        totals = self.admitted_totals
        indices = range(len(totals))
        lowest = min(indices, key=lambda k: totals[k].moving_s)
        highest = max(
            indices, key=lambda k: totals[k].moving_s + totals[k].undetermined_s
        )
        if low != lowest:
            raise ContractError(
                f"low_convention_index ({low}) doit être le premier indice du "
                f"minimum de moving_s ({lowest})."
            )
        if high != highest:
            raise ContractError(
                f"high_convention_index ({high}) doit être le premier indice du "
                f"maximum de moving_s + undetermined_s ({highest})."
            )
        elapsed_s = self.coverage.admitted_elapsed_s
        tolerance_s = CLOCK_TOTALS_RELATIVE_TOLERANCE * max(1.0, elapsed_s)
        expected = (
            min(t.moving_s for t in totals),
            elapsed_s - min(t.stopped_s for t in totals),
        )
        for bound, own, wanted in zip(
            ("basse", "haute"), interval, expected, strict=True
        ):
            if not abs(own - wanted) <= tolerance_s:
                raise ContractError(
                    f"la borne {bound} de admitted_sensitivity_range_s ({own}) doit "
                    f"valoir {wanted} : (min moving_s ; E_A − min stopped_s)."
                )
