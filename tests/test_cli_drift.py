"""La rubrique « dérive » du rapport complet (``cli.py`` ; précision P12.10 de M4d-1,
arbitrage E4) : le format de ``rho_u``, le signe face aux retraits, les mentions, la
ligne de la table. Le rapport du monde (``backtest_rapport_monde.txt``) tient le reste
au caractère près."""

import pytest

from mountain_perf import cli
from mountain_perf.schemas import DRIFT_WEAK_SEPARATION, DriftDiagnostic, Unavailability
from test_schemas_drift import available, fit, unavailable


@pytest.mark.parametrize(
    ("rho", "text"),
    [
        (0.945990, "0.945990"),
        (1e-3, "0.001000"),
        (2.5e-7, "2.50e-07"),
        (1.0000099999222744e-10, "1.00e-10"),
        (1e-10, "≤ 1e−10"),
        (1.4e-64, "≤ 1e−10"),
        (0.0, "≤ 1e−10"),
    ],
)
def test_rho_format(rho: float, text: str) -> None:
    """``rho_u`` : six décimales ; sous ``1e−3``, notation scientifique ; au seuil
    d'identification ou dessous, ``≤ 1e−10`` (du bruit de calcul, sans lecture)."""
    assert cli._rho(rho) == text


def three(slopes: tuple[float | None, ...], b: float = 0.5) -> DriftDiagnostic:
    """Un diagnostic disponible de pente ``b`` dont les retraits ont ``slopes``."""
    withdrawals = tuple(
        fit(count=2, rank=1, slope=s)
        if s is not None
        else fit(count=2, rank=1, slope=None, rho=0.0)
        for s in slopes
    )
    present = [s for s in slopes if s is not None]
    return available(
        fit=fit(slope=b),
        withdrawals=withdrawals,
        slope_range=(min(present), max(present)) if present else None,
    )


@pytest.mark.parametrize(
    ("slopes", "b", "sign"),
    [
        ((0.1, 0.2, None), 0.5, "stable"),
        ((0.1, -0.2, 0.3), 0.5, "instable"),
        ((0.1, 0.0, 0.3), 0.5, "instable"),
        ((-0.1, -0.2, -0.3), -0.5, "stable"),
        ((0.0, 0.0, 0.0), 0.0, "stable"),
        ((None, None, None), 0.5, "non vérifiable"),
    ],
)
def test_sign_against_withdrawals(
    slopes: tuple[float | None, ...], b: float, sign: str
) -> None:
    """Signe (``> 0``, ``< 0``, ``= 0``) de ``b`` face aux retraits identifiables :
    « stable », « instable » dès qu'un retrait diffère, « non vérifiable » sans retrait
    identifiable ; « — » sans pente ou sans diagnostic."""
    assert cli._drift_sign(three(slopes, b)) == sign


def test_sign_without_slope() -> None:
    assert (
        cli._drift_sign(
            available(
                fit=fit(slope=None, rho=0.0),
                withdrawals=(fit(count=2, rank=1, slope=0.1),) * 3,
                slope_range=(0.1, 0.1),
            )
        )
        == "—"
    )
    assert cli._drift_sign(unavailable(Unavailability.NOT_CALIBRATED)) == "—"


@pytest.mark.parametrize(
    ("changes", "text"),
    [
        ({"count": 3, "rank": 2, "rho": 0.5}, "ajustement saturé"),
        ({"count": 4, "rank": 2, "rho": 0.5}, "très peu de degrés de liberté"),
        ({"count": 5, "rank": 2, "rho": 0.5}, "très peu de degrés de liberté"),
        ({"count": 6, "rank": 2, "rho": 0.5}, ""),
        ({"count": 6, "rank": 2, "rho": DRIFT_WEAK_SEPARATION}, ""),
        (
            {"count": 6, "rank": 2, "rho": 0.0999},
            "faible séparation position/régimes",
        ),
        (
            {"count": 4, "rank": 2, "rho": 0.034},
            "très peu de degrés de liberté ; faible séparation position/régimes",
        ),
        ({"count": 4, "rank": 2, "rho": 0.0, "slope": None}, ""),
    ],
)
def test_mentions(changes: dict[str, object], text: str) -> None:
    """``ddl = 0`` : « ajustement saturé » ; 1 ou 2 : « très peu de degrés de
    liberté » ; ``rho_u < 0,10`` (strict) : « faible séparation position/régimes » ;
    rien sans pente."""
    assert cli._drift_mention(fit(**changes)) == text


def test_drift_row_keeps_a_space_after_a_long_range() -> None:
    """L'étendue tient sur 26 caractères : les mentions ne s'y collent pas."""
    cells = [
        "v0 brut",
        "+1.300759",
        "0.034422",
        "3",
        "2",
        "6/6",
        "stable",
        "[−15.700000 ; +2.700000]",
        "très peu de degrés de liberté",
    ]
    row = cli._drift_row("écoulé", cells)
    assert "[−15.700000 ; +2.700000]  très peu" in row
    assert row.startswith(" " * 13 + "écoulé")


def test_unavailable_cells_carry_the_reason() -> None:
    """Un diagnostic indisponible : une seule cellule, le libellé de son motif."""
    for reason, label in (
        (Unavailability.MODEL_ERROR, "erreur du modèle"),
        (Unavailability.NOT_CALIBRATED, "non calé"),
        (Unavailability.INSUFFICIENT_SUPPORT, "support insuffisant"),
        (Unavailability.MULTI_OUTING_DAY, "jour multi-sorties"),
    ):
        assert cli._drift_fit_cells(unavailable(reason)) == [label]


def test_u_mz_u_format() -> None:
    """``uᵀ M_Z u`` (``0010`` D12) : trois chiffres en notation scientifique avec la
    pente ; « — » sans elle (au seuil d'identification ou dessous, du bruit)."""
    assert cli._umzu(fit(u_mz_u=0.0076892899)) == "7.689e-03"
    assert cli._umzu(fit(slope=None, rho=0.0, u_mz_u=1.4e-64)) == "—"
