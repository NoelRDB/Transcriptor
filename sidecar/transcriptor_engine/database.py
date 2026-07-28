from __future__ import annotations

import json
import os
import sqlite3
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

SCHEMA_VERSION = 7


class ProjectDatabase:
    def __init__(self, path: Path | None = None) -> None:
        self.path = path or app_data_dir() / "transcriptor.sqlite3"
        self.path.parent.mkdir(parents=True, exist_ok=True)
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
            job_columns = {
                str(row["name"])
                for row in db.execute("PRAGMA table_info(transcription_jobs)").fetchall()
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
                    db.execute(
                        f"ALTER TABLE transcription_jobs ADD COLUMN {column} {definition}"
                    )
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
            row = db.execute(
                "SELECT value_json FROM app_preferences WHERE key = ?", (key,)
            ).fetchone()
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
                db.execute(
                    """INSERT INTO segments
                    (id, project_id, start_ms, end_ms, text, speaker, confidence,
                     speaker_confidence, speaker_profile_id, speaker_match_confidence, segment_order)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
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
            segments = []
            for segment in segment_rows:
                words = db.execute(
                    "SELECT * FROM words WHERE segment_id = ? ORDER BY start_ms", (segment["id"],)
                ).fetchall()
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
            return repair_data({
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
            })

    def delete_project(self, project_id: str) -> dict[str, Any]:
        """Delete application data for a project without touching its source media."""
        with self.connect() as db:
            row = db.execute(
                "SELECT name, media_path FROM projects WHERE id = ?", (project_id,)
            ).fetchone()
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
                """SELECT id, name, color, sample_count, total_duration_ms, match_threshold,
                    enabled, created_at, updated_at, last_matched_at,
                    centroid_blob IS NOT NULL AS ready,
                    (SELECT COUNT(DISTINCT source_project_id)
                     FROM voice_profile_samples
                     WHERE profile_id = voice_profiles.id
                       AND source_project_id IS NOT NULL) AS source_project_count
                FROM voice_profiles ORDER BY enabled DESC, updated_at DESC, name COLLATE NOCASE"""
            ).fetchall()
        profiles = [
            {
                "id": row["id"],
                "name": row["name"],
                "color": row["color"],
                "sampleCount": row["sample_count"],
                "totalDurationMs": row["total_duration_ms"],
                "sourceProjectCount": row["source_project_count"],
                "matchThreshold": row["match_threshold"],
                "enabled": bool(row["enabled"]),
                "ready": bool(row["ready"]),
                "createdAt": row["created_at"],
                "updatedAt": row["updated_at"],
                "lastMatchedAt": row["last_matched_at"],
                "reliability": self._voice_reliability(int(row["sample_count"])),
            }
            for row in rows
        ]
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
            row = db.execute(
                "SELECT name FROM voice_profiles WHERE id = ?", (profile_id,)
            ).fetchone()
            if not row:
                raise KeyError("El perfil de voz ya no existe.")
            db.execute(
                """UPDATE segments SET speaker_profile_id = NULL, speaker_match_confidence = NULL
                WHERE speaker_profile_id = ?""",
                (profile_id,),
            )
            db.execute("DELETE FROM voice_profiles WHERE id = ?", (profile_id,))
        return {"deleted": True, "profileId": profile_id, "name": row["name"]}

    def learn_voice_observations(
        self,
        project_id: str,
        observations: list[dict[str, Any]],
        min_confidence: float = 0.72,
    ) -> dict[str, Any]:
        learned_samples = 0
        created_profiles: list[str] = []
        assignments: list[dict[str, Any]] = []
        received_samples = 0
        rejected_samples = 0
        rejected_observations = 0
        rejection_reasons = {
            "invalidEmbedding": 0,
            "lowConfidence": 0,
            "durationOutsideRange": 0,
            "insufficientClearAudio": 0,
            "profilePaused": 0,
        }
        now = datetime.now(UTC).isoformat()
        palette = ("#c9ff48", "#7dd3fc", "#f0abfc", "#fdba74", "#86efac", "#fda4af")
        confidence_threshold = max(0.6, min(0.92, float(min_confidence)))
        with self.connect() as db:
            for observation in observations:
                qualified: list[dict[str, Any]] = []
                for sample in observation.get("samples", []):
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
                    if confidence < confidence_threshold:
                        rejected_samples += 1
                        rejection_reasons["lowConfidence"] += 1
                        continue
                    if not 650 <= duration_ms <= 8_000:
                        rejected_samples += 1
                        rejection_reasons["durationOutsideRange"] += 1
                        continue
                    qualified.append({**sample, "_vector": vector})
                qualified.sort(
                    key=lambda item: (float(item.get("confidence") or 0), int(item["durationMs"])),
                    reverse=True,
                )
                qualified = qualified[:6]
                if not qualified or sum(int(item["durationMs"]) for item in qualified) < 1_300:
                    rejected_observations += 1
                    rejection_reasons["insufficientClearAudio"] += 1
                    continue

                matched_id = str(observation.get("matchedProfileId") or "")
                row = (
                    db.execute(
                        """SELECT id, name, centroid_blob, sample_count, enabled
                        FROM voice_profiles WHERE id = ?""",
                        (matched_id,),
                    ).fetchone()
                    if matched_id
                    else None
                )
                if row is not None and not bool(row["enabled"]):
                    rejected_observations += 1
                    rejection_reasons["profilePaused"] += 1
                    continue
                if row is None:
                    profile_id = str(uuid.uuid4())
                    suggested = str(observation.get("suggestedName") or "").strip()
                    if not suggested or suggested.startswith("Hablante "):
                        suggested = self._next_voice_name(db)
                    name = str(sanitize_data(suggested))[:40]
                    color_index = int(
                        db.execute("SELECT COUNT(*) FROM voice_profiles").fetchone()[0]
                    ) % len(palette)
                    db.execute(
                        """INSERT INTO voice_profiles
                        (id, name, color, centroid_blob, sample_count, total_duration_ms,
                         match_threshold, enabled, created_at, updated_at, last_matched_at)
                        VALUES (?, ?, ?, NULL, 0, 0, 0.64, 1, ?, ?, ?)""",
                        (profile_id, name, palette[color_index], now, now, now),
                    )
                    old_centroid = None
                    old_count = 0
                    created_profiles.append(profile_id)
                else:
                    profile_id = str(row["id"])
                    name = str(row["name"])
                    old_count = int(row["sample_count"])
                    try:
                        old_centroid = (
                            unprotect_embedding(bytes(row["centroid_blob"]))
                            if row["centroid_blob"] is not None
                            else None
                        )
                    except (OSError, ValueError):
                        old_centroid = None

                sample_vectors = [item["_vector"] for item in qualified]
                new_centroid = np.stack(sample_vectors).mean(axis=0)
                new_centroid /= max(float(np.linalg.norm(new_centroid)), 1e-8)
                if old_centroid is not None:
                    old_weight = min(max(old_count, 1), 24)
                    new_weight = min(len(sample_vectors), 6)
                    new_centroid = old_centroid * old_weight + new_centroid * new_weight
                    new_centroid /= max(float(np.linalg.norm(new_centroid)), 1e-8)

                for sample in qualified:
                    db.execute(
                        """INSERT INTO voice_profile_samples
                        (id, profile_id, source_project_id, source_segment_id, embedding_blob,
                         duration_ms, confidence, created_at)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                        (
                            str(uuid.uuid4()),
                            profile_id,
                            project_id,
                            str(sample.get("segmentId") or ""),
                            protect_embedding(sample["_vector"]),
                            int(sample["durationMs"]),
                            float(sample.get("confidence") or 0),
                            now,
                        ),
                    )
                    learned_samples += 1
                db.execute(
                    """DELETE FROM voice_profile_samples WHERE id IN (
                        SELECT id FROM voice_profile_samples WHERE profile_id = ?
                        ORDER BY confidence DESC, created_at DESC LIMIT -1 OFFSET 80
                    )""",
                    (profile_id,),
                )
                stats = db.execute(
                    """SELECT COUNT(*) AS count, COALESCE(SUM(duration_ms), 0) AS duration
                    FROM voice_profile_samples WHERE profile_id = ?""",
                    (profile_id,),
                ).fetchone()
                db.execute(
                    """UPDATE voice_profiles SET centroid_blob = ?, sample_count = ?,
                        total_duration_ms = ?, updated_at = ?, last_matched_at = ?
                    WHERE id = ?""",
                    (
                        protect_embedding(new_centroid),
                        int(stats["count"]),
                        int(stats["duration"]),
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
                    }
                )
        return {
            "learnedSamples": learned_samples,
            "createdProfiles": created_profiles,
            "assignments": assignments,
            "receivedObservations": len(observations),
            "receivedSamples": received_samples,
            "rejectedObservations": rejected_observations,
            "rejectedSamples": rejected_samples,
            "rejectionReasons": rejection_reasons,
            "minimumConfidence": confidence_threshold,
            **self.list_voice_profiles(),
        }

    def _voice_profile_summary(self, profile_id: str) -> dict[str, Any]:
        catalog = self.list_voice_profiles()
        profile = next((item for item in catalog["profiles"] if item["id"] == profile_id), None)
        if profile is None:
            raise KeyError("El perfil de voz ya no existe.")
        return profile

    @staticmethod
    def _voice_reliability(sample_count: int) -> str:
        if sample_count >= 18:
            return "alta"
        if sample_count >= 6:
            return "buena"
        return "aprendiendo"

    @staticmethod
    def _next_voice_name(db: sqlite3.Connection) -> str:
        existing = {
            str(row["name"]).casefold()
            for row in db.execute("SELECT name FROM voice_profiles").fetchall()
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
            position = int(
                db.execute("SELECT COALESCE(MAX(position), 0) + 1 FROM job_queue").fetchone()[0]
            )
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
