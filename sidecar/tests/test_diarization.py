import numpy as np

from transcriptor_engine.diarization import SAMPLE_RATE, assign_speakers


def test_offline_acoustic_diarization_can_separate_distinct_voices():
    time = np.arange(SAMPLE_RATE * 2) / SAMPLE_RATE
    first = (0.3 * np.sin(2 * np.pi * 170 * time)).astype(np.float32)
    second = (
        0.25 * np.sin(2 * np.pi * 760 * time) + 0.08 * np.sin(2 * np.pi * 1_500 * time)
    ).astype(np.float32)
    audio = np.concatenate((first, second))
    segments = [
        {"id": "s1", "startMs": 0, "endMs": 2_000, "text": "Primera voz"},
        {"id": "s2", "startMs": 2_000, "endMs": 4_000, "text": "Segunda voz"},
    ]

    output, count = assign_speakers(segments, audio)

    assert count == 2
    assert [segment["speaker"] for segment in output] == ["Hablante 1", "Hablante 2"]
