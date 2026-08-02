param(
  [string]$TargetTriple = ""
)
$ErrorActionPreference = "Stop"
$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path

function Invoke-CheckedNative {
  param(
    [Parameter(Mandatory = $true)][string]$Command,
    [Parameter(ValueFromRemainingArguments = $true)][string[]]$Arguments
  )
  & $Command @Arguments
  if ($LASTEXITCODE -ne 0) {
    throw "El comando '$Command $($Arguments -join ' ')' terminó con código $LASTEXITCODE."
  }
}

if (-not $TargetTriple) {
  $RustCommand = Get-Command rustc -ErrorAction SilentlyContinue
  if ($RustCommand) { $TargetTriple = (& rustc --print host-tuple).Trim() }
  elseif ($env:PROCESSOR_ARCHITECTURE -eq "ARM64") { $TargetTriple = "aarch64-pc-windows-msvc" }
  else { $TargetTriple = "x86_64-pc-windows-msvc" }
}
$DistPath = Join-Path $ProjectRoot "sidecar\dist"
$CTranslateDirectory = Join-Path $ProjectRoot "sidecar\.venv\Lib\site-packages\ctranslate2"
$RequiredCTranslateLibraries = @("ctranslate2.dll", "libiomp5md.dll")
foreach ($Library in $RequiredCTranslateLibraries) {
  if (-not (Test-Path -LiteralPath (Join-Path $CTranslateDirectory $Library) -PathType Leaf)) {
    throw "Falta una biblioteca CPU requerida por CTranslate2: $Library"
  }
}
$PyInstallerArguments = @(
  "--noconfirm", "--clean", "--onefile", "--name", "transcriptor-engine",
  "--distpath", (Join-Path $ProjectRoot "sidecar\dist"),
  "--workpath", (Join-Path $ProjectRoot "sidecar\build"),
  "--specpath", (Join-Path $ProjectRoot "sidecar"),
  "--collect-all", "faster_whisper",
  "--collect-submodules", "ctranslate2",
  "--collect-all", "tokenizers", "--exclude-module", "av",
  "--collect-all", "onnxruntime", "--collect-all", "kaldi_native_fbank",
  "--collect-all", "docx", "--collect-all", "reportlab"
)
foreach ($ExcludedModule in @(
  "av",
  "pytest",
  "_pytest",
  "ruff",
  "iniconfig",
  "pluggy",
  "pygments",
  "altgraph",
  "pefile",
  "pywin32_ctypes",
  "PyInstaller"
)) {
  $PyInstallerArguments += @("--exclude-module", $ExcludedModule)
}
foreach ($Library in $RequiredCTranslateLibraries) {
  $PyInstallerArguments += @(
    "--add-binary",
    "$(Join-Path $CTranslateDirectory $Library);ctranslate2"
  )
}
$FfmpegDirectory = Join-Path $ProjectRoot "sidecar\ffmpeg"
if (Test-Path -LiteralPath (Join-Path $FfmpegDirectory "ffmpeg.exe")) {
  $PyInstallerArguments += @("--add-binary", "$(Join-Path $FfmpegDirectory 'ffmpeg.exe');ffmpeg")
}
if (Test-Path -LiteralPath (Join-Path $FfmpegDirectory "ffprobe.exe")) {
  $PyInstallerArguments += @("--add-binary", "$(Join-Path $FfmpegDirectory 'ffprobe.exe');ffmpeg")
}
$PyInstallerArguments += (Join-Path $ProjectRoot "sidecar\launcher.py")
Invoke-CheckedNative uv run --project (Join-Path $ProjectRoot "sidecar") --extra dev pyinstaller @PyInstallerArguments
$Source = Join-Path $DistPath "transcriptor-engine.exe"
$PreviousErrorActionPreference = $ErrorActionPreference
$ErrorActionPreference = "Continue"
$SidecarArchive = & uv run --project (Join-Path $ProjectRoot "sidecar") --extra dev `
  pyi-archive_viewer -r -b $Source 2>&1
$ArchiveViewerExitCode = $LASTEXITCODE
$ErrorActionPreference = $PreviousErrorActionPreference
if ($ArchiveViewerExitCode -ne 0) {
  throw "No se pudo inspeccionar el contenido del sidecar."
}
$ForbiddenArchivePatterns = @(
  "^av(?:[./\\]|$)",
  "^(?:pytest|_pytest|ruff|iniconfig|pluggy|pygments|altgraph|pefile|pywin32_ctypes|PyInstaller)(?:[./\\]|$)",
  "(?:^|[./\\])libx26[45][^/\\]*\.dll$",
  "^nvidia(?:[./\\]|$)",
  "(?:^|[./\\])(?:cublas|cudnn|cufft|curand|cusolver|cusparse|nvrtc|nvjitlink)[^/\\]*\.dll$"
)
foreach ($ArchiveEntry in $SidecarArchive) {
  $NormalizedEntry = "$ArchiveEntry".Trim()
  foreach ($Pattern in $ForbiddenArchivePatterns) {
    if ($NormalizedEntry -match $Pattern) {
      throw "El sidecar contiene un componente prohibido: $NormalizedEntry"
    }
  }
}
$BinaryDirectory = Join-Path $ProjectRoot "src-tauri\binaries"
New-Item -ItemType Directory -Force -Path $BinaryDirectory | Out-Null
$Destination = Join-Path $BinaryDirectory "transcriptor-engine-$TargetTriple.exe"
Copy-Item -LiteralPath $Source -Destination $Destination -Force

# Los binarios redistribuidos deben llevar los textos legales exactos de las
# dependencias runtime fijadas. El inventario impide arrastrar dependencias de
# desarrollo y el manifiesto conserva cada ruta y hash sin colisiones.
$SitePackagesDirectory = Join-Path $ProjectRoot "sidecar\.venv\Lib\site-packages"
$PythonExecutable = Join-Path $ProjectRoot "sidecar\.venv\Scripts\python.exe"
$RuntimeLicenseDirectory = Join-Path $ProjectRoot "src-tauri\resources\licenses"
New-Item -ItemType Directory -Force -Path $RuntimeLicenseDirectory | Out-Null
$ResolvedRuntimeLicenseDirectory = [System.IO.Path]::GetFullPath($RuntimeLicenseDirectory)
$ProjectRootPrefix = $ProjectRoot.TrimEnd(
  [System.IO.Path]::DirectorySeparatorChar,
  [System.IO.Path]::AltDirectorySeparatorChar
) + [System.IO.Path]::DirectorySeparatorChar
if (-not $ResolvedRuntimeLicenseDirectory.StartsWith(
  $ProjectRootPrefix,
  [System.StringComparison]::OrdinalIgnoreCase
)) {
  throw "La carpeta de licencias generadas queda fuera del repositorio."
}
Get-ChildItem -LiteralPath $ResolvedRuntimeLicenseDirectory -Force -ErrorAction SilentlyContinue |
  Remove-Item -Recurse -Force

& (Join-Path $ProjectRoot "scripts\collect-runtime-licenses.ps1") `
  -SitePackagesDirectory $SitePackagesDirectory `
  -PythonExecutable $PythonExecutable `
  -OutputDirectory $ResolvedRuntimeLicenseDirectory `
  -ProjectRoot $ProjectRoot

$RuntimeLicenseManifestPath = Join-Path $ResolvedRuntimeLicenseDirectory `
  "PYTHON-RUNTIME-LICENSES.json"
