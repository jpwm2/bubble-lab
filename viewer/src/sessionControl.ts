import { parseReplayBundleIndex, type ReplayBundleIndex } from "./runtimeBundle.js";

export type RuntimeSessionBackend = "equilibrium" | "transient" | "thinfilm" | "thinfilm-events";
export type RuntimeSessionState = "CREATED" | "PAUSED" | "RUNNING" | "COMPLETED" | "FAILED";
export type SessionCommandName = "PAUSE" | "RESUME" | "STEP" | "RUN_TO_TIME" | "RESET";
export type SessionCommand =
  | { command: "PAUSE" | "RESUME" | "STEP" | "RESET" }
  | { command: "RUN_TO_TIME"; target_time_s: number };

export interface SessionCapabilities {
  pause: boolean;
  resume: boolean;
  step: boolean;
  run_to_time: boolean;
  reset: boolean;
  persistent_checkpoint_restart: boolean;
  paused_state_edit: boolean;
}

export interface SessionCheckpointProvenance {
  frame_id: string;
  simulation_time_s: number;
  same_build_only: boolean;
  runtime_checkpoint_version: string;
  continuation_format_version: string;
  source_scenario: { id: string; sha256: string };
  backend: { identity: string; version: string; [key: string]: unknown };
  integrity: {
    algorithm: string;
    continuation_sha256: string;
    canonicalization?: string;
    [key: string]: unknown;
  };
}

export interface AuthoritativeSessionSnapshot {
  session_version: string;
  scenario: { id: string; sha256: string };
  backend: { identity: string; version: string; [key: string]: unknown };
  random_seed: number;
  state: RuntimeSessionState;
  physical_time_s: number;
  frame_index: number;
  capabilities: SessionCapabilities;
  command_count: number;
  checkpoint_count: number;
  checkpoints: readonly SessionCheckpointProvenance[];
}

export interface SessionCommandHistoryEntry {
  sequence: number;
  command: string;
  requested: Record<string, unknown>;
  result: "ACCEPTED" | "REJECTED" | "FAILED";
  state_before: RuntimeSessionState;
  state_after: RuntimeSessionState;
  physical_time_before_s: number;
  physical_time_after_s: number;
  overshoot_s: number;
  emitted_frame_ids: readonly string[];
  emitted_checkpoint_ids: readonly string[];
  error?: string;
}

export interface AuthoritativeSessionBundle {
  backend: RuntimeSessionBackend;
  replay: ReplayBundleIndex;
  snapshot: AuthoritativeSessionSnapshot;
  commandHistory: readonly SessionCommandHistoryEntry[];
  replayableCommands: readonly SessionCommand[];
}

export interface SessionIntentState {
  backend: RuntimeSessionBackend;
  authoritative: AuthoritativeSessionSnapshot | null;
  baseCommands: readonly SessionCommand[];
  stagedCommands: readonly SessionCommand[];
  stagedState: RuntimeSessionState;
}

export interface CommandAvailability {
  enabled: boolean;
  reason: string;
}

const SESSION_STATES = new Set<RuntimeSessionState>(["CREATED", "PAUSED", "RUNNING", "COMPLETED", "FAILED"]);
const RUNTIME_BACKENDS = new Set<RuntimeSessionBackend>(["equilibrium", "transient", "thinfilm", "thinfilm-events"]);
const PERSISTENCE_HISTORY_COMMANDS = new Set(["SAVE_CHECKPOINT", "RESTORE_CHECKPOINT"]);

function record(value: unknown, label: string): Record<string, unknown> {
  if (typeof value !== "object" || value === null || Array.isArray(value)) throw new Error(`${label} must be an object`);
  return value as Record<string, unknown>;
}

function finiteNonNegative(value: unknown, label: string): number {
  if (typeof value !== "number" || !Number.isFinite(value) || value < 0) throw new Error(`${label} must be a finite non-negative number`);
  return value;
}

function nonNegativeInteger(value: unknown, label: string): number {
  if (!Number.isInteger(value) || (value as number) < 0) throw new Error(`${label} must be a non-negative integer`);
  return value as number;
}

function nonEmptyString(value: unknown, label: string): string {
  if (typeof value !== "string" || !value) throw new Error(`${label} is required`);
  return value;
}

function sessionState(value: unknown, label: string): RuntimeSessionState {
  if (typeof value !== "string" || !SESSION_STATES.has(value as RuntimeSessionState)) throw new Error(`${label} is not a supported session state`);
  return value as RuntimeSessionState;
}

