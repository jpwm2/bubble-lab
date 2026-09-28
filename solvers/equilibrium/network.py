"""Coupled multi-region surface-energy primitives for equilibrium film networks."""
from __future__ import annotations

from dataclasses import dataclass
import math
import statistics

from .energy import area_gradient, volume_gradient
from .mesh import SurfaceMesh
from .vector import Vec3, add, dot, norm, scale, sub, unit

EXTERIOR = "EXTERIOR"
_ZERO: Vec3 = (0.0, 0.0, 0.0)


@dataclass(frozen=True)
class GasRegion:
    id: str
    target_volume_m3: float


@dataclass(frozen=True)
class FilmPatch:
    """One physical film sheet.

    Face orientation points from adjacent[0] toward adjacent[1].  A shared sheet is
    stored once, so its oriented volume contribution enters the two gas regions with
    opposite signs.
    """

    id: str
    mesh: SurfaceMesh
    adjacent: tuple[str, str]
    sheet_tension_n_m: float
    fixed_vertex_indices: tuple[int, ...] = ()
    # False is reserved for open far-field test-cell sheets whose gas-volume
    # closure is represented by separate closed patches.
    contributes_to_volume: bool = True

    def validate(self) -> None:
        if self.adjacent[0] == self.adjacent[1]:
            raise ValueError("film adjacency must contain two distinct regions")
        if self.sheet_tension_n_m <= 0.0:
            raise ValueError("sheet tension must be positive")
        self.mesh.validate(require_closed=False, require_outward=False)
        if len(set(self.fixed_vertex_indices)) != len(self.fixed_vertex_indices):
            raise ValueError("fixed vertex indices must be unique")
        if any(index < 0 or index >= len(self.mesh.vertices) for index in self.fixed_vertex_indices):
            raise ValueError("fixed vertex index is outside the patch mesh")


@dataclass(frozen=True)
class PlateauJunction:
    """Explicit triple-line topology shared by exactly three film sheets."""

    id: str
    incident_film_ids: tuple[str, str, str]
    vertex_indices_by_film: tuple[tuple[int, ...], tuple[int, ...], tuple[int, ...]]
    normal_plane_only: bool = True
    rigid_normal_translation: bool = False

    def validate(self, patches_by_id: dict[str, FilmPatch]) -> None:
        if not self.id:
            raise ValueError("junction ID must be non-empty")
        if len(set(self.incident_film_ids)) != 3:
            raise ValueError("Plateau junction must reference exactly three distinct films")
        counts = {len(indices) for indices in self.vertex_indices_by_film}
        if len(self.vertex_indices_by_film) != 3 or len(counts) != 1 or next(iter(counts), 0) < 2:
            raise ValueError("junction vertex lists must have the same length >= 2")
        for film_id, indices in zip(self.incident_film_ids, self.vertex_indices_by_film):
            if film_id not in patches_by_id:
                raise ValueError(f"junction {self.id!r} references unknown film {film_id!r}")
            patch = patches_by_id[film_id]
            if len(set(indices)) != len(indices):
                raise ValueError("junction vertex indices must be unique within each film")
            if any(index < 0 or index >= len(patch.mesh.vertices) for index in indices):
                raise ValueError("junction vertex index lies outside an incident film mesh")
        count = len(self.vertex_indices_by_film[0])
        reference_patch = patches_by_id[self.incident_film_ids[0]]
        for sample in range(count):
            reference = reference_patch.mesh.vertices[self.vertex_indices_by_film[0][sample]]
            for film_id, indices in zip(self.incident_film_ids[1:], self.vertex_indices_by_film[1:]):
                candidate = patches_by_id[film_id].mesh.vertices[indices[sample]]
                if norm(sub(candidate, reference)) > 1.0e-12:
                    raise ValueError("incident film copies of a junction vertex must be coincident")


