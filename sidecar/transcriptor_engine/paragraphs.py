from __future__ import annotations

import re
from typing import Any

from .unicode_text import repair_data

_SENTENCE_END = re.compile(r"[.!?…][\"'»”)]*$")


def _join_text(left: str, right: str) -> str:
    left = left.rstrip()
    right = right.lstrip()
    if not left:
        return right
    if not right:
        return left
    if right[0] in ",.;:!?…)]}»”":
        return left + right
    return f"{left} {right}"


def group_segments(
    segments: list[dict[str, Any]],
    *,
    max_duration_ms: int = 42_000,
    max_characters: int = 620,
    max_gap_ms: int = 1_800,
) -> list[dict[str, Any]]:
    """Build readable paragraphs without losing word-level timing.

    Whisper deliberately emits short timestamp-safe fragments.  This second
    layer combines them for reading, while retaining every original word and
    preserving the exact first/last timestamps used for seeking.
    """
    ordered = sorted(
        repair_data(segments),
        key=lambda item: (int(item["startMs"]), int(item.get("order", 0))),
    )
    if not ordered:
        return []

    groups: list[list[dict[str, Any]]] = []
    current: list[dict[str, Any]] = []
    for segment in ordered:
        text = str(segment.get("text", "")).strip()
        if not text:
            continue
        if not current:
            current = [segment]
            continue

        previous = current[-1]
        combined_text = text
        for item in current:
            combined_text = _join_text(str(item.get("text", "")), combined_text)
        gap = max(0, int(segment["startMs"]) - int(previous["endMs"]))
        duration = int(segment["endMs"]) - int(current[0]["startMs"])
        speaker_changed = (
            (previous.get("speaker") or None) != (segment.get("speaker") or None)
            or (previous.get("speakerProfileId") or None)
            != (segment.get("speakerProfileId") or None)
        )
        previous_has_sentence_end = bool(_SENTENCE_END.search(str(previous.get("text", "")).strip()))
        natural_break = previous_has_sentence_end and (
            gap >= 750 or len(" ".join(str(item.get("text", "")) for item in current)) >= 180
        )
        must_break = (
            speaker_changed
            or gap > max_gap_ms
            or duration > max_duration_ms
            or len(combined_text) > max_characters
            or natural_break
        )
        if must_break:
            groups.append(current)
            current = [segment]
        else:
            current.append(segment)
    if current:
        groups.append(current)

    result: list[dict[str, Any]] = []
    for order, group in enumerate(groups):
        first, last = group[0], group[-1]
        text = ""
        words: list[dict[str, Any]] = []
        confidences: list[float] = []
        speaker_confidences: list[float] = []
        speaker_match_confidences: list[float] = []
        review_states: list[str] = []
        speaker_review_states: list[str] = []
        review_reasons: list[str] = []
        for item in group:
            text = _join_text(text, str(item.get("text", "")).strip())
            words.extend(item.get("words", []))
            if item.get("confidence") is not None:
                confidences.append(float(item["confidence"]))
            if item.get("speakerConfidence") is not None:
                speaker_confidences.append(float(item["speakerConfidence"]))
            if item.get("speakerMatchConfidence") is not None:
                speaker_match_confidences.append(float(item["speakerMatchConfidence"]))
            if item.get("reviewState"):
                review_states.append(str(item["reviewState"]))
            if item.get("speakerReviewState"):
                speaker_review_states.append(str(item["speakerReviewState"]))
            for reason in item.get("reviewReasons", []):
                if str(reason) not in review_reasons:
                    review_reasons.append(str(reason))
        review_state = None
        if "pending" in review_states:
            review_state = "pending"
        elif "corrected" in review_states:
            review_state = "corrected"
        elif review_states and len(review_states) == len(group):
            review_state = "accepted"
        speaker_review_state = None
        if "pending" in speaker_review_states:
            speaker_review_state = "pending"
        elif "corrected" in speaker_review_states:
            speaker_review_state = "corrected"
        elif speaker_review_states and len(speaker_review_states) == len(group):
            speaker_review_state = "accepted"
        if confidences and min(confidences) < 0.84:
            reason = "Parte del texto tiene confianza inferior al 84 %."
            if reason not in review_reasons:
                review_reasons.append(reason)
        result.append(
            {
                "id": str(first["id"]),
                "startMs": int(first["startMs"]),
                "endMs": max(int(first["startMs"]) + 1, int(last["endMs"])),
                "text": text,
                "speaker": first.get("speaker"),
                "speakerCluster": first.get("speakerCluster"),
                "confidence": round(min(confidences), 4) if confidences else None,
                "speakerConfidence": (
                    round(min(speaker_confidences), 4)
                    if speaker_confidences
                    else None
                ),
                "speakerProfileId": first.get("speakerProfileId"),
                "speakerMatchConfidence": (
                    round(min(speaker_match_confidences), 4)
                    if speaker_match_confidences
                    else None
                ),
                "speakerProvisional": any(bool(item.get("speakerProvisional")) for item in group),
                "reviewState": review_state,
                "speakerReviewState": speaker_review_state,
                "reviewReasons": review_reasons,
                "order": order,
                "words": words,
            }
        )
    return result
