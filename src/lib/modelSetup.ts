import type {
  HardwareInfo,
  ManagedModel,
  ModelCatalog,
  QualityMode,
} from "../types";

const GIB = 1024 ** 3;
const DOWNLOAD_HEADROOM_BYTES = 512 * 1024 ** 2;
export const SPEAKER_MODEL_BYTES = 28_281_164;

export interface RecommendedModelSetup {
  models: ManagedModel[];
  qualityMode: QualityMode;
  label: string;
  requiredBytes: number;
  freeBytes: number;
  canInstall: boolean;
  includesSpeakerAi: boolean;
  reason: string;
}

function bytesLeft(model: ManagedModel): number {
  if (model.installed) return 0;
  if (model.downloadBytes != null) return Math.max(0, model.downloadBytes);
  return Math.max(0, Math.round(model.sizeGiB * GIB) - model.installedBytes);
}

export function buildRecommendedModelSetup(
  catalog: ModelCatalog,
  hardware: HardwareInfo | null,
  speakerAiReady: boolean,
): RecommendedModelSetup {
  const turbo = catalog.models.find((model) => model.id === "turbo");
  if (!turbo) {
    return {
      models: [],
      qualityMode: "instant",
      label: "Configuración no disponible",
      requiredBytes: 0,
      freeBytes: catalog.freeBytes,
      canInstall: false,
      includesSpeakerAi: false,
      reason: "El catálogo local no contiene el modelo Turbo.",
    };
  }

  const large = catalog.models.find((model) => model.id === "large-v3");
  const speakerBytes = speakerAiReady ? 0 : SPEAKER_MODEL_BYTES;
  const professionalModels = large ? [turbo, large] : [turbo];
  const professionalBytes = professionalModels.reduce(
    (total, model) => total + bytesLeft(model),
    speakerBytes,
  );
  const professionalRequired = professionalBytes
    ? professionalBytes + DOWNLOAD_HEADROOM_BYTES
    : 0;
  const enoughMemory = Boolean(hardware && hardware.memory.totalMiB >= 8 * 1024);
  const professional = Boolean(
    large
    && enoughMemory
    && catalog.freeBytes >= professionalRequired,
  );
  const models = professional ? professionalModels : [turbo];
  const downloadBytes = models.reduce(
    (total, model) => total + bytesLeft(model),
    speakerBytes,
  );
  const requiredBytes = downloadBytes ? downloadBytes + DOWNLOAD_HEADROOM_BYTES : 0;
  const canInstall = models.length > 0 && catalog.freeBytes >= requiredBytes;

  return {
    models,
    qualityMode: professional ? "professional" : "instant",
    label: professional ? "Calidad profesional" : "Transcripción rápida",
    requiredBytes,
    freeBytes: catalog.freeBytes,
    canInstall,
    includesSpeakerAi: !speakerAiReady,
    reason: professional
      ? "Tu equipo puede usar Turbo para la primera pasada y Large-v3 para revisar automáticamente los fragmentos dudosos."
      : enoughMemory
        ? "Instalaremos Turbo para empezar sin ocupar más espacio del necesario."
        : hardware
          ? "Turbo ofrece el mejor equilibrio compatible con la memoria disponible."
          : "No se pudo medir la memoria; usamos la opción conservadora para empezar con seguridad.",
  };
}

export function hasReadyCoreModel(catalog: ModelCatalog): boolean {
  return catalog.models.some(
    (model) => model.id === "turbo"
      && model.installed
      && (!model.integrity || model.integrity === "ready"),
  );
}
