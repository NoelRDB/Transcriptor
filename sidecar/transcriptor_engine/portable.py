from __future__ import annotations

import hashlib
import json
import shutil
import uuid
import zipfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .paths import app_data_dir
from .unicode_text import repair_data, sanitize_data

PACKAGE_VERSION = 1


def export_package(
    project: dict[str, Any],
    output_path: str,
    include_media: bool,
    evidence: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    target = Path(output_path).resolve()
    if target.suffix.lower() != ".transcriptor":
        target = target.with_suffix(".transcriptor")
    target.parent.mkdir(parents=True, exist_ok=True)
    clean = repair_data(sanitize_data({key: value for key, value in project.items() if key != "mediaUrl"}))
    media_path = Path(str(project.get("mediaPath") or ""))
    media_name = media_path.name if include_media and media_path.is_file() else None
    manifest = {
        "format": "Transcriptor Portable Project",
        "version": PACKAGE_VERSION,
        "projectId": str(project.get("id") or ""),
        "createdAt": datetime.now(UTC).isoformat(),
        "mediaIncluded": bool(media_name),
        "mediaName": media_name,
        "mediaSha256": _sha256(media_path) if media_name else None,
    }
    with zipfile.ZipFile(target, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as package:
        package.writestr("manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2))
        package.writestr("project.json", json.dumps(clean, ensure_ascii=False, indent=2))
        package.writestr("evidence.json", json.dumps(evidence or [], ensure_ascii=False, indent=2))
        if media_name:
            package.write(media_path, f"media/{media_name}")
    return {"path": str(target), **manifest}


def import_package(package_path: str) -> dict[str, Any]:
    source = Path(package_path).resolve()
    if not source.is_file():
        raise FileNotFoundError("No se encuentra el proyecto portátil seleccionado.")
    with zipfile.ZipFile(source) as package:
        names = set(package.namelist())
        if not {"manifest.json", "project.json"}.issubset(names):
            raise ValueError("El archivo no es un proyecto Transcriptor válido.")
        manifest = json.loads(package.read("manifest.json"))
        if int(manifest.get("version") or 0) > PACKAGE_VERSION:
            raise ValueError("El proyecto fue creado con una versión más reciente de Transcriptor.")
        project = repair_data(json.loads(package.read("project.json")))
        original_id = str(project.get("id") or uuid.uuid4())
        project["id"] = str(uuid.uuid4())
        project["name"] = f"{project.get('name', 'Proyecto')} · importado"
        project["createdAt"] = datetime.now(UTC).isoformat()
        project["updatedAt"] = project["createdAt"]
        media_name = manifest.get("mediaName")
        if manifest.get("mediaIncluded") and media_name:
            archive_name = f"media/{Path(str(media_name)).name}"
            if archive_name not in names:
                raise ValueError("El paquete indica que incluye audio, pero el archivo no está dentro.")
            destination_dir = app_data_dir() / "imports" / project["id"]
            destination_dir.mkdir(parents=True, exist_ok=True)
            destination = destination_dir / Path(str(media_name)).name
            with package.open(archive_name) as input_file, destination.open("wb") as output_file:
                shutil.copyfileobj(input_file, output_file, length=1024 * 1024)
            expected_hash = str(manifest.get("mediaSha256") or "")
            if expected_hash and _sha256(destination) != expected_hash:
                destination.unlink(missing_ok=True)
                raise ValueError(
                    "La verificación del audio incluido ha fallado; el paquete puede estar dañado."
                )
            project["mediaPath"] = str(destination)
        project["portableSourceId"] = original_id
        return project


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()
