from __future__ import annotations

import io
import json
import sys
import threading
from types import SimpleNamespace

import pytest

import transcriptor_engine.server as server_module
from transcriptor_engine.server import EngineServer


class StubDatabase:
    def load_project(self, _project_id):
        raise KeyError

    def save_project(self, _project):
        return None

    def update_job(self, *_args):
        return None


class StubWriter:
    def result(self, *_args):
        return None


class QueueDatabase(StubDatabase):
    def __init__(self):
        self.projects = [
            {"id": "first", "durationMs": 1000, "segments": []},
            {"id": "second", "durationMs": 1000, "segments": []},
            {"id": "third", "durationMs": 1000, "segments": []},
        ]

    def claim_next_queued_project(self):
        return self.projects.pop(0) if self.projects else None


class AnalysisDatabase(StubDatabase):
    def __init__(self):
        self.insights = None

    def list_projects(self):
        return [{"id": "still-responsive"}]

    def save_insights(self, project_id, source_updated_at, insights):
        self.insights = (project_id, source_updated_at, insights)


class EncodingDatabase(StubDatabase):
    def __init__(self):
        self.saved_project = None

    def save_project(self, project):
        self.saved_project = project


class CaptureWriter:
    def __init__(self):
        self.messages = []
        self.completed = threading.Event()

    def result(self, request_id, payload):
        self.messages.append(("result", request_id, payload))

    def error(self, request_id, message, code="ENGINE_ERROR"):
        self.messages.append(("error", request_id, {"message": message, "code": code}))

    def send(self, message_type, payload, request_id=None):
        self.messages.append((message_type, request_id, payload))
        if message_type == "analysis_completed":
            self.completed.set()


def test_automatic_queue_limits_work_to_safe_capacity(monkeypatch):
    server = EngineServer(database=StubDatabase(), writer=StubWriter())
    monkeypatch.setattr(server, "_effective_queue_concurrency", lambda: 2)
    server._jobs["active-project"] = threading.Event()
    server._jobs["second-project"] = threading.Event()

    with pytest.raises(ValueError, match="Todos los motores están ocupados"):
        server._start_transcription(
            "request-3",
            {
                "id": "third-project",
                "durationMs": 1000,
                "segments": [],
            },
        )


def test_model_manager_rejects_download_before_starting_when_disk_is_full(monkeypatch):
    writer = CaptureWriter()
    server = EngineServer(database=StubDatabase(), writer=writer)
    monkeypatch.setattr(
        server_module,
        "list_models",
        lambda: {
            "freeBytes": 512 * 1024**2,
            "models": [
                {
                    "id": "turbo",
                    "name": "Turbo",
                    "installed": False,
                    "canInstall": False,
                    "requiredFreeBytes": 2 * 1024**3,
                }
            ],
        },
    )

    with pytest.raises(OSError, match="No hay espacio suficiente"):
        server._start_model_download("download-1", "turbo")

    assert server._model_downloads == {}
    assert writer.messages == []


def test_cuda_runtime_status_is_available_through_the_typed_protocol(monkeypatch):
    status = {
        "id": "cuda-runtime",
        "supported": True,
        "ready": False,
        "downloadBytes": 1_285_431_644,
    }
    monkeypatch.setattr(server_module, "get_cuda_runtime_status", lambda: status)
    writer = CaptureWriter()
    server = EngineServer(database=StubDatabase(), writer=writer)

    server.handle(
        {
            "requestId": "cuda-status",
            "action": "get_cuda_runtime_status",
            "payload": {},
        }
    )

    assert status["usable"] is False
    assert ("result", "cuda-status", status) in writer.messages
    assert server._transcriber is None


def test_recording_protocol_starts_without_loading_the_transcription_model(monkeypatch):
    writer = CaptureWriter()
    server = EngineServer(database=StubDatabase(), writer=writer)
    start = {
        "sessionId": "recording-1",
        "sampleRate": 16_000,
        "createdAt": "2026-08-02T12:00:00+00:00",
    }
    monkeypatch.setattr(server.recorder, "start", lambda language: start | {"languageForTest": language})

    server.handle(
        {
            "requestId": "recording-start",
            "action": "start_recording_session",
            "payload": {"language": "es"},
        }
    )

    assert ("result", "recording-start", start | {"languageForTest": "es"}) in writer.messages
    assert server._transcriber is None
    assert server._live is None


