#!/usr/bin/env bash
set -euo pipefail

if [[ $# -ne 1 ]]; then
  echo "Uso: $0 OUTPUT_DIRECTORY" >&2
  exit 2
fi
for command_name in ffmpeg ffprobe; do
  if ! command -v "$command_name" >/dev/null 2>&1; then
    echo "Falta $command_name para generar los medios sintéticos." >&2
    exit 1
  fi
done

OUTPUT_DIRECTORY="$1"
mkdir -p "$OUTPUT_DIRECTORY"
OUTPUT_DIRECTORY="$(cd "$OUTPUT_DIRECTORY" && pwd)"
if [[ "$OUTPUT_DIRECTORY" == "/" || "$OUTPUT_DIRECTORY" == "$HOME" ]]; then
  echo "La salida de fixtures no puede ser una carpeta amplia del sistema." >&2
  exit 1
fi

FFMPEG_COMMON=(-hide_banner -loglevel error -nostdin -y)
ffmpeg "${FFMPEG_COMMON[@]}" \
  -f lavfi -i "sine=frequency=523.25:sample_rate=48000:duration=1.2" \
  -c:a pcm_s16le "$OUTPUT_DIRECTORY/audio.wav"
ffmpeg "${FFMPEG_COMMON[@]}" -i "$OUTPUT_DIRECTORY/audio.wav" \
  -c:a libmp3lame -b:a 96k "$OUTPUT_DIRECTORY/audio.mp3"
ffmpeg "${FFMPEG_COMMON[@]}" -i "$OUTPUT_DIRECTORY/audio.wav" \
  -c:a aac -b:a 64k "$OUTPUT_DIRECTORY/audio.m4a"
ffmpeg "${FFMPEG_COMMON[@]}" -i "$OUTPUT_DIRECTORY/audio.wav" \
  -c:a aac -b:a 64k -f adts "$OUTPUT_DIRECTORY/audio.aac"
ffmpeg "${FFMPEG_COMMON[@]}" -i "$OUTPUT_DIRECTORY/audio.wav" \
  -c:a flac "$OUTPUT_DIRECTORY/audio.flac"
ffmpeg "${FFMPEG_COMMON[@]}" -i "$OUTPUT_DIRECTORY/audio.wav" \
  -c:a libvorbis -q:a 3 "$OUTPUT_DIRECTORY/audio.ogg"
ffmpeg "${FFMPEG_COMMON[@]}" -i "$OUTPUT_DIRECTORY/audio.wav" \
  -c:a libopus -b:a 64k -f opus "$OUTPUT_DIRECTORY/audio.opus"

generate_mpeg4_video() {
  local output_path="$1"
  local container_arguments=("${@:2}")
  ffmpeg "${FFMPEG_COMMON[@]}" \
    -f lavfi -i "testsrc2=size=96x64:rate=12:duration=1.2" \
    -f lavfi -i "sine=frequency=659.25:sample_rate=48000:duration=1.2" \
    -shortest -c:v mpeg4 -q:v 8 -pix_fmt yuv420p \
    -c:a aac -b:a 64k "${container_arguments[@]}" "$output_path"
}
generate_mpeg4_video "$OUTPUT_DIRECTORY/video.mp4"
generate_mpeg4_video "$OUTPUT_DIRECTORY/video.mov"
generate_mpeg4_video "$OUTPUT_DIRECTORY/video.mkv"
ffmpeg "${FFMPEG_COMMON[@]}" \
  -f lavfi -i "testsrc2=size=96x64:rate=12:duration=1.2" \
  -f lavfi -i "sine=frequency=659.25:sample_rate=48000:duration=1.2" \
  -shortest -c:v mpeg4 -q:v 8 -pix_fmt yuv420p \
  -c:a pcm_s16le "$OUTPUT_DIRECTORY/video.avi"
ffmpeg "${FFMPEG_COMMON[@]}" \
  -f lavfi -i "testsrc2=size=96x64:rate=12:duration=1.2" \
  -f lavfi -i "sine=frequency=659.25:sample_rate=48000:duration=1.2" \
  -shortest -c:v libvpx -deadline realtime -cpu-used 8 -pix_fmt yuv420p \
  -c:a libopus -b:a 64k "$OUTPUT_DIRECTORY/video.webm"
generate_mpeg4_video "$OUTPUT_DIRECTORY/video.m4v" -f mp4

audio_fixtures=(
  audio.mp3 audio.wav audio.m4a audio.aac audio.flac audio.ogg audio.opus
)
video_fixtures=(
  video.mp4 video.mov video.mkv video.avi video.webm video.m4v
)
for fixture_name in "${audio_fixtures[@]}"; do
  stream_types="$(ffprobe -v error -show_entries stream=codec_type \
    -of csv=p=0 "$OUTPUT_DIRECTORY/$fixture_name")"
  if [[ "$stream_types" != *audio* ]]; then
    echo "$fixture_name no contiene audio válido." >&2
    exit 1
  fi
done
for fixture_name in "${video_fixtures[@]}"; do
  stream_types="$(ffprobe -v error -show_entries stream=codec_type \
    -of csv=p=0 "$OUTPUT_DIRECTORY/$fixture_name")"
  if [[ "$stream_types" != *audio* || "$stream_types" != *video* ]]; then
    echo "$fixture_name no contiene audio y vídeo válidos." >&2
    exit 1
  fi
done

printf '%s\n' \
  "Fixtures multimedia sintéticos generados en CI; no contienen datos personales." \
  > "$OUTPUT_DIRECTORY/README.txt"
echo "Fixtures FFmpeg generados en $OUTPUT_DIRECTORY"
