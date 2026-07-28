import { useEffect, useMemo, useState } from "react";
import { AlignLeft, BarChart3, BrainCircuit, CheckCircle2, Clock3, Cpu, Lightbulb, ListTree, MessageCircleQuestion, Network, Play, Send, Sparkles, Square, X } from "lucide-react";
import { formatClock } from "../lib/time";
import type { AnalysisProgress, AssistantAnswer, InsightDepth, LocalAiStatus, ProjectInsights } from "../types";

type Tab = "summary" | "points" | "chapters" | "map" | "ask" | "lab";

interface InsightsDialogProps {
  insights: ProjectInsights | null;
  loading: boolean;
  mode: ProjectInsights["mode"];
  depth: InsightDepth;
  progress: AnalysisProgress | null;
  analysisStartedAt: number | null;
  aiStatus: LocalAiStatus | null;
  paragraphCount: number;
  onModeChange: (mode: ProjectInsights["mode"]) => void;
  onDepthChange: (depth: InsightDepth) => void;
  onAnalyze: () => void;
  onCancelAnalysis: () => void;
  onGroupParagraphs: () => void;
  assistantAnswers: AssistantAnswer[];
  assistantLoading: boolean;
  onAsk: (question: string) => void;
  onSeek: (milliseconds: number) => void;
  onClose: () => void;
}

const LAB_FEATURES = [
  ["Diccionario que aprende", "Aprende nombres y términos al corregir texto.", "active"],
  ["Doble motor de revisión", "Turbo transcribe y Large-v3 revisa lo dudoso.", "active"],
  ["Párrafos con contexto", "Une microfragmentos sin perder tiempos ni palabras.", "active"],
  ["Resumen y puntos clave", "Análisis privado con acceso directo al audio original.", "active"],
  ["Capítulos y mapa conceptual", "Estructura conversaciones y contenidos largos.", "active"],
  ["Re-escucha forense", "Comparación automática en fragmentos de baja confianza.", "active"],
  ["Calibrador del ordenador", "Perfiles CPU, GPU, RAM, lote y telemetría local.", "active"],
  ["Búsqueda semántica global", "Buscar una idea en todos los proyectos.", "next"],
  ["Edición de audio por texto", "Cortar contenido seleccionando palabras.", "next"],
  ["Grabación en directo", "Micrófono, texto progresivo y número de hablantes detectado automáticamente.", "active"],
  ["Privacidad y censura", "Detectar datos privados y silenciarlos al exportar.", "next"],
  ["Modo evidencia", "Hash, historial y trazabilidad de cada modificación.", "next"],
  ["Memoria de hablantes", "Reconocer voces conocidas sólo con permiso.", "next"],
  ["Traducción bilingüe", "Subtítulos en dos idiomas conservando sincronía.", "next"],
  ["Generador de contenido", "Actas, tareas, títulos, capítulos y publicaciones.", "base"],
  ["Asistente de calidad de audio", "Detectar ruido, saturación y voz demasiado baja.", "next"],
  ["Proyecto portátil", "Paquete .transcriptor con texto, análisis y ajustes.", "next"],
] as const;

const ASSISTANT_SUGGESTIONS = [
  "¿Cuáles son los puntos clave?",
  "¿Qué tareas quedaron pendientes?",
  "¿Dónde hay desacuerdos o contradicciones?",
] as const;

