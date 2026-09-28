import test from "node:test";
import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { adaptFrame } from "../.build/src/adapter.js";
import { parseContractFrame, parseContractScenario } from "../.build/src/contract.js";
import { createReplay, currentReplayFrame, pauseReplay, playReplay, resetReplay, stepReplay } from "../.build/src/replay.js";
import { addEditorBubble, createViewerState, setMode } from "../.build/src/store.js";

const fixtureRoot = new URL("../../scenarios/fixtures/", import.meta.url);
async function json(name) { return JSON.parse(await readFile(new URL(name, fixtureRoot), "utf8")); }
const fixtureContext = { provenanceSource: "TEST_FIXTURE", provenanceLabel: "Canonical test fixture" };

test("canonical single-bubble fixture uses inline surface mesh and preserves missing pressure", async () => {
  const frame = parseContractFrame(await json("single-isolated.frame.json")), data = adaptFrame(frame, fixtureContext);
  assert.equal(data.bubbles[0].id, "bubble-a");
  assert.equal(data.bubbles[0].shapeSource, "CANONICAL_MESH");
  assert.equal(Object.hasOwn(data.bubbles[0].physical, "pressure"), false);
  assert.equal(data.surfaceMeshes[0].renderable, true);
  assert.equal(data.surfaceMeshes[0].vertices.length, 4);
  assert.equal(data.provenanceSource, "TEST_FIXTURE");
  assert.equal(data.featureDisclosures.pressure, "NOT_IMPLEMENTED");
});

test("canonical shared-film fixture preserves topology, mesh, and TEST_FIXTURE events", async () => {
  const data = adaptFrame(parseContractFrame(await json("two-touching.frame.json")), fixtureContext);
  assert.equal(data.sharedFilms.length, 1); assert.deepEqual(data.sharedFilms[0].adjacentBubbleIds, ["bubble-a", "bubble-b"]);
  assert.equal(data.surfaceMeshes[0].geometryRole, "SHARED_FILM"); assert.equal(data.surfaceMeshes[0].renderable, true);
  assert.deepEqual(data.events.map((event) => event.type), ["CONTACT_BEGIN", "FILM_FORMED"]);
  assert.ok(data.events.every((event) => event.provenance.source === "TEST_FIXTURE"));
});

test("canonical Plateau fixture exposes junction geometry and measurement provenance without upgrading fidelity", async () => {
  const data = adaptFrame(parseContractFrame(await json("three-plateau.frame.json")), fixtureContext);
  assert.equal(data.junctions.length, 1); assert.equal(data.junctions[0].points.length, 2);
  assert.deepEqual(data.junctions[0].measuredAnglesDeg, [120, 120, 120]);
  assert.equal(data.junctions[0].measurementProvenance.source, "TEST_FIXTURE");
  assert.equal(data.featureDisclosures.plateau_angle, "MODELED");
});

test("rupture/coalescence history remains explicit and SIDECAR geometry is not fabricated", async () => {
  const data = adaptFrame(parseContractFrame(await json("rupture-coalescence-history.frame.json")), fixtureContext);
  assert.deepEqual(data.events.map((event) => event.type), ["CONTACT_BEGIN", "COALESCENCE", "RUPTURE"]);
  assert.equal(data.surfaceMeshes[0].storage, "SIDECAR"); assert.equal(data.surfaceMeshes[0].renderable, false);
  assert.ok(data.bubbles.every((bubble) => bubble.visible === false));
});

test("replay orders exact frames, steps deterministically, pauses, and resets without interpolation", async () => {
  const early = parseContractFrame(await json("single-isolated.frame.json")), late = parseContractFrame(await json("rupture-coalescence-history.frame.json"));
  let replay = createReplay([late, early]); assert.equal(currentReplayFrame(replay).frame_id, early.frame_id);
  replay = playReplay(replay); assert.equal(replay.playing, true); replay = stepReplay(replay, 1); assert.equal(currentReplayFrame(replay).frame_id, late.frame_id);
  replay = stepReplay(replay, 1); assert.equal(currentReplayFrame(replay).frame_id, late.frame_id); replay = pauseReplay(replay); assert.equal(replay.playing, false);
  replay = resetReplay(replay); assert.equal(replay.index, 0); assert.equal(replay.playing, false);
});

test("editor operations modify canonical SCENARIO state but never the authoritative FRAME", async () => {
  const scenario = parseContractScenario(await json("single-editable.scenario.json")), frame = parseContractFrame(await json("single-isolated.frame.json")), originalFrame = structuredClone(frame);
  let state = createViewerState(scenario); state = addEditorBubble(state, { position: [0.002, 0, 0.0005], radius: 0.0005 });
  assert.equal(state.editorScenario.initial_bubbles.length, scenario.initial_bubbles.length + 1); assert.deepEqual(frame, originalFrame);
  state = setMode(state, "REPLAY"); const replayLocked = addEditorBubble(state, { position: [0, 0, 0.0005], radius: 0.0005 });
  assert.equal(replayLocked.editorScenario.initial_bubbles.length, state.editorScenario.initial_bubbles.length);
});
