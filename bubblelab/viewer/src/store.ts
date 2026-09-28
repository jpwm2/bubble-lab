import type { ContractBubble, ContractScenario, Vec3, ViewerMode, ViewerState } from "./types.js";
export interface AddBubbleInput { position: Vec3; radius: number; velocity?: Vec3; }
export type ViewerStateListener = (state: ViewerState) => void;

let latestState: ViewerState | null = null;
const listeners = new Set<ViewerStateListener>();

function publish(state: ViewerState): ViewerState {
  latestState = state;
  for (const listener of listeners) listener(state);
  return state;
}

export function getLatestViewerState(): ViewerState | null { return latestState; }
export function subscribeViewerState(listener: ViewerStateListener): () => void {
  listeners.add(listener);
  if (latestState) listener(latestState);
  return () => listeners.delete(listener);
}

export function replaceEditorScenario(scenario: ContractScenario): ViewerState | null {
  if (!latestState) return null;
  latestState.editorScenario = structuredClone(scenario);
  latestState.mode = "EDIT";
  latestState.addMode = false;
  latestState.selectedIds = new Set<string>();
  latestState.selectedSurfaceId = null;
  latestState.nextEditorId = nextEditorNumber(latestState.editorScenario);
  return publish(latestState);
}

function nextEditorNumber(scenario: ContractScenario): number {
  const ids = new Set(scenario.initial_bubbles.map((bubble) => bubble.id));
  let n = 1; while (ids.has(`editor-${n}`)) n += 1; return n;
}
export function createViewerState(scenario: ContractScenario): ViewerState {
  const editorScenario = structuredClone(scenario);
  return publish({ mode: "EDIT", editorScenario, selectedIds: new Set<string>(), selectedSurfaceId: null, addMode: false, nextEditorId: nextEditorNumber(editorScenario) });
}
export function setMode(state: ViewerState, mode: ViewerMode): ViewerState {
  return publish({ ...state, mode, addMode: mode === "EDIT" ? state.addMode : false, selectedIds: new Set<string>(), selectedSurfaceId: null });
}
export function setAddMode(state: ViewerState, enabled: boolean): ViewerState {
  if (state.mode !== "EDIT") return publish(state);
  return publish({ ...state, addMode: enabled, selectedIds: new Set(state.selectedIds), selectedSurfaceId: state.selectedSurfaceId });
}
export function selectBubble(state: ViewerState, id: string, additive = false): ViewerState {
  const selectedIds = additive ? new Set(state.selectedIds) : new Set<string>();
  if (additive && selectedIds.has(id)) selectedIds.delete(id); else selectedIds.add(id);
  return publish({ ...state, selectedIds, selectedSurfaceId: null });
}
export function selectSurface(state: ViewerState, id: string): ViewerState {
  return publish({ ...state, selectedIds: new Set<string>(), selectedSurfaceId: id });
}
export function clearSelection(state: ViewerState): ViewerState { return publish({ ...state, selectedIds: new Set<string>(), selectedSurfaceId: null }); }
export function addEditorBubble(state: ViewerState, input: AddBubbleInput): ViewerState {
  if (state.mode !== "EDIT") return publish(state);
  const id = `editor-${state.nextEditorId}`, volume = (4 / 3) * Math.PI * input.radius ** 3;
  const bubble: ContractBubble = {
    id, volume_m3: volume, equivalent_radius_m: input.radius, centroid_m: input.position,
    velocity_m_s: input.velocity ?? [0, 0, 0], status: "ALIVE",
  };
  return publish({
    ...state,
    editorScenario: { ...state.editorScenario, initial_bubbles: [...state.editorScenario.initial_bubbles, bubble] },
    selectedIds: new Set([id]), selectedSurfaceId: null, nextEditorId: state.nextEditorId + 1,
  });
}
export function deleteSelected(state: ViewerState): ViewerState {
  if (state.mode !== "EDIT" || state.selectedIds.size === 0) return publish(state);
  return publish({
    ...state,
    editorScenario: { ...state.editorScenario, initial_bubbles: state.editorScenario.initial_bubbles.filter((bubble) => !state.selectedIds.has(bubble.id)) },
    selectedIds: new Set<string>(), selectedSurfaceId: null,
  });
}
export function deleteAll(state: ViewerState): ViewerState {
  if (state.mode !== "EDIT") return publish(state);
  return publish({ ...state, editorScenario: { ...state.editorScenario, initial_bubbles: [] }, selectedIds: new Set<string>(), selectedSurfaceId: null });
}
