from __future__ import annotations

from dataclasses import replace
import unittest

from bubblelab.solvers.multiregion_cfd import (
    ManyContactT1GlobalCFDSettings,
    build_supported_manycontact_t1_solver,
    run_manycontact_t1_global_cfd_transition,
    solve_manycontact_shared_field,
)
from bubblelab.solvers.transient.network.t1_hydrodynamics import (
    build_direct_3d_t1_state,
    detect_direct_t1_eligibility,
)


class ManyContactT1GlobalCFDTests(unittest.TestCase):
    def _fixture(self):
        state = build_direct_3d_t1_state(
            mode="saddle-saturation",
            amplitude_m_inv=0.8,
            y_saturation_m=0.04,
            sheet_tension_n_m=0.03,
        )
        eligibility = detect_direct_t1_eligibility(state)
        self.assertTrue(eligibility.eligible, eligibility.reason)
        self.assertIsNotNone(eligibility.neighborhood)
        neighborhood = eligibility.neighborhood
        assert neighborhood is not None
        ids = tuple(region.id for region in state.to_network().regions)
        solver = build_supported_manycontact_t1_solver(
            region_ids=ids,
            old_pair=neighborhood.old_adjacent_regions,
            extra_region_id="E",
            cells=8,
            subdivisions=1,
        )
        return state, neighborhood, solver

    def test_settings_keep_five_region_floor(self) -> None:
        settings = ManyContactT1GlobalCFDSettings(
            minimum_support_regions=4
        )
        with self.assertRaisesRegex(ValueError, "at least five"):
            settings.validate()

    def test_fixture_has_five_unique_stable_support_ids(self) -> None:
        _, _, solver = self._fixture()
        ids = tuple(sorted(front.bubble_id for front in solver.fronts))
        self.assertEqual(len(ids), 5)
        self.assertEqual(len(set(ids)), 5)
        self.assertIn("E", ids)

    def test_shared_field_requires_targets_for_every_support_region(self) -> None:
        _, _, solver = self._fixture()
        targets = {
            front.bubble_id: (0.0, 0.0, 0.0)
            for front in solver.fronts
            if front.bubble_id != "E"
        }
        with self.assertRaisesRegex(ValueError, "all support IDs"):
            solve_manycontact_shared_field(
                solver,
                targets,
                phase="UNIT_TARGET_VALIDATION",
            )

    def test_non_event_contact_must_include_extra_support_region(self) -> None:
        state, neighborhood, solver = self._fixture()
        topology_only_pair = tuple(
            sorted(neighborhood.opposite_regions)
        )
        with self.assertRaisesRegex(ValueError, "extra support region"):
            run_manycontact_t1_global_cfd_transition(
                solver,
                state,
                topology_only_pair,
                ManyContactT1GlobalCFDSettings(),
            )


if __name__ == "__main__":
    unittest.main()
