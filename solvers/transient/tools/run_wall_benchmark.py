"""Canonical resolved-wall CFD verification cases for the transient grid."""
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[4]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from bubblelab.solvers.boundary import PlaneBoundary
from bubblelab.solvers.transient.grid import EulerianGasGrid, GridConfig


def _channel_grid(
    interior_cells: int,
    *,
    top_wall_velocity_m_s: float = 0.0,
    kinematic_viscosity_m2_s: float = 0.1,
) -> EulerianGasGrid:
    h = 1.0 / interior_cells
    grid = EulerianGasGrid(
        GridConfig(
            cells=(4, interior_cells + 2, 4),
            origin_m=(-2.0 * h, -h, -2.0 * h),
            extent_m=(4.0 * h, (interior_cells + 2) * h, 4.0 * h),
            density_kg_m3=1.0,
            dynamic_viscosity_pa_s=kinematic_viscosity_m2_s,
            pressure_iterations=500,
            pressure_tolerance_s_inv=1.0e-10,
        )
    )
    grid.configure_solid_walls(
        (
            PlaneBoundary(
                boundary_id="bottom",
                point_m=(0.0, 0.0, 0.0),
                normal_outward=(0.0, 1.0, 0.0),
            ),
            PlaneBoundary(
                boundary_id="top",
                wall_velocity_m_s=(top_wall_velocity_m_s, 0.0, 0.0),
                point_m=(0.0, 1.0, 0.0),
                normal_outward=(0.0, -1.0, 0.0),
            ),
        )
    )
    return grid


def _fill_u_profile(grid: EulerianGasGrid, profile) -> None:
    wall = grid.resolved_walls
    assert wall is not None
    for q in wall.fluid_indices:
        y = grid.cell_center(*grid._ijk(q))[1]
        grid.u[q] = profile(y)
    grid.apply_solid_wall_constraints()


def _profile_l2_error(grid: EulerianGasGrid, profile) -> float:
    wall = grid.resolved_walls
    assert wall is not None
    errors = []
    for q in wall.fluid_indices:
        y = grid.cell_center(*grid._ijk(q))[1]
        errors.append((grid.u[q] - profile(y)) ** 2)
    return math.sqrt(sum(errors) / len(errors))


def _y_wall_slip_error(grid: EulerianGasGrid) -> float:
    """Reconstruct tangential wall velocity; normal face velocity is direct."""
    wall = grid.resolved_walls
    assert wall is not None
    errors: list[float] = []
    for k in range(grid.nz):
        for i in range(grid.nx):
            fluid = [
                grid._idx(i, j, k)
                for j in range(grid.ny)
                if not wall.is_solid(grid._idx(i, j, k))
            ]
            if len(fluid) < 2:
                continue
            for component, field, bottom_target, top_target in (
                (0, grid.u, 0.0, wall.boundaries[1].wall_velocity_m_s[0]),
                (2, grid.w, 0.0, wall.boundaries[1].wall_velocity_m_s[2]),
            ):
                background = grid.config.background_velocity_m_s[component]
                first = field[fluid[0]] + background
                second = field[fluid[1]] + background
                last = field[fluid[-1]] + background
                penultimate = field[fluid[-2]] + background
                errors.append(abs((1.5 * first - 0.5 * second) - bottom_target))
                errors.append(abs((1.5 * last - 0.5 * penultimate) - top_target))

            bottom_face = grid._face_neighbor(fluid[0], 1, -1)
            errors.append(abs(grid.v[bottom_face] + grid.config.background_velocity_m_s[1]))
            errors.append(abs(grid.v[fluid[-1]] + grid.config.background_velocity_m_s[1]))
    return max(errors, default=0.0)


