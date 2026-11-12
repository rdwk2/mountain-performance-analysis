"""Les résultats de Q1 sous ``MPA_DATA_DIR/resultats/Q1/`` (AN1-2c, charte § 10,
``docs/decisions/0015``) : un dossier ``<date>_<empreinte>/`` par exécution, jamais
réécrit.

Le dossier contient ``figure.html`` (rendue par ``mountain_perf.analyse.plot``),
``points.csv`` (une ligne par point et par vue), ``flux.csv`` (une ligne par mois pour
les activités, puis par mois et par panneau) et ``provenance.json`` : la question, la
commande, le commit et la version du paquet, la date de génération, la période des
données, la provenance des tables lues, les paramètres de la figure et l'empreinte
SHA-256 de chaque fichier. ``<date>`` est la date de génération ; ``<empreinte>``, les
douze premiers chiffres du SHA-256 de ``provenance.json`` sans la date de génération :
les mêmes tables, le même code et les mêmes paramètres donnent la même empreinte.

Le dossier s'écrit d'abord sous un nom temporaire, puis prend son nom : il est complet
ou absent. CSV et JSON en UTF-8, fins de ligne ``\\n``.

La relecture (AN2-3, la page « Q1 ») : :func:`stored_results` relit les dossiers,
:func:`latest_result` retient la dernière figure et dit si elle vient des tables
actuelles, :func:`read_figure` en rend le HTML ; rien de ce qu'écrit
:func:`write_results` ne change.

Python pur : ce module ne demande aucun extra.
"""

from __future__ import annotations

import csv
import dataclasses
import hashlib
import io
import json
import shutil
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from enum import StrEnum
from pathlib import Path

from mountain_perf.analyse.q1 import (
    FigurePoint,
    MonthActivities,
    MonthPanel,
    Q1Figure,
)
from mountain_perf.schemas.processed import ClimbFlag, ProcessedProvenance

RESULTS_DIR = Path("resultats") / "Q1"
"""Le dossier des résultats de Q1, sous ``MPA_DATA_DIR``."""

FIGURE_FILE = "figure.html"
POINTS_FILE = "points.csv"
FLUX_FILE = "flux.csv"
PROVENANCE_FILE = "provenance.json"
COMMAND = "mperf q1"
_TEMPORARY_PREFIX = "."
_TEMPORARY_SUFFIX = ".nouveau"

POINT_COLUMNS: tuple[str, ...] = (
    "view",
    "panel",
    "grade_stratum",
    "altitude_stratum",
    "activity_ref",
    "start_time",
    "status",
    "climb_count",
    "moving_gain_m",
    "moving_s",
    "vertical_speed_ms",
    "vertical_speed_low_ms",
    "vertical_speed_high_ms",
    "found_fraction",
    "min_kept_fraction",
    "max_relative_deviation",
    "stable",
)
"""Les colonnes de ``points.csv``, dans leur ordre."""

FLUX_COLUMNS: tuple[str, ...] = (
    "month",
    "panel",
    "activities",
    "with_track",
    "multisession_activities",
    "climbs",
    "flagged",
    *(f"flag_{flag.value}" for flag in ClimbFlag),
    "multisession",
    "unstratified",
    "kept",
    "kept_unstable",
    "points",
    "points_hidden",
    "points_non_positive",
    "points_unstable",
    "stable_only_points",
    "stable_only_points_hidden",
    "stable_only_points_non_positive",
)
"""Les colonnes de ``flux.csv``, dans leur ordre ; une ligne des activités laisse vides
les colonnes d'un panneau, et inversement."""


class ResultsError(ValueError):
    """Le dossier de résultats existe déjà : rien n'est réécrit."""


def _cell(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, float):
        return repr(value)
    return str(value)


def _csv(columns: Sequence[str], rows: Sequence[Sequence[object]]) -> str:
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\n")
    writer.writerow(columns)
    for row in rows:
        writer.writerow([_cell(value) for value in row])
    return buffer.getvalue()


