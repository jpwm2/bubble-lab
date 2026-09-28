import { parseContractFrame } from "./contract.js";
import {
  parseAuthoritativeSessionMetadata,
  parseSessionCommandHistory,
  type AuthoritativeSessionSnapshot,
  type RuntimeSessionBackend,
  type SessionCommand,
  type SessionCommandHistoryEntry,
} from "./sessionControl.js";
import type { ContractFrame, ContractScenario } from "./types.js";

export interface LiveSessionEnvelope {
  transportVersion: "1.0.0";
  sessionId: string;
  snapshot: AuthoritativeSessionSnapshot;
  latestFrame: ContractFrame;
  commandHistory: readonly SessionCommandHistoryEntry[];
  commandResult?: SessionCommandHistoryEntry;
  checkpoint?: Record<string, unknown>;
  checkpointProvenance?: Record<string, unknown>;
}

export interface LiveSessionBundleDocuments {
  replay: Record<string, unknown>;
  session: AuthoritativeSessionSnapshot;
  commands: readonly SessionCommandHistoryEntry[];
  framePath: string;
  frame: ContractFrame;
}

type FetchLike = (input: RequestInfo | URL, init?: RequestInit) => Promise<Response>;

function record(value: unknown, label: string): Record<string, unknown> {
  if (typeof value !== "object" || value === null || Array.isArray(value)) throw new Error(`${label} must be an object`);
  return value as Record<string, unknown>;
}

function nonEmptyString(value: unknown, label: string): string {
  if (typeof value !== "string" || !value.trim()) throw new Error(`${label} is required`);
  return value;
}

function parseOptionalRecord(value: unknown, label: string): Record<string, unknown> | undefined {
  if (value === undefined) return undefined;
  return { ...record(value, label) };
}

export function normalizeLiveSessionBaseUrl(value: string): string {
  let url: URL;
  try {
    url = new URL(value);
  } catch {
    throw new Error("Live session URL must be an absolute HTTP URL.");
  }
  if (url.protocol !== "http:") throw new Error("Live session transport requires plain HTTP on loopback.");
  if (url.hostname !== "127.0.0.1") throw new Error("Live session transport may connect only to 127.0.0.1.");
  if (url.username || url.password || url.search || url.hash) throw new Error("Live session URL must not contain credentials, query parameters, or fragments.");
  if (url.pathname !== "/" && url.pathname !== "") throw new Error("Live session URL must point to the transport origin, not an arbitrary path.");
  return url.origin;
}

export function parseLiveSessionEnvelope(value: unknown): LiveSessionEnvelope {
  const payload = record(value, "live session response");
  if (payload.transport_version !== "1.0.0") throw new Error(`Unsupported live transport version: ${String(payload.transport_version)}`);
  const sessionId = nonEmptyString(payload.session_id, "session_id");
  const snapshot = parseAuthoritativeSessionMetadata(payload.snapshot);
  const latestFrame = parseContractFrame(payload.latest_frame);
  if (latestFrame.kind !== "FRAME") throw new Error("latest_frame must be a canonical FRAME");
  if (latestFrame.simulation_time_s !== snapshot.physical_time_s) throw new Error("latest FRAME physical time does not match authoritative session state");
  const commandHistory = parseSessionCommandHistory(payload.command_history ?? []);
  if (snapshot.command_count !== commandHistory.length) throw new Error("authoritative command_count does not match command_history");
  let commandResult: SessionCommandHistoryEntry | undefined;
  if (payload.command_result !== undefined) {
    commandResult = parseSessionCommandHistory([payload.command_result])[0];
    if (!commandResult) throw new Error("command_result is invalid");
    const historyEntry = commandHistory.find((entry) => entry.sequence === commandResult!.sequence);
    if (!historyEntry || JSON.stringify(historyEntry) !== JSON.stringify(commandResult)) throw new Error("command_result does not match authoritative command_history");
  }
  const checkpoint = parseOptionalRecord(payload.checkpoint, "checkpoint");
  const checkpointProvenance = parseOptionalRecord(payload.checkpoint_provenance, "checkpoint_provenance");
  return {
    transportVersion: "1.0.0",
    sessionId,
    snapshot,
    latestFrame,
    commandHistory,
    ...(commandResult ? { commandResult } : {}),
    ...(checkpoint ? { checkpoint } : {}),
    ...(checkpointProvenance ? { checkpointProvenance } : {}),
  };
}

