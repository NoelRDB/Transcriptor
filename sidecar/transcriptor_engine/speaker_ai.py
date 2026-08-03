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

from .speaker_model import (
    MODEL_BYTES,
    MODEL_SHA256,
    MODEL_URL,
    speaker_ai_status,
    speaker_model_path,
)

SAMPLE_RATE = 16_000
SINGLE_PROFILE_ABSOLUTE_FLOOR = 0.72
MULTI_PROFILE_ABSOLUTE_FLOOR = 0.70
ProgressCallback = Callable[[dict[str, Any]], None]
_embedder: NeuralSpeakerEmbedder | None = None
_embedder_lock = threading.Lock()


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
        features = np.stack([fbank.get_frame(index) for index in range(fbank.num_frames_ready)]).astype(
            np.float32
        )
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
        self._profile_vectors: dict[str, np.ndarray] = {}
        self._profiles_by_id: dict[str, dict[str, Any]] = {}
        for profile in self.voice_profiles:
            profile_id = str(profile.get("id") or "")
            vector = _normalized_vector(profile.get("centroid"))
            if profile_id and vector is not None:
                self._profile_vectors[profile_id] = vector
                self._profiles_by_id[profile_id] = profile
        self.centroids: list[np.ndarray] = []
        self.counts: list[int] = []
        self.cluster_profile_ids: list[str | None] = []
        self.cluster_names: list[str] = []
        self.cluster_profile_ema: list[dict[str, float]] = []
        self.cluster_profile_support: list[dict[str, int]] = []
        self.cluster_profile_misses: list[int] = []
        self.previous: int | None = None
        self.backend = "neural" if self.embedder else "unavailable"
        self.last_embedding: np.ndarray | None = None
        self.last_cluster_index: int | None = None
        self.last_identity_changed = False
        self.last_identity_previous_profile_id: str | None = None
        self.last_identity_previous_name: str | None = None
        self.last_profile_id: str | None = None
        self.last_profile_name: str | None = None
        self.last_profile_confidence: float | None = None

    def assign(self, audio: np.ndarray) -> tuple[str | None, float | None]:
        self.last_cluster_index = None
        self.last_identity_changed = False
        self.last_identity_previous_profile_id = None
        self.last_identity_previous_name = None
        self.last_profile_id = None
        self.last_profile_name = None
        self.last_profile_confidence = None
        if not self.embedder:
            return None, None
        embedding = self.embedder.embedding(audio)
        self.last_embedding = embedding
        if embedding is None:
            return None, None
        if not self.centroids:
            self._append_cluster(embedding)
            self.previous = 0
            self.last_cluster_index = 0
            self._reevaluate_cluster(0, embedding)
            self._set_last_profile_evidence(0, embedding)
            return self.cluster_names[0], 0.72

        similarities = [float(np.dot(embedding, centroid)) for centroid in self.centroids]
        nearest = int(np.argmax(similarities))
        strong_profile = self._strong_instant_profile_candidate(embedding)
        profile_routed = False
        if strong_profile is not None:
            candidate_id, _candidate_score = strong_profile
            matching_clusters = [
                index
                for index, profile_id in enumerate(self.cluster_profile_ids)
                if profile_id == candidate_id
            ]
            if matching_clusters:
                best_known_cluster = max(
                    matching_clusters,
                    key=lambda index: similarities[index],
                )
                # A known identity is a stronger routing signal than two
                # acoustically similar centroids. This matters especially for
                # partners or relatives whose embeddings can be quite close.
                if similarities[best_known_cluster] >= 0.42:
                    nearest = best_known_cluster
                    profile_routed = True
            else:
                nearest_profile_id = self.cluster_profile_ids[nearest]
                if (
                    nearest_profile_id is not None
                    and nearest_profile_id != candidate_id
                    and len(self.centroids) < self.max_speakers
                    and audio.size >= round(SAMPLE_RATE * 0.72)
                ):
                    nearest = self._append_cluster(embedding)
                    self.previous = nearest
                    self.last_cluster_index = nearest
                    self._reevaluate_cluster(nearest, embedding)
                    self._set_last_profile_evidence(nearest, embedding)
                    return self.cluster_names[nearest], 0.78
        new_speaker_similarity = 0.82 - self.sensitivity * 0.002
        if (
            not profile_routed
            and len(self.centroids) < self.max_speakers
            and similarities[nearest] < new_speaker_similarity
            and audio.size >= round(SAMPLE_RATE * 0.72)
        ):
            nearest = self._append_cluster(embedding)
            self.previous = nearest
            self.last_cluster_index = nearest
            self._reevaluate_cluster(nearest, embedding)
            self._set_last_profile_evidence(nearest, embedding)
            return self.cluster_names[nearest], 0.7

        if (
            not profile_routed
            and self.previous is not None
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
        self.last_cluster_index = nearest
        self._reevaluate_cluster(nearest, embedding)
        self._set_last_profile_evidence(nearest, embedding)
        return self.cluster_names[nearest], confidence

    def _strong_instant_profile_candidate(
        self,
        embedding: np.ndarray,
    ) -> tuple[str, float] | None:
        scores = sorted(
            self._profile_scores(embedding).items(),
            key=lambda item: item[1],
            reverse=True,
        )
        if not scores:
            return None
        profile_id, score = scores[0]
        alternative = scores[1][1] if len(scores) > 1 else None
        margin = score - alternative if alternative is not None else 1.0
        profile = self._profiles_by_id[profile_id]
        threshold = _required_profile_score(
            float(profile.get("matchThreshold", 0.64)),
            len(self._profile_vectors),
        )
        if score >= max(0.76, threshold + 0.04) and margin >= 0.06:
            return profile_id, score
        return None

    def _append_cluster(self, embedding: np.ndarray) -> int:
        index = len(self.centroids)
        self.centroids.append(embedding)
        self.counts.append(1)
        self.cluster_profile_ids.append(None)
        self.cluster_names.append(f"Hablante {index + 1}")
        self.cluster_profile_ema.append({})
        self.cluster_profile_support.append({})
        self.cluster_profile_misses.append(0)
        return index

    def _identify_cluster(self, embedding: np.ndarray) -> None:
        """Initialise profile state for a centroid appended by an older caller."""
        if not self.centroids:
            cluster_index = self._append_cluster(embedding)
        elif len(self.cluster_profile_ids) < len(self.centroids):
            cluster_index = len(self.cluster_profile_ids)
            self.cluster_profile_ids.append(None)
            self.cluster_names.append(f"Hablante {cluster_index + 1}")
            self.cluster_profile_ema.append({})
            self.cluster_profile_support.append({})
            self.cluster_profile_misses.append(0)
        else:
            cluster_index = len(self.centroids) - 1
        self.last_cluster_index = cluster_index
        self._reevaluate_cluster(cluster_index, embedding)
        self._set_last_profile_evidence(cluster_index, embedding)

    def _reevaluate_cluster(self, cluster_index: int, embedding: np.ndarray) -> None:
        if not self._profile_vectors:
            return
        scores = self._profile_scores(embedding)
        if not scores:
            return

        ema = self.cluster_profile_ema[cluster_index]
        for profile_id, score in scores.items():
            previous = ema.get(profile_id)
            ema[profile_id] = score if previous is None else previous * 0.62 + score * 0.38

        centroid_scores = self._profile_scores(self.centroids[cluster_index])
        evidence = {
            profile_id: (
                scores[profile_id] * 0.55
                + ema[profile_id] * 0.25
                + centroid_scores.get(profile_id, scores[profile_id]) * 0.20
            )
            for profile_id in scores
        }
        ordered = sorted(evidence.items(), key=lambda item: item[1], reverse=True)
        candidate_id, candidate_score = ordered[0]
        alternative_score = ordered[1][1] if len(ordered) > 1 else None
        margin = candidate_score - alternative_score if alternative_score is not None else 1.0
        candidate_profile = self._profiles_by_id[candidate_id]
        configured_threshold = float(candidate_profile.get("matchThreshold", 0.64))
        threshold = _required_profile_score(
            configured_threshold,
            len(self._profile_vectors),
        )
        instant_score = scores[candidate_id]
        qualifies = (
            candidate_score >= threshold
            and instant_score >= threshold - 0.025
            and margin >= 0.025
            and self._duplicate_profile_is_safe(
                cluster_index,
                candidate_id,
                instant_score,
                candidate_score,
                margin,
                threshold,
            )
        )

        support = self.cluster_profile_support[cluster_index]
        if qualifies:
            support[candidate_id] = support.get(candidate_id, 0) + 1
            for profile_id in list(support):
                if profile_id != candidate_id:
                    support[profile_id] = 0
        else:
            for profile_id in list(support):
                support[profile_id] = 0

        current_id = self.cluster_profile_ids[cluster_index]
        if current_id == candidate_id and qualifies:
            self.cluster_profile_misses[cluster_index] = 0
            return

        if current_id is None:
            exceptionally_clear = (
                instant_score >= max(0.90, threshold + 0.12)
                and candidate_score >= threshold + 0.08
                and margin >= 0.06
            )
            if qualifies and (support.get(candidate_id, 0) >= 2 or exceptionally_clear):
                self._set_cluster_identity(cluster_index, candidate_profile)
            return

        current_profile = self._profiles_by_id.get(current_id)
        current_threshold = _required_profile_score(
            float(current_profile.get("matchThreshold", 0.64) if current_profile else 0.64),
            len(self._profile_vectors),
        )
        current_score = scores.get(current_id, -1.0)
        if qualifies and candidate_id != current_id:
            clear_switch = (
                support.get(candidate_id, 0) >= 3
                and candidate_score >= threshold + 0.035
                and margin >= 0.045
                and (current_score < current_threshold - 0.025 or instant_score >= current_score + 0.075)
            )
            if clear_switch:
                self._set_cluster_identity(cluster_index, candidate_profile)
                self.cluster_profile_misses[cluster_index] = 0
                return

        if current_score < current_threshold - 0.08:
            self.cluster_profile_misses[cluster_index] += 1
        else:
            self.cluster_profile_misses[cluster_index] = 0
        if self.cluster_profile_misses[cluster_index] >= 4:
            self._set_cluster_identity(cluster_index, None)
            self.cluster_profile_misses[cluster_index] = 0

    def _profile_scores(self, embedding: np.ndarray) -> dict[str, float]:
        return {
            profile_id: float(np.dot(embedding, centroid))
            for profile_id, centroid in self._profile_vectors.items()
            if embedding.shape == centroid.shape
        }

    def _duplicate_profile_is_safe(
        self,
        cluster_index: int,
        profile_id: str,
        instant_score: float,
        evidence_score: float,
        margin: float,
        threshold: float,
    ) -> bool:
        siblings = [
            index
            for index, assigned_profile_id in enumerate(self.cluster_profile_ids)
            if index != cluster_index and assigned_profile_id == profile_id
        ]
        if not siblings:
            return True
        sibling_similarity = max(
            float(np.dot(self.centroids[cluster_index], self.centroids[index])) for index in siblings
        )
        return (
            instant_score >= max(0.72, threshold + 0.04)
            and evidence_score >= threshold + 0.035
            and margin >= 0.04
            and sibling_similarity >= max(0.68, threshold + 0.025)
        )

    def _set_cluster_identity(self, cluster_index: int, profile: dict[str, Any] | None) -> None:
        previous_profile_id = self.cluster_profile_ids[cluster_index]
        previous_name = self.cluster_names[cluster_index]
        profile_id = str(profile["id"]) if profile else None
        name = str(profile["name"]) if profile else f"Hablante {cluster_index + 1}"
        if previous_profile_id == profile_id and previous_name == name:
            return
        self.cluster_profile_ids[cluster_index] = profile_id
        self.cluster_names[cluster_index] = name
        self.last_identity_changed = True
        self.last_identity_previous_profile_id = previous_profile_id
        self.last_identity_previous_name = previous_name

    def _set_last_profile_evidence(self, cluster_index: int, embedding: np.ndarray) -> None:
        profile_id = self.cluster_profile_ids[cluster_index]
        self.last_profile_id = profile_id
        self.last_profile_name = self.cluster_names[cluster_index] if profile_id is not None else None
        profile_centroid = self._profile_vectors.get(profile_id or "")
        if profile_centroid is not None and profile_centroid.shape == embedding.shape:
            self.last_profile_confidence = max(0.0, min(1.0, float(np.dot(embedding, profile_centroid))))


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
        minimum_window = round(SAMPLE_RATE * 0.8)
        if end - start < minimum_window:
            missing = minimum_window - (end - start)
            start = max(0, start - missing // 2)
            end = min(audio.size, end + (minimum_window - (end - start)))
            start = max(0, end - minimum_window)
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
    if not exact_speaker_count and voice_profiles:
        target = max(
            target,
            min(
                max(1, min(int(speaker_count), 8, matrix.shape[0])),
                _known_profile_anchor_count(matrix, voice_profiles),
            ),
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
                "_unitIndex": unit_index,
            }
        )
    cluster_centroids = {label: _normalized_mean(items) for label, items in cluster_vectors.items() if items}
    profile_matches = _match_clusters_to_profiles(cluster_centroids, voice_profiles or [])
    unit_profile_overrides: dict[int, dict[str, Any]] = {}
    for unit_index, unit_vector in enumerate(vectors):
        unit_duration = int(units[unit_index]["endMs"]) - int(
            units[unit_index]["startMs"]
        )
        if unit_vector is None or unit_duration < 800:
            continue
        exceptional_match = _exceptional_profile_match(
            unit_vector,
            voice_profiles or [],
        )
        if exceptional_match is not None:
            unit_profile_overrides[unit_index] = exceptional_match

    for raw_label, samples in list(cluster_samples.items()):
        cluster_match = profile_matches.get(raw_label)
        if not cluster_match:
            continue
        cluster_samples[raw_label] = [
            sample
            for sample in samples
            if not (
                (unit_match := unit_profile_overrides.get(int(sample["_unitIndex"])))
                and str(cluster_match.get("id")) != str(unit_match.get("id"))
            )
        ]
    for raw_label, samples in cluster_samples.items():
        profile_match = profile_matches.get(raw_label)
        if not profile_match:
            continue
        profile_vector = _normalized_vector(profile_match.get("centroid"))
        if profile_vector is None:
            continue
        for sample in samples:
            sample_vector = _normalized_vector(sample.get("embedding"))
            sample["matchConfidence"] = (
                max(0.0, min(1.0, float(np.dot(sample_vector, profile_vector))))
                if sample_vector is not None and sample_vector.shape == profile_vector.shape
                else None
            )
            sample.pop("_unitIndex", None)
    for samples in cluster_samples.values():
        for sample in samples:
            sample.pop("_unitIndex", None)

    output = []
    for index, unit in enumerate(units):
        raw_label = unit_labels[index] if unit_labels[index] is not None else 0
        visible_label = first_seen.setdefault(raw_label, len(first_seen))
        profile_match = unit_profile_overrides.get(index) or profile_matches.get(raw_label)
        profile_vector = _normalized_vector(profile_match.get("centroid")) if profile_match else None
        unit_vector = vectors[index]
        match_confidence = (
            max(0.0, min(1.0, float(np.dot(unit_vector, profile_vector))))
            if unit_vector is not None
            and profile_vector is not None
            and unit_vector.shape == profile_vector.shape
            else None
        )
        output.append(
            {
                **unit,
                "speaker": (str(profile_match["name"]) if profile_match else f"Hablante {visible_label + 1}"),
                "speakerConfidence": unit_confidences[index],
                "speakerClusterIndex": visible_label,
                "speakerProfileId": str(profile_match["id"]) if profile_match else None,
                "speakerMatchConfidence": match_confidence,
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
                    "suggestedName": (str(match["name"]) if match else f"Hablante {visible_label + 1}"),
                    "matchedProfileId": str(match["id"]) if match else None,
                    "matchConfidence": float(match["score"]) if match else None,
                    "centroid": centroid.tolist(),
                    "samples": cluster_samples.get(raw_label, []),
                }
            )
    detected_speaker_keys = {
        (
            str(item.get("speakerProfileId"))
            if item.get("speakerProfileId")
            else str(item.get("speaker"))
        )
        for item in output
    }
    detected_speaker_count = max(1, len(detected_speaker_keys))
    if progress:
        progress(
            {
                "stage": "speaker_alignment",
                "completedUnits": total,
                "totalUnits": total,
                "percent": 100,
                "message": (
                    f"{detected_speaker_count} voces alineadas con "
                    f"{total} intervenciones."
                ),
            }
        )
    return output, detected_speaker_count


def _normalized_mean(vectors: list[np.ndarray]) -> np.ndarray:
    centroid = np.stack(vectors).mean(axis=0).astype(np.float32)
    return centroid / max(float(np.linalg.norm(centroid)), 1e-8)


def _normalized_vector(value: Any) -> np.ndarray | None:
    try:
        vector = np.asarray(value, dtype=np.float32)
    except (TypeError, ValueError):
        return None
    if vector.ndim != 1 or vector.size == 0 or not np.isfinite(vector).all():
        return None
    norm = float(np.linalg.norm(vector))
    return vector / norm if norm > 1e-8 else None


def _required_profile_score(configured_threshold: float, profile_count: int) -> float:
    """Require open-set evidence in addition to any relative cohort margin."""
    threshold = max(0.0, min(1.0, float(configured_threshold)))
    return (
        max(threshold, SINGLE_PROFILE_ABSOLUTE_FLOOR)
        if profile_count == 1
        else max(threshold, MULTI_PROFILE_ABSOLUTE_FLOOR)
    )


def _known_profile_anchor_count(
    matrix: np.ndarray,
    voice_profiles: list[dict[str, Any]],
) -> int:
    """Keep a clearly present known voice from disappearing as a small cluster."""
    profiles: list[tuple[str, float, np.ndarray]] = []
    for profile in voice_profiles:
        vector = _normalized_vector(profile.get("centroid"))
        if not profile.get("enabled", True) or vector is None:
            continue
        profiles.append(
            (
                str(profile.get("id") or ""),
                float(profile.get("matchThreshold", 0.64)),
                vector,
            )
        )
    if not profiles:
        return 1

    support: dict[str, int] = {}
    for embedding in matrix:
        scores = sorted(
            (
                (float(np.dot(embedding, vector)), profile_id, threshold)
                for profile_id, threshold, vector in profiles
                if embedding.shape == vector.shape
            ),
            reverse=True,
        )
        if not scores:
            continue
        best_score, profile_id, threshold = scores[0]
        alternative = scores[1][0] if len(scores) > 1 else None
        margin = best_score - alternative if alternative is not None else 1.0
        required = _required_profile_score(threshold + 0.02, len(profiles))
        if best_score >= required and margin >= 0.035:
            support[profile_id] = support.get(profile_id, 0) + 1
    anchored = sum(1 for count in support.values() if count >= 2)
    return max(1, anchored)


def _exceptional_profile_match(
    embedding: np.ndarray,
    voice_profiles: list[dict[str, Any]],
) -> dict[str, Any] | None:
    """Recognize one very clear cameo without inventing a general cluster."""
    candidates: list[tuple[float, dict[str, Any]]] = []
    for profile in voice_profiles:
        vector = _normalized_vector(profile.get("centroid"))
        if not profile.get("enabled", True) or vector is None:
            continue
        if embedding.shape == vector.shape:
            candidates.append((float(np.dot(embedding, vector)), profile))
    candidates.sort(key=lambda item: item[0], reverse=True)
    if not candidates:
        return None
    score, profile = candidates[0]
    alternative = candidates[1][0] if len(candidates) > 1 else None
    margin = score - alternative if alternative is not None else 1.0
    threshold = float(profile.get("matchThreshold", 0.64))
    if score >= max(0.86, threshold + 0.16) and margin >= 0.12:
        return {**profile, "score": score}
    return None


def _match_clusters_to_profiles(
    cluster_centroids: dict[int, np.ndarray],
    voice_profiles: list[dict[str, Any]],
) -> dict[int, dict[str, Any]]:
    profiles: list[tuple[dict[str, Any], np.ndarray]] = []
    for profile in voice_profiles:
        vector = _normalized_vector(profile.get("centroid"))
        if profile.get("enabled", True) and vector is not None:
            profiles.append((profile, vector))

    normalized_clusters = {
        label: vector
        for label, centroid in cluster_centroids.items()
        if (vector := _normalized_vector(centroid)) is not None
    }
    candidates: list[dict[str, Any]] = []
    for label, centroid in normalized_clusters.items():
        scores = sorted(
            [
                (float(np.dot(centroid, profile_vector)), profile)
                for profile, profile_vector in profiles
                if centroid.shape == profile_vector.shape
            ],
            key=lambda item: item[0],
            reverse=True,
        )
        if not scores:
            continue
        score, profile = scores[0]
        alternative = scores[1][0] if len(scores) > 1 else None
        margin = score - alternative if alternative is not None else 1.0
        threshold = float(profile.get("matchThreshold", 0.64))
        required = _required_profile_score(threshold, len(profiles))
        if score >= required and margin >= 0.025:
            candidates.append(
                {
                    "label": label,
                    "profile": profile,
                    "score": score,
                    "margin": margin,
                    "threshold": threshold,
                    "required": required,
                }
            )

    candidates.sort(key=lambda item: float(item["score"]), reverse=True)
    matches: dict[int, dict[str, Any]] = {}
    matched_clusters_by_profile: dict[str, list[int]] = {}
    for candidate in candidates:
        label = int(candidate["label"])
        profile = candidate["profile"]
        score = float(candidate["score"])
        margin = float(candidate["margin"])
        threshold = float(candidate["threshold"])
        required = float(candidate["required"])
        profile_id = str(profile["id"])
        siblings = matched_clusters_by_profile.get(profile_id, [])
        if siblings:
            sibling_similarity = max(
                float(
                    np.dot(
                        normalized_clusters[label],
                        normalized_clusters[sibling_label],
                    )
                )
                for sibling_label in siblings
            )
            duplicate_is_safe = (
                score >= max(0.72, required + 0.04)
                and margin >= 0.04
                and sibling_similarity >= max(0.68, threshold + 0.025)
            )
            if not duplicate_is_safe:
                continue
        if label in matches:
            continue
        matches[label] = {**profile, "score": score}
        matched_clusters_by_profile.setdefault(profile_id, []).append(label)
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


def _fill_and_smooth_labels(labels: list[int | None], confidences: list[float | None]) -> None:
    previous = 0
    for index, label in enumerate(labels):
        if label is None:
            labels[index] = previous
            confidences[index] = 0.5
        else:
            previous = label
    for index in range(1, len(labels) - 1):
        if labels[index - 1] == labels[index + 1] != labels[index] and (confidences[index] or 0) < 0.75:
            labels[index] = labels[index - 1]
            confidences[index] = min(0.7, confidences[index] or 0.5)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()
