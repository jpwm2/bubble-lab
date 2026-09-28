#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from bubblelab.solvers.contact_lubrication import (
    measure_axis_gap_geometry,
    reynolds_sphere_pressure_pa,
    taylor_lubrication_force_n,
)
from bubblelab.solvers.transient.geometry import icosphere


def squeeze_benchmark() -> dict[str, object]:
    radius = 4.0e-3
    gap = 1.5e-4
    speed = 0.08
    viscosity = 1.825e-5
    analytic = taylor_lubrication_force_n(radius, gap, speed, viscosity)

    characteristic = math.sqrt(2.0 * radius * gap)
    r_max = 100.0 * characteristic
    intervals = 40000
    dr = r_max / intervals
    numerical = 0.0
    for index in range(intervals):
        r = (index + 0.5) * dr
        pressure = reynolds_sphere_pressure_pa(
            radius,
            gap,
            speed,
            viscosity,
            radial_position_m=r,
        )
        numerical += pressure * 2.0 * math.pi * r * dr
    relative_error = abs(numerical - analytic) / analytic
    return {
        "benchmark": "axisymmetric Reynolds squeeze-film pressure integral",
        "radius_m": radius,
        "gap_m": gap,
        "closing_speed_m_s": speed,
        "dynamic_viscosity_pa_s": viscosity,
        "analytic_taylor_force_n": analytic,
        "numerical_pressure_integral_force_n": numerical,
        "integration_radius_over_characteristic": 100.0,
        "relative_error": relative_error,
        "acceptance_relative_error": 2.0e-4,
        "valid": relative_error <= 2.0e-4,
    }


def refinement_benchmark() -> dict[str, object]:
    radius = 0.01
    continuum_gap = 0.0015
    speed = 0.05
    viscosity = 1.825e-5
    center = radius + 0.5 * continuum_gap
    exact_effective_radius = 0.5 * radius
    exact_force = taylor_lubrication_force_n(
        exact_effective_radius,
        continuum_gap,
        speed,
        viscosity,
    )
    rows: list[dict[str, float | int]] = []
    for subdivisions in (0, 1, 2, 3):
        first = icosphere(
            radius_m=radius,
            center_m=(0.0, 0.0, -center),
            subdivisions=subdivisions,
            bubble_id="bubble-a",
            surface_tension_n_m=0.05,
        )
        second = icosphere(
            radius_m=radius,
            center_m=(0.0, 0.0, center),
            subdivisions=subdivisions,
            bubble_id="bubble-b",
            surface_tension_n_m=0.05,
        )
        geometry = measure_axis_gap_geometry(first, second)
        measured_force = taylor_lubrication_force_n(
            geometry.effective_radius_m,
            geometry.gap_m,
            speed,
            viscosity,
        )
        rows.append({
            "subdivisions": subdivisions,
            "mesh_resolution_m": geometry.mesh_resolution_m,
            "measured_gap_m": geometry.gap_m,
            "gap_relative_error": abs(geometry.gap_m - continuum_gap) / continuum_gap,
            "effective_radius_m": geometry.effective_radius_m,
            "effective_radius_relative_error": abs(
                geometry.effective_radius_m - exact_effective_radius
            ) / exact_effective_radius,
            "force_n": measured_force,
            "force_relative_error": abs(measured_force - exact_force) / exact_force,
        })

    first = rows[0]
    finest = rows[-1]
    improving_gap = float(finest["gap_relative_error"]) < float(first["gap_relative_error"])
    improving_force = float(finest["force_relative_error"]) < float(first["force_relative_error"])
    finest_reasonable = float(finest["force_relative_error"]) < 0.20
    return {
        "benchmark": "triangulated two-sphere local-gap refinement",
        "continuum_gap_m": continuum_gap,
        "continuum_effective_radius_m": exact_effective_radius,
        "continuum_taylor_force_n": exact_force,
        "levels": rows,
        "improving_gap": improving_gap,
        "improving_force": improving_force,
        "finest_force_relative_error_limit": 0.20,
        "valid": improving_gap and improving_force and finest_reasonable,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Run contact-lubrication benchmarks")
    parser.add_argument("benchmark", choices=("squeeze", "refinement"))
    parser.add_argument("--assert", dest="assert_valid", action="store_true")
    args = parser.parse_args()

    result = squeeze_benchmark() if args.benchmark == "squeeze" else refinement_benchmark()
    print(json.dumps(result, sort_keys=True, indent=2))
    if args.assert_valid and not bool(result["valid"]):
        raise SystemExit(2)


if __name__ == "__main__":
    main()
