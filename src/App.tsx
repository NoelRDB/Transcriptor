import { useCallback, useEffect, useRef, useState } from "react";
import { AlertTriangle, Info, X } from "lucide-react";
import { engine, localMediaUrl } from "./lib/engine";
import { routeEngineEvent } from "./lib/engineEvents";
import { displayName, mediaKind, MEDIA_FILTERS, safeBaseName } from "./lib/media";
import { downloadText, exportProject, type ExportFormat, type TextExportFormat } from "./lib/exporters";
import { useAppStore } from "./store";
import { DEFAULT_PROJECT_SETTINGS, type AnalysisProgress, type AppSettings, type AssistantAnswer, type AssistantMessage, type InsightDepth, type LocalAiStatus, type ProjectInsights, type QualityMode, type RecordingSessionResult, type SystemDiagnostics, type TranscriptionProject } from "./types";
import { Toolbar } from "./components/Toolbar";
import { Welcome } from "./components/Welcome";
import { MediaPlayer } from "./components/MediaPlayer";
import { TranscriptPanel } from "./components/TranscriptPanel";
import { SettingsDialog } from "./components/SettingsDialog";
import { StatusBar } from "./components/StatusBar";
import { InsightsDialog } from "./components/InsightsDialog";
import { LiveRecorderDialog } from "./components/LiveRecorderDialog";
import { DiagnosticsDialog } from "./components/DiagnosticsDialog";
import { VoicesDialog } from "./components/VoicesDialog";
import { ModelSetupDialog } from "./components/ModelSetupDialog";
import { learnFromCorrection, vocabularyPrompt } from "./lib/dictionary";
import { formatClock } from "./lib/time";
import { buildAutomaticPlan } from "./lib/automaticPlan";

