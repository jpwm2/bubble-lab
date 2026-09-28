import { selectLayoutPolicy, type LayoutPolicy } from "./mobile.js";
import type {
  ContractBubble,
  ContractFrame,
  ContractManifest,
  ContractScenario,
  ContractTopologyEvent,
  FeatureDisclosureStatus,
  FidelityTier,
  Vec3,
} from "./types.js";
import type { ReplayBundleIndex } from "./runtimeBundle.js";

export type LabMode = "EDIT_SCENARIO" | "REVIEW_SCENARIO" | "REVIEW_REPLAY";
export type RuntimeBackend = "equilibrium" | "transient" | "thinfilm" | "thinfilm-events";
export type CapabilityDecision = "HONORED" | "REJECTED" | "REQUIRES_BACKEND" | "RESULT_ONLY";
export type SolidBoundaryType = "floor" | "plane" | "sphere" | "aabb";

export interface LabReplaySource { scenarioId: string; scenarioSha256: string; backend: string; }
export interface LabState { mode: LabMode; scenarioDraft: ContractScenario; replaySource: LabReplaySource | null; }
export interface ValidationIssue { path: string; message: string; }
export interface CapabilityRow {
  feature: string;
  status: FeatureDisclosureStatus;
  decision: CapabilityDecision;
  source: "RUNTIME_KNOWLEDGE" | "RESULT_MANIFEST";
  note: string;
}
export interface InvocationDescriptor {
  executesInBrowser: false;
  backend: RuntimeBackend;
  scenarioFile: string;
  outputDirectory: string;
  frames: number;
  command: string;
}
export interface EventLineageRow {
  eventId: string;
  type: ContractTopologyEvent["type"];
  timeS: number;
  before: readonly string[];
  after: readonly string[];
  filmIds: readonly string[];
  provenance: string;
}
export interface BubblePatch {
  equivalentRadiusM?: number;
  positionM?: Vec3;
  velocityMS?: Vec3;
  pressurePa?: number | null;
  temperatureK?: number | null;
  gasAmountMol?: number | null;
  gasSpecies?: string | null;
}
export interface ThinFilmPatch {
  initial_thickness_m?: number;
  initial_surfactant_mol_m2?: number;
  enable_drainage?: boolean;
  enable_surfactant_diffusion?: boolean;
  enable_gas_diffusion?: boolean;
  dynamic_viscosity_pa_s?: number;
  liquid_density_kg_m3?: number;
  surfactant_diffusivity_m2_s?: number;
  clean_surface_tension_n_m?: number;
  surface_elasticity_n_m_per_mol_m2?: number;
  minimum_surface_tension_n_m?: number;
  disjoining_coefficient_pa_m3?: number;
  positivity_safety?: number;
  max_substeps?: number;
  gas_permeability_mol_m_per_m2_s_pa?: number;
}
export interface EventPatch {
  enable_rupture?: boolean;
  coalesce_on_shared_film_rupture?: boolean;
  thickness_threshold_m?: number;
  dwell_time_s?: number;
  allow_user_trigger?: boolean;
  deterministic_seed?: number;
  user_trigger_time_s?: number | null;
}
export interface BoundaryWettingConfiguration {
  target_contact_angle_deg?: number | null;
  relaxation?: number;
  iterations?: number;
  contact_band_m?: number;
}
export interface SolidBoundaryDefinition {
  id: string;
  type: SolidBoundaryType;
  wall_velocity_m_s?: Vec3;
  wetting?: BoundaryWettingConfiguration;
  point_m?: Vec3;
  normal_outward?: Vec3;
  center_m?: Vec3;
  radius_m?: number;
  minimum_m?: Vec3;
  maximum_m?: Vec3;
}

