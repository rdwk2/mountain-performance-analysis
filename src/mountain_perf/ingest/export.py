"""L'ingestion des exports Garmin et des archives Strava : ``raw/garmin/`` et
``raw/strava/`` → ``interim/activities/`` (AN1-1, AN2-0, AN1-3,
``docs/decisions/0013``). Demande l'extra ``ingest`` : il lit les FIT par
``mountain_perf.ingest.fit``.

Les archives Strava (AN1-3, précisions 25 à 30) se lisent par
``mountain_perf.ingest.strava`` ; leurs activités se fusionnent à celles de Garmin,
Garmin d'abord (``ingest_export``, étapes 3 bis à 5 quater).

Plusieurs exports, chacun dans son dossier sous ``raw/garmin/`` (AN2-0), les autres
dossiers de ``raw/`` étant laissés aux autres sources :
``raw/garmin/<export>/acquisition.json`` (l'instant d'acquisition),
``raw/garmin/<export>/activities/activities.json`` (l'index),
``raw/garmin/<export>/activity_fit/<identifiant>.zip`` (une archive par activité, qui
contient un seul ``.fit``). L'existence d'une activité se décide sur l'export le plus
récent dont la période couvre son départ ; son entrée vient de cet export ; son FIT
aussi, ou, s'il y manque ou ne s'y lit pas, du plus récent export où il se lit. Ne lit
que ``raw/garmin/``, qu'il n'écrit jamais, et n'écrit que sous ``interim/`` ; deux
ingestions des mêmes fichiers écrivent les mêmes octets.
"""

import dataclasses
import hashlib
import io
import json
import lzma
import zipfile
import zlib
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from itertools import pairwise
from pathlib import Path

from mountain_perf.ingest.days import (
    DaysSummary,
    ExportDays,
    ExportDaysError,
    build_days,
    load_export_days,
)
from mountain_perf.ingest.fit import FitRefusedError, read_fit, read_fit_detailed
from mountain_perf.ingest.index import IndexReadError, read_index
from mountain_perf.ingest.interim import write_activities, write_days
from mountain_perf.ingest.strava import (
    FIT_KIND,
    FIT_SUFFIX,
    INDEX_MEMBER,
    STRAVA_DIR,
    MemberAbsent,
    MemberFit,
    MemberNotGzip,
    StravaExport,
    StravaExportError,
    StravaMembers,
    StravaRow,
    load_strava_export,
    strava_entry,
    strava_export_dirs,
)
from mountain_perf.ingest.views import activity_view
from mountain_perf.schemas import (
    ActivityIndex,
    ActivityRecording,
    ExportReport,
    FieldDifferenceCount,
    IndexDifference,
    IndexedActivity,
    IngestionReport,
    ReadFile,
    RecordingMismatch,
    RefusalReason,
    RefusedEntry,
    RefusedFile,
    RetiredActivity,
    SourceRef,
    SourcesReport,
    ToleratedFile,
    ViewRefusal,
    ViewRefusalCount,
    require_export_name,
)
from mountain_perf.validation import ContractError

GARMIN_DIR = "garmin"
"""Le dossier de ``raw/`` où se rangent les exports Garmin, un par sous-dossier
(AN2-0)."""

ACQUISITION_FILE = "acquisition.json"
"""Le fichier de ``raw/garmin/<export>/`` qui porte l'instant d'acquisition de
l'export : un objet JSON à la seule clé ``retrieved_at``, un instant ISO 8601 avec
fuseau."""

MISMATCH_TOLERANCE_S = 1.0
"""L'écart toléré entre un enregistrement et son entrée de l'index, en secondes, au
départ comme au temps écoulé : au-delà (strictement), le rapport le dit."""

_INDEX_FILE = Path("activities") / "activities.json"
_FIT_DIR = "activity_fit"
_UNREADABLE_MEMBER = (
    zipfile.BadZipFile,
    NotImplementedError,
    RuntimeError,
    EOFError,
    zlib.error,
    OSError,
    lzma.LZMAError,
    ValueError,
)
"""Ce que lève la lecture d'une archive ou d'un membre illisible : CRC faux,
compression inconnue, contenu chiffré, archive tronquée, flux deflate, bzip2
(``OSError``) ou lzma corrompu, répertoire central incohérent ou nom de membre qui
n'est pas l'UTF-8 annoncé (``ValueError``). L'archive est lue en mémoire : une
``OSError`` n'y vient que du décompresseur, une ``ValueError`` que de ``zipfile``."""


DAYS_NOT_IN_PLACE = (
    "interim/activities/ est à jour, mais la mise en place d'interim/days/ a échoué : "
    "relancer `mperf ingest`."
)
"""Le message d'``IngestError`` quand ``write_days`` échoue (``OSError``) après la mise
en place d'``interim/activities/`` (deux échanges de dossier, pas un) : si
``days.nouveau/`` n'a pas pris sa place, ``interim/days/`` est l'ancien (ou absent) ; si
seule la suppression de ``days.ancien/`` a échoué, il est le neuf. Le message ne dit pas
lequel : il ne dit rien de faux, et relancer ``mperf ingest`` remet tout en ordre.
L'``OSError`` est la cause (``__cause__``)."""


class IngestError(Exception):
    """L'export ne peut pas être ingéré ; rien n'est écrit. Le message dit pourquoi.

    Une exception : l'échec de la mise en place des jours, après celle des activités
    (``DAYS_NOT_IN_PLACE``), qui le dit.
    """


