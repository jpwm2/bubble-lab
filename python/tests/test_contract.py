from __future__ import annotations
import json
import sys
import tempfile
import unittest
from pathlib import Path

PYTHON_ROOT=Path(__file__).resolve().parents[1]
REPO_ROOT=Path(__file__).resolve().parents[3]
FIXTURES=REPO_ROOT/"bubblelab"/"scenarios"/"fixtures"
sys.path.insert(0,str(PYTHON_ROOT))

from bubblelab_contract import ContractValidationError,canonical_json,dump_document,load_document,parse_document

class ContractRoundTripTests(unittest.TestCase):
    def fixture_paths(self):
        return sorted(FIXTURES.glob("*.json"))

    def test_all_fixtures_parse_and_round_trip_deterministically(self):
        self.assertGreaterEqual(len(self.fixture_paths()),5)
        for path in self.fixture_paths():
            with self.subTest(path=path.name):
                raw=json.loads(path.read_text(encoding="utf-8"))
                document=parse_document(raw)
                reparsed=json.loads(canonical_json(document.to_dict()))
                self.assertEqual(reparsed,raw)
                self.assertEqual(canonical_json(reparsed),canonical_json(raw))

    def test_missing_physics_remains_missing(self):
        bubble=load_document(FIXTURES/"single-isolated.frame.json").to_dict()["bubbles"][0]
        self.assertNotIn("pressure_pa",bubble)
        self.assertNotIn("temperature_k",bubble)
        self.assertNotIn("gas_amount_mol",bubble)
        self.assertNotIn("film_material",bubble)

    def test_sidecar_reference_does_not_inline_payload(self):
        mesh=load_document(FIXTURES/"rupture-coalescence-history.frame.json").to_dict()["surface_meshes"][0]
        self.assertEqual(mesh["vertices"]["storage"],"SIDECAR")
        self.assertIn("uri",mesh["vertices"])
        self.assertNotIn("values",mesh["vertices"])

    def test_dump_is_stable(self):
        document=load_document(FIXTURES/"two-touching.frame.json")
        with tempfile.TemporaryDirectory() as directory:
            a=Path(directory)/"a.json"; b=Path(directory)/"b.json"
            dump_document(document,a); dump_document(load_document(a),b)
            self.assertEqual(a.read_bytes(),b.read_bytes())

    def test_invalid_duplicate_bubble_id_is_rejected(self):
        raw=json.loads((FIXTURES/"two-touching.frame.json").read_text(encoding="utf-8"))
        raw["bubbles"][1]["id"]=raw["bubbles"][0]["id"]
        with self.assertRaises(ContractValidationError): parse_document(raw)

    def test_future_major_contract_is_rejected(self):
        raw=json.loads((FIXTURES/"single-editable.scenario.json").read_text(encoding="utf-8"))
        raw["contract_version"]="2.0.0"
        with self.assertRaises(ContractValidationError): parse_document(raw)

if __name__=="__main__":
    unittest.main()
