import { useEffect, useState } from "react";
import { AudioWaveform, BrainCircuit, CheckCircle2, Cpu, Download, Gauge, LoaderCircle, MemoryStick, Microchip, RefreshCw, Rocket, ShieldCheck, SlidersHorizontal, Sparkles, UserRoundCheck, Users, WandSparkles, X, Zap } from "lucide-react";
import { engine } from "../lib/engine";
import { buildAutomaticPlan, type AutomaticDecision, type AutomaticPlan } from "../lib/automaticPlan";
import type { AppSettings, EngineEvent, HardwareInfo, PerformanceProfile, QualityMode, SpeakerAiStatus } from "../types";
import { VoiceProfilesSection } from "./VoiceProfilesSection";
import { LocalModelsSection } from "./LocalModelsSection";

interface SettingsDialogProps {
  settings: AppSettings;
  durationMs?: number;
  onChange: (settings: Partial<AppSettings>) => void;
  onClose: () => void;
}

const PROFILE_COPY: Record<PerformanceProfile, { label: string; detail: string }> = {
  balanced: { label: "Equilibrado", detail: "Deja recursos libres para otras aplicaciones" },
  performance: { label: "Rápido", detail: "Usa aproximadamente el 75 % de los hilos" },
  maximum: { label: "Máximo", detail: "Usa todos los hilos y la GPU disponible" },
  custom: { label: "Personalizado", detail: "Tú eliges el límite de CPU" },
};

const QUALITY_COPY: Record<QualityMode, { label: string; detail: string; model: string }> = {
  instant: { label: "Instantáneo", detail: "Turbo por lotes para obtener texto a velocidad extrema", model: "Turbo · borrador rápido" },
  professional: { label: "Profesional IA", detail: "Turbo y segunda revisión Large-v3 sólo donde haya dudas", model: "Turbo + Large-v3" },
  maximum: { label: "Máxima fidelidad", detail: "Large-v3 procesa la grabación completa con beam 5", model: "Large-v3 completo" },
};

function formatMemory(mib: number): string {
  return mib >= 1024 ? `${(mib / 1024).toFixed(1)} GB` : `${Math.round(mib)} MB`;
}

function threadsFor(profile: PerformanceProfile, settings: AppSettings, hardware: HardwareInfo | null): number {
  const logical = hardware?.cpu.logicalCores ?? navigator.hardwareConcurrency ?? 4;
  const physical = hardware?.cpu.physicalCores ?? Math.max(1, Math.ceil(logical / 2));
  if (profile === "balanced") return physical;
  if (profile === "performance") return Math.max(physical, Math.round(logical * 0.75));
  if (profile === "custom") return Math.min(logical, Math.max(1, settings.cpuThreads || physical));
  return logical;
}

