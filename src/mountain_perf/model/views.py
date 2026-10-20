"""Ce que l'interface affiche d'une projection, calculé ici et non dans l'interface
(règle 7 de ``CLAUDE.md``).

Le tableau des passages, avec la vitesse et la montée horaire moyennes de chaque
tronçon et l'heure civile de chaque passage ; la vitesse projetée sur chaque intervalle
de la grille ; l'heure de départ civile d'une date et d'une heure saisies. Vitesses en
m/s, mises en forme à l'affichage (``docs/decisions/0002``).
"""

from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from typing import Final
from zoneinfo import ZoneInfo

from mountain_perf.model.engine import projected_timeline
from mountain_perf.schemas import PaceCurve, Projection, Segment

CIVIL_ZONE: Final = ZoneInfo("Europe/Paris")
"""Le fuseau des heures saisies et affichées : celui du calendrier du backtest
(``0010`` D2), défini ici parce que le modèle n'importe pas ``backtest/``."""


@dataclass(frozen=True)
class PassageRow:
    """Une ligne du tableau des passages de l'interface.

    - ``name``, ``distance_m``, ``elevation_m``, ``arrival_s`` — ceux du passage ;
    - ``clock_time`` — l'heure civile du passage, ``None`` sans heure de départ ;
    - ``segment`` — le tronçon **qui précède** le passage, ``None`` pour le départ ;
    - ``speed_ms`` — m/s — vitesse horizontale moyenne du tronçon ;
    - ``ascent_rate_ms`` — m/s — montée horaire moyenne du tronçon (son D+ sur sa
      durée).

    Les deux moyennes portent sur tout le tronçon : sur un tronçon qui monte puis
    descend, elles ne disent rien de ses pentes. ``None`` au départ et sur un tronçon
    de durée nulle (deux passages à la même abscisse).
    """

    name: str
    distance_m: float
    elevation_m: float
    arrival_s: float
    clock_time: datetime | None
    segment: Segment | None
    speed_ms: float | None
    ascent_rate_ms: float | None


def civil_start(day: date, at: time) -> datetime:
    """L'heure de départ civile, à Paris, d'une date et d'une heure saisies.

    Une heure ambiguë (passage à l'heure d'hiver) prend la première (``fold=0``) ; une
    heure qui n'existe pas (passage à l'heure d'été) est celle que ``zoneinfo`` lui
    donne, sans erreur.
    """
    return datetime.combine(day, at, tzinfo=CIVIL_ZONE)


def clock_time(start: datetime, elapsed_s: float) -> datetime:
    """L'heure civile, à Paris, ``elapsed_s`` secondes après ``start``.

    La durée s'ajoute en temps universel, jamais dans le fuseau : un départ la veille
    du passage à l'heure d'hiver garde ses heures justes. ``ValueError`` si ``start``
    ne porte pas de fuseau.
    """
    if start.utcoffset() is None:
        raise ValueError("L'heure de départ doit porter un fuseau.")
    return (start.astimezone(UTC) + timedelta(seconds=elapsed_s)).astimezone(CIVIL_ZONE)


def passage_rows(
    projection: Projection, start: datetime | None = None
) -> tuple[PassageRow, ...]:
    """Une ligne par passage de ``projection``, dans l'ordre ; l'heure de chaque
    passage si ``start`` est donné."""
    segments = projection.segments
    rows: list[PassageRow] = []
    for i, passage in enumerate(projection.passages):
        segment = segments[i - 1] if i > 0 else None
        speed_ms: float | None = None
        ascent_rate_ms: float | None = None
        if segment is not None and segment.duration_s > 0:
            speed_ms = segment.distance_m / segment.duration_s
            ascent_rate_ms = segment.ascent_m / segment.duration_s
        rows.append(
            PassageRow(
                name=passage.point.point.name,
                distance_m=passage.point.distance_m,
                elevation_m=passage.point.elevation_m,
                arrival_s=passage.arrival_s,
                clock_time=None
                if start is None
                else clock_time(start, passage.arrival_s),
                segment=segment,
                speed_ms=speed_ms,
                ascent_rate_ms=ascent_rate_ms,
            )
        )
    return tuple(rows)


def interval_speeds(projection: Projection, curve: PaceCurve) -> tuple[float, ...]:
    """La vitesse projetée (m/s) sur chaque intervalle de la grille du profil, à
    l'effort de la projection : une de moins que de points de grille."""
    timeline = projected_timeline(projection.profile, curve, projection.parameters)
    return tuple(1.0 / pace for pace in timeline.pace_s_per_m)
