import { useEffect, useMemo, useRef, useState } from "react";
import { AudioLines, CircleStop, Headphones, Languages, LoaderCircle, Mic, Pause, Play, ShieldCheck, X } from "lucide-react";
import { engine } from "../lib/engine";
import { LiveAudioCapture } from "../lib/liveAudio";
import { formatClock } from "../lib/time";
import type { LiveAudioSource, RecordingSessionResult } from "../types";

interface LiveRecorderDialogProps {
  audioSource: LiveAudioSource;
  language: string;
  onAudioSourceChange: (source: LiveAudioSource) => void;
  onLanguageChange: (language: string) => void;
  onComplete: (result: RecordingSessionResult) => void;
  onClose: () => void;
}

type RecorderState = "ready" | "requesting" | "recording" | "paused" | "stopping" | "failed";

const WAVE_POINTS = 96;
const EMPTY_WAVE = Array.from({ length: WAVE_POINTS }, () => 0);
const PARTICLE_LAYERS = [
  { scale: 1, phase: 0, offset: 0 },
  { scale: -0.88, phase: 0.22, offset: 0 },
  { scale: 0.64, phase: 0.62, offset: -10 },
  { scale: -0.56, phase: 0.92, offset: 10 },
  { scale: 0.34, phase: 1.45, offset: -20 },
  { scale: -0.28, phase: 1.8, offset: 20 },
] as const;

const LANGUAGES = [
  ["es", "Español"],
  ["en", "Inglés"],
  ["fr", "Francés"],
  ["de", "Alemán"],
  ["it", "Italiano"],
  ["pt", "Portugués"],
  ["ca", "Catalán"],
  ["gl", "Gallego"],
  ["auto", "Detectar al transcribir"],
] as const;

