"""Production deterministic parent-to-children fragmentation event bookkeeping."""
from __future__ import annotations

from dataclasses import asdict, dataclass
import hashlib
import json
import math
from typing import Any

from .geometry import TriMesh, Vec3, add, mul, norm, sub
from .neck import NeckCriteria, NeckDiagnostic, diagnose_neck
from .surgery import MeshSplit, UnsupportedFragmentation, split_mesh_by_plane


def stable_id(prefix: str, *parts: object) -> str:
    payload = json.dumps(parts, sort_keys=True, separators=(",", ":"), ensure_ascii=True, default=str)
    digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()[:20]
    return f"{prefix}-{digest}"


def _allocate(total: float | None, fraction: float) -> tuple[float | None, float | None]:
    if total is None:
        return None, None
    first = total * fraction
    return first, total - first


def _relative_scalar(reference: float, value: float) -> float:
    return abs(value - reference) / max(abs(reference), 1.0e-300)


def _vector_error(reference: Vec3, value: Vec3, scale: float) -> float:
    return norm(sub(value, reference)) / max(scale, 1.0e-300)


@dataclass(frozen=True)
class ParentState:
    id: str
    mesh: TriMesh
    target_volume_m3: float
    gas_amount_mol: float | None
    velocity_m_s: Vec3 = (0.0, 0.0, 0.0)
    mass_kg: float | None = None
    temperature_k: float = 298.15
    gas_species: str | None = "air"

    def __post_init__(self) -> None:
        if not self.id:
            raise ValueError("parent id must be non-empty")
        if self.target_volume_m3 <= 0.0 or not math.isfinite(self.target_volume_m3):
            raise ValueError("target volume must be finite and positive")
        if self.gas_amount_mol is not None and (self.gas_amount_mol < 0.0 or not math.isfinite(self.gas_amount_mol)):
            raise ValueError("gas amount must be finite and non-negative when available")
        if self.mass_kg is not None and (self.mass_kg < 0.0 or not math.isfinite(self.mass_kg)):
            raise ValueError("mass must be finite and non-negative when available")
        if self.temperature_k <= 0.0 or not math.isfinite(self.temperature_k):
            raise ValueError("temperature must be finite and positive")


@dataclass(frozen=True)
class ChildState:
    id: str
    side: str
    mesh: TriMesh
    target_volume_m3: float
    represented_volume_m3: float
    gas_amount_mol: float | None
    centroid_m: Vec3
    velocity_m_s: Vec3
    mass_kg: float | None
    temperature_k: float
    gas_species: str | None
    lineage: tuple[str, ...]
    status: str = "ALIVE"
    geometry_status: str = "CUT_CAP_RESTART_REQUIRES_PHYSICAL_RELAXATION"

    @property
    def equivalent_radius_m(self) -> float:
        return (3.0 * self.target_volume_m3 / (4.0 * math.pi)) ** (1.0 / 3.0)


@dataclass(frozen=True)
class FragmentationResult:
    parent_id: str
    parent_status: str
    children: tuple[ChildState, ChildState]
    event_id: str
    event_time_s: float
    diagnostic: NeckDiagnostic
    surgery: MeshSplit
    conservation: dict[str, float | None | str]
    solver_provenance: dict[str, Any]

    def event_contract(self) -> dict[str, Any]:
        return {
            "id": self.event_id,
            "type": "SPLIT",
            "time_s": self.event_time_s,
            "bubble_ids_before": [self.parent_id],
            "bubble_ids_after": [child.id for child in self.children],
            "film_ids": [],
            "provenance": {
                "source": "SOLVER",
                "detail": "deterministic triangulated neck cut/cap topology surgery",
                **self.solver_provenance,
            },
            "criterion": "MESH_CROSS_SECTIONAL_NECK_AND_SINGLE_SEPARATING_CUT",
            "lineage": {child.id: [self.parent_id] for child in self.children},
            "conservation": dict(self.conservation),
            "restart_geometry_status": "REQUIRES_PHYSICAL_RELAXATION",
            "fidelity_boundary": {
                "singular_pinch_off_cfd": "NOT_RESOLVED",
                "retracting_liquid_rim": "NOT_RESOLVED",
                "droplet_spray": "NOT_RESOLVED",
                "arbitrary_multi_neck_topology": "NOT_SUPPORTED",
            },
        }


