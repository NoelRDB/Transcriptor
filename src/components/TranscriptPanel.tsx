import { useEffect, useMemo, useRef, useState } from "react";
import { AlignLeft, Check, ChevronDown, CircleAlert, Edit3, FileOutput, Fingerprint, Link2, ListX, LocateFixed, Maximize2, Minimize2, Replace, Scissors, Search, Undo2, Redo2, X } from "lucide-react";
import type { TranscriptSegment, VoiceProfile } from "../types";
import { speakerClassName } from "../lib/speakers";
import { activeSegmentIndex, followSegmentIndex, formatClock } from "../lib/time";

interface TranscriptPanelProps {
  segments: TranscriptSegment[];
  voiceProfiles?: VoiceProfile[];
  currentTimeMs: number;
  followPlayback: boolean;
  onFollowChange: (value: boolean) => void;
  onSeek: (ms: number) => void;
  onEdit: (id: string, text: string, commit?: boolean) => void;
  onSpeakerChange?: (id: string, speaker?: string, speakerProfileId?: string) => void;
  onSpeakerReview?: (id: string) => void;
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

interface SpeakerOption {
  value: string;
  name: string;
  profileId?: string;
  label: string;
}

const REVIEW_THRESHOLD = 0.84;
const CRITICAL_CONFIDENCE = 0.70;

function reviewCompleted(state: TranscriptSegment["reviewState"]): boolean {
  return state === "accepted" || state === "corrected" || state === "ignored";
}

function needsTextReview(segment: TranscriptSegment): boolean {
  if (reviewCompleted(segment.reviewState)) return false;
  return segment.reviewState === "pending"
    || Boolean(segment.reviewReasons?.length)
    || (segment.confidence != null && segment.confidence < REVIEW_THRESHOLD);
}

function needsSpeakerReview(segment: TranscriptSegment): boolean {
  if (reviewCompleted(segment.speakerReviewState)) return false;
  return (segment.speakerConfidence != null && segment.speakerConfidence < 0.72)
    || (segment.speakerMatchConfidence != null && segment.speakerMatchConfidence < 0.72);
}

function needsReview(segment: TranscriptSegment): boolean {
  return needsTextReview(segment) || needsSpeakerReview(segment);
}

function confidenceTone(confidence: number): "critical" | "warning" | "good" {
  if (confidence < CRITICAL_CONFIDENCE) return "critical";
  if (confidence < REVIEW_THRESHOLD) return "warning";
  return "good";
}

export function TranscriptPanel({ segments, voiceProfiles, currentTimeMs, followPlayback, onFollowChange, onSeek, onEdit, onSpeakerChange, onSpeakerReview, onReplaceAll, onSplit, onMergeNext, onExportMediaEdit, onUndo, onRedo, onGroupParagraphs, canUndo, canRedo, focusMode = false, onFocusMode }: TranscriptPanelProps) {
  const [query, setQuery] = useState("");
  const [replacement, setReplacement] = useState("");
  const [showReplace, setShowReplace] = useState(false);
  const [replaceNotice, setReplaceNotice] = useState("");
  const [mediaEditMode, setMediaEditMode] = useState(false);
  const [excludedIds, setExcludedIds] = useState<Set<string>>(() => new Set());
  const [editing, setEditing] = useState<string | null>(null);
  const [draft, setDraft] = useState("");
  const [speakerDraft, setSpeakerDraft] = useState("");
  const [speakerProfileDraft, setSpeakerProfileDraft] = useState<string | undefined>();
  const [followPaused, setFollowPaused] = useState(false);
  const [reviewOnly, setReviewOnly] = useState(false);
  const listRef = useRef<HTMLDivElement>(null);
  const editorRef = useRef<HTMLTextAreaElement>(null);
  const resumeTimerRef = useRef<number | null>(null);
  const activeIndex = useMemo(() => activeSegmentIndex(segments, currentTimeMs), [segments, currentTimeMs]);
  const followIndex = useMemo(() => followSegmentIndex(segments, currentTimeMs), [segments, currentTimeMs]);
  const followSegmentId = followIndex >= 0 ? segments[followIndex].id : null;
  const uncertainCount = useMemo(() => segments.filter(needsReview).length, [segments]);
  const visible = useMemo(() => segments.filter((segment) => {
    if (reviewOnly && !needsReview(segment)) return false;
    return !query.trim() || segment.text.toLocaleLowerCase().includes(query.toLocaleLowerCase());
  }), [segments, query, reviewOnly]);
  const { profileSpeakerOptions, genericSpeakerOptions } = useMemo(() => {
    const genericNames = new Set(["Hablante 1", "Hablante 2"]);
    const profiles = new Map<string, { id: string; name: string }>();
    for (const segment of segments) {
      if (!segment.speaker) continue;
      if (segment.speakerProfileId) {
        if (voiceProfiles === undefined) {
          profiles.set(segment.speakerProfileId, {
            id: segment.speakerProfileId,
            name: segment.speaker,
          });
        }
      } else {
        genericNames.add(segment.speaker);
      }
    }
    for (const profile of voiceProfiles ?? []) {
      if (profile.enabled) profiles.set(profile.id, { id: profile.id, name: profile.name });
    }
    const duplicateNames = new Map<string, number>();
    for (const profile of profiles.values()) {
      const normalized = profile.name.trim().toLocaleLowerCase();
      duplicateNames.set(normalized, (duplicateNames.get(normalized) ?? 0) + 1);
    }
    const profileOptions: SpeakerOption[] = [...profiles.values()]
      .sort((left, right) => left.name.localeCompare(right.name, "es", { sensitivity: "base" }))
      .map((profile) => {
        const duplicate = (duplicateNames.get(profile.name.trim().toLocaleLowerCase()) ?? 0) > 1;
        return {
          value: `profile:${profile.id}`,
          name: profile.name,
          profileId: profile.id,
          label: duplicate
            ? `${profile.name} · perfil local · ${profile.id.slice(0, 6)}`
            : `${profile.name} · perfil local`,
        };
      });
    const genericOptions: SpeakerOption[] = [...genericNames]
      .sort((left, right) => left.localeCompare(right, "es", { numeric: true }))
      .map((name) => ({
        value: `speaker:${name}`,
        name,
        label: name,
      }));
    return {
      profileSpeakerOptions: profileOptions,
      genericSpeakerOptions: genericOptions,
    };
  }, [segments, voiceProfiles]);
  const speakerOptions = useMemo(
    () => [...profileSpeakerOptions, ...genericSpeakerOptions],
    [genericSpeakerOptions, profileSpeakerOptions],
  );
  const speakerSelection = speakerProfileDraft
    ? `profile:${speakerProfileDraft}`
    : speakerDraft
      ? `speaker:${speakerDraft}`
      : "";
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
    setSpeakerProfileDraft(segment.speakerProfileId);
  }

