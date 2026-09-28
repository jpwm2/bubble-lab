import type {
  ArrayRef, BubblePhysicalState, ContractBubble, ContractFilmRegion, ContractFrame, ContractJunction, ContractScenario,
  ContractSurfaceMesh, JunctionDescriptor, ProvenanceSource, RenderBubble, RenderFilmThickness, RenderSceneData, RenderSurfaceMesh, SharedFilmDescriptor, Vec3,
} from "./types.js";

export interface AdapterContext { provenanceSource: ProvenanceSource; provenanceLabel: string; }

function inlineVec3s(ref: ArrayRef | undefined): readonly Vec3[] | undefined {
  if (!ref || ref.storage !== "INLINE" || !Array.isArray(ref.values)) return undefined;
  const rowCount = ref.shape.length === 2 ? ref.shape[0] : undefined;
  if (rowCount !== undefined && ref.shape[1] === 3 && ref.values.length === rowCount * 3 && ref.values.every((entry) => typeof entry === "number" && Number.isFinite(entry))) {
    const rows: Vec3[] = [];
    for (let i = 0; i < ref.values.length; i += 3) rows.push([ref.values[i] as number, ref.values[i + 1] as number, ref.values[i + 2] as number]);
    return rows;
  }
  const rows: Vec3[] = [];
  for (const value of ref.values) {
    if (!Array.isArray(value) || value.length !== 3 || !value.every((entry) => typeof entry === "number" && Number.isFinite(entry))) return undefined;
    rows.push([value[0] as number, value[1] as number, value[2] as number]);
  }
  return rows;
}
function inlineFaces(ref: ArrayRef | undefined): readonly (readonly [number, number, number])[] | undefined {
  if (!ref || ref.storage !== "INLINE" || !Array.isArray(ref.values)) return undefined;
  const rowCount = ref.shape.length === 2 ? ref.shape[0] : undefined;
  if (rowCount !== undefined && ref.shape[1] === 3 && ref.values.length === rowCount * 3 && ref.values.every((entry) => Number.isInteger(entry) && (entry as number) >= 0)) {
    const rows: (readonly [number, number, number])[] = [];
    for (let i = 0; i < ref.values.length; i += 3) rows.push([ref.values[i] as number, ref.values[i + 1] as number, ref.values[i + 2] as number]);
    return rows;
  }
  const rows: (readonly [number, number, number])[] = [];
  for (const value of ref.values) {
    if (!Array.isArray(value) || value.length !== 3 || !value.every((entry) => Number.isInteger(entry) && (entry as number) >= 0)) return undefined;
    rows.push([value[0] as number, value[1] as number, value[2] as number]);
  }
  return rows;
}
function inlineNumbers(ref: ArrayRef | undefined): readonly number[] | undefined {
  if (!ref || ref.storage !== "INLINE" || !Array.isArray(ref.values)) return undefined;
  const flat: number[] = [];
  for (const value of ref.values) {
    if (typeof value === "number" && Number.isFinite(value)) {
      flat.push(value);
    } else if (Array.isArray(value) && value.length === 1 && typeof value[0] === "number" && Number.isFinite(value[0])) {
      flat.push(value[0]);
    } else {
      return undefined;
    }
  }
  return flat;
}
function optionalNumber(source: ContractBubble, key: string): number | null | undefined {
  if (!Object.prototype.hasOwnProperty.call(source, key)) return undefined;
  const value = source[key];
  return value === null || typeof value === "number" ? value : undefined;
}
function physicalState(bubble: ContractBubble): BubblePhysicalState {
  const result: BubblePhysicalState = {
    id: bubble.id, status: bubble.status, equivalentRadius: bubble.equivalent_radius_m,
    position: bubble.centroid_m, volume: bubble.volume_m3, velocity: bubble.velocity_m_s,
  };
  if (bubble.pressure_pa !== undefined) result.pressure = bubble.pressure_pa;
  const optionalMappings = [["surface_area_m2", "area"], ["mean_curvature_m_inv", "curvature"], ["film_thickness_m", "thickness"], ["relative_volume_error", "volumeError"]] as const;
  for (const [contractKey, viewerKey] of optionalMappings) {
    if (Object.prototype.hasOwnProperty.call(bubble, contractKey)) { const value = optionalNumber(bubble, contractKey); if (value !== undefined) result[viewerKey] = value; }
  }
  return result;
}
function scalarFilmThickness(film: ContractFilmRegion | undefined): number | undefined {
  const thickness = film?.thickness;
  if (!thickness || typeof thickness !== "object") return undefined;
  for (const key of ["value_m", "thickness_m", "scalar_m", "mean_m"]) {
    const value = thickness[key];
    if (typeof value === "number" && Number.isFinite(value) && value >= 0) return value;
  }
  const value = thickness.value, unit = thickness.unit ?? thickness.units;
  if (typeof value === "number" && Number.isFinite(value) && value >= 0 && unit === "m") return value;
  return undefined;
}
function referencedThicknessField(film: ContractFilmRegion | undefined): string | undefined {
  const thickness = film?.thickness;
  if (!thickness || typeof thickness !== "object") return undefined;
  for (const key of ["field", "field_name", "mesh_field"]) {
    const value = thickness[key];
    if (typeof value === "string" && value.length > 0) return value;
  }
  return undefined;
}
function meshThickness(mesh: ContractSurfaceMesh, film: ContractFilmRegion | undefined, source: ProvenanceSource): RenderFilmThickness | undefined {
  const fieldCandidates = [referencedThicknessField(film), "film_thickness_m", "thickness_m"].filter((name): name is string => Boolean(name));
  for (const fieldName of [...new Set(fieldCandidates)]) {
    const values = inlineNumbers(mesh.fields?.[fieldName]);
    if (!values || values.some((value) => value < 0)) continue;
    if (values.length === mesh.vertex_count) return { kind: "VERTEX_FIELD", valuesM: values, fieldName, provenanceSource: source };
    if (values.length === mesh.face_count) return { kind: "FACE_FIELD", valuesM: values, fieldName, provenanceSource: source };
  }
  const scalarM = scalarFilmThickness(film);
  return scalarM === undefined ? undefined : { kind: "SCALAR", scalarM, provenanceSource: source };
}
function adaptMeshes(meshes: readonly ContractSurfaceMesh[], films: readonly ContractFilmRegion[], source: ProvenanceSource): readonly RenderSurfaceMesh[] {
  const filmByMesh = new Map<string, ContractFilmRegion>();
  for (const film of films) if (typeof film.mesh_id === "string" && !filmByMesh.has(film.mesh_id)) filmByMesh.set(film.mesh_id, film);
  return meshes.map((mesh) => {
    const vertices = inlineVec3s(mesh.vertices), faces = inlineFaces(mesh.faces), renderable = Boolean(vertices && faces), film = filmByMesh.get(mesh.id);
    const base: RenderSurfaceMesh = {
      id: mesh.id, geometryRole: mesh.geometry_role, ownerBubbleIds: mesh.owner_bubble_ids ?? [], regionLabels: mesh.region_labels ?? [],
      storage: mesh.vertices.storage === "INLINE" && mesh.faces.storage === "INLINE" ? "INLINE" : "SIDECAR", renderable, provenanceSource: source,
    };
    if (vertices) base.vertices = vertices;
    if (faces) base.faces = faces;
    if (mesh.vertices.storage === "SIDECAR") base.sidecarUri = mesh.vertices.uri;
    if (film) {
      base.filmId = film.id;
      base.filmKind = film.kind;
      const thickness = meshThickness(mesh, film, source);
      if (thickness) base.physicalThickness = thickness;
    } else {
      const thickness = meshThickness(mesh, undefined, source);
      if (thickness) base.physicalThickness = thickness;
    }
    return base;
  });
}
function adaptBubbles(bubbles: readonly ContractBubble[], meshes: readonly RenderSurfaceMesh[]): readonly RenderBubble[] {
  const meshedOwners = new Set(meshes.filter((mesh) => mesh.renderable && mesh.geometryRole === "OUTER_FILM").flatMap((mesh) => [...mesh.ownerBubbleIds]));
  return bubbles.map((bubble) => ({
    id: bubble.id, position: bubble.centroid_m, displayRadius: bubble.equivalent_radius_m, physical: physicalState(bubble),
    visible: bubble.status === "ALIVE", shapeSource: meshedOwners.has(bubble.id) ? "CANONICAL_MESH" : "VIEWER_SPHERE_FALLBACK",
  }));
}
function adaptSharedFilms(films: readonly ContractFilmRegion[]): readonly SharedFilmDescriptor[] {
  return films.filter((film) => film.kind === "SHARED").map((film) => {
    const result: SharedFilmDescriptor = { id: film.id, adjacentBubbleIds: film.adjacent, surfaceTension: film.surface_tension_n_m };
    if (film.mesh_id !== undefined) result.meshId = film.mesh_id;
    if (film.thickness !== undefined) result.thickness = film.thickness;
    return result;
  });
}
function adaptJunctions(junctions: readonly ContractJunction[], source: ProvenanceSource): readonly JunctionDescriptor[] {
  return junctions.map((junction) => {
    const result: JunctionDescriptor = { id: junction.id, incidentFilmIds: junction.incident_film_ids, provenanceSource: source };
    const points = inlineVec3s(junction.geometry);
    if (points) result.points = points;
    if (junction.measured_angles_deg) result.measuredAnglesDeg = junction.measured_angles_deg;
    if (junction.measurement_provenance) result.measurementProvenance = structuredClone(junction.measurement_provenance);
    return result;
  });
}

