"""Manifeste de backtest (§ 4.5 du brief M4a-1, ``0010`` D2.6).

Fixture : ``tests/fixtures/manifeste/`` (voir son ``README.md``). Chaque variante
copie le dossier dans ``tmp_path`` et réécrit le JSON modifié : un test par règle du
§ 4.5, les attendus du § 7.1, et les emplacements (``artifact_paths``).
"""

import hashlib
import json
import re
import shutil
from collections.abc import Callable
from dataclasses import FrozenInstanceError
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

import pytest

from fixtures.traces import equatorial_point, gpx_document
from mountain_perf.backtest.manifest import (
    ManifestError,
    ManifestReadResult,
    RefusedEntry,
    load_manifest,
)
from mountain_perf.gpx.reader import GpxError
from mountain_perf.gpx.trace_reader import read_trace
from mountain_perf.schemas import (
    ArtifactRef,
    ArtifactRole,
    DataSet,
    Outing,
    OutingLabel,
    ReferenceKind,
    Sport,
    TimingConvention,
)

FIXTURE = Path(__file__).parent / "fixtures" / "manifeste"
P1, P2, VELO = "p1-2026-06-07", "p2-2026-06-10", "velo-2026-06-07"

Document = dict[str, Any]


def _document() -> Document:
    document: Document = json.loads(
        (FIXTURE / "manifeste.json").read_text(encoding="utf-8")
    )
    return document


def _copy(tmp_path: Path) -> Path:
    folder = tmp_path / "manifeste"
    shutil.copytree(FIXTURE, folder)
    return folder


def _variant(tmp_path: Path, change: Callable[[Document], object]) -> Path:
    """Dossier copié, manifeste modifié par ``change`` puis réécrit."""
    folder = tmp_path / "manifeste"
    if not folder.exists():
        _copy(tmp_path)
    document = _document()
    change(document)
    path = folder / "manifeste.json"
    path.write_text(json.dumps(document, ensure_ascii=False), encoding="utf-8")
    return path


def _outing(document: Document, outing_id: str) -> dict[str, Any]:
    entry: dict[str, Any] = next(o for o in document["outings"] if o["id"] == outing_id)
    return entry


def _by_id(result: ManifestReadResult, outing_id: str) -> Outing:
    return next(o for o in result.outings if o.outing_id == outing_id)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _decreasing_gpx() -> str:
    return gpx_document(
        [
            equatorial_point(0.0, "2026-06-07T06:00:10Z"),
            equatorial_point(1.0, "2026-06-07T06:00:00Z"),
        ]
    )


@pytest.fixture(scope="module")
def valid() -> ManifestReadResult:
    return load_manifest(FIXTURE / "manifeste.json")


# ---------------------------------------------------------------------------
# Manifeste valide
# ---------------------------------------------------------------------------


def test_header_and_source(valid: ManifestReadResult) -> None:
    assert valid.athlete_ref == "athlete-1"
    assert valid.domain_start_date == date(2026, 5, 20)
    assert valid.source.kind == "manifest"
    assert valid.source.identifier == "manifeste.json"
    assert valid.source.content_hash == _sha256(FIXTURE / "manifeste.json")
    assert valid.refused == valid.refused_records == ()


def test_rule_8_outings_keep_the_manifest_order(
    valid: ManifestReadResult, tmp_path: Path
) -> None:
    assert [o.outing_id for o in valid.outings] == [P1, P2, VELO]
    reversed_ = load_manifest(
        _variant(tmp_path, lambda d: d["outings"].reverse())
    ).outings
    assert [o.outing_id for o in reversed_] == [VELO, P2, P1]


def test_declarations_are_read(valid: ManifestReadResult) -> None:
    p1, p2, velo = valid.outings
    assert (p1.sport, p2.sport, velo.sport) == (Sport.FOOT, Sport.FOOT, Sport.MTB)
    assert (p1.route_id, p1.variant, p1.declared_portion_m) == ("p1", None, None)
    assert (p2.route_id, p2.declared_portion_m) == ("p2", (0.0, 2500.0))
    assert (p1.dataset, p2.dataset, velo.dataset) == (
        DataSet.REPEATABILITY,
        DataSet.DEVELOPMENT,
        None,
    )
    assert (p1.label, p2.label, velo.label) == (
        OutingLabel.TRAINING,
        OutingLabel.RACE,
        None,
    )
    assert all(o.athlete_ref == "athlete-1" for o in valid.outings)


