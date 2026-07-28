from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor

import numpy as np
import pytest

from transcriptor_engine.database import ProjectDatabase
from transcriptor_engine.voice_crypto import protect_embedding, unprotect_embedding


def _voice(seed: int) -> np.ndarray:
    generator = np.random.default_rng(seed)
    vector = generator.normal(size=192).astype(np.float32)
    return vector / np.linalg.norm(vector)


def _voice_samples(
    voice: np.ndarray,
    count: int,
    *,
    prefix: str,
    confidence: float = 0.91,
) -> list[dict]:
    return [
        {
            "embedding": voice.tolist(),
            "segmentId": f"{prefix}-{index:03d}",
            "startMs": index * 1_500,
            "endMs": index * 1_500 + 1_000,
            "durationMs": 1_000,
            "confidence": confidence,
        }
        for index in range(count)
    ]


def _save_project(
    database: ProjectDatabase,
    project_id: str,
    profile_id: str,
    segments: list[tuple[int, int, float, str | None]],
) -> None:
    database.save_project(
        {
            "id": project_id,
            "name": project_id,
            "mediaPath": f"C:/audio/{project_id}.wav",
            "mediaType": "audio",
            "durationMs": max((end for _, end, _, _ in segments), default=0),
            "model": "turbo",
            "createdAt": "2026-07-28T00:00:00Z",
            "updatedAt": "2026-07-28T00:00:00Z",
            "transcriptionStatus": "completed",
            "lastPlaybackPositionMs": 0,
            "settings": {"language": "es", "model": "turbo"},
            "segments": [
                {
                    "id": f"{project_id}-segment-{index}",
                    "startMs": start,
                    "endMs": end,
                    "text": f"Fragmento {index}",
                    "speaker": "Noel",
                    "speakerProfileId": profile_id,
                    "speakerMatchConfidence": match_confidence,
                    "speakerConfidence": 0.9,
                    "confidence": 0.95,
                    "reviewState": review_state,
                    "order": index,
                    "words": [],
                }
                for index, (start, end, match_confidence, review_state) in enumerate(segments)
            ],
        }
    )


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
        [
            {
                "cluster": 1,
                "suggestedName": "Hablante 1",
                "samples": [
                    {
                        "embedding": voice.tolist(),
                        "segmentId": "segment-source",
                        "durationMs": 2_400,
                        "confidence": 0.93,
                    }
                ],
            }
        ],
    )
    source = first["profiles"][0]
    target_id = "legacy-duplicate-noel"
    with database.connect() as connection:
        connection.execute(
            """INSERT INTO voice_profiles
            (id, name, color, centroid_blob, sample_count, total_duration_ms,
             match_threshold, enabled, created_at, updated_at, last_matched_at)
            VALUES (?, 'Noel', '#7dd3fc', ?, 1, 2000, 0.64, 1, ?, ?, ?)""",
            (
                target_id,
                protect_embedding(voice),
                "2026-07-28T00:00:00Z",
                "2026-07-28T00:00:00Z",
                "2026-07-28T00:00:00Z",
            ),
        )
        connection.execute(
            """INSERT INTO voice_profile_samples
            (id, profile_id, source_project_id, source_segment_id, embedding_blob,
             duration_ms, confidence, created_at)
            VALUES ('legacy-target-sample', ?, 'conversation-two', 'segment-target',
                    ?, 2000, 0.9, '2026-07-28T00:00:00Z')""",
            (target_id, protect_embedding(voice)),
        )
    target = next(
        profile
        for profile in database.list_voice_profiles()["profiles"]
        if profile["id"] == target_id
    )
    database.save_project(
        {
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
            "segments": [
                {
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
                }
            ],
        }
    )

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


