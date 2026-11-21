"""Le lecteur d'un export Strava, ``raw/strava/<export>/`` : l'archive que Strava envoie
(« Télécharger vos données »), telle quelle, et son ``acquisition.json`` (AN1-3,
``docs/decisions/0013``, précisions 25 et 26). N'ouvre dans le zip que
``activities.csv`` et les fichiers que sa colonne ``Filename`` nomme ; ne lit
d'``activities.csv`` que les colonnes dont les contrats ont besoin : ni nom, ni
description, ni note, ni matériel, ni météo (règle 1). N'importe ni ``fit`` ni
``export`` ; ne décode aucun FIT.
"""

import csv
import gzip
import hashlib
import io
import json
import math
import re
import zipfile
import zlib
from collections import Counter
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path
from types import TracebackType
from typing import Final, Self
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from mountain_perf.schemas import (
    HEART_RATE_RANGE_BPM,
    IndexedActivity,
    IndexField,
    RefusalReason,
    RefusedEntry,
    SourceRef,
    require_export_name,
)
from mountain_perf.validation import ContractError

STRAVA_DIR: Final = "strava"
"""Le dossier de ``raw/`` où se rangent les exports Strava, un par sous-dossier."""

ACQUISITION_FILE: Final = "acquisition.json"
"""Le fichier de ``raw/strava/<export>/`` qui porte l'instant d'acquisition : un objet
JSON aux clés ``retrieved_at`` et, facultative, ``timezone`` (un nom IANA)."""

INDEX_MEMBER: Final = "activities.csv"
"""Le membre de l'archive qui porte l'index des activités."""

REF_PREFIX: Final = "strava-"
"""Le préfixe de l'``activity_ref`` d'une entrée Strava : ``strava-<id>``."""

DEFAULT_TIMEZONE: Final = "Europe/Paris"
"""Le fuseau d'une entrée sans décalage lu d'un FIT, quand ``acquisition.json`` ne
nomme pas le sien (D8) ; compté dans ``SourcesReport.default_timezone_entries``."""

INDEX_KIND: Final = "strava_activities"
"""Le ``SourceRef.kind`` de l'index d'un export Strava."""

FIT_KIND: Final = "strava_fit"
"""Le ``SourceRef.kind`` d'un FIT d'un export Strava."""

FIT_SUFFIX: Final = ".fit.gz"
"""Le suffixe des fichiers d'activité dont l'enregistrement se lit (D2)."""

_COL_ID: Final = 0
_COL_DATE: Final = 1
_COL_TYPE: Final = 3
_COL_FILE: Final = 12
_COL_ELAPSED: Final = 15
_COL_MOVING: Final = 16
_COL_DISTANCE: Final = 17
_COL_ASCENT: Final = 20
_COL_DESCENT: Final = 21
_COL_MAX_HR: Final = 30
_COL_AVG_HR: Final = 31

STRAVA_HEADER: Final[tuple[str, ...]] = (
    "Activity ID",
    "Activity Date",
    "Activity Name",
    "Activity Type",
    "Activity Description",
    "Elapsed Time",
    "Distance",
    "Max Heart Rate",
    "Relative Effort",
    "Commute",
    "Activity Private Note",
    "Activity Gear",
    "Filename",
    "Athlete Weight",
    "Bike Weight",
    "Elapsed Time",
    "Moving Time",
    "Distance",
    "Max Speed",
    "Average Speed",
    "Elevation Gain",
    "Elevation Loss",
    "Elevation Low",
    "Elevation High",
    "Max Grade",
    "Average Grade",
    "Average Positive Grade",
    "Average Negative Grade",
    "Max Cadence",
    "Average Cadence",
    "Max Heart Rate",
    "Average Heart Rate",
    "Max Watts",
    "Average Watts",
    "Calories",
    "Max Temperature",
    "Average Temperature",
    "Relative Effort",
    "Total Work",
    "Number of Runs",
    "Uphill Time",
    "Downhill Time",
    "Other Time",
    "Perceived Exertion",
    "Type",
    "Start Time",
    "Weighted Average Power",
    "Power Count",
    "Prefer Perceived Exertion",
    "Perceived Relative Effort",
    "Commute",
    "Total Weight Lifted",
    "From Upload",
    "Grade Adjusted Distance",
    "Weather Observation Time",
    "Weather Condition",
    "Weather Temperature",
    "Apparent Temperature",
    "Dewpoint",
    "Humidity",
    "Weather Pressure",
    "Wind Speed",
    "Wind Gust",
    "Wind Bearing",
    "Precipitation Intensity",
    "Sunrise Time",
    "Sunset Time",
    "Moon Phase",
    "Bike",
    "Gear",
    "Precipitation Probability",
    "Precipitation Type",
    "Cloud Cover",
    "Weather Visibility",
    "UV Index",
    "Weather Ozone",
    "Jump Count",
    "Total Grit",
    "Average Flow",
    "Flagged",
    "Average Elapsed Speed",
    "Dirt Distance",
    "Newly Explored Distance",
    "Newly Explored Dirt Distance",
    "Activity Count",
    "Total Steps",
    "Carbon Saved",
    "Pool Length",
    "Training Load",
    "Intensity",
    "Average Grade Adjusted Pace",
    "Timer Time",
    "Total Cycles",
    "Recovery",
    "With Pet",
    "Competition",
    "Long Run",
    "For a Cause",
    "With Kid",
    "Downhill Distance",
    "Total Sets",
    "Total Reps",
    "Media",
    "Tag",
)
"""L'en-tête d'``activities.csv`` attendu, en entier : 104 noms dans l'ordre, dont cinq
en double (D10). Des noms de colonnes, pas des données."""

