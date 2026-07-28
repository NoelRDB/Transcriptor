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
$PyInstallerArguments = @(
  "--noconfirm", "--clean", "--onefile", "--name", "transcriptor-engine",
  "--distpath", (Join-Path $ProjectRoot "sidecar\dist"),
  "--workpath", (Join-Path $ProjectRoot "sidecar\build"),
  "--specpath", (Join-Path $ProjectRoot "sidecar"),
  "--collect-all", "faster_whisper", "--collect-all", "ctranslate2",
  "--collect-all", "tokenizers", "--collect-all", "av",
  "--collect-all", "onnxruntime", "--collect-all", "kaldi_native_fbank",
  "--collect-all", "docx", "--collect-all", "reportlab"
)
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
$BinaryDirectory = Join-Path $ProjectRoot "src-tauri\binaries"
New-Item -ItemType Directory -Force -Path $BinaryDirectory | Out-Null
$Destination = Join-Path $BinaryDirectory "transcriptor-engine-$TargetTriple.exe"
Copy-Item -LiteralPath $Source -Destination $Destination -Force
$CudaResourceDirectory = Join-Path $ProjectRoot "src-tauri\resources\cuda"
New-Item -ItemType Directory -Force -Path $CudaResourceDirectory | Out-Null
$NvidiaPackageDirectory = Join-Path $ProjectRoot "sidecar\.venv\Lib\site-packages\nvidia"
$RequiredCudaLibraries = @("cublas64_12.dll", "cublasLt64_12.dll", "cudnn64_9.dll")
Get-ChildItem -LiteralPath $CudaResourceDirectory -Filter "*.dll" -File |
  Where-Object { $_.Name -notin $RequiredCudaLibraries } |
  Remove-Item -Force
foreach ($Library in $RequiredCudaLibraries) {
  $SourceLibrary = Get-ChildItem -LiteralPath $NvidiaPackageDirectory -Recurse -Filter $Library -File |
    Select-Object -First 1
  if (-not $SourceLibrary) { throw "Falta el runtime CUDA requerido: $Library" }
  Copy-Item -LiteralPath $SourceLibrary.FullName -Destination $CudaResourceDirectory -Force
}

# Los binarios redistribuidos deben llevar los textos de licencia exactos de
# las versiones fijadas en uv.lock. Se recopilan en cada build para evitar que
# una actualización de dependencias deje avisos obsoletos en el instalador.
$SitePackagesDirectory = Join-Path $ProjectRoot "sidecar\.venv\Lib\site-packages"
$RuntimeLicenseDirectory = Join-Path $ProjectRoot "src-tauri\resources\licenses"
New-Item -ItemType Directory -Force -Path $RuntimeLicenseDirectory | Out-Null
Get-ChildItem -LiteralPath $RuntimeLicenseDirectory -File -ErrorAction SilentlyContinue |
  Remove-Item -Force

$LicenseCount = 0
Get-ChildItem -LiteralPath $SitePackagesDirectory -Directory -Filter "*.dist-info" |
  ForEach-Object {
    $PackageDirectory = $_
    Get-ChildItem -LiteralPath $PackageDirectory.FullName -Recurse -File |
      Where-Object { $_.Name -match "^(LICENSE|LICENCE|COPYING|NOTICE)" } |
      ForEach-Object {
        $SafePackageName = $PackageDirectory.Name -replace "[^A-Za-z0-9._-]", "_"
        $SafeLicenseName = $_.Name -replace "[^A-Za-z0-9._-]", "_"
        $DestinationName = "$SafePackageName--$SafeLicenseName"
        Copy-Item -LiteralPath $_.FullName `
          -Destination (Join-Path $RuntimeLicenseDirectory $DestinationName) -Force
        $LicenseCount += 1
      }
  }

if ($LicenseCount -lt 1) {
  throw "No se encontraron textos de licencia de las dependencias del motor."
}

$FfmpegSourceManifest = Join-Path $FfmpegDirectory "BUILD-SOURCE.txt"
if (Test-Path -LiteralPath $FfmpegSourceManifest) {
  Copy-Item -LiteralPath $FfmpegSourceManifest `
    -Destination (Join-Path $RuntimeLicenseDirectory "FFmpeg-BUILD-SOURCE.txt") -Force
}
else {
  $FfmpegVersion = (& (Join-Path $FfmpegDirectory "ffmpeg.exe") -version 2>&1) -join "`n"
  [System.IO.File]::WriteAllText(
    (Join-Path $RuntimeLicenseDirectory "FFmpeg-BUILD-SOURCE.txt"),
    $FfmpegVersion,
    [System.Text.UTF8Encoding]::new($false)
  )
}

Write-Host "Sidecar preparado: $Destination"
Write-Host "Licencias de runtime preparadas: $LicenseCount"
