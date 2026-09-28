"""Deterministic runtime adapter for the bounded T1-through-global-CFD foundation."""
from __future__ import annotations

from dataclasses import replace
from typing import Any, Mapping

from bubblelab.solvers.multiregion_cfd import (
    MultiregionCFDSettings,
    T1GlobalCFDSettings,
    build_supported_four_region_t1_solver,
    run_t1_global_cfd_transition,
)
from bubblelab.solvers.transient.network.t1_hydrodynamics import (
    DirectT1Settings,
    build_direct_3d_t1_state,
    detect_direct_t1_eligibility,
)


class T1GlobalCFDConfigurationError(ValueError):
    """Raised when the bounded T1/global-CFD runtime scenario is invalid."""


class T1GlobalCFDRuntime:
    MODEL_ID = "bubblelab-global-four-region-t1-cfd"
    VERSION = "0.1.0"

    def __init__(
        self,
        *,
        cells: int,
        extent_m: float,
        support_radius_m: float,
        old_pair_gap_m: float,
        axis_cycle: int,
        direct_amplitude_m_inv: float,
        direct_y_saturation_m: float,
        settings: T1GlobalCFDSettings,
    ) -> None:
        self.cells = int(cells)
        self.extent_m = float(extent_m)
        self.support_radius_m = float(support_radius_m)
        self.old_pair_gap_m = float(old_pair_gap_m)
        self.axis_cycle = int(axis_cycle)
        self.direct_amplitude_m_inv = float(direct_amplitude_m_inv)
        self.direct_y_saturation_m = float(direct_y_saturation_m)
        self.settings = settings
        settings.validate()
        if self.cells < 8:
            raise T1GlobalCFDConfigurationError("T1 global CFD runtime requires at least eight cells per axis")
        if min(self.extent_m, self.support_radius_m, self.old_pair_gap_m) <= 0.0:
            raise T1GlobalCFDConfigurationError("T1 global CFD runtime geometry scales must be positive")

    @classmethod
    def from_scenario(cls, scenario: Mapping[str, Any]) -> "T1GlobalCFDRuntime":
        raw = scenario.get("t1_global_cfd")
        if not isinstance(raw, Mapping):
            raise T1GlobalCFDConfigurationError("scenario.t1_global_cfd must be an object")
        field_raw = raw.get("field") or {}
        direct_raw = raw.get("direct") or {}
        if not isinstance(field_raw, Mapping) or not isinstance(direct_raw, Mapping):
            raise T1GlobalCFDConfigurationError("T1 field/direct settings must be objects")
        field = MultiregionCFDSettings(
            pseudo_steps=int(field_raw.get("pseudo_steps", 10)),
            viscous_cfl=float(field_raw.get("viscous_cfl", 0.08)),
            constraint_relaxation=float(field_raw.get("constraint_relaxation", 0.82)),
            minimum_gap_cells=float(field_raw.get("minimum_gap_cells", 0.25)),
            traction_offset_cells=float(field_raw.get("traction_offset_cells", 0.80)),
            gradient_step_cells=float(field_raw.get("gradient_step_cells", 0.50)),
            maximum_sphericity_error=float(field_raw.get("maximum_sphericity_error", 0.12)),
            minimum_constraint_cells_per_front=int(
                field_raw.get("minimum_constraint_cells_per_front", 8)
            ),
        )
        direct = DirectT1Settings(
            plateau_border_core_radius_m=float(direct_raw.get("plateau_border_core_radius_m", 0.010)),
            mobility_m_per_n_s=float(direct_raw.get("mobility_m_per_n_s", 2.0e-2)),
            hydrodynamic_segments=int(direct_raw.get("hydrodynamic_segments", 24)),
            force_difference_fraction=float(direct_raw.get("force_difference_fraction", 2.0e-4)),
            minimum_driving_force_n=float(direct_raw.get("minimum_driving_force_n", 1.0e-7)),
            minimum_nonplanarity_m=float(direct_raw.get("minimum_nonplanarity_m", 2.0e-4)),
            minimum_tangent_spread=float(direct_raw.get("minimum_tangent_spread", 1.0e-5)),
            minimum_samples=int(direct_raw.get("minimum_samples", 3)),
            maximum_core_to_edge_ratio=float(direct_raw.get("maximum_core_to_edge_ratio", 0.50)),
            post_event_seed_factor=float(direct_raw.get("post_event_seed_factor", 1.25)),
            volume_relative_tolerance=float(direct_raw.get("volume_relative_tolerance", 1.0e-12)),
        )
        settings = T1GlobalCFDSettings(
            field=field,
            direct=direct,
            event_mobility_m_per_n_s=float(raw.get("event_mobility_m_per_n_s", 2.0e-2)),
            pre_event_closing_speed_m_s=float(raw.get("pre_event_closing_speed_m_s", 0.020)),
            pre_event_drift_speed_m_s=float(raw.get("pre_event_drift_speed_m_s", 0.015)),
            post_event_opening_speed_m_s=float(raw.get("post_event_opening_speed_m_s", 0.012)),
            minimum_net_driving_force_n=float(raw.get("minimum_net_driving_force_n", 1.0e-12)),
            maximum_aggregate_traction_mismatch=float(
                raw.get("maximum_aggregate_traction_mismatch", 0.20)
            ),
        )
        return cls(
            cells=int(raw.get("cells", 12)),
            extent_m=float(raw.get("extent_m", 0.014)),
            support_radius_m=float(raw.get("support_radius_m", 0.00120)),
            old_pair_gap_m=float(raw.get("old_pair_gap_m", 0.00035)),
            axis_cycle=int(raw.get("axis_cycle", 0)),
            direct_amplitude_m_inv=float(raw.get("direct_amplitude_m_inv", 0.8)),
            direct_y_saturation_m=float(raw.get("direct_y_saturation_m", 0.04)),
            settings=settings,
        )

    def run(self) -> dict[str, Any]:
        topology_state = build_direct_3d_t1_state(
            amplitude_m_inv=self.direct_amplitude_m_inv,
            y_saturation_m=self.direct_y_saturation_m,
        )
        eligibility = detect_direct_t1_eligibility(topology_state, self.settings.direct)
        if not eligibility.eligible or eligibility.neighborhood is None:
            raise T1GlobalCFDConfigurationError(
                f"scenario is outside supported direct-3D T1 class: {eligibility.reason}"
            )
        region_ids = tuple(region.id for region in topology_state.to_network().regions)
        solver = build_supported_four_region_t1_solver(
            region_ids=region_ids,
            old_pair=eligibility.neighborhood.old_adjacent_regions,
            cells=self.cells,
            extent_m=self.extent_m,
            radius_m=self.support_radius_m,
            old_pair_gap_m=self.old_pair_gap_m,
            axis_cycle=self.axis_cycle,
        )
        result = run_t1_global_cfd_transition(solver, topology_state, self.settings)
        payload = result.as_dict()
        return {
            "identity": self.MODEL_ID,
            "version": self.VERSION,
            "status": "SUPPORTED_CLASS_RESOLVED",
            "supported_class": result.supported_class,
            "authoritative_field": (
                "one Eulerian pressure/velocity field is advanced before and after the real "
                "T1 switch; shared immersed-support cells use partition-of-unity forcing"
            ),
            "event_source": (
                "resolved direct 3D capillary drive minus field-derived hydrodynamic traction"
            ),
            "frames": [
                {
                    "phase": "PRE_T1",
                    "time_s": float(topology_state.time_s),
                    "field": result.pre_field.as_dict(),
                    "adjacency": [list(pair) for pair in result.adjacency_before],
                },
                {
                    "phase": "T1_EVENT",
                    "time_s": float(result.topology_state_after.time_s),
                    "retired_film_ids": list(result.retired_film_ids),
                    "created_film_ids": list(result.created_film_ids),
                    "retired_junction_ids": list(result.retired_junction_ids),
                    "created_junction_ids": list(result.created_junction_ids),
                    "adjacency": [list(pair) for pair in result.adjacency_after],
                },
                {
                    "phase": "POST_T1",
                    "time_s": float(result.topology_state_after.time_s),
                    "field": result.post_field.as_dict(),
                    "adjacency": [list(pair) for pair in result.adjacency_after],
                },
            ],
            "transition": payload,
        }
