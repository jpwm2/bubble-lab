import test from "node:test";
import assert from "node:assert/strict";
import {
  deterministicSampleIndices,
  discoverScalarFields,
  discoverVectorFields,
  extractAmrDiagnostics,
  extractRemeshDiagnostics,
  normalizedScalar,
  resolveScalarRange,
  scalarStatistics,
  summarizeSystem,
  topologySelectionForJunction,
  topologySelectionForSurface,
  viewerDerivedNormalDescriptor,
} from "../.build/src/debug.js";

function frameFixture() {
  return {
    contract_version: "1.0.0",
    kind: "FRAME",
    frame_id: "debug-test",
    simulation_time_s: 0.125,
    manifest: {
      contract_version: "1.0.0",
      units: { system: "SI" },
      solver: { backend: "debug-solver", version: "7" },
      fidelity_tier: "HIGH_FIDELITY",
      feature_disclosures: {
        film_thickness: "RESOLVED",
        pressure: "RESOLVED",
        curvature: "NOT_IMPLEMENTED",
        velocity: "MODELED",
        amr: "RESOLVED",
        remeshing: "RESOLVED",
      },
      random_seed: 42,
      provenance: { producer: "debug-test" },
    },
    environment: {
      gravity_m_s2: [0, 0, -9.81],
      ambient_density_kg_m3: 1.2,
      ambient_dynamic_viscosity_pa_s: 1.8e-5,
      wind: { velocity_m_s: [1, 2, 3] },
    },
    bubbles: [
      {
        id: "a", volume_m3: 1, equivalent_radius_m: 0.5, centroid_m: [0, 0, 0], velocity_m_s: [1, 0, 0],
        status: "ALIVE", pressure_pa: 101400, temperature_k: 300, gas_amount_mol: 0.1, surface_area_m2: 3.1,
      },
      {
        id: "b", volume_m3: 2, equivalent_radius_m: 0.7, centroid_m: [1, 0, 0], velocity_m_s: [0, 1, 0],
        status: "ALIVE", pressure_pa: 101300, temperature_k: 301, gas_amount_mol: 0.2, surface_area_m2: 4.2,
      },
    ],
    surface_meshes: [
      {
        id: "shared-mesh", geometry_role: "SHARED_FILM", owner_bubble_ids: ["a", "b"], vertex_count: 4, face_count: 2,
        vertices: { storage: "INLINE", dtype: "float64", shape: [4, 3], values: [0,0,0, 1,0,0, 1,1,0, 0,1,0] },
        faces: { storage: "INLINE", dtype: "uint32", shape: [2, 3], values: [0,1,2, 0,2,3] },
        fields: {
          film_thickness_m: { storage: "INLINE", dtype: "float64", shape: [4], values: [2e-7, 3e-7, 4e-7, 5e-7] },
          curvature_m_inv: { storage: "INLINE", dtype: "float64", shape: [2], values: [10, 12] },
          velocity_m_s: { storage: "INLINE", dtype: "float64", shape: [4, 3], values: [1,0,0, 2,0,0, 3,0,0, 4,0,0] },
        },
      },
    ],
    film_regions: [
      {
        id: "shared-film", kind: "SHARED", adjacent: ["a", "b"], mesh_id: "shared-mesh",
        surface_tension_n_m: 0.03, thickness: { mean_m: 3.5e-7 },
      },
    ],
    junctions: [
      {
        id: "j0", incident_film_ids: ["f1", "f2", "f3"],
        geometry: { storage: "INLINE", dtype: "float64", shape: [2, 3], values: [0,0,0, 0,0,1] },
        measured_angles_deg: [120, 120, 120],
        measurement_provenance: { source: "SOLVER" },
      },
    ],
    topology: {
      adjacency: [{ a: "a", b: "b", film_id: "shared-film" }],
      events: [{ id: "e0", type: "FILM_FORMED", time_s: 0.1, film_ids: ["shared-film"], provenance: { source: "SOLVER" } }],
    },
    diagnostics: {
      timestep_s: 0.001,
      nonlinear_iterations: 3,
      linear_iterations: 14,
      residuals: { pressure_pa: 1e-7, divergence: 2e-8 },
      max_relative_volume_error: 1e-6,
      compute_time_s: 0.04,
      mesh_quality: {
        amr: {
          active_cells_by_level: { "0": 100, "1": 40 },
          max_refinement_level: 1,
          finest_spacing_m: 0.00025,
          refinement_criterion: "vorticity",
          pressure_residual: 1e-8,
          divergence_residual: 2e-8,
        },
        remeshing: {
          split_count: 4,
          collapse_count: 2,
          flip_count: 1,
          smooth_count: 3,
          vertices_before: 100,
          vertices_after: 102,
          faces_before: 196,
          faces_after: 200,
          quality_before: 0.51,
          quality_after: 0.73,
          pre_projection_volume_change: 4e-7,
          scalar_transfer_error: 8e-8,
        },
      },
    },
  };
}

