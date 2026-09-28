"""Conservative face finite-volume transport on a triangulated soap-film sheet.

Film thickness is a lower-dimensional field h [m] carried by the tracked surface.
It is not a volumetrically resolved liquid layer.  The conserved liquid proxy is
integral(h dA).  Surfactant concentration Gamma [mol/m^2] is stored with the
conserved integral integral(Gamma dA).

For an internal face edge i->j the lubrication flux is

    q = L_e [ -h^3/(3 mu) grad_s(p)
              + rho h^3/(3 mu) g_t
              + h^2/(2 mu) grad_s(sigma) ] + q_adv,

where L_e is shared-edge length.  Pressure may contain capillary and optional
disjoining-pressure contributions.  Equal and opposite edge fluxes make the
scheme conservative by construction.

The linearized equation of state is
    sigma = max(sigma_min, sigma_clean - elasticity * Gamma).
"""
from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Sequence

Vec3 = tuple[float, float, float]
Face = tuple[int, int, int]


def _add(a: Vec3, b: Vec3) -> Vec3:
    return (a[0] + b[0], a[1] + b[1], a[2] + b[2])


def _sub(a: Vec3, b: Vec3) -> Vec3:
    return (a[0] - b[0], a[1] - b[1], a[2] - b[2])


def _mul(a: Vec3, s: float) -> Vec3:
    return (a[0] * s, a[1] * s, a[2] * s)


def _dot(a: Vec3, b: Vec3) -> float:
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def _cross(a: Vec3, b: Vec3) -> Vec3:
    return (
        a[1] * b[2] - a[2] * b[1],
        a[2] * b[0] - a[0] * b[2],
        a[0] * b[1] - a[1] * b[0],
    )


def _norm(a: Vec3) -> float:
    return math.sqrt(_dot(a, a))


def _unit(a: Vec3) -> Vec3:
    n = _norm(a)
    return (0.0, 0.0, 0.0) if n == 0.0 else _mul(a, 1.0 / n)


@dataclass(frozen=True)
class EdgeLink:
    face_i: int
    face_j: int
    edge_length_m: float
    center_distance_m: float
    direction_i_to_j: Vec3


@dataclass(frozen=True)
class SurfaceMesh:
    """Triangular surface geometry used by the reduced-order transport model."""

    vertices_m: tuple[Vec3, ...]
    faces: tuple[Face, ...]
    mesh_id: str = "thinfilm-mesh"
    film_id: str = "thinfilm-film"

    def __post_init__(self) -> None:
        if not self.vertices_m or not self.faces:
            raise ValueError("surface mesh requires vertices and faces")
        n = len(self.vertices_m)
        for face in self.faces:
            if len(set(face)) != 3 or any(index < 0 or index >= n for index in face):
                raise ValueError("invalid triangular face")
            if self.face_area_m2(face) <= 0.0:
                raise ValueError("surface mesh contains a degenerate face")

    def face_area_m2(self, face: Face) -> float:
        a, b, c = (self.vertices_m[index] for index in face)
        return 0.5 * _norm(_cross(_sub(b, a), _sub(c, a)))

    def face_centroid_m(self, face: Face) -> Vec3:
        a, b, c = (self.vertices_m[index] for index in face)
        return _mul(_add(_add(a, b), c), 1.0 / 3.0)

    def face_areas_m2(self) -> tuple[float, ...]:
        return tuple(self.face_area_m2(face) for face in self.faces)

    def face_centroids_m(self) -> tuple[Vec3, ...]:
        return tuple(self.face_centroid_m(face) for face in self.faces)

    def internal_links(self) -> tuple[EdgeLink, ...]:
        owners: dict[tuple[int, int], list[int]] = {}
        for face_index, face in enumerate(self.faces):
            for a, b in ((face[0], face[1]), (face[1], face[2]), (face[2], face[0])):
                edge = (a, b) if a < b else (b, a)
                owners.setdefault(edge, []).append(face_index)

        centers = self.face_centroids_m()
        links: list[EdgeLink] = []
        for edge, incident in sorted(owners.items()):
            if len(incident) != 2:
                continue
            i, j = sorted(incident)
            edge_length = _norm(_sub(self.vertices_m[edge[1]], self.vertices_m[edge[0]]))
            delta = _sub(centers[j], centers[i])
            distance = _norm(delta)
            if edge_length <= 0.0 or distance <= 0.0:
                continue
            links.append(
                EdgeLink(
                    face_i=i,
                    face_j=j,
                    edge_length_m=edge_length,
                    center_distance_m=distance,
                    direction_i_to_j=_unit(delta),
                )
            )
        return tuple(links)