@dataclass(frozen=True)
class IngestionSummary:
    """Ce que l'ingestion a fait, en nombres.

    - ``exports`` — les exports lus, ceux du rapport (AN2-0) ;
    - ``activities`` — entrées de l'index écrit ;
    - ``recordings`` — enregistrements écrits ;
    - ``refused_files`` — fichiers de ``raw/garmin/<export>/activity_fit/`` refusés,
      avant la lecture de leur FIT ou par elle, et FIT des archives Strava refusés
      (AN1-3), chacun une fois ;
    - ``refused_entries`` — entrées des fichiers d'index refusées, tous exports, toutes
      sources ;
    - ``entries_without_archive`` — entrées Garmin de l'index écrit dont aucun export
      n'a de fichier de ``activity_fit/`` à ce nom sans extension, et entrées Strava
      dont aucun membre n'est lu (``Filename`` vide ou mal formé, autre suffixe que
      ``.fit.gz``, membre absent du zip ; un membre présent, même refusé, est une
      archive, AN1-3) ;
    - ``mismatches`` — enregistrements en désaccord avec leur entrée ;
    - ``view_refusals`` — les entrées sans vue ``Activity``, comptées par (motif, type),
      celles du rapport ;
    - ``retired`` — activités retirées de la source (AN2-0) ;
    - ``index_differences`` — par champ, activités dont l'entrée diffère d'un export à
      l'autre, celles du rapport (AN2-0) ;
    - ``fit_differences`` — activités dont deux exports portent des FIT différents ;
    - ``recordings_from_other_export`` — enregistrements tirés d'un autre export que
      l'entrée de leur activité ;
    - ``days`` — ce que l'ingestion des jours a fait (AN2-1) ;
    - ``sources`` — le rapport des sources écrit (``sources.json``), ``None`` sans
      export Strava (AN1-3) ;
    - ``strava_exports`` — les noms des exports Strava, pour le résumé (AN1-3).
    """

    exports: tuple[ExportReport, ...]
    activities: int
    recordings: int
    refused_files: int
    refused_entries: int
    entries_without_archive: int
    mismatches: int
    view_refusals: tuple[ViewRefusalCount, ...]
    retired: int
    index_differences: tuple[FieldDifferenceCount, ...]
    fit_differences: int
    recordings_from_other_export: int
    days: DaysSummary
    sources: SourcesReport | None = None
    strava_exports: tuple[str, ...] = ()


def _label(name: str) -> str:
    """Le dossier d'un export, tel que les messages le nomment."""
    return f"raw/{GARMIN_DIR}/{name}"


def _acquisition(export_dir: Path) -> tuple[datetime, bytes]:
    label = f"{_label(export_dir.name)}/{ACQUISITION_FILE}"
    try:
        data = (export_dir / ACQUISITION_FILE).read_bytes()
    except FileNotFoundError:
        raise IngestError(
            f"{label} manque : chaque dossier de raw/{GARMIN_DIR}/ est un export, avec "
            "l'instant de son acquisition."
        ) from None
    try:
        content = json.loads(data.decode("utf-8-sig"))
    except ValueError:
        raise IngestError(f"{label} : JSON en UTF-8 attendu.") from None
    if not isinstance(content, dict) or set(content) != {"retrieved_at"}:
        raise IngestError(f"{label} : objet {{retrieved_at}} attendu.")
    value = content["retrieved_at"]
    instant: datetime | None = None
    if isinstance(value, str):
        try:
            instant = datetime.fromisoformat(value)
        except ValueError:
            instant = None
    if instant is None or instant.utcoffset() is None:
        raise IngestError(
            f"{label} : retrieved_at doit être un instant ISO 8601 avec fuseau."
        )
    return instant, data


def read_acquisition(export_dir: Path) -> datetime:
    """L'instant d'acquisition de l'export rangé dans ``export_dir``
    (``raw/garmin/<export>/``), lu dans son ``acquisition.json``, tel que
    ``datetime.fromisoformat`` le lit (décalage compris, aucune conversion en UTC).

    Lève ``IngestError``, le message commençant par
    ``raw/garmin/<export>/acquisition.json`` : fichier absent (« … manque : chaque
    dossier de raw/garmin/ est un export, avec l'instant de son acquisition. ») ;
    octets qui ne se décodent pas en ``utf-8-sig`` puis en JSON, une marque d'ordre des
    octets en tête étant admise, pas l'UTF-16 (« … : JSON en UTF-8 attendu. ») ; autre
    chose qu'un objet à la seule clé ``retrieved_at`` (« … : objet {retrieved_at}
    attendu. ») ; valeur qui n'est pas un texte, texte que ``datetime.fromisoformat``
    refuse, ou instant sans fuseau (« … : retrieved_at doit être un instant ISO 8601
    avec fuseau. »). Une autre erreur d'E/S que l'absence du fichier se propage
    (``OSError``).
    """
    return _acquisition(export_dir)[0]


def _misplaced(folder: Path, label: str) -> None:
    """Un export laissé à plat dans ``folder`` (son ``acquisition.json`` ou son
    ``activities/``) : ``IngestError``."""
    for name, found in (
        (ACQUISITION_FILE, (folder / ACQUISITION_FILE).exists()),
        ("activities/", (folder / "activities").is_dir()),
    ):
        if found:
            raise IngestError(
                f"{label}{name} : un export Garmin se range dans son dossier, "
                f"raw/{GARMIN_DIR}/<export>/ ; ranger celui-ci dans le sien."
            )


def export_dirs(raw: Path) -> list[Path]:
    """Les dossiers d'exports Garmin de ``raw`` (``data_dir/raw``), par nom croissant :
    chaque dossier direct de ``raw/garmin/`` ; un fichier de ``raw/garmin/``, et tout
    autre dossier de ``raw/`` (une autre source), sont ignorés.

    ``raw/garmin/`` absent, ou sans dossier : ``[]`` (AN1-3 : une archive Strava peut
    être la seule source ; ``ingest_export`` s'arrête s'il n'y a aucun export).

    Lève ``IngestError`` : un export laissé à plat, l'ancienne disposition, dans
    ``raw/`` ou dans ``raw/garmin/`` (son ``acquisition.json``, ou sinon son dossier
    ``activities/`` : « raw/acquisition.json : un export Garmin se range dans son
    dossier, raw/garmin/<export>/ ; ranger celui-ci dans le sien. ») ; un nom de
    dossier que ``require_export_name`` refuse (« raw/garmin/<nom>/ : le nom d'un
    export est fait de lettres et de chiffres ASCII, de « _ », « . » ou « - ». »).
    """
    garmin = raw / GARMIN_DIR
    _misplaced(raw, "raw/")
    _misplaced(garmin, f"raw/{GARMIN_DIR}/")
    dirs = (
        sorted(
            (path for path in garmin.iterdir() if path.is_dir()), key=lambda p: p.name
        )
        if garmin.is_dir()
        else []
    )
    for path in dirs:
        try:
            require_export_name(path.name)
        except ContractError:
            raise IngestError(
                f"{_label(path.name)}/ : le nom d'un export est fait de lettres et de "
                "chiffres ASCII, de « _ », « . » ou « - »."
            ) from None
    return dirs


