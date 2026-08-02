# Empaquetado Windows

## Cadena de construcción

1. `npm ci` instala el frontend fijado por `package-lock.json`.
2. `uv sync --locked` instala Python 3.12 y `uv.lock`.
3. PyInstaller crea un único `transcriptor-engine-<target>.exe`.
4. Tauri incorpora el sidecar y genera instaladores MSI y NSIS.

El usuario final no necesita Python, Node, Rust ni FFmpeg instalados.

## FFmpeg

El repositorio no versiona binarios. El workflow construye FFmpeg y FFprobe
para Windows x64 desde el commit exacto
`0869e710e6876792fbcebccb536ad620d8e65b97` con MinGW-w64 en Ubuntu 24.04:

```bash
sudo apt-get update
sudo apt-get install --no-install-recommends \
  ffmpeg git mingw-w64 make nasm pkg-config zip
version="$(node -p "require('./package.json').version")"
bash scripts/build-ffmpeg-windows.sh build/ffmpeg "$version"
```

La configuración desactiva autodetección, red, GPL, `nonfree`, x264/x265 y
bibliotecas externas. Conserva los decodificadores/demuxers internos y habilita
explícitamente PCM S16LE, AAC, MPEG-4, WAV/MP4 y los filtros usados por la
edición. El script audita las DLL importadas y genera exactamente:

- `ffmpeg-runtime-windows-x64.zip`, con `ffmpeg.exe`, `ffprobe.exe`,
  `LICENSE.txt`, `BUILD-SOURCE.txt`, `GCC-RUNTIME-LICENSES.txt` y
  `MINGW-W64-LICENSES.txt`;
- `Transcriptor-<versión>-FFmpeg-corresponding-source.tar.gz`, con el árbol
  FFmpeg exacto, instrucciones y el propio script de compilación.

`BUILD-SOURCE.txt` liga ambos artefactos mediante el nombre y SHA-256 del
código fuente correspondiente. El workflow comprueba ese hash antes de
publicar y adjunta el `.tar.gz` a la misma Release que los instaladores.

En Windows, el ZIP interno se prepara así:

```powershell
.\scripts\stage-ffmpeg.ps1 `
  -ArchivePath .\build\ffmpeg\ffmpeg-runtime-windows-x64.zip
