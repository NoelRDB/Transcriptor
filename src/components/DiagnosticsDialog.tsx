import { AlertTriangle, CheckCircle2, Cpu, FolderSearch2, HardDrive, RefreshCw, ShieldCheck, Stethoscope, X, XCircle } from "lucide-react";
import type { SystemDiagnostics, TranscriptionProject } from "../types";

interface DiagnosticsDialogProps {
  project: TranscriptionProject | null;
  diagnostics: SystemDiagnostics | null;
  loading: boolean;
  onRun: () => void;
  onRelocate: () => void;
  onUseCandidate: (path: string) => void;
  onClose: () => void;
}

export function DiagnosticsDialog({ project, diagnostics, loading, onRun, onRelocate, onUseCandidate, onClose }: DiagnosticsDialogProps) {
  const mediaProblem = diagnostics?.checks.some((check) => check.id === "media" && check.status === "error");
  return <div className="modal-backdrop" role="presentation" onMouseDown={(event) => { if (event.target === event.currentTarget) onClose(); }}>
    <section className="diagnostics-dialog" role="dialog" aria-modal="true" aria-labelledby="diagnostics-title">
      <header>
        <div className="dialog-heading-icon"><Stethoscope size={22} /></div>
        <div><span>CENTRO DE SALUD</span><h2 id="diagnostics-title">Diagnóstico y recuperación</h2><p>Comprueba el archivo, los modelos y los recursos locales antes de trabajar.</p></div>
        <button className="icon-button" onClick={onClose} aria-label="Cerrar diagnóstico"><X size={19} /></button>
      </header>

      <div className={`diagnostic-hero ${diagnostics?.status ?? "idle"}`}>
        <span>{diagnostics?.status === "ok" ? <ShieldCheck size={25} /> : diagnostics?.status === "error" ? <XCircle size={25} /> : <AlertTriangle size={25} />}</span>
        <div><strong>{loading ? "Revisando el sistema…" : diagnostics?.status === "ok" ? "Todo listo para transcribir" : diagnostics?.status === "error" ? "Hay un problema que requiere atención" : diagnostics ? "Puedes trabajar, con alguna recomendación" : "Comprueba el equipo en un clic"}</strong><p>{project ? `Proyecto: ${project.name}` : "Diagnóstico general del motor local"}</p></div>
        <button className="button secondary" onClick={onRun} disabled={loading}><RefreshCw className={loading ? "spin" : ""} size={16} /> Comprobar</button>
      </div>

      <div className="diagnostic-grid" aria-live="polite">
        {diagnostics?.checks.map((check) => <article key={check.id} className={check.status}>
          <span>{check.status === "ok" ? <CheckCircle2 size={18} /> : check.status === "warning" ? <AlertTriangle size={18} /> : <XCircle size={18} />}</span>
          <div><strong>{check.label}</strong><p>{check.detail}</p></div>
        </article>)}
        {!diagnostics && !loading && <div className="diagnostic-empty"><Cpu size={32} /><strong>Aún no se ha ejecutado el diagnóstico</strong><p>No se modifica ningún archivo ni se envía información fuera del equipo.</p></div>}
      </div>

      {diagnostics?.hardware && <div className="diagnostic-resources">
        <div><Cpu size={16} /><span><small>Procesador</small><strong>{diagnostics.hardware.cpu.name}</strong></span></div>
        <div><HardDrive size={16} /><span><small>Memoria disponible</small><strong>{Math.round(diagnostics.hardware.memory.availableMiB / 1024)} GB</strong></span></div>
        <div><ShieldCheck size={16} /><span><small>Aceleración</small><strong>{diagnostics.hardware.cudaAvailable ? "CUDA activa" : "CPU local"}</strong></span></div>
      </div>}

      <footer>
        <p><ShieldCheck size={14} /> Los datos de diagnóstico permanecen en este ordenador.</p>
        {project && diagnostics?.mediaCandidates?.[0] && <button className="button primary" onClick={() => onUseCandidate(diagnostics.mediaCandidates![0])}><RefreshCw size={16} /> Reparar automáticamente</button>}
        {project && <button className="button secondary" onClick={onRelocate}><FolderSearch2 size={16} /> {mediaProblem ? "Relocalizar manualmente" : "Cambiar archivo original"}</button>}
        <button className="button primary" onClick={onClose}>Listo</button>
      </footer>
    </section>
  </div>;
}
