from __future__ import annotations

import io
import json
import sys
import threading

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
