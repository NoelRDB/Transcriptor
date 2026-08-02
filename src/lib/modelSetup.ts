import type {
  CudaRuntimeStatus,
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
  includesCudaRuntime: boolean;
  downloadBytes: number;
  cudaRequiredBytes: number;
  cudaFreeBytes: number;
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
  cudaRuntime: CudaRuntimeStatus | null = null,
  includeCudaRuntime = false,
): RecommendedModelSetup {
  const includesCudaRuntime = Boolean(
    includeCudaRuntime
    && hardware?.gpu
    && cudaRuntime?.supported
    && !cudaRuntime.ready,
  );
  const cudaDownloadBytes = includesCudaRuntime ? cudaRuntime?.downloadBytes ?? 0 : 0;
  const cudaRequiredBytes = includesCudaRuntime
    ? cudaRuntime?.requiredFreeBytes ?? 0
    : 0;
  const cudaFreeBytes = cudaRuntime?.freeBytes ?? 0;
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
      includesCudaRuntime,
      downloadBytes: cudaDownloadBytes,
      cudaRequiredBytes,
      cudaFreeBytes,
      reason: "El catálogo local no contiene el modelo Turbo.",
    };
  }

  const large = catalog.models.find((model) => model.id === "large-v3");
  const speakerBytes = speakerAiReady ? 0 : SPEAKER_MODEL_BYTES;
  const professionalModels = large ? [turbo, large] : [turbo];
  const sameVolume = includesCudaRuntime
    && Boolean(cudaRuntime)
    && volumeOf(catalog.root) === volumeOf(cudaRuntime?.root ?? "");
  const capacityFor = (selectedModels: ManagedModel[]) => {
    const modelBytes = selectedModels.reduce(
      (total, model) => total + bytesLeft(model),
      speakerBytes,
    );
    const modelRequired = modelBytes ? modelBytes + DOWNLOAD_HEADROOM_BYTES : 0;
    if (!includesCudaRuntime) {
      return {
        modelBytes,
        requiredBytes: modelRequired,
        canInstall: catalog.freeBytes >= modelRequired,
      };
    }
    if (sameVolume) {
      const combinedRequired = modelBytes + cudaDownloadBytes + DOWNLOAD_HEADROOM_BYTES;
      return {
        modelBytes,
        requiredBytes: combinedRequired,
        canInstall: catalog.freeBytes >= combinedRequired,
      };
    }
    return {
      modelBytes,
      requiredBytes: modelRequired + cudaRequiredBytes,
      canInstall: catalog.freeBytes >= modelRequired && Boolean(cudaRuntime?.canInstall),
    };
  };
  const professionalCapacity = capacityFor(professionalModels);
  const enoughMemory = Boolean(hardware && hardware.memory.totalMiB >= 8 * 1024);
  const professional = Boolean(
    large
    && enoughMemory
    && professionalCapacity.canInstall,
  );
  const models = professional ? professionalModels : [turbo];
  const capacity = professional ? professionalCapacity : capacityFor(models);
  const downloadBytes = capacity.modelBytes + cudaDownloadBytes;
  const requiredBytes = capacity.requiredBytes;
  const canInstall = models.length > 0 && capacity.canInstall;
  const gpuReason = includesCudaRuntime
    ? " También prepararemos CUDA para aprovechar automáticamente tu GPU NVIDIA."
    : "";

  return {
    models,
    qualityMode: professional ? "professional" : "instant",
    label: professional ? "Calidad profesional" : "Transcripción rápida",
    requiredBytes,
    freeBytes: catalog.freeBytes,
    canInstall,
    includesSpeakerAi: !speakerAiReady,
    includesCudaRuntime,
    downloadBytes,
    cudaRequiredBytes,
    cudaFreeBytes,
    reason: professional
      ? `Tu equipo puede usar Turbo para la primera pasada y Large-v3 para revisar automáticamente los fragmentos dudosos.${gpuReason}`
      : enoughMemory
        ? `Instalaremos Turbo para empezar sin ocupar más espacio del necesario.${gpuReason}`
        : hardware
          ? `Turbo ofrece el mejor equilibrio compatible con la memoria disponible.${gpuReason}`
          : "No se pudo medir la memoria; usamos la opción conservadora para empezar con seguridad.",
  };
}

function volumeOf(path: string): string {
  const windowsDrive = /^[a-z]:/i.exec(path);
  if (windowsDrive) return windowsDrive[0].toLowerCase();
  return path.startsWith("/") ? "/" : "";
}

export function hasReadyCoreModel(catalog: ModelCatalog): boolean {
  return catalog.models.some(
    (model) => model.id === "turbo"
      && model.installed
      && (!model.integrity || model.integrity === "ready"),
  );
}
