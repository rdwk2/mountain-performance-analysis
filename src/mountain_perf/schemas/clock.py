"""Contrats des horloges : conventions, partition M/S/U, totaux, épisodes d'arrêt.

Protocole : ``docs/decisions/0010`` D5. Les onze horloges sont l'écoulé, le mouvement
``M_θ`` et ``M_θ + U_θ`` sous chacune des cinq conventions ; toutes sont calculées et
conservées, aucune n'est privilégiée ici.
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from types import MappingProxyType

from mountain_perf.validation import (
    ContractError,
    require_all_finite,
    require_finite,
    require_immutable_sequence,
    require_increasing,
    require_min_length,
)

CLOCK_TOTALS_RELATIVE_TOLERANCE = 1e-9
"""Tolérance relative de l'identité ``M + S + U = E`` (``0010`` D5.2).

Rapportée à ``max(1, E)`` : une somme de 77 000 intervalles flottants s'écarte de
quelques ``1e−7`` s, et une tolérance absolue d'une microseconde serait insatisfiable
sur une course longue.
"""


class IntervalState(StrEnum):
    """État d'un intervalle élémentaire sous une convention (``0010`` D5.2).

    Champs
    ------
    Valeurs décrites dans ``INTERVAL_STATE_DESCRIPTIONS``.

    Invariants
    ----------
    Énumération fermée : chaque intervalle reçoit un seul état par convention.

    Producteur
    ----------
    La partition des horloges (``mountain_perf.backtest.clocks``).

    Consommateurs
    -------------
    ``ClockPartition`` ; les horloges cumulées et les épisodes d'arrêt (M4a) ;
    l'association arrêt → passage (M4a-3).

    Non promis
    ----------
    ``STOPPED`` n'est pas un arrêt physique prouvé : le détecteur n'est pas validé
    (``0010``, Conséquences).
    """

    MOVING = "moving"
    STOPPED = "stopped"
    UNDETERMINED = "undetermined"


INTERVAL_STATE_DESCRIPTIONS: Mapping[IntervalState, str] = MappingProxyType(
    {
        IntervalState.MOVING: "M — mouvement : fenêtre mobile.",
        IntervalState.STOPPED: (
            "S — arrêt : suite d'intervalles immobiles d'une durée au moins égale au "
            "seuil de la convention."
        ),
        IntervalState.UNDETERMINED: (
            "U — indéterminé : trou, fenêtre invalide ou indéterminée, ou immobilité "
            "trop courte."
        ),
    }
)


@dataclass(frozen=True)
class ClockConvention:
    """Seuils d'une convention de détection du mouvement ``θ = (h ; z ; c)``.

    Champs
    ------
    - ``max_horizontal_speed_ms`` — m/s — ``h``, vitesse horizontale maximale d'une
      fenêtre immobile.
    - ``max_vertical_speed_ms`` — m/s — ``z``, vitesse verticale maximale, en valeur
      absolue.
    - ``min_stop_s`` — secondes — ``c``, durée minimale d'une suite immobile pour
      qu'elle devienne un arrêt.

    Invariants
    ----------
    Les trois valeurs sont finies et ``> 0``.

    Producteur
    ----------
    ``CLOCK_CONVENTIONS``, fixé par ``0010`` D5.2.

    Consommateurs
    -------------
    La partition des horloges (M4a).

    Non promis
    ----------
    Aucune convention n'est calée ni validée sur des arrêts connus.
    """

    max_horizontal_speed_ms: float
    max_vertical_speed_ms: float
    min_stop_s: float

    def __post_init__(self) -> None:
        for name in ("max_horizontal_speed_ms", "max_vertical_speed_ms", "min_stop_s"):
            value: float = getattr(self, name)
            require_finite(value, name)
            if value <= 0:
                raise ContractError(f"{name} doit être > 0, reçu {value}.")


CLOCK_CONVENTIONS: tuple[ClockConvention, ...] = (
    ClockConvention(0.05, 0.015, 60.0),
    ClockConvention(0.10, 0.03, 60.0),
    ClockConvention(0.15, 0.045, 60.0),
    ClockConvention(0.10, 0.03, 30.0),
    ClockConvention(0.10, 0.03, 90.0),
)
"""Les cinq conventions de ``0010`` D5.2, **dans cet ordre** (m/s, m/s, s).

