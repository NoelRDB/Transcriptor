$ErrorActionPreference = "Stop"
$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path

foreach ($Command in @("npm", "uv", "rustc", "cargo")) {
  if (-not (Get-Command $Command -ErrorAction SilentlyContinue)) {
    throw "Falta '$Command'. Consulta docs/PACKAGING.md antes de crear el instalador."
  }
}

$Ffmpeg = Join-Path $ProjectRoot "sidecar\ffmpeg\ffmpeg.exe"
$Ffprobe = Join-Path $ProjectRoot "sidecar\ffmpeg\ffprobe.exe"
if (-not (Test-Path -LiteralPath $Ffmpeg) -or -not (Test-Path -LiteralPath $Ffprobe)) {
  throw "Faltan FFmpeg/FFprobe redistribuibles. Ejecuta scripts/stage-ffmpeg.ps1 con una compilación LGPL compatible."
}

Push-Location $ProjectRoot
try {
  npm ci
  uv sync --project sidecar --extra dev --locked
  npm run check
  npm run sidecar:build
  npm run tauri build
  & (Join-Path $PSScriptRoot "verify-release.ps1") -RequireInstallers -StageArtifacts
}
finally {
  Pop-Location
}
