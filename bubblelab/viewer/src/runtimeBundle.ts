import { parseContractFrame } from "./contract.js";
import { createReplay, type ReplayState } from "./replay.js";
import type { ContractFrame, FeatureDisclosureStatus } from "./types.js";

export interface ReplayFrameRef { frame_id: string; path: string; simulation_time_s: number; }
export interface ReplayBundleIndex {
  bundle_version: "1.0.0";
  contract_version: "1.0.0";
  scenario: { id: string; sha256: string };
  backend: { identity: string; version: string; [key: string]: unknown };
  random_seed: number;
  frames: readonly ReplayFrameRef[];
  checkpoints: readonly unknown[];
  provenance: { producer: string; source_scenario: string; [key: string]: unknown };
  fidelity: { requested: string; produced: string; feature_disclosures: Record<string, FeatureDisclosureStatus>; [key: string]: unknown };
  [key: string]: unknown;
}
export interface LoadedReplayBundle { index: ReplayBundleIndex; frames: readonly ContractFrame[]; replay: ReplayState; }

function record(value: unknown, label: string): Record<string, unknown> {
  if (typeof value !== "object" || value === null || Array.isArray(value)) throw new Error(`${label} must be an object`);
  return value as Record<string, unknown>;
}
function safeRelative(path: unknown): string {
  if (typeof path !== "string" || !path || path.startsWith("/") || path.includes("\\") || path.split("/").some((part) => part === ".." || part === "")) {
    throw new Error(`Unsafe replay bundle path: ${String(path)}`);
  }
  return path;
}
export function parseReplayBundleIndex(value: unknown): ReplayBundleIndex {
  const index=record(value,"replay.json");
  if(index.bundle_version!=="1.0.0") throw new Error(`Unsupported replay bundle version: ${String(index.bundle_version)}`);
  if(index.contract_version!=="1.0.0") throw new Error(`Unsupported Bubble Lab contract version: ${String(index.contract_version)}`);
  const scenario=record(index.scenario,"scenario"), backend=record(index.backend,"backend"), provenance=record(index.provenance,"provenance");
  if(typeof scenario.id!=="string"||!scenario.id) throw new Error("scenario.id is required");
  if(typeof backend.identity!=="string"||typeof backend.version!=="string") throw new Error("backend identity/version are required");
  if(typeof provenance.producer!=="string") throw new Error("provenance.producer is required");
  if(!Number.isInteger(index.random_seed)||(index.random_seed as number)<0) throw new Error("random_seed must be a non-negative integer");
  if(!Array.isArray(index.frames)||index.frames.length===0) throw new Error("frames must be a non-empty array");
  const seen=new Set<string>(); let last=-Infinity;
  for(const [i,item] of index.frames.entries()){
    const ref=record(item,`frames[${i}]`);
    if(typeof ref.frame_id!=="string"||!ref.frame_id) throw new Error(`frames[${i}].frame_id is required`);
    if(seen.has(ref.frame_id)) throw new Error(`duplicate frame ID: ${ref.frame_id}`); seen.add(ref.frame_id);
    safeRelative(ref.path);
    if(typeof ref.simulation_time_s!=="number"||!Number.isFinite(ref.simulation_time_s)||ref.simulation_time_s<last) throw new Error("simulation time must be nondecreasing");
    last=ref.simulation_time_s;
  }
  return value as ReplayBundleIndex;
}
export async function loadReplayBundle(indexValue: unknown, readJson: (relativePath: string)=>Promise<unknown>): Promise<LoadedReplayBundle> {
  const index=parseReplayBundleIndex(indexValue); const frames: ContractFrame[]=[];
  for(const ref of index.frames){
    const frame=parseContractFrame(await readJson(safeRelative(ref.path)));
    if(frame.kind!=="FRAME") throw new Error(`${ref.path} is not a FRAME`);
    if(frame.frame_id!==ref.frame_id) throw new Error(`frame ID mismatch for ${ref.path}`);
    if(frame.simulation_time_s!==ref.simulation_time_s) throw new Error(`simulation time mismatch for ${ref.path}`);
    if(frame.manifest.random_seed!==index.random_seed) throw new Error(`random seed mismatch for ${ref.path}`);
    if(frame.manifest.solver.backend!==index.backend.identity) throw new Error(`backend mismatch for ${ref.path}`);
    if(frame.manifest.provenance.source_scenario!==index.scenario.id) throw new Error(`scenario provenance mismatch for ${ref.path}`);
    frames.push(frame);
  }
  return {index,frames,replay:createReplay(frames)};
}
export async function loadReplayBundleFromFiles(files: FileList): Promise<LoadedReplayBundle> {
  const all=[...files]; const replayFile=all.find((file)=>file.name==="replay.json");
  if(!replayFile) throw new Error("Selected folder does not contain replay.json");
  const root=replayFile.webkitRelativePath ? replayFile.webkitRelativePath.slice(0,-"replay.json".length) : "";
  const byRelative=new Map<string,File>();
  for(const file of all){
    const rel=file.webkitRelativePath.startsWith(root)?file.webkitRelativePath.slice(root.length):file.name;
    byRelative.set(rel,file);
  }
  const parseFile=async(file:File)=>JSON.parse(await file.text()) as unknown;
  const indexValue=await parseFile(replayFile);
  return loadReplayBundle(indexValue,async(path)=>{
    const file=byRelative.get(path); if(!file) throw new Error(`Missing replay frame: ${path}`);
    return parseFile(file);
  });
}
