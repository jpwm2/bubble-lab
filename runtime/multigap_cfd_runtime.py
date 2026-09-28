"""Runtime integration for the bounded three-bubble/two-gap global CFD path.

All supported fronts share one TransientSoapFilmSolver and one EulerianGasGrid.
At each supported pre-contact step the three immersed constraints are solved
simultaneously; field-derived closed-control-volume traction changes every bubble's
axial velocity before geometry advances.  The runtime stops at the first declared
resolved-grid handoff guard rather than pretending the regularized global grid is
a contact/T1 solver.
"""
from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
from typing import Any, Mapping

from bubblelab.solvers.contact_lubrication import GapGeometry, measure_axis_gap_geometry
from bubblelab.solvers.multiregion_cfd import (
    MultigapCFDSettings,
    MultiregionCFDSettings,
    build_supported_three_bubble_solver,
    coupled_multigap_response,
)
from bubblelab.solvers.transient.geometry import FilmFront, Vec3


MODEL_ID = "bubblelab-global-3d-three-bubble-two-gap-multiregion-cfd"
MODEL_VERSION = "0.1.0"


class MultigapCFDConfigurationError(ValueError):
    pass


def _translate(front: FilmFront, delta: Vec3) -> None:
    front.vertices = [
        (x + delta[0], y + delta[1], z + delta[2])
        for x, y, z in front.vertices
    ]


def _ordered_fronts(fronts: list[FilmFront]) -> tuple[FilmFront, FilmFront, FilmFront]:
    ordered = tuple(sorted(fronts, key=lambda front: (front.centroid()[0], front.bubble_id)))
    if len(ordered) != 3:
        raise MultigapCFDConfigurationError("runtime requires exactly three tracked fronts")
    return ordered[0], ordered[1], ordered[2]


def _gaps(fronts: list[FilmFront]) -> tuple[GapGeometry, GapGeometry]:
    first, second, third = _ordered_fronts(fronts)
    return (
        measure_axis_gap_geometry(first, second),
        measure_axis_gap_geometry(second, third),
    )


def _volume_errors(fronts: list[FilmFront]) -> dict[str, float]:
    return {
        front.bubble_id: abs(front.volume() - float(front.target_volume_m3))
        / float(front.target_volume_m3)
        for front in fronts
    }


@dataclass(frozen=True)
class RuntimeSettings:
    free_velocities_world: tuple[tuple[str, Vec3], ...]
    outer_resistance_n_s_m: float
    nominal_dt_s: float
    handoff_gap_cells: float
    max_steps: int
    global_settings: MultigapCFDSettings

    def validate(self) -> None:
        if self.outer_resistance_n_s_m <= 0.0:
            raise MultigapCFDConfigurationError("outer_resistance_n_s_m must be positive")
        if self.nominal_dt_s <= 0.0:
            raise MultigapCFDConfigurationError("nominal_dt_s must be positive")
        if self.handoff_gap_cells <= self.global_settings.field.minimum_gap_cells:
            raise MultigapCFDConfigurationError(
                "handoff_gap_cells must remain above the declared field support limit"
            )
        if self.max_steps < 2:
            raise MultigapCFDConfigurationError("max_steps must be at least two")
        if len(self.free_velocities_world) != 3:
            raise MultigapCFDConfigurationError("exactly three free velocities are required")
        self.global_settings.validate()


