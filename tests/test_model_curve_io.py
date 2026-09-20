"""Lecture de courbe : la fixture, les quatre règles du support, les erreurs.

Aucune courbe réelle n'entre ici : ``tests/fixtures/courbe_synthetique.csv`` est
inventée, minuscule, et ses vitesses sont des multiples de 3,6 km/h pour que les
m/s tombent juste.
"""

import json
import math
import tempfile
from itertools import pairwise
from pathlib import Path
from typing import Any

import pytest
from hypothesis import given
from hypothesis import strategies as st

from mountain_perf.model.curve_io import (
    CURVE_HEADER,
    CURVE_PARAMETER_SPECS,
    MIN_EDGE_GRADE,
    REASON_LOW_SUPPORT,
    REASON_OUTSIDE_RANGE,
    CurveError,
    curve_reference,
    read_curve,
)
from mountain_perf.schemas import ContractError, ParameterSet, Sport

FIXTURES = Path(__file__).parent / "fixtures"
CURVE = FIXTURES / "courbe_synthetique.csv"

# Courbe minimale valide : le noyau seul, sans extension possible.
MINIMAL = """\
grade_pct,kmh,hr,vam_mh,time_min
-10.0,9.0,135,0,60.0
0.0,10.8,140,0,120.0
10.0,5.4,150,540,90.0
"""


def parameters(threshold_min: float | None = None) -> ParameterSet:
    values = {} if threshold_min is None else {"curve_min_support_min": threshold_min}
    return ParameterSet(CURVE_PARAMETER_SPECS, values)


def base_meta() -> dict[str, Any]:
    content = (FIXTURES / "courbe_synthetique.meta.json").read_text(encoding="utf-8")
    loaded: dict[str, Any] = json.loads(content)
    return loaded


def write_curve(
    tmp_path: Path,
    *,
    csv_text: str | None = None,
    meta: dict[str, Any] | None = None,
    meta_text: str | None = None,
    with_meta: bool = True,
) -> Path:
    """Écrit un couple CSV / compagnon dans ``tmp_path`` et rend le chemin du CSV."""
    path = tmp_path / "courbe.csv"
    path.write_text(
        CURVE.read_text(encoding="utf-8") if csv_text is None else csv_text,
        encoding="utf-8",
    )
    if with_meta:
        companion = tmp_path / "courbe.meta.json"
        if meta_text is None:
            meta_text = json.dumps(base_meta() if meta is None else meta)
        companion.write_text(meta_text, encoding="utf-8")
    return path


# ---------------------------------------------------------------------------
# La fixture synthétique
# ---------------------------------------------------------------------------


def test_synthetic_curve_is_read_as_expected() -> None:
    result = read_curve(CURVE, parameters())
    assert result.bin_count_read == 9
    assert result.bin_count_kept == 5
    assert result.curve.grade == (-0.20, -0.10, 0.0, 0.10, 0.20)
    # Exact : ce sont des km/h choisis pour être des multiples de 3,6.
    assert result.curve.speed_ms == (2.0, 2.5, 3.0, 1.5, 1.0)
    # Des secondes de données assimilées à des échantillons : le CSV ne compte
    # aucun point (ligne de BACKLOG.md pour M6b).
    assert result.curve.sample_count == (1800, 3600, 7200, 5400, 2700)
    assert result.curve.dispersion_ms is None
    assert result.kept_grade_range == (-0.20, 0.20)
    assert result.curve.sport is Sport.FOOT


def test_source_and_reference_name_the_file_not_the_path() -> None:
    result = read_curve(CURVE, parameters())
    assert result.source.kind == "csv"
    assert result.source.identifier == "courbe_synthetique.csv"
    assert result.curve.source == result.source
    assert result.curve_ref == curve_reference(result.source)
    assert result.curve_ref.startswith("courbe_synthetique.csv#")
    assert len(result.curve_ref.rpartition("#")[2]) == 12


def test_provenance_comes_from_the_companion() -> None:
    estimation = read_curve(CURVE, parameters()).curve.estimation
    assert estimation.activity_count == 3
    assert estimation.hr_center_bpm is None
    assert estimation.hr_width_bpm is None
    assert str(estimation.date_from) == "2026-01-01"
    assert str(estimation.date_to) == "2026-01-31"
    assert estimation.source_activity_types == frozenset({"trail_running"})
    assert estimation.estimator == "fixture synthétique"


