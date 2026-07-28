import json

import pytest

from transcriptor_engine import assistant


def test_answer_has_only_grounded_citations(monkeypatch):
    project = {
        "id": "project-1",
        "segments": [
            {"id": "s1", "startMs": 1_000, "endMs": 4_000, "text": "Marta prepara el informe."},
            {"id": "s2", "startMs": 8_000, "endMs": 12_000, "text": "La fecha límite es el viernes."},
        ],
    }
    monkeypatch.setattr(
        assistant,
        "ensure_local_ai",
        lambda _model: {"available": True, "installed": True},
    )
    response = {
        "answer": "Marta prepara el informe para el viernes.",
        "citations": [
            {"segmentId": "s1", "excerpt": "Marta prepara el informe."},
            {"segmentId": "invented", "excerpt": "No existe."},
        ],
    }
    monkeypatch.setattr(
        assistant,
        "_request_streamed_chat",
        lambda _payload, _cancel: (json.dumps(response, ensure_ascii=False), "stop"),
    )

    result = assistant.answer_transcript_question(project, "¿Quién prepara el informe?")

    assert result["answer"].startswith("Marta")
    assert result["citations"] == [
        {"segmentId": "s1", "startMs": 1_000, "endMs": 4_000, "excerpt": "Marta prepara el informe."}
    ]


def test_answer_rejects_missing_local_ai(monkeypatch):
    monkeypatch.setattr(
        assistant,
        "ensure_local_ai",
        lambda _model: {"available": False, "installed": False},
    )
    with pytest.raises(ValueError, match="Ollama"):
        assistant.answer_transcript_question(
            {"id": "p", "segments": [{"id": "s", "startMs": 0, "text": "Contenido"}]},
            "¿Qué contiene?",
        )
