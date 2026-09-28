"""Runtime integration for the supported global two-bubble multi-region CFD path.

The authoritative state is a TransientSoapFilmSolver: tracked fronts and its
EulerianGasGrid are shared with the global field solve.  When the center-axis gap
is spatially resolved, direct-forcing immersed-interface constraints drive a 3D
pressure/velocity solve on that grid and numerical stress traction changes pair
motion.  Below the declared global-grid handoff, the already accepted resolved
local thin-gap discretization continues the same force balance to contact.
"""
from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
from typing import Any, Mapping

from bubblelab.solvers.contact_lubrication import GapGeometry, measure_axis_gap_geometry
from bubblelab.solvers.multiregion_cfd import (
    MultiregionCFDSettings,
    build_supported_two_bubble_solver,
    coupled_global_response,
)
from bubblelab.solvers.precontact_cfd import PrecontactCFDSettings, solve_thin_gap_field
from bubblelab.solvers.transient.geometry import FilmFront, Vec3


MODEL_ID = "bubblelab-global-3d-two-bubble-immersed-multiregion-cfd"
MODEL_VERSION = "0.1.0"


class MultiregionCFDConfigurationError(ValueError):
    pass


def _translate(front: FilmFront, delta: Vec3) -> None:
    front.vertices = [
        (x + delta[0], y + delta[1], z + delta[2])
        for x, y, z in front.vertices
    ]


def _fronts_by_geometry(
    fronts: list[FilmFront],
    geometry: GapGeometry,
) -> tuple[FilmFront, FilmFront]:
    by_id = {front.bubble_id: front for front in fronts}
    return by_id[geometry.parent_ids[0]], by_id[geometry.parent_ids[1]]


def _translate_pair_inward(
    fronts: list[FilmFront],
    geometry: GapGeometry,
    closure_m: float,
) -> None:
    if closure_m < 0.0:
        raise ValueError("pair closure must be non-negative")
    first, second = _fronts_by_geometry(fronts, geometry)
    n = geometry.normal_a_to_b
    half = 0.5 * closure_m
    _translate(first, (half * n[0], half * n[1], half * n[2]))
    _translate(second, (-half * n[0], -half * n[1], -half * n[2]))


def _volume_errors(fronts: list[FilmFront]) -> dict[str, float]:
    return {
        front.bubble_id: abs(front.volume() - float(front.target_volume_m3))
        / float(front.target_volume_m3)
        for front in fronts
    }


@dataclass(frozen=True)
class RuntimeSettings:
    free_closing_speed_m_s: float
    outer_resistance_n_s_m: float
    nominal_dt_s: float
    global_handoff_gap_cells: float
    contact_gap_m: float
    max_steps: int
    global_settings: MultiregionCFDSettings
    local_settings: PrecontactCFDSettings

    def validate(self) -> None:
        if self.free_closing_speed_m_s <= 0.0:
            raise MultiregionCFDConfigurationError(
                "free_closing_speed_m_s must be positive"
            )
        if self.outer_resistance_n_s_m <= 0.0:
            raise MultiregionCFDConfigurationError(
                "outer_resistance_n_s_m must be positive"
            )
        if self.nominal_dt_s <= 0.0:
            raise MultiregionCFDConfigurationError("nominal_dt_s must be positive")
        if self.global_handoff_gap_cells < self.global_settings.minimum_gap_cells:
            raise MultiregionCFDConfigurationError(
                "global handoff must not lie below the declared resolved support limit"
            )
        if self.contact_gap_m <= 0.0:
            raise MultiregionCFDConfigurationError("contact_gap_m must be positive")
        if self.max_steps < 2:
            raise MultiregionCFDConfigurationError("max_steps must be at least two")
        self.global_settings.validate()
        self.local_settings.validate()


