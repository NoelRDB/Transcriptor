import type { HardwareInfo, RecentProject, SpeakerAiStatus } from "../types";

const CACHE_VERSION = 1;
const RECENT_PROJECTS_KEY = "transcriptor.ui-cache.recent-projects";
const HARDWARE_KEY = "transcriptor.ui-cache.hardware";
const SPEAKER_AI_KEY = "transcriptor.ui-cache.speaker-ai";

interface CacheEnvelope<T> {
  version: number;
  savedAt: number;
  value: T;
}

export function loadCachedRecentProjects(): RecentProject[] {
  return readCache(RECENT_PROJECTS_KEY, 30 * 24 * 60 * 60 * 1_000, isRecentProjectArray) ?? [];
}

export function cacheRecentProjects(projects: RecentProject[]): void {
  writeCache(RECENT_PROJECTS_KEY, projects);
}

export function loadCachedHardwareInfo(): HardwareInfo | null {
  return readCache(HARDWARE_KEY, 7 * 24 * 60 * 60 * 1_000, isHardwareInfo);
}

export function cacheHardwareInfo(hardware: HardwareInfo): void {
  writeCache(HARDWARE_KEY, hardware);
}

export function loadCachedSpeakerAiStatus(): SpeakerAiStatus | null {
  return readCache(SPEAKER_AI_KEY, 30 * 24 * 60 * 60 * 1_000, isSpeakerAiStatus);
}

export function cacheSpeakerAiStatus(status: SpeakerAiStatus): void {
  writeCache(SPEAKER_AI_KEY, status);
}

function readCache<T>(key: string, maxAgeMs: number, validate: (value: unknown) => value is T): T | null {
  try {
    if (typeof localStorage === "undefined") return null;
    const parsed = JSON.parse(localStorage.getItem(key) ?? "null") as Partial<CacheEnvelope<unknown>> | null;
    if (
      !parsed
      || parsed.version !== CACHE_VERSION
      || typeof parsed.savedAt !== "number"
      || Date.now() - parsed.savedAt > maxAgeMs
      || !validate(parsed.value)
    ) return null;
    return parsed.value;
  } catch {
    return null;
  }
}

function writeCache<T>(key: string, value: T): void {
  try {
    if (typeof localStorage === "undefined") return;
    const envelope: CacheEnvelope<T> = { version: CACHE_VERSION, savedAt: Date.now(), value };
    localStorage.setItem(key, JSON.stringify(envelope));
  } catch {
    // A restricted WebView or a full storage quota must not block the local engine.
  }
}

function isRecentProjectArray(value: unknown): value is RecentProject[] {
  return Array.isArray(value) && value.every((project) => {
    if (!project || typeof project !== "object") return false;
    const candidate = project as Partial<RecentProject>;
    return typeof candidate.id === "string"
      && typeof candidate.name === "string"
      && typeof candidate.mediaPath === "string"
      && typeof candidate.updatedAt === "string";
  });
}

function isHardwareInfo(value: unknown): value is HardwareInfo {
  if (!value || typeof value !== "object") return false;
  const candidate = value as Partial<HardwareInfo>;
  return Boolean(candidate.cpu && candidate.memory)
    && typeof candidate.cpu?.logicalCores === "number"
    && typeof candidate.memory?.totalMiB === "number";
}

function isSpeakerAiStatus(value: unknown): value is SpeakerAiStatus {
  if (!value || typeof value !== "object") return false;
  const candidate = value as Partial<SpeakerAiStatus>;
  return typeof candidate.installed === "boolean"
    && typeof candidate.ready === "boolean"
    && typeof candidate.expectedBytes === "number";
}