function runtimeBackend(value: unknown, label: string): RuntimeSessionBackend {
  if (typeof value !== "string" || !RUNTIME_BACKENDS.has(value as RuntimeSessionBackend)) throw new Error(`${label} is not a supported runtime backend`);
  return value as RuntimeSessionBackend;
}

function booleanField(value: unknown, label: string): boolean {
  if (typeof value !== "boolean") throw new Error(`${label} must be boolean`);
  return value;
}

export function defaultSessionCapabilities(backend: RuntimeSessionBackend): SessionCapabilities {
  const live = backend === "transient";
  return {
    pause: live,
    resume: live,
    step: live,
    run_to_time: live,
    reset: live,
    // Persistence is never inferred by the browser. It becomes available only
    // after authoritative session metadata explicitly advertises it.
    persistent_checkpoint_restart: false,
    paused_state_edit: false,
  };
}

export function initialSessionState(backend: RuntimeSessionBackend): RuntimeSessionState {
  return backend === "equilibrium" ? "COMPLETED" : "CREATED";
}

function parseCheckpointProvenance(value: unknown, index: number): SessionCheckpointProvenance {
  const checkpoint = record(value, `session.checkpoints[${index}]`);
  const source = record(checkpoint.source_scenario, `session.checkpoints[${index}].source_scenario`);
  const backend = record(checkpoint.backend, `session.checkpoints[${index}].backend`);
  const integrity = record(checkpoint.integrity, `session.checkpoints[${index}].integrity`);
  const canonicalization = integrity.canonicalization;
  if (canonicalization !== undefined && typeof canonicalization !== "string") {
    throw new Error(`session.checkpoints[${index}].integrity.canonicalization must be a string`);
  }
  return {
    frame_id: nonEmptyString(checkpoint.frame_id, `session.checkpoints[${index}].frame_id`),
    simulation_time_s: finiteNonNegative(checkpoint.simulation_time_s, `session.checkpoints[${index}].simulation_time_s`),
    same_build_only: booleanField(checkpoint.same_build_only, `session.checkpoints[${index}].same_build_only`),
    runtime_checkpoint_version: nonEmptyString(checkpoint.runtime_checkpoint_version, `session.checkpoints[${index}].runtime_checkpoint_version`),
    continuation_format_version: nonEmptyString(checkpoint.continuation_format_version, `session.checkpoints[${index}].continuation_format_version`),
    source_scenario: {
      id: nonEmptyString(source.id, `session.checkpoints[${index}].source_scenario.id`),
      sha256: nonEmptyString(source.sha256, `session.checkpoints[${index}].source_scenario.sha256`),
    },
    backend: {
      ...backend,
      identity: nonEmptyString(backend.identity, `session.checkpoints[${index}].backend.identity`),
      version: nonEmptyString(backend.version, `session.checkpoints[${index}].backend.version`),
    },
    integrity: {
      ...integrity,
      algorithm: nonEmptyString(integrity.algorithm, `session.checkpoints[${index}].integrity.algorithm`),
      continuation_sha256: nonEmptyString(integrity.continuation_sha256, `session.checkpoints[${index}].integrity.continuation_sha256`),
      ...(canonicalization === undefined ? {} : { canonicalization }),
    },
  };
}