_INF = float("inf")

_NUMBER_COLUMNS: tuple[tuple[int, IndexField, float, float, bool], ...] = (
    (_COL_ELAPSED, IndexField.ELAPSED_DURATION, 0.0, _INF, False),
    (_COL_MOVING, IndexField.MOVING_DURATION, 0.0, _INF, True),
    (_COL_DISTANCE, IndexField.DISTANCE, 0.0, _INF, True),
    (_COL_ASCENT, IndexField.ASCENT, 0.0, _INF, True),
    (_COL_DESCENT, IndexField.DESCENT, 0.0, _INF, True),
    (_COL_AVG_HR, IndexField.AVERAGE_HR, *HEART_RATE_RANGE_BPM, True),
    (_COL_MAX_HR, IndexField.MAX_HR, *HEART_RATE_RANGE_BPM, True),
)
"""Rang, champ, plage, borne basse comprise (``Elapsed Time > 0``)."""

_DATE = re.compile(
    r"(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec) ([1-9]|[12][0-9]|3[01]), ([0-9]{4}), ([1-9]|1[0-2]):([0-5][0-9]):([0-5][0-9]) (AM|PM)"  # noqa: E501
)
"""``Activity Date`` : mois anglais, en UTC (C7) ; jamais ``strptime("%b")``, dont la
table des mois dépend de la locale du processus."""

_MONTHS: Final = {
    name: number
    for number, name in enumerate(
        (
            *("Jan", "Feb", "Mar", "Apr", "May", "Jun"),
            *("Jul", "Aug", "Sep", "Oct", "Nov", "Dec"),
        ),
        start=1,
    )
}

_ID = re.compile(r"[0-9]+")
_FILENAME = re.compile(r"activities/[0-9A-Za-z_.-]+")

_UNREADABLE_ZIP = (zipfile.BadZipFile, OSError, ValueError, EOFError)
"""Ce que lève l'ouverture d'une archive illisible."""

_UNREADABLE_MEMBER = (*_UNREADABLE_ZIP, NotImplementedError, RuntimeError, zlib.error)
"""Ce que lève la lecture d'un membre illisible (compression inconnue, contenu
chiffré, flux corrompu)."""

_NOT_GZIP = (OSError, EOFError, zlib.error, gzip.BadGzipFile)
"""Ce que lève ``gzip.decompress`` sur des octets qui ne sont pas un gzip."""

_BLOCK = 1 << 20


class StravaExportError(Exception):
    """L'export Strava ne se lit pas ; le message nomme le fichier (AN1-3)."""


@dataclass(frozen=True)
class StravaRow:
    """Une ligne gardée d'activities.csv."""

    activity_ref: str
    """« strava-<id> »."""
    source_activity_type: str
    start_utc: datetime
    """Le départ, *aware*, en UTC."""
    elapsed_duration_s: float | None
    moving_duration_s: float | None
    distance_m: float | None
    ascent_m: float | None
    descent_m: float | None
    average_hr_bpm: float | None
    max_hr_bpm: float | None
    omitted_fields: tuple[IndexField, ...]
    """Triés par valeur, comme pour Garmin."""
    filename: str | None
    """Le membre du zip, « activities/<nom> », ou ``None`` (vide, ou d'une autre
    forme)."""


