import test from "node:test";
import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import {
  addEditorBubble,
  createViewerState,
  getLatestViewerState,
  replaceEditorScenario,
  subscribeViewerState,
} from "../.build/src/store.js";

const scenario = () => ({
  contract_version: "1.0.0",
  kind: "SCENARIO",
  scenario_id: "shared-panel-test",
  random_seed: 7,
  requested_fidelity_tier: "HIGH_FIDELITY",
  requested_solver: { backend: "transient", features: {} },
  environment: { gravity_m_s2: [0, -9.81, 0], ambient_density_kg_m3: 1.204, ambient_dynamic_viscosity_pa_s: 0.00001825 },
  initial_bubbles: [],
  user_editable: { features: {} },
});

test("lab panel shares the same editable scenario state used by viewport store operations", () => {
  const notifications = [];
  const unsubscribe = subscribeViewerState((state) => notifications.push(state.editorScenario.initial_bubbles.length));
  let state = createViewerState(scenario());
  assert.equal(getLatestViewerState(), state);
  state = addEditorBubble(state, { position: [1, 2, 0.01], radius: 0.01 });
  assert.equal(getLatestViewerState(), state);
  assert.equal(state.editorScenario.initial_bubbles.length, 1);

  const replacement = structuredClone(state.editorScenario);
  replacement.environment.gravity_m_s2 = [0, 0, 0];
  const bridged = replaceEditorScenario(replacement);
  assert.equal(bridged, state, "bridge mutates the state object held by main.ts before the next store transition");
  assert.deepEqual(state.editorScenario.environment.gravity_m_s2, [0, 0, 0]);
  assert.ok(notifications.length >= 3);
  unsubscribe();
});

test("viewer HTML mounts the scientific lab panel and keeps physics execution external", async () => {
  const html = await readFile(new URL("../index.html", import.meta.url), "utf8");
  const panelSource = await readFile(new URL("../.build/src/labPanel.js", import.meta.url), "utf8");
  assert.match(html, /id="lab-config-panel"/);
  assert.match(html, /assets\/labPanel\.js/);
  assert.match(panelSource, /External Python runtime only/);
  assert.match(panelSource, /Physics has not been executed in the browser/);
  assert.doesNotMatch(panelSource, /fake Run/i);
});
