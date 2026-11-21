"""Les résultats de Q2 sous ``MPA_DATA_DIR/resultats/`` (AN3-3b,
``docs/decisions/0023``, charte § 10).

Deux dossiers, chacun ``<date>_<empreinte>/``, jamais réécrits (la règle de Q1,
recopiée ici : ``analyse/results.py`` reste inchangé) : ``resultats/Q2/puissance/``
(``puissance.csv``, ``flux.csv``, ``provenance.json``) et ``resultats/Q2/`` (les
essais, la figure, l'autocorrélation, le flux, la provenance). ``<date>`` est la date
de génération ; ``<empreinte>``, les douze premiers chiffres du SHA-256 de
``provenance.json`` sans ``genere_le``. Un dossier s'écrit sous un nom temporaire
(``.<nom>.nouveau``), puis prend son nom : il est complet ou absent. CSV et JSON en
UTF-8, fins de ligne ``\\n``.

``flux.csv`` compte, par régime, mesure, période, mois, étape et motif, les journées et
les montées exclues, celles retenues, et le 90ᵉ centile de la part hors mouvement.

Python pur : ce module n'importe que la bibliothèque standard, ``analyse/q2/``,
``analyse/inference/`` (par ses fonctions), ``mountain_perf.codec`` (le journal
chaîné), ``mountain_perf.schemas`` et ``TablesMatch`` de
``mountain_perf.analyse.results`` (la relecture, AN3-5).
"""

from __future__ import annotations

import contextlib
import csv
import dataclasses
import hashlib
import io
import json
import math
import re
import shutil
from collections.abc import Iterable, Iterator, Mapping, Sequence
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path

from mountain_perf.analyse.inference.base import order_quantile
from mountain_perf.analyse.inference.reml import RemlFit
from mountain_perf.analyse.q2.data import (
    MOTIF_STEPS,
    Period,
    Q2Data,
    Q2Day,
    Q2Motif,
    period_of,
)
from mountain_perf.analyse.q2.figure import Q2Figure
from mountain_perf.analyse.q2.model import Measure, ModelSpec
from mountain_perf.analyse.q2.parameters import Q2_REGIMES, Q2_ROOT_SEED
from mountain_perf.analyse.q2.power import (
    SCENARIOS,
    PowerLevel,
    PowerResult,
    RegimePower,
)
from mountain_perf.analyse.q2.trials import (
    INTERVAL_FIELDS,
    NOT_DONE,
    Q2Estimation,
    TrialRow,
)
from mountain_perf.analyse.results import TablesMatch
from mountain_perf.codec import canonical_bytes, content_hash
from mountain_perf.schemas import ParameterSet
from mountain_perf.schemas.processed import ClimbRegime, ProcessedProvenance

RESULTS_DIR = Path("resultats") / "Q2"
"""Le dossier des résultats d'estimation de Q2, sous ``MPA_DATA_DIR``."""
POWER_DIR = RESULTS_DIR / "puissance"
"""Le dossier des résultats de puissance."""
FLUX_FILE = "flux.csv"
POWER_FILE = "puissance.csv"
PROVENANCE_FILE = "provenance.json"
POWER_COMMAND = "mperf q2 puissance"
ESTIMATION_COMMAND = "mperf q2"
_TEMPORARY_PREFIX = "."
_TEMPORARY_SUFFIX = ".nouveau"
RESULT_NAME = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}_[0-9a-f]{12}")
"""Le nom d'un dossier de résultats ; tout autre nom n'en est pas un."""

FLUX_COLUMNS: tuple[str, ...] = (
    "regime",
    "mesure",
    "periode",
    "mois",
    "etape",
    "motif",
    "journees",
    "montees",
    "valeur",
)
POWER_COLUMNS: tuple[str, ...] = (
    "regime",
    "scenario",
    "b_fraction_par_an",
    "tirages",
    "tirages_en_echec",
    "p_etabli",
    "p_absence_effet_utile",
    "erreur_mc_etabli",
    "puissance",
    "erreur_s",
    "erreur_m",
    "biais_fraction_par_an",
)
COMMON = "commun"
KEPT = "retenues"
OFF_MOVING = "hors_mouvement"
PERIOD_ORDER: tuple[Period, ...] = (
    Period.BEFORE,
    Period.DISCOVERY,
    Period.AFTER,
    Period.ALL,
)


class Q2ResultsError(ValueError):
    """Un résultat de Q2 ne s'écrit pas : le dossier existe déjà, ou
    ``essais.jsonl`` ne se relit pas ; rien n'est écrit. Ou un dossier
    d'estimation ne se relit pas (:func:`read_estimation`, AN3-5)."""


# --- CSV et JSON -----------------------------------------------------------------


def cell(value: object) -> str:
    """Une case : vide pour ``None``, ``true``/``false``, ``repr`` d'un flottant."""
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, float):
        return repr(value)
    return str(value)


def csv_text(columns: Sequence[str], rows: Iterable[Sequence[object]]) -> str:
    """Un CSV (module ``csv``, fins de ligne ``\\n``)."""
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\n")
    writer.writerow(columns)
    for row in rows:
        writer.writerow([cell(value) for value in row])
    return buffer.getvalue()


def _finite_or_null(value: object) -> object:
    if isinstance(value, float) and not math.isfinite(value):
        return None
    if isinstance(value, Mapping):
        return {k: _finite_or_null(v) for k, v in value.items()}
    if isinstance(value, list | tuple):
        return [_finite_or_null(v) for v in value]
    return value


def json_text(document: object) -> str:
    """Un JSON trié, indenté, sans échappement ASCII ; un flottant non fini (une
    fraction par an +∞, AN3-4) s'écrit ``null``, jamais ``Infinity`` ni ``NaN``."""
    return (
        json.dumps(
            _finite_or_null(document),
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
            allow_nan=False,
        )
        + "\n"
    )


