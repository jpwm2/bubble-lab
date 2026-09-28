"""Runtime continuation adapter for direct 3D T1 hydrodynamics."""
from __future__ import annotations

from dataclasses import dataclass

from bubblelab.solvers.transient.network.core import (
    NetworkStepDiagnostics,
    NetworkStepperSettings,
    TransientNetworkState,
    advance,
)
from bubblelab.solvers.transient.network.t1_hydrodynamics import (
    DirectT1Settings,
    DirectT1TransactionResult,
    perform_direct_t1_transaction,
)


@dataclass(frozen=True)
class T1HydrodynamicsRuntimeResult:
    event: DirectT1TransactionResult
    continued: TransientNetworkState
    diagnostics: tuple[NetworkStepDiagnostics, ...]


def run_t1_hydrodynamics_runtime(
    state: TransientNetworkState,
    *,
    event_settings: DirectT1Settings | None = None,
    stepper_settings: NetworkStepperSettings | None = None,
    continuation_steps: int = 2,
) -> T1HydrodynamicsRuntimeResult:
    """Execute the direct-3D event then continue with the authoritative stepper."""
    if continuation_steps < 1:
        raise ValueError("runtime continuation requires at least one transient step")
    event = perform_direct_t1_transaction(state, event_settings)
    current = event.after
    history = []
    for _ in range(continuation_steps):
        current, diag = advance(current, settings=stepper_settings)
        history.append(diag)
    return T1HydrodynamicsRuntimeResult(event, current, tuple(history))