@dataclass(frozen=True)
class FilmNetwork:
    regions: tuple[GasRegion, ...]
    patches: tuple[FilmPatch, ...]
    junctions: tuple[PlateauJunction, ...] = ()

    def validate(self) -> None:
        region_ids = [region.id for region in self.regions]
        if not region_ids or len(set(region_ids)) != len(region_ids) or EXTERIOR in region_ids:
            raise ValueError("gas-region IDs must be unique and may not use EXTERIOR")
        if any(region.target_volume_m3 <= 0.0 for region in self.regions):
            raise ValueError("all target gas volumes must be positive")
        patch_ids = [patch.id for patch in self.patches]
        if len(set(patch_ids)) != len(patch_ids):
            raise ValueError("film-patch IDs must be unique")
        allowed = set(region_ids) | {EXTERIOR}
        for patch in self.patches:
            patch.validate()
            if not set(patch.adjacent).issubset(allowed):
                raise ValueError(f"patch {patch.id!r} references an unknown region")
        junction_ids = [junction.id for junction in self.junctions]
        if len(set(junction_ids)) != len(junction_ids):
            raise ValueError("junction IDs must be unique")
        patches_by_id = {patch.id: patch for patch in self.patches}
        for junction in self.junctions:
            junction.validate(patches_by_id)

    def region_volume(self, region_id: str) -> float:
        if region_id not in {region.id for region in self.regions}:
            raise KeyError(region_id)
        total = 0.0
        for patch in self.patches:
            if not patch.contributes_to_volume:
                continue
            sign = 1.0 if patch.adjacent[0] == region_id else -1.0 if patch.adjacent[1] == region_id else 0.0
            total += sign * patch.mesh.signed_volume()
        return total

    def region_centroid(self, region_id: str) -> Vec3:
        """Volume centroid assembled from the oriented patch tetrahedra."""
        volume = self.region_volume(region_id)
        if volume <= 0.0:
            raise ValueError("region centroid requires positive closed-network volume")
        moment = [0.0, 0.0, 0.0]
        for patch in self.patches:
            if not patch.contributes_to_volume:
                continue
            sign = 1.0 if patch.adjacent[0] == region_id else -1.0 if patch.adjacent[1] == region_id else 0.0
            if sign == 0.0:
                continue
            for ia, ib, ic in patch.mesh.faces:
                a, b, c = patch.mesh.vertices[ia], patch.mesh.vertices[ib], patch.mesh.vertices[ic]
                tetra_volume = sign * dot(a, (
                    b[1] * c[2] - b[2] * c[1],
                    b[2] * c[0] - b[0] * c[2],
                    b[0] * c[1] - b[1] * c[0],
                )) / 6.0
                tetra_centroid = (
                    0.25 * (a[0] + b[0] + c[0]),
                    0.25 * (a[1] + b[1] + c[1]),
                    0.25 * (a[2] + b[2] + c[2]),
                )
                for axis in range(3):
                    moment[axis] += tetra_volume * tetra_centroid[axis]
        return (moment[0] / volume, moment[1] / volume, moment[2] / volume)

    def surface_energy_j(self) -> float:
        return sum(patch.sheet_tension_n_m * patch.mesh.area() for patch in self.patches)

    def with_patch_vertices(self, vertices_by_patch: dict[str, tuple[Vec3, ...]]) -> "FilmNetwork":
        patches = []
        for patch in self.patches:
            vertices = vertices_by_patch.get(patch.id, patch.mesh.vertices)
            patches.append(FilmPatch(
                id=patch.id,
                mesh=patch.mesh.with_vertices(vertices),
                adjacent=patch.adjacent,
                sheet_tension_n_m=patch.sheet_tension_n_m,
                fixed_vertex_indices=patch.fixed_vertex_indices,
                contributes_to_volume=patch.contributes_to_volume,
            ))

        mutable = {patch.id: list(patch.mesh.vertices) for patch in patches}
        for junction in self.junctions:
            for sample in range(len(junction.vertex_indices_by_film[0])):
                positions = [
                    mutable[film_id][indices[sample]]
                    for film_id, indices in zip(junction.incident_film_ids, junction.vertex_indices_by_film)
                ]
                common = tuple(sum(position[axis] for position in positions) / 3.0 for axis in range(3))
                for film_id, indices in zip(junction.incident_film_ids, junction.vertex_indices_by_film):
                    mutable[film_id][indices[sample]] = common

        reconciled = []
        for patch in patches:
            reconciled.append(FilmPatch(
                id=patch.id,
                mesh=patch.mesh.with_vertices(mutable[patch.id]),
                adjacent=patch.adjacent,
                sheet_tension_n_m=patch.sheet_tension_n_m,
                fixed_vertex_indices=patch.fixed_vertex_indices,
                contributes_to_volume=patch.contributes_to_volume,
            ))
        return FilmNetwork(self.regions, tuple(reconciled), self.junctions)


