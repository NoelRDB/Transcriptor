param(
  [switch]$RequireRuntimeAssets,
  [switch]$RequireInstallers,
  [switch]$StageArtifacts,
  [string]$InstallerDirectory,
  [string]$ArtifactOutputDirectory,
  [switch]$RequireAuthenticode,
  [string]$ExpectedPublisher = "SignPath Foundation",
  [switch]$RequireInstallerPayloadInspection,
  [string]$Version = ""
)

$ErrorActionPreference = "Stop"
$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$Package = Get-Content -LiteralPath (Join-Path $ProjectRoot "package.json") -Raw -Encoding UTF8 |
  ConvertFrom-Json
$TauriConfig = Get-Content -LiteralPath (Join-Path $ProjectRoot "src-tauri\tauri.conf.json") -Raw -Encoding UTF8 |
  ConvertFrom-Json
$RequestedInstallerVersion = $Version
$Version = [string]$Package.version
$InstallerVersion = if ([string]::IsNullOrWhiteSpace($RequestedInstallerVersion)) {
  $Version
}
else {
  $RequestedInstallerVersion
}
if ($InstallerVersion -notmatch "^\d+\.\d+\.\d+$") {
  throw "La versión de instalador '$InstallerVersion' debe usar el formato X.Y.Z."
}
if (
  $InstallerVersion -cne $Version -and
  (
    [string]$env:CI -ieq "true" -or
    $StageArtifacts -or
    $RequireAuthenticode -or
    $RequireInstallerPayloadInspection
  )
) {
  throw (
    "-Version sólo permite auditar metadatos locales de una versión heredada; " +
    "CI, staging, firma e inspección de payload exigen la versión actual $Version."
  )
}

$TrackedLicenseFiles = @(
  @{
    Path = Join-Path $ProjectRoot "docs\licenses\GPL-3.0.txt"
    Sha256 = "3972DC9744F6499F0F9B2DBF76696F2AE7AD8AF9B23DDE66D6AF86C9DFB36986"
  },
  @{
    Path = Join-Path $ProjectRoot "docs\licenses\LGPL-3.0.txt"
    Sha256 = "E3A994D82E644B03A792A930F574002658412F62407F5FEE083F2555C5F23118"
  }
)
foreach ($TrackedLicense in $TrackedLicenseFiles) {
  if (-not (Test-Path -LiteralPath $TrackedLicense.Path -PathType Leaf)) {
    throw "Falta un texto completo de licencia GNU: $($TrackedLicense.Path)"
  }
  $ActualLicenseHash = (Get-FileHash -LiteralPath $TrackedLicense.Path -Algorithm SHA256).Hash
  if ($ActualLicenseHash -ne $TrackedLicense.Sha256) {
    throw "El texto de licencia GNU está incompleto o fue modificado: $($TrackedLicense.Path)"
  }
}

if ($Version -notmatch "^\d+\.\d+\.\d+$") {
  throw "La versión '$Version' debe usar el formato estable X.Y.Z."
}

if ([string]$TauriConfig.version -ne $Version) {
  throw "Las versiones de package.json y tauri.conf.json no coinciden."
}

$CargoManifest = Get-Content -LiteralPath (Join-Path $ProjectRoot "src-tauri\Cargo.toml") -Raw -Encoding UTF8
if ($CargoManifest -notmatch "(?m)^version\s*=\s*`"$([regex]::Escape($Version))`"\s*$") {
  throw "La versión de Cargo.toml no coincide con $Version."
}

$PythonManifest = Get-Content -LiteralPath (Join-Path $ProjectRoot "sidecar\pyproject.toml") -Raw -Encoding UTF8
if ($PythonManifest -notmatch "(?m)^version\s*=\s*`"$([regex]::Escape($Version))`"\s*$") {
  throw "La versión de pyproject.toml no coincide con $Version."
}

$DataPathsSource = Get-Content -LiteralPath (Join-Path $ProjectRoot "sidecar\transcriptor_engine\paths.py") -Raw -Encoding UTF8
if ($DataPathsSource -notmatch '(?m)^APP_DATA_DIRECTORY\s*=\s*"([^"]+)"') {
  throw "No se pudo comprobar la carpeta de datos personales."
}
if ($Matches[1] -eq [string]$TauriConfig.productName) {
  throw "La carpeta de datos personales no puede coincidir con la carpeta de instalación."
}

$BundleTargets = @($TauriConfig.bundle.targets)
if ("nsis" -notin $BundleTargets -or "msi" -notin $BundleTargets) {
  throw "tauri.conf.json debe generar los instaladores NSIS y MSI."
}
if ("binaries/transcriptor-engine" -notin @($TauriConfig.bundle.externalBin)) {
  throw "tauri.conf.json no incluye el motor local como sidecar."
}
if ([string]$TauriConfig.bundle.windows.webviewInstallMode.type -ne "skip") {
  throw "El instalador público debe tratar WebView2 como requisito del sistema y no incorporar su bootstrapper."
}
if ([string]$TauriConfig.bundle.windows.nsis.installMode -ne "currentUser") {
  throw "El instalador recomendado debe funcionar sin privilegios de administrador."
}
$ConfiguredResources = @($TauriConfig.bundle.resources.PSObject.Properties.Name)
foreach ($RequiredResource in @(
  "binaries/transcriptor-engine-runtime/",
  "resources/licenses/",
  "../LICENSE",
  "../docs/THIRD_PARTY_NOTICES.md"
)) {
  if ($RequiredResource -notin $ConfiguredResources) {
    throw "Falta el recurso obligatorio '$RequiredResource' en tauri.conf.json."
  }
}
if ("resources/cuda/" -in $ConfiguredResources) {
  throw "El instalador público no puede incluir las bibliotecas propietarias de CUDA."
}

$AttestationAction =
  "actions/attest@f7c74d28b9d84cb8768d0b8ca14a4bac6ef463e6"
$AttestedWorkflows = @(
  (Join-Path $ProjectRoot ".github\workflows\release-windows.yml")
  (Join-Path $ProjectRoot `
      ".github\workflows\publish-signpath-candidate-v0.1.1.yml")
)
foreach ($AttestedWorkflow in $AttestedWorkflows) {
  if (-not (Test-Path -LiteralPath $AttestedWorkflow -PathType Leaf)) {
    throw "Falta un workflow de publicación con procedencia: $AttestedWorkflow"
  }
  $WorkflowText = Get-Content -LiteralPath $AttestedWorkflow -Raw -Encoding UTF8
  foreach ($RequiredWorkflowEvidence in @(
    $AttestationAction,
    "artifact-metadata: write",
    "attestations: write",
    "id-token: write",
    "gh attestation verify <archivo> -R NoelRDB/Transcriptor",
    "no sustituye Authenticode"
  )) {
    if (
      $WorkflowText.IndexOf(
        $RequiredWorkflowEvidence,
        [System.StringComparison]::Ordinal
      ) -lt 0
    ) {
      throw (
        "El workflow $([System.IO.Path]::GetFileName($AttestedWorkflow)) " +
        "no conserva la atestación obligatoria: $RequiredWorkflowEvidence"
      )
    }
  }
}

Push-Location $ProjectRoot
try {
  $ForbiddenTrackedPatterns = @(
    "sidecar/ffmpeg/",
    "src-tauri/resources/cuda/",
    "src-tauri/binaries/",
    "src-tauri/target/",
    "recordings/",
    "projects/",
    "exports/",
    "models/",
    "cache/",
    "logs/"
  )
  $ForbiddenTrackedExtensions = @(
    ".sqlite", ".sqlite3", ".db", ".wav", ".mp3", ".m4a", ".aac", ".flac", ".ogg",
    ".opus", ".mp4", ".mov", ".mkv", ".avi", ".webm", ".m4v", ".pfx", ".p12", ".pem", ".key"
  )
  $PublishableFiles = @(git ls-files --cached --others --exclude-standard)
  foreach ($PublishableFile in $PublishableFiles) {
    $Normalized = $PublishableFile.Replace("\", "/")
    if ($ForbiddenTrackedPatterns | Where-Object { $Normalized.StartsWith($_, [System.StringComparison]::OrdinalIgnoreCase) }) {
      throw "Git contiene una ruta privada o generada que no debe publicarse: $PublishableFile"
    }
    if ([System.IO.Path]::GetExtension($Normalized).ToLowerInvariant() -in $ForbiddenTrackedExtensions) {
      throw "Git contiene un archivo privado, multimedia o de firma: $PublishableFile"
    }
  }

  $TextExtensions = @(
    ".css", ".html", ".js", ".json", ".md", ".ps1", ".py", ".rs", ".toml",
    ".ts", ".tsx", ".txt", ".yaml", ".yml"
  )
  $PrivateReferences = @()
  foreach ($PublishableFile in $PublishableFiles) {
    if ($PublishableFile.Replace("\", "/") -eq "scripts/verify-release.ps1") {
      continue
    }
    if ([System.IO.Path]::GetExtension($PublishableFile).ToLowerInvariant() -notin $TextExtensions) {
      continue
    }
    $AbsolutePath = Join-Path $ProjectRoot $PublishableFile
    $Content = [System.IO.File]::ReadAllText($AbsolutePath)
    if ($Content -match "(?i)[A-Z]:\\Users\\(?!\.{3}\\)[^\\\r\n]+\\|/Users/(?!\.{3}/)[^/\r\n]+/|/home/(?!\.{3}/)[^/\r\n]+/") {
      $PrivateReferences += $PublishableFile
    }
  }
  if ($PrivateReferences.Count -gt 0) {
    throw "Se detectaron rutas personales en archivos publicables:`n$($PrivateReferences -join "`n")"
  }

  $ExpectedIgnoredPaths = @(
    "sidecar/ffmpeg/ffmpeg.exe",
    "src-tauri/binaries/transcriptor-engine-runtime/python312.dll",
    "src-tauri/resources/cuda/cublas64_12.dll",
    "src-tauri/target/release/transcriptor.exe",
    "recordings/private.wav",
    "projects/private.sqlite3",
    "release/Transcriptor-setup.exe",
    "signing-certificate.pfx"
  )
  foreach ($ExpectedIgnoredPath in $ExpectedIgnoredPaths) {
    git check-ignore --quiet --no-index -- $ExpectedIgnoredPath
    if ($LASTEXITCODE -ne 0) {
      throw "La ruta sensible o generada no está protegida por .gitignore: $ExpectedIgnoredPath"
    }
  }
}
finally {
  Pop-Location
}

