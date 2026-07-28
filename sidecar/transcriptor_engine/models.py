from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any

from .paths import models_dir

GIB = 1024**3
DOWNLOAD_HEADROOM_BYTES = 512 * 1024**2
REQUIRED_MODEL_FILES = (
    "config.json",
    "model.bin",
    "tokenizer.json",
    "vocabulary.json",
)

MODEL_CATALOG = (
    {
        "id": "tiny",
        "name": "Tiny",
        "sizeGiB": 0.08,
        "memoryGiB": 1,
        "speed": "Extrema",
        "accuracy": "Básica",
        "description": "Pruebas rápidas y equipos con muy poca memoria.",
        "recommended": False,
    },
    {
        "id": "small",
        "name": "Small",
        "sizeGiB": 0.5,
        "memoryGiB": 2,
        "speed": "Muy rápida",
        "accuracy": "Buena",
        "description": "Audio claro y transcripciones cotidianas.",
        "recommended": False,
    },
    {
        "id": "turbo",
        "name": "Turbo",
        "sizeGiB": 1.6,
        "memoryGiB": 4,
        "speed": "Rápida",
        "accuracy": "Muy buena",
        "description": "Mejor equilibrio para directo y primera pasada.",
        "recommended": True,
    },
    {
        "id": "large-v3",
        "name": "Large‑v3",
        "sizeGiB": 3.1,
        "memoryGiB": 6,
        "speed": "Exigente",
        "accuracy": "Máxima",
        "description": "Acentos difíciles, ruido y revisión profesional.",
        "recommended": False,
    },
)


def list_models() -> dict[str, Any]:
    root = models_dir().resolve()
    disk = shutil.disk_usage(root)
    entries = []
    for model in MODEL_CATALOG:
        paths = _model_paths(root, str(model["id"]))
        installed_bytes = sum(_directory_size(path) for path in paths if path.is_dir())
        ready_path = next(
            (
                path
                for path in paths
                if _has_complete_model_files(path)
            ),
            None,
        )
        present_files = {
            filename
            for filename in REQUIRED_MODEL_FILES
            if any((path / filename).is_file() for path in paths)
        }
        missing_files = [
            filename for filename in REQUIRED_MODEL_FILES if filename not in present_files
        ]
        download_bytes = max(
            0,
            round(float(model["sizeGiB"]) * GIB) - installed_bytes,
        )
        installed = ready_path is not None
        required_free_bytes = 0 if installed else download_bytes + DOWNLOAD_HEADROOM_BYTES
        entries.append(
            {
                **model,
                "installed": installed,
                "installedBytes": installed_bytes,
                "paths": [str(path) for path in paths if path.exists()],
                "integrity": (
                    "ready"
                    if installed
                    else "partial"
                    if installed_bytes > 0
                    else "missing"
                ),
                "missingFiles": [] if installed else missing_files,
                "downloadBytes": download_bytes,
                "requiredFreeBytes": required_free_bytes,
                "canInstall": installed or disk.free >= required_free_bytes,
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


def _has_complete_model_files(path: Path) -> bool:
    model_binary = path / "model.bin"
    if not model_binary.is_file() or model_binary.stat().st_size < 1024**2:
        return False
    for filename in ("config.json", "tokenizer.json", "vocabulary.json"):
        candidate = path / filename
        if not candidate.is_file() or candidate.stat().st_size < 2:
            return False
        try:
            with candidate.open("r", encoding="utf-8") as stream:
                json.load(stream)
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            return False
    return True
