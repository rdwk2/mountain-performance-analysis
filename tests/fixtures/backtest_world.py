"""Monde synthétique de ``mperf backtest`` (M4b-5) — inventé de bout en bout.

``write_world(root)`` écrit dans ``root`` un manifeste (``manifeste.json``) et ses
fichiers GPX ; ``run_world(root)`` l'exécute (commit, instants et registre fixés). La
courbe est celle des fixtures commitées (``COURBE``). Domaine à partir du
2026-06-01 ; athlète ``athlete-1``. Les sorties, par jour :

- ``a-2026-05-28`` (parcours ``a``, non tracée) : hors domaine par la date ;
  ``velo-2026-05-30`` (VTT, avant le domaine) : par le sport, d'abord ;
  ``trail-2026-05-31`` (à pied, non tracée, sans référence, avant le domaine) : par la
  date, avant le D+/km inconnu ;
- le jeu de **répétabilité** : ``a`` les 3, 6 (arrêt de 150 s dans la descente
  roulante ; puis ``velo-2026-06-06``, VTT de 4 h 30, non retenue), 10 (trou
  d'enregistrement de 90 s) et 12 juin ; ``b`` les 4, 8 et 12 juin — le 12, un jour de
  trois sorties (``a``, ``b`` et ``libre-2026-06-12``, de développement) ;
  ``autre-2026-06-05`` : un autre athlète ; ``velo-2026-06-09`` : VTT retenu, hors
  domaine ; ``plat-2026-06-11`` : hors domaine par son D+/km ;
- le jeu de **développement** : la course ``a-2026-06-14`` ; ``libre-2026-06-15``,
  sans référence, en deux tronçons ; ``c-2026-06-16``, trace sans horodatage
  (refusée, dans le domaine par son tracé) ; ``x-2026-06-18``, trace sans point
  (refusée, D+/km inconnu) ; ``a-2026-06-20``, non tracée, dans le domaine par sa
  référence ;
- le jeu de **confirmation** : ``b-2026-06-25``, ``a-2026-06-27``.

Parcours ``a`` : préparé à trois lieux nommés, montée, plat, descente roulante,
descente raide, montée ; son dernier segment de 10 m tombe dans les 15 dernières
secondes des traces (temps nul sous les ``M θ``). Parcours ``b`` : sa référence est la
trace de ``b-2026-06-08`` (désignée) ; montée, plat, descente roulante puis raide.

Positions sur l'équateur (``equatorial_deg`` de ``traces.py``), altitudes et instants
par additions et multiplications seulement — aucun ``sin``, ``exp`` ni ``log`` : les
octets écrits sont les mêmes sous Windows et sous Linux (leçon de la PR #18). Chaque
itinéraire va vers l'est depuis son origine ``(x0, y0)``, en tronçons de pente
constante ; l'« athlète » y court à une vitesse fixée par tronçon, multipliée par le
facteur du jour.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

from fixtures.traces import equatorial_deg
from mountain_perf.backtest import BacktestRun, prepare_backtest, run_backtest

FIXTURES = Path(__file__).parent
COURBE = FIXTURES / "courbe_synthetique.csv"
"""La courbe de l'exécution (``--curve``), commitée avec son compagnon."""

ATHLETE = "athlete-1"
DOMAIN_START = "2026-06-01"
RECORD_STEP_S = 5
"""Pas d'enregistrement des traces, en secondes."""
REFERENCE_STEP_M = 25
"""Pas des points d'un préparé, en mètres."""
ELEVATION_OFFSET_M = 3.0
"""Les traces enregistrent l'altitude du tracé plus 3 m."""
LATERAL_OFFSET_M = 1.0
"""En mouvement, les enregistrements alternent à ±1 m du tracé (une trace un peu plus
longue que sa référence) ; à l'arrêt, ils restent sur place."""


@dataclass(frozen=True)
class Leg:
    """Un tronçon : longueur, pente, vitesse de l'athlète au facteur 1."""

    length_m: int
    grade: float
    speed_ms: float


