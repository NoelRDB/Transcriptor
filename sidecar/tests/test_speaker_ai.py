from __future__ import annotations

import numpy as np
import pytest

import transcriptor_engine.speaker_ai as speaker_ai
from transcriptor_engine.speaker_ai import (
    OnlineSpeakerIdentifier,
    _cluster_embeddings,
    _estimate_speaker_count,
    _exceptional_profile_match,
    _fill_and_smooth_labels,
    _known_profile_anchor_count,
    _match_clusters_to_profiles,
    _resolve_speaker_target,
    _speaker_units,
    neural_assign_speakers,
)


class _SequenceEmbedder:
    def __init__(self, vectors: list[np.ndarray]) -> None:
        self.vectors = iter(vectors)

    def embedding(self, _audio: np.ndarray) -> np.ndarray:
        vector = np.asarray(next(self.vectors), dtype=np.float32)
        return vector / np.linalg.norm(vector)


def test_neural_embeddings_form_two_stable_voice_clusters() -> None:
    matrix = np.asarray(
        [
            [1.0, 0.02, 0.0],
            [0.99, 0.05, 0.0],
            [0.01, 1.0, 0.02],
            [0.03, 0.99, 0.01],
        ],
        dtype=np.float32,
    )
    matrix /= np.linalg.norm(matrix, axis=1, keepdims=True)

    labels, confidences = _cluster_embeddings(matrix, 2)

    assert labels[0] == labels[1]
    assert labels[2] == labels[3]
    assert labels[0] != labels[2]
    assert np.all(confidences >= 0.72)


def test_automatic_voice_count_finds_three_supported_clusters() -> None:
    matrix = np.asarray(
        [
            [1.0, 0.02, 0.0, 0.0],
            [0.99, 0.04, 0.01, 0.0],
            [0.98, 0.01, 0.03, 0.0],
            [0.99, 0.03, 0.02, 0.0],
            [0.01, 1.0, 0.02, 0.0],
            [0.03, 0.99, 0.01, 0.0],
            [0.02, 0.98, 0.04, 0.0],
            [0.04, 0.99, 0.02, 0.0],
            [0.01, 0.02, 1.0, 0.0],
            [0.03, 0.01, 0.99, 0.0],
            [0.02, 0.04, 0.98, 0.0],
            [0.01, 0.03, 0.99, 0.0],
        ],
        dtype=np.float32,
    )
    matrix /= np.linalg.norm(matrix, axis=1, keepdims=True)

    assert _estimate_speaker_count(matrix, 55) == 3
    assert _resolve_speaker_target(matrix, 2, False, 55) == 2
    assert _resolve_speaker_target(matrix, 8, False, 55) == 3
    assert _resolve_speaker_target(matrix, 2, True, 55) == 2


def test_automatic_voice_count_does_not_split_one_consistent_voice() -> None:
    matrix = np.asarray(
        [[1.0, offset, 0.01, 0.0] for offset in (0.01, 0.02, 0.0, 0.03, 0.015, 0.025)],
        dtype=np.float32,
    )
    matrix /= np.linalg.norm(matrix, axis=1, keepdims=True)

    assert _estimate_speaker_count(matrix, 55) == 1


def test_known_profiles_anchor_a_minority_voice_with_clear_support() -> None:
    majority = np.asarray([[1.0, 0.02, 0.0]] * 18, dtype=np.float32)
    minority = np.asarray([[0.02, 1.0, 0.0]] * 2, dtype=np.float32)
    matrix = np.concatenate((majority, minority))
    matrix /= np.linalg.norm(matrix, axis=1, keepdims=True)

    anchors = _known_profile_anchor_count(
        matrix,
        [
            {"id": "noel", "centroid": [1.0, 0.0, 0.0], "matchThreshold": 0.64},
            {"id": "isabel", "centroid": [0.0, 1.0, 0.0], "matchThreshold": 0.64},
        ],
    )

    assert anchors == 2


