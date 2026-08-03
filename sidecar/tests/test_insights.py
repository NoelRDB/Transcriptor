from transcriptor_engine import deep_insights
from transcriptor_engine.insights import analyze_transcript


def test_analysis_has_traceable_points_and_concept_map():
    project = {
        "id": "p1",
        "durationMs": 120_000,
        "segments": [
            {
                "id": "s1",
                "startMs": 0,
                "endMs": 20_000,
                "text": "Tenemos que mejorar la comunicación del proyecto.",
            },
            {
                "id": "s2",
                "startMs": 22_000,
                "endMs": 40_000,
                "text": "¿Quién revisará el calendario y las tareas?",
            },
            {
                "id": "s3",
                "startMs": 50_000,
                "endMs": 80_000,
                "text": "Ana revisará el calendario y Luis documentará las tareas.",
            },
        ],
    }
    result = analyze_transcript(project, "problems")
    assert result["summary"]
    assert result["keyPoints"]
    assert all("startMs" in point and "segmentId" in point for point in result["keyPoints"])
    assert result["concepts"]
    assert result["statistics"]["wordCount"] > 0


def test_analysis_rejects_an_empty_transcript():
    try:
        analyze_transcript({"id": "empty", "segments": []})
    except ValueError as error:
        assert "vacía" in str(error)
    else:
        raise AssertionError("Expected an empty transcript error")


def test_deep_analysis_has_real_progress_and_grounded_timestamps(monkeypatch):
    project = {
        "id": "deep-project",
        "durationMs": 90_000,
        "segments": [
            {"id": "s1", "startMs": 1_000, "endMs": 20_000, "text": "Acordamos revisar el plan."},
            {"id": "s2", "startMs": 30_000, "endMs": 50_000, "text": "Marta preparará el informe."},
            {"id": "s3", "startMs": 60_000, "endMs": 80_000, "text": "Queda pendiente fijar la fecha."},
        ],
    }
    response = {
        "summary": "El equipo acuerda revisar el plan y deja una fecha pendiente.",
        "findings": [
            {"kind": "agreement", "title": "Revisión acordada", "text": "Revisarán el plan.",
             "evidence": "Acordamos revisar el plan", "startMs": 1_000, "confidence": "explicit"},
            {"kind": "question", "title": "Fecha pendiente", "text": "Aún debe fijarse la fecha.",
             "evidence": "Queda pendiente fijar la fecha", "startMs": 59_000, "confidence": "explicit"},
        ],
        "keyPoints": [
            {"title": "Fecha pendiente", "text": "Aún debe fijarse la fecha.", "startMs": 59_000},
            {"title": "Informe asignado", "text": "Marta preparará el informe.", "startMs": 31_000},
        ],
        "chapters": [
            {"title": "Acuerdos", "description": "Revisión del plan.", "startMs": 900},
            {"title": "Pendientes", "description": "Informe y fecha.", "startMs": 59_000},
        ],
        "concepts": [
            {"label": "Plan de trabajo", "weight": 9},
            {"label": "Informe", "weight": 7},
        ],
        "conceptEdges": [{"source": "Plan de trabajo", "target": "Informe", "weight": 5}],
    }
    monkeypatch.setattr(
        deep_insights,
        "ensure_local_ai",
        lambda _model: {"available": True, "installed": True},
    )
    monkeypatch.setattr(deep_insights, "_chat_json", lambda *_args, **_kwargs: response)
    progress = []

    result = deep_insights.analyze_transcript_deep(project, "couple", progress=progress.append)

    assert result["method"].startswith("local-ollama-qwen3.5:9b")
    assert [point["startMs"] for point in result["keyPoints"]] == [30_000, 60_000]
    assert all(point["segmentId"] in {"s1", "s2", "s3"} for point in result["keyPoints"])
    assert result["conceptEdges"] == [{"source": "concept-1", "target": "concept-2", "weight": 5}]
    assert result["mode"] == "couple"
    assert result["signals"] == {
        "questions": 1, "agreements": 1, "affectionMarkers": 0, "tensionMarkers": 0,
    }
    assert progress[0]["percent"] == 0
    assert progress[-1]["percent"] == 100


def test_general_prompt_covers_every_analysis_angle(monkeypatch):
    captured = {}
    monkeypatch.setattr(
        deep_insights,
        "_chat_json",
        lambda _model, _system, prompt, **_kwargs: captured.setdefault("prompt", prompt) or {},
    )
    deep_insights._analyze_once("[0-1000] texto", "general", "test")
    for term in ("emociones", "afecto", "acuerdos", "tensiones", "problemas", "riesgos", "contradicciones"):
        assert term in captured["prompt"]


def test_deep_analysis_returns_a_structured_fallback_when_qwen_fails(monkeypatch):
    project = {
        "id": "fallback", "durationMs": 30_000,
        "segments": [
            {
                "id": "s1", "startMs": 0, "endMs": 30_000,
                "text": "Tenemos un problema con la fecha.",
            }
        ],
    }
    monkeypatch.setattr(
        deep_insights,
        "ensure_local_ai",
        lambda _model: {"available": True, "installed": True},
    )
    monkeypatch.setattr(
        deep_insights,
        "_chat_json",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(ValueError("JSON incompleto")),
    )
    result = deep_insights.analyze_transcript_deep(project, "problems")
    assert result["method"] == "local-structured-fallback-v2"
    assert result["summary"]
    assert result["findings"]
    assert "respaldo" in result["notice"]
