"""Transient evolution of pre-existing multi-region soap-film networks.

The transient layer owns one coordinate per geometric degree of freedom. Plateau
junction vertices represented by three patch-local indices in the equilibrium
mesh are collapsed to one authoritative DOF and expanded only for FilmNetwork
views.
"""
from __future__ import annotations

from dataclasses import dataclass, replace
import math
import statistics
from typing import Callable

from ...equilibrium.network import (
    FilmNetwork,
    FilmPatch,
    junction_geometry_diagnostics,
    project_region_volumes,
    stationarity,
)

Vec3 = tuple[float, float, float]
Member = tuple[str, int]
ForcingHook = Callable[[str, int, Vec3, float], Vec3]


def _add(a: Vec3, b: Vec3) -> Vec3:
    return (a[0] + b[0], a[1] + b[1], a[2] + b[2])


def _sub(a: Vec3, b: Vec3) -> Vec3:
    return (a[0] - b[0], a[1] - b[1], a[2] - b[2])


def _mul(a: Vec3, s: float) -> Vec3:
    return (a[0] * s, a[1] * s, a[2] * s)


def _norm(a: Vec3) -> float:
    return math.sqrt(a[0] * a[0] + a[1] * a[1] + a[2] * a[2])


@dataclass(frozen=True)
class GeometryDOF:
    id: str
    members: tuple[Member, ...]
    fixed: bool


@dataclass(frozen=True)
class NetworkTopology:
    """Stable identity and patch membership for transient shared geometry."""

    region_ids: tuple[str, ...]
    film_ids: tuple[str, ...]
    junction_ids: tuple[str, ...]
    dofs: tuple[GeometryDOF, ...]
    member_to_dof: dict[Member, int]

    @classmethod
    def from_network(cls, network: FilmNetwork) -> "NetworkTopology":
        network.validate()
        patch_by_id = {patch.id: patch for patch in network.patches}
        all_members = [
            (patch.id, index)
            for patch in network.patches
            for index in range(len(patch.mesh.vertices))
        ]
        parent = {member: member for member in all_members}

        def find(member: Member) -> Member:
            root = member
            while parent[root] != root:
                root = parent[root]
            while parent[member] != member:
                nxt = parent[member]
                parent[member] = root
                member = nxt
            return root

        def union(a: Member, b: Member) -> None:
            ra, rb = find(a), find(b)
            if ra != rb:
                parent[max(ra, rb)] = min(ra, rb)

        junction_name: dict[Member, str] = {}
        for junction in network.junctions:
            count = len(junction.vertex_indices_by_film[0])
            for sample in range(count):
                members = tuple(
                    (film_id, indices[sample])
                    for film_id, indices in zip(
                        junction.incident_film_ids,
                        junction.vertex_indices_by_film,
                    )
                )
                for member in members[1:]:
                    union(members[0], member)
                for member in members:
                    junction_name[member] = f"junction:{junction.id}:{sample:06d}"

        groups: dict[Member, list[Member]] = {}
        for member in all_members:
            groups.setdefault(find(member), []).append(member)

        entries: list[tuple[str, tuple[Member, ...], bool]] = []
        for members_list in groups.values():
            members = tuple(sorted(members_list))
            names = sorted({junction_name[m] for m in members if m in junction_name})
            dof_id = names[0] if names else f"vertex:{members[0][0]}:{members[0][1]:06d}"
            fixed = any(
                index in set(patch_by_id[film_id].fixed_vertex_indices)
                for film_id, index in members
            )
            entries.append((dof_id, members, fixed))
        entries.sort(key=lambda item: item[0])

        dofs = tuple(
            GeometryDOF(dof_id, members, fixed)
            for dof_id, members, fixed in entries
        )
        member_to_dof = {
            member: dof_index
            for dof_index, dof in enumerate(dofs)
            for member in dof.members
        }
        return cls(
            region_ids=tuple(region.id for region in network.regions),
            film_ids=tuple(patch.id for patch in network.patches),
            junction_ids=tuple(junction.id for junction in network.junctions),
            dofs=dofs,
            member_to_dof=member_to_dof,
        )


