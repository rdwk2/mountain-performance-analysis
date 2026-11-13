"""La base d'une spline cubique naturelle à nœuds donnés (AN3-1,
``docs/decisions/0021`` ; Hastie, Tibshirani et Friedman, *The Elements of Statistical
Learning*, éq. 5.4 et 5.5), sans la constante."""

from __future__ import annotations

import numpy

from mountain_perf.analyse.inference.base import FloatArray, InferenceError, as_vector


def natural_cubic_basis(x: object, knots: object) -> FloatArray:
    """La base (n × (K − 1)) : colonne 1, ``x`` ; colonnes ``k + 1``,
    ``d_k(x) − d_{K−1}(x)`` pour ``k = 1 … K − 2``, avec
    ``d_k(x) = [(x − ξ_k)₊³ − (x − ξ_K)₊³] / (ξ_K − ξ_k)``. Affine au-delà des nœuds
    extrêmes ; l'appelant ajoute la constante."""
    points = as_vector(x, "x")
    nodes = as_vector(knots, "knots", min_size=3)
    if not numpy.all(numpy.diff(nodes) > 0.0):
        raise InferenceError("knots : des nœuds strictement croissants sont attendus")
    last = nodes[-1]

    def d(k: int) -> FloatArray:
        """``d_k`` pour ``k`` 1-indexé."""
        node = nodes[k - 1]
        cubes = numpy.maximum(points - node, 0.0) ** 3
        tail = numpy.maximum(points - last, 0.0) ** 3
        return numpy.asarray((cubes - tail) / (last - node), dtype=numpy.float64)

    count = nodes.shape[0]
    columns = [points] + [d(k) - d(count - 1) for k in range(1, count - 1)]
    return numpy.column_stack(columns).astype(numpy.float64)
