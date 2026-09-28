import { serializeScenarioDeterministic } from "./lab.js";
import {
  LiveSessionClient,
  LiveSessionTransportError,
  publishLiveSessionEnvelope,
  type LiveSessionEnvelope,
} from "./liveSession.js";
import type { RuntimeSessionBackend, SessionCommand } from "./sessionControl.js";
import { subscribeViewerState } from "./store.js";
import type { ContractScenario, ViewerState } from "./types.js";

const root = document.querySelector<HTMLElement>("#live-session-panel");
const runtimeBundleInput = document.querySelector<HTMLInputElement>("#runtime-bundle-input");

type LiveEditOperation =
  | "ADD_BUBBLE"
  | "DELETE_BUBBLE"
  | "MOVE_BUBBLE"
  | "RESIZE_BUBBLE"
  | "SET_BUBBLE_VELOCITY";

type LiveEditCommand =
  | {
      command: "ADD_BUBBLE";
      bubble_id: string;
      centroid_m: [number, number, number];
      equivalent_radius_m: number;
      velocity_m_s: [number, number, number];
      surface_tension_n_m: number;
    }
  | { command: "DELETE_BUBBLE"; bubble_id: string }
  | { command: "MOVE_BUBBLE"; bubble_id: string; centroid_m: [number, number, number] }
  | { command: "RESIZE_BUBBLE"; bubble_id: string; equivalent_radius_m: number }
  | { command: "SET_BUBBLE_VELOCITY"; bubble_id: string; velocity_m_s: [number, number, number] };

interface EditDraft {
  operation: LiveEditOperation;
  bubbleId: string;
  centroid: [number, number, number];
  radius: number;
  velocity: [number, number, number];
  tension: number;
}

let viewerState: ViewerState | null = null;
let currentScenarioFingerprint = "";
let activeScenarioFingerprint = "";
let baseUrl = "http://127.0.0.1:8765";
let activeClient: LiveSessionClient | null = null;
let envelope: LiveSessionEnvelope | null = null;
let busy = false;
let panelMessage = "Start the local Python transport, then create a live authoritative session from the editable SCENARIO.";
let editDraft: EditDraft = {
  operation: "MOVE_BUBBLE",
  bubbleId: "bubble-1",
  centroid: [0, 0, 0],
  radius: 0.01,
  velocity: [0, 0, 0],
  tension: 0.05,
};

const escapeHtml = (value: string): string => value.replace(/[&<>"']/g, (character) => ({
  "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#039;",
}[character] ?? character));

function record(value: unknown): Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value) ? value as Record<string, unknown> : {};
}

function selectedBackend(scenario: ContractScenario): RuntimeSessionBackend {
  const backend = record(scenario.requested_solver).backend;
  return backend === "equilibrium" || backend === "thinfilm" || backend === "thinfilm-events" ? backend : "transient";
}

function isStale(): boolean {
  return Boolean(envelope && activeScenarioFingerprint !== currentScenarioFingerprint);
}

function disabled(disable: boolean, reason: string): string {
  return disable ? ` disabled aria-disabled="true" title="${escapeHtml(reason)}"` : ` title="${escapeHtml(reason)}"`;
}

function numeric3(value: unknown, fallback: [number, number, number]): [number, number, number] {
  if (!Array.isArray(value) || value.length !== 3) return fallback;
  const parsed: [number, number, number] = [Number(value[0]), Number(value[1]), Number(value[2])];
  return parsed.every(Number.isFinite) ? parsed : fallback;
}

function authoritativeBubbles(): readonly Record<string, unknown>[] {
  const frame = envelope?.latestFrame as unknown;
  const raw = record(frame).bubbles;
  return Array.isArray(raw) ? raw.map(record) : [];
}

function hydrateEditDraftFromBubble(bubbleId: string): void {
  const found = authoritativeBubbles().find((item) => item.id === bubbleId);
  if (!found) return;
  const film = record(found.film_material);
  editDraft = {
    ...editDraft,
    bubbleId,
    centroid: numeric3(found.centroid_m, editDraft.centroid),
    radius: typeof found.equivalent_radius_m === "number" ? found.equivalent_radius_m : editDraft.radius,
    velocity: numeric3(found.velocity_m_s, editDraft.velocity),
    tension: typeof film.effective_sheet_tension_n_m === "number"
      ? film.effective_sheet_tension_n_m
      : editDraft.tension,
  };
}

