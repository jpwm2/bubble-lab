import type {
  ArrayRef,
  ContractFrame,
  ContractSurfaceMesh,
  FeatureDisclosureStatus,
  ProvenanceSource,
  Vec3,
} from "./types.js";

export type FieldAssociation = "VERTEX" | "FACE" | "BUBBLE" | "FILM" | "SYSTEM" | "ENVIRONMENT";
export type FieldProvenanceClass =
  | "CANONICAL_PHYSICAL"
  | "SOLVER_DIAGNOSTIC"
  | "VISUAL_ONLY"
  | "VIEWER_DERIVED"
  | "UNAVAILABLE";

export interface FieldDescriptorBase {
  key: string;
  name: string;
  sourcePath: string;
  association: FieldAssociation;
  provenanceClass: FieldProvenanceClass;
  provenanceSource: ProvenanceSource;
  available: boolean;
  units?: string;
  disclosure?: FeatureDisclosureStatus;
  meshId?: string;
}

export interface ScalarFieldDescriptor extends FieldDescriptorBase {
  kind: "SCALAR";
  values: readonly number[];
}

export interface VectorFieldDescriptor extends FieldDescriptorBase {
  kind: "VECTOR";
  values: readonly Vec3[];
}

export interface ScalarStatistics {
  count: number;
  missingCount: number;
  min?: number;
  max?: number;
  mean?: number;
}

export interface ScalarRange {
  min: number;
  max: number;
  diverging: boolean;
  source: "AUTO" | "MANUAL";
}

export interface SystemSummary {
  bubbleCount: number;
  sharedFilmCount: number;
  junctionCount: number;
  topologyEventCount: number;
  fidelityTier: string;
  solverIdentity: string;
  activeFeatures: readonly string[];
}

export interface TopologySelection {
  kind: "FILM" | "JUNCTION";
  id: string;
  meshId?: string | null;
  filmKind?: "OUTER" | "SHARED";
  adjacentIds?: readonly [string, string];
  incidentFilmIds?: readonly string[];
  measuredAnglesDeg?: readonly number[];
  measurementProvenance?: Record<string, unknown>;
}

const normalized = (value: string) => value.toLowerCase().replace(/[^a-z0-9]/g, "");

function asRecord(value: unknown): Record<string, unknown> | undefined {
  return typeof value === "object" && value !== null && !Array.isArray(value)
    ? value as Record<string, unknown>
    : undefined;
}

function flattenScalarValues(ref: ArrayRef | undefined): readonly number[] | undefined {
  if (!ref || ref.storage !== "INLINE" || !Array.isArray(ref.values)) return undefined;
  const result: number[] = [];
  for (const value of ref.values) {
    if (typeof value === "number") {
      result.push(value);
      continue;
    }
    if (Array.isArray(value) && value.length === 1 && typeof value[0] === "number") {
      result.push(value[0]);
      continue;
    }
    return undefined;
  }
  return result;
}

function flattenVectorValues(ref: ArrayRef | undefined): readonly Vec3[] | undefined {
  if (!ref || ref.storage !== "INLINE" || !Array.isArray(ref.values)) return undefined;
  const result: Vec3[] = [];
  const rowCount = ref.shape[0];
  if (
    ref.shape.length === 2
    && rowCount !== undefined
    && ref.shape[1] === 3
    && ref.values.length === rowCount * 3
    && ref.values.every((value) => typeof value === "number")
  ) {
    for (let index = 0; index < ref.values.length; index += 3) {
      result.push([
        ref.values[index] as number,
        ref.values[index + 1] as number,
        ref.values[index + 2] as number,
      ]);
    }
    return result;
  }
  for (const value of ref.values) {
    if (!Array.isArray(value) || value.length !== 3 || !value.every((entry) => typeof entry === "number")) return undefined;
    result.push([value[0] as number, value[1] as number, value[2] as number]);
  }
  return result;
}

