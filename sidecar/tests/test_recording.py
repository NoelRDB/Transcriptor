from __future__ import annotations

import base64
import wave

import pytest

import transcriptor_engine.recording as recording_module
from transcriptor_engine.recording import SAMPLE_RATE, RecordingSessionManager


def test_recording_session_writes_a_local_mono_wav(monkeypatch, tmp_path):
    monkeypatch.setattr(recording_module, "app_data_dir", lambda: tmp_path)
    manager = RecordingSessionManager()
    started = manager.start("es")
    pcm = b"\x10\x00" * SAMPLE_RATE

    first = manager.push(started["sessionId"], base64.b64encode(pcm).decode("ascii"), 0)
    duplicate = manager.push(started["sessionId"], base64.b64encode(pcm).decode("ascii"), 0)
    result = manager.stop(started["sessionId"])

    assert first == {"sessionId": started["sessionId"], "durationMs": 1000, "duplicate": False}
    assert duplicate["duplicate"] is True
    assert result["durationMs"] == 1000
    assert result["language"] == "es"
    assert manager.active is False
    with wave.open(result["mediaPath"], "rb") as saved:
        assert saved.getnchannels() == 1
        assert saved.getsampwidth() == 2
        assert saved.getframerate() == SAMPLE_RATE
        assert saved.getnframes() == SAMPLE_RATE
        assert saved.readframes(SAMPLE_RATE) == pcm
    assert not list((tmp_path / "recordings").glob("*.pcm"))


def test_cancel_removes_the_unfinished_recording(monkeypatch, tmp_path):
    monkeypatch.setattr(recording_module, "app_data_dir", lambda: tmp_path)
    manager = RecordingSessionManager()
    started = manager.start("auto")
    manager.push(started["sessionId"], base64.b64encode(b"\x00\x00" * 20).decode("ascii"), 0)

    manager.cancel(started["sessionId"])

    assert manager.active is False
    assert not list((tmp_path / "recordings").iterdir())


@pytest.mark.parametrize("payload", ["not-base64", "AA==", ""])
def test_invalid_audio_blocks_are_rejected(monkeypatch, tmp_path, payload):
    monkeypatch.setattr(recording_module, "app_data_dir", lambda: tmp_path)
    manager = RecordingSessionManager()
    started = manager.start("es")

    with pytest.raises(ValueError, match="bloque de audio"):
        manager.push(started["sessionId"], payload, 0)
