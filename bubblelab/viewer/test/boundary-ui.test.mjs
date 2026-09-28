import test from "node:test";
import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import {
  buildInvocationDescriptor,
  capabilityDisclosure,
  serializeScenarioDeterministic,
  setBackendAndFidelity,
  setSolidBoundaries,
  solidBoundaryDefinitions,
  validateScenarioForBackend,
  validateSolidBoundaries,
} from "../.build/src/lab.js";

const bubble = () => ({
  id: "bubble-1",
  volume_m3: (4 / 3) * Math.PI * 0.01 ** 3,
  equivalent_radius_m: 0.01,
  centroid_m: [0, 0, 0],
  velocity_m_s: [0, 0, 0],
  status: "ALIVE",
  film_material: { effective_sheet_tension_n_m: 0.05 },
});

const scenario = () => ({
  contract_version: "1.0.0",
  kind: "SCENARIO",
  scenario_id: "boundary-ui-test",
  random_seed: 20260918,
  requested_fidelity_tier: "MAXIMUM_REALISM",
  requested_solver: { backend: "transient", features: {} },
  environment: {
    gravity_m_s2: [0, 0, 0],
    ambient_density_kg_m3: 1.204,
    ambient_dynamic_viscosity_pa_s: 0.00001825,
    wind: { velocity_m_s: [0, 0, 0] },
  },
  initial_bubbles: [bubble()],
  user_editable: { features: {}, runtime: { output_cadence_s: 0.01 } },
});

const boundaries = () => [
  {
    id: "floor",
    type: "floor",
    point_m: [0, -0.009, 0],
    normal_outward: [0, 1, 0],
    wall_velocity_m_s: [0, 0, 0],
    wetting: { target_contact_angle_deg: 60, relaxation: 0.35, iterations: 2, contact_band_m: 0.004 },
  },
  {
    id: "obstacle-sphere",
    type: "sphere",
    center_m: [0.04, 0, 0],
    radius_m: 0.005,
    wall_velocity_m_s: [0.01, 0, 0],
    wetting: { target_contact_angle_deg: 90 },
  },
  {
    id: "obstacle-box",
    type: "aabb",
    minimum_m: [-0.02, -0.02, -0.02],
    maximum_m: [-0.01, 0.02, 0.02],
    wall_velocity_m_s: [0, 0, 0],
  },
];

test("solid boundary controls serialize the exact canonical refs and definitions", () => {
  const value = setSolidBoundaries(scenario(), boundaries());
  assert.deepEqual(value.environment.boundary_refs, ["floor", "obstacle-sphere", "obstacle-box"]);
  assert.deepEqual(value.user_editable.solid_boundaries, boundaries());
  assert.equal(value.requested_solver.features.boundary_geometry, true);
  assert.deepEqual(solidBoundaryDefinitions(value), boundaries());
  assert.equal(validateScenarioForBackend(value, "transient").length, 0);

  const parsed = JSON.parse(serializeScenarioDeterministic(value));
  assert.deepEqual(parsed.environment.boundary_refs, ["floor", "obstacle-sphere", "obstacle-box"]);
  assert.equal(parsed.user_editable.solid_boundaries[0].wetting.target_contact_angle_deg, 60);
  assert.equal(parsed.user_editable.solid_boundaries[2].type, "aabb");
});

test("boundary geometry is transient-only and unsupported backend combinations are blocked before handoff", () => {
  const value = setSolidBoundaries(scenario(), boundaries().slice(0, 1));
  const equilibrium = setBackendAndFidelity(value, "equilibrium", "HIGH_FIDELITY");
  assert.ok(validateSolidBoundaries(equilibrium, "equilibrium").some((issue) => issue.path === "environment.boundary_refs" && issue.message.includes("transient")));
  assert.throws(() => buildInvocationDescriptor(equilibrium), /solid-boundary geometry.*transient/);
});

test("accepted transient boundary geometry produces the external runtime invocation", () => {
  const value = setSolidBoundaries(scenario(), boundaries().slice(0, 2));
  const descriptor = buildInvocationDescriptor(value, { scenarioFile: "floor-contact.json", outputDirectory: "out/boundary", frames: 6 });
  assert.equal(descriptor.executesInBrowser, false);
  assert.equal(descriptor.backend, "transient");
  assert.match(descriptor.command, /run_scenario\.py/);
  assert.match(descriptor.command, /--backend transient/);
  assert.match(descriptor.command, /--frames 6/);
});

test("viewer runtime knowledge distinguishes resolved contact, modeled wetting and unimplemented bulk no-slip", () => {
  const rows = capabilityDisclosure(setSolidBoundaries(scenario(), boundaries().slice(0, 1)));
  const byFeature = Object.fromEntries(rows.map((row) => [row.feature, row]));
  assert.equal(byFeature.boundary_geometry.status, "RESOLVED");
  assert.equal(byFeature.solid_boundary_sdf_geometry.status, "RESOLVED");
  assert.equal(byFeature.tracked_film_solid_no_penetration.status, "RESOLVED");
  assert.equal(byFeature.tracked_film_wall_tangential_motion.status, "MODELED");
  assert.equal(byFeature.film_wall_contact_angle.status, "MODELED");
  assert.equal(byFeature.bulk_solid_wall_no_slip.status, "NOT_IMPLEMENTED");
  assert.equal(byFeature.bulk_solid_wall_no_slip.decision, "REJECTED");
  assert.equal(byFeature.bulk_solid_fluid_wall_coupling.status, "NOT_IMPLEMENTED");
});

test("bulk no-slip requests and malformed boundary definitions are rejected truthfully", () => {
  const value = setSolidBoundaries(scenario(), boundaries().slice(0, 1));
  value.requested_solver.features.bulk_solid_wall_no_slip = true;
  assert.ok(validateSolidBoundaries(value, "transient").some((issue) => issue.path.includes("bulk_solid_wall_no_slip")));

  const malformed = scenario();
  malformed.requested_solver.features.boundary_geometry = true;
  malformed.environment.boundary_refs = ["missing"];
  malformed.user_editable.solid_boundaries = [{ id: "bad", type: "sphere", center_m: [0, 0, 0], radius_m: -1 }];
  const issues = validateSolidBoundaries(malformed, "transient");
  assert.ok(issues.some((issue) => issue.message.includes("radius")));
  assert.ok(issues.some((issue) => issue.message.includes("unknown boundary reference")));
});

test("removing all boundaries clears refs and the boundary_geometry request deterministically", () => {
  let value = setSolidBoundaries(scenario(), boundaries().slice(0, 1));
  value = setSolidBoundaries(value, []);
  assert.equal(value.environment.boundary_refs, undefined);
  assert.equal(value.user_editable.solid_boundaries, undefined);
  assert.equal(value.requested_solver.features.boundary_geometry, false);
  assert.equal(validateSolidBoundaries(value, "transient").length, 0);
});

test("Lab panel exposes boundary editors without pretending to execute boundary physics in-browser", async () => {
  const source = await readFile(new URL("../.build/src/labPanel.js", import.meta.url), "utf8");
  assert.match(source, /Add solid boundary/);
  assert.match(source, /floor\/plane, sphere, or AABB/);
  assert.match(source, /External Python runtime only/);
  assert.match(source, /Bulk solid-wall no-slip \/ bulk solid-fluid CFD remains NOT_IMPLEMENTED/);
  assert.doesNotMatch(source, /bulk-no-slip[^\n]*type=.checkbox/i);
});
