import { useEffect, useMemo, useState } from "react";
import {
  CircleStop,
  Clock3,
  FilePlus2,
  FolderOpen,
  Layers3,
  LoaderCircle,
  X,
} from "lucide-react";
import { engine } from "../lib/engine";
import { MEDIA_FILTERS } from "../lib/media";
import { formatClock } from "../lib/time";
import type { EngineEvent, QueueItem, QueueStatus } from "../types";

interface BatchImportResult {
  added: number;
  reused: number;
  failures: Array<{ path: string; message: string }>;
}

interface WorkQueuePanelProps {
  onImportFiles: (
    paths: string[],
    onProgress?: (completed: number, total: number, currentName: string) => void,
  ) => Promise<BatchImportResult>;
  onOpenProject: (projectId: string) => void;
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

const PROGRESS_EVENTS = new Set([
  "queue_item_progress",
  "job_started",
  "model_download_progress",
  "audio_extraction_progress",
  "audio_enhancement_progress",
  "transcription_progress",
]);

export function WorkQueuePanel({ onImportFiles, onOpenProject }: WorkQueuePanelProps) {
  const [status, setStatus] = useState<QueueStatus>(EMPTY_QUEUE_STATUS);
  const [loading, setLoading] = useState(engine.available);
  const [busyProjectId, setBusyProjectId] = useState<string | null>(null);
  const [importProgress, setImportProgress] = useState<{ completed: number; total: number; name: string } | null>(null);
  const [error, setError] = useState("");
  const visibleItems = useMemo(
    () => status.items
      .filter((item) => item.state === "running" || item.state === "queued")
      .sort((left, right) => {
        if (left.state !== right.state) return left.state === "running" ? -1 : 1;
        return left.position - right.position;
      }),
    [status.items],
  );
  const hasWork = visibleItems.length > 0;

  useEffect(() => {
    if (!engine.available) return;
    let active = true;
    const refresh = async () => {
      try {
        const next = await engine.getQueueStatus();
        if (active) setStatus(next);
      } catch (reason) {
        if (active) setError(reason instanceof Error ? reason.message : String(reason));
      } finally {
        if (active) setLoading(false);
      }
    };
    void refresh();
    const unsubscribe = engine.subscribe((event: EngineEvent) => {
      if (event.type === "queue_updated") {
        const payload = event.payload as Partial<QueueStatus> & { items?: QueueItem[] };
        setStatus((current) => ({ ...current, ...payload, items: payload.items ?? current.items }));
        return;
      }
      if (PROGRESS_EVENTS.has(event.type)) {
        const payload = event.payload as Partial<QueueItem> & { projectId?: string };
        if (!payload.projectId) return;
        setStatus((current) => ({
          ...current,
          items: current.items.map((item) => item.projectId === payload.projectId
            ? { ...item, ...payload, state: "running" }
            : item),
        }));
      }
      if (["job_completed", "job_failed", "job_cancelled", "queue_item_failed"].includes(event.type)) {
        void refresh();
      }
    });
    return () => {
      active = false;
      unsubscribe();
    };
  }, []);

  async function importBatch() {
    if (!engine.available) return;
    setError("");
    try {
      const { open } = await import("@tauri-apps/plugin-dialog");
      const selected = await open({ multiple: true, directory: false, filters: MEDIA_FILTERS });
      if (!selected) return;
      const paths = Array.isArray(selected) ? selected : [selected];
      const result = await onImportFiles(paths, (completed, total, name) => {
        setImportProgress({ completed, total, name });
      });
      if (result.failures.length) {
        setError(`${result.added} añadidos; ${result.failures.length} no pudieron importarse. ${result.failures[0].message}`);
      }
      setStatus(await engine.getQueueStatus());
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : String(reason));
    } finally {
      setImportProgress(null);
    }
  }

