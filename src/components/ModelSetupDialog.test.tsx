// @vitest-environment jsdom
import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { EngineEvent, HardwareInfo, ModelCatalog, SpeakerAiStatus } from "../types";
import { ModelSetupDialog } from "./ModelSetupDialog";

const mock = vi.hoisted(() => {
  const listeners = new Set<(event: EngineEvent) => void>();
  return {
    listeners,
    emit(event: EngineEvent) {
      for (const listener of [...listeners]) listener(event);
    },
    listModels: vi.fn(),
    getHardwareInfo: vi.fn(),
    getSpeakerAiStatus: vi.fn(),
    downloadModel: vi.fn(),
    cancelModelDownload: vi.fn(),
    installSpeakerAi: vi.fn(),
    cancelSpeakerAiDownload: vi.fn(),
  };
});

vi.mock("../lib/engine", () => ({
  engine: {
    available: true,
    listModels: mock.listModels,
    getHardwareInfo: mock.getHardwareInfo,
    getSpeakerAiStatus: mock.getSpeakerAiStatus,
    downloadModel: mock.downloadModel,
    cancelModelDownload: mock.cancelModelDownload,
    installSpeakerAi: mock.installSpeakerAi,
    cancelSpeakerAiDownload: mock.cancelSpeakerAiDownload,
    subscribe: (listener: (event: EngineEvent) => void) => {
      mock.listeners.add(listener);
      return () => mock.listeners.delete(listener);
    },
  },
}));

const GIB = 1024 ** 3;
const modelCatalog: ModelCatalog = {
  root: "C:\\Users\\test\\AppData\\Local\\Transcriptor\\models",
  freeBytes: 40 * GIB,
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
      downloadBytes: 1.6 * GIB,
      paths: [],
    },
    {
      id: "large-v3",
      name: "Large-v3",
      sizeGiB: 3.1,
      memoryGiB: 6,
      speed: "Exigente",
      accuracy: "Máxima",
      description: "Revisión profesional",
      installed: false,
      installedBytes: 0,
      downloadBytes: 3.1 * GIB,
      paths: [],
    },
  ],
};
const hardware: HardwareInfo = {
  cpu: { name: "CPU de prueba", physicalCores: 8, logicalCores: 16, usagePercent: 10 },
  memory: { totalMiB: 16 * 1024, availableMiB: 12 * 1024, usagePercent: 25 },
  gpu: {
    name: "GPU de prueba",
    totalVramMiB: 8192,
    usedVramMiB: 256,
    utilizationPercent: 5,
  },
  cudaAvailable: true,
  recommendedProfile: "maximum",
};
const speakerAi: SpeakerAiStatus = {
  installed: false,
  ready: false,
  backend: "spectral",
  model: "CAM++",
  path: "",
  sizeBytes: 0,
  expectedBytes: 28_281_164,
  privacy: "local",
  preciseAvailable: false,
  notice: "Pendiente",
};

beforeEach(() => {
  mock.listeners.clear();
  mock.listModels.mockReset().mockResolvedValue(modelCatalog);
  mock.getHardwareInfo.mockReset().mockResolvedValue(hardware);
  mock.getSpeakerAiStatus.mockReset().mockResolvedValue(speakerAi);
  mock.downloadModel.mockReset().mockResolvedValue({ accepted: true });
  mock.cancelModelDownload.mockReset().mockResolvedValue({ cancelled: true });
  mock.installSpeakerAi.mockReset().mockResolvedValue({ accepted: true });
  mock.cancelSpeakerAiDownload.mockReset().mockResolvedValue({ cancelled: true });
  localStorage.clear();
});

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

async function beginSetup() {
  await screen.findByText("Calidad profesional");
  fireEvent.click(screen.getByRole("checkbox"));
  fireEvent.click(screen.getByRole("button", { name: /Descargar y preparar/i }));
  await waitFor(() => expect(mock.downloadModel).toHaveBeenCalledWith("turbo"));
}

describe("preparación inicial de modelos", () => {
  it("instala secuencialmente Turbo, Large-v3 y CAM++ con un único consentimiento", async () => {
    const onComplete = vi.fn();
    const confirm = vi.spyOn(window, "confirm");
    render(<ModelSetupDialog onComplete={onComplete} onLater={() => undefined} />);
    await screen.findByText(/Autorizo esta descarga única de 5\.2 GB/i);
    await beginSetup();

    act(() => mock.emit({
      type: "model_manager_progress",
      payload: { modelId: "turbo", percent: 35, message: "0.6 GB de 1.6 GB" },
    }));
    await screen.findByText("35 %");
    act(() => mock.emit({
      type: "model_manager_completed",
      payload: { modelId: "turbo" },
    }));
    await waitFor(() => expect(mock.downloadModel).toHaveBeenCalledWith("large-v3"));

    act(() => mock.emit({
      type: "model_manager_completed",
      payload: { modelId: "large-v3" },
    }));
    await waitFor(() => expect(mock.installSpeakerAi).toHaveBeenCalledOnce());

    act(() => mock.emit({
      type: "speaker_model_completed",
      payload: { ...speakerAi, installed: true, ready: true },
    }));

    await screen.findByText("Todo preparado correctamente");
    expect(mock.downloadModel.mock.calls.map((call) => call[0])).toEqual(["turbo", "large-v3"]);
    expect(localStorage.getItem("transcriptor.model-consent.turbo+large-v3")).toBe("accepted");
    fireEvent.click(screen.getByRole("button", { name: /Empezar a usar/i }));
    expect(onComplete).toHaveBeenCalledWith({
      qualityMode: "professional",
      speakerAiReady: true,
    });
    expect(confirm).not.toHaveBeenCalled();
  });

  it("muestra el fallo y permite reintentar la preparación", async () => {
    render(<ModelSetupDialog onComplete={() => undefined} onLater={() => undefined} />);
    await beginSetup();

    act(() => mock.emit({
      type: "model_manager_failed",
      payload: { modelId: "turbo", message: "Conexión interrumpida" },
    }));

    await screen.findByText("Conexión interrumpida");
    fireEvent.click(screen.getByRole("button", { name: /Descargar y preparar/i }));
    await waitFor(() => expect(mock.downloadModel).toHaveBeenCalledTimes(2));
  });

  it("permite cancelar CAM++ sin iniciar otra descarga", async () => {
    render(<ModelSetupDialog onComplete={() => undefined} onLater={() => undefined} />);
    await beginSetup();

    act(() => mock.emit({
      type: "model_manager_completed",
      payload: { modelId: "turbo" },
    }));
    await waitFor(() => expect(mock.downloadModel).toHaveBeenCalledWith("large-v3"));
    act(() => mock.emit({
      type: "model_manager_completed",
      payload: { modelId: "large-v3" },
    }));
    await waitFor(() => expect(mock.installSpeakerAi).toHaveBeenCalledOnce());

    fireEvent.click(screen.getByRole("button", { name: /Cancelar CAM\+\+/i }));
    await waitFor(() => expect(mock.cancelSpeakerAiDownload).toHaveBeenCalledOnce());
    act(() => mock.emit({
      type: "speaker_model_cancelled",
      payload: {},
    }));

    await screen.findByText("Se canceló la instalación de CAM++.");
    expect(mock.downloadModel.mock.calls.map((call) => call[0])).toEqual(["turbo", "large-v3"]);
  });
});