export class LiveSessionTransportError extends Error {
  readonly status: number;
  readonly code: string;
  readonly envelope?: LiveSessionEnvelope;

  constructor(message: string, options: { status: number; code: string; envelope?: LiveSessionEnvelope }) {
    super(message);
    this.name = "LiveSessionTransportError";
    this.status = options.status;
    this.code = options.code;
    if (options.envelope) this.envelope = options.envelope;
  }
}

export class LiveSessionClient {
  readonly baseUrl: string;
  private readonly fetchImpl: FetchLike;

  constructor(baseUrl = "http://127.0.0.1:8765", fetchImpl: FetchLike = fetch) {
    this.baseUrl = normalizeLiveSessionBaseUrl(baseUrl);
    this.fetchImpl = fetchImpl;
  }

  private async request(path: string, init: RequestInit = {}): Promise<unknown> {
    const response = await this.fetchImpl(`${this.baseUrl}${path}`, {
      ...init,
      headers: { "Content-Type": "application/json", ...(init.headers ?? {}) },
    });
    let body: unknown;
    try {
      body = await response.json();
    } catch {
      throw new LiveSessionTransportError("Live session server returned invalid JSON.", {
        status: response.status,
        code: "invalid_server_json",
      });
    }
    if (!response.ok) {
      const root = record(body, "transport error response");
      const error = record(root.error, "transport error");
      let envelope: LiveSessionEnvelope | undefined;
      if (root.session !== undefined) {
        try { envelope = parseLiveSessionEnvelope(root.session); } catch { envelope = undefined; }
      }
      throw new LiveSessionTransportError(
        typeof error.message === "string" ? error.message : `Live session request failed with HTTP ${response.status}.`,
        {
          status: response.status,
          code: typeof error.code === "string" ? error.code : "transport_error",
          ...(envelope ? { envelope } : {}),
        },
      );
    }
    return body;
  }

  async health(): Promise<{ ok: true; transportVersion: string; bindScope: string }> {
    const body = record(await this.request("/v1/health"), "health response");
    if (body.ok !== true) throw new Error("Live session server health check did not report ok=true.");
    return {
      ok: true,
      transportVersion: nonEmptyString(body.transport_version, "transport_version"),
      bindScope: nonEmptyString(body.bind_scope, "bind_scope"),
    };
  }

  async createSession(scenario: ContractScenario, backend: RuntimeSessionBackend): Promise<LiveSessionEnvelope> {
    return parseLiveSessionEnvelope(await this.request("/v1/sessions", {
      method: "POST",
      body: JSON.stringify({ scenario, backend }),
    }));
  }

  async getSession(sessionId: string): Promise<LiveSessionEnvelope> {
    return parseLiveSessionEnvelope(await this.request(`/v1/sessions/${encodeURIComponent(sessionId)}`));
  }

  async command(sessionId: string, command: SessionCommand): Promise<LiveSessionEnvelope> {
    return parseLiveSessionEnvelope(await this.request(`/v1/sessions/${encodeURIComponent(sessionId)}/commands`, {
      method: "POST",
      body: JSON.stringify(command),
    }));
  }

  async saveCheckpoint(sessionId: string): Promise<LiveSessionEnvelope> {
    return parseLiveSessionEnvelope(await this.request(`/v1/sessions/${encodeURIComponent(sessionId)}/checkpoints`, {
      method: "POST",
      body: "{}",
    }));
  }

