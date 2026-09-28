from __future__ import annotations
import copy, json, tempfile, unittest
from pathlib import Path
from bubblelab.runtime.bundle import ReplayBundleValidationError, validate_replay_bundle
from bubblelab.runtime.runner import UnsupportedScenarioFeature, run_scenario

ROOT=Path(__file__).resolve().parents[3]
SCENARIOS=ROOT/"bubblelab"/"scenarios"/"runtime"
def load(name): return json.loads((SCENARIOS/name).read_text(encoding="utf-8"))

class RuntimeTests(unittest.TestCase):
    def test_equilibrium_bundle_validates_and_repeats(self):
        scenario=load("equilibrium-single.scenario.json")
        with tempfile.TemporaryDirectory() as a, tempfile.TemporaryDirectory() as b:
            ra=run_scenario(scenario,"equilibrium",a)
            rb=run_scenario(scenario,"equilibrium",b)
            validate_replay_bundle(a); validate_replay_bundle(b)
            self.assertEqual((Path(a)/"replay.json").read_bytes(),(Path(b)/"replay.json").read_bytes())
            self.assertEqual((Path(a)/ra["frames"][0]["path"]).read_bytes(),(Path(b)/rb["frames"][0]["path"]).read_bytes())
            self.assertEqual(ra["backend"]["identity"],"bubblelab-equilibrium")

    def test_transient_bundle_has_exact_requested_frame_count_and_repeats(self):
        scenario=load("transient-wind.scenario.json")
        with tempfile.TemporaryDirectory() as a, tempfile.TemporaryDirectory() as b:
            ra=run_scenario(scenario,"transient",a,frames=3)
            rb=run_scenario(scenario,"transient",b,frames=3)
            validate_replay_bundle(a); validate_replay_bundle(b)
            self.assertEqual(len(ra["frames"]),3)
            self.assertEqual((Path(a)/"replay.json").read_bytes(),(Path(b)/"replay.json").read_bytes())
            for x,y in zip(ra["frames"],rb["frames"]):
                self.assertEqual((Path(a)/x["path"]).read_bytes(),(Path(b)/y["path"]).read_bytes())

    def test_radius_volume_mismatch_fails(self):
        scenario=load("equilibrium-single.scenario.json")
        scenario["initial_bubbles"][0]["volume_m3"]*=2
        with tempfile.TemporaryDirectory() as out:
            with self.assertRaises(ValueError): run_scenario(scenario,"equilibrium",out)

    def test_unsupported_requested_feature_is_explicit(self):
        scenario=load("transient-wind.scenario.json")
        scenario["requested_solver"]["features"]["drainage"]=True
        with tempfile.TemporaryDirectory() as out:
            with self.assertRaisesRegex(UnsupportedScenarioFeature,"drainage"): run_scenario(scenario,"transient",out)

    def test_validator_rejects_missing_and_duplicate_frames(self):
        scenario=load("equilibrium-single.scenario.json")
        with tempfile.TemporaryDirectory() as out:
            replay=run_scenario(scenario,"equilibrium",out)
            p=Path(out)/"replay.json"; data=json.loads(p.read_text())
            data["frames"].append(copy.deepcopy(data["frames"][0]))
            p.write_text(json.dumps(data),encoding="utf-8")
            with self.assertRaisesRegex(ReplayBundleValidationError,"duplicate"): validate_replay_bundle(out)

if __name__=="__main__": unittest.main()