export function LiveRecorderDialog({ audioSource, language, onAudioSourceChange, onLanguageChange, onComplete, onClose }: LiveRecorderDialogProps) {
  const [state, setState] = useState<RecorderState>("ready");
  const [selectedLanguage, setSelectedLanguage] = useState(language || "es");
  const [durationMs, setDurationMs] = useState(0);
  const [wave, setWave] = useState<number[]>(EMPTY_WAVE);
  const [status, setStatus] = useState("Listo para grabar");
  const [error, setError] = useState<string | null>(null);
  const captureRef = useRef<LiveAudioCapture | null>(null);
  const sessionIdRef = useRef<string | null>(null);
  const queueRef = useRef<Promise<void>>(Promise.resolve());
  const chunkIdRef = useRef(0);

  useEffect(() => () => {
    void captureRef.current?.stop(false).catch(() => undefined);
    const sessionId = sessionIdRef.current;
    if (sessionId) void engine.cancelRecordingSession(sessionId).catch(() => undefined);
  }, []);

  const waveformPaths = useMemo(
    () => PARTICLE_LAYERS.map((layer) => buildParticleWavePath(wave, 720, 176, layer.scale, layer.phase, layer.offset)),
    [wave],
  );
  const level = wave[wave.length - 1] ?? 0;
  const active = state === "recording" || state === "paused";
  const working = state === "requesting" || state === "stopping";
  const hearingSound = state === "recording" && level > 0.045;

  function updateLevel(nextLevel: number) {
    setWave((current) => [...current.slice(1), nextLevel]);
  }

  async function startRecording() {
    setState("requesting");
    setError(null);
    setDurationMs(0);
    setWave(EMPTY_WAVE);
    setStatus("Solicitando acceso al audio…");
    queueRef.current = Promise.resolve();
    chunkIdRef.current = 0;
    try {
      const session = await engine.startRecordingSession(selectedLanguage);
      sessionIdRef.current = session.sessionId;
      const capture = new LiveAudioCapture(
        enqueueChunk,
        updateLevel,
        "balanced",
        setDurationMs,
        "recording",
      );
      captureRef.current = capture;
      await capture.start(audioSource);
      setState("recording");
      setStatus("Grabando en este equipo");
    } catch (reason) {
      const sessionId = sessionIdRef.current;
      if (sessionId) await engine.cancelRecordingSession(sessionId).catch(() => undefined);
      sessionIdRef.current = null;
      setError(friendlyMicrophoneError(reason));
      setState("failed");
      setStatus("No se pudo iniciar la grabación");
    }
  }

  function enqueueChunk(pcmBase64: string) {
    const sessionId = sessionIdRef.current;
    if (!sessionId) return;
    const chunkId = chunkIdRef.current;
    chunkIdRef.current += 1;
    queueRef.current = queueRef.current.then(async () => {
      try {
        const result = await engine.pushRecordingAudio(sessionId, pcmBase64, chunkId);
        setDurationMs((current) => Math.max(current, result.durationMs));
      } catch {
        try {
          const result = await engine.pushRecordingAudio(sessionId, pcmBase64, chunkId);
          setDurationMs((current) => Math.max(current, result.durationMs));
        } catch (reason) {
          setError(`No se pudo guardar un bloque de audio: ${reason instanceof Error ? reason.message : String(reason)}`);
          setStatus("La grabación necesita atención antes de finalizar");
        }
      }
    });
  }

  async function pauseRecording() {
    try {
      await captureRef.current?.pause();
      await queueRef.current;
      setState("paused");
      setStatus("Grabación en pausa");
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : String(reason));
    }
  }

  async function resumeRecording() {
    try {
      await captureRef.current?.resume();
      setState("recording");
      setStatus("Grabando en este equipo");
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : String(reason));
    }
  }

  async function stopRecording() {
    const sessionId = sessionIdRef.current;
    if (!sessionId) return;
    setState("stopping");
    setStatus("Cerrando el WAV y creando el proyecto…");
    try {
      await captureRef.current?.stop(true);
      await queueRef.current;
      const result = await engine.stopRecordingSession(sessionId);
      sessionIdRef.current = null;
      captureRef.current = null;
      onComplete(result);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : String(reason));
      setState("failed");
      setStatus("No se pudo finalizar la grabación");
    }
  }

  async function closeRecorder() {
    if (active || working) return;
    const sessionId = sessionIdRef.current;
    await captureRef.current?.stop(false).catch(() => undefined);
    if (sessionId) await engine.cancelRecordingSession(sessionId).catch(() => undefined);
    sessionIdRef.current = null;
    onClose();
  }

  return (
    <div className="modal-backdrop live-backdrop" role="presentation">
      <section className="recorder-dialog" role="dialog" aria-modal="true" aria-labelledby="recorder-title">
        <header className="recorder-header">
          <div className="recorder-title-mark"><Mic size={22} /></div>
          <div><span>GRABACIÓN LOCAL</span><h2 id="recorder-title">Grabadora de voz</h2><p>Captura el audio ahora. La IA trabajará después, cuando pulses Transcribir.</p></div>
          <button className="icon-button" disabled={active || working} onClick={() => void closeRecorder()} aria-label="Cerrar grabadora" title={active ? "Detén la grabación antes de cerrar" : "Cerrar"}><X size={19} /></button>
        </header>

        <div className="recorder-body">
          <section className={`recorder-stage ${state}`} aria-label="Estado de la grabación">
            <div className="recorder-state-line">
              <span className={`recorder-live-dot ${state === "recording" ? "active" : ""}`} />
              <strong>{state === "recording" ? "GRABANDO" : state === "paused" ? "EN PAUSA" : working ? "GUARDANDO" : "PREPARADO"}</strong>
              <span>{hearingSound ? "Sonido detectado" : state === "recording" ? "Escuchando" : state === "paused" ? "El audio no avanza" : "WAV · 16 kHz"}</span>
            </div>

            <div className="recorder-wave" aria-label={hearingSound ? "Nivel de audio activo" : "Nivel de audio bajo"}>
              <svg viewBox="0 0 720 176" preserveAspectRatio="none" role="img" aria-hidden="true">
                <defs>
                  <linearGradient id="recorder-wave-gradient" x1="0" x2="1">
                    <stop offset="0" stopColor="#78d8ff" />
                    <stop offset="0.5" stopColor="#cbff3d" />
                    <stop offset="1" stopColor="#ff7772" />
                  </linearGradient>
                  <filter id="recorder-particle-glow" x="-20%" y="-40%" width="140%" height="180%">
                    <feGaussianBlur stdDeviation="4" />
                  </filter>
                </defs>
                <line x1="0" y1="88" x2="720" y2="88" className="recorder-wave-axis" />
                <path d={waveformPaths[0]} className="recorder-particle-glow" vectorEffect="non-scaling-stroke" />
                <g className={`recorder-particle-field ${hearingSound ? "active" : ""}`}>
                  {waveformPaths.map((path, index) => <path key={index} d={path} className={`recorder-particle-path layer-${index + 1}`} vectorEffect="non-scaling-stroke" />)}
                </g>
              </svg>
            </div>

            <div className="recorder-clock" aria-live="off">{formatClock(durationMs)}</div>
            <div className="recorder-status" aria-live="polite">{working && <LoaderCircle className="spin" size={15} />}<span>{status}</span></div>

            <div className="recorder-controls">
              {!active ? (
                <button className="recorder-primary" disabled={working} onClick={() => void startRecording()}>
                  {working ? <LoaderCircle className="spin" size={22} /> : <Mic size={22} />}
                  <span>{state === "failed" ? "Intentar de nuevo" : "Empezar a grabar"}</span>
                </button>
              ) : (
                <>
                  <button className="recorder-round secondary" onClick={() => void (state === "paused" ? resumeRecording() : pauseRecording())} aria-label={state === "paused" ? "Reanudar grabación" : "Pausar grabación"}>
                    {state === "paused" ? <Play size={23} fill="currentColor" /> : <Pause size={23} fill="currentColor" />}
                  </button>
                  <button className="recorder-primary stop" onClick={() => void stopRecording()}><CircleStop size={22} /><span>Finalizar y guardar</span></button>
                </>
              )}
            </div>
          </section>

          <section className="recorder-options" aria-label="Opciones de grabación">
            <div className="recorder-option-heading"><span>Antes de grabar</span><small>Dos decisiones. Nada más.</small></div>
            <label className="recorder-option">
              <span className="recorder-option-icon"><Headphones size={19} /></span>
              <span><strong>Fuente de audio</strong><small>Elige qué sonido quieres conservar.</small></span>
              <select value={audioSource} disabled={state !== "ready" && state !== "failed"} onChange={(event) => onAudioSourceChange(event.target.value as LiveAudioSource)} aria-label="Fuente de audio">
                <option value="microphone">Micrófono</option>
                <option value="system">Audio del sistema</option>
                <option value="mixed">Micrófono + sistema</option>
              </select>
            </label>
            <label className="recorder-option">
              <span className="recorder-option-icon"><Languages size={19} /></span>
              <span><strong>Idioma para después</strong><small>Se aplicará cuando transcribas el proyecto.</small></span>
              <select value={selectedLanguage} disabled={state !== "ready" && state !== "failed"} onChange={(event) => { setSelectedLanguage(event.target.value); onLanguageChange(event.target.value); }} aria-label="Idioma de la futura transcripción">
                {LANGUAGES.map(([value, label]) => <option key={value} value={value}>{label}</option>)}
              </select>
            </label>

            <div className="recorder-after-card">
              <span><AudioLines size={19} /></span>
              <div><strong>Al finalizar</strong><p>Se abrirá un proyecto con el WAV listo. La transcripción, los párrafos, la separación de hablantes y el reconocimiento de perfiles se harán juntos al pulsar <b>Transcribir</b>.</p></div>
            </div>
            {error && <p className="live-error" role="alert">{error}</p>}
            <div className="recorder-privacy"><ShieldCheck size={15} /><span>Sin nube · sin transcripción durante la captura · sin IA de voces en segundo plano</span></div>
          </section>
        </div>
      </section>
    </div>
  );
}

