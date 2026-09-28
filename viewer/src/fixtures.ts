import { parseContractFrame, parseContractScenario } from "./contract.js";
import type { LoadedContractFrame, LoadedContractScenario } from "./types.js";

export const frameFixtureDefinitions = [
  { id: "single-isolated", label: "Canonical: single bubble", file: "single-isolated.frame.json" },
  { id: "two-touching", label: "Canonical: shared film", file: "two-touching.frame.json" },
  { id: "three-plateau", label: "Canonical: Plateau junction", file: "three-plateau.frame.json" },
  { id: "rupture-coalescence-history", label: "Canonical: event history", file: "rupture-coalescence-history.frame.json" },
] as const;
export const scenarioFixtureDefinition = { id: "single-editable", label: "Canonical editable scenario", file: "single-editable.scenario.json" } as const;

async function loadJson(path: string): Promise<unknown> {
  const response = await fetch(path, { cache: "no-store" });
  if (!response.ok) throw new Error(`Failed to load ${path}: HTTP ${response.status}`);
  return response.json() as Promise<unknown>;
}
export async function loadCanonicalFrameFixture(id: string): Promise<LoadedContractFrame> {
  const definition = frameFixtureDefinitions.find((fixture) => fixture.id === id);
  if (!definition) throw new Error(`Unknown canonical frame fixture: ${id}`);
  return { document: parseContractFrame(await loadJson(`./fixtures/${definition.file}`)), provenanceSource: "TEST_FIXTURE", label: definition.label };
}
export async function loadCanonicalScenarioFixture(): Promise<LoadedContractScenario> {
  return { document: parseContractScenario(await loadJson(`./fixtures/${scenarioFixtureDefinition.file}`)), provenanceSource: "TEST_FIXTURE", label: scenarioFixtureDefinition.label };
}