$RuntimeLicenseManifest = Get-Content -LiteralPath $RuntimeLicenseManifestPath `
  -Raw -Encoding UTF8 | ConvertFrom-Json
$LicenseCount = @(
  @($RuntimeLicenseManifest.distributions | ForEach-Object { @($_.files) }) +
  @($RuntimeLicenseManifest.bootstrapComponents | ForEach-Object { @($_.files) })
).Count
if ($LicenseCount -lt 1) {
  throw "El manifiesto de licencias runtime está vacío."
}

$TrackedGnuLicenses = @{
  "GPL-3.0.txt" = Join-Path $ProjectRoot "docs\licenses\GPL-3.0.txt"
  "LGPL-3.0.txt" = Join-Path $ProjectRoot "docs\licenses\LGPL-3.0.txt"
}
foreach ($LicenseName in $TrackedGnuLicenses.Keys) {
  $TrackedLicense = $TrackedGnuLicenses[$LicenseName]
  if (-not (Test-Path -LiteralPath $TrackedLicense -PathType Leaf)) {
    throw "Falta el texto completo y versionado de la licencia $LicenseName."
  }
  Copy-Item -LiteralPath $TrackedLicense `
    -Destination (Join-Path $RuntimeLicenseDirectory $LicenseName) -Force
}

$FfmpegArchiveLicense = Join-Path $FfmpegDirectory "LICENSE.txt"
if (-not (Test-Path -LiteralPath $FfmpegArchiveLicense -PathType Leaf)) {
  throw "Falta el LICENSE.txt exacto de la compilación FFmpeg fijada."
}
Copy-Item -LiteralPath $FfmpegArchiveLicense `
  -Destination (Join-Path $RuntimeLicenseDirectory "FFmpeg-LICENSE.txt") -Force

$FfmpegSourceManifest = Join-Path $FfmpegDirectory "BUILD-SOURCE.txt"
if (-not (Test-Path -LiteralPath $FfmpegSourceManifest -PathType Leaf)) {
  throw "Falta BUILD-SOURCE.txt con el origen, SHA-256 y configuración exactos de FFmpeg."
}
Copy-Item -LiteralPath $FfmpegSourceManifest `
  -Destination (Join-Path $RuntimeLicenseDirectory "FFmpeg-BUILD-SOURCE.txt") -Force

$IntelRuntimeLicense = Join-Path $ProjectRoot "docs\licenses\INTEL-SIMPLIFIED-SOFTWARE-LICENSE.txt"
if (-not (Test-Path -LiteralPath $IntelRuntimeLicense -PathType Leaf)) {
  throw "Falta la licencia completa del runtime Intel OpenMP."
}
Copy-Item -LiteralPath $IntelRuntimeLicense `
  -Destination (Join-Path $RuntimeLicenseDirectory "INTEL-SIMPLIFIED-SOFTWARE-LICENSE.txt") -Force

Write-Host "Sidecar preparado: $Destination"
Write-Host "Licencias de runtime preparadas: $LicenseCount"