const boundaryFeatures = (enabled: boolean): Record<string, FeatureDisclosureStatus> => enabled ? {
  boundary_geometry: "RESOLVED",
  solid_boundary_sdf_geometry: "RESOLVED",
  tracked_film_solid_no_penetration: "RESOLVED",
  tracked_film_wall_tangential_motion: "MODELED",
  film_wall_contact_angle: "MODELED",
  bulk_solid_wall_no_slip: "NOT_IMPLEMENTED",
  bulk_solid_fluid_wall_coupling: "NOT_IMPLEMENTED",
} : {
  boundary_geometry: "NOT_IMPLEMENTED",
  solid_boundary_sdf_geometry: "NOT_IMPLEMENTED",
  tracked_film_solid_no_penetration: "NOT_IMPLEMENTED",
  tracked_film_wall_tangential_motion: "NOT_IMPLEMENTED",
  film_wall_contact_angle: "NOT_IMPLEMENTED",
  bulk_solid_wall_no_slip: "NOT_IMPLEMENTED",
  bulk_solid_fluid_wall_coupling: "NOT_IMPLEMENTED",
};

const BACKEND_FEATURES: Readonly<Record<RuntimeBackend, Readonly<Record<string, FeatureDisclosureStatus>>>> = {
  equilibrium: {
    equilibrium_shape: "RESOLVED", gravity: "NOT_IMPLEMENTED", wind: "NOT_IMPLEMENTED",
    film_thickness: "NOT_IMPLEMENTED", drainage: "NOT_IMPLEMENTED", surfactant_diffusion: "NOT_IMPLEMENTED",
    gas_diffusion: "NOT_IMPLEMENTED", shared_film_topology: "NOT_IMPLEMENTED", rupture: "NOT_IMPLEMENTED",
    coalescence: "NOT_IMPLEMENTED", adaptive_mesh_refinement: "NOT_IMPLEMENTED", remeshing: "NOT_IMPLEMENTED",
    ...boundaryFeatures(false),
  },
  transient: {
    equilibrium_shape: "MODELED", gravity: "MODELED", wind: "MODELED", film_thickness: "MODELED",
    drainage: "MODELED", surfactant_diffusion: "MODELED", variable_surface_tension: "MODELED",
    gas_diffusion: "NOT_IMPLEMENTED", shared_film_topology: "NOT_IMPLEMENTED", rupture: "NOT_IMPLEMENTED",
    coalescence: "NOT_IMPLEMENTED", adaptive_mesh_refinement: "NOT_IMPLEMENTED", remeshing: "NOT_IMPLEMENTED",
    ...boundaryFeatures(true),
  },
  thinfilm: {
    equilibrium_shape: "VISUAL_ONLY", gravity: "NOT_IMPLEMENTED", wind: "NOT_IMPLEMENTED",
    film_thickness: "MODELED", drainage: "NOT_IMPLEMENTED", surfactant_diffusion: "NOT_IMPLEMENTED",
    variable_surface_tension: "MODELED", gas_diffusion: "MODELED", shared_film_topology: "MODELED",
    rupture: "NOT_IMPLEMENTED", coalescence: "NOT_IMPLEMENTED", adaptive_mesh_refinement: "NOT_IMPLEMENTED",
    remeshing: "NOT_IMPLEMENTED", ...boundaryFeatures(false),
  },
  "thinfilm-events": {
    equilibrium_shape: "VISUAL_ONLY", gravity: "NOT_IMPLEMENTED", wind: "NOT_IMPLEMENTED",
    film_thickness: "MODELED", drainage: "MODELED", surfactant_diffusion: "MODELED",
    variable_surface_tension: "MODELED", gas_diffusion: "MODELED", shared_film_topology: "MODELED",
    rupture: "MODELED", coalescence: "MODELED", adaptive_mesh_refinement: "NOT_IMPLEMENTED",
    remeshing: "NOT_IMPLEMENTED", fragmentation: "NOT_IMPLEMENTED", splitting: "NOT_IMPLEMENTED",
    ...boundaryFeatures(false),
  },
};

const BULK_WALL_FEATURES = new Set([
  "no_slip_wall", "bulk_no_slip", "bulk_solid_wall_no_slip",
  "bulk_solid_fluid_wall_coupling", "resolved_bulk_wall_coupling",
]);

const cloneScenario = (scenario: ContractScenario): ContractScenario => structuredClone(scenario);
const record = (value: unknown): Record<string, unknown> => typeof value === "object" && value !== null && !Array.isArray(value) ? value as Record<string, unknown> : {};
const finitePositive = (value: unknown): value is number => typeof value === "number" && Number.isFinite(value) && value > 0;
const finiteNonNegative = (value: unknown): value is number => typeof value === "number" && Number.isFinite(value) && value >= 0;
const finiteVec3 = (value: unknown): value is Vec3 => Array.isArray(value) && value.length === 3 && value.every((item) => typeof item === "number" && Number.isFinite(item));