function syncEditDraftToEnvelope(): void {
  const ids = authoritativeBubbles()
    .map((item) => typeof item.id === "string" ? item.id : "")
    .filter(Boolean);
  if (editDraft.operation === "ADD_BUBBLE") return;
  if (!ids.includes(editDraft.bubbleId) && ids[0]) editDraft.bubbleId = ids[0];
  if (editDraft.bubbleId) hydrateEditDraftFromBubble(editDraft.bubbleId);
}

function commandRows(): string {
  if (!envelope?.commandHistory.length) return '<p class="muted">No authoritative live commands have executed yet.</p>';
  return envelope.commandHistory.slice(-8).map((entry) => {
    const marker = entry.result === "ACCEPTED" ? "✓" : entry.result === "REJECTED" ? "⚠" : "✕";
    const error = entry.error ? ` · ${entry.error}` : "";
    return `<div class="kv"><span>${marker} #${entry.sequence} ${escapeHtml(entry.command)}</span><strong>${escapeHtml(`${entry.result} · ${entry.state_before} → ${entry.state_after} · ${entry.physical_time_before_s} s → ${entry.physical_time_after_s} s${error}`)}</strong></div>`;
  }).join("");
}

function render(): void {
  if (!root || !viewerState) return;
  const backend = selectedBackend(viewerState.editorScenario);
  const snapshot = envelope?.snapshot ?? null;
  const stale = isStale();
  const targetInput = document.querySelector<HTMLInputElement>("#live-target-time");
  const existingTarget = Number(targetInput?.value);
  const target = Number.isFinite(existingTarget)
    ? existingTarget
    : Math.max(0.001, (snapshot?.physical_time_s ?? 0) + 0.001);
  const liveBackend = backend === "transient" || backend === "equilibrium";
  const unusable = busy || stale || !envelope;
  const state = snapshot?.state;
  const canPause = !unusable && Boolean(snapshot?.capabilities.pause) && state !== "FAILED" && state !== "COMPLETED";
  const canResume = !unusable && Boolean(snapshot?.capabilities.resume) && state !== "FAILED" && state !== "COMPLETED";
  const canStep = !unusable && Boolean(snapshot?.capabilities.step) && state === "PAUSED";
  const canRun = !unusable && Boolean(snapshot?.capabilities.run_to_time) && state === "RUNNING" && Number.isFinite(target) && target + 1e-15 >= (snapshot?.physical_time_s ?? 0);
  const canReset = !unusable && Boolean(snapshot?.capabilities.reset);
  const canCheckpoint = !unusable && Boolean(snapshot?.capabilities.persistent_checkpoint_restart) && state !== "FAILED" && state !== "COMPLETED";
  const canEdit = !unusable && Boolean(snapshot?.capabilities.paused_state_edit) && state === "PAUSED";
  const lastCheckpoint = snapshot?.checkpoints.at(-1);
  const bubbleOptions = authoritativeBubbles()
    .map((item) => typeof item.id === "string" ? `<option value="${escapeHtml(item.id)}"></option>` : "")
    .join("");
  const editReason = canEdit
    ? "Apply the edit to the Python-owned solver state without advancing physical time."
    : "Live editing requires a non-stale PAUSED transient session advertising paused_state_edit.";

  root.innerHTML = `
    <details class="debug-controls" open>
      <summary>Direct loopback solver transport</summary>
      <div class="control-grid">
        <label>Local transport URL<input id="live-session-url" type="url" value="${escapeHtml(baseUrl)}" spellcheck="false" /></label>
        <label>Selected backend<input type="text" readonly value="${escapeHtml(backend)}" /></label>
      </div>
      <div class="toolbar">
        <button id="live-health" type="button"${disabled(busy, "Check the loopback server without creating a solver session.")}>Check server</button>
        <button id="live-create" type="button"${disabled(busy || !liveBackend, liveBackend ? "Create a RuntimeSession from the current canonical SCENARIO." : "This backend has no accepted live continuation handle.")}>Start live session</button>
        <button id="live-refresh" type="button"${disabled(unusable, "Refresh authoritative state and latest FRAME from the server.")}>Refresh</button>
        <button id="live-close" type="button"${disabled(busy || !envelope, "Discard the server-owned live session.")}>Close live session</button>
      </div>
      <p class="muted">Server command: <code>python3 -m bubblelab.runtime.server --port 8765 --allow-origin http://127.0.0.1:&lt;viewer-port&gt;</code>. Serve this viewer from that explicit HTTP origin; <code>file://</code> / Origin <code>null</code> is intentionally rejected. The browser connects only to 127.0.0.1 and never integrates geometry or advances physical time locally.</p>
      ${stale ? '<p class="muted">The editable SCENARIO changed after this live session was created. Live commands are disabled until a new session is started.</p>' : ""}
      <div class="kv"><span>Session</span><strong>${escapeHtml(envelope?.sessionId ?? "Not created")}</strong></div>
      <div class="kv"><span>Authoritative state</span><strong>${escapeHtml(snapshot?.state ?? "Unavailable")}</strong></div>
      <div class="kv"><span>Authoritative physical time</span><strong>${snapshot ? `${snapshot.physical_time_s} s` : "Unavailable"}</strong></div>
      <div class="kv"><span>Authoritative frame index</span><strong>${snapshot ? String(snapshot.frame_index) : "Unavailable"}</strong></div>
      <div class="kv"><span>Latest canonical FRAME</span><strong>${escapeHtml(envelope?.latestFrame.frame_id ?? "Unavailable")}</strong></div>
      <div class="kv"><span>Last checkpoint</span><strong>${escapeHtml(lastCheckpoint ? `${lastCheckpoint.frame_id} @ ${lastCheckpoint.simulation_time_s} s · same-build only` : "None")}</strong></div>
      <div class="toolbar" role="toolbar" aria-label="Direct authoritative solver commands">
        <button id="live-pause" type="button"${disabled(!canPause, "PAUSE is executed by the Python RuntimeSession.")}>Pause solver</button>
        <button id="live-resume" type="button"${disabled(!canResume, "RESUME is executed by the Python RuntimeSession.")}>Resume solver</button>
        <button id="live-step" type="button"${disabled(!canStep, "STEP requires a PAUSED authoritative session and advances exactly one backend step.")}>Single solver step</button>
        <button id="live-reset" type="button"${disabled(!canReset, "RESET asks the authoritative backend to reproduce its initial state.")}>Reset solver</button>
        <button id="live-checkpoint" type="button"${disabled(!canCheckpoint, "SAVE_CHECKPOINT is generated and stored by the local server; the browser cannot choose filesystem paths.")}>Save checkpoint</button>
      </div>
      <div class="control-grid">
        <label>Physical target time (s)<input id="live-target-time" type="number" min="0" step="any" value="${target}" /></label>
        <label>Transport authority<input type="text" readonly value="Python RuntimeSession only" /></label>
      </div>
      <div class="toolbar"><button id="live-run-to-time" type="button"${disabled(!canRun, "RUN_TO_TIME requires a RUNNING authoritative session and a target not before backend time.")}>Compute to physical time</button></div>

      <h3>Paused authoritative bubble editing</h3>
      <p class="muted">Edits are sent as backend commands. They create a new canonical FRAME at the same physical time; the following STEP continues from that edited solver state.</p>
      <div class="control-grid">
        <label>Operation
          <select id="live-edit-operation">
            ${(["ADD_BUBBLE", "DELETE_BUBBLE", "MOVE_BUBBLE", "RESIZE_BUBBLE", "SET_BUBBLE_VELOCITY"] as LiveEditOperation[])
              .map((operation) => `<option value="${operation}"${operation === editDraft.operation ? " selected" : ""}>${operation}</option>`).join("")}
          </select>
        </label>
        <label>Bubble ID<input id="live-edit-id" list="live-edit-bubble-ids" value="${escapeHtml(editDraft.bubbleId)}" spellcheck="false" /><datalist id="live-edit-bubble-ids">${bubbleOptions}</datalist></label>
      </div>
      <div class="control-grid">
        <label>Centroid X (m)<input id="live-edit-x" type="number" step="any" value="${editDraft.centroid[0]}" /></label>
        <label>Centroid Y (m)<input id="live-edit-y" type="number" step="any" value="${editDraft.centroid[1]}" /></label>
        <label>Centroid Z (m)<input id="live-edit-z" type="number" step="any" value="${editDraft.centroid[2]}" /></label>
        <label>Equivalent radius (m)<input id="live-edit-radius" type="number" min="0" step="any" value="${editDraft.radius}" /></label>
      </div>
      <div class="control-grid">
        <label>Velocity X (m/s)<input id="live-edit-vx" type="number" step="any" value="${editDraft.velocity[0]}" /></label>
        <label>Velocity Y (m/s)<input id="live-edit-vy" type="number" step="any" value="${editDraft.velocity[1]}" /></label>
        <label>Velocity Z (m/s)<input id="live-edit-vz" type="number" step="any" value="${editDraft.velocity[2]}" /></label>
        <label>Sheet tension (N/m)<input id="live-edit-tension" type="number" min="0" step="any" value="${editDraft.tension}" /></label>
      </div>
      <div class="toolbar">
        <button id="live-apply-edit" type="button"${disabled(!canEdit, editReason)}>Apply backend edit</button>
      </div>

      <h3>Authoritative live command history</h3>
      ${commandRows()}
      <p class="muted">Each successful response is converted only into an in-memory Runtime bundle and handed to the existing canonical FRAME importer. Replay controls still navigate produced frames; they do not control this live session.</p>
      <p id="live-session-message" class="muted" aria-live="polite">${escapeHtml(panelMessage)}</p>
    </details>`;
  wireControls();
}

