"""Geometry-bearing local network model for executable T1 research.

The model intentionally mirrors the accepted FilmNetwork semantics without importing
production solver code: one physical film patch is stored once, each patch has two
gas-region IDs, and a Plateau line owns coincident samples on exactly three films.
The supported research class is a quasi-2D network extruded through a finite depth.
"""
from __future__ import annotations

from dataclasses import dataclass, replace
import math
import statistics
from typing import Iterable

Vec2 = tuple[float, float]
Vec3 = tuple[float, float, float]
Face = tuple[int, int, int]


def _sub2(a: Vec2, b: Vec2) -> Vec2:
    return (a[0] - b[0], a[1] - b[1])


def _norm2(a: Vec2) -> float:
    return math.hypot(a[0], a[1])


def _distance3(a: Vec3, b: Vec3) -> float:
    return math.sqrt(sum((a[i] - b[i]) ** 2 for i in range(3)))


def polygon_area(poly: tuple[Vec2, ...]) -> float:
    return abs(sum(
        poly[i][0] * poly[(i + 1) % len(poly)][1]
        - poly[(i + 1) % len(poly)][0] * poly[i][1]
        for i in range(len(poly))
    )) * 0.5


def _edge_key(a: Vec2, b: Vec2, digits: int = 12) -> tuple[Vec2, Vec2]:
    aa = (round(a[0], digits), round(a[1], digits))
    bb = (round(b[0], digits), round(b[1], digits))
    return tuple(sorted((aa, bb)))  # type: ignore[return-value]


@dataclass(frozen=True)
class FilmMesh:
    vertices: tuple[Vec3, ...]
    faces: tuple[Face, ...]

    def area(self) -> float:
        total = 0.0
        for ia, ib, ic in self.faces:
            a, b, c = self.vertices[ia], self.vertices[ib], self.vertices[ic]
            ab = tuple(b[i] - a[i] for i in range(3))
            ac = tuple(c[i] - a[i] for i in range(3))
            cross = (
                ab[1] * ac[2] - ab[2] * ac[1],
                ab[2] * ac[0] - ab[0] * ac[2],
                ab[0] * ac[1] - ab[1] * ac[0],
            )
            total += 0.5 * math.sqrt(sum(value * value for value in cross))
        return total

    def minimum_edge_length(self) -> float:
        lengths: list[float] = []
        seen: set[tuple[int, int]] = set()
        for face in self.faces:
            for a, b in ((face[0], face[1]), (face[1], face[2]), (face[2], face[0])):
                edge = tuple(sorted((a, b)))
                if edge in seen:
                    continue
                seen.add(edge)
                lengths.append(_distance3(self.vertices[edge[0]], self.vertices[edge[1]]))
        return min(lengths) if lengths else 0.0

    def minimum_triangle_quality(self) -> float:
        """Return 1 for equilateral and approach 0 for degenerate triangles."""
        qualities: list[float] = []
        for ia, ib, ic in self.faces:
            a, b, c = self.vertices[ia], self.vertices[ib], self.vertices[ic]
            lengths = (_distance3(a, b), _distance3(b, c), _distance3(c, a))
            semiperimeter = sum(lengths) * 0.5
            radicand = max(
                semiperimeter
                * (semiperimeter - lengths[0])
                * (semiperimeter - lengths[1])
                * (semiperimeter - lengths[2]),
                0.0,
            )
            area = math.sqrt(radicand)
            denom = sum(length * length for length in lengths)
            qualities.append(4.0 * math.sqrt(3.0) * area / denom if denom else 0.0)
        return min(qualities) if qualities else 0.0


@dataclass(frozen=True)
class FilmPatch:
    id: str
    adjacent: tuple[str, str]
    mesh: FilmMesh
    spine: tuple[Vec2, Vec2]
    span_cells: int
    depth_cells: int
    sheet_tension_n_m: float = 1.0

    @property
    def span_length_m(self) -> float:
        return _norm2(_sub2(self.spine[1], self.spine[0]))

    @property
    def span_step_m(self) -> float:
        return self.span_length_m / self.span_cells


@dataclass(frozen=True)
class PlateauLine:
    id: str
    incident_film_ids: tuple[str, str, str]
    vertex_indices_by_film: tuple[tuple[int, ...], tuple[int, ...], tuple[int, ...]]


