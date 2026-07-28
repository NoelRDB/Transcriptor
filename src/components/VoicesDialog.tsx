import { useEffect, useState } from "react";
import {
  AudioWaveform,
  BrainCircuit,
  CheckCircle2,
  Fingerprint,
  LoaderCircle,
  ShieldCheck,
  Sparkles,
  Square,
  UserRoundCheck,
  X,
} from "lucide-react";
import { engine } from "../lib/engine";
import { formatClock } from "../lib/time";
import type {
  AppSettings,
  EngineEvent,
  TranscriptionProject,
  VoiceLearningProgress,
} from "../types";
import { VoiceProfilesSection } from "./VoiceProfilesSection";

interface VoicesDialogProps {
  settings: AppSettings;
  project: TranscriptionProject | null;
  appBusy: boolean;
  onChange: (settings: Partial<AppSettings>) => void;
  onClose: () => void;
}

const LEARNING_STAGES = [
  ["decoding", "Audio"],
  ["speaker_embedding", "Huellas"],
  ["speaker_alignment", "Similitud"],
  ["learning", "Memoria"],
  ["completed", "Listo"],
] as const;

function stageIndex(stage: VoiceLearningProgress["stage"]): number {
  if (stage === "speaker_alignment") return 2;
  if (stage === "learning") return 3;
  if (stage === "completed") return 4;
  if (stage === "speaker_embedding") return 1;
  return 0;
}