def stationary() -> dict[str, object]:
    grid = _channel_grid(16)
    wall = grid.resolved_walls
    assert wall is not None
    for q in wall.fluid_indices:
        y = grid.cell_center(*grid._ijk(q))[1]
        shape = y * (1.0 - y)
        grid.u[q] = shape
        grid.w[q] = -0.25 * shape
    grid.apply_solid_wall_constraints()
    slip = _y_wall_slip_error(grid)
    tangential_response = grid._variable_viscous_term(grid.u, 0)
    near_wall = [
        abs(tangential_response[q])
        for q in wall.fluid_indices
        if grid.cell_center(*grid._ijk(q))[1] < 1.5 * grid.h
        or grid.cell_center(*grid._ijk(q))[1] > 1.0 - 1.5 * grid.h
    ]
    return {
        "case": "stationary",
        "cells_across_channel": 16,
        "wall_slip_error_m_s": slip,
        "near_wall_viscous_response_max_m_s2": max(near_wall, default=0.0),
        "solid_cell_count": wall.solid_cell_count,
        "pass": slip < 5.0e-3 and max(near_wall, default=0.0) > 0.0,
    }


def couette() -> dict[str, object]:
    grid = _channel_grid(16, top_wall_velocity_m_s=1.0)
    analytic = lambda y: y
    _fill_u_profile(grid, analytic)
    dt = 0.05 * grid.h * grid.h / grid.config.dynamic_viscosity_pa_s
    zero = [0.0] * len(grid.u)
    for _ in range(5):
        grid.advance(dt, (zero, zero, zero), (0.0, 0.0, 0.0))
    profile_error = _profile_l2_error(grid, analytic)
    slip = _y_wall_slip_error(grid)
    return {
        "case": "couette",
        "cells_across_channel": 16,
        "profile_l2_error_m_s": profile_error,
        "wall_slip_error_m_s": slip,
        "divergence_linf_s_inv": grid.divergence_linf(),
        "pass": profile_error < 1.0e-10 and slip < 1.0e-10 and grid.divergence_linf() < 1.0e-8,
    }


def poiseuille() -> dict[str, object]:
    nu = 0.1
    acceleration = 0.25
    grid = _channel_grid(16, kinematic_viscosity_m2_s=nu)
    analytic = lambda y: acceleration * y * (1.0 - y) / (2.0 * nu)
    _fill_u_profile(grid, analytic)
    dt = 0.05 * grid.h * grid.h / nu
    zero = [0.0] * len(grid.u)
    for _ in range(5):
        grid.advance(dt, (zero, zero, zero), (acceleration, 0.0, 0.0))
    profile_error = _profile_l2_error(grid, analytic)
    slip = _y_wall_slip_error(grid)
    return {
        "case": "poiseuille",
        "cells_across_channel": 16,
        "profile_l2_error_m_s": profile_error,
        "wall_slip_error_m_s": slip,
        "divergence_linf_s_inv": grid.divergence_linf(),
        "pass": profile_error < 1.0e-10 and slip < 5.0e-3 and grid.divergence_linf() < 1.0e-8,
    }


def refinement() -> dict[str, object]:
    nu = 0.1
    errors: list[float] = []
    ladder = (8, 16, 32)
    for cells in ladder:
        grid = _channel_grid(cells, kinematic_viscosity_m2_s=nu)
        analytic = lambda y: math.sin(math.pi * y)
        _fill_u_profile(grid, analytic)
        discrete = grid._variable_viscous_term(grid.u, 0)
        wall = grid.resolved_walls
        assert wall is not None
        squared = []
        for q in wall.fluid_indices:
            y = grid.cell_center(*grid._ijk(q))[1]
            exact = -nu * math.pi * math.pi * analytic(y)
            squared.append((discrete[q] - exact) ** 2)
        errors.append(math.sqrt(sum(squared) / len(squared)))
    orders = [math.log(errors[i] / errors[i + 1], 2.0) for i in range(len(errors) - 1)]
    return {
        "case": "refinement",
        "cells_across_channel": list(ladder),
        "viscous_operator_l2_error_m_s2": errors,
        "observed_orders": orders,
        "pass": all(errors[i + 1] < errors[i] for i in range(len(errors) - 1)) and min(orders) > 1.3,
    }


CASES = {
    "stationary": stationary,
    "couette": couette,
    "poiseuille": poiseuille,
    "refinement": refinement,
}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("case", choices=sorted(CASES))
    parser.add_argument("--assert", dest="assert_pass", action="store_true")
    args = parser.parse_args()
    report = CASES[args.case]()
    print(json.dumps(report, sort_keys=True))
    if args.assert_pass and not report["pass"]:
        raise SystemExit(f"wall benchmark failed: {args.case}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
