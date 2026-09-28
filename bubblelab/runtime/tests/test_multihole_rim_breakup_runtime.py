from __future__ import annotations
import json
from pathlib import Path
import unittest
from bubblelab.runtime.multihole_rim_breakup_runtime import run_multihole_rim_breakup_runtime

ROOT = Path(__file__).resolve().parents[2]
SCENARIO = ROOT / 'scenarios' / 'runtime' / 'multihole-rim-breakup.scenario.json'


class MultiHoleRimBreakupRuntimeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.payload = run_multihole_rim_breakup_runtime(json.loads(SCENARIO.read_text(encoding='utf-8')))

    def test_runtime_preserves_interacting_event_order(self):
        events=self.payload['event_sequence']
        self.assertEqual([event['type'] for event in events], ['TWO_HOLE_RETRACTION','RIM_INTERACTION_ONSET','MULTIHOLE_LIGAMENT_ONSET','STATE_DERIVED_MULTIRIM_DETACHMENT'])
        self.assertLess(events[0]['time_s'],events[1]['time_s'])
        self.assertLessEqual(events[1]['time_s'],events[2]['time_s'])
        self.assertLess(events[2]['time_s'],events[3]['time_s'])

    def test_runtime_exposes_two_state_coupled_holes(self):
        self.assertEqual(len(self.payload['holes']),2)
        self.assertGreaterEqual(self.payload['interaction']['detachment_time_relative_shift'],0.05)
        self.assertGreater(self.payload['interaction']['final_gap_m'],0.0)
        self.assertEqual(self.payload['interaction']['independent_run_stitching'],'NOT_USED')
        self.assertEqual(self.payload['interaction']['state_model'],'ONE_SHARED_CONSERVATIVE_FILM_PLUS_TWO_SIMULTANEOUS_RIM_STATES')

    def test_runtime_conserves_liquid_and_derives_fragments_from_necks(self):
        budgets=self.payload['budgets']
        self.assertLessEqual(budgets['liquid_volume_relative_error'],1e-12)
        self.assertAlmostEqual(budgets['pre_detachment_rim_volume_m3'],budgets['detached_droplet_volume_m3'],places=14)
        expected=sum(len(hole['evolved_neck_cells']) for hole in self.payload['holes'])
        self.assertEqual(len(self.payload['droplets']),expected)

    def test_runtime_continues_state_derived_droplets(self):
        self.assertTrue(self.payload['continuation']['exact_evolved_velocity_seed'])
        ids=[drop['id'] for drop in self.payload['droplets']]
        self.assertEqual(len(ids),len(set(ids)))
        self.assertEqual({drop['source_hole'] for drop in self.payload['droplets']},{0,1})
        for drop in self.payload['droplets']:
            self.assertGreater(drop['volume_m3'],0.0)
            self.assertNotEqual(drop['continued_position_m'],drop['position_m'])


if __name__ == '__main__':
    unittest.main()