function applyEnvelope(next: LiveSessionEnvelope, backend: RuntimeSessionBackend): void {
  envelope = next;
  syncEditDraftToEnvelope();
  if (runtimeBundleInput) publishLiveSessionEnvelope(runtimeBundleInput, next, backend);
}

async function runAction(action: () => Promise<LiveSessionEnvelope>, success: string): Promise<void> {
  if (!viewerState) return;
  const backend = selectedBackend(viewerState.editorScenario);
  busy = true;
  render();
  try {
    const next = await action();
    applyEnvelope(next, backend);
    panelMessage = success;
  } catch (error) {
    if (error instanceof LiveSessionTransportError && error.envelope) applyEnvelope(error.envelope, backend);
    panelMessage = error instanceof Error ? `${error.name}: ${error.message}` : String(error);
  } finally {
    busy = false;
    render();
  }
}

async function execute(command: SessionCommand): Promise<void> {
  if (!activeClient || !envelope) return;
  await runAction(
    () => activeClient!.command(envelope!.sessionId, command),
    `${command.command} accepted by the authoritative RuntimeSession. Canonical FRAME/state were refreshed from the backend response.`,
  );
}

function buildEditCommand(): LiveEditCommand {
  const id = editDraft.bubbleId.trim();
  if (!id) throw new Error("Bubble ID is required.");
  const finite = (value: number, label: string): number => {
    if (!Number.isFinite(value)) throw new Error(`${label} must be finite.`);
    return value;
  };
  const centroid: [number, number, number] = editDraft.centroid.map((value, index) => finite(value, `Centroid ${"XYZ"[index]}`)) as [number, number, number];
  const velocity: [number, number, number] = editDraft.velocity.map((value, index) => finite(value, `Velocity ${"XYZ"[index]}`)) as [number, number, number];
  if (editDraft.operation === "ADD_BUBBLE") {
    const radius = finite(editDraft.radius, "Equivalent radius");
    const tension = finite(editDraft.tension, "Sheet tension");
    if (radius <= 0) throw new Error("Equivalent radius must be positive.");
    if (tension < 0) throw new Error("Sheet tension must be non-negative.");
    return {
      command: "ADD_BUBBLE",
      bubble_id: id,
      centroid_m: centroid,
      equivalent_radius_m: radius,
      velocity_m_s: velocity,
      surface_tension_n_m: tension,
    };
  }
  if (editDraft.operation === "DELETE_BUBBLE") return { command: "DELETE_BUBBLE", bubble_id: id };
  if (editDraft.operation === "MOVE_BUBBLE") return { command: "MOVE_BUBBLE", bubble_id: id, centroid_m: centroid };
  if (editDraft.operation === "RESIZE_BUBBLE") {
    const radius = finite(editDraft.radius, "Equivalent radius");
    if (radius <= 0) throw new Error("Equivalent radius must be positive.");
    return { command: "RESIZE_BUBBLE", bubble_id: id, equivalent_radius_m: radius };
  }
  return { command: "SET_BUBBLE_VELOCITY", bubble_id: id, velocity_m_s: velocity };
}