export function adaptFrame(frame: ContractFrame, context: AdapterContext = { provenanceSource: "IMPORT", provenanceLabel: "Imported contract frame" }): RenderSceneData {
  const surfaceMeshes = adaptMeshes(frame.surface_meshes, frame.film_regions, context.provenanceSource);
  const result: RenderSceneData = {
    sourceKind: "FRAME", sourceId: frame.frame_id, provenanceSource: context.provenanceSource, provenanceLabel: context.provenanceLabel,
    fidelity: frame.manifest.fidelity_tier, featureDisclosures: { ...frame.manifest.feature_disclosures }, simulationTime: frame.simulation_time_s,
    frame, bubbles: adaptBubbles(frame.bubbles, surfaceMeshes), surfaceMeshes, sharedFilms: adaptSharedFilms(frame.film_regions),
    junctions: adaptJunctions(frame.junctions, context.provenanceSource), events: [...frame.topology.events],
  };
  if (frame.diagnostics) result.diagnostics = frame.diagnostics;
  return result;
}

export function adaptScenario(scenario: ContractScenario, context: AdapterContext = { provenanceSource: "IMPORT", provenanceLabel: "Imported editable scenario" }): RenderSceneData {
  const films = scenario.initial_film_regions ?? [], surfaceMeshes = adaptMeshes(scenario.initial_surface_meshes ?? [], films, context.provenanceSource);
  return {
    sourceKind: "SCENARIO", sourceId: scenario.scenario_id, provenanceSource: context.provenanceSource, provenanceLabel: context.provenanceLabel,
    fidelity: scenario.requested_fidelity_tier, featureDisclosures: {}, scenario,
    bubbles: adaptBubbles(scenario.initial_bubbles, surfaceMeshes), surfaceMeshes,
    sharedFilms: adaptSharedFilms(films), junctions: adaptJunctions(scenario.initial_junctions ?? [], context.provenanceSource), events: [],
  };
}
