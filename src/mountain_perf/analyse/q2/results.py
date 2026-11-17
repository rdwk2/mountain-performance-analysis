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

Python pur : ce module n'importe que la bibliothèque standard, ``analyse/q2/`` et
``analyse/inference/`` (par ses fonctions).
"""

from __future__ import annotations

import csv
import dataclasses
import hashlib
import io
import json
import re
import shutil
from collections.abc import Iterable, Mapping, Sequence
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
from mountain_perf.analyse.q2.model import Measure, ModelSpec
from mountain_perf.analyse.q2.parameters import Q2_REGIMES, Q2_ROOT_SEED
from mountain_perf.analyse.q2.power import (
    SCENARIOS,
    PowerLevel,
    PowerResult,
    RegimePower,
)
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
    ``essais.jsonl`` ne se relit pas ; rien n'est écrit."""


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


def json_text(document: object) -> str:
    """Un JSON trié, indenté, sans échappement ASCII."""
    return json.dumps(document, ensure_ascii=False, indent=2, sort_keys=True) + "\n"


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


def folder_name(
    files: Mapping[str, str], document: Mapping[str, object], generated_on: date
) -> str:
    """Le nom du dossier que :func:`write_folder` écrirait."""
    full = {
        **document,
        "fichiers": {name: sha256_text(text) for name, text in sorted(files.items())},
    }
    return f"{generated_on.isoformat()}_{sha256_text(json_text(full))[:12]}"


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
