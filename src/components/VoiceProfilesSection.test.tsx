// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { DEFAULT_SETTINGS } from "../types";
import { VoiceProfilesSection } from "./VoiceProfilesSection";

const { compareVoiceProfiles, mergeVoiceProfiles, updateVoiceProfile } = vi.hoisted(() => ({
  compareVoiceProfiles: vi.fn().mockResolvedValue({
    sourceProfileId: "voice-source",
    sourceName: "Hablante 1",
    targetProfileId: "voice-noel",
    targetName: "Noel",
    similarity: 0.91,
    threshold: 0.64,
    verdict: "alta",
  }),
  mergeVoiceProfiles: vi.fn().mockResolvedValue({
    merged: true,
    sourceProfileId: "voice-source",
    sourceName: "Hablante 1",
    targetProfileId: "voice-noel",
    targetName: "Noel",
    movedSamples: 6,
    removedSamples: 0,
    retainedSamples: 12,
    updatedSegments: 8,
    affectedProjectIds: ["project-1"],
    targetProfile: {
      id: "voice-noel",
      name: "Noel",
      color: "#7dd3fc",
      sampleCount: 12,
      totalDurationMs: 68_000,
      sourceProjectCount: 2,
      matchThreshold: 0.64,
      enabled: true,
      ready: true,
      reliability: "buena",
      createdAt: "2026-07-01T00:00:00Z",
      updatedAt: "2026-07-28T00:00:00Z",
      lastMatchedAt: "2026-07-28T00:00:00Z",
    },
    catalog: {
      profiles: [{
        id: "voice-noel",
        name: "Noel",
        color: "#7dd3fc",
        sampleCount: 12,
        totalDurationMs: 68_000,
        sourceProjectCount: 2,
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
    },
  }),
  updateVoiceProfile: vi.fn().mockImplementation(
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
  ),
}));

vi.mock("../lib/engine", () => ({
  engine: {
    listVoiceProfiles: vi.fn().mockResolvedValue({
      profiles: [
        {
          id: "voice-source",
          name: "Hablante 1",
          color: "#f0abfc",
          sampleCount: 6,
          totalDurationMs: 37_000,
          sourceProjectCount: 1,
          averageSampleConfidence: 0.99,
          matchThreshold: 0.64,
          enabled: true,
          ready: true,
          reliability: "buena",
          createdAt: "2026-07-02T00:00:00Z",
          updatedAt: "2026-07-28T00:00:00Z",
          lastMatchedAt: "2026-07-28T00:00:00Z",
        },
        {
          id: "voice-noel",
          name: "Noel",
          color: "#7dd3fc",
          sampleCount: 6,
          totalDurationMs: 31_000,
          sourceProjectCount: 1,
          recognizedDurationMs: 3_678_000,
          recognizedProjectCount: 3,
          recognizedSegmentCount: 184,
          averageMatchConfidence: 0.91,
          reliabilityScore: 0.88,
          matchThreshold: 0.64,
          enabled: true,
          ready: true,
          reliability: "buena",
          createdAt: "2026-07-01T00:00:00Z",
          updatedAt: "2026-07-28T00:00:00Z",
          lastMatchedAt: "2026-07-28T00:00:00Z",
        },
      ],
      encryption: "DPAPI · cuenta de Windows",
      storesRawAudio: false,
    }),
    updateVoiceProfile,
    deleteVoiceProfile: vi.fn().mockResolvedValue({ deleted: true }),
    compareVoiceProfiles,
    mergeVoiceProfiles,
    subscribe: vi.fn().mockReturnValue(() => undefined),
  },
}));

afterEach(() => {
  cleanup();
  if (vi.isMockFunction(window.confirm)) vi.mocked(window.confirm).mockRestore();
  vi.clearAllMocks();
});

describe("memoria local de voces", () => {
  it("muestra la fiabilidad y pide consentimiento antes de activarse", async () => {
    const onChange = vi.fn();
    vi.spyOn(window, "confirm").mockReturnValue(true);
    render(<VoiceProfilesSection settings={{ ...DEFAULT_SETTINGS, voiceProfilesEnabled: false }} advanced onChange={onChange} />);

    await waitFor(() => expect(screen.getByDisplayValue("Noel")).toBeTruthy());
    expect(screen.getAllByText(/Buena fiabilidad/)).toHaveLength(2);
    const recognized = screen.getAllByTitle(/Tiempo total de transcripción que la aplicación ha atribuido/)[1];
    expect(recognized.textContent).toContain("1 h 1 min");
    expect(recognized.textContent).toContain("3 conversaciones");
    const memory = screen.getAllByTitle(/Memoria local: sólo huellas matemáticas/)[1];
    expect(memory.textContent).toContain("31 s");
    expect(memory.textContent).toContain("6 muestras claras");
    expect(screen.getByText("Similitud media 91 %")).toBeTruthy();
    expect(screen.getByText("Sin coincidencias verificadas")).toBeTruthy();
    expect(screen.getByText("Calidad de memoria 99 %")).toBeTruthy();
    expect(screen.getByText(/88 % · Buena fiabilidad/)).toBeTruthy();
    expect(screen.getByText(/DPAPI/)).toBeTruthy();

    fireEvent.click(screen.getByRole("button", { name: "Activar" }));
    expect(window.confirm).toHaveBeenCalledOnce();
    expect(onChange).toHaveBeenCalledWith({ voiceProfilesEnabled: true });
  });

  it("compara y fusiona dos perfiles conservando la identidad elegida", async () => {
    vi.spyOn(window, "confirm").mockReturnValue(true);
    render(<VoiceProfilesSection settings={{ ...DEFAULT_SETTINGS, voiceProfilesEnabled: true }} advanced onChange={vi.fn()} />);

    await waitFor(() => expect(screen.getByDisplayValue("Hablante 1")).toBeTruthy());
    fireEvent.click(screen.getByRole("button", { name: "Fusionar Hablante 1" }));
    fireEvent.change(screen.getByLabelText("Perfil que conservará a Hablante 1"), {
      target: { value: "voice-noel" },
    });

    await waitFor(() => expect(screen.getByText("91 %")).toBeTruthy());
    expect(compareVoiceProfiles).toHaveBeenCalledWith("voice-source", "voice-noel");
    fireEvent.click(screen.getByRole("button", { name: "Fusionar en Noel" }));

    await waitFor(() => expect(mergeVoiceProfiles).toHaveBeenCalledWith("voice-source", "voice-noel"));
    expect(screen.queryByDisplayValue("Hablante 1")).toBeNull();
    expect(screen.getByText(/ahora forma parte de “Noel”/)).toBeTruthy();
  });
});
