# Code signing policy

## Estado actual

| Elemento | Estado |
|---|---|
| Última versión documentada | `v0.1.0` |
| Firma Authenticode de `v0.1.0` | No; se publicó sin firma |
| CUDA en los instaladores de `v0.1.0` | Sí; runtime propietario heredado |
| Candidata a firma de SignPath | Una versión futura posterior a `v0.1.0`, no la Release heredada |
| Solicitud a SignPath Foundation | Pendiente de preparación y evaluación |
| Aprobación de SignPath Foundation | No concedida |
| Versiones firmadas por SignPath Foundation | Ninguna |

SignPath Foundation no ha aprobado todavía Transcriptor y no ha firmado ninguna
versión. Esta política documenta el proceso que se aplicará **únicamente si la
solicitud es aceptada y la integración técnica queda validada**. Hasta entonces,
los instaladores deben describirse como no firmados y verificarse mediante las
sumas SHA-256 publicadas en GitHub Releases.

`v0.1.0` permanece descargable, contiene bibliotecas CUDA propietarias dentro
de sus instaladores y no se presentará como candidata a firma. La retirada de
esas bibliotecas se aplica a `master` y a futuras compilaciones; no modifica ni
firma retroactivamente la Release ya publicada.

Una firma válida elimina la indicación de «editor desconocido» y permite
comprobar la integridad y procedencia del binario. No garantiza por sí sola que
Microsoft SmartScreen deje de advertir sobre una versión nueva: la reputación
de Windows se construye con el tiempo.

Cada publicación nueva genera también una atestación Sigstore de procedencia de
GitHub para sus cinco assets finales. Puede verificarse con
`gh attestation verify <archivo> -R NoelRDB/Transcriptor`. Esta atestación
vincula el hash con el repositorio y el workflow, pero no sustituye
Authenticode, el editor de Windows ni SmartScreen.

Antes de despachar la candidata `v0.1.1`, y sólo después de que su commit haya
superado CI, el administrador activará la inmutabilidad de Releases del
repositorio. El workflow completa el borrador antes de publicarlo y no modifica
la Release después de `draft=false`. GitHub podrá entonces bloquear la etiqueta
y los assets y crear una atestación de Release. Tras la propagación se comprueba
con `gh release verify v0.1.1 -R NoelRDB/Transcriptor` y cada archivo local con
`gh release verify-asset v0.1.1 <ruta-local> -R NoelRDB/Transcriptor`.
Esta protección tampoco es una firma Authenticode ni modifica el estado de
firma de ningún PE.

## Proyecto y repositorio autorizados

