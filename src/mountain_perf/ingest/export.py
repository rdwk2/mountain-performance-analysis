"""L'ingestion d'un export Garmin : ``raw/`` → ``interim/activities/`` (AN1-1,
``docs/decisions/0013``, point 5). Demande l'extra ``ingest`` : il lit les FIT par
``mountain_perf.ingest.fit``.

Un seul export, à la racine de ``raw/`` : ``raw/acquisition.json`` (l'instant
d'acquisition), ``raw/activities/activities.json`` (l'index),
``raw/activity_fit/<identifiant>.zip`` (une archive par activité, qui contient un seul
``.fit``). Ne lit que ``raw/``, qu'il n'écrit jamais, et n'écrit que sous ``interim/`` ;
deux ingestions des mêmes fichiers écrivent les mêmes octets.
"""

import dataclasses
import hashlib
import io
import json
import zipfile
import zlib
from collections import Counter
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from mountain_perf.ingest.fit import FitRefusedError, read_fit
from mountain_perf.ingest.index import IndexReadError, read_index
from mountain_perf.ingest.interim import write_activities
from mountain_perf.ingest.views import activity_view
from mountain_perf.schemas import (
    ActivityIndex,
    ActivityRecording,
    IndexedActivity,
    IngestionReport,
    ReadFile,
    RecordingMismatch,
    RefusalReason,
    RefusedFile,
    SourceRef,
    ViewRefusal,
    ViewRefusalCount,
)

ACQUISITION_FILE = "acquisition.json"
"""Le fichier de ``raw/`` qui porte l'instant d'acquisition de l'export : un objet JSON
à la seule clé ``retrieved_at``, un instant ISO 8601 avec fuseau."""

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
)
"""Ce que lève la lecture d'un membre illisible : CRC faux, compression inconnue,
contenu chiffré, archive tronquée."""


class IngestError(Exception):
    """L'export ne peut pas être ingéré ; rien n'est écrit. Le message dit pourquoi."""


@dataclass(frozen=True)
class IngestionSummary:
    """Ce que l'ingestion a fait, en nombres.

    - ``activities`` — entrées de l'index écrit ;
    - ``recordings`` — enregistrements écrits ;
    - ``refused_files`` — fichiers de ``raw/activity_fit/`` refusés ;
    - ``refused_entries`` — entrées du fichier d'index refusées ;
    - ``entries_without_archive`` — entrées de l'index dont aucun fichier de
      ``raw/activity_fit/`` n'a le nom sans extension ;
    - ``mismatches`` — enregistrements en désaccord avec leur entrée ;
    - ``view_refusals`` — les entrées sans vue ``Activity``, comptées par (motif, type),
      celles du rapport.
    """

    activities: int
    recordings: int
    refused_files: int
    refused_entries: int
    entries_without_archive: int
    mismatches: int
    view_refusals: tuple[ViewRefusalCount, ...]


def _acquisition(raw_dir: Path) -> tuple[datetime, bytes]:
    try:
        data = (raw_dir / ACQUISITION_FILE).read_bytes()
    except FileNotFoundError:
        raise IngestError(
            "raw/acquisition.json manque : l'instant d'acquisition de l'export est "
            "requis."
        ) from None
    try:
        content = json.loads(data.decode("utf-8-sig"))
    except ValueError:
        raise IngestError("raw/acquisition.json : JSON en UTF-8 attendu.") from None
    if not isinstance(content, dict) or set(content) != {"retrieved_at"}:
        raise IngestError("raw/acquisition.json : objet {retrieved_at} attendu.")
    value = content["retrieved_at"]
    instant: datetime | None = None
    if isinstance(value, str):
        try:
            instant = datetime.fromisoformat(value)
        except ValueError:
            instant = None
    if instant is None or instant.utcoffset() is None:
        raise IngestError(
            "raw/acquisition.json : retrieved_at doit être un instant ISO 8601 avec "
            "fuseau."
        )
    return instant, data


