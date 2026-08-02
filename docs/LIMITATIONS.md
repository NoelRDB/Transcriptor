# Limitaciones conocidas

- La grabadora captura audio y muestra su nivel, pero no ofrece texto provisional. La separación CAM++ y el reconocimiento de perfiles se ejecutan después al pulsar **Transcribir**, con el archivo completo disponible.
- La cancelación se comprueba entre segmentos. Una ventana de inferencia ya iniciada puede tardar unos segundos en terminar.
- El progreso de descarga usa los tamaños reales publicados por el repositorio. Si el servidor no entrega esos metadatos, muestra bytes descargados sin inventar un porcentaje.
- La selección de pista en medios con varias pistas se detecta, pero todavía utiliza la pista predeterminada.
- La búsqueda, reemplazo global, división y unión visual de segmentos están disponibles. Los cambios estructurales conservan historial de deshacer/rehacer durante la sesión.
- La lista usa `content-visibility` para archivos largos. Una virtualización con medición completa queda en fase 2.
- El gestor permite listar, descargar y eliminar modelos. Hugging Face no garantiza una reanudación granular en todos los ficheros; cancelar es seguro, pero una descarga ya iniciada puede necesitar reiniciarse.
- La Release heredada `v0.1.0` incluye bibliotecas CUDA dentro del instalador y
  sigue descargable. La preparación CUDA opcional sólo describe `master` y las
  versiones posteriores: aparece con una GPU NVIDIA detectada, descarga
  aproximadamente 1,27 GiB, exige 6 GiB libres durante la instalación y verifica
  cada paquete antes de activarlo. Si se cancela, falla el controlador o no hay
  espacio, conserva lo anterior y continúa por CPU. Un reintento comienza de
  nuevo el paquete interrumpido.
- Si un archivo se mueve, el diagnóstico busca candidatos de igual nombre en carpetas controladas del usuario y permite relocalizarlo; no realiza búsquedas indiscriminadas por todo el disco.
- DOCX, PDF, cola persistente y paquetes portables están incluidos. La forma de onda, traducción y actualizaciones automáticas continúan fuera de esta entrega.
- La búsqueda semántica usa expansión local con Qwen cuando está disponible y vuelve a búsqueda léxica si Ollama no responde. No descarga silenciosamente un modelo de embeddings adicional.
- La diarización de archivo usa embeddings neuronales CAM++ y es privada, orientada a una o dos voces. Para conversaciones con solapamientos o más de dos hablantes sigue siendo necesaria una integración opcional más pesada, como pyannote Community-1.
- Los perfiles de voz reducen trabajo manual, pero no son una prueba de identidad. Ruido, micrófonos muy distintos, voces extremadamente parecidas o habla simultánea pueden producir una coincidencia dudosa; por eso el aprendizaje usa umbrales conservadores y siempre se puede corregir o pausar.
- El “modo evidencia” registra actividad y hashes del paquete, pero no equivale por sí solo a una cadena de custodia pericial certificada.
- El análisis profundo depende de Ollama y `qwen3.5:9b` instalados localmente. Puede equivocarse aunque use
  evidencias temporales; nunca debe confundirse un marcador lingüístico con un diagnóstico de las personas.
  El modo extractivo rápido continúa disponible si el modelo no está iniciado.
- macOS y Linux no se han empaquetado ni verificado todavía.
- La primera distribución oficial `v0.1.0` sólo cubre Windows 10/11 x64,
  incorpora CUDA para NVIDIA compatible y usa fallback a CPU. Las próximas
  versiones separan el runtime NVIDIA del instalador.
- `v0.1.0` y los instaladores de desarrollo actuales no están firmados.
  SmartScreen puede advertir que el editor es desconocido. `v0.1.0`, además de
  contener CUDA, no es candidata a recibir una firma retroactiva.