@dataclass(frozen=True)
class SurfaceTransportParameters:
    """Physical and numerical parameters in SI units."""

    dynamic_viscosity_pa_s: float = 1.0e-3
    liquid_density_kg_m3: float = 1000.0
    gravity_m_s2: Vec3 = (0.0, -9.81, 0.0)
    surfactant_diffusivity_m2_s: float = 1.0e-9
    clean_surface_tension_n_m: float = 0.050
    surface_elasticity_n_m_per_mol_m2: float = 2.0e3
    minimum_surface_tension_n_m: float = 0.020
    disjoining_coefficient_pa_m3: float = 0.0
    positivity_safety: float = 0.45
    max_substeps: int = 10000

    def __post_init__(self) -> None:
        if self.dynamic_viscosity_pa_s <= 0.0:
            raise ValueError("dynamic viscosity must be positive")
        if self.liquid_density_kg_m3 < 0.0:
            raise ValueError("liquid density must be non-negative")
        if self.surfactant_diffusivity_m2_s < 0.0:
            raise ValueError("surfactant diffusivity must be non-negative")
        if self.clean_surface_tension_n_m <= 0.0:
            raise ValueError("clean surface tension must be positive")
        if self.minimum_surface_tension_n_m <= 0.0:
            raise ValueError("minimum surface tension must be positive")
        if self.surface_elasticity_n_m_per_mol_m2 < 0.0:
            raise ValueError("surface elasticity must be non-negative")
        if not 0.0 < self.positivity_safety < 1.0:
            raise ValueError("positivity_safety must lie in (0, 1)")
        if self.max_substeps < 1:
            raise ValueError("max_substeps must be positive")


@dataclass(frozen=True)
class SurfaceStepDiagnostics:
    requested_dt_s: float
    substeps: int
    positivity_limited_steps: int
    minimum_substep_s: float
    min_thickness_m: float
    max_thickness_m: float
    liquid_amount_m3: float
    surfactant_amount_mol: float
    liquid_relative_drift: float
    surfactant_relative_drift: float
    roundoff_corrections: int