```

El script rechaza cualquier ZIP que no tenga esas seis entradas raíz exactas,
limita sus tamaños, valida LGPL v3, la GCC Runtime Library Exception, los
términos CRT de MinGW-w64 y el manifiesto de fuente y sólo
entonces copia el runtime a `sidecar\ffmpeg`. No usa rutas internas del ZIP
como destinos.

La CI genera medios sintéticos y ejecuta el binario Windows contra MP3, WAV,
M4A, AAC, FLAC, OGG, OPUS, MP4, MOV, MKV, AVI, WEBM y M4V. También prueba el
comando real de extracción PCM mono a 16 kHz y la edición con remuestreo,
`trim`/`atrim`, `setpts`/`asetpts`, `concat`, MPEG-4, AAC, WAV y MP4.

## Runtime CTranslate2 CPU

El sidecar incorpora CTranslate2 4.8.1 desde el entorno reproducible fijado por
`uv.lock`. El runtime Windows de esa distribución necesita Intel OpenMP, por lo
que se empaqueta `libiomp5md.dll` junto con el texto completo de la Intel
Simplified Software License. CUDA, cuDNN y cuBLAS no forman parte del sidecar
ni del instalador base.

`build-sidecar.ps1` crea un ejecutable autocontenido con PyInstaller y copia el
inventario y las licencias del runtime. `verify-release.ps1` comprueba esos
archivos tanto en el árbol de preparación como en el contenido del ejecutable,
rechaza bibliotecas CUDA y bloquea la publicación si faltan avisos o si el
inventario no coincide. La aceleración NVIDIA es una instalación opcional
posterior, separada del instalador CPU y solicitada expresamente por el usuario.

`build-sidecar.ps1` incorpora los ejecutables y recopila los avisos mediante
`collect-runtime-licenses.ps1`. El inventario cerrado impide incluir PyAV o
dependencias de desarrollo; las rutas se conservan para evitar colisiones y
`PYTHON-RUNTIME-LICENSES.json` registra cada SHA-256. Además se empaquetan
GPL-3.0, LGPL-3.0, el aviso FFmpeg, su manifiesto de fuente, las licencias del
runtime GCC/MinGW-w64 y la licencia del runtime Intel OpenMP.
`verify-release.ps1`
exige que inventario, archivos y hashes coincidan antes de construir
instaladores.

## Firma

La Release pública `v0.1.0` se generó sin firma y conserva CUDA dentro de sus
instaladores heredados; no es candidata a una firma retroactiva. La
configuración actual de `master` prepara una futura candidata sin CUDA
embebido, pero seguirá siendo no firmada hasta que SignPath Foundation apruebe
el proyecto y se verifique una integración real. No almacenes certificados o
contraseñas en el repositorio.

Hasta que se configure la firma, Windows puede mostrar SmartScreen. Esto no impide instalar, pero una publicación dirigida a usuarios no técnicos debería incorporar un certificado antes de anunciarse como estable.

## Comando reproducible

```powershell
npm run package:windows
```

El script se detiene si faltan Rust, Cargo, `uv`, npm o FFmpeg. Ejecuta todas las pruebas antes de compilar Tauri, verifica que Git no contenga datos privados y deja NSIS, MSI y `checksums-SHA256.txt` dentro de `release/`.

El workflow genera una atestación Sigstore de GitHub para cada uno de los cinco
assets finales, después de validar sus hashes y antes de publicar la Release:

```powershell
gh attestation verify <archivo> -R NoelRDB/Transcriptor
```

La atestación acredita procedencia de GitHub Actions. Complementa las sumas y
la firma futura de SignPath, pero no sustituye Authenticode ni SmartScreen.

## Instalación y datos

- NSIS se instala para la cuenta actual y no necesita privilegios de administrador.
- Windows 10/11 normalmente ya incluye WebView2. El modo de Tauri es `skip`: el
  instalador no contiene ni descarga el bootstrapper. Si falta el runtime, el
  usuario debe instalarlo desde la
  [página oficial de Microsoft](https://developer.microsoft.com/microsoft-edge/webview2/)
  antes de abrir Transcriptor.
- El sidecar incluye el runtime de Python y FFmpeg.
- `v0.1.0` sí redistribuye bibliotecas CUDA dentro de sus instaladores
  heredados. Las compilaciones posteriores las excluyen; si no se descargan o
  no están disponibles, el motor vuelve a CPU.
- Los textos de licencia de las dependencias que sí se redistribuyen se recopilan desde las versiones fijadas y se incluyen dentro del instalador.
- Los modelos Whisper, CAM++ y Ollama no forman parte del instalador principal.
  En compilaciones posteriores a `v0.1.0`, Whisper, CAM++ y el runtime CUDA
  opcional se preparan desde la propia interfaz con confirmación, tamaño y
  progreso.
- Proyectos, grabaciones y perfiles se crean después de instalar, dentro del perfil local de cada usuario, y jamás bajo `Program Files` ni dentro del repositorio.

## Modelos

Los modelos Whisper no se incluyen dentro del `.exe` o `.msi`. El usuario elige y confirma la primera descarga desde la propia aplicación, ve el nombre, el espacio requerido y el progreso, y puede cancelar antes de comenzar. No necesita Git, Python ni una consola.

Esta separación es necesaria: Turbo ocupa aproximadamente 1,6 GiB, Large-v3 3,1 GiB y el modelo Qwen recomendado por Ollama alrededor de 6,6 GB. Incluirlos todos convertiría la descarga inicial en más de 11 GB; además, Large-v3 junto al runtime superaría el límite de 2 GiB por archivo de GitHub Releases. Los pesos conservan también sus propias fichas y condiciones de licencia. Por esas razones el instalador contiene el gestor de modelos, no los pesos de todos los modelos.

Esta separación CUDA se aplica a `master` y a las compilaciones posteriores a
`v0.1.0`; no describe el instalador heredado, que sí incorpora las bibliotecas.
En las nuevas compilaciones, el instalador incluye únicamente el gestor, no
bibliotecas de NVIDIA. Cuando se detecta una GPU NVIDIA sin runtime, la
interfaz solicita un consentimiento separado y muestra la descarga real. El
gestor obtiene las ruedas Windows x64 de
`nvidia-cublas-cu12==12.9.2.10` y
`nvidia-cudnn-cu12==9.25.0.15`, además de su dependencia
`nvidia-cuda-nvrtc-cu12==12.9.86`, desde PyPI mediante URLs fijadas. Verifica
sus SHA-256 y extrae una lista cerrada con cuBLAS, todas las subbibliotecas de
cuDNN 9 necesarias y NVRTC, más los textos de licencia exactos de los tres paquetes,
en `%LOCALAPPDATA%\TranscriptorData\runtime\cuda`. La activación es atómica, los
temporales se eliminan al completar o cancelar y una instalación anterior sigue
siendo válida.

Para las nuevas compilaciones, `verify-release.ps1` comprueba que la
configuración pública no incluya el directorio CUDA y bloquea cualquier
artefacto que alcance el límite de 2 GiB de GitHub. Esa comprobación no cambia
el contenido histórico de `v0.1.0`.

## macOS y Linux

La arquitectura y el protocolo son portables, pero aún faltan scripts equivalentes, firma/notarización macOS y pruebas de paquetes AppImage/deb. No anuncies soporte oficial hasta completar esas verificaciones.
