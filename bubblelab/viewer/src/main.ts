import { adaptFrame, adaptScenario } from "./adapter.js";
import { fitSpheres } from "./camera.js";
import {
  discoverScalarFields,
  discoverVectorFields,
  extractAmrDiagnostics,
  extractRemeshDiagnostics,
  resolveScalarRange,
  scalarStatistics,
  summarizeSystem,
  topologySelectionForJunction,
  topologySelectionForSurface,
} from "./debug.js";
import { frameFixtureDefinitions, loadCanonicalFrameFixture, loadCanonicalScenarioFixture } from "./fixtures.js";
import { canCommitPlacementTap, selectLayoutPolicy, type RenderQualityMode } from "./mobile.js";
import { featureFilmThicknessStatus, SOAP_FILM_IOR } from "./optics.js";
import { createReplay, currentReplayFrame, currentReplayTime, pauseReplay, playReplay, resetReplay, stepReplay, type ReplayState } from "./replay.js";
import { loadReplayBundleFromFiles } from "./runtimeBundle.js";
import { addEditorBubble, clearSelection, createViewerState, deleteAll, deleteSelected, selectBubble, selectSurface, setAddMode, setMode } from "./store.js";
import type { ContractBubble, LoadedContractFrame, LoadedContractScenario, RenderSceneData, Vec3, ViewerState } from "./types.js";
import { createSceneController, type DisplayOptions, type FilmVisibilityMode } from "./renderer.js";

const canvas = document.querySelector<HTMLCanvasElement>("#viewport")!;
const fixtureSelect = document.querySelector<HTMLSelectElement>("#fixture-select")!;
const fidelityBadge = document.querySelector<HTMLElement>("#fidelity-badge")!;
const selectionPanel = document.querySelector<HTMLElement>("#selection-panel")!;
const systemPanel = document.querySelector<HTMLElement>("#system-panel")!;
const opticsPanel = document.querySelector<HTMLElement>("#optics-panel")!;
const provenancePanel = document.querySelector<HTMLElement>("#provenance-panel")!;
const eventPanel = document.querySelector<HTMLElement>("#event-panel")!;
const debugFieldPanel = document.querySelector<HTMLElement>("#debug-field-panel")!;
const replayPosition = document.querySelector<HTMLElement>("#replay-position")!;
const statusLine = document.querySelector<HTMLElement>("#status-line")!;
const addHint = document.querySelector<HTMLElement>("#add-hint")!;
const replayPlay = document.querySelector<HTMLButtonElement>("#replay-play")!;
const runtimeBundleInput = document.querySelector<HTMLInputElement>("#runtime-bundle-input")!;
const previewThicknessInput = document.querySelector<HTMLInputElement>("#preview-thickness-nm")!;
const qualityModeSelect = document.querySelector<HTMLSelectElement>("#quality-mode")!;
const scalarSelect = document.querySelector<HTMLSelectElement>("#scalar-channel")!;
const vectorSelect = document.querySelector<HTMLSelectElement>("#vector-channel")!;
const scalarRangeMode = document.querySelector<HTMLSelectElement>("#scalar-range-mode")!;
const scalarMinInput = document.querySelector<HTMLInputElement>("#scalar-min")!;
const scalarMaxInput = document.querySelector<HTMLInputElement>("#scalar-max")!;
const scalarDivergingInput = document.querySelector<HTMLInputElement>("#scalar-diverging")!;
const vectorGlyphCountInput = document.querySelector<HTMLInputElement>("#vector-glyph-count")!;
const vectorScaleInput = document.querySelector<HTMLInputElement>("#vector-scale")!;
const vectorNormalizeInput = document.querySelector<HTMLInputElement>("#vector-normalize")!;
const inspector = document.querySelector<HTMLElement>(".inspector")!;
const inspectorToggle = document.querySelector<HTMLButtonElement>("#inspector-toggle")!;

let loadedFrame: LoadedContractFrame;
let loadedScenario: LoadedContractScenario;
let state: ViewerState;
let replay: ReplayState;
let fieldSignature = "";
let display: DisplayOptions = {
  filmMode: "ALL",
  showCanonicalMesh: true,
  showSphereFallback: true,
  showFaces: true,
  wireframe: false,
  showVertices: false,
  showVertexNormals: false,
  showFaceNormals: false,
  showJunctions: true,
  scalarChannel: "none",
  scalarRangeMode: "AUTO",
  scalarMin: null,
  scalarMax: null,
  scalarDiverging: false,
  vectorChannel: "none",
  vectorGlyphCount: 120,
  vectorScale: 1,
  vectorNormalize: true,
  interferenceMode: "AUTO",
  visualPreviewThicknessNm: 350,
  qualityMode: "AUTO",
};
let fps = 0, renderedFrames = 0, fpsMark = performance.now();
const scene = createSceneController(canvas, { onTap: handleCanvasTap });
for (const fixture of frameFixtureDefinitions) {
  const option = document.createElement("option"); option.value = fixture.id; option.textContent = fixture.label; fixtureSelect.append(option);
}