def sha256_text(text: str) -> str:
    """Le SHA-256 de ``text`` en UTF-8."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


# --- le flux ---------------------------------------------------------------------


def month_key(day: date) -> str:
    """``AAAA-MM`` du jour."""
    return f"{day.year:04d}-{day.month:02d}"


def _months(first: date, last: date) -> list[str]:
    """Chaque mois de ``first`` à ``last``, mois vides compris."""
    months: list[str] = []
    year, month = first.year, first.month
    while (year, month) <= (last.year, last.month):
        months.append(f"{year:04d}-{month:02d}")
        month += 1
        if month == 13:
            year, month = year + 1, 1
    return months


def _periods_of_month(month: str, data: Q2Data) -> tuple[Period, ...]:
    year, number = int(month[:4]), int(month[5:])
    day = date(year, number, 1)
    found: set[Period] = set()
    while day.month == number:
        found.add(period_of(day, data.periods))
        day += timedelta(days=1)
    return tuple(p for p in PERIOD_ORDER if p in found)


@dataclass
class _Count:
    days: set[date] = dataclasses.field(default_factory=set)
    climbs: int = 0

    def add(self, day: date, climbs: int) -> None:
        if climbs:
            self.days.add(day)
            self.climbs += climbs


type _Key = tuple[str, str, Period, str, str, str]


def _flux_counts(
    data: Q2Data, specs: Mapping[tuple[ClimbRegime, Measure], ModelSpec]
) -> dict[_Key, _Count]:
    counts: dict[_Key, _Count] = {}

    def count(
        regime: ClimbRegime,
        measure: str,
        day: Q2Day | date,
        step: str,
        motif: str,
        climbs: int,
    ) -> None:
        when = day if isinstance(day, date) else day.day
        key = (
            regime.value,
            measure,
            period_of(when, data.periods),
            month_key(when),
            step,
            motif,
        )
        counts.setdefault(key, _Count()).add(when, climbs)

    for climb in data.excluded:
        step = str(MOTIF_STEPS[climb.motif])
        count(climb.regime, COMMON, climb.day, step, climb.motif.value, 1)
    for regime in Q2_REGIMES:
        for day in data.days[regime]:
            if day.activity_count >= 2:
                count(
                    regime, COMMON, day, "4", Q2Motif.MERGED_DAY.value, len(day.climbs)
                )
        for measure in Measure:
            spec = specs[(regime, measure)]
            for day, kept in zip(spec.days, spec.in_sample, strict=True):
                if spec.step5_applied and day.step5 is not None:
                    count(
                        regime,
                        measure.value,
                        day,
                        "5",
                        day.step5.value,
                        len(day.climbs),
                    )
                    continue
                if measure is Measure.MS:
                    if day.step6 is not None:
                        count(
                            regime,
                            measure.value,
                            day,
                            "6",
                            day.step6.value,
                            len(day.climbs),
                        )
                    else:
                        reserve = sum(1 for m in day.reserve if m is not None)
                        count(
                            regime,
                            measure.value,
                            day,
                            "6",
                            Q2Motif.MS_RESERVE.value,
                            reserve,
                        )
                if kept:
                    climbs = (
                        len(day.climbs)
                        if measure is Measure.MP
                        else sum(1 for m in day.reserve if m is None)
                    )
                    count(regime, measure.value, day, KEPT, "", climbs)
    return counts


def _motifs(step: int) -> list[Q2Motif]:
    return [m for m in Q2Motif if MOTIF_STEPS[m] == step]


def _blocks(regime: ClimbRegime) -> list[tuple[str, list[tuple[str, str]]]]:
    """Les mesures d'un régime et leurs lignes ``(étape, motif)``."""
    common = [(str(MOTIF_STEPS[m]), m.value) for s in (1, 2, 3, 4) for m in _motifs(s)]
    if regime not in Q2_REGIMES:
        common = [
            (str(MOTIF_STEPS[m]), m.value)
            for m in (*_motifs(1), Q2Motif.OUTSIDE_REGIMES)
        ]
        return [(COMMON, common)]
    mp = [("5", m.value) for m in _motifs(5)] + [(KEPT, "")]
    ms = [(str(MOTIF_STEPS[m]), m.value) for s in (5, 6) for m in _motifs(s)] + [
        (KEPT, "")
    ]
    return [(COMMON, common), (Measure.MP.value, mp), (Measure.MS.value, ms)]


def _off_moving_row(
    regime: ClimbRegime,
    period: Period,
    spec: ModelSpec | None,
) -> list[object]:
    parts: list[float] = []
    days = 0
    if spec is not None:
        for unit in spec.units():
            if unit.day.period is not period:
                continue
            values = [c.off_moving for c in unit.climbs if c.off_moving is not None]
            if values:
                days += 1
                parts.extend(values)
    value = order_quantile(parts, 0.9) if parts else None
    return [
        regime.value,
        Measure.MP.value,
        period.value,
        "",
        OFF_MOVING,
        "",
        days if parts else 0,
        len(parts),
        value,
    ]


def flux_rows(
    data: Q2Data, specs: Mapping[tuple[ClimbRegime, Measure], ModelSpec]
) -> list[list[object]]:
    """Les lignes de ``flux.csv`` (§ 5.9) depuis les données et les modèles retenus
    de chaque régime et mesure (``specs``, qui disent les retraits) : chaque case de
    la grille, à zéro comprise ; ``retenues``, l'échantillon final ; si le 5ᵉ retrait
    joue, les lignes de l'étape 5 de cette mesure à zéro ; ``hors_mouvement``, par
    période, en fin du bloc de M-P de la période."""
    counts = _flux_counts(data, specs)
    regimes = [*Q2_REGIMES, *(r for r in ClimbRegime if r in data.regimes_present)]
    regimes = list(dict.fromkeys(regimes))
    months = _months(*data.activity_dates) if data.activity_dates is not None else []
    by_month = {m: _periods_of_month(m, data) for m in months}
    rows: list[list[object]] = []
    for regime in regimes:
        for measure, lines in _blocks(regime):
            for period in PERIOD_ORDER:
                touched = [m for m in months if period in by_month[m]]
                if not touched:
                    continue
                for month in touched:
                    for step, motif in lines:
                        found = counts.get(
                            (regime.value, measure, period, month, step, motif)
                        )
                        rows.append(
                            [
                                regime.value,
                                measure,
                                period.value,
                                month,
                                step,
                                motif,
                                0 if found is None else len(found.days),
                                0 if found is None else found.climbs,
                                None,
                            ]
                        )
                if measure == Measure.MP.value:
                    rows.append(
                        _off_moving_row(regime, period, specs.get((regime, Measure.MP)))
                    )
    return rows


