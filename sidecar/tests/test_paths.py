from pathlib import Path

from transcriptor_engine import paths


def test_new_windows_install_keeps_data_outside_the_program_directory(
    tmp_path: Path, monkeypatch
):
    monkeypatch.setattr(paths.sys, "platform", "win32")
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    (tmp_path / "Transcriptor").mkdir()
    (tmp_path / "Transcriptor" / "transcriptor.exe").write_bytes(b"program")

    assert paths.app_data_dir() == tmp_path / "TranscriptorData"


def test_existing_windows_install_continues_using_legacy_user_data(
    tmp_path: Path, monkeypatch
):
    monkeypatch.setattr(paths.sys, "platform", "win32")
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    legacy = tmp_path / "Transcriptor"
    legacy.mkdir()
    (legacy / "transcriptor.sqlite3").write_bytes(b"existing project")

    assert paths.app_data_dir() == legacy
    assert paths.preferred_app_data_dir() == tmp_path / "TranscriptorData"