# ---------------------------------------------------------------------------
# Sélection du support — les quatre règles
# ---------------------------------------------------------------------------


def test_extension_stops_at_the_first_slice_below_the_threshold() -> None:
    """Règle 3 : une tranche au-delà d'un trou est écartée, même bien fournie.

    C'est le cas qui distingue la règle 3 d'un simple filtre ``time_min >= seuil`` :
    ±40 % dépassent largement le seuil, mais ±30 % ne l'atteignent pas et arrêtent
    l'extension de leur côté. Un filtre plat retiendrait [−40 %, +40 %].
    """
    result = read_curve(CURVE, parameters())
    assert result.kept_grade_range == (-0.20, 0.20)
    reasons = {round(bin_.grade * 100): bin_.reason for bin_ in result.discarded}
    assert reasons == {
        -40: REASON_OUTSIDE_RANGE,
        -30: REASON_LOW_SUPPORT,
        30: REASON_LOW_SUPPORT,
        40: REASON_OUTSIDE_RANGE,
    }
    threshold = parameters()["curve_min_support_min"]
    beyond = [bin_ for bin_ in result.discarded if bin_.reason == REASON_OUTSIDE_RANGE]
    # Les deux tranches écartées « hors plage contiguë » dépassent pourtant le seuil.
    assert len(beyond) == 2
    assert all(bin_.time_min >= threshold for bin_ in beyond)


def test_a_missing_slice_is_not_a_gap() -> None:
    """La contiguïté se lit sur les lignes présentes, pas sur une grille théorique.

    La fixture est au pas de 10 points de pente alors que la vraie courbe est au pas
    de 5 : les tranches intermédiaires absentes n'interrompent pas l'extension.
    """
    kept = read_curve(CURVE, parameters()).curve.grade
    assert kept == (-0.20, -0.10, 0.0, 0.10, 0.20)


def test_threshold_zero_keeps_every_line() -> None:
    result = read_curve(CURVE, parameters(0.0))
    assert result.bin_count_kept == result.bin_count_read == 9
    assert result.discarded == ()


def test_missing_negative_side_names_the_missing_side(tmp_path: Path) -> None:
    """Règle 1 : aucune tranche n'est fautive ici, c'est un côté qui manque."""
    path = write_curve(
        tmp_path,
        csv_text=(
            "grade_pct,kmh,hr,vam_mh,time_min\n"
            "0.0,10.8,140,0,120.0\n"
            "10.0,5.4,150,540,90.0\n"
        ),
    )
    with pytest.raises(CurveError, match="aucune tranche de pente négative"):
        read_curve(path, parameters())


def test_missing_positive_side_names_the_missing_side(tmp_path: Path) -> None:
    path = write_curve(
        tmp_path,
        csv_text=(
            "grade_pct,kmh,hr,vam_mh,time_min\n"
            "-10.0,9.0,135,0,60.0\n"
            "0.0,10.8,140,0,120.0\n"
        ),
    )
    with pytest.raises(CurveError, match="aucune tranche de pente positive"):
        read_curve(path, parameters())


def test_empty_curve_says_no_usable_line(tmp_path: Path) -> None:
    path = write_curve(tmp_path, csv_text="grade_pct,kmh,hr,vam_mh,time_min\n")
    with pytest.raises(CurveError, match="aucune ligne exploitable"):
        read_curve(path, parameters())


def test_kernel_below_threshold_names_the_slice_its_support_and_the_threshold(
    tmp_path: Path,
) -> None:
    """Règle 2 : on ne saute pas une tranche centrale pour aller chercher plus loin."""
    path = write_curve(tmp_path, csv_text=MINIMAL)
    with pytest.raises(CurveError) as error:
        read_curve(path, parameters(100.0))
    message = str(error.value)
    assert "-10 %" in message
    assert "60.0 min" in message
    assert "100.0 min" in message


def test_support_too_tight_names_both_edges_and_the_minimum(tmp_path: Path) -> None:
    """Règle 4 : sans écartement minimal, l'allure du prolongement déborde."""
    path = write_curve(
        tmp_path,
        csv_text=(
            "grade_pct,kmh,hr,vam_mh,time_min\n"
            "-0.5,10.0,130,0,60.0\n"
            "0.5,9.0,140,0,60.0\n"
        ),
    )
    with pytest.raises(CurveError) as error:
        read_curve(path, parameters())
    message = str(error.value)
    assert "-0.5 %" in message
    assert "0.5 %" in message
    assert f"{MIN_EDGE_GRADE * 100:g} %" in message


