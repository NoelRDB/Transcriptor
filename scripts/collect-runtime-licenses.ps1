param(
  [Parameter(Mandatory = $true)][string]$SitePackagesDirectory,
  [Parameter(Mandatory = $true)][string]$PythonExecutable,
  [Parameter(Mandatory = $true)][string]$OutputDirectory,
  [string]$InventoryPath = "",
  [string]$ProjectRoot = ""
)

$ErrorActionPreference = "Stop"
if ([string]::IsNullOrWhiteSpace($ProjectRoot)) {
  $ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
}
else {
  $ProjectRoot = (Resolve-Path -LiteralPath $ProjectRoot).Path
}
if ([string]::IsNullOrWhiteSpace($InventoryPath)) {
  $InventoryPath = Join-Path $ProjectRoot "docs\licenses\PYTHON-RUNTIME-INVENTORY.json"
}

$ResolvedSitePackages = (Resolve-Path -LiteralPath $SitePackagesDirectory).Path
$ResolvedPython = (Resolve-Path -LiteralPath $PythonExecutable).Path
$ResolvedInventory = (Resolve-Path -LiteralPath $InventoryPath).Path
New-Item -ItemType Directory -Path $OutputDirectory -Force | Out-Null
$ResolvedOutput = (Resolve-Path -LiteralPath $OutputDirectory).Path

function ConvertTo-CanonicalDistributionName {
  param([Parameter(Mandatory = $true)][string]$Name)
  return ($Name.Trim().ToLowerInvariant() -replace "[-_.]+", "-")
}

function Assert-PathInside {
  param(
    [Parameter(Mandatory = $true)][string]$Root,
    [Parameter(Mandatory = $true)][string]$Candidate,
    [Parameter(Mandatory = $true)][string]$Description
  )
  $RootPrefix = [System.IO.Path]::GetFullPath($Root).TrimEnd(
    [System.IO.Path]::DirectorySeparatorChar,
    [System.IO.Path]::AltDirectorySeparatorChar
  ) + [System.IO.Path]::DirectorySeparatorChar
  $FullCandidate = [System.IO.Path]::GetFullPath($Candidate)
  if (-not $FullCandidate.StartsWith($RootPrefix, [System.StringComparison]::OrdinalIgnoreCase)) {
    throw "$Description queda fuera de la carpeta permitida: $FullCandidate"
  }
  return $FullCandidate
}

function Get-RelativeChildPath {
  param(
    [Parameter(Mandatory = $true)][string]$Root,
    [Parameter(Mandatory = $true)][string]$Candidate
  )
  $RootPrefix = [System.IO.Path]::GetFullPath($Root).TrimEnd(
    [System.IO.Path]::DirectorySeparatorChar,
    [System.IO.Path]::AltDirectorySeparatorChar
  ) + [System.IO.Path]::DirectorySeparatorChar
  $FullCandidate = Assert-PathInside $Root $Candidate "La ruta relativa"
  return $FullCandidate.Substring($RootPrefix.Length)
}

function ConvertTo-SafeRelativePath {
  param([Parameter(Mandatory = $true)][string]$RelativePath)
  if ([System.IO.Path]::IsPathRooted($RelativePath)) {
    throw "Se rechazó una ruta legal absoluta: $RelativePath"
  }
  $Segments = @($RelativePath -split "[/\\]+")
  if ($Segments.Count -lt 1 -or $Segments | Where-Object { $_ -in @("", ".", "..") }) {
    throw "Se rechazó una ruta legal no segura: $RelativePath"
  }
  $SafeSegments = @(
    $Segments | ForEach-Object {
      $SafeSegment = $_ -replace "[^A-Za-z0-9._-]", "_"
      if ([string]::IsNullOrWhiteSpace($SafeSegment)) {
        throw "No se pudo normalizar una parte de la ruta legal: $RelativePath"
      }
      $SafeSegment
    }
  )
  # PowerShell convierte un object[] implícitamente en una sola cadena al
  # resolver esta sobrecarga. Forzar string[] conserva cada segmento como una
  # parte real de la ruta en vez de unirlos con espacios.
  return [System.IO.Path]::Combine([string[]]$SafeSegments)
}

