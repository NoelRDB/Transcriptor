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
  Invoke-CheckedNative npm ci
  Invoke-CheckedNative uv sync --project sidecar --extra dev --locked
  & (Join-Path $PSScriptRoot "verify-release.ps1")
  Invoke-CheckedNative npm run check
  Invoke-CheckedNative npm run sidecar:build
  & (Join-Path $PSScriptRoot "verify-release.ps1") -RequireRuntimeAssets
  Invoke-CheckedNative npm run tauri build
  & (Join-Path $PSScriptRoot "verify-release.ps1") -RequireInstallers -StageArtifacts
}
finally {
  Pop-Location
}
