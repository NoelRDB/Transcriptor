from __future__ import annotations

import queue
import subprocess
import sys
import threading
import time
from collections.abc import Callable
from pathlib import Path
from typing import BinaryIO

import numpy as np

from .media import _find_tool

ProgressCallback = Callable[[int, int], None]
EnhancementProgressCallback = Callable[[int, int, dict[str, float | str]], None]
_PCM_BYTES_PER_SAMPLE = 2
_PIPE_CHUNK_BYTES = 256 * 1024
_STDERR_TAIL_BYTES = 64 * 1024
_PIPE_EOF = object()


class AudioDecodeCancelled(Exception):
    pass


def assess_audio_quality(audio: np.ndarray, sampling_rate: int = 16_000) -> dict[str, float | str]:
    """Measure signal conditions without retaining or logging any audio content."""
    if audio.size == 0:
        return {
            "noiseFloorDb": -120.0,
            "speechLevelDb": -120.0,
            "clippingPercent": 0.0,
            "silencePercent": 100.0,
            "recommendedProfile": "off",
        }
    frame_samples = max(1, round(sampling_rate * 0.02))
    usable = audio[: audio.size - (audio.size % frame_samples)]
    if usable.size:
        rms = np.sqrt(np.mean(usable.reshape(-1, frame_samples) ** 2, axis=1) + 1e-12)
    else:
        rms = np.array([float(np.sqrt(np.mean(audio**2) + 1e-12))], dtype=np.float32)
    noise = float(np.percentile(rms, 18))
    speech = float(np.percentile(rms, 82))
    clipping = float(np.mean(np.abs(audio) >= 0.985) * 100)
    silence = float(np.mean(rms < max(0.0025, noise * 1.25)) * 100)
    separation_db = 20 * np.log10(max(speech, 1e-6) / max(noise, 1e-6))
    profile = "strong" if separation_db < 8 else "speech" if separation_db < 17 else "off"
    return {
        "noiseFloorDb": round(float(20 * np.log10(max(noise, 1e-6))), 1),
        "speechLevelDb": round(float(20 * np.log10(max(speech, 1e-6))), 1),
        "clippingPercent": round(clipping, 3),
        "silencePercent": round(silence, 1),
        "recommendedProfile": profile,
    }


def enhance_speech_audio(
    audio: np.ndarray,
    requested_profile: str,
    is_cancelled: Callable[[], bool],
    on_progress: EnhancementProgressCallback,
    sampling_rate: int = 16_000,
) -> tuple[np.ndarray, dict[str, float | str]]:
    """Apply a conservative adaptive noise gate and loudness normalization."""
    assessment = assess_audio_quality(audio, sampling_rate)
    profile = (
        str(assessment["recommendedProfile"])
        if requested_profile == "adaptive"
        else requested_profile
    )
    assessment["appliedProfile"] = profile
    total = int(audio.size)
    if profile == "off" or total == 0:
        on_progress(total, total, assessment)
        return audio, assessment

    output = np.empty_like(audio)
    chunk_samples = sampling_rate * 120
    frame_samples = max(1, round(sampling_rate * 0.02))
    minimum_gain = 0.3 if profile == "speech" else 0.12
    threshold_multiplier = 1.65 if profile == "speech" else 2.15
    for start in range(0, total, chunk_samples):
        if is_cancelled():
            raise AudioDecodeCancelled
        end = min(total, start + chunk_samples)
        block = audio[start:end].astype(np.float32, copy=True)
        block -= float(np.mean(block))
        frame_count = int(np.ceil(block.size / frame_samples))
        padded = np.pad(block, (0, frame_count * frame_samples - block.size))
        frames = padded.reshape(frame_count, frame_samples)
        rms = np.sqrt(np.mean(frames**2, axis=1) + 1e-12)
        noise_floor = max(0.0015, float(np.percentile(rms, 18)))
        threshold = noise_floor * threshold_multiplier
        # Smooth interpolation avoids chopping word beginnings and endings.
        strength = np.clip((rms - noise_floor) / max(threshold - noise_floor, 1e-6), 0, 1)
        gains = minimum_gain + (1 - minimum_gain) * strength
        gains = np.convolve(gains, np.ones(7, dtype=np.float32) / 7, mode="same")
        sample_gains = np.repeat(gains, frame_samples)[: block.size]
        output[start:end] = block * sample_gains
        on_progress(end, total, assessment)

    rms_value = float(np.sqrt(np.mean(output**2) + 1e-12))
    peak = float(np.max(np.abs(output)))
    gain = min(6.0, 0.095 / max(rms_value, 1e-6), 0.94 / max(peak, 1e-6))
    output *= gain
    assessment["normalizationGainDb"] = round(float(20 * np.log10(max(gain, 1e-6))), 1)
    return output, assessment


