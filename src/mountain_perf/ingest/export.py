"""L'ingestion des exports Garmin : ``raw/garmin/`` → ``interim/activities/`` (AN1-1,
AN2-0, ``docs/decisions/0013``). Demande l'extra ``ingest`` : il lit les FIT par
``mountain_perf.ingest.fit``.

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
from dataclasses import dataclass
from datetime import datetime
from itertools import pairwise
from pathlib import Path

from mountain_perf.ingest.fit import FitRefusedError, read_fit
from mountain_perf.ingest.index import IndexReadError, read_index
from mountain_perf.ingest.interim import write_activities
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


class IngestError(Exception):
    """L'export ne peut pas être ingéré ; rien n'est écrit. Le message dit pourquoi."""


@dataclass(frozen=True)
class IngestionSummary:
    """Ce que l'ingestion a fait, en nombres.

    - ``exports`` — les exports lus, ceux du rapport (AN2-0) ;
    - ``activities`` — entrées de l'index écrit ;
    - ``recordings`` — enregistrements écrits ;
    - ``refused_files`` — fichiers de ``raw/garmin/<export>/activity_fit/`` refusés,
      avant la lecture de leur FIT ou par elle, chacun une fois ;
    - ``refused_entries`` — entrées des fichiers d'index refusées, tous exports ;
    - ``entries_without_archive`` — entrées de l'index écrit dont aucun export n'a de
      fichier de ``activity_fit/`` à ce nom sans extension ;
    - ``mismatches`` — enregistrements en désaccord avec leur entrée ;
    - ``view_refusals`` — les entrées sans vue ``Activity``, comptées par (motif, type),
      celles du rapport ;
    - ``retired`` — activités retirées de la source (AN2-0) ;
    - ``index_differences`` — par champ, activités dont l'entrée diffère d'un export à
      l'autre, celles du rapport (AN2-0) ;
    - ``fit_differences`` — activités dont deux exports portent des FIT différents ;
    - ``recordings_from_other_export`` — enregistrements tirés d'un autre export que
      l'entrée de leur activité.
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

    Lève ``IngestError`` : un export laissé à plat, l'ancienne disposition, dans
    ``raw/`` ou dans ``raw/garmin/`` (son ``acquisition.json``, ou sinon son dossier
    ``activities/`` : « raw/acquisition.json : un export Garmin se range dans son
    dossier, raw/garmin/<export>/ ; ranger celui-ci dans le sien. ») ; aucun dossier
    dans ``raw/garmin/``, ou ``raw/garmin/`` absent (« raw/garmin/ ne contient aucun
    export : chacun se range dans raw/garmin/<export>/, avec son acquisition.json. ») ;
    un nom de dossier que ``require_export_name`` refuse (« raw/garmin/<nom>/ : le nom
    d'un export est fait de lettres et de chiffres ASCII, de « _ », « . » ou « - ». »).
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
    if not dirs:
        raise IngestError(
            f"raw/{GARMIN_DIR}/ ne contient aucun export : chacun se range dans "
            f"raw/{GARMIN_DIR}/<export>/, avec son {ACQUISITION_FILE}."
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


def ingest_export(data_dir: Path) -> IngestionSummary:
    """Ingère les exports de ``data_dir/raw/garmin/`` et écrit
    ``data_dir/interim/activities/``.

    Dans cet ordre :

    1. les dossiers d'exports (``export_dirs``) ; puis, pour chacun par nom croissant,
       ``_load`` : l'instant d'acquisition, l'index (chaque entrée gardée porte la
       provenance de son fichier d'index), une entrée gardée partie après l'instant
       d'acquisition, les noms des fichiers de ``activity_fit/`` ;
    2. les exports, triés par instant d'acquisition ; deux instants égaux :
       ``IngestError`` (« raw/garmin/<a>/ et raw/garmin/<b>/ : même instant
       d'acquisition ; l'ordre des exports serait indéterminé. », ``a`` et ``b`` par nom
       croissant) ;
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
    7. l'index : les entrées gardées, ``has_recording`` vrai pour celles qui ont reçu un
       enregistrement, triées par (instant de départ, identifiant) ; les exports, par
       instant d'acquisition ;
    8. les refus de vue (``activity_view``), comptés par (motif, type de la source) ;
       les désaccords d'un enregistrement avec son entrée (au-delà de
       ``MISMATCH_TOLERANCE_S``), triés par identifiant ;
    9. le rapport, puis ``write_activities``.

    Une erreur avant ``write_activities`` n'écrit rien.
    """
    exports = sorted(
        (_load(path) for path in export_dirs(data_dir / "raw")),
        key=lambda export: (export.retrieved_at, export.name),
    )
    for first, second in pairwise(exports):
        if first.retrieved_at == second.retrieved_at:
            raise IngestError(
                f"{_label(first.name)}/ et {_label(second.name)}/ : même instant "
                "d'acquisition ; l'ordre des exports serait indéterminé."
            )

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
    fit_differences = 0
    for ref in sorted(decisive):
        candidates = archives.get(ref, {})
        members = {
            hashlib.sha256(item.member).digest()
            for item in candidates.values()
            if item.member is not None
        }
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

    kept = sorted(
        (
            dataclasses.replace(
                exports[position].entries[ref],
                has_recording=ref in recording_export,
            )
            for ref, position in decisive.items()
        ),
        key=lambda entry: (entry.start_time.timestamp(), entry.activity_ref),
    )
    index = ActivityIndex(tuple(kept), tuple(export.index_source for export in exports))

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
    mismatches = tuple(sorted(found, key=lambda mismatch: mismatch.activity_ref))
    index_differences = tuple(
        FieldDifferenceCount(field, differences[field])
        for field in sorted(differences, key=lambda field: field.value)
    )
    from_other = sum(
        position != decisive[ref] for ref, position in recording_export.items()
    )
    export_reports = tuple(
        ExportReport(
            name=export.name,
            index=export.index_source,
            period_start=export.period_start,
            entries=len(export.entries),
            refused_entries=export.refused,
            archives=len(export.archives),
        )
        for export in exports
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
    write_activities(data_dir, index, recordings, report)
    return IngestionSummary(
        exports=export_reports,
        activities=len(index.entries),
        recordings=len(recordings),
        refused_files=len(refused_files),
        refused_entries=sum(len(export.refused) for export in exports),
        entries_without_archive=sum(
            entry.activity_ref not in all_stems for entry in index.entries
        ),
        mismatches=len(mismatches),
        view_refusals=view_refusals,
        retired=len(retired),
        index_differences=index_differences,
        fit_differences=fit_differences,
        recordings_from_other_export=from_other,
    )
