"""Lecture du manifeste de backtest : sorties, fichiers, provenance (``0010`` D2.6).

Le manifeste est un JSON UTF-8 posé sous ``MPA_DATA_DIR`` ; ses chemins sont
relatifs à son dossier. Chaque fichier cité est haché ; les traces sont lues ;
une sortie ou un relevé externe d'un autre athlète est refusé **avant tout calcul**,
sans qu'aucun de ses fichiers soit ouvert. Une trace illisible fait refuser
l'évaluation de sa sortie, pas la sortie : elle reste dans ``outings`` avec ses
instants déclarés, parce qu'elle compte pour la règle des sorties retenues (D0).

Les messages nomment la sortie et la clé, et les fichiers par leur chemin relatif au
manifeste, jamais absolu (règle 1 de ``CLAUDE.md``). Le résultat reste en mémoire :
il n'est ni sérialisé ni journalisé.
"""

import hashlib
import json
import re
from collections.abc import Mapping, Set
from dataclasses import dataclass
from datetime import UTC, date, datetime
from enum import StrEnum
from pathlib import Path, PurePosixPath, PureWindowsPath
from types import MappingProxyType
from typing import Any

from mountain_perf.gpx.reader import GpxError
from mountain_perf.gpx.trace_reader import TraceError, read_trace
from mountain_perf.schemas import (
    ArtifactRef,
    ArtifactRole,
    DataSet,
    ObservedPassage,
    Outing,
    OutingLabel,
    RecordedTrace,
    ReferenceKind,
    ReferencePerformance,
    RouteReference,
    SourceRef,
    Sport,
    TimingConvention,
)
from mountain_perf.validation import ContractError

SCHEMA_VERSION = 1
"""Seule version du format de manifeste lue."""

DECLARED_TIME_TOLERANCE_S = 1.0
"""Écart maximal (s) entre un ``start``/``end`` déclaré et l'instant de la trace.

Au-delà, le manifeste décrit une autre sortie que ses fichiers.
"""

UNKNOWN_ARTIFACT_KIND = "unknown"
"""``SourceRef.kind`` d'un doublon dont le nom n'a pas d'extension."""

GPX_ARTIFACT_KIND = "gpx"
"""``SourceRef.kind`` d'une trace ou d'une référence."""

MANIFEST_SOURCE_KIND = "manifest"
"""``SourceRef.kind`` du manifeste, source aussi des relevés externes."""

_TOP_KEYS = frozenset({"schema_version", "athlete_ref", "domain_start_date", "outings"})
_OUTING_KEYS = frozenset(
    {
        "id",
        "sport",
        "athlete_ref",
        "traces",
        "duplicates",
        "start",
        "end",
        "route",
        "variant",
        "portion_m",
        "reference",
        "dataset",
        "label",
        "external_records",
    }
)
_ARTIFACT_KEYS = frozenset({"file", "sha256"})
_REFERENCE_KEYS = frozenset({"file", "kind", "available_at", "sha256"})
_RECORD_KEYS = frozenset({"athlete_ref", "event_name", "date", "passages"})
_PASSAGE_KEYS = frozenset({"point_name", "elapsed_s", "distance_m", "convention"})
_DATE = re.compile(r"\d{4}-\d{2}-\d{2}")

# Champ d'``Outing`` → clé du manifeste, pour nommer la clé d'un contrat violé.
_OUTING_FIELD_KEYS = (
    ("start_time", "start"),
    ("end_time", "end"),
    ("declared_portion_m", "portion_m"),
    ("duplicates", "duplicates"),
    ("route_id", "route"),
    ("variant", "variant"),
)


class ManifestError(ValueError):
    """Manifeste inutilisable ; le message nomme la sortie et la clé fautives."""


@dataclass(frozen=True)
class RefusedEntry:
    """Sortie ou relevé refusé : identifiant de sortie, libellé du relevé (``None``
    pour une sortie) et motif en clair."""

    outing_id: str
    label: str | None
    reason: str


@dataclass(frozen=True)
class ManifestReadResult:
    """Manifeste lu : sorties de l'athlète, traces lues, emplacements, refus.

    - ``traces`` : trace lue de chaque sortie tracée non refusée, par identifiant ;
    - ``artifact_paths`` : chemin résolu de chaque fichier lu (traces, doublons,
      références des sorties de ``outings``), par empreinte ; deux fichiers de même
      contenu, interchangeables, n'y font qu'une entrée, la première rencontrée ;
    - ``refused`` : sorties refusées — d'un autre athlète (absentes de ``outings``) ou
      de trace illisible (présentes dans ``outings``, absentes de ``traces``) ;
    - ``refused_records`` : relevés externes d'un autre athlète.
    """

    source: SourceRef
    athlete_ref: str
    domain_start_date: date
    outings: tuple[Outing, ...]
    traces: Mapping[str, RecordedTrace]
    artifact_paths: Mapping[str, Path]
    refused: tuple[RefusedEntry, ...]
    refused_records: tuple[RefusedEntry, ...]