function Copy-VerifiedLegalFile {
  param(
    [Parameter(Mandatory = $true)][string]$Source,
    [Parameter(Mandatory = $true)][string]$Destination,
    [string]$ExpectedSha256 = ""
  )
  if (-not (Test-Path -LiteralPath $Source -PathType Leaf)) {
    throw "Falta un texto legal requerido: $Source"
  }
  if (Test-Path -LiteralPath $Destination) {
    throw "Dos textos legales intentan ocupar el mismo destino: $Destination"
  }
  if (-not [string]::IsNullOrWhiteSpace($ExpectedSha256)) {
    if ($ExpectedSha256 -notmatch "^[A-Fa-f0-9]{64}$") {
      throw "SHA-256 legal inválido para $Source"
    }
    $ActualSourceHash = (Get-FileHash -LiteralPath $Source -Algorithm SHA256).Hash
    if ($ActualSourceHash -ne $ExpectedSha256.ToUpperInvariant()) {
      throw "El texto legal no coincide con su versión fijada: $Source"
    }
  }
  New-Item -ItemType Directory -Path (Split-Path -Parent $Destination) -Force | Out-Null
  Copy-Item -LiteralPath $Source -Destination $Destination
  $SourceHash = (Get-FileHash -LiteralPath $Source -Algorithm SHA256).Hash.ToLowerInvariant()
  $DestinationHash = (Get-FileHash -LiteralPath $Destination -Algorithm SHA256).Hash.ToLowerInvariant()
  if ($SourceHash -ne $DestinationHash) {
    throw "La copia del texto legal no conserva sus bytes: $Destination"
  }
  return $DestinationHash
}

function Get-DistributionMetadata {
  param([Parameter(Mandatory = $true)][System.IO.DirectoryInfo]$Directory)
  $MetadataPath = Join-Path $Directory.FullName "METADATA"
  if (-not (Test-Path -LiteralPath $MetadataPath -PathType Leaf)) {
    return $null
  }
  $Metadata = [System.IO.File]::ReadAllText($MetadataPath)
  $NameMatch = [regex]::Match($Metadata, "(?m)^Name:\s*(.+?)\s*$")
  $VersionMatch = [regex]::Match($Metadata, "(?m)^Version:\s*(.+?)\s*$")
  if (-not $NameMatch.Success -or -not $VersionMatch.Success) {
    throw "METADATA no declara Name y Version: $MetadataPath"
  }
  return [pscustomobject]@{
    Name = $NameMatch.Groups[1].Value.Trim()
    CanonicalName = ConvertTo-CanonicalDistributionName $NameMatch.Groups[1].Value
    Version = $VersionMatch.Groups[1].Value.Trim()
    Directory = $Directory
  }
}

$Inventory = Get-Content -LiteralPath $ResolvedInventory -Raw -Encoding UTF8 | ConvertFrom-Json
if ([int]$Inventory.schemaVersion -ne 1) {
  throw "Versión de inventario de licencias Python no compatible."
}

$ForbiddenNames = @(
  $Inventory.excludedDistributions |
    ForEach-Object { ConvertTo-CanonicalDistributionName "$_" }
)
$ExpectedNames = @(
  $Inventory.distributions |
    ForEach-Object { ConvertTo-CanonicalDistributionName "$($_.name)" }
)
if (($ExpectedNames | Sort-Object -Unique).Count -ne $ExpectedNames.Count) {
  throw "El inventario contiene distribuciones Python duplicadas."
}
foreach ($ExpectedName in $ExpectedNames) {
  if ($ExpectedName -in $ForbiddenNames) {
    throw "Una dependencia excluida aparece en el inventario de runtime: $ExpectedName"
  }
}

$InstalledDistributions = @(
  Get-ChildItem -LiteralPath $ResolvedSitePackages -Directory -Filter "*.dist-info" |
    ForEach-Object { Get-DistributionMetadata $_ } |
    Where-Object { $null -ne $_ }
)

$PythonOutput = Join-Path $ResolvedOutput "python"
$BootstrapOutput = Join-Path $ResolvedOutput "bootstrap"
foreach ($GeneratedDirectory in @($PythonOutput, $BootstrapOutput)) {
  $SafeGeneratedDirectory = Assert-PathInside $ResolvedOutput $GeneratedDirectory "La salida de licencias"
  if (Test-Path -LiteralPath $SafeGeneratedDirectory) {
    Remove-Item -LiteralPath $SafeGeneratedDirectory -Recurse -Force
  }
  New-Item -ItemType Directory -Path $SafeGeneratedDirectory -Force | Out-Null
}

