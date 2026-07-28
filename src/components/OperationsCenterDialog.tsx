import { useEffect, useMemo, useState } from "react";
import type { ReactNode } from "react";
import {
  Activity,
  ArchiveRestore,
  Box,
  CheckCircle2,
  ChevronDown,
  ChevronUp,
  CircleStop,
  Clock3,
  Cpu,
  Download,
  FilePlus2,
  FolderOpen,
  FolderSearch,
  Gauge,
  History,
  Layers3,
  ListChecks,
  LoaderCircle,
  Play,
  RotateCcw,
  Search,
  ShieldCheck,
  Sparkles,
  Trash2,
  X,
} from "lucide-react";
import { engine } from "../lib/engine";
import { MEDIA_FILTERS } from "../lib/media";
import { formatClock } from "../lib/time";
import type {
  EngineEvent,
  EvidenceEvent,
  GlobalSearchResult,
  ModelCatalog,
  ProjectMarker,
  QueueItem,
  QueueStatus,
  RedactionPreview,
  TranscriptVersion,
  TranscriptionProject,
} from "../types";

type OperationsTab = "queue" | "models" | "search" | "history" | "markers" | "privacy";

interface BatchImportResult {
  added: number;
  reused: number;
  failures: Array<{ path: string; message: string }>;
}

interface OperationsCenterDialogProps {
  project: TranscriptionProject | null;
  currentTimeMs: number;
  onImportFiles: (
    paths: string[],
    onProgress?: (completed: number, total: number, currentName: string) => void,
  ) => Promise<BatchImportResult>;
  onOpenProject: (projectId: string, seekMs?: number) => void;
  onProjectRestored: (project: TranscriptionProject) => void;
  onClose: () => void;
}

const EMPTY_QUEUE_STATUS: QueueStatus = {
  items: [],
  maxConcurrentJobs: 0,
  effectiveConcurrency: 1,
  recommendedConcurrency: 1,
  runningCount: 0,
  waitingCount: 0,
  completedCount: 0,
  failedCount: 0,
  availableSlots: 1,
  mode: "auto",
};

