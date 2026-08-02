from __future__ import annotations

import hashlib
import io
import tomllib
import zipfile
from pathlib import Path

import pytest

import transcriptor_engine.cuda_runtime as cuda_runtime
from transcriptor_engine.cuda_runtime import (
    CudaRuntimeCancelled,
    CudaRuntimeError,
    RuntimeLegalDocument,
    RuntimePackage,
    get_cuda_runtime_status,
    install_cuda_runtime,
    preload_cuda_backend,
)


def _wheel(
    files: tuple[str, ...],
    license_path: str | None,
    *,
    ctranslate2: bool = False,
) -> bytes:
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for filename in files:
            package = (
                "ctranslate2"
                if ctranslate2
                else "cublas"
                if filename.startswith("cublas")
                else "cudnn"
            )
            archive.writestr(
                (
                    f"ctranslate2/{filename}"
                    if ctranslate2
                    else f"nvidia/{package}/bin/{filename}"
                ),
                b"MZ" + bytes([len(filename)]) * (64 * 1024),
            )
        if ctranslate2:
            # Both entries are present in the official wheel but are forbidden
            # in the optional runtime: CUDA comes from the pinned NVIDIA wheel
            # and the Python extension remains bundled with the OSS installer.
            archive.writestr(
                "ctranslate2/cudnn64_9.dll",
                b"MZ" + b"forbidden-shim" * 6_000,
            )
            archive.writestr(
                "ctranslate2/_ext.cp312-win_amd64.pyd",
                b"MZ" + b"forbidden-extension" * 4_000,
            )
        archive.writestr("nvidia/unrelated/bin/not-allowed.dll", b"MZ" + b"x" * 70_000)
        if license_path:
            archive.writestr(
                license_path,
                "NVIDIA test license\n" + ("terms\n" * 300),
            )
    return output.getvalue()


