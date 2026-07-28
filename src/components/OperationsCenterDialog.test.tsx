// @vitest-environment jsdom
import { cleanup, render, screen, waitFor } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import type { QueueStatus } from "../types";
import { OperationsCenterDialog } from "./OperationsCenterDialog";

const status: QueueStatus = {
  items: [
    {
      id: "q1",
      projectId: "p1",
      position: 1,
      state: "running",
      name: "Conversación uno",
      durationMs: 60_000,
      mediaPath: "C:/audio/uno.wav",
      mediaType: "audio",
      processedDurationMs: 20_000,
      totalDurationMs: 60_000,
      percent: 36,
      phase: "Transcribiendo",
      message: "Reconociendo voz",
      activeModel: "turbo",
      device: "cuda",
      speedX: 7.5,
      etaMs: 8_000,
      createdAt: "now",
      updatedAt: "now",
    },
    {
      id: "q2",
      projectId: "p2",
      position: 2,
      state: "running",
      name: "Conversación dos",
      durationMs: 120_000,
      mediaPath: "C:/audio/dos.wav",
      mediaType: "audio",
      processedDurationMs: 10_000,
      totalDurationMs: 120_000,
      percent: 20,
      createdAt: "now",
      updatedAt: "now",
    },
  ],
  maxConcurrentJobs: 0,
  effectiveConcurrency: 2,
  recommendedConcurrency: 2,
  runningCount: 2,
  waitingCount: 0,
  completedCount: 0,
  failedCount: 0,
  availableSlots: 0,
  mode: "auto",
};

vi.mock("../lib/engine", () => ({
  engine: {
    getQueueStatus: vi.fn(async () => status),
    listModels: vi.fn(async () => ({ models: [], root: "", freeBytes: 0 })),
    subscribe: vi.fn(() => () => undefined),
  },
}));

afterEach(cleanup);

it("muestra dos transcripciones simultáneas con progreso independiente", async () => {
  render(
    <OperationsCenterDialog
      project={null}
      currentTimeMs={0}
      onImportFiles={vi.fn()}
      onOpenProject={vi.fn()}
      onProjectRestored={vi.fn()}
      onClose={vi.fn()}
    />,
  );

  await waitFor(() => expect(screen.getByText("Conversación uno")).toBeTruthy());
  expect(screen.getByText("Conversación dos")).toBeTruthy();
  expect(screen.getByText("Automático: hasta 2 transcripciones simultáneas")).toBeTruthy();
  expect(screen.getByText("36 %")).toBeTruthy();
  expect(screen.getByText("20 %")).toBeTruthy();
  expect(screen.getByRole("button", { name: /Añadir archivos/i })).toBeTruthy();
});
