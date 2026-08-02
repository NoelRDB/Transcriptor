$ErrorActionPreference = "Stop"
$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$TemporaryBase = [System.IO.Path]::GetFullPath(
  [System.IO.Path]::GetTempPath()
).TrimEnd(
  [System.IO.Path]::DirectorySeparatorChar,
  [System.IO.Path]::AltDirectorySeparatorChar
) + [System.IO.Path]::DirectorySeparatorChar
$TemporaryRoot = Join-Path $TemporaryBase (
  "transcriptor-speaker-smoke-$([guid]::NewGuid().ToString('N'))"
)
$ResolvedTemporaryRoot = [System.IO.Path]::GetFullPath($TemporaryRoot)
if (-not $ResolvedTemporaryRoot.StartsWith(
  $TemporaryBase,
  [System.StringComparison]::OrdinalIgnoreCase
)) {
  throw "La prueba CAM++ queda fuera de la carpeta temporal."
}

function New-SmokeWav {
  param([Parameter(Mandatory = $true)][string]$Path)

  $SampleRate = 16000
  $SampleCount = $SampleRate * 2
  $Stream = [System.IO.File]::Create($Path)
  $Writer = [System.IO.BinaryWriter]::new($Stream)
  try {
    $DataBytes = $SampleCount * 2
    $Writer.Write([Text.Encoding]::ASCII.GetBytes("RIFF"))
    $Writer.Write([int](36 + $DataBytes))
    $Writer.Write([Text.Encoding]::ASCII.GetBytes("WAVEfmt "))
    $Writer.Write([int]16)
    $Writer.Write([int16]1)
    $Writer.Write([int16]1)
    $Writer.Write([int]$SampleRate)
    $Writer.Write([int]($SampleRate * 2))
    $Writer.Write([int16]2)
    $Writer.Write([int16]16)
    $Writer.Write([Text.Encoding]::ASCII.GetBytes("data"))
    $Writer.Write([int]$DataBytes)
    for ($Index = 0; $Index -lt $SampleCount; $Index += 1) {
      $Envelope = 0.55 + 0.35 * [Math]::Sin(
        2 * [Math]::PI * 3 * $Index / $SampleRate
      )
      $Wave = [Math]::Sin(2 * [Math]::PI * 180 * $Index / $SampleRate) +
        0.45 * [Math]::Sin(2 * [Math]::PI * 360 * $Index / $SampleRate)
      $Writer.Write([int16](9000 * $Envelope * $Wave))
    }
  }
  finally {
    $Writer.Dispose()
    $Stream.Dispose()
  }
}

New-Item -ItemType Directory -Path $ResolvedTemporaryRoot | Out-Null
$Process = $null
try {
  $IsolatedLocalData = Join-Path $ResolvedTemporaryRoot "Local"
  $ModelDirectory = Join-Path $IsolatedLocalData "TranscriptorData\models\speaker"
  New-Item -ItemType Directory -Path $ModelDirectory -Force | Out-Null
  $ModelName = "3dspeaker_speech_campplus_sv_zh_en_16k-common_advanced.onnx"
  $InstalledModel = Join-Path $env:LOCALAPPDATA "Transcriptor\models\speaker\$ModelName"
  if (-not (Test-Path -LiteralPath $InstalledModel -PathType Leaf)) {
    throw "La prueba necesita el modelo CAM++ local ya instalado."
  }
  Copy-Item -LiteralPath $InstalledModel -Destination (Join-Path $ModelDirectory $ModelName)

  $WavPath = Join-Path $ResolvedTemporaryRoot "speaker-smoke.wav"
  New-SmokeWav $WavPath
  $Executable = Join-Path $ProjectRoot (
    "src-tauri\binaries\transcriptor-engine-x86_64-pc-windows-msvc.exe"
  )
  if (-not (Test-Path -LiteralPath $Executable -PathType Leaf)) {
    throw "Falta el sidecar empaquetado. Ejecuta npm run sidecar:build."
  }
  $StartInfo = [System.Diagnostics.ProcessStartInfo]::new()
  $StartInfo.FileName = $Executable
  $StartInfo.Arguments = "serve"
  $StartInfo.UseShellExecute = $false
  $StartInfo.CreateNoWindow = $true
  $StartInfo.RedirectStandardInput = $true
  $StartInfo.RedirectStandardOutput = $true
  $StartInfo.RedirectStandardError = $true
  $StartInfo.EnvironmentVariables["LOCALAPPDATA"] = $IsolatedLocalData
  $Process = [System.Diagnostics.Process]::new()
  $Process.StartInfo = $StartInfo
  [void]$Process.Start()

  $Now = [DateTime]::UtcNow.ToString("o")
  $Project = @{
    id = "speaker-smoke"
    name = "Speaker smoke"
    mediaPath = $WavPath
    mediaUrl = ""
    mediaType = "audio"
    durationMs = 2000
    model = "turbo"
    createdAt = $Now
    updatedAt = $Now
    transcriptionStatus = "completed"
    lastPlaybackPositionMs = 0
    settings = @{ speakerSensitivity = 55; voiceProfileMinConfidence = 72 }
    segments = @(
      @{
        id = "segment-1"
        startMs = 0
        endMs = 2000
        text = "Prueba de voz"
        words = @()
        order = 0
      }
    )
  }
  $Request = @{
    requestId = "speaker-smoke-request"
    action = "learn_project_voices"
    payload = @{ projectId = "speaker-smoke"; project = $Project }
  } | ConvertTo-Json -Depth 12 -Compress
  $Stopwatch = [System.Diagnostics.Stopwatch]::StartNew()
  $Process.StandardInput.WriteLine($Request)
  $TerminalEvent = $null
  while ($Stopwatch.Elapsed.TotalSeconds -lt 45) {
    $Line = $Process.StandardOutput.ReadLine()
    if ($null -eq $Line) { break }
    $Event = $Line | ConvertFrom-Json
    if ($Event.type -in @(
      "voice_learning_completed",
      "voice_learning_failed",
      "voice_learning_cancelled"
    )) {
      $TerminalEvent = $Event
      break
    }
  }
  $Process.StandardInput.Close()
  if (-not $Process.WaitForExit(5000)) { $Process.Kill() }
  if ($null -eq $TerminalEvent) {
    throw "La prueba CAM++ no terminó. $($Process.StandardError.ReadToEnd())"
  }
  if ($TerminalEvent.type -ne "voice_learning_completed") {
    throw "CAM++ empaquetado falló: $($TerminalEvent.payload.message)"
  }
  Write-Host (
    "CAM++ empaquetado verificado en $($Stopwatch.ElapsedMilliseconds) ms: " +
    $TerminalEvent.payload.message
  )
}
finally {
  if ($Process -and -not $Process.HasExited) {
    $Process.Kill()
    $Process.WaitForExit()
  }
  if (
    (Test-Path -LiteralPath $ResolvedTemporaryRoot -PathType Container) -and
    $ResolvedTemporaryRoot.StartsWith(
      $TemporaryBase,
      [System.StringComparison]::OrdinalIgnoreCase
    )
  ) {
    Remove-Item -LiteralPath $ResolvedTemporaryRoot -Recurse -Force
  }
}