def test_one_exceptionally_clear_known_voice_can_be_recognized_as_a_cameo() -> None:
    isabel = np.asarray([0.0, 1.0, 0.0], dtype=np.float32)

    match = _exceptional_profile_match(
        isabel,
        [
            {
                "id": "noel",
                "name": "Noel",
                "centroid": [1.0, 0.0, 0.0],
                "matchThreshold": 0.64,
            },
            {
                "id": "isabel",
                "name": "Isabel",
                "centroid": [0.0, 1.0, 0.0],
                "matchThreshold": 0.64,
            },
        ],
    )

    assert match is not None
    assert match["id"] == "isabel"
    assert match["score"] == pytest.approx(1.0)


def test_one_clear_known_cameo_survives_a_dominant_offline_voice(monkeypatch) -> None:
    noel = np.asarray([1.0, 0.0, 0.0], dtype=np.float32)
    isabel = np.asarray([0.0, 1.0, 0.0], dtype=np.float32)
    embedder = _SequenceEmbedder([noel] * 119 + [isabel])
    monkeypatch.setattr(speaker_ai, "get_neural_embedder", lambda: embedder)
    segments = [
        {
            "id": f"segment-{index}",
            "startMs": index * 1_000,
            "endMs": index * 1_000 + 900,
            "text": f"IntervenciÃ³n {index}",
            "order": index,
            "words": [],
        }
        for index in range(120)
    ]

    assigned, speaker_count = neural_assign_speakers(
        segments,
        np.zeros(120 * speaker_ai.SAMPLE_RATE, dtype=np.float32),
        speaker_count=8,
        exact_speaker_count=False,
        voice_profiles=[
            {
                "id": "noel",
                "name": "Noel",
                "centroid": noel.tolist(),
                "matchThreshold": 0.64,
            },
            {
                "id": "isabel",
                "name": "Isabel",
                "centroid": isabel.tolist(),
                "matchThreshold": 0.64,
            },
        ],
    )

    assert {segment["speaker"] for segment in assigned[:119]} == {"Noel"}
    assert assigned[-1]["speaker"] == "Isabel"
    assert assigned[-1]["speakerProfileId"] == "isabel"
    assert assigned[-1]["speakerMatchConfidence"] == pytest.approx(1.0)
    assert speaker_count == 2


def test_short_uncertain_speaker_flip_is_smoothed() -> None:
    labels: list[int | None] = [0, 1, 0, None, 1]
    confidences: list[float | None] = [0.9, 0.58, 0.88, None, 0.82]

    _fill_and_smooth_labels(labels, confidences)

    assert labels == [0, 0, 0, 0, 1]
    assert confidences[1] == 0.58
    assert confidences[3] == 0.5


def test_long_whisper_segment_is_split_into_voice_sized_units() -> None:
    words = [
        {
            "id": f"word-{index}",
            "startMs": index * 500,
            "endMs": index * 500 + 420,
            "text": f" palabra{index}",
        }
        for index in range(10)
    ]
    segment = {
        "id": "segment-1",
        "startMs": 0,
        "endMs": 5_000,
        "text": "Texto largo",
        "words": words,
        "order": 0,
    }

    units = _speaker_units([segment])

    assert len(units) >= 2
    assert all(unit["words"] for unit in units)
    assert units[0]["startMs"] == 0
    assert units[-1]["endMs"] == words[-1]["endMs"]


def test_saved_voice_profiles_are_matched_with_a_safe_margin() -> None:
    noel = np.asarray([1.0, 0.0, 0.0], dtype=np.float32)
    pareja = np.asarray([0.0, 1.0, 0.0], dtype=np.float32)
    clusters = {
        0: np.asarray([0.98, 0.08, 0.0], dtype=np.float32),
        1: np.asarray([0.04, 0.99, 0.0], dtype=np.float32),
    }
    clusters = {key: value / np.linalg.norm(value) for key, value in clusters.items()}

    matches = _match_clusters_to_profiles(
        clusters,
        [
            {"id": "noel", "name": "Noel", "centroid": noel.tolist(), "matchThreshold": 0.64},
            {"id": "pareja", "name": "Mi pareja", "centroid": pareja.tolist(), "matchThreshold": 0.64},
        ],
    )

    assert matches[0]["name"] == "Noel"
    assert matches[1]["name"] == "Mi pareja"
    assert matches[0]["id"] != matches[1]["id"]


