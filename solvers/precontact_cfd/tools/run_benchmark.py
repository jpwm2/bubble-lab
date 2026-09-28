#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from bubblelab.solvers.contact_lubrication import GapGeometry
from bubblelab.solvers.precontact_cfd import (
    PrecontactCFDSettings,
    coupled_cfd_response,
    solve_thin_gap_field,
    taylor_reference_force_n,
)


def _geometry(gap_m: float = 2.0e-4) -> GapGeometry:
    return GapGeometry(
        parent_ids=("bubble-a", "bubble-b"),
        anchor_vertex_indices=(0, 0),
        normal_a_to_b=(0.0, 0.0, 1.0),
        gap_m=gap_m,
        local_radius_a_m=1.0e-2,
        local_radius_b_m=1.0e-2,
        effective_radius_m=5.0e-3,
        local_curvature_a_1_m=200.0,
        local_curvature_b_1_m=200.0,
        mesh_resolution_m=5.0e-4,
        geometry_source="manufactured triangulated local geometry",
    )


def _squeeze() -> dict[str, object]:
    radius = 5.0e-3
    gap = 2.0e-4
    speed = 0.12
    viscosity = 1.825e-5
    settings = PrecontactCFDSettings(radial_cells=96, gap_cells=32)
    field = solve_thin_gap_field(_geometry(gap), speed, viscosity, settings)
    reference = taylor_reference_force_n(radius, gap, speed, viscosity)
    force_error = abs(field.pressure_force_n - reference) / reference
    valid = all((
        force_error < 0.003,
        field.mass_balance_relative_residual < 1.0e-11,
        field.max_pressure_equation_residual_m3_s < 2.0e-15,
        field.max_wall_slip_m_s == 0.0,
        field.max_radial_velocity_m_s > 0.0,
        field.max_wall_shear_pa > 0.0,
    ))
    return {
        "benchmark": "squeeze",
        "valid": valid,
        "production_force_n": field.pressure_force_n,
        "taylor_validation_reference_n": reference,
        "relative_force_error": force_error,
        "center_pressure_pa": field.center_pressure_pa,
        "mass_balance_relative_residual": field.mass_balance_relative_residual,
        "max_pressure_equation_residual_m3_s": field.max_pressure_equation_residual_m3_s,
        "max_wall_slip_m_s": field.max_wall_slip_m_s,
        "max_radial_velocity_m_s": field.max_radial_velocity_m_s,
        "max_wall_shear_pa": field.max_wall_shear_pa,
        "claim_boundary": (
            "local isolated two-front thin-gap patch; Taylor formula is validation-only"
        ),
    }


def _refinement() -> dict[str, object]:
    geometry = _geometry()
    speed = 0.12
    viscosity = 1.825e-5
    reference = taylor_reference_force_n(
        geometry.effective_radius_m,
        geometry.gap_m,
        speed,
        viscosity,
    )
    rows = []
    for radial_cells, gap_cells in ((12, 8), (24, 12), (48, 16), (96, 32)):
        field = solve_thin_gap_field(
            geometry,
            speed,
            viscosity,
            PrecontactCFDSettings(
                radial_cells=radial_cells,
                gap_cells=gap_cells,
            ),
        )
        error = abs(field.pressure_force_n - reference) / reference
        rows.append({
            "radial_cells": radial_cells,
            "gap_cells": gap_cells,
            "pressure_force_n": field.pressure_force_n,
            "relative_taylor_force_error": error,
            "mass_balance_relative_residual": field.mass_balance_relative_residual,
        })
    errors = [float(row["relative_taylor_force_error"]) for row in rows]
    valid = (
        all(later < earlier for earlier, later in zip(errors, errors[1:]))
        and errors[-1] < 0.003
        and all(
            float(row["mass_balance_relative_residual"]) < 1.0e-11
            for row in rows
        )
    )
    return {
        "benchmark": "refinement",
        "valid": valid,
        "reference_force_n": reference,
        "levels": rows,
        "error_reduction_factor": errors[0] / errors[-1],
    }


def _feedback() -> dict[str, object]:
    geometry = _geometry()
    free_speed = 0.18
    viscosity = 1.825e-5
    settings = PrecontactCFDSettings(
        onset_gap_over_effective_radius=1.0,
        radial_cells=64,
        gap_cells=24,
    )
    response = coupled_cfd_response(
        geometry, free_speed, viscosity, settings
    )
    reference_resistance = taylor_reference_force_n(
        geometry.effective_radius_m,
        geometry.gap_m,
        1.0,
        viscosity,
    )
    resistance_error = abs(
        response.cfd_resistance_n_s_m - reference_resistance
    ) / reference_resistance
    valid = all((
        response.active,
        response.field is not None,
        response.coupled_closing_speed_m_s < free_speed,
        response.correction_speed_m_s > 0.0,
        response.force_n > 0.0,
        resistance_error < 0.01,
    ))
    return {
        "benchmark": "feedback",
        "valid": valid,
        "free_closing_speed_m_s": free_speed,
        "coupled_closing_speed_m_s": response.coupled_closing_speed_m_s,
        "correction_speed_m_s": response.correction_speed_m_s,
        "numerical_cfd_resistance_n_s_m": response.cfd_resistance_n_s_m,
        "taylor_validation_reference_resistance_n_s_m": reference_resistance,
        "relative_resistance_error": resistance_error,
        "integrated_numerical_force_n": response.force_n,
        "field": None if response.field is None else response.field.compact_dict(),
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Validate the local resolved pre-contact thin-gap CFD foundation."
        )
    )
    parser.add_argument(
        "benchmark", choices=("squeeze", "refinement", "feedback")
    )
    parser.add_argument("--assert", dest="assert_valid", action="store_true")
    args = parser.parse_args()
    if args.benchmark == "squeeze":
        result = _squeeze()
    elif args.benchmark == "refinement":
        result = _refinement()
    else:
        result = _feedback()
    print(json.dumps(result, sort_keys=True))
    if args.assert_valid and not bool(result["valid"]):
        raise SystemExit(2)


if __name__ == "__main__":
    main()
