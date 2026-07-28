from __future__ import annotations

import json
import zipfile

import pytest

from transcriptor_engine.exporters import export_to, render, subtitle_time

PROJECT = {
    "id": "p1",
    "mediaUrl": "asset://private",
    "segments": [
        {"startMs": 3000, "endMs": 2500, "text": "Final", "order": 2},
        {"startMs": -1, "endMs": 1000, "text": "Hola", "speaker": "Persona 1", "order": 1},
    ],
}


def test_subtitle_time_and_srt_are_normalized():
    assert subtitle_time(3_723_456, ",") == "01:02:03,456"
    output = render(PROJECT, "srt")
    assert "00:00:00,000 --> 00:00:01,000" in output
    assert "00:00:03,000 --> 00:00:03,001" in output


def test_vtt_has_header():
    assert render(PROJECT, "vtt").startswith("WEBVTT\n\n")


def test_long_subtitle_is_split_into_valid_ordered_cues():
    project = {
        "settings": {"subtitleLineLength": 18, "subtitleMaxLines": 1},
        "segments": [
            {
                "startMs": 1_000,
                "endMs": 7_000,
                "text": "Esta frase muy larga debe dividirse en varios subtítulos fáciles de leer",
                "order": 0,
            }
        ],
    }
    output = render(project, "srt")
    timeline_rows = [line for line in output.splitlines() if " --> " in line]
    assert len(timeline_rows) >= 3
    assert timeline_rows[0].startswith("00:00:01,000")
    assert timeline_rows[-1].endswith("00:00:07,000")


def test_json_omits_transient_media_url():
    parsed = json.loads(render(PROJECT, "json"))
    assert "mediaUrl" not in parsed["project"]


def test_export_adds_the_expected_extension(tmp_path):
    export_to(PROJECT, "txt", str(tmp_path / "transcripción"))
    assert (tmp_path / "transcripción.txt").read_text(encoding="utf-8-sig").startswith("Persona 1")


@pytest.mark.parametrize("export_format", ["txt", "srt", "vtt", "json", "csv"])
def test_export_replaces_isolated_surrogates_in_every_format(tmp_path, export_format):
    damaged = {
        **PROJECT,
        "name": "Proyecto \udc81",
        "segments": [
            {
                "startMs": 0,
                "endMs": 1000,
                "text": "Texto \udc81 válido \U0001f642",
                "speaker": "Voz \ud800",
                "order": 0,
                "words": [{"text": "palabra \udc81"}],
            }
        ],
    }

    output = tmp_path / f"resultado.{export_format}"
    export_to(damaged, export_format, str(output))
    contents = output.read_text(encoding="utf-8")

    assert "\udc81" not in contents
    assert "\ud800" not in contents
    assert "\ufffd" in contents
    assert "\U0001f642" in contents
    if export_format == "json":
        json.loads(contents)


@pytest.mark.parametrize("export_format", ["txt", "srt", "vtt", "csv"])
def test_windows_text_exports_have_utf8_bom(tmp_path, export_format):
    output = tmp_path / f"resultado.{export_format}"
    export_to(PROJECT, export_format, str(output))
    assert output.read_bytes().startswith(b"\xef\xbb\xbf")


def test_json_stays_standard_utf8_without_bom(tmp_path):
    output = tmp_path / "resultado.json"
    export_to(PROJECT, "json", str(output))
    assert output.read_bytes().startswith(b"{")


def test_export_repairs_legacy_mojibake(tmp_path):
    damaged = {
        **PROJECT,
        "segments": [
            {
                "startMs": 0,
                "endMs": 1000,
                "text": "m\u00c3\u0083\u00c2\u00a1s informaci\u00c3\u0083\u00c2\u00b3n",
                "order": 0,
            }
        ],
    }
    output = tmp_path / "resultado.txt"
    export_to(damaged, "txt", str(output))
    assert output.read_text(encoding="utf-8-sig") == "m\u00e1s informaci\u00f3n"


def test_docx_export_is_a_valid_office_document(tmp_path):
    output = tmp_path / "resultado.docx"
    export_to({**PROJECT, "name": "Reunión local"}, "docx", str(output))
    assert zipfile.is_zipfile(output)
    with zipfile.ZipFile(output) as package:
        document_xml = package.read("word/document.xml").decode("utf-8")
    assert "Reunión local" in document_xml
    assert "Persona 1" in document_xml


def test_pdf_export_has_pdf_header_and_content(tmp_path):
    output = tmp_path / "resultado.pdf"
    export_to({**PROJECT, "name": "Informe local"}, "pdf", str(output))
    assert output.read_bytes().startswith(b"%PDF-")
    assert output.stat().st_size > 1_000
