export type MediaKind = "audio" | "video";
export type JobState = "idle" | "analyzing" | "waiting_model" | "transcribing" | "completed" | "cancelled" | "failed";

export interface TranscriptWord {
  id: string;
  startMs: number;
  endMs: number;
  text: string;
  probability?: number;
}

export interface TranscriptSegment {
  id: string;
  startMs: number;
  endMs: number;
  text: string;
  speaker?: string;
  speakerConfidence?: number;
  speakerProfileId?: string;
  speakerMatchConfidence?: number;
  speakerProvisional?: boolean;
  speakerCluster?: number;
  speakerClusterIndex?: number;
  confidence?: number;
  reviewState?: "pending" | "accepted" | "corrected" | "ignored";
  speakerReviewState?: "pending" | "accepted" | "corrected" | "ignored";
  reviewReasons?: string[];
  order: number;
  words: TranscriptWord[];
}

export interface MediaMetadata {
  durationMs: number;
  format?: string;
  codec?: string;
  width?: number;
  height?: number;
  audioTracks: number;
}

export interface ProjectSettings {
  language: string;
  model: string;
  device: "auto" | "cpu" | "cuda";
  wordTimestamps: boolean;
  vadFilter: boolean;
  initialPrompt: string;
  hotwords: string;
  followPlayback: boolean;
  performanceProfile: PerformanceProfile;
  cpuThreads: number;
  processPriority: ProcessPriority;
  qualityMode: QualityMode;
  batchSize: number;
  reviewLowConfidence: boolean;
  paragraphMode: boolean;
  maxParagraphSeconds: number;
  maxParagraphCharacters: number;
  audioEnhancement: AudioEnhancement;
  diarizationMode: DiarizationMode;
  experienceMode: ExperienceMode;
  speakerCountMode: SpeakerCountMode;
  speakerCount: number;
  speakerSensitivity: number;
  voiceProfilesEnabled: boolean;
  voiceProfileAutoLearn: boolean;
  voiceProfileMinConfidence: number;
  liveLatency: LiveLatency;
  subtitleLineLength: number;
  subtitleMaxLines: number;
}

export type PerformanceProfile = "balanced" | "performance" | "maximum" | "custom";
export type ProcessPriority = "normal" | "high";
export type QualityMode = "instant" | "professional" | "maximum";
export type AudioEnhancement = "off" | "adaptive" | "speech" | "strong";
export type DiarizationMode = "off" | "adaptive" | "neural" | "precise" | "channels";
export type ExperienceMode = "simple" | "advanced";
export type SpeakerCountMode = "auto" | "exact";
export type LiveLatency = "ultra" | "balanced" | "stable";
export type LiveAudioSource = "microphone" | "system" | "mixed";

export interface HardwareInfo {
  cpu: {
    name: string;
    physicalCores: number;
    logicalCores: number;
    usagePercent: number;
  };
  memory: {
    totalMiB: number;
    availableMiB: number;
    usagePercent: number;
  };
  gpu: {
    name: string;
    totalVramMiB: number;
    usedVramMiB: number;
    utilizationPercent: number;
    driverVersion?: string;
  } | null;
  cudaAvailable: boolean;
  recommendedProfile: PerformanceProfile;
}

export interface TranscriptionProject {
  id: string;
  name: string;
  mediaPath: string;
  mediaUrl: string;
  mediaType: MediaKind;
  mediaHash?: string;
  durationMs: number;
  language?: string;
  detectedLanguage?: string;
  model: string;
  createdAt: string;
  updatedAt: string;
  transcriptionStatus: JobState;
  lastPlaybackPositionMs: number;
  settings: ProjectSettings;
  segments: TranscriptSegment[];
  insights?: ProjectInsights | null;
}

export interface InsightPoint {
  id: string;
  title: string;
  text: string;
  startMs: number;
  endMs: number;
  segmentId: string;
}

export interface InsightChapter {
  id: string;
  title: string;
  startMs: number;
  endMs: number;
  description: string;
}