class SurfaceTransportState:
    """Face-centered thin-film/surfactant state with conservative edge fluxes."""

    def __init__(
        self,
        mesh: SurfaceMesh,
        thickness_m: Sequence[float],
        surfactant_mol_m2: Sequence[float],
        *,
        parameters: SurfaceTransportParameters | None = None,
        capillary_pressure_pa: Sequence[float] | None = None,
    ) -> None:
        self.mesh = mesh
        self.parameters = parameters or SurfaceTransportParameters()
        self.thickness_m = [float(value) for value in thickness_m]
        self.surfactant_mol_m2 = [float(value) for value in surfactant_mol_m2]
        count = len(mesh.faces)
        if len(self.thickness_m) != count or len(self.surfactant_mol_m2) != count:
            raise ValueError("surface fields must have one value per face")
        if any(value < 0.0 for value in self.thickness_m):
            raise ValueError("film thickness must be non-negative")
        if any(value < 0.0 for value in self.surfactant_mol_m2):
            raise ValueError("surfactant concentration must be non-negative")
        self.capillary_pressure_pa = (
            [0.0] * count
            if capillary_pressure_pa is None
            else [float(value) for value in capillary_pressure_pa]
        )
        if len(self.capillary_pressure_pa) != count:
            raise ValueError("capillary pressure must have one value per face")
        self._areas = list(mesh.face_areas_m2())
        self._links = mesh.internal_links()

    @classmethod
    def uniform(
        cls,
        mesh: SurfaceMesh,
        *,
        thickness_m: float,
        surfactant_mol_m2: float = 0.0,
        parameters: SurfaceTransportParameters | None = None,
    ) -> "SurfaceTransportState":
        if thickness_m < 0.0 or surfactant_mol_m2 < 0.0:
            raise ValueError("uniform fields must be non-negative")
        return cls(
            mesh,
            [thickness_m] * len(mesh.faces),
            [surfactant_mol_m2] * len(mesh.faces),
            parameters=parameters,
        )

    def clone(self) -> "SurfaceTransportState":
        return SurfaceTransportState(
            self.mesh,
            list(self.thickness_m),
            list(self.surfactant_mol_m2),
            parameters=self.parameters,
            capillary_pressure_pa=list(self.capillary_pressure_pa),
        )

    def liquid_amount_m3(self) -> float:
        return math.fsum(value * area for value, area in zip(self.thickness_m, self._areas))

    def surfactant_amount_mol(self) -> float:
        return math.fsum(value * area for value, area in zip(self.surfactant_mol_m2, self._areas))

    def surface_tension_n_m(self) -> tuple[float, ...]:
        p = self.parameters
        return tuple(
            max(
                p.minimum_surface_tension_n_m,
                p.clean_surface_tension_n_m
                - p.surface_elasticity_n_m_per_mol_m2 * gamma,
            )
            for gamma in self.surfactant_mol_m2
        )

    def disjoining_pressure_pa(self) -> tuple[float, ...]:
        coefficient = self.parameters.disjoining_coefficient_pa_m3
        values = []
        for h in self.thickness_m:
            if coefficient == 0.0:
                values.append(0.0)
            else:
                values.append(coefficient / max(h, 1.0e-12) ** 3)
        return tuple(values)

    def marangoni_gradient_n_m2(self) -> tuple[Vec3, ...]:
        """Approximate grad_s(sigma), pointing from lower toward higher sigma."""

        sigma = self.surface_tension_n_m()
        accum = [(0.0, 0.0, 0.0) for _ in self.mesh.faces]
        weight = [0.0 for _ in self.mesh.faces]
        for link in self._links:
            grad = (sigma[link.face_j] - sigma[link.face_i]) / link.center_distance_m
            contribution = _mul(link.direction_i_to_j, grad)
            i, j = link.face_i, link.face_j
            accum[i] = _add(accum[i], contribution)
            accum[j] = _add(accum[j], contribution)
            weight[i] += 1.0
            weight[j] += 1.0
        return tuple(
            _mul(value, 1.0 / weight[index]) if weight[index] > 0.0 else (0.0, 0.0, 0.0)
            for index, value in enumerate(accum)
        )

    def _fluxes(
        self,
        face_velocity_m_s: Sequence[Vec3] | None,
    ) -> tuple[list[tuple[int, int, float]], list[tuple[int, int, float]]]:
        p = self.parameters
        sigma = self.surface_tension_n_m()
        disjoining = self.disjoining_pressure_pa()
        pressure = [
            capillary + disjoin
            for capillary, disjoin in zip(self.capillary_pressure_pa, disjoining)
        ]
        velocities = None if face_velocity_m_s is None else list(face_velocity_m_s)
        if velocities is not None and len(velocities) != len(self.mesh.faces):
            raise ValueError("face velocity must have one vector per face")

        liquid_fluxes: list[tuple[int, int, float]] = []
        surfactant_fluxes: list[tuple[int, int, float]] = []

        for link in self._links:
            i, j = link.face_i, link.face_j
            distance = link.center_distance_m
            edge_length = link.edge_length_m
            hbar = 0.5 * (self.thickness_m[i] + self.thickness_m[j])
            grad_p = (pressure[j] - pressure[i]) / distance
            grad_sigma = (sigma[j] - sigma[i]) / distance
            gravity_tangent = _dot(p.gravity_m_s2, link.direction_i_to_j)

            mobility = hbar ** 3 / (3.0 * p.dynamic_viscosity_pa_s)
            marangoni_mobility = hbar ** 2 / (2.0 * p.dynamic_viscosity_pa_s)
            q = edge_length * (
                -mobility * grad_p
                + p.liquid_density_kg_m3 * mobility * gravity_tangent
                + marangoni_mobility * grad_sigma
            )

            advective_speed = 0.0
            if velocities is not None:
                averaged = _mul(_add(velocities[i], velocities[j]), 0.5)
                advective_speed = _dot(averaged, link.direction_i_to_j)
                donor_h = self.thickness_m[i] if advective_speed >= 0.0 else self.thickness_m[j]
                q += donor_h * advective_speed * edge_length

            if q > 0.0 and self.thickness_m[i] <= 0.0:
                q = 0.0
            elif q < 0.0 and self.thickness_m[j] <= 0.0:
                q = 0.0
            liquid_fluxes.append((i, j, q))

            gamma_gradient = (
                self.surfactant_mol_m2[j] - self.surfactant_mol_m2[i]
            ) / distance
            gamma_flux = (
                -p.surfactant_diffusivity_m2_s * gamma_gradient * edge_length
            )
            if velocities is not None:
                donor_gamma = (
                    self.surfactant_mol_m2[i]
                    if advective_speed >= 0.0
                    else self.surfactant_mol_m2[j]
                )
                gamma_flux += donor_gamma * advective_speed * edge_length
            if gamma_flux > 0.0 and self.surfactant_mol_m2[i] <= 0.0:
                gamma_flux = 0.0
            elif gamma_flux < 0.0 and self.surfactant_mol_m2[j] <= 0.0:
                gamma_flux = 0.0
            surfactant_fluxes.append((i, j, gamma_flux))

        return liquid_fluxes, surfactant_fluxes

    @staticmethod
    def _outgoing(
        count: int,
        fluxes: Sequence[tuple[int, int, float]],
    ) -> list[float]:
        outgoing = [0.0] * count
        for i, j, flux in fluxes:
            if flux > 0.0:
                outgoing[i] += flux
            elif flux < 0.0:
                outgoing[j] += -flux
        return outgoing

    def stable_timestep_s(
        self,
        face_velocity_m_s: Sequence[Vec3] | None = None,
    ) -> float:
        liquid_fluxes, surfactant_fluxes = self._fluxes(face_velocity_m_s)
        liquid_amounts = [
            h * area for h, area in zip(self.thickness_m, self._areas)
        ]
        surfactant_amounts = [
            gamma * area
            for gamma, area in zip(self.surfactant_mol_m2, self._areas)
        ]
        outgoing_liquid = self._outgoing(len(self.mesh.faces), liquid_fluxes)
        outgoing_surfactant = self._outgoing(len(self.mesh.faces), surfactant_fluxes)
        bounds: list[float] = []
        safety = self.parameters.positivity_safety
        for amount, outgoing in zip(liquid_amounts, outgoing_liquid):
            if outgoing > 0.0:
                bounds.append(safety * amount / outgoing)
        for amount, outgoing in zip(surfactant_amounts, outgoing_surfactant):
            if outgoing > 0.0:
                bounds.append(safety * amount / outgoing)
        return min(bounds) if bounds else math.inf

    def advance(
        self,
        dt_s: float,
        *,
        face_velocity_m_s: Sequence[Vec3] | None = None,
    ) -> SurfaceStepDiagnostics:
        """Advance one explicit step with conservative donor-based flux limiting.

        stable_timestep_s() exposes the unrestricted explicit positivity bound.
        advance() also accepts larger requested steps: when necessary it scales all
        outgoing edge fluxes from a donor face by the same deterministic factor so
        no face exports more than positivity_safety of its available amount.  This
        avoids a Zeno sequence of ever-smaller substeps near a dry face while
        retaining equal-and-opposite transfers and reporting that limiting occurred.
        """

        if dt_s <= 0.0:
            raise ValueError("dt_s must be positive")
        initial_liquid = self.liquid_amount_m3()
        initial_surfactant = self.surfactant_amount_mol()
        liquid_fluxes, surfactant_fluxes = self._fluxes(face_velocity_m_s)
        liquid_amounts = [
            h * area for h, area in zip(self.thickness_m, self._areas)
        ]
        surfactant_amounts = [
            gamma * area
            for gamma, area in zip(self.surfactant_mol_m2, self._areas)
        ]

        def limited_fluxes(
            amounts: Sequence[float],
            fluxes: Sequence[tuple[int, int, float]],
        ) -> tuple[list[tuple[int, int, float]], bool]:
            outgoing = self._outgoing(len(self.mesh.faces), fluxes)
            factors = [1.0] * len(self.mesh.faces)
            safety = self.parameters.positivity_safety
            limited_here = False
            for index, (amount, rate) in enumerate(zip(amounts, outgoing)):
                requested = rate * dt_s
                if requested > safety * amount and requested > 0.0:
                    factors[index] = max(0.0, safety * amount / requested)
                    limited_here = True

            result: list[tuple[int, int, float]] = []
            for i, j, flux in fluxes:
                if flux > 0.0:
                    flux *= factors[i]
                elif flux < 0.0:
                    flux *= factors[j]
                result.append((i, j, flux))
            return result, limited_here

        liquid_fluxes, liquid_limited = limited_fluxes(
            liquid_amounts,
            liquid_fluxes,
        )
        surfactant_fluxes, surfactant_limited = limited_fluxes(
            surfactant_amounts,
            surfactant_fluxes,
        )

        for i, j, flux in liquid_fluxes:
            transfer = flux * dt_s
            liquid_amounts[i] -= transfer
            liquid_amounts[j] += transfer
        for i, j, flux in surfactant_fluxes:
            transfer = flux * dt_s
            surfactant_amounts[i] -= transfer
            surfactant_amounts[j] += transfer

        corrections = 0
        for index, amount in enumerate(liquid_amounts):
            tolerance = 2.0e-15 * max(abs(initial_liquid), 1.0e-300)
            if amount < -tolerance:
                raise RuntimeError("film-thickness update violated positivity")
            if amount < 0.0:
                liquid_amounts[index] = 0.0
                corrections += 1
        for index, amount in enumerate(surfactant_amounts):
            tolerance = 2.0e-15 * max(abs(initial_surfactant), 1.0e-300)
            if amount < -tolerance:
                raise RuntimeError("surfactant update violated positivity")
            if amount < 0.0:
                surfactant_amounts[index] = 0.0
                corrections += 1

        self.thickness_m = [
            amount / area for amount, area in zip(liquid_amounts, self._areas)
        ]
        self.surfactant_mol_m2 = [
            amount / area
            for amount, area in zip(surfactant_amounts, self._areas)
        ]

        liquid = self.liquid_amount_m3()
        surfactant = self.surfactant_amount_mol()
        return SurfaceStepDiagnostics(
            requested_dt_s=dt_s,
            substeps=1,
            positivity_limited_steps=int(liquid_limited or surfactant_limited),
            minimum_substep_s=dt_s,
            min_thickness_m=min(self.thickness_m),
            max_thickness_m=max(self.thickness_m),
            liquid_amount_m3=liquid,
            surfactant_amount_mol=surfactant,
            liquid_relative_drift=abs(liquid - initial_liquid) / max(abs(initial_liquid), 1.0e-300),
            surfactant_relative_drift=abs(surfactant - initial_surfactant)
            / max(abs(initial_surfactant), 1.0e-300),
            roundoff_corrections=corrections,
        )
