param(
  [Parameter(Mandatory = $true)][string]$FfmpegDirectory,
  [Parameter(Mandatory = $true)][string]$FixtureDirectory
)

$ErrorActionPreference = "Stop"
$ResolvedFfmpegDirectory = (Resolve-Path -LiteralPath $FfmpegDirectory).Path
$ResolvedFixtureDirectory = (Resolve-Path -LiteralPath $FixtureDirectory).Path
$Ffmpeg = Join-Path $ResolvedFfmpegDirectory "ffmpeg.exe"
$Ffprobe = Join-Path $ResolvedFfmpegDirectory "ffprobe.exe"
foreach ($Executable in @($Ffmpeg, $Ffprobe)) {
  if (-not (Test-Path -LiteralPath $Executable -PathType Leaf)) {
    throw "Falta el ejecutable multimedia de prueba: $Executable"
  }
}

function Invoke-CheckedNative {
  param(
    [Parameter(Mandatory = $true)][string]$Command,
    [Parameter(ValueFromRemainingArguments = $true)][string[]]$Arguments
  )
  & $Command @Arguments
  if ($LASTEXITCODE -ne 0) {
    throw "Falló '$Command $($Arguments -join ' ')' con código $LASTEXITCODE."
  }
}

function Read-MediaProbe {
  param([Parameter(Mandatory = $true)][string]$Path)
  $Output = & $Ffprobe `
    -v error `
    -show_entries "format=duration,format_name:stream=codec_type,codec_name" `
    -of json `
    $Path
  if ($LASTEXITCODE -ne 0) {
    throw "FFprobe no pudo analizar $Path"
  }
  return ($Output -join "`n") | ConvertFrom-Json
}

$VersionOutput = (& $Ffmpeg -version 2>&1) -join "`n"
# FFmpeg cita automáticamente los argumentos que contienen comas al mostrar
# la configuración, aunque conserve exactamente los mismos valores.
$NormalizedVersionOutput = $VersionOutput.Replace("'", "")
foreach ($RequiredConfiguration in @(
  "--disable-autodetect",
  "--disable-network",
  "--disable-gpl",
  "--disable-nonfree",
  "--enable-version3",
  "--enable-encoder=pcm_s16le,aac,mpeg4",
  "--enable-muxer=pcm_s16le,wav,mp4,mov"
)) {
  if ($NormalizedVersionOutput.IndexOf(
      $RequiredConfiguration,
      [System.StringComparison]::Ordinal
    ) -lt 0) {
    throw "El runtime no acredita la configuración requerida: $RequiredConfiguration"
  }
}
if ($VersionOutput -match "--enable-lib") {
  throw "El runtime FFmpeg de publicación activa una biblioteca externa."
}