def test_rule_4_traced_outing_times_come_from_the_trace(
    valid: ManifestReadResult,
) -> None:
    p1 = _by_id(valid, P1)
    assert p1.start_time == datetime(2026, 6, 7, 6, 0, tzinfo=UTC)
    assert p1.end_time == datetime(2026, 6, 7, 6, 0, 30, tzinfo=UTC)
    assert valid.traces[P1].start_time == p1.start_time
    assert valid.traces[P1].end_time == p1.end_time
    assert set(valid.traces) == {P1, P2}


def test_t28_two_segment_files_make_one_outing_one_trace_one_day(
    valid: ManifestReadResult,
) -> None:
    """Deux fichiers d'un même enregistrement : une seule sortie (``0010`` D2.6)."""
    assert [o.outing_id for o in valid.outings].count(P2) == 1
    p2 = _by_id(valid, P2)
    trace = valid.traces[P2]
    assert [a.source.identifier for a in p2.traces] == ["matin_1.gpx", "matin_2.gpx"]
    assert [s.identifier for s in trace.sources] == ["matin_1.gpx", "matin_2.gpx"]
    assert trace.time_s == (0.0, 5.0, 10.0, 40.0, 45.0, 50.0)
    assert p2.start_time.date() == p2.end_time.date() == date(2026, 6, 10)


def test_rule_5_untraced_outing_uses_its_declared_times(
    valid: ManifestReadResult,
) -> None:
    velo = _by_id(valid, VELO)
    assert velo.traces == velo.duplicates == ()
    assert velo.start_time == datetime(2026, 6, 7, 15, 0, tzinfo=UTC)
    assert velo.end_time == datetime(2026, 6, 7, 16, 10, tzinfo=UTC)
    assert VELO not in valid.traces


def test_rule_3_roles_availability_and_hashes(valid: ManifestReadResult) -> None:
    p1 = _by_id(valid, P1)
    for artifact in (*p1.traces, *p1.duplicates):
        assert artifact.role is ArtifactRole.EVALUATION_OBSERVATION
        assert artifact.available_at == p1.end_time
    assert p1.reference is not None
    assert p1.reference.kind is ReferenceKind.PREPARED
    assert p1.reference.artifact.role is ArtifactRole.FORECAST_INPUT
    assert p1.reference.artifact.available_at == datetime(
        2026, 5, 24, 18, 0, tzinfo=UTC
    )
    assert p1.traces[0].source.content_hash == _sha256(FIXTURE / "gpx/p1/jour3.gpx")
    assert p1.duplicates[0].source.content_hash == _sha256(FIXTURE / "gpx/p1/jour3.fit")


def test_rule_1_identifiers_are_file_names_only(valid: ManifestReadResult) -> None:
    p1 = _by_id(valid, P1)
    assert p1.reference is not None
    identifiers = [
        a.source.identifier for a in (*p1.traces, *p1.duplicates, p1.reference.artifact)
    ]
    assert identifiers == ["jour3.gpx", "jour3.fit", "prepare.gpx"]


def test_source_kinds(valid: ManifestReadResult) -> None:
    p1 = _by_id(valid, P1)
    assert p1.reference is not None
    assert p1.traces[0].source.kind == "gpx"
    assert p1.duplicates[0].source.kind == "fit"
    assert p1.reference.artifact.source.kind == "gpx"


def test_duplicates_are_hashed_never_read_as_gpx(valid: ManifestReadResult) -> None:
    """Le doublon de la fixture n'est pas du GPX : le lire échouerait."""
    with pytest.raises(GpxError, match="XML mal formé"):
        read_trace([FIXTURE / "gpx/p1/jour3.fit"])
    assert _by_id(valid, P1).duplicates[0].source.identifier == "jour3.fit"
    assert valid.refused == ()


def test_rule_7_external_record_is_built_from_the_manifest(
    valid: ManifestReadResult,
) -> None:
    (record,) = _by_id(valid, P2).external_records
    assert record.source == valid.source
    assert (record.athlete_ref, record.event_name) == ("athlete-1", "Relevé inventé")
    assert record.date == date(2026, 6, 10)
    assert [
        (p.point_name, p.elapsed_s, p.distance_m, p.convention) for p in record.passages
    ] == [
        ("Départ", 0.0, None, TimingConvention.DEPARTURE),
        ("Arrivée", 50.0, 2500.0, TimingConvention.ARRIVAL),
    ]


