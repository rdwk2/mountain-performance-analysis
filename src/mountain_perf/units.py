"""Unités : conversions aux frontières et formatage à l'affichage.

Règle du projet (``docs/decisions/0002-unites.md``) : la vitesse circule en
**m/s** partout dans le code. ``km/h`` sert à lire les fichiers de courbe,
``min/km`` et ``m/h`` (VAM) servent à afficher. Rien d'autre.

Conventions :

- ``grade`` est une fraction (``0.10`` pour 10 %), égale à Δaltitude / distance
  horizontale ; ``speed_ms`` est la vitesse horizontale.
- ``vertical_speed_ms = speed_ms × grade`` est **signée** : positive en montée,
  négative en descente. « VAM » n'est qu'une étiquette d'affichage du cas positif.

Règle de robustesse : **le calcul est strict, l'affichage ne plante jamais.**
Les fonctions de calcul lèvent ``ValueError`` sur une entrée sans sens physique ;
les fonctions ``format_*`` sont totales et renvoient un tiret à la place.
"""

import math

KMH_PER_MS = 3.6
"""1 m/s = 3,6 km/h."""

M_PER_KM = 1000.0
S_PER_H = 3600.0

UNDEFINED = "—"
"""Affiché quand la grandeur n'a pas de valeur (vitesse nulle, entrée non finie)."""


# ---------------------------------------------------------------------------
# Conversions (calcul : strict)
# ---------------------------------------------------------------------------


def kmh_to_ms(speed_kmh: float) -> float:
    """km/h → m/s. À utiliser à la lecture des fichiers, jamais dans un calcul."""
    return speed_kmh / KMH_PER_MS


def ms_to_kmh(speed_ms: float) -> float:
    """m/s → km/h. À utiliser à l'affichage ou au débogage."""
    return speed_ms * KMH_PER_MS


def pace_s_per_km(speed_ms: float) -> float:
    """Allure en secondes par kilomètre pour une vitesse strictement positive.

    Lève ``ValueError`` si ``speed_ms <= 0`` : l'allure d'un coureur immobile
    n'existe pas (elle diverge), et c'est précisément pour ça que l'allure n'est
    pas une unité de stockage.
    """
    if speed_ms <= 0:
        raise ValueError(
            f"L'allure n'est définie que pour une vitesse > 0, reçu {speed_ms} m/s."
        )
    return M_PER_KM / speed_ms


def speed_ms_from_pace(pace_s_per_km: float) -> float:
    """Inverse de :func:`pace_s_per_km`. Lève ``ValueError`` si l'allure est <= 0."""
    if pace_s_per_km <= 0:
        raise ValueError(f"Une allure doit être > 0 s/km, reçu {pace_s_per_km} s/km.")
    return M_PER_KM / pace_s_per_km


def vertical_speed_from_grade(speed_ms: float, grade: float) -> float:
    """Vitesse verticale signée (m/s) à partir de la vitesse horizontale et de la pente.

    ``grade`` = Δaltitude / distance horizontale. Le résultat est positif en
    montée, négatif en descente, nul à plat ou à l'arrêt.
    """
    return speed_ms * grade


# ---------------------------------------------------------------------------
# Formatage (affichage : total, ne lève jamais)
# ---------------------------------------------------------------------------


def format_pace(speed_ms: float) -> str:
    """``"5:42 /km"`` — secondes arrondies à l'entier, report sur les minutes.

    Renvoie :data:`UNDEFINED` si la vitesse est nulle, négative ou non finie.
    """
    if not math.isfinite(speed_ms) or speed_ms <= 0:
        return UNDEFINED
    total_s = round(pace_s_per_km(speed_ms))
    minutes, seconds = divmod(total_s, 60)
    return f"{minutes}:{seconds:02d} /km"


def format_duration(duration_s: float) -> str:
    """``"1:23:45"`` — heures sans zéro de tête, minutes et secondes sur deux chiffres.

    Au-delà de 24 h **les heures continuent** (``"29:03:07"``) : on ne passe pas en
    jours, parce qu'un temps de course se lit en heures et qu'une table de marche
    affichant « 1 j 5:03:07 » se compare mal d'une ligne à l'autre.

    Les secondes sont arrondies à l'entier, avec report : 3 599,6 s donne
    ``"1:00:00"`` et jamais ``"0:59:60"``. Renvoie :data:`UNDEFINED` si la durée est
    négative ou non finie — le formatage ne lève jamais.
    """
    if not math.isfinite(duration_s) or duration_s < 0:
        return UNDEFINED
    hours, rest_s = divmod(round(duration_s), 3600)
    minutes, seconds = divmod(rest_s, 60)
    return f"{hours}:{minutes:02d}:{seconds:02d}"


def format_vam(vertical_speed_ms: float) -> str:
    """``"620 m/h"`` — vitesse verticale en mètres par heure, arrondie à l'entier.

    La valeur est signée (``"-450 m/h"`` en descente). ``round`` renvoie un ``int``,
    qui n'a pas de zéro négatif : une valeur infime comme ``-1e-9`` donne bien
    ``"0 m/h"`` et jamais ``"-0 m/h"``. Renvoie :data:`UNDEFINED` si l'entrée
    n'est pas finie.
    """
    if not math.isfinite(vertical_speed_ms):
        return UNDEFINED
    vertical_speed_mh: int = round(vertical_speed_ms * S_PER_H)
    return f"{vertical_speed_mh} m/h"
