import { describe, expect, it } from "vitest";
import type { HardwareInfo, SpeakerAiStatus } from "../types";
import { buildAutomaticPlan } from "./automaticPlan";

const workstation: HardwareInfo = {
  cpu: { name: "Ryzen", physicalCores: 8, logicalCores: 16, usagePercent: 20 },
  memory: { totalMiB: 32_768, availableMiB: 24_000, usagePercent: 27 },
  gpu: { name: "RTX", totalVramMiB: 8_192, usedVramMiB: 500, utilizationPercent: 5 },
  cudaAvailable: true,
  recommendedProfile: "maximum",
};

const speakerAi: SpeakerAiStatus = {
  installed: true,
  ready: true,
  backend: "CAM++ · ONNX",
  model: "CAM++",
  path: "speaker.onnx",
  sizeBytes: 1,
  expectedBytes: 1,
  privacy: "local",
  preciseAvailable: false,
  notice: "Listo",
};

describe("piloto automático", () => {
  it("usa máxima fidelidad para un audio corto en un equipo potente", () => {
    const plan = buildAutomaticPlan(workstation, speakerAi, 8 * 60_000);

    expect(plan.tier).toBe("workstation");
    expect(plan.settings.qualityMode).toBe("maximum");
    expect(plan.settings.device).toBe("auto");
    expect(plan.settings.cpuThreads).toBe(16);
    expect(plan.settings.diarizationMode).toBe("neural");
    expect(plan.settings.speakerCountMode).toBe("auto");
    expect(plan.settings.speakerCount).toBe(8);
  });

  it("equilibra velocidad y calidad para una conversación larga", () => {
    const plan = buildAutomaticPlan(workstation, speakerAi, 90 * 60_000);

    expect(plan.settings.qualityMode).toBe("professional");
    expect(plan.settings.reviewLowConfidence).toBe(true);
    expect(plan.settings.batchSize).toBe(8);
  });

  it("protege la memoria de un equipo limitado sin desactivar voces", () => {
    const plan = buildAutomaticPlan({
      cpu: { name: "CPU", physicalCores: 2, logicalCores: 4, usagePercent: 30 },
      memory: { totalMiB: 8_192, availableMiB: 2_800, usagePercent: 66 },
      gpu: null,
      cudaAvailable: false,
      recommendedProfile: "performance",
    }, null, 60 * 60_000);

    expect(plan.tier).toBe("efficient");
    expect(plan.settings.qualityMode).toBe("instant");
    expect(plan.settings.performanceProfile).toBe("performance");
    expect(plan.settings.diarizationMode).toBe("adaptive");
    expect(plan.settings.speakerCountMode).toBe("auto");
    expect(plan.settings.liveLatency).toBe("stable");
  });
});
