import {
  buildInvocationDescriptor,
  capabilityDisclosure,
  requestUserBurst,
  serializeScenarioDeterministic,
  setBackendAndFidelity,
  setEnvironmentVectors,
  setRuntimeOutputCadence,
  setSolidBoundaries,
  setThinFilmConfiguration,
  solidBoundaryDefinitions,
  updateBubble,
  validateScenarioForBackend,
  type RuntimeBackend,
  type SolidBoundaryDefinition,
  type SolidBoundaryType,
  type ThinFilmPatch,
} from "./lab.js";
import { getLatestViewerState, replaceEditorScenario, subscribeViewerState } from "./store.js";
import type { ContractScenario, FidelityTier, Vec3, ViewerState } from "./types.js";

const root = document.querySelector<HTMLElement>("#lab-config-panel");

const escapeHtml = (value: string) => value.replace(/[&<>"']/g, (character) => ({
  "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#039;",
}[character] ?? character));
const record = (value: unknown): Record<string, unknown> => typeof value === "object" && value !== null && !Array.isArray(value) ? value as Record<string, unknown> : {};
const numberValue = (value: unknown, fallback = 0): number => typeof value === "number" && Number.isFinite(value) ? value : fallback;
const vec3 = (value: unknown, fallback: Vec3 = [0, 0, 0]): Vec3 => Array.isArray(value) && value.length === 3 && value.every((item) => typeof item === "number" && Number.isFinite(item)) ? [value[0], value[1], value[2]] as Vec3 : fallback;
const inputNumber = (id: string, fallback: number): number => {
  const element = document.querySelector<HTMLInputElement>(`#${id}`);
  const parsed = Number(element?.value);
  return Number.isFinite(parsed) ? parsed : fallback;
};
const inputChecked = (id: string, fallback: boolean): boolean => document.querySelector<HTMLInputElement>(`#${id}`)?.checked ?? fallback;

function selectedBackend(scenario: ContractScenario): RuntimeBackend {
  const value = record(scenario.requested_solver).backend;
  return value === "equilibrium" || value === "transient" || value === "thinfilm" || value === "thinfilm-events" ? value : "transient";
}

function currentScenario(): ContractScenario | null {
  return getLatestViewerState()?.editorScenario ?? null;
}

function applyScenario(scenario: ContractScenario) {
  replaceEditorScenario(scenario);
  queueMicrotask(() => document.querySelector<HTMLButtonElement>("#mode-edit")?.click());
}

async function copyText(text: string, label: string) {
  try {
    await navigator.clipboard.writeText(text);
    setMessage(`${label} copied.`);
  } catch {
    setMessage(`${label} copy failed. Clipboard permission may be unavailable.`);
  }
}

function downloadScenario(scenario: ContractScenario) {
  const blob = new Blob([serializeScenarioDeterministic(scenario)], { type: "application/json" });
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = `${scenario.scenario_id}.scenario.json`;
  anchor.click();
  URL.revokeObjectURL(url);
  setMessage("Canonical SCENARIO exported. Physics has not been executed in the browser.");
}

function setMessage(message: string) {
  const element = document.querySelector<HTMLElement>("#lab-message");
  if (element) element.textContent = message;
}