@dataclass(frozen=True)
class Itinerary:
    """Un itinéraire vers l'est depuis ``(x0, y0)``, et ses lieux nommés à leur
    distance du départ."""

    x0_m: float
    y0_m: float
    start_elevation_m: float
    legs: tuple[Leg, ...]
    places: tuple[tuple[str, int], ...] = ()

    @property
    def length_m(self) -> int:
        return sum(leg.length_m for leg in self.legs)

    def leg_at(self, s_m: float) -> tuple[Leg, int, float]:
        """Le tronçon qui porte ``s``, sa distance et son altitude de départ."""
        start, elevation = 0, self.start_elevation_m
        for leg in self.legs[:-1]:
            if s_m < start + leg.length_m:
                return leg, start, elevation
            start += leg.length_m
            elevation += leg.grade * leg.length_m
        return self.legs[-1], start, elevation

    def elevation_m(self, s_m: float) -> float:
        leg, start, elevation = self.leg_at(s_m)
        return elevation + leg.grade * (s_m - start)

    def position_deg(self, s_m: float, offset_m: float = 0.0) -> tuple[float, float]:
        return equatorial_deg(self.x0_m + s_m, self.y0_m + offset_m)


ROUTE_A = Itinerary(
    x0_m=0.0,
    y0_m=0.0,
    start_elevation_m=1500.0,
    legs=(
        Leg(1100, 0.15, 1.30),
        Leg(500, 0.0, 3.10),
        Leg(1000, -0.10, 2.60),
        Leg(1000, -0.20, 1.90),
        Leg(660, 0.12, 1.45),
    ),
    places=(("Col", 1100), ("Pont", 2100), ("Source", 3600)),
)
"""Le parcours ``a`` : montée, plat, descente roulante, descente raide, montée ;
4 260 m : son dernier segment de 10 m tombe dans les 15 dernières secondes des traces
(temps nul sous les ``M θ``, comme Q1 sur le réel)."""

ROUTE_B = Itinerary(
    x0_m=0.0,
    y0_m=5000.0,
    start_elevation_m=1200.0,
    legs=(
        Leg(1250, 0.14, 1.35),
        Leg(750, 0.0, 3.00),
        Leg(1000, -0.08, 2.70),
        Leg(560, -0.18, 2.00),
    ),
)
"""Le parcours ``b`` : montée, plat, descente roulante puis raide ; sa référence est
une trace."""

FREE = Itinerary(
    x0_m=0.0,
    y0_m=10000.0,
    start_elevation_m=900.0,
    legs=(Leg(1000, 0.14, 1.35), Leg(1000, -0.14, 2.10), Leg(560, 0.0, 3.00)),
)
"""Une sortie sans parcours (``libre-2026-06-15``)."""

REFUSED = Itinerary(x0_m=0.0, y0_m=12000.0, start_elevation_m=900.0, legs=FREE.legs)
"""La sortie à trace refusée (``c-2026-06-16``) : son fichier n'a aucun horodatage."""

FLAT = Itinerary(
    x0_m=0.0, y0_m=15000.0, start_elevation_m=400.0, legs=(Leg(2000, 0.005, 3.20),)
)
"""La sortie de plat (``plat-2026-06-11``) : hors domaine."""


@dataclass(frozen=True)
class Recording:
    """Une trace à écrire : son itinéraire, son départ, le facteur du jour, un arrêt
    ``(distance, durée)``, un trou d'enregistrement ``[début ; fin[`` en secondes, et
    l'instant qui la coupe en deux tronçons (deux fichiers, ``_1`` et ``_2``)."""

    file: str
    itinerary: Itinerary
    start: datetime
    factor: float
    stop: tuple[int, int] | None = None
    gap_s: tuple[int, int] | None = None
    split_s: int | None = None

    @property
    def files(self) -> tuple[str, ...]:
        if self.split_s is None:
            return (self.file,)
        stem = self.file.removesuffix(".gpx")
        return (f"{stem}_1.gpx", f"{stem}_2.gpx")


def _utc(text: str) -> datetime:
    return datetime.fromisoformat(text).astimezone(UTC)


