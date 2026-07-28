// @vitest-environment jsdom
import { cleanup, render, screen, waitFor } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import type { QueueStatus } from "../types";
import { WorkQueuePanel } from "./WorkQueuePanel";

const status: QueueStatus = {
  items: [
    {
      id: "q1",
      projectId: "p1",
      position: 1,
      state: "running",
      name: "Conversación activa",
      durationMs: 60_000,
      mediaPath: "C:/audio/uno.wav",
      mediaType: "audio",
      processedDurationMs: 24_000,
      totalDurationMs: 60_000,
      percent: 40,
      phase: "Transcribiendo",
      activeModel: "turbo",
      device: "cuda",
      speedX: 8.2,
      etaMs: 5_000,
      createdAt: "now",
      updatedAt: "now",
    },
    {
      id: "q2",
      projectId: "p2",
      position: 2,
      state: "queued",
      name: "Conversación en espera",
      durationMs: 90_000,
      mediaPath: "C:/audio/dos.wav",
      mediaType: "audio",
      processedDurationMs: 0,
      totalDurationMs: 90_000,
      percent: 0,
      createdAt: "now",
      updatedAt: "now",
    },
  ],
  maxConcurrentJobs: 0,
  effectiveConcurrency: 2,
  recommendedConcurrency: 2,
  runningCount: 1,
  waitingCount: 1,
  completedCount: 0,
  failedCount: 0,
  availableSlots: 1,
  mode: "auto",
};

vi.mock("../lib/engine", () => ({
  engine: {
    available: true,
    getQueueStatus: vi.fn(async () => status),
    subscribe: vi.fn(() => () => undefined),
    cancel: vi.fn(),
    removeFromQueue: vi.fn(),
  },
}));

afterEach(cleanup);

it("muestra en la pantalla principal los trabajos activos y en espera", async () => {
  render(<WorkQueuePanel onImportFiles={vi.fn()} onOpenProject={vi.fn()} />);

  await waitFor(() => expect(screen.getByText("Conversación activa")).toBeTruthy());
  expect(screen.getByText("Conversación en espera")).toBeTruthy();
  expect(screen.getByText("40 %")).toBeTruthy();
  expect(screen.getByText(/1 procesando · 1 en espera · 2 en paralelo/)).toBeTruthy();
  expect(screen.getByRole("button", { name: /Añadir lote/i })).toBeTruthy();
});
