# Privacidad y datos locales

## Principio

Transcriptor procesa el audio, el vídeo, el texto y las huellas de voz en el ordenador del usuario. No existe una cuenta común, una base de datos remota ni telemetría activada por defecto.

Subir el código a GitHub no sube los datos creados con la aplicación. El repositorio, el instalador y el directorio de datos son tres ámbitos separados.

## Ubicaciones en Windows

Cada cuenta de Windows tiene un directorio privado e independiente:

```text
%LOCALAPPDATA%\Transcriptor\
├── transcriptor.sqlite3   proyectos y segmentos
├── recordings\            grabaciones creadas en directo
├── imports\               medios incorporados desde paquetes portables
├── models\                modelos descargados con consentimiento
└── logs\                  diagnóstico técnico sin texto transcrito
```

Ollama gestiona sus modelos en `%USERPROFILE%\.ollama\models` salvo que el usuario cambie su configuración. Los archivos originales que se abren desde Documentos, Descargas u otra carpeta permanecen donde estaban: la base de datos sólo conserva su ruta.

La cuenta `Usuario A` no comparte estas rutas con `Usuario B`, y dos equipos diferentes tampoco quedan sincronizados. No hay vinculación automática entre grabaciones.

## Qué puede usar internet

- GitHub, sólo cuando el usuario descarga manualmente el instalador o una futura actualización.
- Hugging Face u otro origen documentado, sólo después de aceptar la descarga de un modelo.
- Ollama, cuando el usuario instala o descarga expresamente un modelo local.
- Un proveedor en la nube futuro, únicamente si se implementa como opción separada, visible y desactivada inicialmente.

Ni el medio ni su transcripción se envían en esas descargas.

## Exportaciones y paquetes

TXT, subtítulos, JSON, DOCX, PDF y paquetes `.transcriptor` se escriben exclusivamente en la ubicación elegida por el usuario. Un paquete portable puede contener datos del proyecto por definición; sólo debe compartirse si el usuario decide exportarlo y enviarlo.

## Borrado y desinstalación

La desinstalación elimina la aplicación, pero no borra proyectos personales en silencio. Para borrar datos hay que usar las opciones de limpieza de la aplicación o eliminar conscientemente `%LOCALAPPDATA%\Transcriptor`.

Los temporales controlados por la aplicación se limpian cuando dejan de ser necesarios. Un cierre inesperado puede dejar archivos recuperables que el diagnóstico local puede identificar.

## Protección del repositorio

`.gitignore` excluye medios, bases de datos, modelos, motores descargados, binarios CUDA, artefactos de compilación y certificados. `scripts/verify-release.ps1` vuelve a comprobar los archivos versionados y cancela una publicación si encuentra:

- rutas personales como `C:\Users\...`;
- audio o vídeo;
- SQLite u otras bases de datos;
- carpetas de grabaciones, proyectos, modelos o caché;
- certificados o claves de firma.

No adjuntes grabaciones, transcripciones ni diagnósticos sin revisar a una incidencia pública de GitHub.
