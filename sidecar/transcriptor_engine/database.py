from __future__ import annotations

import json
import os
import sqlite3
import threading
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np

from .paths import app_data_dir
from .unicode_text import repair_data, sanitize_data
from .voice_crypto import encryption_label, protect_embedding, unprotect_embedding

SCHEMA_VERSION = 9
VOICE_PROFILE_SAMPLE_LIMIT = 160
VOICE_OBSERVATION_SAMPLE_LIMIT = 24
NEW_PROFILE_TWO_SAMPLE_MIN_COHERENCE = 0.90
REVIEW_STATES = {"pending", "accepted", "corrected", "ignored"}
_VOICE_LEARNING_LOCKS_GUARD = threading.Lock()
_VOICE_LEARNING_LOCKS: dict[str, threading.RLock] = {}


def _voice_learning_lock_for(path: Path) -> threading.RLock:
    """Share profile-discovery exclusion across database instances in this process."""
    key = os.path.normcase(str(path.resolve()))
    with _VOICE_LEARNING_LOCKS_GUARD:
        return _VOICE_LEARNING_LOCKS.setdefault(key, threading.RLock())


class ProjectDatabase:
    def __init__(self, path: Path | None = None) -> None:
        self.path = path or app_data_dir() / "transcriptor.sqlite3"
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._voice_learning_lock = _voice_learning_lock_for(self.path)
        self.migrate()

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self.path, timeout=15)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA journal_mode = WAL")
        try:
            yield connection
            connection.commit()
        finally:
            connection.close()

    def migrate(self) -> None:
        with self.connect() as db:
            db.executescript(
                """
                CREATE TABLE IF NOT EXISTS schema_migrations (
                    version INTEGER PRIMARY KEY,
                    applied_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );
                CREATE TABLE IF NOT EXISTS projects (
                    id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    media_path TEXT NOT NULL,
                    media_hash TEXT,
                    media_type TEXT NOT NULL CHECK(media_type IN ('audio', 'video')),
                    duration_ms INTEGER NOT NULL DEFAULT 0,
                    language TEXT,
                    detected_language TEXT,
                    model TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    transcription_status TEXT NOT NULL,
                    last_playback_position_ms INTEGER NOT NULL DEFAULT 0,
                    settings_json TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS segments (
                    id TEXT PRIMARY KEY,
                    project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
                    start_ms INTEGER NOT NULL,
                    end_ms INTEGER NOT NULL,
                    text TEXT NOT NULL,
                    speaker TEXT,
                    confidence REAL,
                    speaker_confidence REAL,
                    review_state TEXT,
                    speaker_review_state TEXT,
                    segment_order INTEGER NOT NULL
                );
                CREATE INDEX IF NOT EXISTS ix_segments_project_order ON segments(project_id, segment_order);
                CREATE TABLE IF NOT EXISTS words (
                    id TEXT PRIMARY KEY,
                    segment_id TEXT NOT NULL REFERENCES segments(id) ON DELETE CASCADE,
                    start_ms INTEGER NOT NULL,
                    end_ms INTEGER NOT NULL,
                    text TEXT NOT NULL,
                    probability REAL
                );
                CREATE INDEX IF NOT EXISTS ix_words_segment_start ON words(segment_id, start_ms);
                CREATE TABLE IF NOT EXISTS transcription_jobs (
                    id TEXT PRIMARY KEY,
                    project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
                    state TEXT NOT NULL,
                    processed_duration_ms INTEGER NOT NULL DEFAULT 0,
                    total_duration_ms INTEGER NOT NULL DEFAULT 0,
                    error_code TEXT,
                    error_message TEXT,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );
                CREATE TABLE IF NOT EXISTS transcript_versions (
                    id TEXT PRIMARY KEY,
                    project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    model TEXT NOT NULL,
                    segment_count INTEGER NOT NULL,
                    segments_json TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS ix_versions_project_created
                    ON transcript_versions(project_id, created_at DESC);
                CREATE TABLE IF NOT EXISTS project_insights (
                    project_id TEXT PRIMARY KEY REFERENCES projects(id) ON DELETE CASCADE,
                    generated_at TEXT NOT NULL,
                    method TEXT NOT NULL,
                    source_updated_at TEXT NOT NULL,
                    insights_json TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS assistant_messages (
                    id TEXT PRIMARY KEY,
                    project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
                    role TEXT NOT NULL CHECK(role IN ('user', 'assistant')),
                    content TEXT NOT NULL,
                    citations_json TEXT NOT NULL DEFAULT '[]',
                    model TEXT,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );
                CREATE INDEX IF NOT EXISTS ix_assistant_project_created
                    ON assistant_messages(project_id, created_at);
                CREATE TABLE IF NOT EXISTS job_queue (
                    id TEXT PRIMARY KEY,
                    project_id TEXT NOT NULL UNIQUE REFERENCES projects(id) ON DELETE CASCADE,
                    position INTEGER NOT NULL,
                    state TEXT NOT NULL,
                    settings_json TEXT NOT NULL,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );
                CREATE INDEX IF NOT EXISTS ix_job_queue_position ON job_queue(position, created_at);
                CREATE TABLE IF NOT EXISTS app_preferences (
                    key TEXT PRIMARY KEY,
                    value_json TEXT NOT NULL,
                    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );
                CREATE TABLE IF NOT EXISTS project_markers (
                    id TEXT PRIMARY KEY,
                    project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
                    time_ms INTEGER NOT NULL,
                    kind TEXT NOT NULL,
                    label TEXT NOT NULL,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );
                CREATE INDEX IF NOT EXISTS ix_markers_project_time
                    ON project_markers(project_id, time_ms);
                CREATE TABLE IF NOT EXISTS evidence_events (
                    id TEXT PRIMARY KEY,
                    project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
                    event_type TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );
                CREATE INDEX IF NOT EXISTS ix_evidence_project_created
                    ON evidence_events(project_id, created_at);
                CREATE TABLE IF NOT EXISTS voice_profiles (
                    id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    color TEXT NOT NULL,
                    centroid_blob BLOB,
                    sample_count INTEGER NOT NULL DEFAULT 0,
                    total_duration_ms INTEGER NOT NULL DEFAULT 0,
                    match_threshold REAL NOT NULL DEFAULT 0.64,
                    enabled INTEGER NOT NULL DEFAULT 1,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    last_matched_at TEXT
                );
                CREATE TABLE IF NOT EXISTS voice_profile_samples (
                    id TEXT PRIMARY KEY,
                    profile_id TEXT NOT NULL REFERENCES voice_profiles(id) ON DELETE CASCADE,
                    source_project_id TEXT,
                    source_segment_id TEXT,
                    embedding_blob BLOB NOT NULL,
                    duration_ms INTEGER NOT NULL,
                    confidence REAL NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS ix_voice_samples_profile_created
                    ON voice_profile_samples(profile_id, created_at DESC);
                """
            )
            segment_columns = {
                str(row["name"]) for row in db.execute("PRAGMA table_info(segments)").fetchall()
            }
            if "speaker_confidence" not in segment_columns:
                db.execute("ALTER TABLE segments ADD COLUMN speaker_confidence REAL")
            if "speaker_profile_id" not in segment_columns:
                db.execute("ALTER TABLE segments ADD COLUMN speaker_profile_id TEXT")
            if "speaker_match_confidence" not in segment_columns:
                db.execute("ALTER TABLE segments ADD COLUMN speaker_match_confidence REAL")
            if "review_state" not in segment_columns:
                db.execute("ALTER TABLE segments ADD COLUMN review_state TEXT")
            if "speaker_review_state" not in segment_columns:
                db.execute("ALTER TABLE segments ADD COLUMN speaker_review_state TEXT")
            job_columns = {
                str(row["name"]) for row in db.execute("PRAGMA table_info(transcription_jobs)").fetchall()
            }
            for column, definition in (
                ("progress_percent", "REAL"),
                ("stage", "TEXT"),
                ("phase", "TEXT"),
                ("message", "TEXT"),
                ("device", "TEXT"),
                ("active_model", "TEXT"),
                ("speed_x", "REAL"),
                ("eta_ms", "INTEGER"),
            ):
                if column not in job_columns:
                    db.execute(f"ALTER TABLE transcription_jobs ADD COLUMN {column} {definition}")
            db.execute("INSERT OR IGNORE INTO schema_migrations(version) VALUES (?)", (SCHEMA_VERSION,))
            db.execute(
                "UPDATE transcription_jobs SET state='failed', error_code='INTERRUPTED', "
                "error_message='La aplicación se cerró antes de terminar.', updated_at=CURRENT_TIMESTAMP "
                "WHERE state IN ('analyzing', 'waiting_model', 'transcribing')"
            )
            db.execute(
                "UPDATE projects SET transcription_status='failed' WHERE transcription_status='transcribing'"
            )
            db.execute("UPDATE job_queue SET state='queued' WHERE state='running'")

    def update_job(
        self,
        project_id: str,
        state: str,
        processed_duration_ms: int,
        total_duration_ms: int,
        error_code: str | None = None,
        error_message: str | None = None,
        *,
        progress_percent: float | None = None,
        stage: str | None = None,
        phase: str | None = None,
        message: str | None = None,
        device: str | None = None,
        active_model: str | None = None,
        speed_x: float | None = None,
        eta_ms: int | None = None,
    ) -> None:
        with self.connect() as db:
            db.execute(
                """INSERT INTO transcription_jobs
                (id, project_id, state, processed_duration_ms, total_duration_ms,
                    error_code, error_message, progress_percent, stage, phase, message,
                    device, active_model, speed_x, eta_ms)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET state=excluded.state,
                    processed_duration_ms=excluded.processed_duration_ms,
                    total_duration_ms=excluded.total_duration_ms,
                    error_code=excluded.error_code, error_message=excluded.error_message,
                    progress_percent=COALESCE(excluded.progress_percent, transcription_jobs.progress_percent),
                    stage=COALESCE(excluded.stage, transcription_jobs.stage),
                    phase=COALESCE(excluded.phase, transcription_jobs.phase),
                    message=COALESCE(excluded.message, transcription_jobs.message),
                    device=COALESCE(excluded.device, transcription_jobs.device),
                    active_model=COALESCE(excluded.active_model, transcription_jobs.active_model),
                    speed_x=COALESCE(excluded.speed_x, transcription_jobs.speed_x),
                    eta_ms=COALESCE(excluded.eta_ms, transcription_jobs.eta_ms),
                    updated_at=CURRENT_TIMESTAMP""",
                (
                    project_id,
                    project_id,
                    state,
                    processed_duration_ms,
                    total_duration_ms,
                    error_code,
                    error_message,
                    progress_percent,
                    stage,
                    phase,
                    message,
                    device,
                    active_model,
                    speed_x,
                    eta_ms,
                ),
            )

    def get_preference(self, key: str, default: Any = None) -> Any:
        with self.connect() as db:
            row = db.execute("SELECT value_json FROM app_preferences WHERE key = ?", (key,)).fetchone()
        if not row:
            return default
        try:
            return repair_data(json.loads(row["value_json"]))
        except (json.JSONDecodeError, TypeError):
            return default

    def set_preference(self, key: str, value: Any) -> None:
        with self.connect() as db:
            db.execute(
                """INSERT INTO app_preferences(key, value_json) VALUES (?, ?)
                ON CONFLICT(key) DO UPDATE SET value_json=excluded.value_json,
                    updated_at=CURRENT_TIMESTAMP""",
                (key, json.dumps(sanitize_data(value), ensure_ascii=False)),
            )

    def update_project_status(self, project_id: str, status: str, updated_at: str) -> None:
        with self.connect() as db:
            cursor = db.execute(
                "UPDATE projects SET transcription_status = ?, updated_at = ? WHERE id = ?",
                (status, updated_at, project_id),
            )
            if cursor.rowcount != 1:
                raise KeyError("El proyecto no existe o fue eliminado.")

    def save_project(self, project: dict[str, Any]) -> None:
        project = repair_data(sanitize_data(project))
        settings = project.get("settings", {})
        with self.connect() as db:
            db.execute(
                """INSERT INTO projects VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    name=excluded.name, media_path=excluded.media_path, media_hash=excluded.media_hash,
                    media_type=excluded.media_type, duration_ms=excluded.duration_ms,
                    language=excluded.language, detected_language=excluded.detected_language,
                    model=excluded.model, updated_at=excluded.updated_at,
                    transcription_status=excluded.transcription_status,
                    last_playback_position_ms=excluded.last_playback_position_ms,
                    settings_json=excluded.settings_json""",
                (
                    project["id"],
                    project["name"],
                    project["mediaPath"],
                    project.get("mediaHash"),
                    project["mediaType"],
                    int(project.get("durationMs", 0)),
                    project.get("language"),
                    project.get("detectedLanguage"),
                    project.get("model", settings.get("model", "small")),
                    project["createdAt"],
                    project["updatedAt"],
                    project.get("transcriptionStatus", "idle"),
                    int(project.get("lastPlaybackPositionMs", 0)),
                    json.dumps(settings, ensure_ascii=False),
                ),
            )
            db.execute("DELETE FROM segments WHERE project_id = ?", (project["id"],))
            for order, segment in enumerate(project.get("segments", [])):
                review_state = segment.get("reviewState")
                if review_state not in REVIEW_STATES:
                    review_state = None
                speaker_review_state = segment.get("speakerReviewState")
                if speaker_review_state not in REVIEW_STATES:
                    speaker_review_state = None
                db.execute(
                    """INSERT INTO segments
                    (id, project_id, start_ms, end_ms, text, speaker, confidence,
                     speaker_confidence, speaker_profile_id, speaker_match_confidence,
                     review_state, speaker_review_state, segment_order)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        segment["id"],
                        project["id"],
                        int(segment["startMs"]),
                        int(segment["endMs"]),
                        segment.get("text", ""),
                        segment.get("speaker"),
                        segment.get("confidence"),
                        segment.get("speakerConfidence"),
                        segment.get("speakerProfileId"),
                        segment.get("speakerMatchConfidence"),
                        review_state,
                        speaker_review_state,
                        int(segment.get("order", order)),
                    ),
                )
                db.executemany(
                    "INSERT INTO words VALUES (?, ?, ?, ?, ?, ?)",
                    [
                        (
                            word["id"],
                            segment["id"],
                            int(word["startMs"]),
                            int(word["endMs"]),
                            word.get("text", ""),
                            word.get("probability"),
                        )
                        for word in segment.get("words", [])
                    ],
                )

    def load_project(self, project_id: str) -> dict[str, Any]:
        with self.connect() as db:
            row = db.execute("SELECT * FROM projects WHERE id = ?", (project_id,)).fetchone()
            if not row:
                raise KeyError("El proyecto no existe o fue eliminado.")
            segment_rows = db.execute(
                "SELECT * FROM segments WHERE project_id = ? ORDER BY segment_order, start_ms", (project_id,)
            ).fetchall()
            word_rows = db.execute(
                """SELECT words.* FROM words
                   JOIN segments ON segments.id = words.segment_id
                   WHERE segments.project_id = ?
                   ORDER BY segments.segment_order, words.start_ms""",
                (project_id,),
            ).fetchall()
            words_by_segment: dict[str, list[sqlite3.Row]] = {}
            for word in word_rows:
                words_by_segment.setdefault(str(word["segment_id"]), []).append(word)
            segments = []
            for segment in segment_rows:
                words = words_by_segment.get(str(segment["id"]), [])
                segments.append(
                    {
                        "id": segment["id"],
                        "startMs": segment["start_ms"],
                        "endMs": segment["end_ms"],
                        "text": segment["text"],
                        "speaker": segment["speaker"],
                        "confidence": segment["confidence"],
                        "speakerConfidence": segment["speaker_confidence"],
                        "speakerProfileId": segment["speaker_profile_id"],
                        "speakerMatchConfidence": segment["speaker_match_confidence"],
                        "speakerProvisional": False,
                        "reviewState": segment["review_state"],
                        "speakerReviewState": segment["speaker_review_state"],
                        "order": segment["segment_order"],
                        "words": [
                            {
                                "id": word["id"],
                                "startMs": word["start_ms"],
                                "endMs": word["end_ms"],
                                "text": word["text"],
                                "probability": word["probability"],
                            }
                            for word in words
                        ],
                    }
                )
            insights_row = db.execute(
                "SELECT insights_json FROM project_insights WHERE project_id = ? AND source_updated_at = ?",
                (project_id, row["updated_at"]),
            ).fetchone()
            return repair_data(
                {
                    "id": row["id"],
                    "name": row["name"],
                    "mediaPath": row["media_path"],
                    "mediaHash": row["media_hash"],
                    "mediaUrl": "",
                    "mediaType": row["media_type"],
                    "durationMs": row["duration_ms"],
                    "language": row["language"],
                    "detectedLanguage": row["detected_language"],
                    "model": row["model"],
                    "createdAt": row["created_at"],
                    "updatedAt": row["updated_at"],
                    "transcriptionStatus": row["transcription_status"],
                    "lastPlaybackPositionMs": row["last_playback_position_ms"],
                    "settings": json.loads(row["settings_json"]),
                    "segments": segments,
                    "insights": json.loads(insights_row["insights_json"]) if insights_row else None,
                }
            )

    def delete_project(self, project_id: str) -> dict[str, Any]:
        """Delete application data for a project without touching its source media."""
        with self.connect() as db:
            row = db.execute("SELECT name, media_path FROM projects WHERE id = ?", (project_id,)).fetchone()
            if not row:
                raise KeyError("El proyecto no existe o ya fue eliminado.")
            db.execute("DELETE FROM projects WHERE id = ?", (project_id,))
            return {
                "deleted": True,
                "projectId": project_id,
                "name": row["name"],
                "mediaPath": row["media_path"],
                "mediaPreserved": True,
            }

    def list_voice_profiles(self) -> dict[str, Any]:
        with self.connect() as db:
            rows = db.execute(
                """WITH sample_metrics AS (
                    SELECT profile_id,
                        COUNT(DISTINCT CASE
                            WHEN source_project_id IS NOT NULL AND source_project_id != ''
                            THEN source_project_id END) AS source_project_count,
                        AVG(confidence) AS average_sample_confidence
                    FROM voice_profile_samples
                    GROUP BY profile_id
                ),
                recognition_metrics AS (
                    SELECT s.speaker_profile_id AS profile_id,
                        COUNT(*) AS recognized_segment_count,
                        COALESCE(SUM(CASE WHEN s.end_ms > s.start_ms
                            THEN s.end_ms - s.start_ms ELSE 0 END), 0) AS recognized_duration_ms,
                        COUNT(DISTINCT s.project_id) AS recognized_project_count,
                        AVG(CASE
                            WHEN s.speaker_match_confidence
                                BETWEEN matched_profile.match_threshold AND 1.0
                            THEN s.speaker_match_confidence
                        END) AS average_match_confidence
                    FROM segments s
                    JOIN voice_profiles matched_profile
                        ON matched_profile.id = s.speaker_profile_id
                    WHERE s.speaker_profile_id IS NOT NULL
                    GROUP BY s.speaker_profile_id
                )
                SELECT vp.id, vp.name, vp.color, vp.sample_count, vp.total_duration_ms,
                    vp.match_threshold, vp.enabled, vp.created_at, vp.updated_at,
                    vp.last_matched_at, vp.centroid_blob IS NOT NULL AS ready,
                    COALESCE(sm.source_project_count, 0) AS source_project_count,
                    sm.average_sample_confidence,
                    COALESCE(rm.recognized_segment_count, 0) AS recognized_segment_count,
                    COALESCE(rm.recognized_duration_ms, 0) AS recognized_duration_ms,
                    COALESCE(rm.recognized_project_count, 0) AS recognized_project_count,
                    rm.average_match_confidence
                FROM voice_profiles vp
                LEFT JOIN sample_metrics sm ON sm.profile_id = vp.id
                LEFT JOIN recognition_metrics rm ON rm.profile_id = vp.id
                ORDER BY vp.enabled DESC, vp.updated_at DESC, vp.name COLLATE NOCASE"""
            ).fetchall()
        profiles: list[dict[str, Any]] = []
        for row in rows:
            average_match_confidence = (
                float(row["average_match_confidence"])
                if row["average_match_confidence"] is not None
                else None
            )
            reliability_score = self._voice_reliability_score(
                sample_count=int(row["sample_count"]),
                total_duration_ms=int(row["total_duration_ms"]),
                source_project_count=int(row["source_project_count"]),
                average_match_confidence=average_match_confidence,
            )
            profiles.append(
                {
                    "id": row["id"],
                    "name": row["name"],
                    "color": row["color"],
                    "sampleCount": row["sample_count"],
                    "totalDurationMs": row["total_duration_ms"],
                    "sourceProjectCount": row["source_project_count"],
                    "averageSampleConfidence": (
                        float(row["average_sample_confidence"])
                        if row["average_sample_confidence"] is not None
                        else None
                    ),
                    "recognizedSegmentCount": row["recognized_segment_count"],
                    "recognizedDurationMs": row["recognized_duration_ms"],
                    "recognizedProjectCount": row["recognized_project_count"],
                    "averageMatchConfidence": average_match_confidence,
                    "averageProfileSimilarity": average_match_confidence,
                    "matchThreshold": row["match_threshold"],
                    "enabled": bool(row["enabled"]),
                    "ready": bool(row["ready"]),
                    "createdAt": row["created_at"],
                    "updatedAt": row["updated_at"],
                    "lastMatchedAt": row["last_matched_at"],
                    "reliabilityScore": reliability_score,
                    "reliability": self._voice_reliability(reliability_score),
                }
            )
        return {
            "profiles": repair_data(profiles),
            "encryption": encryption_label(),
            "storesRawAudio": False,
        }

    def load_voice_matcher_profiles(self) -> list[dict[str, Any]]:
        with self.connect() as db:
            rows = db.execute(
                """SELECT id, name, centroid_blob, match_threshold, enabled
                FROM voice_profiles WHERE enabled = 1 AND centroid_blob IS NOT NULL"""
            ).fetchall()
        profiles: list[dict[str, Any]] = []
        for row in rows:
            try:
                centroid = unprotect_embedding(bytes(row["centroid_blob"]))
            except (OSError, ValueError):
                continue
            profiles.append(
                {
                    "id": row["id"],
                    "name": row["name"],
                    "centroid": centroid.tolist(),
                    "matchThreshold": float(row["match_threshold"]),
                    "enabled": True,
                }
            )
        return profiles

    def update_voice_profile(
        self,
        profile_id: str,
        *,
        name: str | None = None,
        enabled: bool | None = None,
        match_threshold: float | None = None,
    ) -> dict[str, Any]:
        assignments: list[str] = []
        values: list[Any] = []
        if name is not None:
            clean_name = str(sanitize_data(name)).strip()[:40]
            if not clean_name:
                raise ValueError("El nombre del hablante no puede estar vacío.")
            assignments.append("name = ?")
            values.append(clean_name)
        if enabled is not None:
            assignments.append("enabled = ?")
            values.append(1 if enabled else 0)
        if match_threshold is not None:
            assignments.append("match_threshold = ?")
            values.append(max(0.55, min(0.86, float(match_threshold))))
        if not assignments:
            raise ValueError("No hay cambios que guardar en el perfil.")
        assignments.append("updated_at = ?")
        values.append(datetime.now(UTC).isoformat())
        values.append(profile_id)
        with self.connect() as db:
            cursor = db.execute(
                f"UPDATE voice_profiles SET {', '.join(assignments)} WHERE id = ?",
                values,
            )
            if cursor.rowcount != 1:
                raise KeyError("El perfil de voz ya no existe.")
        return self._voice_profile_summary(profile_id)

    def delete_voice_profile(self, profile_id: str) -> dict[str, Any]:
        with self.connect() as db:
            row = db.execute("SELECT name FROM voice_profiles WHERE id = ?", (profile_id,)).fetchone()
            if not row:
                raise KeyError("El perfil de voz ya no existe.")
            db.execute(
                """UPDATE segments SET speaker_profile_id = NULL, speaker_match_confidence = NULL
                WHERE speaker_profile_id = ?""",
                (profile_id,),
            )
            db.execute("DELETE FROM voice_profiles WHERE id = ?", (profile_id,))
        return {"deleted": True, "profileId": profile_id, "name": row["name"]}

    def compare_voice_profiles(
        self,
        source_profile_id: str,
        target_profile_id: str,
    ) -> dict[str, Any]:
        if source_profile_id == target_profile_id:
            raise ValueError("El perfil de origen y el de destino deben ser diferentes.")
        with self.connect() as db:
            rows = db.execute(
                """SELECT id, name, centroid_blob, match_threshold
                FROM voice_profiles WHERE id IN (?, ?)""",
                (source_profile_id, target_profile_id),
            ).fetchall()
        profiles = {str(row["id"]): row for row in rows}
        if source_profile_id not in profiles:
            raise KeyError("El perfil de voz de origen ya no existe.")
        if target_profile_id not in profiles:
            raise KeyError("El perfil de voz de destino ya no existe.")
        source = profiles[source_profile_id]
        target = profiles[target_profile_id]
        similarity: float | None = None
        try:
            if source["centroid_blob"] is not None and target["centroid_blob"] is not None:
                source_centroid = unprotect_embedding(bytes(source["centroid_blob"]))
                target_centroid = unprotect_embedding(bytes(target["centroid_blob"]))
                similarity = float(np.clip(np.dot(source_centroid, target_centroid), -1.0, 1.0))
        except (OSError, ValueError):
            similarity = None
        threshold = max(
            float(source["match_threshold"]),
            float(target["match_threshold"]),
        )
        if similarity is None:
            verdict = "sin_datos"
        elif similarity >= threshold + 0.08:
            verdict = "alta"
        elif similarity >= threshold:
            verdict = "compatible"
        else:
            verdict = "baja"
        return {
            "sourceProfileId": source_profile_id,
            "sourceName": str(source["name"]),
            "targetProfileId": target_profile_id,
            "targetName": str(target["name"]),
            "similarity": similarity,
            "threshold": threshold,
            "verdict": verdict,
        }

    def merge_voice_profiles(
        self,
        source_profile_id: str,
        target_profile_id: str,
    ) -> dict[str, Any]:
        if source_profile_id == target_profile_id:
            raise ValueError("El perfil de origen y el de destino deben ser diferentes.")
        now = datetime.now(UTC).isoformat()
        affected_project_ids: list[str] = []
        moved_samples = 0
        removed_samples = 0
        updated_segments = 0
        source_name = ""
        target_name = ""
        with self.connect() as db:
            rows = db.execute(
                """SELECT id, name, centroid_blob, sample_count, total_duration_ms,
                    match_threshold, last_matched_at
                FROM voice_profiles WHERE id IN (?, ?)""",
                (source_profile_id, target_profile_id),
            ).fetchall()
            profiles = {str(row["id"]): row for row in rows}
            if source_profile_id not in profiles:
                raise KeyError("El perfil de voz de origen ya no existe.")
            if target_profile_id not in profiles:
                raise KeyError("El perfil de voz de destino ya no existe.")
            source = profiles[source_profile_id]
            target = profiles[target_profile_id]
            source_name = str(source["name"])
            target_name = str(target["name"])

            affected_project_ids = [
                str(row["project_id"])
                for row in db.execute(
                    """SELECT DISTINCT project_id FROM segments
                    WHERE speaker_profile_id = ? ORDER BY project_id""",
                    (source_profile_id,),
                ).fetchall()
            ]
            moved_samples = int(
                db.execute(
                    "SELECT COUNT(*) FROM voice_profile_samples WHERE profile_id = ?",
                    (source_profile_id,),
                ).fetchone()[0]
            )
            db.execute(
                "UPDATE voice_profile_samples SET profile_id = ? WHERE profile_id = ?",
                (target_profile_id, source_profile_id),
            )

            combined_sample_count = int(
                db.execute(
                    "SELECT COUNT(*) FROM voice_profile_samples WHERE profile_id = ?",
                    (target_profile_id,),
                ).fetchone()[0]
            )
            rebuilt_centroid, rebuilt_count, rebuilt_duration = (
                self._rebuild_voice_profile_memory(db, target_profile_id)
            )
            removed_samples = max(0, combined_sample_count - rebuilt_count)

            samples = db.execute(
                """SELECT id, source_project_id, source_segment_id, embedding_blob,
                    duration_ms, confidence, created_at
                FROM voice_profile_samples WHERE profile_id = ?
                ORDER BY confidence DESC, created_at DESC""",
                (target_profile_id,),
            ).fetchall()
            retained: list[sqlite3.Row] = []
            duplicate_ids: list[str] = []
            seen_sources: set[tuple[str, str]] = set()
            for sample in samples:
                project_id = str(sample["source_project_id"] or "")
                segment_id = str(sample["source_segment_id"] or "")
                source_key = (project_id, segment_id)
                if project_id and segment_id and source_key in seen_sources:
                    duplicate_ids.append(str(sample["id"]))
                    continue
                if project_id and segment_id:
                    seen_sources.add(source_key)
                if len(retained) < VOICE_PROFILE_SAMPLE_LIMIT:
                    retained.append(sample)
                else:
                    duplicate_ids.append(str(sample["id"]))
            if duplicate_ids:
                db.executemany(
                    "DELETE FROM voice_profile_samples WHERE id = ?",
                    [(sample_id,) for sample_id in duplicate_ids],
                )
            removed_samples += len(duplicate_ids)

            vectors: list[np.ndarray] = []
            weights: list[float] = []
            corrupt_ids: list[str] = []
            for sample in retained:
                try:
                    vector = unprotect_embedding(bytes(sample["embedding_blob"]))
                    if vector.size != 192 or not np.isfinite(vector).all():
                        raise ValueError("Huella de voz inválida.")
                except (OSError, ValueError):
                    continue
                vectors.append(vector)
                duration_weight = min(max(float(sample["duration_ms"]) / 1_000.0, 0.65), 6.0)
                weights.append(max(float(sample["confidence"]), 0.01) * duration_weight)
            if corrupt_ids:
                db.executemany(
                    "DELETE FROM voice_profile_samples WHERE id = ?",
                    [(sample_id,) for sample_id in corrupt_ids],
                )
                removed_samples += len(corrupt_ids)

            centroid: np.ndarray | None = None
            if vectors:
                centroid = np.average(np.stack(vectors), axis=0, weights=np.asarray(weights))
                centroid /= max(float(np.linalg.norm(centroid)), 1e-8)
            elif target["centroid_blob"] is not None:
                try:
                    centroid = unprotect_embedding(bytes(target["centroid_blob"]))
                except (OSError, ValueError):
                    centroid = None
            if rebuilt_centroid is not None:
                centroid = rebuilt_centroid

            last_matched_at = (
                max(
                    str(source["last_matched_at"] or ""),
                    str(target["last_matched_at"] or ""),
                )
                or None
            )
            db.execute(
                """UPDATE voice_profiles SET centroid_blob = ?, sample_count = ?,
                    total_duration_ms = ?, updated_at = ?, last_matched_at = ?
                WHERE id = ?""",
                (
                    protect_embedding(centroid) if centroid is not None else None,
                    rebuilt_count,
                    rebuilt_duration,
                    now,
                    last_matched_at,
                    target_profile_id,
                ),
            )
            cursor = db.execute(
                """UPDATE segments SET speaker_profile_id = ?, speaker = ?
                WHERE speaker_profile_id = ?""",
                (target_profile_id, target_name, source_profile_id),
            )
            updated_segments = int(cursor.rowcount)
            db.execute("DELETE FROM voice_profiles WHERE id = ?", (source_profile_id,))

        catalog = self.list_voice_profiles()
        target_profile = next(
            profile for profile in catalog["profiles"] if profile["id"] == target_profile_id
        )
        return {
            "merged": True,
            "sourceProfileId": source_profile_id,
            "sourceName": source_name,
            "targetProfileId": target_profile_id,
            "targetName": target_name,
            "targetProfile": target_profile,
            "movedSamples": moved_samples,
            "removedSamples": removed_samples,
            "retainedSamples": int(target_profile["sampleCount"]),
            "updatedSegments": updated_segments,
            "affectedProjectIds": affected_project_ids,
            "catalog": catalog,
        }

    def learn_voice_observations(
        self,
        project_id: str,
        observations: list[dict[str, Any]],
        min_confidence: float = 0.72,
        *,
        replace_project_evidence: bool = False,
    ) -> dict[str, Any]:
        # Jobs may transcribe in parallel, but profile discovery must observe
        # the latest committed centroids before creating a new local identity.
        with self._voice_learning_lock:
            return self._learn_voice_observations_unlocked(
                project_id,
                observations,
                min_confidence,
                replace_project_evidence,
            )

    def _learn_voice_observations_unlocked(
        self,
        project_id: str,
        observations: list[dict[str, Any]],
        min_confidence: float,
        replace_project_evidence: bool,
    ) -> dict[str, Any]:
        learned_samples = 0
        created_profiles: list[str] = []
        assignments: list[dict[str, Any]] = []
        received_samples = 0
        rejected_samples = 0
        rejected_observations = 0
        eligible_samples = 0
        selected_samples = 0
        not_selected_samples = 0
        duplicate_samples = 0
        replaced_samples = 0
        rejection_reasons = {
            "invalidEmbedding": 0,
            "lowConfidence": 0,
            "durationOutsideRange": 0,
            "insufficientClearAudio": 0,
            "profilePaused": 0,
            "profileNotFound": 0,
            "weakProfileMatch": 0,
            "weakProfileSample": 0,
            "incoherentVoice": 0,
            "paddedContext": 0,
        }
        now = datetime.now(UTC).isoformat()
        palette = ("#c9ff48", "#7dd3fc", "#f0abfc", "#fdba74", "#86efac", "#fda4af")
        confidence_threshold = max(0.6, min(0.92, float(min_confidence)))
        refreshed_profile_sources: set[tuple[str, str]] = set()
        successful_project_profiles: set[str] = set()
        with self.connect() as db:
            # Reserve the SQLite writer before reading candidate centroids. This
            # also serializes profile discovery with other application processes.
            db.execute("BEGIN IMMEDIATE")
            previous_project_profiles = (
                {
                    str(row["profile_id"])
                    for row in db.execute(
                        """SELECT DISTINCT profile_id FROM voice_profile_samples
                        WHERE source_project_id = ?""",
                        (project_id,),
                    ).fetchall()
                }
                if project_id
                else set()
            )
            for observation in observations:
                valid_samples: list[dict[str, Any]] = []
                for sequence, sample in enumerate(observation.get("samples", [])):
                    received_samples += 1
                    try:
                        vector = np.asarray(sample["embedding"], dtype=np.float32).reshape(-1)
                        confidence = float(sample.get("confidence") or 0)
                        duration_ms = int(sample.get("durationMs") or 0)
                    except (KeyError, TypeError, ValueError):
                        rejected_samples += 1
                        rejection_reasons["invalidEmbedding"] += 1
                        continue
                    if vector.size != 192 or not np.isfinite(vector).all():
                        rejected_samples += 1
                        rejection_reasons["invalidEmbedding"] += 1
                        continue
                    norm = float(np.linalg.norm(vector))
                    if norm < 1e-8:
                        rejected_samples += 1
                        rejection_reasons["invalidEmbedding"] += 1
                        continue
                    if confidence < confidence_threshold:
                        rejected_samples += 1
                        rejection_reasons["lowConfidence"] += 1
                        continue
                    if sample.get("learningEligible") is False:
                        rejected_samples += 1
                        rejection_reasons["paddedContext"] += 1
                        continue
                    if not 650 <= duration_ms <= 8_000:
                        rejected_samples += 1
                        rejection_reasons["durationOutsideRange"] += 1
                        continue
                    try:
                        temporal_position = int(sample.get("startMs", sequence))
                    except (TypeError, ValueError):
                        temporal_position = sequence
                    valid_samples.append(
                        {
                            **sample,
                            "_vector": vector / norm,
                            "_sequence": sequence,
                            "_temporalPosition": temporal_position,
                        }
                    )
                eligible_samples += len(valid_samples)
                qualified = self._select_temporally_diverse_voice_samples(
                    valid_samples,
                    VOICE_OBSERVATION_SAMPLE_LIMIT,
                )
                selected_samples += len(qualified)
                not_selected_samples += max(0, len(valid_samples) - len(qualified))
                if not qualified or sum(int(item["durationMs"]) for item in qualified) < 1_300:
                    rejected_observations += 1
                    rejection_reasons["insufficientClearAudio"] += 1
                    continue

                matched_id = str(observation.get("matchedProfileId") or "")
                row = (
                    db.execute(
                        """SELECT id, name, centroid_blob, sample_count, enabled, match_threshold
                        FROM voice_profiles WHERE id = ?""",
                        (matched_id,),
                    ).fetchone()
                    if matched_id
                    else None
                )
                if matched_id and row is None:
                    rejected_observations += 1
                    rejected_samples += len(qualified)
                    rejection_reasons["profileNotFound"] += len(qualified)
                    continue
                if row is not None and not bool(row["enabled"]):
                    rejected_observations += 1
                    rejected_samples += len(qualified)
                    rejection_reasons["profilePaused"] += 1
                    continue

                observation_centroid, qualified, incoherent_count, coherence = (
                    self._robust_observation_centroid(qualified)
                )
                if incoherent_count:
                    rejected_samples += incoherent_count
                    rejection_reasons["incoherentVoice"] += incoherent_count
                if (
                    observation_centroid is None
                    or not qualified
                    or sum(int(item["durationMs"]) for item in qualified) < 1_300
                    or (len(qualified) >= 3 and coherence < 0.42)
                ):
                    rejected_observations += 1
                    rejected_samples += len(qualified)
                    rejection_reasons["insufficientClearAudio"] += 1
                    continue

                old_centroid: np.ndarray | None = None
                effective_match_confidence: float | None = None
                if row is None:
                    compatible: list[tuple[float, sqlite3.Row, np.ndarray]] = []
                    candidate_rows = db.execute(
                        """SELECT id, name, centroid_blob, sample_count, enabled,
                            match_threshold
                        FROM voice_profiles
                        WHERE enabled = 1 AND centroid_blob IS NOT NULL"""
                    ).fetchall()
                    for candidate in candidate_rows:
                        try:
                            candidate_centroid = unprotect_embedding(
                                bytes(candidate["centroid_blob"])
                            )
                            norm = float(np.linalg.norm(candidate_centroid))
                            if (
                                candidate_centroid.size != observation_centroid.size
                                or not np.isfinite(candidate_centroid).all()
                                or norm < 1e-8
                            ):
                                continue
                            candidate_centroid = candidate_centroid / norm
                        except (OSError, ValueError):
                            continue
                        compatible.append(
                            (
                                float(
                                    np.clip(
                                        np.dot(
                                            observation_centroid,
                                            candidate_centroid,
                                        ),
                                        -1.0,
                                        1.0,
                                    )
                                ),
                                candidate,
                                candidate_centroid,
                            )
                        )
                    compatible.sort(key=lambda item: item[0], reverse=True)
                    if compatible:
                        best_score, best_row, best_centroid = compatible[0]
                        alternative = compatible[1][0] if len(compatible) > 1 else None
                        required = min(
                            0.90,
                            float(best_row["match_threshold"]) + 0.015,
                        )
                        required = (
                            max(required, 0.72)
                            if len(compatible) == 1
                            else max(required, 0.70)
                        )
                        margin = (
                            best_score - alternative
                            if alternative is not None
                            else 1.0
                        )
                        if best_score >= required and margin >= 0.035:
                            row = best_row
                            old_centroid = best_centroid

                if row is not None:
                    if old_centroid is None:
                        try:
                            old_centroid = (
                                unprotect_embedding(bytes(row["centroid_blob"]))
                                if row["centroid_blob"] is not None
                                else None
                            )
                            if old_centroid is not None:
                                old_centroid = old_centroid / max(
                                    float(np.linalg.norm(old_centroid)),
                                    1e-8,
                                )
                        except (OSError, ValueError):
                            old_centroid = None
                    required_match = min(
                        0.90,
                        float(row["match_threshold"]) + 0.015,
                    )
                    if old_centroid is not None:
                        sample_floor = max(0.52, required_match - 0.03)
                        profile_filtered: list[dict[str, Any]] = []
                        for sample in qualified:
                            similarity = float(
                                np.clip(
                                    np.dot(sample["_vector"], old_centroid),
                                    -1.0,
                                    1.0,
                                )
                            )
                            if similarity >= sample_floor:
                                profile_filtered.append(sample)
                            else:
                                rejected_samples += 1
                                rejection_reasons["weakProfileSample"] += 1
                        qualified = profile_filtered
                        (
                            observation_centroid,
                            qualified,
                            profile_incoherent_count,
                            coherence,
                        ) = self._robust_observation_centroid(qualified)
                        if profile_incoherent_count:
                            rejected_samples += profile_incoherent_count
                            rejection_reasons[
                                "incoherentVoice"
                            ] += profile_incoherent_count
                    if (
                        observation_centroid is None
                        or not qualified
                        or sum(int(item["durationMs"]) for item in qualified) < 1_300
                        or (len(qualified) >= 3 and coherence < 0.42)
                    ):
                        rejected_observations += 1
                        rejected_samples += len(qualified)
                        rejection_reasons["insufficientClearAudio"] += 1
                        continue
                    match_evidence: list[float] = []
                    try:
                        reported_match = observation.get("matchConfidence")
                        if reported_match is not None:
                            match_evidence.append(float(reported_match))
                    except (TypeError, ValueError):
                        pass
                    if old_centroid is not None:
                        match_evidence.append(
                            float(np.clip(np.dot(observation_centroid, old_centroid), -1.0, 1.0))
                        )
                    effective_match_confidence = min(match_evidence) if match_evidence else None
                    if effective_match_confidence is None or effective_match_confidence < required_match:
                        rejected_observations += 1
                        rejected_samples += len(qualified)
                        rejection_reasons["weakProfileMatch"] += len(qualified)
                        continue
                if (
                    row is None
                    and len(qualified) == 2
                    and coherence < NEW_PROFILE_TWO_SAMPLE_MIN_COHERENCE
                ):
                    # With only two incompatible snippets there is no majority
                    # voice to trust. Wait for clearer evidence instead of
                    # creating a contaminated local identity.
                    rejected_observations += 1
                    rejected_samples += len(qualified)
                    rejection_reasons["incoherentVoice"] += len(qualified)
                    continue
                if row is None:
                    profile_id = str(uuid.uuid4())
                    suggested = str(observation.get("suggestedName") or "").strip()
                    if not suggested or suggested.startswith("Hablante "):
                        suggested = self._next_voice_name(db)
                    name = str(sanitize_data(suggested))[:40]
                    color_index = int(db.execute("SELECT COUNT(*) FROM voice_profiles").fetchone()[0]) % len(
                        palette
                    )
                    db.execute(
                        """INSERT INTO voice_profiles
                        (id, name, color, centroid_blob, sample_count, total_duration_ms,
                         match_threshold, enabled, created_at, updated_at, last_matched_at)
                        VALUES (?, ?, ?, NULL, 0, 0, 0.64, 1, ?, ?, ?)""",
                        (profile_id, name, palette[color_index], now, now, now),
                    )
                    created_profiles.append(profile_id)
                else:
                    profile_id = str(row["id"])
                    name = str(row["name"])
                successful_project_profiles.add(profile_id)

                source_scope = (profile_id, project_id)
                if project_id and source_scope not in refreshed_profile_sources:
                    previous_count = int(
                        db.execute(
                            """SELECT COUNT(*) FROM voice_profile_samples
                            WHERE profile_id = ? AND source_project_id = ?""",
                            source_scope,
                        ).fetchone()[0]
                    )
                    if previous_count:
                        db.execute(
                            """DELETE FROM voice_profile_samples
                            WHERE profile_id = ? AND source_project_id = ?""",
                            source_scope,
                        )
                        replaced_samples += previous_count
                    refreshed_profile_sources.add(source_scope)
                existing_sources = {
                    str(item["source_segment_id"])
                    for item in db.execute(
                        """SELECT source_segment_id FROM voice_profile_samples
                        WHERE profile_id = ? AND source_project_id = ?
                          AND source_segment_id IS NOT NULL AND source_segment_id != ''""",
                        (profile_id, project_id),
                    ).fetchall()
                }
                for sample in qualified:
                    source_segment_id = str(sample.get("segmentId") or "")
                    if source_segment_id and source_segment_id in existing_sources:
                        duplicate_samples += 1
                        continue
                    db.execute(
                        """INSERT INTO voice_profile_samples
                        (id, profile_id, source_project_id, source_segment_id, embedding_blob,
                         duration_ms, confidence, created_at)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                        (
                            str(uuid.uuid4()),
                            profile_id,
                            project_id,
                            source_segment_id,
                            protect_embedding(sample["_vector"]),
                            int(sample["durationMs"]),
                            float(sample.get("confidence") or 0),
                            now,
                        ),
                    )
                    if source_segment_id:
                        existing_sources.add(source_segment_id)
                    learned_samples += 1
                centroid, retained_count, retained_duration = self._rebuild_voice_profile_memory(
                    db,
                    profile_id,
                )
                db.execute(
                    """UPDATE voice_profiles SET centroid_blob = ?, sample_count = ?,
                        total_duration_ms = ?, updated_at = ?, last_matched_at = ?
                    WHERE id = ?""",
                    (
                        protect_embedding(centroid) if centroid is not None else None,
                        retained_count,
                        retained_duration,
                        now,
                        now,
                        profile_id,
                    ),
                )
                assignments.append(
                    {
                        "cluster": int(observation.get("cluster") or 1),
                        "profileId": profile_id,
                        "name": name,
                        "created": profile_id in created_profiles,
                        "matchConfidence": effective_match_confidence,
                    }
                )
            # A successful full-project pass is authoritative for the identities
            # it found. Remove evidence that this project previously attributed
            # to a different profile, then rebuild every affected centroid.
            if project_id and replace_project_evidence and rejected_observations == 0:
                stale_profiles = previous_project_profiles - successful_project_profiles
                for profile_id in stale_profiles:
                    previous_count = int(
                        db.execute(
                            """SELECT COUNT(*) FROM voice_profile_samples
                            WHERE profile_id = ? AND source_project_id = ?""",
                            (profile_id, project_id),
                        ).fetchone()[0]
                    )
                    if not previous_count:
                        continue
                    db.execute(
                        """DELETE FROM voice_profile_samples
                        WHERE profile_id = ? AND source_project_id = ?""",
                        (profile_id, project_id),
                    )
                    replaced_samples += previous_count
                    centroid, retained_count, retained_duration = (
                        self._rebuild_voice_profile_memory(db, profile_id)
                    )
                    db.execute(
                        """UPDATE voice_profiles SET centroid_blob = ?, sample_count = ?,
                            total_duration_ms = ?, updated_at = ?
                        WHERE id = ?""",
                        (
                            protect_embedding(centroid) if centroid is not None else None,
                            retained_count,
                            retained_duration,
                            now,
                            profile_id,
                        ),
                    )
        return {
            "learnedSamples": learned_samples,
            "createdProfiles": created_profiles,
            "assignments": assignments,
            "receivedObservations": len(observations),
            "receivedSamples": received_samples,
            "eligibleSamples": eligible_samples,
            "selectedSamples": selected_samples,
            "notSelectedSamples": not_selected_samples,
            "duplicateSamples": duplicate_samples,
            "replacedSamples": replaced_samples,
            "rejectedObservations": rejected_observations,
            "rejectedSamples": rejected_samples,
            "rejectionReasons": rejection_reasons,
            "minimumConfidence": confidence_threshold,
            "maximumSamplesPerObservation": VOICE_OBSERVATION_SAMPLE_LIMIT,
            "maximumSamplesPerProfile": VOICE_PROFILE_SAMPLE_LIMIT,
            **self.list_voice_profiles(),
        }

    @staticmethod
    def _select_temporally_diverse_voice_samples(
        samples: list[dict[str, Any]],
        limit: int,
    ) -> list[dict[str, Any]]:
        if len(samples) <= limit:
            return sorted(
                samples,
                key=lambda item: (int(item["_temporalPosition"]), int(item["_sequence"])),
            )
        ordered = sorted(
            samples,
            key=lambda item: (int(item["_temporalPosition"]), int(item["_sequence"])),
        )
        selected: list[dict[str, Any]] = []
        for bucket in range(limit):
            start = bucket * len(ordered) // limit
            end = (bucket + 1) * len(ordered) // limit
            candidates = ordered[start:end]
            selected.append(
                max(
                    candidates,
                    key=lambda item: (
                        float(item.get("confidence") or 0),
                        min(int(item.get("durationMs") or 0), 6_000),
                    ),
                )
            )
        return sorted(
            selected,
            key=lambda item: (int(item["_temporalPosition"]), int(item["_sequence"])),
        )

    @staticmethod
    def _robust_observation_centroid(
        samples: list[dict[str, Any]],
    ) -> tuple[np.ndarray | None, list[dict[str, Any]], int, float]:
        if not samples:
            return None, [], 0, 0.0
        matrix = np.stack([np.asarray(item["_vector"], dtype=np.float32) for item in samples])
        similarities = np.clip(matrix @ matrix.T, -1.0, 1.0)
        medoid_index = int(np.argmax(np.median(similarities, axis=1)))
        medoid_similarities = similarities[medoid_index]
        median_similarity = float(np.median(medoid_similarities))
        mad = float(np.median(np.abs(medoid_similarities - median_similarity)))
        cutoff = max(0.45, median_similarity - max(0.08, 2.5 * mad))
        keep_indices = [
            index for index, similarity in enumerate(medoid_similarities) if float(similarity) >= cutoff
        ]
        if not keep_indices:
            return None, [], len(samples), 0.0
        kept = [samples[index] for index in keep_indices]
        kept_matrix = matrix[keep_indices]
        weights = np.asarray(
            [
                max(float(item.get("confidence") or 0), 0.01)
                * min(max(float(item.get("durationMs") or 0) / 1_000.0, 0.65), 6.0)
                for item in kept
            ],
            dtype=np.float32,
        )
        centroid = np.average(kept_matrix, axis=0, weights=weights)
        centroid /= max(float(np.linalg.norm(centroid)), 1e-8)
        coherence = float(np.median(np.clip(kept_matrix @ centroid, -1.0, 1.0)))
        return centroid.astype(np.float32), kept, len(samples) - len(kept), coherence

    @staticmethod
    def _rebuild_voice_profile_memory(
        db: sqlite3.Connection,
        profile_id: str,
    ) -> tuple[np.ndarray | None, int, int]:
        rows = db.execute(
            """SELECT id, source_project_id, source_segment_id, embedding_blob,
                duration_ms, confidence, created_at
            FROM voice_profile_samples WHERE profile_id = ?
            ORDER BY confidence DESC, created_at DESC""",
            (profile_id,),
        ).fetchall()
        valid: list[dict[str, Any]] = []
        delete_ids: list[str] = []
        seen_sources: set[tuple[str, str]] = set()
        for row in rows:
            project_id = str(row["source_project_id"] or "")
            segment_id = str(row["source_segment_id"] or "")
            source_key = (project_id, segment_id)
            if project_id and segment_id and source_key in seen_sources:
                delete_ids.append(str(row["id"]))
                continue
            try:
                vector = unprotect_embedding(bytes(row["embedding_blob"]))
                norm = float(np.linalg.norm(vector))
                if vector.size != 192 or not np.isfinite(vector).all() or norm < 1e-8:
                    raise ValueError("Huella de voz inválida.")
                vector = vector / norm
            except (OSError, ValueError):
                # Keep inaccessible DPAPI evidence intact. A restored database
                # or transient account-key issue must not silently destroy it.
                continue
            if project_id and segment_id:
                seen_sources.add(source_key)
            valid.append({"row": row, "vector": vector.astype(np.float32)})

        groups: dict[str, list[dict[str, Any]]] = {}
        for item in valid:
            project_key = str(item["row"]["source_project_id"] or "__sin_proyecto__")
            groups.setdefault(project_key, []).append(item)
        for items in groups.values():
            items.sort(
                key=lambda item: (
                    float(item["row"]["confidence"]),
                    min(int(item["row"]["duration_ms"]), 6_000),
                    str(item["row"]["created_at"]),
                ),
                reverse=True,
            )
        retained: list[dict[str, Any]] = []
        group_keys = sorted(groups)
        while group_keys and len(retained) < VOICE_PROFILE_SAMPLE_LIMIT:
            next_keys: list[str] = []
            for key in group_keys:
                if len(retained) >= VOICE_PROFILE_SAMPLE_LIMIT:
                    break
                items = groups[key]
                if items:
                    retained.append(items.pop(0))
                if items:
                    next_keys.append(key)
            group_keys = next_keys
        retained_ids = {str(item["row"]["id"]) for item in retained}
        delete_ids.extend(
            str(item["row"]["id"]) for item in valid if str(item["row"]["id"]) not in retained_ids
        )
        if delete_ids:
            db.executemany(
                "DELETE FROM voice_profile_samples WHERE id = ?",
                [(sample_id,) for sample_id in dict.fromkeys(delete_ids)],
            )
        if not retained:
            return None, 0, 0

        matrix = np.stack([item["vector"] for item in retained])
        pairwise = np.clip(matrix @ matrix.T, -1.0, 1.0)
        medoid_index = int(np.argmax(np.median(pairwise, axis=1)))
        medoid_similarities = pairwise[medoid_index]
        base_weights = np.asarray(
            [
                max(float(item["row"]["confidence"]), 0.01)
                * min(max(float(item["row"]["duration_ms"]) / 1_000.0, 0.65), 6.0)
                for item in retained
            ],
            dtype=np.float32,
        )
        coherence_weights = np.square(np.clip((medoid_similarities - 0.25) / 0.75, 0.05, 1.0))
        centroid = np.average(matrix, axis=0, weights=base_weights * coherence_weights)
        centroid /= max(float(np.linalg.norm(centroid)), 1e-8)
        duration_ms = sum(int(item["row"]["duration_ms"]) for item in retained)
        return centroid.astype(np.float32), len(retained), duration_ms

    def _voice_profile_summary(self, profile_id: str) -> dict[str, Any]:
        catalog = self.list_voice_profiles()
        profile = next((item for item in catalog["profiles"] if item["id"] == profile_id), None)
        if profile is None:
            raise KeyError("El perfil de voz ya no existe.")
        return profile

    @staticmethod
    def _voice_reliability_score(
        *,
        sample_count: int,
        total_duration_ms: int,
        source_project_count: int,
        average_match_confidence: float | None,
    ) -> int:
        sample_score = min(max(sample_count, 0) / 24.0, 1.0)
        duration_score = min(max(total_duration_ms, 0) / 90_000.0, 1.0)
        project_score = min(max(source_project_count, 0) / 3.0, 1.0)
        similarity_score = (
            0.0
            if average_match_confidence is None
            else float(np.clip((average_match_confidence - 0.5) / 0.4, 0.0, 1.0))
        )
        return int(
            round(
                100
                * (
                    sample_score * 0.30
                    + duration_score * 0.25
                    + project_score * 0.20
                    + similarity_score * 0.25
                )
            )
        )

    @staticmethod
    def _voice_reliability(reliability_score: int) -> str:
        if reliability_score >= 78:
            return "alta"
        if reliability_score >= 48:
            return "buena"
        return "aprendiendo"

    @staticmethod
    def _next_voice_name(db: sqlite3.Connection) -> str:
        existing = {
            str(row["name"]).casefold() for row in db.execute("SELECT name FROM voice_profiles").fetchall()
        }
        index = 1
        while f"hablante {index}" in existing:
            index += 1
        return f"Hablante {index}"

    def save_insights(self, project_id: str, source_updated_at: str, insights: dict[str, Any]) -> None:
        insights = repair_data(sanitize_data(insights))
        with self.connect() as db:
            db.execute(
                """INSERT INTO project_insights
                (project_id, generated_at, method, source_updated_at, insights_json)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(project_id) DO UPDATE SET
                    generated_at=excluded.generated_at,
                    method=excluded.method,
                    source_updated_at=excluded.source_updated_at,
                    insights_json=excluded.insights_json""",
                (
                    project_id,
                    str(insights.get("generatedAt", "")),
                    str(insights.get("method", "local-extractive-v1")),
                    source_updated_at,
                    json.dumps(insights, ensure_ascii=False),
                ),
            )

    def create_transcript_version(self, project_id: str) -> bool:
        """Snapshot the last completed text before a destructive retranscription."""
        project = self.load_project(project_id)
        segments = project.get("segments", [])
        if not segments:
            return False
        with self.connect() as db:
            db.execute(
                """INSERT INTO transcript_versions
                (id, project_id, model, segment_count, segments_json)
                VALUES (?, ?, ?, ?, ?)""",
                (
                    str(uuid.uuid4()),
                    project_id,
                    str(project.get("model") or "desconocido"),
                    len(segments),
                    json.dumps(repair_data(segments), ensure_ascii=False),
                ),
            )
            old_rows = db.execute(
                "SELECT id FROM transcript_versions WHERE project_id = ? "
                "ORDER BY created_at DESC, rowid DESC LIMIT -1 OFFSET 5",
                (project_id,),
            ).fetchall()
            db.executemany(
                "DELETE FROM transcript_versions WHERE id = ?",
                [(row["id"],) for row in old_rows],
            )
        return True

    def load_project_for_media(self, media_path: str) -> dict[str, Any] | None:
        normalized_target = os.path.normcase(os.path.normpath(media_path))
        with self.connect() as db:
            rows = db.execute(
                """SELECT id, media_path FROM projects
                WHERE transcription_status = 'completed' OR EXISTS (
                    SELECT 1 FROM segments WHERE segments.project_id = projects.id
                  )
                ORDER BY updated_at DESC"""
            ).fetchall()
        row = next(
            (
                candidate
                for candidate in rows
                if os.path.normcase(os.path.normpath(candidate["media_path"])) == normalized_target
            ),
            None,
        )
        return self.load_project(row["id"]) if row else None

    def list_projects(self, limit: int = 12) -> list[dict[str, Any]]:
        with self.connect() as db:
            rows = db.execute(
                "SELECT id, name, media_path, media_type, updated_at, transcription_status, duration_ms "
                "FROM projects ORDER BY updated_at DESC LIMIT ?",
                (limit,),
            ).fetchall()
            return [
                {
                    "id": row["id"],
                    "name": row["name"],
                    "mediaPath": row["media_path"],
                    "mediaType": row["media_type"],
                    "updatedAt": row["updated_at"],
                    "transcriptionStatus": row["transcription_status"],
                    "durationMs": row["duration_ms"],
                }
                for row in rows
            ]

    def save_assistant_message(
        self,
        project_id: str,
        role: str,
        content: str,
        citations: list[dict[str, Any]] | None = None,
        model: str | None = None,
        message_id: str | None = None,
    ) -> dict[str, Any]:
        if role not in {"user", "assistant"}:
            raise ValueError("El rol del mensaje no es válido.")
        item = {
            "id": message_id or str(uuid.uuid4()),
            "projectId": project_id,
            "role": role,
            "content": content.strip(),
            "citations": citations or [],
            "model": model,
        }
        with self.connect() as db:
            db.execute(
                """INSERT INTO assistant_messages
                (id, project_id, role, content, citations_json, model)
                VALUES (?, ?, ?, ?, ?, ?)""",
                (
                    item["id"],
                    project_id,
                    role,
                    item["content"],
                    json.dumps(item["citations"], ensure_ascii=False),
                    model,
                ),
            )
        return item

    def list_assistant_messages(self, project_id: str, limit: int = 100) -> list[dict[str, Any]]:
        with self.connect() as db:
            rows = db.execute(
                """SELECT * FROM assistant_messages WHERE project_id = ?
                ORDER BY created_at, rowid LIMIT ?""",
                (project_id, limit),
            ).fetchall()
        return repair_data(
            [
                {
                    "id": row["id"],
                    "projectId": row["project_id"],
                    "role": row["role"],
                    "content": row["content"],
                    "citations": json.loads(row["citations_json"]),
                    "model": row["model"],
                    "createdAt": row["created_at"],
                }
                for row in rows
            ]
        )

    def search_transcripts(self, query: str, limit: int = 50) -> list[dict[str, Any]]:
        terms = list(dict.fromkeys(term for term in query.strip().split() if len(term) >= 2))[:16]
        if not terms:
            return []
        clauses = " OR ".join("LOWER(s.text) LIKE ?" for _ in terms)
        score = " + ".join("CASE WHEN LOWER(s.text) LIKE ? THEN 1 ELSE 0 END" for _ in terms)
        parameters = [f"%{term.lower()}%" for term in terms]
        with self.connect() as db:
            rows = db.execute(
                f"""SELECT s.id AS segment_id, s.project_id, s.start_ms, s.end_ms, s.text,
                    s.speaker, p.name AS project_name, p.media_path, ({score}) AS relevance
                FROM segments s JOIN projects p ON p.id = s.project_id
                WHERE {clauses}
                ORDER BY relevance DESC, p.updated_at DESC, s.start_ms LIMIT ?""",
                (*parameters, *parameters, limit),
            ).fetchall()
        return repair_data(
            [
                {
                    "segmentId": row["segment_id"],
                    "projectId": row["project_id"],
                    "projectName": row["project_name"],
                    "mediaPath": row["media_path"],
                    "startMs": row["start_ms"],
                    "endMs": row["end_ms"],
                    "speaker": row["speaker"],
                    "text": row["text"],
                    "relevance": row["relevance"],
                }
                for row in rows
            ]
        )

    def save_marker(self, project_id: str, time_ms: int, kind: str, label: str) -> dict[str, Any]:
        marker = {
            "id": str(uuid.uuid4()),
            "projectId": project_id,
            "timeMs": max(0, int(time_ms)),
            "kind": kind,
            "label": label.strip() or kind,
        }
        with self.connect() as db:
            db.execute(
                """INSERT INTO project_markers (id, project_id, time_ms, kind, label)
                VALUES (?, ?, ?, ?, ?)""",
                (marker["id"], project_id, marker["timeMs"], kind, marker["label"]),
            )
        return marker

    def list_markers(self, project_id: str) -> list[dict[str, Any]]:
        with self.connect() as db:
            rows = db.execute(
                "SELECT * FROM project_markers WHERE project_id = ? ORDER BY time_ms",
                (project_id,),
            ).fetchall()
        return [
            {
                "id": row["id"],
                "projectId": row["project_id"],
                "timeMs": row["time_ms"],
                "kind": row["kind"],
                "label": row["label"],
                "createdAt": row["created_at"],
            }
            for row in rows
        ]

    def record_evidence(self, project_id: str, event_type: str, payload: dict[str, Any]) -> None:
        with self.connect() as db:
            db.execute(
                """INSERT INTO evidence_events (id, project_id, event_type, payload_json)
                VALUES (?, ?, ?, ?)""",
                (
                    str(uuid.uuid4()),
                    project_id,
                    event_type,
                    json.dumps(sanitize_data(payload), ensure_ascii=False),
                ),
            )

    def list_evidence(self, project_id: str, limit: int = 200) -> list[dict[str, Any]]:
        with self.connect() as db:
            rows = db.execute(
                """SELECT * FROM evidence_events WHERE project_id = ?
                ORDER BY created_at DESC, rowid DESC LIMIT ?""",
                (project_id, limit),
            ).fetchall()
        return repair_data(
            [
                {
                    "id": row["id"],
                    "projectId": row["project_id"],
                    "eventType": row["event_type"],
                    "payload": json.loads(row["payload_json"]),
                    "createdAt": row["created_at"],
                }
                for row in rows
            ]
        )

    def list_versions(self, project_id: str) -> list[dict[str, Any]]:
        with self.connect() as db:
            rows = db.execute(
                """SELECT id, created_at, model, segment_count FROM transcript_versions
                WHERE project_id = ? ORDER BY created_at DESC, rowid DESC""",
                (project_id,),
            ).fetchall()
        return [
            {
                "id": row["id"],
                "projectId": project_id,
                "createdAt": row["created_at"],
                "model": row["model"],
                "segmentCount": row["segment_count"],
            }
            for row in rows
        ]

    def restore_version(self, project_id: str, version_id: str) -> dict[str, Any]:
        with self.connect() as db:
            row = db.execute(
                "SELECT segments_json FROM transcript_versions WHERE id = ? AND project_id = ?",
                (version_id, project_id),
            ).fetchone()
        if not row:
            raise KeyError("La versión solicitada ya no existe.")
        current = self.load_project(project_id)
        self.create_transcript_version(project_id)
        current["segments"] = repair_data(json.loads(row["segments_json"]))
        current["updatedAt"] = datetime.now(UTC).isoformat()
        current["transcriptionStatus"] = "completed"
        self.save_project(current)
        self.record_evidence(project_id, "version_restored", {"versionId": version_id})
        return current

    def enqueue_project(self, project: dict[str, Any]) -> dict[str, Any]:
        self.save_project(project)
        with self.connect() as db:
            position = int(db.execute("SELECT COALESCE(MAX(position), 0) + 1 FROM job_queue").fetchone()[0])
            queue_id = str(uuid.uuid4())
            db.execute(
                """INSERT INTO job_queue (id, project_id, position, state, settings_json)
                VALUES (?, ?, ?, 'queued', ?)
                ON CONFLICT(project_id) DO UPDATE SET
                    position=excluded.position, state='queued', settings_json=excluded.settings_json,
                    updated_at=CURRENT_TIMESTAMP""",
                (
                    queue_id,
                    project["id"],
                    position,
                    json.dumps(project.get("settings", {}), ensure_ascii=False),
                ),
            )
        return {"projectId": project["id"], "position": position, "state": "queued"}

    def list_queue(self) -> list[dict[str, Any]]:
        with self.connect() as db:
            rows = db.execute(
                """SELECT q.id, q.project_id, q.position, q.state, q.created_at, q.updated_at,
                    p.name, p.duration_ms, p.media_path, p.media_type,
                    j.processed_duration_ms, j.total_duration_ms, j.progress_percent,
                    j.stage, j.phase, j.message, j.device, j.active_model, j.speed_x,
                    j.eta_ms, j.error_message
                FROM job_queue q JOIN projects p ON p.id = q.project_id
                LEFT JOIN transcription_jobs j ON j.project_id = q.project_id
                ORDER BY CASE q.state WHEN 'running' THEN 0 WHEN 'queued' THEN 1 ELSE 2 END,
                    q.position, q.created_at"""
            ).fetchall()
        return repair_data(
            [
                {
                    "id": row["id"],
                    "projectId": row["project_id"],
                    "position": row["position"],
                    "state": row["state"],
                    "name": row["name"],
                    "durationMs": row["duration_ms"],
                    "mediaPath": row["media_path"],
                    "mediaType": row["media_type"],
                    "processedDurationMs": row["processed_duration_ms"] or 0,
                    "totalDurationMs": row["total_duration_ms"] or row["duration_ms"],
                    "percent": row["progress_percent"],
                    "stage": row["stage"],
                    "phase": row["phase"],
                    "message": row["message"],
                    "device": row["device"],
                    "activeModel": row["active_model"],
                    "speedX": row["speed_x"],
                    "etaMs": row["eta_ms"],
                    "errorMessage": row["error_message"],
                    "createdAt": row["created_at"],
                    "updatedAt": row["updated_at"],
                }
                for row in rows
            ]
        )

    def claim_next_queued_project(self) -> dict[str, Any] | None:
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute(
                """SELECT project_id FROM job_queue WHERE state = 'queued'
                ORDER BY position, created_at LIMIT 1"""
            ).fetchone()
            if not row:
                return None
            db.execute(
                "UPDATE job_queue SET state = 'running', updated_at = CURRENT_TIMESTAMP WHERE project_id = ?",
                (row["project_id"],),
            )
            project_id = str(row["project_id"])
        return self.load_project(project_id)

    def set_queue_state(self, project_id: str, state: str) -> None:
        with self.connect() as db:
            db.execute(
                "UPDATE job_queue SET state = ?, updated_at = CURRENT_TIMESTAMP WHERE project_id = ?",
                (state, project_id),
            )

    def remove_from_queue(self, project_id: str) -> bool:
        with self.connect() as db:
            row = db.execute("SELECT state FROM job_queue WHERE project_id = ?", (project_id,)).fetchone()
            if not row:
                return False
            if row["state"] == "running":
                raise ValueError("Cancela el trabajo activo antes de retirarlo de la cola.")
            db.execute("DELETE FROM job_queue WHERE project_id = ?", (project_id,))
        return True

    def reorder_queue(self, project_ids: list[str]) -> list[dict[str, Any]]:
        with self.connect() as db:
            for position, project_id in enumerate(project_ids, 1):
                db.execute(
                    """UPDATE job_queue SET position = ?, updated_at = CURRENT_TIMESTAMP
                    WHERE project_id = ? AND state = 'queued'""",
                    (position, project_id),
                )
        return self.list_queue()
