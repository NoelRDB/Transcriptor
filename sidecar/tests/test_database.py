from __future__ import annotations

import pytest

from transcriptor_engine.database import ProjectDatabase


def project() -> dict:
    return {
        "id": "proyecto-ñ",
        "name": "Reunión",
        "mediaPath": "C:/Vídeos con espacios/reunión.mp4",
        "mediaType": "video",
        "durationMs": 2200,
        "model": "small",
        "createdAt": "2026-01-01T00:00:00Z",
        "updatedAt": "2026-01-01T00:00:00Z",
        "transcriptionStatus": "completed",
        "lastPlaybackPositionMs": 500,
        "settings": {"language": "es", "model": "small"},
        "segments": [
            {
                "id": "s1",
                "startMs": 0,
                "endMs": 2100,
                "text": "Hola mundo",
                "speaker": None,
                "confidence": 0.9,
                "order": 0,
                "words": [{"id": "w1", "startMs": 0, "endMs": 500, "text": "Hola", "probability": 0.98}],
            }
        ],
    }


def test_project_roundtrip_and_recent_list(tmp_path):
    database = ProjectDatabase(tmp_path / "datos.sqlite3")
    database.save_project(project())
    loaded = database.load_project("proyecto-ñ")
    assert loaded["name"] == "Reunión"
    assert loaded["segments"][0]["words"][0]["text"] == "Hola"
    assert database.list_projects()[0]["mediaPath"].endswith("reunión.mp4")


def test_saving_replaces_segments_atomically(tmp_path):
    database = ProjectDatabase(tmp_path / "datos.sqlite3")
    value = project()
    database.save_project(value)
    value["segments"] = []
    database.save_project(value)
    assert database.load_project(value["id"])["segments"] == []


def test_completed_project_can_be_recovered_by_media_path(tmp_path):
    database = ProjectDatabase(tmp_path / "datos.sqlite3")
    value = project()
    database.save_project(value)

    recovered = database.load_project_for_media(value["mediaPath"].swapcase())

    assert recovered is not None
    assert recovered["id"] == value["id"]
    assert recovered["segments"][0]["text"] == "Hola mundo"


def test_empty_unfinished_project_is_not_reused(tmp_path):
    database = ProjectDatabase(tmp_path / "datos.sqlite3")
    value = project()
    value["transcriptionStatus"] = "failed"
    value["segments"] = []
    database.save_project(value)

    assert database.load_project_for_media(value["mediaPath"]) is None


def test_delete_project_removes_app_data_but_preserves_source_media(tmp_path):
    database = ProjectDatabase(tmp_path / "datos.sqlite3")
    media = tmp_path / "conversación.wav"
    media.write_bytes(b"audio original")
    value = project()
    value["mediaPath"] = str(media)
    database.save_project(value)

    result = database.delete_project(value["id"])

    assert result["deleted"] is True
    assert result["mediaPreserved"] is True
    assert media.read_bytes() == b"audio original"
    assert database.list_projects() == []
    with pytest.raises(KeyError, match="eliminado"):
        database.load_project(value["id"])


def test_job_state_is_persisted(tmp_path):
    database = ProjectDatabase(tmp_path / "datos.sqlite3")
    database.save_project(project())
    database.update_job("proyecto-ñ", "transcribing", 1000, 2200)
    with database.connect() as connection:
        row = connection.execute(
            "SELECT state, processed_duration_ms FROM transcription_jobs WHERE project_id = ?",
            ("proyecto-ñ",),
        ).fetchone()
    assert dict(row) == {"state": "transcribing", "processed_duration_ms": 1000}


def test_status_update_preserves_existing_transcript(tmp_path):
    database = ProjectDatabase(tmp_path / "datos.sqlite3")
    value = project()
    database.save_project(value)

    database.update_project_status(value["id"], "failed", "2026-01-02T00:00:00Z")

    loaded = database.load_project(value["id"])
    assert loaded["transcriptionStatus"] == "failed"
    assert loaded["segments"][0]["text"] == "Hola mundo"


def test_saving_sanitizes_invalid_unicode_without_losing_the_project(tmp_path):
    database = ProjectDatabase(tmp_path / "datos.sqlite3")
    value = project()
    value["name"] = "Reunión \udc81"
    value["segments"][0]["text"] = "Hola \udc81 mundo"
    value["segments"][0]["words"][0]["text"] = "Hola \ud800"

    database.save_project(value)
    loaded = database.load_project(value["id"])

    assert loaded["name"] == "Reunión �"
    assert loaded["segments"][0]["text"] == "Hola � mundo"
    assert loaded["segments"][0]["words"][0]["text"] == "Hola �"


