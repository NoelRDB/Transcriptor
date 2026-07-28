from transcriptor_engine import system_diagnostics


def test_diagnostics_reports_a_readable_media_file(tmp_path, monkeypatch):
    media = tmp_path / "Grabación ñ.wav"
    media.write_bytes(b"test")
    monkeypatch.setattr(system_diagnostics, "_find_tool", lambda name: f"C:/tools/{name}.exe")
    monkeypatch.setattr(system_diagnostics, "models_dir", lambda: tmp_path)
    monkeypatch.setattr(
        system_diagnostics,
        "get_hardware_info",
        lambda _cuda: {"gpu": None, "cudaAvailable": False, "cpu": {}, "memory": {}},
    )
    monkeypatch.setattr(
        system_diagnostics,
        "get_local_ai_status",
        lambda: {"available": True, "installed": True},
    )
    monkeypatch.setattr(
        system_diagnostics,
        "analyze_media",
        lambda path: {"durationMs": 1_000, "audioTracks": 1, "path": path},
    )

    result = system_diagnostics.diagnose_system(str(media))

    media_check = next(item for item in result["checks"] if item["id"] == "media")
    assert media_check["status"] == "ok"
    assert result["media"]["audioTracks"] == 1


def test_missing_media_can_be_found_in_controlled_user_folders(tmp_path, monkeypatch):
    desktop = tmp_path / "Desktop"
    desktop.mkdir()
    moved = desktop / "entrevista.wav"
    moved.write_bytes(b"audio")
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    monkeypatch.setattr(system_diagnostics, "app_data_dir", lambda: tmp_path / "app-data")

    candidates = system_diagnostics._find_media_candidates(tmp_path / "old" / "entrevista.wav")

    assert candidates == [str(moved.resolve())]
