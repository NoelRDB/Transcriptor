param(
  [switch]$RequireRuntimeAssets,
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
if ([string]$TauriConfig.bundle.windows.webviewInstallMode.type -ne "embedBootstrapper") {
  throw "El instalador debe incorporar el bootstrapper de WebView2."
}
if ([string]$TauriConfig.bundle.windows.nsis.installMode -ne "currentUser") {
  throw "El instalador recomendado debe funcionar sin privilegios de administrador."
}
$ConfiguredResources = @($TauriConfig.bundle.resources.PSObject.Properties.Name)
foreach ($RequiredResource in @(
  "resources/cuda/",
  "resources/licenses/",
  "../LICENSE",
  "../docs/THIRD_PARTY_NOTICES.md"
)) {
  if ($RequiredResource -notin $ConfiguredResources) {
    throw "Falta el recurso obligatorio '$RequiredResource' en tauri.conf.json."
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
      MinimumBytes = 10MB
    },
    @{ Path = Join-Path $ProjectRoot "sidecar\ffmpeg\ffmpeg.exe"; MinimumBytes = 1MB },
    @{ Path = Join-Path $ProjectRoot "sidecar\ffmpeg\ffprobe.exe"; MinimumBytes = 1MB },
    @{ Path = Join-Path $ProjectRoot "src-tauri\resources\cuda\cublas64_12.dll"; MinimumBytes = 1MB },
    @{ Path = Join-Path $ProjectRoot "src-tauri\resources\cuda\cublasLt64_12.dll"; MinimumBytes = 1MB },
    @{ Path = Join-Path $ProjectRoot "src-tauri\resources\cuda\cudnn64_9.dll"; MinimumBytes = 64KB }
  )
  foreach ($RuntimeFile in $RuntimeFiles) {
    if (-not (Test-Path -LiteralPath $RuntimeFile.Path -PathType Leaf)) {
      throw "Falta un componente necesario para el instalador: $($RuntimeFile.Path)"
    }
    if ((Get-Item -LiteralPath $RuntimeFile.Path).Length -lt $RuntimeFile.MinimumBytes) {
      throw "El componente parece incompleto: $($RuntimeFile.Path)"
    }
  }

  $FfmpegVersion = (& (Join-Path $ProjectRoot "sidecar\ffmpeg\ffmpeg.exe") -version 2>&1) -join "`n"
  if ($FfmpegVersion -match "--enable-(gpl|nonfree)") {
    throw "FFmpeg activa componentes GPL o nonfree y no puede entrar en esta publicación."
  }
  if ($FfmpegVersion -notmatch "--disable-libx264" -or $FfmpegVersion -notmatch "--disable-libx265") {
    throw "No se ha podido verificar que FFmpeg excluya x264 y x265."
  }

  $RuntimeLicenseDirectory = Join-Path $ProjectRoot "src-tauri\resources\licenses"
  $RuntimeLicenses = @(
    Get-ChildItem -LiteralPath $RuntimeLicenseDirectory -File -ErrorAction SilentlyContinue
  )
  foreach ($LicensePattern in @(
    "nvidia_cublas_cu12-*.dist-info--License.txt",
    "nvidia_cudnn_cu12-*.dist-info--License.txt",
    "FFmpeg-BUILD-SOURCE.txt"
  )) {
    if (-not ($RuntimeLicenses | Where-Object { $_.Name -like $LicensePattern })) {
      throw "Falta el aviso de redistribución '$LicensePattern'."
    }
  }
}

$BundleDirectories = @(
  (Join-Path $ProjectRoot "src-tauri\target\x86_64-pc-windows-msvc\release\bundle"),
  (Join-Path $ProjectRoot "src-tauri\target\release\bundle")
)
$Installers = @()
foreach ($BundleDirectory in $BundleDirectories) {
  if (Test-Path -LiteralPath $BundleDirectory) {
    $Installers += @(Get-ChildItem -LiteralPath $BundleDirectory -Recurse -File |
      Where-Object { $_.Name -like "*-setup.exe" -or $_.Extension -eq ".msi" })
  }
}
$Installers = @(
  $Installers |
    Sort-Object LastWriteTimeUtc -Descending |
    Group-Object Name |
    ForEach-Object { $_.Group | Select-Object -First 1 }
)
$NsisInstallers = @($Installers | Where-Object { $_.Name -like "*-setup.exe" })
$MsiInstallers = @($Installers | Where-Object { $_.Extension -eq ".msi" })
if ($RequireInstallers -and ($NsisInstallers.Count -lt 1 -or $MsiInstallers.Count -lt 1)) {
  throw "No se encontraron ambos formatos, NSIS y MSI, en las carpetas de bundle esperadas."
}
foreach ($Installer in $Installers) {
  if ($Installer.Length -ge 2GB) {
    throw "$($Installer.Name) ocupa $($Installer.Length) bytes y supera el límite de 2 GiB de GitHub Releases."
  }
}

if ($StageArtifacts -and $Installers.Count -gt 0) {
  $ReleaseDirectory = Join-Path $ProjectRoot "release"
  New-Item -ItemType Directory -Path $ReleaseDirectory -Force | Out-Null
  $ChecksumLines = @()
  foreach ($Installer in ($Installers | Sort-Object Name)) {
    $Destination = Join-Path $ReleaseDirectory $Installer.Name
    Copy-Item -LiteralPath $Installer.FullName -Destination $Destination -Force
    $Hash = (Get-FileHash -LiteralPath $Destination -Algorithm SHA256).Hash.ToLowerInvariant()
    $ChecksumLines += "$Hash  $($Installer.Name)"
  }
  $ChecksumPath = Join-Path $ReleaseDirectory "checksums-SHA256.txt"
  [System.IO.File]::WriteAllLines($ChecksumPath, $ChecksumLines, [System.Text.UTF8Encoding]::new($false))
  Copy-Item -LiteralPath (Join-Path $ProjectRoot "docs\THIRD_PARTY_NOTICES.md") `
    -Destination (Join-Path $ReleaseDirectory "THIRD_PARTY_NOTICES.md") -Force
  Write-Host "Artefactos preparados en $ReleaseDirectory"
}

Write-Host "Verificación de publicación superada para Transcriptor $Version."
