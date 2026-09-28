from __future__ import annotations
import unittest
from bubblelab.solvers.events.rim_breakup import evolve_rim_breakup, rayleigh_plateau_reference


class RimBreakupTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.result = evolve_rim_breakup()

    def test_dynamic_sequence(self):
        self.assertGreater(self.result.ligament_onset_time_s, 0.0)
        self.assertGreater(self.result.detachment_time_s, self.result.ligament_onset_time_s)
        self.assertEqual(len(self.result.droplets), self.result.config.azimuthal_mode)
        self.assertEqual(self.result.samples[0].retraction_speed_m_s, 0.0)

    def test_conservation_and_impulse(self):
        self.assertLessEqual(self.result.liquid_volume_relative_error, 1e-12)
        self.assertLessEqual(abs(self.result.radial_momentum_residual_kg_m_s), 1e-12)
        self.assertAlmostEqual(sum(d.volume_m3 for d in self.result.droplets), self.result.pre_detachment_rim_volume_m3, places=14)

    def test_reference_regimes_are_declared(self):
        ref = rayleigh_plateau_reference(self.result.config)
        self.assertGreater(ref["dimensionless_wavenumber"], 0.0)
        self.assertLess(ref["dimensionless_wavenumber"], 1.0)
        self.assertEqual(self.result.provenance["supported_class"], "ONE_CIRCULAR_THIN_FILM_HOLE_ONE_AZIMUTHAL_MODE")
        self.assertEqual(self.result.provenance["spray_distribution"], "UNSUPPORTED")

    def test_stable_fragment_ids(self):
        repeat = evolve_rim_breakup()
        self.assertEqual(self.result.solver_digest, repeat.solver_digest)
        self.assertEqual([d.id for d in self.result.droplets], [d.id for d in repeat.droplets])


if __name__ == "__main__":
    unittest.main()