function Invoke-CTranslate2BinaryAudit {
  param(
    [Parameter(Mandatory = $true)][string]$PythonExecutable,
    [Parameter(Mandatory = $true)][string]$CTranslate2Path,
    [Parameter(Mandatory = $true)][string[]]$AllowedRuntimeImports
  )

  foreach ($RequiredFile in @($PythonExecutable, $CTranslate2Path)) {
    if (-not (Test-Path -LiteralPath $RequiredFile -PathType Leaf)) {
      throw "Falta un archivo necesario para auditar CTranslate2: $RequiredFile"
    }
  }

  $Inspector = @'
import json
import sys

import pefile

pe = pefile.PE(sys.argv[1], fast_load=False)
imports = set()
for directory_name in ("DIRECTORY_ENTRY_IMPORT", "DIRECTORY_ENTRY_DELAY_IMPORT"):
    for entry in getattr(pe, directory_name, []) or []:
        name = (entry.dll or b"").decode("ascii", errors="strict").lower()
        if name:
            imports.add(name)

print(
    json.dumps(
        {
            "imports": sorted(imports),
        },
        ensure_ascii=True,
        separators=(",", ":"),
    )
)
'@

  $PreviousErrorActionPreference = $ErrorActionPreference
  $ErrorActionPreference = "Continue"
  $AuditOutput = @(
    $Inspector | & $PythonExecutable - $CTranslate2Path 2>&1
  )
  $AuditExitCode = $LASTEXITCODE
  $ErrorActionPreference = $PreviousErrorActionPreference
  if ($AuditExitCode -ne 0) {
    throw (
      "No se pudo auditar la tabla de importaciones PE de ctranslate2.dll:`n" +
      (($AuditOutput | Select-Object -Last 12) -join "`n")
    )
  }

  try {
    $Audit = ($AuditOutput -join "`n") | ConvertFrom-Json
  }
  catch {
    throw "La auditoría PE de ctranslate2.dll no produjo JSON válido."
  }

  $Imports = @($Audit.imports | ForEach-Object { "$_".ToLowerInvariant() })
  $NormalizedRuntimeImports = @(
    $AllowedRuntimeImports |
      ForEach-Object { "$_".ToLowerInvariant() } |
      Sort-Object -Unique
  )
  if (
    $NormalizedRuntimeImports.Count -lt 1 -or
    "libiomp5md.dll" -notin $NormalizedRuntimeImports
  ) {
    throw "El inventario CTranslate2 debe declarar el runtime Intel libiomp5md.dll."
  }
  if ($Imports.Count -lt 1) {
    throw "ctranslate2.dll no declara importaciones PE auditables."
  }
  $AllowedSystemImports = @(
    "advapi32.dll",
    "bcrypt.dll",
    "comdlg32.dll",
    "crypt32.dll",
    "dbghelp.dll",
    "gdi32.dll",
    "kernel32.dll",
    "ntdll.dll",
    "ole32.dll",
    "oleaut32.dll",
    "rpcrt4.dll",
    "secur32.dll",
    "shell32.dll",
    "shlwapi.dll",
    "ucrtbase.dll",
    "user32.dll",
    "version.dll",
    "winmm.dll",
    "ws2_32.dll"
  )
  $UnexpectedImports = @(
    $Imports |
      Where-Object {
        $_ -notin $NormalizedRuntimeImports -and
        $_ -notin $AllowedSystemImports -and
        $_ -notmatch "^(?:api|ext)-ms-win-[a-z0-9_-]+\.dll$" -and
        $_ -notmatch "^(?:concrt|msvcp|vcruntime)\d+(?:_\d+)?(?:_[a-z0-9_]+)?\.dll$"
      } |
      Sort-Object -Unique
  )
  if ($UnexpectedImports.Count -gt 0) {
    throw (
      "ctranslate2.dll importa bibliotecas fuera de sistema/MSVC/Intel OpenMP:`n" +
      ($UnexpectedImports -join "`n")
    )
  }

  return $Audit
}

function Get-PyInstallerCTranslate2Records {
  param(
    [Parameter(Mandatory = $true)][string]$PythonExecutable,
    [Parameter(Mandatory = $true)][string]$SidecarPath,
    [Parameter(Mandatory = $true)][string[]]$ExpectedRuntimeFileNames
  )

  $NormalizedExpectedNames = @(
    $ExpectedRuntimeFileNames |
      ForEach-Object {
        "ctranslate2/$([System.IO.Path]::GetFileName("$_").ToLowerInvariant())"
      } |
      Sort-Object -Unique
  )
  if (
    $NormalizedExpectedNames.Count -lt 2 -or
    "ctranslate2/ctranslate2.dll" -notin $NormalizedExpectedNames -or
    "ctranslate2/libiomp5md.dll" -notin $NormalizedExpectedNames
  ) {
    throw "El inventario no declara un conjunto CTranslate2 CPU completo."
  }

  $Inspector = @'
import hashlib
import json
import sys

from PyInstaller.archive.readers import CArchiveReader

archive = CArchiveReader(sys.argv[1])
expected = set(sys.argv[2].split(";"))
entries = {}
for original_name in archive.toc:
    normalized_name = original_name.replace("\\", "/").lower()
    if normalized_name in expected:
        if normalized_name in entries:
            raise RuntimeError(f"duplicate archive entry: {normalized_name}")
        data = archive.extract(original_name)
        entries[normalized_name] = {
            "sha256": hashlib.sha256(data).hexdigest(),
            "size": len(data),
        }
print(json.dumps(entries, sort_keys=True, separators=(",", ":")))
'@

  $PreviousErrorActionPreference = $ErrorActionPreference
  $ErrorActionPreference = "Continue"
  $InspectionOutput = @(
    $Inspector |
      & $PythonExecutable - $SidecarPath (
        $NormalizedExpectedNames -join ";"
      ) 2>&1
  )
  $InspectionExitCode = $LASTEXITCODE
  $ErrorActionPreference = $PreviousErrorActionPreference
  if ($InspectionExitCode -ne 0) {
    throw (
      "No se pudieron extraer los hashes CTranslate2 del sidecar:`n" +
      (($InspectionOutput | Select-Object -Last 12) -join "`n")
    )
  }
  try {
    $Records = ($InspectionOutput -join "`n") | ConvertFrom-Json
  }
  catch {
    throw "La inspección CTranslate2 del sidecar no produjo JSON válido."
  }
  $RecordNames = @($Records.PSObject.Properties.Name)
  foreach ($ExpectedRecordName in $NormalizedExpectedNames) {
    if ($ExpectedRecordName -notin $RecordNames) {
      throw "El sidecar no contiene el runtime CPU requerido: $ExpectedRecordName"
    }
  }
  if ($RecordNames.Count -ne $NormalizedExpectedNames.Count) {
    throw "El sidecar contiene un conjunto CTranslate2 inesperado."
  }
  return $Records
}

