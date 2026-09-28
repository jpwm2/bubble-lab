export type Vec3 = readonly [number, number, number];
export type FidelityTier = "INTERACTIVE" | "HIGH_FIDELITY" | "MAXIMUM_REALISM";
export type FeatureDisclosureStatus = "RESOLVED" | "MODELED" | "VISUAL_ONLY" | "NOT_IMPLEMENTED";
export type ProvenanceSource = "SOLVER" | "USER" | "IMPORT" | "TEST_FIXTURE";
export type ViewerMode = "EDIT" | "REPLAY";
export type BubbleStatus = "ALIVE" | "RUPTURED" | "MERGED" | "SPLIT" | "REMOVED";
export type GeometryRole = "OUTER_FILM" | "SHARED_FILM" | "PLATEAU_BORDER" | "BOUNDARY" | "OTHER";

export interface InlineArrayRef {
  storage: "INLINE";
  dtype: "float32" | "float64" | "int32" | "uint32" | "uint8";
  shape: readonly number[];
  values: readonly unknown[];
  [key: string]: unknown;
}
export interface SidecarArrayRef {
  storage: "SIDECAR";
  dtype: "float32" | "float64" | "int32" | "uint32" | "uint8";
  shape: readonly number[];
  uri: string;
  byte_offset?: number;
  byte_length?: number;
  encoding?: "raw" | "npy" | "npz" | "zarr" | "custom";
  [key: string]: unknown;
}
export type ArrayRef = InlineArrayRef | SidecarArrayRef;

export interface ContractManifest {
  contract_version: "1.0.0";
  units: { system: "SI"; [key: string]: unknown };
  solver: { backend: string; version: string; adapter?: string | null; [key: string]: unknown };
  fidelity_tier: FidelityTier;
  feature_disclosures: Record<string, FeatureDisclosureStatus>;
  random_seed: number;
  provenance: { producer: string; source_scenario?: string | null; created_at?: string | null; tolerances?: Record<string, number>; [key: string]: unknown };
  [key: string]: unknown;
}
export interface ContractEnvironment {
  gravity_m_s2: Vec3;
  ambient_density_kg_m3: number;
  ambient_dynamic_viscosity_pa_s: number;
  [key: string]: unknown;
}
export interface ContractBubble {
  id: string;
  volume_m3: number;
  equivalent_radius_m: number;
  centroid_m: Vec3;
  velocity_m_s: Vec3;
  status: BubbleStatus;
  pressure_pa?: number | null | undefined;
  temperature_k?: number | null | undefined;
  gas_amount_mol?: number | null | undefined;
  gas_species?: string | null | undefined;
  film_material?: Record<string, unknown> | null | undefined;
  [key: string]: unknown;
}
export interface ContractSurfaceMesh {
  id: string;
  geometry_role: GeometryRole;
  owner_bubble_ids?: readonly string[];
  region_labels?: readonly string[];
  vertex_count: number;
  face_count: number;
  vertices: ArrayRef;
  faces: ArrayRef;
  fields?: Record<string, ArrayRef>;
  [key: string]: unknown;
}
export interface ContractFilmRegion {
  id: string;
  kind: "OUTER" | "SHARED";
  adjacent: readonly [string, string];
  mesh_id?: string | null;
  surface_tension_n_m: number;
  thickness?: Record<string, unknown> | null;
  [key: string]: unknown;
}
export interface ContractJunction {
  id: string;
  incident_film_ids: readonly string[];
  geometry?: ArrayRef;
  measured_angles_deg?: readonly number[];
  measurement_provenance?: Record<string, unknown>;
  [key: string]: unknown;
}
export interface ContractTopologyEvent {
  id: string;
  type: "CONTACT_BEGIN" | "FILM_FORMED" | "COALESCENCE" | "RUPTURE" | "SPLIT" | "CONTACT_END" | "BUBBLE_REMOVED";
  time_s: number;
  bubble_ids_before?: readonly string[];
  bubble_ids_after?: readonly string[];
  film_ids?: readonly string[];
  provenance: { source: ProvenanceSource; detail?: string; [key: string]: unknown };
  [key: string]: unknown;
}
export interface ContractDiagnostics {
  timestep_s?: number;
  nonlinear_iterations?: number;
  linear_iterations?: number;
  residuals?: Record<string, number>;
  max_relative_volume_error?: number;
  mesh_quality?: Record<string, unknown>;
  compute_time_s?: number;
  [key: string]: unknown;
}
export interface ContractFrame {
  contract_version: "1.0.0";
  kind: "FRAME" | "CHECKPOINT";
  frame_id: string;
  simulation_time_s: number;
  manifest: ContractManifest;
  environment: ContractEnvironment;
  bubbles: readonly ContractBubble[];
  surface_meshes: readonly ContractSurfaceMesh[];
  film_regions: readonly ContractFilmRegion[];
  junctions: readonly ContractJunction[];
  topology: { adjacency: readonly Record<string, unknown>[]; events: readonly ContractTopologyEvent[]; [key: string]: unknown };
  diagnostics?: ContractDiagnostics;
  checkpoint_state?: Record<string, unknown>;
  [key: string]: unknown;
}
export interface ContractScenario {
  contract_version: "1.0.0";
  kind: "SCENARIO";
  scenario_id: string;
  random_seed: number;
  requested_fidelity_tier: FidelityTier;
  requested_solver: Record<string, unknown> | null;
  environment: ContractEnvironment;
  initial_bubbles: ContractBubble[];
  initial_surface_meshes?: ContractSurfaceMesh[];
  initial_film_regions?: ContractFilmRegion[];
  initial_junctions?: ContractJunction[];
  user_editable: Record<string, unknown>;
  metadata?: Record<string, unknown>;
  [key: string]: unknown;
}

