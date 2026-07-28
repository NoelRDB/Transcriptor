from __future__ import annotations

import hashlib
import os
import threading
import urllib.request
from collections.abc import Callable
from pathlib import Path
from typing import Any

import kaldi_native_fbank as knf
import numpy as np
import onnxruntime as ort

from .paths import models_dir

SAMPLE_RATE = 16_000
MODEL_NAME = "3dspeaker_speech_campplus_sv_zh_en_16k-common_advanced.onnx"
MODEL_URL = (
    "https://github.com/k2-fsa/sherpa-onnx/releases/download/"
    f"speaker-recongition-models/{MODEL_NAME}"
)
MODEL_SHA256 = "aa3cfc16963a10586a9393f5035d6d6b57e98d358b347f80c2a30bf4f00ceba2"
MODEL_BYTES = 28_281_164

ProgressCallback = Callable[[dict[str, Any]], None]
_embedder: NeuralSpeakerEmbedder | None = None
_embedder_lock = threading.Lock()


def speaker_model_path() -> Path:
    return models_dir() / "speaker" / MODEL_NAME


def speaker_ai_status() -> dict[str, Any]:
    path = speaker_model_path()
    installed = path.is_file() and path.stat().st_size == MODEL_BYTES
    return {
        "installed": installed,
        "ready": installed,
        "backend": "CAM++ · ONNX" if installed else "Acústico ligero",
        "model": "CAM++ multilingüe · 192 dimensiones",
        "path": str(path),
        "sizeBytes": MODEL_BYTES,
        "expectedBytes": MODEL_BYTES,
        "privacy": "local",
        "preciseAvailable": _pyannote_available(),
        "preciseModel": "pyannote Community-1",
        "notice": (
            "La IA neuronal de voces está lista."
            if installed
            else "Instala el modelo de voces para sustituir la comparación espectral básica."
        ),
    }


def download_speaker_model(progress: ProgressCallback, cancelled: Callable[[], bool]) -> dict[str, Any]:
    global _embedder
    target = speaker_model_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    partial = target.with_suffix(".onnx.part")
    if target.is_file() and _sha256(target) == MODEL_SHA256:
        progress(
            {"stage": "completed", "downloadedBytes": MODEL_BYTES, "totalBytes": MODEL_BYTES, "percent": 100}
        )
        return speaker_ai_status()

    request = urllib.request.Request(MODEL_URL, headers={"User-Agent": "Transcriptor/0.2"})
    downloaded = partial.stat().st_size if partial.exists() else 0
    if downloaded:
        request.add_header("Range", f"bytes={downloaded}-")
    mode = "ab" if downloaded else "wb"
    with urllib.request.urlopen(request, timeout=45) as response, partial.open(mode) as output:
        response_total = int(response.headers.get("Content-Length") or 0)
        total = downloaded + response_total if response_total else MODEL_BYTES
        while True:
            if cancelled():
                raise RuntimeError("Descarga del modelo de voces cancelada.")
            chunk = response.read(1024 * 512)
            if not chunk:
                break
            output.write(chunk)
            downloaded += len(chunk)
            progress(
                {
                    "stage": "downloading",
                    "downloadedBytes": downloaded,
                    "totalBytes": total,
                    "percent": round(min(100, downloaded / max(total, 1) * 100), 2),
                }
            )
    if partial.stat().st_size != MODEL_BYTES or _sha256(partial) != MODEL_SHA256:
        partial.unlink(missing_ok=True)
        raise RuntimeError("El modelo descargado no supera la verificación de integridad.")
    os.replace(partial, target)
    with _embedder_lock:
        _embedder = None
    progress(
        {"stage": "completed", "downloadedBytes": MODEL_BYTES, "totalBytes": MODEL_BYTES, "percent": 100}
    )
    return speaker_ai_status()


