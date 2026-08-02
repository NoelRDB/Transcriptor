#!/usr/bin/env bash
set -euo pipefail

if [[ $# -ne 2 ]]; then
  echo "Uso: $0 OUTPUT_DIRECTORY VERSION" >&2
  exit 2
fi

OUTPUT_DIRECTORY="$1"
VERSION="$2"
FFMPEG_REPOSITORY="https://github.com/FFmpeg/FFmpeg.git"
FFMPEG_COMMIT="0869e710e6876792fbcebccb536ad620d8e65b97"
SOURCE_ASSET_NAME="Transcriptor-${VERSION}-FFmpeg-corresponding-source.tar.gz"
RUNTIME_ASSET_NAME="ffmpeg-runtime-windows-x64.zip"
SCRIPT_PATH="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/$(basename "${BASH_SOURCE[0]}")"

if [[ ! "$VERSION" =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]]; then
  echo "La versión debe usar el formato X.Y.Z." >&2
  exit 2
fi
for command_name in dpkg-query git make nasm readlink tar gzip zip sha256sum \
  x86_64-w64-mingw32-gcc x86_64-w64-mingw32-objdump; do
  if ! command -v "$command_name" >/dev/null 2>&1; then
    echo "Falta la herramienta de build: $command_name" >&2
    exit 1
  fi
done

mkdir -p "$OUTPUT_DIRECTORY"
OUTPUT_DIRECTORY="$(cd "$OUTPUT_DIRECTORY" && pwd)"
if [[ "$OUTPUT_DIRECTORY" == "/" || "$OUTPUT_DIRECTORY" == "$HOME" ]]; then
  echo "La salida no puede ser una carpeta amplia del sistema." >&2
  exit 1
fi
WORK_ROOT="$(mktemp -d "$OUTPUT_DIRECTORY/ffmpeg-build.XXXXXXXX")"
cleanup() {
  if [[ -n "${WORK_ROOT:-}" && -d "$WORK_ROOT" &&
        "$WORK_ROOT" == "$OUTPUT_DIRECTORY"/ffmpeg-build.* ]]; then
    rm -rf -- "$WORK_ROOT"
  fi
}
trap cleanup EXIT

SOURCE_CHECKOUT="$WORK_ROOT/source"
BUILD_DIRECTORY="$WORK_ROOT/build"
RUNTIME_DIRECTORY="$WORK_ROOT/runtime"
CORRESPONDING_PARENT="$WORK_ROOT/corresponding"
CORRESPONDING_ROOT_NAME="Transcriptor-${VERSION}-FFmpeg-corresponding-source"
CORRESPONDING_ROOT="$CORRESPONDING_PARENT/$CORRESPONDING_ROOT_NAME"
SOURCE_TREE_NAME="ffmpeg-$FFMPEG_COMMIT"
SOURCE_TREE="$CORRESPONDING_ROOT/$SOURCE_TREE_NAME"
SOURCE_ASSET="$WORK_ROOT/$SOURCE_ASSET_NAME"
RUNTIME_ASSET="$WORK_ROOT/$RUNTIME_ASSET_NAME"
GCC_RUNTIME_LICENSE_NAME="GCC-RUNTIME-LICENSES.txt"
MINGW_RUNTIME_LICENSE_NAME="MINGW-W64-LICENSES.txt"
TOOLCHAIN_PROVENANCE_NAME="TOOLCHAIN-PROVENANCE.txt"

package_for_file() {
  local requested_path="$1"
  local resolved_path
  resolved_path="$(readlink -f "$requested_path")"
  if [[ ! -f "$resolved_path" ]]; then
    echo "No existe el archivo del toolchain: $requested_path" >&2
    exit 1
  fi
  local owning_package
  owning_package="$(
    dpkg-query -S "$resolved_path" 2>/dev/null |
      sed -n '1{s/: .*//p;}'
  )"
  if [[ -z "$owning_package" ]]; then
    echo "No se pudo atribuir a un paquete: $resolved_path" >&2
    exit 1
  fi
  printf '%s\n' "$owning_package"
}

copyright_for_package() {
  local package_name="$1"
  local copyright_path
  copyright_path="$(
    dpkg-query -L "$package_name" |
      grep -E '^/usr/share/doc/[^/]+/copyright$' |
      head -n 1
  )"
  if [[ -z "$copyright_path" || ! -f "$copyright_path" ]]; then
    echo "No se encontró el copyright de $package_name." >&2
    exit 1
  fi
  readlink -f "$copyright_path"
}

