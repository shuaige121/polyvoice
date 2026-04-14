from __future__ import annotations

import argparse
import hashlib
import shutil
import sys
import tarfile
import time
import urllib.error
import urllib.request
from collections.abc import Callable
from pathlib import Path

APP_ROOT = Path(__file__).resolve().parents[1]
if str(APP_ROOT) not in sys.path:
    sys.path.insert(0, str(APP_ROOT))

from polyvoice_app import paths  # noqa: E402

MODEL_DIR_NAME = "sense-voice-zh-en-ja-ko-yue-2024-07-17"
ARCHIVE_NAME = "sherpa-onnx-sense-voice-zh-en-ja-ko-yue-int8-2024-07-17.tar.bz2"
MODEL_URL = (
    "https://github.com/k2-fsa/sherpa-onnx/releases/download/asr-models/"
    "sherpa-onnx-sense-voice-zh-en-ja-ko-yue-int8-2024-07-17.tar.bz2"
)
MODEL_SHA256 = "7d1efa2138a65b0b488df37f8b89e3d91a60676e416f515b952358d83dfd347e"
MODEL_SIZE_BYTES = 163_002_883
RETRY_STATUSES = {429, 500, 502, 503, 504}
ProgressCallback = Callable[[int, int | None], None]
UrlOpen = Callable[[urllib.request.Request, float], object]


class DownloadError(RuntimeError):
    pass


def default_download_dir() -> Path:
    return paths.app_dir() / "downloads"


def download_archive(
    *,
    url: str = MODEL_URL,
    destination: Path | None = None,
    expected_sha256: str = MODEL_SHA256,
    expected_size: int | None = MODEL_SIZE_BYTES,
    progress: ProgressCallback | None = None,
    urlopen: UrlOpen = urllib.request.urlopen,
    retries: int = 3,
    timeout: float = 30,
) -> Path:
    destination = destination or default_download_dir() / ARCHIVE_NAME
    destination.parent.mkdir(parents=True, exist_ok=True)
    part_path = destination.with_suffix(destination.suffix + ".part")

    if destination.exists():
        verify_sha256(destination, expected_sha256)
        if progress:
            progress(destination.stat().st_size, destination.stat().st_size)
        return destination

    attempt = 0
    while True:
        try:
            _download_once(
                url=url,
                destination=destination,
                part_path=part_path,
                expected_sha256=expected_sha256,
                expected_size=expected_size,
                progress=progress,
                urlopen=urlopen,
                timeout=timeout,
            )
            return destination
        except urllib.error.HTTPError as exc:
            attempt += 1
            if exc.code not in RETRY_STATUSES or attempt > retries:
                raise DownloadError(f"download failed with HTTP {exc.code}: {exc.reason}") from exc
            time.sleep(min(2**attempt, 10))
        except urllib.error.URLError as exc:
            attempt += 1
            if attempt > retries:
                raise DownloadError(f"download failed: {exc.reason}") from exc
            time.sleep(min(2**attempt, 10))


def _download_once(
    *,
    url: str,
    destination: Path,
    part_path: Path,
    expected_sha256: str,
    expected_size: int | None,
    progress: ProgressCallback | None,
    urlopen: UrlOpen,
    timeout: float,
) -> None:
    resume_from = part_path.stat().st_size if part_path.exists() else 0
    headers = {"User-Agent": "polyvoice-windows-model-downloader/0.1"}
    if resume_from:
        headers["Range"] = f"bytes={resume_from}-"
    request = urllib.request.Request(url, headers=headers)

    with urlopen(request, timeout=timeout) as response:
        status = getattr(response, "status", response.getcode())
        if resume_from and status == 200:
            part_path.unlink(missing_ok=True)
            resume_from = 0
        if status not in {200, 206}:
            raise DownloadError(f"download failed with HTTP {status}")

        total = _content_total(response, resume_from, expected_size)
        mode = "ab" if resume_from and status == 206 else "wb"
        done = resume_from if mode == "ab" else 0
        if progress:
            progress(done, total)
        with part_path.open(mode + "") as handle:
            while True:
                chunk = response.read(1024 * 1024)
                if not chunk:
                    break
                handle.write(chunk)
                done += len(chunk)
                if progress:
                    progress(done, total)

    if expected_size is not None and part_path.stat().st_size != expected_size:
        raise DownloadError(
            f"downloaded size mismatch for {part_path.name}: "
            f"expected {expected_size}, got {part_path.stat().st_size}"
        )
    verify_sha256(part_path, expected_sha256)
    part_path.replace(destination)


def _content_total(response: object, resume_from: int, expected_size: int | None) -> int | None:
    content_range = response.headers.get("Content-Range")
    if content_range and "/" in content_range:
        try:
            return int(content_range.rsplit("/", 1)[1])
        except ValueError:
            pass
    content_length = response.headers.get("Content-Length")
    if content_length:
        try:
            return resume_from + int(content_length)
        except ValueError:
            pass
    return expected_size


def verify_sha256(path: Path, expected_sha256: str) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    actual = digest.hexdigest()
    if actual.lower() != expected_sha256.lower():
        raise DownloadError(f"SHA256 mismatch for {path}: expected {expected_sha256}, got {actual}")
    return actual


def install_model(
    *,
    target_dir: Path | None = None,
    archive_path: Path | None = None,
    progress: ProgressCallback | None = None,
) -> Path:
    target_dir = target_dir or paths.default_model_dir()
    archive_path = archive_path or download_archive(progress=progress)
    target_dir.mkdir(parents=True, exist_ok=True)
    extract_model_files(archive_path, target_dir)
    return target_dir


def extract_model_files(archive_path: Path, target_dir: Path) -> None:
    wanted = {"model.int8.onnx", "tokens.txt"}
    found: set[str] = set()
    target_dir.mkdir(parents=True, exist_ok=True)
    with tarfile.open(archive_path, "r:bz2") as archive:
        for member in archive.getmembers():
            filename = Path(member.name).name
            if filename not in wanted or not member.isfile():
                continue
            source = archive.extractfile(member)
            if source is None:
                continue
            output_path = target_dir / filename
            tmp_path = output_path.with_suffix(output_path.suffix + ".tmp")
            with source, tmp_path.open("wb") as output:
                shutil.copyfileobj(source, output)
            tmp_path.replace(output_path)
            found.add(filename)
    missing = wanted - found
    if missing:
        raise DownloadError(f"archive is missing required model files: {', '.join(sorted(missing))}")


def print_progress(done: int, total: int | None) -> None:
    if total:
        percent = min(done / total * 100, 100)
        print(f"\rDownloading model: {percent:5.1f}% ({done}/{total} bytes)", end="", flush=True)
    else:
        print(f"\rDownloading model: {done} bytes", end="", flush=True)


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Download the polyvoice SenseVoice int8 model.")
    parser.add_argument("--target-dir", type=Path, default=paths.default_model_dir())
    parser.add_argument("--download-dir", type=Path, default=default_download_dir())
    parser.add_argument("--url", default=MODEL_URL)
    parser.add_argument("--sha256", default=MODEL_SHA256)
    parser.add_argument("--no-progress", action="store_true")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv or sys.argv[1:])
    archive_path = args.download_dir / ARCHIVE_NAME
    try:
        archive = download_archive(
            url=args.url,
            destination=archive_path,
            expected_sha256=args.sha256,
            progress=None if args.no_progress else print_progress,
        )
        if not args.no_progress:
            print()
        install_model(target_dir=args.target_dir, archive_path=archive)
    except DownloadError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    print(f"SenseVoice model installed at {args.target_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
