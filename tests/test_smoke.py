"""Test de fumée : le paquet s'importe et la chaîne d'outils fonctionne."""

import mountain_perf


def test_package_exposes_a_version() -> None:
    assert isinstance(mountain_perf.__version__, str)
    assert mountain_perf.__version__ != ""
