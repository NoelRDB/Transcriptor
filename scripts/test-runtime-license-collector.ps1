param(
  [string]$PythonExecutable = ""
)

$ErrorActionPreference = "Stop"
$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
if ([string]::IsNullOrWhiteSpace($PythonExecutable)) {
  $PythonExecutable = Join-Path $ProjectRoot "sidecar\.venv\Scripts\python.exe"
}
$ResolvedPython = (Resolve-Path -LiteralPath $PythonExecutable).Path
$TemporaryRoot = Join-Path ([System.IO.Path]::GetTempPath()) `
  ("transcriptor-license-test-" + [guid]::NewGuid())
$SitePackages = Join-Path $TemporaryRoot "site-packages"
$OutputDirectory = Join-Path $TemporaryRoot "output"
$InventoryPath = Join-Path $TemporaryRoot "inventory.json"

function Write-Utf8File {
  param(
    [Parameter(Mandatory = $true)][string]$Path,
    [Parameter(Mandatory = $true)][string]$Content
  )
  New-Item -ItemType Directory -Path (Split-Path -Parent $Path) -Force | Out-Null
  [System.IO.File]::WriteAllText(
    $Path,
    $Content,
    [System.Text.UTF8Encoding]::new($false)
  )
}

try {
  New-Item -ItemType Directory -Path $SitePackages, $OutputDirectory -Force | Out-Null
  $Alpha = Join-Path $SitePackages "alpha_package-1.0.0.dist-info"
  $Beta = Join-Path $SitePackages "beta_package-2.0.0.dist-info"
  $Excluded = Join-Path $SitePackages "av-99.0.0.dist-info"

  Write-Utf8File (Join-Path $Alpha "METADATA") "Name: alpha-package`nVersion: 1.0.0`n"
  Write-Utf8File (Join-Path $Alpha "LICENSE.txt") "alpha root license"
  Write-Utf8File (Join-Path $Alpha "licenses\vendor\LICENSE.txt") "alpha vendor license"
  Write-Utf8File (Join-Path $Beta "METADATA") "Name: beta_package`nVersion: 2.0.0`n"
  Write-Utf8File (Join-Path $Beta "LICENSE.txt") "beta root license"
  Write-Utf8File (Join-Path $Excluded "METADATA") "Name: av`nVersion: 99.0.0`n"
  Write-Utf8File (Join-Path $Excluded "LICENSE.txt") "must never be copied"

  $Inventory = [ordered]@{
    schemaVersion = 1
    distributions = @(
      [ordered]@{ name = "alpha-package"; version = "1.0.0" },
      [ordered]@{ name = "beta-package"; version = "2.0.0" }
    )
    excludedDistributions = @("av")
    bootstrapComponents = @()
  }
  Write-Utf8File $InventoryPath ($Inventory | ConvertTo-Json -Depth 5)

  & (Join-Path $ProjectRoot "scripts\collect-runtime-licenses.ps1") `
    -SitePackagesDirectory $SitePackages `
    -PythonExecutable $ResolvedPython `
    -OutputDirectory $OutputDirectory `
    -InventoryPath $InventoryPath `
    -ProjectRoot $ProjectRoot

  $ManifestPath = Join-Path $OutputDirectory "PYTHON-RUNTIME-LICENSES.json"
  $Manifest = Get-Content -LiteralPath $ManifestPath -Raw -Encoding UTF8 |
    ConvertFrom-Json
  $Distributions = @($Manifest.distributions)
  if ($Distributions.Count -ne 2) {
    throw "Se esperaban dos distribuciones en el manifiesto de prueba."
  }
  $AlphaRecord = $Distributions | Where-Object { $_.canonicalName -eq "alpha-package" }
  $BetaRecord = $Distributions | Where-Object { $_.canonicalName -eq "beta-package" }
  if (@($AlphaRecord.files).Count -ne 2 -or @($BetaRecord.files).Count -ne 1) {
    throw "El recolector perdió licencias con nombres repetidos."
  }

  $AllRecords = @(
    $Manifest.distributions | ForEach-Object { @($_.files) }
    $Manifest.bootstrapComponents | ForEach-Object { @($_.files) }
  )
  $AllPaths = @($AllRecords | ForEach-Object { "$($_.path)" })
  if (($AllPaths | Sort-Object -Unique).Count -ne $AllPaths.Count) {
    throw "El manifiesto contiene una colisión de destinos."
  }
  if ($AllPaths -match "(?i)(?:^|/)av(?:-|/)") {
    throw "El recolector copió una dependencia excluida."
  }
  foreach ($Record in $AllRecords) {
    $LegalPath = Join-Path $OutputDirectory $Record.path
    if (-not (Test-Path -LiteralPath $LegalPath -PathType Leaf)) {
      throw "El manifiesto apunta a un archivo inexistente: $($Record.path)"
    }
    $Hash = (Get-FileHash -LiteralPath $LegalPath -Algorithm SHA256).Hash.ToLowerInvariant()
    if ($Hash -ne "$($Record.sha256)") {
      throw "El hash de prueba no coincide para $($Record.path)"
    }
  }

  Write-Host "Prueba del recolector de licencias superada sin colisiones."
}
finally {
  $ResolvedTemporaryRoot = [System.IO.Path]::GetFullPath($TemporaryRoot)
  $SystemTemporaryPrefix = [System.IO.Path]::GetFullPath(
    [System.IO.Path]::GetTempPath()
  ).TrimEnd(
    [System.IO.Path]::DirectorySeparatorChar,
    [System.IO.Path]::AltDirectorySeparatorChar
  ) + [System.IO.Path]::DirectorySeparatorChar
  if (
    (Test-Path -LiteralPath $ResolvedTemporaryRoot) -and
    $ResolvedTemporaryRoot.StartsWith(
      $SystemTemporaryPrefix,
      [System.StringComparison]::OrdinalIgnoreCase
    ) -and
    [System.IO.Path]::GetFileName($ResolvedTemporaryRoot).StartsWith(
      "transcriptor-license-test-",
      [System.StringComparison]::Ordinal
    )
  ) {
    Remove-Item -LiteralPath $ResolvedTemporaryRoot -Recurse -Force
  }
}
