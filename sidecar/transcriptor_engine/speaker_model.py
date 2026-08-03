from __future__ import annotations

import importlib.util
from pathlib import Path
from typing import Any

from .paths import models_dir

MODEL_NAME = "3dspeaker_speech_campplus_sv_zh_en_16k-common_advanced.onnx"
MODEL_URL = f"https://github.com/k2-fsa/sherpa-onnx/releases/download/speaker-recongition-models/{MODEL_NAME}"
MODEL_SHA256 = "aa3cfc16963a10586a9393f5035d6d6b57e98d358b347f80c2a30bf4f00ceba2"
MODEL_BYTES = 28_281_164


def speaker_model_path() -> Path:
    return models_dir() / "speaker" / MODEL_NAME


def speaker_ai_status() -> dict[str, Any]:
    """Inspect the local model without importing NumPy or ONNX Runtime."""
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


def _pyannote_available() -> bool:
    try:
        return importlib.util.find_spec("pyannote.audio") is not None
    except (ImportError, ModuleNotFoundError, ValueError):
        return False