def _packages() -> tuple[
    tuple[RuntimePackage, ...],
    tuple[RuntimeLegalDocument, ...],
    dict[str, bytes],
]:
    definitions = (
        (
            "cublas",
            tuple(
                filename
                for filename in cuda_runtime.CUDA_RUNTIME_FILES
                if filename.startswith("cublas")
            ),
        ),
        (
            "cuda-nvrtc",
            tuple(
                filename
                for filename in cuda_runtime.CUDA_RUNTIME_FILES
                if filename.startswith("nvrtc")
            ),
        ),
        (
            "cudnn",
            tuple(
                filename
                for filename in cuda_runtime.CUDA_RUNTIME_FILES
                if filename.startswith("cudnn")
            ),
        ),
        (
            "ctranslate2",
            cuda_runtime.CTRANSLATE2_GPU_FILES,
        ),
    )
    packages = []
    downloads = {}
    for name, files in definitions:
        license_path = (
            None
            if name == "ctranslate2"
            else f"nvidia_{name}_cu12-1.0.0.dist-info/licenses/License.txt"
        )
        content = _wheel(
            files,
            license_path,
            ctranslate2=name == "ctranslate2",
        )
        url = f"https://files.pythonhosted.org/test/{name}.whl"
        packages.append(
            RuntimePackage(
                name=(
                    "ctranslate2"
                    if name == "ctranslate2"
                    else f"nvidia-{name}-cu12"
                ),
                version="1.0.0",
                url=url,
                sha256=hashlib.sha256(content).hexdigest(),
                size=len(content),
                files=files,
                license_path=license_path,
                license_filename=(
                    None
                    if name == "ctranslate2"
                    else (
                        "NVIDIA-cuBLAS-License.txt"
                        if name == "cublas"
                        else (
                            "NVIDIA-CUDA-NVRTC-License.txt"
                            if name == "cuda-nvrtc"
                            else "NVIDIA-cuDNN-License.txt"
                        )
                    )
                ),
            )
        )
        downloads[url] = content
    ctranslate2_license = (
        "MIT License\nThe OpenNMT Authors\n" + ("permission\n" * 200)
    ).encode()
    intel_license = b"%PDF-1.7\n" + b"Intel license terms\n" * 100
    nvidia_runtime_license = (
        "End User License Agreement\nNVIDIA\n" + ("terms\n" * 200)
    ).encode()
    nvidia_legal_archive_io = io.BytesIO()
    with zipfile.ZipFile(nvidia_legal_archive_io, "w") as archive:
        archive.writestr(
            "nvidia_cuda_runtime_cu12-12.8.90.dist-info/License.txt",
            nvidia_runtime_license,
        )
    nvidia_legal_archive = nvidia_legal_archive_io.getvalue()

    intel_openmp_eula = (
        "Intel End User License Agreement for Developer Tools\n"
        + ("terms – conditions\n" * 200)
    ).encode("cp1252")
    intel_openmp_notices = (
        "OpenMP Runtime library\nThird party programs\n" + ("notice\n" * 200)
    ).encode()
    intel_legal_archive_io = io.BytesIO()
    with zipfile.ZipFile(intel_legal_archive_io, "w") as archive:
        archive.writestr(
            "intel_openmp-2025.3.0.dist-info/LICENSE.txt",
            intel_openmp_eula,
        )
        archive.writestr(
            "intel_openmp-2025.3.0.data/data/share/doc/compiler/"
            "licensing/openmp/third-party-programs.txt",
            intel_openmp_notices,
        )
    intel_legal_archive = intel_legal_archive_io.getvalue()
    onednn_license = (
        "Apache License\nVersion 2.0\n" + ("terms\n" * 200)
    ).encode()
    onednn_notices = (
        "oneDNN Third Party Programs\n" + ("notice\n" * 200)
    ).encode()

    documents = (
        RuntimeLegalDocument(
            name="CTranslate2 MIT license",
            version="4.8.1",
            url=(
                "https://raw.githubusercontent.com/OpenNMT/"
                "CTranslate2/v4.8.1/LICENSE"
            ),
            sha256=hashlib.sha256(ctranslate2_license).hexdigest(),
            size=len(ctranslate2_license),
            filename="CTranslate2-MIT.txt",
            media_type="text/plain",
        ),
        RuntimeLegalDocument(
            name="Intel Simplified Software License",
            version="October 2022",
            url="https://cdrdv2.intel.com/v1/dl/getContent/749362",
            sha256=hashlib.sha256(intel_license).hexdigest(),
            size=len(intel_license),
            filename="Intel-Simplified-Software-License.pdf",
            media_type="application/pdf",
        ),
        RuntimeLegalDocument(
            name="NVIDIA CUDA Runtime license",
            version="12.8.90",
            url="https://files.pythonhosted.org/test/nvidia-runtime.whl",
            sha256=hashlib.sha256(nvidia_legal_archive).hexdigest(),
            size=len(nvidia_legal_archive),
            filename="NVIDIA-CUDA-Runtime-License.txt",
            media_type="text/plain",
            archive_path=(
                "nvidia_cuda_runtime_cu12-12.8.90.dist-info/License.txt"
            ),
            content_sha256=hashlib.sha256(nvidia_runtime_license).hexdigest(),
            content_size=len(nvidia_runtime_license),
        ),
        RuntimeLegalDocument(
            name="Intel OpenMP EULA",
            version="2025.3.0",
            url="https://files.pythonhosted.org/test/intel-openmp.whl",
            sha256=hashlib.sha256(intel_legal_archive).hexdigest(),
            size=len(intel_legal_archive),
            filename="Intel-OpenMP-EULA.txt",
            media_type="text/plain",
            archive_path="intel_openmp-2025.3.0.dist-info/LICENSE.txt",
            content_sha256=hashlib.sha256(intel_openmp_eula).hexdigest(),
            content_size=len(intel_openmp_eula),
            encoding="cp1252",
        ),
        RuntimeLegalDocument(
            name="Intel OpenMP third-party programs",
            version="2025.3.0",
            url="https://files.pythonhosted.org/test/intel-openmp.whl",
            sha256=hashlib.sha256(intel_legal_archive).hexdigest(),
            size=len(intel_legal_archive),
            filename="Intel-OpenMP-Third-Party-Programs.txt",
            media_type="text/plain",
            archive_path=(
                "intel_openmp-2025.3.0.data/data/share/doc/compiler/"
                "licensing/openmp/third-party-programs.txt"
            ),
            content_sha256=hashlib.sha256(intel_openmp_notices).hexdigest(),
            content_size=len(intel_openmp_notices),
        ),
        RuntimeLegalDocument(
            name="oneDNN Apache 2.0 license",
            version="3.1.1",
            url=(
                "https://raw.githubusercontent.com/uxlfoundation/"
                "oneDNN/commit/LICENSE"
            ),
            sha256=hashlib.sha256(onednn_license).hexdigest(),
            size=len(onednn_license),
            filename="oneDNN-Apache-2.0.txt",
            media_type="text/plain",
        ),
        RuntimeLegalDocument(
            name="oneDNN third-party programs",
            version="3.1.1",
            url=(
                "https://raw.githubusercontent.com/uxlfoundation/"
                "oneDNN/commit/THIRD-PARTY-PROGRAMS"
            ),
            sha256=hashlib.sha256(onednn_notices).hexdigest(),
            size=len(onednn_notices),
            filename="oneDNN-Third-Party-Programs.txt",
            media_type="text/plain",
        ),
    )
    downloads[documents[0].url] = ctranslate2_license
    downloads[documents[1].url] = intel_license
    downloads[documents[2].url] = nvidia_legal_archive
    downloads[documents[3].url] = intel_legal_archive
    downloads[documents[5].url] = onednn_license
    downloads[documents[6].url] = onednn_notices
    return tuple(packages), documents, downloads