export function VoicesDialog({ settings, project, appBusy, onChange, onClose }: VoicesDialogProps) {
  const [progress, setProgress] = useState<VoiceLearningProgress | null>(null);
  const [error, setError] = useState("");
  const projectId = project?.id;
  const working = progress?.state === "running";
  const currentStage = stageIndex(progress?.stage ?? "decoding");
  const canLearn = Boolean(project?.segments.length && project.mediaPath && !appBusy);

  useEffect(() => engine.subscribe((event: EngineEvent) => {
    if (!event.type.startsWith("voice_learning_")) return;
    const payload = event.payload as VoiceLearningProgress;
    if (projectId && payload.projectId !== projectId) return;
    if (event.type === "voice_learning_progress" || event.type === "voice_learning_completed") {
      setProgress(payload);
      setError("");
    }
    if (event.type === "voice_learning_cancelled") {
      setProgress((current) => ({
        ...payload,
        stage: current?.stage ?? "decoding",
        phase: "Análisis cancelado",
        percent: current?.percent ?? 0,
      }));
    }
    if (event.type === "voice_learning_failed") {
      setProgress((current) => ({
        ...payload,
        stage: current?.stage ?? "decoding",
        phase: "No se pudieron analizar las voces",
        percent: current?.percent ?? 0,
      }));
      setError(payload.message);
    }
  }), [projectId]);

  async function learnCurrentProject() {
    if (!project) return;
    setError("");
    setProgress({
      projectId: project.id,
      state: "running",
      stage: "decoding",
      phase: "Preparando el análisis vocal",
      message: "Abriendo el audio original sin modificar la transcripción…",
      percent: 0,
    });
    onChange({ voiceProfilesEnabled: true, voiceProfileAutoLearn: true });
    try {
      await engine.learnProjectVoices(project.id);
    } catch (reason) {
      const message = reason instanceof Error ? reason.message : String(reason);
      setError(message);
      setProgress((current) => current ? {
        ...current,
        state: "failed",
        phase: "No se pudo iniciar",
        message,
      } : null);
    }
  }

  async function cancelLearning() {
    if (!project) return;
    await engine.cancelVoiceLearning(project.id).catch(() => undefined);
  }

  return <div className="modal-backdrop" onMouseDown={working ? undefined : onClose}>
    <section className="voices-dialog" role="dialog" aria-modal="true" aria-labelledby="voices-title" onMouseDown={(event) => event.stopPropagation()}>
      <header>
        <span className="voices-hero-icon"><Fingerprint /></span>
        <div>
          <small>IDENTIDAD DE VOZ · 100 % LOCAL</small>
          <h2 id="voices-title">Biblioteca de voces</h2>
          <p>Transcriptor aprende patrones de timbre, resonancia y prosodia para reconocer a las mismas personas en próximas conversaciones.</p>
        </div>
        <button className="icon-button" onClick={onClose} disabled={working} aria-label="Cerrar"><X /></button>
      </header>

      <div className="voices-scroll">
        <section className={`voice-learning-card ${working ? "working" : ""} ${progress?.state ?? "idle"}`}>
          <div className="voice-learning-lead">
            <span className="voice-learning-orbit">
              {working ? <LoaderCircle /> : progress?.state === "completed" ? <CheckCircle2 /> : <BrainCircuit />}
              {working ? <><i /><i /><i /></> : null}
            </span>
            <div>
              <small>PROYECTO ACTUAL</small>
              <strong>{project?.name ?? "No hay ningún proyecto abierto"}</strong>
              <p>{project
                ? `${project.segments.length} fragmentos · ${formatClock(project.durationMs)} · el texto no se modificará`
                : "Abre una grabación transcrita para añadir sus voces a la memoria."}</p>
            </div>
            {working
              ? <button className="button voice-stop" onClick={() => void cancelLearning()}><Square />Detener</button>
              : <button className="button primary" disabled={!canLearn} onClick={() => void learnCurrentProject()}><Sparkles />Aprender de este proyecto</button>}
          </div>

          {progress ? <div className="voice-learning-live" aria-live="polite">
            <div className="voice-learning-status">
              <span><strong>{progress.phase}</strong><small>{progress.message}</small></span>
              <output>{Math.round(progress.percent)} %</output>
            </div>
            <div
              className={`voice-learning-progress ${working ? "active" : ""}`}
              role="progressbar"
              aria-label="Progreso del aprendizaje de voces"
              aria-valuemin={0}
              aria-valuemax={100}
              aria-valuenow={progress.percent}
            >
              <i style={{ width: `${progress.percent}%` }} />
              {working ? <b aria-hidden="true" /> : null}
            </div>
            <div className="voice-learning-stages" aria-label="Fases del análisis de voces">
              {LEARNING_STAGES.map(([key, label], index) => <span
                key={key}
                className={index < currentStage ? "done" : index === currentStage ? "active" : ""}
                aria-current={index === currentStage && working ? "step" : undefined}
              ><i />{label}</span>)}
            </div>
            {progress.state === "completed" ? <div className="voice-learning-result">
              <CheckCircle2 />
              <span><strong>{progress.learnedSamples ?? 0} fragmentos vocales aprendidos</strong><small>{progress.createdProfiles?.length ?? 0} perfiles nuevos · los fragmentos dudosos no se guardan</small></span>
            </div> : null}
          </div> : <div className="voice-learning-explainer">
            <article><AudioWaveform /><span><strong>1. Escucha</strong><small>Localiza turnos de voz claros.</small></span></article>
            <article><Fingerprint /><span><strong>2. Compara</strong><small>Calcula huellas CAM++ de 192 dimensiones.</small></span></article>
            <article><UserRoundCheck /><span><strong>3. Recuerda</strong><small>Acumula similitudes entre grabaciones.</small></span></article>
          </div>}
          {error ? <p className="voice-learning-error" role="alert">{error}</p> : null}
        </section>

        <VoiceProfilesSection settings={settings} advanced={settings.experienceMode === "advanced"} onChange={onChange} />

        <aside className="voices-privacy-note">
          <ShieldCheck />
          <span><strong>No se entrena una copia de tu voz.</strong><small>Sólo se guardan vectores matemáticos cifrados para tu cuenta de Windows. No se conserva el audio del fragmento ni se envía nada a internet.</small></span>
        </aside>
      </div>
    </section>
  </div>;
}