export function parseAuthoritativeSessionMetadata(value: unknown): AuthoritativeSessionSnapshot {
  const meta = record(value, "session.json");
  const scenario = record(meta.scenario, "session.scenario");
  const backend = record(meta.backend, "session.backend");
  const capabilities = record(meta.capabilities, "session.capabilities");
  if (typeof meta.session_version !== "string" || !meta.session_version) throw new Error("session_version is required");
  if (typeof scenario.id !== "string" || !scenario.id || typeof scenario.sha256 !== "string" || !scenario.sha256) throw new Error("session scenario id/sha256 are required");
  if (typeof backend.identity !== "string" || !backend.identity || typeof backend.version !== "string" || !backend.version) throw new Error("session backend identity/version are required");

  const checkpointValues = meta.checkpoints === undefined ? [] : meta.checkpoints;
  if (!Array.isArray(checkpointValues)) throw new Error("session.checkpoints must be an array");
  const checkpoints = checkpointValues.map((item, index) => parseCheckpointProvenance(item, index));
  const checkpointCount = meta.checkpoint_count === undefined
    ? checkpoints.length
    : nonNegativeInteger(meta.checkpoint_count, "session.checkpoint_count");
  if (checkpointCount !== checkpoints.length) throw new Error("session checkpoint_count does not match checkpoints");

  return {
    session_version: meta.session_version,
    scenario: { id: scenario.id, sha256: scenario.sha256 },
    backend: backend as AuthoritativeSessionSnapshot["backend"],
    random_seed: nonNegativeInteger(meta.random_seed, "session.random_seed"),
    state: sessionState(meta.state, "session.state"),
    physical_time_s: finiteNonNegative(meta.physical_time_s, "session.physical_time_s"),
    frame_index: nonNegativeInteger(meta.frame_index, "session.frame_index"),
    capabilities: {
      pause: booleanField(capabilities.pause, "capabilities.pause"),
      resume: booleanField(capabilities.resume, "capabilities.resume"),
      step: booleanField(capabilities.step, "capabilities.step"),
      run_to_time: booleanField(capabilities.run_to_time, "capabilities.run_to_time"),
      reset: booleanField(capabilities.reset, "capabilities.reset"),
      persistent_checkpoint_restart: booleanField(capabilities.persistent_checkpoint_restart, "capabilities.persistent_checkpoint_restart"),
      paused_state_edit: booleanField(capabilities.paused_state_edit, "capabilities.paused_state_edit"),
    },
    command_count: nonNegativeInteger(meta.command_count, "session.command_count"),
    checkpoint_count: checkpointCount,
    checkpoints,
  };
}

function stringArray(value: unknown, label: string): readonly string[] {
  if (!Array.isArray(value) || value.some((item) => typeof item !== "string")) throw new Error(`${label} must be an array of strings`);
  return [...value] as string[];
}

export function parseSessionCommandHistory(value: unknown): readonly SessionCommandHistoryEntry[] {
  if (!Array.isArray(value)) throw new Error("commands.json must contain an array");
  return value.map((item, index) => {
    const entry = record(item, `commands[${index}]`);
    if (!Number.isInteger(entry.sequence) || (entry.sequence as number) < 1) throw new Error(`commands[${index}].sequence must be a positive integer`);
    if (typeof entry.command !== "string" || !entry.command) throw new Error(`commands[${index}].command is required`);
    if (entry.result !== "ACCEPTED" && entry.result !== "REJECTED" && entry.result !== "FAILED") throw new Error(`commands[${index}].result is invalid`);
    const parsed: SessionCommandHistoryEntry = {
      sequence: entry.sequence as number,
      command: entry.command,
      requested: { ...record(entry.requested, `commands[${index}].requested`) },
      result: entry.result,
      state_before: sessionState(entry.state_before, `commands[${index}].state_before`),
      state_after: sessionState(entry.state_after, `commands[${index}].state_after`),
      physical_time_before_s: finiteNonNegative(entry.physical_time_before_s, `commands[${index}].physical_time_before_s`),
      physical_time_after_s: finiteNonNegative(entry.physical_time_after_s, `commands[${index}].physical_time_after_s`),
      overshoot_s: finiteNonNegative(entry.overshoot_s, `commands[${index}].overshoot_s`),
      emitted_frame_ids: stringArray(entry.emitted_frame_ids, `commands[${index}].emitted_frame_ids`),
      emitted_checkpoint_ids: stringArray(entry.emitted_checkpoint_ids, `commands[${index}].emitted_checkpoint_ids`),
    };
    if (typeof entry.error === "string") parsed.error = entry.error;
    return parsed;
  }).sort((a, b) => a.sequence - b.sequence);
}

export function commandFromHistory(entry: SessionCommandHistoryEntry): SessionCommand | null {
  if (entry.result !== "ACCEPTED") return null;
  if (entry.command === "PAUSE" || entry.command === "RESUME" || entry.command === "STEP" || entry.command === "RESET") return { command: entry.command };
  if (entry.command === "RUN_TO_TIME") {
    const target = entry.requested.target_time_s;
    if (typeof target === "number" && Number.isFinite(target) && target >= 0) return { command: "RUN_TO_TIME", target_time_s: target };
  }
  return null;
}

