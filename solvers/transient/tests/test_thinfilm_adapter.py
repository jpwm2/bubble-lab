from __future__ import annotations

import unittest

from bubblelab.solvers.thinfilm.surface import SurfaceTransportParameters
from bubblelab.solvers.transient.geometry import icosphere
from bubblelab.solvers.transient.remeshing import FrontRemesher, RemeshConfig
from bubblelab.solvers.transient.thinfilm_adapter import ThinFilmAttachment


class ThinFilmAdapterTests(unittest.TestCase):
    def test_attach_advance_and_marangoni_hook(self):
        front = icosphere(radius_m=0.008, subdivisions=1)
        count = len(front.faces)
        attachment = ThinFilmAttachment(
            front,
            thickness_m=8.0e-6,
            surfactant_mol_m2=[
                1.0e-6 if index % 2 == 0 else 2.0e-6
                for index in range(count)
            ],
            parameters=SurfaceTransportParameters(
                gravity_m_s2=(0.0, 0.0, 0.0),
                surfactant_diffusivity_m2_s=1.0e-9,
            ),
        )
        initial_liquid = attachment.state.liquid_amount_m3()
        diag = attachment.advance(1.0e-3)
        self.assertLessEqual(diag.liquid_relative_drift, 1.0e-12)
        self.assertAlmostEqual(attachment.state.liquid_amount_m3(), initial_liquid, places=18)
        self.assertEqual(len(attachment.surface_tension_n_m()), count)
        self.assertEqual(len(attachment.marangoni_gradient_n_m2()), count)

    def test_conservative_fields_survive_remesh_and_keep_ids(self):
        front = icosphere(radius_m=0.008, subdivisions=1)
        count = len(front.faces)
        attachment = ThinFilmAttachment(
            front,
            thickness_m=[8.0e-6 * (1.0 + 0.01 * (index % 3)) for index in range(count)],
            surfactant_mol_m2=[2.0e-6] * count,
        )
        fields = attachment.conservative_fields()
        initial_liquid = attachment.state.liquid_amount_m3()
        initial_surfactant = attachment.state.surfactant_amount_mol()
        mesh_id = front.mesh_id
        film_id = front.film_id
        remesher = FrontRemesher(
            RemeshConfig(
                mode="interval",
                target_edge_length_m=front.mean_edge_length(),
                max_geometry_relative_error=1.0e-12,
            )
        )
        edge = tuple(sorted(front.faces[0][:2]))
        self.assertTrue(remesher.split_edge(front, edge, fields, fraction=0.08))
        transfer = attachment.consume_remesh(front, fields)
        self.assertLessEqual(transfer.liquid_relative_error, 1.0e-10)
        self.assertLessEqual(transfer.surfactant_relative_error, 1.0e-10)
        self.assertAlmostEqual(attachment.state.liquid_amount_m3(), initial_liquid, places=18)
        self.assertAlmostEqual(attachment.state.surfactant_amount_mol(), initial_surfactant, places=18)
        self.assertEqual(front.mesh_id, mesh_id)
        self.assertEqual(front.film_id, film_id)
        self.assertTrue(transfer.region_identity_preserved)


if __name__ == "__main__":
    unittest.main()
