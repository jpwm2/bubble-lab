"""Adapters from accepted film-network and thin-film state into the event layer."""
from __future__ import annotations

import math
from typing import Iterable, Mapping

from .model import BubbleState, EventState, SharedFilmState

Vec3 = tuple[float, float, float]


def _mapping_by_id(items: Mapping[str, object] | Iterable[object] | None) -> dict[str, object]:
    if items is None:
        return {}
    if isinstance(items, Mapping):
        return dict(items)
    return {str(getattr(item, "id")): item for item in items}


def state_from_thinfilm_pair(
    surface_state: object,
    gas_a: object,
    gas_b: object,
    *,
    film_id: str | None = None,
    centroids_m: Mapping[str, Vec3] | None = None,
    velocities_m_s: Mapping[str, Vec3] | None = None,
    masses_kg: Mapping[str, float] | None = None,
    molar_mass_kg_mol: float | None = None,
    seed: int = 0,
) -> EventState:
    """Build event state from accepted SurfaceTransportState/GasRegionState objects."""
    mesh = getattr(surface_state, "mesh")
    thickness = tuple(float(value) for value in getattr(surface_state, "thickness_m"))
    if not thickness:
        raise ValueError("thin-film state must contain thickness samples")
    areas = tuple(float(value) for value in mesh.face_areas_m2())
    tensions = tuple(float(value) for value in surface_state.surface_tension_n_m())
    resolved_film_id = film_id or str(getattr(mesh, "film_id", "shared-film"))
    a_id = str(getattr(gas_a, "id"))
    b_id = str(getattr(gas_b, "id"))
    centroids_m = centroids_m or {}
    velocities_m_s = velocities_m_s or {}
    masses_kg = masses_kg or {}

    def bubble(gas: object) -> BubbleState:
        identifier = str(getattr(gas, "id"))
        return BubbleState(
            id=identifier,
            volume_m3=float(getattr(gas, "volume_m3")),
            gas_amount_mol=float(getattr(gas, "amount_mol")),
            centroid_m=centroids_m.get(identifier, (0.0, 0.0, 0.0)),
            velocity_m_s=velocities_m_s.get(identifier, (0.0, 0.0, 0.0)),
            temperature_k=float(getattr(gas, "temperature_k", 298.15)),
            mass_kg=masses_kg.get(identifier),
            molar_mass_kg_mol=molar_mass_kg_mol,
        )

    film = SharedFilmState(
        id=resolved_film_id,
        adjacent=(a_id, b_id),
        min_thickness_m=min(thickness),
        mean_thickness_m=math.fsum(thickness) / len(thickness),
        area_m2=math.fsum(areas),
        surface_tension_n_m=math.fsum(tensions) / len(tensions),
        mesh_id=str(getattr(mesh, "mesh_id", resolved_film_id + "-mesh")),
    )
    bubbles = {a_id: bubble(gas_a), b_id: bubble(gas_b)}
    return EventState(bubbles=bubbles, active_films={film.id: film}, retired_films={}, seed=seed)


def state_from_film_network(
    network: object,
    *,
    gas_regions: Mapping[str, object] | Iterable[object] | None = None,
    thinfilm_by_film: Mapping[str, object] | None = None,
    velocities_m_s: Mapping[str, Vec3] | None = None,
    masses_kg: Mapping[str, float] | None = None,
    molar_mass_kg_mol: float | None = None,
    seed: int = 0,
) -> EventState:
    """Adapt accepted FilmNetwork geometry plus optional accepted thin-film/gas state."""
    gases = _mapping_by_id(gas_regions)
    thinfilm_by_film = thinfilm_by_film or {}
    velocities_m_s = velocities_m_s or {}
    masses_kg = masses_kg or {}

    bubbles: dict[str, BubbleState] = {}
    for region in getattr(network, "regions"):
        identifier = str(getattr(region, "id"))
        gas = gases.get(identifier)
        if gas is not None:
            volume = float(getattr(gas, "volume_m3"))
            amount = float(getattr(gas, "amount_mol"))
            temperature = float(getattr(gas, "temperature_k", 298.15))
        else:
            volume = float(getattr(region, "target_volume_m3"))
            amount = None
            temperature = 298.15
        try:
            centroid = tuple(float(value) for value in network.region_centroid(identifier))
        except (AttributeError, ValueError):
            centroid = (0.0, 0.0, 0.0)
        bubbles[identifier] = BubbleState(
            id=identifier,
            volume_m3=volume,
            gas_amount_mol=amount,
            centroid_m=centroid,  # type: ignore[arg-type]
            velocity_m_s=velocities_m_s.get(identifier, (0.0, 0.0, 0.0)),
            temperature_k=temperature,
            mass_kg=masses_kg.get(identifier),
            molar_mass_kg_mol=molar_mass_kg_mol,
        )

    active_films: dict[str, SharedFilmState] = {}
    for patch in getattr(network, "patches"):
        adjacent = tuple(str(value) for value in getattr(patch, "adjacent"))
        if "EXTERIOR" in adjacent:
            continue
        identifier = str(getattr(patch, "id"))
        thinfilm = thinfilm_by_film.get(identifier)
        if thinfilm is not None:
            samples = tuple(float(value) for value in getattr(thinfilm, "thickness_m"))
            min_thickness = min(samples)
            mean_thickness = math.fsum(samples) / len(samples)
        else:
            raise ValueError(
                f"shared film {identifier!r} requires accepted thin-film thickness state"
            )
        mesh = getattr(patch, "mesh")
        active_films[identifier] = SharedFilmState(
            id=identifier,
            adjacent=(adjacent[0], adjacent[1]),
            min_thickness_m=min_thickness,
            mean_thickness_m=mean_thickness,
            area_m2=float(mesh.area()),
            surface_tension_n_m=float(getattr(patch, "sheet_tension_n_m")),
            mesh_id=str(getattr(mesh, "mesh_id", identifier + "-mesh")),
        )
    return EventState(bubbles=bubbles, active_films=active_films, retired_films={}, seed=seed)
