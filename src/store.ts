import { create } from "zustand";
import type { AppSettings, JobProgress, ProjectInsights, RecentProject, TranscriptSegment, TranscriptionProject, VoiceProfile } from "./types";
import { DEFAULT_SETTINGS } from "./types";

type HistoryEntry =
  | {
      kind: "text";
      segmentId: string;
      before: string;
      after: string;
      beforeReview?: TranscriptSegment["reviewState"];
      afterReview?: TranscriptSegment["reviewState"];
    }
  | { kind: "segments"; before: TranscriptSegment[]; after: TranscriptSegment[] };

interface AppState {
  project: TranscriptionProject | null;
  recentProjects: RecentProject[];
  voiceProfiles: VoiceProfile[] | null;
  settings: AppSettings;
  progress: JobProgress;
  currentTimeMs: number;
  isPlaying: boolean;
  isDirty: boolean;
  error: string | null;
  notice: string | null;
  history: HistoryEntry[];
  future: HistoryEntry[];
  setProject: (project: TranscriptionProject | null) => void;
  updateProjectSettings: (settings: Partial<TranscriptionProject["settings"]>) => void;
  setRecentProjects: (projects: RecentProject[]) => void;
  setVoiceProfiles: (profiles: VoiceProfile[]) => void;
  setSettings: (settings: Partial<AppSettings>) => void;
  setProgress: (progress: Partial<JobProgress>) => void;
  setCurrentTime: (ms: number) => void;
  setPlaying: (playing: boolean) => void;
  setSegments: (segments: TranscriptSegment[], append?: boolean) => void;
  setInsights: (insights: ProjectInsights | null) => void;
  editSegment: (id: string, text: string, commit?: boolean) => void;
  editSpeaker: (id: string, speaker?: string, speakerProfileId?: string) => void;
  reviewSpeaker: (id: string) => void;
  replaceAll: (query: string, replacement: string) => number;
  splitSegment: (id: string, position: number, text?: string) => void;
  mergeWithNext: (id: string) => void;
  markSaved: () => void;
  setError: (error: string | null) => void;
  setNotice: (notice: string | null) => void;
  undo: () => void;
  redo: () => void;
}

const initialProgress: JobProgress = { state: "idle", phase: "Preparado", processedDurationMs: 0, totalDurationMs: 0, percent: null };

