"""Allure en fonction de la pente : interpolation entre tranches, prolongement au-delà.

Deux régimes, décidés dans ``docs/decisions/0009`` :

- **dans la plage du support**, l'allure ``p = 1/v`` est interpolée linéairement
  entre les deux centres de tranche encadrants. Pas la vitesse : le temps est la
  grandeur qui s'additionne, ``T = Σ Δd · p(g)``, et un intervalle de grille dont la
  pente est la moyenne de pentes plus fines a pour temps **exact** la moyenne
  pondérée de leurs allures ;
- **au-delà du dernier centre retenu de chaque côté**, la vitesse verticale est
  figée : ``v(g) = v(g_b) · |g_b| / |g|``, donc ``p(g) = |g| / C±`` avec
  ``C± = |v(g_b) · g_b|``. Le raccord est exact au bord par construction.

La décision ``0002`` interdit de **stocker** une vitesse sous forme d'allure et
d'interpoler une courbe ainsi stockée ; elle n'interdit pas ce choix de calcul.
``PaceCurve`` reste en m/s, et l'allure de ce module est en **secondes par mètre**,
cohérente avec ``T = Σ Δd · p``. ``units.pace_s_per_km`` n'a rien à faire ici : elle
est en secondes par kilomètre et reste un formateur d'affichage.
"""

from bisect import bisect_right

from mountain_perf.schemas import PaceCurve

MAX_SAFE_GRADE = 1000.0
"""Pente maximale (fraction) sur laquelle l'allure est garantie finie et ``> 0``.

Soit ±100 000 %, ce qui couvre très largement tout profil issu d'un GPX. Ce n'est
pas une affirmation en l'air : elle découle des règles du lecteur de courbe. Les
vitesses lues valent au moins ``0,01 km/h`` et les bords du support sont à au moins
1 % de pente, donc ``C± >= (0,01 / 3,6) × 0,01 = 1/36 000`` m/s exactement, soit
environ ``2,78e-5`` m/s, et l'allure la plus grande atteignable vaut
``1000 × 36 000 = 3,6e7`` s/m. Au-delà de ce domaine, le calcul peut déborder les
flottants : c'est une limite de représentation, pas un choix de modèle.
"""


class PaceModel:
    """Allure ``p(g)`` en secondes par mètre, lue sur une :class:`PaceCurve`.

    Immuable et sans état : aucun cache, aucune mémoire d'un appel à l'autre.

    **Précondition, garantie par le lecteur et non revérifiée ici** : la courbe
    encadre strictement le plat, ``grade[0] < 0 < grade[-1]``, donc les deux vitesses
    verticales de bord ``C±`` sont strictement positives. C'est exactement ce
    qu'assure la règle 1 de la sélection du support
    (:func:`mountain_perf.model.curve_io.read_curve`). Sans elle, un support
    entièrement d'un côté du plat donnerait ``C = 0`` — division par zéro — ou une
    allure nulle à plat, donc une vitesse infinie.
    """

    def __init__(self, curve: PaceCurve) -> None:
        self._grade = tuple(curve.grade)
        self._pace_s_per_m = tuple(1.0 / speed_ms for speed_ms in curve.speed_ms)
        # Vitesses verticales des deux bords : ce que le prolongement fige.
        self._low_vertical_ms = abs(curve.speed_ms[0] * curve.grade[0])
        self._high_vertical_ms = abs(curve.speed_ms[-1] * curve.grade[-1])

    @property
    def grade_range(self) -> tuple[float, float]:
        """Plage de pentes du support, en fraction : au-delà, on prolonge."""
        return (self._grade[0], self._grade[-1])

    def is_extrapolated(self, grade: float) -> bool:
        """La pente demandée est-elle hors du support ? Les bords en font partie."""
        return grade < self._grade[0] or grade > self._grade[-1]

    def pace_s_per_m(self, grade: float) -> float:
        """Allure (s/m) à cette pente : finie et ``> 0`` pour ``|g| <= 1000``.

        Exacte aux centres de tranche. Hors du support, ``|g| / C±`` redonne
        exactement l'allure du bord en ``g = g_b`` : le raccord est continu sans
        qu'on ait à le forcer.
        """
        if grade < self._grade[0]:
            return abs(grade) / self._low_vertical_ms
        if grade > self._grade[-1]:
            return abs(grade) / self._high_vertical_ms
        i = min(max(bisect_right(self._grade, grade) - 1, 0), len(self._grade) - 2)
        low, high = self._grade[i], self._grade[i + 1]
        # Retour exact aux nœuds : deux pentes égales doivent donner le même bit.
        if grade == low:
            return self._pace_s_per_m[i]
        if grade == high:
            return self._pace_s_per_m[i + 1]
        ratio = (grade - low) / (high - low)
        return (1.0 - ratio) * self._pace_s_per_m[i] + ratio * self._pace_s_per_m[i + 1]

    def speed_ms(self, grade: float) -> float:
        """Vitesse horizontale (m/s) à cette pente, inverse de l'allure."""
        return 1.0 / self.pace_s_per_m(grade)
