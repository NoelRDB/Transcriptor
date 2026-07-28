import { useEffect, useRef, useState } from "react";
import { Expand, Pause, Play, RotateCcw, RotateCw, Volume1, Volume2, VolumeX } from "lucide-react";
import type { TranscriptionProject } from "../types";
import { clamp, formatClock } from "../lib/time";

interface MediaPlayerProps {
  project: TranscriptionProject;
  currentTimeMs: number;
  skipSeconds: number;
  onTime: (ms: number) => void;
  onPlaying: (playing: boolean) => void;
  onError: (message: string) => void;
  seekSignal: number;
}

export function MediaPlayer({ project, currentTimeMs, skipSeconds, onTime, onPlaying, onError, seekSignal }: MediaPlayerProps) {
  const mediaRef = useRef<HTMLMediaElement>(null);
  const [playing, setPlaying] = useState(false);
  const [volume, setVolume] = useState(1);
  const [rate, setRate] = useState(1);
  const [duration, setDuration] = useState(project.durationMs || 0);

  useEffect(() => {
    const media = mediaRef.current;
    if (media) media.currentTime = currentTimeMs / 1000;
    // seekSignal deliberately triggers this effect.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [seekSignal]);

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (event.target instanceof HTMLInputElement || event.target instanceof HTMLTextAreaElement) return;
      const media = mediaRef.current;
      if (!media) return;
      if (event.code === "Space") {
        event.preventDefault();
        if (media.paused) {
          void media.play().catch(() => onError("No se pudo iniciar la reproducción del archivo."));
        } else media.pause();
      }
      if (event.code === "ArrowLeft") media.currentTime = Math.max(0, media.currentTime - skipSeconds);
      if (event.code === "ArrowRight") media.currentTime = Math.min(media.duration || Infinity, media.currentTime + skipSeconds);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [skipSeconds, onError]);

  async function toggle() {
    const media = mediaRef.current;
    if (!media) return;
    try {
      if (media.paused) await media.play(); else media.pause();
    } catch {
      onError("No se pudo iniciar la reproducción. Comprueba que el archivo siga disponible y que su códec sea compatible.");
    }
  }

  function setPlaybackRate(next: number) {
    setRate(next);
    if (mediaRef.current) mediaRef.current.playbackRate = next;
  }

  const MediaTag = project.mediaType === "video" ? "video" : "audio";
  const effectiveDuration = duration || project.durationMs;

  return (
    <section className={`player-card ${project.mediaType}`} aria-label="Reproductor multimedia">
      <div className="media-stage">
        {project.mediaType === "audio" && <div className="audio-art"><span /><div><strong>{project.name}</strong><small>Archivo de audio</small></div></div>}
        <MediaTag
          ref={(node) => { mediaRef.current = node; }}
          src={project.mediaUrl}
          preload="metadata"
          onLoadedMetadata={(event) => {
            setDuration(event.currentTarget.duration * 1000);
            event.currentTarget.currentTime = currentTimeMs / 1000;
          }}
          onTimeUpdate={(event) => onTime(event.currentTarget.currentTime * 1000)}
          onPlay={() => { setPlaying(true); onPlaying(true); }}
          onPause={() => { setPlaying(false); onPlaying(false); }}
          onEnded={() => { setPlaying(false); onPlaying(false); }}
          onError={(event) => {
            const code = event.currentTarget.error?.code;
            onError(`No se pudo cargar el audio o vídeo${code ? ` (código ${code})` : ""}. Comprueba el archivo y su códec.`);
          }}
        />
      </div>
      <div className="timeline-row">
        <span>{formatClock(currentTimeMs)}</span>
        <input aria-label="Posición" type="range" min={0} max={Math.max(1, effectiveDuration)} step={100} value={clamp(currentTimeMs, 0, effectiveDuration || 1)} onChange={(event) => { const ms = Number(event.target.value); if (mediaRef.current) mediaRef.current.currentTime = ms / 1000; onTime(ms); }} />
        <span>{formatClock(effectiveDuration)}</span>
      </div>
      <div className="player-controls">
        <div className="control-group">
          <button className="icon-button" onClick={() => { if (mediaRef.current) mediaRef.current.currentTime -= skipSeconds; }} aria-label={`Retroceder ${skipSeconds} segundos`}><RotateCcw size={19} /><small>{skipSeconds}</small></button>
          <button className="play-button" onClick={toggle} aria-label={playing ? "Pausar" : "Reproducir"}>{playing ? <Pause fill="currentColor" /> : <Play fill="currentColor" />}</button>
          <button className="icon-button" onClick={() => { if (mediaRef.current) mediaRef.current.currentTime += skipSeconds; }} aria-label={`Avanzar ${skipSeconds} segundos`}><RotateCw size={19} /><small>{skipSeconds}</small></button>
        </div>
        <div className="control-group right">
          <button className="icon-button" aria-label={volume ? "Silenciar" : "Activar sonido"} onClick={() => { const next = volume ? 0 : 1; setVolume(next); if (mediaRef.current) mediaRef.current.volume = next; }}>{volume === 0 ? <VolumeX size={19} /> : volume < 0.6 ? <Volume1 size={19} /> : <Volume2 size={19} />}</button>
          <input className="volume" aria-label="Volumen" type="range" min={0} max={1} step={0.05} value={volume} onChange={(e) => { const next = Number(e.target.value); setVolume(next); if (mediaRef.current) mediaRef.current.volume = next; }} />
          <select aria-label="Velocidad" value={rate} onChange={(e) => setPlaybackRate(Number(e.target.value))}>{[0.5, 0.75, 1, 1.25, 1.5, 2].map((value) => <option value={value} key={value}>{value}×</option>)}</select>
          {project.mediaType === "video" && <button className="icon-button" aria-label="Pantalla completa" onClick={() => mediaRef.current?.requestFullscreen()}><Expand size={19} /></button>}
        </div>
      </div>
    </section>
  );
}