function unitsForName(name: string): string | undefined {
  const lower = name.toLowerCase();
  if (lower.endsWith("_pa") || lower.includes("pressure_pa")) return "Pa";
  if (lower.endsWith("_m_s2")) return "m/s²";
  if (lower.endsWith("_m_s") || lower.includes("velocity")) return "m/s";
  if (lower.endsWith("_m2")) return "m²";
  if (lower.endsWith("_m3")) return "m³";
  if (lower.endsWith("_m_inv")) return "1/m";
  if (lower.endsWith("_n_m")) return "N/m";
  if (lower.endsWith("_kg_m3")) return "kg/m³";
  if (lower.endsWith("_pa_s")) return "Pa·s";
  if (lower.endsWith("_mol")) return "mol";
  if (lower.endsWith("_k")) return "K";
  if (lower.endsWith("_m") || lower.includes("thickness")) return "m";
  if (lower.includes("angle") && lower.includes("deg")) return "deg";
  return undefined;
}

const FEATURE_FAMILIES: ReadonlyArray<readonly [string, readonly string[]]> = [
  ["filmthickness", ["filmthickness", "thinfilmthickness", "thickness"]],
  ["pressure", ["pressure"]],
  ["curvature", ["curvature"]],
  ["surfacetension", ["surfacetension", "tension"]],
  ["surfactant", ["surfactant"]],
  ["velocity", ["velocity", "flow"]],
  ["meshquality", ["meshquality", "quality"]],
  ["amr", ["amr", "adaptivemesh", "refinement"]],
  ["remeshing", ["remesh", "remeshing"]],
];

function disclosureForName(
  name: string,
  disclosures: Readonly<Record<string, FeatureDisclosureStatus>>,
): FeatureDisclosureStatus | undefined {
  const target = normalized(name);
  for (const [key, value] of Object.entries(disclosures)) {
    if (normalized(key) === target) return value;
  }
  for (const [, aliases] of FEATURE_FAMILIES) {
    if (!aliases.some((alias) => target.includes(alias))) continue;
    for (const [key, value] of Object.entries(disclosures)) {
      const candidate = normalized(key);
      if (aliases.some((alias) => candidate.includes(alias))) return value;
    }
  }
  return undefined;
}

function classify(
  disclosure: FeatureDisclosureStatus | undefined,
  diagnostic = false,
): { provenanceClass: FieldProvenanceClass; available: boolean } {
  if (disclosure === "NOT_IMPLEMENTED") return { provenanceClass: "UNAVAILABLE", available: false };
  if (disclosure === "VISUAL_ONLY") return { provenanceClass: "VISUAL_ONLY", available: true };
  return {
    provenanceClass: diagnostic ? "SOLVER_DIAGNOSTIC" : "CANONICAL_PHYSICAL",
    available: true,
  };
}

function baseDescriptor(
  frame: ContractFrame,
  source: ProvenanceSource,
  name: string,
  sourcePath: string,
  association: FieldAssociation,
  diagnostic = false,
): Omit<FieldDescriptorBase, "key"> {
  const disclosure = disclosureForName(name, frame.manifest.feature_disclosures);
  const classified = classify(disclosure, diagnostic);
  const result: Omit<FieldDescriptorBase, "key"> = {
    name,
    sourcePath,
    association,
    provenanceClass: classified.provenanceClass,
    provenanceSource: source,
    available: classified.available,
  };
  const units = unitsForName(name);
  if (units) result.units = units;
  if (disclosure) result.disclosure = disclosure;
  return result;
}

function meshAssociation(mesh: ContractSurfaceMesh, ref: ArrayRef): "VERTEX" | "FACE" | undefined {
  const first = ref.shape[0];
  if (first === mesh.vertex_count) return "VERTEX";
  if (first === mesh.face_count) return "FACE";
  return undefined;
}

function meshFields(frame: ContractFrame, source: ProvenanceSource): {
  scalars: ScalarFieldDescriptor[];
  vectors: VectorFieldDescriptor[];
} {
  const scalars: ScalarFieldDescriptor[] = [];
  const vectors: VectorFieldDescriptor[] = [];
  frame.surface_meshes.forEach((mesh, meshIndex) => {
    for (const [name, ref] of Object.entries(mesh.fields ?? {})) {
      const association = meshAssociation(mesh, ref);
      if (!association) continue;
      const sourcePath = `surface_meshes[${meshIndex}].fields.${name}`;
      if (ref.shape.length === 2 && ref.shape[1] === 3) {
        const values = flattenVectorValues(ref);
        if (!values || values.length !== ref.shape[0]) continue;
        vectors.push({
          key: `mesh:${mesh.id}:${name}`,
          kind: "VECTOR",
          values,
          meshId: mesh.id,
          ...baseDescriptor(frame, source, name, sourcePath, association),
        });
        continue;
      }
      const values = flattenScalarValues(ref);
      if (!values || values.length !== ref.shape[0]) continue;
      scalars.push({
        key: `mesh:${mesh.id}:${name}`,
        kind: "SCALAR",
        values,
        meshId: mesh.id,
        ...baseDescriptor(frame, source, name, sourcePath, association),
      });
    }
  });
  return { scalars, vectors };
}

