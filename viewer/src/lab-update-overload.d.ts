import type { ContractScenario, Vec3 } from "./types.js";
import "./lab.js";

declare module "./lab.js" {
  export function updateBubble(
    scenario: ContractScenario,
    bubbleId: string,
    patch: {
      equivalentRadiusM?: number | undefined;
      positionM?: Vec3 | undefined;
      velocityMS?: Vec3 | undefined;
      pressurePa?: number | null | undefined;
      temperatureK?: number | null | undefined;
      gasAmountMol?: number | null | undefined;
      gasSpecies?: string | null | undefined;
    },
  ): ContractScenario;
}
