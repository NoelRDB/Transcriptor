import { useEffect, useState } from "react";
import {
  Box,
  CheckCircle2,
  Download,
  HardDrive,
  LoaderCircle,
  ShieldCheck,
  Trash2,
  X,
} from "lucide-react";
import { engine } from "../lib/engine";
import type { EngineEvent, ModelCatalog, QueueStatus } from "../types";

export function LocalModelsSection() {
  const [catalog, setCatalog] = useState<ModelCatalog | null>(null);
  const [queueStatus, setQueueStatus] = useState<QueueStatus | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [progress, setProgress] = useState<Record<string, number | null>>({});
  const [error, setError] = useState("");

  useEffect(() => {
    if (!engine.available) return;
    let active = true;
    Promise.all([engine.listModels(), engine.getQueueStatus()])
      .then(([nextCatalog, nextQueue]) => {
        if (!active) return;
        setCatalog(nextCatalog);
        setQueueStatus(nextQueue);
      })
      .catch((reason) => {
        if (active) setError(reason instanceof Error ? reason.message : String(reason));
      });
    const unsubscribe = engine.subscribe((event: EngineEvent) => {
      if (event.type === "model_manager_progress") {
        const payload = event.payload as { modelId: string; percent?: number | null };
        setProgress((current) => ({ ...current, [payload.modelId]: payload.percent ?? null }));
      }
      if (event.type === "model_manager_completed" || event.type === "model_manager_cancelled") {
        setBusy(null);
        void engine.listModels().then(setCatalog);
      }
      if (event.type === "model_manager_failed") {
        setBusy(null);
        setError(String((event.payload as { message?: string }).message ?? "No se pudo preparar el modelo."));
      }
      if (event.type === "queue_updated") setQueueStatus(event.payload as QueueStatus);
    });
    return () => {
      active = false;
      unsubscribe();
    };
  }, []);

  async function downloadModel(modelId: string, name: string, sizeGiB: number) {
    if (!window.confirm(`${name} ocupa aproximadamente ${sizeGiB} GB. Se descargará sólo con tu permiso y quedará en este equipo. ¿Continuar?`)) return;
    setBusy(modelId);
    setError("");
    setProgress((current) => ({ ...current, [modelId]: null }));
    try {
      await engine.downloadModel(modelId);
    } catch (reason) {
      setBusy(null);
      setError(reason instanceof Error ? reason.message : String(reason));
    }
  }

  async function removeModel(modelId: string, name: string) {
    if (!window.confirm(`Se eliminará ${name} de este equipo. Podrás descargarlo de nuevo cuando lo necesites. ¿Continuar?`)) return;
    setBusy(modelId);
    setError("");
    try {
      await engine.deleteModel(modelId);
      setCatalog(await engine.listModels());
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : String(reason));
    } finally {
      setBusy(null);
    }
  }

  async function changeConcurrency(maxConcurrentJobs: number) {
    setError("");
    try {
      setQueueStatus(await engine.setQueueConcurrency(maxConcurrentJobs));
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : String(reason));
    }
  }

  const installed = catalog?.models.filter((model) => model.installed).length ?? 0;
  return (
    <section className="local-models-section" aria-labelledby="local-models-title">
      <div className="section-heading">
        <div><span>MODELOS LOCALES</span><strong id="local-models-title">Reconocimiento de voz</strong></div>
        <output>{catalog ? `${installed} instalados` : "Comprobando…"}</output>
      </div>
      <div className="models-summary">
        <span><HardDrive size={17} /></span>
        <div>
          <strong>Descargas bajo tu control</strong>
          <p>{catalog ? `${formatGiB(catalog.freeBytes)} libres · ${catalog.root}` : "Leyendo el almacenamiento de modelos…"}</p>
        </div>
        {queueStatus && <label>
          <span>Trabajos simultáneos</span>
          <select value={queueStatus.maxConcurrentJobs} onChange={(event) => void changeConcurrency(Number(event.target.value))}>
            <option value={0}>Automático ({queueStatus.recommendedConcurrency})</option>
            <option value={1}>1 trabajo</option>
            <option value={2}>2 trabajos</option>
            <option value={3}>3 trabajos</option>
          </select>
        </label>}
      </div>
      {error && <div className="models-settings-error" role="alert"><span>{error}</span><button onClick={() => setError("")} aria-label="Cerrar error"><X size={13} /></button></div>}
      <div className="settings-model-grid">
        {catalog?.models.map((model) => {
          const downloading = busy === model.id && !model.installed;
          const modelProgress = progress[model.id];
          const partial = model.integrity === "partial";
          const canInstall = model.canInstall !== false;
          return (
            <article key={model.id} className={model.installed ? "installed" : ""}>
              <span className="settings-model-icon"><Box size={19} /></span>
              <div className="settings-model-copy">
                <div><strong>{model.name}</strong><em>{model.installed ? <><CheckCircle2 size={11} /> Instalado</> : partial ? "Descarga incompleta" : `${model.sizeGiB} GB`}</em></div>
                <p>{model.description}</p>
                <small>{model.speed} · precisión {model.accuracy.toLowerCase()} · RAM recomendada {model.memoryGiB} GB</small>
                {!model.installed && !canInstall ? <small className="model-space-warning">No hay espacio libre suficiente para completar este modelo.</small> : null}
                {downloading && <div className="settings-model-progress"><progress max={100} value={modelProgress ?? undefined} /><span>{modelProgress == null ? "Preparando…" : `${modelProgress.toFixed(0)} %`}</span></div>}
              </div>
              <div className="settings-model-action">
                {downloading ? (
                  <button className="button secondary" disabled><LoaderCircle className="spin" size={14} /> Descargando…</button>
                ) : model.installed ? (
                  <button className="icon-button danger-icon" disabled={busy === model.id} onClick={() => void removeModel(model.id, model.name)} aria-label={`Eliminar ${model.name}`} title="Eliminar modelo">
                    {busy === model.id ? <LoaderCircle className="spin" size={15} /> : <Trash2 size={15} />}
                  </button>
                ) : (
                  <button className="button secondary" disabled={busy !== null || !engine.available || !canInstall} onClick={() => void downloadModel(model.id, model.name, model.sizeGiB)}><Download size={14} /> {partial ? "Completar" : canInstall ? "Descargar" : "Sin espacio"}</button>
                )}
              </div>
            </article>
          );
        })}
      </div>
      <p className="models-privacy"><ShieldCheck size={13} /> Los modelos se ejecutan sin conexión. Nunca se descarga un modelo grande sin confirmación.</p>
    </section>
  );
}

function formatGiB(bytes: number): string {
  return `${(bytes / 1024 ** 3).toFixed(1)} GB`;
}
