param(
  [Parameter(Mandatory = $true)][string]$ArchivePath
)
$ErrorActionPreference = "Stop"
$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$ResolvedArchive = (Resolve-Path -LiteralPath $ArchivePath).Path
$TemporaryDirectory = Join-Path ([System.IO.Path]::GetTempPath()) ("transcriptor-ffmpeg-" + [guid]::NewGuid())
$Destination = Join-Path $ProjectRoot "sidecar\ffmpeg"
New-Item -ItemType Directory -Path $TemporaryDirectory | Out-Null
try {
  Expand-Archive -LiteralPath $ResolvedArchive -DestinationPath $TemporaryDirectory
  $Ffmpeg = Get-ChildItem -LiteralPath $TemporaryDirectory -Recurse -Filter "ffmpeg.exe" | Select-Object -First 1
  $Ffprobe = Get-ChildItem -LiteralPath $TemporaryDirectory -Recurse -Filter "ffprobe.exe" | Select-Object -First 1
  if (-not $Ffmpeg -or -not $Ffprobe) { throw "El archivo no contiene ffmpeg.exe y ffprobe.exe." }
  New-Item -ItemType Directory -Force -Path $Destination | Out-Null
  Copy-Item -LiteralPath $Ffmpeg.FullName -Destination (Join-Path $Destination "ffmpeg.exe") -Force
  Copy-Item -LiteralPath $Ffprobe.FullName -Destination (Join-Path $Destination "ffprobe.exe") -Force
  Write-Host "FFmpeg y FFprobe preparados en $Destination"
}
finally {
  if ((Test-Path -LiteralPath $TemporaryDirectory) -and $TemporaryDirectory.StartsWith([System.IO.Path]::GetTempPath())) {
    Remove-Item -LiteralPath $TemporaryDirectory -Recurse -Force
  }
}