@dataclass(frozen=True)
class StravaExport:
    """Un export Strava lu."""

    name: str
    retrieved_at: datetime
    """Tel que ``datetime.fromisoformat`` le lit."""
    timezone: str | None
    """La clé ``timezone`` d'``acquisition.json``, ou ``None``."""
    acquisition_hash: str
    archive: Path
    """Le zip."""
    archive_hash: str
    """SHA-256 des octets du zip."""
    index_source: SourceRef
    """(``INDEX_KIND``, ``"activities.csv"``, SHA-256 du membre, ``retrieved_at``)."""
    rows: tuple[StravaRow, ...]
    """Les lignes gardées, dans l'ordre du fichier."""
    refused: tuple[RefusedEntry, ...]
    """Par rang croissant (rang 0 : la première ligne après l'en-tête)."""
    named_files: int
    """Les lignes gardées dont ``filename`` n'est pas ``None``."""
    period_start: datetime | None
    """Le premier départ des lignes gardées, ou ``None``."""


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def strava_export_dirs(raw: Path) -> list[Path]:
    """Les dossiers d'exports Strava de ``raw`` (``data_dir/raw``) : les dossiers
    directs de ``raw/strava/``, par nom croissant ; ``raw/strava/`` absent : ``[]``.

    Lève ``StravaExportError`` : un fichier ``acquisition.json``, ou au suffixe ``.zip``
    (casse ignorée), directement dans ``raw/strava/`` (« raw/strava/<nom> : une archive
    Strava se range dans son dossier, raw/strava/<export>/ ; ranger celle-ci dans le
    sien. ») ; un nom de dossier que ``require_export_name`` refuse
    (« raw/strava/<nom>/ : le nom d'un export est fait de lettres et de chiffres ASCII,
    de « _ », « . » ou « - ». »)."""
    folder = raw / STRAVA_DIR
    if not folder.is_dir():
        return []
    paths = sorted(folder.iterdir(), key=lambda path: path.name)
    for path in paths:
        if path.is_file() and (
            path.name == ACQUISITION_FILE or path.name.lower().endswith(".zip")
        ):
            raise StravaExportError(
                f"raw/{STRAVA_DIR}/{path.name} : une archive Strava se range dans son "
                f"dossier, raw/{STRAVA_DIR}/<export>/ ; ranger celle-ci dans le sien."
            )
    dirs = [path for path in paths if path.is_dir()]
    for path in dirs:
        try:
            require_export_name(path.name)
        except ContractError:
            raise StravaExportError(
                f"raw/{STRAVA_DIR}/{path.name}/ : le nom d'un export est fait de "
                "lettres et de chiffres ASCII, de « _ », « . » ou « - »."
            ) from None
    return dirs


def _acquisition(export_dir: Path) -> tuple[datetime, str | None, bytes]:
    label = f"raw/{STRAVA_DIR}/{export_dir.name}/{ACQUISITION_FILE}"
    try:
        data = (export_dir / ACQUISITION_FILE).read_bytes()
    except FileNotFoundError:
        raise StravaExportError(
            f"{label} manque : chaque dossier de raw/{STRAVA_DIR}/ est un export, avec "
            "l'instant de son acquisition."
        ) from None
    try:
        content = json.loads(data.decode("utf-8-sig"))
    except ValueError:
        raise StravaExportError(f"{label} : JSON en UTF-8 attendu.") from None
    if not isinstance(content, dict) or set(content) not in (
        {"retrieved_at"},
        {"retrieved_at", "timezone"},
    ):
        raise StravaExportError(
            f"{label} : objet {{retrieved_at, timezone}} attendu (timezone facultatif)."
        )
    value = content["retrieved_at"]
    instant: datetime | None = None
    if isinstance(value, str):
        try:
            instant = datetime.fromisoformat(value)
        except ValueError:
            instant = None
    if instant is None or instant.utcoffset() is None:
        raise StravaExportError(
            f"{label} : retrieved_at doit être un instant ISO 8601 avec fuseau."
        )
    zone = content.get("timezone")
    if "timezone" in content:
        known = False
        if isinstance(zone, str):
            try:
                ZoneInfo(zone)
                known = True
            except (ValueError, ZoneInfoNotFoundError):
                known = False
        if not known:
            raise StravaExportError(
                f"{label} : timezone doit être un nom de fuseau IANA connu, par "
                "exemple « Europe/Paris »."
            )
    return instant, zone if isinstance(zone, str) else None, data


