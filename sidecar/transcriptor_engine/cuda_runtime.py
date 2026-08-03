from __future__ import annotations

import ctypes
import hashlib
import json
import os
import platform
import shutil
import sys
import tempfile
import threading
import uuid
import zipfile
from collections.abc import Callable, Iterable
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, BinaryIO
from urllib.request import Request, urlopen

from .paths import preferred_app_data_dir

Emit = Callable[[dict[str, Any]], None]
Cancelled = Callable[[], bool]

CUDA_RUNTIME_ID = "cuda-runtime"
NVIDIA_RUNTIME_FILES = (
    "cublas64_12.dll",
    "cublasLt64_12.dll",
    "cudnn64_9.dll",
    "cudnn_adv64_9.dll",
    "cudnn_cnn64_9.dll",
    "cudnn_engines_precompiled64_9.dll",
    "cudnn_engines_runtime_compiled64_9.dll",
    "cudnn_engines_tensor_ir64_9.dll",
    "cudnn_ext64_9.dll",
    "cudnn_graph64_9.dll",
    "cudnn_heuristic64_9.dll",
    "cudnn_ops64_9.dll",
    "nvrtc-builtins64_129.dll",
    "nvrtc64_120_0.alt.dll",
    "nvrtc64_120_0.dll",
)
CTRANSLATE2_GPU_FILES = (
    "ctranslate2.dll",
    "libiomp5md.dll",
)
CUDA_RUNTIME_FILES = NVIDIA_RUNTIME_FILES + CTRANSLATE2_GPU_FILES
CUDA_LICENSE_FILES = (
    "NVIDIA-cuBLAS-License.txt",
    "NVIDIA-cuDNN-License.txt",
    "NVIDIA-CUDA-NVRTC-License.txt",
    "CTranslate2-MIT.txt",
    "Intel-Simplified-Software-License.pdf",
    "NVIDIA-CUDA-Runtime-License.txt",
    "Intel-OpenMP-EULA.txt",
    "Intel-OpenMP-Third-Party-Programs.txt",
    "oneDNN-Apache-2.0.txt",
    "oneDNN-Third-Party-Programs.txt",
)
# The three wheels occupy about 1.27 GiB and the allowlisted runtime expands to
# about 1.94 GiB. During an atomic upgrade, both the previous and staged runtime
# can coexist. Six GiB leaves room for the active wheel and filesystem overhead.
CUDA_INSTALL_REQUIRED_FREE_BYTES = 6 * 1024**3
_DOWNLOAD_CHUNK_BYTES = 1024**2
_MAX_RUNTIME_LIBRARY_BYTES = 2 * 1024**3
_MANIFEST_NAME = "runtime-manifest.json"
_MANIFEST_SCHEMA_VERSION = 2
_LOAD_LIBRARY_SEARCH_DLL_LOAD_DIR = 0x00000100
_LOAD_LIBRARY_SEARCH_DEFAULT_DIRS = 0x00001000

_PRELOAD_ORDER = (
    "libiomp5md.dll",
    "nvrtc-builtins64_129.dll",
    "nvrtc64_120_0.alt.dll",
    "nvrtc64_120_0.dll",
    "cublasLt64_12.dll",
    "cublas64_12.dll",
    "cudnn_ops64_9.dll",
    "cudnn_graph64_9.dll",
    "cudnn_heuristic64_9.dll",
    "cudnn_engines_precompiled64_9.dll",
    "cudnn_engines_runtime_compiled64_9.dll",
    "cudnn_engines_tensor_ir64_9.dll",
    "cudnn_adv64_9.dll",
    "cudnn_cnn64_9.dll",
    "cudnn_ext64_9.dll",
    "cudnn64_9.dll",
    "ctranslate2.dll",
)
_PRELOAD_LOCK = threading.Lock()
_PRELOADED_LIBRARY_HANDLES: list[Any] = []
_PRELOADED_DIRECTORY_HANDLES: list[Any] = []
_GPU_BACKEND_PRELOADED = False
_GPU_BACKEND_ACTIVATION: dict[str, Any] | None = None


@dataclass(frozen=True)
class RuntimePackage:
    name: str
    version: str
    url: str
    sha256: str
    size: int
    files: tuple[str, ...]
    license_path: str | None
    license_filename: str | None


@dataclass(frozen=True)
class RuntimeLegalDocument:
    name: str
    version: str
    url: str
    sha256: str
    size: int
    filename: str
    media_type: str
    archive_path: str | None = None
    content_sha256: str | None = None
    content_size: int | None = None
    encoding: str = "utf-8"