def _settings_from_scenario(scenario: Mapping[str, Any]) -> RuntimeSettings:
    raw = scenario.get("coupling")
    if not isinstance(raw, Mapping):
        raise MultiregionCFDConfigurationError("scenario coupling object is required")
    global_raw = raw.get("global_field") or {}
    local_raw = raw.get("local_handoff") or {}
    settings = RuntimeSettings(
        free_closing_speed_m_s=float(raw.get("free_closing_speed_m_s", 0.06)),
        outer_resistance_n_s_m=float(raw.get("outer_resistance_n_s_m", 1.5e-6)),
        nominal_dt_s=float(raw.get("nominal_dt_s", 0.01)),
        global_handoff_gap_cells=float(raw.get("global_handoff_gap_cells", 1.75)),
        contact_gap_m=float(raw.get("contact_gap_m", 5.0e-5)),
        max_steps=int(raw.get("max_steps", 96)),
        global_settings=MultiregionCFDSettings(
            pseudo_steps=int(global_raw.get("pseudo_steps", 5)),
            viscous_cfl=float(global_raw.get("viscous_cfl", 0.08)),
            constraint_relaxation=float(global_raw.get("constraint_relaxation", 0.85)),
            minimum_gap_cells=float(global_raw.get("minimum_gap_cells", 1.25)),
            traction_offset_cells=float(global_raw.get("traction_offset_cells", 0.8)),
            gradient_step_cells=float(global_raw.get("gradient_step_cells", 0.5)),
            maximum_sphericity_error=float(
                global_raw.get("maximum_sphericity_error", 0.12)
            ),
            minimum_constraint_cells_per_front=int(
                global_raw.get("minimum_constraint_cells_per_front", 8)
            ),
        ),
        local_settings=PrecontactCFDSettings(
            enabled=True,
            minimum_gap_m=float(local_raw.get("minimum_gap_m", 1.0e-7)),
            onset_gap_over_effective_radius=float(
                local_raw.get("onset_gap_over_effective_radius", 10.0)
            ),
            outer_drag_scale=1.0,
            radial_cells=int(local_raw.get("radial_cells", 24)),
            gap_cells=int(local_raw.get("gap_cells", 8)),
            radial_extent_over_sqrt_2rh=float(
                local_raw.get("radial_extent_over_sqrt_2rh", 60.0)
            ),
            radial_stretch=float(local_raw.get("radial_stretch", 5.0)),
            volume_relative_tolerance=float(
                local_raw.get("volume_relative_tolerance", 5.0e-12)
            ),
        ),
    )
    settings.validate()
    return settings


def build_solver_from_scenario(
    scenario: Mapping[str, Any],
    *,
    cells_override: int | None = None,
):
    domain = scenario.get("domain")
    bubbles = scenario.get("bubbles")
    material = scenario.get("materials")
    if not isinstance(domain, Mapping):
        raise MultiregionCFDConfigurationError("scenario domain object is required")
    if not isinstance(bubbles, Mapping):
        raise MultiregionCFDConfigurationError("scenario bubbles object is required")
    if not isinstance(material, Mapping):
        raise MultiregionCFDConfigurationError("scenario materials object is required")
    exterior = material.get("exterior") or {}
    interior = material.get("interior") or {}
    return build_supported_two_bubble_solver(
        cells=int(cells_override or domain.get("cells", 14)),
        extent_m=float(domain.get("extent_m", 0.024)),
        radius_m=float(bubbles.get("radius_m", 0.003)),
        gap_m=float(bubbles.get("initial_gap_m", 0.0045)),
        subdivisions=int(bubbles.get("subdivisions", 1)),
        exterior_density_kg_m3=float(exterior.get("density_kg_m3", 1.204)),
        exterior_viscosity_pa_s=float(
            exterior.get("dynamic_viscosity_pa_s", 1.825e-5)
        ),
        interior_density_kg_m3=float(interior.get("density_kg_m3", 1.05)),
        interior_viscosity_pa_s=float(
            interior.get("dynamic_viscosity_pa_s", 1.65e-5)
        ),
        pressure_iterations=int(domain.get("pressure_iterations", 120)),
        pressure_tolerance_s_inv=float(
            domain.get("pressure_tolerance_s_inv", 2.0e-6)
        ),
    )


def _local_response(
    geometry: GapGeometry,
    free_speed_m_s: float,
    viscosity_pa_s: float,
    outer_resistance_n_s_m: float,
    settings: PrecontactCFDSettings,
) -> tuple[float, dict[str, Any]]:
    trial = solve_thin_gap_field(
        geometry,
        free_speed_m_s,
        viscosity_pa_s,
        settings,
    )
    resistance = (
        trial.pressure_force_n / free_speed_m_s
        if free_speed_m_s > 1.0e-15
        else 0.0
    )
    coupled = free_speed_m_s * outer_resistance_n_s_m / (
        outer_resistance_n_s_m + max(resistance, 0.0)
    )
    production = solve_thin_gap_field(
        geometry,
        coupled,
        viscosity_pa_s,
        settings,
    )
    return coupled, {
        "model": "LOCAL_DISCRETIZED_INCOMPRESSIBLE_THIN_GAP_CFD_HANDOFF",
        "resolved_cfd_resistance_n_s_m": float(max(resistance, 0.0)),
        "trial_pressure_force_n": float(trial.pressure_force_n),
        "production_pressure_force_n": float(production.pressure_force_n),
        "production_center_pressure_pa": float(production.center_pressure_pa),
        "mass_balance_relative_residual": float(
            production.mass_balance_relative_residual
        ),
        "max_pressure_equation_residual_m3_s": float(
            production.max_pressure_equation_residual_m3_s
        ),
        "max_wall_slip_m_s": float(production.max_wall_slip_m_s),
        "radial_cells": len(production.radial_centers_m),
        "gap_cells": len(production.radial_velocity_faces_m_s[0]) - 1,
    }


