"""Contrats de l'activité : métadonnées d'une sortie et son flux point par point.

``Activity`` **référence** son flux (``stream_ref``) et ne le contient pas : lister deux
mille activités ne doit pas charger des gigaoctets.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timezone

from mountain_perf.schemas.common import (
    ELEVATION_RANGE_M,
    HEART_RATE_RANGE_BPM,
    LATITUDE_RANGE_DEG,
    LONGITUDE_RANGE_DEG,
    UTC_OFFSET_RANGE_S,
    QualityFlag,
    SourceRef,
    Sport,
)
from mountain_perf.validation import (
    ContractError,
    require_all_finite,
    require_all_in_range,
    require_aware,
    require_finite,
    require_immutable_sequence,
    require_in_range,
    require_increasing,
    require_min_length,
    require_non_empty,
    require_same_length,
)


@dataclass(frozen=True)
class Activity:
    """Métadonnées d'une sortie enregistrée.

    Champs
    ------
    - ``activity_ref`` — sans unité — identifiant stable de l'activité dans la source.
    - ``sport`` — sans unité — famille de modèle qui s'applique.
    - ``source_activity_type`` — sans unité — type d'activité de la source, tel quel
      (``activityType.typeKey`` de Garmin).
    - ``start_time`` — instant — départ, *aware*, **dans son fuseau local à décalage
      fixe** (pas en UTC).
    - ``elapsed_duration_s`` — secondes — temps écoulé, ``> 0``.
    - ``moving_duration_s`` — secondes — temps en mouvement, ``> 0``.
    - ``distance_m`` — mètres — distance de la source, ``>= 0``.
    - ``ascent_m``, ``descent_m`` — mètres — D+ et D− de la source, ``>= 0``.
    - ``average_hr_bpm``, ``max_hr_bpm`` — battements par minute — FC moyenne et
      maximale, ``[20, 250]``, si présentes.
    - ``stream_ref`` — sans unité — **référence** au flux (``TrackPointStream``),
      jamais le flux lui-même.
    - ``quality_flags`` — sans unité — suspicions ; vide par défaut.
    - ``source`` — sans unité — provenance.

    Propriété calculée (jamais stockée) : ``utc_offset_s``, le décalage porté par le
    fuseau de ``start_time``.

    **``start_time`` n'est pas normalisé en UTC**, contrairement à
    ``SourceRef.retrieved_at`` : son fuseau porte le décalage local, qui a un sens
    physique ici (chaleur, nuit). Règle générale : un instant dont l'heure locale a un
    sens physique se stocke dans son fuseau à décalage fixe, les autres en UTC
    (``docs/decisions/0006``). Le décalage n'est pas un champ parallèle : deux sources
    de vérité finiraient par diverger, et l'erreur d'une heure qui en résulte est
    silencieuse. Les comparaisons d'instants restent justes quel que soit le fuseau.

    Invariants
    ----------
    - ``activity_ref`` non vide ;
    - flottants finis ;
    - durées ``> 0`` et ``moving_duration_s <= elapsed_duration_s`` ;
    - ``distance_m``, ``ascent_m``, ``descent_m`` ``>= 0`` ;
    - FC dans ``[20, 250]`` si présentes, et ``average_hr_bpm <= max_hr_bpm`` si les
      deux le sont ;
    - ``start_time`` *aware*, et son décalage dans ``[-43200, 50400]`` secondes — ce
      qui attrape une confusion secondes / minutes / heures.

    **Les deux durées restent deux champs.** La vérité terrain est en temps écoulé ; si
    un seul chiffre portait à la fois « j'allais moins vite » et « je me suis arrêté
    plus longtemps », le backtest ne pourrait jamais dire laquelle des deux hypothèses
    était fausse. L'une se corrige par la physiologie, l'autre par la logistique : deux
    champs rendent le résidu attribuable.

    Producteur
    ----------
    L'ingestion (M6b). Le producteur **attache le fuseau local à l'instant**, et ne
    passe pas un instant en UTC nu : l'objet le prendrait pour une heure locale à
    UTC+0, sans rien lever.

    Consommateurs
    -------------
    L'estimation de courbe (M6b), qui filtre et sélectionne les activités.

    Non promis
    ----------
    - **le flux n'est pas contenu**, seulement référencé ; ``stream_ref`` peut être
      absent ;
    - ``distance_m`` est celle de la source, et **on ne sait pas encore si elle est 2D
      ou 3D** (à vérifier au M6b) : l'écart biaiserait la pente d'autant plus que la
      pente est forte ;
    - ``source_activity_type`` n'est pas normalisé. **``sport`` ne remplace pas ce
      filtre** (exclure le tapis, séparer marche et course) : il dit seulement quelle
      famille de modèle s'applique ;
    - ``utc_offset_s`` est le décalage administratif ; l'heure *solaire*, qui compte
      physiquement pour la chaleur et la nuit, en diffère de quelques dizaines de
      minutes sur les Alpes (``docs/decisions/0006``) ;
    - le fuseau d'origine de ``start_time`` n'est pas conservé : il est ramené à un
      fuseau à décalage fixe de même instant et de même heure murale ;
    - ``quality_flags`` vide ne garantit pas l'absence de défaut.
    """

    activity_ref: str
    sport: Sport
    source_activity_type: str | None
    start_time: datetime
    elapsed_duration_s: float
    moving_duration_s: float
    distance_m: float
    ascent_m: float
    descent_m: float
    average_hr_bpm: float | None
    max_hr_bpm: float | None
    stream_ref: str | None
    source: SourceRef
    quality_flags: frozenset[QualityFlag] = frozenset()

    def __post_init__(self) -> None:
        require_non_empty(self.activity_ref, "activity_ref")
        offset = require_aware(self.start_time, "start_time")
        require_in_range(
            offset.total_seconds(), *UTC_OFFSET_RANGE_S, "décalage de start_time (s)"
        )
        # Même instant, même heure murale : seul le fuseau devient à décalage fixe.
        object.__setattr__(
            self, "start_time", self.start_time.astimezone(timezone(offset))
        )
        for name in ("elapsed_duration_s", "moving_duration_s"):
            value: float = getattr(self, name)
            require_finite(value, name)
            if value <= 0:
                raise ContractError(f"{name} doit être > 0, reçu {value}.")
        if self.moving_duration_s > self.elapsed_duration_s:
            raise ContractError(
                f"moving_duration_s ({self.moving_duration_s}) doit être <= "
                f"elapsed_duration_s ({self.elapsed_duration_s})."
            )
        for name in ("distance_m", "ascent_m", "descent_m"):
            value = getattr(self, name)
            require_finite(value, name)
            if value < 0:
                raise ContractError(f"{name} doit être >= 0, reçu {value}.")
        for name in ("average_hr_bpm", "max_hr_bpm"):
            hr: float | None = getattr(self, name)
            if hr is not None:
                require_finite(hr, name)
                require_in_range(hr, *HEART_RATE_RANGE_BPM, name)
        if (
            self.average_hr_bpm is not None
            and self.max_hr_bpm is not None
            and self.average_hr_bpm > self.max_hr_bpm
        ):
            raise ContractError(
                f"average_hr_bpm ({self.average_hr_bpm}) doit être <= "
                f"max_hr_bpm ({self.max_hr_bpm})."
            )

    @property
    def utc_offset_s(self) -> int:
        """Décalage local au départ (secondes), lu sur le fuseau de ``start_time``.

        L'heure locale est ``start_time`` lui-même. Décalage administratif : l'heure
        *solaire* en diffère de quelques dizaines de minutes sur les Alpes.
        """
        return int(require_aware(self.start_time, "start_time").total_seconds())


@dataclass(frozen=True)
class TrackPointStream:
    """Flux point par point d'une activité.

    Tableaux parallèles : le point ``i`` est ``time_s[i]`` et, pour chaque tableau
    présent, sa valeur d'indice ``i``.

    Champs
    ------
    - ``activity_ref`` — sans unité — l'``Activity`` à laquelle le flux appartient.
    - ``time_s`` — secondes — temps depuis le départ, ``>= 0``.
    - ``latitude_deg``, ``longitude_deg`` — degrés — WGS84, dans leurs plages.
    - ``elevation_m`` — mètres — altitudes, ``[-500, 9000]``.
    - ``distance_m`` — mètres — distance cumulée de la source.
    - ``speed_ms`` — m/s — vitesse mesurée par le capteur, ``>= 0``.
    - ``heart_rate_bpm`` — battements par minute — FC, ``[20, 250]``.
    - ``quality_flags`` — sans unité — suspicions ; vide par défaut.
    - ``source`` — sans unité — provenance.

    Tous les tableaux sauf ``time_s`` sont optionnels (``None`` = absent du flux).

    Invariants
    ----------
    - ``activity_ref`` non vide ;
    - tableaux en tuples, de même longueur que ``time_s``, valeurs finies ;
    - ``time_s`` : au moins 1 point, ``>= 0``, strictement croissant ;
    - ``distance_m`` **croissante au sens large** ;
    - ``speed_ms >= 0`` ; coordonnées, altitudes et FC dans leurs plages.

    **Un point suffit** là où ``Route`` et ``RouteProfile`` en exigent 2 : ceux-ci
    définissent une géométrie, qui n'existe pas en dessous de deux points ; un flux est
    un enregistrement, et un enregistrement d'un seul échantillon reste une mesure —
    c'est à l'estimation de décider s'il sert.

    Le sens large sur ``distance_m`` n'est pas un relâchement : **un coureur à l'arrêt
    ne progresse pas**, et le sens strict rejetterait toute activité comportant une
    pause. C'est le contraire du profil, strictement croissant parce que c'est une
    grille.

    ``speed_ms`` est **stocké et non dérivé** de ``distance_m`` et ``time_s`` : c'est
    une mesure indépendante du capteur, qui ne vaut pas exactement ``Δd/Δt``.

    Producteur
    ----------
    L'ingestion (M6b).

    Consommateurs
    -------------
    L'estimation de courbe (M6b).

    Non promis
    ----------
    - la régularité de l'échantillonnage ;
    - la présence d'un champ donné ;
    - ``time_s[0]`` n'est **pas** garanti nul ;
    - la correspondance entre ``distance_m`` et un recalcul depuis les positions ;
    - ``activity_ref`` n'est pas vérifié contre une ``Activity`` existante ;
    - les tableaux ne sont pas copiés ; ils sont exigés immuables.
    """

    activity_ref: str
    time_s: Sequence[float]
    latitude_deg: Sequence[float] | None
    longitude_deg: Sequence[float] | None
    elevation_m: Sequence[float] | None
    distance_m: Sequence[float] | None
    speed_ms: Sequence[float] | None
    heart_rate_bpm: Sequence[float] | None
    source: SourceRef
    quality_flags: frozenset[QualityFlag] = frozenset()

    def __post_init__(self) -> None:
        require_non_empty(self.activity_ref, "activity_ref")
        arrays = {
            name: array
            for name in (
                "time_s",
                "latitude_deg",
                "longitude_deg",
                "elevation_m",
                "distance_m",
                "speed_ms",
                "heart_rate_bpm",
            )
            if (array := getattr(self, name)) is not None
        }
        for name, array in arrays.items():
            require_immutable_sequence(array, name)
        require_same_length(**arrays)
        require_min_length(self.time_s, 1, "time_s")
        for name, array in arrays.items():
            require_all_finite(array, name)
        require_all_in_range(self.time_s, 0.0, float("inf"), "time_s")
        require_increasing(self.time_s, "time_s", strict=True)
        if self.distance_m is not None:
            require_increasing(self.distance_m, "distance_m", strict=False)
        if self.speed_ms is not None:
            require_all_in_range(self.speed_ms, 0.0, float("inf"), "speed_ms")
        ranges = {
            "latitude_deg": LATITUDE_RANGE_DEG,
            "longitude_deg": LONGITUDE_RANGE_DEG,
            "elevation_m": ELEVATION_RANGE_M,
            "heart_rate_bpm": HEART_RATE_RANGE_BPM,
        }
        for name, (low, high) in ranges.items():
            if name in arrays:
                require_all_in_range(arrays[name], low, high, name)
