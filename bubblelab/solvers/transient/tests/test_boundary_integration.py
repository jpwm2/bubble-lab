from __future__ import annotations

import unittest

from bubblelab.solvers.boundary import PlaneBoundary, WettingParameters
from bubblelab.solvers.transient.export import frame_dict
from bubblelab.solvers.transient.geometry import icosphere
from bubblelab.solvers.transient.grid import GridConfig
from bubblelab.solvers.transient.solver import TimeStepPolicy, TransientConfig, TransientSoapFilmSolver


class BoundaryIntegrationTests(unittest.TestCase):
    def test_disabled_boundaries_preserve_empty_boundary_diagnostics(self):
        front = icosphere(radius_m=0.006, subdivisions=1)
        config = TransientConfig(
            grid=GridConfig(
                cells=(8, 8, 8),
                origin_m=(-0.02, -0.02, -0.02),
                extent_m=(0.04, 0.04, 0.04),
            ),
            timestep=TimeStepPolicy(max_dt_s=1.0e-5, capillary_safety=0.05),
        )
        solver = TransientSoapFilmSolver([front], config)
        diagnostic = solver.step(1.0e-5)
        self.assertEqual(diagnostic.boundary_contact_vertex_count, 0)
        self.assertEqual(diagnostic.boundary_ids, ())

    def test_export_is_explicit_about_periodic_bulk_limitation(self):
        floor = PlaneBoundary(
            "floor",
            point_m=(0.0, 0.0, 0.0),
            normal_outward=(0.0, 1.0, 0.0),
            wetting=WettingParameters(target_contact_angle_deg=60.0),
        )
        front = icosphere(radius_m=0.004, center_m=(0.0, 0.0035, 0.0), subdivisions=1)
        config = TransientConfig(
            grid=GridConfig(
                cells=(6, 6, 6),
                origin_m=(-0.015, -0.005, -0.015),
                extent_m=(0.03, 0.03, 0.03),
            ),
            timestep=TimeStepPolicy(max_dt_s=1.0e-5, capillary_safety=0.05),
            solid_boundaries=(floor,),
            boundary_tolerance_m=1.0e-8,
        )
        solver = TransientSoapFilmSolver([front], config)
        solver.step(1.0e-5)
        frame = frame_dict(solver)
        disclosures = frame["manifest"]["feature_disclosures"]
        self.assertEqual(disclosures["tracked_film_solid_no_penetration"], "RESOLVED")
        self.assertEqual(disclosures["film_wall_contact_angle"], "MODELED")
        self.assertEqual(disclosures["bulk_solid_wall_no_slip"], "NOT_IMPLEMENTED")
        contact = frame["diagnostics"]["solid_boundary_contact"]
        self.assertEqual(contact["bulk_eulerian_wall_coupling"], "NOT_IMPLEMENTED_PERIODIC_GRID")
        self.assertEqual(contact["configured_boundaries"][0]["boundary_id"], "floor")


if __name__ == "__main__":
    unittest.main()
