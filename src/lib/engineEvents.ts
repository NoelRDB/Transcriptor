import { engine } from "./engine";
import { shouldRouteEngineEvent } from "./jobs";
import { useAppStore } from "../store";
import type { EngineEvent, JobProgress, TranscriptSegment, VoiceProfileMergeResult } from "../types";

export function routeEngineEvent(event: EngineEvent): void {
  const state = useAppStore.getState();
  const payload = event.payload as Record<string, any>;
  if (!shouldRouteEngineEvent(event.type, event.payload, state.project?.id)) return;
  if (event.type === "voice_profiles_merged") {
    const merged = event.payload as VoiceProfileMergeResult;
    const project = state.project;
    if (!project || !merged.affectedProjectIds.includes(project.id)) return;
    let changed = false;
    const segments = project.segments.map((segment) => {
      if (segment.speakerProfileId !== merged.sourceProfileId) return segment;
      changed = true;
      return {
        ...segment,
        speaker: merged.targetName,
        speakerProfileId: merged.targetProfileId,
      };
    });
    if (changed) state.setSegments(segments);
    return;
  }
  if (["transcription_progress", "audio_extraction_progress", "audio_enhancement_progress", "model_download_progress", "job_started"].includes(event.type)) {
    state.setProgress(payload as unknown as Partial<JobProgress>);
  }
  if (event.type === "partial_segments") {
    state.setSegments(payload.segments as TranscriptSegment[], !payload.replaceExisting);
  }
  if (event.type === "job_completed") {
    state.setProgress({ state: "completed", stage: "completed", phase: "Transcripción completada", percent: 100, phasePercent: 100, processedDurationMs: payload.durationMs, totalDurationMs: payload.durationMs, message: "Texto, voces y proyecto guardados correctamente", speedX: null, phaseRate: null, etaMs: 0, reviewEtaMs: 0, diarizationEtaMs: 0 });
    const project = useAppStore.getState().project;
    if (project && project.id === String(payload.projectId)) {
      const mediaUrl = project.mediaUrl;
      state.setProject({ ...project, detectedLanguage: String(payload.language), model: String(payload.model || project.model), transcriptionStatus: "completed", segments: project.segments });
      void engine.loadProject(String(payload.projectId)).then((saved) => {
        const current = useAppStore.getState().project;
        if (current?.id === payload.projectId) useAppStore.getState().setProject({ ...saved, mediaUrl });
      }).catch((error) => useAppStore.getState().setError(`La transcripción terminó, pero no se pudo verificar el guardado: ${error.message}`));
      void engine.listProjects().then(useAppStore.getState().setRecentProjects).catch(() => undefined);
    }
  }
  if (event.type === "job_cancelled") {
    state.setProgress({ state: "cancelled", phase: "Transcripción cancelada", message: "La versión anterior se ha conservado" });
    void restoreSavedProject(String(payload.projectId), "cancelled", "Transcripción cancelada", "La versión anterior se ha conservado");
  }
  if (event.type === "job_failed" || event.type === "engine_closed") {
    const message = String(payload.message || "El motor de transcripción dejó de responder.");
    state.setProgress({ state: "failed", phase: "Error", message });
    state.setError(message);
    if (event.type === "job_failed" && payload.projectId) void restoreSavedProject(String(payload.projectId), "failed", "Error", message);
  }
}

async function restoreSavedProject(projectId: string, status: "cancelled" | "failed", phase: string, message: string): Promise<void> {
  const current = useAppStore.getState().project;
  if (!current || current.id !== projectId) return;
  const mediaUrl = current.mediaUrl;
  try {
    const saved = await engine.loadProject(projectId);
    const state = useAppStore.getState();
    if (state.project?.id !== projectId) return;
    state.setProject({ ...saved, mediaUrl, transcriptionStatus: status });
    state.setProgress({ state: status, phase, message });
  } catch {
    // The original in-memory project remains available if reloading is impossible.
  }
}
