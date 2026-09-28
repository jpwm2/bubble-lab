"""Runtime coupling for numerically resolved local pre-contact thin-gap flow."""
from __future__ import annotations

from dataclasses import replace
from typing import Any, Mapping, Sequence

from bubblelab.solvers.contact_lubrication import (
    GapGeometry,
    apply_pair_translation,
    gap_geometry_from_observation,
)
from bubblelab.solvers.precontact_cfd import (
    PrecontactCFDSettings,
    coupled_cfd_response,
)
from bubblelab.solvers.transient.geometry import FilmFront


class PrecontactCFDConfigurationError(ValueError):
    """Raised when the supported local CFD patch is not physically configured."""


class PrecontactCFDRuntime:
    """Deterministic local thin-gap pressure/velocity traction coupling adapter."""

    MODEL_ID = "bubblelab-local-thin-gap-incompressible-cfd"
    VERSION = "0.1.0"

    def __init__(
        self,
        *,
        enabled: bool,
        dynamic_viscosity_pa_s: float,
        settings: PrecontactCFDSettings,
    ) -> None:
        settings.validate()
        if dynamic_viscosity_pa_s <= 0.0:
            raise PrecontactCFDConfigurationError(
                "ambient dynamic viscosity must be positive for pre-contact CFD"
            )
        self.enabled = bool(enabled)
        self.dynamic_viscosity_pa_s = float(dynamic_viscosity_pa_s)
        self.settings = settings
        self.activation_count = 0
        self.cumulative_radial_outflow_m3 = 0.0
        self.cumulative_viscous_dissipation_j = 0.0
        self.max_volume_relative_change = 0.0
        self.max_pressure_pa = 0.0
        self.max_force_n = 0.0
        self.max_mass_balance_relative_residual = 0.0
        self.max_wall_slip_m_s = 0.0
        self.last_step: dict[str, Any] | None = None
        self.step_history: list[dict[str, Any]] = []

    @classmethod
    def from_scenario(cls, scenario: Mapping[str, Any]) -> "PrecontactCFDRuntime":
        editable = scenario.get("user_editable") or {}
        contact = editable.get("contact_runtime") if isinstance(editable, Mapping) else None
        raw = contact.get("precontact_cfd") if isinstance(contact, Mapping) else None
        if raw is None:
            enabled = False
            raw = {}
        elif not isinstance(raw, Mapping):
            raise PrecontactCFDConfigurationError(
                "contact_runtime.precontact_cfd must be an object"
            )
        else:
            enabled = bool(raw.get("enabled", True))
        environment = scenario.get("environment") or {}
        viscosity = float(environment.get("ambient_dynamic_viscosity_pa_s", 0.0))
        settings = PrecontactCFDSettings(
            enabled=enabled,
            minimum_gap_m=float(raw.get("minimum_gap_m", 1.0e-7)),
            onset_gap_over_effective_radius=float(
                raw.get("onset_gap_over_effective_radius", 0.5)
            ),
            outer_drag_scale=float(raw.get("outer_drag_scale", 1.0)),
            radial_cells=int(raw.get("radial_cells", 64)),
            gap_cells=int(raw.get("gap_cells", 16)),
            radial_extent_over_sqrt_2rh=float(
                raw.get("radial_extent_over_sqrt_2rh", 100.0)
            ),
            radial_stretch=float(raw.get("radial_stretch", 6.0)),
            volume_relative_tolerance=float(
                raw.get("volume_relative_tolerance", 5.0e-12)
            ),
        )
        return cls(
            enabled=enabled,
            dynamic_viscosity_pa_s=viscosity,
            settings=settings,
        )

    def geometry(
        self,
        fronts: Sequence[FilmFront],
        observation: Any,
    ) -> GapGeometry:
        return gap_geometry_from_observation(fronts, observation)

    def couple_step(
        self,
        fronts: Sequence[FilmFront],
        before_geometry: GapGeometry,
        free_observation: Any,
        dt_s: float,
    ) -> dict[str, Any]:
        if dt_s <= 0.0:
            raise ValueError("pre-contact CFD coupling timestep must be positive")
        free_geometry = self.geometry(fronts, free_observation)
        free_closure = max(0.0, before_geometry.gap_m - free_geometry.gap_m)
        free_speed = free_closure / dt_s
        midpoint_gap = max(
            self.settings.minimum_gap_m,
            0.5 * (
                max(before_geometry.gap_m, 0.0)
                + max(free_geometry.gap_m, 0.0)
            ),
        )
        model_geometry = replace(
            free_geometry,
            gap_m=midpoint_gap,
            geometry_source=(
                free_geometry.geometry_source
                + "; midpoint local parabolic CFD patch over one accepted transient step"
            ),
        )
        response = coupled_cfd_response(
            model_geometry,
            free_speed,
            self.dynamic_viscosity_pa_s,
            self.settings,
        )
        correction = min(
            free_closure,
            response.correction_speed_m_s * dt_s,
        )
        volume_errors = apply_pair_translation(
            fronts,
            free_geometry,
            correction,
            self.settings.volume_relative_tolerance,
        )
        maximum_volume_error = max(volume_errors.values(), default=0.0)
        self.max_volume_relative_change = max(
            self.max_volume_relative_change,
            maximum_volume_error,
        )
        if response.active:
            self.activation_count += 1
            self.cumulative_radial_outflow_m3 += (
                response.radial_outflow_m3_s * dt_s
            )
            self.cumulative_viscous_dissipation_j += (
                response.viscous_dissipation_w * dt_s
            )
            self.max_pressure_pa = max(
                self.max_pressure_pa,
                response.center_pressure_pa,
            )
            self.max_force_n = max(self.max_force_n, response.force_n)
            assert response.field is not None
            self.max_mass_balance_relative_residual = max(
                self.max_mass_balance_relative_residual,
                response.field.mass_balance_relative_residual,
            )
            self.max_wall_slip_m_s = max(
                self.max_wall_slip_m_s,
                response.field.max_wall_slip_m_s,
            )

        step = {
            "model": response.model,
            "model_status": (
                "SUPPORTED_CLASS_RESOLVED" if self.enabled else "NOT_IMPLEMENTED"
            ),
            "step_dt_s": float(dt_s),
            "before_gap_m": float(before_geometry.gap_m),
            "free_gap_m": float(free_geometry.gap_m),
            "model_gap_m": float(model_geometry.gap_m),
            "separation_correction_m": float(correction),
            "geometry": {
                "parent_ids": list(model_geometry.parent_ids),
                "anchor_vertex_indices": list(model_geometry.anchor_vertex_indices),
                "normal_a_to_b": list(model_geometry.normal_a_to_b),
                "local_radius_a_m": float(model_geometry.local_radius_a_m),
                "local_radius_b_m": float(model_geometry.local_radius_b_m),
                "effective_radius_m": float(model_geometry.effective_radius_m),
                "local_curvature_a_1_m": float(model_geometry.local_curvature_a_1_m),
                "local_curvature_b_1_m": float(model_geometry.local_curvature_b_1_m),
                "mesh_resolution_m": float(model_geometry.mesh_resolution_m),
                "source": model_geometry.geometry_source,
            },
            "response": response.as_dict(),
            "conservation": {
                "closed_bubble_volume_relative_change": {
                    key: float(value)
                    for key, value in sorted(volume_errors.items())
                },
                "max_closed_bubble_volume_relative_change": float(
                    maximum_volume_error
                ),
                "local_gap_mass_balance_relative_residual": (
                    0.0
                    if response.field is None
                    else float(response.field.mass_balance_relative_residual)
                ),
                "radial_gap_outflow_m3_s": float(response.radial_outflow_m3_s),
                "liquid_inventory_model": (
                    "resolved local gap velocity/pressure patch with zero-thickness "
                    "tracked interfaces; not a persistent global liquid-film inventory"
                ),
            },
        }
        self.last_step = step
        self.step_history.append(step)
        return step

    def _summary(self) -> dict[str, Any]:
        return {
            "identity": self.MODEL_ID,
            "version": self.VERSION,
            "status": (
                "SUPPORTED_CLASS_RESOLVED" if self.enabled else "NOT_IMPLEMENTED"
            ),
            "formulation": (
                "axisymmetric radial finite-volume incompressible squeeze-flow pressure "
                "solve; face mobility and radial velocity obtained from a discretized "
                "no-slip Stokes solve across the gap; traction integrated numerically "
                "from the solved pressure"
            ),
            "geometry_source": (
                "authoritative triangulated tracked-front gap and discrete local curvature "
                "-> deterministic local parabolic patch"
            ),
            "moving_interface_boundary_conditions": (
                "measured relative approach supplies +/- half closing-speed normal wall "
                "motion; radial velocity is no-slip at both interfaces"
            ),
            "production_traction_source": (
                "numerically solved pressure field; Taylor/Reynolds closed form is "
                "validation-only"
            ),
            "dynamic_viscosity_pa_s": self.dynamic_viscosity_pa_s,
            "radial_cells": self.settings.radial_cells,
            "gap_cells": self.settings.gap_cells,
            "activation_count": int(self.activation_count),
            "cumulative_radial_gap_outflow_m3": float(
                self.cumulative_radial_outflow_m3
            ),
            "cumulative_viscous_dissipation_j": float(
                self.cumulative_viscous_dissipation_j
            ),
            "max_center_pressure_pa": float(self.max_pressure_pa),
            "max_cfd_traction_force_n": float(self.max_force_n),
            "max_local_mass_balance_relative_residual": float(
                self.max_mass_balance_relative_residual
            ),
            "max_wall_slip_m_s": float(self.max_wall_slip_m_s),
            "max_closed_bubble_volume_relative_change": float(
                self.max_volume_relative_change
            ),
            "supported_class": [
                "one isolated two-front pre-contact gap",
                "locally axisymmetric thin gap represented from measured gap and curvatures",
                "creeping incompressible ambient-fluid squeeze flow",
            ],
            "not_claimed": [
                "global full-domain multi-region Navier-Stokes coupling",
                "simultaneous general multi-contact/T1 gap CFD",
                "inertial, compressible, thermal, or rarefied-gas gap flow",
                "persistent resolved liquid-film thickness/inventory before contact",
            ],
        }

    def decorate_frame(
        self,
        frame: dict[str, Any],
        *,
        step: dict[str, Any] | None = None,
        handoff: bool = False,
    ) -> None:
        if not self.enabled:
            return
        disclosures = frame["manifest"]["feature_disclosures"]
        disclosures["pre_contact_lubrication_drainage"] = "MODELED"
        disclosures["pre_contact_lubrication_pressure_feedback"] = "MODELED"
        disclosures["pre_contact_local_gap_resolved_cfd"] = "MODELED"
        disclosures["fully_coupled_multi_region_eulerian_cfd"] = "NOT_IMPLEMENTED"
        provenance = frame["manifest"].setdefault("provenance", {})
        provenance.update({
            "pre_contact_cfd_model": self.MODEL_ID,
            "pre_contact_cfd_status": "SUPPORTED_CLASS_RESOLVED",
            "pre_contact_cfd_geometry": (
                "authoritative triangulated gap + discrete local curvature"
            ),
            "pre_contact_cfd_global_multiregion_status": "NOT_IMPLEMENTED",
        })
        diagnostics = frame.setdefault("diagnostics", {})
        diagnostics["pre_contact_cfd"] = {
            "summary": self._summary(),
            "step": step if step is not None else self.last_step,
            "handoff_to_shared_film": bool(handoff),
        }
        if handoff:
            for event in frame.get("topology", {}).get("events", []):
                if event.get("transition_kind") != "CONTACT_FORMATION":
                    continue
                event.setdefault("provenance", {}).update({
                    "pre_contact_cfd_model": self.MODEL_ID,
                    "pre_contact_cfd_status": "SUPPORTED_CLASS_RESOLVED",
                    "pre_contact_cfd_history_steps": len(self.step_history),
                    "last_pre_contact_cfd_step": self.last_step,
                })

    def backend_metadata(self) -> dict[str, Any]:
        return self._summary()