@dataclass(frozen=True)
class _Export:
    """Un export lu : son nom, son instant, ses fichiers et ses entrées gardées."""

    name: str
    retrieved_at: datetime
    acquisition_hash: str
    index_source: SourceRef
    entries: dict[str, IndexedActivity]
    refused: tuple[RefusedEntry, ...]
    archives: tuple[Path, ...]
    period_start: datetime | None


def _load(export_dir: Path) -> _Export:
    """L'export de ``export_dir``, dans cet ordre : l'instant d'acquisition ; l'index
    (absent : « raw/garmin/<export>/activities/activities.json manque. » ; illisible :
    le message de l'``IndexReadError``, préfixé de
    ``raw/garmin/<export>/activities/``) ; une entrée gardée qui part après l'instant
    d'acquisition (« raw/garmin/<export>/ : une activité de l'index part après l'instant
    d'acquisition de l'export ; acquisition.json est faux. ») ; les noms des fichiers de
    ``activity_fit/`` (un sous-dossier est ignoré ; un nom qui contient « : » ou
    « \\ » : « raw/garmin/<export>/activity_fit/<nom> : nom de fichier que le rapport
    ne peut pas porter (« : » ou « \\ »). »)."""
    name = export_dir.name
    label = _label(name)
    retrieved_at, acquisition = _acquisition(export_dir)
    try:
        index_bytes = (export_dir / _INDEX_FILE).read_bytes()
    except FileNotFoundError:
        raise IngestError(f"{label}/{_INDEX_FILE.as_posix()} manque.") from None
    source = SourceRef(
        "garmin_activities", _INDEX_FILE.name, _sha256(index_bytes), retrieved_at
    )
    try:
        index_read = read_index(index_bytes, source)
    except IndexReadError as error:
        raise IngestError(f"{label}/{_INDEX_FILE.parent.as_posix()}/{error}") from None
    entries = {entry.activity_ref: entry for entry in index_read.entries}
    if any(entry.start_time > retrieved_at for entry in entries.values()):
        raise IngestError(
            f"{label}/ : une activité de l'index part après l'instant d'acquisition "
            f"de l'export ; {ACQUISITION_FILE} est faux."
        )
    fit_dir = export_dir / _FIT_DIR
    files = (
        sorted(
            (path for path in fit_dir.iterdir() if path.is_file()),
            key=lambda path: path.name,
        )
        if fit_dir.is_dir()
        else []
    )
    for path in files:
        if ":" in path.name or "\\" in path.name:
            raise IngestError(
                f"{label}/{_FIT_DIR}/{path.name} : nom de fichier que le rapport ne "
                "peut pas porter (« : » ou « \\ »)."
            )
    starts = [entry.start_time for entry in entries.values()]
    return _Export(
        name=name,
        retrieved_at=retrieved_at,
        acquisition_hash=_sha256(acquisition),
        index_source=source,
        entries=entries,
        refused=index_read.refused,
        archives=tuple(files),
        period_start=min(starts) if starts else None,
    )


def _covers(export: _Export, start: datetime) -> bool:
    return export.period_start is not None and (
        export.period_start <= start <= export.retrieved_at
    )


def _differs(a: IndexedActivity, b: IndexedActivity, field: IndexDifference) -> bool:
    first, second = getattr(a, field.value), getattr(b, field.value)
    if field is IndexDifference.START_TIME:
        return bool(first != second or first.utcoffset() != second.utcoffset())
    return bool(first != second)


@dataclass(frozen=True)
class _Archive:
    """Une archive d'un export pour une activité qu'il porte : son chemin, son nom au
    rapport, son empreinte, et son membre ``.fit`` (``None`` : pas un seul FIT)."""

    path: Path
    name: str
    content_hash: str
    member: bytes | None


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _fit_member(archive: bytes) -> bytes | None:
    """Les octets de l'unique membre ``.fit`` (casse ignorée) d'une archive zip ;
    ``None`` pour une archive qui n'est pas un zip, qui n'a pas exactement un membre,
    dont le membre ne finit pas par ``.fit``, ou dont le membre ne se lit pas."""
    try:
        with zipfile.ZipFile(io.BytesIO(archive)) as zf:
            members = zf.namelist()
            if len(members) != 1 or not members[0].lower().endswith(".fit"):
                return None
            return zf.read(members[0])
    except _UNREADABLE_MEMBER:
        return None


def _mismatch(
    recording: ActivityRecording, entry: IndexedActivity
) -> RecordingMismatch | None:
    offset_s = (recording.start_time - entry.start_time).total_seconds()
    elapsed = [session.elapsed_duration_s for session in recording.sessions]
    recording_elapsed_s = (
        None
        if any(value is None for value in elapsed)
        else sum(value for value in elapsed if value is not None)
    )
    index_elapsed_s = entry.elapsed_duration_s
    differs = abs(offset_s) > MISMATCH_TOLERANCE_S or (
        recording_elapsed_s is not None
        and index_elapsed_s is not None
        and abs(recording_elapsed_s - index_elapsed_s) > MISMATCH_TOLERANCE_S
    )
    if not differs:
        return None
    return RecordingMismatch(
        entry.activity_ref, offset_s, recording_elapsed_s, index_elapsed_s
    )