function requestedFeatures(scenario: ContractScenario): Record<string, unknown> {
  const solver = record(scenario.requested_solver);
  return { ...record(solver.features), ...record(scenario.user_editable.features) };
}
function backendOf(scenario: ContractScenario): RuntimeBackend | null {
  const value = record(scenario.requested_solver).backend;
  return value === "equilibrium" || value === "transient" || value === "thinfilm" || value === "thinfilm-events" ? value : null;
}
function setEditableSection(scenario: ContractScenario, key: string, patch: Record<string, unknown>): ContractScenario {
  const next = cloneScenario(scenario);
  next.user_editable = { ...next.user_editable, [key]: { ...record(next.user_editable[key]), ...patch } };
  return next;
}
function setSolverFeatures(scenario: ContractScenario, patch: Record<string, unknown>): ContractScenario {
  const next = cloneScenario(scenario);
  const solver = record(next.requested_solver);
  next.requested_solver = { ...solver, features: { ...record(solver.features), ...patch } };
  return next;
}
function normalizeBoundaryType(value: unknown): SolidBoundaryType | null {
  if (typeof value !== "string") return null;
  const type = value.trim().toLowerCase();
  if (type === "floor" || type === "plane" || type === "sphere" || type === "aabb") return type;
  if (type === "axis_aligned_box") return "aabb";
  return null;
}

export function solidBoundaryDefinitions(scenario: ContractScenario): SolidBoundaryDefinition[] {
  const raw = scenario.user_editable.solid_boundaries;
  if (!Array.isArray(raw)) return [];
  const result: SolidBoundaryDefinition[] = [];
  for (const entry of raw) {
    const spec = record(entry);
    const type = normalizeBoundaryType(spec.type);
    if (typeof spec.id !== "string" || !spec.id || !type) continue;
    const boundary: SolidBoundaryDefinition = { id: spec.id, type };
    if (finiteVec3(spec.wall_velocity_m_s)) boundary.wall_velocity_m_s = [...spec.wall_velocity_m_s] as Vec3;
    if (finiteVec3(spec.point_m)) boundary.point_m = [...spec.point_m] as Vec3;
    if (finiteVec3(spec.normal_outward)) boundary.normal_outward = [...spec.normal_outward] as Vec3;
    if (finiteVec3(spec.center_m)) boundary.center_m = [...spec.center_m] as Vec3;
    if (typeof spec.radius_m === "number") boundary.radius_m = spec.radius_m;
    if (finiteVec3(spec.minimum_m)) boundary.minimum_m = [...spec.minimum_m] as Vec3;
    if (finiteVec3(spec.maximum_m)) boundary.maximum_m = [...spec.maximum_m] as Vec3;
    const wetting = record(spec.wetting);
    if (Object.keys(wetting).length) {
      const normalized: BoundaryWettingConfiguration = {};
      if (wetting.target_contact_angle_deg === null || typeof wetting.target_contact_angle_deg === "number") normalized.target_contact_angle_deg = wetting.target_contact_angle_deg as number | null;
      if (typeof wetting.relaxation === "number") normalized.relaxation = wetting.relaxation;
      if (typeof wetting.iterations === "number") normalized.iterations = wetting.iterations;
      if (typeof wetting.contact_band_m === "number") normalized.contact_band_m = wetting.contact_band_m;
      boundary.wetting = normalized;
    }
    result.push(boundary);
  }
  return result;
}

export function setSolidBoundaries(scenario: ContractScenario, boundaries: readonly SolidBoundaryDefinition[]): ContractScenario {
  let next = cloneScenario(scenario);
  const definitions = boundaries.map((boundary) => structuredClone(boundary));
  const environment = { ...next.environment } as Record<string, unknown>;
  const editable = { ...next.user_editable };
  if (definitions.length) {
    environment.boundary_refs = definitions.map(({ id }) => id);
    editable.solid_boundaries = definitions;
  } else {
    delete environment.boundary_refs;
    delete editable.solid_boundaries;
  }
  next.environment = environment as ContractScenario["environment"];
  next.user_editable = editable;
  next = setSolverFeatures(next, { boundary_geometry: definitions.length > 0 });
  return next;
}

