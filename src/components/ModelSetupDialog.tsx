import { useEffect, useMemo, useState } from "react";
import {
  BrainCircuit,
  Check,
  CheckCircle2,
  Cpu,
  Download,
  HardDrive,
  LoaderCircle,
  LockKeyhole,
  Mic2,
  ShieldCheck,
  Sparkles,
} from "lucide-react";
import { engine } from "../lib/engine";
import {
  buildRecommendedModelSetup,
  type RecommendedModelSetup,
} from "../lib/modelSetup";
import type {
  EngineEvent,
  HardwareInfo,
  ModelCatalog,
  QualityMode,
  SpeakerAiStatus,
} from "../types";

interface ModelSetupDialogProps {
  onComplete: (result: {
    qualityMode: QualityMode;
    speakerAiReady: boolean;
  }) => void;
  onLater: () => void;
}

type SetupState = "checking" | "ready" | "installing" | "completed" | "failed";

interface ActiveDownload {
  id: string;
  name: string;
  kind: "transcription" | "speakers";
  position: number;
  total: number;
}

export function ModelSetupDialog({ onComplete, onLater }: ModelSetupDialogProps) {
  const [catalog, setCatalog] = useState<ModelCatalog | null>(null);
  const [hardware, setHardware] = useState<HardwareInfo | null>(null);
  const [speakerAi, setSpeakerAi] = useState<SpeakerAiStatus | null>(null);
  const [state, setState] = useState<SetupState>("checking");
  const [consent, setConsent] = useState(false);
  const [activeDownload, setActiveDownload] = useState<ActiveDownload | null>(null);
  const [progress, setProgress] = useState<number | null>(null);
  const [progressMessage, setProgressMessage] = useState("");
  const [error, setError] = useState("");
  const [cancelling, setCancelling] = useState(false);

  const plan = useMemo(
    () => catalog
      ? buildRecommendedModelSetup(catalog, hardware, Boolean(speakerAi?.ready))
      : null,
    [catalog, hardware, speakerAi?.ready],
  );

  useEffect(() => {
    let active = true;
    Promise.all([
      engine.listModels(),
      engine.getHardwareInfo().catch(() => null),
      engine.getSpeakerAiStatus(),
    ])
      .then(([nextCatalog, nextHardware, nextSpeakerAi]) => {
        if (!active) return;
        setCatalog(nextCatalog);
        setHardware(nextHardware);
        setSpeakerAi(nextSpeakerAi);
        setState("ready");
      })
      .catch((reason) => {
        if (!active) return;
        setError(reason instanceof Error ? reason.message : String(reason));
        setState("failed");
      });
    return () => { active = false; };
  }, []);

  async function prepareComputer() {
    if (!plan || !plan.canInstall || !consent) return;
    setState("installing");
    setError("");
    setCancelling(false);
    const missingModels = plan.models.filter((model) => !model.installed);
    const totalSteps = missingModels.length + (plan.includesSpeakerAi ? 1 : 0);
    let position = 0;
    try {
      for (const model of missingModels) {
        position += 1;
        setActiveDownload({
          id: model.id,
          name: model.name,
          kind: "transcription",
          position,
          total: totalSteps,
        });
        setProgress(null);
        setProgressMessage(`Conectando con el repositorio oficial de ${model.name}…`);
        await waitForModel(model.id, () => engine.downloadModel(model.id), (event) => {
          const payload = event.payload as { percent?: number | null; message?: string };
          setProgress(payload.percent ?? null);
          setProgressMessage(payload.message ?? `Descargando ${model.name}…`);
        });
      }
      if (plan.includesSpeakerAi) {
        position += 1;
        setActiveDownload({
          id: "speaker-ai",
          name: "CAM++",
          kind: "speakers",
          position,
          total: totalSteps,
        });
        setProgress(0);
        setProgressMessage("Preparando el reconocimiento local de hablantes…");
        await waitForSpeakerModel(() => engine.installSpeakerAi(), (event) => {
          const payload = event.payload as {
            downloadedBytes?: number;
            totalBytes?: number;
            percent?: number;
          };
          setProgress(payload.percent ?? null);
          setProgressMessage(
            payload.totalBytes
              ? `${formatBytes(payload.downloadedBytes ?? 0)} de ${formatBytes(payload.totalBytes)}`
              : "Descargando CAM++…",
          );
        });
        setSpeakerAi((current) => current ? { ...current, installed: true, ready: true } : current);
      }
      const finalCatalog = await engine.listModels();
      setCatalog(finalCatalog);
      setProgress(100);
      setProgressMessage("Modelos verificados y listos para usarse sin conexión.");
      setActiveDownload(null);
      setState("completed");
      rememberConsent(plan);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : String(reason));
      setActiveDownload(null);
      setCancelling(false);
      setState("failed");
    }
  }

  async function cancelPreparation() {
    if (!activeDownload || activeDownload.kind !== "speakers" || cancelling) return;
    setCancelling(true);
    setProgressMessage("Deteniendo la preparación de forma segura…");
    try {
      await engine.cancelSpeakerAiDownload();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : String(reason));
      setCancelling(false);
    }
  }

  if (state === "checking") {
    return <div className="modal-backdrop model-setup-backdrop">
      <section className="model-setup-dialog compact" role="dialog" aria-modal="true" aria-labelledby="model-setup-title" aria-describedby="model-setup-description">
        <LoaderCircle className="spin" size={28} />
        <h2 id="model-setup-title">Preparando el primer inicio…</h2>
        <p id="model-setup-description">Comprobando el equipo, el espacio y los modelos locales.</p>
      </section>
    </div>;
  }

  const requiredBytes = plan?.requiredBytes ?? 0;
  const hasSpace = Boolean(plan?.canInstall);
  const installing = state === "installing";
  const completed = state === "completed";

  return <div className="modal-backdrop model-setup-backdrop">
    <section className="model-setup-dialog" role="dialog" aria-modal="true" aria-labelledby="model-setup-title" aria-describedby="model-setup-description">
      <header>
        <span className="model-setup-mark"><Sparkles /></span>
        <div>
          <span>PRIMER INICIO · CONFIGURACIÓN GUIADA</span>
          <h2 id="model-setup-title">{completed ? "Transcriptor está listo" : "Prepara la IA local"}</h2>
          <p id="model-setup-description">{completed
            ? "Ya puedes transcribir sin instalar Python, Node.js ni herramientas adicionales."
            : "Una sola preparación. Después, la transcripción y las voces funcionan en este ordenador."}</p>
        </div>
      </header>

      <div className="model-setup-content">
        {completed ? (
          <div className="model-setup-complete">
            <span><CheckCircle2 /></span>
            <strong>Todo preparado correctamente</strong>
            <p>Los modelos se han verificado y permanecerán disponibles aunque cierres la aplicación.</p>
            <div>
              <span><Check /> Transcripción profesional</span>
              <span><Check /> Detección de hablantes</span>
              <span><Check /> Procesamiento privado</span>
            </div>
          </div>
        ) : (
          <>
            <section className="setup-recommendation">
              <div>
                <span>RECOMENDADO PARA ESTE EQUIPO</span>
                <strong>{plan?.label ?? "Preparación local"}</strong>
                <p>{plan?.reason ?? error}</p>
              </div>
              {hardware && <output><Cpu size={14} /> {hardware.memory.totalMiB >= 1024 ? `${(hardware.memory.totalMiB / 1024).toFixed(0)} GB RAM` : `${hardware.memory.totalMiB} MB RAM`}{hardware.cudaAvailable ? " · GPU CUDA" : " · CPU"}</output>}
            </section>

            <div className="setup-package-list">
              {plan?.models.map((model) => <article key={model.id}>
                <span><BrainCircuit /></span>
                <div>
                  <strong>{model.name}{model.id === "large-v3" ? " · revisión de calidad" : " · transcripción"}</strong>
                  <p>{model.installed ? "Ya está instalado y verificado." : `${model.sizeGiB} GB · ${model.description}`}</p>
                </div>
                <em>{model.installed ? <><Check size={12} /> Listo</> : "Incluido"}</em>
              </article>)}
              <article>
                <span><Mic2 /></span>
                <div>
                  <strong>CAM++ · reconocimiento de voces</strong>
                  <p>{speakerAi?.ready ? "Ya está instalado y verificado." : "27 MB · Distingue y recuerda hablantes sólo en este equipo."}</p>
                </div>
                <em>{speakerAi?.ready ? <><Check size={12} /> Listo</> : "Incluido"}</em>
              </article>
            </div>

            {installing && activeDownload && <section className="setup-download" aria-live="polite">
              <div>
                <span><LoaderCircle className="spin" /></span>
                <div><strong>{activeDownload.kind === "speakers" ? "Preparando voces" : `Descargando ${activeDownload.name}`}</strong><p>Paso {activeDownload.position} de {activeDownload.total} · {progressMessage}</p></div>
                <output>{progress == null ? "Calculando…" : `${progress.toFixed(0)} %`}</output>
              </div>
              <progress aria-label={`Progreso de ${activeDownload.name}`} max={100} value={progress ?? undefined} />
              <small>No cierres Transcriptor durante esta preparación.</small>
            </section>}

            {error && <div className="setup-error" role="alert">
              <strong>No se pudo completar la preparación</strong>
              <span>{error}</span>
            </div>}

            {!installing && <label className="setup-consent">
              <input type="checkbox" checked={consent} onChange={(event) => setConsent(event.target.checked)} />
              <span><strong>Autorizo esta descarga única de {formatBytes(requiredBytes)}</strong><small>Los modelos proceden de sus repositorios oficiales, se guardan en {catalog?.root} y no contienen tus audios ni transcripciones.</small></span>
            </label>}

            <div className={`setup-storage ${hasSpace ? "" : "insufficient"}`}>
              <HardDrive size={15} />
              <span>{formatBytes(catalog?.freeBytes ?? 0)} libres</span>
              <i />
              <span>{formatBytes(requiredBytes)} necesarios, incluida la reserva de seguridad</span>
            </div>

            <p className="setup-runtime-note"><ShieldCheck size={14} /> La aplicación ya incluye su motor y FFmpeg. No tendrás que instalar Python, Node.js ni escribir comandos.</p>
          </>
        )}
      </div>

      <footer>
        <span><LockKeyhole size={13} /> Audio y modelos bajo tu control</span>
        <div>
          {!completed && !installing && <button className="button ghost" onClick={onLater}>Ahora no</button>}
          {installing && activeDownload?.kind === "speakers" && <button className="button ghost" disabled={cancelling} onClick={() => void cancelPreparation()}>{cancelling ? "Deteniendo…" : "Cancelar CAM++"}</button>}
          {installing && activeDownload?.kind === "transcription" && <span className="setup-download-lock"><LockKeyhole size={13} /> Descarga verificable en curso</span>}
          {completed ? (
            <button className="button primary" onClick={() => onComplete({ qualityMode: plan?.qualityMode ?? "instant", speakerAiReady: true })}>Empezar a usar Transcriptor</button>
          ) : (
            <button className="button primary" disabled={installing || !consent || !hasSpace} onClick={() => void prepareComputer()}>
              {installing ? <LoaderCircle className="spin" size={15} /> : <Download size={15} />}
              {installing ? "Preparando…" : hasSpace ? "Descargar y preparar" : "Espacio insuficiente"}
            </button>
          )}
        </div>
      </footer>
    </section>
  </div>;
}

