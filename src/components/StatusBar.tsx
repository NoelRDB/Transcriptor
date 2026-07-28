import { useState, type ReactNode } from "react";
import {
  Activity,
  AudioWaveform,
  BrainCircuit,
  CheckCircle2,
  ChevronDown,
  ChevronUp,
  CircleAlert,
  Cpu,
  Gauge,
  HardDrive,
  Languages,
  Layers3,
  LockKeyhole,
  MemoryStick,
  Microchip,
  Save,
  Sparkles,
  Timer,
  Users,
} from "lucide-react";
import type { JobProgress } from "../types";
import { formatClock } from "../lib/time";

const STAGES = [
  ["model_loading", "Modelo"],
  ["decoding", "Audio"],
  ["restoring", "Mejora"],
  ["language_detection", "Idioma"],
  ["transcribing", "Texto"],
  ["reviewing", "Revisión IA"],
  ["diarizing", "Voces"],
  ["completed", "Guardado"],
] as const;

const STAGE_ORDER: Record<string, number> = {
  preparing: 0,
  model_loading: 0,
  model_download: 0,
  decoding: 1,
  restoring: 2,
  language_detection: 3,
  transcribing: 4,
  reviewing: 5,
  diarizing: 6,
  saving: 7,
  completed: 7,
};

const STAGE_COPY: Record<string, { label: string; detail: string; icon: ReactNode }> = {
  preparing: { label: "Preparando el motor", detail: "Comprobando recursos y configuración", icon: <Activity /> },
  model_loading: { label: "Cargando el modelo", detail: "Preparando la inteligencia artificial local", icon: <BrainCircuit /> },
  model_download: { label: "Preparando el modelo", detail: "Descarga e integridad del modelo local", icon: <BrainCircuit /> },
  decoding: { label: "Leyendo el audio", detail: "Conversión segura a voz de 16 kHz", icon: <AudioWaveform /> },
  restoring: { label: "Mejorando la voz", detail: "Analizando volumen, ruido y silencios", icon: <Sparkles /> },
  language_detection: { label: "Detectando el idioma", detail: "Localizando las regiones que contienen voz", icon: <Languages /> },
  transcribing: { label: "Reconociendo el texto", detail: "Whisper está procesando el audio completo", icon: <AudioWaveform /> },
  reviewing: { label: "Revisión inteligente Large-v3", detail: "Volviendo a escuchar únicamente los fragmentos dudosos", icon: <BrainCircuit /> },
  diarizing: { label: "Identificando las voces", detail: "CAM++ está comparando timbres y alineando hablantes", icon: <Users /> },
  saving: { label: "Guardando el proyecto", detail: "Consolidando texto, voces y copia de recuperación", icon: <Save /> },
  completed: { label: "Trabajo finalizado", detail: "El resultado está guardado", icon: <CheckCircle2 /> },
};

interface StatusBarProps {
  progress: JobProgress;
  model: string;
  language?: string;
}

interface PhaseFeedback {
  label: string;
  detail: string;
  icon: ReactNode;
  percent: number | null;
  counter: string;
}