def flux_csv(
    data: Q2Data, specs: Mapping[tuple[ClimbRegime, Measure], ModelSpec]
) -> str:
    """``flux.csv``."""
    return csv_text(FLUX_COLUMNS, flux_rows(data, specs))


# --- la puissance ----------------------------------------------------------------


def _power_lines(
    result: RegimePower, fractions: Mapping[int, tuple[float, ...]]
) -> list[list[object]]:
    summary = result.summary
    if summary is None:
        return []
    lines: list[list[object]] = []
    for scenario in SCENARIOS:
        for k, (row, fraction) in enumerate(
            zip(summary.rows[scenario], fractions[scenario], strict=True)
        ):
            bias = summary.bias.get(scenario)
            lines.append(
                [
                    result.regime.value,
                    scenario,
                    fraction,
                    row.n_draws,
                    summary.failed[scenario][k],
                    row.p_established,
                    row.p_no_useful_effect,
                    row.mc_se_established,
                    row.power,
                    row.s_error,
                    row.m_error,
                    None if bias is None else bias[k],
                ]
            )
    return lines


def power_csv(result: PowerResult) -> str:
    """``puissance.csv`` : une ligne par régime simulé, scénario et ``b``."""
    rows: list[list[object]] = []
    for regime in result.regimes:
        rows.extend(_power_lines(regime, result.grids.fractions))
    return csv_text(POWER_COLUMNS, rows)


def _flags(fit: RemlFit) -> dict[str, object]:
    return {
        "tau2_a_zero": fit.tau2_at_zero,
        "s2u_a_zero": fit.s2u_at_zero,
        "phi_a_la_borne_basse": fit.phi_at_lower,
        "phi_a_la_borne_haute": fit.phi_at_upper,
        "phi_identifie": fit.phi_identified,
        "profil_phi": [list(pair) for pair in fit.profile],
    }


def _regime_document(result: RegimePower) -> dict[str, object]:
    world, summary = result.world, result.summary
    if world is None or summary is None:
        return {"statut": "non_estimable", "motif": result.reason}
    calibration = summary.calibration
    return {
        "statut": "calculee",
        "monde": {
            "n": world.spec.n,
            "p": world.spec.p,
            "retraits": list(world.spec.withdrawals),
            "tau2": world.tau2,
            "s2u": world.s2u,
            "phi": world.phi,
            "s2e": world.s2e,
        },
        "colonnes": list(world.columns),
        "residus_de_journee_nuls": world.residual_day_zero,
        "reml_sans_date": _flags(world.reml),
        "seuils": list(result.alphas),
        "plus_petit_effet_visible": summary.smallest_visible,
        "a_delta": {
            "puissance": summary.power_at_delta,
            "erreur_s": summary.s_error_at_delta,
            "erreur_m": summary.m_error_at_delta,
        },
        "a_zero": {
            str(s): {"p_etabli": v[0], "p_absence_effet_utile": v[1]}
            for s, v in sorted(summary.at_zero.items())
        },
        "calibration": {
            "declenchee": calibration.triggered,
            "alpha": calibration.alpha,
            "taux_nominal": calibration.nominal_rate,
            "taux": list(calibration.rates),
        },
        "absence_hors_d_atteinte": summary.no_effect_out_of_reach,
        "non_tranche_attendu": summary.undecided_expected,
        "message": "données insuffisantes pour juger un effet de 5 %/an"
        if summary.insufficient
        else None,
        "tirages_en_echec": sum(sum(f) for f in summary.failed.values()),
    }


def _period(data: Q2Data) -> dict[str, str] | None:
    days = [d.day for r in Q2_REGIMES for d in data.days[r]]
    if not days:
        return None
    return {"debut": min(days).isoformat(), "fin": max(days).isoformat()}


def common_provenance(
    data: Q2Data,
    tables: ProcessedProvenance,
    parameters: ParameterSet,
    *,
    command: str,
    commit: str,
    package_version: str,
) -> dict[str, object]:
    """Les champs communs aux deux provenances (§ 10.1), sans les fichiers ni la date
    de génération."""
    periods = data.periods
    return {
        "question": "Q2",
        "commande": command,
        "commit": commit,
        "version_du_paquet": package_version,
        "periode": _period(data),
        "tables": dataclasses.asdict(tables),
        "periodes": None
        if periods is None
        else {
            "debut": periods.discovery_start.isoformat(),
            "fin": periods.discovery_end.isoformat(),
        },
        "parametres": dict(sorted(parameters.values.items())),
        "graine": Q2_ROOT_SEED,
        "appareil_principal": {
            "fabricant": data.principal[0],
            "produit": data.principal[1],
        },
    }


def write_folder(
    data_dir: Path,
    relative: Path,
    files: Mapping[str, str],
    document: Mapping[str, object],
    generated_on: date,
) -> Path:
    """Écrit ``files`` et ``provenance.json`` (``document`` plus les empreintes des
    fichiers, puis ``genere_le``) dans ``data_dir/relative/<date>_<empreinte>/``,
    sous un nom temporaire puis renommé ; :class:`Q2ResultsError` si le dossier existe
    déjà (rien n'est écrit)."""
    full = {
        **document,
        "fichiers": {name: sha256_text(text) for name, text in sorted(files.items())},
    }
    name = f"{generated_on.isoformat()}_{sha256_text(json_text(full))[:12]}"
    root = data_dir / relative
    target = root / name
    if target.exists():
        raise Q2ResultsError(
            f"{(relative / name).as_posix()}/ existe déjà : rien n'est réécrit"
        )
    temporary = root / f"{_TEMPORARY_PREFIX}{name}{_TEMPORARY_SUFFIX}"
    if temporary.exists():
        shutil.rmtree(temporary)
    try:
        temporary.mkdir(parents=True)
        for file_name, text in files.items():
            (temporary / file_name).write_text(text, encoding="utf-8", newline="")
        dated = {**full, "genere_le": generated_on.isoformat()}
        (temporary / PROVENANCE_FILE).write_text(
            json_text(dated), encoding="utf-8", newline=""
        )
    except BaseException:
        shutil.rmtree(temporary, ignore_errors=True)
        raise
    temporary.rename(target)
    return target


