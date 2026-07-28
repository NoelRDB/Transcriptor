from transcriptor_engine.paragraphs import group_segments


def segment(index: int, start: int, end: int, text: str, speaker=None):
    return {
        "id": f"s{index}",
        "startMs": start,
        "endMs": end,
        "text": text,
        "speaker": speaker,
        "confidence": 0.9,
        "order": index,
        "words": [{"id": f"w{index}", "startMs": start, "endMs": end, "text": text}],
    }


def test_short_whisper_fragments_become_readable_paragraphs():
    source = [
        segment(0, 0, 1800, "Esta es una idea"),
        segment(1, 1900, 3600, "que continúa aquí"),
        segment(2, 3700, 5100, "y termina ahora."),
        segment(3, 7000, 8500, "Este es otro párrafo."),
    ]
    grouped = group_segments(source)
    assert [item["text"] for item in grouped] == [
        "Esta es una idea que continúa aquí y termina ahora.",
        "Este es otro párrafo.",
    ]
    assert len(grouped[0]["words"]) == 3
    assert grouped[0]["startMs"] == 0
    assert grouped[0]["endMs"] == 5100


def test_speaker_changes_always_start_a_new_paragraph():
    grouped = group_segments(
        [segment(0, 0, 1000, "Hola", "Ana"), segment(1, 1100, 2000, "Hola", "Luis")]
    )
    assert len(grouped) == 2


def test_long_paragraph_is_bounded_without_losing_words():
    source = [segment(i, i * 1000, i * 1000 + 900, "texto repetido") for i in range(60)]
    grouped = group_segments(source, max_duration_ms=10_000)
    assert len(grouped) > 1
    assert sum(len(item["words"]) for item in grouped) == len(source)


def test_paragraph_keeps_the_lowest_confidence_visible_for_review():
    source = [
        segment(0, 0, 1_000, "Texto muy claro"),
        {**segment(1, 1_100, 2_000, "pero esta parte es dudosa."), "confidence": 0.68},
    ]

    grouped = group_segments(source)

    assert len(grouped) == 1
    assert grouped[0]["confidence"] == 0.68
    assert any("84 %" in reason for reason in grouped[0]["reviewReasons"])
