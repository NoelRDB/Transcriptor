from __future__ import annotations

import numpy as np

from transcriptor_engine.database import ProjectDatabase
from transcriptor_engine.voice_crypto import protect_embedding, unprotect_embedding


def _voice(seed: int) -> np.ndarray:
    generator = np.random.default_rng(seed)
    vector = generator.normal(size=192).astype(np.float32)
    return vector / np.linalg.norm(vector)


def test_voice_embedding_roundtrip_is_protected_for_the_current_account() -> None:
    voice = _voice(7)

    protected = protect_embedding(voice)
    restored = unprotect_embedding(protected)

    assert protected != voice.tobytes()
    assert float(np.dot(voice, restored)) > 0.999


def test_learning_creates_reuses_and_deletes_a_local_voice_profile(tmp_path) -> None:
    database = ProjectDatabase(tmp_path / "voice-profiles.sqlite3")
    voice = _voice(12)

    first = database.learn_voice_observations(
        "project-one",
        [
            {
                "cluster": 1,
                "suggestedName": "Hablante 1",
                "samples": [
                    {
                        "embedding": voice.tolist(),
                        "segmentId": "segment-one",
                        "durationMs": 2_200,
                        "confidence": 0.91,
                    }
                ],
            }
        ],
    )

    profile = first["profiles"][0]
    assert profile["name"] == "Hablante 1"
    assert profile["sampleCount"] == 1
    assert first["storesRawAudio"] is False
    matcher = database.load_voice_matcher_profiles()[0]
    assert matcher["name"] == "Hablante 1"
    assert float(np.dot(voice, np.asarray(matcher["centroid"]))) > 0.999

    database.update_voice_profile(profile["id"], name="Noel")
    second = database.learn_voice_observations(
        "project-two",
        [
            {
                "cluster": 1,
                "suggestedName": "Noel",
                "matchedProfileId": profile["id"],
                "samples": [
                    {
                        "embedding": voice.tolist(),
                        "segmentId": "segment-two",
                        "durationMs": 1_900,
                        "confidence": 0.88,
                    }
                ],
            }
        ],
    )

    assert second["profiles"][0]["name"] == "Noel"
    assert second["profiles"][0]["sampleCount"] == 2
    assert second["profiles"][0]["sourceProjectCount"] == 2
    database.delete_voice_profile(profile["id"])
    assert database.list_voice_profiles()["profiles"] == []


def test_learning_reports_why_uncertain_audio_was_not_stored(tmp_path) -> None:
    database = ProjectDatabase(tmp_path / "voice-rejections.sqlite3")
    voice = _voice(32)

    result = database.learn_voice_observations(
        "project-uncertain",
        [
            {
                "cluster": 1,
                "samples": [
                    {
                        "embedding": voice.tolist(),
                        "segmentId": "uncertain-segment",
                        "durationMs": 2_100,
                        "confidence": 0.61,
                    }
                ],
            }
        ],
        min_confidence=0.72,
    )

    assert result["profiles"] == []
    assert result["receivedSamples"] == 1
    assert result["rejectedSamples"] == 1
    assert result["rejectionReasons"]["lowConfidence"] == 1