function bubbleScalar(
  frame: ContractFrame,
  source: ProvenanceSource,
  property: string,
): ScalarFieldDescriptor | undefined {
  const values: number[] = [];
  for (const bubble of frame.bubbles) {
    const value = bubble[property];
    if (typeof value === "number") values.push(value);
  }
  if (!values.length) return undefined;
  return {
    key: `bubble:${property}`,
    kind: "SCALAR",
    values,
    ...baseDescriptor(frame, source, property, `bubbles[*].${property}`, "BUBBLE"),
  };
}

function filmThicknessScalar(value: unknown): number | undefined {
  const record = asRecord(value);
  if (!record) return undefined;
  for (const key of ["value_m", "thickness_m", "scalar_m", "mean_m"]) {
    const candidate = record[key];
    if (typeof candidate === "number") return candidate;
  }
  if (typeof record.value === "number" && (record.unit === "m" || record.units === "m")) return record.value;
  return undefined;
}

export function discoverScalarFields(
  frame: ContractFrame,
  source: ProvenanceSource = "SOLVER",
): readonly ScalarFieldDescriptor[] {
  const result = [...meshFields(frame, source).scalars];
  for (const property of [
    "volume_m3",
    "equivalent_radius_m",
    "pressure_pa",
    "temperature_k",
    "gas_amount_mol",
    "surface_area_m2",
    "relative_volume_error",
    "mean_curvature_m_inv",
    "film_thickness_m",
  ]) {
    const field = bubbleScalar(frame, source, property);
    if (field) result.push(field);
  }

  const tensions = frame.film_regions.map((film) => film.surface_tension_n_m).filter((value) => typeof value === "number");
  if (tensions.length) {
    result.push({
      key: "film:surface_tension_n_m",
      kind: "SCALAR",
      values: tensions,
      ...baseDescriptor(frame, source, "surface_tension_n_m", "film_regions[*].surface_tension_n_m", "FILM"),
    });
  }
  const thicknesses = frame.film_regions.map((film) => filmThicknessScalar(film.thickness)).filter((value): value is number => typeof value === "number");
  if (thicknesses.length) {
    result.push({
      key: "film:film_thickness_m",
      kind: "SCALAR",
      values: thicknesses,
      ...baseDescriptor(frame, source, "film_thickness_m", "film_regions[*].thickness", "FILM"),
    });
  }

  const residuals = asRecord(frame.diagnostics?.residuals);
  if (residuals) {
    for (const [name, value] of Object.entries(residuals)) {
      if (typeof value !== "number") continue;
      result.push({
        key: `diagnostic:residuals:${name}`,
        kind: "SCALAR",
        values: [value],
        ...baseDescriptor(frame, source, name, `diagnostics.residuals.${name}`, "SYSTEM", true),
      });
    }
  }
  return result.sort((a, b) => a.key.localeCompare(b.key));
}

export function discoverVectorFields(
  frame: ContractFrame,
  source: ProvenanceSource = "SOLVER",
): readonly VectorFieldDescriptor[] {
  const result = [...meshFields(frame, source).vectors];
  const velocities = frame.bubbles.map((bubble) => bubble.velocity_m_s);
  if (velocities.length) {
    result.push({
      key: "bubble:velocity_m_s",
      kind: "VECTOR",
      values: velocities,
      ...baseDescriptor(frame, source, "velocity_m_s", "bubbles[*].velocity_m_s", "BUBBLE"),
    });
  }
  result.push({
    key: "environment:gravity_m_s2",
    kind: "VECTOR",
    values: [frame.environment.gravity_m_s2],
    ...baseDescriptor(frame, source, "gravity_m_s2", "environment.gravity_m_s2", "ENVIRONMENT"),
  });
  const wind = asRecord(frame.environment.wind);
  const windVelocity = wind?.velocity_m_s;
  if (Array.isArray(windVelocity) && windVelocity.length === 3 && windVelocity.every((value) => typeof value === "number")) {
    result.push({
      key: "environment:wind.velocity_m_s",
      kind: "VECTOR",
      values: [[windVelocity[0] as number, windVelocity[1] as number, windVelocity[2] as number]],
      ...baseDescriptor(frame, source, "wind_velocity_m_s", "environment.wind.velocity_m_s", "ENVIRONMENT"),
    });
  }
  return result.sort((a, b) => a.key.localeCompare(b.key));
}