function bubbleEditorHtml(scenario: ContractScenario): string {
  return scenario.initial_bubbles.map((bubble, index) => {
    const position = bubble.centroid_m;
    const velocity = bubble.velocity_m_s;
    return `<details class="debug-controls" ${index === 0 ? "open" : ""}>
      <summary>Bubble ${index + 1} · ${escapeHtml(bubble.id)}</summary>
      <div class="control-grid">
        <label>Radius (m)<input data-bubble="${escapeHtml(bubble.id)}" data-field="radius" type="number" step="any" min="0" value="${bubble.equivalent_radius_m}" /></label>
        <label>Volume (derived)<input type="text" readonly value="${bubble.volume_m3}" /></label>
        <label>X (m)<input data-bubble="${escapeHtml(bubble.id)}" data-field="px" type="number" step="any" value="${position[0]}" /></label>
        <label>Y (m)<input data-bubble="${escapeHtml(bubble.id)}" data-field="py" type="number" step="any" value="${position[1]}" /></label>
        <label>Z (m)<input data-bubble="${escapeHtml(bubble.id)}" data-field="pz" type="number" step="any" value="${position[2]}" /></label>
        <label>Vx (m/s)<input data-bubble="${escapeHtml(bubble.id)}" data-field="vx" type="number" step="any" value="${velocity[0]}" /></label>
        <label>Vy (m/s)<input data-bubble="${escapeHtml(bubble.id)}" data-field="vy" type="number" step="any" value="${velocity[1]}" /></label>
        <label>Vz (m/s)<input data-bubble="${escapeHtml(bubble.id)}" data-field="vz" type="number" step="any" value="${velocity[2]}" /></label>
        <label>Pressure (Pa)<input data-bubble="${escapeHtml(bubble.id)}" data-field="pressure" type="number" step="any" value="${bubble.pressure_pa ?? ""}" /></label>
        <label>Temperature (K)<input data-bubble="${escapeHtml(bubble.id)}" data-field="temperature" type="number" step="any" value="${bubble.temperature_k ?? ""}" /></label>
        <label>Gas amount (mol)<input data-bubble="${escapeHtml(bubble.id)}" data-field="gas" type="number" step="any" min="0" value="${bubble.gas_amount_mol ?? ""}" /></label>
        <label>Gas species<input data-bubble="${escapeHtml(bubble.id)}" data-field="species" type="text" value="${escapeHtml(bubble.gas_species ?? "")}" /></label>
      </div>
    </details>`;
  }).join("") || '<p class="muted">No bubbles. Use the viewport Add bubble control to create initial geometry.</p>';
}

function boundaryField(index: number, field: string, label: string, value: number, min?: number, step = "any"): string {
  const minimum = min === undefined ? "" : ` min="${min}"`;
  return `<label>${label}<input data-boundary-index="${index}" data-boundary-field="${field}" type="number" step="${step}"${minimum} value="${value}" /></label>`;
}

function boundaryVectorFields(index: number, prefix: string, label: string, value: Vec3): string {
  return ["X", "Y", "Z"].map((axis, component) => boundaryField(index, `${prefix}${component}`, `${label} ${axis}`, value[component]!, undefined)).join("");
}

function boundaryEditorHtml(scenario: ContractScenario): string {
  const boundaries = solidBoundaryDefinitions(scenario);
  if (!boundaries.length) return '<p class="muted">No solid boundaries. Add a floor/plane, sphere, or AABB below. Boundary geometry is executed only by the external transient runtime.</p>';
  return boundaries.map((boundary, index) => {
    const wall = boundary.wall_velocity_m_s ?? [0, 0, 0];
    const wetting = boundary.wetting ?? {};
    const point = boundary.point_m ?? [0, 0, 0];
    const normal = boundary.normal_outward ?? [0, 1, 0];
    const center = boundary.center_m ?? [0, 0, 0];
    const minimum = boundary.minimum_m ?? [-0.01, -0.01, -0.01];
    const maximum = boundary.maximum_m ?? [0.01, 0.01, 0.01];
    return `<details class="debug-controls" data-boundary-editor="${index}" ${index === 0 ? "open" : ""}>
      <summary>Boundary ${index + 1} · ${escapeHtml(boundary.id)} · ${escapeHtml(boundary.type)}</summary>
      <div class="control-grid">
        <label>Stable ID<input data-boundary-index="${index}" data-boundary-field="id" type="text" value="${escapeHtml(boundary.id)}" /></label>
        <label>Geometry<select data-boundary-index="${index}" data-boundary-field="type">
          ${(["floor", "plane", "sphere", "aabb"] as SolidBoundaryType[]).map((type) => `<option value="${type}" ${boundary.type === type ? "selected" : ""}>${type}</option>`).join("")}
        </select></label>
        ${boundaryVectorFields(index, "wall", "Wall velocity (m/s)", wall)}
        <label>Contact angle (deg)<input data-boundary-index="${index}" data-boundary-field="angle" type="number" min="0" max="180" step="any" value="${wetting.target_contact_angle_deg ?? ""}" /></label>
        ${boundaryField(index, "relaxation", "Wetting relaxation", wetting.relaxation ?? 0.45, 0)}
        ${boundaryField(index, "iterations", "Wetting iterations", wetting.iterations ?? 3, 1, "1")}
        ${boundaryField(index, "contactBand", "Contact band (m)", wetting.contact_band_m ?? 0.002, 0)}
      </div>
      <p class="muted">Plane/floor geometry</p>
      <div class="control-grid">${boundaryVectorFields(index, "point", "Point (m)", point)}${boundaryVectorFields(index, "normal", "Outward normal", normal)}</div>
      <p class="muted">Sphere geometry</p>
      <div class="control-grid">${boundaryVectorFields(index, "center", "Center (m)", center)}${boundaryField(index, "radius", "Radius (m)", boundary.radius_m ?? 0.01, 0)}</div>
      <p class="muted">AABB geometry</p>
      <div class="control-grid">${boundaryVectorFields(index, "min", "Minimum (m)", minimum)}${boundaryVectorFields(index, "max", "Maximum (m)", maximum)}</div>
      <div class="toolbar"><button type="button" data-remove-boundary="${index}">Remove boundary</button></div>
    </details>`;
  }).join("");
}