def decode_audio_with_progress(
    media_path: str,
    duration_ms: int,
    is_cancelled: Callable[[], bool],
    on_progress: ProgressCallback,
    sampling_rate: int = 16_000,
) -> np.ndarray:
    """Decode through bundled FFmpeg while reporting progress from received PCM."""
    source = Path(media_path)
    if not source.is_file():
        raise FileNotFoundError("El archivo no existe o fue movido.")
    ffmpeg = _find_tool("ffmpeg")
    if not ffmpeg:
        raise RuntimeError(
            "FFmpeg no está disponible. Reinstala Transcriptor para recuperar el motor multimedia."
        )
    if sampling_rate <= 0:
        raise ValueError("La frecuencia de muestreo debe ser mayor que cero.")

    total_ms = max(0, int(duration_ms or 0))
    on_progress(0, total_ms)
    command = [
        ffmpeg,
        "-hide_banner",
        "-nostdin",
        "-loglevel",
        "error",
        "-i",
        str(source.resolve()),
        "-map",
        "0:a:0",
        "-vn",
        "-ac",
        "1",
        "-ar",
        str(sampling_rate),
        "-f",
        "s16le",
        "pipe:1",
    ]
    creation_flags = (
        int(getattr(subprocess, "CREATE_NO_WINDOW", 0)) if sys.platform == "win32" else 0
    )
    try:
        process = subprocess.Popen(
            command,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            shell=False,
            bufsize=0,
            creationflags=creation_flags,
        )
    except OSError as error:
        raise RuntimeError(f"No se pudo iniciar FFmpeg: {error}") from error

    if process.stdout is None or process.stderr is None:  # pragma: no cover - subprocess contract
        _stop_process(process)
        raise RuntimeError("FFmpeg no pudo abrir sus canales de salida.")

    chunks: queue.Queue[bytes | object] = queue.Queue()
    stdout_errors: list[BaseException] = []
    stderr_tail = bytearray()
    stdout_thread = threading.Thread(
        target=_read_stdout,
        args=(process.stdout, chunks, stdout_errors),
        name="ffmpeg-pcm-reader",
        daemon=True,
    )
    stderr_thread = threading.Thread(
        target=_read_stderr,
        args=(process.stderr, stderr_tail),
        name="ffmpeg-error-reader",
        daemon=True,
    )
    stdout_thread.start()
    stderr_thread.start()

    raw_buffer = bytearray()
    last_report_at = time.monotonic()
    try:
        finished = False
        while not finished:
            if is_cancelled():
                _stop_process(process)
                raise AudioDecodeCancelled
            try:
                item = chunks.get(timeout=0.1)
            except queue.Empty:
                continue
            if item is _PIPE_EOF:
                finished = True
                continue
            raw_buffer.extend(item)
            sample_count = len(raw_buffer) // _PCM_BYTES_PER_SAMPLE
            processed_ms = round(sample_count / sampling_rate * 1000)
            now = time.monotonic()
            if now - last_report_at >= 0.25:
                reported_ms = min(total_ms, processed_ms) if total_ms else processed_ms
                on_progress(reported_ms, total_ms)
                last_report_at = now

        try:
            return_code = process.wait(timeout=30)
        except subprocess.TimeoutExpired as error:
            _stop_process(process)
            raise RuntimeError("FFmpeg dejó de responder al finalizar la decodificación.") from error
        stdout_thread.join(timeout=2)
        stderr_thread.join(timeout=2)
        if stdout_errors:
            raise RuntimeError("No se pudo leer el audio decodificado por FFmpeg.") from stdout_errors[0]
        if return_code != 0:
            raise ValueError(_decode_error_message(stderr_tail))
    finally:
        if process.poll() is None:
            _stop_process(process)
        process.stdout.close()
        process.stderr.close()
        stdout_thread.join(timeout=2)
        stderr_thread.join(timeout=2)

    if is_cancelled():
        raise AudioDecodeCancelled
    if len(raw_buffer) % _PCM_BYTES_PER_SAMPLE:
        raw_buffer.pop()
    sample_count = len(raw_buffer) // _PCM_BYTES_PER_SAMPLE
    processed_ms = round(sample_count / sampling_rate * 1000)
    final_total_ms = total_ms or processed_ms
    on_progress(final_total_ms, final_total_ms)
    audio = np.frombuffer(raw_buffer, dtype="<i2").astype(np.float32)
    audio /= 32768.0
    return audio


def _read_stdout(
    pipe: BinaryIO,
    chunks: queue.Queue[bytes | object],
    errors: list[BaseException],
) -> None:
    try:
        while chunk := pipe.read(_PIPE_CHUNK_BYTES):
            chunks.put(chunk)
    except BaseException as error:  # surfaced on the decoding worker
        errors.append(error)
    finally:
        chunks.put(_PIPE_EOF)


def _read_stderr(pipe: BinaryIO, tail: bytearray) -> None:
    try:
        while chunk := pipe.read(4096):
            tail.extend(chunk)
            if len(tail) > _STDERR_TAIL_BYTES:
                del tail[: len(tail) - _STDERR_TAIL_BYTES]
    except (OSError, ValueError):
        # Closing a pipe while cancelling can interrupt this reader on Windows.
        return


def _stop_process(process: subprocess.Popen[bytes]) -> None:
    if process.poll() is not None:
        return
    try:
        process.terminate()
        process.wait(timeout=3)
    except (OSError, subprocess.TimeoutExpired):
        try:
            process.kill()
            process.wait(timeout=3)
        except (OSError, subprocess.TimeoutExpired):
            return


def _decode_error_message(stderr_tail: bytearray) -> str:
    detail_lines = [
        line.strip()
        for line in stderr_tail.decode("utf-8", errors="replace").splitlines()
        if line.strip()
    ]
    detail = " · ".join(detail_lines[-3:])[-600:]
    lowered = detail.lower()
    if "matches no streams" in lowered or "does not contain any stream" in lowered:
        return "El archivo no contiene ninguna pista de audio."
    if not detail:
        return "FFmpeg no pudo decodificar el audio. El archivo puede estar dañado o no ser compatible."
    return f"FFmpeg no pudo decodificar el audio: {detail}"
