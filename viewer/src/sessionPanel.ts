import { serializeScenarioDeterministic } from "./lab.js";
import {
  buildSessionInvocation,
  clearStagedSessionCommands,
  commandAvailability,
  commandResultSummary,
  createSessionIntent,
  fullSessionCommandSequence,
  loadAuthoritativeSessionBundleFromFiles,
  serializeSessionCommands,
  stageSessionCommand,
  type AuthoritativeSessionBundle,
  type RuntimeSessionBackend,
  type SessionCommand,
  type SessionIntentState,
} from "./sessionControl.js";
import { subscribeViewerState } from "./store.js";
import type { ContractScenario, ViewerState } from "./types.js";

const root = document.querySelector<HTMLElement>("#session-control-panel");
const runtimeBundleInput = document.querySelector<HTMLInputElement>("#runtime-bundle-input");

let viewerState: ViewerState | null = null;
let scenarioFingerprint = "";
let intent: SessionIntentState = createSessionIntent("transient");
let importedBundle: AuthoritativeSessionBundle | null = null;
let panelMessage = "Stage solver commands here, execute them with the external runtime, then import the generated Runtime bundle.";

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

function scenarioName(): string {
  return viewerState?.editorScenario.scenario_id ?? "scenario";
}

function commandLabel(command: SessionCommand): string {
  return command.command === "RUN_TO_TIME" ? `RUN_TO_TIME ${command.target_time_s} s` : command.command;
}

function commandRows(): string {
  const base = intent.baseCommands.map((command, index) => `<div class="kv"><span>#${index + 1} authoritative base</span><strong>${escapeHtml(commandLabel(command))}</strong></div>`);
  const staged = intent.stagedCommands.map((command, index) => `<div class="kv"><span>#${intent.baseCommands.length + index + 1} staged intent</span><strong>${escapeHtml(commandLabel(command))}</strong></div>`);
  return [...base, ...staged].join("") || '<p class="muted">No solver commands staged. Browser replay controls do not populate this queue.</p>';
}

function historyRows(): string {
  if (!importedBundle) return '<p class="muted">No authoritative session command history imported.</p>';
  if (!importedBundle.commandHistory.length) return '<p class="muted">The imported authoritative session has no commands yet.</p>';
  return importedBundle.commandHistory.slice(-10).map((entry) => {
    const summary = commandResultSummary(entry);
    const marker = entry.result === "ACCEPTED" ? "✓" : entry.result === "REJECTED" ? "⚠" : "✕";
    return `<div class="kv"><span>${marker} backend response</span><strong>${escapeHtml(summary)}</strong></div>`;
  }).join("");
}

function disabledAttribute(enabled: boolean, reason: string): string {
  return enabled ? ` title="${escapeHtml(reason)}"` : ` disabled aria-disabled="true" title="${escapeHtml(reason)}"`;
}

