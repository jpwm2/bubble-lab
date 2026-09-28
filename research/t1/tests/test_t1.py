from __future__ import annotations

import unittest

from bubblelab.research.t1.benchmarks import eligibility_benchmark, neighbor_switch_benchmark, refinement_benchmark
from bubblelab.research.t1.model import build_pre_t1_network, combine_disjoint_networks, translate_network
from bubblelab.research.t1.prototype import detect_eligibility, perform_neighbor_switch


class T1ResearchTests(unittest.TestCase):
    def test_geometry_is_embedded_in_region_cells_and_plateau_lines(self) -> None:
        network = build_pre_t1_network(0.12)
        network.validate()
        self.assertEqual(5, len(network.films))
        self.assertEqual(2, len(network.junctions))
        self.assertTrue(all(len(j.incident_film_ids) == 3 for j in network.junctions))
        self.assertTrue(all(film.mesh.area() > 0.0 for film in network.films))
        self.assertEqual(set(network.region_ids), set(network.geometric_volume_by_id()))

    def test_eligibility_identifies_exact_four_region_neighborhood(self) -> None:
        result = detect_eligibility(build_pre_t1_network(0.12))
        self.assertTrue(result.eligible, result.reason)
        self.assertIsNotNone(result.neighborhood)
        assert result.neighborhood is not None
        self.assertEqual(("A", "B"), result.neighborhood.old_adjacent_regions)
        self.assertEqual(("C", "D"), result.neighborhood.opposite_regions)
        self.assertEqual(("film:AB:central",), result.candidate_film_ids)
        self.assertLess(result.collapsing_length_m, result.threshold_m)

    def test_eligibility_rejects_coarse_geometry(self) -> None:
        result = detect_eligibility(build_pre_t1_network(0.8))
        self.assertFalse(result.eligible)
        self.assertIn("under-resolved", result.reason)

    def test_eligibility_rejects_ambiguous_simultaneous_collapses(self) -> None:
        one = build_pre_t1_network(0.12)
        two = translate_network(build_pre_t1_network(0.12, id_prefix="x:"), 3.0, 0.0)
        result = detect_eligibility(combine_disjoint_networks(one, two))
        self.assertFalse(result.eligible)
        self.assertEqual("ambiguous simultaneous collapses", result.reason)

    def test_neighbor_switch_preserves_regions_and_rewires_adjacency(self) -> None:
        result = perform_neighbor_switch(build_pre_t1_network(0.12))
        before_pairs = {tuple(sorted(film.adjacent)) for film in result.before.films}
        after_pairs = {tuple(sorted(film.adjacent)) for film in result.after.films}
        self.assertIn(("A", "B"), before_pairs)
        self.assertNotIn(("A", "B"), after_pairs)
        self.assertNotIn(("C", "D"), before_pairs)
        self.assertIn(("C", "D"), after_pairs)
        self.assertEqual(result.before.region_ids, result.after.region_ids)
        self.assertEqual(1, len(result.lineage.retired_film_ids))
        self.assertEqual(1, len(result.lineage.created_film_ids))
        self.assertEqual(2, len(result.lineage.retired_junction_ids))
        self.assertEqual(2, len(result.lineage.created_junction_ids))
        result.after.validate()

    def test_neighbor_switch_is_deterministic(self) -> None:
        one = perform_neighbor_switch(build_pre_t1_network(0.12))
        two = perform_neighbor_switch(build_pre_t1_network(0.12))
        self.assertEqual(one.after.topology_signature(), two.after.topology_signature())
        self.assertEqual(one.lineage, two.lineage)
        self.assertEqual(one.after.region_cells_xy, two.after.region_cells_xy)

    def test_benchmarks_pass(self) -> None:
        self.assertTrue(eligibility_benchmark()["pass"])
        self.assertTrue(neighbor_switch_benchmark()["pass"])
        self.assertTrue(refinement_benchmark()["pass"])


if __name__ == "__main__":
    unittest.main()
