"""Configurations de sensibilité, déclarées et non exécutées (``0010`` D13).

Chaque configuration sera une exécution complète du protocole (M4d) ; rien n'est
exécuté en M4a.
"""

from mountain_perf.schemas import CLOCKS, SensitivityConfiguration

SENSITIVITY_SCORE_STEPS_M = (100.0, 250.0, 500.0)
"""Pas de grille ``Δ`` de la sensibilité en écoulé (m, ``0010`` D13)."""

SENSITIVITY_LATERAL_TOLERANCES_M = (15.0, 30.0, 45.0)
"""Tolérances latérales ``ε`` de la sensibilité en écoulé (m, ``0010`` D13)."""

SENSITIVITY_CENTRAL_M = (250.0, 30.0)
"""``(Δ, ε)`` des configurations sous les dix horloges de mouvement (m, ``0010``
D13)."""

SENSITIVITY_CLUSTER_RADIUS_M = 15.0
"""``r_c``, fixe dans toutes les configurations (m, ``0010`` D13)."""

SENSITIVITY_CONFIGURATIONS: tuple[SensitivityConfiguration, ...] = (
    *(
        SensitivityConfiguration(
            step_m, tolerance_m, SENSITIVITY_CLUSTER_RADIUS_M, CLOCKS[0]
        )
        for step_m in SENSITIVITY_SCORE_STEPS_M
        for tolerance_m in SENSITIVITY_LATERAL_TOLERANCES_M
    ),
    *(
        SensitivityConfiguration(
            *SENSITIVITY_CENTRAL_M, SENSITIVITY_CLUSTER_RADIUS_M, clock
        )
        for clock in CLOCKS[1:]
    ),
)
"""Les dix-neuf configurations de ``0010`` D13, **dans cet ordre** : pour ``Δ`` puis
``ε``, les neuf en écoulé (``CLOCKS[0]``) ; puis ``(250, 30)`` sous les dix horloges
de mouvement ``CLOCKS[1:]``, dans leur ordre."""
