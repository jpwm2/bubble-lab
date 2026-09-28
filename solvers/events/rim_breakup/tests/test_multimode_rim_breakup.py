from __future__ import annotations
import unittest
from bubblelab.solvers.events.rim_breakup.multimode_solver import MultimodeRimBreakupConfig, evolve_multimode_rim_breakup


class MultimodeRimBreakupTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.result = evolve_multimode_rim_breakup()

    def test_one_asymmetric_state_contains_competing_modes(self):
        initial = dict(self.result.initial_mode_amplitudes)
        final = dict(self.result.final_mode_amplitudes)
        self.assertGreaterEqual(len(initial), 2)
        for mode in self.result.config.disturbance_modes:
            self.assertGreater(initial[mode], 0.0)
            self.assertGreater(final[mode], initial[mode])
        initial_ratio = initial[self.result.config.disturbance_modes[1]] / initial[self.result.config.disturbance_modes[0]]
        final_ratio = final[self.result.config.disturbance_modes[1]] / final[self.result.config.disturbance_modes[0]]
        self.assertGreater(abs(final_ratio - initial_ratio), 0.2)

    def test_detachment_is_state_derived_not_mode_count(self):
        self.assertGreaterEqual(len(self.result.neck_cells), 2)
        self.assertEqual(len(self.result.droplets), len(self.result.neck_cells))
        self.assertNotIn(len(self.result.droplets), self.result.config.disturbance_modes)
        self.assertGreater(self.result.detachment_time_s, self.result.ligament_onset_time_s)

    def test_conservation_and_impulse(self):
        self.assertLessEqual(self.result.liquid_volume_relative_error, 1e-12)
        self.assertLessEqual(abs(self.result.radial_momentum_residual_kg_m_s), 1e-12)
        self.assertAlmostEqual(self.result.pre_detachment_rim_volume_m3, self.result.droplet_volume_m3, places=14)

    def test_asymmetry_and_claim_boundary(self):
        config = self.result.config
        self.assertGreater(config.initial_mean_hole_radius_m * (1.0 + config.hole_asymmetry_fraction), config.initial_mean_hole_radius_m * (1.0 - config.hole_asymmetry_fraction))
        self.assertEqual(self.result.provenance["supported_class"], "ONE_ASYMMETRIC_THIN_FILM_HOLE_SIMULTANEOUS_MULTIMODE_REDUCED_RIM")
        self.assertEqual(self.result.provenance["turbulent_atomization"], "UNSUPPORTED")

    def test_deterministic_replay(self):
        repeat = evolve_multimode_rim_breakup(MultimodeRimBreakupConfig())
        self.assertEqual(self.result.solver_digest, repeat.solver_digest)
        self.assertEqual(self.result.droplets, repeat.droplets)
        self.assertEqual(self.result.final_volume_per_radian_m3, repeat.final_volume_per_radian_m3)


if __name__ == "__main__":
    unittest.main()