@dataclass(frozen=True)
class LocalFilmNetwork:
    region_ids: tuple[str, ...]
    films: tuple[FilmPatch, ...]
    junctions: tuple[PlateauLine, ...]
    region_cells_xy: tuple[tuple[str, tuple[Vec2, ...]], ...]
    target_region_volumes_m3: tuple[tuple[str, float], ...]
    depth_m: float
    generation: int = 0

    def film_by_id(self) -> dict[str, FilmPatch]:
        return {film.id: film for film in self.films}

    def junction_by_id(self) -> dict[str, PlateauLine]:
        return {junction.id: junction for junction in self.junctions}

    def cell_by_id(self) -> dict[str, tuple[Vec2, ...]]:
        return dict(self.region_cells_xy)

    def target_volume_by_id(self) -> dict[str, float]:
        return dict(self.target_region_volumes_m3)

    def geometric_volume_by_id(self) -> dict[str, float]:
        return {
            region_id: polygon_area(cell) * self.depth_m
            for region_id, cell in self.region_cells_xy
        }

    def relative_volume_errors(self) -> dict[str, float]:
        target = self.target_volume_by_id()
        actual = self.geometric_volume_by_id()
        return {
            region_id: abs(actual[region_id] - target[region_id]) / target[region_id]
            for region_id in self.region_ids
        }

    def surface_energy_j(self) -> float:
        return sum(film.sheet_tension_n_m * film.mesh.area() for film in self.films)

    def topology_signature(self) -> tuple[object, ...]:
        adjacency = tuple(sorted(
            (film.id, tuple(sorted(film.adjacent))) for film in self.films
        ))
        incidence = tuple(sorted(
            (junction.id, tuple(sorted(junction.incident_film_ids)))
            for junction in self.junctions
        ))
        return (tuple(sorted(self.region_ids)), adjacency, incidence)

    def minimum_feature_scale_m(self) -> float:
        values = [film.mesh.minimum_edge_length() for film in self.films]
        return min(values) if values else 0.0

    def minimum_triangle_quality(self) -> float:
        values = [film.mesh.minimum_triangle_quality() for film in self.films]
        return min(values) if values else 0.0

    def local_resolution_m(self, exclude_film_ids: Iterable[str] = ()) -> float:
        excluded = set(exclude_film_ids)
        steps = [
            film.span_step_m
            for film in self.films
            if film.id not in excluded
        ]
        if not steps:
            raise ValueError("network has no resolved non-candidate film spans")
        return statistics.median(steps)

    def validate(self) -> None:
        if len(self.region_ids) < 4 or len(set(self.region_ids)) != len(self.region_ids):
            raise ValueError("research network requires at least four unique gas-region IDs")
        if self.depth_m <= 0.0:
            raise ValueError("extrusion depth must be positive")
        film_ids = [film.id for film in self.films]
        if len(set(film_ids)) != len(film_ids):
            raise ValueError("film IDs must be unique")
        adjacency_pairs: set[tuple[str, str]] = set()
        for film in self.films:
            if len(set(film.adjacent)) != 2 or not set(film.adjacent).issubset(self.region_ids):
                raise ValueError(f"film {film.id!r} has invalid gas adjacency")
            pair = tuple(sorted(film.adjacent))
            if pair in adjacency_pairs:
                raise ValueError("duplicate gas adjacency is not supported in the local T1 class")
            adjacency_pairs.add(pair)
            if film.span_cells < 1 or film.depth_cells < 2:
                raise ValueError("film grid dimensions are insufficient")
            if film.mesh.area() <= 0.0 or film.mesh.minimum_triangle_quality() <= 1.0e-12:
                raise ValueError("film geometry is degenerate")

        by_film = self.film_by_id()
        junction_ids = [junction.id for junction in self.junctions]
        if len(set(junction_ids)) != len(junction_ids):
            raise ValueError("junction IDs must be unique")
        for junction in self.junctions:
            if len(set(junction.incident_film_ids)) != 3:
                raise ValueError("each Plateau line must reference exactly three films")
            if len(junction.vertex_indices_by_film) != 3:
                raise ValueError("each Plateau line needs three index lists")
            counts = {len(indices) for indices in junction.vertex_indices_by_film}
            if len(counts) != 1 or next(iter(counts), 0) < 3:
                raise ValueError("Plateau line sample counts must agree and contain at least three samples")
            for film_id in junction.incident_film_ids:
                if film_id not in by_film:
                    raise ValueError("Plateau line references an unknown film")
            count = len(junction.vertex_indices_by_film[0])
            for sample in range(count):
                points = []
                for film_id, indices in zip(junction.incident_film_ids, junction.vertex_indices_by_film):
                    patch = by_film[film_id]
                    index = indices[sample]
                    if not 0 <= index < len(patch.mesh.vertices):
                        raise ValueError("Plateau line vertex index is outside its film")
                    points.append(patch.mesh.vertices[index])
                if any(_distance3(point, points[0]) > 1.0e-11 for point in points[1:]):
                    raise ValueError("Plateau-line film copies must be geometrically coincident")

        cells = self.cell_by_id()
        if set(cells) != set(self.region_ids):
            raise ValueError("closed cross-section cells must be present for every gas region")
        if any(polygon_area(cell) <= 0.0 for cell in cells.values()):
            raise ValueError("gas-region cross-section cells must have positive area")
        targets = self.target_volume_by_id()
        if set(targets) != set(self.region_ids) or any(value <= 0.0 for value in targets.values()):
            raise ValueError("positive target volumes are required for all gas regions")

        # Every represented film spine must be a literal common polygon edge of both
        # adjacent gas cells. This prevents a graph-only topology from passing.
        for film in self.films:
            expected = _edge_key(*film.spine)
            for region_id in film.adjacent:
                cell = cells[region_id]
                edges = {
                    _edge_key(cell[i], cell[(i + 1) % len(cell)])
                    for i in range(len(cell))
                }
                if expected not in edges:
                    raise ValueError(
                        f"film {film.id!r} spine is not embedded in region {region_id!r} geometry"
                    )


