from __future__ import annotations

import unittest

from bubblelab.solvers.equilibrium.network import junction_geometry_diagnostics
from bubblelab.solvers.equilibrium.plateau import reference_plateau_network
from bubblelab.solvers.equilibrium.plateau_benchmarks import (
    assert_plateau_convergence,
    assert_plateau_three,
    plateau_convergence,
    plateau_three,
    plateau_three_result,
    unequal_tension_metrics,
)
from bubblelab.solvers.equilibrium.plateau_export import canonical_plateau_frame


class PlateauTopologyTests(unittest.TestCase):
    def test_junction_is_explicit_and_uses_one_common_geometric_line(self) -> None:
        network = reference_plateau_network(longitudinal_segments=12)
        self.assertEqual(len(network.junctions), 1)
        junction = network.junctions[0]
        self.assertEqual(len(junction.incident_film_ids), 3)
        self.assertEqual(len(set(junction.incident_film_ids)), 3)

        patches = {patch.id: patch for patch in network.patches}
        for sample in range(len(junction.vertex_indices_by_film[0])):
            points = [
                patches[film_id].mesh.vertices[indices[sample]]
                for film_id, indices in zip(junction.incident_film_ids, junction.vertex_indices_by_film)
            ]
            self.assertEqual(points[0], points[1])
            self.assertEqual(points[1], points[2])

    def test_b06_equal_tension_plateau_junction(self) -> None:
        metrics = plateau_three()
        assert_plateau_three(metrics)

    def test_b06_refinement(self) -> None:
        metrics = plateau_convergence()
        assert_plateau_convergence(metrics)

    def test_unequal_tension_changes_neumann_equilibrium(self) -> None:
        metrics = unequal_tension_metrics()
        self.assertTrue(metrics["converged"])
        self.assertLessEqual(metrics["junction_force_residual"], 5.0e-3)
        self.assertGreater(metrics["maximum_angle_change_deg"], 5.0)


class PlateauExportTests(unittest.TestCase):
    def test_canonical_export_contains_three_film_junction(self) -> None:
        result = plateau_three_result()
        frame = canonical_plateau_frame(result)
        self.assertEqual(frame["contract_version"], "1.0.0")
        self.assertEqual(frame["kind"], "FRAME")
        self.assertGreaterEqual(len(frame["bubbles"]), 3)
        self.assertEqual(len(frame["junctions"]), 1)
        junction = frame["junctions"][0]
        self.assertEqual(len(junction["incident_film_ids"]), 3)
        self.assertEqual(len(junction["measured_angles_deg"]), 3)
        self.assertEqual(frame["manifest"]["feature_disclosures"]["plateau_junctions"], "RESOLVED")
        self.assertEqual(
            frame["manifest"]["feature_disclosures"]["finite_width_plateau_borders"],
            "NOT_IMPLEMENTED",
        )

        diagnostics = junction_geometry_diagnostics(result.network, "plateau-junction-0")
        self.assertLessEqual(diagnostics["max_force_residual"], 5.0e-3)


if __name__ == "__main__":
    unittest.main()
