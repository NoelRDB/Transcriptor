from __future__ import annotations

import json
import shutil
import subprocess
import sys
import wave
from pathlib import Path
from typing import Any

from .paths import executable_dir


def analyze_media(media_path: str) -> dict[str, Any]:
    path = Path(media_path)
    if not path.is_file():
        raise FileNotFoundError("El archivo no existe o fue movido.")
    probe = _find_tool("ffprobe")
    probe_error: BaseException | None = None
    if probe:
        try:
            return _analyze_ffprobe(probe, path)
        except (
            OSError,
            subprocess.SubprocessError,
            json.JSONDecodeError,
            KeyError,
            TypeError,
            ValueError,
        ) as error:
            probe_error = error
    try:
        return _analyze_wav(path)
    except (EOFError, OSError, wave.Error) as wav_error:
        if probe_error is not None:
            raise ValueError(_probe_error_message(probe_error)) from probe_error
        raise RuntimeError(
            "FFprobe no está disponible y el archivo no es un WAV PCM legible. "
            "Reinstala Transcriptor para recuperar el analizador multimedia."
        ) from wav_error


def _find_tool(name: str) -> str | None:
    extension = ".exe" if sys.platform == "win32" else ""
    development_root = Path(__file__).resolve().parents[1]
    candidates = [
        executable_dir() / "ffmpeg" / f"{name}{extension}",
        executable_dir() / f"{name}{extension}",
        development_root / "ffmpeg" / f"{name}{extension}",
    ]
    for candidate in candidates:
        if candidate.is_file():
            return str(candidate)
    return shutil.which(name)


def _analyze_ffprobe(probe: str, path: Path) -> dict[str, Any]:
    completed = subprocess.run(
        [
            probe,
            "-v",
            "error",
            "-show_entries",
            "format=duration,format_name:stream=index,codec_type,codec_name,width,height",
            "-of",
            "json",
            str(path.resolve()),
        ],
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=60,
        shell=False,
    )
    data = json.loads(completed.stdout)
    streams = data.get("streams", [])
    audio = [stream for stream in streams if stream.get("codec_type") == "audio"]
    video = next((stream for stream in streams if stream.get("codec_type") == "video"), {})
    duration = float(data.get("format", {}).get("duration") or 0)
    return {
        "durationMs": round(duration * 1000),
        "format": data.get("format", {}).get("format_name"),
        "codec": (audio[0] if audio else video).get("codec_name"),
        "width": video.get("width"),
        "height": video.get("height"),
        "audioTracks": len(audio),
        "analyzer": "ffprobe",
    }


def _analyze_wav(path: Path) -> dict[str, Any]:
    """Small stdlib fallback used when FFprobe is unavailable (for example in CI)."""
    with wave.open(str(path), "rb") as source:
        channels = source.getnchannels()
        sample_rate = source.getframerate()
        frames = source.getnframes()
        sample_width = source.getsampwidth()
        if channels < 1 or sample_rate < 1:
            raise wave.Error("invalid WAV parameters")
        duration_ms = round(frames / sample_rate * 1000)
    codec = {
        1: "pcm_u8",
        2: "pcm_s16le",
        3: "pcm_s24le",
        4: "pcm_s32le",
    }.get(sample_width, f"pcm_{sample_width * 8}bit")
    return {
        "durationMs": duration_ms,
        "format": "wav",
        "codec": codec,
        "width": None,
        "height": None,
        "audioTracks": 1,
        "analyzer": "wave",
    }


def _probe_error_message(error: BaseException) -> str:
    detail = ""
    if isinstance(error, subprocess.CalledProcessError):
        stderr = error.stderr
        if isinstance(stderr, bytes):
            detail = stderr.decode("utf-8", errors="replace")
        elif stderr:
            detail = str(stderr)
    detail_lines = [line.strip() for line in detail.splitlines() if line.strip()]
    if detail_lines:
        return (
            "No se pudo leer el archivo. Puede estar dañado o utilizar un formato no compatible: "
            + " · ".join(detail_lines[-2:])[:500]
        )
    return "No se pudo leer el archivo. Puede estar dañado o utilizar un formato no compatible."
