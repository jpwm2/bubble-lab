import test from "node:test";
import assert from "node:assert/strict";
import {
  buildInvocationDescriptor,
  capabilityDisclosure,
  cloneFrameReadOnly,
  createLabState,
  enterReplayReview,
  eventLineage,
  forkReplayToScenarioEdit,
  labPanelPolicy,
  requestUserBurst,
  serializeScenarioDeterministic,
  setBackendAndFidelity,
  setEnvironmentVectors,
  setEventConfiguration,
  setRuntimeOutputCadence,
  setThinFilmConfiguration,
  updateBubble,
  validateScenarioForBackend,
} from "../.build/src/lab.js";

const bubble = (id, radius, x = 0) => ({
  id,
  volume_m3: (4 / 3) * Math.PI * radius ** 3,
  equivalent_radius_m: radius,
  centroid_m: [x, 0, 0],
  velocity_m_s: [0, 0, 0],
  status: "ALIVE",
  temperature_k: 298.15,
  gas_amount_mol: 0.00004,
  gas_species: "air",
  film_material: { effective_sheet_tension_n_m: 0.05 },
});

const scenario = () => ({
  contract_version: "1.0.0",
  kind: "SCENARIO",
  scenario_id: "lab-ui-test",
  random_seed: 42,
  requested_fidelity_tier: "HIGH_FIDELITY",
  requested_solver: { backend: "transient", features: {} },
  environment: {
    gravity_m_s2: [0, -9.81, 0],
    ambient_density_kg_m3: 1.204,
    ambient_dynamic_viscosity_pa_s: 0.00001825,
  },
  initial_bubbles: [bubble("b1", 0.01)],
  user_editable: { features: {}, runtime: { output_cadence_s: 0.01 } },
  metadata: { purpose: "lab ui test" },
});

function sharedFilmScenario(backend = "thinfilm") {
  let value = scenario();
  value.initial_bubbles = [bubble("small", 0.006, -0.006), bubble("large", 0.008, 0.008)];
  value.initial_surface_meshes = [{
    id: "mesh-shared",
    geometry_role: "SHARED_FILM",
    owner_bubble_ids: ["small", "large"],
    region_labels: ["small", "large"],
    vertex_count: 3,
    face_count: 1,
    vertices: { storage: "INLINE", dtype: "float64", shape: [3, 3], values: [0, -0.001, 0, 0, 0.001, 0, 0, 0, 0.001] },
    faces: { storage: "INLINE", dtype: "uint32", shape: [1, 3], values: [0, 1, 2] },
  }];
  value.initial_film_regions = [{
    id: "film-shared",
    kind: "SHARED",
    adjacent: ["small", "large"],
    mesh_id: "mesh-shared",
    surface_tension_n_m: 0.05,
  }];
  value.initial_junctions = [];
  value = setBackendAndFidelity(value, backend, "HIGH_FIDELITY");
  value = setThinFilmConfiguration(value, {
    initial_thickness_m: 8e-6,
    initial_surfactant_mol_m2: 1e-6,
    enable_drainage: false,
    enable_surfactant_diffusion: false,
    enable_gas_diffusion: true,
    dynamic_viscosity_pa_s: 0.001,
    liquid_density_kg_m3: 1000,
    surfactant_diffusivity_m2_s: 0,
    clean_surface_tension_n_m: 0.05,
    surface_elasticity_n_m_per_mol_m2: 2000,
    minimum_surface_tension_n_m: 0.02,
    positivity_safety: 0.45,
    max_substeps: 10000,
    gas_permeability_mol_m_per_m2_s_pa: 1e-11,
  });
  value.requested_solver.features.shared_film_topology = true;
  return value;
}