def run_precontact_cfd_transition(
    scenario: Mapping[str, Any],
    frames: int,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Run the accepted two-front contact path with resolved local gap-CFD feedback."""
    if frames < 2:
        raise PrecontactCFDConfigurationError(
            "pre-contact CFD transition requires at least two frames"
        )

    from bubblelab.runtime import contact_runtime as contact
    from bubblelab.solvers.transient.contact import (
        ContactFormationError,
        form_contact,
        observe_contact,
    )
    from bubblelab.solvers.transient.network.core import (
        advance as advance_network,
        diagnostics as network_diagnostics,
    )

    first, second = contact._validate_scenario(scenario)
    config = contact._config(scenario)
    solver, contact_settings, network_settings = contact._build_solver(
        scenario,
        first,
        second,
    )
    coupling = PrecontactCFDRuntime.from_scenario(scenario)
    ordered = sorted(solver.fronts, key=lambda item: item.bubble_id)
    try:
        observation = observe_contact(
            ordered[0], ordered[1], contact_settings
        )
    except ContactFormationError as exc:
        raise PrecontactCFDConfigurationError(str(exc)) from exc
    if observation.contact:
        raise PrecontactCFDConfigurationError(
            "pre-contact CFD initial condition must begin with separated fronts"
        )

    first_frame = contact._pre_frame(solver, observation, 0)
    coupling.decorate_frame(first_frame)
    output = [first_frame]
    transition = None
    network_state = None
    network_centroids = None
    trigger = None
    event_time_s = None
    post_steps = 0
    forcing = contact._network_forcing(scenario, config)

    for frame_index in range(1, frames):
        if network_state is None:
            ordered = sorted(
                solver.fronts,
                key=lambda item: item.bubble_id,
            )
            before_geometry = coupling.geometry(ordered, observation)
            step_diagnostics = solver.step()
            ordered = sorted(
                solver.fronts,
                key=lambda item: item.bubble_id,
            )
            try:
                free_observation = observe_contact(
                    ordered[0], ordered[1], contact_settings
                )
            except ContactFormationError as exc:
                raise PrecontactCFDConfigurationError(str(exc)) from exc
            step = coupling.couple_step(
                ordered,
                before_geometry,
                free_observation,
                float(step_diagnostics.timestep_s),
            )
            try:
                observation = observe_contact(
                    ordered[0], ordered[1], contact_settings
                )
            except ContactFormationError as exc:
                raise PrecontactCFDConfigurationError(str(exc)) from exc

            if not observation.contact:
                frame = contact._pre_frame(
                    solver,
                    observation,
                    frame_index,
                )
                coupling.decorate_frame(frame, step=step)
                output.append(frame)
                continue

            transition = form_contact(
                ordered[0],
                ordered[1],
                contact_settings,
            )
            trigger = transition.observation
            event_time_s = float(solver.time_s)
            network_state = replace(
                transition.state,
                time_s=event_time_s,
                step_index=solver.step_index,
            )
            diag = network_diagnostics(network_state)
            frame, network_centroids = contact._post_frame(
                scenario,
                network_state,
                diag,
                network_settings,
                frame_index,
                None,
                trigger,
                event_time_s,
                transition.raw_relative_volume_errors,
                transition.projected_relative_volume_errors,
                post_steps,
                True,
            )
            coupling.decorate_frame(frame, step=step, handoff=True)
            output.append(frame)
            continue

        assert (
            transition is not None
            and trigger is not None
            and event_time_s is not None
        )
        network_state, diag = advance_network(
            network_state,
            settings=network_settings,
            forcing=forcing,
        )
        post_steps += 1
        frame, network_centroids = contact._post_frame(
            scenario,
            network_state,
            diag,
            network_settings,
            frame_index,
            network_centroids,
            trigger,
            event_time_s,
            transition.raw_relative_volume_errors,
            transition.projected_relative_volume_errors,
            post_steps,
            False,
        )
        coupling.decorate_frame(frame)
        output.append(frame)

    if (
        network_state is None
        or transition is None
        or trigger is None
        or event_time_s is None
    ):
        raise PrecontactCFDConfigurationError(
            "supported contact was not reached within the requested physical frames"
        )

    event_count = sum(
        1
        for frame in output
        for event in frame["topology"]["events"]
        if event.get("transition_kind") == "CONTACT_FORMATION"
    )
    if event_count != 1:
        raise RuntimeError(
            "pre-contact CFD replay must contain exactly one contact formation event"
        )

    return output, {
        "identity": "bubblelab-precontact-cfd-runtime",
        "version": PrecontactCFDRuntime.VERSION,
        "model_class": (
            "accepted front-tracked sharp-interface approach + supported-class "
            "resolved local thin-gap incompressible pressure/velocity solve -> "
            "accepted local contact surgery -> accepted shared-DOF transient film network"
        ),
        "base_contact_backend": contact.BACKEND_ID,
        "base_contact_version": contact.VERSION,
        "pre_contact_cfd": coupling.backend_metadata(),
        "contact_surgery": "bubblelab.solvers.transient.contact.form_contact",
        "post_contact_solver": "bubblelab.solvers.transient.network.core.advance",
        "contact_event_time_s": float(event_time_s),
        "contact_events": 1,
        "contract_event_type": "FILM_FORMED",
        "transition_kind": "CONTACT_FORMATION",
        "topology_guarantee": (
            "one accepted shared film and one authoritative shared contact-ring DOF set"
        ),
        "handoff": (
            "CFD-corrected authoritative front geometry is handed directly to accepted "
            "form_contact; no post-hoc delay or threshold modification"
        ),
        "unsupported": [
            "global full-domain multi-region Eulerian/Navier-Stokes gap coupling",
            "general simultaneous multi-contact/T1 gap CFD",
            "inertial/compressible/thermal/rarefied-gas thin-gap physics",
        ],
    }