function render(state: ViewerState) {
  if (!root) return;
  const scenario = state.editorScenario;
  const backend = selectedBackend(scenario);
  const solver = record(scenario.requested_solver);
  const thinfilm = record(scenario.user_editable.thinfilm);
  const runtime = record(scenario.user_editable.runtime);
  const events = record(scenario.user_editable.events);
  const wind = vec3(record(scenario.environment.wind).velocity_m_s);
  const gravity = scenario.environment.gravity_m_s2;
  const issues = validateScenarioForBackend(scenario, backend);
  const capabilities = capabilityDisclosure(scenario);
  let command = "Unavailable until the scenario/backend combination validates.";
  if (!issues.length) {
    try { command = buildInvocationDescriptor(scenario).command; } catch { /* validation text remains authoritative */ }
  }

  root.innerHTML = `
    <div class="kv"><span>Application state</span><strong>${state.mode === "EDIT" ? "EDIT_SCENARIO" : "REVIEW_REPLAY"}</strong></div>
    <div class="kv"><span>Physics execution</span><strong>External Python runtime only</strong></div>
    <p class="muted">These controls edit canonical SCENARIO intent. They never calculate or fabricate authoritative FRAME physics in the browser.</p>
    <div class="control-grid">
      <label>Backend<select id="lab-backend">
        ${["equilibrium", "transient", "thinfilm", "thinfilm-events"].map((value) => `<option value="${value}" ${backend === value ? "selected" : ""}>${value}</option>`).join("")}
      </select></label>
      <label>Fidelity<select id="lab-fidelity">
        ${["INTERACTIVE", "HIGH_FIDELITY", "MAXIMUM_REALISM"].map((value) => `<option value="${value}" ${scenario.requested_fidelity_tier === value ? "selected" : ""}>${value}</option>`).join("")}
      </select></label>
      <label>Output cadence (s)<input id="lab-cadence" type="number" step="any" min="0" value="${numberValue(runtime.output_cadence_s, 0.01)}" /></label>
    </div>
    <h3>Environment</h3>
    <div class="control-grid">
      <label>Gravity X<input id="lab-gx" type="number" step="any" value="${gravity[0]}" /></label>
      <label>Gravity Y<input id="lab-gy" type="number" step="any" value="${gravity[1]}" /></label>
      <label>Gravity Z<input id="lab-gz" type="number" step="any" value="${gravity[2]}" /></label>
      <label>Wind X<input id="lab-wx" type="number" step="any" value="${wind[0]}" /></label>
      <label>Wind Y<input id="lab-wy" type="number" step="any" value="${wind[1]}" /></label>
      <label>Wind Z<input id="lab-wz" type="number" step="any" value="${wind[2]}" /></label>
    </div>
    <h3>Solid boundaries</h3>
    <p class="muted">Transient resolves tracked-film SDF geometry and no-penetration. Wall tangential motion and contact-angle wetting are MODELED. Bulk solid-wall no-slip / bulk solid-fluid CFD remains NOT_IMPLEMENTED.</p>
    ${boundaryEditorHtml(scenario)}
    <div class="toolbar">
      <select id="lab-boundary-add-type"><option value="floor">floor</option><option value="plane">plane</option><option value="sphere">sphere</option><option value="aabb">AABB</option></select>
      <button id="lab-add-boundary" type="button">Add solid boundary</button>
    </div>
    <h3>Initial bubbles</h3>
    ${bubbleEditorHtml(scenario)}
    <h3>Thin-film / liquid transport</h3>
    <div class="control-grid">
      <label><input id="lab-drainage" type="checkbox" ${thinfilm.enable_drainage === true ? "checked" : ""} /> Drainage</label>
      <label><input id="lab-surfactant" type="checkbox" ${thinfilm.enable_surfactant_diffusion === true ? "checked" : ""} /> Surfactant diffusion</label>
      <label><input id="lab-gas-diffusion" type="checkbox" ${thinfilm.enable_gas_diffusion === true ? "checked" : ""} /> Gas diffusion / coarsening</label>
      <label>Initial thickness (m)<input id="lab-thickness" type="number" step="any" min="0" value="${numberValue(thinfilm.initial_thickness_m, 8e-6)}" /></label>
      <label>Initial surfactant (mol/m²)<input id="lab-surfactant-initial" type="number" step="any" min="0" value="${numberValue(thinfilm.initial_surfactant_mol_m2, 1e-6)}" /></label>
      <label>Dynamic viscosity (Pa·s)<input id="lab-viscosity" type="number" step="any" min="0" value="${numberValue(thinfilm.dynamic_viscosity_pa_s, 0.001)}" /></label>
      <label>Liquid density (kg/m³)<input id="lab-density" type="number" step="any" min="0" value="${numberValue(thinfilm.liquid_density_kg_m3, 1000)}" /></label>
      <label>Surfactant diffusivity (m²/s)<input id="lab-diffusivity" type="number" step="any" min="0" value="${numberValue(thinfilm.surfactant_diffusivity_m2_s, 2e-8)}" /></label>
      <label>Clean tension (N/m)<input id="lab-clean-tension" type="number" step="any" min="0" value="${numberValue(thinfilm.clean_surface_tension_n_m, 0.05)}" /></label>
      <label>Minimum tension (N/m)<input id="lab-min-tension" type="number" step="any" min="0" value="${numberValue(thinfilm.minimum_surface_tension_n_m, 0.02)}" /></label>
      <label>Surface elasticity<input id="lab-elasticity" type="number" step="any" min="0" value="${numberValue(thinfilm.surface_elasticity_n_m_per_mol_m2, 2000)}" /></label>
      <label>Gas permeability<input id="lab-permeability" type="number" step="any" min="0" value="${numberValue(thinfilm.gas_permeability_mol_m_per_m2_s_pa, 1e-11)}" /></label>
      <label>Positivity safety<input id="lab-positivity" type="number" step="any" min="0" max="1" value="${numberValue(thinfilm.positivity_safety, 0.45)}" /></label>
      <label>Max substeps<input id="lab-substeps" type="number" step="1" min="1" value="${numberValue(thinfilm.max_substeps, 10000)}" /></label>
    </div>
    <h3>Rupture / event intent</h3>
    <div class="control-grid">
      <label><input id="lab-allow-user-trigger" type="checkbox" ${events.allow_user_trigger === true ? "checked" : ""} /> Allow user-triggered rupture</label>
      <label>User trigger time (s)<input id="lab-burst-time" type="number" min="0" step="any" value="${numberValue(events.user_trigger_time_s, 0)}" /></label>
    </div>
    <div class="toolbar">
      <button id="lab-apply">Apply scenario controls</button>
      <button id="lab-request-burst">Prepare burst request</button>
      <button id="lab-copy-json">Copy SCENARIO JSON</button>
      <button id="lab-download-json">Export SCENARIO</button>
      <button id="lab-copy-command" ${issues.length ? "disabled" : ""}>Copy runtime command</button>
    </div>
    <p id="lab-message" class="muted">${state.mode === "REPLAY" ? "Loaded FRAME/replay is read-only. Applying scenario controls explicitly returns to EDIT_SCENARIO." : "Edit controls, then apply. The viewport and this panel share the same canonical editable SCENARIO."}</p>
    <h3>Runtime handoff</h3>
    <pre class="lab-command">${escapeHtml(command)}</pre>
    <h3>Validation</h3>
    ${issues.length ? `<div class="event-card">${issues.map((issue) => `<span><strong>${escapeHtml(issue.path)}</strong> · ${escapeHtml(issue.message)}</span>`).join("")}</div>` : '<p class="muted">Scenario is accepted by the viewer-side runtime gate for the selected backend.</p>'}
    <h3>Capability disclosure</h3>
    <div class="disclosures">${capabilities.map((row) => `<div class="kv"><span>${escapeHtml(row.feature)}</span><strong>${escapeHtml(`${row.status} · ${row.decision}`)}</strong></div>`).join("")}</div>
    <p class="muted">Before execution these rows describe accepted runtime capability, not solved output. Once a FRAME is loaded, the existing provenance/fidelity panel shows the authoritative manifest disclosures.</p>
    <input id="lab-solver-features" type="hidden" value="${escapeHtml(JSON.stringify(record(solver.features)))}" />
  `;
  wireControls(scenario);
}

