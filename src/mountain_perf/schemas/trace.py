"""Contrat de la trace réalisée lue, sans rien de dérivé (M4a, ``0010`` D4.4)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from mountain_perf.schemas.common import (
    ELEVATION_RANGE_M,
    LATITUDE_RANGE_DEG,
    LONGITUDE_RANGE_DEG,
    SourceRef,
)
from mountain_perf.validation import (
    ContractError,
    require_all_finite,
    require_all_in_range,
    require_aware,
    require_immutable_sequence,
    require_increasing,
    require_min_length,
    require_same_length,
)


@dataclass(frozen=True)
class RecordedTrace:
    """Trace réalisée d'une sortie, telle que lue, enregistrements dans l'ordre.

    Tableaux parallèles : l'enregistrement ``i`` est à l'instant
    ``start_time + time_s[i]``, en ``(latitude_deg[i], longitude_deg[i],
    elevation_m[i])``.

    Champs
    ------
    - ``start_time`` — instant — premier enregistrement, *aware*, stocké en UTC.
    - ``time_s`` — secondes — temps depuis ``start_time``.
    - ``latitude_deg``, ``longitude_deg`` — degrés — positions brutes WGS84.
    - ``elevation_m`` — mètres — altitudes brutes.
    - ``sources`` — sans unité — un fichier par tronçon, dans l'ordre de
      concaténation.
    - ``dropped_same_instant_count`` — sans unité — enregistrements écartés parce
      qu'ils répétaient l'instant du dernier conservé.

    Propriétés calculées (jamais stockées) : ``end_time`` et ``elapsed_s`` (l'écoulé
    ``E`` de ``0010`` D5.1, trous compris).

    Invariants
    ----------
    - ``start_time`` porte un fuseau ; il est normalisé en UTC ;
    - les quatre tableaux et ``sources`` sont des tuples ;
    - les quatre tableaux ont la même longueur, au moins 2 enregistrements ;
    - valeurs finies ; coordonnées et altitudes dans leurs plages ;
    - ``time_s[0] == 0`` et ``time_s`` strictement croissant ;
    - au moins une source ;
    - ``dropped_same_instant_count >= 0``.

    Producteur
    ----------
    ``read_trace`` (``mountain_perf.gpx.trace_reader``).

    Consommateurs
    -------------
    Le manifeste (M4a) ; les séries dérivées et les horloges (M4a) ; l'appariement
    (M4a-2).

    Non promis
    ----------
    - l'échantillonnage est irrégulier ;
    - **aucune position n'est dédoublonnée** : les enregistrements immobiles restent ;
    - aucun lissage, aucun bloc, aucun trou détecté : ce sont des séries dérivées ;
    - ce n'est pas un ``TrackPointStream``, qui décrit un flux Garmin (M6b) ;
    - les tableaux ne sont pas copiés ; ils sont exigés immuables.
    """

    start_time: datetime
    time_s: tuple[float, ...]
    latitude_deg: tuple[float, ...]
    longitude_deg: tuple[float, ...]
    elevation_m: tuple[float, ...]
    sources: tuple[SourceRef, ...]
    dropped_same_instant_count: int

    def __post_init__(self) -> None:
        require_aware(self.start_time, "start_time")
        object.__setattr__(self, "start_time", self.start_time.astimezone(UTC))
        arrays = {
            "time_s": self.time_s,
            "latitude_deg": self.latitude_deg,
            "longitude_deg": self.longitude_deg,
            "elevation_m": self.elevation_m,
        }
        for name, array in arrays.items():
            require_immutable_sequence(array, name)
        require_same_length(**arrays)
        require_min_length(self.time_s, 2, "time_s")
        for name, array in arrays.items():
            require_all_finite(array, name)
        if self.time_s[0] != 0:
            raise ContractError(f"time_s[0] doit valoir 0, reçu {self.time_s[0]}.")
        require_increasing(self.time_s, "time_s", strict=True)
        require_all_in_range(self.latitude_deg, *LATITUDE_RANGE_DEG, "latitude_deg")
        require_all_in_range(self.longitude_deg, *LONGITUDE_RANGE_DEG, "longitude_deg")
        require_all_in_range(self.elevation_m, *ELEVATION_RANGE_M, "elevation_m")
        require_immutable_sequence(self.sources, "sources")
        require_min_length(self.sources, 1, "sources")
        if self.dropped_same_instant_count < 0:
            raise ContractError(
                "dropped_same_instant_count doit être >= 0, "
                f"reçu {self.dropped_same_instant_count}."
            )

    @property
    def end_time(self) -> datetime:
        """Instant du dernier enregistrement, en UTC."""
        return self.start_time + timedelta(seconds=self.time_s[-1])

    @property
    def elapsed_s(self) -> float:
        """Écoulé ``E`` (secondes) : ``time_s[-1]``, trous compris (``0010`` D5.1)."""
        return self.time_s[-1]
