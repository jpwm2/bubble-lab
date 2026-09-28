"""Narrow adapter between FilmFront/remeshing and reduced-order thin-film transport."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

from bubblelab.solvers.thinfilm import (
    SurfaceMesh,
    SurfaceStepDiagnostics,
    SurfaceTransportParameters,
    SurfaceTransportState,
)
from bubblelab.solvers.thinfilm.surface import Vec3

from .geometry import FilmFront
from .remeshing import ConservativeArealField, RemeshReport


@dataclass(frozen=True)
class ThinFilmTransferDiagnostics:
    liquid_relative_error: float
    surfactant_relative_error: float
    region_identity_preserved: bool


class ThinFilmAttachment:
    """Attach h and Gamma face fields to a tracked transient FilmFront.

    ConservativeArealField stores h*dA and Gamma*dA during remeshing.  Calling
    consume_remesh reconstructs face densities on the new connectivity and reports
    conservation errors without changing topology or firing physical events.
    """

    LIQUID_FIELD = "thinfilm_liquid_volume_m3"
    SURFACTANT_FIELD = "thinfilm_surfactant_mol"

    def __init__(
        self,
        front: FilmFront,
        *,
        thickness_m: float | Sequence[float],
        surfactant_mol_m2: float | Sequence[float] = 0.0,
        parameters: SurfaceTransportParameters | None = None,
    ) -> None:
        self.front = front
        self.parameters = parameters or SurfaceTransportParameters()
        count = len(front.faces)
        h = (
            [float(thickness_m)] * count
            if isinstance(thickness_m, (int, float))
            else [float(value) for value in thickness_m]
        )
        gamma = (
            [float(surfactant_mol_m2)] * count
            if isinstance(surfactant_mol_m2, (int, float))
            else [float(value) for value in surfactant_mol_m2]
        )
        self.state = SurfaceTransportState(
            self._surface_from_front(front),
            h,
            gamma,
            parameters=self.parameters,
        )
        self._fields = self._fields_from_state()

    @staticmethod
    def _surface_from_front(front: FilmFront) -> SurfaceMesh:
        return SurfaceMesh(
            vertices_m=tuple(tuple(value for value in vertex) for vertex in front.vertices),
            faces=tuple(tuple(index for index in face) for face in front.faces),
            mesh_id=front.mesh_id,
            film_id=front.film_id,
        )

    def _fields_from_state(self) -> dict[str, ConservativeArealField]:
        return {
            self.LIQUID_FIELD: ConservativeArealField.from_density(
                self.front,
                self.LIQUID_FIELD,
                lambda index, _point: self.state.thickness_m[index],
            ),
            self.SURFACTANT_FIELD: ConservativeArealField.from_density(
                self.front,
                self.SURFACTANT_FIELD,
                lambda index, _point: self.state.surfactant_mol_m2[index],
            ),
        }

    def conservative_fields(self) -> dict[str, ConservativeArealField]:
        return self._fields

    def advance(
        self,
        dt_s: float,
        *,
        face_velocity_m_s: Sequence[Vec3] | None = None,
        capillary_pressure_pa: Sequence[float] | None = None,
    ) -> SurfaceStepDiagnostics:
        if capillary_pressure_pa is not None:
            values = [float(value) for value in capillary_pressure_pa]
            if len(values) != len(self.state.mesh.faces):
                raise ValueError("capillary pressure must have one value per face")
            self.state.capillary_pressure_pa = values
        diagnostics = self.state.advance(
            dt_s,
            face_velocity_m_s=face_velocity_m_s,
        )
        self._fields = self._fields_from_state()
        tensions = self.state.surface_tension_n_m()
        if tensions:
            self.front.surface_tension_n_m = sum(tensions) / len(tensions)
        return diagnostics

    def consume_remesh(
        self,
        front: FilmFront,
        fields: dict[str, ConservativeArealField],
        report: RemeshReport | None = None,
    ) -> ThinFilmTransferDiagnostics:
        if self.LIQUID_FIELD not in fields or self.SURFACTANT_FIELD not in fields:
            raise ValueError("remeshed thin-film conservative fields are missing")
        liquid = fields[self.LIQUID_FIELD]
        surfactant = fields[self.SURFACTANT_FIELD]
        if len(liquid.face_amounts) != len(front.faces):
            raise ValueError("liquid remesh field has wrong face count")
        if len(surfactant.face_amounts) != len(front.faces):
            raise ValueError("surfactant remesh field has wrong face count")

        old_liquid = self.state.liquid_amount_m3()
        old_surfactant = self.state.surfactant_amount_mol()
        surface = self._surface_from_front(front)
        areas = surface.face_areas_m2()
        h = [amount / area for amount, area in zip(liquid.face_amounts, areas)]
        gamma = [
            amount / area
            for amount, area in zip(surfactant.face_amounts, areas)
        ]
        self.front = front
        self.state = SurfaceTransportState(
            surface,
            h,
            gamma,
            parameters=self.parameters,
        )
        self._fields = fields
        new_liquid = self.state.liquid_amount_m3()
        new_surfactant = self.state.surfactant_amount_mol()
        identity = (
            surface.mesh_id == front.mesh_id
            and surface.film_id == front.film_id
            and (
                True
                if report is None
                else report.region_identity_preserved
            )
        )
        return ThinFilmTransferDiagnostics(
            liquid_relative_error=abs(new_liquid - old_liquid)
            / max(abs(old_liquid), 1.0e-300),
            surfactant_relative_error=abs(new_surfactant - old_surfactant)
            / max(abs(old_surfactant), 1.0e-300),
            region_identity_preserved=identity,
        )

    def surface_tension_n_m(self) -> tuple[float, ...]:
        return self.state.surface_tension_n_m()

    def marangoni_gradient_n_m2(self) -> tuple[Vec3, ...]:
        return self.state.marangoni_gradient_n_m2()
