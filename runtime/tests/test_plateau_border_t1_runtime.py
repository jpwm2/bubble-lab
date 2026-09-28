from __future__ import annotations

import unittest

from bubblelab.runtime.plateau_border_t1_runtime import run_plateau_border_t1_runtime
from bubblelab.solvers.plateau_border import PlateauBorderModel
from bubblelab.solvers.transient.network.t1_hydrodynamics import build_direct_3d_t1_state


class PlateauBorderT1RuntimeTests(unittest.TestCase):
    def test_event_switch_and_continuation(self) -> None:
        state = build_direct_3d_t1_state(
            amplitude_m_inv=0.8,
            y_saturation_m=0.04,
        )
        model = PlateauBorderModel(state)
        old_pair = tuple(sorted(model.neighborhood.old_adjacent_regions))
        new_pair = tuple(sorted(model.neighborhood.opposite_regions))
        result = run_plateau_border_t1_runtime(state, continuation_steps=2)
        self.assertIn(old_pair, result.event.adjacency_before)
        self.assertNotIn(old_pair, result.event.adjacency_after)
        self.assertNotIn(new_pair, result.event.adjacency_before)
        self.assertIn(new_pair, result.event.adjacency_after)
        self.assertEqual(len(result.diagnostics), 2)
        self.assertGreater(result.continued.time_s, result.event.after.time_s)


if __name__ == "__main__":
    unittest.main()
