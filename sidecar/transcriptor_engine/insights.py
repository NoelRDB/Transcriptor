from __future__ import annotations

import math
import re
import unicodedata
import uuid
from collections import Counter, defaultdict
from datetime import UTC, datetime
from typing import Any

from .unicode_text import repair_data

_WORDS = re.compile(r"[\wáéíóúüñÁÉÍÓÚÜÑ]{3,}", re.UNICODE)
_STOPWORDS = {
    "para", "pero", "porque", "como", "cuando", "donde", "quien", "esto", "esta", "este", "estas",
    "estos", "desde", "hasta", "sobre", "entre", "tambien", "también", "aunque", "entonces", "ahora",
    "aqui", "aquí", "alli", "allí", "muy", "más", "mas", "menos", "todo", "toda", "todos", "todas",
    "algo", "nada", "cada", "otro", "otra", "otros", "otras", "mismo", "misma", "hacer", "hace", "hecho",
    "tener", "tiene", "tienen", "ser", "estar", "está", "están", "fue", "son", "era", "hay", "que",
    "del", "las", "los", "una", "uno", "unos", "unas", "con", "sin", "por", "sus", "nos", "les",
    "dice", "dijo", "voy", "vamos", "bueno", "pues", "vale", "creo", "puede", "pueden", "quiero",
}
_AGREEMENT = {"acuerdo", "acepto", "sí", "claro", "perfecto", "vale", "correcto"}
_TENSION = {"problema", "enfado", "enfadado", "discusión", "mentira", "culpa", "nunca", "siempre", "odio"}
_AFFECTION = {"amor", "quiero", "cariño", "juntos", "abrazo", "beso", "confianza", "apoyo"}


def _fold(value: str) -> str:
    return "".join(
        character
        for character in unicodedata.normalize("NFKD", value.casefold())
        if not unicodedata.combining(character)
    )


def _tokens(value: str) -> list[str]:
    return [token for token in (_fold(item) for item in _WORDS.findall(value)) if token not in _STOPWORDS]


def _shorten(value: str, limit: int = 260) -> str:
    value = re.sub(r"\s+", " ", value).strip()
    if len(value) <= limit:
        return value
    cut = value.rfind(" ", 0, limit - 1)
    return value[: max(40, cut)] + "…"


def _title(tokens: list[str], fallback: str) -> str:
    common = [word.capitalize() for word, _ in Counter(tokens).most_common(3)]
    return " · ".join(common) if common else fallback