# ---------------------------------------------------------------------------
# Emplacements (§ 4.5)
# ---------------------------------------------------------------------------


def _all_artifacts(result: ManifestReadResult) -> list[ArtifactRef]:
    return [
        artifact
        for outing in result.outings
        for artifact in (
            *outing.traces,
            *outing.duplicates,
            *((outing.reference.artifact,) if outing.reference else ()),
        )
    ]


def test_one_artifact_path_per_file_read(valid: ManifestReadResult) -> None:
    files = [
        "gpx/p1/jour3.gpx",
        "gpx/p1/jour3.fit",
        "gpx/p1/prepare.gpx",
        "gpx/p2/matin_1.gpx",
        "gpx/p2/matin_2.gpx",
    ]
    assert dict(valid.artifact_paths) == {
        _sha256(FIXTURE / name): (FIXTURE / name).resolve() for name in files
    }


def test_every_artifact_resolves_to_its_file(valid: ManifestReadResult) -> None:
    for artifact in _all_artifacts(valid):
        path = valid.artifact_paths[artifact.source.content_hash]
        assert path.name == artifact.source.identifier
        assert _sha256(path) == artifact.source.content_hash


def test_same_name_references_resolve_to_distinct_paths(tmp_path: Path) -> None:
    def cite(document: Document) -> None:
        _outing(document, P2)["reference"] = {
            "file": "gpx/p2/prepare.gpx",
            "kind": "prepared",
            "available_at": "2026-06-01T08:00:00Z",
        }

    result = load_manifest(_variant(tmp_path, cite))
    references = [o.reference.artifact for o in result.outings if o.reference]
    assert [r.source.identifier for r in references] == ["prepare.gpx"] * 2
    paths = [result.artifact_paths[r.source.content_hash] for r in references]
    assert paths[0] != paths[1]
    assert [p.parent.name for p in paths] == ["p1", "p2"]


def test_one_reference_cited_twice_gives_one_entry(tmp_path: Path) -> None:
    def cite(document: Document) -> None:
        _outing(document, P2)["reference"] = dict(_outing(document, P1)["reference"])

    result = load_manifest(_variant(tmp_path, cite))
    assert len(result.artifact_paths) == 5
    p1, p2 = _by_id(result, P1).reference, _by_id(result, P2).reference
    assert p1 is not None
    assert p2 is not None
    assert p1.artifact.source.content_hash == p2.artifact.source.content_hash


# ---------------------------------------------------------------------------
# Précisions de relecture : doublon sans extension, empreinte en majuscules
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("name", "kind"),
    [("doublon", "unknown"), (".doublon", "unknown"), ("DOUBLON.FIT", "fit")],
)
def test_duplicate_kind_is_its_lowercase_suffix_or_unknown(
    tmp_path: Path, name: str, kind: str
) -> None:
    folder = _copy(tmp_path)
    (folder / "gpx/p1" / name).write_text("doublon synthétique\n", encoding="utf-8")

    def cite(document: Document) -> None:
        _outing(document, P1)["duplicates"] = [{"file": f"gpx/p1/{name}"}]

    result = load_manifest(_variant(tmp_path, cite))
    (duplicate,) = _by_id(result, P1).duplicates
    assert duplicate.source.kind == kind
    assert duplicate.source.identifier == name
    assert result.refused == ()


def test_identical_contents_keep_the_first_path_met(tmp_path: Path) -> None:
    """P6 — § 4.5 : deux fichiers de même contenu à deux chemins distincts donnent
    une seule entrée, celle du **premier** rencontré dans l'ordre du manifeste."""
    folder = _copy(tmp_path)
    shutil.copyfile(folder / "gpx/p1/prepare.gpx", folder / "gpx/p2/copie.gpx")

    def cite(document: Document) -> None:
        _outing(document, P2)["reference"] = {
            "file": "gpx/p2/copie.gpx",
            "kind": "prepared",
            "available_at": "2026-06-01T08:00:00Z",
        }

    result = load_manifest(_variant(tmp_path, cite))
    content_hash = _sha256(FIXTURE / "gpx/p1/prepare.gpx")
    assert [path for h, path in result.artifact_paths.items() if h == content_hash] == [
        (folder / "gpx/p1/prepare.gpx").resolve()
    ]
    p2 = _by_id(result, P2).reference
    assert p2 is not None
    assert p2.artifact.source.identifier == "copie.gpx"


