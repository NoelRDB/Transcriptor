// @vitest-environment jsdom

import { beforeEach, describe, expect, it } from "vitest";
import { useAppStore } from "./store";
import { DEFAULT_PROJECT_SETTINGS } from "./types";
import type { TranscriptionProject } from "./types";

function project(): TranscriptionProject {
  return {
    id: "project-review",
    name: "Conversación",
    mediaPath: "C:\\audio\\conversation.wav",
    mediaUrl: "asset://conversation.wav",
    mediaType: "audio",
    durationMs: 4_000,
    model: "turbo",
    createdAt: "2026-07-28T00:00:00.000Z",
    updatedAt: "2026-07-28T00:00:00.000Z",
    transcriptionStatus: "completed",
    lastPlaybackPositionMs: 0,
    settings: { ...DEFAULT_PROJECT_SETTINGS },
    segments: [{
      id: "segment-1",
      startMs: 0,
      endMs: 4_000,
      text: "Texto dudoso",
      speaker: "Noel",
      speakerConfidence: 0.76,
      speakerProfileId: "voice-noel",
      speakerMatchConfidence: 0.82,
      speakerProvisional: false,
      confidence: 0.74,
      order: 0,
      words: [],
    }],
  };
}

describe("transcript review state", () => {
  beforeEach(() => {
    useAppStore.getState().setProject(project());
  });

  it("marks unchanged text as accepted and corrected text as corrected", () => {
    useAppStore.getState().editSegment("segment-1", "Texto dudoso", true);
    expect(useAppStore.getState().project?.segments[0].reviewState).toBe("accepted");

    useAppStore.getState().setProject(project());
    useAppStore.getState().editSegment("segment-1", "Texto ya corregido", true);
    expect(useAppStore.getState().project?.segments[0]).toMatchObject({
      text: "Texto ya corregido",
      reviewState: "corrected",
    });
  });

  it("clears stale profile identity when the speaker is changed manually", () => {
    useAppStore.getState().editSpeaker("segment-1", "Isabel");

    expect(useAppStore.getState().project?.segments[0]).toMatchObject({
      speaker: "Isabel",
      speakerProfileId: undefined,
      speakerMatchConfidence: undefined,
      speakerProvisional: false,
      speakerReviewState: "corrected",
    });
    expect(useAppStore.getState().project?.segments[0].reviewState).toBeUndefined();
  });

  it("links a manual correction to the selected local voice profile", () => {
    useAppStore.getState().editSpeaker("segment-1", "Isabel", "voice-isabel");

    expect(useAppStore.getState().project?.segments[0]).toMatchObject({
      speaker: "Isabel",
      speakerProfileId: "voice-isabel",
      speakerMatchConfidence: undefined,
      speakerReviewState: "corrected",
    });
    expect(useAppStore.getState().project?.segments[0].reviewState).toBeUndefined();
  });

  it("reviews speaker confidence without accepting doubtful text", () => {
    useAppStore.getState().reviewSpeaker("segment-1");

    expect(useAppStore.getState().project?.segments[0]).toMatchObject({
      speakerReviewState: "accepted",
      confidence: 0.74,
    });
    expect(useAppStore.getState().project?.segments[0].reviewState).toBeUndefined();
  });

  it("restores review state when undoing a text review", () => {
    useAppStore.getState().editSegment("segment-1", "Texto ya corregido", true);
    useAppStore.getState().undo();

    expect(useAppStore.getState().project?.segments[0]).toMatchObject({
      text: "Texto dudoso",
      reviewState: undefined,
    });
  });

  it("requires a fresh review after splitting a reviewed fragment", () => {
    const reviewed = project();
    reviewed.segments[0].reviewState = "accepted";
    reviewed.segments[0].speakerReviewState = "accepted";
    useAppStore.getState().setProject(reviewed);

    useAppStore.getState().splitSegment("segment-1", 5);

    expect(useAppStore.getState().project?.segments).toHaveLength(2);
    for (const segment of useAppStore.getState().project?.segments ?? []) {
      expect(segment.reviewState).toBeUndefined();
      expect(segment.speakerReviewState).toBeUndefined();
      expect(segment.confidence).toBe(0.74);
    }
  });

  it("merges confidence and review state conservatively", () => {
    const mixed = project();
    mixed.segments[0].reviewState = "accepted";
    mixed.segments[0].speakerReviewState = "accepted";
    mixed.segments.push({
      ...mixed.segments[0],
      id: "segment-2",
      startMs: 4_000,
      endMs: 8_000,
      text: "Segundo texto",
      confidence: 0.61,
      reviewState: undefined,
      speakerMatchConfidence: 0.69,
      speakerReviewState: undefined,
      order: 1,
    });
    useAppStore.getState().setProject(mixed);

    useAppStore.getState().mergeWithNext("segment-1");

    expect(useAppStore.getState().project?.segments[0]).toMatchObject({
      confidence: 0.61,
      speakerMatchConfidence: 0.69,
      reviewState: undefined,
      speakerReviewState: undefined,
    });
  });

  it("does not invent one speaker when merging two different identities", () => {
    const mixed = project();
    mixed.segments.push({
      ...mixed.segments[0],
      id: "segment-2",
      startMs: 4_000,
      endMs: 8_000,
      text: "Respuesta",
      speaker: "Isabel",
      speakerProfileId: "voice-isabel",
      speakerMatchConfidence: 0.91,
      order: 1,
    });
    useAppStore.getState().setProject(mixed);

    useAppStore.getState().mergeWithNext("segment-1");

    expect(useAppStore.getState().project?.segments[0]).toMatchObject({
      speaker: undefined,
      speakerProfileId: undefined,
      speakerMatchConfidence: undefined,
      speakerProvisional: true,
      speakerReviewState: undefined,
    });
  });
});