def _archive(export_dir: Path) -> Path:
    label = f"raw/{STRAVA_DIR}/{export_dir.name}"
    zips = sorted(
        (
            path
            for path in export_dir.iterdir()
            if path.is_file() and path.name.lower().endswith(".zip")
        ),
        key=lambda path: path.name,
    )
    if not zips:
        raise StravaExportError(
            f"{label}/ : aucune archive .zip ; l'archive de Strava se range telle "
            f"quelle à côté de {ACQUISITION_FILE}."
        )
    if len(zips) > 1:
        raise StravaExportError(
            f"{label}/ : plusieurs archives .zip ; un export Strava n'en a qu'une."
        )
    (path,) = zips
    if ":" in path.name or "\\" in path.name:
        raise StravaExportError(
            f"{label}/{path.name} : nom de fichier que le rapport ne peut pas porter "
            "(« : » ou « \\ »)."
        )
    return path


def _file_sha256(path: Path) -> str:
    """SHA-256 d'un fichier, lu par blocs : jamais le fichier entier en mémoire."""
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while block := stream.read(_BLOCK):
            digest.update(block)
    return digest.hexdigest()


def _index_text(path: Path, label: str) -> tuple[str, bytes]:
    """Le texte d'``activities.csv`` et ses octets ; seul ce membre est ouvert."""
    try:
        with zipfile.ZipFile(path) as archive:
            try:
                archive.getinfo(INDEX_MEMBER)
            except KeyError:
                raise StravaExportError(
                    f"{label} : {INDEX_MEMBER} manque dans l'archive."
                ) from None
            try:
                data = archive.read(INDEX_MEMBER)
            except _UNREADABLE_MEMBER:
                raise StravaExportError(
                    f"{label} : {INDEX_MEMBER} illisible dans l'archive."
                ) from None
    except _UNREADABLE_ZIP:
        raise StravaExportError(f"{label} : archive zip illisible.") from None
    try:
        return data.decode("utf-8-sig"), data
    except UnicodeDecodeError:
        raise StravaExportError(
            f"{label} : {INDEX_MEMBER} : texte en UTF-8 attendu."
        ) from None


def _header_difference(header: list[str]) -> int:
    """Le premier rang où ``header`` et ``STRAVA_HEADER`` diffèrent, ou la longueur de
    la plus courte si l'une prolonge l'autre."""
    for rank, (found, expected) in enumerate(zip(header, STRAVA_HEADER, strict=False)):
        if found != expected:
            return rank
    return min(len(header), len(STRAVA_HEADER))


def _check_header(rows: list[list[str]], label: str) -> None:
    """La première ligne doit être égale à ``STRAVA_HEADER`` (D10)."""
    header = rows[0] if rows else []
    if tuple(header) != STRAVA_HEADER:
        raise StravaExportError(
            f"{label} : l'en-tête d'activities.csv n'est pas celui qu'attend "
            f"l'ingestion ({len(header)} colonnes, {len(STRAVA_HEADER)} attendues ; "
            f"première différence à la colonne {_header_difference(header)}) : la "
            "forme de l'archive de Strava a changé."
        )


def _parse_date(text: str) -> datetime | None:
    """L'instant UTC d'``Activity Date`` (``Nov 20, 2026, 7:01:02 AM``), lu par
    ``_DATE`` sans la locale (C7) : ``12 AM`` → 0 h, ``12 PM`` → 12 h ; ``None`` pour
    un texte d'une autre forme ou une date impossible."""
    match = _DATE.fullmatch(text)
    if match is None:
        return None
    month, day, year, hour, minute, second, half = match.groups()
    hour_24 = int(hour) % 12 + (12 if half == "PM" else 0)
    try:
        return datetime(
            int(year),
            _MONTHS[month],
            int(day),
            hour_24,
            int(minute),
            int(second),
            tzinfo=UTC,
        )
    except ValueError:
        return None


