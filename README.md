# Transcriptor

Aplicación de escritorio para transcribir audio y vídeo localmente, reproducir el medio y editar el texto sincronizado por segmento o palabra. El MVP prioriza Windows 10/11 y no envía medios, transcripciones ni telemetría a internet.

## Descargar e instalar

Las versiones públicas se publican en la sección **Releases** del repositorio. Para Windows 10/11 x64:

1. Descarga `Transcriptor_<versión>_x64-setup.exe` — es la opción recomendada.
2. Ejecuta el instalador. No requiere Python, Node.js, Rust, FFmpeg ni CUDA instalados.
3. En el primer uso, elige qué modelo de reconocimiento quieres descargar. Ningún modelo de varios GB se descarga sin confirmación.

También se publica un `.msi` para despliegues administrados y `checksums-SHA256.txt` para comprobar la integridad. Mientras los instaladores no tengan firma de código, Windows SmartScreen puede mostrar una advertencia de editor desconocido; comprueba la suma SHA-256 y descarga exclusivamente desde **Releases**.

El instalador contiene la aplicación y sus motores, pero **nunca** contiene grabaciones, transcripciones, proyectos, perfiles de voz o modelos de otro usuario.

## Estado del MVP

Incluido:

- Interfaz Tauri 2 + React 19 + TypeScript.
- Reproductor de audio/vídeo con velocidad, volumen, saltos, atajos y pantalla completa.
- Panel redimensionable y responsive con sincronización, autoseguimiento, modo de lectura, búsqueda, edición y deshacer/rehacer.
- Sidecar Python JSONL con Faster-Whisper, VAD, timestamps por palabra, confianza acústica y fallback CUDA → CPU.
- Tres modos de IA local: Turbo por lotes, Turbo preciso con revisión selectiva Large-v3 y Large-v3 completo.
- Análisis con FFprobe y fallback PyAV.
- Progreso basado en tiempo realmente procesado, descarga medida en bytes y cancelación cooperativa.
- Proyectos SQLite con migraciones, versiones de recuperación, guardado automático y posición de reproducción.
- Párrafos contextuales que conservan todas las palabras y timestamps; también pueden aplicarse a proyectos existentes.
- Centro de inteligencia local con análisis profundo Qwen 3.5, puntos trazables, capítulos, señales y mapa conceptual.
- Grabación y transcripción de micrófono en directo por bloques de latencia configurable, guardada automáticamente como WAV local.
- Modos Sencillo y Avanzado: valores recomendados o control de voces, latencia, calidad y recursos.
- Separación neuronal local de dos hablantes con CAM++, confianza por intervención y perfiles de voz opcionales cifrados.
- Separación acústica ligera entre Hablante 1 y Hablante 2, con reasignación manual desde el editor.
- Diccionario personal que incorpora correcciones al vocabulario de las siguientes transcripciones.
- Exportación TXT, SRT, WebVTT y CSV con firma UTF-8 para Windows; JSON estructurado en UTF-8 estándar.
- Exportación DOCX y PDF, variantes anonimizadas y paquetes portables `.transcriptor` con verificación SHA-256.
- Centro de operaciones con cola persistente, gestor de modelos, búsqueda semántica local, versiones, marcadores y detector de datos sensibles.
- Restauración adaptativa de voz, diarización local opcional y creación de una copia de audio/vídeo omitiendo fragmentos seleccionados.
- Chat local con la transcripción, extractores especializados y respuestas ancladas a instantes verificables.
- Captura en directo desde micrófono, audio del sistema o mezcla, con idioma fijado por el usuario y marcadores durante la grabación.
- Consentimiento antes de descargar cada modelo.
- Tema claro/oscuro/sistema y navegación esencial con teclado.
- Instaladores NSIS/MSI configurados para Windows.

El laboratorio de IA muestra qué módulos avanzados están activos y cuáles requieren modelos o permisos adicionales. La forma de onda, traducción y actualizaciones automáticas quedan para fases posteriores. Consulta [limitaciones](docs/LIMITATIONS.md).

## Inteligencia local

El botón **Analizar** abre una vista con resumen, puntos clave, capítulos y mapa conceptual. El modo
**Profundo** usa Ollama y `qwen3.5:9b` en el propio ordenador: estudia bloques temporales completos y
realiza una segunda pasada de síntesis global. Cada punto conserva un instante verificable y la interfaz
muestra progreso basado en bloques realmente terminados. El audio y el texto nunca salen del equipo.

El modo **Rápido** mantiene el motor extractivo determinista como alternativa sin LLM. Comprende menos
contexto y se identifica expresamente como análisis rápido. En modo conversación, ambos métodos evitan
presentar indicios lingüísticos como diagnósticos sobre las personas.

```powershell
# Comprobar la IA local
ollama --version
ollama list

# Preparar otro equipo (descarga aproximada: 6,6 GB)
ollama pull qwen3.5:9b
```

Ollama guarda sus modelos por defecto en `%USERPROFILE%\.ollama\models`. La descarga sólo debe hacerse
con consentimiento explícito del usuario.

## Modos de calidad