export interface ProjectInsights {
  projectId: string;
  generatedAt: string;
  method: string;
  mode: "general" | "conversation" | "meeting" | "interview" | "class" | "podcast" | "personal" | "legal";
  summary: string;
  keyPoints: InsightPoint[];
  chapters: InsightChapter[];
  concepts: Array<{ id: string; label: string; weight: number }>;
  conceptEdges: Array<{ source: string; target: string; weight: number }>;
  signals: { questions: number; agreements: number; affectionMarkers: number; tensionMarkers: number };
  statistics: { wordCount: number; paragraphCount: number; questions: number; wordsPerMinute: number };
  notice: string;
  depth?: "quick" | "deep";
  model?: string;
  processingSeconds?: number;
}

export type InsightDepth = "deep" | "quick";

export interface LocalAiStatus {
  available: boolean;
  version: string;
  model: string;
  installed: boolean;
  models: string[];
  endpoint: string;
}

export interface SpeakerAiStatus {
  installed: boolean;
  ready: boolean;
  backend: string;
  model: string;
  path: string;
  sizeBytes: number;
  expectedBytes: number;
  privacy: string;
  preciseAvailable: boolean;
  notice: string;
}

export interface VoiceProfile {
  id: string;
  name: string;
  color: string;
  sampleCount: number;
  totalDurationMs: number;
  sourceProjectCount?: number;
  recognizedDurationMs?: number;
  recognizedProjectCount?: number;
  recognizedSegmentCount?: number;
  averageMatchConfidence?: number | null;
  averageProfileSimilarity?: number | null;
  averageSampleConfidence?: number | null;
  reliabilityScore?: number | null;
  matchThreshold: number;
  enabled: boolean;
  ready: boolean;
  reliability: "aprendiendo" | "buena" | "alta";
  createdAt: string;
  updatedAt: string;
  lastMatchedAt?: string | null;
}

export interface VoiceProfileCatalog {
  profiles: VoiceProfile[];
  encryption: string;
  storesRawAudio: boolean;
  learnedSamples?: number;
  createdProfiles?: string[];
  receivedObservations?: number;
  receivedSamples?: number;
  rejectedObservations?: number;
  rejectedSamples?: number;
  minimumConfidence?: number;
  rejectionReasons?: Record<string, number>;
}

export interface VoiceProfileComparison {
  sourceProfileId: string;
  sourceName: string;
  targetProfileId: string;
  targetName: string;
  similarity: number | null;
  threshold: number;
  verdict: "alta" | "compatible" | "baja" | "sin_datos";
}

export interface VoiceProfileMergeResult {
  merged: boolean;
  sourceProfileId: string;
  sourceName: string;
  targetProfileId: string;
  targetName: string;
  targetProfile: VoiceProfile;
  movedSamples: number;
  removedSamples: number;
  retainedSamples: number;
  updatedSegments: number;
  affectedProjectIds: string[];
  catalog: VoiceProfileCatalog;
}

export interface VoiceLearningProgress {
  projectId: string;
  state: "running" | "completed" | "cancelled" | "failed";
  stage: "decoding" | "speaker_embedding" | "speaker_alignment" | "learning" | "completed";
  phase: string;
  message: string;
  percent: number;
  completedUnits?: number;
  totalUnits?: number;
  etaMs?: number | null;
  elapsedMs?: number;
  learnedSamples?: number;
  createdProfiles?: string[];
  receivedSamples?: number;
  rejectedSamples?: number;
}

export interface DiagnosticCheck {
  id: string;
  label: string;
  status: "ok" | "warning" | "error";
  detail: string;
}

export interface SystemDiagnostics {
  status: "ok" | "warning" | "error";
  checks: DiagnosticCheck[];
  errors: number;
  warnings: number;
  media?: MediaMetadata | null;
  hardware: HardwareInfo;
  models: string[];
  mediaCandidates?: string[];
}

export interface AssistantCitation {
  segmentId: string;
  startMs: number;
  endMs: number;
  excerpt: string;
}

export interface AssistantAnswer {
  id: string;
  projectId: string;
  question: string;
  answer: string;
  citations: AssistantCitation[];
  model: string;
  generatedAt: string;
}

export interface AssistantMessage {
  id: string;
  projectId: string;
  role: "user" | "assistant";
  content: string;
  citations: AssistantCitation[];
  model?: string;
  createdAt?: string;
}