def _settings_from_scenario(scenario: Mapping[str, Any]) -> RuntimeSettings:
    coupling = scenario.get("coupling")
    if not isinstance(coupling, Mapping):
        raise MultigapCFDConfigurationError("scenario coupling object is required")
    raw_velocities = coupling.get("free_velocities_world_m_s")
    if not isinstance(raw_velocities, Mapping):
        raise MultigapCFDConfigurationError("free_velocities_world_m_s object is required")
    field_raw = coupling.get("global_field") or {}
    velocities: list[tuple[str, Vec3]] = []
    for bubble_id in sorted(raw_velocities):
        raw = raw_velocities[bubble_id]
        if not isinstance(raw, (list, tuple)) or len(raw) != 3:
            raise MultigapCFDConfigurationError(
                f"velocity for {bubble_id!r} must be a three-component array"
            )
        velocities.append(
            (bubble_id, (float(raw[0]), float(raw[1]), float(raw[2])))
        )
    settings = RuntimeSettings(
        free_velocities_world=tuple(velocities),
        outer_resistance_n_s_m=float(coupling.get("outer_resistance_n_s_m", 8.0e-6)),
        nominal_dt_s=float(coupling.get("nominal_dt_s", 0.01)),
        handoff_gap_cells=float(coupling.get("handoff_gap_cells", 1.8)),
        max_steps=int(coupling.get("max_steps", 64)),
        global_settings=MultigapCFDSettings(
            field=MultiregionCFDSettings(
                pseudo_steps=int(field_raw.get("pseudo_steps", 8)),
                viscous_cfl=float(field_raw.get("viscous_cfl", 0.08)),
                constraint_relaxation=float(field_raw.get("constraint_relaxation", 0.85)),
                minimum_gap_cells=float(field_raw.get("minimum_gap_cells", 1.5)),
                traction_offset_cells=float(field_raw.get("traction_offset_cells", 0.8)),
                gradient_step_cells=float(field_raw.get("gradient_step_cells", 0.5)),
                maximum_sphericity_error=float(
                    field_raw.get("maximum_sphericity_error", 0.12)
                ),
                minimum_constraint_cells_per_front=int(
                    field_raw.get("minimum_constraint_cells_per_front", 8)
                ),
            ),
            feedback_iterations=int(field_raw.get("feedback_iterations", 3)),
            feedback_relaxation=float(field_raw.get("feedback_relaxation", 0.30)),
            maximum_axis_offset_over_radius=float(
                field_raw.get("maximum_axis_offset_over_radius", 0.08)
            ),
        ),
    )
    settings.validate()
    return settings


def build_solver_from_scenario(scenario: Mapping[str, Any]):
    domain = scenario.get("domain")
    bubbles = scenario.get("bubbles")
    material = scenario.get("materials")
    if not isinstance(domain, Mapping):
        raise MultigapCFDConfigurationError("scenario domain object is required")
    if not isinstance(bubbles, Mapping):
        raise MultigapCFDConfigurationError("scenario bubbles object is required")
    if not isinstance(material, Mapping):
        raise MultigapCFDConfigurationError("scenario materials object is required")
    exterior = material.get("exterior") or {}
    interior = material.get("interior") or {}
    return build_supported_three_bubble_solver(
        cells=int(domain.get("cells", 12)),
        extent_m=float(domain.get("extent_m", 0.030)),
        radius_m=float(bubbles.get("radius_m", 0.0022)),
        left_gap_m=float(bubbles.get("left_gap_m", 0.0064)),
        right_gap_m=float(bubbles.get("right_gap_m", 0.0060)),
        subdivisions=int(bubbles.get("subdivisions", 1)),
        exterior_density_kg_m3=float(exterior.get("density_kg_m3", 1.204)),
        exterior_viscosity_pa_s=float(
            exterior.get("dynamic_viscosity_pa_s", 1.825e-5)
        ),
        interior_density_kg_m3=float(interior.get("density_kg_m3", 1.05)),
        interior_viscosity_pa_s=float(
            interior.get("dynamic_viscosity_pa_s", 1.65e-5)
        ),
        pressure_iterations=int(domain.get("pressure_iterations", 100)),
        pressure_tolerance_s_inv=float(
            domain.get("pressure_tolerance_s_inv", 3.0e-6)
        ),
    )


def _model_disclosure(settings: RuntimeSettings, solver: Any) -> dict[str, Any]:
    return {
        "identity": MODEL_ID,
        "version": MODEL_VERSION,
        "status": "SUPPORTED_CLASS_RESOLVED",
        "authoritative_state": (
            "three tracked FilmFront objects plus the same EulerianGasGrid pressure, "
            "velocity, density and viscosity fields used by the transient solver"
        ),
        "global_formulation": (
            "one 3D regularized immersed direct-forcing field for all three fronts; "
            "one projection per pseudo-step; closed finite-volume pressure/viscous "
            "traction recovery per bubble"
        ),
        "production_feedback": (
            "field-derived front traction enters a simultaneous overdamped mobility "
            "iteration for all three axial bubble velocities"
        ),
        "grid": {
            "cells": list(solver.grid.config.cells),
            "cell_size_m": float(solver.grid.h),
            "handoff_gap_cells": float(settings.handoff_gap_cells),
        },
        "supported_class": [
            "exactly three separated quasi-spherical tracked fronts",
            "collinear chain with exactly two simultaneously active pre-contact gaps",
            "axial low-Mach incompressible Newtonian motion",
            "disjoint immersed forcing and closed traction control-volume supports",
        ],
        "not_claimed": [
            "pairwise force-curve superposition",
            "arbitrary bubble count or unrestricted contact graph",
            "overlapping immersed supports or contact/T1-through-CFD",
            "turbulence, compressibility, thermal or rarefied-gas physics",
            "universal full-domain multiphase Navier-Stokes",
        ],
    }


