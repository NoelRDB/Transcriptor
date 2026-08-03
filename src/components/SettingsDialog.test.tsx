// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { DEFAULT_SETTINGS } from "../types";
import { engine } from "../lib/engine";
import { SettingsDialog } from "./SettingsDialog";

vi.mock("../lib/engine", () => ({
  engine: {
    available: true,
    getCachedHardwareInfo: vi.fn().mockReturnValue(null),
    getCachedSpeakerAiStatus: vi.fn().mockReturnValue(null),
    getHardwareInfo: vi.fn().mockResolvedValue({
      cpu: { name: "AMD Ryzen de prueba", physicalCores: 8, logicalCores: 16, usagePercent: 20 },
      memory: { totalMiB: 32768, availableMiB: 20480, usagePercent: 37.5 },
      gpu: { name: "NVIDIA RTX de prueba", totalVramMiB: 8192, usedVramMiB: 512, utilizationPercent: 12 },
      cudaAvailable: true,
      recommendedProfile: "maximum",
    }),
    getSpeakerAiStatus: vi.fn().mockResolvedValue({
      installed: true,
      ready: true,
      backend: "CAM++ · ONNX",
      model: "CAM++",
      path: "C:\\models\\speaker.onnx",
      sizeBytes: 28_281_164,
      expectedBytes: 28_281_164,
      privacy: "local",
      preciseAvailable: false,
      notice: "Lista",
    }),
    listVoiceProfiles: vi.fn().mockResolvedValue({
      profiles: [],
      encryption: "DPAPI · cuenta de Windows",
      storesRawAudio: false,
    }),
    listModels: vi.fn().mockResolvedValue({
      root: "C:\\models",
      freeBytes: 100 * 1024 ** 3,
      models: [
        { id: "turbo", name: "Turbo", sizeGiB: 1.5, memoryGiB: 4, speed: "Rápido", accuracy: "Muy buena", description: "Modelo veloz", installed: true, installedBytes: 1, paths: [] },
        { id: "large-v3", name: "Large-v3", sizeGiB: 3.1, memoryGiB: 6, speed: "Exigente", accuracy: "Máxima", description: "Modelo preciso", installed: false, installedBytes: 0, paths: [] },
      ],
    }),
    getQueueStatus: vi.fn().mockResolvedValue({
      items: [], maxConcurrentJobs: 0, effectiveConcurrency: 2, recommendedConcurrency: 2,
      runningCount: 0, waitingCount: 0, completedCount: 0, failedCount: 0, availableSlots: 2, mode: "auto",
    }),
    setQueueConcurrency: vi.fn(),
    subscribe: vi.fn().mockReturnValue(() => undefined),
  },
}));

afterEach(cleanup);

describe("centro de rendimiento", () => {
  it("muestra el hardware detectado y asigna el perfil elegido", async () => {
    const onChange = vi.fn();
    render(<SettingsDialog settings={{ ...DEFAULT_SETTINGS, performanceProfile: "balanced" }} onChange={onChange} onClose={() => undefined} />);

    await waitFor(() => expect(screen.getByText("AMD Ryzen de prueba")).toBeTruthy());
    expect(screen.getByText("32.0 GB RAM")).toBeTruthy();
    expect(screen.getByText("NVIDIA RTX de prueba")).toBeTruthy();
    expect(screen.getAllByText(/CUDA disponible/).length).toBeGreaterThan(0);
    expect(screen.getByText(/Piloto automático · potencia completa/)).toBeTruthy();
    expect(screen.getByText("CAM++ neuronal activada")).toBeTruthy();
    expect(screen.getByText("Reconocimiento de voz")).toBeTruthy();
    expect(screen.getByRole("button", { name: /Descargar/i })).toBeTruthy();

    fireEvent.click(screen.getByRole("button", { name: /Avanzado/ }));
    fireEvent.click(screen.getByRole("button", { name: /Máximo/ }));
    expect(onChange).toHaveBeenCalledWith({ performanceProfile: "maximum", cpuThreads: 16 });
  });

  it("el modo sencillo elimina el número fijo de hablantes", async () => {
    const onChange = vi.fn();
    render(<SettingsDialog settings={{ ...DEFAULT_SETTINGS, experienceMode: "advanced", speakerCountMode: "exact", speakerCount: 2 }} onChange={onChange} onClose={() => undefined} />);

    await waitFor(() => expect(screen.getByText("AMD Ryzen de prueba")).toBeTruthy());
    fireEvent.click(screen.getByRole("button", { name: /Sencillo/ }));

    expect(onChange).toHaveBeenCalledWith(expect.objectContaining({
      experienceMode: "simple",
      device: "auto",
      speakerCountMode: "auto",
      speakerCount: 8,
      diarizationMode: "neural",
    }));
  });

  it("muestra sólo los controles avanzados útiles de voces y ningún ajuste de la antigua transcripción en directo", async () => {
    render(<SettingsDialog settings={{ ...DEFAULT_SETTINGS, experienceMode: "advanced" }} onChange={() => undefined} onClose={() => undefined} />);

    await waitFor(() => expect(screen.getByText("AMD Ryzen de prueba")).toBeTruthy());
    expect(screen.getByText("Número de voces")).toBeTruthy();
    expect(screen.getByText("Máximo de hablantes")).toBeTruthy();
    expect(screen.getByText("Sensibilidad al cambio de voz")).toBeTruthy();
    expect(screen.queryByText("Latencia en directo")).toBeNull();
    expect(screen.queryByText("Nombre de la primera voz")).toBeNull();
    expect(screen.queryByText("Nombre de la segunda voz")).toBeNull();
  });

  it("no ofrece instalar CAM++ mientras todavía está comprobando el modelo local", async () => {
    let finishCheck!: (value: Awaited<ReturnType<typeof engine.getSpeakerAiStatus>>) => void;
    vi.mocked(engine.getSpeakerAiStatus).mockImplementationOnce(() => new Promise((resolve) => {
      finishCheck = resolve;
    }));

    render(<SettingsDialog settings={DEFAULT_SETTINGS} onChange={() => undefined} onClose={() => undefined} />);

    expect(screen.getByText("Comprobando la IA de voces")).toBeTruthy();
    expect(screen.queryByRole("button", { name: "Instalar IA" })).toBeNull();
    finishCheck({
      installed: true,
      ready: true,
      backend: "CAM++ · ONNX",
      model: "CAM++",
      path: "C:\\models\\speaker.onnx",
      sizeBytes: 28_281_164,
      expectedBytes: 28_281_164,
      privacy: "local",
      preciseAvailable: false,
      notice: "Lista",
    });
    await waitFor(() => expect(screen.getByText("Separación neuronal activada")).toBeTruthy());
  });
});
