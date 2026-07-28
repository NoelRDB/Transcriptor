from __future__ import annotations

import json
import re
from datetime import UTC, datetime
from typing import Any

from .deep_insights import DEFAULT_MODEL, _request_streamed_chat, ensure_local_ai
from .unicode_text import repair_data


def answer_transcript_question(
    project: dict[str, Any], question: str, model: str = DEFAULT_MODEL, cancel: Any | None = None
) -> dict[str, Any]:
    question = re.sub(r"\s+", " ", question).strip()
    if len(question) < 3:
        raise ValueError("Escribe una pregunta un poco más concreta.")
    segments = sorted(
        [item for item in project.get("segments", []) if str(item.get("text", "")).strip()],
        key=lambda item: (int(item.get("startMs", 0)), int(item.get("order", 0))),
    )
    if not segments:
        raise ValueError("La transcripción está vacía.")
    status = ensure_local_ai(model)
    if not status.get("available") or not status.get("installed"):
        raise ValueError("Inicia Ollama y descarga Qwen 3.5 para preguntar a la transcripción.")

    selected = _select_context(segments, question)
    source_lines = "\n".join(
        f"[{item['id']}|{_clock(int(item.get('startMs', 0)))}] {str(item.get('text', '')).strip()}"
        for item in selected
    )
    system = (
        "Respondes únicamente con evidencia de una transcripción privada. No inventes datos ni identidades. "
        "Si la respuesta no aparece, dilo claramente. Devuelve JSON válido con answer y citations. "
        "Cada cita debe usar exactamente un segmentId proporcionado y un excerpt breve."
    )
    prompt = f"""Pregunta: {question}

TRANSCRIPCIÓN SELECCIONADA:
{source_lines}

Devuelve:
{{"answer":"respuesta clara en español","citations":[
  {{"segmentId":"id exacto","excerpt":"evidencia breve"}}
]}}
"""
    payload = {
        "model": model,
        "stream": True,
        "think": False,
        "format": "json",
        "keep_alive": "20m",
        "messages": [{"role": "system", "content": system}, {"role": "user", "content": prompt}],
        "options": {"temperature": 0.08, "num_ctx": 8_192, "num_predict": 1_400, "seed": 11},
    }
    content, done_reason = _request_streamed_chat(payload, cancel)
    if done_reason == "length":
        raise ValueError("La respuesta local quedó incompleta. Formula una pregunta más concreta.")
    content = re.sub(r"^```(?:json)?\s*|\s*```$", "", content.strip(), flags=re.IGNORECASE)
    try:
        raw = repair_data(json.loads(content))
    except json.JSONDecodeError as error:
        raise ValueError("La IA local no devolvió una respuesta válida. Inténtalo de nuevo.") from error

    by_id = {str(item["id"]): item for item in selected}
    citations = []
    for citation in raw.get("citations", [])[:8]:
        source = by_id.get(str(citation.get("segmentId", "")))
        if not source:
            continue
        citations.append(
            {
                "segmentId": str(source["id"]),
                "startMs": int(source.get("startMs", 0)),
                "endMs": int(source.get("endMs", source.get("startMs", 0))),
                "excerpt": str(citation.get("excerpt") or source.get("text", ""))[:240].strip(),
            }
        )
    return {
        "id": f"answer-{datetime.now(UTC).timestamp():.0f}",
        "projectId": str(project.get("id", "")),
        "question": question,
        "answer": str(raw.get("answer", "")).strip() or "No encontré una respuesta verificable.",
        "citations": citations,
        "model": model,
        "generatedAt": datetime.now(UTC).isoformat(),
    }


def expand_search_terms(query: str, model: str = DEFAULT_MODEL) -> dict[str, Any]:
    """Expand a concept into grounded lexical candidates using the installed local model."""
    query = re.sub(r"\s+", " ", query).strip()
    original_terms = re.findall(r"[\wáéíóúüñ]{2,}", query.lower())
    status = ensure_local_ai(model, wait_seconds=5)
    if not status.get("available") or not status.get("installed"):
        return {"terms": original_terms, "method": "lexical"}
    payload = {
        "model": model,
        "stream": True,
        "think": False,
        "format": "json",
        "keep_alive": "20m",
        "messages": [
            {
                "role": "system",
                "content": (
                    "Expandes búsquedas documentales en español. Devuelve sólo JSON. "
                    "No respondas a la consulta: genera términos y sinónimos breves "
                    "que podrían aparecer literalmente."
                ),
            },
            {
                "role": "user",
                "content": (
                    f"Consulta: {query}\nDevuelve {{\"terms\":[\"término\"]}} con 6 a 12 palabras o frases, "
                    "incluyendo las palabras importantes de la consulta."
                ),
            },
        ],
        "options": {"temperature": 0.1, "num_ctx": 2_048, "num_predict": 180, "seed": 17},
    }
    try:
        content, _ = _request_streamed_chat(payload, None)
        content = re.sub(r"^```(?:json)?\s*|\s*```$", "", content.strip(), flags=re.IGNORECASE)
        values = json.loads(content).get("terms", [])
        terms = list(
            dict.fromkeys(
                [*original_terms, *(str(value).strip().lower() for value in values if str(value).strip())]
            )
        )[:16]
        return {"terms": terms, "method": f"local-{model}"}
    except (ValueError, json.JSONDecodeError, OSError):
        return {"terms": original_terms, "method": "lexical"}


def _select_context(
    segments: list[dict[str, Any]], question: str, limit: int = 32_000
) -> list[dict[str, Any]]:
    if sum(len(str(item.get("text", ""))) for item in segments) <= limit:
        return segments
    terms = set(re.findall(r"[\wáéíóúüñ]{3,}", question.lower()))
    scored = []
    for index, segment in enumerate(segments):
        text_terms = set(re.findall(r"[\wáéíóúüñ]{3,}", str(segment.get("text", "")).lower()))
        scored.append((len(terms & text_terms), index))
    chosen_indexes = {0, len(segments) - 1}
    for score, index in sorted(scored, reverse=True)[:24]:
        if score <= 0 and len(chosen_indexes) >= 10:
            break
        chosen_indexes.update(range(max(0, index - 1), min(len(segments), index + 2)))
    selected = [segments[index] for index in sorted(chosen_indexes)]
    while sum(len(str(item.get("text", ""))) for item in selected) > limit and len(selected) > 4:
        selected.pop(len(selected) // 2)
    return selected


def _clock(milliseconds: int) -> str:
    seconds = max(0, milliseconds // 1000)
    return f"{seconds // 60:02d}:{seconds % 60:02d}"
