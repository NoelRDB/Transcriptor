import numpy as np

from transcriptor_engine.audio import assess_audio_quality, enhance_speech_audio


def test_adaptive_audio_enhancement_reports_and_normalizes_signal():
    sample_rate = 16_000
    rng = np.random.default_rng(4)
    noise = rng.normal(0, 0.025, sample_rate * 2).astype(np.float32)
    speech = (0.08 * np.sin(2 * np.pi * 220 * np.arange(sample_rate * 2) / sample_rate)).astype(np.float32)
    audio = noise + speech
    progress = []

    output, assessment = enhance_speech_audio(
        audio,
        "strong",
        lambda: False,
        lambda processed, total, details: progress.append((processed, total, details)),
    )

    assert output.shape == audio.shape
    assert float(np.max(np.abs(output))) <= 0.95
    assert assessment["appliedProfile"] == "strong"
    assert progress[-1][0] == audio.size
    assert "noiseFloorDb" in assess_audio_quality(audio)
