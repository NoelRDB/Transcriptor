from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path
from typing import Any

import av

from .paths import executable_dir


def analyze_media(media_path: str) -> dict[str, Any]:
    path = Path(media_path)
    if not path.is_file():
        raise FileNotFoundError("El archivo no existe o fue movido.")
    probe = _find_tool("ffprobe")
    if probe:
        try:
            return _analyze_ffprobe(probe, path)
        except (subprocess.SubprocessError, json.JSONDecodeError, KeyError):
            pass
    return _analyze_pyav(path)


def _find_tool(name: str) -> str | None:
    extension = ".exe" if __import__("sys").platform == "win32" else ""
    candidates = [executable_dir() / "ffmpeg" / f"{name}{extension}", executable_dir() / f"{name}{extension}"]
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
            str(path),
        ],
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=60,
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


def _analyze_pyav(path: Path) -> dict[str, Any]:
    try:
        with av.open(str(path)) as container:
            audio = list(container.streams.audio)
            video = list(container.streams.video)
            if not audio:
                raise ValueError("El archivo no contiene ninguna pista de audio.")
            duration = float(container.duration or 0) / av.time_base
            first_video = video[0] if video else None
            return {
                "durationMs": round(duration * 1000),
                "format": container.format.name,
                "codec": audio[0].codec_context.name,
                "width": getattr(first_video, "width", None),
                "height": getattr(first_video, "height", None),
                "audioTracks": len(audio),
                "analyzer": "pyav",
            }
    except av.AVError as error:
        raise ValueError(
            "No se pudo leer el archivo. Puede estar dañado o utilizar un formato no compatible."
        ) from error