def _model_disclosure(settings: RuntimeSettings, solver: Any) -> dict[str, Any]:
    return {
        "identity": MODEL_ID,
        "version": MODEL_VERSION,
        "status": "SUPPORTED_CLASS_RESOLVED",
        "authoritative_state": (
            "TransientSoapFilmSolver tracked fronts + the same EulerianGasGrid "
            "velocity/pressure/material fields used by the base transient path"
        ),
        "global_formulation": (
            "3D regularized direct-forcing immersed tracked interfaces; explicit "
            "viscous relaxation; variable-density incompressible projection; "
            "pressure plus viscous stress integrated on triangulated fronts"
        ),
        "global_resolution": {
            "cells": list(solver.grid.config.cells),
            "cell_size_m": float(solver.grid.h),
            "handoff_gap_cells": float(settings.global_handoff_gap_cells),
        },
        "production_traction_source": (
            "numerically solved Eulerian pressure and viscous velocity-gradient stress"
        ),
        "subgrid_handoff": (
            "accepted discretized local no-slip thin-gap pressure/velocity solve; "
            "same explicit outer mobility, no Taylor/Reynolds production force"
        ),
        "supported_class": [
            "exactly two separated closed quasi-spherical tracked fronts",
            "single center-axis pre-contact gap",
            "incompressible low-Mach Newtonian regions on periodic base Eulerian grid",
            "resolved global gap followed by explicit local discretized thin-gap handoff",
        ],
        "not_claimed": [
            "arbitrary simultaneous multi-gap or many-bubble coupling",
            "general T1 CFD or topology change inside the global field solver",
            "turbulence, compressibility, thermal or rarefied-gas physics",
            "cut-cell exact sharp moving-interface Navier-Stokes",
            "universal full-domain multiphase CFD",
        ],
    }