def _configure_test_runtime(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> Path:
    data_root = tmp_path / "TranscriptorData"
    target = data_root / "runtime" / "cuda"
    monkeypatch.setattr(cuda_runtime, "_runtime_supported", lambda: True)
    monkeypatch.setattr(cuda_runtime, "preferred_app_data_dir", lambda: data_root)
    monkeypatch.setattr(cuda_runtime, "_GPU_BACKEND_PRELOADED", False)
    return target


def test_cuda_catalog_matches_the_windows_wheels_pinned_in_uv_lock() -> None:
    packages = {package.name: package for package in cuda_runtime.CUDA_PACKAGES}
    lock = tomllib.loads(
        (Path(__file__).resolve().parents[1] / "uv.lock").read_text(encoding="utf-8")
    )
    locked = {
        package["name"]: package
        for package in lock["package"]
        if package["name"] in packages
    }

    assert packages["nvidia-cublas-cu12"].version == "12.9.2.10"
    assert packages["nvidia-cublas-cu12"].size == 553_162_896
    assert packages["nvidia-cublas-cu12"].sha256 == (
        "623f43027d40d44ceadf0043f002bd25cf353e8f13ce90b9a87057019f560661"
    )
    assert packages["nvidia-cublas-cu12"].license_path == (
        "nvidia_cublas_cu12-12.9.2.10.dist-info/licenses/License.txt"
    )
    assert packages["nvidia-cudnn-cu12"].version == "9.25.0.15"
    assert packages["nvidia-cudnn-cu12"].size == 732_268_748
    assert packages["nvidia-cudnn-cu12"].sha256 == (
        "7987acb3cc5b793151e64c05a12a3625f5a8d4cfabe87eea3a65f0676ef2da67"
    )
    assert packages["nvidia-cudnn-cu12"].license_path == (
        "nvidia_cudnn_cu12-9.25.0.15.dist-info/licenses/License.txt"
    )
    assert packages["nvidia-cuda-nvrtc-cu12"].version == "12.9.86"
    assert packages["nvidia-cuda-nvrtc-cu12"].size == 76_408_187
    assert packages["nvidia-cuda-nvrtc-cu12"].sha256 == (
        "72972ebdcf504d69462d3bcd67e7b81edd25d0fb85a2c46d3ea3517666636349"
    )
    assert packages["nvidia-cuda-nvrtc-cu12"].license_path == (
        "nvidia_cuda_nvrtc_cu12-12.9.86.dist-info/licenses/License.txt"
    )
    assert packages["ctranslate2"].version == "4.8.1"
    assert packages["ctranslate2"].size == 19_220_789
    assert packages["ctranslate2"].sha256 == (
        "49f96e861b57301f0b76a082109bde2cac8204a6b4fedc870883008271e82251"
    )
    assert packages["ctranslate2"].files == (
        "ctranslate2.dll",
        "libiomp5md.dll",
    )
    assert packages["ctranslate2"].license_path is None
    for name, package in packages.items():
        windows_wheel = next(
            wheel for wheel in locked[name]["wheels"] if "win_amd64" in wheel["url"]
        )
        assert locked[name]["version"] == package.version
        assert windows_wheel["url"] == package.url
        assert windows_wheel["size"] == package.size
        assert windows_wheel["hash"] == f"sha256:{package.sha256}"


def test_cuda_install_verifies_and_activates_only_the_allowlisted_dlls(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    target = _configure_test_runtime(tmp_path, monkeypatch)
    packages, documents, downloads = _packages()
    events: list[dict[str, object]] = []

    status = install_cuda_runtime(
        events.append,
        lambda: False,
        packages=packages,
        legal_documents=documents,
        opener=lambda url: io.BytesIO(downloads[url]),
    )

    assert status["ready"] is True
    assert status["source"] == "managed"
    assert {path.name for path in target.iterdir()} == {
        *cuda_runtime.CUDA_RUNTIME_FILES,
        *cuda_runtime.CUDA_LICENSE_FILES,
        "runtime-manifest.json",
    }
    assert "NVIDIA test license" in (
        target / "NVIDIA-cuBLAS-License.txt"
    ).read_text(encoding="utf-8")
    assert not (target / "_ext.cp312-win_amd64.pyd").exists()
    manifest = cuda_runtime.json.loads(
        (target / "runtime-manifest.json").read_text(encoding="utf-8")
    )
    assert manifest["schemaVersion"] == 2
    assert manifest["backend"]["signPathCovered"] is False
    assert len(manifest["inventorySha256"]) == 64
    cudnn_record = next(
        record for record in manifest["files"] if record["name"] == "cudnn64_9.dll"
    )
    assert cudnn_record["package"] == "nvidia-cudnn-cu12"
    assert [event["percent"] for event in events] == sorted(
        event["percent"] for event in events
    )
    assert events[-1]["percent"] == 100
    assert not list(target.parent.glob(".cuda-*"))


def test_bad_sha_keeps_an_existing_runtime_and_removes_temporary_files(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    target = _configure_test_runtime(tmp_path, monkeypatch)
    target.mkdir(parents=True)
    marker = target / "previous-install.txt"
    marker.write_text("conservar", encoding="utf-8")
    packages, documents, downloads = _packages()
    packages = (
        RuntimePackage(
            **{
                **packages[0].__dict__,
                "sha256": "0" * 64,
            }
        ),
        *packages[1:],
    )

    with pytest.raises(CudaRuntimeError, match="SHA-256"):
        install_cuda_runtime(
            lambda _event: None,
            lambda: False,
            packages=packages,
            legal_documents=documents,
            opener=lambda url: io.BytesIO(downloads[url]),
        )

    assert marker.read_text(encoding="utf-8") == "conservar"
    assert not list(target.parent.glob(".cuda-*"))


def test_managed_runtime_with_a_corrupted_library_is_not_reported_ready(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    target = _configure_test_runtime(tmp_path, monkeypatch)
    packages, documents, downloads = _packages()
    install_cuda_runtime(
        lambda _event: None,
        lambda: False,
        packages=packages,
        legal_documents=documents,
        opener=lambda url: io.BytesIO(downloads[url]),
    )

    corrupted = target / "cudnn64_9.dll"
    corrupted.write_bytes(b"MZ" + b"z" * (corrupted.stat().st_size - 2))

    status = get_cuda_runtime_status()

    assert status["ready"] is False
    assert status["source"] == "missing"


def test_missing_static_dependency_notice_fails_closed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    target = _configure_test_runtime(tmp_path, monkeypatch)
    packages, documents, downloads = _packages()
    install_cuda_runtime(
        lambda _event: None,
        lambda: False,
        packages=packages,
        legal_documents=documents,
        opener=lambda url: io.BytesIO(downloads[url]),
    )

    (target / "oneDNN-Third-Party-Programs.txt").unlink()

    status = get_cuda_runtime_status()
    assert status["ready"] is False
    assert status["activationState"] == "corrupt"
    assert "oneDNN-Third-Party-Programs.txt" in status["missingFiles"]


def test_cancelled_download_never_replaces_the_previous_runtime(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    target = _configure_test_runtime(tmp_path, monkeypatch)
    target.mkdir(parents=True)
    marker = target / "previous-install.txt"
    marker.write_text("conservar", encoding="utf-8")
    packages, documents, downloads = _packages()
    checks = 0

    def cancelled() -> bool:
        nonlocal checks
        checks += 1
        return checks >= 3

    with pytest.raises(CudaRuntimeCancelled):
        install_cuda_runtime(
            lambda _event: None,
            cancelled,
            packages=packages,
            legal_documents=documents,
            opener=lambda url: io.BytesIO(downloads[url]),
        )

    assert marker.read_text(encoding="utf-8") == "conservar"
    assert not list(target.parent.glob(".cuda-*"))


def test_status_rejects_a_previous_uninventoried_bundled_runtime(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    data_root = tmp_path / "TranscriptorData"
    managed = data_root / "runtime" / "cuda"
    bundled = tmp_path / "old-install" / "cuda"
    bundled.mkdir(parents=True)
    for filename in cuda_runtime.CUDA_RUNTIME_FILES:
        (bundled / filename).write_bytes(b"MZ" + b"x" * (64 * 1024))
    monkeypatch.setattr(cuda_runtime, "_runtime_supported", lambda: True)
    monkeypatch.setattr(cuda_runtime, "preferred_app_data_dir", lambda: data_root)
    monkeypatch.setenv("TRANSCRIPTOR_CUDA_DIR", str(bundled))
    monkeypatch.setattr(
        cuda_runtime,
        "cuda_library_groups",
        lambda: [
            ("managed", (managed,)),
            ("bundled-legacy", (bundled,)),
        ],
    )

    status = get_cuda_runtime_status()

    assert status["ready"] is False
    assert status["source"] == "missing"
    assert status["signPathCovered"] is False


def test_status_never_combines_cuda_libraries_from_unrelated_groups(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    first = tmp_path / "first"
    second = tmp_path / "second"
    first.mkdir()
    second.mkdir()
    for filename in ("cublas64_12.dll", "cublasLt64_12.dll"):
        (first / filename).write_bytes(b"MZ" + b"x" * (64 * 1024))
    (second / "cudnn64_9.dll").write_bytes(b"MZ" + b"x" * (64 * 1024))
    monkeypatch.setattr(cuda_runtime, "_runtime_supported", lambda: True)
    monkeypatch.setattr(
        cuda_runtime,
        "cuda_library_groups",
        lambda: [
            ("legacy", (first,)),
            ("legacy", (second,)),
        ],
    )
    monkeypatch.setattr(
        cuda_runtime,
        "preferred_app_data_dir",
        lambda: tmp_path / "TranscriptorData",
    )

    status = get_cuda_runtime_status()

    assert status["ready"] is False
    assert status["source"] == "missing"


def test_legal_document_catalog_is_exact_and_pinned() -> None:
    documents = {
        document.filename: document
        for document in cuda_runtime.CUDA_LEGAL_DOCUMENTS
    }

    assert documents["CTranslate2-MIT.txt"].url == (
        "https://raw.githubusercontent.com/OpenNMT/CTranslate2/v4.8.1/LICENSE"
    )
    assert documents["CTranslate2-MIT.txt"].size == 1_115
    assert documents["CTranslate2-MIT.txt"].sha256 == (
        "54aa79d9fe3c09e67a16dcd95b9e88676405a6ec174efda31036983cf7672ecb"
    )
    assert documents["Intel-Simplified-Software-License.pdf"].url == (
        "https://cdrdv2.intel.com/v1/dl/getContent/749362"
    )
    assert documents["Intel-Simplified-Software-License.pdf"].size == 70_926
    assert documents["Intel-Simplified-Software-License.pdf"].sha256 == (
        "cb199f4ed41d96df26f653bf2ac6d5a5c81be739334ca93df027bea74bc963a3"
    )
    assert set(documents) == {
        "CTranslate2-MIT.txt",
        "Intel-Simplified-Software-License.pdf",
        "NVIDIA-CUDA-Runtime-License.txt",
        "Intel-OpenMP-EULA.txt",
        "Intel-OpenMP-Third-Party-Programs.txt",
        "oneDNN-Apache-2.0.txt",
        "oneDNN-Third-Party-Programs.txt",
    }
    assert documents["NVIDIA-CUDA-Runtime-License.txt"].content_sha256 == (
        "ad6f5853fba0ca0d159d0f58d49ae49830c2f8c93f7a92648b9ce90adb4c6ccd"
    )
    assert documents["Intel-OpenMP-EULA.txt"].content_sha256 == (
        "febfb69a5b058f55892dc7f341108a9ca29d50e9fe85723a57eebbb826436958"
    )
    assert documents["Intel-OpenMP-EULA.txt"].encoding == "cp1252"
    assert documents["Intel-OpenMP-Third-Party-Programs.txt"].content_sha256 == (
        "f8ce918fe7311ce279e68380a2e233f8a42b1cd3dda8f4c48d6de97a0255c1d7"
    )
    assert documents["oneDNN-Apache-2.0.txt"].sha256 == (
        "dd12452e1ae11e3282271aa5895d8175296b83e936a027209f9399d26a407d0f"
    )
    assert documents["oneDNN-Third-Party-Programs.txt"].sha256.lower() == (
        "9117585dfc6b5cd0fafc063312f28a86ec82eb97bf68316dcefcaAA7fc11428e"
    ).lower()


def test_preload_uses_verified_absolute_paths_without_mutating_path(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    target = _configure_test_runtime(tmp_path, monkeypatch)
    packages, documents, downloads = _packages()
    install_cuda_runtime(
        lambda _event: None,
        lambda: False,
        packages=packages,
        legal_documents=documents,
        opener=lambda url: io.BytesIO(downloads[url]),
    )
    loaded: list[tuple[Path, Path]] = []
    old_path = cuda_runtime.os.environ.get("PATH")
    monkeypatch.setattr(cuda_runtime, "_ctranslate2_already_loaded", lambda: False)
    monkeypatch.setattr(
        cuda_runtime,
        "_load_library_absolute",
        lambda path, parent: loaded.append((path, parent)) or object(),
    )
    monkeypatch.setattr(cuda_runtime, "_PRELOADED_LIBRARY_HANDLES", [])
    monkeypatch.setattr(cuda_runtime, "_PRELOADED_DIRECTORY_HANDLES", [])
    monkeypatch.setattr(cuda_runtime, "_GPU_BACKEND_PRELOADED", False)

    status = preload_cuda_backend()

    assert status["activated"] is True
    assert status["restartRequired"] is False
    assert [path.name for path, _parent in loaded] == list(
        cuda_runtime._PRELOAD_ORDER
    )
    assert all(path.is_absolute() and parent == target for path, parent in loaded)
    assert cuda_runtime.os.environ.get("PATH") == old_path


def test_loaded_cpu_backend_requires_restart_instead_of_fake_activation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _configure_test_runtime(tmp_path, monkeypatch)
    packages, documents, downloads = _packages()
    install_cuda_runtime(
        lambda _event: None,
        lambda: False,
        packages=packages,
        legal_documents=documents,
        opener=lambda url: io.BytesIO(downloads[url]),
    )
    monkeypatch.setattr(cuda_runtime, "_ctranslate2_already_loaded", lambda: True)
    monkeypatch.setattr(cuda_runtime, "_GPU_BACKEND_PRELOADED", False)
    monkeypatch.setattr(
        cuda_runtime,
        "_load_library_absolute",
        lambda *_args: pytest.fail("No debe cargar DLLs sobre CT2 ya activo"),
    )

    status = preload_cuda_backend()

    assert status["ready"] is True
    assert status["activated"] is False
    assert status["usable"] is False
    assert status["restartRequired"] is True
    assert status["activationState"] == "restart-required"