export interface ManagedModel {
  id: string;
  name: string;
  sizeGiB: number;
  memoryGiB: number;
  speed: string;
  accuracy: string;
  description: string;
  installed: boolean;
  installedBytes: number;
  paths: string[];
  recommended?: boolean;
  integrity?: "ready" | "partial" | "missing";
  missingFiles?: string[];
  downloadBytes?: number;
  requiredFreeBytes?: number;
  canInstall?: boolean;
}

export interface ModelCatalog {
  models: ManagedModel[];
  root: string;
  freeBytes: number;
}

export interface QueueItem {
  id: string;
  projectId: string;
  position: number;
  state: "queued" | "running" | "completed" | "failed" | "cancelled";
  name: string;
  durationMs: number;
  mediaPath: string;
  mediaType: MediaKind;
  processedDurationMs: number;
  totalDurationMs: number;
  percent: number | null;
  stage?: JobProgress["stage"] | null;
  phase?: string | null;
  message?: string | null;
  device?: string | null;
  activeModel?: string | null;
  speedX?: number | null;
  etaMs?: number | null;
  errorMessage?: string | null;
  createdAt: string;
  updatedAt: string;
}

export interface QueueStatus {
  items: QueueItem[];
  maxConcurrentJobs: number;
  effectiveConcurrency: number;
  recommendedConcurrency: number;
  runningCount: number;
  waitingCount: number;
  completedCount: number;
  failedCount: number;
  availableSlots: number;
  mode: "auto" | "manual";
}

export interface GlobalSearchResult {
  segmentId: string;
  projectId: string;
  projectName: string;
  mediaPath: string;
  startMs: number;
  endMs: number;
  speaker?: string;
  text: string;
  relevance?: number;
}

export interface SemanticSearchResponse {
  terms: string[];
  method: string;
  results: GlobalSearchResult[];
}

export interface RedactionPreview {
  counts: Record<string, number>;
  total: number;
  findings: Array<{ kind: string; segmentId: string; startMs: number; preview: string }>;
}

export interface TranscriptVersion {
  id: string;
  projectId: string;
  createdAt: string;
  model: string;
  segmentCount: number;
}

export interface ProjectMarker {
  id: string;
  projectId: string;
  timeMs: number;
  kind: "important" | "task" | "question" | "review" | string;
  label: string;
  createdAt?: string;
}

export interface EvidenceEvent {
  id: string;
  projectId: string;
  eventType: string;
  payload: Record<string, unknown>;
  createdAt: string;
}

export interface AnalysisProgress {
  projectId: string;
  stage: "preparing" | "chunk_analysis" | "synthesis" | "validation" | "completed";
  completedUnits: number;
  totalUnits: number;
  percent: number;
  message: string;
  elapsedMs: number;
  model: string;
}

export interface LiveSessionStarted {
  sessionId: string;
  sampleRate: number;
  separateSpeakers: boolean;
  createdAt: string;
  speakerBackend?: string;
  knownProfileCount?: number;
  profileRecognitionAvailable?: boolean;
}

export interface LiveChunkResult {
  sessionId: string;
  segments: TranscriptSegment[];
  durationMs: number;
  language?: string;
  device: string;
  speakerCount: number;
  speakerBackend?: string;
  latencyMs: number;
}

export interface DeletedProjectResult {
  deleted: boolean;
  projectId: string;
  name: string;
  mediaPath: string;
  mediaPreserved: boolean;
}

export interface LiveSessionResult {
  sessionId: string;
  mediaPath: string;
  durationMs: number;
  segments: TranscriptSegment[];
  language: string;
  model: string;
  createdAt: string;
  speakerCount: number;
  speakerBackend?: string;
  voiceLearningWarning?: string;
  markers?: Array<{ timeMs: number; kind: string; label: string }>;
}

