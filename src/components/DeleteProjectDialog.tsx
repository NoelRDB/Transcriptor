import { AlertTriangle, FileAudio2, Trash2, X } from "lucide-react";
import type { RecentProject } from "../types";

interface DeleteProjectDialogProps {
  project: RecentProject;
  busy: boolean;
  error: string | null;
  onCancel: () => void;
  onConfirm: () => void;
}

export function DeleteProjectDialog({ project, busy, error, onCancel, onConfirm }: DeleteProjectDialogProps) {
  return (
    <div className="modal-backdrop delete-backdrop" role="presentation" onMouseDown={(event) => { if (event.currentTarget === event.target && !busy) onCancel(); }}>
      <section className="delete-dialog" role="alertdialog" aria-modal="true" aria-labelledby="delete-project-title" aria-describedby="delete-project-description">
        <header>
          <span className="delete-dialog-icon"><Trash2 size={20} /></span>
          <button className="icon-button" disabled={busy} onClick={onCancel} aria-label="Cerrar"><X size={18} /></button>
        </header>
        <h2 id="delete-project-title">¿Eliminar este proyecto?</h2>
        <p id="delete-project-description">Se quitarán la transcripción, los hablantes y los análisis guardados en Transcriptor.</p>
        <div className="delete-project-summary"><FileAudio2 size={18} /><span><strong>{project.name}</strong><small>El archivo de audio o vídeo original no se eliminará.</small></span></div>
        {error && <p className="delete-project-error" role="alert"><AlertTriangle size={15} />{error}</p>}
        <footer>
          <button className="button secondary" disabled={busy} onClick={onCancel}>Cancelar</button>
          <button className="button danger solid-danger" disabled={busy} onClick={onConfirm}><Trash2 size={16} />{busy ? "Eliminando…" : "Eliminar proyecto"}</button>
        </footer>
      </section>
    </div>
  );
}