def run_multiregion_precontact_cfd(
    scenario: Mapping[str, Any],
    *,
    global_enabled: bool | None = None,
) -> dict[str, Any]:
    settings = _settings_from_scenario(scenario)
    solver = build_solver_from_scenario(scenario)
    environment = scenario.get("materials", {}).get("exterior", {})
    viscosity = float(environment.get("dynamic_viscosity_pa_s", 1.825e-5))
    enabled = bool(
        scenario.get("coupling", {}).get("global_enabled", True)
        if global_enabled is None
        else global_enabled
    )
    frames: list[dict[str, Any]] = []
    global_activations = 0
    local_activations = 0
    max_mass_residual = 0.0
    max_pair_force_imbalance = 0.0
    max_constraint_mismatch = 0.0
    max_volume_error = 0.0
    last_global: dict[str, Any] | None = None
    handoff_time_s: float | None = None
    contact_time_s: float | None = None

    for _ in range(settings.max_steps):
        geometry = measure_axis_gap_geometry(solver.fronts[0], solver.fronts[1])
        gap = float(geometry.gap_m)
        if gap <= settings.contact_gap_m * (1.0 + 1.0e-12):
            contact_time_s = float(solver.time_s)
            break
        handoff_gap = settings.global_handoff_gap_cells * solver.grid.h
        in_global_range = gap > handoff_gap * (1.0 + 1.0e-12)
        phase: str
        diagnostics: dict[str, Any]

        if in_global_range and enabled:
            response = coupled_global_response(
                solver,
                settings.free_closing_speed_m_s,
                settings.outer_resistance_n_s_m,
                settings.global_settings,
            )
            coupled_speed = response.coupled_closing_speed_m_s
            diagnostics = response.as_dict()
            field = response.production_field
            max_mass_residual = max(
                max_mass_residual,
                field.mass_balance_relative_residual,
            )
            max_pair_force_imbalance = max(
                max_pair_force_imbalance,
                field.pair_force_relative_imbalance,
            )
            max_constraint_mismatch = max(
                max_constraint_mismatch,
                field.constraint_traction_relative_mismatch,
            )
            last_global = field.as_dict()
            global_activations += 1
            phase = "GLOBAL_MULTI_REGION_CFD"
        elif in_global_range:
            coupled_speed = settings.free_closing_speed_m_s
            diagnostics = {
                "model": "CONTROL_FREE_APPROACH_WITH_GLOBAL_CFD_DISABLED",
                "free_closing_speed_m_s": settings.free_closing_speed_m_s,
                "coupled_closing_speed_m_s": coupled_speed,
            }
            phase = "GLOBAL_RANGE_CONTROL"
        else:
            if handoff_time_s is None:
                handoff_time_s = float(solver.time_s)
            coupled_speed, diagnostics = _local_response(
                geometry,
                settings.free_closing_speed_m_s,
                viscosity,
                settings.outer_resistance_n_s_m,
                settings.local_settings,
            )
            max_mass_residual = max(
                max_mass_residual,
                float(diagnostics["mass_balance_relative_residual"]),
            )
            local_activations += 1
            phase = "LOCAL_RESOLVED_THIN_GAP_HANDOFF"

        if coupled_speed <= 0.0:
            raise RuntimeError("coupled pre-contact speed stalled at zero")
        dt = settings.nominal_dt_s
        if in_global_range:
            to_handoff = max(0.0, gap - handoff_gap)
            if to_handoff > 0.0:
                dt = min(dt, to_handoff / coupled_speed)
        else:
            to_contact = max(0.0, gap - settings.contact_gap_m)
            if to_contact > 0.0:
                dt = min(dt, to_contact / coupled_speed)
        if dt <= 1.0e-15:
            dt = min(
                settings.nominal_dt_s,
                max(gap - settings.contact_gap_m, 0.0) / coupled_speed,
            )
        if dt <= 1.0e-15:
            contact_time_s = float(solver.time_s)
            break

        closure = min(
            coupled_speed * dt,
            max(0.0, gap - settings.contact_gap_m),
        )
        before_centers = {
            front.bubble_id: front.centroid() for front in solver.fronts
        }
        _translate_pair_inward(solver.fronts, geometry, closure)
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
        after_geometry = measure_axis_gap_geometry(
            solver.fronts[0], solver.fronts[1]
        )
        volume_errors = _volume_errors(solver.fronts)
        max_volume_error = max(
            max_volume_error,
            max(volume_errors.values(), default=0.0),
        )
        frames.append(
            {
                "step_index": int(solver.step_index),
                "time_s": float(solver.time_s),
                "phase": phase,
                "gap_before_m": gap,
                "gap_after_m": float(after_geometry.gap_m),
                "step_dt_s": float(dt),
                "free_closing_speed_m_s": float(
                    settings.free_closing_speed_m_s
                ),
                "coupled_closing_speed_m_s": float(coupled_speed),
                "global_grid_shared_state": bool(phase == "GLOBAL_MULTI_REGION_CFD"),
                "diagnostics": diagnostics,
                "conservation": {
                    "closed_bubble_volume_relative_error": {
                        key: float(value)
                        for key, value in sorted(volume_errors.items())
                    },
                    "max_closed_bubble_volume_relative_error": float(
                        max(volume_errors.values(), default=0.0)
                    ),
                },
            }
        )
        if after_geometry.gap_m <= settings.contact_gap_m * (1.0 + 1.0e-10):
            contact_time_s = float(solver.time_s)
            break

    if contact_time_s is None:
        raise RuntimeError(
            f"supported transition did not reach contact within {settings.max_steps} steps"
        )
    final_geometry = measure_axis_gap_geometry(solver.fronts[0], solver.fronts[1])
    summary = {
        "model": _model_disclosure(settings, solver),
        "global_enabled": enabled,
        "global_activation_count": int(global_activations),
        "local_handoff_activation_count": int(local_activations),
        "handoff_time_s": None if handoff_time_s is None else float(handoff_time_s),
        "contact_time_s": float(contact_time_s),
        "final_gap_m": float(final_geometry.gap_m),
        "contact_gap_m": float(settings.contact_gap_m),
        "max_mass_balance_relative_residual": float(max_mass_residual),
        "max_pair_force_relative_imbalance": float(max_pair_force_imbalance),
        "max_constraint_traction_relative_mismatch": float(max_constraint_mismatch),
        "max_closed_bubble_volume_relative_error": float(max_volume_error),
        "last_global_field": last_global,
    }
    return {
        "manifest": {
            "model_id": MODEL_ID,
            "model_version": MODEL_VERSION,
            "feature_disclosures": {
                "global_two_bubble_multiregion_cfd": (
                    "MODELED" if enabled else "CONTROL_DISABLED"
                ),
                "general_simultaneous_multigap_cfd": "NOT_IMPLEMENTED",
                "general_t1_cfd": "NOT_IMPLEMENTED",
                "compressible_thermal_rarefied_cfd": "NOT_IMPLEMENTED",
            },
        },
        "frames": frames,
        "summary": summary,
    }


def load_scenario(path: str | Path) -> dict[str, Any]:
    return json.loads(Path(path).read_text())


def replay_signature(result: Mapping[str, Any]) -> str:
    return json.dumps(result, sort_keys=True, separators=(",", ":"))