@dataclass(frozen=True)
class TransientNetworkState:
    """Authoritative shared-DOF state plus immutable network metadata."""

    template: FilmNetwork
    topology: NetworkTopology
    positions: tuple[Vec3, ...]
    time_s: float = 0.0
    step_index: int = 0
    pressures_pa: tuple[tuple[str, float], ...] = ()

    @classmethod
    def from_network(cls, network: FilmNetwork) -> "TransientNetworkState":
        topology = NetworkTopology.from_network(network)
        patch_by_id = {patch.id: patch for patch in network.patches}
        positions = []
        for dof in topology.dofs:
            samples = [
                patch_by_id[film_id].mesh.vertices[index]
                for film_id, index in dof.members
            ]
            reference = samples[0]
            if any(_norm(_sub(sample, reference)) > 1.0e-10 for sample in samples[1:]):
                raise ValueError(
                    f"shared DOF {dof.id!r} has disconnected member geometry"
                )
            positions.append(reference)
        pressures, _ = stationarity(network)
        return cls(
            template=network,
            topology=topology,
            positions=tuple(positions),
            pressures_pa=tuple(
                (region.id, pressures[region.id]) for region in network.regions
            ),
        )

    def to_network(self) -> FilmNetwork:
        patches = []
        for patch in self.template.patches:
            vertices = tuple(
                self.positions[self.topology.member_to_dof[(patch.id, index)]]
                for index in range(len(patch.mesh.vertices))
            )
            patches.append(FilmPatch(
                id=patch.id,
                mesh=patch.mesh.with_vertices(vertices),
                adjacent=patch.adjacent,
                sheet_tension_n_m=patch.sheet_tension_n_m,
                fixed_vertex_indices=patch.fixed_vertex_indices,
                contributes_to_volume=patch.contributes_to_volume,
            ))
        network = FilmNetwork(
            self.template.regions,
            tuple(patches),
            self.template.junctions,
        )
        network.validate()
        return network

    def topology_signature(self) -> tuple[object, ...]:
        return (
            self.topology.region_ids,
            self.topology.film_ids,
            self.topology.junction_ids,
            tuple((dof.id, dof.members, dof.fixed) for dof in self.topology.dofs),
        )

    def shared_dof_count(self) -> int:
        return sum(len(dof.members) > 1 for dof in self.topology.dofs)


@dataclass(frozen=True)
class NetworkStepperSettings:
    dt_s: float = 2.0e-4
    mobility_m_per_n_s: float = 2.0e-2
    max_displacement_edge_fraction: float = 0.025
    volume_relative_tolerance: float = 2.0e-10
    volume_projection_iterations: int = 20
    max_backtracks: int = 18
    energy_roundoff_relative: float = 2.0e-12

    def validate(self) -> None:
        if self.dt_s <= 0.0 or self.mobility_m_per_n_s <= 0.0:
            raise ValueError("dt and mobility must be positive")
        if not (0.0 < self.max_displacement_edge_fraction <= 0.25):
            raise ValueError(
                "max displacement edge fraction must lie in (0, 0.25]"
            )
        if self.volume_relative_tolerance <= 0.0:
            raise ValueError("volume tolerance must be positive")
        if self.volume_projection_iterations < 1 or self.max_backtracks < 1:
            raise ValueError("iteration limits must be positive")


@dataclass(frozen=True)
class NetworkStepDiagnostics:
    step_index: int
    time_s: float
    surface_energy_j: float
    relative_volume_errors: tuple[tuple[str, float], ...]
    pressures_pa: tuple[tuple[str, float], ...]
    max_junction_force_residual: float
    accepted_scale: float
    max_displacement_m: float


class ConstantForcing:
    """Deterministic wind/gravity/acceleration-style interface forcing.

    acceleration_m_s2 is converted into an effective interface velocity using the
    configured response time. The hook changes authoritative transient geometry,
    never renderer-only coordinates.
    """

    def __init__(
        self,
        velocity_m_s: Vec3 = (0.0, 0.0, 0.0),
        acceleration_m_s2: Vec3 = (0.0, 0.0, 0.0),
        response_time_s: float = 0.0,
    ) -> None:
        if response_time_s < 0.0:
            raise ValueError("response time must be non-negative")
        self.velocity = _add(
            velocity_m_s,
            _mul(acceleration_m_s2, response_time_s),
        )

    def __call__(
        self,
        dof_id: str,
        step_index: int,
        position: Vec3,
        time_s: float,
    ) -> Vec3:
        return self.velocity


def _median_edge_length(network: FilmNetwork) -> float:
    lengths = [
        length
        for patch in network.patches
        for length in patch.mesh.edge_lengths()
    ]
    return statistics.median(lengths)


def _unique_residuals(
    state: TransientNetworkState,
    network: FilmNetwork,
) -> tuple[dict[str, float], tuple[Vec3, ...]]:
    pressures, residual = stationarity(network)
    patch_index = {patch.id: i for i, patch in enumerate(network.patches)}
    values = []
    for dof in state.topology.dofs:
        local = [
            residual[patch_index[film_id]][vertex_index]
            for film_id, vertex_index in dof.members
        ]
        inv = 1.0 / len(local)
        values.append((
            sum(value[0] for value in local) * inv,
            sum(value[1] for value in local) * inv,
            sum(value[2] for value in local) * inv,
        ))
    return pressures, tuple(values)


