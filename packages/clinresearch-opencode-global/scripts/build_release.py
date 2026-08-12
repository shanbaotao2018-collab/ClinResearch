#!/usr/bin/env python3
"""Create reproducible ZIP and tar.gz release archives from this source package."""

from __future__ import annotations

import argparse
import hashlib
import json
import tarfile
import zipfile
from pathlib import Path


PACKAGE_ROOT = Path(__file__).resolve().parents[1]
EXCLUDED_PARTS = {"dist", "__pycache__"}
EXCLUDED_FILENAMES = {".DS_Store", ".Rhistory"}


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

    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for path, relative in files:
            archive.write(path, Path(release_name) / relative)
    with tarfile.open(tar_path, "w:gz") as archive:
        for path, relative in files:
            archive.add(path, arcname=str(Path(release_name) / relative), recursive=False)

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