  async getCheckpoint(sessionId: string, frameId = "latest"): Promise<LiveSessionEnvelope> {
    return parseLiveSessionEnvelope(await this.request(`/v1/sessions/${encodeURIComponent(sessionId)}/checkpoints/${encodeURIComponent(frameId)}`));
  }

  async closeSession(sessionId: string): Promise<void> {
    await this.request(`/v1/sessions/${encodeURIComponent(sessionId)}`, { method: "DELETE" });
  }
}

export function buildLiveSessionBundleDocuments(
  envelope: LiveSessionEnvelope,
  backend: RuntimeSessionBackend,
): LiveSessionBundleDocuments {
  const framePath = "frames/000000.json";
  const frameManifest = record(envelope.latestFrame.manifest, "latest FRAME manifest");
  const fidelityTier = nonEmptyString(frameManifest.fidelity_tier, "latest FRAME fidelity_tier");
  const featureDisclosures = record(frameManifest.feature_disclosures, "latest FRAME feature_disclosures");
  const checkpoints = envelope.snapshot.checkpoints.map((checkpoint, index) => ({
    frame_id: checkpoint.frame_id,
    path: `checkpoints/${index.toString().padStart(6, "0")}.json`,
    simulation_time_s: checkpoint.simulation_time_s,
    same_build_only: checkpoint.same_build_only,
  }));
  return {
    replay: {
      bundle_version: "1.0.0",
      contract_version: "1.0.0",
      scenario: { ...envelope.snapshot.scenario },
      backend: { ...envelope.snapshot.backend },
      random_seed: envelope.snapshot.random_seed,
      run_settings: { backend, requested_frames: null, output_cadence_s: null, session_control: true, live_transport: true },
      frames: [{ frame_id: envelope.latestFrame.frame_id, path: framePath, simulation_time_s: envelope.latestFrame.simulation_time_s }],
      checkpoints,
      provenance: { producer: "bubblelab.runtime.server", source_scenario: envelope.snapshot.scenario.id },
      fidelity: { requested: fidelityTier, produced: fidelityTier, feature_disclosures: { ...featureDisclosures } },
      session_control: {
        version: envelope.snapshot.session_version,
        state: envelope.snapshot.state,
        physical_time_s: envelope.snapshot.physical_time_s,
        frame_index: envelope.snapshot.frame_index,
        checkpoint_count: envelope.snapshot.checkpoint_count,
        command_log: "commands.json",
        metadata: "session.json",
        transport: "loopback-http-json",
      },
    },
    session: envelope.snapshot,
    commands: envelope.commandHistory,
    framePath,
    frame: envelope.latestFrame,
  };
}

function syntheticFile(content: unknown, name: string, relativePath: string): File {
  const file = new File([`${JSON.stringify(content)}\n`], name, { type: "application/json" });
  Object.defineProperty(file, "webkitRelativePath", { configurable: true, value: relativePath });
  return file;
}

export function liveSessionBundleFileList(
  envelope: LiveSessionEnvelope,
  backend: RuntimeSessionBackend,
): FileList {
  if (typeof DataTransfer === "undefined") throw new Error("DataTransfer is unavailable in this browser.");
  const docs = buildLiveSessionBundleDocuments(envelope, backend);
  const transfer = new DataTransfer();
  const root = "bubblelab-live/";
  transfer.items.add(syntheticFile(docs.replay, "replay.json", `${root}replay.json`));
  transfer.items.add(syntheticFile(docs.session, "session.json", `${root}session.json`));
  transfer.items.add(syntheticFile(docs.commands, "commands.json", `${root}commands.json`));
  transfer.items.add(syntheticFile(docs.frame, docs.framePath, `${root}${docs.framePath}`));
  return transfer.files;
}

export function publishLiveSessionEnvelope(
  input: HTMLInputElement,
  envelope: LiveSessionEnvelope,
  backend: RuntimeSessionBackend,
): void {
  input.files = liveSessionBundleFileList(envelope, backend);
  input.dispatchEvent(new Event("change"));
}
