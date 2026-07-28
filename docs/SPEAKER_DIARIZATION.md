# Separación de hablantes

## Objetivo

Transcriptor ofrece dos niveles de uso sobre el mismo motor local:

- **Sencillo:** activa la configuración recomendada: CAM++, dos hablantes, sensibilidad 55, latencia equilibrada, revisión profesional y asignación automática de CPU/GPU.
- **Avanzado:** permite elegir número de voces, sensibilidad, nombres visibles, latencia del directo, calidad y recursos del motor.

La aplicación no conoce por sí sola la identidad civil de una persona. `Hablante 1` y `Hablante 2` son agrupaciones acústicas. Si el usuario activa explícitamente **Memoria local de voces**, puede renombrarlas y reutilizar esos nombres en otras conversaciones.

## Motor híbrido implementado

1. Faster-Whisper detecta palabras y tiempos.
2. Las intervenciones largas se dividen en unidades vocales de aproximadamente 1–3 segundos.
3. `kaldi-native-fbank` obtiene 80 bandas log-Mel a 16 kHz.
4. CAM++ de 3D-Speaker genera una huella neuronal normalizada de 192 dimensiones.
5. El modo de archivo agrupa las huellas y suaviza cambios breves de baja confianza.
6. El modo en directo mantiene centroides de sesión y usa histéresis para que una misma voz no cambie de etiqueta continuamente.
7. Con la memoria activada, los centroides se comparan de forma conservadora contra los perfiles conocidos y se exige un umbral mínimo y margen frente a otras voces.
8. Sólo los fragmentos claros superan el filtro de aprendizaje incremental; un perfil conserva como máximo 80 embeddings.
9. Si CAM++ falta o no puede cargarse, se usa el comparador acústico compatible y se informa en pantalla.

El modelo CAM++ ocupa aproximadamente 27 MiB, se descarga sólo después de una confirmación y se verifica mediante SHA-256. El audio no se sube. La memoria de voces está desactivada inicialmente y requiere una confirmación independiente. En Windows, los embeddings de 192 dimensiones se cifran con DPAPI para la cuenta del usuario; no se copian recortes de audio ni texto al perfil.

## Memoria local de voces

En **Ajustes → Hablantes conocidos** se puede:

- activar o desactivar globalmente el reconocimiento persistente;
- renombrar `Hablante 1`, `Hablante 2`, etc.;
- ver fragmentos aprendidos, duración acumulada, última coincidencia y fiabilidad;
- pausar un perfil sin borrarlo;
- ajustar su umbral en modo avanzado;
- comparar dos perfiles y fusionar duplicados conservando el nombre, color y ajustes del perfil de destino;
- desactivar el aprendizaje manteniendo el reconocimiento;
- olvidar por completo una voz.

Los nombres se asignan a las coincidencias del modelo, no a una identidad inferida. Al borrar un perfil se eliminan sus embeddings cifrados, pero las transcripciones históricas conservan el texto y el nombre que ya tenían.

La fusión no se ejecuta automáticamente: primero calcula la similitud real entre los centroides acústicos y muestra una valoración, y después exige confirmación. Las muestras cifradas del perfil de origen se deduplican y se incorporan al destino, su centroide se vuelve a calcular y los segmentos vinculados pasan a utilizar el perfil y el nombre de destino. El perfil de origen se elimina únicamente al completar toda la operación dentro de una transacción.

En un equipo con GPU CUDA, Whisper puede transcribir con la GPU mientras CAM++ analiza las voces con CPU mediante ONNX Runtime. Esto permite usar ambos recursos sin competir por la VRAM principal.

## Progreso y latencia

La fase de voces informa del número real de unidades completadas, total, porcentaje, tiempo transcurrido, estimación restante y backend activo. No se inventa progreso mediante una animación.

Perfiles del directo:

- **Ultrabajo:** bloques de 0,58–1,05 s; respuesta más rápida, menos contexto por bloque.
- **Equilibrado:** bloques de 0,78–1,45 s; opción recomendada.
- **Estable:** bloques de 1,10–2,15 s; más contexto en ruido o frases difíciles.

La latencia observada incluye captura, cola y tiempo de inferencia; depende del equipo y no puede garantizarse únicamente con el tamaño del bloque.

## Camino de máxima precisión

CAM++ es la base ligera adecuada para el instalador. Para reuniones con voces solapadas o más de dos personas, la futura opción de máxima precisión podrá integrar pyannote Community-1. Esa variante no se activa silenciosamente: requiere aceptar las condiciones del modelo, configurar credenciales de Hugging Face y asumir una instalación basada en PyTorch mucho mayor.

## Prompt de evolución

```text
Actúa como arquitecto y desarrollador senior de Transcriptor. Conserva el trabajo existente y mejora la diarización sin romper la transcripción, reproducción, edición, persistencia ni exportación.

Mantén dos experiencias sobre el mismo motor:
1. Modo Sencillo: valores recomendados, dos hablantes exactos, CAM++ local, sensibilidad equilibrada, latencia equilibrada, CPU/GPU automáticas y mensajes comprensibles.
2. Modo Avanzado: número exacto o automático de hablantes, sensibilidad, nombres, perfiles de latencia, dispositivo, calidad y revisión final.

Los perfiles de voz reutilizables ya implementados deben seguir tratándose como datos biométricos sensibles:
- conserva el consentimiento separado de “separar hablantes”;
- guarda sólo embeddings cifrados localmente, nunca copias de audio por defecto;
- permite ver, renombrar, pausar y eliminar cada perfil;
- exige umbral, margen de decisión y fragmentos claros antes de aprender;
- no actives identificación persistente al seleccionar únicamente “separar hablantes”.

Para archivos:
- usa timestamps de Faster-Whisper;
- crea unidades de voz de 1–3 s sin cortar palabras;
- genera embeddings CAM++ de 192 dimensiones mediante ONNX Runtime;
- agrupa, alinea y suaviza cambios breves de baja confianza;
- conserva speakerConfidence y permite corregir etiquetas;
- informa progreso real como unidades procesadas / total y calcula la ETA con tiempo medido.

Para directo:
- captura PCM mono de 16 kHz;
- ofrece perfiles ultrabajo, equilibrado y estable;
- mantén centroides por sesión con histéresis y compáralos con los perfiles consentidos;
- muestra texto provisional, confianza, backend, cola y latencia real;
- guarda el WAV y permite una revisión final completa al detener.

Privacidad:
- procesamiento local por defecto;
- consentimiento antes de descargar modelos;
- verificación SHA-256;
- no guardar huellas reutilizables sin consentimiento ni registrar texto/audio;
- fallback explícito al motor acústico si la IA no está disponible.

No afirmes que el sistema conoce la identidad real. Para pyannote Community-1, explica primero licencia, credenciales, tamaño y consecuencias de empaquetado. No marques el trabajo como terminado hasta ejecutar lint, tipos, pruebas de clustering y un flujo real con audio local.
```
