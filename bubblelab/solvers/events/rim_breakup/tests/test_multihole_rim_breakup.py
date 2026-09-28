from __future__ import annotations
import unittest
from bubblelab.solvers.events.rim_breakup.multihole_solver import MultiHoleRimBreakupConfig, evolve_multihole_rim_breakup, evolve_isolated_superposition_reference


class MultiHoleRimBreakupTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.result = evolve_multihole_rim_breakup()
        cls.isolated = evolve_isolated_superposition_reference()

    def test_two_holes_share_one_interacting_conservative_state(self):
        self.assertEqual(len(self.result.final_hole_radii_m), 2)
        self.assertGreater(self.result.config.hole_center_distance_m, sum(self.result.config.initial_hole_radii_m))
        self.assertLessEqual(self.result.interaction_onset_time_s, self.result.ligament_onset_time_s)
        self.assertLess(self.result.ligament_onset_time_s, self.result.detachment_time_s)
        self.assertGreater(self.result.final_gap_m, 0.0)
        self.assertEqual(self.result.provenance['state_model'], 'ONE_SHARED_CONSERVATIVE_FILM_PLUS_TWO_SIMULTANEOUS_RIM_STATES')
        self.assertEqual(self.result.provenance['independent_run_stitching'], 'NOT_USED')

    def test_interaction_changes_breakup_relative_to_isolated_superposition(self):
        relative_shift = abs(self.result.detachment_time_s-self.isolated.detachment_time_s)/self.isolated.detachment_time_s
        self.assertGreaterEqual(relative_shift, 0.05)
        probe_time = 0.10
        coupled = min(self.result.samples, key=lambda s: abs(s.time_s-probe_time))
        isolated = min(self.isolated.samples, key=lambda s: abs(s.time_s-probe_time))
        neck_change = max(abs(a-b)/b for a,b in zip(coupled.hole_neck_radius_ratios, isolated.hole_neck_radius_ratios))
        self.assertGreaterEqual(neck_change, 0.05)

    def test_simultaneous_modes_are_state_coupled(self):
        self.assertGreaterEqual(min(len(row) for row in self.result.initial_mode_amplitudes), 2)
        coupled = min(self.result.samples, key=lambda s: abs(s.time_s-0.10))
        isolated = min(self.isolated.samples, key=lambda s: abs(s.time_s-0.10))
        relative_changes=[]
        for hole in (0,1):
            c=dict(coupled.hole_mode_amplitudes[hole])
            r=dict(isolated.hole_mode_amplitudes[hole])
            relative_changes.extend(abs(c[m]-r[m])/r[m] for m in c)
        self.assertGreaterEqual(max(relative_changes), 0.05)
        self.assertGreater(coupled.bridge_fraction, 0.0)

    def test_detachment_count_and_masses_come_from_evolved_necks(self):
        neck_count = sum(len(row) for row in self.result.neck_cells)
        self.assertEqual(len(self.result.droplets), neck_count)
        seeded_modes = {m for row in self.result.config.hole_modes for m in row}
        self.assertNotIn(len(self.result.droplets), seeded_modes)
        for hole in (0,1):
            detached = sum(drop.volume_m3 for drop in self.result.droplets if drop.source_hole == hole)
            self.assertAlmostEqual(detached, self.result.final_rim_volume_m3[hole], places=14)

    def test_liquid_volume_is_conserved_through_detachment(self):
        self.assertLessEqual(self.result.liquid_volume_relative_error, 1e-12)
        self.assertAlmostEqual(self.result.pre_detachment_rim_volume_m3, self.result.droplet_volume_m3, places=14)
        self.assertAlmostEqual(self.result.remaining_film_volume_m3+self.result.droplet_volume_m3, self.result.initial_liquid_volume_m3, places=14)

    def test_deterministic_replay(self):
        repeat = evolve_multihole_rim_breakup(MultiHoleRimBreakupConfig())
        self.assertEqual(self.result.solver_digest, repeat.solver_digest)
        self.assertEqual(self.result.droplets, repeat.droplets)
        self.assertEqual(self.result.final_mode_amplitudes, repeat.final_mode_amplitudes)


if __name__ == '__main__':
    unittest.main()
