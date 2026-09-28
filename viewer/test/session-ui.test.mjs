import test from "node:test";
import assert from "node:assert/strict";
import {
  buildSessionInvocation,
  clearStagedSessionCommands,
  commandAvailability,
  commandResultSummary,
  createSessionIntent,
  defaultSessionCapabilities,
  fullSessionCommandSequence,
  parseAuthoritativeSessionMetadata,
  parseSessionCommandHistory,
  serializeSessionCommands,
  stageSessionCommand,
} from "../.build/src/sessionControl.js";
import { createReplay, playReplay } from "../.build/src/replay.js";

const snapshot = (state = "PAUSED", physicalTime = 0.25) => ({
  session_version: "1.0.0",
  scenario: { id: "session-ui-test", sha256: "abc123" },
  backend: { identity: "bubblelab-transient-reference", version: "1.0" },
  random_seed: 7,
  state,
  physical_time_s: physicalTime,
  frame_index: 4,
  capabilities: defaultSessionCapabilities("transient"),
  command_count: 2,
});

const frame = (id, time) => ({
  contract_version: "1.0.0",
  kind: "FRAME",
  frame_id: id,
  simulation_time_s: time,
  manifest: {
    contract_version: "1.0.0",
    units: { system: "SI" },
    solver: { backend: "bubblelab-transient-reference", version: "1" },
    fidelity_tier: "MAXIMUM_REALISM",
    feature_disclosures: {},
    random_seed: 7,
    provenance: { producer: "test" },
  },
  environment: { gravity_m_s2: [0, -9.81, 0], ambient_density_kg_m3: 1.2, ambient_dynamic_viscosity_pa_s: 1.8e-5 },
  bubbles: [],
  surface_meshes: [],
  film_regions: [],
  junctions: [],
  topology: { adjacency: [], events: [] },
});

test("deterministic command generation preserves explicit solver intent", () => {
  let intent = createSessionIntent("transient");
  intent = stageSessionCommand(intent, { command: "RESUME" });
  intent = stageSessionCommand(intent, { command: "RUN_TO_TIME", target_time_s: 0.5 });
  const sequence = fullSessionCommandSequence(intent);
  assert.deepEqual(sequence, [
    { command: "RESUME" },
    { command: "RUN_TO_TIME", target_time_s: 0.5 },
  ]);
  assert.equal(serializeSessionCommands(sequence), serializeSessionCommands(structuredClone(sequence)));
  assert.match(serializeSessionCommands(sequence), /"target_time_s": 0.5/);
});

test("capability gating exposes live controls only for transient", () => {
  const transient = createSessionIntent("transient");
  assert.equal(commandAvailability(transient, "PAUSE").enabled, true);
  assert.equal(commandAvailability(transient, "STEP").enabled, false);
  for (const backend of ["equilibrium", "thinfilm", "thinfilm-events"]) {
    const intent = createSessionIntent(backend);
    assert.equal(commandAvailability(intent, "PAUSE").enabled, false);
    assert.equal(commandAvailability(intent, "RESUME").enabled, false);
    assert.equal(commandAvailability(intent, "RESET").enabled, false);
  }
  assert.equal(defaultSessionCapabilities("transient").persistent_checkpoint_restart, false);
});

test("checkpoint capability and provenance require authoritative backend evidence", () => {
  const authoritative = snapshot("PAUSED", 0.25);
  authoritative.capabilities.persistent_checkpoint_restart = true;
  authoritative.checkpoint_count = 1;
  authoritative.checkpoints = [{
    frame_id: "checkpoint-000004",
    simulation_time_s: 0.25,
    same_build_only: true,
    runtime_checkpoint_version: "1.0.0",
    continuation_format_version: "1.0.0",
    source_scenario: { id: "session-ui-test", sha256: "abc123" },
    backend: { identity: "bubblelab-transient-reference", version: "1.0" },
    integrity: {
      algorithm: "sha256",
      canonicalization: "json-sort-keys-compact-utf8",
      continuation_sha256: "deadbeef",
    },
  }];
  const parsed = parseAuthoritativeSessionMetadata(authoritative);
  assert.equal(parsed.capabilities.persistent_checkpoint_restart, true);
  assert.equal(parsed.checkpoint_count, 1);
  assert.equal(parsed.checkpoints[0].frame_id, "checkpoint-000004");
  assert.equal(parsed.checkpoints[0].same_build_only, true);
  assert.equal(parsed.checkpoints[0].integrity.continuation_sha256, "deadbeef");
});

test("single solver step stages exactly one STEP and remains paused", () => {
  let intent = createSessionIntent("transient");
  intent = stageSessionCommand(intent, { command: "PAUSE" });
  const before = fullSessionCommandSequence(intent).length;
  intent = stageSessionCommand(intent, { command: "STEP" });
  assert.equal(fullSessionCommandSequence(intent).length, before + 1);
  assert.equal(fullSessionCommandSequence(intent).filter((command) => command.command === "STEP").length, 1);
  assert.equal(intent.stagedState, "PAUSED");
});