def write_power_results(
    data_dir: Path,
    result: PowerResult,
    data: Q2Data,
    specs: Mapping[tuple[ClimbRegime, Measure], ModelSpec],
    tables: ProcessedProvenance,
    parameters: ParameterSet,
    *,
    commit: str,
    package_version: str,
    generated_on: date,
) -> Path:
    """Écrit ``resultats/Q2/puissance/<date>_<empreinte>/`` : ``puissance.csv``,
    ``flux.csv``, ``provenance.json`` (sans ``b̂`` ni aucun terme de date ajusté sur
    les données)."""
    files = {POWER_FILE: power_csv(result), FLUX_FILE: flux_csv(data, specs)}
    document = {
        **common_provenance(
            data,
            tables,
            parameters,
            command=POWER_COMMAND,
            commit=commit,
            package_version=package_version,
        ),
        "grilles": {
            "b_fraction_par_an": {
                str(s): list(f) for s, f in sorted(result.grids.fractions.items())
            },
            "seuils": {r.regime.value: list(r.alphas) for r in result.regimes},
        },
        "regimes": {r.regime.value: _regime_document(r) for r in result.regimes},
    }
    return write_folder(data_dir, POWER_DIR, files, document, generated_on)


# --- la relecture du dernier résultat de puissance ---------------------------------


@dataclass(frozen=True)
class StoredPower:
    """Le résultat de puissance retenu : son dossier, l'empreinte SHA-256 de son
    ``provenance.json``, et ce que l'estimation en lit, par régime."""

    folder: Path
    digest: str
    levels: Mapping[str, PowerLevel]


def _temporary(name: str) -> bool:
    return name.startswith(_TEMPORARY_PREFIX) and name.endswith(_TEMPORARY_SUFFIX)


def _read_power(folder: Path) -> tuple[date, dict[str, object], bytes] | None:
    try:
        raw = (folder / PROVENANCE_FILE).read_bytes()
        document = json.loads(raw.decode("utf-8"))
    except (OSError, UnicodeDecodeError, ValueError):
        return None
    if not isinstance(document, dict):
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
    return generated_on, document, raw


def _levels(document: Mapping[str, object]) -> dict[str, PowerLevel]:
    levels: dict[str, PowerLevel] = {}
    regimes = document.get("regimes")
    if not isinstance(regimes, dict):
        return levels
    for name, entry in regimes.items():
        calibration = entry.get("calibration") if isinstance(entry, dict) else None
        if not isinstance(calibration, dict):
            levels[name] = PowerLevel(False, False, None)
            continue
        alpha = calibration.get("alpha")
        levels[name] = PowerLevel(
            True,
            bool(calibration.get("declenchee")),
            float(alpha) if isinstance(alpha, int | float) else None,
        )
    return levels


def _written_ns(folder: Path) -> int:
    try:
        return (folder / PROVENANCE_FILE).stat().st_mtime_ns
    except OSError:
        return 0


def latest_power(data_dir: Path, current: ProcessedProvenance) -> StoredPower | None:
    """Le dernier résultat de puissance des tables ``current`` (§ 10.3) : parmi les
    dossiers complets de ``resultats/Q2/puissance/`` dont la valeur ``tables`` est
    celle de ``current`` (relue par JSON), la ``genere_le`` la plus récente ; à
    égalité, le ``provenance.json`` écrit le plus tard ; puis le nom le plus grand.
    ``None`` s'il n'y en a pas."""
    root = data_dir / POWER_DIR
    if not root.is_dir():
        return None
    written = json.loads(json.dumps(dataclasses.asdict(current)))
    candidates: list[tuple[tuple[date, int, str], Path, dict[str, object], bytes]] = []
    for folder in root.iterdir():
        if not folder.is_dir() or _temporary(folder.name):
            continue
        if not RESULT_NAME.fullmatch(folder.name):
            continue
        read = _read_power(folder)
        if read is None or read[1].get("tables") != written:
            continue
        generated_on, document, raw = read
        key = (generated_on, _written_ns(folder), folder.name)
        candidates.append((key, folder, document, raw))
    if not candidates:
        return None
    _, folder, document, raw = max(candidates, key=lambda item: item[0])
    return StoredPower(folder, hashlib.sha256(raw).hexdigest(), _levels(document))


# --- l'estimation ------------------------------------------------------------------

TRIALS_FILE = "essais.csv"
FIGURE_CSV = "figure.csv"
FIGURE_HTML = "figure.html"
AUTOCORRELATION_FILE = "autocorrelation.csv"
JOURNAL = Path("resultats") / "essais.jsonl"
"""Le journal chaîné des essais, sous ``MPA_DATA_DIR``."""
FIGURE_COLUMNS: tuple[str, ...] = (
    "type",
    "date",
    "residu_partiel",
    "estimation",
    "bas",
    "haut",
    "provisoire",
)
AUTOCORRELATION_COLUMNS: tuple[str, ...] = (
    "regime",
    "mesure",
    "de",
    "a",
    "paires",
    "correlation",
)


