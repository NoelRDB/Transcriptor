# Publicar una versión en GitHub

## Una sola vez por repositorio

1. Crea o enlaza un repositorio público de GitHub.
2. Activa GitHub Actions.
3. En **Settings → Secrets and variables → Actions → Variables** define:
   - `FFMPEG_ARCHIVE_URL`: URL HTTPS de una versión exacta `win64-lgpl`, nunca `latest`.
   - `FFMPEG_ARCHIVE_SHA256`: suma SHA-256 de ese ZIP.
4. Configura un certificado de firma de código antes de una versión estable destinada a usuarios no técnicos. No guardes el `.pfx` ni su contraseña en Git.

## Preparar la versión

La misma versión debe aparecer en:

- `package.json`;
- `src-tauri/tauri.conf.json`;
- `src-tauri/Cargo.toml`;
- `sidecar/pyproject.toml`.

Después ejecuta:

```powershell
npm ci
uv sync --project sidecar --extra dev --locked
npm run release:verify
npm run check
```

Añade las novedades a `CHANGELOG.md`, revisa `docs/THIRD_PARTY_NOTICES.md` y confirma que la variante FFmpeg no contiene `--enable-gpl` ni `--enable-nonfree`.

## Compilar localmente

```powershell
.\scripts\stage-ffmpeg.ps1 -ArchivePath C:\ruta\ffmpeg-win64-lgpl.zip
npm run package:windows
```

El resultado listo para distribuir queda en `release/`:

- `Transcriptor_<versión>_x64-setup.exe`;
- `Transcriptor_<versión>_x64_en-US.msi`;
- `checksums-SHA256.txt`.

## Publicar automáticamente

Cuando las comprobaciones hayan pasado:

```powershell
git tag v0.1.0
git push origin v0.1.0
```

La etiqueta debe coincidir exactamente con la versión. El flujo `.github/workflows/release-windows.yml`:

1. instala dependencias fijadas;
2. descarga y verifica FFmpeg;
3. audita privacidad;
4. ejecuta lint, tipos y pruebas;
5. crea el sidecar autocontenido;
6. genera NSIS y MSI;
7. publica ambos en GitHub Releases;
8. adjunta las sumas SHA-256.

No se sube `%LOCALAPPDATA%`, el contenido del directorio de trabajo ni ningún archivo que no esté versionado. GitHub Actions parte de un clon limpio del repositorio.

## Comprobación final

Antes de anunciar una versión:

- instala el `setup.exe` en un usuario de Windows limpio;
- importa MP3, WAV y MP4;
- prueba CPU y, si es posible, NVIDIA/CUDA;
- transcribe, cancela, reabre, reproduce, edita y exporta;
- confirma que no existen proyectos previos tras instalar;
- verifica la suma SHA-256 publicada;
- comprueba el comportamiento de SmartScreen y la firma.
