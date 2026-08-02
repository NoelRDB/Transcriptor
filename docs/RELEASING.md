# Publicar una versión en GitHub

## Una sola vez por repositorio

1. Crea o enlaza un repositorio público de GitHub.
2. Activa GitHub Actions.
3. No configures una descarga FFmpeg externa: el workflow compila el commit
   fijado y adjunta su código fuente correspondiente exacto.
4. Lee y mantén la [Code signing policy](CODE_SIGNING_POLICY.md). La solicitud a
   SignPath Foundation sigue pendiente y `v0.1.0` no está firmada. No afirmes
   que una versión usa SignPath hasta que exista aprobación, configuración
   operativa y una firma verificada.

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

Genera primero el runtime y el código fuente correspondiente desde Ubuntu,
WSL2 o un contenedor Linux con el toolchain documentado en
[Empaquetado](PACKAGING.md). Después, en Windows:

```powershell
.\scripts\stage-ffmpeg.ps1 `
  -ArchivePath C:\ruta\ffmpeg-runtime-windows-x64.zip
npm run package:windows
```

El resultado listo para distribuir queda en `release/`:

- `Transcriptor_<versión>_x64-setup.exe`;
- `Transcriptor_<versión>_x64_en-US.msi`;
- `checksums-SHA256.txt`;
- `Transcriptor-<versión>-FFmpeg-corresponding-source.tar.gz`;
- `THIRD_PARTY_NOTICES.md`.

`checksums-SHA256.txt` contiene exactamente los otros cuatro assets, ordenados
por nombre: NSIS, MSI, código fuente correspondiente de FFmpeg y avisos de
terceros. El propio archivo de sumas queda cubierto por la atestación Sigstore.

## Inmutabilidad de GitHub Releases

Para `v0.1.1`, primero sube el commit y espera a que CI termine correctamente.
Después, y **antes de despachar el workflow manual de la candidata**, un
administrador debe activar **Settings → General → Releases → Enable release
immutability**. La activación sólo afecta a Releases publicadas a partir de ese
momento; por eso no debe hacerse después de publicar `v0.1.1`.

El workflow prepara y modifica únicamente un borrador privado. Adjunta y
verifica todos los assets antes del único cambio final a `draft=false`. Desde
ese instante no vuelve a editar, sustituir ni eliminar la Release, la etiqueta
o sus assets. GitHub bloquea esos elementos y genera la atestación de Release.

La atestación puede tardar unos instantes en estar disponible. No se usa como
puerta inmediata del workflow. Tras la publicación, espera a su propagación y
verifica manualmente:

```powershell
gh release verify v0.1.1 -R NoelRDB/Transcriptor
gh release verify-asset v0.1.1 `
  .\Transcriptor_0.1.1_x64-setup.exe `
  -R NoelRDB/Transcriptor
