from __future__ import annotations

import unittest

from bubblelab.runtime.t1_hydrodynamics_runtime import run_t1_hydrodynamics_runtime
from bubblelab.solvers.transient.network.core import NetworkStepperSettings
from bubblelab.solvers.transient.network.t1_hydrodynamics import (
    DirectT1Settings,
    build_direct_3d_t1_state,
)


class T1HydrodynamicsRuntimeTests(unittest.TestCase):
    def test_post_event_state_continues_through_authoritative_stepper(self) -> None:
        state = build_direct_3d_t1_state(
            mode="twisted-saturation",
            amplitude_m_inv=0.8,
            y_saturation_m=0.04,
        )
        result = run_t1_hydrodynamics_runtime(
            state,
            event_settings=DirectT1Settings(
                plateau_border_core_radius_m=0.010,
                hydrodynamic_segments=20,
            ),
            stepper_settings=NetworkStepperSettings(
                dt_s=5.0e-5,
                mobility_m_per_n_s=5.0e-3,
                volume_relative_tolerance=2.0e-10,
            ),
            continuation_steps=2,
        )
        self.assertEqual(len(result.diagnostics), 2)
        self.assertEqual(result.continued.step_index, result.event.after.step_index + 2)
        self.assertGreater(result.continued.time_s, result.event.after.time_s)
        self.assertEqual(
            result.continued.topology_signature(),
            result.event.after.topology_signature(),
        )
        self.assertLessEqual(
            max(error for _, error in result.diagnostics[-1].relative_volume_errors),
            2.0e-10,
        )

    def test_runtime_replay_is_deterministic(self) -> None:
        state = build_direct_3d_t1_state(
            mode="saddle-saturation",
            amplitude_m_inv=0.8,
            y_saturation_m=0.04,
        )
        kwargs = dict(
            event_settings=DirectT1Settings(hydrodynamic_segments=16),
            stepper_settings=NetworkStepperSettings(
                dt_s=5.0e-5,
                mobility_m_per_n_s=5.0e-3,
            ),
            continuation_steps=1,
        )
        first = run_t1_hydrodynamics_runtime(state, **kwargs)
        second = run_t1_hydrodynamics_runtime(state, **kwargs)
        self.assertEqual(first.event.forecast, second.event.forecast)
        self.assertEqual(first.continued, second.continued)
        self.assertEqual(first.diagnostics, second.diagnostics)


if __name__ == "__main__":
    unittest.main()
