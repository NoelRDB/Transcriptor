# Configuracion de firma de releases

La release oficial envia a SignPath un ZIP de GitHub Actions que contiene
exactamente el instalador NSIS y el paquete MSI. La configuracion
`artifact-configuration.xml` firma solo esos dos contenedores finales.

## Configuracion necesaria

Primero, el proyecto debe solicitar y obtener la aceptación de SignPath para
Open Source Code Signing. Añadir este workflow no concede un certificado ni
implica que la solicitud ya esté aprobada.

En SignPath:

1. Crea un proyecto asociado a este repositorio y al Trusted Build System
   `GitHub.com`.
2. Instala la GitHub App de SignPath y concede acceso a
   `NoelRDB/Transcriptor`, necesario para verificar el origen del build.
3. Crea una configuracion de artefacto copiando
   `artifact-configuration.xml`.
4. Crea una politica de release que use el certificado cuyo editor sea
   exactamente `SignPath Foundation`, exija timestamp y acepte unicamente
   builds del repositorio y tags `v*`.
5. Crea un API token con permiso exclusivo para enviar solicitudes mediante
   esa politica.

En el Environment protegido de GitHub `production-signing`, configura:

- Variable `SIGNPATH_ORGANIZATION_ID`.
- Variable `SIGNPATH_PROJECT_SLUG`.
- Variable `SIGNPATH_SIGNING_POLICY_SLUG`.
- Variable `SIGNPATH_ARTIFACT_CONFIGURATION_SLUG`.
- Secret `SIGNPATH_API_TOKEN`.

Configura revisores obligatorios en el Environment. El workflow valida que
todos estos valores existan antes de construir o publicar. También envía el
parámetro obligatorio `version`, que restringe ProductName, ProductVersion y
FileVersion del instalador NSIS. La configuración restringe igualmente
Subject y Author del MSI a los valores generados por Tauri.

## Alcance y limitacion deliberada

Esta primera politica no hace firma profunda. Firma el EXE exterior de NSIS y
el MSI, pero los payloads internos conservan sus firmas originales o permanecen
sin firmar; esto incluye el ejecutable y las DLL que NSIS extrae. En particular,
no se firma ni se vuelve a firmar FFmpeg, FFprobe o binarios de NVIDIA.

Para firmar en el futuro los binarios propios instalados, debe crearse una
configuracion profunda que enumere exclusivamente artefactos de Transcriptor y
use `authenticode-verify` para componentes de terceros. No se debe sustituir
una firma valida de un proveedor por la del proyecto.

La publicacion queda bloqueada si falta SignPath, si el editor no coincide
exactamente, si no existe timestamp o si SignTool devuelve una advertencia.