def _grid_strip(
    film_id: str,
    adjacent: tuple[str, str],
    start: Vec2,
    end: Vec2,
    depth_m: float,
    resolution_m: float,
    tension: float = 1.0,
) -> FilmPatch:
    span = _norm2(_sub2(end, start))
    if span <= 0.0:
        raise ValueError("film spine must have positive length")
    span_cells = max(1, math.ceil(span / resolution_m))
    depth_cells = max(2, math.ceil(depth_m / resolution_m))
    vertices: list[Vec3] = []
    for i in range(span_cells + 1):
        alpha = i / span_cells
        x = start[0] + alpha * (end[0] - start[0])
        y = start[1] + alpha * (end[1] - start[1])
        for j in range(depth_cells + 1):
            z = -0.5 * depth_m + j * depth_m / depth_cells
            vertices.append((x, y, z))
    stride = depth_cells + 1
    faces: list[Face] = []
    for i in range(span_cells):
        for j in range(depth_cells):
            a = i * stride + j
            b = (i + 1) * stride + j
            c = (i + 1) * stride + j + 1
            d = i * stride + j + 1
            faces.append((a, b, c))
            faces.append((a, c, d))
    return FilmPatch(
        id=film_id,
        adjacent=adjacent,
        mesh=FilmMesh(tuple(vertices), tuple(faces)),
        spine=(start, end),
        span_cells=span_cells,
        depth_cells=depth_cells,
        sheet_tension_n_m=tension,
    )


def boundary_indices(film: FilmPatch, at_start: bool) -> tuple[int, ...]:
    stride = film.depth_cells + 1
    base = 0 if at_start else film.span_cells * stride
    return tuple(base + j for j in range(stride))