def test_declared_sha256_is_compared_case_insensitively(tmp_path: Path) -> None:
    def upper(document: Document) -> None:
        entry = _outing(document, P1)["duplicates"][0]
        entry["sha256"] = entry["sha256"].upper()

    result = load_manifest(_variant(tmp_path, upper))
    content_hash = _by_id(result, P1).duplicates[0].source.content_hash
    assert content_hash == _sha256(FIXTURE / "gpx/p1/jour3.fit")
    assert content_hash == content_hash.lower()


# ---------------------------------------------------------------------------
# Règles 1 et 2 : ManifestError qui nomme la sortie et la clé
# ---------------------------------------------------------------------------


def _expect(
    tmp_path: Path, change: Callable[[Document], object], where: str, key: str
) -> str:
    """``ManifestError`` attendue, qui nomme ``where`` et ``key`` ; rend le message."""
    path = _variant(tmp_path, change)
    with pytest.raises(
        ManifestError, match=re.escape(f"{where}, clé {key} :")
    ) as error:
        load_manifest(path)
    assert str(tmp_path) not in str(error.value)
    return str(error.value)


@pytest.mark.parametrize(
    ("file", "rule"),
    [
        ("/gpx/p1/jour3.gpx", "chemin absolu"),
        ("C:/gpx/p1/jour3.gpx", "lecteur Windows"),
        ("//serveur/partage/jour3.gpx", "chemin réseau"),
        ("gpx\\p1\\jour3.gpx", "antislash"),
        ("../manifeste/gpx/p1/jour3.gpx", "composant « .. »"),
        ("gpx/../gpx/p1/jour3.gpx", "composant « .. »"),
        ("/home/personne-inventee/courses/prive.gpx", "chemin absolu"),
        ("C:/Users/personne-inventee/courses/prive.gpx", "lecteur Windows"),
    ],
)
def test_rule_1_paths_are_relative_posix_without_parent(
    tmp_path: Path, file: str, rule: str
) -> None:
    """Le refus ne recopie jamais la valeur reçue : un chemin absolu contient le
    nom de l'utilisateur (règle 1 de ``CLAUDE.md``, P11)."""

    def change(document: Document) -> None:
        _outing(document, P1)["traces"][0]["file"] = file

    message = _expect(tmp_path, change, f"sortie {P1}", "traces[0].file")
    assert file not in message
    assert repr(file)[1:-1] not in message
    assert f"({rule} refusé)" in message


def _set(outing_id: str, key: str, value: object) -> Callable[[Document], object]:
    return lambda document: _outing(document, outing_id).__setitem__(key, value)


def _delete(outing_id: str, key: str) -> Callable[[Document], object]:
    return lambda document: _outing(document, outing_id).pop(key)


