const PROJECT_JOB_EVENT_TYPES = new Set([
  "job_started",
  "model_download_progress",
  "audio_extraction_progress",
  "transcription_progress",
  "partial_segments",
  "job_paused",
  "job_completed",
  "job_cancelled",
  "job_failed",
]);

export function shouldRouteEngineEvent(type: string, payload: unknown, activeProjectId?: string): boolean {
  if (!PROJECT_JOB_EVENT_TYPES.has(type)) return true;
  if (!payload || typeof payload !== "object" || !("projectId" in payload)) return false;
  return (payload as { projectId?: unknown }).projectId === activeProjectId;
}
