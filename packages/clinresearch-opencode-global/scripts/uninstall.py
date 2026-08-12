#!/usr/bin/env python3
"""Safely remove only files that were installed by the ClinResearch installer."""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sys
from pathlib import Path
from typing import Any


INSTALL_MANIFEST_NAME = "clinresearch-global-install.json"


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def sha256_tree(path: Path) -> str:
    digest = hashlib.sha256()
    for item in sorted(path.rglob("*")):
        if item.is_file():
            digest.update(item.relative_to(path).as_posix().encode("utf-8"))
            digest.update(sha256_file(item).encode("ascii"))
    return digest.hexdigest()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Uninstall ClinResearch Agents from global OpenCode config.")
    parser.add_argument("--config-dir", default=str(Path.home() / ".config" / "opencode"))
    parser.add_argument("--dry-run", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    config_dir = Path(args.config_dir).expanduser().resolve()
    manifest_path = config_dir / INSTALL_MANIFEST_NAME
    if not manifest_path.is_file():
        raise FileNotFoundError(f"Install manifest not found: {manifest_path}")
    manifest: dict[str, Any] = json.loads(manifest_path.read_text(encoding="utf-8"))
    skipped: list[str] = []
    removed: list[str] = []

    def remove_file(path_text: str, expected_hash: str) -> None:
        path = Path(path_text)
        if not path.exists():
            return
        if sha256_file(path) != expected_hash:
            skipped.append(f"modified file: {path}")
            return
        if not args.dry_run:
            path.unlink()
        removed.append(str(path))

    def remove_directory(path_text: str, expected_hash: str) -> None:
        path = Path(path_text)
        if not path.exists():
            return
        if sha256_tree(path) != expected_hash:
            skipped.append(f"modified directory: {path}")
            return
        if not args.dry_run:
            shutil.rmtree(path)
        removed.append(str(path))

    for path_text, expected_hash in manifest.get("installed_files", {}).items():
        remove_file(path_text, expected_hash)
    for path_text, expected_hash in manifest.get("installed_directories", {}).items():
        remove_directory(path_text, expected_hash)

    config_path = Path(manifest["config_path"])
    if config_path.is_file():
        config = json.loads(config_path.read_text(encoding="utf-8"))
        changed = False
        if config.get("mcp", {}).get("literature_review") == manifest.get("mcp"):
            del config["mcp"]["literature_review"]
            changed = True
        for key, value in manifest.get("permissions", {}).items():
            if config.get("permission", {}).get(key) == value:
                del config["permission"][key]
                changed = True
        plugin_uri = manifest.get("plugin_uri")
        if plugin_uri in config.get("plugin", []):
            config["plugin"].remove(plugin_uri)
            changed = True
        if changed and not args.dry_run:
            config_path.write_text(json.dumps(config, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    if not args.dry_run:
        manifest_path.unlink()
    print(f"Removed {len(removed)} ClinResearch files/directories.")
    if skipped:
        print("Skipped modified paths:")
        for item in skipped:
            print(f"- {item}")
    print("Restart OpenCode to reload global configuration.")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (FileNotFoundError, json.JSONDecodeError) as error:
        print(f"Uninstall failed: {error}", file=sys.stderr)
        raise SystemExit(2)