RECORDINGS = (
    Recording("gpx/a/a03.gpx", ROUTE_A, _utc("2026-06-03T08:00:00+02:00"), 1.00),
    Recording(
        "gpx/a/a06.gpx",
        ROUTE_A,
        _utc("2026-06-06T08:00:00+02:00"),
        0.96,
        stop=(2000, 150),
    ),
    Recording(
        "gpx/a/a10.gpx",
        ROUTE_A,
        _utc("2026-06-10T08:00:00+02:00"),
        1.03,
        gap_s=(1500, 1590),
    ),
    Recording("gpx/a/a12.gpx", ROUTE_A, _utc("2026-06-12T07:00:00+02:00"), 0.98),
    Recording("gpx/a/a14.gpx", ROUTE_A, _utc("2026-06-14T09:00:00+02:00"), 1.12),
    Recording("gpx/a/a27.gpx", ROUTE_A, _utc("2026-06-27T08:00:00+02:00"), 1.05),
    Recording("gpx/b/b04.gpx", ROUTE_B, _utc("2026-06-04T18:00:00+02:00"), 1.00),
    Recording("gpx/b/b08.gpx", ROUTE_B, _utc("2026-06-08T18:00:00+02:00"), 1.04),
    Recording("gpx/b/b12.gpx", ROUTE_B, _utc("2026-06-12T17:00:00+02:00"), 0.97),
    Recording("gpx/libre/libre12.gpx", FREE, _utc("2026-06-12T19:00:00+02:00"), 1.02),
    Recording("gpx/b/b25.gpx", ROUTE_B, _utc("2026-06-25T18:00:00+02:00"), 1.06),
    Recording(
        "gpx/libre/libre15.gpx",
        FREE,
        _utc("2026-06-15T08:00:00+02:00"),
        1.00,
        split_s=600,
    ),
    Recording("gpx/libre/plat11.gpx", FLAT, _utc("2026-06-11T08:00:00+02:00"), 1.00),
)


def _breakpoints(recording: Recording) -> list[tuple[float, float]]:
    """``(t, s)`` : l'instant d'arrivée à chaque mètre, et la fin de l'arrêt."""
    itinerary = recording.itinerary
    points = [(0.0, 0.0)]
    t = 0.0
    for i in range(itinerary.length_m):
        if recording.stop is not None and recording.stop[0] == i:
            t += recording.stop[1]
            points.append((t, float(i)))
        leg, _, _ = itinerary.leg_at(i + 0.5)
        t += 1.0 / (leg.speed_ms * recording.factor)
        points.append((t, float(i + 1)))
    return points


def _distance_at(
    points: list[tuple[float, float]], t: float, index: int
) -> tuple[float, int]:
    """``s(t)`` par interpolation linéaire, en avançant depuis ``index``."""
    while index + 1 < len(points) and points[index + 1][0] <= t:
        index += 1
    if index + 1 == len(points):
        return points[-1][1], index
    (t0, s0), (t1, s1) = points[index], points[index + 1]
    return s0 + (s1 - s0) * (t - t0) / (t1 - t0), index


def _document(waypoints: list[str], trackpoints: list[str], name: str) -> str:
    return "\n".join(
        [
            '<?xml version="1.0" encoding="UTF-8"?>',
            "<!-- Synthétique : monde de mperf backtest (M4b-5). -->",
            '<gpx version="1.1" creator="synthetic-tests" '
            'xmlns="http://www.topografix.com/GPX/1/1">',
            *waypoints,
            f"  <trk><name>{name}</name><trkseg>",
            *trackpoints,
            "  </trkseg></trk>",
            "</gpx>",
            "",
        ]
    )


def _trkpt(lat: float, lon: float, elevation: float, time: str | None) -> str:
    stamp = f"<time>{time}</time>" if time is not None else ""
    return (
        f'    <trkpt lat="{lat!r}" lon="{lon!r}"><ele>{elevation!r}</ele>{stamp}'
        "</trkpt>"
    )


def recorded_gpx(recording: Recording) -> tuple[str, ...]:
    """La trace : un enregistrement toutes les ``RECORD_STEP_S`` secondes jusqu'à
    l'arrivée, sauf dans le trou ; ±1 m du tracé en mouvement, sur place à l'arrêt ;
    un document par tronçon."""
    itinerary = recording.itinerary
    points = _breakpoints(recording)
    end_s = points[-1][0]
    parts: list[list[str]] = [[]]
    index, previous_s, offset, k = 0, -1.0, LATERAL_OFFSET_M, 0
    while True:
        t = k * RECORD_STEP_S
        s, index = _distance_at(points, float(t), index)
        k += 1
        if recording.split_s is not None and t == recording.split_s:
            parts.append([])
        gap = recording.gap_s
        if gap is None or not gap[0] <= t < gap[1]:
            if s != previous_s:
                offset = -offset
            lat, lon = itinerary.position_deg(s, offset)
            stamp = recording.start + timedelta(seconds=t)
            parts[-1].append(
                _trkpt(
                    lat,
                    lon,
                    itinerary.elevation_m(s) + ELEVATION_OFFSET_M,
                    stamp.strftime("%Y-%m-%dT%H:%M:%SZ"),
                )
            )
        previous_s = s
        if t >= end_s:
            return tuple(_document([], lines, "Trace synthétique") for lines in parts)


