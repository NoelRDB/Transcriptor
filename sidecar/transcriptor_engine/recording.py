from __future__ import annotations

import base64
import threading
import uuid
import wave
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .paths import app_data_dir

SAMPLE_RATE = 16_000
MAX_CHUNK_BYTES = SAMPLE_RATE * 2 * 30


@dataclass
class RecordingSession:
    id: str
    raw_path: Path
    wav_path: Path
    language: str
    created_at: str
    samples_written: int = 0
    received_chunks: set[int] = field(default_factory=set)
    lock: threading.Lock = field(default_factory=threading.Lock)


class RecordingSessionManager:
    """Persist microphone/system PCM without running transcription or speaker AI."""

    def __init__(self) -> None:
        self.sessions: dict[str, RecordingSession] = {}

    @property
    def active(self) -> bool:
        return bool(self.sessions)

    def start(self, language: str = "auto") -> dict[str, Any]:
        if self.sessions:
            raise ValueError("Ya hay una grabación activa.")
        recordings = app_data_dir() / "recordings"
        recordings.mkdir(parents=True, exist_ok=True)
        session_id = str(uuid.uuid4())
        timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        raw_path = recordings / f"Grabación {timestamp}-{session_id[:8]}.pcm"
        wav_path = recordings / f"Grabación {timestamp}-{session_id[:8]}.wav"
        raw_path.touch()
        created_at = datetime.now(UTC).isoformat()
        self.sessions[session_id] = RecordingSession(
            id=session_id,
            raw_path=raw_path,
            wav_path=wav_path,
            language=self._normalize_language(language),
            created_at=created_at,
        )
        return {
            "sessionId": session_id,
            "sampleRate": SAMPLE_RATE,
            "createdAt": created_at,
        }

    def push(self, session_id: str, encoded_pcm: str, chunk_id: int) -> dict[str, Any]:
        session = self._session(session_id)
        if chunk_id < 0:
            raise ValueError("El identificador del bloque de audio no es válido.")
        try:
            pcm_bytes = base64.b64decode(encoded_pcm, validate=True)
        except ValueError as error:
            raise ValueError("El bloque de audio recibido no es válido.") from error
        if not pcm_bytes or len(pcm_bytes) % 2 or len(pcm_bytes) > MAX_CHUNK_BYTES:
            raise ValueError("El bloque de audio tiene un tamaño no válido.")
        with session.lock:
            if chunk_id in session.received_chunks:
                duration_ms = round(session.samples_written / SAMPLE_RATE * 1000)
                return {"sessionId": session_id, "durationMs": duration_ms, "duplicate": True}
            with session.raw_path.open("ab") as target:
                target.write(pcm_bytes)
            session.samples_written += len(pcm_bytes) // 2
            session.received_chunks.add(chunk_id)
            duration_ms = round(session.samples_written / SAMPLE_RATE * 1000)
        return {"sessionId": session_id, "durationMs": duration_ms, "duplicate": False}

    def stop(self, session_id: str) -> dict[str, Any]:
        session = self._session(session_id)
        with session.lock:
            self._finalize_wav(session)
            duration_ms = round(session.samples_written / SAMPLE_RATE * 1000)
        self.sessions.pop(session_id, None)
        return {
            "sessionId": session.id,
            "mediaPath": str(session.wav_path),
            "durationMs": duration_ms,
            "language": session.language,
            "createdAt": session.created_at,
        }

    def cancel(self, session_id: str) -> None:
        session = self._session(session_id)
        with session.lock:
            session.raw_path.unlink(missing_ok=True)
            session.wav_path.unlink(missing_ok=True)
        self.sessions.pop(session_id, None)

    def cancel_all(self) -> None:
        for session_id in list(self.sessions):
            self.cancel(session_id)

    @staticmethod
    def _normalize_language(language: str) -> str:
        candidate = str(language or "auto").strip().lower()
        return candidate if candidate else "auto"

    @staticmethod
    def _finalize_wav(session: RecordingSession) -> None:
        with wave.open(str(session.wav_path), "wb") as output:
            output.setnchannels(1)
            output.setsampwidth(2)
            output.setframerate(SAMPLE_RATE)
            with session.raw_path.open("rb") as source:
                while block := source.read(1024 * 1024):
                    output.writeframesraw(block)
        session.raw_path.unlink(missing_ok=True)

    def _session(self, session_id: str) -> RecordingSession:
        session = self.sessions.get(session_id)
        if not session:
            raise KeyError("La sesión de grabación ya no existe.")
        return session