def test_listing_projects_does_not_load_whisper_or_live_transcription():
    writer = CaptureWriter()
    database = AnalysisDatabase()
    server = EngineServer(database=database, writer=writer)

    server.handle({"requestId": "projects", "action": "list_projects", "payload": {}})

    assert ("result", "projects", [{"id": "still-responsive"}]) in writer.messages
    assert server._transcriber is None
    assert server._live is None


def test_cuda_runtime_manager_streams_progress_and_reports_activation(monkeypatch):
    writer = CaptureWriter()
    server = EngineServer(database=StubDatabase(), writer=writer)

    def install(emit, _cancelled):
        emit(
            {
                "phase": "downloading",
                "percent": 45,
                "downloadedBytes": 500,
                "totalBytes": 1_000,
            }
        )
        return {"id": "cuda-runtime", "ready": True, "source": "managed"}

    monkeypatch.setattr(server_module, "install_cuda_runtime", install)
    monkeypatch.setattr(
        server_module,
        "preload_cuda_backend",
        lambda: {
            "activated": True,
            "restartRequired": False,
            "activationState": "active",
        },
    )
    server._run_cuda_runtime_download(threading.Event())

    assert any(
        message_type == "cuda_runtime_progress"
        and payload["percent"] == 45
        and payload["runtimeId"] == "cuda-runtime"
        for message_type, _request_id, payload in writer.messages
    )
    assert server._transcriber is None
    assert any(
        message_type == "cuda_runtime_completed"
        and payload["ready"] is True
        and payload["usable"] is True
        for message_type, _request_id, payload in writer.messages
    )


def test_queue_fills_two_transcription_slots_in_parallel(monkeypatch):
    database = QueueDatabase()
    server = EngineServer(database=database, writer=StubWriter())
    monkeypatch.setattr(server, "_effective_queue_concurrency", lambda: 2)
    monkeypatch.setattr(server, "_send_queue_update", lambda: None)

    def start(_request_id, project, *, from_queue=False):
        assert from_queue
        server._jobs[project["id"]] = threading.Event()

    monkeypatch.setattr(server, "_start_transcription", start)

    server._fill_queue_slots()

    assert set(server._jobs) == {"first", "second"}
    assert [project["id"] for project in database.projects] == ["third"]


def test_protocol_reads_utf8_paths_when_windows_stdin_uses_a_legacy_code_page(monkeypatch):
    project = {"id": "unicode-project", "mediaPath": r"C:\audio\Grabación con ñ.wav"}
    request = {
        "requestId": "save-unicode",
        "action": "save_project",
        "payload": {"project": project},
    }
    raw_input = (json.dumps(request, ensure_ascii=False) + "\n").encode("utf-8")
    legacy_stdin = io.TextIOWrapper(io.BytesIO(raw_input), encoding="cp1252")
    monkeypatch.setattr(sys, "stdin", legacy_stdin)
    database = EncodingDatabase()
    writer = CaptureWriter()

    EngineServer(database=database, writer=writer).serve()

    assert database.saved_project == project
    assert ("result", "save-unicode", {"saved": True}) in writer.messages


def test_analysis_runs_in_background_and_keeps_protocol_responsive(monkeypatch):
    release = threading.Event()

    def fake_analysis(project, mode, model, progress, cancel):
        progress({"projectId": project["id"], "percent": 0})
        assert release.wait(2)
        return {"projectId": project["id"], "method": "test", "mode": mode}

    monkeypatch.setattr(server_module, "analyze_transcript_deep", fake_analysis)
    database = AnalysisDatabase()
    writer = CaptureWriter()
    server = EngineServer(database=database, writer=writer)
    project = {"id": "analysis-project", "updatedAt": "now", "segments": [{"text": "Hola"}]}

    server.handle(
        {
            "requestId": "analysis-request",
            "action": "analyze_transcript",
            "payload": {"project": project, "depth": "deep", "mode": "general"},
        }
    )
    server.handle({"requestId": "list-request", "action": "list_projects", "payload": {}})

    assert (
        "result",
        "analysis-request",
        {"accepted": True, "projectId": "analysis-project"},
    ) in writer.messages
    assert ("result", "list-request", [{"id": "still-responsive"}]) in writer.messages
    release.set()
    assert writer.completed.wait(2)
    assert database.insights is not None


