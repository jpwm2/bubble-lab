"""Deterministic reduced-order thin-film validation benchmarks."""
from __future__ import annotations

import math

from .gas import GasRegionState, GasTransferPair, R_GAS_J_MOL_K
from .surface import SurfaceMesh, SurfaceTransportParameters, SurfaceTransportState


def inclined_patch() -> SurfaceMesh:
    return SurfaceMesh(
        vertices_m=(
            (0.0, 0.0, 0.0),
            (1.0e-3, 0.0, 0.0),
            (1.0e-3, 3.0e-3, 0.0),
            (0.0, 1.0e-3, 0.0),
        ),
        faces=((0, 1, 2), (0, 2, 3)),
        mesh_id="mesh-thinfilm-demo",
        film_id="film-a-b",
    )


def _run_surface(dt_s: float, end_s: float) -> SurfaceTransportState:
    params = SurfaceTransportParameters(
        gravity_m_s2=(0.0, -9.81, 0.0),
        surfactant_diffusivity_m2_s=0.0,
        surface_elasticity_n_m_per_mol_m2=0.0,
    )
    state = SurfaceTransportState.uniform(
        inclined_patch(),
        thickness_m=10.0e-6,
        parameters=params,
    )
    steps = round(end_s / dt_s)
    for _ in range(steps):
        state.advance(dt_s)
    return state


def uniform_film_benchmark() -> dict[str, object]:
    params = SurfaceTransportParameters(
        gravity_m_s2=(0.0, 0.0, 0.0),
        surfactant_diffusivity_m2_s=1.0e-9,
    )
    state = SurfaceTransportState.uniform(
        inclined_patch(),
        thickness_m=8.0e-6,
        surfactant_mol_m2=2.0e-6,
        parameters=params,
    )
    initial_liquid = state.liquid_amount_m3()
    initial_h = tuple(state.thickness_m)
    diag = state.advance(0.25)
    passed = (
        tuple(state.thickness_m) == initial_h
        and diag.liquid_relative_drift <= 1.0e-14
        and min(state.thickness_m) >= 0.0
        and abs(state.liquid_amount_m3() - initial_liquid)
        <= 1.0e-14 * initial_liquid
    )
    return {
        "benchmark": "uniform-film",
        "passed": passed,
        "liquid_relative_drift": diag.liquid_relative_drift,
        "min_thickness_m": min(state.thickness_m),
        "max_thickness_m": max(state.thickness_m),
        "substeps": diag.substeps,
    }


def gravity_drainage_benchmark() -> dict[str, object]:
    mesh = inclined_patch()
    areas = mesh.face_areas_m2()
    centers = mesh.face_centroids_m()
    lower = min(range(2), key=lambda index: centers[index][1])
    upper = 1 - lower

    coarse = _run_surface(0.02, 0.08)
    medium = _run_surface(0.01, 0.08)
    fine = _run_surface(0.005, 0.08)
    initial_amount = 10.0e-6 * math.fsum(areas)
    mass_error = abs(fine.liquid_amount_m3() - initial_amount) / initial_amount
    d1 = abs(coarse.thickness_m[lower] - medium.thickness_m[lower])
    d2 = abs(medium.thickness_m[lower] - fine.thickness_m[lower])
    observed_order = math.log(d1 / d2, 2.0) if d1 > 0.0 and d2 > 0.0 else math.inf
    passed = (
        fine.thickness_m[lower] > 10.0e-6
        and fine.thickness_m[upper] < 10.0e-6
        and mass_error <= 1.0e-12
        and observed_order >= 0.95
        and min(fine.thickness_m) > 0.0
    )
    return {
        "benchmark": "gravity-drainage",
        "passed": passed,
        "lower_face": lower,
        "lower_thickness_m": fine.thickness_m[lower],
        "upper_thickness_m": fine.thickness_m[upper],
        "liquid_relative_drift": mass_error,
        "observed_time_order": observed_order,
    }