test("discovers vertex and face scalar fields and gates NOT_IMPLEMENTED physics", () => {
  const fields = discoverScalarFields(frameFixture(), "TEST_FIXTURE");
  const thickness = fields.find((field) => field.key === "mesh:shared-mesh:film_thickness_m");
  assert.equal(thickness.association, "VERTEX");
  assert.equal(thickness.units, "m");
  assert.equal(thickness.provenanceClass, "CANONICAL_PHYSICAL");
  assert.equal(thickness.disclosure, "RESOLVED");
  assert.equal(thickness.available, true);

  const curvature = fields.find((field) => field.key === "mesh:shared-mesh:curvature_m_inv");
  assert.equal(curvature.association, "FACE");
  assert.equal(curvature.disclosure, "NOT_IMPLEMENTED");
  assert.equal(curvature.provenanceClass, "UNAVAILABLE");
  assert.equal(curvature.available, false);

  const pressure = fields.find((field) => field.key === "bubble:pressure_pa");
  assert.deepEqual(pressure.values, [101400, 101300]);
  assert.equal(pressure.association, "BUBBLE");

  const residual = fields.find((field) => field.key === "diagnostic:residuals:divergence");
  assert.equal(residual.provenanceClass, "SOLVER_DIAGNOSTIC");
  assert.equal(residual.association, "SYSTEM");
});

test("discovers mesh, bubble and environment vector fields without synthesizing force data", () => {
  const fields = discoverVectorFields(frameFixture(), "TEST_FIXTURE");
  const meshVelocity = fields.find((field) => field.key === "mesh:shared-mesh:velocity_m_s");
  assert.equal(meshVelocity.association, "VERTEX");
  assert.equal(meshVelocity.values.length, 4);
  assert.equal(meshVelocity.disclosure, "MODELED");

  assert.deepEqual(fields.find((field) => field.key === "bubble:velocity_m_s").values, [[1,0,0],[0,1,0]]);
  assert.deepEqual(fields.find((field) => field.key === "environment:gravity_m_s2").values, [[0,0,-9.81]]);
  assert.deepEqual(fields.find((field) => field.key === "environment:wind.velocity_m_s").values, [[1,2,3]]);
  assert.equal(fields.some((field) => field.name.includes("force") || field.name.includes("traction")), false);
});

test("scalar statistics ignore NaN and report missing values explicitly", () => {
  const stats = scalarStatistics([1, Number.NaN, -2, 5, Number.POSITIVE_INFINITY]);
  assert.equal(stats.count, 3);
  assert.equal(stats.missingCount, 2);
  assert.equal(stats.min, -2);
  assert.equal(stats.max, 5);
  assert.equal(stats.mean, 4 / 3);
  assert.deepEqual(scalarStatistics([Number.NaN]), { count: 0, missingCount: 1 });
});