# These immutable Windows x64 artifacts are pinned by sidecar/uv.lock. Updating a
# version requires updating its URL, byte size and SHA-256 together.
CUDA_PACKAGES = (
    RuntimePackage(
        name="nvidia-cublas-cu12",
        version="12.9.2.10",
        url=(
            "https://files.pythonhosted.org/packages/20/e2/"
            "fc9a0e985249d873150276d5afb02e39a66817fedbf1a385724393e505ed/"
            "nvidia_cublas_cu12-12.9.2.10-py3-none-win_amd64.whl"
        ),
        sha256="623f43027d40d44ceadf0043f002bd25cf353e8f13ce90b9a87057019f560661",
        size=553_162_896,
        files=("cublas64_12.dll", "cublasLt64_12.dll"),
        license_path=(
            "nvidia_cublas_cu12-12.9.2.10.dist-info/licenses/License.txt"
        ),
        license_filename="NVIDIA-cuBLAS-License.txt",
    ),
    RuntimePackage(
        name="nvidia-cuda-nvrtc-cu12",
        version="12.9.86",
        url=(
            "https://files.pythonhosted.org/packages/52/de/"
            "823919be3b9d0ccbf1f784035423c5f18f4267fb0123558d58b813c6ec86/"
            "nvidia_cuda_nvrtc_cu12-12.9.86-py3-none-win_amd64.whl"
        ),
        sha256="72972ebdcf504d69462d3bcd67e7b81edd25d0fb85a2c46d3ea3517666636349",
        size=76_408_187,
        files=(
            "nvrtc-builtins64_129.dll",
            "nvrtc64_120_0.alt.dll",
            "nvrtc64_120_0.dll",
        ),
        license_path=(
            "nvidia_cuda_nvrtc_cu12-12.9.86.dist-info/licenses/License.txt"
        ),
        license_filename="NVIDIA-CUDA-NVRTC-License.txt",
    ),
    RuntimePackage(
        name="nvidia-cudnn-cu12",
        version="9.25.0.15",
        url=(
            "https://files.pythonhosted.org/packages/cf/9e/"
            "f5dd69a26620c490f082af690e706cb2c94e34881a63d8e9c4a1b5eb83cd/"
            "nvidia_cudnn_cu12-9.25.0.15-py3-none-win_amd64.whl"
        ),
        sha256="7987acb3cc5b793151e64c05a12a3625f5a8d4cfabe87eea3a65f0676ef2da67",
        size=732_268_748,
        files=(
            "cudnn64_9.dll",
            "cudnn_adv64_9.dll",
            "cudnn_cnn64_9.dll",
            "cudnn_engines_precompiled64_9.dll",
            "cudnn_engines_runtime_compiled64_9.dll",
            "cudnn_engines_tensor_ir64_9.dll",
            "cudnn_ext64_9.dll",
            "cudnn_graph64_9.dll",
            "cudnn_heuristic64_9.dll",
            "cudnn_ops64_9.dll",
        ),
        license_path=(
            "nvidia_cudnn_cu12-9.25.0.15.dist-info/licenses/License.txt"
        ),
        license_filename="NVIDIA-cuDNN-License.txt",
    ),
    RuntimePackage(
        name="ctranslate2",
        version="4.8.1",
        url=(
            "https://files.pythonhosted.org/packages/c0/82/"
            "0a5f7f2b03b4e10aacb3146715724e1b96bb993cc7d199be28c9825aa120/"
            "ctranslate2-4.8.1-cp312-cp312-win_amd64.whl"
        ),
        sha256="49f96e861b57301f0b76a082109bde2cac8204a6b4fedc870883008271e82251",
        size=19_220_789,
        files=CTRANSLATE2_GPU_FILES,
        # The upstream wheel does not contain license files. Exact, pinned
        # upstream legal documents are downloaded separately below.
        license_path=None,
        license_filename=None,
    ),
)

CUDA_LEGAL_DOCUMENTS = (
    RuntimeLegalDocument(
        name="CTranslate2 MIT license",
        version="4.8.1",
        url="https://raw.githubusercontent.com/OpenNMT/CTranslate2/v4.8.1/LICENSE",
        sha256="54aa79d9fe3c09e67a16dcd95b9e88676405a6ec174efda31036983cf7672ecb",
        size=1_115,
        filename="CTranslate2-MIT.txt",
        media_type="text/plain",
    ),
    RuntimeLegalDocument(
        name="Intel Simplified Software License",
        version="October 2022",
        url="https://cdrdv2.intel.com/v1/dl/getContent/749362",
        sha256="cb199f4ed41d96df26f653bf2ac6d5a5c81be739334ca93df027bea74bc963a3",
        size=70_926,
        filename="Intel-Simplified-Software-License.pdf",
        media_type="application/pdf",
    ),
    RuntimeLegalDocument(
        name="NVIDIA CUDA Runtime license",
        version="12.8.90",
        url=(
            "https://files.pythonhosted.org/packages/30/a5/"
            "a515b7600ad361ea14bfa13fb4d6687abf500adc270f19e89849c0590492/"
            "nvidia_cuda_runtime_cu12-12.8.90-py3-none-win_amd64.whl"
        ),
        sha256="c0c6027f01505bfed6c3b21ec546f69c687689aad5f1a377554bc6ca4aa993a8",
        size=944_318,
        filename="NVIDIA-CUDA-Runtime-License.txt",
        media_type="text/plain",
        archive_path=(
            "nvidia_cuda_runtime_cu12-12.8.90.dist-info/License.txt"
        ),
        content_sha256=(
            "ad6f5853fba0ca0d159d0f58d49ae49830c2f8c93f7a92648b9ce90adb4c6ccd"
        ),
        content_size=59_262,
    ),
    RuntimeLegalDocument(
        name="Intel OpenMP EULA",
        version="2025.3.0",
        url=(
            "https://files.pythonhosted.org/packages/79/69/"
            "05addedd727061b61a85b4fd989754edb628b5be1cd5d161727f98cf4d86/"
            "intel_openmp-2025.3.0-py2.py3-none-win_amd64.whl"
        ),
        sha256="8ff899d01a41b92ffe0e618b221ea633127d16df726086082d381c431c31339d",
        size=32_083_814,
        filename="Intel-OpenMP-EULA.txt",
        media_type="text/plain",
        archive_path="intel_openmp-2025.3.0.dist-info/LICENSE.txt",
        content_sha256=(
            "febfb69a5b058f55892dc7f341108a9ca29d50e9fe85723a57eebbb826436958"
        ),
        content_size=25_224,
        # The pinned official Intel wheel encodes LICENSE.txt as Windows-1252
        # (it contains typographic byte 0x96), not UTF-8.
        encoding="cp1252",
    ),
    RuntimeLegalDocument(
        name="Intel OpenMP third-party programs",
        version="2025.3.0",
        url=(
            "https://files.pythonhosted.org/packages/79/69/"
            "05addedd727061b61a85b4fd989754edb628b5be1cd5d161727f98cf4d86/"
            "intel_openmp-2025.3.0-py2.py3-none-win_amd64.whl"
        ),
        sha256="8ff899d01a41b92ffe0e618b221ea633127d16df726086082d381c431c31339d",
        size=32_083_814,
        filename="Intel-OpenMP-Third-Party-Programs.txt",
        media_type="text/plain",
        archive_path=(
            "intel_openmp-2025.3.0.data/data/share/doc/compiler/"
            "licensing/openmp/third-party-programs.txt"
        ),
        content_sha256=(
            "f8ce918fe7311ce279e68380a2e233f8a42b1cd3dda8f4c48d6de97a0255c1d7"
        ),
        content_size=31_578,
    ),
    RuntimeLegalDocument(
        name="oneDNN Apache 2.0 license",
        version="3.1.1",
        url=(
            "https://raw.githubusercontent.com/uxlfoundation/oneDNN/"
            "64f6bcbcbab628e96f33a62c3e975f8535a7bde4/LICENSE"
        ),
        sha256="dd12452e1ae11e3282271aa5895d8175296b83e936a027209f9399d26a407d0f",
        size=11_521,
        filename="oneDNN-Apache-2.0.txt",
        media_type="text/plain",
    ),
    RuntimeLegalDocument(
        name="oneDNN third-party programs",
        version="3.1.1",
        url=(
            "https://raw.githubusercontent.com/uxlfoundation/oneDNN/"
            "64f6bcbcbab628e96f33a62c3e975f8535a7bde4/THIRD-PARTY-PROGRAMS"
        ),
        sha256="9117585dfc6b5cd0fafc063312f28a86ec82eb97bf68316dcefcaAA7fc11428e",
        size=29_825,
        filename="oneDNN-Third-Party-Programs.txt",
        media_type="text/plain",
    ),
)


