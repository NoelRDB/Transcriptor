// @vitest-environment jsdom
import { beforeEach, describe, expect, it } from "vitest";
import { routeEngineEvent } from "./lib/engineEvents";
import { useAppStore } from "./store";
import { DEFAULT_PROJECT_SETTINGS, type TranscriptSegment, type TranscriptionProject } from "./types";

const oldSegment: TranscriptSegment = {
  id: "old",
  startMs: 0,
  endMs: 1_000,
  text: "Texto anterior",
  order: 0,
  words: [],
};

function project(): TranscriptionProject {
  return {
    id: "project-1",
    name: "Prueba",
    mediaPath: "audio.ogg",
    mediaUrl: "audio.ogg",
    mediaType: "audio",
    durationMs: 60_000,
    model: "small",
    createdAt: "2026-01-01T00:00:00Z",
    updatedAt: "2026-01-01T00:00:00Z",
    transcriptionStatus: "completed",
    lastPlaybackPositionMs: 0,
    settings: DEFAULT_PROJECT_SETTINGS,
    segments: [oldSegment],
  };
}

describe("eventos parciales de transcripción", () => {
  beforeEach(() => useAppStore.getState().setProject(project()));

  it("conserva el texto anterior hasta que llega el primer fragmento nuevo", () => {
    expect(useAppStore.getState().project?.segments).toEqual([oldSegment]);

    const first = { ...oldSegment, id: "new-1", text: "Texto nuevo" };
    routeEngineEvent({
      type: "partial_segments",
      payload: { projectId: "project-1", segments: [first], replaceExisting: true },
    });

    expect(useAppStore.getState().project?.segments).toEqual([first]);
  });

  it("acumula los fragmentos posteriores", () => {
    const first = { ...oldSegment, id: "new-1", text: "Primero" };
    const second = { ...oldSegment, id: "new-2", startMs: 1_000, endMs: 2_000, order: 1, text: "Segundo" };
    routeEngineEvent({
      type: "partial_segments",
      payload: { projectId: "project-1", segments: [first], replaceExisting: true },
    });
    routeEngineEvent({
      type: "partial_segments",
      payload: { projectId: "project-1", segments: [second], replaceExisting: false },
    });

    expect(useAppStore.getState().project?.segments.map((segment) => segment.id)).toEqual(["new-1", "new-2"]);
  });

  it("actualiza el proyecto abierto cuando dos identidades de voz se fusionan", () => {
    useAppStore.getState().setProject({
      ...project(),
      segments: [{
        ...oldSegment,
        speaker: "Hablante 1",
        speakerProfileId: "voice-source",
      }],
    });

    routeEngineEvent({
      type: "voice_profiles_merged",
      payload: {
        sourceProfileId: "voice-source",
        targetProfileId: "voice-noel",
        targetName: "Noel",
        affectedProjectIds: ["project-1"],
      },
    });

    expect(useAppStore.getState().project?.segments[0]).toMatchObject({
      speaker: "Noel",
      speakerProfileId: "voice-noel",
    });
  });
});
