import { ArrowUpRight, Check, FileAudio2, FileVideo2, FolderOpen, LoaderCircle, LockKeyhole, Sparkles, Trash2 } from "lucide-react";
import { useState } from "react";
import type { RecentProject } from "../types";
import { formatClock } from "../lib/time";
import { DeleteProjectDialog } from "./DeleteProjectDialog";
import { WorkQueuePanel } from "./WorkQueuePanel";

interface BatchImportResult {
  added: number;
  reused: number;
  failures: Array<{ path: string; message: string }>;
}

interface WelcomeProps {
  recent: RecentProject[];
  loading?: boolean;
  onOpen: () => void;
  onOpenRecent: (id: string) => void;
  onDeleteRecent: (id: string) => Promise<void>;
  onDropPath: (path: string) => void;
  onImportFiles: (
    paths: string[],
    onProgress?: (completed: number, total: number, currentName: string) => void,
  ) => Promise<BatchImportResult>;
}

function projectStatus(project: RecentProject) {
  const running = ["analyzing", "waiting_model", "transcribing"].includes(project.transcriptionStatus);
  return { label: project.transcriptionStatus === "completed" ? "Completado" : running ? "Procesando" : "Pendiente", running };
}

export function Welcome({ recent, loading = false, onOpen, onOpenRecent, onDeleteRecent, onDropPath, onImportFiles }: WelcomeProps) {
  const [pendingDelete, setPendingDelete] = useState<RecentProject | null>(null);
  const [deleting, setDeleting] = useState(false);
  const [deleteError, setDeleteError] = useState<string | null>(null);
  const handleDrop = (event: React.DragEvent<HTMLElement>) => {
    event.preventDefault();
    const file = event.dataTransfer.files[0] as File & { path?: string };
    if (file?.path) onDropPath(file.path);
  };

  const confirmDelete = async () => {
    if (!pendingDelete) return;
    setDeleting(true);
    setDeleteError(null);
    try {
      await onDeleteRecent(pendingDelete.id);
      setPendingDelete(null);
    } catch (reason) {
      setDeleteError(reason instanceof Error ? reason.message : String(reason));
    } finally {
      setDeleting(false);
    }
  };

  return (
    <main className="welcome" onDragOver={(event) => event.preventDefault()} onDrop={handleDrop}>
      <section className="welcome-hero" aria-labelledby="welcome-title">
        <div className="hero-eyebrow"><Sparkles size={14} /> IA privada en tu ordenador</div>
        <h1 id="welcome-title">Del audio a las ideas.<br /><em>Sin perder el contexto.</em></h1>
        <p>Transcribe, revisa y entiende cualquier conversación. Reproduce cada instante junto a su texto y obtén conclusiones sin subir tus archivos.</p>

        <div className="hero-features" aria-label="Funciones principales">
          <span><Check size={13} /> Audio y vídeo</span>
          <span><Check size={13} /> Texto sincronizado</span>
          <span><Check size={13} /> Análisis con IA local</span>
        </div>

        <button className="drop-zone" onClick={onOpen}>
          <span className="drop-icon" aria-hidden="true"><FileAudio2 /><FileVideo2 /></span>
          <span className="drop-copy">
            <strong>Importar audio o vídeo</strong>
            <small>Arrastra el archivo aquí o selecciónalo desde tu equipo</small>
            <i>MP3, WAV, M4A, FLAC, OGG, MP4, MOV, MKV y WEBM</i>
          </span>
          <span className="drop-action" aria-hidden="true"><ArrowUpRight size={19} /></span>
        </button>

        <div className="privacy-note">
          <span className="privacy-icon"><LockKeyhole size={16} /></span>
          <span><strong>Privado por diseño</strong><small>El audio y la transcripción permanecen en este dispositivo.</small></span>
        </div>
      </section>

      <aside className="welcome-sidebar" aria-label="Actividad y proyectos">
        <WorkQueuePanel onImportFiles={onImportFiles} onOpenProject={onOpenRecent} />
        <section className="recent-card" aria-label="Proyectos recientes">
          <header className="recent-title">
            <span><strong>Proyectos recientes</strong><small>{recent.length ? `${recent.length} guardados en este equipo` : "Tu historial local"}</small></span>
            <FolderOpen size={18} />
          </header>
          {loading ? (
            <div className="no-recent" role="status"><span><LoaderCircle className="spin" size={25} /></span><strong>Conectando con tus proyectos…</strong><p>Iniciando el motor local y recuperando tu historial.</p></div>
          ) : !recent.length ? (
            <div className="no-recent"><span><FolderOpen size={25} /></span><strong>Aún no hay proyectos</strong><p>Cuando abras un archivo podrás retomarlo desde aquí.</p></div>
          ) : (
            <div className="recent-list">
              {recent.map((project) => {
                const status = projectStatus(project);
                return (
                  <article className="recent-project" key={project.id}>
                    <button className="recent-open" onClick={() => onOpenRecent(project.id)} title={`Abrir ${project.name}`}>
                      <span className={`file-kind ${project.mediaType}`}>{project.mediaType === "video" ? <FileVideo2 /> : <FileAudio2 />}</span>
                      <span className="recent-project-copy">
                        <strong>{project.name}</strong>
                        <small>{new Date(project.updatedAt).toLocaleDateString("es-ES", { day: "2-digit", month: "short" })} · {formatClock(project.durationMs)}</small>
                      </span>
                      <span className={`project-status ${status.running ? "running" : ""}`}><i />{status.label}</span>
                    </button>
                    <button className="recent-delete" onClick={() => { setDeleteError(null); setPendingDelete(project); }} aria-label={`Eliminar ${project.name}`} title="Eliminar proyecto"><Trash2 size={15} /></button>
                  </article>
                );
              })}
            </div>
          )}
          <footer><LockKeyhole size={13} /> Proyectos almacenados sólo en este equipo</footer>
        </section>
      </aside>
      {pendingDelete && <DeleteProjectDialog project={pendingDelete} busy={deleting} error={deleteError} onCancel={() => { setPendingDelete(null); setDeleteError(null); }} onConfirm={() => void confirmDelete()} />}
    </main>
  );
}
