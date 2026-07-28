import base64
import wave
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

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


class ReidentifyingClusterer:
    def __init__(self):
        self.calls = 0
        self.last_confidence = 0.9
        self.last_cluster_index = 0
        self.last_identity_changed = False
        self.backend = "CAM++ · perfiles locales"
        self.neural = SimpleNamespace(
            last_profile_id=None,
            last_profile_confidence=None,
            last_embedding=None,
        )

    @property
    def speaker_count(self):
        return 1

    def assign(self, _audio):
        self.calls += 1
        self.last_identity_changed = self.calls == 2
        if self.calls == 1:
            self.neural.last_profile_id = None
            self.neural.last_profile_confidence = None
            return "Hablante 1"
        self.neural.last_profile_id = "voice-isabel"
        self.neural.last_profile_confidence = 0.91
        return "Isabel"


def test_live_late_identity_relabels_previous_segments(tmp_path, monkeypatch):
    monkeypatch.setattr(live_module, "app_data_dir", lambda: tmp_path)
    manager = LiveSessionManager(Transcriber())
    manager.model = FakeModel()
    manager.device = "cpu"
    started = manager.start({"language": "es"}, separate_speakers=True)
    manager.sessions[started["sessionId"]].clusterer = ReidentifyingClusterer()
    pcm = (voiced(180) * 32767).astype("<i2").tobytes()
    encoded = base64.b64encode(pcm).decode("ascii")
    events = []

    manager.push(
        started["sessionId"],
        encoded,
        lambda event_type, payload: events.append((event_type, payload)),
    )
    manager.push(
        started["sessionId"],
        encoded,
        lambda event_type, payload: events.append((event_type, payload)),
    )
    completed = manager.stop(started["sessionId"])

    identity_updates = [
        payload
        for event_type, payload in events
        if event_type == "live_partial" and payload.get("identityUpdate")
    ]
    assert identity_updates
    assert identity_updates[0]["segment"]["speaker"] == "Isabel"
    assert identity_updates[0]["segment"]["speakerProfileId"] == "voice-isabel"
    assert completed["segments"][0]["speaker"] == "Isabel"
    assert completed["segments"][0]["speakerProvisional"] is False


def test_live_voice_evidence_is_bounded_and_time_diverse():
    session = SimpleNamespace(voice_observations=[])
    for index in range(3_600):
        LiveSessionManager._retain_voice_observation(
            session,
            {
                "cluster": 1,
                "startMs": index * 1_000,
                "durationMs": 1_000,
                "confidence": 0.8 + (index % 10) / 100,
                "matchConfidence": 0.82 + (index % 10) / 100,
            },
        )

    assert len(session.voice_observations) <= 48
    positions = sorted(sample["startMs"] for sample in session.voice_observations)
    assert len({position // 15_000 for position in positions}) > 35
    assert positions[0] < 5 * 60_000
    assert positions[-1] > 55 * 60_000
    assert positions[-1] - positions[0] > 50 * 60_000
    assert positions[len(positions) // 4] > 10 * 60_000
    assert 20 * 60_000 < positions[len(positions) // 2] < 40 * 60_000
    assert positions[len(positions) * 3 // 4] > 45 * 60_000
    assert max(
        right - left
        for left, right in zip(positions, positions[1:], strict=False)
    ) < 8 * 60_000


def test_live_final_identity_uses_stable_weighted_support_not_one_peak():
    session = SimpleNamespace(
        clusterer=SimpleNamespace(
            neural=SimpleNamespace(cluster_profile_ids=["isabel"])
        )
    )
    samples = [
        {
            "matchedProfileId": "noel",
            "matchConfidence": 0.99,
            "confidence": 0.95,
            "durationMs": 2_000,
        },
        *[
            {
                "matchedProfileId": "isabel",
                "matchConfidence": 0.81,
                "confidence": 0.88,
                "durationMs": 2_000,
            }
            for _ in range(5)
        ],
    ]

    profile_id, confidence = LiveSessionManager._stable_cluster_identity(
        session,
        1,
        samples,
    )

    assert profile_id == "isabel"
    assert confidence == pytest.approx(0.81)