async function executeEdit(): Promise<void> {
  if (!activeClient || !envelope) return;
  let command: LiveEditCommand;
  try {
    command = buildEditCommand();
  } catch (error) {
    panelMessage = error instanceof Error ? error.message : String(error);
    render();
    return;
  }
  await runAction(
    () => activeClient!.command(envelope!.sessionId, command as unknown as SessionCommand),
    `${command.command} accepted by the authoritative RuntimeSession at unchanged physical time.`,
  );
}

function readNumber(id: string, fallback: number): number {
  const value = Number(document.querySelector<HTMLInputElement>(`#${id}`)?.value);
  return Number.isFinite(value) ? value : fallback;
}

function captureEditDraft(): void {
  editDraft = {
    ...editDraft,
    bubbleId: document.querySelector<HTMLInputElement>("#live-edit-id")?.value ?? editDraft.bubbleId,
    centroid: [
      readNumber("live-edit-x", editDraft.centroid[0]),
      readNumber("live-edit-y", editDraft.centroid[1]),
      readNumber("live-edit-z", editDraft.centroid[2]),
    ],
    radius: readNumber("live-edit-radius", editDraft.radius),
    velocity: [
      readNumber("live-edit-vx", editDraft.velocity[0]),
      readNumber("live-edit-vy", editDraft.velocity[1]),
      readNumber("live-edit-vz", editDraft.velocity[2]),
    ],
    tension: readNumber("live-edit-tension", editDraft.tension),
  };
}

