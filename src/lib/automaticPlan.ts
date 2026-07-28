import type {
  AppSettings,
  HardwareInfo,
  PerformanceProfile,
  ProjectSettings,
  QualityMode,
  SpeakerAiStatus,
} from "../types";

export interface AutomaticDecision {
  id: "compute" | "transcription" | "audio" | "speakers" | "profiles" | "live";
  label: string;
  value: string;
  detail: string;
}

type AutomaticSettings = Pick<
  AppSettings,
  | "device"
  | "performanceProfile"
  | "cpuThreads"
  | "processPriority"
  | "qualityMode"
  | "defaultModel"
  | "batchSize"
  | "reviewLowConfidence"
  | "audioEnhancement"
  | "diarizationMode"
  | "speakerCountMode"
  | "speakerCount"
  | "speakerSensitivity"
  | "liveLatency"
>;

export interface AutomaticPlan {
  tier: "efficient" | "accelerated" | "workstation";
  title: string;
  summary: string;
  settings: AutomaticSettings;
  decisions: AutomaticDecision[];
}

const MINUTE_MS = 60_000;

export function buildAutomaticPlan(
  hardware: HardwareInfo,
  speakerAi: SpeakerAiStatus | null,
  durationMs = 0,
  voiceProfilesEnabled = false,
): AutomaticPlan {
  const logicalCores = Math.max(1, hardware.cpu.logicalCores);
  const totalRamMiB = hardware.memory.totalMiB;
  const availableRamMiB = hardware.memory.availableMiB;
  const vramMiB = hardware.gpu?.totalVramMiB ?? 0;
  const accelerated = hardware.cudaAvailable && vramMiB >= 4_096;
  const workstation = accelerated && vramMiB >= 6_144 && totalRamMiB >= 16_384 && logicalCores >= 8;
  const constrained = totalRamMiB < 10_240 || logicalCores < 6 || availableRamMiB < 3_072;
  const shortRecording = durationMs > 0 && durationMs <= 20 * MINUTE_MS;

  const qualityMode: QualityMode = workstation && shortRecording
    ? "maximum"
    : constrained
      ? "instant"
      : "professional";
  const performanceProfile: PerformanceProfile = constrained ? "performance" : "maximum";
  const batchSize = accelerated ? (vramMiB >= 8_192 ? 8 : 4) : logicalCores >= 12 ? 4 : 2;
  const liveLatency: ProjectSettings["liveLatency"] = workstation
    ? "ultra"
    : constrained
      ? "stable"
      : "balanced";
  const neuralReady = Boolean(speakerAi?.ready);
  const tier = workstation ? "workstation" : accelerated || !constrained ? "accelerated" : "efficient";
  const qualityLabel = qualityMode === "maximum"
    ? "Large-v3 completo"
    : qualityMode === "professional"
      ? "Turbo + revisión Large-v3"
      : "Turbo optimizado";

  return {
    tier,
    title: workstation ? "Piloto automático · potencia completa" : constrained ? "Piloto automático · eficiencia segura" : "Piloto automático · calidad equilibrada",
    summary: `${qualityLabel}, ${neuralReady ? "separación neuronal" : "separación adaptativa"} y recursos ajustados para este equipo${durationMs ? ` y ${formatDuration(durationMs)}` : ""}.`,
    settings: {
      device: "auto",
      performanceProfile,
      cpuThreads: performanceProfile === "maximum"
        ? logicalCores
        : Math.max(hardware.cpu.physicalCores, Math.round(logicalCores * 0.75)),
      processPriority: "normal",
      qualityMode,
      defaultModel: qualityMode === "maximum" ? "large-v3" : "turbo",
      batchSize,
      reviewLowConfidence: qualityMode === "professional",
      audioEnhancement: "adaptive",
      diarizationMode: neuralReady ? "neural" : "adaptive",
      speakerCountMode: "auto",
      speakerCount: 8,
      speakerSensitivity: 55,
      liveLatency,
    },
    decisions: [
      {
        id: "compute",
        label: "Motor de cálculo",
        value: accelerated ? "GPU + CPU automáticas" : "CPU multinúcleo automática",
        detail: accelerated
          ? `CUDA disponible · ${formatMemory(vramMiB)} VRAM · ${logicalCores} hilos como apoyo`
          : `${logicalCores} hilos detectados · retroceso seguro si cambia la carga`,
      },
      {
        id: "transcription",
        label: "Calidad de transcripción",
        value: qualityLabel,
        detail: qualityMode === "maximum"
          ? "La duración es adecuada para aplicar la máxima fidelidad al audio completo."
          : qualityMode === "professional"
            ? "Turbo crea el texto y Large-v3 vuelve a escuchar sólo donde existe una duda real."
            : "El equipo priorizará estabilidad y memoria sin cargar un modelo que no pueda sostener.",
      },
      {
        id: "audio",
        label: "Preparación de audio",
        value: "Restauración adaptativa",
        detail: "Mide ruido, volumen y silencios antes de decidir cuánto debe limpiar.",
      },
      {
        id: "speakers",
        label: "IA especializada en voces",
        value: neuralReady ? "CAM++ neuronal activada" : "Adaptativa con respaldo acústico",
        detail: neuralReady
          ? "El número de hablantes se deduce automáticamente; no se obliga a encontrar dos."
          : "Funcionará ahora y adoptará CAM++ automáticamente cuando instales el modelo local.",
      },
      {
        id: "profiles",
        label: "Reconocimiento recurrente",
        value: voiceProfilesEnabled ? "Perfiles de voz automáticos" : "Disponible con consentimiento",
        detail: voiceProfilesEnabled
          ? "Aprende únicamente de fragmentos fiables y conserva las huellas cifradas en Windows."
          : "La separación funciona sin perfiles; activarlos requiere una confirmación porque guardan huellas cifradas.",
      },
      {
        id: "live",
        label: "Transcripción en directo",
        value: liveLatency === "ultra" ? "Retardo ultrabajo" : liveLatency === "stable" ? "Contexto estable" : "Retardo equilibrado",
        detail: liveLatency === "ultra"
          ? "El equipo permite bloques rápidos sin renunciar al repaso final."
          : liveLatency === "stable"
            ? "Usa bloques algo mayores para proteger la precisión en este equipo."
            : "Equilibra contexto y velocidad según la capacidad disponible.",
      },
    ],
  };
}

function formatMemory(mib: number): string {
  return mib >= 1024 ? `${(mib / 1024).toFixed(mib % 1024 ? 1 : 0)} GB` : `${Math.round(mib)} MB`;
}

function formatDuration(durationMs: number): string {
  const minutes = Math.max(1, Math.round(durationMs / MINUTE_MS));
  return minutes < 60 ? `${minutes} min de audio` : `${Math.floor(minutes / 60)} h ${minutes % 60} min de audio`;
}