class CudaRuntimeError(RuntimeError):
    pass


class CudaRuntimeCancelled(CudaRuntimeError):
    pass


def managed_cuda_dir() -> Path:
    """Use TranscriptorData even when projects still live in a legacy data root."""
    return preferred_app_data_dir() / "runtime" / "cuda"


def cuda_library_groups() -> list[tuple[str, tuple[Path, ...]]]:
    """Return the only directory trusted as an optional GPU backend.

    Previous builds accepted DLLs from PATH, the executable directory and
    development site-packages. That makes the current working directory or an
    unrelated installation an authority over executable code. The optional
    backend is now accepted only from the private, hash-inventoried managed
    directory.
    """
    return [("managed", (managed_cuda_dir(),))]


def _find_cuda_runtime() -> tuple[str, tuple[Path, ...], dict[str, Path]]:
    source, directories = cuda_library_groups()[0]
    directory = directories[0]
    found = {
        filename: directory / filename
        for filename in CUDA_RUNTIME_FILES
        if _valid_runtime_file(directory / filename)
    }
    if (
        len(found) == len(CUDA_RUNTIME_FILES)
        and _managed_runtime_integrity(directory)
    ):
        return source, directories, found
    return "missing", (), {}


def cuda_library_directories() -> list[Path]:
    """Return only the complete, hash-verified managed runtime directory."""
    _source, directories, _found = _find_cuda_runtime()
    return list(directories)


def managed_cuda_runtime_present() -> bool:
    """Return a fast UI hint; activation still performs full SHA-256 verification."""
    target = managed_cuda_dir()
    try:
        manifest = json.loads((target / _MANIFEST_NAME).read_text(encoding="utf-8"))
        if manifest.get("schemaVersion") != _MANIFEST_SCHEMA_VERSION:
            return False
        records = manifest.get("files")
        if not isinstance(records, list):
            return False
        expected_names = set(CUDA_RUNTIME_FILES) | set(CUDA_LICENSE_FILES)
        by_name = {
            str(record.get("name")): record
            for record in records
            if isinstance(record, dict) and isinstance(record.get("name"), str)
        }
        if set(by_name) != expected_names or len(by_name) != len(records):
            return False
        if manifest.get("inventorySha256") != _inventory_digest(
            sorted(records, key=lambda record: str(record.get("name", "")))
        ):
            return False
        for name, record in by_name.items():
            path = target / name
            if not path.is_file() or path.stat().st_size != record.get("sizeBytes"):
                return False
        return all(_valid_runtime_file(target / name) for name in CUDA_RUNTIME_FILES)
    except (OSError, UnicodeError, ValueError, TypeError, json.JSONDecodeError):
        return False


def get_cuda_runtime_status() -> dict[str, Any]:
    target = managed_cuda_dir()
    package_bytes = sum(package.size for package in CUDA_PACKAGES) + sum(
        size
        for _url, _sha256, size in _unique_legal_sources(CUDA_LEGAL_DOCUMENTS)
    )
    required_free_bytes = CUDA_INSTALL_REQUIRED_FREE_BYTES
    try:
        free_bytes = shutil.disk_usage(target.parent.parent).free
    except OSError:
        free_bytes = 0

    source, _directories, found = _find_cuda_runtime()
    ready = (
        source == "managed"
        and all(filename in found for filename in CUDA_RUNTIME_FILES)
    )
    installed = _directory_nonempty(target)
    restart_required = bool(
        ready and not _GPU_BACKEND_PRELOADED and _ctranslate2_already_loaded()
    )
    expected_names = CUDA_RUNTIME_FILES + CUDA_LICENSE_FILES
    return {
        "id": CUDA_RUNTIME_ID,
        "supported": _runtime_supported(),
        "installed": installed,
        "ready": ready,
        "source": source,
        "root": str(target),
        "downloadBytes": package_bytes,
        "requiredFreeBytes": required_free_bytes,
        "freeBytes": free_bytes,
        "canInstall": _runtime_supported() and free_bytes >= required_free_bytes,
        "missingFiles": [
            filename
            for filename in expected_names
            if not (target / filename).is_file()
        ],
        "restartRequired": restart_required,
        "activationState": (
            "restart-required"
            if restart_required
            else "ready"
            if ready
            else "corrupt"
            if installed
            else "not-installed"
        ),
        "backend": "gpu-optional-proprietary",
        "trust": "sha256-verified-runtime-download",
        "signPathCovered": False,
        "cpuBackend": {
            "backend": "cpu-bundled-oss",
            "openSource": True,
            "signPathCovered": True,
        },
        "packages": [
            {
                "name": package.name,
                "version": package.version,
                "sizeBytes": package.size,
                "sha256": package.sha256,
            }
            for package in CUDA_PACKAGES
        ],
        "legalDocuments": [
            {
                "name": document.name,
                "version": document.version,
                "filename": document.filename,
                "sizeBytes": _document_content_size(document),
                "sha256": _document_content_sha256(document),
                "url": document.url,
                "sourceSizeBytes": document.size,
                "sourceSha256": document.sha256,
            }
            for document in CUDA_LEGAL_DOCUMENTS
        ],
    }