def split_parent(
    parent: ParentState,
    *,
    event_time_s: float,
    criteria: NeckCriteria | None = None,
    geometry_volume_tolerance: float = 5.0e-11,
) -> FragmentationResult:
    if event_time_s < 0.0 or not math.isfinite(event_time_s):
        raise ValueError("event_time_s must be finite and non-negative")
    criteria = criteria or NeckCriteria()
    diagnostic = diagnose_neck(parent.mesh, criteria)
    if not diagnostic.detected:
        raise UnsupportedFragmentation(diagnostic.rejection_reason or "no fragmentation neck detected")
    if not diagnostic.eligible or diagnostic.cut_coordinate is None:
        raise UnsupportedFragmentation(diagnostic.rejection_reason or "fragmentation neck is not eligible")
    surgery = split_mesh_by_plane(
        parent.mesh,
        origin=diagnostic.origin,
        axis=diagnostic.axis,
        coordinate=diagnostic.cut_coordinate,
        volume_tolerance=geometry_volume_tolerance,
    )
    v_geom = (surgery.negative.mesh.volume(), surgery.positive.mesh.volume())
    geom_total = math.fsum(v_geom)
    fractions = (v_geom[0] / geom_total, v_geom[1] / geom_total)
    target0, target1 = _allocate(parent.target_volume_m3, fractions[0])
    gas0, gas1 = _allocate(parent.gas_amount_mol, fractions[0])
    mass0, mass1 = _allocate(parent.mass_kg, fractions[0])
    assert target0 is not None and target1 is not None
    event_id = stable_id(
        "split",
        parent.id,
        float(event_time_s).hex(),
        parent.mesh.digest(),
        float(diagnostic.cut_coordinate).hex(),
        asdict(criteria),
    )
    child_ids = (
        stable_id("bubble", parent.id, event_id, "negative-axis"),
        stable_id("bubble", parent.id, event_id, "positive-axis"),
    )
    centroids = (surgery.negative.mesh.volume_centroid(), surgery.positive.mesh.volume_centroid())
    children = (
        ChildState(
            child_ids[0], "NEGATIVE_AXIS", surgery.negative.mesh, target0, v_geom[0], gas0,
            centroids[0], parent.velocity_m_s, mass0, parent.temperature_k, parent.gas_species, (parent.id,)
        ),
        ChildState(
            child_ids[1], "POSITIVE_AXIS", surgery.positive.mesh, target1, v_geom[1], gas1,
            centroids[1], parent.velocity_m_s, mass1, parent.temperature_k, parent.gas_species, (parent.id,)
        ),
    )
    gas_error = None
    if parent.gas_amount_mol is not None and gas0 is not None and gas1 is not None:
        gas_error = _relative_scalar(parent.gas_amount_mol, math.fsum((gas0, gas1)))
    target_error = _relative_scalar(parent.target_volume_m3, math.fsum((target0, target1)))
    parent_centroid = parent.mesh.volume_centroid()
    child_com = tuple(
        (v_geom[0] * centroids[0][axis] + v_geom[1] * centroids[1][axis]) / geom_total
        for axis in range(3)
    )
    length_scale = max(parent.mesh.volume() ** (1.0 / 3.0), parent.mesh.mean_edge_length(), 1.0e-300)
    com_error = _vector_error(parent_centroid, child_com, length_scale)
    momentum_error = None
    if parent.mass_kg is not None and mass0 is not None and mass1 is not None:
        before = mul(parent.velocity_m_s, parent.mass_kg)
        after = add(mul(parent.velocity_m_s, mass0), mul(parent.velocity_m_s, mass1))
        momentum_error = _vector_error(before, after, max(norm(before), parent.mass_kg * 1.0e-12, 1.0e-300))
    conservation: dict[str, float | None | str] = {
        "gas_amount_relative_error": gas_error,
        "target_volume_relative_error": target_error,
        "geometric_volume_relative_error": surgery.geometric_volume_relative_error,
        "center_of_mass_scale_relative_error": com_error,
        "linear_momentum_relative_error": momentum_error,
        "surface_energy_accounting": "UNRESOLVED_SINGULAR_PINCH_EVENT",
    }
    provenance = {
        "solver": "fragmentation-topology",
        "version": "1.0.0",
        "parent_mesh_digest": parent.mesh.digest(),
        "cut_coordinate": diagnostic.cut_coordinate,
        "neck_radius": diagnostic.neck_radius,
        "mesh_spacing": diagnostic.mesh_spacing,
        "radius_to_spacing": diagnostic.radius_to_spacing,
        "prominence_ratio": diagnostic.prominence_ratio,
        "geometric_volume_tolerance": geometry_volume_tolerance,
    }
    return FragmentationResult(
        parent_id=parent.id,
        parent_status="SPLIT",
        children=children,
        event_id=event_id,
        event_time_s=event_time_s,
        diagnostic=diagnostic,
        surgery=surgery,
        conservation=conservation,
        solver_provenance=provenance,
    )
