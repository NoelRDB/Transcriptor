import { describe, expect, it } from "vitest";
import { exportProject, sanitizeUnicode } from "./exporters";
import { DEFAULT_PROJECT_SETTINGS, type TranscriptionProject } from "../types";

const project: TranscriptionProject = {
  id: "p1", name: "Prueba", mediaPath: "C:\\Vídeos\\prueba.mp4", mediaUrl: "asset://test", mediaType: "video",
  durationMs: 5000, model: "small", createdAt: "2026-01-01", updatedAt: "2026-01-01", transcriptionStatus: "completed",
  lastPlaybackPositionMs: 0, settings: DEFAULT_PROJECT_SETTINGS,
  segments: [
    { id: "s2", startMs: 2500, endMs: 2000, text: "Segundo", order: 2, words: [] },
    { id: "s1", startMs: -20, endMs: 1000, text: "Hola, \"mundo\"", speaker: "Ana", order: 1, words: [] },
  ],
};

describe("transcript exporters", () => {
  it("sorts and normalizes SRT cues", () => {
    const output = exportProject(project, "srt");
    expect(output).toContain("00:00:00,000 --> 00:00:01,000");
    expect(output).toContain("00:00:02,500 --> 00:00:02,501");
    expect(output.indexOf("Hola")).toBeLessThan(output.indexOf("Segundo"));
  });
  it("creates a valid WebVTT header", () => expect(exportProject(project, "vtt")).toMatch(/^WEBVTT\n\n/));
  it("escapes CSV fields", () => expect(exportProject(project, "csv")).toContain('"Hola, ""mundo"""'));
  it("does not persist the transient media URL to JSON", () => expect(exportProject(project, "json")).not.toContain("asset://test"));
  it("replaces isolated surrogates while preserving valid emoji", () => {
    expect(sanitizeUnicode(`Bien \uD83D\uDE42 mal \uDC81 fin \uD800`)).toBe("Bien 🙂 mal � fin �");
    const damaged = {
      ...project,
      name: "Prueba \uDC81",
      segments: [{ ...project.segments[0], text: "Texto \uDC81 válido 🙂" }],
    };
    expect(() => JSON.parse(exportProject(damaged, "json"))).not.toThrow();
    expect(exportProject(damaged, "txt")).toContain("Texto � válido 🙂");
  });
});