function render(): void {
  if (!root || !viewerState) return;
  const targetElement = document.querySelector<HTMLInputElement>("#session-target-time");
  const currentTarget = Number(targetElement?.value);
  const defaultTarget = Number.isFinite(currentTarget)
    ? currentTarget
    : Math.max(0.01, (intent.authoritative?.physical_time_s ?? 0) + 0.01);
  const pause = commandAvailability(intent, "PAUSE");
  const resume = commandAvailability(intent, "RESUME");
  const step = commandAvailability(intent, "STEP");
  const reset = commandAvailability(intent, "RESET");
  const run = commandAvailability(intent, "RUN_TO_TIME", defaultTarget);
  const authoritative = importedBundle?.snapshot ?? null;
  const lastCheckpoint = authoritative && authoritative.checkpoints.length
    ? authoritative.checkpoints[authoritative.checkpoints.length - 1]
    : null;
  const checkpointStatus = !authoritative
    ? "Awaiting authoritative metadata"
    : authoritative.capabilities.persistent_checkpoint_restart
      ? lastCheckpoint
        ? `Supported · ${lastCheckpoint.frame_id} · same-build only`
        : "Supported · no backend checkpoint imported"
      : "Unavailable (backend reported)";
  const checkpointNote = !authoritative
    ? "Checkpoint capability is not inferred in the browser. Import authoritative session metadata to confirm support."
    : !authoritative.capabilities.persistent_checkpoint_restart
      ? "The imported backend explicitly reports persistent checkpoint/restart as unavailable."
      : lastCheckpoint
        ? `Last backend checkpoint ${lastCheckpoint.frame_id} at ${lastCheckpoint.simulation_time_s} s; runtime ${lastCheckpoint.runtime_checkpoint_version}; continuation ${lastCheckpoint.continuation_format_version}; source ${lastCheckpoint.source_scenario.sha256}; ${lastCheckpoint.integrity.algorithm} ${lastCheckpoint.integrity.continuation_sha256}.`
        : "The backend reports same-build persistent checkpoint/restart support, but no saved checkpoint evidence is present in this imported bundle.";
  const importedMismatch = importedBundle && (
    importedBundle.backend !== selectedBackend(viewerState.editorScenario)
    || importedBundle.snapshot.scenario.id !== viewerState.editorScenario.scenario_id
  );
  const capabilityNote = intent.backend === "transient"
    ? "Transient exposes authoritative PAUSE / RESUME / STEP / RUN_TO_TIME / RESET."
    : intent.backend === "equilibrium"
      ? "Equilibrium is a completed quasi-static result; live solver stepping is unavailable."
      : `${intent.backend} has no authoritative live continuation handle yet; batch replay remains available.`;
  root.innerHTML = `
    <details class="debug-controls" open>
      <summary>Authoritative solver session</summary>
      <div class="kv"><span>Selected backend</span><strong>${escapeHtml(intent.backend)}</strong></div>
      <div class="kv"><span>Authoritative state</span><strong>${escapeHtml(authoritative?.state ?? "No response imported")}</strong></div>
      <div class="kv"><span>Authoritative physical time</span><strong>${authoritative ? `${authoritative.physical_time_s} s` : "Unavailable"}</strong></div>
      <div class="kv"><span>Authoritative frame index</span><strong>${authoritative ? String(authoritative.frame_index) : "Unavailable"}</strong></div>
      <div class="kv"><span>Queued intent state</span><strong>${escapeHtml(intent.stagedState)} · command intent only</strong></div>
      <p class="muted">${escapeHtml(capabilityNote)} The browser never advances canonical physics or physical time locally.</p>
      ${importedMismatch ? '<p class="muted">Imported session metadata is display-only because its scenario/backend does not match the current editable SCENARIO.</p>' : ""}
      <div class="toolbar" role="toolbar" aria-label="Authoritative solver session command intent">
        <button id="session-pause" type="button"${disabledAttribute(pause.enabled, pause.reason)}>Pause solver</button>
        <button id="session-resume" type="button"${disabledAttribute(resume.enabled, resume.reason)}>Resume solver</button>
        <button id="session-step" type="button"${disabledAttribute(step.enabled, step.reason)}>Single solver step</button>
        <button id="session-reset" type="button"${disabledAttribute(reset.enabled, reset.reason)}>Reset solver</button>
      </div>
      <div class="control-grid">
        <label>Physical target time (s)<input id="session-target-time" type="number" min="0" step="any" value="${defaultTarget}" /></label>
        <label>Persistent checkpoint/restart<input type="text" readonly value="${escapeHtml(checkpointStatus)}" /></label>
      </div>
      <p class="muted">${escapeHtml(checkpointNote)} The browser never serializes hidden solver continuation state and never claims save/restore success without imported backend evidence.</p>
      <div class="toolbar">
        <button id="session-run-to-time" type="button"${disabledAttribute(run.enabled, run.reason)}>Compute to physical time</button>
        <button id="session-clear-staged" type="button" ${intent.stagedCommands.length ? "" : "disabled aria-disabled=\"true\""}>Clear staged</button>
      </div>
      <h3>Deterministic solver command sequence</h3>
      ${commandRows()}
      <div class="toolbar">
        <button id="session-export-commands" type="button">Export session.commands.json</button>
        <button id="session-copy-command" type="button">Copy external CLI command</button>
      </div>
      <p class="muted">Run the exported command file with the external Python session runtime. Loading its generated Runtime bundle updates canonical FRAME display through the existing replay importer and updates authoritative session state here.</p>
      <h3>Authoritative backend command history</h3>
      ${historyRows()}
      <h3>Replay is separate</h3>
      <p class="muted">Replay Play / Step / Reset replay only navigate already-produced FRAME records. They never PAUSE, RESUME, STEP, RESET, or advance this solver session.</p>
      <p id="session-message" class="muted" aria-live="polite">${escapeHtml(panelMessage)}</p>
    </details>`;
  wireControls();
}