function validateWetting(value: unknown, path: string, issues: ValidationIssue[]): void {
  if (value === undefined || value === null) return;
  if (typeof value !== "object" || Array.isArray(value)) {
    issues.push({ path, message: "wetting must be an object" });
    return;
  }
  const wetting = value as Record<string, unknown>;
  const allowed = new Set(["target_contact_angle_deg", "relaxation", "iterations", "contact_band_m"]);
  for (const key of Object.keys(wetting)) if (!allowed.has(key)) issues.push({ path: `${path}.${key}`, message: `unsupported wetting parameter: ${key}` });
  const angle = wetting.target_contact_angle_deg;
  if (angle !== undefined && angle !== null && (typeof angle !== "number" || !Number.isFinite(angle) || angle < 0 || angle > 180)) issues.push({ path: `${path}.target_contact_angle_deg`, message: "contact angle must be null or a finite value from 0 to 180 degrees" });
  const relaxation = wetting.relaxation;
  if (relaxation !== undefined && (typeof relaxation !== "number" || !Number.isFinite(relaxation) || relaxation <= 0 || relaxation > 1)) issues.push({ path: `${path}.relaxation`, message: "wetting relaxation must be finite and in (0, 1]" });
  const iterations = wetting.iterations;
  if (iterations !== undefined && (!Number.isInteger(iterations) || (iterations as number) < 1)) issues.push({ path: `${path}.iterations`, message: "wetting iterations must be a positive integer" });
  if (wetting.contact_band_m !== undefined && !finitePositive(wetting.contact_band_m)) issues.push({ path: `${path}.contact_band_m`, message: "contact band must be finite and positive" });
}

function validateBoundarySpec(entry: unknown, index: number, issues: ValidationIssue[]): string | null {
  const path = `user_editable.solid_boundaries[${index}]`;
  if (typeof entry !== "object" || entry === null || Array.isArray(entry)) {
    issues.push({ path, message: "solid boundary must be an object" });
    return null;
  }
  const spec = entry as Record<string, unknown>;
  const id = spec.id;
  if (typeof id !== "string" || !id.trim()) issues.push({ path: `${path}.id`, message: "solid boundary id must be a non-empty string" });
  const type = normalizeBoundaryType(spec.type);
  if (!type) issues.push({ path: `${path}.type`, message: "supported boundary types are floor/plane, sphere and AABB" });
  if (spec.wall_velocity_m_s !== undefined && !finiteVec3(spec.wall_velocity_m_s)) issues.push({ path: `${path}.wall_velocity_m_s`, message: "wall velocity must contain exactly three finite numbers" });
  validateWetting(spec.wetting, `${path}.wetting`, issues);
  for (const key of Object.keys(spec)) if (BULK_WALL_FEATURES.has(key)) issues.push({ path: `${path}.${key}`, message: "resolved no-slip bulk-wall CFD is not implemented by the transient runtime" });

  if (type === "floor" || type === "plane") {
    if (!finiteVec3(spec.point_m)) issues.push({ path: `${path}.point_m`, message: "plane/floor boundary requires a finite point_m vector" });
    const normal = finiteVec3(spec.normal_outward) ? spec.normal_outward : null;
    if (!normal || Math.hypot(...normal) === 0) issues.push({ path: `${path}.normal_outward`, message: "plane/floor boundary requires a non-zero finite outward normal" });
  } else if (type === "sphere") {
    if (!finiteVec3(spec.center_m)) issues.push({ path: `${path}.center_m`, message: "sphere boundary requires a finite center_m vector" });
    if (!finitePositive(spec.radius_m)) issues.push({ path: `${path}.radius_m`, message: "sphere boundary radius must be finite and positive" });
  } else if (type === "aabb") {
    const minimum = finiteVec3(spec.minimum_m) ? spec.minimum_m : null;
    const maximum = finiteVec3(spec.maximum_m) ? spec.maximum_m : null;
    if (!minimum) issues.push({ path: `${path}.minimum_m`, message: "AABB boundary requires a finite minimum_m vector" });
    if (!maximum) issues.push({ path: `${path}.maximum_m`, message: "AABB boundary requires a finite maximum_m vector" });
    if (minimum && maximum && !minimum.every((value, axis) => value < maximum[axis]!)) issues.push({ path, message: "AABB minimum_m must be strictly less than maximum_m on every axis" });
  }
  return typeof id === "string" && id.trim() ? id : null;
}

