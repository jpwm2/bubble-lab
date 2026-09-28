import test from "node:test";
import assert from "node:assert/strict";
import {
  LiveSessionClient,
  LiveSessionTransportError,
  buildLiveSessionBundleDocuments,
  normalizeLiveSessionBaseUrl,
  parseLiveSessionEnvelope,
} from "../.build/src/liveSession.js";

const capabilities = {
  pause: true,
  resume: true,
  step: true,
  run_to_time: true,
  reset: true,
  persistent_checkpoint_restart: true,
  paused_state_edit: false,
};

function frame(id = "session-000001", time = 0.1) {
  return {
    contract_version: "1.0.0",
    kind: "FRAME",
    frame_id: id,
    simulation_time_s: time,
    manifest: {
      contract_version: "1.0.0",
      units: { system: "SI" },
      solver: { backend: "bubblelab-transient-reference", version: "1.0" },
      fidelity_tier: "MAXIMUM_REALISM",
      feature_disclosures: {},
      random_seed: 7,
      provenance: { producer: "test", source_scenario: "live-test" },
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

function historyEntry(overrides = {}) {
  return {
    sequence: 1,
    command: "STEP",
    requested: {},
    result: "ACCEPTED",
    state_before: "PAUSED",
    state_after: "PAUSED",
    physical_time_before_s: 0.05,
    physical_time_after_s: 0.1,
    overshoot_s: 0,
    emitted_frame_ids: ["session-000001"],
    emitted_checkpoint_ids: [],
    ...overrides,
  };
}

function rawEnvelope(overrides = {}) {
  const entry = historyEntry();
  return {
    transport_version: "1.0.0",
    session_id: "live-000001",
    snapshot: {
      session_version: "1.0.0",
      scenario: { id: "live-test", sha256: "abc123" },
      backend: { identity: "bubblelab-transient-reference", version: "1.0" },
      random_seed: 7,
      state: "PAUSED",
      physical_time_s: 0.1,
      frame_index: 1,
      capabilities,
      command_count: 1,
      checkpoint_count: 0,
      checkpoints: [],
    },
    latest_frame: frame(),
    command_history: [entry],
    command_result: entry,
    ...overrides,
  };
}

test("live transport URL is restricted to an explicit IPv4 loopback HTTP origin", () => {
  assert.equal(normalizeLiveSessionBaseUrl("http://127.0.0.1:8765/"), "http://127.0.0.1:8765");
  for (const value of [
    "https://127.0.0.1:8765",
    "http://localhost:8765",
    "http://192.168.1.10:8765",
    "http://127.0.0.1:8765/v1/sessions",
    "http://user:pass@127.0.0.1:8765",
  ]) {
    assert.throws(() => normalizeLiveSessionBaseUrl(value));
  }
});

test("authoritative envelope parsing requires server state, history, and FRAME time to agree", () => {
  const parsed = parseLiveSessionEnvelope(rawEnvelope());
  assert.equal(parsed.sessionId, "live-000001");
  assert.equal(parsed.snapshot.state, "PAUSED");
  assert.equal(parsed.snapshot.physical_time_s, 0.1);
  assert.equal(parsed.latestFrame.frame_id, "session-000001");
  assert.equal(parsed.commandResult.result, "ACCEPTED");

  const badTime = rawEnvelope();
  badTime.latest_frame = frame("session-000001", 0.2);
  assert.throws(() => parseLiveSessionEnvelope(badTime), /physical time/);

  const badCount = rawEnvelope();
  badCount.snapshot = { ...badCount.snapshot, command_count: 2 };
  assert.throws(() => parseLiveSessionEnvelope(badCount), /command_count/);
});

test("client sends solver commands to loopback without locally changing physical state", async () => {
  const calls = [];
  const authoritative = rawEnvelope();
  const fetchImpl = async (url, init = {}) => {
    calls.push({ url: String(url), init });
    return new Response(JSON.stringify(authoritative), {
      status: 200,
      headers: { "Content-Type": "application/json" },
    });
  };
  const client = new LiveSessionClient("http://127.0.0.1:8765", fetchImpl);
  const before = structuredClone(authoritative);
  const response = await client.command("live-000001", { command: "STEP" });
  assert.equal(calls.length, 1);
  assert.equal(calls[0].url, "http://127.0.0.1:8765/v1/sessions/live-000001/commands");
  assert.equal(calls[0].init.method, "POST");
  assert.deepEqual(JSON.parse(calls[0].init.body), { command: "STEP" });
  assert.deepEqual(authoritative, before);
  assert.equal(response.snapshot.physical_time_s, authoritative.snapshot.physical_time_s);
  assert.equal(response.latestFrame.simulation_time_s, authoritative.latest_frame.simulation_time_s);
});

test("structured command rejection carries authoritative unchanged state instead of success", async () => {
  const rejected = historyEntry({
    result: "REJECTED",
    state_before: "CREATED",
    state_after: "CREATED",
    physical_time_before_s: 0,
    physical_time_after_s: 0,
    emitted_frame_ids: [],
    error: "STEP requires the session to be PAUSED",
  });
  const session = rawEnvelope({
    snapshot: {
      ...rawEnvelope().snapshot,
      state: "CREATED",
      physical_time_s: 0,
      frame_index: 0,
      command_count: 1,
    },
    latest_frame: frame("session-000000", 0),
    command_history: [rejected],
    command_result: rejected,
  });
  const fetchImpl = async () => new Response(JSON.stringify({
    error: { code: "invalid_command", message: rejected.error },
    transport_version: "1.0.0",
    session,
  }), {
    status: 409,
    headers: { "Content-Type": "application/json" },
  });
  const client = new LiveSessionClient("http://127.0.0.1:8765", fetchImpl);
  await assert.rejects(
    () => client.command("live-000001", { command: "STEP" }),
    (error) => {
      assert.ok(error instanceof LiveSessionTransportError);
      assert.equal(error.code, "invalid_command");
      assert.equal(error.status, 409);
      assert.equal(error.envelope.snapshot.state, "CREATED");
      assert.equal(error.envelope.snapshot.physical_time_s, 0);
      assert.equal(error.envelope.commandResult.result, "REJECTED");
      return true;
    },
  );
});

test("live response is adapted into an importer-compatible one-FRAME session bundle without fabricating time", () => {
  const parsed = parseLiveSessionEnvelope(rawEnvelope());
  const docs = buildLiveSessionBundleDocuments(parsed, "transient");
  assert.equal(docs.replay.bundle_version, "1.0.0");
  assert.equal(docs.replay.run_settings.backend, "transient");
  assert.equal(docs.replay.run_settings.session_control, true);
  assert.equal(docs.replay.run_settings.live_transport, true);
  assert.deepEqual(docs.replay.frames, [{
    frame_id: parsed.latestFrame.frame_id,
    path: "frames/000000.json",
    simulation_time_s: parsed.latestFrame.simulation_time_s,
  }]);
  assert.equal(docs.session.physical_time_s, parsed.snapshot.physical_time_s);
  assert.equal(docs.frame.simulation_time_s, parsed.snapshot.physical_time_s);
  assert.deepEqual(docs.commands, parsed.commandHistory);
});
