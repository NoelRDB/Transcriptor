// @vitest-environment jsdom

import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { RecentProject } from "../types";
import { Welcome } from "./Welcome";

vi.mock("./WorkQueuePanel", () => ({
  WorkQueuePanel: () => <div data-testid="work-queue" />,
}));

afterEach(cleanup);

const recent: RecentProject = {
  id: "recent-1",
  name: "Entrevista.wav",
  mediaPath: "C:\\Audio\\Entrevista.wav",
  mediaType: "audio",
  updatedAt: "2026-08-03T00:00:00.000Z",
  transcriptionStatus: "completed",
  durationMs: 4_200,
};

function renderWelcome(loading = false) {
  const onRevealRecent = vi.fn();
  render(
    <Welcome
      recent={[recent]}
      loading={loading}
      onOpen={vi.fn()}
      onOpenRecent={vi.fn()}
      onRevealRecent={onRevealRecent}
      onDeleteRecent={vi.fn().mockResolvedValue(undefined)}
      onDropPath={vi.fn()}
      onImportFiles={vi.fn().mockResolvedValue({ added: 0, reused: 0, failures: [] })}
    />,
  );
  return onRevealRecent;
}

describe("proyectos recientes en Inicio", () => {
  it("mantiene visible la caché mientras actualiza el motor", () => {
    renderWelcome(true);

    expect(screen.getByTitle("Abrir Entrevista.wav")).toBeTruthy();
    expect(screen.queryByText("Conectando con tus proyectos…")).toBeNull();
  });

  it("permite mostrar el archivo en su carpeta con un control accesible", () => {
    const onRevealRecent = renderWelcome();

    fireEvent.click(screen.getByRole("button", { name: "Mostrar Entrevista.wav en su carpeta" }));

    expect(onRevealRecent).toHaveBeenCalledWith(recent.mediaPath);
  });
});
