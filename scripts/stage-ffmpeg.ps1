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
  Add-Type -AssemblyName System.IO.Compression.FileSystem
  $Archive = [System.IO.Compression.ZipFile]::OpenRead($ResolvedArchive)
  try {
    $RequiredEntries = @{}
    $MaximumEntryLengths = @{
      "ffmpeg.exe" = 512MB
      "ffprobe.exe" = 512MB
      "LICENSE.txt" = 1MB
      "BUILD-SOURCE.txt" = 1MB
      "GCC-RUNTIME-LICENSES.txt" = 2MB
      "MINGW-W64-LICENSES.txt" = 2MB
    }
    $RequiredNames = @(
      "ffmpeg.exe",
      "ffprobe.exe",
      "LICENSE.txt",
      "BUILD-SOURCE.txt",
      "GCC-RUNTIME-LICENSES.txt",
      "MINGW-W64-LICENSES.txt"
    )
    if ($Archive.Entries.Count -ne $RequiredNames.Count) {
      throw "El ZIP de FFmpeg debe contener exactamente seis archivos permitidos."
    }
    foreach ($RequiredName in $RequiredNames) {
      $Matches = @(
        $Archive.Entries |
          Where-Object {
            $_.FullName.Equals(
              $RequiredName,
              [System.StringComparison]::Ordinal
            )
          }
      )
      if ($Matches.Count -ne 1) {
        throw "El archivo debe contener exactamente una entrada llamada $RequiredName."
      }
      if ($Matches[0].Length -lt 1) {
        throw "La entrada $RequiredName está vacía."
      }
      if ($Matches[0].Length -gt $MaximumEntryLengths[$RequiredName]) {
        throw "La entrada $RequiredName supera el tamaño máximo permitido."
      }
      $RequiredEntries[$RequiredName] = $Matches[0]
    }

    # No se expande el ZIP completo ni se usa su ruta interna como destino:
    # cada entrada permitida se copia a un nombre fijo dentro de nuestro
    # temporal. Así una ruta absoluta, '..' o un enlace del ZIP no puede
    # escribir fuera de la carpeta controlada.
    foreach ($RequiredName in $RequiredEntries.Keys) {
      $StagedPath = Join-Path $TemporaryDirectory $RequiredName
      $InputStream = $RequiredEntries[$RequiredName].Open()
      $OutputStream = [System.IO.File]::Create($StagedPath)
      try {
        $InputStream.CopyTo($OutputStream)
      }
      finally {
        $OutputStream.Dispose()
        $InputStream.Dispose()
      }
    }
  }
  finally {
    $Archive.Dispose()
  }

  $Ffmpeg = Join-Path $TemporaryDirectory "ffmpeg.exe"
  $Ffprobe = Join-Path $TemporaryDirectory "ffprobe.exe"
  $License = Join-Path $TemporaryDirectory "LICENSE.txt"
  $SourceManifest = Join-Path $TemporaryDirectory "BUILD-SOURCE.txt"
  $GccRuntimeLicenses = Join-Path $TemporaryDirectory `
    "GCC-RUNTIME-LICENSES.txt"
  $MingwRuntimeLicenses = Join-Path $TemporaryDirectory `
    "MINGW-W64-LICENSES.txt"
  if ((Get-Item -LiteralPath $Ffmpeg).Length -lt 1MB -or
      (Get-Item -LiteralPath $Ffprobe).Length -lt 1MB) {
    throw "Los ejecutables FFmpeg extraídos parecen incompletos."
  }
  $LicenseText = [System.IO.File]::ReadAllText($License)
  if ($LicenseText -notmatch "(?m)^\s*GNU LESSER GENERAL PUBLIC LICENSE\s*$" -or
      $LicenseText -notmatch "(?m)^\s*Version 3, 29 June 2007\s*$") {
    throw "LICENSE.txt no declara la GNU Lesser General Public License v3."
  }
  $SourceManifestText = [System.IO.File]::ReadAllText($SourceManifest)
  if (
    $SourceManifestText -notmatch
      "(?m)^Source commit:\s+0869e710e6876792fbcebccb536ad620d8e65b97\s*$" -or
    $SourceManifestText -notmatch
      "(?m)^Corresponding source asset:\s+Transcriptor-\d+\.\d+\.\d+-FFmpeg-corresponding-source\.tar\.gz\s*$" -or
    $SourceManifestText -notmatch "(?m)^Corresponding source SHA-256:\s+[a-f0-9]{64}\s*$" -or
    $SourceManifestText -notmatch "(?m)^Configuration:\s+.*--disable-autodetect.*$" -or
    $SourceManifestText -notmatch "(?m)^Configuration:\s+.*--disable-network.*$" -or
    $SourceManifestText -notmatch
      "(?m)^Target compiler:\s+x86_64-w64-mingw32-gcc\s*$" -or
    $SourceManifestText -notmatch
      "(?m)^Target compiler version:\s+[^\r\n]+\s*$" -or
    $SourceManifestText -notmatch
      "(?m)^GCC runtime package:\s+[^\r\n=]+=[^\r\n]+\s*$" -or
    $SourceManifestText -notmatch
      "(?m)^GCC runtime license:\s+GCC-RUNTIME-LICENSES\.txt\s*$" -or
    $SourceManifestText -notmatch
      "(?m)^GCC runtime license SHA-256:\s+[a-f0-9]{64}\s*$" -or
    $SourceManifestText -notmatch
      "(?m)^MinGW-w64 runtime package:\s+[^\r\n=]+=[^\r\n]+\s*$" -or
    $SourceManifestText -notmatch
      "(?m)^MinGW-w64 licenses:\s+MINGW-W64-LICENSES\.txt\s*$" -or
    $SourceManifestText -notmatch
      "(?m)^MinGW-w64 licenses SHA-256:\s+[a-f0-9]{64}\s*$" -or
    $SourceManifestText -match "--enable-(?:gpl|nonfree|lib)"
  ) {
    throw "BUILD-SOURCE.txt no acredita la fuente y configuración LGPL fijadas."
  }
  $ExpectedGccRuntimeHash = [regex]::Match(
    $SourceManifestText,
    "(?m)^GCC runtime license SHA-256:\s+([a-f0-9]{64})\s*$"
  ).Groups[1].Value
  $ExpectedMingwRuntimeHash = [regex]::Match(
    $SourceManifestText,
    "(?m)^MinGW-w64 licenses SHA-256:\s+([a-f0-9]{64})\s*$"
  ).Groups[1].Value
  $ActualGccRuntimeHash = (
    Get-FileHash -LiteralPath $GccRuntimeLicenses -Algorithm SHA256
  ).Hash.ToLowerInvariant()
  $ActualMingwRuntimeHash = (
    Get-FileHash -LiteralPath $MingwRuntimeLicenses -Algorithm SHA256
  ).Hash.ToLowerInvariant()
  if (
    $ActualGccRuntimeHash -cne $ExpectedGccRuntimeHash -or
    $ActualMingwRuntimeHash -cne $ExpectedMingwRuntimeHash
  ) {
    throw "Los avisos del toolchain FFmpeg no coinciden con BUILD-SOURCE.txt."
  }
  if (
    -not (Select-String -LiteralPath $GccRuntimeLicenses `
      -Pattern "GCC Runtime Library Exception" -Quiet) -or
    -not (Select-String -LiteralPath $MingwRuntimeLicenses `
      -Pattern "Zope Public License|ZPL-2|public domain" -Quiet)
  ) {
    throw "Los avisos del runtime GCC/MinGW-w64 están incompletos."
  }

  New-Item -ItemType Directory -Force -Path $Destination | Out-Null
  Copy-Item -LiteralPath $Ffmpeg -Destination (Join-Path $Destination "ffmpeg.exe") -Force
  Copy-Item -LiteralPath $Ffprobe -Destination (Join-Path $Destination "ffprobe.exe") -Force
  Copy-Item -LiteralPath $License -Destination (Join-Path $Destination "LICENSE.txt") -Force
  Copy-Item -LiteralPath $SourceManifest `
    -Destination (Join-Path $Destination "BUILD-SOURCE.txt") -Force
  Copy-Item -LiteralPath $GccRuntimeLicenses `
    -Destination (Join-Path $Destination "GCC-RUNTIME-LICENSES.txt") -Force
  Copy-Item -LiteralPath $MingwRuntimeLicenses `
    -Destination (Join-Path $Destination "MINGW-W64-LICENSES.txt") -Force
  Write-Host "FFmpeg, FFprobe y evidencia legal exacta preparados en $Destination"
}
finally {
  if ((Test-Path -LiteralPath $TemporaryDirectory) -and $TemporaryDirectory.StartsWith([System.IO.Path]::GetTempPath())) {
    Remove-Item -LiteralPath $TemporaryDirectory -Recurse -Force
  }
}
