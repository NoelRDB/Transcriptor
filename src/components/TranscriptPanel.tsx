import { useEffect, useMemo, useRef, useState } from "react";
import { AlignLeft, Check, ChevronDown, CircleAlert, Edit3, FileOutput, Fingerprint, Link2, ListX, LocateFixed, Maximize2, Minimize2, Replace, Scissors, Search, Undo2, Redo2, X } from "lucide-react";
import type { TranscriptSegment } from "../types";
import { speakerClassName } from "../lib/speakers";
import { activeSegmentIndex, followSegmentIndex, formatClock } from "../lib/time";

interface TranscriptPanelProps {
  segments: TranscriptSegment[];
  currentTimeMs: number;
  followPlayback: boolean;
  onFollowChange: (value: boolean) => void;
  onSeek: (ms: number) => void;
  onEdit: (id: string, text: string, commit?: boolean) => void;
  onSpeakerChange?: (id: string, speaker?: string) => void;
  onReplaceAll?: (query: string, replacement: string) => number;
  onSplit?: (id: string, position: number, text: string) => void;
  onMergeNext?: (id: string) => void;
  onExportMediaEdit?: (excludedIds: string[]) => void;
  onUndo: () => void;
  onRedo: () => void;
  onGroupParagraphs?: () => void;
  canUndo: boolean;
  canRedo: boolean;
  focusMode?: boolean;
  onFocusMode?: () => void;
}

