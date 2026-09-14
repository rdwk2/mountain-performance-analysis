"""Contrats de la vérité terrain : performances réelles chronométrées (M4).

Convention des temps de passage : ``docs/decisions/0005``.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date
from enum import StrEnum
from types import MappingProxyType

from mountain_perf.schemas.common import SourceRef
from mountain_perf.validation import (
    ContractError,
    require_finite,
    require_immutable_sequence,
    require_increasing,
    require_min_length,
    require_non_empty,
)


class TimingConvention(StrEnum):
    """Ce que mesure un temps de passage relevé : l'arrivée au point ou le départ.

    Champs
    ------
    Valeurs décrites dans ``TIMING_CONVENTION_DESCRIPTIONS``.

    Invariants
    ----------
    Énumération fermée. ``DEPARTURE`` est le défaut du projet ; ``UNKNOWN`` est une
    valeur honnête, pas une erreur.

    Producteur
    ----------
    La lecture des relevés de référence (M4), passage par passage.

    Consommateurs
    -------------
    L'appariement projection ↔ référence (M4), qui compare au ``departure_s`` ou à
    l'``arrival_s`` d'un ``Passage`` ; l'affichage et l'export (option ``ARRIVAL``).

    Non promis
    ----------
    Rien ne devine la convention d'un relevé : les relevés réels mélangent les deux
    sans le dire (``docs/PIEGES_DATA.md``). Faute d'information, c'est ``UNKNOWN``.
    """

    DEPARTURE = "departure"
    ARRIVAL = "arrival"
    UNKNOWN = "unknown"


TIMING_CONVENTION_DESCRIPTIONS: Mapping[TimingConvention, str] = MappingProxyType(
    {
        TimingConvention.DEPARTURE: (
            "Temps au départ du point — défaut du projet : raisonnement de course et "
            "barrières horaires."
        ),
        TimingConvention.ARRIVAL: "Temps à l'arrivée au point.",
        TimingConvention.UNKNOWN: "Convention non connue pour ce relevé.",
    }
)


@dataclass(frozen=True)
class ObservedPassage:
    """Temps de passage relevé à un point, lors d'une performance réelle.

    Champs
    ------
    - ``point_name`` — sans unité — nom du point tel que relevé.
    - ``elapsed_s`` — secondes — temps écoulé depuis le départ, ``>= 0``.
    - ``distance_m`` — mètres — abscisse du point sur le tracé, ``>= 0``, si le point
      a pu être situé.
    - ``convention`` — sans unité — ce que mesure ``elapsed_s`` : arrivée, départ, ou
      inconnu.

    Invariants
    ----------
    - ``point_name`` non vide ;
    - ``elapsed_s`` fini et ``>= 0`` ;
    - ``distance_m`` fini et ``>= 0`` si présent.

    Producteur
    ----------
    La lecture des relevés de référence (M4).

    Consommateurs
    -------------
    ``ReferencePerformance`` ; l'appariement et la métrique d'erreur (M4).

    Non promis
    ----------
    - ``point_name`` n'est pas garanti identique au nom d'un ``NamedPoint`` ;
    - ``distance_m`` n'est pas garanti sur la même grille ni le même tracé qu'un
      ``RouteProfile`` donné ;
    - la convention est portée **par passage** : deux passages d'une même performance
      peuvent en avoir deux différentes.
    """

    point_name: str
    elapsed_s: float
    distance_m: float | None
    convention: TimingConvention

    def __post_init__(self) -> None:
        require_non_empty(self.point_name, "point_name")
        require_finite(self.elapsed_s, "elapsed_s")
        if self.elapsed_s < 0:
            raise ContractError(f"elapsed_s doit être >= 0, reçu {self.elapsed_s}.")
        if self.distance_m is not None:
            require_finite(self.distance_m, "distance_m")
            if self.distance_m < 0:
                raise ContractError(
                    f"distance_m doit être >= 0, reçu {self.distance_m}."
                )


@dataclass(frozen=True)
class ReferencePerformance:
    """Performance réelle chronométrée : la vérité terrain du backtest.

    Champs
    ------
    - ``athlete_ref`` — sans unité — **pseudonyme** de l'athlète, jamais un nom réel.
    - ``event_name`` — sans unité — nom de l'épreuve ou de la sortie.
    - ``date`` — date civile — jour de la performance.
    - ``passages`` — sans unité — temps relevés, dans l'ordre du parcours.
    - ``source`` — sans unité — provenance du relevé.

    Invariants
    ----------
    - ``athlete_ref`` et ``event_name`` non vides ;
    - ``passages`` est un tuple d'au moins 2 passages ;
    - ``elapsed_s`` croissant au sens large le long de la liste.

    Producteur
    ----------
    La lecture des relevés de référence (M4).

    Consommateurs
    -------------
    Le backtest (M4).

    Non promis
    ----------
    - **l'appariement avec une projection n'est pas défini ici** : rapprocher un
      ``ObservedPassage`` d'un ``Passage`` — par nom, par abscisse, avec quelle
      tolérance — est du M4 ;
    - **seule une performance dont ``athlete_ref`` désigne l'athlète du projet peut
      être évaluée contre une projection.** Pour les autres coureurs il n'y a ni
      données d'entraînement, ni courbe, ni projection : comparer une projection issue
      de *sa* courbe au temps de *quelqu'un d'autre* ne produit pas un résultat faux,
      il en produit un dépourvu de sens — et qui ne se voit pas, noyé dans une erreur
      moyenne un peu plus grande. ``athlete_ref`` est un garde-fou, **pas** une gestion
      multi-athlètes, et rien ici ne vérifie qui il désigne ;
    - les données de population (plusieurs centaines de coureurs) ne sont **pas**
      modélisées : leur usage n'est pas défini ;
    - la monotonie de ``elapsed_s`` ne dit rien des conventions : un mélange
      ``ARRIVAL`` / ``DEPARTURE`` passe, et c'est voulu ;
    - l'ordre des ``distance_m`` n'est pas vérifié.
    """

    athlete_ref: str
    event_name: str
    date: date
    passages: tuple[ObservedPassage, ...]
    source: SourceRef

    def __post_init__(self) -> None:
        require_non_empty(self.athlete_ref, "athlete_ref")
        require_non_empty(self.event_name, "event_name")
        require_immutable_sequence(self.passages, "passages")
        require_min_length(self.passages, 2, "passages")
        require_increasing(
            tuple(passage.elapsed_s for passage in self.passages),
            "passages.elapsed_s",
            strict=False,
        )
