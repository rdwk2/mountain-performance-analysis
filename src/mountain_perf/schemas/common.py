"""Contrats communs : sport, drapeaux de qualité, provenance, plages physiques.

Convention d'écriture des schémas (M1a, suivie par M1b) :

- ``@dataclass(frozen=True)``, sans ``slots`` (``docs/decisions/0007``) ;
- validation dans ``__post_init__``, exclusivement via ``mountain_perf.validation`` ;
- docstring de classe en cinq rubriques : Champs · Invariants · Producteur ·
  Consommateurs · Non promis. C'est la source unique du dictionnaire de données
  (``docs/DICTIONNAIRE_DONNEES.md``, généré par ``just dictionary``) ;
- les membres d'une énumération sont décrits dans un ``Mapping`` voisin, parce que
  Python ne conserve pas de docstring par membre.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from types import MappingProxyType

from mountain_perf.validation import (
    ContractError,
    require_aware,
    require_non_empty,
)

LATITUDE_RANGE_DEG: tuple[float, float] = (-90.0, 90.0)
"""Plage physique d'une latitude, en degrés."""

LONGITUDE_RANGE_DEG: tuple[float, float] = (-180.0, 180.0)
"""Plage physique d'une longitude, en degrés."""

ELEVATION_RANGE_M: tuple[float, float] = (-500.0, 9000.0)
"""Plage physique d'une altitude terrestre, en mètres (mer Morte → Everest, arrondi)."""


class Sport(StrEnum):
    """Famille de modèle de performance.

    Le critère de découpage est : **la même famille de modèle s'applique-t-elle ?**,
    c'est-à-dire ``v = f(pente) × modificateurs`` tient-il avec la même forme de
    ``f``. La marche et la course sont toutes deux ``FOOT`` : courbes différentes,
    même famille. Le ski de randonnée non : la descente n'est pas sur la même
    fonction et le rapport montée/descente est d'un ordre de grandeur.

    Une nouvelle valeur se justifie quand la *forme* du modèle change, pas quand
    l'activité change de nom. On ne déclare pas de valeur « au cas où ».

    Champs
    ------
    Valeurs décrites dans ``SPORT_DESCRIPTIONS``.

    Invariants
    ----------
    Énumération fermée ; une valeur inconnue n'existe pas.

    Producteur
    ----------
    L'ingestion (M6b) et le choix d'une courbe.

    Consommateurs
    -------------
    La sélection de courbe, à partir de l'intégration d'une deuxième courbe.

    Non promis
    ----------
    Rien ne lit ce champ avant la deuxième courbe. Aucun ``if sport == …`` n'est
    légitime de M2 à M5, sauf pour valider une cohérence (``docs/decisions/0003``).
    """

    FOOT = "foot"
    SKI_TOURING = "ski_touring"
    MTB = "mtb"


SPORT_DESCRIPTIONS: Mapping[Sport, str] = MappingProxyType(
    {
        Sport.FOOT: "Déplacement à pied : marche, randonnée, course, trail.",
        Sport.SKI_TOURING: "Ski de randonnée : montée en peaux, descente à ski.",
        Sport.MTB: "Vélo tout-terrain.",
    }
)


class QualityFlag(StrEnum):
    """Suspicion portée par un objet, sans l'empêcher d'exister.

    Politique de validation à deux niveaux — une décision de contrat, pas de style :

    - **invariant dur** : ``__post_init__`` lève ``ContractError``, l'objet n'existe
      pas (tableaux de longueurs différentes, altitude hors plage, ``datetime``
      naïf…) ;
    - **suspicion** : l'objet existe et porte un ``QualityFlag``. Rien n'est bloqué.

    Si tout levait, une seule activité avec un trou GPS ferait tomber toute
    l'estimation de courbe ; si rien ne levait, on la construirait sur des données
    pourries sans le savoir. **Le contrat est strict, l'ingestion est tolérante et
    tracée.**

    Champs
    ------
    Valeurs décrites dans ``QUALITY_FLAG_DESCRIPTIONS``.

    Invariants
    ----------
    Énumération fermée. Seules les valeurs dont l'usage est déjà prévu sont
    déclarées.

    Producteur
    ----------
    Les détecteurs de qualité de l'ingestion (M6b). Aucun détecteur n'existe en M1.

    Consommateurs
    -------------
    L'estimation de courbe (M6b), qui décide d'écarter ou de pondérer.

    Non promis
    ----------
    Aucun seuil ni méthode de détection : ils sont du M6b. L'absence de drapeau ne
    garantit pas l'absence de défaut, tant qu'aucun détecteur n'existe.
    """

    GPS_GAP = "gps_gap"
    ELEVATION_SPIKE = "elevation_spike"
    IMPLAUSIBLE_SPEED = "implausible_speed"


