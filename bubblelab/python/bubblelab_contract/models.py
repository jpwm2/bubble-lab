"""Typed reference models for the Bubble Lab contract."""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any, Mapping

CONTRACT_VERSION = "1.0.0"
FEATURE_STATES = {"RESOLVED", "MODELED", "VISUAL_ONLY", "NOT_IMPLEMENTED"}
FIDELITY_TIERS = {"INTERACTIVE", "HIGH_FIDELITY", "MAXIMUM_REALISM"}

@dataclass(frozen=True)
class SimulationManifest:
    units: dict[str, Any]
    solver: dict[str, Any]
    fidelity_tier: str
    feature_disclosures: dict[str, str]
    random_seed: int
    provenance: dict[str, Any]
    contract_version: str = CONTRACT_VERSION
    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "SimulationManifest":
        return cls(dict(data["units"]), dict(data["solver"]), str(data["fidelity_tier"]),
                   dict(data["feature_disclosures"]), int(data["random_seed"]),
                   dict(data["provenance"]), str(data["contract_version"]))
    def to_dict(self) -> dict[str, Any]:
        return {"contract_version": self.contract_version, "units": self.units, "solver": self.solver,
                "fidelity_tier": self.fidelity_tier, "feature_disclosures": self.feature_disclosures,
                "random_seed": self.random_seed, "provenance": self.provenance}

@dataclass(frozen=True)
class EnvironmentState:
    gravity_m_s2: list[float]
    ambient_density_kg_m3: float
    ambient_dynamic_viscosity_pa_s: float
    wind: dict[str, Any] | None = None
    flow_metadata: dict[str, Any] | None = None
    boundary_refs: list[str] | None = None
    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "EnvironmentState":
        return cls(list(data["gravity_m_s2"]), float(data["ambient_density_kg_m3"]),
                   float(data["ambient_dynamic_viscosity_pa_s"]),
                   dict(data["wind"]) if "wind" in data else None,
                   dict(data["flow_metadata"]) if "flow_metadata" in data else None,
                   list(data["boundary_refs"]) if "boundary_refs" in data else None)
    def to_dict(self) -> dict[str, Any]:
        out = {"gravity_m_s2": self.gravity_m_s2,
               "ambient_density_kg_m3": self.ambient_density_kg_m3,
               "ambient_dynamic_viscosity_pa_s": self.ambient_dynamic_viscosity_pa_s}
        for key in ("wind", "flow_metadata", "boundary_refs"):
            value = getattr(self, key)
            if value is not None:
                out[key] = value
        return out

@dataclass(frozen=True)
class BubbleState:
    id: str
    volume_m3: float
    equivalent_radius_m: float
    centroid_m: list[float]
    velocity_m_s: list[float]
    status: str
    pressure_pa: float | None = None
    temperature_k: float | None = None
    gas_amount_mol: float | None = None
    gas_species: str | None = None
    film_material: dict[str, Any] | None = None
    _present_optional: frozenset[str] = field(default_factory=frozenset, repr=False, compare=False)
    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "BubbleState":
        optional = ("pressure_pa","temperature_k","gas_amount_mol","gas_species","film_material")
        kwargs: dict[str, Any] = {
            "id": str(data["id"]), "volume_m3": float(data["volume_m3"]),
            "equivalent_radius_m": float(data["equivalent_radius_m"]),
            "centroid_m": list(data["centroid_m"]), "velocity_m_s": list(data["velocity_m_s"]),
            "status": str(data["status"]), "_present_optional": frozenset(k for k in optional if k in data)}
        for key in ("pressure_pa","temperature_k","gas_amount_mol"):
            if key in data:
                kwargs[key] = None if data[key] is None else float(data[key])
        if "gas_species" in data:
            kwargs["gas_species"] = None if data["gas_species"] is None else str(data["gas_species"])
        if "film_material" in data:
            kwargs["film_material"] = None if data["film_material"] is None else dict(data["film_material"])
        return cls(**kwargs)
    def to_dict(self) -> dict[str, Any]:
        out = {"id":self.id,"volume_m3":self.volume_m3,"equivalent_radius_m":self.equivalent_radius_m,
               "centroid_m":self.centroid_m,"velocity_m_s":self.velocity_m_s,"status":self.status}
        for key in self._present_optional:
            out[key] = getattr(self,key)
        return out

@dataclass(frozen=True)
class SurfaceMesh:
    id: str
    geometry_role: str
    vertex_count: int
    face_count: int
    vertices: dict[str, Any]
    faces: dict[str, Any]
    owner_bubble_ids: list[str] = field(default_factory=list)
    region_labels: list[str] = field(default_factory=list)
    fields: dict[str, Any] = field(default_factory=dict)

@dataclass(frozen=True)
class FilmRegion:
    id: str
    kind: str
    adjacent: list[str]
    surface_tension_n_m: float
    mesh_id: str | None = None
    thickness: dict[str, Any] | None = None

@dataclass(frozen=True)
class Junction:
    id: str
    incident_film_ids: list[str]
    geometry: dict[str, Any] | None = None
    measured_angles_deg: list[float] | None = None
    measurement_provenance: dict[str, Any] | None = None