function waitForModel(
  modelId: string,
  start: () => Promise<unknown>,
  onProgress: (event: EngineEvent) => void,
): Promise<void> {
  return waitForEngineTask(
    start,
    (event) => {
      const payload = event.payload as { modelId?: string; message?: string };
      if (payload.modelId !== modelId) return null;
      if (event.type === "model_manager_progress") {
        onProgress(event);
        return null;
      }
      if (event.type === "model_manager_completed") return "completed";
      if (event.type === "model_manager_failed") return new Error(payload.message ?? `No se pudo descargar ${modelId}.`);
      if (event.type === "model_manager_cancelled") return new Error(`Se canceló la descarga de ${modelId}.`);
      return null;
    },
  );
}

function waitForSpeakerModel(
  start: () => Promise<unknown>,
  onProgress: (event: EngineEvent) => void,
): Promise<void> {
  return waitForEngineTask(
    start,
    (event) => {
      const payload = event.payload as { message?: string };
      if (event.type === "speaker_model_progress") {
        onProgress(event);
        return null;
      }
      if (event.type === "speaker_model_completed") return "completed";
      if (event.type === "speaker_model_failed") return new Error(payload.message ?? "No se pudo instalar CAM++.");
      if (event.type === "speaker_model_cancelled") return new Error("Se canceló la instalación de CAM++.");
      return null;
    },
  );
}