class NeuralSpeakerEmbedder:
    def __init__(self, model_path: Path | None = None, threads: int = 2) -> None:
        path = model_path or speaker_model_path()
        if not path.is_file():
            raise FileNotFoundError("El modelo neuronal de voces no está instalado.")
        options = ort.SessionOptions()
        options.intra_op_num_threads = max(1, min(4, threads))
        options.inter_op_num_threads = 1
        self.session = ort.InferenceSession(
            str(path),
            sess_options=options,
            providers=["CPUExecutionProvider"],
        )

    def embedding(self, audio: np.ndarray) -> np.ndarray | None:
        if audio.size < round(SAMPLE_RATE * 0.55):
            return None
        samples = np.asarray(audio, dtype=np.float32)
        samples = samples - float(samples.mean())
        rms = float(np.sqrt(np.mean(np.square(samples))))
        if rms < 0.0015:
            return None
        peak = float(np.max(np.abs(samples)))
        if peak > 1:
            samples /= peak

        options = knf.FbankOptions()
        options.frame_opts.samp_freq = SAMPLE_RATE
        options.frame_opts.dither = 0
        options.frame_opts.snip_edges = False
        options.mel_opts.num_bins = 80
        fbank = knf.OnlineFbank(options)
        fbank.accept_waveform(SAMPLE_RATE, samples.tolist())
        fbank.input_finished()
        if fbank.num_frames_ready < 20:
            return None
        features = np.stack(
            [fbank.get_frame(index) for index in range(fbank.num_frames_ready)]
        ).astype(np.float32)
        features -= features.mean(axis=0, keepdims=True)
        vector = self.session.run(None, {"x": features[None, :, :]})[0][0].astype(np.float32)
        norm = float(np.linalg.norm(vector))
        return vector / norm if norm > 1e-8 and np.isfinite(vector).all() else None


def get_neural_embedder() -> NeuralSpeakerEmbedder | None:
    global _embedder
    if not speaker_ai_status()["installed"]:
        return None
    with _embedder_lock:
        if _embedder is None:
            _embedder = NeuralSpeakerEmbedder()
        return _embedder


