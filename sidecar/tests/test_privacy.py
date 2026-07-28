from transcriptor_engine.privacy import preview_redactions, redact_project


def test_sensitive_data_is_previewed_masked_and_redacted():
    project = {
        "name": "Conversación",
        "segments": [
            {
                "id": "s1",
                "startMs": 1_000,
                "text": "Escribe a ana@example.com o llama al 612 345 678. DNI 12345678Z.",
                "words": [{"text": "ana@example.com"}],
            }
        ],
    }

    preview = preview_redactions(project)
    redacted = redact_project(project)

    assert preview["total"] == 3
    assert "ana@example.com" not in str(preview)
    assert redacted["segments"][0]["text"] == (
        "Escribe a [CORREO] o llama al [TELÉFONO]. DNI [DOCUMENTO]."
    )
    assert redacted["segments"][0]["words"] == []
