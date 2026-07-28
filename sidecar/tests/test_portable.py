import json
import zipfile

from transcriptor_engine import portable


def test_portable_project_roundtrip_with_verified_media(tmp_path, monkeypatch):
    monkeypatch.setattr(portable, "app_data_dir", lambda: tmp_path / "app-data")
    media = tmp_path / "voz con acento.wav"
    media.write_bytes(b"small generated audio fixture")
    project = {
        "id": "original",
        "name": "Reunión",
        "mediaPath": str(media),
        "mediaType": "audio",
        "durationMs": 1000,
        "model": "turbo",
        "createdAt": "2026-01-01T00:00:00Z",
        "updatedAt": "2026-01-01T00:00:00Z",
        "transcriptionStatus": "completed",
        "lastPlaybackPositionMs": 0,
        "settings": {},
        "segments": [{"id": "s1", "startMs": 0, "endMs": 1000, "text": "Hola", "order": 0}],
    }
    output = tmp_path / "portable.transcriptor"

    result = portable.export_package(project, str(output), include_media=True)
    imported = portable.import_package(str(output))

    assert result["mediaIncluded"] is True
    assert imported["id"] != project["id"]
    assert imported["portableSourceId"] == project["id"]
    assert imported["segments"][0]["text"] == "Hola"
    assert portable.Path(imported["mediaPath"]).read_bytes() == media.read_bytes()
    with zipfile.ZipFile(output) as package:
        assert json.loads(package.read("manifest.json"))["mediaSha256"]
