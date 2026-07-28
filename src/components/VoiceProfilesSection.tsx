import { useEffect, useRef, useState } from "react";
import type { CSSProperties } from "react";
import { ArrowRight, Check, Fingerprint, GitMerge, LoaderCircle, Pause, Play, ShieldCheck, Trash2, UsersRound, X } from "lucide-react";
import { engine } from "../lib/engine";
import type { AppSettings, EngineEvent, VoiceProfile, VoiceProfileCatalog, VoiceProfileComparison } from "../types";

interface VoiceProfilesSectionProps {
  settings: AppSettings;
  advanced: boolean;
  onChange: (settings: Partial<AppSettings>) => void;
}

function formatLearnedTime(milliseconds: number): string {
  const seconds = Math.round(milliseconds / 1000);
  if (seconds < 60) return `${seconds} s aprendidos`;
  return `${Math.floor(seconds / 60)} min ${seconds % 60} s aprendidos`;
}

function formatLastSeen(value?: string | null): string {
  if (!value) return "Todavía sin coincidencias";
  const date = new Date(value);
  return Number.isNaN(date.valueOf())
    ? "Coincidencia reciente"
    : `Última coincidencia: ${date.toLocaleDateString("es-ES", { day: "2-digit", month: "short" })}`;
}

export function VoiceProfilesSection({ settings, advanced, onChange }: VoiceProfilesSectionProps) {
  const [catalog, setCatalog] = useState<VoiceProfileCatalog | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [busyId, setBusyId] = useState("");
  const [learningNotice, setLearningNotice] = useState("");
  const [mergeSourceId, setMergeSourceId] = useState("");
  const [mergeTargetId, setMergeTargetId] = useState("");
  const [comparison, setComparison] = useState<VoiceProfileComparison | null>(null);
  const [comparisonLoading, setComparisonLoading] = useState(false);
  const comparisonToken = useRef(0);
  const mergeSource = catalog?.profiles.find((profile) => profile.id === mergeSourceId) ?? null;
  const mergeTarget = catalog?.profiles.find((profile) => profile.id === mergeTargetId) ?? null;

  useEffect(() => {
    let active = true;
    engine.listVoiceProfiles()
      .then((result) => { if (active) setCatalog(result); })
      .catch((reason) => { if (active) setError(reason instanceof Error ? reason.message : String(reason)); })
      .finally(() => { if (active) setLoading(false); });
    const unsubscribe = engine.subscribe((event: EngineEvent) => {
      if (!active || event.type !== "voice_profiles_updated") return;
      const updated = event.payload as VoiceProfileCatalog;
      setCatalog(updated);
      if (updated.learnedSamples !== undefined) {
        const created = updated.createdProfiles?.length ?? 0;
        setLearningNotice(updated.learnedSamples > 0
          ? `${updated.learnedSamples} fragmentos vocales incorporados · ${created} ${created === 1 ? "perfil nuevo" : "perfiles nuevos"}.`
          : `No se guardaron muestras: ${updated.rejectedSamples ?? 0} fragmentos no alcanzaron la calidad mínima.`);
      }
      setLoading(false);
      setError("");
    });
    return () => { active = false; unsubscribe(); };
  }, []);

  function setProfilesEnabled(enabled: boolean) {
    if (enabled) {
      const accepted = window.confirm(
        "Transcriptor guardará huellas matemáticas de voz para reconocer a las mismas personas en otras conversaciones. " +
        "En Windows se cifran para tu cuenta con DPAPI. No se copian fragmentos de audio ni texto y puedes pausar o borrar cada perfil. ¿Activar?",
      );
      if (!accepted) return;
    }
    onChange({ voiceProfilesEnabled: enabled });
  }

  async function updateProfile(profile: VoiceProfile, changes: { name?: string; enabled?: boolean; matchThreshold?: number }) {
    setBusyId(profile.id);
    setError("");
    try {
      const updated = await engine.updateVoiceProfile(profile.id, changes);
      setCatalog((current) => current
        ? { ...current, profiles: current.profiles.map((item) => item.id === updated.id ? updated : item) }
        : current);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : String(reason));
    } finally {
      setBusyId("");
    }
  }

  async function deleteProfile(profile: VoiceProfile) {
    const accepted = window.confirm(
      `¿Olvidar la voz de “${profile.name}”? Se borrarán sus huellas cifradas. Las transcripciones existentes conservarán el nombre escrito.`,
    );
    if (!accepted) return;
    setBusyId(profile.id);
    setError("");
    try {
      await engine.deleteVoiceProfile(profile.id);
      setCatalog((current) => current
        ? { ...current, profiles: current.profiles.filter((item) => item.id !== profile.id) }
        : current);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : String(reason));
    } finally {
      setBusyId("");
    }
  }

  function openMerge(profile: VoiceProfile) {
    comparisonToken.current += 1;
    setMergeSourceId(profile.id);
    setMergeTargetId("");
    setComparison(null);
    setComparisonLoading(false);
    setError("");
  }

  function closeMerge() {
    comparisonToken.current += 1;
    setMergeSourceId("");
    setMergeTargetId("");
    setComparison(null);
    setComparisonLoading(false);
  }

  async function selectMergeTarget(targetId: string) {
    const token = comparisonToken.current + 1;
    comparisonToken.current = token;
    setMergeTargetId(targetId);
    setComparison(null);
    setError("");
    if (!mergeSource || !targetId) {
      setComparisonLoading(false);
      return;
    }
    setComparisonLoading(true);
    try {
      const result = await engine.compareVoiceProfiles(mergeSource.id, targetId);
      if (comparisonToken.current === token) setComparison(result);
    } catch (reason) {
      if (comparisonToken.current === token) {
        setError(reason instanceof Error ? reason.message : String(reason));
      }
    } finally {
      if (comparisonToken.current === token) setComparisonLoading(false);
    }
  }

  async function mergeProfiles() {
    if (!mergeSource || !mergeTarget) return;
    const accepted = window.confirm(
      `¿Fusionar “${mergeSource.name}” dentro de “${mergeTarget.name}”? ` +
      `“${mergeSource.name}” desaparecerá como perfil independiente y sus huellas cifradas se incorporarán a “${mergeTarget.name}”.`,
    );
    if (!accepted) return;
    setBusyId(mergeSource.id);
    setError("");
    try {
      const result = await engine.mergeVoiceProfiles(mergeSource.id, mergeTarget.id);
      setCatalog(result.catalog);
      setLearningNotice(
        `Perfiles fusionados: “${result.sourceName}” ahora forma parte de “${result.targetName}”. ` +
        `${result.retainedSamples} fragmentos y ${result.updatedSegments} segmentos vinculados actualizados.`,
      );
      closeMerge();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : String(reason));
    } finally {
      setBusyId("");
    }
  }

  return <section className="voice-profiles" aria-labelledby="voice-profiles-title">
    <div className="voice-profiles-heading">
      <div className="voice-profiles-title">
        <span className="voice-profiles-icon"><Fingerprint /></span>
        <div>
          <small>HABLANTES CONOCIDOS</small>
          <strong id="voice-profiles-title">Memoria local de voces</strong>
          <p>Aprende el timbre en fragmentos claros y reutiliza el nombre en futuras conversaciones.</p>
        </div>
      </div>
      <button
        type="button"
        className={`voice-memory-toggle ${settings.voiceProfilesEnabled ? "enabled" : ""}`}
        aria-pressed={settings.voiceProfilesEnabled}
        onClick={() => setProfilesEnabled(!settings.voiceProfilesEnabled)}
      >
        {settings.voiceProfilesEnabled ? <><Check />Activada</> : "Activar"}
      </button>
    </div>

    {settings.voiceProfilesEnabled && <div className="voice-learning-options">
      <label>
        <span><strong>Seguir aprendiendo</strong><small>Añade sólo fragmentos claros y nunca conserva el audio del recorte.</small></span>
        <input type="checkbox" checked={settings.voiceProfileAutoLearn} onChange={(event) => onChange({ voiceProfileAutoLearn: event.target.checked })} />
      </label>
      {advanced && <label>
        <span><strong>Calidad mínima del fragmento</strong><small>Más alto aprende más despacio, pero evita contaminar un perfil con otra voz.</small></span>
        <div className="voice-confidence-control">
          <input type="range" min={60} max={90} value={settings.voiceProfileMinConfidence} onChange={(event) => onChange({ voiceProfileMinConfidence: Number(event.target.value) })} />
          <output>{settings.voiceProfileMinConfidence} %</output>
        </div>
      </label>}
    </div>}
    {learningNotice ? <p className="voice-learning-notice" role="status"><Check />{learningNotice}</p> : null}

    {mergeSource && catalog && <section className="voice-merge-panel" role="dialog" aria-labelledby="voice-merge-title">
      <header>
        <span className="voice-merge-icon"><GitMerge /></span>
        <div>
          <small>CORREGIR IDENTIDAD</small>
          <strong id="voice-merge-title">Fusionar “{mergeSource.name}”</strong>
          <p>Elige la identidad que quieres conservar. Sumaremos sus huellas y corregiremos los segmentos enlazados.</p>
        </div>
        <button type="button" className="voice-merge-close" onClick={closeMerge} aria-label="Cancelar fusión"><X /></button>
      </header>
      <div className="voice-merge-flow">
        <article style={{ "--voice-color": mergeSource.color } as CSSProperties}>
          <span className="voice-avatar">{mergeSource.name.slice(0, 2).toUpperCase()}</span>
          <div><small>SE ABSORBE</small><strong>{mergeSource.name}</strong><p>{mergeSource.sampleCount} fragmentos</p></div>
        </article>
        <ArrowRight className="voice-merge-arrow" aria-hidden="true" />
        <label>
          <span>Conservar este perfil</span>
          <select
            aria-label={`Perfil que conservará a ${mergeSource.name}`}
            value={mergeTargetId}
            disabled={busyId === mergeSource.id}
            onChange={(event) => void selectMergeTarget(event.target.value)}
          >
            <option value="">Elige la identidad correcta…</option>
            {catalog.profiles.filter((profile) => profile.id !== mergeSource.id).map((profile) =>
              <option key={profile.id} value={profile.id}>{profile.name} · {profile.sampleCount} fragmentos</option>
            )}
          </select>
        </label>
      </div>
      {comparisonLoading && <div className="voice-merge-comparison loading" role="status"><LoaderCircle />Comparando timbres cifrados…</div>}
      {comparison && mergeTarget && <div className={`voice-merge-comparison ${comparison.verdict}`}>
        <div>
          <small>SIMILITUD ACÚSTICA</small>
          <strong>{comparison.similarity === null ? "Sin datos suficientes" : `${Math.round(comparison.similarity * 100)} %`}</strong>
        </div>
        <span>
          {comparison.verdict === "alta" && "Coincidencia fuerte: la fusión parece coherente."}
          {comparison.verdict === "compatible" && "Coincidencia compatible: revisa los nombres y confirma."}
          {comparison.verdict === "baja" && "Similitud baja: podrían ser personas distintas."}
          {comparison.verdict === "sin_datos" && "Puedes fusionarlos manualmente, pero aún no hay huella suficiente para compararlos."}
        </span>
        {comparison.similarity !== null && <div className="voice-merge-meter" aria-hidden="true"><i style={{ width: `${Math.max(0, Math.min(100, comparison.similarity * 100))}%` }} /></div>}
      </div>}
      <footer>
        <p>La identidad conservada será “{mergeTarget?.name ?? "la que elijas"}”. No se guarda ni copia audio.</p>
        <button type="button" className="button" onClick={closeMerge} disabled={busyId === mergeSource.id}>Cancelar</button>
        <button type="button" className="button primary" onClick={() => void mergeProfiles()} disabled={!mergeTarget || comparisonLoading || busyId === mergeSource.id}>
          {busyId === mergeSource.id ? <LoaderCircle className="voice-merge-spinner" /> : <GitMerge />}
          {mergeTarget ? `Fusionar en ${mergeTarget.name}` : "Selecciona un destino"}
        </button>
      </footer>
    </section>}

    {loading && <div className="voice-profiles-state">Leyendo perfiles cifrados…</div>}
    {!loading && catalog?.profiles.length === 0 && <div className="voice-profiles-empty">
      <span><UsersRound /></span>
      <div><strong>Aún no hay voces guardadas</strong><p>Activa la memoria y transcribe una conversación. Crearemos “Hablante 1”, “Hablante 2” y los que hagan falta; después sólo tendrás que poner sus nombres.</p></div>
    </div>}
    {catalog && catalog.profiles.length > 0 && <div className="voice-profile-list">
      {catalog.profiles.map((profile) => <VoiceProfileRow
        key={`${profile.id}:${profile.updatedAt}`}
        profile={profile}
        advanced={advanced}
        busy={busyId === profile.id}
        canMerge={catalog.profiles.length > 1}
        onUpdate={(changes) => void updateProfile(profile, changes)}
        onMerge={() => openMerge(profile)}
        onDelete={() => void deleteProfile(profile)}
      />)}
    </div>}
    {error && <p className="voice-profile-error" role="alert">{error}</p>}
    <p className="voice-profile-privacy"><ShieldCheck />{catalog?.encryption ?? "Protección local"} · sin muestras de audio · sin nube</p>
  </section>;
}