def diagnostics(
    state: TransientNetworkState,
    accepted_scale: float = 1.0,
    max_displacement_m: float = 0.0,
) -> NetworkStepDiagnostics:
    network = state.to_network()
    pressures, _ = stationarity(network)
    volume_errors = tuple(
        (
            region.id,
            abs(network.region_volume(region.id) - region.target_volume_m3)
            / region.target_volume_m3,
        )
        for region in network.regions
    )
    junction_residual = max(
        (
            float(
                junction_geometry_diagnostics(network, junction.id)[
                    "max_force_residual"
                ]
            )
            for junction in network.junctions
        ),
        default=0.0,
    )
    return NetworkStepDiagnostics(
        step_index=state.step_index,
        time_s=state.time_s,
        surface_energy_j=network.surface_energy_j(),
        relative_volume_errors=volume_errors,
        pressures_pa=tuple((region.id, pressures[region.id]) for region in network.regions),
        max_junction_force_residual=junction_residual,
        accepted_scale=accepted_scale,
        max_displacement_m=max_displacement_m,
    )


def advance(
    state: TransientNetworkState,
    settings: NetworkStepperSettings | None = None,
    forcing: ForcingHook | None = None,
) -> tuple[TransientNetworkState, NetworkStepDiagnostics]:
    """Advance one deterministic overdamped capillary timestep.

    With zero forcing this is constrained gradient flow of surface energy. Finite
    timestep volume drift is removed by the coupled multi-region Newton projection.
    """
    cfg = settings or NetworkStepperSettings()
    cfg.validate()
    network = state.to_network()
    before_energy = network.surface_energy_j()
    _, residuals = _unique_residuals(state, network)
    median_edge = _median_edge_length(network)

    velocities: list[Vec3] = []
    for dof, position, residual in zip(
        state.topology.dofs,
        state.positions,
        residuals,
    ):
        if dof.fixed:
            velocities.append((0.0, 0.0, 0.0))
            continue
        velocity = _mul(residual, -cfg.mobility_m_per_n_s)
        if forcing is not None:
            velocity = _add(
                velocity,
                forcing(dof.id, state.step_index, position, state.time_s),
            )
        velocities.append(velocity)

    max_speed = max((_norm(value) for value in velocities), default=0.0)
    requested = cfg.dt_s * max_speed
    displacement_cap = cfg.max_displacement_edge_fraction * median_edge
    cap_scale = (
        1.0
        if requested <= displacement_cap or requested == 0.0
        else displacement_cap / requested
    )

    accepted_state: TransientNetworkState | None = None
    accepted_scale = cap_scale
    max_displacement = 0.0
    for backtrack in range(cfg.max_backtracks):
        scale = cap_scale * (0.5 ** backtrack)
        positions = tuple(
            _add(position, _mul(velocity, cfg.dt_s * scale))
            for position, velocity in zip(state.positions, velocities)
        )
        trial = replace(
            state,
            positions=positions,
            time_s=state.time_s + cfg.dt_s,
            step_index=state.step_index + 1,
        )
        projected_network = project_region_volumes(
            trial.to_network(),
            relative_tolerance=cfg.volume_relative_tolerance,
            max_iterations=cfg.volume_projection_iterations,
        )
        projected_raw = TransientNetworkState.from_network(projected_network)
        projected = replace(
            projected_raw,
            template=state.template,
            topology=state.topology,
            time_s=state.time_s + cfg.dt_s,
            step_index=state.step_index + 1,
        )
        after_energy = projected_network.surface_energy_j()
        allowance = cfg.energy_roundoff_relative * max(abs(before_energy), 1.0)
        if forcing is not None or after_energy <= before_energy + allowance:
            accepted_state = projected
            accepted_scale = scale
            max_displacement = max(
                (
                    _norm(_sub(after, before))
                    for after, before in zip(projected.positions, state.positions)
                ),
                default=0.0,
            )
            break

    if accepted_state is None:
        raise RuntimeError("network timestep line search stalled")

    diag = diagnostics(accepted_state, accepted_scale, max_displacement)
    accepted_state = replace(accepted_state, pressures_pa=diag.pressures_pa)
    return accepted_state, diag


def run_steps(
    state: TransientNetworkState,
    steps: int,
    settings: NetworkStepperSettings | None = None,
    forcing: ForcingHook | None = None,
) -> tuple[TransientNetworkState, tuple[NetworkStepDiagnostics, ...]]:
    if steps < 0:
        raise ValueError("steps must be non-negative")
    history = []
    current = state
    for _ in range(steps):
        current, diag = advance(current, settings=settings, forcing=forcing)
        history.append(diag)
    return current, tuple(history)
