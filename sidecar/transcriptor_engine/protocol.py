from __future__ import annotations

import json
import sys
import threading
from typing import Any


class ProtocolWriter:
    """Emite exclusivamente JSONL por stdout; los logs técnicos van dentro del protocolo."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        if hasattr(sys.stdout, "reconfigure"):
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    def send(self, message_type: str, payload: Any, request_id: str | None = None) -> None:
        message = {"type": message_type, "payload": payload}
        if request_id:
            message["requestId"] = request_id
        encoded = json.dumps(message, ensure_ascii=False, separators=(",", ":"))
        with self._lock:
            sys.stdout.write(encoded + "\n")
            sys.stdout.flush()

    def result(self, request_id: str, payload: Any) -> None:
        self.send("result", payload, request_id)

    def error(self, request_id: str, message: str, code: str = "ENGINE_ERROR") -> None:
        self.send("error", {"code": code, "message": message}, request_id)