LIBGCC_ARCHIVE="$(x86_64-w64-mingw32-gcc -print-libgcc-file-name)"
MINGW_CRT_ARCHIVE="$(x86_64-w64-mingw32-gcc -print-file-name=libmingw32.a)"
GCC_RUNTIME_PACKAGE="$(package_for_file "$LIBGCC_ARCHIVE")"
MINGW_RUNTIME_PACKAGE="$(package_for_file "$MINGW_CRT_ARCHIVE")"
GCC_RUNTIME_PACKAGE_VERSION="$(
  dpkg-query -W -f='${Package}=${Version}' "$GCC_RUNTIME_PACKAGE"
)"
MINGW_RUNTIME_PACKAGE_VERSION="$(
  dpkg-query -W -f='${Package}=${Version}' "$MINGW_RUNTIME_PACKAGE"
)"
GCC_RUNTIME_COPYRIGHT="$(copyright_for_package "$GCC_RUNTIME_PACKAGE")"
MINGW_RUNTIME_COPYRIGHT="$(copyright_for_package "$MINGW_RUNTIME_PACKAGE")"
if ! grep -qi 'GCC Runtime Library Exception' "$GCC_RUNTIME_COPYRIGHT"; then
  echo "El aviso de GCC no conserva la Runtime Library Exception." >&2
  exit 1
fi
if ! grep -Eqi 'Zope Public License|ZPL-2|public domain' \
  "$MINGW_RUNTIME_COPYRIGHT"; then
  echo "El aviso MinGW-w64 no declara sus términos CRT aplicables." >&2
  exit 1
fi
GCC_RUNTIME_LICENSE_SHA256="$(
  sha256sum "$GCC_RUNTIME_COPYRIGHT" | awk '{print $1}'
)"
MINGW_RUNTIME_LICENSE_SHA256="$(
  sha256sum "$MINGW_RUNTIME_COPYRIGHT" | awk '{print $1}'
)"
TOOLCHAIN_COMPILER_VERSION="$(
  x86_64-w64-mingw32-gcc -dumpfullversion -dumpversion
)"

git init -q "$SOURCE_CHECKOUT"
git -C "$SOURCE_CHECKOUT" remote add origin "$FFMPEG_REPOSITORY"
git -C "$SOURCE_CHECKOUT" -c protocol.version=2 fetch --depth 1 origin "$FFMPEG_COMMIT"
git -C "$SOURCE_CHECKOUT" checkout -q --detach FETCH_HEAD
ACTUAL_COMMIT="$(git -C "$SOURCE_CHECKOUT" rev-parse HEAD)"
if [[ "$ACTUAL_COMMIT" != "$FFMPEG_COMMIT" ]]; then
  echo "El checkout de FFmpeg no coincide con el commit fijado." >&2
  exit 1
fi
SOURCE_DATE_EPOCH="$(git -C "$SOURCE_CHECKOUT" show -s --format=%ct "$FFMPEG_COMMIT")"
export SOURCE_DATE_EPOCH TZ=UTC ZERO_AR_DATE=1

CONFIGURE_ARGUMENTS=(
  "--target-os=mingw32"
  "--arch=x86_64"
  "--cross-prefix=x86_64-w64-mingw32-"
  "--enable-cross-compile"
  "--disable-autodetect"
  "--disable-network"
  "--disable-doc"
  "--disable-debug"
  "--disable-ffplay"
  "--disable-sdl2"
  "--disable-devices"
  "--disable-iconv"
  "--disable-zlib"
  "--disable-bzlib"
  "--disable-lzma"
  "--disable-gpl"
  "--disable-nonfree"
  "--disable-libx264"
  "--disable-libx265"
  "--enable-version3"
  "--enable-static"
  "--disable-shared"
  "--enable-w32threads"
  "--disable-pthreads"
  "--disable-encoders"
  "--enable-encoder=pcm_s16le,aac,mpeg4"
  "--disable-muxers"
  "--enable-muxer=s16le,wav,mp4,mov"
  "--enable-filter=trim,atrim,setpts,asetpts,concat,aresample,scale,format,aformat"
  "--extra-version=transcriptor"
  "--extra-ldflags=-Wl,--no-insert-timestamp"
)
CONFIGURATION_TEXT="./configure ${CONFIGURE_ARGUMENTS[*]}"