def trial_columns() -> tuple[str, ...]:
    """Les colonnes d'``essais.csv`` : un champ de ``TrialRow`` par colonne, un
    intervalle en deux (``_bas``, ``_haut``)."""
    columns: list[str] = []
    for item in dataclasses.fields(TrialRow):
        if item.name in INTERVAL_FIELDS:
            columns += [f"{item.name}_bas", f"{item.name}_haut"]
        else:
            columns.append(item.name)
    return tuple(columns)


def _trial_cells(row: TrialRow) -> list[object]:
    cells: list[object] = []
    for item in dataclasses.fields(TrialRow):
        value = getattr(row, item.name)
        if item.name in INTERVAL_FIELDS:
            cells += [None, None] if value is None else [value[0], value[1]]
        else:
            cells.append(value)
    return cells


def essais_csv(rows: Sequence[TrialRow]) -> str:
    """``essais.csv`` : les lignes d'essai, dans l'ordre des indices."""
    return csv_text(trial_columns(), [_trial_cells(r) for r in rows])


def autocorrelation_csv(
    rows: Sequence[tuple[str, str, int, int | None, int, float | None]],
) -> str:
    """``autocorrelation.csv`` (``a`` vide à la dernière classe, ``correlation`` vide
    sans paire)."""
    return csv_text(AUTOCORRELATION_COLUMNS, rows)


def figure_csv(figure: Q2Figure | None) -> str:
    """``figure.csv`` : une ligne ``point`` par journée, puis une ligne ``courbe`` par
    jour de la grille ; son seul en-tête sans figure."""
    rows: list[list[object]] = []
    if figure is not None:
        rows += [
            ["point", p.day.isoformat(), p.residual, None, None, None, None]
            for p in figure.points
        ]
        rows += [
            [
                "courbe",
                c.day.isoformat(),
                None,
                c.estimate,
                c.low,
                c.high,
                c.provisional,
            ]
            for c in figure.curve
        ]
    return csv_text(FIGURE_COLUMNS, rows)


def _json_value(value: object) -> object:
    if isinstance(value, float) and not math.isfinite(value):
        return None
    if isinstance(value, tuple):
        return [_json_value(v) for v in value]
    return value


def trial_record(row: TrialRow) -> dict[str, object]:
    """Les champs de ``row`` en types JSON, dans l'ordre de ``TrialRow`` (un
    intervalle en liste, ``NaN`` et absences en ``null``)."""
    return {
        item.name: _json_value(getattr(row, item.name))
        for item in dataclasses.fields(TrialRow)
    }


def _broken(line: int) -> Q2ResultsError:
    return Q2ResultsError(
        f"essais.jsonl, ligne {line} : la chaîne est rompue ; rien n'est écrit"
    )


def check_trials(data_dir: Path) -> str | None:
    """Relit ``resultats/essais.jsonl`` en entier : chaque ligne se décode et son
    ``precedente`` est l'empreinte de la ligne d'avant (``null`` pour la première).
    Rend l'empreinte de la dernière ligne (``None`` sans fichier, ou vide) ;
    :class:`Q2ResultsError` à la première ligne qui ne suit plus.

    Limite : une retouche de la **dernière** ligne ne se voit pas par la chaîne
    seule."""
    path = data_dir / JOURNAL
    if not path.exists():
        return None
    data = path.read_bytes()
    if not data:
        return None
    if not data.endswith(b"\n"):
        raise _broken(data.count(b"\n") + 1)
    previous: str | None = None
    for number, line in enumerate(data[:-1].split(b"\n"), start=1):
        try:
            record = json.loads(line.decode("utf-8"))
        except (UnicodeDecodeError, ValueError) as error:
            raise _broken(number) from error
        if not isinstance(record, dict) or record.get("precedente") != previous:
            raise _broken(number)
        previous = content_hash(line)
    return previous


def append_trials(
    data_dir: Path, execution: str, commit: str, rows: Sequence[TrialRow]
) -> None:
    """Ajoute une ligne par essai de ``rows`` à ``resultats/essais.jsonl``, en une
    seule écriture, chaînées sur la dernière ligne existante ; la chaîne est relue
    d'abord (:func:`check_trials`) : rompue, rien n'est écrit."""
    previous = check_trials(data_dir)
    lines: list[bytes] = []
    for row in rows:
        record = {
            "question": "Q2",
            "execution": execution,
            "commit": commit,
            "essai": trial_record(row),
            "precedente": previous,
        }
        line = canonical_bytes(record)
        lines.append(line + b"\n")
        previous = content_hash(line)
    path = data_dir / JOURNAL
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("ab") as journal:
        journal.write(b"".join(lines))


def estimation_files(
    estimation: Q2Estimation, data: Q2Data, figure: Q2Figure | None, html: str
) -> dict[str, str]:
    """Les fichiers du dossier d'estimation, sauf ``provenance.json``."""
    return {
        TRIALS_FILE: essais_csv(estimation.rows),
        FLUX_FILE: flux_csv(data, estimation.specs),
        FIGURE_CSV: figure_csv(figure),
        FIGURE_HTML: html,
        AUTOCORRELATION_FILE: autocorrelation_csv(estimation.autocorrelation),
    }


def estimation_document(
    estimation: Q2Estimation,
    data: Q2Data,
    figure: Q2Figure | None,
    tables: ProcessedProvenance,
    parameters: ParameterSet,
    power: StoredPower,
    *,
    commit: str,
    package_version: str,
) -> dict[str, object]:
    """La provenance du dossier d'estimation, sans les fichiers ni ``genere_le``."""
    return {
        **common_provenance(
            data,
            tables,
            parameters,
            command=ESTIMATION_COMMAND,
            commit=commit,
            package_version=package_version,
        ),
        "puissance": {"dossier": power.folder.name, "empreinte": power.digest},
        "niveaux": dict(estimation.levels),
        "non_faites": list(NOT_DONE),
        "bornes": dict(estimation.bounds),
        "figure": None
        if figure is None
        else {
            "noeuds": list(figure.knots),
            "tirages": figure.draws,
            "cle": [Q2_ROOT_SEED, *figure.key],
        },
    }