def run_multigap_cfd(
    scenario: Mapping[str, Any],
    *,
    global_enabled: bool | None = None,
) -> dict[str, Any]:
    settings = _settings_from_scenario(scenario)
    solver = build_solver_from_scenario(scenario)
    configured_enabled = bool(scenario.get("coupling", {}).get("global_enabled", True))
    enabled = configured_enabled if global_enabled is None else bool(global_enabled)
    free = dict(settings.free_velocities_world)
    if set(free) != {front.bubble_id for front in solver.fronts}:
        raise MultigapCFDConfigurationError(
            "free velocity ids must exactly match the three scenario bubble ids"
        )

    frames: list[dict[str, Any]] = []
    activation_count = 0
    max_mass_residual = 0.0
    max_constraint_mismatch = 0.0
    max_global_force_imbalance = 0.0
    max_volume_error = 0.0
    max_front_velocity_change_fraction = 0.0
    changed_front_ids: set[str] = set()
    handoff_time_s: float | None = None
    handoff_pair_ids: tuple[str, str] | None = None
    last_field: dict[str, Any] | None = None

    for _ in range(settings.max_steps):
        gaps = _gaps(solver.fronts)
        handoff_gap_m = settings.handoff_gap_cells * solver.grid.h
        smallest = min(gaps, key=lambda gap: gap.gap_m)
        if smallest.gap_m <= handoff_gap_m * (1.0 + 1.0e-12):
            handoff_time_s = float(solver.time_s)
            handoff_pair_ids = smallest.parent_ids
            break

        if enabled:
            response = coupled_multigap_response(
                solver,
                free,
                settings.outer_resistance_n_s_m,
                settings.global_settings,
            )
            velocities = dict(response.coupled_velocities_world)
            diagnostics = response.as_dict()
            field = response.production_field
            activation_count += 1
            max_mass_residual = max(
                max_mass_residual, field.mass_balance_relative_residual
            )
            max_constraint_mismatch = max(
                max_constraint_mismatch,
                field.max_constraint_traction_relative_mismatch,
            )
            max_global_force_imbalance = max(
                max_global_force_imbalance,
                field.global_force_relative_imbalance,
            )
            last_field = field.as_dict()
            phase = "GLOBAL_THREE_BUBBLE_TWO_GAP_CFD"
        else:
            velocities = dict(free)
            diagnostics = {
                "model": "CONTROL_FREE_MANY_BUBBLE_APPROACH_WITH_GLOBAL_CFD_DISABLED",
                "free_velocities_world_m_s": {
                    key: list(value) for key, value in sorted(free.items())
                },
                "coupled_velocities_world_m_s": {
                    key: list(value) for key, value in sorted(free.items())
                },
            }
            phase = "GLOBAL_RANGE_CONTROL"

        for bubble_id in sorted(free):
            change = abs(velocities[bubble_id][0] - free[bubble_id][0]) / max(
                abs(free[bubble_id][0]), 0.01
            )
            max_front_velocity_change_fraction = max(
                max_front_velocity_change_fraction, change
            )
            if change > 0.01:
                changed_front_ids.add(bubble_id)

        ordered = _ordered_fronts(solver.fronts)
        current_gaps = _gaps(solver.fronts)
        closing_speeds = (
            velocities[ordered[0].bubble_id][0] - velocities[ordered[1].bubble_id][0],
            velocities[ordered[1].bubble_id][0] - velocities[ordered[2].bubble_id][0],
        )
        dt = settings.nominal_dt_s
        for geometry, closing in zip(current_gaps, closing_speeds):
            if closing > 1.0e-15:
                remaining = max(0.0, geometry.gap_m - handoff_gap_m)
                if remaining > 0.0:
                    dt = min(dt, remaining / closing)
        if dt <= 1.0e-15:
            handoff_time_s = float(solver.time_s)
            handoff_pair_ids = min(current_gaps, key=lambda gap: gap.gap_m).parent_ids
            break

        before_centers = {front.bubble_id: front.centroid() for front in solver.fronts}
        for front in solver.fronts:
            velocity = velocities[front.bubble_id]
            _translate(front, (velocity[0] * dt, velocity[1] * dt, velocity[2] * dt))
        solver.time_s += dt
        solver.step_index += 1
        for front in solver.fronts:
            before = before_centers[front.bubble_id]
            after = front.centroid()
            solver._bubble_velocities[front.bubble_id] = (
                (after[0] - before[0]) / dt,
                (after[1] - before[1]) / dt,
                (after[2] - before[2]) / dt,
            )

        after_gaps = _gaps(solver.fronts)
        volume_errors = _volume_errors(solver.fronts)
        max_volume_error = max(
            max_volume_error, max(volume_errors.values(), default=0.0)
        )
        frames.append(
            {
                "step_index": int(solver.step_index),
                "time_s": float(solver.time_s),
                "phase": phase,
                "gap_before_m": [float(gap.gap_m) for gap in current_gaps],
                "gap_after_m": [float(gap.gap_m) for gap in after_gaps],
                "gap_parent_ids": [list(gap.parent_ids) for gap in current_gaps],
                "step_dt_s": float(dt),
                "free_velocities_world_m_s": {
                    key: list(value) for key, value in sorted(free.items())
                },
                "coupled_velocities_world_m_s": {
                    key: list(value) for key, value in sorted(velocities.items())
                },
                "simultaneously_active_gap_count": 2,
                "global_grid_shared_state": bool(enabled),
                "diagnostics": diagnostics,
                "conservation": {
                    "closed_bubble_volume_relative_error": {
                        key: float(value) for key, value in sorted(volume_errors.items())
                    },
                    "max_closed_bubble_volume_relative_error": float(
                        max(volume_errors.values(), default=0.0)
                    ),
                },
            }
        )
        smallest_after = min(after_gaps, key=lambda gap: gap.gap_m)
        if smallest_after.gap_m <= handoff_gap_m * (1.0 + 1.0e-10):
            handoff_time_s = float(solver.time_s)
            handoff_pair_ids = smallest_after.parent_ids
            break

    if handoff_time_s is None:
        raise RuntimeError(
            f"multigap supported path did not reach the resolved-grid handoff within {settings.max_steps} steps"
        )
    final_gaps = _gaps(solver.fronts)
    return {
        "manifest": {
            "model_id": MODEL_ID,
            "model_version": MODEL_VERSION,
            "feature_disclosures": {
                "global_three_bubble_two_gap_multiregion_cfd": (
                    "MODELED" if enabled else "CONTROL_DISABLED"
                ),
                "pairwise_force_superposition": "NOT_USED",
                "unrestricted_manybubble_topology": "NOT_IMPLEMENTED",
                "general_t1_through_cfd": "NOT_IMPLEMENTED",
                "compressible_thermal_rarefied_cfd": "NOT_IMPLEMENTED",
            },
        },
        "frames": frames,
        "summary": {
            "model": _model_disclosure(settings, solver),
            "global_enabled": enabled,
            "global_activation_count": int(activation_count),
            "resolved_handoff_time_s": float(handoff_time_s),
            "resolved_handoff_pair_ids": (
                None if handoff_pair_ids is None else list(handoff_pair_ids)
            ),
            "handoff_gap_m": float(settings.handoff_gap_cells * solver.grid.h),
            "final_gaps_m": [float(gap.gap_m) for gap in final_gaps],
            "changed_front_ids": sorted(changed_front_ids),
            "changed_front_count": len(changed_front_ids),
            "max_front_velocity_change_fraction": float(
                max_front_velocity_change_fraction
            ),
            "max_mass_balance_relative_residual": float(max_mass_residual),
            "max_constraint_traction_relative_mismatch": float(
                max_constraint_mismatch
            ),
            "max_global_force_relative_imbalance": float(
                max_global_force_imbalance
            ),
            "max_closed_bubble_volume_relative_error": float(max_volume_error),
            "last_global_field": last_field,
        },
    }


def load_scenario(path: str | Path) -> dict[str, Any]:
    return json.loads(Path(path).read_text())


def replay_signature(result: Mapping[str, Any]) -> str:
    return json.dumps(result, sort_keys=True, separators=(",", ":"))
