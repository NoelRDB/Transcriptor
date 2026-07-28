from __future__ import annotations

import ctypes
import os
from ctypes import wintypes

import numpy as np

_ENTROPY = b"Transcriptor.VoiceProfile.v1"
_DPAPI_PREFIX = b"DPAPI1"
_RAW_PREFIX = b"RAW1"


class _DataBlob(ctypes.Structure):
    _fields_ = [
        ("cbData", wintypes.DWORD),
        ("pbData", ctypes.POINTER(ctypes.c_ubyte)),
    ]


def _blob(data: bytes) -> tuple[_DataBlob, ctypes.Array[ctypes.c_ubyte]]:
    buffer = (ctypes.c_ubyte * len(data)).from_buffer_copy(data)
    return _DataBlob(len(data), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_ubyte))), buffer


def protect_embedding(vector: np.ndarray) -> bytes:
    normalized = np.asarray(vector, dtype=np.float32).reshape(-1)
    if normalized.size != 192 or not np.isfinite(normalized).all():
        raise ValueError("La huella vocal no tiene el formato CAM++ esperado.")
    raw = normalized.tobytes()
    if os.name != "nt":
        return _RAW_PREFIX + raw

    source, source_buffer = _blob(raw)
    entropy, entropy_buffer = _blob(_ENTROPY)
    output = _DataBlob()
    crypt32 = ctypes.windll.crypt32
    kernel32 = ctypes.windll.kernel32
    if not crypt32.CryptProtectData(
        ctypes.byref(source),
        "Transcriptor voice profile",
        ctypes.byref(entropy),
        None,
        None,
        0x01,
        ctypes.byref(output),
    ):
        raise ctypes.WinError()
    try:
        encrypted = ctypes.string_at(output.pbData, output.cbData)
        return _DPAPI_PREFIX + encrypted
    finally:
        kernel32.LocalFree(output.pbData)
        del source_buffer, entropy_buffer


def unprotect_embedding(payload: bytes) -> np.ndarray:
    if payload.startswith(_RAW_PREFIX):
        raw = payload[len(_RAW_PREFIX) :]
    elif payload.startswith(_DPAPI_PREFIX) and os.name == "nt":
        source, source_buffer = _blob(payload[len(_DPAPI_PREFIX) :])
        entropy, entropy_buffer = _blob(_ENTROPY)
        output = _DataBlob()
        crypt32 = ctypes.windll.crypt32
        kernel32 = ctypes.windll.kernel32
        if not crypt32.CryptUnprotectData(
            ctypes.byref(source),
            None,
            ctypes.byref(entropy),
            None,
            None,
            0x01,
            ctypes.byref(output),
        ):
            raise ctypes.WinError()
        try:
            raw = ctypes.string_at(output.pbData, output.cbData)
        finally:
            kernel32.LocalFree(output.pbData)
            del source_buffer, entropy_buffer
    else:
        raise ValueError("La huella vocal no se puede descifrar en esta cuenta.")

    vector = np.frombuffer(raw, dtype=np.float32).copy()
    if vector.size != 192 or not np.isfinite(vector).all():
        raise ValueError("La huella vocal almacenada está dañada.")
    norm = float(np.linalg.norm(vector))
    if norm <= 1e-8:
        raise ValueError("La huella vocal almacenada está vacía.")
    return vector / norm


def encryption_label() -> str:
    return "DPAPI · cuenta de Windows" if os.name == "nt" else "almacenamiento local"
