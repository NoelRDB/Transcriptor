# Instalar Transcriptor en Windows

Esta guía está pensada para cualquier persona, aunque nunca haya usado GitHub
ni herramientas de programación.

## Qué necesitas

- Windows 10 u 11 de 64 bits.
- Conexión a internet durante la descarga inicial.
- Aproximadamente 4 GB libres para la aplicación y el modelo Turbo.
- Al menos 8 GB libres si también quieres máxima precisión con Large-v3.
- Alrededor de 15 GB libres si además instalarás Ollama y Qwen para análisis
  profundo.

No necesitas instalar Python, Node.js, Rust, FFmpeg, CUDA ni abrir una terminal.

## Descargar la aplicación

1. Abre la
   **[última versión de Transcriptor](https://github.com/NoelRDB/Transcriptor/releases/latest)**.
2. Busca el apartado **Assets**. Si está plegado, haz clic sobre él.
3. Descarga el archivo con este formato:

   ```text
   Transcriptor_<versión>_x64-setup.exe
   ```

4. No descargues `Source code.zip` ni `Source code.tar.gz`: contienen el código,
   no la aplicación instalable.

| Archivo | Para qué sirve |
|---|---|
| `*_x64-setup.exe` | Instalación normal. Es la opción recomendada. |
| `*_x64_en-US.msi` | Instalación administrada para empresas o técnicos. |
| `checksums-SHA256.txt` | Verificar que la descarga no se ha alterado. |
| `Source code.*` | Código para desarrolladores; no instala Transcriptor. |

> [!NOTE]
> Si la página indica que no hay versiones publicadas, el instalador todavía
> se está preparando. No descargues copias desde páginas de terceros.

## Instalar paso a paso

1. Abre `Transcriptor_<versión>_x64-setup.exe` desde la carpeta Descargas.
2. Sigue el asistente de instalación.
3. Cuando termine, abre **Transcriptor** desde el menú Inicio o su acceso
   directo.

El instalador configura automáticamente:

- la aplicación de escritorio;
- el motor de transcripción y su runtime de Python;
- FFmpeg y FFprobe para leer audio y vídeo;
- WebView2 para mostrar la interfaz;
- las bibliotecas de ejecución necesarias para CPU y GPU NVIDIA compatible.

Si no existe una GPU NVIDIA compatible, Transcriptor cambia automáticamente a
CPU. No es un error y no hay que instalar CUDA manualmente.

### Si Windows muestra “Protegió su PC”

Hasta que los instaladores estén firmados, SmartScreen puede indicar que el
editor es desconocido.

1. Comprueba que lo descargaste desde
   `github.com/NoelRDB/Transcriptor/releases`.
2. Comprueba el SHA-256 siguiendo la sección siguiente.
3. Si ambos datos son correctos, pulsa **Más información** y después
   **Ejecutar de todas formas**.

No continúes si el archivo procede de otra web o tiene un nombre diferente.

## Comprobar la descarga

Esta comprobación es opcional, pero recomendable mientras el instalador no esté
firmado.

1. Descarga también `checksums-SHA256.txt` desde los mismos **Assets**.
2. Abre PowerShell dentro de Descargas.
3. Ejecuta:

   ```powershell
   Get-FileHash .\Transcriptor_*_x64-setup.exe -Algorithm SHA256
   ```

4. El valor mostrado debe coincidir con el correspondiente en
   `checksums-SHA256.txt`.

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
