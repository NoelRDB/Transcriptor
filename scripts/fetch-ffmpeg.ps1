param(
  [Parameter(Mandatory = $true)][string]$Url,
  [Parameter(Mandatory = $true)][ValidatePattern("^[A-Fa-f0-9]{64}$")][string]$Sha256
)

$ErrorActionPreference = "Stop"
$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$ParsedUrl = [Uri]$Url
if ($ParsedUrl.Scheme -ne "https") {
  throw "FFmpeg sólo puede descargarse mediante HTTPS."
}

$TemporaryDirectory = Join-Path ([System.IO.Path]::GetTempPath()) ("transcriptor-ffmpeg-download-" + [guid]::NewGuid())
$ArchivePath = Join-Path $TemporaryDirectory "ffmpeg.zip"
New-Item -ItemType Directory -Path $TemporaryDirectory | Out-Null

try {
  Write-Host "Descargando la compilación FFmpeg fijada..."
  Invoke-WebRequest -Uri $ParsedUrl -OutFile $ArchivePath -UseBasicParsing

  $ActualSha256 = (Get-FileHash -LiteralPath $ArchivePath -Algorithm SHA256).Hash
  if ($ActualSha256 -ne $Sha256.ToUpperInvariant()) {
    throw "La suma SHA-256 de FFmpeg no coincide. Esperada: $Sha256. Recibida: $ActualSha256"
  }

  & (Join-Path $PSScriptRoot "stage-ffmpeg.ps1") -ArchivePath $ArchivePath

  $FfmpegPath = Join-Path $ProjectRoot "sidecar\ffmpeg\ffmpeg.exe"
  $VersionOutput = (& $FfmpegPath -version 2>&1) -join "`n"
  if ($VersionOutput -match "--enable-(gpl|nonfree)") {
    throw "La compilación descargada activa componentes GPL o nonfree. Usa una variante LGPL redistribuible."
  }
  if ($VersionOutput -notmatch "--disable-libx264" -or $VersionOutput -notmatch "--disable-libx265") {
    throw "No se puede confirmar que la compilación FFmpeg excluya x264/x265. Revisa el proveedor."
  }

  $SourceManifest = @(
    "Componente: FFmpeg/FFprobe",
    "Archivo original: $ParsedUrl",
    "SHA-256 del archivo: $($Sha256.ToLowerInvariant())",
    "",
    $VersionOutput
  )
  [System.IO.File]::WriteAllLines(
    (Join-Path $ProjectRoot "sidecar\ffmpeg\BUILD-SOURCE.txt"),
    $SourceManifest,
    [System.Text.UTF8Encoding]::new($false)
  )

  Write-Host "FFmpeg verificado y preparado para el instalador."
}
finally {
  $TempRoot = [System.IO.Path]::GetFullPath([System.IO.Path]::GetTempPath())
  if (Test-Path -LiteralPath $TemporaryDirectory) {
    $ResolvedTemporaryDirectory = [System.IO.Path]::GetFullPath($TemporaryDirectory)
    if (-not $ResolvedTemporaryDirectory.StartsWith($TempRoot, [System.StringComparison]::OrdinalIgnoreCase)) {
      throw "Se rechazó limpiar un directorio temporal fuera de la ruta permitida."
    }
    Remove-Item -LiteralPath $ResolvedTemporaryDirectory -Recurse -Force
  }
}
