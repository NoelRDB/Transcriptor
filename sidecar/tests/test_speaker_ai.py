from __future__ import annotations

import numpy as np

from transcriptor_engine.speaker_ai import (
    _cluster_embeddings,
    _estimate_speaker_count,
    _fill_and_smooth_labels,
    _match_clusters_to_profiles,
    _resolve_speaker_target,
    _speaker_units,
)


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


def test_saved_voice_profiles_are_matched_one_to_one_with_a_safe_margin() -> None:
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
