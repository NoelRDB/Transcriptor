// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import type { JobProgress } from "../types";
import { StatusBar } from "./StatusBar";

afterEach(cleanup);

const progress: JobProgress = {
  state: "transcribing",
  stage: "transcribing",
  phase: "Transcribiendo…",
  message: "Transcribiendo · 8 %",
  processedDurationMs: 414_230,
  totalDurationMs: 4_970_040,
  percent: 8.3,
  device: "CUDA",
  cpuThreads: 16,
  elapsedMs: 65_000,
  speedX: 6.4,
  etaMs: 711_000,
  segmentsProduced: 42,
  ramMiB: 972,
  cpuUsagePercent: 61,
  systemRamUsedMiB: 12_288,
  systemRamTotalMiB: 32_768,
  gpuUsagePercent: 82,
  gpuVramUsedMiB: 2_048,
  gpuVramTotalMiB: 8_192,
  performanceProfile: "maximum",
};

describe("progreso visible de transcripción", () => {
  it("muestra porcentaje, tiempos, velocidad, fragmentos y dispositivo reales", () => {
    render(<StatusBar progress={progress} model="small" language="es" />);

    expect(screen.getByRole("progressbar").getAttribute("aria-valuenow")).toBe("8.3");
    expect(screen.getByText("06:54 / 01:22:50")).toBeTruthy();
    expect(screen.getByText("6.4×")).toBeTruthy();
    expect(screen.getByText("~11:51")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Mostrar detalles" }));
    expect(screen.getByText("42")).toBeTruthy();
    expect(screen.getByText("972 MB")).toBeTruthy();
    expect(screen.getByText("61 %")).toBeTruthy();
    expect(document.querySelector('[aria-current="step"]')?.textContent).toContain("Texto");
    expect(screen.getByText("82 % · 2048 / 8192 MB")).toBeTruthy();
    expect(screen.getByText("12.0 / 32 GB")).toBeTruthy();
    expect(screen.getByText("Máximo")).toBeTruthy();
    expect(screen.getByText("CUDA + 16 hilos CPU")).toBeTruthy();
  });

  it("describe la fase indeterminada sin inventar un porcentaje", () => {
    render(<StatusBar progress={{ ...progress, stage: "language_detection", percent: null, speedX: undefined, etaMs: null }} model="small" />);

    expect(screen.getByText("En curso")).toBeTruthy();
    expect(screen.getByRole("progressbar").hasAttribute("aria-valuenow")).toBe(false);
  });

  it("separa el progreso global de la revisión inteligente", () => {
    render(<StatusBar progress={{
      ...progress,
      stage: "reviewing",
      phase: "Revisión inteligente…",
      message: "Large-v3 revisando fragmentos dudosos · 60/120",
      percent: 91,
      phasePercent: 50,
      phaseRate: 2.5,
      speedX: null,
      etaMs: null,
      reviewCompletedUnits: 60,
      reviewTotalUnits: 120,
      reviewEtaMs: 24_000,
    }} model="large-v3" language="es" />);

    expect(screen.getByText("91 %")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Mostrar detalles" }));
    const bars = screen.getAllByRole("progressbar");
    expect(bars[0].getAttribute("aria-valuenow")).toBe("91");
    expect(bars[1].getAttribute("aria-valuenow")).toBe("50");
    expect(screen.getByText("Revisión inteligente Large-v3")).toBeTruthy();
    expect(screen.getByText("60 de 120")).toBeTruthy();
    expect(screen.getByText("2.5 frag/s")).toBeTruthy();
    expect(screen.getByText("~00:24")).toBeTruthy();
  });

  it("no anuncia el cien por cien hasta que el guardado ha terminado", () => {
    const { rerender } = render(<StatusBar progress={{
      ...progress,
      stage: "saving",
      phase: "Guardando el resultado…",
      percent: 100,
      phasePercent: null,
      speedX: null,
    }} model="large-v3" />);

    expect(screen.getByText("99 %")).toBeTruthy();
    expect(screen.getByRole("progressbar").getAttribute("aria-valuenow")).toBe("99.5");

    rerender(<StatusBar progress={{
      ...progress,
      state: "completed",
      stage: "completed",
      phase: "Transcripción completada",
      percent: 100,
      phasePercent: 100,
    }} model="large-v3" />);
    expect(screen.queryByRole("progressbar")).toBeNull();
    expect(screen.getByText("Transcripción completada")).toBeTruthy();
  });
});