# ---------------------------------------------------------------------------
# Erreurs de lecture — une par cas
# ---------------------------------------------------------------------------


def test_unexpected_header_is_rejected(tmp_path: Path) -> None:
    path = write_curve(tmp_path, csv_text=MINIMAL.replace("vam_mh", "vam"))
    with pytest.raises(CurveError, match="En-tête inattendu"):
        read_curve(path, parameters())


def test_duplicate_grade_is_rejected(tmp_path: Path) -> None:
    path = write_curve(tmp_path, csv_text=MINIMAL + "10.0,4.0,150,540,30.0\n")
    with pytest.raises(CurveError, match="Pente en double : 10 %"):
        read_curve(path, parameters())


@pytest.mark.parametrize("speed", ["0.0", "-5.4"])
def test_non_positive_speed_is_rejected(tmp_path: Path, speed: str) -> None:
    path = write_curve(tmp_path, csv_text=MINIMAL.replace("5.4", speed))
    with pytest.raises(CurveError, match="hors de"):
        read_curve(path, parameters())


@pytest.mark.parametrize("speed", ["540", "150"])
def test_speed_above_the_guard_is_rejected(tmp_path: Path, speed: str) -> None:
    """Une vitesse en m/s prise pour des km/h, ou une colonne décalée."""
    path = write_curve(tmp_path, csv_text=MINIMAL.replace("5.4", speed))
    with pytest.raises(CurveError, match="erreur d'unité ou de colonne"):
        read_curve(path, parameters())


def test_speed_below_the_guard_is_rejected(tmp_path: Path) -> None:
    """La borne basse est ce qui rend l'inversion sûre, pas un simple ``> 0``.

    Sans elle, une vitesse de ``1e-309`` m/s passe le contrat et l'allure au nœud
    vaut ``inf``, sans qu'aucun invariant ne s'en plaigne.
    """
    path = write_curve(tmp_path, csv_text=MINIMAL.replace("5.4", "0.005"))
    with pytest.raises(CurveError, match="erreur d'unité ou de colonne"):
        read_curve(path, parameters())


@pytest.mark.parametrize("column", ["hr", "vam_mh"])
def test_non_finite_value_in_an_ignored_column_is_rejected(
    tmp_path: Path, column: str
) -> None:
    """``hr`` et ``vam_mh`` ne servent à rien, mais elles sont lues **et validées**.

    Une cellule non finie signale un fichier abîmé, même dans une colonne dont le
    modèle ne se sert pas.
    """
    cell = {"hr": "135", "vam_mh": "540"}[column]
    path = write_curve(tmp_path, csv_text=MINIMAL.replace(f",{cell},", ",nan,"))
    with pytest.raises(CurveError, match="valeur non finie"):
        read_curve(path, parameters())


def test_non_numeric_value_is_rejected(tmp_path: Path) -> None:
    path = write_curve(tmp_path, csv_text=MINIMAL.replace("9.0", "abc"))
    with pytest.raises(CurveError, match="numérique illisible"):
        read_curve(path, parameters())


def test_grade_outside_the_contract_range_is_rejected(tmp_path: Path) -> None:
    path = write_curve(tmp_path, csv_text=MINIMAL.replace("-10.0", "-250.0"))
    with pytest.raises(CurveError, match="pente -250 % hors de"):
        read_curve(path, parameters())


def test_negative_time_min_is_rejected(tmp_path: Path) -> None:
    path = write_curve(tmp_path, csv_text=MINIMAL.replace(",60.0", ",-60.0"))
    with pytest.raises(CurveError, match="time_min doit être >= 0"):
        read_curve(path, parameters())


def test_missing_companion_names_the_expected_file(tmp_path: Path) -> None:
    path = write_curve(tmp_path, csv_text=MINIMAL, with_meta=False)
    with pytest.raises(CurveError) as error:
        read_curve(path, parameters())
    message = str(error.value)
    assert "courbe.meta.json" in message
    assert "courbe.csv" in message


def test_unreadable_companion_is_rejected(tmp_path: Path) -> None:
    path = write_curve(tmp_path, csv_text=MINIMAL, meta_text="{pas du json")
    with pytest.raises(CurveError, match="JSON illisible"):
        read_curve(path, parameters())