def analyze_transcript(project: dict[str, Any], mode: str = "general") -> dict[str, Any]:
    """Private, deterministic semantic overview with timestamp provenance.

    This baseline deliberately remains extractive: it cannot invent details and
    every point can take the user back to the supporting audio. A local LLM can
    later rewrite the same evidence into more natural prose.
    """
    project = repair_data(project)
    segments = [item for item in project.get("segments", []) if str(item.get("text", "")).strip()]
    if not segments:
        raise ValueError("La transcripción está vacía; no hay contenido que analizar.")

    token_sets = [set(_tokens(str(segment["text"]))) for segment in segments]
    document_frequency = Counter(token for tokens in token_sets for token in tokens)
    total_documents = max(1, len(segments))
    global_frequency = Counter(token for segment in segments for token in _tokens(str(segment["text"])))

    ranked: list[tuple[float, int]] = []
    for index, segment in enumerate(segments):
        tokens = _tokens(str(segment["text"]))
        if not tokens:
            ranked.append((0.0, index))
            continue
        score = sum(
            (1.0 + math.log1p(global_frequency[token]))
            * math.log((total_documents + 1) / (document_frequency[token] + 0.5))
            for token in set(tokens)
        ) / math.sqrt(len(tokens))
        if "?" in str(segment["text"]):
            score *= 1.08
        ranked.append((score, index))

    selected: list[int] = []
    for _score, index in sorted(ranked, reverse=True):
        candidate = token_sets[index]
        redundant = any(
            len(candidate & token_sets[chosen]) / max(1, len(candidate | token_sets[chosen])) > 0.62
            for chosen in selected
        )
        if not redundant:
            selected.append(index)
        if len(selected) == min(8, len(segments)):
            break
    selected_by_time = sorted(selected[:5])

    key_points = []
    for index in selected:
        segment = segments[index]
        tokens = _tokens(str(segment["text"]))
        key_points.append(
            {
                "id": str(uuid.uuid4()),
                "title": _title(tokens, f"Punto en {round(int(segment['startMs']) / 60_000)} min"),
                "text": _shorten(str(segment["text"])),
                "startMs": int(segment["startMs"]),
                "endMs": int(segment["endMs"]),
                "segmentId": str(segment["id"]),
            }
        )

    duration_ms = max(int(project.get("durationMs", 0)), int(segments[-1]["endMs"]))
    chapter_size = max(180_000, min(600_000, math.ceil(max(1, duration_ms) / 8)))
    chapter_buckets: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for segment in segments:
        chapter_buckets[int(segment["startMs"]) // chapter_size].append(segment)
    chapters = []
    for bucket, items in sorted(chapter_buckets.items()):
        tokens = [token for item in items for token in _tokens(str(item["text"]))]
        chapters.append(
            {
                "id": str(uuid.uuid4()),
                "title": _title(tokens, f"Parte {bucket + 1}"),
                "startMs": int(items[0]["startMs"]),
                "endMs": int(items[-1]["endMs"]),
                "description": _shorten(" ".join(str(item["text"]) for item in items[:2]), 190),
            }
        )

    concepts = [
        {"id": token, "label": token.capitalize(), "weight": count}
        for token, count in global_frequency.most_common(12)
    ]
    concept_ids = {item["id"] for item in concepts}
    edge_counts: Counter[tuple[str, str]] = Counter()
    for tokens in token_sets:
        present = sorted(tokens & concept_ids)
        for left_index, left in enumerate(present):
            for right in present[left_index + 1 :]:
                edge_counts[(left, right)] += 1
    concept_edges = [
        {"source": left, "target": right, "weight": weight}
        for (left, right), weight in edge_counts.most_common(18)
    ]

    full_text = " ".join(str(segment["text"]) for segment in segments)
    folded_tokens = _tokens(full_text)
    token_counter = Counter(folded_tokens)
    signals = {
        "questions": full_text.count("?"),
        "agreements": sum(token_counter[_fold(word)] for word in _AGREEMENT),
        "affectionMarkers": sum(token_counter[_fold(word)] for word in _AFFECTION),
        "tensionMarkers": sum(token_counter[_fold(word)] for word in _TENSION),
    }
    summary_parts = []
    for index in selected_by_time:
        sentence = _shorten(str(segments[index]["text"]), 220).strip()
        if sentence and sentence[-1] not in ".!?…":
            sentence += "."
        summary_parts.append(sentence)
    summary = "\n\n".join(summary_parts)
    word_count = len(re.findall(r"\S+", full_text))
    return {
        "projectId": str(project["id"]),
        "generatedAt": datetime.now(UTC).isoformat(),
        "method": "local-extractive-v1",
        "mode": mode
        if mode in {"general", "interview", "friends", "couple", "podcast", "diary", "legal", "problems"}
        else "general",
        "summary": summary,
        "keyPoints": key_points,
        "chapters": chapters,
        "concepts": concepts,
        "conceptEdges": concept_edges,
        "signals": signals,
        "statistics": {
            "wordCount": word_count,
            "paragraphCount": len(segments),
            "questions": signals["questions"],
            "wordsPerMinute": round(word_count / max(duration_ms / 60_000, 0.1)),
            "durationMinutes": round(duration_ms / 60_000, 1),
        },
        "notice": (
            "Análisis local basado únicamente en el texto. Son indicios, no hechos psicológicos "
            "ni diagnósticos."
        ),
    }