# ---------------------------------------------------------------------------
# Les archives Strava (AN1-3)
# ---------------------------------------------------------------------------


NO_EXPORT = (
    f"raw/ ne contient aucun export : un export Garmin se range dans "
    f"raw/{GARMIN_DIR}/<export>/, une archive Strava dans raw/{STRAVA_DIR}/<export>/, "
    f"chacun avec son {ACQUISITION_FILE}."
)
"""Le message d'``IngestError`` quand ``raw/`` ne porte ni export Garmin ni archive
Strava (AN1-3)."""


def _check_names(garmin: list[Path], strava: list[Path]) -> None:
    """Aucun export dans les deux sources ; un même nom de dossier dans les deux (le
    premier en ordre croissant) : ``IngestError`` (AN1-3)."""
    if not garmin and not strava:
        raise IngestError(NO_EXPORT)
    common = sorted({path.name for path in garmin} & {path.name for path in strava})
    if common:
        name = common[0]
        raise IngestError(
            f"raw/{GARMIN_DIR}/{name}/ et raw/{STRAVA_DIR}/{name}/ : même nom "
            "d'export ; le rapport nomme les exports par leur nom seul : renommer "
            "l'un des deux dossiers."
        )


def _check_instants(garmin: list[_Export], strava: list[StravaExport]) -> None:
    """Deux exports au même instant d'acquisition, toutes sources confondues (C2) :
    ``IngestError``, qui nomme les deux dossiers (Garmin avant Strava, puis par nom)."""
    labelled = sorted(
        [(export.retrieved_at, _label(export.name)) for export in garmin]
        + [
            (export.retrieved_at, f"raw/{STRAVA_DIR}/{export.name}")
            for export in strava
        ]
    )
    for (first_at, first), (second_at, second) in pairwise(labelled):
        if first_at == second_at:
            raise IngestError(
                f"{first}/ et {second}/ : même instant d'acquisition ; l'ordre des "
                "exports serait indéterminé."
            )


def _strava_covers(export: StravaExport, start: datetime) -> bool:
    return export.period_start is not None and (
        export.period_start <= start <= export.retrieved_at
    )


def _strava_existence(
    strava: list[StravaExport], rows: list[dict[str, StravaRow]]
) -> tuple[dict[str, int], list[RetiredActivity]]:
    """L'existence entre exports Strava (rangés par instant d'acquisition), la règle de
    la précision 15 : pour chaque activité, l'export Strava le plus récent dont la
    période couvre son départ décide ; absente de lui, elle est retirée ; présente, sa
    ligne vient de lui (« décisive »). Ni les champs ni les FIT ne se comparent entre
    exports Strava."""
    latest: dict[str, int] = {}
    for position, found in enumerate(rows):
        for ref in found:
            latest[ref] = position
    decisive: dict[str, int] = {}
    retired: list[RetiredActivity] = []
    for ref, position in latest.items():
        start = rows[position][ref].start_utc
        chosen = max(
            i for i, export in enumerate(strava) if _strava_covers(export, start)
        )
        if chosen == position:
            decisive[ref] = position
        else:
            retired.append(RetiredActivity(ref, strava[chosen].name))
    return decisive, retired


@dataclass(frozen=True)
class _StravaIdentity:
    """Ce que la passe d'identité garde d'un FIT Strava lu (C6) : l'empreinte du FIT
    décompressé, l'identité de son premier ``file_id``, son départ, son décalage local ;
    pas l'enregistrement."""

    fit_hash: bytes
    manufacturer: str | None
    product: int | None
    time_created: datetime | None
    start: datetime
    local_offset_s: int | None


@dataclass(frozen=True)
class _GarminKeys:
    """Les clés d'appariement d'une activité Garmin gardée : les empreintes des membres
    ``.fit`` de toutes ses archives lisibles (calculées avant leur lecture), et, si
    elle a un enregistrement, son identité (fabricant, produit, création, départ)."""

    hashes: frozenset[bytes]
    identity: tuple[str | None, int | None, datetime | None, datetime] | None


def _pair(
    strava_keys: dict[str, set[object]], garmin_keys: dict[str, set[object]]
) -> tuple[dict[str, str], set[str]]:
    """Une passe de l'appariement (D5), un pour un par activités : ``(s, g)`` est une
    paire si les clés de ``s`` ne désignent que ``g`` et si ``g`` n'est désignée que
    par ``s`` ; une activité Strava qui désigne au moins une activité Garmin sans
    former de paire est ambiguë à cette passe."""
    by_key: dict[object, set[str]] = {}
    for garmin, keys in garmin_keys.items():
        for key in keys:
            by_key.setdefault(key, set()).add(garmin)
    candidates = {
        strava: set().union(*(by_key.get(key, set()) for key in keys))
        for strava, keys in strava_keys.items()
    }
    designers: dict[str, set[str]] = {}
    for strava, found in candidates.items():
        for garmin in found:
            designers.setdefault(garmin, set()).add(strava)
    pairs: dict[str, str] = {}
    ambiguous: set[str] = set()
    for strava, found in candidates.items():
        if len(found) == 1:
            (garmin,) = found
            if designers[garmin] == {strava}:
                pairs[strava] = garmin
                continue
        if found:
            ambiguous.add(strava)
    return pairs, ambiguous


def _hash_key(identity: _StravaIdentity) -> set[object]:
    return {identity.fit_hash}


def _garmin_hash_key(keys: _GarminKeys) -> set[object]:
    return set(keys.hashes)


def _identity_key(identity: _StravaIdentity) -> set[object]:
    values = (identity.manufacturer, identity.product, identity.time_created)
    if any(value is None for value in values):
        return set()
    return {(*values, identity.start)}


def _garmin_identity_key(keys: _GarminKeys) -> set[object]:
    if keys.identity is None or any(value is None for value in keys.identity):
        return set()
    return {keys.identity}