test("run-to-time validates state, target and authoritative physical time", () => {
  const authoritative = parseAuthoritativeSessionMetadata(snapshot("PAUSED", 0.25));
  let intent = createSessionIntent("transient", authoritative);
  assert.equal(commandAvailability(intent, "RUN_TO_TIME", 0.5).enabled, false);
  intent = stageSessionCommand(intent, { command: "RESUME" });
  assert.equal(commandAvailability(intent, "RUN_TO_TIME", -1).enabled, false);
  assert.equal(commandAvailability(intent, "RUN_TO_TIME", 0.2).enabled, false);
  assert.equal(commandAvailability(intent, "RUN_TO_TIME", 0.5).enabled, true);
  intent = stageSessionCommand(intent, { command: "RUN_TO_TIME", target_time_s: 0.5 });
  assert.equal(intent.stagedState, "PAUSED");
  assert.equal(intent.authoritative.physical_time_s, 0.25);
});

test("reset is solver intent and does not impersonate replay reset", () => {
  let intent = createSessionIntent("transient", parseAuthoritativeSessionMetadata(snapshot("PAUSED", 0.25)));
  intent = stageSessionCommand(intent, { command: "RESET" });
  assert.equal(intent.stagedState, "CREATED");
  assert.deepEqual(fullSessionCommandSequence(intent), [{ command: "RESET" }]);
  assert.equal(intent.authoritative.physical_time_s, 0.25);
});

test("rejections and failures remain explicit in authoritative command presentation", () => {
  const [entry] = parseSessionCommandHistory([{
    sequence: 3,
    command: "STEP",
    requested: {},
    result: "REJECTED",
    state_before: "RUNNING",
    state_after: "RUNNING",
    physical_time_before_s: 0.25,
    physical_time_after_s: 0.25,
    overshoot_s: 0,
    emitted_frame_ids: [],
    emitted_checkpoint_ids: [],
    error: "STEP requires the session to be PAUSED",
  }]);
  assert.equal(entry.result, "REJECTED");
  assert.match(commandResultSummary(entry), /REJECTED/);
  assert.match(commandResultSummary(entry), /requires the session to be PAUSED/);
});

test("replay play state is separate from solver session command intent", () => {
  const replay = playReplay(createReplay([frame("f0", 0), frame("f1", 0.1)]));
  const replayBefore = structuredClone({ index: replay.index, playing: replay.playing });
  let intent = createSessionIntent("transient");
  intent = stageSessionCommand(intent, { command: "PAUSE" });
  assert.deepEqual({ index: replay.index, playing: replay.playing }, replayBefore);
  assert.equal(replay.playing, true);
  assert.deepEqual(fullSessionCommandSequence(intent), [{ command: "PAUSE" }]);
});

test("staging commands never mutates imported authoritative state before backend response", () => {
  const authoritative = parseAuthoritativeSessionMetadata(snapshot("PAUSED", 0.25));
  const before = structuredClone(authoritative);
  let intent = createSessionIntent("transient", authoritative);
  intent = stageSessionCommand(intent, { command: "STEP" });
  assert.deepEqual(authoritative, before);
  assert.deepEqual(intent.authoritative, before);
  assert.equal(intent.authoritative.physical_time_s, 0.25);
  assert.equal(intent.authoritative.frame_index, 4);
});

test("authoritative base history plus staged continuation serializes deterministically", () => {
  const authoritative = parseAuthoritativeSessionMetadata(snapshot("PAUSED", 0.25));
  let intent = createSessionIntent("transient", authoritative, [{ command: "PAUSE" }, { command: "STEP" }]);
  intent = stageSessionCommand(intent, { command: "STEP" });
  assert.deepEqual(fullSessionCommandSequence(intent), [
    { command: "PAUSE" },
    { command: "STEP" },
    { command: "STEP" },
  ]);
  intent = clearStagedSessionCommands(intent);
  assert.deepEqual(fullSessionCommandSequence(intent), [{ command: "PAUSE" }, { command: "STEP" }]);
  assert.equal(intent.stagedState, "PAUSED");
});

test("external handoff invokes authoritative session CLI rather than browser physics", () => {
  const command = buildSessionInvocation("transient", {
    scenarioFile: "case.scenario.json",
    commandsFile: "case.commands.json",
    outputDirectory: "case.session-output",
  });
  assert.match(command, /^python3 bubblelab\/runtime\/tools\/run_session\.py/);
  assert.match(command, /--commands 'case\.commands\.json'/);
  assert.match(command, /--backend transient$/);
  assert.doesNotMatch(command, /replay-play|requestAnimationFrame|canvas/);
});