def install_cuda_runtime(
    emit: Emit,
    cancelled: Cancelled,
    *,
    packages: Iterable[RuntimePackage] = CUDA_PACKAGES,
    legal_documents: Iterable[RuntimeLegalDocument] = CUDA_LEGAL_DOCUMENTS,
    opener: Callable[[str], BinaryIO] | None = None,
) -> dict[str, Any]:
    if not _runtime_supported():
        raise CudaRuntimeError(
            "La aceleración CUDA local sólo está disponible en Windows de 64 bits."
        )
    package_list = tuple(packages)
    legal_document_list = tuple(legal_documents)
    _validate_package_definition(package_list, legal_document_list)
    target = managed_cuda_dir()
    _prepare_private_runtime_parent(target)
    total_bytes = sum(package.size for package in package_list) + sum(
        size
        for _url, _sha256, size in _unique_legal_sources(legal_document_list)
    )
    required_free = CUDA_INSTALL_REQUIRED_FREE_BYTES
    free_bytes = shutil.disk_usage(target.parent).free
    if free_bytes < required_free:
        raise OSError(
            "No hay espacio suficiente para preparar la aceleración NVIDIA. "
            f"Se necesitan {required_free / 1024**3:.1f} GB libres y hay "
            f"{free_bytes / 1024**3:.1f} GB."
        )

    temporary_root = Path(
        tempfile.mkdtemp(prefix=".cuda-install-", dir=str(target.parent))
    )
    staging = target.parent / f".cuda-staging-{uuid.uuid4().hex}"
    backup = target.parent / f".cuda-backup-{uuid.uuid4().hex}"
    downloaded_bytes = 0
    extracted_files: list[dict[str, Any]] = []
    open_download = opener or _open_download

    try:
        staging.mkdir(parents=False)
        emit(_progress("preparing", 0, downloaded_bytes, total_bytes, "Preparando la descarga segura…"))
        for package in package_list:
            _raise_if_cancelled(cancelled)
            wheel_path = temporary_root / f"{package.name}-{package.version}.whl"
            package_base = downloaded_bytes
            emit(
                _progress(
                    "downloading",
                    package_base / max(1, total_bytes) * 90,
                    downloaded_bytes,
                    total_bytes,
                    f"Descargando {package.name} {package.version}…",
                    package=package,
                )
            )
            downloaded_bytes = _download_verified_wheel(
                package,
                wheel_path,
                package_base,
                total_bytes,
                emit,
                cancelled,
                open_download,
            )
            emit(
                _progress(
                    "verifying",
                    downloaded_bytes / max(1, total_bytes) * 90,
                    downloaded_bytes,
                    total_bytes,
                    f"Integridad SHA-256 verificada para {package.name}.",
                    package=package,
                )
            )
            extracted_files.extend(
                _extract_runtime_files(package, wheel_path, staging, cancelled)
            )
            wheel_path.unlink(missing_ok=True)
            emit(
                _progress(
                    "extracting",
                    downloaded_bytes / max(1, total_bytes) * 90,
                    downloaded_bytes,
                    total_bytes,
                    f"Componentes de {package.name} extraídos.",
                    package=package,
                )
            )

        legal_source_cache: dict[tuple[str, str, int], Path] = {}
        for document_index, document in enumerate(legal_document_list):
            _raise_if_cancelled(cancelled)
            source_key = (document.url, document.sha256, document.size)
            source_path = legal_source_cache.get(source_key)
            if source_path is None:
                document_base = downloaded_bytes
                source_path = temporary_root / f"legal-source-{document_index}"
                emit(
                    _progress(
                        "downloading",
                        document_base / max(1, total_bytes) * 90,
                        downloaded_bytes,
                        total_bytes,
                        f"Descargando {document.name}…",
                        package=document,
                    )
                )
                downloaded_bytes = _download_verified_artifact(
                    document,
                    source_path,
                    document_base,
                    total_bytes,
                    emit,
                    cancelled,
                    open_download,
                )
                legal_source_cache[source_key] = source_path
            destination = staging / document.filename
            _install_legal_document(
                document,
                source_path,
                destination,
                cancelled,
            )
            _validate_legal_document(document, destination)
            extracted_files.append(
                {
                    "name": document.filename,
                    "sizeBytes": destination.stat().st_size,
                    "sha256": _document_content_sha256(document),
                    "package": document.name,
                    "kind": "license",
                    "sourceUrl": document.url,
                    "sourceSizeBytes": document.size,
                    "sourceSha256": document.sha256,
                    "mediaType": document.media_type,
                }
            )
            emit(
                _progress(
                    "verifying",
                    downloaded_bytes / max(1, total_bytes) * 90,
                    downloaded_bytes,
                    total_bytes,
                    f"Documento legal exacto verificado: {document.name}.",
                    package=document,
                )
            )

        _raise_if_cancelled(cancelled)
        missing = [
            filename for filename in CUDA_RUNTIME_FILES
            if not _valid_runtime_file(staging / filename)
        ]
        if missing:
            raise CudaRuntimeError(
                "El runtime descargado está incompleto: " + ", ".join(missing)
            )
        inventory = sorted(extracted_files, key=lambda record: str(record["name"]))
        inventory_sha256 = _inventory_digest(inventory)
        manifest = {
            "schemaVersion": _MANIFEST_SCHEMA_VERSION,
            "installedAt": datetime.now(UTC).isoformat(),
            "backend": {
                "id": "ctranslate2-gpu-optional",
                "kind": "proprietary-optional-runtime",
                "signPathCovered": False,
                "activation": "absolute-path-preload",
                "acl": "inherited-from-private-local-app-data",
            },
            "packages": [
                {
                    **asdict(package),
                    "files": list(package.files),
                }
                for package in package_list
            ],
            "legalDocuments": [asdict(document) for document in legal_document_list],
            "inventorySha256": inventory_sha256,
            "files": inventory,
        }
        (staging / _MANIFEST_NAME).write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        emit(
            _progress(
                "installing",
                98,
                total_bytes,
                total_bytes,
                "Activando el backend GPU opcional de forma atómica…",
            )
        )
        _atomic_activate(staging, target, backup)
        emit(
            _progress(
                "completed",
                100,
                total_bytes,
                total_bytes,
                "Backend NVIDIA verificado y preparado.",
            )
        )
        return get_cuda_runtime_status()
    except CudaRuntimeCancelled:
        raise
    except (OSError, ValueError, zipfile.BadZipFile) as error:
        raise CudaRuntimeError(
            "No se pudo preparar la aceleración NVIDIA. "
            "La descarga temporal se ha eliminado y puedes reintentarlo."
        ) from error
    finally:
        shutil.rmtree(temporary_root, ignore_errors=True)
        if staging.exists():
            shutil.rmtree(staging, ignore_errors=True)
        if backup.exists():
            if target.exists():
                shutil.rmtree(backup, ignore_errors=True)
            else:
                os.replace(backup, target)


