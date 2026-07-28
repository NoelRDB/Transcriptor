// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { DEFAULT_SETTINGS } from "../types";
import { VoiceProfilesSection } from "./VoiceProfilesSection";

const { updateVoiceProfile } = vi.hoisted(() => ({ updateVoiceProfile: vi.fn().mockImplementation(
  (_id: string, changes: Record<string, unknown>) => Promise.resolve({
    id: "voice-1",
    name: changes.name ?? "Noel",
    color: "#c9ff48",
    sampleCount: 12,
    totalDurationMs: 31_000,
    matchThreshold: 0.64,
    enabled: true,
    ready: true,
    reliability: "buena",
    createdAt: "2026-07-01T00:00:00Z",
    updatedAt: "2026-07-28T00:00:00Z",
    lastMatchedAt: "2026-07-28T00:00:00Z",
  }),
) }));

vi.mock("../lib/engine", () => ({
  engine: {
    listVoiceProfiles: vi.fn().mockResolvedValue({
      profiles: [{
        id: "voice-1",
        name: "Noel",
        color: "#c9ff48",
        sampleCount: 12,
        totalDurationMs: 31_000,
        matchThreshold: 0.64,
        enabled: true,
        ready: true,
        reliability: "buena",
        createdAt: "2026-07-01T00:00:00Z",
        updatedAt: "2026-07-28T00:00:00Z",
        lastMatchedAt: "2026-07-28T00:00:00Z",
      }],
      encryption: "DPAPI · cuenta de Windows",
      storesRawAudio: false,
    }),
    updateVoiceProfile,
    deleteVoiceProfile: vi.fn().mockResolvedValue({ deleted: true }),
    subscribe: vi.fn().mockReturnValue(() => undefined),
  },
}));

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

describe("memoria local de voces", () => {
  it("muestra la fiabilidad y pide consentimiento antes de activarse", async () => {
    const onChange = vi.fn();
    vi.spyOn(window, "confirm").mockReturnValue(true);
    render(<VoiceProfilesSection settings={{ ...DEFAULT_SETTINGS, voiceProfilesEnabled: false }} advanced onChange={onChange} />);

    await waitFor(() => expect(screen.getByDisplayValue("Noel")).toBeTruthy());
    expect(screen.getByText("Buena fiabilidad")).toBeTruthy();
    expect(screen.getByText(/DPAPI/)).toBeTruthy();

    fireEvent.click(screen.getByRole("button", { name: "Activar" }));
    expect(window.confirm).toHaveBeenCalledOnce();
    expect(onChange).toHaveBeenCalledWith({ voiceProfilesEnabled: true });
  });
});