def write_estimation_results(
    data_dir: Path,
    estimation: Q2Estimation,
    data: Q2Data,
    figure: Q2Figure | None,
    html: str,
    tables: ProcessedProvenance,
    parameters: ParameterSet,
    power: StoredPower,
    *,
    commit: str,
    package_version: str,
    generated_on: date,
) -> Path:
    """Écrit ``resultats/Q2/<date>_<empreinte>/`` : ``essais.csv``, ``flux.csv``,
    ``figure.csv``, ``figure.html``, ``autocorrelation.csv``, ``provenance.json``.
    :class:`Q2ResultsError` si le dossier existe déjà (rien n'est écrit)."""
    document = estimation_document(
        estimation,
        data,
        figure,
        tables,
        parameters,
        power,
        commit=commit,
        package_version=package_version,
    )
    files = estimation_files(estimation, data, figure, html)
    return write_folder(data_dir, RESULTS_DIR, files, document, generated_on)


# --- la relecture d'un résultat d'estimation (AN3-5) ------------------------------

INT_COLUMNS: tuple[str, ...] = (
    "indice",
    "n_journees",
    "n_montees",
    "p",
    "tirages_retires",
    "montees_retirees",
)
"""Les colonnes d'``essais.csv`` relues en entiers."""
FLOAT_COLUMNS: tuple[str, ...] = (
    "niveau",
    "estimation_fraction",
    "intervalle_fraction_bas",
    "intervalle_fraction_haut",
    "inverse_fraction",
    "intervalle_inverse_fraction_bas",
    "intervalle_inverse_fraction_haut",
    "p_valeur",
    "kappa",
    "intervalle_kappa_bas",
    "intervalle_kappa_haut",
    "tau2",
    "s2u",
    "phi",
)
"""Les colonnes d'``essais.csv`` relues en flottants (``inf`` compris)."""
BOOL_COLUMNS: tuple[str, ...] = (
    "k_contient_zero",
    "holm_rejet",
    "tau2_a_zero",
    "s2u_a_zero",
    "phi_a_la_borne_basse",
    "phi_a_la_borne_haute",
    "phi_identifie",
    "variante_effective",
    "exploratoire",
)
"""Les colonnes d'``essais.csv`` relues en booléens (``true``, ``false``) ; les
autres colonnes restent du texte."""
REGIME_ORDER: tuple[str, ...] = ("long_climb", "short_climb", "ski_touring")
"""L'ordre des mises en garde de la puissance, par régime."""
_LONG = "long_climb"
_BIAS_SCENARIO = "4"
_CALCULATED = "calculee"
_FLUX_KEY: tuple[str, ...] = ("regime", "mesure", "periode", "etape", "motif")


@dataclass(frozen=True)
class StoredEstimation:
    """Un dossier d'estimation de Q2 relu : son chemin, sa date de génération, la
    valeur ``tables`` de son ``provenance.json``, telle que relue, et ce document
    entier."""

    folder: Path
    generated_on: date
    tables: object
    document: Mapping[str, object]


@dataclass(frozen=True)
class LatestEstimation:
    """L'estimation retenue par :func:`latest_estimation`, ce qu'elle dit des tables
    actuelles, et le compte des dossiers illisibles."""

    estimation: StoredEstimation
    match: TablesMatch
    unreadable: int


@dataclass(frozen=True)
class RegimeWarning:
    """Les mises en garde d'un régime calculé, lues dans la puissance que nomme
    l'estimation : la part de « établi » à effet nul simulé (scénario 1), le seuil
    nominal, le message de la puissance, et, aux montées longues seulement, le biais
    du scénario 4 à ``delta``."""

    regime: str
    established_at_zero: float | None
    nominal_level: float | None
    message: str | None
    bias_at_delta: float | None


@dataclass(frozen=True)
class EstimationReading:
    """Ce que la page « Q2 » montre d'un dossier d'estimation, relu sans recalcul.
    ``power`` vaut ``None`` si la puissance nommée manque ou a changé, ou si aucune
    n'est nommée (``power_folder`` vaut alors ``None``)."""

    trials: tuple[Mapping[str, object], ...]
    figure_html: str | None
    flux: tuple[Mapping[str, object], ...]
    autocorrelation: tuple[Mapping[str, object], ...]
    period: Mapping[str, str] | None
    bounds: Mapping[str, object]
    power_folder: str | None
    power: tuple[RegimeWarning, ...] | None
    delta: float | None


def _stored_estimation(folder: Path) -> StoredEstimation | None:
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
    if not (folder / TRIALS_FILE).is_file():
        return None
    return StoredEstimation(folder, generated_on, document["tables"], document)


def stored_estimations(data_dir: Path) -> tuple[tuple[StoredEstimation, ...], int]:
    """Les dossiers d'estimation de Q2 sous ``data_dir``, triés par nom, et le compte
    des illisibles. Seuls les dossiers au nom de ``RESULT_NAME`` sont considérés
    (``puissance/``, les dossiers temporaires et tout autre nom sont ignorés, sans être
    comptés) ; l'un d'eux est illisible si ``provenance.json`` manque ou ne se lit pas
    (UTF-8, JSON), n'est pas un objet, n'a pas ``tables``, si ``genere_le`` n'est pas
    une date ``AAAA-MM-JJ`` égale au préfixe du nom, ou si ``essais.csv`` manque."""
    root = data_dir / RESULTS_DIR
    if not root.is_dir():
        return (), 0
    folders = sorted(
        (
            path
            for path in root.iterdir()
            if path.is_dir() and RESULT_NAME.fullmatch(path.name)
        ),
        key=lambda path: path.name,
    )
    estimations: list[StoredEstimation] = []
    unreadable = 0
    for folder in folders:
        stored = _stored_estimation(folder)
        if stored is None:
            unreadable += 1
        else:
            estimations.append(stored)
    return tuple(estimations), unreadable


