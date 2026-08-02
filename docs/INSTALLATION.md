# Instalar Transcriptor en Windows

Esta guía está pensada para cualquier persona, aunque nunca haya usado GitHub
ni herramientas de programación.

## Qué necesitas

- Windows 10 u 11 de 64 bits.
- Conexión a internet para descargar el instalador y los componentes opcionales
  que el usuario decida instalar.
- Aproximadamente 4 GB libres para la aplicación y el modelo Turbo.
- Al menos 8 GB libres si también quieres máxima precisión con Large-v3.
- Alrededor de 15 GB libres si además instalarás Ollama y Qwen para análisis
  profundo.

No necesitas instalar Python, Node.js, Rust, FFmpeg, CUDA ni abrir una terminal.

## Descargar la aplicación

1. Pulsa **[Descargar Transcriptor v0.1.1 para Windows](https://github.com/NoelRDB/Transcriptor/releases/download/v0.1.1/Transcriptor_0.1.1_x64-setup.exe)**.
   La descarga del instalador recomendado comenzará directamente.
2. Si prefieres comprobar todos los archivos, abre la
   [página de la Release v0.1.1](https://github.com/NoelRDB/Transcriptor/releases/tag/v0.1.1)
   y despliega **Assets**.
3. El instalador normal tiene este formato:

   ```text
   Transcriptor_<versión>_x64-setup.exe
   ```

4. No descargues `Source code.zip` ni `Source code.tar.gz`: contienen el código,
   no la aplicación instalable.

> [!IMPORTANT]
> `v0.1.1` es una candidata de evaluación sin firma Authenticode. Comprueba el
> archivo `checksums-SHA256.txt` publicado en la misma Release antes de abrir
> el instalador.

| Archivo | Para qué sirve |
|---|---|
| `*_x64-setup.exe` | Instalación normal. Es la opción recomendada. |
| `*_x64_en-US.msi` | Instalación administrada para empresas o técnicos. |
| `checksums-SHA256.txt` | Verificar que la descarga no se ha alterado. |
| `Source code.*` | Código para desarrolladores; no instala Transcriptor. |

> [!NOTE]
> Si la página indica que no hay versiones publicadas, el instalador todavía
> se está preparando. No descargues copias desde páginas de terceros.

### Diferencia importante de versiones

| Versión | Runtime NVIDIA | Firma |
|---|---|---|
| `v0.1.0` heredada | Incluye cuBLAS y cuDNN dentro del instalador | Sin firma; no es candidata a SignPath |
| Próxima Release y compilaciones actuales de `master` | No incluye CUDA; lo ofrece después como descarga opcional | Sólo se declarará firmada si SignPath la aprueba y la firma se verifica |

`v0.1.0` continúa descargable en GitHub. La nueva separación de CUDA no cambia
ese archivo ya publicado ni permite considerarlo firmado.

## Instalar paso a paso

1. Abre `Transcriptor_<versión>_x64-setup.exe` desde la carpeta Descargas.
2. Sigue el asistente de instalación.
3. Cuando termine, abre **Transcriptor** desde el menú Inicio o su acceso
   directo.

El instalador configura automáticamente:

- la aplicación de escritorio;
- el motor de transcripción y su runtime de Python;
- FFmpeg y FFprobe para leer audio y vídeo;
- las bibliotecas necesarias para transcribir con CPU.

El runtime CPU de CTranslate2 se construye desde fuentes fijadas para esta
aplicación. No contiene CUDA, oneMKL ni Intel OpenMP: utiliza oneDNN y LLVM
OpenMP abiertos y conserva dentro del instalador el marcador de procedencia y
los SHA-256 de sus DLL. La cadena de publicación rechaza el instalador si esa
evidencia no coincide.

Windows 10/11 normalmente ya incorpora Microsoft Edge WebView2. El instalador
de Transcriptor no contiene ni descarga su bootstrapper. Si WebView2 no está
disponible, instala primero el runtime desde la
[página oficial de Microsoft](https://developer.microsoft.com/microsoft-edge/webview2/)
y vuelve a abrir Transcriptor. No necesitas hacer este paso si la aplicación se
abre normalmente.

En `v0.1.0`, cuBLAS y cuDNN ya vienen dentro del instalador. En las
compilaciones actuales de `master` y la próxima Release, el instalador no
contiene esos binarios propietarios. En ambos diseños, si no existe una GPU
NVIDIA compatible, Transcriptor utiliza CPU automáticamente. No es un error.

### Aceleración NVIDIA opcional después de `v0.1.0`

En las compilaciones actuales de `master` y las versiones posteriores a
`v0.1.0`, si la aplicación detecta una GPU NVIDIA compatible y falta el
runtime, el asistente **Prepara la IA local** muestra la tarjeta
**Aceleración NVIDIA CUDA**:

1. revisa la descarga aproximada de 1,27 GiB y los 6 GiB temporales indicados;
2. pulsa **Instalar** sólo si quieres usar la GPU;
3. sigue el progreso real o cancela sin afectar al modo CPU;
4. si se interrumpe, utiliza **Reintentar**.

La descarga sólo comienza con una confirmación explícita. Cada *wheel* se
comprueba contra un SHA-256 fijado y sólo se extraen
las DLL de cuBLAS, cuDNN 9 y NVRTC incluidas en una lista cerrada, junto con
los textos de licencia exactos incluidos por NVIDIA. La aplicación los
activa de forma atómica en:

```text
%LOCALAPPDATA%\TranscriptorData\runtime\cuda
```

Los archivos temporales se eliminan después. En estas versiones posteriores, el
runtime no está en el repositorio ni en el instalador y no hay que instalar el
CUDA Toolkit manualmente.

### Si Windows muestra “Protegió su PC”

La versión `v0.1.0` no tiene firma Authenticode y no es candidata a recibirla
retroactivamente. Por eso SmartScreen puede indicar que el editor es
desconocido. La solicitud a SignPath Foundation está pendiente: el proyecto no
ha sido aprobado por SignPath y no existe todavía ningún instalador firmado por
esa fundación.

La candidata `v0.1.1` está completamente sin firma: NSIS/MSI,
`Transcriptor.exe`, el sidecar y los DLL internos no tienen Authenticode. En
una futura integración inicial de SignPath sólo los contenedores NSIS/MSI se
describirán como firmados; los PE internos seguirán declarados como no firmados
hasta que exista y se verifique un flujo autorizado de dos etapas.

1. Comprueba que lo descargaste desde
   `github.com/NoelRDB/Transcriptor/releases`.
2. Comprueba el SHA-256 siguiendo la sección siguiente.
3. Si ambos datos son correctos, pulsa **Más información** y después
   **Ejecutar de todas formas**.

No continúes si el archivo procede de otra web o tiene un nombre diferente.

Cuando una versión futura esté firmada, su página de GitHub Release lo indicará
de forma expresa y Windows mostrará la identidad del editor del certificado.
Una firma válida permite verificar procedencia e integridad, pero una versión
nueva todavía puede recibir un aviso de reputación de SmartScreen. No asumas
que un archivo está firmado sólo porque tenga el mismo nombre.

El estado y el procedimiento de verificación se mantienen en la
[Code signing policy](CODE_SIGNING_POLICY.md).

## Comprobar la descarga

Esta comprobación es opcional, pero especialmente recomendable para `v0.1.0` y
cualquier instalador cuya Release no confirme una firma válida.

1. Descarga también `checksums-SHA256.txt` desde los mismos **Assets**.
2. Abre PowerShell dentro de Descargas.
3. Ejecuta:

   ```powershell
   Get-FileHash .\Transcriptor_*_x64-setup.exe -Algorithm SHA256
   ```

4. El valor mostrado debe coincidir con el correspondiente en
   `checksums-SHA256.txt`.

Como comprobación adicional de procedencia, instala
[GitHub CLI](https://cli.github.com/) y ejecuta en la carpeta de descarga:

```powershell
gh attestation verify .\Transcriptor_<versión>_x64-setup.exe `
  -R NoelRDB/Transcriptor
```

La atestación Sigstore vincula el hash del archivo con el repositorio y el
workflow de GitHub Actions que lo produjo. No sustituye la firma Authenticode,
el editor de Windows ni la reputación de SmartScreen; en la candidata sin firma
seguirán siendo aplicables las advertencias indicadas arriba.

Si la página de `v0.1.1` muestra el distintivo **Immutable**, GitHub también
protege su etiqueta y sus assets contra sustituciones. Después de descargar el
instalador puedes verificar la atestación de esa Release y la coincidencia del
archivo local:

```powershell
gh release verify v0.1.1 -R NoelRDB/Transcriptor
gh release verify-asset v0.1.1 `
  .\Transcriptor_0.1.1_x64-setup.exe `
  -R NoelRDB/Transcriptor
```

GitHub puede tardar unos instantes en publicar esa atestación; vuelve a probar
tras un intervalo breve. Esta comprobación tampoco sustituye Authenticode ni
SmartScreen.

## Preparar los modelos locales

El instalador incluye todo el software necesario, pero no impone varios
gigabytes de modelos a todo el mundo. La propia aplicación permite descargarlos
con un clic y muestra tamaño, espacio libre y progreso real:

1. Abre Transcriptor.
2. Pulsa el engranaje **Ajustes**.
3. En **Modelos locales → Reconocimiento de voz**, pulsa **Descargar**.
4. Acepta la descarga después de revisar su tamaño.
5. Espera hasta que aparezca **Instalado**.

También puedes abrir un audio y pulsar **Transcribir**. Si falta un modelo,
Transcriptor pedirá permiso y lo preparará automáticamente antes de comenzar.

| Modelo | Descarga aproximada | Uso recomendado |
|---|---:|---|
| Tiny | 0,08 GB | Pruebas rápidas en equipos con poca memoria. |
| Small | 0,5 GB | Audio claro y equipos modestos. |
| Turbo | 1,6 GB | Recomendado para directo y uso cotidiano. |
| Large-v3 | 3,1 GB | Máxima precisión, ruido y acentos difíciles. |
| CAM++ | 27 MB | Separar hablantes y reconocer perfiles de voz. |

Para empezar sin complicaciones, instala **Turbo** y **CAM++**. El modo
**Profesional IA** puede solicitar además Large-v3 para volver a escuchar sólo
los fragmentos dudosos.

### Resúmenes, puntos clave y mapas conceptuales

La transcripción no necesita Ollama. Las funciones de análisis profundo sí usan
Ollama y Qwen de forma local. Son opcionales porque añaden aproximadamente
6,6 GB y requieren más memoria. Transcriptor nunca los descarga en silencio.
El análisis rápido sigue disponible sin ellos.

## Privacidad

- Los modelos descargados contienen pesos de inteligencia artificial, no
  proyectos, grabaciones ni transcripciones de otros usuarios de Transcriptor.
- Descargar un modelo no envía tu audio, vídeo ni texto.
- Después de instalarlo, la inferencia se ejecuta dentro de tu ordenador.
- Proyectos, grabaciones y perfiles de voz se guardan por separado para cada
  cuenta de Windows.
- Tus datos no se incluyen al actualizar la aplicación ni al publicar el código
  en GitHub.

Los datos se almacenan principalmente en:

```text
%LOCALAPPDATA%\TranscriptorData\
```

Consulta [Privacidad y datos locales](PRIVACY.md) para conocer el detalle.

## Problemas habituales

### No aparece “Assets”

La versión puede seguir compilándose o todavía no estar publicada. Actualiza la
página unos minutos después. Si continúa igual, revisa la pestaña
[Releases](https://github.com/NoelRDB/Transcriptor/releases).

### Descargué un ZIP y no veo el instalador

Has descargado `Source code.zip`. Vuelve a **Releases → Assets** y elige el
archivo que termina en `_x64-setup.exe`.

### Un modelo no termina de descargarse

Comprueba la conexión, el espacio libre y si el antivirus o la red bloquean la
descarga. Si se interrumpe, vuelve a abrir Transcriptor y pulsa **Completar**:
los archivos parciales se revisan y sólo se descarga lo que siga faltando.

### No tengo tarjeta NVIDIA

La aplicación utiliza la CPU automáticamente. Funcionará igual, aunque los
modelos grandes pueden tardar más.

### Quiero eliminar un modelo

Abre **Ajustes → Modelos locales** y utiliza el icono de papelera. Los proyectos
y las transcripciones no se borran al eliminar un modelo.
