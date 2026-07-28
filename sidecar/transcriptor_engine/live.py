from __future__ import annotations

import base64
import threading
import time
import uuid
import wave
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np

from .paragraphs import group_segments
from .paths import app_data_dir
from .speaker_ai import OnlineSpeakerIdentifier
from .transcriber import Transcriber

LiveEmit = Callable[[str, dict[str, Any]], None]
SAMPLE_RATE = 16_000
MAX_CHUNK_BYTES = SAMPLE_RATE * 2 * 30


class SpeakerClusterer:
    """Small online voice clustering layer for a live session.

    CAM++ performs the primary comparison and the spectral fallback keeps live
    capture usable without the optional model. Reusable profiles are supplied
    only after the user explicitly enables local voice learning.
    """

    def __init__(
        self,
        sensitivity: int = 55,
        max_speakers: int = 2,
        voice_profiles: list[dict[str, Any]] | None = None,
    ) -> None:
        self.centroids: list[np.ndarray] = []
        self.counts: list[int] = []
        self.max_speakers = max(1, min(8, max_speakers))
        self.neural = OnlineSpeakerIdentifier(sensitivity, max_speakers, voice_profiles)
        self.last_confidence: float | None = None
        self.last_cluster_index: int | None = None
        self.last_cluster_backend: str | None = None
        self.last_identity_changed = False
        self.backend = (
            "CAM++ · perfiles locales"
            if self.neural.embedder
            else "Espectral · sin reconocimiento de perfiles"
        )

    @property
    def speaker_count(self) -> int:
        return max(len(self.centroids), len(self.neural.centroids))

    def assign(self, audio: np.ndarray) -> str:
        neural_speaker, confidence = self.neural.assign(audio)
        if neural_speaker:
            self.last_confidence = confidence
            self.last_cluster_index = getattr(self.neural, "last_cluster_index", None)
            self.last_cluster_backend = "neural"
            self.last_identity_changed = bool(
                getattr(self.neural, "last_identity_changed", False)
            )
            return neural_speaker
        self.last_confidence = None
        self.last_cluster_backend = "spectral"
        self.last_identity_changed = False
        embedding = self._embedding(audio)
        if embedding is None:
            self.last_cluster_index = 0 if not self.centroids else len(self.centroids) - 1
            return "Hablante 1" if not self.centroids else f"Hablante {len(self.centroids)}"
        if not self.centroids:
            self.centroids.append(embedding)
            self.counts.append(1)
            self.last_cluster_index = 0
            return "Hablante 1"

        distances = [1.0 - float(np.dot(embedding, centroid)) for centroid in self.centroids]
        nearest = int(np.argmin(distances))
        # A deliberately conservative threshold prevents background noise or a
        # changed vowel from inventing a second person too easily.
        if (
            len(self.centroids) < self.max_speakers
            and distances[nearest] > 0.105
            and audio.size >= SAMPLE_RATE * 0.65
        ):
            self.centroids.append(embedding)
            self.counts.append(1)
            self.last_cluster_index = len(self.centroids) - 1
            return f"Hablante {len(self.centroids)}"
        self.counts[nearest] += 1
        weight = min(0.22, 1.0 / self.counts[nearest])
        centroid = self.centroids[nearest] * (1.0 - weight) + embedding * weight
        self.centroids[nearest] = centroid / max(float(np.linalg.norm(centroid)), 1e-8)
        self.last_cluster_index = nearest
        return f"Hablante {nearest + 1}"

    @staticmethod
    def _embedding(audio: np.ndarray) -> np.ndarray | None:
        if audio.size < SAMPLE_RATE // 3:
            return None
        samples = audio.astype(np.float32, copy=False)
        samples = samples - float(np.mean(samples))
        peak = float(np.max(np.abs(samples)))
        if peak < 0.004:
            return None
        samples /= peak
        frame_size, hop = 512, 256
        frame_count = 1 + max(0, (samples.size - frame_size) // hop)
        if frame_count < 4:
            return None
        indices = np.arange(frame_size)[None, :] + np.arange(frame_count)[:, None] * hop
        frames = samples[indices] * np.hanning(frame_size)[None, :]
        spectrum = np.abs(np.fft.rfft(frames, axis=1)) ** 2
        # Voice identity lives mostly between 80 Hz and 4 kHz. Log-spaced bands
        # retain timbre while reducing sensitivity to the exact words spoken.
        edges = np.geomspace(3, 128, 25).astype(int)
        bands = []
        for start, end in zip(edges[:-1], edges[1:], strict=True):
            bands.append(np.log1p(np.mean(spectrum[:, start : max(start + 1, end)], axis=1)))
        band_matrix = np.stack(bands, axis=1)
        feature = np.concatenate((np.mean(band_matrix, axis=0), np.std(band_matrix, axis=0)))
        feature -= float(np.mean(feature))
        norm = float(np.linalg.norm(feature))
        return feature / norm if norm > 1e-8 else None


@dataclass
class LiveSession:
    id: str
    raw_path: Path
    wav_path: Path
    settings: dict[str, Any]
    separate_speakers: bool
    created_at: str
    samples_written: int = 0
    segments: list[dict[str, Any]] = field(default_factory=list)
    language: str | None = None
    model_error: str | None = None
    voice_observations: list[dict[str, Any]] = field(default_factory=list)
    voice_observation_buckets: dict[int, set[int]] = field(default_factory=dict)
    clusterer: SpeakerClusterer = field(default_factory=SpeakerClusterer)


class LiveSessionManager:
    def __init__(self, transcriber: Transcriber) -> None:
        self.transcriber = transcriber
        self.sessions: dict[str, LiveSession] = {}
        self.model: Any | None = None
        self.device: str | None = None
        self.model_lock = threading.Lock()

    @property
    def active(self) -> bool:
        return bool(self.sessions)

    def start(
        self, settings: dict[str, Any], separate_speakers: bool, emit: LiveEmit | None = None
    ) -> dict[str, Any]:
        if self.sessions:
            raise ValueError("Ya hay una grabación en directo activa.")
        recordings = app_data_dir() / "recordings"
        recordings.mkdir(parents=True, exist_ok=True)
        session_id = str(uuid.uuid4())
        timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        raw_path = recordings / f"Grabación {timestamp}-{session_id[:8]}.pcm"
        wav_path = recordings / f"Grabación {timestamp}.wav"
        raw_path.touch()
        session = LiveSession(
            id=session_id,
            raw_path=raw_path,
            wav_path=wav_path,
            settings=settings,
            separate_speakers=separate_speakers,
            created_at=datetime.now(UTC).isoformat(),
            clusterer=SpeakerClusterer(
                int(settings.get("speakerSensitivity", 55)),
                int(settings.get("speakerCount", 8)),
                settings.get("_voiceProfiles") if settings.get("voiceProfilesEnabled") else None,
            ),
        )
        self.sessions[session_id] = session
        if emit:
            threading.Thread(
                target=self._warm_model,
                args=(session, emit),
                name=f"live-model-{session_id[:8]}",
                daemon=True,
            ).start()
        return {
            "sessionId": session_id,
            "sampleRate": SAMPLE_RATE,
            "separateSpeakers": separate_speakers,
            "createdAt": session.created_at,
            "speakerBackend": session.clusterer.backend,
            "knownProfileCount": len(settings.get("_voiceProfiles") or []),
            "profileRecognitionAvailable": bool(session.clusterer.neural.embedder),
        }

    def push(self, session_id: str, encoded_pcm: str, emit: LiveEmit) -> dict[str, Any]:
        started_at = time.perf_counter()
        session = self._session(session_id)
        try:
            pcm_bytes = base64.b64decode(encoded_pcm, validate=True)
        except ValueError as error:
            raise ValueError("El bloque de audio recibido no es válido.") from error
        if not pcm_bytes or len(pcm_bytes) % 2 or len(pcm_bytes) > MAX_CHUNK_BYTES:
            raise ValueError("El bloque de audio tiene un tamaño no válido.")
        with session.raw_path.open("ab") as target:
            target.write(pcm_bytes)
        pcm = np.frombuffer(pcm_bytes, dtype="<i2").astype(np.float32) / 32768.0
        offset_ms = round(session.samples_written / SAMPLE_RATE * 1000)
        session.samples_written += pcm.size
        duration_ms = round(session.samples_written / SAMPLE_RATE * 1000)
        if float(np.sqrt(np.mean(np.square(pcm)))) < 0.0015:
            return {
                "sessionId": session_id,
                "segments": [],
                "durationMs": duration_ms,
                "language": session.language,
                "device": (self.device or "preparando").upper(),
                "speakerCount": session.clusterer.speaker_count if session.separate_speakers else 0,
                "speakerBackend": session.clusterer.backend,
                "latencyMs": round((time.perf_counter() - started_at) * 1000),
            }
        if session.model_error and self.model is None:
            raise RuntimeError(session.model_error)
        self._ensure_model(session.settings, emit)

        language = session.settings.get("language")
        language = None if language in {None, "", "auto"} else str(language)
        previous_context = " ".join(item["text"] for item in session.segments[-3:])[-280:]
        user_prompt = str(session.settings.get("initialPrompt") or "").strip()
        rolling_prompt = ". ".join(part for part in (user_prompt, previous_context) if part)
        stream, info = self.model.transcribe(
            pcm,
            language=language or session.language,
            word_timestamps=True,
            vad_filter=True,
            vad_parameters={"min_silence_duration_ms": 350, "speech_pad_ms": 160},
            beam_size=1,
            condition_on_previous_text=False,
            initial_prompt=rolling_prompt or None,
            hotwords=session.settings.get("hotwords") or None,
        )
        session.language = session.language or info.language
        produced: list[dict[str, Any]] = []
        for segment in stream:
            item = self.transcriber._segment_item(segment, len(session.segments), offset_ms)
            if not item["text"]:
                continue
            local_start = max(0, round(float(segment.start) * SAMPLE_RATE))
            local_end = min(pcm.size, round(float(segment.end) * SAMPLE_RATE))
            voice_start = max(0, local_start - round(SAMPLE_RATE * 0.18))
            voice_end = min(pcm.size, local_end + round(SAMPLE_RATE * 0.18))
            minimum_voice_window = round(SAMPLE_RATE * 0.75)
            voice_window_padded = voice_end - voice_start < minimum_voice_window
            if voice_window_padded:
                missing = minimum_voice_window - (voice_end - voice_start)
                voice_start = max(0, voice_start - missing // 2)
                voice_end = min(
                    pcm.size,
                    voice_end + (minimum_voice_window - (voice_end - voice_start)),
                )
                voice_start = max(0, voice_end - minimum_voice_window)
            item["speaker"] = (
                session.clusterer.assign(pcm[voice_start:voice_end])
                if session.separate_speakers
                else None
            )
            cluster_index = (
                session.clusterer.last_cluster_index
                if session.separate_speakers
                else None
            )
            item["speakerConfidence"] = (
                session.clusterer.last_confidence if session.separate_speakers else None
            )
            item["speakerProfileId"] = (
                session.clusterer.neural.last_profile_id if session.separate_speakers else None
            )
            item["speakerMatchConfidence"] = (
                session.clusterer.neural.last_profile_confidence
                if session.separate_speakers
                else None
            )
            item["speakerCluster"] = (
                cluster_index + 1 if cluster_index is not None else None
            )
            item["speakerClusterBackend"] = (
                getattr(session.clusterer, "last_cluster_backend", "neural")
                if session.separate_speakers
                else None
            )
            item["speakerProvisional"] = bool(
                session.separate_speakers and not item.get("speakerProfileId")
            )
            if (
                session.separate_speakers
                and cluster_index is not None
                and getattr(session.clusterer, "last_cluster_backend", "neural")
                == "neural"
                and session.clusterer.last_identity_changed
                and item.get("speakerProfileId")
                and getattr(
                    session.clusterer.neural,
                    "last_identity_previous_profile_id",
                    None,
                )
                is None
            ):
                for previous in reversed(session.segments):
                    if previous.get("speakerCluster") != cluster_index + 1:
                        continue
                    if previous.get("speakerClusterBackend") != "neural":
                        continue
                    if not previous.get("speakerProvisional"):
                        break
                    previous["speaker"] = item["speaker"]
                    previous["speakerProfileId"] = item.get("speakerProfileId")
                    previous["speakerMatchConfidence"] = item.get(
                        "speakerMatchConfidence"
                    )
                    previous["speakerProvisional"] = not bool(
                        item.get("speakerProfileId")
                    )
                    emit(
                        "live_partial",
                        {
                            "segment": dict(previous),
                            "durationMs": duration_ms,
                            "language": session.language,
                            "device": (self.device or "cpu").upper(),
                            "speakerBackend": session.clusterer.backend,
                            "identityUpdate": True,
                            "message": (
                                f"Voz reconocida como {item['speaker']}"
                                if item.get("speakerProfileId")
                                else "Identidad de voz actualizada"
                            ),
                        },
                    )
            embedding = session.clusterer.neural.last_embedding
            if (
                embedding is not None
                and bool(session.settings.get("voiceProfilesEnabled", False))
                and bool(session.settings.get("voiceProfileAutoLearn", True))
                and (session.clusterer.last_confidence or 0) >= 0.6
                and getattr(session.clusterer, "last_cluster_backend", "neural")
                == "neural"
                and not voice_window_padded
            ):
                self._retain_voice_observation(
                    session,
                    {
                        "speaker": item.get("speaker") or "Hablante 1",
                        "cluster": (cluster_index + 1) if cluster_index is not None else 1,
                        "matchedProfileId": item.get("speakerProfileId"),
                        "matchConfidence": item.get("speakerMatchConfidence"),
                        "embedding": embedding.tolist(),
                        "segmentId": item["id"],
                        "startMs": item["startMs"],
                        "endMs": item["endMs"],
                        "durationMs": item["endMs"] - item["startMs"],
                        "confidence": session.clusterer.last_confidence,
                        "learningEligible": True,
                    },
                )
            session.segments.append(item)
            produced.append(item)
            emit(
                "live_partial",
                {
                    "segment": item,
                    "durationMs": duration_ms,
                    "language": session.language,
                    "device": (self.device or "cpu").upper(),
                    "speakerBackend": session.clusterer.backend,
                },
            )
        return {
            "sessionId": session_id,
            "segments": produced,
            "durationMs": duration_ms,
            "language": session.language,
            "device": (self.device or "cpu").upper(),
            "speakerCount": session.clusterer.speaker_count if session.separate_speakers else 0,
            "speakerBackend": session.clusterer.backend,
            "latencyMs": round((time.perf_counter() - started_at) * 1000),
        }

    def stop(self, session_id: str) -> dict[str, Any]:
        session = self._session(session_id)
        self._finalize_wav(session)
        segments = group_segments(session.segments, max_duration_ms=35_000, max_characters=520)
        self.sessions.pop(session_id, None)
        observations: list[dict[str, Any]] = []
        grouped: dict[int, list[dict[str, Any]]] = {}
        for sample in session.voice_observations:
            key = int(sample.get("cluster") or 1)
            grouped.setdefault(key, []).append(sample)
        for cluster, samples in sorted(grouped.items()):
            matched_profile_id, match_confidence = self._stable_cluster_identity(
                session,
                cluster,
                samples,
            )
            matched_samples = [
                sample
                for sample in samples
                if sample.get("matchedProfileId") == matched_profile_id
            ]
            representative = max(
                matched_samples,
                key=self._voice_sample_quality,
                default=samples[-1],
            )
            known_profile = next(
                (
                    profile
                    for profile in session.settings.get("_voiceProfiles", [])
                    if str(profile.get("id") or "") == matched_profile_id
                ),
                None,
            )
            observations.append(
                {
                    "cluster": cluster,
                    "suggestedName": str(
                        (known_profile or {}).get("name")
                        or representative.get("speaker")
                        or f"Hablante {cluster}"
                    ),
                    "matchedProfileId": matched_profile_id,
                    "matchConfidence": match_confidence,
                    "samples": matched_samples if matched_profile_id else samples,
                }
            )
        return {
            "sessionId": session_id,
            "mediaPath": str(session.wav_path),
            "durationMs": round(session.samples_written / SAMPLE_RATE * 1000),
            "segments": segments,
            "language": session.language or "es",
            "model": "turbo-live",
            "createdAt": session.created_at,
            "speakerCount": session.clusterer.speaker_count if session.separate_speakers else 0,
            "speakerBackend": session.clusterer.backend,
            "_voiceObservations": observations,
            "_voiceProfileMinConfidence": int(
                session.settings.get("voiceProfileMinConfidence", 72)
            ),
        }

    @staticmethod
    def _retain_voice_observation(
        session: LiveSession, observation: dict[str, Any]
    ) -> None:
        """Keep bounded, time-diverse evidence during recordings of several hours."""
        cluster = int(observation.get("cluster") or 1)
        bucket = int(observation.get("startMs") or 0) // 15_000

        same_bucket = [
            (index, sample)
            for index, sample in enumerate(session.voice_observations)
            if int(sample.get("cluster") or 1) == cluster
            and int(sample.get("startMs") or 0) // 15_000 == bucket
        ]
        if same_bucket:
            weakest_index, weakest = min(
                same_bucket,
                key=lambda item: LiveSessionManager._voice_sample_quality(item[1]),
            )
            if (
                LiveSessionManager._voice_sample_quality(observation)
                > LiveSessionManager._voice_sample_quality(weakest)
            ):
                session.voice_observations[weakest_index] = observation
            return

        seen_by_cluster = getattr(session, "voice_observation_buckets", None)
        if seen_by_cluster is None:
            seen_by_cluster = {}
            session.voice_observation_buckets = seen_by_cluster
        seen_buckets = seen_by_cluster.setdefault(cluster, set())
        if bucket in seen_buckets:
            return
        seen_buckets.add(bucket)

        same_cluster = [
            (index, sample)
            for index, sample in enumerate(session.voice_observations)
            if int(sample.get("cluster") or 1) == cluster
        ]
        if len(same_cluster) >= 48:
            candidates = [sample for _index, sample in same_cluster]
            candidates.append(observation)
            positions = np.asarray(
                [int(sample.get("startMs") or 0) for sample in candidates],
                dtype=np.float64,
            )
            targets = np.linspace(float(positions.min()), float(positions.max()), 48)
            remaining = set(range(len(candidates)))
            retained: list[dict[str, Any]] = []
            for target in targets:
                selected = min(
                    remaining,
                    key=lambda index: (
                        abs(float(positions[index]) - float(target)),
                        -LiveSessionManager._voice_sample_quality(candidates[index]),
                    ),
                )
                remaining.remove(selected)
                retained.append(candidates[selected])
            retained.sort(key=lambda sample: int(sample.get("startMs") or 0))
            for (target_index, _old), sample in zip(
                same_cluster,
                retained,
                strict=True,
            ):
                session.voice_observations[target_index] = sample
            return
        session.voice_observations.append(observation)

    @staticmethod
    def _voice_sample_quality(sample: dict[str, Any]) -> float:
        cluster_score = float(sample.get("confidence") or 0)
        identity_score = float(sample.get("matchConfidence") or cluster_score)
        duration_score = min(1.0, float(sample.get("durationMs") or 0) / 4_000)
        return identity_score * 0.62 + cluster_score * 0.28 + duration_score * 0.10

    @staticmethod
    def _stable_cluster_identity(
        session: LiveSession,
        cluster: int,
        samples: list[dict[str, Any]],
    ) -> tuple[str | None, float | None]:
        weights: dict[str, float] = {}
        durations: dict[str, int] = {}
        weighted_scores: dict[str, float] = {}
        for sample in samples:
            profile_id = str(sample.get("matchedProfileId") or "")
            if not profile_id:
                continue
            confidence = max(0.0, float(sample.get("confidence") or 0))
            match = max(0.0, float(sample.get("matchConfidence") or 0))
            duration = max(0, int(sample.get("durationMs") or 0))
            weight = min(duration, 8_000) * max(confidence, 0.01) * max(match, 0.01)
            weights[profile_id] = weights.get(profile_id, 0.0) + weight
            durations[profile_id] = durations.get(profile_id, 0) + duration
            weighted_scores[profile_id] = weighted_scores.get(profile_id, 0.0) + match * weight
        if not weights:
            return None, None

        final_profile_id = None
        neural_index = cluster - 1
        cluster_profile_ids = getattr(
            session.clusterer.neural,
            "cluster_profile_ids",
            [],
        )
        if 0 <= neural_index < len(cluster_profile_ids):
            final_profile_id = cluster_profile_ids[neural_index]
        winner = max(weights, key=weights.get)
        total_weight = sum(weights.values())
        if (
            final_profile_id in weights
            and weights[str(final_profile_id)] >= weights[winner] * 0.82
        ):
            winner = str(final_profile_id)
        support_ratio = weights[winner] / max(total_weight, 1e-8)
        if durations[winner] < 1_300 or support_ratio < 0.62:
            return None, None
        average = weighted_scores[winner] / max(weights[winner], 1e-8)
        return winner, max(0.0, min(1.0, average))

    def cancel(self, session_id: str) -> None:
        session = self._session(session_id)
        session.raw_path.unlink(missing_ok=True)
        self.sessions.pop(session_id, None)

    def _ensure_model(self, settings: dict[str, Any], emit: LiveEmit) -> None:
        if self.model is not None:
            return
        with self.model_lock:
            if self.model is not None:
                return
            from faster_whisper import WhisperModel

            _profile, threads = self.transcriber._resolve_resources(settings)
            self.device = self.transcriber._select_device(str(settings.get("device", "auto")), emit)
            try:
                self.model = self.transcriber._load_model(
                    WhisperModel, "turbo", self.device, 0, emit, threads, "live"
                )
            except Exception:
                if self.device != "cuda":
                    raise
                self.device = "cpu"
                self.model = self.transcriber._load_model(
                    WhisperModel, "turbo", "cpu", 0, emit, threads, "live"
                )

    def _warm_model(self, session: LiveSession, emit: LiveEmit) -> None:
        def scoped_emit(event_type: str, payload: dict[str, Any]) -> None:
            output_type = "live_partial" if event_type == "live_partial" else "live_status"
            emit(output_type, {**payload, "sessionId": session.id})

        scoped_emit(
            "live_status",
            {
                "stage": "model_loading",
                "message": "Preparando Turbo para transcribir mientras hablas…",
            },
        )
        try:
            self._ensure_model(session.settings, scoped_emit)
            scoped_emit(
                "live_status",
                {
                    "stage": "ready",
                    "device": (self.device or "cpu").upper(),
                    "message": f"Motor listo en {(self.device or 'cpu').upper()} · escuchando en tiempo real",
                },
            )
        except Exception as error:
            session.model_error = str(error)
            scoped_emit(
                "live_status",
                {
                    "stage": "failed",
                    "message": f"No se pudo preparar el modelo en directo: {error}",
                },
            )

    @staticmethod
    def _finalize_wav(session: LiveSession) -> None:
        with wave.open(str(session.wav_path), "wb") as output:
            output.setnchannels(1)
            output.setsampwidth(2)
            output.setframerate(SAMPLE_RATE)
            with session.raw_path.open("rb") as source:
                while block := source.read(1024 * 1024):
                    output.writeframesraw(block)
        session.raw_path.unlink(missing_ok=True)

    def _session(self, session_id: str) -> LiveSession:
        session = self.sessions.get(session_id)
        if not session:
            raise KeyError("La sesión de grabación ya no existe.")
        return session
