from __future__ import annotations

import ctypes
import fnmatch
import gc
import math
import os
import sys
import threading
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .audio import AudioDecodeCancelled, decode_audio_with_progress, enhance_speech_audio
from .diarization import assign_speakers
from .hardware import RuntimeMonitor
from .paragraphs import group_segments
from .paths import models_dir
from .unicode_text import sanitize_text

Emit = Callable[[str, dict[str, Any]], None]
_DLL_DIRECTORY_HANDLES: list[Any] = []

_PHASE_PROGRESS_RANGES: dict[str, tuple[float, float]] = {
    "decoding": (0.0, 10.0),
    "restoring": (10.0, 15.0),
    "language_detection": (15.0, 18.0),
    "transcribing": (18.0, 88.0),
    "reviewing": (88.0, 94.0),
    "diarizing": (94.0, 99.5),
    "saving": (99.5, 99.9),
}


def global_progress(stage: str, phase_percent: float | None) -> float:
    """Map real per-phase progress to monotonic end-to-end progress."""
    start, end = _PHASE_PROGRESS_RANGES[stage]
    if phase_percent is None:
        return start
    bounded = max(0.0, min(100.0, float(phase_percent)))
    return round(start + (end - start) * bounded / 100, 2)


def _configure_cuda_library_paths() -> None:
    if sys.platform != "win32" or _DLL_DIRECTORY_HANDLES:
        return
    roots = [
        Path(os.environ["TRANSCRIPTOR_CUDA_DIR"])
        if os.environ.get("TRANSCRIPTOR_CUDA_DIR")
        else Path("__cuda_dir_not_configured__"),
        Path(getattr(sys, "_MEIPASS", Path(sys.executable).resolve().parent)),
        Path(sys.executable).resolve().parent,
        Path(sys.prefix) / "Lib" / "site-packages",
    ]
    directories: list[Path] = []
    for root in roots:
        if root.name in {"cuda", "bin"}:
            directories.append(root)
        directories.extend(
            [
                root / "nvidia" / "cublas" / "bin",
                root / "nvidia" / "cudnn" / "bin",
                root / "nvidia" / "cuda_runtime" / "bin",
                root / "nvidia" / "cuda_nvrtc" / "bin",
            ]
        )
    for directory in directories:
        if not directory.is_dir():
            continue
        os.environ["PATH"] = f"{directory}{os.pathsep}{os.environ.get('PATH', '')}"
        if hasattr(os, "add_dll_directory"):
            _DLL_DIRECTORY_HANDLES.append(os.add_dll_directory(str(directory)))


@dataclass(frozen=True)
class QualityPlan:
    mode: str
    primary_model: str
    use_batch: bool
    batch_size: int
    review_model: str | None


@dataclass
class TranscriptionOutcome:
    segments: list[dict[str, Any]]
    language: str
    duration_ms: int
    device: str
    model: str
    quality_mode: str
    reviewed_segments: int = 0
    voice_observations: list[dict[str, Any]] = field(default_factory=list)