def test_profile_catalog_separates_acoustic_memory_from_recognized_coverage(tmp_path) -> None:
    database = ProjectDatabase(tmp_path / "voice-metrics.sqlite3")
    voice = _voice(70)
    learned = database.learn_voice_observations(
        "memory-source",
        [
            {
                "cluster": 1,
                "suggestedName": "Noel",
                "samples": _voice_samples(voice, 8, prefix="memory"),
            }
        ],
    )
    profile_id = learned["profiles"][0]["id"]
    _save_project(
        database,
        "recognized-one",
        profile_id,
        [(0, 1_000, 0.55, "corrected"), (1_000, 3_000, 0.85, None)],
    )
    _save_project(
        database,
        "recognized-two",
        profile_id,
        [(0, 3_000, 0.95, "accepted")],
    )

    profile = database.list_voice_profiles()["profiles"][0]

    assert profile["totalDurationMs"] == 8_000
    assert profile["sourceProjectCount"] == 1
    assert profile["recognizedDurationMs"] == 6_000
    assert profile["recognizedSegmentCount"] == 3
    assert profile["recognizedProjectCount"] == 2
    # Coverage remains honest (including a manual attribution), while the
    # similarity statistic only averages matches that passed this profile's
    # configured identity threshold.
    assert profile["averageMatchConfidence"] == pytest.approx(0.90)
    assert profile["averageProfileSimilarity"] == pytest.approx(0.90)
    assert profile["averageSampleConfidence"] == pytest.approx(0.91)
    assert 0 <= profile["reliabilityScore"] <= 100

    draft = database.load_project("recognized-one")
    draft["segments"][0]["speakerReviewState"] = "accepted"
    draft["updatedAt"] = "2026-07-28T00:01:00Z"
    database.save_project(draft)
    reopened = ProjectDatabase(database.path).load_project("recognized-one")
    assert reopened["segments"][0]["reviewState"] == "corrected"
    assert reopened["segments"][0]["speakerReviewState"] == "accepted"
    assert reopened["segments"][1]["reviewState"] is None


def test_learning_keeps_up_to_24_samples_spread_across_the_conversation(tmp_path) -> None:
    database = ProjectDatabase(tmp_path / "voice-diversity.sqlite3")
    voice = _voice(71)

    result = database.learn_voice_observations(
        "long-conversation",
        [
            {
                "cluster": 1,
                "samples": _voice_samples(voice, 48, prefix="long"),
            }
        ],
    )

    profile = result["profiles"][0]
    assert result["receivedSamples"] == 48
    assert result["eligibleSamples"] == 48
    assert result["selectedSamples"] == 24
    assert result["notSelectedSamples"] == 24
    assert result["maximumSamplesPerObservation"] == 24
    assert profile["sampleCount"] == 24
    assert profile["totalDurationMs"] == 24_000
    with database.connect() as connection:
        retained = connection.execute(
            """SELECT source_segment_id FROM voice_profile_samples
            WHERE profile_id = ? ORDER BY source_segment_id""",
            (profile["id"],),
        ).fetchall()
    retained_indices = [int(str(row["source_segment_id"]).rsplit("-", 1)[1]) for row in retained]
    assert min(retained_indices) <= 1
    assert max(retained_indices) >= 46


def test_profile_memory_is_capped_at_160_and_preserves_project_diversity(tmp_path) -> None:
    database = ProjectDatabase(tmp_path / "voice-cap.sqlite3")
    voice = _voice(72)
    first = database.learn_voice_observations(
        "conversation-0",
        [
            {
                "cluster": 1,
                "suggestedName": "Isabel",
                "samples": _voice_samples(voice, 24, prefix="p0"),
            }
        ],
    )
    profile_id = first["profiles"][0]["id"]
    for project_index in range(1, 7):
        database.learn_voice_observations(
            f"conversation-{project_index}",
            [
                {
                    "cluster": 1,
                    "matchedProfileId": profile_id,
                    "matchConfidence": 0.99,
                    "samples": _voice_samples(
                        voice,
                        24,
                        prefix=f"p{project_index}",
                    ),
                }
            ],
        )

    profile = database.list_voice_profiles()["profiles"][0]
    assert profile["sampleCount"] == 160
    assert profile["sourceProjectCount"] == 7
    assert profile["totalDurationMs"] == 160_000


