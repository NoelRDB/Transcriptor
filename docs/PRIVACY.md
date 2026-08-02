# Privacidad y datos locales

## Principio

Transcriptor procesa el audio, el vídeo, el texto y las huellas de voz en el ordenador del usuario. No existe una cuenta común, una base de datos remota ni telemetría activada por defecto.

Subir el código a GitHub no sube los datos creados con la aplicación. El repositorio, el instalador y el directorio de datos son tres ámbitos separados.

La regla aplicable es:

> This program will not transfer any information to other networked systems
> unless specifically requested by the user or the person installing or
> operating it.

Es decir, Transcriptor no transfiere información a sistemas externos salvo
cuando el usuario o la persona que lo instala u opera solicita expresamente una
acción que necesita red. La comunicación local con procesos del mismo equipo,
como el sidecar u Ollama en `localhost`, no envía el contenido fuera del
ordenador.

## Diferencia entre `v0.1.0` y las próximas versiones

La Release pública heredada `v0.1.0` incluye bibliotecas CUDA propietarias
dentro de sus instaladores. Esos binarios son software de ejecución y no
contienen proyectos, grabaciones, texto ni perfiles de voz, pero sí forman parte
de la descarga de esa versión.

Las compilaciones actuales de `master` y las próximas Releases excluyen CUDA
del instalador. Sólo descargan el runtime después de que el usuario lo solicite
expresamente desde la aplicación. Este cambio no altera ni sustituye
retroactivamente los instaladores `v0.1.0` que siguen disponibles en GitHub.

El motor CPU incluido procede del entorno CTranslate2 fijado por `uv.lock` e
incluye su runtime Intel OpenMP. Los inventarios locales conservan versiones,
licencias y hashes de los avisos; no contienen audio, texto, perfiles ni
identificadores del usuario. El instalador base no contiene CUDA.

## Ubicaciones en Windows

Cada cuenta de Windows tiene un directorio privado e independiente:

```text
%LOCALAPPDATA%\TranscriptorData\
├── transcriptor.sqlite3   proyectos y segmentos
├── recordings\            grabaciones creadas en directo
├── imports\               medios incorporados desde paquetes portables
├── models\                modelos descargados con consentimiento
├── runtime\cuda\          aceleración NVIDIA opcional desde versiones posteriores a v0.1.0
└── logs\                  diagnóstico técnico sin texto transcrito
```

Ollama gestiona sus modelos en `%USERPROFILE%\.ollama\models` salvo que el usuario cambie su configuración. Los archivos originales que se abren desde Documentos, Descargas u otra carpeta permanecen donde estaban: la base de datos sólo conserva su ruta.

La cuenta `Usuario A` no comparte estas rutas con `Usuario B`, y dos equipos diferentes tampoco quedan sincronizados. No hay vinculación automática entre grabaciones.

## Qué puede usar internet

- GitHub, sólo cuando el usuario descarga manualmente el instalador, consulta una
  versión o solicita una futura actualización.
- Microsoft, sólo si el usuario comprueba que Windows no tiene WebView2 y abre
  manualmente su
  [página oficial](https://developer.microsoft.com/microsoft-edge/webview2/)
  para instalarlo. El instalador de Transcriptor no contiene ni descarga ese
  bootstrapper.
- Hugging Face u otro origen documentado, sólo después de que el usuario acepte
  la descarga de un modelo concreto y vea su tamaño.
- Ollama, cuando el usuario solicita expresamente instalar o descargar un modelo
  local. El análisis posterior se realiza contra el servicio local.
- NVIDIA/PyPI, sólo si se detecta una GPU compatible y el usuario acepta desde
  **Aceleración NVIDIA CUDA** la descarga opcional del runtime mostrado. La
  aplicación presenta tamaño y progreso, permite cancelar o reintentar y
  verifica cada archivo con un SHA-256 fijado antes de activarlo.
- Un proveedor en la nube futuro, únicamente si se implementa como opción
  separada, visible, desactivada inicialmente y con consentimiento específico
  antes de transferir contenido.

Ni el medio ni su transcripción se envían en esas descargas.

En las compilaciones posteriores a `v0.1.0`, el runtime CUDA opcional contiene
únicamente bibliotecas de ejecución. No contiene ni recibe audio, vídeo, texto,
perfiles de voz o proyectos. Se extraen los archivos necesarios en
`%LOCALAPPDATA%\TranscriptorData\runtime\cuda` mediante una activación atómica;
los temporales se eliminan. Si el usuario no lo instala, Transcriptor continúa
funcionando con CPU.

No existen cargas automáticas de audio, vídeo, transcripciones, perfiles de voz
o diagnósticos. Tampoco hay publicidad, analítica remota ni sincronización entre
equipos. Una acción de exportar o crear un paquete sólo escribe en la ubicación
elegida; compartir después ese archivo queda bajo control del usuario.

Los modelos son archivos de sólo lectura con pesos de inteligencia artificial.
No contienen proyectos de otros usuarios de Transcriptor y descargarlos no
sube grabaciones, texto ni perfiles de voz. Una vez instalados, la
transcripción y la comparación de voces pueden ejecutarse sin conexión. La
gestión se realiza desde
**Ajustes → Modelos locales**, donde se muestra el tamaño, el progreso y la
opción de eliminación.

## Exportaciones y paquetes

TXT, subtítulos, JSON, DOCX, PDF y paquetes `.transcriptor` se escriben exclusivamente en la ubicación elegida por el usuario. Un paquete portable puede contener datos del proyecto por definición; sólo debe compartirse si el usuario decide exportarlo y enviarlo.

## Borrado y desinstalación

La desinstalación elimina la aplicación, pero no borra proyectos personales en silencio. Para borrar datos hay que usar las opciones de limpieza de la aplicación o eliminar conscientemente `%LOCALAPPDATA%\TranscriptorData`. Las versiones de desarrollo anteriores pueden conservar sus datos en `%LOCALAPPDATA%\Transcriptor`.

Los temporales controlados por la aplicación se limpian cuando dejan de ser necesarios. Un cierre inesperado puede dejar archivos recuperables que el diagnóstico local puede identificar.

## Protección del repositorio

`.gitignore` excluye medios, bases de datos, modelos, motores descargados, binarios CUDA, artefactos de compilación y certificados. `scripts/verify-release.ps1` vuelve a comprobar los archivos versionados y cancela una publicación si encuentra:

- rutas personales como `C:\Users\...`;
- audio o vídeo;
- SQLite u otras bases de datos;
- carpetas de grabaciones, proyectos, modelos o caché;
- certificados o claves de firma.

No adjuntes grabaciones, transcripciones ni diagnósticos sin revisar a una incidencia pública de GitHub.

## Construcción y firma de versiones

GitHub Actions puede procesar el código fuente y los artefactos de una versión
para compilarlos, probarlos y publicarlos. Si SignPath Foundation acepta la
solicitud pendiente, SignPath procesará únicamente el artefacto limpio generado
por ese trabajo para verificar su origen y firmarlo. Este proceso de
mantenimiento no se ejecuta desde la instalación de un usuario y no tiene
acceso a `%LOCALAPPDATA%\TranscriptorData`.

La versión `v0.1.0` no está firmada, incluye CUDA en su paquete heredado y no es
candidata a firma. SignPath Foundation no ha aprobado ni firmado todavía
Transcriptor. Consulta la
[Code signing policy](CODE_SIGNING_POLICY.md) para conocer el estado y el
proceso previsto.
