from __future__ import annotations

import os
import sys
from pathlib import Path

APP_DATA_DIRECTORY = "TranscriptorData"
LEGACY_APP_DATA_DIRECTORY = "Transcriptor"
_LEGACY_DATA_MARKERS = (
    "transcriptor.sqlite3",
    "models",
    "recordings",
    "imports",
    "logs",
)


def app_data_dir() -> Path:
    if sys.platform == "win32":
        root = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
    elif sys.platform == "darwin":
        root = Path.home() / "Library" / "Application Support"
    else:
        root = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share"))
    preferred = root / APP_DATA_DIRECTORY
    legacy = root / LEGACY_APP_DATA_DIRECTORY
    path = legacy if _contains_legacy_user_data(legacy) else preferred
    path.mkdir(parents=True, exist_ok=True)
    return path


def models_dir() -> Path:
    path = app_data_dir() / "models"
    path.mkdir(parents=True, exist_ok=True)
    return path


def executable_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(getattr(sys, "_MEIPASS", Path(sys.executable).resolve().parent))
    return Path(__file__).resolve().parents[2]


def _contains_legacy_user_data(path: Path) -> bool:
    return path.is_dir() and any((path / marker).exists() for marker in _LEGACY_DATA_MARKERS)