def prepared_gpx(itinerary: Itinerary) -> str:
    """Le préparé : un point tous les ``REFERENCE_STEP_M`` mètres et à l'arrivée, sur le
    tracé, sans horodatage, et ses lieux nommés."""
    waypoints = []
    for name, s in itinerary.places:
        lat, lon = itinerary.position_deg(float(s))
        elevation = itinerary.elevation_m(float(s))
        waypoints.append(
            f'  <wpt lat="{lat!r}" lon="{lon!r}"><ele>{elevation!r}</ele>'
            f"<name>{name}</name></wpt>"
        )
    trackpoints = []
    for s in (*range(0, itinerary.length_m, REFERENCE_STEP_M), itinerary.length_m):
        lat, lon = itinerary.position_deg(float(s))
        trackpoints.append(_trkpt(lat, lon, itinerary.elevation_m(float(s)), None))
    return _document(waypoints, trackpoints, "Préparé synthétique")


def untimed_gpx(itinerary: Itinerary) -> str:
    """Une trace sans horodatage (refusée par ``read_trace``, lisible par
    ``read_gpx``) : un point tous les 10 m et à l'arrivée."""
    trackpoints = []
    for s in (*range(0, itinerary.length_m, 10), itinerary.length_m):
        lat, lon = itinerary.position_deg(float(s))
        trackpoints.append(
            _trkpt(lat, lon, itinerary.elevation_m(float(s)) + ELEVATION_OFFSET_M, None)
        )
    return _document([], trackpoints, "Trace sans horodatage")


