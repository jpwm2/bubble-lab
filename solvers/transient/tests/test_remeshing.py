from __future__ import annotations

import unittest

from bubblelab.solvers.transient import (
    ConservativeArealField,
    FrontRemesher,
    GridConfig,
    RemeshConfig,
    TimeStepPolicy,
    TransientConfig,
    TransientSoapFilmSolver,
    icosphere,
    mesh_quality,
)


class RemeshingTests(unittest.TestCase):
    def test_quality_trigger_repairs_deterministic_short_edge_and_conserves_field(self):
        front = icosphere(radius_m=0.008, subdivisions=1)
        target = front.mean_edge_length()
        preparation = FrontRemesher(
            RemeshConfig(
                mode="interval",
                target_edge_length_m=target,
                max_geometry_relative_error=1.0e-12,
            )
        )
        edge = tuple(sorted(front.faces[0][:2]))
        self.assertTrue(preparation.split_edge(front, edge, fraction=0.08))

        before = mesh_quality(front)
        field = ConservativeArealField.from_density(front, "mass", 2.5)
        initial_amount = field.total_amount()
        remesher = FrontRemesher(
            RemeshConfig(
                mode="quality",
                target_edge_length_m=target,
                min_angle_deg=25.0,
                max_aspect_ratio=3.0,
                max_geometry_relative_error=1.0e-12,
            )
        )
        report = remesher.remesh(front, {"mass": field})
        after = mesh_quality(front)

        self.assertTrue(report.attempted)
        self.assertGreater(report.operation_count, 0)
        self.assertGreater(after.min_angle_deg, before.min_angle_deg)
        self.assertLess(after.max_aspect_ratio, before.max_aspect_ratio)
        self.assertLessEqual(report.volume_relative_change, 1.0e-12)
        self.assertLess(
            abs(field.total_amount() - initial_amount) / initial_amount,
            1.0e-12,
        )
        self.assertTrue(report.region_identity_preserved)

    def test_identical_remesh_runs_have_exact_signature(self):
        def run():
            front = icosphere(radius_m=0.008, subdivisions=1)
            target = front.mean_edge_length()
            remesher = FrontRemesher(
                RemeshConfig(
                    mode="interval",
                    target_edge_length_m=target,
                    max_geometry_relative_error=1.0e-12,
                )
            )
            edge = tuple(sorted(front.faces[0][:2]))
            self.assertTrue(remesher.split_edge(front, edge, fraction=0.08))
            field = ConservativeArealField.from_density(front, "mass", 1.0)
            quality = FrontRemesher(
                RemeshConfig(
                    mode="quality",
                    target_edge_length_m=target,
                    min_angle_deg=25.0,
                    max_aspect_ratio=3.0,
                    max_geometry_relative_error=1.0e-12,
                )
            )
            report = quality.remesh(front, {"mass": field})
            return front.vertices, front.faces, field.face_amounts, report.signature()

        self.assertEqual(run(), run())

    def test_solver_interval_stage_records_pre_projection_remesh_diagnostics(self):
        front = icosphere(radius_m=0.006, subdivisions=1, surface_tension_n_m=0.0)
        config = TransientConfig(
            grid=GridConfig(
                cells=(8, 8, 8),
                origin_m=(-0.02, -0.02, -0.02),
                extent_m=(0.04, 0.04, 0.04),
                background_velocity_m_s=(0.05, 0.0, 0.0),
            ),
            timestep=TimeStepPolicy(max_dt_s=1.0e-4),
            remeshing=RemeshConfig(
                mode="interval",
                interval_steps=1,
                target_edge_length_m=front.mean_edge_length(),
            ),
        )
        solver = TransientSoapFilmSolver([front], config)
        field = solver.attach_surface_field(front.bubble_id, "generic_mass", 1.0)
        amount = field.total_amount()
        diag = solver.step(1.0e-4)

        self.assertEqual(len(diag.remesh_reports), 1)
        self.assertLessEqual(diag.remesh_max_field_conservation_error, 1.0e-12)
        self.assertAlmostEqual(
            solver.surface_fields[front.bubble_id]["generic_mass"].total_amount(),
            amount,
            places=14,
        )
        self.assertEqual(solver.fronts[0].bubble_id, front.bubble_id)

    def test_disabled_remeshing_preserves_legacy_replay_path(self):
        front = icosphere(radius_m=0.006, subdivisions=1, surface_tension_n_m=0.0)
        solver = TransientSoapFilmSolver([front], TransientConfig())
        diag = solver.step(1.0e-5)
        self.assertEqual(diag.remesh_operation_count, 0)
        self.assertEqual(diag.remesh_reports, ())


if __name__ == "__main__":
    unittest.main()
