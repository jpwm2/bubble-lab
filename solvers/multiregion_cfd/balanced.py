"""Momentum-consistent traction recovery for the supported two-bubble CFD path.

The tracked interfaces use regularized immersed forcing: the numerical interface
occupies a finite Eulerian support rather than one geometric zero-thickness
surface.  Sampling Cauchy stress *inside* that regularization layer does not obey
the same discrete momentum equation as the forcing reaction.

For production feedback we therefore use the finite-volume equivalent of a
closed stress-surface integral.  For each bubble, a control volume contains its
interior region plus every Eulerian cell touched by its immersed forcing support.
The pressure and viscous momentum operators used by the authoritative field
solver are integrated over that volume.  By the discrete divergence theorem this
is the pressure/viscous traction flux through the closed control surface.  It is
field-derived (never substituted from the immersed reaction), but is directly
comparable with that reaction for the momentum-balance gate.
"""
from __future__ import annotations

from dataclasses import replace
from typing import Any, Sequence

from bubblelab.solvers.transient.geometry import FilmFront, Vec3, dot, norm

from . import core as _core
from .core import (
    GlobalCoupledResponse,
    GlobalFieldResult,
    MultiregionCFDSettings,
    SurfaceTraction,
)


def _add(a: Vec3, b: Vec3) -> Vec3:
    return (a[0] + b[0], a[1] + b[1], a[2] + b[2])


def _control_volume_cells(grid: Any, front: FilmFront) -> set[int]:
    """Closed Eulerian volume enclosing one front's regularized forcing support."""
    support = set(_core._constraint_map(grid, front, (0.0, 0.0, 0.0)))
    interior = {
        q for q, label in enumerate(grid.region_labels) if label == front.bubble_id
    }
    return support | interior


def _discrete_control_surface_tractions(
    grid: Any,
    fronts: Sequence[FilmFront],
) -> tuple[SurfaceTraction, SurfaceTraction]:
    """Integrate the solver's pressure/viscous momentum flux on closed volumes."""
    masks = tuple(_control_volume_cells(grid, front) for front in fronts)
    overlap = masks[0] & masks[1]
    if overlap:
        raise ValueError(
            "global CFD immersed forcing supports overlap; hand off before "
            f"the regularized control volumes share {len(overlap)} Eulerian cells"
        )

    # These are exactly the spatial operators advanced by _relax_global_field.
    viscous_acceleration = tuple(
        grid._variable_viscous_term(field, axis)
        for axis, field in enumerate((grid.u, grid.v, grid.w))
    )
    pressure_mobility_gradient = grid._mobility_gradient(grid.pressure)
    volume = grid.cell_volume

    tractions: list[SurfaceTraction] = []
    for front, mask in zip(fronts, masks):
        pressure_force = tuple(
            sum(
                -grid.density[q] * pressure_mobility_gradient[axis][q] * volume
                for q in mask
            )
            for axis in range(3)
        )
        viscous_force = tuple(
            sum(
                grid.density[q] * viscous_acceleration[axis][q] * volume
                for q in mask
            )
            for axis in range(3)
        )
        total_force = _add(pressure_force, viscous_force)
        tractions.append(
            SurfaceTraction(
                bubble_id=front.bubble_id,
                pressure_force_n=pressure_force,
                viscous_force_n=viscous_force,
                total_force_n=total_force,
            )
        )
    return tractions[0], tractions[1]


def _recover_balanced_traction(
    solver: Any,
    result: GlobalFieldResult,
    settings: MultiregionCFDSettings,
) -> GlobalFieldResult:
    """Recover production traction from a closed discrete stress control surface."""
    del settings  # The discrete control surface has no arbitrary sampling offset.
    fronts = _core._ordered_fronts(solver.fronts, result.geometry)
    tractions = _discrete_control_surface_tractions(solver.grid, fronts)
    axis = result.geometry.normal_a_to_b
    resisting = _core._axis_resistance(
        tractions[0].total_force_n,
        tractions[1].total_force_n,
        axis,
    )
    pressure_resisting = _core._axis_resistance(
        tractions[0].pressure_force_n,
        tractions[1].pressure_force_n,
        axis,
    )
    viscous_resisting = 0.5 * (
        -dot(tractions[0].viscous_force_n, axis)
        + dot(tractions[1].viscous_force_n, axis)
    )
    pair_sum = _add(tractions[0].total_force_n, tractions[1].total_force_n)
    pair_imbalance = norm(pair_sum) / max(
        norm(tractions[0].total_force_n) + norm(tractions[1].total_force_n),
        1.0e-30,
    )

    reactions = dict(result.constraint_reaction_forces_n)
    reaction_resisting = _core._axis_resistance(
        reactions[fronts[0].bubble_id],
        reactions[fronts[1].bubble_id],
        axis,
    )
    mismatch = abs(reaction_resisting - resisting) / max(
        reaction_resisting,
        resisting,
        1.0e-30,
    )
    return replace(
        result,
        tractions=tractions,
        resisting_force_n=resisting,
        pressure_resisting_force_n=pressure_resisting,
        viscous_resisting_force_n=viscous_resisting,
        pair_force_relative_imbalance=pair_imbalance,
        constraint_traction_relative_mismatch=mismatch,
    )


def solve_global_precontact_field(
    solver: Any,
    closing_speed_m_s: float,
    settings: MultiregionCFDSettings | None = None,
) -> GlobalFieldResult:
    """Solve the authoritative field and integrate closed control-surface traction."""
    cfg = settings or MultiregionCFDSettings()
    result = _core.solve_global_precontact_field(solver, closing_speed_m_s, cfg)
    return _recover_balanced_traction(solver, result, cfg)


def coupled_global_response(
    solver: Any,
    free_closing_speed_m_s: float,
    outer_resistance_n_s_m: float,
    settings: MultiregionCFDSettings | None = None,
) -> GlobalCoupledResponse:
    """Couple front speed using resistance from solved discrete stress flux."""
    cfg = settings or MultiregionCFDSettings()
    free_speed = float(free_closing_speed_m_s)
    if free_speed < 0.0:
        raise ValueError("free closing speed must be non-negative")
    if outer_resistance_n_s_m <= 0.0:
        raise ValueError("outer resistance must be positive")

    grid, fronts, geometry = _core._validate_supported_class(
        solver,
        cfg,
        refresh_regions=True,
    )
    baseline = _core._snapshot(grid)

    trial_raw = _core._solve_current_geometry(grid, fronts, geometry, free_speed, cfg)
    trial = _recover_balanced_traction(solver, trial_raw, cfg)
    if free_speed <= 1.0e-15:
        resistance = 0.0
        coupled = 0.0
    else:
        resistance = trial.resisting_force_n / free_speed
        coupled = free_speed * outer_resistance_n_s_m / (
            outer_resistance_n_s_m + max(resistance, 0.0)
        )

    _core._restore(grid, baseline)
    production_raw = _core._solve_current_geometry(grid, fronts, geometry, coupled, cfg)
    production = _recover_balanced_traction(solver, production_raw, cfg)
    return GlobalCoupledResponse(
        free_closing_speed_m_s=free_speed,
        coupled_closing_speed_m_s=coupled,
        correction_speed_m_s=max(0.0, free_speed - coupled),
        outer_resistance_n_s_m=float(outer_resistance_n_s_m),
        resolved_cfd_resistance_n_s_m=float(max(resistance, 0.0)),
        trial_field=trial,
        production_field=production,
    )
