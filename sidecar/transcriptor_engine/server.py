from __future__ import annotations

import json
import os
import sys
import threading
import time
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .assistant import answer_transcript_question, expand_search_terms
from .audio import AudioDecodeCancelled, decode_audio_with_progress
from .database import ProjectDatabase
from .deep_insights import AnalysisCancelledError, analyze_transcript_deep, get_local_ai_status
from .diagnostics import record_diagnostic
from .exporters import export_to
from .hardware import get_hardware_info
from .insights import analyze_transcript
from .live import LiveSessionManager
from .media import analyze_media
from .media_edit import export_without_segments
from .models import delete_model, list_models
from .paragraphs import group_segments
from .portable import export_package, import_package
from .privacy import preview_redactions, redact_project
from .protocol import ProtocolWriter
from .speaker_ai import download_speaker_model, neural_assign_speakers, speaker_ai_status
from .system_diagnostics import diagnose_system
from .transcriber import CancelledError, Transcriber


class EngineServer:
    def __init__(self, database: ProjectDatabase | None = None, writer: ProtocolWriter | None = None) -> None:
        self.database = database or ProjectDatabase()
        self.writer = writer or ProtocolWriter()
        self.transcriber = Transcriber()
        self.live = LiveSessionManager(self.transcriber)
        self._jobs: dict[str, threading.Event] = {}
        self._analysis_jobs: dict[str, threading.Event] = {}
        self._voice_jobs: dict[str, threading.Event] = {}
        self._model_downloads: dict[str, threading.Event] = {}
        self._jobs_lock = threading.Lock()
        self._queue_fill_lock = threading.Lock()
        self._queue_hardware: dict[str, Any] | None = None

    def serve(self) -> None:
        # Tauri writes JSONL to the sidecar as UTF-8.  A frozen Python process on
        # Windows otherwise decodes stdin with the active legacy code page, which
        # turns paths such as ``Grabación.wav`` into ``GrabaciÃ³n.wav``.
        if hasattr(sys.stdin, "reconfigure"):
            sys.stdin.reconfigure(encoding="utf-8", errors="strict")
        if hasattr(self.database, "claim_next_queued_project"):
            threading.Thread(target=self._fill_queue_slots, daemon=True).start()
        for raw_line in sys.stdin:
            try:
                message = json.loads(raw_line)
                self.handle(message)
            except json.JSONDecodeError:
                self.writer.send(
                    "engine_log", {"level": "warning", "message": "Se ignoró una solicitud JSON no válida."}
                )
            except Exception as error:
                request_id = message.get("requestId") if "message" in locals() else None
                if request_id:
                    self.writer.error(request_id, self._safe_error(error))
        # Closing the desktop app must never wait on a model or leave orphan processes.
        with self._jobs_lock:
            cancellation_tokens = [
                *self._jobs.values(),
                *self._analysis_jobs.values(),
                *self._voice_jobs.values(),
                *self._model_downloads.values(),
            ]
            for cancel in cancellation_tokens:
                cancel.set()
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            with self._jobs_lock:
                has_active_jobs = bool(self._jobs or self._analysis_jobs or self._voice_jobs)
            if not has_active_jobs:
                break
            time.sleep(0.1)

    def handle(self, message: dict[str, Any]) -> None:
        request_id = str(message.get("requestId", ""))
        action = message.get("action")
        payload = message.get("payload") or {}
        if not request_id or not action:
            raise ValueError("La solicitud no incluye requestId o action.")
        try:
            if action == "analyze_media":
                self.writer.result(request_id, analyze_media(payload["mediaPath"]))
            elif action == "diagnose_system":
                self.writer.result(
                    request_id,
                    diagnose_system(
                        str(payload.get("mediaPath") or "") or None,
                        self.transcriber._cuda_runtime_available(),
                    ),
                )
            elif action == "get_hardware_info":
                self.writer.result(
                    request_id,
                    get_hardware_info(self.transcriber._cuda_runtime_available()),
                )
            elif action == "list_models":
                self.writer.result(request_id, list_models())
            elif action == "download_model":
                self._start_model_download(request_id, str(payload["modelId"]))
            elif action == "cancel_model_download":
                self._cancel_model_download(request_id, str(payload["modelId"]))
            elif action == "get_speaker_ai_status":
                self.writer.result(request_id, speaker_ai_status())
            elif action == "install_speaker_ai":
                self._start_speaker_ai_download(request_id)
            elif action == "cancel_speaker_ai_download":
                self._cancel_model_download(request_id, "speaker-ai")
            elif action == "list_voice_profiles":
                self.writer.result(request_id, self.database.list_voice_profiles())
            elif action == "learn_project_voices":
                self._start_voice_learning(request_id, str(payload["projectId"]))
            elif action == "cancel_voice_learning":
                self._cancel_voice_learning(request_id, str(payload["projectId"]))
            elif action == "update_voice_profile":
                self.writer.result(
                    request_id,
                    self.database.update_voice_profile(
                        str(payload["profileId"]),
                        name=payload.get("name"),
                        enabled=payload.get("enabled"),
                        match_threshold=payload.get("matchThreshold"),
                    ),
                )
            elif action == "delete_voice_profile":
                self.writer.result(
                    request_id,
                    self.database.delete_voice_profile(str(payload["profileId"])),
                )
            elif action == "compare_voice_profiles":
                self.writer.result(
                    request_id,
                    self.database.compare_voice_profiles(
                        str(payload["sourceProfileId"]),
                        str(payload["targetProfileId"]),
                    ),
                )
            elif action == "merge_voice_profiles":
                if payload.get("confirmed") is not True:
                    raise ValueError("La fusión de perfiles requiere confirmación explícita.")
                result = self.database.merge_voice_profiles(
                    str(payload["sourceProfileId"]),
                    str(payload["targetProfileId"]),
                )
                self.writer.send("voice_profiles_updated", result["catalog"])
                self.writer.send("voice_profiles_merged", result)
                self.writer.result(request_id, result)
            elif action == "delete_model":
                self.writer.result(request_id, delete_model(str(payload["modelId"])))
            elif action == "get_local_ai_status":
                self.writer.result(request_id, get_local_ai_status(str(payload.get("model", "qwen3.5:9b"))))
            elif action == "save_project":
                self.database.save_project(payload["project"])
                self.writer.result(request_id, {"saved": True})
            elif action == "list_projects":
                self.writer.result(request_id, self.database.list_projects())
            elif action == "search_transcripts":
                self.writer.result(
                    request_id,
                    self.database.search_transcripts(str(payload.get("query", ""))),
                )
            elif action == "semantic_search":
                expansion = expand_search_terms(str(payload.get("query", "")))
                results = self.database.search_transcripts(" ".join(expansion["terms"]), limit=80)
                self.writer.result(request_id, {**expansion, "results": results})
            elif action == "load_project":
                self.writer.result(request_id, self.database.load_project(payload["projectId"]))
            elif action == "list_versions":
                self.writer.result(request_id, self.database.list_versions(str(payload["projectId"])))
            elif action == "restore_version":
                self.writer.result(
                    request_id,
                    self.database.restore_version(str(payload["projectId"]), str(payload["versionId"])),
                )
            elif action == "list_evidence":
                self.writer.result(request_id, self.database.list_evidence(str(payload["projectId"])))
            elif action == "list_assistant_messages":
                self.writer.result(
                    request_id, self.database.list_assistant_messages(str(payload["projectId"]))
                )
            elif action == "add_marker":
                self.writer.result(
                    request_id,
                    self.database.save_marker(
                        str(payload["projectId"]),
                        int(payload.get("timeMs", 0)),
                        str(payload.get("kind", "important")),
                        str(payload.get("label", "Importante")),
                    ),
                )
            elif action == "list_markers":
                self.writer.result(request_id, self.database.list_markers(str(payload["projectId"])))
            elif action == "delete_project":
                project_id = str(payload["projectId"])
                with self._jobs_lock:
                    if (
                        project_id in self._jobs
                        or project_id in self._analysis_jobs
                        or project_id in self._voice_jobs
                    ):
                        raise ValueError("Detén el trabajo de este proyecto antes de eliminarlo.")
                self.writer.result(request_id, self.database.delete_project(project_id))
            elif action == "load_project_for_media":
                self.writer.result(request_id, self.database.load_project_for_media(payload["mediaPath"]))
            elif action == "export_project":
                export_project = (
                    redact_project(payload["project"])
                    if bool(payload.get("redactSensitive"))
                    else payload["project"]
                )
                export_to(export_project, payload["format"], payload["outputPath"])
                self.writer.result(request_id, {"exported": True, "outputPath": payload["outputPath"]})
            elif action == "preview_redactions":
                self.writer.result(request_id, preview_redactions(payload["project"]))
            elif action == "export_package":
                project = payload["project"]
                result = export_package(
                    project,
                    str(payload["outputPath"]),
                    bool(payload.get("includeMedia")),
                    self.database.list_evidence(str(project["id"])),
                )
                self.database.record_evidence(
                    str(project["id"]),
                    "portable_exported",
                    {"mediaIncluded": bool(payload.get("includeMedia"))},
                )
                self.writer.result(request_id, result)
            elif action == "import_package":
                project = import_package(str(payload["packagePath"]))
                self.database.save_project(project)
                self.database.record_evidence(
                    str(project["id"]), "portable_imported", {"source": "portable_package"}
                )
                self.writer.result(request_id, project)
            elif action == "export_media_edit":
                project = payload["project"]
                result = export_without_segments(
                    project,
                    [str(item) for item in payload.get("excludedSegmentIds", [])],
                    str(payload["outputPath"]),
                )
                self.database.record_evidence(
                    str(project["id"]),
                    "media_edited",
                    {"removedSegments": result["removedSegments"]},
                )
                self.writer.result(request_id, result)
            elif action == "group_paragraphs":
                project = payload["project"]
                self.database.create_transcript_version(project["id"])
                project["segments"] = group_segments(
                    project.get("segments", []),
                    max_duration_ms=int(payload.get("maxSeconds", 42)) * 1000,
                    max_characters=int(payload.get("maxCharacters", 620)),
                )
                project["updatedAt"] = datetime.now(UTC).isoformat()
                self.database.save_project(project)
                self.writer.result(request_id, project)
            elif action == "analyze_transcript":
                self._start_analysis(request_id, payload)
            elif action == "ask_transcript":
                self._start_question(request_id, payload)
            elif action == "cancel_analysis":
                self._cancel_analysis(request_id, str(payload["projectId"]))
            elif action == "start_live_session":
                with self._jobs_lock:
                    if self._jobs or self._analysis_jobs or self._voice_jobs:
                        raise ValueError("Detén el trabajo actual antes de grabar en directo.")
                def emit_live_start(event_type: str, live_payload: dict[str, Any]) -> None:
                    self.writer.send(event_type, live_payload)

                live_settings = dict(payload.get("settings", {}))
                if bool(live_settings.get("voiceProfilesEnabled", False)):
                    live_settings["_voiceProfiles"] = self.database.load_voice_matcher_profiles()
                self.writer.result(request_id, self.live.start(
                    live_settings,
                    bool(payload.get("separateSpeakers", True)),
                    emit_live_start,
                ))
            elif action == "push_live_audio":
                session_id = str(payload["sessionId"])

                def emit_live(event_type: str, live_payload: dict[str, Any]) -> None:
                    output_type = "live_partial" if event_type == "live_partial" else "live_status"
                    self.writer.send(output_type, {**live_payload, "sessionId": session_id})

                self.writer.result(
                    request_id,
                    self.live.push(session_id, str(payload["pcmBase64"]), emit_live),
                )
            elif action == "stop_live_session":
                session_id = str(payload["sessionId"])
                result = self.live.stop(session_id)
                observations = result.pop("_voiceObservations", [])
                minimum_confidence = float(
                    result.pop("_voiceProfileMinConfidence", 72)
                ) / 100
                if observations:
                    learned = self.database.learn_voice_observations(
                        session_id, observations, min_confidence=minimum_confidence
                    )
                    self._apply_voice_assignments(result["segments"], observations, learned)
                    self.writer.send("voice_profiles_updated", learned)
                self.writer.result(request_id, result)
            elif action == "cancel_live_session":
                self.live.cancel(str(payload["sessionId"]))
                self.writer.result(request_id, {"cancelled": True})
            elif action == "transcribe":
                self._start_transcription(request_id, payload["project"])
            elif action == "enqueue_transcription":
                queued = self.database.enqueue_project(payload["project"])
                self.writer.result(request_id, queued)
                self._send_queue_update()
                threading.Thread(target=self._fill_queue_slots, daemon=True).start()
            elif action == "list_queue":
                self.writer.result(request_id, self.database.list_queue())
            elif action == "get_queue_status":
                self.writer.result(request_id, self._queue_status())
            elif action == "set_queue_concurrency":
                requested = int(payload.get("maxConcurrentJobs", 0))
                if requested < 0 or requested > 3:
                    raise ValueError("La concurrencia debe ser automática o estar entre 1 y 3.")
                if hasattr(self.database, "set_preference"):
                    self.database.set_preference("queue.max_concurrent_jobs", requested)
                status = self._queue_status()
                self.writer.result(request_id, status)
                self.writer.send("queue_updated", status)
                threading.Thread(target=self._fill_queue_slots, daemon=True).start()
            elif action == "remove_from_queue":
                removed = self.database.remove_from_queue(str(payload["projectId"]))
                self.writer.result(request_id, {"removed": removed})
                self._send_queue_update()
            elif action == "reorder_queue":
                items = self.database.reorder_queue([str(item) for item in payload.get("projectIds", [])])
                self.writer.result(request_id, items)
                self._send_queue_update()
            elif action == "cancel":
                self._cancel(request_id, payload["projectId"])
            else:
                self.writer.error(request_id, f"Acción desconocida: {action}", "UNKNOWN_ACTION")
        except (KeyError, ValueError, FileNotFoundError) as error:
            self.writer.error(request_id, self._safe_error(error), "INVALID_REQUEST")
        except Exception as error:
            self.writer.error(request_id, self._safe_error(error))

    def _start_voice_learning(self, request_id: str, project_id: str) -> None:
        project = self.database.load_project(project_id)
        media_path = Path(str(project.get("mediaPath") or ""))
        if not media_path.is_file():
            raise FileNotFoundError(
                "No se encuentra el audio o vídeo original. Relocalízalo antes de analizar sus voces."
            )
        if not project.get("segments"):
            raise ValueError("Este proyecto todavía no tiene una transcripción de la que aprender.")
        if not speaker_ai_status()["ready"]:
            raise ValueError(
                "La IA local CAM++ no está instalada. Instálala en Voces antes de analizar el proyecto."
            )
        with self._jobs_lock:
            if self.live.active or self._jobs or self._analysis_jobs or self._voice_jobs:
                raise ValueError("Ya hay otro trabajo en curso. Espera a que termine o cancélalo.")
            cancel = threading.Event()
            self._voice_jobs[project_id] = cancel
        self.writer.result(request_id, {"accepted": True, "projectId": project_id})
        threading.Thread(
            target=self._run_voice_learning,
            args=(project, cancel),
            daemon=True,
        ).start()

    def _run_voice_learning(
        self,
        project: dict[str, Any],
        cancel: threading.Event,
    ) -> None:
        project_id = str(project["id"])
        duration_ms = int(project.get("durationMs") or 0)
        started_at = time.monotonic()

        def send_progress(
            stage: str,
            phase: str,
            message: str,
            percent: float,
            *,
            completed_units: int = 0,
            total_units: int = 0,
            eta_ms: int | None = None,
        ) -> None:
            self.writer.send(
                "voice_learning_progress",
                {
                    "projectId": project_id,
                    "state": "running",
                    "stage": stage,
                    "phase": phase,
                    "message": message,
                    "percent": round(max(0.0, min(100.0, percent)), 2),
                    "completedUnits": completed_units,
                    "totalUnits": total_units,
                    "etaMs": eta_ms,
                    "elapsedMs": round((time.monotonic() - started_at) * 1000),
                },
            )

        try:
            send_progress(
                "decoding",
                "Preparando el audio",
                "Decodificando el archivo a mono 16 kHz para CAM++…",
                0,
            )
            decode_started = time.monotonic()

            def decode_progress(processed_ms: int, total_ms: int) -> None:
                if cancel.is_set():
                    raise AudioDecodeCancelled
                effective_total = total_ms or duration_ms
                phase_percent = (
                    processed_ms / max(effective_total, 1) * 100
                    if effective_total
                    else 0
                )
                elapsed_ms = max(1, round((time.monotonic() - decode_started) * 1000))
                speed = processed_ms / elapsed_ms
                eta_ms = (
                    round(max(0, effective_total - processed_ms) / speed)
                    if effective_total and speed > 0
                    else None
                )
                send_progress(
                    "decoding",
                    "Preparando el audio",
                    f"Audio leído: {processed_ms // 1000} s de {effective_total // 1000} s",
                    phase_percent * 0.28,
                    completed_units=processed_ms,
                    total_units=effective_total,
                    eta_ms=eta_ms,
                )

            audio = decode_audio_with_progress(
                str(project["mediaPath"]),
                duration_ms,
                cancel.is_set,
                decode_progress,
            )
            if cancel.is_set():
                raise CancelledError

            observations: list[dict[str, Any]] = []
            settings = dict(project.get("settings", {}))
            embedding_started = time.monotonic()

            def embedding_progress(event: dict[str, Any]) -> None:
                if cancel.is_set():
                    raise CancelledError
                completed = int(event.get("completedUnits") or 0)
                total = max(1, int(event.get("totalUnits") or 1))
                phase_percent = float(event.get("percent") or 0)
                elapsed_ms = max(1, round((time.monotonic() - embedding_started) * 1000))
                rate = completed / max(elapsed_ms / 1000, 0.001)
                eta_ms = round(max(0, total - completed) / rate * 1000) if rate > 0 else None
                send_progress(
                    str(event.get("stage") or "speaker_embedding"),
                    "Construyendo huellas de voz",
                    str(event.get("message") or "Comparando timbre, resonancia y prosodia…"),
                    28 + phase_percent * 0.66,
                    completed_units=completed,
                    total_units=total,
                    eta_ms=eta_ms,
                )

            _, speaker_count = neural_assign_speakers(
                list(project.get("segments", [])),
                audio,
                speaker_count=8,
                exact_speaker_count=False,
                sensitivity=int(settings.get("speakerSensitivity", 55)),
                progress=embedding_progress,
                voice_profiles=self.database.load_voice_matcher_profiles(),
                profile_observations=observations,
            )
            del audio
            if cancel.is_set():
                raise CancelledError
            send_progress(
                "learning",
                "Actualizando la memoria local",
                f"Validando {len(observations)} voces candidatas sin guardar audio…",
                96,
                completed_units=0,
                total_units=len(observations),
            )
            learned = self.database.learn_voice_observations(
                project_id,
                observations,
                min_confidence=float(settings.get("voiceProfileMinConfidence", 72)) / 100,
            )
            project["settings"] = {
                **settings,
                "voiceProfilesEnabled": True,
                "voiceProfileAutoLearn": True,
                "speakerCountMode": "auto",
            }
            project["updatedAt"] = datetime.now(UTC).isoformat()
            self.database.save_project(project)
            self.database.record_evidence(
                project_id,
                "voice_memory_updated",
                {
                    "speakerCount": speaker_count,
                    "learnedSamples": int(learned.get("learnedSamples", 0)),
                    "createdProfiles": len(learned.get("createdProfiles", [])),
                },
            )
            self.writer.send("voice_profiles_updated", learned)
            self.writer.send(
                "voice_learning_completed",
                {
                    **learned,
                    "projectId": project_id,
                    "state": "completed",
                    "stage": "completed",
                    "phase": "Memoria de voces actualizada",
                    "message": (
                        f"{learned.get('learnedSamples', 0)} fragmentos claros aprendidos "
                        f"de {speaker_count} voces detectadas."
                    ),
                    "percent": 100,
                    "elapsedMs": round((time.monotonic() - started_at) * 1000),
                },
            )
        except (AudioDecodeCancelled, CancelledError):
            self.writer.send(
                "voice_learning_cancelled",
                {
                    "projectId": project_id,
                    "state": "cancelled",
                    "message": "Análisis de voces cancelado; no se ha perdido ninguna transcripción.",
                },
            )
        except Exception as error:
            self.writer.send(
                "voice_learning_failed",
                {
                    "projectId": project_id,
                    "state": "failed",
                    "message": self._safe_error(error),
                },
            )
        finally:
            with self._jobs_lock:
                self._voice_jobs.pop(project_id, None)
            threading.Thread(target=self._fill_queue_slots, daemon=True).start()

    def _cancel_voice_learning(self, request_id: str, project_id: str) -> None:
        with self._jobs_lock:
            cancel = self._voice_jobs.get(project_id)
        if cancel is None:
            self.writer.result(request_id, {"cancelled": False})
            return
        cancel.set()
        self.writer.result(request_id, {"cancelled": True})

    def _start_transcription(
        self,
        request_id: str,
        project: dict[str, Any],
        *,
        from_queue: bool = False,
    ) -> None:
        project_id = project["id"]
        capacity = self._effective_queue_concurrency()
        with self._jobs_lock:
            if self.live.active:
                raise ValueError("Detén la grabación en directo antes de iniciar otra transcripción.")
            if project_id in self._jobs:
                raise ValueError("Este proyecto ya se está transcribiendo.")
            if len(self._jobs) >= capacity:
                raise ValueError(
                    "Todos los motores están ocupados. Añade el archivo a la cola "
                    "y comenzará automáticamente."
                )
            if self._analysis_jobs or self._voice_jobs:
                raise ValueError("Ya hay un análisis en curso. Espera a que termine o cancélalo.")
            cancel = threading.Event()
            self._jobs[project_id] = cancel
            active_count = len(self._jobs)
        if from_queue and capacity > 1:
            project = {
                **project,
                "settings": {
                    **project.get("settings", {}),
                    "queueCpuThreads": max(
                        1,
                        (os.cpu_count() or 4) // max(1, min(capacity, active_count)),
                    ),
                },
            }
        try:
            try:
                saved = self.database.load_project(project_id)
                preserved_segments = saved.get("segments", [])
                self.database.create_transcript_version(project_id)
            except KeyError:
                preserved_segments = project.get("segments", [])
            self.database.save_project(
                {**project, "segments": preserved_segments, "transcriptionStatus": "transcribing"}
            )
            self.database.update_job(project_id, "waiting_model", 0, int(project.get("durationMs", 0)))
            record_diagnostic(
                "job_accepted",
                project_id=project_id,
                duration_ms=int(project.get("durationMs", 0)),
                model=str(project.get("settings", {}).get("model", project.get("model", "small"))),
                requested_device=str(project.get("settings", {}).get("device", "auto")),
            )
            self.writer.result(request_id, {"accepted": True})
            threading.Thread(target=self._run_transcription, args=(project, cancel), daemon=True).start()
        except Exception:
            with self._jobs_lock:
                self._jobs.pop(project_id, None)
            raise

    def _start_analysis(self, request_id: str, payload: dict[str, Any]) -> None:
        project = payload["project"]
        project_id = str(project["id"])
        with self._jobs_lock:
            if self.live.active or self._jobs:
                raise ValueError("Detén la grabación o transcripción actual antes de analizar el contenido.")
            if self._analysis_jobs or self._voice_jobs:
                raise ValueError("Ya hay un análisis en curso. Espera a que termine o cancélalo.")
            cancel = threading.Event()
            self._analysis_jobs[project_id] = cancel
        self.writer.result(request_id, {"accepted": True, "projectId": project_id})
        record_diagnostic("analysis_started", project_id=project_id, depth=str(payload.get("depth", "deep")))
        threading.Thread(
            target=self._run_analysis,
            args=(
                project,
                str(payload.get("mode", "general")),
                str(payload.get("depth", "deep")),
                str(payload.get("model", "qwen3.5:9b")),
                cancel,
            ),
            daemon=True,
        ).start()

    def _start_question(self, request_id: str, payload: dict[str, Any]) -> None:
        project = payload["project"]
        project_id = str(project["id"])
        with self._jobs_lock:
            if self.live.active or self._jobs or self._analysis_jobs or self._voice_jobs:
                raise ValueError("Espera a que termine el trabajo actual antes de preguntar.")
            cancel = threading.Event()
            self._analysis_jobs[project_id] = cancel
        self.writer.result(request_id, {"accepted": True, "projectId": project_id})
        self.database.save_assistant_message(project_id, "user", str(payload.get("question", "")))
        self.writer.send("assistant_started", {"projectId": project_id})
        threading.Thread(
            target=self._run_question,
            args=(project, str(payload.get("question", "")), str(payload.get("model", "qwen3.5:9b")), cancel),
            daemon=True,
        ).start()

    def _run_question(
        self, project: dict[str, Any], question: str, model: str, cancel: threading.Event
    ) -> None:
        project_id = str(project["id"])
        try:
            answer = answer_transcript_question(project, question, model, cancel)
            if cancel.is_set():
                raise AnalysisCancelledError("Pregunta cancelada.")
            self.database.save_assistant_message(
                project_id,
                "assistant",
                str(answer["answer"]),
                list(answer.get("citations", [])),
                model,
                str(answer["id"]),
            )
            self.writer.send("assistant_completed", {"projectId": project_id, "answer": answer})
        except AnalysisCancelledError:
            self.writer.send("assistant_cancelled", {"projectId": project_id})
        except Exception as error:
            self.writer.send(
                "assistant_failed",
                {"projectId": project_id, "message": self._safe_error(error)},
            )
        finally:
            with self._jobs_lock:
                self._analysis_jobs.pop(project_id, None)

    def _start_model_download(self, request_id: str, model_id: str) -> None:
        allowed = {str(item["id"]) for item in list_models()["models"]}
        if model_id not in allowed:
            raise ValueError("El modelo solicitado no pertenece al catálogo permitido.")
        with self._jobs_lock:
            if model_id in self._model_downloads:
                raise ValueError("Ese modelo ya se está descargando.")
            cancel = threading.Event()
            self._model_downloads[model_id] = cancel
        self.writer.result(request_id, {"accepted": True, "modelId": model_id})
        threading.Thread(
            target=self._run_model_download,
            args=(model_id, cancel),
            name=f"model-manager-{model_id}",
            daemon=True,
        ).start()

    def _run_model_download(self, model_id: str, cancel: threading.Event) -> None:
        try:
            def emit(_event_type: str, payload: dict[str, Any]) -> None:
                if not cancel.is_set():
                    self.writer.send("model_manager_progress", {**payload, "modelId": model_id})

            self.transcriber._download_model_with_progress(model_id, 0, emit, "manager")
            if cancel.is_set():
                self.writer.send("model_manager_cancelled", {"modelId": model_id})
            else:
                self.writer.send("model_manager_completed", {"modelId": model_id, **list_models()})
        except Exception as error:
            self.writer.send(
                "model_manager_failed",
                {"modelId": model_id, "message": self._safe_error(error)},
            )
        finally:
            with self._jobs_lock:
                self._model_downloads.pop(model_id, None)

    def _start_speaker_ai_download(self, request_id: str) -> None:
        model_id = "speaker-ai"
        with self._jobs_lock:
            if model_id in self._model_downloads:
                raise ValueError("La IA de hablantes ya se está descargando.")
            cancel = threading.Event()
            self._model_downloads[model_id] = cancel
        self.writer.result(request_id, {"accepted": True, "modelId": model_id})
        threading.Thread(
            target=self._run_speaker_ai_download,
            args=(cancel,),
            name="speaker-ai-manager",
            daemon=True,
        ).start()

    def _run_speaker_ai_download(self, cancel: threading.Event) -> None:
        model_id = "speaker-ai"
        try:
            def emit(payload: dict[str, Any]) -> None:
                if not cancel.is_set():
                    self.writer.send("speaker_model_progress", payload)

            result = download_speaker_model(emit, cancel.is_set)
            if cancel.is_set():
                self.writer.send("speaker_model_cancelled", {"modelId": model_id})
            else:
                self.writer.send("speaker_model_completed", result)
        except Exception as error:
            event = "speaker_model_cancelled" if cancel.is_set() else "speaker_model_failed"
            self.writer.send(event, {"modelId": model_id, "message": self._safe_error(error)})
        finally:
            with self._jobs_lock:
                self._model_downloads.pop(model_id, None)

    def _cancel_model_download(self, request_id: str, model_id: str) -> None:
        with self._jobs_lock:
            cancel = self._model_downloads.get(model_id)
        if cancel:
            cancel.set()
        self.writer.result(request_id, {"cancelled": bool(cancel), "modelId": model_id})

    def _run_analysis(
        self,
        project: dict[str, Any],
        mode: str,
        depth: str,
        model: str,
        cancel: threading.Event,
    ) -> None:
        project_id = str(project["id"])
        started_at = time.monotonic()
        try:
            if depth == "quick":
                if cancel.is_set():
                    raise AnalysisCancelledError("Análisis cancelado.")
                insights = analyze_transcript(project, mode)
            else:
                insights = analyze_transcript_deep(
                    project,
                    mode,
                    model,
                    lambda event: self.writer.send("analysis_progress", event),
                    cancel,
                )
            if cancel.is_set():
                raise AnalysisCancelledError("Análisis cancelado.")
            self.database.save_insights(project_id, str(project.get("updatedAt", "")), insights)
            self.writer.send("analysis_completed", {"projectId": project_id, "insights": insights})
            record_diagnostic(
                "analysis_completed",
                project_id=project_id,
                depth=depth,
                elapsed_ms=round((time.monotonic() - started_at) * 1000),
            )
        except AnalysisCancelledError:
            self.writer.send(
                "analysis_cancelled",
                {
                    "projectId": project_id,
                    "message": "Análisis cancelado; el resultado anterior se conserva.",
                },
            )
            record_diagnostic("analysis_cancelled", project_id=project_id)
        except Exception as error:
            message = self._safe_error(error)
            self.writer.send(
                "analysis_failed",
                {"projectId": project_id, "message": message},
            )
            record_diagnostic("analysis_failed", project_id=project_id, error_type=error.__class__.__name__)
        finally:
            with self._jobs_lock:
                self._analysis_jobs.pop(project_id, None)

    def _cancel_analysis(self, request_id: str, project_id: str) -> None:
        with self._jobs_lock:
            cancel = self._analysis_jobs.get(project_id)
        if not cancel:
            self.writer.result(request_id, {"cancelled": False})
            return
        cancel.set()
        self.writer.result(request_id, {"cancelled": True})

    def _run_transcription(self, project: dict[str, Any], cancel: threading.Event) -> None:
        project_id = project["id"]
        started_at = time.monotonic()
        final_state = "failed"
        try:

            def emit(event_type: str, payload: dict[str, Any]) -> None:
                scoped_payload = {**payload, "projectId": project_id}
                self.writer.send(event_type, scoped_payload)
                if event_type in {"job_started", "transcription_progress"}:
                    self.database.update_job(
                        project_id,
                        str(scoped_payload.get("state", "transcribing")),
                        int(scoped_payload.get("processedDurationMs", 0)),
                        int(scoped_payload.get("totalDurationMs", project.get("durationMs", 0))),
                        progress_percent=(
                            float(scoped_payload["percent"])
                            if scoped_payload.get("percent") is not None
                            else None
                        ),
                        stage=str(scoped_payload.get("stage") or "") or None,
                        phase=str(scoped_payload.get("phase") or "") or None,
                        message=str(scoped_payload.get("message") or "") or None,
                        device=str(scoped_payload.get("device") or "") or None,
                        active_model=str(scoped_payload.get("activeModel") or "") or None,
                        speed_x=(
                            float(scoped_payload["speedX"])
                            if scoped_payload.get("speedX") is not None
                            else None
                        ),
                        eta_ms=(
                            int(scoped_payload["etaMs"])
                            if scoped_payload.get("etaMs") is not None
                            else None
                        ),
                    )
                    self.writer.send("queue_item_progress", scoped_payload)
                if event_type in {"model_download_progress", "job_started"}:
                    record_diagnostic(
                        "engine_phase",
                        project_id=project_id,
                        phase=event_type,
                        state=str(scoped_payload.get("state", "")),
                        device=str(scoped_payload.get("device", "")),
                    )

            settings = project.get("settings", {})
            voice_profiles = (
                self.database.load_voice_matcher_profiles()
                if bool(settings.get("voiceProfilesEnabled", False))
                else []
            )
            outcome = self.transcriber.transcribe(project, cancel, emit, voice_profiles)
            emit(
                "transcription_progress",
                {
                    "state": "transcribing",
                    "stage": "saving",
                    "phase": "Guardando el resultado…",
                    "processedDurationMs": outcome.duration_ms,
                    "totalDurationMs": outcome.duration_ms,
                    "percent": 99.5,
                    "phasePercent": None,
                    "message": "Consolidando texto, voces y copia de recuperación local…",
                    "segmentsProduced": len(outcome.segments),
                    "activeModel": outcome.model,
                    "speedX": None,
                    "phaseRate": None,
                    "etaMs": None,
                },
            )
            if outcome.voice_observations:
                learned = self.database.learn_voice_observations(
                    project_id,
                    outcome.voice_observations,
                    min_confidence=float(settings.get("voiceProfileMinConfidence", 72)) / 100,
                )
                self._apply_voice_assignments(
                    outcome.segments, outcome.voice_observations, learned
                )
                self.writer.send("voice_profiles_updated", learned)
                self.writer.send(
                    "partial_segments",
                    {
                        "projectId": project_id,
                        "segments": outcome.segments,
                        "replaceExisting": True,
                    },
                )
            project.update(
                {
                    "segments": outcome.segments,
                    "detectedLanguage": outcome.language,
                    "durationMs": outcome.duration_ms,
                    "model": outcome.model,
                    "transcriptionStatus": "completed",
                    "updatedAt": datetime.now(UTC).isoformat(),
                }
            )
            self.database.save_project(project)
            self.database.record_evidence(
                project_id,
                "transcription_completed",
                {"model": outcome.model, "language": outcome.language, "segmentCount": len(outcome.segments)},
            )
            self.database.update_job(
                project_id,
                "completed",
                outcome.duration_ms,
                outcome.duration_ms,
                progress_percent=100,
                stage="completed",
                phase="Transcripción completada",
                message="Proyecto guardado correctamente",
                device=outcome.device,
                active_model=outcome.model,
                eta_ms=0,
            )
            final_state = "completed"
            self.writer.send(
                "job_completed",
                {
                    "projectId": project_id,
                    "language": outcome.language,
                    "durationMs": outcome.duration_ms,
                    "segmentCount": len(outcome.segments),
                    "device": outcome.device,
                    "model": outcome.model,
                    "qualityMode": outcome.quality_mode,
                    "reviewedSegments": outcome.reviewed_segments,
                },
            )
            record_diagnostic(
                "job_completed",
                project_id=project_id,
                duration_ms=outcome.duration_ms,
                segment_count=len(outcome.segments),
                device=outcome.device,
                elapsed_ms=round((time.monotonic() - started_at) * 1000),
            )
        except CancelledError:
            final_state = "cancelled"
            self.database.update_project_status(project_id, "cancelled", datetime.now(UTC).isoformat())
            self.database.update_job(project_id, "cancelled", 0, int(project.get("durationMs", 0)))
            self.writer.send(
                "job_cancelled",
                {
                    "projectId": project_id,
                    "message": "Transcripción cancelada. La versión anterior se ha conservado.",
                },
            )
            record_diagnostic(
                "job_cancelled",
                project_id=project_id,
                elapsed_ms=round((time.monotonic() - started_at) * 1000),
            )
        except Exception as error:
            self.database.update_project_status(project_id, "failed", datetime.now(UTC).isoformat())
            self.database.update_job(
                project_id,
                "failed",
                0,
                int(project.get("durationMs", 0)),
                "TRANSCRIPTION_FAILED",
                self._safe_error(error),
            )
            self.writer.send(
                "job_failed",
                {"projectId": project_id, "code": "TRANSCRIPTION_FAILED", "message": self._safe_error(error)},
            )
            record_diagnostic(
                "job_failed",
                project_id=project_id,
                error_type=error.__class__.__name__,
                elapsed_ms=round((time.monotonic() - started_at) * 1000),
            )
        finally:
            with self._jobs_lock:
                self._jobs.pop(project_id, None)
            self.database.set_queue_state(project_id, final_state)
            self._send_queue_update()
            threading.Thread(target=self._fill_queue_slots, daemon=True).start()

    @staticmethod
    def _apply_voice_assignments(
        segments: list[dict[str, Any]],
        observations: list[dict[str, Any]],
        learned: dict[str, Any],
    ) -> None:
        old_names = {
            int(item.get("cluster") or 1): str(item.get("suggestedName") or "")
            for item in observations
        }
        for assignment in learned.get("assignments", []):
            cluster = int(assignment.get("cluster") or 1)
            old_name = old_names.get(cluster) or f"Hablante {cluster}"
            for segment in segments:
                if segment.get("speaker") == old_name:
                    segment["speaker"] = str(assignment["name"])
                    segment["speakerProfileId"] = str(assignment["profileId"])

    def _recommended_queue_concurrency(self) -> int:
        if self._queue_hardware is None:
            try:
                self._queue_hardware = get_hardware_info(
                    self.transcriber._cuda_runtime_available()
                )
            except Exception:
                self._queue_hardware = {}
        hardware = self._queue_hardware
        gpu = hardware.get("gpu") or {}
        memory = hardware.get("memory") or {}
        logical = int(
            (hardware.get("cpu") or {}).get("logicalCores")
            or os.cpu_count()
            or 4
        )
        total_memory = int(memory.get("totalMiB") or 0)
        total_vram = int(gpu.get("totalVramMiB") or 0)
        if (
            bool(hardware.get("cudaAvailable"))
            and total_vram >= 14_000
            and total_memory >= 32_000
        ):
            return 3
        if (
            bool(hardware.get("cudaAvailable"))
            and total_vram >= 6_000
            and total_memory >= 16_000
        ):
            return 2
        if (
            not hardware.get("cudaAvailable")
            and logical >= 16
            and total_memory >= 24_000
        ):
            return 2
        return 1

    def _configured_queue_concurrency(self) -> int:
        if not hasattr(self.database, "get_preference"):
            return 0
        try:
            return max(
                0,
                min(
                    3,
                    int(
                        self.database.get_preference(
                            "queue.max_concurrent_jobs", 0
                        )
                        or 0
                    ),
                ),
            )
        except (TypeError, ValueError):
            return 0

    def _effective_queue_concurrency(self) -> int:
        configured = self._configured_queue_concurrency()
        return configured or self._recommended_queue_concurrency()

    def _queue_status(self) -> dict[str, Any]:
        items = self.database.list_queue()
        configured = self._configured_queue_concurrency()
        effective = configured or self._recommended_queue_concurrency()
        running = sum(1 for item in items if item.get("state") == "running")
        waiting = sum(1 for item in items if item.get("state") == "queued")
        completed = sum(1 for item in items if item.get("state") == "completed")
        failed = sum(
            1 for item in items if item.get("state") in {"failed", "cancelled"}
        )
        return {
            "items": items,
            "maxConcurrentJobs": configured,
            "effectiveConcurrency": effective,
            "recommendedConcurrency": self._recommended_queue_concurrency(),
            "runningCount": running,
            "waitingCount": waiting,
            "completedCount": completed,
            "failedCount": failed,
            "availableSlots": max(0, effective - running),
            "mode": "auto" if configured == 0 else "manual",
        }

    def _send_queue_update(self) -> None:
        if hasattr(self.database, "list_queue"):
            self.writer.send("queue_updated", self._queue_status())

    def _fill_queue_slots(self) -> None:
        if not hasattr(self.database, "claim_next_queued_project"):
            return
        if not self._queue_fill_lock.acquire(blocking=False):
            return
        try:
            while True:
                with self._jobs_lock:
                    if (
                        self._analysis_jobs
                        or self._voice_jobs
                        or self.live.active
                        or len(self._jobs) >= self._effective_queue_concurrency()
                    ):
                        return
                project = self.database.claim_next_queued_project()
                if not project:
                    return
                try:
                    self._start_transcription(
                        f"queue-{uuid.uuid4()}",
                        project,
                        from_queue=True,
                    )
                    self._send_queue_update()
                except Exception as error:
                    project_id = str(project["id"])
                    with self._jobs_lock:
                        capacity_full = (
                            len(self._jobs) >= self._effective_queue_concurrency()
                        )
                    if capacity_full:
                        self.database.set_queue_state(project_id, "queued")
                        self._send_queue_update()
                        return
                    self.database.set_queue_state(project_id, "failed")
                    self.writer.send(
                        "queue_item_failed",
                        {"projectId": project_id, "message": self._safe_error(error)},
                    )
                    self._send_queue_update()
        finally:
            self._queue_fill_lock.release()

    def _cancel(self, request_id: str, project_id: str) -> None:
        with self._jobs_lock:
            cancel = self._jobs.get(project_id)
        if not cancel:
            self.writer.result(request_id, {"cancelled": False, "message": "No hay ningún trabajo activo."})
            return
        cancel.set()
        self.writer.result(request_id, {"cancelled": True})

    @staticmethod
    def _safe_error(error: Exception) -> str:
        # No expone argumentos completos que puedan contener rutas o texto transcrito.
        if isinstance(error, KeyError):
            return str(error).strip("'")
        text = str(error).splitlines()[0]
        return text[:500] or error.__class__.__name__
