from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any

from .paths import models_dir

MODEL_CATALOG = (
    {
        "id": "tiny",
        "name": "Tiny",
        "sizeGiB": 0.08,
        "memoryGiB": 1,
        "speed": "Extrema",
        "accuracy": "Básica",
        "description": "Pruebas rápidas y equipos con muy poca memoria.",
    },
    {
        "id": "small",
        "name": "Small",
        "sizeGiB": 0.5,
        "memoryGiB": 2,
        "speed": "Muy rápida",
        "accuracy": "Buena",
        "description": "Audio claro y transcripciones cotidianas.",
    },
    {
        "id": "turbo",
        "name": "Turbo",
        "sizeGiB": 1.6,
        "memoryGiB": 4,
        "speed": "Rápida",
        "accuracy": "Muy buena",
        "description": "Mejor equilibrio para directo y primera pasada.",
    },
    {
        "id": "large-v3",
        "name": "Large‑v3",
        "sizeGiB": 3.1,
        "memoryGiB": 6,
        "speed": "Exigente",
        "accuracy": "Máxima",
        "description": "Acentos difíciles, ruido y revisión profesional.",
    },
)


def list_models() -> dict[str, Any]:
    root = models_dir().resolve()
    disk = shutil.disk_usage(root)
    entries = []
    for model in MODEL_CATALOG:
        paths = _model_paths(root, str(model["id"]))
        installed_bytes = sum(_directory_size(path) for path in paths if path.is_dir())
        entries.append(
            {
                **model,
                "installed": installed_bytes > 0 and any((path / "config.json").is_file() for path in paths),
                "installedBytes": installed_bytes,
                "paths": [str(path) for path in paths if path.exists()],
            }
        )
    return {"models": entries, "root": str(root), "freeBytes": disk.free}


def delete_model(model_id: str) -> dict[str, Any]:
    allowed = {str(item["id"]) for item in MODEL_CATALOG}
    if model_id not in allowed:
        raise ValueError("El modelo solicitado no pertenece al catálogo permitido.")
    root = models_dir().resolve()
    removed_bytes = 0
    removed_paths: list[str] = []
    for path in _model_paths(root, model_id):
        resolved = path.resolve()
        if not resolved.is_relative_to(root) or not resolved.is_dir():
            continue
        removed_bytes += _directory_size(resolved)
        shutil.rmtree(resolved)
        removed_paths.append(str(resolved))
    return {"modelId": model_id, "deleted": bool(removed_paths), "removedBytes": removed_bytes}


def _model_paths(root: Path, model_id: str) -> list[Path]:
    repo_suffix = {
        "tiny": "models--Systran--faster-whisper-tiny",
        "small": "models--Systran--faster-whisper-small",
        "turbo": "models--mobiuslabsgmbh--faster-whisper-large-v3-turbo",
        "large-v3": "models--Systran--faster-whisper-large-v3",
    }[model_id]
    return [root / model_id, root / repo_suffix]


def _directory_size(path: Path) -> int:
    return sum(item.stat().st_size for item in path.rglob("*") if item.is_file())