mkdir -p "$BUILD_DIRECTORY"
pushd "$BUILD_DIRECTORY" >/dev/null
"$SOURCE_CHECKOUT/configure" "${CONFIGURE_ARGUMENTS[@]}"
if ! grep -q '^#define CONFIG_GPL 0$' config.h ||
   ! grep -q '^#define CONFIG_NONFREE 0$' config.h ||
   ! grep -q '^#define CONFIG_VERSION3 1$' config.h; then
  echo "La configuración de FFmpeg no conserva el perfil LGPL v3." >&2
  exit 1
fi
for required_component in \
  CONFIG_PCM_S16LE_ENCODER CONFIG_AAC_ENCODER CONFIG_MPEG4_ENCODER \
  CONFIG_S16LE_MUXER CONFIG_WAV_MUXER CONFIG_MP4_MUXER CONFIG_MOV_MUXER \
  CONFIG_TRIM_FILTER CONFIG_ATRIM_FILTER CONFIG_SETPTS_FILTER \
  CONFIG_ASETPTS_FILTER CONFIG_CONCAT_FILTER CONFIG_ARESAMPLE_FILTER \
  CONFIG_SCALE_FILTER CONFIG_FORMAT_FILTER CONFIG_AFORMAT_FILTER; do
  if ! grep -q "^#define $required_component 1$" config.h config_components.h; then
    echo "Falta el componente FFmpeg requerido: $required_component" >&2
    exit 1
  fi
done
for required_library in CONFIG_SWRESAMPLE CONFIG_SWSCALE; do
  if ! grep -q "^#define $required_library 1$" config.h config_components.h; then
    echo "Falta la biblioteca FFmpeg requerida: $required_library" >&2
    exit 1
  fi
done
JOBS="${FFMPEG_BUILD_JOBS:-$(nproc)}"
if [[ ! "$JOBS" =~ ^[1-9][0-9]*$ ]]; then
  echo "FFMPEG_BUILD_JOBS debe ser un entero positivo." >&2
  exit 2
fi
make -j"$JOBS" ffmpeg ffprobe
popd >/dev/null

for executable_name in ffmpeg.exe ffprobe.exe; do
  if [[ ! -s "$BUILD_DIRECTORY/$executable_name" ]]; then
    echo "No se generó $executable_name." >&2
    exit 1
  fi
done
if [[ ! -s "$SOURCE_CHECKOUT/COPYING.LGPLv3" ]]; then
  echo "La fuente fijada no contiene COPYING.LGPLv3." >&2
  exit 1
fi

ALLOWED_SYSTEM_DLLS=(
  advapi32.dll avicap32.dll bcrypt.dll d3d11.dll dxgi.dll dxva2.dll
  gdi32.dll kernel32.dll mf.dll mfplat.dll mfreadwrite.dll msvcrt.dll
  ntdll.dll ole32.dll oleaut32.dll propsys.dll psapi.dll secur32.dll
  shell32.dll shlwapi.dll ucrtbase.dll user32.dll version.dll vfw32.dll
  winmm.dll ws2_32.dll
)
is_allowed_system_dll() {
  local candidate="${1,,}"
  if [[ "$candidate" == api-ms-win-*.dll || "$candidate" == ext-ms-win-*.dll ]]; then
    return 0
  fi
  local allowed
  for allowed in "${ALLOWED_SYSTEM_DLLS[@]}"; do
    if [[ "$candidate" == "$allowed" ]]; then
      return 0
    fi
  done
  return 1
}
collect_imports() {
  x86_64-w64-mingw32-objdump -p "$1" |
    sed -n 's/^[[:space:]]*DLL Name:[[:space:]]*//p' |
    sort -fu
}
verify_imports() {
  local executable_path="$1"
  local import_name
  local found=0
  while IFS= read -r import_name; do
    [[ -z "$import_name" ]] && continue
    found=1
    if ! is_allowed_system_dll "$import_name"; then
      echo "$(basename "$executable_path") enlaza una DLL no permitida: $import_name" >&2
      exit 1
    fi
  done < <(collect_imports "$executable_path")
  if [[ "$found" -ne 1 ]]; then
    echo "No se pudieron auditar las importaciones de $(basename "$executable_path")." >&2
    exit 1
  fi
}
verify_imports "$BUILD_DIRECTORY/ffmpeg.exe"
verify_imports "$BUILD_DIRECTORY/ffprobe.exe"
FFMPEG_IMPORTS="$(collect_imports "$BUILD_DIRECTORY/ffmpeg.exe" | paste -sd, -)"
FFPROBE_IMPORTS="$(collect_imports "$BUILD_DIRECTORY/ffprobe.exe" | paste -sd, -)"