- Proyecto: **Transcriptor**.
- Repositorio oficial:
  [NoelRDB/Transcriptor](https://github.com/NoelRDB/Transcriptor).
- Licencia del código propio: [MIT](../LICENSE).
- Artefactos previstos para firma: únicamente los instaladores exteriores
  Windows NSIS/MSI construidos desde una etiqueta de versión del repositorio.
  El ejecutable principal, el sidecar y las DLL del payload se auditan, pero la
  configuración actual no les aplica una firma Authenticode individual.

La configuración prevista de SignPath es, por ahora, de una sola etapa y firma
únicamente NSIS/MSI después del empaquetado. Por ello, incluso en una futura
Release cuyo instalador exterior esté firmado, `Transcriptor.exe`, el sidecar y
los DLL instalados continuarán sin firma individual. No se describirá esa
Release como «todos los binarios firmados». Si SignPath autoriza más adelante
un flujo de dos etapas, deberá firmar primero los PE internos, verificar cada
firma, empaquetar exactamente esos bytes y firmar después NSIS/MSI; el workflow
quedará bloqueado si falta cualquiera de ambas etapas. Ese flujo no se
considera disponible hasta tener aprobación y configuración reales.

No se firmará código de otro proyecto como si perteneciera a Transcriptor. Los
componentes de terceros conservarán su identidad, firma y licencia. Un binario
de terceros sin firma sólo podrá incluirse en el paquete cuando sus términos de
redistribución y la política de SignPath lo permitan; no recibirá una firma que
lo presente como código propio.

Los modelos descargados por el usuario después de instalar no forman parte del
artefacto firmado.

## Responsables

El proyecto tiene actualmente un único mantenedor:

| Rol | Responsable | Responsabilidad |
|---|---|---|
| Autor o *committer* | [NoelRDB](https://github.com/NoelRDB) | Mantener el código, los scripts de construcción y la configuración del proyecto. |
| Revisor | [NoelRDB](https://github.com/NoelRDB) | Revisar contribuciones externas, resultados de CI, licencias, privacidad y contenido de la versión. |
| Aprobador | [NoelRDB](https://github.com/NoelRDB) | Aprobar manualmente cada solicitud de firma y confirmar que corresponde a una versión pública válida. |

Las contribuciones de terceros se incorporarán mediante *pull request* y
revisión del mantenedor. Al ser un proyecto de una sola persona, las
modificaciones directas del mantenedor no tienen una segunda revisión humana;
esta limitación se declara expresamente y se compensa con comprobaciones
automatizadas, revisión del *diff* de la versión y aprobación manual separada de
la solicitud de firma. Si se incorporan más mantenedores, esta tabla se
actualizará antes de asignarles permisos.

Todos los participantes con permisos de escritura o firma deben proteger tanto
GitHub como SignPath con autenticación multifactor.

## Condiciones previas a la solicitud

Antes de pedir la aprobación de SignPath Foundation se debe:

1. mantener el repositorio público, activo y documentado;
2. conservar una licencia aprobada por OSI para el código propio;
3. publicar al menos una versión instalable sin presentarla como firmada;
4. documentar autores, revisores y aprobadores;
5. mantener una política de privacidad y desinstalación visible;
6. producir los binarios mediante una construcción automatizada y verificable;
7. auditar las licencias y el origen de todo lo incluido en el instalador;
8. excluir malware, software potencialmente no deseado, secretos, datos de
   usuario y funciones destinadas a eludir controles de seguridad;
9. obtener confirmación de SignPath sobre cualquier componente redistribuible
   que no use una licencia aprobada por OSI.

El futuro paquete Windows candidato a firma no incorporará cuBLAS ni cuDNN. En
las compilaciones actuales de `master`, la aceleración NVIDIA se prepara
mediante una descarga opcional posterior, solicitada por el usuario y
almacenada fuera del instalador. La evaluación deberá confirmar que este límite
de alcance, junto con cualquier otro runtime o modelo, cumple la política
concedida. El paquete CPU usa CTranslate2 4.8.1 desde el entorno fijado por
`uv.lock` e incluye `libiomp5md.dll`, con la licencia Intel Simplified Software
License conservada dentro del instalador. Los inventarios versionados registran
las versiones y los SHA-256 de los avisos legales.

La publicación queda bloqueada si esos inventarios no coinciden o si aparece
un runtime CUDA o NVIDIA dentro del instalador. La existencia de este documento
no presupone que el paquete cumpla ya todos los criterios de SignPath; la
elegibilidad de Intel OpenMP deberá confirmarse expresamente durante su revisión.

El bootstrapper propietario de Microsoft WebView2 tampoco se incorpora al
artefacto candidato. Tauri usa el modo `skip`: WebView2 es un requisito del
sistema que Windows 10/11 normalmente ya satisface y, si falta, el usuario lo
instala por separado desde la
[página oficial de Microsoft](https://developer.microsoft.com/microsoft-edge/webview2/).
La auditoría extrae NSIS y MSI y rechaza expresamente
`MicrosoftEdgeWebview2Setup.exe`.

Las condiciones oficiales del programa prevalecen sobre esta descripción:
[SignPath Foundation conditions for Open Source
projects](https://signpath.org/terms.html).

## Proceso previsto después de una aprobación

Una vez que SignPath apruebe el proyecto y configure su política:

1. se construirá desde una etiqueta `vX.Y.Z` del repositorio oficial en
   ejecutores alojados por GitHub;
2. la versión de los manifiestos y la etiqueta deberán coincidir;
3. se ejecutarán lint, tipos, pruebas, auditoría de privacidad, comprobaciones
   de licencias y validación del paquete;
4. los instaladores NSIS y MSI sin firmar se conservarán como artefacto del
   trabajo para que SignPath pueda verificar su procedencia;
5. el aprobador revisará la etiqueta, el *commit*, los resultados de CI y el
   inventario del instalador antes de aprobar manualmente la firma;
6. sólo se publicarán los instaladores exteriores devueltos por SignPath, con
   marca de tiempo, tras verificar sus firmas y sumas SHA-256; el contenido
   interno no se describirá como firmado individualmente;
7. la Release indicará de forma inequívoca qué archivos están firmados, el
   editor mostrado por Windows y cómo comprobarlos.

Cada versión requiere una aprobación manual nueva. No se firmarán artefactos
compilados en un equipo personal, procedentes de un *fork*, modificados después
de la firma o no vinculados a una ejecución verificable del repositorio.

El procedimiento técnico detallado se mantendrá en
[Publicar una versión](RELEASING.md). No se activará ni se anunciará como
operativo hasta que haya sido probado con la configuración concedida por
SignPath.

## Atribución tras la aprobación

Sólo después de que exista una aprobación vigente y una versión haya sido
firmada mediante ese servicio, la página de descarga de esa versión mostrará:

> Free code signing provided by
> [SignPath.io](https://signpath.io/), certificate by
> [SignPath Foundation](https://signpath.org/)

El certificado se emitiría a nombre de **SignPath Foundation**. Esa sería la
identidad de editor mostrada por Windows; no debe presentarse como un
certificado personal de NoelRDB ni como uno emitido directamente a
«Transcriptor».

## Privacidad

Transcriptor procesa localmente medios, transcripciones y perfiles de voz. No
incorpora telemetría activada por defecto y no envía contenido a la red para
firmar una versión. La firma ocurre sobre artefactos limpios creados por GitHub
Actions y no accede a datos generados en los equipos de los usuarios.

> This program will not transfer any information to other networked systems
> unless specifically requested by the user or the person installing or
> operating it.

Las acciones de red permitidas y sus condiciones se detallan en
[Privacidad y datos locales](PRIVACY.md). Ningún proyecto, grabación,
transcripción, perfil de voz, modelo descargado, caché o base de datos del
usuario se incorpora al repositorio ni a los instaladores.

## Incidencias y revocación

Una sospecha de artefacto manipulado, clave comprometida, firma indebida,
malware o vulneración de esta política debe comunicarse mediante el proceso de
[seguridad](../SECURITY.md), sin adjuntar datos personales. El mantenedor
detendrá la publicación, investigará el origen y colaborará con SignPath en la
revocación o las medidas correctoras que correspondan.

El historial no se reescribirá para aparentar que una versión antigua estaba
firmada. Una versión revocada o sustituida se marcará claramente en GitHub
Releases.
