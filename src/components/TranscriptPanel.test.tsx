// @vitest-environment jsdom

import { act, cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { TranscriptSegment, VoiceProfile } from "../types";
import { TranscriptPanel } from "./TranscriptPanel";

const segments: TranscriptSegment[] = [
  { id: "s1", startMs: 0, endMs: 900, text: "Primer fragmento", order: 0, words: [] },
  { id: "s2", startMs: 1200, endMs: 2200, text: "Segundo fragmento", order: 1, words: [] },
];

function voiceProfile(id: string, name: string, enabled = true): VoiceProfile {
  return {
    id,
    name,
    color: "#c9ff48",
    sampleCount: 8,
    totalDurationMs: 24_000,
    matchThreshold: 0.64,
    enabled,
    ready: true,
    reliability: "buena",
    createdAt: "2026-07-28T00:00:00Z",
    updatedAt: "2026-07-28T00:00:00Z",
  };
}

const baseProps = {
  segments,
  followPlayback: true,
  onFollowChange: vi.fn(),
  onSeek: vi.fn(),
  onEdit: vi.fn(),
  onUndo: vi.fn(),
  onRedo: vi.fn(),
  canUndo: false,
  canRedo: false,
};

describe("TranscriptPanel follow mode", () => {
  const scrollTo = vi.fn();

  beforeEach(() => {
    vi.useFakeTimers();
    vi.stubGlobal("CSS", { escape: (value: string) => value });
    Object.defineProperty(window, "matchMedia", {
      configurable: true,
      value: vi.fn(() => ({ matches: true })),
    });
    Object.defineProperty(HTMLElement.prototype, "scrollTo", {
      configurable: true,
      value: scrollTo,
    });
    vi.spyOn(window, "requestAnimationFrame").mockImplementation((callback) => {
      callback(0);
      return 1;
    });
    vi.spyOn(window, "cancelAnimationFrame").mockImplementation(() => undefined);
  });

  afterEach(() => {
    cleanup();
    scrollTo.mockClear();
    vi.useRealTimers();
    vi.restoreAllMocks();
    vi.unstubAllGlobals();
  });

  it("scrolls when playback advances to another segment", () => {
    const view = render(<TranscriptPanel {...baseProps} currentTimeMs={100} />);
    expect(scrollTo).toHaveBeenCalled();
    const calls = scrollTo.mock.calls.length;

    view.rerender(<TranscriptPanel {...baseProps} currentTimeMs={1500} />);

    expect(scrollTo.mock.calls.length).toBeGreaterThan(calls);
  });

  it("temporarily pauses after manual wheel scrolling and resumes", () => {
    const view = render(<TranscriptPanel {...baseProps} currentTimeMs={100} />);
    const list = view.container.querySelector(".segment-list");
    expect(list).not.toBeNull();

    fireEvent.wheel(list!);
    expect(screen.getByRole("button", { name: /Reanudar/i })).toBeTruthy();

    act(() => vi.advanceTimersByTime(4_000));

    expect(screen.getByRole("button", { name: /Seguir/i })).toBeTruthy();
  });

  it("allows a detected speaker to be corrected manually", () => {
    const onSpeakerChange = vi.fn();
    const onEdit = vi.fn();
    render(<TranscriptPanel {...baseProps} currentTimeMs={100} onEdit={onEdit} onSpeakerChange={onSpeakerChange} />);

    fireEvent.click(screen.getAllByRole("button", { name: "Editar fragmento" })[0]);
    fireEvent.change(screen.getByRole("combobox", { name: "Hablante" }), { target: { value: "speaker:Hablante 2" } });
    fireEvent.click(screen.getByRole("button", { name: /Aplicar/i }));

    expect(onSpeakerChange).toHaveBeenCalledWith("s1", "Hablante 2", undefined);
    expect(onEdit).not.toHaveBeenCalled();
  });

  it("preserves the profile id when correcting to a known local voice", () => {
    const onSpeakerChange = vi.fn();
    const profiledSegments = [
      segments[0],
      { ...segments[1], speaker: "Isabel", speakerProfileId: "voice-isabel" },
    ];
    render(<TranscriptPanel {...baseProps} segments={profiledSegments} currentTimeMs={100} onSpeakerChange={onSpeakerChange} />);

    fireEvent.click(screen.getAllByRole("button", { name: "Editar fragmento" })[0]);
    fireEvent.change(screen.getByRole("combobox", { name: "Hablante" }), { target: { value: "profile:voice-isabel" } });
    fireEvent.click(screen.getByRole("button", { name: /Aplicar/i }));

    expect(onSpeakerChange).toHaveBeenCalledWith("s1", "Isabel", "voice-isabel");
  });

  it("offers enabled local profiles even when they do not appear in this transcript", () => {
    const onSpeakerChange = vi.fn();
    render(<TranscriptPanel
      {...baseProps}
      currentTimeMs={100}
      voiceProfiles={[
        voiceProfile("voice-isabel", "Isabel"),
        voiceProfile("voice-paused", "Perfil pausado", false),
      ]}
      onSpeakerChange={onSpeakerChange}
    />);

    fireEvent.click(screen.getAllByRole("button", { name: "Editar fragmento" })[0]);
    expect(screen.getByRole("option", { name: "Isabel · perfil local" })).toBeTruthy();
    expect(screen.queryByRole("option", { name: /Perfil pausado/ })).toBeNull();
    fireEvent.change(screen.getByRole("combobox", { name: "Hablante" }), {
      target: { value: "profile:voice-isabel" },
    });
    fireEvent.click(screen.getByRole("button", { name: /Aplicar/i }));

    expect(onSpeakerChange).toHaveBeenCalledWith("s1", "Isabel", "voice-isabel");
  });

  it("keeps duplicate profile names separate by their stable ids", () => {
    const onSpeakerChange = vi.fn();
    render(<TranscriptPanel
      {...baseProps}
      currentTimeMs={100}
      voiceProfiles={[
        voiceProfile("voice-noel-primary", "Noel"),
        voiceProfile("voice-noel-secondary", "Noel"),
      ]}
      onSpeakerChange={onSpeakerChange}
    />);

    fireEvent.click(screen.getAllByRole("button", { name: "Editar fragmento" })[0]);
    const duplicateOptions = screen.getAllByRole("option", { name: /Noel · perfil local/ });
    expect(duplicateOptions).toHaveLength(2);
    expect(duplicateOptions[0].getAttribute("value")).not.toBe(duplicateOptions[1].getAttribute("value"));

    fireEvent.change(screen.getByRole("combobox", { name: "Hablante" }), {
      target: { value: "profile:voice-noel-secondary" },
    });
    fireEvent.click(screen.getByRole("button", { name: /Aplicar/i }));

    expect(onSpeakerChange).toHaveBeenCalledWith("s1", "Noel", "voice-noel-secondary");
  });

  it("separates transcript, voice separation and identity confidence", () => {
    const uncertainSegments: TranscriptSegment[] = [{
      ...segments[0],
      confidence: 0.68,
      speaker: "Isabel",
      speakerConfidence: 0.76,
      speakerProfileId: "voice-isabel",
      speakerMatchConfidence: 0.81,
    }];
    render(<TranscriptPanel {...baseProps} segments={uncertainSegments} currentTimeMs={100} />);

    expect(screen.getByText("Texto").parentElement?.textContent).toContain("68 %");
    expect(screen.getByText("Separación de voz").parentElement?.textContent).toContain("76 %");
    expect(screen.getByText("Identidad").parentElement?.textContent).toContain("81 %");
  });

  it("lets a doubtful segment be accepted and removed from the review queue by the store callback", () => {
    const onEdit = vi.fn();
    render(<TranscriptPanel
      {...baseProps}
      onEdit={onEdit}
      currentTimeMs={100}
      segments={[{ ...segments[0], confidence: 0.79 }]}
    />);

    fireEvent.click(screen.getByRole("button", { name: /Texto correcto/i }));

    expect(onEdit).toHaveBeenCalledWith("s1", "Primer fragmento", true);
  });

  it("does not count an already corrected low-confidence segment as pending", () => {
    render(<TranscriptPanel
      {...baseProps}
      currentTimeMs={100}
      segments={[{ ...segments[0], confidence: 0.65, reviewState: "corrected" }]}
    />);

    expect(screen.queryByRole("button", { name: /Texto correcto/i })).toBeNull();
    expect(screen.queryByTitle("Mostrar fragmentos que merecen revisión")).toBeNull();
    expect(screen.getByText("Texto corregido")).toBeTruthy();
  });

  it("keeps voice review pending after only the text is accepted", () => {
    const onEdit = vi.fn();
    const onSpeakerReview = vi.fn();
    render(<TranscriptPanel
      {...baseProps}
      onEdit={onEdit}
      onSpeakerReview={onSpeakerReview}
      currentTimeMs={100}
      segments={[{
        ...segments[0],
        confidence: 0.75,
        speaker: "Isabel",
        speakerConfidence: 0.67,
        reviewState: "accepted",
      }]}
    />);

    expect(screen.queryByRole("button", { name: /Texto correcto/i })).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: /Voz correcta/i }));

    expect(onEdit).not.toHaveBeenCalled();
    expect(onSpeakerReview).toHaveBeenCalledWith("s1");
  });
});