def _fit_start_key(identity: _StravaIdentity) -> set[object]:
    return {identity.start} if identity.manufacturer == "garmin" else set()


def _garmin_fit_start_key(keys: _GarminKeys) -> set[object]:
    if keys.identity is None or keys.identity[0] != "garmin":
        return set()
    return {keys.identity[3]}


def _match_strava(
    identities: dict[str, _StravaIdentity], garmin: dict[str, _GarminKeys]
) -> tuple[dict[str, tuple[int, str]], set[str]]:
    """L'appariement (D5) des activités Strava décisives qui ont une identité avec les
    activités Garmin gardées, en trois passes : (a) l'empreinte du FIT ; (b) fabricant,
    produit, création et départ ; (c) le départ seul, fabricant ``garmin`` des deux
    côtés. Rend, pour chaque activité Strava appariée, sa passe (0, 1, 2) et l'activité
    Garmin ; et les activités Strava non appariées qui ont été ambiguës à une passe."""
    passes: tuple[
        tuple[
            Callable[[_StravaIdentity], set[object]],
            Callable[[_GarminKeys], set[object]],
        ],
        ...,
    ] = (
        (_hash_key, _garmin_hash_key),
        (_identity_key, _garmin_identity_key),
        (_fit_start_key, _garmin_fit_start_key),
    )
    matched: dict[str, tuple[int, str]] = {}
    taken: set[str] = set()
    ambiguous: set[str] = set()
    for rank, (strava_key, garmin_key) in enumerate(passes):
        pairs, found = _pair(
            {s: strava_key(item) for s, item in identities.items() if s not in matched},
            {g: garmin_key(keys) for g, keys in garmin.items() if g not in taken},
        )
        for strava, partner in pairs.items():
            matched[strava] = (rank, partner)
            taken.add(partner)
        ambiguous |= found
    return matched, ambiguous - set(matched)


def _retiring_export(start: datetime, garmin: list[_Export]) -> str | None:
    """L'export Garmin le plus récent dont la période couvre ``start``, ou ``None``
    (D6, (g) 2)."""
    covering = [export.name for export in garmin if _covers(export, start)]
    return covering[-1] if covering else None


@dataclass(frozen=True)
class _MemberOutcome:
    """La première lecture d'un membre ``.fit.gz`` d'un export Strava : présent dans le
    zip (lu, même refusé), et l'identité de son FIT s'il se lit."""

    present: bool
    identity: _StravaIdentity | None


def _member_name(export: StravaExport, filename: str) -> str:
    return f"{STRAVA_DIR}/{export.name}/{export.archive.name}/{filename}"


def _fit_source(export: StravaExport, filename: str, raw: bytes) -> SourceRef:
    return SourceRef(
        FIT_KIND, filename.rsplit("/", 1)[-1], _sha256(raw), export.retrieved_at
    )


def _is_fit(row: StravaRow) -> bool:
    return row.filename is not None and row.filename.lower().endswith(FIT_SUFFIX)


def _first_reading(
    members: StravaMembers,
    export: StravaExport,
    filename: str,
    ref: str,
    read: list[ReadFile],
    refused_files: list[RefusedFile],
    tolerated: set[ToleratedFile],
) -> _MemberOutcome:
    """La première lecture d'un membre ``.fit.gz`` (étape 5 bis) : absent, rien (C9) ;
    pas un gzip, lu et refusé ``NOT_A_GZIP_FIT`` ; sinon lu par la lecture tolérante,
    son refus inscrit, ou son identité et ses champs sautés gardés (C6)."""
    found = members.read(filename)
    if isinstance(found, MemberAbsent):
        return _MemberOutcome(False, None)
    name = _member_name(export, filename)
    read.append(ReadFile(name, _sha256(found.raw)))
    if isinstance(found, MemberNotGzip):
        refused_files.append(RefusedFile(name, RefusalReason.NOT_A_GZIP_FIT))
        return _MemberOutcome(True, None)
    try:
        detailed = read_fit_detailed(
            found.fit,
            activity_ref=ref,
            source=_fit_source(export, filename, found.raw),
            tolerant=True,
        )
    except FitRefusedError as error:
        refused_files.append(RefusedFile(name, error.reason))
        return _MemberOutcome(True, None)
    device = detailed.recording.device
    tolerated.update(
        ToleratedFile(name, device.manufacturer, skipped.message, skipped.field_number)
        for skipped in detailed.skipped
    )
    return _MemberOutcome(
        True,
        _StravaIdentity(
            fit_hash=hashlib.sha256(found.fit).digest(),
            manufacturer=device.manufacturer,
            product=device.product,
            time_created=device.time_created,
            start=detailed.recording.start_time,
            local_offset_s=detailed.local_offset_s,
        ),
    )