def _filename(text: str) -> str | None:
    """Le membre que la ligne nomme : ``activities/<nom>`` ; vide ou d'une autre forme
    (``../x.fit.gz``, un chemin absolu, une contre-oblique) : ``None``."""
    return text if _FILENAME.fullmatch(text) else None


def _number(
    text: str, low: float, high: float, low_included: bool
) -> tuple[float | None, bool]:
    """``(valeur, omis)`` : ``(None, False)`` pour un texte vide ; un texte qui ne se
    lit pas en flottant, une valeur non finie ou hors plage est omise."""
    if text == "":
        return None, False
    try:
        number = float(text)
    except ValueError:
        return None, True
    if not math.isfinite(number):
        return None, True
    above_low = number >= low if low_included else number > low
    if not above_low or number > high:
        return None, True
    return number, False


def _row(fields: list[str], ref: str, kind: str, start: datetime) -> StravaRow:
    values: dict[IndexField, float | None] = {}
    omitted: list[IndexField] = []
    for column, field, low, high, low_included in _NUMBER_COLUMNS:
        number, is_omitted = _number(fields[column], low, high, low_included)
        values[field] = number
        if is_omitted:
            omitted.append(field)
    return StravaRow(
        activity_ref=ref,
        source_activity_type=kind,
        start_utc=start,
        elapsed_duration_s=values[IndexField.ELAPSED_DURATION],
        moving_duration_s=values[IndexField.MOVING_DURATION],
        distance_m=values[IndexField.DISTANCE],
        ascent_m=values[IndexField.ASCENT],
        descent_m=values[IndexField.DESCENT],
        average_hr_bpm=values[IndexField.AVERAGE_HR],
        max_hr_bpm=values[IndexField.MAX_HR],
        omitted_fields=tuple(sorted(omitted, key=lambda field: field.value)),
        filename=_filename(fields[_COL_FILE]),
    )


def _rows(
    body: list[list[str]],
) -> tuple[list[StravaRow], list[RefusedEntry]]:
    """Les lignes, dans cet ordre (précision 14) : l'identifiant ; un identifiant
    répété fait refuser toutes ses lignes ``DUPLICATE_ENTRY`` ; une ligne qui n'a pas
    104 colonnes, sans identifiant, sans type ou sans date lisible :
    ``UNUSABLE_ENTRY`` ; un ``Filename`` d'une autre forme qu'``activities/<nom>`` garde
    sa ligne, sans fichier ; les nombres (``_number``)."""
    ids = [
        fields[_COL_ID] if fields and _ID.fullmatch(fields[_COL_ID]) else None
        for fields in body
    ]
    counts = Counter(ident for ident in ids if ident is not None)
    rows: list[StravaRow] = []
    refused: list[RefusedEntry] = []
    for position, (fields, ident) in enumerate(zip(body, ids, strict=True)):
        if ident is not None and counts[ident] > 1:
            refused.append(RefusedEntry(position, RefusalReason.DUPLICATE_ENTRY))
            continue
        if ident is None or len(fields) != len(STRAVA_HEADER):
            refused.append(RefusedEntry(position, RefusalReason.UNUSABLE_ENTRY))
            continue
        kind = fields[_COL_TYPE]
        start = _parse_date(fields[_COL_DATE])
        if not kind.strip() or start is None:
            refused.append(RefusedEntry(position, RefusalReason.UNUSABLE_ENTRY))
            continue
        rows.append(_row(fields, REF_PREFIX + ident, kind, start))
    return rows, refused


