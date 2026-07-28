from __future__ import annotations

import math
import struct
import wave

import transcriptor_engine.audio as audio_module
from transcriptor_engine.audio import AudioDecodeCancelled, decode_audio_with_progress
from transcriptor_engine.media import analyze_media


def test_analyze_unicode_wav_path(tmp_path):
    path = tmp_path / "audio con espacios ñ.wav"
    with wave.open(str(path), "wb") as output:
        output.setnchannels(1)
        output.setsampwidth(2)
        output.setframerate(16_000)
        samples = [int(1000 * math.sin(2 * math.pi * 440 * i / 16_000)) for i in range(1600)]
        output.writeframes(b"".join(struct.pack("<h", sample) for sample in samples))
    metadata = analyze_media(str(path))
    assert 90 <= metadata["durationMs"] <= 110
    assert metadata["audioTracks"] == 1


def test_decode_audio_reports_real_progress(tmp_path):
    path = tmp_path / "progreso.wav"
    with wave.open(str(path), "wb") as output:
        output.setnchannels(1)
        output.setsampwidth(2)
        output.setframerate(16_000)
        output.writeframes(b"\0\0" * 16_000)
    events = []

    audio = decode_audio_with_progress(
        str(path), 1_000, lambda: False, lambda done, total: events.append((done, total))
    )

    assert len(audio) == 16_000
    assert events[0] == (0, 1_000)
    assert events[-1] == (1_000, 1_000)


def test_decode_audio_uses_a_native_file_handle_for_unicode_windows_paths(tmp_path, monkeypatch):
    path = tmp_path / "Grabación con ñ.wav"
    with wave.open(str(path), "wb") as output:
        output.setnchannels(1)
        output.setsampwidth(2)
        output.setframerate(16_000)
        output.writeframes(b"\0\0" * 1600)
    original_open = audio_module.av.open
    opened_sources = []

    def tracked_open(source, *args, **kwargs):
        opened_sources.append(source)
        return original_open(source, *args, **kwargs)

    monkeypatch.setattr(audio_module.av, "open", tracked_open)
    decode_audio_with_progress(str(path), 100, lambda: False, lambda *_: None)

    assert opened_sources
    assert hasattr(opened_sources[0], "read")
    assert not isinstance(opened_sources[0], str)


def test_decode_audio_can_be_cancelled(tmp_path):
    path = tmp_path / "cancelar.wav"
    with wave.open(str(path), "wb") as output:
        output.setnchannels(1)
        output.setsampwidth(2)
        output.setframerate(16_000)
        output.writeframes(b"\0\0" * 16_000)

    try:
        decode_audio_with_progress(str(path), 1_000, lambda: True, lambda *_: None)
    except AudioDecodeCancelled:
        pass
    else:
        raise AssertionError("La decodificación debió cancelarse")
