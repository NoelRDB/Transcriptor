# Empaquetado Windows

## Cadena de construcción

1. `npm ci` instala el frontend fijado por `package-lock.json`.
2. `uv sync --locked` instala Python 3.12 y `uv.lock`.
3. PyInstaller crea un único `transcriptor-engine-<target>.exe`.
4. Tauri incorpora el sidecar y genera instaladores MSI y NSIS.

El usuario final no necesita Python, Node, Rust ni FFmpeg instalados.

## FFmpeg

El repositorio no versiona binarios de FFmpeg. Antes de una distribución oficial hay que obtener una compilación Windows x64 estática compatible con redistribución LGPL que incluya `ffmpeg.exe` y `ffprobe.exe`.

```powershell
.\scripts\stage-ffmpeg.ps1 -ArchivePath C:\descargas\ffmpeg-lgpl-shared.zip
```

El script sólo extrae rutas verificadas dentro de un directorio temporal, copia ambos ejecutables y elimina ese temporal. `build-sidecar.ps1` los incluye dentro del sidecar. Revisa las opciones de compilación del proveedor: una compilación que active componentes GPL cambia las obligaciones de distribución.

Para automatización existe un segundo script que exige HTTPS y una suma SHA-256:

```powershell
.\scripts\fetch-ffmpeg.ps1 `
  -Url https://github.com/BtbN/FFmpeg-Builds/releases/download/<tag-exacto>/ffmpeg-<versión>-win64-lgpl.zip `
  -Sha256 <64-caracteres-hexadecimales>
```

No uses la URL flotante `latest` en una publicación: el contenido puede cambiar sin que cambie la dirección. El flujo de GitHub lee `FFMPEG_ARCHIVE_URL` y `FFMPEG_ARCHIVE_SHA256` de **Settings → Secrets and variables → Actions → Variables** y se detiene si faltan o si la suma no coincide. Además rechaza automáticamente compilaciones que declaren `--enable-gpl` o `--enable-nonfree`.

## Firma

Los instaladores de producción deben firmarse con un certificado de firma de código. La configuración actual genera instaladores sin firma para pruebas internas. No almacenes certificados o contraseñas en el repositorio.

Hasta que se configure la firma, Windows puede mostrar SmartScreen. Esto no impide instalar, pero una publicación dirigida a usuarios no técnicos debería incorporar un certificado antes de anunciarse como estable.

## Comando reproducible

```powershell
npm run package:windows
```

El script se detiene si faltan Rust, Cargo, `uv`, npm o FFmpeg. Ejecuta todas las pruebas antes de compilar Tauri, verifica que Git no contenga datos privados y deja NSIS, MSI y `checksums-SHA256.txt` dentro de `release/`.

## Instalación y datos

- NSIS se instala para la cuenta actual y no necesita privilegios de administrador.
- El instalador incorpora el bootstrapper de WebView2; Windows 10/11 normalmente ya incluye el runtime.
- El sidecar incluye el runtime de Python y FFmpeg.
- CUDA acelera equipos NVIDIA compatibles; si no existe una GPU válida, el motor vuelve a CPU.
- Los modelos Whisper, CAM++ y Ollama no forman parte del instalador principal.
- Proyectos, grabaciones y perfiles se crean después de instalar, dentro del perfil local de cada usuario, y jamás bajo `Program Files` ni dentro del repositorio.

## Modelos

Los modelos Whisper no se incluyen en el instalador. El usuario elige y confirma la primera descarga, ve el nombre del modelo y puede cancelar antes de comenzar. Esto mantiene pequeño el instalador y evita descargas de varios GB sin consentimiento.

Para CUDA se redistribuyen únicamente `cublas64_12.dll`, `cublasLt64_12.dll` y `cudnn64_9.dll`, que son las bibliotecas cargadas por CTranslate2 durante una inferencia Whisper verificada en Windows. El resto de módulos opcionales del paquete NVIDIA no se copia: superaría el límite de NSIS sin intervenir en este flujo. El script falla si falta cualquiera de las tres bibliotecas requeridas.

## macOS y Linux

La arquitectura y el protocolo son portables, pero aún faltan scripts equivalentes, firma/notarización macOS y pruebas de paquetes AppImage/deb. No anuncies soporte oficial hasta completar esas verificaciones.