export function SettingsDialog({ settings, durationMs = 0, onChange, onClose }: SettingsDialogProps) {
  const [hardware, setHardware] = useState<HardwareInfo | null>(null);
  const [speakerAi, setSpeakerAi] = useState<SpeakerAiStatus | null>(null);
  const [speakerDownload, setSpeakerDownload] = useState<{ downloadedBytes: number; totalBytes: number; percent: number } | null>(null);
  const [speakerError, setSpeakerError] = useState("");
  const [installingSpeakerAi, setInstallingSpeakerAi] = useState(false);
  const [hardwareError, setHardwareError] = useState("");
  const [loading, setLoading] = useState(true);
  const maxThreads = hardware?.cpu.logicalCores ?? navigator.hardwareConcurrency ?? 4;
  const assignedThreads = threadsFor(settings.performanceProfile, settings, hardware);
  const automaticPlan = hardware ? buildAutomaticPlan(hardware, speakerAi, durationMs, settings.voiceProfilesEnabled) : null;

  const refreshHardware = () => {
    setLoading(true);
    setHardwareError("");
    engine.getHardwareInfo()
      .then(setHardware)
      .catch((error) => setHardwareError(error instanceof Error ? error.message : String(error)))
      .finally(() => setLoading(false));
  };

  useEffect(() => {
    let active = true;
    Promise.allSettled([engine.getHardwareInfo(), engine.getSpeakerAiStatus()]).then(([hardwareResult, speakerResult]) => {
      if (!active) return;
      if (hardwareResult.status === "fulfilled") setHardware(hardwareResult.value);
      else setHardwareError(hardwareResult.reason instanceof Error ? hardwareResult.reason.message : String(hardwareResult.reason));
      if (speakerResult.status === "fulfilled") setSpeakerAi(speakerResult.value);
      else setSpeakerError(speakerResult.reason instanceof Error ? speakerResult.reason.message : String(speakerResult.reason));
      setLoading(false);
    });
    const unsubscribe = engine.subscribe((event: EngineEvent) => {
      if (!active) return;
      if (event.type === "speaker_model_progress") {
        const payload = event.payload as { downloadedBytes: number; totalBytes: number; percent: number };
        setSpeakerDownload(payload);
        setInstallingSpeakerAi(true);
      }
      if (event.type === "speaker_model_completed") {
        setSpeakerAi(event.payload as SpeakerAiStatus);
        setSpeakerDownload(null);
        setInstallingSpeakerAi(false);
        setSpeakerError("");
      }
      if (event.type === "speaker_model_failed" || event.type === "speaker_model_cancelled") {
        const payload = event.payload as { message?: string };
        setSpeakerError(payload.message ?? (event.type === "speaker_model_cancelled" ? "Descarga cancelada." : "No se pudo instalar la IA de hablantes."));
        setSpeakerDownload(null);
        setInstallingSpeakerAi(false);
      }
    });
    return () => { active = false; unsubscribe(); };
  }, []);

  function selectProfile(profile: PerformanceProfile) {
    const cpuThreads = threadsFor(profile, settings, hardware);
    onChange({ performanceProfile: profile, cpuThreads });
  }

  function selectQuality(qualityMode: QualityMode) {
    onChange({ qualityMode, defaultModel: qualityMode === "maximum" ? "large-v3" : "turbo" });
  }

  function selectExperienceMode(experienceMode: AppSettings["experienceMode"]) {
    if (experienceMode === "simple") {
      onChange({
        ...(automaticPlan?.settings ?? {}),
        experienceMode,
        device: "auto",
        audioEnhancement: "adaptive",
        diarizationMode: speakerAi?.ready ? "neural" : "adaptive",
        speakerCountMode: "auto",
        speakerCount: 8,
        speakerSensitivity: 55,
      });
      return;
    }
    onChange({ experienceMode });
  }

  async function installSpeakerModel() {
    const accepted = window.confirm("Se descargarán unos 27 MB desde el repositorio oficial de 3D-Speaker. El modelo quedará en este equipo y se usará sin subir audio. ¿Continuar?");
    if (!accepted) return;
    setInstallingSpeakerAi(true);
    setSpeakerError("");
    try {
      await engine.installSpeakerAi();
    } catch (error) {
      setInstallingSpeakerAi(false);
      setSpeakerError(error instanceof Error ? error.message : String(error));
    }
  }

  return <div className="modal-backdrop" onMouseDown={onClose}>
    <section className={`settings-dialog performance-dialog ${settings.experienceMode === "simple" ? "simple-mode" : "advanced-mode"}`} role="dialog" aria-modal="true" aria-labelledby="settings-title" onMouseDown={(event) => event.stopPropagation()}>
      <header>
        <div><span>Configuración local</span><h2 id="settings-title">Ajustes de Transcriptor</h2><p>{settings.experienceMode === "simple" ? "Modelos, rendimiento, voces y preferencias en un único lugar." : "Configura manualmente modelos, motor, voces, latencia y preferencias."}</p></div>
        <button className="icon-button" onClick={onClose} aria-label="Cerrar"><X /></button>
      </header>

      <div className="settings-scroll">
        <nav className="experience-switch" aria-label="Nivel de configuración">
          <button className={settings.experienceMode === "simple" ? "selected" : ""} onClick={() => selectExperienceMode("simple")} aria-pressed={settings.experienceMode === "simple"}>
            <WandSparkles size={18} /><span><strong>Sencillo</strong><small>Todo recomendado y automático</small></span>
          </button>
          <button className={settings.experienceMode === "advanced" ? "selected" : ""} onClick={() => selectExperienceMode("advanced")} aria-pressed={settings.experienceMode === "advanced"}>
            <SlidersHorizontal size={18} /><span><strong>Avanzado</strong><small>Control de motor, voces y latencia</small></span>
          </button>
        </nav>

        <LocalModelsSection />

        {settings.experienceMode === "simple" ? <AutomaticPlanPanel plan={automaticPlan} loading={loading} hardwareError={hardwareError} /> : null}

        <section className="hardware-section" aria-labelledby="hardware-title">
          <div className="section-heading"><div><span>DETECTADO EN ESTE EQUIPO</span><strong id="hardware-title">Capacidad disponible</strong></div><button className="refresh-hardware" onClick={refreshHardware} disabled={loading}><RefreshCw size={13} className={loading ? "spin" : ""} />Actualizar</button></div>
          {hardware ? <div className="hardware-grid">
            <article><Cpu /><div><small>PROCESADOR</small><strong>{hardware.cpu.name}</strong><span>{hardware.cpu.physicalCores} núcleos · {hardware.cpu.logicalCores} hilos · uso actual {hardware.cpu.usagePercent.toFixed(0)} %</span></div></article>
            <article><MemoryStick /><div><small>MEMORIA</small><strong>{formatMemory(hardware.memory.totalMiB)} RAM</strong><span>{formatMemory(hardware.memory.availableMiB)} disponibles · {hardware.memory.usagePercent.toFixed(0)} % en uso</span></div></article>
            <article className={!hardware.gpu ? "unavailable" : ""}><Microchip /><div><small>GRÁFICA</small><strong>{hardware.gpu?.name ?? "No se detectó una GPU NVIDIA"}</strong><span>{hardware.gpu ? `${formatMemory(hardware.gpu.totalVramMiB)} VRAM · ${hardware.cudaAvailable ? "CUDA disponible" : "CUDA no disponible"}` : "Se utilizará el procesador"}</span></div></article>
          </div> : <div className="hardware-loading">{hardwareError || "Detectando CPU, memoria y GPU…"}</div>}
        </section>

        <section className="speaker-ai-section" aria-labelledby="speaker-ai-title">
          <div className="section-heading"><div><span>IDENTIDAD DE VOZ · 100 % LOCAL</span><strong id="speaker-ai-title">IA especializada en hablantes</strong></div><output className={speakerAi?.ready ? "ready" : ""}>{speakerAi?.ready ? "CAM++ listo" : "Modelo opcional · 27 MB"}</output></div>
          <div className={`speaker-ai-card ${speakerAi?.ready ? "ready" : ""}`}>
            <span className="speaker-ai-icon"><Users /></span>
            <div>
              <strong>{speakerAi?.ready ? "Separación neuronal activada" : "Mejora la separación entre voces"}</strong>
              <p>{speakerAi?.ready ? "Cada fragmento se convierte en una huella acústica de 192 dimensiones. El audio y las huellas no salen del ordenador." : "CAM++ distingue timbre, resonancia, prosodia y características vocales. Si no se instala, seguirá disponible el método acústico compatible."}</p>
              {speakerDownload && <div className="speaker-download" role="progressbar" aria-valuemin={0} aria-valuemax={100} aria-valuenow={speakerDownload.percent}><i><b style={{ width: `${speakerDownload.percent}%` }} /></i><small>{speakerDownload.percent.toFixed(0)} % · {(speakerDownload.downloadedBytes / 1_048_576).toFixed(1)} de {(speakerDownload.totalBytes / 1_048_576).toFixed(1)} MB</small></div>}
              {speakerError && <small className="speaker-error">{speakerError}</small>}
            </div>
            {!speakerAi?.ready && <button className="button secondary" disabled={installingSpeakerAi} onClick={() => void installSpeakerModel()}>{installingSpeakerAi ? <LoaderCircle className="spin" size={15} /> : <Download size={15} />}{installingSpeakerAi ? "Instalando…" : "Instalar IA"}</button>}
            {speakerAi?.ready && <CheckCircle2 className="speaker-ready-check" />}
          </div>
          {settings.experienceMode === "advanced" && <div className="speaker-advanced-grid">
            <label><span>Número de voces<small>Automático estima cuántas personas existen usando sus huellas vocales.</small></span><select value={settings.speakerCountMode} onChange={(event) => onChange({ speakerCountMode: event.target.value as AppSettings["speakerCountMode"] })}><option value="auto">Automático · recomendado</option><option value="exact">Exactamente</option></select></label>
            <label><span>{settings.speakerCountMode === "exact" ? "Número de hablantes" : "Máximo de hablantes"}<small>{settings.speakerCountMode === "exact" ? "Fuerza esa cantidad cuando la conoces de antemano." : "Evita crear más perfiles que personas esperadas."}</small></span><select value={settings.speakerCount} onChange={(event) => onChange({ speakerCount: Number(event.target.value) })}>{[1, 2, 3, 4, 5, 6, 7, 8].map((count) => <option key={count} value={count}>{count} hablante{count === 1 ? "" : "s"}</option>)}</select></label>
            <label className="speaker-sensitivity"><span>Sensibilidad al cambio de voz<small>Bájala si mezcla personas; súbela si divide demasiado a la misma persona.</small></span><div><input type="range" min={20} max={90} value={settings.speakerSensitivity} onChange={(event) => onChange({ speakerSensitivity: Number(event.target.value) })} /><output>{settings.speakerSensitivity}</output></div></label>
            <label><span>Latencia en directo<small>Menos retardo usa bloques más pequeños y puede perder algo de contexto.</small></span><select value={settings.liveLatency} onChange={(event) => onChange({ liveLatency: event.target.value as AppSettings["liveLatency"] })}><option value="ultra">Ultrabaja · 0,6–1,1 s</option><option value="balanced">Equilibrada · 0,8–1,5 s</option><option value="stable">Estable · 1,1–2,2 s</option></select></label>
          </div>}
          <VoiceProfilesSection settings={settings} advanced={settings.experienceMode === "advanced"} onChange={onChange} />
        </section>

        <section className="quality-section advanced-only" aria-labelledby="quality-title">
          <div className="section-heading"><div><span>INTELIGENCIA ARTIFICIAL LOCAL</span><strong id="quality-title">Calidad de transcripción</strong></div><output>{QUALITY_COPY[settings.qualityMode].model}</output></div>
          <div className="quality-grid">
            {(Object.keys(QUALITY_COPY) as QualityMode[]).map((mode) => <button key={mode} className={settings.qualityMode === mode ? "selected" : ""} onClick={() => selectQuality(mode)} aria-pressed={settings.qualityMode === mode}>
              {mode === "instant" ? <Rocket /> : mode === "professional" ? <Sparkles /> : <BrainCircuit />}
              <div><strong>{QUALITY_COPY[mode].label}</strong><span>{QUALITY_COPY[mode].detail}</span><small>{QUALITY_COPY[mode].model}</small></div>
            </button>)}
          </div>
          <div className="quality-options">
            <label><span>Revisión inteligente<small>Large-v3 vuelve a escuchar únicamente fragmentos de baja confianza</small></span><input type="checkbox" checked={settings.reviewLowConfidence} disabled={settings.qualityMode !== "professional"} onChange={(event) => onChange({ reviewLowConfidence: event.target.checked })} /></label>
            <label><span>Lote instantáneo<small>Más lote utiliza más VRAM; 8 es adecuado para tu GPU</small></span><select value={settings.batchSize} disabled={settings.qualityMode !== "instant"} onChange={(event) => onChange({ batchSize: Number(event.target.value) })}><option value={2}>2 · conservador</option><option value={4}>4 · equilibrado</option><option value={8}>8 · máximo</option></select></label>
            <label><span>Restauración de voz<small>Analiza ruido, volumen y silencios antes de transcribir</small></span><select value={settings.audioEnhancement} onChange={(event) => onChange({ audioEnhancement: event.target.value as AppSettings["audioEnhancement"] })}><option value="adaptive">Adaptativa · recomendado</option><option value="off">Sin procesar</option><option value="speech">Limpieza suave</option><option value="strong">Ruido intenso</option></select></label>
            <label><span>Separación de hablantes<small>CAM++ compara huellas neuronales; si falta, vuelve al motor acústico.</small></span><select value={settings.diarizationMode} onChange={(event) => onChange({ diarizationMode: event.target.value as AppSettings["diarizationMode"] })}><option value="neural">Neuronal CAM++ · recomendado</option><option value="adaptive">Híbrida automática</option><option value="channels">Por canales estéreo</option><option value="off">Desactivada</option></select></label>
          </div>
        </section>

        <section className="profile-section advanced-only" aria-labelledby="profile-title">
          <div className="section-heading"><div><span>RECURSOS DEL MOTOR</span><strong id="profile-title">Perfil de rendimiento</strong></div><output>{assignedThreads} de {maxThreads} hilos</output></div>
          <div className="profile-grid">
            {(Object.keys(PROFILE_COPY) as PerformanceProfile[]).map((profile) => <button key={profile} className={settings.performanceProfile === profile ? "selected" : ""} onClick={() => selectProfile(profile)} aria-pressed={settings.performanceProfile === profile}>
              {profile === "maximum" ? <Zap /> : profile === "custom" ? <Gauge /> : <Cpu />}
              <strong>{PROFILE_COPY[profile].label}</strong><span>{PROFILE_COPY[profile].detail}</span><small>{threadsFor(profile, settings, hardware)} hilos</small>
            </button>)}
          </div>
          {settings.performanceProfile === "custom" && <label className="thread-slider">
            <span><strong>Límite de CPU</strong><small>Más hilos suele acelerar la transcripción, pero deja menos capacidad para otras tareas.</small></span>
            <div><input aria-label="Hilos de CPU" type="range" min={1} max={maxThreads} value={assignedThreads} onChange={(event) => onChange({ cpuThreads: Number(event.target.value) })} /><output>{assignedThreads}</output></div>
          </label>}
          <div className="resource-controls">
            <label><span>Motor de cálculo<small>Automático prioriza CUDA y vuelve a CPU si falla</small></span><select value={settings.device} onChange={(event) => onChange({ device: event.target.value as AppSettings["device"] })}><option value="auto">Automático · recomendado</option><option value="cuda" disabled={Boolean(hardware && !hardware.cudaAvailable)}>GPU CUDA</option><option value="cpu">Sólo CPU</option></select></label>
            <label><span>Prioridad de Windows<small>“Alta” puede reducir la respuesta de otras aplicaciones</small></span><select value={settings.processPriority} onChange={(event) => onChange({ processPriority: event.target.value as AppSettings["processPriority"] })}><option value="normal">Normal · recomendado</option><option value="high">Alta</option></select></label>
          </div>
          <p className="resource-note"><ShieldCheck size={14} />La memoria RAM y la VRAM se reservan automáticamente según el modelo. Forzar una cantidad no acelera el cálculo y podría provocar errores.</p>
        </section>

        <section className="general-section" aria-labelledby="general-title">
          <div className="section-heading"><div><span>GENERAL</span><strong id="general-title">Transcripción y aplicación</strong></div></div>
          <div className="setting-grid">
            <label><span>Idioma<small>Se aplicará también al proyecto abierto y al modo en directo</small></span><select value={settings.defaultLanguage} onChange={(event) => onChange({ defaultLanguage: event.target.value })}><option value="es">Español</option><option value="en">Inglés</option><option value="fr">Francés</option><option value="de">Alemán</option><option value="it">Italiano</option><option value="pt">Portugués</option><option value="ca">Catalán</option><option value="gl">Gallego</option><option value="auto">Detección automática</option></select></label>
            <label><span>Tema<small>Apariencia de la aplicación</small></span><select value={settings.theme} onChange={(event) => onChange({ theme: event.target.value as AppSettings["theme"] })}><option value="system">Usar el sistema</option><option value="dark">Oscuro</option><option value="light">Claro</option></select></label>
            <label><span>Salto del reproductor<small>Segundos con ← y →</small></span><input type="number" min={2} max={60} value={settings.skipSeconds} onChange={(event) => onChange({ skipSeconds: Number(event.target.value) })} /></label>
            <label><span>Guardado automático<small>Intervalo en segundos</small></span><input type="number" min={1} max={60} value={settings.autosaveSeconds} onChange={(event) => onChange({ autosaveSeconds: Number(event.target.value) })} /></label>
            <label><span>Párrafos contextuales<small>Une las líneas breves conservando sus tiempos</small></span><input type="checkbox" checked={settings.paragraphMode} onChange={(event) => onChange({ paragraphMode: event.target.checked })} /></label>
            <label><span>Duración por párrafo<small>Máximo antes de iniciar un bloque nuevo</small></span><select value={settings.maxParagraphSeconds} disabled={!settings.paragraphMode} onChange={(event) => onChange({ maxParagraphSeconds: Number(event.target.value) })}><option value={25}>25 segundos</option><option value={42}>42 segundos</option><option value={60}>60 segundos</option></select></label>
            <label><span>Longitud de subtítulo<small>Caracteres aproximados por línea</small></span><select value={settings.subtitleLineLength} onChange={(event) => onChange({ subtitleLineLength: Number(event.target.value) })}><option value={32}>32 · móvil</option><option value={42}>42 · estándar</option><option value={52}>52 · amplio</option></select></label>
            <label><span>Líneas de subtítulo<small>El exportador divide automáticamente los bloques largos</small></span><select value={settings.subtitleMaxLines} onChange={(event) => onChange({ subtitleMaxLines: Number(event.target.value) })}><option value={1}>1 línea</option><option value={2}>2 líneas</option><option value={3}>3 líneas</option></select></label>
          </div>
        </section>
      </div>
      <footer><p>Todo se procesa localmente. Las estadísticas sólo se muestran en pantalla y no se envían.</p><button className="button primary" onClick={onClose}>Guardar y cerrar</button></footer>
    </section>
  </div>;
}