@pytest.mark.parametrize(
    "field",
    [
        "sport",
        "activity_count",
        "hr_center_bpm",
        "date_from",
        "date_to",
        "source_activity_types",
        "min_duration_s",
        "estimator",
        "generated_at",
    ],
)
def test_missing_companion_field_names_the_field(tmp_path: Path, field: str) -> None:
    meta = base_meta()
    del meta[field]
    path = write_curve(tmp_path, csv_text=MINIMAL, meta=meta)
    with pytest.raises(CurveError, match=f"champ « {field} » manquant"):
        read_curve(path, parameters())


def test_naive_generated_at_is_rejected(tmp_path: Path) -> None:
    """Ne jamais supposer un fuseau : un instant sans décalage n'en désigne aucun."""
    path = write_curve(
        tmp_path,
        csv_text=MINIMAL,
        meta=base_meta() | {"generated_at": "2026-02-01T12:00:00"},
    )
    with pytest.raises(CurveError, match="doit porter un fuseau horaire"):
        read_curve(path, parameters())


def test_unknown_sport_names_the_admitted_values(tmp_path: Path) -> None:
    path = write_curve(
        tmp_path, csv_text=MINIMAL, meta=base_meta() | {"sport": "trail"}
    )
    with pytest.raises(CurveError) as error:
        read_curve(path, parameters())
    message = str(error.value)
    assert "sport inconnu" in message
    for sport in Sport:
        assert sport.value in message


def test_half_a_heart_rate_window_remains_a_contract_error(tmp_path: Path) -> None:
    """Le contrat le vérifie déjà ; le lecteur ne recopie pas son message."""
    path = write_curve(
        tmp_path, csv_text=MINIMAL, meta=base_meta() | {"hr_center_bpm": 150}
    )
    with pytest.raises(ContractError, match="ensemble"):
        read_curve(path, parameters())


def test_unknown_companion_field_is_ignored(tmp_path: Path) -> None:
    """Pour ne pas bloquer une version future du fichier."""
    path = write_curve(
        tmp_path, csv_text=MINIMAL, meta=base_meta() | {"bin_width_pct": 5}
    )
    assert read_curve(path, parameters()).bin_count_kept == 3


# ---------------------------------------------------------------------------
# Propriété : ce que le lecteur garantit au modèle d'allure
# ---------------------------------------------------------------------------


@st.composite
def curve_csv_texts(draw: st.DrawFn) -> str:
    """CSV bien formés, valeurs quelconques : beaucoup seront refusés, c'est le but."""
    rows = draw(
        st.lists(
            st.tuples(
                st.integers(min_value=-60, max_value=60),
                st.floats(
                    min_value=0.5, max_value=20.0, allow_nan=False, allow_infinity=False
                ),
                st.integers(min_value=0, max_value=200),
                st.integers(min_value=0, max_value=2000),
                st.floats(
                    min_value=0.0,
                    max_value=200.0,
                    allow_nan=False,
                    allow_infinity=False,
                ),
            ),
            max_size=12,
            unique_by=lambda row: row[0],
        )
    )
    lines = [",".join(CURVE_HEADER)]
    lines += [f"{row[0]}.0,{row[1]},{row[2]},{row[3]},{row[4]}" for row in rows]
    return "\n".join(lines) + "\n"


@given(curve_csv_texts())
def test_reader_guarantees_what_the_pace_model_assumes(text: str) -> None:
    """Une courbe acceptée encadre strictement le plat et reste inversible.

    Le contrat ``PaceCurve`` vérifie ses propres invariants ; ce test garantit que
    le lecteur ne produit **jamais** d'objet qui les violerait, et qu'il tient en
    plus les préconditions dont :class:`~mountain_perf.model.pace.PaceModel` dépend
    sans les revérifier.
    """
    with tempfile.TemporaryDirectory() as directory:
        base = Path(directory)
        (base / "courbe.meta.json").write_text(
            json.dumps(base_meta()), encoding="utf-8"
        )
        path = base / "courbe.csv"
        path.write_text(text, encoding="utf-8")
        try:
            curve = read_curve(path, parameters()).curve
        except (CurveError, ContractError):
            return
    assert len(curve.grade) >= 2
    assert curve.grade[0] < 0 < curve.grade[-1]
    assert min(abs(curve.grade[0]), abs(curve.grade[-1])) >= MIN_EDGE_GRADE
    assert all(before < after for before, after in pairwise(curve.grade))
    assert all(speed > 0 and math.isfinite(1.0 / speed) for speed in curve.speed_ms)
    assert all(count >= 0 for count in curve.sample_count)