# El archivo de corresponding source incluye el árbol exacto y el script que
# controla la compilación. Así no depende de que el repositorio siga accesible.
mkdir -p "$SOURCE_TREE"
git -C "$SOURCE_CHECKOUT" archive "$FFMPEG_COMMIT" |
  tar -xf - -C "$SOURCE_TREE"
cp "$SCRIPT_PATH" "$CORRESPONDING_ROOT/build-ffmpeg-windows.sh"
cp "$GCC_RUNTIME_COPYRIGHT" \
  "$CORRESPONDING_ROOT/$GCC_RUNTIME_LICENSE_NAME"
cp "$MINGW_RUNTIME_COPYRIGHT" \
  "$CORRESPONDING_ROOT/$MINGW_RUNTIME_LICENSE_NAME"
{
  echo "Target compiler: x86_64-w64-mingw32-gcc"
  echo "Target compiler version: $TOOLCHAIN_COMPILER_VERSION"
  echo "GCC runtime package: $GCC_RUNTIME_PACKAGE_VERSION"
  echo "GCC runtime archive: $LIBGCC_ARCHIVE"
  echo "GCC runtime license: $GCC_RUNTIME_LICENSE_NAME"
  echo "GCC runtime license SHA-256: $GCC_RUNTIME_LICENSE_SHA256"
  echo "MinGW-w64 runtime package: $MINGW_RUNTIME_PACKAGE_VERSION"
  echo "MinGW-w64 CRT archive: $MINGW_CRT_ARCHIVE"
  echo "MinGW-w64 licenses: $MINGW_RUNTIME_LICENSE_NAME"
  echo "MinGW-w64 licenses SHA-256: $MINGW_RUNTIME_LICENSE_SHA256"
} > "$CORRESPONDING_ROOT/$TOOLCHAIN_PROVENANCE_NAME"
{
  echo "Transcriptor $VERSION - corresponding source de FFmpeg"
  echo
  echo "Repositorio original: $FFMPEG_REPOSITORY"
  echo "Commit exacto: $FFMPEG_COMMIT"
  echo "Objetivo: Windows x86_64 mediante MinGW-w64"
  echo
  echo "Dependencias en Ubuntu 24.04:"
  echo "  sudo apt-get update"
  echo "  sudo apt-get install --no-install-recommends git mingw-w64 make nasm pkg-config zip"
  echo
  echo "Desde esta carpeta:"
  echo "  mkdir build && cd build"
  echo "  ../$SOURCE_TREE_NAME/configure ${CONFIGURE_ARGUMENTS[*]}"
  echo "  make -j\$(nproc) ffmpeg ffprobe"
  echo
  echo "El script build-ffmpeg-windows.sh conserva también la descarga fijada,"
  echo "la auditoría de DLL importadas y el empaquetado reproducible."
} > "$CORRESPONDING_ROOT/BUILD-INSTRUCTIONS.txt"
find "$CORRESPONDING_ROOT" -exec touch -d "@$SOURCE_DATE_EPOCH" {} +
tar --sort=name --format=gnu --mtime="@$SOURCE_DATE_EPOCH" \
  --owner=0 --group=0 --numeric-owner \
  -C "$CORRESPONDING_PARENT" -cf - "$CORRESPONDING_ROOT_NAME" |
  gzip -n -9 > "$SOURCE_ASSET"