function wireBubbleInputs(scenario: ContractScenario): ContractScenario {
  let next = scenario;
  for (const bubble of scenario.initial_bubbles) {
    const select = (field: string) => document.querySelector<HTMLInputElement>(`[data-bubble="${CSS.escape(bubble.id)}"][data-field="${field}"]`);
    const readOptional = (field: string): number | null | undefined => {
      const input = select(field);
      if (!input || input.value.trim() === "") return undefined;
      const value = Number(input.value);
      return Number.isFinite(value) ? value : undefined;
    };
    const radius = inputNumberFrom(select("radius"), bubble.equivalent_radius_m);
    const position: Vec3 = [inputNumberFrom(select("px"), bubble.centroid_m[0]), inputNumberFrom(select("py"), bubble.centroid_m[1]), inputNumberFrom(select("pz"), bubble.centroid_m[2])];
    const velocity: Vec3 = [inputNumberFrom(select("vx"), bubble.velocity_m_s[0]), inputNumberFrom(select("vy"), bubble.velocity_m_s[1]), inputNumberFrom(select("vz"), bubble.velocity_m_s[2])];
    next = updateBubble(next, bubble.id, {
      equivalentRadiusM: radius,
      positionM: position,
      velocityMS: velocity,
      pressurePa: readOptional("pressure"),
      temperatureK: readOptional("temperature"),
      gasAmountMol: readOptional("gas"),
      gasSpecies: select("species")?.value.trim() || undefined,
    });
  }
  return next;
}