function Assert-ExactDirectoryTreeMatch {
  param(
    [Parameter(Mandatory = $true)][string]$ReferenceDirectory,
    [Parameter(Mandatory = $true)][string]$ActualDirectory,
    [Parameter(Mandatory = $true)][string]$Description
  )

  foreach ($RequiredDirectory in @($ReferenceDirectory, $ActualDirectory)) {
    if (-not (Test-Path -LiteralPath $RequiredDirectory -PathType Container)) {
      throw "Falta una carpeta para comprobar ${Description}: $RequiredDirectory"
    }
  }
  $ReferenceRoot = (Resolve-Path -LiteralPath $ReferenceDirectory).Path.TrimEnd(
    [System.IO.Path]::DirectorySeparatorChar,
    [System.IO.Path]::AltDirectorySeparatorChar
  )
  $ActualRoot = (Resolve-Path -LiteralPath $ActualDirectory).Path.TrimEnd(
    [System.IO.Path]::DirectorySeparatorChar,
    [System.IO.Path]::AltDirectorySeparatorChar
  )

  $ReferenceFiles = @(
    Get-ChildItem -LiteralPath $ReferenceRoot -Recurse -File -Force
  )
  $ActualFiles = @(
    Get-ChildItem -LiteralPath $ActualRoot -Recurse -File -Force
  )
  if ($ReferenceFiles.Count -lt 1 -or $ActualFiles.Count -lt 1) {
    throw "El árbol de $Description no puede estar vacío."
  }

  $ReferenceMap =
    [System.Collections.Generic.Dictionary[string, string]]::new(
      [System.StringComparer]::OrdinalIgnoreCase
    )
  foreach ($ReferenceFile in $ReferenceFiles) {
    $RelativePath = $ReferenceFile.FullName.Substring(
      $ReferenceRoot.Length
    ).TrimStart("\", "/").Replace("\", "/")
    if ($ReferenceMap.ContainsKey($RelativePath)) {
      throw "$Description contiene una ruta fuente duplicada: $RelativePath"
    }
    $ReferenceMap.Add(
      $RelativePath,
      (Get-FileHash -LiteralPath $ReferenceFile.FullName -Algorithm SHA256).Hash
    )
  }

  $ActualMap =
    [System.Collections.Generic.Dictionary[string, string]]::new(
      [System.StringComparer]::OrdinalIgnoreCase
    )
  foreach ($ActualFile in $ActualFiles) {
    $RelativePath = $ActualFile.FullName.Substring(
      $ActualRoot.Length
    ).TrimStart("\", "/").Replace("\", "/")
    if ($ActualMap.ContainsKey($RelativePath)) {
      throw "$Description contiene una ruta destino duplicada: $RelativePath"
    }
    $ActualMap.Add(
      $RelativePath,
      (Get-FileHash -LiteralPath $ActualFile.FullName -Algorithm SHA256).Hash
    )
  }

  foreach ($ExpectedRecord in $ReferenceMap.GetEnumerator()) {
    if (-not $ActualMap.ContainsKey($ExpectedRecord.Key)) {
      throw "$Description no conserva el archivo $($ExpectedRecord.Key)."
    }
    if ($ActualMap[$ExpectedRecord.Key] -cne $ExpectedRecord.Value) {
      throw "$Description modificó el archivo $($ExpectedRecord.Key)."
    }
  }
  if ($ActualMap.Count -ne $ReferenceMap.Count) {
    $UnexpectedPaths = @(
      $ActualMap.Keys |
        Where-Object { -not $ReferenceMap.ContainsKey($_) } |
        Sort-Object
    )
    throw (
      "$Description contiene archivos no declarados:`n" +
      ($UnexpectedPaths -join "`n")
    )
  }
}

if ($env:GITHUB_REF_TYPE -eq "tag") {
  if ($env:GITHUB_REF_NAME -notmatch "^v\d+\.\d+\.\d+$") {
    throw "La etiqueta $($env:GITHUB_REF_NAME) debe usar el formato vX.Y.Z."
  }
  if ($env:GITHUB_REF_NAME -ne "v$Version") {
    throw "La etiqueta $($env:GITHUB_REF_NAME) no coincide con la versión v$Version."
  }
}

if ($RequireRuntimeAssets) {
  $RuntimeFiles = @(
    @{
      Path = Join-Path $ProjectRoot "src-tauri\binaries\transcriptor-engine-x86_64-pc-windows-msvc.exe"
      MinimumBytes = 1MB
    },
    @{ Path = Join-Path $ProjectRoot "sidecar\ffmpeg\ffmpeg.exe"; MinimumBytes = 1MB },
    @{ Path = Join-Path $ProjectRoot "sidecar\ffmpeg\ffprobe.exe"; MinimumBytes = 1MB },
    @{ Path = Join-Path $ProjectRoot "sidecar\ffmpeg\LICENSE.txt"; MinimumBytes = 7KB },
    @{ Path = Join-Path $ProjectRoot "sidecar\ffmpeg\BUILD-SOURCE.txt"; MinimumBytes = 256 },
    @{
      Path = Join-Path $ProjectRoot "sidecar\ffmpeg\GCC-RUNTIME-LICENSES.txt"
      MinimumBytes = 1KB
    },
    @{
      Path = Join-Path $ProjectRoot "sidecar\ffmpeg\MINGW-W64-LICENSES.txt"
      MinimumBytes = 1KB
    }
  )
  foreach ($RuntimeFile in $RuntimeFiles) {
    if (-not (Test-Path -LiteralPath $RuntimeFile.Path -PathType Leaf)) {
      throw "Falta un componente necesario para el instalador: $($RuntimeFile.Path)"
    }
    if ((Get-Item -LiteralPath $RuntimeFile.Path).Length -lt $RuntimeFile.MinimumBytes) {
      throw "El componente parece incompleto: $($RuntimeFile.Path)"
    }
  }
  $SidecarPath = $RuntimeFiles[0].Path
  $SidecarRuntimeDirectory = Join-Path $ProjectRoot "src-tauri\binaries\transcriptor-engine-runtime"
  if (-not (Test-Path -LiteralPath $SidecarRuntimeDirectory -PathType Container)) {
    throw "Falta el runtime instalado junto al sidecar: $SidecarRuntimeDirectory"
  }
  $SidecarRuntimeFiles = @(
    Get-ChildItem -LiteralPath $SidecarRuntimeDirectory -Recurse -File -Force
  )
  $SidecarRuntimeBytes = ($SidecarRuntimeFiles | Measure-Object Length -Sum).Sum
  if ($SidecarRuntimeFiles.Count -lt 10 -or $SidecarRuntimeBytes -lt 50MB) {
    throw "El runtime de directorio del sidecar parece incompleto."
  }
  $SidecarArchive = & uv run --project (Join-Path $ProjectRoot "sidecar") --extra dev `
    pyi-archive_viewer -l $SidecarPath 2>&1
  if ($LASTEXITCODE -ne 0) {
    throw "No se pudo inspeccionar el contenido del sidecar público."
  }
  $SidecarArchiveText = @(
    $SidecarArchive
    $SidecarRuntimeFiles | ForEach-Object { $_.FullName }
  ) -join "`n"
  $ForbiddenSidecarPatterns = @(
    "(?im)(?:^|[./\\])av(?:[./\\]|$)",
    "(?im)(?:^|[./\\])(?:pytest|_pytest|ruff|iniconfig|pluggy|pygments|altgraph|pefile|pywin32_ctypes|PyInstaller)(?:[./\\]|$)",
    "(?im)(?:^|[./\\])(?:cublas|cudnn|cufft|curand|cusolver|cusparse|nvrtc|nvjitlink)[^/\\]*\.dll$",
    "(?im)(?:^|[./\\])vcomp[^/\\]*\.dll$"
  )
  foreach ($ForbiddenSidecarPattern in $ForbiddenSidecarPatterns) {
    if ($SidecarArchiveText -match $ForbiddenSidecarPattern) {
      throw "El sidecar público contiene una dependencia excluida: $($Matches[0])"
    }
  }

  $FfmpegVersion = (& (Join-Path $ProjectRoot "sidecar\ffmpeg\ffmpeg.exe") -version 2>&1) -join "`n"
  # FFmpeg cita automáticamente los argumentos que contienen comas al mostrar
  # la configuración, aunque conserve exactamente los mismos valores.
  $NormalizedFfmpegVersion = $FfmpegVersion.Replace("'", "")
  foreach ($RequiredFfmpegConfiguration in @(
    "--disable-autodetect",
    "--disable-network",
    "--disable-gpl",
    "--disable-nonfree",
    "--disable-libx264",
    "--disable-libx265",
    "--enable-version3",
    "--enable-static",
    "--disable-shared",
    "--enable-encoder=pcm_s16le,aac,mpeg4",
    "--enable-muxer=pcm_s16le,wav,mp4,mov",
    "--enable-filter=trim,atrim,setpts,asetpts,concat,aresample,scale,format,aformat"
  )) {
    if ($NormalizedFfmpegVersion.IndexOf(
        $RequiredFfmpegConfiguration,
        [System.StringComparison]::Ordinal
      ) -lt 0) {
      throw "FFmpeg no acredita la configuración requerida: $RequiredFfmpegConfiguration"
    }
  }
  if ($FfmpegVersion -match "--enable-(?:gpl|nonfree|lib)") {
    throw "FFmpeg activa un componente GPL, nonfree o una biblioteca externa."
  }

  $FfmpegArchiveLicense = Join-Path $ProjectRoot "sidecar\ffmpeg\LICENSE.txt"
  $FfmpegLicenseText = [System.IO.File]::ReadAllText($FfmpegArchiveLicense)
  if ($FfmpegLicenseText -notmatch "(?m)^\s*GNU LESSER GENERAL PUBLIC LICENSE\s*$" -or
      $FfmpegLicenseText -notmatch "(?m)^\s*Version 3, 29 June 2007\s*$" -or
      $FfmpegLicenseText -notmatch "(?m)^\s*6\. Revised Versions of the GNU Lesser General Public License\.\s*$") {
    throw "El LICENSE.txt extraído de FFmpeg no es el texto completo de LGPL v3."
  }
  $TrackedLgplText = [System.IO.File]::ReadAllText(
    (Join-Path $ProjectRoot "docs\licenses\LGPL-3.0.txt")
  )
  # La copia histórica que distribuye FFmpeg conserva http://fsf.org/ y la
  # copia documental actual usa https://fsf.org/. El contenido legal restante
  # debe continuar coincidiendo exactamente.
  $NormalizedFfmpegLicense = $FfmpegLicenseText.Replace("`r`n", "`n").Replace(
    "http://fsf.org/",
    "https://fsf.org/"
  ).TrimEnd() + "`n"
  $NormalizedTrackedLgpl = $TrackedLgplText.Replace("`r`n", "`n").Replace(
    "http://fsf.org/",
    "https://fsf.org/"
  ).TrimEnd() + "`n"
  if ($NormalizedFfmpegLicense -cne $NormalizedTrackedLgpl) {
    throw "LICENSE.txt no coincide con el texto LGPL v3 completo y versionado."
  }

  $FfmpegSourceManifestPath = Join-Path $ProjectRoot "sidecar\ffmpeg\BUILD-SOURCE.txt"
  $FfmpegSourceManifest = [System.IO.File]::ReadAllText($FfmpegSourceManifestPath)
  $FfmpegGccRuntimeLicensesPath = Join-Path $ProjectRoot `
    "sidecar\ffmpeg\GCC-RUNTIME-LICENSES.txt"
  $FfmpegMingwRuntimeLicensesPath = Join-Path $ProjectRoot `
    "sidecar\ffmpeg\MINGW-W64-LICENSES.txt"
  $ExpectedFfmpegSourceAsset = "Transcriptor-$Version-FFmpeg-corresponding-source.tar.gz"
  if (
    $FfmpegSourceManifest -notmatch
      "(?m)^Source repository:\s+https://github\.com/FFmpeg/FFmpeg\.git\s*$" -or
    $FfmpegSourceManifest -notmatch
      "(?m)^Source commit:\s+0869e710e6876792fbcebccb536ad620d8e65b97\s*$" -or
    $FfmpegSourceManifest -notmatch
      "(?m)^Corresponding source asset:\s+$([regex]::Escape($ExpectedFfmpegSourceAsset))\s*$" -or
    $FfmpegSourceManifest -notmatch
      "(?m)^Corresponding source SHA-256:\s+[a-f0-9]{64}\s*$" -or
    $FfmpegSourceManifest -notmatch
      "(?m)^Build script:\s+scripts/build-ffmpeg-windows\.sh\s*$" -or
    $FfmpegSourceManifest -notmatch
      "(?m)^Target:\s+x86_64-w64-mingw32\s*$" -or
    $FfmpegSourceManifest -notmatch
      "(?m)^License profile:\s+GNU LGPL v3 or later\s*$" -or
    $FfmpegSourceManifest -notmatch
      "(?m)^Configuration:\s+.*--disable-autodetect.*--disable-network.*--enable-version3.*$" -or
    $FfmpegSourceManifest -notmatch
      "(?m)^Target compiler:\s+x86_64-w64-mingw32-gcc\s*$" -or
    $FfmpegSourceManifest -notmatch
      "(?m)^Target compiler version:\s+[^\r\n]+\s*$" -or
    $FfmpegSourceManifest -notmatch
      "(?m)^GCC runtime package:\s+[^\r\n=]+=[^\r\n]+\s*$" -or
    $FfmpegSourceManifest -notmatch
      "(?m)^GCC runtime license:\s+GCC-RUNTIME-LICENSES\.txt\s*$" -or
    $FfmpegSourceManifest -notmatch
      "(?m)^GCC runtime license SHA-256:\s+[a-f0-9]{64}\s*$" -or
    $FfmpegSourceManifest -notmatch
      "(?m)^MinGW-w64 runtime package:\s+[^\r\n=]+=[^\r\n]+\s*$" -or
    $FfmpegSourceManifest -notmatch
      "(?m)^MinGW-w64 licenses:\s+MINGW-W64-LICENSES\.txt\s*$" -or
    $FfmpegSourceManifest -notmatch
      "(?m)^MinGW-w64 licenses SHA-256:\s+[a-f0-9]{64}\s*$" -or
    $FfmpegSourceManifest -match "--enable-(?:gpl|nonfree|lib)"
  ) {
    throw "BUILD-SOURCE.txt no acredita la fuente exacta y configuración LGPL v3 de FFmpeg."
  }
  $ExpectedGccRuntimeLicenseHash = [regex]::Match(
    $FfmpegSourceManifest,
    "(?m)^GCC runtime license SHA-256:\s+([a-f0-9]{64})\s*$"
  ).Groups[1].Value
  $ExpectedMingwRuntimeLicenseHash = [regex]::Match(
    $FfmpegSourceManifest,
    "(?m)^MinGW-w64 licenses SHA-256:\s+([a-f0-9]{64})\s*$"
  ).Groups[1].Value
  $ActualGccRuntimeLicenseHash = (
    Get-FileHash -LiteralPath $FfmpegGccRuntimeLicensesPath -Algorithm SHA256
  ).Hash.ToLowerInvariant()
  $ActualMingwRuntimeLicenseHash = (
    Get-FileHash -LiteralPath $FfmpegMingwRuntimeLicensesPath -Algorithm SHA256
  ).Hash.ToLowerInvariant()
  if (
    $ActualGccRuntimeLicenseHash -cne $ExpectedGccRuntimeLicenseHash -or
    $ActualMingwRuntimeLicenseHash -cne $ExpectedMingwRuntimeLicenseHash
  ) {
    throw "Los avisos GCC/MinGW-w64 no coinciden con la procedencia FFmpeg."
  }
  if (
    -not (Select-String -LiteralPath $FfmpegGccRuntimeLicensesPath `
      -Pattern "GCC Runtime Library Exception" -Quiet) -or
    -not (Select-String -LiteralPath $FfmpegMingwRuntimeLicensesPath `
      -Pattern "Zope Public License|ZPL-2|public domain" -Quiet)
  ) {
    throw "Los avisos GCC Runtime Exception o MinGW-w64 están incompletos."
  }

  $RuntimeLicenseDirectory = Join-Path $ProjectRoot "src-tauri\resources\licenses"
  $RuntimeLicenses = @(
    Get-ChildItem -LiteralPath $RuntimeLicenseDirectory -File -ErrorAction SilentlyContinue
  )
  foreach ($LicensePattern in @(
    "FFmpeg-BUILD-SOURCE.txt",
    "FFmpeg-GCC-RUNTIME-LICENSES.txt",
    "FFmpeg-LICENSE.txt",
    "FFmpeg-MINGW-W64-LICENSES.txt",
    "GPL-3.0.txt",
    "LGPL-3.0.txt",
    "INTEL-SIMPLIFIED-SOFTWARE-LICENSE.txt",
    "PYTHON-RUNTIME-INVENTORY.json",
    "PYTHON-RUNTIME-LICENSES.json"
  )) {
    if (-not ($RuntimeLicenses | Where-Object { $_.Name -like $LicensePattern })) {
      throw "Falta el aviso de redistribución '$LicensePattern'."
    }
  }

  $ExpectedRuntimeLicenseSources = @{
    "FFmpeg-BUILD-SOURCE.txt" = $FfmpegSourceManifestPath
    "FFmpeg-GCC-RUNTIME-LICENSES.txt" = $FfmpegGccRuntimeLicensesPath
    "FFmpeg-LICENSE.txt" = $FfmpegArchiveLicense
    "FFmpeg-MINGW-W64-LICENSES.txt" = $FfmpegMingwRuntimeLicensesPath
    "GPL-3.0.txt" = Join-Path $ProjectRoot "docs\licenses\GPL-3.0.txt"
    "LGPL-3.0.txt" = Join-Path $ProjectRoot "docs\licenses\LGPL-3.0.txt"
    "INTEL-SIMPLIFIED-SOFTWARE-LICENSE.txt" = Join-Path $ProjectRoot `
      "docs\licenses\INTEL-SIMPLIFIED-SOFTWARE-LICENSE.txt"
    "PYTHON-RUNTIME-INVENTORY.json" = Join-Path $ProjectRoot `
      "docs\licenses\PYTHON-RUNTIME-INVENTORY.json"
  }
  foreach ($RuntimeLicenseName in $ExpectedRuntimeLicenseSources.Keys) {
    $RuntimeLicensePath = Join-Path $RuntimeLicenseDirectory $RuntimeLicenseName
    $SourceLicensePath = $ExpectedRuntimeLicenseSources[$RuntimeLicenseName]
    if ((Get-FileHash -LiteralPath $RuntimeLicensePath -Algorithm SHA256).Hash -ne
        (Get-FileHash -LiteralPath $SourceLicensePath -Algorithm SHA256).Hash) {
      throw "El aviso empaquetado '$RuntimeLicenseName' no coincide con su fuente exacta."
    }
  }

  function ConvertTo-CanonicalRuntimeName {
    param([Parameter(Mandatory = $true)][string]$Name)
    return ($Name.Trim().ToLowerInvariant() -replace "[-_.]+", "-")
  }

  $RuntimeInventoryPath = Join-Path $ProjectRoot `
    "docs\licenses\PYTHON-RUNTIME-INVENTORY.json"
  $RuntimeLicenseManifestPath = Join-Path $RuntimeLicenseDirectory `
    "PYTHON-RUNTIME-LICENSES.json"
  $RuntimeInventory = Get-Content -LiteralPath $RuntimeInventoryPath `
    -Raw -Encoding UTF8 | ConvertFrom-Json
  $RuntimeLicenseManifest = Get-Content -LiteralPath $RuntimeLicenseManifestPath `
    -Raw -Encoding UTF8 | ConvertFrom-Json
  if (
    [int]$RuntimeInventory.schemaVersion -ne 1 -or
    [int]$RuntimeLicenseManifest.schemaVersion -ne 1
  ) {
    throw "El inventario o manifiesto de licencias Python no es compatible."
  }

  $ExpectedRuntimePairs = @(
    $RuntimeInventory.distributions | ForEach-Object {
      "{0}=={1}" -f (ConvertTo-CanonicalRuntimeName "$($_.name)"), "$($_.version)"
    }
  )
  $ActualRuntimePairs = @(
    $RuntimeLicenseManifest.distributions | ForEach-Object {
      "{0}=={1}" -f (ConvertTo-CanonicalRuntimeName "$($_.name)"), "$($_.version)"
    }
  )
  $RuntimePairDifference = @(
    Compare-Object `
      -ReferenceObject ($ExpectedRuntimePairs | Sort-Object) `
      -DifferenceObject ($ActualRuntimePairs | Sort-Object)
  )
  if ($RuntimePairDifference.Count -gt 0) {
    throw "El manifiesto legal no coincide exactamente con las dependencias runtime fijadas."
  }

  $ForbiddenRuntimeNames = @(
    $RuntimeInventory.excludedDistributions |
      ForEach-Object { ConvertTo-CanonicalRuntimeName "$_" }
  )
  foreach ($RuntimeDistribution in @($RuntimeLicenseManifest.distributions)) {
    $CanonicalRuntimeName = ConvertTo-CanonicalRuntimeName "$($RuntimeDistribution.name)"
    if ($CanonicalRuntimeName -in $ForbiddenRuntimeNames) {
      throw "El manifiesto legal incluye una dependencia excluida: $CanonicalRuntimeName"
    }
    if (@($RuntimeDistribution.files).Count -lt 1) {
      throw "Falta un texto legal para $CanonicalRuntimeName==$($RuntimeDistribution.version)."
    }
  }

  $ManifestFileRecords = @(
    $RuntimeLicenseManifest.distributions | ForEach-Object { @($_.files) }
    $RuntimeLicenseManifest.bootstrapComponents | ForEach-Object { @($_.files) }
  )
  $ManifestRelativePaths = @()
  $RuntimeLicensePrefix = [System.IO.Path]::GetFullPath(
    $RuntimeLicenseDirectory
  ).TrimEnd(
    [System.IO.Path]::DirectorySeparatorChar,
    [System.IO.Path]::AltDirectorySeparatorChar
  ) + [System.IO.Path]::DirectorySeparatorChar
  foreach ($ManifestFileRecord in $ManifestFileRecords) {
    $RelativePath = "$($ManifestFileRecord.path)"
    if (
      [System.IO.Path]::IsPathRooted($RelativePath) -or
      @($RelativePath -split "[/\\]+") -contains ".." -or
      $RelativePath -notmatch "^(?:python|bootstrap)/"
    ) {
      throw "El manifiesto legal contiene una ruta no segura: $RelativePath"
    }
    $FullLicensePath = [System.IO.Path]::GetFullPath(
      (Join-Path $RuntimeLicenseDirectory $RelativePath)
    )
    if (-not $FullLicensePath.StartsWith(
        $RuntimeLicensePrefix,
        [System.StringComparison]::OrdinalIgnoreCase
      )) {
      throw "Un texto legal queda fuera de resources/licenses: $RelativePath"
    }
    if (-not (Test-Path -LiteralPath $FullLicensePath -PathType Leaf)) {
      throw "El manifiesto legal apunta a un archivo inexistente: $RelativePath"
    }
    if ("$($ManifestFileRecord.sha256)" -notmatch "^[a-f0-9]{64}$") {
      throw "El manifiesto legal contiene un SHA-256 inválido: $RelativePath"
    }
    $ActualRuntimeLicenseHash = (
      Get-FileHash -LiteralPath $FullLicensePath -Algorithm SHA256
    ).Hash.ToLowerInvariant()
    if ($ActualRuntimeLicenseHash -cne "$($ManifestFileRecord.sha256)") {
      throw "Un texto legal no coincide con su hash: $RelativePath"
    }
    $ManifestRelativePaths += $RelativePath.Replace("\", "/")
  }
  if (($ManifestRelativePaths | Sort-Object -Unique).Count -ne $ManifestRelativePaths.Count) {
    throw "El manifiesto legal contiene colisiones de ruta."
  }

  $ActualManagedLicensePaths = @(
    foreach ($ManagedDirectoryName in @("python", "bootstrap")) {
      $ManagedDirectory = Join-Path $RuntimeLicenseDirectory $ManagedDirectoryName
      if (-not (Test-Path -LiteralPath $ManagedDirectory -PathType Container)) {
        throw "Falta la carpeta legal administrada: $ManagedDirectoryName"
      }
      Get-ChildItem -LiteralPath $ManagedDirectory -Recurse -File | ForEach-Object {
        $_.FullName.Substring($RuntimeLicensePrefix.Length).Replace("\", "/")
      }
    }
  )
  if (@(
      Compare-Object `
        -ReferenceObject ($ManifestRelativePaths | Sort-Object) `
        -DifferenceObject ($ActualManagedLicensePaths | Sort-Object)
    ).Count -gt 0) {
    throw "Hay textos legales sin manifestar o archivos manifestados ausentes."
  }

  foreach ($ExpectedDistribution in @($RuntimeInventory.distributions)) {
    $ExpectedCanonicalName = ConvertTo-CanonicalRuntimeName "$($ExpectedDistribution.name)"
    $ManifestDistribution = @(
      $RuntimeLicenseManifest.distributions |
        Where-Object {
          (ConvertTo-CanonicalRuntimeName "$($_.name)") -eq $ExpectedCanonicalName
        }
    )
    if ($ManifestDistribution.Count -ne 1) {
      throw "No existe un único registro legal para $ExpectedCanonicalName."
    }
    foreach ($RepositoryFile in @($ExpectedDistribution.repositoryFiles)) {
      if ($null -eq $RepositoryFile) { continue }
      $ExpectedSource = "repository:$($RepositoryFile.source)"
      $MatchingFile = @(
        $ManifestDistribution[0].files |
          Where-Object {
            "$($_.source)" -ceq $ExpectedSource -and
            "$($_.sha256)" -ceq "$($RepositoryFile.sha256)"
          }
      )
      if ($MatchingFile.Count -ne 1) {
        throw "Falta el texto legal versionado de $ExpectedCanonicalName."
      }
    }
    foreach ($PackageFile in @($ExpectedDistribution.packageFiles)) {
      if ($null -eq $PackageFile) { continue }
      $ExpectedSource = "package:$($PackageFile.source)"
      $MatchingFile = @(
        $ManifestDistribution[0].files |
          Where-Object {
            "$($_.source)" -ceq $ExpectedSource -and
            "$($_.sha256)" -ceq "$($PackageFile.sha256)"
          }
      )
      if ($MatchingFile.Count -ne 1) {
        throw "Falta un aviso incluido por $ExpectedCanonicalName."
      }
    }
  }

  $BootstrapNames = @(
    $RuntimeLicenseManifest.bootstrapComponents | ForEach-Object { "$($_.name)" }
  )
  foreach ($RequiredBootstrapName in @("PyInstaller", "Python")) {
    if ($RequiredBootstrapName -notin $BootstrapNames) {
      throw "Falta la licencia del componente de arranque $RequiredBootstrapName."
    }
  }

  $AllowedRootLicenseFiles = @(
    "FFmpeg-BUILD-SOURCE.txt",
    "FFmpeg-GCC-RUNTIME-LICENSES.txt",
    "FFmpeg-LICENSE.txt",
    "FFmpeg-MINGW-W64-LICENSES.txt",
    "GPL-3.0.txt",
    "INTEL-SIMPLIFIED-SOFTWARE-LICENSE.txt",
    "LGPL-3.0.txt",
    "PYTHON-RUNTIME-INVENTORY.json",
    "PYTHON-RUNTIME-LICENSES.json"
  )
  $UnexpectedRootLicenseFiles = @(
    Get-ChildItem -LiteralPath $RuntimeLicenseDirectory -File |
      Where-Object { $_.Name -notin $AllowedRootLicenseFiles }
  )
  if ($UnexpectedRootLicenseFiles.Count -gt 0) {
    throw "Hay avisos runtime obsoletos o no inventariados: $($UnexpectedRootLicenseFiles.Name -join ', ')"
  }
}

function Test-InstallerNameForVersion {
  param(
    [Parameter(Mandatory = $true)][string]$Name,
    [Parameter(Mandatory = $true)][string]$ExpectedVersion
  )

  $EscapedVersion = [regex]::Escape($ExpectedVersion)
  return $Name -match "(?i)(?:^|[_-])$EscapedVersion(?:[_-]|$)"
}

function Assert-ExactInstallerVersion {
  param(
    [Parameter(Mandatory = $true)][string]$ActualVersion,
    [Parameter(Mandatory = $true)][string]$ExpectedVersion,
    [Parameter(Mandatory = $true)][string]$Description
  )

  $ActualMatch = [regex]::Match(
    $ActualVersion.Trim(),
    "^(?<major>\d+)\.(?<minor>\d+)\.(?<patch>\d+)(?:\.(?<revision>\d+))?$"
  )
  $ExpectedMatch = [regex]::Match(
    $ExpectedVersion,
    "^(?<major>\d+)\.(?<minor>\d+)\.(?<patch>\d+)$"
  )
  if (-not $ActualMatch.Success -or -not $ExpectedMatch.Success) {
    throw "$Description declara una versión no válida: '$ActualVersion'."
  }
  foreach ($Part in @("major", "minor", "patch")) {
    if ([int64]$ActualMatch.Groups[$Part].Value -ne [int64]$ExpectedMatch.Groups[$Part].Value) {
      throw "$Description declara '$ActualVersion' y se esperaba '$ExpectedVersion'."
    }
  }
  if (
    $ActualMatch.Groups["revision"].Success -and
    [int64]$ActualMatch.Groups["revision"].Value -ne 0
  ) {
    throw "$Description declara '$ActualVersion' y se esperaba '$ExpectedVersion' (o '$ExpectedVersion.0')."
  }
}

function Get-MsiProperty {
  param(
    [Parameter(Mandatory = $true)][string]$Path,
    [Parameter(Mandatory = $true)][string]$Property
  )

  $WindowsInstaller = $null
  $Database = $null
  $View = $null
  $Record = $null
  try {
    $WindowsInstaller = New-Object -ComObject WindowsInstaller.Installer
    $Database = $WindowsInstaller.GetType().InvokeMember(
      "OpenDatabase",
      "InvokeMethod",
      $null,
      $WindowsInstaller,
      @($Path, 0)
    )
    $Query = "SELECT ``Value`` FROM ``Property`` WHERE ``Property``='$Property'"
    $View = $Database.GetType().InvokeMember(
      "OpenView",
      "InvokeMethod",
      $null,
      $Database,
      @($Query)
    )
    [void]$View.GetType().InvokeMember(
      "Execute",
      "InvokeMethod",
      $null,
      $View,
      $null
    )
    $Record = $View.GetType().InvokeMember(
      "Fetch",
      "InvokeMethod",
      $null,
      $View,
      $null
    )
    if ($null -eq $Record) {
      throw "La propiedad MSI '$Property' no existe."
    }
    return [string]$Record.GetType().InvokeMember(
      "StringData",
      "GetProperty",
      $null,
      $Record,
      @(1)
    )
  }
  finally {
    foreach ($ComObject in @($Record, $View, $Database, $WindowsInstaller)) {
      if (
        $null -ne $ComObject -and
        [System.Runtime.InteropServices.Marshal]::IsComObject($ComObject)
      ) {
        [void][System.Runtime.InteropServices.Marshal]::FinalReleaseComObject($ComObject)
      }
    }
  }
}

function Resolve-SevenZipExecutable {
  $Candidates = @()
  if (-not [string]::IsNullOrWhiteSpace($env:TRANSCRIPTOR_7ZIP_PATH)) {
    $Candidates += $env:TRANSCRIPTOR_7ZIP_PATH
  }
  $SevenZipCommand = Get-Command "7z.exe" -ErrorAction SilentlyContinue
  if ($SevenZipCommand) {
    $Candidates += $SevenZipCommand.Source
  }
  if (-not [string]::IsNullOrWhiteSpace($env:ProgramFiles)) {
    $Candidates += Join-Path $env:ProgramFiles "7-Zip\7z.exe"
  }
  if (-not [string]::IsNullOrWhiteSpace(${env:ProgramFiles(x86)})) {
    $Candidates += Join-Path ${env:ProgramFiles(x86)} "7-Zip\7z.exe"
  }
  if (-not [string]::IsNullOrWhiteSpace($env:ChocolateyInstall)) {
    $Candidates += Join-Path $env:ChocolateyInstall "bin\7z.exe"
  }

  foreach ($Candidate in @($Candidates | Select-Object -Unique)) {
    if (Test-Path -LiteralPath $Candidate -PathType Leaf) {
      return (Resolve-Path -LiteralPath $Candidate).Path
    }
  }
  throw (
    "La inspección obligatoria del payload NSIS requiere 7-Zip. " +
    "Instala 7-Zip o define TRANSCRIPTOR_7ZIP_PATH con la ruta exacta de 7z.exe."
  )
}

function Expand-NsisPayload {
  param(
    [Parameter(Mandatory = $true)][string]$SevenZip,
    [Parameter(Mandatory = $true)][System.IO.FileInfo]$Installer,
    [Parameter(Mandatory = $true)][string]$Destination
  )

  New-Item -ItemType Directory -Path $Destination -Force | Out-Null
  $SevenZipOutput = @(
    & $SevenZip "x" "-y" "-bb0" "-o$Destination" "--" $Installer.FullName 2>&1
  )
  if ($LASTEXITCODE -ne 0) {
    $Detail = ($SevenZipOutput | Select-Object -Last 12) -join "`n"
    throw "7-Zip no pudo extraer $($Installer.Name).`n$Detail"
  }
}

function Expand-MsiPayload {
  param(
    [Parameter(Mandatory = $true)][System.IO.FileInfo]$Installer,
    [Parameter(Mandatory = $true)][string]$Destination
  )

  $MsiExec = Join-Path $env:WINDIR "System32\msiexec.exe"
  if (-not (Test-Path -LiteralPath $MsiExec -PathType Leaf)) {
    throw "Windows Installer no está disponible para inspeccionar $($Installer.Name)."
  }
  New-Item -ItemType Directory -Path $Destination -Force | Out-Null
  $ArgumentLine = '/a "{0}" /qn TARGETDIR="{1}" REBOOT=ReallySuppress' -f
    $Installer.FullName,
    $Destination
  $Process = Start-Process `
    -FilePath $MsiExec `
    -ArgumentList $ArgumentLine `
    -Wait `
    -PassThru `
    -WindowStyle Hidden
  if ($Process.ExitCode -ne 0) {
    throw "Windows Installer no pudo extraer $($Installer.Name) (código $($Process.ExitCode))."
  }
}

function Assert-PayloadLicensesMatch {
  param(
    [Parameter(Mandatory = $true)][System.IO.FileInfo]$Installer,
    [Parameter(Mandatory = $true)][string]$PayloadDirectory,
    [Parameter(Mandatory = $true)][System.IO.FileInfo[]]$PayloadFiles
  )

  $ExpectedFiles =
    [System.Collections.Generic.Dictionary[string, string]]::new(
      [System.StringComparer]::OrdinalIgnoreCase
    )
  $RuntimeLicenseDirectory = Join-Path (
    $ProjectRoot
  ) "src-tauri\resources\licenses"
  if (-not (Test-Path -LiteralPath $RuntimeLicenseDirectory -PathType Container)) {
    throw "Falta el árbol legal auditado que debe entrar en los instaladores."
  }
  $ResolvedRuntimeLicenseDirectory = (
    Resolve-Path -LiteralPath $RuntimeLicenseDirectory
  ).Path.TrimEnd(
    [System.IO.Path]::DirectorySeparatorChar,
    [System.IO.Path]::AltDirectorySeparatorChar
  )
  $RuntimeLicensePrefix =
    $ResolvedRuntimeLicenseDirectory + [System.IO.Path]::DirectorySeparatorChar
  $RuntimeLicenseFiles = @(
    Get-ChildItem `
      -LiteralPath $ResolvedRuntimeLicenseDirectory `
      -Recurse `
      -File `
      -Force
  )
  if ($RuntimeLicenseFiles.Count -eq 0) {
    throw "El árbol legal runtime está vacío."
  }
  foreach ($SourceFile in $RuntimeLicenseFiles) {
    if (
      -not $SourceFile.FullName.StartsWith(
        $RuntimeLicensePrefix,
        [System.StringComparison]::OrdinalIgnoreCase
      )
    ) {
      throw "Un texto legal runtime queda fuera de su raíz auditada."
    }
    $RelativeSourcePath = $SourceFile.FullName.Substring(
      $RuntimeLicensePrefix.Length
    ).Replace("\", "/")
    $PayloadKey = "licenses/runtime/$RelativeSourcePath"
    if ($ExpectedFiles.ContainsKey($PayloadKey)) {
      throw "El árbol legal fuente contiene una ruta duplicada: $PayloadKey"
    }
    $ExpectedFiles.Add($PayloadKey, $SourceFile.FullName)
  }

  foreach ($RootLicense in @(
    @{
      # NSIS aplica el destino configurado; WiX conserva el nombre fuente.
      Key = if ($Installer.Extension -ieq ".msi") {
        "licenses/LICENSE"
      }
      else {
        "licenses/Transcriptor-MIT.txt"
      }
      Source = Join-Path $ProjectRoot "LICENSE"
    },
    @{
      Key = "licenses/THIRD_PARTY_NOTICES.md"
      Source = Join-Path $ProjectRoot "docs\THIRD_PARTY_NOTICES.md"
    }
  )) {
    if (-not (Test-Path -LiteralPath $RootLicense.Source -PathType Leaf)) {
      throw "Falta el aviso fuente obligatorio: $($RootLicense.Source)"
    }
    if ($ExpectedFiles.ContainsKey($RootLicense.Key)) {
      throw "La ruta legal esperada está duplicada: $($RootLicense.Key)"
    }
    $ExpectedFiles.Add($RootLicense.Key, $RootLicense.Source)
  }

  # PyInstaller puede conservar avisos de varias distribuciones dentro de sus
  # metadatos. Sólo aceptamos los que ya figuran en el manifiesto cerrado y
  # exigimos que la copia del runtime y la copia legal centralizada coincidan
  # con el SHA-256 registrado. La clave conserva distribución, versión y ruta
  # para que dos LICENSE con el mismo nombre nunca colisionen.
  $RuntimeManifestPath = Join-Path $RuntimeLicenseDirectory `
    "PYTHON-RUNTIME-LICENSES.json"
  $RuntimeManifest = Get-Content -LiteralPath $RuntimeManifestPath `
    -Raw -Encoding UTF8 | ConvertFrom-Json
  $RuntimeSidecarDirectory = Join-Path (
    $ProjectRoot
  ) "src-tauri\binaries\transcriptor-engine-runtime"
  if (-not (Test-Path -LiteralPath $RuntimeSidecarDirectory -PathType Container)) {
    throw "Falta el runtime del motor cuyos metadatos legales deben auditarse."
  }
  $ResolvedRuntimeSidecarDirectory = (
    Resolve-Path -LiteralPath $RuntimeSidecarDirectory
  ).Path.TrimEnd(
    [System.IO.Path]::DirectorySeparatorChar,
    [System.IO.Path]::AltDirectorySeparatorChar
  )
  $RuntimeSidecarPrefix =
    $ResolvedRuntimeSidecarDirectory + [System.IO.Path]::DirectorySeparatorChar

  foreach ($RuntimeDistribution in @($RuntimeManifest.distributions)) {
    foreach ($LicenseRecord in @($RuntimeDistribution.files)) {
      $WheelLicenseMatch = [regex]::Match(
        "$($LicenseRecord.source)",
        "(?i)^wheel:(?<path>.+\.dist-info/licenses/.+)$"
      )
      if (-not $WheelLicenseMatch.Success) {
        continue
      }
      $RelativeMetadataPath = $WheelLicenseMatch.Groups["path"].Value
      $UnsafeMetadataSegments = @(
        $RelativeMetadataPath -split "/" |
          Where-Object { $_ -in @("", ".", "..") }
      )
      if (
        [System.IO.Path]::IsPathRooted($RelativeMetadataPath) -or
        $UnsafeMetadataSegments.Count -ne 0
      ) {
        throw "El manifiesto contiene una ruta legal de wheel no segura."
      }
      $SidecarLicensePath = [System.IO.Path]::GetFullPath(
        $(Join-Path $ResolvedRuntimeSidecarDirectory (
          $RelativeMetadataPath.Replace(
            "/",
            [System.IO.Path]::DirectorySeparatorChar
          )
        ))
      )
      if (-not $SidecarLicensePath.StartsWith(
        $RuntimeSidecarPrefix,
        [System.StringComparison]::OrdinalIgnoreCase
      )) {
        throw "Un aviso de wheel queda fuera del runtime permitido."
      }
      if (-not (Test-Path -LiteralPath $SidecarLicensePath -PathType Leaf)) {
        continue
      }

      $CentralLicensePath = [System.IO.Path]::GetFullPath(
        $(Join-Path $ResolvedRuntimeLicenseDirectory "$($LicenseRecord.path)")
      )
      if (-not $CentralLicensePath.StartsWith(
        $RuntimeLicensePrefix,
        [System.StringComparison]::OrdinalIgnoreCase
      )) {
        throw "Un aviso del manifiesto queda fuera de la raíz legal auditada."
      }
      if (-not (Test-Path -LiteralPath $CentralLicensePath -PathType Leaf)) {
        throw "Falta un aviso centralizado declarado en el manifiesto runtime."
      }
      $ExpectedRecordHash = "$($LicenseRecord.sha256)".ToLowerInvariant()
      if ($ExpectedRecordHash -notmatch "^[a-f0-9]{64}$") {
        throw "El manifiesto runtime contiene un SHA-256 legal no válido."
      }
      $SidecarLicenseHash = (
        Get-FileHash -LiteralPath $SidecarLicensePath -Algorithm SHA256
      ).Hash.ToLowerInvariant()
      $CentralLicenseHash = (
        Get-FileHash -LiteralPath $CentralLicensePath -Algorithm SHA256
      ).Hash.ToLowerInvariant()
      if (
        $SidecarLicenseHash -cne $ExpectedRecordHash -or
        $CentralLicenseHash -cne $ExpectedRecordHash
      ) {
        throw "Una licencia conservada por PyInstaller difiere del manifiesto."
      }
      $PayloadKey = "transcriptor-engine-runtime/$RelativeMetadataPath"
      if ($ExpectedFiles.ContainsKey($PayloadKey)) {
        throw "El manifiesto declara dos veces la licencia $PayloadKey."
      }
      $ExpectedFiles.Add($PayloadKey, $CentralLicensePath)
    }
  }

  $ResolvedPayloadDirectory = (
    Resolve-Path -LiteralPath $PayloadDirectory
  ).Path.TrimEnd(
    [System.IO.Path]::DirectorySeparatorChar,
    [System.IO.Path]::AltDirectorySeparatorChar
  )
  $PayloadPrefix =
    $ResolvedPayloadDirectory + [System.IO.Path]::DirectorySeparatorChar
  $PayloadLicenseFiles =
    [System.Collections.Generic.Dictionary[
      string,
      System.Collections.Generic.List[System.IO.FileInfo]
    ]]::new([System.StringComparer]::OrdinalIgnoreCase)

  foreach ($PayloadFile in $PayloadFiles) {
    if (
      -not $PayloadFile.FullName.StartsWith(
        $PayloadPrefix,
        [System.StringComparison]::OrdinalIgnoreCase
      )
    ) {
      throw "$($Installer.Name) extrajo un archivo fuera de su raíz temporal."
    }
    $RelativePayloadPath = $PayloadFile.FullName.Substring(
      $PayloadPrefix.Length
    ).Replace("\", "/")
    $LicenseMatch = [regex]::Match(
      $RelativePayloadPath,
      "(?i)(?:^|/)(?<key>transcriptor-engine-runtime/.+\.dist-info/licenses/.+)$"
    )
    if (-not $LicenseMatch.Success) {
      $LicenseMatch = [regex]::Match(
      $RelativePayloadPath,
      "(?i)(?:^|/)(?<key>licenses/.+)$"
      )
    }
    if (-not $LicenseMatch.Success) {
      continue
    }
    $PayloadKey = $LicenseMatch.Groups["key"].Value
    if (-not $ExpectedFiles.ContainsKey($PayloadKey)) {
      throw (
        "$($Installer.Name) contiene un aviso legal no auditado: " +
        $RelativePayloadPath
      )
    }
    if (-not $PayloadLicenseFiles.ContainsKey($PayloadKey)) {
      $PayloadLicenseFiles.Add(
        $PayloadKey,
        [System.Collections.Generic.List[System.IO.FileInfo]]::new()
      )
    }
    $PayloadLicenseFiles[$PayloadKey].Add($PayloadFile)
  }

  foreach ($ExpectedFile in @(
    $ExpectedFiles.GetEnumerator() | Sort-Object Key
  )) {
    if (
      -not $PayloadLicenseFiles.ContainsKey($ExpectedFile.Key) -or
      $PayloadLicenseFiles[$ExpectedFile.Key].Count -ne 1
    ) {
      $FoundCount = if ($PayloadLicenseFiles.ContainsKey($ExpectedFile.Key)) {
        $PayloadLicenseFiles[$ExpectedFile.Key].Count
      }
      else {
        0
      }
      throw (
        "$($Installer.Name) debe contener exactamente una copia de " +
        "$($ExpectedFile.Key); encontradas: $FoundCount."
      )
    }
    $ExpectedHash = (
      Get-FileHash -LiteralPath $ExpectedFile.Value -Algorithm SHA256
    ).Hash
    $PayloadHash = (
      Get-FileHash `
        -LiteralPath $PayloadLicenseFiles[$ExpectedFile.Key][0].FullName `
        -Algorithm SHA256
    ).Hash
    if ($ExpectedHash -cne $PayloadHash) {
      throw (
        "$($Installer.Name) contiene un aviso legal distinto del auditado: " +
        $ExpectedFile.Key
      )
    }
  }

  if ($PayloadLicenseFiles.Count -ne $ExpectedFiles.Count) {
    throw (
      "$($Installer.Name) no conserva el conjunto legal exacto: " +
      "esperados=$($ExpectedFiles.Count), encontrados=$($PayloadLicenseFiles.Count)."
    )
  }
}

function Assert-PayloadAndSidecarAreClean {
  param(
    [Parameter(Mandatory = $true)][System.IO.FileInfo]$Installer,
    [Parameter(Mandatory = $true)][string]$PayloadDirectory,
    [Parameter(Mandatory = $true)][string]$ExpectedSidecarPath,
    [Parameter(Mandatory = $true)][string]$ExpectedRuntimeDirectory
  )

  $PayloadFiles = @(Get-ChildItem -LiteralPath $PayloadDirectory -Recurse -File)
  $EmbeddedWebViewBootstrappers = @(
    $PayloadFiles |
      Where-Object {
        $_.Name -ieq "MicrosoftEdgeWebview2Setup.exe"
      }
  )
  if ($EmbeddedWebViewBootstrappers.Count -gt 0) {
    $RelativeBootstrappers = @(
      $EmbeddedWebViewBootstrappers |
        ForEach-Object {
          $_.FullName.Substring($PayloadDirectory.Length).TrimStart("\", "/")
        }
    )
    throw (
      "$($Installer.Name) incorpora el bootstrapper propietario de WebView2 " +
      "que debe quedar fuera del artefacto OSS:`n" +
      ($RelativeBootstrappers -join "`n")
    )
  }
  Assert-PayloadLicensesMatch `
    -Installer $Installer `
    -PayloadDirectory $PayloadDirectory `
    -PayloadFiles $PayloadFiles
  $ForbiddenBinaryPatterns = @(
    "(?i)^cublas.*\.dll$",
    "(?i)^cudnn.*\.dll$",
    "(?i)^cu(?:fft|rand|solver|sparse).*\.dll$",
    "(?i)^nv(?:blas|rtc|jitlink|jpeg).*\.dll$",
    "(?i)^vcomp.*\.dll$",
    "(?i)^(?:lib)?av(?:codec|device|filter|format|util|resample|swresample|swscale).*\.(?:dll|pyd)$",
    "(?i)^(?:lib)?x26[45].*\.(?:dll|pyd)$"
  )
  $ForbiddenPayloadFiles = @(
    $PayloadFiles | Where-Object {
      $PayloadFile = $_
      $ForbiddenBinaryPatterns | Where-Object { $PayloadFile.Name -match $_ }
    }
  )
  if ($ForbiddenPayloadFiles.Count -gt 0) {
    $RelativeForbidden = @(
      $ForbiddenPayloadFiles |
        ForEach-Object {
          $_.FullName.Substring($PayloadDirectory.Length).TrimStart("\", "/")
        }
    )
    throw (
      "$($Installer.Name) contiene bibliotecas CUDA/NVIDIA, PyAV/FFmpeg o x264/x265 prohibidas:`n" +
      ($RelativeForbidden -join "`n")
    )
  }

  $Sidecars = @(
    $PayloadFiles |
      Where-Object { $_.Name -like "transcriptor-engine*.exe" }
  )
  if ($Sidecars.Count -ne 1) {
    throw "$($Installer.Name) debe contener exactamente un sidecar; encontrados: $($Sidecars.Count)."
  }
  if (-not (Test-Path -LiteralPath $ExpectedSidecarPath -PathType Leaf)) {
    throw "Falta el sidecar construido que debe compararse con el payload: $ExpectedSidecarPath"
  }
  $ExpectedSidecarHash = (
    Get-FileHash -LiteralPath $ExpectedSidecarPath -Algorithm SHA256
  ).Hash
  $PayloadSidecarHash = (
    Get-FileHash -LiteralPath $Sidecars[0].FullName -Algorithm SHA256
  ).Hash
  if ($ExpectedSidecarHash -cne $PayloadSidecarHash) {
    throw "$($Installer.Name) contiene un sidecar distinto del binario construido y auditado."
  }
  $PayloadRuntimeDirectories = @(
    Get-ChildItem -LiteralPath $PayloadDirectory -Recurse -Directory -Force |
      Where-Object { $_.Name -ieq "transcriptor-engine-runtime" }
  )
  if ($PayloadRuntimeDirectories.Count -ne 1) {
    throw (
      "$($Installer.Name) debe contener exactamente un runtime del sidecar; " +
      "encontrados: $($PayloadRuntimeDirectories.Count)."
    )
  }
  Assert-ExactDirectoryTreeMatch `
    -ReferenceDirectory $ExpectedRuntimeDirectory `
    -ActualDirectory $PayloadRuntimeDirectories[0].FullName `
    -Description "runtime instalado del sidecar"

  $ArchiveViewer = Join-Path $ProjectRoot (
    "sidecar\.venv\Scripts\pyi-archive_viewer.exe"
  )
  if (-not (Test-Path -LiteralPath $ArchiveViewer -PathType Leaf)) {
    throw (
      "Falta pyi-archive_viewer en el entorno bloqueado. " +
      "Ejecuta uv sync --project sidecar --extra dev --locked."
    )
  }
  $ArchiveEntries = @(
    & $ArchiveViewer -l $Sidecars[0].FullName 2>&1
  )
  if ($LASTEXITCODE -ne 0) {
    throw "No se pudo abrir como archivo PyInstaller el sidecar de $($Installer.Name)."
  }
  $ArchiveText = $ArchiveEntries -join "`n"
  $ForbiddenArchivePatterns = @(
    "(?i)(?:^|[^a-z0-9])nvidia(?:$|[^a-z0-9])",
    "(?i)cublas(?:lt)?64",
    "(?i)cudnn(?:_[a-z]+)?64",
    "(?i)nv(?:rtc|jitlink|blas|jpeg)64",
    "(?i)(?:^|[/\\])vcomp[^/\\]*\.dll",
    "(?i)(?:^|[^a-z0-9])av(?:$|[^a-z0-9])",
    "(?i)(?:lib)?av(?:codec|device|filter|format|util|resample|swresample|swscale)",
    "(?i)(?:lib)?x26[45]"
  )
  $ForbiddenArchiveMatches = @(
    $ForbiddenArchivePatterns |
      Where-Object { $ArchiveText -match $_ }
  )
  if ($ForbiddenArchiveMatches.Count -gt 0) {
    throw (
      "El sidecar extraído de $($Installer.Name) contiene entradas de " +
      "CUDA/NVIDIA, PyAV/FFmpeg o x264/x265."
    )
  }
}

