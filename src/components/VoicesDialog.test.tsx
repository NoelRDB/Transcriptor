// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { DEFAULT_PROJECT_SETTINGS, DEFAULT_SETTINGS, type TranscriptionProject } from "../types";
import { VoicesDialog } from "./VoicesDialog";

const { learnProjectVoices } = vi.hoisted(() => ({
  learnProjectVoices: vi.fn().mockResolvedValue({ accepted: true, projectId: "project-1" }),
}));

vi.mock("../lib/engine", () => ({
  engine: {
    subscribe: vi.fn().mockReturnValue(() => undefined),
    learnProjectVoices,
    cancelVoiceLearning: vi.fn().mockResolvedValue({ cancelled: true }),
    listVoiceProfiles: vi.fn().mockResolvedValue({
      profiles: [],
      encryption: "DPAPI · cuenta de Windows",
      storesRawAudio: false,
    }),
    updateVoiceProfile: vi.fn(),
    deleteVoiceProfile: vi.fn(),
  },
}));

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

const project: TranscriptionProject = {
  id: "project-1",
  name: "Conversación de prueba",
  mediaPath: "C:\\audio\\conversacion.wav",
  mediaUrl: "asset://audio",
  mediaType: "audio",
  durationMs: 65_000,
  language: "es",
  model: "turbo",
  createdAt: "2026-07-28T00:00:00Z",
  updatedAt: "2026-07-28T00:00:00Z",
  transcriptionStatus: "completed",
  lastPlaybackPositionMs: 0,
  settings: DEFAULT_PROJECT_SETTINGS,
  segments: [{
    id: "segment-1",
    startMs: 0,
    endMs: 2_000,
    text: "Hola",
    order: 0,
    words: [],
  }],
};

describe("biblioteca de voces", () => {
  it("permite aprender del proyecto actual y activa la memoria local", async () => {
    const onChange = vi.fn();
    const latestProject = {
      ...project,
      segments: [{ ...project.segments[0], text: "Hola corregido", reviewState: "corrected" as const }],
    };
    const onBeforeLearn = vi.fn().mockResolvedValue(latestProject);
    render(<VoicesDialog
      settings={{ ...DEFAULT_SETTINGS, voiceProfilesEnabled: false }}
      project={project}
      appBusy={false}
      onChange={onChange}
      onBeforeLearn={onBeforeLearn}
      onClose={vi.fn()}
    />);

    fireEvent.click(screen.getByRole("button", { name: /Aprender de este proyecto/i }));

    await waitFor(() => expect(learnProjectVoices).toHaveBeenCalledWith(latestProject));
    expect(onBeforeLearn).toHaveBeenCalledOnce();
    expect(onBeforeLearn.mock.invocationCallOrder[0]).toBeLessThan(
      learnProjectVoices.mock.invocationCallOrder[0],
    );
    expect(onChange).toHaveBeenCalledWith({
      voiceProfilesEnabled: true,
      voiceProfileAutoLearn: true,
    });
    expect(screen.getByRole("progressbar").getAttribute("aria-valuenow")).toBe("0");
  });
});