def test_voice_learning_transfers_identity_without_touching_corrected_text():
    original = [
        {
            "id": "paragraph-1",
            "startMs": 0,
            "endMs": 4_000,
            "text": "Texto corregido manualmente, con espacios.",
            "words": [{"id": "w1", "text": "Texto"}, {"id": "w2", "text": "viejo"}],
            "reviewState": "corrected",
            "order": 0,
        }
    ]
    assigned = [
        {
            "id": "rebuilt-unit",
            "startMs": 0,
            "endMs": 4_000,
            "text": "Textoviejo",
            "speaker": "Isabel",
            "speakerProfileId": "voice-isabel",
            "speakerConfidence": 0.93,
            "speakerMatchConfidence": 0.89,
            "speakerClusterIndex": 1,
        }
    ]

    merged = EngineServer._merge_voice_metadata(original, assigned)

    assert merged[0]["id"] == "paragraph-1"
    assert merged[0]["text"] == "Texto corregido manualmente, con espacios."
    assert merged[0]["words"] == original[0]["words"]
    assert merged[0]["reviewState"] == "corrected"
    assert merged[0]["speaker"] == "Isabel"
    assert merged[0]["speakerProfileId"] == "voice-isabel"


def test_live_recording_is_returned_when_voice_memory_update_fails():
    class FailingVoiceDatabase(StubDatabase):
        def learn_voice_observations(self, *_args, **_kwargs):
            raise RuntimeError("memoria no disponible")

    writer = CaptureWriter()
    server = EngineServer(database=FailingVoiceDatabase(), writer=writer)
    server.live = SimpleNamespace(
        stop=lambda _session_id: {
            "sessionId": "live-1",
            "mediaPath": "C:/recordings/live.wav",
            "segments": [{"id": "s1", "text": "GrabaciÃ³n conservada"}],
            "_voiceObservations": [{"cluster": 1, "samples": [{"durationMs": 2_000}]}],
            "_voiceProfileMinConfidence": 72,
        }
    )

    server.handle(
        {
            "requestId": "stop-live",
            "action": "stop_live_session",
            "payload": {"sessionId": "live-1"},
        }
    )

    result = next(
        payload
        for message_type, request_id, payload in writer.messages
        if message_type == "result" and request_id == "stop-live"
    )
    assert result["mediaPath"] == "C:/recordings/live.wav"
    assert result["segments"][0]["text"] == "GrabaciÃ³n conservada"
    assert "voiceLearningWarning" in result
    assert not any(message[0] == "error" for message in writer.messages)


def test_voice_learning_receives_the_latest_project_snapshot(monkeypatch):
    writer = CaptureWriter()
    server = EngineServer(database=StubDatabase(), writer=writer)
    captured = []
    monkeypatch.setattr(
        server,
        "_start_voice_learning",
        lambda request_id, project_id, snapshot=None: captured.append(
            (request_id, project_id, snapshot)
        ),
    )
    snapshot = {
        "id": "project-latest",
        "segments": [
            {
                "id": "segment-1",
                "text": "CorrecciÃ³n que aÃºn estaba sucia",
                "reviewState": "corrected",
            }
        ],
    }

    server.handle(
        {
            "requestId": "learn-latest",
            "action": "learn_project_voices",
            "payload": {
                "projectId": "project-latest",
                "project": snapshot,
            },
        }
    )

    assert captured == [("learn-latest", "project-latest", snapshot)]


