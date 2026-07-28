from pathlib import Path

from transcriptor_engine import media_edit


def test_ranges_are_merged_and_complemented():
    assert media_edit._merge_ranges([(4_000, 5_000), (1_000, 3_000), (2_500, 4_500)]) == [
        (1_000, 5_000)
    ]
    assert media_edit._complement_ranges([(1_000, 2_000), (4_000, 5_000)], 6_000) == [
        (0, 1_000),
        (2_000, 4_000),
        (5_000, 6_000),
    ]


def test_command_keeps_unicode_paths_as_separate_arguments(monkeypatch):
    monkeypatch.setattr(media_edit, "_find_tool", lambda _name: "C:/Tools/ffmpeg.exe")
    source = Path("C:/Vídeos con espacios/niño.wav")
    target = Path("C:/Salida/copia editada.wav")

    command = media_edit.build_edit_command(source, target, [(0, 1_000), (2_000, 4_000)], "audio")

    assert command[command.index("-i") + 1] == str(source)
    assert command[-1] == str(target)
    assert "concat=n=2:v=0:a=1" in command[command.index("-filter_complex") + 1]
