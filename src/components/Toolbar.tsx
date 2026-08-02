import { useRef, useState } from "react";
import { BrainCircuit, Check, Download, FileAudio, Fingerprint, FolderOpen, LoaderCircle, Mic, PanelTop, Pencil, Settings, Square, Stethoscope, WandSparkles, X } from "lucide-react";
import type { ExportFormat } from "../lib/exporters";
import type { JobState, TranscriptionProject } from "../types";

interface ToolbarProps {
  project: TranscriptionProject | null;
  jobState: JobState;
  isDirty: boolean;
  onOpen: () => void;
  onBrowserFile: (file: File) => void;
  onTranscribe: () => void;
  onCancel: () => void;
  onExport: (format: ExportFormat) => void;
  onInsights: () => void;
  onLive: () => void;
  onVoices: () => void;
  onSettings: () => void;
  onDiagnostics: () => void;
  onRenameProject: (name: string) => Promise<void>;
  onShowProjects: () => void;
}

const EXPORT_OPTIONS: Array<{ format: ExportFormat; label: string; detail: string }> = [
  { format: "txt", label: "TXT", detail: "Texto limpio" },
  { format: "docx", label: "DOCX", detail: "Documento Word" },
  { format: "pdf", label: "PDF", detail: "Documento maquetado" },
  { format: "srt", label: "SRT", detail: "Subtítulos" },
  { format: "vtt", label: "VTT", detail: "Subtítulos web" },
  { format: "json", label: "JSON", detail: "Datos estructurados" },
  { format: "csv", label: "CSV", detail: "Hoja de datos" },
  { format: "txt-safe", label: "TXT seguro", detail: "Datos sensibles ocultos" },
  { format: "pdf-safe", label: "PDF seguro", detail: "Informe anonimizado" },
  { format: "package", label: "Proyecto", detail: "Portable sin audio" },
  { format: "package-media", label: "Proyecto completo", detail: "Portable con audio/vídeo" },
];

export function Toolbar({ project, jobState, isDirty, onOpen, onBrowserFile, onTranscribe, onCancel, onExport, onInsights, onLive, onVoices, onSettings, onDiagnostics, onRenameProject, onShowProjects }: ToolbarProps) {
  const input = useRef<HTMLInputElement>(null);
  const [exportOpen, setExportOpen] = useState(false);
  const [editingName, setEditingName] = useState(false);
  const [draftName, setDraftName] = useState("");
  const [renaming, setRenaming] = useState(false);
  const working = ["analyzing", "waiting_model", "transcribing"].includes(jobState);
  const open = () => window.__TAURI_INTERNALS__ ? onOpen() : input.current?.click();

  async function submitName() {
    const name = draftName.trim();
    if (!project || !name) return;
    setRenaming(true);
    try {
      await onRenameProject(name);
      setEditingName(false);
    } finally {
      setRenaming(false);
    }
  }

  return (
    <header className="toolbar" data-has-project={Boolean(project)}>
      <button className="brand" disabled={working} onClick={onShowProjects} aria-label="Ir a proyectos recientes">
        <span className="brand-mark"><PanelTop size={18} /></span>
        <span className="brand-copy"><strong>Transcriptor</strong><small>IA local y privada</small></span>
      </button>
      <span className="toolbar-separator" />
      <button className="button secondary open-button" disabled={working} onClick={open}><FolderOpen size={17} /><span>Abrir archivo</span></button>
      <input ref={input} hidden type="file" accept="audio/*,video/*,.mkv,.m4v,.opus" onChange={(event) => event.target.files?.[0] && onBrowserFile(event.target.files[0])} />
      <div className="project-heading" title={project?.mediaPath}>
        <span className="project-heading-icon"><FileAudio size={16} /></span>
        {editingName && project ? (
          <form className="project-name-editor" onSubmit={(event) => { event.preventDefault(); void submitName(); }}>
            <small>Proyecto actual</small>
            <span><input autoFocus maxLength={120} value={draftName} onChange={(event) => setDraftName(event.target.value)} aria-label="Nombre del proyecto" /><button type="submit" disabled={renaming || !draftName.trim()} aria-label="Guardar nombre"><Check size={15} /></button><button type="button" disabled={renaming} onClick={() => setEditingName(false)} aria-label="Cancelar"><X size={15} /></button></span>
          </form>
        ) : (
          <span className="project-heading-copy"><small>{project ? "Proyecto actual" : "Espacio de trabajo"}</small><strong>{project?.name ?? "Ningún proyecto abierto"}</strong></span>
        )}
        {project && !editingName && <button className="project-rename-button" disabled={working} onClick={() => { setDraftName(project.name); setEditingName(true); }} aria-label="Cambiar nombre del proyecto" title="Cambiar nombre"><Pencil size={14} /></button>}
        {isDirty && <i aria-label="Cambios pendientes" />}
      </div>
      <nav className="toolbar-actions" aria-label="Acciones del proyecto">
        <button className="button live-button" disabled={working} onClick={onLive}><Mic size={17} /><span>Grabar</span></button>
        <button className="button secondary voices-toolbar-button" onClick={onVoices}><Fingerprint size={17} /><span>Voces</span></button>
        <button className="button intelligence" disabled={!project?.segments.length || working} onClick={onInsights}><BrainCircuit size={17} /><span>Inteligencia</span></button>
        <button className="icon-button health-button" onClick={onDiagnostics} aria-label="Diagnóstico y recuperación" title="Diagnóstico y recuperación"><Stethoscope size={18} /></button>
        {working ? (
          <button className="button danger" onClick={onCancel}><Square size={13} fill="currentColor" /><span>Detener</span></button>
        ) : (
          <button className="button primary" disabled={!project} onClick={onTranscribe}>
            {jobState === "analyzing" ? <LoaderCircle className="spin" size={17} /> : <WandSparkles size={17} />}
            <span>{project?.segments.length ? "Retranscribir" : "Transcribir"}</span>
          </button>
        )}
        <div className="menu-wrap">
          <button className="button secondary" disabled={!project?.segments.length} onClick={() => setExportOpen(!exportOpen)} aria-expanded={exportOpen}><Download size={17} /><span>Exportar</span></button>
          {exportOpen && <div className="menu" role="menu">
            {EXPORT_OPTIONS.map((option) => <button key={option.format} role="menuitem" onClick={() => { onExport(option.format); setExportOpen(false); }}>{option.label}<small>{option.detail}</small></button>)}
          </div>}
        </div>
        <button className="icon-button settings-button" onClick={onSettings} aria-label="Ajustes y modelos" title="Ajustes y modelos"><Settings size={19} /></button>
      </nav>
    </header>
  );
}