class OnlineSpeakerIdentifier:
    """Low-latency neural clustering with hysteresis and an adaptive voice limit."""

    def __init__(
        self,
        sensitivity: int = 55,
        max_speakers: int = 2,
        voice_profiles: list[dict[str, Any]] | None = None,
    ) -> None:
        self.embedder = get_neural_embedder()
        self.sensitivity = max(0, min(100, sensitivity))
        self.max_speakers = max(1, min(8, max_speakers))
        self.voice_profiles = [
            profile
            for profile in (voice_profiles or [])
            if profile.get("enabled", True) and profile.get("centroid") is not None
        ]
        self.centroids: list[np.ndarray] = []
        self.counts: list[int] = []
        self.cluster_profile_ids: list[str | None] = []
        self.cluster_names: list[str] = []
        self.previous: int | None = None
        self.backend = "neural" if self.embedder else "unavailable"
        self.last_embedding: np.ndarray | None = None
        self.last_profile_id: str | None = None
        self.last_profile_confidence: float | None = None

    def assign(self, audio: np.ndarray) -> tuple[str | None, float | None]:
        if not self.embedder:
            return None, None
        embedding = self.embedder.embedding(audio)
        self.last_embedding = embedding
        self.last_profile_id = None
        self.last_profile_confidence = None
        if embedding is None:
            return None, None
        if not self.centroids:
            self.centroids.append(embedding)
            self.counts.append(1)
            self._identify_cluster(embedding)
            self.previous = 0
            return self.cluster_names[0], 0.72

        similarities = [float(np.dot(embedding, centroid)) for centroid in self.centroids]
        nearest = int(np.argmax(similarities))
        new_speaker_similarity = 0.82 - self.sensitivity * 0.002
        if (
            len(self.centroids) < self.max_speakers
            and similarities[nearest] < new_speaker_similarity
            and audio.size >= round(SAMPLE_RATE * 0.72)
        ):
            self.centroids.append(embedding)
            self.counts.append(1)
            self._identify_cluster(embedding)
            self.previous = len(self.centroids) - 1
            return self.cluster_names[-1], 0.7

        if (
            self.previous is not None
            and self.previous < len(similarities)
            and similarities[self.previous] >= similarities[nearest] - 0.035
        ):
            nearest = self.previous
        ordered = sorted(similarities, reverse=True)
        margin = ordered[0] - ordered[1] if len(ordered) > 1 else max(0, ordered[0] - 0.55)
        confidence = max(0.5, min(0.99, 0.58 + margin * 1.9))
        self.counts[nearest] += 1
        if confidence >= 0.62:
            weight = min(0.12, 1.0 / self.counts[nearest])
            centroid = self.centroids[nearest] * (1 - weight) + embedding * weight
            self.centroids[nearest] = centroid / max(float(np.linalg.norm(centroid)), 1e-8)
        self.previous = nearest
        self.last_profile_id = self.cluster_profile_ids[nearest]
        if self.last_profile_id:
            profile = next(
                (item for item in self.voice_profiles if item.get("id") == self.last_profile_id),
                None,
            )
            if profile is not None:
                self.last_profile_confidence = float(
                    np.dot(embedding, np.asarray(profile["centroid"], dtype=np.float32))
                )
        return self.cluster_names[nearest], confidence

    def _identify_cluster(self, embedding: np.ndarray) -> None:
        used = {profile_id for profile_id in self.cluster_profile_ids if profile_id}
        candidates: list[tuple[float, dict[str, Any]]] = []
        for profile in self.voice_profiles:
            if str(profile.get("id")) in used:
                continue
            centroid = np.asarray(profile["centroid"], dtype=np.float32)
            score = float(np.dot(embedding, centroid))
            candidates.append((score, profile))
        candidates.sort(key=lambda item: item[0], reverse=True)
        selected: dict[str, Any] | None = None
        score: float | None = None
        if candidates:
            best_score, best = candidates[0]
            threshold = float(best.get("matchThreshold", 0.64))
            margin = best_score - candidates[1][0] if len(candidates) > 1 else 1.0
            if best_score >= threshold and margin >= 0.025:
                selected, score = best, best_score
        self.cluster_profile_ids.append(str(selected["id"]) if selected else None)
        self.cluster_names.append(
            str(selected["name"]) if selected else f"Hablante {len(self.cluster_names) + 1}"
        )
        self.last_profile_id = str(selected["id"]) if selected else None
        self.last_profile_confidence = score


