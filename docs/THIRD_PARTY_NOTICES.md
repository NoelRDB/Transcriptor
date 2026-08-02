# Avisos de terceros

El código propio de Transcriptor se distribuye bajo MIT. Las dependencias conservan sus licencias:

- Tauri: Apache-2.0 o MIT.
- React: MIT.
- Zustand: MIT.
- Lucide: ISC.
- Faster-Whisper: MIT.
- CTranslate2: MIT. Las compilaciones posteriores a `v0.1.0` no redistribuyen
  el runtime binario oficial para Windows. El runtime CPU se compila desde la
  fuente fijada de CTranslate2 con CUDA, cuDNN y oneMKL desactivados. La ruta
  CPU usa versiones fijadas de oneDNN y LLVM OpenMP, ambas abiertas. El
  instalador conserva las licencias y avisos de CTranslate2, oneDNN y LLVM,
  además de
  `CTRANSLATE2-OSS-RUNTIME.json`, que registra versiones, commits, opciones de
  compilación, submódulos, tamaños y SHA-256 de cada DLL del runtime.
- oneDNN: Apache-2.0. La compilación CPU usa una versión y commit fijados, y
  conserva `LICENSE` y `THIRD-PARTY-PROGRAMS` junto al marcador del runtime.
- LLVM OpenMP: Apache-2.0 con LLVM exception. `libomp.dll` se construye desde
  una etiqueta y commit fijados y conserva los textos legales de su fuente.
- PyAV: BSD-3-Clause. Faster-Whisper lo declara como dependencia, pero las
  compilaciones actuales de `master` no empaquetan PyAV ni sus bibliotecas
  FFmpeg: Transcriptor decodifica con el FFmpeg LGPL fijado y verificado. La
  Release heredada `v0.1.0` sí contiene el *wheel* binario de PyAV y, con él,
  una compilación FFmpeg que incluye componentes GPL como x264/x265; esa
  Release no es candidata a firma.
