#!/usr/bin/env python3
"""Create reproducible ZIP and tar.gz release archives from this source package."""

from __future__ import annotations

import argparse
import gzip
import hashlib
import io
import json
import os
import stat
import tarfile
import zipfile
from datetime import UTC, datetime
from pathlib import Path


PACKAGE_ROOT = Path(__file__).resolve().parents[1]
EXCLUDED_PARTS = {"dist", "__pycache__"}
EXCLUDED_FILENAMES = {".DS_Store", ".Rhistory"}
DEFAULT_SOURCE_DATE_EPOCH = 315532800  # 1980-01-01, the earliest ZIP timestamp.


def iter_files():
    for path in sorted(PACKAGE_ROOT.rglob("*")):
        relative = path.relative_to(PACKAGE_ROOT)
        if (
            any(part in EXCLUDED_PARTS for part in relative.parts)
            or path.name in EXCLUDED_FILENAMES
            or not path.is_file()
        ):
            continue
        yield path, relative


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def source_epoch() -> int:
    raw = os.environ.get("SOURCE_DATE_EPOCH", str(DEFAULT_SOURCE_DATE_EPOCH))
    try:
        return max(int(raw), DEFAULT_SOURCE_DATE_EPOCH)
    except ValueError as error:
        raise ValueError("SOURCE_DATE_EPOCH must be an integer Unix timestamp") from error


def archive_mode(path: Path) -> int:
    return 0o755 if path.stat().st_mode & stat.S_IXUSR else 0o644


def write_zip(path: Path, release_name: str, files, epoch: int) -> None:
    timestamp = datetime.fromtimestamp(epoch, tz=UTC).timetuple()[:6]
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for source, relative in files:
            info = zipfile.ZipInfo(str(Path(release_name) / relative), date_time=timestamp)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.create_system = 3
            info.external_attr = archive_mode(source) << 16
            archive.writestr(info, source.read_bytes())


def write_tar_gz(path: Path, release_name: str, files, epoch: int) -> None:
    with path.open("wb") as output:
        with gzip.GzipFile(filename="", mode="wb", fileobj=output, mtime=epoch, compresslevel=9) as zipped:
            with tarfile.open(fileobj=zipped, mode="w", format=tarfile.PAX_FORMAT) as archive:
                for source, relative in files:
                    data = source.read_bytes()
                    info = tarfile.TarInfo(str(Path(release_name) / relative))
                    info.size = len(data)
                    info.mode = archive_mode(source)
                    info.mtime = epoch
                    info.uid = 0
                    info.gid = 0
                    info.uname = "root"
                    info.gname = "root"
                    archive.addfile(info, io.BytesIO(data))


def main() -> int:
    parser = argparse.ArgumentParser(description="Build ClinResearch global OpenCode release archives.")
    parser.add_argument("--output-dir", required=True)
    args = parser.parse_args()
    manifest = json.loads((PACKAGE_ROOT / "manifest.json").read_text(encoding="utf-8"))
    release_name = f"{manifest['name']}-{manifest['version']}"
    output_dir = Path(args.output_dir).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    zip_path = output_dir / f"{release_name}.zip"
    tar_path = output_dir / f"{release_name}.tar.gz"
    checksums_path = output_dir / f"{release_name}.sha256"
    files = list(iter_files())
    epoch = source_epoch()
    write_zip(zip_path, release_name, files, epoch)
    write_tar_gz(tar_path, release_name, files, epoch)

    checksums_path.write_text(
        f"{digest(zip_path)}  {zip_path.name}\n{digest(tar_path)}  {tar_path.name}\n",
        encoding="utf-8",
    )
    print(f"Built {zip_path}")
    print(f"Built {tar_path}")
    print(f"Built {checksums_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