export const useAppStore = create<AppState>((set, get) => ({
  project: null,
  recentProjects: [],
  voiceProfiles: null,
  settings: loadSettings(),
  progress: initialProgress,
  currentTimeMs: 0,
  isPlaying: false,
  isDirty: false,
  error: null,
  notice: null,
  history: [],
  future: [],
  setProject: (project) => set({ project, currentTimeMs: project?.lastPlaybackPositionMs ?? 0, progress: project ? { ...initialProgress, state: project.transcriptionStatus } : initialProgress, isDirty: false, history: [], future: [], error: null }),
  updateProjectSettings: (settings) => set((state) => state.project ? ({ project: { ...state.project, settings: { ...state.project.settings, ...settings }, updatedAt: new Date().toISOString() }, isDirty: true }) : {}),
  setRecentProjects: (recentProjects) => set({ recentProjects }),
  setVoiceProfiles: (voiceProfiles) => set({ voiceProfiles }),
  setSettings: (partial) => set((state) => {
    const settings = { ...state.settings, ...partial };
    localStorage.setItem("transcriptor.settings", JSON.stringify(settings));
    return { settings };
  }),
  setProgress: (partial) => set((state) => ({ progress: { ...state.progress, ...partial } })),
  setCurrentTime: (currentTimeMs) => set({ currentTimeMs }),
  setPlaying: (isPlaying) => set({ isPlaying }),
  setSegments: (segments, append = false) => set((state) => {
    if (!state.project) return {};
    const next = append ? mergeSegments(state.project.segments, segments) : segments;
    return { project: { ...state.project, segments: next, updatedAt: new Date().toISOString() }, isDirty: true };
  }),
  setInsights: (insights) => set((state) => state.project ? ({ project: { ...state.project, insights } }) : {}),
  editSegment: (id, text, commit = false) => set((state) => {
    if (!state.project) return {};
    const current = state.project.segments.find((segment) => segment.id === id);
    if (!current) return {};
    const textChanged = current.text !== text;
    if (!textChanged && !commit) return {};
    const nextReview = commit ? (textChanged ? "corrected" : "accepted") : current.reviewState;
    if (!textChanged && current.reviewState === nextReview) return {};
    const history: HistoryEntry[] = commit
      ? [...state.history.slice(-99), {
          kind: "text",
          segmentId: id,
          before: current.text,
          after: text,
          beforeReview: current.reviewState,
          afterReview: nextReview,
        }]
      : state.history;
    return {
      project: {
        ...state.project,
        segments: state.project.segments.map((segment) => segment.id === id
          ? { ...segment, text, reviewState: nextReview }
          : segment),
        updatedAt: new Date().toISOString(),
      },
      isDirty: true,
      history,
      future: commit ? [] : state.future,
    };
  }),
  editSpeaker: (id, speaker, speakerProfileId) => set((state) => {
    if (!state.project) return {};
    const normalizedSpeaker = speaker || undefined;
    const normalizedProfileId = speakerProfileId || undefined;
    const current = state.project.segments.find((segment) => segment.id === id);
    if (
      !current
      || (
        current.speaker === normalizedSpeaker
        && current.speakerProfileId === normalizedProfileId
      )
    ) return {};
    return {
      project: {
        ...state.project,
        segments: state.project.segments.map((segment) => segment.id === id ? {
          ...segment,
          speaker: normalizedSpeaker,
          speakerProfileId: normalizedProfileId,
          speakerMatchConfidence: undefined,
          speakerProvisional: false,
          speakerReviewState: "corrected",
        } : segment),
        updatedAt: new Date().toISOString(),
        insights: null,
      },
      isDirty: true,
    };
  }),
  reviewSpeaker: (id) => set((state) => {
    if (!state.project) return {};
    const current = state.project.segments.find((segment) => segment.id === id);
    if (!current || current.speakerReviewState === "accepted") return {};
    return {
      project: {
        ...state.project,
        segments: state.project.segments.map((segment) => segment.id === id
          ? { ...segment, speakerReviewState: "accepted" }
          : segment),
        updatedAt: new Date().toISOString(),
      },
      isDirty: true,
    };
  }),
  replaceAll: (query, replacement) => {
    const state = get();
    if (!state.project || !query) return 0;
    const pattern = new RegExp(escapeRegExp(query), "gi");
    let replacements = 0;
    const next = state.project.segments.map((segment) => {
      const matches = segment.text.match(pattern)?.length ?? 0;
      replacements += matches;
      return matches ? { ...segment, text: segment.text.replace(pattern, replacement) } : segment;
    });
    if (!replacements) return 0;
    set({
      project: { ...state.project, segments: next, updatedAt: new Date().toISOString(), insights: null },
      history: [...state.history.slice(-99), { kind: "segments", before: state.project.segments, after: next }],
      future: [],
      isDirty: true,
    });
    return replacements;
  },
  splitSegment: (id, position, suppliedText) => set((state) => {
    if (!state.project) return {};
    const index = state.project.segments.findIndex((segment) => segment.id === id);
    if (index < 0) return {};
    const segment = state.project.segments[index];
    const text = suppliedText ?? segment.text;
    const safePosition = Math.min(text.length - 1, Math.max(1, position));
    const leftText = text.slice(0, safePosition).trim();
    const rightText = text.slice(safePosition).trim();
    if (!leftText || !rightText) return {};
    const splitRatio = safePosition / text.length;
    const splitMs = Math.round(segment.startMs + (segment.endMs - segment.startMs) * splitRatio);
    const leftWords = segment.words.filter((word) => word.endMs <= splitMs);
    const rightWords = segment.words.filter((word) => word.endMs > splitMs);
    const replacement: TranscriptSegment[] = [
      {
        ...segment,
        endMs: splitMs,
        text: leftText,
        words: leftWords,
        reviewState: undefined,
        speakerReviewState: undefined,
      },
      {
        ...segment,
        id: crypto.randomUUID(),
        startMs: splitMs,
        text: rightText,
        words: rightWords,
        reviewState: undefined,
        speakerReviewState: undefined,
      },
    ];
    const next = [...state.project.segments.slice(0, index), ...replacement, ...state.project.segments.slice(index + 1)]
      .map((item, order) => ({ ...item, order }));
    return {
      project: { ...state.project, segments: next, updatedAt: new Date().toISOString(), insights: null },
      history: [...state.history.slice(-99), { kind: "segments", before: state.project.segments, after: next }],
      future: [],
      isDirty: true,
    };
  }),
  mergeWithNext: (id) => set((state) => {
    if (!state.project) return {};
    const index = state.project.segments.findIndex((segment) => segment.id === id);
    if (index < 0 || index >= state.project.segments.length - 1) return {};
    const current = state.project.segments[index];
    const following = state.project.segments[index + 1];
    const sameSpeaker = current.speaker === following.speaker
      && current.speakerProfileId === following.speakerProfileId;
    const textReviewed = current.reviewState !== undefined && following.reviewState !== undefined;
    const speakerReviewed = sameSpeaker
      && current.speakerReviewState !== undefined
      && following.speakerReviewState !== undefined;
    const merged: TranscriptSegment = {
      ...current,
      endMs: Math.max(current.endMs, following.endMs),
      text: `${current.text.trim()} ${following.text.trim()}`.trim(),
      words: [...current.words, ...following.words],
      confidence: minimumDefined(current.confidence, following.confidence),
      reviewState: textReviewed
        ? (current.reviewState === "corrected" || following.reviewState === "corrected" ? "corrected" : "accepted")
        : undefined,
      speaker: sameSpeaker ? current.speaker : undefined,
      speakerProfileId: sameSpeaker ? current.speakerProfileId : undefined,
      speakerConfidence: sameSpeaker
        ? minimumDefined(current.speakerConfidence, following.speakerConfidence)
        : undefined,
      speakerMatchConfidence: sameSpeaker
        ? minimumDefined(current.speakerMatchConfidence, following.speakerMatchConfidence)
        : undefined,
      speakerProvisional: sameSpeaker
        ? Boolean(current.speakerProvisional || following.speakerProvisional)
        : true,
      speakerReviewState: speakerReviewed
        ? (
            current.speakerReviewState === "corrected" || following.speakerReviewState === "corrected"
              ? "corrected"
              : "accepted"
          )
        : undefined,
    };
    const next = [...state.project.segments.slice(0, index), merged, ...state.project.segments.slice(index + 2)]
      .map((item, order) => ({ ...item, order }));
    return {
      project: { ...state.project, segments: next, updatedAt: new Date().toISOString(), insights: null },
      history: [...state.history.slice(-99), { kind: "segments", before: state.project.segments, after: next }],
      future: [],
      isDirty: true,
    };
  }),
  markSaved: () => set({ isDirty: false }),
  setError: (error) => set({ error }),
  setNotice: (notice) => set({ notice }),
  undo: () => {
    const state = get();
    const action = state.history.at(-1);
    if (!action || !state.project) return;
    const segments = action.kind === "segments"
      ? action.before
      : state.project.segments.map((segment) => segment.id === action.segmentId
        ? { ...segment, text: action.before, reviewState: action.beforeReview }
        : segment);
    set({ project: { ...state.project, segments }, history: state.history.slice(0, -1), future: [action, ...state.future], isDirty: true });
  },
  redo: () => {
    const state = get();
    const action = state.future[0];
    if (!action || !state.project) return;
    const segments = action.kind === "segments"
      ? action.after
      : state.project.segments.map((segment) => segment.id === action.segmentId
        ? { ...segment, text: action.after, reviewState: action.afterReview }
        : segment);
    set({ project: { ...state.project, segments }, history: [...state.history, action], future: state.future.slice(1), isDirty: true });
  },
}));

function mergeSegments(current: TranscriptSegment[], incoming: TranscriptSegment[]): TranscriptSegment[] {
  const map = new Map(current.map((segment) => [segment.id, segment]));
  incoming.forEach((segment) => map.set(segment.id, segment));
  return [...map.values()].sort((a, b) => a.order - b.order || a.startMs - b.startMs);
}

function minimumDefined(left?: number, right?: number): number | undefined {
  if (left === undefined) return right;
  if (right === undefined) return left;
  return Math.min(left, right);
}

function loadSettings(): AppSettings {
  try {
    const settings = { ...DEFAULT_SETTINGS, ...JSON.parse(localStorage.getItem("transcriptor.settings") ?? "{}") };
    if (settings.experienceMode === "simple") {
      return {
        ...settings,
        device: "auto",
        audioEnhancement: "adaptive",
        speakerCountMode: "auto",
        speakerCount: 8,
      };
    }
    return settings;
  } catch {
    return DEFAULT_SETTINGS;
  }
}

function escapeRegExp(value: string): string {
  return value.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}
