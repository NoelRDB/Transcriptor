from __future__ import annotations

from collections.abc import Callable
from typing import Any

import numpy as np

SAMPLE_RATE = 16_000


class AcousticSpeakerClusterer:
    """Ephemeral adaptive clustering; no reusable voiceprint is persisted."""

    def __init__(self, max_speakers: int = 8, sensitivity: int = 55) -> None:
        self.max_speakers = max(1, min(8, max_speakers))
        self.sensitivity = max(0, min(100, sensitivity))
        self.centroids: list[np.ndarray] = []
        self.counts: list[int] = []

    def assign(self, audio: np.ndarray) -> str | None:
        embedding = self._embedding(audio)
        if embedding is None:
            return None
        if not self.centroids:
            self.centroids.append(embedding)
            self.counts.append(1)
            return "Hablante 1"
        distances = [1.0 - float(np.dot(embedding, centroid)) for centroid in self.centroids]
        nearest = int(np.argmin(distances))
        split_distance = 0.16 - self.sensitivity * 0.0008
        if (
            len(self.centroids) < self.max_speakers
            and distances[nearest] > split_distance
            and audio.size >= SAMPLE_RATE
        ):
            self.centroids.append(embedding)
            self.counts.append(1)
            return f"Hablante {len(self.centroids)}"
        self.counts[nearest] += 1
        weight = min(0.15, 1.0 / self.counts[nearest])
        centroid = self.centroids[nearest] * (1.0 - weight) + embedding * weight
        self.centroids[nearest] = centroid / max(float(np.linalg.norm(centroid)), 1e-8)
        return f"Hablante {nearest + 1}"

    @staticmethod
    def _embedding(audio: np.ndarray) -> np.ndarray | None:
        if audio.size < SAMPLE_RATE // 2:
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
        edges = np.geomspace(3, 128, 25).astype(int)
        bands = [
            np.log1p(np.mean(spectrum[:, start : max(start + 1, end)], axis=1))
            for start, end in zip(edges[:-1], edges[1:], strict=True)
        ]
        band_matrix = np.stack(bands, axis=1)
        feature = np.concatenate((np.mean(band_matrix, axis=0), np.std(band_matrix, axis=0)))
        feature -= float(np.mean(feature))
        norm = float(np.linalg.norm(feature))
        return feature / norm if norm > 1e-8 else None


def assign_speakers(
    segments: list[dict[str, Any]],
    audio: np.ndarray,
    mode: str = "acoustic",
    speaker_count: int = 2,
    exact_speaker_count: bool = True,
    sensitivity: int = 55,
    progress: Callable[[dict[str, Any]], None] | None = None,
    voice_profiles: list[dict[str, Any]] | None = None,
    profile_observations: list[dict[str, Any]] | None = None,
) -> tuple[list[dict[str, Any]], int]:
    if mode in {"adaptive", "neural", "precise"}:
        try:
            from .speaker_ai import neural_assign_speakers

            return neural_assign_speakers(
                segments=segments,
                audio=audio,
                speaker_count=speaker_count,
                exact_speaker_count=exact_speaker_count,
                sensitivity=sensitivity,
                progress=progress,
                voice_profiles=voice_profiles,
                profile_observations=profile_observations,
            )
        except (FileNotFoundError, ImportError, OSError, RuntimeError):
            if progress:
                progress(
                    {
                        "stage": "speaker_fallback",
                        "completedUnits": 0,
                        "totalUnits": len(segments),
                        "percent": 0,
                        "message": "La IA de voces no está disponible; usando separación acústica segura.",
                    }
                )
    clusterer = AcousticSpeakerClusterer(
        max_speakers=speaker_count if exact_speaker_count else 8,
        sensitivity=sensitivity,
    )
    previous = "Hablante 1"
    output: list[dict[str, Any]] = []
    for segment in segments:
        start = max(0, round(int(segment["startMs"]) * SAMPLE_RATE / 1000))
        end = min(audio.size, round(int(segment["endMs"]) * SAMPLE_RATE / 1000))
        speaker = clusterer.assign(audio[start:end]) or previous
        previous = speaker
        output.append(
            {
                **segment,
                "speaker": speaker,
                "speakerConfidence": None,
                "speakerProvisional": False,
            }
        )
        if progress:
            progress(
                {
                    "stage": "speaker_embedding",
                    "completedUnits": len(output),
                    "totalUnits": len(segments),
                    "percent": round(len(output) / max(len(segments), 1) * 100, 2),
                    "message": f"Comparando la intervención {len(output)} de {len(segments)}…",
                }
            )
    return output, len(clusterer.centroids)
