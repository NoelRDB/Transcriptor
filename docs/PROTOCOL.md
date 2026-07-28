# Protocolo JSONL

Cada línea de stdin y stdout es un objeto JSON UTF-8 completo. stdout queda reservado al protocolo.

## Solicitud

```json
{"requestId":"uuid","action":"analyze_media","payload":{"mediaPath":"C:\\media\\audio.mp3"}}
```

Acciones actuales:

- `analyze_media`
- `save_project`
- `list_projects`
- `load_project`
- `transcribe`
- `cancel`
- `export_project`
- `group_paragraphs`
- `analyze_transcript`
- `get_local_ai_status`
- `list_models`, `download_model`, `delete_model`
- `get_speaker_ai_status`, `install_speaker_ai`, `cancel_speaker_ai_download`
- `enqueue_transcription`, `list_queue`, `reorder_queue`, `remove_from_queue`
- `semantic_search`
- `list_versions`, `restore_version`, `list_evidence`
- `list_markers`, `add_marker`
- `list_assistant_messages`, `ask_transcript`
- `preview_redactions`
- `export_package`, `import_package`
- `export_media_edit`

`analyze_transcript` acepta `depth: "deep" | "quick"`, confirma inmediatamente la aceptación y
ejecuta el trabajo fuera del bucle de entrada. Emite `analysis_progress`, `analysis_completed`,
`analysis_cancelled` o `analysis_failed`; `cancel_analysis` permite interrumpirlo. El modo profundo usa exclusivamente
`http://127.0.0.1:11434`, analiza bloques temporales con Qwen 3.5 y emite `analysis_progress`
con unidades terminadas, porcentaje, fase, modelo y tiempo transcurrido. El texto no se envía
a ningún endpoint remoto.
- `start_live_session`
- `push_live_audio`
- `stop_live_session`
- `cancel_live_session`

Las sesiones en directo aceptan fuente `microphone`, `system` o `mixed`, idioma explícito y marcadores temporales. El permiso para compartir audio del sistema lo gestiona WebView2 y siempre requiere una acción visible del usuario.

## Respuestas

```json
{"type":"result","requestId":"uuid","payload":{"accepted":true}}
```

```json
{"type":"error","requestId":"uuid","payload":{"code":"INVALID_REQUEST","message":"Mensaje seguro"}}
```

## Eventos

- `job_started`: el modelo está cargado y comienza inferencia.
- `media_analyzed`: reservado para análisis asíncrono futuro.
- `audio_extraction_progress`: reservado para extracción explícita con FFmpeg.
- `model_download_progress`: bytes y porcentaje real cuando el repositorio publica el tamaño total; nunca inventa porcentajes.
- `speaker_model_progress`, `speaker_model_completed`, `speaker_model_cancelled` y `speaker_model_failed`: instalación consentida y verificable de CAM++.
- `transcription_progress` con etapa `reviewing`: Large-v3 revisa fragmentos de baja confianza después de la pasada Turbo.
- `transcription_progress` con etapa `diarizing`: unidades vocales completadas, total, ETA medida y backend de hablantes activo.
- `voice_profiles_updated`: catálogo público actualizado después de aprender una voz; nunca incluye embeddings.
- `transcription_progress`: duración procesada, total y porcentaje calculado.
- `partial_segments`: uno o más segmentos completos con palabras. Al terminar puede incluir `replaceExisting: true` para sustituir los microfragmentos por párrafos contextuales.
- `job_completed`: idioma, duración, dispositivo y recuento.
- `job_cancelled`: confirmación cooperativa.
- `job_failed`: código y mensaje seguro.
- `engine_log`: diagnóstico sin contenido privado.
- `live_status`: carga del modelo y estado técnico de la sesión de micrófono, sin incluir audio ni texto.

Los timestamps son milisegundos enteros. El final de un segmento es exclusivo para decidir el resaltado.
Acciones locales de perfiles:

- `list_voice_profiles`: devuelve nombres, fiabilidad, duración y configuración, sin vectores.
- `update_voice_profile`: renombra, pausa o ajusta el umbral.
- `delete_voice_profile`: elimina el perfil y todas sus huellas cifradas.