def _point_row(p: FigurePoint) -> list[object]:
    s = p.stability
    return [
        p.view.value,
        p.panel.value,
        p.grade_stratum.value,
        p.altitude_stratum.value,
        p.activity_ref,
        p.start_time.isoformat(),
        p.status.value,
        p.climb_count,
        p.moving_gain_m,
        p.moving_s,
        p.vertical_speed_ms,
        p.vertical_speed_low_ms,
        p.vertical_speed_high_ms,
        None if s is None else s.found_fraction,
        None if s is None else s.min_kept_fraction,
        None if s is None else s.max_relative_deviation,
        None if s is None else s.stable,
    ]


def points_csv(figure: Q1Figure) -> str:
    """``points.csv`` : une ligne par point de ``figure``, dans son ordre."""
    return _csv(POINT_COLUMNS, [_point_row(p) for p in figure.points])


def _activities_row(m: MonthActivities) -> list[object]:
    row: list[object] = [m.month, None, m.activities, m.with_track, m.multisession]
    return row + [None] * (len(FLUX_COLUMNS) - len(row))


def _panel_row(m: MonthPanel) -> list[object]:
    return [
        m.month,
        m.panel.value,
        None,
        None,
        None,
        m.climbs,
        m.flagged,
        *(count for _, count in m.flags),
        m.multisession,
        m.unstratified,
        m.kept,
        m.kept_unstable,
        m.points,
        m.points_hidden,
        m.points_non_positive,
        m.points_unstable,
        m.stable_only_points,
        m.stable_only_points_hidden,
        m.stable_only_points_non_positive,
    ]


def flux_csv(figure: Q1Figure) -> str:
    """``flux.csv`` : les lignes des activités, mois par mois, puis celles des
    panneaux, panneau par panneau et mois par mois."""
    rows = [_activities_row(m) for m in figure.month_activities]
    rows += [_panel_row(m) for m in figure.month_panels]
    return _csv(FLUX_COLUMNS, rows)


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def provenance(
    figure: Q1Figure,
    files: dict[str, str],
    *,
    commit: str,
    package_version: str,
) -> dict[str, object]:
    """La provenance du résultat, sans la date de génération : ``files`` donne le
    contenu de chaque fichier, par nom."""
    period = figure.period
    return {
        "question": "Q1",
        "commande": COMMAND,
        "commit": commit,
        "version_du_paquet": package_version,
        "periode": None
        if period is None
        else {
            "debut": period[0].isoformat(),
            "fin": period[1].isoformat(),
        },
        "tables": dataclasses.asdict(figure.provenance),
        "parametres_de_la_figure": dict(sorted(figure.parameters.values.items())),
        "fichiers": {name: _sha256(text) for name, text in sorted(files.items())},
    }


def _json(document: object) -> str:
    return json.dumps(document, ensure_ascii=False, indent=2, sort_keys=True) + "\n"


def write_results(
    data_dir: Path,
    figure: Q1Figure,
    html: str,
    *,
    commit: str,
    package_version: str,
    generated_on: date,
) -> Path:
    """Écrit le dossier de résultats de ``figure`` sous
    ``data_dir/resultats/Q1/`` et le rend. :class:`ResultsError` si un dossier du même
    nom existe déjà."""
    files = {
        FIGURE_FILE: html,
        POINTS_FILE: points_csv(figure),
        FLUX_FILE: flux_csv(figure),
    }
    document = provenance(figure, files, commit=commit, package_version=package_version)
    digest = _sha256(_json(document))[:12]
    name = f"{generated_on.isoformat()}_{digest}"
    root = data_dir / RESULTS_DIR
    target = root / name
    if target.exists():
        raise ResultsError(
            f"{(RESULTS_DIR / name).as_posix()}/ existe déjà : rien n'est réécrit"
        )
    temporary = root / f"{_TEMPORARY_PREFIX}{name}{_TEMPORARY_SUFFIX}"
    if temporary.exists():
        shutil.rmtree(temporary)
    try:
        temporary.mkdir(parents=True)
        for file_name, text in files.items():
            (temporary / file_name).write_text(text, encoding="utf-8", newline="")
        dated = {**document, "genere_le": generated_on.isoformat()}
        (temporary / PROVENANCE_FILE).write_text(
            _json(dated), encoding="utf-8", newline=""
        )
    except BaseException:
        shutil.rmtree(temporary, ignore_errors=True)
        raise
    temporary.rename(target)
    return target