GradientField = tuple[tuple[Vec3, ...], ...]


def _junction_tangent(network: FilmNetwork, junction: PlateauJunction, sample: int) -> Vec3:
    patch_by_id = {patch.id: patch for patch in network.patches}
    indices = junction.vertex_indices_by_film[0]
    vertices = patch_by_id[junction.incident_film_ids[0]].mesh.vertices
    if sample == 0:
        direction = sub(vertices[indices[1]], vertices[indices[0]])
    elif sample == len(indices) - 1:
        direction = sub(vertices[indices[-1]], vertices[indices[-2]])
    else:
        direction = sub(vertices[indices[sample + 1]], vertices[indices[sample - 1]])
    return unit(direction)


def _normal_plane_component(value: Vec3, tangent: Vec3) -> Vec3:
    return sub(value, scale(tangent, dot(value, tangent)))


def _share_junction_dofs(network: FilmNetwork, field: GradientField) -> GradientField:
    """Project patch-local vectors onto the declared common triple-line DOFs."""
    values = [list(patch_values) for patch_values in field]
    patch_index = {patch.id: index for index, patch in enumerate(network.patches)}
    patch_by_id = {patch.id: patch for patch in network.patches}

    for junction in network.junctions:
        count = len(junction.vertex_indices_by_film[0])
        if junction.rigid_normal_translation:
            entries = [
                (patch_index[film_id], vertex_index)
                for film_id, indices in zip(junction.incident_film_ids, junction.vertex_indices_by_film)
                for vertex_index in indices
            ]
            blocked = any(
                vertex_index in set(network.patches[pindex].fixed_vertex_indices)
                for pindex, vertex_index in entries
            )
            if blocked:
                shared = _ZERO
            else:
                shared = tuple(
                    sum(values[pindex][vertex_index][axis] for pindex, vertex_index in entries) / len(entries)
                    for axis in range(3)
                )
                if junction.normal_plane_only:
                    shared = _normal_plane_component(shared, _junction_tangent(network, junction, count // 2))
            for pindex, vertex_index in entries:
                values[pindex][vertex_index] = shared
            continue

        for sample in range(count):
            entries = [
                (patch_index[film_id], indices[sample])
                for film_id, indices in zip(junction.incident_film_ids, junction.vertex_indices_by_film)
            ]
            blocked = any(
                vertex_index in set(patch_by_id[film_id].fixed_vertex_indices)
                for film_id, indices in zip(junction.incident_film_ids, junction.vertex_indices_by_film)
                for vertex_index in (indices[sample],)
            )
            if blocked:
                shared = _ZERO
            else:
                shared = tuple(
                    sum(values[pindex][vertex_index][axis] for pindex, vertex_index in entries) / 3.0
                    for axis in range(3)
                )
                if junction.normal_plane_only:
                    shared = _normal_plane_component(shared, _junction_tangent(network, junction, sample))
            for pindex, vertex_index in entries:
                values[pindex][vertex_index] = shared
    return tuple(tuple(patch_values) for patch_values in values)


def _junction_conormal(network: FilmNetwork, junction: PlateauJunction, film_position: int, sample: int) -> Vec3:
    film_id = junction.incident_film_ids[film_position]
    indices = junction.vertex_indices_by_film[film_position]
    patch = next(patch for patch in network.patches if patch.id == film_id)
    vertex_index = indices[sample]
    vertex = patch.mesh.vertices[vertex_index]
    tangent = _junction_tangent(network, junction, sample)
    line_indices = set(indices)
    neighbors: set[int] = set()
    for face in patch.mesh.faces:
        if vertex_index in face:
            neighbors.update(index for index in face if index not in line_indices)
    directions = []
    for neighbor in sorted(neighbors):
        direction = _normal_plane_component(sub(patch.mesh.vertices[neighbor], vertex), tangent)
        if norm(direction) > 1.0e-15:
            directions.append(unit(direction))
    if not directions:
        raise ValueError(f"junction {junction.id!r} has degenerate co-normal geometry")
    return unit(tuple(sum(direction[axis] for direction in directions) for axis in range(3)))


def junction_geometry_diagnostics(
    network: FilmNetwork,
    junction_id: str,
    *,
    central_fraction: float = 0.60,
) -> dict[str, object]:
    """Measure pairwise film angles and Neumann force balance from solved geometry."""
    if not (0.0 < central_fraction <= 1.0):
        raise ValueError("central_fraction must lie in (0, 1]")
    network.validate()
    junction = next((item for item in network.junctions if item.id == junction_id), None)
    if junction is None:
        raise KeyError(junction_id)
    patch_by_id = {patch.id: patch for patch in network.patches}
    tensions = [patch_by_id[film_id].sheet_tension_n_m for film_id in junction.incident_film_ids]
    count = len(junction.vertex_indices_by_film[0])
    edge_fraction = 0.5 * (1.0 - central_fraction)
    samples = [
        index for index in range(count)
        if edge_fraction <= index / max(count - 1, 1) <= 1.0 - edge_fraction
    ] or list(range(count))

    angles_by_sample = []
    force_residuals = []
    for sample in samples:
        conormals = tuple(_junction_conormal(network, junction, film, sample) for film in range(3))
        angles = []
        for left, right in ((0, 1), (1, 2), (2, 0)):
            cosine = min(1.0, max(-1.0, dot(conormals[left], conormals[right])))
            angles.append(math.degrees(math.acos(cosine)))
        force = _ZERO
        for tension, conormal in zip(tensions, conormals):
            force = add(force, scale(conormal, tension))
        angles_by_sample.append(tuple(angles))
        force_residuals.append(norm(force) / sum(tensions))
    return {
        "sample_indices": tuple(samples),
        "pairwise_angles_deg": tuple(angles_by_sample),
        "force_residuals": tuple(force_residuals),
        "max_force_residual": max(force_residuals),
        "mean_force_residual": sum(force_residuals) / len(force_residuals),
        "measurement": "co-normals projected from solved incident-triangle geometry",
    }


def max_junction_force_residual(network: FilmNetwork) -> float:
    return max(
        (float(junction_geometry_diagnostics(network, junction.id)["max_force_residual"]) for junction in network.junctions),
        default=0.0,
    )


def _masked(patch: FilmPatch, values: tuple[Vec3, ...]) -> tuple[Vec3, ...]:
    fixed = set(patch.fixed_vertex_indices)
    return tuple(_ZERO if index in fixed else value for index, value in enumerate(values))


def energy_gradient(network: FilmNetwork) -> GradientField:
    raw = tuple(
        _masked(patch, tuple(scale(value, patch.sheet_tension_n_m) for value in area_gradient(patch.mesh)))
        for patch in network.patches
    )
    return _share_junction_dofs(network, raw)


def region_volume_gradient(network: FilmNetwork, region_id: str) -> GradientField:
    gradients = []
    for patch in network.patches:
        sign = 0.0
        if patch.contributes_to_volume:
            sign = 1.0 if patch.adjacent[0] == region_id else -1.0 if patch.adjacent[1] == region_id else 0.0
        gradients.append(_masked(patch, tuple(scale(value, sign) for value in volume_gradient(patch.mesh))))
    return _share_junction_dofs(network, tuple(gradients))


def _field_dot(a: GradientField, b: GradientField) -> float:
    return sum(dot(va, vb) for pa, pb in zip(a, b) for va, vb in zip(pa, pb))


def _zeros(network: FilmNetwork) -> GradientField:
    return tuple(tuple(_ZERO for _ in patch.mesh.vertices) for patch in network.patches)


def _field_linear_combination(base: GradientField, fields: list[GradientField], coefficients: list[float]) -> GradientField:
    result = []
    for patch_index, base_patch in enumerate(base):
        values = []
        for vertex_index, base_value in enumerate(base_patch):
            value = base_value
            for field, coefficient in zip(fields, coefficients):
                value = add(value, scale(field[patch_index][vertex_index], coefficient))
            values.append(value)
        result.append(tuple(values))
    return tuple(result)


def _solve_linear(matrix: list[list[float]], rhs: list[float]) -> list[float]:
    n = len(rhs)
    augmented = [list(row) + [rhs[index]] for index, row in enumerate(matrix)]
    for column in range(n):
        pivot = max(range(column, n), key=lambda row: abs(augmented[row][column]))
        if abs(augmented[pivot][column]) <= 1.0e-30:
            raise ValueError("coupled volume constraints are singular")
        augmented[column], augmented[pivot] = augmented[pivot], augmented[column]
        divisor = augmented[column][column]
        for j in range(column, n + 1):
            augmented[column][j] /= divisor
        for row in range(n):
            if row == column:
                continue
            factor = augmented[row][column]
            for j in range(column, n + 1):
                augmented[row][j] -= factor * augmented[column][j]
    return [augmented[index][n] for index in range(n)]


def stationarity(network: FilmNetwork) -> tuple[dict[str, float], GradientField]:
    """Return one pressure multiplier per gas region and the projected energy gradient."""
    grad_energy = energy_gradient(network)
    grad_volumes = [region_volume_gradient(network, region.id) for region in network.regions]
    gram = [[_field_dot(left, right) for right in grad_volumes] for left in grad_volumes]
    rhs = [_field_dot(gradient, grad_energy) for gradient in grad_volumes]
    multipliers = _solve_linear(gram, rhs)
    residual = _field_linear_combination(grad_energy, grad_volumes, [-value for value in multipliers])
    return {region.id: multipliers[index] for index, region in enumerate(network.regions)}, residual


def _apply_field(network: FilmNetwork, field: GradientField, coefficient: float) -> FilmNetwork:
    vertices_by_patch = {}
    for patch, patch_field in zip(network.patches, field):
        vertices_by_patch[patch.id] = tuple(
            add(vertex, scale(direction, coefficient))
            for vertex, direction in zip(patch.mesh.vertices, patch_field)
        )
    return network.with_patch_vertices(vertices_by_patch)


def project_region_volumes(
    network: FilmNetwork,
    *,
    relative_tolerance: float = 1.0e-11,
    max_iterations: int = 16,
) -> FilmNetwork:
    """Coupled Newton projection onto every gas-volume constraint.

    The correction is a linear combination of all region-volume gradients.  No gas
    region is independently rescaled, which is essential when a shared film belongs
    to two constraints with opposite signs.
    """
    current = network
    for _ in range(max_iterations):
        errors = [region.target_volume_m3 - current.region_volume(region.id) for region in current.regions]
        relative = max(abs(error) / region.target_volume_m3 for error, region in zip(errors, current.regions))
        if relative <= relative_tolerance:
            return current
        gradients = [region_volume_gradient(current, region.id) for region in current.regions]
        gram = [[_field_dot(left, right) for right in gradients] for left in gradients]
        coefficients = _solve_linear(gram, errors)
        correction = _field_linear_combination(_zeros(current), gradients, coefficients)
        current = _apply_field(current, correction, 1.0)
    return current


@dataclass(frozen=True)
class NetworkSolverSettings:
    max_iterations: int = 300
    relative_volume_tolerance: float = 1.0e-10
    normalized_force_tolerance: float = 1.0e-3
    junction_force_tolerance: float = 5.0e-3
    initial_step_fraction: float = 0.08
    minimum_step_fraction: float = 1.0e-8
    max_backtracks: int = 24
    energy_roundoff_allowance: float = 1.0e-13


@dataclass(frozen=True)
class NetworkEquilibriumResult:
    network: FilmNetwork
    pressures_pa: dict[str, float]
    converged: bool
    termination_reason: str
    iterations: int
    relative_volume_residuals: dict[str, float]
    normalized_force_residual: float
    surface_energy_j: float
    initial_surface_energy_j: float
    energy_history_j: tuple[float, ...]
    junction_force_residuals: dict[str, float]


def _normalized_force(network: FilmNetwork, residual: GradientField) -> float:
    magnitudes = [norm(value) for patch_values in residual for value in patch_values]
    rms = math.sqrt(sum(value * value for value in magnitudes) / max(len(magnitudes), 1))
    edge_lengths = [length for patch in network.patches for length in patch.mesh.edge_lengths()]
    h = statistics.median(edge_lengths)
    tension = max(patch.sheet_tension_n_m for patch in network.patches)
    return rms / max(tension * h, 1.0e-30)


def solve_film_network(
    network: FilmNetwork,
    settings: NetworkSolverSettings | None = None,
) -> NetworkEquilibriumResult:
    """Minimize total film energy subject to all gas-region volume constraints."""
    cfg = settings or NetworkSolverSettings()
    network.validate()
    current = project_region_volumes(
        network,
        relative_tolerance=0.1 * cfg.relative_volume_tolerance,
    )
    initial_energy = current.surface_energy_j()
    energy_history = [initial_energy]
    converged = False
    termination = "maximum_iterations"
    iterations = 0

    for iteration in range(cfg.max_iterations + 1):
        iterations = iteration
        pressures, residual = stationarity(current)
        normalized_force = _normalized_force(current, residual)
        relative_volumes = {
            region.id: abs(current.region_volume(region.id) - region.target_volume_m3) / region.target_volume_m3
            for region in current.regions
        }
        junction_force = max_junction_force_residual(current)
        if (
            max(relative_volumes.values()) <= cfg.relative_volume_tolerance
            and normalized_force <= cfg.normalized_force_tolerance
            and junction_force <= cfg.junction_force_tolerance
        ):
            converged = True
            termination = "converged"
            break
        if iteration == cfg.max_iterations:
            break

        max_node_force = max(norm(value) for patch_values in residual for value in patch_values)
        if max_node_force <= 1.0e-30:
            termination = "stationary"
            break
        median_edge = statistics.median(
            length for patch in current.patches for length in patch.mesh.edge_lengths()
        )
        base_scale = cfg.initial_step_fraction * median_edge / max_node_force
        current_energy = energy_history[-1]
        fraction = cfg.initial_step_fraction
        accepted = False

        for _ in range(cfg.max_backtracks):
            trial = _apply_field(
                current,
                residual,
                -base_scale * (fraction / cfg.initial_step_fraction),
            )
            trial = project_region_volumes(
                trial,
                relative_tolerance=0.1 * cfg.relative_volume_tolerance,
            )
            try:
                trial.validate()
            except ValueError:
                fraction *= 0.5
                continue
            trial_energy = trial.surface_energy_j()
            allowance = cfg.energy_roundoff_allowance * max(abs(current_energy), 1.0)
            if trial_energy <= current_energy + allowance:
                current = trial
                energy_history.append(trial_energy)
                accepted = True
                break
            fraction *= 0.5
            if fraction < cfg.minimum_step_fraction:
                break

        if not accepted:
            termination = "line_search_stalled"
            break

    pressures, residual = stationarity(current)
    normalized_force = _normalized_force(current, residual)
    relative_volumes = {
        region.id: abs(current.region_volume(region.id) - region.target_volume_m3) / region.target_volume_m3
        for region in current.regions
    }
    junction_force_residuals = {
        junction.id: float(junction_geometry_diagnostics(current, junction.id)["max_force_residual"])
        for junction in current.junctions
    }
    if (
        max(relative_volumes.values()) <= cfg.relative_volume_tolerance
        and normalized_force <= cfg.normalized_force_tolerance
        and max(junction_force_residuals.values(), default=0.0) <= cfg.junction_force_tolerance
    ):
        converged = True
        termination = "converged"
    return NetworkEquilibriumResult(
        network=current,
        pressures_pa=pressures,
        converged=converged,
        termination_reason=termination,
        iterations=iterations,
        relative_volume_residuals=relative_volumes,
        normalized_force_residual=normalized_force,
        surface_energy_j=current.surface_energy_j(),
        initial_surface_energy_j=initial_energy,
        energy_history_j=tuple(energy_history),
        junction_force_residuals=junction_force_residuals,
    )
