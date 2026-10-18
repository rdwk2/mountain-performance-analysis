"""Constantes des fourchettes (``0010`` D11) : la relation que la batterie jointe ne
vérifiait pas (relecture C de la PR M4d-2). ``BAND_ALPHA`` n'est lu par aucun code : la
pénalité et les ordres extrêmes l'écrivent en dur, comme le brief ; ce test les lie.
"""

from mountain_perf.schemas import BAND_ALPHA, BAND_PENALTY, BAND_QUANTILE_ORDERS


def test_penalty_and_extreme_orders_follow_alpha() -> None:
    """D11 : la pénalité du score d'intervalle vaut ``2/alpha`` ; la plage va de
    l'ordre ``alpha/2`` à l'ordre ``1 − alpha/2`` (premier et dernier de
    ``BAND_QUANTILE_ORDERS``)."""
    (low_a, low_b), *_, (high_a, high_b) = BAND_QUANTILE_ORDERS
    assert BAND_PENALTY == 2 / BAND_ALPHA
    assert low_a / low_b == BAND_ALPHA / 2
    assert high_a / high_b == 1 - BAND_ALPHA / 2
