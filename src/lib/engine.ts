import type { AssistantMessage, DeletedProjectResult, EngineEvent, EvidenceEvent, GlobalSearchResult, HardwareInfo, InsightDepth, LiveChunkResult, LiveSessionResult, LiveSessionStarted, LocalAiStatus, ModelCatalog, ProjectInsights, ProjectMarker, ProjectSettings, QueueItem, QueueStatus, RecentProject, RedactionPreview, SemanticSearchResponse, SpeakerAiStatus, SystemDiagnostics, TranscriptVersion, TranscriptionProject, VoiceProfile, VoiceProfileCatalog } from "../types";

type EventListener = (event: EngineEvent) => void;
type PendingRequest = { resolve: (value: unknown) => void; reject: (reason: Error) => void; timeout: number };

class EngineClient {
  private child: { write(data: string): Promise<void>; kill(): Promise<void> } | null = null;
  private pending = new Map<string, PendingRequest>();
  private listeners = new Set<EventListener>();
  private starting: Promise<void> | null = null;
  private lineBuffer = "";
  private hasResponded = false;

  get available(): boolean {
    return Boolean(window.__TAURI_INTERNALS__);
  }

  subscribe(listener: EventListener): () => void {
    this.listeners.add(listener);
    return () => this.listeners.delete(listener);
  }

  async start(): Promise<void> {
    if (!this.available) throw new Error("El motor local sólo está disponible dentro de la aplicación de escritorio.");
    if (this.child) return;
    if (this.starting) return this.starting;
    this.starting = this.spawn();
    try { await this.starting; } finally { this.starting = null; }
  }

  private async spawn(): Promise<void> {
    const { Command } = await import("@tauri-apps/plugin-shell");
    const { join, resourceDir } = await import("@tauri-apps/api/path");
    const cudaDirectory = await join(await resourceDir(), "cuda");
    const command = Command.sidecar("binaries/transcriptor-engine", ["serve"], {
      env: { TRANSCRIPTOR_CUDA_DIR: cudaDirectory },
    });
    command.stdout.on("data", (data) => this.consume(String(data)));
    command.stderr.on("data", (data) => this.listeners.forEach((listener) => listener({ type: "engine_log", payload: { level: "error", message: String(data) } })));
    command.on("close", ({ code }) => {
      this.child = null;
      this.hasResponded = false;
      const error = new Error(`El motor local se cerró inesperadamente (código ${code ?? "desconocido"}).`);
      this.pending.forEach((request) => { window.clearTimeout(request.timeout); request.reject(error); });
      this.pending.clear();
      this.listeners.forEach((listener) => listener({ type: "engine_closed", payload: { code } }));
    });
    this.child = await command.spawn();
  }

  private consume(chunk: string): void {
    if (!this.lineBuffer && !chunk.includes("\n") && chunk.trimStart().startsWith("{") && chunk.trimEnd().endsWith("}")) {
      try { this.route(JSON.parse(chunk) as EngineEvent); return; } catch { /* wait for another chunk */ }
    }
    this.lineBuffer += chunk;
    const lines = this.lineBuffer.split(/\r?\n/);
    this.lineBuffer = lines.pop() ?? "";
    for (const line of lines) {
      if (!line.trim()) continue;
      try { this.route(JSON.parse(line) as EngineEvent); }
      catch { this.listeners.forEach((listener) => listener({ type: "engine_log", payload: { level: "warning", message: "El motor devolvió un mensaje no válido." } })); }
    }
  }

  private route(event: EngineEvent): void {
    if ((event.type === "result" || event.type === "error") && event.requestId) {
      this.hasResponded = true;
      const request = this.pending.get(event.requestId);
      if (request) {
        window.clearTimeout(request.timeout);
        this.pending.delete(event.requestId);
        if (event.type === "result") request.resolve(event.payload);
        else request.reject(new Error((event.payload as { message?: string }).message ?? "Error desconocido del motor"));
      }
    }
    this.listeners.forEach((listener) => listener(event));
  }

