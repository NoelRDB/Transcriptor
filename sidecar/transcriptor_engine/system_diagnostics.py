from __future__ import annotations

import os
import shutil
import time
from pathlib import Path
from typing import Any

from .deep_insights import get_local_ai_status
from .hardware import get_hardware_info
from .media import _find_tool, analyze_media
from .paths import app_data_dir, models_dir


def diagnose_system(media_path: str | None = None, cuda_available: bool = False) -> dict[str, Any]:
    checks: list[dict[str, str]] = []

    def add(check_id: str, label: str, status: str, detail: str) -> None:
        checks.append({"id": check_id, "label": label, "status": status, "detail": detail})

    data_dir = app_data_dir()
    writable = os.access(data_dir, os.W_OK)
    add(
        "storage",
        "Carpeta de trabajo",
        "ok" if writable else "error",
        str(data_dir) if writable else "La aplicación no puede escribir en su carpeta de datos.",
    )
    disk = shutil.disk_usage(data_dir)
    free_gib = disk.free / (1024**3)
    add(
        "disk",
        "Espacio disponible",
        "ok" if free_gib >= 5 else "warning" if free_gib >= 1 else "error",
        f"{free_gib:.1f} GB libres",
    )

    ffmpeg = _find_tool("ffmpeg")
    ffprobe = _find_tool("ffprobe")
    add("ffmpeg", "FFmpeg", "ok" if ffmpeg else "error", ffmpeg or "No se encontró FFmpeg.")
    add("ffprobe", "FFprobe", "ok" if ffprobe else "error", ffprobe or "No se encontró FFprobe.")

    installed_models = sorted(path.name for path in models_dir().iterdir() if path.is_dir())
    add(
        "models",
        "Modelos de voz",
        "ok" if installed_models else "warning",
        (
            f"{len(installed_models)} modelo(s) almacenado(s)"
            if installed_models
            else "Aún no hay modelos descargados."
        ),
    )

    hardware = get_hardware_info(cuda_available)
    gpu = hardware.get("gpu")
    add(
        "compute",
        "Aceleración",
        "ok",
        (
            f"{gpu['name']} · CUDA disponible"
            if hardware.get("cudaAvailable") and gpu
            else "CPU disponible · CUDA no detectada"
        ),
    )

    ai = get_local_ai_status()
    add(
        "ollama",
        "IA de comprensión",
        "ok" if ai.get("available") and ai.get("installed") else "warning",
        (
            "Ollama y Qwen listos"
            if ai.get("available") and ai.get("installed")
            else "Ollama o el modelo Qwen no están listos."
        ),
    )

    media: dict[str, Any] | None = None
    media_candidates: list[str] = []
    if media_path:
        path = Path(media_path)
        if not path.is_file():
            media_candidates = _find_media_candidates(path)
            add(
                "media",
                "Archivo original",
                "error",
                (
                    f"No existe en la ruta guardada. Encontrado en: {media_candidates[0]}"
                    if media_candidates
                    else "No existe en la ruta guardada. Relocalízalo para continuar."
                ),
            )
        elif not os.access(path, os.R_OK):
            add("media", "Archivo original", "error", "El archivo existe, pero no se puede leer.")
        else:
            try:
                media = analyze_media(str(path))
                tracks = int(media.get("audioTracks", 0))
                add(
                    "media",
                    "Archivo original",
                    "ok" if tracks else "error",
                    f"Accesible · {tracks} pista(s) de audio" if tracks else "El archivo no contiene audio.",
                )
            except (OSError, ValueError) as error:
                add("media", "Archivo original", "error", str(error))

    errors = sum(item["status"] == "error" for item in checks)
    warnings = sum(item["status"] == "warning" for item in checks)
    return {
        "status": "error" if errors else "warning" if warnings else "ok",
        "checks": checks,
        "errors": errors,
        "warnings": warnings,
        "media": media,
        "hardware": hardware,
        "models": installed_models,
        "mediaCandidates": media_candidates,
    }


def _find_media_candidates(missing_path: Path, limit: int = 5) -> list[str]:
    filename = missing_path.name.casefold()
    if not filename:
        return []
    roots: list[Path] = [app_data_dir() / "recordings", app_data_dir() / "imports"]
    user_profile = os.environ.get("USERPROFILE")
    if user_profile:
        home = Path(user_profile)
        roots.extend([home / "Desktop", home / "Downloads", home / "Documents"])
    candidates: list[str] = []
    seen: set[Path] = set()
    deadline = time.monotonic() + 6
    ignored = {"node_modules", ".git", ".venv", "target", "AppData"}
    for root in roots:
        if not root.is_dir() or time.monotonic() >= deadline:
            continue
        for directory, child_directories, files in os.walk(root):
            child_directories[:] = [name for name in child_directories if name not in ignored]
            if time.monotonic() >= deadline:
                break
            for name in files:
                if name.casefold() != filename:
                    continue
                candidate = (Path(directory) / name).resolve()
                if candidate not in seen:
                    seen.add(candidate)
                    candidates.append(str(candidate))
                if len(candidates) >= limit:
                    return candidates
    return candidates
