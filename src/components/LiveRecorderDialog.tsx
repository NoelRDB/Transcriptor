import { useEffect, useRef, useState } from "react";
import type { CSSProperties } from "react";
import { AudioLines, CheckCircle2, CircleHelp, CircleStop, Cpu, Flag, Gauge, Languages, ListTodo, LoaderCircle, Mic, Mic2, Radio, ShieldCheck, SlidersHorizontal, Sparkles, TimerReset, Users, X } from "lucide-react";
import { engine } from "../lib/engine";
import { LiveAudioCapture } from "../lib/liveAudio";
import { speakerClassName } from "../lib/speakers";
import { formatClock } from "../lib/time";
import type { EngineEvent, LiveAudioSource, LiveSessionResult, ProjectSettings, TranscriptSegment } from "../types";

interface LiveRecorderDialogProps {
  settings: ProjectSettings;
  audioSource: LiveAudioSource;
  onAudioSourceChange: (source: LiveAudioSource) => void;
  onLanguageChange: (language: string) => void;
  onComplete: (result: LiveSessionResult, refineAfterStop: boolean) => void;
  onClose: () => void;
}

type RecorderState = "ready" | "requesting" | "recording" | "stopping" | "failed";
type EngineStage = "idle" | "model_loading" | "ready" | "failed";

const METER_BARS = [0.3, 0.52, 0.76, 0.46, 0.9, 0.62, 1, 0.7, 0.43, 0.84, 0.58, 0.34] as const;

