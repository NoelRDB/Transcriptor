# Avisos de terceros

El código propio de Transcriptor se distribuye bajo MIT. Las dependencias conservan sus licencias:

- Tauri: Apache-2.0 o MIT.
- React: MIT.
- Zustand: MIT.
- Lucide: ISC.
- Faster-Whisper: MIT.
- CTranslate2: MIT.
- PyAV: BSD-3-Clause; enlaza con bibliotecas FFmpeg.
- FFmpeg/FFprobe: LGPL-2.1-or-later o GPL según opciones de compilación. Las publicaciones oficiales de Transcriptor deben usar la variante `lgpl` sin `--enable-gpl` ni `--enable-nonfree`. La configuración actual usa `--enable-version3`, por lo que se aplican los términos LGPL-3.0-or-later. El código fuente correspondiente y los textos oficiales están disponibles en [ffmpeg.org](https://ffmpeg.org/) y en el [repositorio de FFmpeg](https://github.com/FFmpeg/FFmpeg).
- SQLite: dominio público.
- PyInstaller: GPL-2.0-or-later con excepción para distribuir aplicaciones generadas.
- python-docx: MIT.
- ReportLab: BSD-3-Clause.
- ONNX Runtime: MIT.
- kaldi-native-fbank: Apache-2.0.
- 3D-Speaker y el modelo CAM++ distribuido por su proyecto: Apache-2.0; conserva la ficha y los avisos del modelo en cada release.
- NVIDIA cuBLAS y cuDNN: sujetos a los términos de redistribución del NVIDIA CUDA Toolkit y cuDNN incluidos con la versión distribuida.

Este archivo es un inventario técnico, no asesoramiento jurídico. Conserva el informe exacto de dependencias y las opciones de compilación de FFmpeg usadas en cada release.

Los modelos descargados tras instalar no forman parte del binario de Transcriptor. Antes de redistribuir un modelo dentro de una versión futura habrá que conservar su ficha, licencia, atribuciones y condiciones de uso exactas.