@dataclass(frozen=True)
class TopologyGraph:
    adjacency: list[dict[str, Any]]
    events: list[dict[str, Any]]

@dataclass(frozen=True)
class SolverDiagnostics:
    timestep_s: float | None = None
    nonlinear_iterations: int | None = None
    linear_iterations: int | None = None
    residuals: dict[str, float] | None = None
    max_relative_volume_error: float | None = None
    mesh_quality: dict[str, Any] | None = None
    compute_time_s: float | None = None

@dataclass(frozen=True)
class Frame:
    frame_id: str
    simulation_time_s: float
    manifest: SimulationManifest
    environment: EnvironmentState
    bubbles: list[BubbleState]
    surface_meshes: list[dict[str, Any]]
    film_regions: list[dict[str, Any]]
    junctions: list[dict[str, Any]]
    topology: dict[str, Any]
    diagnostics: dict[str, Any] | None = None
    checkpoint_state: dict[str, Any] | None = None
    kind: str = "FRAME"
    contract_version: str = CONTRACT_VERSION
    extras: dict[str, Any] = field(default_factory=dict)
    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "Frame":
        known={"contract_version","kind","frame_id","simulation_time_s","manifest","environment","bubbles",
               "surface_meshes","film_regions","junctions","topology","diagnostics","checkpoint_state"}
        return cls(str(data["frame_id"]), float(data["simulation_time_s"]),
                   SimulationManifest.from_dict(data["manifest"]), EnvironmentState.from_dict(data["environment"]),
                   [BubbleState.from_dict(x) for x in data["bubbles"]],
                   [dict(x) for x in data["surface_meshes"]], [dict(x) for x in data["film_regions"]],
                   [dict(x) for x in data["junctions"]], dict(data["topology"]),
                   dict(data["diagnostics"]) if "diagnostics" in data else None,
                   dict(data["checkpoint_state"]) if "checkpoint_state" in data else None,
                   str(data["kind"]), str(data["contract_version"]),
                   {k:v for k,v in data.items() if k not in known})
    def to_dict(self) -> dict[str, Any]:
        out={"contract_version":self.contract_version,"kind":self.kind,"frame_id":self.frame_id,
             "simulation_time_s":self.simulation_time_s,"manifest":self.manifest.to_dict(),
             "environment":self.environment.to_dict(),"bubbles":[x.to_dict() for x in self.bubbles],
             "surface_meshes":self.surface_meshes,"film_regions":self.film_regions,
             "junctions":self.junctions,"topology":self.topology}
        out.update(self.extras)
        if self.diagnostics is not None: out["diagnostics"]=self.diagnostics
        if self.checkpoint_state is not None: out["checkpoint_state"]=self.checkpoint_state
        return out

@dataclass(frozen=True)
class Checkpoint(Frame):
    kind: str = "CHECKPOINT"

@dataclass(frozen=True)
class Scenario:
    scenario_id: str
    random_seed: int
    requested_fidelity_tier: str
    environment: EnvironmentState
    initial_bubbles: list[BubbleState]
    user_editable: dict[str, Any]
    requested_solver: dict[str, Any] | None = None
    initial_surface_meshes: list[dict[str, Any]] | None = None
    initial_film_regions: list[dict[str, Any]] | None = None
    initial_junctions: list[dict[str, Any]] | None = None
    metadata: dict[str, Any] | None = None
    kind: str = "SCENARIO"
    contract_version: str = CONTRACT_VERSION
    _present_optional: frozenset[str] = field(default_factory=frozenset, repr=False, compare=False)
    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "Scenario":
        optional=("requested_solver","initial_surface_meshes","initial_film_regions","initial_junctions","metadata")
        return cls(str(data["scenario_id"]), int(data["random_seed"]), str(data["requested_fidelity_tier"]),
                   EnvironmentState.from_dict(data["environment"]), [BubbleState.from_dict(x) for x in data["initial_bubbles"]],
                   dict(data["user_editable"]),
                   None if data.get("requested_solver") is None else dict(data["requested_solver"]),
                   [dict(x) for x in data["initial_surface_meshes"]] if "initial_surface_meshes" in data else None,
                   [dict(x) for x in data["initial_film_regions"]] if "initial_film_regions" in data else None,
                   [dict(x) for x in data["initial_junctions"]] if "initial_junctions" in data else None,
                   dict(data["metadata"]) if "metadata" in data else None, str(data["kind"]),
                   str(data["contract_version"]), frozenset(k for k in optional if k in data))
    def to_dict(self) -> dict[str, Any]:
        out={"contract_version":self.contract_version,"kind":self.kind,"scenario_id":self.scenario_id,
             "random_seed":self.random_seed,"requested_fidelity_tier":self.requested_fidelity_tier,
             "environment":self.environment.to_dict(),"initial_bubbles":[x.to_dict() for x in self.initial_bubbles],
             "user_editable":self.user_editable}
        for key in self._present_optional: out[key]=getattr(self,key)
        return out
