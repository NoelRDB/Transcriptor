# Historial de cambios

Todos los cambios relevantes se documentan aquí. El proyecto sigue versionado semántico mientras la API y el formato de datos evolucionan.

## [0.1.1] - 2026-08-03

### Añadido

- Acceso **Mostrar en carpeta** en cada proyecto reciente para localizar su
  audio o vídeo original desde la pantalla principal.
- Caché local de proyectos recientes para conservar el contenido visible
  mientras el motor se inicia y actualiza el historial en segundo plano.
- Prueba del motor CAM++ realmente empaquetado antes de aceptar una publicación.

### Cambiado

- Arranque y apertura de proyectos optimizados: los proyectos guardados evitan
  análisis multimedia redundantes y las voces se precargan después del primer
  contenido visible.
- Carga de proyectos grandes reducida a una sola consulta de palabras, con una
  ruta rápida para texto ASCII que evita reparaciones Unicode innecesarias.
- Verificación completa de CUDA almacenada durante la sesión para no repetir
  comprobaciones costosas antes de cada transcripción.
- Ajustes separa los estados de hardware, CUDA, modelos, CAM++ y Ollama para
  evitar refrescos globales y mensajes incorrectos de instalación.
- La grabadora detecta dispositivos y permisos en paralelo para estar lista
  antes y conservar mensajes de error específicos por fuente.
- El sidecar pasa a un runtime `onedir`, verificable y compartido por todas las
  operaciones, en lugar de extraerse de nuevo en cada ejecución.
- Candidata pública limpia para la evaluación de firma gratuita de SignPath.
- CUDA deja de formar parte del instalador y pasa a ser una descarga opcional,
  separada, consentida, verificable y con fallback completo a CPU.
- El runtime CPU de CTranslate2 4.8.1 procede del entorno fijado por `uv.lock`;
  su inventario, la licencia de Intel OpenMP y la ausencia de bibliotecas CUDA
  se auditan antes de publicar.
- PyAV y su FFmpeg GPL heredado dejan de empaquetarse; la decodificación usa el
  FFmpeg LGPL fijado, con fuentes, licencias y avisos reproducibles.
- WebView2 pasa a ser un requisito del sistema: el instalador no incorpora ni
  descarga su bootstrapper; si falta, se obtiene manualmente desde Microsoft.
- La preparación de NVIDIA conserva las licencias exactas de cuBLAS y cuDNN y
  nunca mezcla bibliotecas procedentes de instalaciones distintas.
- Publicación fail-closed: una candidata sin firma para evaluación y releases
  posteriores bloqueadas hasta verificar Authenticode de SignPath Foundation.
- Atestaciones Sigstore de procedencia de GitHub para los cinco assets finales,
  verificables sin sustituir Authenticode ni SmartScreen.

## [0.1.0] - 2026-07-28

### Añadido

- Aplicación Tauri para Windows con reproductor y transcripción local sincronizada.
- Faster-Whisper con CPU, CUDA, progreso real, cancelación y revisión inteligente.
- Asistente de primer inicio para instalar Turbo, Large-v3 y CAM++ según la memoria
  y el espacio disponible, con consentimiento, progreso e integridad verificable.
- Edición, proyectos persistentes, exportadores y recuperación.
- Grabación en directo, diarización local y memoria opcional de perfiles de voz.
- Comparación acústica y fusión segura de perfiles de voz duplicados, conservando muestras y reasignando sus fragmentos.
- Análisis local con Ollama, cola de trabajos y gestor de modelos.
- Instaladores NSIS/MSI autocontenidos.
- Auditoría de privacidad, licencias, tamaños y publicación automatizada mediante
  GitHub Releases.