class Transcriber:
    @staticmethod
    def _quality_plan(settings: dict[str, Any]) -> QualityPlan:
        mode = str(settings.get("qualityMode", "professional"))
        batch_size = min(16, max(1, int(settings.get("batchSize") or 8)))
        if mode == "instant":
            return QualityPlan("instant", "turbo", True, batch_size, None)
        if mode == "maximum":
            return QualityPlan("maximum", "large-v3", False, 1, None)
        return QualityPlan(
            "professional",
            "turbo",
            False,
            1,
            "large-v3" if settings.get("reviewLowConfidence", True) else None,
        )

    @staticmethod
    def _resolve_resources(settings: dict[str, Any]) -> tuple[str, int]:
        logical = max(1, os.cpu_count() or 4)
        physical = max(1, logical // 2)
        queue_threads = int(settings.get("queueCpuThreads") or 0)
        if queue_threads > 0:
            return "custom", min(logical, max(1, queue_threads))
        profile = str(settings.get("performanceProfile", "maximum"))
        if profile == "balanced":
            threads = physical
        elif profile == "performance":
            threads = max(physical, round(logical * 0.75))
        elif profile == "custom":
            threads = int(settings.get("cpuThreads") or physical)
        else:
            profile = "maximum"
            threads = logical
        return profile, min(logical, max(1, threads))

    @staticmethod
    def _apply_priority(priority: str) -> None:
        if priority != "high":
            return
        try:
            import psutil

            process = psutil.Process()
            process.nice(psutil.HIGH_PRIORITY_CLASS if sys.platform == "win32" else -5)
        except (AttributeError, OSError, PermissionError):
            pass

    @staticmethod
    def _cuda_runtime_available() -> bool:
        try:
            _configure_cuda_library_paths()
            import ctranslate2

            if ctranslate2.get_cuda_device_count() < 1:
                return False
            if sys.platform == "win32":
                for library in ("cublas64_12.dll", "cublasLt64_12.dll", "cudnn64_9.dll"):
                    ctypes.WinDLL(library)
            return True
        except (ImportError, OSError, RuntimeError):
            return False

    def _select_device(self, requested_device: str, emit: Emit) -> str:
        if requested_device == "cpu":
            return "cpu"
        if self._cuda_runtime_available():
            return "cuda"
        emit(
            "engine_log",
            {
                "level": "warning",
                "message": "CUDA no está disponible o le faltan cuBLAS/cuDNN; se continuará por CPU.",
            },
        )
        return "cpu"

    @staticmethod
    def _load_model(
        model_class: Any,
        model_name: str,
        device: str,
        duration_ms: int,
        emit: Emit,
        cpu_threads: int | None = None,
        quality_mode: str = "professional",
    ) -> Any:
        common = {
            "device": device,
            "compute_type": "float16" if device == "cuda" else "int8",
            "cpu_threads": cpu_threads or max(1, os.cpu_count() or 4),
            "num_workers": 1,
            "download_root": str(models_dir()),
        }
        base_progress = {
            "state": "waiting_model",
            "stage": "model_loading",
            "phase": "Cargando el modelo local…",
            "processedDurationMs": 0,
            "totalDurationMs": duration_ms,
            "percent": None,
            "activeModel": model_name,
            "qualityMode": quality_mode,
        }
        emit(
            "model_download_progress",
            {**base_progress, "message": f"Cargando {model_name} instalado en {device.upper()}…"},
        )
        installed_dir = models_dir() / model_name
        if (installed_dir / "config.json").is_file():
            return model_class(str(installed_dir), **common, local_files_only=True)
        try:
            return model_class(model_name, **common, local_files_only=True)
        except Exception:
            emit(
                "model_download_progress",
                {
                    **base_progress,
                    "stage": "model_download",
                    "phase": "Descargando el modelo…",
                    "message": f"{model_name} no está completo. Descargando una sola vez…",
                },
            )
            try:
                if str(getattr(model_class, "__module__", "")).startswith("faster_whisper"):
                    model_path = Transcriber._download_model_with_progress(
                        model_name, duration_ms, emit, quality_mode
                    )
                    return model_class(model_path, **common, local_files_only=True)
                return model_class(model_name, **common, local_files_only=False)
            except Exception as download_error:
                raise RuntimeError(
                    f"No se pudo cargar ni descargar {model_name}. "
                    "Comprueba la conexión y el espacio disponible."
                ) from download_error

    @staticmethod
    def _download_model_with_progress(
        model_name: str, duration_ms: int, emit: Emit, quality_mode: str
    ) -> str:
        from faster_whisper.utils import _MODELS, download_model

        repo_id = _MODELS.get(model_name, model_name)
        target = models_dir() / model_name
        target.mkdir(parents=True, exist_ok=True)
        allowed = ("config.json", "preprocessor_config.json", "model.bin", "tokenizer.json", "vocabulary.*")
        total_bytes: int | None = None
        try:
            from huggingface_hub import HfApi

            info = HfApi().model_info(repo_id, files_metadata=True)
            sizes = [
                int(file.size)
                for file in info.siblings
                if file.size is not None
                and any(fnmatch.fnmatch(file.rfilename, pattern) for pattern in allowed)
            ]
            if sizes:
                total_bytes = sum(sizes)
        except Exception:
            total_bytes = None

        result: dict[str, str] = {}
        failure: list[BaseException] = []

        def download() -> None:
            try:
                result["path"] = download_model(model_name, output_dir=str(target))
            except BaseException as error:  # propagated on the transcription worker
                failure.append(error)

        worker = threading.Thread(target=download, name=f"model-download-{model_name}", daemon=True)
        worker.start()
        while worker.is_alive():
            downloaded = sum(
                file.stat().st_size
                for file in target.rglob("*")
                if file.is_file() and ".cache" not in file.parts
            )
            percent = min(99.0, round(downloaded / total_bytes * 100, 1)) if total_bytes else None
            total_label = f" de {total_bytes / 1024**3:.2f} GB" if total_bytes else ""
            emit(
                "model_download_progress",
                {
                    "state": "waiting_model",
                    "stage": "model_download",
                    "phase": "Descargando el modelo…",
                    "processedDurationMs": 0,
                    "totalDurationMs": duration_ms,
                    "percent": percent,
                    "activeModel": model_name,
                    "qualityMode": quality_mode,
                    "message": f"{model_name}: {downloaded / 1024**3:.2f} GB{total_label}",
                },
            )
            worker.join(timeout=0.5)
        if failure:
            raise failure[0]
        emit(
            "model_download_progress",
            {
                "state": "waiting_model",
                "stage": "model_loading",
                "phase": "Modelo descargado",
                "processedDurationMs": 0,
                "totalDurationMs": duration_ms,
                "percent": 100,
                "activeModel": model_name,
                "qualityMode": quality_mode,
                "message": f"{model_name} está verificado y listo para cargar.",
            },
        )
        return result.get("path", str(target))

    @staticmethod
    def _confidence(segment: Any) -> float:
        word_probabilities = [
            float(word.probability)
            for word in (getattr(segment, "words", None) or [])
            if getattr(word, "probability", None) is not None
        ]
        word_score = sum(word_probabilities) / len(word_probabilities) if word_probabilities else 0.0
        avg_logprob = float(getattr(segment, "avg_logprob", -2.0) or -2.0)
        acoustic_score = min(1.0, max(0.0, math.exp(min(0.0, avg_logprob))))
        score = word_score * 0.75 + acoustic_score * 0.25 if word_probabilities else acoustic_score
        return round(min(1.0, max(0.0, score)), 4)

    @classmethod
    def _segment_item(cls, segment: Any, order: int, offset_ms: int = 0) -> dict[str, Any]:
        return {
            "id": str(uuid.uuid4()),
            "startMs": offset_ms + round(segment.start * 1000),
            "endMs": offset_ms + round(segment.end * 1000),
            "text": sanitize_text(segment.text.strip()),
            "speaker": None,
            "confidence": cls._confidence(segment),
            "order": order,
            "words": [
                {
                    "id": str(uuid.uuid4()),
                    "startMs": offset_ms + round(word.start * 1000),
                    "endMs": offset_ms + round(word.end * 1000),
                    "text": sanitize_text(word.word.strip()),
                    "probability": word.probability,
                }
                for word in (segment.words or [])
            ],
        }

    @staticmethod
    def _needs_review(segment: dict[str, Any]) -> bool:
        text = str(segment.get("text", ""))
        confidence = float(segment.get("confidence") or 0.0)
        suspicious = any(marker in text for marker in ("�", "Ã", "Â"))
        return confidence < 0.84 or suspicious

    def transcribe(
        self,
        project: dict[str, Any],
        cancel: threading.Event,
        emit: Emit,
        voice_profiles: list[dict[str, Any]] | None = None,
    ) -> TranscriptionOutcome:
        media_path = Path(str(project.get("mediaPath") or ""))
        if not media_path.is_file():
            raise FileNotFoundError(
                "No se encuentra el audio o vídeo original. "
                "Vuelve a abrirlo o relocaliza el archivo antes de retranscribir."
            )
        from faster_whisper import BatchedInferencePipeline, WhisperModel

        settings = project.get("settings", {})
        plan = self._quality_plan(settings)
        requested_device = settings.get("device", "auto")
        duration_ms = int(project.get("durationMs", 0))
        overall_started = time.perf_counter()
        profile, cpu_threads = self._resolve_resources(settings)
        self._apply_priority(str(settings.get("processPriority", "normal")))
        monitor = RuntimeMonitor()
        device = self._select_device(requested_device, emit)

        try:
            model = self._load_model(
                WhisperModel,
                plan.primary_model,
                device,
                duration_ms,
                emit,
                cpu_threads,
                plan.mode,
            )
        except Exception as gpu_error:
            if device != "cuda":
                raise RuntimeError(f"No se pudo cargar {plan.primary_model}: {gpu_error}") from gpu_error
            emit(
                "engine_log",
                {"level": "warning", "message": "La GPU falló al cargar el modelo; se usará CPU."},
            )
            device = "cpu"
            model = self._load_model(
                WhisperModel,
                plan.primary_model,
                "cpu",
                duration_ms,
                emit,
                cpu_threads,
                plan.mode,
            )

        if cancel.is_set():
            raise CancelledError
        language = settings.get("language")
        language = None if language in {None, "", "auto"} else language
        initial_prompt = settings.get("initialPrompt") or None
        hotwords = settings.get("hotwords") or None
        common_progress = {
            "device": device.upper(),
            "cpuThreads": cpu_threads,
            "performanceProfile": profile,
            "qualityMode": plan.mode,
            "activeModel": plan.primary_model,
        }
        emit(
            "job_started",
            {
                "state": "transcribing",
                "stage": "decoding",
                "phase": "Decodificando el audio…",
                "processedDurationMs": 0,
                "totalDurationMs": duration_ms,
                "percent": global_progress("decoding", 0),
                "phasePercent": 0,
                "message": "Convirtiendo el audio a mono 16 kHz…",
                "elapsedMs": round((time.perf_counter() - overall_started) * 1000),
                **common_progress,
                **monitor.snapshot(),
            },
        )

        decode_started = time.perf_counter()

        def decode_progress(processed_ms: int, total_ms: int) -> None:
            elapsed_ms = max(1, round((time.perf_counter() - decode_started) * 1000))
            phase_percent = round(processed_ms / total_ms * 100, 1) if total_ms else None
            speed = processed_ms / elapsed_ms
            emit(
                "audio_extraction_progress",
                {
                    "state": "transcribing",
                    "stage": "decoding",
                    "phase": "Decodificando el audio…",
                    "processedDurationMs": processed_ms,
                    "totalDurationMs": total_ms,
                    "percent": global_progress("decoding", phase_percent),
                    "phasePercent": phase_percent,
                    "message": f"Decodificando audio · {phase_percent:.0f} %"
                    if phase_percent is not None
                    else "Decodificando audio…",
                    "elapsedMs": round((time.perf_counter() - overall_started) * 1000),
                    "speedX": round(speed, 2),
                    "etaMs": round(max(0, total_ms - processed_ms) / speed) if speed > 0 else None,
                    "segmentsProduced": 0,
                    **common_progress,
                    **monitor.snapshot(),
                },
            )

        try:
            audio = decode_audio_with_progress(
                project["mediaPath"], duration_ms, cancel.is_set, decode_progress
            )
        except AudioDecodeCancelled as error:
            raise CancelledError from error

        enhancement_started = time.perf_counter()

        def enhancement_progress(
            processed_samples: int,
            total_samples: int,
            assessment: dict[str, float | str],
        ) -> None:
            phase_percent = (
                round(processed_samples / total_samples * 100, 1) if total_samples else 100
            )
            profile_name = str(assessment.get("appliedProfile", "off"))
            labels = {
                "off": "Audio ya limpio",
                "speech": "Limpieza de voz",
                "strong": "Restauración intensa",
            }
            emit(
                "audio_enhancement_progress",
                {
                    "state": "transcribing",
                    "stage": "restoring",
                    "phase": "Preparando la voz…",
                    "processedDurationMs": round(processed_samples / 16_000 * 1000),
                    "totalDurationMs": duration_ms,
                    "percent": global_progress("restoring", phase_percent),
                    "phasePercent": phase_percent,
                    "message": (
                        f"{labels.get(profile_name, profile_name)} · ruido "
                        f"{assessment.get('noiseFloorDb', 0)} dB"
                    ),
                    "elapsedMs": round((time.perf_counter() - overall_started) * 1000),
                    "speedX": round(
                        (processed_samples / 16_000)
                        / max(time.perf_counter() - enhancement_started, 0.001),
                        2,
                    ),
                    "segmentsProduced": 0,
                    "audioQuality": assessment,
                    **common_progress,
                    **monitor.snapshot(),
                },
            )

        try:
            audio, audio_assessment = enhance_speech_audio(
                audio,
                str(settings.get("audioEnhancement", "adaptive")),
                cancel.is_set,
                enhancement_progress,
            )
        except AudioDecodeCancelled as error:
            raise CancelledError from error

        emit(
            "transcription_progress",
            {
                "state": "transcribing",
                "stage": "language_detection",
                "phase": "Detectando idioma y voz…",
                "processedDurationMs": 0,
                "totalDurationMs": duration_ms,
                "percent": global_progress("language_detection", None),
                "phasePercent": None,
                "message": (
                    "Detectando idioma y regiones con voz · "
                    f"audio {audio_assessment.get('appliedProfile', 'off')}"
                ),
                "elapsedMs": round((time.perf_counter() - overall_started) * 1000),
                "segmentsProduced": 0,
                **common_progress,
                **monitor.snapshot(),
            },
        )
        inference_started = time.perf_counter()
        transcribe_options = {
            "language": language,
            "word_timestamps": bool(settings.get("wordTimestamps", True)),
            "vad_filter": bool(settings.get("vadFilter", True)),
            "vad_parameters": {"min_silence_duration_ms": 500, "speech_pad_ms": 250},
            "initial_prompt": initial_prompt,
            "hotwords": hotwords,
            "beam_size": 5,
            "condition_on_previous_text": True,
        }
        if plan.use_batch:
            pipeline = BatchedInferencePipeline(model=model)
            segment_stream, info = pipeline.transcribe(
                audio, batch_size=plan.batch_size, **transcribe_options
            )
        else:
            segment_stream, info = model.transcribe(audio, **transcribe_options)
        if not duration_ms:
            duration_ms = round(info.duration * 1000)
        mode_detail = f"lote {plan.batch_size}" if plan.use_batch else "beam 5"
        emit(
            "transcription_progress",
            {
                "state": "transcribing",
                "stage": "transcribing",
                "phase": "Transcribiendo…",
                "processedDurationMs": 0,
                "totalDurationMs": duration_ms,
                "percent": global_progress(
                    "transcribing", 0 if duration_ms else None
                ),
                "phasePercent": 0 if duration_ms else None,
                "message": f"Idioma: {info.language} · {plan.primary_model} · {mode_detail}",
                "elapsedMs": round((time.perf_counter() - overall_started) * 1000),
                "segmentsProduced": 0,
                **common_progress,
                **monitor.snapshot(),
            },
        )

        output: list[dict[str, Any]] = []
        for segment in segment_stream:
            if cancel.is_set():
                raise CancelledError
            item = self._segment_item(segment, len(output))
            if not item["text"]:
                continue
            output.append(item)
            processed = min(duration_ms, item["endMs"])
            phase_percent = (
                round(processed / duration_ms * 100, 1) if duration_ms else None
            )
            inference_elapsed_ms = max(1, round((time.perf_counter() - inference_started) * 1000))
            speed = processed / inference_elapsed_ms
            recognition_detail = f"en lotes de {plan.batch_size}" if plan.use_batch else "con beam 5"
            emit(
                "partial_segments",
                {
                    "projectId": project["id"],
                    "segments": [item],
                    "replaceExisting": len(output) == 1,
                },
            )
            emit(
                "transcription_progress",
                {
                    "state": "transcribing",
                    "stage": "transcribing",
                    "phase": "Transcribiendo…",
                    "processedDurationMs": processed,
                    "totalDurationMs": duration_ms,
                    "percent": global_progress("transcribing", phase_percent),
                    "phasePercent": phase_percent,
                    "message": f"{plan.primary_model} está reconociendo voz {recognition_detail}…",
                    "elapsedMs": round((time.perf_counter() - overall_started) * 1000),
                    "speedX": round(speed, 2),
                    "etaMs": round(max(0, duration_ms - processed) / speed) if speed > 0 else None,
                    "segmentsProduced": len(output),
                    **common_progress,
                    **monitor.snapshot(),
                },
            )

        reviewed = 0
        verifier_used = False
        if plan.review_model and output and device == "cuda":
            candidates = [segment for segment in output if self._needs_review(segment)]
            max_reviews = min(120, max(12, math.ceil(len(output) * 0.12)))
            candidates = sorted(candidates, key=lambda item: float(item.get("confidence") or 0.0))[
                :max_reviews
            ]
            if candidates:
                emit(
                    "transcription_progress",
                    {
                        "state": "transcribing",
                        "stage": "reviewing",
                        "phase": "Revisión inteligente…",
                        "processedDurationMs": duration_ms,
                        "totalDurationMs": duration_ms,
                        "percent": global_progress("reviewing", None),
                        "phasePercent": None,
                        "message": (
                            "Liberando Turbo y preparando Large-v3 para revisar "
                            f"{len(candidates)} fragmentos dudosos…"
                        ),
                        "segmentsProduced": len(output),
                        "reviewSegments": len(candidates),
                        "reviewCompletedUnits": 0,
                        "reviewTotalUnits": len(candidates),
                        "reviewEtaMs": None,
                        "phaseRate": None,
                        "speedX": None,
                        "etaMs": None,
                        "activeModel": plan.review_model,
                        "elapsedMs": round((time.perf_counter() - overall_started) * 1000),
                        **{key: value for key, value in common_progress.items() if key != "activeModel"},
                        **monitor.snapshot(),
                    },
                )
                del model
                if "pipeline" in locals():
                    del pipeline
                gc.collect()
                verifier = self._load_model(
                    WhisperModel,
                    plan.review_model,
                    device,
                    duration_ms,
                    emit,
                    cpu_threads,
                    plan.mode,
                )
                verifier_used = True
                sample_rate = 16_000
                review_started = time.perf_counter()
                for review_index, current in enumerate(candidates, start=1):
                    if cancel.is_set():
                        raise CancelledError
                    start_ms = max(0, int(current["startMs"]) - 150)
                    end_ms = min(duration_ms, int(current["endMs"]) + 150)
                    clip = audio[round(start_ms * sample_rate / 1000) : round(end_ms * sample_rate / 1000)]
                    context_index = int(current["order"])
                    context_parts = [initial_prompt or ""]
                    if context_index > 0:
                        context_parts.append(output[context_index - 1]["text"])
                    if context_index + 1 < len(output):
                        context_parts.append(output[context_index + 1]["text"])
                    refined_stream, _ = verifier.transcribe(
                        clip,
                        language=info.language,
                        word_timestamps=True,
                        vad_filter=False,
                        beam_size=5,
                        condition_on_previous_text=False,
                        initial_prompt=" ".join(part for part in context_parts if part).strip() or None,
                        hotwords=hotwords,
                    )
                    refined_parts = list(refined_stream)
                    refined_text = sanitize_text(
                        " ".join(part.text.strip() for part in refined_parts).strip()
                    )
                    if refined_text:
                        confidence = round(
                            sum(self._confidence(part) for part in refined_parts) / len(refined_parts), 4
                        )
                        original_confidence = float(current.get("confidence") or 0.0)
                        original_is_corrupt = any(
                            marker in str(current.get("text", "")) for marker in ("�", "Ã", "Â")
                        )
                        if confidence >= original_confidence - 0.03 or original_is_corrupt:
                            words = []
                            for part in refined_parts:
                                words.extend(self._segment_item(part, 0, start_ms)["words"])
                            updated = {
                                **current,
                                "text": refined_text,
                                "confidence": confidence,
                                "words": words,
                            }
                            output[context_index] = updated
                            current.update(updated)
                            reviewed += 1
                            emit(
                                "partial_segments",
                                {
                                    "projectId": project["id"],
                                    "segments": [updated],
                                    "replaceExisting": False,
                                },
                            )
                    review_elapsed_ms = max(
                        1, round((time.perf_counter() - review_started) * 1000)
                    )
                    review_rate = review_index / (review_elapsed_ms / 1000)
                    review_eta_ms = round(
                        max(0, len(candidates) - review_index)
                        / max(review_rate, 0.001)
                        * 1000
                    )
                    review_phase_percent = round(
                        review_index / max(len(candidates), 1) * 100, 2
                    )
                    emit(
                        "transcription_progress",
                        {
                            "state": "transcribing",
                            "stage": "reviewing",
                            "phase": "Revisión inteligente…",
                            "processedDurationMs": duration_ms,
                            "totalDurationMs": duration_ms,
                            "percent": global_progress("reviewing", review_phase_percent),
                            "phasePercent": review_phase_percent,
                            "message": (
                                f"Large-v3 revisando fragmentos dudosos · {review_index}/{len(candidates)}"
                            ),
                            "segmentsProduced": len(output),
                            "reviewSegments": len(candidates) - review_index,
                            "reviewCompletedUnits": review_index,
                            "reviewTotalUnits": len(candidates),
                            "reviewEtaMs": review_eta_ms,
                            "phaseRate": round(review_rate, 2),
                            "speedX": None,
                            "etaMs": review_eta_ms,
                            "activeModel": plan.review_model,
                            "elapsedMs": round((time.perf_counter() - overall_started) * 1000),
                            **{key: value for key, value in common_progress.items() if key != "activeModel"},
                            **monitor.snapshot(),
                        },
                    )

        voice_observations: list[dict[str, Any]] = []
        diarization_mode = str(settings.get("diarizationMode", "off"))
        if diarization_mode in {"adaptive", "neural", "precise", "channels"} and output:
            emit(
                "transcription_progress",
                {
                    "state": "transcribing",
                    "stage": "diarizing",
                    "phase": "Preparando la IA de hablantes…",
                    "processedDurationMs": duration_ms,
                    "totalDurationMs": duration_ms,
                    "percent": global_progress("diarizing", None),
                    "phasePercent": None,
                    "message": "Detectando turnos y preparando huellas vocales locales…",
                    "segmentsProduced": len(output),
                    "diarizationCompletedUnits": 0,
                    "diarizationTotalUnits": len(output),
                    "diarizationEtaMs": None,
                    "phaseRate": None,
                    "speedX": None,
                    "etaMs": None,
                    **common_progress,
                    **monitor.snapshot(),
                },
            )
            diarization_started = time.perf_counter()

            def diarization_progress(event: dict[str, Any]) -> None:
                completed = int(event.get("completedUnits", 0))
                total = max(1, int(event.get("totalUnits", len(output))))
                elapsed_ms = round((time.perf_counter() - diarization_started) * 1000)
                average_ms = elapsed_ms / completed if completed else 0
                eta_ms = round(max(0, total - completed) * average_ms) if completed else None
                stage = str(event.get("stage", "speaker_embedding"))
                phase = {
                    "speaker_embedding": "Extrayendo huellas vocales…",
                    "speaker_alignment": "Alineando palabras y hablantes…",
                    "speaker_fallback": "Activando separación compatible…",
                }.get(stage, "Separando hablantes…")
                emit(
                    "transcription_progress",
                    {
                        "state": "transcribing",
                        "stage": "diarizing",
                        "phase": phase,
                        "processedDurationMs": duration_ms,
                        "totalDurationMs": duration_ms,
                        "percent": global_progress(
                            "diarizing", float(event.get("percent", 0))
                        ),
                        "phasePercent": float(event.get("percent", 0)),
                        "message": str(event.get("message", phase)),
                        "segmentsProduced": len(output),
                        "diarizationCompletedUnits": completed,
                        "diarizationTotalUnits": total,
                        "diarizationEtaMs": eta_ms,
                        "phaseRate": (
                            round(completed / max(elapsed_ms / 1000, 0.001), 2)
                            if completed
                            else None
                        ),
                        "speedX": None,
                        "speakerBackend": (
                            "Acústico adaptativo"
                            if stage == "speaker_fallback"
                            else "CAM++ · ONNX"
                            if diarization_mode in {"adaptive", "neural", "precise"}
                            else "Canales/acústica"
                        ),
                        "elapsedMs": round((time.perf_counter() - overall_started) * 1000),
                        "etaMs": eta_ms,
                        **common_progress,
                        **monitor.snapshot(),
                    },
                )

            output, speaker_count = assign_speakers(
                output,
                audio,
                mode=diarization_mode,
                speaker_count=int(settings.get("speakerCount", 8)),
                exact_speaker_count=str(settings.get("speakerCountMode", "auto")) == "exact",
                sensitivity=int(settings.get("speakerSensitivity", 55)),
                progress=diarization_progress,
                voice_profiles=voice_profiles,
                profile_observations=(
                    voice_observations
                    if bool(settings.get("voiceProfilesEnabled", False))
                    and bool(settings.get("voiceProfileAutoLearn", True))
                    else None
                ),
            )
            emit(
                "partial_segments",
                {"projectId": project["id"], "segments": output, "replaceExisting": True},
            )
            emit(
                "engine_log",
                {
                    "level": "info",
                    "message": (
                        f"Diarización híbrida local: {speaker_count or 1} voz/ces candidata/s "
                        f"con modo {diarization_mode}."
                    ),
                },
            )

        if bool(settings.get("paragraphMode", True)):
            output = group_segments(
                output,
                max_duration_ms=int(settings.get("maxParagraphSeconds", 42)) * 1000,
                max_characters=int(settings.get("maxParagraphCharacters", 620)),
            )
            emit(
                "partial_segments",
                {
                    "projectId": project["id"],
                    "segments": output,
                    "replaceExisting": True,
                },
            )

        return TranscriptionOutcome(
            segments=output,
            language=info.language,
            duration_ms=duration_ms,
            device=device,
            model=f"{plan.primary_model}+{plan.review_model}" if verifier_used else plan.primary_model,
            quality_mode=plan.mode,
            reviewed_segments=reviewed,
            voice_observations=voice_observations,
        )


class CancelledError(Exception):
    pass
