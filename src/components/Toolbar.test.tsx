// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { TranscriptionProject } from "../types";
import { DEFAULT_PROJECT_SETTINGS } from "../types";
import { Toolbar } from "./Toolbar";

const project: TranscriptionProject = {
  id: "project-1",
  name: "Conversación original",
  mediaPath: "C:\\audio.wav",
  mediaUrl: "asset://audio.wav",
  mediaType: "audio",
  durationMs: 1000,
  model: "turbo",
  createdAt: "2026-08-02T12:00:00Z",
  updatedAt: "2026-08-02T12:00:00Z",
  transcriptionStatus: "idle",
  lastPlaybackPositionMs: 0,
  settings: DEFAULT_PROJECT_SETTINGS,
  segments: [],
};

afterEach(cleanup);

describe("barra del proyecto", () => {
  it("renombra el proyecto y ofrece Grabar sin el antiguo centro de operaciones", async () => {
    const rename = vi.fn().mockResolvedValue(undefined);
    render(<Toolbar project={project} jobState="idle" isDirty={false} onOpen={() => undefined} onBrowserFile={() => undefined} onTranscribe={() => undefined} onCancel={() => undefined} onExport={() => undefined} onInsights={() => undefined} onLive={() => undefined} onVoices={() => undefined} onSettings={() => undefined} onDiagnostics={() => undefined} onRenameProject={rename} onShowProjects={() => undefined} />);

    expect(screen.getByRole("button", { name: "Grabar" })).toBeTruthy();
    expect(screen.queryByRole("button", { name: /trabajos en curso/i })).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Cambiar nombre del proyecto" }));
    const input = screen.getByLabelText("Nombre del proyecto");
    fireEvent.change(input, { target: { value: "Charla con Isabel" } });
    fireEvent.click(screen.getByRole("button", { name: "Guardar nombre" }));

    await waitFor(() => expect(rename).toHaveBeenCalledWith("Charla con Isabel"));
  });
});