export function validateSolidBoundaries(scenario: ContractScenario, backend: RuntimeBackend = backendOf(scenario) ?? "transient"): ValidationIssue[] {
  const issues: ValidationIssue[] = [];
  const features = requestedFeatures(scenario);
  for (const feature of BULK_WALL_FEATURES) if (features[feature] === true) issues.push({ path: `requested_solver.features.${feature}`, message: "resolved no-slip bulk-wall CFD is not implemented by the transient runtime" });

  const refsValue = (scenario.environment as Record<string, unknown>).boundary_refs;
  const definitions = scenario.user_editable.solid_boundaries;
  if (refsValue !== undefined && !Array.isArray(refsValue)) {
    issues.push({ path: "environment.boundary_refs", message: "boundary_refs must be an array of non-empty boundary IDs" });
    return issues;
  }
  const refs = Array.isArray(refsValue) ? refsValue : [];
  if (features.boundary_geometry === true && refs.length === 0) issues.push({ path: "environment.boundary_refs", message: "boundary_geometry requires environment.boundary_refs and user_editable.solid_boundaries" });
  if (!refs.length) return issues;
  if (backend !== "transient") issues.push({ path: "environment.boundary_refs", message: "solid-boundary geometry is currently integrated only with the transient backend" });

  const refIds: string[] = [];
  refs.forEach((value, index) => {
    if (typeof value !== "string" || !value) issues.push({ path: `environment.boundary_refs[${index}]`, message: "boundary reference must be a non-empty string" });
    else refIds.push(value);
  });
  if (new Set(refIds).size !== refIds.length) issues.push({ path: "environment.boundary_refs", message: "boundary_refs must not contain duplicates" });
  if (!Array.isArray(definitions) || definitions.length === 0) {
    issues.push({ path: "user_editable.solid_boundaries", message: "boundary_refs requires solid boundary definitions" });
    return issues;
  }
  const ids = definitions.map((entry, index) => validateBoundarySpec(entry, index, issues)).filter((id): id is string => id !== null);
  if (new Set(ids).size !== ids.length) issues.push({ path: "user_editable.solid_boundaries", message: "solid boundary IDs must be unique" });
  const known = new Set(ids);
  const missing = refIds.filter((id) => !known.has(id));
  if (missing.length) issues.push({ path: "environment.boundary_refs", message: `unknown boundary reference(s): ${missing.join(", ")}` });
  return issues;
}

