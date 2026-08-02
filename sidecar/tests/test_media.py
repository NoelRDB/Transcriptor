from __future__ import annotations

import io
import json
import math
import struct
import wave
from types import SimpleNamespace

import pytest

import transcriptor_engine.audio as audio_module
import transcriptor_engine.media as media_module
from transcriptor_engine.audio import AudioDecodeCancelled, decode_audio_with_progress
from transcriptor_engine.media import analyze_media


class FakeFfmpegProcess:
    def __init__(self, pcm: bytes, *, stderr: bytes = b"", return_code: int = 0) -> None:
        self.stdout = io.BytesIO(pcm)
        self.stderr = io.BytesIO(stderr)
        self.expected_return_code = return_code
        self.returncode: int | None = None
        self.terminated = False
        self.killed = False

    def poll(self) -> int | None:
        return self.returncode

    def wait(self, timeout: float | None = None) -> int:
        del timeout
        if self.returncode is None:
            self.returncode = self.expected_return_code
        return self.returncode

    def terminate(self) -> None:
        self.terminated = True
        self.returncode = -15

    def kill(self) -> None:
        self.killed = True
        self.returncode = -9


def _wav(path, *, duration_samples: int = 1_600) -> None:
    with wave.open(str(path), "wb") as output:
        output.setnchannels(1)
        output.setsampwidth(2)
        output.setframerate(16_000)
        samples = [
            int(1000 * math.sin(2 * math.pi * 440 * index / 16_000))
            for index in range(duration_samples)
        ]
        output.writeframes(b"".join(struct.pack("<h", sample) for sample in samples))


def _mock_ffmpeg(monkeypatch, process: FakeFfmpegProcess):
    calls = []

    def popen(command, **options):
        calls.append((command, options))
        return process

    monkeypatch.setattr(audio_module, "_find_tool", lambda _name: "C:/Motor/ffmpeg.exe")
    monkeypatch.setattr(audio_module.subprocess, "Popen", popen)
    return calls


def test_analyze_unicode_wav_path_with_stdlib_fallback(tmp_path, monkeypatch):
    path = tmp_path / "audio con espacios ñ.wav"
    _wav(path)
    monkeypatch.setattr(media_module, "_find_tool", lambda _name: None)

    metadata = analyze_media(str(path))

    assert 90 <= metadata["durationMs"] <= 110
    assert metadata["audioTracks"] == 1
    assert metadata["codec"] == "pcm_s16le"
    assert metadata["analyzer"] == "wave"


def test_ffprobe_uses_unicode_path_as_one_argv_item(tmp_path, monkeypatch):
    path = tmp_path / "Grabación de Isabel ñ.wav"
    path.write_bytes(b"not read by mocked ffprobe")
    calls = []

    def run(command, **options):
        calls.append((command, options))
        return SimpleNamespace(
            stdout=json.dumps(
                {
                    "format": {"duration": "1.25", "format_name": "wav"},
                    "streams": [{"index": 0, "codec_type": "audio", "codec_name": "pcm_s16le"}],
                }
            )
        )

    monkeypatch.setattr(media_module, "_find_tool", lambda _name: "C:/Motor/ffprobe.exe")
    monkeypatch.setattr(media_module.subprocess, "run", run)

    metadata = analyze_media(str(path))

    command, options = calls[0]
    assert command[0] == "C:/Motor/ffprobe.exe"
    assert str(path.resolve()) in command
    assert options["shell"] is False
    assert metadata["durationMs"] == 1_250
    assert metadata["analyzer"] == "ffprobe"


def test_decode_audio_reports_progress_from_pcm_samples(tmp_path, monkeypatch):
    path = tmp_path / "progreso.wav"
    path.write_bytes(b"media")
    pcm = b"\0\0" * 16_000
    calls = _mock_ffmpeg(monkeypatch, FakeFfmpegProcess(pcm))
    events = []

    audio = decode_audio_with_progress(
        str(path), 1_000, lambda: False, lambda done, total: events.append((done, total))
    )

    assert len(audio) == 16_000
    assert events[0] == (0, 1_000)
    assert (1_000, 1_000) in events[1:]
    assert events[-1] == (1_000, 1_000)
    command, options = calls[0]
    assert command[-1] == "pipe:1"
    assert command[command.index("-ar") + 1] == "16000"
    assert options["shell"] is False
    assert options["stdin"] == audio_module.subprocess.DEVNULL


def test_decode_audio_preserves_unicode_path_in_argv(tmp_path, monkeypatch):
    path = tmp_path / "Grabación con espacios y ñ.wav"
    path.write_bytes(b"media")
    calls = _mock_ffmpeg(monkeypatch, FakeFfmpegProcess(b"\0\0" * 1_600))

    decode_audio_with_progress(str(path), 100, lambda: False, lambda *_: None)

    command, _options = calls[0]
    assert str(path.resolve()) in command
    assert command.count(str(path.resolve())) == 1


def test_decode_audio_cancellation_terminates_process(tmp_path, monkeypatch):
    path = tmp_path / "cancelar.wav"
    path.write_bytes(b"media")
    process = FakeFfmpegProcess(b"\0\0" * 16_000)
    _mock_ffmpeg(monkeypatch, process)

    with pytest.raises(AudioDecodeCancelled):
        decode_audio_with_progress(str(path), 1_000, lambda: True, lambda *_: None)

    assert process.terminated
    assert process.poll() is not None


def test_decode_audio_drains_stderr_and_returns_readable_error(tmp_path, monkeypatch):
    path = tmp_path / "dañado.ogg"
    path.write_bytes(b"media")
    stderr = b"x" * 70_000 + b"\nInvalid data found when processing input\n"
    process = FakeFfmpegProcess(b"", stderr=stderr, return_code=1)
    _mock_ffmpeg(monkeypatch, process)

    with pytest.raises(ValueError, match="Invalid data found"):
        decode_audio_with_progress(str(path), 0, lambda: False, lambda *_: None)

    assert process.poll() == 1