export default function App() {
  const store = useAppStore();
  const [showSettings, setShowSettings] = useState(false);
  const [showInsights, setShowInsights] = useState(false);
  const [showLive, setShowLive] = useState(false);
  const [showDiagnostics, setShowDiagnostics] = useState(false);
  const [showVoices, setShowVoices] = useState(false);
  const [showModelSetup, setShowModelSetup] = useState(false);
  const [diagnostics, setDiagnostics] = useState<SystemDiagnostics | null>(null);
  const [diagnosticsLoading, setDiagnosticsLoading] = useState(false);
  const [assistantAnswers, setAssistantAnswers] = useState<AssistantAnswer[]>([]);
  const [assistantLoading, setAssistantLoading] = useState(false);
  const [insightsLoading, setInsightsLoading] = useState(false);
  const [insightMode, setInsightMode] = useState<ProjectInsights["mode"]>("general");
  const [insightDepth, setInsightDepth] = useState<InsightDepth>("deep");
  const [analysisProgress, setAnalysisProgress] = useState<AnalysisProgress | null>(null);
  const [analysisStartedAt, setAnalysisStartedAt] = useState<number | null>(null);
  const [localAiStatus, setLocalAiStatus] = useState<LocalAiStatus | null>(null);
  const [seekSignal, setSeekSignal] = useState(0);
  const [split, setSplit] = useState(57);
  const [transcriptFocus, setTranscriptFocus] = useState(false);
  const dragging = useRef(false);
  const activeProjectId = store.project?.id;

  useEffect(() => {
    if (!store.notice) return;
    const timer = window.setTimeout(() => useAppStore.getState().setNotice(null), 9_000);
    return () => window.clearTimeout(timer);
  }, [store.notice]);

  useEffect(() => {
    document.documentElement.dataset.theme = store.settings.theme;
    document.documentElement.style.setProperty("--text-scale", String(store.settings.textScale));
  }, [store.settings]);

  const openMedia = useCallback(async (path?: string) => {
    const state = useAppStore.getState();
    try {
      let selected = path;
      if (!selected) {
        if (!engine.available) return;
        const { open } = await import("@tauri-apps/plugin-dialog");
        const result = await open({ multiple: false, directory: false, filters: MEDIA_FILTERS });
        if (!result) return;
        selected = result;
      }
      if (selected.toLocaleLowerCase().endsWith(".transcriptor")) {
        if (!engine.available) throw new Error("Los proyectos portátiles sólo se abren en la aplicación de escritorio.");
        state.setProgress({ state: "analyzing", stage: "preparing", phase: "Importando el proyecto…", message: "Verificando archivos, texto y huellas digitales…" });
        const imported = await engine.importPackage(selected);
        state.setProject({ ...imported, mediaUrl: await localMediaUrl(imported.mediaPath) });
        state.setRecentProjects(await engine.listProjects());
        return;
      }
      const kind = mediaKind(selected);
      if (!kind) throw new Error("Este formato no está admitido. Selecciona un archivo de audio o vídeo compatible.");
      state.setProgress({ state: "analyzing", stage: "preparing", phase: "Analizando el archivo…", message: "Leyendo códec, pistas y duración…" });
      const metadata = engine.available ? await engine.analyze(selected) : {};
      if (engine.available) {
        const saved = await engine.loadProjectForMedia(selected);
        if (saved) {
          state.setProject({ ...saved, mediaPath: selected, mediaUrl: await localMediaUrl(selected) });
          state.setRecentProjects(await engine.listProjects());
          return;
        }
      }
      const now = new Date().toISOString();
      const project: TranscriptionProject = {
        id: crypto.randomUUID(), name: displayName(selected), mediaPath: selected, mediaUrl: await localMediaUrl(selected), mediaType: kind,
        durationMs: Number(metadata.durationMs ?? 0), model: state.settings.defaultModel, createdAt: now, updatedAt: now,
        transcriptionStatus: "idle", lastPlaybackPositionMs: 0, segments: [],
        settings: projectSettingsFromApp(state.settings),
      };
      state.setProject(project);
      if (engine.available) await engine.save(project);
    } catch (error) {
      const message = error instanceof Error ? error.message : String(error);
      state.setProgress({ state: "failed", phase: "No se pudo abrir el archivo", message });
      state.setError(message);
    }
  }, []);

  const queueMediaFiles = useCallback(async (
    paths: string[],
    onProgress?: (completed: number, total: number, currentName: string) => void,
  ) => {
    const state = useAppStore.getState();
    const uniquePaths = [...new Set(paths)];
    const failures: Array<{ path: string; message: string }> = [];
    let added = 0;
    let reused = 0;
    const automaticInputs = state.settings.experienceMode === "simple"
      ? await Promise.allSettled([engine.getHardwareInfo(), engine.getSpeakerAiStatus()])
      : null;

    for (const [index, selected] of uniquePaths.entries()) {
      onProgress?.(index, uniquePaths.length, displayName(selected));
      try {
        const kind = mediaKind(selected);
        if (!kind) throw new Error("Formato no compatible");
        const metadata = await engine.analyze(selected);
        const saved = await engine.loadProjectForMedia(selected);
        const now = new Date().toISOString();
        let settings = saved?.settings ?? projectSettingsFromApp(state.settings);
        if (automaticInputs && automaticInputs[0].status === "fulfilled") {
          const plan = buildAutomaticPlan(
            automaticInputs[0].value,
            automaticInputs[1].status === "fulfilled" ? automaticInputs[1].value : null,
            Number(metadata.durationMs ?? saved?.durationMs ?? 0),
            state.settings.voiceProfilesEnabled,
          );
          settings = {
            ...settings,
            ...projectSettingsFromApp({ ...state.settings, ...plan.settings }),
          };
        }
        const queuedProject: TranscriptionProject = saved
          ? {
            ...saved,
            mediaPath: selected,
            mediaUrl: await localMediaUrl(selected),
            transcriptionStatus: "idle",
            settings,
          }
          : {
            id: crypto.randomUUID(),
            name: displayName(selected),
            mediaPath: selected,
            mediaUrl: await localMediaUrl(selected),
            mediaType: kind,
            durationMs: Number(metadata.durationMs ?? 0),
            model: settings.model,
            createdAt: now,
            updatedAt: now,
            transcriptionStatus: "idle",
            lastPlaybackPositionMs: 0,
            segments: [],
            settings,
          };
        if (saved) reused += 1;
        await engine.enqueue(queuedProject);
        added += 1;
      } catch (reason) {
        failures.push({
          path: selected,
          message: reason instanceof Error ? reason.message : String(reason),
        });
      }
      onProgress?.(index + 1, uniquePaths.length, displayName(selected));
    }
    state.setRecentProjects(await engine.listProjects());
    return { added, reused, failures };
  }, []);

  useEffect(() => engine.subscribe(routeEngineEvent), []);

  useEffect(() => {
    if (!engine.available) {
      useAppStore.getState().setVoiceProfiles([]);
      return;
    }
    let active = true;
    engine.listVoiceProfiles()
      .then((catalog) => {
        if (active) useAppStore.getState().setVoiceProfiles(catalog.profiles);
      })
      .catch(() => undefined);
    return () => { active = false; };
  }, []);

  useEffect(() => engine.subscribe((event) => {
    if (event.type === "job_completed" || event.type === "job_failed" || event.type === "job_cancelled") {
      void engine.listProjects().then(useAppStore.getState().setRecentProjects).catch(() => undefined);
    }
  }), []);

  useEffect(() => engine.subscribe((event) => {
    const projectId = String((event.payload as { projectId?: string }).projectId ?? "");
    if (projectId !== useAppStore.getState().project?.id) return;
    if (event.type === "analysis_progress") {
      setAnalysisProgress(event.payload as AnalysisProgress);
    }
    if (event.type === "analysis_completed") {
      const insights = (event.payload as { insights: ProjectInsights }).insights;
      useAppStore.getState().setInsights(insights);
      setInsightsLoading(false);
      setAnalysisStartedAt(null);
    }
    if (event.type === "analysis_cancelled" || event.type === "analysis_failed") {
      const message = String((event.payload as { message?: string }).message ?? "El análisis no pudo completarse.");
      setInsightsLoading(false);
      setAnalysisStartedAt(null);
      if (event.type === "analysis_failed") useAppStore.getState().setError(message);
    }
    if (event.type === "assistant_completed") {
      const answer = (event.payload as { answer: AssistantAnswer }).answer;
      setAssistantAnswers((current) => [answer, ...current]);
      setAssistantLoading(false);
    }
    if (event.type === "assistant_cancelled" || event.type === "assistant_failed") {
      setAssistantLoading(false);
      if (event.type === "assistant_failed") {
        useAppStore.getState().setError(String((event.payload as { message?: string }).message ?? "La IA local no pudo responder."));
      }
    }
  }), []);

  useEffect(() => {
    let active = true;
    setAssistantLoading(false);
    if (!activeProjectId || !engine.available) {
      setAssistantAnswers([]);
      return () => { active = false; };
    }
    engine.listAssistantMessages(activeProjectId)
      .then((messages) => { if (active) setAssistantAnswers(messagesToAnswers(messages)); })
      .catch(() => { if (active) setAssistantAnswers([]); });
    return () => { active = false; };
  }, [activeProjectId]);

  useEffect(() => {
    if (!showInsights || !engine.available) return;
    let current = true;
    engine.getLocalAiStatus().then((status) => { if (current) setLocalAiStatus(status); }).catch(() => {
      if (current) setLocalAiStatus({ available: false, installed: false, version: "", model: "qwen3.5:9b", models: [], endpoint: "http://127.0.0.1:11434" });
    });
    return () => { current = false; };
  }, [showInsights]);

  useEffect(() => {
    if (!engine.available) return;
    let unsubscribe: (() => void) | undefined;
    import("@tauri-apps/api/webview").then(({ getCurrentWebview }) => getCurrentWebview().onDragDropEvent((event) => {
      if (event.payload.type === "drop" && event.payload.paths[0]) void openMedia(event.payload.paths[0]);
    })).then((fn) => { unsubscribe = fn; }).catch(() => undefined);
    return () => { unsubscribe?.(); };
  }, [openMedia]);

  useEffect(() => {
    if (!engine.available) return;
    engine.listProjects().then(useAppStore.getState().setRecentProjects).catch(() => undefined);
  }, []);

  useEffect(() => {
    if (
      !engine.available
      || sessionStorage.getItem("transcriptor.model-onboarding.postponed") === "true"
    ) return;
    if (localStorage.getItem("transcriptor.model-onboarding.v1") !== "completed") {
      setShowModelSetup(true);
      return;
    }
    let active = true;
    Promise.all([
      engine.getHardwareInfo(),
      engine.getCudaRuntimeStatus(),
    ]).then(([hardware, runtime]) => {
      if (
        active
        && hardware.gpu
        && runtime.supported
        && !runtime.ready
        && localStorage.getItem("transcriptor.cuda-runtime-prompt.v1") !== "dismissed"
      ) {
        setShowModelSetup(true);
      }
    }).catch(() => undefined);
    return () => { active = false; };
  }, []);

  useEffect(() => {
    if (!store.project || !store.isDirty || !engine.available || ["analyzing", "waiting_model", "transcribing"].includes(store.progress.state)) return;
    const timer = window.setTimeout(() => engine.save(store.project!).then(useAppStore.getState().markSaved).catch((error) => useAppStore.getState().setError(error.message)), store.settings.autosaveSeconds * 1000);
    return () => window.clearTimeout(timer);
  }, [store.project, store.isDirty, store.settings.autosaveSeconds, store.progress.state]);

  useEffect(() => {
    if (!activeProjectId || !engine.available) return;
    const timer = window.setInterval(() => {
      const state = useAppStore.getState();
      if (state.project && !["analyzing", "waiting_model", "transcribing"].includes(state.progress.state)) {
        void engine.save({ ...state.project, lastPlaybackPositionMs: state.currentTimeMs }).catch(() => undefined);
      }
    }, 15_000);
    return () => window.clearInterval(timer);
  }, [activeProjectId]);

  async function openBrowserFile(file: File) {
    const kind = mediaKind(file.name);
    if (!kind) return store.setError("Este formato no está admitido.");
    const now = new Date().toISOString();
    store.setProject({ id: crypto.randomUUID(), name: displayName(file.name), mediaPath: file.name, mediaUrl: URL.createObjectURL(file), mediaType: kind, durationMs: 0, model: store.settings.defaultModel, createdAt: now, updatedAt: now, transcriptionStatus: "idle", lastPlaybackPositionMs: 0, segments: [], settings: projectSettingsFromApp(store.settings) });
    store.setError("La vista web puede reproducir el archivo, pero la transcripción requiere abrir la aplicación Tauri con “npm run tauri dev”.");
  }

  async function transcribe(projectOverride?: TranscriptionProject, qualityOverride?: QualityMode) {
    const targetProject = projectOverride ?? useAppStore.getState().project;
    if (!targetProject) return;
    if (!engine.available) return store.setError("La transcripción real se ejecuta en la aplicación de escritorio, no en la vista web.");
    let effectiveSettings = store.settings;
    let automaticSummary = "";
    if (store.settings.experienceMode === "simple") {
      store.setProgress({
        state: "analyzing",
        stage: "preparing",
        phase: "Diseñando el plan automático…",
        percent: null,
        phasePercent: null,
        message: "Midiendo CPU, memoria, GPU, duración del audio e IA de hablantes…",
      });
      const [hardwareResult, speakerResult] = await Promise.allSettled([
        engine.getHardwareInfo(),
        engine.getSpeakerAiStatus(),
      ]);
      if (hardwareResult.status === "fulfilled") {
        const automaticPlan = buildAutomaticPlan(
          hardwareResult.value,
          speakerResult.status === "fulfilled" ? speakerResult.value : null,
          targetProject.durationMs,
          store.settings.voiceProfilesEnabled,
        );
        effectiveSettings = { ...store.settings, ...automaticPlan.settings };
        automaticSummary = automaticPlan.summary;
        store.setSettings(automaticPlan.settings);
      } else {
        effectiveSettings = {
          ...store.settings,
          device: "auto",
          speakerCountMode: "auto",
          speakerCount: 8,
          audioEnhancement: "adaptive",
          diarizationMode: "adaptive",
        };
        automaticSummary = "Configuración automática segura; el motor decidirá CPU/GPU, audio y número de voces.";
      }
    }
    const qualityMode = qualityOverride ?? effectiveSettings.qualityMode;
    const requiredModels = qualityMode === "professional" ? ["turbo", "large-v3"] : [qualityMode === "maximum" ? "large-v3" : "turbo"];
    const consentKey = `transcriptor.model-consent.${requiredModels.join("+")}`;
    if (!localStorage.getItem(consentKey)) {
      const accepted = window.confirm(`El modo seleccionado utiliza ${requiredModels.join(" + ")}. La primera vez descargará varios GB y los guardará sólo en este equipo. ¿Continuar?`);
      if (!accepted) {
        store.setProgress({ state: targetProject.transcriptionStatus, stage: "preparing", phase: "Preparado", percent: null, phasePercent: null, message: "No se ha descargado ni iniciado ningún modelo." });
        return;
      }
      localStorage.setItem(consentKey, "accepted");
    }
    store.setProgress({ state: "transcribing", stage: "preparing", phase: qualityOverride ? "Creando la versión final…" : store.settings.experienceMode === "simple" ? "Aplicando el piloto automático…" : "Preparando la transcripción…", processedDurationMs: 0, totalDurationMs: targetProject.durationMs, percent: 0, phasePercent: 0, message: qualityOverride ? "El borrador está guardado; revisando el audio completo…" : automaticSummary || "Iniciando el motor local…", elapsedMs: 0, speedX: null, phaseRate: null, etaMs: null, reviewCompletedUnits: undefined, reviewTotalUnits: undefined, reviewEtaMs: null, diarizationCompletedUnits: undefined, diarizationTotalUnits: undefined, diarizationEtaMs: null, speakerBackend: undefined, segmentsProduced: 0, performanceProfile: effectiveSettings.performanceProfile, qualityMode, activeModel: qualityMode === "maximum" ? "large-v3" : "turbo", device: undefined, cpuThreads: undefined, ramMiB: undefined, cpuUsagePercent: undefined, gpuUsagePercent: undefined, gpuVramUsedMiB: undefined, gpuVramTotalMiB: undefined });
    const projectWithResources = {
      ...targetProject,
      transcriptionStatus: "transcribing" as const,
      // La cola persiste el proyecto antes de ejecutarlo. Conservamos aquí la
      // versión actual para que una retranscripción pueda recuperarse o
      // versionarse antes de que lleguen los nuevos fragmentos.
      segments: targetProject.segments,
      settings: {
        ...targetProject.settings,
        language: targetProject.settings.language || effectiveSettings.defaultLanguage,
        device: effectiveSettings.device,
        performanceProfile: effectiveSettings.performanceProfile,
        cpuThreads: effectiveSettings.cpuThreads,
        processPriority: effectiveSettings.processPriority,
        qualityMode,
        model: qualityMode === "maximum" ? "large-v3" : "turbo",
        batchSize: effectiveSettings.batchSize,
        reviewLowConfidence: effectiveSettings.reviewLowConfidence,
        paragraphMode: effectiveSettings.paragraphMode,
        maxParagraphSeconds: effectiveSettings.maxParagraphSeconds,
        maxParagraphCharacters: effectiveSettings.maxParagraphCharacters,
        audioEnhancement: effectiveSettings.audioEnhancement,
        diarizationMode: effectiveSettings.diarizationMode,
        experienceMode: effectiveSettings.experienceMode,
        speakerCountMode: effectiveSettings.speakerCountMode,
        speakerCount: effectiveSettings.speakerCount,
        speakerSensitivity: effectiveSettings.speakerSensitivity,
        voiceProfilesEnabled: effectiveSettings.voiceProfilesEnabled,
        voiceProfileAutoLearn: effectiveSettings.voiceProfileAutoLearn,
        voiceProfileMinConfidence: effectiveSettings.voiceProfileMinConfidence,
        liveLatency: effectiveSettings.liveLatency,
        subtitleLineLength: effectiveSettings.subtitleLineLength,
        subtitleMaxLines: effectiveSettings.subtitleMaxLines,
        hotwords: vocabularyPrompt(targetProject.settings.hotwords),
      },
    };
    try {
      const queued = await engine.enqueue(projectWithResources);
      store.setProgress({
        state: "transcribing",
        stage: "preparing",
        phase: queued.position > 1 ? "En espera de un motor libre" : "Iniciando la transcripción…",
        message: queued.position > 1
          ? `Trabajo ${queued.position} de la cola. Comenzará automáticamente.`
          : "El motor local está preparando el archivo.",
      });
    }
    catch (error) {
      const message = error instanceof Error ? error.message : String(error);
      store.setProgress({ state: "failed", phase: "No se pudo iniciar la transcripción", message });
      store.setError(message);
    }
  }

  async function cancel() {
    if (!store.project) return;
    try {
      const result = await engine.cancel(store.project.id);
      if (!result.cancelled) {
        const removed = await engine.removeFromQueue(store.project.id);
        if (removed.removed) {
          store.setProgress({ state: "cancelled", phase: "Retirado de la cola", message: "La versión anterior se ha conservado." });
        }
      }
    }
    catch (error) { store.setError(error instanceof Error ? error.message : String(error)); }
  }

  async function exportTranscript(format: ExportFormat) {
    if (!store.project) return;
    const portable = format === "package" || format === "package-media";
    const safe = format.endsWith("-safe");
    const actualFormat = safe ? format.replace("-safe", "") : format;
    const extension = portable ? "transcriptor" : actualFormat;
    const suffix = safe ? "-anonimizado" : "";
    const filename = `${safeBaseName(store.project.name)}${suffix}.${extension}`;
    if (!engine.available) {
      if (portable || safe || format === "docx" || format === "pdf") {
        store.setError("Este formato requiere ejecutar la aplicación de escritorio.");
        return;
      }
      return downloadText(filename, exportProject(store.project, format as TextExportFormat));
    }
    try {
      const { save } = await import("@tauri-apps/plugin-dialog");
      const outputPath = await save({ defaultPath: filename, filters: [{ name: portable ? "Proyecto Transcriptor" : actualFormat.toUpperCase(), extensions: [extension] }] });
      if (!outputPath) return;
      if (portable) await engine.exportPackage(store.project, outputPath, format === "package-media");
      else await engine.export(store.project, actualFormat, outputPath, safe);
    } catch (error) { store.setError(error instanceof Error ? error.message : String(error)); }
  }

  async function exportMediaEdit(excludedSegmentIds: string[]) {
    const project = useAppStore.getState().project;
    if (!project || !engine.available || !excludedSegmentIds.length) return;
    const extension = project.mediaType === "video" ? "mp4" : "wav";
    try {
      const { save } = await import("@tauri-apps/plugin-dialog");
      const outputPath = await save({
        defaultPath: `${safeBaseName(project.name)}-editado.${extension}`,
        filters: [{ name: project.mediaType === "video" ? "Vídeo MP4" : "Audio WAV", extensions: [extension] }],
      });
      if (!outputPath) return;
      store.setProgress({ state: "analyzing", stage: "preparing", phase: "Creando copia editada…", message: `Omitiendo ${excludedSegmentIds.length} fragmentos sin modificar el original`, percent: null });
      const result = await engine.exportMediaEdit(project, excludedSegmentIds, outputPath);
      store.setProgress({ state: project.transcriptionStatus, phase: "Copia editada creada", message: `${result.removedSegments} fragmentos omitidos · ${formatClock(result.remainingDurationMs)}`, percent: 100 });
    } catch (error) {
      store.setProgress({ state: project.transcriptionStatus, phase: "Edición detenida", percent: null });
      store.setError(error instanceof Error ? error.message : String(error));
    }
  }

  async function openRecent(id: string, seekMs?: number) {
    try {
      const project = await engine.loadProject(id);
      store.setProject({ ...project, mediaUrl: await localMediaUrl(project.mediaPath) });
      if (seekMs !== undefined) {
        store.setCurrentTime(seekMs);
        setSeekSignal((value) => value + 1);
      }
    } catch (error) { store.setError(error instanceof Error ? error.message : String(error)); }
  }

  async function deleteRecent(id: string) {
    if (!engine.available) throw new Error("La eliminación de proyectos requiere la aplicación de escritorio.");
    await engine.deleteProject(id);
    if (useAppStore.getState().project?.id === id) store.setProject(null);
    store.setRecentProjects(await engine.listProjects());
  }

  async function analyzeTranscript() {
    if (!store.project?.segments.length || !engine.available) return;
    setInsightsLoading(true);
    setAnalysisProgress(null);
    setAnalysisStartedAt(Date.now());
    try {
      await engine.analyzeTranscript(store.project, insightMode, insightDepth);
    } catch (error) {
      store.setError(error instanceof Error ? error.message : String(error));
      setInsightsLoading(false);
      setAnalysisStartedAt(null);
    }
  }

  async function cancelAnalysis() {
    if (!store.project || !insightsLoading) return;
    try {
      await engine.cancelAnalysis(store.project.id);
    } catch (error) {
      store.setError(error instanceof Error ? error.message : String(error));
    }
  }

  async function groupIntoParagraphs() {
    if (!store.project?.segments.length || !engine.available) return;
    setInsightsLoading(true);
    try {
      const mediaUrl = store.project.mediaUrl;
      const grouped = await engine.groupParagraphs(store.project, store.settings.maxParagraphSeconds, store.settings.maxParagraphCharacters);
      useAppStore.getState().setProject({ ...grouped, mediaUrl, insights: null });
    } catch (error) {
      store.setError(error instanceof Error ? error.message : String(error));
    } finally {
      setInsightsLoading(false);
    }
  }

  function editSegment(id: string, text: string, commit?: boolean) {
    if (commit) {
      const previous = useAppStore.getState().project?.segments.find((segment) => segment.id === id)?.text;
      if (previous) learnFromCorrection(previous, text);
    }
    useAppStore.getState().editSegment(id, text, commit);
  }

  async function openLiveRecorder() {
    if (!engine.available) return store.setError("La grabación en directo requiere la aplicación de escritorio.");
    if (["analyzing", "waiting_model", "transcribing"].includes(store.progress.state)) return;
    if (store.project && store.isDirty) {
      try { await engine.save(store.project); store.markSaved(); }
      catch (error) { return store.setError(error instanceof Error ? error.message : String(error)); }
    }
    setShowLive(true);
  }

  async function completeLiveRecording(result: RecordingSessionResult) {
    const now = new Date().toISOString();
    const language = result.language || store.settings.defaultLanguage;
    const project: TranscriptionProject = {
      id: result.sessionId,
      name: displayName(result.mediaPath),
      mediaPath: result.mediaPath,
      mediaUrl: await localMediaUrl(result.mediaPath),
      mediaType: "audio",
      durationMs: result.durationMs,
      language,
      model: store.settings.defaultModel,
      createdAt: result.createdAt,
      updatedAt: now,
      transcriptionStatus: "idle",
      lastPlaybackPositionMs: 0,
      settings: {
        ...projectSettingsFromApp(store.settings),
        language,
      },
      segments: [],
      insights: null,
    };
    try {
      await engine.save(project);
      store.setProject(project);
      store.setRecentProjects(await engine.listProjects());
      store.setProgress({
        state: "idle",
        phase: "Grabación lista",
        processedDurationMs: 0,
        totalDurationMs: result.durationMs,
        percent: null,
        message: "Audio guardado. Pulsa Transcribir para generar el texto y reconocer las voces.",
      });
      setShowLive(false);
    } catch (error) {
      store.setError(error instanceof Error ? error.message : String(error));
    }
  }

  async function renameCurrentProject(name: string) {
    const current = useAppStore.getState().project;
    const nextName = name.trim();
    if (!current || !nextName || nextName === current.name) return;
    const updated = { ...current, name: nextName, updatedAt: new Date().toISOString() };
    try {
      await engine.save(updated);
      useAppStore.getState().setProject(updated);
      useAppStore.getState().setRecentProjects(await engine.listProjects());
    } catch (error) {
      const message = error instanceof Error ? error.message : String(error);
      useAppStore.getState().setError(message);
      throw error;
    }
  }

  async function runDiagnostics() {
    if (!engine.available) return;
    setDiagnosticsLoading(true);
    try {
      setDiagnostics(await engine.diagnose(useAppStore.getState().project?.mediaPath));
    } catch (error) {
      store.setError(error instanceof Error ? error.message : String(error));
    } finally {
      setDiagnosticsLoading(false);
    }
  }

  async function openDiagnostics() {
    setShowDiagnostics(true);
    await runDiagnostics();
  }

  async function relocateProjectMedia(candidatePath?: string) {
    const project = useAppStore.getState().project;
    if (!project || !engine.available) return;
    try {
      let selected = candidatePath;
      if (!selected) {
        const { open } = await import("@tauri-apps/plugin-dialog");
        selected = await open({ multiple: false, directory: false, filters: MEDIA_FILTERS }) ?? undefined;
      }
      if (!selected) return;
      const kind = mediaKind(selected);
      if (!kind) throw new Error("Selecciona un archivo de audio o vídeo compatible.");
      const metadata = await engine.analyze(selected);
      const updated: TranscriptionProject = {
        ...project,
        mediaPath: selected,
        mediaUrl: await localMediaUrl(selected),
        mediaType: kind,
        durationMs: Number(metadata.durationMs ?? project.durationMs),
        transcriptionStatus: project.segments.length ? "completed" : "idle",
        updatedAt: new Date().toISOString(),
      };
      await engine.save(updated);
      store.setProject(updated);
      store.setRecentProjects(await engine.listProjects());
      await runDiagnostics();
    } catch (error) {
      store.setError(error instanceof Error ? error.message : String(error));
    }
  }

  async function askTranscript(question: string) {
    const project = useAppStore.getState().project;
    if (!project || assistantLoading) return;
    setAssistantLoading(true);
    try {
      await engine.askTranscript(project, question);
    } catch (error) {
      setAssistantLoading(false);
      store.setError(error instanceof Error ? error.message : String(error));
    }
  }

  function seek(ms: number) { store.setCurrentTime(ms); setSeekSignal((value) => value + 1); }

  function changeSettings(changes: Partial<AppSettings>) {
    const state = useAppStore.getState();
    state.setSettings(changes);
    const projectChanges: Partial<TranscriptionProject["settings"]> = {};
    const directKeys = ["device", "performanceProfile", "cpuThreads", "processPriority", "qualityMode", "batchSize", "reviewLowConfidence", "paragraphMode", "maxParagraphSeconds", "maxParagraphCharacters", "audioEnhancement", "diarizationMode", "experienceMode", "speakerCountMode", "speakerCount", "speakerSensitivity", "voiceProfilesEnabled", "voiceProfileAutoLearn", "voiceProfileMinConfidence", "liveLatency", "subtitleLineLength", "subtitleMaxLines"] as const;
    directKeys.forEach((key) => { if (changes[key] !== undefined) Object.assign(projectChanges, { [key]: changes[key] }); });
    if (changes.defaultLanguage !== undefined) projectChanges.language = changes.defaultLanguage;
    if (changes.defaultModel !== undefined) projectChanges.model = changes.defaultModel;
    if (state.project && Object.keys(projectChanges).length) state.updateProjectSettings(projectChanges);
  }

  async function saveBeforeVoiceLearning() {
    const state = useAppStore.getState();
    if (!state.project) throw new Error("No hay un proyecto abierto.");
    await engine.save(state.project);
    state.markSaved();
    return state.project;
  }

  return <div className={`app-shell ${store.error ? "has-error" : ""}`}>
    <Toolbar project={store.project} jobState={store.progress.state} isDirty={store.isDirty} onOpen={() => openMedia()} onBrowserFile={openBrowserFile} onTranscribe={() => void transcribe()} onCancel={cancel} onExport={exportTranscript} onInsights={() => { setInsightMode(store.project?.insights?.mode ?? "general"); setShowInsights(true); }} onLive={() => void openLiveRecorder()} onVoices={() => setShowVoices(true)} onSettings={() => setShowSettings(true)} onDiagnostics={() => void openDiagnostics()} onRenameProject={renameCurrentProject} onShowProjects={() => store.setProject(null)} />
    {store.error && <div className="error-banner" role="alert"><AlertTriangle size={18} /><span>{store.error}</span><button onClick={() => store.setError(null)} aria-label="Cerrar"><X size={17} /></button></div>}
    {store.notice && !store.error && <div className="notice-banner" role="status"><Info size={18} /><span>{store.notice}</span><button onClick={() => store.setNotice(null)} aria-label="Cerrar aviso"><X size={17} /></button></div>}
    {!store.project ? <Welcome recent={store.recentProjects} onOpen={() => engine.available ? openMedia() : document.querySelector<HTMLInputElement>('input[type="file"]')?.click()} onOpenRecent={openRecent} onDeleteRecent={deleteRecent} onDropPath={openMedia} onImportFiles={queueMediaFiles} /> :
      <main className={`workspace ${transcriptFocus ? "transcript-focus" : ""}`} style={transcriptFocus ? undefined : { gridTemplateColumns: `${split}% 7px 1fr` }} onPointerMove={(event) => { if (!dragging.current) return; const rect = event.currentTarget.getBoundingClientRect(); setSplit(Math.min(72, Math.max(35, ((event.clientX - rect.left) / rect.width) * 100))); }} onPointerUp={() => { dragging.current = false; }} onPointerLeave={() => { dragging.current = false; }}>
        <div className="player-pane"><div className="media-info"><span>{store.project.mediaType === "video" ? "VÍDEO" : "AUDIO"}</span><strong>{store.project.name}</strong><small>{store.project.mediaPath}</small></div><MediaPlayer key={store.project.id} project={store.project} currentTimeMs={store.currentTimeMs} skipSeconds={store.settings.skipSeconds} onTime={store.setCurrentTime} onPlaying={store.setPlaying} onError={store.setError} seekSignal={seekSignal} /></div>
        <button className="splitter" aria-label="Redimensionar paneles" onKeyDown={(event) => { if (event.key === "ArrowLeft") setSplit((value) => Math.max(35, value - 2)); if (event.key === "ArrowRight") setSplit((value) => Math.min(72, value + 2)); }} onPointerDown={(event) => { dragging.current = true; event.currentTarget.setPointerCapture(event.pointerId); }} />
        <TranscriptPanel key={store.project.id} segments={store.project.segments} voiceProfiles={store.voiceProfiles ?? undefined} currentTimeMs={store.currentTimeMs} followPlayback={store.project.settings.followPlayback} onFollowChange={(value) => store.updateProjectSettings({ followPlayback: value })} onSeek={seek} onEdit={editSegment} onSpeakerChange={store.editSpeaker} onSpeakerReview={store.reviewSpeaker} onReplaceAll={store.replaceAll} onSplit={store.splitSegment} onMergeNext={store.mergeWithNext} onExportMediaEdit={(excludedIds) => void exportMediaEdit(excludedIds)} onUndo={store.undo} onRedo={store.redo} onGroupParagraphs={() => void groupIntoParagraphs()} canUndo={Boolean(store.history.length)} canRedo={Boolean(store.future.length)} focusMode={transcriptFocus} onFocusMode={() => setTranscriptFocus((value) => !value)} />
      </main>}
    {store.project && <StatusBar progress={store.progress} model={store.project.model} language={store.project.detectedLanguage} />}
    {showSettings && <SettingsDialog
      settings={store.settings}
      durationMs={store.project?.durationMs}
      onChange={changeSettings}
      onPrepareModels={() => {
        localStorage.removeItem("transcriptor.cuda-runtime-prompt.v1");
        setShowSettings(false);
        setShowModelSetup(true);
      }}
      onClose={() => setShowSettings(false)}
    />}
    {showVoices && <VoicesDialog settings={store.settings} project={store.project} appBusy={["analyzing", "waiting_model", "transcribing"].includes(store.progress.state)} onChange={changeSettings} onBeforeLearn={saveBeforeVoiceLearning} onClose={() => setShowVoices(false)} />}
    {showInsights && store.project && <InsightsDialog insights={store.project.insights ?? null} loading={insightsLoading} mode={insightMode} depth={insightDepth} progress={analysisProgress} analysisStartedAt={analysisStartedAt} aiStatus={localAiStatus} paragraphCount={store.project.segments.length} onModeChange={setInsightMode} onDepthChange={setInsightDepth} onAnalyze={analyzeTranscript} onCancelAnalysis={cancelAnalysis} onGroupParagraphs={groupIntoParagraphs} assistantAnswers={assistantAnswers} assistantLoading={assistantLoading} onAsk={(question) => void askTranscript(question)} onSeek={(milliseconds) => { seek(milliseconds); setShowInsights(false); }} onClose={() => setShowInsights(false)} />}
    {showLive && <LiveRecorderDialog language={store.settings.defaultLanguage} audioSource={store.settings.liveAudioSource} onAudioSourceChange={(source) => store.setSettings({ liveAudioSource: source })} onLanguageChange={(language) => store.setSettings({ defaultLanguage: language })} onComplete={(result) => void completeLiveRecording(result)} onClose={() => setShowLive(false)} />}
    {showDiagnostics && <DiagnosticsDialog project={store.project} diagnostics={diagnostics} loading={diagnosticsLoading} onRun={() => void runDiagnostics()} onRelocate={() => void relocateProjectMedia()} onUseCandidate={(path) => void relocateProjectMedia(path)} onClose={() => setShowDiagnostics(false)} />}
    {showModelSetup && <ModelSetupDialog
      onComplete={({ qualityMode, speakerAiReady, cudaReady }) => {
        store.setSettings({
          qualityMode,
          defaultModel: qualityMode === "maximum" ? "large-v3" : "turbo",
          voiceProfilesEnabled: speakerAiReady,
          diarizationMode: speakerAiReady ? "neural" : "adaptive",
        });
        if (cudaReady) {
          localStorage.removeItem("transcriptor.cuda-runtime-prompt.v1");
        } else {
          localStorage.setItem("transcriptor.cuda-runtime-prompt.v1", "dismissed");
        }
        setShowModelSetup(false);
      }}
      onLater={() => {
        sessionStorage.setItem("transcriptor.model-onboarding.postponed", "true");
        if (localStorage.getItem("transcriptor.model-onboarding.v1") === "completed") {
          localStorage.setItem("transcriptor.cuda-runtime-prompt.v1", "dismissed");
        }
        setShowModelSetup(false);
      }}
    />}
  </div>;
}