export function InsightsDialog({ insights, loading, mode, depth, progress, analysisStartedAt, aiStatus, paragraphCount, onModeChange, onDepthChange, onAnalyze, onCancelAnalysis, onGroupParagraphs, assistantAnswers, assistantLoading, onAsk, onSeek, onClose }: InsightsDialogProps) {
  const [tab, setTab] = useState<Tab>("summary");
  const [question, setQuestion] = useState("");
  const [clock, setClock] = useState(() => Date.now());
  const nodes = useMemo(() => layoutConcepts(insights), [insights]);
  const elapsedMs = loading && analysisStartedAt ? Math.max(progress?.elapsedMs ?? 0, clock - analysisStartedAt) : progress?.elapsedMs ?? 0;

  useEffect(() => {
    if (!loading) return;
    const timer = window.setInterval(() => setClock(Date.now()), 1_000);
    return () => window.clearInterval(timer);
  }, [loading]);

  return <div className="modal-backdrop" role="presentation" onMouseDown={(event) => { if (event.target === event.currentTarget) onClose(); }}>
    <section className="insights-dialog" role="dialog" aria-modal="true" aria-labelledby="insights-title">
      <header>
        <div><span>IA LOCAL · PRIVADA</span><h2 id="insights-title"><BrainCircuit size={22} /> Inteligencia de la transcripción</h2><p>Comprende el contenido sin enviar el audio ni el texto fuera del equipo.</p></div>
        <button className="icon-button" onClick={onClose} aria-label="Cerrar análisis"><X size={19} /></button>
      </header>
      <div className="insights-actions">
        <label><span>Tipo de contenido</span><select value={mode} onChange={(event) => onModeChange(event.target.value as ProjectInsights["mode"])}><option value="general">General</option><option value="conversation">Conversación</option><option value="meeting">Reunión</option><option value="interview">Entrevista</option><option value="class">Clase o formación</option><option value="podcast">Podcast</option><option value="personal">Diario personal</option><option value="legal">Declaración / legal</option></select></label>
        <label><span>Profundidad</span><select value={depth} onChange={(event) => onDepthChange(event.target.value as InsightDepth)} disabled={loading}><option value="deep">Profundo · Qwen 3.5</option><option value="quick">Rápido · extractivo</option></select></label>
        <button className="button secondary" onClick={onGroupParagraphs} disabled={loading || paragraphCount < 2}><AlignLeft size={16} /> Agrupar en párrafos</button>
        {loading ? <button className="button danger" onClick={onCancelAnalysis}><Square size={13} fill="currentColor" /> Cancelar análisis</button> : <button className="button primary" onClick={onAnalyze} disabled={paragraphCount === 0 || (depth === "deep" && aiStatus !== null && (!aiStatus.available || !aiStatus.installed))}><Sparkles size={16} /> {insights ? "Actualizar análisis" : "Analizar ahora"}</button>}
      </div>
      <div className="ai-analysis-status" data-state={aiStatus?.available && aiStatus.installed ? "ready" : "waiting"}>
        <div><Cpu size={15} /><span>{aiStatus === null ? "Comprobando IA local…" : aiStatus.available && aiStatus.installed ? `Qwen 3.5 9B listo · Ollama ${aiStatus.version} · procesamiento privado` : "Qwen 3.5 9B no está disponible. Inicia Ollama para usar el análisis profundo."}</span></div>
        {loading && progress ? <div className="analysis-progress" aria-live="polite"><div><strong>{progress.percent}%</strong><span>{progress.message}</span><time>{formatElapsed(elapsedMs)}</time></div><progress max={100} value={progress.percent} /></div> : null}
        {loading && !progress ? <div className="analysis-progress" aria-live="polite"><div><strong>0%</strong><span>Preparando el motor de análisis local…</span><time>{formatElapsed(elapsedMs)}</time></div><progress max={100} value={0} /></div> : null}
      </div>
      <nav className="insights-tabs" aria-label="Secciones del análisis">
        <button className={tab === "summary" ? "active" : ""} onClick={() => setTab("summary")}><Lightbulb size={15} /> Resumen</button>
        <button className={tab === "points" ? "active" : ""} onClick={() => setTab("points")}><ListTree size={15} /> Puntos</button>
        <button className={tab === "chapters" ? "active" : ""} onClick={() => setTab("chapters")}><Clock3 size={15} /> Capítulos</button>
        <button className={tab === "map" ? "active" : ""} onClick={() => setTab("map")}><Network size={15} /> Mapa</button>
        <button className={tab === "ask" ? "active" : ""} onClick={() => setTab("ask")}><MessageCircleQuestion size={15} /> Preguntar</button>
        <button className={tab === "lab" ? "active" : ""} onClick={() => setTab("lab")}><BarChart3 size={15} /> Laboratorio</button>
      </nav>
      <div className="insights-content">
        {!insights && tab !== "lab" && tab !== "ask" ? <div className="insights-empty"><BrainCircuit size={36} /><strong>Convierte la transcripción en conocimiento</strong><p>El modo profundo estudia el contenido por bloques, relaciona el contexto completo y valida las marcas temporales antes de mostrar el resultado.</p></div> : null}
        {insights && tab === "summary" && <div className="summary-view"><div className="summary-copy"><span>RESUMEN EJECUTIVO · {insights.depth === "deep" || insights.method.includes("ollama") ? "IA PROFUNDA" : "ANÁLISIS RÁPIDO"}</span><p>{insights.summary}</p><small>{insights.notice}</small>{insights.processingSeconds ? <em>Procesado localmente en {formatElapsed(insights.processingSeconds * 1000)}</em> : null}</div><div className="analysis-stats"><article><strong>{insights.statistics.wordCount.toLocaleString("es-ES")}</strong><span>palabras</span></article><article><strong>{insights.statistics.paragraphCount}</strong><span>párrafos</span></article><article><strong>{insights.statistics.wordsPerMinute}</strong><span>palabras/min</span></article><article><strong>{insights.signals.questions}</strong><span>preguntas</span></article></div>{insights.mode === "conversation" && <div className="signal-grid"><Signal label="Acuerdos" value={insights.signals.agreements} /><Signal label="Afecto" value={insights.signals.affectionMarkers} /><Signal label="Tensión" value={insights.signals.tensionMarkers} /><Signal label="Preguntas" value={insights.signals.questions} /></div>}</div>}
        {insights && tab === "points" && <div className="insight-list">{insights.keyPoints.map((point) => <article key={point.id}><button onClick={() => onSeek(point.startMs)} aria-label={`Reproducir desde ${formatClock(point.startMs)}`}><Play size={12} /> {formatClock(point.startMs)}</button><div><strong>{point.title}</strong><p>{point.text}</p></div></article>)}</div>}
        {insights && tab === "chapters" && <div className="chapter-list">{insights.chapters.map((chapter, index) => <button key={chapter.id} onClick={() => onSeek(chapter.startMs)}><span>{String(index + 1).padStart(2, "0")}</span><div><strong>{chapter.title}</strong><p>{chapter.description}</p><small>{formatClock(chapter.startMs)} — {formatClock(chapter.endMs)}</small></div><Play size={15} /></button>)}</div>}
        {insights && tab === "map" && <div className="concept-map"><svg viewBox="0 0 760 420" role="img" aria-label="Mapa de relaciones entre los conceptos principales">{insights.conceptEdges.map((edge) => { const left = nodes.get(edge.source); const right = nodes.get(edge.target); return left && right ? <line key={`${edge.source}-${edge.target}`} x1={left.x} y1={left.y} x2={right.x} y2={right.y} strokeWidth={Math.min(5, 1 + edge.weight)} /> : null; })}{[...nodes.entries()].map(([id, node]) => <g key={id} transform={`translate(${node.x} ${node.y})`}><circle r={node.radius} /><text textAnchor="middle" dominantBaseline="middle">{node.label}</text></g>)}</svg><p>Las líneas representan relaciones contextuales encontradas en el contenido; el grosor indica su relevancia.</p></div>}
        {tab === "ask" && <div className="assistant-view">
          <div className="assistant-intro"><MessageCircleQuestion size={24} /><div><strong>Pregunta con pruebas, no con suposiciones</strong><p>La IA responde usando sólo esta transcripción y enlaza cada afirmación con el instante original.</p></div></div>
          <form className="assistant-form" onSubmit={(event) => { event.preventDefault(); const clean = question.trim(); if (!clean || assistantLoading) return; onAsk(clean); setQuestion(""); }}>
            <label htmlFor="transcript-question">Pregunta sobre la conversación</label>
            <div><input id="transcript-question" value={question} onChange={(event) => setQuestion(event.target.value)} placeholder="Ej.: ¿Qué decisiones se tomaron y quién es responsable?" disabled={assistantLoading} /><button className="button primary" disabled={assistantLoading || question.trim().length < 3}><Send size={15} /> Preguntar</button></div>
          </form>
          <div className="assistant-history" aria-live="polite">
            {assistantLoading && <article className="assistant-thinking"><span className="thinking-dots"><i /><i /><i /></span><div><strong>Qwen está contrastando la transcripción</strong><p>Selecciona contexto relevante y valida las citas temporales antes de responder.</p></div></article>}
            {!assistantAnswers.length && !assistantLoading && <div className="assistant-suggestions"><span>Prueba con:</span>{ASSISTANT_SUGGESTIONS.map((suggestion) => <button key={suggestion} onClick={() => setQuestion(suggestion)}>{suggestion}</button>)}</div>}
            {assistantAnswers.map((answer) => <article className="assistant-answer" key={answer.id}><span>PREGUNTA</span><h3>{answer.question}</h3><p>{answer.answer}</p>{answer.citations.length > 0 && <div className="assistant-citations"><strong>Fuentes en el audio</strong>{answer.citations.map((citation) => <button key={`${answer.id}-${citation.segmentId}`} onClick={() => onSeek(citation.startMs)}><Play size={12} /><time>{formatClock(citation.startMs)}</time><span>{citation.excerpt}</span></button>)}</div>}<small>{answer.model} · IA local</small></article>)}
          </div>
        </div>}
        {tab === "lab" && <div className="feature-lab"><div className="lab-intro"><strong>17 capacidades, una sola arquitectura</strong><p>Las funciones activas ya trabajan localmente. Las marcadas como «Siguiente módulo» quedan visibles para desarrollarlas con sus modelos y permisos correctos, sin fingir resultados.</p></div><div className="feature-grid">{LAB_FEATURES.map(([name, description, status]) => <article key={name} className={status}><CheckCircle2 size={16} /><div><strong>{name}</strong><p>{description}</p><span>{status === "active" ? "Activo" : status === "base" ? "Base disponible" : "Siguiente módulo"}</span></div></article>)}</div></div>}
      </div>
    </section>
  </div>;
}

function Signal({ label, value }: { label: string; value: number }) {
  return <article><strong>{value}</strong><span>{label}</span></article>;
}

function formatElapsed(milliseconds: number): string {
  const seconds = Math.max(0, Math.round(milliseconds / 1000));
  return seconds < 60 ? `${seconds} s` : `${Math.floor(seconds / 60)} min ${seconds % 60} s`;
}

function layoutConcepts(insights: ProjectInsights | null): Map<string, { x: number; y: number; radius: number; label: string }> {
  const result = new Map<string, { x: number; y: number; radius: number; label: string }>();
  if (!insights?.concepts.length) return result;
  const maximum = Math.max(...insights.concepts.map((concept) => concept.weight));
  insights.concepts.forEach((concept, index) => {
    const angle = index / insights.concepts.length * Math.PI * 2 - Math.PI / 2;
    const ring = index === 0 ? 0 : index < 6 ? 125 : 185;
    result.set(concept.id, { x: 380 + Math.cos(angle) * ring, y: 210 + Math.sin(angle) * ring, radius: 25 + concept.weight / maximum * 18, label: concept.label.slice(0, 13) });
  });
  return result;
}
