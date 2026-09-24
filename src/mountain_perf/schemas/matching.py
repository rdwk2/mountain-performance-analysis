"""Contrats des points de score : l'observation de chaque point de la grille de score.

Protocole : ``docs/decisions/0010`` D4.2 et D4.5 à D4.9. Pour chaque point ``k`` de
la grille de score du tracé de référence, la trace dit s'il a été franchi, **où**
(position fractionnaire ``π``, abscisse réalisée ``d_r(π)``), **quand** (``t*``), et
sinon pourquoi. Les segments, la couverture et le préfixe (M4a-2b) se construisent
sur ces observations.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from types import MappingProxyType

from mountain_perf.validation import ContractError, require_finite


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