export interface JobProgress {
  state: JobState;
  stage?: "preparing" | "model_loading" | "model_download" | "decoding" | "restoring" | "language_detection" | "transcribing" | "reviewing" | "diarizing" | "saving" | "completed";
  phase: string;
  processedDurationMs: number;
  totalDurationMs: number;
  percent: number | null;
  message?: string;
  device?: string;
  cpuThreads?: number;
  elapsedMs?: number;
  speedX?: number | null;
  etaMs?: number | null;
  phasePercent?: number | null;
  phaseRate?: number | null;
  segmentsProduced?: number;
  ramMiB?: number;
  cpuUsagePercent?: number;
  systemRamUsedMiB?: number;
  systemRamTotalMiB?: number;
  gpuUsagePercent?: number;
  gpuVramUsedMiB?: number;
  gpuVramTotalMiB?: number;
  performanceProfile?: PerformanceProfile;
  qualityMode?: QualityMode;
  activeModel?: string;
  reviewSegments?: number;
  reviewCompletedUnits?: number;
  reviewTotalUnits?: number;
  reviewEtaMs?: number | null;
  diarizationCompletedUnits?: number;
  diarizationTotalUnits?: number;
  diarizationEtaMs?: number | null;
  speakerBackend?: string;
}

export interface EngineEvent<T = unknown> {
  type: string;
  requestId?: string;
  payload: T;
}

export interface RecentProject {
  id: string;
  name: string;
  mediaPath: string;
  mediaType: MediaKind;
  updatedAt: string;
  transcriptionStatus: JobState;
  durationMs: number;
}

export interface AppSettings {
  theme: "system" | "light" | "dark";
  defaultModel: string;
  defaultLanguage: string;
  device: "auto" | "cpu" | "cuda";
  skipSeconds: number;
  autosaveSeconds: number;
  textScale: number;
  performanceProfile: PerformanceProfile;
  cpuThreads: number;
  processPriority: ProcessPriority;
  qualityMode: QualityMode;
  batchSize: number;
  reviewLowConfidence: boolean;
  paragraphMode: boolean;
  maxParagraphSeconds: number;
  maxParagraphCharacters: number;
  audioEnhancement: AudioEnhancement;
  diarizationMode: DiarizationMode;
  experienceMode: ExperienceMode;
  speakerCountMode: SpeakerCountMode;
  speakerCount: number;
  speakerSensitivity: number;
  voiceProfilesEnabled: boolean;
  voiceProfileAutoLearn: boolean;
  voiceProfileMinConfidence: number;
  liveLatency: LiveLatency;
  liveAudioSource: LiveAudioSource;
  subtitleLineLength: number;
  subtitleMaxLines: number;
}

export const DEFAULT_SETTINGS: AppSettings = {
  theme: "system",
  defaultModel: "turbo",
  defaultLanguage: "es",
  device: "auto",
  skipSeconds: 10,
  autosaveSeconds: 3,
  textScale: 1,
  performanceProfile: "maximum",
  cpuThreads: 0,
  processPriority: "normal",
  qualityMode: "professional",
  batchSize: 8,
  reviewLowConfidence: true,
  paragraphMode: true,
  maxParagraphSeconds: 42,
  maxParagraphCharacters: 620,
  audioEnhancement: "adaptive",
  diarizationMode: "neural",
  experienceMode: "simple",
  speakerCountMode: "auto",
  speakerCount: 8,
  speakerSensitivity: 55,
  voiceProfilesEnabled: false,
  voiceProfileAutoLearn: true,
  voiceProfileMinConfidence: 72,
  liveLatency: "balanced",
  liveAudioSource: "microphone",
  subtitleLineLength: 42,
  subtitleMaxLines: 2,
};

export const DEFAULT_PROJECT_SETTINGS: ProjectSettings = {
  language: "auto",
  model: "turbo",
  device: "auto",
  wordTimestamps: true,
  vadFilter: true,
  initialPrompt: "",
  hotwords: "",
  followPlayback: true,
  performanceProfile: "maximum",
  cpuThreads: 0,
  processPriority: "normal",
  qualityMode: "professional",
  batchSize: 8,
  reviewLowConfidence: true,
  paragraphMode: true,
  maxParagraphSeconds: 42,
  maxParagraphCharacters: 620,
  audioEnhancement: "adaptive",
  diarizationMode: "neural",
  experienceMode: "simple",
  speakerCountMode: "auto",
  speakerCount: 8,
  speakerSensitivity: 55,
  voiceProfilesEnabled: false,
  voiceProfileAutoLearn: true,
  voiceProfileMinConfidence: 72,
  liveLatency: "balanced",
  subtitleLineLength: 42,
  subtitleMaxLines: 2,
};
