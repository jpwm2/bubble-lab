from __future__ import annotations

import copy
import json
import unittest

from bubblelab.solvers.boundary import PlaneBoundary, WettingParameters
from bubblelab.solvers.transient import (
    AMRConfig,
    GridConfig,
    RemeshConfig,
    TransientConfig,
    TransientSoapFilmSolver,
    icosphere,
)
from bubblelab.solvers.transient.checkpoint import (
    IncompatibleCheckpointError,
    canonical_bytes,
    restore_solver,
    snapshot_solver,
)


class TransientCheckpointTests(unittest.TestCase):
    def _solver(self) -> TransientSoapFilmSolver:
        front = icosphere(
            radius_m=0.008,
            subdivisions=1,
            bubble_id="restart-bubble",
            surface_tension_n_m=0.05,
        )
        config = TransientConfig(
            grid=GridConfig(
                cells=(8, 8, 8),
                origin_m=(-0.02, -0.02, -0.02),
                extent_m=(0.04, 0.04, 0.04),
                background_velocity_m_s=(0.03, 0.0, 0.0),
            ),
            amr=AMRConfig(
                enabled=True,
                max_levels=1,
                refinement_ratio=2,
                front_band_cells=0.9,
            ),
            deterministic_seed=20260918,
            remeshing=RemeshConfig(
                mode="interval",
                interval_steps=1,
                target_edge_length_m=0.006,
                max_passes=1,
                max_operations_per_pass=8,
            ),
            solid_boundaries=(
                PlaneBoundary(
                    boundary_id="floor",
                    point_m=(0.0, -0.012, 0.0),
                    normal_outward=(0.0, 1.0, 0.0),
                    wetting=WettingParameters(
                        target_contact_angle_deg=75.0,
                        relaxation=0.4,
                        iterations=2,
                        contact_band_m=0.002,
                    ),
                ),
            ),
        )
        return TransientSoapFilmSolver([front], config)

    def test_json_roundtrip_restores_authoritative_state(self):
        solver = self._solver()
        solver.step(solver.select_timestep())
        payload = snapshot_solver(solver)
        decoded = json.loads(canonical_bytes(payload))
        restored = restore_solver(decoded)
        self.assertEqual(canonical_bytes(payload), canonical_bytes(snapshot_solver(restored)))
        self.assertEqual(solver.replay_signature(), restored.replay_signature())

    def test_restored_amr_remesh_boundary_path_continues_exactly(self):
        solver = self._solver()
        solver.step(solver.select_timestep())
        restored = restore_solver(json.loads(canonical_bytes(snapshot_solver(solver))))

        dt = solver.select_timestep()
        self.assertEqual(dt, restored.select_timestep())
        solver.step(dt)
        restored.step(dt)
        self.assertEqual(
            canonical_bytes(snapshot_solver(solver)),
            canonical_bytes(snapshot_solver(restored)),
        )
        self.assertEqual(solver.replay_signature(), restored.replay_signature())

    def test_cross_version_checkpoint_is_rejected(self):
        payload = snapshot_solver(self._solver())
        payload = copy.deepcopy(payload)
        payload["solver_version"] = "different-build"
        with self.assertRaisesRegex(IncompatibleCheckpointError, "cross-version"):
            restore_solver(payload)


if __name__ == "__main__":
    unittest.main()
