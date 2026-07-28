# Seguridad

## Versiones compatibles

Mientras el proyecto permanezca en `0.x`, sólo la versión más reciente recibe correcciones. La distribución probada actualmente es Windows 10/11 x64.

## Informar de una vulnerabilidad

Usa el sistema privado **Security → Report a vulnerability** del repositorio cuando esté disponible. No publiques tokens, certificados, rutas personales, grabaciones, transcripciones, perfiles de voz ni bases de datos en una incidencia.

Incluye la versión, Windows, pasos mínimos para reproducir y el mensaje de error sin contenido privado. Los diagnósticos deben revisarse antes de adjuntarlos.

## Modelo de privacidad

La aplicación procesa localmente por defecto. Cualquier función futura que envíe medios o texto a un servicio externo deberá:

1. estar desactivada inicialmente;
2. identificar proveedor y datos enviados;
3. solicitar consentimiento explícito;
4. permitir revocar la configuración.

Los flujos de publicación rechazan datos personales, medios, bases de datos y material de firma versionado.