def _download_verified_wheel(
    package: RuntimePackage,
    destination: Path,
    package_base: int,
    total_bytes: int,
    emit: Emit,
    cancelled: Cancelled,
    opener: Callable[[str], BinaryIO],
) -> int:
    return _download_verified_artifact(
        package,
        destination,
        package_base,
        total_bytes,
        emit,
        cancelled,
        opener,
    )


def _download_verified_artifact(
    artifact: RuntimePackage | RuntimeLegalDocument,
    destination: Path,
    artifact_base: int,
    total_bytes: int,
    emit: Emit,
    cancelled: Cancelled,
    opener: Callable[[str], BinaryIO],
) -> int:
    digest = hashlib.sha256()
    artifact_bytes = 0
    response = opener(artifact.url)
    try:
        with destination.open("wb") as output:
            while True:
                _raise_if_cancelled(cancelled)
                chunk = response.read(_DOWNLOAD_CHUNK_BYTES)
                if not chunk:
                    break
                output.write(chunk)
                digest.update(chunk)
                artifact_bytes += len(chunk)
                if artifact_bytes > artifact.size:
                    raise CudaRuntimeError(
                        f"{artifact.name} supera el tamaño fijado en el catálogo."
                    )
                downloaded = artifact_base + artifact_bytes
                emit(
                    _progress(
                        "downloading",
                        downloaded / max(1, total_bytes) * 90,
                        downloaded,
                        total_bytes,
                        f"Descargando {artifact.name}…",
                        package=artifact,
                    )
                )
    finally:
        close = getattr(response, "close", None)
        if callable(close):
            close()
    if artifact_bytes != artifact.size:
        raise CudaRuntimeError(
            f"{artifact.name} tiene {artifact_bytes} bytes; "
            f"se esperaban {artifact.size}."
        )
    if digest.hexdigest().lower() != artifact.sha256.lower():
        raise CudaRuntimeError(
            f"La suma SHA-256 de {artifact.name} no coincide."
        )
    return artifact_base + artifact_bytes


def _extract_runtime_files(
    package: RuntimePackage,
    wheel_path: Path,
    staging: Path,
    cancelled: Cancelled,
) -> list[dict[str, Any]]:
    extracted: list[dict[str, Any]] = []
    with zipfile.ZipFile(wheel_path) as wheel:
        members: dict[str, zipfile.ZipInfo] = {}
        for info in wheel.infolist():
            normalized = info.filename.replace("\\", "/")
            filename = normalized.rsplit("/", 1)[-1]
            if filename not in package.files:
                continue
            if filename in members:
                raise CudaRuntimeError(f"{package.name} contiene {filename} duplicado.")
            members[filename] = info
        missing = [filename for filename in package.files if filename not in members]
        if missing:
            raise CudaRuntimeError(
                f"{package.name} no contiene " + ", ".join(missing)
            )
        for filename in package.files:
            _raise_if_cancelled(cancelled)
            info = members[filename]
            if (
                info.file_size < 64 * 1024
                or info.file_size > _MAX_RUNTIME_LIBRARY_BYTES
            ):
                raise CudaRuntimeError(
                    f"{filename} tiene un tamaño inesperado dentro de {package.name}."
                )
            destination = staging / filename
            digest = hashlib.sha256()
            with wheel.open(info) as source, destination.open("xb") as output:
                while True:
                    _raise_if_cancelled(cancelled)
                    chunk = source.read(_DOWNLOAD_CHUNK_BYTES)
                    if not chunk:
                        break
                    output.write(chunk)
                    digest.update(chunk)
            if not _valid_runtime_file(destination):
                raise CudaRuntimeError(f"{filename} no es una biblioteca Windows válida.")
            extracted.append(
                {
                    "name": filename,
                    "sizeBytes": destination.stat().st_size,
                    "sha256": digest.hexdigest(),
                    "package": package.name,
                    "kind": "library",
                }
            )
        if package.license_path and package.license_filename:
            try:
                license_info = wheel.getinfo(package.license_path)
            except KeyError as error:
                raise CudaRuntimeError(
                    f"{package.name} no contiene su licencia exacta."
                ) from error
            if (
                license_info.is_dir()
                or license_info.file_size < 1024
                or license_info.file_size > 1024 * 1024
            ):
                raise CudaRuntimeError(
                    f"La licencia incluida en {package.name} "
                    "tiene un tamaño inesperado."
                )
            license_destination = staging / package.license_filename
            license_digest = hashlib.sha256()
            with (
                wheel.open(license_info) as source,
                license_destination.open("xb") as output,
            ):
                while True:
                    _raise_if_cancelled(cancelled)
                    chunk = source.read(_DOWNLOAD_CHUNK_BYTES)
                    if not chunk:
                        break
                    output.write(chunk)
                    license_digest.update(chunk)
            try:
                license_text = license_destination.read_text(
                    encoding="utf-8",
                    errors="strict",
                )
            except UnicodeError as error:
                raise CudaRuntimeError(
                    f"La licencia incluida en {package.name} "
                    "no es texto UTF-8 válido."
                ) from error
            if "NVIDIA" not in license_text or "license" not in license_text.lower():
                raise CudaRuntimeError(
                    f"No se pudo reconocer la licencia incluida en {package.name}."
                )
            extracted.append(
                {
                    "name": package.license_filename,
                    "sizeBytes": license_destination.stat().st_size,
                    "sha256": license_digest.hexdigest(),
                    "package": package.name,
                    "kind": "license",
                }
            )
    return extracted