@dataclass(frozen=True)
class _File:
    path: Path
    content_hash: str


def _error(where: str, key: str, message: str) -> ManifestError:
    return ManifestError(f"{where}, clé {key} : {message}")


def _object(value: Any, where: str, key: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise _error(where, key, "objet JSON attendu.")
    return value


def _list(value: Any, where: str, key: str) -> list[Any]:
    if not isinstance(value, list):
        raise _error(where, key, "liste JSON attendue.")
    return value


def _check_keys(
    data: Mapping[str, Any],
    allowed: Set[str],
    required: Set[str],
    where: str,
    prefix: str = "",
) -> None:
    for key in data:
        if key not in allowed:
            raise _error(where, prefix + key, "clé inconnue.")
    for key in sorted(required):
        if key not in data:
            raise _error(where, prefix + key, "clé obligatoire absente.")


def _text(value: Any, where: str, key: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise _error(where, key, f"texte non vide attendu, reçu {value!r}.")
    return value


def _number(value: Any, where: str, key: str) -> float:
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise _error(where, key, f"nombre attendu, reçu {value!r}.")
    return float(value)


def _instant(value: Any, where: str, key: str) -> datetime:
    text = _text(value, where, key)
    try:
        instant = datetime.fromisoformat(text)
    except ValueError as error:
        raise _error(where, key, f"instant illisible {text!r}.") from error
    if instant.utcoffset() is None:
        raise _error(where, key, f"instant sans décalage horaire {text!r}.")
    return instant


def _date(value: Any, where: str, key: str) -> date:
    text = _text(value, where, key)
    try:
        if not _DATE.fullmatch(text):
            raise ValueError(text)
        return date.fromisoformat(text)
    except ValueError as error:
        raise _error(where, key, f"date AAAA-MM-JJ attendue, reçu {text!r}.") from error


def _enum[E: StrEnum](cls: type[E], value: Any, where: str, key: str) -> E:
    if isinstance(value, str):
        for member in cls:
            if member.value == value:
                return member
    allowed = ", ".join(member.value for member in cls)
    raise _error(where, key, f"valeur inconnue {value!r} (admises : {allowed}).")


def _contract_key(error: ContractError) -> str:
    """Clé du manifeste du premier champ d'``Outing`` que nomme ``error``."""
    text = str(error)
    named = [
        (text.find(field), key) for field, key in _OUTING_FIELD_KEYS if field in text
    ]
    return min(named)[1] if named else "(sortie)"


def _duplicate_kind(name: str) -> str:
    """Suffixe du nom sans son point, en minuscules ; ``unknown`` s'il est vide."""
    return PurePosixPath(name).suffix[1:].lower() or UNKNOWN_ARTIFACT_KIND


class _Reader:
    """État d'une lecture : dossier, provenance, emplacements, traces et refus."""

    def __init__(self, folder: Path, source: SourceRef) -> None:
        self._folder = folder
        self._source = source
        self._athlete = ""
        self._paths: dict[str, Path] = {}
        self._traces: dict[str, RecordedTrace] = {}
        self._refused: list[RefusedEntry] = []
        self._refused_records: list[RefusedEntry] = []

    def read(self, document: Any) -> ManifestReadResult:
        where = "manifeste"
        top = _object(document, where, "(racine)")
        _check_keys(top, _TOP_KEYS, _TOP_KEYS, where)
        version = top["schema_version"]
        if type(version) is not int or version != SCHEMA_VERSION:
            raise _error(
                where,
                "schema_version",
                f"doit valoir {SCHEMA_VERSION}, reçu {version!r}.",
            )
        self._athlete = _text(top["athlete_ref"], where, "athlete_ref")
        domain_start_date = _date(top["domain_start_date"], where, "domain_start_date")
        seen: set[str] = set()
        outings = [
            outing
            for index, entry in enumerate(_list(top["outings"], where, "outings"))
            if (outing := self._outing(entry, index, seen)) is not None
        ]
        return ManifestReadResult(
            source=self._source,
            athlete_ref=self._athlete,
            domain_start_date=domain_start_date,
            outings=tuple(outings),
            traces=MappingProxyType(self._traces),
            artifact_paths=MappingProxyType(self._paths),
            refused=tuple(self._refused),
            refused_records=tuple(self._refused_records),
        )

    def _outing(self, entry: Any, index: int, seen: set[str]) -> Outing | None:
        where = f"sortie n°{index + 1}"
        data = _object(entry, where, f"outings[{index}]")
        if "id" not in data:
            raise _error(where, "id", "clé obligatoire absente.")
        outing_id = _text(data["id"], where, "id")
        where = f"sortie {outing_id}"
        if outing_id in seen:
            raise _error(where, "id", "identifiant en double.")
        seen.add(outing_id)
        _check_keys(data, _OUTING_KEYS, {"id", "sport"}, where)
        athlete = _text(data.get("athlete_ref", self._athlete), where, "athlete_ref")
        if athlete != self._athlete:
            self._refused.append(
                RefusedEntry(
                    outing_id,
                    None,
                    "athlete_ref différent de celui du manifeste : ce n'est pas une "
                    "sortie de l'athlète (0010 D2.6).",
                )
            )
            return None

        sport = _enum(Sport, data["sport"], where, "sport")
        traces = self._files(data.get("traces", []), where, "traces")
        duplicates = self._files(data.get("duplicates", []), where, "duplicates")
        declared = {
            key: _instant(data[key], where, key) if data.get(key) is not None else None
            for key in ("start", "end")
        }
        reference = self._reference(data.get("reference"), where)
        records = self._records(data.get("external_records", []), where, outing_id)

        trace: RecordedTrace | None = None
        if traces:
            try:
                trace = read_trace([file.path for file in traces])
            except (GpxError, TraceError, ContractError) as error:
                names = ", ".join(file.path.name for file in traces)
                self._refused.append(
                    RefusedEntry(outing_id, None, f"trace refusée ({names}) : {error}")
                )
        if trace is not None:
            for key, actual in (("start", trace.start_time), ("end", trace.end_time)):
                expected = declared[key]
                if (
                    expected is not None
                    and abs((expected - actual).total_seconds())
                    > DECLARED_TIME_TOLERANCE_S
                ):
                    raise _error(
                        where,
                        key,
                        f"à plus de {DECLARED_TIME_TOLERANCE_S:g} s de celui de la "
                        "trace.",
                    )
            start_time, end_time = trace.start_time, trace.end_time
        else:
            reason = "trace refusée" if traces else "sortie non tracée"
            declared_start, declared_end = declared["start"], declared["end"]
            if declared_start is None:
                raise _error(where, "start", f"obligatoire ({reason}).")
            if declared_end is None:
                raise _error(where, "end", f"obligatoire ({reason}).")
            start_time, end_time = declared_start, declared_end

        def observation(file: _File, kind: str) -> ArtifactRef:
            return ArtifactRef(
                self._source_ref(file, kind),
                end_time,
                ArtifactRole.EVALUATION_OBSERVATION,
            )

        try:
            outing = Outing(
                outing_id=outing_id,
                athlete_ref=athlete,
                sport=sport,
                start_time=start_time,
                end_time=end_time,
                traces=tuple(observation(file, GPX_ARTIFACT_KIND) for file in traces),
                duplicates=tuple(
                    observation(file, _duplicate_kind(file.path.name))
                    for file in duplicates
                ),
                route_id=self._optional_text(data.get("route"), where, "route"),
                variant=self._optional_text(data.get("variant"), where, "variant"),
                declared_portion_m=self._portion(data.get("portion_m"), where),
                reference=reference[0] if reference else None,
                dataset=(
                    _enum(DataSet, data["dataset"], where, "dataset")
                    if data.get("dataset") is not None
                    else None
                ),
                label=(
                    _enum(OutingLabel, data["label"], where, "label")
                    if data.get("label") is not None
                    else None
                ),
                external_records=records,
            )
        except ContractError as error:
            raise _error(where, _contract_key(error), f"{error}") from error
        for file in (*traces, *duplicates, *(reference[1:] if reference else ())):
            self._paths.setdefault(file.content_hash, file.path)
        if trace is not None:
            self._traces[outing_id] = trace
        return outing

    def _file(self, data: Mapping[str, Any], where: str, key: str) -> _File:
        """Fichier ``data["file"]``, résolu, existant, haché et recoupé à ``sha256``."""
        text = _text(data["file"], where, f"{key}.file")
        relative = PurePosixPath(text)
        if (
            "\\" in text
            or relative.is_absolute()
            or PureWindowsPath(text).drive
            or ".." in relative.parts
        ):
            raise _error(
                where,
                f"{key}.file",
                "chemin relatif au manifeste attendu, séparé par « / » et sans "
                f"« .. », reçu {text!r}.",
            )
        path = self._folder.joinpath(*relative.parts).resolve()
        if not path.is_file():
            raise _error(where, f"{key}.file", f"fichier introuvable ({text}).")
        content_hash = hashlib.sha256(path.read_bytes()).hexdigest()
        if "sha256" in data:
            declared = _text(data["sha256"], where, f"{key}.sha256")
            if declared.lower() != content_hash:
                raise _error(
                    where,
                    f"{key}.sha256",
                    f"empreinte déclarée différente du contenu ({text}).",
                )
        return _File(path, content_hash)

    def _files(self, value: Any, where: str, key: str) -> tuple[_File, ...]:
        files = []
        for k, item in enumerate(_list(value, where, key)):
            data = _object(item, where, f"{key}[{k}]")
            _check_keys(data, _ARTIFACT_KEYS, {"file"}, where, f"{key}[{k}].")
            files.append(self._file(data, where, f"{key}[{k}]"))
        return tuple(files)

    def _reference(self, value: Any, where: str) -> tuple[RouteReference, _File] | None:
        if value is None:
            return None
        data = _object(value, where, "reference")
        _check_keys(
            data, _REFERENCE_KEYS, _REFERENCE_KEYS - {"sha256"}, where, "reference."
        )
        kind = _enum(ReferenceKind, data["kind"], where, "reference.kind")
        available_at = _instant(data["available_at"], where, "reference.available_at")
        file = self._file(data, where, "reference")
        artifact = ArtifactRef(
            self._source_ref(file, GPX_ARTIFACT_KIND),
            available_at,
            ArtifactRole.FORECAST_INPUT,
        )
        return RouteReference(kind, artifact), file

    def _records(
        self, value: Any, where: str, outing_id: str
    ) -> tuple[ReferencePerformance, ...]:
        records = []
        for k, item in enumerate(_list(value, where, "external_records")):
            key = f"external_records[{k}]"
            data = _object(item, where, key)
            _check_keys(data, _RECORD_KEYS, _RECORD_KEYS, where, f"{key}.")
            event_name = _text(data["event_name"], where, f"{key}.event_name")
            athlete = _text(data["athlete_ref"], where, f"{key}.athlete_ref")
            if athlete != self._athlete:
                self._refused_records.append(
                    RefusedEntry(
                        outing_id,
                        event_name,
                        "athlete_ref différent de celui du manifeste : relevé d'un "
                        "autre athlète (0010 D2.6).",
                    )
                )
                continue
            record_date = _date(data["date"], where, f"{key}.date")
            passages = tuple(
                self._passage(passage, where, f"{key}.passages[{j}]")
                for j, passage in enumerate(
                    _list(data["passages"], where, f"{key}.passages")
                )
            )
            try:
                records.append(
                    ReferencePerformance(
                        athlete_ref=athlete,
                        event_name=event_name,
                        date=record_date,
                        passages=passages,
                        source=self._source,
                    )
                )
            except ContractError as error:
                raise _error(where, key, f"{error}") from error
        return tuple(records)

    def _passage(self, value: Any, where: str, key: str) -> ObservedPassage:
        data = _object(value, where, key)
        _check_keys(
            data,
            _PASSAGE_KEYS,
            {"point_name", "elapsed_s", "convention"},
            where,
            f"{key}.",
        )
        distance = data.get("distance_m")
        try:
            return ObservedPassage(
                point_name=_text(data["point_name"], where, f"{key}.point_name"),
                elapsed_s=_number(data["elapsed_s"], where, f"{key}.elapsed_s"),
                distance_m=(
                    _number(distance, where, f"{key}.distance_m")
                    if distance is not None
                    else None
                ),
                convention=_enum(
                    TimingConvention, data["convention"], where, f"{key}.convention"
                ),
            )
        except ContractError as error:
            raise _error(where, key, f"{error}") from error

    def _optional_text(self, value: Any, where: str, key: str) -> str | None:
        return None if value is None else _text(value, where, key)

    def _portion(self, value: Any, where: str) -> tuple[float, float] | None:
        if value is None:
            return None
        items = _list(value, where, "portion_m")
        if len(items) != 2:
            raise _error(where, "portion_m", f"couple [a, b] attendu, reçu {items!r}.")
        return (
            _number(items[0], where, "portion_m[0]"),
            _number(items[1], where, "portion_m[1]"),
        )

    def _source_ref(self, file: _File, kind: str) -> SourceRef:
        return SourceRef(
            kind=kind,
            identifier=file.path.name,
            content_hash=file.content_hash,
            retrieved_at=self._source.retrieved_at,
        )


def load_manifest(path: Path) -> ManifestReadResult:
    """Lit le manifeste ``path`` selon les règles 1 à 8 du § 4.5 du brief M4a-1.

    ``ManifestError`` pour tout manifeste mal formé ; les refus d'athlète et de trace
    ne sont pas des erreurs : ils sont rapportés dans ``refused`` et
    ``refused_records``.
    """
    content = path.read_bytes()
    source = SourceRef(
        kind=MANIFEST_SOURCE_KIND,
        identifier=path.name,
        content_hash=hashlib.sha256(content).hexdigest(),
        retrieved_at=datetime.now(UTC),
    )
    try:
        document = json.loads(content.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ManifestError(f"manifeste : JSON illisible ({error}).") from error
    return _Reader(path.parent, source).read(document)