export function TranscriptPanel({ segments, currentTimeMs, followPlayback, onFollowChange, onSeek, onEdit, onSpeakerChange, onReplaceAll, onSplit, onMergeNext, onExportMediaEdit, onUndo, onRedo, onGroupParagraphs, canUndo, canRedo, focusMode = false, onFocusMode }: TranscriptPanelProps) {
  const [query, setQuery] = useState("");
  const [replacement, setReplacement] = useState("");
  const [showReplace, setShowReplace] = useState(false);
  const [replaceNotice, setReplaceNotice] = useState("");
  const [mediaEditMode, setMediaEditMode] = useState(false);
  const [excludedIds, setExcludedIds] = useState<Set<string>>(() => new Set());
  const [editing, setEditing] = useState<string | null>(null);
  const [draft, setDraft] = useState("");
  const [speakerDraft, setSpeakerDraft] = useState("");
  const [followPaused, setFollowPaused] = useState(false);
  const [reviewOnly, setReviewOnly] = useState(false);
  const listRef = useRef<HTMLDivElement>(null);
  const editorRef = useRef<HTMLTextAreaElement>(null);
  const resumeTimerRef = useRef<number | null>(null);
  const activeIndex = useMemo(() => activeSegmentIndex(segments, currentTimeMs), [segments, currentTimeMs]);
  const followIndex = useMemo(() => followSegmentIndex(segments, currentTimeMs), [segments, currentTimeMs]);
  const followSegmentId = followIndex >= 0 ? segments[followIndex].id : null;
  const uncertainCount = useMemo(() => segments.filter((segment) => segment.confidence != null && segment.confidence < 0.84).length, [segments]);
  const visible = useMemo(() => segments.filter((segment) => {
    if (reviewOnly && !(segment.confidence != null && segment.confidence < 0.84)) return false;
    return !query.trim() || segment.text.toLocaleLowerCase().includes(query.toLocaleLowerCase());
  }), [segments, query, reviewOnly]);
  const speakerOptions = useMemo(() => {
    const names = new Set<string>(["Hablante 1", "Hablante 2"]);
    for (const segment of segments) if (segment.speaker) names.add(segment.speaker);
    return [...names];
  }, [segments]);
  const following = followPlayback && !followPaused;

  useEffect(() => {
    return () => {
      if (resumeTimerRef.current !== null) window.clearTimeout(resumeTimerRef.current);
    };
  }, []);

  useEffect(() => {
    if (!following || editing || !followSegmentId || query) return;
    const frame = window.requestAnimationFrame(() => {
      const list = listRef.current;
      const target = list?.querySelector<HTMLElement>(`[data-segment-id="${CSS.escape(followSegmentId)}"]`);
      if (!list || !target) return;
      const listRect = list.getBoundingClientRect();
      const targetRect = target.getBoundingClientRect();
      const targetCenter = targetRect.top - listRect.top + list.scrollTop + targetRect.height / 2;
      const nextTop = Math.max(0, targetCenter - list.clientHeight / 2);
      const reduceMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
      list.scrollTo({ top: nextTop, behavior: reduceMotion ? "auto" : "smooth" });
    });
    return () => window.cancelAnimationFrame(frame);
  }, [editing, followSegmentId, following, query]);

  function pauseFollowingTemporarily() {
    if (!followPlayback) return;
    setFollowPaused(true);
    if (resumeTimerRef.current !== null) window.clearTimeout(resumeTimerRef.current);
    resumeTimerRef.current = window.setTimeout(() => {
      setFollowPaused(false);
      resumeTimerRef.current = null;
    }, 4_000);
  }

  function toggleFollowing() {
    if (followPaused) {
      if (resumeTimerRef.current !== null) window.clearTimeout(resumeTimerRef.current);
      resumeTimerRef.current = null;
      setFollowPaused(false);
      if (!followPlayback) onFollowChange(true);
      return;
    }
    onFollowChange(!followPlayback);
  }

  function beginEdit(segment: TranscriptSegment) {
    setEditing(segment.id);
    setDraft(segment.text);
    setSpeakerDraft(segment.speaker ?? "");
  }

  function commit() {
    if (editing) {
      onEdit(editing, draft, true);
      onSpeakerChange?.(editing, speakerDraft || undefined);
    }
    setEditing(null);
  }

  return (
    <aside className="transcript-panel" aria-label="Transcripción">
      <div className="panel-title">
        <div><span>TRANSCRIPCIÓN</span><strong>{segments.length ? `${segments.length} fragmentos` : "Sin contenido"}</strong></div>
        <div className="panel-tools">
          {uncertainCount > 0 && <button className={`review-button ${reviewOnly ? "active" : ""}`} onClick={() => setReviewOnly((value) => !value)} title="Mostrar fragmentos que merecen revisión"><CircleAlert size={15} /> {uncertainCount}</button>}
          <button className="icon-button" disabled={!canUndo} onClick={onUndo} aria-label="Deshacer"><Undo2 size={17} /></button>
          <button className="icon-button" disabled={!canRedo} onClick={onRedo} aria-label="Rehacer"><Redo2 size={17} /></button>
          {onGroupParagraphs && <button className="icon-button" disabled={segments.length < 2} onClick={onGroupParagraphs} aria-label="Agrupar fragmentos en párrafos" title="Agrupar en párrafos con contexto"><AlignLeft size={17} /></button>}
          {onExportMediaEdit && <button className={`icon-button ${mediaEditMode ? "active" : ""}`} disabled={!segments.length} onClick={() => { setMediaEditMode((value) => !value); setExcludedIds(new Set()); }} aria-label="Editar audio desde el texto" title="Seleccionar fragmentos que se eliminarán de una copia"><ListX size={17} /></button>}
          <button className={`follow-button ${following ? "active" : ""}`} onClick={toggleFollowing} title={followPaused ? "El seguimiento se reanudará automáticamente" : "Mantener el fragmento activo centrado"}><LocateFixed size={16} /> {followPaused ? "Reanudar" : "Seguir"}</button>
          {onFocusMode && <button className="icon-button" onClick={onFocusMode} aria-label={focusMode ? "Mostrar reproductor" : "Ampliar transcripción"} title={focusMode ? "Mostrar reproductor" : "Ampliar transcripción"}>{focusMode ? <Minimize2 size={17} /> : <Maximize2 size={17} />}</button>}
        </div>
      </div>
      <div className="transcript-search-tools">
        <label className="search-box"><Search size={17} /><input value={query} onChange={(e) => { setQuery(e.target.value); setReplaceNotice(""); }} placeholder="Buscar en la transcripción…" aria-label="Buscar" />{query && <button onClick={() => setQuery("")} aria-label="Borrar búsqueda"><X size={15} /></button>}<button className={showReplace ? "active" : ""} onClick={() => setShowReplace((value) => !value)} aria-label="Buscar y reemplazar" title="Buscar y reemplazar"><Replace size={15} /></button></label>
        {showReplace && <div className="replace-box"><input value={replacement} onChange={(event) => setReplacement(event.target.value)} placeholder="Reemplazar por…" aria-label="Texto de reemplazo" /><button disabled={!query || !onReplaceAll} onClick={() => { const count = onReplaceAll?.(query, replacement) ?? 0; setReplaceNotice(count ? `${count} cambio${count === 1 ? "" : "s"}` : "Sin coincidencias"); }}><Replace size={14} /> Reemplazar todo</button>{replaceNotice && <output>{replaceNotice}</output>}</div>}
      </div>
      <div className="segment-list" ref={listRef} onWheel={pauseFollowingTemporarily} onTouchMove={pauseFollowingTemporarily}>
        {!segments.length && <div className="empty-transcript"><div className="sound-lines"><i /><i /><i /><i /><i /></div><strong>La transcripción aparecerá aquí</strong><p>El texto se añadirá progresivamente y quedará sincronizado con el reproductor.</p></div>}
        {visible.map((segment) => {
          const active = segment.id === segments[activeIndex]?.id;
          const activeWord = active ? segment.words.findIndex((word) => currentTimeMs >= word.startMs && currentTimeMs < word.endMs) : -1;
          const uncertain = segment.confidence != null && segment.confidence < 0.84;
          const excluded = excludedIds.has(segment.id);
          const toggleExcluded = () => setExcludedIds((current) => { const next = new Set(current); if (next.has(segment.id)) next.delete(segment.id); else next.add(segment.id); return next; });
          return <article key={segment.id} data-segment-id={segment.id} className={`segment ${active ? "active" : ""} ${uncertain ? "uncertain" : ""} ${excluded ? "excluded" : ""}`} tabIndex={0} aria-label={`${mediaEditMode ? excluded ? "Conservar" : "Eliminar de la copia" : "Ir a"} ${formatClock(segment.startMs)}: ${segment.text}`} onKeyDown={(event) => { if ((event.key === "Enter" || event.key === " ") && editing !== segment.id) { event.preventDefault(); if (mediaEditMode) toggleExcluded(); else onSeek(segment.startMs); } }} onClick={() => { if (editing === segment.id) return; if (mediaEditMode) toggleExcluded(); else onSeek(segment.startMs); }}>
            <div className="segment-meta">{mediaEditMode && <input type="checkbox" checked={excluded} onChange={toggleExcluded} onClick={(event) => event.stopPropagation()} aria-label={`Eliminar fragmento de ${formatClock(segment.startMs)}`} />}<button onClick={(event) => { event.stopPropagation(); onSeek(segment.startMs); }}>{formatClock(segment.startMs)}</button>{segment.speaker && <span className={speakerClassName(segment.speaker)}>{segment.speaker}</span>}{segment.speakerProfileId && <span className="voice-profile-badge" title={`Voz reconocida${segment.speakerMatchConfidence ? ` con un ${Math.round(segment.speakerMatchConfidence * 100)} % de similitud` : ""}`}><Fingerprint size={10} />Perfil</span>}{uncertain && <span className="confidence-badge" title="Confianza acústica baja"><CircleAlert size={11} /> {Math.round((segment.confidence ?? 0) * 100)} %</span>}<button className="edit-segment" onClick={(event) => { event.stopPropagation(); beginEdit(segment); }} aria-label="Editar fragmento"><Edit3 size={14} /></button></div>
            {editing === segment.id ? <div className="edit-wrap" onClick={(e) => e.stopPropagation()}>{onSpeakerChange && <label className="speaker-editor"><span>Hablante</span><select value={speakerDraft} onChange={(event) => setSpeakerDraft(event.target.value)}><option value="">Sin identificar</option>{speakerOptions.map((speaker) => <option key={speaker} value={speaker}>{speaker}</option>)}</select></label>}<textarea ref={editorRef} autoFocus value={draft} onChange={(e) => setDraft(e.target.value)} onKeyDown={(e) => { if (e.key === "Escape") setEditing(null); if ((e.ctrlKey || e.metaKey) && e.key === "Enter") commit(); }} /><div>{onSplit && <button disabled={draft.trim().length < 2} onClick={() => { const position = editorRef.current?.selectionStart ?? Math.round(draft.length / 2); onSplit(segment.id, position, draft); setEditing(null); }} title="Divide el fragmento en la posición del cursor"><Scissors size={14} /> Dividir</button>}{onMergeNext && segment.order < segments.length - 1 && <button onClick={() => { onMergeNext(segment.id); setEditing(null); }}><Link2 size={14} /> Unir siguiente</button>}<button onClick={() => setEditing(null)}><X size={14} /> Cancelar</button><button className="save-edit" onClick={commit}><Check size={14} /> Aplicar</button></div></div> :
              <p>{segment.words.length ? segment.words.map((word, index) => <span className={index === activeWord ? "active-word" : ""} key={word.id}>{word.text}{" "}</span>) : highlight(segment.text, query)}</p>}
          </article>;
        })}
      </div>
      {mediaEditMode && <div className="media-edit-bar"><span><ListX size={14} /><strong>{excludedIds.size}</strong> fragmentos se omitirán de una copia; el original no cambia.</span><button className="button primary" disabled={!excludedIds.size} onClick={() => onExportMediaEdit?.([...excludedIds])}><FileOutput size={15} /> Crear copia editada</button></div>}
      {(query || reviewOnly) && <div className="search-results">{visible.length} {reviewOnly ? "fragmentos para revisar" : "coincidencias"} <ChevronDown size={14} /></div>}
    </aside>
  );
}

function highlight(text: string, query: string) {
  if (!query.trim()) return text;
  const parts = text.split(new RegExp(`(${escapeRegExp(query)})`, "gi"));
  return parts.map((part, index) => part.toLocaleLowerCase() === query.toLocaleLowerCase() ? <mark key={index}>{part}</mark> : part);
}

function escapeRegExp(value: string): string { return value.replace(/[.*+?^${}()|[\]\\]/g, "\\$&"); }