def _atomic_activate(staging: Path, target: Path, backup: Path) -> None:
    moved_existing = False
    try:
        if target.exists():
            os.replace(target, backup)
            moved_existing = True
        os.replace(staging, target)
        if not _managed_runtime_integrity(target):
            raise CudaRuntimeError(
                "El backend activado no supera la verificación final."
            )
    except (OSError, CudaRuntimeError):
        if target.exists():
            shutil.rmtree(target, ignore_errors=True)
        if moved_existing and backup.exists():
            os.replace(backup, target)
        raise
    if backup.exists():
        shutil.rmtree(backup, ignore_errors=True)


def preload_cuda_backend() -> dict[str, Any]:
    """Preload the optional GPU backend from verified absolute paths only.

    The official CTranslate2 Windows wheel contains a GPU-enabled
    ``ctranslate2.dll``. Its Python extension is deliberately *not* installed:
    the bundled, same-version extension binds to the preloaded DLL. Once any
    CTranslate2 module/DLL is already present in the process, Windows cannot
    safely replace that module, so the result explicitly requires a restart.
    """
    global _GPU_BACKEND_ACTIVATION, _GPU_BACKEND_PRELOADED

    with _PRELOAD_LOCK:
        if _GPU_BACKEND_PRELOADED and _GPU_BACKEND_ACTIVATION is not None:
            # The verified DLLs are already mapped into this process. Rehashing
            # the almost 2 GiB runtime for every queued transcription only
            # rereads files that Windows is already executing.
            return dict(_GPU_BACKEND_ACTIVATION)
        status = get_cuda_runtime_status()
        if not status["ready"]:
            return {
                **status,
                "activated": False,
                "usable": False,
            }
        if _ctranslate2_already_loaded():
            return {
                **status,
                "activated": False,
                "usable": False,
                "restartRequired": True,
                "activationState": "restart-required",
            }
        # get_cuda_runtime_status() performed the complete SHA-256 verification
        # while holding the preload lock. Resolve and load that exact directory
        # without repeating the same multi-gigabyte scan.
        directory = _verified_managed_runtime_directory(
            integrity_already_verified=True
        )
        directory_handle: Any | None = None
        loaded_handles: list[Any] = []
        try:
            if hasattr(os, "add_dll_directory"):
                directory_handle = os.add_dll_directory(str(directory))
            for filename in _PRELOAD_ORDER:
                loaded_handles.append(
                    _load_library_absolute(directory / filename, directory)
                )
        except (OSError, CudaRuntimeError):
            close = getattr(directory_handle, "close", None)
            if callable(close):
                close()
            # Loaded Windows modules cannot be safely unloaded here. We never
            # pretend the backend is usable; the caller surfaces the failure and
            # keeps the already-bundled CPU backend as an explicit choice.
            raise
        if directory_handle is not None:
            _PRELOADED_DIRECTORY_HANDLES.append(directory_handle)
        _PRELOADED_LIBRARY_HANDLES.extend(loaded_handles)
        _GPU_BACKEND_PRELOADED = True
        _GPU_BACKEND_ACTIVATION = {
            **status,
            "activated": True,
            "usable": True,
            "restartRequired": False,
            "activationState": "active",
        }
        return dict(_GPU_BACKEND_ACTIVATION)


def _load_library_absolute(path: Path, expected_parent: Path) -> Any:
    if sys.platform != "win32":
        raise CudaRuntimeError(
            "El backend GPU opcional sólo puede cargarse en Windows."
        )
    try:
        resolved = path.resolve(strict=True)
        parent = expected_parent.resolve(strict=True)
    except OSError as error:
        raise CudaRuntimeError(
            f"No se pudo resolver de forma segura {path.name}."
        ) from error
    if not resolved.is_absolute() or resolved.parent != parent:
        raise CudaRuntimeError(
            f"{path.name} no pertenece al directorio GPU verificado."
        )
    if not _valid_runtime_file(resolved):
        raise CudaRuntimeError(f"{path.name} no es una DLL válida.")
    handle = ctypes.WinDLL(  # type: ignore[attr-defined]
        str(resolved),
        winmode=(
            _LOAD_LIBRARY_SEARCH_DLL_LOAD_DIR
            | _LOAD_LIBRARY_SEARCH_DEFAULT_DIRS
        ),
    )
    loaded_path = _loaded_module_path(int(handle._handle))
    if loaded_path is None or not _same_path(loaded_path, resolved):
        raise CudaRuntimeError(
            f"Windows resolvió {path.name} desde una ubicación no autorizada."
        )
    return handle


def _loaded_module_path(handle: int) -> Path | None:
    if sys.platform != "win32" or not handle:
        return None
    try:
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)  # type: ignore[attr-defined]
        get_module_filename = kernel32.GetModuleFileNameW
        get_module_filename.argtypes = [
            ctypes.c_void_p,
            ctypes.c_wchar_p,
            ctypes.c_uint32,
        ]
        get_module_filename.restype = ctypes.c_uint32
        buffer_size = 32_768
        buffer = ctypes.create_unicode_buffer(buffer_size)
        length = get_module_filename(handle, buffer, buffer_size)
        if length <= 0 or length >= buffer_size:
            return None
        return Path(buffer.value)
    except (AttributeError, OSError, ValueError):
        return None