export function OperationsCenterDialog({
  project,
  currentTimeMs,
  onImportFiles,
  onOpenProject,
  onProjectRestored,
  onClose,
}: OperationsCenterDialogProps) {
  const [tab, setTab] = useState<OperationsTab>("queue");
  const [queueStatus, setQueueStatus] = useState<QueueStatus>(EMPTY_QUEUE_STATUS);
  const [catalog, setCatalog] = useState<ModelCatalog | null>(null);
  const [versions, setVersions] = useState<TranscriptVersion[]>([]);
  const [markers, setMarkers] = useState<ProjectMarker[]>([]);
  const [evidence, setEvidence] = useState<EvidenceEvent[]>([]);
  const [redactions, setRedactions] = useState<RedactionPreview | null>(null);
  const [query, setQuery] = useState("");
  const [results, setResults] = useState<GlobalSearchResult[]>([]);
  const [searchMethod, setSearchMethod] = useState("");
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState<string | null>(null);
  const [batchProgress, setBatchProgress] = useState<{
    completed: number;
    total: number;
    name: string;
  } | null>(null);
  const [modelProgress, setModelProgress] = useState<Record<string, number | null>>({});
  const [error, setError] = useState("");

  const runningItems = useMemo(
    () => queueStatus.items.filter((item) => item.state === "running"),
    [queueStatus.items],
  );
  const queuedItems = useMemo(
    () => queueStatus.items.filter((item) => item.state === "queued"),
    [queueStatus.items],
  );
  const finishedItems = useMemo(
    () => queueStatus.items.filter((item) => !["running", "queued"].includes(item.state)),
    [queueStatus.items],
  );

  useEffect(() => {
    let active = true;
    const load = async () => {
      setLoading(true);
      try {
        const [nextQueue, nextCatalog] = await Promise.all([
          engine.getQueueStatus(),
          engine.listModels(),
        ]);
        if (!active) return;
        setQueueStatus(nextQueue);
        setCatalog(nextCatalog);
        if (project) {
          const [nextVersions, nextMarkers, nextEvidence, nextRedactions] = await Promise.all([
            engine.listVersions(project.id),
            engine.listMarkers(project.id),
            engine.listEvidence(project.id),
            engine.previewRedactions(project),
          ]);
          if (!active) return;
          setVersions(nextVersions);
          setMarkers(nextMarkers);
          setEvidence(nextEvidence);
          setRedactions(nextRedactions);
        }
      } catch (reason) {
        if (active) setError(reason instanceof Error ? reason.message : String(reason));
      } finally {
        if (active) setLoading(false);
      }
    };
    void load();
    const unsubscribe = engine.subscribe((event: EngineEvent) => {
      if (event.type === "queue_updated") {
        const payload = event.payload as Partial<QueueStatus> & { items: QueueItem[] };
        setQueueStatus((current) => ({ ...current, ...payload }));
      }
      if (
        [
          "queue_item_progress",
          "job_started",
          "model_download_progress",
          "audio_extraction_progress",
          "audio_enhancement_progress",
          "transcription_progress",
        ].includes(event.type)
      ) {
        const payload = event.payload as Partial<QueueItem> & { projectId?: string };
        if (!payload.projectId) return;
        setQueueStatus((current) => ({
          ...current,
          items: current.items.map((item) => (
            item.projectId === payload.projectId
              ? { ...item, ...payload, state: "running" }
              : item
          )),
        }));
      }
      if (event.type === "model_manager_progress") {
        const payload = event.payload as { modelId: string; percent?: number | null };
        setModelProgress((current) => ({
          ...current,
          [payload.modelId]: payload.percent ?? null,
        }));
      }
      if (event.type === "model_manager_completed" || event.type === "model_manager_cancelled") {
        setBusy(null);
        void engine.listModels().then(setCatalog);
      }
      if (event.type === "model_manager_failed") {
        setBusy(null);
        setError(String((event.payload as { message?: string }).message ?? "No se pudo preparar el modelo."));
      }
      if (event.type === "queue_item_failed") {
        setError(String((event.payload as { message?: string }).message ?? "Un trabajo de la cola no pudo comenzar."));
      }
    });
    return () => {
      active = false;
      unsubscribe();
    };
  }, [project]);

  async function refreshQueue() {
    setQueueStatus(await engine.getQueueStatus());
  }

  async function enqueueCurrent() {
    if (!project) return;
    setBusy("queue-current");
    try {
      await engine.enqueue({ ...project, transcriptionStatus: "idle" });
      await refreshQueue();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : String(reason));
    } finally {
      setBusy(null);
    }
  }

  async function importBatch() {
    setBusy("queue-import");
    setError("");
    try {
      const { open } = await import("@tauri-apps/plugin-dialog");
      const selected = await open({ multiple: true, directory: false, filters: MEDIA_FILTERS });
      if (!selected) return;
      const paths = Array.isArray(selected) ? selected : [selected];
      const result = await onImportFiles(paths, (completed, total, name) => {
        setBatchProgress({ completed, total, name });
      });
      if (result.failures.length) {
        const first = result.failures[0];
        setError(
          `${result.added} añadidos; ${result.failures.length} no pudieron importarse. `
          + `${first.message}`,
        );
      }
      await refreshQueue();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : String(reason));
    } finally {
      setBatchProgress(null);
      setBusy(null);
    }
  }

  async function setConcurrency(value: number) {
    setBusy("queue-concurrency");
    try {
      setQueueStatus(await engine.setQueueConcurrency(value));
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : String(reason));
    } finally {
      setBusy(null);
    }
  }

  async function moveQueueItem(projectId: string, direction: -1 | 1) {
    const index = queuedItems.findIndex((item) => item.projectId === projectId);
    const target = index + direction;
    if (index < 0 || target < 0 || target >= queuedItems.length) return;
    const reordered = [...queuedItems];
    [reordered[index], reordered[target]] = [reordered[target], reordered[index]];
    try {
      await engine.reorderQueue(reordered.map((item) => item.projectId));
      await refreshQueue();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : String(reason));
      await refreshQueue();
    }
  }

  async function removeQueueItem(item: QueueItem) {
    try {
      if (item.state === "running") await engine.cancel(item.projectId);
      else await engine.removeFromQueue(item.projectId);
      await refreshQueue();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : String(reason));
    }
  }

  async function retryQueueItem(item: QueueItem) {
    setBusy(item.projectId);
    try {
      const queuedProject = await engine.loadProject(item.projectId);
      await engine.enqueue({ ...queuedProject, transcriptionStatus: "idle" });
      await refreshQueue();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : String(reason));
    } finally {
      setBusy(null);
    }
  }

  async function clearFinished() {
    setBusy("queue-clear");
    try {
      for (const item of finishedItems) await engine.removeFromQueue(item.projectId);
      await refreshQueue();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : String(reason));
    } finally {
      setBusy(null);
    }
  }

  async function runSearch() {
    if (query.trim().length < 2) return;
    setBusy("search");
    try {
      const response = await engine.semanticSearch(query);
      setResults(response.results);
      setSearchMethod(response.method);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : String(reason));
    } finally {
      setBusy(null);
    }
  }

  async function addMarker(kind: string, label: string) {
    if (!project) return;
    try {
      await engine.addMarker(project.id, currentTimeMs, kind, label);
      setMarkers(await engine.listMarkers(project.id));
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : String(reason));
    }
  }

  async function restore(version: TranscriptVersion) {
    if (!project || !window.confirm("Se guardará la versión actual y se restaurará la seleccionada. ¿Continuar?")) return;
    setBusy(version.id);
    try {
      const restored = await engine.restoreVersion(project.id, version.id);
      onProjectRestored(restored);
      setVersions(await engine.listVersions(project.id));
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : String(reason));
    } finally {
      setBusy(null);
    }
  }

  async function downloadModel(modelId: string) {
    setBusy(modelId);
    setModelProgress((current) => ({ ...current, [modelId]: null }));
    try {
      await engine.downloadModel(modelId);
    } catch (reason) {
      setBusy(null);
      setError(reason instanceof Error ? reason.message : String(reason));
    }
  }

  async function removeModel(modelId: string, name: string) {
    if (!window.confirm(`Se eliminará ${name} del equipo. Podrás descargarlo de nuevo. ¿Continuar?`)) return;
    setBusy(modelId);
    try {
      await engine.deleteModel(modelId);
      setCatalog(await engine.listModels());
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : String(reason));
    } finally {
      setBusy(null);
    }
  }

  return (
    <div
      className="modal-backdrop"
      role="presentation"
      onMouseDown={(event) => {
        if (event.target === event.currentTarget) onClose();
      }}
    >
      <section className="operations-dialog" role="dialog" aria-modal="true" aria-labelledby="operations-title">
        <header>
          <div>
            <span>CENTRO DE PRODUCCIÓN</span>
            <h2 id="operations-title"><Layers3 size={21} /> Transcripciones en marcha</h2>
            <p>Importa lotes, controla cada motor y continúa trabajando mientras procesa.</p>
          </div>
          <button className="icon-button" onClick={onClose} aria-label="Cerrar"><X size={19} /></button>
        </header>
        <nav className="operations-tabs" aria-label="Herramientas">
          <button className={tab === "queue" ? "active" : ""} onClick={() => setTab("queue")}><ListChecks size={15} /> Producción</button>
          <button className={tab === "models" ? "active" : ""} onClick={() => setTab("models")}><Box size={15} /> Modelos</button>
          <button className={tab === "search" ? "active" : ""} onClick={() => setTab("search")}><Search size={15} /> Buscar</button>
          <button className={tab === "history" ? "active" : ""} onClick={() => setTab("history")}><History size={15} /> Versiones</button>
          <button className={tab === "markers" ? "active" : ""} onClick={() => setTab("markers")}><Sparkles size={15} /> Marcadores</button>
          <button className={tab === "privacy" ? "active" : ""} onClick={() => setTab("privacy")}><ShieldCheck size={15} /> Privacidad</button>
        </nav>
        {error && <div className="operations-error" role="alert">{error}<button onClick={() => setError("")} aria-label="Cerrar error"><X size={14} /></button></div>}
        <div className="operations-content">
          {loading && <div className="operations-empty"><LoaderCircle className="spin" size={28} /><strong>Preparando el centro…</strong></div>}

          {!loading && tab === "queue" && (
            <section className="operations-section queue-dashboard">
              <div className="queue-overview">
                <QueueMetric icon={<Activity />} value={queueStatus.runningCount} label="Procesando" tone="active" />
                <QueueMetric icon={<Clock3 />} value={queueStatus.waitingCount} label="En espera" />
                <QueueMetric icon={<CheckCircle2 />} value={queueStatus.completedCount} label="Terminadas" />
                <QueueMetric icon={<Cpu />} value={`${queueStatus.effectiveConcurrency}×`} label="Motores activos" />
              </div>

              <div className="queue-command-card">
                <div className="queue-command-copy">
                  <span><Gauge size={16} /> PLANIFICADOR LOCAL</span>
                  <strong>
                    {queueStatus.mode === "auto"
                      ? `Automático: hasta ${queueStatus.effectiveConcurrency} transcripciones simultáneas`
                      : `${queueStatus.effectiveConcurrency} transcripciones simultáneas`}
                  </strong>
                  <p>
                    {queueStatus.mode === "auto"
                      ? "Ajustado a la GPU, RAM y CPU disponibles. Si falta memoria, los siguientes archivos permanecen seguros en espera."
                      : "Límite manual. Usa Automático para que Transcriptor proteja la memoria y la VRAM."}
                  </p>
                </div>
                <label className="queue-concurrency">
                  <span>Trabajos a la vez</span>
                  <select
                    value={queueStatus.maxConcurrentJobs}
                    disabled={busy === "queue-concurrency"}
                    onChange={(event) => void setConcurrency(Number(event.target.value))}
                  >
                    <option value={0}>Automático ({queueStatus.recommendedConcurrency})</option>
                    <option value={1}>1 trabajo</option>
                    <option value={2}>2 trabajos</option>
                    <option value={3}>3 trabajos</option>
                  </select>
                </label>
                <div className="queue-primary-actions">
                  <button className="button primary" disabled={busy === "queue-import"} onClick={() => void importBatch()}>
                    {busy === "queue-import" ? <LoaderCircle className="spin" size={15} /> : <FilePlus2 size={15} />}
                    Añadir archivos
                  </button>
                  <button className="button secondary" disabled={!project || busy === "queue-current"} onClick={() => void enqueueCurrent()}>
                    <ListChecks size={15} /> Proyecto abierto
                  </button>
                </div>
              </div>

              {batchProgress && (
                <div className="batch-import-progress" role="status">
                  <LoaderCircle className="spin" size={16} />
                  <div>
                    <strong>Preparando {batchProgress.completed + 1} de {batchProgress.total}</strong>
                    <span>{batchProgress.name}</span>
                  </div>
                  <progress max={batchProgress.total} value={batchProgress.completed} />
                </div>
              )}

              <div className="queue-lane-heading">
                <div><span className="live-dot" /> <strong>En ejecución</strong><small>{runningItems.length} de {queueStatus.effectiveConcurrency} motores ocupados</small></div>
              </div>
              <div className="queue-active-grid">
                {runningItems.length
                  ? runningItems.map((item) => (
                    <QueueCard
                      key={item.id}
                      item={item}
                      onOpen={() => onOpenProject(item.projectId)}
                      onRemove={() => void removeQueueItem(item)}
                    />
                  ))
                  : <div className="queue-idle-state"><Play size={18} /><span><strong>Motores preparados</strong><small>Añade dos o más archivos y comenzarán en paralelo.</small></span></div>}
              </div>

              <div className="queue-lane-heading">
                <div><strong>Siguientes trabajos</strong><small>{queuedItems.length ? `${queuedItems.length} esperando turno` : "Sin archivos pendientes"}</small></div>
              </div>
              <div className="queue-list">
                {queuedItems.map((item, index) => (
                  <QueueCard
                    key={item.id}
                    item={item}
                    order={index + 1}
                    canMoveUp={index > 0}
                    canMoveDown={index < queuedItems.length - 1}
                    onMove={(direction) => void moveQueueItem(item.projectId, direction)}
                    onOpen={() => onOpenProject(item.projectId)}
                    onRemove={() => void removeQueueItem(item)}
                  />
                ))}
                {!queuedItems.length && !runningItems.length && (
                  <Empty icon={<FilePlus2 />} title="Arrastra tu carga de trabajo aquí" detail="Selecciona varios audios o vídeos; Transcriptor los analizará, ordenará y procesará sin bloquear la interfaz." action={<button className="button primary" onClick={() => void importBatch()}><FolderOpen size={15} /> Seleccionar archivos</button>} />
                )}
              </div>

              {!!finishedItems.length && (
                <>
                  <div className="queue-lane-heading queue-history-heading">
                    <div><strong>Actividad reciente</strong><small>{finishedItems.length} trabajos conservados</small></div>
                    <button className="button ghost" disabled={busy === "queue-clear"} onClick={() => void clearFinished()}><Trash2 size={13} /> Limpiar lista</button>
                  </div>
                  <div className="queue-history-list">
                    {finishedItems.map((item) => (
                      <QueueCard
                        key={item.id}
                        item={item}
                        busy={busy === item.projectId}
                        onOpen={() => onOpenProject(item.projectId)}
                        onRetry={() => void retryQueueItem(item)}
                        onRemove={() => void removeQueueItem(item)}
                      />
                    ))}
                  </div>
                </>
              )}
            </section>
          )}

          {!loading && tab === "models" && <section className="operations-section"><div className="section-lead"><div><strong>Modelos de reconocimiento</strong><p>{catalog ? `${(catalog.freeBytes / 1024 ** 3).toFixed(1)} GB libres · ${catalog.root}` : "Leyendo modelos…"}</p></div></div><div className="model-list">{catalog?.models.map((model) => <article key={model.id} className={model.installed ? "installed" : ""}><div className="model-icon"><Box size={20} /></div><div><strong>{model.name}<em>{model.installed ? "Instalado" : `${model.sizeGiB} GB`}</em></strong><p>{model.description}</p><small>{model.speed} · precisión {model.accuracy.toLowerCase()} · RAM recomendada {model.memoryGiB} GB</small>{busy === model.id && <progress max={100} value={modelProgress[model.id] ?? undefined} />}</div><div>{model.installed ? <button className="icon-button danger-icon" disabled={busy === model.id} onClick={() => void removeModel(model.id, model.name)} aria-label={`Eliminar ${model.name}`}><Trash2 size={16} /></button> : <button className="button secondary" disabled={busy !== null} onClick={() => void downloadModel(model.id)}><Download size={15} /> Descargar</button>}</div></article>)}</div></section>}
          {!loading && tab === "search" && <section className="operations-section"><form className="global-search" onSubmit={(event) => { event.preventDefault(); void runSearch(); }}><Search size={17} /><input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Buscar una idea en todos los proyectos…" aria-label="Búsqueda global semántica" /><button className="button primary" disabled={query.trim().length < 2 || busy === "search"}>{busy === "search" ? <LoaderCircle className="spin" size={14} /> : <Sparkles size={14} />} Buscar con IA</button></form>{searchMethod && <p className="search-method">{searchMethod === "lexical" ? "Búsqueda textual local" : "Qwen amplió el concepto localmente"} · {results.length} resultados</p>}<div className="global-results">{results.map((result) => <button key={`${result.projectId}-${result.segmentId}`} onClick={() => onOpenProject(result.projectId, result.startMs)}><time>{formatClock(result.startMs)}</time><span><strong>{result.projectName}</strong><p>{result.text}</p></span></button>)}{query && !results.length && busy !== "search" && <Empty icon={<FolderSearch />} title="Sin coincidencias" detail="Prueba con menos palabras o términos diferentes." />}</div></section>}
          {!loading && tab === "history" && <section className="operations-section"><div className="section-lead"><div><strong>Versiones y evidencia</strong><p>Cada retranscripción conserva el texto anterior.</p></div></div>{project ? <div className="version-layout"><div className="version-list">{versions.length ? versions.map((version) => <article key={version.id}><History size={17} /><div><strong>{new Date(version.createdAt).toLocaleString("es-ES")}</strong><small>{version.model} · {version.segmentCount} segmentos</small></div><button className="button secondary" disabled={busy === version.id} onClick={() => void restore(version)}><ArchiveRestore size={14} /> Restaurar</button></article>) : <Empty icon={<History />} title="Todavía no hay versiones" detail="Aparecerán al retranscribir o restaurar." />}</div><div className="evidence-list"><strong>Actividad verificable</strong>{evidence.map((event) => <article key={event.id}><ShieldCheck size={14} /><span>{event.eventType.replaceAll("_", " ")}<small>{new Date(event.createdAt).toLocaleString("es-ES")}</small></span></article>)}</div></div> : <Empty icon={<History />} title="Abre un proyecto" detail="El historial pertenece a cada transcripción." />}</section>}
          {!loading && tab === "markers" && <section className="operations-section"><div className="section-lead"><div><strong>Marcadores del proyecto</strong><p>Se guardan en el instante actual del reproductor: {formatClock(currentTimeMs)}.</p></div></div>{project ? <><div className="marker-actions">{[["important", "Importante"], ["task", "Tarea"], ["question", "Pregunta"], ["review", "Revisar"]].map(([kind, label]) => <button className="button secondary" key={kind} onClick={() => void addMarker(kind, label)}>{label}</button>)}</div><div className="marker-list">{markers.map((marker) => <button key={marker.id} onClick={() => onOpenProject(marker.projectId, marker.timeMs)}><Clock3 size={14} /><time>{formatClock(marker.timeMs)}</time><span>{marker.label}</span></button>)}</div></> : <Empty icon={<Sparkles />} title="Abre un proyecto" detail="Después podrás marcar cualquier instante." />}</section>}
          {!loading && tab === "privacy" && <section className="operations-section"><div className="section-lead"><div><strong>Detector de datos sensibles</strong><p>Reconoce correos, teléfonos, documentos, tarjetas e IP sin mostrar ni enviar el dato completo.</p></div></div>{project && redactions ? <><div className="privacy-summary"><ShieldCheck size={22} /><div><strong>{redactions.total ? `${redactions.total} dato${redactions.total === 1 ? "" : "s"} para proteger` : "No se detectaron datos sensibles"}</strong><p>Usa «TXT seguro» o «PDF seguro» en Exportar para sustituirlos automáticamente.</p></div></div><div className="redaction-list">{redactions.findings.map((finding, index) => <button key={`${finding.segmentId}-${finding.kind}-${index}`} onClick={() => onOpenProject(project.id, finding.startMs)}><time>{formatClock(finding.startMs)}</time><span><strong>{redactionLabel(finding.kind)}</strong><small>{finding.preview}</small></span></button>)}</div></> : <Empty icon={<ShieldCheck />} title="Abre un proyecto" detail="La comprobación se realiza únicamente sobre el texto local." />}</section>}
        </div>
        <footer><span><ShieldCheck size={13} /> Cola persistente · archivos siempre locales</span><button className="button primary" onClick={onClose}><CheckCircle2 size={15} /> Listo</button></footer>
      </section>
    </div>
  );
}