export function createLabState(scenario: ContractScenario): LabState { return { mode: "EDIT_SCENARIO", scenarioDraft: cloneScenario(scenario), replaySource: null }; }
export function setLabMode(state: LabState, mode: Exclude<LabMode, "REVIEW_REPLAY">): LabState { return { ...state, mode, scenarioDraft: cloneScenario(state.scenarioDraft) }; }
export function enterReplayReview(state: LabState, index: ReplayBundleIndex): LabState {
  return { ...state, mode: "REVIEW_REPLAY", scenarioDraft: cloneScenario(state.scenarioDraft), replaySource: { scenarioId: index.scenario.id, scenarioSha256: index.scenario.sha256, backend: index.backend.identity } };
}
export function forkReplayToScenarioEdit(state: LabState): LabState { return { ...state, mode: "EDIT_SCENARIO", scenarioDraft: cloneScenario(state.scenarioDraft) }; }
export function setBackendAndFidelity(scenario: ContractScenario, backend: RuntimeBackend, fidelity: FidelityTier): ContractScenario {
  const next = cloneScenario(scenario);
  next.requested_fidelity_tier = fidelity;
  next.requested_solver = { ...record(next.requested_solver), backend };
  return next;
}
export function setEnvironmentVectors(scenario: ContractScenario, gravity: Vec3, wind: Vec3): ContractScenario {
  const next = cloneScenario(scenario);
  next.environment = { ...next.environment, gravity_m_s2: [...gravity] as Vec3, wind: { ...record(next.environment.wind), velocity_m_s: [...wind] } };
  return next;
}
export function setRuntimeOutputCadence(scenario: ContractScenario, outputCadenceS: number): ContractScenario { return setEditableSection(scenario, "runtime", { output_cadence_s: outputCadenceS }); }
export function setThinFilmConfiguration(scenario: ContractScenario, patch: ThinFilmPatch): ContractScenario {
  let next = setEditableSection(scenario, "thinfilm", patch as Record<string, unknown>);
  const featurePatch: Record<string, unknown> = {};
  if (patch.enable_drainage !== undefined) featurePatch.drainage = patch.enable_drainage;
  if (patch.enable_surfactant_diffusion !== undefined) {
    featurePatch.surfactant_diffusion = patch.enable_surfactant_diffusion;
    featurePatch.variable_surface_tension = patch.enable_surfactant_diffusion;
  }
  if (patch.enable_gas_diffusion !== undefined) {
    featurePatch.gas_diffusion = patch.enable_gas_diffusion;
    featurePatch.coarsening = patch.enable_gas_diffusion;
  }
  return Object.keys(featurePatch).length ? setSolverFeatures(next, featurePatch) : next;
}
export function setEventConfiguration(scenario: ContractScenario, patch: EventPatch): ContractScenario {
  const next = cloneScenario(scenario);
  const events: Record<string, unknown> = { ...record(next.user_editable.events), ...patch };
  if (patch.user_trigger_time_s === null) delete events.user_trigger_time_s;
  next.user_editable = { ...next.user_editable, events };
  return next;
}
export function requestUserBurst(scenario: ContractScenario, timeS: number): ContractScenario {
  return setSolverFeatures(setEventConfiguration(scenario, { enable_rupture: true, allow_user_trigger: true, user_trigger_time_s: timeS }), { shared_film_topology: true, rupture: true, coalescence: true });
}
export function updateBubble(scenario: ContractScenario, bubbleId: string, patch: BubblePatch): ContractScenario {
  const next = cloneScenario(scenario);
  const index = next.initial_bubbles.findIndex(({ id }) => id === bubbleId);
  if (index < 0) throw new Error(`Unknown bubble: ${bubbleId}`);
  const current = next.initial_bubbles[index]!;
  const radius = patch.equivalentRadiusM ?? current.equivalent_radius_m;
  const replacement: ContractBubble = {
    ...current,
    equivalent_radius_m: radius,
    volume_m3: patch.equivalentRadiusM === undefined ? current.volume_m3 : (4 / 3) * Math.PI * radius ** 3,
    centroid_m: patch.positionM ?? current.centroid_m,
    velocity_m_s: patch.velocityMS ?? current.velocity_m_s,
    pressure_pa: patch.pressurePa === undefined ? current.pressure_pa : patch.pressurePa,
    temperature_k: patch.temperatureK === undefined ? current.temperature_k : patch.temperatureK,
    gas_amount_mol: patch.gasAmountMol === undefined ? current.gas_amount_mol : patch.gasAmountMol,
    gas_species: patch.gasSpecies === undefined ? current.gas_species : patch.gasSpecies,
  };
  next.initial_bubbles[index] = replacement;
  return next;
}