RULE_2_CASES: list[tuple[str, Callable[[Document], object], str, str]] = [
    (
        "fichier-manquant",
        lambda d: _outing(d, P1)["traces"][0].__setitem__("file", "gpx/p1/absent.gpx"),
        f"sortie {P1}",
        "traces[0].file",
    ),
    ("cle-inconnue", _set(P1, "couleur", "bleu"), f"sortie {P1}", "couleur"),
    (
        "cle-inconnue-racine",
        lambda d: d.__setitem__("commentaire", "x"),
        "manifeste",
        "commentaire",
    ),
    (
        "cle-inconnue-reference",
        lambda d: _outing(d, P1)["reference"].__setitem__("note", "x"),
        f"sortie {P1}",
        "reference.note",
    ),
    (
        "cle-inconnue-passage",
        lambda d: _outing(d, P2)["external_records"][0]["passages"][0].__setitem__(
            "rang", 1
        ),
        f"sortie {P2}",
        "external_records[0].passages[0].rang",
    ),
    ("cle-obligatoire-sport", _delete(P1, "sport"), f"sortie {P1}", "sport"),
    (
        "cle-obligatoire-racine",
        lambda d: d.pop("domain_start_date"),
        "manifeste",
        "domain_start_date",
    ),
    (
        "cle-obligatoire-id",
        lambda d: d["outings"][2].pop("id"),
        "sortie n°3",
        "id",
    ),
    (
        "disponibilite-obligatoire",
        lambda d: _outing(d, P1)["reference"].pop("available_at"),
        f"sortie {P1}",
        "reference.available_at",
    ),
    ("sport-inconnu", _set(P1, "sport", "ski"), f"sortie {P1}", "sport"),
    ("jeu-inconnu", _set(P1, "dataset", "autre"), f"sortie {P1}", "dataset"),
    ("etiquette-inconnue", _set(P1, "label", "course"), f"sortie {P1}", "label"),
    (
        "nature-inconnue",
        lambda d: _outing(d, P1)["reference"].__setitem__("kind", "trace"),
        f"sortie {P1}",
        "reference.kind",
    ),
    (
        "convention-inconnue",
        lambda d: _outing(d, P2)["external_records"][0]["passages"][0].__setitem__(
            "convention", "milieu"
        ),
        f"sortie {P2}",
        "external_records[0].passages[0].convention",
    ),
    (
        "instant-sans-decalage",
        _set(VELO, "start", "2026-06-07T17:00:00"),
        f"sortie {VELO}",
        "start",
    ),
    (
        "disponibilite-sans-decalage",
        lambda d: _outing(d, P1)["reference"].__setitem__(
            "available_at", "2026-05-24T20:00:00"
        ),
        f"sortie {P1}",
        "reference.available_at",
    ),
    (
        "identifiant-en-double",
        lambda d: d["outings"][2].__setitem__("id", P1),
        f"sortie {P1}",
        "id",
    ),
    (
        "empreinte-differente",
        lambda d: _outing(d, P1)["duplicates"][0].__setitem__("sha256", "0" * 64),
        f"sortie {P1}",
        "duplicates[0].sha256",
    ),
    (
        "contrat-debut-apres-fin",
        _set(VELO, "end", "2026-06-07T16:00:00+02:00"),
        f"sortie {VELO}",
        "start",
    ),
    ("contrat-portion", _set(P2, "portion_m", [2500, 0]), f"sortie {P2}", "portion_m"),
    ("portion-non-couple", _set(P2, "portion_m", [0]), f"sortie {P2}", "portion_m"),
    ("route-vide", _set(P1, "route", " "), f"sortie {P1}", "route"),
    (
        "version",
        lambda d: d.__setitem__("schema_version", 2),
        "manifeste",
        "schema_version",
    ),
    (
        "version-booleenne",
        lambda d: d.__setitem__("schema_version", True),
        "manifeste",
        "schema_version",
    ),
    (
        "date-du-domaine",
        lambda d: d.__setitem__("domain_start_date", "20260520"),
        "manifeste",
        "domain_start_date",
    ),
    (
        "temps-non-numerique",
        lambda d: _outing(d, P2)["external_records"][0]["passages"][1].__setitem__(
            "elapsed_s", "50"
        ),
        f"sortie {P2}",
        "external_records[0].passages[1].elapsed_s",
    ),
]


@pytest.mark.parametrize(
    ("change", "where", "key"),
    [case[1:] for case in RULE_2_CASES],
    ids=[case[0] for case in RULE_2_CASES],
)
def test_rule_2_malformed_manifest_names_outing_and_key(
    tmp_path: Path, change: Callable[[Document], object], where: str, key: str
) -> None:
    _expect(tmp_path, change, where, key)


JSON_TYPE_CASES: list[tuple[str, Callable[[Document], object], str, str]] = [
    (
        "booleen-pour-un-temps",
        lambda d: _outing(d, P2)["external_records"][0]["passages"][1].__setitem__(
            "elapsed_s", False
        ),
        f"sortie {P2}",
        "external_records[0].passages[1].elapsed_s",
    ),
    (
        "booleen-dans-la-portion",
        _set(P2, "portion_m", [False, 2500]),
        f"sortie {P2}",
        "portion_m[0]",
    ),
    (
        "version-flottante",
        lambda d: d.__setitem__("schema_version", 1.0),
        "manifeste",
        "schema_version",
    ),
    (
        "sorties-en-objet",
        lambda d: d.__setitem__("outings", {}),
        "manifeste",
        "outings",
    ),
    (
        "traces-en-texte",
        _set(P1, "traces", "gpx/p1/jour3.gpx"),
        f"sortie {P1}",
        "traces",
    ),
]