export function LiveRecorderDialog({ settings, audioSource, onAudioSourceChange, onLanguageChange, onComplete, onClose }: LiveRecorderDialogProps) {
  const [state, setState] = useState<RecorderState>("ready");
  const [engineStage, setEngineStage] = useState<EngineStage>("idle");
  const [separateSpeakers, setSeparateSpeakers] = useState(true);
  const [refineAfterStop, setRefineAfterStop] = useState(false);
  const [selectedLanguage, setSelectedLanguage] = useState(settings.language && settings.language !== "auto" ? settings.language : "es");
  const [segments, setSegments] = useState<TranscriptSegment[]>([]);
  const [durationMs, setDurationMs] = useState(0);
  const [level, setLevel] = useState(0);
  const [pendingBlocks, setPendingBlocks] = useState(0);
  const [status, setStatus] = useState("Todo listo para comenzar");
  const [device, setDevice] = useState("Automático");
  const [language, setLanguage] = useState("Detectando");
  const [speakerCount, setSpeakerCount] = useState(0);
  const [speakerBackend, setSpeakerBackend] = useState("Preparando");
  const [speakerSensitivity, setSpeakerSensitivity] = useState(settings.speakerSensitivity);
  const [speakerCountMode, setSpeakerCountMode] = useState(settings.speakerCountMode);
  const [speakerLimit, setSpeakerLimit] = useState(settings.speakerCount);
  const [liveLatency, setLiveLatency] = useState(settings.liveLatency);
  const [lastLatencyMs, setLastLatencyMs] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [markers, setMarkers] = useState<Array<{ timeMs: number; kind: string; label: string }>>([]);
  const captureRef = useRef<LiveAudioCapture | null>(null);
  const sessionIdRef = useRef<string | null>(null);
  const queueRef = useRef<Promise<void>>(Promise.resolve());
  const transcriptEndRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const unsubscribe = engine.subscribe((event: EngineEvent) => {
      if (event.type !== "live_status" && event.type !== "live_partial") return;
      const payload = event.payload as { sessionId?: string; message?: string; stage?: EngineStage; device?: string; language?: string; speakerBackend?: string; segment?: TranscriptSegment };
      if (sessionIdRef.current && payload.sessionId !== sessionIdRef.current) return;
      if (event.type === "live_partial" && payload.segment) {
        setSegments((current) => mergeLiveSegments(current, [payload.segment!]));
        if (payload.language) setLanguage(payload.language.toUpperCase());
        if (payload.device) setDevice(payload.device);
        if (payload.speakerBackend) setSpeakerBackend(payload.speakerBackend);
        setStatus("Texto actualizado · seguimos escuchando");
        return;
      }
      if (payload.stage) setEngineStage(payload.stage);
      if (payload.device) setDevice(payload.device);
      if (payload.speakerBackend) setSpeakerBackend(payload.speakerBackend);
      if (payload.message) setStatus(payload.message);
      if (payload.stage === "failed" && payload.message) setError(payload.message);
    });
    return unsubscribe;
  }, []);

  useEffect(() => {
    if (state !== "recording") return;
    const timer = window.setInterval(() => setDurationMs((value) => value + 250), 250);
    return () => window.clearInterval(timer);
  }, [state]);

  useEffect(() => {
    transcriptEndRef.current?.scrollIntoView({ block: "nearest", behavior: "smooth" });
  }, [segments.length]);

  async function startRecording() {
    setState("requesting");
    setEngineStage("model_loading");
    setError(null);
    setSegments([]);
    setDurationMs(0);
    setPendingBlocks(0);
    setLastLatencyMs(null);
    setSpeakerCount(0);
    setMarkers([]);
    setLanguage(selectedLanguage === "auto" ? "Detectando" : selectedLanguage.toUpperCase());
    setStatus("Preparando el micrófono y el modelo Turbo…");
    queueRef.current = Promise.resolve();
    try {
      const session = await engine.startLiveSession({ ...settings, language: selectedLanguage, speakerSensitivity, speakerCountMode, speakerCount: speakerLimit, liveLatency }, separateSpeakers);
      sessionIdRef.current = session.sessionId;
      if (session.speakerBackend) setSpeakerBackend(session.speakerBackend);
      const capture = new LiveAudioCapture(enqueueChunk, setLevel, liveLatency);
      captureRef.current = capture;
      await capture.start(audioSource);
      setState("recording");
      setStatus("Escuchando · habla con naturalidad");
    } catch (reason) {
      const sessionId = sessionIdRef.current;
      if (sessionId) await engine.cancelLiveSession(sessionId).catch(() => undefined);
      sessionIdRef.current = null;
      setError(friendlyMicrophoneError(reason));
      setEngineStage("failed");
      setState("failed");
    }
  }

  function enqueueChunk(pcmBase64: string) {
    const sessionId = sessionIdRef.current;
    if (!sessionId) return;
    setPendingBlocks((value) => value + 1);
    queueRef.current = queueRef.current
      .then(async () => {
        setStatus("Comprendiendo la última frase…");
        const result = await engine.pushLiveAudio(sessionId, pcmBase64);
        if (result.segments.length) setSegments((current) => mergeLiveSegments(current, result.segments));
        setDurationMs((current) => Math.max(current, result.durationMs));
        setLastLatencyMs(result.latencyMs);
        setSpeakerCount(result.speakerCount);
        if (result.speakerBackend) setSpeakerBackend(result.speakerBackend);
        setDevice(result.device);
        if (result.language) setLanguage(result.language.toUpperCase());
        setStatus(result.segments.length ? "Transcripción al día · seguimos escuchando" : "Escuchando · esperando una frase clara");
      })
      .catch((reason) => {
        setError(reason instanceof Error ? reason.message : String(reason));
        setStatus("Un fragmento no pudo transcribirse; el audio continúa guardándose");
      })
      .finally(() => setPendingBlocks((value) => Math.max(0, value - 1)));
  }

  async function stopRecording() {
    const sessionId = sessionIdRef.current;
    if (!sessionId) return;
    setState("stopping");
    setStatus("Terminando la última frase y guardando el WAV…");
    try {
      await captureRef.current?.stop(true);
      await queueRef.current;
      const result = await engine.stopLiveSession(sessionId);
      sessionIdRef.current = null;
      onComplete({ ...result, markers }, refineAfterStop);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : String(reason));
      setState("failed");
    }
  }

  async function cancelAndClose() {
    if (state === "recording" || state === "stopping") return;
    const sessionId = sessionIdRef.current;
    await captureRef.current?.stop(false).catch(() => undefined);
    if (sessionId) await engine.cancelLiveSession(sessionId).catch(() => undefined);
    sessionIdRef.current = null;
    onClose();
  }

  const working = state === "requesting" || state === "stopping";
  const recording = state === "recording";
  const hearingSpeech = recording && level > 0.075;
  const visibleSegments = segments.slice(-80);

  return (
    <div className="modal-backdrop live-backdrop" role="presentation">
      <section className="live-dialog" role="dialog" aria-modal="true" aria-labelledby="live-title">
        <header className="live-header">
          <div><span>ESTUDIO EN DIRECTO</span><h2 id="live-title"><Mic2 size={22} /> Transcripción en tiempo real</h2><p>Habla con naturalidad: el texto se confirma cada vez que completas una frase.</p></div>
          <div className="live-header-actions">
            <span className="live-mode-pill">{settings.experienceMode === "simple" ? <Sparkles size={12} /> : <SlidersHorizontal size={12} />}{settings.experienceMode === "simple" ? "Modo sencillo" : "Modo avanzado"}</span>
            <span className={`live-engine-pill ${engineStage}`}><i />{engineStage === "ready" ? "Motor listo" : engineStage === "model_loading" ? "Preparando IA" : engineStage === "failed" ? "Revisar motor" : "Modo local"}</span>
            <button className="icon-button" disabled={recording || working} onClick={cancelAndClose} aria-label="Cerrar"><X size={19} /></button>
          </div>
        </header>

        <aside className="live-control-panel">
          <div className="live-recorder-card">
            <div className={`microphone-orb ${recording ? "active" : ""}`} style={{ "--pulse-scale": 1 + level * .22, "--pulse-scale-mid": 1 + level * .15, "--pulse-scale-outer": 1 + level * .09, "--pulse-opacity": .3 + level * .5, "--pulse-opacity-outer": .15 + level * .35 } as CSSProperties}><span><Mic size={29} /></span><i /><i /><i /></div>
            <strong className="live-clock">{formatClock(durationMs)}</strong>
            <div className="live-status" aria-live="polite">{working && <LoaderCircle className="spin" size={14} />}<span>{status}</span></div>
            <div className={`live-level-meter ${hearingSpeech ? "speaking" : ""}`} aria-label={hearingSpeech ? "Voz detectada" : "Esperando voz"}>
              {METER_BARS.map((factor) => <i key={factor} style={{ height: `${Math.max(8, factor * (14 + level * 22))}px`, opacity: Math.max(.22, Math.min(1, .25 + level * factor * 1.5)) }} />)}
            </div>
            <span className="live-listening-label"><Radio size={12} />{hearingSpeech ? "Voz detectada" : recording ? "Escuchando" : "Micrófono detenido"}</span>
          </div>

          <dl className="live-metrics">
            <div><dt><Cpu size={14} /> Motor</dt><dd>{device}</dd></div>
            <div><dt><Languages size={14} /> Idioma</dt><dd>{language}</dd></div>
            <div><dt><Gauge size={14} /> Latencia</dt><dd>{lastLatencyMs === null ? "—" : lastLatencyMs < 1000 ? `${lastLatencyMs} ms` : `${(lastLatencyMs / 1000).toFixed(1)} s`}</dd></div>
            <div><dt><TimerReset size={14} /> Cola</dt><dd className={pendingBlocks > 1 ? "metric-warning" : ""}>{pendingBlocks ? `${pendingBlocks} bloque${pendingBlocks === 1 ? "" : "s"}` : "Al día"}</dd></div>
            <div><dt><Users size={14} /> Voces IA</dt><dd>{separateSpeakers ? speakerBackend : "Desactivada"}</dd></div>
            <div><dt><Radio size={14} /> Respuesta</dt><dd>{liveLatency === "ultra" ? "Ultrabaja" : liveLatency === "stable" ? "Estable" : "Equilibrada"}</dd></div>
          </dl>

          <label className="live-language-option">
            <span className="live-option-icon"><AudioLines size={18} /></span>
            <span><strong>Fuente de audio</strong><small>Micrófono, sonido del ordenador o ambos mezclados.</small></span>
            <select value={audioSource} disabled={state !== "ready" && state !== "failed"} onChange={(event) => onAudioSourceChange(event.target.value as LiveAudioSource)} aria-label="Fuente de audio en directo">
              <option value="microphone">Micrófono</option>
              <option value="system">Audio del sistema</option>
              <option value="mixed">Micrófono + sistema</option>
            </select>
          </label>

          <label className="live-language-option">
            <span className="live-option-icon"><Languages size={18} /></span>
            <span><strong>Idioma de la conversación</strong><small>Fijarlo evita que la IA confunda idiomas parecidos.</small></span>
            <select value={selectedLanguage} disabled={state !== "ready" && state !== "failed"} onChange={(event) => { setSelectedLanguage(event.target.value); setLanguage(event.target.value === "auto" ? "Detectando" : event.target.value.toUpperCase()); onLanguageChange(event.target.value); }} aria-label="Idioma de la transcripción en directo">
              <option value="es">Español</option>
              <option value="en">Inglés</option>
              <option value="fr">Francés</option>
              <option value="de">Alemán</option>
              <option value="it">Italiano</option>
              <option value="pt">Portugués</option>
              <option value="ca">Catalán</option>
              <option value="gl">Gallego</option>
              <option value="auto">Detectar automáticamente</option>
            </select>
          </label>

          <label className={`speaker-option ${separateSpeakers ? "selected" : ""}`}>
            <input type="checkbox" checked={separateSpeakers} disabled={state !== "ready" && state !== "failed"} onChange={(event) => setSeparateSpeakers(event.target.checked)} />
            <Users size={18} />
            <span><strong>Separar hablantes con IA</strong><small>Compara timbre, prosodia y huellas neuronales; el número puede decidirse automáticamente.</small></span>
            {separateSpeakers && <CheckCircle2 size={17} />}
          </label>

          {settings.experienceMode === "simple" ? <div className="live-simple-voice"><Sparkles size={15} /><span><strong>Piloto automático activo</strong><small>Número de voces automático · sensibilidad adaptativa · retardo ajustado al equipo</small></span></div> :
            <div className="live-advanced-voice">
              <label><span>Número de voces</span><select value={speakerCountMode} disabled={recording || working} onChange={(event) => setSpeakerCountMode(event.target.value as ProjectSettings["speakerCountMode"])}><option value="auto">Automático</option><option value="exact">Exactamente</option></select></label>
              <label><span>{speakerCountMode === "exact" ? "N.º de hablantes" : "Máximo"}</span><select value={speakerLimit} disabled={recording || working} onChange={(event) => setSpeakerLimit(Number(event.target.value))}>{[1, 2, 3, 4, 5, 6, 7, 8].map((count) => <option key={count} value={count}>{count} hablante{count === 1 ? "" : "s"}</option>)}</select></label>
              <label><span>Sensibilidad</span><div><input aria-label="Sensibilidad de voces" type="range" min={20} max={90} value={speakerSensitivity} disabled={recording || working} onChange={(event) => setSpeakerSensitivity(Number(event.target.value))} /><output>{speakerSensitivity}</output></div></label>
              <label><span>Retardo</span><select value={liveLatency} disabled={recording || working} onChange={(event) => setLiveLatency(event.target.value as ProjectSettings["liveLatency"])}><option value="ultra">Ultrabajo</option><option value="balanced">Equilibrado</option><option value="stable">Más contexto</option></select></label>
            </div>}

          <label className={`speaker-option refine-option ${refineAfterStop ? "selected" : ""}`}>
            <input type="checkbox" checked={refineAfterStop} disabled={state !== "ready" && state !== "failed"} onChange={(event) => setRefineAfterStop(event.target.checked)} />
            <Sparkles size={18} />
            <span><strong>Crear versión final al detener</strong><small>Conserva el borrador inmediato y después revisa el WAV completo con máxima precisión. Puede requerir Large-v3.</small></span>
            {refineAfterStop && <CheckCircle2 size={17} />}
          </label>

          {error && <p className="live-error" role="alert">{error}</p>}
          <div className="live-privacy"><ShieldCheck size={14} /><span>Audio WAV y texto procesados sólo en este equipo</span></div>

          <div className="live-marker-tools" aria-label="Marcadores en directo">
            <span>{markers.length ? `${markers.length} marcador${markers.length === 1 ? "" : "es"}` : "Marcar este instante"}</span>
            <div><button disabled={!recording} onClick={() => setMarkers((items) => [...items, { timeMs: durationMs, kind: "important", label: "Importante" }])}><Flag size={13} /> Importante</button><button disabled={!recording} onClick={() => setMarkers((items) => [...items, { timeMs: durationMs, kind: "task", label: "Tarea" }])}><ListTodo size={13} /> Tarea</button><button disabled={!recording} onClick={() => setMarkers((items) => [...items, { timeMs: durationMs, kind: "question", label: "Pregunta" }])}><CircleHelp size={13} /> Pregunta</button></div>
          </div>

          <div className="live-main-actions">
            {recording ? <button className="button danger live-stop" onClick={stopRecording}><CircleStop size={17} /> Detener y crear proyecto</button> : <button className="button primary live-start" disabled={working} onClick={startRecording}>{working ? <LoaderCircle className="spin" size={17} /> : <Mic size={17} />}{state === "failed" ? "Intentar de nuevo" : "Empezar a transcribir"}</button>}
            <small>{recording ? "La grabación y todo el texto se conservarán al detener." : "Puedes cerrar sin crear ningún archivo mientras no hayas empezado."}</small>
          </div>
        </aside>

        <section className="live-transcript" aria-label="Transcripción en directo">
          <header className="live-transcript-title">
            <span><i className={recording ? "active" : ""} /> TRANSCRIPCIÓN</span>
            <strong>{segments.length ? `${segments.length} intervención${segments.length === 1 ? "" : "es"}` : "Esperando voz"}{speakerCount > 1 ? ` · ${speakerCount} hablantes` : ""}</strong>
          </header>
          <div className="live-segments">
            {visibleSegments.length ? visibleSegments.map((segment) => <article key={segment.id}><div><span className={speakerClassName(segment.speaker)}>{segment.speaker ?? "Hablante sin identificar"}{segment.speakerProvisional ? " · provisional" : ""}</span><time>{segment.speakerConfidence != null ? `${Math.round(segment.speakerConfidence * 100)} % voz · ` : ""}{formatClock(segment.startMs)}</time></div><p>{segment.text}</p></article>) : <div className="live-empty"><span><AudioLines size={28} /></span><strong>Tu conversación aparecerá aquí</strong><p>El primer texto puede tardar un poco mientras Turbo se prepara. Después se actualizará al terminar cada frase.</p></div>}
            {hearingSpeech && <div className="live-draft"><AudioLines size={16} /><span><strong>Escuchando la frase actual…</strong><small>Se mostrará cuando la IA confirme las palabras.</small></span></div>}
            <div ref={transcriptEndRef} />
          </div>
        </section>
      </section>
    </div>
  );
}

function mergeLiveSegments(current: TranscriptSegment[], incoming: TranscriptSegment[]): TranscriptSegment[] {
  const merged = new Map(current.map((segment) => [segment.id, segment]));
  incoming.forEach((segment) => merged.set(segment.id, segment));
  return [...merged.values()].sort((left, right) => left.startMs - right.startMs || left.order - right.order);
}

function friendlyMicrophoneError(reason: unknown): string {
  if (reason instanceof DOMException && reason.name === "NotAllowedError") return "Windows ha bloqueado el micrófono. Permite el acceso y vuelve a intentarlo.";
  if (reason instanceof DOMException && reason.name === "NotFoundError") return "No se ha encontrado ningún micrófono disponible.";
  return reason instanceof Error ? reason.message : String(reason);
}