SOURCE_ASSET_CONTENTS="$(tar -tzf "$SOURCE_ASSET")"
for required_source_member in \
  "$CORRESPONDING_ROOT_NAME/BUILD-INSTRUCTIONS.txt" \
  "$CORRESPONDING_ROOT_NAME/build-ffmpeg-windows.sh" \
  "$CORRESPONDING_ROOT_NAME/$GCC_RUNTIME_LICENSE_NAME" \
  "$CORRESPONDING_ROOT_NAME/$MINGW_RUNTIME_LICENSE_NAME" \
  "$CORRESPONDING_ROOT_NAME/$TOOLCHAIN_PROVENANCE_NAME" \
  "$CORRESPONDING_ROOT_NAME/$SOURCE_TREE_NAME/configure" \
  "$CORRESPONDING_ROOT_NAME/$SOURCE_TREE_NAME/COPYING.LGPLv3"; do
  if ! grep -Fxq "$required_source_member" <<<"$SOURCE_ASSET_CONTENTS"; then
    echo "El corresponding source no contiene $required_source_member" >&2
    exit 1
  fi
done
if grep -Eq '(^|/)\.git(/|$)' <<<"$SOURCE_ASSET_CONTENTS"; then
  echo "El corresponding source contiene metadatos Git inesperados." >&2
  exit 1
fi
SOURCE_ASSET_SHA256="$(sha256sum "$SOURCE_ASSET" | awk '{print $1}')"

mkdir -p "$RUNTIME_DIRECTORY"
cp "$BUILD_DIRECTORY/ffmpeg.exe" "$RUNTIME_DIRECTORY/ffmpeg.exe"
cp "$BUILD_DIRECTORY/ffprobe.exe" "$RUNTIME_DIRECTORY/ffprobe.exe"
cp "$SOURCE_CHECKOUT/COPYING.LGPLv3" "$RUNTIME_DIRECTORY/LICENSE.txt"
cp "$GCC_RUNTIME_COPYRIGHT" \
  "$RUNTIME_DIRECTORY/$GCC_RUNTIME_LICENSE_NAME"
cp "$MINGW_RUNTIME_COPYRIGHT" \
  "$RUNTIME_DIRECTORY/$MINGW_RUNTIME_LICENSE_NAME"
{
  echo "Component: FFmpeg"
  echo "Source repository: $FFMPEG_REPOSITORY"
  echo "Source commit: $FFMPEG_COMMIT"
  echo "Corresponding source asset: $SOURCE_ASSET_NAME"
  echo "Corresponding source SHA-256: $SOURCE_ASSET_SHA256"
  echo "Build script: scripts/build-ffmpeg-windows.sh"
  echo "Target: x86_64-w64-mingw32"
  echo "License profile: GNU LGPL v3 or later"
  echo "Configuration: $CONFIGURATION_TEXT"
  echo "Imported system DLLs (ffmpeg.exe): $FFMPEG_IMPORTS"
  echo "Imported system DLLs (ffprobe.exe): $FFPROBE_IMPORTS"
  echo "Target compiler: x86_64-w64-mingw32-gcc"
  echo "Target compiler version: $TOOLCHAIN_COMPILER_VERSION"
  echo "GCC runtime package: $GCC_RUNTIME_PACKAGE_VERSION"
  echo "GCC runtime license: $GCC_RUNTIME_LICENSE_NAME"
  echo "GCC runtime license SHA-256: $GCC_RUNTIME_LICENSE_SHA256"
  echo "MinGW-w64 runtime package: $MINGW_RUNTIME_PACKAGE_VERSION"
  echo "MinGW-w64 licenses: $MINGW_RUNTIME_LICENSE_NAME"
  echo "MinGW-w64 licenses SHA-256: $MINGW_RUNTIME_LICENSE_SHA256"
} > "$RUNTIME_DIRECTORY/BUILD-SOURCE.txt"
find "$RUNTIME_DIRECTORY" -type f -exec touch -d "@$SOURCE_DATE_EPOCH" {} +
pushd "$RUNTIME_DIRECTORY" >/dev/null
zip -X -9 -q "$RUNTIME_ASSET" \
  ffmpeg.exe ffprobe.exe LICENSE.txt BUILD-SOURCE.txt \
  "$GCC_RUNTIME_LICENSE_NAME" "$MINGW_RUNTIME_LICENSE_NAME"
popd >/dev/null

mv -f -- "$SOURCE_ASSET" "$OUTPUT_DIRECTORY/$SOURCE_ASSET_NAME"
mv -f -- "$RUNTIME_ASSET" "$OUTPUT_DIRECTORY/$RUNTIME_ASSET_NAME"
echo "FFmpeg Windows listo: $OUTPUT_DIRECTORY/$RUNTIME_ASSET_NAME"
echo "Corresponding source listo: $OUTPUT_DIRECTORY/$SOURCE_ASSET_NAME"
