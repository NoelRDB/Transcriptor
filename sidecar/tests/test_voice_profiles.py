from __future__ import annotations

import numpy as np
import pytest

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


def test_duplicate_voice_profiles_can_be_compared_and_merged_transactionally(tmp_path) -> None:
    database = ProjectDatabase(tmp_path / "voice-merge.sqlite3")
    voice = _voice(44)
    first = database.learn_voice_observations(
        "conversation-one",
        [{
            "cluster": 1,
            "suggestedName": "Hablante 1",
            "samples": [{
                "embedding": voice.tolist(),
                "segmentId": "segment-source",
                "durationMs": 2_400,
                "confidence": 0.93,
            }],
        }],
    )
    source = first["profiles"][0]
    second = database.learn_voice_observations(
        "conversation-two",
        [{
            "cluster": 1,
            "suggestedName": "Noel",
            "samples": [{
                "embedding": voice.tolist(),
                "segmentId": "segment-target",
                "durationMs": 2_000,
                "confidence": 0.9,
            }],
        }],
    )
    target = next(profile for profile in second["profiles"] if profile["name"] == "Noel")
    database.save_project({
        "id": "conversation-one",
        "name": "Conversación",
        "mediaPath": "C:/audio/conversation.wav",
        "mediaType": "audio",
        "durationMs": 2_400,
        "model": "turbo",
        "createdAt": "2026-07-28T00:00:00Z",
        "updatedAt": "2026-07-28T00:00:00Z",
        "transcriptionStatus": "completed",
        "lastPlaybackPositionMs": 0,
        "settings": {"language": "es", "model": "turbo"},
        "segments": [{
            "id": "segment-source",
            "startMs": 0,
            "endMs": 2_400,
            "text": "Esta voz es de Noel.",
            "speaker": "Hablante 1",
            "speakerProfileId": source["id"],
            "speakerMatchConfidence": 0.91,
            "confidence": 0.95,
            "order": 0,
            "words": [],
        }],
    })

    comparison = database.compare_voice_profiles(source["id"], target["id"])
    assert comparison["similarity"] == pytest.approx(1.0)
    assert comparison["verdict"] == "alta"

    merged = database.merge_voice_profiles(source["id"], target["id"])

    assert merged["sourceName"] == "Hablante 1"
    assert merged["targetName"] == "Noel"
    assert merged["movedSamples"] == 1
    assert merged["retainedSamples"] == 2
    assert merged["updatedSegments"] == 1
    assert merged["affectedProjectIds"] == ["conversation-one"]
    assert [profile["name"] for profile in merged["catalog"]["profiles"]] == ["Noel"]
    project = database.load_project("conversation-one")
    assert project["segments"][0]["speaker"] == "Noel"
    assert project["segments"][0]["speakerProfileId"] == target["id"]
    matcher = database.load_voice_matcher_profiles()[0]
    assert matcher["id"] == target["id"]
    assert float(np.dot(voice, np.asarray(matcher["centroid"]))) > 0.999

    with pytest.raises(ValueError, match="diferentes"):
        database.merge_voice_profiles(target["id"], target["id"])