- **Instantáneo — Turbo por lotes:** máxima velocidad. En la RTX 3070 Laptop probada alcanza aproximadamente 44× sobre voz española limpia.
- **Profesional — Turbo + Large-v3:** Turbo preciso transcribe todo y Large-v3 vuelve a escuchar sólo los fragmentos con baja confianza. Es el modo recomendado.
- **Máxima precisión — Large-v3:** utiliza Large-v3 para todo. Consume más tiempo y VRAM; no siempre mejora una grabación limpia.

Las cifras dependen del ruido, duración, temperatura, energía disponible y tipo de voz. La aplicación muestra velocidad y uso reales durante cada trabajo.

## Requisitos de desarrollo

- Windows 10 u 11 con WebView2.
- Node.js 18.20 o posterior.
- Rust estable con el toolchain MSVC y Visual Studio Build Tools C++.
- `uv`.
- Python 3.12, gestionado automáticamente por `uv`.

## Puesta en marcha

```powershell
npm install
uv sync --project sidecar --extra dev
npm run sidecar:build
npm run tauri dev
```

La vista del frontend se puede abrir sin Rust con `npm run dev`. Permite revisar la interfaz y reproducir un archivo, pero la transcripción real sólo se habilita dentro de Tauri.

## Comprobaciones

```powershell
npm run lint
npm run test
npm run build
npm run sidecar:test
```

Comprobación completa:

```powershell
npm run check
```

## Crear instaladores Windows

Para distribuir todos los formatos sin instalaciones manuales en el equipo del usuario final, prepara una compilación redistribuible LGPL de FFmpeg/FFprobe y ejecuta:

```powershell
.\scripts\stage-ffmpeg.ps1 -ArchivePath C:\ruta\ffmpeg-lgpl-shared.zip
npm run package:windows
```

Los instaladores se generan bajo `src-tauri\target\release\bundle`. Lee primero [empaquetado y licencias](docs/PACKAGING.md).

El comando también copia los artefactos finales y sus sumas SHA-256 a `release/`. Esa carpeta es local y está excluida de Git.

## Datos locales

En Windows se utilizan estas ubicaciones:

- Proyectos: `%LOCALAPPDATA%\Transcriptor\transcriptor.sqlite3`
- Modelos: `%LOCALAPPDATA%\Transcriptor\models`
- Modelo contextual Qwen/Ollama: `%USERPROFILE%\.ollama\models`
- Grabaciones: `%LOCALAPPDATA%\Transcriptor\recordings`
- Registros técnicos: `%LOCALAPPDATA%\Transcriptor\logs`
- Paquetes importados: `%LOCALAPPDATA%\Transcriptor\imports`
- Temporales de PyInstaller: gestionados por el sistema durante la ejecución del sidecar.

Los archivos originales no se copian a la base de datos. El proyecto conserva su ruta para reproducirlos de nuevo.
Cada cuenta de Windows recibe su propio `%LOCALAPPDATA%`: los proyectos de dos usuarios o dos ordenadores no se enlazan entre sí. Desinstalar la aplicación no borra silenciosamente los proyectos personales. Consulta la [política de privacidad local](docs/PRIVACY.md).

## Grabación en directo

Pulsa **En directo**, elige micrófono, audio del sistema o una mezcla y comienza a hablar. La aplicación convierte el audio a PCM mono de 16 kHz, guarda cada bloque localmente antes de transcribirlo y muestra resultados provisionales. El perfil equilibrado usa bloques aproximados de 0,8–1,5 segundos y el perfil ultrabajo puede reducirlos a 0,6–1,1 segundos. El idioma queda fijado por el usuario. Al detener, finaliza un WAV reproducible y crea un proyecto normal que se puede editar, analizar y exportar.

La separación de dos hablantes incluida es neuronal y privada: CAM++ genera huellas acústicas de 192 dimensiones y el motor aplica histéresis para estabilizar las etiquetas. La memoria reutilizable está desactivada inicialmente; al activarla con consentimiento, Windows cifra los embeddings con DPAPI, aprende únicamente de fragmentos claros y permite renombrar, pausar o borrar cada voz desde Ajustes. No guarda copias de audio en los perfiles. Si el modelo opcional de unos 27 MiB no está instalado, vuelve al comparador acústico compatible. Consulta [la arquitectura de diarización y los perfiles de voz](docs/SPEAKER_DIARIZATION.md).

## Atajos

- `Espacio`: reproducir/pausar.
- `←` / `→`: retroceder/avanzar el intervalo configurado.
- `Enter` o `Espacio` sobre un fragmento: saltar a su inicio.
- `Ctrl+Enter` mientras se edita: aplicar el cambio.
- `Esc` mientras se edita: cancelar.
- Flechas sobre el divisor: ajustar el ancho de los paneles.
- Botón de ampliar en el panel derecho: ocultar o recuperar temporalmente el reproductor.

## Documentación

- [Arquitectura](docs/ARCHITECTURE.md)
- [Protocolo frontend–sidecar](docs/PROTOCOL.md)
- [Empaquetado](docs/PACKAGING.md)
- [Publicación de versiones](docs/RELEASING.md)
- [Privacidad y datos locales](docs/PRIVACY.md)
- [Limitaciones](docs/LIMITATIONS.md)
- [Avisos de terceros](docs/THIRD_PARTY_NOTICES.md)
- [Seguridad](SECURITY.md)

## Licencia

El código propio de Transcriptor se distribuye bajo la [licencia MIT](LICENSE). Los motores, bibliotecas y modelos de terceros conservan sus licencias y condiciones respectivas.