if ($RequireInstallerPayloadInspection -and -not $RequireInstallers) {
  throw "-RequireInstallerPayloadInspection exige también -RequireInstallers."
}
if (
  [string]$env:CI -ieq "true" -and
  $RequireInstallers -and
  -not $RequireInstallerPayloadInspection
) {
  throw (
    "En CI, -RequireInstallers exige -RequireInstallerPayloadInspection; " +
    "no se permite publicar sin extraer y auditar ambos payloads."
  )
}

if ([string]::IsNullOrWhiteSpace($InstallerDirectory)) {
  $BundleDirectories = @(
    (Join-Path $ProjectRoot "src-tauri\target\x86_64-pc-windows-msvc\release\bundle"),
    (Join-Path $ProjectRoot "src-tauri\target\release\bundle")
  )
}
else {
  $RequestedInstallerDirectory = if ([System.IO.Path]::IsPathRooted($InstallerDirectory)) {
    $InstallerDirectory
  }
  else {
    Join-Path $ProjectRoot $InstallerDirectory
  }
  if (-not (Test-Path -LiteralPath $RequestedInstallerDirectory -PathType Container)) {
    throw "No existe la carpeta de instaladores indicada: $RequestedInstallerDirectory"
  }
  $BundleDirectories = @((Resolve-Path -LiteralPath $RequestedInstallerDirectory).Path)
}
$DiscoveredInstallers = @()
$ForbiddenCudaLibraries = @("cublas64_12.dll", "cublasLt64_12.dll", "cudnn64_9.dll")
foreach ($BundleDirectory in $BundleDirectories) {
  if (Test-Path -LiteralPath $BundleDirectory) {
    $BundledCudaLibraries = @(
      Get-ChildItem -LiteralPath $BundleDirectory -Recurse -File |
        Where-Object { $_.Name -in $ForbiddenCudaLibraries }
    )
    if ($BundledCudaLibraries.Count -gt 0) {
      throw "El bundle público contiene bibliotecas CUDA que deben descargarse tras el consentimiento."
    }
    $DiscoveredInstallers += @(Get-ChildItem -LiteralPath $BundleDirectory -Recurse -File |
      Where-Object { $_.Name -like "*-setup.exe" -or $_.Extension -eq ".msi" })
  }
}
$DiscoveredInstallers = @(
  $DiscoveredInstallers |
    Sort-Object FullName -Unique
)
$InstallersFromOtherVersions = @(
  $DiscoveredInstallers |
    Where-Object { -not (Test-InstallerNameForVersion $_.Name $InstallerVersion) }
)
if ($InstallersFromOtherVersions.Count -gt 0) {
  Write-Warning (
    "Se ignoraron instaladores de otra versión:`n" +
    (($InstallersFromOtherVersions | Select-Object -ExpandProperty FullName) -join "`n")
  )
}
$Installers = @(
  $DiscoveredInstallers |
    Where-Object { Test-InstallerNameForVersion $_.Name $InstallerVersion }
)
$NsisInstallers = @(
  $Installers | Where-Object { $_.Name -like "*-setup.exe" }
)
$MsiInstallers = @(
  $Installers | Where-Object { $_.Extension -ieq ".msi" }
)
$InstallerValidationRequested = (
  $RequireInstallers -or
  $RequireAuthenticode -or
  $RequireInstallerPayloadInspection -or
  $StageArtifacts
)
if (
  $InstallerValidationRequested -and
  ($NsisInstallers.Count -ne 1 -or $MsiInstallers.Count -ne 1)
) {
  $FoundNames = if ($DiscoveredInstallers.Count -gt 0) {
    ($DiscoveredInstallers | Select-Object -ExpandProperty Name) -join ", "
  }
  else {
    "ninguno"
  }
  throw (
    "Se exige exactamente un NSIS y un MSI de Transcriptor $InstallerVersion. " +
    "Encontrados para esa versión: NSIS=$($NsisInstallers.Count), MSI=$($MsiInstallers.Count). " +
    "Artefactos detectados: $FoundNames"
  )
}
foreach ($Installer in $Installers) {
  if ($Installer.Length -ge 2GB) {
    throw "$($Installer.Name) ocupa $($Installer.Length) bytes y supera el límite de 2 GiB de GitHub Releases."
  }
}

