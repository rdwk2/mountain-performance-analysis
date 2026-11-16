"""Les sorties des profils de démo (M5-3) : la simulation d'une sortie à 1 Hz, le
calendrier d'un personnage, l'export Garmin (index, FIT, instant d'acquisition) et les
préparés du dossier.

Le hasard vient d'un seul flux, ``random.Random(graine du personnage)``, créé une fois
par :func:`write_export` et tiré dans l'ordre des numéros de sortie ; dans une sortie,
le facteur du jour, puis un bruit d'altitude par enregistrement (D8). Le générateur ne
lit jamais l'horloge : T0 lui est donné.
"""

import io
import json
import random
import zipfile
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Final
from zoneinfo import ZoneInfo

from mountain_perf.demo.constantes import (
    ACQUISITION_HOUR,
    ALTITUDE_NOISE_M,
    HR_BASE,
    HR_LAG_S,
    HR_PER_GRADE,
    HR_REST,
    ID_BASE,
    LOAD_PER_MINUTE,
    OUTING_FACTOR_MIN,
    OUTING_FACTOR_SPAN,
    OUTING_START_HOUR,
    REDUCED_HISTORY_DAYS,
    REDUCED_LAPS,
    STOP_EVERY,
    STOP_S,
)
from mountain_perf.demo.fit import FitRecord, fit_activity_bytes
from mountain_perf.demo.gpx import write_route_gpx, write_trace_gpx
from mountain_perf.demo.parcours import (
    ROUTES,
    Route,
    altitude_at,
    climb_m,
    grade_at,
    length_m,
    route,
    to_lat_lon,
    xy_at,
)
from mountain_perf.demo.personnages import Character, true_speed_ms

PARIS: Final = ZoneInfo("Europe/Paris")
"""Le fuseau des dates des profils de démo."""

EXPORT_NAME: Final = "demo"
"""Le dossier de l'export Garmin sous ``raw/garmin/``."""

ACTIVITY_TYPE: Final = "trail_running"
"""Le type Garmin des sorties (``activityType.typeKey``)."""

ZIP_DATE_TIME: Final = (2001, 1, 1, 0, 0, 0)
"""La date fixe des membres des archives : des octets qui ne dépendent pas de
l'heure."""

_TIME_FORMAT = "%Y-%m-%d %H:%M:%S"


@dataclass(frozen=True)
class Outing:
    """Une sortie simulée : son départ (UTC), ses enregistrements, la durée de son arrêt
    (secondes à vitesse nulle, ``STOP_S`` ou 0) et son facteur du jour."""

    start: datetime
    records: tuple[FitRecord, ...]
    stop_s: int
    factor: float


def simulate(
    person: Character,
    loop: Route,
    laps: int,
    *,
    start: datetime,
    stop: bool,
    rng: random.Random,
) -> Outing:
    """Une trace à 1 Hz sur ``laps`` tours de la boucle ``loop``, dans l'ordre du § 6.2
    (b) du brief : le facteur du jour ; à chaque seconde, l'enregistrement (position du
    tour courant, altitude bruitée, FC, distance, vitesse) ; la vitesse vraie fois le
    facteur, nulle pendant l'arrêt (``STOP_S`` secondes dès que la distance atteint la
    moitié d'un tour) ; la FC qui rejoint sa cible avec un retard de ``HR_LAG_S`` ; la
    distance avancée, bornée au total ; la trace finit au total."""
    factor = OUTING_FACTOR_MIN + OUTING_FACTOR_SPAN * rng.random()
    total = length_m(loop)
    goal = laps * total
    s = 0.0
    hr = HR_REST
    lap = 0
    stop_start: int | None = None
    records: list[FitRecord] = []
    t = 0
    while True:
        while lap < laps - 1 and s >= (lap + 1) * total:
            lap += 1
        sigma = s - lap * total
        grade = grade_at(loop, sigma)
        if stop and stop_start is None and s >= total / 2:
            stop_start = t
        stopped = stop_start is not None and t < stop_start + STOP_S
        speed = 0.0 if stopped else true_speed_ms(person, grade) * factor
        lat, lon = to_lat_lon(*xy_at(loop, sigma))
        altitude = altitude_at(loop, sigma) + ALTITUDE_NOISE_M * (rng.random() - 0.5)
        records.append(FitRecord(t, lat, lon, altitude, hr, s, speed))
        if s >= goal:
            break
        target = HR_REST if stopped else HR_BASE + HR_PER_GRADE * max(grade, 0.0)
        hr = hr + (target - hr) / HR_LAG_S
        s = min(goal, s + speed)
        t += 1
    return Outing(start, tuple(records), STOP_S if stop else 0, factor)


@dataclass(frozen=True)
class PlannedOuting:
    """Une sortie du calendrier : son numéro (1, 2, …), son jour, sa boucle, ses tours,
    et si elle s'arrête."""

    number: int
    day: date
    loop: str
    laps: int
    stop: bool


def history_days(person: Character, *, reduced: bool = False) -> int:
    """La longueur de l'historique du personnage, en jours ; en version réduite, au
    plus ``REDUCED_HISTORY_DAYS``."""
    if reduced:
        return min(person.history_days, REDUCED_HISTORY_DAYS)
    return person.history_days