def test_transcription_emits_voice_catalog_after_persisting_new_segments(monkeypatch):
    class CatalogDatabase(StubDatabase):
        def __init__(self):
            self.saved_project = None
            self.calls = []

        def load_voice_matcher_profiles(self):
            return []

        def learn_voice_observations(self, *_args, **_kwargs):
            self.calls.append("learn")
            return {
                "profiles": [{"id": "voice-isabel", "recognizedDurationMs": 0}],
                "assignments": [{
                    "cluster": 1,
                    "profileId": "voice-isabel",
                    "name": "Isabel",
                }],
            }

        def save_project(self, project):
            self.calls.append("save")
            self.saved_project = project

        def list_voice_profiles(self):
            self.calls.append("catalog")
            assert self.saved_project is not None
            recognized_ms = sum(
                int(segment["endMs"]) - int(segment["startMs"])
                for segment in self.saved_project["segments"]
                if segment.get("speakerProfileId") == "voice-isabel"
            )
            return {
                "profiles": [{
                    "id": "voice-isabel",
                    "name": "Isabel",
                    "recognizedDurationMs": recognized_ms,
                }],
                "encryption": "DPAPI",
                "storesRawAudio": False,
            }

        def record_evidence(self, *_args, **_kwargs):
            return None

        def set_queue_state(self, *_args, **_kwargs):
            return None

        def update_job(self, *_args, **_kwargs):
            return None

        def update_project_status(self, *_args, **_kwargs):
            return None

    database = CatalogDatabase()
    writer = CaptureWriter()
    server = EngineServer(database=database, writer=writer)
    server.transcriber = SimpleNamespace(
        transcribe=lambda *_args, **_kwargs: SimpleNamespace(
            duration_ms=2_000,
            segments=[{
                "id": "segment-1",
                "startMs": 0,
                "endMs": 2_000,
                "text": "Hola",
                "speaker": "Hablante 1",
                "order": 0,
                "words": [],
            }],
            voice_observations=[{
                "cluster": 1,
                "suggestedName": "Hablante 1",
                "samples": [],
            }],
            language="es",
            model="turbo",
            device="cpu",
            quality_mode="professional",
            reviewed_segments=0,
        )
    )
    monkeypatch.setattr(server, "_send_queue_update", lambda: None)
    monkeypatch.setattr(server, "_fill_queue_slots", lambda: None)
    monkeypatch.setattr(server_module, "record_diagnostic", lambda *_args, **_kwargs: None)
    server._jobs["project-voice"] = threading.Event()

    server._run_transcription(
        {
            "id": "project-voice",
            "durationMs": 2_000,
            "segments": [],
            "settings": {"voiceProfilesEnabled": True},
        },
        threading.Event(),
    )

    catalog_events = [
        payload
        for message_type, _request_id, payload in writer.messages
        if message_type == "voice_profiles_updated"
    ]
    assert database.calls.index("save") < database.calls.index("catalog")
    assert len(catalog_events) == 1
    assert catalog_events[0]["profiles"][0]["recognizedDurationMs"] == 2_000


def test_complete_diarization_reconciles_voice_memory_when_no_samples_are_found(
    monkeypatch,
):
    class EmptyEvidenceDatabase(StubDatabase):
        def __init__(self):
            self.learning_calls = []

        def load_voice_matcher_profiles(self):
            return []

        def learn_voice_observations(self, project_id, observations, **kwargs):
            self.learning_calls.append((project_id, observations, kwargs))
            return {"profiles": [], "assignments": []}

        def list_voice_profiles(self):
            return {"profiles": [], "encryption": "DPAPI", "storesRawAudio": False}

        def record_evidence(self, *_args, **_kwargs):
            return None

        def set_queue_state(self, *_args, **_kwargs):
            return None

        def update_job(self, *_args, **_kwargs):
            return None

        def update_project_status(self, *_args, **_kwargs):
            return None

    database = EmptyEvidenceDatabase()
    writer = CaptureWriter()
    server = EngineServer(database=database, writer=writer)
    server.transcriber = SimpleNamespace(
        transcribe=lambda *_args, **_kwargs: SimpleNamespace(
            duration_ms=2_000,
            segments=[],
            voice_observations=[],
            language="es",
            model="turbo",
            device="cpu",
            quality_mode="professional",
            reviewed_segments=0,
        )
    )
    monkeypatch.setattr(server, "_send_queue_update", lambda: None)
    monkeypatch.setattr(server, "_fill_queue_slots", lambda: None)
    monkeypatch.setattr(server_module, "record_diagnostic", lambda *_args, **_kwargs: None)
    server._jobs["project-without-new-voices"] = threading.Event()

    server._run_transcription(
        {
            "id": "project-without-new-voices",
            "durationMs": 2_000,
            "segments": [],
            "settings": {
                "voiceProfilesEnabled": True,
                "voiceProfileAutoLearn": True,
                "diarizationMode": "adaptive",
            },
        },
        threading.Event(),
    )

    assert database.learning_calls == [
        (
            "project-without-new-voices",
            [],
            {
                "min_confidence": 0.72,
                "replace_project_evidence": True,
            },
        )
    ]
    assert any(message[0] == "voice_profiles_updated" for message in writer.messages)
