import sys
import threading

import pytest

from transcriptor_engine.transcriber import Transcriber, global_progress


def test_faster_whisper_import_uses_deliberate_av_stub():
    from faster_whisper import WhisperModel

    assert WhisperModel is not None
    assert getattr(sys.modules["av"], "__transcriptor_stub__", False) is True


def test_global_progress_reserves_space_for_every_real_phase():
    assert global_progress("decoding", 100) == 10
    assert global_progress("restoring", 100) == 15
    assert global_progress("transcribing", 100) == 88
    assert global_progress("reviewing", 50) == 91
    assert global_progress("diarizing", 100) == 99.5
    assert global_progress("saving", 100) == 99.9
    assert global_progress("reviewing", None) == 88


def test_cpu_request_does_not_probe_cuda(monkeypatch):
    transcriber = Transcriber()
    monkeypatch.setattr(transcriber, "_cuda_runtime_available", lambda: (_ for _ in ()).throw(AssertionError))

    assert transcriber._select_device("cpu", lambda *_: None) == "cpu"


def test_auto_falls_back_to_cpu_with_explanation(monkeypatch):
    transcriber = Transcriber()
    monkeypatch.setattr(transcriber, "_cuda_runtime_available", lambda: False)
    events = []

    device = transcriber._select_device("auto", lambda event, payload: events.append((event, payload)))

    assert device == "cpu"
    assert events[0][0] == "engine_log"
    assert events[0][1]["level"] == "info"
    assert "Modo CPU activo" in events[0][1]["message"]
    assert "misma calidad" in events[0][1]["message"]


def test_explicit_cuda_request_warns_when_gpu_is_unavailable(monkeypatch):
    transcriber = Transcriber()
    monkeypatch.setattr(transcriber, "_cuda_runtime_available", lambda: False)
    events = []

    device = transcriber._select_device("cuda", lambda event, payload: events.append((event, payload)))

    assert device == "cpu"
    assert events[0][1]["level"] == "warning"


def test_auto_uses_cuda_only_after_successful_probe(monkeypatch):
    transcriber = Transcriber()
    monkeypatch.setattr(transcriber, "_cuda_runtime_available", lambda: True)

    assert transcriber._select_device("auto", lambda *_: None) == "cuda"


def test_installed_model_is_loaded_without_network():
    calls = []

    class FakeModel:
        def __init__(self, name, **options):
            calls.append((name, options))

    events = []
    model = Transcriber._load_model(
        FakeModel, "small", "cpu", 60_000, lambda event, payload: events.append((event, payload))
    )

    assert isinstance(model, FakeModel)
    assert len(calls) == 1
    assert calls[0][1]["local_files_only"] is True
    assert calls[0][1]["cpu_threads"] >= 1
    assert "instalado" in events[0][1]["message"]


def test_missing_local_model_downloads_only_after_local_attempt():
    calls = []

    class FakeModel:
        def __init__(self, name, **options):
            calls.append((name, options))
            if options["local_files_only"]:
                raise RuntimeError("missing")

    events = []
    model = Transcriber._load_model(
        FakeModel, "small", "cpu", 60_000, lambda event, payload: events.append((event, payload))
    )

    assert isinstance(model, FakeModel)
    assert [call[1]["local_files_only"] for call in calls] == [True, False]
    assert "Descargando" in events[-1][1]["message"]


def test_resource_profiles_resolve_to_safe_thread_limits(monkeypatch):
    monkeypatch.setattr("transcriptor_engine.transcriber.os.cpu_count", lambda: 16)

    assert Transcriber._resolve_resources({"performanceProfile": "balanced"}) == ("balanced", 8)
    assert Transcriber._resolve_resources({"performanceProfile": "performance"}) == ("performance", 12)
    assert Transcriber._resolve_resources({"performanceProfile": "maximum"}) == ("maximum", 16)
    assert Transcriber._resolve_resources(
        {"performanceProfile": "custom", "cpuThreads": 99}
    ) == ("custom", 16)


def test_quality_modes_select_real_models_and_batching():
    instant = Transcriber._quality_plan({"qualityMode": "instant", "batchSize": 8})
    professional = Transcriber._quality_plan({"qualityMode": "professional", "reviewLowConfidence": True})
    maximum = Transcriber._quality_plan({"qualityMode": "maximum"})

    assert (instant.primary_model, instant.use_batch, instant.batch_size) == ("turbo", True, 8)
    assert (professional.primary_model, professional.review_model) == ("turbo", "large-v3")
    assert (maximum.primary_model, maximum.review_model) == ("large-v3", None)


def test_confidence_marks_doubtful_segments_for_review():
    assert Transcriber._needs_review({"text": "frase dudosa", "confidence": 0.4})
    assert Transcriber._needs_review({"text": "Texto con Ã©", "confidence": 0.95})
    assert not Transcriber._needs_review({"text": "Texto correcto", "confidence": 0.93})


def test_missing_media_fails_before_loading_a_model(tmp_path):
    transcriber = Transcriber()

    with pytest.raises(FileNotFoundError, match="relocaliza"):
        transcriber.transcribe(
            {"mediaPath": str(tmp_path / "movido.wav"), "settings": {}},
            threading.Event(),
            lambda *_: None,
        )