- FFmpeg/FFprobe: el perfil puede ser LGPL o GPL según las opciones de
  compilación. Las publicaciones posteriores a `v0.1.0` construyen su propio
  runtime Windows x64 directamente desde el
  [commit `0869e710e6876792fbcebccb536ad620d8e65b97`](https://github.com/FFmpeg/FFmpeg/commit/0869e710e6876792fbcebccb536ad620d8e65b97)
  mediante [`scripts/build-ffmpeg-windows.sh`](../scripts/build-ffmpeg-windows.sh).
  La configuración fijada activa LGPL v3, desactiva GPL, `nonfree`, red,
  autodetección, x264/x265 y todas las bibliotecas externas. Mantiene sólo los
  encoders, muxers y filtros internos necesarios para extraer PCM y editar
  WAV/MP4 con AAC y MPEG-4.

  El artefacto interno contiene exactamente `ffmpeg.exe`, `ffprobe.exe`,
  `LICENSE.txt`, `BUILD-SOURCE.txt`, `GCC-RUNTIME-LICENSES.txt` y
  `MINGW-W64-LICENSES.txt`. Este último par conserva los términos exactos del
  código runtime enlazado estáticamente por el toolchain. `BUILD-SOURCE.txt`
  registra repositorio, commit, configuración, paquetes/versiones GCC y
  MinGW-w64, hashes de esos avisos, DLL de sistema importadas, nombre y SHA-256
  del código fuente correspondiente. Cada Release adjunta
  `Transcriptor-<versión>-FFmpeg-corresponding-source.tar.gz`, que contiene el
  árbol FFmpeg exacto, instrucciones y el script de compilación; su hash debe
  coincidir con `BUILD-SOURCE.txt`. El flujo ejecuta los binarios Windows
  contra medios sintéticos MP3, WAV, M4A, AAC, FLAC, OGG, OPUS, MP4, MOV, MKV,
  AVI, WEBM y M4V, además de comprobar extracción PCM, remuestreo y edición.

  El instalador conserva el `COPYING.LGPLv3` de esa fuente y los textos GNU
  completos versionados
  [`GPL-3.0`](licenses/GPL-3.0.txt) y
  [`LGPL-3.0`](licenses/LGPL-3.0.txt), ya que LGPLv3 incorpora GPLv3. La
  explicación general de licencias de FFmpeg está en su
  [`LICENSE.md`](https://github.com/FFmpeg/FFmpeg/blob/0869e710e6876792fbcebccb536ad620d8e65b97/LICENSE.md).
- GCC runtime usado por MinGW-w64: GPL con GCC Runtime Library Exception. La
  excepción permite distribuir el ejecutable resultante sin convertirlo por
  ello en GPL cuando la compilación cumple sus condiciones. Se conserva el
  `copyright` exacto del paquete que aportó `libgcc`.
- MinGW-w64 CRT: términos permisivos y, según los archivos concretos,
  dedicaciones al dominio público o Zope Public License. Se conserva el
  `copyright` exacto del paquete que aportó el CRT enlazado.
- SQLite: dominio público.
- PyInstaller: GPL-2.0-or-later con excepción para distribuir aplicaciones generadas.
- Runtime Python: el inventario exacto se conserva en
  [`PYTHON-RUNTIME-INVENTORY.json`](licenses/PYTHON-RUNTIME-INVENTORY.json).
  El build copia los avisos desde cada distribución permitida sin aplanar
  rutas, añade los textos ausentes de FlatBuffers, Tokenizers y ONNX Runtime
  desde fuentes fijadas, incluye las licencias de Python y del bootloader de
  PyInstaller y genera `PYTHON-RUNTIME-LICENSES.json` con un SHA-256 por
  archivo. Las licencias y la procedencia del runtime CTranslate2 CPU
  construido por el proyecto se conservan por separado bajo
  `ctranslate2-oss/`. PyAV y las dependencias de desarrollo quedan excluidas.
- python-docx: MIT.
- ReportLab: BSD-3-Clause.
- ONNX Runtime: MIT.
- kaldi-native-fbank: Apache-2.0.
- 3D-Speaker y el modelo CAM++ distribuido por su proyecto: Apache-2.0; conserva la ficha y los avisos del modelo en cada release.
- NVIDIA cuBLAS, cuDNN y CUDA NVRTC:
  - la Release heredada `v0.1.0` sí redistribuye bibliotecas CUDA dentro de sus
    instaladores y continúa disponible públicamente;
  - las compilaciones actuales de `master` y las futuras Releases no las
    incluyen en el repositorio ni en el instalador;
  - en esas versiones posteriores, si el usuario acepta la aceleración NVIDIA,
    la aplicación descarga los paquetes documentados, verifica sus SHA-256 y
    extrae únicamente las DLL necesarias y los textos de licencia exactos que
    acompañan a cada paquete a una carpeta privada.

  Tanto los binarios heredados como una descarga opcional posterior conservan
  los términos de la [licencia del NVIDIA CUDA
  Toolkit](https://docs.nvidia.com/cuda/eula/index.html) y del
  [acuerdo de cuDNN](https://docs.nvidia.com/deeplearning/cudnn/frontend/latest/reference/eula.html).

Este archivo es un inventario técnico, no asesoramiento jurídico. Conserva el informe exacto de dependencias y las opciones de compilación de FFmpeg usadas en cada release.

Los modelos descargados tras instalar no forman parte del binario de Transcriptor. Antes de redistribuir un modelo dentro de una versión futura habrá que conservar su ficha, licencia, atribuciones y condiciones de uso exactas.

## Evaluación para SignPath Foundation

El hecho de que el código propio use MIT no convierte automáticamente todas las
dependencias o redistribuibles en software bajo una licencia aprobada por OSI.
Las condiciones de SignPath Foundation excluyen componentes propietarios salvo
las excepciones que la propia fundación acepte, y prohíben firmar binarios de
terceros como si fueran código del proyecto.

Antes de presentar o completar la solicitud se debe preparar un inventario del
artefacto Windows y clasificar cada archivo como:

- código propio compilable que queda dentro de los instaladores candidatos;
- componente de terceros abierto, con licencia y origen verificables;
- biblioteca de sistema o runtime redistribuible que forme parte del artefacto;
- modelo descargado posteriormente y, por tanto, fuera del instalador;
- componente propietario que debe excluirse o someterse a una decisión expresa
  de SignPath.

La revisión debe prestar atención especial a cuBLAS, cuDNN, otros binarios de
NVIDIA, WebView2, PyInstaller, FFmpeg/FFprobe, CTranslate2, LLVM OpenMP y
cualquier peso de modelo. Los binarios de terceros no recibirán una firma que los identifique
como código propio de Transcriptor. En el diseño actual de `master`, cuBLAS,
cuDNN y las bibliotecas binarias de PyAV quedan fuera del artefacto futuro que
se presentaría a SignPath. CUDA sólo se descarga después si el usuario lo
solicita, con tamaño, progreso, cancelación/reintento y SHA-256 fijado.
El runtime CPU de CTranslate2 se construye desde fuente con componentes
propietarios desactivados, oneDNN y LLVM OpenMP; la auditoría comprueba su
marcador de procedencia, los hashes de todos los DLL y las importaciones PE
antes de aceptar el instalador. Los mensajes diagnósticos negativos que
explican que CUDA o oneMKL no fueron compilados no se confunden con una
dependencia: la comprobación vinculante es el conjunto exacto de DLL, hashes e
importaciones.

La solicitud está pendiente y no hay aprobación. `v0.1.0` se distribuye sin
firma de código, contiene el runtime CUDA heredado y **no es candidata a
firma**. Esta sección no certifica la elegibilidad del paquete futuro;
documenta los asuntos que deben resolverse antes de activar la política
descrita en [Code signing policy](CODE_SIGNING_POLICY.md).
