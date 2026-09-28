import test from "node:test";
import assert from "node:assert/strict";
import { fitSpheres } from "../.build/src/camera.js";
import { parseContractFrame } from "../.build/src/contract.js";
import { createViewerState, selectBubble, selectSurface } from "../.build/src/store.js";

test("contract parser rejects unknown major/version instead of guessing", () => {
  assert.throws(() => parseContractFrame({ contract_version: "2.0.0", kind: "FRAME" }), /Unsupported Bubble Lab contract version/);
});
test("selection replacement and additive toggle remain deterministic", () => {
  const scenario = { contract_version: "1.0.0", kind: "SCENARIO", scenario_id: "test", random_seed: 0, requested_fidelity_tier: "INTERACTIVE", requested_solver: null, environment: { gravity_m_s2: [0, -9.8, 0], ambient_density_kg_m3: 1.2, ambient_dynamic_viscosity_pa_s: 0.000018 }, initial_bubbles: [{ id: "a", volume_m3: 1e-9, equivalent_radius_m: 0.001, centroid_m: [0, 0, 0], velocity_m_s: [0, 0, 0], status: "ALIVE" }, { id: "b", volume_m3: 1e-9, equivalent_radius_m: 0.001, centroid_m: [0.002, 0, 0], velocity_m_s: [0, 0, 0], status: "ALIVE" }], user_editable: {} };
  let state = createViewerState(scenario); state = selectBubble(state, "a"); state = selectBubble(state, "b", true); assert.deepEqual([...state.selectedIds].sort(), ["a", "b"]); state = selectBubble(state, "a", true); assert.deepEqual([...state.selectedIds], ["b"]); state = selectSurface(state, "film-a"); assert.equal(state.selectedSurfaceId, "film-a"); assert.deepEqual([...state.selectedIds], []); state = selectBubble(state, "b"); assert.equal(state.selectedSurfaceId, null); assert.deepEqual([...state.selectedIds], ["b"]);
});
test("camera fit handles canonical millimetre-scale geometry", () => {
  const fit = fitSpheres([{ center: [-0.001, 0, 0], radius: 0.001 }, { center: [0.001, 0, 0], radius: 0.001 }]); assert.deepEqual(fit.target, [0, 0, 0]); assert.ok(fit.distance > 0.001); assert.ok(fit.distance < 0.1); assert.ok(Number.isFinite(fit.distance));
});
