param(
  [string]$TargetTriple = ""
)
$ErrorActionPreference = "Stop"
$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
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
uv run --project (Join-Path $ProjectRoot "sidecar") --extra dev pyinstaller @PyInstallerArguments
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
Write-Host "Sidecar preparado: $Destination"
