param(
  [switch]$RequireInstallers,
  [switch]$StageArtifacts
)

$ErrorActionPreference = "Stop"
$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$Package = Get-Content -LiteralPath (Join-Path $ProjectRoot "package.json") -Raw -Encoding UTF8 |
  ConvertFrom-Json
$TauriConfig = Get-Content -LiteralPath (Join-Path $ProjectRoot "src-tauri\tauri.conf.json") -Raw -Encoding UTF8 |
  ConvertFrom-Json
$Version = [string]$Package.version

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

if ($env:GITHUB_REF_TYPE -eq "tag" -and $env:GITHUB_REF_NAME -ne "v$Version") {
  throw "La etiqueta $($env:GITHUB_REF_NAME) no coincide con la versión v$Version."
}

$BundleDirectory = Join-Path $ProjectRoot "src-tauri\target\release\bundle"
$Installers = @()
if (Test-Path -LiteralPath $BundleDirectory) {
  $Installers = @(Get-ChildItem -LiteralPath $BundleDirectory -Recurse -File |
    Where-Object { $_.Name -like "*-setup.exe" -or $_.Extension -eq ".msi" })
}
if ($RequireInstallers -and $Installers.Count -lt 2) {
  throw "No se encontraron los instaladores NSIS y MSI bajo $BundleDirectory."
}

if ($StageArtifacts -and $Installers.Count -gt 0) {
  $ReleaseDirectory = Join-Path $ProjectRoot "release"
  New-Item -ItemType Directory -Path $ReleaseDirectory -Force | Out-Null
  $ChecksumLines = @()
  foreach ($Installer in $Installers) {
    $Destination = Join-Path $ReleaseDirectory $Installer.Name
    Copy-Item -LiteralPath $Installer.FullName -Destination $Destination -Force
    $Hash = (Get-FileHash -LiteralPath $Destination -Algorithm SHA256).Hash.ToLowerInvariant()
    $ChecksumLines += "$Hash  $($Installer.Name)"
  }
  $ChecksumPath = Join-Path $ReleaseDirectory "checksums-SHA256.txt"
  [System.IO.File]::WriteAllLines($ChecksumPath, $ChecksumLines, [System.Text.UTF8Encoding]::new($false))
  Write-Host "Artefactos preparados en $ReleaseDirectory"
}

Write-Host "Verificación de publicación superada para Transcriptor $Version."