export function StatusBar({ progress, model, language }: StatusBarProps) {
  const [expanded, setExpanded] = useState(false);
  const working = ["analyzing", "waiting_model", "transcribing"].includes(progress.state);
  const StateIcon = progress.state === "failed" ? CircleAlert : progress.state === "completed" ? CheckCircle2 : working ? Activity : LockKeyhole;
  const stage = progress.stage ?? "preparing";
  const stageIndex = STAGE_ORDER[stage] ?? 0;
  const phase = phaseFeedback(progress);
  const globalPercent = progress.percent == null
    ? null
    : working
      ? Math.min(99.5, Math.max(0, progress.percent))
      : Math.min(100, Math.max(0, progress.percent));
  const percentLabel = globalPercent === null
    ? "En curso"
    : `${working ? Math.min(99, Math.floor(globalPercent)) : Math.round(globalPercent)} %`;
  const deviceLabel = progress.device ? `${progress.device}${progress.cpuThreads ? ` + ${progress.cpuThreads} hilos CPU` : ""}` : "Automático";
  const profileLabel = progress.performanceProfile === "balanced" ? "Equilibrado" : progress.performanceProfile === "performance" ? "Rápido" : progress.performanceProfile === "custom" ? "Personalizado" : "Máximo";
  const activeModel = progress.activeModel || model;
  const postProcessing = stage === "reviewing" || stage === "diarizing" || stage === "saving";
  const remainingMs = stage === "reviewing"
    ? progress.reviewEtaMs
    : stage === "diarizing"
      ? progress.diarizationEtaMs
      : progress.etaMs;
  const rateLabel = stage === "reviewing" || stage === "diarizing" ? "Ritmo de fase" : "Velocidad real";
  const rateValue = progress.phaseRate
    ? `${progress.phaseRate.toFixed(1)} ${stage === "reviewing" ? "frag/s" : "huellas/s"}`
    : postProcessing
      ? stage === "saving" ? "Finalizando" : "Midiendo…"
      : progress.speedX ? `${progress.speedX.toFixed(1)}×` : "Midiendo…";

  return <footer className={`status-bar ${working ? "working" : ""} ${expanded ? "expanded" : ""}`} aria-busy={working}>
    <div className="status-progress-area">
      <div className={`status-state ${progress.state}`} role="status" aria-live="polite">
        <span className={`status-activity-icon ${working ? "active" : ""}`}><StateIcon size={18} /></span>
        <div><strong>{progress.phase}</strong><span>{progress.message || progress.phase}</span></div>
        {working ? <b>{percentLabel}</b> : null}
      </div>
      {working ? <div
        className={`job-progress active ${globalPercent === null ? "waiting" : ""}`}
        role="progressbar"
        aria-label="Progreso total de la transcripción"
        aria-valuemin={0}
        aria-valuemax={100}
        aria-valuenow={globalPercent ?? undefined}
        aria-valuetext={globalPercent === null ? "Trabajo activo, calculando progreso" : `${globalPercent.toFixed(1)} por ciento; ${phase.label}`}
      >
        {globalPercent !== null ? <div className="job-progress-fill" style={{ width: `${globalPercent}%` }} /> : null}
        <i aria-hidden="true" />
      </div> : null}
      {expanded && working ? <PhaseActivity phase={phase} /> : null}
      {expanded && working ? <div className="progress-stages" aria-label="Fases de la transcripción">
        {STAGES.map(([key, label], index) => <span
          key={key}
          className={index < stageIndex ? "done" : index === stageIndex ? "active" : ""}
          aria-current={index === stageIndex ? "step" : undefined}
        ><i />{label}</span>)}
      </div> : null}
    </div>
    <div className="metrics-shell">
      <div className="status-metrics primary-metrics">
        <Metric icon={<Activity size={14} />} label={postProcessing ? "Audio leído" : "Procesado"} value={`${formatClock(progress.processedDurationMs)} / ${formatClock(progress.totalDurationMs)}`} />
        <Metric icon={<Gauge size={14} />} label={rateLabel} value={rateValue} />
        <Metric icon={<Timer size={14} />} label="Restante de fase" value={remainingMs != null ? `~${formatClock(remainingMs)}` : working ? "Calculando…" : "—"} />
        <Metric icon={<HardDrive size={14} />} label="Modelo activo" value={activeModel} />
      </div>
      {expanded ? <div className="status-metrics status-details">
        <Metric icon={<Layers3 size={14} />} label="Fragmentos" value={String(progress.segmentsProduced ?? 0)} />
        <Metric icon={<Users size={14} />} label="IA de hablantes" value={speakerStatus(progress, stageIndex)} />
        <Metric icon={<Cpu size={14} />} label="CPU motor" value={progress.cpuUsagePercent != null ? `${Math.round(progress.cpuUsagePercent)} %` : "Midiendo…"} />
        <Metric icon={<MemoryStick size={14} />} label="RAM motor" value={progress.ramMiB != null ? `${Math.round(progress.ramMiB)} MB` : "Midiendo…"} />
        <Metric icon={<MemoryStick size={14} />} label="RAM del PC" value={progress.systemRamUsedMiB != null && progress.systemRamTotalMiB ? `${(progress.systemRamUsedMiB / 1024).toFixed(1)} / ${(progress.systemRamTotalMiB / 1024).toFixed(0)} GB` : "Midiendo…"} />
        <Metric icon={<Microchip size={14} />} label="GPU / VRAM" value={progress.gpuUsagePercent != null ? `${Math.round(progress.gpuUsagePercent)} % · ${Math.round(progress.gpuVramUsedMiB ?? 0)} / ${Math.round(progress.gpuVramTotalMiB ?? 0)} MB` : progress.device === "CPU" ? "No utilizada" : "Midiendo…"} />
        <Metric icon={<Cpu size={14} />} label="Motor" value={deviceLabel} />
        <Metric icon={<Gauge size={14} />} label="Perfil" value={profileLabel} />
        <Metric icon={<HardDrive size={14} />} label="Configuración" value={`${model} · ${language || "idioma auto"}`} />
      </div> : null}
    </div>
    <button
      className="details-toggle"
      onClick={() => setExpanded((value) => !value)}
      aria-expanded={expanded}
      aria-label={expanded ? "Ocultar detalles" : "Mostrar detalles"}
      title={expanded ? "Ocultar detalles" : "Mostrar detalles"}
    >
      {expanded ? <ChevronDown size={14} /> : <ChevronUp size={14} />}
      <span>{expanded ? "Menos" : "Detalles"}</span>
    </button>
  </footer>;
}