  async function remove(item: QueueItem) {
    setBusyProjectId(item.projectId);
    setError("");
    try {
      if (item.state === "running") await engine.cancel(item.projectId);
      else await engine.removeFromQueue(item.projectId);
      setStatus(await engine.getQueueStatus());
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : String(reason));
    } finally {
      setBusyProjectId(null);
    }
  }

  return (
    <section className={`work-queue-panel ${hasWork ? "has-work" : "is-idle"}`} aria-labelledby="work-queue-title">
      <header>
        <span className="work-queue-heading">
          <i className={status.runningCount ? "active" : ""}><Layers3 size={17} /></i>
          <span>
            <strong id="work-queue-title">Trabajo en curso</strong>
            <small>
              {hasWork
                ? `${status.runningCount} procesando · ${status.waitingCount} en espera · ${status.effectiveConcurrency} en paralelo`
                : "No hay tareas activas"}
            </small>
          </span>
        </span>
        <button className="button queue-add-button" disabled={!engine.available || Boolean(importProgress)} onClick={() => void importBatch()}>
          {importProgress ? <LoaderCircle className="spin" size={14} /> : <FilePlus2 size={14} />}
          <span>{importProgress ? `${importProgress.completed}/${importProgress.total}` : "Añadir lote"}</span>
        </button>
      </header>

      {error && <div className="work-queue-error" role="alert"><span>{error}</span><button onClick={() => setError("")} aria-label="Cerrar error"><X size={13} /></button></div>}

      {loading ? (
        <div className="work-queue-empty"><LoaderCircle className="spin" size={18} /><span><strong>Leyendo los trabajos…</strong><small>Recuperando la cola local</small></span></div>
      ) : hasWork ? (
        <div className="work-queue-list">
          {visibleItems.slice(0, 4).map((item) => (
            <QueueRow
              key={item.id}
              item={item}
              busy={busyProjectId === item.projectId}
              onOpen={() => onOpenProject(item.projectId)}
              onRemove={() => void remove(item)}
            />
          ))}
          {visibleItems.length > 4 && <small className="work-queue-overflow">+ {visibleItems.length - 4} trabajos más esperando su turno</small>}
        </div>
      ) : (
        <div className="work-queue-empty">
          <span className="queue-ready-icon"><Layers3 size={18} /></span>
          <span><strong>Motores preparados</strong><small>Añade varios archivos y se repartirán automáticamente entre CPU y GPU.</small></span>
        </div>
      )}
      {importProgress && <div className="work-queue-import"><span>Preparando {importProgress.name}</span><progress max={importProgress.total} value={importProgress.completed} /></div>}
    </section>
  );
}

function QueueRow({ item, busy, onOpen, onRemove }: { item: QueueItem; busy: boolean; onOpen: () => void; onRemove: () => void }) {
  const percent = Math.max(0, Math.min(100, item.percent ?? 0));
  const running = item.state === "running";
  return (
    <article className={`work-queue-row ${item.state}`}>
      <span className="work-queue-state">
        {running ? <LoaderCircle className="spin" size={15} /> : <Clock3 size={14} />}
      </span>
      <div className="work-queue-copy">
        <div><strong>{item.name}</strong><em>{running ? item.phase || "Procesando" : `Turno ${item.position}`}</em></div>
        <small>
          {running
            ? [item.activeModel, item.device?.toUpperCase(), item.speedX != null ? `${item.speedX.toFixed(1)}×` : null, item.etaMs != null ? `quedan ${formatEta(item.etaMs)}` : null].filter(Boolean).join(" · ")
            : `${item.mediaType === "video" ? "Vídeo" : "Audio"} · ${formatClock(item.durationMs)} · en espera`}
        </small>
        {running && <div className="work-queue-progress"><progress max={100} value={percent} /><output>{percent.toFixed(0)} %</output></div>}
      </div>
      <div className="work-queue-actions">
        <button className="icon-button" onClick={onOpen} aria-label={`Abrir ${item.name}`} title="Abrir proyecto"><FolderOpen size={14} /></button>
        <button className="icon-button danger-icon" disabled={busy} onClick={onRemove} aria-label={running ? `Cancelar ${item.name}` : `Retirar ${item.name}`} title={running ? "Cancelar" : "Retirar"}>
          {busy ? <LoaderCircle className="spin" size={14} /> : running ? <CircleStop size={14} /> : <X size={14} />}
        </button>
      </div>
    </article>
  );
}

function formatEta(milliseconds: number): string {
  if (milliseconds < 60_000) return `${Math.max(1, Math.ceil(milliseconds / 1000))} s`;
  const minutes = Math.ceil(milliseconds / 60_000);
  return minutes < 60 ? `${minutes} min` : `${Math.floor(minutes / 60)} h ${minutes % 60} min`;
}
