from __future__ import annotations

import unittest

from bubblelab.solvers.plateau_border import (
    PlateauBorderModel,
    PlateauBorderSettings,
    conforming_subdivide_state,
    evolve_and_switch,
)
from bubblelab.solvers.transient.network.t1_hydrodynamics import build_direct_3d_t1_state


def _state(surface_tension_n_m: float = 1.0):
    return build_direct_3d_t1_state(
        amplitude_m_inv=0.8,
        y_saturation_m=0.04,
        sheet_tension_n_m=surface_tension_n_m,
    )


class PlateauBorderHydrodynamicsTests(unittest.TestCase):
    def test_force_balance_has_resolved_components(self) -> None:
        model = PlateauBorderModel(_state())
        sample = model.evolve_to_event().samples[0]
        self.assertGreater(sample.forces.sheet_traction_n, 0.0)
        self.assertGreater(sample.forces.border_capillary_force_n, 0.0)
        self.assertGreater(sample.forces.capillary_force_n, 0.0)
        self.assertGreaterEqual(sample.forces.pressure_force_n, 0.0)
        self.assertGreater(sample.forces.viscous_force_n, 0.0)
        self.assertAlmostEqual(sample.forces.force_balance_residual_n, 0.0, places=12)

    def test_liquid_volume_is_conserved(self) -> None:
        evolution = PlateauBorderModel(_state()).evolve_to_event()
        self.assertLessEqual(evolution.maximum_liquid_relative_error, 1.0e-12)
        self.assertAlmostEqual(
            evolution.initial_liquid_volume_m3,
            evolution.final_liquid_volume_m3,
            places=16,
        )

    def test_surface_tension_and_viscosity_have_independent_response(self) -> None:
        low_gamma = PlateauBorderModel(
            _state(0.8),
            PlateauBorderSettings(surface_tension_n_m=0.8),
        ).evolve_to_event()
        high_gamma = PlateauBorderModel(
            _state(1.2),
            PlateauBorderSettings(surface_tension_n_m=1.2),
        ).evolve_to_event()
        self.assertLess(high_gamma.event_time_s, low_gamma.event_time_s)

        low_mu = PlateauBorderModel(
            _state(),
            PlateauBorderSettings(liquid_viscosity_pa_s=0.08),
        ).evolve_to_event()
        high_mu = PlateauBorderModel(
            _state(),
            PlateauBorderSettings(liquid_viscosity_pa_s=0.18),
        ).evolve_to_event()
        self.assertGreater(high_mu.event_time_s, low_mu.event_time_s)

    def test_time_step_and_mesh_refinement_converge(self) -> None:
        coarse = PlateauBorderModel(
            _state(),
            PlateauBorderSettings(time_step_s=4.0e-4),
        ).evolve_to_event()
        fine = PlateauBorderModel(
            _state(),
            PlateauBorderSettings(time_step_s=2.0e-4),
        ).evolve_to_event()
        relative = abs(coarse.event_time_s - fine.event_time_s) / fine.event_time_s
        self.assertLess(relative, 0.03)

        base_state = _state()
        refined_state = conforming_subdivide_state(base_state)
        base_time = PlateauBorderModel(base_state).evolve_to_event().event_time_s
        refined_time = PlateauBorderModel(refined_state).evolve_to_event().event_time_s
        mesh_relative = abs(base_time - refined_time) / refined_time
        self.assertLess(mesh_relative, 1.0e-9)

    def test_real_t1_switch_uses_border_event_time(self) -> None:
        result = evolve_and_switch(_state())
        neighborhood = PlateauBorderModel(_state()).neighborhood
        old_pair = tuple(sorted(neighborhood.old_adjacent_regions))
        new_pair = tuple(sorted(neighborhood.opposite_regions))
        self.assertIn(old_pair, result.adjacency_before)
        self.assertNotIn(old_pair, result.adjacency_after)
        self.assertNotIn(new_pair, result.adjacency_before)
        self.assertIn(new_pair, result.adjacency_after)
        self.assertAlmostEqual(
            result.after.time_s - result.before.time_s,
            result.evolution.event_time_s,
            places=12,
        )
        self.assertLessEqual(max(error for _, error in result.volume_errors_after), 1.0e-12)

    def test_deterministic_replay(self) -> None:
        state = _state()
        first = evolve_and_switch(state)
        second = evolve_and_switch(state)
        self.assertEqual(first.evolution, second.evolution)
        self.assertEqual(first.lineage, second.lineage)
        self.assertEqual(first.after, second.after)


if __name__ == "__main__":
    unittest.main()