export function createSessionIntent(
  backend: RuntimeSessionBackend,
  authoritative: AuthoritativeSessionSnapshot | null = null,
  baseCommands: readonly SessionCommand[] = [],
): SessionIntentState {
  return {
    backend,
    authoritative,
    baseCommands: baseCommands.map((command) => ({ ...command })),
    stagedCommands: [],
    stagedState: authoritative?.state ?? initialSessionState(backend),
  };
}

export function sessionCapabilities(intent: SessionIntentState): SessionCapabilities {
  return intent.authoritative?.capabilities ?? defaultSessionCapabilities(intent.backend);
}

function capabilityKey(command: SessionCommandName): keyof SessionCapabilities {
  if (command === "RUN_TO_TIME") return "run_to_time";
  return command.toLowerCase() as "pause" | "resume" | "step" | "reset";
}

export function commandAvailability(intent: SessionIntentState, command: SessionCommandName, targetTimeS?: number): CommandAvailability {
  const capabilities = sessionCapabilities(intent);
  if (!capabilities[capabilityKey(command)]) return { enabled: false, reason: `${command} is unavailable for the selected authoritative backend.` };
  if (intent.stagedState === "FAILED") return { enabled: false, reason: "The authoritative session is FAILED; import a valid result or reset from a fresh source scenario." };
  if (intent.stagedState === "COMPLETED" && command !== "RESET") return { enabled: false, reason: "The authoritative session is COMPLETED and has no live continuation handle." };
  if (command === "STEP" && intent.stagedState !== "PAUSED") return { enabled: false, reason: "STEP requires a PAUSED solver session." };
  if (command === "RUN_TO_TIME") {
    if (intent.stagedState !== "RUNNING") return { enabled: false, reason: "RUN_TO_TIME requires a RUNNING solver session." };
    if (typeof targetTimeS !== "number" || !Number.isFinite(targetTimeS) || targetTimeS < 0) return { enabled: false, reason: "Target physical time must be finite and non-negative." };
    const authoritativeTime = intent.authoritative?.physical_time_s ?? 0;
    if (targetTimeS + 1e-15 < authoritativeTime) return { enabled: false, reason: `Target physical time cannot be before authoritative time ${authoritativeTime}.` };
  }
  return { enabled: true, reason: "Command can be staged for external authoritative execution." };
}

function nextState(current: RuntimeSessionState, command: SessionCommand): RuntimeSessionState {
  if (command.command === "PAUSE") return "PAUSED";
  if (command.command === "RESUME") return "RUNNING";
  if (command.command === "STEP" || command.command === "RUN_TO_TIME") return "PAUSED";
  if (command.command === "RESET") return "CREATED";
  return current;
}

export function stageSessionCommand(intent: SessionIntentState, command: SessionCommand): SessionIntentState {
  const target = command.command === "RUN_TO_TIME" ? command.target_time_s : undefined;
  const availability = commandAvailability(intent, command.command, target);
  if (!availability.enabled) throw new Error(availability.reason);
  return {
    ...intent,
    stagedCommands: [...intent.stagedCommands, { ...command }],
    stagedState: nextState(intent.stagedState, command),
  };
}

export function clearStagedSessionCommands(intent: SessionIntentState): SessionIntentState {
  return {
    ...intent,
    stagedCommands: [],
    stagedState: intent.authoritative?.state ?? initialSessionState(intent.backend),
  };
}

export function fullSessionCommandSequence(intent: SessionIntentState): readonly SessionCommand[] {
  return [...intent.baseCommands, ...intent.stagedCommands].map((command) => ({ ...command }));
}

export function serializeSessionCommands(commands: readonly SessionCommand[]): string {
  return `${JSON.stringify({ commands: commands.map((command) => ({ ...command })) }, null, 2)}\n`;
}

function shellQuote(value: string): string {
  return `'${value.replaceAll("'", "'\\''")}'`;
}

export function buildSessionInvocation(
  backend: RuntimeSessionBackend,
  options: { scenarioFile?: string; commandsFile?: string; outputDirectory?: string } = {},
): string {
  const scenarioFile = options.scenarioFile ?? "scenario.json";
  const commandsFile = options.commandsFile ?? "session.commands.json";
  const outputDirectory = options.outputDirectory ?? "session-output";
  return [
    "python3 bubblelab/runtime/tools/run_session.py",
    shellQuote(scenarioFile),
    "--commands", shellQuote(commandsFile),
    "--output", shellQuote(outputDirectory),
    "--backend", backend,
  ].join(" ");
}