function waitForEngineTask(
  start: () => Promise<unknown>,
  route: (event: EngineEvent) => "completed" | Error | null,
): Promise<void> {
  return new Promise<void>((resolve, reject) => {
    const unsubscribe = engine.subscribe((event) => {
      const result = route(event);
      if (!result) return;
      unsubscribe();
      if (result === "completed") resolve();
      else reject(result);
    });
    start().catch((reason) => {
      unsubscribe();
      reject(reason);
    });
  });
}

function rememberConsent(plan: RecommendedModelSetup) {
  try {
    for (const model of plan.models) {
      localStorage.setItem(`transcriptor.model-consent.${model.id}`, "accepted");
    }
    const ids = plan.models.map((model) => model.id);
    if (ids.includes("turbo") && ids.includes("large-v3")) {
      localStorage.setItem("transcriptor.model-consent.turbo+large-v3", "accepted");
    }
    localStorage.setItem("transcriptor.model-onboarding.v1", "completed");
  } catch {
    // Tauri normally provides storage; a restricted webview can still continue this session.
  }
}

function formatBytes(bytes: number): string {
  if (bytes >= 1024 ** 3) return `${(bytes / 1024 ** 3).toFixed(1)} GB`;
  return `${Math.max(0, bytes / 1024 ** 2).toFixed(0)} MB`;
}
