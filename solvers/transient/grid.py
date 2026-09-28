"""Deterministic variable-property Eulerian reference grid for sharp film coupling."""
from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Iterable, Mapping

from .geometry import Vec3


@dataclass(frozen=True)
class RegionProperties:
    density_kg_m3: float
    dynamic_viscosity_pa_s: float

    def __post_init__(self) -> None:
        if self.density_kg_m3 <= 0.0:
            raise ValueError("region density must be positive")
        if self.dynamic_viscosity_pa_s < 0.0:
            raise ValueError("region viscosity must be non-negative")


@dataclass(frozen=True)
class GridConfig:
    cells: tuple[int, int, int] = (10, 10, 10)
    origin_m: Vec3 = (-0.025, -0.025, -0.025)
    extent_m: Vec3 = (0.05, 0.05, 0.05)
    density_kg_m3: float = 1.204
    dynamic_viscosity_pa_s: float = 1.825e-5
    background_velocity_m_s: Vec3 = (0.0, 0.0, 0.0)
    pressure_iterations: int = 240
    pressure_tolerance_s_inv: float = 2.0e-7


class EulerianGasGrid:
    """Periodic collocated grid with variable material properties and projection.

    Velocity components are stored at the positive faces of each logical cell.
    The backward divergence and forward gradient are paired. Variable-density
    projection uses face mobility beta=1/rho_face, where beta is the arithmetic
    mean of adjacent cell inverse densities (equivalent to harmonic rho).

    Constant-tension capillarity is coupled through a discontinuous cell pressure
    potential rather than cloud-in-cell force smearing. The exact same face
    gradient and mobility are used for the pressure-potential force and pressure
    correction, giving a balanced sharp one-cell jump for static interfaces.

    When SDF solids are configured, the periodic stencil is cut at fluid-solid
    intersections. Viscosity uses a Dirichlet no-slip wall value at the actual
    SDF crossing distance and pressure projection uses zero pressure-correction
    flux while preserving the declared wall-normal velocity.
    """

    def __init__(self, config: GridConfig):
        self.config = config
        nx, ny, nz = config.cells
        if min(nx, ny, nz) < 4:
            raise ValueError("each grid dimension must have at least four cells")
        if config.density_kg_m3 <= 0.0:
            raise ValueError("density must be positive")
        if config.dynamic_viscosity_pa_s < 0.0:
            raise ValueError("viscosity must be non-negative")
        self.nx, self.ny, self.nz = nx, ny, nz
        self.dx = config.extent_m[0] / nx
        self.dy = config.extent_m[1] / ny
        self.dz = config.extent_m[2] / nz
        if max(abs(self.dx - self.dy), abs(self.dx - self.dz)) > 1e-14:
            raise ValueError("reference grid currently requires cubic cells")
        self.h = self.dx
        n = nx * ny * nz
        self.u = [0.0] * n
        self.v = [0.0] * n
        self.w = [0.0] * n
        self.pressure = [0.0] * n
        self.region_labels = ["EXTERIOR"] * n
        self.density = [config.density_kg_m3] * n
        self.dynamic_viscosity = [config.dynamic_viscosity_pa_s] * n
        self.capillary_pressure_potential = [0.0] * n
        self.last_projection_iterations = 0
        self.last_projection_residual = 0.0
        self.last_gravity_m_s2: Vec3 = (0.0, 0.0, 0.0)
        self.hydrostatic_reference_density_kg_m3: float | None = None
        self._resolved_walls = None

    @property
    def resolved_walls(self):
        return self._resolved_walls

    def configure_solid_walls(self, boundaries) -> None:
        """Build resolved no-slip geometry from authoritative SDF boundaries."""
        ordered = tuple(boundaries)
        if not ordered:
            self._resolved_walls = None
            return
        from .wall import ResolvedNoSlipWallField

        self._resolved_walls = ResolvedNoSlipWallField(self, ordered)
        self.apply_solid_wall_constraints()

    def apply_solid_wall_constraints(self) -> None:
        if self._resolved_walls is not None:
            self._resolved_walls.enforce_velocity((self.u, self.v, self.w))

    def clone(self) -> "EulerianGasGrid":
        other = EulerianGasGrid(self.config)
        other.u = list(self.u)
        other.v = list(self.v)
        other.w = list(self.w)
        other.pressure = list(self.pressure)
        other.region_labels = list(self.region_labels)
        other.density = list(self.density)
        other.dynamic_viscosity = list(self.dynamic_viscosity)
        other.capillary_pressure_potential = list(self.capillary_pressure_potential)
        other.last_projection_iterations = self.last_projection_iterations
        other.last_projection_residual = self.last_projection_residual
        other.last_gravity_m_s2 = self.last_gravity_m_s2
        other.hydrostatic_reference_density_kg_m3 = self.hydrostatic_reference_density_kg_m3
        if self._resolved_walls is not None:
            other.configure_solid_walls(self._resolved_walls.boundaries)
        return other

    @property
    def cell_volume(self) -> float:
        return self.h ** 3

    def _idx(self, i: int, j: int, k: int) -> int:
        return ((k % self.nz) * self.ny + (j % self.ny)) * self.nx + (i % self.nx)

    def _ijk(self, q: int) -> tuple[int, int, int]:
        i = q % self.nx
        q //= self.nx
        j = q % self.ny
        k = q // self.ny
        return i, j, k

    def cell_center(self, i: int, j: int, k: int) -> Vec3:
        ox, oy, oz = self.config.origin_m
        return (
            ox + (i + 0.5) * self.h,
            oy + (j + 0.5) * self.h,
            oz + (k + 0.5) * self.h,
        )

    def _wrap_pos(self, p: Vec3) -> Vec3:
        out = []
        for x, origin, extent in zip(p, self.config.origin_m, self.config.extent_m):
            out.append(origin + ((x - origin) % extent))
        return (out[0], out[1], out[2])

    def _weights(self, p: Vec3):
        p = self._wrap_pos(p)
        rel = []
        for x, origin in zip(p, self.config.origin_m):
            rel.append((x - origin) / self.h - 0.5)
        bases = [math.floor(a) for a in rel]
        frac = [rel[d] - bases[d] for d in range(3)]
        for dk in (0, 1):
            wz = (1.0 - frac[2]) if dk == 0 else frac[2]
            k = bases[2] + dk
            for dj in (0, 1):
                wy = (1.0 - frac[1]) if dj == 0 else frac[1]
                j = bases[1] + dj
                for di in (0, 1):
                    wx = (1.0 - frac[0]) if di == 0 else frac[0]
                    i = bases[0] + di
                    yield self._idx(i, j, k), wx * wy * wz

    def sample_dynamic_velocity(self, p: Vec3, fields=None) -> Vec3:
        u, v, w = fields if fields is not None else (self.u, self.v, self.w)
        su = sv = sw = 0.0
        for q, weight in self._weights(p):
            su += weight * u[q]
            sv += weight * v[q]
            sw += weight * w[q]
        return (su, sv, sw)

    def sample_velocity(self, p: Vec3, fields=None) -> Vec3:
        dyn = self.sample_dynamic_velocity(p, fields)
        bg = self.config.background_velocity_m_s
        return (dyn[0] + bg[0], dyn[1] + bg[1], dyn[2] + bg[2])

    def configure_regions(
        self,
        labels: list[str],
        properties: Mapping[str, RegionProperties],
        capillary_pressure_pa: Mapping[str, float] | None = None,
    ) -> None:
        """Install cell region identity, material fields and sharp jump potential."""
        if len(labels) != len(self.u):
            raise ValueError("region label count must equal cell count")
        exterior = RegionProperties(
            self.config.density_kg_m3,
            self.config.dynamic_viscosity_pa_s,
        )
        props = {"EXTERIOR": exterior, **dict(properties)}
        for label in set(labels):
            if label not in props:
                raise ValueError(f"missing material properties for region {label!r}")
        jumps = dict(capillary_pressure_pa or {})
        self.region_labels = list(labels)
        self.density = [props[label].density_kg_m3 for label in labels]
        self.dynamic_viscosity = [props[label].dynamic_viscosity_pa_s for label in labels]
        self.capillary_pressure_potential = [jumps.get(label, 0.0) for label in labels]

    def spread_vertex_forces(self, points: Iterable[Vec3], forces: Iterable[Vec3]) -> tuple[list[float], list[float], list[float]]:
        """Legacy cloud-in-cell spread retained only for explicit diffuse comparisons."""
        n = self.nx * self.ny * self.nz
        fx = [0.0] * n
        fy = [0.0] * n
        fz = [0.0] * n
        inv_vol = 1.0 / self.cell_volume
        for p, force in zip(points, forces):
            for q, weight in self._weights(p):
                scale = weight * inv_vol
                fx[q] += force[0] * scale
                fy[q] += force[1] * scale
                fz[q] += force[2] * scale
        return fx, fy, fz

    def total_integrated_force(self, force_density) -> Vec3:
        fx, fy, fz = force_density
        vol = self.cell_volume
        return (sum(fx) * vol, sum(fy) * vol, sum(fz) * vol)

    def _face_neighbor(self, q: int, axis: int, offset: int = 1) -> int:
        i, j, k = self._ijk(q)
        if axis == 0:
            return self._idx(i + offset, j, k)
        if axis == 1:
            return self._idx(i, j + offset, k)
        return self._idx(i, j, k + offset)

    def _face_inv_density(self, q: int, axis: int) -> float:
        if self._resolved_walls is not None and self._resolved_walls.blocks_positive_face(q, axis):
            return 0.0
        r = self._face_neighbor(q, axis, 1)
        return 0.5 * (1.0 / self.density[q] + 1.0 / self.density[r])

    def _face_viscosity(self, q: int, axis: int, offset: int = 1) -> float:
        r = self._face_neighbor(q, axis, offset)
        a = self.dynamic_viscosity[q]
        b = self.dynamic_viscosity[r]
        if a == 0.0 or b == 0.0:
            return 0.0
        return 2.0 * a * b / (a + b)

    def divergence(self, fields=None) -> list[float]:
        u, v, w = fields if fields is not None else (self.u, self.v, self.w)
        inv_h = 1.0 / self.h
        out = [0.0] * len(u)
        wall = self._resolved_walls
        for q in range(len(u)):
            if wall is not None and wall.is_solid(q):
                continue
            i, j, k = self._ijk(q)
            out[q] = (
                u[q] - u[self._idx(i - 1, j, k)]
                + v[q] - v[self._idx(i, j - 1, k)]
                + w[q] - w[self._idx(i, j, k - 1)]
            ) * inv_h
        return out

    def divergence_linf(self) -> float:
        return max(abs(x) for x in self.divergence())

    def max_speed(self) -> float:
        bg = self.config.background_velocity_m_s
        best = 0.0
        for q, (u, v, w) in enumerate(zip(self.u, self.v, self.w)):
            if self._resolved_walls is not None and self._resolved_walls.is_solid(q):
                continue
            s = math.sqrt((u + bg[0]) ** 2 + (v + bg[1]) ** 2 + (w + bg[2]) ** 2)
            if s > best:
                best = s
        return best

    def kinetic_energy(self) -> float:
        bg = self.config.background_velocity_m_s
        e = 0.0
        for q, (rho, u, v, w) in enumerate(zip(self.density, self.u, self.v, self.w)):
            if self._resolved_walls is not None and self._resolved_walls.is_solid(q):
                continue
            e += 0.5 * rho * ((u + bg[0]) ** 2 + (v + bg[1]) ** 2 + (w + bg[2]) ** 2) * self.cell_volume
        return e

    def _advect_component(self, field: list[float], old_fields, dt: float, component_axis: int = 0) -> list[float]:
        out = [0.0] * len(field)
        wall = self._resolved_walls
        for q in range(len(field)):
            if wall is not None and wall.is_solid(q):
                out[q] = wall.dynamic_wall_velocity_for_cell(q)[component_axis]
                continue
            i, j, k = self._ijk(q)
            x = self.cell_center(i, j, k)
            vel = self.sample_velocity(x, old_fields)
            back = (x[0] - dt * vel[0], x[1] - dt * vel[1], x[2] - dt * vel[2])
            if wall is not None and wall.point_is_solid(back):
                out[q] = wall.dynamic_wall_velocity_at(back)[component_axis]
            else:
                out[q] = sum(weight * field[r] for r, weight in self._weights(back))
        return out

    def _variable_viscous_term(self, field: list[float], component_axis: int = 0) -> list[float]:
        wall = self._resolved_walls
        if wall is None:
            inv_h2 = 1.0 / (self.h * self.h)
            out = [0.0] * len(field)
            for q in range(len(field)):
                center = field[q]
                accum = 0.0
                for axis in range(3):
                    rp = self._face_neighbor(q, axis, 1)
                    rm = self._face_neighbor(q, axis, -1)
                    mu_p = self._face_viscosity(q, axis, 1)
                    mu_m = self._face_viscosity(rm, axis, 1)
                    accum += mu_p * (field[rp] - center) - mu_m * (center - field[rm])
                out[q] = accum * inv_h2 / self.density[q]
            return out

        out = [0.0] * len(field)
        h = self.h
        for q in wall.fluid_indices:
            center = field[q]
            accum = 0.0
            for axis in range(3):
                minus = wall.intersection(q, axis, -1)
                plus = wall.intersection(q, axis, 1)
                if minus is None:
                    rm = self._face_neighbor(q, axis, -1)
                    value_m = field[rm]
                    distance_m = h
                    mu_m = self._face_viscosity(rm, axis, 1)
                else:
                    value_m = minus.wall_velocity_dynamic_m_s[component_axis]
                    distance_m = minus.distance_fraction * h
                    mu_m = self.dynamic_viscosity[q]
                if plus is None:
                    rp = self._face_neighbor(q, axis, 1)
                    value_p = field[rp]
                    distance_p = h
                    mu_p = self._face_viscosity(q, axis, 1)
                else:
                    value_p = plus.wall_velocity_dynamic_m_s[component_axis]
                    distance_p = plus.distance_fraction * h
                    mu_p = self.dynamic_viscosity[q]
                accum += 2.0 / (distance_m + distance_p) * (
                    mu_p * (value_p - center) / distance_p
                    - mu_m * (center - value_m) / distance_m
                )
            out[q] = accum / self.density[q]
        return out

    def advect_and_diffuse(self, dt: float) -> tuple[list[float], list[float], list[float]]:
        old = (list(self.u), list(self.v), list(self.w))
        if self._resolved_walls is not None:
            self._resolved_walls.enforce_velocity(old)
        adv = [self._advect_component(component, old, dt, axis) for axis, component in enumerate(old)]
        if max(self.dynamic_viscosity, default=0.0) == 0.0:
            result = (adv[0], adv[1], adv[2])
            if self._resolved_walls is not None:
                self._resolved_walls.enforce_velocity(result)
            return result
        result = []
        for axis, component in enumerate(adv):
            visc = self._variable_viscous_term(component, axis)
            result.append([a + dt * d for a, d in zip(component, visc)])
        fields = (result[0], result[1], result[2])
        if self._resolved_walls is not None:
            self._resolved_walls.enforce_velocity(fields)
        return fields

    def _mobility_gradient(self, field: list[float]) -> tuple[list[float], list[float], list[float]]:
        inv_h = 1.0 / self.h
        gx = [0.0] * len(field)
        gy = [0.0] * len(field)
        gz = [0.0] * len(field)
        wall = self._resolved_walls
        for q in range(len(field)):
            if wall is not None and wall.is_solid(q):
                continue
            for axis, dest in ((0, gx), (1, gy), (2, gz)):
                mobility = self._face_inv_density(q, axis)
                if mobility == 0.0:
                    continue
                r = self._face_neighbor(q, axis, 1)
                dest[q] = mobility * (field[r] - field[q]) * inv_h
        return gx, gy, gz

    def _div_mobility_gradient(self, field: list[float]) -> list[float]:
        return self.divergence(self._mobility_gradient(field))

    def _project_with_walls(self, fields, dt: float) -> tuple[list[float], list[float], list[float]]:
        wall = self._resolved_walls
        if wall is None:
            raise RuntimeError("wall projection requires configured resolved walls")
        u, v, w = (list(fields[0]), list(fields[1]), list(fields[2]))
        wall.enforce_velocity((u, v, w))
        fluid = wall.fluid_indices
        div = self.divergence((u, v, w))
        b = [0.0] * len(div)
        for q in fluid:
            b[q] = -div[q] / dt
        mean_b = sum(b[q] for q in fluid) / len(fluid) if fluid else 0.0
        for q in fluid:
            b[q] -= mean_b

        def apply_a(x: list[float]) -> list[float]:
            div_beta_grad = self._div_mobility_gradient(x)
            return [-value if not wall.is_solid(q) else 0.0 for q, value in enumerate(div_beta_grad)]

        p = [0.0] * len(b)
        r = list(b)
        diag_inv = [0.0] * len(b)
        inv_h2 = 1.0 / (self.h * self.h)
        for q in fluid:
            diag = 0.0
            for axis in range(3):
                diag += self._face_inv_density(q, axis)
                rm = self._face_neighbor(q, axis, -1)
                diag += self._face_inv_density(rm, axis)
            diag_inv[q] = 1.0 / (diag * inv_h2) if diag > 0.0 else 0.0
        z = [m * value for m, value in zip(diag_inv, r)]
        direction = list(z)
        rz = sum(r[q] * z[q] for q in fluid)
        residual = dt * max((abs(r[q]) for q in fluid), default=0.0)
        iterations = 0

        for it in range(self.config.pressure_iterations):
            if residual <= self.config.pressure_tolerance_s_inv:
                break
            ad = apply_a(direction)
            denom = sum(direction[q] * ad[q] for q in fluid)
            if abs(denom) <= 1e-300:
                break
            alpha = rz / denom
            for q in fluid:
                p[q] += alpha * direction[q]
                r[q] -= alpha * ad[q]
            avg_p = sum(p[q] for q in fluid) / len(fluid) if fluid else 0.0
            avg_r = sum(r[q] for q in fluid) / len(fluid) if fluid else 0.0
            for q in fluid:
                p[q] -= avg_p
                r[q] -= avg_r
            residual = dt * max((abs(r[q]) for q in fluid), default=0.0)
            iterations = it + 1
            if residual <= self.config.pressure_tolerance_s_inv:
                break
            z = [diag_inv[q] * r[q] if not wall.is_solid(q) else 0.0 for q in range(len(r))]
            rz_new = sum(r[q] * z[q] for q in fluid)
            if abs(rz) <= 1e-300:
                break
            beta_cg = rz_new / rz
            for q in fluid:
                direction[q] = z[q] + beta_cg * direction[q]
            rz = rz_new

        pgx, pgy, pgz = self._mobility_gradient(p)
        cu = [a - dt * g for a, g in zip(u, pgx)]
        cv = [a - dt * g for a, g in zip(v, pgy)]
        cw = [a - dt * g for a, g in zip(w, pgz)]
        wall.enforce_velocity((cu, cv, cw))
        self.pressure = p
        self.last_projection_iterations = iterations
        self.last_projection_residual = residual
        return cu, cv, cw

    def project(self, fields, dt: float) -> tuple[list[float], list[float], list[float]]:
        """Variable-density pressure projection using a symmetric SPD operator."""
        if self._resolved_walls is not None:
            return self._project_with_walls(fields, dt)

        u, v, w = fields
        div = self.divergence((u, v, w))
        b = [-d / dt for d in div]
        mean_b = sum(b) / len(b)
        b = [value - mean_b for value in b]

        def apply_a(x: list[float]) -> list[float]:
            div_beta_grad = self._div_mobility_gradient(x)
            return [-value for value in div_beta_grad]

        p = [0.0] * len(b)
        r = list(b)
        diag_inv = [0.0] * len(b)
        inv_h2 = 1.0 / (self.h * self.h)
        for q in range(len(b)):
            diag = 0.0
            for axis in range(3):
                diag += self._face_inv_density(q, axis)
                rm = self._face_neighbor(q, axis, -1)
                diag += self._face_inv_density(rm, axis)
            diag_inv[q] = 1.0 / (diag * inv_h2) if diag > 0.0 else 1.0
        z = [m * value for m, value in zip(diag_inv, r)]
        direction = list(z)
        rz = sum(a * bval for a, bval in zip(r, z))
        residual = dt * max((abs(value) for value in r), default=0.0)
        iterations = 0

        for it in range(self.config.pressure_iterations):
            if residual <= self.config.pressure_tolerance_s_inv:
                break
            ad = apply_a(direction)
            denom = sum(a * bval for a, bval in zip(direction, ad))
            if abs(denom) <= 1e-300:
                break
            alpha = rz / denom
            p = [pv + alpha * dv for pv, dv in zip(p, direction)]
            r = [rv - alpha * av for rv, av in zip(r, ad)]
            avg_p = sum(p) / len(p)
            p = [value - avg_p for value in p]
            avg_r = sum(r) / len(r)
            r = [value - avg_r for value in r]
            residual = dt * max((abs(value) for value in r), default=0.0)
            iterations = it + 1
            if residual <= self.config.pressure_tolerance_s_inv:
                break
            z = [m * value for m, value in zip(diag_inv, r)]
            rz_new = sum(a * bval for a, bval in zip(r, z))
            if abs(rz) <= 1e-300:
                break
            beta_cg = rz_new / rz
            direction = [zv + beta_cg * dv for zv, dv in zip(z, direction)]
            rz = rz_new

        pgx, pgy, pgz = self._mobility_gradient(p)
        cu = [a - dt * g for a, g in zip(u, pgx)]
        cv = [a - dt * g for a, g in zip(v, pgy)]
        cw = [a - dt * g for a, g in zip(w, pgz)]
        self.pressure = p
        self.last_projection_iterations = iterations
        self.last_projection_residual = residual
        return cu, cv, cw

    def physical_pressure_field(self) -> list[float]:
        """Return pressure including the declared reference hydrostatic component."""
        rho_ref = self.hydrostatic_reference_density_kg_m3
        if rho_ref is None:
            return list(self.pressure)
        gx, gy, gz = self.last_gravity_m_s2
        out = [0.0] * len(self.pressure)
        for q, dynamic in enumerate(self.pressure):
            x, y, z = self.cell_center(*self._ijk(q))
            out[q] = dynamic + rho_ref * (gx * x + gy * y + gz * z)
        return out

    def mean_pressure(self, region_label: str, physical: bool = True) -> float:
        field = self.physical_pressure_field() if physical else self.pressure
        values = [p for q, (p, label) in enumerate(zip(field, self.region_labels)) if label == region_label and not (self._resolved_walls is not None and self._resolved_walls.is_solid(q))]
        if not values:
            raise ValueError(f"region {region_label!r} has no grid cells")
        return sum(values) / len(values)

    def advance(
        self,
        dt: float,
        force_density,
        gravity_m_s2: Vec3,
        hydrostatic_reference_density_kg_m3: float | None = None,
    ) -> None:
        if dt <= 0.0:
            raise ValueError("dt must be positive")
        u, v, w = self.advect_and_diffuse(dt)
        fx, fy, fz = force_density
        gx, gy, gz = gravity_m_s2

        for q in range(len(u)):
            if self._resolved_walls is not None and self._resolved_walls.is_solid(q):
                continue
            inv_rho = 1.0 / self.density[q]
            if hydrostatic_reference_density_kg_m3 is None:
                ax, ay, az = gx, gy, gz
            else:
                factor = 1.0 - hydrostatic_reference_density_kg_m3 * inv_rho
                ax, ay, az = gx * factor, gy * factor, gz * factor
            u[q] += dt * (ax + fx[q] * inv_rho)
            v[q] += dt * (ay + fy[q] * inv_rho)
            w[q] += dt * (az + fz[q] * inv_rho)

        capx, capy, capz = self._mobility_gradient(self.capillary_pressure_potential)
        u = [a + dt * g for a, g in zip(u, capx)]
        v = [a + dt * g for a, g in zip(v, capy)]
        w = [a + dt * g for a, g in zip(w, capz)]
        if self._resolved_walls is not None:
            self._resolved_walls.enforce_velocity((u, v, w))

        self.hydrostatic_reference_density_kg_m3 = hydrostatic_reference_density_kg_m3
        self.last_gravity_m_s2 = gravity_m_s2
        self.u, self.v, self.w = self.project((u, v, w), dt)