def _open_download(url: str) -> BinaryIO:
    request = Request(
        url,
        headers={
            "User-Agent": "Transcriptor-CUDA-Manager/1",
            "Accept": "application/octet-stream",
        },
    )
    return urlopen(request, timeout=30)  # noqa: S310 - fixed HTTPS URLs + SHA-256


def _progress(
    phase: str,
    percent: float,
    downloaded_bytes: int,
    total_bytes: int,
    message: str,
    *,
    package: RuntimePackage | RuntimeLegalDocument | None = None,
) -> dict[str, Any]:
    return {
        "phase": phase,
        "percent": round(max(0.0, min(100.0, percent)), 2),
        "downloadedBytes": downloaded_bytes,
        "totalBytes": total_bytes,
        "message": message,
        "package": package.name if package else None,
        "version": package.version if package else None,
    }


def _raise_if_cancelled(cancelled: Cancelled) -> None:
    if cancelled():
        raise CudaRuntimeCancelled(
            "Preparación de CUDA cancelada; no se modificó la instalación anterior."
        )


def _validate_package_definition(
    packages: tuple[RuntimePackage, ...],
    legal_documents: tuple[RuntimeLegalDocument, ...],
) -> None:
    files = [filename for package in packages for filename in package.files]
    if set(files) != set(CUDA_RUNTIME_FILES) or len(files) != len(CUDA_RUNTIME_FILES):
        raise ValueError("El catálogo CUDA no define exactamente las bibliotecas permitidas.")
    for package in packages:
        if (
            not package.url.startswith("https://files.pythonhosted.org/")
            or len(package.sha256) != 64
            or package.size <= 0
            or (
                package.license_path is not None
                and Path(package.license_path).name.lower() != "license.txt"
            )
            or (
                package.license_filename is not None
                and Path(package.license_filename).name != package.license_filename
            )
            or ((package.license_path is None) != (package.license_filename is None))
        ):
            raise ValueError(f"El catálogo de {package.name} no es válido.")
    wheel_license_files = [
        package.license_filename
        for package in packages
        if package.license_filename is not None
    ]
    document_license_files = [document.filename for document in legal_documents]
    license_files = wheel_license_files + document_license_files
    if (
        set(license_files) != set(CUDA_LICENSE_FILES)
        or len(license_files) != len(CUDA_LICENSE_FILES)
    ):
        raise ValueError("El catálogo CUDA no define exactamente sus licencias.")
    for document in legal_documents:
        if (
            not document.url.startswith(
                (
                    "https://raw.githubusercontent.com/OpenNMT/CTranslate2/",
                    "https://raw.githubusercontent.com/uxlfoundation/oneDNN/",
                    "https://cdrdv2.intel.com/",
                    "https://files.pythonhosted.org/",
                )
            )
            or len(document.sha256) != 64
            or document.size <= 0
            or Path(document.filename).name != document.filename
            or document.media_type not in {"text/plain", "application/pdf"}
            or document.encoding not in {"utf-8", "cp1252"}
            or (
                document.encoding == "cp1252"
                and document.filename != "Intel-OpenMP-EULA.txt"
            )
            or (
                document.archive_path is not None
                and (
                    not document.content_sha256
                    or len(document.content_sha256) != 64
                    or not document.content_size
                    or document.content_size <= 0
                    or document.archive_path.startswith(("/", "\\"))
                    or ".." in Path(document.archive_path).parts
                )
            )
            or (
                document.archive_path is None
                and (
                    document.content_sha256 is not None
                    or document.content_size is not None
                )
            )
        ):
            raise ValueError(f"El documento legal {document.name} no es válido.")


def _validate_legal_document(
    document: RuntimeLegalDocument,
    path: Path,
) -> None:
    try:
        if document.media_type == "text/plain":
            text = path.read_text(encoding=document.encoding, errors="strict")
            required_markers = {
                "CTranslate2-MIT.txt": ("MIT License", "The OpenNMT Authors"),
                "NVIDIA-CUDA-Runtime-License.txt": (
                    "End User License Agreement",
                    "NVIDIA",
                ),
                "Intel-OpenMP-EULA.txt": (
                    "Intel End User License Agreement",
                    "Developer Tools",
                ),
                "Intel-OpenMP-Third-Party-Programs.txt": (
                    "OpenMP Runtime library",
                    "Third party programs",
                ),
                "oneDNN-Apache-2.0.txt": (
                    "Apache License",
                    "Version 2.0",
                ),
                "oneDNN-Third-Party-Programs.txt": (
                    "oneDNN",
                    "Third Party Programs",
                ),
            }
            markers = required_markers.get(document.filename)
            if not markers or not all(marker in text for marker in markers):
                raise CudaRuntimeError(
                    f"No se pudo reconocer el documento legal {document.filename}."
                )
            return
        with path.open("rb") as source:
            if source.read(5) != b"%PDF-":
                raise CudaRuntimeError(
                    "La licencia de Intel no es el PDF oficial esperado."
                )
    except UnicodeError as error:
        raise CudaRuntimeError(
            f"{document.filename} no usa la codificación esperada "
            f"({document.encoding})."
        ) from error


def _install_legal_document(
    document: RuntimeLegalDocument,
    source_path: Path,
    destination: Path,
    cancelled: Cancelled,
) -> None:
    if document.archive_path is None:
        with source_path.open("rb") as source, destination.open("xb") as output:
            while True:
                _raise_if_cancelled(cancelled)
                chunk = source.read(_DOWNLOAD_CHUNK_BYTES)
                if not chunk:
                    break
                output.write(chunk)
    else:
        try:
            with zipfile.ZipFile(source_path) as archive:
                info = archive.getinfo(document.archive_path)
                if info.is_dir() or info.file_size != _document_content_size(document):
                    raise CudaRuntimeError(
                        f"{document.name} tiene un tamaño interno inesperado."
                    )
                with archive.open(info) as source, destination.open("xb") as output:
                    while True:
                        _raise_if_cancelled(cancelled)
                        chunk = source.read(_DOWNLOAD_CHUNK_BYTES)
                        if not chunk:
                            break
                        output.write(chunk)
        except KeyError as error:
            raise CudaRuntimeError(
                f"La fuente oficial no contiene {document.archive_path}."
            ) from error
    digest = hashlib.sha256()
    with destination.open("rb") as source:
        while chunk := source.read(_DOWNLOAD_CHUNK_BYTES):
            digest.update(chunk)
    if (
        destination.stat().st_size != _document_content_size(document)
        or digest.hexdigest().lower() != _document_content_sha256(document).lower()
    ):
        raise CudaRuntimeError(
            f"El contenido exacto de {document.name} no coincide."
        )