def neural_assign_speakers(
    segments: list[dict[str, Any]],
    audio: np.ndarray,
    speaker_count: int = 2,
    exact_speaker_count: bool = True,
    sensitivity: int = 55,
    progress: ProgressCallback | None = None,
    voice_profiles: list[dict[str, Any]] | None = None,
    profile_observations: list[dict[str, Any]] | None = None,
) -> tuple[list[dict[str, Any]], int]:
    embedder = get_neural_embedder()
    if not embedder:
        raise FileNotFoundError("El modelo neuronal de voces no está instalado.")
    units = _speaker_units(segments)
    vectors: list[np.ndarray | None] = []
    valid_indices: list[int] = []
    total = len(units)
    for index, unit in enumerate(units):
        start = max(0, round((unit["startMs"] - 120) * SAMPLE_RATE / 1000))
        end = min(audio.size, round((unit["endMs"] + 120) * SAMPLE_RATE / 1000))
        vector = embedder.embedding(audio[start:end])
        vectors.append(vector)
        if vector is not None:
            valid_indices.append(index)
        if progress:
            progress(
                {
                    "stage": "speaker_embedding",
                    "completedUnits": index + 1,
                    "totalUnits": total,
                    "percent": round((index + 1) / max(total, 1) * 100, 2),
                    "message": f"Analizando la huella vocal {index + 1} de {total}…",
                }
            )
    if not valid_indices:
        return [{**segment, "speaker": "Hablante 1"} for segment in segments], 1

    matrix = np.stack([vectors[index] for index in valid_indices if vectors[index] is not None])
    target = _resolve_speaker_target(
        matrix,
        speaker_count=speaker_count,
        exact_speaker_count=exact_speaker_count,
        sensitivity=sensitivity,
    )
    labels, confidences = _cluster_embeddings(matrix, target)
    unit_labels: list[int | None] = [None] * len(units)
    unit_confidences: list[float | None] = [None] * len(units)
    for position, unit_index in enumerate(valid_indices):
        unit_labels[unit_index] = int(labels[position])
        unit_confidences[unit_index] = float(confidences[position])
    _fill_and_smooth_labels(unit_labels, unit_confidences)

    first_seen: dict[int, int] = {}
    for label in unit_labels:
        if label is not None and label not in first_seen:
            first_seen[label] = len(first_seen)
    cluster_vectors: dict[int, list[np.ndarray]] = {}
    cluster_samples: dict[int, list[dict[str, Any]]] = {}
    for position, unit_index in enumerate(valid_indices):
        raw_label = int(labels[position])
        vector = vectors[unit_index]
        if vector is None:
            continue
        cluster_vectors.setdefault(raw_label, []).append(vector)
        unit = units[unit_index]
        cluster_samples.setdefault(raw_label, []).append(
            {
                "embedding": vector.tolist(),
                "segmentId": str(unit["id"]),
                "startMs": int(unit["startMs"]),
                "endMs": int(unit["endMs"]),
                "durationMs": int(unit["endMs"]) - int(unit["startMs"]),
                "confidence": float(confidences[position]),
            }
        )
    cluster_centroids = {
        label: _normalized_mean(items) for label, items in cluster_vectors.items() if items
    }
    profile_matches = _match_clusters_to_profiles(cluster_centroids, voice_profiles or [])

    output = []
    for index, unit in enumerate(units):
        raw_label = unit_labels[index] if unit_labels[index] is not None else 0
        visible_label = first_seen.setdefault(raw_label, len(first_seen))
        profile_match = profile_matches.get(raw_label)
        output.append(
            {
                **unit,
                "speaker": (
                    str(profile_match["name"])
                    if profile_match
                    else f"Hablante {visible_label + 1}"
                ),
                "speakerConfidence": unit_confidences[index],
                "speakerProfileId": str(profile_match["id"]) if profile_match else None,
                "speakerMatchConfidence": (
                    float(profile_match["score"]) if profile_match else None
                ),
                "speakerProvisional": False,
                "order": index,
            }
        )
    if profile_observations is not None:
        for raw_label, visible_label in sorted(first_seen.items(), key=lambda item: item[1]):
            centroid = cluster_centroids.get(raw_label)
            if centroid is None:
                continue
            match = profile_matches.get(raw_label)
            profile_observations.append(
                {
                    "cluster": visible_label + 1,
                    "suggestedName": (
                        str(match["name"]) if match else f"Hablante {visible_label + 1}"
                    ),
                    "matchedProfileId": str(match["id"]) if match else None,
                    "matchConfidence": float(match["score"]) if match else None,
                    "centroid": centroid.tolist(),
                    "samples": cluster_samples.get(raw_label, []),
                }
            )
    if progress:
        progress(
            {
                "stage": "speaker_alignment",
                "completedUnits": total,
                "totalUnits": total,
                "percent": 100,
                "message": f"{len(first_seen)} voces alineadas con {total} intervenciones.",
            }
        )
    return output, len(first_seen)


def _normalized_mean(vectors: list[np.ndarray]) -> np.ndarray:
    centroid = np.stack(vectors).mean(axis=0).astype(np.float32)
    return centroid / max(float(np.linalg.norm(centroid)), 1e-8)