def read_acquisition(raw_dir: Path) -> datetime:
    """L'instant d'acquisition de l'export rangé dans ``raw_dir``, lu dans
    ``acquisition.json``, tel que ``datetime.fromisoformat`` le lit (décalage compris,
    aucune conversion en UTC).

    Lève ``IngestError`` : fichier absent (« raw/acquisition.json manque : l'instant
    d'acquisition de l'export est requis. ») ; octets qui ne se décodent pas en
    ``utf-8-sig`` puis en JSON, une marque d'ordre des octets en tête étant admise, pas
    l'UTF-16 (« raw/acquisition.json : JSON en UTF-8 attendu. ») ; autre chose qu'un
    objet à la seule clé ``retrieved_at`` (« raw/acquisition.json : objet
    {retrieved_at} attendu. ») ; valeur qui n'est pas un texte, texte que
    ``datetime.fromisoformat`` refuse, ou instant sans fuseau (« raw/acquisition.json :
    retrieved_at doit être un instant ISO 8601 avec fuseau. »). Une autre erreur d'E/S
    que l'absence du fichier se propage (``OSError``).
    """
    return _acquisition(raw_dir)[0]


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
    """Ingère l'export de ``data_dir/raw/`` et écrit ``data_dir/interim/activities/``.

    Dans cet ordre :

    1. l'instant d'acquisition (``read_acquisition``) ;
    2. l'index, ``raw/activities/activities.json`` : absent, ``IngestError``
       (« raw/activities/activities.json manque. ») ; illisible, ``IngestError`` au
       message de l'``IndexReadError`` ;
    3. chaque **fichier** de ``raw/activity_fit/`` (un sous-dossier est ignoré ; dossier
       absent : aucun), par nom croissant : lu, empreint (SHA-256 des octets de
       l'archive), inscrit au rapport sous le nom ``activity_fit/<nom>`` ; un nom qui
       contient « : » ou « \\ » arrête l'ingestion avant sa lecture (``IngestError``) ;
       un nom sans extension que portent plusieurs fichiers fait refuser chacun d'eux
       ``DUPLICATE_ARCHIVE``, avant tout autre contrôle ; sinon, nom sans extension
       absent des entrées gardées de l'index : ``NOT_IN_INDEX`` ; sinon, archive qui
       n'est pas un zip à un seul membre ``.fit`` lisible : ``NOT_ONE_FIT`` ; sinon
       ``read_fit``, ou le motif de son refus ;
    4. l'index : les entrées gardées, ``has_recording`` vrai pour celles qui ont reçu un
       enregistrement, triées par (instant de départ, identifiant) ;
    5. les refus de vue : ``activity_view`` de chaque entrée, comptés par (motif, type
       de la source), triés ainsi ;
    6. les désaccords : un ``RecordingMismatch`` quand l'écart des départs, ou celui des
       temps écoulés (somme des sessions, si toutes le portent, contre
       ``elapsed_duration_s``, s'il est présent), dépasse strictement
       ``MISMATCH_TOLERANCE_S`` ; triés par identifiant ;
    7. le rapport : l'instant d'acquisition, les fichiers lus et refusés, triés par
       nom, les entrées refusées, les refus de vue, les désaccords ;
    8. ``write_activities``.

    Une erreur avant l'étape 8 n'écrit rien.
    """
    raw = data_dir / "raw"
    retrieved_at, acquisition = _acquisition(raw)
    try:
        index_bytes = (raw / _INDEX_FILE).read_bytes()
    except FileNotFoundError:
        raise IngestError("raw/activities/activities.json manque.") from None
    try:
        index_read = read_index(index_bytes)
    except IndexReadError as error:
        raise IngestError(str(error)) from None
    entries = {entry.activity_ref: entry for entry in index_read.entries}

    fit_dir = raw / _FIT_DIR
    files = (
        sorted(
            (path for path in fit_dir.iterdir() if path.is_file()),
            key=lambda path: path.name,
        )
        if fit_dir.is_dir()
        else []
    )
    stems = Counter(path.stem for path in files)
    read = [
        ReadFile(ACQUISITION_FILE, _sha256(acquisition)),
        ReadFile(_INDEX_FILE.as_posix(), _sha256(index_bytes)),
    ]
    refused_files: list[RefusedFile] = []
    recordings: list[ActivityRecording] = []
    for path in files:
        if ":" in path.name or "\\" in path.name:
            raise IngestError(
                f"raw/{_FIT_DIR}/{path.name} : nom de fichier que le rapport ne peut "
                "pas porter (« : » ou « \\ »)."
            )
        archive = path.read_bytes()
        content_hash = _sha256(archive)
        name = f"{_FIT_DIR}/{path.name}"
        read.append(ReadFile(name, content_hash))
        reason: RefusalReason | None = None
        if stems[path.stem] > 1:
            reason = RefusalReason.DUPLICATE_ARCHIVE
        elif path.stem not in entries:
            reason = RefusalReason.NOT_IN_INDEX
        else:
            member = _fit_member(archive)
            if member is None:
                reason = RefusalReason.NOT_ONE_FIT
            else:
                source = SourceRef("garmin_fit", path.name, content_hash, retrieved_at)
                try:
                    recordings.append(
                        read_fit(member, activity_ref=path.stem, source=source)
                    )
                except FitRefusedError as error:
                    reason = error.reason
        if reason is not None:
            refused_files.append(RefusedFile(name, reason))

    received = {recording.activity_ref for recording in recordings}
    kept = sorted(
        (
            dataclasses.replace(entry, has_recording=entry.activity_ref in received)
            for entry in index_read.entries
        ),
        key=lambda entry: (entry.start_time.timestamp(), entry.activity_ref),
    )
    index = ActivityIndex(
        tuple(kept),
        SourceRef(
            "garmin_activities",
            _INDEX_FILE.name,
            _sha256(index_bytes),
            retrieved_at,
        ),
    )

    refusals: Counter[tuple[ViewRefusal, str]] = Counter()
    for entry in index.entries:
        refusal = activity_view(index, entry).refusal
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
        mismatch = _mismatch(recording, entries[recording.activity_ref])
        if mismatch is not None:
            found.append(mismatch)
    mismatches = tuple(sorted(found, key=lambda mismatch: mismatch.activity_ref))

    report = IngestionReport(
        retrieved_at=retrieved_at,
        read=tuple(sorted(read, key=lambda item: item.name)),
        refused_files=tuple(sorted(refused_files, key=lambda item: item.name)),
        refused_entries=index_read.refused,
        view_refusals=view_refusals,
        mismatches=mismatches,
    )
    write_activities(data_dir, index, recordings, report)
    archived = set(stems)
    return IngestionSummary(
        activities=len(index.entries),
        recordings=len(recordings),
        refused_files=len(refused_files),
        refused_entries=len(index_read.refused),
        entries_without_archive=sum(
            entry.activity_ref not in archived for entry in index.entries
        ),
        mismatches=len(mismatches),
        view_refusals=view_refusals,
    )
