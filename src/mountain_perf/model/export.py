"""L'export CSV des passages d'une projection, commun à ``mperf project --csv`` et à
l'interface (M3 ; déplacé en M5, sans changement de sortie)."""

import csv
from typing import TextIO

from mountain_perf.schemas import Projection

PASSAGE_CSV_HEADER = (
    "name",
    "distance_m",
    "elevation_m",
    "arrival_s",
    "departure_s",
    "moving_time_s",
    "segment_duration_s",
    "segment_distance_m",
    "segment_ascent_m",
    "segment_descent_m",
)
"""En-tête de l'export des passages. Les colonnes ``segment_*`` décrivent le tronçon
**qui précède** le passage ; elles sont vides sur la première ligne."""


def write_passages_csv(projection: Projection, stream: TextIO) -> None:
    """Écrit le tableau des passages, une ligne par passage.

    Les durées sont en secondes, brutes : ce tableau est fait pour être relu par un
    programme, ``format_duration`` ne sert qu'au rapport. Les colonnes ``segment_*``
    décrivent le tronçon **qui précède** le passage — ce ne sont donc pas des
    cumulés, et elles sont vides sur la première ligne, qui n'a rien avant elle.
    """
    writer = csv.writer(stream, lineterminator="\n")
    writer.writerow(PASSAGE_CSV_HEADER)
    segments = projection.segments
    for i, passage in enumerate(projection.passages):
        # Vides sur la première ligne : elle n'a aucun tronçon avant elle.
        before: tuple[str | float, ...] = ("", "", "", "")
        if i > 0:
            segment = segments[i - 1]
            before = (
                segment.duration_s,
                segment.distance_m,
                segment.ascent_m,
                segment.descent_m,
            )
        writer.writerow(
            (
                passage.point.point.name,
                passage.point.distance_m,
                passage.point.elevation_m,
                passage.arrival_s,
                passage.departure_s,
                passage.moving_time_s,
                *before,
            )
        )
