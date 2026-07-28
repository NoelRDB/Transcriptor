// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import type { SystemDiagnostics } from "../types";
import { DiagnosticsDialog } from "./DiagnosticsDialog";

afterEach(cleanup);

it("muestra el problema del medio y ofrece relocalizarlo", () => {
  const onRelocate = vi.fn();
  const diagnostics: SystemDiagnostics = {
    status: "error",
    errors: 1,
    warnings: 0,
    checks: [{ id: "media", label: "Archivo original", status: "error", detail: "No existe." }],
    hardware: {
      cpu: { name: "CPU de prueba", physicalCores: 8, logicalCores: 16, usagePercent: 10 },
      memory: { totalMiB: 32_768, availableMiB: 16_384, usagePercent: 50 },
      gpu: null,
      cudaAvailable: false,
      recommendedProfile: "performance",
    },
    models: [],
  };
  const project = {
    id: "p",
    name: "Grabación",
    mediaPath: "C:/movido.wav",
    mediaUrl: "",
    mediaType: "audio" as const,
    durationMs: 1_000,
    model: "turbo",
    createdAt: "now",
    updatedAt: "now",
    transcriptionStatus: "failed" as const,
    lastPlaybackPositionMs: 0,
    settings: {} as never,
    segments: [],
  };

  render(<DiagnosticsDialog project={project} diagnostics={diagnostics} loading={false} onRun={vi.fn()} onRelocate={onRelocate} onUseCandidate={vi.fn()} onClose={vi.fn()} />);

  expect(screen.getByText("Hay un problema que requiere atención")).toBeTruthy();
  fireEvent.click(screen.getByRole("button", { name: "Relocalizar manualmente" }));
  expect(onRelocate).toHaveBeenCalledOnce();
});