def test_matched_profile_requires_real_similarity_and_never_creates_from_unknown_id(
    tmp_path,
) -> None:
    database = ProjectDatabase(tmp_path / "voice-safety.sqlite3")
    known_voice = _voice(73)
    other_voice = _voice(74)
    first = database.learn_voice_observations(
        "known",
        [
            {
                "cluster": 1,
                "suggestedName": "Noel",
                "samples": _voice_samples(known_voice, 2, prefix="known"),
            }
        ],
    )
    profile_id = first["profiles"][0]["id"]

    weak = database.learn_voice_observations(
        "other",
        [
            {
                "cluster": 1,
                "matchedProfileId": profile_id,
                "matchConfidence": 0.99,
                "samples": _voice_samples(other_voice, 2, prefix="other"),
            }
        ],
    )
    missing = database.learn_voice_observations(
        "missing",
        [
            {
                "cluster": 1,
                "matchedProfileId": "does-not-exist",
                "matchConfidence": 0.99,
                "samples": _voice_samples(known_voice, 2, prefix="missing"),
            }
        ],
    )

    assert weak["learnedSamples"] == 0
    assert weak["rejectedObservations"] == 1
    assert weak["rejectionReasons"]["weakProfileSample"] == 2
    assert missing["learnedSamples"] == 0
    assert missing["rejectionReasons"]["profileNotFound"] == 2
    profiles = database.list_voice_profiles()["profiles"]
    assert len(profiles) == 1
    assert profiles[0]["sampleCount"] == 2


def test_reliability_score_uses_memory_diversity_and_recognition_similarity(tmp_path) -> None:
    database = ProjectDatabase(tmp_path / "voice-reliability.sqlite3")
    voice = _voice(75)
    first = database.learn_voice_observations(
        "source-0",
        [
            {
                "cluster": 1,
                "suggestedName": "Isabel",
                "samples": _voice_samples(voice, 2, prefix="source0"),
            }
        ],
    )
    profile_id = first["profiles"][0]["id"]
    initial_score = first["profiles"][0]["reliabilityScore"]

    for project_index in range(1, 4):
        database.learn_voice_observations(
            f"source-{project_index}",
            [
                {
                    "cluster": 1,
                    "matchedProfileId": profile_id,
                    "matchConfidence": 0.96,
                    "samples": _voice_samples(
                        voice,
                        10,
                        prefix=f"source{project_index}",
                    ),
                }
            ],
        )
        _save_project(
            database,
            f"coverage-{project_index}",
            profile_id,
            [(0, 20_000, 0.94, "accepted")],
        )

    mature = database.list_voice_profiles()["profiles"][0]
    assert mature["reliabilityScore"] > initial_score
    assert mature["reliabilityScore"] >= 78
    assert mature["reliability"] == "alta"


def test_known_profile_filters_each_sample_before_updating_memory(tmp_path) -> None:
    database = ProjectDatabase(tmp_path / "voice-sample-filter.sqlite3")
    voice = _voice(80)
    orthogonal = _voice(81)
    orthogonal -= float(np.dot(orthogonal, voice)) * voice
    orthogonal /= np.linalg.norm(orthogonal)
    contaminant = 0.50 * voice + np.sqrt(1 - 0.50**2) * orthogonal
    first = database.learn_voice_observations(
        "known-source",
        [{"cluster": 1, "samples": _voice_samples(voice, 2, prefix="known")}],
    )
    profile_id = first["profiles"][0]["id"]

    correct_sample = _voice_samples(voice, 1, prefix="correct")[0]
    correct_sample.update({"endMs": 2_000, "durationMs": 2_000})
    result = database.learn_voice_observations(
        "mixed-source",
        [
            {
                "cluster": 1,
                "matchedProfileId": profile_id,
                "matchConfidence": 0.92,
                "samples": [
                    correct_sample,
                    *_voice_samples(contaminant, 1, prefix="other"),
                ],
            }
        ],
    )

    assert result["learnedSamples"] == 1
    assert result["rejectionReasons"]["weakProfileSample"] == 1
    assert result["profiles"][0]["sampleCount"] == 3


