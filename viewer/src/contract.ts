import type { ContractFrame, ContractScenario } from "./types.js";

function asRecord(value: unknown, label: string): Record<string, unknown> {
  if (typeof value !== "object" || value === null || Array.isArray(value)) throw new Error(`${label} must be an object`);
  return value as Record<string, unknown>;
}
function requireArray(record: Record<string, unknown>, key: string): void {
  if (!Array.isArray(record[key])) throw new Error(`${key} must be an array`);
}
function requireString(record: Record<string, unknown>, key: string): void {
  if (typeof record[key] !== "string" || record[key] === "") throw new Error(`${key} must be a non-empty string`);
}
function requireNumber(record: Record<string, unknown>, key: string): void {
  if (typeof record[key] !== "number" || !Number.isFinite(record[key])) throw new Error(`${key} must be a finite number`);
}
function requireContractV1(record: Record<string, unknown>): void {
  if (record.contract_version !== "1.0.0") throw new Error(`Unsupported Bubble Lab contract version: ${String(record.contract_version)}`);
}

export function parseContractFrame(value: unknown): ContractFrame {
  const frame = asRecord(value, "FRAME");
  requireContractV1(frame);
  if (frame.kind !== "FRAME" && frame.kind !== "CHECKPOINT") throw new Error(`Expected FRAME/CHECKPOINT, got ${String(frame.kind)}`);
  requireString(frame, "frame_id"); requireNumber(frame, "simulation_time_s");
  asRecord(frame.manifest, "manifest"); asRecord(frame.environment, "environment"); asRecord(frame.topology, "topology");
  requireArray(frame, "bubbles"); requireArray(frame, "surface_meshes"); requireArray(frame, "film_regions"); requireArray(frame, "junctions");
  const manifest = frame.manifest as Record<string, unknown>;
  requireContractV1(manifest); asRecord(manifest.feature_disclosures, "feature_disclosures"); asRecord(manifest.provenance, "manifest.provenance");
  return value as ContractFrame;
}

export function parseContractScenario(value: unknown): ContractScenario {
  const scenario = asRecord(value, "SCENARIO");
  requireContractV1(scenario);
  if (scenario.kind !== "SCENARIO") throw new Error(`Expected SCENARIO, got ${String(scenario.kind)}`);
  requireString(scenario, "scenario_id");
  if (!Number.isInteger(scenario.random_seed) || (scenario.random_seed as number) < 0) throw new Error("random_seed must be a non-negative integer");
  asRecord(scenario.environment, "environment"); asRecord(scenario.user_editable, "user_editable"); requireArray(scenario, "initial_bubbles");
  return value as ContractScenario;
}