```

Repite la comprobación después de un intervalo breve si GitHub todavía no ha
publicado la atestación. `gh release verify-asset` recibe la ruta del archivo
local descargado, no sólo el nombre remoto. Comprueba del mismo modo MSI,
sumas, avisos y código fuente correspondiente.

La inmutabilidad y la atestación de Release impiden sustituir en GitHub la
etiqueta o los assets publicados. Son controles distintos de la atestación
Sigstore generada por el workflow y no sustituyen Authenticode, la identidad de
editor de Windows ni la reputación de SmartScreen.

## Publicar automáticamente

Cuando las comprobaciones hayan pasado:

```powershell
$releaseTag = Read-Host 'Nueva etiqueta (formato vX.Y.Z)'
git tag -a $releaseTag -m "Transcriptor $releaseTag"
git push origin "refs/tags/$releaseTag"
```

No reutilices ni muevas `v0.1.0`: identifica la Release heredada sin firma y con
CUDA embebido. La nueva etiqueta debe ser **anotada**, apuntar directamente al
`HEAD` actual de `master` y coincidir exactamente con la versión. Los tags
ligeros, los tags sobre otro commit, `v0.1.1` y las versiones con sufijos se
rechazan. El flujo `.github/workflows/release-windows.yml`:

1. instala dependencias fijadas;
2. compila FFmpeg LGPL desde la fuente fijada y genera su corresponding source;
3. prueba el runtime Windows con los 13 formatos admitidos y los flujos de
   extracción/edición;
4. audita privacidad;
5. ejecuta lint, tipos y pruebas;
6. construye y audita el sidecar CTranslate2 CPU desde dependencias fijadas y
   crea el ejecutable autocontenido;
7. genera NSIS y MSI;
8. crea una GitHub Release en borrador;
9. valida formatos, runtime, inventario legal, payload, tamaños y sumas
   SHA-256 antes de solicitar la firma;
10. envía exclusivamente los instaladores NSIS y MSI a SignPath;
11. verifica Authenticode, editor y marca de tiempo de ambos instaladores;
12. genera atestaciones Sigstore de GitHub para los cinco assets finales;
13. publica instaladores, avisos y corresponding source únicamente si todas
    las comprobaciones terminan correctamente.

No se sube `%LOCALAPPDATA%`, el contenido del directorio de trabajo ni ningún archivo que no esté versionado. GitHub Actions parte de un clon limpio del repositorio.

La etiqueta debe tener exactamente el formato `vX.Y.Z` y coincidir con los cuatro manifiestos. Una etiqueta incorrecta detiene la publicación antes de hacer visible ningún instalador.

## Firma de código

### Estado actual

`v0.1.0` se publicó sin firma Authenticode, incluye bibliotecas CUDA dentro de
sus instaladores heredados y no es candidata a firma retroactiva. SignPath
Foundation no ha aprobado ni firmado Transcriptor. El workflow actual de
`master` prepara artefactos futuros sin CUDA embebido y debe tratarlos como no
firmados hasta que exista una aprobación y una firma verificable. Cada Release
debe describir su estado sin ambigüedad.

> **Puerta del runtime CPU:** no crees ni subas un tag estable si el sidecar no
> procede del entorno fijado por `uv.lock`. El workflow debe encontrar los
> inventarios `PYTHON-RUNTIME-INVENTORY.json` y
> `PYTHON-RUNTIME-LICENSES.json`, comprobar sus avisos —incluido Intel
> OpenMP— y rechazar cualquier biblioteca CUDA o NVIDIA dentro del instalador.

### Procedimiento condicionado a la aprobación de SignPath

Sólo después de recibir la aprobación y probar la configuración concedida:

1. la construcción que vaya a firmarse se ejecutará desde el repositorio
   oficial en ejecutores alojados por GitHub;
2. el artefacto sin firmar se subirá como artefacto del workflow para que
   SignPath compruebe su procedencia;
3. [NoelRDB](https://github.com/NoelRDB), como aprobador, revisará etiqueta,
   *commit*, pruebas, licencias, privacidad e inventario antes de aprobar
   manualmente cada solicitud;
4. se publicará únicamente el artefacto firmado devuelto por SignPath;
5. se verificará Authenticode, la marca de tiempo y la suma SHA-256 antes de
   hacer visible la Release;
6. la Release distinguirá claramente archivos firmados y no firmados e
   incluirá la atribución requerida por SignPath Foundation.

No se conservará un `.pfx` ni una clave privada en GitHub. No se firmarán
artefactos locales, de un *fork* o modificados después de su construcción. La
configuración actual de SignPath firma únicamente los contenedores de
instalación exteriores NSIS y MSI. Los ejecutables y DLL incluidos dentro del
payload se auditan, pero no reciben una firma Authenticode individual.
No anuncies «todos los binarios firmados». Un flujo profesional de dos etapas
(PE internos primero, instaladores después) sólo podrá activarse cuando
SignPath lo autorice y proporcione una configuración verificable; hasta
entonces se documenta como limitación y el workflow no lo simula.

La integración no debe activarse si la auditoría de terceros encuentra un
componente incompatible con las condiciones del programa. El instalador no
debe contener el runtime propietario CUDA, modelos descargables ni datos
locales. La descarga opcional posterior de NVIDIA queda fuera del artefacto
firmado y debe mantenerse separada, consentida y verificable; consulta
[Avisos de terceros](THIRD_PARTY_NOTICES.md).

## Comprobación final

Antes de anunciar una versión:

- instala el `setup.exe` en un usuario de Windows limpio;
- importa MP3, WAV y MP4;
- prueba CPU y, si es posible, NVIDIA/CUDA;
- confirma que el instalador CPU conserva los inventarios y licencias de
  CTranslate2/Intel OpenMP y no contiene bibliotecas CUDA;
- transcribe, cancela, reabre, reproduce, edita y exporta;
- confirma que no existen proyectos previos tras instalar;
- verifica la suma SHA-256 publicada;
- verifica la procedencia con
  `gh attestation verify <archivo> -R NoelRDB/Transcriptor`;
- cuando la política de inmutabilidad ya esté activa, verifica la Release con
  `gh release verify <tag> -R NoelRDB/Transcriptor` y cada descarga local con
  `gh release verify-asset <tag> <ruta-local> -R NoelRDB/Transcriptor`;
- comprueba el comportamiento de SmartScreen;
- si la Release declara una firma, verifica editor, cadena, marca de tiempo y
  firma Authenticode de los instaladores NSIS y MSI publicados;
- confirma que no se atribuye una firma individual a ejecutables o DLL del
  payload;
- confirma que la descripción de la Release coincide con el estado real de
  [la política de firma](CODE_SIGNING_POLICY.md).