function inputNumberFrom(input: HTMLInputElement | null, fallback: number): number {
  const value = Number(input?.value);
  return Number.isFinite(value) ? value : fallback;
}

function collectBoundaryInputs(base: ContractScenario): SolidBoundaryDefinition[] {
  const existing = solidBoundaryDefinitions(base);
  const editors = [...document.querySelectorAll<HTMLElement>("[data-boundary-editor]")];
  return editors.map((editor, order) => {
    const index = Number(editor.dataset.boundaryEditor);
    const fallback = existing[index] ?? defaultBoundary("floor", `boundary-${order + 1}`);
    const input = (field: string) => editor.querySelector<HTMLInputElement | HTMLSelectElement>(`[data-boundary-field="${field}"]`);
    const number = (field: string, fallbackValue: number): number => {
      const parsed = Number(input(field)?.value);
      return Number.isFinite(parsed) ? parsed : fallbackValue;
    };
    const vector = (prefix: string, fallbackValue: Vec3): Vec3 => [number(`${prefix}0`, fallbackValue[0]), number(`${prefix}1`, fallbackValue[1]), number(`${prefix}2`, fallbackValue[2])];
    const id = input("id")?.value.trim() || fallback.id;
    const selectedType = input("type")?.value;
    const type: SolidBoundaryType = selectedType === "plane" || selectedType === "sphere" || selectedType === "aabb" ? selectedType : "floor";
    const result: SolidBoundaryDefinition = {
      id,
      type,
      wall_velocity_m_s: vector("wall", fallback.wall_velocity_m_s ?? [0, 0, 0]),
      wetting: {
        relaxation: number("relaxation", fallback.wetting?.relaxation ?? 0.45),
        iterations: Math.max(1, Math.round(number("iterations", fallback.wetting?.iterations ?? 3))),
        contact_band_m: number("contactBand", fallback.wetting?.contact_band_m ?? 0.002),
      },
    };
    const angleElement = input("angle");
    if (angleElement && angleElement.value.trim() !== "") {
      const angle = Number(angleElement.value);
      if (Number.isFinite(angle)) result.wetting!.target_contact_angle_deg = angle;
    }
    if (type === "floor" || type === "plane") {
      result.point_m = vector("point", fallback.point_m ?? [0, 0, 0]);
      result.normal_outward = vector("normal", fallback.normal_outward ?? [0, 1, 0]);
    } else if (type === "sphere") {
      result.center_m = vector("center", fallback.center_m ?? [0, 0, 0]);
      result.radius_m = number("radius", fallback.radius_m ?? 0.01);
    } else {
      result.minimum_m = vector("min", fallback.minimum_m ?? [-0.01, -0.01, -0.01]);
      result.maximum_m = vector("max", fallback.maximum_m ?? [0.01, 0.01, 0.01]);
    }
    return result;
  });
}