function stage(command: SessionCommand): void {
  try {
    intent = stageSessionCommand(intent, command);
    panelMessage = `${commandLabel(command)} staged. Authoritative state/time remain unchanged until a backend bundle is imported.`;
  } catch (error) {
    panelMessage = error instanceof Error ? error.message : String(error);
  }
  render();
}

function copyText(text: string): void {
  navigator.clipboard.writeText(text).then(
    () => { panelMessage = "External session CLI command copied."; render(); },
    () => { panelMessage = "Clipboard copy failed. Clipboard permission may be unavailable."; render(); },
  );
}

function exportCommands(): void {
  const commands = fullSessionCommandSequence(intent);
  const blob = new Blob([serializeSessionCommands(commands)], { type: "application/json" });
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = `${scenarioName()}.session.commands.json`;
  anchor.click();
  URL.revokeObjectURL(url);
  panelMessage = `Exported ${commands.length} deterministic solver command(s). No browser physics was executed.`;
  render();
}

function wireControls(): void {
  document.querySelector<HTMLButtonElement>("#session-pause")?.addEventListener("click", () => stage({ command: "PAUSE" }));
  document.querySelector<HTMLButtonElement>("#session-resume")?.addEventListener("click", () => stage({ command: "RESUME" }));
  document.querySelector<HTMLButtonElement>("#session-step")?.addEventListener("click", () => stage({ command: "STEP" }));
  document.querySelector<HTMLButtonElement>("#session-reset")?.addEventListener("click", () => stage({ command: "RESET" }));
  document.querySelector<HTMLButtonElement>("#session-run-to-time")?.addEventListener("click", () => {
    const target = Number(document.querySelector<HTMLInputElement>("#session-target-time")?.value);
    stage({ command: "RUN_TO_TIME", target_time_s: target });
  });
  document.querySelector<HTMLInputElement>("#session-target-time")?.addEventListener("input", () => render());
  document.querySelector<HTMLButtonElement>("#session-clear-staged")?.addEventListener("click", () => {
    intent = clearStagedSessionCommands(intent);
    panelMessage = "Staged solver command intent cleared. Imported authoritative response is unchanged.";
    render();
  });
  document.querySelector<HTMLButtonElement>("#session-export-commands")?.addEventListener("click", exportCommands);
  document.querySelector<HTMLButtonElement>("#session-copy-command")?.addEventListener("click", () => {
    const scenarioFile = `${scenarioName()}.scenario.json`;
    const commandsFile = `${scenarioName()}.session.commands.json`;
    copyText(buildSessionInvocation(intent.backend, { scenarioFile, commandsFile, outputDirectory: `${scenarioName()}.session-output` }));
  });
}

runtimeBundleInput?.addEventListener("change", async () => {
  if (!runtimeBundleInput.files?.length) return;
  try {
    const bundle = await loadAuthoritativeSessionBundleFromFiles(runtimeBundleInput.files);
    importedBundle = bundle;
    const matchesCurrent = viewerState
      && bundle.backend === selectedBackend(viewerState.editorScenario)
      && bundle.snapshot.scenario.id === viewerState.editorScenario.scenario_id;
    intent = matchesCurrent
      ? createSessionIntent(bundle.backend, bundle.snapshot, bundle.replayableCommands)
      : createSessionIntent(selectedBackend(viewerState!.editorScenario));
    panelMessage = matchesCurrent
      ? "Authoritative session bundle imported. Session state/time, checkpoint capability/provenance, and command history now come from the backend response."
      : "Authoritative session bundle imported for display, but continuation staging is disabled for that result because the current editable SCENARIO/backend differs.";
  } catch (error) {
    importedBundle = null;
    panelMessage = error instanceof Error ? error.message : String(error);
  }
  render();
});

if (root) subscribeViewerState((state) => {
  viewerState = state;
  const nextFingerprint = serializeScenarioDeterministic(state.editorScenario);
  if (nextFingerprint !== scenarioFingerprint) {
    scenarioFingerprint = nextFingerprint;
    importedBundle = null;
    intent = createSessionIntent(selectedBackend(state.editorScenario));
    panelMessage = "SCENARIO intent changed. Solver command queue and prior authoritative session association were cleared.";
  }
  render();
});