foreach ($NsisInstaller in $NsisInstallers) {
  $VersionInfo = [System.Diagnostics.FileVersionInfo]::GetVersionInfo(
    $NsisInstaller.FullName
  )
  if ([string]$VersionInfo.ProductName -cne "Transcriptor") {
    throw "$($NsisInstaller.Name) no declara ProductName=Transcriptor."
  }
  Assert-ExactInstallerVersion `
    -ActualVersion ([string]$VersionInfo.FileVersion) `
    -ExpectedVersion $InstallerVersion `
    -Description "FileVersion de $($NsisInstaller.Name)"
  Assert-ExactInstallerVersion `
    -ActualVersion ([string]$VersionInfo.ProductVersion) `
    -ExpectedVersion $InstallerVersion `
    -Description "ProductVersion de $($NsisInstaller.Name)"
}
foreach ($MsiInstaller in $MsiInstallers) {
  $MsiProductName = Get-MsiProperty $MsiInstaller.FullName "ProductName"
  if ($MsiProductName -cne "Transcriptor") {
    throw "$($MsiInstaller.Name) no declara ProductName=Transcriptor."
  }
  Assert-ExactInstallerVersion `
    -ActualVersion (Get-MsiProperty $MsiInstaller.FullName "ProductVersion") `
    -ExpectedVersion $InstallerVersion `
    -Description "ProductVersion de $($MsiInstaller.Name)"
}

if ($RequireInstallerPayloadInspection) {
  $SevenZip = Resolve-SevenZipExecutable
  $ExpectedSidecarPath = Join-Path $ProjectRoot (
    "src-tauri\binaries\transcriptor-engine-x86_64-pc-windows-msvc.exe"
  )
  $ExpectedRuntimeDirectory = Join-Path $ProjectRoot (
    "src-tauri\binaries\transcriptor-engine-runtime"
  )
  $TemporaryRoot = Join-Path (
    [System.IO.Path]::GetTempPath()
  ) "transcriptor-installer-audit-$([guid]::NewGuid().ToString('N'))"
  $ResolvedTemporaryRoot = [System.IO.Path]::GetFullPath($TemporaryRoot)
  $TemporaryPrefix = [System.IO.Path]::GetFullPath(
    [System.IO.Path]::GetTempPath()
  ).TrimEnd(
    [System.IO.Path]::DirectorySeparatorChar,
    [System.IO.Path]::AltDirectorySeparatorChar
  ) + [System.IO.Path]::DirectorySeparatorChar
  if (
    -not $ResolvedTemporaryRoot.StartsWith(
      $TemporaryPrefix,
      [System.StringComparison]::OrdinalIgnoreCase
    )
  ) {
    throw "La carpeta temporal de auditoría queda fuera del directorio temporal."
  }

  New-Item -ItemType Directory -Path $ResolvedTemporaryRoot | Out-Null
  try {
    $NsisPayload = Join-Path $ResolvedTemporaryRoot "nsis"
    Expand-NsisPayload $SevenZip $NsisInstallers[0] $NsisPayload
    Assert-PayloadAndSidecarAreClean `
      -Installer $NsisInstallers[0] `
      -PayloadDirectory $NsisPayload `
      -ExpectedSidecarPath $ExpectedSidecarPath `
      -ExpectedRuntimeDirectory $ExpectedRuntimeDirectory

    $MsiPayload = Join-Path $ResolvedTemporaryRoot "msi"
    Expand-MsiPayload $MsiInstallers[0] $MsiPayload
    Assert-PayloadAndSidecarAreClean `
      -Installer $MsiInstallers[0] `
      -PayloadDirectory $MsiPayload `
      -ExpectedSidecarPath $ExpectedSidecarPath `
      -ExpectedRuntimeDirectory $ExpectedRuntimeDirectory
  }
  finally {
    if (
      (Test-Path -LiteralPath $ResolvedTemporaryRoot -PathType Container) -and
      $ResolvedTemporaryRoot.StartsWith(
        $TemporaryPrefix,
        [System.StringComparison]::OrdinalIgnoreCase
      )
    ) {
      Remove-Item `
        -LiteralPath $ResolvedTemporaryRoot `
        -Recurse `
        -Force `
        -ErrorAction SilentlyContinue
    }
  }
}

if ($RequireAuthenticode) {
  if ($Installers.Count -eq 0) {
    throw "No hay instaladores para comprobar con Authenticode."
  }
  $AuthenticodeVerifier = Join-Path $ProjectRoot "scripts\verify-authenticode.ps1"
  $InstallerPaths = @($Installers | ForEach-Object { $_.FullName })
  & $AuthenticodeVerifier `
    -Path $InstallerPaths `
    -ExpectedPublisher $ExpectedPublisher `
    -RequireTimestamp:$true
}