QUALITY_FLAG_DESCRIPTIONS: Mapping[QualityFlag, str] = MappingProxyType(
    {
        QualityFlag.GPS_GAP: (
            "Intervalle sans position enregistrée assez long pour rendre "
            "l'interpolation douteuse."
        ),
        QualityFlag.ELEVATION_SPIKE: (
            "Variation d'altitude entre deux points incompatible avec un "
            "déplacement à pied."
        ),
        QualityFlag.IMPLAUSIBLE_SPEED: (
            "Vitesse incompatible avec le sport et la pente."
        ),
    }
)


_SHA256_HEX = re.compile(r"[0-9a-f]{64}")
_PATH_SEPARATORS = ("/", "\\", ":")


@dataclass(frozen=True)
class SourceRef:
    """Provenance d'un objet venu de l'extérieur du programme.

    Champs
    ------
    - ``kind`` — sans unité — nature de la source : ``"gpx"``,
      ``"garmin_activity"``, ``"csv"``.
    - ``identifier`` — sans unité — **nom du fichier, jamais un chemin complet**.
    - ``content_hash`` — sans unité — ``sha256`` du contenu, 64 caractères
      hexadécimaux minuscules.
    - ``retrieved_at`` — instant — moment de l'acquisition, *aware*, stocké en UTC.

    Invariants
    ----------
    - ``kind`` et ``identifier`` non vides ;
    - ``identifier`` ne contient ni ``/``, ni ``\\``, ni ``:``, et n'est pas ``.``
      ou ``..`` : un chemin complet contient le nom de l'utilisateur, et ces objets
      finiront sérialisés puis cités. La règle 1 tient au niveau du type ;
    - ``content_hash`` est un ``sha256`` hexadécimal minuscule ;
    - ``retrieved_at`` porte un fuseau ; il est normalisé en UTC à la construction.

    Producteur
    ----------
    Les lecteurs de fichiers : GPX (M2), ingestion Garmin (M6b), CSV de référence (M4).

    Consommateurs
    -------------
    Tout objet dérivé qui recopie sa provenance (``RouteProfile``), et le backtest
    (M4), qui doit pouvoir dire sur quel fichier il a calibré et sur quel fichier il
    évalue.

    Non promis
    ----------
    - ``kind`` n'est pas une énumération fermée : aucun code ne doit en dépendre
      pour se brancher ;
    - ``identifier`` n'est pas unique : deux fichiers de même nom se distinguent par
      ``content_hash`` ;
    - le fuseau d'origine de ``retrieved_at`` n'est pas conservé.
    """

    kind: str
    identifier: str
    content_hash: str
    retrieved_at: datetime

    def __post_init__(self) -> None:
        require_non_empty(self.kind, "kind")
        require_non_empty(self.identifier, "identifier")
        # La valeur reçue n'est volontairement pas citée : un chemin personnel ne
        # doit pas entrer dans une trace d'exception.
        if any(sep in self.identifier for sep in _PATH_SEPARATORS):
            raise ContractError(
                "identifier doit être un nom de fichier, pas un chemin "
                "(séparateur trouvé)."
            )
        if self.identifier in (".", ".."):
            raise ContractError(
                "identifier doit être un nom de fichier, pas un chemin "
                "(« . » ou « .. »)."
            )
        if not _SHA256_HEX.fullmatch(self.content_hash):
            raise ContractError(
                "content_hash doit être un sha256 hexadécimal minuscule "
                f"(64 caractères), reçu {self.content_hash!r}."
            )
        require_aware(self.retrieved_at, "retrieved_at")
        object.__setattr__(self, "retrieved_at", self.retrieved_at.astimezone(UTC))