def surfactant_conservation_benchmark() -> dict[str, object]:
    params = SurfaceTransportParameters(
        gravity_m_s2=(0.0, 0.0, 0.0),
        surfactant_diffusivity_m2_s=2.0e-8,
        clean_surface_tension_n_m=0.050,
        surface_elasticity_n_m_per_mol_m2=2.0e3,
        minimum_surface_tension_n_m=0.020,
    )
    state = SurfaceTransportState(
        inclined_patch(),
        [8.0e-6, 8.0e-6],
        [1.0e-6, 4.0e-6],
        parameters=params,
    )
    initial_total = state.surfactant_amount_mol()
    initial_jump = abs(state.surfactant_mol_m2[1] - state.surfactant_mol_m2[0])
    initial_sigma = state.surface_tension_n_m()
    gradient = state.marangoni_gradient_n_m2()
    link = state.mesh.internal_links()[0]
    direction_low_to_high_sigma = (
        link.direction_i_to_j
        if initial_sigma[link.face_j] > initial_sigma[link.face_i]
        else tuple(-value for value in link.direction_i_to_j)
    )
    low_sigma_face = (
        link.face_i
        if initial_sigma[link.face_i] < initial_sigma[link.face_j]
        else link.face_j
    )
    marangoni_alignment = sum(
        a * b
        for a, b in zip(gradient[low_sigma_face], direction_low_to_high_sigma)
    )
    diag = state.advance(0.5)
    final_jump = abs(state.surfactant_mol_m2[1] - state.surfactant_mol_m2[0])
    final_sigma = state.surface_tension_n_m()
    conservation = abs(state.surfactant_amount_mol() - initial_total) / initial_total
    monotonic_eos = (
        (state.surfactant_mol_m2[0] < state.surfactant_mol_m2[1])
        == (final_sigma[0] > final_sigma[1])
    )
    passed = (
        conservation <= 1.0e-12
        and final_jump < initial_jump
        and monotonic_eos
        and marangoni_alignment > 0.0
        and diag.surfactant_relative_drift <= 1.0e-12
    )
    return {
        "benchmark": "surfactant-conservation",
        "passed": passed,
        "surfactant_relative_drift": conservation,
        "initial_concentration_jump_mol_m2": initial_jump,
        "final_concentration_jump_mol_m2": final_jump,
        "surface_tension_n_m": list(final_sigma),
        "marangoni_alignment": marangoni_alignment,
    }


def _gas_case(dt_s: float, end_s: float) -> tuple[GasRegionState, GasRegionState]:
    a = GasRegionState("bubble-a", volume_m3=1.0e-6, amount_mol=1.0e-5)
    b = GasRegionState("bubble-b", volume_m3=2.0e-6, amount_mol=1.0e-5)
    pair = GasTransferPair(
        "bubble-a",
        "bubble-b",
        shared_area_m2=1.0e-4,
        film_thickness_m=1.0e-6,
        permeability_mol_m_per_m2_s_pa=1.0e-12,
    )
    for _ in range(round(end_s / dt_s)):
        pair.advance(a, b, dt_s)
    return a, b


