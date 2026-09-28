"""Runtime adapter for the bounded many-contact T1/global-CFD foundation."""
from __future__ import annotations

from typing import Any, Mapping

from bubblelab.solvers.multiregion_cfd import (
    ManyContactT1GlobalCFDSettings,
    MultiregionCFDSettings,
    StrongT1GlobalCFDSettings,
    T1GlobalCFDSettings,
    build_supported_manycontact_t1_solver,
    run_manycontact_t1_global_cfd_transition,
)
from bubblelab.solvers.transient.network.t1_hydrodynamics import (
    DirectT1Settings,
    build_direct_3d_t1_state,
    detect_direct_t1_eligibility,
)


class ManyContactT1GlobalCFDConfigurationError(ValueError):
    """Raised when a many-contact runtime scenario is outside supported scope."""


class ManyContactT1GlobalCFDRuntime:
    MODEL_ID = "bubblelab-global-manycontact-strongly-coupled-t1-cfd"
    VERSION = "0.1.0"

    def __init__(
        self,
        *,
        cells: int,
        extent_m: float,
        support_radius_m: float,
        old_pair_gap_m: float,
        transverse_offset_m: float,
        transverse_z_offset_m: float,
        extra_region_id: str,
        non_event_gap_m: float,
        non_event_lateral_offset_m: float,
        axis_cycle: int,
        direct_mode: str,
        direct_amplitude_m_inv: float,
        direct_y_saturation_m: float,
        sheet_tension_n_m: float,
        exterior_density_kg_m3: float,
        exterior_viscosity_pa_s: float,
        interior_density_kg_m3: float,
        interior_viscosity_pa_s: float,
        pressure_iterations: int,
        pressure_tolerance_s_inv: float,
        settings: ManyContactT1GlobalCFDSettings,
    ) -> None:
        self.cells = int(cells)
        self.extent_m = float(extent_m)
        self.support_radius_m = float(support_radius_m)
        self.old_pair_gap_m = float(old_pair_gap_m)
        self.transverse_offset_m = float(transverse_offset_m)
        self.transverse_z_offset_m = float(transverse_z_offset_m)
        self.extra_region_id = str(extra_region_id)
        self.non_event_gap_m = float(non_event_gap_m)
        self.non_event_lateral_offset_m = float(non_event_lateral_offset_m)
        self.axis_cycle = int(axis_cycle)
        self.direct_mode = str(direct_mode)
        self.direct_amplitude_m_inv = float(direct_amplitude_m_inv)
        self.direct_y_saturation_m = float(direct_y_saturation_m)
        self.sheet_tension_n_m = float(sheet_tension_n_m)
        self.exterior_density_kg_m3 = float(exterior_density_kg_m3)
        self.exterior_viscosity_pa_s = float(exterior_viscosity_pa_s)
        self.interior_density_kg_m3 = float(interior_density_kg_m3)
        self.interior_viscosity_pa_s = float(interior_viscosity_pa_s)
        self.pressure_iterations = int(pressure_iterations)
        self.pressure_tolerance_s_inv = float(pressure_tolerance_s_inv)
        self.settings = settings
        settings.validate()
        if self.cells < 8:
            raise ManyContactT1GlobalCFDConfigurationError(
                "many-contact T1 runtime requires at least eight cells per axis"
            )
        if min(
            self.extent_m,
            self.support_radius_m,
            self.old_pair_gap_m,
            self.transverse_offset_m,
            self.transverse_z_offset_m,
            self.non_event_gap_m,
            self.sheet_tension_n_m,
            self.exterior_density_kg_m3,
            self.exterior_viscosity_pa_s,
            self.interior_density_kg_m3,
            self.interior_viscosity_pa_s,
        ) <= 0.0:
            raise ManyContactT1GlobalCFDConfigurationError(
                "many-contact geometry and material properties must be positive"
            )
        if self.non_event_lateral_offset_m < 0.0:
            raise ManyContactT1GlobalCFDConfigurationError(
                "many-contact lateral offset must be non-negative"
            )
        if not self.extra_region_id:
            raise ManyContactT1GlobalCFDConfigurationError(
                "many-contact extra_region_id must be non-empty"
            )

    @classmethod
    def from_scenario(
        cls, scenario: Mapping[str, Any]
    ) -> "ManyContactT1GlobalCFDRuntime":
        raw = scenario.get("manycontact_t1_global_cfd")
        if not isinstance(raw, Mapping):
            raise ManyContactT1GlobalCFDConfigurationError(
                "scenario.manycontact_t1_global_cfd must be an object"
            )
        field_raw = raw.get("field") or {}
        direct_raw = raw.get("direct") or {}
        if not isinstance(field_raw, Mapping) or not isinstance(
            direct_raw, Mapping
        ):
            raise ManyContactT1GlobalCFDConfigurationError(
                "many-contact field/direct settings must be objects"
            )
        field = MultiregionCFDSettings(
            pseudo_steps=int(field_raw.get("pseudo_steps", 20)),
            viscous_cfl=float(field_raw.get("viscous_cfl", 0.08)),
            constraint_relaxation=float(
                field_raw.get("constraint_relaxation", 0.82)
            ),
            minimum_gap_cells=float(
                field_raw.get("minimum_gap_cells", 0.25)
            ),
            traction_offset_cells=float(
                field_raw.get("traction_offset_cells", 0.80)
            ),
            gradient_step_cells=float(
                field_raw.get("gradient_step_cells", 0.50)
            ),
            maximum_sphericity_error=float(
                field_raw.get("maximum_sphericity_error", 0.12)
            ),
            minimum_constraint_cells_per_front=int(
                field_raw.get("minimum_constraint_cells_per_front", 8)
            ),
        )
        direct = DirectT1Settings(
            plateau_border_core_radius_m=float(
                direct_raw.get("plateau_border_core_radius_m", 0.010)
            ),
            mobility_m_per_n_s=float(
                direct_raw.get("mobility_m_per_n_s", 2.0e-2)
            ),
            hydrodynamic_segments=int(
                direct_raw.get("hydrodynamic_segments", 24)
            ),
            force_difference_fraction=float(
                direct_raw.get("force_difference_fraction", 2.0e-4)
            ),
            minimum_driving_force_n=float(
                direct_raw.get("minimum_driving_force_n", 1.0e-7)
            ),
            minimum_nonplanarity_m=float(
                direct_raw.get("minimum_nonplanarity_m", 2.0e-4)
            ),
            minimum_tangent_spread=float(
                direct_raw.get("minimum_tangent_spread", 1.0e-5)
            ),
            minimum_samples=int(
                direct_raw.get("minimum_samples", 3)
            ),
            maximum_core_to_edge_ratio=float(
                direct_raw.get("maximum_core_to_edge_ratio", 0.50)
            ),
            post_event_seed_factor=float(
                direct_raw.get("post_event_seed_factor", 1.25)
            ),
            volume_relative_tolerance=float(
                direct_raw.get("volume_relative_tolerance", 1.0e-12)
            ),
        )
        base = T1GlobalCFDSettings(
            field=field,
            direct=direct,
            event_mobility_m_per_n_s=float(
                raw.get("event_mobility_m_per_n_s", 2.0e-2)
            ),
            pre_event_closing_speed_m_s=float(
                raw.get("pre_event_closing_speed_m_s", 0.020)
            ),
            pre_event_drift_speed_m_s=float(
                raw.get("pre_event_drift_speed_m_s", 0.0)
            ),
            post_event_opening_speed_m_s=float(
                raw.get("post_event_opening_speed_m_s", 0.012)
            ),
            minimum_net_driving_force_n=float(
                raw.get("minimum_net_driving_force_n", 1.0e-12)
            ),
            maximum_aggregate_traction_mismatch=float(
                raw.get("maximum_aggregate_traction_mismatch", 0.20)
            ),
        )
        strong = StrongT1GlobalCFDSettings(
            base=base,
            feedback_iterations=int(
                raw.get("feedback_iterations", 4)
            ),
            feedback_relaxation=float(
                raw.get("feedback_relaxation", 0.65)
            ),
            maximum_feedback_relative_residual=float(
                raw.get("maximum_feedback_relative_residual", 5.0e-3)
            ),
        )
        settings = ManyContactT1GlobalCFDSettings(
            strong=strong,
            minimum_support_regions=int(
                raw.get("minimum_support_regions", 5)
            ),
            non_event_relative_speed_m_s=float(
                raw.get("non_event_relative_speed_m_s", 0.0005)
            ),
            minimum_non_event_causality_fraction=float(
                raw.get(
                    "minimum_non_event_causality_fraction", 0.02
                )
            ),
        )
        return cls(
            cells=int(raw.get("cells", 10)),
            extent_m=float(raw.get("extent_m", 0.010)),
            support_radius_m=float(
                raw.get("support_radius_m", 0.00105)
            ),
            old_pair_gap_m=float(
                raw.get("old_pair_gap_m", 0.00028)
            ),
            transverse_offset_m=float(
                raw.get("transverse_offset_m", 0.00275)
            ),
            transverse_z_offset_m=float(
                raw.get("transverse_z_offset_m", 0.00160)
            ),
            extra_region_id=str(raw.get("extra_region_id", "E")),
            non_event_gap_m=float(
                raw.get("non_event_gap_m", 0.00018)
            ),
            non_event_lateral_offset_m=float(
                raw.get("non_event_lateral_offset_m", 0.00025)
            ),
            axis_cycle=int(raw.get("axis_cycle", 0)),
            direct_mode=str(
                raw.get("direct_mode", "saddle-saturation")
            ),
            direct_amplitude_m_inv=float(
                raw.get("direct_amplitude_m_inv", 0.8)
            ),
            direct_y_saturation_m=float(
                raw.get("direct_y_saturation_m", 0.04)
            ),
            sheet_tension_n_m=float(
                raw.get("sheet_tension_n_m", 0.03)
            ),
            exterior_density_kg_m3=float(
                raw.get("exterior_density_kg_m3", 970.0)
            ),
            exterior_viscosity_pa_s=float(
                raw.get("exterior_viscosity_pa_s", 50.0)
            ),
            interior_density_kg_m3=float(
                raw.get("interior_density_kg_m3", 1.204)
            ),
            interior_viscosity_pa_s=float(
                raw.get("interior_viscosity_pa_s", 1.825e-5)
            ),
            pressure_iterations=int(
                raw.get("pressure_iterations", 120)
            ),
            pressure_tolerance_s_inv=float(
                raw.get("pressure_tolerance_s_inv", 2.0e-6)
            ),
            settings=settings,
        )

    def run(self) -> dict[str, Any]:
        topology_state = build_direct_3d_t1_state(
            mode=self.direct_mode,
            amplitude_m_inv=self.direct_amplitude_m_inv,
            y_saturation_m=self.direct_y_saturation_m,
            sheet_tension_n_m=self.sheet_tension_n_m,
        )
        eligibility = detect_direct_t1_eligibility(
            topology_state, self.settings.strong.base.direct
        )
        if not eligibility.eligible or eligibility.neighborhood is None:
            raise ManyContactT1GlobalCFDConfigurationError(
                "scenario is outside supported direct-3D T1 class: "
                f"{eligibility.reason}"
            )
        topology_ids = tuple(
            region.id for region in topology_state.to_network().regions
        )
        if self.extra_region_id in topology_ids:
            raise ManyContactT1GlobalCFDConfigurationError(
                "extra_region_id collides with a topology gas ID"
            )
        solver = build_supported_manycontact_t1_solver(
            region_ids=topology_ids,
            old_pair=eligibility.neighborhood.old_adjacent_regions,
            extra_region_id=self.extra_region_id,
            cells=self.cells,
            extent_m=self.extent_m,
            radius_m=self.support_radius_m,
            old_pair_gap_m=self.old_pair_gap_m,
            transverse_offset_m=self.transverse_offset_m,
            transverse_z_offset_m=self.transverse_z_offset_m,
            non_event_gap_m=self.non_event_gap_m,
            non_event_lateral_offset_m=(
                self.non_event_lateral_offset_m
            ),
            exterior_density_kg_m3=self.exterior_density_kg_m3,
            exterior_viscosity_pa_s=self.exterior_viscosity_pa_s,
            interior_density_kg_m3=self.interior_density_kg_m3,
            interior_viscosity_pa_s=self.interior_viscosity_pa_s,
            pressure_iterations=self.pressure_iterations,
            pressure_tolerance_s_inv=self.pressure_tolerance_s_inv,
            subdivisions=2,
            axis_cycle=self.axis_cycle,
        )
        event_pair = tuple(
            sorted(eligibility.neighborhood.old_adjacent_regions)
        )
        non_event_pair = (
            event_pair[0],
            self.extra_region_id,
        )
        result = run_manycontact_t1_global_cfd_transition(
            solver,
            topology_state,
            non_event_pair,
            self.settings,
        )
        transition = result.transition
        new_pair = tuple(
            sorted(eligibility.neighborhood.opposite_regions)
        )
        return {
            "identity": self.MODEL_ID,
            "version": self.VERSION,
            "status": "SUPPORTED_CLASS_MANYCONTACT_STRONGLY_COUPLED",
            "supported_class": transition.supported_class,
            "claim_boundary": (
                "bounded five-region many-contact foundation with one embedded "
                "four-region non-coplanar T1 and one extra active contact; not "
                "arbitrary contact graphs, repeated unrestricted topology "
                "changes, singular Plateau-border CFD, turbulence, "
                "compressibility, thermal, rarefied, or universal multiphase "
                "Navier-Stokes"
            ),
            "authoritative_field": (
                "all support fronts share one partitioned Eulerian field; "
                "decoupled causality trials restore the same baseline, then the "
                "active production field continues directly through real T1 "
                "surgery into the post-event solve"
            ),
            "event_source": (
                "self-consistent mobility balance using resolved pressure/viscous "
                "traction from the active many-contact field"
            ),
            "physical_regime": {
                "sheet_tension_n_m": self.sheet_tension_n_m,
                "exterior_density_kg_m3": (
                    self.exterior_density_kg_m3
                ),
                "exterior_dynamic_viscosity_pa_s": (
                    self.exterior_viscosity_pa_s
                ),
                "interior_density_kg_m3": (
                    self.interior_density_kg_m3
                ),
                "interior_dynamic_viscosity_pa_s": (
                    self.interior_viscosity_pa_s
                ),
            },
            "frames": [
                {
                    "phase": "PRE_T1_MANYCONTACT_ACTIVE",
                    "time_s": float(topology_state.time_s),
                    "field": transition.pre_field.as_dict(),
                    "adjacency": [
                        list(pair)
                        for pair in transition.adjacency_before
                    ],
                    "active_contacts": [
                        list(event_pair),
                        list(result.non_event_contact_pair),
                    ],
                },
                {
                    "phase": "T1_EVENT",
                    "time_s": float(
                        transition.topology_state_after.time_s
                    ),
                    "retired_film_ids": list(
                        transition.retired_film_ids
                    ),
                    "created_film_ids": list(
                        transition.created_film_ids
                    ),
                    "retired_junction_ids": list(
                        transition.retired_junction_ids
                    ),
                    "created_junction_ids": list(
                        transition.created_junction_ids
                    ),
                    "adjacency": [
                        list(pair)
                        for pair in transition.adjacency_after
                    ],
                },
                {
                    "phase": "POST_T1_MANYCONTACT_ACTIVE",
                    "time_s": float(
                        transition.topology_state_after.time_s
                    ),
                    "field": transition.post_field.as_dict(),
                    "adjacency": [
                        list(pair)
                        for pair in transition.adjacency_after
                    ],
                    "active_contacts": [
                        list(new_pair),
                        list(result.non_event_contact_pair),
                    ],
                },
            ],
            "transition": result.as_dict(),
        }
