"""Les vues du moteur sur ``interim/`` : ``Activity`` et ``TrackPointStream`` (M1b),
calculées à la lecture, jamais écrites (``docs/decisions/0013``, point 2).

Sans dépendance : le moteur obtient ses contrats sans fitdecode (``0011``).
"""

from dataclasses import dataclass
from itertools import pairwise

from mountain_perf.ingest.types import SOURCE_TYPE_SPORTS
from mountain_perf.schemas import (
    Activity,
    ActivityRecording,
    IndexedActivity,
    QualityFlag,
    TrackPointStream,
    ViewRefusal,
)
from mountain_perf.validation import ContractError

GPS_GAP_THRESHOLD_S = 10.0
"""Le seuil de ``GPS_GAP`` : deux instants consécutifs de la vue séparés de plus de
10 s. C'est le seuil du trou du moteur (``0010`` D4.4) : 10 s exactement n'est pas un
trou."""


@dataclass(frozen=True)
class ActivityView:
    """La vue ``Activity`` d'une entrée de l'index, ou le motif de son absence.

    Des deux champs, ``activity_view`` en remplit toujours exactement un :
    ``activity`` quand la vue existe, ``refusal`` sinon (la classe ne l'impose pas).
    """

    activity: Activity | None
    refusal: ViewRefusal | None


def activity_view(entry: IndexedActivity) -> ActivityView:
    """La vue ``Activity`` de ``entry``, une entrée de l'index.

    Refus, dans cet ordre : type de la source absent de ``SOURCE_TYPE_SPORTS``
    (``NO_SPORT``) ; un des champs ``elapsed_duration_s``, ``moving_duration_s``,
    ``distance_m``, ``ascent_m``, ``descent_m`` absent (``MISSING_FIELD``) ;
    ``Activity`` refuse les valeurs (``ContractError``, ``INVARIANT``). Sinon
    ``Activity`` avec l'identifiant, la famille de la table, le type de la source, le
    départ, les durées, distances et fréquences cardiaques recopiés de l'entrée ;
    ``stream_ref`` vaut l'identifiant si l'entrée a un enregistrement, ``None`` sinon ;
    ``source`` est celle de l'entrée, la provenance de l'export dont elle vient
    (AN2-0) ; aucun drapeau.
    """
    sport = SOURCE_TYPE_SPORTS.get(entry.source_activity_type)
    if sport is None:
        return ActivityView(None, ViewRefusal.NO_SPORT)
    elapsed = entry.elapsed_duration_s
    moving = entry.moving_duration_s
    distance = entry.distance_m
    ascent = entry.ascent_m
    descent = entry.descent_m
    if (
        elapsed is None
        or moving is None
        or distance is None
        or ascent is None
        or descent is None
    ):
        return ActivityView(None, ViewRefusal.MISSING_FIELD)
    try:
        activity = Activity(
            activity_ref=entry.activity_ref,
            sport=sport,
            source_activity_type=entry.source_activity_type,
            start_time=entry.start_time,
            elapsed_duration_s=elapsed,
            moving_duration_s=moving,
            distance_m=distance,
            ascent_m=ascent,
            descent_m=descent,
            average_hr_bpm=entry.average_hr_bpm,
            max_hr_bpm=entry.max_hr_bpm,
            stream_ref=entry.activity_ref if entry.has_recording else None,
            source=entry.source,
        )
    except ContractError:
        return ActivityView(None, ViewRefusal.INVARIANT)
    return ActivityView(activity, None)


@dataclass(frozen=True)
class StreamView:
    """La vue ``TrackPointStream`` d'un enregistrement, et ce qu'elle a laissé.

    - ``stream`` — la vue, ``None`` si l'enregistrement n'a pas de positions ou si aucun
      instant de positions n'a tous les canaux demandés ;
    - ``positions_without_requested`` — les instants de positions écartés faute d'une
      valeur d'un canal demandé au même instant.
    """

    stream: TrackPointStream | None
    positions_without_requested: int


def stream_view(
    recording: ActivityRecording,
    *,
    elevation: bool = False,
    distance: bool = False,
    heart_rate: bool = False,
    speed: bool = False,
) -> StreamView:
    """La vue ``TrackPointStream`` de ``recording``, aux seuls instants où les positions
    et chaque canal demandé ont une valeur.

    Sans canal des positions : ``StreamView(None, 0)``. Un instant de positions est
    gardé si chaque canal demandé a une valeur **au même instant** (égalité exacte des
    ``time_s``) ; un canal demandé absent de l'enregistrement n'en a aucune.
    ``positions_without_requested`` compte les instants de positions non gardés. Aucun
    instant gardé : ``stream`` vaut ``None``. Chaque canal non demandé est à ``None``
    dans la vue. ``quality_flags`` vaut ``{GPS_GAP}`` si deux instants consécutifs de la
    vue (après l'intersection) sont séparés de plus de ``GPS_GAP_THRESHOLD_S`` : les
    trous du canal des positions, et ceux que l'intersection crée. La vue ne lit ni
    ``start_time``, ni les sessions, ni les événements du chronomètre : un arrêt du
    chronomètre qui sépare deux instants de plus du seuil pose aussi le drapeau.

    Les ``time_s`` de la vue partent de ``ActivityRecording.start_time`` (le départ de
    la première session du FIT), pas de ``Activity.start_time``, qui vient de l'index.
    """
    position = recording.position
    if position is None:
        return StreamView(None, 0)
    requested: dict[str, dict[float, float]] = {}
    if elevation:
        channel = recording.elevation
        requested["elevation"] = (
            {}
            if channel is None
            else dict(zip(channel.time_s, channel.elevation_m, strict=True))
        )
    if distance:
        dist = recording.distance
        requested["distance"] = (
            {} if dist is None else dict(zip(dist.time_s, dist.distance_m, strict=True))
        )
    if heart_rate:
        hr = recording.heart_rate
        requested["heart_rate"] = (
            {} if hr is None else dict(zip(hr.time_s, hr.heart_rate_bpm, strict=True))
        )
    if speed:
        sp = recording.speed
        requested["speed"] = (
            {} if sp is None else dict(zip(sp.time_s, sp.speed_ms, strict=True))
        )
    kept = [
        i
        for i, t in enumerate(position.time_s)
        if all(t in values for values in requested.values())
    ]
    dropped = len(position.time_s) - len(kept)
    if not kept:
        return StreamView(None, dropped)
    time_s = tuple(position.time_s[i] for i in kept)

    def column(name: str) -> tuple[float, ...] | None:
        values = requested.get(name)
        return None if values is None else tuple(values[t] for t in time_s)

    gap = any(
        later - earlier > GPS_GAP_THRESHOLD_S for earlier, later in pairwise(time_s)
    )
    stream = TrackPointStream(
        activity_ref=recording.activity_ref,
        time_s=time_s,
        latitude_deg=tuple(position.latitude_deg[i] for i in kept),
        longitude_deg=tuple(position.longitude_deg[i] for i in kept),
        elevation_m=column("elevation"),
        distance_m=column("distance"),
        speed_ms=column("speed"),
        heart_rate_bpm=column("heart_rate"),
        source=recording.source,
        quality_flags=frozenset({QualityFlag.GPS_GAP}) if gap else frozenset(),
    )
    return StreamView(stream, dropped)