interface VoiceProfileRowProps {
  profile: VoiceProfile;
  advanced: boolean;
  busy: boolean;
  canMerge: boolean;
  onUpdate: (changes: { name?: string; enabled?: boolean; matchThreshold?: number }) => void;
  onMerge: () => void;
  onDelete: () => void;
}

function VoiceProfileRow({ profile, advanced, busy, canMerge, onUpdate, onMerge, onDelete }: VoiceProfileRowProps) {
  const [name, setName] = useState(profile.name);
  const [threshold, setThreshold] = useState(Math.round(profile.matchThreshold * 100));

  function saveName() {
    const trimmed = name.trim();
    if (!trimmed) {
      setName(profile.name);
      return;
    }
    if (trimmed !== profile.name) onUpdate({ name: trimmed });
  }

  return <article className={`voice-profile-row ${profile.enabled ? "" : "paused"}`} style={{ "--voice-color": profile.color } as CSSProperties}>
    <span className="voice-avatar" aria-hidden="true">{profile.name.slice(0, 2).toUpperCase()}</span>
    <div className="voice-profile-main">
      <input
        aria-label={`Nombre de ${profile.name}`}
        value={name}
        maxLength={40}
        disabled={busy}
        onChange={(event) => setName(event.target.value)}
        onBlur={saveName}
        onKeyDown={(event) => {
          if (event.key === "Enter") event.currentTarget.blur();
          if (event.key === "Escape") { setName(profile.name); event.currentTarget.blur(); }
        }}
      />
      <span>{profile.sourceProjectCount ?? 0} {(profile.sourceProjectCount ?? 0) === 1 ? "grabación" : "grabaciones"} · {profile.sampleCount} fragmentos · {formatLearnedTime(profile.totalDurationMs)}</span>
      <small>{formatLastSeen(profile.lastMatchedAt)}</small>
    </div>
    <div className="voice-reliability">
      <span data-level={profile.reliability}>{profile.reliability === "alta" ? "Fiabilidad alta" : profile.reliability === "buena" ? "Buena fiabilidad" : "Aprendiendo"}</span>
      {advanced && <label>
        <span>Umbral {threshold} %</span>
        <input
          type="range"
          min={55}
          max={86}
          value={threshold}
          disabled={busy}
          onChange={(event) => setThreshold(Number(event.target.value))}
          onPointerUp={(event) => onUpdate({ matchThreshold: Number(event.currentTarget.value) / 100 })}
          onKeyUp={(event) => {
            if (event.key.startsWith("Arrow") || event.key === "Home" || event.key === "End") {
              onUpdate({ matchThreshold: Number(event.currentTarget.value) / 100 });
            }
          }}
        />
      </label>}
    </div>
    <div className="voice-profile-actions">
      <button type="button" disabled={busy || !canMerge} onClick={onMerge} aria-label={`Fusionar ${profile.name}`} title="Fusionar con otra identidad"><GitMerge /></button>
      <button type="button" disabled={busy} onClick={() => onUpdate({ enabled: !profile.enabled })} aria-label={profile.enabled ? `Pausar ${profile.name}` : `Activar ${profile.name}`} title={profile.enabled ? "Pausar reconocimiento" : "Activar reconocimiento"}>
        {profile.enabled ? <Pause /> : <Play />}
      </button>
      <button type="button" className="danger" disabled={busy} onClick={onDelete} aria-label={`Olvidar ${profile.name}`} title="Olvidar voz"><Trash2 /></button>
    </div>
  </article>;
}
