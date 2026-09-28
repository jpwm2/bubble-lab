import unittest
from bubblelab.validation.final import wave27_suite

class Wave27FinalValidationTests(unittest.TestCase):
    def test_static_audit_preserves_declared_gaps(self):
        result=wave27_suite.build_final_validation(execute=False,assert_honest=False)
        self.assertEqual(result["baseline"],"post-wave-27 accepted main")
        self.assertFalse(result["summary"]["final_acceptance_ready"])
        self.assertEqual(result["completion_audit_summary"]["status_counts"],{"SATISFIED":30,"PARTIAL":8,"DEFERRED":0,"UNVERIFIED":1,"NOT_IMPLEMENTED":0})
        self.assertEqual(result["completion_audit_summary"]["status_changes"],[])
        self.assertEqual(wave27_suite.honesty_issues(),[])
    def test_wave27_evidence_is_explicit_and_bounded(self):
        names={x["name"] for x in wave27_suite.HISTORICAL_EVIDENCE}
        self.assertTrue({"wave27-multievent-topology-gas-network","wave27-3d-multineck-breakup","wave27-liquid-border-global-cfd"} <= names)
        text=" ".join(wave27_suite.CLAIM_BOUNDARIES).lower()
        self.assertIn("unrestricted topology surgery",text)
        self.assertIn("unrestricted singular",text)
        self.assertIn("universal singular plateau-border",text)
    def test_gap_priority_order(self):
        self.assertEqual([x["priority"] for x in wave27_suite.SMALLEST_BLOCKING_GAPS],["physical validity","numerical stability","state/conservation/reproducibility","runtime control","visualization","performance"])

if __name__=="__main__": unittest.main()
