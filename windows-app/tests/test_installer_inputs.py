from __future__ import annotations

import importlib.util
import io
import shutil
import subprocess
import tarfile
import tomllib
import urllib.error
from pathlib import Path

import pytest

APP_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = APP_ROOT.parent
SCRIPTS_DIR = APP_ROOT / "scripts"


def load_download_model_module():
    spec = importlib.util.spec_from_file_location(
        "download_model", SCRIPTS_DIR / "download-model.py"
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class FakeResponse:
    def __init__(self, payload: bytes, status: int = 200, headers: dict[str, str] | None = None):
        self._payload = io.BytesIO(payload)
        self.status = status
        self.headers = headers or {"Content-Length": str(len(payload))}

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def getcode(self) -> int:
        return self.status

    def read(self, size: int = -1) -> bytes:
        return self._payload.read(size)


def make_model_archive(tmp_path: Path) -> Path:
    archive_path = tmp_path / "model.tar.bz2"
    with tarfile.open(archive_path, "w:bz2") as archive:
        for name, payload in {
            "sense/model.int8.onnx": b"fake model",
            "sense/tokens.txt": b"<blank>\nhello\n",
        }.items():
            data = io.BytesIO(payload)
            info = tarfile.TarInfo(name)
            info.size = len(payload)
            archive.addfile(info, data)
    return archive_path


def test_download_model_retries_on_503(tmp_path):
    module = load_download_model_module()
    archive = make_model_archive(tmp_path)
    payload = archive.read_bytes()
    digest = module.hashlib.sha256(payload).hexdigest()
    calls = 0

    def fake_urlopen(request, timeout):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise urllib.error.HTTPError(request.full_url, 503, "Service Unavailable", {}, None)
        return FakeResponse(payload)

    destination = tmp_path / "downloaded.tar.bz2"
    result = module.download_archive(
        url="https://example.invalid/model.tar.bz2",
        destination=destination,
        expected_sha256=digest,
        expected_size=len(payload),
        urlopen=fake_urlopen,
        retries=2,
    )

    assert result == destination
    assert destination.read_bytes() == payload
    assert calls == 2
    assert not destination.with_suffix(".bz2.part").exists()


def test_download_model_extracts_required_files(tmp_path):
    module = load_download_model_module()
    archive = make_model_archive(tmp_path)
    target = tmp_path / "model"

    module.extract_model_files(archive, target)

    assert (target / "model.int8.onnx").read_bytes() == b"fake model"
    assert (target / "tokens.txt").read_text() == "<blank>\nhello\n"


def test_installer_filename_carries_pyproject_minor_version():
    pyproject = tomllib.loads((APP_ROOT / "pyproject.toml").read_text())
    version = pyproject["project"]["version"]
    major_minor = ".".join(version.split(".")[:2])
    nsis = (SCRIPTS_DIR / "make-installer.nsi").read_text()

    assert f'!define APP_VERSION "{version}"' in nsis
    assert f'!define APP_VERSION_SHORT "{major_minor}"' in nsis
    assert "polyvoice-installer-v${APP_VERSION_SHORT}.exe" in nsis


def test_ci_build_fails_cleanly_when_python_embed_url_unavailable(tmp_path):
    pwsh = shutil.which("pwsh")
    if pwsh is None:
        pytest.skip("PowerShell 7 is not installed in this environment")

    bad_url = "http://127.0.0.1:9/python-3.12.10-embed-amd64.zip"
    result = subprocess.run(
        [
            pwsh,
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(SCRIPTS_DIR / "ci-build.ps1"),
            "-PythonZipUrl",
            bad_url,
            "-PythonSpdxUrl",
            bad_url + ".spdx.json",
        ],
        cwd=APP_ROOT,
        text=True,
        capture_output=True,
        timeout=60,
        check=False,
    )

    combined = result.stdout + result.stderr
    assert result.returncode != 0
    assert "build-embeddable.ps1 failed" in combined or "connection" in combined.lower()