def gas_diffusion_pair_benchmark() -> dict[str, object]:
    a0 = GasRegionState("bubble-a", volume_m3=1.0e-6, amount_mol=1.0e-5)
    b0 = GasRegionState("bubble-b", volume_m3=2.0e-6, amount_mol=1.0e-5)
    pair = GasTransferPair(
        "bubble-a",
        "bubble-b",
        shared_area_m2=1.0e-4,
        film_thickness_m=1.0e-6,
        permeability_mol_m_per_m2_s_pa=1.0e-12,
    )
    initial_total = a0.amount_mol + b0.amount_mol
    initial_dp = a0.pressure_pa - b0.pressure_pa
    first = pair.advance(a0, b0, 0.1)
    direction_ok = first.amount_transferred_a_to_b_mol > 0.0 and initial_dp > 0.0

    coarse_a, coarse_b = _gas_case(0.25, 1.0)
    fine_a, fine_b = _gas_case(0.125, 1.0)
    total = 2.0e-5
    va, vb = 1.0e-6, 2.0e-6
    equilibrium_a = total * va / (va + vb)
    conductance = pair.conductance_mol_s_pa
    decay = conductance * R_GAS_J_MOL_K * 298.15 * (1.0 / va + 1.0 / vb)
    exact_a = equilibrium_a + (1.0e-5 - equilibrium_a) * math.exp(-decay * 1.0)
    coarse_error = abs(coarse_a.amount_mol - exact_a)
    fine_error = abs(fine_a.amount_mol - exact_a)
    observed_order = (
        math.log(coarse_error / fine_error, 2.0)
        if coarse_error > 0.0 and fine_error > 0.0
        else math.inf
    )
    total_drift = abs((fine_a.amount_mol + fine_b.amount_mol) - initial_total) / initial_total
    passed = (
        direction_ok
        and total_drift <= 1.0e-10
        and observed_order >= 0.95
        and coarse_a.amount_mol < 1.0e-5
        and coarse_b.amount_mol > 1.0e-5
    )
    return {
        "benchmark": "gas-diffusion-pair",
        "passed": passed,
        "initial_pressure_difference_pa": initial_dp,
        "amount_a_mol": fine_a.amount_mol,
        "amount_b_mol": fine_b.amount_mol,
        "gas_total_relative_drift": total_drift,
        "observed_time_order": observed_order,
        "coarsening_direction": "high-pressure-a-to-low-pressure-b",
    }


def remesh_transfer_benchmark() -> dict[str, object]:
    from bubblelab.solvers.transient.geometry import icosphere
    from bubblelab.solvers.transient.remeshing import FrontRemesher, RemeshConfig
    from bubblelab.solvers.transient.thinfilm_adapter import ThinFilmAttachment

    front = icosphere(radius_m=0.008, subdivisions=1)
    count = len(front.faces)
    thickness = [7.0e-6 * (1.0 + 0.05 * ((index % 5) - 2)) for index in range(count)]
    surfactant = [2.0e-6 * (1.0 + 0.03 * ((index % 7) - 3)) for index in range(count)]
    attachment = ThinFilmAttachment(
        front,
        thickness_m=thickness,
        surfactant_mol_m2=surfactant,
    )
    initial_liquid = attachment.state.liquid_amount_m3()
    initial_surfactant = attachment.state.surfactant_amount_mol()
    fields = attachment.conservative_fields()
    remesher = FrontRemesher(
        RemeshConfig(
            mode="interval",
            target_edge_length_m=front.mean_edge_length(),
            max_geometry_relative_error=1.0e-12,
        )
    )
    edge = tuple(sorted(front.faces[0][:2]))
    changed = remesher.split_edge(front, edge, fields, fraction=0.08)
    transfer = attachment.consume_remesh(front, fields)
    liquid_error = abs(attachment.state.liquid_amount_m3() - initial_liquid) / initial_liquid
    surfactant_error = abs(attachment.state.surfactant_amount_mol() - initial_surfactant) / initial_surfactant
    passed = (
        changed
        and liquid_error <= 1.0e-10
        and surfactant_error <= 1.0e-10
        and transfer.region_identity_preserved
    )
    return {
        "benchmark": "remesh-transfer",
        "passed": passed,
        "mesh_changed": changed,
        "liquid_relative_error": liquid_error,
        "surfactant_relative_error": surfactant_error,
        "region_identity_preserved": transfer.region_identity_preserved,
    }


BENCHMARKS = {
    "uniform-film": uniform_film_benchmark,
    "gravity-drainage": gravity_drainage_benchmark,
    "surfactant-conservation": surfactant_conservation_benchmark,
    "gas-diffusion-pair": gas_diffusion_pair_benchmark,
    "remesh-transfer": remesh_transfer_benchmark,
}
