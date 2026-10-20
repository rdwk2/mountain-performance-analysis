"""Les contrôles de l'interface, générés depuis les specs des paramètres (M5).

L'interface ne connaît aucun paramètre par son nom : elle parcourt un tuple de specs et
en fait un contrôle par spec. Une plage d'affichage déclarée (``ParameterDisplay``) en
fait un curseur ; sans elle, un champ numérique borné aux garde-fous de la spec. Un
effet ajouté au moteur avec sa spec apparaît donc dans l'interface.
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from mountain_perf.schemas import ParameterDisplay, ParameterSpec
from mountain_perf.validation import ContractError


@dataclass(frozen=True)
class ParameterControl:
    """Le contrôle d'un paramètre : sa spec, son libellé, ses bornes, son pas, son
    défaut, en flottants.

    Avec une plage d'affichage, le libellé, les bornes et le pas sont les siens (un
    curseur) ; sans elle, le libellé est ``nom (unité)`` (ou le nom seul, sans unité),
    les bornes sont les garde-fous de la spec, et le pas est absent (un champ
    numérique).
    """

    spec: ParameterSpec
    label: str
    low: float
    high: float
    step: float | None
    default: float

    @property
    def slider(self) -> bool:
        """Un curseur (une plage déclarée), ou un champ numérique."""
        return self.step is not None


def parameter_controls(
    specs: Sequence[ParameterSpec], displays: Sequence[ParameterDisplay]
) -> tuple[ParameterControl, ...]:
    """Un contrôle par spec, dans l'ordre des specs.

    ``ContractError``, dans cet ordre : une plage d'un paramètre absent de ``specs`` ;
    deux plages du même paramètre ; puis, spec par spec, une plage hors des garde-fous
    de la spec, un défaut hors de la plage.
    """
    names = {spec.name for spec in specs}
    for display in displays:
        if display.name not in names:
            raise ContractError(
                f"Plage d'affichage d'un paramètre inconnu : {display.name}."
            )
    by_name: dict[str, ParameterDisplay] = {}
    for display in displays:
        if display.name in by_name:
            raise ContractError(f"Deux plages d'affichage pour {display.name}.")
        by_name[display.name] = display
    controls: list[ParameterControl] = []
    for spec in specs:
        declared = by_name.get(spec.name)
        if declared is None:
            label = spec.name if spec.unit is None else f"{spec.name} ({spec.unit})"
            controls.append(
                ParameterControl(
                    spec=spec,
                    label=label,
                    low=float(spec.minimum),
                    high=float(spec.maximum),
                    step=None,
                    default=float(spec.default),
                )
            )
            continue
        if declared.low < spec.minimum or declared.high > spec.maximum:
            raise ContractError(
                f"{spec.name} : plage [{declared.low}, {declared.high}] hors des "
                f"garde-fous [{spec.minimum}, {spec.maximum}]."
            )
        if not declared.low <= spec.default <= declared.high:
            raise ContractError(
                f"{spec.name} : défaut {spec.default} hors de la plage "
                f"[{declared.low}, {declared.high}]."
            )
        controls.append(
            ParameterControl(
                spec=spec,
                label=declared.label,
                low=float(declared.low),
                high=float(declared.high),
                step=float(declared.step),
                default=float(spec.default),
            )
        )
    return tuple(controls)


def changed_values(
    controls: Sequence[ParameterControl], values: Mapping[str, float]
) -> dict[str, float]:
    """Les valeurs de ``values`` qui diffèrent du défaut de leur contrôle, et elles
    seules, dans l'ordre de ``values`` ; ``ContractError`` pour un nom inconnu.

    Un paramètre laissé à son défaut n'est pas transmis, comme une option absente de
    ``mperf`` : le jeu de valeurs prend alors le défaut de la spec tel quel. Un entier
    reste un entier : ``grid_step_m`` vaut ``50``, et ``50.0`` ferait écrire ``0.0`` au
    lieu de ``0`` dans le CSV. L'export de l'interface est ainsi, à l'octet, celui de la
    commande lancée avec les seules options qui s'écartent d'un défaut (donner un défaut
    à la commande, ``--step-m 50``, change son CSV).
    """
    defaults = {control.spec.name: control.default for control in controls}
    unknown = sorted(set(values) - set(defaults))
    if unknown:
        raise ContractError(f"Paramètres inconnus : {', '.join(unknown)}.")
    return {name: value for name, value in values.items() if value != defaults[name]}
