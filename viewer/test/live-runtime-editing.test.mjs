import test from "node:test";
import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { LiveSessionClient } from "../.build/src/liveSession.js";

const capabilities = {
  pause: true,
  resume: true,
  step: true,
  run_to_time: true,
  reset: true,
  persistent_checkpoint_restart: true,
  paused_state_edit: true,
};

function frame() {
  return {
    contract_version: "1.0.0",
    kind: "FRAME",
    frame_id: "session-000001",
    simulation_time_s: 0,
    manifest: {
      contract_version: "1.0.0",
      units: { system: "SI" },
      solver: { backend: "bubblelab-transient-reference", version: "1.0" },
      fidelity_tier: "MAXIMUM_REALISM",
      feature_disclosures: {},
      random_seed: 7,
      provenance: { producer: "test", source_scenario: "live-edit-test" },
    },
    environment: {
      gravity_m_s2: [0, -9.81, 0],
      ambient_density_kg_m3: 1.2,
      ambient_dynamic_viscosity_pa_s: 1.8e-5,
    },
    bubbles: [],
    surface_meshes: [],
    film_regions: [],
    junctions: [],
    topology: { adjacency: [], events: [] },
  };
}

function envelope(command, requested) {
  const entry = {
    sequence: 1,
    command,
    requested,
    result: "ACCEPTED",
    state_before: "PAUSED",
    state_after: "PAUSED",
    physical_time_before_s: 0,
    physical_time_after_s: 0,
    overshoot_s: 0,
    emitted_frame_ids: ["session-000001"],
    emitted_checkpoint_ids: [],
  };
  return {
    transport_version: "1.0.0",
    session_id: "live-edit",
    snapshot: {
      session_version: "1.1.0",
      scenario: { id: "live-edit-test", sha256: "abc123" },
      backend: { identity: "bubblelab-transient-reference", version: "1.0" },
      random_seed: 7,
      state: "PAUSED",
      physical_time_s: 0,
      frame_index: 1,
      capabilities,
      command_count: 1,
      checkpoint_count: 0,
      checkpoints: [],
    },
    latest_frame: frame(),
    command_history: [entry],
    command_result: entry,
  };
}

test("live client sends authoritative edit commands unchanged to the hardened command route", async () => {
  const command = {
    command: "ADD_BUBBLE",
    bubble_id: "bubble-2",
    centroid_m: [0.018, 0, 0],
    equivalent_radius_m: 0.004,
    velocity_m_s: [-0.01, 0, 0],
    surface_tension_n_m: 0.05,
  };
  const calls = [];
  const fetchImpl = async (url, init = {}) => {
    calls.push({ url: String(url), init });
    return new Response(JSON.stringify(envelope(command.command, {
      ...command,
      command: undefined,
      authoritative_rebuild: "REGION_CLASSIFICATION_ONLY",
    })), {
      status: 200,
      headers: { "Content-Type": "application/json" },
    });
  };
  const client = new LiveSessionClient("http://127.0.0.1:8765", fetchImpl);
  const response = await client.command("live-edit", command);
  assert.equal(calls.length, 1);
  assert.equal(calls[0].url, "http://127.0.0.1:8765/v1/sessions/live-edit/commands");
  assert.equal(calls[0].init.method, "POST");
  assert.deepEqual(JSON.parse(calls[0].init.body), command);
  assert.equal(response.commandResult.command, "ADD_BUBBLE");
  assert.equal(response.snapshot.state, "PAUSED");
  assert.equal(response.snapshot.physical_time_s, 0);
  assert.equal(response.snapshot.capabilities.paused_state_edit, true);
});

test("built Lab panel exposes all five backend edit operations only through paused edit UI", async () => {
  const panel = await readFile(new URL("../.build/src/liveSessionPanel.js", import.meta.url), "utf8");
  for (const operation of [
    "ADD_BUBBLE",
    "DELETE_BUBBLE",
    "MOVE_BUBBLE",
    "RESIZE_BUBBLE",
    "SET_BUBBLE_VELOCITY",
  ]) {
    assert.match(panel, new RegExp(operation));
  }
  assert.match(panel, /live-apply-edit/);
  assert.match(panel, /paused_state_edit/);
  assert.match(panel, /state === "PAUSED"/);
  assert.match(panel, /activeClient.*command/s);
});
