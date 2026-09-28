"""Acceptance benchmarks for the transient film-network foundation."""
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
import sys

REPO_ROOT = Path(__file__).resolve().parents[5]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from bubblelab.solvers.equilibrium.network import NetworkSolverSettings, solve_film_network, stationarity
from bubblelab.solvers.equilibrium.plateau import reference_plateau_network
from bubblelab.solvers.equilibrium.shared_geometry import reference_two_bubble_network
from bubblelab.solvers.transient.network.core import ConstantForcing, NetworkStepperSettings, TransientNetworkState, diagnostics, run_steps


def _max_volume_error(history) -> float:
    return max((error for diag in history for _, error in diag.relative_volume_errors), default=0.0)


def _max_position_delta(a: TransientNetworkState, b: TransientNetworkState) -> float:
    return max((math.sqrt(sum((x - y) ** 2 for x, y in zip(pa, pb))) for pa, pb in zip(a.positions, b.positions)), default=0.0)


def _shared_fixture():
    reference = reference_two_bubble_network(
        radius_a_m=8.0e-3,
        radius_b_m=8.0e-3,
        contact_radius_m=3.0e-3,
        sheet_tension_n_m=0.05,
        outer_rings=6,
        shared_rings=6,
        azimuth_segments=24,
    )
    solved = solve_film_network(reference, NetworkSolverSettings(
        max_iterations=120,
        relative_volume_tolerance=2.0e-9,
        normalized_force_tolerance=2.0e-2,
        junction_force_tolerance=1.0e-2,
        initial_step_fraction=0.05,
    ))
    return solved.network, solved


def _plateau_fixture():
    reference = reference_plateau_network(
        longitudinal_segments=12,
        junction_offset_m=(0.0, 0.0),
        twist_rad=0.0,
    )
    solved = solve_film_network(reference, NetworkSolverSettings(
        max_iterations=160,
        relative_volume_tolerance=2.0e-9,
        normalized_force_tolerance=2.5e-2,
        junction_force_tolerance=2.0e-2,
        initial_step_fraction=0.05,
    ))
    return solved.network, solved


def shared_film_hold(assertions: bool) -> dict[str, object]:
    network, solved = _shared_fixture()
    initial = TransientNetworkState.from_network(network)
    settings = NetworkStepperSettings(dt_s=2.0e-4, mobility_m_per_n_s=1.0e-2)
    final, history = run_steps(initial, 8, settings=settings)
    final_network = final.to_network()
    energies = [network.surface_energy_j(), *(diag.surface_energy_j for diag in history)]
    nonincreasing = all(right <= left + 2.0e-12 * max(abs(left), 1.0) for left, right in zip(energies, energies[1:]))
    shared = [patch for patch in final_network.patches if patch.id == "shared-ab"]
    topology_same = initial.topology_signature() == final.topology_signature()
    volume_error = _max_volume_error(history)
    pressures, _ = stationarity(final_network)
    pressure_gap = pressures["bubble-a"] - pressures["bubble-b"]
    result = {
        "benchmark": "shared-film-hold",
        "solver_converged": solved.converged,
        "topology_unchanged": topology_same,
        "shared_film_count": len(shared),
        "shared_film_adjacency": list(shared[0].adjacent) if shared else [],
        "max_relative_volume_error": volume_error,
        "energy_nonincreasing": nonincreasing,
        "pressure_gap_pa": pressure_gap,
        "steps": final.step_index,
    }
    if assertions:
        assert len(shared) == 1
        assert shared[0].adjacent == ("bubble-a", "bubble-b")
        assert topology_same
        assert volume_error <= 5.0e-8
        assert nonincreasing
        assert abs(pressure_gap) <= 5.0
        assert final.step_index == 8 and final.time_s > 0.0
    return result


def plateau_hold(assertions: bool) -> dict[str, object]:
    network, solved = _plateau_fixture()
    initial = TransientNetworkState.from_network(network)
    settings = NetworkStepperSettings(dt_s=1.0e-4, mobility_m_per_n_s=8.0e-3)
    before = diagnostics(initial)
    final, history = run_steps(initial, 6, settings=settings)
    after = diagnostics(final)
    final_network = final.to_network()
    junction = final_network.junctions[0]
    expected_shared = len(junction.vertex_indices_by_film[0])
    result = {
        "benchmark": "plateau-hold",
        "solver_converged": solved.converged,
        "junction_count": len(final_network.junctions),
        "incident_film_count": len(junction.incident_film_ids),
        "shared_junction_dofs": final.shared_dof_count(),
        "expected_shared_junction_dofs": expected_shared,
        "topology_unchanged": initial.topology_signature() == final.topology_signature(),
        "initial_junction_force_residual": before.max_junction_force_residual,
        "final_junction_force_residual": after.max_junction_force_residual,
        "max_relative_volume_error": _max_volume_error(history),
    }
    if assertions:
        assert len(final_network.junctions) == 1
        assert len(junction.incident_film_ids) == 3
        assert final.shared_dof_count() == expected_shared
        assert initial.topology_signature() == final.topology_signature()
        assert after.max_junction_force_residual <= 3.0e-2
        assert _max_volume_error(history) <= 5.0e-8
    return result


def forced_network(assertions: bool) -> dict[str, object]:
    network, _ = _shared_fixture()
    initial = TransientNetworkState.from_network(network)
    forcing = ConstantForcing(
        velocity_m_s=(0.0, 2.0e-4, 0.0),
        acceleration_m_s2=(0.0, -9.81e-3, 0.0),
        response_time_s=1.0e-2,
    )
    settings = NetworkStepperSettings(dt_s=5.0e-4, mobility_m_per_n_s=8.0e-3)
    final, history = run_steps(initial, 6, settings=settings, forcing=forcing)
    movement = _max_position_delta(initial, final)
    result = {
        "benchmark": "forced-network",
        "max_geometry_delta_m": movement,
        "topology_unchanged": initial.topology_signature() == final.topology_signature(),
        "max_relative_volume_error": _max_volume_error(history),
        "steps": final.step_index,
    }
    if assertions:
        assert movement > 1.0e-10
        assert initial.topology_signature() == final.topology_signature()
        assert _max_volume_error(history) <= 5.0e-8
    return result


def replay(assertions: bool) -> dict[str, object]:
    network, _ = _plateau_fixture()
    a0 = TransientNetworkState.from_network(network)
    b0 = TransientNetworkState.from_network(network)
    settings = NetworkStepperSettings(dt_s=1.0e-4, mobility_m_per_n_s=8.0e-3)
    forcing = ConstantForcing(velocity_m_s=(2.0e-5, -1.0e-5, 0.0))
    a, ah = run_steps(a0, 5, settings=settings, forcing=forcing)
    b, bh = run_steps(b0, 5, settings=settings, forcing=forcing)
    identical = (
        a.topology_signature() == b.topology_signature()
        and a.positions == b.positions
        and a.pressures_pa == b.pressures_pa
        and ah == bh
    )
    result = {"benchmark": "replay", "identical": identical, "dof_count": len(a.positions), "step_index": a.step_index}
    if assertions:
        assert identical
    return result


BENCHMARKS = {
    "shared-film-hold": shared_film_hold,
    "plateau-hold": plateau_hold,
    "forced-network": forced_network,
    "replay": replay,
}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("benchmark", choices=tuple(BENCHMARKS))
    parser.add_argument("--assert", dest="assertions", action="store_true")
    args = parser.parse_args()
    print(json.dumps(BENCHMARKS[args.benchmark](args.assertions), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
