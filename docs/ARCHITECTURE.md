# Arquitectura

## Capas

```text
React/TypeScript
  ├─ reproductor y sincronización temporal
  ├─ edición, búsqueda, análisis y exportación
  └─ store tipado (Zustand)
          │ JSONL por stdin/stdout
          ▼
Sidecar Python
  ├─ servidor y cola/cancelación
  ├─ Faster-Whisper + CTranslate2
  ├─ FFprobe/PyAV
  ├─ restauración adaptativa + Faster-Whisper + diarización acústica
  ├─ agrupador contextual + análisis/chat semántico local
  ├─ sesiones PCM/WAV en directo y fuentes micrófono/sistema/mixta
  ├─ cola, gestor de modelos, privacidad y paquetes portables
  ├─ exportadores de texto, subtítulos, DOCX, PDF y edición multimedia
  └─ SQLite
          │
          ▼
Archivos y modelos locales
```

Tauri sólo proporciona la ventana, el protocolo seguro para archivos locales y el lanzamiento del sidecar. Su ACL permite ejecutar exclusivamente `binaries/transcriptor-engine serve`; las rutas nunca se concatenan en un comando de shell.

## Decisiones

### Sidecar persistente

Un proceso persistente evita arrancar Python y cargar dependencias para cada operación. Las solicitudes cortas se correlacionan mediante `requestId`; los trabajos largos emiten eventos. El escritor serializa stdout con un bloqueo para que dos hilos nunca mezclen mensajes.

### SQLite en Python

Una sola capa es dueña de la persistencia y evita duplicar migraciones entre Rust y Python. Cada operación abre una conexión corta en modo WAL. Segmentos y palabras están normalizados y se reemplazan dentro de una transacción al guardar.

### Reproducción independiente

El medio se reproduce directamente desde su ruta mediante el protocolo de recursos de Tauri. La transcripción recorre el archivo tan rápido como lo permita el hardware. El frontend localiza el segmento actual con búsqueda binaria y la palabra activa por timestamps.

### FFprobe con fallback

FFprobe es el analizador preferente en las distribuciones completas. PyAV permite analizar y decodificar en desarrollo o si FFprobe no está disponible, manteniendo la función principal sin ejecutar comandos construidos dinámicamente.

## Persistencia

Las tablas son `schema_migrations`, `projects`, `segments`, `words`, `transcription_jobs`, `transcript_versions`, `project_insights`, `assistant_messages`, `job_queue`, `project_markers` y `evidence_events`. Los binarios multimedia nunca se guardan en SQLite. `settings_json` conserva opciones que evolucionan sin alterar cada columna del proyecto.

## Párrafos e inteligencia

Faster-Whisper sigue produciendo fragmentos pequeños para ofrecer progreso y timestamps fiables. Tras la revisión acústica, el agrupador une esos fragmentos según pausa, puntuación, duración, longitud y hablante, conservando todas las palabras originales. El análisis semántico trabaja sobre esos párrafos y guarda únicamente resultados derivados en SQLite. Sus puntos clave siempre incluyen `segmentId` y `startMs` para volver a la evidencia original.

La memoria opcional de hablantes reutiliza embeddings CAM++ locales. SQLite conserva el centroide y una selección limitada de embeddings de alta confianza; en Windows se cifran con DPAPI para la cuenta actual. La UI sólo recibe metadatos de los perfiles, nunca los vectores. El audio original continúa perteneciendo al proyecto y no se duplica dentro del perfil.

## Audio en directo

WebView2 solicita la fuente elegida y el frontend reduce la señal a PCM mono de 16 kHz. Envía bloques Base64 tipados de latencia adaptativa; el motor los escribe primero en una carpeta controlada y después los procesa con un modelo Turbo persistente. Al detener, el PCM se finaliza como WAV y se crea un proyecto SQLite ordinario. Sólo se admite una sesión en directo o un trabajo de archivo simultáneo.

## Identidad de voz local

La diarización utiliza un sistema híbrido. CAM++ produce embeddings temporales de 192 dimensiones desde características log-Mel calculadas con `kaldi-native-fbank`; ONNX Runtime ejecuta el modelo en CPU. En archivos se agrupan las huellas y se suavizan cambios breves. En directo se actualizan centroides efímeros con histéresis. Si el modelo no está instalado o falla, se conserva el comparador espectral anterior como fallback explícito. SQLite guarda la etiqueta y su confianza, pero no una huella reutilizable de la persona.

Los modos Sencillo y Avanzado son capas de configuración, no motores distintos. El modo Sencillo fija una receta validada; el Avanzado expone los mismos parámetros tipados. Esto evita divergencias funcionales entre ambas interfaces.

La separación ligera calcula vectores espectrales por intervención y mantiene como máximo dos centroides durante la sesión. Los vectores no se persisten. Este método minimiza dependencias y latencia, pero no sustituye a una diarización neuronal para voces similares o solapadas.

## Privacidad

- No hay SDK de telemetría ni proveedores cloud.
- La CSP no permite conexiones web generales.
- Los logs del protocolo no incluyen texto transcrito ni argumentos de línea de comandos.
- La descarga de modelos requiere confirmación por modelo.
- Los modelos se descargan desde Hugging Face únicamente tras ese consentimiento.
- El modo profesional ejecuta Turbo con beam 5 y calcula confianza a partir de palabras y probabilidad acústica. Libera Turbo antes de cargar Large-v3 y revisar como máximo el 12 % de los fragmentos más dudosos.
- Antes de retranscribir, SQLite conserva hasta cinco versiones anteriores del texto. Cancelar o fallar restaura la última versión guardada en la interfaz.