def latest_estimation(
    data_dir: Path, current: ProcessedProvenance | None
) -> LatestEstimation | None:
    """La dernière estimation de Q2, à la règle de Q1 (``latest_result``) : parmi les
    dossiers des tables actuelles (``current``, écrite comme ``provenance.json``
    l'écrit), sinon parmi tous, la ``genere_le`` la plus récente ; à égalité, le
    ``provenance.json`` écrit le plus tard ; puis le nom le plus grand. ``None`` sans
    dossier lisible."""
    estimations, unreadable = stored_estimations(data_dir)
    if not estimations:
        return None
    if current is None:
        match, candidates = TablesMatch.UNKNOWN, estimations
    else:
        written = json.loads(json.dumps(dataclasses.asdict(current)))
        same = tuple(e for e in estimations if e.tables == written)
        match = TablesMatch.SAME if same else TablesMatch.DIFFERENT
        candidates = same or estimations
    latest = max(
        candidates,
        key=lambda e: (e.generated_on, _written_ns(e.folder), e.folder.name),
    )
    return LatestEstimation(latest, match, unreadable)


@contextlib.contextmanager
def _reading(label: str) -> Iterator[None]:
    """Toute erreur de lecture sous ``label`` (le fichier) devient
    :class:`Q2ResultsError`, qui le nomme."""
    try:
        yield
    except Q2ResultsError:
        raise
    except (
        OSError,
        KeyError,
        IndexError,
        ValueError,
        TypeError,
        AttributeError,
        csv.Error,
    ) as error:
        raise Q2ResultsError(f"{label} : ne se relit pas ({error!r})") from error


def _object(value: object, what: str) -> Mapping[str, object]:
    if not isinstance(value, dict):
        raise TypeError(f"{what} n'est pas un objet")
    return value


def _number(value: object, what: str) -> float | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise TypeError(f"{what} n'est pas un nombre")
    return float(value)