def test_legacy_mojibake_is_repaired_on_load_and_save(tmp_path):
    database = ProjectDatabase(tmp_path / "datos.sqlite3")
    value = project()
    value["segments"][0]["text"] = "Â¿QuÃ© tal estÃ¡s?"
    database.save_project(value)

    loaded = database.load_project(value["id"])

    assert loaded["segments"][0]["text"] == "¿Qué tal estás?"


def test_irrecoverable_legacy_africa_sequence_is_repaired(tmp_path):
    database = ProjectDatabase(tmp_path / "datos.sqlite3")
    value = project()
    value["segments"][0]["text"] = "El continente es Ã�frica"
    database.save_project(value)

    assert database.load_project(value["id"])["segments"][0]["text"] == "El continente es África"


def test_transcript_version_keeps_previous_segments(tmp_path):
    database = ProjectDatabase(tmp_path / "datos.sqlite3")
    value = project()
    database.save_project(value)

    assert database.create_transcript_version(value["id"])
    with database.connect() as connection:
        version = connection.execute(
            "SELECT segment_count, segments_json FROM transcript_versions WHERE project_id = ?",
            (value["id"],),
        ).fetchone()

    assert version["segment_count"] == 1
    assert "Hola mundo" in version["segments_json"]


def test_insights_are_only_loaded_for_the_exact_transcript_version(tmp_path):
    database = ProjectDatabase(tmp_path / "datos.sqlite3")
    value = project()
    database.save_project(value)
    insights = {"generatedAt": "2026-01-01T00:00:01Z", "method": "test", "summary": "Resumen"}
    database.save_insights(value["id"], value["updatedAt"], insights)
    assert database.load_project(value["id"])["insights"]["summary"] == "Resumen"

    value["updatedAt"] = "2026-01-02T00:00:00Z"
    value["segments"][0]["text"] = "Texto corregido"
    database.save_project(value)
    assert database.load_project(value["id"])["insights"] is None


def test_assistant_markers_evidence_and_global_search_are_persistent(tmp_path):
    database = ProjectDatabase(tmp_path / "datos.sqlite3")
    value = project()
    value["segments"][0]["text"] = "La reunión trata sobre el presupuesto anual"
    database.save_project(value)
    database.save_assistant_message(value["id"], "user", "¿Cuál es el tema?")
    marker = database.save_marker(value["id"], 750, "important", "Presupuesto")
    database.record_evidence(value["id"], "manual_review", {"segmentId": "s1"})

    assert database.list_assistant_messages(value["id"])[0]["content"].startswith("¿Cuál")
    assert database.list_markers(value["id"])[0]["id"] == marker["id"]
    assert database.list_evidence(value["id"])[0]["eventType"] == "manual_review"
    assert database.search_transcripts("presupuesto vacaciones")[0]["segmentId"] == "s1"


def test_queue_reorders_claims_and_recovers_interrupted_item(tmp_path):
    path = tmp_path / "datos.sqlite3"
    database = ProjectDatabase(path)
    first = project()
    second = {**project(), "id": "segundo", "name": "Segundo proyecto"}
    second["segments"] = []
    database.enqueue_project(first)
    database.enqueue_project(second)
    database.reorder_queue([second["id"], first["id"]])

    assert database.claim_next_queued_project()["id"] == second["id"]
    assert database.list_queue()[0]["state"] == "running"
    recovered = ProjectDatabase(path)
    assert recovered.list_queue()[0]["state"] == "queued"


def test_queue_persists_concurrency_and_individual_progress(tmp_path):
    database = ProjectDatabase(tmp_path / "datos.sqlite3")
    value = project()
    database.enqueue_project(value)
    database.set_preference("queue.max_concurrent_jobs", 2)
    database.update_job(
        value["id"],
        "transcribing",
        25_000,
        100_000,
        progress_percent=42.5,
        stage="transcribing",
        phase="Transcribiendo…",
        message="Reconociendo voz",
        device="cuda",
        active_model="turbo",
        speed_x=8.2,
        eta_ms=9_000,
    )

    item = database.list_queue()[0]

    assert database.get_preference("queue.max_concurrent_jobs") == 2
    assert item["processedDurationMs"] == 25_000
    assert item["percent"] == 42.5
    assert item["activeModel"] == "turbo"
    assert item["etaMs"] == 9_000


def test_version_restore_snapshots_current_text_and_records_evidence(tmp_path):
    database = ProjectDatabase(tmp_path / "datos.sqlite3")
    value = project()
    database.save_project(value)
    assert database.create_transcript_version(value["id"])
    version_id = database.list_versions(value["id"])[0]["id"]
    value["segments"][0]["text"] = "Texto posterior"
    database.save_project(value)

    restored = database.restore_version(value["id"], version_id)

    assert restored["segments"][0]["text"] == "Hola mundo"
    assert len(database.list_versions(value["id"])) == 2
    assert database.list_evidence(value["id"])[0]["eventType"] == "version_restored"