function bundleRoot(files: readonly File[], replayFile: File): string {
  return replayFile.webkitRelativePath ? replayFile.webkitRelativePath.slice(0, -"replay.json".length) : "";
}

function filesByRelativePath(files: readonly File[], root: string): Map<string, File> {
  const result = new Map<string, File>();
  for (const file of files) {
    const relative = file.webkitRelativePath && file.webkitRelativePath.startsWith(root)
      ? file.webkitRelativePath.slice(root.length)
      : file.name;
    result.set(relative, file);
  }
  return result;
}

export async function loadAuthoritativeSessionBundleFromFiles(files: FileList): Promise<AuthoritativeSessionBundle> {
  const all = [...files];
  const replayFile = all.find((file) => file.name === "replay.json");
  if (!replayFile) throw new Error("Selected folder does not contain replay.json");
  const root = bundleRoot(all, replayFile);
  const byRelative = filesByRelativePath(all, root);
  const readJson = async (path: string): Promise<unknown> => {
    const file = byRelative.get(path);
    if (!file) throw new Error(`Selected session bundle is missing ${path}`);
    return JSON.parse(await file.text()) as unknown;
  };
  const replay = parseReplayBundleIndex(await readJson("replay.json"));
  const runSettings = record(replay.run_settings, "replay.run_settings");
  if (runSettings.session_control !== true) throw new Error("Replay bundle is not an authoritative session-control bundle");
  const backend = runtimeBackend(runSettings.backend, "replay.run_settings.backend");
  const sessionControl = record(replay.session_control, "replay.session_control");
  const metadataPath = typeof sessionControl.metadata === "string" ? sessionControl.metadata : "session.json";
  const commandLogPath = typeof sessionControl.command_log === "string" ? sessionControl.command_log : "commands.json";
  const snapshot = parseAuthoritativeSessionMetadata(await readJson(metadataPath));
  const commandHistory = parseSessionCommandHistory(await readJson(commandLogPath));
  if (snapshot.scenario.id !== replay.scenario.id || snapshot.scenario.sha256 !== replay.scenario.sha256) throw new Error("Session metadata scenario does not match replay.json");
  if (snapshot.backend.identity !== replay.backend.identity || snapshot.backend.version !== replay.backend.version) throw new Error("Session metadata backend does not match replay.json");
  if (snapshot.random_seed !== replay.random_seed) throw new Error("Session metadata random seed does not match replay.json");
  if (snapshot.command_count !== commandHistory.length) throw new Error("Session command_count does not match commands.json");
  if (snapshot.checkpoint_count !== replay.checkpoints.length) throw new Error("Session checkpoint_count does not match replay.json");
  if (sessionControl.checkpoint_count !== undefined && nonNegativeInteger(sessionControl.checkpoint_count, "replay.session_control.checkpoint_count") !== snapshot.checkpoint_count) throw new Error("Session checkpoint count does not match replay.json");
  if (sessionControl.state !== undefined && sessionState(sessionControl.state, "replay.session_control.state") !== snapshot.state) throw new Error("Session state does not match replay.json");
  if (sessionControl.physical_time_s !== undefined && finiteNonNegative(sessionControl.physical_time_s, "replay.session_control.physical_time_s") !== snapshot.physical_time_s) throw new Error("Session physical time does not match replay.json");
  if (sessionControl.frame_index !== undefined && nonNegativeInteger(sessionControl.frame_index, "replay.session_control.frame_index") !== snapshot.frame_index) throw new Error("Session frame index does not match replay.json");
  const replayableCommands: SessionCommand[] = [];
  for (const entry of commandHistory) {
    const command = commandFromHistory(entry);
    if (command) {
      replayableCommands.push(command);
      continue;
    }
    if (entry.result !== "ACCEPTED" || PERSISTENCE_HISTORY_COMMANDS.has(entry.command)) continue;
    throw new Error(`Authoritative command #${entry.sequence} cannot be deterministically replayed by this UI handoff`);
  }
  return { backend, replay, snapshot, commandHistory, replayableCommands };
}

export function commandResultSummary(entry: SessionCommandHistoryEntry): string {
  const base = `#${entry.sequence} ${entry.command} · ${entry.result} · ${entry.state_before} → ${entry.state_after} · ${entry.physical_time_before_s} s → ${entry.physical_time_after_s} s`;
  return entry.error ? `${base} · ${entry.error}` : base;
}