L'ordre départage les égalités de ``θ_bas`` et ``θ_haut`` (D5.4).
"""

CENTRAL_CONVENTION_INDEX = 1
"""Indice de la convention centrale ``θ_c = (0,10 ; 0,03 ; 60)`` (``0010`` D5.2)."""


class ClockKind(StrEnum):
    """Nature d'une horloge (``0010`` D5.4).

    Champs
    ------
    Valeurs décrites dans ``CLOCK_KIND_DESCRIPTIONS``.

    Invariants
    ----------
    Énumération fermée.

    Producteur
    ----------
    ``CLOCKS``.

    Consommateurs
    -------------
    ``clock_duration_s`` (M4a) ; les totaux sur support admis (M4a-2) ; les métriques
    (M4b).

    Non promis
    ----------
    Aucune horloge n'est la « bonne » : l'écoulé est la référence principale, les dix
    autres sont des scénarios.
    """

    ELAPSED = "elapsed"
    MOVING = "moving"
    MOVING_OR_UNDETERMINED = "moving_or_undetermined"


CLOCK_KIND_DESCRIPTIONS: Mapping[ClockKind, str] = MappingProxyType(
    {
        ClockKind.ELAPSED: "Écoulé : temps de montre, trous et arrêts compris.",
        ClockKind.MOVING: "M_θ : temps en mouvement sous une convention.",
        ClockKind.MOVING_OR_UNDETERMINED: (
            "M_θ + U_θ : temps en mouvement ou indéterminé sous une convention."
        ),
    }
)


@dataclass(frozen=True)
class Clock:
    """Une des onze horloges : nature et, hors écoulé, convention.

    Champs
    ------
    - ``kind`` — sans unité — écoulé, ``M_θ`` ou ``M_θ + U_θ``.
    - ``convention_index`` — sans unité — indice dans ``CLOCK_CONVENTIONS``.

    Invariants
    ----------
    ``convention_index`` vaut ``None`` si et seulement si ``kind`` est ``ELAPSED`` ;
    sinon il est dans ``[0, 4]``.

    Producteur
    ----------
    ``CLOCKS``.

    Consommateurs
    -------------
    ``clock_duration_s`` (M4a) ; le rapport (M4b).

    Non promis
    ----------
    Rien sur la valeur d'une horloge : elle dépend d'une partition.
    """

    kind: ClockKind
    convention_index: int | None = None

    def __post_init__(self) -> None:
        if self.kind is ClockKind.ELAPSED:
            if self.convention_index is not None:
                raise ContractError(
                    "convention_index doit être None pour l'écoulé, "
                    f"reçu {self.convention_index}."
                )
            return
        if self.convention_index is None or not (
            0 <= self.convention_index < len(CLOCK_CONVENTIONS)
        ):
            raise ContractError(
                f"convention_index doit être dans [0, {len(CLOCK_CONVENTIONS) - 1}] "
                f"pour {self.kind}, reçu {self.convention_index}."
            )


CLOCKS: tuple[Clock, ...] = (
    Clock(ClockKind.ELAPSED),
    *(Clock(ClockKind.MOVING, i) for i in range(len(CLOCK_CONVENTIONS))),
    *(
        Clock(ClockKind.MOVING_OR_UNDETERMINED, i)
        for i in range(len(CLOCK_CONVENTIONS))
    ),
)
"""Les onze horloges de ``0010`` D5.4 : écoulé, ``M_θ1…M_θ5``, ``(M+U)_θ1…(M+U)_θ5``."""


@dataclass(frozen=True)
class ClockPartition:
    """État de chaque intervalle élémentaire d'une trace, sous les cinq conventions.

    L'intervalle ``i`` est ``[time_s[i] ; time_s[i+1])`` ; ``states[k][i]`` est son
    état sous ``CLOCK_CONVENTIONS[k]``.

    Champs
    ------
    - ``time_s`` — secondes — instants des enregistrements, depuis le premier.
    - ``states`` — sans unité — un tuple d'états par convention.

    Invariants
    ----------
    - ``time_s`` et ``states`` (et chacun de ses éléments) sont des tuples ;
    - ``time_s`` : au moins 2 valeurs, finies, strictement croissantes, avec
      ``time_s[0] == 0`` (l'origine de ``0010`` D5.3, celle de ``RecordedTrace``) ;
    - ``len(states) == 5`` ;
    - chaque élément de ``states`` a ``len(time_s) − 1`` états.

    Producteur
    ----------
    ``clock_partition`` (``mountain_perf.backtest.clocks``).

    Consommateurs
    -------------
    Les horloges cumulées, les totaux et les épisodes d'arrêt (M4a) ; les totaux sur
    support admis (M4a-2) ; l'association arrêt → passage (M4a-3).

    Non promis
    ----------
    - les mesures de fenêtre (``v_h``, ``D_h``…) ne sont pas conservées ;
    - un état ``STOPPED`` n'est pas un arrêt physique prouvé (détecteur non validé,
      ``0010`` Conséquences) ;
    - la partition n'est pas recoupée avec une trace.
    """

    time_s: tuple[float, ...]
    states: tuple[tuple[IntervalState, ...], ...]

    def __post_init__(self) -> None:
        require_immutable_sequence(self.time_s, "time_s")
        require_min_length(self.time_s, 2, "time_s")
        require_all_finite(self.time_s, "time_s")
        if self.time_s[0] != 0:
            raise ContractError(f"time_s[0] doit valoir 0, reçu {self.time_s[0]}.")
        require_increasing(self.time_s, "time_s", strict=True)
        require_immutable_sequence(self.states, "states")
        if len(self.states) != len(CLOCK_CONVENTIONS):
            raise ContractError(
                f"states doit porter {len(CLOCK_CONVENTIONS)} conventions, "
                f"reçu {len(self.states)}."
            )
        for k, states in enumerate(self.states):
            require_immutable_sequence(states, f"states[{k}]")
            if len(states) != len(self.time_s) - 1:
                raise ContractError(
                    f"states[{k}] doit porter {len(self.time_s) - 1} états "
                    f"(un par intervalle), reçu {len(states)}."
                )


@dataclass(frozen=True)
class ClockTotals:
    """Totaux d'une trace sous une convention : écoulé, mouvement, arrêt, indéterminé.

    Champs
    ------
    - ``elapsed_s`` — secondes — écoulé ``E``, trous compris.
    - ``moving_s`` — secondes — ``M_θ``.
    - ``stopped_s`` — secondes — ``S_θ``.
    - ``undetermined_s`` — secondes — ``U_θ``.

    Invariants
    ----------
    - valeurs finies et ``>= 0`` ;
    - ``|M + S + U − E| <= 1e−9 · max(1, E)``.

    Producteur
    ----------
    ``trace_totals`` (``mountain_perf.backtest.clocks``), pour les totaux de la trace.

    Consommateurs
    -------------
    Le rapport (M4b), qui publie séparément les totaux de la trace et ceux du support
    admis (M4a-2).

    Non promis
    ----------
    Ce ne sont pas les totaux du support admis : les deux jeux ne se mélangent jamais
    (``0010`` D5.4).
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
class StopEpisode:
    """Suite maximale d'intervalles ``STOPPED`` sous une convention.

    Champs
    ------
    - ``start_s``, ``end_s`` — secondes depuis le premier enregistrement — bornes de
      l'épisode.
    - ``first_record``, ``last_record`` — sans unité — indices des enregistrements qui
      bornent l'épisode.

    Invariants
    ----------
    - ``start_s`` et ``end_s`` finis, ``0 <= start_s < end_s`` ;
    - ``0 <= first_record < last_record``.

    Producteur
    ----------
    ``stop_episodes`` (``mountain_perf.backtest.clocks``).

    Consommateurs
    -------------
    L'association arrêt → passage (M4a-3) ; le rapport (M4b).

    Non promis
    ----------
    - l'épisode n'est pas un arrêt physique prouvé ;
    - les bornes ne sont pas recoupées avec une partition.
    """

    start_s: float
    end_s: float
    first_record: int
    last_record: int

    def __post_init__(self) -> None:
        require_finite(self.start_s, "start_s")
        require_finite(self.end_s, "end_s")
        if self.start_s < 0:
            raise ContractError(f"start_s doit être >= 0, reçu {self.start_s}.")
        if self.start_s >= self.end_s:
            raise ContractError(
                f"start_s ({self.start_s}) doit précéder end_s ({self.end_s})."
            )
        if self.first_record < 0:
            raise ContractError(
                f"first_record doit être >= 0, reçu {self.first_record}."
            )
        if self.first_record >= self.last_record:
            raise ContractError(
                f"first_record ({self.first_record}) doit précéder "
                f"last_record ({self.last_record})."
            )