def ingest_export(data_dir: Path) -> IngestionSummary:
    """Ingère les exports de ``data_dir/raw/garmin/`` et les archives de
    ``data_dir/raw/strava/`` (AN1-3), et écrit ``data_dir/interim/activities/``, puis
    ``data_dir/interim/days/``.

    Dans cet ordre :

    1. les dossiers d'exports Garmin (``export_dirs``) et Strava
       (``strava_export_dirs`` ; une ``StravaExportError`` devient ``IngestError``, au
       même message) ; aucun export dans les deux : ``IngestError`` (``NO_EXPORT``) ; un
       même nom de dossier dans les deux : ``IngestError`` (« raw/garmin/<x>/ et
       raw/strava/<x>/ : même nom d'export ; … ») ; puis, pour chaque export Garmin par
       nom croissant, ``_load`` : l'instant d'acquisition, l'index (chaque entrée gardée
       porte la provenance de son fichier d'index), une entrée gardée partie après
       l'instant d'acquisition, les noms des fichiers de ``activity_fit/`` ;
    1 bis. chaque export Strava, par nom croissant (``load_strava_export``) ;
    2. les exports, triés par instant d'acquisition ; deux instants égaux, toutes
       sources confondues (C2) : ``IngestError`` (« raw/garmin/<a>/ et raw/garmin/<b>/ :
       même instant d'acquisition ; l'ordre des exports serait indéterminé. », ``a`` et
       ``b`` par nom croissant ; de même « raw/strava/<a>/ et raw/strava/<b>/ … » et
       « raw/garmin/<a>/ et raw/strava/<b>/ … ») ; puis les familles journalières de
       chaque export Garmin, dans l'ordre des instants (``load_export_days``) : leur
       refus devient ``IngestError``, au même message (« raw/garmin/<export>/ : … ;
       acquisition.json est faux. ») ; sans export Garmin, chaque export Strava entre
       aux jours sans fichier journalier (C8) ;
    3. l'existence de chaque activité : sur l'export le plus récent dont la période
       (du premier départ de ses entrées gardées à son instant d'acquisition, bornes
       comprises) couvre son départ, lu dans l'export le plus récent qui la porte ;
       absente de cet export décisif, elle est retirée de la source ;
    4. chaque **fichier** de ``raw/garmin/<export>/activity_fit/``, export par export
       dans l'ordre des instants, par nom croissant : lu, empreint (SHA-256 des octets
       de l'archive), inscrit au rapport sous ``garmin/<export>/activity_fit/<nom>`` ;
       un nom sans extension que portent plusieurs fichiers du même export fait refuser
       chacun d'eux ``DUPLICATE_ARCHIVE`` ; sinon, nom absent des entrées gardées de cet
       export : ``NOT_IN_INDEX`` ; sinon, archive qui n'est pas un zip à un seul membre
       ``.fit`` lisible : ``NOT_ONE_FIT`` ;
    5. l'enregistrement de chaque activité gardée, par identifiant croissant : ses
       archives (refusée ``DUPLICATE_ARCHIVE`` ou ``NOT_IN_INDEX``, une archive n'en est
       pas une), celle de l'export décisif d'abord, puis celles des autres exports, du
       plus récent au plus ancien ; une archive ``NOT_ONE_FIT`` est passée ; sinon
       ``read_fit`` : son refus inscrit au rapport sous le nom de l'archive, à son
       motif, et l'archive suivante essayée ; le premier FIT lu donne l'enregistrement,
       dont la source est son archive, avec l'instant d'acquisition de son export ;
       seuls les membres essayés sont décodés ;
    6. les comptes entre exports, pour chaque activité gardée : les membres ``.fit``
       distincts de ses archives (deux ou plus : un FIT différent) ; les champs
       d'``IndexDifference`` où l'entrée d'un autre export qui la porte diffère de celle
       de l'export décisif (le départ par son instant et son décalage) ;
    3 bis. l'existence entre exports Strava (``_strava_existence``) ; les activités
       Strava retirées s'ajoutent aux retirées ;
    5 bis. l'identité des FIT Strava (C6) : pour chaque activité Strava décisive, par
       identifiant croissant, dont le ``Filename`` finit par ``.fit.gz``, un seul
       ``StravaMembers`` par export ; un membre nommé par plusieurs lignes se lit une
       fois ; absent : rien (une entrée sans archive, C9) ; pas un gzip : lu et refusé
       ``NOT_A_GZIP_FIT`` ; sinon ``read_fit_detailed(..., tolerant=True)`` : son refus
       inscrit au rapport, ou son identité et ses champs sautés gardés, sans
       l'enregistrement ;
    5 ter. l'appariement (``_match_strava``) avec les activités Garmin gardées (leurs
       empreintes de membres, leur identité si elles ont un enregistrement) ; puis, pour
       chaque activité Strava décisive : appariée, pas d'entrée (Garmin d'abord) ; non
       appariée, d'un FIT ``garmin`` parti dans la période d'un export Garmin : retirée
       (``_retiring_export``) ; sinon, une entrée Strava (``strava_entry``, le décalage
       de son FIT s'il en a un) ;
    5 quater. l'enregistrement des entrées Strava dont le FIT a une identité, par une
       seconde lecture tolérante ;
    7. l'index : les entrées gardées et les entrées Strava, ``has_recording`` vrai pour
       celles qui ont reçu un enregistrement, triées par (instant de départ,
       identifiant) ; les exports de toutes les sources, par instant d'acquisition ;
    8. les refus de vue (``activity_view``), comptés par (motif, type de la source) ;
       les désaccords d'un enregistrement avec son entrée (au-delà de
       ``MISMATCH_TOLERANCE_S``), triés par identifiant ;
    9. le rapport ; s'il y a un export Strava, le rapport des sources
       (``SourcesReport``, C5) ;
    10. les jours (``build_days``), calculés en entier ;
    11. ``write_activities`` ; puis ``write_days``. Si ``write_days`` échoue
        (``OSError``), ``interim/activities/`` est déjà neuf : ``IngestError``
        (``DAYS_NOT_IN_PLACE``), de cause l'``OSError``.

    Les étapes 3 à 9 sont celles d'AN2-0, inchangées pour Garmin ; les FIT Garmin se
    lisent toujours strictement (``read_fit``). Une erreur avant ``write_activities``
    n'écrit rien.
    """
    raw = data_dir / "raw"
    garmin_dirs = export_dirs(raw)
    try:
        strava_dirs = strava_export_dirs(raw)
    except StravaExportError as error:
        raise IngestError(str(error)) from None
    _check_names(garmin_dirs, strava_dirs)
    exports = sorted(
        (_load(path) for path in garmin_dirs),
        key=lambda export: (export.retrieved_at, export.name),
    )
    try:
        strava = sorted(
            (load_strava_export(path) for path in strava_dirs),
            key=lambda export: (export.retrieved_at, export.name),
        )
    except StravaExportError as error:
        raise IngestError(str(error)) from None
    _check_instants(exports, strava)
    daily: list[ExportDays] = []
    for export in exports:
        try:
            daily.append(
                load_export_days(
                    data_dir / "raw" / GARMIN_DIR / export.name,
                    export.name,
                    export.retrieved_at,
                )
            )
        except ExportDaysError as error:
            raise IngestError(str(error)) from None
    if not exports:
        daily = [ExportDays(export.name, export.retrieved_at, ()) for export in strava]

    latest: dict[str, int] = {}
    for position, export in enumerate(exports):
        for ref in export.entries:
            latest[ref] = position
    decisive: dict[str, int] = {}
    retired: list[RetiredActivity] = []
    for ref, position in latest.items():
        start = exports[position].entries[ref].start_time
        chosen = max(i for i, export in enumerate(exports) if _covers(export, start))
        if chosen == position:
            decisive[ref] = position
        else:
            retired.append(RetiredActivity(ref, exports[chosen].name))

    read: list[ReadFile] = []
    refused_files: list[RefusedFile] = []
    archives: dict[str, dict[int, _Archive]] = {}
    all_stems: set[str] = set()
    for position, export in enumerate(exports):
        prefix = f"{GARMIN_DIR}/{export.name}"
        read.append(ReadFile(f"{prefix}/{ACQUISITION_FILE}", export.acquisition_hash))
        read.append(
            ReadFile(
                f"{prefix}/{_INDEX_FILE.as_posix()}", export.index_source.content_hash
            )
        )
        stems = Counter(path.stem for path in export.archives)
        all_stems.update(stems)
        for path in export.archives:
            archive = path.read_bytes()
            name = f"{prefix}/{_FIT_DIR}/{path.name}"
            content_hash = _sha256(archive)
            read.append(ReadFile(name, content_hash))
            if stems[path.stem] > 1:
                refused_files.append(RefusedFile(name, RefusalReason.DUPLICATE_ARCHIVE))
                continue
            if path.stem not in export.entries:
                refused_files.append(RefusedFile(name, RefusalReason.NOT_IN_INDEX))
                continue
            member = _fit_member(archive)
            if member is None:
                refused_files.append(RefusedFile(name, RefusalReason.NOT_ONE_FIT))
            archives.setdefault(path.stem, {})[position] = _Archive(
                path, name, content_hash, member
            )

    recordings: list[ActivityRecording] = []
    recording_export: dict[str, int] = {}
    garmin_hashes: dict[str, frozenset[bytes]] = {}
    fit_differences = 0
    for ref in sorted(decisive):
        candidates = archives.get(ref, {})
        members = {
            hashlib.sha256(item.member).digest()
            for item in candidates.values()
            if item.member is not None
        }
        garmin_hashes[ref] = frozenset(members)
        fit_differences += len(members) > 1
        order = sorted(
            candidates, key=lambda position: (position != decisive[ref], -position)
        )
        for position in order:
            item = candidates[position]
            if item.member is None:
                continue
            source = SourceRef(
                "garmin_fit",
                item.path.name,
                item.content_hash,
                exports[position].retrieved_at,
            )
            try:
                recording = read_fit(item.member, activity_ref=ref, source=source)
            except FitRefusedError as error:
                refused_files.append(RefusedFile(item.name, error.reason))
                continue
            recordings.append(recording)
            recording_export[ref] = position
            break

    differences: Counter[IndexDifference] = Counter()
    for ref, position in decisive.items():
        entry = exports[position].entries[ref]
        others = [
            export.entries[ref]
            for i, export in enumerate(exports)
            if i != position and ref in export.entries
        ]
        for field in IndexDifference:
            if any(_differs(entry, other, field) for other in others):
                differences[field] += 1

    garmin_keys = {ref: _GarminKeys(garmin_hashes[ref], None) for ref in decisive}
    for recording in recordings:
        device = recording.device
        garmin_keys[recording.activity_ref] = _GarminKeys(
            garmin_hashes[recording.activity_ref],
            (
                device.manufacturer,
                device.product,
                device.time_created,
                recording.start_time,
            ),
        )
    strava_rows = [{row.activity_ref: row for row in export.rows} for export in strava]
    strava_decisive, strava_retired = _strava_existence(strava, strava_rows)
    retired.extend(strava_retired)
    tolerated: set[ToleratedFile] = set()
    identities: dict[str, _StravaIdentity] = {}
    with_member: set[str] = set()
    for position, held in enumerate(strava):
        prefix = f"{STRAVA_DIR}/{held.name}"
        read.append(ReadFile(f"{prefix}/{ACQUISITION_FILE}", held.acquisition_hash))
        read.append(ReadFile(f"{prefix}/{held.archive.name}", held.archive_hash))
        read.append(
            ReadFile(
                f"{prefix}/{held.archive.name}/{INDEX_MEMBER}",
                held.index_source.content_hash,
            )
        )
        rows = strava_rows[position]
        wanted = [
            ref
            for ref in sorted(strava_decisive)
            if strava_decisive[ref] == position and _is_fit(rows[ref])
        ]
        if not wanted:
            continue
        outcomes: dict[str, _MemberOutcome] = {}
        with StravaMembers(held) as strava_members:
            for ref in wanted:
                filename = rows[ref].filename or ""
                if filename not in outcomes:
                    outcomes[filename] = _first_reading(
                        strava_members,
                        held,
                        filename,
                        ref,
                        read,
                        refused_files,
                        tolerated,
                    )
                outcome = outcomes[filename]
                if outcome.present:
                    with_member.add(ref)
                if outcome.identity is not None:
                    identities[ref] = outcome.identity

    matched, ambiguous = _match_strava(identities, garmin_keys)
    strava_entries: dict[str, IndexedActivity] = {}
    retired_garmin_device = 0
    default_timezone_entries = 0
    for ref in sorted(strava_decisive):
        if ref in matched:
            continue
        held = strava[strava_decisive[ref]]
        row = strava_rows[strava_decisive[ref]][ref]
        identity = identities.get(ref)
        if identity is not None and identity.manufacturer == "garmin":
            retiring = _retiring_export(row.start_utc, exports)
            if retiring is not None:
                retired.append(RetiredActivity(ref, retiring))
                retired_garmin_device += 1
                continue
        entry, by_default = strava_entry(
            row, held, None if identity is None else identity.local_offset_s
        )
        default_timezone_entries += by_default
        strava_entries[ref] = entry

    strava_recordings: list[ActivityRecording] = []
    for position, held in enumerate(strava):
        refs = [
            ref
            for ref in sorted(strava_entries)
            if strava_decisive[ref] == position and ref in identities
        ]
        if not refs:
            continue
        with StravaMembers(held) as strava_members:
            for ref in refs:
                filename = strava_rows[position][ref].filename or ""
                fit_member = strava_members.read(filename)
                if not isinstance(fit_member, MemberFit):
                    continue
                try:
                    detailed = read_fit_detailed(
                        fit_member.fit,
                        activity_ref=ref,
                        source=_fit_source(held, filename, fit_member.raw),
                        tolerant=True,
                    )
                except FitRefusedError:
                    continue
                strava_recordings.append(detailed.recording)
    strava_recorded = {recording.activity_ref for recording in strava_recordings}

    kept = sorted(
        [
            dataclasses.replace(
                exports[position].entries[ref],
                has_recording=ref in recording_export,
            )
            for ref, position in decisive.items()
        ]
        + [
            dataclasses.replace(entry, has_recording=ref in strava_recorded)
            for ref, entry in strava_entries.items()
        ],
        key=lambda entry: (entry.start_time.timestamp(), entry.activity_ref),
    )
    index = ActivityIndex(
        tuple(kept),
        tuple(
            sorted(
                [export.index_source for export in exports]
                + [export.index_source for export in strava],
                key=lambda source: source.retrieved_at,
            )
        ),
    )

    refusals: Counter[tuple[ViewRefusal, str]] = Counter()
    for entry in index.entries:
        refusal = activity_view(entry).refusal
        if refusal is not None:
            refusals[(refusal, entry.source_activity_type)] += 1
    view_refusals = tuple(
        ViewRefusalCount(reason, kind, count)
        for (reason, kind), count in sorted(
            refusals.items(), key=lambda item: (item[0][0].value, item[0][1])
        )
    )
    found: list[RecordingMismatch] = []
    for recording in recordings:
        ref = recording.activity_ref
        mismatch = _mismatch(recording, exports[decisive[ref]].entries[ref])
        if mismatch is not None:
            found.append(mismatch)
    for recording in strava_recordings:
        mismatch = _mismatch(recording, strava_entries[recording.activity_ref])
        if mismatch is not None:
            found.append(mismatch)
    mismatches = tuple(sorted(found, key=lambda mismatch: mismatch.activity_ref))
    index_differences = tuple(
        FieldDifferenceCount(field, differences[field])
        for field in sorted(differences, key=lambda field: field.value)
    )
    from_other = sum(
        position != decisive[ref] for ref, position in recording_export.items()
    )
    export_reports = tuple(
        sorted(
            [
                ExportReport(
                    name=export.name,
                    index=export.index_source,
                    period_start=export.period_start,
                    entries=len(export.entries),
                    refused_entries=export.refused,
                    archives=len(export.archives),
                )
                for export in exports
            ]
            + [
                ExportReport(
                    name=export.name,
                    index=export.index_source,
                    period_start=export.period_start,
                    entries=len(export.rows),
                    refused_entries=export.refused,
                    archives=export.named_files,
                )
                for export in strava
            ],
            key=lambda item: item.index.retrieved_at,
        )
    )
    report = IngestionReport(
        exports=export_reports,
        read=tuple(sorted(read, key=lambda item: item.name)),
        refused_files=tuple(sorted(refused_files, key=lambda item: item.name)),
        retired=tuple(sorted(retired, key=lambda item: item.activity_ref)),
        view_refusals=view_refusals,
        mismatches=mismatches,
        index_differences=index_differences,
        fit_differences=fit_differences,
        recordings_from_other_export=from_other,
    )
    sources = (
        SourcesReport(
            strava_exports=len(strava),
            strava_entries=len(strava_entries),
            matched_by_hash=sum(rank == 0 for rank, _ in matched.values()),
            matched_by_identity=sum(rank == 1 for rank, _ in matched.values()),
            matched_by_fit_start=sum(rank == 2 for rank, _ in matched.values()),
            ambiguous=len(ambiguous),
            retired_garmin_device=retired_garmin_device,
            default_timezone_entries=default_timezone_entries,
            strava_recordings_without_elevation=sum(
                recording.elevation is None for recording in strava_recordings
            ),
            tolerated=tuple(
                sorted(
                    tolerated,
                    key=lambda item: (item.name, item.message, item.field_number),
                )
            ),
        )
        if strava
        else None
    )
    days = build_days(daily)
    write_activities(
        data_dir, index, [*recordings, *strava_recordings], report, sources
    )
    try:
        write_days(data_dir, days.records, days.history, days.report)
    except OSError as error:
        raise IngestError(DAYS_NOT_IN_PLACE) from error
    return IngestionSummary(
        exports=export_reports,
        activities=len(index.entries),
        recordings=len(recordings) + len(strava_recordings),
        refused_files=len(refused_files),
        refused_entries=sum(len(export.refused) for export in exports)
        + sum(len(held.refused) for held in strava),
        entries_without_archive=sum(
            entry.activity_ref not in all_stems
            for entry in index.entries
            if entry.activity_ref not in strava_entries
        )
        + sum(ref not in with_member for ref in strava_entries),
        mismatches=len(mismatches),
        view_refusals=view_refusals,
        retired=len(retired),
        index_differences=index_differences,
        fit_differences=fit_differences,
        recordings_from_other_export=from_other,
        days=days.summary,
        sources=sources,
        strava_exports=tuple(export.name for export in strava),
    )