function projectSettingsFromApp(settings: AppSettings): TranscriptionProject["settings"] {
  return {
    ...DEFAULT_PROJECT_SETTINGS,
    language: settings.defaultLanguage,
    model: settings.defaultModel,
    device: settings.device,
    performanceProfile: settings.performanceProfile,
    cpuThreads: settings.cpuThreads,
    processPriority: settings.processPriority,
    qualityMode: settings.qualityMode,
    batchSize: settings.batchSize,
    reviewLowConfidence: settings.reviewLowConfidence,
    paragraphMode: settings.paragraphMode,
    maxParagraphSeconds: settings.maxParagraphSeconds,
    maxParagraphCharacters: settings.maxParagraphCharacters,
    audioEnhancement: settings.audioEnhancement,
    diarizationMode: settings.diarizationMode,
    experienceMode: settings.experienceMode,
    speakerCountMode: settings.speakerCountMode,
    speakerCount: settings.speakerCount,
    speakerSensitivity: settings.speakerSensitivity,
    voiceProfilesEnabled: settings.voiceProfilesEnabled,
    voiceProfileAutoLearn: settings.voiceProfileAutoLearn,
    voiceProfileMinConfidence: settings.voiceProfileMinConfidence,
    liveLatency: settings.liveLatency,
    subtitleLineLength: settings.subtitleLineLength,
    subtitleMaxLines: settings.subtitleMaxLines,
  };
}

function messagesToAnswers(messages: AssistantMessage[]): AssistantAnswer[] {
  const answers: AssistantAnswer[] = [];
  let question = "Pregunta anterior";
  for (const message of messages) {
    if (message.role === "user") {
      question = message.content;
      continue;
    }
    answers.unshift({
      id: message.id,
      projectId: message.projectId,
      question,
      answer: message.content,
      citations: message.citations,
      model: message.model ?? "qwen3.5:9b",
      generatedAt: message.createdAt ?? "",
    });
  }
  return answers;
}