function wireControls(): void {
  document.querySelector<HTMLInputElement>("#live-session-url")?.addEventListener("input", (event) => {
    baseUrl = (event.target as HTMLInputElement).value;
  });
  document.querySelector<HTMLButtonElement>("#live-health")?.addEventListener("click", async () => {
    busy = true; render();
    try {
      const client = new LiveSessionClient(baseUrl);
      const health = await client.health();
      panelMessage = `Loopback server healthy · transport ${health.transportVersion} · ${health.bindScope}.`;
    } catch (error) {
      panelMessage = error instanceof Error ? `${error.name}: ${error.message}` : String(error);
    } finally { busy = false; render(); }
  });
  document.querySelector<HTMLButtonElement>("#live-create")?.addEventListener("click", async () => {
    if (!viewerState) return;
    const backend = selectedBackend(viewerState.editorScenario);
    busy = true; render();
    try {
      const client = new LiveSessionClient(baseUrl);
      if (activeClient && envelope) {
        try { await activeClient.closeSession(envelope.sessionId); } catch { /* stale local process may already be gone */ }
      }
      const next = await client.createSession(viewerState.editorScenario, backend);
      activeClient = client;
      activeScenarioFingerprint = currentScenarioFingerprint;
      applyEnvelope(next, backend);
      panelMessage = `Live ${backend} session created. State, time, FRAME, capabilities, and history come from the Python backend.`;
    } catch (error) {
      activeClient = null;
      envelope = null;
      activeScenarioFingerprint = "";
      panelMessage = error instanceof Error ? `${error.name}: ${error.message}` : String(error);
    } finally { busy = false; render(); }
  });
  document.querySelector<HTMLButtonElement>("#live-refresh")?.addEventListener("click", () => {
    if (!activeClient || !envelope) return;
    void runAction(() => activeClient!.getSession(envelope!.sessionId), "Authoritative live session refreshed from the server.");
  });
  document.querySelector<HTMLButtonElement>("#live-close")?.addEventListener("click", async () => {
    if (!activeClient || !envelope) return;
    const closingClient = activeClient;
    const sessionId = envelope.sessionId;
    busy = true; render();
    try {
      await closingClient.closeSession(sessionId);
      panelMessage = `Live session ${sessionId} closed. The last imported canonical FRAME remains available only as replay data.`;
      activeClient = null;
      envelope = null;
      activeScenarioFingerprint = "";
    } catch (error) {
      panelMessage = error instanceof Error ? `${error.name}: ${error.message}` : String(error);
    } finally { busy = false; render(); }
  });
  document.querySelector<HTMLButtonElement>("#live-pause")?.addEventListener("click", () => { void execute({ command: "PAUSE" }); });
  document.querySelector<HTMLButtonElement>("#live-resume")?.addEventListener("click", () => { void execute({ command: "RESUME" }); });
  document.querySelector<HTMLButtonElement>("#live-step")?.addEventListener("click", () => { void execute({ command: "STEP" }); });
  document.querySelector<HTMLButtonElement>("#live-reset")?.addEventListener("click", () => { void execute({ command: "RESET" }); });
  document.querySelector<HTMLButtonElement>("#live-checkpoint")?.addEventListener("click", () => {
    if (!activeClient || !envelope) return;
    void runAction(() => activeClient!.saveCheckpoint(envelope!.sessionId), "Canonical same-build checkpoint saved by the server and provenance refreshed.");
  });
  document.querySelector<HTMLInputElement>("#live-target-time")?.addEventListener("input", () => render());
  document.querySelector<HTMLButtonElement>("#live-run-to-time")?.addEventListener("click", () => {
    const target = Number(document.querySelector<HTMLInputElement>("#live-target-time")?.value);
    void execute({ command: "RUN_TO_TIME", target_time_s: target });
  });

  document.querySelector<HTMLSelectElement>("#live-edit-operation")?.addEventListener("change", (event) => {
    captureEditDraft();
    editDraft.operation = (event.target as HTMLSelectElement).value as LiveEditOperation;
    if (editDraft.operation === "ADD_BUBBLE") {
      const ids = authoritativeBubbles().map((item) => item.id).filter((id): id is string => typeof id === "string");
      if (ids.includes(editDraft.bubbleId)) {
        editDraft.bubbleId = "bubble-new";
        editDraft.centroid = [0.018, 0, 0];
        editDraft.radius = 0.004;
        editDraft.velocity = [0, 0, 0];
      }
    } else {
      syncEditDraftToEnvelope();
    }
    render();
  });
  document.querySelector<HTMLInputElement>("#live-edit-id")?.addEventListener("change", (event) => {
    captureEditDraft();
    const id = (event.target as HTMLInputElement).value.trim();
    editDraft.bubbleId = id;
    if (editDraft.operation !== "ADD_BUBBLE") hydrateEditDraftFromBubble(id);
    render();
  });
  for (const id of ["live-edit-x", "live-edit-y", "live-edit-z", "live-edit-radius", "live-edit-vx", "live-edit-vy", "live-edit-vz", "live-edit-tension"]) {
    document.querySelector<HTMLInputElement>(`#${id}`)?.addEventListener("change", captureEditDraft);
  }
  document.querySelector<HTMLButtonElement>("#live-apply-edit")?.addEventListener("click", () => {
    captureEditDraft();
    void executeEdit();
  });
}

if (root) subscribeViewerState((state) => {
  viewerState = state;
  const nextFingerprint = serializeScenarioDeterministic(state.editorScenario);
  if (currentScenarioFingerprint && nextFingerprint !== currentScenarioFingerprint && envelope) {
    panelMessage = "Editable SCENARIO changed. The existing live session remains authoritative for its original SCENARIO, so further live commands are disabled until a new session is started.";
  }
  currentScenarioFingerprint = nextFingerprint;
  render();
});