def test_reanalysis_replaces_evidence_from_the_same_project(tmp_path) -> None:
    database = ProjectDatabase(tmp_path / "voice-project-refresh.sqlite3")
    voice = _voice(82)
    first = database.learn_voice_observations(
        "live-session",
        [{"cluster": 1, "samples": _voice_samples(voice, 2, prefix="live")}],
    )
    profile_id = first["profiles"][0]["id"]

    refined = database.learn_voice_observations(
        "live-session",
        [
            {
                "cluster": 1,
                "matchedProfileId": profile_id,
                "matchConfidence": 0.98,
                "samples": _voice_samples(voice, 3, prefix="refined"),
            }
        ],
    )

    assert refined["replacedSamples"] == 2
    assert refined["profiles"][0]["sampleCount"] == 3
    assert refined["profiles"][0]["sourceProjectCount"] == 1


def test_reanalysis_moves_project_evidence_and_rebuilds_both_profiles(tmp_path) -> None:
    database = ProjectDatabase(tmp_path / "voice-project-reassignment.sqlite3")
    voice_a = _voice(820)
    voice_b = _voice(821)
    first = database.learn_voice_observations(
        "shared-project",
        [
            {
                "cluster": 1,
                "suggestedName": "Noel",
                "samples": _voice_samples(voice_a, 2, prefix="shared-a"),
            }
        ],
    )
    profile_a = first["profiles"][0]["id"]
    database.learn_voice_observations(
        "reference-a",
        [
            {
                "cluster": 1,
                "matchedProfileId": profile_a,
                "matchConfidence": 0.98,
                "samples": _voice_samples(voice_a, 2, prefix="reference-a"),
            }
        ],
    )
    second = database.learn_voice_observations(
        "reference-b",
        [
            {
                "cluster": 1,
                "suggestedName": "Isabel",
                "samples": _voice_samples(voice_b, 2, prefix="reference-b"),
            }
        ],
    )
    profile_b = next(profile["id"] for profile in second["profiles"] if profile["id"] != profile_a)

    reassigned = database.learn_voice_observations(
        "shared-project",
        [
            {
                "cluster": 1,
                "matchedProfileId": profile_b,
                "matchConfidence": 0.98,
                "samples": _voice_samples(voice_b, 2, prefix="shared-b"),
            }
        ],
        replace_project_evidence=True,
    )

    profiles = {profile["id"]: profile for profile in reassigned["profiles"]}
    assert reassigned["replacedSamples"] == 2
    assert profiles[profile_a]["sampleCount"] == 2
    assert profiles[profile_a]["sourceProjectCount"] == 1
    assert profiles[profile_b]["sampleCount"] == 4
    assert profiles[profile_b]["sourceProjectCount"] == 2
    with database.connect() as connection:
        stale_count = int(
            connection.execute(
                """SELECT COUNT(*) FROM voice_profile_samples
                WHERE profile_id = ? AND source_project_id = ?""",
                (profile_a, "shared-project"),
            ).fetchone()[0]
        )
    assert stale_count == 0
    matchers = {profile["id"]: profile for profile in database.load_voice_matcher_profiles()}
    assert float(np.dot(voice_a, np.asarray(matchers[profile_a]["centroid"]))) > 0.99
    assert float(np.dot(voice_b, np.asarray(matchers[profile_b]["centroid"]))) > 0.99