def load_strava_export(export_dir: Path) -> StravaExport:
    """L'export Strava de ``export_dir`` (``raw/strava/<export>/``), dans cet ordre :
    ``acquisition.json`` ; l'unique zip du dossier (les autres fichiers et les
    sous-dossiers sont ignorés), son empreinte par blocs ; ``activities.csv`` dans
    l'archive, seul membre ouvert ; son en-tête, égal à ``STRAVA_HEADER`` ; ses
    lignes ; une ligne gardée partie après l'instant d'acquisition. Chaque refus lève
    ``StravaExportError``, au message qui nomme le fichier (``0013``, précision 25)."""
    name = export_dir.name
    retrieved_at, zone, acquisition = _acquisition(export_dir)
    path = _archive(export_dir)
    label = f"raw/{STRAVA_DIR}/{name}/{path.name}"
    archive_hash = _file_sha256(path)
    text, data = _index_text(path, label)
    table = list(csv.reader(io.StringIO(text, newline="")))
    _check_header(table, label)
    rows, refused = _rows(table[1:])
    if any(row.start_utc > retrieved_at for row in rows):
        raise StravaExportError(
            f"raw/{STRAVA_DIR}/{name}/ : une activité de l'index part après l'instant "
            f"d'acquisition de l'export ; {ACQUISITION_FILE} est faux."
        )
    return StravaExport(
        name=name,
        retrieved_at=retrieved_at,
        timezone=zone,
        acquisition_hash=_sha256(acquisition),
        archive=path,
        archive_hash=archive_hash,
        index_source=SourceRef(INDEX_KIND, INDEX_MEMBER, _sha256(data), retrieved_at),
        rows=tuple(rows),
        refused=tuple(refused),
        named_files=sum(row.filename is not None for row in rows),
        period_start=min((row.start_utc for row in rows), default=None),
    )


def strava_entry(
    row: StravaRow, export: StravaExport, offset_s: int | None
) -> tuple[IndexedActivity, bool]:
    """L'entrée d'index d'une ligne, et vrai si elle est datée par le fuseau par défaut.

    Le départ : ``row.start_utc`` dans le décalage ``offset_s`` (celui de son FIT,
    d'abord, D8) ; sans lui, dans le décalage, à l'instant du départ, du fuseau
    ``export.timezone``, ou de ``DEFAULT_TIMEZONE`` (alors daté par le défaut). Sans
    enregistrement ; ``elevation_corrected`` et ``training_load`` absents ; la source,
    ``export.index_source``."""
    if offset_s is not None:
        offset = timedelta(seconds=offset_s)
    else:
        zone = ZoneInfo(export.timezone or DEFAULT_TIMEZONE)
        found = row.start_utc.astimezone(zone).utcoffset()
        offset = timedelta(0) if found is None else found
    entry = IndexedActivity(
        activity_ref=row.activity_ref,
        source_activity_type=row.source_activity_type,
        start_time=row.start_utc.astimezone(timezone(offset)),
        elapsed_duration_s=row.elapsed_duration_s,
        moving_duration_s=row.moving_duration_s,
        distance_m=row.distance_m,
        ascent_m=row.ascent_m,
        descent_m=row.descent_m,
        elevation_corrected=None,
        average_hr_bpm=row.average_hr_bpm,
        max_hr_bpm=row.max_hr_bpm,
        training_load=None,
        has_recording=False,
        omitted_fields=row.omitted_fields,
        source=export.index_source,
    )
    return entry, offset_s is None and export.timezone is None


@dataclass(frozen=True)
class MemberAbsent:
    """Le membre est absent du zip, ou illisible."""


@dataclass(frozen=True)
class MemberNotGzip:
    """Le membre se lit, mais ne se décompresse pas en gzip."""

    raw: bytes


@dataclass(frozen=True)
class MemberFit:
    """Le membre, ses octets gzippés et décompressés."""

    raw: bytes
    fit: bytes


MemberRead = MemberAbsent | MemberNotGzip | MemberFit
"""Les trois issues de ``StravaMembers.read``."""


class StravaMembers:
    """Les membres d'un export Strava, le zip gardé ouvert
    (``with StravaMembers(export) as members``) ; n'ouvre que le membre demandé."""

    def __init__(self, export: StravaExport) -> None:
        self._path = export.archive
        self._archive: zipfile.ZipFile | None = None

    def __enter__(self) -> Self:
        self._archive = zipfile.ZipFile(self._path)
        return self

    def __exit__(
        self,
        kind: type[BaseException] | None,
        error: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        if self._archive is not None:
            self._archive.close()
            self._archive = None

    def read(self, filename: str) -> MemberRead:
        """Le membre ``filename`` : ``MemberAbsent`` (absent, ou illisible),
        ``MemberNotGzip`` (lu, pas un gzip), ``MemberFit``."""
        if self._archive is None:
            raise RuntimeError("StravaMembers.read hors de son bloc with.")
        try:
            raw = self._archive.read(filename)
        except KeyError:
            return MemberAbsent()
        except _UNREADABLE_MEMBER:
            return MemberAbsent()
        try:
            fit = gzip.decompress(raw)
        except _NOT_GZIP:
            return MemberNotGzip(raw)
        return MemberFit(raw, fit)