if ($StageArtifacts -and $Installers.Count -gt 0) {
  $ReleaseDirectory = if ([string]::IsNullOrWhiteSpace($ArtifactOutputDirectory)) {
    Join-Path $ProjectRoot "release"
  }
  elseif ([System.IO.Path]::IsPathRooted($ArtifactOutputDirectory)) {
    $ArtifactOutputDirectory
  }
  else {
    Join-Path $ProjectRoot $ArtifactOutputDirectory
  }
  New-Item -ItemType Directory -Path $ReleaseDirectory -Force | Out-Null
  $StagedChecksumAssets = @()
  foreach ($Installer in ($Installers | Sort-Object Name)) {
    $Destination = Join-Path $ReleaseDirectory $Installer.Name
    Copy-Item -LiteralPath $Installer.FullName -Destination $Destination -Force
    $StagedChecksumAssets += Get-Item -LiteralPath $Destination
  }
  $NoticesDestination = Join-Path $ReleaseDirectory "THIRD_PARTY_NOTICES.md"
  Copy-Item -LiteralPath (Join-Path $ProjectRoot "docs\THIRD_PARTY_NOTICES.md") `
    -Destination $NoticesDestination -Force
  $StagedChecksumAssets += Get-Item -LiteralPath $NoticesDestination
  $ChecksumLines = @(
    $StagedChecksumAssets |
      Sort-Object Name |
      ForEach-Object {
        $Hash = (
          Get-FileHash -LiteralPath $_.FullName -Algorithm SHA256
        ).Hash.ToLowerInvariant()
        "$Hash  $($_.Name)"
      }
  )
  $ChecksumPath = Join-Path $ReleaseDirectory "checksums-SHA256.txt"
  [System.IO.File]::WriteAllLines($ChecksumPath, $ChecksumLines, [System.Text.UTF8Encoding]::new($false))
  Write-Host "Artefactos preparados en $ReleaseDirectory"
}

Write-Host "Verificación de publicación superada para Transcriptor $Version."
