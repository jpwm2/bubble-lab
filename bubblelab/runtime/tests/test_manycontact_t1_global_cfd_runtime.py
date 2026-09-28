from __future__ import annotations

import unittest

from bubblelab.runtime.manycontact_t1_global_cfd_runtime import (
    ManyContactT1GlobalCFDConfigurationError,
    ManyContactT1GlobalCFDRuntime,
)


class ManyContactT1GlobalCFDRuntimeTests(unittest.TestCase):
    def test_scenario_parser_keeps_manycontact_gates(self) -> None:
        runtime = ManyContactT1GlobalCFDRuntime.from_scenario(
            {
                "manycontact_t1_global_cfd": {
                    "minimum_support_regions": 5,
                    "non_event_relative_speed_m_s": 0.030,
                    "minimum_non_event_causality_fraction": 0.02,
                    "feedback_iterations": 4,
                    "field": {"pseudo_steps": 20},
                }
            }
        )
        self.assertEqual(runtime.settings.minimum_support_regions, 5)
        self.assertAlmostEqual(
            runtime.settings.non_event_relative_speed_m_s, 0.030
        )
        self.assertAlmostEqual(
            runtime.settings.minimum_non_event_causality_fraction, 0.02
        )
        self.assertEqual(runtime.settings.strong.feedback_iterations, 4)
        self.assertEqual(runtime.settings.strong.base.field.pseudo_steps, 20)

    def test_missing_scenario_block_is_rejected(self) -> None:
        with self.assertRaisesRegex(
            ManyContactT1GlobalCFDConfigurationError,
            "manycontact_t1_global_cfd",
        ):
            ManyContactT1GlobalCFDRuntime.from_scenario({})

    def test_underresolved_grid_is_rejected(self) -> None:
        with self.assertRaisesRegex(
            ManyContactT1GlobalCFDConfigurationError,
            "at least eight cells",
        ):
            ManyContactT1GlobalCFDRuntime.from_scenario(
                {"manycontact_t1_global_cfd": {"cells": 7}}
            )


if __name__ == "__main__":
    unittest.main()