def _match_clusters_to_profiles(
    cluster_centroids: dict[int, np.ndarray],
    voice_profiles: list[dict[str, Any]],
) -> dict[int, dict[str, Any]]:
    profiles = [
        profile
        for profile in voice_profiles
        if profile.get("enabled", True) and profile.get("centroid") is not None
    ]
    candidates: list[tuple[float, int, dict[str, Any]]] = []
    for label, centroid in cluster_centroids.items():
        scores = sorted(
            [
                (
                float(np.dot(centroid, np.asarray(profile["centroid"], dtype=np.float32))),
                profile,
                )
                for profile in profiles
            ],
            key=lambda item: item[0],
            reverse=True,
        )
        for index, (score, profile) in enumerate(scores):
            threshold = float(profile.get("matchThreshold", 0.64))
            alternative = scores[1][0] if index == 0 and len(scores) > 1 else None
            if score >= threshold and (alternative is None or score - alternative >= 0.025):
                candidates.append((score, label, profile))
    candidates.sort(key=lambda item: item[0], reverse=True)
    matches: dict[int, dict[str, Any]] = {}
    used_profiles: set[str] = set()
    for score, label, profile in candidates:
        profile_id = str(profile["id"])
        if label in matches or profile_id in used_profiles:
            continue
        matches[label] = {**profile, "score": score}
        used_profiles.add(profile_id)
    return matches


def _speaker_units(segments: list[dict[str, Any]]) -> list[dict[str, Any]]:
    units: list[dict[str, Any]] = []
    for segment in segments:
        words = sorted(segment.get("words", []), key=lambda item: int(item["startMs"]))
        if not words or int(segment["endMs"]) - int(segment["startMs"]) <= 3_400:
            units.append({**segment, "words": words})
            continue
        current: list[dict[str, Any]] = []
        groups: list[list[dict[str, Any]]] = []
        for index, word in enumerate(words):
            current.append(word)
            duration = int(current[-1]["endMs"]) - int(current[0]["startMs"])
            next_word = words[index + 1] if index + 1 < len(words) else None
            pause = int(next_word["startMs"]) - int(word["endMs"]) if next_word else 10_000
            if duration >= 3_000 or (duration >= 1_050 and pause >= 260) or next_word is None:
                groups.append(current)
                current = []
        if current:
            groups.append(current)
        if len(groups) > 1 and int(groups[-1][-1]["endMs"]) - int(groups[-1][0]["startMs"]) < 550:
            groups[-2].extend(groups.pop())
        for group_index, group in enumerate(groups):
            units.append(
                {
                    **segment,
                    "id": f"{segment['id']}-voice-{group_index}",
                    "startMs": int(group[0]["startMs"]),
                    "endMs": int(group[-1]["endMs"]),
                    "text": "".join(str(word.get("text", "")) for word in group).strip(),
                    "words": group,
                }
            )
    return units


def _cluster_embeddings(matrix: np.ndarray, clusters: int) -> tuple[np.ndarray, np.ndarray]:
    clusters = max(1, min(int(clusters), matrix.shape[0]))
    if clusters == 1:
        # A single coherent cluster is still useful training evidence.  The old
        # value (0.72) sat exactly on the default learning threshold and was
        # frequently lost after float conversions.
        return np.zeros(matrix.shape[0], dtype=np.int32), np.full(matrix.shape[0], 0.86)
    mean = matrix.mean(axis=0)
    mean /= max(float(np.linalg.norm(mean)), 1e-8)
    selected = [int(np.argmin(matrix @ mean))]
    while len(selected) < clusters:
        selected_scores = matrix @ matrix[selected].T
        nearest_selected = np.max(selected_scores, axis=1)
        nearest_selected[selected] = 2.0
        selected.append(int(np.argmin(nearest_selected)))
    centroids = matrix[selected].copy()
    labels = np.zeros(matrix.shape[0], dtype=np.int32)
    for _ in range(20):
        scores = matrix @ centroids.T
        next_labels = np.argmax(scores, axis=1).astype(np.int32)
        if np.array_equal(labels, next_labels) and _ > 0:
            break
        labels = next_labels
        for cluster in range(clusters):
            members = matrix[labels == cluster]
            if members.size:
                centroid = members.mean(axis=0)
                centroids[cluster] = centroid / max(float(np.linalg.norm(centroid)), 1e-8)
    scores = matrix @ centroids.T
    ordered = np.sort(scores, axis=1)
    best_similarity = np.clip(ordered[:, -1], 0.0, 1.0)
    separation_margin = np.clip(ordered[:, -1] - ordered[:, -2], 0.0, 1.0)
    # Confidence describes whether this particular intervention is safe to use
    # as voice-memory evidence.  The previous formula only measured the margin
    # between two centroids and therefore rejected almost every natural
    # conversation at the default 72 % threshold, even when its own centroid
    # fit was excellent.
    confidence = np.clip(
        0.62 + best_similarity * 0.24 + separation_margin * 1.35,
        0.55,
        0.99,
    )
    return labels, confidence