def _end_text(recording: Recording) -> str:
    """L'instant du dernier enregistrement d'une trace, en UTC."""
    end_s = _breakpoints(recording)[-1][0]
    last = -(-end_s // RECORD_STEP_S) * RECORD_STEP_S
    return (recording.start + timedelta(seconds=last)).isoformat()


def manifest() -> dict[str, object]:
    """Le manifeste du monde, au format v1 de M4a."""
    b08 = next(r for r in RECORDINGS if r.file == "gpx/b/b08.gpx")
    reference_a = {
        "file": "gpx/a/prepare.gpx",
        "kind": "prepared",
        "available_at": "2026-05-25T20:00:00+02:00",
    }
    reference_b = {
        "file": "gpx/b/b08.gpx",
        "kind": "designated_trace",
        "available_at": _end_text(b08),
    }

    def traced(outing_id: str, file: str, **fields: object) -> dict[str, object]:
        return {"id": outing_id, "sport": "foot", "traces": [{"file": file}], **fields}

    def on_a(
        outing_id: str, file: str, dataset: str, label: str = "training"
    ) -> dict[str, object]:
        return traced(
            outing_id,
            file,
            route="a",
            reference=reference_a,
            dataset=dataset,
            label=label,
        )

    def on_b(outing_id: str, file: str, dataset: str) -> dict[str, object]:
        return traced(
            outing_id,
            file,
            route="b",
            reference=reference_b,
            dataset=dataset,
            label="training",
        )

    outings: list[dict[str, object]] = [
        {
            "id": "a-2026-05-28",
            "sport": "foot",
            "start": "2026-05-28T08:00:00+02:00",
            "end": "2026-05-28T08:45:00+02:00",
            "route": "a",
            "reference": reference_a,
            "dataset": "development",
            "label": "training",
        },
        {
            "id": "velo-2026-05-30",
            "sport": "mtb",
            "start": "2026-05-30T09:00:00+02:00",
            "end": "2026-05-30T10:00:00+02:00",
        },
        {
            "id": "trail-2026-05-31",
            "sport": "foot",
            "start": "2026-05-31T09:00:00+02:00",
            "end": "2026-05-31T10:00:00+02:00",
        },
        on_a("a-2026-06-03", "gpx/a/a03.gpx", "repeatability"),
        on_b("b-2026-06-04", "gpx/b/b04.gpx", "repeatability"),
        {
            "id": "autre-2026-06-05",
            "athlete_ref": "athlete-2",
            "sport": "foot",
            "start": "2026-06-05T08:00:00+02:00",
            "end": "2026-06-05T09:00:00+02:00",
        },
        on_a("a-2026-06-06", "gpx/a/a06.gpx", "repeatability"),
        {
            "id": "velo-2026-06-06",
            "sport": "mtb",
            "start": "2026-06-06T14:00:00+02:00",
            "end": "2026-06-06T18:30:00+02:00",
        },
        on_b("b-2026-06-08", "gpx/b/b08.gpx", "repeatability"),
        {
            "id": "velo-2026-06-09",
            "sport": "mtb",
            "start": "2026-06-09T17:00:00+02:00",
            "end": "2026-06-09T18:00:00+02:00",
        },
        on_a("a-2026-06-10", "gpx/a/a10.gpx", "repeatability"),
        traced("plat-2026-06-11", "gpx/libre/plat11.gpx", label="training"),
        on_a("a-2026-06-12", "gpx/a/a12.gpx", "repeatability"),
        on_b("b-2026-06-12", "gpx/b/b12.gpx", "repeatability"),
        traced(
            "libre-2026-06-12",
            "gpx/libre/libre12.gpx",
            dataset="development",
            label="training",
        ),
        on_a("a-2026-06-14", "gpx/a/a14.gpx", "development", label="race"),
        {
            "id": "libre-2026-06-15",
            "sport": "foot",
            "traces": [
                {"file": "gpx/libre/libre15_1.gpx"},
                {"file": "gpx/libre/libre15_2.gpx"},
            ],
            "dataset": "development",
            "label": "training",
        },
        {
            "id": "c-2026-06-16",
            "sport": "foot",
            "traces": [{"file": "gpx/libre/c16.gpx"}],
            "start": "2026-06-16T08:00:00+02:00",
            "end": "2026-06-16T08:30:00+02:00",
            "dataset": "development",
            "label": "training",
        },
        {
            "id": "x-2026-06-18",
            "sport": "foot",
            "traces": [{"file": "gpx/libre/x18.gpx"}],
            "start": "2026-06-18T08:00:00+02:00",
            "end": "2026-06-18T08:40:00+02:00",
            "dataset": "development",
            "label": "training",
        },
        {
            "id": "a-2026-06-20",
            "sport": "foot",
            "start": "2026-06-20T08:00:00+02:00",
            "end": "2026-06-20T08:45:00+02:00",
            "route": "a",
            "reference": reference_a,
            "dataset": "development",
            "label": "training",
        },
        on_b("b-2026-06-25", "gpx/b/b25.gpx", "confirmation"),
        on_a("a-2026-06-27", "gpx/a/a27.gpx", "confirmation"),
    ]
    return {
        "schema_version": 1,
        "athlete_ref": ATHLETE,
        "domain_start_date": DOMAIN_START,
        "outings": outings,
    }


EMPTY_GPX = _document([], [], "Trace vide")
"""La trace de ``x-2026-06-18`` : un GPX sans aucun ``<trkpt>`` — refusée par
``read_trace``, et sans profil de domaine (``read_gpx`` la refuse aussi)."""


def write_world(root: Path) -> Path:
    """Écrit le monde dans ``root`` ; rend le chemin du manifeste."""
    files = {
        name: text
        for recording in RECORDINGS
        for name, text in zip(recording.files, recorded_gpx(recording), strict=True)
    }
    files["gpx/a/prepare.gpx"] = prepared_gpx(ROUTE_A)
    files["gpx/libre/c16.gpx"] = untimed_gpx(REFUSED)
    files["gpx/libre/x18.gpx"] = EMPTY_GPX
    for name, text in files.items():
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8", newline="\n")
    path = root / "manifeste.json"
    path.write_text(
        json.dumps(manifest(), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    return path


COMMIT = "0123456789abcdef0123456789abcdef01234567"
"""Le commit déclaré par les exécutions des tests (40 caractères hexadécimaux)."""
RETRIEVED_AT = datetime(2026, 10, 4, 12, 0, tzinfo=UTC)
"""L'instant de lecture du compagnon de la courbe (``curve_artifacts``)."""
RECORDED_AT = datetime(2026, 10, 4, 12, 30, tzinfo=UTC)
"""L'instant d'enregistrement des événements des exécutions des tests."""


def run_world(root: Path) -> BacktestRun:
    """Écrit le monde dans ``root / "monde"`` et l'exécute, registre dans
    ``root / "registre"``."""
    manifest = write_world(root / "monde")
    preparation = prepare_backtest(
        manifest, COURBE, commit=COMMIT, tree_modified=False, retrieved_at=RETRIEVED_AT
    )
    return run_backtest(preparation, root / "registre", recorded_at=RECORDED_AT)