@pytest.mark.parametrize(
    ("change", "where", "key"),
    [case[1:] for case in JSON_TYPE_CASES],
    ids=[case[0] for case in JSON_TYPE_CASES],
)
def test_rule_2_json_types_are_checked(
    tmp_path: Path, change: Callable[[Document], object], where: str, key: str
) -> None:
    """P10 — choix 6 du plan : un booléen n'est pas un nombre, ``1.0`` n'est pas la
    version ``1``, une valeur non liste n'est pas une liste vide."""
    _expect(tmp_path, change, where, key)


def test_rule_2_unreadable_json(tmp_path: Path) -> None:
    path = _copy(tmp_path) / "manifeste.json"
    path.write_text("{", encoding="utf-8")
    with pytest.raises(ManifestError, match="JSON illisible"):
        load_manifest(path)


# ---------------------------------------------------------------------------
# Règle 4 : sortie tracée
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("key", "value", "accepted"),
    [
        ("start", "2026-06-07T08:00:01+02:00", True),
        ("start", "2026-06-07T08:00:01.5+02:00", False),
        ("end", "2026-06-07T06:00:29Z", True),
        ("end", "2026-06-07T06:00:28.9Z", False),
    ],
)
def test_rule_4_declared_times_agree_with_the_trace_within_1_s(
    tmp_path: Path, key: str, value: str, accepted: bool
) -> None:
    path = _variant(tmp_path, _set(P1, key, value))
    if accepted:
        assert _by_id(load_manifest(path), P1).start_time == datetime(
            2026, 6, 7, 6, 0, tzinfo=UTC
        )
    else:
        with pytest.raises(ManifestError, match=re.escape(f"sortie {P1}, clé {key} :")):
            load_manifest(path)


BAD_TRACES = {
    "instant-decroissant": _decreasing_gpx(),
    "instant-absent": gpx_document(
        [equatorial_point(0.0, "2026-06-07T06:00:00Z"), ("0", "0", "1000", None)]
    ),
    "latitude-hors-plage": gpx_document(
        [
            equatorial_point(0.0, "2026-06-07T06:00:00Z"),
            ("91", "0", "1000", "2026-06-07T06:00:10Z"),
        ]
    ),
}


@pytest.mark.parametrize("text", BAD_TRACES.values(), ids=BAD_TRACES.keys())
def test_rule_4_refused_trace_keeps_the_outing_with_declared_times(
    tmp_path: Path, text: str
) -> None:
    """TraceError, GpxError ou ContractError : l'évaluation est refusée, la sortie
    compte encore pour la règle des sorties retenues (``0010`` D0)."""
    folder = _copy(tmp_path)
    (folder / "gpx/p1/jour3.gpx").write_text(text, encoding="utf-8")

    def declare(document: Document) -> None:
        _outing(document, P1)["start"] = "2026-06-07T08:00:00+02:00"
        _outing(document, P1)["end"] = "2026-06-07T10:00:00+02:00"

    result = load_manifest(_variant(tmp_path, declare))
    p1 = _by_id(result, P1)
    assert p1.start_time == datetime(2026, 6, 7, 6, 0, tzinfo=UTC)
    assert p1.end_time == datetime(2026, 6, 7, 8, 0, tzinfo=UTC)
    assert P1 not in result.traces
    assert [(r.outing_id, r.label) for r in result.refused] == [(P1, None)]
    assert "jour3.gpx" in result.refused[0].reason
    assert p1.traces[0].source.content_hash in result.artifact_paths


@pytest.mark.parametrize("missing", ["start", "end"])
def test_rule_4_refused_trace_without_declared_times_is_an_error(
    tmp_path: Path, missing: str
) -> None:
    folder = _copy(tmp_path)
    (folder / "gpx/p1/jour3.gpx").write_text(_decreasing_gpx(), encoding="utf-8")

    def declare(document: Document) -> None:
        _outing(document, P1)["start"] = "2026-06-07T08:00:00+02:00"
        _outing(document, P1)["end"] = "2026-06-07T10:00:00+02:00"
        _outing(document, P1).pop(missing)

    _expect(tmp_path, declare, f"sortie {P1}", missing)


# ---------------------------------------------------------------------------
# Règle 5 : sortie non tracée
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("missing", ["start", "end"])
def test_rule_5_untraced_outing_needs_start_and_end(
    tmp_path: Path, missing: str
) -> None:
    _expect(tmp_path, _delete(VELO, missing), f"sortie {VELO}", missing)


