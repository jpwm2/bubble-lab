import test from "node:test";
import assert from "node:assert/strict";
import { adaptFrame } from "../.build/src/adapter.js";
import {
  fresnelSchlick,
  normalIncidenceReflectance,
  resolveOpticalThickness,
  thinFilmPhase,
  thinFilmReflectance,
  thinFilmRgb,
} from "../.build/src/optics.js";

test("normal-incidence Fresnel reflectance matches the exact dielectric result", () => {
  assert.ok(Math.abs(normalIncidenceReflectance(1, 1.5) - 0.04) < 1e-15);
  assert.ok(Math.abs(fresnelSchlick(1, 1.5, 1) - 0.04) < 1e-15);
});

test("thin-film phase advances by 2pi for one optical thickness period", () => {
  const wavelengthNm = 550, index = 1.333, thicknessM = 120e-9;
  const periodM = wavelengthNm * 1e-9 / (2 * index);
  const delta = thinFilmPhase(thicknessM + periodM, wavelengthNm, index, 1) - thinFilmPhase(thicknessM, wavelengthNm, index, 1);
  assert.ok(Math.abs(delta - 2 * Math.PI) < 1e-12);
});

test("zero thickness cancels reflection for a symmetric air-film-air stack", () => {
  const zero = thinFilmReflectance({ thicknessM: 0, wavelengthNm: 550, cosIncident: 1, nIncident: 1, nFilm: 1.333, nExit: 1 });
  const tiny = thinFilmReflectance({ thicknessM: 1e-15, wavelengthNm: 550, cosIncident: 1, nIncident: 1, nFilm: 1.333, nExit: 1 });
  assert.ok(zero < 1e-15);
  assert.ok(tiny < 1e-12);
});

test("thin-film response changes with incidence angle", () => {
  const normal = thinFilmReflectance({ thicknessM: 350e-9, wavelengthNm: 550, cosIncident: 1 });
  const oblique = thinFilmReflectance({ thicknessM: 350e-9, wavelengthNm: 550, cosIncident: 0.45 });
  assert.ok(Math.abs(normal - oblique) > 0.01);
});

test("sampled RGB is deterministic for fixed optical inputs", () => {
  const rgb = thinFilmRgb(350e-9, 0.65);
  assert.deepEqual(rgb.map((value) => Number(value.toFixed(8))), [0.53246238, 0.63289507, 0.57049789]);
  assert.deepEqual(thinFilmRgb(350e-9, 0.65), rgb);
});

test("grazing-angle optics stay finite and bounded", () => {
  for (const wavelengthNm of [420, 550, 660]) {
    const reflectance = thinFilmReflectance({ thicknessM: 350e-9, wavelengthNm, cosIncident: 1e-9 });
    assert.ok(Number.isFinite(reflectance));
    assert.ok(reflectance >= 0 && reflectance <= 1);
  }
  const grazing = fresnelSchlick(1, 1.333, 0);
  assert.ok(Number.isFinite(grazing));
  assert.ok(grazing >= 0 && grazing <= 1);
});

test("thickness source classification never upgrades visual preview into physics", () => {
  const physical = { kind: "SCALAR", scalarM: 420e-9 };
  assert.equal(resolveOpticalThickness("RESOLVED", physical, "AUTO", 350e-9).source, "PHYSICAL_RESOLVED");
  assert.equal(resolveOpticalThickness("MODELED", physical, "AUTO", 350e-9).source, "PHYSICAL_MODELED");
  assert.equal(resolveOpticalThickness(undefined, physical, "AUTO", 350e-9).source, "CONTRACT_INPUT");
  assert.equal(resolveOpticalThickness("NOT_IMPLEMENTED", physical, "AUTO", 350e-9).source, "BLOCKED_BY_DISCLOSURE");
  const preview = resolveOpticalThickness("NOT_IMPLEMENTED", physical, "VISUAL_PREVIEW", 333e-9);
  assert.equal(preview.source, "VISUAL_ONLY");
  assert.equal(preview.thicknessM, 333e-9);
  assert.equal(resolveOpticalThickness("RESOLVED", physical, "OFF", 333e-9).source, "NONE");
});

test("adapter preserves authoritative inline vertex thickness and does not synthesize absent thickness", () => {
  const base = {
    contract_version: "1.0.0",
    kind: "FRAME",
    frame_id: "optics-fixture",
    simulation_time_s: 0,
    manifest: {
      contract_version: "1.0.0",
      units: { system: "SI" },
      solver: { backend: "optics-test", version: "1" },
      fidelity_tier: "HIGH_FIDELITY",
      feature_disclosures: { film_thickness: "RESOLVED" },
      random_seed: 0,
      provenance: { producer: "optics-test" },
    },
    environment: { gravity_m_s2: [0, 0, 0], ambient_density_kg_m3: 1.2, ambient_dynamic_viscosity_pa_s: 1.8e-5 },
    bubbles: [],
    film_regions: [{
      id: "film-a", kind: "OUTER", adjacent: ["bubble-a", "EXTERIOR"], mesh_id: "mesh-a",
      surface_tension_n_m: 0.03, thickness: { field: "film_thickness_m" },
    }],
    junctions: [],
    topology: { adjacency: [], events: [] },
  };
  const mesh = {
    id: "mesh-a", geometry_role: "OUTER_FILM", owner_bubble_ids: ["bubble-a"], vertex_count: 3, face_count: 1,
    vertices: { storage: "INLINE", dtype: "float64", shape: [3, 3], values: [0, 0, 0, 1, 0, 0, 0, 1, 0] },
    faces: { storage: "INLINE", dtype: "uint32", shape: [1, 3], values: [0, 1, 2] },
    fields: { film_thickness_m: { storage: "INLINE", dtype: "float64", shape: [3], values: [200e-9, 300e-9, 400e-9] } },
  };
  const withThickness = adaptFrame({ ...base, surface_meshes: [mesh] }, { provenanceSource: "SOLVER", provenanceLabel: "test" });
  assert.equal(withThickness.surfaceMeshes[0].physicalThickness.kind, "VERTEX_FIELD");
  assert.deepEqual(withThickness.surfaceMeshes[0].physicalThickness.valuesM, [200e-9, 300e-9, 400e-9]);

  const withoutThickness = adaptFrame({
    ...base,
    manifest: { ...base.manifest, feature_disclosures: { film_thickness: "NOT_IMPLEMENTED" } },
    film_regions: [{ ...base.film_regions[0], thickness: null }],
    surface_meshes: [{ ...mesh, fields: {} }],
  }, { provenanceSource: "SOLVER", provenanceLabel: "test" });
  assert.equal(withoutThickness.surfaceMeshes[0].physicalThickness, undefined);
});
