from __future__ import annotations

from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[4]
CONTRACT_PYTHON = ROOT / "bubblelab" / "python"
if str(CONTRACT_PYTHON) not in sys.path:
    sys.path.insert(0, str(CONTRACT_PYTHON))

from bubblelab_contract.validation import assert_valid
from bubblelab.solvers.transient import TransientSoapFilmSolver, frame_dict, icosphere


class ExportTests(unittest.TestCase):
    def test_frame_validates_and_does_not_invent_thickness_or_topology(self):
        solver = TransientSoapFilmSolver([icosphere(subdivisions=1)])
        solver.step()
        frame = frame_dict(solver)
        assert_valid(frame)
        self.assertEqual(frame["contract_version"], "1.0.0")
        self.assertEqual(frame["kind"], "FRAME")
        self.assertEqual(frame["junctions"], [])
        self.assertEqual(frame["topology"]["events"], [])
        self.assertNotIn("thickness", frame["film_regions"][0])
        disclosures = frame["manifest"]["feature_disclosures"]
        self.assertIn(disclosures["pressure_jump"], ("RESOLVED", "MODELED"))
        self.assertEqual(disclosures["region_specific_bulk_properties"], "RESOLVED")
        self.assertEqual(disclosures["buoyancy/density_contrast"], "MODELED")
        self.assertEqual(disclosures["adaptive_mesh_refinement"], "NOT_IMPLEMENTED")
        self.assertEqual(disclosures["film_thickness"], "NOT_IMPLEMENTED")
        self.assertEqual(disclosures["topology_change"], "NOT_IMPLEMENTED")
        self.assertEqual(disclosures["coalescence"], "NOT_IMPLEMENTED")


if __name__ == "__main__":
    unittest.main()