function defaultBoundary(type: SolidBoundaryType, id: string): SolidBoundaryDefinition {
  const common: SolidBoundaryDefinition = {
    id,
    type,
    wall_velocity_m_s: [0, 0, 0],
    wetting: { target_contact_angle_deg: 90, relaxation: 0.45, iterations: 3, contact_band_m: 0.002 },
  };
  if (type === "floor" || type === "plane") return { ...common, point_m: [0, -0.01, 0], normal_outward: [0, 1, 0] };
  if (type === "sphere") return { ...common, center_m: [0.03, 0, 0], radius_m: 0.005 };
  return { ...common, minimum_m: [-0.01, -0.01, -0.01], maximum_m: [0.01, 0.01, 0.01] };
}

function uniqueBoundaryId(boundaries: readonly SolidBoundaryDefinition[], type: SolidBoundaryType): string {
  const stem = type === "aabb" ? "box" : type;
  const used = new Set(boundaries.map((boundary) => boundary.id));
  let ordinal = 1;
  while (used.has(`${stem}-${ordinal}`)) ordinal += 1;
  return `${stem}-${ordinal}`;
}

function collectScenario(base: ContractScenario): ContractScenario {
  const backend = (document.querySelector<HTMLSelectElement>("#lab-backend")?.value ?? selectedBackend(base)) as RuntimeBackend;
  const fidelity = (document.querySelector<HTMLSelectElement>("#lab-fidelity")?.value ?? base.requested_fidelity_tier) as FidelityTier;
  let next = setBackendAndFidelity(base, backend, fidelity);
  next = setEnvironmentVectors(next,
    [inputNumber("lab-gx", base.environment.gravity_m_s2[0]), inputNumber("lab-gy", base.environment.gravity_m_s2[1]), inputNumber("lab-gz", base.environment.gravity_m_s2[2])],
    [inputNumber("lab-wx", 0), inputNumber("lab-wy", 0), inputNumber("lab-wz", 0)],
  );
  next = setSolidBoundaries(next, collectBoundaryInputs(base));
  next = setRuntimeOutputCadence(next, Math.max(0, inputNumber("lab-cadence", 0.01)));
  const patch: ThinFilmPatch = {
    enable_drainage: inputChecked("lab-drainage", false),
    enable_surfactant_diffusion: inputChecked("lab-surfactant", false),
    enable_gas_diffusion: inputChecked("lab-gas-diffusion", false),
    initial_thickness_m: Math.max(0, inputNumber("lab-thickness", 8e-6)),
    initial_surfactant_mol_m2: Math.max(0, inputNumber("lab-surfactant-initial", 1e-6)),
    dynamic_viscosity_pa_s: Math.max(0, inputNumber("lab-viscosity", 0.001)),
    liquid_density_kg_m3: Math.max(0, inputNumber("lab-density", 1000)),
    surfactant_diffusivity_m2_s: Math.max(0, inputNumber("lab-diffusivity", 2e-8)),
    clean_surface_tension_n_m: Math.max(0, inputNumber("lab-clean-tension", 0.05)),
    minimum_surface_tension_n_m: Math.max(0, inputNumber("lab-min-tension", 0.02)),
    surface_elasticity_n_m_per_mol_m2: Math.max(0, inputNumber("lab-elasticity", 2000)),
    gas_permeability_mol_m_per_m2_s_pa: Math.max(0, inputNumber("lab-permeability", 1e-11)),
    positivity_safety: Math.min(1, Math.max(0, inputNumber("lab-positivity", 0.45))),
    max_substeps: Math.max(1, Math.round(inputNumber("lab-substeps", 10000))),
  };
  next = setThinFilmConfiguration(next, patch);
  return wireBubbleInputs(next);
}

