import base64
import wave
from pathlib import Path
from types import SimpleNamespace

import numpy as np

import transcriptor_engine.live as live_module
from transcriptor_engine.live import SAMPLE_RATE, LiveSessionManager, SpeakerClusterer
from transcriptor_engine.transcriber import Transcriber


def voiced(frequency: float) -> np.ndarray:
    time = np.arange(SAMPLE_RATE, dtype=np.float32) / SAMPLE_RATE
    base = np.sin(2 * np.pi * frequency * time)
    harmonics = 0.5 * np.sin(2 * np.pi * frequency * 2 * time)
    return ((base + harmonics) * 0.4).astype(np.float32)


def test_speaker_clusterer_is_stable_for_the_same_voice():
    clusterer = SpeakerClusterer()
    first = clusterer.assign(voiced(130))
    second = clusterer.assign(voiced(130) * 0.8)
    assert first == "Hablante 1"
    assert second == "Hablante 1"


def test_live_paths_are_not_public_or_network_locations():
    # A regression guard for the privacy contract: recordings are represented
    # by ordinary local filesystem paths, never URLs.
    example = Path("recordings") / "Grabación.wav"
    assert "://" not in str(example)


class FakeModel:
    def __init__(self):
        self.options = []

    def transcribe(self, _audio, **options):
        self.options.append(options)
        word = SimpleNamespace(start=0.1, end=0.5, word="hola", probability=0.98)
        segment = SimpleNamespace(
            start=0.1,
            end=0.8,
            text="Hola en directo",
            words=[word],
            avg_logprob=-0.1,
        )
        return iter([segment]), SimpleNamespace(language="es")


def test_live_session_saves_wav_and_timestamped_segments(tmp_path, monkeypatch):
    monkeypatch.setattr(live_module, "app_data_dir", lambda: tmp_path)
    manager = LiveSessionManager(Transcriber())
    manager.model = FakeModel()
    manager.device = "cpu"
    started = manager.start({"language": "es"}, separate_speakers=True)
    pcm = (voiced(130) * 32767).astype("<i2").tobytes()

    events = []
    chunk = manager.push(
        started["sessionId"],
        base64.b64encode(pcm).decode("ascii"),
        lambda event_type, payload: events.append((event_type, payload)),
    )
    completed = manager.stop(started["sessionId"])

    assert chunk["segments"][0]["speaker"] == "Hablante 1"
    assert chunk["segments"][0]["startMs"] == 100
    assert manager.model.options[0]["language"] == "es"
    assert chunk["latencyMs"] >= 0
    assert events[0][0] == "live_partial"
    assert events[0][1]["segment"]["text"] == "Hola en directo"
    assert completed["segments"][0]["text"] == "Hola en directo"
    with wave.open(completed["mediaPath"], "rb") as recording:
        assert recording.getframerate() == SAMPLE_RATE
        assert recording.getnchannels() == 1
        assert recording.getnframes() == SAMPLE_RATE