export function validateScenarioForBackend(scenario: ContractScenario, backend: RuntimeBackend = backendOf(scenario) ?? "transient"): ValidationIssue[] {
  const issues = validateSolidBoundaries(scenario, backend);
  const features = requestedFeatures(scenario);
  const thinfilm = record(scenario.user_editable.thinfilm);
  const events = record(scenario.user_editable.events);
  const bubbleCount = scenario.initial_bubbles.length;
  const hasFilms = (scenario.initial_film_regions?.length ?? 0) > 0 || (scenario.initial_surface_meshes?.length ?? 0) > 0;
  const hasJunctions = (scenario.initial_junctions?.length ?? 0) > 0;
  const nonzeroGravity = scenario.environment.gravity_m_s2.some((value) => Math.abs(value) > 0);
  const nonzeroVelocity = scenario.initial_bubbles.some((bubble) => bubble.velocity_m_s.some((value) => Math.abs(value) > 0));
  const runtime = record(scenario.user_editable.runtime);

  if (backend === "equilibrium") {
    if (bubbleCount !== 1) issues.push({ path: "initial_bubbles", message: "equilibrium supports exactly one bubble" });
    if (scenario.requested_fidelity_tier !== "HIGH_FIDELITY") issues.push({ path: "requested_fidelity_tier", message: "equilibrium requires HIGH_FIDELITY" });
    if (nonzeroGravity) issues.push({ path: "environment.gravity_m_s2", message: "equilibrium runtime slice requires zero gravity" });
    if (nonzeroVelocity) issues.push({ path: "initial_bubbles[].velocity_m_s", message: "equilibrium does not support initial bubble velocity" });
    if (hasFilms || hasJunctions) issues.push({ path: "initial_*", message: "equilibrium runtime slice does not accept initial films or junctions" });
  }
  if (backend === "transient") {
    if (bubbleCount !== 1) issues.push({ path: "initial_bubbles", message: "transient runtime slice supports exactly one bubble" });
    if (nonzeroVelocity) issues.push({ path: "initial_bubbles[].velocity_m_s", message: "transient uses environment.wind instead of independent initial velocity" });
    if (hasFilms) issues.push({ path: "initial_film_regions", message: "transient builds its transport mesh from the tracked outer FilmFront" });
    if (hasJunctions) issues.push({ path: "initial_junctions", message: "transient thin-film integration does not support multi-junction transport" });
    if (features.gas_diffusion === true || features.shared_film_topology === true || thinfilm.enable_gas_diffusion === true) issues.push({ path: "requested_solver.features", message: "gas diffusion/shared-film topology requires thinfilm or thinfilm-events" });
  }
  if (backend === "thinfilm" || backend === "thinfilm-events") {
    if (bubbleCount !== 2) issues.push({ path: "initial_bubbles", message: `${backend} requires exactly two bubbles` });
    if (!Object.keys(thinfilm).length) issues.push({ path: "user_editable.thinfilm", message: `${backend} requires thin-film runtime configuration` });
    if (thinfilm.enable_gas_diffusion !== true) issues.push({ path: "user_editable.thinfilm.enable_gas_diffusion", message: `${backend} requires gas diffusion` });
    if (features.shared_film_topology !== true) issues.push({ path: "requested_solver.features.shared_film_topology", message: `${backend} requires shared_film_topology=true` });
    if (hasJunctions) issues.push({ path: "initial_junctions", message: `${backend} does not support multi-junction transport` });
  }
  if (backend === "thinfilm" && (thinfilm.enable_drainage === true || thinfilm.enable_surfactant_diffusion === true)) issues.push({ path: "user_editable.thinfilm", message: "standalone thinfilm is fixed-film gas diffusion; drainage/surfactant transport requires transient coupling" });
  if (backend === "thinfilm-events") {
    if (!finitePositive(runtime.output_cadence_s)) issues.push({ path: "user_editable.runtime.output_cadence_s", message: "thinfilm-events requires positive output cadence" });
    if (events.user_trigger_time_s !== undefined && events.allow_user_trigger !== true) issues.push({ path: "user_editable.events.allow_user_trigger", message: "user trigger time requires allow_user_trigger=true" });
    if (events.user_trigger_time_s !== undefined && !finiteNonNegative(events.user_trigger_time_s)) issues.push({ path: "user_editable.events.user_trigger_time_s", message: "user trigger time must be finite and non-negative" });
    if (events.coalesce_on_shared_film_rupture === false) issues.push({ path: "user_editable.events.coalesce_on_shared_film_rupture", message: "accepted event runtime coalesces immediately after shared-film rupture" });
  }
  for (const unsupported of ["adaptive_mesh_refinement", "amr", "cfd", "vof", "level_set", "fragmentation", "splitting"] as const) if (features[unsupported] === true) issues.push({ path: `requested_solver.features.${unsupported}`, message: `${unsupported} is not implemented by the accepted runtime backends` });
  return issues;
}