def build_pre_t1_network(
    resolution_m: float,
    collapse_fraction: float = 0.35,
    half_extent_m: float = 1.0,
    depth_m: float = 0.6,
    id_prefix: str = "",
) -> LocalFilmNetwork:
    """Build a closed four-cell cross-section with a shrinking AB film.

    The five internal interfaces are extruded to actual triangular surface meshes.
    The short AB sheet is bounded by two Plateau lines and is the T1 candidate.
    """
    if resolution_m <= 0.0 or half_extent_m <= 0.0 or depth_m <= 0.0:
        raise ValueError("positive geometric scales are required")
    if not 0.0 < collapse_fraction < 1.0:
        raise ValueError("collapse fraction must lie in (0, 1)")

    def rid(name: str) -> str:
        return f"{id_prefix}{name}"

    def fid(name: str) -> str:
        return f"{id_prefix}film:{name}"

    def jid(name: str) -> str:
        return f"{id_prefix}junction:{name}"

    length = collapse_fraction * resolution_m
    top = (0.0, 0.5 * length)
    bottom = (0.0, -0.5 * length)
    nw = (-half_extent_m, half_extent_m)
    ne = (half_extent_m, half_extent_m)
    se = (half_extent_m, -half_extent_m)
    sw = (-half_extent_m, -half_extent_m)

    films = (
        _grid_strip(fid("AB:central"), (rid("A"), rid("B")), top, bottom, depth_m, resolution_m),
        _grid_strip(fid("AC"), (rid("A"), rid("C")), top, nw, depth_m, resolution_m),
        _grid_strip(fid("BC"), (rid("B"), rid("C")), top, ne, depth_m, resolution_m),
        _grid_strip(fid("AD"), (rid("A"), rid("D")), bottom, sw, depth_m, resolution_m),
        _grid_strip(fid("BD"), (rid("B"), rid("D")), bottom, se, depth_m, resolution_m),
    )
    by_id = {film.id: film for film in films}
    top_j = PlateauLine(
        jid("top"),
        (fid("AB:central"), fid("AC"), fid("BC")),
        (
            boundary_indices(by_id[fid("AB:central")], True),
            boundary_indices(by_id[fid("AC")], True),
            boundary_indices(by_id[fid("BC")], True),
        ),
    )
    bottom_j = PlateauLine(
        jid("bottom"),
        (fid("AB:central"), fid("AD"), fid("BD")),
        (
            boundary_indices(by_id[fid("AB:central")], False),
            boundary_indices(by_id[fid("AD")], True),
            boundary_indices(by_id[fid("BD")], True),
        ),
    )
    cells = (
        (rid("A"), (nw, top, bottom, sw)),
        (rid("B"), (top, ne, se, bottom)),
        (rid("C"), (nw, ne, top)),
        (rid("D"), (bottom, se, sw)),
    )
    region_ids = tuple(rid(name) for name in ("A", "B", "C", "D"))
    target = tuple(
        (region_id, polygon_area(cell) * depth_m)
        for region_id, cell in cells
    )
    network = LocalFilmNetwork(
        region_ids=region_ids,
        films=films,
        junctions=(top_j, bottom_j),
        region_cells_xy=cells,
        target_region_volumes_m3=target,
        depth_m=depth_m,
    )
    network.validate()
    return network


def combine_disjoint_networks(*networks: LocalFilmNetwork) -> LocalFilmNetwork:
    """Combine independent local cells for ambiguity-detector testing."""
    if not networks:
        raise ValueError("at least one network is required")
    depth = networks[0].depth_m
    if any(abs(network.depth_m - depth) > 1.0e-12 for network in networks):
        raise ValueError("combined research networks must share extrusion depth")
    combined = LocalFilmNetwork(
        region_ids=tuple(region for network in networks for region in network.region_ids),
        films=tuple(film for network in networks for film in network.films),
        junctions=tuple(junction for network in networks for junction in network.junctions),
        region_cells_xy=tuple(cell for network in networks for cell in network.region_cells_xy),
        target_region_volumes_m3=tuple(item for network in networks for item in network.target_region_volumes_m3),
        depth_m=depth,
    )
    combined.validate()
    return combined


def translate_network(network: LocalFilmNetwork, dx: float, dy: float) -> LocalFilmNetwork:
    """Translate all geometry while preserving IDs/topology and accounting."""
    films: list[FilmPatch] = []
    for film in network.films:
        vertices = tuple((x + dx, y + dy, z) for x, y, z in film.mesh.vertices)
        spine = tuple((x + dx, y + dy) for x, y in film.spine)
        films.append(replace(film, mesh=FilmMesh(vertices, film.mesh.faces), spine=spine))
    cells = tuple(
        (region_id, tuple((x + dx, y + dy) for x, y in cell))
        for region_id, cell in network.region_cells_xy
    )
    translated = replace(network, films=tuple(films), region_cells_xy=cells)
    translated.validate()
    return translated
