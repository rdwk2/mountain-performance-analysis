"""Ce que l'athlète déclare pour les montées, dans ``MPA_DATA_DIR/athlete.toml``
(charte, § 3 ; ``docs/decisions/0014``). Le fichier est tenu à la main : la
bibliothèque le lit, ne l'écrit jamais. Seule sa table ``[analyse]`` est lue ici ;
les autres tables appartiennent à d'autres lecteurs.

```toml
[analyse]
reference_vertical_speed_m_per_h = 900
barometer_products = [{ manufacturer = "garmin", product = 1 }]
```

- ``reference_vertical_speed_m_per_h`` : ``V_ref``, la vitesse ascensionnelle de
  référence, déclarée et non calculée sur les données (exception à la charte, § 3) :
  elle fixe la frontière des régimes en gain, qui ne doit pas dépendre de la mesure.
  Absente : le défaut du projet. Lue en m/h, la grandeur du fichier, et rendue en m/s.
- ``barometer_products`` : les produits (fabricant et numéro de produit du FIT,
  jamais un numéro de série) qui portent un baromètre, pour les fichiers qui ne
  décrivent pas leurs capteurs internes.

Fichier absent, ou sans table ``[analyse]`` : les défauts. Une clé inconnue de la
table, ou une valeur hors de sa plage, est refusée (:class:`AthleteError`).
"""

from __future__ import annotations

import math
import tomllib
from dataclasses import dataclass
from pathlib import Path

from mountain_perf.analyse.quality import DEFAULT_REFERENCE_VERTICAL_SPEED_MS

ATHLETE_FILE = "athlete.toml"
"""Le nom du fichier, à la racine de ``MPA_DATA_DIR``."""

_SECTION = "analyse"
_KEYS = frozenset({"reference_vertical_speed_m_per_h", "barometer_products"})
_PRODUCT_KEYS = frozenset({"manufacturer", "product"})
_MIN_M_PER_H, _MAX_M_PER_H = 100.0, 5000.0


class AthleteError(ValueError):
    """``athlete.toml`` illisible, ou sa table ``[analyse]`` invalide."""


@dataclass(frozen=True)
class AthleteSettings:
    """Les déclarations de l'athlète pour les montées.

    - ``reference_vertical_speed_ms`` : ``V_ref``, en m/s ;
    - ``reference_vertical_speed_declared`` : vrai si le fichier la déclare ;
    - ``barometer_products`` : couples (fabricant, numéro de produit).
    """

    reference_vertical_speed_ms: float
    reference_vertical_speed_declared: bool
    barometer_products: frozenset[tuple[str, int]]

    def barometric(
        self, barometer: bool | None, manufacturer: str | None, product: int | None
    ) -> bool:
        """L'altitude d'un fichier vient-elle d'un baromètre ? Ce que le fichier dit
        de ses capteurs internes l'emporte ; s'il n'en dit rien, la déclaration de
        l'athlète ; sinon, non."""
        if barometer is not None:
            return barometer
        return (manufacturer, product) in self.barometer_products


DEFAULT_SETTINGS = AthleteSettings(
    DEFAULT_REFERENCE_VERTICAL_SPEED_MS, False, frozenset()
)
"""Les déclarations d'un athlète qui n'en fait aucune."""


def read_athlete(data_dir: Path) -> AthleteSettings:
    """Les déclarations de ``data_dir/athlete.toml`` ; les défauts s'il est absent."""
    path = data_dir / ATHLETE_FILE
    if not path.exists():
        return DEFAULT_SETTINGS
    try:
        with path.open("rb") as file:
            document = tomllib.load(file)
    except (OSError, UnicodeDecodeError, tomllib.TOMLDecodeError) as error:
        raise AthleteError(f"{ATHLETE_FILE} illisible : {error}") from error
    section = document.get(_SECTION)
    if section is None:
        return DEFAULT_SETTINGS
    if not isinstance(section, dict):
        raise AthleteError(f"[{_SECTION}] n'est pas une table")
    unknown = sorted(set(section) - _KEYS)
    if unknown:
        raise AthleteError(f"[{_SECTION}] : clés inconnues {unknown}")
    speed = DEFAULT_SETTINGS.reference_vertical_speed_ms
    declared = "reference_vertical_speed_m_per_h" in section
    if declared:
        value = section["reference_vertical_speed_m_per_h"]
        if (
            isinstance(value, bool)
            or not isinstance(value, int | float)
            or not math.isfinite(value)
            or not _MIN_M_PER_H <= value <= _MAX_M_PER_H
        ):
            raise AthleteError(
                "reference_vertical_speed_m_per_h : un nombre de "
                f"{_MIN_M_PER_H:g} à {_MAX_M_PER_H:g} m/h"
            )
        speed = float(value) / 3600.0
    entries = section.get("barometer_products", [])
    if not isinstance(entries, list):
        raise AthleteError("barometer_products : une liste de tables")
    products: set[tuple[str, int]] = set()
    for entry in entries:
        if not isinstance(entry, dict) or set(entry) != _PRODUCT_KEYS:
            raise AthleteError(
                "barometer_products : des tables { manufacturer, product }"
            )
        manufacturer, product = entry["manufacturer"], entry["product"]
        if (
            not isinstance(manufacturer, str)
            or not manufacturer
            or isinstance(product, bool)
            or not isinstance(product, int)
            or product < 0
        ):
            raise AthleteError(
                "barometer_products : un fabricant non vide et un numéro de produit"
                " entier positif ou nul"
            )
        products.add((manufacturer, product))
    return AthleteSettings(speed, declared, frozenset(products))