test("scenario controls edit canonical values and serialize deterministically", () => {
  let value = scenario();
  value = setEnvironmentVectors(value, [0, -3.2, 0], [0.25, 0, 0]);
  value = updateBubble(value, "b1", { equivalentRadiusM: 0.012, positionM: [1, 2, 3], pressurePa: 101500 });
  value = setRuntimeOutputCadence(value, 0.0025);
  const once = serializeScenarioDeterministic(value);
  const twice = serializeScenarioDeterministic(structuredClone(value));
  assert.equal(once, twice);
  assert.deepEqual(value.environment.gravity_m_s2, [0, -3.2, 0]);
  assert.deepEqual(value.environment.wind.velocity_m_s, [0.25, 0, 0]);
  assert.deepEqual(value.initial_bubbles[0].centroid_m, [1, 2, 3]);
  assert.equal(value.user_editable.runtime.output_cadence_s, 0.0025);
  assert.equal(JSON.parse(once).kind, "SCENARIO");
});

test("unsupported feature gating rejects combinations before handoff", () => {
  let value = scenario();
  value = setThinFilmConfiguration(value, { enable_gas_diffusion: true });
  const transientIssues = validateScenarioForBackend(value, "transient");
  assert.ok(transientIssues.some((issue) => issue.message.includes("gas diffusion")));
  value.requested_solver.features.adaptive_mesh_refinement = true;
  assert.ok(validateScenarioForBackend(value, "transient").some((issue) => issue.path.includes("adaptive_mesh_refinement")));
});

test("replay review stays separate from editable scenario and fork is explicit", () => {
  const original = scenario();
  const state = createLabState(original);
  const replay = enterReplayReview(state, {
    bundle_version: "1.0.0",
    contract_version: "1.0.0",
    scenario: { id: "solver-source", sha256: "abc123" },
    backend: { identity: "bubblelab-transient-reference", version: "1" },
    random_seed: 42,
    frames: [{ frame_id: "f0", path: "frames/000000.json", simulation_time_s: 0 }],
    checkpoints: [],
    provenance: { producer: "bubblelab.runtime", source_scenario: "solver-source" },
    fidelity: { requested: "HIGH_FIDELITY", produced: "HIGH_FIDELITY", feature_disclosures: {} },
  });
  assert.equal(replay.mode, "REVIEW_REPLAY");
  const forked = forkReplayToScenarioEdit(replay);
  assert.equal(forked.mode, "EDIT_SCENARIO");
  forked.scenarioDraft.initial_bubbles[0].centroid_m = [9, 9, 9];
  assert.deepEqual(original.initial_bubbles[0].centroid_m, [0, 0, 0]);
});

test("thin-film controls map to documented runtime keys and feature requests", () => {
  let value = scenario();
  value = setThinFilmConfiguration(value, {
    initial_thickness_m: 8e-6,
    initial_surfactant_mol_m2: 2e-6,
    enable_drainage: true,
    enable_surfactant_diffusion: true,
    enable_gas_diffusion: false,
  });
  assert.equal(value.user_editable.thinfilm.initial_thickness_m, 8e-6);
  assert.equal(value.user_editable.thinfilm.initial_surfactant_mol_m2, 2e-6);
  assert.equal(value.requested_solver.features.drainage, true);
  assert.equal(value.requested_solver.features.surfactant_diffusion, true);
  assert.equal(value.requested_solver.features.variable_surface_tension, true);
  assert.equal(value.requested_solver.features.gas_diffusion, false);
});

test("burst request is canonical event intent, not a fabricated frame mutation", () => {
  let value = sharedFilmScenario("thinfilm-events");
  value = setRuntimeOutputCadence(value, 0.05);
  value = requestUserBurst(value, 0.15);
  assert.deepEqual(value.user_editable.events, { enable_rupture: true, allow_user_trigger: true, user_trigger_time_s: 0.15 });
  assert.equal(value.requested_solver.features.rupture, true);
  assert.equal(value.requested_solver.features.coalescence, true);
  assert.equal(validateScenarioForBackend(value, "thinfilm-events").length, 0);
});

test("event configuration rejects a disabled accepted coalescence transition", () => {
  let value = sharedFilmScenario("thinfilm-events");
  value = setRuntimeOutputCadence(value, 0.05);
  value = setEventConfiguration(value, { enable_rupture: true, coalesce_on_shared_film_rupture: false });
  assert.ok(validateScenarioForBackend(value, "thinfilm-events").some((issue) => issue.message.includes("coalesces immediately")));
});