function AutomaticPlanPanel({ plan, loading, hardwareError }: { plan: AutomaticPlan | null; loading: boolean; hardwareError: string }) {
  if (!plan) {
    return <section className="automatic-plan loading" role="status">
      <span className="automatic-plan-orbit">{loading ? <Sparkles size={18} /> : <ShieldCheck size={18} />}<i /><i /></span>
      <div><strong>{loading ? "Calculando el mejor plan para este equipo…" : "Piloto automático seguro disponible"}</strong><p>{loading ? "Midiendo CPU, memoria, GPU y disponibilidad de la IA de voces." : "Se volverá a medir el hardware al comenzar la transcripción y, si no responde, se usará una configuración compatible."}</p></div>
      {loading ? <LoaderCircle className="spin" size={18} /> : null}
      {!loading && hardwareError ? <span className="sr-only">{hardwareError}</span> : null}
    </section>;
  }
  return <section className={`automatic-plan ${plan.tier}`} aria-labelledby="automatic-plan-title">
    <header>
      <span className="automatic-plan-orbit"><WandSparkles size={19} /><i /><i /></span>
      <div><small>AUTOMATIZACIÓN ADAPTATIVA</small><strong id="automatic-plan-title">{plan.title}</strong><p>{plan.summary}</p></div>
      <output><CheckCircle2 size={14} /> Listo</output>
    </header>
    <div className="automatic-plan-grid">
      {plan.decisions.map((decision) => <article key={decision.id}>
        <span>{automaticDecisionIcon(decision)}</span>
        <div><small>{decision.label}</small><strong>{decision.value}</strong><p>{decision.detail}</p></div>
        <CheckCircle2 size={14} aria-label="Activado automáticamente" />
      </article>)}
    </div>
    <footer><ShieldCheck size={14} /><span>Se vuelve a calcular al comenzar cada archivo según su duración y la capacidad disponible en ese momento.</span></footer>
  </section>;
}

function automaticDecisionIcon(decision: AutomaticDecision) {
  if (decision.id === "compute") return <Cpu size={17} />;
  if (decision.id === "transcription") return <BrainCircuit size={17} />;
  if (decision.id === "audio") return <AudioWaveform size={17} />;
  if (decision.id === "speakers") return <Users size={17} />;
  if (decision.id === "profiles") return <UserRoundCheck size={17} />;
  return <Zap size={17} />;
}
