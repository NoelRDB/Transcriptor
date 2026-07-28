from __future__ import annotations

import copy
import re
from typing import Any

from .unicode_text import repair_data, sanitize_data

PATTERNS: tuple[tuple[str, str, re.Pattern[str]], ...] = (
    ("email", "CORREO", re.compile(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.IGNORECASE)),
    ("dni", "DOCUMENTO", re.compile(r"\b(?:\d{8}[A-Z]|[XYZ]\d{7}[A-Z])\b", re.IGNORECASE)),
    (
        "phone",
        "TELÉFONO",
        re.compile(r"(?<!\w)(?:\+?34[ .-]?)?[6789]\d{2}(?:[ .-]?\d{3}){2}(?!\w)"),
    ),
    (
        "card",
        "TARJETA",
        re.compile(r"(?<!\d)(?:\d[ -]?){13,19}(?!\d)"),
    ),
    (
        "ip",
        "DIRECCIÓN IP",
        re.compile(r"\b(?:25[0-5]|2[0-4]\d|1?\d?\d)(?:\.(?:25[0-5]|2[0-4]\d|1?\d?\d)){3}\b"),
    ),
)


def preview_redactions(project: dict[str, Any]) -> dict[str, Any]:
    findings: list[dict[str, Any]] = []
    counts: dict[str, int] = {}
    for segment in project.get("segments", []):
        text = str(segment.get("text") or "")
        for kind, _label, pattern in PATTERNS:
            for match in pattern.finditer(text):
                value = match.group(0)
                if kind == "card" and not _valid_luhn(value):
                    continue
                counts[kind] = counts.get(kind, 0) + 1
                findings.append(
                    {
                        "kind": kind,
                        "segmentId": str(segment.get("id") or ""),
                        "startMs": int(segment.get("startMs") or 0),
                        "preview": _masked(value),
                    }
                )
    return {"counts": counts, "total": len(findings), "findings": findings[:200]}


def redact_project(project: dict[str, Any]) -> dict[str, Any]:
    output = repair_data(sanitize_data(copy.deepcopy(project)))
    for segment in output.get("segments", []):
        text = str(segment.get("text") or "")
        for kind, label, pattern in PATTERNS:
            if kind == "card":
                text = pattern.sub(
                    lambda match, replacement=label: (
                        f"[{replacement}]" if _valid_luhn(match.group(0)) else match.group(0)
                    ),
                    text,
                )
            else:
                text = pattern.sub(f"[{label}]", text)
        segment["text"] = text
        segment["words"] = []
    output["name"] = f"{output.get('name', 'Transcripción')} · anonimizada"
    return output


def _masked(value: str) -> str:
    if len(value) <= 4:
        return "•" * len(value)
    return f"{value[:2]}{'•' * min(8, len(value) - 4)}{value[-2:]}"


def _valid_luhn(value: str) -> bool:
    digits = [int(character) for character in value if character.isdigit()]
    if not 13 <= len(digits) <= 19:
        return False
    checksum = 0
    parity = len(digits) % 2
    for index, digit in enumerate(digits):
        if index % 2 == parity:
            digit *= 2
            if digit > 9:
                digit -= 9
        checksum += digit
    return checksum % 10 == 0