$Fixtures = @(
  @{ Name = "audio.mp3"; Type = "audio" },
  @{ Name = "audio.wav"; Type = "audio" },
  @{ Name = "audio.m4a"; Type = "audio" },
  @{ Name = "audio.aac"; Type = "audio" },
  @{ Name = "audio.flac"; Type = "audio" },
  @{ Name = "audio.ogg"; Type = "audio" },
  @{ Name = "audio.opus"; Type = "audio" },
  @{ Name = "video.mp4"; Type = "video" },
  @{ Name = "video.mov"; Type = "video" },
  @{ Name = "video.mkv"; Type = "video" },
  @{ Name = "video.avi"; Type = "video" },
  @{ Name = "video.webm"; Type = "video" },
  @{ Name = "video.m4v"; Type = "video" }
)
$TemporaryRoot = Join-Path ([System.IO.Path]::GetTempPath()) `
  ("Transcriptor FFmpeg á " + [guid]::NewGuid())
New-Item -ItemType Directory -Path $TemporaryRoot | Out-Null

try {
  $UnicodeFixtureDirectory = Join-Path $TemporaryRoot "medios con espacios y Unicode"
  New-Item -ItemType Directory -Path $UnicodeFixtureDirectory | Out-Null
  foreach ($Fixture in $Fixtures) {
    $SourcePath = Join-Path $ResolvedFixtureDirectory $Fixture.Name
    if (-not (Test-Path -LiteralPath $SourcePath -PathType Leaf)) {
      throw "Falta el fixture sintético $($Fixture.Name)."
    }
    $FixturePath = Join-Path $UnicodeFixtureDirectory $Fixture.Name
    Copy-Item -LiteralPath $SourcePath -Destination $FixturePath
    $Probe = Read-MediaProbe $FixturePath
    $StreamTypes = @($Probe.streams | ForEach-Object { "$($_.codec_type)" })
    if ("audio" -notin $StreamTypes) {
      throw "$($Fixture.Name) no expone una pista de audio."
    }
    if ($Fixture.Type -eq "video" -and "video" -notin $StreamTypes) {
      throw "$($Fixture.Name) no expone una pista de vídeo."
    }
    if ([double]$Probe.format.duration -le 0) {
      throw "$($Fixture.Name) no tiene duración válida."
    }

    $PcmPath = Join-Path $TemporaryRoot "$($Fixture.Name).s16le"
    Invoke-CheckedNative -Command $Ffmpeg -Arguments @(
      "-hide_banner", "-nostdin", "-loglevel", "error", "-y",
      "-i", $FixturePath, "-map", "0:a:0", "-vn", "-ac", "1",
      "-ar", "16000", "-f", "s16le", $PcmPath
    )
    if ((Get-Item -LiteralPath $PcmPath).Length -lt 16000) {
      throw "La extracción PCM de $($Fixture.Name) parece truncada."
    }
  }

  $EditedAudio = Join-Path $TemporaryRoot "edición de audio.wav"
  $AudioFilter = (
    "[0:a]atrim=start=0:end=0.4,asetpts=PTS-STARTPTS," +
    "aresample=16000,aformat=sample_fmts=fltp:channel_layouts=mono[a0];" +
    "[0:a]atrim=start=0.6:end=1.0,asetpts=PTS-STARTPTS," +
    "aresample=16000,aformat=sample_fmts=fltp:channel_layouts=mono[a1];" +
    "[a0][a1]concat=n=2:v=0:a=1[outa]"
  )
  Invoke-CheckedNative -Command $Ffmpeg -Arguments @(
    "-hide_banner", "-nostdin", "-loglevel", "error", "-y",
    "-i", (Join-Path $UnicodeFixtureDirectory "audio.flac"),
    "-filter_complex", $AudioFilter, "-map", "[outa]",
    "-c:a", "pcm_s16le", $EditedAudio
  )
  $EditedAudioProbe = Read-MediaProbe $EditedAudio
  if ("audio" -notin @($EditedAudioProbe.streams.codec_type)) {
    throw "La edición WAV no produjo audio."
  }

  $EditedVideo = Join-Path $TemporaryRoot "edición de vídeo.mp4"
  $VideoFilter = (
    "[0:v]trim=start=0:end=0.4,setpts=PTS-STARTPTS," +
    "scale=96:64,format=yuv420p[v0];" +
    "[0:a]atrim=start=0:end=0.4,asetpts=PTS-STARTPTS,aresample=32000[a0];" +
    "[0:v]trim=start=0.6:end=1.0,setpts=PTS-STARTPTS," +
    "scale=96:64,format=yuv420p[v1];" +
    "[0:a]atrim=start=0.6:end=1.0,asetpts=PTS-STARTPTS,aresample=32000[a1];" +
    "[v0][a0][v1][a1]concat=n=2:v=1:a=1[outv][outa]"
  )
  Invoke-CheckedNative -Command $Ffmpeg -Arguments @(
    "-hide_banner", "-nostdin", "-loglevel", "error", "-y",
    "-i", (Join-Path $UnicodeFixtureDirectory "video.mkv"),
    "-filter_complex", $VideoFilter,
    "-map", "[outv]", "-map", "[outa]",
    "-c:v", "mpeg4", "-q:v", "5",
    "-c:a", "aac", "-movflags", "+faststart", $EditedVideo
  )
  $EditedVideoProbe = Read-MediaProbe $EditedVideo
  $EditedStreamTypes = @($EditedVideoProbe.streams.codec_type)
  if ("audio" -notin $EditedStreamTypes -or "video" -notin $EditedStreamTypes) {
    throw "La edición MP4 no produjo audio y vídeo."
  }

  Write-Host (
    "FFmpeg Windows superó {0} formatos, extracción PCM y edición multimedia." -f
      $Fixtures.Count
  )
}
finally {
  $ResolvedTemporaryRoot = [System.IO.Path]::GetFullPath($TemporaryRoot)
  $TemporaryPrefix = [System.IO.Path]::GetFullPath(
    [System.IO.Path]::GetTempPath()
  ).TrimEnd(
    [System.IO.Path]::DirectorySeparatorChar,
    [System.IO.Path]::AltDirectorySeparatorChar
  ) + [System.IO.Path]::DirectorySeparatorChar
  if (
    (Test-Path -LiteralPath $ResolvedTemporaryRoot) -and
    $ResolvedTemporaryRoot.StartsWith(
      $TemporaryPrefix,
      [System.StringComparison]::OrdinalIgnoreCase
    ) -and
    [System.IO.Path]::GetFileName($ResolvedTemporaryRoot).StartsWith(
      "Transcriptor FFmpeg á ",
      [System.StringComparison]::Ordinal
    )
  ) {
    Remove-Item -LiteralPath $ResolvedTemporaryRoot -Recurse -Force
  }
}
