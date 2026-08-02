from __future__ import annotations

from typing import Any


def sanitize_text(value: str) -> str:
    """Replace isolated UTF-16 surrogates while preserving every valid Unicode character."""
    if value.isascii():
        return value
    return "".join("\ufffd" if 0xD800 <= ord(character) <= 0xDFFF else character for character in value)


_MOJIBAKE_MARKERS = ("Ã", "Â", "â€", "â€™", "ðŸ", "ƒ")


def _mojibake_score(value: str) -> int:
    return sum(value.count(marker) for marker in _MOJIBAKE_MARKERS) + value.count("\ufffd") * 4


def repair_mojibake(value: str) -> str:
    """Repair UTF-8 that was accidentally decoded as a Western single-byte encoding.

    A conversion is accepted only when it strictly reduces common corruption markers,
    so legitimate Spanish and names containing these characters are left untouched.
    """
    if value.isascii():
        return value
    best = sanitize_text(value)
    # An early build replaced the second byte of "África" before saving it.
    # This exact residual form cannot be recovered by a generic UTF-8 roundtrip.
    best = best.replace("\u00c3\ufffdfrica", "África")
    if _mojibake_score(best) == 0:
        return best
    for _ in range(2):
        current_score = _mojibake_score(best)
        candidates: list[str] = []
        for encoding in ("latin-1", "cp1252"):
            try:
                candidates.append(best.encode(encoding).decode("utf-8"))
            except (UnicodeEncodeError, UnicodeDecodeError):
                continue
        improved = min(candidates, key=_mojibake_score, default=best)
        if _mojibake_score(improved) >= current_score:
            break
        best = improved
    return best


def sanitize_data(value: Any) -> Any:
    if isinstance(value, str):
        return sanitize_text(value)
    if isinstance(value, list):
        return [sanitize_data(item) for item in value]
    if isinstance(value, tuple):
        return tuple(sanitize_data(item) for item in value)
    if isinstance(value, dict):
        return {
            sanitize_text(key) if isinstance(key, str) else key: sanitize_data(item)
            for key, item in value.items()
        }
    return value


def repair_data(value: Any) -> Any:
    if isinstance(value, str):
        return repair_mojibake(value)
    if isinstance(value, list):
        return [repair_data(item) for item in value]
    if isinstance(value, tuple):
        return tuple(repair_data(item) for item in value)
    if isinstance(value, dict):
        return {
            repair_mojibake(key) if isinstance(key, str) else key: repair_data(item)
            for key, item in value.items()
        }
    return value
