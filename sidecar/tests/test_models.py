from pathlib import Path

from transcriptor_engine import models


def _disk_usage(free: int):
    return type("DiskUsage", (), {"total": free * 2, "used": free, "free": free})()


def test_model_catalog_distinguishes_partial_and_ready_installations(
    tmp_path: Path, monkeypatch
):
    monkeypatch.setattr(models, "models_dir", lambda: tmp_path)
    monkeypatch.setattr(
        models.shutil,
        "disk_usage",
        lambda _path: _disk_usage(20 * models.GIB),
    )
    partial = tmp_path / "turbo"
    partial.mkdir()
    (partial / "config.json").write_text("{}", encoding="utf-8")

    catalog = models.list_models()
    turbo = next(item for item in catalog["models"] if item["id"] == "turbo")

    assert turbo["installed"] is False
    assert turbo["integrity"] == "partial"
    assert turbo["missingFiles"] == [
        "model.bin",
        "tokenizer.json",
        "vocabulary.json",
    ]
    assert turbo["canInstall"] is True
    assert turbo["requiredFreeBytes"] > turbo["downloadBytes"]

    (partial / "model.bin").write_bytes(b"\0" * (1024**2 + 1))
    (partial / "tokenizer.json").write_text("{}", encoding="utf-8")
    (partial / "vocabulary.json").write_text("{}", encoding="utf-8")
    ready = next(item for item in models.list_models()["models"] if item["id"] == "turbo")

    assert ready["installed"] is True
    assert ready["integrity"] == "ready"
    assert ready["missingFiles"] == []
    assert ready["requiredFreeBytes"] == 0


def test_model_catalog_reports_insufficient_space_before_download(
    tmp_path: Path, monkeypatch
):
    monkeypatch.setattr(models, "models_dir", lambda: tmp_path)
    monkeypatch.setattr(
        models.shutil,
        "disk_usage",
        lambda _path: _disk_usage(256 * 1024**2),
    )

    catalog = models.list_models()
    turbo = next(item for item in catalog["models"] if item["id"] == "turbo")

    assert turbo["recommended"] is True
    assert turbo["installed"] is False
    assert turbo["canInstall"] is False
    assert turbo["requiredFreeBytes"] > catalog["freeBytes"]