def plan(
    person: Character, t0: date, *, reduced: bool = False
) -> tuple[PlannedOuting, ...]:
    """Les sorties du personnage, de ``T0 − historique`` (k = 0) à ``T0 − 1`` : un jour
    de sortie quand ``k`` modulo le cycle est l'un de ses restes ; la n-ième sortie
    prend la ``n mod len(week)``-ième entrée du cycle. En version réduite, l'historique
    est borné et chaque sortie fait ``REDUCED_LAPS`` tour."""
    days = history_days(person, reduced=reduced)
    first = t0 - timedelta(days=days)
    outings: list[PlannedOuting] = []
    for k in range(days):
        if k % person.cycle_days not in person.outing_days:
            continue
        loop, laps = person.week[len(outings) % len(person.week)]
        number = len(outings) + 1
        outings.append(
            PlannedOuting(
                number,
                first + timedelta(days=k),
                loop,
                REDUCED_LAPS if reduced else laps,
                number % STOP_EVERY == 0,
            )
        )
    return tuple(outings)


@dataclass(frozen=True)
class ExportSummary:
    """Ce que :func:`write_export` a écrit : le nombre de sorties, le premier et le
    dernier jour de l'historique (T0 − 1), la trace témoin."""

    outings: int
    first_day: date
    last_day: date
    witness: Path


def export_dir(folder: Path) -> Path:
    """Le dossier de l'export Garmin du dossier de démo ``folder``."""
    return folder / "raw" / "garmin" / EXPORT_NAME


def write_acquisition(folder: Path, t0: date) -> None:
    """``acquisition.json`` de l'export : T0 à ``ACQUISITION_HOUR`` à Paris, après la
    dernière sortie et le jour local de T0."""
    moment = datetime(t0.year, t0.month, t0.day, ACQUISITION_HOUR, tzinfo=PARIS)
    path = export_dir(folder) / "acquisition.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(json.dumps({"retrieved_at": moment.isoformat()}).encode("utf-8"))


def _archive(member: str, data: bytes) -> bytes:
    """Un zip non compressé à un membre, aux métadonnées fixes."""
    info = zipfile.ZipInfo(member, date_time=ZIP_DATE_TIME)
    info.compress_type = zipfile.ZIP_STORED
    info.create_system = 0
    info.external_attr = 0
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_STORED) as archive:
        archive.writestr(info, data)
    return buffer.getvalue()


def _laps_text(laps: int) -> str:
    return f"{laps} tour" if laps == 1 else f"{laps} tours"


def write_export(
    person: Character, folder: Path, t0: date, *, reduced: bool = False
) -> ExportSummary:
    """L'export Garmin du personnage sous ``folder/raw/garmin/demo/`` : l'instant
    d'acquisition, une archive FIT par sortie, l'index ; et la trace témoin sous
    ``folder/sorties/``, la dernière sortie d'un tour sur la boucle témoin."""
    planned = plan(person, t0, reduced=reduced)
    export = export_dir(folder)
    (export / "activity_fit").mkdir(parents=True, exist_ok=True)
    (export / "activities").mkdir(parents=True, exist_ok=True)
    write_acquisition(folder, t0)
    rng = random.Random(person.seed)
    entries: list[dict[str, object]] = []
    witness: tuple[PlannedOuting, Outing] | None = None
    for item in planned:
        loop = route(item.loop)
        local = datetime(
            item.day.year,
            item.day.month,
            item.day.day,
            OUTING_START_HOUR,
            tzinfo=PARIS,
        )
        start = local.astimezone(UTC)
        outing = simulate(person, loop, item.laps, start=start, stop=item.stop, rng=rng)
        elapsed = outing.records[-1].elapsed_s
        distance = item.laps * length_m(loop)
        identifier = ID_BASE * (person.rank + 1) + item.number
        data = fit_activity_bytes(
            start, outing.records, timer_s=elapsed, distance_m=distance
        )
        (export / "activity_fit" / f"{identifier}.zip").write_bytes(
            _archive(f"{identifier}_ACTIVITY.fit", data)
        )
        rates = [round(record.heart_rate) for record in outing.records]
        climb = item.laps * climb_m(loop)
        load = (
            None
            if item.number == len(planned) - 1
            else round(elapsed / 60 * LOAD_PER_MINUTE, 1)
        )
        entries.append(
            {
                "activityId": identifier,
                "activityName": f"{item.loop}, {_laps_text(item.laps)}",
                "activityType": {"typeKey": ACTIVITY_TYPE},
                "startTimeLocal": local.strftime(_TIME_FORMAT),
                "startTimeGMT": start.strftime(_TIME_FORMAT),
                "elapsedDuration": round(float(elapsed), 1),
                "movingDuration": round(float(elapsed - outing.stop_s), 1),
                "distance": round(distance, 1),
                "elevationGain": round(climb, 1),
                "elevationLoss": round(climb, 1),
                "averageHR": round(sum(rates) / len(rates), 1),
                "maxHR": float(max(rates)),
                "activityTrainingLoad": load,
            }
        )
        if item.loop == person.witness_loop and item.laps == 1:
            witness = (item, outing)
    (export / "activities" / "activities.json").write_bytes(
        json.dumps(entries, ensure_ascii=False, indent=1).encode("utf-8")
    )
    if witness is None:
        raise ValueError(f"aucune sortie d'un tour sur {person.witness_loop}")
    item, outing = witness
    traces = folder / "sorties"
    traces.mkdir(parents=True, exist_ok=True)
    path = traces / f"sortie_{item.day.isoformat()}_{item.loop}.gpx"
    write_trace_gpx(outing, path)
    return ExportSummary(
        len(planned),
        t0 - timedelta(days=history_days(person, reduced=reduced)),
        t0 - timedelta(days=1),
        path,
    )


def write_routes(folder: Path) -> None:
    """Les six préparés sous ``folder/routes/<nom>.gpx``, les mêmes pour tous."""
    routes = folder / "routes"
    routes.mkdir(parents=True, exist_ok=True)
    for found in ROUTES:
        write_route_gpx(found, routes / f"{found.name}.gpx")