def _estimate_speaker_count(matrix: np.ndarray, sensitivity: int = 55) -> int:
    """Choose 1–8 voices from CAM++ evidence without loading the whole distance matrix."""
    if matrix.shape[0] < 4:
        return 1
    if matrix.shape[0] > 240:
        indices = np.linspace(0, matrix.shape[0] - 1, 240, dtype=np.int32)
        sample = matrix[indices]
    else:
        sample = matrix
    max_clusters = min(8, sample.shape[0] // 2)
    bounded_sensitivity = max(0, min(100, int(sensitivity)))
    minimum_separation = 0.22 - bounded_sensitivity * 0.002
    minimum_score = 0.24 - bounded_sensitivity * 0.001
    minimum_support = max(2, int(np.ceil(sample.shape[0] * 0.04)))
    best_clusters = 1
    best_score = minimum_score
    for clusters in range(2, max_clusters + 1):
        labels, _ = _cluster_embeddings(sample, clusters)
        counts = np.bincount(labels, minlength=clusters)
        if np.any(counts < minimum_support):
            continue
        centroids = np.stack(
            [
                _normalized_mean([vector for vector in sample[labels == cluster]])
                for cluster in range(clusters)
            ]
        )
        centroid_similarities = centroids @ centroids.T
        centroid_similarities += np.eye(clusters, dtype=np.float32) * -2
        separation = 1.0 - float(np.max(centroid_similarities))
        if separation < minimum_separation:
            continue
        silhouette = _cosine_silhouette(sample, labels, clusters)
        score = silhouette + separation * 0.35 - (clusters - 1) * 0.025
        if silhouette >= 0.08 and score > best_score:
            best_clusters = clusters
            best_score = score
    return best_clusters


def _resolve_speaker_target(
    matrix: np.ndarray,
    speaker_count: int,
    exact_speaker_count: bool,
    sensitivity: int = 55,
) -> int:
    maximum = max(1, min(int(speaker_count), 8, matrix.shape[0]))
    if exact_speaker_count:
        return maximum
    return min(maximum, _estimate_speaker_count(matrix, sensitivity))


def _cosine_silhouette(matrix: np.ndarray, labels: np.ndarray, clusters: int) -> float:
    distances = 1.0 - np.clip(matrix @ matrix.T, -1.0, 1.0)
    scores: list[float] = []
    for index, label in enumerate(labels):
        own_indices = np.flatnonzero(labels == label)
        own_indices = own_indices[own_indices != index]
        within = float(np.mean(distances[index, own_indices])) if own_indices.size else 0.0
        nearest_other = min(
            float(np.mean(distances[index, labels == other]))
            for other in range(clusters)
            if other != label and np.any(labels == other)
        )
        denominator = max(within, nearest_other, 1e-8)
        scores.append((nearest_other - within) / denominator)
    return float(np.mean(scores)) if scores else 0.0


def _fill_and_smooth_labels(
    labels: list[int | None], confidences: list[float | None]
) -> None:
    previous = 0
    for index, label in enumerate(labels):
        if label is None:
            labels[index] = previous
            confidences[index] = 0.5
        else:
            previous = label
    for index in range(1, len(labels) - 1):
        if (
            labels[index - 1] == labels[index + 1] != labels[index]
            and (confidences[index] or 0) < 0.75
        ):
            labels[index] = labels[index - 1]
            confidences[index] = min(0.7, confidences[index] or 0.5)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _pyannote_available() -> bool:
    try:
        import pyannote.audio  # noqa: F401
    except (ImportError, OSError):
        return False
    return True