def test_online_unknown_cluster_can_match_a_known_profile_later(monkeypatch) -> None:
    unknown = np.asarray([0.0, 1.0, 0.0], dtype=np.float32)
    noel = np.asarray([1.0, 0.04, 0.0], dtype=np.float32)
    embedder = _SequenceEmbedder([unknown, noel, noel, noel, noel, noel])
    monkeypatch.setattr(speaker_ai, "get_neural_embedder", lambda: embedder)
    identifier = OnlineSpeakerIdentifier(
        max_speakers=1,
        voice_profiles=[
            {
                "id": "noel",
                "name": "Noel",
                "centroid": [1.0, 0.0, 0.0],
                "matchThreshold": 0.76,
            }
        ],
    )
    audio = np.ones(speaker_ai.SAMPLE_RATE, dtype=np.float32)

    first_name, _ = identifier.assign(audio)
    assert first_name == "Hablante 1"
    assert identifier.last_profile_id is None

    identity_changes = []
    names = []
    for _ in range(5):
        name, _ = identifier.assign(audio)
        names.append(name)
        identity_changes.append(identifier.last_identity_changed)

    assert names[-1] == "Noel"
    assert any(identity_changes)
    assert identifier.last_cluster_index == 0
    assert identifier.last_profile_id == "noel"
    assert identifier.last_profile_name == "Noel"
    assert identifier.last_profile_confidence is not None
    assert identifier.last_profile_confidence > 0.98


def test_online_ambiguous_unknown_voice_is_not_forced_to_a_profile(monkeypatch) -> None:
    ambiguous = np.asarray([1.0, 1.0, 0.0], dtype=np.float32)
    embedder = _SequenceEmbedder([ambiguous] * 6)
    monkeypatch.setattr(speaker_ai, "get_neural_embedder", lambda: embedder)
    identifier = OnlineSpeakerIdentifier(
        max_speakers=1,
        voice_profiles=[
            {
                "id": "first",
                "name": "Primera",
                "centroid": [1.0, 0.0, 0.0],
                "matchThreshold": 0.64,
            },
            {
                "id": "second",
                "name": "Segunda",
                "centroid": [0.0, 1.0, 0.0],
                "matchThreshold": 0.64,
            },
        ],
    )
    audio = np.ones(speaker_ai.SAMPLE_RATE, dtype=np.float32)

    for _ in range(6):
        name, _ = identifier.assign(audio)

    assert name == "Hablante 1"
    assert identifier.last_profile_id is None
    assert identifier.last_profile_name is None
    assert identifier.last_profile_confidence is None


def test_large_margin_below_open_set_floor_stays_unknown(monkeypatch) -> None:
    unknown = np.asarray([0.68, np.sqrt(1 - 0.68**2), 0.0], dtype=np.float32)
    embedder = _SequenceEmbedder([unknown] * 6)
    monkeypatch.setattr(speaker_ai, "get_neural_embedder", lambda: embedder)
    profiles = [
        {
            "id": "noel",
            "name": "Noel",
            "centroid": [1.0, 0.0, 0.0],
            "matchThreshold": 0.64,
        },
        {
            "id": "isabel",
            "name": "Isabel",
            "centroid": [-1.0, 0.0, 0.0],
            "matchThreshold": 0.64,
        },
    ]
    identifier = OnlineSpeakerIdentifier(max_speakers=1, voice_profiles=profiles)
    audio = np.ones(speaker_ai.SAMPLE_RATE, dtype=np.float32)

    names = [identifier.assign(audio)[0] for _ in range(6)]

    assert set(names) == {"Hablante 1"}
    assert identifier.last_profile_id is None
    assert _match_clusters_to_profiles({0: unknown}, profiles) == {}


@pytest.mark.parametrize("similarity", [0.66, 0.70])
def test_single_profile_needs_an_absolute_similarity_floor_online(
    monkeypatch,
    similarity: float,
) -> None:
    unknown = np.asarray(
        [similarity, np.sqrt(1 - similarity**2), 0.0],
        dtype=np.float32,
    )
    embedder = _SequenceEmbedder([unknown] * 8)
    monkeypatch.setattr(speaker_ai, "get_neural_embedder", lambda: embedder)
    identifier = OnlineSpeakerIdentifier(
        max_speakers=1,
        voice_profiles=[
            {
                "id": "noel",
                "name": "Noel",
                "centroid": [1.0, 0.0, 0.0],
                "matchThreshold": 0.64,
            }
        ],
    )
    audio = np.ones(speaker_ai.SAMPLE_RATE, dtype=np.float32)

    names = [identifier.assign(audio)[0] for _ in range(8)]

    assert set(names) == {"Hablante 1"}
    assert identifier.last_profile_id is None