export function scalarStatistics(values: readonly number[]): ScalarStatistics {
  const finiteValues = values.filter(Number.isFinite);
  if (!finiteValues.length) return { count: 0, missingCount: values.length };
  const sum = finiteValues.reduce((acc, value) => acc + value, 0);
  return {
    count: finiteValues.length,
    missingCount: values.length - finiteValues.length,
    min: Math.min(...finiteValues),
    max: Math.max(...finiteValues),
    mean: sum / finiteValues.length,
  };
}

export function resolveScalarRange(
  values: readonly number[],
  options: { mode: "AUTO" | "MANUAL"; min?: number; max?: number; diverging?: boolean },
): ScalarRange | undefined {
  const stats = scalarStatistics(values);
  if (stats.min === undefined || stats.max === undefined) return undefined;
  let min = stats.min, max = stats.max, source: "AUTO" | "MANUAL" = "AUTO";
  if (
    options.mode === "MANUAL"
    && typeof options.min === "number"
    && Number.isFinite(options.min)
    && typeof options.max === "number"
    && Number.isFinite(options.max)
    && options.max > options.min
  ) {
    min = options.min;
    max = options.max;
    source = "MANUAL";
  }
  const diverging = options.diverging === true && min < 0 && max > 0;
  if (diverging) {
    const extent = Math.max(Math.abs(min), Math.abs(max));
    min = -extent;
    max = extent;
  }
  if (max === min) {
    const delta = Math.max(1, Math.abs(max)) * 1e-12;
    min -= delta;
    max += delta;
  }
  return { min, max, diverging, source };
}

export function normalizedScalar(value: number, range: ScalarRange): number | undefined {
  if (!Number.isFinite(value)) return undefined;
  return Math.max(0, Math.min(1, (value - range.min) / (range.max - range.min)));
}

export function deterministicSampleIndices(length: number, maxCount: number): readonly number[] {
  if (!Number.isInteger(length) || length <= 0 || !Number.isInteger(maxCount) || maxCount <= 0) return [];
  if (length <= maxCount) return Array.from({ length }, (_, index) => index);
  if (maxCount === 1) return [0];
  const result: number[] = [];
  for (let index = 0; index < maxCount; index += 1) {
    result.push(Math.round(index * (length - 1) / (maxCount - 1)));
  }
  return [...new Set(result)];
}

export function summarizeSystem(frame: ContractFrame): SystemSummary {
  return {
    bubbleCount: frame.bubbles.length,
    sharedFilmCount: frame.film_regions.filter((film) => film.kind === "SHARED").length,
    junctionCount: frame.junctions.length,
    topologyEventCount: frame.topology.events.length,
    fidelityTier: frame.manifest.fidelity_tier,
    solverIdentity: `${frame.manifest.solver.backend} ${frame.manifest.solver.version}`,
    activeFeatures: Object.entries(frame.manifest.feature_disclosures)
      .filter(([, status]) => status !== "NOT_IMPLEMENTED")
      .map(([name, status]) => `${name}=${status}`)
      .sort(),
  };
}

function findRecordByNames(root: unknown, names: readonly string[], depth = 0): Record<string, unknown> | undefined {
  const record = asRecord(root);
  if (!record || depth > 4) return undefined;
  const wanted = new Set(names.map(normalized));
  for (const [key, value] of Object.entries(record)) {
    if (wanted.has(normalized(key))) {
      const child = asRecord(value);
      if (child) return child;
    }
  }
  for (const value of Object.values(record)) {
    const child = findRecordByNames(value, names, depth + 1);
    if (child) return child;
  }
  return undefined;
}

function findValueByNames(root: unknown, names: readonly string[], depth = 0): unknown {
  const record = asRecord(root);
  if (!record || depth > 4) return undefined;
  const wanted = new Set(names.map(normalized));
  for (const [key, value] of Object.entries(record)) if (wanted.has(normalized(key))) return value;
  for (const value of Object.values(record)) {
    const found = findValueByNames(value, names, depth + 1);
    if (found !== undefined) return found;
  }
  return undefined;
}