class TablesMatch(StrEnum):
    """Ce que la figure de Q1 retenue dit des tables actuelles : ``same``, elle en
    vient ; ``different``, aucun résultat n'en vient ; ``unknown``, les tables
    actuelles ne se relisent pas."""

    SAME = "same"
    DIFFERENT = "different"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class StoredResult:
    """Un dossier de résultats de Q1 relu : son chemin, sa date de génération, et la
    valeur ``tables`` de son ``provenance.json``, telle que relue."""

    folder: Path
    generated_on: date
    tables: object


@dataclass(frozen=True)
class LatestResult:
    """Le résultat retenu par :func:`latest_result`, ce qu'il dit des tables actuelles,
    et le compte des dossiers illisibles."""

    result: StoredResult
    match: TablesMatch
    unreadable: int


def _temporary(name: str) -> bool:
    """Un dossier temporaire de :func:`write_results` : ses deux marques."""
    return name.startswith(_TEMPORARY_PREFIX) and name.endswith(_TEMPORARY_SUFFIX)


def _stored(folder: Path) -> StoredResult | None:
    """Le dossier relu, ou ``None`` s'il est illisible."""
    try:
        document = json.loads((folder / PROVENANCE_FILE).read_bytes().decode("utf-8"))
    except (OSError, UnicodeDecodeError, ValueError):
        return None
    if not isinstance(document, dict) or "tables" not in document:
        return None
    written = document.get("genere_le")
    if not isinstance(written, str):
        return None
    try:
        generated_on = date.fromisoformat(written)
    except ValueError:
        return None
    if generated_on.isoformat() != folder.name.split("_", 1)[0]:
        return None
    return StoredResult(folder, generated_on, document["tables"])


def stored_results(data_dir: Path) -> tuple[tuple[StoredResult, ...], int]:
    """Les dossiers de résultats de Q1 sous ``data_dir``, triés par nom, et le compte
    des illisibles : ``provenance.json`` absent ou qui ne se lit pas (UTF-8, JSON), sans
    ``tables``, ou dont ``genere_le`` n'est pas une date, écrite ``AAAA-MM-JJ``, qui
    est le préfixe du nom. Ce qui n'est pas un dossier et les dossiers temporaires de
    :func:`write_results` sont ignorés, sans être comptés."""
    root = data_dir / RESULTS_DIR
    if not root.is_dir():
        return (), 0
    folders = sorted(
        (
            path
            for path in root.iterdir()
            if path.is_dir() and not _temporary(path.name)
        ),
        key=lambda path: path.name,
    )
    results: list[StoredResult] = []
    unreadable = 0
    for folder in folders:
        stored = _stored(folder)
        if stored is None:
            unreadable += 1
        else:
            results.append(stored)
    return tuple(results), unreadable


def _written_ns(result: StoredResult) -> int:
    try:
        return (result.folder / PROVENANCE_FILE).stat().st_mtime_ns
    except OSError:
        return 0


def latest_result(
    data_dir: Path, current: ProcessedProvenance | None
) -> LatestResult | None:
    """La dernière figure de Q1 : parmi les résultats des tables actuelles
    (``current``, écrite comme ``provenance.json`` l'écrit), sinon parmi tous, la
    ``genere_le`` la plus récente ; à égalité, le ``provenance.json`` écrit le plus
    tard ; puis le nom le plus grand. ``None`` sans résultat lisible."""
    results, unreadable = stored_results(data_dir)
    if not results:
        return None
    if current is None:
        match, candidates = TablesMatch.UNKNOWN, results
    else:
        written = json.loads(json.dumps(dataclasses.asdict(current)))
        same = tuple(result for result in results if result.tables == written)
        match = TablesMatch.SAME if same else TablesMatch.DIFFERENT
        candidates = same or results
    latest = max(
        candidates,
        key=lambda result: (
            result.generated_on,
            _written_ns(result),
            result.folder.name,
        ),
    )
    return LatestResult(latest, match, unreadable)


def read_figure(result: StoredResult) -> str | None:
    """Le texte de ``figure.html`` du résultat ; ``None`` s'il ne s'ouvre pas."""
    try:
        return (result.folder / FIGURE_FILE).read_text(encoding="utf-8")
    except OSError:
        return None