$DistributionRecords = @()
foreach ($Expected in $Inventory.distributions) {
  $CanonicalName = ConvertTo-CanonicalDistributionName "$($Expected.name)"
  $Matches = @(
    $InstalledDistributions |
      Where-Object {
        $_.CanonicalName -eq $CanonicalName -and $_.Version -eq "$($Expected.version)"
      }
  )
  if ($Matches.Count -ne 1) {
    throw "Se esperaba exactamente $($Expected.name)==$($Expected.version), encontrados: $($Matches.Count)."
  }

  $Installed = $Matches[0]
  $SafeDistributionDirectoryName = "$CanonicalName-$($Installed.Version)" -replace "[^A-Za-z0-9._-]", "_"
  $DistributionOutput = Join-Path $PythonOutput $SafeDistributionDirectoryName
  $FileRecords = @()

  $WheelLegalFiles = @(
    Get-ChildItem -LiteralPath $Installed.Directory.FullName -Recurse -File |
      Where-Object {
        $_.Name -match "^(LICENSE|LICENCE|COPYING|NOTICE)" -or
        $_.DirectoryName.StartsWith(
          (Join-Path $Installed.Directory.FullName "licenses"),
          [System.StringComparison]::OrdinalIgnoreCase
        )
      } |
      Sort-Object FullName -Unique
  )
  foreach ($WheelLegalFile in $WheelLegalFiles) {
    $RelativeSource = Get-RelativeChildPath `
      -Root $Installed.Directory.FullName `
      -Candidate $WheelLegalFile.FullName
    $SafeRelativeSource = ConvertTo-SafeRelativePath $RelativeSource
    $Destination = Join-Path $DistributionOutput (Join-Path "wheel" $SafeRelativeSource)
    $Hash = Copy-VerifiedLegalFile $WheelLegalFile.FullName $Destination
    $FileRecords += [pscustomobject]@{
      source = "wheel:$($Installed.Directory.Name)/$($RelativeSource.Replace('\', '/'))"
      path = (
        Get-RelativeChildPath -Root $ResolvedOutput -Candidate $Destination
      ).Replace("\", "/")
      sha256 = $Hash
    }
  }

  foreach ($RepositoryFile in @($Expected.repositoryFiles)) {
    if ($null -eq $RepositoryFile) { continue }
    $Source = Assert-PathInside $ProjectRoot (Join-Path $ProjectRoot "$($RepositoryFile.source)") `
      "El texto legal versionado"
    $SafeTarget = ConvertTo-SafeRelativePath "$($RepositoryFile.target)"
    $Destination = Join-Path $DistributionOutput (Join-Path "repository" $SafeTarget)
    $Hash = Copy-VerifiedLegalFile $Source $Destination "$($RepositoryFile.sha256)"
    $FileRecords += [pscustomobject]@{
      source = "repository:$($RepositoryFile.source)"
      path = (
        Get-RelativeChildPath -Root $ResolvedOutput -Candidate $Destination
      ).Replace("\", "/")
      sha256 = $Hash
    }
  }

  foreach ($PackageFile in @($Expected.packageFiles)) {
    if ($null -eq $PackageFile) { continue }
    $Source = Assert-PathInside $ResolvedSitePackages `
      (Join-Path $ResolvedSitePackages "$($PackageFile.source)") "El aviso incluido en el paquete"
    $SafeTarget = ConvertTo-SafeRelativePath "$($PackageFile.target)"
    $Destination = Join-Path $DistributionOutput (Join-Path "package" $SafeTarget)
    $Hash = Copy-VerifiedLegalFile $Source $Destination "$($PackageFile.sha256)"
    $FileRecords += [pscustomobject]@{
      source = "package:$($PackageFile.source)"
      path = (
        Get-RelativeChildPath -Root $ResolvedOutput -Candidate $Destination
      ).Replace("\", "/")
      sha256 = $Hash
    }
  }

  if ($FileRecords.Count -lt 1) {
    throw "No se encontró ningún texto legal para $($Expected.name)==$($Expected.version)."
  }
  $DistributionRecords += [pscustomobject]@{
    name = "$($Expected.name)"
    canonicalName = $CanonicalName
    version = "$($Expected.version)"
    files = @($FileRecords | Sort-Object path)
  }
}

$BootstrapRecords = @()
foreach ($Bootstrap in @($Inventory.bootstrapComponents)) {
  if ($null -eq $Bootstrap) { continue }
  $CanonicalDistribution = ConvertTo-CanonicalDistributionName "$($Bootstrap.distribution)"
  $Matches = @(
    $InstalledDistributions |
      Where-Object {
        $_.CanonicalName -eq $CanonicalDistribution -and $_.Version -eq "$($Bootstrap.version)"
      }
  )
  if ($Matches.Count -ne 1) {
    throw "No se encontró el componente de arranque $($Bootstrap.name)==$($Bootstrap.version)."
  }
  $Installed = $Matches[0]
  $SafeBootstrapName = "$($Bootstrap.name)-$($Bootstrap.version)" -replace "[^A-Za-z0-9._-]", "_"
  $ComponentOutput = Join-Path $BootstrapOutput $SafeBootstrapName
  $FileRecords = @()
  foreach ($RequiredFile in @($Bootstrap.requiredFiles)) {
    $SafeRequiredFile = ConvertTo-SafeRelativePath "$RequiredFile"
    $Source = Assert-PathInside $Installed.Directory.FullName `
      (Join-Path $Installed.Directory.FullName "$RequiredFile") "El aviso del componente de arranque"
    $Destination = Join-Path $ComponentOutput $SafeRequiredFile
    $Hash = Copy-VerifiedLegalFile $Source $Destination
    $FileRecords += [pscustomobject]@{
      source = "wheel:$($Installed.Directory.Name)/$("$RequiredFile".Replace('\', '/'))"
      path = (
        Get-RelativeChildPath -Root $ResolvedOutput -Candidate $Destination
      ).Replace("\", "/")
      sha256 = $Hash
    }
  }
  $BootstrapRecords += [pscustomobject]@{
    name = "$($Bootstrap.name)"
    version = "$($Bootstrap.version)"
    files = @($FileRecords | Sort-Object path)
  }
}

$PythonVersion = (& $ResolvedPython -c "import platform; print(platform.python_version())").Trim()
$PythonBasePrefix = (& $ResolvedPython -c "import sys; print(sys.base_prefix)").Trim()
$PythonLicense = Assert-PathInside $PythonBasePrefix (Join-Path $PythonBasePrefix "LICENSE.txt") `
  "La licencia del runtime Python"
$PythonLicenseDestination = Join-Path $BootstrapOutput `
  (Join-Path "Python-$PythonVersion" "LICENSE.txt")
$PythonLicenseHash = Copy-VerifiedLegalFile $PythonLicense $PythonLicenseDestination
$BootstrapRecords += [pscustomobject]@{
  name = "Python"
  version = $PythonVersion
  files = @(
    [pscustomobject]@{
      source = "python-runtime:LICENSE.txt"
      path = (Get-RelativeChildPath `
        -Root $ResolvedOutput `
        -Candidate $PythonLicenseDestination
      ).Replace("\", "/")
      sha256 = $PythonLicenseHash
    }
  )
}

$Manifest = [ordered]@{
  schemaVersion = 1
  inventory = "PYTHON-RUNTIME-INVENTORY.json"
  distributions = @($DistributionRecords | Sort-Object canonicalName)
  bootstrapComponents = @($BootstrapRecords | Sort-Object name)
}
$ManifestPath = Join-Path $ResolvedOutput "PYTHON-RUNTIME-LICENSES.json"
[System.IO.File]::WriteAllText(
  $ManifestPath,
  ($Manifest | ConvertTo-Json -Depth 10),
  [System.Text.UTF8Encoding]::new($false)
)
Copy-Item -LiteralPath $ResolvedInventory `
  -Destination (Join-Path $ResolvedOutput "PYTHON-RUNTIME-INVENTORY.json") -Force

Write-Host (
  "Licencias runtime recopiladas sin colisiones: {0} distribuciones, {1} componentes de arranque." -f
    $DistributionRecords.Count,
    $BootstrapRecords.Count
)
