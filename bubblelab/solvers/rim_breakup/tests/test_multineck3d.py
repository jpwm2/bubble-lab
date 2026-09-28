import unittest

from bubblelab.solvers.rim_breakup.benchmarks import (
    benchmark_conservation,
    benchmark_geometry,
    benchmark_interaction,
    benchmark_refinement,
    benchmark_replay,
    benchmark_response,
)
from bubblelab.solvers.rim_breakup.multineck3d import MultiNeck3DConfig, evolve_multineck_breakup


class MultiNeck3DTests(unittest.TestCase):
    def test_default_run_has_multiple_state_derived_detachments(self):
        result = evolve_multineck_breakup()
        self.assertGreaterEqual(len(result.events), 2)
        self.assertGreater(result.geometry_noncoplanarity, 0.15)
        self.assertFalse(result.provenance["event_time_scripting"])
        self.assertFalse(result.provenance["hardcoded_fragment_count"])

    def test_geometry_benchmark(self):
        benchmark_geometry(True)

    def test_interaction_benchmark(self):
        benchmark_interaction(True)

    def test_conservation_benchmark(self):
        benchmark_conservation(True)

    def test_response_benchmark(self):
        benchmark_response(True)

    def test_refinement_benchmark(self):
        benchmark_refinement(True)

    def test_replay_benchmark(self):
        benchmark_replay(True)

    def test_invalid_coplanar_geometry_is_rejected(self):
        base = MultiNeck3DConfig()
        config = MultiNeck3DConfig(
            neck_centers_m=base.neck_centers_m,
            neck_axes=((1.0, 0.0, 0.0),) + base.neck_axes[1:],
        )
        planar = MultiNeck3DConfig(
            neck_centers_m=((0.0,0.0,0.0),(0.003,0.0,0.0),(0.0,0.003,0.0)),
            neck_axes=((1.0,0.0,0.0), base.neck_axes[1], base.neck_axes[2]),
        )
        with self.assertRaises(ValueError):
            evolve_multineck_breakup(planar)
        self.assertGreater(len(evolve_multineck_breakup(config).events), 1)


if __name__ == "__main__":
    unittest.main()