@pytest.mark.parametrize("similarity", [0.66, 0.70])
def test_single_profile_needs_an_absolute_similarity_floor_offline(
    similarity: float,
) -> None:
    unknown = np.asarray(
        [similarity, np.sqrt(1 - similarity**2), 0.0],
        dtype=np.float32,
    )

    matches = _match_clusters_to_profiles(
        {0: unknown},
        [
            {
                "id": "noel",
                "name": "Noel",
                "centroid": [1.0, 0.0, 0.0],
                "matchThreshold": 0.64,
            }
        ],
    )

    assert matches == {}


def test_two_oversplit_clusters_can_converge_to_the_same_known_person() -> None:
    clusters = {
        0: np.asarray([0.998, 0.055, 0.0], dtype=np.float32),
        1: np.asarray([0.994, -0.06, 0.0], dtype=np.float32),
    }
    matches = _match_clusters_to_profiles(
        clusters,
        [
            {
                "id": "isabel",
                "name": "Isabel",
                "centroid": [1.0, 0.0, 0.0],
                "matchThreshold": 0.64,
            },
            {
                "id": "other",
                "name": "Otra voz",
                "centroid": [0.0, 1.0, 0.0],
                "matchThreshold": 0.64,
            },
        ],
    )

    assert matches[0]["id"] == "isabel"
    assert matches[1]["id"] == "isabel"
    assert matches[0]["score"] > 0.99
    assert matches[1]["score"] > 0.99


def test_moderately_oversplit_clusters_can_share_one_strong_profile() -> None:
    angle = np.deg2rad(22.5)
    clusters = {
        0: np.asarray([np.cos(angle), np.sin(angle), 0.0], dtype=np.float32),
        1: np.asarray([np.cos(angle), -np.sin(angle), 0.0], dtype=np.float32),
    }

    matches = _match_clusters_to_profiles(
        clusters,
        [
            {
                "id": "noel",
                "name": "Noel",
                "centroid": [1.0, 0.0, 0.0],
                "matchThreshold": 0.64,
            },
            {
                "id": "other",
                "name": "Otra voz",
                "centroid": [0.0, 0.0, 1.0],
                "matchThreshold": 0.64,
            },
        ],
    )

    assert matches[0]["id"] == "noel"
    assert matches[1]["id"] == "noel"
    assert float(np.dot(clusters[0], clusters[1])) == pytest.approx(
        np.sqrt(0.5),
        abs=1e-5,
    )


def test_similar_known_voices_route_to_separate_live_clusters(monkeypatch) -> None:
    noel = np.asarray([1.0, 0.0, 0.0], dtype=np.float32)
    isabel = np.asarray([0.75, np.sqrt(1 - 0.75**2), 0.0], dtype=np.float32)
    sequence = [noel] * 3 + [isabel] * 5 + [noel] * 5
    embedder = _SequenceEmbedder(sequence)
    monkeypatch.setattr(speaker_ai, "get_neural_embedder", lambda: embedder)
    identifier = OnlineSpeakerIdentifier(
        max_speakers=2,
        voice_profiles=[
            {
                "id": "noel",
                "name": "Noel",
                "centroid": noel.tolist(),
                "matchThreshold": 0.64,
            },
            {
                "id": "isabel",
                "name": "Isabel",
                "centroid": isabel.tolist(),
                "matchThreshold": 0.64,
            },
        ],
    )
    audio = np.ones(speaker_ai.SAMPLE_RATE, dtype=np.float32)

    assignments = []
    for _ in sequence:
        name, _confidence = identifier.assign(audio)
        assignments.append(
            (name, identifier.last_cluster_index, identifier.last_profile_id)
        )

    assert {cluster for _name, cluster, _profile in assignments[:3]} == {0}
    assert {cluster for _name, cluster, _profile in assignments[3:8]} == {1}
    assert {cluster for _name, cluster, _profile in assignments[8:]} == {0}
    assert assignments[2][2] == "noel"
    assert assignments[7][2] == "isabel"
    assert assignments[-1][2] == "noel"
