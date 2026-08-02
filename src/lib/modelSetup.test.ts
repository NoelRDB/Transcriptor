import { describe, expect, it } from "vitest";
import type { CudaRuntimeStatus, HardwareInfo, ModelCatalog } from "../types";
import {
  buildRecommendedModelSetup,
  hasReadyCoreModel,
  SPEAKER_MODEL_BYTES,
} from "./modelSetup";

const GIB = 1024 ** 3;

function catalog(freeBytes = 20 * GIB): ModelCatalog {
  return {
    root: "C:\\models",
    freeBytes,
    models: [
      {
        id: "turbo",
        name: "Turbo",
        sizeGiB: 1.6,
        memoryGiB: 4,
        speed: "Rápida",
        accuracy: "Muy buena",
        description: "Primera pasada",
        installed: false,
        installedBytes: 0,
        paths: [],
        integrity: "missing",
        downloadBytes: 1.6 * GIB,
        canInstall: true,
      },
      {
        id: "large-v3",
        name: "Large-v3",
        sizeGiB: 3.1,
        memoryGiB: 6,
        speed: "Exigente",
        accuracy: "Máxima",
        description: "Revisión",
        installed: false,
        installedBytes: 0,
        paths: [],
        integrity: "missing",
        downloadBytes: 3.1 * GIB,
        canInstall: true,
      },
    ],
  };
}

function hardware(totalMiB: number): HardwareInfo {
  return {
    cpu: { name: "CPU", physicalCores: 4, logicalCores: 8, usagePercent: 0 },
    memory: { totalMiB, availableMiB: totalMiB / 2, usagePercent: 50 },
    gpu: null,
    cudaAvailable: false,
    recommendedProfile: "balanced",
  };
}

function cudaStatus(): CudaRuntimeStatus {
  return {
    id: "cuda-runtime",
    supported: true,
    installed: false,
    ready: false,
    source: "missing",
    root: "C:\\TranscriptorData\\runtime\\cuda",
    downloadBytes: 1_285_431_644,
    requiredFreeBytes: 1_822_302_556,
    freeBytes: 20 * GIB,
    canInstall: true,
    missingFiles: ["cublas64_12.dll", "cublasLt64_12.dll", "cudnn64_9.dll"],
    packages: [],
  };
}

describe("preparación recomendada de modelos", () => {
  it("elige Turbo, Large-v3 y CAM++ con memoria y espacio suficientes", () => {
    const plan = buildRecommendedModelSetup(catalog(), hardware(16 * 1024), false);

    expect(plan.models.map((model) => model.id)).toEqual(["turbo", "large-v3"]);
    expect(plan.qualityMode).toBe("professional");
    expect(plan.includesSpeakerAi).toBe(true);
    expect(plan.requiredBytes).toBeGreaterThan(4.7 * GIB + SPEAKER_MODEL_BYTES);
    expect(plan.canInstall).toBe(true);
  });

  it("reduce el paquete a Turbo en equipos con poca memoria", () => {
    const plan = buildRecommendedModelSetup(catalog(), hardware(6 * 1024), false);

    expect(plan.models.map((model) => model.id)).toEqual(["turbo"]);
    expect(plan.qualityMode).toBe("instant");
  });

  it("usa la opción conservadora si no puede medir el hardware", () => {
    const plan = buildRecommendedModelSetup(catalog(), null, false);

    expect(plan.models.map((model) => model.id)).toEqual(["turbo"]);
    expect(plan.reason).toContain("No se pudo medir la memoria");
  });

  it("bloquea el inicio antes de descargar cuando falta espacio", () => {
    const plan = buildRecommendedModelSetup(
      catalog(900 * 1024 ** 2),
      hardware(16 * 1024),
      false,
    );

    expect(plan.models.map((model) => model.id)).toEqual(["turbo"]);
    expect(plan.canInstall).toBe(false);
    expect(plan.requiredBytes).toBeGreaterThan(plan.freeBytes);
  });

  it("sólo considera listo un Turbo completo", () => {
    const partial = catalog();
    partial.models[0] = {
      ...partial.models[0],
      installed: true,
      integrity: "partial",
    };
    expect(hasReadyCoreModel(partial)).toBe(false);

    partial.models[0] = { ...partial.models[0], integrity: "ready" };
    expect(hasReadyCoreModel(partial)).toBe(true);
  });

  it("añade CUDA al consentimiento sólo cuando hay una NVIDIA sin runtime", () => {
    const gpuHardware: HardwareInfo = {
      ...hardware(16 * 1024),
      gpu: {
        name: "NVIDIA RTX",
        totalVramMiB: 8192,
        usedVramMiB: 0,
        utilizationPercent: 0,
      },
    };
    const withoutCuda = buildRecommendedModelSetup(
      catalog(),
      gpuHardware,
      false,
      cudaStatus(),
      true,
    );
    const cpuOnly = buildRecommendedModelSetup(
      catalog(),
      gpuHardware,
      false,
      cudaStatus(),
    );
    const withCuda = buildRecommendedModelSetup(
      catalog(),
      gpuHardware,
      false,
      { ...cudaStatus(), installed: true, ready: true, source: "managed" },
      true,
    );

    expect(withoutCuda.includesCudaRuntime).toBe(true);
    expect(cpuOnly.includesCudaRuntime).toBe(false);
    expect(cpuOnly.canInstall).toBe(true);
    expect(withoutCuda.downloadBytes).toBeGreaterThan(
      withCuda.downloadBytes + 1_200_000_000,
    );
    expect(withoutCuda.reason).toContain("GPU NVIDIA");
    expect(withCuda.includesCudaRuntime).toBe(false);
  });
});