test("automatic and manual ranges are deterministic and signed ranges become symmetric only when requested", () => {
  assert.deepEqual(resolveScalarRange([-2, 1, 5], { mode: "AUTO" }), { min: -2, max: 5, diverging: false, source: "AUTO" });
  assert.deepEqual(resolveScalarRange([-2, 1, 5], { mode: "AUTO", diverging: true }), { min: -5, max: 5, diverging: true, source: "AUTO" });
  assert.deepEqual(resolveScalarRange([-2, 1, 5], { mode: "MANUAL", min: -3, max: 7, diverging: true }), { min: -7, max: 7, diverging: true, source: "MANUAL" });
  assert.equal(normalizedScalar(0, { min: -5, max: 5, diverging: true, source: "AUTO" }), 0.5);
  assert.equal(normalizedScalar(Number.NaN, { min: 0, max: 1, diverging: false, source: "AUTO" }), undefined);
});

test("constant ranges remain finite rather than dividing by zero", () => {
  const range = resolveScalarRange([3, 3, 3], { mode: "AUTO" });
  assert.ok(range.max > range.min);
  assert.ok(Number.isFinite(normalizedScalar(3, range)));
});

test("deterministic subsampling preserves endpoints and never mutates source counts", () => {
  assert.deepEqual(deterministicSampleIndices(10, 4), [0, 3, 6, 9]);
  assert.deepEqual(deterministicSampleIndices(4, 10), [0, 1, 2, 3]);
  assert.deepEqual(deterministicSampleIndices(100000, 1), [0]);
  assert.deepEqual(deterministicSampleIndices(0, 10), []);
});

test("system summary reports topology counts, fidelity, solver and active feature disclosures", () => {
  const summary = summarizeSystem(frameFixture());
  assert.equal(summary.bubbleCount, 2);
  assert.equal(summary.sharedFilmCount, 1);
  assert.equal(summary.junctionCount, 1);
  assert.equal(summary.topologyEventCount, 1);
  assert.equal(summary.fidelityTier, "HIGH_FIDELITY");
  assert.equal(summary.solverIdentity, "debug-solver 7");
  assert.ok(summary.activeFeatures.includes("film_thickness=RESOLVED"));
  assert.equal(summary.activeFeatures.some((entry) => entry.startsWith("curvature=")), false);
});

test("AMR and remeshing metadata are extracted numerically without inventing spatial boxes", () => {
  const frame = frameFixture();
  assert.deepEqual(extractAmrDiagnostics(frame), {
    active_cells_by_level: { "0": 100, "1": 40 },
    max_refinement_level: 1,
    finest_spacing_m: 0.00025,
    refinement_criterion: "vorticity",
    pressure_residual: 1e-8,
    divergence_residual: 2e-8,
  });
  assert.deepEqual(extractRemeshDiagnostics(frame), {
    split_count: 4,
    collapse_count: 2,
    flip_count: 1,
    smooth_count: 3,
    vertices_before: 100,
    vertices_after: 102,
    faces_before: 196,
    faces_after: 200,
    quality_before: 0.51,
    quality_after: 0.73,
    pre_projection_volume_change: 4e-7,
    scalar_transfer_error: 8e-8,
  });

  const without = { ...frame, diagnostics: { timestep_s: 0.1 } };
  assert.equal(extractAmrDiagnostics(without), undefined);
  assert.equal(extractRemeshDiagnostics(without), undefined);
});

test("shared-film and junction selection resolve canonical topology identities", () => {
  const frame = frameFixture();
  assert.deepEqual(topologySelectionForSurface(frame, "shared-mesh"), {
    kind: "FILM",
    id: "shared-film",
    filmKind: "SHARED",
    adjacentIds: ["a", "b"],
    meshId: "shared-mesh",
  });
  assert.deepEqual(topologySelectionForJunction(frame, "j0"), {
    kind: "JUNCTION",
    id: "j0",
    incidentFilmIds: ["f1", "f2", "f3"],
    measuredAnglesDeg: [120, 120, 120],
    measurementProvenance: { source: "SOLVER" },
  });
});

test("computed render normals are explicitly VIEWER_DERIVED rather than curvature or force", () => {
  const descriptor = viewerDerivedNormalDescriptor("shared-mesh", "VERTEX", 4);
  assert.equal(descriptor.provenanceClass, "VIEWER_DERIVED");
  assert.equal(descriptor.association, "VERTEX");
  assert.equal(descriptor.sourcePath, "renderer.geometry.computeVertexNormals");
  assert.equal(descriptor.available, true);
});