function QueueMetric({ icon, value, label, tone }: { icon: ReactNode; value: ReactNode; label: string; tone?: "active" }) {
  return <article className={tone ? `queue-metric ${tone}` : "queue-metric"}><span>{icon}</span><div><strong>{value}</strong><small>{label}</small></div></article>;
}

function QueueCard({
  item,
  order,
  canMoveUp,
  canMoveDown,
  busy,
  onMove,
  onOpen,
  onRetry,
  onRemove,
}: {
  item: QueueItem;
  order?: number;
  canMoveUp?: boolean;
  canMoveDown?: boolean;
  busy?: boolean;
  onMove?: (direction: -1 | 1) => void;
  onOpen: () => void;
  onRetry?: () => void;
  onRemove: () => void;
}) {
  const percent = item.state === "completed" ? 100 : Math.max(0, Math.min(100, item.percent ?? 0));
  const stateLabel = {
    queued: "En espera",
    running: item.phase || "Transcribiendo",
    completed: "Completada",
    failed: "Con error",
    cancelled: "Cancelada",
  }[item.state];
  return (
    <article className={`queue-job-card ${item.state}`}>
      <span className="queue-position">
        {item.state === "running" ? <LoaderCircle className="spin" size={16} /> : item.state === "completed" ? <CheckCircle2 size={16} /> : order ?? <Clock3 size={15} />}
      </span>
      <div className="queue-job-main">
        <div className="queue-job-title">
          <strong>{item.name}</strong>
          <span className={`queue-state ${item.state}`}>{stateLabel}</span>
        </div>
        <div className="queue-job-meta">
          <span>{item.mediaType === "video" ? "Vídeo" : "Audio"} · {formatClock(item.durationMs)}</span>
          {item.activeModel && <span>{item.activeModel}</span>}
          {item.device && <span>{item.device.toUpperCase()}</span>}
          {item.speedX != null && <span>{item.speedX.toFixed(1)}×</span>}
          {item.etaMs != null && item.state === "running" && <span>Quedan {formatEta(item.etaMs)}</span>}
        </div>
        {item.state === "running" && (
          <div className="queue-job-progress">
            <progress max={100} value={percent} />
            <span>{percent.toFixed(0)} %</span>
          </div>
        )}
        <small className="queue-job-message">
          {item.state === "queued"
            ? `Turno ${order ?? item.position} · comenzará en cuanto haya un motor libre`
            : item.errorMessage || item.message || stateLabel}
        </small>
      </div>
      {onMove && <span className="queue-reorder"><button className="icon-button" disabled={!canMoveUp} onClick={() => onMove(-1)} aria-label={`Subir ${item.name}`}><ChevronUp size={14} /></button><button className="icon-button" disabled={!canMoveDown} onClick={() => onMove(1)} aria-label={`Bajar ${item.name}`}><ChevronDown size={14} /></button></span>}
      <div className="queue-job-actions">
        <button className="icon-button" onClick={onOpen} aria-label={`Abrir ${item.name}`} title="Abrir proyecto"><FolderOpen size={15} /></button>
        {onRetry && <button className="icon-button" disabled={busy} onClick={onRetry} aria-label={`Reintentar ${item.name}`} title="Reintentar"><RotateCcw className={busy ? "spin" : ""} size={15} /></button>}
        <button className={`icon-button ${item.state === "running" ? "danger-icon" : ""}`} onClick={onRemove} aria-label={item.state === "running" ? `Cancelar ${item.name}` : `Retirar ${item.name}`} title={item.state === "running" ? "Cancelar" : "Retirar"}>{item.state === "running" ? <CircleStop size={15} /> : <X size={15} />}</button>
      </div>
    </article>
  );
}

function Empty({ icon, title, detail, action }: { icon: ReactNode; title: string; detail: string; action?: ReactNode }) {
  return <div className="operations-empty"><span>{icon}</span><strong>{title}</strong><p>{detail}</p>{action && <div className="operations-empty-action">{action}</div>}</div>;
}

function formatEta(milliseconds: number): string {
  if (milliseconds < 60_000) return `${Math.max(1, Math.ceil(milliseconds / 1000))} s`;
  const minutes = Math.ceil(milliseconds / 60_000);
  return minutes < 60 ? `${minutes} min` : `${Math.floor(minutes / 60)} h ${minutes % 60} min`;
}

function redactionLabel(kind: string): string {
  return ({ email: "Correo electrónico", phone: "Teléfono", dni: "Documento", card: "Tarjeta", ip: "Dirección IP" } as Record<string, string>)[kind] ?? kind;
}