function diagnosticSnapshot(
  root: unknown,
  fields: Readonly<Record<string, readonly string[]>>,
): Record<string, unknown> | undefined {
  const result: Record<string, unknown> = {};
  for (const [canonical, aliases] of Object.entries(fields)) {
    const value = findValueByNames(root, aliases);
    if (value !== undefined) result[canonical] = value;
  }
  return Object.keys(result).length ? result : undefined;
}

export function extractAmrDiagnostics(frame: ContractFrame): Record<string, unknown> | undefined {
  const diagnostics = frame.diagnostics;
  if (!diagnostics) return undefined;
  const scope = findRecordByNames(diagnostics, ["amr", "adaptive_mesh_refinement", "adaptive_mesh", "refinement"]) ?? diagnostics;
  return diagnosticSnapshot(scope, {
    active_cells_by_level: ["active_cells_by_level", "cells_by_level", "level_cell_counts"],
    max_refinement_level: ["max_refinement_level", "max_level", "refinement_level_max"],
    finest_spacing_m: ["finest_spacing_m", "finest_dx_m", "minimum_cell_spacing_m", "min_cell_size_m"],
    refinement_criterion: ["refinement_criterion", "criterion", "refinement_indicator"],
    pressure_residual: ["pressure_residual", "pressure_solver_residual"],
    divergence_residual: ["divergence_residual", "continuity_residual"],
  });
}

export function extractRemeshDiagnostics(frame: ContractFrame): Record<string, unknown> | undefined {
  const diagnostics = frame.diagnostics;
  if (!diagnostics) return undefined;
  const scope = findRecordByNames(diagnostics, ["remesh", "remeshing", "surface_remeshing"]) ?? diagnostics;
  return diagnosticSnapshot(scope, {
    split_count: ["split_count", "splits", "edge_splits"],
    collapse_count: ["collapse_count", "collapses", "edge_collapses"],
    flip_count: ["flip_count", "flips", "edge_flips"],
    smooth_count: ["smooth_count", "smoothing_count", "smooth_iterations"],
    vertices_before: ["vertices_before", "vertex_count_before"],
    vertices_after: ["vertices_after", "vertex_count_after"],
    faces_before: ["faces_before", "face_count_before"],
    faces_after: ["faces_after", "face_count_after"],
    quality_before: ["quality_before", "mesh_quality_before"],
    quality_after: ["quality_after", "mesh_quality_after"],
    pre_projection_volume_change: ["pre_projection_volume_change", "volume_change_before_projection"],
    scalar_transfer_error: ["scalar_transfer_error", "field_transfer_error"],
  });
}

export function topologySelectionForSurface(frame: ContractFrame, surfaceId: string): TopologySelection | undefined {
  const film = frame.film_regions.find((candidate) => candidate.mesh_id === surfaceId || candidate.id === surfaceId);
  if (!film) return undefined;
  const result: TopologySelection = {
    kind: "FILM",
    id: film.id,
    filmKind: film.kind,
    adjacentIds: film.adjacent,
  };
  if (film.mesh_id !== undefined) result.meshId = film.mesh_id;
  return result;
}

export function topologySelectionForJunction(frame: ContractFrame, junctionId: string): TopologySelection | undefined {
  const junction = frame.junctions.find((candidate) => candidate.id === junctionId);
  if (!junction) return undefined;
  const result: TopologySelection = {
    kind: "JUNCTION",
    id: junction.id,
    incidentFilmIds: [...junction.incident_film_ids],
  };
  if (junction.measured_angles_deg) result.measuredAnglesDeg = [...junction.measured_angles_deg];
  if (junction.measurement_provenance) result.measurementProvenance = structuredClone(junction.measurement_provenance);
  return result;
}

export function viewerDerivedNormalDescriptor(
  meshId: string,
  association: "VERTEX" | "FACE",
  count: number,
): Omit<VectorFieldDescriptor, "values"> {
  return {
    key: `viewer:${meshId}:${association.toLowerCase()}-normals`,
    kind: "VECTOR",
    name: `${association.toLowerCase()}_normals`,
    sourcePath: "renderer.geometry.computeVertexNormals",
    association,
    provenanceClass: "VIEWER_DERIVED",
    provenanceSource: "IMPORT",
    available: count > 0,
    meshId,
  };
}