def _document_content_sha256(document: RuntimeLegalDocument) -> str:
    return document.content_sha256 or document.sha256


def _document_content_size(document: RuntimeLegalDocument) -> int:
    return document.content_size or document.size


def _unique_legal_sources(
    legal_documents: Iterable[RuntimeLegalDocument],
) -> set[tuple[str, str, int]]:
    return {
        (document.url, document.sha256, document.size)
        for document in legal_documents
    }


def _inventory_digest(records: list[dict[str, Any]]) -> str:
    payload = json.dumps(
        records,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _valid_runtime_file(path: Path) -> bool:
    try:
        if not path.is_file() or path.stat().st_size < 64 * 1024:
            return False
        with path.open("rb") as library:
            return library.read(2) == b"MZ"
    except OSError:
        return False


def _directory_nonempty(path: Path) -> bool:
    try:
        return path.is_dir() and next(path.iterdir(), None) is not None
    except OSError:
        return False


def _managed_runtime_integrity(directory: Path) -> bool:
    """Reject a partially written or corrupted managed runtime.

    Wheel hashes are verified before activation. The manifest stores hashes of
    the extracted allowlist so later starts can distinguish a reusable runtime
    from files that were truncated or modified on disk.
    """
    try:
        manifest = json.loads(
            (directory / _MANIFEST_NAME).read_text(encoding="utf-8")
        )
        if manifest.get("schemaVersion") != _MANIFEST_SCHEMA_VERSION:
            return False
        backend = manifest.get("backend")
        if (
            not isinstance(backend, dict)
            or backend.get("id") != "ctranslate2-gpu-optional"
            or backend.get("signPathCovered") is not False
            or backend.get("activation") != "absolute-path-preload"
        ):
            return False
        records = manifest.get("files")
        if not isinstance(records, list):
            return False
        expected_names = set(CUDA_RUNTIME_FILES) | set(CUDA_LICENSE_FILES)
        by_name: dict[str, dict[str, Any]] = {}
        for record in records:
            if not isinstance(record, dict):
                return False
            name = record.get("name")
            if not isinstance(name, str) or name in by_name:
                return False
            by_name[name] = record
        if set(by_name) != expected_names:
            return False
        if manifest.get("inventorySha256") != _inventory_digest(
            sorted(records, key=lambda record: str(record.get("name", "")))
        ):
            return False
        for name, record in by_name.items():
            path = directory / name
            if not path.is_file() or path.stat().st_size != record.get("sizeBytes"):
                return False
            digest = hashlib.sha256()
            with path.open("rb") as source:
                while chunk := source.read(_DOWNLOAD_CHUNK_BYTES):
                    digest.update(chunk)
            if digest.hexdigest().lower() != str(record.get("sha256", "")).lower():
                return False
        return True
    except (OSError, UnicodeError, ValueError, TypeError, json.JSONDecodeError):
        return False


def _prepare_private_runtime_parent(target: Path) -> None:
    expected = preferred_app_data_dir() / "runtime" / "cuda"
    if not _same_path(target, expected):
        raise CudaRuntimeError(
            "La carpeta GPU no pertenece al directorio privado de Transcriptor."
        )
    data_root = preferred_app_data_dir()
    data_root.mkdir(parents=True, exist_ok=True)
    runtime_parent = data_root / "runtime"
    runtime_parent.mkdir(exist_ok=True)
    if data_root.is_symlink() or runtime_parent.is_symlink() or target.is_symlink():
        raise CudaRuntimeError(
            "La carpeta GPU administrada no puede ser un enlace simbólico."
        )
    try:
        if runtime_parent.resolve(strict=True).parent != data_root.resolve(strict=True):
            raise CudaRuntimeError(
                "La carpeta GPU sale del directorio privado de Transcriptor."
            )
    except OSError as error:
        raise CudaRuntimeError(
            "No se pudo verificar la carpeta privada del backend GPU."
        ) from error


def _verified_managed_runtime_directory(
    *, integrity_already_verified: bool = False
) -> Path:
    target = managed_cuda_dir()
    _prepare_private_runtime_parent(target)
    if not integrity_already_verified and not _managed_runtime_integrity(target):
        raise CudaRuntimeError(
            "El backend GPU está incompleto o alguno de sus hashes ha cambiado."
        )
    try:
        resolved = target.resolve(strict=True)
    except OSError as error:
        raise CudaRuntimeError(
            "No se pudo resolver la carpeta del backend GPU."
        ) from error
    if resolved.parent != (preferred_app_data_dir() / "runtime").resolve(strict=True):
        raise CudaRuntimeError(
            "La carpeta del backend GPU no está en el directorio administrado."
        )
    return resolved


def _ctranslate2_already_loaded() -> bool:
    if any(
        module == "ctranslate2" or module.startswith("ctranslate2.")
        for module in sys.modules
    ):
        return True
    if sys.platform != "win32":
        return False
    try:
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)  # type: ignore[attr-defined]
        get_module_handle = kernel32.GetModuleHandleW
        get_module_handle.argtypes = [ctypes.c_wchar_p]
        get_module_handle.restype = ctypes.c_void_p
        return bool(get_module_handle("ctranslate2.dll"))
    except (AttributeError, OSError):
        return False


def _same_path(left: Path, right: Path) -> bool:
    return os.path.normcase(os.path.abspath(left)) == os.path.normcase(os.path.abspath(right))


def _runtime_supported() -> bool:
    architecture = platform.machine().lower()
    return sys.platform == "win32" and architecture in {"amd64", "x86_64"}