test("backend/fidelity selection and capability disclosure use runtime knowledge or manifest truth", () => {
  const equilibrium = setBackendAndFidelity(scenario(), "equilibrium", "INTERACTIVE");
  assert.ok(validateScenarioForBackend(equilibrium, "equilibrium").some((issue) => issue.message.includes("HIGH_FIDELITY")));
  const runtimeRows = capabilityDisclosure(setBackendAndFidelity(scenario(), "transient", "HIGH_FIDELITY"));
  assert.equal(runtimeRows.find((row) => row.feature === "gas_diffusion").decision, "REQUIRES_BACKEND");
  const manifestRows = capabilityDisclosure(scenario(), {
    contract_version: "1.0.0",
    units: { system: "SI" },
    solver: { backend: "authoritative", version: "9" },
    fidelity_tier: "MAXIMUM_REALISM",
    feature_disclosures: { gas_diffusion: "RESOLVED" },
    random_seed: 42,
    provenance: { producer: "test" },
  });
  assert.deepEqual(manifestRows[0], {
    feature: "gas_diffusion", status: "RESOLVED", decision: "RESULT_ONLY", source: "RESULT_MANIFEST",
    note: "Authoritative result disclosure from authoritative 9",
  });
});

test("invocation descriptor generates an external runtime command and never claims browser execution", () => {
  const value = sharedFilmScenario("thinfilm");
  const descriptor = buildInvocationDescriptor(value, { scenarioFile: "prepared.json", outputDirectory: "out/replay", frames: 12 });
  assert.equal(descriptor.executesInBrowser, false);
  assert.equal(descriptor.backend, "thinfilm");
  assert.match(descriptor.command, /bubblelab\/runtime\/tools\/run_scenario\.py/);
  assert.match(descriptor.command, /--backend thinfilm/);
  assert.match(descriptor.command, /--frames 12/);
});

test("event lineage exposes rupture/coalescence parents, children, films and provenance", () => {
  const rows = eventLineage([
    { id: "e2", type: "COALESCENCE", time_s: 0.2, bubble_ids_before: ["a", "b"], bubble_ids_after: ["ab"], film_ids: ["f"], provenance: { source: "SOLVER", detail: "post rupture" } },
    { id: "e1", type: "RUPTURE", time_s: 0.1, bubble_ids_before: ["a", "b"], bubble_ids_after: ["a", "b"], film_ids: ["f"], provenance: { source: "USER", detail: "requested" } },
  ]);
  assert.deepEqual(rows.map((row) => row.eventId), ["e1", "e2"]);
  assert.deepEqual(rows[1].before, ["a", "b"]);
  assert.deepEqual(rows[1].after, ["ab"]);
  assert.equal(rows[0].provenance, "USER · requested");
});

test("mobile policy keeps lab controls collapsible while critical state remains persistent", () => {
  assert.deepEqual(labPanelPolicy(390, 844), {
    orientation: "PORTRAIT", inspector: "DRAWER", compact: true, scenarioControlsCollapsible: true, criticalStatePersistent: true,
  });
  assert.deepEqual(labPanelPolicy(1280, 800), {
    orientation: "LANDSCAPE", inspector: "SIDEBAR", compact: false, scenarioControlsCollapsible: false, criticalStatePersistent: true,
  });
});

test("frame helper clones authoritative FRAME rather than sharing mutable references", () => {
  const frame = {
    contract_version: "1.0.0", kind: "FRAME", frame_id: "f0", simulation_time_s: 0,
    manifest: { contract_version: "1.0.0", units: { system: "SI" }, solver: { backend: "x", version: "1" }, fidelity_tier: "HIGH_FIDELITY", feature_disclosures: {}, random_seed: 1, provenance: { producer: "x" } },
    environment: { gravity_m_s2: [0, 0, 0], ambient_density_kg_m3: 1, ambient_dynamic_viscosity_pa_s: 1e-5 },
    bubbles: [bubble("frame-bubble", 0.01)], surface_meshes: [], film_regions: [], junctions: [], topology: { adjacency: [], events: [] },
  };
  const cloned = cloneFrameReadOnly(frame);
  cloned.bubbles[0].centroid_m = [3, 3, 3];
  assert.deepEqual(frame.bubbles[0].centroid_m, [0, 0, 0]);
});