export interface LoadedContractFrame { document: ContractFrame; provenanceSource: ProvenanceSource; label: string; }
export interface LoadedContractScenario { document: ContractScenario; provenanceSource: ProvenanceSource; label: string; }

export interface BubblePhysicalState {
  id: string;
  status: BubbleStatus;
  equivalentRadius: number;
  position: Vec3;
  volume: number;
  velocity: Vec3;
  pressure?: number | null;
  area?: number | null;
  curvature?: number | null;
  thickness?: number | null;
  volumeError?: number | null;
}
export interface RenderBubble {
  id: string;
  position: Vec3;
  displayRadius: number;
  physical: BubblePhysicalState;
  visible: boolean;
  shapeSource: "CANONICAL_MESH" | "VIEWER_SPHERE_FALLBACK";
}
export interface RenderFilmThickness {
  kind: "SCALAR" | "VERTEX_FIELD" | "FACE_FIELD";
  scalarM?: number;
  valuesM?: readonly number[];
  fieldName?: string;
  provenanceSource: ProvenanceSource;
}
export interface RenderSurfaceMesh {
  id: string;
  geometryRole: GeometryRole;
  ownerBubbleIds: readonly string[];
  regionLabels: readonly string[];
  storage: "INLINE" | "SIDECAR";
  renderable: boolean;
  vertices?: readonly Vec3[];
  faces?: readonly (readonly [number, number, number])[];
  sidecarUri?: string;
  filmId?: string;
  filmKind?: "OUTER" | "SHARED";
  physicalThickness?: RenderFilmThickness;
  provenanceSource: ProvenanceSource;
}
export interface SharedFilmDescriptor {
  id: string;
  adjacentBubbleIds: readonly [string, string];
  meshId?: string | null;
  surfaceTension: number;
  thickness?: Record<string, unknown> | null;
}
export interface JunctionDescriptor {
  id: string;
  incidentFilmIds: readonly string[];
  points?: readonly Vec3[];
  measuredAnglesDeg?: readonly number[];
  measurementProvenance?: Record<string, unknown>;
  provenanceSource: ProvenanceSource;
}
export interface RenderSceneData {
  sourceKind: "FRAME" | "SCENARIO";
  sourceId: string;
  provenanceSource: ProvenanceSource;
  provenanceLabel: string;
  fidelity: FidelityTier;
  featureDisclosures: Readonly<Record<string, FeatureDisclosureStatus>>;
  simulationTime?: number;
  frame?: ContractFrame;
  scenario?: ContractScenario;
  bubbles: readonly RenderBubble[];
  surfaceMeshes: readonly RenderSurfaceMesh[];
  sharedFilms: readonly SharedFilmDescriptor[];
  junctions: readonly JunctionDescriptor[];
  events: readonly ContractTopologyEvent[];
  diagnostics?: ContractDiagnostics;
}
export interface ViewerState {
  mode: ViewerMode;
  editorScenario: ContractScenario;
  selectedIds: Set<string>;
  selectedSurfaceId: string | null;
  addMode: boolean;
  nextEditorId: number;
}
