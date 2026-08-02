from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any

from .media import _find_tool


def export_without_segments(
    project: dict[str, Any], excluded_segment_ids: list[str], output_path: str
) -> dict[str, Any]:
    source = Path(str(project.get("mediaPath") or "")).resolve()
    if not source.is_file():
        raise FileNotFoundError("No se encuentra el audio o vídeo original.")
    duration_ms = int(project.get("durationMs") or 0)
    if duration_ms <= 0:
        raise ValueError("No se puede editar un archivo sin duración conocida.")
    excluded_ids = set(excluded_segment_ids)
    excluded = [
        (max(0, int(item.get("startMs") or 0)), min(duration_ms, int(item.get("endMs") or 0)))
        for item in project.get("segments", [])
        if str(item.get("id")) in excluded_ids
    ]
    keep = _complement_ranges(_merge_ranges(excluded), duration_ms)
    if not keep:
        raise ValueError("La selección eliminaría todo el contenido multimedia.")
    media_type = str(project.get("mediaType") or "audio")
    target = Path(output_path).resolve()
    expected_suffix = ".mp4" if media_type == "video" else ".wav"
    if target.suffix.lower() != expected_suffix:
        target = target.with_suffix(expected_suffix)
    target.parent.mkdir(parents=True, exist_ok=True)
    command = build_edit_command(source, target, keep, media_type)
    creation_flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    completed = subprocess.run(
        command,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        creationflags=creation_flags,
        check=False,
    )
    if completed.returncode != 0:
        detail = (
            completed.stderr.strip().splitlines()[-1]
            if completed.stderr.strip()
            else "Error desconocido"
        )
        raise RuntimeError(f"FFmpeg no pudo crear la edición: {detail}")
    return {
        "outputPath": str(target),
        "removedSegments": len(excluded_ids),
        "remainingDurationMs": sum(end - start for start, end in keep),
    }


def build_edit_command(
    source: Path, target: Path, keep_ranges: list[tuple[int, int]], media_type: str
) -> list[str]:
    ffmpeg = _find_tool("ffmpeg")
    if not ffmpeg:
        raise FileNotFoundError("FFmpeg no está disponible en la instalación.")
    filters: list[str] = []
    inputs: list[str] = []
    if media_type == "video":
        for index, (start_ms, end_ms) in enumerate(keep_ranges):
            start, end = start_ms / 1000, end_ms / 1000
            filters.extend(
                [
                    f"[0:v]trim=start={start:.3f}:end={end:.3f},setpts=PTS-STARTPTS[v{index}]",
                    f"[0:a]atrim=start={start:.3f}:end={end:.3f},asetpts=PTS-STARTPTS[a{index}]",
                ]
            )
            inputs.append(f"[v{index}][a{index}]")
        filters.append(f"{''.join(inputs)}concat=n={len(keep_ranges)}:v=1:a=1[outv][outa]")
        output_options = [
            "-map",
            "[outv]",
            "-map",
            "[outa]",
            "-c:v",
            "mpeg4",
            "-q:v",
            "5",
            "-c:a",
            "aac",
            "-movflags",
            "+faststart",
        ]
    else:
        for index, (start_ms, end_ms) in enumerate(keep_ranges):
            start, end = start_ms / 1000, end_ms / 1000
            filters.append(
                f"[0:a]atrim=start={start:.3f}:end={end:.3f},asetpts=PTS-STARTPTS[a{index}]"
            )
            inputs.append(f"[a{index}]")
        filters.append(f"{''.join(inputs)}concat=n={len(keep_ranges)}:v=0:a=1[outa]")
        output_options = ["-map", "[outa]", "-c:a", "pcm_s16le"]
    return [
        ffmpeg,
        "-hide_banner",
        "-loglevel",
        "error",
        "-y",
        "-i",
        str(source),
        "-filter_complex",
        ";".join(filters),
        *output_options,
        str(target),
    ]


def _merge_ranges(ranges: list[tuple[int, int]]) -> list[tuple[int, int]]:
    merged: list[tuple[int, int]] = []
    for start, end in sorted((start, end) for start, end in ranges if end > start):
        if merged and start <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], end))
        else:
            merged.append((start, end))
    return merged


def _complement_ranges(excluded: list[tuple[int, int]], duration_ms: int) -> list[tuple[int, int]]:
    keep: list[tuple[int, int]] = []
    cursor = 0
    for start, end in excluded:
        if start > cursor:
            keep.append((cursor, start))
        cursor = max(cursor, end)
    if cursor < duration_ms:
        keep.append((cursor, duration_ms))
    return [(start, end) for start, end in keep if end - start >= 40]