def test_authoritative_empty_reanalysis_removes_old_project_evidence(tmp_path) -> None:
    database = ProjectDatabase(tmp_path / "voice-empty-reanalysis.sqlite3")
    voice = _voice(822)
    learned = database.learn_voice_observations(
        "silent-after-reanalysis",
        [{"cluster": 1, "samples": _voice_samples(voice, 2, prefix="old-voice")}],
    )
    profile_id = learned["profiles"][0]["id"]

    result = database.learn_voice_observations(
        "silent-after-reanalysis",
        [],
        replace_project_evidence=True,
    )

    profile = next(item for item in result["profiles"] if item["id"] == profile_id)
    assert result["replacedSamples"] == 2
    assert profile["sampleCount"] == 0
    assert profile["totalDurationMs"] == 0
    assert profile["sourceProjectCount"] == 0
    assert profile["ready"] is False


def test_two_incoherent_samples_do_not_create_a_voice_profile(tmp_path) -> None:
    database = ProjectDatabase(tmp_path / "voice-incoherent-pair.sqlite3")
    voice_a = np.zeros(192, dtype=np.float32)
    voice_a[0] = 1.0
    voice_b = np.zeros(192, dtype=np.float32)
    voice_b[0] = 0.50
    voice_b[1] = np.sqrt(1 - 0.50**2)

    result = database.learn_voice_observations(
        "ambiguous-project",
        [
            {
                "cluster": 1,
                "samples": [
                    _voice_samples(voice_a, 1, prefix="ambiguous-a")[0],
                    _voice_samples(voice_b, 1, prefix="ambiguous-b")[0],
                ],
            }
        ],
    )

    assert result["profiles"] == []
    assert result["assignments"] == []
    assert result["createdProfiles"] == []
    assert result["rejectedObservations"] == 1
    assert result["rejectionReasons"]["incoherentVoice"] == 2


def test_parallel_discovery_reuses_the_profile_created_by_the_first_job(tmp_path) -> None:
    database_path = tmp_path / "voice-parallel.sqlite3"
    databases = (ProjectDatabase(database_path), ProjectDatabase(database_path))
    voice = _voice(83)

    def learn(job: tuple[ProjectDatabase, str]):
        database, project_id = job
        return database.learn_voice_observations(
            project_id,
            [
                {
                    "cluster": 1,
                    "samples": _voice_samples(
                        voice,
                        2,
                        prefix=project_id,
                    ),
                }
            ],
        )

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(
            pool.map(
                learn,
                (
                    (databases[0], "parallel-a"),
                    (databases[1], "parallel-b"),
                ),
            )
        )

    profiles = databases[0].list_voice_profiles()["profiles"]
    assert len(profiles) == 1
    assert profiles[0]["sampleCount"] == 4
    assert profiles[0]["sourceProjectCount"] == 2
    assert sum(len(result["createdProfiles"]) for result in results) == 1


def test_database_open_set_floor_does_not_contaminate_a_known_profile(tmp_path) -> None:
    database = ProjectDatabase(tmp_path / "voice-open-set.sqlite3")
    noel = np.zeros(192, dtype=np.float32)
    noel[0] = 1.0
    isabel = -noel
    unknown = np.zeros(192, dtype=np.float32)
    unknown[0] = 0.68
    unknown[1] = np.sqrt(1 - 0.68**2)
    first = database.learn_voice_observations(
        "noel-source",
        [{"cluster": 1, "suggestedName": "Noel", "samples": _voice_samples(noel, 2, prefix="noel")}],
    )
    noel_id = first["profiles"][0]["id"]
    database.learn_voice_observations(
        "isabel-source",
        [{"cluster": 1, "suggestedName": "Isabel", "samples": _voice_samples(isabel, 2, prefix="isabel")}],
    )

    result = database.learn_voice_observations(
        "unknown-source",
        [{"cluster": 1, "samples": _voice_samples(unknown, 2, prefix="unknown")}],
    )

    profiles = {profile["id"]: profile for profile in result["profiles"]}
    assert len(profiles) == 3
    assert profiles[noel_id]["sampleCount"] == 2
    assert len(result["createdProfiles"]) == 1