  function commit() {
    if (editing) {
      const original = segments.find((segment) => segment.id === editing);
      if (original && original.text !== draft) onEdit(editing, draft, true);
      onSpeakerChange?.(editing, speakerDraft || undefined, speakerProfileDraft);
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
          const uncertain = needsReview(segment);
          const textNeedsReview = needsTextReview(segment);
          const speakerNeedsReview = needsSpeakerReview(segment);
          const textTone = segment.confidence == null ? null : confidenceTone(segment.confidence);
          const excluded = excludedIds.has(segment.id);
          const toggleExcluded = () => setExcludedIds((current) => { const next = new Set(current); if (next.has(segment.id)) next.delete(segment.id); else next.add(segment.id); return next; });
          return <article key={segment.id} data-segment-id={segment.id} className={`segment ${active ? "active" : ""} ${uncertain ? `uncertain review-${textTone ?? "warning"}` : ""} ${excluded ? "excluded" : ""}`} tabIndex={0} aria-label={`${mediaEditMode ? excluded ? "Conservar" : "Eliminar de la copia" : "Ir a"} ${formatClock(segment.startMs)}: ${segment.text}`} onKeyDown={(event) => { if ((event.key === "Enter" || event.key === " ") && editing !== segment.id) { event.preventDefault(); if (mediaEditMode) toggleExcluded(); else onSeek(segment.startMs); } }} onClick={() => { if (editing === segment.id) return; if (mediaEditMode) toggleExcluded(); else onSeek(segment.startMs); }}>
            <div className="segment-meta">{mediaEditMode && <input type="checkbox" checked={excluded} onChange={toggleExcluded} onClick={(event) => event.stopPropagation()} aria-label={`Eliminar fragmento de ${formatClock(segment.startMs)}`} />}<button onClick={(event) => { event.stopPropagation(); onSeek(segment.startMs); }}>{formatClock(segment.startMs)}</button>{segment.speaker && <span className={speakerClassName(segment.speaker)}>{segment.speaker}</span>}{segment.speakerProfileId && <span className="voice-profile-badge" title={`Voz reconocida${segment.speakerMatchConfidence ? ` con un ${Math.round(segment.speakerMatchConfidence * 100)} % de similitud` : ""}`}><Fingerprint size={10} />Perfil</span>}{segment.reviewState === "accepted" && <span className="review-state-badge"><Check size={10} />Texto revisado</span>}{segment.reviewState === "corrected" && <span className="review-state-badge"><Check size={10} />Texto corregido</span>}{segment.speakerReviewState === "accepted" && <span className="review-state-badge"><Check size={10} />Voz revisada</span>}{segment.speakerReviewState === "corrected" && <span className="review-state-badge"><Check size={10} />Voz corregida</span>}{textNeedsReview && <button className="review-accept" onClick={(event) => { event.stopPropagation(); onEdit(segment.id, segment.text, true); }} title="Confirmar solamente el texto"><Check size={12} /> Texto correcto</button>}{speakerNeedsReview && onSpeakerReview && <button className="review-accept" onClick={(event) => { event.stopPropagation(); onSpeakerReview(segment.id); }} title="Confirmar solamente la voz"><Check size={12} /> Voz correcta</button>}<button className="edit-segment" onClick={(event) => { event.stopPropagation(); beginEdit(segment); }} aria-label="Editar fragmento"><Edit3 size={14} /></button></div>
            {(segment.confidence != null || segment.speakerConfidence != null || segment.speakerMatchConfidence != null) && <div className="segment-quality" aria-label="Fiabilidad del fragmento">
              {segment.confidence != null && <span data-tone={confidenceTone(segment.confidence)} title="Fiabilidad del texto reconocido"><strong>Texto</strong>{Math.round(segment.confidence * 100)} %</span>}
              {segment.speakerConfidence != null && <span data-tone={confidenceTone(segment.speakerConfidence)} title="Seguridad de que la separación o el cambio de voz es correcto"><strong>Separación de voz</strong>{Math.round(segment.speakerConfidence * 100)} %</span>}
              {segment.speakerMatchConfidence != null && <span data-tone={confidenceTone(segment.speakerMatchConfidence)} title={`Similitud con el perfil local${segment.speakerProvisional ? "; identidad aún provisional" : ""}`}><strong>Identidad</strong>{Math.round(segment.speakerMatchConfidence * 100)} %</span>}
            </div>}
            {editing === segment.id ? <div className="edit-wrap" onClick={(e) => e.stopPropagation()}>{onSpeakerChange && <label className="speaker-editor"><span>Hablante</span><select aria-label="Hablante" value={speakerSelection} onChange={(event) => { const option = speakerOptions.find((item) => item.value === event.target.value); setSpeakerDraft(option?.name ?? ""); setSpeakerProfileDraft(option?.profileId); }}><option value="">Sin identificar</option>{speakerProfileDraft && !profileSpeakerOptions.some((option) => option.profileId === speakerProfileDraft) && <option value={`profile:${speakerProfileDraft}`} disabled>{speakerDraft || "Perfil anterior"} · perfil no disponible</option>}{profileSpeakerOptions.length > 0 && <optgroup label="Perfiles locales">{profileSpeakerOptions.map((speaker) => <option key={speaker.value} value={speaker.value}>{speaker.label}</option>)}</optgroup>}<optgroup label="Etiquetas de esta transcripción">{genericSpeakerOptions.map((speaker) => <option key={speaker.value} value={speaker.value}>{speaker.label}</option>)}</optgroup></select></label>}<textarea ref={editorRef} autoFocus value={draft} onChange={(e) => setDraft(e.target.value)} onKeyDown={(e) => { if (e.key === "Escape") setEditing(null); if ((e.ctrlKey || e.metaKey) && e.key === "Enter") commit(); }} /><div>{onSplit && <button disabled={draft.trim().length < 2} onClick={() => { const position = editorRef.current?.selectionStart ?? Math.round(draft.length / 2); onSplit(segment.id, position, draft); setEditing(null); }} title="Divide el fragmento en la posición del cursor"><Scissors size={14} /> Dividir</button>}{onMergeNext && segment.order < segments.length - 1 && <button onClick={() => { onMergeNext(segment.id); setEditing(null); }}><Link2 size={14} /> Unir siguiente</button>}<button onClick={() => setEditing(null)}><X size={14} /> Cancelar</button><button className="save-edit" onClick={commit}><Check size={14} /> Aplicar</button></div></div> :
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
