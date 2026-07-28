from __future__ import annotations

import io
import time
from collections.abc import Callable

import av
import numpy as np

ProgressCallback = Callable[[int, int], None]
EnhancementProgressCallback = Callable[[int, int, dict[str, float | str]], None]


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
    """Decode and normalize audio while reporting real decoded timeline progress."""
    raw_buffer = io.BytesIO()
    sample_count = 0
    last_report_at = 0.0
    resampler = av.audio.resampler.AudioResampler(format="s16", layout="mono", rate=sampling_rate)

    # Passing a Unicode Windows path directly to FFmpeg/PyAV can fail in a
    # frozen PyInstaller build even though Python can open it. A native file
    # handle keeps accents, spaces and long paths out of FFmpeg's path parser.
    with (
        open(media_path, "rb") as media_source,
        av.open(media_source, mode="r", metadata_errors="ignore") as container,
    ):
        if not container.streams.audio:
            raise ValueError("El archivo no contiene ninguna pista de audio.")
        total_ms = duration_ms or round(float(container.duration or 0) / av.time_base * 1000)
        on_progress(0, total_ms)

        def consume(frame: av.AudioFrame) -> None:
            nonlocal sample_count, last_report_at
            array = frame.to_ndarray()
            raw_buffer.write(array.tobytes())
            sample_count += int(array.size)
            now = time.monotonic()
            if now - last_report_at >= 0.25:
                processed_ms = round(sample_count / sampling_rate * 1000)
                on_progress(min(total_ms, processed_ms) if total_ms else processed_ms, total_ms)
                last_report_at = now

        for frame in container.decode(audio=0):
            if is_cancelled():
                raise AudioDecodeCancelled
            for normalized in resampler.resample(frame):
                consume(normalized)

        for normalized in resampler.resample(None):
            consume(normalized)

    if is_cancelled():
        raise AudioDecodeCancelled
    processed_ms = round(sample_count / sampling_rate * 1000)
    on_progress(total_ms or processed_ms, total_ms or processed_ms)
    audio = np.frombuffer(raw_buffer.getbuffer(), dtype=np.int16).astype(np.float32)
    audio /= 32768.0
    return audio
