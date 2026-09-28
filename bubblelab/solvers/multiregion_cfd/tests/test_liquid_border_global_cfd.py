import unittest
from dataclasses import replace
from bubblelab.solvers.multiregion_cfd import LiquidBorderGlobalCFDSettings, T1GlobalCFDSettings, build_supported_four_region_t1_solver, run_liquid_border_global_cfd_transition
from bubblelab.solvers.transient.network.t1_hydrodynamics import build_direct_3d_t1_state, detect_direct_t1_eligibility

class LiquidBorderGlobalCFDTests(unittest.TestCase):
    def _run(self):
        state=build_direct_3d_t1_state(mode="twisted-saturation",amplitude_m_inv=.8,y_saturation_m=.04,sheet_tension_n_m=.03)
        base=T1GlobalCFDSettings(); base=replace(base,field=replace(base.field,pseudo_steps=8),pre_event_drift_speed_m_s=0.0)
        e=detect_direct_t1_eligibility(state,base.direct); self.assertTrue(e.eligible)
        ids=tuple(r.id for r in state.to_network().regions)
        solver=build_supported_four_region_t1_solver(region_ids=ids,old_pair=e.neighborhood.old_adjacent_regions,cells=8,extent_m=.010,radius_m=.0012,old_pair_gap_m=.00035,transverse_offset_m=.0031,transverse_z_offset_m=.00135,exterior_density_kg_m3=970.,exterior_viscosity_pa_s=50.,interior_density_kg_m3=1.204,interior_viscosity_pa_s=1.825e-5)
        cfg=LiquidBorderGlobalCFDSettings(base=base,maximum_steps=256)
        return run_liquid_border_global_cfd_transition(solver,state,cfg)
    def test_shared_field_liquid_border_and_real_surgery(self):
        r=self._run(); self.assertTrue(r.authoritative_grid_preserved); self.assertNotEqual(r.adjacency_before,r.adjacency_after); self.assertEqual(len(r.liquid_segment_vertices_m),6); self.assertLessEqual(r.maximum_liquid_relative_error,1e-12); self.assertLessEqual(r.maximum_gas_volume_relative_error,1e-12)
    def test_field_feedback_changes_timing(self):
        r=self._run(); self.assertGreaterEqual(r.event_time_shift_fraction,.02); self.assertLessEqual(r.maximum_traction_mismatch,.20)
    def test_deterministic_replay(self):
        a=self._run().as_dict(); b=self._run().as_dict(); self.assertEqual(a,b)

if __name__ == "__main__": unittest.main()
