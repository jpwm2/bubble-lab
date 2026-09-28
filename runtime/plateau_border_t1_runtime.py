"""Runtime adapter for the dynamic Plateau-border driven T1 foundation."""
from __future__ import annotations

from dataclasses import dataclass

from bubblelab.solvers.plateau_border import (
    PlateauBorderSettings,
    PlateauBorderT1Result,
    evolve_and_switch,
)
from bubblelab.solvers.transient.network.core import (
    NetworkStepDiagnostics,
    NetworkStepperSettings,
    TransientNetworkState,
    advance,
)


@dataclass(frozen=True)
class PlateauBorderT1RuntimeResult:
    event: PlateauBorderT1Result
    continued: TransientNetworkState
    diagnostics: tuple[NetworkStepDiagnostics, ...]


def run_plateau_border_t1_runtime(
    state: TransientNetworkState,
    *,
    event_settings: PlateauBorderSettings | None = None,
    stepper_settings: NetworkStepperSettings | None = None,
    continuation_steps: int = 2,
) -> PlateauBorderT1RuntimeResult:
    """Evolve liquid-border physics, switch topology, then continue transiently."""
    if continuation_steps < 1:
        raise ValueError("runtime continuation requires at least one transient step")
    event = evolve_and_switch(state, event_settings)
    current = event.after
    history = []
    for _ in range(continuation_steps):
        current, diagnostics = advance(current, settings=stepper_settings)
        history.append(diagnostics)
    return PlateauBorderT1RuntimeResult(event, current, tuple(history))