function decisionForFeature(feature: string, status: FeatureDisclosureStatus, backend: RuntimeBackend): CapabilityDecision {
  if (status !== "NOT_IMPLEMENTED") return "HONORED";
  if ((feature === "gas_diffusion" || feature === "shared_film_topology") && (backend === "equilibrium" || backend === "transient")) return "REQUIRES_BACKEND";
  if ((feature === "rupture" || feature === "coalescence") && backend !== "thinfilm-events") return "REQUIRES_BACKEND";
  if (["boundary_geometry", "solid_boundary_sdf_geometry", "tracked_film_solid_no_penetration", "tracked_film_wall_tangential_motion", "film_wall_contact_angle"].includes(feature) && backend !== "transient") return "REQUIRES_BACKEND";
  return "REJECTED";
}
export function capabilityDisclosure(scenario: ContractScenario, manifest?: ContractManifest): CapabilityRow[] {
  if (manifest) return Object.entries(manifest.feature_disclosures).sort(([a], [b]) => a.localeCompare(b)).map(([feature, status]) => ({ feature, status, decision: "RESULT_ONLY" as const, source: "RESULT_MANIFEST" as const, note: `Authoritative result disclosure from ${manifest.solver.backend} ${manifest.solver.version}` }));
  const backend = backendOf(scenario) ?? "transient";
  return Object.entries(BACKEND_FEATURES[backend]).sort(([a], [b]) => a.localeCompare(b)).map(([feature, status]) => ({ feature, status, decision: decisionForFeature(feature, status, backend), source: "RUNTIME_KNOWLEDGE" as const, note: status === "NOT_IMPLEMENTED" ? `Rejected by current ${backend} runtime contract` : `Declared support for current ${backend} runtime` }));
}

const shellQuote = (value: string): string => `'${value.replaceAll("'", "'\\''")}'`;
export function buildInvocationDescriptor(scenario: ContractScenario, options: { scenarioFile?: string; outputDirectory?: string; frames?: number } = {}): InvocationDescriptor {
  const backend = backendOf(scenario);
  if (!backend) throw new Error("Select a supported runtime backend before generating an invocation descriptor");
  const issues = validateScenarioForBackend(scenario, backend);
  if (issues.length) throw new Error(`Scenario is not runnable with ${backend}: ${issues.map((issue) => `${issue.path}: ${issue.message}`).join("; ")}`);
  const scenarioFile = options.scenarioFile ?? `${scenario.scenario_id}.scenario.json`;
  const outputDirectory = options.outputDirectory ?? `replay-${scenario.scenario_id}`;
  const frames = options.frames ?? 4;
  if (!Number.isInteger(frames) || frames < 1) throw new Error("frames must be a positive integer");
  const command = ["python3 bubblelab/runtime/tools/run_scenario.py", shellQuote(scenarioFile), "--backend", backend, "--output", shellQuote(outputDirectory), ...(backend === "equilibrium" ? [] : ["--frames", String(frames)])].join(" ");
  return { executesInBrowser: false, backend, scenarioFile, outputDirectory, frames, command };
}
function sortJson(value: unknown): unknown {
  if (Array.isArray(value)) return value.map(sortJson);
  if (typeof value === "object" && value !== null) return Object.fromEntries(Object.entries(value as Record<string, unknown>).sort(([a], [b]) => a.localeCompare(b)).map(([key, entry]) => [key, sortJson(entry)]));
  return value;
}
export function serializeScenarioDeterministic(scenario: ContractScenario): string { return `${JSON.stringify(sortJson(scenario), null, 2)}\n`; }
export function cloneFrameReadOnly(frame: ContractFrame): ContractFrame { return structuredClone(frame); }
export function eventLineage(events: readonly ContractTopologyEvent[]): EventLineageRow[] {
  return [...events].sort((a, b) => a.time_s - b.time_s || a.id.localeCompare(b.id)).map((event) => ({ eventId: event.id, type: event.type, timeS: event.time_s, before: event.bubble_ids_before ?? [], after: event.bubble_ids_after ?? [], filmIds: event.film_ids ?? [], provenance: [event.provenance.source, event.provenance.detail].filter(Boolean).join(" · ") }));
}
export function labPanelPolicy(viewportWidth: number, viewportHeight: number): LayoutPolicy & { scenarioControlsCollapsible: boolean; criticalStatePersistent: true } {
  const layout = selectLayoutPolicy(viewportWidth, viewportHeight);
  return { ...layout, scenarioControlsCollapsible: layout.compact, criticalStatePersistent: true };
}
