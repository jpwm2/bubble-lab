from __future__ import annotations

import json
import math
from pathlib import Path
import tempfile
import unittest

from bubblelab.solvers.equilibrium.energy import area_gradient, volume_gradient
from bubblelab.solvers.equilibrium.export import canonical_frame
from bubblelab.solvers.equilibrium.mesh import SurfaceMesh
from bubblelab.solvers.equilibrium.solver import SolverSettings, solve_prescribed_volume
from bubblelab.solvers.equilibrium.sphere import icosphere, sphere_volume


class MeshTests(unittest.TestCase):
    def test_icosphere_is_closed_outward_and_deterministic(self) -> None:
        first = icosphere(2)
        second = icosphere(2)
        first.validate()
        self.assertGreater(first.signed_volume(), 0.0)
        self.assertEqual(first, second)
        reversed_mesh = SurfaceMesh(first.vertices, tuple((a, c, b) for a, b, c in first.faces))
        self.assertLess(reversed_mesh.signed_volume(), 0.0)
        self.assertEqual(reversed_mesh.oriented_outward().faces, first.faces)

    def test_area_and_volume_gradients_match_finite_difference(self) -> None:
        mesh = icosphere(1)
        area_grad = area_gradient(mesh)
        volume_grad = volume_gradient(mesh)
        vertex_index = 7
        axis = 1
        eps = 1.0e-7
        base = list(mesh.vertices)
        plus = base.copy()
        minus = base.copy()
        plus[vertex_index] = tuple(value + (eps if i == axis else 0.0) for i, value in enumerate(base[vertex_index]))
        minus[vertex_index] = tuple(value - (eps if i == axis else 0.0) for i, value in enumerate(base[vertex_index]))
        plus_mesh = mesh.with_vertices(plus)
        minus_mesh = mesh.with_vertices(minus)
        area_fd = (plus_mesh.area() - minus_mesh.area()) / (2.0 * eps)
        volume_fd = (plus_mesh.signed_volume() - minus_mesh.signed_volume()) / (2.0 * eps)
        self.assertAlmostEqual(area_fd, area_grad[vertex_index][axis], delta=2.0e-7)
        self.assertAlmostEqual(volume_fd, volume_grad[vertex_index][axis], delta=2.0e-7)


class SolverTests(unittest.TestCase):
    def test_projected_solver_reduces_energy_and_preserves_volume(self) -> None:
        radius = 1.0
        target = sphere_volume(radius)
        mesh = icosphere(2, radius)
        perturbed = []
        for index, vertex in enumerate(mesh.vertices):
            factor = 1.0 + 0.035 * math.sin(1.7 * index)
            perturbed.append(tuple(factor * value for value in vertex))
        result = solve_prescribed_volume(
            mesh.with_vertices(perturbed),
            target,
            0.05,
            SolverSettings(max_iterations=80, normalized_force_tolerance=1.0e-3),
        )
        self.assertLess(result.surface_energy_j, result.initial_surface_energy_j)
        self.assertLessEqual(result.relative_volume_error, 1.0e-10)
        self.assertTrue(all(b <= a * (1.0 + 2.0e-13) for a, b in zip(result.energy_history_j, result.energy_history_j[1:])))

    def test_pressure_converges_toward_young_laplace(self) -> None:
        radius = 0.01
        tension = 0.05
        target = sphere_volume(radius)
        errors = []
        exact = 2.0 * tension / radius
        for level in (2, 3, 4):
            result = solve_prescribed_volume(icosphere(level, radius), target, tension)
            errors.append(abs(result.pressure_jump_pa - exact) / exact)
        self.assertGreater(errors[0], errors[1])
        self.assertGreater(errors[1], errors[2])
        self.assertLess(errors[2], 5.0e-3)


class ExportTests(unittest.TestCase):
    def test_canonical_export_is_sparse_and_contract_shaped(self) -> None:
        radius = 0.01
        tension = 0.05
        target = sphere_volume(radius)
        result = solve_prescribed_volume(icosphere(2, radius), target, tension)
        frame = canonical_frame(result, target_volume_m3=target, sheet_tension_n_m=tension)
        encoded = json.dumps(frame)
        self.assertEqual(frame["contract_version"], "1.0.0")
        self.assertEqual(frame["kind"], "FRAME")
        self.assertEqual(frame["manifest"]["fidelity_tier"], "HIGH_FIDELITY")
        self.assertEqual(frame["manifest"]["feature_disclosures"]["film_thickness"], "NOT_IMPLEMENTED")
        self.assertEqual(frame["junctions"], [])
        self.assertNotIn('"thickness"', encoded)
        self.assertNotIn('"velocity_field"', encoded)
        self.assertEqual(frame["surface_meshes"][0]["geometry_role"], "OUTER_FILM")


if __name__ == "__main__":
    unittest.main()