const fmt = (value: number | null | undefined, digits = 4) => {
  if (typeof value !== "number" || !Number.isFinite(value)) return "Unavailable";
  const magnitude = Math.abs(value);
  return magnitude > 0 && (magnitude < 0.001 || magnitude >= 10000) ? value.toExponential(3) : value.toFixed(digits);
};
const vec = (value: Vec3 | undefined) => value ? `[${value.map((item) => fmt(item, 4)).join(", ")}]` : "Unavailable";
const textValue = (value: unknown): string => {
  if (value === undefined || value === null) return "Unavailable";
  if (typeof value === "number") return Number.isFinite(value) ? fmt(value, 6) : "Unavailable";
  if (typeof value === "string" || typeof value === "boolean") return String(value);
  try { return JSON.stringify(value); } catch { return String(value); }
};
const HTML_ESCAPES: Readonly<Record<string, string>> = {
  "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#039;",
};
const escapeHtml = (value: string) => value.replace(/[&<>"']/g, (character) => HTML_ESCAPES[character] ?? character);
const row = (name: string, value: string) => `<div class="kv"><span>${escapeHtml(name)}</span><strong>${escapeHtml(value)}</strong></div>`;
const rawBubble = (data: RenderSceneData, id: string): ContractBubble | undefined => data.frame?.bubbles.find((bubble) => bubble.id === id);

function handleCanvasTap(clientX: number, clientY: number, additive = false) {
  if (canCommitPlacementTap(state.mode, state.addMode, true)) {
    const point = scene.projectToPlacementPlane(clientX, clientY);
    if (point) {
      const radius = 0.0005;
      state = addEditorBubble(state, { position: [point[0], point[1], radius], radius });
      refresh();
    }
    return;
  }
  const target = scene.pickTarget(clientX, clientY);
  if (!target) state = clearSelection(state);
  else if (target.kind === "BUBBLE") state = selectBubble(state, target.id, additive);
  else if (target.kind === "JUNCTION") state = selectSurface(state, `junction:${target.id}`);
  else state = selectSurface(state, target.id);
  refresh();
}

function applyResponsiveLayout() {
  const policy = selectLayoutPolicy(window.innerWidth, window.innerHeight);
  document.documentElement.dataset.inspectorLayout = policy.inspector.toLowerCase();
  document.documentElement.dataset.orientation = policy.orientation.toLowerCase();
  inspectorToggle.hidden = !policy.compact;
  if (!policy.compact) inspector.classList.remove("mobile-collapsed");
  inspectorToggle.setAttribute("aria-expanded", String(!inspector.classList.contains("mobile-collapsed")));
}

function currentData(): RenderSceneData {
  if (state.mode === "EDIT") return adaptScenario(state.editorScenario, { provenanceSource: loadedScenario.provenanceSource, provenanceLabel: loadedScenario.label });
  return adaptFrame(currentReplayFrame(replay), { provenanceSource: loadedFrame.provenanceSource, provenanceLabel: loadedFrame.label });
}

function renderSelection(data: RenderSceneData) {
  if (state.selectedSurfaceId?.startsWith("junction:")) {
    const junctionId = state.selectedSurfaceId.slice("junction:".length);
    const topology = data.frame ? topologySelectionForJunction(data.frame, junctionId) : undefined;
    if (!topology) {
      selectionPanel.innerHTML = '<p class="muted">Selected junction is not present in this canonical FRAME.</p>';
      return;
    }
    selectionPanel.innerHTML = `<article class="bubble-card">${row("Selection", "Canonical junction")}${row("Junction ID", topology.id)}${row("Incident films", topology.incidentFilmIds?.join(", ") ?? "Unavailable")}${row("Measured angles", topology.measuredAnglesDeg?.map((value) => `${fmt(value, 2)}°`).join(", ") ?? "Unavailable")}${row("Measurement provenance", textValue(topology.measurementProvenance))}</article>`;
    return;
  }
  if (state.selectedSurfaceId) {
    const surface = data.surfaceMeshes.find((mesh) => mesh.id === state.selectedSurfaceId);
    if (!surface) { selectionPanel.innerHTML = '<p class="muted">Selected film/surface is not present in this source.</p>'; return; }
    const thickness = surface.physicalThickness
      ? `${surface.physicalThickness.kind} · ${surface.physicalThickness.provenanceSource}`
      : "Unavailable";
    const topology = data.frame ? topologySelectionForSurface(data.frame, surface.id) : undefined;
    selectionPanel.innerHTML = `<article class="bubble-card">${row("Selection", "Canonical film/surface")}${row("Mesh ID", surface.id)}${row("Geometry role", surface.geometryRole)}${row("Owners", surface.ownerBubbleIds.length ? surface.ownerBubbleIds.join(", ") : "None")}${row("Film region ID", topology?.id ?? surface.filmId ?? "Unavailable")}${row("Film kind", topology?.filmKind ?? surface.filmKind ?? "Unavailable")}${row("Adjacent IDs", topology?.adjacentIds?.join(", ") ?? "Unavailable")}${row("Storage", surface.storage)}${row("Physical thickness", thickness)}</article>`;
    return;
  }
  if (state.selectedIds.size === 0) { selectionPanel.innerHTML = '<p class="muted">No bubble, film, or junction selected.</p>'; return; }
  const selected = data.bubbles.filter((bubble) => state.selectedIds.has(bubble.id));
  if (!selected.length) { selectionPanel.innerHTML = '<p class="muted">Selected ID is not present in this source.</p>'; return; }
  selectionPanel.innerHTML = selected.map((bubble) => {
    const raw = rawBubble(data, bubble.id);
    const contactCount = data.frame?.topology.adjacency.filter((entry) => entry.a === bubble.id || entry.b === bubble.id).length;
    return `<article class="bubble-card">${row("ID", bubble.id)}${row("Status", bubble.physical.status)}${row("Volume", `${fmt(bubble.physical.volume)} m³`)}${row("Equivalent radius", `${fmt(bubble.physical.equivalentRadius)} m`)}${row("Centroid", vec(bubble.physical.position))}${row("Velocity", vec(bubble.physical.velocity))}${row("Pressure", bubble.physical.pressure === null ? "Unavailable (null)" : `${fmt(bubble.physical.pressure, 2)}${typeof bubble.physical.pressure === "number" ? " Pa" : ""}`)}${row("Temperature", typeof raw?.temperature_k === "number" ? `${fmt(raw.temperature_k, 2)} K` : "Unavailable")}${row("Gas amount", typeof raw?.gas_amount_mol === "number" ? `${fmt(raw.gas_amount_mol)} mol` : "Unavailable")}${row("Surface area", bubble.physical.area === null ? "Unavailable (null)" : `${fmt(bubble.physical.area)}${typeof bubble.physical.area === "number" ? " m²" : ""}`)}${row("Relative volume error", fmt(bubble.physical.volumeError))}${row("Contacts", contactCount === undefined ? "Unavailable" : String(contactCount))}${row("Film thickness", bubble.physical.thickness === null ? "Unavailable (null)" : `${fmt(bubble.physical.thickness)}${typeof bubble.physical.thickness === "number" ? " m" : ""}`)}${row("Shape source", bubble.shapeSource === "CANONICAL_MESH" ? "Canonical surface mesh" : "Viewer sphere fallback")}</article>`;
  }).join("");
}

function diagnosticRows(title: string, values: Record<string, unknown> | undefined): string {
  if (!values) return `<h3>${escapeHtml(title)}</h3><p class="muted">Unavailable</p>`;
  return `<h3>${escapeHtml(title)}</h3>${Object.entries(values).map(([key, value]) => row(key, textValue(value))).join("")}`;
}

function renderSystem(data: RenderSceneData) {
  const alive = data.bubbles.filter((bubble) => bubble.visible);
  const totalVolume = alive.reduce((sum, bubble) => sum + bubble.physical.volume, 0);
  const areas = alive.map((bubble) => bubble.physical.area);
  const totalArea = areas.length > 0 && areas.every((area) => typeof area === "number")
    ? (areas as number[]).reduce((a, b) => a + b, 0)
    : undefined;
  const baseRows = [
    row("Bubble records", String(data.bubbles.length)),
    row("Alive bubbles", String(alive.length)),
    row("Total alive volume", `${fmt(totalVolume)} m³`),
    row("Total area", `${fmt(totalArea)}${typeof totalArea === "number" ? " m²" : ""}`),
    row("Simulation time", data.simulationTime === undefined ? "Not applicable (SCENARIO)" : `${fmt(data.simulationTime, 6)} s`),
    row("Timestep", data.diagnostics?.timestep_s === undefined ? "Unavailable" : `${fmt(data.diagnostics.timestep_s, 6)} s`),
    row("FPS", fps ? fps.toFixed(0) : "Measuring"),
    row("Compute time", data.diagnostics?.compute_time_s === undefined ? "Unavailable" : `${fmt(data.diagnostics.compute_time_s, 6)} s`),
    row("Nonlinear iterations", data.diagnostics?.nonlinear_iterations === undefined ? "Unavailable" : String(data.diagnostics.nonlinear_iterations)),
    row("Linear iterations", data.diagnostics?.linear_iterations === undefined ? "Unavailable" : String(data.diagnostics.linear_iterations)),
    row("Max volume error", fmt(data.diagnostics?.max_relative_volume_error)),
  ];
  if (!data.frame) {
    systemPanel.innerHTML = baseRows.join("") + row("Shared films", String(data.sharedFilms.length)) + row("Junctions", String(data.junctions.length));
    return;
  }
  const summary = summarizeSystem(data.frame);
  const residuals = data.frame.diagnostics?.residuals;
  systemPanel.innerHTML = [
    ...baseRows,
    row("Shared films", String(summary.sharedFilmCount)),
    row("Junctions", String(summary.junctionCount)),
    row("Topology events", String(summary.topologyEventCount)),
    row("Fidelity tier", summary.fidelityTier),
    row("Solver/backend", summary.solverIdentity),
    row("Active features", summary.activeFeatures.length ? summary.activeFeatures.join(", ") : "None declared active"),
    diagnosticRows("Residuals", residuals),
    diagnosticRows("AMR metadata", extractAmrDiagnostics(data.frame)),
    diagnosticRows("Remeshing metadata", extractRemeshDiagnostics(data.frame)),
  ].join("");
}

function renderOptics(data: RenderSceneData) {
  const disclosure = featureFilmThicknessStatus(data.featureDisclosures);
  const meshThickness = data.surfaceMeshes.filter((mesh) => mesh.physicalThickness);
  const bubbleThickness = data.bubbles.filter((bubble) => typeof bubble.physical.thickness === "number");
  const fieldCount = meshThickness.filter((mesh) => mesh.physicalThickness?.kind !== "SCALAR").length;
  const physicalCount = meshThickness.length + bubbleThickness.length;
  let source: string;
  if (display.interferenceMode === "OFF") source = "Interference off · neutral Fresnel/transmission";
  else if (display.interferenceMode === "VISUAL_PREVIEW") source = `VISUAL_ONLY preview · ${fmt(display.visualPreviewThicknessNm, 0)} nm`;
  else if ((disclosure === "NOT_IMPLEMENTED" || disclosure === "VISUAL_ONLY") && physicalCount > 0) source = `Physical thickness blocked by disclosure: ${disclosure}`;
  else if (physicalCount > 0) {
    source = disclosure === "RESOLVED" ? "PHYSICAL · RESOLVED contract thickness"
      : disclosure === "MODELED" ? "PHYSICAL · MODELED contract thickness"
      : "CONTRACT_INPUT · canonical scenario/import thickness";
  } else source = "No authoritative thickness · neutral Fresnel/transmission";
  opticsPanel.innerHTML = [
    row("Film thickness disclosure", disclosure ?? (data.sourceKind === "SCENARIO" ? "No manifest in SCENARIO" : "Unspecified")),
    row("Interference source", source),
    row("Canonical thickness inputs", `${physicalCount} (${fieldCount} field-based)`),
    row("Film optical IOR", `${SOAP_FILM_IOR.toFixed(3)} · renderer optical constant`),
    row("Ambient medium", display.qualityMode === "BATTERY" ? "Air · environment map disabled by rendering profile" : "Air · environment reflection via PMREM"),
    row("Surface handling", display.qualityMode === "BATTERY" ? "Renderer-only Battery mode · costly transmission/iridescence disabled" : "Transparent · transmission · double-sided"),
    row("Rendering profile", `${display.qualityMode} · presentation only; canonical physics unchanged`),
  ].join("");
}

function renderProvenance(data: RenderSceneData) {
  const disclosures = Object.entries(data.featureDisclosures).sort(([a], [b]) => a.localeCompare(b));
  const sourceRows = [
    row("Contract source", data.sourceKind), row("Source ID", data.sourceId),
    row("Provenance", data.provenanceSource), row("Fidelity", data.fidelity),
  ];
  if (data.frame) sourceRows.push(
    row("Producer", data.frame.manifest.provenance.producer),
    row("Solver", `${data.frame.manifest.solver.backend} ${data.frame.manifest.solver.version}`),
  );
  const disclosureHtml = disclosures.length
    ? `<div class="disclosures">${disclosures.map(([featureName, value]) => row(featureName, value)).join("")}</div>`
    : '<p class="muted">Feature disclosures are supplied by result manifests; an editable SCENARIO has none yet.</p>';
  provenancePanel.innerHTML = `${sourceRows.join("")}<h3>Feature disclosures</h3>${disclosureHtml}`;
}

function renderEvents(data: RenderSceneData) {
  if (!data.events.length) { eventPanel.innerHTML = '<p class="muted">No topology events in this source.</p>'; return; }
  eventPanel.innerHTML = data.events.map((event) =>
    `<article class="event-card"><strong>${escapeHtml(event.type)}</strong><span>t=${escapeHtml(fmt(event.time_s, 6))} s · ${escapeHtml(event.provenance.source)}</span><small>${escapeHtml(event.provenance.detail ?? "No detail supplied")}</small></article>`
  ).join("");
}

function syncFieldSelectors(data: RenderSceneData) {
  const scalarFields = data.frame ? discoverScalarFields(data.frame, data.provenanceSource) : [];
  const vectorFields = data.frame ? discoverVectorFields(data.frame, data.provenanceSource) : [];
  const signature = [
    data.sourceKind, data.sourceId,
    ...scalarFields.map((field) => `s:${field.key}:${field.available}`),
    ...vectorFields.map((field) => `v:${field.key}:${field.available}`),
  ].join("|");
  if (signature === fieldSignature) return;
  fieldSignature = signature;

  scalarSelect.replaceChildren();
  const noneScalar = document.createElement("option"); noneScalar.value = "none"; noneScalar.textContent = "None"; scalarSelect.append(noneScalar);
  for (const field of scalarFields) {
    const option = document.createElement("option");
    option.value = field.key;
    option.textContent = `${field.name} · ${field.association}${field.available ? "" : " · Unavailable"}`;
    scalarSelect.append(option);
  }
  if (!scalarFields.some((field) => field.key === display.scalarChannel)) display = { ...display, scalarChannel: "none" };
  scalarSelect.value = display.scalarChannel;

  vectorSelect.replaceChildren();
  const noneVector = document.createElement("option"); noneVector.value = "none"; noneVector.textContent = "None"; vectorSelect.append(noneVector);
  for (const field of vectorFields) {
    const option = document.createElement("option");
    option.value = field.key;
    option.textContent = `${field.name} · ${field.association}${field.available ? "" : " · Unavailable"}`;
    vectorSelect.append(option);
  }
  if (!vectorFields.some((field) => field.key === display.vectorChannel)) display = { ...display, vectorChannel: "none" };
  vectorSelect.value = display.vectorChannel;
}

function renderDebugField(data: RenderSceneData) {
  if (!data.frame) {
    debugFieldPanel.innerHTML = '<p class="muted">Scientific scalar/vector discovery is available for canonical FRAME replay data. Editable SCENARIO values remain inspectable without being promoted to solved physics.</p>';
    return;
  }
  const scalarFields = discoverScalarFields(data.frame, data.provenanceSource);
  const vectorFields = discoverVectorFields(data.frame, data.provenanceSource);
  const scalar = scalarFields.find((field) => field.key === display.scalarChannel);
  const vectorField = vectorFields.find((field) => field.key === display.vectorChannel);
  const parts: string[] = [];
  if (scalar) {
    const stats = scalarStatistics(scalar.values);
    const range = resolveScalarRange(scalar.values, {
      mode: display.scalarRangeMode,
      ...(typeof display.scalarMin === "number" ? { min: display.scalarMin } : {}),
      ...(typeof display.scalarMax === "number" ? { max: display.scalarMax } : {}),
      diverging: display.scalarDiverging,
    });
    parts.push(
      "<h3>Scalar selection</h3>",
      row("Field", scalar.name),
      row("Source path", scalar.sourcePath),
      row("Association", scalar.association),
      row("Units", scalar.units ?? "Unknown / dimensionless"),
      row("Provenance class", scalar.provenanceClass),
      row("Input provenance", scalar.provenanceSource),
      row("Feature disclosure", scalar.disclosure ?? "Unspecified"),
      row("Availability", scalar.available ? "Available" : "Unavailable — blocked by NOT_IMPLEMENTED"),
      row("Finite / missing", `${stats.count} / ${stats.missingCount}`),
      row("Min", fmt(stats.min, 6)), row("Max", fmt(stats.max, 6)), row("Mean", fmt(stats.mean, 6)),
      row("Display range", range ? `${fmt(range.min, 6)} … ${fmt(range.max, 6)} · ${range.source}${range.diverging ? " · diverging" : ""}` : "Unavailable"),
    );
  } else parts.push("<h3>Scalar selection</h3><p class=\"muted\">None selected.</p>");

  if (vectorField) {
    parts.push(
      "<h3>Vector selection</h3>",
      row("Field", vectorField.name),
      row("Source path", vectorField.sourcePath),
      row("Association", vectorField.association),
      row("Units", vectorField.units ?? "Unknown / dimensionless"),
      row("Provenance class", vectorField.provenanceClass),
      row("Feature disclosure", vectorField.disclosure ?? "Unspecified"),
      row("Vectors", String(vectorField.values.length)),
      row("Glyph mode", display.vectorNormalize ? "Normalized direction" : "Magnitude-preserving display scale"),
    );
  } else parts.push("<h3>Vector selection</h3><p class=\"muted\">None selected.</p>");

  const canonicalVertexNormals = vectorFields.some((field) => field.association === "VERTEX" && field.name.toLowerCase().includes("normal") && field.available);
  const canonicalFaceNormals = vectorFields.some((field) => field.association === "FACE" && field.name.toLowerCase().includes("normal") && field.available);
  parts.push(
    "<h3>Normal overlays</h3>",
    row("Vertex normals", display.showVertexNormals ? (canonicalVertexNormals ? "Canonical vector field when mesh-matched" : "VIEWER_DERIVED render geometry") : "Off"),
    row("Face normals", display.showFaceNormals ? (canonicalFaceNormals ? "Canonical vector field when mesh-matched" : "VIEWER_DERIVED render geometry") : "Off"),
    '<p class="muted">VIEWER_DERIVED normals are geometry inspection aids only. They are not solver curvature, traction, stress, or force.</p>',
  );
  debugFieldPanel.innerHTML = parts.join("");
}

function updateButtons() {
  document.querySelector("#mode-edit")?.classList.toggle("active", state.mode === "EDIT");
  document.querySelector("#mode-replay")?.classList.toggle("active", state.mode === "REPLAY");
  document.querySelector("#add-toggle")?.classList.toggle("active", state.addMode);
  document.querySelector("#mode-edit")?.setAttribute("aria-pressed", String(state.mode === "EDIT"));
  document.querySelector("#mode-replay")?.setAttribute("aria-pressed", String(state.mode === "REPLAY"));
  document.querySelector("#add-toggle")?.setAttribute("aria-pressed", String(state.addMode));
  for (const id of ["add-toggle", "delete-selected", "delete-all", "burst-request"]) {
    const button = document.querySelector<HTMLButtonElement>(`#${id}`); if (button) button.disabled = state.mode !== "EDIT";
  }
  addHint.classList.toggle("hidden", !state.addMode);
  replayPlay.textContent = replay.playing ? "Pause" : "Play";
  replayPosition.textContent = `${replay.index + 1}/${replay.frames.length} · t=${fmt(currentReplayTime(replay), 6)} s · exact frames only`;
  previewThicknessInput.disabled = display.interferenceMode !== "VISUAL_PREVIEW";
  qualityModeSelect.value = display.qualityMode;
  scalarRangeMode.value = display.scalarRangeMode;
  scalarMinInput.disabled = display.scalarRangeMode !== "MANUAL";
  scalarMaxInput.disabled = display.scalarRangeMode !== "MANUAL";
  scalarDivergingInput.checked = display.scalarDiverging;
  vectorGlyphCountInput.value = String(display.vectorGlyphCount);
  vectorScaleInput.value = String(display.vectorScale);
  vectorNormalizeInput.checked = display.vectorNormalize;
}

function refresh() {
  const data = currentData();
  syncFieldSelectors(data);
  fidelityBadge.textContent = `${data.fidelity} · ${data.provenanceSource}`;
  statusLine.textContent = state.mode === "EDIT"
    ? `${loadedScenario.label}: editing canonical SCENARIO initial conditions. Loaded FRAME data is separate and is never mutated by editor or debug/optical display actions.`
    : `${loadedFrame.label}: canonical ${data.sourceKind} is read-only. Missing physics stays Unavailable; debug overlays and optical preview are never promoted to solver truth.`;
  renderSelection(data);
  renderSystem(data);
  renderDebugField(data);
  renderOptics(data);
  renderProvenance(data);
  renderEvents(data);
  scene.setData(data, state.selectedIds, state.selectedSurfaceId, display);
  updateButtons();
}

function fitAll() {
  const data = currentData(), visible = data.bubbles.filter((bubble) => bubble.visible);
  const spheres = visible.map((bubble) => ({ center: bubble.position, radius: bubble.displayRadius }));
  if (spheres.length === 0) for (const mesh of data.surfaceMeshes) if (mesh.vertices) for (const point of mesh.vertices) spheres.push({ center: point, radius: 0 });
  const fit = fitSpheres(spheres); scene.setCamera(fit.target, fit.distance);
}

function focusSelected() {
  const data = currentData();
  if (state.selectedSurfaceId?.startsWith("junction:")) {
    const id = state.selectedSurfaceId.slice("junction:".length);
    const junction = data.junctions.find((candidate) => candidate.id === id);
    if (!junction?.points?.length) return;
    const fit = fitSpheres(junction.points.map((point) => ({ center: point, radius: 0 })));
    scene.setCamera(fit.target, fit.distance); return;
  }
  if (state.selectedSurfaceId) {
    const surface = data.surfaceMeshes.find((mesh) => mesh.id === state.selectedSurfaceId);
    if (!surface?.vertices?.length) return;
    const fit = fitSpheres(surface.vertices.map((point) => ({ center: point, radius: 0 })));
    scene.setCamera(fit.target, fit.distance); return;
  }
  const selected = data.bubbles.filter((bubble) => state.selectedIds.has(bubble.id) && bubble.visible);
  if (!selected.length) return;
  const fit = fitSpheres(selected.map((bubble) => ({ center: bubble.position, radius: bubble.displayRadius })));
  scene.setCamera(fit.target, fit.distance);
}

function enterReplay() { if (state.mode !== "REPLAY") state = setMode(state, "REPLAY"); }
function numericInput(input: HTMLInputElement): number | null {
  if (input.value.trim() === "") return null;
  const value = Number(input.value);
  return Number.isFinite(value) ? value : null;
}

async function bootstrap() {
  [loadedScenario, loadedFrame] = await Promise.all([loadCanonicalScenarioFixture(), loadCanonicalFrameFixture(frameFixtureDefinitions[0]!.id)]);
  state = createViewerState(loadedScenario.document); replay = createReplay([loadedFrame.document]);
  fixtureSelect.value = frameFixtureDefinitions[0]!.id;
  applyResponsiveLayout();
  window.addEventListener("resize", applyResponsiveLayout);
  inspectorToggle.addEventListener("click", () => {
    inspector.classList.toggle("mobile-collapsed");
    inspectorToggle.setAttribute("aria-expanded", String(!inspector.classList.contains("mobile-collapsed")));
  });
  fixtureSelect.addEventListener("change", async () => {
    loadedFrame = await loadCanonicalFrameFixture(fixtureSelect.value);
    replay = createReplay([loadedFrame.document]);
    fieldSignature = "";
    if (state.mode === "REPLAY") {
      state = { ...state, selectedIds: new Set<string>(), selectedSurfaceId: null };
      refresh(); fitAll();
    }
  });
  runtimeBundleInput.addEventListener("change", async () => {
    if (!runtimeBundleInput.files?.length) return;
    try {
      const loaded = await loadReplayBundleFromFiles(runtimeBundleInput.files);
      replay = loaded.replay;
      loadedFrame = {
        document: loaded.frames[0]!,
        provenanceSource: "SOLVER",
        label: `Runtime bundle: ${loaded.index.scenario.id} / ${loaded.index.backend.identity} ${loaded.index.backend.version}`,
      };
      state = setMode(state, "REPLAY");
      state = { ...state, selectedIds: new Set<string>(), selectedSurfaceId: null };
      fieldSignature = "";
      refresh(); fitAll();
    } catch (error) {
      statusLine.textContent = `Runtime bundle load failed: ${error instanceof Error ? error.message : String(error)}`;
    } finally {
      runtimeBundleInput.value = "";
    }
  });

  document.querySelector("#mode-edit")?.addEventListener("click", () => { replay = pauseReplay(replay); state = setMode(state, "EDIT"); fieldSignature = ""; refresh(); fitAll(); });
  document.querySelector("#mode-replay")?.addEventListener("click", () => { state = setMode(state, "REPLAY"); fieldSignature = ""; refresh(); fitAll(); });
  replayPlay.addEventListener("click", () => { enterReplay(); replay = replay.playing ? pauseReplay(replay) : playReplay(replay); refresh(); });
  document.querySelector("#replay-back")?.addEventListener("click", () => { enterReplay(); replay = pauseReplay(stepReplay(replay, -1)); fieldSignature = ""; refresh(); fitAll(); });
  document.querySelector("#replay-forward")?.addEventListener("click", () => { enterReplay(); replay = pauseReplay(stepReplay(replay, 1)); fieldSignature = ""; refresh(); fitAll(); });
  document.querySelector("#replay-reset")?.addEventListener("click", () => { enterReplay(); replay = resetReplay(replay); fieldSignature = ""; refresh(); fitAll(); });
  document.querySelector("#add-toggle")?.addEventListener("click", () => { state = setAddMode(state, !state.addMode); refresh(); });
  document.querySelector("#delete-selected")?.addEventListener("click", () => { state = deleteSelected(state); refresh(); });
  document.querySelector("#delete-all")?.addEventListener("click", () => {
    if (state.editorScenario.initial_bubbles.length === 0 || !confirm("Delete every bubble from the editable SCENARIO initial state?")) return;
    state = deleteAll(state); refresh();
  });
  document.querySelector("#burst-request")?.addEventListener("click", () => {
    const ids = [...state.selectedIds];
    statusLine.textContent = ids.length
      ? `Burst request emitted for ${ids.join(", ")}. No visual rupture was fabricated.`
      : "Select one or more bubbles before requesting burst.";
    window.dispatchEvent(new CustomEvent("bubblelab:burst-request", { detail: { bubbleIds: ids, sourceKind: currentData().sourceKind } }));
  });
  document.querySelector("#focus-selected")?.addEventListener("click", focusSelected);
  document.querySelector("#fit-all")?.addEventListener("click", fitAll);

  document.querySelector<HTMLSelectElement>("#film-visibility")?.addEventListener("change", (event) => {
    display = { ...display, filmMode: (event.target as HTMLSelectElement).value as FilmVisibilityMode }; refresh();
  });
  for (const [id, key] of [
    ["show-canonical", "showCanonicalMesh"],
    ["show-fallback", "showSphereFallback"],
    ["show-faces", "showFaces"],
    ["wireframe", "wireframe"],
    ["show-vertices", "showVertices"],
    ["show-vertex-normals", "showVertexNormals"],
    ["show-face-normals", "showFaceNormals"],
    ["show-junctions", "showJunctions"],
  ] as const) {
    document.querySelector<HTMLInputElement>(`#${id}`)?.addEventListener("change", (event) => {
      display = { ...display, [key]: (event.target as HTMLInputElement).checked }; refresh();
    });
  }

  document.querySelector<HTMLSelectElement>("#interference-mode")?.addEventListener("change", (event) => {
    display = { ...display, interferenceMode: (event.target as HTMLSelectElement).value as DisplayOptions["interferenceMode"] }; refresh();
  });
  previewThicknessInput.addEventListener("input", () => {
    const value = Number(previewThicknessInput.value);
    display = { ...display, visualPreviewThicknessNm: Number.isFinite(value) ? Math.max(0, value) : 0 }; refresh();
  });
  scalarSelect.addEventListener("change", () => { display = { ...display, scalarChannel: scalarSelect.value }; refresh(); });
  scalarRangeMode.addEventListener("change", () => {
    display = { ...display, scalarRangeMode: scalarRangeMode.value as DisplayOptions["scalarRangeMode"] }; refresh();
  });
  scalarMinInput.addEventListener("input", () => { display = { ...display, scalarMin: numericInput(scalarMinInput) }; refresh(); });
  scalarMaxInput.addEventListener("input", () => { display = { ...display, scalarMax: numericInput(scalarMaxInput) }; refresh(); });
  scalarDivergingInput.addEventListener("change", () => { display = { ...display, scalarDiverging: scalarDivergingInput.checked }; refresh(); });
  vectorSelect.addEventListener("change", () => { display = { ...display, vectorChannel: vectorSelect.value }; refresh(); });
  vectorGlyphCountInput.addEventListener("input", () => {
    const value = Math.round(Number(vectorGlyphCountInput.value));
    display = { ...display, vectorGlyphCount: Number.isFinite(value) ? Math.max(1, Math.min(2000, value)) : 120 }; refresh();
  });
  vectorScaleInput.addEventListener("input", () => {
    const value = Number(vectorScaleInput.value);
    display = { ...display, vectorScale: Number.isFinite(value) ? Math.max(0, value) : 1 }; refresh();
  });
  vectorNormalizeInput.addEventListener("change", () => { display = { ...display, vectorNormalize: vectorNormalizeInput.checked }; refresh(); });
  qualityModeSelect.addEventListener("change", (event) => {
    display = { ...display, qualityMode: (event.target as HTMLSelectElement).value as RenderQualityMode }; refresh();
  });

  window.setInterval(() => {
    if (!replay.playing) return;
    const before = replay.index, next = stepReplay(replay, 1);
    replay = next.index === before ? pauseReplay(next) : next;
    if (state.mode === "REPLAY") { fieldSignature = ""; refresh(); fitAll(); }
  }, 750);
  refresh(); fitAll();
}

function fpsLoop(now: number) {
  renderedFrames += 1;
  const elapsed = now - fpsMark;
  if (elapsed >= 500) {
    fps = renderedFrames * 1000 / elapsed;
    renderedFrames = 0; fpsMark = now;
    if (typeof state !== "undefined") renderSystem(currentData());
  }
  requestAnimationFrame(fpsLoop);
}
requestAnimationFrame(fpsLoop);
bootstrap().catch((error) => {
  statusLine.textContent = `Viewer startup failed: ${error instanceof Error ? error.message : String(error)}`;
  console.error(error);
});