function wireControls(renderedScenario: ContractScenario) {
  document.querySelector<HTMLButtonElement>("#lab-apply")?.addEventListener("click", () => {
    applyScenario(collectScenario(renderedScenario));
  });
  document.querySelector<HTMLButtonElement>("#lab-request-burst")?.addEventListener("click", () => {
    let next = collectScenario(renderedScenario);
    next = requestUserBurst(next, Math.max(0, inputNumber("lab-burst-time", 0)));
    applyScenario(next);
  });
  document.querySelector<HTMLButtonElement>("#lab-copy-json")?.addEventListener("click", () => {
    void copyText(serializeScenarioDeterministic(collectScenario(renderedScenario)), "SCENARIO JSON");
  });
  document.querySelector<HTMLButtonElement>("#lab-download-json")?.addEventListener("click", () => downloadScenario(collectScenario(renderedScenario)));
  document.querySelector<HTMLButtonElement>("#lab-copy-command")?.addEventListener("click", () => {
    const scenario = collectScenario(renderedScenario);
    try { void copyText(buildInvocationDescriptor(scenario).command, "Runtime command"); }
    catch (error) { setMessage(error instanceof Error ? error.message : String(error)); }
  });
  document.querySelector<HTMLButtonElement>("#lab-add-boundary")?.addEventListener("click", () => {
    const next = collectScenario(renderedScenario);
    const boundaries = solidBoundaryDefinitions(next);
    const selected = document.querySelector<HTMLSelectElement>("#lab-boundary-add-type")?.value;
    const type: SolidBoundaryType = selected === "plane" || selected === "sphere" || selected === "aabb" ? selected : "floor";
    boundaries.push(defaultBoundary(type, uniqueBoundaryId(boundaries, type)));
    applyScenario(setSolidBoundaries(next, boundaries));
  });
  document.querySelectorAll<HTMLButtonElement>("[data-remove-boundary]").forEach((button) => button.addEventListener("click", () => {
    const next = collectScenario(renderedScenario);
    const boundaries = solidBoundaryDefinitions(next);
    const index = Number(button.dataset.removeBoundary);
    if (Number.isInteger(index) && index >= 0 && index < boundaries.length) boundaries.splice(index, 1);
    applyScenario(setSolidBoundaries(next, boundaries));
  }));
}

window.addEventListener("bubblelab:burst-request", () => {
  const scenario = currentScenario();
  if (!scenario) return;
  const time = Math.max(0, inputNumber("lab-burst-time", 0));
  applyScenario(requestUserBurst(scenario, time));
});

if (root) subscribeViewerState(render);
