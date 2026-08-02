param(
  [Parameter(Mandatory = $true, Position = 0)]
  [ValidateNotNullOrEmpty()]
  [string[]]$Path,

  [ValidateNotNullOrEmpty()]
  [string]$ExpectedPublisher = "SignPath Foundation",

  [bool]$RequireTimestamp = $true
)

$ErrorActionPreference = "Stop"

function Resolve-SignTool {
  $Command = Get-Command "signtool.exe" -ErrorAction SilentlyContinue
  if ($Command) {
    return $Command.Source
  }

  $ProgramFilesX86 = ${env:ProgramFiles(x86)}
  if ([string]::IsNullOrWhiteSpace($ProgramFilesX86)) {
    throw "No se pudo localizar SignTool: ProgramFiles(x86) no esta definido."
  }

  $SdkBinDirectory = Join-Path $ProgramFilesX86 "Windows Kits\10\bin"
  if (-not (Test-Path -LiteralPath $SdkBinDirectory -PathType Container)) {
    throw "No se encontro SignTool. Instala Windows SDK antes de verificar una release."
  }

  $Candidates = @(
    Get-ChildItem -LiteralPath $SdkBinDirectory -Directory -ErrorAction SilentlyContinue |
      ForEach-Object {
        $Candidate = Join-Path $_.FullName "x64\signtool.exe"
        if (Test-Path -LiteralPath $Candidate -PathType Leaf) {
          Get-Item -LiteralPath $Candidate
        }
      } |
      Sort-Object {
        try {
          [version]$_.Directory.Parent.Name
        }
        catch {
          [version]"0.0"
        }
      } -Descending
  )

  if ($Candidates.Count -eq 0) {
    throw "No se encontro SignTool x64 en Windows SDK."
  }

  return $Candidates[0].FullName
}

$Artifacts = @()
foreach ($RequestedPath in $Path) {
  if (-not (Test-Path -LiteralPath $RequestedPath)) {
    throw "No existe el artefacto o directorio de firma: $RequestedPath"
  }

  $ResolvedPath = (Resolve-Path -LiteralPath $RequestedPath).Path
  if (Test-Path -LiteralPath $ResolvedPath -PathType Container) {
    $Artifacts += @(
      Get-ChildItem -LiteralPath $ResolvedPath -Recurse -File |
        Where-Object {
          $_.Extension -ieq ".msi" -or
          ($_.Extension -ieq ".exe" -and $_.Name -like "*-setup.exe")
        }
    )
  }
  else {
    $Artifact = Get-Item -LiteralPath $ResolvedPath
    if ($Artifact.Extension -ine ".msi" -and $Artifact.Extension -ine ".exe") {
      throw "Authenticode solo se verifica aqui para instaladores EXE o MSI: $ResolvedPath"
    }
    $Artifacts += $Artifact
  }
}

$Artifacts = @(
  $Artifacts |
    Sort-Object FullName -Unique
)

if ($Artifacts.Count -eq 0) {
  throw "No se encontraron instaladores EXE o MSI para verificar."
}

$SignTool = Resolve-SignTool
foreach ($Artifact in $Artifacts) {
  $Signature = Get-AuthenticodeSignature -LiteralPath $Artifact.FullName
  if ($Signature.Status -ne [System.Management.Automation.SignatureStatus]::Valid) {
    throw "Firma Authenticode no valida en '$($Artifact.FullName)': $($Signature.Status) - $($Signature.StatusMessage)"
  }
  if (-not $Signature.SignerCertificate) {
    throw "El instalador no incluye certificado de editor: $($Artifact.FullName)"
  }

  $Publisher = $Signature.SignerCertificate.GetNameInfo(
    [System.Security.Cryptography.X509Certificates.X509NameType]::SimpleName,
    $false
  )
  if (-not [string]::Equals(
      $Publisher,
      $ExpectedPublisher,
      [System.StringComparison]::OrdinalIgnoreCase
    )) {
    throw "Editor inesperado en '$($Artifact.FullName)'. Esperado: '$ExpectedPublisher'. Detectado: '$Publisher'."
  }

  if ($RequireTimestamp -and -not $Signature.TimeStamperCertificate) {
    throw "El instalador no tiene sello temporal Authenticode: $($Artifact.FullName)"
  }

  $SignToolOutput = @(
    & $SignTool verify /pa /all /tw /v $Artifact.FullName 2>&1
  )
  $SignToolExitCode = $LASTEXITCODE
  if ($SignToolExitCode -ne 0) {
    throw @"
SignTool rechazo '$($Artifact.FullName)' con codigo $SignToolExitCode.
$($SignToolOutput -join [Environment]::NewLine)
"@
  }

  $TimestampPublisher = if ($Signature.TimeStamperCertificate) {
    $Signature.TimeStamperCertificate.GetNameInfo(
      [System.Security.Cryptography.X509Certificates.X509NameType]::SimpleName,
      $false
    )
  }
  else {
    "sin sello temporal"
  }
  Write-Host "Firma valida: $($Artifact.Name) | Editor: $Publisher | Timestamp: $TimestampPublisher"
}

Write-Host "Verificacion Authenticode superada para $($Artifacts.Count) instalador(es)."
