// @vitest-environment jsdom
import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type {
  CudaRuntimeStatus,
  EngineEvent,
  HardwareInfo,
  ModelCatalog,
  SpeakerAiStatus,
} from "../types";
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
    getCudaRuntimeStatus: vi.fn(),
    getSpeakerAiStatus: vi.fn(),
    downloadModel: vi.fn(),
    cancelModelDownload: vi.fn(),
    installCudaRuntime: vi.fn(),
    cancelCudaRuntimeDownload: vi.fn(),
    installSpeakerAi: vi.fn(),
    cancelSpeakerAiDownload: vi.fn(),
  };
});

vi.mock("../lib/engine", () => ({
  engine: {
    available: true,
    listModels: mock.listModels,
    getHardwareInfo: mock.getHardwareInfo,
    getCudaRuntimeStatus: mock.getCudaRuntimeStatus,
    getSpeakerAiStatus: mock.getSpeakerAiStatus,
    downloadModel: mock.downloadModel,
    cancelModelDownload: mock.cancelModelDownload,
    installCudaRuntime: mock.installCudaRuntime,
    cancelCudaRuntimeDownload: mock.cancelCudaRuntimeDownload,
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
const cudaReady: CudaRuntimeStatus = {
  id: "cuda-runtime",
  supported: true,
  installed: true,
  ready: true,
  usable: true,
  source: "managed",
  root: "C:\\Users\\test\\AppData\\Local\\TranscriptorData\\runtime\\cuda",
  downloadBytes: 1_285_431_644,
  requiredFreeBytes: 1_822_302_556,
  freeBytes: 40 * GIB,
  canInstall: true,
  missingFiles: [],
  packages: [],
};
const cudaMissing: CudaRuntimeStatus = {
  ...cudaReady,
  installed: false,
  ready: false,
  usable: false,
  source: "missing",
  missingFiles: ["cublas64_12.dll", "cublasLt64_12.dll", "cudnn64_9.dll"],
};

beforeEach(() => {
  mock.listeners.clear();
  mock.listModels.mockReset().mockResolvedValue(modelCatalog);
  mock.getHardwareInfo.mockReset().mockResolvedValue(hardware);
  mock.getCudaRuntimeStatus.mockReset().mockResolvedValue(cudaReady);
  mock.getSpeakerAiStatus.mockReset().mockResolvedValue(speakerAi);
  mock.downloadModel.mockReset().mockResolvedValue({ accepted: true });
  mock.cancelModelDownload.mockReset().mockResolvedValue({ cancelled: true });
  mock.installCudaRuntime.mockReset().mockResolvedValue({ accepted: true });
  mock.cancelCudaRuntimeDownload.mockReset().mockResolvedValue({ cancelled: true });
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
  fireEvent.click(screen.getByRole("checkbox", { name: /Autorizo la descarga seleccionada/i }));
  fireEvent.click(screen.getByRole("button", { name: /Descargar y preparar/i }));
  await waitFor(() => expect(mock.downloadModel).toHaveBeenCalledWith("turbo"));
}

describe("preparación inicial de modelos", () => {
  it("instala secuencialmente Turbo, Large-v3 y CAM++ con un único consentimiento", async () => {
    const onComplete = vi.fn();
    const confirm = vi.spyOn(window, "confirm");
    render(<ModelSetupDialog onComplete={onComplete} onLater={() => undefined} />);
    await screen.findByText(/Autorizo la descarga seleccionada de 4\.7 GB/i);
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
      cudaReady: true,
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

  it("prepara CUDA con progreso real cuando detecta NVIDIA y no hay runtime", async () => {
    const readyCatalog: ModelCatalog = {
      ...modelCatalog,
      models: modelCatalog.models.map((model) => ({
        ...model,
        installed: true,
        integrity: "ready",
      })),
    };
    mock.listModels.mockResolvedValue(readyCatalog);
    mock.getSpeakerAiStatus.mockResolvedValue({
      ...speakerAi,
      installed: true,
      ready: true,
    });
    mock.getCudaRuntimeStatus
      .mockReset()
      .mockResolvedValueOnce(cudaMissing)
      .mockResolvedValue(cudaReady);

    render(<ModelSetupDialog onComplete={() => undefined} onLater={() => undefined} />);
    await screen.findByText(/NVIDIA y CTranslate2 GPU.*verificados por SHA-256/i);
    fireEvent.click(screen.getByRole("checkbox", { name: /Añadir aceleración NVIDIA/i }));
    fireEvent.click(screen.getByRole("checkbox", { name: /Autorizo la descarga seleccionada/i }));
    fireEvent.click(screen.getByRole("button", { name: /Descargar y preparar/i }));
    await waitFor(() => expect(mock.installCudaRuntime).toHaveBeenCalledOnce());

    act(() => mock.emit({
      type: "cuda_runtime_progress",
      payload: {
        runtimeId: "cuda-runtime",
        percent: 42,
        downloadedBytes: 540_000_000,
        totalBytes: cudaMissing.downloadBytes,
        message: "Descargando nvidia-cublas-cu12…",
      },
    }));
    await screen.findByText("42 %");
    await screen.findByText(/Descargando nvidia-cublas-cu12…/);

    act(() => mock.emit({
      type: "cuda_runtime_completed",
      payload: { ...cudaReady, runtimeId: "cuda-runtime", usable: true },
    }));
    await screen.findByText("Todo preparado correctamente");
    expect(localStorage.getItem("transcriptor.cuda-runtime-consent.v2")).toBe("accepted");
  });

  it("explica el fallback a CPU si CUDA se instala pero el controlador no puede activarla", async () => {
    const readyCatalog: ModelCatalog = {
      ...modelCatalog,
      models: modelCatalog.models.map((model) => ({
        ...model,
        installed: true,
        integrity: "ready",
      })),
    };
    const unusableCuda = { ...cudaReady, usable: false };
    const onComplete = vi.fn();
    mock.listModels.mockResolvedValue(readyCatalog);
    mock.getSpeakerAiStatus.mockResolvedValue({
      ...speakerAi,
      installed: true,
      ready: true,
    });
    mock.getCudaRuntimeStatus
      .mockReset()
      .mockResolvedValueOnce(cudaMissing)
      .mockResolvedValue(unusableCuda);

    render(<ModelSetupDialog onComplete={onComplete} onLater={() => undefined} />);
    await screen.findByText(/NVIDIA y CTranslate2 GPU.*verificados por SHA-256/i);
    fireEvent.click(screen.getByRole("checkbox", { name: /Añadir aceleración NVIDIA/i }));
    fireEvent.click(screen.getByRole("checkbox", { name: /Autorizo la descarga seleccionada/i }));
    fireEvent.click(screen.getByRole("button", { name: /Descargar y preparar/i }));
    await waitFor(() => expect(mock.installCudaRuntime).toHaveBeenCalledOnce());

    act(() => mock.emit({
      type: "cuda_runtime_completed",
      payload: { ...unusableCuda, runtimeId: "cuda-runtime" },
    }));

    await screen.findByText(/CPU activa por incompatibilidad local/i);
    fireEvent.click(screen.getByRole("button", { name: /Empezar a usar Transcriptor/i }));
    expect(onComplete).toHaveBeenCalledWith(expect.objectContaining({ cudaReady: false }));
  });

  it("cancela CUDA de forma explícita y permite reintentarlo", async () => {
    const readyCatalog: ModelCatalog = {
      ...modelCatalog,
      models: modelCatalog.models.map((model) => ({
        ...model,
        installed: true,
        integrity: "ready",
      })),
    };
    mock.listModels.mockResolvedValue(readyCatalog);
    mock.getSpeakerAiStatus.mockResolvedValue({
      ...speakerAi,
      installed: true,
      ready: true,
    });
    mock.getCudaRuntimeStatus.mockReset().mockResolvedValue(cudaMissing);

    render(<ModelSetupDialog onComplete={() => undefined} onLater={() => undefined} />);
    await screen.findByText(/NVIDIA y CTranslate2 GPU.*verificados por SHA-256/i);
    fireEvent.click(screen.getByRole("checkbox", { name: /Añadir aceleración NVIDIA/i }));
    fireEvent.click(screen.getByRole("checkbox", { name: /Autorizo la descarga seleccionada/i }));
    fireEvent.click(screen.getByRole("button", { name: /Descargar y preparar/i }));
    await waitFor(() => expect(mock.installCudaRuntime).toHaveBeenCalledOnce());

    fireEvent.click(screen.getByRole("button", { name: /Cancelar CUDA/i }));
    await waitFor(() => expect(mock.cancelCudaRuntimeDownload).toHaveBeenCalledOnce());
    act(() => mock.emit({
      type: "cuda_runtime_cancelled",
      payload: { runtimeId: "cuda-runtime" },
    }));

    await screen.findByText(/Se canceló la preparación de CUDA/i);
    fireEvent.click(screen.getByRole("button", { name: /Descargar y preparar/i }));
    await waitFor(() => expect(mock.installCudaRuntime).toHaveBeenCalledTimes(2));
  });
});