def _text_or_none(value: object, what: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise TypeError(f"{what} n'est pas un texte")
    return value


def _csv_rows(
    path: Path, label: str, columns: Sequence[str], *, required: bool
) -> list[dict[str, str]] | None:
    """Les lignes d'un CSV, réduites à ``columns`` ; ``None`` s'il manque et n'est pas
    exigé ; :class:`Q2ResultsError` s'il lui manque une colonne ou une case."""
    if not required and not path.exists():
        return None
    rows: list[dict[str, str]] = []
    with _reading(label), path.open(encoding="utf-8", newline="") as stream:
        reader = csv.DictReader(stream)
        header = reader.fieldnames or []
        missing = [c for c in columns if c not in header]
        if missing:
            raise Q2ResultsError(f"{label} : colonnes absentes : {', '.join(missing)}")
        for number, row in enumerate(reader, start=2):
            values = [row.get(c) for c in columns]
            if any(v is None for v in values):
                raise Q2ResultsError(f"{label}, ligne {number} : cases manquantes")
            rows.append({c: str(v) for c, v in zip(columns, values, strict=True)})
    return rows


def _trial_value(column: str, text: str, where: str) -> object:
    """Une case d'``essais.csv`` relue (``cell`` à l'envers)."""
    if text == "":
        return None
    try:
        if column in BOOL_COLUMNS:
            if text in ("true", "false"):
                return text == "true"
            raise ValueError(text)
        if column in INT_COLUMNS:
            return int(text)
        if column in FLOAT_COLUMNS:
            return float(text)
    except ValueError as error:
        raise Q2ResultsError(
            f"{where}, colonne {column} : case illisible « {text} »"
        ) from error
    return text


def _trials(path: Path, label: str) -> tuple[Mapping[str, object], ...]:
    columns = trial_columns()
    rows = _csv_rows(path, label, columns, required=True) or []
    return tuple(
        {c: _trial_value(c, row[c], f"{label}, ligne {number}") for c in columns}
        for number, row in enumerate(rows, start=2)
    )


def flux_summary(rows: Sequence[Mapping[str, str]]) -> tuple[dict[str, object], ...]:
    """Les lignes de ``flux.csv`` sommées sur les mois : une ligne par (``regime``,
    ``mesure``, ``periode``, ``etape``, ``motif``), dans l'ordre de première
    apparition, ``journees`` et ``montees`` sommées, ``valeur`` à ``None`` ; une ligne
    dont ``valeur`` n'est pas vide (``hors_mouvement``) passe seule, sans être
    sommée, ``valeur`` en flottant. Chaque ligne rendue a ces cinq clés, puis
    ``journees``, ``montees`` et ``valeur``."""
    order: list[tuple[str, ...] | int] = []
    sums: dict[tuple[str, ...], list[int]] = {}
    alone: dict[int, dict[str, object]] = {}
    for index, row in enumerate(rows):
        key = tuple(row[c] for c in _FLUX_KEY)
        days, climbs = int(row["journees"]), int(row["montees"])
        if row["valeur"] != "":
            order.append(index)
            alone[index] = {
                **dict(zip(_FLUX_KEY, key, strict=True)),
                "journees": days,
                "montees": climbs,
                "valeur": float(row["valeur"]),
            }
            continue
        if key not in sums:
            order.append(key)
            sums[key] = [0, 0]
        sums[key][0] += days
        sums[key][1] += climbs
    lines: list[dict[str, object]] = []
    for item in order:
        if isinstance(item, int):
            lines.append(alone[item])
            continue
        lines.append(
            {
                **dict(zip(_FLUX_KEY, item, strict=True)),
                "journees": sums[item][0],
                "montees": sums[item][1],
                "valeur": None,
            }
        )
    return tuple(lines)


def _autocorrelation(
    rows: Sequence[Mapping[str, str]],
) -> tuple[dict[str, object], ...]:
    return tuple(
        {
            "regime": row["regime"],
            "mesure": row["mesure"],
            "de": int(row["de"]),
            "a": None if row["a"] == "" else int(row["a"]),
            "paires": int(row["paires"]),
            "correlation": None
            if row["correlation"] == ""
            else float(row["correlation"]),
        }
        for row in rows
    )


def _read_period(document: Mapping[str, object]) -> Mapping[str, str] | None:
    value = document.get("periode")
    if value is None:
        return None
    period = _object(value, "periode")
    start, end = period["debut"], period["fin"]
    if not isinstance(start, str) or not isinstance(end, str):
        raise TypeError("periode : debut et fin ne sont pas des dates")
    date.fromisoformat(start)
    date.fromisoformat(end)
    return {"debut": start, "fin": end}


def _read_bounds(document: Mapping[str, object]) -> Mapping[str, object]:
    value = document.get("bornes")
    if value is None:
        return {}
    bounds = _object(value, "bornes")
    for regime, entry in bounds.items():
        _object(entry, f"bornes.{regime}")
    return dict(bounds)


def _bias(path: Path, label: str, delta: float) -> float | None:
    rows = _csv_rows(path, label, POWER_COLUMNS, required=False)
    if rows is None:
        return None
    with _reading(label):
        for row in rows:
            if (
                row["regime"] == _LONG
                and row["scenario"] == _BIAS_SCENARIO
                and float(row["b_fraction_par_an"]) == delta
            ):
                bias = row["biais_fraction_par_an"]
                return None if bias == "" else float(bias)
    return None


def _power(
    data_dir: Path, document: Mapping[str, object], label: str
) -> tuple[str | None, tuple[RegimeWarning, ...] | None, float | None]:
    """La puissance que nomme l'estimation : ``(dossier, mises en garde, delta)`` ;
    sans puissance nommée, ``(None, None, None)`` ; nommée mais absente ou changée
    (empreinte), ``(dossier, None, None)``, comme un nom qui n'est pas un nom de
    résultat (``RESULT_NAME``), traité comme une puissance absente."""
    if "puissance" not in document:
        return None, None, None
    with _reading(label):
        named = _object(document["puissance"], "puissance")
        name, digest = named["dossier"], named["empreinte"]
        if not isinstance(name, str) or not isinstance(digest, str):
            raise TypeError("puissance : dossier et empreinte ne sont pas des textes")
    if not RESULT_NAME.fullmatch(name):
        return name, None, None
    folder = data_dir / POWER_DIR / name
    try:
        raw = (folder / PROVENANCE_FILE).read_bytes()
    except OSError:
        return name, None, None
    if hashlib.sha256(raw).hexdigest() != digest:
        return name, None, None
    power_label = (POWER_DIR / name / PROVENANCE_FILE).as_posix()
    warnings: list[RegimeWarning] = []
    with _reading(power_label):
        power = _object(json.loads(raw.decode("utf-8")), "provenance")
        parameters = _object(power["parametres"], "parametres")
        delta = _number(parameters["delta"], "parametres.delta")
        if delta is None:
            raise TypeError("parametres.delta est vide")
        regimes = _object(power["regimes"], "regimes")
        for regime in REGIME_ORDER:
            if regime not in regimes:
                continue
            entry = _object(regimes[regime], f"regimes.{regime}")
            if entry.get("statut") != _CALCULATED:
                continue
            at_zero = _object(entry["a_zero"], f"regimes.{regime}.a_zero")
            first = _object(at_zero["1"], f"regimes.{regime}.a_zero.1")
            levels = entry["seuils"]
            if not isinstance(levels, list):
                raise TypeError(f"regimes.{regime}.seuils n'est pas une liste")
            warnings.append(
                RegimeWarning(
                    regime,
                    _number(first["p_etabli"], "p_etabli"),
                    _number(levels[0], "seuils"),
                    _text_or_none(entry["message"], "message"),
                    None,
                )
            )
    csv_label = (POWER_DIR / name / POWER_FILE).as_posix()
    read = tuple(
        dataclasses.replace(
            warning, bias_at_delta=_bias(folder / POWER_FILE, csv_label, delta)
        )
        if warning.regime == _LONG
        else warning
        for warning in warnings
    )
    return name, read, delta


def read_estimation(data_dir: Path, estimation: StoredEstimation) -> EstimationReading:
    """Relit un dossier d'estimation, sans rien recalculer : les essais typés, la
    figure (``None`` si elle ne s'ouvre pas), le flux sommé sur les mois,
    l'autocorrélation, la période, les bornes, et la puissance que nomme
    ``provenance.json``, à son empreinte. ``flux.csv`` ou ``autocorrelation.csv``
    absent : ``()`` ; ``puissance.csv`` absent : les biais à ``None``. Tout fichier mal
    formé lève :class:`Q2ResultsError`, qui nomme le fichier ; aucune autre exception
    n'en sort."""
    folder = estimation.folder
    base = f"{RESULTS_DIR.as_posix()}/{folder.name}"
    trials = _trials(folder / TRIALS_FILE, f"{base}/{TRIALS_FILE}")
    figure_html: str | None
    with _reading(f"{base}/{FIGURE_HTML}"):
        try:
            figure_html = (folder / FIGURE_HTML).read_text(encoding="utf-8")
        except OSError:
            figure_html = None
    flux_label = f"{base}/{FLUX_FILE}"
    flux_read = _csv_rows(folder / FLUX_FILE, flux_label, FLUX_COLUMNS, required=False)
    with _reading(flux_label):
        flux = () if flux_read is None else flux_summary(flux_read)
    auto_label = f"{base}/{AUTOCORRELATION_FILE}"
    auto_read = _csv_rows(
        folder / AUTOCORRELATION_FILE,
        auto_label,
        AUTOCORRELATION_COLUMNS,
        required=False,
    )
    with _reading(auto_label):
        autocorrelation = () if auto_read is None else _autocorrelation(auto_read)
    provenance_label = f"{base}/{PROVENANCE_FILE}"
    document = estimation.document
    with _reading(provenance_label):
        period = _read_period(document)
        bounds = _read_bounds(document)
    power_folder, power, delta = _power(data_dir, document, provenance_label)
    return EstimationReading(
        trials=trials,
        figure_html=figure_html,
        flux=flux,
        autocorrelation=autocorrelation,
        period=period,
        bounds=bounds,
        power_folder=power_folder,
        power=power,
        delta=delta,
    )