  async request<T>(action: string, payload: unknown = {}, timeoutMs = 30_000): Promise<T> {
    await this.start();
    const requestId = crypto.randomUUID();
    return new Promise<T>((resolve, reject) => {
      const effectiveTimeoutMs = this.hasResponded ? timeoutMs : Math.max(timeoutMs, 120_000);
      const timeout = window.setTimeout(() => {
        this.pending.delete(requestId);
        reject(new Error(`El motor no respondió a “${action}” a tiempo.`));
      }, effectiveTimeoutMs);
      this.pending.set(requestId, { resolve: resolve as (value: unknown) => void, reject, timeout });
      this.child!.write(`${JSON.stringify({ requestId, action, payload })}\n`).catch((error) => {
        window.clearTimeout(timeout);
        this.pending.delete(requestId);
        reject(error instanceof Error ? error : new Error(String(error)));
      });
    });
  }

  analyze(mediaPath: string) { return this.request<Record<string, unknown>>("analyze_media", { mediaPath }, 60_000); }
  getHardwareInfo() { return this.request<HardwareInfo>("get_hardware_info", {}, 60_000); }
  diagnose(mediaPath?: string) { return this.request<SystemDiagnostics>("diagnose_system", { mediaPath }, 120_000); }
  listModels() { return this.request<ModelCatalog>("list_models"); }
  downloadModel(modelId: string) { return this.request<{ accepted: boolean }>("download_model", { modelId }); }
  cancelModelDownload(modelId: string) { return this.request<{ cancelled: boolean }>("cancel_model_download", { modelId }); }
  deleteModel(modelId: string) { return this.request<{ deleted: boolean; removedBytes: number }>("delete_model", { modelId }); }
  getSpeakerAiStatus() { return this.request<SpeakerAiStatus>("get_speaker_ai_status"); }
  installSpeakerAi() { return this.request<{ accepted: boolean }>("install_speaker_ai"); }
  cancelSpeakerAiDownload() { return this.request<{ cancelled: boolean }>("cancel_speaker_ai_download"); }
  listVoiceProfiles() { return this.request<VoiceProfileCatalog>("list_voice_profiles"); }
  learnProjectVoices(projectId: string) {
    return this.request<{ accepted: boolean; projectId: string }>("learn_project_voices", { projectId }, 60_000);
  }
  cancelVoiceLearning(projectId: string) {
    return this.request<{ cancelled: boolean }>("cancel_voice_learning", { projectId });
  }
  updateVoiceProfile(profileId: string, changes: { name?: string; enabled?: boolean; matchThreshold?: number }) {
    return this.request<VoiceProfile>("update_voice_profile", { profileId, ...changes });
  }
  deleteVoiceProfile(profileId: string) {
    return this.request<{ deleted: boolean; profileId: string; name: string }>("delete_voice_profile", { profileId });
  }
  transcribe(project: TranscriptionProject) { return this.request<{ accepted: boolean }>("transcribe", { project }, 24 * 60 * 60 * 1000); }
  enqueue(project: TranscriptionProject) { return this.request<{ projectId: string; position: number }>("enqueue_transcription", { project }); }
  listQueue() { return this.request<QueueItem[]>("list_queue"); }
  getQueueStatus() { return this.request<QueueStatus>("get_queue_status"); }
  setQueueConcurrency(maxConcurrentJobs: number) { return this.request<QueueStatus>("set_queue_concurrency", { maxConcurrentJobs }); }
  removeFromQueue(projectId: string) { return this.request<{ removed: boolean }>("remove_from_queue", { projectId }); }
  reorderQueue(projectIds: string[]) { return this.request<QueueItem[]>("reorder_queue", { projectIds }); }
  cancel(projectId: string) { return this.request<{ cancelled: boolean; message?: string }>("cancel", { projectId }); }
  save(project: TranscriptionProject) { return this.request("save_project", { project }); }
  listProjects() { return this.request<RecentProject[]>("list_projects"); }
  searchTranscripts(query: string) { return this.request<GlobalSearchResult[]>("search_transcripts", { query }); }
  semanticSearch(query: string) { return this.request<SemanticSearchResponse>("semantic_search", { query }, 120_000); }
  loadProject(projectId: string) { return this.request<TranscriptionProject>("load_project", { projectId }); }
  listVersions(projectId: string) { return this.request<TranscriptVersion[]>("list_versions", { projectId }); }
  restoreVersion(projectId: string, versionId: string) { return this.request<TranscriptionProject>("restore_version", { projectId, versionId }); }
  listEvidence(projectId: string) { return this.request<EvidenceEvent[]>("list_evidence", { projectId }); }
  listAssistantMessages(projectId: string) { return this.request<AssistantMessage[]>("list_assistant_messages", { projectId }); }
  addMarker(projectId: string, timeMs: number, kind: string, label: string) { return this.request<ProjectMarker>("add_marker", { projectId, timeMs, kind, label }); }
  listMarkers(projectId: string) { return this.request<ProjectMarker[]>("list_markers", { projectId }); }
  deleteProject(projectId: string) { return this.request<DeletedProjectResult>("delete_project", { projectId }); }
  loadProjectForMedia(mediaPath: string) { return this.request<TranscriptionProject | null>("load_project_for_media", { mediaPath }); }
  export(project: TranscriptionProject, format: string, outputPath: string, redactSensitive = false) { return this.request("export_project", { project, format, outputPath, redactSensitive }); }
  previewRedactions(project: TranscriptionProject) { return this.request<RedactionPreview>("preview_redactions", { project }); }
  exportPackage(project: TranscriptionProject, outputPath: string, includeMedia: boolean) { return this.request("export_package", { project, outputPath, includeMedia }, 24 * 60 * 60 * 1000); }
  importPackage(packagePath: string) { return this.request<TranscriptionProject>("import_package", { packagePath }, 24 * 60 * 60 * 1000); }
  exportMediaEdit(project: TranscriptionProject, excludedSegmentIds: string[], outputPath: string) { return this.request<{ outputPath: string; removedSegments: number; remainingDurationMs: number }>("export_media_edit", { project, excludedSegmentIds, outputPath }, 24 * 60 * 60 * 1000); }
  groupParagraphs(project: TranscriptionProject, maxSeconds = 42, maxCharacters = 620) {
    return this.request<TranscriptionProject>("group_paragraphs", { project, maxSeconds, maxCharacters }, 60_000);
  }
  getLocalAiStatus(model = "qwen3.5:9b") {
    return this.request<LocalAiStatus>("get_local_ai_status", { model }, 30_000);
  }
  analyzeTranscript(project: TranscriptionProject, mode: ProjectInsights["mode"], depth: InsightDepth, model = "qwen3.5:9b") {
    return this.request<{ accepted: boolean; projectId: string }>("analyze_transcript", { project, mode, depth, model }, 60_000);
  }
  cancelAnalysis(projectId: string) {
    return this.request<{ cancelled: boolean }>("cancel_analysis", { projectId });
  }
  askTranscript(project: TranscriptionProject, question: string, model = "qwen3.5:9b") {
    return this.request<{ accepted: boolean; projectId: string }>("ask_transcript", { project, question, model }, 60_000);
  }
  startLiveSession(settings: ProjectSettings, separateSpeakers: boolean) {
    return this.request<LiveSessionStarted>("start_live_session", { settings, separateSpeakers }, 60_000);
  }
  pushLiveAudio(sessionId: string, pcmBase64: string) {
    return this.request<LiveChunkResult>("push_live_audio", { sessionId, pcmBase64 }, 120_000);
  }
  stopLiveSession(sessionId: string) {
    return this.request<LiveSessionResult>("stop_live_session", { sessionId }, 60_000);
  }
  cancelLiveSession(sessionId: string) {
    return this.request<{ cancelled: boolean }>("cancel_live_session", { sessionId });
  }
}

export const engine = new EngineClient();

export async function localMediaUrl(path: string): Promise<string> {
  if (!window.__TAURI_INTERNALS__) return path;
  const { convertFileSrc, invoke } = await import("@tauri-apps/api/core");
  const allowedPath = await invoke<string>("allow_media_file", { path });
  return convertFileSrc(allowedPath);
}
