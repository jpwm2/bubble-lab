import type { ContractFrame } from "./types.js";

export interface ReplayState { frames: readonly ContractFrame[]; index: number; playing: boolean; }

export function createReplay(frames: readonly ContractFrame[]): ReplayState {
  if (frames.length === 0) throw new Error("Replay requires at least one frame");
  const ordered = frames.map((frame, inputOrder) => ({ frame, inputOrder })).sort((a, b) =>
    a.frame.simulation_time_s - b.frame.simulation_time_s || a.frame.frame_id.localeCompare(b.frame.frame_id) || a.inputOrder - b.inputOrder,
  ).map(({ frame }) => frame);
  return { frames: ordered, index: 0, playing: false };
}
export function currentReplayFrame(state: ReplayState): ContractFrame { return state.frames[state.index]!; }
export function currentReplayTime(state: ReplayState): number { return currentReplayFrame(state).simulation_time_s; }
export function playReplay(state: ReplayState): ReplayState { return { ...state, playing: true }; }
export function pauseReplay(state: ReplayState): ReplayState { return { ...state, playing: false }; }
export function stepReplay(state: ReplayState, delta: -1 | 1): ReplayState {
  const index = Math.max(0, Math.min(state.frames.length - 1, state.index + delta));
  return { ...state, index };
}
export function selectReplayFrame(state: ReplayState, index: number): ReplayState {
  const clamped = Math.max(0, Math.min(state.frames.length - 1, Math.trunc(index)));
  return { ...state, index: clamped };
}
export function resetReplay(state: ReplayState): ReplayState { return { ...state, index: 0, playing: false }; }
