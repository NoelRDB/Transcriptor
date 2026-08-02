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


def _platform_data_root() -> Path:
    if sys.platform == "win32":
        return Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support"
    return Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share"))


def preferred_app_data_dir() -> Path:
    """Return the stable data root used by newly managed application runtimes."""
    path = _platform_data_root() / APP_DATA_DIRECTORY
    path.mkdir(parents=True, exist_ok=True)
    return path


def app_data_dir() -> Path:
    root = _platform_data_root()
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
