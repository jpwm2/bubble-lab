"""Deterministic topology-event state for rupture and coalescence.

The event layer is intentionally solver-neutral.  It consumes reduced physical state,
records explicit topology transitions, and produces a conservative restart geometry.
It does not perform post-event CFD relaxation.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, replace
import hashlib
import json
import math
from typing import Any, Iterable

Vec3 = tuple[float, float, float]
Face = tuple[int, int, int]
EXTERIOR = "EXTERIOR"
_BUBBLE_STATUSES = {"ALIVE", "RUPTURED", "MERGED", "SPLIT", "REMOVED"}
_EVENT_TYPES = {"RUPTURE", "COALESCENCE"}


def _finite_vec3(value: Iterable[float], name: str) -> Vec3:
    values = tuple(float(component) for component in value)
    if len(values) != 3 or any(not math.isfinite(component) for component in values):
        raise ValueError(f"{name} must contain three finite values")
    return values  # type: ignore[return-value]


def _weighted_vec3(items: Iterable[tuple[float, Vec3]]) -> Vec3:
    weighted = list(items)
    total = math.fsum(weight for weight, _ in weighted)
    if total <= 0.0:
        if not weighted:
            return (0.0, 0.0, 0.0)
        count = float(len(weighted))
        return tuple(math.fsum(vec[axis] for _, vec in weighted) / count for axis in range(3))  # type: ignore[return-value]
    return tuple(
        math.fsum(weight * vec[axis] for weight, vec in weighted) / total
        for axis in range(3)
    )  # type: ignore[return-value]


def stable_id(prefix: str, *parts: object) -> str:
    """Return a deterministic compact identifier from canonical JSON input."""
    payload = json.dumps(parts, sort_keys=True, separators=(",", ":"), ensure_ascii=True, default=str)
    digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()[:20]
    return f"{prefix}-{digest}"


@dataclass(frozen=True)
class RestartGeometry:
    """Closed restart surface whose polyhedral volume matches the target exactly.

    A regular octahedron is deliberately used instead of pretending the immediate
    post-coalescence shape has already relaxed to a sphere.  The geometry is coarse
    but deterministic, closed, centroid-preserving, and suitable as a seed for a
    later surface or transient relaxation stage.
    """

    kind: str
    vertices_m: tuple[Vec3, ...]
    faces: tuple[Face, ...]
    target_volume_m3: float
    requires_relaxation: bool = True

    @classmethod
    def volume_matched_octahedron(cls, target_volume_m3: float, centroid_m: Vec3) -> "RestartGeometry":
        if target_volume_m3 <= 0.0 or not math.isfinite(target_volume_m3):
            raise ValueError("target restart volume must be finite and positive")
        cx, cy, cz = _finite_vec3(centroid_m, "centroid_m")
        a = (0.75 * target_volume_m3) ** (1.0 / 3.0)
        vertices: tuple[Vec3, ...] = (
            (cx + a, cy, cz),
            (cx - a, cy, cz),
            (cx, cy + a, cz),
            (cx, cy - a, cz),
            (cx, cy, cz + a),
            (cx, cy, cz - a),
        )
        faces: tuple[Face, ...] = (
            (0, 2, 4),
            (0, 4, 3),
            (0, 3, 5),
            (0, 5, 2),
            (1, 4, 2),
            (1, 3, 4),
            (1, 5, 3),
            (1, 2, 5),
        )
        geometry = cls(
            kind="VOLUME_MATCHED_OCTAHEDRON",
            vertices_m=vertices,
            faces=faces,
            target_volume_m3=float(target_volume_m3),
            requires_relaxation=True,
        )
        actual = geometry.volume_m3()
        if actual <= 0.0:
            raise RuntimeError("restart geometry has non-positive volume")
        scale = (target_volume_m3 / actual) ** (1.0 / 3.0)
        if abs(scale - 1.0) > 4.0e-16:
            scaled = tuple(
                (
                    cx + (x - cx) * scale,
                    cy + (y - cy) * scale,
                    cz + (z - cz) * scale,
                )
                for x, y, z in vertices
            )
            geometry = replace(geometry, vertices_m=scaled)
        return geometry

    def signed_volume_m3(self) -> float:
        terms = []
        for ia, ib, ic in self.faces:
            a, b, c = self.vertices_m[ia], self.vertices_m[ib], self.vertices_m[ic]
            cross = (
                b[1] * c[2] - b[2] * c[1],
                b[2] * c[0] - b[0] * c[2],
                b[0] * c[1] - b[1] * c[0],
            )
            terms.append((a[0] * cross[0] + a[1] * cross[1] + a[2] * cross[2]) / 6.0)
        return math.fsum(terms)

    def volume_m3(self) -> float:
        return abs(self.signed_volume_m3())

    def volume_relative_error(self) -> float:
        return abs(self.volume_m3() - self.target_volume_m3) / self.target_volume_m3


@dataclass(frozen=True)
class BubbleState:
    id: str
    volume_m3: float
    gas_amount_mol: float | None
    centroid_m: Vec3 = (0.0, 0.0, 0.0)
    velocity_m_s: Vec3 = (0.0, 0.0, 0.0)
    temperature_k: float = 298.15
    mass_kg: float | None = None
    gas_species: str | None = "air"
    molar_mass_kg_mol: float | None = None
    status: str = "ALIVE"
    lineage: tuple[str, ...] = ()
    restart_geometry: RestartGeometry | None = None

    def __post_init__(self) -> None:
        if not self.id:
            raise ValueError("bubble id must be non-empty")
        if self.volume_m3 <= 0.0 or not math.isfinite(self.volume_m3):
            raise ValueError("bubble volume must be finite and positive")
        if self.gas_amount_mol is not None and (self.gas_amount_mol < 0.0 or not math.isfinite(self.gas_amount_mol)):
            raise ValueError("gas amount must be finite and non-negative when available")
        if self.temperature_k <= 0.0 or not math.isfinite(self.temperature_k):
            raise ValueError("temperature must be finite and positive")
        if self.mass_kg is not None and (self.mass_kg < 0.0 or not math.isfinite(self.mass_kg)):
            raise ValueError("mass must be finite and non-negative when available")
        if self.molar_mass_kg_mol is not None and (self.molar_mass_kg_mol <= 0.0 or not math.isfinite(self.molar_mass_kg_mol)):
            raise ValueError("molar mass must be finite and positive when available")
        if self.status not in _BUBBLE_STATUSES:
            raise ValueError(f"unsupported bubble status {self.status!r}")
        object.__setattr__(self, "centroid_m", _finite_vec3(self.centroid_m, "centroid_m"))
        object.__setattr__(self, "velocity_m_s", _finite_vec3(self.velocity_m_s, "velocity_m_s"))

    @property
    def equivalent_radius_m(self) -> float:
        return (3.0 * self.volume_m3 / (4.0 * math.pi)) ** (1.0 / 3.0)

    @property
    def inferred_mass_kg(self) -> float | None:
        if self.mass_kg is not None:
            return self.mass_kg
        if self.gas_amount_mol is not None and self.molar_mass_kg_mol is not None:
            return self.gas_amount_mol * self.molar_mass_kg_mol
        return None

    @property
    def pressure_pa(self) -> float | None:
        if self.gas_amount_mol is None:
            return None
        return self.gas_amount_mol * 8.31446261815324 * self.temperature_k / self.volume_m3


@dataclass(frozen=True)
class SharedFilmState:
    id: str
    adjacent: tuple[str, str]
    min_thickness_m: float
    mean_thickness_m: float
    area_m2: float
    surface_tension_n_m: float
    mesh_id: str | None = None
    status: str = "ACTIVE"
    rupture_time_s: float | None = None

    def __post_init__(self) -> None:
        if not self.id:
            raise ValueError("film id must be non-empty")
        if len(self.adjacent) != 2 or self.adjacent[0] == self.adjacent[1]:
            raise ValueError("film adjacency must contain two distinct regions")
        if (
            self.min_thickness_m < 0.0
            or self.mean_thickness_m < 0.0
            or not math.isfinite(self.min_thickness_m)
            or not math.isfinite(self.mean_thickness_m)
        ):
            raise ValueError("film thickness must be finite and non-negative")
        if self.area_m2 <= 0.0 or not math.isfinite(self.area_m2):
            raise ValueError("film area must be finite and positive")
        if self.surface_tension_n_m < 0.0 or not math.isfinite(self.surface_tension_n_m):
            raise ValueError("surface tension must be finite and non-negative")
        if self.status not in {"ACTIVE", "RUPTURED", "REMOVED"}:
            raise ValueError("unsupported film status")


@dataclass(frozen=True)
class TopologyEvent:
    id: str
    type: str
    time_s: float
    bubble_ids_before: tuple[str, ...]
    bubble_ids_after: tuple[str, ...]
    film_ids: tuple[str, ...]
    provenance: dict[str, Any]
    pre_event_state_ref: str
    criterion: str | None = None
    threshold_m: float | None = None
    lineage: dict[str, tuple[str, ...]] | None = None
    conservation: dict[str, Any] | None = None

    def __post_init__(self) -> None:
        if not self.id:
            raise ValueError("event id must be non-empty")
        if self.type not in _EVENT_TYPES:
            raise ValueError(f"unsupported event type {self.type!r}")
        if self.time_s < 0.0 or not math.isfinite(self.time_s):
            raise ValueError("event time must be finite and non-negative")
        if self.provenance.get("source") not in {"SOLVER", "USER", "IMPORT", "TEST_FIXTURE"}:
            raise ValueError("event provenance source is invalid")
        if not self.pre_event_state_ref:
            raise ValueError("pre-event state reference must be non-empty")

    def to_contract(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            "id": self.id,
            "type": self.type,
            "time_s": self.time_s,
            "bubble_ids_before": list(self.bubble_ids_before),
            "bubble_ids_after": list(self.bubble_ids_after),
            "film_ids": list(self.film_ids),
            "provenance": dict(self.provenance),
            "pre_event_state_ref": self.pre_event_state_ref,
        }
        if self.criterion is not None:
            result["criterion"] = self.criterion
        if self.threshold_m is not None:
            result["threshold_m"] = self.threshold_m
        if self.lineage is not None:
            result["lineage"] = {child: list(parents) for child, parents in self.lineage.items()}
        if self.conservation is not None:
            result["conservation"] = self.conservation
        return result


@dataclass(frozen=True)
class EventState:
    bubbles: dict[str, BubbleState]
    active_films: dict[str, SharedFilmState]
    retired_films: dict[str, SharedFilmState]
    events: tuple[TopologyEvent, ...] = ()
    seed: int = 0

    def __post_init__(self) -> None:
        if self.seed < 0:
            raise ValueError("seed must be non-negative")
        if set(self.active_films).intersection(self.retired_films):
            raise ValueError("a film cannot be active and retired simultaneously")
        for key, bubble in self.bubbles.items():
            if key != bubble.id:
                raise ValueError("bubble mapping key must match bubble id")
        for collection in (self.active_films, self.retired_films):
            for key, film in collection.items():
                if key != film.id:
                    raise ValueError("film mapping key must match film id")

    def active_bubbles(self) -> dict[str, BubbleState]:
        return {key: bubble for key, bubble in self.bubbles.items() if bubble.status == "ALIVE"}

    def with_film(self, film: SharedFilmState) -> "EventState":
        if film.id not in self.active_films:
            raise KeyError(film.id)
        active = dict(self.active_films)
        active[film.id] = film
        return replace(self, active_films=active)

    def digest(self) -> str:
        def bubble_payload(bubble: BubbleState) -> dict[str, Any]:
            data = asdict(bubble)
            if bubble.restart_geometry is not None:
                data["restart_geometry"] = asdict(bubble.restart_geometry)
            return data

        payload = {
            "seed": self.seed,
            "bubbles": {key: bubble_payload(self.bubbles[key]) for key in sorted(self.bubbles)},
            "active_films": {key: asdict(self.active_films[key]) for key in sorted(self.active_films)},
            "retired_films": {key: asdict(self.retired_films[key]) for key in sorted(self.retired_films)},
            "events": [event.to_contract() for event in self.events],
        }
        encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False)
        return "sha256:" + hashlib.sha256(encoded.encode("utf-8")).hexdigest()

    def canonical_payload(self) -> dict[str, Any]:
        return {
            "state_ref": self.digest(),
            "seed": self.seed,
            "bubbles": {
                key: {
                    "id": bubble.id,
                    "volume_m3": bubble.volume_m3,
                    "gas_amount_mol": bubble.gas_amount_mol,
                    "centroid_m": list(bubble.centroid_m),
                    "velocity_m_s": list(bubble.velocity_m_s),
                    "temperature_k": bubble.temperature_k,
                    "mass_kg": bubble.mass_kg,
                    "status": bubble.status,
                    "lineage": list(bubble.lineage),
                    "restart_geometry": None if bubble.restart_geometry is None else {
                        "kind": bubble.restart_geometry.kind,
                        "target_volume_m3": bubble.restart_geometry.target_volume_m3,
                        "represented_volume_m3": bubble.restart_geometry.volume_m3(),
                        "volume_relative_error": bubble.restart_geometry.volume_relative_error(),
                    },
                }
                for key, bubble in sorted(self.bubbles.items())
            },
            "active_films": {
                key: asdict(film) for key, film in sorted(self.active_films.items())
            },
            "retired_films": {
                key: asdict(film) for key, film in sorted(self.retired_films.items())
            },
            "events": [event.to_contract() for event in self.events],
        }


def merged_temperature_k(a: BubbleState, b: BubbleState) -> float:
    if a.gas_amount_mol is not None and b.gas_amount_mol is not None:
        total = math.fsum((a.gas_amount_mol, b.gas_amount_mol))
        if total > 0.0:
            return math.fsum((a.gas_amount_mol * a.temperature_k, b.gas_amount_mol * b.temperature_k)) / total
    return _weighted_vec3(((a.volume_m3, (a.temperature_k, 0.0, 0.0)), (b.volume_m3, (b.temperature_k, 0.0, 0.0))))[0]


def merge_centroid_and_velocity(a: BubbleState, b: BubbleState) -> tuple[Vec3, Vec3, float | None, str]:
    mass_a = a.inferred_mass_kg
    mass_b = b.inferred_mass_kg
    if mass_a is not None and mass_b is not None and math.fsum((mass_a, mass_b)) > 0.0:
        centroid = _weighted_vec3(((mass_a, a.centroid_m), (mass_b, b.centroid_m)))
        velocity = _weighted_vec3(((mass_a, a.velocity_m_s), (mass_b, b.velocity_m_s)))
        return centroid, velocity, math.fsum((mass_a, mass_b)), "MASS_WEIGHTED"
    centroid = _weighted_vec3(((a.volume_m3, a.centroid_m), (b.volume_m3, b.centroid_m)))
    velocity = _weighted_vec3(((a.volume_m3, a.velocity_m_s), (b.volume_m3, b.velocity_m_s)))
    return centroid, velocity, None, "VOLUME_WEIGHTED_FALLBACK"