function buildParticleWavePath(levels: number[], width: number, height: number, scale: number, phase: number, offset: number): string {
  const center = height / 2;
  const step = width / Math.max(1, levels.length - 1);
  return levels.map((value, index) => {
    const activity = Math.max(0.018, Math.min(1, value));
    const carrier = Math.sin(index * 0.63 + phase) * 0.68 + Math.sin(index * 0.19 + phase * 1.7) * 0.32;
    const y = center + offset + carrier * (4 + activity * height * 0.36) * scale;
    return `${index ? "L" : "M"}${(index * step).toFixed(2)},${y.toFixed(2)}`;
  }).join(" ");
}

function friendlyMicrophoneError(reason: unknown): string {
  const message = reason instanceof Error ? reason.message : String(reason);
  if (/NotAllowed|Permission|denied|permiso/i.test(message)) return "Windows ha bloqueado el acceso. Permite el micrófono para Transcriptor en Configuración → Privacidad y seguridad → Micrófono.";
  if (/NotFound|device|dispositivo/i.test(message)) return "No se encontró una fuente de audio disponible. Conecta o habilita un micrófono e inténtalo de nuevo.";
  if (/audio del sistema|display|compartir/i.test(message)) return "Selecciona una ventana o pantalla y activa «Compartir audio del sistema» en el selector de Windows.";
  return message;
}