# ---------------------------------------------------------------------------
# Règle 6 : sortie d'un autre athlète
# ---------------------------------------------------------------------------


def test_rule_6_other_athlete_outing_is_refused_and_excluded(tmp_path: Path) -> None:
    """``0010`` D2.6 : refusée avant tout calcul — ses fichiers ne sont même pas
    ouverts (ici, sa trace n'existe pas)."""

    def other(document: Document) -> None:
        _outing(document, P1)["athlete_ref"] = "athlete-2"
        _outing(document, P1)["traces"] = [{"file": "gpx/p1/absent.gpx"}]

    result = load_manifest(_variant(tmp_path, other))
    assert [o.outing_id for o in result.outings] == [P2, VELO]
    assert [(r.outing_id, r.label) for r in result.refused] == [(P1, None)]
    assert "athlete_ref" in result.refused[0].reason
    assert P1 not in result.traces
    assert _sha256(FIXTURE / "gpx/p1/jour3.fit") not in result.artifact_paths


def test_rule_6_other_athlete_outing_with_existing_files_is_excluded(
    tmp_path: Path,
) -> None:
    """P5 — l'exclusion jugée pour elle-même : la sortie refusée cite ses fichiers
    existants, rien ne peut échouer avant l'assertion d'exclusion."""
    result = load_manifest(_variant(tmp_path, _set(P1, "athlete_ref", "athlete-2")))
    assert [o.outing_id for o in result.outings] == [P2, VELO]
    assert [(r.outing_id, r.label) for r in result.refused] == [(P1, None)]
    assert P1 not in result.traces
    assert _sha256(FIXTURE / "gpx/p1/jour3.gpx") not in result.artifact_paths


def test_rule_6_same_athlete_declared_explicitly_is_kept(tmp_path: Path) -> None:
    result = load_manifest(_variant(tmp_path, _set(P1, "athlete_ref", "athlete-1")))
    assert [o.outing_id for o in result.outings] == [P1, P2, VELO]


# ---------------------------------------------------------------------------
# Règle 7 : relevés externes
# ---------------------------------------------------------------------------


def test_rule_7_other_athlete_record_is_refused_outing_kept(tmp_path: Path) -> None:
    def other(document: Document) -> None:
        records = _outing(document, P2)["external_records"]
        stranger = json.loads(json.dumps(records[0]))
        stranger["athlete_ref"] = "coureur-446"
        stranger["event_name"] = "Relevé d'un autre"
        records.insert(0, stranger)

    result = load_manifest(_variant(tmp_path, other))
    p2 = _by_id(result, P2)
    assert [r.event_name for r in p2.external_records] == ["Relevé inventé"]
    assert [(r.outing_id, r.label) for r in result.refused_records] == [
        (P2, "Relevé d'un autre")
    ]
    assert result.refused == ()


@pytest.mark.parametrize(
    "change",
    [
        lambda passages: passages.pop(),
        lambda passages: passages.reverse(),
        lambda passages: passages[0].__setitem__("elapsed_s", -1),
    ],
    ids=["un-seul-passage", "temps-decroissants", "temps-negatif"],
)
def test_rule_7_record_violating_its_contract_is_an_error(
    tmp_path: Path, change: Callable[[list[Any]], object]
) -> None:
    def violate(document: Document) -> None:
        change(_outing(document, P2)["external_records"][0]["passages"])

    path = _variant(tmp_path, violate)
    with pytest.raises(
        ManifestError, match=re.escape(f"sortie {P2}, clé external_records[0]")
    ):
        load_manifest(path)


# ---------------------------------------------------------------------------
# P9 — résultats internes gelés ou en lecture seule (§ 4.5)
# ---------------------------------------------------------------------------


def test_manifest_result_is_frozen(valid: ManifestReadResult) -> None:
    target: Any = valid
    with pytest.raises(FrozenInstanceError):
        target.outings = ()


@pytest.mark.parametrize("name", ["traces", "artifact_paths"])
def test_manifest_result_mappings_are_read_only(
    valid: ManifestReadResult, name: str
) -> None:
    mapping: Any = getattr(valid, name)
    key = next(iter(mapping))
    with pytest.raises(TypeError):
        mapping[key] = None


def test_refused_entry_is_frozen() -> None:
    target: Any = RefusedEntry(P1, None, "motif inventé")
    with pytest.raises(FrozenInstanceError):
        target.reason = "autre motif"
