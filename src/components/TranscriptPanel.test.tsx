// @vitest-environment jsdom

import { act, cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { TranscriptSegment } from "../types";
import { TranscriptPanel } from "./TranscriptPanel";

const segments: TranscriptSegment[] = [
  { id: "s1", startMs: 0, endMs: 900, text: "Primer fragmento", order: 0, words: [] },
  { id: "s2", startMs: 1200, endMs: 2200, text: "Segundo fragmento", order: 1, words: [] },
];

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
    render(<TranscriptPanel {...baseProps} currentTimeMs={100} onSpeakerChange={onSpeakerChange} />);

    fireEvent.click(screen.getAllByRole("button", { name: "Editar fragmento" })[0]);
    fireEvent.change(screen.getByRole("combobox", { name: "Hablante" }), { target: { value: "Hablante 2" } });
    fireEvent.click(screen.getByRole("button", { name: /Aplicar/i }));

    expect(onSpeakerChange).toHaveBeenCalledWith("s1", "Hablante 2");
  });
});