function PhaseActivity({ phase }: { phase: PhaseFeedback }) {
  return <div className="phase-activity" aria-label={`${phase.label}: ${phase.counter}`}>
    <span className="phase-orbit" aria-hidden="true">{phase.icon}<i /><i /><i /></span>
    <div>
      <span><strong>{phase.label}</strong><em>EN CURSO</em></span>
      <small>{phase.detail}</small>
    </div>
    <output>{phase.counter}</output>
    <div
      className={`phase-progress ${phase.percent === null ? "indeterminate" : ""}`}
      role="progressbar"
      aria-label={`Progreso de fase: ${phase.label}`}
      aria-valuemin={0}
      aria-valuemax={100}
      aria-valuenow={phase.percent ?? undefined}
      aria-valuetext={phase.percent === null ? `${phase.label} en curso, calculando avance` : `${phase.percent.toFixed(1)} por ciento; ${phase.counter}`}
    >
      {phase.percent !== null ? <i style={{ width: `${phase.percent}%` }} /> : null}
      <b aria-hidden="true" />
    </div>
  </div>;
}

function phaseFeedback(progress: JobProgress): PhaseFeedback {
  const stage = progress.stage ?? "preparing";
  const copy = STAGE_COPY[stage] ?? STAGE_COPY.preparing;
  let completed: number | undefined;
  let total: number | undefined;
  if (stage === "reviewing") {
    completed = progress.reviewCompletedUnits;
    total = progress.reviewTotalUnits;
  } else if (stage === "diarizing") {
    completed = progress.diarizationCompletedUnits;
    total = progress.diarizationTotalUnits;
  }
  const fallbackPercent = stage === "transcribing" && progress.totalDurationMs > 0
    ? progress.processedDurationMs / progress.totalDurationMs * 100
    : null;
  const counterPercent = completed != null && total
    ? completed / total * 100
    : null;
  const percent = progress.phasePercent == null
    ? counterPercent ?? fallbackPercent
    : Math.min(100, Math.max(0, progress.phasePercent));
  const counter = completed != null && total
    ? `${completed} de ${total}`
    : percent != null
      ? `${Math.round(percent)} % de esta fase`
      : stage === "saving" ? "Últimos ajustes" : "Motor trabajando";
  return { ...copy, percent, counter };
}

function speakerStatus(progress: JobProgress, stageIndex: number): string {
  if (progress.stage === "diarizing" && progress.diarizationTotalUnits) {
    return `${progress.diarizationCompletedUnits ?? 0} / ${progress.diarizationTotalUnits} · ${progress.speakerBackend ?? "local"}`;
  }
  if (stageIndex < STAGE_ORDER.diarizing) return "Pendiente · fase posterior";
  if (stageIndex > STAGE_ORDER.diarizing || progress.state === "completed") return "Completada";
  return progress.speakerBackend ?? "Preparando…";
}

function Metric({ icon, label, value }: { icon: ReactNode; label: string; value: string }) {
  return <span>{icon}<small>{label}</small><strong title={value}>{value}</strong></span>;
}
