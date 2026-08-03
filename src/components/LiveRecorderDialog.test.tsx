// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { LiveRecorderDialog } from "./LiveRecorderDialog";

const { startEngine, startSession, pushAudio, stopSession, cancelSession, captureStart, capturePause, captureResume, captureStop } = vi.hoisted(() => ({
  startEngine: vi.fn().mockResolvedValue(undefined),
  startSession: vi.fn().mockResolvedValue({ sessionId: "recording-1", sampleRate: 16000, createdAt: "2026-08-02T12:00:00Z" }),
  pushAudio: vi.fn().mockResolvedValue({ sessionId: "recording-1", durationMs: 1000, duplicate: false }),
  stopSession: vi.fn().mockResolvedValue({ sessionId: "recording-1", mediaPath: "C:\\recordings\\Grabación.wav", durationMs: 1000, language: "es", createdAt: "2026-08-02T12:00:00Z" }),
  cancelSession: vi.fn().mockResolvedValue({ cancelled: true }),
  captureStart: vi.fn().mockResolvedValue(undefined),
  capturePause: vi.fn().mockResolvedValue(undefined),
  captureResume: vi.fn().mockResolvedValue(undefined),
  captureStop: vi.fn().mockResolvedValue(undefined),
}));

vi.mock("../lib/engine", () => ({
  engine: {
    start: startEngine,
    startRecordingSession: startSession,
    pushRecordingAudio: pushAudio,
    stopRecordingSession: stopSession,
    cancelRecordingSession: cancelSession,
  },
}));

vi.mock("../lib/liveAudio", () => ({
  LiveAudioCapture: class {
    start = captureStart;
    pause = capturePause;
    resume = captureResume;
    stop = captureStop;
  },
}));

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

describe("grabadora local", () => {
  it("muestra sólo captura, fuente e idioma, sin IA en directo", () => {
    render(<LiveRecorderDialog audioSource="microphone" language="es" onAudioSourceChange={() => undefined} onLanguageChange={() => undefined} onComplete={() => undefined} onClose={() => undefined} />);

    expect(screen.getByRole("heading", { name: "Grabadora de voz" })).toBeTruthy();
    expect(screen.getByLabelText("Fuente de audio")).toBeTruthy();
    expect(screen.getByLabelText("Idioma de la futura transcripción")).toBeTruthy();
    expect(screen.queryByText(/Separar hablantes/)).toBeNull();
    expect(screen.queryByText(/Piloto automático/)).toBeNull();
    expect(screen.queryByText(/Crear versión final/)).toBeNull();
    expect(screen.queryByText(/transcripción en tiempo real/i)).toBeNull();
    expect(document.querySelectorAll(".recorder-particle-path")).toHaveLength(6);
  });

  it("permite grabar, pausar, reanudar y finalizar el WAV", async () => {
    const onComplete = vi.fn();
    render(<LiveRecorderDialog audioSource="microphone" language="es" onAudioSourceChange={() => undefined} onLanguageChange={() => undefined} onComplete={onComplete} onClose={() => undefined} />);

    fireEvent.click(screen.getByRole("button", { name: /Empezar a grabar/ }));
    await waitFor(() => expect(startSession).toHaveBeenCalledWith("es"));
    await waitFor(() => expect(screen.getByRole("button", { name: "Pausar grabación" })).toBeTruthy());

    fireEvent.click(screen.getByRole("button", { name: "Pausar grabación" }));
    await waitFor(() => expect(capturePause).toHaveBeenCalled());
    fireEvent.click(screen.getByRole("button", { name: "Reanudar grabación" }));
    await waitFor(() => expect(captureResume).toHaveBeenCalled());
    fireEvent.click(screen.getByRole("button", { name: /Finalizar y guardar/ }));

    await waitFor(() => expect(stopSession).toHaveBeenCalledWith("recording-1"));
    await waitFor(() => expect(onComplete).toHaveBeenCalledWith(expect.objectContaining({ mediaPath: expect.stringContaining("Grabación.wav") })));
  });

  it("solicita el audio mientras el motor termina de arrancar", async () => {
    let finishEngineStart!: () => void;
    startEngine.mockImplementationOnce(() => new Promise<void>((resolve) => {
      finishEngineStart = resolve;
    }));
    render(<LiveRecorderDialog audioSource="microphone" language="es" onAudioSourceChange={() => undefined} onLanguageChange={() => undefined} onComplete={() => undefined} onClose={() => undefined} />);

    fireEvent.click(screen.getByRole("button", { name: /Empezar a grabar/ }));

    await waitFor(() => expect(startEngine).toHaveBeenCalled());
    expect(captureStart).toHaveBeenCalledWith("microphone");
    expect(startSession).not.toHaveBeenCalled();
    finishEngineStart();
    await waitFor(() => expect(startSession).toHaveBeenCalledWith("es"));
  });
});
